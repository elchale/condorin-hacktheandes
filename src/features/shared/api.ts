// Calls the member pages make straight to the Django API (no proxy). Expediente and evento calls
// carry only the token in the path, with credentials omitted; panel calls carry the bearer session.

import { API_URL } from "../../config";
import { clearSession, readSession, saveSession } from "../../lib/storage";
import type { Session } from "../../types";
import type { ApiError, Incident, Page, Panel, Patch, Payload, Status } from "./types";

/** Thrown for any non 2xx answer, carrying the API's error envelope. */
export class ExpedienteError extends Error {
  status: number;
  body: ApiError;
  constructor(status: number, body: ApiError) {
    super(body.message);
    this.status = status;
    this.body = body;
  }
}

const FALLBACK: ApiError = { message: "Algo falló. Inténtalo otra vez.", type: "unknown", field_errors: {} };
const OFFLINE: ApiError = { ...FALLBACK, message: "Sin conexión. Revisa tu internet e inténtalo otra vez.", type: "offline" };

async function call<T>(path: string, method: string, body?: unknown, bearer?: string): Promise<{ status: number; data: T }> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (bearer) headers.Authorization = `Bearer ${bearer}`;
  let res: Response;
  try {
    res = await fetch(API_URL + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      credentials: "omit",
    });
  } catch {
    throw new ExpedienteError(0, OFFLINE);
  }
  const data = await res.json().catch(() => null);
  // A dead bearer session signs the member out everywhere; pages that need one send them to /entrar.
  if (res.status === 401 && bearer && (!data?.type || data.type === "session_invalid") && readSession()?.token === bearer) clearSession();
  if (!res.ok) throw new ExpedienteError(res.status, data?.type ? data : FALLBACK);
  return { status: res.status, data: data as T };
}

const expPath = (token: string) => `/api/v1/expedientes/${encodeURIComponent(token)}`;

/** Opened in a new tab; the token is the whole auth, so a plain link works. */
export const pdfUrl = (token: string) => `${API_URL}${expPath(token)}?formato=pdf`;

export const loadExpediente = (token: string) => call<Payload>(expPath(token), "GET").then((r) => r.data);

export const saveExpediente = (token: string, patch: Patch) => call<Payload>(expPath(token), "PATCH", patch).then((r) => r.data);

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
export const loadMe = (session: string) => call<Panel>("/api/v1/me", "GET", undefined, session).then((r) => r.data);

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
  call<Page<Incident>>(`/api/v1/me/incidentes?page=${page}`, "GET", undefined, session).then((r) => r.data);

/** The member's personal expediente token for one incident (created if they had no alert for it). */
export const expedienteToken = (session: string, incidentId: number) =>
  call<{ token: string }>(`/api/v1/me/incidentes/${incidentId}/expediente`, "POST", {}, session).then((r) => r.data);

export type LinkSignIn = { signedIn: boolean; fresh?: boolean; name?: string; ong?: string };

/**
 * Opening a WhatsApp alert link signs in the member it was sent to (POST /api/v1/auth/enlace, 7 days).
 * An existing session is never replaced, so a forwarded link cannot switch accounts. Never throws.
 */
export async function signInWithLink(token: string): Promise<LinkSignIn> {
  if (readSession()) return { signedIn: true };
  if (!/^[\w-]{16,64}$/.test(token)) return { signedIn: false };
  try {
    const { data } = await call<Session>("/api/v1/auth/enlace", "POST", { token });
    if (!data?.token) return { signedIn: false };
    if (!readSession()) saveSession({ token: data.token, member: data.member, ong: data.ong });
    return { signedIn: true, fresh: true, name: data.member?.name, ong: data.ong?.name };
  } catch {
    return { signedIn: false };
  }
}
