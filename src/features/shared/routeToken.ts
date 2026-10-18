/** The token prop, or the last path segment when the router did not pass one (/evento/<token>). */
export function routeToken(token: string | undefined, prefix: string): string {
  if (token) return token;
  const path = window.location.pathname.replace(/\/+$/, "");
  return path.startsWith(`${prefix}/`) ? decodeURIComponent(path.slice(prefix.length + 1)) : "";
}
