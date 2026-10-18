# Open data layers for the Ojo de Cóndor map: sources and processing

All files fetched on 2026-10-17 (Lima) / 2026-10-18 UTC. All outputs are GeoJSON FeatureCollections in WGS84 (lon, lat),
validated by `scripts/build_manifest.py` (geometry type, coordinates inside lon -82..-68, lat -19..1, gzip level 6 under 400 KB)
and by `mapshaper -info`. Rebuild everything from `raw/` with `bash scripts/build_layers.sh`. Raw downloads total about 123 MB.

## mineria-amw.geojson (Amazon Mining Watch mining footprint)
URL: https://data.source.coop/earthgenome/amazon-mining-watch/amazon_basin_detections.geojson (113.4 MB, Last-Modified 2026-10-16),
the authoritative "detections_onset" product named in `data/outputs/MANIFEST.yaml` of https://github.com/earthrise-media/mining-detector
(product `amazon-aca-v4.10b-ensemble`, model 48px_v4.10b ensemble on Sentinel 2). License: CC BY 4.0 (stated in MANIFEST.yaml,
`license: CC-BY-4.0`; the repository code is MIT). Attribution: Amazon Mining Watch, Earth Genome and Amazon Conservation.
Each source feature is a ~480 m detection patch with `onset` (year 2018 to 2024 confirmed; quarters Q125 to Q326 provisional) and `status`.
Processing: clip to bbox then to the geoBoundaries Peru ADM0 polygon buffered 30 km (Albers equal area, `scripts/buffer_peru.py`),
29,551 patches kept; snap; `year` = onset year (quarters mapped to 2025 or 2026), `estado` = confirmado/provisional; dissolve by year and
estado; `area_ha` = area of the dissolved patch cells (overstates the real scar area, it is cell area, not mask area); simplify 5% keep-shapes;
precision 0.0002. Note: year 2018 means "already present by 2018" (start of the record). Result: 9 MultiPolygon features (one per year),
869,544 bytes, 153,569 bytes gzip.

## anp-sernanp.geojson (protected natural areas, SERNANP)
URL: https://geoservicios.sernanp.gob.pe/arcgis/rest/services/base_fisica/peru_sernanp_0102/MapServer layers 0 "ANP de Administracion
Nacional Definitiva" (104), 1 "ANP de Administracion Nacional Transitoria" (6) and 2 "Area de Conservacion Regional" (48), queried with
`f=geojson`, `maxAllowableOffset=0.0005`, paged 10 at a time (`scripts/arcgis_pager.py`). This is the WFS/REST service SERNANP lists on
https://geoportal.sernanp.gob.pe/ as its public "servicio de descarga". License: no license text on the service; public state information,
and SERNANP publishes its datasets on https://www.datosabiertos.gob.pe under Open Data Commons Attribution (ODC BY). Cite "SERNANP".
Processing (`scripts/sernanp_merge.py`): unified props `anp`, `categoria` (transitory = "Zona Reservada", regional = "Área de Conservación
Regional"), `codigo`, `ubicacion`, `ha` (legal area); kept areas intersecting Loreto, Ucayali, Madre de Dios, Amazonas, San Martín, Cusco,
Puno, Junín, Pasco, Huánuco (geoBoundaries ADM1, shrunk 0.02°), minus 11 high Andean or non Amazon areas (Titicaca, Huayhuash, Junín,
Huayllay, Chacamarca, Ausangate, Huaytapallana, Tres Cañones, Vilacota Maure, Cerro Khapia, Nor Yauyos-Cochas); simplify 20% keep-shapes,
precision 0.0001. Result: 58 features, 152,924 bytes, 47,324 bytes gzip.

## concesiones-ingemmet.geojson (mining concessions, INGEMMET)
URL: https://geocatmin.ingemmet.gob.pe/arcgis/rest/services/SERV_CATASTRO_MINERO_WGS84/MapServer/0 ("Catastro Minero", records updated
2026-10-16), queried by object id chunks (the server rejects pagination, `scripts/arcgis_ids.py`) with
`DEPA IN ('MADRE DE DIOS','LORETO','AMAZONAS','UCAYALI','SAN MARTIN') OR (DEPA='PUNO' AND PROVI IN ('SANDIA','CARABAYA'))`,
`maxAllowableOffset=0.0002`: 8,402 records. License: no license text on the service; GEOCATMIN is free public access, and INGEMMET
publishes its datasets on datosabiertos.gob.pe under ODbL. Cite "INGEMMET, Catastro Minero". Processing: kept current rights only
(LEYENDA TITULADO 4,534, TRAMITE 1,808, OTROS 364 = quarries and plants), dropped extinguished or blocked (1,696); props `concesion`,
`titular`, `estado` (Titulado, En trámite, Otro derecho), `ha`; simplify 10% keep-shapes, precision 0.0002, dropped 2 tiny quarries that
collapsed to empty. Privacy (`scripts/mask_persons.py`): `titular` is kept only when it looks like a legal entity (contains S.A., S.A.C.,
S.R.L., E.I.R.L., S.C.R.L., LTDA, SOCIEDAD, EMPRESA, MINERA, COMPAÑIA/COMPAÑÍA, CORPORACION/CORPORACIÓN, CONSORCIO, COOPERATIVA,
ASOCIACION/ASOCIACIÓN, COMUNIDAD, INVERSIONES, GRUPO, the dotless forms SA, SAC, SAA, SRL, EIRL, SCRL as whole words, or ends in INC, LLC,
CORP, or names a public body: GOBIERNO, MINISTERIO, MUNICIPALIDAD, UNIVERSIDAD, INSTITUTO, PROYECTO ESPECIAL, AUTORIDAD); otherwise it is
replaced by "Persona natural". 2,239 holders kept, 4,465 replaced. Result: 6,704 features, 1,856,404 bytes, 243,165 bytes gzip.

## reinfo.geojson (REINFO formalization registry)
URL: https://geocatmin.ingemmet.gob.pe/arcgis/rest/services/SERV_REINFO/MapServer/0 ("Reinfo - MINEM", points graphed by INGEMMET from
coordinates sent by MINEM's Dirección General de Formalización Minera; FECHA_ACTUALIZACION 2025-02-26 on every record), same department
filter (DEPARTAMENTO / PROVINCIA): 21,192 points (Puno Sandia and Carabaya 11,142, Madre de Dios 9,125, Amazonas 357, San Martín 318,
Loreto 163, Ucayali 87). License: same as INGEMMET above (public GEOCATMIN service; cite "MINEM, REINFO, vía INGEMMET GEOCATMIN").
Processing: props `estado` (Vigente 7,505 / Suspendido 13,687), `actividad` (Explotación / Beneficio), `derecho` (mining right name).
Miner names, legal representatives and RUC were deliberately NOT exported, so no holder name field remains (the privacy rule applied to
concessions has nothing to act on here; `derecho` is the name of the mining right, not of a person). Precision 0.0001. Result: 21,192 Point features,
3,679,930 bytes, 249,444 bytes gzip. Caveat: the registry snapshot is from February 2025; statuses may have changed since.

## peru-amazonia.geojson (context outline)
URL: https://github.com/wmgeolab/geoBoundaries/raw/90a1d52/releaseData/gbOpen/PER/ADM1/geoBoundaries-PER-ADM1.geojson (via
https://www.geoboundaries.org/api/current/gbOpen/PER/ADM1/). License: Public Domain (geoBoundaries gbOpen, source Wikimedia Commons).
Processing: kept Loreto, Ucayali, Madre de Dios, Amazonas, San Martín; prop `departamento`; simplify 60% keep-shapes, precision 0.001.
Result: 5 features, 25,517 bytes, 7,359 bytes gzip. The Peru ADM0 file from the same release
(.../gbOpen/PER/ADM0/geoBoundaries-PER-ADM0.geojson) was used only for the 30 km clip buffer.

## Skipped
- comunidades-nativas.geojson: not produced. MINCU's BDPI has no public WFS or download (geoservicios.cultura.gob.pe/geoserver exposes no
  feature types; the BDPI viewer uses an internal API with no license). RAISG territories (geo2.socioambiental.org/raisg/rest/services/
  aprotegida2024/MapServer/29, about 2,600 Peru native communities and indigenous reserves) are reachable, but RAISG's terms of use
  (https://www.raisg.org/es/terminos-de-uso/) allow only non profit use, require the data "no sean alteradas" (no simplification or
  clipping) and do not grant redistribution. IBC/SICNA and LandMark datasets require per dataset license acceptance and were not verified.
  INGEMMET's GEOCATMIN_SOCIAL folder requires a token.
