import { Icon } from "./Icon";
import { dragas } from "./format";
import { ScenePreview } from "./ScenePreview";
import type { Payload } from "./types";
import { card, textLink } from "./ui";



/** Screen 1: what the satellite saw, with the evidence images. Read only. */
export function AlertSection({ incident }: { incident: Payload["incident"] }) {
  const { detections, history, scene } = incident;
  const best = detections[0];

  return (
    <section aria-labelledby="alerta" className={card}>
      <h2 id="alerta" className="text-xl font-black tracking-tight sm:text-2xl">
        {dragas(detections.length)} en el río {incident.river.name}
      </h2>
      <p className="mt-1 text-muted">
        {incident.captured_at_label} · {incident.satellite}
      </p>

      <div className="mt-4">
        <ScenePreview scene={scene} river={incident.river.name} />
      </div>

      <h3 className="mt-5 font-bold">Recortes de cada detección</h3>
      <ul className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
        {detections.map((d, i) => (
          <li key={i} className="min-w-0 overflow-hidden rounded-2xl bg-white ring-1 ring-line">
            <div className="aspect-[4/3] bg-panel-2">
              {d.crop_url ? (
                // Signed links that expire: shown as is, never cached.
                <img src={d.crop_url} alt={`Recorte ${i + 1} de la imagen satelital`} className="size-full object-cover" loading="lazy" />
              ) : (
                <div className="flex size-full flex-col items-center justify-center gap-2 p-4 text-center text-muted">
                  <Icon name="satellite" className="size-8" />
                  <span className="text-sm">La imagen de evidencia se está preparando</span>
                </div>
              )}
            </div>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 p-3 text-sm">
              <dt className="text-muted">Detección</dt>
              <dd className="font-semibold">N° {i + 1}</dd>
              <dt className="text-muted">Confianza</dt>
              <dd className="font-semibold tabular-nums">{Math.round(d.confidence * 100)}%</dd>
              <dt className="text-muted">WGS84</dt>
              <dd className="break-words tabular-nums">
                {d.lat}, {d.lon}
              </dd>
              <dt className="text-muted">UTM</dt>
              <dd className="break-words tabular-nums">{d.utm}</dd>
            </dl>
          </li>
        ))}
      </ul>

      <p className="mt-4 text-sm">{incident.place}.</p>
      {history.length > 0 && (
        <p className="mt-3 rounded-2xl bg-ambar/10 p-4 text-sm">
          Ya se detectó actividad cerca de aquí el {history.map((h) => h.label).join(", el ")}. Ojo de Cóndor lo agrega a la denuncia.
        </p>
      )}
      {history[0]?.preview_url && scene.preview_url && (
        <div className="mt-4">
          <h3 className="font-bold">Antes y ahora</h3>
          <div className="mt-2 grid grid-cols-2 gap-2">
            {[
              { src: history[0].preview_url, label: `Antes · ${history[0].label}` },
              { src: scene.preview_url, label: `Ahora · ${incident.captured_at_label.split(" a las ")[0]}` },
            ].map((p) => (
              <figure key={p.label} className="min-w-0 overflow-hidden rounded-2xl bg-panel-2 ring-1 ring-line">
                <img src={p.src} alt={`Imagen satelital, ${p.label}`} className="aspect-[4/3] w-full object-cover" loading="lazy" />
                <figcaption className="px-2 py-1.5 text-xs text-muted">{p.label}</figcaption>
              </figure>
            ))}
          </div>
        </div>
      )}

      <div className="mt-3 flex flex-col text-sm sm:flex-row sm:gap-6">
        {best && (
          <a href={best.maps_url} target="_blank" rel="noopener noreferrer" className={`${textLink} inline-flex min-h-11 items-center`}>
            Ver en el mapa
          </a>
        )}
        {scene.download_url && (
          <a href={scene.download_url} className={`${textLink} inline-flex min-h-11 items-center`}>
            Descargar imagen original
          </a>
        )}
      </div>
    </section>
  );
}
