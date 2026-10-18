"""Merge SERNANP layers (definitive ANP, transitory zones, ACR), keep those that intersect Amazon departments.
Usage: python -X utf8 -I sernanp_merge.py <raw_dir> <adm1.geojson> <out.geojson>"""
import json, sys, os
from shapely.geometry import shape
from shapely.ops import unary_union

raw, adm1, out = sys.argv[1:4]
AMAZON_DEPTS = {"Loreto", "Ucayali", "Madre de Dios", "Amazonas", "San Martín", "Cusco", "Puno", "Junín", "Pasco", "Huánuco"}
# Inside those departments but high Andean puna or outside the Amazon basin (Titicaca, Pacific drainage).
EXCLUDE = {"del Titicaca", "Nor Yauyos-Cochas", "Reserva Paisajística Cerro Khapia", "Vilacota Maure",
           "Cordillera Huayhuash", "Ausangate", "Huaytapallana", "Tres Cañones", "de Junín", "de Huayllay", "de Chacamarca"}
depts = [f for f in json.load(open(adm1, encoding="utf-8"))["features"]]
names = {f["properties"]["shapeName"] for f in depts}
missing = AMAZON_DEPTS - names
if missing:
    sys.exit(f"department names not found: {missing} (have {sorted(names)})")
mask = unary_union([shape(f["geometry"]) for f in depts if f["properties"]["shapeName"] in AMAZON_DEPTS]).buffer(-0.02)

def load(name):
    return json.load(open(os.path.join(raw, name), encoding="utf-8"))["features"]

rows = []
for f in load("anp_definitivas.geojson"):
    p = f["properties"]
    rows.append((f, {"anp": p["anp_nomb"], "categoria": p["anp_cate"], "codigo": p["anp_codi"], "ubicacion": p["anp_ubpo"], "ha": p["anp_suleg"]}))
for f in load("anp_transitorias.geojson"):
    p = f["properties"]
    rows.append((f, {"anp": p["zr_nomb"], "categoria": "Zona Reservada", "codigo": p["zr_codi"], "ubicacion": p["zr_ubpo"], "ha": p["anp_suleg"]}))
for f in load("acr.geojson"):
    p = f["properties"]
    rows.append((f, {"anp": p["acr_nomb"], "categoria": "Área de Conservación Regional", "codigo": p["acr_codi"], "ubicacion": p["acr_ubpo"], "ha": p["acr_suleg"]}))

feats = []
for f, props in rows:
    if not f.get("geometry") or props["anp"] in EXCLUDE:
        continue
    g = shape(f["geometry"])
    if not g.is_valid:
        g = g.buffer(0)
    if not g.intersects(mask):
        continue
    props["ha"] = round(props["ha"]) if props["ha"] else None
    feats.append({"type": "Feature", "properties": props, "geometry": f["geometry"]})
json.dump({"type": "FeatureCollection", "features": feats}, open(out, "w", encoding="utf-8"), ensure_ascii=False)
print("kept", len(feats), "of", len(rows))
for x in sorted((p["properties"]["categoria"], p["properties"]["anp"]) for p in feats):
    print(" ", x[0], "|", x[1])
