import { Cloud, CloudFog, CloudLightning, CloudRain, CloudSnow, CloudSun, Droplets, Mountain, Sun, Thermometer } from "lucide-react";
import { number } from "../lib/intelligence";
import type { Environment } from "../lib/market-intelligence";

export function weatherCondition(code?: number | null) {
  if (code === 0) return { Icon: Sun, label: "Clear" };
  if (code === 1 || code === 2) return { Icon: CloudSun, label: "Partly cloudy" };
  if (code === 3) return { Icon: Cloud, label: "Cloudy" };
  if (code === 45 || code === 48) return { Icon: CloudFog, label: "Fog" };
  if (code != null && code >= 95 && code <= 99) return { Icon: CloudLightning, label: "Thunderstorms" };
  if (code != null && ((code >= 71 && code <= 77) || code === 85 || code === 86)) return { Icon: CloudSnow, label: "Snow" };
  if (code != null && ((code >= 51 && code <= 67) || (code >= 80 && code <= 82))) return { Icon: CloudRain, label: "Rain" };
  return { Icon: Thermometer, label: "Conditions unavailable" };
}

export function Weather({ env, loading, error, retry }: { env?: Environment; loading: boolean; error: boolean; retry: () => void }) {
  const current = env?.current;
  const { Icon, label } = weatherCondition(current?.weather_code);
  const terrain = env?.terrain;
  return <section className="mi-place-weather" aria-label="Weather and terrain">
    <h3>Weather &amp; terrain</h3>
    {current ? <div className="mi-weather-now">
      <Icon size={29} aria-hidden />
      <div><strong>{current.temperature_c == null ? "—" : number(current.temperature_c) + "°C"}</strong><small>{label}{env?.weather_stale ? " · Cached model" : " · Local model"}</small></div>
      <div><small><Droplets size={14} />{current.humidity_pct == null ? "Humidity unavailable" : number(current.humidity_pct) + "% humidity"}</small>
        {current.precipitation_mm != null && <small>{number(current.precipitation_mm)} mm recent rain</small>}</div>
    </div> : <p className="mi-note">{loading ? "Checking local conditions…" : "Current weather unavailable."} {error && <button className="mi-text-link" onClick={retry}>Retry</button>}</p>}
    {!!env?.outlook?.length && <div className="mi-weather-days">
      {env.outlook.map(day => {
        const condition = weatherCondition(day.weather_code);
        return <div key={day.date}><strong>{new Date(day.date + "T12:00:00").toLocaleDateString("en-IN", { weekday: "short" })}</strong>
          <small><condition.Icon size={16} />{condition.label}</small>
          <span>{day.tmin_c ?? "—"}–{day.tmax_c ?? "—"}°C</span>
          {day.rain_probability_pct != null && <small>{day.rain_probability_pct}% rain chance</small>}</div>;
      })}
    </div>}
    {env?.cautions?.filter(note => /rain|wind/i.test(note)).slice(0, 1).map(note => <p key={note} className="mi-note">{note}</p>)}
    <div className="mi-terrain-metric"><Mountain size={20} aria-hidden /><div><strong>{terrain?.elevation_m == null ? loading ? "Checking elevation…" : "Elevation unavailable" : number(terrain.elevation_m) + " m estimated elevation"}</strong>
      {terrain?.setting && terrain.available && <small>{terrain.setting}</small>}</div></div>
  </section>;
}
