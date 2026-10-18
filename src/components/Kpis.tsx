import { fmtNum } from "../lib/format";
import type { Totals } from "../types";

export function Kpis({ totals }: { totals: Totals }) {
  const tiles: { label: string; value: number; tone: string }[] = [
    { label: "Detecciones", value: totals.detections, tone: "text-ink" },
    { label: "Dragas con alerta", value: totals.alerting_detections, tone: "text-rojo" },
    { label: "Expedientes", value: totals.expedientes, tone: "text-verde" },
    { label: "Ríos vigilados", value: totals.rivers, tone: "text-cian" },
  ];
  return (
    <dl className="grid grid-cols-4 gap-1 sm:gap-2">
      {tiles.map((t) => (
        <div key={t.label} className="min-w-0 rounded-md border border-line bg-panel/95 px-1.5 py-1.5 sm:px-3 sm:py-2">
          <dd className={`tnum text-lg font-bold leading-none sm:text-2xl ${t.tone}`}>{fmtNum(t.value)}</dd>
          <dt className="mt-1 text-[9.5px] font-semibold uppercase leading-tight tracking-[0.04em] text-muted sm:text-[10.5px] sm:tracking-[0.1em]">
            {t.label}
          </dt>
        </div>
      ))}
    </dl>
  );
}
