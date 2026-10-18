"""The live open data sources. Each module has ID, TTL_S, ATTRIBUTION, URL and fetch(meter) -> dict."""
from . import firms, glofas, openmeteo, sentinel

REGISTRY = {module.ID: module for module in (firms, sentinel, openmeteo, glofas)}

# Raster layers the map loads straight from Global Forest Watch (checked unauthenticated on 2026-10-18).
# The backend never fetches them, it only advertises them. `render_type=true_color` returns visible
# pink pixels; the plain `latest/default` tiles carry encoded dates and look black.
GFW_ATTRIBUTION = 'Global Forest Watch, University of Maryland'
GFW = 'https://tiles.globalforestwatch.org'
TILE_LAYERS = [
    {'id': 'gfw-integrated-alerts', 'title': 'Alertas de deforestación (GFW)',
     'dataset': 'GFW Integrated Deforestation Alerts (GLAD L, GLAD S2, RADD)',
     'url': f'{GFW}/gfw_integrated_alerts/latest/dynamic/{{z}}/{{x}}/{{y}}.png?render_type=true_color',
     'attribution': f'{GFW_ATTRIBUTION}, Integrated Deforestation Alerts',
     'min_zoom': 6, 'max_zoom': 14, 'opacity': 0.8},
    {'id': 'gfw-radd-alerts', 'title': 'Alertas por radar RADD (Sentinel 1)',
     'dataset': 'RADD Forest Disturbance Alerts (Wageningen University)',
     'url': f'{GFW}/wur_radd_alerts/latest/dynamic/{{z}}/{{x}}/{{y}}.png?render_type=true_color',
     'attribution': f'{GFW_ATTRIBUTION}, Wageningen University (RADD)',
     'min_zoom': 6, 'max_zoom': 14, 'opacity': 0.8},
    {'id': 'gfw-glad-s2-alerts', 'title': 'Alertas GLAD Sentinel 2',
     'dataset': 'GLAD Sentinel 2 Alerts',
     'url': f'{GFW}/umd_glad_sentinel2_alerts/latest/dynamic/{{z}}/{{x}}/{{y}}.png?render_type=true_color',
     'attribution': f'{GFW_ATTRIBUTION}, GLAD Sentinel 2 Alerts',
     'min_zoom': 6, 'max_zoom': 14, 'opacity': 0.8},
    {'id': 'gfw-tree-cover-loss', 'title': 'Pérdida de bosque desde 2001 (Hansen)',
     'dataset': 'Tree Cover Loss (Hansen/UMD/Google/USGS/NASA), canopy density 30 %',
     'url': f'{GFW}/umd_tree_cover_loss/latest/dynamic/{{z}}/{{x}}/{{y}}.png?tcd=30&render_type=true_color',
     'attribution': f'{GFW_ATTRIBUTION}, Hansen et al. Tree Cover Loss',
     'min_zoom': 3, 'max_zoom': 12, 'opacity': 0.7},
]
