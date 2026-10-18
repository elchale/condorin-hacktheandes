// The time window of the map: the 3 Lima calendar days ending on a chosen day (today by default).
// Days are plain "2026-10-18" strings, compared as text and moved with UTC arithmetic.
import { nowMs } from "./clock";
import { limaDay } from "./format";

export const WINDOW_DAYS = 3;
const MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
const MON = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"];

const parts = (day: string) => day.split("-").map(Number) as [number, number, number];
const utc = (day: string) => {
  const [y, m, d] = parts(day);
  return Date.UTC(y, m - 1, d);
};

/** Today in Lima, following the API's clock. */
export const todayLima = () => limaDay(nowMs());
export const addDays = (day: string, n: number) => new Date(utc(day) + n * 86400_000).toISOString().slice(0, 10);
export const daysBetween = (a: string, b: string) => Math.round((utc(b) - utc(a)) / 86400_000);

/** "20 de julio de 2026". */
export function longDay(day: string): string {
  const [y, m, d] = parts(day);
  return `${d} de ${MONTHS[m - 1]} de ${y}`;
}
/** "20 jul", or "20 jul 2026". */
export function shortDay(day: string, year = false): string {
  const [y, m, d] = parts(day);
  return `${d} ${MON[m - 1]}${year ? ` ${y}` : ""}`;
}

/** "16 al 18 de octubre de 2026", "30 de septiembre al 2 de octubre de 2026", across years in full. */
function rangeLong(from: string, to: string): string {
  const [y1, m1, d1] = parts(from);
  const [y2, m2] = parts(to);
  if (y1 !== y2) return `${longDay(from)} al ${longDay(to)}`;
  if (m1 !== m2) return `${d1} de ${MONTHS[m1 - 1]} al ${longDay(to)}`;
  return `${d1} al ${longDay(to)}`;
}
/** "16 al 18 oct 2026", "30 set al 2 oct 2026". */
function rangeShort(from: string, to: string): string {
  const [y1, m1, d1] = parts(from);
  const [y2, m2] = parts(to);
  if (y1 !== y2) return `${shortDay(from, true)} al ${shortDay(to, true)}`;
  if (m1 !== m2) return `${shortDay(from)} al ${shortDay(to, true)}`;
  return `${d1} al ${shortDay(to, true)}`;
}

export type TimeWindow = {
  from: string;
  to: string;
  isToday: boolean;
  /** For the headline: "últimos 3 días (16 al 18 de octubre de 2026)" or "3 días hasta el 20 de julio de 2026 (18 al 20 de julio)". */
  words: string;
  /** For the map chip: "Últimos 3 días: 16 al 18 oct 2026" or "3 días hasta el 20 jul 2026". */
  chip: string;
};

export function makeWindow(end: string, today: string): TimeWindow {
  const from = addDays(end, -(WINDOW_DAYS - 1));
  const isToday = end === today;
  return isToday
    ? { from, to: end, isToday, words: `últimos ${WINDOW_DAYS} días (${rangeLong(from, end)})`, chip: `Últimos ${WINDOW_DAYS} días: ${rangeShort(from, end)}` }
    : { from, to: end, isToday, words: `${WINDOW_DAYS} días hasta el ${longDay(end)}`, chip: `${WINDOW_DAYS} días hasta el ${shortDay(end, true)}` };
}

/** The days with data closest to the window (before or after), oldest first. */
export function nearestDays(days: string[], w: TimeWindow, n = 3): string[] {
  const dist = (d: string) => (d < w.from ? daysBetween(d, w.from) : d > w.to ? daysBetween(w.to, d) : 0);
  return days
    .filter((d) => d < w.from || d > w.to)
    .sort((a, b) => dist(a) - dist(b))
    .slice(0, n)
    .sort();
}
