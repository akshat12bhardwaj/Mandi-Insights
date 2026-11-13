import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { MapPin } from "lucide-react";
import { Heading } from "./Intelligence";
import { useRegionalWeather } from "../components/RegionalWeather";
import { Weather } from "../components/PlaceWeather";
import { MapView, type MapPoint } from "../components/MapView";
import { params, rupees, number, useIntelligence, type Overview, type Market, type Facility } from "../lib/intelligence";
import type { Environment, MarketInventory } from "../lib/market-intelligence";

const date = (value?: string | null) => value ? value.slice(0, 10) : "Unavailable";
type Choice = { series_id: string; crop: string; label: string; price: number | null };
type Point = Choice & MapPoint;
type Directory = { points: Point[]; unmapped: Choice[]; unmapped_count: number; bounds: [number, number] | null; state_options: { id: string; name: string }[]; selected_state_id: string; batch_id: string };
type Place = {
  market: Market & { state_name?: string };
  warehouses: { rows: (Facility & { distance_km: number; distance_basis: string })[]; radius_km: number; reason?: string };
  connections: { name: string; destination: string; km: number; hours: number; basis: string }[];
  batch_id: string;
};

export function MarketsExplorer() {
  const [url] = useSearchParams();
  const [crop, setCrop] = useState(url.get("crop") || "");
  const [state, setState] = useState(url.get("state") || "");
  const [search, setSearch] = useState("");
  const [basis, setBasis] = useState("reported");
  const [side, setSide] = useState<"above" | "below">("above");
  const [threshold, setThreshold] = useState<number>();
  const [selected, setSelected] = useState({ series_id: url.get("series") || "", crop: url.get("crop") || "" });
  const [group, setGroup] = useState<number[]>([]);
  const [tab, setTab] = useState("Terrain & roads");
  const [cropOffset, setCropOffset] = useState(0);
  const weather = useRegionalWeather();
  const overview = useIntelligence<Overview>("overview");
  const filters = params({ crop, state, search: search.trim(), basis: crop ? basis : "reported" });
  const directory = useIntelligence<Directory>("market-map?" + filters);
  const data = directory.data;
  const region = data?.selected_state_id ?? state;
  const stateOptions = data?.state_options ?? [];
  const place = useIntelligence<Place>("market-place?" + params(selected), !!selected.series_id);
  const d = place.data;
  const env = useIntelligence<Environment>("market-environment?" + params(selected), !!d?.market.coordinate);
  const inventory = useIntelligence<MarketInventory>("market-crops?" + params({ series_id: selected.series_id, limit: 8, offset: cropOffset }), !!selected.series_id && tab === "Reported crops");
  const bounds = data?.bounds;
  const value = bounds ? Math.max(bounds[0], Math.min(bounds[1], threshold ?? bounds[side === "above" ? 0 : 1])) : 0;
  const matches = (p: Choice) => p.price == null || (side === "above" ? p.price >= value : p.price <= value);
  const points = useMemo<MapPoint[]>(() => (data?.points || []).map(p => ({
    ...p, kind: "market", tone: matches(p) ? "ok" : "muted",
  })), [data, side, value]);
  const selectedPoint = data?.points?.find(p => p.series_id === selected.series_id);
  const extra: MapPoint[] = d?.market.coordinate && !selectedPoint ? [{
    id: -1, ...d.market.coordinate, label: d.market.market, tone: "ok", kind: "market",
  }] : [];
  const nearby: MapPoint[] = (d?.warehouses.rows || []).map((w, i) => ({
    id: -2 - i, lat: w.latitude, lng: w.longitude, label: w.name, tone: "ink", kind: "warehouse",
  }));
  const select = (p: Choice) => { setSelected({ series_id: p.series_id, crop: p.crop }); setCropOffset(0); setGroup([]); };
  const clearSelection = () => {
    setSelected({ series_id: "", crop: "" });
    setCropOffset(0);
    setGroup([]);
  };
  const facilityLink = (id: string) => "/warehouses?" + params({ facility: id });
  const tabs = ["Terrain & roads", "Nearby storage", "Reported crops"];
  return <div className="mi-page">
    <Heading title="Know your market." text="Explore mandis, their surroundings and road access." />
    <div className="mi-toolbar">
      <label className="mi-field"><span>Crop</span><select aria-label="Crop" value={crop} onChange={e => { setCrop(e.target.value); setState(""); setThreshold(undefined); clearSelection(); }}>
        <option value="">All crops</option>{overview.data?.catalog.crops.map(c => <option key={c.crop}>{c.crop}</option>)}
      </select></label>
      <label className="mi-field"><span>State</span><select aria-label="State" value={region} onChange={e => { setState(e.target.value); clearSelection(); }}>
        <option value="">All states</option>
        {region && !stateOptions.some(s => s.id === region) && <option value={region}>{state}</option>}
        {stateOptions.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
      </select></label>
      <label className="mi-field"><span>Find a market</span><input type="search" maxLength={100} value={search} onChange={e => { setSearch(e.target.value); clearSelection(); }} /></label>
      {crop && <label className="mi-field"><span>Price basis</span><select aria-label="Price basis" value={basis} onChange={e => { setBasis(e.target.value); setState(""); setThreshold(undefined); clearSelection(); }}>
        <option value="reported">Latest reported price</option><option value="forecast">Current eligible estimate</option>
      </select></label>}
      {crop && bounds && <div className="mi-threshold">
        <div role="group" aria-label="Price direction">
          {(["above", "below"] as const).map(mode => <button key={mode} className={side === mode ? "mi-primary" : "mi-secondary"} aria-pressed={side === mode} onClick={() => { setSide(mode); setThreshold(undefined); }}>{mode === "above" ? "Above" : "Below"}</button>)}
        </div>
        <label className="mi-field"><span>Price threshold · {rupees(value)}/quintal</span><input aria-label="Price threshold" type="range" min={bounds[0]} max={bounds[1]} step={bounds[1] === bounds[0] ? 1 : (bounds[1] - bounds[0]) / 100} value={value} disabled={bounds[0] === bounds[1]} onChange={e => setThreshold(Number(e.target.value))} /></label>
      </div>}
    </div>
    {directory.error && <p role="alert" className="mi-note">Market map could not load. <button className="mi-text-link" onClick={() => void directory.refetch()}>Retry</button></p>}
    <div className="mi-explore-grid mi-map-first">
      <section className="mi-panel mi-market-map">
        <div className="mi-section-heading"><h2>Market map</h2><span aria-live="polite">{data ? number(points.filter(p => p.tone === "ok").length) + (crop ? " matching mapped markets" : " mapped markets") : "Loading markets…"}</span></div>
        <MapView weather={weather} points={[...points, ...extra, ...nearby]} selectedId={selectedPoint?.id ?? (extra.length ? -1 : undefined)} compact fitKey={filters + ":" + points.length} className="mi-discovery-map" ariaLabel="Market map" onGroupSelect={ids => ids[0] <= -2 ? setTab("Nearby storage") : setGroup(ids)} onSelect={id => {
          if (id <= -2) { setTab("Nearby storage"); return; }
          const point = data?.points?.find(p => p.id === id);
          if (point) select(point);
        }} />
        <p className="mi-note">Shop pins mark mandis. Dashed outlines mark approximate locations. Weather icons show regional forecasts.{!crop && " Choose a crop to compare prices."}{crop && " Each pin uses one series for this crop, chosen by latest report date. Varieties and grades can differ."}</p>
        {group.length > 0 && <div className="mi-map-choices"><strong>Markets at this map location</strong>{(data?.points || []).filter(p => group.includes(p.id)).slice(0, 20).map(p => <button key={p.id} onClick={() => select(p)}>{p.label}</button>)}{group.length > 20 && <small>Search by market name to narrow this group.</small>}</div>}
        {!!data?.unmapped_count && <details className="mi-series-details"><summary>{number(data.unmapped_count)} markets without a map reference</summary><div className="mi-map-choices">{data.unmapped.filter(matches).map(p => <button key={p.series_id} onClick={() => select(p)}>{p.label}</button>)}</div><p className="mi-note">Use market search to narrow these results.</p></details>}
      </section>
      <section key={d?.market.series_id} className="mi-panel mi-market-profile mi-panel-enter">
        {place.error ? <p role="alert">Market details are unavailable. <button className="mi-text-link" onClick={() => void place.refetch()}>Retry</button></p> : !d ? <p className="mi-note">{selected.series_id ? "Loading market details…" : "Select a shop pin to inspect a market."}</p> : <>
          <h2>{d.market.market}</h2><p><MapPin size={14} /> {d.market.district}, {d.market.state_name || d.market.state}</p>
          <p className="mi-note">{d.market.coordinate?.precision || "Location reference unavailable"}</p>
          {crop && selectedPoint?.price != null && <p className="mi-note">{rupees(selectedPoint.price)}/quintal · {crop} · {basis === "forecast" ? "Current eligible estimate" : "Latest reported price"}</p>}
          <p className="mi-summary-insight">{d.market.coordinate ? `${d.connections.length} nearby road references checked. ${d.warehouses.rows.length} storage facilities shown within the project search area.` : "Weather, roads and nearby storage require a mapped reference."}</p>
          <Weather env={env.data?.batch_id === d.batch_id ? env.data : undefined} loading={env.isFetching} error={!!env.error} retry={() => void env.refetch()} />
          <div className="mi-market-actions" role="group" aria-label="Market details">
            {tabs.map(t => <button key={t} className={tab === t ? "mi-primary" : "mi-secondary"} aria-pressed={tab === t} onClick={() => setTab(t)}>{t}</button>)}
          </div>
          {tab === "Terrain & roads" && <div className="mi-series-details">
            {!d.connections.length && <p className="mi-note">Nearby road connections unavailable.</p>}
            {d.connections.map(r => <div className="mi-connection" key={r.destination}><div><strong>{r.name}</strong><span>{number(r.km)} km · about {number(r.hours)} hours</span><small>{r.basis}</small></div></div>)}
          </div>}
          {tab === "Nearby storage" && <div className="mi-series-details">
            <p className="mi-note">{d.warehouses.reason || `Facilities within ${d.warehouses.radius_km} km straight-line distance.`}</p>
            {d.warehouses.rows.map(w => <div className="mi-connection" key={w.warehouse_id}><div><Link className="mi-text-link" to={facilityLink(w.warehouse_id)}>{w.name}</Link><span>{w.storage_class} · {number(w.free_t)} t simulated free · {number(w.distance_km)} km</span><small>{w.distance_basis}</small></div></div>)}
          </div>}
          {tab === "Reported crops" && <div className="mi-series-details">
            {inventory.error ? <p className="mi-note">Crop reports are unavailable for this market.</p> : inventory.data?.batch_id === d.batch_id ? <>
              <p className="mi-note">Latest audited report for each crop, variety, grade and source series.</p>
              <div className="mi-inventory">{inventory.data.rows.map(r => <article key={r.series_id}><strong>{r.crop} · {r.variety}</strong><small>{r.grade} · {r.source}</small><span>{rupees(r.last_observed_price)}/q · {date(r.observation_date)}</span></article>)}</div>
              {inventory.data.total_series > 8 && <div className="mi-pagination">
                <button disabled={!cropOffset} onClick={() => setCropOffset(cropOffset - 8)}>Previous reports</button>
                <span>{cropOffset + 1}–{cropOffset + inventory.data.rows.length} of {inventory.data.total_series}</span>
                <button disabled={cropOffset + 8 >= inventory.data.total_series} onClick={() => setCropOffset(cropOffset + 8)}>More reports</button>
              </div>}
            </> : <p role="status">Loading crop reports…</p>}
          </div>}
        </>}
      </section>
    </div>
  </div>;
}
