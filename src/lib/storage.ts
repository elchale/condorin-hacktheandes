// localStorage can throw (private mode, blocked site data). Every access is guarded.

export function getItem(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function setItem(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

export function getJSON<T>(key: string, fallback: T): T {
  const raw = getItem(key);
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

// Compatibility names: session helpers now live in ./session (getSession, saveSession, setToken, clearToken, authHeaders).
export { getSession as readSession, saveSession, clearToken as clearSession, subscribeSession } from "./session";
