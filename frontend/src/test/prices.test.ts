import { describe, expect, it } from "vitest";
import type { Week } from "../lib/api";
import { buildInsights, compareStates, inWindow, observed, stats, weeklyGrid } from "../lib/prices";

const w = (d: string, p: number): Week => ({ week_start: `${d}T00:00:00`, records: 1, markets: 1, arrivals_tonnes_sum: 1, modal_price_median: p });
const MH = [w("2020-05-04", 1000), w("2020-05-11", 900), w("2020-05-25", 800), w("2020-06-01", 700)];   // 18 May missing

describe("price figures", () => {
  it("windows, summarises and keeps missing weeks as gaps", () => {
    const obs = observed(MH);
    const win = inWindow(obs, "2020-06-01", 30);
    expect(win.map((o) => o.date)).toEqual(["2020-05-04", "2020-05-11", "2020-05-25", "2020-06-01"]);
    const s = stats(win)!;
    expect([s.change, s.changePct, s.high.price, s.low.price]).toEqual([-300, -30, 1000, 700]);
    expect(weeklyGrid(win, "2020-06-01").map((g) => g.price)).toEqual([1000, 900, null, 800, 700]);
    expect(stats(win.slice(0, 1))!.changePct).toBeNull();     // one report is not a trend
  });

  it("ranks only states that reported in the same week", () => {
    const rows = compareStates({ MH, GJ: [w("2020-06-01", 1200)], RJ: [w("2020-05-25", 2000)] }, "2020-06-01", 30);
    const by = Object.fromEntries(rows.map((r) => [r.state, r]));
    expect([by.MH.comparable, by.GJ.comparable, by.RJ.comparable]).toEqual([true, true, false]);
    const ins = buildInsights({ crop: "Onion", state: "MH", periodLabel: "30 days", s: by.MH.stats, rows });
    expect(ins.map((i) => i.id)).toEqual(["trend", "compare", "distance", "range"]);
    expect(ins[0].title).toBe("Prices have fallen in MH");
    expect(ins[1].evidence).toContain("GJ reported ₹1,200 against ₹700");   // RJ's higher but older price is not used
  });

  it("says so when there is nothing to compare", () => {
    const rows = compareStates({ MH }, "2020-06-01", 30);
    const ins = buildInsights({ crop: "Onion", state: "MH", periodLabel: "30 days", s: rows[0].stats, rows });
    expect(ins.find((i) => i.id === "compare")!.title).toBe("Not enough data to compare states");
    expect(buildInsights({ crop: "Onion", state: "MH", periodLabel: "30 days", s: null, rows })[0].title).toBe("Not enough price data");
  });
});
