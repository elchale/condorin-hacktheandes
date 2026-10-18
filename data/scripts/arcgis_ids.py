"""Download an ArcGIS REST layer by object id chunks (for servers without pagination).
Usage: python -X utf8 -I arcgis_ids.py <layer_url> <out.geojson> <where> <outFields> [chunk] [key=value ...]"""
import json, sys, time, urllib.parse, urllib.request

layer, out, where, fields = sys.argv[1:5]
chunk = int(sys.argv[5]) if len(sys.argv) > 5 else 200
extra = dict(a.split("=", 1) for a in sys.argv[6:])
UA = {"User-Agent": "Mozilla/5.0 ojo-de-condor-data/1.0"}

def post(params):
    body = urllib.parse.urlencode(params).encode()
    for attempt in range(5):
        try:
            req = urllib.request.Request(layer.rstrip("/") + "/query", data=body, headers=UA)
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.load(r)
            if "error" in d:
                raise RuntimeError(d["error"])
            return d
        except Exception as e:
            print("retry", attempt, repr(e)[:150], file=sys.stderr)
            time.sleep(3 + 3 * attempt)
    sys.exit("failed")

ids = sorted(post({"where": where, "returnIdsOnly": "true", "f": "json"}).get("objectIds") or [])
print("ids", len(ids), file=sys.stderr)
feats = []
for i in range(0, len(ids), chunk):
    q = {"objectIds": ",".join(map(str, ids[i:i + chunk])), "outFields": fields, "returnGeometry": "true",
         "outSR": "4326", "f": "geojson"}
    q.update(extra)
    feats.extend(post(q).get("features", []))
    print("got", len(feats), file=sys.stderr)
json.dump({"type": "FeatureCollection", "features": feats}, open(out, "w", encoding="utf-8"), ensure_ascii=False)
print("features", len(feats), "of ids", len(ids))
