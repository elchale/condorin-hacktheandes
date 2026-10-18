# Member pages (ported from the Next app)

Plain React components with a default export that takes `{ token?: string }`. When the router does not pass
the token, the page reads it from the path (`shared/routeToken.ts`). Every page has "Volver al mapa" to `/`
through `shared/PageFrame.tsx` (the SPA `TopBar` plus a slim second bar).

| Route | Component | API calls (all straight to `API_URL`, `credentials: "omit"`) |
| --- | --- | --- |
| `/panel` | `panel/PanelPage.tsx` | `GET /api/v1/me` (bearer session); `POST /api/v1/me/incidentes/<id>/expediente` then `/expediente/<token>` or `/evento/<token>`. No session: `/entrar?next=/panel`. A 401 clears the session. `?bienvenida=1` shows the welcome overlay. |
| `/evento/<token>` | `evento/EventoPage.tsx` | `GET /api/v1/eventos/<token>` |
| `/expediente/<token>` | `expediente/ExpedientePage.tsx` | `GET` and `PATCH /api/v1/expedientes/<token>` (autosave on blur, filings, reopen); `POST /api/v1/expedientes/<token>/enviar` (`{}` sends the WhatsApp code, `{code}` confirms); PDF link `${API_URL}/api/v1/expedientes/<token>?formato=pdf` |
| `/privacidad` | `legal/PrivacidadPage.tsx` | none |
| `/terminos` | `legal/TerminosPage.tsx` | none |

Evento and expediente also call `POST /api/v1/auth/enlace {token}` once when there is no session
(`shared/useLinkSignIn.tsx`): the answer `{token, member, ong}` is stored with `saveSession` from
`src/lib/storage.ts` only if no session exists, and the "Entraste como" overlay is shown.

`shared/` holds the ported helpers: `api.ts` (fetch wrapper and every call above), `types.ts` (expediente,
evento and panel payloads), `ui.ts` (class strings in the console palette), `format.ts`, `Icon.tsx`,
`AlertSection.tsx`, `ScenePreview.tsx` and `OpenInBrowser.tsx` (shared by evento and expediente).

Colors: the Next pages used the light landing tokens (`marca`, `tinta`, `gris`...). They were mapped to the
SPA tokens in `src/index.css` (`rojo`, `ink`, `muted`, `panel`, `night`, `line`, `ambar`, `verde`). Copy is unchanged.
