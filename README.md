# Ojo de Cóndor (condorin)

[![CI](https://github.com/elchale/condorin-hacktheandes/actions/workflows/ci.yml/badge.svg)](https://github.com/elchale/condorin-hacktheandes/actions/workflows/ci.yml)

Ojo de Cóndor watches Amazon rivers for illegal gold mining dredges in satellite images, alerts the ONGs that
watch each river by WhatsApp within minutes, and turns each detection into a denuncia (expediente) they can
file with the Fiscalía (FEMA) and OEFA the same day.

Built for Hack the Andes, Lima, 17 and 18 October 2026.

- Live site: https://www.condorin.pe
- API: https://api.condorin.pe
- Live numbers: https://api.condorin.pe/api/v1/mapa (`totals`: scenes, detections, alerts sent and opened, expedientes, ONGs, members)

## Try it in two minutes

1. Open https://www.condorin.pe on a phone. KPIs and detections paint first; then the map loads with the open
   data layers (Capas) and live feeds (NASA FIRMS fires, Sentinel, Open-Meteo, GloFAS river discharge).
2. Tap a detection on río Yaguas: satellite crop, confidence, protected area, and how many alerts went out.
3. Sign in at https://www.condorin.pe/entrar with a Peruvian WhatsApp number: a 6 digit code arrives on WhatsApp.
4. https://www.condorin.pe/acerca explains the product and what we left out.

## Why

Detection is no longer the bottleneck; acting on it is.

- Peru has lost 139,169 ha of Amazon forest to mining by mid 2025, 97.5% of it in Madre de Dios, and dredges are
  back on the Nanay, Pachitea, Cenepa and Tambopata (MAAP, RAMI 2025 and 2026).
- Satellite alerts already exist (Amazon Mining Watch, MAAP, MapBiomas), but few become a case: of 7,200+ illegal
  mining denuncias filed with the Fiscalía in 2019 to 2023, only 285 ended in a sentence. In Brazil, IBAMA acted
  on 1.3% to 2.2% of MapBiomas alerts (2019 to 2022).
- What works is organized people using alerts: in a randomized trial with 36 communities in Loreto, monitors who
  received satellite alerts cut deforestation by 52% in the first year (PNAS 2021).

**User:** the ONG or community monitor who watches a river. They get the evidence on WhatsApp (the only app that
works on the worst phone and network), and the denuncia comes prefilled with location, hashes of the evidence,
the protected area and the authority to file with. Conservación Internacional Perú validated the problem with us
and helped us find the data sources.

**Pilot river:** Yaguas (Putumayo, Loreto), inside the Parque Nacional Yaguas.

## How it fits together

```
satellite scene uploaded to gs://river-images/<river>/<date>...
        │
        ▼
detection/   Cloud Run Job, YOLO on 640 px tiles, crops of each dredge
        │    POST /api/v1/detections (Google ID token, idempotent per image)
        ▼
backend/     Django + DRF on Cloud Run, Postgres (Neon)
        │    pins the evidence (GCS hashes, SHA-256 of crops)
        │    WhatsApp alert with the crop to every member of every ONG watching the river
        ▼
frontend/    condorin.pe: public map, WhatsApp sign in, panel, alert page, expediente
        │    member completes the prefilled expediente, confirms with a WhatsApp code
        ▼
             folio + PDF emailed to the ONG, filed with FEMA and OEFA, receipt tracked
data/        open data layers on the map (mining footprint, protected areas, concessions, REINFO)
```

## Repository layout

| Folder | What it is | Stack | Deploy |
|---|---|---|---|
| [`detection/`](detection/) | Dredge detector over very high resolution images | Python 3.12, Ultralytics YOLO, Cloud Run Job + trigger service | Cloud Run |
| [`backend/`](backend/) | API, alerts, expedientes, evidence | Django 5.2, DRF, Postgres (Neon), WhatsApp Cloud API, GCS | Cloud Run (`api.condorin.pe`) |
| [`frontend/`](frontend/) | Public site and member flows | Vite, TypeScript, Preact, Tailwind 4, Leaflet | Vercel (`www.condorin.pe`) |
| [`data/`](data/) | Map layers, API contract, prod snapshot | GeoJSON, mapshaper, Python | served by the frontend |

Root CI (`.github/workflows/ci.yml`) runs every part: Django tests on Postgres, the detector tests with
a stub model, frontend typecheck and build, and a check of the map layers. Every source
repository also runs its own CI and deploys on push to main (Cloud Run for backend and detector, Vercel for
the frontend). Secrets live in Secret Manager, Vercel and GitHub secrets; only `.env.example` templates
are in the repo.

Each folder keeps its own README with setup, configuration and design decisions. The history of each
original repository is preserved (merged with `git subtree`), and `.github/workflows/sync.yml` pulls new
commits from them every 10 minutes (`bash scripts/sync-subtrees.sh` does the same by hand).

## Running locally

```bash
# backend
cd backend && python3.13 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.template .env && python manage.py migrate && python manage.py runserver   # see backend/README.md

# frontend
cd frontend && cp .env.example .env && npm install && npm run dev   # VITE_API_URL=http://localhost:8000

# detector with a fake model, no GCP needed
cd detection && python3.12 -m venv .venv && .venv/bin/pip install -e ".[job,trigger,dev]" && .venv/bin/pytest
```

## What we decided and what was left out

- Dredges on rivers first (open pit mines are covered by the Amazon Mining Watch layer, not by our model).
- No task queue: alerts go out on a thread after commit, and the detector is idempotent so reruns are safe.
- Hackathon limits in the backend: only recent scenes alert and WhatsApp alerts are capped (`backend/detections/limits.py`).
- Imagery is bought per scene (SkyFi); continuous tasking of very high resolution satellites is out of budget for now.
- Filing with FEMA and OEFA is still done by the ONG on the official forms; we prefill and track it.

## Team

Carlos Feijoo, Johguxo, Sergio Tello.

## Licence

`detection/` is AGPL-3.0 (it runs on Ultralytics YOLO). Open data layers keep their source licences, listed in
[`data/out/SOURCES.md`](data/out/SOURCES.md).
