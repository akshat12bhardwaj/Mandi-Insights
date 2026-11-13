"""Separately versioned diagnostics and fitted candidates using pre-2019 data."""
import joblib
import numpy as np
import pandas as pd
from Code.daily import evaluate as ev
from Code.daily.forecast import fit_models,learned_predictions,metrics,METHODS,FEATURES
from Code.daily.dataset import OUT as DAILY,write_json,sha
from .build import OUT
from .service import catalog

DEST=OUT/'phase2/models-v1'
PROTOCOL={'version':'phase2-diagnostics-v1','train_end':'2016-12-31','selection_year':2017,'confirmation_year':2018,
          'reporting_delay_days':3,'market_cap':12,'features':FEATURES,'methods':METHODS,
          'promotion_rule':'Retain operational persistence until prospective availability-vintage evidence supports a current-regime learned model.'}


def train():
    DEST.mkdir(parents=True,exist_ok=True)
    if (DEST/'complete.json').exists():
        print('Existing immutable Phase 2 study retained.');return
    write_json(DEST/'protocol.json',PROTOCOL)
    summaries=[];breakdowns=[];support=[];predictions=[]
    for crop in catalog()['crops']:
        if not crop.get('storage'):continue
        print('Phase 2 model diagnostics:',crop['crop'],flush=True)
        history=pd.read_parquet(DAILY/crop['storage']/'observations.parquet',filters=[('date','<=',pd.Timestamp('2018-12-31'))])
        candidates=history[history.date<='2016-12-31'].groupby(['state','series_id'],observed=True).size().reset_index(name='n')
        candidates=candidates[candidates.n>=365].sort_values(['n','series_id'],ascending=[False,True])
        candidates['state_order']=candidates.groupby('state',observed=True).cumcount()
        selected=candidates.sort_values(['state_order','n','series_id'],ascending=[True,False,True]).head(12).series_id
        training=[];validation=[]
        for sid in selected:
            examples,_=ev.simulation_rows(history[history.series_id==sid])
            training.extend(r for r in examples if r['date']<'2017-01-01')
            validation.extend(r for r in examples if r['date']>='2017-01-01')
            support.append({'crop':crop['crop'],'series_id':sid,'role':'retrospective_development_only'})
        if not training or not validation:continue
        models=fit_models(np.stack([r['x'] for r in training]),np.array([r['actual']/r['persistence']-1 for r in training]))
        predicted=learned_predictions(models,np.stack([r['x'] for r in validation]),[r['persistence'] for r in validation])
        table=pd.DataFrame([{k:v for k,v in r.items() if k!='x'} for r in validation])
        for name,values in predicted.items():table[name]=values
        table['crop']=crop['crop'];table['year']=pd.to_datetime(table.date).dt.year;table['quarter']=pd.to_datetime(table.date).dt.quarter
        predictions.append(table)
        slug=crop['storage'].replace('\\','/').split('/')[-1]
        model_path=DEST/f'{slug}.joblib'
        joblib.dump({'models':models,'features':FEATURES,'training_cutoff':PROTOCOL['train_end'],'source_sha256':crop['observations_sha256'],'serving_approved':False},model_path)
        for method in METHODS:
            result=metrics(table.actual,table[method]);baseline=metrics(table.actual,table.persistence)['mae']
            summaries.append({'crop':crop['crop'],'model':method,**result,'skill_vs_persistence_pct':100*(1-result['mae']/baseline),
                              'markets':int(table.series_id.nunique()),'training_rows':len(training),'artifact':model_path.name if method in models else None,'serving_selected':method=='persistence'})
            for kind,keys in [('year',['year']),('season',['quarter']),('market',['series_id']),('freshness',['age_days'])]:
                for group,g in table.groupby(keys):
                    value=group[0] if isinstance(group,tuple) else group
                    score=metrics(g.actual,g[method]);base=metrics(g.actual,g.persistence)['mae']
                    breakdowns.append({'crop':crop['crop'],'model':method,'dimension':kind,'value':str(value),**score,'skill_pct':100*(1-score['mae']/base) if base else None})
    pd.DataFrame(summaries).to_csv(DEST/'metrics.csv',index=False)
    pd.DataFrame(breakdowns).to_csv(DEST/'breakdowns.csv',index=False)
    pd.DataFrame(support).to_csv(DEST/'supported_series.csv',index=False)
    pd.concat(predictions).to_parquet(DEST/'development_predictions.parquet',index=False)
    write_json(DEST/'complete.json',{'protocol':PROTOCOL,'metric_sha256':sha(DEST/'metrics.csv'),
                                   'crop_models':{c['crop']:'persistence' for c in catalog()['crops']},
                                   'rows':int(sum(r['rows'] for r in summaries if r['model']=='persistence')),
                                   'model_artifacts':[{'path':p.name,'sha256':sha(p)} for p in DEST.glob('*.joblib')]})


if __name__=='__main__':train()
