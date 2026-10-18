import { PERIODS, type Period } from "../config";
import { fmtAgo, fmtNum } from "../lib/format";
import type { Totals } from "../types";

/** One plain sentence that says what the map shows, then the period in words. */
export function Headline({ period }: { period: Period }) {
  return (
    <div className="px-4">
      <h1 className="text-[17px] font-extrabold leading-snug tracking-tight lg:text-lg">Minería ilegal detectada en la Amazonía peruana</h1>
      <p className="mt-0.5 text-[13px] text-muted">
        Mostrando: <strong className="font-bold text-ink">{period.words}</strong>
      </p>
    </div>
  );
}

/** At most three numbers, with plain labels. */
export function Kpis({ detections, alertsSent, ha }: { detections: number; alertsSent: number; ha: number }) {
  const tiles = [
    { label: "Dragas detectadas", value: detections, tone: "text-rojo" },
    { label: "Alertas enviadas por WhatsApp", value: alertsSent, tone: "text-ink" },
    { label: "Hectáreas de huella minera", value: ha, tone: "text-ink" },
  ];
  return (
    <dl className="grid grid-cols-3 gap-2 px-4">
      {tiles.map((t) => (
        <div key={t.label} className="flex min-w-0 flex-col-reverse justify-end rounded-2xl bg-panel-2 px-2.5 py-2">
          <dt className="mt-1 text-[11px] font-medium leading-tight text-muted">{t.label}</dt>
          <dd className={`tnum text-xl font-extrabold leading-none tracking-tight ${t.tone}`}>{fmtNum(t.value)}</dd>
        </div>
      ))}
    </dl>
  );
}

/** The single time control: a labelled segmented control. */
export function PeriodSelector({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  return (
    <fieldset className="px-4">
      <legend className="label-caps mb-1.5">Periodo</legend>
      <div className="grid grid-cols-4 rounded-xl bg-panel-2 p-1" role="radiogroup" aria-label="Periodo">
        {PERIODS.map((p) => {
          const on = p.id === value;
          return (
            <button
              key={p.id}
              type="button"
              role="radio"
              aria-checked={on}
              onClick={() => onChange(p.id)}
              className={`min-h-10 whitespace-nowrap rounded-lg px-1 text-[13px] font-bold transition-colors ${
                on ? "bg-white text-ink shadow-[0_1px_3px_rgba(24,24,27,.18)]" : "text-muted hover:text-ink"
              }`}
            >
              {p.label}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

/** What each color means, in words. */
export function Legend({ footprint, anp, extra = [] }: { footprint: boolean; anp: boolean; extra?: { id: string; label: string; color: string }[] }) {
  return (
    <ul className="space-y-1.5 text-[13px] leading-snug text-ink" aria-label="Leyenda">
      <li className="flex items-center gap-2">
        <span className="size-3.5 shrink-0 rounded-full bg-rojo ring-2 ring-white shadow-[0_0_0_1px_rgba(0,0,0,.25)]" aria-hidden />
        <span>
          <strong className="font-bold">Puntos rojos:</strong> dragas detectadas por satélite
        </span>
      </li>
      {footprint && (
        <li className="flex items-center gap-2">
          <span className="size-3.5 shrink-0 rounded-[4px] bg-huella ring-1 ring-yellow-700/60" aria-hidden />
          <span>
            <strong className="font-bold">Amarillo:</strong> huella minera acumulada (Amazon Mining Watch)
          </span>
        </li>
      )}
      {anp && (
        <li className="flex items-center gap-2">
          <span className="size-3.5 shrink-0 rounded-[4px] border-2 border-[#22c55e] bg-[#22c55e]/10" aria-hidden />
          <span>
            <strong className="font-bold">Verde:</strong> áreas naturales protegidas
          </span>
        </li>
      )}
      {extra.map((m) => (
        <li key={m.id} className="flex items-center gap-2">
          <span className="size-3.5 shrink-0 rounded-[4px]" style={{ background: m.color }} aria-hidden />
          <span>{m.label}</span>
        </li>
      ))}
    </ul>
  );
}

/** One line footer: freshness plus the "people are using it" counters. */
export function UpdatedLine({ generatedAt, live, totals }: { generatedAt: string; live: boolean; totals: Totals }) {
  const bits = [`Actualizado ${fmtAgo(generatedAt)}${live ? "" : " (copia guardada)"}`];
  if (totals.users != null) bits.push(`${fmtNum(totals.users)} personas registradas`);
  if (totals.alerts_opened != null) bits.push(`${fmtNum(totals.alerts_opened)} alertas abiertas`);
  return <p className="tnum px-4 text-xs text-muted">{bits.join(" · ")}</p>;
}
