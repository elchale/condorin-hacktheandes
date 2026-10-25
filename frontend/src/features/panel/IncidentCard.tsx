import { dragas } from "../shared/format";
import { Icon } from "../shared/Icon";
import type { Incident, TriageReason, TriageStatus } from "../../types";
import { TriageBar } from "./TriageBar";
import { TRIAGE_STYLE } from "./triage";

const STATUS_STYLE = {
  none: "bg-rojo/10 text-rojo-3",
  draft: "bg-ambar/10 text-amber-800",
  ready: "bg-night text-ink ring-1 ring-line",
  filed: "bg-verde/10 text-green-800",
} as const;

const primary =
  "inline-flex w-full items-center justify-center gap-2 rounded-xl bg-rojo px-5 py-3.5 font-bold text-white hover:bg-rojo-2 sm:w-auto";
const outline =
  "inline-flex w-full items-center justify-center gap-2 rounded-xl bg-panel px-5 py-3.5 font-bold text-ink ring-2 ring-inset ring-ink hover:bg-ink hover:text-white sm:w-auto";

/** What the member can do next with this incident, as one sentence and one button. */
function nextStep(e: Incident["expediente"]) {
  if (!e) return { note: "Nadie de tu ONG ha empezado la denuncia.", button: "Crear expediente", style: primary };
  if (e.status === "draft") {
    const note = e.missing
      ? `Borrador. ${e.missing === 1 ? "Falta 1 dato" : `Faltan ${e.missing} datos`}.`
      : "Borrador listo. Solo falta revisarlo y confirmarlo.";
    return { note, button: "Continuar expediente", style: primary };
  }
  if (e.status === "ready") {
    return {
      note: `${e.folio} listo. Preséntalo ante ${e.authorities.join(" y ") || "las autoridades"} y registra el número.`,
      button: "Presentar a las autoridades",
      style: primary,
    };
  }
  return { note: `${e.folio} presentado ante ${e.filings === 1 ? "1 autoridad" : `${e.filings} autoridades`}.`, button: "Ver expediente", style: outline };
}

type Props = {
  incident: Incident;
  /** Opens the member's personal token for this incident on the expediente or the evento page. */
  onOpen: (incident: Incident, to: "expediente" | "evento") => void;
  busy?: boolean;
  /** Members can decide what an incident is; observers only see the decision. */
  canAct?: boolean;
  onTriage?: (incident: Incident, status: TriageStatus, reason?: TriageReason) => void;
  onClearTriage?: (incident: Incident) => void;
};

export function IncidentCard({ incident, onOpen, busy = false, canAct = false, onTriage, onClearTriage }: Props) {
  const e = incident.expediente;
  const step = nextStep(e);
  const triage = incident.triage;
  // The ONG said the model was wrong: no denuncia to start until they undo it (the API refuses it too).
  const rejected = triage?.status === "false_positive";
  const [crop, ...more] = incident.crops;

  return (
    <article className={`flex h-full flex-col overflow-hidden rounded-3xl bg-panel ring-1 ring-line ${rejected ? "opacity-75" : ""}`}>
      <div className="relative aspect-[16/9] bg-panel-2">
        {crop ? (
          // Signed GCS links that expire: shown as is, lazily.
          <img src={crop} alt={`Recorte satelital de la detección en el río ${incident.river.name}`} className="size-full object-cover" loading="lazy" />
        ) : (
          <div className="flex size-full flex-col items-center justify-center gap-2 text-muted">
            <Icon name="satellite" className="size-8" />
            <span className="text-sm">La imagen de evidencia se está preparando</span>
          </div>
        )}
        {more.length > 0 && (
          <span className="absolute bottom-3 right-3 rounded-full bg-ink/75 px-3 py-1 text-xs font-semibold text-white">
            {more.length === 1 ? "1 recorte más" : `${more.length} recortes más`}
          </span>
        )}
      </div>

      <div className="flex flex-1 flex-col p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-lg font-bold">Río {incident.river.name}</h3>
          <div className="flex flex-wrap gap-2">
            {triage && (
              <span className={`rounded-full px-3 py-1 text-xs font-bold ${TRIAGE_STYLE[triage.status]}`}>{triage.status_label}</span>
            )}
            {!rejected && (
              <span className={`rounded-full px-3 py-1 text-xs font-bold ${STATUS_STYLE[e?.status ?? "none"]}`}>
                {e ? e.status_label : "Sin expediente"}
              </span>
            )}
          </div>
        </div>
        <p className="mt-1 text-sm text-muted">
          {dragas(incident.detections)} · {incident.captured_at_label} · {incident.satellite}
        </p>
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          <dt className="text-muted">Confianza</dt>
          <dd className="font-semibold tabular-nums">{Math.round(incident.top_confidence * 100)}%</dd>
          <dt className="text-muted">Ubicación</dt>
          <dd className="min-w-0 break-words tabular-nums">
            {incident.lat}, {incident.lon}
            <span className="block text-muted">UTM {incident.utm}</span>
          </dd>
          {incident.river.protected_area && (
            <>
              <dt className="text-muted">Área protegida</dt>
              <dd>{incident.river.protected_area}</dd>
            </>
          )}
        </dl>

        {canAct && onTriage && onClearTriage ? (
          <TriageBar incident={incident} disabled={busy} onSet={onTriage} onClear={onClearTriage} />
        ) : (
          triage && (
            <p className="mt-4 text-sm text-muted">
              Tu ONG la marcó como «{triage.status_label}»{triage.reason_label ? ` (${triage.reason_label})` : ""}.
            </p>
          )
        )}

        <p className="mt-4 text-sm">
          {rejected ? "Marcada como no es una draga. No hace falta una denuncia." : step.note}
        </p>
        <div className="mt-auto flex flex-col gap-3 pt-4 sm:flex-row sm:flex-wrap">
          {!rejected && (
            <button type="button" disabled={busy} onClick={() => onOpen(incident, "expediente")} className={`${step.style} disabled:opacity-60`}>
              {step.button}
              <Icon name="arrow" className="size-5" />
            </button>
          )}
          <button
            type="button"
            disabled={busy}
            onClick={() => onOpen(incident, "evento")}
            className="inline-flex min-h-11 items-center justify-center px-2 py-3 font-semibold text-rojo-3 underline underline-offset-2 disabled:opacity-60"
          >
            Ver evento
          </button>
        </div>
      </div>
    </article>
  );
}
