import { nowMs } from "./clock";

const LOCALE = "es-PE";
const TZ = "America/Lima";

const longDate = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "long", year: "numeric", timeZone: TZ });
const shortDate = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", timeZone: TZ });
const time = new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit", timeZone: TZ });
const monthFmt = new Intl.DateTimeFormat(LOCALE, { month: "short", year: "numeric", timeZone: "UTC" });
const num = new Intl.NumberFormat(LOCALE);

export const fmtLongDate = (iso: string) => longDate.format(new Date(iso));
export const fmtShortDate = (iso: string) => shortDate.format(new Date(iso)).replace(".", "");
export const fmtTime = (iso: string) => time.format(new Date(iso));
const shortYear = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", year: "numeric", timeZone: TZ });
/** "31 jul 2025": the list mixes years, so every row says which one. */
export const fmtDayYear = (iso: string) => shortYear.format(new Date(iso)).replace(/\./g, "").replace(/ de /g, " ");
const dayKey = new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit", day: "2-digit", timeZone: TZ });
/** Calendar day in Lima, "2026-10-18". */
export const limaDay = (iso: string | number) => dayKey.format(new Date(iso));
export const fmtNum = (n: number) => num.format(n);
export const fmtPct = (x: number) => `${Math.round(x * 100)}%`;

/** "2026-10" to "oct 2026". */
export function fmtMonth(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return monthFmt.format(new Date(Date.UTC(y, m - 1, 15))).replace(".", "").replace(" de ", " ");
}

/** "hace 5 min", "hace 3 h", "hace 2 días", or a short date. */
export function fmtAgo(iso: string, now = nowMs()): string {
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (s < 60) return "hace un momento";
  if (s < 3600) return `hace ${Math.round(s / 60)} min`;
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
  const d = Math.round(s / 86400);
  if (d < 14) return d === 1 ? "hace 1 día" : `hace ${d} días`;
  return fmtShortDate(iso);
}

export const monthOf = (iso: string) => iso.slice(0, 7);

export function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

export function firstName(name: string | undefined | null): string {
  return (name ?? "").trim().split(/\s+/)[0] ?? "";
}
