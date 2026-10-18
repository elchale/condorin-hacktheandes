// A tiny HTML builder for Leaflet popups and tooltips (they take strings). Every value interpolated
// with h`` is escaped unless it is already Html (another h`` result or raw()); arrays are joined.
import { escapeHtml } from "../lib/format";

export class Html {
  constructor(readonly value: string) {}
  toString() {
    return this.value;
  }
}

/** Trusted markup, passed through as is (only for strings built here, never for data). */
export const raw = (s: string) => new Html(s);

const part = (v: unknown): string => {
  if (v instanceof Html) return v.value;
  if (Array.isArray(v)) return v.map(part).join("");
  if (v === null || v === undefined || v === false) return "";
  return escapeHtml(String(v));
};

export function h(strings: TemplateStringsArray, ...values: unknown[]): Html {
  let out = strings[0];
  for (let i = 0; i < values.length; i++) out += part(values[i]) + strings[i + 1];
  return new Html(out);
}

export { escapeHtml };
