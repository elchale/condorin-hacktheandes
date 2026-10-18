# Expediente page (condorin.pe/expediente/[token])

What the Next.js page must do with this API. The goal: someone on a phone, on a slow connection, goes
from the WhatsApp alert to a denuncia ready to file in a few minutes, and never types anything Ojo de Cóndor
already knows.

## Principles

- **Mobile first.** One column. Large tap targets. It must work at 360 px wide with no sideways scroll.
- **Nothing is lost.** Autosave each field on blur with a `PATCH` of only that field, and show "Guardado"
  quietly. Answers about the ONG and the signer are remembered by the backend for the next alert.
- **Ask only what is missing.** `expediente.missing` lists the required fields still empty, with the
  message to show. The progress indicator counts these, not the whole form.
- **Shared, not duplicated.** If `updated_by` is someone else, show "José también está trabajando en este
  expediente" so nobody files the same denuncia twice.

## Screens

1. **La alerta** (top of the page, read only). The crop image (`incident.detections[].crop_url`), the river
   and `incident.place`, `captured_at_label`, the satellite, a map pin (`maps_url`), and the coordinates in
   both WGS84 and UTM. If `incident.history` is not empty, show "Ya se detectó actividad aquí el …".
   Add a "Descargar imagen original" link (`scene.download_url`).
2. **Quién denuncia.** `ong_name`, `ong_ruc`, `ong_address`, `notify_email`, `rep_name`, `rep_dni`,
   `rep_position`. Most are prefilled, so show them as a summary card with "Editar". Open the card by default
   only when something in it is in `missing`.
3. **Qué pasó.** `facts` is already written by Ojo de Cóndor. Show it in an editable text area that says
   "Revisa y corrige si hace falta". Optional fields: `place_reference` ("¿Cómo se llama el lugar?"),
   `field_observations` ("¿Alguien de la comunidad lo vio?"), `field_evidence_links` (links to photos or
   videos), `suspects` (defaults to "Por identificar."), and `risk_notes`.
4. **A quién se envía.** Checkboxes from `authorities[]`, with `selected` set and a short description.
   `identity_reserved` is a toggle: "Pedir reserva de identidad".
5. **Revisar y confirmar.** A "Ver borrador" button opens `pdf_url` (BORRADOR watermark). The required
   checkbox is `truth_declared`. "Confirmar expediente" calls `POST /enviar {}`:
   - 400 → scroll to the first field in `field_errors`.
   - 202 → a code input that auto-submits at 6 digits, "Te enviamos un código a +51 *** *** 808" (`phone_hint`),
     and a resend button after 45 s. Handle `code_invalid` and `code_expired`.
6. **Listo para presentar** (`status = ready`). "Descargar PDF". Then one step per selected authority, in order:
   the name, `instructions`, and a button to `submit_url` (or the phone or address). Last, a field for the
   receipt number ("Número de registro") and the date; this sends `PATCH filings`. Show "Te enviamos el PDF a …"
   (`sent.emailed_to`).
7. **Presentado** (`status = filed`). The receipts per authority. Show "Corregir" only while the status is
   `ready`; it sends `PATCH {reopen: true}`.

Errors: `link_expired` → a friendly page ("Pide a tu ONG que te reenvíe la alerta"). 404 → "Revisa que
el enlace esté completo".

## Panel (condorin.pe/panel)

After signing in with the WhatsApp code, or by opening an alert link, the member lands on /panel: the ONG's
incidents with the evidence crops and one action each (Crear expediente, Continuar, Presentar a las
autoridades, Ver expediente). Every action opens this same expediente page with the member's own token.

## Time replay dashboard (later, no endpoints yet)

The frontend will get a dashboard that replays detections over a chosen time range (a "simular tiempo"
slider). It will show alerts going out, expedientes moving from draft to filed, and rivers on a map.
The backend has no endpoints for it yet, by decision. The data it will need is already stored:
`SatelliteImage.captured_at`, `Detection` coordinates and confidence, `Alert.sent_at` and `opened_at`, and
`Expediente.status`, `finalized_at` and `filings`. `manage.py simulate_detection` can produce demo data.
