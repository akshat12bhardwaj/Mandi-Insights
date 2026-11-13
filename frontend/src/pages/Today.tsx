import { lazy, Suspense, useState, useEffect } from "react";
import { CloudSun, Leaf, Route, ShoppingBasket, Warehouse } from "lucide-react";
import { PageHeader } from "../components/Layout";
import { Card } from "../components/ui";
import { MapView as DecisionMap } from "../components/MapView";
import { useDaily, type DailyCrop, type DailyMarket, type DailyPrediction, type DailyHistory } from "../lib/daily";
import { useRoute } from "../lib/api";
import { useDecisionOptions, useTrading, useDecisionWeather, type DecisionRequest, type EligibleMarket, type TradingResult } from "../lib/decisions";

const DailyPriceChart = lazy(() => import("../components/DailyPriceChart"));
const money = (n: number | null | undefined) => n == null ? "Not calculated" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const inputClass = "h-9 w-full min-w-0 rounded-lg border border-line bg-white px-2.5 text-[13px] text-ink";
const emptyRequest: DecisionRequest = { objective: "compare_all", preferred_sell_series_id: null, acquisition_rs_per_quintal: null, max_transport_km: null, warehouse_id: null, series_id: "", quantity_quintals: 10, destination: null, region: "state", storage_days: 30,
  storage_rs_per_tonne_month: null, transport: { mode: "freight", load_capacity_quintals: null, vehicle_type: "Goods vehicle", rs_per_vehicle_km: null, toll_rs_per_trip: 0, freight_rs_per_tonne_km: null, fuel_rs_per_litre: null,
    vehicle_km_per_litre: null, fixed_trip_rs: 0, handling_rs_per_quintal: 0, destination_access_km: null, market_access_km: {}, warehouse_access_km: {} } };
const unavailable: Record<string, string> = { insufficient_history: "Not enough recent reports for a useful estimate.",
  stale_unavailable: "History is too old for today's estimate.", batch_expired: "Today's price update is not ready yet." };

function Choice({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (s: string) => void }) {
  return <label className="grid min-w-0 gap-1 text-[12px] font-medium text-muted">{label}
    <select aria-label={label} value={value} onChange={e => onChange(e.target.value)} disabled={!options.length} className={inputClass}>
      {!options.length && <option value="">No options available</option>}{options.map(v => <option key={v} value={v}>{v}</option>)}
    </select></label>;
}
function NumberInput({ label, value, onChange, min = 0, max = 1000000 }: { label: string; value: number | null; onChange: (n: number | null) => void; min?: number; max?: number }) {
  return <label className="grid min-w-0 gap-1 text-xs text-muted">{label}<input aria-label={label} type="number" step="any" min={min} max={max} value={value ?? ""}
    placeholder="Unknown" className={inputClass} onChange={e => onChange(e.target.value === "" ? null : Number(e.target.value))} /></label>;
}

const objectiveLabels={buy_now:"Buy now",sell_now:"Sell now",buy_deliver:"Buy and deliver",buy_store_sell:"Buy, store, then sell",compare_all:"Compare all viable scenarios"};
function PlanCard({data,loading,onTab,destination}:{data?:TradingResult;loading:boolean;onTab:(s:string)=>void;destination?:string}) {
 const p=data?.plan;
 const explore=(tab:string,id:string)=>{onTab(tab);requestAnimationFrame(()=>document.getElementById(id)?.scrollIntoView({behavior:"smooth",block:"start"}));};
 return <Card className="mt-4 border-ok/20 p-5" data-testid="decision-summary"><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-base font-semibold text-ok">Today's supported plan</h2><p className="text-xs text-muted">{data?.target_date ?? "Today"} IST · {data?.quantity_quintals ?? "—"} quintals</p></div><p className="mt-2 text-sm leading-relaxed">{data?.summary ?? (loading?"Comparing available scenarios…":"No complete recommendation yet. Choose a crop and review the available estimates.")}</p><dl className="mt-4 grid gap-3 text-xs sm:grid-cols-3 lg:grid-cols-6">{[["Buy from",p?.buy?.market ?? (p?.kind==="sell_owned"?"Already owned":"Not established")],["Sell / deliver to",p?.sell?.market ?? destination ?? "Not selected"],["Store at","No verified storage plan"],["Transport",p?.route ? `${p.route.objective} · ${p.route.trips ?? "?"} trip(s)` : "Not calculated"],["Modeled cost",money(p?.total_cost)],[p?.kind==="sell_owned"&&p.estimated_margin==null?"Net sale proceeds":"Estimated margin",money(p?.kind==="sell_owned"&&p.estimated_margin==null?p.net_sale_proceeds:p?.estimated_margin)]].map(([label,value])=><div key={label}><dt className="text-muted">{label}</dt><dd className="mt-1 font-semibold text-ink">{value}</dd></div>)}</dl><div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-xs font-medium text-ok"><button onClick={()=>explore("decision","buying-alternatives")}>Explore buying markets</button><button onClick={()=>explore("decision","selling-alternatives")}>Explore selling markets</button><button onClick={()=>explore("transport","decision-workspace")}>Compare routes</button><button onClick={()=>explore("store","decision-workspace")}>Compare storage</button></div><p className="mt-3 text-[11px] text-muted">Estimated scenarios, not verified trading opportunities. Small price differences may be indistinguishable relative to historical error.</p></Card>;
}

export default function Today() {
  const [categoryValue, setCategory] = useState("Vegetables"), [cropValue, setCrop] = useState("Onion");
  const [stateValue, setState] = useState(""), [districtValue, setDistrict] = useState(""), [marketValue, setMarket] = useState(""), [seriesValue, setSeries] = useState("");
  const [activeTab, setTab] = useState("decision"), [objective, setObjective] = useState("shortest");
  const [draft, setDraft] = useState<DecisionRequest>(emptyRequest), [applied, setApplied] = useState<DecisionRequest>(emptyRequest);
  const [showDetails, setShowDetails] = useState(false);
  useEffect(() => { if (draft.quantity_quintals <= 0 || !Number.isInteger(draft.storage_days) || draft.storage_days < 1) return; const timer = setTimeout(() => setApplied(draft), 450); return () => clearTimeout(timer); }, [draft]);
  const catalog = useDaily<{ crops: DailyCrop[]; dataset_version: string }>("crops");
  const categories = [...new Set((catalog.data?.crops ?? []).map(c => c.category))].sort();
  const category = categories.includes(categoryValue) ? categoryValue : categories[0] ?? "";
  const crops = (catalog.data?.crops ?? []).filter(c => c.category === category).map(c => c.crop);
  const crop = crops.includes(cropValue) ? cropValue : crops[0] ?? "";
  const options = useDecisionOptions(crop), preferred = options.data?.eligible_markets[0];
  const locations = useDaily<{ state: string; district: string }[]>("locations", { crop }, !!crop);
  const states = [...new Set((locations.data ?? []).map(r => r.state))].sort();
  const state = states.includes(stateValue) ? stateValue : states.includes(preferred?.state ?? "") ? preferred!.state : states[0] ?? "";
  const districts = [...new Set((locations.data ?? []).filter(r => r.state === state).map(r => r.district))].sort();
  const district = districts.includes(districtValue) ? districtValue : state === preferred?.state && districts.includes(preferred.district) ? preferred.district : districts[0] ?? "";
  const marketsQuery = useDaily<DailyMarket[]>("markets", { crop, state, district }, !!district);
  const markets = [...new Set((marketsQuery.data ?? []).map(m => m.market))].sort();
  const market = markets.includes(marketValue) ? marketValue : district === preferred?.district && markets.includes(preferred.market) ? preferred.market : markets[0] ?? "";
  const series = (marketsQuery.data ?? []).filter(m => m.market === market);
  const selected = series.find(m => m.series_id === seriesValue) ?? series.find(m => m.series_id === preferred?.series_id) ?? series[0];
  const sid = selected?.series_id ?? "";
  useEffect(()=>{setDraft(d=>({...d,preferred_sell_series_id:null,warehouse_id:null}));setApplied(d=>({...d,preferred_sell_series_id:null,warehouse_id:null}));},[sid]);
  const forecast = useDaily<DailyPrediction>("today", { series_id: sid }, !!sid);
  const history = useDaily<DailyHistory>("history", { series_id: sid, limit: "90", release:forecast.data?.dataset_version ?? "" }, !!sid && !!forecast.data);
  const comparison = useTrading({ ...applied, series_id: sid }), weather = useDecisionWeather(sid);
  const decision = comparison.data, p = forecast.data, origin = decision?.plan?.route_origin ?? decision?.analysis_origin ?? undefined;
  const routeDestination = decision?.plan?.route_destination ?? decision?.analysis_destination ?? applied.destination;
  const visibleRoutes = decision?.plan?.routes.length ? decision.plan.routes : decision?.analysis_routes ?? [];
  const shownObjective = visibleRoutes.some(r=>r.objective===objective) ? objective : decision?.plan?.route?.objective ?? visibleRoutes[0]?.objective ?? "shortest";
  const storageFocus = decision?.storage.find(w => w.warehouse_id === applied.warehouse_id) ?? decision?.storage[0];
  const facilityWeather = useDecisionWeather(activeTab === "store" ? sid : "", activeTab === "store" ? storageFocus?.warehouse_id : undefined);
  const route = useRoute(activeTab === "transport" && origin !== routeDestination ? origin : undefined, activeTab === "transport" ? routeDestination ?? undefined : undefined, shownObjective);
  const destinations = options.data?.destinations ?? [];
  const routePoints = destinations.filter(n => n.node_id === origin || n.node_id === routeDestination).map((n, id) => ({ id, lat: n.latitude, lng: n.longitude, label: `${n.name} district reference`, tone: "ok" as const }));
  const error = catalog.error ?? locations.error ?? marketsQuery.error ?? forecast.error;
  const reset = () => { setDraft(d => ({...d,preferred_sell_series_id:null,warehouse_id:null})); setState(""); setDistrict(""); setMarket(""); setSeries(""); };
  const switchMarket = (m: EligibleMarket) => { setState(m.state); setDistrict(m.district); setMarket(m.market); setSeries(m.series_id); };
  const setTransport = (key: keyof DecisionRequest["transport"], value: unknown) => setDraft(d => ({ ...d, transport: { ...d.transport, [key]: value } }));
  const setAccess = (key: "market_access_km" | "warehouse_access_km", id: string, value: number | null) => {
    const next = { ...draft.transport[key] }; if (value === null) delete next[id]; else next[id] = value; setTransport(key, next);
  };
  const wx = weather.data?.days?.find(d => d.date === p?.target_date);
  const reliability = p?.predicted_modal_price == null ? "Estimate unavailable" : p.status === "stale_prediction" ? "Older reports · use caution" : "Recent reports · indicative estimate";

  return <>
    <PageHeader icon={<Leaf size={20} />} title="Today's mandi price" subtitle="Compare buying options, plan delivery and explore storage." />
    <div className="mb-3 flex overflow-x-auto rounded-xl border border-line bg-white px-2" role="tablist" aria-label="Decision support">
      {[{id:"decision",label:"Today's Decision",Icon:ShoppingBasket},{id:"transport",label:"Route Analysis",Icon:Route},{id:"store",label:"Storage Analysis",Icon:Warehouse}].map(({id,label,Icon}) => <button key={id} role="tab" id={`tab-${id}`} aria-selected={activeTab===id} aria-controls={`panel-${id}`} tabIndex={activeTab===id?0:-1} onClick={()=>setTab(id)} onKeyDown={e=>{const ids=["decision","transport","store"];if(e.key==="ArrowRight"||e.key==="ArrowLeft"){e.preventDefault();const next=ids[(ids.indexOf(id)+(e.key==="ArrowRight"?1:2))%3];setTab(next);document.getElementById(`tab-${next}`)?.focus();}}} className={`flex shrink-0 items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium ${activeTab===id?"border-ok text-ok":"border-transparent text-muted"}`}><Icon size={15}/>{label}</button>)}
    </div>
    {catalog.isLoading && <p role="status">Loading supported crops…</p>}
    {error && <Card className="mb-4 p-4"><p role="alert">{error.message}</p></Card>}
    {catalog.data && <Card className="p-4"><div className="grid grid-cols-2 gap-x-4 gap-y-3 md:grid-cols-3">
      <Choice label="Crop category" value={category} options={categories} onChange={v => { setCategory(v); setCrop(""); reset(); }} />
      <Choice label="Crop" value={crop} options={crops} onChange={v => { setCrop(v); reset(); }} />
      <Choice label="State" value={state} options={states} onChange={v => { setState(v); setDistrict(""); setMarket(""); setSeries(""); }} />
    </div><details className="mt-3 text-xs"><summary className="cursor-pointer text-ok">Reference market: {market || "Choose a market"} - {district} - {selected?.variety ?? "Choose variety"}</summary><div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-3">
      <Choice label="District" value={district} options={districts} onChange={v => { setDistrict(v); setMarket(""); setSeries(""); }} />
      <Choice label="Market" value={market} options={markets} onChange={v => { setMarket(v); setSeries(""); }} />
      <label className="grid min-w-0 gap-1 text-xs font-medium text-muted">Variety<select aria-label="Variety" className={inputClass} value={sid} disabled={!series.length} onChange={e => setSeries(e.target.value)}>
        {!series.length && <option value="">No series available</option>}{series.map(s => <option key={s.series_id} value={s.series_id}>{s.variety} · {s.grade}{s.source === "datagov" ? "" : " · Archive"}</option>)}
      </select></label>
    </div></details><p className="mt-3 text-[11px] text-muted">{options.data ? `${options.data.eligible_count} eligible market-variety estimates for this crop today.` : "Checking today's availability…"} Historical markets remain accessible; unavailable estimates are clearly marked.</p></Card>}

    <Card className="mt-3 p-4"><form onSubmit={e => { e.preventDefault(); setApplied(draft); }} className="mb-4">
          <div className="grid items-end gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <NumberInput label="Quantity (quintals)" min={0.01} value={draft.quantity_quintals} onChange={v => setDraft(d => ({ ...d, quantity_quintals: v ?? 0 }))} />
            <label className="grid gap-1 text-xs text-muted">Destination reference<select aria-label="Destination reference" className={inputClass} value={draft.destination ?? ""} onChange={e => setDraft(d => ({ ...d, destination: e.target.value || null }))}>
              <option value="">Choose a destination</option>{destinations.map(n => <option key={n.node_id} value={n.node_id}>{n.name}, {n.state}</option>)}</select></label>
            <Choice label="Procurement region" value={draft.region === "state" ? "Selected state" : "All available states"} options={["Selected state", "All available states"]} onChange={v => setDraft(d => ({ ...d, region: v === "Selected state" ? "state" : "all" }))} />
            <Choice label="Decision objective" value={objectiveLabels[draft.objective ?? "compare_all"]} options={Object.values(objectiveLabels)} onChange={v=>setDraft(d=>({...d,objective:Object.entries(objectiveLabels).find(([,label])=>label===v)![0] as DecisionRequest["objective"]}))} />
            <NumberInput label="Maximum transport (km)" max={10000} value={draft.max_transport_km ?? null} onChange={v=>setDraft(d=>({...d,max_transport_km:v}))} />
            <label className="grid gap-1 text-xs text-muted">Preferred selling market<select aria-label="Preferred selling market" className={inputClass} value={draft.preferred_sell_series_id ?? ""} onChange={e=>setDraft(d=>({...d,preferred_sell_series_id:e.target.value||null}))}><option value="">Compare compatible markets</option>{options.data?.eligible_markets.filter(m=>m.variety===p?.variety && m.grade===p?.grade).map(m=><option key={m.series_id} value={m.series_id}>{m.market}, {m.district}</option>)}</select></label>
            <button type="submit" className="h-9 rounded-lg bg-ok px-4 text-xs font-medium text-white">Compare options</button>
          </div>
          {JSON.stringify(draft) !== JSON.stringify(applied) && <p className="mt-2 text-[11px] text-muted">Changes are not applied yet. The scenario updates across all three tabs after a short pause.</p>}
          <details className="mt-3 text-xs"><summary className="cursor-pointer font-medium text-ok">Transport and storage assumptions</summary>
            <p className="mt-2 text-muted">Your scenario inputs, not verified freight quotes. Trip count uses your stated load capacity. Blank values remain unknown. Enter each market's access distance below, then compare again.</p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Choice label="Transport calculation" value={draft.transport.mode === "freight" ? "Freight rate" : draft.transport.mode === "per_km" ? "Vehicle distance rate" : "Fuel expense"} options={["Freight rate", "Fuel expense", "Vehicle distance rate"]} onChange={v => setTransport("mode", v === "Freight rate" ? "freight" : v === "Vehicle distance rate" ? "per_km" : "fuel")} />
              <NumberInput label="Vehicle load capacity (quintals)" min={0.01} value={draft.transport.load_capacity_quintals ?? null} onChange={v=>setTransport("load_capacity_quintals",v)} />
              <label className="grid gap-1 text-xs text-muted">Vehicle type<input aria-label="Vehicle type" className={inputClass} value={draft.transport.vehicle_type ?? ""} onChange={e=>setTransport("vehicle_type",e.target.value)} /></label>
              <NumberInput label="Toll assumption (₹/trip)" value={draft.transport.toll_rs_per_trip ?? 0} onChange={v=>setTransport("toll_rs_per_trip",v ?? 0)} />
              <NumberInput label="Owned produce acquisition (₹/quintal)" value={draft.acquisition_rs_per_quintal ?? null} onChange={v=>setDraft(d=>({...d,acquisition_rs_per_quintal:v}))} />
              {draft.transport.mode === "freight" ? <NumberInput label="Freight (₹/tonne-km)" max={10000} value={draft.transport.freight_rs_per_tonne_km} onChange={v => setTransport("freight_rs_per_tonne_km", v)} /> : draft.transport.mode === "per_km" ? <NumberInput label="Vehicle rate (₹/km)" value={draft.transport.rs_per_vehicle_km ?? null} onChange={v=>setTransport("rs_per_vehicle_km",v)} /> : <>
                <NumberInput label="Fuel price (₹/litre)" max={1000} value={draft.transport.fuel_rs_per_litre} onChange={v => setTransport("fuel_rs_per_litre", v)} />
                <NumberInput label="Vehicle efficiency (km/litre)" min={0.01} max={100} value={draft.transport.vehicle_km_per_litre} onChange={v => setTransport("vehicle_km_per_litre", v)} /></>}
              <NumberInput label="Destination access road (km)" max={1000} value={draft.transport.destination_access_km} onChange={v => setTransport("destination_access_km", v)} />
              <NumberInput label="Fixed trip charges (₹)" value={draft.transport.fixed_trip_rs} onChange={v => setTransport("fixed_trip_rs", v ?? 0)} />
              <NumberInput label="Handling (₹/quintal)" value={draft.transport.handling_rs_per_quintal} onChange={v => setTransport("handling_rs_per_quintal", v ?? 0)} />
              <NumberInput label="Storage duration (days)" min={1} max={365} value={draft.storage_days} onChange={v => setDraft(d => ({ ...d, storage_days: v ?? 0 }))} />
              <NumberInput label="Storage assumption (₹/tonne-month)" value={draft.storage_rs_per_tonne_month} onChange={v => setDraft(d => ({ ...d, storage_rs_per_tonne_month: v }))} />
            </div></details>
        </form></Card>
    <PlanCard data={decision} loading={comparison.isFetching} onTab={setTab} destination={destinations.find(n=>n.node_id===applied.destination)?.name} />
    {activeTab === "decision" && <div className="mt-4 grid items-start gap-4 lg:grid-cols-[1.5fr_1fr]">
      <Card className="min-w-0 p-5" data-testid="daily-forecast">
        {p ? <><div className="flex flex-wrap items-start justify-between gap-2"><div><p className="text-xs text-muted">{p.crop} · {p.market}, {p.district}, {p.state}</p>
          <h2 className="mt-2 text-sm font-medium">Today's estimate <span className="font-normal text-muted">· {p.target_date} IST</span></h2>
          <p className="mt-1 text-[38px] font-semibold leading-tight tracking-tight">{p.predicted_modal_price === null ? "Unavailable" : money(p.predicted_modal_price)} <span className="text-sm font-normal text-muted">/ quintal</span></p>
        </div><span className="rounded-full bg-ok-soft px-2.5 py-1 text-[11px] text-ok">{reliability}</span></div>
          {p.predicted_modal_price === null && <p role="status" className="mt-2 text-sm text-muted">{unavailable[p.status] ?? "A current estimate is not available."} See eligible alternatives below.</p>}
          {p.previous_forecast?.prediction != null && <p className="mt-2 text-xs text-muted">Previous run for {p.previous_forecast.target_date}: {money(p.previous_forecast.prediction)}/quintal. This is not a current-day estimate.</p>}
          <p className="mt-2 text-[11px] text-muted">An estimated price, not a reported trade or guaranteed quote. Issued {new Date(p.forecast_issue_timestamp).toLocaleString("en-IN",{timeZone:"Asia/Kolkata",dateStyle:"medium",timeStyle:"short"})} IST.</p>
          {p.observed_today !== null && <p className="mt-2 text-xs text-ok">Reported today: {money(p.observed_today)}/quintal. Kept separate from this prediction.</p>}
          <div className="mt-3 flex items-start gap-2 border-t border-line pt-3 text-xs text-muted"><CloudSun size={16} className="shrink-0 text-ok" />
            <p>{weather.data?.available && wx ? `${wx.tmax_c ?? "—"}°C maximum · ${wx.rain_mm ?? "—"} mm forecast rain · humidity ${wx.humidity_mean_pct ?? "—"}% · wind ${wx.wind_max_kmh ?? "—"} km/h${weather.data.stale ? " · older update" : ""}. District reference only.` : weather.isLoading ? "Checking local weather…" : "Weather context unavailable at this location."} <span>Weather is not used in this price estimate.</span> {weather.data?.heavy_rain_days?.some(d=>d.date===p.target_date) && <span>Heavy rain is forecast near the reference; check loading and local road conditions. This is not a closure alert.</span>} <a href="https://open-meteo.com/" className="underline">Open-Meteo</a></p>
          </div>
          <div className="mt-4 border-t border-line pt-3"><div className="mb-2 flex justify-between text-xs"><h3 className="font-medium">Price trend</h3><span className="text-muted">Observed — green · Prediction — amber</span></div>
            {history.isLoading && <p className="text-xs text-muted">Loading price history…</p>}{history.error && <p role="alert" className="text-xs">History is unavailable.</p>}
            {history.data && <Suspense fallback={<p className="text-xs text-muted">Loading chart…</p>}><DailyPriceChart history={history.data} prediction={p} compact /></Suspense>}
          </div>
        </> : <p role="status" className="text-sm text-muted">{sid ? "Loading today's estimate…" : "Select an available crop and market."}</p>}
      </Card>

      <Card className="p-5"><h2 className="text-base font-semibold">Scenario breakdown</h2><p className="mt-1 text-xs text-muted">{decision?.quantity_quintals ?? applied.quantity_quintals} quintals · selected plan</p><dl className="mt-4 space-y-3 text-sm">{[["Buying / acquisition",decision?.plan?.procurement_cost],["Transport",decision?.plan?.transport_cost],["Handling",decision?.plan?.handling_cost],["Total modeled cost",decision?.plan?.total_cost],["Estimated sale revenue",decision?.plan?.sale_revenue],["Net sale proceeds",decision?.plan?.net_sale_proceeds]].map(([label,value])=><div className="flex justify-between gap-3" key={String(label)}><dt className="text-muted">{label}</dt><dd className="font-medium">{money(value as number|null|undefined)}</dd></div>)}</dl><p className="mt-4 text-xs leading-relaxed text-muted">Margins exclude unmodeled taxes, spoilage, financing and return travel. Owned produce has no assumed purchase cost.</p></Card>
    </div>}

    <Card className="mt-4 min-w-0 overflow-hidden" id="decision-workspace">
      <div className="flex justify-end border-b border-line px-4 py-2"><button className="text-xs text-ok" aria-expanded={showDetails} onClick={() => setShowDetails(!showDetails)}>Details</button></div>
      <div role="tabpanel" id={`panel-${activeTab}`} aria-labelledby={`tab-${activeTab}`} className="p-4 sm:p-5">

        {comparison.error && !showDetails && <p role="alert" className="mb-3 text-sm">{comparison.error.message}</p>}
        {options.error && <p className="text-xs text-muted">Availability information is temporarily unavailable.</p>}
        {comparison.isFetching && !showDetails && <p role="status" className="mb-3 text-xs text-muted">Updating comparison…</p>}

        {activeTab === "decision" && <><h2 id="buying-alternatives" className="text-sm font-semibold">Where to buy</h2><p className="mt-1 text-xs text-muted">{decision ? `${decision.quantity_quintals} quintals · ${decision.comparison_scope}` : "Only eligible current forecasts are compared."}</p>
          <div className="mt-3 divide-y divide-line">{decision?.markets.map(m => <div key={m.series_id} className="grid gap-3 py-3 sm:grid-cols-[1.5fr_1fr_1fr]">
            <div><button className="text-left text-sm font-medium text-ok underline-offset-2 hover:underline" onClick={() => switchMarket(m)}>{m.market}</button><p className="mt-1 text-xs text-muted">{m.district}, {m.state} · {m.variety} · {m.grade}</p><p className="mt-1 text-[11px] text-muted">{m.age_days} days since report · {m.comparable ? "Matching variety and grade" : "Different variety or grade"}</p></div>
            <div><p className="text-xs text-muted">Predicted / quintal</p><p className="mt-1 text-lg font-semibold">{money(m.predicted_price)}</p><p className="mt-1 text-[11px] text-muted">Landed total: {money(m.landed_cost)}</p>{decision.cheapest_scenario_series_id === m.series_id && <span className="text-[11px] text-ok">Lowest costed scenario</span>}</div>
            <div><NumberInput label={`Access road km: ${m.market}`} max={1000} value={draft.transport.market_access_km[m.series_id] ?? null} onChange={v => setAccess("market_access_km", m.series_id, v)} /><p className="mt-1 text-[11px] leading-snug text-muted">{m.limitation}</p></div>
          </div>)}</div>{decision && !decision.markets.length && <p className="mt-3 text-sm text-muted">No eligible alternatives for this crop today. Choose another crop; historical prices remain available above.</p>}</>}

        {activeTab === "decision" && <div className="mt-5 border-t border-line pt-4"><h2 id="selling-alternatives" className="text-sm font-semibold">Selling / delivery alternatives</h2><p className="mt-1 text-xs text-muted">Compatible current-day estimates; future storage sale prices are not available.</p><div className="mt-3 grid gap-3 md:grid-cols-3">{decision?.selling_markets?.slice(0,5).map(m=><div className="rounded-xl border border-line p-3" key={m.series_id}><button className="text-left text-sm font-medium text-ok" onClick={()=>setDraft(d=>({...d,preferred_sell_series_id:m.series_id,objective:"sell_now"}))}>{m.market}</button><p className="mt-1 text-xs text-muted">{m.district}, {m.state} · {m.variety}</p><p className="mt-2 font-semibold">{money(m.predicted_price)}/quintal</p><NumberInput label={`Selling access km: ${m.market}`} max={1000} value={draft.transport.market_access_km[m.series_id] ?? null} onChange={v=>setAccess("market_access_km",m.series_id,v)} /></div>)}</div>{decision && !decision.selling_markets?.length && <p className="mt-2 text-xs text-muted">No compatible selling estimate for this destination. Select another destination or clear the preference.</p>}<h3 className="mt-5 text-sm font-semibold">Scenario cost comparison</h3><div className="mt-2 divide-y divide-line">{decision?.scenarios?.slice(0,6).map(s=><div key={s.scenario_id} className="grid gap-1 py-3 text-xs sm:grid-cols-3"><p>{s.kind.replaceAll("_"," ")} · {s.buy?.market ?? "Owned produce"} → {s.sell?.market ?? "Chosen destination"}</p><p>Cost {money(s.total_cost)} · {s.kind==="sell_owned"?"Net proceeds":"Margin"} {money(s.kind==="sell_owned"?s.net_sale_proceeds:s.estimated_margin)}</p><p className="text-muted">{s.complete?s.ranking.replaceAll("_"," "):s.missing[0]}</p></div>)}</div></div>}

        {activeTab === "store" && <><h2 className="text-sm font-semibold">Where to store</h2><p className="mt-1 text-xs leading-relaxed text-muted">Candidates near the selected market's district reference. Suitability, capacity, availability and operator tariffs are unknown. {crop === "Potato" ? "Confirm suitable potato cold-storage conditions." : crop === "Onion" ? "Confirm suitable ventilated onion storage." : category === "Fruits" || category === "Vegetables" ? "Confirm crop-specific temperature, humidity and shelf life; an ordinary warehouse may not be suitable." : "Confirm moisture, pest control and compatibility for this crop."}</p>
          <div className="mt-3 grid gap-3 md:grid-cols-2">{decision?.storage.map(w => <div key={w.warehouse_id} className="rounded-xl border border-line p-3"><p className="text-sm font-medium">{w.name}</p><p className="mt-1 text-xs text-muted">{w.facility_type.replaceAll("_", " ")} · {w.reference_road_distance_km.toFixed(1)} km from district road reference</p>
            <p className="mt-1 text-[11px] text-muted">{w.operator?.toUpperCase() ?? "Operator unknown"} - nominal capacity (tonnes): {w.nominal_capacity_t ?? "unknown"}</p><details className="mt-1 text-[11px] text-muted"><summary className="cursor-pointer">Source and verification</summary><p>{w.source ?? "OSM reported"} - source snapshot {w.source_update_date ?? "unknown"}; coordinates are not a verified entrance.</p></details><p className="mt-2 text-xs">Storage: {money(w.storage_cost)}{w.storage_cost !== null ? " · your rate assumption" : " · tariff unknown"}</p><p className="mt-1 text-xs">Transport: {money(w.transport_cost)} · Scenario total: {money(w.scenario_total)}</p>
            <button className="mt-2 text-xs text-ok underline" onClick={()=>setDraft(d=>({...d,warehouse_id:w.warehouse_id}))}>{applied.warehouse_id===w.warehouse_id?"Selected candidate":"Inspect this candidate"}</button><p className="mt-1 text-[11px] text-muted">Suitability and available capacity: unknown · reported location, unverified</p><div className="mt-2"><NumberInput label={`Facility access road km: ${w.name}`} max={1000} value={draft.transport.warehouse_access_km[w.warehouse_id] ?? null} onChange={v => setAccess("warehouse_access_km", w.warehouse_id, v)} /></div></div>)}</div>
          {storageFocus && <><p className="mt-3 text-xs text-muted">{storageFocus.reason ?? "Closest mapped candidate by reference road distance; not confirmed suitable or available."} Destination → facility reference distance: {storageFocus.destination_to_facility_reference_km ?? "unknown"} km; the reverse road leg is not verified.</p><div className="mt-3 h-60 overflow-hidden rounded-xl border border-line"><DecisionMap className="h-full w-full" compact ariaLabel="Map of OSM-reported storage candidate locations, unverified" points={[{id:0,lat:storageFocus.latitude,lng:storageFocus.longitude,label:storageFocus.name+" · OSM-reported location, unverified",tone:"muted"}]} fitKey={storageFocus.warehouse_id} /></div><p className="mt-2 text-xs text-muted">{facilityWeather.data?.available ? "Outdoor weather at the OSM-reported facility location is available; it does not describe indoor storage conditions." : "Facility weather context unavailable."}</p></>}
          {decision && !decision.storage.length && <p className="mt-3 text-sm text-muted">No mapped storage candidates near a verified reference for this market.</p>}<p className="mt-3 text-[11px] text-muted">Storage scenarios are market-to-facility alternatives. The facility-to-destination road leg is unverified. Direct delivery has fewer unknown inputs when fully costed; no validated future price justifies holding for profit. Spoilage, shrinkage and financing are unmodeled. No storage-for-profit recommendation is supported.</p></>}

        {activeTab === "transport" && <><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-sm font-semibold">Transportation</h2><p className="mt-1 text-xs text-muted">Distinct saved OSM paths between the plan’s district references; no live traffic or truck-access verification.</p></div><Choice label="Route shown" value={shownObjective === "shortest" ? "Shortest distance" : "Fastest estimate"} options={[...new Set(visibleRoutes.map(r=>r.objective === "shortest" ? "Shortest distance" : "Fastest estimate"))]} onChange={v => setObjective(v === "Shortest distance" ? "shortest" : "fastest")} /></div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">{visibleRoutes.map(r => <div key={r.objective} className="rounded-xl border border-line p-3"><p className="text-sm font-medium">{r.objective === "shortest" ? "Shortest distance" : "Fastest estimate"}</p><p className="mt-1 text-xs text-muted">{r.road_distance_km.toFixed(1)} km reference road · {r.travel_time_h.toFixed(1)} h assumed free flow</p><p className="mt-1 text-xs text-muted">{r.trips ?? "Unknown"} trip(s) · {r.objectives?.length===2?"Same path serves both objectives":"Distinct saved path"}</p><p className="mt-2 text-sm">Transport: {money(r.transport_cost)} · {money(r.cost_per_quintal)}/quintal</p>{r.fuel_expense !== null && <p className="mt-1 text-xs text-muted">Fuel component: {money(r.fuel_expense)}</p>}</div>)}</div>
          {!routeDestination && <p className="mt-3 text-sm text-muted">Choose a destination and compare options to view routes.</p>}
          {origin && routeDestination && origin !== routeDestination && <div className="mt-4 h-72 overflow-hidden rounded-xl border border-line"><DecisionMap className="h-full w-full" points={routePoints} line={route.data?.geometry} compact fitKey={`${origin}-${routeDestination}-${shownObjective}-${route.data?.geometry?.length ?? 0}`} /></div>}
          {route.data && !route.data.geometry && <p className="mt-2 text-xs text-muted">The road shape is unavailable; map markers are district references.</p>}
          {decision?.plan?.route?.reason && <p className="mt-3 text-sm"><strong>Why this route? </strong>{decision.plan.route.reason}</p>}{decision?.location_evidence && <details className="mt-3 text-xs text-muted"><summary className="cursor-pointer text-ok">Location precision and road access</summary>{Object.entries(decision.location_evidence).map(([role,e])=>e && <p className="mt-2" key={role}>{role}: {e.meaning}. Reference {e.reference_coordinate.latitude.toFixed(5)}, {e.reference_coordinate.longitude.toFixed(5)}. Road snap {e.road_access_coordinate ? `${e.road_access_coordinate.latitude.toFixed(5)}, ${e.road_access_coordinate.longitude.toFixed(5)}; ${e.road_access_coordinate.straight_line_gap_km.toFixed(3)} km straight-line gap, not a road access distance` : "unavailable"}.</p>)}</details>}{route.error && <p role="alert" className="mt-2 text-xs">The route map is unavailable.</p>}<p className="mt-3 text-[11px] text-muted">Reference road distances exclude access legs in cost assumptions. Route objectives may use the same road path. Trip count uses your load capacity; legal truck restrictions, closures, waiting and return travel remain unknown.</p></>}

        {showDetails && <div className="space-y-3 text-xs leading-relaxed text-muted"><h2 className="text-sm font-semibold text-ink">Methodology and data details</h2>
          {p && <><p>Last observed: {money(p.last_observed_price)}/quintal on {p.last_observation_date ?? "unknown"} · {p.data_freshness.age_days ?? "unknown"} days old.</p><p>Variety: {p.variety} · Grade: {p.grade} · Source: {p.source}. Model: last observed price (persistence).</p>
            <p>At least 180 observations over a year and sufficient recent reporting are required. More than seven days since the last observation withholds the estimate. Today's observation is excluded.</p>
            {p.historical_error && <p>2017–2018 development simulation MAE: {money(p.historical_error.mae)}/quintal across {p.historical_error.markets} sampled series. Assumed reporting delay; not calibrated live confidence.</p>}
            <p className="break-all">Issued {p.forecast_issue_timestamp} · {p.model_version} · {p.dataset_version}</p></>}
          <p>Weather remains context: no valid new daily weather comparison is possible without historical availability vintages. The existing closed weekly weather study did not justify deployment. Current weather can be retrieved after price issuance and never changes that forecast.</p>
          {decision?.limitations.map(l => <p key={l}>{l}</p>)}<p>Source: DMI / AGMARKNET, data.gov.in. Road and facility data © OpenStreetMap contributors (ODbL). <a href="https://open-meteo.com/" className="underline">Weather by Open-Meteo.com (CC BY 4.0)</a>.</p>
        </div>}
      </div>
    </Card>
  </>;
}
