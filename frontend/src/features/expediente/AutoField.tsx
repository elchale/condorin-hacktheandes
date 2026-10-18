import { useEffect, useRef, useState } from "react";
import type { EditableFields } from "../../types";
import { field, fieldError, fieldId, hint as hintClass, label as labelClass } from "../shared/ui";

type TextName = { [K in keyof EditableFields]: EditableFields[K] extends string ? K : never }[keyof EditableFields];

type Props = {
  name: TextName;
  label: string;
  value: string;
  onSave: (name: TextName, value: string) => void;
  error?: string;
  hint?: string;
  multiline?: boolean;
  rows?: number;
  type?: "text" | "email" | "url";
  inputMode?: "numeric" | "email" | "text";
  maxLength?: number;
  placeholder?: string;
  disabled?: boolean;
};

/** A text field that saves itself on blur, sending only this field, and only when it changed. */
export function AutoField({ name, label, value, onSave, error, hint, multiline, rows = 4, type = "text", inputMode, maxLength, placeholder, disabled }: Props) {
  const [draft, setDraft] = useState(value);
  const focused = useRef(false);

  // A save by someone else (or the server cleaning the value) shows up unless the person is typing here.
  useEffect(() => {
    if (!focused.current) setDraft(value);
  }, [value]);

  const common = {
    id: `${fieldId(name)}-input`,
    name,
    value: draft,
    disabled,
    placeholder,
    maxLength,
    "aria-invalid": Boolean(error) || undefined,
    "aria-describedby": error ? `${fieldId(name)}-error` : undefined,
    className: `${field} mt-2 ${error ? "border-rojo" : ""}`,
    onFocus: () => (focused.current = true),
    onBlur: () => {
      focused.current = false;
      const next = draft.trim() === draft ? draft : draft.trim();
      if (next !== value) onSave(name, next);
    },
  };

  return (
    <div id={fieldId(name)} className="scroll-mt-24">
      <label htmlFor={common.id} className={labelClass}>
        {label}
      </label>
      {hint && <p className={hintClass}>{hint}</p>}
      {multiline ? (
        <textarea {...common} rows={rows} onChange={(e) => setDraft(e.target.value)} />
      ) : (
        <input {...common} type={type} inputMode={inputMode} onChange={(e) => setDraft(e.target.value)} />
      )}
      {error && (
        <p id={`${fieldId(name)}-error`} className={fieldError}>
          {error}
        </p>
      )}
    </div>
  );
}
