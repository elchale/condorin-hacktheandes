import { useEffect, useState } from "react";
import { WelcomeOverlay } from "../../components/WelcomeOverlay";
import { useSession } from "../../lib/hooks";
import { signInWithLink } from "./api";

/**
 * Opening an alert link (expediente or evento) signs the member in, so the panel is one tap away.
 * Returns whether there is a session and the "Entraste como <ONG>" overlay to render.
 */
export function useLinkSignIn(token: string) {
  const session = useSession();
  const [welcome, setWelcome] = useState<{ ong: string; name?: string } | null>(null);
  const hadSession = Boolean(session);

  useEffect(() => {
    if (hadSession) return;
    let alive = true;
    signInWithLink(token).then((r) => {
      if (alive && r.fresh && r.ong) setWelcome({ ong: r.ong, name: r.name });
    });
    return () => {
      alive = false;
    };
    // Only on first open of this token; a later sign in elsewhere must not trigger another call.
  }, [token]);

  const overlay = welcome && <WelcomeOverlay ong={welcome.ong} name={welcome.name} onDone={() => setWelcome(null)} />;
  return { signedIn: hadSession, overlay };
}
