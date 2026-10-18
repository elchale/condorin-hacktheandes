"""Validate every layer in out/ and write out/layers.json.
Usage: python -X utf8 -I build_manifest.py <out_dir>
Checks: FeatureCollection, every feature has a geometry of the declared family, coordinates are lon,lat
inside a Peru plus margin box, gzip (level 6) size under 400 KB."""
import gzip, json, os, sys

OUT = sys.argv[1]
LON, LAT = (-82.0, -68.0), (-19.0, 1.0)
MAX_GZ = 400_000

LAYERS = [
    {"id": "mineria-amw", "file": "mineria-amw.geojson",
     "title": "Huella minera detectada por satélite (Amazon Mining Watch)", "short": "Huella minera",
     "source": "Amazon Mining Watch, Earth Genome y Amazon Conservation (modelo 48px v4.10b, Sentinel 2)",
     "license": "CC BY 4.0",
     "url": "https://source.coop/earthgenome/amazon-mining-watch",
     "year": "2018 a 2026 (2025 y 2026 provisionales)", "color": "#f59e0b", "geometry": "Polygon",
     "property_labels": {"year": "Año de inicio", "estado": "Estado", "area_ha": "Área de celdas con detección (ha)"}},
    {"id": "anp-sernanp", "file": "anp-sernanp.geojson",
     "title": "Áreas naturales protegidas de la Amazonía (SERNANP)", "short": "Áreas protegidas",
     "source": "SERNANP, Servicio Nacional de Áreas Naturales Protegidas por el Estado",
     "license": "Datos públicos de SERNANP (servicio de descarga WFS y REST); SERNANP publica sus datos abiertos con ODC BY. Citar la fuente.",
     "url": "https://geoservicios.sernanp.gob.pe/arcgis/rest/services/base_fisica/peru_sernanp_0102/MapServer",
     "year": "2026", "color": "#22c55e", "geometry": "Polygon",
     "property_labels": {"anp": "Nombre", "categoria": "Categoría", "codigo": "Código", "ubicacion": "Ubicación", "ha": "Superficie legal (ha)"}},
    {"id": "concesiones-ingemmet", "file": "concesiones-ingemmet.geojson",
     "title": "Concesiones mineras vigentes y en trámite (INGEMMET)", "short": "Concesiones mineras",
     "source": "INGEMMET, Catastro Minero (GEOCATMIN), actualizado al 16 de octubre de 2026",
     "license": "Información pública de INGEMMET (GEOCATMIN, acceso libre); INGEMMET publica sus datos abiertos con ODbL. Citar la fuente.",
     "url": "https://geocatmin.ingemmet.gob.pe/arcgis/rest/services/SERV_CATASTRO_MINERO_WGS84/MapServer/0",
     "year": "2026", "color": "#a855f7", "geometry": "Polygon",
     "property_labels": {"concesion": "Concesión", "titular": "Titular (solo personas jurídicas)", "estado": "Estado", "ha": "Hectáreas"}},
    {"id": "reinfo", "file": "reinfo.geojson",
     "title": "Mineros en formalización (REINFO, MINEM)", "short": "REINFO",
     "source": "MINEM, Registro Integral de Formalización Minera, publicado por INGEMMET en GEOCATMIN (corte 26 de febrero de 2025)",
     "license": "Información pública de MINEM e INGEMMET (GEOCATMIN, acceso libre); INGEMMET publica sus datos abiertos con ODbL. Citar la fuente.",
     "url": "https://geocatmin.ingemmet.gob.pe/arcgis/rest/services/SERV_REINFO/MapServer/0",
     "year": "2025", "color": "#fb7185", "geometry": "Point",
     "property_labels": {"estado": "Estado", "actividad": "Actividad", "derecho": "Derecho minero"}},
    {"id": "peru-amazonia", "file": "peru-amazonia.geojson",
     "title": "Departamentos amazónicos del Perú", "short": "Amazonía peruana",
     "source": "geoBoundaries (William & Mary geoLab), Perú ADM1",
     "license": "Dominio público",
     "url": "https://www.geoboundaries.org/api/current/gbOpen/PER/ADM1/",
     "year": "2008", "color": "#334155", "geometry": "Polygon",
     "property_labels": {"departamento": "Departamento"}},
]

FAMILY = {"Polygon": {"Polygon", "MultiPolygon"}, "Point": {"Point", "MultiPoint"}}

def coords(g):
    t, c = g["type"], g["coordinates"]
    if t == "Point":
        yield c
    elif t in ("MultiPoint", "LineString"):
        yield from c
    elif t in ("Polygon", "MultiLineString"):
        for r in c:
            yield from r
    elif t == "MultiPolygon":
        for p in c:
            for r in p:
                yield from r

manifest, ok = [], True
for meta in LAYERS:
    path = os.path.join(OUT, meta["file"])
    raw = open(path, "rb").read()
    fc = json.loads(raw)
    assert fc.get("type") == "FeatureCollection", meta["file"]
    feats = fc["features"]
    n_bad = 0
    for f in feats:
        g = f.get("geometry")
        if not g or g["type"] not in FAMILY[meta["geometry"]]:
            n_bad += 1
            continue
        for x, y in (p[:2] for p in coords(g)):
            if not (LON[0] <= x <= LON[1] and LAT[0] <= y <= LAT[1]):
                n_bad += 1
                break
    gz = len(gzip.compress(raw, 6))
    status = "OK" if n_bad == 0 and gz < MAX_GZ and feats else "FAIL"
    ok &= status == "OK"
    print(f"{status} {meta['file']}: {len(feats)} features, {len(raw)} bytes, {gz} gz, bad={n_bad}")
    manifest.append(dict(meta, features=len(feats), bytes_gzip=gz))

if not ok:
    sys.exit("validation failed, layers.json not written")
order = ["id", "file", "title", "short", "source", "license", "url", "year", "color", "geometry", "features", "bytes_gzip", "property_labels"]
manifest = [{k: m[k] for k in order} for m in manifest]
with open(os.path.join(OUT, "layers.json"), "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
print("wrote layers.json with", len(manifest), "layers")
