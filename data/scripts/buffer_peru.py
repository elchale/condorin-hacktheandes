"""Buffer the Peru ADM0 boundary by N km (default 30) and write GeoJSON.
Usage: python -X utf8 -I buffer_peru.py <in_adm0.geojson> <out.geojson> [km]"""
import json, sys
from shapely.geometry import shape, mapping
from shapely.ops import transform
from pyproj import Transformer

src, dst = sys.argv[1], sys.argv[2]
km = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
fc = json.load(open(src, encoding="utf-8"))
geom = shape(fc["features"][0]["geometry"])
# Peru spans several UTM zones; use a custom Albers equal area centered on Peru for buffering.
proj = "+proj=aea +lat_1=-2 +lat_2=-16 +lat_0=-9 +lon_0=-75 +datum=WGS84 +units=m"
fwd = Transformer.from_crs("EPSG:4326", proj, always_xy=True).transform
inv = Transformer.from_crs(proj, "EPSG:4326", always_xy=True).transform
buf = transform(inv, transform(fwd, geom).buffer(km * 1000, resolution=8).simplify(500))
json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"buffer_km": km}, "geometry": mapping(buf)}]},
          open(dst, "w", encoding="utf-8"))
print("bounds", [round(v, 3) for v in buf.bounds])
