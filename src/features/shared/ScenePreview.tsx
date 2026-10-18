import { useState } from "react";
import type { Payload } from "./types";

type Scene = Payload["incident"]["scene"];

/**
 * The whole satellite scene with a box on every detection, as the detector saw it. Boxes are placed in
 * percentages of the image's natural size, so they stay on target at any width. Numbers match the crops.
 */
export function ScenePreview({ scene, river }: { scene: Scene; river: string }) {
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  if (!scene.preview_url) return null;
  let n = 0;

  return (
    <figure className="overflow-hidden rounded-2xl bg-panel-2 ring-1 ring-line">
      {/* Fixed 4:3 box, so every card has the same height; the scene is fitted inside (boxes stay on target). */}
      <div className="flex aspect-[4/3] items-center justify-center bg-zinc-200">
      <div
        className="relative max-h-full max-w-full"
        style={size ? (size.w / size.h > 4 / 3 ? { width: "100%", aspectRatio: `${size.w} / ${size.h}` } : { height: "100%", aspectRatio: `${size.w} / ${size.h}` }) : { width: "100%", height: "100%" }}
      >
        {/* Signed links that expire: shown as is, never cached. */}
        <img
          src={scene.preview_url}
          alt={`Imagen satelital completa del río ${river} con las detecciones marcadas`}
          className="block size-full object-contain"
          loading="lazy"
          onLoad={(e) => setSize({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
        />
        {size &&
          scene.boxes.map((b, i) => {
            const [x, y, w, h] = b.bbox;
            const label = b.alerting ? String(++n) : null;
            return (
              <span
                key={i}
                className={`absolute rounded-sm ${b.alerting ? "border-2 border-rojo shadow-[0_0_0_1px_rgba(0,0,0,0.35)]" : "border border-dashed border-white/70"}`}
                style={{ left: `${(x / size.w) * 100}%`, top: `${(y / size.h) * 100}%`, width: `${(w / size.w) * 100}%`, height: `${(h / size.h) * 100}%` }}
              >
                <span
                  className={`absolute -top-px left-0 -translate-y-full whitespace-nowrap rounded-t-sm px-1 font-mono text-[10px] font-bold leading-4 sm:text-xs ${
                    b.alerting ? "bg-rojo text-white" : "bg-white/80 text-ink"
                  }`}
                >
                  {label ? `${label} · ${Math.round(b.confidence * 100)}%` : `${Math.round(b.confidence * 100)}%`}
                </span>
              </span>
            );
          })}
      </div>
      </div>
      <figcaption className="flex flex-wrap justify-between gap-x-4 gap-y-1 px-3 py-2 text-xs text-muted">
        <span>Escena completa · recuadros rojos: superan el umbral</span>
        {scene.md5_hash && <span className="font-mono">MD5 {scene.md5_hash.slice(0, 12)}…</span>}
      </figcaption>
    </figure>
  );
}
