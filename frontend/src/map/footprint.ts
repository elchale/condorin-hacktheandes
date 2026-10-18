/** Bounding box center and planar weight of every polygon part, for the "in view" hectares. */
export type Part = { lat: number; lon: number; year: number; ha: number };
export function footprintParts(gj: GeoJSON.FeatureCollection): Part[] {
  const out: Part[] = [];
  for (const f of gj.features) {
    const year = Number(f.properties?.year) || 0;
    const total = Number(f.properties?.area_ha) || 0;
    const g = f.geometry;
    const polys = g.type === "MultiPolygon" ? g.coordinates : g.type === "Polygon" ? [g.coordinates] : [];
    const mine: Part[] = [];
    let sum = 0;
    for (const poly of polys) {
      const ring = poly[0];
      let a = 0;
      let sx = 0;
      let sy = 0;
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        a += (ring[j][0] - ring[i][0]) * (ring[j][1] + ring[i][1]);
        sx += ring[i][0];
        sy += ring[i][1];
      }
      const w = Math.abs(a) * Math.cos(((sy / ring.length) * Math.PI) / 180);
      sum += w;
      mine.push({ lon: sx / ring.length, lat: sy / ring.length, year, ha: w });
    }
    // Scale the planar weights so each year adds up to its published area.
    for (const p of mine) out.push({ ...p, ha: sum ? (p.ha / sum) * total : 0 });
  }
  return out;
}
