// Fetch wrapper for the Django API. Stable API for every page:
//   api<T>(path, { method, body, headers, auth, timeout, signal }) -> Promise<T>
//   apiGet<T>(path, opts), apiPost<T>(path, body, opts)
//   ApiError { message, type, status, fieldErrors }, friendlyError(e) -> Spanish text
// Errors follow the envelope {"message", "type", "field_errors"}. Default timeout 20 s.

import { API_URL, LIVE_TIMEOUT_MS } from "../config";
import type { Mapa, Session } from "../types";
import { authHeaders, clearToken, getToken } from "./session";

export class ApiError extends Error {
  type: string;
  status: number;
  fieldErrors: Record<string, string[] | string>;
  constructor(message: string, type: string, status: number, fieldErrors: Record<string, string[] | string> = {}) {
    super(message);
    this.type = type;
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
}

const FRIENDLY: Record<string, string> = {
  code_invalid: "El código no es correcto. Revisa el mensaje de WhatsApp e inténtalo otra vez.",
  code_expired: "El código venció. Pide uno nuevo.",
  code_too_soon: "Ya te enviamos un código hace poco. Espera unos segundos y vuelve a pedirlo.",
  session_invalid: "Tu sesión terminó. Vuelve a entrar.",
  network: "No pudimos conectar. Revisa tu señal e inténtalo otra vez.",
  timeout: "La conexión está muy lenta. Inténtalo otra vez.",
};

/** Spanish message for the user: known types first, then the API message, then a generic one. */
export function friendlyError(e: unknown): string {
  if (e instanceof ApiError) return FRIENDLY[e.type] ?? (e.message || "Algo falló. Inténtalo otra vez.");
  return "Algo falló. Inténtalo otra vez.";
}

export type ApiOptions = {
  method?: string;
  /** Sent as JSON when it is not a string, FormData or Blob. */
  body?: unknown;
  headers?: Record<string, string>;
  /** Send the bearer token (default: true when signed in). */
  auth?: boolean;
  /** Milliseconds, default 20000. */
  timeout?: number;
  signal?: AbortSignal;
};

export async function api<T>(path: string, opts: ApiOptions = {}): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), opts.timeout ?? 20000);
  const onAbort = () => ctrl.abort();
  if (opts.signal?.aborted) ctrl.abort();
  else opts.signal?.addEventListener("abort", onAbort, { once: true });
  const headers: Record<string, string> = { Accept: "application/json", ...(opts.auth === false ? {} : authHeaders()), ...opts.headers };
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
    res = await fetch(API_URL + path, { method: opts.method ?? (body ? "POST" : "GET"), headers, body, signal: ctrl.signal });
  } catch (e) {
    const aborted = e instanceof DOMException && e.name === "AbortError";
    throw new ApiError("", aborted ? "timeout" : "network", 0);
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener("abort", onAbort);
  }
  const data = res.status === 204 ? {} : await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && data?.type === "session_invalid") clearToken();
    throw new ApiError(data?.message ?? "", data?.type ?? `http_${res.status}`, res.status, data?.field_errors ?? {});
  }
  return data as T;
}

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
