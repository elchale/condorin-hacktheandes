import { lazy, Suspense, type ComponentType, type LazyExoticComponent, type ReactElement } from "react";
import { Dashboard } from "./pages/Dashboard";
import { Link, useLocation } from "./router";
import { useNoReferrer } from "./lib/meta";
import { TopBar } from "./components/TopBar";
import { loadAcerca, loadEntrar, loadEvento, loadExpediente, loadPanel, loadPrivacidad, loadTerminos } from "./routes";

// Only the dashboard ships in the first chunk; every other route loads on demand.
type Page = LazyExoticComponent<ComponentType<{ token?: string }>>;
const Entrar = lazy(loadEntrar) as Page;
const Acerca = lazy(loadAcerca) as Page;
const Panel = lazy(loadPanel) as Page;
const Evento = lazy(loadEvento) as Page;
const Expediente = lazy(loadExpediente) as Page;
const Privacidad = lazy(loadPrivacidad) as Page;
const Terminos = lazy(loadTerminos) as Page;

const STATIC: Record<string, Page> = {
  "/entrar": Entrar,
  "/acerca": Acerca,
  "/panel": Panel,
  "/privacidad": Privacidad,
  "/terminos": Terminos,
};
const WITH_TOKEN: Record<string, Page> = { evento: Evento, expediente: Expediente };

function Fallback() {
  return <div className="grid-bg min-h-dvh" aria-busy="true" />;
}

function TokenRoute({ Page, token }: { Page: Page; token: string }) {
  useNoReferrer();
  return <Page token={token} />;
}

function NotFound() {
  return (
    <div className="min-h-dvh">
      <TopBar back />
      <main className="mx-auto max-w-md px-4 py-16 text-center">
        <p className="label-caps">Error 404</p>
        <h1 className="mt-2 text-2xl font-black">Esta página no existe</h1>
        <Link href="/" className="mt-6 inline-flex min-h-12 items-center rounded-lg bg-rojo px-5 font-bold text-white">
          Volver al mapa
        </Link>
      </main>
    </div>
  );
}

export function App() {
  const { path } = useLocation();
  const p = path.replace(/\/+$/, "") || "/";
  if (p === "/") return <Dashboard />;

  let page: ReactElement;
  const m = p.match(/^\/(evento|expediente)\/([^/]+)$/);
  if (STATIC[p]) {
    const Page = STATIC[p];
    page = <Page />;
  } else if (m) {
    page = <TokenRoute key={p} Page={WITH_TOKEN[m[1]]} token={decodeURIComponent(m[2])} />;
  } else return <NotFound />;

  return <Suspense fallback={<Fallback />}>{page}</Suspense>;
}
