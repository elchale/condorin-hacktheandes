/** Field notes helpers, kept apart from the component so they can be tested without a DOM. */

/** Same limit as the API (expedientes/notas.py MAX_CHARS); a longer note is refused there, never cut. */
export const NOTE_MAX = 500;

/** The observaciones with the note added on its own line; unchanged when the note is already there. */
export function withNote(observations: string, note: string): string {
  const text = note.trim();
  if (!text || observations.includes(text)) return observations;
  return observations.trim() ? `${observations.trimEnd()}\n${text}` : text;
}

const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"];

/** "16 oct 2026" for an ISO timestamp; empty when there is none (a note saved a moment ago). */
export function noteDate(iso: string): string {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return "";
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}
