import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, it, expect, vi } from "vitest";
import { Strategies } from "../pages/Strategies";
import type { Strategy } from "../lib/intelligence";
vi.mock("../components/MapView", () => ({
  MapView: ({ truck, stopIndex }: { truck?: boolean; stopIndex?: number }) =>
    <div data-testid="map" data-truck={String(truck)} data-stop={stopIndex} />,
}));

function trade(
  id: string,
  mode: "intrastate" | "interstate",
  alternative = false,
): Strategy {
  const market = (name: string, state: string) => ({
    series_id: name,
    crop: "Onion",
    state,
    district: "D",
    market: name,
    variety: "Other",
    grade: "FAQ",
    source: "datagov",
    predicted_price: 1000,
    last_observed_price: 1000,
    status: "Estimated today",
    coordinate: { lat: 25, lng: 75, node: name, precision: "Approximate" },
  });
  return {
    id,
    crop: "Onion",
    trading_mode: mode,
    buy: market("Buy " + id, "Haryana"),
    sell: market("Sell " + id, mode === "intrastate" ? "Haryana" : "Punjab"),
    quantity_q: 100,
    trips: 1,
    vehicle: "Medium truck",
    route: {
      objective: "approximate",
      km: 100,
      hours: 2,
      basis: "Approximate distance scenario",
      origin: "A",
      destination: "B",
      transport_cost: 3500,
    },
    routes: [],
    storage_days: 0,
    warehouse: null,
    procurement: 100000,
    transport: 3500,
    handling: 1800,
    storage: 0,
    total_cost: 105300,
    sale_revenue: 130000,
    margin: 24700,
    risk_adjusted_margin: 20000,
    uncertainty_screen: 4700,
    sale_price: 1300,
    sale_basis: "Current-day forecast",
    loss_pct: 1,
    explanation: "Calculated comparison",
    decision: {
      scope: alternative ? "selected_alternative" : "category_recommendation",
      headline: "Buy Onion in Buy " + id + " · sell in Sell " + id,
      cards: [],
      alternatives: [],
      trade_off: "Lower freight.",
      why_selected: "Measured adjusted value",
      next_alternative: "Alternative adds ₹500 freight.",
      practical_tie: false,
      break_even_sale_price: 1063,
      what_changes: "Lower realized price.",
      storage: "Compare dates",
    },
  };
}

const inside = trade("inside", "intrastate"),
  outside = trade("outside", "interstate");
let batch = "first",
  stale = false,
  storageWins = false;
beforeEach(() => {
  batch = "first";
  stale = false;
  storageWins = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      const url = new URL(input, "http://localhost");
      const crop = url.searchParams.get("crop") || "";
      const requested = url.searchParams.get("mode") || "auto";
      const mode =
        requested === "auto"
          ? crop === "Wheat"
            ? "intrastate"
            : "interstate"
          : requested;
      const quantity = Number(url.searchParams.get("quantity") || 100);
      const state = url.searchParams.get("state") || "";
      const make = (r: Strategy) => ({ ...r, quantity_q: quantity });
      const intraRows = [
        inside,
        ...[1, 2, 3].map((i) => trade("intra-alt" + i, "intrastate", true)),
      ].map(make);
      const interRows = [
        outside,
        ...[1, 2, 3].map((i) => trade("inter-alt" + i, "interstate", true)),
      ].map(make);
      if (storageWins) {
        const schedule = {
          procurement_at: "2026-11-13T08:00:00+05:30", depart_at: "2026-11-13T08:30:00+05:30",
          storage_start_at: null, storage_end_at: null, arrival_at: "2026-11-13T11:00:00+05:30",
          sale_at: "2026-11-13T11:00:00+05:30", elapsed_hours: 3, travel_hours: 2, loading_hours: .5,
        };
        const geometry: [number, number][] = [[25, 75], [26, 75], [27, 75]];
        const direct = { ...interRows[0], schedule, route: { ...outside.route, geometry } };
        const stored = {
          ...direct, storage_days: 7, storage: 1400, sale_price: 2000, sale_revenue: 198000,
          total_cost: 106700, margin: 91300,
          warehouse: { warehouse_id: "W", name: "Test Warehouse", latitude: 26, longitude: 75 } as Strategy["warehouse"],
          route: { ...direct.route, objective: "via_storage", stop_index: 1 },
          schedule: { ...schedule, storage_start_at: "2026-11-13T10:00:00+05:30",
            storage_end_at: "2026-11-20T10:00:00+05:30", sale_at: "2026-11-20T11:00:00+05:30",
            arrival_at: "2026-11-20T11:00:00+05:30", elapsed_hours: 171 },
        };
        interRows[0] = { ...stored, timing_options: [stored, direct], route_plans: [direct] };
      }
      const unavailable =
        (crop === "Wheat" && mode === "interstate") ||
        (state === "GJ" && mode === "intrastate") ||
        (stale && crop === "Onion");
      const groups = {
        intrastate: {
          rows: intraRows,
          best: intraRows[0],
          candidate_count: 8,
          empty_reason: null,
        },
        interstate: {
          rows: crop === "Wheat" ? [] : interRows,
          best: crop === "Wheat" ? null : interRows[0],
          candidate_count: crop === "Wheat" ? 0 : 9,
          empty_reason: "No exact cross-state variety match.",
        },
      };
      const active = groups[mode as "intrastate" | "interstate"];
      const body = url.pathname.endsWith("/overview")
        ? {
            date: "2026-11-13",
            batch_id: batch,
            catalog: { crops: [{ crop: "Brinjal" }] },
            freshness: { batch_current: true, eligible_predictions: 254 },
            config: {
              vehicles: { "Medium truck": { capacity_q: 100, rs_km: 35 } },
              handling_rs_q: 18,
            },
          }
        : url.pathname.endsWith("/markets")
          ? { rows: [], states: [], districts: [], map_points: [] }
          : url.pathname.endsWith("/warehouses")
            ? { rows: [], states: [] }
            : {
                batch_id: batch,
                dataset_version: "version-" + batch,
                date: "2026-11-13",
                active_mode: mode,
                default_mode: "interstate",
                rows: unavailable ? [] : active.rows,
                groups: unavailable
                  ? { ...groups, [mode]: { ...active, rows: [], best: null } }
                  : groups,
                competitors: unavailable ? [] : active.rows.slice(1, 4),
                candidate_count: active.candidate_count,
                ranking: "Historical error and route evidence.",
                forecast_ready_crops: ["Onion", "Potato", "Wheat"],
                filters: {
                  crops:
                    mode === "intrastate"
                      ? ["Onion", "Potato", "Wheat"]
                      : ["Onion", "Potato"],
                  states:
                    crop === "Potato" && mode === "interstate"
                      ? [{ id: "GJ", name: "Gujarat" }, { id: "MP", name: "Madhya Pradesh" }]
                      : crop === "Potato" ? []
                      : [
                          { id: "HR", name: "Haryana" },
                          { id: "PB", name: "Punjab" },
                        ],
                },
                effective_filters: {
                  crop,
                  state: url.searchParams.get("state") || "",
                  buy_id: "",
                  sell_id: "",
                  mode,
                },
                notices: [],
                fallback_crops: ["Onion", "Potato"],
                empty_explanation: unavailable
                  ? "No exact cross-state variety match. Your crop is preserved."
                  : null,
                selected_comparison: {
                  insight: "Alternative adds ₹500 freight.",
                  crop: "Onion",
                  id: "competitor",
                  score_difference: 500,
                  margin_difference: 500,
                },
              };
      return new Response(JSON.stringify(body));
    }),
  );
});
function show(path = "/") {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[path]}>
        <Strategies />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("shows one recommendation and defaults to the strongest mode", async () => {
  show();
  await screen.findByText(/Top recommendation/);
  expect(screen.getByRole("region", { name: "Journey plan" })).toHaveTextContent("Estimated arrival for sale");
  const timing = screen.getByRole("region", { name: "When to sell" });
  expect(within(timing).getByRole("heading", { name: "Sell on arrival" })).toBeVisible();
  expect(within(timing).getByRole("heading", { name: "Store 30 days" })).toBeVisible();
  expect(screen.getByRole("button", { name: /^Interstate/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(document.querySelectorAll(".mi-decision-story")).toHaveLength(1);
  expect(document.querySelectorAll(".mi-detail-heading")).toHaveLength(0);
  expect(
    document.querySelectorAll(".mi-inline-competitors > article"),
  ).toHaveLength(3);
  expect(
    within(screen.getByLabelText("Crop")).queryByRole("option", {
      name: "Brinjal",
    }),
  ).not.toBeInTheDocument();
});

it("switches the complete journey while preserving shared inputs", async () => {
  show();
  await screen.findByText(/Top recommendation/);
  await userEvent.selectOptions(screen.getByLabelText("Crop"), "Onion");
  await userEvent.selectOptions(
    screen.getAllByLabelText("Purchase region")[0],
    "HR",
  );
  await userEvent.clear(screen.getAllByLabelText("Quantity (quintals)")[0]);
  await userEvent.type(
    screen.getAllByLabelText("Quantity (quintals)")[0],
    "250",
  );
  await userEvent.click(screen.getByRole("button", { name: /^Intrastate/ }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /^Intrastate/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    ),
  );
  expect(screen.getByLabelText("Crop")).toHaveValue("Onion");
  expect(screen.getAllByLabelText("Purchase region")[0]).toHaveValue("HR");
  expect(screen.getAllByLabelText("Quantity (quintals)")[0]).toHaveValue(250);
  expect(screen.queryByText("Comparison assumptions")).not.toBeInTheDocument();
  expect(
    screen.getByRole("heading", {
      name: "Buy Onion in Buy inside · sell in Sell inside",
    }),
  ).toBeVisible();
  expect(
    vi
      .mocked(fetch)
      .mock.calls.some(
        ([url]) =>
          String(url).includes("mode=intrastate") &&
          String(url).includes("quantity=250"),
      ),
  ).toBe(true);
});

it("preserves Wheat when interstate is unavailable and offers an explicit alternative", async () => {
  show("/?crop=Wheat");
  await screen.findByText(/Top recommendation/);
  await userEvent.click(screen.getByRole("button", { name: /^Interstate/ }));
  expect(
    await screen.findByRole("region", { name: "Unavailable trading mode" }),
  ).toBeVisible();
  expect(screen.getByLabelText("Crop")).toHaveValue("Wheat");
  expect(screen.getByText(/Your crop is preserved/)).toBeVisible();
  expect(document.querySelector(".mi-decision-story")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Try Onion" }));
  expect(await screen.findByText(/Top recommendation/)).toBeVisible();
  expect(screen.getByLabelText("Crop")).toHaveValue("Onion");
});

it("updates purchase regions with crop and mode and preserves an unavailable selection", async () => {
  show("/?mode=interstate");
  await screen.findByText(/Top recommendation/);
  const region = screen.getByLabelText("Purchase region");
  await userEvent.selectOptions(screen.getByLabelText("Crop"), "Potato");
  expect(await within(region).findByRole("option", { name: "Gujarat" })).toBeVisible();
  expect(within(region).queryByRole("option", { name: "Haryana" })).toBeNull();
  await userEvent.selectOptions(region, "GJ");
  await userEvent.click(screen.getByRole("button", { name: /^Intrastate/ }));
  expect(await screen.findByRole("region", { name: "Unavailable trading mode" })).toBeVisible();
  expect(region).toHaveValue("GJ");
  expect(within(region).queryByRole("option", { name: "Madhya Pradesh" })).toBeNull();
  expect(screen.queryByText(/Top recommendation/)).toBeNull();
});

it("links to the exact competitor without relabeling the recommendation", async () => {
  show();
  await screen.findByText(/Top recommendation/);
  const link = screen.getByRole("link", { name: "Inspect competitor 1" });
  expect(link.getAttribute("href")).toMatch(/^\/strategies\/plan\/.+\?crop=/);
  expect(link.getAttribute("href")).toContain("quantity=100");
  expect(link.getAttribute("href")).toContain("mode=interstate");
  expect(screen.queryByRole("link", { name: "Plan purchase date" })).toBeNull();
  expect(document.querySelector('input[type="date"]')).toBeNull();
  expect(document.querySelectorAll(".mi-decision-story")).toHaveLength(1);
});

it("opens the recommended storage journey and updates timing, finances and route together", async () => {
  storageWins = true;
  show();
  const timing = await screen.findByRole("region", { name: "When to sell" });
  const storage = within(timing).getByRole("heading", { name: "Store 7 days" }).closest("article")!;
  expect(storage).toHaveTextContent("Recommended timing");
  expect(storage).toHaveTextContent("₹1,400");
  const journey = screen.getByRole("region", { name: "Journey plan" });
  expect(journey).toHaveTextContent("Estimated arrival for sale 20 Nov");
  expect(screen.getByTestId("map")).toHaveAttribute("data-stop", "1");
  expect(screen.getByTestId("map")).toHaveAttribute("data-truck", "true");
  expect(document.querySelector(".mi-financial")).toHaveTextContent("₹91,300");
  await userEvent.click(within(timing).getByRole("button", { name: "Plan this sale" }));
  expect(journey).toHaveTextContent("Estimated arrival for sale 13 Nov");
  expect(document.querySelector(".mi-financial")).toHaveTextContent("₹24,700");
  expect(screen.getByTestId("map")).not.toHaveAttribute("data-stop");
  expect(storage).toHaveTextContent("Recommended timing");
});

it("does not silently discard a selected crop after its support changes", async () => {
  show("/?crop=Onion");
  await screen.findByText(/Top recommendation/);
  stale = true;
  batch = "second";
  await userEvent.click(screen.getByRole("button", { name: /^Interstate/ }));
  expect(
    await screen.findByRole("region", { name: "Unavailable trading mode" }),
  ).toBeVisible();
  expect(screen.getByLabelText("Crop")).toHaveValue("Onion");
});
