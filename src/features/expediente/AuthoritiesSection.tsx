import type { Authority, Patch, Payload } from "../shared/types";
import { card, fieldError, fieldId, hint, sectionTitle } from "../shared/ui";

type Props = {
  authorities: Authority[];
  expediente: Payload["expediente"];
  errors: Record<string, string>;
  save: (patch: Patch) => void;
};

/** Screen 4: where it goes, and whether to ask for identity protection. Each tap saves. */
export function AuthoritiesSection({ authorities, expediente: e, errors, save }: Props) {
  const selected = authorities.filter((a) => a.selected).map((a) => a.code);
  const toggle = (code: string, on: boolean) =>
    save({ authorities: on ? [...selected, code] : selected.filter((c) => c !== code) });
  const error = errors.authorities ?? e.missing.authorities;

  return (
    <section aria-labelledby="aquien" className={card}>
      <h2 id="aquien" className={sectionTitle}>
        A quién se envía
      </h2>
      <p className={hint}>Ya marcamos las que corresponden a este río. Puedes agregar otras.</p>

      <fieldset id={fieldId("authorities")} className="mt-4 scroll-mt-24 space-y-3">
        <legend className="sr-only">Autoridades</legend>
        {authorities.map((a) => (
          <label key={a.code} className="flex cursor-pointer gap-3 rounded-2xl p-3 ring-1 ring-line has-[:checked]:ring-2 has-[:checked]:ring-rojo">
            <input type="checkbox" className="mt-1 size-5 shrink-0 accent-rojo" checked={a.selected} onChange={(ev) => toggle(a.code, ev.target.checked)} />
            <span className="min-w-0">
              <span className="block font-semibold">{a.name}</span>
              {a.is_primary && <span className="block text-sm text-muted">Vía principal para minería ilegal.</span>}
            </span>
          </label>
        ))}
        {error && <p className={fieldError}>{error}</p>}
      </fieldset>

      <label className="mt-5 flex cursor-pointer gap-3">
        <input type="checkbox" className="mt-1 size-5 shrink-0 accent-rojo" checked={e.identity_reserved} onChange={(ev) => save({ identity_reserved: ev.target.checked })} />
        <span>
          <span className="block font-semibold">Pedir reserva de identidad</span>
          <span className="block text-sm text-muted">La autoridad no revelará quién denuncia.</span>
        </span>
      </label>
    </section>
  );
}
