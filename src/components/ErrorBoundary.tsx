import { Component, type ReactNode } from "react";

// A render error used to unmount the whole app and leave a blank page. This keeps a way out on screen.

const RELOAD_KEY = "condorin.reloaded";

/** After a deploy the old route chunks are gone: one reload fetches the new ones. */
export function isChunkError(e: unknown): boolean {
  const m = e instanceof Error ? `${e.name} ${e.message}` : String(e);
  return /dynamically imported module|Importing a module script failed|ChunkLoadError|Unable to preload CSS/i.test(m);
}

/** Reload, at most once a minute per tab; false when we just tried (so a broken deploy does not loop). */
export function reloadOnce(): boolean {
  try {
    const last = Number(sessionStorage.getItem(RELOAD_KEY));
    if (last && Date.now() - last < 60_000) return false;
    sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
  } catch {
    return false;
  }
  location.reload();
  return true;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: unknown }> {
  state = { error: null as unknown };

  static getDerivedStateFromError(error: unknown) {
    return { error };
  }

  componentDidCatch(error: unknown) {
    if (isChunkError(error) && reloadOnce()) return;
    console.error(error);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="mx-auto max-w-md px-4 py-16 text-center">
        <h1 className="text-2xl font-black">Algo falló al abrir esta página</h1>
        <p className="mt-2 text-muted">Recarga la página. Si sigue pasando, vuelve al mapa y entra otra vez.</p>
        <div className="mt-6 flex flex-col items-center gap-3">
          <button
            type="button"
            onClick={() => location.reload()}
            className="inline-flex min-h-12 items-center rounded-lg bg-rojo px-5 font-bold text-white"
          >
            Recargar
          </button>
          <a href="/" className="font-medium text-rojo-3 underline underline-offset-2">
            Volver al mapa
          </a>
        </div>
      </main>
    );
  }
}
