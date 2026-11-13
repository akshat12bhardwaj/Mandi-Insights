import { useQuery } from "@tanstack/react-query";
import { MapPin, Package, Truck, Warehouse, TrendingUp } from "lucide-react";
import { number, request, rupees, type Strategy, type TradeRoute } from "../lib/intelligence";

export function journeySchedule(strategy: Strategy, route: TradeRoute, date: string) {
  const departure = Date.parse(date + "T08:00:00+05:30");
  const formatter = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
  const schedule = strategy.schedule;
  if (schedule) return {
    buy: formatter.format(Date.parse(schedule.procurement_at)), arrival: formatter.format(Date.parse(schedule.arrival_at)),
    sale: formatter.format(Date.parse(schedule.sale_at)), hours: schedule.travel_hours,
    at: (offset: number) => formatter.format(Date.parse(schedule.procurement_at) + offset * 3600000),
  };
  const hours = route.hours * strategy.trips;
  const at = (offset: number) => formatter.format(departure + offset * 3600000);
  return { buy: at(0), arrival: at(hours), sale: at(hours + strategy.storage_days * 24), hours, at };
}

export function JourneyPlan({ strategy, route, date }: { strategy: Strategy; route: TradeRoute; date: string }) {
  const plan = journeySchedule(strategy, route, date);
  const storageArrival = route.storage_arrival_hours;
  const formatter = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
  const storageStart = strategy.schedule?.storage_start_at ? formatter.format(Date.parse(strategy.schedule.storage_start_at)) : storageArrival == null ? null : plan.at(storageArrival * strategy.trips);
  const storageEnd = strategy.schedule?.storage_end_at ? formatter.format(Date.parse(strategy.schedule.storage_end_at)) : storageArrival == null ? null : plan.at(storageArrival * strategy.trips + strategy.storage_days * 24);
  const steps = [
    { name: "Buy", Icon: MapPin, day: plan.buy, place: strategy.buy.market, detail: number(strategy.quantity_q) + " q · " + rupees(strategy.procurement) },
    { name: "Load", Icon: Package, day: plan.buy, place: strategy.buy.market, detail: strategy.vehicle + " · " + (strategy.schedule ? number(strategy.schedule.loading_hours) + " h loading · " : "") + rupees(strategy.handling) + " handling" },
    { name: "Transport", Icon: Truck, day: plan.buy + " → " + (storageStart || plan.arrival), place: strategy.warehouse ? "Via " + strategy.warehouse.name : strategy.sell.market, detail: number(route.km) + " km · " + number(plan.hours) + " h total driving" },
    ...(strategy.warehouse ? [{ name: "Store", Icon: Warehouse, day: storageStart && storageEnd ? storageStart + " → " + storageEnd : "Before delivery", place: strategy.warehouse.name, detail: strategy.storage_days + " days · " + rupees(strategy.storage) }] : []),
    { name: "Sell", Icon: TrendingUp, day: plan.sale, place: strategy.sell.market, detail: rupees(strategy.sale_price) + "/q estimate" },
  ];
  return <section className="mi-panel mi-plan" aria-label="Journey plan">
    <h2>Journey plan</h2>
    <p>Depart {plan.buy}{strategy.schedule ? " at " + new Intl.DateTimeFormat("en-IN", { hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" }).format(Date.parse(strategy.schedule.depart_at)) : " at 8 am"} IST · {strategy.trips} {strategy.trips === 1 ? "trip" : "trips"}</p>
    <ol>{steps.map(({ Icon, ...step }) => <li key={step.name}>
      <Icon size={19} aria-hidden /><div><small>{step.day}</small><strong>{step.name}</strong><span>{step.place}</span><small>{step.detail}</small></div>
    </li>)}</ol>
    <p>Estimated arrival for sale {plan.sale}. {strategy.warehouse && storageEnd == null && "Warehouse departure depends on the inbound leg."}</p>
  </section>;
}

export function TimingComparison({ strategy, date, arrivalRoute, warehouse, batch, selectedDays, onUse, chart = false }: {
  strategy: Strategy; date: string; arrivalRoute: TradeRoute; warehouse: string | null; batch?: string;
  selectedDays: number; onUse: (strategy: Strategy) => void; chart?: boolean;
}) {
  const inputs = { buy_id: strategy.buy.series_id, sell_id: strategy.sell.series_id, quantity: strategy.quantity_q,
    vehicle: strategy.vehicle, handling: strategy.handling / strategy.quantity_q,
    loss: strategy.handling_loss_pct ?? strategy.loss_pct, warehouse_id: warehouse, batch_id: batch, future_mode: "forecast" };
  const options = useQuery({
    queryKey: ["selling-timing", inputs],
    queryFn: () => request<{ rows: Strategy[]; recommended_days: number; unavailable: { days: number; reason: string }[] }>("storage-options", inputs),
    staleTime: 60000, retry: false, enabled: !strategy.schedule,
  });
  const entries = [0, 7, 14, 30].map(days => ({
    days,
    row: strategy.schedule ? (!days && strategy.route_plans?.find(r => !r.storage_days && r.route.objective === arrivalRoute.objective))
      || strategy.timing_options?.find(r => r.storage_days === days)
      : days ? options.data?.rows?.find(r => r.storage_days === days) : strategy,
  }));
  const arrival = entries[0].row;
  const bestMargin = Math.max(...entries.flatMap(({ row }) => row ? [row.margin] : []));
  const scale = Math.max(1, ...entries.flatMap(({ row }) => row ? [Math.abs(row.margin)] : []));
  return <section className="mi-panel mi-plan" aria-label="When to sell">
    <h2>When to sell</h2>
    <p>Compare direct delivery with holding the crop. Sale dates include travel time.</p>
    {chart && <div className="mi-margin-chart" role="group" aria-label="Estimated margin by sale date">
      {entries.map(({ days, row }) => <div key={days} className={selectedDays === days ? "is-selected" : ""}>
        <span>{row ? journeySchedule(row, row.route, date).sale : "Unavailable"} · {days ? days + " days storage" : "On arrival"}</span>
        {row ? <><div className="mi-margin-axis" aria-hidden><i style={{ width: Math.abs(row.margin) / scale * 50 + "%" }}
          className={row.margin < 0 ? "is-negative" : ""} /></div><strong>{rupees(row.margin)}</strong></> : <span>—</span>}
      </div>)}
    </div>}
    <div className="mi-timing-grid">{entries.map(({ days, row }) => {
      const route = strategy.schedule || days ? row?.route : arrivalRoute;
      const delta = row && route ? route.transport_cost - row.transport : 0;
      const recommended = (strategy.schedule ? strategy.storage_days : options.data?.recommended_days) === days;
      const sale = row && route ? journeySchedule(row, route, date).sale : undefined;
      return <article key={days} className={selectedDays === days ? "is-selected" : ""}>
        <h3>{days ? "Store " + days + " days" : "Sell on arrival"}</h3>
        {recommended && <span className="mi-badge">Recommended timing</span>}
        {chart && row && row.margin === bestMargin && <span className="mi-badge">Highest estimated margin</span>}
        {row ? <>
          <p>Planned sale · {sale}</p>
          <dl><div><dt>{row.sale_quote?.kind === "persistence_assumption" ? "Carried-forward price" : "Price estimate"}</dt><dd>{rupees(row.sale_price)}/q</dd></div>
          <div><dt>Selling revenue</dt><dd>{rupees(row.sale_revenue)}</dd></div>
          <div><dt>Transport</dt><dd>{rupees(row.transport + delta)}</dd></div>
          <div><dt>Storage</dt><dd>{rupees(row.storage)}</dd></div>
          <div><dt>Total cost</dt><dd>{rupees(row.total_cost + delta)}</dd></div>
          <div><dt>Net margin</dt><dd>{rupees(row.margin - delta)}</dd></div></dl>
          {chart && days > 0 && arrival && <small>{rupees(row.margin - arrival.margin)} margin change vs arrival. Costs change by {rupees(row.total_cost - arrival.total_cost)} and revenue by {rupees(row.sale_revenue - arrival.sale_revenue)}.</small>}
          {days > 0 && row.future_forecast && <small>Price forecast for {row.future_forecast.target_date}</small>}
          {selectedDays !== days && <button className="mi-secondary" onClick={() => onUse(row)}>Plan this sale</button>}
          {selectedDays === days && <span className="mi-plan-selected">Selected plan</span>}
        </> : <p>{(options.isPending && !strategy.schedule) || (strategy.schedule && !strategy.timing_options) ? "Checking plan options…" :
          (strategy.timing_unavailable || options.data?.unavailable)?.find(r => r.days === days)?.reason || "Plan unavailable."}</p>}
      </article>;
    })}</div>
    {options.isError && <button className="mi-text-link" onClick={() => void options.refetch()}>Retry storage comparison</button>}
  </section>;
}
