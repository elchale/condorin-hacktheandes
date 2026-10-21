import { Skeleton } from "../shared/Skeleton";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../../lib/api";
import { useSession } from "../../lib/hooks";
import { Link } from "../../router";
import { AlertSection } from "../shared/AlertSection";
import { loadExpediente, saveExpediente } from "../shared/api";
import { OpenInBrowser } from "../shared/OpenInBrowser";
import { PageFrame, PANEL_SIGN_IN } from "../shared/PageFrame";
import { routeToken } from "../shared/routeToken";
import type { Patch, Payload } from "../../types";
import { card, fieldId, primaryButton } from "../shared/ui";
import { AuthoritiesSection } from "./AuthoritiesSection";
import { ConfirmSection } from "./ConfirmSection";
import { DenuncianteSection } from "./DenuncianteSection";
import { FilingSection } from "./FilingSection";
import { HechosSection } from "./HechosSection";
import { NotasSection } from "./NotasSection";

type SaveState = "idle" | "saving" | "saved" | "error";

const flatten = (errors: Record<string, string[]>) =>
  Object.fromEntries(Object.entries(errors).map(([k, v]) => [k, v[0]]));

/**
 * condorin.pe/expediente/<token>: from the WhatsApp alert (or the panel) to a denuncia ready to file.
 * The token is the whole auth for the expediente; signing in to the site is only for the panel.
 */
export default function ExpedientePage({ token: tokenProp }: { token?: string }) {
  const token = routeToken(tokenProp, "/expediente");
  const [data, setData] = useState<Payload | null>(null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [notice, setNotice] = useState("");
  const [emailedTo, setEmailedTo] = useState<string[]>();
  // The link token opens this page on its own; the panel needs a real sign in (WhatsApp code).
  const signedIn = Boolean(useSession());

  const load = useCallback(() => {
    setLoadError(null);
    loadExpediente(token)
      .then(setData)
      .catch((err) => setLoadError(err instanceof ApiError ? err : new ApiError(String(err), "unknown", 0)));
  }, [token]);

  useEffect(load, [load]);

  // Blurring two fields quickly sends two PATCHes; run them in order so an older answer never
  // replaces a newer one on screen (which looked like the second field had been lost).
  const queue = useRef<Promise<unknown>>(Promise.resolve());

  const send = useCallback(
    async (patch: Patch) => {
      setSaveState("saving");
      setNotice("");
      try {
        const next = await saveExpediente(token, patch);
        setData(next);
        setErrors((prev) => {
          const rest = { ...prev };
          for (const key of Object.keys(patch)) delete rest[key];
          return rest;
        });
        setSaveState("saved");
        return true;
      } catch (err) {
        setSaveState("error");
        if (err instanceof ApiError) {
          if (Object.keys(err.fieldErrors).length) setErrors((prev) => ({ ...prev, ...flatten(err.fieldErrors) }));
          else setNotice(err.message);
          if (err.type === "expediente_locked") load();
        } else {
          setNotice((err as Error).message);
        }
        return false;
      }
    },
    [token, load],
  );

  const save = useCallback(
    (patch: Patch): Promise<boolean> => {
      const run = queue.current.then(() => send(patch));
      queue.current = run;
      return run;
    },
    [send],
  );

  const saveField = useCallback((name: string, value: string) => void save({ [name]: value } as Patch), [save]);

  function showMissing(fieldErrors: Record<string, string[]>) {
    setErrors(flatten(fieldErrors));
    const first = Object.keys(fieldErrors)[0];
    // The section may need a render to open before the field exists.
    requestAnimationFrame(() => document.getElementById(fieldId(first))?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  if (loadError) {
    return (
      <Frame signedIn={signedIn}>
        <LoadError error={loadError} onRetry={load} />
      </Frame>
    );
  }
  if (!data) {
    return (
      <Frame signedIn={signedIn}>
        <OpenInBrowser token={token} />
        <div className="mt-4">
          <Skeleton kind="page" label="Abriendo el expediente" />
        </div>
      </Frame>
    );
  }

  const { expediente: e, member, authorities, incident } = data;
  const missing = Object.keys(e.missing).length;
  const someoneElse = e.updated_by && e.updated_by !== member.name;

  return (
    <Frame signedIn={signedIn} saveState={e.status === "draft" ? saveState : "idle"}>
      <div className="space-y-4">
        <OpenInBrowser token={token} />
        <header>
          <p className="text-sm font-semibold text-muted">{data.ong.name}</p>
          <h1 className="text-2xl font-black tracking-tight sm:text-3xl">
            {e.status === "draft" ? "Prepara la denuncia" : `Expediente ${e.folio}`}
          </h1>
          {e.status === "draft" && (
            <p className="mt-1 text-muted">
              {missing ? `${missing === 1 ? "Falta 1 dato" : `Faltan ${missing} datos`} para terminar. Todo se guarda solo.` : "Está completo. Revisa y confirma."}
            </p>
          )}
        </header>

        {someoneElse && e.status === "draft" && (
          <p className="rounded-2xl bg-ambar/10 p-4 text-sm">{e.updated_by} también está trabajando en este expediente.</p>
        )}
        {notice && (
          <p role="alert" className="rounded-2xl bg-rojo/10 p-4 text-sm text-rojo-3">
            {notice}
          </p>
        )}

        <AlertSection incident={incident} />

        {e.status === "draft" ? (
          <>
            <DenuncianteSection expediente={e} errors={errors} onSave={saveField} />
            <HechosSection expediente={e} errors={errors} onSave={saveField} />
            <NotasSection key={`${token}:${signedIn}`} token={token} expediente={e} save={save} signedIn={signedIn} />
            <AuthoritiesSection authorities={authorities} expediente={e} errors={errors} save={save} />
            <ConfirmSection
              token={token}
              expediente={e}
              errors={errors}
              save={save}
              onMissing={showMissing}
              onConfirmed={(payload) => {
                setData(payload);
                setEmailedTo(payload.sent?.emailed_to);
                setErrors({});
                window.scrollTo({ top: 0, behavior: "smooth" });
              }}
            />
          </>
        ) : (
          <FilingSection token={token} expediente={e} authorities={authorities} emailedTo={emailedTo} errors={errors} save={save} />
        )}
      </div>
    </Frame>
  );
}

const SAVE_LABEL: Record<SaveState, string> = { idle: "", saving: "Guardando…", saved: "Guardado", error: "No se guardó" };

function Frame({ signedIn, saveState = "idle", children }: { signedIn: boolean; saveState?: SaveState; children: ReactNode }) {
  return (
    <PageFrame
      back={signedIn ? { href: "/panel", label: "Mi panel" } : PANEL_SIGN_IN}
      status={
        <span aria-live="polite" className={saveState === "error" ? "font-semibold text-rojo-3" : "text-muted"}>
          {SAVE_LABEL[saveState]}
        </span>
      }
    >
      {children}
    </PageFrame>
  );
}

function LoadError({ error, onRetry }: { error: ApiError; onRetry: () => void }) {
  const known: Record<string, { title: string; body: string }> = {
    link_expired: { title: "Este enlace venció", body: "Pide a tu ONG que te reenvíe la alerta, o entra a tu panel." },
    not_found: { title: "No encontramos este expediente", body: "Revisa que el enlace esté completo." },
  };
  const page = known[error.type];
  return (
    <section className={`${card} text-center`}>
      <h1 className="text-xl font-black">{page?.title ?? "No pudimos abrir el expediente"}</h1>
      <p className="mt-2 text-muted">{page?.body ?? error.message}</p>
      {page ? (
        <Link href="/panel" className={`${primaryButton} mt-6 inline-block`}>
          Ir a mi panel
        </Link>
      ) : (
        <button type="button" className={`${primaryButton} mt-6`} onClick={onRetry}>
          Intentar de nuevo
        </button>
      )}
    </section>
  );
}
