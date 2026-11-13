"""Measured recent continuity and eligibility; no price observations invented."""
import json
import pandas as pd
from Code.daily import operational as op
from Code.daily.dataset import OUT as DAILY, write_json
from Code.daily.policy import now_ist
from .build import OUT
from .service import catalog


def audit():
    dest,manifest,_=op.load_release()
    registry=pd.read_parquet(dest/'registry.parquet')
    pointer=json.loads((DAILY/'batch.json').read_text())
    store=op.BatchStore(DAILY/pointer['path'])
    with store.connect() as db:
        predictions=[json.loads(x[0]) for x in db.execute('SELECT payload FROM predictions')]
    frame=pd.DataFrame(predictions)
    target=pd.Timestamp(now_ist().date())
    rows=[]
    for crop in catalog()['crops']:
        name=crop['crop'];series=registry[(registry.crop==name)&(registry.source=='datagov')]
        pred=frame[(frame.crop==name)&(frame.source=='datagov')]
        current=pointer['target_date']==str(target.date())
        eligible=int(pred.predicted_modal_price.notna().sum()) if current else 0
        maxobs=int(series.usable_observations.max()) if len(series) else 0
        maxspan=int(((pd.to_datetime(series.last_date)-pd.to_datetime(series.first_date)).dt.days+1).max()) if len(series) else 0
        sources=[r for r in manifest['sources'] if r['crop']==name and r['storage'].startswith('recent')]
        dates=pd.DatetimeIndex([]);recent_rows=0;last=None;date_rows=0
        for source in sources:
            h=pd.read_parquet(DAILY/source['storage']/'observations.parquet',columns=['date'])
            dates=dates.union(pd.DatetimeIndex(h.date.unique()))
            recent_rows+=int((h.date>=target-pd.Timedelta(days=365)).sum());date_rows+=len(h)
            last=str(h.date.max().date()) if len(h) else last
        window=dates[(dates>=target-pd.Timedelta(days=365))&(dates<target)]
        statuses=pred.status.value_counts().to_dict() if len(pred) else {}
        reason=('Eligible current forecasts' if eligible else 'Expired forecast batch' if not current else
                'No recent-source observations collected' if not len(series) else
                'No series meets all current eligibility checks; inspect status counts and recent continuity' if maxobs>=180 and maxspan>=365 else
                f'Recent series have at most {maxobs} observations / {maxspan} days span; need 180 observations, 365-day span and sufficient recent reporting')
        rows.append({'crop':name,'historical_records':int(crop.get('usable_records',0)),'recent_source_records':date_rows,
                     'last_365d_records':recent_rows,'last_observation':last or crop['last_date'],
                     'recent_series':len(series),'eligible_forecasts':eligible,'max_series_observations':maxobs,'max_series_span_days':maxspan,
                     'reporting_days_last365':len(window),'missing_crop_reporting_days_last365':365-len(window),
                     'recent_states':int(series.state.nunique()),'recent_districts':int(series.district.nunique()),
                     'median_series_missing_frequency':float(series.missing_calendar_frequency.median()) if len(series) else None,
                     'reason':reason,'model':'persistence','price_unit':'INR/quintal'})
        rows[-1]['status_counts']=statuses
    report={'as_of':now_ist().isoformat(),'dataset_version':manifest['dataset_version'],'batch_target':pointer['target_date'],
            'forecast_count':sum(r['eligible_forecasts'] for r in rows),'eligible_crop_count':sum(r['eligible_forecasts']>0 for r in rows),
            'note':'Recent-source identity remains separate from historical archive; crop reporting-day counts are not individual-market continuity.', 'rows':rows}
    write_json(OUT/'phase2/operational_view.json',{
        'version':'phase2-operational-view-v1','dataset_version':manifest['dataset_version'],
        'sources':manifest['sources'],'registry':str((dest/'registry.parquet').relative_to(DAILY)),
        'unit':'INR/quintal','identity':['crop','source','state','district','market','variety','grade'],
        'price_columns':['date','price','available_at','source_row','availability_basis'],
        'optional_covariates':{'arrivals_tonnes':None,'weather':None,'production_context':None},
        'covariate_policy':'Unavailable in validated daily source contract; not imputed or used in models. Historical contextual views remain separate.',
        'eligibility_policy':'daily-prices-v1 unchanged; see Code/daily/policy.py'})
    write_json(OUT/'phase2/coverage.json',report)
    pd.DataFrame(rows).to_csv(OUT/'phase2/coverage.csv',index=False)
    return report


if __name__=='__main__':
    result=audit()
    print(pd.DataFrame(result['rows'])[['crop','recent_source_records','last_observation','eligible_forecasts','max_series_observations','max_series_span_days']].to_string(index=False))
