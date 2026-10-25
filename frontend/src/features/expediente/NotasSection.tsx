import { useCallback, useEffect, useState } from "react";
import { ApiError, friendlyError } from "../../lib/api";
import { Link } from "../../router";
import type { Patch, Payload } from "../../types";
import { correctNote, deleteNote, loadNotes, saveNote, type FieldNote } from "../shared/api";
import { card, field, hint, label, outlineButton, sectionTitle, textLink } from "../shared/ui";
import { NOTE_MAX, noteDate, withNote } from "./notes";

type Props = {
  token: string;
  expediente: Payload["expediente"];
  save: (patch: Patch) => Promise<boolean>;
  signedIn: boolean;
};

type State =
  | { kind: "loading" }
  | { kind: "off" }
  | { kind: "signin" }
  | { kind: "error" }
  | { kind: "ready"; notes: FieldNote[] };

const smallButton = "rounded-lg px-3 py-2 text-sm font-semibold ring-1 ring-inset ring-line hover:bg-panel-2 disabled:opacity-50";

/**
 * The member's own field notes, from Atomic Memory when the API has it on (otherwise nothing renders).
 * A note only reaches the denuncia when the member taps "Agregar a observaciones"; it never changes the detection.
 * The list only changes after the API confirms the save or the delete.
 */
export function NotasSection({ token, expediente, save, signedIn }: Props) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    loadNotes(token)
      .then((r) => setState(r.enabled ? { kind: "ready", notes: r.notes } : { kind: "off" }))
      .catch((e) => {
        if (e instanceof ApiError && e.type === "notes_session_required") setState({ kind: "signin" });
        else if (e instanceof ApiError && e.type === "observer_restricted") setState({ kind: "off" });
        else setState({ kind: "error" });
      });
  }, [token]);

  useEffect(load, [load, signedIn]);

  async function run(action: () => Promise<string>) {
    setBusy(true);
    setMessage(null);
    try {
      setMessage({ ok: true, text: await action() });
    } catch (e) {
      setMessage({ ok: false, text: friendlyError(e) });
    } finally {
      setBusy(false);
    }
  }

  const setNotes = (update: (notes: FieldNote[]) => FieldNote[]) =>
    setState((s) => (s.kind === "ready" ? { kind: "ready", notes: update(s.notes) } : s));

  if (state.kind === "off" || state.kind === "loading") return null;

  return (
    <section aria-labelledby="notas" className={card}>
      <h2 id="notas" className={sectionTitle}>
        Mis notas de campo
      </h2>
      <p className={hint}>
        Solo tú las ves. Te recuerdan lo que aprendiste en otras denuncias. No son evidencia, no cambian la detección y no
        pasan a la denuncia si no las agregas.
      </p>

      {state.kind === "signin" && (
        <p className="mt-4 text-sm">
          <Link href={`/entrar?next=${encodeURIComponent(`/expediente/${token}`)}`} className={textLink}>
            Entra con tu código de WhatsApp
          </Link>{" "}
          para ver y guardar tus notas.
        </p>
      )}

      {state.kind === "error" && (
        <p role="status" className="mt-4 rounded-2xl bg-ambar/10 p-4 text-sm">
          No pudimos cargar tus notas ahora. El expediente sigue igual.{" "}
          <button type="button" className={textLink} onClick={load}>
            Intentar de nuevo
          </button>
        </p>
      )}

      {state.kind === "ready" && (
        <>
          {state.notes.length > 0 ? (
            <ul className="mt-4 space-y-3">
              {state.notes.map((n) => {
                const added = expediente.field_observations.includes(n.text);
                return (
                  <li key={n.id} className="rounded-2xl bg-night p-4 ring-1 ring-line">
                    {editing?.id === n.id ? (
                      <>
                        <label htmlFor={`nota-${n.id}`} className="sr-only">
                          Corregir nota
                        </label>
                        <textarea
                          id={`nota-${n.id}`}
                          className={field}
                          rows={3}
                          maxLength={NOTE_MAX}
                          value={editing.text}
                          onChange={(e) => setEditing({ id: n.id, text: e.currentTarget.value })}
                        />
                        <div className="mt-2 flex flex-wrap gap-2">
                          <button
                            type="button"
                            className={smallButton}
                            disabled={busy || !editing.text.trim()}
                            onClick={() =>
                              run(async () => {
                                const r = await correctNote(token, n.id, editing.text);
                                setNotes((notes) => notes.map((x) => (x.id === n.id ? r.note : x)));
                                setEditing(null);
                                return r.previous_deleted
                                  ? "Nota corregida."
                                  : "Se guardó la corrección, pero la nota anterior no se pudo borrar. Bórrala cuando vuelva a aparecer.";
                              })
                            }
                          >
                            Guardar corrección
                          </button>
                          <button type="button" className={smallButton} disabled={busy} onClick={() => setEditing(null)}>
                            Cancelar
                          </button>
                        </div>
                      </>
                    ) : (
                      <>
                        <p className="whitespace-pre-line">{n.text}</p>
                        <p className="mt-1 text-xs text-muted">
                          {[n.river_name && `Río ${n.river_name}`, noteDate(n.created_at)].filter(Boolean).join(" · ")}
                        </p>
                        <div className="mt-3 flex flex-wrap gap-2">
                          <button
                            type="button"
                            className={smallButton}
                            disabled={busy || added}
                            onClick={() =>
                              run(async () => {
                                const ok = await save({ field_observations: withNote(expediente.field_observations, n.text) });
                                if (!ok) throw new ApiError("No se pudo agregar a las observaciones.", "not_saved", 0);
                                return "Agregada a las observaciones de esta denuncia. Revísala antes de confirmar.";
                              })
                            }
                          >
                            {added ? "Ya está en observaciones" : "Agregar a observaciones"}
                          </button>
                          <button type="button" className={smallButton} disabled={busy} onClick={() => setEditing({ id: n.id, text: n.text })}>
                            Corregir
                          </button>
                          <button
                            type="button"
                            className={smallButton}
                            disabled={busy}
                            onClick={() =>
                              run(async () => {
                                const r = await deleteNote(token, n.id);
                                if (r?.deleted !== true) throw new ApiError("No pudimos confirmar que la nota se borró.", "not_deleted", 0);
                                setNotes((notes) => notes.filter((x) => x.id !== n.id));
                                return "Nota borrada.";
                              })
                            }
                          >
                            Borrar
                          </button>
                        </div>
                      </>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="mt-4 text-sm text-muted">Todavía no tienes notas para este río.</p>
          )}

          <div className="mt-5">
            <label htmlFor="nota-nueva" className={label}>
              Nueva nota
            </label>
            <p className={hint}>Algo que quieras recordar la próxima vez. Revisa que sea correcto antes de guardarla.</p>
            <textarea
              id="nota-nueva"
              className={`${field} mt-2`}
              rows={3}
              maxLength={NOTE_MAX}
              value={draft}
              placeholder="Por ejemplo: el acceso es por la quebrada Lobo, a dos horas desde la comunidad."
              onChange={(e) => setDraft(e.currentTarget.value)}
            />
            <button
              type="button"
              className={`${outlineButton} mt-3`}
              disabled={busy || !draft.trim()}
              onClick={() =>
                run(async () => {
                  const r = await saveNote(token, draft);
                  setNotes((notes) => [r.note, ...notes]);
                  setDraft("");
                  return "Nota guardada en tus notas de campo.";
                })
              }
            >
              Guardar nota
            </button>
          </div>
        </>
      )}

      {message && (
        <p role="status" aria-live="polite" className={`mt-4 text-sm ${message.ok ? "text-muted" : "font-semibold text-rojo-3"}`}>
          {message.text}
        </p>
      )}
    </section>
  );
}
