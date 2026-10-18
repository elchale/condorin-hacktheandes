import { useEffect } from "react";

/** While mounted, ask the browser not to send the URL (which carries a token) as Referer. */
export function useNoReferrer() {
  useEffect(() => {
    const m = document.createElement("meta");
    m.name = "referrer";
    m.content = "no-referrer";
    document.head.appendChild(m);
    return () => m.remove();
  }, []);
}
