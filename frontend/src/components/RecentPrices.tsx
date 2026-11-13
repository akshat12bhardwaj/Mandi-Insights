import { useMemo } from "react";
import { useRecentMeta, useRecentWeekly, type Crop } from "../lib/api";
import { longDate, rs } from "../lib/format";
import { weeklyGrid } from "../lib/prices";
import { PriceHistory } from "./charts";
import { Card, Chip, Empty, ErrorState, Loading } from "./ui";

const BREAK_LABELS: Record<string, string> = { "2024-02-03": "New source", "2025-11-07": "Market list relaunch" };
const monday = (iso: string) => {
  const t = Date.parse(iso.slice(0, 10));
  return new Date(t - ((new Date(t).getUTCDay() + 6) % 7) * 86_400_000).toISOString().slice(0, 10);
};

/** Observed weekly state prices after the main history window: two sources, gaps kept, source changes marked. */
export function RecentPrices({ crop, state }: { crop: Crop; state?: string }) {
  const meta = useRecentMeta();
  const has = !!state && !!meta.data?.states_by_crop?.[crop]?.includes(state);
  const weekly = useRecentWeekly(crop, state, has);
  const rows = weekly.data ?? [];
  const grid = useMemo(() => {
    const obs = rows.map((r) => ({ date: r.week_start.slice(0, 10), price: r.modal_price_median }));
    return obs.length ? weeklyGrid(obs, obs[obs.length - 1].date) : [];
  }, [rows]);
  const breaks = (meta.data?.breaks ?? []).map((b) => ({ date: monday(b.date), label: BREAK_LABELS[b.date] ?? "Source change" }))
    .filter((b) => grid.some((g) => g.date === b.date));
  const latest = rows[rows.length - 1];
  const reported = grid.filter((g) => g.price !== null).length;

  return (
    <Card className="p-5" data-testid="recent-prices">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-[15px] font-semibold">Recent prices{state ? ` · ${state}` : ""}</h2>
          <p className="text-[12px] text-muted">Typical weekly {crop.toLowerCase()} price, July 2020 onward · observed reports, not a forecast</p>
        </div>
        {latest && <div className="text-right"><div className="text-[18px] font-semibold tabular-nums">{rs(latest.modal_price_median)}</div>
          <div className="text-[12px] text-muted">per quintal · week of {longDate(latest.week_start)}</div></div>}
      </div>
      <div className="mt-3 h-[220px]">
        {meta.isLoading ? <Loading /> : meta.error ? <ErrorState error={meta.error} /> : !meta.data?.available ? (
          <Empty title="Recent prices are not available">They have not been prepared in this installation.</Empty>
        ) : !has ? (
          <Empty title={`No recent reports for ${state ?? "this state"}`}>No Fair Average Quality {crop.toLowerCase()} prices were reported here in the recent data.</Empty>
        ) : weekly.isLoading ? <Loading /> : weekly.error ? <ErrorState error={weekly.error} /> : <PriceHistory data={grid} breaks={breaks} />}
      </div>
      {meta.data?.available && (
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11.5px] text-faint">
          {has && <Chip tone={reported / Math.max(grid.length, 1) < 0.5 ? "warn" : "muted"}>{reported} of {grid.length} weeks reported</Chip>}
          <span>Gaps are weeks with no report. Dotted lines mark a change of source (Feb 2024) and the relaunch of the market list (Nov 2025), after which many markets were renamed.</span>
          <span>{meta.data.attribution}; retrieved {longDate(meta.data.retrieved ?? "")}.</span>
        </div>
      )}
    </Card>
  );
}
