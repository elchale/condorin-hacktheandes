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

export type ApiError = { message: string; type: string; field_errors: Record<string, string[]> };

export type Patch = Partial<EditableFields> & {
  authorities?: string[];
  filings?: { authority: string; receipt_number: string; filed_at: string }[];
  reopen?: boolean;
};

/** The payload of GET /api/v1/me (the panel view): member, ONG, totals and incidents. */
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
  member: { name: string; phone: string; joined_now: boolean };
  ong: { name: string; rivers: { slug: string; name: string; protected_area: string }[]; members: number };
  totals: { incidents: number; without_expediente: number; draft: number; ready: number; filed: number };
  incidents: Incident[];
};
