/** Class strings shared by the member pages (panel, evento, expediente), in the console palette. */
export const field =
  "w-full min-w-0 rounded-xl border border-line bg-night px-4 py-3.5 text-base text-ink placeholder:text-muted/60 focus:border-rojo focus:outline-none focus:ring-2 focus:ring-rojo/20 disabled:opacity-60";

export const label = "block font-medium text-ink";

export const primaryButton =
  "w-full rounded-xl bg-rojo px-6 py-4 text-base font-bold text-white transition-colors duration-200 hover:bg-rojo-2 disabled:cursor-not-allowed disabled:bg-panel-2 disabled:text-muted";

export const textLink = "font-medium text-red-400 underline underline-offset-2 hover:text-red-300";

export const card = "rounded-3xl bg-panel p-5 ring-1 ring-line sm:p-6";
export const sectionTitle = "text-lg font-bold";
export const hint = "mt-1 text-sm text-muted";
export const fieldError = "mt-1 text-sm font-medium text-red-300";
export const outlineButton =
  "inline-flex w-full items-center justify-center gap-2 rounded-xl bg-transparent px-5 py-3.5 font-bold text-ink ring-2 ring-inset ring-ink/70 hover:bg-ink hover:text-night disabled:opacity-50 sm:w-auto";

/** The id each field's wrapper gets, so a 400 from /enviar can scroll to it. */
export const fieldId = (name: string) => `campo-${name}`;
