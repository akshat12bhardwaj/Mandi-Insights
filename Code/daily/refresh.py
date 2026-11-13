"""Bounded, resumable daily-extension ingestion. Default is a download plan only.

Does not mutate the established candidate manifests, raw snapshots or freezes.
Credentials are read by the existing key loader and never logged.
"""
import argparse
from datetime import date, timedelta
import hashlib
import json
import time
import requests
from urllib3.exceptions import HTTPError as TransportError
from Code.candidates.datagov_key_check import BASE, load_key
from Code.candidates.datagov_partition_check import single_call_ok, rid
from .dataset import OUT, ROOT, write_json, sha
from .policy import now_ist

RAW = ROOT / "Dataset_Candidates/daily_v1"
LIMIT = 5000

def validate_pair(first, second, crop, day):
    for body in (first, second):
        if (not isinstance(body, dict) or not isinstance(body.get("records"), list)
                or "total" not in body or isinstance(body["total"], bool)
                or not str(body["total"]).isdigit()):
            raise ValueError("Malformed provider response; explicit total and records required")
        if not single_call_ok(body, LIMIT)["ok"]:
            raise ValueError("Truncated or duplicated commodity-day; narrower approved partitions required")
        for r in body["records"]:
            if r.get("Commodity") != crop or r.get("Arrival_Date") != day.strftime("%d/%m/%Y"):
                raise ValueError("Response did not respect crop/date filters")
            if any(not isinstance(r.get(k),str) or not r[k].strip() for k in ("State", "District", "Market", "Variety", "Grade")):
                raise ValueError("Missing identity fields")
            if any(k not in r for k in ("Modal_Price", "Min_Price", "Max_Price")):
                raise ValueError("Missing price fields")
    a, b = ({rid(r) for r in body["records"]} for body in (first, second))
    if a != b:
        raise ValueError("Repeated commodity-day responses disagree")
    return hashlib.sha256("\n".join(sorted(a)).encode()).hexdigest()

def plan(start, end, crops):
    if start > end or end > now_ist().date():
        raise ValueError("Invalid date range")
    days = (end-start).days+1
    return {"start": str(start), "end": str(end), "crops": crops, "crop_days": days*len(crops),
            "maximum_calls": days*len(crops)*2, "page_limit": LIMIT,
            "order": "newest_first",
            "notes": "Two matching complete responses per crop-day. Existing accepted partitions are skipped. No automatic retries or pagination. Download bytes capped."}

def collect(start, end, crops, budget, byte_budget, fetch=None, recheck=False):
    manifest_path = OUT / "refresh_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"partitions": {}}
    key = load_key(ROOT) if fetch is None else None
    if fetch is None and not key:
        raise ValueError("Missing data.gov.in credential; use DATAGOV_API_KEY or the existing local secrets file")
    scope = {"start":str(start),"end":str(end),"crops":crops,"call_cap":budget,"byte_cap":byte_budget}
    scope_id = hashlib.sha256(json.dumps(scope,sort_keys=True).encode()).hexdigest()[:20]
    usage_path = OUT / "refresh_usage" / f"{scope_id}.json"
    usage = json.loads(usage_path.read_text()) if usage_path.exists() else {
        "scope":scope,"calls_used":0,"bytes_received":0,"last_outcome":"not_started"}
    if usage.get("accounting_incomplete"):
        raise ValueError("Earlier attempt has incomplete usage accounting; a new explicitly approved budget is required")
    verified=usage.setdefault("verified_partitions",{})
    if recheck and usage.get("last_outcome")=="completed":
        return {"calls":0,"bytes":0,"total_calls_used":usage["calls_used"],"total_bytes_received":usage["bytes_received"],
                "accepted_partitions":len(manifest["partitions"]),"status":"scope_already_completed"}
    calls = downloaded = 0
    def save_usage(outcome):
        usage.update(last_outcome=outcome,updated_at=now_ist().isoformat())
        write_json(usage_path,usage)
    def request(crop, day):
        nonlocal calls, downloaded
        if usage["calls_used"] >= budget:
            raise ValueError("Approved request budget exhausted; accepted partitions retained")
        if usage["bytes_received"] >= byte_budget:
            raise ValueError("Approved download byte budget exhausted")
        calls += 1
        usage["calls_used"] += 1
        usage["last_partition"] = {"crop":crop,"date":str(day)}
        save_usage("request_started")  # Failed calls also consume the approved allowance.
        if fetch:
            return fetch(crop, day)
        params = {"api-key": key, "format": "json", "limit": LIMIT, "offset": 0,
                  "filters[Commodity]": crop, "filters[Arrival_Date]": day.strftime("%d/%m/%Y")}
        try:
            # Stream under a hard byte cap; never expose request URLs or exception text.
            with requests.get(BASE, params=params, timeout=(10,40), stream=True,
                              headers={"User-Agent": "curl/8.0"}) as response:
                if response.status_code != 200:
                    save_usage(f"http_{response.status_code}")
                    raise ValueError(f"Provider returned HTTP {response.status_code}; collection stopped")
                parts = []
                while usage["bytes_received"] < byte_budget:
                    # Never request more response bytes than remain in the approved allowance.
                    chunk = response.raw.read(min(65536,byte_budget-usage["bytes_received"]),decode_content=True)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    usage["bytes_received"] += len(chunk)
                    save_usage("receiving_response")
                    parts.append(chunk)
                else:
                    save_usage("byte_cap_reached")
                    raise ValueError("Approved download byte budget exhausted")
                body = json.loads(b"".join(parts))
        except requests.Timeout:
            save_usage("provider_timeout")
            raise ValueError("Provider connection/read timed out; accepted partitions retained") from None
        except (requests.RequestException, TransportError) as exc:
            save_usage(f"network_{type(exc).__name__}")
            raise ValueError(f"Provider network failure ({type(exc).__name__}); accepted partitions retained") from None
        except json.JSONDecodeError:
            save_usage("response_json_invalid")
            raise ValueError("Provider returned an invalid JSON response; accepted partitions retained") from None
        save_usage("response_received")
        time.sleep(.8)
        return body
    for offset in range((end-start).days+1):
        day = end - timedelta(days=offset)
        for crop in crops:
            partition = f"{crop}|{day}"
            saved = manifest["partitions"].get(partition)
            if saved:
                path = ROOT / saved["path"]
                if not path.exists() or sha(path)!=saved["file_sha256"]:
                    raise ValueError("Accepted raw partition is missing or modified; investigate before resuming")
                if not recheck:
                    continue
                if verified.get(partition)==saved["file_sha256"]:
                    continue
            first, second = request(crop,day), request(crop,day)
            try:
                fingerprint = validate_pair(first,second,crop,day)
            except (ValueError,TypeError,AttributeError,KeyError):
                save_usage("partition_validation_failed")
                raise ValueError("Partition validation failed; collection stopped with accepted partitions retained") from None
            stamp = now_ist().isoformat()
            if saved and json.loads((ROOT/saved["path"]).read_text(encoding="utf-8"))["double_fetch_content_sha256"]==fingerprint:
                verified[partition]=saved["file_sha256"]
                save_usage("partition_rechecked_unchanged")
                continue
            raw = RAW / hashlib.sha256(crop.encode()).hexdigest()[:12] / f"{day}-{fingerprint[:12]}.json"
            if raw.exists():
                raw=raw.with_name(raw.stem+"-"+hashlib.sha256(stamp.encode()).hexdigest()[:12]+".json")
            # Retain source observations and retrieval timestamp, omit reflected URLs / keys.
            write_json(raw,{"records":first["records"],"retrieved_at":stamp,"commodity":crop,"date":str(day),
                            "source":BASE,"double_fetch_content_sha256":fingerprint})
            revisions=([*saved.get("revisions",[]),{k:v for k,v in saved.items() if k!="revisions"}] if saved else [])
            manifest["partitions"][partition]={"path":str(raw.relative_to(ROOT)),"file_sha256":sha(raw),"revisions":revisions,
                "crop":crop,"date":str(day),"records":len(first["records"]),"retrieved_at":stamp,
                "status":"accepted" if first["records"] else "empty_report_not_zero_price"}
            write_json(manifest_path,manifest)
            verified[partition]=manifest["partitions"][partition]["file_sha256"]
            save_usage("partition_accepted")
    save_usage("completed")
    return {"calls":calls,"bytes":downloaded,"total_calls_used":usage["calls_used"],"total_bytes_received":usage["bytes_received"],
            "accepted_partitions":len(manifest["partitions"])}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start",type=date.fromisoformat,required=True)
    p.add_argument("--end",type=date.fromisoformat,required=True)
    p.add_argument("--budget",type=int,default=0)
    p.add_argument("--max-mb",type=int,default=100)
    p.add_argument("--execute",action="store_true",help="Actually collect; run only after approving this download plan")
    a=p.parse_args()
    catalog=json.loads((OUT/"catalog.json").read_text(encoding="utf-8"))
    crops=[c["crop"] for c in catalog["crops"]]
    proposal=plan(a.start,a.end,crops)
    print(json.dumps(proposal,indent=2))
    if a.execute:
        if a.budget < 2 or a.max_mb < 1:
            p.error("A positive call and byte budget is required")
        try:
            print(json.dumps(collect(a.start,a.end,crops,a.budget,a.max_mb*1_000_000)))
        except ValueError as exc:
            p.exit(1,str(exc)+"\n")

if __name__=="__main__":
    main()
