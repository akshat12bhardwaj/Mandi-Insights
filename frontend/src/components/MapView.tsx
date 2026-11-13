import L from "leaflet";
import { Maximize2, Minus, Plus } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import { cn } from "../lib/format";
import { IconButton } from "./ui";
import { animateTruck } from "./TruckRoute";

export interface MapPoint {
  id: number;
  lat: number;
  lng: number;
  label: string;
  tone: "ok" | "muted" | "ink";
  kind?: "market" | "warehouse";
  approximate?: boolean;
}

const SYMBOL = {
  market: '<path d="M3 9l2-5h14l2 5M4 12v8h16v-8M9 20v-5h6v5M3 9v2a3 3 0 0 0 6 0 3 3 0 0 0 6 0 3 3 0 0 0 6 0V9Z"/>',
  warehouse: '<path d="M3 20V8l9-5 9 5v12H3Zm4 0V10h10v10M7 14h10m-10 3h10"/>',
};

const TONE = { ok: "#2f7a57", muted: "#a3a89f", ink: "#1c2a23" };
const INDIA: L.LatLngTuple[] = [
  [7, 67],
  [36, 98],
];

/** Space the overlays (left panel, bottom cards) take on wide screens, so fitted points stay visible. */
function overlayPadding(bottomCards = true): L.FitBoundsOptions {
  return window.innerWidth >= 1024
    ? {
        paddingTopLeft: [400, 40],
        paddingBottomRight: [80, bottomCards ? 290 : 40],
      }
    : { padding: [30, 30] };
}

/**
 * Leaflet map of verified district reference points. Draws points only: no lines, routes or invented sites.
 * Imperative Leaflet (not react-leaflet) keeps the dependency list short.
 */
export function MapView({
  points,
  selectedId,
  onSelect,
  onGroupSelect,
  className,
  fitKey,
  bottomCards = true,
  line,
  weather,
  truck = false,
  stopIndex,
  compact = false,
  ariaLabel = "Map of verified district reference points",
}: {
  points: MapPoint[];
  selectedId?: number;
  onSelect?: (id: number) => void;
  onGroupSelect?: (ids: number[]) => void;
  className?: string;
  fitKey?: string;
  bottomCards?: boolean;
  line?: [number, number][] | null; // a computed road route (lat, lon); never a straight connector
  weather?: { lat: number; lng: number; label: string; icon: string }[];
  truck?: boolean;
  stopIndex?: number;
  compact?: boolean;
  ariaLabel?: string;
}) {
  const pad = () =>
    compact
      ? { padding: [28, 28] as L.PointTuple }
      : overlayPadding(bottomCards);
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const select = useRef(onSelect);
  select.current = onSelect;
  const groupSelect = useRef(onGroupSelect);
  groupSelect.current = onGroupSelect;
  const lineKey = useMemo(() => JSON.stringify(line || null), [line]);

  useEffect(() => {
    const m = L.map(el.current!, {
      zoomControl: false,
      zoomAnimation: false,
      fadeAnimation: false,
      markerZoomAnimation: false,
      attributionControl: true,
      minZoom: 4,
      maxZoom: 11,
      zoomSnap: 1,
      maxBounds: [
        [-5, 50],
        [45, 115],
      ],
    });
    // Keyless light-grey basemap (CARTO's public tiles now require an API key).
    L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
      {
        maxZoom: 16,
        attribution:
          "Basemap &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors",
      },
    ).addTo(m);
    m.fitBounds(INDIA, pad());
    layer.current = L.layerGroup().addTo(m);
    map.current = m;
    const ro = new ResizeObserver(() => { if(map.current===m)m.invalidateSize(); });
    ro.observe(el.current!);
    return () => {
      ro.disconnect();
      map.current = null;
      m.stop();
      m.remove();
    };
  }, []);

  useEffect(() => {
    if (truck && line && map.current && el.current)
      return animateTruck(map.current, el.current, line, stopIndex);
  }, [lineKey, truck, stopIndex]);

  useEffect(() => {
    const m = map.current;
    if (!m || !weather?.length) return;
    const overlay = L.layerGroup().addTo(m);
    for (const point of weather) {
      const icon = document.createElement("span");
      icon.textContent = point.icon;
      const label = document.createElement("span");
      label.textContent = point.label + " · regional model";
      L.marker([point.lat, point.lng], {
        icon: L.divIcon({ className: "mi-weather-pin", html: icon, iconSize: [27, 27], iconAnchor: [-8, 31] }),
        title: label.textContent, alt: label.textContent, zIndexOffset: 300,
      }).bindTooltip(label).addTo(overlay);
    }
    return () => { overlay.remove(); };
  }, [weather]);

  // Redraw route and points; selected point gets a halo.
  useEffect(() => {
    const g = layer.current;
    if (!g) return;
    const redraw = () => {
      g.clearLayers();
      if (line?.length) {
        L.polyline(line, {
          color: "#ffffff",
          weight: 8,
          opacity: 0.9,
          interactive: false,
        }).addTo(g);
        L.polyline(line, {
          color: "#225c44",
          weight: 5,
          opacity: 1,
          interactive: false,
        }).addTo(g);
      }
      const zoom = map.current?.getZoom() || 4;
      const cell = zoom <= 5 ? 2 : zoom <= 6 ? 0.5 : 0.00001;
      const groups = new Map<string, MapPoint[]>();
      const visible = zoom > 6 ? map.current?.getBounds().pad(0.25) : undefined;
      for (const p of points) {
        if (visible && !visible.contains([p.lat, p.lng])) continue;
        const key = truck ? String(p.id) : `${p.kind || ''}:${Math.floor(p.lat / cell)}:${Math.floor(p.lng / cell)}`;
        const members = groups.get(key);
        if (members) members.push(p);
        else groups.set(key, [p]);
      }
      for (const group of groups.values()) {
        const p = group.find((p) => p.id === selectedId) || group[0];
        const tip = document.createElement('span');
        tip.textContent = group.length > 1 ? `${group.length} entries near ${p.label}` : p.label;
        const sel = p.id === selectedId;
        const activate = () => {
          if (group.length > 1 && zoom <= 6)
            map.current?.setView([p.lat, p.lng], zoom + 2);
          else if (group.length > 1 && groupSelect.current) groupSelect.current(group.map(p => p.id));
          else select.current?.(p.id);
        };
        if (p.kind) {
          const glyph = document.createElement("span");
          const tone = group.some(member => member.tone === "ok") ? "ok" : p.tone;
          glyph.className = `mi-map-pin ${tone} ${sel ? "selected" : ""} ${group.every(member => member.approximate) ? "approximate" : ""}`;
          glyph.innerHTML = group.length > 1 ? String(group.length) :
            `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round">${SYMBOL[p.kind]}</svg>`;
          const marker = L.marker([p.lat, p.lng], { title: tip.textContent, alt: tip.textContent,
            icon: L.divIcon({ html: glyph, className: "mi-map-icon", iconSize: [28, 28], iconAnchor: [14, 14] }),
            zIndexOffset: sel ? 1000 : 0,
          }).bindTooltip(tip, { direction: "top", offset: [0, -12] }).on("click", activate).addTo(g);
          marker.getElement()?.setAttribute("aria-label", tip.textContent);
          continue;
        }
        if (sel)
          L.circleMarker([p.lat, p.lng], {
            radius: 16,
            stroke: false,
            fillColor: TONE[p.tone],
            fillOpacity: 0.14,
            interactive: false,
          }).addTo(g);
        L.circleMarker([p.lat, p.lng], {
          radius: group.length > 1 ? 12 : sel ? 7 : 5,
          color: "#fff",
          weight: 2,
          fillColor: TONE[p.tone],
          fillOpacity: 1,
        })
          .bindTooltip(
            tip,
            { className: "node-tip", direction: "top", offset: [0, -6] },
          )
          .on("click", activate)
          .addTo(g);
      }
    };
    redraw();
    map.current?.on("moveend", redraw);
    return () => {
      map.current?.off("moveend", redraw);
    };
  }, [points, selectedId, line, truck]);

  // Fit to the route, else the point set, whenever its identity (fitKey) changes.
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    if (line?.length)
      return void m.fitBounds(L.latLngBounds(line), { ...pad(), maxZoom: 9 });
    if (!points.length) return;
    m.fitBounds(L.latLngBounds(points.map((p) => [p.lat, p.lng])), {
      ...pad(),
      maxZoom: compact ? 10 : 7,
    });
  }, [fitKey, lineKey]);

  useEffect(() => {
    const m = map.current;
    const p = points.find((x) => x.id === selectedId);
    if (!m || !p) return;
    const b = L.latLngBounds([
      [p.lat, p.lng],
      [p.lat, p.lng],
    ]);
    const selectedBounds = {
      ...pad(),
      maxZoom: Math.max(m.getZoom(), 6),
      duration: 0.6,
    };
    if (compact) m.fitBounds(b, { ...selectedBounds, animate: false });
    else m.flyToBounds(b, selectedBounds);
  }, [selectedId]);

  const fit = () => {
    const m = map.current;
    if (!m) return;
    m.flyToBounds(
      points.length
        ? L.latLngBounds(points.map((p) => [p.lat, p.lng]))
        : L.latLngBounds(INDIA),
      { ...pad(), maxZoom: compact ? 10 : 7, duration: 0.5 },
    );
  };

  return (
    <div
      className={cn("relative isolate overflow-hidden", className)}
      data-testid="map"
    >
      <div
        ref={el}
        className="absolute inset-0 z-0"
        role="region"
        aria-label={ariaLabel}
      />
      <div className="absolute top-1/2 right-5 z-[500] flex -translate-y-1/2 flex-col gap-2 lg:right-6">
        <IconButton label="Zoom in" onClick={() => map.current?.zoomIn()}>
          <Plus size={16} />
        </IconButton>
        <IconButton label="Zoom out" onClick={() => map.current?.zoomOut()}>
          <Minus size={16} />
        </IconButton>
        <IconButton label="Fit to points" onClick={fit}>
          <Maximize2 size={14} />
        </IconButton>
      </div>
    </div>
  );
}
