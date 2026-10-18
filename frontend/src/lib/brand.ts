/** Display name of the product. Change it here and everywhere follows. Technical ids keep "condorin". */
export const BRAND_NAME = "Ojo de Cóndor";

/** Digits only; 9 digit Peruvian mobiles get the 51 prefix ("987 654 321" to "51987654321"). */
export function normalizePhone(raw: string): string {
  const d = raw.replace(/\D/g, "");
  return d.length === 9 ? `51${d}` : d;
}

/** "51987654321" to "+51 987 654 321"; anything else as "+<digits>". */
export function formatPhone(phone: string): string {
  const p = phone.replace(/\D/g, "");
  const d = p.startsWith("51") && p.length === 11 ? p.slice(2) : p;
  return d.length === 9 ? `+51 ${d.slice(0, 3)} ${d.slice(3, 6)} ${d.slice(6)}` : `+${p}`;
}
