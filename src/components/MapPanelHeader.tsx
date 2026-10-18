import { FIRST_YEAR, LAST_YEAR } from "../config";
import { addDays, shortDay, todayLima, type TimeWindow } from "../lib/days";
import { fmtAgo, fmtNum } from "../lib/format";
import type { Totals } from "../types";

/** One plain sentence that says what the map shows, then the period in words. */
export function Headline({ words }: { words: string }) {
  return (
    <div className="px-4">
      <h1 className="text-[17px] font-extrabold leading-snug tracking-tight lg:text-lg">Minería ilegal detectada en la Amazonía peruana</h1>
      <p className="mt-0.5 text-[13px] text-muted">
        Mostrando: <strong className="font-bold text-ink">{words}</strong>
      </p>
    </div>
  );
}

/** At most three numbers, with plain labels. */
export function Kpis({ detections, alertsSent, ha, onDetections }: { detections: number; alertsSent: number; ha: number; onDetections?: () => void }) {
  const tiles = [
    { label: "Dragas detectadas", value: detections, tone: "text-rojo" },
    { label: "Alertas enviadas por WhatsApp", value: alertsSent, tone: "text-ink" },
    { label: `Hectáreas de huella minera, ${FIRST_YEAR} a ${LAST_YEAR}`, value: ha, tone: "text-ink" },
  ];
  return (
    <dl className="grid grid-cols-3 gap-2 px-4">
      {tiles.map((t, i) => (
        <div
          key={t.label}
          {...(i === 0 && onDetections
            ? {
                role: "button",
                tabIndex: 0,
                title: "Ver en el mapa",
                onClick: onDetections,
                onKeyDown: (e: { key: string; preventDefault: () => void }) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onDetections();
                  }
                },
              }
            : {})}
          className={`flex min-w-0 flex-col-reverse justify-end rounded-2xl bg-panel-2 px-2.5 py-2 ${i === 0 && onDetections ? "cursor-pointer hover:bg-zinc-200/70" : ""}`}
        >
          <dt className="mt-1 text-[11px] font-medium leading-tight text-muted">{t.label}</dt>
          <dd className={`tnum text-xl font-extrabold leading-none tracking-tight ${t.tone}`}>{fmtNum(t.value)}</dd>
        </div>
      ))}
    </dl>
  );
}

const stepBtn =
  "min-h-11 whitespace-nowrap rounded-xl bg-panel-2 px-2 text-[13px] font-bold text-ink hover:bg-zinc-200/70 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-panel-2";

/**
 * "Viaje en el tiempo": the single time control. The map shows the 3 days ending on the chosen day
 * (today by default). Day buttons step one day, the native date input jumps, "Hoy" comes back.
 */
export function TimeTravel({ win, today, onChange }: { win: TimeWindow; today: string; onChange: (day: string) => void }) {
  const end = win.to;
  return (
    <div className="px-4" role="group" aria-labelledby="viaje-titulo">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <p id="viaje-titulo" className="label-caps">
          Viaje en el tiempo
        </p>
        <button
          type="button"
          aria-pressed={win.isToday}
          onClick={() => onChange(today)}
          className={`min-h-9 rounded-full px-3.5 text-xs font-bold ${win.isToday ? "bg-ink text-white" : "bg-rojo text-white hover:bg-rojo/90"}`}
        >
          {win.isToday ? "Hoy" : "Volver a hoy"}
        </button>
      </div>
      <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] gap-1.5">
        <button type="button" className={stepBtn} onClick={() => onChange(addDays(end, -1))} aria-label="Día anterior">
          <span aria-hidden>‹ </span>Día anterior
        </button>
        <input
          type="date"
          value={end}
          min={`${FIRST_YEAR}-01-01`}
          max={today}
          onChange={(e) => {
            const v = (e.currentTarget as HTMLInputElement).value;
            if (/^\d{4}-\d{2}-\d{2}$/.test(v)) onChange(v > today ? today : v);
          }}
          aria-label="Elegir día"
          className="tnum min-h-11 w-full min-w-0 rounded-xl border border-line bg-white px-1 text-[13px] font-bold text-ink"
        />
        <button type="button" className={stepBtn} disabled={end >= today} onClick={() => onChange(addDays(end, 1))} aria-label="Día siguiente">
          Día siguiente<span aria-hidden> ›</span>
        </button>
      </div>
    </div>
  );
}

/** Days that have detections, newest first, each a button that travels there. A dot marks them. */
export function DataDays({ days, win, onPick }: { days: { day: string; n: number }[]; win: TimeWindow; onPick: (day: string) => void }) {
  if (!days.length) return null;
  const year = Number(todayLima().slice(0, 4));
  return (
    <div className="px-4">
      <p className="mb-1 text-[11px] font-medium text-muted">Días con detecciones (toca uno para ir)</p>
      <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1">
        {days.map(({ day, n }) => {
          const on = day >= win.from && day <= win.to;
          return (
            <button
              key={day}
              type="button"
              aria-pressed={on}
              onClick={() => onPick(day)}
              className={`tnum flex min-h-9 shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-xs font-semibold ${
                on ? "border-ink bg-ink text-white" : "border-line text-ink hover:bg-panel-2"
              }`}
            >
              <span className="size-2 rounded-full bg-rojo" aria-hidden />
              {shortDay(day, Number(day.slice(0, 4)) !== year)}
              <span className={on ? "text-white/75" : "text-muted"}>({n})</span>
            </button>
          );
        })}
      </div>
    </div>
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
            <strong className="font-bold">Amarillo:</strong> Huella minera acumulada {FIRST_YEAR} a {LAST_YEAR} (Amazon Mining Watch)
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
