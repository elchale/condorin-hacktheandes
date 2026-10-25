import { useCallback, useEffect, useState } from "react";
import { friendlyError } from "../../lib/api";
import { noteDate } from "../expediente/notes";
import type { Antecedentes } from "./api";

type Props = {
  load: () => Promise<Antecedentes>;
  /** Load as soon as it shows (the expediente page); otherwise wait for the member to ask (panel cards). */
  auto?: boolean;
};

type State = { kind: "idle" } | { kind: "loading" } | { kind: "error"; message: string } | { kind: "ready"; data: Antecedentes };

/**
 * What the member's ONG already decided or filed near this place, from its Atomic Memory when the API has it on
 * (otherwise nothing renders). Reference only: it never changes the detection or the decision.
 */
export function AntecedentesList({ load, auto = false }: Props) {
  const [state, setState] = useState<State>({ kind: "idle" });

  const run = useCallback(() => {
    setState({ kind: "loading" });
    load()
      .then((data) => setState({ kind: "ready", data }))
      .catch((e) => setState({ kind: "error", message: friendlyError(e) }));
  }, [load]);

  useEffect(() => {
    if (auto) run();
  }, [auto, run]);

  if (state.kind === "idle") {
    return (
      <button type="button" onClick={run} className="mt-3 min-h-11 px-2 text-sm font-semibold text-rojo-3 underline underline-offset-2">
        Ver antecedentes cerca de aquí
      </button>
    );
  }
  if (state.kind === "loading") return <p className="mt-3 text-sm text-muted">Buscando antecedentes…</p>;
  if (state.kind === "error") {
    return (
      <p role="alert" className="mt-3 text-sm text-rojo-3">
        {state.message}{" "}
        <button type="button" onClick={run} className="font-semibold underline underline-offset-2">
          Reintentar
        </button>
      </p>
    );
  }
  if (!state.data.enabled) return null;
  if (!state.data.antecedentes.length) {
    return auto ? null : <p className="mt-3 text-sm text-muted">Tu ONG no tiene antecedentes cerca de este punto.</p>;
  }
  return (
    <section className="mt-3 rounded-2xl bg-panel-2 p-4" aria-label="Antecedentes cerca de este punto">
      <h4 className="text-sm font-bold">Antecedentes de tu ONG cerca de aquí</h4>
      <ul className="mt-2 space-y-2 text-sm">
        {state.data.antecedentes.map((a) => (
          <li key={a.id}>
            <span className="font-semibold">{a.event_label}</span>
            <span className="text-muted">
              {" · "}a {a.distance_km} km{a.created_at ? ` · ${noteDate(a.created_at)}` : ""}
            </span>
            <span className="block text-muted">{a.text}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
