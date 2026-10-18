import { useEffect, useSyncExternalStore } from "react";

type Platform = "android" | "ios";

/**
 * WhatsApp (and Facebook, Instagram) open links in their own in-app browser, where the session is lost
 * as soon as the chat is closed. A template button cannot choose the browser, so the page hands itself
 * over: an Android intent opens the default browser, and iOS 17+ understands x-safari-https.
 * It tries once per link on its own; many in-app browsers only allow it from a tap, so a bar with a
 * big button stays at the top, with the menu steps as a last resort.
 */
function inAppPlatform(): Platform | null {
  const ua = navigator.userAgent;
  const android = /Android/i.test(ua);
  const ios = /iPhone|iPad|iPod/i.test(ua);
  const named = /WhatsApp|FBAN|FBAV|FB_IAB|Instagram|Line\//i.test(ua);
  // Android WebView: "; wv)" or the "Version/4.0 Chrome/…" pair that real Chrome never sends.
  const webview = android && (/; wv\)/.test(ua) || /Version\/[\d.]+ Chrome\//.test(ua));
  // iOS WKWebView inside an app: no "Safari/" token (Safari, Chrome and Firefox for iOS all send one).
  const wkwebview = ios && !/Safari\//.test(ua);
  if (!(named || webview || wkwebview)) return null;
  if (android) return "android";
  if (ios) return "ios";
  return null;
}

function externalUrl(platform: Platform, href: string) {
  if (platform === "ios") return `x-safari-${href}`;
  const url = new URL(href);
  return `intent://${url.host}${url.pathname}${url.search}#Intent;scheme=https;S.browser_fallback_url=${encodeURIComponent(href)};end`;
}

const noSubscribe = () => () => {};

export function OpenInBrowser({ token }: { token: string }) {
  // The user agent never changes, so there is nothing to subscribe to; null on the server.
  const platform = useSyncExternalStore(noSubscribe, inAppPlatform, () => null);

  useEffect(() => {
    if (!platform) return;
    const key = `cdn_escape_${token}`;
    try {
      if (sessionStorage.getItem(key)) return;
      sessionStorage.setItem(key, "1");
    } catch {
      return; // no storage: do not risk a redirect loop, the bar is enough
    }
    window.location.href = externalUrl(platform, window.location.href);
  }, [platform, token]);

  if (!platform) return null;
  return (
    <div className="sticky top-16 z-20 rounded-2xl bg-ink p-4 text-white shadow-xl">
      <p className="font-bold">Estás dentro de WhatsApp</p>
      <p className="mt-1 text-sm text-white/80">Ábrelo en tu navegador para que tu sesión se mantenga.</p>
      <a
        href={externalUrl(platform, typeof window === "undefined" ? "" : window.location.href)}
        className="mt-3 block rounded-xl bg-rojo px-4 py-3.5 text-center font-bold text-white"
      >
        Abrir en {platform === "ios" ? "Safari" : "el navegador"}
      </a>
      <p className="mt-2 text-xs text-white/70">
        Si no se abre, toca {platform === "ios" ? "el ícono de compartir o los tres puntos" : "los tres puntos ⋮"} arriba y elige
        &quot;Abrir en {platform === "ios" ? "Safari" : "el navegador"}&quot;.
      </p>
    </div>
  );
}
