import * as Tabs from "@radix-ui/react-tabs";
import { TrendingUp } from "lucide-react";
import { useState } from "react";
import { Legend, Lines, SERIES, type Line_ } from "../components/charts";
import { PageHeader, SectionTitle, useCrop } from "../components/Layout";
import { Card, Empty, ErrorState, Loading, Q, SearchBox, Segmented, Select } from "../components/ui";
import { useArrivalSeries, useArrivalsSummary, useMeta, usePriceSeries, usePriceSummary, useSeriesOptions, type SeriesKey } from "../lib/api";
import { cn, int, rs, shortDate } from "../lib/format";
import { cropOptions } from "./Overview";

type Kind = "prices" | "arrivals";
const PERIODS = [
  { value: "val_2019", label: "2019" }, { value: "val_2020", label: "2020" },
  { value: "test_2021", label: "2021" }, { value: "test_2022", label: "2022" },
];
const LINES: Line_[] = [
  { key: "persistence", name: "Last week's value", color: SERIES.reference, dashed: true, width: 1.5 },
  { key: "observed", name: "Actual (reported)", color: SERIES.actual, width: 1.5 },
  { key: "hgb_conservative", name: "Estimate", color: SERIES.accent },
];
const keyOf = (s: SeriesKey) => `${s.state}|${s.district}|${s.market}|${s.variety}`;

export default function Outlook() {
  const { crop, setCrop } = useCrop();
  const [kind, setKind] = useState<Kind>("prices");
  const [horizon, setHorizon] = useState(1);
  const [period, setPeriod] = useState("test_2022");
  const meta = useMeta();

  return (
    <Tabs.Root value={kind} onValueChange={(v) => setKind(v as Kind)}>
      <PageHeader icon={<TrendingUp size={18} />} title="Price Outlook" subtitle="How well past 1–4 week estimates matched what was actually reported · not a live forecast"
        controls={<>
          <Tabs.List aria-label="Outlook type" className="inline-flex h-9 items-center gap-0.5 rounded-lg border border-line bg-subtle p-0.5">
            {(["prices", "arrivals"] as Kind[]).map((k) => (
              <Tabs.Trigger key={k} value={k} className="h-7.5 rounded-md px-3 text-[13px] font-medium text-ink/65 capitalize data-[state=active]:bg-white data-[state=active]:text-ok data-[state=active]:shadow-pill">{k}</Tabs.Trigger>
            ))}
          </Tabs.List>
          <Segmented label="Crop" value={crop} onChange={setCrop} options={cropOptions} />
          <Segmented label="Horizon" value={horizon} onChange={setHorizon} options={(meta.data?.horizons ?? [1, 2, 4]).map((h) => ({ value: h, label: `${h} wk ahead` }))} />
          {kind === "arrivals" && <Select label="Year" className="w-28" value={period} onChange={setPeriod} options={PERIODS} />}
        </>}
      />
      {(["prices", "arrivals"] as Kind[]).map((k) => (
        <Tabs.Content key={k} value={k}>
          <SeriesExplorer kind={k} horizon={horizon} period={period} />
        </Tabs.Content>
      ))}
    </Tabs.Root>
  );
}

function SeriesExplorer({ kind, horizon, period }: { kind: Kind; horizon: number; period: string }) {
  const { crop } = useCrop();
  const opts = useSeriesOptions(kind, crop, horizon);
  const [query, setQuery] = useState("");
  const [sel, setSel] = useState<string>();
  const list = opts.data ?? [];
  const series = list.find((s) => keyOf(s) === sel) ?? list[0];
  const key = series && { state: series.state, district: series.district, market: series.market, variety: series.variety };
  const shown = list.filter((s) => `${s.market} ${s.district} ${s.state} ${s.variety}`.toLowerCase().includes(query.trim().toLowerCase()));

  return (
    <div className="grid gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
      <Card glass className="flex max-h-[520px] flex-col overflow-hidden lg:h-[max(600px,calc(100vh-200px))] lg:max-h-none">
        <div className="border-b border-line/70 px-5 pt-4 pb-3">
          <h2 className="text-[15px] font-semibold">Markets</h2>
          <p className="text-[12px] text-muted">{crop} · {horizon} week{horizon > 1 ? "s" : ""} ahead · {list.length} markets</p>
        </div>
        <div className="px-4 pt-3"><SearchBox value={query} onChange={setQuery} placeholder="Search market, district or state" /></div>
        <div className="thin-scroll mt-3 min-h-0 flex-1 overflow-y-auto px-4 pb-4" data-testid="series-list">
          {opts.isLoading ? <Loading label="Loading markets" /> : opts.error ? <ErrorState error={opts.error} /> : !shown.length ? <Empty title="No matching markets" /> : (
            <ul className="space-y-1.5">
              {shown.slice(0, 150).map((s) => (
                <li key={keyOf(s)}>
                  <button type="button" onClick={() => setSel(keyOf(s))} aria-current={series && keyOf(s) === keyOf(series)}
                    className={cn("w-full rounded-xl px-3 py-2 text-left transition", series && keyOf(s) === keyOf(series) ? "bg-white shadow-soft" : "bg-white/40 hover:bg-white/70")}>
                    <div className="truncate text-[13px]">{s.market}</div>
                    <div className="truncate text-[11px] text-muted">{s.district}, {s.state} · {s.variety}</div>
                  </button>
                </li>))}
              {shown.length > 150 && <li className="px-2 pt-1 text-[12px] text-muted">Showing 150 of {shown.length}; refine the search.</li>}
            </ul>
          )}
        </div>
      </Card>
      <div className="flex min-w-0 flex-col gap-4">
        <Card glass className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 className="truncate text-[18px] font-semibold">{series ? `${series.market}, ${series.district}` : "Select a market"}</h2>
              <p className="text-[12.5px] text-muted">
                {kind === "prices" ? `Modal price, ₹ per quintal · estimated ${horizon} week${horizon > 1 ? "s" : ""} ahead · 2019–2020` : `Arrivals, tonnes per day · estimated ${horizon} week${horizon > 1 ? "s" : ""} ahead · ${PERIODS.find((p) => p.value === period)?.label}`}
              </p>
            </div>
            <Legend items={LINES.map((l) => ({ name: l.name, color: l.color, dashed: l.dashed }))} />
          </div>
          <div className="mt-4 h-[360px]" data-testid="outlook-chart">
            {kind === "prices" ? <PriceChart horizon={horizon} s={key} /> : <ArrivalChart horizon={horizon} period={period} s={key} />}
          </div>
        </Card>
        <Metrics kind={kind} horizon={horizon} />
      </div>
    </div>
  );
}

function PriceChart({ horizon, s }: { horizon: number; s?: SeriesKey }) {
  const { crop } = useCrop();
  const q = usePriceSeries(crop, horizon, s);
  if (!s) return <Empty title="No market selected" />;
  return <Q query={q} empty={(d) => !d.length} loading="Loading data">{(d) => <Lines data={d} x="origin_date" xFmt={shortDate} fmt={(v) => `₹${int(v)}`} lines={LINES} />}</Q>;
}

function ArrivalChart({ horizon, period, s }: { horizon: number; period: string; s?: SeriesKey }) {
  const { crop } = useCrop();
  const q = useArrivalSeries(crop, horizon, period, s);
  if (!s) return <Empty title="No market selected" />;
  return <Q query={q} empty={(d) => !d.length} loading="Loading data">{(d) => <Lines data={d.map((r) => ({ ...r, week: `Week ${r.week_no + 1}` }))} x="week" fmt={(v) => `${v.toFixed(1)} t/day`} lines={LINES} />}</Q>;
}

/** Plain-language reliability from the stored results: typical miss of the estimate vs simply using last week's value. */
function Metrics({ kind, horizon }: { kind: Kind; horizon: number }) {
  const { crop } = useCrop();
  const ps = usePriceSummary();
  const as = useArrivalsSummary();
  const h = `${horizon} week${horizon > 1 ? "s" : ""} ahead`;
  return (
    <Card className="p-5" data-testid="reliability">
      <SectionTitle title="How reliable were these estimates?" hint={`${crop} · ${h} · checked once on 2021–2022 data`} />
      <div className="mt-3 text-[13.5px] leading-relaxed text-ink">
        {kind === "prices" ? (
          <Q query={ps}>{(d) => {
            const rows = d.test.filter((r) => r.crop === crop && r.horizon_weeks === horizon);
            const r = rows.find((x) => x.period === "test_combined") ?? rows[0];
            if (!r) return <p className="text-muted">No stored check for this crop and time ahead.</p>;
            return r.approach === "persistence"
              ? <p>The estimate was <b>not more accurate</b> than simply using last week's price, which was off by about {rs(r.persistence_mae)} per quintal on average.</p>
              : <p>The estimate was off by about <b>{rs(r.mae)} per quintal</b> on average, against {rs(r.persistence_mae)} for simply using last week's price{r.rel_mae_improvement_pct > 0 ? ` (${r.rel_mae_improvement_pct.toFixed(1)}% closer)` : ", so it was no better"}.</p>;
          }}</Q>
        ) : (
          <Q query={as}>{(d) => {
            const rows = d.test.filter((r) => r.crop === crop && r.horizon_weeks === horizon);
            const r = rows.find((x) => x.period === "test_combined") ?? rows[0];
            if (!r) return <p className="text-muted">No stored check for this crop and time ahead.</p>;
            return <p>Estimated arrivals were typically off by <b>{r.wape_pct.toFixed(0)}%</b>, against {r.persistence_wape_pct.toFixed(0)}% for simply using last week's arrivals.</p>;
          }}</Q>
        )}
      </div>
      <p className="mt-3 text-[12px] text-muted">These are past checks, not a promise about future accuracy. Use them alongside current mandi rates.</p>
    </Card>
  );
}
