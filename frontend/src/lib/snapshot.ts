import type { Mapa } from "../types";
// Offline fallback: the production export (python -X utf8 manage.py export_mapa) copied from
// mapa-data/mapa-snapshot.json by `npm run sync-data`. Rendered instantly, then replaced by the live API.
import raw from "../data/mapa-snapshot.json";

export const SNAPSHOT = raw as unknown as Mapa;
