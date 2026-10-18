import { useMemo, useRef, useState } from "react";
import type { ExtraLayer } from "../../components/Panels";
import { forecastDays, nextPass, oldestFetch, slugKey, useFuentes } from "../../lib/fuentes";
import { fmtNum } from "../../lib/format";
import type { ResolvedRiver } from "../../map/types";

export const FIRE_COLOR = "#f97316";

export type LiveCredit = { id: string; label: string; credit: string; url?: string };

/**
 * Live feeds (fires, Global Forest Watch tiles, river radar and rain): fetched once the map is up.
 * Returns what the map draws, the extra rows of the "Capas" tab, the credits and the river popup lines.
 */
export function useLiveFeeds(mapReady: boolean, rivers: ResolvedRiver[], wantMap: () => void) {
  const feeds = useFuentes(mapReady);
  const [firesOn, setFiresOn] = useState(false);
  const [tilesOn, setTilesOn] = useState<Set<string>>(() => new Set());
  // The toggles call the latest wantMap without rebuilding the rows each time it changes.
  const want = useRef(wantMap);
  want.current = wantMap;
  const fireCount = feeds?.fires.features.length ?? 0;
  const activeTiles = useMemo(() => (feeds?.tile_layers ?? []).filter((t) => tilesOn.has(t.id)), [feeds, tilesOn]);

  const extras = useMemo<ExtraLayer[]>(() => {
    if (!feeds) return [];
    const out: ExtraLayer[] = [];
    if (fireCount)
      out.push({
        id: "fires",
        title: "Incendios (7 días, NASA FIRMS)",
        sub: `${fmtNum(fireCount)} focos de calor detectados por satélite`,
        color: FIRE_COLOR,
        on: firesOn,
        onToggle: () => {
          want.current();
          setFiresOn((v) => !v);
        },
      });
    for (const t of feeds.tile_layers)
      out.push({
        id: t.id,
        title: t.title,
        sub: `${t.attribution}. Se ve desde el zoom ${t.min_zoom}.`,
        color: "#db2777",
        on: tilesOn.has(t.id),
        onToggle: () => {
          want.current();
          setTilesOn((s) => {
            const n = new Set(s);
            if (n.has(t.id)) n.delete(t.id);
            else n.add(t.id);
            return n;
          });
        },
      });
    return out;
  }, [feeds, fireCount, firesOn, tilesOn]);

  const liveCredits = useMemo(() => {
    const out: LiveCredit[] = [];
    if (firesOn && feeds) out.push({ id: "fires", label: "Incendios", credit: feeds.sources.firms?.attribution || "NASA FIRMS", url: feeds.sources.firms?.url });
    for (const t of activeTiles) out.push({ id: t.id, label: t.title, credit: t.attribution, url: "https://www.globalforestwatch.org" });
    if (feeds) {
      const src = feeds.sources;
      if (src["open-meteo"]?.ok) out.push({ id: "open-meteo", label: "Lluvia y pronóstico", credit: src["open-meteo"].attribution, url: src["open-meteo"].url });
      if (src.glofas?.ok) out.push({ id: "glofas", label: "Caudal de los ríos", credit: src.glofas.attribution, url: src.glofas.url });
      if (src.sentinel?.ok) out.push({ id: "sentinel", label: "Pasos de radar", credit: src.sentinel.attribution, url: src.sentinel.url });
    }
    return out;
  }, [firesOn, feeds, activeTiles]);

  const liveAt = feeds ? oldestFetch(feeds.sources) : null;

  // Popup lines for each river ring on the map: next radar pass and rain for the next 3 days.
  const riverInfo = useMemo(() => {
    const out: Record<string, string[]> = {};
    if (!feeds) return out;
    for (const r of rivers) {
      const k = slugKey(r.slug);
      const lines: string[] = [];
      const pass = nextPass(feeds.satellite[k]);
      if (pass) lines.push(`Próximo paso de radar: ${pass}`);
      for (const d of forecastDays(feeds.weather[k]).slice(0, 3))
        lines.push(`Lluvia ${d.day}: ${Math.round(d.rain_mm)} mm${d.rain_prob != null ? ` (probabilidad ${d.rain_prob} %)` : ""}`);
      if (lines.length) out[r.slug] = lines;
    }
    return out;
  }, [feeds, rivers]);

  return { feeds, firesOn, fireCount, activeTiles, extras, liveCredits, liveAt, riverInfo };
}
