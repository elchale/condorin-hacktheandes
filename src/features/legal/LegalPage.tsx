import { useEffect, type ReactNode } from "react";
import { BRAND_NAME } from "../../config";
import { PageFrame } from "../shared/PageFrame";
import { COMPANY, LEGAL_UPDATED_AT } from "./company";

export function LegalPage({ title, children }: { title: string; children: ReactNode }) {
  useEffect(() => {
    document.title = `${title} · ${BRAND_NAME}`;
  }, [title]);
  return (
    <PageFrame width="wide">
      <article className="mx-auto max-w-3xl py-4 sm:py-8">
        <h1 className="text-3xl font-black tracking-tight sm:text-4xl">{title}</h1>
        <p className="mt-2 text-sm text-muted">Última actualización: {LEGAL_UPDATED_AT}</p>
        <div className="mt-8 space-y-4 rounded-3xl bg-panel p-6 ring-1 ring-line sm:p-10">{children}</div>
        <p className="mt-6 text-sm text-muted">
          {COMPANY.legalName} · RUC {COMPANY.ruc}. Ojo de Cóndor no es una entidad del Estado peruano.
        </p>
      </article>
    </PageFrame>
  );
}

export function LegalSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3 pt-4 first:pt-0 [&_li]:ml-5 [&_li]:list-disc [&_p]:leading-relaxed [&_ul]:space-y-1.5">
      <h2 className="text-xl font-bold">{title}</h2>
      {children}
    </section>
  );
}
