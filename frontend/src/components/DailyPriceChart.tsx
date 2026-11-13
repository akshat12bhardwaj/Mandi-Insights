import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DailyHistory, DailyPrediction } from "../lib/daily";

export default function DailyPriceChart({ history, prediction, compact = false }: { history: DailyHistory; prediction: DailyPrediction; compact?: boolean }) {
  const points = history.points;
  const map = new Map(points.map(p => [p.date, p.price]));
  const last = points.at(-1)?.date;
  if (!last) return <p>No observed prices for this series.</p>;
  const start = new Date(`${last}T00:00:00Z`);
  start.setUTCDate(start.getUTCDate() - 89);
  const end = prediction.predicted_modal_price === null ? last : prediction.target_date;
  const rows: { date: string; observed: number | null; predicted: number | null }[] = [];
  for (let d = start; d.toISOString().slice(0, 10) <= end; d.setUTCDate(d.getUTCDate() + 1)) {
    const date = d.toISOString().slice(0, 10);
    rows.push({ date, observed: map.get(date) ?? null, predicted: date === prediction.target_date ? prediction.predicted_modal_price : null });
  }
  return <div className={compact ? "h-44" : "h-64"} aria-label="Observed prices and today's prediction in rupees per quintal">
    <ResponsiveContainer width="100%" height="100%"><LineChart data={rows} margin={{ top: 12, right: 16, left: 8, bottom: 8 }}>
      <CartesianGrid vertical={false} stroke="#ebe8df" />
      <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
      <YAxis tick={{ fontSize: 11 }} width={65} domain={[0, "auto"]} />
      <Tooltip formatter={(value, name) => [`₹${Number(value).toLocaleString("en-IN")}/quintal`, name]} />
      <Line name="Observed price" type="linear" dataKey="observed" stroke="#2f7a57" dot={false} connectNulls={false} isAnimationActive={false} />
      <Line name="Prediction" dataKey="predicted" stroke="#a05c21" dot={{ r: 6 }} connectNulls={false} isAnimationActive={false} />
    </LineChart></ResponsiveContainer>
  </div>;
}
