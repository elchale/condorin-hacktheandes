import { useCallback, useEffect, useState } from "react";
import { Link } from "../../router";
import { AlertSection } from "../shared/AlertSection";
import { ExpedienteError, loadEvento, type Evento } from "../shared/api";
import { Icon } from "../shared/Icon";
import { OpenInBrowser } from "../shared/OpenInBrowser";
import { Skeleton } from "../shared/Skeleton";
import { PageFrame } from "../shared/PageFrame";
import { routeToken } from "../shared/routeToken";
import type { ApiError } from "../shared/types";
import { card, outlineButton, primaryButton } from "../shared/ui";
import { useLinkSignIn } from "../shared/useLinkSignIn";

/** What to do next with this event, as one button to the expediente page. */
function nextAction(e: Evento["expediente"]) {
  if (!e) return { note: "Nadie de tu ONG ha empezado la denuncia todavía.", button: "Crear expediente" };
  if (e.status === "draft") {
    return {
      note: e.missing ? `Hay un borrador. ${e.missing === 1 ? "Falta 1 dato" : `Faltan ${e.missing} datos`}.` : "Hay un borrador listo para revisar y confirmar.",
      button: "Continuar expediente",
    };
  }
  if (e.status === "ready") return { note: `${e.folio} está listo. Falta presentarlo ante las autoridades.`, button: "Presentar a las autoridades" };
  return { note: `${e.folio} ya fue presentado.`, button: "Ver expediente" };
}

/**
 * condorin.pe/evento/<token>: the detection itself (evidence, satellite map, coordinates) and the choice
 * to start the denuncia. Opened from "Ver evento" in the WhatsApp alert or from the panel.
 */
export default function EventoPage({ token: tokenProp }: { token?: string }) {
  const token = routeToken(tokenProp, "/evento");
  const [data, setData] = useState<Evento | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const { signedIn, overlay } = useLinkSignIn(token);

  const load = useCallback(() => {
    loadEvento(token)
      .then(setData)
      .catch((err) =>
        setError(err instanceof ExpedienteError ? err.body : { message: "No pudimos abrir el evento.", type: "unknown", field_errors: {} }),
      );
  }, [token]);

  useEffect(load, [load]);

  const best = data?.incident.detections[0];
  const action = data && nextAction(data.expediente);

  return (
    <PageFrame
      back={signedIn ? { href: "/panel", label: "Todos los eventos" } : undefined}
      status={data && <span className="text-muted">{data.ong.name}</span>}
    >
      {overlay}
      <div className="space-y-4">
        <OpenInBrowser token={token} />

        {error ? (
          <section className={`${card} text-center`}>
            <h1 className="text-xl font-black">{error.type === "link_expired" ? "Este enlace venció" : "No pudimos abrir el evento"}</h1>
            <p className="mt-2 text-muted">{error.type === "not_found" ? "Revisa que el enlace esté completo." : error.message}</p>
            {error.type === "link_expired" || error.type === "not_found" ? (
              <Link href="/panel" className={`${primaryButton} mt-6 inline-block`}>
                Ir a mis eventos
              </Link>
            ) : (
              <button
                type="button"
                className={`${primaryButton} mt-6`}
                onClick={() => {
                  setError(null);
                  load();
                }}
              >
                Intentar de nuevo
              </button>
            )}
          </section>
        ) : !data ? (
          <Skeleton kind="page" label="Abriendo el evento" />
        ) : (
          <>
            <AlertSection incident={data.incident} />

            {best && (
              <section aria-labelledby="ubicacion" className={card}>
                <h2 id="ubicacion" className="text-lg font-bold">
                  Ubicación
                </h2>
                <p className="mt-1 text-sm text-muted">
                  {best.lat}, {best.lon} · UTM {best.utm}
                </p>
                <div className="mt-4 aspect-[4/3] overflow-hidden rounded-2xl bg-panel-2 ring-1 ring-line">
                  <iframe
                    title={`Mapa satelital del punto en el río ${data.incident.river.name}`}
                    src={`https://maps.google.com/maps?q=${best.lat},${best.lon}&t=k&z=15&output=embed`}
                    className="size-full border-0"
                    loading="lazy"
                    referrerPolicy="no-referrer"
                  />
                </div>
                <a href={best.maps_url} target="_blank" rel="noopener noreferrer" className={`${outlineButton} mt-4`}>
                  Abrir en Google Maps
                </a>
                {data.incident.discarded > 0 && (
                  <p className="mt-4 text-sm text-muted">
                    {data.incident.discarded === 1 ? "Otra detección quedó" : `Otras ${data.incident.discarded} detecciones quedaron`} por debajo
                    del umbral de {Math.round(data.incident.threshold * 100)}% y no se incluyen.
                  </p>
                )}
              </section>
            )}

            {action && (
              <section aria-labelledby="accion" className={card}>
                <h2 id="accion" className="text-lg font-bold">
                  ¿Qué quieres hacer?
                </h2>
                <p className="mt-1 text-muted">{action.note}</p>
                <Link href={`/expediente/${token}`} className={`${primaryButton} mt-4 inline-flex items-center justify-center gap-2`}>
                  {action.button}
                  <Icon name="arrow" className="size-5" />
                </Link>
                {signedIn && (
                  <Link href="/panel" className={`${outlineButton} mt-3 w-full`}>
                    Ver todos los eventos
                  </Link>
                )}
              </section>
            )}
          </>
        )}
      </div>
    </PageFrame>
  );
}
