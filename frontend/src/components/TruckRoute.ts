import L from "leaflet";

export function routePosition(line: L.LatLngTuple[], cumulative: number[], distance: number): L.LatLngTuple {
  let left = 0;
  let right = cumulative.length - 1;
  while (right - left > 1) {
    const middle = Math.floor((left + right) / 2);
    if (cumulative[middle] < distance) left = middle;
    else right = middle;
  }
  const span = cumulative[right] - cumulative[left];
  const t = span ? Math.max(0, Math.min(1, (distance - cumulative[left]) / span)) : 0;
  return [line[left][0] + (line[right][0] - line[left][0]) * t, line[left][1] + (line[right][1] - line[left][1]) * t];
}

export function truckBearing(from: L.LatLngTuple, to: L.LatLngTuple) {
  const rad = Math.PI / 180;
  const a = from[0] * rad, b = to[0] * rad, delta = (to[1] - from[1]) * rad;
  return Math.atan2(Math.sin(delta) * Math.cos(b), Math.cos(a) * Math.sin(b) - Math.sin(a) * Math.cos(b) * Math.cos(delta)) / rad - 90;
}

export function animateTruck(map: L.Map, element: HTMLElement, line: L.LatLngTuple[], stopIndex?: number) {
  if (line.length < 2) return;
  const cumulative = [0];
  for (let i = 1; i < line.length; i++) cumulative.push(cumulative[i - 1] + map.distance(line[i - 1], line[i]));
  const total = cumulative[cumulative.length - 1];
  if (total <= 0) return;
  const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const icon = L.divIcon({ className: "mi-route-truck", iconSize: [30, 30], iconAnchor: [15, 15],
    html: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M2 5h12v12H2zM14 9h4l4 4v4h-8"/><circle cx="6" cy="18" r="2" fill="#225c44"/><circle cx="18" cy="18" r="2" fill="#225c44"/></svg>',
  });
  const marker = L.marker(line[0], { icon, interactive: false, keyboard: false, zIndexOffset: 2000 });
  const duration = 18000;
  const stop = stopIndex != null && stopIndex > 0 && stopIndex < line.length - 1
    ? cumulative[stopIndex] / total * duration : undefined;
  const hold = stop == null ? 0 : 1600;
  let elapsed = 0, previous = 0, frame = 0, visible = false;
  const pause = () => { cancelAnimationFrame(frame); frame = 0; previous = 0; };
  const tick = (now: number) => {
    if (previous) elapsed += now - previous;
    previous = now;
    const time = elapsed % (duration + hold + 2000);
    const travel = stop == null || time <= stop ? time : Math.max(stop, time - hold);
    const distance = Math.min(1, travel / duration) * total;
    const position = routePosition(line, cumulative, distance);
    marker.setLatLng(position);
    const element = marker.getElement?.();
    if (element) {
      element.dataset.lat = String(position[0]);
      element.dataset.lng = String(position[1]);
    }
    const from = routePosition(line, cumulative, Math.max(0, distance - 30));
    const to = routePosition(line, cumulative, Math.min(total, distance + 30));
    const svg = element?.querySelector("svg");
    if (svg) svg.style.transform = `rotate(${truckBearing(from, to)}deg)`;
    frame = requestAnimationFrame(tick);
  };
  const update = () => {
    if (!map.hasLayer(marker)) marker.addTo(map);
    if (motion.matches) {
      pause();
      marker.setLatLng(line[0]);
      const pin = marker.getElement?.();
      if (pin) {
        pin.dataset.lat = String(line[0][0]);
        pin.dataset.lng = String(line[0][1]);
        pin.dataset.stationary = "true";
      }
      return;
    }
    marker.getElement?.()?.removeAttribute("data-stationary");
    if (!visible || document.hidden) pause();
    else if (!frame) frame = requestAnimationFrame(tick);
  };
  const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; update(); });
  observer.observe(element);
  motion.addEventListener("change", update);
  document.addEventListener("visibilitychange", update);
  return () => {
    pause();
    observer.disconnect();
    marker.remove();
    motion.removeEventListener("change", update);
    document.removeEventListener("visibilitychange", update);
  };
}
