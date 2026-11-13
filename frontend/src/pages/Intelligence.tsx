import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Truck } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { MapView, type MapPoint } from "../components/MapView";
import { useRegionalWeather } from "../components/RegionalWeather";
import { WarehouseDetails, type StorageCompatibility, type NearbyMarkets } from "../components/WarehouseDetails";
import {
  useIntelligence,
  request,
  params,
  rupees,
  number,
  type Facility,
  type Strategy,
} from "../lib/intelligence";

function Select({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  children: ReactNode;
}) {
  return (
    <label className="mi-field">
      <span>{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {children}
      </select>
    </label>
  );
}
function Input({
  label,
  value,
  onChange,
  min = 0,
  max = 100000,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
}) {
  return (
    <label className="mi-field">
      <span>{label}</span>
      <input
        aria-label={label}
        type="number"
        step="any"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}
function Message({
  error,
  loading,
  empty,
  onRetry,
}: {
  error?: Error | null;
  loading?: boolean;
  empty?: string;
  onRetry?: () => void;
}) {
  if (error)
    return (
      <div role="alert" className="mi-message">
        {error.message}{" "}
        <button type="button" onClick={onRetry}>
          Try again
        </button>
      </div>
    );
  if (loading)
    return (
      <div role="status" className="mi-message">
        Loading market intelligence…
      </div>
    );
  return empty ? <div className="mi-message">{empty}</div> : null;
}
export function Heading({ title, text }: { title: string; text: string }) {
  return <header className="mi-heading"><div><h1>{title}</h1><p>{text}</p></div></header>;
}

function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="mi-metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </div>
  );
}
export function StrategyDetail({ strategy: direct, route, onRoute, onRoadReady }: {
  strategy: Strategy; route: Strategy["route"]; onRoute: (objective: string) => void; onRoadReady: () => void;
}) {
  const [showConditions, setShowConditions] = useState(false);
  const transportDelta = route.transport_cost - direct.transport;
  const journeyPath = "journey-path?" + params({
    origin: route.origin, destination: route.destination, objective: route.objective === "fastest" ? "fastest" : "shortest",
    warehouse_id: direct.warehouse?.warehouse_id,
  });
  const geometry = useQuery({
    queryKey: ["journey-path", journeyPath],
    queryFn: () => request<{ geometry: [number, number][] | null; stop_index?: number; road_km?: number; source?: string }>(journeyPath),
    enabled: !route.geometry?.length, staleTime: Infinity,
  });
  const needsRepricing = !!direct.schedule && (route.objective === "approximate" || route.objective === "via_storage") && !route.geometry?.length;
  const line = route.geometry || (needsRepricing ? undefined : geometry.data?.geometry);
  useEffect(() => {
    if (needsRepricing && geometry.data?.geometry?.length) onRoadReady();
  }, [needsRepricing, geometry.data]);
  const conditions = useIntelligence<{ samples: { name: string; current: { temperature_c: number | null } | null; outlook: { rain_mm: number | null }[] }[] }>(
    "route-conditions?" + params({ origin: route.origin, destination: route.destination, objective: route.objective, warehouse_id: direct.warehouse?.warehouse_id }),
    showConditions,
  );
  const points = useMemo<MapPoint[]>(() => {
    const places: MapPoint[] = [direct.buy, direct.sell].flatMap((m, id) => m.coordinate ? [{
      id, lat: m.coordinate.lat, lng: m.coordinate.lng, label: (id ? "Destination · " : "Origin · ") + m.market, tone: id ? "ink" : "ok", kind: "market",
    }] : []);
    if (direct.warehouse) places.push({ id: 2, lat: direct.warehouse.latitude, lng: direct.warehouse.longitude,
      label: direct.warehouse.name, tone: "ink", kind: "warehouse" });
    return places;
  }, [direct]);
  const expenses = direct.total_cost + transportDelta;
  const margin = direct.margin - transportDelta;
  return <section className="mi-detail mi-panel-enter">
    <div className="mi-detail-grid">
      <div className="mi-route-map">
        <MapView points={points} line={line} truck={!!line?.length} stopIndex={route.stop_index ?? geometry.data?.stop_index} compact
          className="h-full min-h-[340px]" fitKey={direct.id + route.objective + (direct.warehouse?.warehouse_id || "")} ariaLabel="Trade route map" />
        <div className="mi-map-caption" role="status">{line?.length
          ? `Illustrated road journey · ${route.basis.startsWith("Local directed") ? "Local OpenStreetMap road graph" : geometry.data?.source || "Saved OpenStreetMap route"}`
          : geometry.isFetching ? "Finding a road path…" : "Market references · road path unavailable"}</div>
        {!line?.length && !geometry.isFetching && <div className="mi-journey-fallback" aria-label="Schematic journey">
          <Truck size={18} aria-hidden /><span>{direct.buy.market}</span><span aria-hidden>→</span>
          {direct.warehouse && <><span>{direct.warehouse.name}</span><span aria-hidden>→</span></>}
          <span>{direct.sell.market}</span>
        </div>}
      </div>
      <div className="mi-costs mi-financial">
        <h3>Journey finances</h3>
        <p className="mi-trip-stats">{direct.buy.market} → {direct.sell.market}</p>
        <p className="mi-trip-stats">{direct.warehouse ? "Via " + direct.warehouse.name : "Direct delivery"}</p>
        <dl className="mi-financial-totals">
          <div><dt>Estimated net margin</dt><dd>{rupees(margin)}</dd></div>
          <div><dt>Total estimated cost</dt><dd>{rupees(expenses)}</dd></div>
          <div><dt>Estimated selling revenue</dt><dd>{rupees(direct.sale_revenue)}</dd></div>
        </dl>
        <dl className="mi-financial-lines">
          <div><dt>Procurement</dt><dd>{rupees(direct.procurement)}</dd></div>
          <div><dt>Transportation</dt><dd>{rupees(route.transport_cost)}</dd></div>
          {direct.handling > 0 && <div><dt>Loading and unloading</dt><dd>{rupees(direct.handling)}</dd></div>}
          {direct.storage > 0 && <div><dt>Storage · {direct.storage_days} days</dt><dd>{rupees(direct.storage)}</dd></div>}
        </dl>
        <p className="mi-trip-stats">{number(route.km)} km · about {number(route.hours)} h per trip · {direct.trips} {direct.trips === 1 ? "trip" : "trips"}</p>
        {direct.routes.length > 1 && <div className="mi-route-options" role="group" aria-label="Compare routes">
          {direct.routes.map(r => <button key={r.objective} className="mi-secondary" aria-pressed={route.objective === r.objective}
            onClick={() => onRoute(r.objective)}>{r.objective === "fastest" ? "Fastest estimate" : "Shortest distance"}<small>{number(r.hours)} h · {rupees(r.transport_cost)}</small></button>)}
        </div>}
        <details className="mi-series-details" onToggle={e => setShowConditions(e.currentTarget.open)}>
          <summary>Weather along the route</summary>
          {showConditions && (conditions.data?.samples.length ? conditions.data.samples.map(sample =>
            <p key={sample.name}><strong>{sample.name}</strong> · {sample.current?.temperature_c == null ? "Temperature unavailable" : number(sample.current.temperature_c) + "°C"}{sample.outlook[0]?.rain_mm != null && " · " + number(sample.outlook[0].rain_mm) + " mm forecast rain"}</p>
          ) : <p>{conditions.isPending ? "Checking route weather…" : "Route weather unavailable."}</p>)}
        </details>
      </div>
    </div>
  </section>;
}

export function WarehousesExplorer() {
  const weather = useRegionalWeather();
  const [url] = useSearchParams();
  const [crop, setCrop] = useState(url.get("facility") ? "" : url.get("crop") || "");
  const [state, setState] = useState("");
  const [kind, setKind] = useState("");
  const [free, setFree] = useState(0);
  const [marketSearch, setMarketSearch] = useState("");
  const [selected, setSelected] = useState(url.get("facility") || "");
  const [group, setGroup] = useState<number[]>([]);
  const filters = params({ crop, state, kind, min_free_t: free, market_search: marketSearch });
  const query = useIntelligence<{ rows: Facility[]; states: string[]; compatibility: StorageCompatibility[] }>("warehouses?" + filters);
  const rows = query.data?.rows || [];
  const active = selected ? rows.find(r => r.warehouse_id === selected) : undefined;
  const nearby = useIntelligence<NearbyMarkets>("warehouses/" + encodeURIComponent(selected) + "/nearby-markets", !!active);
  const reset = () => { setSelected(""); setGroup([]); };
  const select = (id: number) => { setSelected(rows[id].warehouse_id); setGroup([]); };
  const points: MapPoint[] = rows.map((r, i) => ({
    id: i, lat: r.latitude, lng: r.longitude, label: r.name + ", " + r.district_reference,
    kind: "warehouse", tone: r.occupancy_pct >= 85 ? "muted" : "ok",
  }));
  const neighbors: MapPoint[] = (nearby.data?.rows || []).filter(r => r.coordinate).map((r, i) => ({
    id: -1 - i, ...r.coordinate, label: r.market, kind: "market", tone: "ink",
  }));
  const [marketGroup, setMarketGroup] = useState(false);
  return <div className="mi-page">
    <Heading title="Room for the next step." text="Explore storage facilities, shared capacity and nearby mandis." />
    <div className="mi-toolbar">
      <Select label="State" value={state} onChange={v => { setState(v); reset(); }}><option value="">All states</option>{query.data?.states.map(s => <option key={s}>{s}</option>)}</Select>
      <Select label="Storage type" value={kind} onChange={v => { setKind(v); reset(); }}><option value="">All types</option><option value="dry">Dry storage</option><option value="ventilated">Ventilated</option><option value="cold">Cold storage</option></Select>
      <Select label="Crop compatibility" value={crop} onChange={v => { setCrop(v); reset(); }}><option value="">All crops</option>{query.data?.compatibility?.filter(r => r.storage_class !== "unsupported").map(r => <option key={r.crop}>{r.crop}</option>)}</Select>
      <Input label="Minimum free capacity (tonnes)" value={free} onChange={v => { setFree(v); reset(); }} />
      <label className="mi-field"><span>Near a market</span><input type="search" maxLength={100} value={marketSearch} onChange={e => { setMarketSearch(e.target.value); reset(); }} /></label>
    </div>
    <Message loading={query.isPending} error={query.error} onRetry={() => void query.refetch()} empty={query.data && !rows.length ? "No facilities match these filters." : undefined} />
    <div className="mi-explore-grid mi-map-first">
      <section className="mi-panel mi-market-map">
        <div className="mi-section-heading"><h2>Warehouse map</h2><span>{rows.length} facilities</span></div>
        <MapView weather={weather} points={[...points, ...neighbors]} selectedId={active ? rows.indexOf(active) : undefined} onSelect={id => id < 0 ? setMarketGroup(true) : select(id)} onGroupSelect={ids => ids[0] < 0 ? setMarketGroup(true) : setGroup(ids)} compact fitKey={filters + ":" + rows.length} className="mi-discovery-map" ariaLabel="Warehouse map" />
        <p className="mi-note">Muted warehouse pins indicate high simulated occupancy. Shop pins show nearby markets. Weather icons show regional forecasts.</p>
        {!!group.length && <div className="mi-map-choices">{group.map(id => <button key={id} onClick={() => select(id)}>{points[id]?.label}</button>)}</div>}
        {marketGroup && active && <div className="mi-map-choices">
          {nearby.data?.rows.map(r => <Link key={r.series_id} to={"/markets?" + params({ crop: r.crop, series: r.series_id })}>{r.market}</Link>)}
          <button onClick={() => setMarketGroup(false)}>Close nearby markets</button>
        </div>}
      </section>
      <section key={active?.warehouse_id} className="mi-panel mi-market-profile mi-panel-enter">
        {active ? <>
          <h2>{active.name}</h2><p>{active.district_reference}, {active.region} · {active.storage_class} storage</p>
          <p className="mi-note">{active.latitude.toFixed(3)}°N, {active.longitude.toFixed(3)}°E · reported facility reference</p>
          <Occupancy facility={active} />
          <div className="mi-capacity-grid"><Metric label="Total" value={number(active.total_t) + " t"} /><Metric label="Occupied" value={number(active.occupied_t) + " t"} /><Metric label="Free" value={number(active.free_t) + " t"} /></div>
          <p className="mi-note">{number(active.free_t / active.total_t * 100)}% available · {active.capacity_basis} · occupancy simulated weekly</p>
          <p>{rupees(active.rs_q_day, 2)}/quintal/day estimated · up to {active.max_days} days modeled</p>
          <WarehouseDetails key={active.warehouse_id} facility={active} nearby={nearby.data} error={!!nearby.error} loading={nearby.isPending} />
          {url.get("crop") && active.supported_crops.includes(url.get("crop")!) && <Link className="mi-secondary" to={"/?" + params({
            crop: url.get("crop") || undefined, buy: url.get("series") || undefined,
            sell: url.get("sell") || undefined, warehouse: active.warehouse_id, quantity: url.get("quantity") || undefined,
          })}>Compare this storage option</Link>}
        </> : <p className="mi-note">{selected && query.data ? "The selected facility is unavailable in these results." : "Select a warehouse pin to inspect a facility."}</p>}
      </section>
    </div>
  </div>;
}
function Occupancy({ facility: w }: { facility: Facility }) {
  return (
    <div className="mi-occupancy">
      <div>
        <span>Storage utilization · {w.occupancy_pct}%</span>
        <small>{w.status}</small>
      </div>
      <progress
        value={w.occupancy_pct}
        max="100"
        aria-label={`${w.name} occupancy`}
      />
    </div>
  );
}
