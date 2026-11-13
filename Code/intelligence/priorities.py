"""Measured collection priorities and source pause state, without network access."""
import json
from Code.daily.policy import now_ist
from Code.daily.dataset import OUT as DAILY,write_json
from .build import OUT
from .service import catalog


def plan():
    path=OUT/'phase2/coverage.json'
    coverage=json.loads(path.read_text())['rows'] if path.exists() else []
    by_crop={r['crop']:r for r in coverage}
    rows=[]
    for c in catalog()['crops']:
        current=by_crop.get(c['crop'],{})
        if current.get('eligible_forecasts',0):continue
        rows.append({'crop':c['crop'],'historically_eligible_series':c['daily_eligible_series'],
                     'recent_records':current.get('recent_source_records',0),'recent_states':current.get('recent_states',0),
                     'maximum_recent_series_observations':current.get('max_series_observations',0),
                     'reason':'Prioritize historically continuous markets with confirmed recent reporting; keep existing identity and eligibility rules.'})
    rows.sort(key=lambda r:(r['recent_records']==0,-r['historically_eligible_series'],-r['recent_records'],r['crop']))
    pause=DAILY/'phase2_rate_limit.json';until=json.loads(pause.read_text()).get('until') if pause.exists() else None
    result={'as_of':now_ist().isoformat(),'provider_paused_until':until,'paused':bool(until and until>now_ist().isoformat()),'priorities':rows}
    write_json(OUT/'phase3/collection_priority.json',result)
    return result


if __name__=='__main__':print(json.dumps(plan(),indent=2))
