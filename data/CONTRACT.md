# Ojo de Cóndor map dashboard: shared contract (2026-10-18)

Read this whole file before writing code. Five agents work in parallel; each owns one folder and must not
touch the others. Everything here is Spanish for users (es_PE), English in code and comments.

## Ownership (do not write outside your folder)
- Agent BACKEND: `hacktheandes/condorin-backend/` only, plus the single file `hacktheandes/mapa-data/mapa-snapshot.json`.
- Agent NEXT: `hacktheandes/condorin/` only.
- Agent DATA: `hacktheandes/mapa-data/` only (never the snapshot file).
- Agent VITE: new folder `hacktheandes/condorin-mapa/` only.
- Agent LOAD: the session scratchpad only.

## Hard rules (from Carlos and CLAUDE.md)
- Brand display name is `Ojo de Cóndor` (one constant, BRAND_NAME, so it can be changed in one line). Technical ids keep `condorin`.
- No dashes as punctuation in any user visible copy (no "-" or em dash between words). "307-A" style legal names are fine. No emojis.
- Mobile first. Check 360, 375, 390 px: no sideways scroll, tap targets at least 44 px.
- Never `git push`. Pushing to main deploys to production (Vercel and Cloud Run) and needs Carlos's approval.
  Commit only YOUR files with `git add <paths>` and `git commit -- <paths>`. Both repos already have 40+ uncommitted
  files from another session (the rename): leave them exactly as they are, do not stage them, do not revert them.
- Never send WhatsApp messages, emails or alerts. Local Django must run with `WA_SEND_ENABLED=False` and `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend`.
  `condorin-backend/.env` points at PRODUCTION Neon: read from it is fine, do not create or modify rows except through tests (tests use the separate `test_condorin` database).
- Windows: heredocs through Bash mangle accents. Write any file containing non ASCII with the Write or Edit tools, and run Python with `python -X utf8`.
- Do not download big imagery. Every static data file in the frontends must stay under 400 KB gzipped; prefer under 150 KB.
- Spend tokens carefully: do not dump large files into your context (use head, wc, jq style summaries).

## Design direction (REVISED 2026-10-18 05:30 by Carlos): LIGHT mode, map like Amazon Mining Watch
Carlos rejected the dark console. The site is light (white panels, #f3f3f6 surfaces, zinc text, brand red only for
primary buttons, alert markers and key numbers), styled like the Next landing and panel. The map is the hero: Esri
satellite imagery by default with a labels overlay, the Amazon Mining Watch footprint ON by default in bright yellow
with a year slider and cumulative hectares, protected areas as a green outline, red detection markers with halo and
clusters, initial view fitting the Peruvian Amazon. TIME RULE (Carlos, 2026-10-18 12:40 UTC): the map shows ONLY the detections of the LAST 3 DAYS by default and says so in words
("Mostrando: últimos 3 días (16 al 18 de octubre)"); a "Viaje en el tiempo" day control (día anterior, día siguiente, fecha, Hoy,
marks on days with data) shows another day's detections. The yearly mining footprint is not filtered and is labeled
"Huella minera acumulada 2018 a 2026". No year options, no "Todo".
SIMPLICITY RULES (Carlos, 2026-10-18 05:50): a first time phone visitor must understand in five seconds what is shown,
which period it covers and what the colors mean. ONE time control that filters detections and footprint together and always
states the period in words ("Mostrando: 2024 a 2026"); a plain language headline plus a legend (rojo dragas detectadas, amarillo
huella minera, verde áreas protegidas); at most three KPIs with plain labels and at most three tabs; concessions and REINFO
hidden behind "Más capas"; only a small "Mapa / Satélite" switch; no EN VIVO badge, just "Actualizado hace X min"; every
control has a text label. Default: satellite + footprint + protected areas + detections, zoomed to the Peruvian Amazon.
The paragraphs below describe the ORIGINAL dark direction and are
kept only for the layout, tabs and performance rules; ignore their colors.
Look (superseded): a dark operations console in the spirit of Palantir Gotham. Near black blue background (#0b1120 base, panels #111a2e,
borders rgba(148,163,184,.18)), text #e2e8f0, muted #94a3b8. Accents: brand red #e11d2e for detections and alerts,
amber #f59e0b for pending, cyan #22d3ee for selection and live states, green #22c55e for filed expedientes.
Numbers in tabular figures (font-variant-numeric: tabular-nums), small uppercase labels with letter spacing, thin 1 px rules,
subtle grid, no glassmorphism blur on mobile (expensive). Geist or system-ui font.

Layout, mobile first:
- Top bar, 56 px, sticky: brand mark + "Ojo de Cóndor" at top LEFT; at right a clear primary button "Entrar" (red, white text)
  when logged out, or a chip with the member first name or ONG + "Mi panel" when logged in. A small "Acerca" link.
- Below: the map fills the viewport (100dvh minus bars). Over the map, a compact KPI strip (4 tiles: detecciones, dragas con alerta,
  expedientes, ríos vigilados) and a layer button.
- Bottom sheet (mobile) / left panel 360 px (desktop, from 1024 px): tabs "Detecciones", "Ríos", "Capas", "Actividad".
  Detecciones: list sorted by date, confidence bar, river, satellite; tapping flies the map to it and opens the popup.
  Ríos: cards with ONG count, last detection, protected area badge.
  Capas: toggles for the static open data layers from `layers.json` (each shows its size, loads lazily on first toggle, remembers choice in localStorage).
  Actividad: anonymized timeline from `activity`.
- Time scrubber (range of months from `timeline`) filtering detections; and a "Satélite" basemap toggle.
- Logged in members see their ONG rivers highlighted and a "Mis detecciones" filter.
- Popups: river, date (long Spanish date), confidence %, satellite, model, "Ver en Google Maps" link, and for logged in members a link to condorin.pe/panel.
- Keep an "Antes y ahora" or crop image out of the public map (signed URLs expire); link to the panel instead.

Performance rules (worst phone, worst network):
- Map library: Leaflet 1.9.x (about 42 KB gz) with `preferCanvas: true`. Not MapLibre GL (too heavy for low end phones).
- Basemap: CARTO dark raster `https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png` at 1x only (never @2x), attribution
  "© OpenStreetMap contributors © CARTO". Satellite toggle: Esri World Imagery
  `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` with attribution "Esri, Maxar, Earthstar Geographics".
- If `navigator.connection.saveData` or `effectiveType` is 2g or slow-2g: start zoomed on the detections only, no imagery, no static layers preloaded, and show a small "modo ahorro" note.
- First paint must be text (KPIs, list) before the map JS loads; map chunk is code split and loaded after idle or on first interaction.
- Static layers: fetched only when toggled, cached with immutable headers, each under 400 KB gz.
- Initial JS budget: Vite SPA under 90 KB gz for the first route; Next page as small as Next allows (no client components beyond the map and sheet).
- Images: none above the fold except the 40 px brand mark.

## Data contract A: `GET /api/v1/mapa` (public, no auth, CORS any origin, cacheable)
Headers: `Cache-Control: public, max-age=60, stale-while-revalidate=600`, `ETag`, gzip. Optional `Authorization: Bearer <session>`
adds `mine`. Shape (all timestamps ISO 8601 UTC, coordinates WGS84 numbers):

```json
{
  "generated_at": "2026-10-18T03:00:00Z",
  "clock": {"now": "2026-10-18T03:00:00Z", "today": "2026-10-17", "label": "sábado 17 de octubre de 2026", "simulated": false, "timezone": "America/Lima"},
  "brand": "Ojo de Cóndor",
  "bbox": [minLon, minLat, maxLon, maxLat],
  "totals": {"images": 0, "detections": 0, "alerting_detections": 0, "alerts_sent": 0,
             "expedientes": 0, "expedientes_filed": 0, "ongs": 0, "members": 0, "rivers": 0},
  "rivers": [{"slug": "malinowski", "name": "Malinowski", "basin": "", "region": "Madre de Dios", "province": "", "district": "",
              "protected_area": "", "lat": -12.9, "lon": -69.9, "ongs": 9, "images": 2, "detections": 6,
              "last_captured_at": "2026-10-17T14:00:00Z"}],
  "images": [{"id": 1, "river": "malinowski", "satellite": "Planet", "captured_at": "...", "model": "name version",
              "detections": 6, "alerting": 5, "top_confidence": 0.93, "lat": -12.9, "lon": -69.9,
              "alerts_sent": 10, "expedientes": {"draft": 1, "ready": 0, "filed": 0}}],
  "detections": {"type": "FeatureCollection", "features": [
      {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
       "properties": {"id": 1, "image": 1, "river": "malinowski", "confidence": 0.93, "captured_at": "...",
                      "alerting": true, "satellite": "Planet", "kind": "draga"}}]},
  "timeline": [{"month": "2026-09", "images": 1, "detections": 4}, {"month": "2026-10", "images": 1, "detections": 6}],
  "activity": [{"at": "...", "kind": "image", "river": "malinowski", "label": "Nueva escena en el río Malinowski con 6 detecciones"}],
  "mine": null
}
```
`kind` of a detection is "draga" for now (the detector reports dredges). `activity` kinds: `image`, `alert`
("Alerta enviada a 9 ONGs"), `expediente_opened`, `expediente_filed`. Never include names, phones, tokens or signed URLs.
`mine` when signed in: `{"member": {"name": "", "phone": "51..."}, "ong": {"name": "", "rivers": ["malinowski"]}}`.

River coordinates: centroid of its detections; if a river has none, use this fallback table in code:
yaguas (-2.65, -71.35), malinowski (-12.95, -69.95), nanay (-3.75, -73.45), madre-de-dios (-12.60, -69.20),
tambopata (-12.85, -69.35), inambari (-13.05, -70.10), napo (-3.30, -72.80), putumayo (-2.40, -72.80), marañon (-4.50, -77.50).

The snapshot file `hacktheandes/mapa-data/mapa-snapshot.json` is exactly this payload, written from the production database
by BACKEND (`python -X utf8 manage.py export_mapa > ...`). NEXT and VITE copy it into their repos as the offline fallback
(`src/data/mapa-snapshot.json`) and ALSO fetch the live endpoint at runtime (Next: server side with revalidate 60; Vite: in the
browser). Until the file exists, build against a hand written stub with the same shape (two rivers, six detections).

## Data contract B: session auth for the SPA (BACKEND provides, VITE consumes; NEXT keeps its own cookies)
- `POST /api/v1/auth/codigo` body `{"phone": "51936282808", "consent": true}` → 202 `{"phone": "51936282808", "pending": "<signed>"}`.
  Normalizes Peruvian numbers (9 digits → prefix 51). Rate limits: one code per phone every 45 s, 10 per IP per hour.
  Sends WA_CODE_TEMPLATE via `core.whatsapp.send_code` (dry run when WA_SEND_ENABLED is False). The code never leaves the server:
  `pending` is a signed value of phone + sha256(code) + expiry (10 min), like `condorin/src/lib/otp.ts`.
- `POST /api/v1/auth/entrar` body `{"pending": "...", "code": "123456"}` → 200 `{"token": "<signed 30 days>", "member": {"name": "", "phone": ""}, "ong": {"name": ""}}`.
  5 attempts per pending. Records the sign in the same way the Next app does (table `accounts_member`: phone, consent_at, last_sign_in_at,
  see the `accounts` app) and joins the member to the default ONG through `panel.services.member_for_phone`.
- `GET /api/v1/me` with `Authorization: Bearer <token>` → exactly the `PanelView` payload (member, ong, totals, incidents).
- `POST /api/v1/me/incidentes/<id>/expediente` → `{"token": "..."}` (same as the panel route).
- Errors keep the envelope `{"message", "type", "field_errors"}`; types `code_invalid`, `code_expired`, `code_too_soon` (429), `session_invalid` (401).
- CORS: when DEBUG, `http://localhost:5173` and `http://localhost:3000` are allowed; production relies on ADDITIONAL_CORS_ORIGINS.

## Data contract C: static open data layers (DATA produces in `mapa-data/out/`, NEXT and VITE copy to `public/data/`)
`mapa-data/out/layers.json`:
```json
[{"id": "mineria-amw", "file": "mineria-amw.geojson", "title": "Huella minera (Amazon Mining Watch)", "short": "Huella minera",
  "source": "Amazon Mining Watch, Earthrise Media y Amazon Conservation", "license": "CC BY 4.0", "url": "https://...",
  "year": "2018 a 2024", "color": "#f59e0b", "geometry": "Polygon", "features": 1234, "bytes_gzip": 210000,
  "property_labels": {"year": "Año"}}]
```
Expected layers (produce every one you can verify, skip and document any you cannot):
1. `mineria-amw.geojson` mining footprint polygons for Peru (plus 30 km buffer over the borders), simplified.
2. `anp-sernanp.geojson` protected natural areas of the Peruvian Amazon (SERNANP), simplified, props name and category.
3. `concesiones-ingemmet.geojson` mining concessions in Madre de Dios, Puno (Amazon side), Loreto, Amazonas, Ucayali; props holder, status; simplified or dissolved.
4. `comunidades-nativas.geojson` native communities or indigenous territories (MINCU or RAISG), simplified.
5. `reinfo.geojson` REINFO formalization registry points/areas for the same regions, if available.
Frontends read ONLY `layers.json` to build the Capas tab, so nothing else about the files is hardcoded.
If `public/data/layers.json` is missing at build time, frontends ship an empty `[]` and hide the tab.

## Routes (NEXT and VITE)
- `/` the map dashboard (main page). Session aware: Next reads the member cookie (`cdn_session`, `src/lib/session.ts`) and the admin
  cookie; Vite reads the bearer token from localStorage. Logged in users land here after login and can always come back here.
- `/entrar` login page: phone + consent, then the 6 digit code; after success go to `/?bienvenida=1` (welcome overlay, then the map).
  Query `?next=/panel` returns there instead.
- `/acerca` about page with the CURRENT landing content (hero text, qué detecta, cómo funciona, mercurio, CTA) restyled to fit, plus the legal links.
- Existing Next pages `/panel`, `/evento/[token]`, `/expediente/[token]` get a "Volver al mapa" link to `/` in their headers.
  `requirePhone()` redirects to `/entrar?next=<path>` instead of `/#entrar`.

## Data contract D: GET /api/v1/fuentes (public, no auth, CORS any origin, gzip, `Cache-Control: public, max-age=300, stale-while-revalidate=3600`, ETag)

Live open data the backend pulls itself (BACKEND owns it, NEXT and VITE consume). Every key below is always
present; a source that never loaded gives `{}` (or an empty FeatureCollection) and `sources[id].ok=false`.
Times are UTC ISO `YYYY-MM-DDTHH:MM:SSZ`; dates (`date`) are Lima calendar days. `slug` is the river slug of contract A.
Gzipped size about 30 KB on 2026-10-18 (cap 400 KB).

```jsonc
{
  "generated_at": "2026-10-18T12:00:00Z",
  "sources": {                      // one entry per source: firms, sentinel, open-meteo, glofas
    "firms": {"fetched_at": "…Z", "ok": true, "ttl_s": 3600, "error": null, "attribution": "NASA FIRMS (VIIRS 375 m, …)", "url": "https://…"}
  },
  "fires": {                        // GeoJSON, VIIRS 7 days, Amazon lowland box lon -78.5..-68, lat -13.5..0.5, the 2,000 hottest, newest first
    "type": "FeatureCollection",
    "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [-69.95, -12.95]},
                  "properties": {"at": "…Z", "frp": 12.3, "confidence": "l|n|h", "sensor": "VIIRS", "daynight": "D|N"}}]
  },
  "fires_near_rivers": {            // every deduplicated fire within 25 km of the river point, last 7 days
    "<slug>": {"count_7d": 4, "max_frp": 22.5, "last_at": "…Z" | null, "radius_km": 25.0}
  },
  "satellite": {
    "<slug>": {"s1_last": "…Z", "s1_last_id": "S1C_IW_GRDH_…", "s1_passes_30d": 8, "s1_next_estimate": "…Z",
               "next_passes": [{"at": "…Z", "platform": "Sentinel-1C"}],   // next 3 estimated radar passes, future only
               "s2_last": "…Z", "s2_last_cloud": 93.2, "s2_clear_last_30d": 4}
  },
  "weather": {
    "<slug>": {"rain_mm_7d": 36.0, "rain_mm_24h": 3.2, "temp_c": 23.2, "updated_at": "…Z",
               "forecast": [{"date": "2026-10-18", "rain_mm": 9.2, "rain_prob": 100, "tmax_c": 30.4}],  // 7 days from today
               "rain_mm_next_3d": 33.6}
  },
  "rivers": {                       // GloFAS discharge (Open-Meteo Flood API), largest river cell within about 11 km
    "<slug>": {"discharge": {"today_m3s": 156.0, "mean_m3s": 164.4, "trend": "sube|baja|estable",   // trend: day +3 vs today, ±5 %
                             "series": [{"date": "2026-10-11", "m3s": 161.9}],  // 14 days: 7 past days, then today and 6 forecast days
                             "cell": [-2.775, -70.875]} | null}
  },
  "summary": {                      // one plain Spanish sentence per river, ready to show, no dashes
    "<slug>": "Río Yaguas: 36 mm de lluvia en 7 días y 34 mm previstos en 3 días, caudal en subida (156 m³/s), próximo paso de radar el martes 20 a las 18:02."  // fires part only when count_7d > 0
  },
  "tile_layers": [                  // Global Forest Watch raster tiles the map loads directly
    {"id": "gfw-integrated-alerts", "title": "…", "dataset": "…", "url": "https://tiles…/{z}/{x}/{y}.png?…", "attribution": "…", "min_zoom": 6, "max_zoom": 14, "opacity": 0.8}
  ]
}
```

Freshness: `.github/workflows/refresh-feeds.yml` calls `POST /api/v1/fuentes/refresh` (Bearer `PANEL_API_SECRET`, `?force=1`
refetches all) every 30 minutes; each source refetches once its TTL is over (FIRMS 1 h, Open-Meteo 3 h, Sentinel and GloFAS 6 h).
If the schedule lags, a GET still answers from cache at once and refreshes stale sources in the background.
