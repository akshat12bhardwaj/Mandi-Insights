import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { Heading, StrategyDetail } from "./Intelligence";
import { JourneyPlan, TimingComparison, journeySchedule } from "../components/JourneyPlan";
import { DecisionStory } from "../components/DecisionStory";
import {
  useIntelligence,
  params,
  rupees,
  number,
  type Strategy,
  type StrategyResult,
  type Overview,
} from "../lib/intelligence";

type Mode = "intrastate" | "interstate";
export function Strategies() {
  const [url, setUrl] = useSearchParams();
  const overview = useIntelligence<Overview>("overview");
  const [crop, setCrop] = useState(url.get("crop") || "");
  const [state, setState] = useState(url.get("state") || "");
  const [quantity, setQuantity] = useState(() => {
    const carried = Number(url.get("quantity"));
    return carried > 0 && carried <= 100000 ? carried : 100;
  });
  const [vehicle, setVehicle] = useState(url.get("vehicle") || "Medium truck");
  const [mode, setMode] = useState<Mode | "auto">(url.get("mode") === "intrastate" ? "intrastate" : url.get("mode") === "interstate" ? "interstate" : "auto");
  const [restoreScroll] = useState(() => Number(sessionStorage.getItem("mi-comparison-scroll") || 0));
  const [selected, setSelected] = useState("");
  const [objective, setObjective] = useState("");
  const [detailRevision, setDetailRevision] = useState(0);
  const [adjusted, setAdjusted] = useState<{
    scenario: Strategy;
    batch?: string;
    mode: Mode;
  } | null>(null);
  const query = useIntelligence<StrategyResult>(
    "strategies?" +
      params({
        crop,
        state,
        quantity,
        vehicle,
        mode,
        plan: true,
        warehouse_id: url.get("warehouse") || "",
        selected_id: selected,
        buy_id: url.get("buy") || "",
        sell_id: url.get("sell") || "",
      }),
    quantity > 0 && quantity <= 100000,
  );
  useEffect(() => {
    if (!query.data || !restoreScroll) return;
    sessionStorage.removeItem("mi-comparison-scroll");
    const frame = requestAnimationFrame(() => window.scrollTo(0, restoreScroll));
    return () => cancelAnimationFrame(frame);
  }, [restoreScroll, !!query.data]);
  const data = query.data;
  const activeMode: Mode =
    data?.active_mode ||
    (mode === "auto" ? data?.rows[0]?.trading_mode || "interstate" : mode);
  const group = data?.groups?.[activeMode];
  const best = group?.best || null;
  const rows = group?.rows || data?.rows || [];
  const active =
    (adjusted?.batch === data?.batch_id && adjusted?.mode === activeMode
      ? adjusted.scenario
      : null) ||
    rows.find((r) => r.id === selected) ||
    best;
  const inspected = rows.find(r => r.id === selected) || best;
  const inspecting = !!selected && query.isPending;
  const route = active?.routes.find(r => r.objective === objective) || active?.route;
  const planDate = data?.date || overview.data?.date;
  const filters = params({ ...Object.fromEntries(url), crop, state, quantity, vehicle, mode });
  useEffect(() => {
    if (filters !== url.toString()) setUrl(filters, { replace: true, preventScrollReset: true });
  }, [filters, url, setUrl]);
  const planLink = (strategy: Strategy) => "/strategies/plan/" + encodeURIComponent(strategy.id) + "?" +
    params({ crop: strategy.crop, quantity, vehicle, mode: activeMode, warehouse: url.get("warehouse") || "" });
  const rememberComparison = () => {
    sessionStorage.setItem("mi-comparison-scroll", String(window.scrollY));
  };
  const comparisonState = { fromComparison: true, returnTo: "/?" + filters };
  const alternatives =
    data?.competitors || rows.filter((r) => r.id !== best?.id).slice(0, 3);
  useEffect(() => {
    setAdjusted(null);
    setObjective("");
  }, [
    crop,
    state,
    quantity,
    vehicle,
    mode,
    selected,
    data?.batch_id,
  ]);
  useEffect(() => {
    if (data && selected && !rows.some((r) => r.id === selected))
      setSelected("");
  }, [data]);
  const pick = (id: string) => {
    setSelected(id);
    setAdjusted(null);
    setObjective("");
    setDetailRevision((value) => value + 1);
  };
  const changeCrop = (value: string) => {
    setCrop(value);
    setSelected("");
    setAdjusted(null);
    setObjective("");
    setUrl(value ? { crop: value } : {});
  };
  const changeMode = (value: Mode) => {
    setMode(value);
    setSelected("");
    setAdjusted(null);
    setObjective("");
  };
  const clearMarkets = () => setUrl(crop ? { crop } : {});
  const vehicles = Object.keys(
    overview.data?.config.vehicles || { "Medium truck": {} },
  );
  const modeCrops = data?.filters?.crops || [];
  const modeStates = data?.filters?.states || [];
  const selectedRegion = data?.effective_filters?.state || state;
  const unavailableRegion = !!(data && state && !modeStates.some(s => s.id === selectedRegion));
  const maxMargin = Math.max(
    1,
    Math.abs(best?.margin || 0),
    ...alternatives.map((r) => Math.abs(r.margin)),
  );
  return (
    <div className="mi-page mi-single-mode">
      <Heading
        title="A better move for your harvest."
        text="Choose a trading mode, then compare the whole journey."
      />
      <div className="mi-toolbar mi-trading-toolbar">
        <label>
          Crop
          <select
            aria-label="Crop"
            value={crop}
            onChange={(e) => changeCrop(e.target.value)}
          >
            <option value="">All eligible crops</option>
            {crop && !modeCrops.includes(crop) && (
              <option value={crop}>{crop} — unavailable in this mode</option>
            )}
            {modeCrops.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label>
          Purchase region
          <select
            aria-label="Purchase region"
            value={selectedRegion}
            onChange={(e) => {
              setState(e.target.value);
              setSelected("");
            }}
          >
            <option value="">Across India</option>
            {selectedRegion && !modeStates.some((s) => s.id === selectedRegion) && (
              <option value={selectedRegion}>
                {selectedRegion} — unavailable for these filters
              </option>
            )}
            {modeStates.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Quantity (quintals)
          <input
            aria-label="Quantity (quintals)"
            type="number"
            min="1"
            max="100000"
            step="any"
            value={quantity}
            onChange={(e) => setQuantity(Number(e.target.value))}
          />
        </label>
        <label>
          Truck
          <select
            aria-label="Truck"
            value={vehicle}
            onChange={(e) => setVehicle(e.target.value)}
          >
            {vehicles.map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </label>

      </div>
      <div className="mi-mode-switch-row">
        <div className="mi-segmented" role="group" aria-label="Trading mode">
          {(["intrastate", "interstate"] as const).map((category) => (
            <button
              type="button"
              aria-pressed={activeMode === category}
              onClick={() => changeMode(category)}
              key={category}
            >
              <strong>
                {category === "intrastate" ? "Intrastate" : "Interstate"}
              </strong>

            </button>
          ))}
        </div>
        <p>
          {activeMode === "intrastate"
            ? "Buy and sell within the same state."
            : "Buy in one state and sell in another."}

        </p>
      </div>
      {(url.get("buy") || url.get("sell") || url.get("warehouse")) && (
        <div className="mi-context">
          Market or storage carried into this comparison.{" "}
          <button onClick={clearMarkets}>Clear carried selection</button>
        </div>
      )}
      {data?.notices?.map((n) => (
        <p className="mi-note" role="status" key={n}>
          {n}
        </p>
      ))}
      {(query.error || overview.error) && (
        <div className="mi-message" role="alert">
          {(query.error || overview.error)?.message}
          <button onClick={() => void query.refetch()}>Try again</button>
        </div>
      )}
      {query.isPending && (
        <p role="status" className="mi-message">
          {inspecting ? "Loading the selected plan…" : "Finding supported opportunities…"}
        </p>
      )}
      {data && !best && !query.isPending && (
        <section
          className="mi-empty-mode"
          aria-label="Unavailable trading mode"
        >
          <h2>
            No supported {activeMode} trade for {crop || "these filters"}
          </h2>
          <p>
            {data.empty_explanation || group?.empty_reason || data.empty_reason}
          </p>
          <div>
            <button
              className="mi-primary"
              onClick={() => {
                setState("");
                changeCrop("");
              }}
            >
              Show all eligible crops
            </button>
            {state && (
              <button className="mi-secondary" onClick={() => setState("")}>
                Widen purchase region
              </button>
            )}
            {data.fallback_crops
              ?.filter((c) => c !== crop)
              .slice(0, 2)
              .map((c) => (
                <button
                  className="mi-secondary"
                  key={c}
                  onClick={() => {
                    setState("");
                    changeCrop(c);
                  }}
                >
                  Try {c}
                </button>
              ))}
            <Link to={"/markets?" + params({ crop })}>
              Inspect market forecasts
            </Link>
          </div>
          {!unavailableRegion && <small>
            Additional source history and accepted location references can
            expand availability. Varieties, grades and source identities remain
            separate.
          </small>}
        </section>
      )}
      {best && (
        <>
          <DecisionStory
            strategy={best}
            onSelect={pick}
            selectionLabel="Top recommendation"
            hideComparisons
            operational
            planDate={planDate}
          />
          {active && route && inspected && planDate && <div className="mi-planning" key={inspected.id + ":" + activeMode}>
            <JourneyPlan strategy={active} route={route} date={planDate} />
            <TimingComparison strategy={inspected} selectedDays={active.storage_days} date={planDate}
              arrivalRoute={inspected.route_plans?.find(r => r.route.objective === objective)?.route ||
                inspected.timing_options?.find(r => !r.storage_days)?.route || inspected.route}
              warehouse={url.get("warehouse")} batch={data?.batch_id}
              onUse={scenario => { setObjective(""); setAdjusted({ scenario, batch: data?.batch_id, mode: activeMode }); }} />
          </div>}
          <section
            className="mi-inline-competitors"
            aria-label="Strongest competitors"
          >
            <header>
              <div>
                <h2>Strongest competitors</h2>
                <p>
                  Compare estimated margins for the same {number(quantity)} quintals and truck.
                </p>
              </div>

            </header>
            <div className="mi-competitor-reference">
              <span>System recommendation · {best.crop}</span>
              <strong>{rupees(best.margin)} margin</strong>

            </div>
            {alternatives.length ? (
              alternatives.map((s, i) => (
                <article
                  key={s.id}
                  className={active?.id === s.id ? "is-selected" : ""}
                >
                  <div className="mi-competitor-main">
                    <strong>
                      {s.crop} · {s.buy.market} <ArrowRight size={13} />{" "}
                      {s.sell.market}
                    </strong>
                    <small>
                      {s.buy.variety} · {s.buy.grade} · {s.buy.state} to{" "}
                      {s.sell.state}
                    </small>
                    <div className="mi-bar-track">
                      <i
                        className={
                          s.margin < 0 ? "is-negative" : "is-alternative"
                        }
                        style={{
                          width: (Math.abs(s.margin) / maxMargin) * 100 + "%",
                        }}
                      />
                    </div>
                    <small>
                      {number(s.route.km)} km · {rupees(s.transport)} freight ·{" "}
                      {planDate && "Sale " + journeySchedule(s, s.route, planDate).sale + " · "}{s.storage_days ? s.storage_days + " days in storage" : "Direct delivery"}
                    </small>
                  </div>
                  <div className="mi-competitor-values">
                    <strong>{rupees(s.margin)} margin</strong>

                    <small>{rupees(s.margin - best.margin)} margin difference{s.schedule && " · " + number(s.schedule.elapsed_hours / 24) + " days total"}</small>
                    <Link
                      className="mi-secondary"
                      aria-label={`Inspect competitor ${i + 1}`}
                      to={planLink(s)}
                      state={comparisonState}
                      onClick={rememberComparison}
                    >
                      Inspect alternative
                    </Link>
                  </div>
                </article>
              ))
            ) : (
              <p className="mi-note">
                No other compatible pair is available in this mode.
              </p>
            )}
            {!adjusted && data?.selected_comparison && (
              <p className="mi-competitor-insight">
                {active?.id !== best.id
                  ? "Inspected trade versus the system recommendation: "
                  : "Nearest competitor: "}
                {data.selected_comparison.insight}
              </p>
            )}
          </section>
        </>
      )}
      {active && best && (
        <>
          <div className="mi-inspection-heading">
            <div>
              <span>
                {adjusted
                  ? "Selected selling date"
                  : active.id === best.id
                    ? "Recommended route and economics"
                    : "Inspecting selected alternative"}
              </span>
              <h2>
                {active.crop} · {active.buy.market} <ArrowRight size={16} />{" "}
                {active.sell.market}
              </h2>
              <p>
                {number(active.quantity_q)} quintals · {active.buy.variety} ·{" "}
                {active.buy.grade} · {rupees(active.margin)} estimated net
                margin
              </p>
            </div>
            {(adjusted || active.id !== best.id) && (
              <button className="mi-secondary" onClick={() => pick(best.id)}>
                Return to recommendation
              </button>
            )}
            <Link
              to={
                "/markets?" +
                params({
                  crop: active.crop,
                  series: active.buy.series_id,
                  state: active.buy.state,
                  district: active.buy.district,
                })
              }
            >
              Buying market
            </Link>
            <Link to={"/markets?" + params({
              crop: active.crop, series: active.sell.series_id, state: active.sell.state, district: active.sell.district,
            })}>Selling market</Link>
            <Link to={"/warehouses?" + params({
              crop: active.crop, facility: active.warehouse?.warehouse_id || url.get("warehouse") || undefined,
              series: active.buy.series_id, sell: active.sell.series_id, quantity: active.quantity_q,
            })}>
              Storage options
            </Link>
          </div>
          <StrategyDetail
            key={
              active.id +
              quantity +
              vehicle +
              data?.batch_id +
              activeMode +
              url.get("warehouse") +
              detailRevision
            }
            strategy={active}
            route={route || active.route}
            onRoadReady={() => {
              void query.refetch().then(result => {
                if (!adjusted || !inspected) return;
                const updated = result.data?.rows.find(row => row.id === inspected.id)?.timing_options?.find(row =>
                  row.storage_days === active.storage_days && row.warehouse?.warehouse_id === active.warehouse?.warehouse_id);
                if (updated) setAdjusted(current => current === adjusted ? { ...current, scenario: updated } : current);
              });
            }}
            onRoute={value => {
              const plan = active.route_plans?.find(row => row.route.objective === value) ||
                inspected?.route_plans?.find(row => row.route.objective === value);
              if (plan) setAdjusted({ scenario: plan, batch: data?.batch_id, mode: activeMode });
              setObjective(value);
            }}
          />
        </>
      )}
    </div>
  );
}
