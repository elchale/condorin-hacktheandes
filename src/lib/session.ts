// Bearer session for the Django API (Data contract B), kept in localStorage.
// Stable API for every page: getToken, setToken, clearToken, authHeaders, getSession, saveSession, subscribeSession.

import type { Session } from "../types";
import { getJSON, setItem } from "./storage";

const KEY = "condorin.session";
const listeners = new Set<() => void>();
let cached: Session | null | undefined;

const notify = () => listeners.forEach((f) => f());

export function getSession(): Session | null {
  if (cached === undefined) {
    const s = getJSON<Session | null>(KEY, null);
    cached = s && typeof s.token === "string" && s.token ? s : null;
  }
  return cached;
}

export function saveSession(s: Session) {
  cached = s;
  setItem(KEY, JSON.stringify(s));
  notify();
}

export function getToken(): string | null {
  return getSession()?.token ?? null;
}

/** Store a token; member and ONG info are optional (kept from the current session when omitted). */
export function setToken(token: string, info?: Partial<Omit<Session, "token">>) {
  const prev = getSession();
  saveSession({
    token,
    member: info?.member ?? prev?.member ?? { name: "", phone: "" },
    ong: info?.ong ?? prev?.ong ?? { name: "" },
  });
}

export function clearToken() {
  cached = null;
  setItem(KEY, null);
  notify();
}

/** `{ Authorization: "Bearer ..." }` when signed in, otherwise `{}`. */
export function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export function subscribeSession(f: () => void) {
  listeners.add(f);
  // Another tab signed in or out.
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY) {
      cached = undefined;
      f();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(f);
    window.removeEventListener("storage", onStorage);
  };
}
