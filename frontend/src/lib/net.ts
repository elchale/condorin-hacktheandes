import { getItem, setItem } from "./storage";

type NetInfo = { saveData?: boolean; effectiveType?: string };

/** True when the browser asks to save data or the link is 2g / slow-2g. */
export function connectionIsSlow(): boolean {
  const c = (navigator as Navigator & { connection?: NetInfo }).connection;
  if (!c) return false;
  return !!c.saveData || c.effectiveType === "2g" || c.effectiveType === "slow-2g";
}

const KEY = "condorin.ahorro";

/** User choice wins; otherwise follow the connection hints. */
export function initialSaveData(): boolean {
  const v = getItem(KEY);
  if (v === "1") return true;
  if (v === "0") return false;
  return connectionIsSlow();
}

export function rememberSaveData(on: boolean) {
  setItem(KEY, on ? "1" : "0");
}

/** Run after the browser is idle (or after `timeout` ms at the latest). */
export function whenIdle(fn: () => void, timeout = 1500): () => void {
  const w = window as Window & {
    requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number;
    cancelIdleCallback?: (id: number) => void;
  };
  if (w.requestIdleCallback) {
    const id = w.requestIdleCallback(fn, { timeout });
    return () => w.cancelIdleCallback?.(id);
  }
  const id = window.setTimeout(fn, 200);
  return () => window.clearTimeout(id);
}
