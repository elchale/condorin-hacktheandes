import { useSyncExternalStore, type AnchorHTMLAttributes, type MouseEvent } from "react";

// A history based router for three routes. About 30 lines instead of a dependency.

const listeners = new Set<() => void>();
const notify = () => listeners.forEach((f) => f());
window.addEventListener("popstate", notify);

function subscribe(f: () => void) {
  listeners.add(f);
  return () => {
    listeners.delete(f);
  };
}

const snapshot = () => location.pathname + location.search;

export function useLocation(): { path: string; search: URLSearchParams } {
  const full = useSyncExternalStore(subscribe, snapshot);
  const i = full.indexOf("?");
  return { path: i < 0 ? full : full.slice(0, i), search: new URLSearchParams(i < 0 ? "" : full.slice(i)) };
}

export function navigate(to: string, { replace = false } = {}) {
  if (replace) history.replaceState(null, "", to);
  else history.pushState(null, "", to);
  notify();
  if (!replace) window.scrollTo(0, 0);
}

type LinkProps = AnchorHTMLAttributes<HTMLAnchorElement> & { href: string };

export function Link({ href, onClick, ...rest }: LinkProps) {
  const handle = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e);
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (!href.startsWith("/") || rest.target) return;
    e.preventDefault();
    navigate(href);
  };
  return <a href={href} onClick={handle} {...rest} />;
}
