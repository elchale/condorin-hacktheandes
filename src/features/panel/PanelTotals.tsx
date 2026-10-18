import type { Panel } from "../shared/types";

export function PanelTotals({ totals }: { totals: Panel["totals"] }) {
  const cards = [
    { label: "Sin expediente", value: totals.without_expediente, tone: "text-red-400" },
    { label: "En borrador", value: totals.draft, tone: "text-ambar" },
    { label: "Listos para presentar", value: totals.ready, tone: "text-ink" },
    { label: "Presentados", value: totals.filed, tone: "text-verde" },
  ];
  return (
    <dl className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
      {cards.map(({ label, value, tone }) => (
        <div key={label} className="rounded-3xl bg-panel p-4 ring-1 ring-line sm:p-5">
          <dt className="text-sm text-muted">{label}</dt>
          <dd className={`mt-1 text-3xl font-black tabular-nums ${tone}`}>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
