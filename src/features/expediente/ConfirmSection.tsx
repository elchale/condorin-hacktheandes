import { useEffect, useState } from "react";
import { ExpedienteError, pdfUrl, sendExpediente } from "../shared/api";
import type { Patch, Payload } from "../shared/types";
import { card, field, fieldError, fieldId, hint, outlineButton, primaryButton, sectionTitle, textLink } from "../shared/ui";

const RESEND_SECONDS = 45;

type Props = {
  token: string;
  expediente: Payload["expediente"];
  errors: Record<string, string>;
  save: (patch: Patch) => void;
  /** 400 from /enviar: what is still missing. */
  onMissing: (errors: Record<string, string[]>) => void;
  onConfirmed: (payload: Payload) => void;
};

/** Screen 5: check the draft, declare it true, and confirm with the code sent by WhatsApp. */
export function ConfirmSection({ token, expediente: e, errors, save, onMissing, onConfirmed }: Props) {
  const [phoneHint, setPhoneHint] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [wait, setWait] = useState(0);
  const missing = Object.keys(e.missing).length;

  useEffect(() => {
    if (wait <= 0) return;
    const t = setTimeout(() => setWait(wait - 1), 1000);
    return () => clearTimeout(t);
  }, [wait]);

  async function requestCode() {
    setBusy(true);
    setError("");
    try {
      const res = await sendExpediente(token);
      if (res.status === 202) {
        setPhoneHint(res.data.phone_hint);
        setCode("");
        setWait(RESEND_SECONDS);
      }
    } catch (err) {
      if (err instanceof ExpedienteError && err.status === 400) onMissing(err.body.field_errors);
      else setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function confirm(value: string) {
    setBusy(true);
    setError("");
    try {
      const res = await sendExpediente(token, value);
      if (res.status === 200) onConfirmed(res.data);
    } catch (err) {
      setError((err as Error).message);
      if (err instanceof ExpedienteError && err.body.type === "code_expired") setPhoneHint(null);
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="confirmar" className={card}>
      <h2 id="confirmar" className={sectionTitle}>
        Revisar y confirmar
      </h2>
      <p className={hint}>Mira el documento tal como lo recibirán las autoridades antes de confirmarlo.</p>
      <a href={pdfUrl(token)} target="_blank" rel="noopener" className={`${outlineButton} mt-4`}>
        Ver borrador en PDF
      </a>

      <label id={fieldId("truth_declared")} className="mt-5 flex scroll-mt-24 cursor-pointer gap-3">
        <input
          type="checkbox"
          className="mt-1 size-5 shrink-0 accent-rojo"
          checked={e.truth_declared}
          onChange={(ev) => save({ truth_declared: ev.target.checked })}
        />
        <span>Declaro que los hechos descritos son verdaderos según lo que sé.</span>
      </label>
      {errors.truth_declared && <p className={fieldError}>{errors.truth_declared}</p>}

      {!phoneHint ? (
        <>
          <button type="button" className={`${primaryButton} mt-6`} disabled={busy} onClick={requestCode}>
            {busy ? "Revisando…" : "Confirmar expediente"}
          </button>
          {missing > 0 && (
            <p className={`${hint} text-center`}>
              {missing === 1 ? "Falta 1 dato." : `Faltan ${missing} datos.`} Al confirmar te llevamos al primero.
            </p>
          )}
        </>
      ) : (
        <form className="mt-6 space-y-3" onSubmit={(ev) => (ev.preventDefault(), confirm(code))}>
          <label htmlFor="codigo" className="block font-medium">
            Te enviamos un código por WhatsApp al {phoneHint}
          </label>
          <input
            id="codigo"
            className={`${field} text-center text-2xl tracking-[0.5em]`}
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            placeholder="000000"
            value={code}
            disabled={busy}
            autoFocus
            onChange={(ev) => {
              const digits = ev.target.value.replace(/\D/g, "");
              setCode(digits);
              if (digits.length === 6) confirm(digits);
            }}
          />
          <button className={primaryButton} disabled={busy || code.length !== 6}>
            {busy ? "Confirmando…" : "Confirmar con el código"}
          </button>
          <p className="text-center text-sm">
            {wait > 0 ? (
              <span className="text-muted">Puedes pedir otro código en {wait} s</span>
            ) : (
              <button type="button" className={textLink} onClick={requestCode} disabled={busy}>
                Enviar otro código
              </button>
            )}
          </p>
        </form>
      )}

      {error && (
        <p role="alert" className="mt-4 rounded-xl bg-rojo/10 px-4 py-3 text-sm text-rojo-3">
          {error}
        </p>
      )}
    </section>
  );
}
