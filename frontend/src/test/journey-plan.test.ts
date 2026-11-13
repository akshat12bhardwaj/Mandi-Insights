import { expect, it } from "vitest";
import { journeySchedule } from "../components/JourneyPlan";
import type { Strategy, TradeRoute } from "../lib/intelligence";

it("carries sequential trips across midnight and adds storage days to the sale date", () => {
  const strategy = { trips: 2, storage_days: 7 } as Strategy;
  const route = { hours: 10 } as TradeRoute;
  expect(journeySchedule(strategy, route, "2026-11-13")).toMatchObject({
    buy: "13 Nov", arrival: "14 Nov", sale: "21 Nov", hours: 20,
  });
});
