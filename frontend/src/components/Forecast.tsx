import { CloudRain } from "lucide-react";
import { useForecast, useRouteWeather, type Forecast } from "../lib/api";
import { Chip, ErrorState, Loading } from "./ui";

const day = (iso: string) => new Date(Date.parse(iso)).toLocaleDateString("en-IN", { weekday: "short", timeZone: "UTC" });
const time = (iso: string) => new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/** Seven days of forecast rain (mm, chance) and maximum temperature; a missing value shows as a dash, never zero. */
export function ForecastStrip({ f, heavyMm = 64.5 }: { f: Forecast; heavyMm?: number }) {
  if (!f.available) return <p className="text-[12px] text-muted">Forecast unavailable right now. {f.reason ? `(${f.reason})` : ""}</p>;
  return (
    <div>
      <ol className="grid grid-cols-7 gap-1 text-center text-[11px]" aria-label="Seven-day forecast">
        {f.days.map((d) => {
          const heavy = d.rain_mm !== null && d.rain_mm >= heavyMm;
          return (
            <li key={d.date} className={heavy ? "rounded-lg bg-warn-soft py-1" : "rounded-lg bg-white/70 py-1"}
              aria-label={`${day(d.date)}: rain ${d.rain_mm ?? "unknown"} mm, chance ${d.rain_probability_pct ?? "unknown"}%, max ${d.tmax_c ?? "unknown"} °C`}>
              <div className="text-faint">{day(d.date)}</div>
              <div className="mt-0.5 tabular-nums text-ink">{d.rain_mm === null ? "–" : `${d.rain_mm.toFixed(d.rain_mm < 10 ? 1 : 0)}`}</div>
              <div className="tabular-nums text-faint">{d.rain_probability_pct === null ? "–" : `${d.rain_probability_pct}%`}</div>
              <div className="tabular-nums text-muted">{d.tmax_c === null ? "–" : `${Math.round(d.tmax_c)}°`}</div>
            </li>
          );
        })}
      </ol>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-faint">
        <span>Rain mm · chance · max °C</span>
        {f.retrieved_utc && <span>Updated {time(f.retrieved_utc)}</span>}
        {f.stale && <Chip tone="warn">Not updated recently</Chip>}
        {/* CC BY 4.0: Open-Meteo requires a link wherever its data is displayed */}
        <span><a href={f.attribution.link} target="_blank" rel="noopener noreferrer" className="underline hover:text-ink">{f.attribution.text}</a> ({f.attribution.licence})</span>
      </div>
    </div>
  );
}

/** Forecast at a verified district point (approximate for the district). */
export function PointForecast({ id }: { id: number }) {
  const f = useForecast(id);
  return (
    <div className="rounded-xl bg-subtle p-2.5" data-testid="point-forecast">
      <div className="mb-1.5 flex justify-between text-[12px] text-muted"><span>Next 7 days</span><span>approximate for the district</span></div>
      {f.isLoading ? <Loading className="py-2" /> : f.error ? <ErrorState error={f.error} /> : f.data && <ForecastStrip f={f.data} />}
    </div>
  );
}

/** Weather at a route's two end points. It never speaks for the road in between, and is not an official warning. */
export function RouteWeather({ origin, dest }: { origin: string; dest: string }) {
  const w = useRouteWeather(origin, dest);
  return (
    <div className="rounded-xl border border-line bg-white/80 p-3" data-testid="route-weather">
      <p className="flex items-center gap-1.5 text-[13px] font-medium text-ink"><CloudRain size={14} /> Weather at the start and end</p>
      {w.isLoading ? <Loading className="py-2" /> : w.error ? <ErrorState error={w.error} /> : w.data && (
        <div className="mt-2 space-y-2.5">
          {w.data.message
            ? <p role="status" className="rounded-lg bg-warn-soft px-2.5 py-1.5 text-[12px] text-ink">{w.data.message}</p>
            : (w.data.origin.available || w.data.dest.available) && <p className="text-[12px] text-muted">No heavy rain is forecast at either end in the next 7 days.</p>}
          {[w.data.origin, w.data.dest].map((e, i) => (
            <div key={e.node_id}>
              <p className="mb-1 text-[12px] text-muted">{i === 0 ? "Start" : "End"}: {e.name}</p>
              <ForecastStrip f={e} heavyMm={w.data.heavy_rain_threshold_mm} />
            </div>
          ))}
          <p className="text-[11px] leading-snug text-faint">Covers the two district points only, not the road between them. A forecast, not an official warning; it does not show whether a road is open.</p>
        </div>
      )}
    </div>
  );
}
