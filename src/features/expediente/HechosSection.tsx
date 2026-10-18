import { AutoField } from "./AutoField";
import type { Payload } from "../../types";
import { card, sectionTitle } from "../shared/ui";

type Props = {
  expediente: Payload["expediente"];
  errors: Record<string, string>;
  onSave: (name: keyof Payload["expediente"], value: string) => void;
};

/** Screen 3: the facts, already drafted by Ojo de Cóndor, plus what only the community knows. */
export function HechosSection({ expediente: e, errors, onSave }: Props) {
  return (
    <section aria-labelledby="que" className={card}>
      <h2 id="que" className={sectionTitle}>
        Qué pasó
      </h2>
      <div className="mt-4 space-y-5">
        <AutoField
          name="facts"
          label="Hechos"
          hint="Ojo de Cóndor ya los escribió con los datos del satélite. Revisa y corrige si hace falta."
          value={e.facts}
          error={errors.facts ?? e.missing.facts}
          onSave={onSave}
          multiline
          rows={10}
        />
        <AutoField name="place_reference" label="¿Cómo se llama el lugar?" hint="Opcional. Por ejemplo, el nombre de la quebrada o la comunidad." value={e.place_reference} error={errors.place_reference} onSave={onSave} />
        <AutoField name="field_observations" label="¿Alguien de la comunidad lo vio?" hint="Opcional. Cuenta qué vieron y cuándo." value={e.field_observations} error={errors.field_observations} onSave={onSave} multiline />
        <AutoField name="field_evidence_links" label="Enlaces a fotos o videos" hint="Opcional. Uno por línea." value={e.field_evidence_links} error={errors.field_evidence_links} onSave={onSave} multiline rows={3} />
        <AutoField name="suspects" label="Presuntos responsables" value={e.suspects} error={errors.suspects} onSave={onSave} multiline rows={2} />
        <AutoField name="risk_notes" label="Riesgos para la comunidad" hint="Opcional. Por ejemplo, amenazas o agua contaminada." value={e.risk_notes} error={errors.risk_notes} onSave={onSave} multiline rows={3} />
      </div>
    </section>
  );
}
