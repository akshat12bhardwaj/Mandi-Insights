import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { WarehousesExplorer } from "../pages/Intelligence";
import { Strategies } from "../pages/Strategies";
import { params, request } from "../lib/intelligence";

vi.mock("../components/MapView", () => ({
  MapView: () => <div data-testid="map" />,
}));
const crops = [
  "Onion",
  "Potato",
  "Tomato",
  "Green Chilli",
  "Brinjal",
  "Cauliflower",
  "Cabbage",
  "Wheat",
  "Banana",
  "Cucumbar(Kheera)",
  "Paddy(Dhan)(Common)",
  "Pumpkin",
  "Carrot",
  "Bottle gourd",
  "Apple",
  "Ginger(Green)",
  "Rice",
  "Bhindi(Ladies Finger)",
  "Raddish",
  "Bitter gourd",
];
const overview = {
  date: "2026-11-12",
  catalog: {
    crops: crops.map((crop) => ({
      crop,
      category: "Vegetables",
      daily_eligible_series: 50,
    })),
  },
  states: ["Maharashtra"],
  freshness: { batch_current: true, eligible_predictions: 208 },
  config: { vehicles: { "Medium truck": { capacity_q: 100, rs_km: 35 } } },
};
beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      const url = new URL(input, "http://localhost");
      const body = url.pathname.endsWith("/overview")
        ? overview
        : url.pathname.endsWith("/warehouses")
          ? { rows: [], states: [] }
          : {
              rows: [],
              candidate_count: 0,
              empty_reason: "No compatible current forecasts.",
            };
      return new Response(JSON.stringify(body));
    }),
  );
});
function show(page: React.ReactNode, path = "/") {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[path]}>{page}</MemoryRouter>
    </QueryClientProvider>,
  );
}

it("keeps historical-only crops out of active strategy filters", async () => {
  show(<Strategies />);
  expect(
    await screen.findByText("No compatible current forecasts."),
  ).toBeInTheDocument();
  const crop = screen.getByRole("combobox", { name: "Crop" });
  await waitFor(() =>
    expect(within(crop).getAllByRole("option")).toHaveLength(1),
  );
  expect(within(crop).queryByRole('option',{name:'Brinjal'})).not.toBeInTheDocument();
});

it("carries buying and selling market selections into the API request", async () => {
  show(<Strategies />, "/?crop=Onion&buy=one&sell=two");
  expect(
    await screen.findByText("No compatible current forecasts."),
  ).toBeInTheDocument();
  expect(
    vi
      .mocked(fetch)
      .mock.calls.some(
        ([url]) =>
          String(url).includes("buy_id=one") &&
          String(url).includes("sell_id=two"),
      ),
  ).toBe(true);
});

it("filters warehouses by capacity and handles an empty catalog", async () => {
  show(<WarehousesExplorer />);
  expect(
    await screen.findByText(/No facilities match these filters/),
  ).toBeInTheDocument();
  const input = screen.getByRole("spinbutton", {
    name: "Minimum free capacity (tonnes)",
  });
  await userEvent.clear(input);
  await userEvent.type(input, "500");
  await waitFor(() =>
    expect(
      vi
        .mocked(fetch)
        .mock.calls.some(([url]) => String(url).includes("min_free_t=500")),
    ).toBe(true),
  );
});

it("surfaces structured server errors without exposing response internals", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            detail: "Choose compatible storage with enough space",
          }),
          { status: 422 },
        ),
    ),
  );
  await expect(request("scenario", {})).rejects.toThrow(
    "Choose compatible storage with enough space",
  );
});

it("encodes filters and omits absent selections", () => {
  expect(
    params({
      crop: "Green Chilli",
      state: "",
      quantity: 100,
      recent: true,
      other: undefined,
    }),
  ).toBe("crop=Green+Chilli&quantity=100&recent=true");
});
