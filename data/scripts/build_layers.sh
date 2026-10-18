#!/usr/bin/env bash
# Rebuild every layer in mapa-data/out from the raw downloads (see out/SOURCES.md for download URLs).
# Run from anywhere: bash mapa-data/scripts/build_layers.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
MS="node scripts/node_modules/mapshaper/bin/mapshaper"
PY=".venv/Scripts/python -X utf8 -I"
mkdir -p work out

# 0. Peru boundary + 30 km buffer (clip mask for AMW)
$PY scripts/buffer_peru.py raw/geoboundaries/PER-ADM0.geojson work/peru-buffer30.geojson 30

# 1. Amazon Mining Watch detections -> Peru + 30 km, dissolved by onset year
$MS -i raw/amw/amazon_basin_detections.geojson \
  -clip bbox=-81.6,-18.7,-68.3,0.3 -clip work/peru-buffer30.geojson -o work/amw-peru-raw.geojson
$MS -i work/amw-peru-raw.geojson snap \
  -each "year = onset.charAt(0)=='Q' ? 2000 + Number(onset.slice(2)) : Number(onset); estado = status=='confirmed' ? 'confirmado' : 'provisional'" \
  -dissolve fields=year,estado -o work/amw-diss.geojson
$MS -i work/amw-diss.geojson -each "area_ha = Math.round(this.area/10000)" \
  -simplify 5% keep-shapes -filter-fields year,estado,area_ha -o precision=0.0002 out/mineria-amw.geojson

# 2. SERNANP protected areas (definitive + transitory + ACR) touching Amazon departments
$PY scripts/sernanp_merge.py raw/sernanp raw/geoboundaries/PER-ADM1.geojson work/anp-merged.geojson
$MS -i work/anp-merged.geojson -simplify 20% keep-shapes -o precision=0.0001 out/anp-sernanp.geojson

# 3. INGEMMET mining concessions, current rights only (titulado, en trámite, otros)
$MS -i raw/ingemmet/catastro_amazonia.geojson \
  -filter "LEYENDA=='TITULADO' || LEYENDA=='TRAMITE' || LEYENDA=='OTROS'" \
  -each "concesion = CONCESION; titular = TIT_CONCES; estado = ({TITULADO:'Titulado',TRAMITE:'En trámite',OTROS:'Otro derecho'})[LEYENDA]; ha = Math.round(HECTAGIS)" \
  -filter-fields concesion,titular,estado,ha -simplify 10% keep-shapes -o precision=0.0002 out/concesiones-ingemmet.geojson
$PY scripts/drop_empty.py out/concesiones-ingemmet.geojson
$PY scripts/mask_persons.py out/concesiones-ingemmet.geojson titular

# 5. REINFO points (no personal names, no RUC)
$MS -i raw/reinfo/reinfo_amazonia.geojson \
  -each "estado = ESTADO=='VIGENTE' ? 'Vigente' : 'Suspendido'; actividad = TIPO_ACT=='BENEFICIO' ? 'Beneficio' : 'Explotación'; derecho = NOMBRE_DM" \
  -filter-fields estado,actividad,derecho -o precision=0.0001 out/reinfo.geojson

# Context outline
$MS -i raw/geoboundaries/PER-ADM1.geojson \
  -filter "['Loreto','Ucayali','Madre de Dios','Amazonas','San Martín'].indexOf(shapeName) > -1" \
  -each "departamento = shapeName" -filter-fields departamento -simplify 60% keep-shapes \
  -o precision=0.001 out/peru-amazonia.geojson

$PY scripts/build_manifest.py out
