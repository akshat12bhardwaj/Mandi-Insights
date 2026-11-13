"""Deterministic INR scenarios; quantity is quintals (10 quintals = 1 tonne)."""
from decimal import Decimal, ROUND_HALF_UP
import math
from .contracts import Transport


def amount(value):
    return Decimal(str(value))


def money(value):
    return float(amount(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def transport_cost(km, quantity, assumptions: Transport):
    if km is None:
        return None, None
    distance, tonnes = amount(km), amount(quantity)/10
    trips = trip_count(quantity,assumptions) or 1  # Legacy v1 compatibility; v2 withholds costs without capacity.
    if assumptions.mode == "freight":
        if assumptions.freight_rs_per_tonne_km is None:
            return None, None
        variable = distance*tonnes*amount(assumptions.freight_rs_per_tonne_km)
        fuel = None  # An inclusive freight rate is never added to a fuel estimate.
    elif assumptions.mode == "per_km":
        if assumptions.rs_per_vehicle_km is None:
            return None,None
        variable=distance*trips*amount(assumptions.rs_per_vehicle_km)
        fuel=None
    else:
        if assumptions.fuel_rs_per_litre is None or assumptions.vehicle_km_per_litre is None:
            return None, None
        variable = distance*trips/amount(assumptions.vehicle_km_per_litre)*amount(assumptions.fuel_rs_per_litre)
        fuel = money(variable)
    return money(variable+trips*(amount(assumptions.fixed_trip_rs)+amount(assumptions.toll_rs_per_trip))), fuel


def trip_count(quantity,assumptions):
    if assumptions.load_capacity_quintals is None:
        return None
    from decimal import ROUND_CEILING
    return int((amount(quantity)/amount(assumptions.load_capacity_quintals)).to_integral_value(rounding=ROUND_CEILING))


def storage_cost(quantity, days, rate):
    return None if rate is None else money(amount(quantity)/10*amount(days)/30*amount(rate))


def validate_access(assumptions):
    for distances in (assumptions.market_access_km, assumptions.warehouse_access_km):
        if any(not math.isfinite(v) or not 0 <= v <= 1000 for v in distances.values()):
            raise ValueError("Access road distances must be finite and between 0 and 1000 km")
