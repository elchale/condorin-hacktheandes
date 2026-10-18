import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "./map.css";
import { PANEL_URL } from "../config";
import { escapeHtml, fmtLongDate, fmtPct } from "../lib/format";
import type { DetectionFeature } from "../types";
import type { MapViewProps } from "./types";
import { navigate } from "../router";

// The contract asks for CARTO dark_all, but since 2026 keyless CARTO tiles come back watermarked
// "API KEY REQUIRED" (verified 2026-10-18, ETag wm-...-dark). Esri's Dark Gray Canvas is keyless, 1x,
// small (3 to 6 KB JPEG per tile) and draws rivers clearly. Set VITE_BASEMAP=carto to go back.
const CARTO = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png";
const ESRI_DARK = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}";
const ESRI_DARK_LABELS = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}";
const USE_CARTO = import.meta.env.VITE_BASEMAP === "carto";
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const COLORS = { red: "#e11d2e", amber: "#f59e0b", cyan: "#22d3ee", slate: "#94a3b8" };
const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function popupHtml(f: DetectionFeature, p: MapViewProps, riverName: string): string {
  const d = f.properties;
  const [lon, lat] = f.geometry.coordinates;
  const img = p.images[d.image];
  const gmaps = `https://www.google.com/maps?q=${lat.toFixed(5)},${lon.toFixed(5)}`;
  const rows: [string, string][] = [
    ["Fecha", fmtLongDate(d.captured_at)],
    ["Confianza", fmtPct(d.confidence)],
    ["Satélite", d.satellite],
  ];
  if (img?.model) rows.push(["Modelo", img.model]);
  return `<div class="cp">
    <p class="cp-k">${d.alerting ? "Draga con alerta" : "Posible draga"}</p>
    <p class="cp-t">Río ${escapeHtml(riverName)}</p>
    <dl>${rows.map(([k, v]) => `<dt>${k}</dt><dd>${escapeHtml(v)}</dd>`).join("")}</dl>
    <a href="${gmaps}" target="_blank" rel="noopener noreferrer">Ver en Google Maps</a>
    ${p.signedIn ? `<a href="${PANEL_URL}" class="cp-panel" data-spa>Abrir en Mi panel</a>` : ""}
  </div>`;
}

function layerPopup(props: Record<string, unknown> | null, labels: Record<string, string> | undefined, title: string) {
  if (!props) return escapeHtml(title);
  const keys = labels ? Object.keys(labels) : Object.keys(props).slice(0, 4);
  const rows = keys
    .filter((k) => props[k] !== undefined && props[k] !== null && props[k] !== "")
    .map((k) => `<dt>${escapeHtml(labels?.[k] ?? k)}</dt><dd>${escapeHtml(String(props[k]))}</dd>`)
    .join("");
  return `<div class="cp"><p class="cp-k">${escapeHtml(title)}</p><dl>${rows}</dl></div>`;
}

export default function MapView(props: MapViewProps) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const renderer = useRef<L.Canvas | null>(null);
  const base = useRef<L.TileLayer | null>(null);
  const labels = useRef<L.TileLayer | null>(null);
  const detLayer = useRef<L.LayerGroup | null>(null);
  const riverLayer = useRef<L.LayerGroup | null>(null);
  const markers = useRef<Map<number, L.CircleMarker>>(new Map());
  const staticLayers = useRef<Map<string, L.GeoJSON>>(new Map());
  const latest = useRef(props);
  latest.current = props;

  const pad = () => ({
    paddingTopLeft: L.point(24, 96),
    paddingBottomRight: L.point(24, latest.current.bottomInset + 24),
  });

  const fitAll = (animate: boolean) => {
    const m = map.current;
    const p = latest.current;
    if (!m) return;
    // Save data mode starts on the detections only; otherwise detections plus every watched river.
    const pts: L.LatLngExpression[] = p.detections.map((f) => [f.geometry.coordinates[1], f.geometry.coordinates[0]]);
    if (!p.saveData || pts.length === 0) p.rivers.forEach((r) => pts.push([r.lat, r.lon]));
    if (pts.length === 0) {
      m.setView([-8, -73], 5);
      return;
    }
    const b = L.latLngBounds(pts);
    m.fitBounds(b, { ...pad(), maxZoom: 13, animate });
  };

  // Create the map once.
  useEffect(() => {
    if (!el.current) return;
    const m = L.map(el.current, { preferCanvas: true, zoomControl: false, attributionControl: true, minZoom: 3 });
    m.attributionControl.setPrefix(false);
    if (window.matchMedia("(min-width: 1024px)").matches) L.control.zoom({ position: "bottomright" }).addTo(m);
    // Labels sit above the base tiles and below the detections, and never catch taps.
    const lp = m.createPane("labels");
    lp.style.zIndex = "350";
    lp.style.pointerEvents = "none";
    renderer.current = L.canvas({ padding: 0.3 });
    detLayer.current = L.layerGroup().addTo(m);
    riverLayer.current = L.layerGroup().addTo(m);
    map.current = m;
    fitAll(false);
    // Popup links to our own pages stay inside the SPA.
    const onClick = (e: MouseEvent) => {
      const a = (e.target as HTMLElement).closest?.("a[data-spa]") as HTMLAnchorElement | null;
      if (!a || e.metaKey || e.ctrlKey) return;
      e.preventDefault();
      navigate(a.getAttribute("href") || "/");
    };
    el.current.addEventListener("click", onClick);
    return () => {
      m.remove();
      map.current = null;
      markers.current.clear();
      staticLayers.current.clear();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Basemap (1x tiles only, never @2x).
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    base.current?.remove();
    labels.current?.remove();
    labels.current = null;
    const sat = props.basemap === "sat" && !props.saveData;
    const opts = { maxZoom: 18, detectRetina: false, updateWhenIdle: true, keepBuffer: 1 };
    if (sat) {
      base.current = L.tileLayer(ESRI, { ...opts, attribution: "Esri, Maxar, Earthstar Geographics" });
    } else if (USE_CARTO) {
      base.current = L.tileLayer(CARTO, { ...opts, subdomains: "abcd", maxZoom: 19, attribution: "© OpenStreetMap contributors © CARTO" });
    } else {
      base.current = L.tileLayer(ESRI_DARK, { ...opts, maxZoom: 16, attribution: "Esri, HERE, Garmin, © OpenStreetMap contributors" });
      // Place names: small transparent PNGs, desktop only and never in save data mode (phones get
      // the river labels drawn from our data, which saves a dozen requests and decodes).
      if (!props.saveData && window.matchMedia("(min-width: 1024px)").matches) labels.current = L.tileLayer(ESRI_DARK_LABELS, { ...opts, maxZoom: 16, pane: "labels" }).addTo(m);
    }
    base.current.addTo(m).bringToBack();
  }, [props.basemap, props.saveData]);

  // Rivers: hollow rings, cyan when the member's ONG watches them.
  useEffect(() => {
    const g = riverLayer.current;
    if (!g) return;
    g.clearLayers();
    const mine = new Set(props.mineRivers);
    for (const r of props.rivers) {
      const own = mine.has(r.slug);
      L.circleMarker([r.lat, r.lon], {
        renderer: renderer.current!,
        radius: own ? 22 : 16,
        color: own ? COLORS.cyan : COLORS.slate,
        weight: own ? 2 : 1,
        dashArray: own ? undefined : "3 4",
        fill: false,
        interactive: false,
      })
        .bindTooltip(`Río ${escapeHtml(r.name)}`, { permanent: true, direction: "right", offset: [own ? 22 : 16, 0], className: own ? "rt rt-own" : "rt" })
        .addTo(g);
    }
  }, [props.rivers, props.mineRivers]);

  // Detections.
  useEffect(() => {
    const g = detLayer.current;
    if (!g) return;
    g.clearLayers();
    markers.current.clear();
    const names = Object.fromEntries(props.rivers.map((r) => [r.slug, r.name]));
    const mine = new Set(props.mineRivers);
    for (const f of props.detections) {
      const d = f.properties;
      const [lon, lat] = f.geometry.coordinates;
      const mk = L.circleMarker([lat, lon], {
        renderer: renderer.current!,
        radius: 5 + Math.round(d.confidence * 4),
        color: mine.has(d.river) ? COLORS.cyan : "#0b1120",
        weight: mine.has(d.river) ? 2 : 1,
        fillColor: d.alerting ? COLORS.red : COLORS.amber,
        fillOpacity: 0.9,
      });
      mk.bindPopup(() => popupHtml(f, latest.current, names[d.river] ?? d.river), { maxWidth: 260, autoPanPaddingBottomRight: L.point(16, latest.current.bottomInset + 16) });
      mk.on("click", () => latest.current.onSelect(d.id));
      mk.addTo(g);
      markers.current.set(d.id, mk);
    }
  }, [props.detections, props.rivers, props.mineRivers]);

  // Static open data layers (already fetched by the dashboard).
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const want = new Map(props.layers.map((l) => [l.meta.id, l]));
    for (const [id, layer] of staticLayers.current) {
      if (!want.has(id)) {
        layer.remove();
        staticLayers.current.delete(id);
      }
    }
    for (const [id, l] of want) {
      if (staticLayers.current.has(id)) continue;
      const color = l.meta.color || COLORS.amber;
      const gj = L.geoJSON(l.data, {
        style: () => ({ color, weight: 1, fillColor: color, fillOpacity: 0.18, renderer: renderer.current! }),
        pointToLayer: (_f, latlng) => L.circleMarker(latlng, { renderer: renderer.current!, radius: 3, color, fillColor: color, fillOpacity: 0.7, weight: 1 }),
        onEachFeature: (f, layer) => layer.bindPopup(() => layerPopup(f.properties, l.meta.property_labels, l.meta.short || l.meta.title)),
      }).addTo(m);
      gj.bringToBack();
      staticLayers.current.set(id, gj);
    }
    detLayer.current?.eachLayer((x) => (x as L.CircleMarker).bringToFront());
  }, [props.layers]);

  // One shot commands from the list.
  useEffect(() => {
    const m = map.current;
    const c = props.command;
    if (!m || !c) return;
    const animate = !reduced();
    if (c.kind === "fit") return fitAll(animate);
    if (c.kind === "point") {
      const z = Math.max(m.getZoom(), c.zoom);
      const target = offsetForSheet(m, L.latLng(c.lat, c.lon), z, latest.current.bottomInset);
      return void (animate ? m.flyTo(target, z, { duration: 0.8 }) : m.setView(target, z));
    }
    const mk = markers.current.get(c.id);
    if (!mk) return;
    const z = Math.max(m.getZoom(), 13);
    const target = offsetForSheet(m, mk.getLatLng(), z, latest.current.bottomInset);
    if (animate) {
      m.once("moveend", () => mk.openPopup());
      m.flyTo(target, z, { duration: 0.8 });
    } else {
      m.setView(target, z);
      mk.openPopup();
    }
  }, [props.command]);

  return <div ref={el} className="absolute inset-0" role="region" aria-label="Mapa de detecciones" />;
}

/** Shift the center down so the target sits in the visible part above the bottom sheet. */
function offsetForSheet(m: L.Map, ll: L.LatLng, zoom: number, inset: number): L.LatLng {
  if (!inset) return ll;
  const p = m.project(ll, zoom).add([0, inset / 2]);
  return m.unproject(p, zoom);
}
