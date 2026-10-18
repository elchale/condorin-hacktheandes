import { useState } from "react";
import { AutoField } from "./AutoField";
import type { Payload } from "../../types";
import { card, hint, sectionTitle, textLink } from "../shared/ui";

type Props = {
  expediente: Payload["expediente"];
  errors: Record<string, string>;
  onSave: (name: keyof Payload["expediente"], value: string) => void;
};

const FIELDS = ["ong_name", "ong_ruc", "ong_address", "notify_email", "rep_name", "rep_dni", "rep_position"] as const;

/** Screen 2: who files. Mostly prefilled, so it starts as a summary unless something is missing. */
export function DenuncianteSection({ expediente: e, errors, onSave }: Props) {
  const incomplete = FIELDS.some((f) => f in e.missing || f in errors);
  const [editing, setEditing] = useState(incomplete);
  const open = editing || incomplete;
  const err = (f: (typeof FIELDS)[number]) => errors[f] ?? (open ? e.missing[f] : undefined);

  return (
    <section aria-labelledby="quien" className={card}>
      <div className="flex items-start justify-between gap-3">
        <h2 id="quien" className={sectionTitle}>
          Quién denuncia
        </h2>
        {!open && (
          <button type="button" className={`${textLink} text-sm`} onClick={() => setEditing(true)}>
            Editar
          </button>
        )}
      </div>

      {!open ? (
        <dl className="mt-3 space-y-1 text-sm">
          <dd className="font-semibold">{e.ong_name}</dd>
          {e.ong_ruc && <dd className="text-muted">RUC {e.ong_ruc}</dd>}
          <dd className="text-muted">{e.ong_address}</dd>
          <dd className="text-muted">{e.notify_email}</dd>
          <dd className="pt-2">
            Firma {e.rep_name}, DNI {e.rep_dni}
            {e.rep_position ? `, ${e.rep_position}` : ""}
          </dd>
        </dl>
      ) : (
        <div className="mt-4 space-y-5">
          <p className={hint}>Lo guardamos para la próxima alerta, así no lo vuelves a escribir.</p>
          <AutoField name="ong_name" label="Razón social de la ONG" value={e.ong_name} error={err("ong_name")} onSave={onSave} />
          <AutoField name="ong_ruc" label="RUC (opcional)" value={e.ong_ruc} error={err("ong_ruc")} onSave={onSave} inputMode="numeric" maxLength={11} />
          <AutoField name="ong_address" label="Domicilio de la ONG" value={e.ong_address} error={err("ong_address")} onSave={onSave} />
          <AutoField
            name="notify_email"
            label="Correo para notificaciones"
            hint="Aquí te enviamos el PDF final y aquí te escribirán las autoridades."
            value={e.notify_email}
            error={err("notify_email")}
            onSave={onSave}
            type="email"
            inputMode="email"
          />
          <AutoField name="rep_name" label="Nombre de quien firma" value={e.rep_name} error={err("rep_name")} onSave={onSave} />
          <AutoField name="rep_dni" label="DNI de quien firma" value={e.rep_dni} error={err("rep_dni")} onSave={onSave} inputMode="numeric" maxLength={8} />
          <AutoField name="rep_position" label="Cargo (opcional)" value={e.rep_position} error={err("rep_position")} onSave={onSave} />
        </div>
      )}
    </section>
  );
}
