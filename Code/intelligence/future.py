"""Independent 7/14/30-day price study. Never opens protected evaluation years."""
import argparse
import json
from functools import lru_cache
import joblib
import numpy as np
import pandas as pd
from Code.daily import evaluate as ev
from Code.daily.forecast import fit_models,learned_predictions,metrics,METHODS,FEATURES
from Code.daily.dataset import OUT as DAILY,write_json,sha
from Code.daily.policy import now_ist
from .build import OUT

DEST=OUT/'phase3/future_v1'
HORIZONS=(7,14,30)
PROTOCOL={'version':'future-price-v1','train_target_cutoff':'2016-12-28','training_issue_cutoff':'2016-12-31',
          'selection_year':2017,'confirmation_year':2018,'horizons':list(HORIZONS),'features':FEATURES,
          'reporting_delay_days':3,'series_per_crop':12,'origins':'Eligible Wednesday origins with an observed origin-day report; future targets must have an exact reported price.',
          'seasonal_baseline':'Price on target minus 364 days, only if known before origin minus three days; otherwise persistence.',
          'selection':'Select on 2017; confirm the selected candidate on 2018. Learned serving promotion also requires current-regime availability-vintage evidence, which is absent.',
          'interpretation':'Retrospective validation on revised archives with assumed publication delay, not live calibrated confidence.',
          'protected_boundary':'No 2019+ target or protected research output is read/scored.'}


def examples(history,horizon):
    """Feature origins precede target; labels crossing training cutoff are purged."""
    rows,_=ev.simulation_rows(history)
    prices=history.set_index('date').price.to_dict()
    result=[]
    for row in rows:
        origin=pd.Timestamp(row['date']);target=origin+pd.Timedelta(days=horizon)
        if target>pd.Timestamp('2018-12-31') or target not in prices:continue
        past=target-pd.Timedelta(days=364)
        seasonal=prices.get(past,row['persistence']) if past<=origin-pd.Timedelta(days=3) else row['persistence']
        result.append({**row,'origin':str(origin.date()),'date':str(target.date()),'actual':float(prices[target]),'seasonal_naive_7d':float(seasonal)})
    return result


def train():
    from .service import catalog
    DEST.mkdir(parents=True,exist_ok=True)
    if (DEST/'manifest.json').exists():print('Existing future study retained.');return
    write_json(DEST/'protocol.json',PROTOCOL)
    scores=[];breakdowns=[];support=[];choices=[]
    for crop in catalog()['crops']:
        if not crop.get('storage'):continue
        print('Future validation:',crop['crop'],flush=True)
        history=pd.read_parquet(DAILY/crop['storage']/'observations.parquet',filters=[('date','<=',pd.Timestamp('2018-12-31'))])
        pool=history[history.date<='2016-12-31'].groupby(['state','series_id'],observed=True).size().reset_index(name='n')
        pool=pool[pool.n>=365].sort_values(['n','series_id'],ascending=[False,True]);pool['state_order']=pool.groupby('state',observed=True).cumcount()
        ids=pool.sort_values(['state_order','n','series_id'],ascending=[True,False,True]).head(12).series_id
        groups=[history[history.series_id==sid].sort_values('date') for sid in ids]
        for horizon in HORIZONS:
            train_rows=[];validation=[]
            for g in groups:
                for row in examples(g,horizon):
                    if row['date']<=PROTOCOL['train_target_cutoff']:train_rows.append(row)
                    elif row['origin']>='2017-01-01':validation.append(row)
            if len(train_rows)<100 or len(validation)<100:continue
            models=fit_models(np.stack([r['x'] for r in train_rows]),np.array([r['actual']/r['persistence']-1 for r in train_rows]))
            table=pd.DataFrame([{k:v for k,v in r.items() if k!='x'} for r in validation])
            predicted=learned_predictions(models,np.stack([r['x'] for r in validation]),table.persistence)
            for name,values in predicted.items():table[name]=values
            table['year']=pd.to_datetime(table.date).dt.year;table['season']=pd.to_datetime(table.date).dt.quarter
            select=table[table.year==2017];confirm=table[table.year==2018]
            candidate=min(METHODS,key=lambda m:metrics(select.actual,select[m])['mae']) if len(select) else 'persistence'
            confirmed=bool(len(confirm) and metrics(confirm.actual,confirm[candidate])['mae']<metrics(confirm.actual,confirm.persistence)['mae']*.98)
            slug=crop['storage'].replace('\\','/').split('/')[-1]
            artifact=DEST/f'{slug}-{horizon}d.joblib'
            joblib.dump({'models':models,'features':FEATURES,'protocol':PROTOCOL,'source_sha256':crop['observations_sha256'],'serving_approved':False},artifact)
            choices.append({'crop':crop['crop'],'horizon_days':horizon,'selected_on_2017':candidate,'confirmed_2018':confirmed,
                            'serving_model':'persistence','serving_reason':'Historically evaluated baseline; no current-regime learned promotion evidence','artifact':artifact.name})
            for method in METHODS:
                score=metrics(table.actual,table[method]);base=metrics(table.actual,table.persistence)['mae']
                scores.append({'crop':crop['crop'],'horizon_days':horizon,'model':method,**score,'skill_pct':100*(1-score['mae']/base),'markets':table.series_id.nunique()})
                for dimension,column in [('year','year'),('market','series_id'),('season','season'),('freshness','age_days')]:
                    for value,g in table.groupby(column):
                        score=metrics(g.actual,g[method]);base=metrics(g.actual,g.persistence)['mae']
                        breakdowns.append({'crop':crop['crop'],'horizon_days':horizon,'model':method,'dimension':dimension,'value':str(value),**score,'skill_pct':100*(1-score['mae']/base) if base else None})
            support.extend({'crop':crop['crop'],'horizon_days':horizon,'series_id':sid,'scope':'historical evaluation cohort'} for sid in ids)
    pd.DataFrame(scores).to_csv(DEST/'metrics.csv',index=False);pd.DataFrame(breakdowns).to_csv(DEST/'breakdowns.csv',index=False)
    pd.DataFrame(support).to_csv(DEST/'supported_series.csv',index=False)
    write_json(DEST/'manifest.json',{'version':'future-price-v1','created_at':now_ist().isoformat(),'protocol':PROTOCOL,'choices':choices,
                                   'metrics_sha256':sha(DEST/'metrics.csv'),'artifacts':[{'path':p.name,'sha256':sha(p)} for p in DEST.glob('*.joblib')]})


@lru_cache(maxsize=2)
def _evaluation(signature):
    manifest=json.loads((DEST/'manifest.json').read_text(encoding='utf-8'))
    if sha(DEST/'metrics.csv')!=manifest['metrics_sha256']:raise ValueError('Future evaluation artifact changed')
    table=pd.read_csv(DEST/'metrics.csv')
    scores={(row.crop,row.horizon_days):row for row in table[table.model=='persistence'].itertuples()}
    return manifest,scores


def forecast(price,horizon):
    if horizon not in HORIZONS:raise ValueError('Choose a 7, 14 or 30 day forecast')
    issue=now_ist()
    if price.get('target_date')!=str(issue.date()) or not price.get('predicted_modal_price'):raise ValueError('A current eligible market forecast is required')
    path=DEST/'manifest.json'
    manifest,scores=_evaluation(path.stat().st_mtime_ns) if path.exists() else ({'version':None},{})
    row=scores.get((price['crop'],horizon))
    version=manifest['version']
    if row is None:
        from .learning import score as dynamic_score
        evaluated=dynamic_score(price['crop'],horizon)
        if evaluated:row=pd.Series(evaluated);version=evaluated['version']
    if row is None or row.rows<100:raise ValueError('Insufficient horizon validation coverage')
    return {'kind':'future_forecast','crop':price['crop'],'series_id':price['series_id'],'horizon_days':horizon,
            'target_date':str(issue.date()+pd.Timedelta(days=horizon)),'issued_at':issue.isoformat(),'price':price['predicted_modal_price'],
            'unit':'INR/quintal','model':'persistence','model_version':version,'dataset_version':price.get('dataset_version'),'base_price_issue':price.get('forecast_issue_timestamp'),'historical_mae':float(row.mae),
            'historical_rmse':float(row.rmse),'validation_rows':int(row.rows),'validation_scope':'2017–2018 revised-archive simulation; three-day reporting delay assumed',
            'uncertainty_kind':'Historical error context, not a calibrated confidence interval','source_observation':price['last_observation_date']}


def batch():
    if not (DEST/'manifest.json').exists():
        from .learning import DEST as dynamic
        if not any((dynamic/'runs').glob('*/manifest.json')):return 0
    from .service import current_prices
    rows=[]
    for price in current_prices():
        for horizon in HORIZONS:
            try:rows.append(forecast(price,horizon))
            except ValueError:continue
    write_json(OUT/'phase3/future_batch.json',{'issue':now_ist().isoformat(),'batch_signature':sha(DAILY/'batch.json'),'forecasts':rows,'count':len(rows)})
    return len(rows)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['train','batch']);args=p.parse_args()
    if args.command=='train':train()
    else:print('Future forecasts:',batch())
