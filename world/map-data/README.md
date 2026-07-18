---
type: "overview"
category: "maps"
title: "Map Data"
version: "0.2.1"
created: "2026-05-06"
last_updated: "2026-07-18"
author: "halc8312"
tags: ["map-data", "geography", "transportation", "json"]
status: "draft"
document_kind: "readme"
summary: "世界地図の機械可読データ、スキーマ、同期・検証手順の案内です。"
---

# Map Data - Eternal Arcadia

## Purpose

This directory contains structured, machine-readable map data for the world of **Eternal Arcadia**. The data represents the geographical layout, transportation network, nodes (cities, ports, airports), routes (roads, sea lanes, air routes, special paths), and hazard zones.

The current data format is **Map Data v0.1**; the frontmatter `version` tracks revisions to this README. The dataset remains a prototype foundation for future web maps, tile maps, and game integration.

## Canon Boundary

- `world/map-data/data/*.json` is the authoritative editing source for machine-readable map data. The copies under `docs/data/map/` are generated publication artifacts and must not be edited directly.
- This source-of-truth role does not make every JSON value canon. `confidence: "canon"` means that a value is supported by a stable canon document; `estimated`, `inferred`, and `placeholder` values remain tooling aids or proposals.
- POIs with `status: "draft"` are proposals, even when they are usable in the map viewer. Stable canon documents take precedence whenever prose and structured data disagree.
- Files under `schemas/`, `docs/`, and `examples/` define formats, workflows, or examples; they are technical project documentation rather than facts about the world.

See [`CANON_POLICY.md`](../../CANON_POLICY.md) for the repository-wide policy.

## File Structure

```
world/map-data/
  README.md              # This file
  data/
    continents.json      # Five major continents
    regions.json         # Regional divisions
    nodes.json           # Cities, ports, airports, terminals (30+)
    routes.json          # Transportation paths (25+)
    hazards.json         # Danger zones (6+)
    pois.json            # POI and spots data (planned)
    pixel-mapping.json   # Canonical ID-to-world-image pixel coordinates
  schemas/
    continent.schema.json
    region.schema.json
    node.schema.json
    route.schema.json
    hazard.schema.json
    poi.schema.json      # POI schema (v0.1)
    pixel-mapping.schema.json
  docs/
    poi-data-spec.md     # POI data specification v0.1
    poi-authoring-template.md
    poi-review-checklist.md
    poi-ai-addition-workflow.md
  scripts/
    sync_map_data.py
    validate_pois.py
  examples/
    route_astralis_to_jade_port.json   # Example route output
    route_astralis_to_marineport.json
    route_portzephia_to_timeport.json
  exports/
    world_transport.geojson    # Combined GeoJSON
    nodes.geojson              # Node points
    routes.geojson             # Route lines
    hazards.geojson            # Hazard polygons/points
    world_transport_network.svg   # Static visualization
```

## Coordinate System

- **System**: Abstract internal coordinate system
- **Range**: X and Y from 0 to 10,000 (integer)
- **Origin**: Southwest corner of the world map
- **Z-axis**: Vertical layer (0 = ground/sea level, positive = air/floating, negative = underwater/underground)

Approximate continent centers:

| Continent | Center (X, Y) |
|-----------|---------------|
| Elysion   | (5000, 5000)  |
| Lumiera   | (7500, 4700)  |
| Chaos Ria | (5000, 7600)  |
| Atlantis  | (2500, 4700)  |
| Grimoire  | (5000, 2200)  |

Coordinates are approximate in v0.1. Precision will improve in future versions.

## Data Types

### Node Types

Nodes represent locations: cities, ports, airports, terminals, landmarks, etc.

Available types:

- `capital` - National/continental capital
- `city` - Major city
- `town` - Town
- `port` - Sea port
- `airport` - Full airport
- `air_terminal` - Smaller air facility
- `carriage_terminal` - Station/terminal for land transport
- `inn` - Inn, tavern, waystation
- `checkpoint` - Border checkpoint, guard post
- `oasis` - Desert oasis
- `caravan_lodge` - Caravanserai
- `floating_island` - Floating island settlement
- `underwater_city` - Underwater city
- `submarine_terminal` - Submarine base
- `warp_gate` - Teleportation gate
- `forbidden_gate` - Forbidden/sealed gate
- `landmark` - Notable landmark
- `ruin` - Ruins

### Route Types

Routes connect nodes and represent transportation paths.

**Route types:**

- `road` - Road/highway
- `rail` - Railway/magical train
- `sea` - Sea route
- `air` - Air route
- `caravan` - Caravan/dessert route
- `submarine` - Submarine route
- `tunnel` - Underground tunnel
- `underwater_tunnel` - Undersea tunnel
- `ice_road` - Ice road
- `warp` - Warp/teleport
- `forbidden_path` - Forbidden path

**Modes** (transportation method):

- `stagecoach`, `express_carriage`, `magic_train`
- `wind_magic_ship`, `sailing_ship`
- `airship`, `griffin`
- `caravan`, `sand_vehicle`
- `submarine`, `tidal_train`
- `walking`, `spirit_warp`, `chrono_tunnel`

**Status:**

- `active` - Regularly operating
- `seasonal` - Seasonal operation
- `restricted` - Permits required
- `forbidden` - Closed/forbidden
- `experimental` - Experimental/test phase
- `dangerous` - Known hazardous
- `closed` - Permanently closed

**Danger level:** 0 (safe) to 5 (forbidden)

### Hazard Types

Hazard zones represent dangerous areas affecting travel.

Types: `sandstorm`, `pirate_sea`, `ice_sea`, `time_distortion`, `forbidden_zone`, `monster_sea`, `volcanic_zone`, `avalanche`, `spirit_anomaly`, `fog`, `storm`

**Severity:** 0 (none) to 5 (catastrophic)

### Confidence Levels

- `canon` - Explicitly stated in repository documents
- `estimated` - Coordinates/distances estimated for map tooling
- `inferred` - Logically derived but not directly stated
- `placeholder` - Temporary value requiring later review

## Validation

Validate all map data files:

```bash
python tools/map/validate_map_data.py
```

Example output (counts may vary):

```
Map data validation passed.
  Continents: <count>
  Regions: <count>
  Nodes: <count>
  Routes: <count>
  Hazards: <count>
```

The actual counts reflect the current dataset and may change over time. Run the validator for the latest numbers.

The validator checks:

- Unique IDs across all datasets
- All required fields present
- Reference integrity (IDs exist, continent/region/node references valid)
- Enum values valid (types, modes, status, etc.)
- Value ranges (danger_level 0-5, severity 0-5, coordinates 0-10000)
- Confidence levels valid

## POI Data Specification

POI (Point of Interest) data is managed in [`data/pois.json`](./data/pois.json) and follows
the specification defined in [`docs/poi-data-spec.md`](./docs/poi-data-spec.md).

### Purpose

POIs represent specific facilities, landmarks, and spots within settlements or
along transportation routes: markets, shops, inns, temples, guilds, academies,
theaters, administrative buildings, industrial sites, research facilities,
dungeon entrances, hazardous locations, and more.

### Data Structure

Each POI entry includes:

- **Basic info**: id, name, category, type
- **Location**: continent_id, region_id, nearest_node_id, position (x,y,z)
- **Importance**: 1–5 scale (local to world-significant)
- **Status**: draft, active, historical, ruined, restricted, sealed, abandoned, seasonal, hidden
- **Justification fields** (required): lore_basis, historical_reason, economic_role, cultural_role, transport_role, risk_context
- **Tags**: keywords for filtering

See [`docs/poi-data-spec.md`](./docs/poi-data-spec.md) for full field definitions and examples.

### Alignment Rules

All POIs must align with:

- continental history and geography
- city and regional roles
- transportation networks
- established religion and beliefs
- magic systems
- political structure
- economic sphere
- hazard zones
- existing Map Data
- canon setting documents

The required justification fields (`lore_basis`, `historical_reason`, etc.) enforce
this alignment. See [`poi-design-guidelines.md`](./poi-design-guidelines.md) for detailed rules.

### Schema Validation

POI data is validated against [`schemas/poi.schema.json`](./schemas/poi.schema.json).
The schema enforces:

- Required fields presence
- Enum values for `category` (21 types) and `status` (9 types)
- `importance` as integer 1–5
- Coordinate ranges (0–10000 for x, y; any number for z)
- Pattern matching for IDs (lowercase snake_case)
- Non-empty arrays for `lore_basis` and `tags`
- No additional properties beyond defined optional fields

### Current Status

**v0.1 — Astralis starter dataset under review.**

`pois.json` currently contains 31 reviewed Elysion trial entries: 16 Astralis
capital-region facilities, 7 Astralis–Port Zephia road-corridor facilities, and
8 Port Zephia harbor facilities.
Core facilities such as the royal palace, grand market, carriage plaza, magic
academy, star-cup temple, and Port Zephia customs / warehouse functions can be
treated as `active`, while flavor or placement-sensitive facilities remain
`draft`.

IDs currently follow the `astralis_`, `astralis_zephia_road_`, and
`port_zephia_` prefix naming conventions. The dataset remains intentionally
limited to an Elysion capital / road / harbor baseline so later
continent-by-continent expansion can build on a reviewed foundation.

### GitHub Pages Copy

GitHub Pages uses the copy at [`docs/data/map/pois.json`](../../docs/data/map/pois.json).
Use `python world/map-data/scripts/sync_map_data.py` to copy all authoritative source map
data files (continents, regions, nodes, routes, hazards, POIs, pixel mapping) from
`world/map-data/data/` to `docs/data/map/`. Pass `--check` to verify the copies
without writing (used in CI).

### POI Addition Flow

When adding or reviewing POIs:

1. Read [`poi-design-guidelines.md`](./poi-design-guidelines.md)
2. Read [`docs/poi-data-spec.md`](./docs/poi-data-spec.md)
3. Draft the request with [`docs/poi-authoring-template.md`](./docs/poi-authoring-template.md)
4. Edit [`data/pois.json`](./data/pois.json)
5. Sync [`docs/data/map/pois.json`](../../docs/data/map/pois.json)
6. Run `python -m json.tool` for both POI files and the schema
7. Run `python world/map-data/scripts/validate_pois.py`
8. Check the result on Leaflet and confirm `focusPoi()` works
9. Review with [`docs/poi-review-checklist.md`](./docs/poi-review-checklist.md)

## POI追加の標準手順

1. IssueテンプレートからPOI追加依頼を作成する
2. `poi-design-guidelines.md` を確認する
3. `poi-data-spec.md` を確認する
4. `poi-authoring-template.md` に沿って内容を作る
5. `world/map-data/data/pois.json` を編集する
6. `sync_map_data.py` で docs 側へ同期する
7. `validate_pois.py` で検証する
8. Leaflet上で `focusPoi()` を確認する
9. `poi-review-checklist.md` でレビューする

## POI Design Guidance

For detailed design rules and world-alignment requirements, see
[POI / Spot Design Guidelines](./poi-design-guidelines.md).

This guideline defines:

- Core principle: POIs must arise from world settings
- Alignment checklists
- Required evidence fields (same as specification)
- Continental POI tendencies (Elysion, Lumiera, Chaos Ria, Atlantis, Grimoire)
- POI capacity by settlement scale
- Common POIs around transport nodes
- Proposed categories and naming rules
- Rules against shallow additions

## Route Finder

Find optimal routes between nodes:

```bash
# Find fastest route from Astralis to Jade Port
python tools/map/route_finder.py --from astralis --to jade_port --weight time

# Exclude air routes
python tools/map/route_finder.py --from astralis --to jade_port --weight time --no-air

# Exclude sea routes
python tools/map/route_finder.py --from port_zephia --to marineport --weight time --no-sea

# Seasonal route in summer (month 7); avoid high danger
python tools/map/route_finder.py --from port_zephia --to time_port --weight safety --avoid-danger-level 4 --month 7

# Seasonal route check in winter (month 12) - likely no route
python tools/map/route_finder.py --from port_zephia --to time_port --weight safety --avoid-danger-level 4 --month 12
```

**Weight options:**

- `time` - Minimize travel time (hours)
- `distance` - Minimize distance (km)
- `safety` - Minimize `estimated_time_hours × (danger_level + 1)²`
- `cost` - Minimize gold cost

**Filters:**

- `--avoid-danger-level N` - Skip routes with danger >= N
- `--no-air` - Exclude air routes (default: air routes are included)
- `--no-sea` - Exclude sea routes (default: sea routes are included)
- `--allow-restricted` - Include routes with status `restricted` (permits required). Does not affect `seasonal` routes.
- `--month N` - Travel month (1-12); seasonal routes only operate in their active months. If omitted, seasonal routes are included but their seasonal availability is not evaluated.

**Route status handling (v0.1):**

- `active` - always included
- `seasonal` - included if `--month` matches `active_months`; if `--month` is omitted, included with unresolved availability; if months are missing while a month is requested, excluded
- `restricted` - excluded unless `--allow-restricted` is given
- `forbidden` - always excluded (no option to include)
- `experimental`, `dangerous`, `closed` - always excluded

## GeoJSON Export

Export map data to GeoJSON for use in GIS software, web maps, etc.:

```bash
python tools/map/export_geojson.py
```

Outputs in `world/map-data/exports/`:

- `world_transport.geojson` - Combined features
- `nodes.geojson` - Points
- `routes.geojson` - LineStrings
- `hazards.geojson` - Points with radius data

Coordinates use internal x/y directly. No lat/lon conversion in v0.1.

## Static Network Visualization

Generate a simple SVG visualization:

```bash
python tools/map/render_static_network.py
```

Output: `world/map-data/exports/world_transport_network.svg`

Features:

- Lines colored by route type (brown=road, blue=sea, pink=air, green=rail, gold=caravan, purple=special)
- Nodes sized/colored by type (red=capital, blue=port, pink=airport, purple=floating)
- Labels for major nodes
- Hover tooltips with names and types

Open the SVG file in any browser or vector graphics editor.

## Data Sources

Canon data extracted from:

- `world/geography/continents.md`
- `world/geography/regions/central-region.md`
- `world/transportation/land-transportation.md`
- `world/transportation/sea-routes.md`
- `world/transportation/air-transportation.md`
- `world/transportation/sky-routes.md`
- `world/transportation/stations-and-terminals.md`

## Roadmap (Future)

**v0.2 Goals:**

- Expand node count to 100+
- Add more regional routes
- Include precise distance/time data
- Add name_en fields for English localization
- Implement web map viewer prototype
- Add tilemap support for regional areas

**Long-term:**

- Interactive web map with Leaflet/OpenLayers
- Real-time route planning with constraints
- Integration with game engine
- Full world coverage with all settlements

## Contributing

When adding data:

1. Follow the JSON schemas strictly
2. Use lowercase snake_case for all IDs
3. Preserve Japanese names in `name` field
4. Mark uncertain values with `"confidence": "estimated"` or `"inferred"`
5. Keep data human-editable (pretty-printed JSON)
6. Add no generated files to version control (exports are generated)

## License

Same as repository license. See `LICENSE` file.
