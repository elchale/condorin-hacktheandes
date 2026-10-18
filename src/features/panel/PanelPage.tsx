import { useCallback, useEffect, useState } from "react";
import { WelcomeOverlay } from "../../components/WelcomeOverlay";
import { useSession } from "../../lib/hooks";
import { clearSession } from "../../lib/storage";
import { navigate, useLocation } from "../../router";
import { ExpedienteError, expedienteToken, loadMe } from "../shared/api";
import { PageFrame } from "../shared/PageFrame";
import type { ApiError, Incident, Panel } from "../shared/types";
import { Skeleton } from "../shared/Skeleton";
import { card, primaryButton } from "../shared/ui";
import { IncidentCard } from "./IncidentCard";
import { PanelTotals } from "./PanelTotals";
import { TodayClock } from "./TodayClock";

const UNKNOWN: ApiError = { message: "No pudimos conectarnos con Ojo de Cóndor. Inténtalo otra vez en un momento.", type: "unknown", field_errors: {} };

/** /panel: the member's ONG, its detections and the next action for each. Needs the bearer session. */
export default function PanelPage(_props: { token?: string }) {
  const session = useSession();
  const { search } = useLocation();
  const [data, setData] = useState<Panel | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [openError, setOpenError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [welcome, setWelcome] = useState(search.get("bienvenida") === "1");
  const sessionToken = session?.token ?? null;
  const [attempt, setAttempt] = useState(0);
  const retry = () => {
    setError(null);
    setAttempt((n) => n + 1);
  };

  useEffect(() => {
    if (!sessionToken) {
      navigate("/entrar?next=/panel", { replace: true });
      return;
    }
    let alive = true;
    loadMe(sessionToken)
      .then((panel) => alive && setData(panel))
      .catch((err) => {
        if (!alive) return;
        if (err instanceof ExpedienteError && err.status === 401) {
          clearSession(); // the effect runs again without a session and sends the member to /entrar
          return;
        }
        setError(err instanceof ExpedienteError ? err.body : UNKNOWN);
      });
    return () => {
      alive = false;
    };
  }, [sessionToken, attempt]);

  const open = useCallback(
    async (incident: Incident, to: "expediente" | "evento") => {
      if (!sessionToken) return;
      setBusy(true);
      setOpenError(false);
      try {
        const { token } = await expedienteToken(sessionToken, incident.id);
        navigate(`/${to}/${encodeURIComponent(token)}`);
      } catch {
        setOpenError(true);
        setBusy(false);
      }
    },
    [sessionToken],
  );

  if (!sessionToken) return null;

  if (error) {
    return (
      <PageFrame width="wide">
        <section role="alert" className={`${card} text-center`}>
          <h1 className="text-xl font-black">No pudimos abrir tu panel</h1>
          <p className="mt-2 text-muted">{error.message}</p>
          <button type="button" onClick={retry} className={`${primaryButton} mt-6`}>
            Intentar de nuevo
          </button>
        </section>
      </PageFrame>
    );
  }

  if (!data) {
    return (
      <PageFrame width="wide">
        <Skeleton kind="panel" label="Cargando tu panel" />
      </PageFrame>
    );
  }

  const { member, ong, totals, incidents } = data;
  return (
    <PageFrame width="wide" status={<span className="text-muted">{ong.name}</span>}>
      {welcome && (
        <WelcomeOverlay
          ong={ong.name}
          name={member.name}
          onDone={() => {
            setWelcome(false);
            navigate("/panel", { replace: true });
          }}
        />
      )}
      <header>
        <p className="text-sm font-semibold text-muted">{ong.name}</p>
        <h1 className="mt-1 text-2xl font-black tracking-tight sm:text-3xl">
          {member.name ? `Hola, ${member.name.split(" ")[0]}` : "Hola"}
        </h1>
        <p className="mt-2 text-muted">
          {ong.rivers.length
            ? `Tu ONG vigila ${ong.rivers.map((r) => `el río ${r.name}`).join(", ")}. Aquí están las detecciones y lo que puedes hacer con cada una.`
            : "Tu ONG todavía no vigila ningún río."}
        </p>
      </header>

      <TodayClock clock={data.clock} />

      {member.joined_now && (
        <p className="mt-6 rounded-2xl bg-verde/10 p-4 text-sm text-ink" role="status">
          Te uniste a {ong.name}. Desde ahora también te llegarán sus alertas por WhatsApp.
        </p>
      )}
      {openError && (
        <p role="alert" className="mt-6 rounded-2xl bg-rojo/10 p-4 text-sm text-rojo-3">
          No pudimos abrir ese expediente. Inténtalo otra vez.
        </p>
      )}

      <PanelTotals totals={totals} />

      <h2 className="mt-10 text-lg font-bold">Detecciones</h2>
      {incidents.length ? (
        <ul className="mt-3 grid gap-4 lg:grid-cols-2">
          {incidents.map((incident) => (
            <li key={incident.id} className="min-w-0">
              <IncidentCard incident={incident} onOpen={open} busy={busy} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 rounded-3xl bg-panel p-6 text-muted ring-1 ring-line">
          Todavía no hay detecciones en los ríos de tu ONG. Te avisaremos por WhatsApp apenas aparezca una.
        </p>
      )}
    </PageFrame>
  );
}
