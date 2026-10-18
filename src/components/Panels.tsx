import { BRAND_NAME } from "../config";
import { fmtAgo, fmtDayYear, fmtNum, fmtPct, fmtShortDate, fmtTime } from "../lib/format";
import type { ActivityItem, DetectionFeature, LayerMeta } from "../types";
import { DEFAULT_LAYERS, layerMinZoom, type ResolvedRiver } from "../map/types";
import { useEffect } from "react";
import { dischargeLine, firesLine, forecastDays, radarLine, slugKey, summaryBody, type Fuentes, type RiverWeather } from "../lib/fuentes";

export type DetFilter = "todas" | "alerta" | "mias";

export function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={`min-h-11 shrink-0 rounded-full border px-3 text-[13px] font-semibold ${
        on ? "border-ink bg-ink text-white" : "border-line text-muted hover:text-ink"
      }`}
    >
      {children}
    </button>
  );
}

export function DetectionList(props: {
  items: DetectionFeature[];
  names: Record<string, string>;
  mine: Set<string>;
  selected: number | null;
  filter: DetFilter;
  setFilter: (f: DetFilter) => void;
  signedIn: boolean;
  mineReady: boolean;
  onPick: (id: number) => void;
  /** Days with data closest to an empty window, offered as buttons ("2026-10-16" and its label). */
  nearDays?: { day: string; label: string }[];
  onJumpDay?: (day: string) => void;
}) {
  const { items, names, mine, selected, filter, setFilter, signedIn, onPick } = props;
  return (
    <div>
      <div className="flex gap-2 overflow-x-auto px-3 pb-2 sm:px-4">
        <Chip on={filter === "todas"} onClick={() => setFilter("todas")}>Todas</Chip>
        <Chip on={filter === "alerta"} onClick={() => setFilter("alerta")}>Con alerta</Chip>
        {signedIn && <Chip on={filter === "mias"} onClick={() => setFilter("mias")}>Mis detecciones</Chip>}
      </div>
      {items.length === 0 ? (
        filter === "mias" && !props.mineReady ? (
          <p className="px-4 py-6 text-sm text-muted">Conectando para ver los ríos de tu ONG.</p>
        ) : filter !== "todas" ? (
          <p className="px-4 py-6 text-sm text-muted">Ninguna detección de este tipo en estos 3 días. Prueba otro día.</p>
        ) : (
          <div className="px-4 py-5">
            <p className="text-sm font-semibold text-ink">Sin detecciones en estos 3 días. Prueba otro día.</p>
            {!!props.nearDays?.length && (
              <>
                <p className="mt-2 text-xs text-muted">Días cercanos con detecciones:</p>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {props.nearDays.map((d) => (
                    <button
                      key={d.day}
                      type="button"
                      onClick={() => props.onJumpDay?.(d.day)}
                      className="tnum flex min-h-11 items-center gap-1.5 rounded-full border border-line px-3 text-[13px] font-bold text-ink hover:bg-panel-2"
                    >
                      <span className="size-2 rounded-full bg-rojo" aria-hidden />
                      {d.label}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        )
      ) : (
        <ul className="divide-y divide-line border-y border-line">
          {items.map((f) => {
            const d = f.properties;
            const sel = selected === d.id;
            return (
              <li key={d.id}>
                <button
                  type="button"
                  onClick={() => onPick(d.id)}
                  className={`flex min-h-14 w-full items-center gap-3 px-3 py-2.5 text-left sm:px-4 ${sel ? "bg-cian/10" : "hover:bg-panel-2"}`}
                >
                  <span className={`size-2.5 shrink-0 rounded-full ${d.alerting ? "bg-rojo" : "bg-ambar"}`} aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline justify-between gap-2">
                      <span className={`truncate text-sm font-semibold ${mine.has(d.river) ? "text-cian" : ""}`}>
                        Río {names[d.river] ?? d.river}
                      </span>
                      <span className="tnum shrink-0 text-xs text-muted">{fmtDayYear(d.captured_at)}</span>
                    </span>
                    <span className="mt-1.5 flex items-center gap-2">
                      <span className="h-1 flex-1 overflow-hidden rounded bg-line" aria-hidden>
                        <span className={`block h-full ${d.alerting ? "bg-rojo" : "bg-ambar"}`} style={{ width: fmtPct(d.confidence) }} />
                      </span>
                      <span className="tnum w-9 text-right text-xs">{fmtPct(d.confidence)}</span>
                      <span className="w-20 truncate text-right text-xs text-muted">{d.satellite}</span>
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export function RiverList({
  rivers,
  mine,
  onPick,
  feeds,
  focus,
}: {
  rivers: ResolvedRiver[];
  mine: Set<string>;
  onPick: (r: ResolvedRiver) => void;
  feeds?: Fuentes | null;
  /** Slug of the card to scroll to and outline ("Ver río" from the dashboard). */
  focus?: { slug: string; n: number } | null;
}) {
  useEffect(() => {
    if (focus) document.getElementById(`rio-${focus.slug}`)?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [focus]);
  return (
    <ul className="space-y-2 px-3 sm:px-4">
      {rivers.map((r) => (
        <li key={r.slug} id={`rio-${r.slug}`} className="scroll-mt-3">
          <button
            type="button"
            onClick={() => onPick(r)}
            className={`w-full rounded-lg border bg-panel-2/60 p-3 text-left hover:bg-panel-2 ${
              focus?.slug === r.slug ? "border-rojo ring-2 ring-rojo/30" : mine.has(r.slug) ? "border-cian/60" : "border-line"
            }`}
          >
            <span className="flex items-baseline justify-between gap-2">
              <span className="font-bold">Río {r.name}</span>
              {mine.has(r.slug) && <span className="label-caps !text-cian">Tu ONG</span>}
            </span>
            <span className="mt-0.5 block text-xs text-muted">{[r.region, r.province].filter(Boolean).join(", ")}</span>
            {feeds?.summary[slugKey(r.slug)] && (
              <span className="mt-2 block text-[13px] leading-snug text-ink">{summaryBody(feeds.summary[slugKey(r.slug)])}</span>
            )}
            {r.protected_area && (
              <span className="mt-2 inline-block rounded border border-verde/40 bg-verde/10 px-1.5 py-0.5 text-[11px] font-semibold text-verde">
                {r.protected_area}
              </span>
            )}
            <span className="tnum mt-2 grid grid-cols-3 gap-2 text-xs">
              <span>
                <span className="label-caps block">ONGs</span>
                {fmtNum(r.ongs)}
              </span>
              <span>
                <span className="label-caps block">Detecciones</span>
                {fmtNum(r.detections)}
              </span>
              <span>
                <span className="label-caps block">Última</span>
                {r.last_captured_at ? fmtDayYear(r.last_captured_at) : "Ninguna"}
              </span>
            </span>
            {feeds && <FeedLines feeds={feeds} slug={slugKey(r.slug)} />}
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Forecast strip, discharge, radar and nearby fires for one river card; each line only when it has data. */
function FeedLines({ feeds, slug }: { feeds: Fuentes; slug: string }) {
  const days = forecastDays(feeds.weather[slug]);
  const lines = [
    dischargeLine(feeds.rivers[slug]?.discharge),
    radarLine(feeds.satellite[slug]),
    firesLine(feeds.fires_near_rivers[slug]),
  ].filter((x): x is string => !!x);
  if (!days.length && !lines.length) return null;
  return (
    <span className="mt-2 block space-y-2 border-t border-line pt-2 text-xs text-muted">
      {days.length > 0 && <RainStrip days={days} w={feeds.weather[slug]} />}
      {lines.length > 0 && (
        <span className="block space-y-0.5">
          {lines.map((l) => (
            <span key={l} className="block">
              {l}
            </span>
          ))}
        </span>
      )}
    </span>
  );
}

/** Seven small bars: rain in mm per day, paler when the rain is less likely. */
function RainStrip({ days, w }: { days: ReturnType<typeof forecastDays>; w?: RiverWeather }) {
  const top = Math.max(10, ...days.map((d) => d.rain_mm));
  const label = days.map((d) => `${d.day}: ${Math.round(d.rain_mm)} mm${d.rain_prob != null ? `, ${d.rain_prob} %` : ""}`).join("; ");
  return (
    <span className="block">
      <span className="block font-semibold text-ink">Lluvia prevista, próximos {days.length} días (mm)</span>
      <span className="mt-1 grid gap-1" style={{ gridTemplateColumns: `repeat(${days.length}, minmax(0, 1fr))` }} role="img" aria-label={label}>
        {days.map((d) => (
          <span key={d.date} className="flex flex-col items-center" title={`${d.day}: ${Math.round(d.rain_mm)} mm, probabilidad ${d.rain_prob ?? "?"} %`}>
            <span className="flex h-8 w-full items-end justify-center rounded-sm bg-white">
              <span
                className="w-3 rounded-t-sm bg-sky-600"
                style={{ height: `${Math.max(2, Math.round((d.rain_mm / top) * 32))}px`, opacity: 0.3 + 0.7 * Math.min(1, Math.max(0, (d.rain_prob ?? 100) / 100)) }}
              />
            </span>
            <span className="tnum mt-0.5 text-[11px] font-semibold leading-none text-ink">{Math.round(d.rain_mm)}</span>
            <span className="mt-0.5 text-[10px] leading-none">{d.letter}</span>
          </span>
        ))}
      </span>
      <span className="mt-1 block text-[11px]">
        {typeof w?.rain_mm_next_3d === "number" ? `${Math.round(w.rain_mm_next_3d)} mm en los próximos 3 días. ` : ""}Barra más clara: lluvia menos probable.
      </span>
    </span>
  );
}

export type LayerStatus = "loading" | "error" | "ready";

/** A live layer from /api/v1/fuentes (fires, Global Forest Watch tiles) shown under "Más capas". */
export type ExtraLayer = { id: string; title: string; sub: string; color: string; on: boolean; onToggle: () => void };

function ExtraRow({ x }: { x: ExtraLayer }) {
  return (
    <li>
      <button
        type="button"
        role="switch"
        aria-checked={x.on}
        onClick={x.onToggle}
        className="flex w-full items-start gap-3 rounded-2xl bg-panel-2 p-3 text-left hover:bg-zinc-200/70"
      >
        <span className="mt-1 size-3.5 shrink-0 rounded-[4px]" style={{ background: x.color }} aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-bold">{x.title}</span>
          <span className="mt-0.5 block text-xs text-muted">{x.sub}</span>
        </span>
        <span className={`relative mt-0.5 h-6 w-10 shrink-0 rounded-full transition-colors ${x.on ? "bg-rojo" : "bg-zinc-300"}`} aria-hidden>
          <span className={`absolute top-0.5 size-5 rounded-full bg-white shadow transition-transform ${x.on ? "translate-x-[18px]" : "translate-x-0.5"}`} />
        </span>
      </button>
    </li>
  );
}

/** Small amber card explaining what save data mode turns off. */
export function SaveNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-3 flex gap-2 rounded-lg border border-ambar/40 bg-ambar/10 px-3 py-2 text-xs leading-relaxed text-amber-800">
      <span className="label-caps shrink-0 !text-ambar">Modo ahorro</span>
      <span>{children}</span>
    </p>
  );
}

function LayerRow({ m, on, st, onToggle }: { m: LayerMeta; on: boolean; st?: LayerStatus; onToggle: (m: LayerMeta) => void }) {
  return (
    <li>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        onClick={() => onToggle(m)}
        className="flex w-full items-start gap-3 rounded-2xl bg-panel-2 p-3 text-left hover:bg-zinc-200/70"
      >
        <span className="mt-1 size-3.5 shrink-0 rounded-[4px]" style={{ background: m.color }} aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-bold">{m.title}</span>
          <span className="mt-0.5 block text-xs text-muted">
            {m.source}, {m.year}.
          </span>
          <span className="tnum mt-1 block text-xs text-muted">
            {fmtNum(m.features)} elementos, {Math.max(1, Math.round(m.bytes_gzip / 1024))} KB
            {layerMinZoom(m) > 0 && <span> · se ve al acercarte</span>}
            {st === "loading" && <span className="font-semibold text-ink"> · cargando</span>}
            {st === "error" && <span className="font-semibold text-rojo-3"> · no se pudo cargar, toca para reintentar</span>}
          </span>
        </span>
        <span className={`relative mt-0.5 h-6 w-10 shrink-0 rounded-full transition-colors ${on ? "bg-rojo" : "bg-zinc-300"}`} aria-hidden>
          <span className={`absolute top-0.5 size-5 rounded-full bg-white shadow transition-transform ${on ? "translate-x-[18px]" : "translate-x-0.5"}`} />
        </span>
      </button>
    </li>
  );
}

/** Capas: the two default layers, then everything else behind "Más capas", then save data mode. */
export function LayersTab(props: {
  metas: LayerMeta[];
  active: Set<string>;
  status: Record<string, LayerStatus>;
  onToggle: (m: LayerMeta) => void;
  saveData: boolean;
  onToggleSave: () => void;
  extras?: ExtraLayer[];
}) {
  const { metas, active, status, onToggle, saveData, onToggleSave, extras = [] } = props;
  const main = metas.filter((m) => DEFAULT_LAYERS.includes(m.id));
  const more = metas.filter((m) => !DEFAULT_LAYERS.includes(m.id));
  const moreOn = more.some((m) => active.has(m.id)) || extras.some((x) => x.on);
  const moreCount = more.length + extras.length;
  return (
    <div className="px-4">
      {saveData && <SaveNote>Las capas se descargan solo cuando las activas.</SaveNote>}
      <ul className="space-y-2">
        {main.map((m) => (
          <LayerRow key={m.id} m={m} on={active.has(m.id)} st={status[m.id]} onToggle={onToggle} />
        ))}
      </ul>
      {moreCount > 0 && (
        <details className="group mt-3" open={moreOn}>
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between rounded-xl px-1 text-sm font-bold [&::-webkit-details-marker]:hidden">
            Más capas ({moreCount})
            <span className="text-muted transition-transform group-open:rotate-180" aria-hidden>
              ▾
            </span>
          </summary>
          <ul className="mt-1 space-y-2">
            {more.map((m) => (
              <LayerRow key={m.id} m={m} on={active.has(m.id)} st={status[m.id]} onToggle={onToggle} />
            ))}
            {extras.map((x) => (
              <ExtraRow key={x.id} x={x} />
            ))}
          </ul>
        </details>
      )}
      <button
        type="button"
        role="switch"
        aria-checked={saveData}
        onClick={onToggleSave}
        className="mt-3 flex min-h-11 w-full items-center justify-between gap-3 rounded-xl px-1 text-left text-sm"
      >
        <span>
          <span className="block font-bold">Modo ahorro de datos</span>
          <span className="block text-xs text-muted">Para señal débil: no precarga capas.</span>
        </span>
        <span className={`relative h-6 w-10 shrink-0 rounded-full transition-colors ${saveData ? "bg-ambar" : "bg-zinc-300"}`} aria-hidden>
          <span className={`absolute top-0.5 size-5 rounded-full bg-white shadow transition-transform ${saveData ? "translate-x-[18px]" : "translate-x-0.5"}`} />
        </span>
      </button>
    </div>
  );
}

const KIND: Record<string, { label: string; dot: string }> = {
  image: { label: "Escena", dot: "bg-cian" },
  alert: { label: "Alerta", dot: "bg-rojo" },
  expediente_opened: { label: "Expediente", dot: "bg-ambar" },
  expediente_filed: { label: "Presentado", dot: "bg-verde" },
};

export function ActivityList({ items, usage = [] }: { items: ActivityItem[]; usage?: { label: string; value: number; tone: string }[] }) {
  return (
    <>
      {usage.length > 0 && (
        <dl className="mx-3 mb-4 grid grid-cols-2 gap-2 sm:mx-4">
          {usage.map((u) => (
            <div key={u.label} className="flex flex-col-reverse rounded-lg border border-line bg-panel-2/60 px-3 py-2">
              <dt className="label-caps mt-1">{u.label}</dt>
              <dd className={`tnum text-2xl font-bold leading-none ${u.tone}`}>{fmtNum(u.value)}</dd>
            </div>
          ))}
        </dl>
      )}
      {items.length === 0 ? <p className="px-4 py-6 text-sm text-muted">Sin actividad reciente.</p> : <Timeline items={items} />}
    </>
  );
}

function Timeline({ items }: { items: ActivityItem[] }) {
  return (
    <ol className="relative mx-3 border-l border-line pl-4 sm:mx-4">
      {items.map((a, i) => {
        const k = KIND[a.kind] ?? { label: "Evento", dot: "bg-muted" };
        return (
          <li key={i} className="relative pb-4">
            <span className={`absolute -left-[21px] top-1.5 size-2.5 rounded-full ring-4 ring-white ${k.dot}`} aria-hidden />
            <p className="label-caps">
              {k.label} <span className="tnum normal-case tracking-normal">{fmtAgo(a.at)}</span>
            </p>
            <p className="mt-0.5 text-sm">{a.label}</p>
          </li>
        );
      })}
    </ol>
  );
}

export function LiveBadge({ live, generatedAt, checked }: { live: boolean; generatedAt: string; checked: boolean }) {
  if (live)
    return (
      <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.1em] text-verde">
        <span className="live-dot size-2 rounded-full bg-verde" aria-hidden />
        En vivo <span className="tnum font-normal normal-case tracking-normal text-muted">{fmtTime(generatedAt)}</span>
      </span>
    );
  return (
    <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.1em] text-ambar">
      <span className="size-2 rounded-full bg-ambar" aria-hidden />
      {checked ? "Respaldo" : "Conectando"}
      <span className="tnum font-normal normal-case tracking-normal text-muted">datos del {fmtShortDate(generatedAt)}</span>
    </span>
  );
}


const BASEMAP_CREDIT =
  import.meta.env.VITE_BASEMAP === "carto"
    ? "© OpenStreetMap contributors © CARTO"
    : "Esri, HERE, Garmin, © OpenStreetMap contributors";

/** Every source the map draws on: imagery, basemaps and each open data layer in layers.json. */
export function SourcesFooter({ layers, live = [] }: { layers: LayerMeta[]; live?: { id: string; label: string; credit: string; url?: string }[] }) {
  const link = "underline underline-offset-2 hover:text-ink";
  return (
    <footer className="mt-6 border-t border-line px-3 py-4 text-xs leading-relaxed text-muted sm:px-4">
      <p className="label-caps mb-2">Fuentes</p>
      <ul className="space-y-1.5">
        <li>
          <span className="text-ink">Detecciones:</span> modelo de {BRAND_NAME} sobre imágenes{" "}
          <a className={link} href="https://www.planet.com" target="_blank" rel="noopener noreferrer">Planet</a>,{" "}
          <a className={link} href="https://skyfi.com" target="_blank" rel="noopener noreferrer">SkyFi</a> (a través de un aliado con
          acceso licenciado) y radar{" "}
          <a className={link} href="https://sentinels.copernicus.eu/web/sentinel/missions/sentinel-1" target="_blank" rel="noopener noreferrer">
            Copernicus Sentinel-1
          </a>{" "}
          (ESA).
        </li>
        <li>
          <span className="text-ink">Mapa base:</span> {BASEMAP_CREDIT}.
        </li>
        <li>
          <span className="text-ink">Satélite:</span> Esri, Maxar, Earthstar Geographics.
        </li>
        {layers.map((l) => (
          <li key={l.id}>
            <span className="text-ink">{l.short || l.title}:</span>{" "}
            <a href={l.url} target="_blank" rel="noopener noreferrer" className={link}>
              {l.source}
            </a>
            . {l.license}
          </li>
        ))}
        {live.map((l) => (
          <li key={l.id}>
            <span className="text-ink">{l.label}:</span>{" "}
            {l.url ? (
              <a href={l.url} target="_blank" rel="noopener noreferrer" className={link}>
                {l.credit}
              </a>
            ) : (
              l.credit
            )}
            .
          </li>
        ))}
      </ul>
    </footer>
  );
}

/** "Hoy en los ríos": the live summary sentence of the watched rivers (two on phones, three on desktop). */
export function TodayRivers({
  rivers,
  mine,
  feeds,
  onOpen,
}: {
  rivers: ResolvedRiver[];
  mine: Set<string>;
  feeds: Fuentes | null;
  onOpen: (slug: string) => void;
}) {
  if (!feeds) return null;
  const rows = rivers
    .filter((r) => feeds.summary[slugKey(r.slug)])
    .sort((a, b) => Number(mine.has(b.slug)) - Number(mine.has(a.slug)) || b.detections - a.detections)
    .slice(0, 3);
  if (!rows.length) return null;
  return (
    <section className="px-4" aria-labelledby="hoy-rios">
      <h2 id="hoy-rios" className="label-caps mb-1.5">
        Hoy en los ríos
      </h2>
      <ul className="divide-y divide-line rounded-xl bg-panel-2">
        {rows.map((r, i) => (
          <li key={r.slug} className={`flex items-center gap-2 py-1.5 pl-3 pr-1.5 ${i === 2 ? "hidden lg:flex" : ""}`}>
            <p className="line-clamp-2 min-w-0 flex-1 text-xs leading-snug text-ink">{feeds.summary[slugKey(r.slug)]}</p>
            <button
              type="button"
              onClick={() => onOpen(r.slug)}
              className="min-h-11 shrink-0 rounded-lg px-2.5 text-xs font-bold text-rojo hover:bg-white"
              aria-label={`Ver río ${r.name}`}
            >
              Ver río
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
