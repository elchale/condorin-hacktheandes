import type { DetectionFeature, LayerMeta, River, SceneImage } from "../types";

export type Basemap = "dark" | "sat";

/** One shot instructions for the map; `n` changes on every request so the same target can be repeated. */
export type MapCommand =
  | { kind: "detection"; id: number; n: number }
  | { kind: "point"; lat: number; lon: number; zoom: number; n: number }
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
  saveData: boolean;
  /** Pixels hidden under the bottom sheet (phones), so fits and fly targets stay visible. */
  bottomInset: number;
  command: MapCommand | null;
  onSelect: (id: number) => void;
};
