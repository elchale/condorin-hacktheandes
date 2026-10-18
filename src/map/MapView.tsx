import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "./map.css";
import { PANEL_URL } from "../config";
import { escapeHtml, fmtLongDate, fmtPct, fmtTime, limaDay } from "../lib/format";
import type { DetectionFeature } from "../types";
import type { FireCollection } from "../lib/fuentes";
import { AMAZONIA, ANP_ID, FOOTPRINT_ID, layerMinZoom, type ActiveLayer, type MapViewProps } from "./types";
import { navigate } from "../router";

// Esri tiles are keyless, 1x and all on one host (one TLS connection, one CSP entry).
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services";
const TILES = {
  sat: `${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`,
  satLabels: `${ESRI}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`,
  calles: `${ESRI}/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
  callesLabels: `${ESRI}/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}`,
};
const ATTRIB = {
  sat: "Esri, Maxar, Earthstar Geographics",
  calles: "Esri, HERE, Garmin, © OpenStreetMap contributors",
};
const C = { red: "#e11d2e", amber: "#f59e0b", yellow: "#facc15", yellowEdge: "#a16207", green: "#22c55e", white: "#ffffff" };
const CLUSTER_PX = 30;
const FIRE = "#f97316";
const CONF: Record<string, string> = { h: "alta", n: "normal", l: "baja" };
/** Fire dot radius: tiny when the whole country is in view (thousands of points), larger close in. */
const fireRadius = (frp: number, z: number) => (z < 7 ? 1.4 + Math.min(1.6, Math.sqrt(frp) / 10) : 2.5 + Math.min(5, Math.sqrt(frp) / 4));
const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function popupHtml(f: DetectionFeature, p: MapViewProps, riverName: string): string {
  const d = f.properties;
  const [lon, lat] = f.geometry.coordinates;
  const img = p.images[d.image];
  const gmaps = `https://www.google.com/maps?q=${lat.toFixed(5)},${lon.toFixed(5)}`;
  const pct = fmtPct(d.confidence);
  return `<div class="cp">
    <p class="cp-k${d.alerting ? "" : " cp-k-amber"}">${d.alerting ? "Draga con alerta" : "Posible draga"}</p>
    <p class="cp-t">Río ${escapeHtml(riverName)}</p>
    <p class="cp-d">${escapeHtml(fmtLongDate(d.captured_at))}</p>
    <div class="cp-conf"><span>Confianza</span><b>${pct}</b></div>
    <div class="cp-bar"><i style="width:${pct}"></i></div>
    <dl><dt>Satélite</dt><dd>${escapeHtml(d.satellite)}</dd>${img?.model ? `<dt>Modelo</dt><dd>${escapeHtml(img.model)}</dd>` : ""}</dl>
    <a href="${gmaps}" target="_blank" rel="noopener noreferrer" class="cp-btn">Ver en Google Maps</a>
    ${p.signedIn ? `<a href="${PANEL_URL}" class="cp-btn cp-panel" data-spa>Abrir en Mi panel</a>` : ""}
  </div>`;
}

/** Detections that share one map spot (often the same coordinate: a time series of one place). */
type Spot = { ll: L.LatLng; items: DetectionFeature[]; same: boolean };
/** River ring popup: the name, then the live lines (next radar pass, rain for 3 days) when they arrived. */
function riverPopupHtml(name: string, lines?: string[]): string {
  const body = lines?.length
    ? `<ul class="rp-l">${lines.map((l) => `<li>${escapeHtml(l)}</li>`).join("")}</ul>`
    : `<p class="rp-l">Cargando lluvia y pasos de radar.</p>`;
  return `<div class="cp"><p class="cp-t">Río ${escapeHtml(name)}</p>${body}</div>`;
}

const POP = { maxWidth: 300, minWidth: 250, autoPanPaddingTopLeft: L.point(16, 124), autoPanPaddingBottomRight: L.point(16, 16) };

/** White card listing every scene at the spot, newest first; each row opens its detail. */
function spotHtml(s: Spot, names: Record<string, string>): string {
  const rivers = [...new Set(s.items.map((f) => f.properties.river))];
  const river = rivers.length === 1 ? names[rivers[0]] ?? rivers[0] : "";
  const n = s.items.length;
  const head = `${n} detecciones en ${s.same ? "este punto" : "esta zona"}${river ? ` del río ${river}` : ""}`;
  const rows = s.items
    .map((f) => {
      const d = f.properties;
      return `<li><span class="sp-txt"><b>${escapeHtml(fmtLongDate(d.captured_at))}</b><span>${fmtPct(d.confidence)} de confianza · ${escapeHtml(d.satellite)}</span></span><button type="button" class="sp-btn" data-det="${d.id}">Ver detalle</button></li>`;
    })
    .join("");
  return `<div class="cp sp"><p class="cp-k">Mismo lugar, varias fechas</p><p class="sp-h">${escapeHtml(head)}</p><ul class="sp-list">${rows}</ul></div>`;
}

function layerPopup(props: Record<string, unknown> | null, labels: Record<string, string> | undefined, title: string) {
  if (!props) return escapeHtml(title);
  const keys = labels ? Object.keys(labels) : Object.keys(props).slice(0, 4);
  const rows = keys
    .filter((k) => props[k] !== undefined && props[k] !== null && props[k] !== "")
    .map((k) => {
      const v = props[k];
      const s = typeof v === "number" ? v.toLocaleString("es-PE") : String(v);
      return `<dt>${escapeHtml(labels?.[k] ?? k)}</dt><dd>${escapeHtml(s)}</dd>`;
    })
    .join("");
  return `<div class="cp"><p class="cp-k cp-k-muted">${escapeHtml(title)}</p><dl>${rows}</dl></div>`;
}

function firePopup(p: FireCollection["features"][number]["properties"]): string {
  const conf = p.confidence ? CONF[p.confidence] : undefined;
  return `<div class="cp">
    <p class="cp-k cp-k-amber">Incendio activo</p>
    <p class="cp-d">${escapeHtml(fmtLongDate(p.at))}, ${escapeHtml(fmtTime(p.at))}</p>
    <dl><dt>Sensor</dt><dd>${escapeHtml(p.sensor || "VIIRS")}</dd>${
      Number.isFinite(p.frp) ? `<dt>Potencia</dt><dd>${escapeHtml(p.frp.toLocaleString("es-PE"))} MW</dd>` : ""
    }${conf ? `<dt>Confianza</dt><dd>${conf}</dd>` : ""}</dl>
    <p class="cp-d">Fuente: NASA FIRMS</p>
  </div>`;
}

/** Bounding box center and planar weight of every polygon part, for the "in view" hectares. */
type Part = { lat: number; lon: number; year: number; ha: number };
function footprintParts(gj: GeoJSON.FeatureCollection): Part[] {
  const out: Part[] = [];
  for (const f of gj.features) {
    const year = Number(f.properties?.year) || 0;
    const total = Number(f.properties?.area_ha) || 0;
    const g = f.geometry;
    const polys = g.type === "MultiPolygon" ? g.coordinates : g.type === "Polygon" ? [g.coordinates] : [];
    const mine: Part[] = [];
    let sum = 0;
    for (const poly of polys) {
      const ring = poly[0];
      let a = 0;
      let sx = 0;
      let sy = 0;
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        a += (ring[j][0] - ring[i][0]) * (ring[j][1] + ring[i][1]);
        sx += ring[i][0];
        sy += ring[i][1];
      }
      const w = Math.abs(a) * Math.cos(((sy / ring.length) * Math.PI) / 180);
      sum += w;
      mine.push({ lon: sx / ring.length, lat: sy / ring.length, year, ha: w });
    }
    // Scale the planar weights so each year adds up to its published area.
    for (const p of mine) out.push({ ...p, ha: sum ? (p.ha / sum) * total : 0 });
  }
  return out;
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
  const staticLayers = useRef<Map<string, L.Layer>>(new Map());
  const yearLayers = useRef<Map<number, L.GeoJSON>>(new Map());
  const parts = useRef<Part[]>([]);
  const pendingPopup = useRef<number | null>(null);
  const fireLayer = useRef<L.LayerGroup | null>(null);
  const tileOverlays = useRef<Map<string, L.TileLayer>>(new Map());
  const spots = useRef<Map<number, Spot>>(new Map());
  const spotPopup = useRef<{ spot: Spot; popup: L.Popup } | null>(null);
  const latest = useRef(props);
  latest.current = props;

  const riverNames = () => Object.fromEntries(latest.current.rivers.map((r) => [r.slug, r.name]));
  const detailHtml = (spot: Spot, id: number) => {
    const names = riverNames();
    const f = spot.items.find((x) => x.properties.id === id);
    if (!f) return spotHtml(spot, names);
    return `<button type="button" class="sp-back" data-back>Volver a las ${spot.items.length} detecciones</button>${popupHtml(f, latest.current, names[f.properties.river] ?? f.properties.river)}`;
  };
  /** Opens the list card for a spot, or straight on one scene's detail. */
  const openSpot = (spot: Spot, detailId?: number) => {
    const m = map.current;
    if (!m) return;
    const popup = L.popup(POP)
      .setLatLng(spot.ll)
      .setContent(detailId != null ? detailHtml(spot, detailId) : spotHtml(spot, riverNames()))
      .openOn(m);
    spotPopup.current = { spot, popup };
    if (detailId != null) latest.current.onSelect(detailId);
  };
  /** Popup for one detection: its own marker, or the card of the spot it shares. */
  const openFor = (id: number): boolean => {
    const mk = markers.current.get(id);
    if (mk) {
      mk.openPopup();
      return true;
    }
    const spot = spots.current.get(id);
    if (spot) {
      openSpot(spot, id);
      return true;
    }
    return false;
  };

  const fitAmazonia = (animate: boolean) => map.current?.fitBounds(AMAZONIA, { padding: [8, 8], animate });

  const reportInView = () => {
    const m = map.current;
    const cb = latest.current.onFootprintInView;
    if (!m || !cb || parts.current.length === 0) return;
    const b = m.getBounds();
    const [from, to] = latest.current.years;
    let ha = 0;
    for (const p of parts.current) if (p.year >= from && p.year <= to && b.contains([p.lat, p.lon])) ha += p.ha;
    cb(Math.round(ha));
  };

  // Footprint: one GeoJSON per year so the slider only adds, removes and restyles (no rebuild).
  const styleYears = () => {
    const m = map.current;
    if (!m) return;
    const [from, y] = latest.current.years;
    const z = m.getZoom();
    for (const [year, layer] of yearLayers.current) {
      if (year > y || year < from) {
        layer.remove();
        continue;
      }
      const age = y - year;
      // Far out, the footprint cells are a few pixels wide: a bright stroke keeps them visible.
      const far = z < 9;
      layer.setStyle({
        color: far || age === 0 ? "#fde047" : C.yellowEdge,
        weight: z < 7 ? 2.5 : far ? 1.5 : age === 0 ? 1.2 : 0.6,
        fillColor: age === 0 ? "#fde047" : C.yellow,
        // Close in, the imagery under the footprint matters more than the fill.
        fillOpacity: (age === 0 ? 0.8 : Math.max(0.4, 0.62 - age * 0.03)) * (z >= 12 ? 0.45 : 1),
      });
      if (!m.hasLayer(layer)) layer.addTo(m);
    }
    detLayer.current?.eachLayer((x) => (x as L.Path).bringToFront?.());
    reportInView();
  };

  const buildLayer = (l: ActiveLayer): L.Layer => {
    const meta = l.meta;
    const popup = (f: GeoJSON.Feature, layer: L.Layer) =>
      layer.bindPopup(() => layerPopup(f.properties, meta.property_labels, meta.short || meta.title), { maxWidth: 260 });
    if (meta.id === FOOTPRINT_ID) {
      const fc = l.data as GeoJSON.FeatureCollection;
      parts.current = footprintParts(fc);
      const group = L.layerGroup();
      for (const f of fc.features) {
        const year = Number(f.properties?.year) || 0;
        yearLayers.current.set(year, L.geoJSON(f, { renderer: renderer.current!, onEachFeature: popup } as L.GeoJSONOptions));
      }
      return group;
    }
    const color = meta.color || C.amber;
    const outline = meta.id === ANP_ID;
    return L.geoJSON(l.data, {
      renderer: renderer.current!,
      style: () =>
        outline
          ? { color: C.green, weight: 1.6, fillColor: C.green, fillOpacity: 0.08 }
          : { color, weight: 1, fillColor: color, fillOpacity: 0.2 },
      pointToLayer: (_f, latlng) =>
        L.circleMarker(latlng, { renderer: renderer.current!, radius: 3.5, color: C.white, weight: 1, fillColor: color, fillOpacity: 0.9 }),
      onEachFeature: popup,
    } as L.GeoJSONOptions);
  };

  // Static open data layers (already fetched by the dashboard). Dense point layers are built and
  // drawn only from their minimum zoom up; switching a layer off removes it and drops it from memory.
  const syncStatic = () => {
    const m = map.current;
    if (!m) return;
    const z = m.getZoom();
    const want = new Map(latest.current.layers.map((l) => [l.meta.id, l]));
    for (const [id, layer] of staticLayers.current) {
      const l = want.get(id);
      if (!l || z < layerMinZoom(l.meta)) {
        layer.remove();
        staticLayers.current.delete(id);
        if (id === FOOTPRINT_ID) {
          yearLayers.current.forEach((y) => y.remove());
          yearLayers.current.clear();
          parts.current = [];
          latest.current.onFootprintInView?.(0);
        }
      }
    }
    for (const [id, l] of want) {
      if (staticLayers.current.has(id) || z < layerMinZoom(l.meta)) continue;
      const layer = buildLayer(l).addTo(m);
      if (id !== FOOTPRINT_ID) (layer as L.GeoJSON).bringToBack();
      staticLayers.current.set(id, layer);
      if (id === FOOTPRINT_ID) styleYears();
    }
    detLayer.current?.eachLayer((x) => (x as L.Path).bringToFront?.());
  };

  // Detections: red dots with a white halo; dots closer than CLUSTER_PX merge into a counted bubble.
  const drawDetections = () => {
    const m = map.current;
    const g = detLayer.current;
    if (!m || !g) return;
    g.clearLayers();
    markers.current.clear();
    spots.current.clear();
    const p = latest.current;
    const names = Object.fromEntries(p.rivers.map((r) => [r.slug, r.name]));
    const mine = new Set(p.mineRivers);
    const z = m.getZoom();
    const groups: { pt: L.Point; items: DetectionFeature[] }[] = [];
    for (const f of p.detections) {
      const pt = m.project([f.geometry.coordinates[1], f.geometry.coordinates[0]], z);
      const near = groups.find((x) => x.pt.distanceTo(pt) < CLUSTER_PX);
      if (near) near.items.push(f);
      else groups.push({ pt, items: [f] });
    }
    // Only scenes captured today (Lima) get the soft pulse ring, one per place.
    const today = limaDay(Date.now());
    const pulses = new Map<string, [number, number]>();
    for (const f of p.detections) {
      if (limaDay(f.properties.captured_at) !== today) continue;
      const [lon, lat] = f.geometry.coordinates;
      pulses.set(`${lat.toFixed(4)},${lon.toFixed(4)}`, [lat, lon]);
    }
    for (const grp of groups) {
      if (grp.items.length > 1) {
        const n = grp.items.length;
        const alert = grp.items.some((f) => f.properties.alerting);
        const ll = m.unproject(grp.pt, z);
        const size = n < 10 ? 34 : 40;
        const b = L.latLngBounds(grp.items.map((f) => [f.geometry.coordinates[1], f.geometry.coordinates[0]] as [number, number]));
        // Same coordinate (a time series of one place): zooming can never split it, so it lists the scenes.
        const same = b.getNorthEast().distanceTo(b.getSouthWest()) < 30;
        const list = same || z >= m.getMaxZoom();
        const items = [...grp.items].sort((a, c) => c.properties.captured_at.localeCompare(a.properties.captured_at));
        const spot: Spot = { ll: same ? b.getCenter() : ll, items, same };
        for (const f of items) spots.current.set(f.properties.id, spot);
        const mk = L.marker(spot.ll, {
          icon: L.divIcon({ className: "", html: `<span class="cl${alert ? "" : " cl-amber"}">${n}</span>`, iconSize: [size, size] }),
          keyboard: true,
          title: list ? `${n} detecciones en este punto, ver la lista` : `${n} detecciones, acercar`,
        });
        mk.on("click", () => {
          if (list) return openSpot(spot);
          m.fitBounds(b, { padding: [60, 60], maxZoom: Math.max(z + 3, 14), animate: !reduced() });
        });
        mk.addTo(g);
        continue;
      }
      const f = grp.items[0];
      const d = f.properties;
      const [lon, lat] = f.geometry.coordinates;
      const own = mine.has(d.river);
      const mk = L.circleMarker([lat, lon], {
        renderer: renderer.current!,
        radius: 6 + Math.round(d.confidence * 3),
        color: own ? "#0e7490" : C.white,
        weight: own ? 3 : 2.5,
        fillColor: d.alerting ? C.red : C.amber,
        fillOpacity: 1,
      });
      mk.bindPopup(() => popupHtml(f, latest.current, names[d.river] ?? d.river), { ...POP, maxWidth: 280, minWidth: 220 });
      mk.on("click", () => latest.current.onSelect(d.id));
      mk.addTo(g);
      markers.current.set(d.id, mk);
    }
    if (!p.saveData)
      for (const ll of pulses.values())
        L.marker(ll, { icon: L.divIcon({ className: "", html: '<span class="pulse"></span>', iconSize: [56, 56] }), interactive: false, keyboard: false })
          .setZIndexOffset(-100)
          .addTo(g);
    const want = pendingPopup.current;
    if (want != null && (markers.current.has(want) || spots.current.has(want))) {
      pendingPopup.current = null;
      openFor(want);
    }
  };

  // Create the map once.
  useEffect(() => {
    if (!el.current) return;
    const m = L.map(el.current, { preferCanvas: true, zoomControl: false, attributionControl: true, minZoom: 4 });
    m.attributionControl.setPrefix(false);
    L.control.zoom({ position: "topright", zoomInTitle: "Acercar", zoomOutTitle: "Alejar" }).addTo(m);
    // Labels sit above the base tiles and the footprint, and never catch taps.
    const lp = m.createPane("labels");
    lp.style.zIndex = "450";
    lp.style.pointerEvents = "none";
    renderer.current = L.canvas({ padding: 0.3 });
    riverLayer.current = L.layerGroup().addTo(m);
    detLayer.current = L.layerGroup().addTo(m);
    map.current = m;
    fitAmazonia(false);
    latest.current.onReady?.();
    const onZoom = () => {
      latest.current.onZoom?.(m.getZoom());
      syncStatic();
      styleYears();
      drawDetections();
    };
    m.on("zoomend", onZoom);
    m.on("moveend", reportInView);
    onZoom();
    // Popup links to our own pages stay inside the SPA.
    const onClick = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      const sp = spotPopup.current;
      const det = t.closest?.("[data-det]") as HTMLElement | null;
      if (det && sp) {
        const id = Number(det.dataset.det);
        sp.popup.setContent(detailHtml(sp.spot, id));
        latest.current.onSelect(id);
        return;
      }
      if (t.closest?.("[data-back]") && sp) {
        sp.popup.setContent(spotHtml(sp.spot, riverNames()));
        return;
      }
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
      yearLayers.current.clear();
      tileOverlays.current.clear();
      fireLayer.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Basemap (1x tiles only, never @2x). Satellite by default, place labels on top.
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    base.current?.remove();
    labels.current?.remove();
    const sat = props.basemap === "sat"; // satellite stays on in save data mode too (Carlos)
    const opts = { maxZoom: 18, maxNativeZoom: sat ? 18 : 16, detectRetina: false, updateWhenIdle: true, keepBuffer: 1 };
    base.current = L.tileLayer(sat ? TILES.sat : TILES.calles, { ...opts, attribution: sat ? ATTRIB.sat : ATTRIB.calles });
    const report = latest.current.onTilesLoading;
    base.current.on("loading", () => report?.(true));
    base.current.on("load", () => report?.(false));
    base.current.addTo(m).bringToBack();
    labels.current = L.tileLayer(sat ? TILES.satLabels : TILES.callesLabels, { ...opts, pane: "labels" }).addTo(m);
    el.current?.classList.toggle("is-sat", sat);
  }, [props.basemap]);

  // Rivers: labelled rings, teal when the member's ONG watches them.
  useEffect(() => {
    const g = riverLayer.current;
    if (!g) return;
    g.clearLayers();
    const mine = new Set(props.mineRivers);
    for (const r of props.rivers) {
      const own = mine.has(r.slug);
      L.circleMarker([r.lat, r.lon], {
        renderer: renderer.current!,
        radius: own ? 20 : 15,
        color: own ? "#22d3ee" : C.white,
        weight: own ? 2.5 : 1.5,
        dashArray: own ? undefined : "4 4",
        fill: false,
        interactive: false,
      })
        // The label is the click target (the ring stays out of the way of the detections inside it).
        .bindTooltip(`Río ${escapeHtml(r.name)}`, { permanent: true, interactive: true, direction: "right", offset: [own ? 20 : 15, 0], className: own ? "rt rt-own" : "rt" })
        .bindPopup(() => riverPopupHtml(r.name, latest.current.riverInfo?.[r.slug]), { ...POP, maxWidth: 280, minWidth: 220 })
        .addTo(g);
    }
  }, [props.rivers, props.mineRivers]);

  // NASA FIRMS fires: small orange canvas dots sized by fire radiative power, under the detections.
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    fireLayer.current?.remove();
    fireLayer.current = null;
    const fc = props.fires;
    if (!fc) return;
    const g = L.layerGroup();
    for (const f of fc.features) {
      const [lon, lat] = f.geometry.coordinates;
      const frp = Number(f.properties.frp) || 0;
      L.circleMarker([lat, lon], {
        renderer: renderer.current!,
        radius: fireRadius(frp, m.getZoom()),
        color: "#7c2d12",
        weight: m.getZoom() < 7 ? 0 : 0.6,
        fillColor: FIRE,
        fillOpacity: 0.85,
        frp,
      } as L.CircleMarkerOptions)
        .bindPopup(() => firePopup(f.properties), { maxWidth: 240 })
        .addTo(g);
    }
    g.addTo(m);
    fireLayer.current = g;
    detLayer.current?.eachLayer((x) => (x as L.Path).bringToFront?.());
    const resize = () => {
      const z = m.getZoom();
      g.eachLayer((x) => {
        const c = x as L.CircleMarker;
        const frp = Number((c.options as { frp?: number }).frp) || 0;
        c.setRadius(fireRadius(frp, z));
        c.setStyle({ weight: z < 7 ? 0 : 0.6 });
      });
    };
    m.on("zoomend", resize);
    return () => {
      m.off("zoomend", resize);
    };
  }, [props.fires]);

  // Global Forest Watch raster overlays, above the basemap and below the footprint.
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const want = new Map((props.tiles ?? []).map((t) => [t.id, t]));
    for (const [id, layer] of tileOverlays.current) {
      if (!want.has(id)) {
        layer.remove();
        tileOverlays.current.delete(id);
      }
    }
    for (const [id, t] of want) {
      if (tileOverlays.current.has(id)) continue;
      const layer = L.tileLayer(t.url, {
        minZoom: t.min_zoom,
        maxNativeZoom: t.max_zoom,
        maxZoom: 18,
        opacity: t.opacity,
        attribution: t.attribution,
        detectRetina: false,
        updateWhenIdle: true,
        keepBuffer: 1,
        zIndex: 5,
      }).addTo(m);
      tileOverlays.current.set(id, layer);
    }
  }, [props.tiles]);

  useEffect(drawDetections, [props.detections, props.rivers, props.mineRivers, props.saveData]);
  useEffect(syncStatic, [props.layers]);
  useEffect(styleYears, [props.years[0], props.years[1]]);

  // One shot commands from the list.
  useEffect(() => {
    const m = map.current;
    const c = props.command;
    if (!m || !c) return;
    const animate = !reduced();
    if (c.kind === "fit") return void fitAmazonia(animate);
    if (c.kind === "bounds") return void m.fitBounds(c.bounds, { padding: [60, 60], maxZoom: 12, animate });
    if (c.kind === "point") {
      const z = Math.max(m.getZoom(), c.zoom);
      return void (animate ? m.flyTo([c.lat, c.lon], z, { duration: 0.8 }) : m.setView([c.lat, c.lon], z));
    }
    const f = props.detections.find((x) => x.properties.id === c.id);
    if (!f) return;
    const ll = L.latLng(f.geometry.coordinates[1], f.geometry.coordinates[0]);
    const z = Math.max(m.getZoom(), 15);
    m.closePopup();
    pendingPopup.current = c.id;
    const open = () => {
      if (openFor(c.id)) pendingPopup.current = null;
    };
    if (animate) {
      m.once("moveend", open);
      m.flyTo(ll, z, { duration: 0.9 });
    } else {
      m.setView(ll, z);
      open();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.command]);

  return <div ref={el} className="map-root absolute inset-0" role="region" aria-label="Mapa satelital de minería y detecciones" />;
}
