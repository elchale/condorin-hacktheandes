import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LayerStatus } from "../../components/Panels";
import { FOOTPRINT_HA } from "../../config";
import { initialSaveData } from "../../lib/net";
import { getItem, getJSON, setItem } from "../../lib/storage";
import { DEFAULT_LAYERS, FOOTPRINT_ID, type ActiveLayer } from "../../map/types";
import type { LayerMeta } from "../../types";

const LAYERS_KEY = "condorin.capas";

/** Remembered layer choice, or the defaults (footprint and protected areas). Save data mode starts empty. */
function initialLayers(saveData: boolean): Set<string> {
  if (saveData) return new Set();
  if (getItem(LAYERS_KEY) === null) return new Set(DEFAULT_LAYERS);
  return new Set(getJSON<string[]>(LAYERS_KEY, []));
}

/**
 * Static layers (Data contract C). layers.json and the default layers are fetched at once, in
 * parallel with the map chunk, so the footprint paints with the first tiles.
 * `wantMap` runs when the member turns a layer on (it loads the map chunk if needed).
 */
export function useLayers(wantMap: () => void) {
  const [metas, setMetas] = useState<LayerMeta[]>([]);
  const [activeIds, setActiveIds] = useState<Set<string>>(() => initialLayers(initialSaveData()));
  const [layerData, setLayerData] = useState<Record<string, GeoJSON.GeoJsonObject>>({});
  const [layerStatus, setLayerStatus] = useState<Record<string, LayerStatus>>({});

  const fetchLayer = useCallback((m: LayerMeta) => {
    setLayerStatus((s) => ({ ...s, [m.id]: "loading" }));
    fetch(`/data/${m.file}?v=${m.bytes_gzip}`)
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .then((gj: GeoJSON.GeoJsonObject) => {
        setLayerData((d) => ({ ...d, [m.id]: gj }));
        setLayerStatus((s) => ({ ...s, [m.id]: "ready" }));
      })
      .catch(() => setLayerStatus((s) => ({ ...s, [m.id]: "error" })));
  }, []);

  const started = useRef(false);
  // The first active set, read once when layers.json arrives (later toggles fetch on their own).
  const firstActive = useRef(activeIds);
  useEffect(() => {
    let alive = true;
    fetch("/data/layers.json")
      .then((r) => (r.ok ? r.json() : []))
      .then((x: unknown) => {
        if (!alive) return;
        const list = Array.isArray(x) ? (x as LayerMeta[]) : [];
        setMetas(list);
        if (started.current) return;
        started.current = true;
        list.filter((m) => firstActive.current.has(m.id)).forEach(fetchLayer);
      })
      .catch(() => alive && setMetas([]));
    return () => {
      alive = false;
    };
  }, [fetchLayer]);

  const toggleLayer = (m: LayerMeta) => {
    wantMap();
    const next = new Set(activeIds);
    if (next.has(m.id) && layerStatus[m.id] !== "error") next.delete(m.id);
    else {
      next.add(m.id);
      if (!layerData[m.id]) fetchLayer(m);
    }
    setActiveIds(next);
    setItem(LAYERS_KEY, JSON.stringify([...next]));
  };

  const activeLayers = useMemo<ActiveLayer[]>(
    () => metas.filter((m) => activeIds.has(m.id) && layerData[m.id]).map((m) => ({ meta: m, data: layerData[m.id] })),
    [metas, activeIds, layerData],
  );

  // Footprint hectares up to the chosen year: from the file once loaded, the bundled table before.
  const yearHa = useMemo(() => {
    const fc = layerData[FOOTPRINT_ID] as GeoJSON.FeatureCollection | undefined;
    if (!fc?.features) return FOOTPRINT_HA;
    const t: Record<number, number> = {};
    for (const f of fc.features) t[Number(f.properties?.year)] = Number(f.properties?.area_ha) || 0;
    return t;
  }, [layerData]);
  // The footprint is yearly and cumulative: the time window never filters it.
  const ha = useMemo(() => Object.values(yearHa).reduce((s, v) => s + v, 0), [yearHa]);

  return { metas, activeIds, layerStatus, toggleLayer, activeLayers, ha };
}
