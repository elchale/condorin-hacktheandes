// Bearer session for the Django API (Data contract B), kept in localStorage.
// Stable API for every page: getToken, setToken, clearToken, authHeaders, getSession, saveSession, subscribeSession.
// A session past its lifetime is dropped here, so pages never render with a dead token; the API's 401 stays
// the final word (a device clock can be wrong).

import type { Session } from "../types";
import { getJSON, setItem } from "./storage";

const KEY = "condorin.session";
const listeners = new Set<() => void>();
let cached: Session | null | undefined;
let expiryTimer: number | undefined;

const notify = () => listeners.forEach((f) => f());

// Lifetimes of accounts/session.py: 30 days for a WhatsApp code session, 7 for an alert link session.
const CODE_SECONDS = 30 * 24 * 60 * 60;
const LINK_SECONDS = 7 * 24 * 60 * 60;
const B62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";

/** When a Django TimestampSigner session ("<base64 json>:<base62 seconds>:<sig>") stops working, or null if unreadable. */
export function sessionExpiresAt(token: string): number | null {
  const [payload, stamp] = token.split(":");
  if (!payload || !stamp) return null;
  let seconds = 0;
  for (const ch of stamp) {
    const v = B62.indexOf(ch);
    if (v < 0) return null;
    seconds = seconds * 62 + v;
  }
  let via = "code";
  try {
    via = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/"))).via ?? "code";
  } catch {
    /* unreadable payload: assume the longer lifetime and let the API decide */
  }
  return (seconds + (via === "link" ? LINK_SECONDS : CODE_SECONDS)) * 1000;
}

/** Older builds and other apps may have stored a partial object: keep only a usable shape. */
function normalize(s: unknown): Session | null {
  const o = s as Partial<Session> | null;
  if (!o || typeof o !== "object" || typeof o.token !== "string" || !o.token) return null;
  return {
    token: o.token,
    member: { name: String(o.member?.name ?? ""), phone: String(o.member?.phone ?? "") },
    ong: { name: String(o.ong?.name ?? "") },
  };
}

/** Drop the session the moment it expires while the page stays open. */
function scheduleExpiry(s: Session | null) {
  window.clearTimeout(expiryTimer);
  const at = s && sessionExpiresAt(s.token);
  // setTimeout overflows past ~24.8 days; a later visit re-checks on load anyway.
  if (at && at - Date.now() < 2 ** 31 - 1) expiryTimer = window.setTimeout(clearToken, Math.max(0, at - Date.now()));
}

const expired = (s: Session) => {
  const at = sessionExpiresAt(s.token);
  return at !== null && at <= Date.now();
};

export function getSession(): Session | null {
  if (cached === undefined) {
    let s = normalize(getJSON<unknown>(KEY, null));
    if (s && expired(s)) {
      setItem(KEY, null);
      s = null;
    }
    cached = s;
    scheduleExpiry(s);
  }
  return cached;
}

export function saveSession(s: Session) {
  cached = normalize(s);
  setItem(KEY, cached && JSON.stringify(cached));
  scheduleExpiry(cached);
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
  window.clearTimeout(expiryTimer);
  if (cached === null) return;
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
  // A laptop waking up: timers paused while asleep, so check the lifetime again.
  const onVisible = () => {
    if (document.visibilityState === "visible" && cached && expired(cached)) clearToken();
  };
  window.addEventListener("storage", onStorage);
  document.addEventListener("visibilitychange", onVisible);
  return () => {
    listeners.delete(f);
    window.removeEventListener("storage", onStorage);
    document.removeEventListener("visibilitychange", onVisible);
  };
}
