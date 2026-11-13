"""Economic evidence, measured quality and concise comparison-derived explanations."""
import hashlib
from contextvars import ContextVar
import json
from pathlib import Path
from functools import lru_cache
import numpy as np
import pandas as pd
from Code.daily.dataset import OUT as DAILY,sha,write_json
from Code.daily.policy import now_ist
from .build import OUT

QUALITY=OUT/'phase3/market_quality.json'
ENGINE_VERSION='decision-evidence-v1'
quality_snapshot = ContextVar('strategy_quality_snapshot', default=None)


def money(value):return f'₹{value:,.0f}'


def build_quality():
    from . import service as s
    from Code.api import daily
    manifest,_,_,pointer=daily.snapshot();prices=s.current_prices();ids={r['series_id'] for r in prices}
    entries={}
    for source in manifest['sources']:
        if not source['storage'].startswith('recent'):continue
        table=pd.read_parquet(DAILY/source['storage']/'observations.parquet',columns=['series_id','date','price','available_at'],filters=[('series_id','in',sorted(ids))])
        table=table[(table.date<pd.Timestamp(pointer['target_date']))&(pd.to_datetime(table.available_at,utc=True,format='mixed')<=pd.Timestamp(pointer['issue']))]
        for sid,g in table.sort_values('date').groupby('series_id',observed=True):
            g=g.tail(30);changes=g.price.diff().dropna().abs()
            entries[sid]={'reports':len(g),'recent_step_variation_rs':float(changes.quantile(.8)) if len(changes)>=10 else None,
                          'first_report':str(g.date.min().date()),'last_report':str(g.date.max().date()),'basis':'80th percentile absolute price movement per reporting step; not daily volatility or a confidence interval'}
    write_json(QUALITY,{'batch_signature':sha(DAILY/'batch.json'),'issue':pointer['issue'],'rows':entries})
    return len(entries)


@lru_cache(maxsize=2)
def _quality(signature):return json.loads(Path(signature[0]).read_text(encoding='utf-8'))


def quality_rows():
    from Code.api import daily
    path=daily.auxiliary_path('quality',QUALITY)
    if not path.exists():return {}
    data=_quality((str(path),path.stat().st_mtime_ns))
    held=daily.serving()
    signature=held.get('batch_pointer_sha256') if held else sha(DAILY/'batch.json')
    # The saved profile binds to the original pointer bytes, not its serialization.
    return data['rows'] if data['batch_signature']==signature else {}


def quality_for(series_id):
    rows = quality_snapshot.get()
    return (quality_rows() if rows is None else rows).get(series_id)


def assess(scenario,config):
    q=scenario['quantity_q'];buy=scenario['buy'];sell=scenario['sell']
    qualities=[quality_for(m['series_id']) for m in (buy,sell)]
    moves=[r['recent_step_variation_rs'] for r in qualities if r and r['recent_step_variation_rs'] is not None]
    observed_screen=(sum(moves)*q) if len(moves)==2 else 0
    ages=[m.get('data_freshness',{}).get('age_days') for m in (buy,sell)]
    age=max((a for a in ages if a is not None),default=None)
    historical=scenario.get('uncertainty_screen')
    unknown=max(scenario['procurement'],scenario['sale_revenue'])*config.get('unknown_error_fraction',.1) if historical is None else 0
    forecast_reserve=max(historical or 0,observed_screen,unknown)*(1+config['stale_day_multiplier']*max(0,(age or 1)-1))
    approximate=scenario['route']['objective']=='approximate' or 'Approximate' in scenario['route']['basis'] or 'assumes symmetric' in scenario['route']['basis']
    logistics_reserve=scenario['route'].get('base_freight',scenario['transport'])*config['approximate_freight_reserve'] if approximate else 0
    capacity=scenario.get('payload_q') or 100
    utilization=q/(scenario['trips']*capacity)
    scenario.update(risk_adjusted_margin=round(scenario['margin']-forecast_reserve-logistics_reserve,2),
                    forecast_reserve=round(forecast_reserve,2),logistics_reserve=round(logistics_reserve,2),
                    truck_utilization=utilization,data_quality={'maximum_observation_age_days':age,'recent_price_movement_rs':max(moves) if moves else None,
                    'variation_reports':min((r['reports'] for r in qualities if r),default=0),'route_evidence':'Approximate distance' if approximate else 'Road path between mapped references',
                    'label':('Age unavailable' if age is None else 'Recent reports' if age<=3 else 'Older reports')+(' · approximate route' if approximate else ' · saved road path'),
                    'historical_error_available':historical is not None,'confidence_percentage':None})
    if historical is None:scenario['data_quality']['label']+=' · historical error unavailable'
    return scenario


def comparison(selected,alternative):
    a,b=selected,alternative
    values={'procurement_saving':b['procurement']-a['procurement'],'transport_saving':b['transport']-a['transport'],
            'revenue_advantage':a['sale_revenue']-b['sale_revenue'],'margin_difference':a['margin']-b['margin'],
            'score_difference':a['risk_adjusted_margin']-b['risk_adjusted_margin'],
            'risk_deduction_saving':b.get('forecast_reserve',0)+b.get('logistics_reserve',0)-a.get('forecast_reserve',0)-a.get('logistics_reserve',0)}
    if values['margin_difference']<0 and values['score_difference']>=0:
        text=f"{b['sell']['market']} has {money(-values['margin_difference'])} more estimated margin, but {money(values['risk_deduction_saving'])} more modeled uncertainty deductions."
    else:
        drivers=[(values['procurement_saving'],'lower buying expense'),(values['transport_saving'],'lower freight'),(values['revenue_advantage'],'higher estimated sale proceeds')]
        amount,label=max(drivers)
        text=(f"Against {b['buy']['market']} to {b['sell']['market']}, {money(amount)} in {label} is the largest economic difference. "
              f"The total margin difference is {money(values['margin_difference'])}.") if amount>0 else 'The alternatives have no positive economic advantage on these inputs.'
    return {'id':b['id'],'crop':b['crop'],'buy_market':b['buy']['market'],'sell_market':b['sell']['market'],
            'margin':b['margin'],'transport':b['transport'],'procurement':b['procurement'],'sale_revenue':b['sale_revenue'],
            'score':b['risk_adjusted_margin'],'distance_km':b['route']['km'],**{k:round(v,2) for k,v in values.items()},'insight':text}


def rank(scenarios,config):
    ordered=sorted(scenarios,key=lambda s:(-s['risk_adjusted_margin'],s['route']['km'],s['id']))
    if not ordered:return [],0
    best=ordered[0]['risk_adjusted_margin'];tolerance=max(config['tie_absolute_rs'],abs(best)*config['tie_score_fraction'])
    tied=[s for s in ordered if best-s['risk_adjusted_margin']<=tolerance]
    rest=[s for s in ordered if best-s['risk_adjusted_margin']>tolerance]
    return sorted(tied,key=lambda s:(s['logistics_reserve']>0,
                  s.get('schedule', {}).get('elapsed_hours', 0),s['route']['km'],s['trips'],s['id']))+rest,tolerance


def explain(scenario,alternatives,tie_limit):
    compatible=[a for a in alternatives if a['id']!=scenario['id'] and all(a['buy'].get(k)==scenario['buy'].get(k) for k in ('crop','variety','grade','source'))]
    rivals=compatible[:2]
    comparisons=[comparison(scenario,a) for a in rivals]
    same_buy=[a for a in compatible if a['buy']['series_id']==scenario['buy']['series_id']]
    higher_sale=next((a for a in same_buy if a['sale_price']>scenario['sale_price'] and a['margin']<scenario['margin']),None)
    tradeoff=(f"{higher_sale['sell']['market']} offers a higher estimated selling price, but adds {money(higher_sale['transport']-scenario['transport'])} in freight and leaves {money(scenario['margin']-higher_sale['margin'])} less margin." if higher_sale and higher_sale['transport']>scenario['transport'] else comparisons[0]['insight'] if comparisons else 'No compatible alternative remains in this shortlist; widen the crop or location filters.')
    cards=[{'title':'Price spread','value':money(scenario['sale_price']-scenario['buy']['predicted_price'])+'/quintal',
            'text':f"Buy at {money(scenario['buy']['predicted_price'])}; sell estimate {money(scenario['sale_price'])}, before losses and expenses."},
           {'title':'Transport evidence','value':f"{scenario['route']['km']:,.0f} km · {scenario['trips']} trip(s)",
            'text':scenario['data_quality']['route_evidence']+f"; {money(scenario['transport'])} modeled freight."},
           {'title':'Data quality','value':scenario['data_quality']['label'],
            'text':f"Most recent inputs are up to {scenario['data_quality']['maximum_observation_age_days']} day(s) old. "+('Historical error and measured movement screen the margin.' if scenario.get('uncertainty_screen') is not None else 'Historical error is unavailable; the configured exposure reserve and measured movement screen the margin.')}]
    tied=bool(comparisons and abs(comparisons[0]['score_difference'])<=tie_limit)
    why=f"Options within {money(tie_limit)} of adjusted value are treated as similar; fewer approximate legs, shorter travel and fewer trips are preferred." if tied else 'Ranks by margin after historical error, recent price movement, freshness and route-evidence deductions.'
    sale_quantity=scenario['quantity_q']*(1-scenario['loss_pct']/100)
    return {'headline':f"Buy {scenario['crop']} in {scenario['buy']['market']} · sell in {scenario['sell']['market']}" if scenario['margin']>0 else 'No positive-margin trade in this comparison',
            'cards':cards,'alternatives':comparisons,'trade_off':tradeoff,'why_selected':why,'practical_tie':tied,
            'break_even_sale_price':round(scenario['total_cost']/sale_quantity,2),'what_changes':f"Below {money(scenario['total_cost']/sale_quantity)}/quintal realized selling price, this trade loses its estimated margin.",
            'storage':'Compare 7, 14 and 30 day forecasts with storage expenses in the storage comparison.','engine_version':ENGINE_VERSION}


if __name__=='__main__':print('Quality profiles built:',build_quality())
