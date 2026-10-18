import { BRAND_NAME } from "../config";
import { fmtAgo, fmtMonth, fmtNum, fmtPct, fmtShortDate, fmtTime } from "../lib/format";
import type { ActivityItem, DetectionFeature, LayerMeta } from "../types";
import type { ResolvedRiver } from "../map/types";

export type DetFilter = "todas" | "alerta" | "mias";

export function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={`min-h-11 shrink-0 rounded-full border px-3 text-[13px] font-semibold ${
        on ? "border-cian bg-cian/10 text-cian" : "border-line text-muted hover:text-ink"
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

export function LayersTab(props: {
  metas: LayerMeta[];
  active: Set<string>;
  status: Record<string, LayerStatus>;
  onToggle: (m: LayerMeta) => void;
  saveData: boolean;
}) {
  const { metas, active, status, onToggle, saveData } = props;
  return (
    <div className="px-3 sm:px-4">
      {saveData && <p className="mb-2 text-xs text-ambar">Modo ahorro: las capas se descargan solo cuando las activas.</p>}
      <ul className="space-y-2">
        {metas.map((m) => {
          const on = active.has(m.id);
          const st = status[m.id];
          return (
            <li key={m.id}>
              <button
                type="button"
                role="switch"
                aria-checked={on}
                onClick={() => onToggle(m)}
                className="flex w-full items-start gap-3 rounded-lg border border-line bg-panel-2/60 p-3 text-left hover:bg-panel-2"
              >
                <span className="mt-1 size-3 shrink-0 rounded-sm" style={{ background: m.color }} aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold">{m.title}</span>
                  <span className="mt-0.5 block text-xs text-muted">
                    {m.source}, {m.year}. {m.license}.
                  </span>
                  <span className="tnum mt-1 block text-xs text-muted">
                    {fmtNum(m.features)} elementos, {Math.max(1, Math.round(m.bytes_gzip / 1024))} KB
                    {st === "loading" && <span className="text-cian"> · cargando</span>}
                    {st === "error" && <span className="text-rojo"> · no se pudo cargar, toca para reintentar</span>}
                  </span>
                </span>
                <span className={`relative mt-0.5 h-6 w-10 shrink-0 rounded-full transition-colors ${on ? "bg-cian" : "bg-line"}`} aria-hidden>
                  <span className={`absolute top-0.5 size-5 rounded-full bg-night transition-transform ${on ? "translate-x-[18px]" : "translate-x-0.5"}`} />
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

const KIND: Record<string, { label: string; dot: string }> = {
  image: { label: "Escena", dot: "bg-cian" },
  alert: { label: "Alerta", dot: "bg-rojo" },
  expediente_opened: { label: "Expediente", dot: "bg-ambar" },
  expediente_filed: { label: "Presentado", dot: "bg-verde" },
};

export function ActivityList({ items }: { items: ActivityItem[] }) {
  if (items.length === 0) return <p className="px-4 py-6 text-sm text-muted">Sin actividad reciente.</p>;
  return (
    <ol className="relative mx-3 border-l border-line pl-4 sm:mx-4">
      {items.map((a, i) => {
        const k = KIND[a.kind] ?? { label: "Evento", dot: "bg-muted" };
        return (
          <li key={i} className="relative pb-4">
            <span className={`absolute -left-[21px] top-1.5 size-2.5 rounded-full ring-4 ring-panel ${k.dot}`} aria-hidden />
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

export function Scrubber({ months, value, onChange }: { months: string[]; value: number; onChange: (i: number) => void }) {
  if (months.length < 2) return null;
  const last = value >= months.length - 1;
  return (
    <div className="flex items-center gap-3 px-3 sm:px-4">
      <label htmlFor="scrub" className="label-caps w-24 shrink-0">
        {last ? "Todo hasta" : "Hasta"}
        <span className="tnum block text-[13px] font-bold normal-case tracking-normal text-ink">{fmtMonth(months[value])}</span>
      </label>
      <input
        id="scrub"
        className="scrub"
        type="range"
        min={0}
        max={months.length - 1}
        step={1}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-valuetext={fmtMonth(months[value])}
      />
    </div>
  );
}

export function LiveBadge({ live, generatedAt, checked }: { live: boolean; generatedAt: string; checked: boolean }) {
  if (live)
    return (
      <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.1em] text-cian">
        <span className="live-dot size-2 rounded-full bg-cian" aria-hidden />
        En vivo <span className="tnum font-normal normal-case tracking-normal text-muted">{fmtTime(generatedAt)}</span>
      </span>
    );
  return (
    <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.1em] text-ambar">
      <span className="size-2 rounded-full bg-ambar" aria-hidden />
      {checked ? "Sin conexión" : "Conectando"}
      <span className="tnum font-normal normal-case tracking-normal text-muted">datos del {fmtShortDate(generatedAt)}</span>
    </span>
  );
}

export function SourcesFooter({ layers }: { layers: LayerMeta[] }) {
  return (
    <footer className="mt-6 border-t border-line px-3 py-4 text-[11px] leading-relaxed text-muted sm:px-4">
      <p>
        Detecciones de {BRAND_NAME} sobre imágenes Planet y Copernicus Sentinel-1. Mapa base: Esri, HERE, Garmin, © OpenStreetMap contributors.
        Satélite: Esri, Maxar, Earthstar Geographics.
      </p>
      {layers.map((l) => (
        <p key={l.id} className="mt-1">
          {l.short || l.title}:{" "}
          <a href={l.url} target="_blank" rel="noopener noreferrer" className="underline">
            {l.source}
          </a>{" "}
          ({l.license})
        </p>
      ))}
    </footer>
  );
}
