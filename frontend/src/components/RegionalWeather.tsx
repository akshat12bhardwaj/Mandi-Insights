import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { request } from "../lib/intelligence";
import { weatherCondition } from "./PlaceWeather";

export interface WeatherPin { name: string; lat: number; lng: number; weather_code: number; temperature_c: number | null }

export function useRegionalWeather() {
  const query = useQuery({
    queryKey: ["regional-weather"],
    queryFn: () => request<{ rows: WeatherPin[] }>("regional-weather"),
    staleTime: 30 * 60 * 1000,
    retry: false,
  });
  return useMemo(() => (query.data?.rows || []).map(row => {
    const { label } = weatherCondition(row.weather_code);
    const glyphs: Record<string, string> = { Clear: "☀", "Partly cloudy": "⛅", Cloudy: "☁", Fog: "≋", Thunderstorms: "⛈", Snow: "❄", Rain: "🌧" };
    return { ...row, label: row.name + " · " + label + (row.temperature_c == null ? "" : " · " + row.temperature_c + "°C"),
      icon: glyphs[label] || "◌" };
  }), [query.data]);
}
