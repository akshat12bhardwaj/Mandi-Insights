import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { compact, int, longDate } from "../lib/format";

// Recessive axes and grid; text in ink tokens, colour only on marks.
const axis = { tick: { fontSize: 11, fill: "#5b6761" }, axisLine: false, tickLine: false } as const;
const tipStyle = { contentStyle: { borderRadius: 12, border: "1px solid #e3e0d6", boxShadow: "0 4px 16px rgb(28 42 35/.08)", fontSize: 12, padding: "6px 10px" }, labelStyle: { color: "#5b6761", marginBottom: 2 } };
export const SERIES = { actual: "#1c2a23", reference: "#8f968f", accent: "#2f7a57" };

export interface Line_ { key: string; name: string; color: string; dashed?: boolean; width?: number }

// Loose row type: rows come straight from the API.
type Row = Record<string, any>;
type H = number | `${number}%`;

export function ThinBars({ data, x, y, name, height = "100%", fmt = compact, highlight }: {
  data: Row[]; x: string; y: string; name: string; height?: H; fmt?: (v: number) => string; highlight?: (d: Row) => boolean;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barCategoryGap={1}>
        <CartesianGrid vertical={false} stroke="#ebe8df" />
        <XAxis dataKey={x} {...axis} minTickGap={36} />
        <YAxis {...axis} tickFormatter={(v) => compact(v, 0)} width={38} />
        <Tooltip {...tipStyle} cursor={{ fill: "rgb(31 92 67 / .08)" }} formatter={(v) => [fmt(Number(v)), name]} />
        <Bar dataKey={y} name={name} maxBarSize={3} fill={SERIES.accent} isAnimationActive={false}
          {...(highlight && { shape: (p: Row) => <rect x={p.x} y={p.y} width={p.width} height={p.height} rx={1} fill={highlight(p.payload) ? SERIES.accent : "#c9ccc2"} /> })} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function Lines({ data, x, lines, height = "100%", fmt = compact, xFmt }: {
  data: Row[]; x: string; lines: Line_[]; height?: H; fmt?: (v: number) => string; xFmt?: (v: string) => string;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid vertical={false} stroke="#ebe8df" />
        <XAxis dataKey={x} {...axis} minTickGap={40} tickFormatter={xFmt} />
        <YAxis {...axis} tickFormatter={(v) => compact(v, 1)} width={40} domain={["auto", "auto"]} />
        <Tooltip {...tipStyle} labelFormatter={(l) => (xFmt ? xFmt(String(l)) : String(l))} formatter={(v, n) => [v === null || v === undefined ? "–" : fmt(Number(v)), n]} />
        {lines.map((l) => (
          <Line key={l.key} type="monotone" dataKey={l.key} name={l.name} stroke={l.color} strokeWidth={l.width ?? 2} dot={false}
            strokeDasharray={l.dashed ? "4 3" : undefined} connectNulls isAnimationActive={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "#fff" }} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function Legend({ items }: { items: { name: string; color: string; dashed?: boolean }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted" aria-label="Legend">
      {items.map((i) => (
        <li key={i.name + i.color} className="flex items-center gap-1.5">
          <svg width="14" height="4" aria-hidden><line x1="0" y1="2" x2="14" y2="2" stroke={i.color} strokeWidth="2" strokeDasharray={i.dashed ? "3 2" : undefined} /></svg>
          {i.name}
        </li>
      ))}
    </ul>
  );
}

const monthTick = (iso: string, long: boolean) =>
  new Date(Date.parse(iso)).toLocaleDateString("en-IN", long ? { month: "short", year: "2-digit", timeZone: "UTC" } : { day: "numeric", month: "short", timeZone: "UTC" });

/** Observed weekly prices: gaps stay as breaks (no interpolation), a dashed line marks the calculated period average. */
export function PriceHistory({ data, average, breaks = [] }: { data: { date: string; price: number | null }[]; average?: number; breaks?: { date: string; label: string }[] }) {
  const long = data.length > 20;
  const sparse = data.filter((d) => d.price !== null).length <= 26;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
        <CartesianGrid vertical={false} stroke="#ebe8df" />
        <XAxis dataKey="date" {...axis} minTickGap={48} tickFormatter={(v) => monthTick(v, long)} />
        <YAxis {...axis} width={60} domain={["auto", "auto"]} tickFormatter={(v) => `₹${int(v)}`} />
        <Tooltip cursor={{ stroke: "#c9ccc2" }} content={({ active, payload, label }) => {
          if (!active || !label) return null;
          const v = payload?.[0]?.value as number | null | undefined;
          return (
            <div className="rounded-xl border border-line bg-white px-3 py-2 text-[12px] shadow-soft">
              <div className="text-muted">Week of {longDate(String(label))}</div>
              <div className="mt-0.5 font-semibold text-ink tabular-nums">{v === null || v === undefined ? "No report this week" : `₹${int(v)} per quintal`}</div>
            </div>
          );
        }} />
        {average !== undefined && <ReferenceLine y={average} stroke={SERIES.reference} strokeDasharray="4 4" ifOverflow="extendDomain" />}
        {breaks.map((b) => <ReferenceLine key={b.date} x={b.date} stroke={SERIES.reference} strokeDasharray="2 3" label={{ value: b.label, position: "insideTopLeft", fontSize: 10, fill: "#5b6761" }} />)}
        <Line type="linear" dataKey="price" name="Typical price" stroke={SERIES.accent} strokeWidth={2.25} connectNulls={false} isAnimationActive={false}
          dot={sparse ? { r: 2.5, fill: SERIES.accent, strokeWidth: 0 } : false} activeDot={{ r: 5, strokeWidth: 2, stroke: "#fff" }} />
      </LineChart>
    </ResponsiveContainer>
  );
}
