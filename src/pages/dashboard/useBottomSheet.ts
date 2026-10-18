import { useLayoutEffect, useRef, useState, type PointerEvent as RPointerEvent } from "react";

export const HANDLE = 24;

/** 0 peek, 1 half, 2 full. */
export type Snap = 0 | 1 | 2;

/**
 * Bottom sheet (phones): three snap points driven by a CSS variable. The peek shows the handle,
 * the stats and the year slider; it is measured, so it fits any font size. Inert on desktop.
 */
export function useBottomSheet(desktop: boolean) {
  const sheet = useRef<HTMLElement>(null);
  const peekBox = useRef<HTMLDivElement>(null);
  const [snap, setSnap] = useState<Snap>(0);
  const [sheetH, setSheetH] = useState(0);
  const [peek, setPeek] = useState(190);
  useLayoutEffect(() => {
    const measure = () => {
      setSheetH(sheet.current?.offsetHeight ?? 0);
      // Collapsed, the sheet takes about a quarter of the screen (the rest shows on the half snap).
      if (peekBox.current) setPeek(Math.min(HANDLE + peekBox.current.offsetHeight + 8, Math.max(150, Math.round(window.innerHeight * 0.25))));
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);
  const snapY = (s: Snap) => (s === 2 ? 0 : s === 1 ? Math.round(sheetH * 0.16) : Math.max(0, sheetH - peek));
  const justDragged = useRef(false);
  const drag = useRef<{ y0: number; t0: number; base: number; moved: boolean } | null>(null);

  const onDown = (e: RPointerEvent) => {
    if (desktop) return;
    drag.current = { y0: e.clientY, t0: performance.now(), base: snapY(snap), moved: false };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    sheet.current?.classList.add("dragging");
  };
  const onMove = (e: RPointerEvent) => {
    const d = drag.current;
    if (!d || !sheet.current) return;
    const dy = e.clientY - d.y0;
    if (Math.abs(dy) > 6) d.moved = true;
    const y = Math.min(snapY(0), Math.max(0, d.base + dy));
    sheet.current.style.setProperty("--sheet-y", `${y}px`);
  };
  const onUp = (e: RPointerEvent) => {
    const d = drag.current;
    drag.current = null;
    if (!d || !sheet.current) return;
    sheet.current.classList.remove("dragging");
    sheet.current.style.removeProperty("--sheet-y");
    justDragged.current = d.moved;
    if (!d.moved) return;
    const dy = e.clientY - d.y0;
    const v = dy / Math.max(1, performance.now() - d.t0); // px per ms
    const y = d.base + dy;
    let next: Snap;
    if (v < -0.5) next = snap === 0 ? 1 : 2;
    else if (v > 0.5) next = snap === 2 ? 1 : 0;
    else {
      const opts: Snap[] = [0, 1, 2];
      next = opts.reduce((best, s) => (Math.abs(snapY(s) - y) < Math.abs(snapY(best) - y) ? s : best), 0 as Snap);
    }
    setSnap(next);
  };
  const dragProps = desktop ? {} : { onPointerDown: onDown, onPointerMove: onMove, onPointerUp: onUp, onPointerCancel: onUp };

  /** The handle's tap: toggles peek and half, unless it ended a drag. */
  const onHandleClick = () => {
    if (justDragged.current) return void (justDragged.current = false);
    setSnap((s) => (s === 0 ? 1 : 0));
  };

  return { sheet, peekBox, snap, setSnap, peek, snapY, dragProps, onHandleClick };
}
