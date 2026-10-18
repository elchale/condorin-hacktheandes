import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { RIVER_FALLBACK } from "../config";
import { Kpis } from "../components/Kpis";
import {
  ActivityList,
  DetectionList,
  LayersTab,
  LiveBadge,
  RiverList,
  Scrubber,
  SourcesFooter,
  type DetFilter,
  type LayerStatus,
} from "../components/Panels";
import { TopBar } from "../components/TopBar";
import { WelcomeOverlay } from "../components/WelcomeOverlay";
import { useMapa, useMedia, useSession } from "../lib/hooks";
import { monthOf } from "../lib/format";
import { initialSaveData, rememberSaveData, whenIdle } from "../lib/net";
import { getJSON, setItem } from "../lib/storage";
import { navigate, useLocation } from "../router";
import type { DetectionFeature, LayerMeta, Mapa, SceneImage } from "../types";
import type { ActiveLayer, Basemap, MapCommand, ResolvedRiver } from "../map/types";

const loadMap = () => import("../map/MapView");
const MapView = lazy(loadMap);

type Tab = "detecciones" | "rios" | "capas" | "actividad";
const PEEK = 156; // px of the sheet visible when collapsed: handle, status, scrubber and tabs
const LAYERS_KEY = "condorin.capas";

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
  return out;
}

export function Dashboard() {
  const session = useSession();
  const { search } = useLocation();
  const { data, live, checkedAt } = useMapa(session?.token ?? null);
  const desktop = useMedia("(min-width: 1024px)");

  const [tab, setTab] = useState<Tab>("detecciones");
  const [filter, setFilter] = useState<DetFilter>("todas");
  const [selected, setSelected] = useState<number | null>(null);
  const [command, setCommand] = useState<MapCommand | null>(null);
  const [basemap, setBasemap] = useState<Basemap>("dark");
  const [saveData, setSaveData] = useState(initialSaveData);
  const [mapWanted, setMapWanted] = useState(false);
  const [welcome, setWelcome] = useState(() => search.get("bienvenida") === "1");

  // Derived data
  const rivers = useMemo(() => resolveRivers(data), [data]);
  const names = useMemo(() => Object.fromEntries(data.rivers.map((r) => [r.slug, r.name])), [data]);
  const images = useMemo(() => Object.fromEntries(data.images.map((i) => [i.id, i])) as Record<number, SceneImage>, [data]);
  const mineList = useMemo(() => (session ? data.mine?.ong.rivers ?? [] : []), [data, session]);
  const mine = useMemo(() => new Set(mineList), [mineList]);
  const months = useMemo(() => data.timeline.map((t) => t.month).sort(), [data]);
  const [monthIdx, setMonthIdx] = useState(Number.MAX_SAFE_INTEGER);
  const idx = Math.min(monthIdx, Math.max(0, months.length - 1));
  const sorted = useMemo(
    () => [...data.detections.features].sort((a, b) => b.properties.captured_at.localeCompare(a.properties.captured_at)),
    [data],
  );
  const inTime = useMemo(() => {
    if (months.length < 2) return sorted;
    const until = months[idx];
    return sorted.filter((f) => monthOf(f.properties.captured_at) <= until);
  }, [sorted, months, idx]);
  const visible = useMemo<DetectionFeature[]>(() => {
    if (filter === "alerta") return inTime.filter((f) => f.properties.alerting);
    if (filter === "mias") return inTime.filter((f) => mine.has(f.properties.river));
    return inTime;
  }, [inTime, filter, mine]);

  useEffect(() => {
    if (!session && filter === "mias") setFilter("todas");
  }, [session, filter]);

  // Map chunk: after idle, or right away on the first interaction.
  useEffect(() => whenIdle(() => setMapWanted(true), 2500), []);
  const wantMap = useCallback(() => {
    if (!mapWanted) {
      void loadMap();
      setMapWanted(true);
    }
  }, [mapWanted]);

  // Static layers (Data contract C): only layers.json is read up front, after idle.
  const [metas, setMetas] = useState<LayerMeta[]>([]);
  const [activeIds, setActiveIds] = useState<Set<string>>(() => new Set(getJSON<string[]>(LAYERS_KEY, [])));
  const [layerData, setLayerData] = useState<Record<string, GeoJSON.GeoJsonObject>>({});
  const [layerStatus, setLayerStatus] = useState<Record<string, LayerStatus>>({});

  useEffect(
    () =>
      whenIdle(() => {
        fetch("/data/layers.json")
          .then((r) => (r.ok ? r.json() : []))
          .then((x: unknown) => setMetas(Array.isArray(x) ? (x as LayerMeta[]) : []))
          .catch(() => setMetas([]));
      }, 3000),
    [],
  );

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

  // Remembered layers come back once the map is there, never in save data mode.
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current || !mapWanted || metas.length === 0) return;
    restored.current = true;
    if (saveData) return setActiveIds(new Set());
    metas.filter((m) => activeIds.has(m.id)).forEach(fetchLayer);
  }, [mapWanted, metas, saveData, activeIds, fetchLayer]);

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

  // Bottom sheet (phones): three snap points driven by a CSS variable.
  const sheet = useRef<HTMLElement>(null);
  const [snap, setSnap] = useState<0 | 1 | 2>(0); // 0 peek, 1 half, 2 full
  const [sheetH, setSheetH] = useState(0);
  useEffect(() => {
    const measure = () => setSheetH(sheet.current?.offsetHeight ?? 0);
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);
  const snapY = (s: 0 | 1 | 2) => (s === 2 ? 0 : s === 1 ? Math.round(sheetH * 0.45) : Math.max(0, sheetH - PEEK));
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
    if (Math.abs(dy) > 4) d.moved = true;
    const y = Math.min(snapY(0), Math.max(0, d.base + dy));
    sheet.current.style.setProperty("--sheet-y", `${y}px`);
  };
  const onUp = (e: RPointerEvent) => {
    const d = drag.current;
    drag.current = null;
    if (!d || !sheet.current) return;
    sheet.current.classList.remove("dragging");
    sheet.current.style.removeProperty("--sheet-y");
    if (!d.moved) return setSnap((s) => (s === 0 ? 1 : 0));
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

  const toggleSave = () => {
    const next = !saveData;
    setSaveData(next);
    rememberSaveData(next);
    if (next) setBasemap("dark");
  };

  const tabs: { id: Tab; label: string }[] = [
    { id: "detecciones", label: "Detecciones" },
    { id: "rios", label: "Ríos" },
    ...(metas.length ? [{ id: "capas" as Tab, label: "Capas" }] : []),
    { id: "actividad", label: "Actividad" },
  ];
  const currentTab = tab === "capas" && !metas.length ? "detecciones" : tab;

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <TopBar />
      <main className="relative min-h-0 flex-1 lg:flex">
        {/* Map area. On phones it stops above the collapsed sheet so the attribution stays visible. */}
        <section
          className="absolute inset-x-0 top-0 isolate lg:relative lg:order-2 lg:h-full lg:flex-1"
          style={desktop ? undefined : { bottom: PEEK - 12 }}
          onPointerDown={wantMap}
        >
          <div className="grid-bg absolute inset-0" />
          {mapWanted && (
            <Suspense fallback={<p className="label-caps absolute inset-x-0 top-1/2 text-center">Cargando mapa</p>}>
              <MapView
                detections={visible}
                rivers={rivers}
                images={images}
                mineRivers={mineList}
                signedIn={!!session}
                basemap={basemap}
                layers={activeLayers}
                saveData={saveData}
                bottomInset={0}
                command={command}
                onSelect={setSelected}
              />
            </Suspense>
          )}
          <div className="pointer-events-none absolute inset-x-2 top-2 z-[500] sm:inset-x-3 sm:top-3">
            <div className="pointer-events-auto">
              <Kpis totals={data.totals} />
            </div>
            <div className="pointer-events-auto mt-2 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setBasemap((b) => (b === "dark" ? "sat" : "dark"))}
                disabled={saveData}
                aria-pressed={basemap === "sat"}
                title={saveData ? "No disponible en modo ahorro" : undefined}
                className={`min-h-11 rounded-md border px-3 text-[13px] font-semibold disabled:opacity-50 ${
                  basemap === "sat" ? "border-cian bg-panel text-cian" : "border-line bg-panel text-ink"
                }`}
              >
                Satélite
              </button>
              {metas.length > 0 && (
                <button
                  type="button"
                  onClick={() => openTab("capas")}
                  className="min-h-11 rounded-md border border-line bg-panel px-3 text-[13px] font-semibold"
                >
                  Capas
                </button>
              )}
            </div>
          </div>
        </section>

        {/* Bottom sheet on phones, left panel from 1024 px. */}
        <aside
          ref={sheet}
          aria-label="Panel de datos"
          className="sheet fixed inset-x-0 bottom-0 z-[1000] flex h-[calc(100dvh-104px)] flex-col rounded-t-xl border-t border-line bg-panel shadow-[0_-8px_24px_rgba(0,0,0,.45)] lg:static lg:order-1 lg:h-full lg:w-[360px] lg:shrink-0 lg:rounded-none lg:border-r lg:border-t-0 lg:shadow-none"
          style={desktop ? undefined : ({ "--sheet-y": `${snapY(snap)}px` } as React.CSSProperties)}
        >
          <div
            className="flex h-5 shrink-0 touch-none items-center justify-center lg:hidden"
            onPointerDown={onDown}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerCancel={onUp}
            role="button"
            aria-label={snap === 0 ? "Expandir panel" : "Contraer panel"}
            tabIndex={0}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setSnap((s) => (s === 0 ? 1 : 0))}
          >
            <span className="h-1 w-10 rounded-full bg-muted/50" />
          </div>
          <div
            className="flex shrink-0 touch-none items-center justify-between gap-2 px-3 pb-0.5 sm:px-4 lg:pt-3"
            onPointerDown={onDown}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerCancel={onUp}
          >
            <LiveBadge live={live} generatedAt={data.generated_at} checked={checkedAt !== null} />
            <button
              type="button"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={toggleSave}
              aria-pressed={saveData}
              className={`min-h-11 rounded-full border px-3 text-[11px] font-semibold ${saveData ? "border-ambar text-ambar" : "border-line text-muted"}`}
            >
              {saveData ? "Modo ahorro activo" : "Modo ahorro"}
            </button>
          </div>
          <div className="shrink-0">
            <Scrubber months={months} value={idx} onChange={setMonthIdx} />
          </div>
          <div role="tablist" className="flex shrink-0 border-b border-line px-1">
            {tabs.map((t) => (
              <button
                key={t.id}
                role="tab"
                type="button"
                aria-selected={currentTab === t.id}
                onClick={() => openTab(t.id)}
                className={`min-h-11 flex-1 border-b-2 px-1 text-[13px] font-semibold ${
                  currentTab === t.id ? "border-cian text-ink" : "border-transparent text-muted"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div role="tabpanel" className="min-h-0 flex-1 overflow-y-auto overscroll-contain pt-3">
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
            {currentTab === "rios" && <RiverList rivers={rivers} mine={mine} onPick={pickRiver} />}
            {currentTab === "capas" && (
              <LayersTab metas={metas} active={activeIds} status={layerStatus} onToggle={toggleLayer} saveData={saveData} />
            )}
            {currentTab === "actividad" && <ActivityList items={data.activity} />}
            <SourcesFooter layers={metas.filter((m) => activeIds.has(m.id))} />
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
