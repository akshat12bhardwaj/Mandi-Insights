import { expect, it, vi } from "vitest";
import type L from "leaflet";
import { animateTruck, routePosition, truckBearing } from "../components/TruckRoute";

const { marker } = vi.hoisted(() => ({
  marker: { setLatLng: vi.fn(), addTo: vi.fn(), remove: vi.fn() },
}));
vi.mock("leaflet", () => ({ default: { marker: () => marker, divIcon: () => ({}) } }));

it("interpolates through bends by traveled distance", () => {
  expect(routePosition([[0, 0], [0, 3], [4, 3]], [0, 3, 7], 5)).toEqual([2, 3]);
});

it("rotates an east-facing truck to geographic headings", () => {
  expect(truckBearing([0, 0], [0, 1])).toBeCloseTo(0);
  expect(truckBearing([0, 0], [1, 0])).toBeCloseTo(-90);
  expect(truckBearing([0, 0], [-1, 0])).toBeCloseTo(90);
});

it("holds at a storage stop and cancels animation for reduced motion and cleanup", () => {
  let visibility: IntersectionObserverCallback;
  let motionChange: () => void;
  const observer = { observe: vi.fn(), disconnect: vi.fn() };
  const motion = { matches: false, addEventListener: (_: string, fn: () => void) => { motionChange = fn; }, removeEventListener: vi.fn() };
  vi.stubGlobal("IntersectionObserver", class { constructor(fn: IntersectionObserverCallback) { visibility = fn; return observer; } });
  vi.stubGlobal("matchMedia", () => motion);
  let callback: FrameRequestCallback;
  vi.stubGlobal("requestAnimationFrame", vi.fn(fn => { callback = fn; return 1; }));
  const cancel = vi.fn();
  vi.stubGlobal("cancelAnimationFrame", cancel);
  const map = { distance: () => 100, hasLayer: () => false } as unknown as L.Map;
  const stop = animateTruck(map, document.createElement("div"), [[0, 0], [0, 1], [1, 1]], 1)!;
  visibility!([{ isIntersecting: true } as IntersectionObserverEntry], observer as unknown as IntersectionObserver);
  callback!(1);
  callback!(9601);
  expect(marker.setLatLng).toHaveBeenLastCalledWith([0, 1]);
  motion.matches = true;
  motionChange!();
  expect(cancel).toHaveBeenCalledWith(1);
  expect(marker.setLatLng).toHaveBeenLastCalledWith([0, 0]);
  stop();
  expect(marker.remove).toHaveBeenCalled();
  expect(observer.disconnect).toHaveBeenCalled();
  expect(animateTruck(map, document.createElement("div"), [])).toBeUndefined();
  vi.unstubAllGlobals();
});
