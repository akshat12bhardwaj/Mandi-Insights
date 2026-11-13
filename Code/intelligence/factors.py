"""Matched historical ablations with explicit availability assumptions; no promotion."""
import json
import joblib
import numpy as np
import pandas as pd
from Code.daily import evaluate as ev
from Code.daily.forecast import fit_models,learned_predictions,metrics
from Code.daily.dataset import ROOT,OUT as DAILY,write_json,sha
from .build import OUT

DEST=OUT/'phase3/factors_v1'
ARR=['arrivals_prev_obs','arrivals_roll7d_mean','arrivals_roll30d_mean','arrivals_roll30d_std']
PROD=['apy_production_tonnes_lag2','apy_yield_t_per_ha_lag2']
KEY=['state','district','market','variety']


def train():
    from .service import catalog
    DEST.mkdir(parents=True,exist_ok=True)
    if (DEST/'manifest.json').exists():print('Existing factors study retained.');return
    protocol={'version':'agricultural-factors-v1','train_end':'2016-12-31','selection_year':2017,'confirmation_year':2018,
              'market_reporting_lag_assumption_days':3,'production_lag_agricultural_years':2,
              'comparison':'Matched complete-case cohort for price, price+arrivals, price+arrivals+production; all targets before 2019.',
              'weather':'Excluded: original availability vintages missing; no guessed historical publication timestamps.',
              'serving_promotion':False,'reason':'Historical lag assumptions are not verified original publication vintages; current daily arrivals are absent.'}
    write_json(DEST/'protocol.json',protocol)
    scores=[];breakdowns=[];coverage=[]
    for crop in [r for r in catalog()['crops'] if r['crop'] in ('Onion','Potato','Wheat')]:
        print('Factors study:',crop['crop'],flush=True)
        history=pd.read_parquet(DAILY/crop['storage']/'observations.parquet',filters=[('date','<=',pd.Timestamp('2018-12-31'))])
        raw=pd.read_parquet(ROOT/f"Processed_Data/features/features_{crop['crop'].lower()}.parquet",
                            columns=KEY+['reported_date','usable_modal_price']+ARR+PROD,filters=[('reported_date','<=',pd.Timestamp('2018-12-31'))])
        raw=raw[raw.usable_modal_price].drop_duplicates(KEY+['reported_date'],keep=False)
        pool=history[history.date<='2016-12-31'].groupby(['state','series_id'],observed=True).size().reset_index(name='n')
        pool=pool[pool.n>=365].sort_values(['n','series_id'],ascending=[False,True]);pool['state_order']=pool.groupby('state',observed=True).cumcount()
        ids=pool.sort_values(['state_order','n','series_id'],ascending=[True,False,True]).head(12).series_id
        training=[];validation=[];scheduled=0
        for sid in ids:
            g=history[history.series_id==sid].sort_values('date');identity=g.iloc[0]
            sub=raw
            for key in KEY:sub=sub[sub[key]==identity[key]]
            sub=sub.sort_values('reported_date');dates=sub.reported_date.to_numpy(dtype='datetime64[D]')
            rows,_=ev.simulation_rows(g);scheduled+=len(rows)
            for row in rows:
                cutoff=np.datetime64(row['date'])-np.timedelta64(3,'D');idx=np.searchsorted(dates,cutoff,side='right')-1
                if idx<0 or int((cutoff-dates[idx]).astype(int))>7:continue
                values=sub.iloc[idx][ARR+PROD].to_numpy(float)
                if not np.isfinite(values).all() or (values<0).any():continue
                engineered=np.log1p(values)
                item={**row,'extra':engineered}
                (training if row['date']<'2017-01-01' else validation).append(item)
        coverage.append({'crop':crop['crop'],'scheduled_examples':scheduled,'training_rows':len(training),'matched_validation_rows':len(validation),'markets_selected':len(ids)})
        if len(training)<100 or len(validation)<100:continue
        table=pd.DataFrame([{k:v for k,v in r.items() if k not in ('x','extra')} for r in validation])
        table['year']=pd.to_datetime(table.date).dt.year;table['season']=pd.to_datetime(table.date).dt.quarter
        score=metrics(table.actual,table.persistence)
        scores.append({'crop':crop['crop'],'variant':'matched_persistence','model':'persistence',**score,'skill_pct':0.})
        for variant,nextra in [('price',0),('price_arrivals',4),('price_arrivals_production',6)]:
            xt=np.stack([np.concatenate([r['x'],r['extra'][:nextra]]) for r in training]);xv=np.stack([np.concatenate([r['x'],r['extra'][:nextra]]) for r in validation])
            models=fit_models(xt,np.array([r['actual']/r['persistence']-1 for r in training]))
            artifact=DEST/f"{crop['crop'].lower()}-{variant}.joblib";joblib.dump({'models':models,'protocol':protocol,'serving_approved':False},artifact)
            predicted=learned_predictions(models,xv,table.persistence)
            for model,values in predicted.items():
                result=metrics(table.actual,values);base=metrics(table.actual,table.persistence)['mae']
                scores.append({'crop':crop['crop'],'variant':variant,'model':model,**result,'skill_pct':100*(1-result['mae']/base)})
                table['candidate']=values
                for dimension,column in [('year','year'),('season','season'),('market','series_id'),('freshness','age_days')]:
                    for value,group in table.groupby(column):
                        result=metrics(group.actual,group.candidate);base=metrics(group.actual,group.persistence)['mae']
                        breakdowns.append({'crop':crop['crop'],'variant':variant,'model':model,'dimension':dimension,'value':str(value),**result,'skill_pct':100*(1-result['mae']/base) if base else None})
    pd.DataFrame(scores).to_csv(DEST/'metrics.csv',index=False);pd.DataFrame(breakdowns).to_csv(DEST/'breakdowns.csv',index=False);pd.DataFrame(coverage).to_csv(DEST/'coverage.csv',index=False)
    write_json(DEST/'manifest.json',{'protocol':protocol,'metrics_sha256':sha(DEST/'metrics.csv'),'coverage':coverage,
                                   'models':[{'path':p.name,'sha256':sha(p)} for p in DEST.glob('*.joblib')],
                                   'operational_gate':'No new covariates deployed; prospective source availability and current arrival/weather inputs are required.'})


if __name__=='__main__':train()
