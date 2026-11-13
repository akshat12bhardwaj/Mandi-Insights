import type { Coordinate, Facility, Market } from './intelligence';

export interface Environment {
  batch_id?: string;
  available: boolean;
  current: { time: string; weather_code?: number; interval_seconds?: number; temperature_c: number | null; humidity_pct: number | null; precipitation_mm: number | null; wind_kmh: number | null } | null;
  outlook: { date: string; weather_code?: number; tmin_c: number | null; tmax_c: number | null; rain_mm: number | null; rain_probability_pct: number | null }[];
  weather_stale?: boolean;
  weather_retrieved_at?: string;
  weather_basis?: string;
  reason?: string;
  terrain: { available: boolean; elevation_m?: number; sample_relief_m?: number; band?: string; setting?: string; logistics_note?: string; source?: string; source_url?: string; basis?: string; stale?: boolean; retrieved_at?: string };
  cautions: string[];
  decision_policy?: string;
  attribution?: string;
}
export interface MarketTrade {
  id: string; buy_id: string; sell_id: string; buy_market: string; sell_market: string;
  net_margin: number; adjusted_value: number; freight: number; quantity_q: number;
  distance_km: number; hours: number; route_basis: string; objective: string;
}
export interface MarketOpportunity extends MarketTrade {
  crop: string; variety: string; grade: string; source: string;
  handling: number; comparison: string | null;
  alternative: MarketTrade | null;
}
export type ReportedSeries = Omit<Market, 'coordinate'> & { forecast_ready: boolean };
export interface MarketInventory {
  rows: (ReportedSeries & { recent_movement_rs: number | null })[];
  total: number;
  total_series: number;
  crop_count: number;
  forecast_series: number;
  batch_id: string;
}
export interface MarketDetail {
  market: Market;
  location: Coordinate | null;
  price: { kind: 'forecast' | 'observed'; current_estimate: number | null; latest_observed: { date: string; price: number } | null; forecast_input_date: string | null; history: { date: string; price: number }[]; trend_pct: number | null; trend_reports: number; unit: string };
  activity: Pick<MarketInventory, 'total_series' | 'forecast_series' | 'crop_count'>;
  warehouses: { rows: (Facility & { distance_km: number; hours: number; distance_kind: string; distance_basis: string; compatible: boolean; enough_capacity: boolean; seven_day_charge: number | null; usefulness: string })[]; compatible_count: number; known_facilities_in_radius?: number; radius_km: number; radius_basis?: string; reason?: string };
  access: { mapped: boolean; precision: string; snap_gap_km: number | null; network_status: string | null; connections: MarketTrade[]; note: string };
  decision: { role: 'buy' | 'sell' | 'observe'; headline: string; explanation: string; peer_count: number; peer_basis: string; peer_median?: number | null; difference_from_peer_median?: number | null; pair_count: number; best_buy: MarketTrade | null; best_sell: MarketTrade | null; storage_note: string; ranking_policy?: string };
  environment: Environment;
  quantity_q: number;
  batch_id: string;
}
