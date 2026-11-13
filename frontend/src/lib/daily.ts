import { useQuery } from "@tanstack/react-query";

export interface DailyCrop {
  crop: string; category: string; raw_records: number; usable_records: number;
  first_date: string; last_date: string; daily_eligible_series: number;
}
export interface DailyMarket {
  series_id: string; market: string; variety: string; source: string; grade: string;
  first_date: string; last_date: string; usable_observations: number;
}
export interface DailyPrediction {
  crop: string; category: string; state: string; district: string; market: string; variety: string;
  series_id: string; source: string; grade: string; kind: "prediction"; unit: "INR/quintal";
  target_date: string; forecast_issue_timestamp: string; dataset_version: string; model_version: string;
  model: string; status: string; predicted_modal_price: number | null;
  last_observed_price: number | null; last_observation_date: string | null;
  observed_today: number | null; observed_today_status: string;
  previous_forecast?: {target_date:string;issued_at:string;prediction:number|null;kind:string}|null;
  data_freshness: { age_days: number | null; observations: number; density: number };
  historical_error: { mae: number; rmse: number; smape_pct: number; rows: number; markets: number; period: string; scope: string } | null;
}
export interface DailyHistory { points: { date: string; price: number; available_at: string }[] }

export function useDaily<T>(path: string, params: Record<string, string> = {}, enabled = true) {
  return useQuery<T, Error>({
    queryKey: ["daily-v1", path, params], enabled, staleTime: 60_000, retry: false, refetchInterval:path === "today" ? 60_000 : false,
    queryFn: async () => {
      const response = await fetch(`/api/v3/daily/${path}?${new URLSearchParams(params)}`);
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(typeof body.detail === "string" ? body.detail : "Daily prices are unavailable. Please try again later.");
      }
      return response.json();
    },
  });
}
