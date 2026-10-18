/** Legal identity of the data controller, shown in the privacy policy and terms. */
export const COMPANY = {
  legalName: "Qolca Solutions S.A.C.",
  ruc: "20613914464",
  /** Domicilio fiscal registered with SUNAT (same entity as Comehometag). */
  address: "Pj. Tiziano Muñoz 155, Urb. Ingeniería, San Martín de Porres, Lima, Perú",
  email: "info@qolca.org",
} as const;

/** Bump when the privacy policy or terms change in a way users must re-accept. */
export const LEGAL_UPDATED_AT = "17 de octubre de 2026";
