import { useState } from "react";
import type { Incident, TriageReason, TriageStatus } from "../../types";
import { REASON_LABEL, TRIAGE_LABEL } from "./triage";

type Props = {
  incident: Incident;
  disabled?: boolean;
  onSet: (incident: Incident, status: TriageStatus, reason?: TriageReason) => void;
  onClear: (incident: Incident) => void;
};

const chip = "min-h-11 rounded-xl px-3 py-2 text-sm font-semibold ring-1 ring-inset disabled:opacity-60";
const idle = "bg-panel text-ink ring-line hover:bg-panel-2";
const active = "bg-ink text-white ring-ink";

/** The ONG's decision on one incident, for members who can act: real, not a dredge (and why) or verified in the field. */
export function TriageBar({ incident, disabled = false, onSet, onClear }: Props) {
  const current = incident.triage?.status ?? null;
  // Asking "why" after tapping "No es una draga", before anything is sent.
  const [asking, setAsking] = useState(false);

  return (
    <div className="mt-4" role="group" aria-label="¿Qué es esta detección?">
      <p className="text-sm font-semibold">¿Qué es esto?</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {(["confirmed", "verified_field"] as const).map((status) => (
          <button
            key={status}
            type="button"
            disabled={disabled}
            aria-pressed={current === status}
            onClick={() => {
              setAsking(false);
              onSet(incident, status);
            }}
            className={`${chip} ${current === status ? active : idle}`}
          >
            {TRIAGE_LABEL[status]}
          </button>
        ))}
        <button
          type="button"
          disabled={disabled}
          aria-pressed={current === "false_positive" || asking}
          aria-expanded={asking}
          onClick={() => setAsking((v) => !v)}
          className={`${chip} ${current === "false_positive" || asking ? active : idle}`}
        >
          {TRIAGE_LABEL.false_positive}
        </button>
        {current && (
          <button
            type="button"
            disabled={disabled}
            onClick={() => {
              setAsking(false);
              onClear(incident);
            }}
            className="min-h-11 px-2 text-sm font-semibold text-rojo-3 underline underline-offset-2 disabled:opacity-60"
          >
            Deshacer
          </button>
        )}
      </div>
      {asking && (
        <div className="mt-3">
          <p className="text-sm text-muted">¿Qué era?</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {(Object.keys(REASON_LABEL) as TriageReason[]).map((reason) => (
              <button
                key={reason}
                type="button"
                disabled={disabled}
                onClick={() => {
                  setAsking(false);
                  onSet(incident, "false_positive", reason);
                }}
                className={`${chip} ${incident.triage?.reason === reason ? active : idle}`}
              >
                {REASON_LABEL[reason]}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
