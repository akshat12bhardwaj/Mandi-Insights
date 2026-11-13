import { ArrowRight, MapPin, Truck, Warehouse, TrendingUp } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import {
  request,
  rupees,
  number,
  type Strategy,
  type ScenarioInput,
} from "../lib/intelligence";

export function DecisionStory({
  strategy: s,
  onSelect,
  selectionLabel,
  hideComparisons = false,
  operational = false,
  planDate,
}: {
  strategy: Strategy;
  onSelect: (id: string) => void;
  selectionLabel?: string;
  hideComparisons?: boolean;
  operational?: boolean;
  planDate?: string;
}) {
  const decision = s.decision;
  if (!decision) return null;
  const alternatives = decision.alternatives;
  const maxMargin = Math.max(
    1,
    Math.abs(s.margin),
    ...alternatives.map((a) => Math.abs(a.margin)),
  );
  return (
    <section
      className="mi-decision-story"
      aria-label="Recommended trading journey"
    >
      <div className="mi-decision-title">
        <div>
          <span className="mi-badge">
            {selectionLabel ||
              (decision.scope === "custom_scenario"
                ? "Your adjusted scenario"
                : decision.practical_tie
                  ? "Practical choice among similar options"
                  : decision.scope === "selected_alternative"
                    ? "Selected alternative"
                    : "Recommended comparison")}{" "}
            · {s.crop}
          </span>
          <h2>{decision.headline}</h2>
          <p>{operational ? `Buy and deliver ${number(s.quantity_q)} quintals · ${number(s.route.km)} km · about ${number(s.route.hours)} h per trip · ${s.storage_days ? s.storage_days + " days in storage" : "Sell on arrival"}` : s.data_quality?.label}</p>
          {operational && s.schedule && planDate && <p>{s.trading_mode === "intrastate" ? "Intrastate" : "Interstate"} · Buy {s.schedule.procurement_at.slice(0, 10)} · Sell {s.schedule.sale_at.slice(0, 10)}</p>}
        </div>
        <div className="mi-decision-value">
          <small>Estimated net margin</small>
          <strong>{rupees(s.margin)}</strong>
          <span>For {number(s.quantity_q)} quintals</span>
        </div>
      </div>
      {!operational && <ol className="mi-journey">
        <li>
          <MapPin size={18} />
          <div>
            <small>Buy · {s.buy.state}</small>
            <strong>{s.buy.market}</strong>
            <span>{rupees(s.buy.predicted_price)}/quintal</span>
          </div>
        </li>
        <li>
          <Truck size={18} />
          <div>
            <small>Transport</small>
            <strong>
              {number(s.route.km)} km · {s.trips} trip{s.trips > 1 ? "s" : ""}
            </strong>
            <span>
              {rupees(s.transport)} · {number((s.truck_utilization || 0) * 100)}
              % load use
            </span>
          </div>
        </li>
        {s.warehouse && (
          <li>
            <Warehouse size={18} />
            <div>
              <small>Store</small>
              <strong>{s.warehouse.name}</strong>
              <span>
                {s.storage_days} days · {rupees(s.storage)}
              </span>
            </div>
          </li>
        )}
        <li>
          <TrendingUp size={18} />
          <div>
            <small>Sell · {s.sell.state}</small>
            <strong>{s.sell.market}</strong>
            <span>{rupees(s.sale_price)}/quintal</span>
          </div>
        </li>
      </ol>}
      {hideComparisons && (
        <h3 className="mi-why-heading">Why this option wins</h3>
      )}
      <div className="mi-reasons">
        {(operational ? [
          { title: "Price advantage", value: rupees(s.sale_price - (s.buy.predicted_price ?? s.sale_price)) + "/q", text: "Estimated sale price less purchase price, before expenses." },
          { title: "Delivery plan", value: number(s.route.hours * s.trips) + " h driving", text: rupees(s.transport) + " transport for " + s.trips + (s.trips === 1 ? " trip." : " trips.") },
          ...(decision.cards.find(c => c.title === "Next alternative") ? [decision.cards.find(c => c.title === "Next alternative")!] : []),
        ] : decision.cards).map((c) => (
          <article key={c.title}>
            <h3>{c.title}</h3>
            <strong>{c.value}</strong>
            <p>{c.text}</p>
          </article>
        ))}
      </div>
      {!operational && !!decision.context_notes?.length && <div className="mi-note">{decision.context_notes.map(note => <p key={note}>{note}</p>)}</div>}
      {!hideComparisons && !!alternatives.length && (
        <div className="mi-evidence-compare">
          <div className="mi-evidence-heading">
            <h3>Why choose this over the alternatives?</h3>
            <span>Estimated margin after expenses</span>
          </div>
          <div className="mi-value-row">
            <span>Selected trade</span>
            <div className="mi-bar-track">
              <i
                style={{ width: (Math.abs(s.margin) / maxMargin) * 100 + "%" }}
              />
            </div>
            <strong>{rupees(s.margin)}</strong>
          </div>
          {alternatives.map((a) => (
            <button
              key={a.id}
              className="mi-value-row"
              onClick={() => onSelect(a.id)}
              aria-label={`Explore alternative ${a.buy_market} to ${a.sell_market}`}
            >
              <span>
                {a.buy_market} to {a.sell_market}
              </span>
              <div className="mi-bar-track">
                <i
                  className={a.margin < 0 ? "is-negative" : "is-alternative"}
                  style={{
                    width: (Math.abs(a.margin) / maxMargin) * 100 + "%",
                  }}
                />
              </div>
              <strong>{rupees(a.margin)}</strong>
            </button>
          ))}
          <p className="mi-tradeoff">
            <ArrowRight size={15} />
            {decision.trade_off}
          </p>
        </div>
      )}

    </section>
  );
}

interface StorageResult {
  rows: Strategy[];
  recommended_days: number;
  recommendation: string;
  reason: string;
  scope: string;
  unavailable: { days: number; reason: string }[];
}
export function SellingDates({
  form,
  onUse,
}: {
  form: ScenarioInput;
  onUse: (s: Strategy) => void;
}) {
  const query = useMutation({
    mutationFn: (inputs: ScenarioInput) =>
      request<StorageResult>("storage-options", {
        ...inputs,
        future_mode: "forecast",
      }),
  });
  const inputsCurrent =
    JSON.stringify(query.variables) === JSON.stringify(form);
  return (
    <details className="mi-selling-dates">
      <summary>Sell now or store?</summary>
      <p>
        Compare today's sale with 7, 14 and 30 day price forecasts, storage
        charges, travel and modeled losses.
      </p>
      <button
        type="button"
        className="mi-primary"
        onClick={() => query.mutate({ ...form })}
        disabled={query.isPending}
      >
        {query.isPending ? "Comparing selling dates…" : "Compare selling dates"}
      </button>
      {query.error && inputsCurrent && (
        <p role="alert">{query.error.message}</p>
      )}
      {query.data && !inputsCurrent && (
        <p className="mi-note">
          Inputs changed. Compare selling dates again to update these options.
        </p>
      )}
      {query.data && inputsCurrent && (
        <>
          <div className="mi-storage-options">
            {query.data.rows.map((s) => (
              <article
                className={
                  s.storage_days === query.data!.recommended_days
                    ? "is-recommended"
                    : ""
                }
                key={s.storage_days}
              >
                <span className="mi-badge">
                  {s.storage_days === 0
                    ? "Sell immediately"
                    : `Store ${s.storage_days} days`}
                  {s.storage_days === query.data!.recommended_days
                    ? " · Recommended"
                    : ""}
                </span>
                <strong>{rupees(s.margin)}</strong>
                <small>Estimated net margin</small>
                <p>
                  {s.storage_days
                    ? `${s.warehouse?.storage_class} storage · ${rupees(s.storage)} charges`
                    : "No storage expense"}
                </p>
                <p>
                  {s.future_forecast
                    ? `Estimated ${s.future_forecast.target_date} · ${rupees(s.future_forecast.price)}/quintal`
                    : "Current-day estimate"}
                </p>
                <button
                  type="button"
                  className="mi-secondary"
                  onClick={() => onUse(s)}
                >
                  Use this option
                </button>
              </article>
            ))}
          </div>
          {query.data.unavailable.map((r, i) => (
            <p className="mi-note" key={i}>
              {r.days} days: {r.reason}
            </p>
          ))}
        </>
      )}
    </details>
  );
}
