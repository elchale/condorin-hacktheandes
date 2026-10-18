// The API's clock. Every payload (/api/v1/mapa, /api/v1/me) carries `clock`: the instant the server
// considers "now" (real, or the demo day set with `manage.py set_today`). The SPA learns the offset
// between that instant and this device and reasons about time with nowMs(), so "últimos 30 días",
// "hace 5 min" and the panel's clock all follow the server's day, and tick on from it.
import { useEffect, useState } from "react";

export type Clock = {
  /** ISO instant the server treats as now. */
  now: string;
  /** "2026-07-10", Lima calendar day. */
  today: string;
  /** "viernes 10 de julio de 2026". */
  label: string;
  simulated: boolean;
  timezone: string;
};

let offsetMs = 0;
let simulated = false;
let known = false;

/** Remember the server's clock from a payload; a missing block (old snapshot) changes nothing. */
export function syncClock(clock: Clock | null | undefined): void {
  if (!clock?.now) return;
  const t = new Date(clock.now).getTime();
  if (Number.isNaN(t)) return;
  offsetMs = t - Date.now();
  simulated = !!clock.simulated;
  known = true;
}

/** Milliseconds since the epoch, as the server sees it right now. */
export const nowMs = (): number => Date.now() + offsetMs;

export const clockIsSimulated = (): boolean => simulated;
export const clockKnown = (): boolean => known;

/** Re-renders every `tickMs`, returning the server's now. */
export function useNow(tickMs = 1000): number {
  const [t, setT] = useState(nowMs);
  useEffect(() => {
    const id = window.setInterval(() => setT(nowMs()), tickMs);
    return () => window.clearInterval(id);
  }, [tickMs]);
  return t;
}
