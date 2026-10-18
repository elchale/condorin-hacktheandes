import { useEffect, useRef, useState } from "react";
import { BRAND_NAME, PANEL_URL } from "../config";
import { useSession } from "../lib/hooks";
import { signOut } from "../lib/api";
import { firstName } from "../lib/format";
import { Link } from "../router";
import { loadAcerca, loadEntrar, loadPanel } from "../routes";

export function Brand() {
  return (
    <Link href="/" className="flex min-h-11 min-w-0 items-center gap-2 font-extrabold tracking-tight" aria-label={`${BRAND_NAME}, ir al mapa`}>
      <img src="/brand/logo.png" width={32} height={32} alt="" className="size-8 shrink-0" />
      <span className="truncate text-[15px] sm:text-base">{BRAND_NAME}</span>
    </Link>
  );
}

/** Sticky 56 px bar. `back` swaps the "Acerca" link for "Volver al mapa" (inner pages). */
export function TopBar({ back = false }: { back?: boolean }) {
  const session = useSession();
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  // Escape closes the account menu and gives the focus back to its button.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);
  const who = firstName(session?.member.name) || session?.ong.name || "Mi cuenta";

  return (
    <header className="sticky top-0 z-[1100] flex h-14 items-center justify-between gap-2 border-b border-line bg-night px-3 sm:px-4">
      <Brand />
      <nav className="flex shrink-0 items-center gap-1 sm:gap-2" aria-label="Principal">
        {back ? (
          <Link href="/" className="flex min-h-11 items-center whitespace-nowrap px-2 text-sm text-muted hover:text-ink">
            Volver al mapa
          </Link>
        ) : (
          <Link
            href="/acerca"
            onPointerEnter={() => void loadAcerca()}
            className="flex min-h-11 items-center px-2 text-sm text-muted hover:text-ink"
          >
            Acerca
          </Link>
        )}
        {session ? (
          <>
            <Link
              href={PANEL_URL}
              onPointerEnter={() => void loadPanel()}
              className={`min-h-11 items-center whitespace-nowrap rounded-md bg-rojo px-3 text-sm font-bold text-white hover:bg-rojo-2 ${back ? "hidden min-[400px]:flex" : "flex"}`}
            >
              Mi panel
            </Link>
            <div className="relative">
              <button
                ref={button}
                type="button"
                onClick={() => setOpen((v) => !v)}
                aria-expanded={open}
                aria-haspopup="menu"
                aria-label={`Cuenta de ${who}`}
                className="flex min-h-11 min-w-0 max-w-[6.5rem] items-center gap-1.5 rounded-full border border-line bg-panel px-2 text-sm min-[400px]:max-w-32 sm:max-w-44 sm:px-3"
              >
                <span className="grid size-6 shrink-0 place-items-center rounded-full bg-cian/15 text-xs font-bold text-cian">
                  {who.charAt(0).toUpperCase()}
                </span>
                <span className="min-w-0 truncate">{who}</span>
              </button>
              {open && (
                <div role="menu" className="absolute right-0 top-12 w-60 rounded-lg border border-line bg-panel p-3 text-sm shadow-xl">
                  <p className="font-semibold">{session.member.name || "Miembro"}</p>
                  {session.ong.name && <p className="mt-0.5 text-muted">{session.ong.name}</p>}
                  <button
                    role="menuitem"
                    type="button"
                    onClick={() => {
                      setOpen(false);
                      void signOut();
                    }}
                    className="mt-3 min-h-11 w-full rounded-md border border-line text-left px-3 hover:bg-panel-2"
                  >
                    Cerrar sesión
                  </button>
                </div>
              )}
            </div>
          </>
        ) : (
          <Link
            href="/entrar"
            onPointerEnter={() => void loadEntrar()}
            onTouchStart={() => void loadEntrar()}
            className="flex min-h-11 items-center rounded-md bg-rojo px-4 text-sm font-bold text-white hover:bg-rojo-2"
          >
            Entrar
          </Link>
        )}
      </nav>
    </header>
  );
}
