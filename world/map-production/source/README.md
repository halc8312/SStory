---
type: "overview"
category: "maps"
title: "Map Production Source"
version: "0.1.0"
created: "2026-07-18"
last_updated: "2026-07-18"
author: "halc8312"
tags: ["map-production", "geojson", "coordinates", "tiles"]
status: "draft"
document_kind: "readme"
summary: "高詳細地図制作で共有するEA-WORLD-1座標系と暫定形状データの案内です。"
---

# Map Production Source

This directory is the editable geometry baseline for the high-detail map pipeline.
It does not replace the lore documents or `world/map-data/data/`; it gives their
named features a shared geometry that is ready for rendering in a single planar coordinate space.

## EA-WORLD-1

`EA-WORLD-1` is a project-local, non-geodetic coordinate reference system.

- Extent: `x = 0..10000`, `y = 0..10000`
- Origin: the north-west corner of the printable world-map canvas
- Axes: `x` increases eastward; `y` increases southward; `z` increases upward
- Units: normalized image units, not km and not latitude/longitude
- Canonical raster transform: for `world-map-hires.jpg` (4096 x 2730),
  `x = pixel_x / 4096 * 10000` and `y = pixel_y / 2730 * 10000`
- GeoJSON coordinates are `[x, y]`. Vertical membership is carried in feature
  properties because RFC 7946 clients do not consistently preserve a third axis.

The legacy map-data README describes a south-west origin, but the current data,
pixel mapping, coordinate notes, and Leaflet `flipY` behavior all establish that a
smaller source `y` means farther north. EA-WORLD-1 records that actual convention
explicitly. No legacy coordinate was changed while creating this baseline.

GeoJSON normally implies WGS84 under RFC 7946. These files intentionally use a
local planar grid and declare it with the foreign member
`"coordinate_reference_system": "EA-WORLD-1"`; consumers must not send these
coordinates to a geographic projection without an explicit conversion.

## Source precedence and confidence

Names, IDs, affiliations, route endpoints, and vertical positions come from the
authoritative JSON files in `world/map-data/data/`. Visual placement is anchored
to `pixel-mapping.json` and `docs/assets/images/maps/world/world-map-hires.jpg`.
The older `world/maps/world-map.svg` is a secondary composition reference.

The current artwork does not provide survey-grade boundaries or route center lines.
Every newly traced polygon and line therefore carries both:

- `geometry_confidence: "estimated"`
- `review_status: "provisional"`

This distinction is important: an entity may have `source_confidence: "canon"`
while its drawn outline remains provisional. A generated image must preserve canon
entities and relationships, but must not present these draft edges as newly settled
lore.

## Files

- `landmasses.geojson`: five canon continent IDs with provisional coastlines
- `regions.geojson`: fourteen canon region IDs with provisional work areas
- `terrain.geojson`: visually identified terrain envelopes and axes
- `hydrography.geojson`: named waters and provisional river/channel axes
- `transport-geometries.geojson`: all route IDs connected at mapped node anchors
- `settlement-footprints.geojson`: provisional envelopes for settlement-like nodes
- `vertical-layers.json`: rendering bands that cover every currently used `z`
- `gazetteer.json`: searchable index of continent, region, node, and POI names
- `map-sheets.json`: world, continent, region, and golden-path production sheets

## Editing rules

1. Preserve IDs already present in `world/map-data/data/`.
2. A boundary becomes `reviewed` only after visual comparison at 100%, 200%, and
   400%, parent/child alignment review, and an explicit canon review where needed.
3. Generated imagery must never redefine coastlines, routes, settlements, or labels.
4. Labels and POIs remain vector data; do not bake them into generated raster tiles.
5. Record new geometric claims as `estimated` and `provisional` until evidence exists.
6. Keep polygon rings closed and all EA-WORLD-1 coordinates inside `0..10000`.

## Known limits

- Coastlines are manual low-vertex traces of the current 4096 x 2730 illustration,
  not coast-extraction output.
- Region borders are production work areas. The lore establishes membership and
  centers but not legal borders, so overlaps are intentional.
- Routes have canon endpoints but no canon waypoints; current center lines are direct
  endpoint connections (the Astralis loop is the one explicit schematic loop).
- Settlement envelopes indicate label/texture allocation areas, not walls or
  administrative limits.
- POIs have legacy local coordinates but no reviewed EA-WORLD-1 pixel anchors; the
  gazetteer preserves those source coordinates without inventing exact placements.
