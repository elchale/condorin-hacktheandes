// Copies the shared data from ../mapa-data into this repo: the map snapshot (offline fallback)
// and the static layers (only when layers.json exists, per Data contract C). Run: npm run sync-data
import { copyFileSync, existsSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const SRC = process.env.MAPA_DATA ?? "../mapa-data";
const snap = join(SRC, "mapa-snapshot.json");
if (existsSync(snap)) {
  JSON.parse(readFileSync(snap, "utf8")); // fail loudly on a half written file
  copyFileSync(snap, "src/data/mapa-snapshot.json");
  console.log("snapshot", statSync(snap).size, "bytes");
} else console.log("no snapshot at", snap, "(keeping the bundled one)");

const layers = join(SRC, "out", "layers.json");
if (existsSync(layers)) {
  const list = JSON.parse(readFileSync(layers, "utf8"));
  copyFileSync(layers, "public/data/layers.json");
  for (const l of list) {
    const f = join(SRC, "out", l.file);
    if (!existsSync(f)) {
      console.warn("missing", l.file);
      continue;
    }
    copyFileSync(f, join("public/data", l.file));
    console.log("layer", l.id, statSync(f).size, "bytes,", l.bytes_gzip, "gz");
  }
} else console.log("no layers.json yet: public/data/layers.json stays as is");
