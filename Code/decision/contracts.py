from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Transport(Contract):
    mode: Literal["freight", "fuel", "per_km"] = "freight"
    vehicle_type: str = Field("Goods vehicle (user assumption)",max_length=80)
    load_capacity_quintals: float | None = Field(None,gt=0,le=100000)
    rs_per_vehicle_km: float | None = Field(None,ge=0,le=10000)
    toll_rs_per_trip: float = Field(0,ge=0,le=1e6)
    freight_rs_per_tonne_km: float | None = Field(None, ge=0, le=10000)
    fuel_rs_per_litre: float | None = Field(None, ge=0, le=1000)
    vehicle_km_per_litre: float | None = Field(None, gt=0, le=100)
    fixed_trip_rs: float = Field(0, ge=0, le=1e8)
    handling_rs_per_quintal: float = Field(0, ge=0, le=1e6)
    destination_access_km: float | None = Field(None, ge=0, le=1000)
    market_access_km: dict[str, float] = Field(default_factory=dict, max_length=100)
    warehouse_access_km: dict[str, float] = Field(default_factory=dict, max_length=100)


class DecisionRequest(Contract):
    series_id: str = Field(min_length=1, max_length=100)
    quantity_quintals: float = Field(10, gt=0, le=1000000)
    destination: str | None = Field(None, max_length=150)
    region: Literal["state", "all"] = "state"
    transport: Transport = Field(default_factory=Transport)
    storage_days: int = Field(30, ge=1, le=365)
    storage_rs_per_tonne_month: float | None = Field(None, ge=0, le=1e6)
    objective: Literal["buy_now","sell_now","buy_deliver","buy_store_sell","compare_all"] = "buy_deliver"
    preferred_sell_series_id: str | None = Field(None,max_length=100)
    acquisition_rs_per_quintal: float | None = Field(None,ge=0,le=1e7)
    max_transport_km: float | None = Field(None,ge=0,le=10000)
    warehouse_id: str | None = Field(None,max_length=150)


class RouteOption(Contract):
    objective: Literal["shortest", "fastest"]
    road_distance_km: float
    travel_time_h: float
    transport_cost: float | None
    fuel_expense: float | None
    cost_per_quintal: float | None
    trips: int | None = None


class MarketOption(Contract):
    series_id: str
    crop: str
    state: str
    district: str
    market: str
    variety: str
    grade: str
    predicted_price: float
    age_days: int
    comparable: bool
    reference_node: str | None
    procurement_cost: float
    landed_cost: float | None
    landed_per_quintal: float | None
    best_route: str | None
    routes: list[RouteOption]
    limitation: str


class StorageOption(Contract):
    warehouse_id: str
    name: str
    facility_type: str
    latitude: float
    longitude: float
    reference_road_distance_km: float
    transport_cost: float | None
    storage_cost: float | None
    storage_cost_basis: Literal["user_assumption", "unknown"]
    scenario_total: float | None
    suitability: Literal["unknown"] = "unknown"
    available_capacity_t: None = None
    recommendation: Literal["candidate_only"] = "candidate_only"
    source: str | None = None
    source_update_date: str | None = None
    operator: str | None = None
    nominal_capacity_t: float | None = None
    coordinate_status: str = "reported_unverified"
    cold_storage_confirmed: bool | None = None
    destination_to_facility_reference_km: float | None = None
    distance_to_destination_km: float | None = None
    reason: str = "Ranked by reference road distance; suitability and availability require confirmation."


class TradingScenario(Contract):
    scenario_id: str
    kind: Literal["buy","deliver","trade","sell_owned","store"]
    buy: EligibleMarket | None = None
    sell: EligibleMarket | None = None
    route_origin: str | None = None
    route_destination: str | None = None
    route: dict | None = None
    routes: list[dict] = Field(default_factory=list)
    procurement_cost: float | None
    transport_cost: float | None
    handling_cost: float
    total_cost: float | None
    sale_revenue: float | None = None
    net_sale_proceeds: float | None = None
    estimated_margin: float | None = None
    complete: bool
    missing: list[str]
    uncertainty_screen_rs: float | None = None
    ranking: str = "incomplete"
    explanation: str


class DecisionResponse(Contract):
    version: Literal["decision-scenarios-v1"] = "decision-scenarios-v1"
    target_date: str
    quantity_quintals: float
    quantity_tonnes: float
    markets: list[MarketOption]
    storage: list[StorageOption]
    selected: MarketOption | None
    comparison_scope: str
    summary: str
    status: Literal["scenario_comparison", "price_comparison", "unavailable"]
    cheapest_scenario_series_id: str | None
    future_revenue: None = None
    potential_net_margin: None = None
    limitations: list[str]


class EligibleMarket(Contract):
    series_id: str
    crop: str
    state: str
    district: str
    market: str
    variety: str
    grade: str
    reference_node: str | None


class Destination(Contract):
    node_id: str
    name: str
    state: str
    district: str
    latitude: float
    longitude: float


class DecisionOptions(Contract):
    eligible_markets: list[EligibleMarket]
    eligible_count: int
    target_date: str
    destinations: list[Destination]
    destination_note: str


class WeatherContext(BaseModel):
    available: bool
    kind: str = "current_forecast_context"
    used_in_price_model: Literal[False]
    daily_validation: str
    reason: str | None
    archive_note: str
    prior_evidence: str
    comparison_status: dict[str, str]
    feature_version: str
    reference_node: str | None
    coverage: str
    context_reason: str | None = None
    days: list[dict]
    stale: bool = False
    retrieved_utc: str | None = None
    attribution: dict | None = None
    price_forecast_issue: str | None = None
    heavy_rain_days: list[dict] = Field(default_factory=list)


class TradingResponse(DecisionResponse):
    version: Literal["trading-scenarios-v2"] = "trading-scenarios-v2"
    objective: str
    selling_markets: list[dict]
    scenarios: list[TradingScenario]
    plan: TradingScenario | None
    uncertainty: dict
    assumptions: dict
    warehouse_selection: str | None = None
    provenance: dict
    analysis_routes: list[dict]
    analysis_origin: str | None
    analysis_destination: str | None
    location_evidence: dict
