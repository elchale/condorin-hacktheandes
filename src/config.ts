export { BRAND_NAME } from "./lib/brand";

export const API_URL: string = (import.meta.env.VITE_API_URL ?? "https://api.condorin.pe").replace(/\/$/, "");

/** Public site origin (this SPA is served there; used for absolute links and share images). */
export const SITE_URL = "https://condorin.pe";
export const PANEL_URL = "/panel";
export const PRIVACY_URL = "/privacidad";
export const TERMS_URL = "/terminos";
export const PETITION_URL = "https://c.org/rPspHG8WJ7";

export const LIVE_TIMEOUT_MS = 6000;
export const LIVE_REFRESH_MS = 120_000;
export const RESEND_COOLDOWN_S = 45;

/** River fallback coordinates from the contract, used when a river has no lat/lon. */
export const RIVER_FALLBACK: Record<string, [number, number]> = {
  yaguas: [-2.65, -71.35],
  malinowski: [-12.95, -69.95],
  nanay: [-3.75, -73.45],
  "madre-de-dios": [-12.6, -69.2],
  tambopata: [-12.85, -69.35],
  inambari: [-13.05, -70.1],
  napo: [-3.3, -72.8],
  putumayo: [-2.4, -72.8],
  "marañon": [-4.5, -77.5],
};

/** Years of the mining footprint slider (Amazon Mining Watch, 2025 and 2026 provisional). */
export const FIRST_YEAR = 2018;
export const LAST_YEAR = 2026;
/** Footprint hectares added each year, from mineria-amw.geojson (area_ha); replaced by the file once it loads. */
export const FOOTPRINT_HA: Record<number, number> = {
  2018: 74807,
  2019: 22494,
  2020: 24353,
  2021: 24933,
  2022: 19543,
  2023: 20621,
  2024: 21378,
  2025: 25522,
  2026: 25967,
};

/** The one time control: it filters the detections and the mining footprint together. */
export type Period = { id: string; label: string; words: string; years: [number, number]; days?: number };
/**
 * Options built from the years that have detections: "30 días", the two newest years with data,
 * and "Todo" (the default, so a time series of one spot never vanishes behind a short window).
 */
export function buildPeriods(detectionYears: number[]): Period[] {
  const years = [...new Set(detectionYears.filter((y) => y >= FIRST_YEAR && y <= LAST_YEAR))].sort((a, b) => b - a);
  const shown = (years.length ? years : [LAST_YEAR]).slice(0, 2);
  const first = Math.min(FIRST_YEAR, ...years);
  return [
    { id: "30d", label: "30 días", words: "últimos 30 días", years: [LAST_YEAR, LAST_YEAR], days: 30 },
    ...shown.map((y): Period => ({ id: `y${y}`, label: String(y), words: `solo ${y}`, years: [y, y] })),
    { id: "todo", label: "Todo", words: `todo el periodo, ${first} a ${LAST_YEAR}`, years: [first, LAST_YEAR] },
  ];
}
export const PERIODS: Period[] = buildPeriods([LAST_YEAR - 1, LAST_YEAR]);
export const DEFAULT_PERIOD = "todo";
