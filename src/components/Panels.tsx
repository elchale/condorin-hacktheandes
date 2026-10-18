import { BRAND_NAME } from "../config";
import { fmtAgo, fmtNum, fmtPct, fmtShortDate, fmtTime } from "../lib/format";
import type { ActivityItem, DetectionFeature, LayerMeta } from "../types";
import { DEFAULT_LAYERS, layerMinZoom, type ResolvedRiver } from "../map/types";

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
        <p className="px-4 py-6 text-sm text-muted">
          {filter === "mias" && !props.mineReady
            ? "Conectando para ver los ríos de tu ONG."
            : "No hay detecciones en este periodo."}
        </p>
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
                      <span className="tnum shrink-0 text-xs text-muted">{fmtShortDate(d.captured_at)}</span>
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

export function RiverList({ rivers, mine, onPick }: { rivers: ResolvedRiver[]; mine: Set<string>; onPick: (r: ResolvedRiver) => void }) {
  return (
    <ul className="space-y-2 px-3 sm:px-4">
      {rivers.map((r) => (
        <li key={r.slug}>
          <button
            type="button"
            onClick={() => onPick(r)}
            className={`w-full rounded-lg border bg-panel-2/60 p-3 text-left hover:bg-panel-2 ${mine.has(r.slug) ? "border-cian/60" : "border-line"}`}
          >
            <span className="flex items-baseline justify-between gap-2">
              <span className="font-bold">Río {r.name}</span>
              {mine.has(r.slug) && <span className="label-caps !text-cian">Tu ONG</span>}
            </span>
            <span className="mt-0.5 block text-xs text-muted">{[r.region, r.province].filter(Boolean).join(", ")}</span>
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
                {r.last_captured_at ? fmtShortDate(r.last_captured_at) : "Ninguna"}
              </span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export type LayerStatus = "loading" | "error" | "ready";

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
}) {
  const { metas, active, status, onToggle, saveData, onToggleSave } = props;
  const main = metas.filter((m) => DEFAULT_LAYERS.includes(m.id));
  const more = metas.filter((m) => !DEFAULT_LAYERS.includes(m.id));
  const moreOn = more.some((m) => active.has(m.id));
  return (
    <div className="px-4">
      {saveData && <SaveNote>Las capas se descargan solo cuando las activas.</SaveNote>}
      <ul className="space-y-2">
        {main.map((m) => (
          <LayerRow key={m.id} m={m} on={active.has(m.id)} st={status[m.id]} onToggle={onToggle} />
        ))}
      </ul>
      {more.length > 0 && (
        <details className="group mt-3" open={moreOn}>
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between rounded-xl px-1 text-sm font-bold [&::-webkit-details-marker]:hidden">
            Más capas ({more.length})
            <span className="text-muted transition-transform group-open:rotate-180" aria-hidden>
              ▾
            </span>
          </summary>
          <ul className="mt-1 space-y-2">
            {more.map((m) => (
              <LayerRow key={m.id} m={m} on={active.has(m.id)} st={status[m.id]} onToggle={onToggle} />
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
export function SourcesFooter({ layers }: { layers: LayerMeta[] }) {
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
      </ul>
    </footer>
  );
}
