// Calls the member pages make, on the shared client in lib/api.ts. Expediente and evento calls
// carry only the token in the path; panel calls carry the bearer session.

import { API_URL } from "../../config";
import { request } from "../../lib/api";
import type { Incident, Page, Panel, Patch, Payload, Status } from "../../types";

/** Token only calls: the link token in the path is the whole auth, never the bearer session. */
const call = <T>(path: string, method: string, body?: unknown) => request<T>(path, { method, body, auth: false, cache: "no-store" });
/** Panel calls: the bearer session of the member. */
const callAs = <T>(session: string, path: string, method: string, body?: unknown) =>
  request<T>(path, { method, body, token: session, cache: "no-store" });

const expPath = (token: string) => `/api/v1/expedientes/${encodeURIComponent(token)}`;

/** Opened in a new tab; the token is the whole auth, so a plain link works. */
export const pdfUrl = (token: string) => `${API_URL}${expPath(token)}?formato=pdf`;

export const loadExpediente = (token: string) => call<Payload>(expPath(token), "GET").then((r) => r.data);

/** Recording filings needs the member's code session, so that patch also carries the stored bearer. */
export const saveExpediente = (token: string, patch: Patch) =>
  ("filings" in patch
    ? request<Payload>(expPath(token), { method: "PATCH", body: patch, cache: "no-store" })
    : call<Payload>(expPath(token), "PATCH", patch)
  ).then((r) => r.data);

export type SendResult =
  | { status: 202; data: { status: "code_sent"; phone_hint: string; expires_in: number } }
  | { status: 200; data: Payload };

/** `{}` asks for the WhatsApp code (202); `{code}` confirms (200 with the final expediente). */
export const sendExpediente = (token: string, code?: string) =>
  call<SendResult["data"]>(`${expPath(token)}/enviar`, "POST", code ? { code } : {}) as Promise<SendResult>;

export type Evento = {
  member: { name: string; first_name: string };
  ong: { name: string };
  incident: Payload["incident"];
  expediente: null | { status: Status; status_label: string; folio: string | null; missing: number; updated_by: string | null };
};

export const loadEvento = (token: string) => call<Evento>(`/api/v1/eventos/${encodeURIComponent(token)}`, "GET").then((r) => r.data);

/** The member panel (`PanelView`) with the first page of incidents, for the bearer session. */
export const loadMe = (session: string) => callAs<Panel>(session, "/api/v1/me", "GET").then((r) => r.data);

/** The page number in a DRF `next` link (the link itself may name another host or scheme). */
export function pageOf(link: string | null): number | null {
  if (!link) return null;
  try {
    const n = Number(new URL(link).searchParams.get("page"));
    return Number.isInteger(n) && n > 0 ? n : null;
  } catch {
    return null;
  }
}

/** One more page of the member's incidents ("Ver más"). */
export const loadIncidents = (session: string, page: number) =>
  callAs<Page<Incident>>(session, `/api/v1/me/incidentes?page=${page}`, "GET").then((r) => r.data);

/** The member's personal expediente token for one incident (created if they had no alert for it). */
export const expedienteToken = (session: string, incidentId: number) =>
  callAs<{ token: string }>(session, `/api/v1/me/incidentes/${incidentId}/expediente`, "POST", {}).then((r) => r.data);
