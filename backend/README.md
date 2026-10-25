# Ojo de Cóndor API

Backend for [condorin.pe](https://condorin.pe), deployed at **api.condorin.pe**. It receives what the
satellite detector finds on Amazon rivers, alerts the ONGs that watch each river by WhatsApp, and helps
them turn that evidence into a denuncia they can file with the Fiscalía and OEFA the same day.

Django 5.2 + DRF on Postgres (Neon), with no task queue. It shares the database with the Next.js app, and Django
owns the schema and every migration (see [Shared database](#shared-database)).

## How it works

```
detector ──POST /api/v1/detections──▶ store scene + detections (idempotent)
                                        │
                                        ▼ after commit, on a thread
                    pin evidence: GCS md5/crc32c of the scene, SHA-256 of each crop
                                        │
                                        ▼
         WhatsApp template condorin_evento_v2 to every member of every ONG that watches the river
         [crop image]  "Hola María, Ojo de Cóndor detectó 1 posible draga en el río Yaguas..."
         [Crear expediente → condorin.pe/expediente/<token>]   [Ver ubicación → Google Maps]
                                        │
                                        ▼ member taps
   condorin.pe/expediente/<token>  ──GET──▶ expediente for (image, ONG), created and prefilled
         member fixes what is missing ──PATCH──▶ autosave; answers remembered for next time
         "Confirmar" ──POST /enviar──▶ WhatsApp code (condorin_codigo) to that member
         code ──POST /enviar──▶ folio CND-2026-00001, final PDF, emailed to the ONG
         files it on the FEMA and OEFA forms, types the receipt number ──PATCH──▶ status filed
```

- **Hackathon limits (`detections/limits.py`).** Only scenes captured today or yesterday (Lima) alert, overriding `ALERT_RECENT_DAYS`, and at most 50 WhatsApp alerts are ever sent (status `sent`); the rest become `capped`, are never retried, and the webhook answers `reason: capped`. The welcome also stops once the cap is used up. Only alerts sent from `HACKATHON_CAP_SINCE` count (the cap was reset before the live demo).
- **TODO(prod):** remove `HACKATHON_ALERT_WINDOW_DAYS`, `HACKATHON_MAX_ALERT_MESSAGES` and `HACKATHON_CAP_SINCE` before real production.
- **Who is alerted, and when.** Only a scene captured within `ALERT_RECENT_DAYS` (default 7) alerts, at
  once, on commit. Recipients: every active member of every active ONG watching the river, plus every
  active admin (`accounts_admin`) with a `phone` (`manage.py set_admin_phone <email> <phone>`). Admins sit in
  the hidden ONG "Equipo Ojo de Cóndor" (`internal=True`, `ongs/team.py`), which watches every river, gets
  its own personal tokens and expedientes, and stays out of the public map and the panel. Older scenes,
  and payloads marked `"simulated"` or `"demo"`, are stored and shown but alert nobody; the webhook answers
  `alerted` and `reason` (`alerted`, `old_scene`, `simulated`, `below_threshold`, `no_recipients`).
- **One expediente per image and ONG.** Every member of the ONG who taps the alert opens the same one,
  so two people never file duplicates. Each ONG gets its own.
- **The token is personal** (one per member per image) and expires after `ALERT_LINK_DAYS`. A forwarded
  link can read and edit the draft, but finalizing needs the WhatsApp code sent to that member's phone.
- **Evidence is pinned.** The scene is referenced by `gs://bucket/object#generation`, an immutable
  version, together with GCS's own MD5 and CRC32C. Each crop gets a SHA-256. All of it goes in the PDF annexes, and
  the PDF's own SHA-256 goes in the email. Links shown to the user are V4 signed URLs for that exact version.
- **The PDF** follows what NCPP art. 328 and DAR's 2025 guide ask for: denunciante, numbered hechos
  (drafted by Ojo de Cóndor), ubicación in WGS84 and UTM, presuntos responsables, fundamentos (CP 307-A/B,
  DL 1100, Ley 26834 inside a protected area), medios probatorios, petitorio (constatación fiscal,
  interdicción) and a signature block. Annexes include the crops, scene custody data, earlier detections within
  3 km and the Copernicus credit. Drafts carry a BORRADOR watermark.
- **Where it is filed.** FEMA (Ministerio Público, Denuncias en línea) is the main route because illegal mining is a crime.
  OEFA (Servicio Nacional de Denuncias Ambientales, which replaced SINADA in May 2026) leaves an administrative record.
  SERNANP is added when the river is inside a protected area. None of them publishes an email for
  complaints, so the PDF is emailed to the ONG with step by step links. An authority gets it by email
  only if an admin enters a confirmed address.

## Known shortcuts

Built in 30 hours. These are the shortcuts we took on purpose, what each one risks, and how production replaces it.

| Shortcut | Where | Risk | In production |
|---|---|---|---|
| Hackathon alert window (today or yesterday) and a cap of 50 WhatsApp alerts | `detections/limits.py` | A real scene older than yesterday alerts nobody | Delete the limits; `ALERT_RECENT_DAYS` and Meta's own quality rating take over |
| Everyone who signs in joins the default ONG as a full member (`DEFAULT_ONG_JOIN_ROLE`, `observer` to read only) | `panel.services.member_for_phone` | Anyone with a phone sees that ONG's incidents, gets its alerts and can sign its expedientes (set `observer` to stop that) | Invitations sent by each ONG's admin, one member per invitation |
| Alerts are sent on a thread after the webhook answers | `detections.services.dispatch` | On Cloud Run with request based CPU the thread can stall; `manage.py send_pending_alerts` retries | `ALERTS_INLINE=True` or Cloud Tasks, plus CPU always allocated |
| Background work runs on daemon threads (alerts, the welcome, the admin email, the Claude hechos) | `detections.services.dispatch`, `panel/welcome.py`, `expedientes.services` | A daemon thread dies with its process: a deploy, a scale in or a crash mid send loses that work silently. Alerts are claimed as `sending` first, so `send_pending_alerts` picks them up again after `ALERT_SENDING_STALE_MINUTES`; a lost welcome, admin email or Claude rewrite is not retried (the deterministic hechos stay) | A task queue (Cloud Tasks) with retries, or a periodic `send_pending_alerts` job |
| An unknown river slug from the detector is created, not rejected | `detections.services.ingest` | A typo stores a scene nobody watches (the webhook answers `no_recipients`) | Kept: a new river must be stored; an admin assigns ONGs to it |
| The detector runs when someone calls its trigger, not on every upload | detector repo, `POST /procesar` | A forgotten call means no scene | Kept: bucket events fire per file with no "upload finished" signal; a scheduler calls the trigger after each satellite pass |
| Demo clock | `core/clock.py`, `manage.py set_today` | A wrong day hides scenes or replays alerts | Only for demos; `set_today --real` |

## API

Seventeen routes: the webhook, the expediente (three plus the event page), four for the condorin.pe server, the public map,
six for the browser sign in (map and static SPA), and the pages.

| Method | Path | Who | What |
|---|---|---|---|
| POST | `/api/v1/detections` | detector | `Authorization: Bearer <Google ID token or shared secret>`, `Idempotency-Key`. 201 new, 200 duplicate. |
| GET | `/api/v1/expedientes/<token>` | ONG member | Opens (and on first tap creates) the expediente, with everything the page needs. `?formato=pdf` returns the PDF. |
| PATCH | `/api/v1/expedientes/<token>` | ONG member | Any subset of the fields (autosave), `authorities: [codes]`, `filings: [{authority, receipt_number, filed_at}]` (only with `Authorization: Bearer <session>` opened with a WhatsApp code by that same member, else 403 `code_session_required`), `reopen: true`. |
| POST | `/api/v1/expedientes/<token>/enviar` | ONG member | `{}` checks completeness and sends the code (202). `{"code": "123456"}` finalizes and emails (200). |
| GET | `/api/v1/panel` | condorin.pe server | `Authorization: Bearer <PANEL_API_SECRET>`, `X-Condorin-Phone`. The member, their ONG and its incidents with the next action. Joins the default ONG on first call (demo only) with `DEFAULT_ONG_JOIN_ROLE` (default `member`) and sends the WhatsApp welcome, never an event. `member` carries `role` (`member` or `observer`) and `can_act`. |
| POST | `/api/v1/panel/incidentes/<id>/expediente` | condorin.pe server | Same headers. The member's personal expediente token for that incident, created if they had no alert. |
| POST / DELETE | `/api/v1/panel/incidentes/<id>/triaje` | condorin.pe server | Same headers. `{"status": "confirmed" \| "false_positive" \| "verified_field", "reason": "boat" \| "sandbar" \| "other"}` (reason required for `false_positive`) sets what the member's ONG decided about the incident, shared by all its members; DELETE puts it back to new. Members only (observers get 403). A rejected incident leaves the `draft` and `without_expediente` totals and cannot be opened (409) until restored. `manage.py export_false_positives` prints the rejected crops as hard negatives for retraining. |
| POST | `/api/v1/panel/enlace` | condorin.pe server | `{"token"}` → the member a WhatsApp alert link may sign in (sent, under `LINK_SIGN_IN_DAYS`), else 404. |
| GET | `/api/v1/panel/actividad?limit=N` | condorin.pe server | Secret only, no phone. The admin live feed: the last N scenes received (default 20, max 50), newest first, each with its detections, the ONGs that watch the river, their alerts and expediente, and the 8 decision steps (contract in `condorin/src/lib/admin/activity.ts`). |
| GET | `/api/v1/mapa` | anyone | The public map (contract A in `hacktheandes/mapa-data/CONTRACT.md`): totals (with `alerts_opened` and `users` as usage counters), rivers, scenes, detections as GeoJSON, a monthly timeline and an anonymized activity feed. No names, phones, tokens or signed URLs. With a valid `Authorization: Bearer <session>` it adds `mine` and turns private. `manage.py export_mapa` prints the same JSON. |
| GET | `/api/v1/fuentes` | anyone | Live open data for the map (contract D): NASA FIRMS VIIRS fires on the Amazon lowland side (lon -78.5 to -68, lat -13.5 to 0.5, 7 days, the 2,000 hottest) plus `fires_near_rivers` (fires within 25 km of each river), Sentinel 1 and 2 passes per river from the Copernicus catalogue (last, count, cloud, `next_passes`: the next 3 estimated radar passes), Open-Meteo rain and temperature per river with a 7 day `forecast`, GloFAS river discharge per river (`rivers[slug].discharge`: today, mean, trend, 14 day series, from the Open-Meteo Flood API), one Spanish `summary` sentence per river, and Global Forest Watch tile layers. Served from the `FeedCache` table. Any origin, gzip, 5 min cache. |
| POST | `/api/v1/fuentes/refresh` | GitHub workflow | `Authorization: Bearer <FUENTES_REFRESH_SECRET>` (when set; else `PANEL_API_SECRET`). Refreshes the stale sources now (`?force=1`: all of them) on parallel threads and returns each one's status (`ok`, `failed`, `fresh`, `busy`, or `running` when it outlasts 45 s and finishes in the background). 502 when every source it tried failed. |
| POST | `/api/v1/auth/codigo` | map SPA | `{"phone", "consent": true}` → 202 `{"phone", "pending"}`. Sends `condorin_codigo` by WhatsApp. One code per phone every 45 s, 6 per phone and 10 per IP per hour (the IP is the last `X-Forwarded-For` entry, `NUM_PROXIES` 1). |
| POST | `/api/v1/auth/entrar` | map SPA | `{"pending", "code"}` → `{"token", "member", "ong"}`. 5 attempts per code, 20 per phone and 30 per IP per hour. Records the sign in on `accounts_member` and joins the default ONG, like condorin.pe. |
| POST | `/api/v1/auth/enlace` | SPA | `{"token": <alert token>}` → the same as `/auth/entrar` with `"via": "link"` and a 7 day session. Same rules and same 404 as `/api/v1/panel/enlace`. |
| GET | `/api/v1/me` | map SPA | `Authorization: Bearer <token>`. Exactly the `/api/v1/panel` payload. |
| POST | `/api/v1/auth/salir` | SPA | Same bearer. `{"signed_out": true}`. Ends every session of that phone on every device (bumps `session_version`); idempotent, a missing or dead session gets the same answer. |
| POST | `/api/v1/me/incidentes/<id>/expediente` | map SPA | Same bearer. `{"token"}` like the panel route. |
| POST / DELETE | `/api/v1/me/incidentes/<id>/triaje` | map SPA | Same bearer. Same body and rules as the panel triage route; answers `{"triage"}`. |
| GET | `/`, `/healthz/` and `/readyz/` | anyone | Landing page with the logo; liveness probe (the process is up); readiness probe (`SELECT 1` on the database, 503 when it does not answer). |
| | `/admin/` | staff | ONGs, members, rivers, authorities, detections, alerts, expedientes. `ADMIN_URL` moves it (default `admin/`). |

Errors always come back as `{"message", "type", "field_errors"}`. With a 400 from `/enviar`,
`field_errors` lists exactly what is still missing, so the page can jump to it. Error `type`s the page
should handle: `link_expired` (410), `code_invalid`, `code_expired`, `code_too_soon` (429), `code_limit` (429, more
than 5 codes for one expediente in an hour), `expediente_locked` (409), `observer_restricted` (403), `code_session_required` (403, a filing sent without a code session), `whatsapp_error` (502).

**Roles.** A member the ONG or the admins added (`role` `member`) opens, edits, confirms and files. Someone who joined the
default ONG by signing in gets `DEFAULT_ONG_JOIN_ROLE`: `member` by default for the live demo, or `observer` (admins with a phone
always join as `member`). For an observer the panel, the incidents, the alerts and the event page work as usual, and
`GET /api/v1/expedientes/<token>` returns the ONG's existing draft with `"read_only": true`, the signer's `rep_name`,
`rep_dni`, `rep_position` and `notify_email` blank, no names of other members and `pdf_url` null. `PATCH`, `/enviar` and
`?formato=pdf` answer 403 `observer_restricted`. Promote someone in `/admin/` (Miembros, rol).

The frontend is connected: condorin.pe/expediente/<token> calls these routes through its own `/api/expedientes` proxy,
and condorin.pe/panel uses the panel routes. The screens are in [`docs/EXPEDIENTE_UX.md`](docs/EXPEDIENTE_UX.md).

### The public map and the SPA session

- **CORS.** `/api/v1/mapa` answers any origin (`Access-Control-Allow-Origin: *`, preflight included, see `mapa/middleware.py`).
  Every other route only allows condorin.pe, `ADDITIONAL_CORS_ORIGINS` and, with `DEBUG`, `http://localhost:5173` and `:3000`.
- **Cache.** The anonymous map is `Cache-Control: public, max-age=60, stale-while-revalidate=600` with an ETag (a 304 on
  revalidation) and is kept `MAPA_CACHE_SECONDS` (30) in the process cache, so a burst costs one set of about eight queries.
  Nothing else is publicly cacheable; expediente routes keep their private headers.
- **Gzip.** `GZipMiddleware` compresses every response above 200 bytes when the client accepts it (Cloud Run does not).
- **Session.** `pending` and the session token are `django.core.signing.TimestampSigner` values (salts `otp-pending`, `session`).
  The pending value carries an HMAC of the code keyed with `DJANGO_SECRET_KEY`, never the code; it lasts 10 minutes and the
  session 30 days. Attempts, the 45 s resend lock and the throttles of the sign in routes live in the shared default
  cache, the DatabaseCache table `django_cache` (created by the `core` migration `0002_cache_table`), so the limits hold across
  every Cloud Run instance. The map and feed payloads, the clock row and the high volume throttles stay in the process cache
  `local` (`core/cache.py`, `core/throttling.py`). Error types: `code_invalid`, `code_expired`, `code_too_soon` (429),
  `session_invalid` (401). Sessions also carry `v`, the phone's `session_version` (`ongs_member`, the highest of its rows):
  `/auth/salir` bumps it, so every older token of that phone stops working. Tokens from before versions count as 0. Sessions carry `via` (`code` or `link`); a link session never finalizes a denuncia, because
  `/enviar` ignores the bearer and always asks for the WhatsApp code sent to that member.
- **Browser calls.** The expediente, event, PDF, `/auth/*` and `/me*` routes answer condorin.pe and www.condorin.pe
  (preflight with `Authorization` and JSON bodies); `Content-Disposition` is exposed so the SPA can name the PDF.

### The clock: what day it is for the API

`core/clock.py` answers "now" for everything the product reasons about in time. By default it is the real clock. With
`manage.py set_today 2026-07-10` (or the **Reloj** row in `/admin/`) the whole API moves to that day, at the current Lima
time of day, and keeps ticking from there (`2026-07-10T09:00` pins the start instant):

- The map, the panel, the admin feed and the event history only show scenes captured up to that instant; the later
  ones do not exist yet. `generated_at`, alert `sent_at`, `opened_at`, `finalized_at` and the date on the PDF follow it.
- Moving the day queues an alert for every current recipient of each scene captured that day and sends them
  (`core.clock.replay_today`). Alerts are unique per scene and member and only pending or failed ones are sent, so
  repeating the command, or a day that already alerted for real, messages nobody twice. `--no-send` moves the day
  quietly; `--resend` retries today's pending ones; `set_today` alone prints the state; `--real` returns to real time.
- Every payload carries `clock`: `{"now", "today", "label", "simulated", "timezone"}`. The SPA shows it on the panel
  (date, ticking Lima time, a "fecha simulada" tag) and uses `now` for "últimos 30 días" and "hace 5 min".
- Security windows stay on the real clock: alert link expiry (`ALERT_LINK_DAYS`), WhatsApp codes and signed
  sessions, and the link sign in window (`LINK_SIGN_IN_DAYS` from the real moment the alert row was created, not
  its demo `sent_at`), so a demo alert signs in for 7 real days whatever day the clock shows.
- The state is one row read through the process cache for 5 s, so a request costs at most one extra query and
  every instance follows a change within seconds. The public map cache key includes the day.

### Signing in from the WhatsApp link

The alert button opens condorin.pe/expediente/<token> and the member is signed in without a code:

- The token is 192 random bits, one per member and image, and only reached that member's WhatsApp chat.
- The browser posts it to condorin.pe/api/enlace (link preview bots do not run JS, so they never sign in).
  That route checks the origin and asks `/api/v1/panel/enlace` with the shared secret. Only alerts WhatsApp
  delivered, within `LINK_SIGN_IN_DAYS` (7) of delivery, sign in. Anything else gets the same 404.
- The session lasts 7 days (30 with a code), and an existing session is never replaced by a link.
- The page sends `Referrer-Policy: no-referrer` and is not indexed. Confirming the denuncia still needs a fresh WhatsApp code.

### Evidence and PDFs in Cloud Storage

The service account in `GCS_CREDENTIALS_JSON` reads the scenes and crops the detector writes (to pin hashes
and sign links) and creates objects in `GCS_EXPEDIENTES_BUCKET`, where each final PDF is archived as
`expedientes/<year>/<folio>-<sha256 prefix>.pdf`, never overwritten. The database keeps its own copy,
so a failed upload never blocks a denuncia.

## Local setup

```bash
py -3.13 -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # Windows
cp .env.template .env      # fill in the values (DATABASE_URL is the Neon database)
python manage.py migrate   # also seeds FEMA, OEFA, SERNANP and the río Yaguas
python manage.py runserver
```

In `/admin`, create an ONG, tick the rivers it watches, and add its members (name and WhatsApp
number). Then:

```bash
python manage.py simulate_detection --river yaguas   # stores a scene marked simulated: alerts nobody, needs WA_SEND_ENABLED=False
python manage.py send_pending_alerts                 # retries alerts that failed (cron or by hand), recent scenes only
python manage.py purge_demo_events                   # lists demo and mock scenes; --yes deletes them with alerts and expedientes
python manage.py set_today 2026-07-10                # the API lives on that day: hides later scenes, sends that day's alerts (--real to return)
python manage.py set_admin_phone admin@example.org 51987654321   # admin gets every recent alert (--clear to stop)
python manage.py create_alert_template               # prints the WhatsApp template; --submit sends it to Meta
python manage.py create_welcome_template             # same for the welcome a person gets on joining (no event)
python manage.py send_event 42                       # who would get scene 42 by hand; --send sends it, --phone 519... only them, --resend again
python -X utf8 manage.py export_mapa > ../mapa-data/mapa-snapshot.json   # offline snapshot of GET /api/v1/mapa
python -X utf8 manage.py refresh_fuentes   # fetch the open data feeds now (--source firms, --force); writes only FeedCache
curl -X POST -H "Authorization: Bearer $PANEL_API_SECRET" http://localhost:8000/api/v1/fuentes/refresh   # the same over HTTP
python scripts/latency.py https://api.condorin.pe /healthz/ /api/v1/mapa --n 20   # p50, p95 and gzip bytes
pytest
ruff check .
```

Without `WA_TOKEN`, WhatsApp messages are logged instead of sent. Without GCS credentials, the
evidence still records the URIs, but the hashes and signed links stay empty.

The hechos of a new expediente are written by `expedientes/drafting.py` from the detection. With
`EXPEDIENTE_IA_ENABLED=True` and an `ANTHROPIC_API_KEY`, that draft goes once through Claude
(`expedientes/redaccion.py`, LangChain, model `EXPEDIENTE_IA_MODEL`, default `claude-opus-5-5`) after the
expediente is committed, on a thread (`expedientes.services.improve_later`), so no transaction waits on Claude. The
expediente is stored and shown with the deterministic draft first; the rewrite replaces it only while nobody edited
the hechos. The flag is off by default; if the call fails, the deterministic draft is kept.

## Shared database

The Next.js app and this API use the same Neon database, and **Django owns the schema**: every table,
including the two the frontend uses, is created by `python manage.py migrate` here. The `accounts` app
holds those two tables: `accounts_member` (people who signed in on condorin.pe with WhatsApp) and
`accounts_admin` (Google accounts allowed into condorin.pe/admin). Columns the frontend inserts without
a value have database defaults (`db_default`), because Prisma does not run Django's Python defaults.
`condorin/prisma/schema.prisma` only maps onto these tables, and Prisma never migrates. When a migration
changes them, update that mapping and run `npx prisma generate`.

`manage.py import_prisma_backup <file.json>` loads admins and members from a JSON backup of the old
Prisma tables. That is how the users were carried over on 2026-10-17. The backup stays outside the repo.

Tests never touch production rows. pytest creates a separate `test_condorin` database on the server of
`DATABASE_URL` and drops it at the end, and `backend/test_settings.py` refuses to load when that server is Neon:
run `scripts/check.sh` (a throwaway Postgres in Docker) or point `DATABASE_URL` at a local Postgres.

## Deploy

Cloud Run serves `api.condorin.pe` (a push to main deploys it, see `.github/workflows/ci.yml`). Set the
variables from `.env.template` and, before the first real alert:

1. `condorin_evento_v2` (no footer; buttons Crear expediente and Ver evento) is approved on the Qolca WABA (2026-10-17). New wording needs a new name: change `WA_ALERT_TEMPLATE` and run `create_alert_template --submit`.
2. Give the GCS service account `storage.objects.get` on the detector buckets. It needs a key to sign links.
3. Configure the detector: an OIDC token with audience `https://api.condorin.pe/api/v1/detections` from a
   service account listed in `DETECTIONS_ALLOWED_SERVICE_ACCOUNTS`, or the shared secret.

### Cloud Run

The `Dockerfile` builds the image (`.dockerignore` keeps `.env` out of it), the entrypoint migrates
unless `RUN_MIGRATIONS=0` (bounded by `MIGRATE_TIMEOUT`, 120 s, and every database connect by `DB_CONNECT_TIMEOUT`, 10 s,
so an unreachable database fails the revision fast instead of hanging the deploy), and gunicorn listens on the `$PORT` Cloud Run injects.

```bash
REGION=us-central1
# Secrets go in Secret Manager; the service account needs roles/secretmanager.secretAccessor.
for s in DJANGO_SECRET_KEY DATABASE_URL WA_TOKEN DETECTIONS_SHARED_SECRET GCS_CREDENTIALS_JSON EMAIL_HOST_PASSWORD; do
  printf '%s' "<value>" | gcloud secrets create $s --data-file=-
done

gcloud run deploy condorin-api --source . --region $REGION --allow-unauthenticated \
  --no-cpu-throttling --min-instances 1 --max-instances 3 --memory 1Gi --cpu 1 --timeout 60 \
  --set-env-vars DOMAIN=api.condorin.pe,EXTRA_ALLOWED_HOSTS=.run.app,FRONTEND_URL=https://condorin.pe,WA_PHONE_NUMBER_ID=<id>,WA_WABA_ID=<id>,GCS_PROJECT_ID=<project>,DETECTIONS_ALLOWED_SERVICE_ACCOUNTS=<sa> \
  --set-secrets DJANGO_SECRET_KEY=DJANGO_SECRET_KEY:latest,DATABASE_URL=DATABASE_URL:latest,WA_TOKEN=WA_TOKEN:latest,DETECTIONS_SHARED_SECRET=DETECTIONS_SHARED_SECRET:latest,GCS_CREDENTIALS_JSON=GCS_CREDENTIALS_JSON:latest,EMAIL_HOST_PASSWORD=EMAIL_HOST_PASSWORD:latest
```

- **Continuous deploy**: after the first deploy, every push to `main` that passes Ruff and pytest ships
  through the `deploy` job in `.github/workflows/ci.yml`. It builds the image, pushes it to Artifact
  Registry and points the service at it, so env vars and secrets set on the service are kept. GitHub signs
  in as the `github-deployer` service account, whose JSON key is the `GCP_SA_KEY` repository secret. It
  only holds `roles/run.developer`, `roles/artifactregistry.writer` on the repository and
  `roles/iam.serviceAccountUser` on the runtime service account.
- **`--no-cpu-throttling` is required.** Alerts go out on a thread after the webhook responds, and by
  default Cloud Run stops giving CPU to an instance once its response is sent. `--min-instances 1` keeps
  one warm, and 1Gi leaves room for two workers rendering PDFs.
- **`--allow-unauthenticated`**: the browser and the detector call the API directly; Django checks the
  link token and the webhook bearer.
- **`GCS_CREDENTIALS_JSON` is still needed.** Cloud Run's default credentials hold no private key, so they
  cannot sign the evidence links.
- **Retries**: create a Cloud Run job from the same image running `python manage.py send_pending_alerts`
  and trigger it from Cloud Scheduler (every 15 minutes, say). With more than one instance, run
  migrations the same way (a job running `python manage.py migrate`) and set `RUN_MIGRATIONS=0` on the service.
- **Open data feeds**: the backend pulls FIRMS, Sentinel, Open-Meteo and GloFAS itself. `.github/workflows/refresh-feeds.yml` calls
  `POST /api/v1/fuentes/refresh` every 30 minutes (and on demand, with a `force` input) using the
  `PANEL_API_SECRET` repository secret, which must equal the service's `PANEL_API_SECRET`
  (`gh secret set PANEL_API_SECRET --repo elchale/condorin-backend`). Each source refetches once its TTL is
  over (FIRMS 1 h, Open-Meteo 3 h, Sentinel and GloFAS 6 h). GitHub may delay scheduled runs, so the
  fallback stays: a visitor who finds a stale source gets the cached data at once and starts one
  background refresh (stale while revalidate). After a deploy, `refresh_fuentes --force` warms everything.
- **Domain**: `gcloud beta run domain-mappings create --service condorin-api --domain api.condorin.pe --region $REGION`,
  then add the DNS records it prints. Not every region supports domain mappings.
- **Vercel**: the frontend calls `https://api.condorin.pe` (or the `run.app` URL until the domain is live).
  To allow preview deployments, set `CORS_ALLOWED_ORIGIN_REGEXES` to something like
  `^https://condorin-[a-z0-9-]+\.vercel\.app$`. Lists containing commas need gcloud's custom delimiter,
  e.g. `--set-env-vars "^;^ADDITIONAL_CORS_ORIGINS=a,b;DOMAIN=api.condorin.pe"`.
