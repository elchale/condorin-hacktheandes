import type { ReactNode } from "react";
import { TopBar } from "../../components/TopBar";
import { Link } from "../../router";

type Props = {
  /** Small text on the right of the second bar (save state, ONG name). */
  status?: ReactNode;
  /** Optional back link shown before "Volver al mapa" (for example to the panel). */
  back?: { href: string; label: string };
  width?: "narrow" | "wide";
  children: ReactNode;
};

/**
 * Link pages (evento, expediente) work with the link token alone. Going to the panel is an explicit
 * choice that goes through the WhatsApp code sign in, so a forwarded link never opens a full session.
 */
export const PANEL_SIGN_IN = { href: "/entrar?next=/panel", label: "Entrar a mi panel" };

/** The SPA top bar plus a slim bar with "Volver al mapa", shared by the panel, evento and expediente pages. */
export function PageFrame({ status, back, width = "narrow", children }: Props) {
  const max = width === "wide" ? "max-w-5xl" : "max-w-2xl";
  return (
    <div className="min-h-dvh bg-panel-2 text-ink">
      <TopBar />
      <div className="border-b border-line bg-white">
        <div className={`mx-auto flex ${max} items-center justify-between gap-3 px-4`}>
          <div className="flex min-w-0 items-center gap-4 text-sm">
            <Link href="/" className="flex min-h-11 items-center font-semibold text-rojo-2 underline underline-offset-2 hover:text-rojo-3">
              Volver al mapa
            </Link>
            {back && (
              <Link href={back.href} className="flex min-h-11 items-center font-semibold text-muted hover:text-ink">
                {back.label}
              </Link>
            )}
          </div>
          {status && <div className="min-w-0 truncate text-sm">{status}</div>}
        </div>
      </div>
      <main className={`mx-auto ${max} px-4 py-6`}>{children}</main>
    </div>
  );
}
