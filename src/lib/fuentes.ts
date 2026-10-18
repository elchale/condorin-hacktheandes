// Live open data feeds from GET /api/v1/fuentes (public, gzip, about 60 KB): NASA FIRMS fires,
// Sentinel passes and weather per river, and Global Forest Watch raster tile layers.
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
};
export type RiverWeather = { rain_mm_7d?: number | null; rain_mm_24h?: number | null; temp_c?: number | null };

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);
  return data;
}

const dayFmt = new Intl.DateTimeFormat("es-PE", { weekday: "short", day: "numeric", month: "short", timeZone: "America/Lima" });
/** "lun 20 oct". */
const fmtDay = (iso: string) => dayFmt.format(new Date(iso)).replace(/[.,]/g, "").replace(/\s+/g, " ").trim();
const valid = (iso?: string | null): iso is string => !!iso && !Number.isNaN(new Date(iso).getTime());

/** "Radar Sentinel-1: último paso hace 2 días, próximo estimado lun 20 oct", or null without data. */
export function radarLine(s?: RiverSatellite): string | null {
  if (!s || !valid(s.s1_last)) return null;
  let out = `Radar Sentinel-1: último paso ${fmtAgo(s.s1_last)}`;
  if (valid(s.s1_next_estimate) && new Date(s.s1_next_estimate).getTime() > Date.now()) out += `, próximo estimado ${fmtDay(s.s1_next_estimate)}`;
  return out;
}

/** "Lluvia 7 días: 67 mm", or null without data. */
export function rainLine(w?: RiverWeather): string | null {
  if (!w || typeof w.rain_mm_7d !== "number" || !Number.isFinite(w.rain_mm_7d)) return null;
  return `Lluvia 7 días: ${Math.round(w.rain_mm_7d)} mm`;
}
