import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FIRST_YEAR, LAST_YEAR, RIVER_FALLBACK } from "../config";
import { makeWindow, nearestDays, shortDay, todayLima } from "../lib/days";
import { DetectionList, LayersTab, RiverList, SaveNote, SourcesFooter, TodayRivers, type DetFilter } from "../components/Panels";
import { fmtAgo, limaDay } from "../lib/format";
import { DataDays, Headline, Kpis, Legend, TimeTravel, UpdatedLine } from "../components/MapPanelHeader";
import { TopBar } from "../components/TopBar";
import { WelcomeOverlay } from "../components/WelcomeOverlay";
import { useMapa, useMedia, useSession } from "../lib/hooks";
import { initialSaveData, rememberSaveData, whenIdle } from "../lib/net";
import { navigate, useLocation } from "../router";
import type { DetectionFeature, Mapa, SceneImage } from "../types";
import { ANP_ID, FOOTPRINT_ID, layerMinZoom, type Basemap, type MapCommand, type ResolvedRiver } from "../map/types";
import { HANDLE, useBottomSheet } from "./dashboard/useBottomSheet";
import { useLayers } from "./dashboard/useLayers";
import { FIRE_COLOR, useLiveFeeds } from "./dashboard/useLiveFeeds";

const loadMap = () => import("../map/MapView");
const MapView = lazy(loadMap);

type Tab = "detecciones" | "rios" | "capas";
const FOOTPRINT_YEARS: [number, number] = [FIRST_YEAR, LAST_YEAR];

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
  // The time window ends on this Lima day; null follows today (the default: the last 3 days).
  const [endDay, setEndDay] = useState<string | null>(null);
  const [legendOpen, setLegendOpen] = useState(false);
  const [tilesLoading, setTilesLoading] = useState(false);

  // Derived data
  const rivers = useMemo(() => resolveRivers(data), [data]);
  const names = useMemo(() => Object.fromEntries(data.rivers.map((r) => [r.slug, r.name])), [data]);
  const images = useMemo(() => Object.fromEntries(data.images.map((i) => [i.id, i])) as Record<number, SceneImage>, [data]);
  const mineList = useMemo(() => (session ? data.mine?.ong.rivers ?? [] : []), [data, session]);
  const mine = useMemo(() => new Set(mineList), [mineList]);
  const sorted = useMemo(
    () => [...data.detections.features].sort((a, b) => b.properties.captured_at.localeCompare(a.properties.captured_at)),
    [data],
  );
  // Lima day of every scene, and the days that have data (newest first, with how many scenes).
  const dayOf = useMemo(() => new Map(sorted.map((f) => [f.properties.id, limaDay(f.properties.captured_at)])), [sorted]);
  const dataDays = useMemo(() => {
    const c = new Map<string, number>();
    for (const d of dayOf.values()) c.set(d, (c.get(d) ?? 0) + 1);
    return [...c].map(([day, n]) => ({ day, n })).sort((a, b) => b.day.localeCompare(a.day));
  }, [dayOf]);
  const today = todayLima();
  const end = endDay && endDay < today ? endDay : today;
  const win = useMemo(() => makeWindow(end, today), [end, today]);
  const travel = (day: string) => setEndDay(day >= today ? null : day);
  const inTime = useMemo(
    () =>
      sorted.filter((f) => {
        const d = dayOf.get(f.properties.id) ?? "";
        return d >= win.from && d <= win.to;
      }),
    [sorted, dayOf, win],
  );
  const nearDays = useMemo(
    () => (inTime.length ? [] : nearestDays(dataDays.map((d) => d.day), win).map((day) => ({ day, label: shortDay(day, true) }))),
    [inTime, dataDays, win],
  );
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

  const { metas, activeIds, layerStatus, toggleLayer, activeLayers, ha } = useLayers(wantMap);

  // Live feeds (fires, Global Forest Watch tiles, river radar and rain): fetched once the map is up.
  const [mapReady, setMapReady] = useState(false);
  const onMapReady = useCallback(() => setMapReady(true), []);
  const { feeds, firesOn, fireCount, activeTiles, extras, liveCredits, liveAt, riverInfo } = useLiveFeeds(mapReady, rivers, wantMap);

  // Dense layers that are on but hidden at this zoom (the map draws them from zoom 9 up).
  const farLayers =
    mapWanted && zoom > 0
      ? [
          ...activeLayers.filter((l) => zoom < layerMinZoom(l.meta)).map((l) => l.meta.short || l.meta.title),
          ...activeTiles.filter((t) => zoom < t.min_zoom).map((t) => t.title),
        ]
      : [];
  const busy = tilesLoading || Object.values(layerStatus).includes("loading");

  const { sheet, peekBox, snap, setSnap, peek, snapY, dragProps, onHandleClick } = useBottomSheet(desktop);

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
  const [riverFocus, setRiverFocus] = useState<{ slug: string; n: number } | null>(null);
  const openRiver = (slug: string) => {
    setTab("rios");
    setRiverFocus({ slug, n: ++n.current });
    if (!desktop) setSnap(2);
  };
  const pickRiver = (r: ResolvedRiver) => {
    wantMap();
    setCommand({ kind: "point", lat: r.lat, lon: r.lon, zoom: 11, n: ++n.current });
    if (!desktop) setSnap(0);
  };

  // The KPI zooms to the detections in the time window (the map opens on the whole Amazon).
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
                years={FOOTPRINT_YEARS}
                pulseDay={win.to}
                saveData={saveData}
                command={command}
                onSelect={setSelected}
                onZoom={setZoom}
                onTilesLoading={setTilesLoading}
                fires={firesOn ? feeds?.fires ?? null : null}
                tiles={activeTiles}
                onReady={onMapReady}
                riverInfo={riverInfo}
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
              {win.chip}
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
          className="sheet fixed inset-x-0 bottom-0 z-[1000] flex h-[calc(100dvh-96px)] flex-col rounded-t-3xl bg-white shadow-[0_-10px_30px_rgba(24,24,27,.18)] lg:static lg:order-1 lg:h-full lg:w-[380px] lg:shrink-0 lg:rounded-none lg:border-r lg:border-line lg:shadow-none"
          style={desktop ? undefined : ({ "--sheet-y": `${snapY(snap)}px` } as React.CSSProperties)}
        >
          <button
            type="button"
            className="flex shrink-0 touch-none items-center justify-center lg:hidden"
            style={{ height: HANDLE }}
            {...dragProps}
            onClick={onHandleClick}
            aria-label={snap === 0 ? "Expandir panel" : "Contraer panel"}
            aria-expanded={snap > 0}
          >
            <span className="h-1.5 w-11 rounded-full bg-zinc-300" />
          </button>
          <div ref={peekBox} className="shrink-0 space-y-3 lg:pt-5">
            <div className="touch-none space-y-3 lg:touch-auto" {...dragProps}>
              <Headline words={win.words} />
            </div>
            <TimeTravel win={win} today={today} onChange={travel} />
            <Kpis detections={inTime.length} alertsSent={data.totals.alerts_sent} ha={ha} onDetections={showDetections} />
            <DataDays days={dataDays} win={win} onPick={travel} />
          </div>
          {currentTab !== "rios" && (
            <div className="shrink-0 pt-3">
              <TodayRivers rivers={rivers} mine={mine} feeds={feeds} onOpen={openRiver} />
            </div>
          )}
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
                nearDays={nearDays}
                onJumpDay={travel}
              />
            )}
            {currentTab === "rios" && <RiverList rivers={rivers} mine={mine} onPick={pickRiver} feeds={feeds} focus={riverFocus} />}
            {currentTab === "capas" && (
              <LayersTab metas={metas} active={activeIds} status={layerStatus} onToggle={toggleLayer} saveData={saveData} onToggleSave={toggleSave} extras={extras} />
            )}
            <div className="mt-6 space-y-1">
              <UpdatedLine generatedAt={data.generated_at} live={live} totals={data.totals} />
              {liveAt && <p className="tnum px-4 text-xs text-muted">Datos en vivo actualizados {fmtAgo(liveAt, Date.now())}</p>}
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
