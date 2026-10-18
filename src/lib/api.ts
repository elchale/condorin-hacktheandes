// The one fetch wrapper for the Django API (no proxy). Stable API for every page:
//   api<T>(path, { method, body, headers, auth, token, cache, timeout, signal }) -> Promise<T>
//   request<T>(path, opts) -> Promise<{ status, data }> (when the status code matters, e.g. 200 vs 202)
//   apiGet<T>(path, opts), apiPost<T>(path, body, opts)
//   ApiError { message, type, status, fieldErrors }, friendlyError(e) -> Spanish text
// Errors follow the envelope {"message", "type", "field_errors"}; `message` is always readable Spanish.
// Default timeout 20 s. Cookies are never sent (credentials: "omit"): auth is the bearer token, or the
// link token in the path for evento and expediente pages.

import { API_URL, LIVE_TIMEOUT_MS } from "../config";
import type { Mapa, Session } from "../types";
import { clearToken, getToken } from "./session";

const GENERIC = "Algo falló. Inténtalo otra vez.";

const FRIENDLY: Record<string, string> = {
  code_invalid: "El código no es correcto. Revisa el mensaje de WhatsApp e inténtalo otra vez.",
  code_expired: "El código venció. Pide uno nuevo.",
  code_too_soon: "Ya te enviamos un código hace poco. Espera unos segundos y vuelve a pedirlo.",
  session_invalid: "Tu sesión terminó. Vuelve a entrar.",
  network: "No pudimos conectar. Revisa tu señal e inténtalo otra vez.",
  timeout: "La conexión está muy lenta. Inténtalo otra vez.",
};

export class ApiError extends Error {
  type: string;
  status: number;
  /** Field name to its messages (the API sends lists; a lone string is wrapped). */
  fieldErrors: Record<string, string[]>;
  constructor(message: string, type: string, status: number, fieldErrors: Record<string, string[] | string> = {}) {
    super(message || FRIENDLY[type] || GENERIC);
    this.type = type;
    this.status = status;
    this.fieldErrors = Object.fromEntries(Object.entries(fieldErrors).map(([k, v]) => [k, Array.isArray(v) ? v : [String(v)]]));
  }
}

/** Spanish message for the user: known types first, then the API message, then a generic one. */
export function friendlyError(e: unknown): string {
  if (e instanceof ApiError) return FRIENDLY[e.type] ?? (e.message || GENERIC);
  return GENERIC;
}

export type ApiOptions = {
  method?: string;
  /** Sent as JSON when it is not a string, FormData or Blob. */
  body?: unknown;
  headers?: Record<string, string>;
  /** Send the stored bearer token (default: true when signed in). False for token only (link) calls. */
  auth?: boolean;
  /** An explicit bearer token, sent instead of the stored one. */
  token?: string;
  cache?: RequestCache;
  /** Milliseconds, default 20000. */
  timeout?: number;
  signal?: AbortSignal;
};

export async function request<T>(path: string, opts: ApiOptions = {}): Promise<{ status: number; data: T }> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), opts.timeout ?? 20000);
  const onAbort = () => ctrl.abort();
  if (opts.signal?.aborted) ctrl.abort();
  else opts.signal?.addEventListener("abort", onAbort, { once: true });
  const bearer = opts.token ?? (opts.auth === false ? null : getToken());
  const headers: Record<string, string> = { Accept: "application/json", ...(bearer ? { Authorization: `Bearer ${bearer}` } : {}), ...opts.headers };
  let body: BodyInit | undefined;
  if (opts.body !== undefined) {
    if (typeof opts.body === "string" || opts.body instanceof FormData || opts.body instanceof Blob) body = opts.body as BodyInit;
    else {
      body = JSON.stringify(opts.body);
      headers["Content-Type"] = "application/json";
    }
  }
  let res: Response;
  try {
    res = await fetch(API_URL + path, {
      method: opts.method ?? (body ? "POST" : "GET"),
      headers,
      body,
      cache: opts.cache,
      credentials: "omit",
      signal: ctrl.signal,
    });
  } catch (e) {
    const aborted = e instanceof DOMException && e.name === "AbortError";
    throw new ApiError("", aborted ? "timeout" : "network", 0);
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener("abort", onAbort);
  }
  const data = res.status === 204 ? {} : await res.json().catch(() => null);
  if (!res.ok) {
    // A dead bearer session signs the member out everywhere (only the session that was sent, so a
    // newer sign in from another tab survives); pages that need one send them to /entrar.
    if (res.status === 401 && bearer && (!data?.type || data.type === "session_invalid") && getToken() === bearer) clearToken();
    throw new ApiError(data?.type ? data.message ?? "" : "", data?.type ?? `http_${res.status}`, res.status, data?.field_errors ?? {});
  }
  return { status: res.status, data: data as T };
}

export const api = <T>(path: string, opts: ApiOptions = {}): Promise<T> => request<T>(path, opts).then((r) => r.data);

export const apiGet = <T>(path: string, opts: Omit<ApiOptions, "method" | "body"> = {}) => api<T>(path, { ...opts, method: "GET" });
export const apiPost = <T>(path: string, body?: unknown, opts: Omit<ApiOptions, "method" | "body"> = {}) =>
  api<T>(path, { ...opts, method: "POST", body: body ?? {} });

function looksLikeMapa(x: unknown): x is Mapa {
  const m = x as Mapa;
  return !!m && typeof m === "object" && !!m.totals && !!m.detections && Array.isArray(m.detections.features);
}

/** Live map payload (Data contract A). Sends the token when present so `mine` comes back; drops a dead token once. */
export async function fetchMapa(): Promise<Mapa> {
  const hadToken = !!getToken();
  try {
    const data = await api<unknown>("/api/v1/mapa", { timeout: LIVE_TIMEOUT_MS });
    if (!looksLikeMapa(data)) throw new ApiError("", "bad_payload", 200);
    return data;
  } catch (e) {
    if (hadToken && e instanceof ApiError && e.status === 401) {
      clearToken();
      return fetchMapa();
    }
    throw e;
  }
}

export const requestCode = (phone: string, consent: boolean) =>
  apiPost<{ phone: string; pending: string }>("/api/v1/auth/codigo", { phone, consent }, { auth: false });

export const signIn = (pending: string, code: string) =>
  apiPost<Omit<Session, "token"> & { token: string }>("/api/v1/auth/entrar", { pending, code }, { auth: false });


/**
 * Sign out: tell the API to end this session (POST /api/v1/auth/salir bumps the session version, so the
 * token dies everywhere), then forget it here. The local session is cleared even when the call fails.
 */
export async function signOut(): Promise<void> {
  const token = getToken();
  if (token) {
    try {
      await apiPost("/api/v1/auth/salir", {}, { token, timeout: 5000 });
    } catch {
      /* offline, already dead, or an API without the endpoint yet: the local session goes anyway */
    }
  }
  clearToken();
}
