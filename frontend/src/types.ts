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
  /** The API's clock (real or the demo day); absent in old snapshots. */
  clock?: import("./lib/clock").Clock;
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

// Member pages (evento, expediente, panel).

/** The payload of GET /api/v1/expedientes/<token> (see condorin-backend expedientes/serializers.py). */
export type Status = "draft" | "ready" | "filed";

export type EditableFields = {
  ong_name: string;
  ong_ruc: string;
  ong_address: string;
  notify_email: string;
  rep_name: string;
  rep_dni: string;
  rep_position: string;
  facts: string;
  place_reference: string;
  field_observations: string;
  field_evidence_links: string;
  suspects: string;
  risk_notes: string;
  identity_reserved: boolean;
  truth_declared: boolean;
};

export type Authority = {
  code: string;
  name: string;
  kind: string;
  is_primary: boolean;
  selected: boolean;
  submit_url: string;
  phone: string;
  address: string;
  instructions: string;
  max_attachment_mb: number | null;
  sends_by_email: boolean;
  filing: null | { receipt_number: string; filed_at: string; filed_by: string | null };
};

export type Detection = {
  lat: string;
  lon: string;
  utm: string;
  confidence: number;
  maps_url: string;
  crop_url: string | null;
  crop_uri: string;
  crop_sha256: string;
};

export type Payload = {
  member: { name: string; first_name: string; phone_hint: string };
  ong: { name: string };
  expediente: EditableFields & {
    id: number;
    folio: string | null;
    status: Status;
    status_label: string;
    missing: Record<string, string>;
    created_by: string | null;
    updated_by: string | null;
    updated_at: string;
    finalized_at: string | null;
    finalized_by: string | null;
    pdf_url: string;
    pdf_sha256: string;
  };
  incident: {
    river: { slug: string; name: string; basin: string; district: string; province: string; region: string; protected_area: string };
    place: string;
    satellite: string;
    captured_at: string;
    captured_at_label: string;
    model: string;
    detections: Detection[];
    /** Detections below the confidence threshold, stored but not alerted. */
    discarded: number;
    threshold: number;
    scene: {
      uri: string;
      md5_hash: string;
      crc32c: string;
      size_bytes: number | null;
      download_url: string | null;
      preview_url: string | null;
      /** Every detection, discarded ones too; bbox is [x, y, width, height] in scene pixels. */
      boxes: { bbox: [number, number, number, number]; confidence: number; alerting: boolean }[];
    };
    history: { captured_at: string; label: string; satellite: string; detections: number; preview_url: string | null }[];
  };
  authorities: Authority[];
  /** Only in the response that confirms the expediente. */
  sent?: { emailed_to: string[]; authorities_emailed: string[] };
};

export type Patch = Partial<EditableFields> & {
  authorities?: string[];
  filings?: { authority: string; receipt_number: string; filed_at: string }[];
  reopen?: boolean;
};

/** The payload of GET /api/v1/me (the panel view): member, ONG, totals and incidents. */
export type TriageStatus = "confirmed" | "false_positive" | "verified_field";
export type TriageReason = "boat" | "sandbar" | "other";

/** What the member's ONG decided about an incident (shared by its members); `null` means nobody looked yet. */
export type Triage = {
  status: TriageStatus;
  status_label: string;
  reason: TriageReason | "";
  reason_label: string;
  updated_at: string;
  /** Null for observers: they see that someone decided, never who. */
  set_by: string | null;
};

export type Incident = {
  id: number;
  river: { slug: string; name: string; protected_area: string };
  place: string;
  satellite: string;
  captured_at: string;
  captured_at_label: string;
  model: string;
  detections: number;
  top_confidence: number;
  lat: string;
  lon: string;
  utm: string;
  maps_url: string;
  /** Signed links to the crops of the strongest detections; empty while the bucket is not readable. */
  crops: string[];
  evidence_pinned: boolean;
  triage: Triage | null;
  expediente: null | {
    status: Status;
    status_label: string;
    folio: string | null;
    updated_at: string;
    updated_by: string | null;
    missing: number;
    authorities: string[];
    filings: number;
  };
};

export type Panel = {
  /** The API's clock: today's date and time, real or simulated. */
  clock?: import("./lib/clock").Clock;
  member: { name: string; phone: string; joined_now: boolean; role?: "member" | "observer"; can_act?: boolean };
  ong: { name: string; rivers: { slug: string; name: string; protected_area: string }[]; members: number };
  totals: {
    incidents: number;
    without_expediente: number;
    draft: number;
    ready: number;
    filed: number;
    /** Incidents by decision of the ONG; `new` is the ones nobody has looked at. */
    triage?: Record<TriageStatus | "new", number>;
  };
  /** First page of incidents, newest first; the rest come from GET /api/v1/me/incidentes?page=N. */
  incidents: Incident[];
  /** DRF page links (absolute URLs); `count` is every incident of the ONG. */
  pagination?: { count: number; next: string | null; previous: string | null };
};

/** DRF's standard PageNumberPagination envelope. */
export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };
