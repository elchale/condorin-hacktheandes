"""Page an ArcGIS REST layer query into one GeoJSON FeatureCollection.
Usage: python -X utf8 -I arcgis_pager.py <layer_url> <out.geojson> <page_size> [key=value ...]
Extra key=value pairs are added to the query (where, outFields, geometry, maxAllowableOffset...)."""
import json, sys, time, urllib.parse, urllib.request

layer, out, page = sys.argv[1], sys.argv[2], int(sys.argv[3])
extra = dict(a.split("=", 1) for a in sys.argv[4:])
params = {"where": "1=1", "outFields": "*", "returnGeometry": "true", "outSR": "4326", "f": "geojson"}
params.update(extra)
feats, offset = [], 0
while True:
    q = dict(params, resultOffset=str(offset), resultRecordCount=str(page))
    url = layer.rstrip("/") + "/query?" + urllib.parse.urlencode(q)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ojo-de-condor-data/1.0"}), timeout=180) as r:
                data = json.load(r)
            break
        except Exception as e:  # network flakiness on government servers
            print("retry", offset, attempt, repr(e)[:120], file=sys.stderr)
            time.sleep(3 + attempt * 3)
    else:
        sys.exit(f"failed at offset {offset}")
    if "error" in data:
        sys.exit(f"server error at offset {offset}: {data['error']}")
    got = data.get("features", [])
    feats.extend(got)
    print("offset", offset, "got", len(got), file=sys.stderr)
    more = data.get("exceededTransferLimit") or data.get("properties", {}).get("exceededTransferLimit")
    if not got or not more:
        break
    offset += len(got)
json.dump({"type": "FeatureCollection", "features": feats}, open(out, "w", encoding="utf-8"))
print("features", len(feats))
