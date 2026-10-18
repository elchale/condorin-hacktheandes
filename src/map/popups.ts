// Popup HTML for the map (Leaflet takes strings). Every value goes through h``, so data is always escaped.
import type L from "leaflet";
import { PANEL_URL } from "../config";
import { fmtLongDate, fmtPct, fmtTime } from "../lib/format";
import type { FireCollection } from "../lib/fuentes";
import type { DetectionFeature, SceneImage } from "../types";
import { h } from "./html";

const CONF: Record<string, string> = { h: "alta", n: "normal", l: "baja" };

/** Detections that share one map spot (often the same coordinate: a time series of one place). */
export type Spot = { ll: L.LatLng; items: DetectionFeature[]; same: boolean };

export function popupHtml(f: DetectionFeature, p: { images: Record<number, SceneImage>; signedIn: boolean }, riverName: string): string {
  const d = f.properties;
  const [lon, lat] = f.geometry.coordinates;
  const img = p.images[d.image];
  const gmaps = `https://www.google.com/maps?q=${lat.toFixed(5)},${lon.toFixed(5)}`;
  const pct = fmtPct(d.confidence);
  return h`<div class="cp">
    <p class="cp-k${d.alerting ? "" : " cp-k-amber"}">${d.alerting ? "Draga con alerta" : "Posible draga"}</p>
    <p class="cp-t">Río ${riverName}</p>
    <p class="cp-d">${fmtLongDate(d.captured_at)}</p>
    <div class="cp-conf"><span>Confianza</span><b>${pct}</b></div>
    <div class="cp-bar"><i style="width:${pct}"></i></div>
    <dl><dt>Satélite</dt><dd>${d.satellite}</dd>${img?.model ? h`<dt>Modelo</dt><dd>${img.model}</dd>` : ""}</dl>
    <a href="${gmaps}" target="_blank" rel="noopener noreferrer" class="cp-btn">Ver en Google Maps</a>
    ${p.signedIn ? h`<a href="${PANEL_URL}" class="cp-btn cp-panel" data-spa>Abrir en Mi panel</a>` : ""}
  </div>`.value;
}

/** River ring popup: the name, then the live lines (next radar pass, rain for 3 days) when they arrived. */
export function riverPopupHtml(name: string, lines?: string[]): string {
  const body = lines?.length ? h`<ul class="rp-l">${lines.map((l) => h`<li>${l}</li>`)}</ul>` : h`<p class="rp-l">Cargando lluvia y pasos de radar.</p>`;
  return h`<div class="cp"><p class="cp-t">Río ${name}</p>${body}</div>`.value;
}

/** White card listing every scene at the spot, newest first; each row opens its detail. */
export function spotHtml(s: Spot, names: Record<string, string>): string {
  const rivers = [...new Set(s.items.map((f) => f.properties.river))];
  const river = rivers.length === 1 ? names[rivers[0]] ?? rivers[0] : "";
  const n = s.items.length;
  const head = `${n} detecciones en ${s.same ? "este punto" : "esta zona"}${river ? ` del río ${river}` : ""}`;
  const rows = s.items.map((f) => {
    const d = f.properties;
    return h`<li><span class="sp-txt"><b>${fmtLongDate(d.captured_at)}</b><span>${fmtPct(d.confidence)} de confianza · ${d.satellite}</span></span><button type="button" class="sp-btn" data-det="${d.id}">Ver detalle</button></li>`;
  });
  return h`<div class="cp sp"><p class="cp-k">Mismo lugar, varias fechas</p><p class="sp-h">${head}</p><ul class="sp-list">${rows}</ul></div>`.value;
}

/** One scene of a spot, with the way back to the list. */
export function spotDetailHtml(s: Spot, f: DetectionFeature, p: Parameters<typeof popupHtml>[1], riverName: string): string {
  return h`<button type="button" class="sp-back" data-back>Volver a las ${s.items.length} detecciones</button>`.value + popupHtml(f, p, riverName);
}

export function layerPopup(props: Record<string, unknown> | null, labels: Record<string, string> | undefined, title: string): string {
  if (!props) return h`${title}`.value;
  const keys = labels ? Object.keys(labels) : Object.keys(props).slice(0, 4);
  const rows = keys
    .filter((k) => props[k] !== undefined && props[k] !== null && props[k] !== "")
    .map((k) => {
      const v = props[k];
      const s = typeof v === "number" ? v.toLocaleString("es-PE") : String(v);
      return h`<dt>${labels?.[k] ?? k}</dt><dd>${s}</dd>`;
    });
  return h`<div class="cp"><p class="cp-k cp-k-muted">${title}</p><dl>${rows}</dl></div>`.value;
}

export function firePopup(p: FireCollection["features"][number]["properties"]): string {
  const conf = p.confidence ? CONF[p.confidence] : undefined;
  return h`<div class="cp">
    <p class="cp-k cp-k-amber">Incendio activo</p>
    <p class="cp-d">${fmtLongDate(p.at)}, ${fmtTime(p.at)}</p>
    <dl><dt>Sensor</dt><dd>${p.sensor || "VIIRS"}</dd>${
      Number.isFinite(p.frp) ? h`<dt>Potencia</dt><dd>${p.frp.toLocaleString("es-PE")} MW</dd>` : ""
    }${conf ? h`<dt>Confianza</dt><dd>${conf}</dd>` : ""}</dl>
    <p class="cp-d">Fuente: NASA FIRMS</p>
  </div>`.value;
}

/** Permanent river label (Leaflet tooltips take HTML too). */
export const riverLabel = (name: string) => h`Río ${name}`.value;
