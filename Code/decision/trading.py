"""Trading v2: compatible current forecasts, explicit costs, no future-price invention."""
import hashlib
from functools import lru_cache
from fastapi import HTTPException
from . import service as svc
from .contracts import DecisionRequest
from .costs import amount,money,trip_count


def identity(row):
    return {**{k:row[k] for k in ("series_id","crop","state","district","market","variety","grade")},
            "reference_node":svc.reference_node(row["state"],row["district"])}


def location_evidence(node_id):
    if not node_id:
        return None
    nodes=svc.lg.routing_nodes().set_index("node_id")
    if node_id not in nodes.index:
        return None
    reference=nodes.loc[node_id]
    result={"node_id":node_id,"precision_tier":4,"meaning":"Verified district reference; approximate for a market, not a mandi entrance",
            "reference_coordinate":{"latitude":float(reference.latitude),"longitude":float(reference.longitude)},"road_access_coordinate":None}
    if svc.lg.pl.SNAP.exists():
        snap=svc.pd.read_csv(svc.lg.pl.SNAP)
        match=snap[snap.node_id==node_id]
        if len(match):
            row=match.iloc[0]
            result["road_access_coordinate"]={"latitude":float(row.network_lat),"longitude":float(row.network_lon),"straight_line_gap_km":float(row.access_gap_km),"basis":"Derived nearest two-way road vertex; not a verified market access road"}
    return result


@lru_cache(maxsize=1024)
def path_identity(origin,dest,objective):
    if origin==dest:
        return "same_reference"
    g=svc.lg.geometry()
    if g is None:
        return f"unverified:{objective}"
    try:
        return hashlib.sha256(str(g.loc[(origin,dest,objective),"coordinates"]).encode()).hexdigest()
    except KeyError:
        return f"unverified:{objective}"


def routes_between(buy,sell,request):
    origin=svc.reference_node(buy["state"],buy["district"])
    dest=svc.reference_node(sell["state"],sell["district"]) if sell else request.destination
    assumptions=request.transport.model_copy(deep=True)
    if sell:
        assumptions.destination_access_km=assumptions.market_access_km.get(sell["series_id"])
    scoped=request.model_copy(update={"destination":dest,"transport":assumptions})
    options=svc.route_options(origin,dest,buy["series_id"],scoped)
    unique={}
    access=assumptions.market_access_km.get(buy["series_id"])
    for route in options:
        route={**route,"objectives":[route["objective"]]}
        distance=(route["road_distance_km"]+access+assumptions.destination_access_km
                  if access is not None and assumptions.destination_access_km is not None else None)
        route["total_distance_km"]=distance
        if request.max_transport_km is not None and (distance is None or distance>request.max_transport_km):
            continue
        if assumptions.load_capacity_quintals is None:
            route.update(transport_cost=None,fuel_expense=None,cost_per_quintal=None)
        key=path_identity(origin,dest,route["objective"])
        if key in unique:
            unique[key]["objectives"].append(route["objective"])
        else:
            unique[key]=route
    routes=list(unique.values())
    costed=[r for r in routes if r["transport_cost"] is not None]
    best=min(costed,key=lambda r:(r["transport_cost"],r["travel_time_h"],r["objective"])) if costed else None
    if best:
        other=[r["transport_cost"] for r in costed if r is not best]
        advantage=min(other)-best["transport_cost"] if other else None
        best["reason"]=(f"Lowest modeled transport expense across {len(routes)} distinct saved road paths; "
                        + (f"₹{advantage:,.2f} less than the next costed path. " if advantage is not None else "Only one distinct costed path is available. ")
                        + f"{best['trips']} trip(s); not live traffic or verified truck access.")
        if advantage is not None and advantage<=max(1.,best["transport_cost"]*.01):
            best["reason"]+=" The cost difference is under a 1% scenario screen; treat the routes as practically similar until actual charges/access are confirmed."
    return origin,dest,routes,best


def make_scenario(buy,sell,request,kind,error):
    q=amount(request.quantity_quintals)
    owned=kind=="sell_owned"
    procurement=(money(q*amount(request.acquisition_rs_per_quintal)) if request.acquisition_rs_per_quintal is not None else None) if owned else money(q*amount(buy["predicted_modal_price"]))
    handling=money(q*amount(request.transport.handling_rs_per_quintal))
    missing=[]
    origin,dest,routes,best=(None,None,[],None) if kind in ("buy","store") else routes_between(buy,sell,request)
    if kind not in ("buy","store") and not best:
        if not origin:missing.append("No verified routing reference for the origin market.")
        if not dest:missing.append("Choose a destination with a supported routing reference.")
        if request.transport.load_capacity_quintals is None:missing.append("Enter vehicle load capacity.")
        if request.transport.market_access_km.get(buy['series_id']) is None:missing.append("Enter the origin market's access-road distance.")
        access=request.transport.market_access_km.get(sell['series_id']) if sell else request.transport.destination_access_km
        if access is None:missing.append("Enter the selling/delivery endpoint's access-road distance.")
        if request.transport.mode=='freight' and request.transport.freight_rs_per_tonne_km is None:missing.append("Enter a freight-rate assumption.")
        if request.transport.mode=='per_km' and request.transport.rs_per_vehicle_km is None:missing.append("Enter a vehicle-km rate assumption.")
        if request.transport.mode=='fuel' and (request.transport.fuel_rs_per_litre is None or request.transport.vehicle_km_per_litre is None):missing.append("Enter fuel price and vehicle efficiency.")
        if not missing:missing.append("No saved road path satisfies the route/distance constraints.")
    transport=best["transport_cost"] if best else None
    if kind=="store":
        missing.extend(["Verified storage suitability and available capacity are missing.","No separately validated future selling-price forecast.","Full market → facility → destination road legs are not verified."])
    outlay=(money(amount(procurement or 0)+amount(handling)) if kind=="buy" else
            money(amount(procurement or 0)+amount(transport)+amount(handling)) if transport is not None else None)
    revenue=money(q*amount(sell["predicted_modal_price"])) if sell and kind!="store" else None
    proceeds=money(amount(revenue)-amount(transport)-amount(handling)) if revenue is not None and transport is not None else None
    margin=money(amount(revenue)-amount(outlay)) if revenue is not None and outlay is not None and procurement is not None else None
    complete=not missing
    label="Sale proceeds exclude acquisition cost; profit is unknown." if owned and procurement is None else "Estimated scenario; excludes unmodeled spoilage, financing, tax, waiting and return travel."
    return {"scenario_id":f"{kind}:{buy['series_id']}:{sell['series_id'] if sell else request.destination or '-'}",
            "kind":kind,"buy":None if owned else identity(buy),"sell":identity(sell) if sell else None,
            "route_origin":origin,"route_destination":dest,"route":best,"routes":routes,
            "procurement_cost":procurement,"transport_cost":transport,"handling_cost":handling,"total_cost":outlay,
            "sale_revenue":revenue,"net_sale_proceeds":proceeds,"estimated_margin":margin,
            "complete":complete,"missing":missing,"uncertainty_screen_rs":money(q*amount(error)*2) if error is not None else None,
            "ranking":"point_estimate_only" if complete else "incomplete","explanation":label}


def compare(request:DecisionRequest):
    base=svc.compare(request)
    selected=svc.daily.today(request.series_id)
    prices=svc.eligible_prices(selected["crop"])
    compatible=[r for r in prices if all(r[k]==selected[k] for k in ("variety","grade","source"))]
    regional=[r for r in compatible if request.region=="all" or r["state"]==selected["state"]]
    buys=sorted(regional or compatible,key=lambda r:(r["predicted_modal_price"],r["series_id"]))[:8]
    sells=sorted(compatible,key=lambda r:(-r["predicted_modal_price"],r["series_id"]))
    if request.preferred_sell_series_id:
        sells=[r for r in sells if r["series_id"]==request.preferred_sell_series_id]
        if not sells:
            raise HTTPException(422,"The chosen selling market lacks a current compatible variety/grade forecast.")
    elif request.destination:
        sells=[r for r in sells if svc.reference_node(r["state"],r["district"])==request.destination]
    sells=sells[:8]
    historical=selected.get("historical_error") or svc.daily.error_information(selected["crop"])
    error=historical.get("mae") if historical else None
    scenarios=[]
    if request.objective in ("buy_now","compare_all"):
        scenarios.extend(make_scenario(b,None,request,"buy",error) for b in buys)
    if request.objective in ("buy_deliver","compare_all") and request.destination:
        scenarios.extend(make_scenario(b,None,request,"deliver",error) for b in buys)
    if request.objective=="sell_now":
        scenarios.extend(make_scenario(selected,s,request,"sell_owned",error) for s in sells if s["series_id"]!=selected["series_id"])
    if request.objective in ("buy_deliver","compare_all"):
        scenarios.extend(make_scenario(b,s,request,"trade",error) for b in buys for s in sells if b["series_id"]!=s["series_id"])
    if request.objective=="buy_store_sell":
        scenarios.extend(make_scenario(b,None,request,"store",error) for b in buys)
    complete=[s for s in scenarios if s["complete"]]
    kind="sell_owned" if request.objective=="sell_now" else "trade" if any(s["kind"]=="trade" and (s["estimated_margin"] or 0)>0 for s in complete) else "deliver" if request.destination else "buy"
    group=[s for s in complete if s["kind"]==kind]
    profit_kind=kind in ("trade","sell_owned")
    def score(s):
        return (s["net_sale_proceeds"] if kind=="sell_owned" else s["estimated_margin"]) if profit_kind else -s["total_cost"]
    group=sorted(group,key=lambda s:(-score(s),s["scenario_id"]))
    plan=group[0] if group else None
    if plan:
        screen=plan["uncertainty_screen_rs"]
        gap=score(plan)-score(group[1]) if len(group)>1 else None
        ranking=("margin_within_error_screen" if kind=="trade" and screen is not None and score(plan)<=screen else
                 "similar_within_error_screen" if screen is not None and gap is not None and gap<=screen else
                 "uncertainty_unavailable" if screen is None else "single_complete_scenario" if gap is None else "stronger_point_estimate")
        for row in group:
            row["ranking"]="similar_within_error_screen" if screen is not None and score(plan)-score(row)<=screen else "point_estimate_only"
        plan["ranking"]=ranking
        market=(plan["sell"] or plan["buy"])["market"]
        base["summary"]=(f"{market}: " + ("estimated net sale proceeds " if kind=="sell_owned" else "estimated scenario margin " if kind=="trade" else "estimated pickup subtotal " if kind=="buy" else "estimated cost ")
                         + f"₹{score(plan) if profit_kind else -score(plan):,.2f} for {request.quantity_quintals:g} quintals. "
                         + ("The margin is within the historical-error screen; a reliable trading advantage is not established." if ranking=="margin_within_error_screen" else
                            "The leading options are similar within a conservative historical-error screen; no clear winner is established." if ranking=="similar_within_error_screen" else
                            "This is the only complete scenario in its comparison group." if gap is None else "This is a point-estimate comparison, not a verified trading opportunity."))
        if kind=="buy":
            base["summary"]+=" Delivery and storage are not costed."
        if kind=="sell_owned" and plan["procurement_cost"] is None:
            base["summary"]+=" Acquisition cost is unknown; these sale proceeds are not profit."
        plan["explanation"]=base["summary"]+" "+plan["explanation"]
    elif request.objective=="buy_store_sell":
        base["summary"]="Storage-for-profit is unsupported: facility suitability, current space, full road legs and a validated future selling price are missing. Review candidates and costs in Storage Analysis."
    elif scenarios:
        base["summary"]="No complete scenario for this objective. Add the missing route, vehicle and access-cost inputs; available prices remain visible."
    base["cheapest_scenario_series_id"]=None  # v1 point-price winner is not a v2 uncertainty-aware recommendation.
    if plan and plan.get("buy"):
        plan_buy=next((p for p in prices if p["series_id"]==plan["buy"]["series_id"]),None)
        if plan_buy:
            base["storage"]=svc.storage_candidates(plan_buy,request)
    if request.transport.load_capacity_quintals is None:
        for market in base["markets"]:
            market["landed_cost"]=market["landed_per_quintal"]=None
    # Enrich the existing catalog without claiming a reverse warehouse road leg.
    links=svc.lg.node_warehouse()
    for w in base["storage"]:
        if request.destination and links is not None:
            match=links[(links.node_id==request.destination)&(links.warehouse_id==w["warehouse_id"])]
            if len(match):
                w["destination_to_facility_reference_km"]=float(match.iloc[0].road_distance_km)
        if request.transport.load_capacity_quintals is None:
            w["transport_cost"]=None;w["scenario_total"]=None
    if request.warehouse_id and request.warehouse_id not in {w["warehouse_id"] for w in base["storage"]}:
        raise HTTPException(422,"Choose a storage candidate from the current market's list.")
    anchor_sell=sells[0] if request.preferred_sell_series_id and sells else None
    analysis_buy=next((p for p in prices if plan and plan.get("buy") and p["series_id"]==plan["buy"]["series_id"]),selected)
    analysis_origin,analysis_dest,analysis_routes,_=routes_between(analysis_buy,anchor_sell,request)
    base["comparison_scope"]+=f" Scenario screen: {len(buys)} buying and {len(sells)} selling candidates; not a global optimum."
    return {**base,"objective":request.objective,"selling_markets":[{**identity(s),"predicted_price":s["predicted_modal_price"],"age_days":s["data_freshness"]["age_days"]} for s in sells],
            "scenarios":(group+[s for s in scenarios if s not in group])[:24],"plan":plan,
            "uncertainty":{"mae_rs_per_quintal":error,"period":"2017–2018 development simulation" if error is not None else None,
                           "method":"twice crop-level MAE × quantity; a conservative economic screen, NOT a confidence interval or market-specific validation",
                           "calibrated":False},"assumptions":request.model_dump(),"warehouse_selection":request.warehouse_id,
            "analysis_routes":analysis_routes,"analysis_origin":analysis_origin,"analysis_destination":analysis_dest,
            "location_evidence":{"origin":location_evidence(plan["route_origin"] if plan and plan["route_origin"] else analysis_origin),
                                 "destination":location_evidence(plan["route_destination"] if plan and plan["route_destination"] else analysis_dest)},
            "future_revenue":None,"potential_net_margin":None,
            "provenance":{"forecast_issue_timestamp":selected.get("forecast_issue_timestamp"),"dataset_version":selected.get("dataset_version"),
                          "model_version":selected.get("model_version"),"price_unit":"INR/quintal","prices":"approved current daily batch", "roads":"pinned OSM / Geofabrik outputs; district references, not market entrances"},
            "status":"scenario_comparison" if plan else base["status"]}
