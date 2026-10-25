import type { TriageReason, TriageStatus } from "../../types";

export const TRIAGE_LABEL: Record<TriageStatus, string> = {
  confirmed: "Es una draga",
  false_positive: "No es una draga",
  verified_field: "Verificada en campo",
};

export const REASON_LABEL: Record<TriageReason, string> = {
  boat: "Bote o lancha",
  sandbar: "Banco de arena o sombra",
  other: "Otra cosa",
};

export const TRIAGE_STYLE: Record<TriageStatus, string> = {
  confirmed: "bg-rojo/10 text-rojo-3",
  false_positive: "bg-panel-2 text-muted",
  verified_field: "bg-verde/10 text-green-800",
};
