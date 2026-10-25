import { ApiError } from "../../lib/api";
import { useCallback, useEffect, useState } from "react";
import { WelcomeOverlay } from "../../components/WelcomeOverlay";
import { useSession } from "../../lib/hooks";
import { clearToken } from "../../lib/session";
import { navigate, useLocation } from "../../router";
import { clearTriage, expedienteToken, loadIncidents, loadMe, pageOf, setTriage } from "../shared/api";
import { PageFrame } from "../shared/PageFrame";
import type { Incident, Panel, Triage, TriageReason, TriageStatus } from "../../types";
import { Skeleton } from "../shared/Skeleton";
import { card, outlineButton, primaryButton } from "../shared/ui";
import { IncidentCard } from "./IncidentCard";
import { PanelTotals } from "./PanelTotals";
import { TRIAGE_LABEL } from "./triage";
import { TodayClock } from "./TodayClock";

const UNKNOWN = new ApiError("No pudimos conectarnos con Ojo de Cóndor. Inténtalo otra vez en un momento.", "unknown", 0);

/** /panel: the member's ONG, its detections and the next action for each. Needs the bearer session. */
export default function PanelPage(_props: { token?: string }) {
  const session = useSession();
  const { search } = useLocation();
  const [data, setData] = useState<Panel | null>(null);
  // Pages loaded with "Ver más" after the first one, which comes inside /me.
  const [more, setMore] = useState<Incident[]>([]);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [openError, setOpenError] = useState(false);
  const [busy, setBusy] = useState(false);
  // Decisions made on this page, applied over the loaded cards; `null` is "back to new".
  const [triaged, setTriaged] = useState<Record<number, Triage | null>>({});
  const [triageError, setTriageError] = useState(false);
  const [filter, setFilter] = useState<TriageStatus | "new" | "all">("all");
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
      .then((panel) => {
        if (!alive) return;
        setData(panel);
        setMore([]);
        setTriaged({});
        setNextPage(pageOf(panel.pagination?.next ?? null));
      })
      .catch((err) => {
        if (!alive) return;
        if (err instanceof ApiError && err.status === 401) {
          clearToken(); // the effect runs again without a session and sends the member to /entrar
          return;
        }
        setError(err instanceof ApiError ? err : UNKNOWN);
      });
    return () => {
      alive = false;
    };
  }, [sessionToken, attempt]);

  const showMore = async () => {
    if (!sessionToken || !nextPage || loadingMore) return;
    setLoadingMore(true);
    setMoreError(false);
    try {
      const page = await loadIncidents(sessionToken, nextPage);
      // A scene that arrived meanwhile shifts the pages by one: never show the same card twice.
      setMore((prev) => {
        const seen = new Set([...(data?.incidents ?? []), ...prev].map((i) => i.id));
        return [...prev, ...page.results.filter((i) => !seen.has(i.id))];
      });
      setNextPage(pageOf(page.next));
    } catch {
      setMoreError(true); // a 401 already signed the member out, and the effect sends them to /entrar
    } finally {
      setLoadingMore(false);
    }
  };

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

  const decide = useCallback(
    async (incident: Incident, change: () => Promise<Triage | null>) => {
      if (!sessionToken) return;
      setBusy(true);
      setTriageError(false);
      try {
        const triage = await change();
        setTriaged((prev) => ({ ...prev, [incident.id]: triage }));
        // The totals follow the decision (a rejected incident is no pending work); the cards stay as they are.
        const fresh = await loadMe(sessionToken);
        setData((prev) => (prev ? { ...prev, totals: fresh.totals } : prev));
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) clearToken();
        else setTriageError(true);
      } finally {
        setBusy(false);
      }
    },
    [sessionToken],
  );
  const onTriage = useCallback(
    (incident: Incident, status: TriageStatus, reason?: TriageReason) =>
      void decide(incident, () => setTriage(sessionToken ?? "", incident.id, status, reason)),
    [decide, sessionToken],
  );
  const onClearTriage = useCallback(
    (incident: Incident) => void decide(incident, () => clearTriage(sessionToken ?? "", incident.id)),
    [decide, sessionToken],
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

  const { member, ong, totals } = data;
  const loaded = [...data.incidents, ...more].map((i) => (i.id in triaged ? { ...i, triage: triaged[i.id] } : i));
  const counts = totals.triage;
  const incidents = filter === "all" ? loaded : loaded.filter((i) => (i.triage?.status ?? "new") === filter);
  const filters: [TriageStatus | "new" | "all", string, number][] = counts
    ? [
        ["all", "Todas", totals.incidents],
        ["new", "Por revisar", counts.new],
        ["confirmed", TRIAGE_LABEL.confirmed, counts.confirmed],
        ["verified_field", TRIAGE_LABEL.verified_field, counts.verified_field],
        ["false_positive", TRIAGE_LABEL.false_positive, counts.false_positive],
      ]
    : [];
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
      {filters.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Filtrar por decisión de tu ONG">
          {filters.map(([key, label, n]) => (
            <button
              key={key}
              type="button"
              aria-pressed={filter === key}
              onClick={() => setFilter(key)}
              className={`min-h-11 rounded-xl px-3 py-2 text-sm font-semibold ring-1 ring-inset ${filter === key ? "bg-ink text-white ring-ink" : "bg-panel text-ink ring-line hover:bg-panel-2"}`}
            >
              {label} <span className="tabular-nums">{n}</span>
            </button>
          ))}
        </div>
      )}
      {triageError && (
        <p role="alert" className="mt-3 rounded-2xl bg-rojo/10 p-4 text-sm text-rojo-3">
          No pudimos guardar tu decisión. Inténtalo otra vez.
        </p>
      )}
      {incidents.length || nextPage ? (
        <>
          <ul className="mt-3 grid gap-4 lg:grid-cols-2">
            {incidents.map((incident) => (
              <li key={incident.id} className="min-w-0">
                <IncidentCard
                  incident={incident}
                  onOpen={open}
                  busy={busy}
                  canAct={member.can_act ?? false}
                  onTriage={onTriage}
                  onClearTriage={onClearTriage}
                />
              </li>
            ))}
          </ul>
          <div className="mt-6 flex flex-col items-center gap-2 text-sm text-muted">
            <p aria-live="polite">
              {filter === "all"
                ? `Mostrando ${incidents.length} de ${Math.max(totals.incidents, incidents.length)} detecciones`
                : `${incidents.length} en esta lista${nextPage ? ". Carga más detecciones para ver otras." : ""}`}
            </p>
            {moreError && (
              <p role="alert" className="text-rojo-3">
                No pudimos cargar más detecciones. Inténtalo otra vez.
              </p>
            )}
            {nextPage && (
              <button type="button" onClick={() => void showMore()} disabled={loadingMore} className={outlineButton}>
                {loadingMore ? "Cargando…" : "Ver más detecciones"}
              </button>
            )}
          </div>
        </>
      ) : (
        <p className="mt-3 rounded-3xl bg-panel p-6 text-muted ring-1 ring-line">
          {filter === "all"
            ? "Todavía no hay detecciones en los ríos de tu ONG. Te avisaremos por WhatsApp apenas aparezca una."
            : "No hay detecciones con esa decisión."}
        </p>
      )}
    </PageFrame>
  );
}
