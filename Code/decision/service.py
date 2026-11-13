"""Read-only comparisons over approved daily batches and existing OSM outputs.

No market is relocated to a district point. Routes are explicitly reference-point
scenarios with independently entered access-road distances, never verified trips.
"""
import json
import pandas as pd
from Code.api import daily, logistics as lg
from Code.daily.policy import now_ist
from .contracts import DecisionRequest
from .costs import amount, money, storage_cost, transport_cost, validate_access,trip_count


def eligible_prices(crop):
    manifest, registry, batch, pointer = daily.snapshot()
    if pointer["target_date"] != str(now_ist().date()):
        return []
    if pd.Timestamp(pointer["issue"]) > pd.Timestamp(now_ist()):
        return []
    with batch.connect() as db:
        rows = [json.loads(r[0]) for r in db.execute("SELECT payload FROM predictions WHERE price IS NOT NULL")]
    return [r for r in rows if r["crop"] == crop and r["status"] in ("prediction_available", "stale_prediction")
            and r["target_date"] == str(now_ist().date())]


def reference_node(state, district):
    n = lg.routing_nodes()
    match = n[(n.state == state) & (n.district == district) & (n.verification == "passed")]
    return None if len(match) != 1 else str(match.iloc[0].node_id)


def options(crop):
    daily.crop_rows(crop)  # validates the selected empirical catalog
    prices = eligible_prices(crop)
    markets=[{**{k:r[k] for k in ("series_id","crop","state","district","market","variety","grade")},
              "reference_node":reference_node(r["state"],r["district"])} for r in prices]
    return {"eligible_markets": sorted(markets,key=lambda r:(r["reference_node"] is None,r["state"],r["district"],r["market"],r["variety"])),
            "eligible_count": len(prices), "target_date": str(now_ist().date()),
            "destinations": lg._records(lg.routing_nodes()[["node_id","name","state","district","latitude","longitude"]]),
            "destination_note": "Verified district reference points, not exact delivery addresses."}


def route_options(origin, dest, sid, request):
    assumptions = request.transport
    matrix = lg.od()
    if not origin or not dest or matrix is None:
        return []
    if origin == dest:
        # Zero is between the same reference point, not between two market addresses.
        records = [{"objective":o,"road_distance_km":0.,"travel_time_h":0.} for o in ("shortest","fastest")]
    else:
        records = matrix[(matrix.origin_id==origin)&(matrix.dest_id==dest)&(matrix.status=="ok")].to_dict("records")
    access = assumptions.market_access_km.get(sid)
    destination_access = assumptions.destination_access_km
    result=[]
    for r in records:
        distance = (r["road_distance_km"]+access+destination_access
                    if access is not None and destination_access is not None else None)
        cost,fuel = transport_cost(distance,request.quantity_quintals,assumptions)
        result.append({"objective":r["objective"],"road_distance_km":float(r["road_distance_km"]),
                       "travel_time_h":float(r["travel_time_h"]),"transport_cost":cost,"fuel_expense":fuel,
                       "trips":trip_count(request.quantity_quintals,assumptions),
                       "cost_per_quintal":money(amount(cost)/amount(request.quantity_quintals)) if cost is not None else None})
    return result


def market_option(row, selected, request):
    sid=row["series_id"]
    origin=reference_node(row["state"],row["district"])
    routes=route_options(origin,request.destination,sid,request)
    priced=[r for r in routes if r["transport_cost"] is not None]
    best=min(priced,key=lambda r:(r["transport_cost"],r["travel_time_h"],r["objective"])) if priced else None
    comparable=all(row[k]==selected[k] for k in ("variety","grade","source"))
    buying=money(amount(row["predicted_modal_price"])*amount(request.quantity_quintals))
    landed=money(amount(buying)+amount(best["transport_cost"])+amount(request.quantity_quintals)*amount(request.transport.handling_rs_per_quintal)) if best and comparable else None
    return {**{k:row[k] for k in ("series_id","crop","state","district","market","variety","grade")},
            "predicted_price":row["predicted_modal_price"],"age_days":row["data_freshness"]["age_days"],
            "comparable":comparable,"reference_node":origin,"procurement_cost":buying,"landed_cost":landed,
            "landed_per_quintal":money(amount(landed)/amount(request.quantity_quintals)) if landed is not None else None,
            "best_route":best["objective"] if best else None,"routes":routes,
            "limitation":("Different variety or grade; switch selection before comparing costs." if not comparable else
                           "District-reference scenario; market coordinates and vehicle capacity are unverified." if landed is not None else
                           "Add a destination, transport rate and access-road distances to calculate a scenario." if origin else
                           "No verified district road reference for this market.")}


def storage_candidates(selected, request):
    origin=reference_node(selected["state"],selected["district"])
    wh, links = lg.warehouses(), lg.node_warehouse()
    if not origin or wh is None or links is None:
        return []
    near=links[links.node_id==origin].sort_values("road_distance_km").head(5).merge(wh,on="warehouse_id")
    result=[]
    for row in near.to_dict("records"):
        access=request.transport.market_access_km.get(selected["series_id"])
        facility_access=request.transport.warehouse_access_km.get(row["warehouse_id"])
        distance=row["road_distance_km"]+access+facility_access if access is not None and facility_access is not None else None
        transport,_=transport_cost(distance,request.quantity_quintals,request.transport)
        storage=storage_cost(request.quantity_quintals,request.storage_days,request.storage_rs_per_tonne_month)
        # Separate alternative: market -> warehouse, NOT destination -> warehouse.
        total=(amount(selected["predicted_modal_price"])*amount(request.quantity_quintals)+amount(transport)+amount(storage)
               +amount(request.quantity_quintals)*amount(request.transport.handling_rs_per_quintal)) if transport is not None and storage is not None and selected["predicted_modal_price"] is not None else None
        result.append({"warehouse_id":row["warehouse_id"],"name":row["name"],"facility_type":row["facility_type"],
                       "source":row.get("source"),"source_update_date":lg._snapshot_date() if row.get("source") else None,"operator":row.get("operator_class"),
                       "latitude":row["latitude"],"longitude":row["longitude"],"reference_road_distance_km":row["road_distance_km"],
                       "transport_cost":transport,"storage_cost":storage,"scenario_total":money(total) if total is not None else None,
                       "storage_cost_basis":"user_assumption" if storage is not None else "unknown"})
    return result


def compare(request: DecisionRequest):
    validate_access(request.transport)
    selected=daily.today(request.series_id)
    if request.destination and request.destination not in set(lg.routing_nodes().node_id):
        from fastapi import HTTPException
        raise HTTPException(404,"Unsupported destination reference point")
    prices=eligible_prices(selected["crop"])
    regional=[r for r in prices if request.region=="all" or r["state"]==selected["state"]]
    # The only available alternatives may lie outside the currently selected state.
    candidates=regional or prices
    rows=[market_option(r,selected,request) for r in candidates]
    comparable=[r for r in rows if r["comparable"]]
    costed=[r for r in comparable if r["landed_cost"] is not None]
    ordered=sorted(comparable or rows,key=lambda r:(r["landed_cost"] is None,r["landed_cost"] if r["landed_cost"] is not None else r["predicted_price"],r["series_id"]))
    best=min(costed,key=lambda r:(r["landed_cost"],r["series_id"])) if len(costed)>=2 else None
    chosen=next((r for r in rows if r["series_id"]==request.series_id),None)
    if best:
        summary=f"{best['market']} has the lowest estimated landed cost among {len(costed)} costed comparable series: ₹{best['landed_cost']:,.2f} for {request.quantity_quintals:g} quintals. Confirm access roads, freight and supply before buying."
    elif len(costed)==1:
        only=costed[0]
        summary=f"{only['market']} has an estimated landed cost of ₹{only['landed_cost']:,.2f} for {request.quantity_quintals:g} quintals under your assumptions. Only one comparable market is fully costed, so a lowest-cost buying recommendation is unavailable."
    elif comparable:
        summary="Compare available price estimates below. A buying recommendation needs complete delivery costs; the lowest mandi price alone is not the lowest landed cost."
    elif rows:
        summary="No matching forecast is available for this selection. Switch to an eligible market below; its variety or grade may differ."
    else:
        summary="No eligible current forecasts for this crop. Try another supported crop or return after the data refresh."
    return {"target_date":str(now_ist().date()),"quantity_quintals":request.quantity_quintals,"quantity_tonnes":request.quantity_quintals/10,
            "markets":ordered[:5],"selected":chosen,"storage":storage_candidates(selected,request),
            "comparison_scope":f"{'Selected state' if regional and request.region=='state' else 'All available states'}; {len(rows)} eligible series, {len(comparable)} matching variety/grade/source, {len(costed)} fully costed; top five shown.",
            "summary":summary,"status":"scenario_comparison" if best else "price_comparison" if rows else "unavailable",
            "cheapest_scenario_series_id":best["series_id"] if best else None,
            "limitations":["Costs use user-entered one-trip assumptions; vehicle capacity and market supply are unverified.",
                            "Road distance and travel time cover district reference points; access legs are entered separately. No live traffic.",
                            "Storage locations are reported, unverified candidates; crop suitability, availability, capacity and tariffs are unknown.",
                            "No validated future selling-price forecast: revenue and profit are unavailable.",
                            "Taxes, spoilage, shrinkage, financing, waiting and return travel are unmodeled.",
                            "Historical crop-level errors are not calibrated market-level confidence intervals."]}
