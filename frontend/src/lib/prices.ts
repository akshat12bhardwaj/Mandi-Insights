import type { Week } from "./api";
import { longDate, rs } from "./format";

// Weekly state prices (median of mandi modal prices, ₹/quintal) turned into decision figures. Everything here works on
// observed weeks only: a missing week stays missing (never zero, never interpolated).

export const PERIODS = [
  { value: "1m", label: "30 days", days: 30 },
  { value: "3m", label: "90 days", days: 90 },
  { value: "6m", label: "6 months", days: 182 },
  { value: "1y", label: "1 year", days: 365 },
  { value: "3y", label: "3 years", days: 1095 },
] as const;
export type Period = (typeof PERIODS)[number]["value"];

export interface Obs { date: string; price: number }   // date: ISO week start (Monday)
const DAY = 86_400_000;
const ms = (iso: string) => Date.parse(iso.slice(0, 10));
const iso = (t: number) => new Date(t).toISOString().slice(0, 10);

/** All observed weeks, oldest first. */
export const observed = (weeks: Week[]): Obs[] =>
  weeks.filter((w) => w.modal_price_median !== null && w.modal_price_median !== undefined)
    .map((w) => ({ date: w.week_start.slice(0, 10), price: w.modal_price_median }))
    .sort((a, b) => a.date.localeCompare(b.date));

/** Observed weeks in the window (end - days, end]. */
export const inWindow = (obs: Obs[], end: string, days: number) =>
  obs.filter((o) => ms(o.date) > ms(end) - days * DAY && ms(o.date) <= ms(end));

export interface Stats { n: number; first: Obs; latest: Obs; high: Obs; low: Obs; average: number; change: number | null; changePct: number | null }

export function stats(obs: Obs[]): Stats | null {
  if (!obs.length) return null;
  const first = obs[0], latest = obs[obs.length - 1];
  const high = obs.reduce((a, b) => (b.price > a.price ? b : a));
  const low = obs.reduce((a, b) => (b.price < a.price ? b : a));
  const two = obs.length >= 2 && first.price > 0;
  return {
    n: obs.length, first, latest, high, low, average: obs.reduce((s, o) => s + o.price, 0) / obs.length,
    change: two ? latest.price - first.price : null, changePct: two ? (100 * (latest.price - first.price)) / first.price : null,
  };
}

/** One row per week across the window so gaps show as breaks in the chart. */
export function weeklyGrid(obs: Obs[], end: string): { date: string; price: number | null }[] {
  if (!obs.length) return [];
  const byDate = new Map(obs.map((o) => [o.date, o.price]));
  const out: { date: string; price: number | null }[] = [];
  for (let t = ms(obs[0].date); t <= ms(end); t += 7 * DAY) out.push({ date: iso(t), price: byDate.get(iso(t)) ?? null });
  return out;
}

export interface MarketRow { state: string; latest: Obs | null; stats: Stats | null; comparable: boolean }

/**
 * Same crop, same reporting week, same window: a state is comparable only if it reported in the reference week.
 * Others keep their last report (on or before the reference week) for display but are never ranked.
 */
export function compareStates(byState: Record<string, Week[]>, refDate: string, days: number): MarketRow[] {
  return Object.entries(byState).map(([state, weeks]) => {
    const obs = observed(weeks).filter((o) => o.date <= refDate);
    const latest = obs[obs.length - 1] ?? null;
    const comparable = latest?.date === refDate;
    return { state, latest, comparable, stats: comparable ? stats(inWindow(obs, refDate, days)) : null };
  });
}

export interface Insight {
  id: string; tone: "up" | "down" | "neutral" | "warn"; title: string; evidence: string;
  action: { label: string; to: string };   // "#id" scrolls within the page; "/path" navigates
}

const signedRs = (v: number) => `${v >= 0 ? "+" : "−"}${rs(Math.abs(v))}`;
const signedPct = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`;

/** Plain-language observations backed only by the figures passed in. No forecasts, no buy/sell signals. */
export function buildInsights({ crop, state, periodLabel, s, rows, dataEnd }: {
  crop: string; state: string; periodLabel: string; s: Stats | null; rows: MarketRow[]; dataEnd?: string;
}): Insight[] {
  const out: Insight[] = [];
  if (!s) {
    return [{ id: "none", tone: "warn", title: "Not enough price data", action: { label: "Choose a longer period", to: "#filters" },
      evidence: `No ${crop.toLowerCase()} prices were reported in ${state} in the selected ${periodLabel}.` }];
  }
  if (dataEnd && s.latest.date < dataEnd) {
    out.push({ id: "stale", tone: "warn", title: `${state} has no recent reports`, action: { label: "Compare markets", to: "#compare" },
      evidence: `Its last report is for the week of ${longDate(s.latest.date)}, while other states report up to ${longDate(dataEnd)}.` });
  }

  if (s.changePct === null) {
    out.push({ id: "trend", tone: "warn", title: "Too few reports to see a trend", action: { label: "Choose a longer period", to: "#filters" },
      evidence: `Only one week in the last ${periodLabel} has a reported price (${rs(s.latest.price)} per quintal).` });
  } else if (Math.abs(s.changePct) < 3) {
    out.push({ id: "trend", tone: "neutral", title: `Prices are steady in ${state}`, action: { label: "View price history", to: "#price-history" },
      evidence: `The typical price moved ${signedPct(s.changePct)} over the last ${periodLabel}, from ${rs(s.first.price)} to ${rs(s.latest.price)} per quintal.` });
  } else if (s.changePct > 0) {
    out.push({ id: "trend", tone: "up", title: `Prices are rising in ${state}`, action: { label: "View price history", to: "#price-history" },
      evidence: `The typical price rose ${s.changePct.toFixed(1)}% (${rs(s.change!)} per quintal) over the last ${periodLabel}, to ${rs(s.latest.price)} per quintal.` });
  } else {
    out.push({ id: "trend", tone: "down", title: `Prices have fallen in ${state}`, action: { label: "Compare markets", to: "#compare" },
      evidence: `The typical price fell ${Math.abs(s.changePct).toFixed(1)}% (${rs(-s.change!)} per quintal) over the last ${periodLabel}; check other states before deciding where to sell.` });
  }

  const others = rows.filter((r) => r.comparable && r.state !== state && r.latest);
  const higher = others.filter((r) => r.latest!.price > s.latest.price).sort((a, b) => b.latest!.price - a.latest!.price);
  const week = longDate(s.latest.date);
  if (!others.length) {
    out.push({ id: "compare", tone: "warn", title: "Not enough data to compare states", action: { label: "Compare markets", to: "#compare" },
      evidence: `No other state reported ${crop.toLowerCase()} prices for the week of ${week}.` });
  } else if (higher.length) {
    const top = higher[0];
    const gap = top.latest!.price - s.latest.price;
    out.push({ id: "compare", tone: "neutral", title: `${higher.length} of ${others.length} other states reported a higher price`,
      action: { label: "Compare markets", to: "#compare" },
      evidence: `${top.state} reported ${rs(top.latest!.price)} against ${rs(s.latest.price)} in ${state} for the week of ${week} (${signedRs(gap)} per quintal); transport, fees and quality can outweigh the gap.` });
    out.push({ id: "distance", tone: "neutral", title: "Check the trip before choosing a market", action: { label: "Check road distance", to: "/routes" },
      evidence: "A higher quoted price only helps if it covers the extra distance and costs; road distances between district points are available." });
  } else {
    out.push({ id: "compare", tone: "neutral", title: "No other state reported a higher price", action: { label: "Compare markets", to: "#compare" },
      evidence: `Among ${others.length + 1} states reporting for the week of ${week}, ${state} had the highest typical price.` });
  }

  const range = s.high.price - s.low.price;
  if (s.n >= 4 && range >= 0.05 * s.latest.price) {
    if (s.latest.price >= s.high.price - 0.1 * range) {
      out.push({ id: "range", tone: "neutral", title: `Near the top of its ${periodLabel} range`, action: { label: "View price history", to: "#price-history" },
        evidence: `The latest price is close to the ${periodLabel} high of ${rs(s.high.price)} (week of ${longDate(s.high.date)}); past highs do not show where prices go next.` });
    } else if (s.latest.price <= s.low.price + 0.1 * range) {
      out.push({ id: "range", tone: "neutral", title: `Near the bottom of its ${periodLabel} range`, action: { label: "View price history", to: "#price-history" },
        evidence: `The latest price is close to the ${periodLabel} low of ${rs(s.low.price)} (week of ${longDate(s.low.date)}); past lows do not show where prices go next.` });
    }
  }
  return out;
}
