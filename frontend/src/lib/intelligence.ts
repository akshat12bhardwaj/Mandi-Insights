import { useQuery } from "@tanstack/react-query";

export interface CropInfo {
  crop: string;
  category: string;
  daily_eligible_series: number;
  usable_records: number;
  markets: number;
}
export interface Coordinate {
  lat: number;
  lng: number;
  node: string;
  precision: string;
}
export interface Market {
  series_id: string;
  crop: string;
  state: string;
  district: string;
  market: string;
  variety: string;
  grade: string;
  source: string;
  predicted_price: number | null;
  last_observed_price: number;
  observation_date?: string;
  last_observation_date?: string;
  coordinate: Coordinate | null;
  status: string;
}
export interface Facility {
  warehouse_id: string;
  name: string;
  latitude: number;
  longitude: number;
  region: string;
  district_reference: string;
  storage_class: string;
  total_t: number;
  occupied_t: number;
  free_t: number;
  occupancy_pct: number;
  capacity_basis: string;
  rs_q_day: number;
  max_days: number;
  status: string;
  supported_crops: string[];
}
export interface TradeRoute {
  storage_arrival_hours?: number;
  stop_index?: number;
  base_hours?: number;
  base_freight?: number;
  toll_cost?: number | null;
  delay_cost?: number;
  traffic_hours?: number;
  loading_hours?: number;
  geometry?: [number, number][];
  objective: string;
  km: number;
  hours: number;
  basis: string;
  origin: string;
  destination: string;
  transport_cost: number;
}
export interface Strategy {
  schedule?: {
    procurement_at: string; depart_at: string; storage_start_at: string | null;
    storage_end_at: string | null; arrival_at: string; sale_at: string;
    elapsed_hours: number; travel_hours: number; loading_hours: number;
  };
  sale_quote?: { kind: string; target_date: string; price: number };
  timing_options?: Strategy[];
  timing_unavailable?: { days: number; reason: string }[];
  route_plans?: Strategy[];
  storage_handling?: number;
  trading_mode?: "intrastate" | "interstate";
  buy_state_id?: string;
  sell_state_id?: string;
  payload_q?: number;
  truck_utilization?: number;
  forecast_reserve?: number;
  logistics_reserve?: number;
  data_quality?: {
    label: string;
    maximum_observation_age_days: number | null;
    route_evidence: string;
    recent_price_movement_rs: number | null;
  };
  decision?: {
    context_notes?: string[];
    next_alternative?: string;
    scope?: string;
    headline: string;
    cards: { title: string; value: string; text: string }[];
    alternatives: {
      id: string;
      crop: string;
      buy_market: string;
      sell_market: string;
      margin: number;
      transport: number;
      procurement: number;
      sale_revenue: number;
      score: number;
      distance_km: number;
      procurement_saving: number;
      transport_saving: number;
      revenue_advantage: number;
      margin_difference: number;
      score_difference: number;
      insight: string;
    }[];
    trade_off: string;
    why_selected: string;
    practical_tie: boolean;
    break_even_sale_price: number;
    what_changes: string;
    storage: string;
  };
  future_forecast?: {
    model: string;
    horizon_days: number;
    target_date: string;
    price: number;
    historical_mae: number;
    validation_scope: string;
  };
  sale_kind?: string;
  id: string;
  crop: string;
  buy: Market;
  sell: Market;
  quantity_q: number;
  trips: number;
  vehicle: string;
  route: TradeRoute;
  routes: TradeRoute[];
  storage_days: number;
  storage_detour_km?: number;
  warehouse: Facility | null;
  procurement: number;
  transport: number;
  handling: number;
  storage: number;
  total_cost: number;
  sale_revenue: number;
  margin: number;
  uncertainty_screen: number | null;
  risk_adjusted_margin: number;
  sale_price: number;
  sale_basis: string;
  direct_comparison?: {
    total_cost: number;
    sale_revenue: number;
    margin: number;
    transport: number;
    sale_basis: string;
  };
  loss_pct: number;
  handling_loss_pct?: number;
  explanation: string;
}
export interface Overview {
  dataset_version?: string;
  batch_id?: string;
  refresh?: {
    source_waiting?: boolean;
    last_success: string | null;
    latest_observation: string | null;
    status: string;
  };
  catalog: { crops: CropInfo[] };
  date: string;
  states: string[];
  freshness: {
    batch_current: boolean;
    eligible_predictions: number;
    latest_observation_by_crop: Record<string, string>;
  };
  config: {
    vehicles: Record<
      string,
      { capacity_q: number; rs_km: number; km_litre: number }
    >;
    quantity_q: number;
    handling_rs_q: number;
    handling_loss_pct: number;
  };
}
export interface MarketResult {
  batch_id?: string;
  rows: Market[];
  total: number;
  states: string[];
  districts: string[];
  mapped_count: number;
  unmapped_count: number;
  map_points: {
    id: number;
    lat: number;
    lng: number;
    label: string;
    series_id: string;
    tone: "ok" | "muted" | "ink";
  }[];
}
export interface StrategyResult {
  active_mode?: "intrastate" | "interstate";
  default_mode?: "intrastate" | "interstate";
  competitors?: Strategy[];
  empty_explanation?: string | null;
  fallback_crops?: string[];
  selected_comparison?: {
    insight: string;
    crop: string;
    id: string;
    score_difference: number;
    margin_difference: number;
  } | null;
  forecast_count?: number;
  batch_current?: boolean;
  dataset_version?: string;
  batch_id?: string;
  forecast_ready_crops?: string[];
  strategy_ready_crops?: string[];
  filters?: { crops: string[]; states: { id: string; name: string }[] };
  effective_filters?: {
    crop: string;
    state: string;
    buy_id: string;
    sell_id: string;
    mode: string;
  };
  notices?: string[];
  groups?: Record<
    "intrastate" | "interstate",
    {
      rows: Strategy[];
      best: Strategy | null;
      candidate_count: number;
      empty_reason: string | null;
    }
  >;
  rows: Strategy[];
  candidate_count: number;
  date: string;
  ranking: string;
  empty_reason: string | null;
}
export interface ScenarioInput {
  toll_rs_trip?: number;
  congestion_pct?: number;
  loading_minutes?: number;
  delay_rs_hour?: number;
  batch_id?: string;
  future_mode?: "forecast" | "scenario";
  rs_km?: number;
  capacity_q?: number;
  buy_id: string;
  sell_id: string;
  quantity: number;
  vehicle: string;
  handling: number;
  loss: number;
  days: number;
  warehouse_id: string | null;
  route_index: number;
  future_change: number;
}

export async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(
    "/api/v4/" + path,
    body === undefined
      ? undefined
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(
      typeof error?.detail === "string"
        ? error.detail
        : "Data could not be loaded. Try again.",
    );
  }
  return response.json();
}
export function useIntelligence<T>(path: string, enabled = true) {
  return useQuery<T>({
    queryKey: ["intelligence", path],
    queryFn: () => request<T>(path),
    staleTime: 60000,
    refetchInterval: 60000,
    retry: 1,
    enabled,
  });
}
export function params(
  values: Record<string, string | number | boolean | undefined>,
) {
  const p = new URLSearchParams();
  Object.entries(values).forEach(([k, v]) => {
    if (v !== undefined && v !== "") p.set(k, String(v));
  });
  return p.toString();
}
export const rupees = (n: number | null | undefined, digits = 0) =>
  n == null
    ? "Unavailable"
    : new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      }).format(n);
export const number = (n: number) =>
  new Intl.NumberFormat("en-IN", { maximumFractionDigits: 1 }).format(n);
