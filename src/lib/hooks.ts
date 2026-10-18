import { useEffect, useState, useSyncExternalStore } from "react";
import { LIVE_REFRESH_MS } from "../config";
import type { Mapa, Session } from "../types";
import { fetchMapa } from "./api";
import { syncClock } from "./clock";
import { SNAPSHOT } from "./snapshot";
import { getSession, subscribeSession } from "./session";

export function useSession(): Session | null {
  return useSyncExternalStore(subscribeSession, getSession);
}

export type MapaState = { data: Mapa; live: boolean; checkedAt: number | null };

/** Bundled snapshot first (instant paint), then the live endpoint swapped in silently; refreshed while visible. */
export function useMapa(token: string | null): MapaState {
  const [state, setState] = useState<MapaState>({ data: SNAPSHOT, live: false, checkedAt: null });

  useEffect(() => {
    let alive = true;
    const load = () => {
      if (document.visibilityState === "hidden") return;
      fetchMapa()
        .then((data) => {
          if (!alive) return;
          syncClock(data.clock);
          setState({ data, live: true, checkedAt: Date.now() });
        })
        .catch(() => alive && setState((s) => ({ ...s, live: false, checkedAt: Date.now() })));
    };
    load();
    const id = window.setInterval(load, LIVE_REFRESH_MS);
    // Back to the tab (or the phone unlocked): the interval skipped while hidden, so refresh now.
    const onVisible = () => {
      if (document.visibilityState === "visible") load();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive = false;
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [token]);

  return state;
}

export function useMedia(query: string): boolean {
  const [m, setM] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const f = () => setM(mq.matches);
    mq.addEventListener?.("change", f);
    return () => mq.removeEventListener?.("change", f);
  }, [query]);
  return m;
}
