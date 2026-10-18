"""Drop features whose geometry is null (polygons that collapse at output precision).
Usage: python -X utf8 -I drop_empty.py <file.geojson>  (rewrites in place, compact)"""
import json, sys
p = sys.argv[1]
fc = json.load(open(p, encoding="utf-8"))
before = len(fc["features"])
fc["features"] = [f for f in fc["features"] if f.get("geometry")]
with open(p, "w", encoding="utf-8") as fh:
    json.dump(fc, fh, ensure_ascii=False, separators=(",", ":"))
print("drop_empty", p, before, "->", len(fc["features"]))
