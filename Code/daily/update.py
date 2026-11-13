"""Bounded daily refresh + publication. Default is an offline plan, not networking.

Example: python -B -m Code.daily.update --lookback-days 7 --budget 280 --max-mb 50 --execute
No Windows task is installed by this command. Existing research is never invoked.
"""
import argparse
from datetime import timedelta
import json
from . import refresh,operational as op
from .dataset import OUT,write_json,sha
from .policy import now_ist


def run(lookback=7,budget=280,max_mb=50,execute=False,collector=None,catalog_override=None):
    if not 1<=lookback<=365 or budget<2 or max_mb<1:
        raise ValueError("Invalid refresh limits")
    end=now_ist().date()  # Today's actual can be displayed, but never enters today's forecast features.
    start=end-timedelta(days=lookback-1)
    catalog=catalog_override if catalog_override is not None else json.loads((OUT/"catalog.json").read_text(encoding="utf-8"))
    crops=[c["crop"] for c in catalog["crops"]]
    proposal={**refresh.plan(start,end,crops),"call_cap":budget,"byte_cap":max_mb*1000000,"scheduled_execution_active":False}
    proposal["notes"]="Recheck recent dates once per bounded scope for late reports; preserve immutable source vintages. Completed scopes resume without extra calls. No automatic retries or active scheduler."
    if not execute:
        return proposal
    lock=OUT/"update.lock"
    lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open("x",encoding="utf-8") as f:
        f.write(now_ist().isoformat())
    saved={name:(OUT/name).read_bytes() if (OUT/name).exists() else None for name in ("release.json","batch.json")}
    try:
        result=(collector(start,end,crops,budget,max_mb*1000000) if collector else
                refresh.collect(start,end,crops,budget,max_mb*1000000,recheck=True))
        before=json.loads(saved["release.json"]) if saved["release.json"] else None
        dest,manifest=op.release(publish=False, catalog_override=catalog) if catalog_override is not None else op.release(publish=False)
        after={"release":dest.name,"manifest_sha256":sha(dest/"manifest.json")}
        held=json.loads(saved["batch.json"]) if saved["batch.json"] else {}
        current=held.get("target_date")==str(now_ist().date())
        if before!=after or not current:
            op.batch(release_bundle=(dest,manifest))
            write_json(OUT/"release.json",after)
        status={"status":"updated" if before!=after or not current else "unchanged_current_batch",
                "issue_timestamp":now_ist().isoformat(),"collection":result,"scheduled_execution_active":False}
        write_json(OUT/"update_status.json",status)
        return status
    except Exception:
        # Old pointers remain authoritative on any collection/publication failure.
        for name,content in saved.items():
            if content is not None:
                temp=OUT/(name+".restore.tmp");temp.write_bytes(content);temp.replace(OUT/name)
            elif (OUT/name).exists():
                (OUT/name).unlink()
        write_json(OUT/"update_status.json",{"status":"failed_previous_release_retained","issue_timestamp":now_ist().isoformat(),
                                             "reason":"Collection or publication failed; inspect sanitized refresh usage diagnostics.","scheduled_execution_active":False})
        raise
    finally:
        lock.unlink()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-days",type=int,default=7)
    parser.add_argument("--budget",type=int,default=280)
    parser.add_argument("--max-mb",type=int,default=50)
    parser.add_argument("--execute",action="store_true")
    args=parser.parse_args()
    try:
        print(json.dumps(run(args.lookback_days,args.budget,args.max_mb,args.execute),indent=2))
    except Exception:
        parser.exit(1,"Daily refresh stopped. Prior published pointers retained where possible; inspect local update/refresh diagnostics.\n")

if __name__=="__main__":
    main()
