import { useState, type FormEvent } from "react";
import { nowMs } from "../../lib/clock";
import { limaDay } from "../../lib/format";
import { pdfUrl } from "../shared/api";
import type { Authority, Patch, Payload } from "../../types";
import { card, field, fieldError, hint, label, outlineButton, primaryButton, sectionTitle, textLink } from "../shared/ui";

/** Lima day on the API clock (the demo day too), so a filing date is never "tomorrow" for the server. */
const today = () => limaDay(nowMs());

const DATE = new Intl.DateTimeFormat("es-PE", { dateStyle: "long", timeZone: "UTC" });
const formatDate = (iso: string) => DATE.format(new Date(`${iso}T00:00:00Z`));

type Props = {
  token: string;
  expediente: Payload["expediente"];
  authorities: Authority[];
  emailedTo?: string[];
  /** Field errors from the last save (a 400 on a filing lands here). */
  errors: Record<string, string>;
  save: (patch: Patch) => Promise<boolean>;
};

/** Screens 6 and 7: download the final PDF, file it with each authority, record the receipt. */
export function FilingSection({ token, expediente: e, authorities, emailedTo, errors, save }: Props) {
  const chosen = authorities.filter((a) => a.selected);
  const filed = e.status === "filed";

  return (
    <>
      <section aria-labelledby="listo" className="rounded-3xl bg-verde/10 p-5 ring-1 ring-verde/40 sm:p-6">
        <h2 id="listo" className="text-xl font-black tracking-tight">
          {filed ? `Expediente ${e.folio} presentado` : `Expediente ${e.folio} listo para presentar`}
        </h2>
        <p className="mt-1 text-sm text-muted">
          Confirmado{e.finalized_by ? ` por ${e.finalized_by}` : ""}. La huella digital del PDF queda registrada.
        </p>
        {emailedTo && emailedTo.length > 0 && <p className="mt-3 text-sm">Te enviamos el PDF a {emailedTo.join(", ")}.</p>}
        <a href={pdfUrl(token)} target="_blank" rel="noopener" className={`${primaryButton} mt-4 inline-flex justify-center sm:w-auto`}>
          Descargar PDF
        </a>
      </section>

      <ol className="space-y-4">
        {chosen.map((a, i) => (
          <li key={a.code} className={card}>
            <p className="text-sm font-semibold text-muted">Paso {i + 1}</p>
            <h3 className={sectionTitle}>{a.name}</h3>
            {a.filing ? (
              <p className="mt-2 rounded-2xl bg-verde/10 p-4 text-sm">
                Presentado el {formatDate(a.filing.filed_at)} con el número <strong>{a.filing.receipt_number}</strong>
                {a.filing.filed_by ? `, registrado por ${a.filing.filed_by}` : ""}.
              </p>
            ) : (
              <AuthoritySteps authority={a} errors={errors} save={save} />
            )}
          </li>
        ))}
      </ol>

      {e.status === "ready" && (
        <p className="text-center text-sm">
          ¿Hay algo que corregir?{" "}
          <button type="button" className={textLink} onClick={() => save({ reopen: true })}>
            Corregir el expediente
          </button>
        </p>
      )}
    </>
  );
}

function AuthoritySteps({ authority: a, errors, save }: { authority: Authority; errors: Props["errors"]; save: Props["save"] }) {
  const [receipt, setReceipt] = useState("");
  const [date, setDate] = useState(today);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const errorId = `recibo-error-${a.code}`;
  const message = failed ? errors.filings || errors.receipt_number || errors.filed_at || "No pudimos guardar el número. Inténtalo otra vez." : "";

  async function submit(ev: FormEvent) {
    ev.preventDefault();
    setBusy(true);
    setFailed(false);
    const ok = await save({ filings: [{ authority: a.code, receipt_number: receipt.trim(), filed_at: date }] });
    setFailed(!ok);
    setBusy(false);
  }

  return (
    <>
      {a.instructions && <p className="mt-2 whitespace-pre-line text-sm">{a.instructions}</p>}
      {a.max_attachment_mb && <p className={hint}>Acepta adjuntos de hasta {a.max_attachment_mb} MB.</p>}
      <div className="mt-3 flex flex-col gap-2 text-sm">
        {a.submit_url && (
          <a href={a.submit_url} target="_blank" rel="noopener noreferrer" className={outlineButton}>
            Ir al formulario
          </a>
        )}
        {a.phone && <span>Teléfono: {a.phone}</span>}
        {a.address && <span>Dirección: {a.address}</span>}
      </div>

      <form onSubmit={submit} className="mt-5 grid gap-3 border-t border-line pt-4 sm:grid-cols-[1fr_auto]">
        <p className="font-medium sm:col-span-2">¿Ya lo presentaste? Anota el número que te dieron.</p>
        <div className="min-w-0">
          <label htmlFor={`recibo-${a.code}`} className={label}>
            Número de registro
          </label>
          <input
            id={`recibo-${a.code}`}
            className={`${field} mt-2`}
            value={receipt}
            onChange={(ev) => setReceipt(ev.target.value)}
            aria-invalid={message ? true : undefined}
            aria-describedby={message ? errorId : undefined}
            required
            maxLength={120}
          />
        </div>
        <div className="min-w-0">
          <label htmlFor={`fecha-${a.code}`} className={label}>
            Fecha
          </label>
          <input
            id={`fecha-${a.code}`}
            type="date"
            className={`${field} mt-2`}
            value={date}
            max={today()}
            onChange={(ev) => setDate(ev.target.value)}
            required
          />
        </div>
        {message && (
          <p id={errorId} role="alert" className={`${fieldError} sm:col-span-2`}>
            {message}
          </p>
        )}
        <button className={`${primaryButton} sm:col-span-2`} disabled={busy || !receipt.trim()}>
          {busy ? "Guardando…" : "Guardar número de registro"}
        </button>
      </form>
    </>
  );
}
