import { ArrowDownRight, ArrowRight, ArrowUpRight, Info, Lightbulb, Minus, TriangleAlert } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { PriceHistory, SERIES } from "../components/charts";
import { PageHeader, SectionTitle, useCrop } from "../components/Layout";
import { Card, Chip, Empty, ErrorState, Loading, Segmented, Select } from "../components/ui";
import { CROPS, useMeta, useOverview, useWeekly, useWeeklyMany, type Crop, type Week } from "../lib/api";
import { cn, compact, int, longDate, rs, yr } from "../lib/format";
import { buildInsights, compareStates, inWindow, observed, PERIODS, stats, weeklyGrid, type Insight, type MarketRow, type Period } from "../lib/prices";

export const cropOptions = CROPS.map((c) => ({ value: c, label: c }));

const go = (hash: string) => document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: "smooth", block: "start" });
const signed = (v: number, f: (n: number) => string) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${f(Math.abs(v))}`;
const pct1 = (v: number) => `${v.toFixed(1)}%`;

/** Market Overview: what prices are doing, where else they were higher, and what to check next. */
export default function Overview() {
  const { crop, setCrop } = useCrop();
  const meta = useMeta();
  const [stateSel, setStateSel] = useState<string>();
  const [periodSel, setPeriod] = useState<Period>("3m");
  const states = meta.data?.states_by_crop[crop] ?? [];
  const state = stateSel && states.includes(stateSel) ? stateSel : states[0];
  const weekly = useWeekly(crop, state);
  const all = useWeeklyMany(crop, states);

  const obs = useMemo(() => observed(weekly.data ?? []), [weekly.data]);
  const ref = obs[obs.length - 1]?.date;
  const periods = PERIODS.map((p) => ({ ...p, disabled: !ref || inWindow(obs, ref, p.days).length < 2 }));
  const period = periods.find((p) => p.value === periodSel && !p.disabled) ?? periods.find((p) => !p.disabled) ?? periods[1];
  const win = ref ? inWindow(obs, ref, period.days) : [];
  const s = stats(win);

  const loading = meta.isLoading || weekly.isLoading;
  const allDone = all.every((q) => !q.isLoading);
  const rows: MarketRow[] = useMemo(() => {
    if (!ref || !allDone) return [];
    const byState: Record<string, Week[]> = {};
    states.forEach((st, i) => { if (all[i]?.data) byState[st] = all[i].data!; });
    return compareStates(byState, ref, period.days);
  }, [ref, allDone, crop, period.days, states.join("|")]);
  const dataEnd = rows.reduce<string | undefined>((m, r) => (r.latest && (!m || r.latest.date > m) ? r.latest.date : m), undefined);
  const insights = s ? buildInsights({ crop, state: state ?? "", periodLabel: period.label, s, rows, dataEnd }) : [];
  const select = (st: string) => { setStateSel(st); go("#price-history"); };

  return (
    <>
      <div id="filters" className="scroll-mt-20">
        <PageHeader title="Market Overview"
          subtitle={<>{crop} · {state ?? "…"}{ref && <> · latest report: week of {longDate(ref)}</>}</>}
          controls={<>
            <Segmented label="Crop" value={crop} onChange={(c: Crop) => { setCrop(c); setStateSel(undefined); }} options={cropOptions} />
            <Select label="State" className="w-full sm:w-48" value={state ?? ""} onChange={setStateSel} options={states.map((x) => ({ value: x, label: x }))} />
            <div className="no-scrollbar max-w-full overflow-x-auto">
              <Segmented label="Time period" value={period.value} onChange={setPeriod} options={periods.map((p) => ({ value: p.value, label: p.label, disabled: p.disabled }))} />
            </div>
          </>}
        />
      </div>

      {(meta.error || weekly.error) && <ErrorState error={meta.error ?? weekly.error} className="mb-4" />}
      {ref && (
        <p className="mb-4 flex items-start gap-2 rounded-xl border border-warn/20 bg-warn-soft px-3.5 py-2.5 text-[13px] text-ink">
          <Info size={16} className="mt-0.5 shrink-0 text-warn" aria-hidden />
          <span>These are historical mandi reports up to {longDate(dataEnd ?? ref)}. Check today's rates with your mandi before you sell.</span>
        </p>
      )}

      <section aria-label="Price summary" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {loading ? <Card className="col-span-full"><Loading label="Loading prices" /></Card> : !s ? (
          <Card className="col-span-full"><Empty title="No price reports for this selection">Try another state or a longer time period.</Empty></Card>
        ) : <>
          <Metric testId="kpi-latest" label="Latest typical price" value={rs(s.latest.price)} unit="per quintal" sub={`Week of ${longDate(s.latest.date)}`} />
          <Metric testId="kpi-change" label={`Change over ${period.label}`} unit={s.change === null ? undefined : "per quintal"}
            value={s.change === null ? "Not enough data" : signed(s.change, rs)} tone={s.changePct === null ? undefined : s.changePct > 0 ? "up" : s.changePct < 0 ? "down" : undefined}
            sub={s.changePct === null ? "Needs at least two weekly reports" : `${signed(s.changePct, pct1)} since ${longDate(s.first.date)}`} />
          <Metric label={`Highest in ${period.label}`} value={rs(s.high.price)} unit="per quintal" sub={`Week of ${longDate(s.high.date)}`} />
          <Metric label={`Lowest in ${period.label}`} value={rs(s.low.price)} unit="per quintal" sub={`Week of ${longDate(s.low.date)}`} />
        </>}
      </section>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Card className="p-5 xl:col-start-2 xl:row-start-1" data-testid="insights">
          <SectionTitle title="What can I do?" hint="Observations from the reported prices, with a next step for each." />
          {loading ? <Loading /> : !s ? <Empty title="Not enough information">There are no reported prices to base observations on.</Empty> : (
            <ul className="mt-4 space-y-3">{insights.map((i) => <InsightItem key={i.id} i={i} />)}</ul>
          )}
          <p className="mt-4 text-[12px] leading-relaxed text-muted">Past price movements do not show what prices will do next. A higher quoted price is not the same as a higher net return.</p>
        </Card>

        <Card id="price-history" className="scroll-mt-20 p-5 xl:col-start-1 xl:row-start-1">
          <SectionTitle title="Price history" hint={<>Typical {crop.toLowerCase()} price in {state} mandis, ₹ per quintal, weekly · last {period.label}</>} />
          <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[12px] text-muted" aria-label="Legend">
            <li className="flex items-center gap-1.5"><svg width="16" height="4" aria-hidden><line x1="0" y1="2" x2="16" y2="2" stroke={SERIES.accent} strokeWidth="2.5" /></svg>Reported weekly price</li>
            {s && <li className="flex items-center gap-1.5"><svg width="16" height="4" aria-hidden><line x1="0" y1="2" x2="16" y2="2" stroke={SERIES.reference} strokeWidth="2" strokeDasharray="4 3" /></svg>Average for the period, {rs(s.average)} (calculated)</li>}
          </ul>
          <div className="mt-3 h-[280px] sm:h-[340px] xl:h-[400px]" role="img" aria-label={s ? `Weekly ${crop} prices in ${state} from ${longDate(s.first.date)} to ${longDate(s.latest.date)}, between ${rs(s.low.price)} and ${rs(s.high.price)} per quintal` : "No price data"}>
            {loading ? <Loading /> : !s ? <Empty title="No reports in this period" /> : <PriceHistory data={weeklyGrid(win, ref!)} average={s.average} />}
          </div>
          {s && <Gaps grid={weeklyGrid(win, ref!)} />}
          <SeasonSummary crop={crop} state={state} />
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Comparison rows={rows} state={state} loading={!allDone || loading} periodLabel={period.label} refDate={ref} onSelect={select} />
        <RecentChanges rows={rows} loading={!allDone || loading} periodLabel={period.label} refDate={ref} />
      </div>
      <p className="mt-4 text-[12px] text-muted">
        Typical price = the middle (median) of the modal prices reported by a state's mandis in a week. Source: daily mandi reports from open government data.
      </p>
    </>
  );
}

function Metric({ label, value, unit, sub, tone, testId }: { label: string; value: string; unit?: string; sub: string; tone?: "up" | "down"; testId?: string }) {
  const Icon = tone === "up" ? ArrowUpRight : ArrowDownRight;
  return (
    <Card className="min-w-0 p-4" data-testid={testId}>
      <div className="text-[12.5px] font-medium text-muted">{label}</div>
      <div className={cn("mt-1.5 flex flex-wrap items-baseline gap-x-1.5 tabular-nums", tone === "up" ? "text-ok" : tone === "down" ? "text-bad" : "text-ink")}>
        {tone && <Icon size={18} className="self-center" aria-hidden />}
        <span className="text-[20px] leading-tight font-semibold tracking-tight sm:text-[22px]">{value}</span>
        {unit && <span className="text-[12px] font-normal text-muted">{unit}</span>}
      </div>
      <div className="mt-1 text-[12px] text-muted">{sub}</div>
    </Card>
  );
}

const TONE: Record<Insight["tone"], { icon: ReactNode; cls: string }> = {
  up: { icon: <ArrowUpRight size={16} />, cls: "bg-ok-soft text-ok" },
  down: { icon: <ArrowDownRight size={16} />, cls: "bg-bad-soft text-bad" },
  neutral: { icon: <Lightbulb size={16} />, cls: "bg-subtle text-ink/70" },
  warn: { icon: <TriangleAlert size={16} />, cls: "bg-warn-soft text-warn" },
};

function InsightItem({ i }: { i: Insight }) {
  const cls = "mt-2 inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-white px-3 text-[12.5px] font-medium text-ok transition hover:bg-ok-soft";
  return (
    <li className="flex gap-3 rounded-xl border border-line p-3.5">
      <span className={cn("grid size-8 shrink-0 place-items-center rounded-lg", TONE[i.tone].cls)} aria-hidden>{TONE[i.tone].icon}</span>
      <div className="min-w-0">
        <h3 className="text-[14px] font-semibold text-ink">{i.title}</h3>
        <p className="mt-0.5 text-[13px] leading-relaxed text-muted">{i.evidence}</p>
        {i.action.to.startsWith("#")
          ? <button type="button" className={cls} onClick={() => go(i.action.to)}>{i.action.label}<ArrowRight size={14} aria-hidden /></button>
          : <Link to={i.action.to} className={cls}>{i.action.label}<ArrowRight size={14} aria-hidden /></Link>}
      </div>
    </li>
  );
}

function Gaps({ grid }: { grid: { price: number | null }[] }) {
  const missing = grid.filter((g) => g.price === null).length;
  if (!missing) return null;
  return <p className="mt-2 text-[12px] text-muted">{missing} of {grid.length} weeks had no reports; they are left as gaps, not filled in.</p>;
}

/** The state's agricultural-year figures from /api/overview: supply context for the price chart. */
function SeasonSummary({ crop, state }: { crop: Crop; state?: string }) {
  const ov = useOverview(crop, state);
  const k = ov.data?.kpis;
  if (ov.error) return <ErrorState error={ov.error} className="mt-4" />;
  if (!k) return null;
  const items = [
    { id: "kpi-arrivals", label: `Arrivals, ${yr(k.year)} season`, value: `${compact(k.arrivals_tonnes)} t`, change: k.arrivals_change_pct },
    { id: "kpi-price", label: `Typical price, ${yr(k.year)} season`, value: rs(k.typical_price_rs_per_quintal), change: k.price_change_pct },
    { id: "kpi-markets", label: "Mandis reporting per week", value: int(k.typical_markets_per_week), change: null },
  ];
  return (
    <dl className="mt-4 grid gap-3 border-t border-line pt-4 sm:grid-cols-3">
      {items.map((x) => (
        <div key={x.id} data-testid={x.id} className="min-w-0">
          <dt className="text-[12px] text-muted">{x.label}</dt>
          <dd className="mt-0.5 text-[15px] font-semibold text-ink tabular-nums">
            {x.value}
            {x.change !== null && <span className="ml-1.5 text-[12px] font-normal text-muted">{signed(x.change, pct1)} vs {yr(k.previous_year)}</span>}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Change({ pct }: { pct: number | null | undefined }) {
  if (pct === null || pct === undefined) return <span className="text-muted">–</span>;
  const Icon = pct > 0 ? ArrowUpRight : pct < 0 ? ArrowDownRight : Minus;
  return (
    <span className={cn("inline-flex items-center gap-0.5 tabular-nums", pct > 0 ? "text-ok" : pct < 0 ? "text-bad" : "text-muted")}>
      <Icon size={14} aria-hidden />{signed(pct, pct1)}
    </span>
  );
}

function Comparison({ rows, state, loading, periodLabel, refDate, onSelect }: {
  rows: MarketRow[]; state?: string; loading: boolean; periodLabel: string; refDate?: string; onSelect: (s: string) => void;
}) {
  const [all, setAll] = useState(false);
  const ranked = rows.filter((r) => r.comparable).sort((a, b) => b.latest!.price - a.latest!.price);
  const others = rows.filter((r) => !r.comparable && r.latest).sort((a, b) => b.latest!.date.localeCompare(a.latest!.date));
  const sel = ranked.find((r) => r.state === state);
  const max = Math.max(1, ...ranked.map((r) => r.latest!.price));
  const shown = all ? ranked : ranked.slice(0, 8);
  return (
    <Card id="compare" className="scroll-mt-20 p-5" data-testid="comparison">
      <SectionTitle title="Compare states" hint={refDate ? <>Typical price for the week of {longDate(refDate)}, highest first. Change is over the last {periodLabel}.</> : "Typical price by state"} />
      {loading ? <Loading label="Loading other states" /> : ranked.length < 2 ? (
        <Empty title="Not enough information to compare">No other state reported prices for the same week.</Empty>
      ) : (
        <>
          <ul className="mt-4 divide-y divide-line">
            {shown.map((r) => {
              const isSel = r.state === state;
              const diff = sel && !isSel ? r.latest!.price - sel.latest!.price : null;
              return (
                <li key={r.state}>
                  <button type="button" onClick={() => onSelect(r.state)} aria-current={isSel || undefined} aria-label={`Show ${r.state} price history`}
                    className={cn("grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1.5 rounded-lg px-2 py-2.5 text-left transition sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)_6.5rem_5rem]",
                      isSel ? "bg-ok-soft" : "hover:bg-subtle")}>
                    <span className="min-w-0">
                      <span className="block truncate text-[13.5px] font-medium text-ink">{r.state}</span>
                      {isSel ? <span className="text-[11.5px] font-medium text-ok">Your selection</span>
                        : diff !== null && <span className="text-[11.5px] text-muted tabular-nums">{signed(diff, rs)} vs {state}</span>}
                    </span>
                    <span className="order-last col-span-2 h-2 rounded-full bg-subtle sm:order-none sm:col-span-1" aria-hidden>
                      <span className={cn("block h-2 rounded-full", isSel ? "bg-ok" : "bg-ok/45")} style={{ width: `${(r.latest!.price / max) * 100}%` }} />
                    </span>
                    <span className="text-right text-[14px] font-semibold text-ink tabular-nums">{rs(r.latest!.price)}</span>
                    <span className="hidden text-right text-[12.5px] sm:block"><Change pct={r.stats?.changePct} /></span>
                  </button>
                </li>
              );
            })}
          </ul>
          {ranked.length > 8 && (
            <button type="button" onClick={() => setAll(!all)} className="mt-2 h-9 rounded-lg px-2 text-[13px] font-medium text-ok hover:bg-ok-soft">
              {all ? "Show fewer states" : `Show all ${ranked.length} states`}
            </button>
          )}
        </>
      )}
      {!loading && others.length > 0 && (
        <details className="mt-3 rounded-lg bg-subtle px-3 py-2 text-[12.5px] text-muted">
          <summary className="cursor-pointer font-medium text-ink">{others.length} state{others.length > 1 ? "s" : ""} not compared: no report for this week</summary>
          <ul className="mt-2 space-y-1">
            {others.map((r) => <li key={r.state} className="flex justify-between gap-3"><span>{r.state}</span><span className="tabular-nums">{rs(r.latest!.price)} · week of {longDate(r.latest!.date)}</span></li>)}
          </ul>
        </details>
      )}
      <p className="mt-3 text-[12px] text-muted">States are not ranked by distance; transport, fees and quality differences are not included.</p>
    </Card>
  );
}

function RecentChanges({ rows, loading, periodLabel, refDate }: { rows: MarketRow[]; loading: boolean; periodLabel: string; refDate?: string }) {
  const withChange = rows.filter((r) => r.comparable && r.stats?.changePct !== null && r.stats?.changePct !== undefined);
  const rising = withChange.filter((r) => r.stats!.changePct! >= 3).sort((a, b) => b.stats!.changePct! - a.stats!.changePct!).slice(0, 3);
  const falling = withChange.filter((r) => r.stats!.changePct! <= -3).sort((a, b) => a.stats!.changePct! - b.stats!.changePct!).slice(0, 3);
  const priced = rows.filter((r) => r.comparable).sort((a, b) => b.latest!.price - a.latest!.price);
  const hi = priced[0], lo = priced[priced.length - 1];
  const List = ({ title, items, empty }: { title: string; items: MarketRow[]; empty: string }) => (
    <div>
      <h3 className="text-[13px] font-semibold text-ink">{title}</h3>
      {!items.length ? <p className="mt-1 text-[12.5px] text-muted">{empty}</p> : (
        <ul className="mt-1.5 space-y-1">
          {items.map((r) => (
            <li key={r.state} className="flex items-center justify-between gap-3 text-[13px]">
              <span className="truncate text-ink">{r.state}</span>
              <span className="flex shrink-0 items-center gap-2"><span className="text-[12px] text-muted tabular-nums">{signed(r.stats!.change!, rs)}</span><Change pct={r.stats!.changePct} /></span>
            </li>))}
        </ul>
      )}
    </div>
  );
  return (
    <Card className="p-5" data-testid="recent-changes">
      <SectionTitle title="Recent changes" hint={`Over the last ${periodLabel}, states reporting in the same week.`} />
      {loading ? <Loading /> : withChange.length < 2 ? <Empty title="Not enough information to compare changes" /> : (
        <div className="mt-4 space-y-4">
          <List title="Rising the most" items={rising} empty="No state rose by 3% or more." />
          <List title="Falling the most" items={falling} empty="No state fell by 3% or more." />
          {hi && lo && hi !== lo && (
            <div className="rounded-lg bg-subtle px-3 py-2.5 text-[12.5px] text-muted">
              <span className="font-semibold text-ink">Gap between states: {rs(hi.latest!.price - lo.latest!.price)}</span> per quintal between {hi.state} ({rs(hi.latest!.price)}) and {lo.state} ({rs(lo.latest!.price)}) for the week of {longDate(refDate!)}.
            </div>
          )}
          <p className="text-[12px] text-muted">Changes of less than 3% either way are treated as steady. <Chip tone="muted">Not a buy or sell signal</Chip></p>
        </div>
      )}
    </Card>
  );
}
