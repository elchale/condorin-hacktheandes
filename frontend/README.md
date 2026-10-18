# Ojo de Cóndor (condorin-mapa)

The public site of Ojo de Cóndor at condorin.pe: a live map of illegal gold mining detections (river dredges)
in the Peruvian Amazon, WhatsApp sign in, the member panel, the alert (evento) and expediente pages, and the
legal pages. It is a static single page app that talks only to the Django API (`api.condorin.pe`,
repo `condorin-backend`). It replaces the earlier Next.js app.

It is built for the worst phone on the worst network: about 19 KB gzipped of JavaScript before the map,
text first (KPIs and the detections list paint from a bundled snapshot before any request), the map
library loaded after idle, and a save data mode.

## Stack

- Vite 7, TypeScript, Tailwind CSS 4 (`@tailwindcss/vite`), system fonts only
- Preact 10 through `preact/compat` aliases (the code is written against the React 19 API and types;
  the aliases in `vite.config.ts` save about 60 KB gzipped on the first route). To switch back to React,
  delete the `resolve.alias` block.
- Leaflet 1.9 with the canvas renderer, in its own chunk
- A 40 line history router (`src/router.tsx`)

## Run

```bash
npm install
cp .env.example .env        # VITE_API_URL, defaults to https://api.condorin.pe
npm run dev                 # http://localhost:5173
npm run build               # tsc --noEmit, then vite build into dist/
npm run preview             # serve dist/ on http://localhost:4173
npm run sync-data           # copy ../mapa-data/mapa-snapshot.json and ../mapa-data/out/* in
```

For a local Django, set `VITE_API_URL=` (empty) and the dev server proxies `/api` to `http://localhost:8000`,
or set `VITE_API_URL=http://localhost:8000` (Django allows `http://localhost:5173` when `DEBUG`).

## Routes

| Path | Chunk | What |
| --- | --- | --- |
| `/` | main | Map dashboard: KPIs, bottom sheet (phones) or left panel (from 1024 px) with Detecciones, Ríos, Capas, Actividad; time scrubber; satellite toggle; `?bienvenida=1` shows the welcome overlay |
| `/entrar` | Entrar | Phone, consent, 6 digit WhatsApp code; `?next=/panel` returns there |
| `/acerca` | Acerca | Landing copy, honest limits ("Qué decidimos y qué quedó fuera"), photo credits |
| `/panel` | features/panel | Member panel |
| `/evento/:token`, `/expediente/:token` | features | Pages opened from WhatsApp alerts (`referrer` set to `no-referrer` while open) |
| `/privacidad`, `/terminos` | features/legal | Legal pages |

`src/features/**` is ported from the Next app separately. Shared building blocks for those pages:

- `src/lib/api.ts`: `api<T>(path, opts)`, `apiGet`, `apiPost`, `ApiError {message, type, status, fieldErrors}`, `friendlyError(e)`. 20 s timeout, bearer token sent when signed in.
- `src/lib/session.ts`: `getToken`, `setToken`, `clearToken`, `authHeaders`, `getSession`, `saveSession`, `subscribeSession`; `useSession()` in `src/lib/hooks.ts`.
- `src/lib/brand.ts`: `BRAND_NAME` (change the display name in one line), `formatPhone`, `normalizePhone`.
- `src/components/Shell.tsx`: page frame with the top bar and "Volver al mapa".

## Data

- Live: `GET /api/v1/mapa` (public, cacheable; with `Authorization: Bearer <token>` it adds `mine`, so the
  member's ONG rivers are highlighted and "Mis detecciones" works). Fetched in the browser with a 6 s timeout,
  then every 2 minutes while the tab is visible. The badge says EN VIVO with the payload time, or Sin conexión.
- Offline fallback: `src/data/mapa-snapshot.json`, the production export (`manage.py export_mapa`), bundled.
- Static layers: `public/data/layers.json` plus one GeoJSON per layer (each under 250 KB gzipped). Fetched only
  when a layer is switched on; the choice is remembered in localStorage (never restored in save data mode).
  If `layers.json` is `[]` the Capas tab hides.
- Auth (Data contract B): `POST /api/v1/auth/codigo` then `POST /api/v1/auth/entrar`; the token lives in
  localStorage under `condorin.session`.

### Sources and attribution

- Detections: Ojo de Cóndor on Planet and Copernicus Sentinel-1 imagery.
- Basemap: Esri World Dark Gray Canvas (Esri, HERE, Garmin, © OpenStreetMap contributors). CARTO dark was the
  plan, but keyless CARTO tiles now come back watermarked "API KEY REQUIRED"; `VITE_BASEMAP=carto` switches back
  if a key or allowlist is arranged.
- Satellite: Esri World Imagery (Esri, Maxar, Earthstar Geographics).
- Layers: see each entry of `layers.json` (Amazon Mining Watch, SERNANP, INGEMMET, REINFO, ...) and
  `../mapa-data/out/SOURCES.md`.
- Photos on /acerca: Wikimedia Commons, credited in the page footer.

## Build sizes (gzip, `vite build`)

See the table printed by `npm run build`. At the time of writing: main chunk (route `/`) 19 KB JS + 6.6 KB CSS;
map chunk 46 KB JS + 3 KB CSS (Leaflet included); Entrar 2 KB; Acerca 3.6 KB.

## Deploy

Any static host. `vercel.json` (Vercel) and `public/_headers` + `public/_redirects` (Cloudflare Pages, Netlify)
carry the same rules:

- every unknown path rewrites to `/index.html` (client side routes);
- `/assets/*` (hashed file names) and `/data/*` (layer files, fetched with a `?v=` version) are
  `Cache-Control: public, max-age=31536000, immutable`; `layers.json` is cached for one hour;
- `index.html` is revalidated on every load, so a deploy is picked up at once;
- `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`.

The API must allow the site origin in CORS (`ADDITIONAL_CORS_ORIGINS` in the backend).
