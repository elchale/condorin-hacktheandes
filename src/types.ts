// Shapes from mapa-data/CONTRACT.md (Data contracts A, B and C).

export type Totals = {
  images: number;
  detections: number;
  alerting_detections: number;
  alerts_sent: number;
  /** Alerts whose link was opened (added 2026-10-17, absent in older payloads). */
  alerts_opened?: number;
  expedientes: number;
  expedientes_filed: number;
  ongs: number;
  members: number;
  /** People registered on the site (added 2026-10-17). */
  users?: number;
  rivers: number;
};

export type River = {
  slug: string;
  name: string;
  basin: string;
  region: string;
  province: string;
  district: string;
  protected_area: string;
  lat: number | null;
  lon: number | null;
  ongs: number;
  images: number;
  detections: number;
  last_captured_at: string | null;
};

export type SceneImage = {
  id: number;
  river: string;
  satellite: string;
  captured_at: string;
  model: string;
  detections: number;
  alerting: number;
  top_confidence: number;
  lat: number;
  lon: number;
  alerts_sent: number;
  expedientes: { draft: number; ready: number; filed: number };
};

export type DetectionProps = {
  id: number;
  image: number;
  river: string;
  confidence: number;
  captured_at: string;
  alerting: boolean;
  satellite: string;
  kind: string;
};

export type DetectionFeature = {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: DetectionProps;
};

export type ActivityItem = {
  at: string;
  kind: "image" | "alert" | "expediente_opened" | "expediente_filed" | string;
  river: string;
  label: string;
};

export type Mine = {
  member: { name: string; phone: string };
  ong: { name: string; rivers: string[] };
} | null;

export type Mapa = {
  generated_at: string;
  brand: string;
  bbox: [number, number, number, number] | null;
  totals: Totals;
  rivers: River[];
  images: SceneImage[];
  detections: { type: "FeatureCollection"; features: DetectionFeature[] };
  timeline: { month: string; images: number; detections: number }[];
  activity: ActivityItem[];
  mine: Mine;
};

export type LayerMeta = {
  id: string;
  file: string;
  title: string;
  short: string;
  source: string;
  license: string;
  url: string;
  year: string;
  color: string;
  geometry: string;
  features: number;
  bytes_gzip: number;
  property_labels?: Record<string, string>;
};

export type Session = {
  token: string;
  member: { name: string; phone: string };
  ong: { name: string };
};
