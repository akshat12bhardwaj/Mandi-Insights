import { useEffect } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { JourneyPlan, TimingComparison } from "../components/JourneyPlan";
import { params, rupees, number, useIntelligence, type StrategyResult } from "../lib/intelligence";
import { StrategyDetail } from "./Intelligence";

export default function AlternativePlan() {
  const { planId = "" } = useParams();
  const [url, setUrl] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => { window.scrollTo(0, 0); }, [planId]);
  const [buy, sell, extra] = planId.split(":");
  const quantity = Number(url.get("quantity") || 100);
  const vehicle = url.get("vehicle") || "Medium truck";
  const mode = url.get("mode") || "auto";
  const valid = !!buy && !!sell && extra === undefined;
  const query = useIntelligence<StrategyResult>("strategies?" + params({
    plan: true, selected_id: planId, crop: url.get("crop") || "", buy_id: buy, sell_id: sell,
    quantity, vehicle, mode, warehouse_id: url.get("warehouse") || "",
  }), valid && quantity > 0 && quantity <= 100000);
  const data = query.data;
  const base = data?.rows.find(row => row.id === planId);
  const days = url.get("days");
  const objective = url.get("route");
  const selectedTiming = days == null ? undefined : base?.timing_options?.find(row => row.storage_days === Number(days));
  const active = selectedTiming || base;
  const plan = (objective && active?.storage_days === 0 ? base?.route_plans?.find(row => row.route.objective === objective && !row.storage_days) : undefined) || active;
  const change = (values: Record<string, string>) => {
    setUrl(previous => {
      const next = new URLSearchParams(previous);
      for (const [key, value] of Object.entries(values)) {
        if (value) next.set(key, value);
        else next.delete(key);
      }
      return next;
    }, { replace: true, state: location.state, preventScrollReset: true });
  };
  const back = typeof location.state?.returnTo === "string" ? location.state.returnTo : "/?" + params({ quantity, vehicle, mode });
  return <div className="mi-page">
    <Link className="mi-text-link" to={back} state={{ restoreScroll: location.state?.scroll }} onClick={event => {
      if (location.state?.fromComparison && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
        event.preventDefault();
        navigate(-1);
      }
    }}>← Back to Strategies</Link>
    <header className="mi-heading">
      <div><h1>{base ? base.crop + " trading plan" : "Trading plan"}</h1>
        {plan && <p>{plan.buy.market}, {plan.buy.state} → {plan.sell.market}, {plan.sell.state}</p>}</div>
      {plan && <div className="mi-decision-value"><small>Estimated net margin</small><strong>{rupees(plan.margin)}</strong></div>}
    </header>
    {valid && <div className="mi-toolbar">
      <label className="mi-field"><span>Quantity (quintals)</span><input type="number" min="1" max="100000" step="any" value={url.get("quantity") ?? "100"}
        onChange={e => change({ quantity: e.target.value || "0", days: "", route: "" })} /></label>
      <label className="mi-field"><span>Truck</span><select value={vehicle} onChange={e => change({ vehicle: e.target.value, days: "", route: "" })}>
        {["Light truck", "Medium truck", "Heavy truck"].map(name => <option key={name}>{name}</option>)}</select></label>
    </div>}
    {!valid || query.isError || (data && !base) || !(quantity > 0 && quantity <= 100000) ? <section className="mi-panel">
      <h2>Plan unavailable</h2><p>{query.error?.message || (quantity <= 0 || quantity > 100000 ? "Enter a quantity between 1 and 100,000 quintals." : "This trade has no feasible plan in the current publication.")}</p>
      {query.isError && <button className="mi-secondary" onClick={() => void query.refetch()}>Retry</button>}
    </section> : query.isPending ? <p role="status" className="mi-message">Calculating trading plan…</p> : null}
    {base && plan && data && <div className="mi-planning">
      {days !== null && !selectedTiming && <p className="mi-note" role="status">That selling option is unavailable in the current publication. Showing the recommended timing for this trade.</p>}
      <p className="mi-note">{number(plan.quantity_q)} quintals · {plan.vehicle} · {plan.trading_mode || mode} · {plan.warehouse ? plan.storage_days + " days at " + plan.warehouse.name : "Direct delivery"}</p>
      <p className="mi-note">Buying price {rupees(plan.buy.predicted_price)}/q · Current-day estimate</p>
      <JourneyPlan strategy={plan} route={plan.route} date={data.date} />
      <TimingComparison strategy={base} date={data.date} arrivalRoute={base.route_plans?.find(row => row.route.objective === objective)?.route ||
        base.timing_options?.find(row => !row.storage_days)?.route || base.route}
        selectedDays={plan.storage_days} warehouse={null} batch={data.batch_id} chart
        onUse={row => change({ days: String(row.storage_days), route: "" })} />
      <StrategyDetail key={planId + ":" + quantity + ":" + vehicle + ":" + plan.storage_days}
        strategy={plan} route={plan.route} onRoute={value => change({ route: value })} onRoadReady={() => void query.refetch()} />
    </div>}
  </div>;
}
