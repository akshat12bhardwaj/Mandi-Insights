import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { MarketsExplorer } from "../pages/MarketIntelligence";
import type { MapPoint } from "../components/MapView";

vi.mock("../components/MapView", () => ({
  MapView: ({ points, onSelect, onGroupSelect }: { points: MapPoint[]; onSelect: (id: number) => void; onGroupSelect: (ids: number[]) => void }) =>
    <div aria-label="Map pins">{points.map(p => <button key={p.id} data-tone={p.tone} data-kind={p.kind} onClick={() => onSelect(p.id)}>{p.label}</button>)}
      <button onClick={() => onGroupSelect([1, 2])}>Open cluster</button></div>,
}));

const points = [
  { id: 1, series_id: "one", crop: "Wheat", label: "Ganaur APMC", lat: 29, lng: 77, price: 2000 },
  { id: 2, series_id: "two", crop: "Wheat", label: "Sonipat APMC", lat: 29, lng: 77, price: 3000 },
];
let inventoryMissing: boolean;
beforeEach(() => {
  inventoryMissing = false;
  vi.stubGlobal("fetch", vi.fn(async (input: string) => {
    const url = new URL(input, "http://localhost");
    let payload: unknown = {};
    if (url.pathname.endsWith("/overview")) payload = { catalog: { crops: [{ crop: "Wheat" }] }, date: "2026-11-13", freshness: {}, config: {} };
    if (url.pathname.endsWith("/market-map")) {
      const search = url.searchParams.get("search")?.toLowerCase();
      payload = { points: points.filter(p => !search || p.label.toLowerCase().includes(search)),
        bounds: url.searchParams.get("crop") ? url.searchParams.get("basis") === "forecast" ? [2300, 3300] : [2000, 3000] : null,
        state_options: [{ id: "HR", name: "Haryana" }], selected_state_id: url.searchParams.get("state") || "",
        unmapped_count: 1, unmapped: [{ series_id: "remote", crop: "Wheat", label: "Remote Mandi", price: null }] };
    }
    if (url.pathname.endsWith("/market-place")) {
      const id = url.searchParams.get("series_id");
      payload = { batch_id: "a", market: { market: points.find(p => p.series_id === id)?.label || "Remote Mandi",
        state: "Haryana", district: "Sonipat", coordinate: id === "remote" ? null : { lat: 29, lng: 77, precision: "District reference" } },
        warehouses: { rows: [], radius_km: 100 }, connections: [] };
    }
    if (url.pathname.endsWith("/market-environment")) payload = { batch_id: "a", available: true, current: null, outlook: [], terrain: { available: false }, cautions: [] };
    if (url.pathname.endsWith("/market-crops")) {
      if (inventoryMissing) return new Response("{}", { status: 404 });
      payload = { batch_id: "a", total_series: 1, rows: [{ series_id: "one", crop: "Wheat", variety: "Other", grade: "FAQ", source: "datagov", last_observed_price: 2000, observation_date: "2026-11-10" }] };
    }
    return new Response(JSON.stringify(payload));
  }));
});
function show(path = "/markets") {
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={[path]}><MarketsExplorer /></MemoryRouter></QueryClientProvider>);
}

it("selects a clustered market without a directory or price-history chart", async () => {
  show();
  await userEvent.click(await screen.findByRole("button", { name: "Open cluster" }));
  await userEvent.click(within(screen.getByText("Markets at this map location").parentElement!).getByRole("button", { name: "Ganaur APMC" }));
  expect(await screen.findByRole("heading", { name: "Ganaur APMC" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Market directory" })).not.toBeInTheDocument();
  expect(screen.queryByText("Reported price history")).not.toBeInTheDocument();
});

it("updates above/below marker highlighting and uses separate data-derived bounds", async () => {
  show();
  await screen.findByRole("button", { name: "Ganaur APMC" });
  expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("Crop", { exact: true }), "Wheat");
  const slider = await screen.findByRole("slider");
  expect(slider).toHaveAttribute("min", "2000");
  fireEvent.change(slider, { target: { value: "2500" } });
  expect(screen.getByRole("button", { name: "Ganaur APMC" })).toHaveAttribute("data-tone", "muted");
  expect(screen.getByRole("button", { name: "Sonipat APMC" })).toHaveAttribute("data-tone", "ok");
  await userEvent.click(screen.getByRole("button", { name: "Below" }));
  fireEvent.change(screen.getByRole("slider"), { target: { value: "2500" } });
  expect(screen.getByRole("button", { name: "Sonipat APMC" })).toHaveAttribute("data-tone", "muted");
  await userEvent.selectOptions(screen.getByLabelText("Price basis"), "forecast");
  expect(await screen.findByRole("slider")).toHaveAttribute("max", "3300");
});

it("searches map pins and opens an unmapped market without inventing geography", async () => {
  show();
  await userEvent.click(await screen.findByRole("button", { name: "Ganaur APMC" }));
  expect(await screen.findByRole("heading", { name: "Ganaur APMC" })).toBeVisible();
  const search = screen.getByRole("searchbox");
  await userEvent.type(search, "Sonipat");
  await screen.findByRole("button", { name: "Sonipat APMC" });
  expect(screen.queryByRole("button", { name: "Ganaur APMC" })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Ganaur APMC" })).not.toBeInTheDocument();
  await userEvent.clear(search);
  await userEvent.click(await screen.findByRole("button", { name: "Ganaur APMC" }));
  expect(await screen.findByRole("heading", { name: "Ganaur APMC" })).toBeVisible();
  await userEvent.selectOptions(screen.getByLabelText("State", { exact: true }), "HR");
  expect(screen.queryByRole("heading", { name: "Ganaur APMC" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByText(/markets without a map reference/));
  await userEvent.click(screen.getByRole("button", { name: "Remote Mandi" }));
  expect(await screen.findByText("Location reference unavailable")).toBeInTheDocument();
});

it("preserves an incoming exact market and gives missing crop reports a useful fallback", async () => {
  inventoryMissing = true;
  show("/markets?crop=Wheat&series=one");
  expect(await screen.findByRole("heading", { name: "Ganaur APMC" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Reported crops" }));
  expect(await screen.findByText("Crop reports are unavailable for this market.", {}, { timeout: 3000 })).toBeInTheDocument();
});
