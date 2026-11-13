from datetime import date
import json
import pytest
from Code.daily import refresh as rf, operational as op

def response(price="150"):
    return {"total":1,"records":[{"Commodity":"Onion","Arrival_Date":"08/11/2026","State":"S","District":"D",
        "Market":"M","Variety":"Other","Grade":"FAQ","Min_Price":"100","Max_Price":"200","Modal_Price":price}]}

def test_download_plan_is_bounded_without_network():
    p=rf.plan(date(2026,11,1),date(2026,11,8),["Onion","Potato"])
    assert p["maximum_calls"]==32 and p["crop_days"]==16
    assert p["order"]=="newest_first"


@pytest.mark.parametrize("body", [{}, {"records": []}, {"total": None, "records": []},
                                  {"total": False, "records": []}, {"total": 0, "records": None}])
def test_missing_response_metadata_is_not_an_empty_market_report(body):
    with pytest.raises(ValueError, match="Malformed"):
        rf.validate_pair(body, body, "Onion", date(2026,11,8))


def test_explicit_empty_reports_are_valid_missing_observations():
    body={"total":0,"records":[]}
    assert rf.validate_pair(body,body,"Onion",date(2026,11,8))


def test_refresh_prioritizes_newest_day_within_same_budget(tmp_path,monkeypatch):
    monkeypatch.setattr(rf,"OUT",tmp_path)
    calls=[]
    def fetch(crop,day):
        calls.append(day)
        return {"total":0,"records":[]}
    monkeypatch.setattr(rf,"ROOT",tmp_path)
    monkeypatch.setattr(rf,"RAW",tmp_path/"raw")
    with pytest.raises(ValueError,match="budget"):
        rf.collect(date(2026,11,7),date(2026,11,8),["Onion"],2,1_000_000,fetch=fetch)
    assert calls==[date(2026,11,8)]*2
    manifest=json.loads((tmp_path/"refresh_manifest.json").read_text())
    assert manifest["partitions"]["Onion|2026-11-08"]["status"]=="empty_report_not_zero_price"

def test_partition_validation_rejects_truncation_changes_and_wrong_day():
    day=date(2026,11,8)
    assert rf.validate_pair(response(),response(),"Onion",day)
    with pytest.raises(ValueError,match="disagree"):
        rf.validate_pair(response(),response("160"),"Onion",day)
    with pytest.raises(ValueError,match="Truncated"):
        rf.validate_pair({**response(),"total":2},response(),"Onion",day)
    with pytest.raises(ValueError,match="filters"):
        rf.validate_pair(response(),response(),"Potato",day)

def test_incremental_resume_and_raw_tamper_detection(tmp_path,monkeypatch):
    monkeypatch.setattr(rf,"ROOT",tmp_path)
    monkeypatch.setattr(rf,"OUT",tmp_path/"out")
    monkeypatch.setattr(rf,"RAW",tmp_path/"raw")
    calls=[]
    def fetch(crop,day):
        calls.append((crop,day)); return response()
    args=(date(2026,11,8),date(2026,11,8),["Onion"],2,1_000_000)
    result=rf.collect(*args,fetch=fetch)
    assert result["calls"]==2 and len(calls)==2
    assert rf.collect(*args,fetch=fetch)["calls"]==0
    manifest=json.loads((rf.OUT/"refresh_manifest.json").read_text())
    path=tmp_path/next(iter(manifest["partitions"].values()))["path"]
    path.write_text("corrupt")
    with pytest.raises(ValueError,match="modified"):
        rf.collect(*args,fetch=fetch)

def test_request_budget_stops_before_unapproved_call(tmp_path,monkeypatch):
    monkeypatch.setattr(rf,"OUT",tmp_path)
    calls=[]
    with pytest.raises(ValueError,match="budget"):
        rf.collect(date(2026,11,8),date(2026,11,8),["Onion"],1,1_000_000,fetch=lambda c,d: calls.append(c) or response())
    assert len(calls)==1
    # A resumed process cannot reset the approved allowance after the failed run.
    with pytest.raises(ValueError,match="budget"):
        rf.collect(date(2026,11,8),date(2026,11,8),["Onion"],1,1_000_000,fetch=lambda c,d: calls.append(c) or response())
    assert len(calls)==1

def test_validation_failure_retains_usage_without_saving_bad_partition(tmp_path,monkeypatch):
    monkeypatch.setattr(rf,"OUT",tmp_path)
    count=[]
    def fetch(c,d):
        count.append(1)
        return response("150" if len(count)==1 else "160")
    with pytest.raises(ValueError,match="validation failed"):
        rf.collect(date(2026,11,8),date(2026,11,8),["Onion"],2,1_000_000,fetch=fetch)
    usage=json.loads(next((tmp_path/"refresh_usage").glob("*.json")).read_text())
    assert usage["calls_used"]==2 and usage["last_outcome"]=="partition_validation_failed"
    assert not (tmp_path/"refresh_manifest.json").exists()

def test_increment_can_be_imported_without_merging_archive_identity(tmp_path,monkeypatch):
    monkeypatch.setattr(rf,"ROOT",tmp_path)
    monkeypatch.setattr(rf,"OUT",tmp_path/"out")
    monkeypatch.setattr(rf,"RAW",tmp_path/"raw")
    monkeypatch.setattr(op,"ROOT",tmp_path)
    monkeypatch.setattr(op,"OUT",tmp_path/"out")
    rf.collect(date(2026,11,8),date(2026,11,8),["Onion"],2,1_000_000,fetch=lambda c,d:response())
    imported=op.import_recent("Onion")
    assert imported["records"]==1
    import pandas as pd
    rows=pd.read_parquet(op.OUT/imported["storage"]/"observations.parquet")
    assert rows.iloc[0].source=="datagov" and rows.iloc[0].grade=="FAQ" and rows.iloc[0].price==150


def test_new_crop_grades_remain_distinct_without_changing_legacy_faq_policy(tmp_path,monkeypatch):
    monkeypatch.setattr(rf,"ROOT",tmp_path)
    monkeypatch.setattr(rf,"OUT",tmp_path/"out")
    monkeypatch.setattr(rf,"RAW",tmp_path/"raw")
    monkeypatch.setattr(op,"ROOT",tmp_path)
    monkeypatch.setattr(op,"OUT",tmp_path/"out")
    def fetch(crop,day):
        records=[]
        for grade,price in [("Grade A","150"),("Grade B","140")]:
            row=response(price)["records"][0]
            records.append({**row,"Commodity":crop,"Grade":grade})
        return {"total":2,"records":records}
    rf.collect(date(2026,11,8),date(2026,11,8),["Banana","Onion"],4,1_000_000,fetch=fetch)
    imported=op.import_recent("Banana")
    import pandas as pd
    rows=pd.read_parquet(op.OUT/imported["storage"]/"observations.parquet")
    assert set(rows.grade)=={"Grade A","Grade B"}
    assert rows.series_id.nunique()==2
    assert imported["processing_policy"]==op.RECENT_POLICY_VERSION
    assert op.import_recent("Onion") is None
