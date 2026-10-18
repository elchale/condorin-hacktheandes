import { useEffect, useState } from "react";
import { BRAND_NAME, PRIVACY_URL, RESEND_COOLDOWN_S, TERMS_URL } from "../config";
import { Brand } from "../components/TopBar";
import { friendlyError, requestCode, signIn } from "../lib/api";
import { saveSession } from "../lib/session";
import { formatPhone, normalizePhone } from "../lib/brand";
import { Link, navigate, useLocation } from "../router";

const field =
  "min-h-12 w-full rounded-lg border border-line bg-night px-3 text-base text-ink placeholder:text-muted/60 focus:border-cian focus:outline-none";
const primary =
  "min-h-12 w-full rounded-lg bg-rojo px-4 font-bold text-white hover:bg-rojo-2 disabled:cursor-not-allowed disabled:opacity-50";
const textLink = "text-cian underline underline-offset-4";

/** Only same site paths ("/panel", "/expediente/abc"), never "//host" or absolute URLs. */
function safeNext(next: string | null): string | null {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/entrar") ? next : null;
}

export default function Entrar() {
  const { search } = useLocation();
  const [step, setStep] = useState<"phone" | "code">("phone");
  const [phone, setPhone] = useState("");
  const [consent, setConsent] = useState(false);
  const [pending, setPending] = useState("");
  const [sentTo, setSentTo] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    const prev = document.title;
    document.title = `Entrar · ${BRAND_NAME}`;
    return () => {
      document.title = prev;
    };
  }, []);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = window.setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => window.clearTimeout(t);
  }, [cooldown]);

  const send = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await requestCode(normalizePhone(phone), consent);
      setPending(r.pending);
      setSentTo(r.phone);
      setStep("code");
      setCode("");
      setCooldown(RESEND_COOLDOWN_S);
    } catch (e) {
      setError(friendlyError(e));
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await signIn(pending, code);
      saveSession({ token: r.token, member: r.member ?? { name: "", phone: sentTo }, ong: r.ong ?? { name: "" } });
      const next = safeNext(search.get("next"));
      navigate(next && next !== "/" ? next : "/?bienvenida=1", { replace: true });
    } catch (e) {
      setError(friendlyError(e));
      setBusy(false);
    }
  };

  const phoneReady = consent && phone.replace(/\D/g, "").length >= 9;

  return (
    <div className="grid-bg flex min-h-dvh flex-col">
      <header className="flex h-14 items-center justify-between border-b border-line bg-night px-3 sm:px-4">
        <Brand />
        <Link href="/" className="flex min-h-11 items-center px-2 text-sm text-muted hover:text-ink">
          Volver al mapa
        </Link>
      </header>
      <main className="flex flex-1 items-start justify-center px-4 py-8 sm:items-center">
        <div className="w-full max-w-sm rounded-3xl bg-white p-5 shadow-[0_8px_30px_rgba(24,24,27,.08)] ring-1 ring-line sm:p-7">
          <p className="label-caps">Acceso para miembros</p>
          <h1 className="mt-1 text-2xl font-black tracking-tight">Entrar a {BRAND_NAME}</h1>
          <p className="mt-2 text-sm text-muted">
            {step === "phone"
              ? "Usa tu número de WhatsApp. Te enviamos un código de 6 dígitos."
              : `Ingresa el código enviado al ${formatPhone(sentTo)}.`}
          </p>

          {error && (
            <p role="alert" className="mt-4 rounded-lg border border-rojo/50 bg-rojo/10 px-3 py-2 text-sm text-rojo-3">
              {error}
            </p>
          )}

          {step === "phone" ? (
            <form onSubmit={(e) => (e.preventDefault(), phoneReady && !busy && void send())} className="mt-5 space-y-4">
              <label htmlFor="phone" className="block text-sm font-semibold">
                Número de celular con WhatsApp
              </label>
              <div className="flex gap-2">
                <span className="flex items-center rounded-lg border border-line bg-night px-3 text-muted">+51</span>
                <input
                  id="phone"
                  className={field}
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel-national"
                  placeholder="987 654 321"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  required
                />
              </div>
              <label className="flex items-start gap-3 text-sm text-muted">
                <input
                  type="checkbox"
                  className="mt-0.5 size-5 shrink-0 accent-[#e11d2e]"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                  required
                />
                <span>
                  Acepto los{" "}
                  <a href={TERMS_URL} target="_blank" rel="noopener noreferrer" className={textLink}>
                    Términos y condiciones
                  </a>{" "}
                  y la{" "}
                  <a href={PRIVACY_URL} target="_blank" rel="noopener noreferrer" className={textLink}>
                    Política de privacidad
                  </a>
                  , y autorizo el tratamiento de mis datos para recibir alertas.
                </span>
              </label>
              <button className={primary} disabled={busy || !phoneReady}>
                {busy ? "Enviando código…" : "Enviar código por WhatsApp"}
              </button>
            </form>
          ) : (
            <form onSubmit={(e) => (e.preventDefault(), code.length === 6 && !busy && void verify())} className="mt-5 space-y-4">
              <label htmlFor="code" className="block text-sm font-semibold">
                Código de 6 dígitos
              </label>
              <input
                id="code"
                className={`${field} tnum text-center text-2xl tracking-[0.5em]`}
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                placeholder="000000"
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                autoFocus
                required
              />
              <button className={primary} disabled={busy || code.length !== 6}>
                {busy ? "Verificando…" : "Entrar"}
              </button>
              <div className="flex items-center justify-between gap-2 text-sm">
                <button
                  type="button"
                  className={`min-h-11 ${textLink}`}
                  onClick={() => {
                    setStep("phone");
                    setError("");
                  }}
                >
                  Cambiar número
                </button>
                <button
                  type="button"
                  className={`min-h-11 tnum ${cooldown > 0 ? "text-muted" : textLink}`}
                  onClick={() => void send()}
                  disabled={busy || cooldown > 0}
                >
                  {cooldown > 0 ? `Reenviar en ${cooldown} s` : "Enviar otro código"}
                </button>
              </div>
            </form>
          )}
        </div>
      </main>
    </div>
  );
}
