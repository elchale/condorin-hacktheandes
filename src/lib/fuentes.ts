// Live open data feeds from GET /api/v1/fuentes (public, gzip, about 30 KB): NASA FIRMS fires,
// Sentinel passes, weather forecast, GloFAS discharge and a summary sentence per river, and Global Forest Watch raster tile layers.
// Fetched once after the map is up, never before first paint; any failure is silent.
import { useEffect, useState } from "react";
import { API_URL } from "../config";
import { fmtAgo } from "./format";
import { whenIdle } from "./net";

export type FireProps = { at: string; frp: number; sensor: string; daynight?: string; confidence?: string };
export type FireCollection = GeoJSON.FeatureCollection<GeoJSON.Point, FireProps>;

export type RiverSatellite = {
  s1_last?: string | null;
  s1_passes_30d?: number | null;
  s1_next_estimate?: string | null;
  s2_last?: string | null;
  s2_last_cloud?: number | null;
  s2_clear_last_30d?: number | null;
  next_passes?: { at: string; platform?: string }[];
};
export type ForecastDay = { date: string; rain_mm: number | null; rain_prob: number | null; tmax_c?: number | null };
export type RiverWeather = {
  rain_mm_7d?: number | null;
  rain_mm_24h?: number | null;
  temp_c?: number | null;
  forecast?: ForecastDay[];
  rain_mm_next_3d?: number | null;
};
export type Discharge = { today_m3s: number | null; mean_m3s?: number | null; trend?: "sube" | "baja" | "estable" | string };
export type FiresNear = { count_7d?: number | null; radius_km?: number | null };

export type TileLayerMeta = {
  id: string;
  title: string;
  dataset?: string;
  url: string;
  attribution: string;
  min_zoom: number;
  max_zoom: number;
  opacity: number;
};

export type FeedSource = { fetched_at: string | null; ok: boolean; attribution: string; url: string };

export type Fuentes = {
  generated_at: string;
  fires: FireCollection;
  satellite: Record<string, RiverSatellite>;
  weather: Record<string, RiverWeather>;
  rivers: Record<string, { discharge?: Discharge | null }>;
  fires_near_rivers: Record<string, FiresNear>;
  summary: Record<string, string>;
  tile_layers: TileLayerMeta[];
  sources: Record<string, FeedSource>;
};

const TIMEOUT_MS = 8000;

/** Slugs from the feeds drop accents ("maranon"); the map may keep them ("marañon"). */
export const slugKey = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

function byKey<T>(o: Record<string, T> | undefined): Record<string, T> {
  const out: Record<string, T> = {};
  for (const [k, v] of Object.entries(o ?? {})) out[slugKey(k)] = v;
  return out;
}

function clean(x: unknown): Fuentes | null {
  if (!x || typeof x !== "object") return null;
  const d = x as Partial<Fuentes>;
  const feats = Array.isArray(d.fires?.features) ? d.fires!.features.filter((f) => f?.geometry?.type === "Point") : [];
  return {
    generated_at: d.generated_at ?? "",
    fires: { type: "FeatureCollection", features: feats },
    satellite: byKey(d.satellite),
    weather: byKey(d.weather),
    rivers: byKey(d.rivers),
    fires_near_rivers: byKey(d.fires_near_rivers),
    summary: Object.fromEntries(Object.entries(byKey(d.summary)).filter(([, v]) => typeof v === "string" && v.trim())),
    tile_layers: Array.isArray(d.tile_layers) ? d.tile_layers.filter((t) => t && typeof t.url === "string" && t.url.startsWith("https://")) : [],
    sources: d.sources ?? {},
  };
}

/** Feeds, once `ready` turns true (the map is up) and the browser is idle. Null until then or on any error. */
export function useFuentes(ready: boolean): Fuentes | null {
  const [data, setData] = useState<Fuentes | null>(null);
  useEffect(() => {
    if (!ready || data) return;
    const ctrl = new AbortController();
    let timer = 0;
    const cancelIdle = whenIdle(() => {
      timer = window.setTimeout(() => ctrl.abort(), TIMEOUT_MS);
      fetch(`${API_URL}/api/v1/fuentes`, { signal: ctrl.signal })
        .then((r) => (r.ok ? r.json() : null))
        .then((x) => {
          const f = clean(x);
          if (f) setData(f);
        })
        .catch(() => {})
        .finally(() => window.clearTimeout(timer));
    }, 3000);
    return () => {
      cancelIdle();
      window.clearTimeout(timer);
      ctrl.abort();
    };
    // Fetched once: `data` is only the "already have it" guard, its change must not refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);
  return data;
}

const dayFmt = new Intl.DateTimeFormat("es-PE", { weekday: "short", day: "numeric", month: "short", timeZone: "America/Lima" });
/** "lun 20 oct". */
const fmtDay = (iso: string) => dayFmt.format(new Date(iso)).replace(/[.,]/g, "").replace(/\s+/g, " ").trim();
const valid = (iso?: string | null): iso is string => !!iso && !Number.isNaN(new Date(iso).getTime());

const num = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);
const fmtInt = (x: number) => Math.round(x).toLocaleString("es-PE");

/** "Radar: último paso hace 2 días, próximo mar 28 oct (Sentinel-1D)", or null without data. */
export function radarLine(s?: RiverSatellite): string | null {
  const next = nextPass(s);
  const last = s && valid(s.s1_last) ? `último paso ${fmtAgo(s.s1_last, Date.now())}` : "";
  if (!next && !last) return null;
  return `Radar: ${[last, next ? `próximo ${next}` : ""].filter(Boolean).join(", ")}`;
}

/** "mar 28 oct (Sentinel-1D)": the first future radar pass, or null. */
export function nextPass(s?: RiverSatellite): string | null {
  const now = Date.now();
  const p = (s?.next_passes ?? []).find((x) => valid(x?.at) && new Date(x.at).getTime() > now);
  if (p) return `${fmtDay(p.at)}${p.platform ? ` (${p.platform})` : ""}`;
  if (s && valid(s.s1_next_estimate) && new Date(s.s1_next_estimate).getTime() > now) return fmtDay(s.s1_next_estimate);
  return null;
}

const TREND: Record<string, string> = { sube: "en subida", baja: "en bajada", estable: "estable" };
/** "Caudal en subida, 156 m³/s", or null without data. */
export function dischargeLine(d?: Discharge | null): string | null {
  if (!d || !num(d.today_m3s)) return null;
  const t = d.trend && TREND[d.trend] ? ` ${TREND[d.trend]}` : "";
  return `Caudal${t}, ${fmtInt(d.today_m3s)} m³/s`;
}

/** "3 focos de calor a menos de 25 km en 7 días", or null when there are none. */
export function firesLine(f?: FiresNear): string | null {
  if (!f || !num(f.count_7d) || f.count_7d <= 0) return null;
  const km = num(f.radius_km) ? Math.round(f.radius_km) : 25;
  return `${f.count_7d === 1 ? "1 foco de calor" : `${fmtInt(f.count_7d)} focos de calor`} a menos de ${km} km en 7 días`;
}

const letterFmt = new Intl.DateTimeFormat("es-PE", { weekday: "narrow", timeZone: "UTC" });
const shortDayFmt = new Intl.DateTimeFormat("es-PE", { weekday: "short", day: "numeric", timeZone: "UTC" });
/** Forecast days with a rain amount, at most 7, each with its day letter ("L") and short day ("sáb 18"). */
export function forecastDays(w?: RiverWeather): (ForecastDay & { rain_mm: number; letter: string; day: string })[] {
  return (w?.forecast ?? [])
    .filter((d) => d && /^\d{4}-\d{2}-\d{2}$/.test(d.date) && num(d.rain_mm))
    .slice(0, 7)
    .map((d) => {
      const t = new Date(`${d.date}T12:00:00Z`);
      return { ...d, rain_mm: d.rain_mm as number, letter: letterFmt.format(t).toUpperCase(), day: shortDayFmt.format(t).replace(/[.,]/g, "") };
    });
}

/** The summary without its "Río X: " lead, for places that already show the river name. */
export const summaryBody = (s: string) => {
  const b = s.replace(/^R[ií]o [^:]{1,40}:\s*/, "");
  return b.charAt(0).toUpperCase() + b.slice(1);
};

/** The oldest fetched_at among the sources that loaded (how fresh the live data is at worst), or null. */
export function oldestFetch(sources: Record<string, FeedSource>): string | null {
  const t = Object.values(sources)
    .filter((x) => x?.ok && valid(x.fetched_at))
    .map((x) => x.fetched_at as string)
    .sort();
  return t[0] ?? null;
}
