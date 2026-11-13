"""Compare direct sale with historically evaluated horizon forecasts and storage."""
from . import service as s, future, planning


def calculate(buy,sell,request,annotate=True):
    warehouse=next((w for w in s.warehouses() if w['warehouse_id']==request.warehouse_id),None) if request.warehouse_id else None
    transport={k:getattr(request,k) for k in ('toll_rs_trip','congestion_pct','loading_minutes','delay_rs_hour') if hasattr(request,k)}
    now=s.now_ist().replace(second=0,microsecond=0)
    base=s.calculate(buy,sell,request.quantity,request.vehicle,request.handling,request.loss,request.days,warehouse,request.route_index,rs_km=request.rs_km,capacity_q=request.capacity_q,planned=True,**transport)
    scenario_price=round(sell['predicted_price']*(1+request.future_change/100), 2) if request.days and request.future_mode=='scenario' else None
    result=planning.complete(base,now.date(),now,scenario_price=scenario_price)
    if result is None:
        raise ValueError('The journey exceeds the planning window')
    result['sale_kind']=result['sale_quote']['kind']
    if request.days:
        direct=calculate(buy,sell,request.model_copy(update={'days':0,'warehouse_id':None}),annotate=False)
        result['direct_comparison']={k:direct[k] for k in ('total_cost','sale_revenue','margin','transport','sale_basis')}
        result['storage_detour_km']=round(result['route']['km']-direct['route']['km'],1)
    if not annotate:
        return result
    from .explanations import explain
    result['decision']=explain(result,[],s.CONFIG['decision']['tie_absolute_rs'])
    result['decision'].update(scope='custom_scenario',why_selected='Your adjusted scenario uses the selected inputs; it is not a new global ranking.',
                              trade_off='Use the shortlist filters to compare daily default scenarios with other markets.')
    from .market_context import scenario_contribution
    return scenario_contribution(result)


def compare(request):
    if request.buy_id==request.sell_id:raise ValueError('Choose different buying and selling markets')
    prices={r['series_id']:{**r,'predicted_price':r['predicted_modal_price'],'coordinate':s.market_coordinate(r)} for r in s.current_prices()}
    if request.buy_id not in prices or request.sell_id not in prices:raise ValueError('Choose current eligible buying and selling markets')
    buy,sell=prices[request.buy_id],prices[request.sell_id]
    from .market_inventory import market_key
    if market_key(buy)==market_key(sell):raise ValueError('Choose different buying and selling markets')
    direct=request.model_copy(update={'days':0,'warehouse_id':None,'future_mode':'forecast'})
    immediate=calculate(buy,sell,direct);immediate['label']='Sell on arrival'
    rows=[immediate];unavailable=[]
    origin=buy['coordinate']
    if not origin:raise ValueError('A procurement location is required')
    candidates=[w for w in s.warehouses() if buy['crop'] in w['supported_crops'] and w['free_t']>=request.quantity/10
                and (not request.warehouse_id or request.warehouse_id == w['warehouse_id'])]
    candidates=sorted(candidates,key=lambda w: (
        sum(s.distance(p['coordinate'],{'lat':w['latitude'],'lng':w['longitude']}) for p in (buy,sell)),
        w['warehouse_id']))[:s.CONFIG['planning']['warehouse_limit']]
    for days in future.HORIZONS:
        options=[]
        for warehouse in candidates:
            if days>warehouse['max_days']:continue
            try:
                option=calculate(buy,sell,request.model_copy(update={'days':days,'warehouse_id':warehouse['warehouse_id'],'future_mode':'forecast','route_index':0}))
                options.append(option)
            except ValueError as exc:
                if str(exc) != 'The journey exceeds the planning window':
                    raise
                continue
        if options:
            best=planning.rank(options,s.CONFIG['decision'])[0][0]
            best['label']=f'Store {days} days';rows.append(best)
        elif not any(r['days']==days for r in unavailable):unavailable.append({'days':days,'reason':'No compatible candidate with enough capacity and duration support'})
    ranked,_=planning.rank(rows,s.CONFIG['decision'])
    best=ranked[0]
    return {'rows':rows,'recommended_days':best['storage_days'],'recommendation':best['label'],
            'reason':('After transport, storage, losses and price evidence, selling on arrival has the stronger screened margin.' if best['storage_days']==0 else
                      f"After transport, storage, losses and horizon error screening, {best['label'].lower()} has the stronger estimated net value."),
            'scope':f'{len(candidates)} compatible facilities screened by combined distance to both markets',
            'unavailable':unavailable,'future_forecasts_are_scenarios':False}
