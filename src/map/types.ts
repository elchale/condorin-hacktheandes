import type { DetectionFeature, LayerMeta, River, SceneImage } from "../types";
import type { FireCollection, TileLayerMeta } from "../lib/fuentes";

/** "sat": Esri World Imagery with the Esri place labels (default, like Amazon Mining Watch). "calles": Esri light gray. */
export type Basemap = "sat" | "calles";

/** One shot instructions for the map; `n` changes on every request so the same target can be repeated. */
export type MapCommand =
  | { kind: "detection"; id: number; n: number }
  | { kind: "point"; lat: number; lon: number; zoom: number; n: number }
  | { kind: "bounds"; bounds: [[number, number], [number, number]]; n: number }
  | { kind: "fit"; n: number };

export type ActiveLayer = { meta: LayerMeta; data: GeoJSON.GeoJsonObject };

export type ResolvedRiver = River & { lat: number; lon: number };

export type MapViewProps = {
  detections: DetectionFeature[];
  rivers: ResolvedRiver[];
  images: Record<number, SceneImage>;
  mineRivers: string[];
  signedIn: boolean;
  basemap: Basemap;
  layers: ActiveLayer[];
  /** The footprint layer shows these years [from, to] (inclusive), the newest year brighter. */
  years: [number, number];
  saveData: boolean;
  /** Lima day ("2026-10-18") whose scenes get the soft pulse ring: the last day of the time window. */
  pulseDay?: string;
  command: MapCommand | null;
  onSelect: (id: number) => void;
  /** Reports the zoom after every change (the dashboard shows the "Acércate" hint). */
  onZoom?: (zoom: number) => void;
  /** Hectares of mining footprint inside the current view, up to `year`. */
  onFootprintInView?: (ha: number) => void;
  /** True while base tiles are loading (drives the thin progress bar). */
  onTilesLoading?: (loading: boolean) => void;
  /** NASA FIRMS fires to draw (null when the layer is off). */
  fires?: FireCollection | null;
  /** Global Forest Watch raster overlays that are on. */
  tiles?: TileLayerMeta[];
  /** Called once when the map exists (the dashboard then fetches the live feeds). */
  onReady?: () => void;
  /** Live lines for each river ring popup (next radar pass, rain for 3 days), by river slug. */
  riverInfo?: Record<string, string[]>;
};

/** The hero layer (Amazon Mining Watch footprint), on by default and filtered by the year slider. */
export const FOOTPRINT_ID = "mineria-amw";
/** Protected areas, on by default as a green outline. */
export const ANP_ID = "anp-sernanp";
export const DEFAULT_LAYERS = [FOOTPRINT_ID, ANP_ID];

/** The Peruvian Amazon, the first view: [[south, west], [north, east]]. */
export const AMAZONIA: [[number, number], [number, number]] = [
  [-14.6, -78.2],
  [-2.2, -68.6],
];

/** Dense point layers (REINFO, 21,192 points) are drawn only from this zoom up. */
export const DENSE_MIN_ZOOM = 9;
export const layerMinZoom = (m: LayerMeta): number => (m.geometry === "Point" && m.features > 5000 ? DENSE_MIN_ZOOM : 0);
