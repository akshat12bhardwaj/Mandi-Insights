from fastapi import APIRouter,HTTPException
from Code.api import daily,logistics as lg
from Code.daily.policy import commodity
from Code.decision import service,weather,trading,weather_context as wx
from Code.decision.contracts import DecisionRequest,DecisionResponse,DecisionOptions,WeatherContext,TradingResponse

router=APIRouter(prefix="/api/v3/decisions",tags=["Decision scenarios"])


@router.post("/trading",response_model=TradingResponse)
def trading_decision(request:DecisionRequest):
    try:
        return trading.compare(request)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc


@router.get("/options",response_model=DecisionOptions)
def options(crop:str):
    return service.options(commodity(crop))


@router.post("/compare",response_model=DecisionResponse)
def compare(request:DecisionRequest):
    try:
        return service.compare(request)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc


@router.get("/weather",response_model=WeatherContext)
def weather_context(series_id:str,warehouse_id:str|None=None):
    prediction=daily.today(series_id)
    nid=service.reference_node(prediction["state"],prediction["district"])
    result={**weather.metadata(),"available":False,"days":[],"reference_node":nid,
            "coverage":"District reference point; not market-site measurements."}
    if warehouse_id:
        facilities=lg.warehouses()
        match=facilities[facilities.warehouse_id==warehouse_id] if facilities is not None else None
        if match is None or match.empty:
            raise HTTPException(404,"Unknown storage facility")
        import hashlib
        facility=match.iloc[0]
        return {**result,**wx.context("facility_"+hashlib.sha256(warehouse_id.encode()).hexdigest()[:20],float(facility.latitude),float(facility.longitude)),
                "coverage":"OSM-reported facility coordinates, unverified; outdoor model forecast, not indoor storage conditions.","reference_node":None,"used_in_price_model":False}
    if not nid:
        return {**result,"context_reason":"No verified nearby weather reference for this market."}
    from Code.api.main import point_key
    row=lg.routing_nodes().set_index("node_id").loc[nid]
    fc=wx.context(point_key(row.state,row.district),float(row.latitude),float(row.longitude))
    # New context may be retrieved AFTER price issuance; it never changes that forecast.
    return {**result,**fc,"used_in_price_model":False,"context_reason":fc.get("reason"),
            "heavy_rain_days":lg.fc.flags(fc.get("days",[])),
            "price_forecast_issue":prediction["forecast_issue_timestamp"]}


@router.get("/warehouse-catalog")
def warehouse_catalog():
    facilities=lg.warehouses()
    if facilities is None:
        return {"facilities":[],"note":"Catalog unavailable"}
    records=lg._records(facilities)
    for facility in records:
        facility["facility_coordinate"]={"latitude":facility["latitude"],"longitude":facility["longitude"],"status":facility["location_status"],"method":facility["coord_method"]}
        facility["road_access_coordinate"]=None
    return {"facilities":records,"note":"Existing OSM identities retained; nominal and available capacity remain distinct. Coordinates are reported points/area centroids, not verified road entrances.",
            "official_sources":[{"name":"CWC regional offices","url":"https://cewacor.in/CWCRegionalOffices","status":"Reviewed; linked warehouse pages returned errors; no new facility facts accepted"},
                                {"name":"WDRA / DFPD","url":"https://dfpd.gov.in/warehousing-development-regulatory-authority/en","status":"Reviewed; no usable facility-level register obtained"}]}
