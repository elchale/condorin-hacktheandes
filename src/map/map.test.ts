import { describe, expect, it } from "vitest";
import { footprintParts } from "./footprint";
import { h, raw } from "./html";

describe("h``", () => {
  it("escapes interpolated values", () => {
    expect(h`<b>${"<img onerror=x>"}</b>`.value).toBe("<b>&lt;img onerror=x&gt;</b>");
    expect(h`<a title="${`" onclick="x`}">`.value).toBe('<a title="&quot; onclick=&quot;x">');
  });

  it("nests h`` and raw() as markup, joins arrays and skips empty values", () => {
    const rows = ["a&b", "<c>"].map((x) => h`<li>${x}</li>`);
    expect(h`<ul>${rows}</ul>`.value).toBe("<ul><li>a&amp;b</li><li>&lt;c&gt;</li></ul>");
    expect(h`${raw("<br>")}${null}${undefined}${false}${0}`.value).toBe("<br>0");
  });
});

const square = (lon: number, lat: number, size: number): GeoJSON.Position[][] => [
  [
    [lon, lat],
    [lon + size, lat],
    [lon + size, lat + size],
    [lon, lat + size],
    [lon, lat],
  ],
];

describe("footprintParts", () => {
  it("splits each year's published area over its polygons by planar weight", () => {
    const fc: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: { year: 2024, area_ha: 300 },
          geometry: { type: "MultiPolygon", coordinates: [square(-70, -12, 0.01), square(-70.1, -12, 0.02)] },
        },
        { type: "Feature", properties: { year: 2025, area_ha: 50 }, geometry: { type: "Polygon", coordinates: square(-69, -11, 0.01) } },
        { type: "Feature", properties: { year: 2026, area_ha: 10 }, geometry: { type: "Point", coordinates: [-69, -11] } },
      ],
    };
    const parts = footprintParts(fc);
    expect(parts).toHaveLength(3);
    const y2024 = parts.filter((p) => p.year === 2024);
    expect(y2024.reduce((s, p) => s + p.ha, 0)).toBeCloseTo(300, 6);
    // The second square has four times the area of the first one.
    expect(y2024[1].ha / y2024[0].ha).toBeCloseTo(4, 2);
    expect(parts.find((p) => p.year === 2025)?.ha).toBeCloseTo(50, 6);
    // The center is the mean of the ring's vertices (closing point included).
    expect(y2024[0].lat).toBeCloseTo(-12 + (0.01 * 2) / 5, 9);
  });
});
