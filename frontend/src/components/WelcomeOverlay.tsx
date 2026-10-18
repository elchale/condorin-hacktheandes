import { useEffect, useRef, useState } from "react";
import { firstName } from "../lib/format";

const SHOW_MS = 2200;
const FADE_MS = 450;

/** Full screen "Sesión iniciada" card for a moment after sign in, then fades away. Tap to skip. */
export function WelcomeOverlay({ ong, name, onDone }: { ong: string; name?: string; onDone: () => void }) {
  const [phase, setPhase] = useState<"in" | "out">("in");
  const done = useRef(onDone);
  done.current = onDone;

  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const t = window.setTimeout(() => setPhase("out"), reduced ? 1200 : SHOW_MS);
    return () => window.clearTimeout(t);
  }, []);

  useEffect(() => {
    if (phase !== "out") return;
    const t = window.setTimeout(() => done.current(), FADE_MS);
    return () => window.clearTimeout(t);
  }, [phase]);

  const first = firstName(name);
  return (
    <div
      role="status"
      aria-live="polite"
      onClick={() => setPhase("out")}
      className={`fixed inset-0 z-[2000] flex items-center justify-center bg-rojo p-6 text-white transition-opacity duration-[450ms] ${
        phase === "out" ? "opacity-0" : "opacity-100"
      }`}
    >
      <div className="welcome-in flex max-w-sm flex-col items-center text-center">
        <span className="grid size-24 place-items-center rounded-full bg-white shadow-xl shadow-black/20">
          <img src="/brand/logo.png" width={72} height={72} alt="" className="size-[72px]" />
        </span>
        <span className="mt-6 grid size-10 place-items-center rounded-full bg-white text-green-600" aria-hidden>
          <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 12.5l4.5 4.5L19 7" />
          </svg>
        </span>
        <p className="mt-4 text-lg font-semibold text-white/85">{first ? `Hola, ${first}` : "Sesión iniciada"}</p>
        <p className="mt-1 text-2xl font-black leading-tight tracking-tight [overflow-wrap:anywhere]">
          {ong ? `Entraste como ${ong}` : "Ya puedes ver tus ríos en el mapa"}
        </p>
      </div>
    </div>
  );
}
