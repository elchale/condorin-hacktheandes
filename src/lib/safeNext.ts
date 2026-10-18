/** Only same site paths ("/panel", "/expediente/abc"), never "//host" or absolute URLs. */
export function safeNext(next: string | null): string | null {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.includes("\\") && !next.startsWith("/entrar") ? next : null;
}
