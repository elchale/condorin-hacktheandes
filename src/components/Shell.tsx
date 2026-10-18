import { useEffect, type ReactNode } from "react";
import { BRAND_NAME } from "../lib/brand";
import { TopBar } from "./TopBar";

type ShellProps = {
  children: ReactNode;
  /** Sets document.title to "<title> · <BRAND_NAME>". */
  title?: string;
  /** Show "Volver al mapa" in the top bar (default true). */
  back?: boolean;
  /** Tailwind classes for <main> (default: centered column, 16 px gutters). */
  className?: string;
};

/** Page frame for inner pages: sticky top bar with the brand and "Volver al mapa", then the content. */
export function Shell({ children, title, back = true, className = "mx-auto w-full max-w-3xl px-4 py-6 sm:px-6" }: ShellProps) {
  useEffect(() => {
    if (!title) return;
    const prev = document.title;
    document.title = `${title} · ${BRAND_NAME}`;
    return () => {
      document.title = prev;
    };
  }, [title]);
  return (
    <div className="flex min-h-dvh flex-col">
      <TopBar back={back} />
      <main className={`flex-1 ${className}`}>{children}</main>
    </div>
  );
}
