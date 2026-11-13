import { Weather } from "./PlaceWeather";
import { Link } from "react-router-dom";
import { number, params, useIntelligence, type Facility } from "../lib/intelligence";
import type { Environment, ReportedSeries } from "../lib/market-intelligence";

export interface StorageCompatibility {
  crop: string;
  category: string;
  storage_class: string;
  requirements: string;
}
export interface NearbyMarket extends ReportedSeries {
  coordinate: { lat: number; lng: number };
  distance_km: number;
  distance_basis: string;
}
export interface NearbyMarkets { rows: NearbyMarket[]; radius_km: number }

export function WarehouseDetails({ facility, nearby, error, loading }: {
  facility: Facility; nearby?: NearbyMarkets; error: boolean; loading: boolean;
}) {
  const path = "warehouses/" + encodeURIComponent(facility.warehouse_id);
  const environment = useIntelligence<Environment>(path + "/environment");
  return <>
    <Weather env={environment.data} loading={environment.isFetching} error={!!environment.error} retry={() => void environment.refetch()} />
    <details className="mi-series-details" open>
      <summary>Nearby markets & roads</summary>
      {error ? <p className="mi-note">Nearby-market data could not load. Try reselecting the facility.</p> :
        loading ? <p className="mi-note">Finding nearby markets…</p> :
        !nearby?.rows.length ? <p className="mi-note">No mapped markets in the project's screening area.</p> :
        <><p className="mi-note">Within {nearby.radius_km} km straight-line distance. Pins show market references.</p>
          {nearby.rows.map(row => <div className="mi-connection" key={row.series_id}><div>
            <Link className="mi-text-link" to={"/markets?" + params({ crop: row.crop, series: row.series_id, state: row.state })}>{row.market}</Link>
            <span>{number(row.distance_km)} km · {row.district}, {row.state}</span><small>{row.distance_basis}</small>
          </div></div>)}</>}
    </details>
  </>;
}
