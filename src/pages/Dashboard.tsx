import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { buildPeriods, DEFAULT_PERIOD, FOOTPRINT_HA, RIVER_FALLBACK } from "../config";
import { DetectionList, LayersTab, RiverList, SaveNote, SourcesFooter, type DetFilter, type ExtraLayer, type LayerStatus } from "../components/Panels";
import { useFuentes } from "../lib/fuentes";
import { fmtNum } from "../lib/format";
import { Headline, Kpis, Legend, PeriodSelector, UpdatedLine } from "../components/MapPanelHeader";
import { TopBar } from "../components/TopBar";
import { WelcomeOverlay } from "../components/WelcomeOverlay";
import { useMapa, useMedia, useSession } from "../lib/hooks";
import { initialSaveData, rememberSaveData, whenIdle } from "../lib/net";
import { getItem, getJSON, setItem } from "../lib/storage";
import { navigate, useLocation } from "../router";
import type { DetectionFeature, LayerMeta, Mapa, SceneImage } from "../types";
import { ANP_ID, DEFAULT_LAYERS, FOOTPRINT_ID, layerMinZoom, type ActiveLayer, type Basemap, type MapCommand, type ResolvedRiver } from "../map/types";

const loadMap = () => import("../map/MapView");
const MapView = lazy(loadMap);

type Tab = "detecciones" | "rios" | "capas";
const LAYERS_KEY = "condorin.capas";
const HANDLE = 24;
const FIRE_COLOR = "#f97316";

function resolveRivers(data: Mapa): ResolvedRiver[] {
  const out: ResolvedRiver[] = [];
  for (const r of data.rivers) {
    let lat = r.lat;
    let lon = r.lon;
    if (lat == null || lon == null) {
      const pts = data.detections.features.filter((f) => f.properties.river === r.slug);
      if (pts.length) {
        lon = pts.reduce((s, f) => s + f.geometry.coordinates[0], 0) / pts.length;
        lat = pts.reduce((s, f) => s + f.geometry.coordinates[1], 0) / pts.length;
      } else if (RIVER_FALLBACK[r.slug]) {
        [lat, lon] = RIVER_FALLBACK[r.slug];
      }
    }
    if (lat != null && lon != null) out.push({ ...r, lat, lon });
  }
  // Rivers with detections first (the one being watched right now on top).
  out.sort((a, b) => b.detections - a.detections || a.name.localeCompare(b.name));
  return out;
}

/** Remembered layer choice, or the defaults (footprint and protected areas). Save data mode starts empty. */
function initialLayers(saveData: boolean): Set<string> {
  if (saveData) return new Set();
  if (getItem(LAYERS_KEY) === null) return new Set(DEFAULT_LAYERS);
  return new Set(getJSON<string[]>(LAYERS_KEY, []));
}

export function Dashboard() {
  const session = useSession();
  const { search } = useLocation();
  const { data, live } = useMapa(session?.token ?? null);
  const desktop = useMedia("(min-width: 1024px)");

  const [tab, setTab] = useState<Tab>("detecciones");
  const [filter, setFilter] = useState<DetFilter>("todas");
  const [selected, setSelected] = useState<number | null>(null);
  const [command, setCommand] = useState<MapCommand | null>(null);
  const [basemap, setBasemap] = useState<Basemap>("sat");
  const [saveData, setSaveData] = useState(initialSaveData);
  const [mapWanted, setMapWanted] = useState(false);
  const [welcome, setWelcome] = useState(() => search.get("bienvenida") === "1");
  const [zoom, setZoom] = useState(0);
  const [periodId, setPeriodId] = useState(DEFAULT_PERIOD);
  const [legendOpen, setLegendOpen] = useState(false);
  const [tilesLoading, setTilesLoading] = useState(false);

  // Derived data
  const rivers = useMemo(() => resolveRivers(data), [data]);
  const names = useMemo(() => Object.fromEntries(data.rivers.map((r) => [r.slug, r.name])), [data]);
  const images = useMemo(() => Object.fromEntries(data.images.map((i) => [i.id, i])) as Record<number, SceneImage>, [data]);
  const mineList = useMemo(() => (session ? data.mine?.ong.rivers ?? [] : []), [data, session]);
  const mine = useMemo(() => new Set(mineList), [mineList]);
  const periods = useMemo(() => buildPeriods(data.detections.features.map((f) => Number(f.properties.captured_at.slice(0, 4)))), [data]);
  const period = periods.find((p) => p.id === periodId) ?? periods[periods.length - 1];
  const sorted = useMemo(
    () => [...data.detections.features].sort((a, b) => b.properties.captured_at.localeCompare(a.properties.captured_at)),
    [data],
  );
  const inTime = useMemo(() => {
    const [from, to] = period.years;
    const since = period.days ? Date.now() - period.days * 86400_000 : 0;
    return sorted.filter((f) => {
      const y = Number(f.properties.captured_at.slice(0, 4));
      return y >= from && y <= to && (!since || new Date(f.properties.captured_at).getTime() >= since);
    });
  }, [sorted, period]);
  const visible = useMemo<DetectionFeature[]>(() => {
    if (filter === "alerta") return inTime.filter((f) => f.properties.alerting);
    if (filter === "mias") return inTime.filter((f) => mine.has(f.properties.river));
    return inTime;
  }, [inTime, filter, mine]);

  useEffect(() => {
    if (!session && filter === "mias") setFilter("todas");
  }, [session, filter]);

  // Map chunk: right away (the satellite map is the page), after idle in save data mode.
  useEffect(() => {
    if (!saveData) {
      setMapWanted(true);
      return;
    }
    return whenIdle(() => setMapWanted(true), 2500);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const wantMap = useCallback(() => {
    if (!mapWanted) {
      void loadMap();
      setMapWanted(true);
    }
  }, [mapWanted]);

  // Static layers (Data contract C). layers.json and the default layers are fetched at once, in
  // parallel with the map chunk, so the footprint paints with the first tiles.
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
        list.filter((m) => activeIds.has(m.id)).forEach(fetchLayer);
      })
      .catch(() => alive && setMetas([]));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
  const ha = useMemo(
    () => Object.entries(yearHa).reduce((s, [y, v]) => (Number(y) >= period.years[0] && Number(y) <= period.years[1] ? s + v : s), 0),
    [yearHa, period],
  );

  // Live feeds (fires, Global Forest Watch tiles, river radar and rain): fetched once the map is up.
  const [mapReady, setMapReady] = useState(false);
  const onMapReady = useCallback(() => setMapReady(true), []);
  const feeds = useFuentes(mapReady);
  const [firesOn, setFiresOn] = useState(false);
  const [tilesOn, setTilesOn] = useState<Set<string>>(() => new Set());
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
          wantMap();
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
          wantMap();
          setTilesOn((s) => {
            const n = new Set(s);
            if (n.has(t.id)) n.delete(t.id);
            else n.add(t.id);
            return n;
          });
        },
      });
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feeds, fireCount, firesOn, tilesOn]);
  const liveCredits = useMemo(() => {
    const out: { id: string; label: string; credit: string; url?: string }[] = [];
    if (firesOn && feeds) out.push({ id: "fires", label: "Incendios", credit: feeds.sources.firms?.attribution || "NASA FIRMS", url: feeds.sources.firms?.url });
    for (const t of activeTiles) out.push({ id: t.id, label: t.title, credit: t.attribution, url: "https://www.globalforestwatch.org" });
    return out;
  }, [firesOn, feeds, activeTiles]);

  // Dense layers that are on but hidden at this zoom (the map draws them from zoom 9 up).
  const farLayers =
    mapWanted && zoom > 0
      ? [
          ...activeLayers.filter((l) => zoom < layerMinZoom(l.meta)).map((l) => l.meta.short || l.meta.title),
          ...activeTiles.filter((t) => zoom < t.min_zoom).map((t) => t.title),
        ]
      : [];
  const busy = tilesLoading || Object.values(layerStatus).includes("loading");

  // Bottom sheet (phones): three snap points driven by a CSS variable. The peek shows the handle,
  // the stats and the year slider; it is measured, so it fits any font size.
  const sheet = useRef<HTMLElement>(null);
  const peekBox = useRef<HTMLDivElement>(null);
  const [snap, setSnap] = useState<0 | 1 | 2>(0); // 0 peek, 1 half, 2 full
  const [sheetH, setSheetH] = useState(0);
  const [peek, setPeek] = useState(190);
  useLayoutEffect(() => {
    const measure = () => {
      setSheetH(sheet.current?.offsetHeight ?? 0);
      // Collapsed, the sheet takes about a quarter of the screen (the rest shows on the half snap).
      if (peekBox.current) setPeek(Math.min(HANDLE + peekBox.current.offsetHeight + 8, Math.max(150, Math.round(window.innerHeight * 0.25))));
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);
  const snapY = (s: 0 | 1 | 2) => (s === 2 ? 0 : s === 1 ? Math.round(sheetH * 0.16) : Math.max(0, sheetH - peek));
  const justDragged = useRef(false);
  const drag = useRef<{ y0: number; t0: number; base: number; moved: boolean } | null>(null);

  const onDown = (e: RPointerEvent) => {
    if (desktop) return;
    drag.current = { y0: e.clientY, t0: performance.now(), base: snapY(snap), moved: false };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    sheet.current?.classList.add("dragging");
  };
  const onMove = (e: RPointerEvent) => {
    const d = drag.current;
    if (!d || !sheet.current) return;
    const dy = e.clientY - d.y0;
    if (Math.abs(dy) > 6) d.moved = true;
    const y = Math.min(snapY(0), Math.max(0, d.base + dy));
    sheet.current.style.setProperty("--sheet-y", `${y}px`);
  };
  const onUp = (e: RPointerEvent) => {
    const d = drag.current;
    drag.current = null;
    if (!d || !sheet.current) return;
    sheet.current.classList.remove("dragging");
    sheet.current.style.removeProperty("--sheet-y");
    justDragged.current = d.moved;
    if (!d.moved) return;
    const dy = e.clientY - d.y0;
    const v = dy / Math.max(1, performance.now() - d.t0); // px per ms
    const y = d.base + dy;
    let next: 0 | 1 | 2;
    if (v < -0.5) next = snap === 0 ? 1 : 2;
    else if (v > 0.5) next = snap === 2 ? 1 : 0;
    else {
      const opts: (0 | 1 | 2)[] = [0, 1, 2];
      next = opts.reduce((best, s) => (Math.abs(snapY(s) - y) < Math.abs(snapY(best) - y) ? s : best), 0 as 0 | 1 | 2);
    }
    setSnap(next);
  };
  const dragProps = desktop ? {} : { onPointerDown: onDown, onPointerMove: onMove, onPointerUp: onUp, onPointerCancel: onUp };

  const openTab = (t: Tab) => {
    setTab(t);
    if (!desktop && snap === 0) setSnap(1);
  };

  const n = useRef(0);
  const pickDetection = (id: number) => {
    wantMap();
    setSelected(id);
    setCommand({ kind: "detection", id, n: ++n.current });
    if (!desktop) setSnap(0);
  };
  const pickRiver = (r: ResolvedRiver) => {
    wantMap();
    setCommand({ kind: "point", lat: r.lat, lon: r.lon, zoom: 11, n: ++n.current });
    if (!desktop) setSnap(0);
  };

  // The KPI zooms to the detections in the period (the map opens on the whole Amazon).
  const showDetections = () => {
    if (!visible.length) return;
    wantMap();
    const lats = visible.map((f) => f.geometry.coordinates[1]);
    const lons = visible.map((f) => f.geometry.coordinates[0]);
    setCommand({ kind: "bounds", bounds: [[Math.min(...lats), Math.min(...lons)], [Math.max(...lats), Math.max(...lons)]], n: ++n.current });
    if (!desktop) setSnap(0);
  };

  const toggleSave = () => {
    const next = !saveData;
    setSaveData(next);
    rememberSaveData(next);
  };

  const tabs: { id: Tab; label: string }[] = [
    { id: "detecciones", label: "Detecciones" },
    { id: "rios", label: "Ríos" },
    ...(metas.length || extras.length ? [{ id: "capas" as Tab, label: "Capas" }] : []),
  ];
  const currentTab = tab === "capas" && !metas.length && !extras.length ? "detecciones" : tab;
  const expanded = !desktop && snap > 0;
  const legend = (
    <Legend
      footprint={activeIds.has(FOOTPRINT_ID)}
      anp={activeIds.has(ANP_ID)}
      extra={[
        ...metas.filter((m) => activeIds.has(m.id) && m.id !== FOOTPRINT_ID && m.id !== ANP_ID).map((m) => ({ id: m.id, label: m.short || m.title, color: m.color })),
        ...(firesOn && fireCount ? [{ id: "fires", label: "Naranja: incendios de los últimos 7 días", color: FIRE_COLOR }] : []),
      ]}
    />
  );

  const seg = (on: boolean) =>
    `min-h-11 px-3.5 text-[13px] font-bold transition-colors ${on ? "bg-ink text-white" : "bg-white text-ink hover:bg-panel-2"}`;

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-white">
      <TopBar />
      <main className="relative min-h-0 flex-1 lg:flex">
        {/* Map area. On phones it stops at the top of the collapsed sheet, so the attribution stays visible. */}
        <section
          className="map-shell absolute inset-x-0 top-0 isolate lg:relative lg:order-2 lg:h-full lg:flex-1"
          style={desktop ? undefined : { bottom: peek - 16 }}
          onPointerDown={wantMap}
          aria-label="Mapa"
        >
          {busy && <div className="progress absolute inset-x-0 top-0 z-[700] h-[3px]" role="progressbar" aria-label="Cargando capas del mapa" />}
          {mapWanted ? (
            <Suspense fallback={<MapPlaceholder />}>
              <MapView
                detections={visible}
                rivers={rivers}
                images={images}
                mineRivers={mineList}
                signedIn={!!session}
                basemap={basemap}
                layers={activeLayers}
                years={period.years}
                saveData={saveData}
                command={command}
                onSelect={setSelected}
                onZoom={setZoom}
                onTilesLoading={setTilesLoading}
                fires={firesOn ? feeds?.fires ?? null : null}
                tiles={activeTiles}
                onReady={onMapReady}
              />
            </Suspense>
          ) : (
            <MapPlaceholder />
          )}
          <div className="pointer-events-none absolute left-3 top-3 z-[600] flex max-w-[calc(100%-80px)] flex-wrap items-start gap-2">
            <div className="pointer-events-auto flex overflow-hidden rounded-xl shadow-[0_2px_10px_rgba(24,24,27,.18)]" role="group" aria-label="Mapa base">
              <button type="button" className={seg(basemap === "sat")} aria-pressed={basemap === "sat"} onClick={() => setBasemap("sat")}>
                Satélite
              </button>
              <button type="button" className={seg(basemap === "calles")} aria-pressed={basemap === "calles"} onClick={() => setBasemap("calles")}>
                Mapa
              </button>
            </div>
            <p className="pointer-events-auto flex min-h-11 items-center rounded-xl bg-white/95 px-3 text-[13px] font-bold text-ink shadow-[0_2px_10px_rgba(24,24,27,.18)]">
              {period.words.charAt(0).toUpperCase() + period.words.slice(1)}
            </p>
            <button
              type="button"
              onClick={() => setLegendOpen((v) => !v)}
              aria-expanded={legendOpen}
              aria-controls="leyenda-mapa"
              className="pointer-events-auto min-h-11 rounded-xl bg-white px-3.5 text-[13px] font-bold text-ink shadow-[0_2px_10px_rgba(24,24,27,.18)] hover:bg-panel-2 lg:hidden"
            >
              Leyenda
            </button>
            {legendOpen && (
              <div id="leyenda-mapa" className="pointer-events-auto basis-full rounded-2xl bg-white p-3 shadow-[0_6px_20px_rgba(24,24,27,.2)] lg:hidden">
                {legend}
              </div>
            )}
            {farLayers.length > 0 && (
              <p role="status" className="pointer-events-auto flex min-h-11 basis-full items-center self-start rounded-xl bg-ink/85 px-3 text-xs font-semibold text-white sm:basis-auto">
                Acércate para ver {farLayers.join(" y ")}
              </p>
            )}
          </div>
        </section>

        {/* White bottom sheet on phones, white left panel (380 px) from 1024 px. */}
        <aside
          ref={sheet}
          aria-label="Datos del mapa"
          role={expanded ? "dialog" : undefined}
          aria-modal={expanded ? false : undefined}
          className="sheet fixed inset-x-0 bottom-0 z-[1000] flex h-[calc(100dvh-96px)] flex-col rounded-t-3xl bg-white shadow-[0_-10px_30px_rgba(24,24,27,.18)] lg:static lg:order-1 lg:h-full lg:w-[380px] lg:shrink-0 lg:rounded-none lg:border-r lg:border-line lg:shadow-none"
          style={desktop ? undefined : ({ "--sheet-y": `${snapY(snap)}px` } as React.CSSProperties)}
        >
          <button
            type="button"
            className="flex shrink-0 touch-none items-center justify-center lg:hidden"
            style={{ height: HANDLE }}
            {...dragProps}
            onClick={() => {
              if (justDragged.current) return void (justDragged.current = false);
              setSnap((s) => (s === 0 ? 1 : 0));
            }}
            aria-label={snap === 0 ? "Expandir panel" : "Contraer panel"}
            aria-expanded={snap > 0}
          >
            <span className="h-1.5 w-11 rounded-full bg-zinc-300" />
          </button>
          <div ref={peekBox} className="shrink-0 space-y-3 lg:pt-5">
            <div className="touch-none space-y-3 lg:touch-auto" {...dragProps}>
              <Headline period={period} />
              <Kpis detections={inTime.length} alertsSent={data.totals.alerts_sent} ha={ha} onDetections={showDetections} />
            </div>
            <PeriodSelector periods={periods} value={period.id} onChange={setPeriodId} />
          </div>
          <div className="hidden shrink-0 px-4 pt-4 lg:block">{legend}</div>
          <div className="h-3 shrink-0" />
          <div role="tablist" aria-label="Secciones" className="flex shrink-0 border-b border-line px-2">
            {tabs.map((t) => (
              <button
                key={t.id}
                role="tab"
                type="button"
                id={`tab-${t.id}`}
                aria-selected={currentTab === t.id}
                aria-controls="panel-datos"
                onClick={() => openTab(t.id)}
                className={`min-h-11 flex-1 border-b-2 px-1 text-[13px] font-bold ${
                  currentTab === t.id ? "border-rojo text-ink" : "border-transparent text-muted hover:text-ink"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div id="panel-datos" role="tabpanel" aria-labelledby={`tab-${currentTab}`} className="min-h-0 flex-1 overflow-y-auto overscroll-contain pt-3">
            {saveData && currentTab === "detecciones" && (
              <div className="px-4">
                <SaveNote>Sin capas precargadas para gastar menos datos. La imagen satelital se mantiene.</SaveNote>
              </div>
            )}
            {currentTab === "detecciones" && (
              <DetectionList
                items={visible}
                names={names}
                mine={mine}
                selected={selected}
                filter={filter}
                setFilter={setFilter}
                signedIn={!!session}
                mineReady={!!data.mine}
                onPick={pickDetection}
              />
            )}
            {currentTab === "rios" && <RiverList rivers={rivers} mine={mine} onPick={pickRiver} feeds={feeds} />}
            {currentTab === "capas" && (
              <LayersTab metas={metas} active={activeIds} status={layerStatus} onToggle={toggleLayer} saveData={saveData} onToggleSave={toggleSave} extras={extras} />
            )}
            <div className="mt-6 space-y-1">
              <UpdatedLine generatedAt={data.generated_at} live={live} totals={data.totals} />
            </div>
            <SourcesFooter layers={metas} live={liveCredits} />
          </div>
        </aside>
      </main>

      {welcome && session && (
        <WelcomeOverlay
          ong={session.ong.name}
          name={session.member.name}
          onDone={() => {
            setWelcome(false);
            navigate("/", { replace: true });
          }}
        />
      )}
    </div>
  );
}

/** Shown until Leaflet arrives: the forest tone of the imagery with a quiet label, never a blank box. */
function MapPlaceholder() {
  return (
    <div className="map-placeholder absolute inset-0 grid place-items-center" aria-hidden>
      <span className="rounded-full bg-white/90 px-3 py-1.5 text-xs font-semibold text-muted shadow">Cargando mapa satelital</span>
    </div>
  );
}
