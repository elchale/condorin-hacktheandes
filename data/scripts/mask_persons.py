"""Replace holder names that do not look like a legal entity with "Persona natural" (privacy rule from the coordinator).
Usage: python -X utf8 -I mask_persons.py <file.geojson> <field> [<field> ...]  (rewrites in place, compact)"""
import json, re, sys
from collections import Counter

# Substring markers (dotted abbreviations and words) and dotless abbreviations as whole words.
MARKERS = ["S.A.", "S.A.C.", "S.R.L.", "E.I.R.L.", "S.C.R.L.", "LTDA", "SOCIEDAD", "EMPRESA", "MINERA", "COMPAÑIA", "COMPAÑÍA",
           "CORPORACION", "CORPORACIÓN", "CONSORCIO", "COOPERATIVA", "ASOCIACION", "ASOCIACIÓN", "COMUNIDAD", "INVERSIONES", "GRUPO",
           # Public bodies (coordinator decision 2026-10-18)
           "GOBIERNO", "MINISTERIO", "MUNICIPALIDAD", "UNIVERSIDAD", "INSTITUTO", "PROYECTO ESPECIAL", "AUTORIDAD"]
WORDS = re.compile(r"\b(SA|SAC|SAA|SRL|EIRL|SCRL)\b")
ENDS = re.compile(r"\b(INC|LLC|CORP)\.?\s*$")

def is_entity(name):
    n = (name or "").upper().strip()
    return bool(n) and (any(m in n for m in MARKERS) or WORDS.search(n) or ENDS.search(n))

path, fields = sys.argv[1], sys.argv[2:]
fc = json.load(open(path, encoding="utf-8"))
stats = Counter()
for f in fc["features"]:
    p = f["properties"]
    for k in fields:
        if k in p:
            if is_entity(p[k]):
                stats["kept"] += 1
            else:
                p[k] = "Persona natural"
                stats["masked"] += 1
with open(path, "w", encoding="utf-8") as fh:
    json.dump(fc, fh, ensure_ascii=False, separators=(",", ":"))
print("mask_persons", path, fields, dict(stats))
