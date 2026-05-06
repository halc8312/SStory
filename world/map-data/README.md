# Map Data - Eternal Arcadia

## Purpose

This directory contains structured, machine-readable map data for the world of **Eternal Arcadia**. The data represents the geographical layout, transportation network, nodes (cities, ports, airports), routes (roads, sea lanes, air routes, special paths), and hazard zones.

This is **Map Data v0.1** — a prototype foundation for future web maps, tile maps, and game integration.

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
  schemas/
    continent.schema.json
    region.schema.json
    node.schema.json
    route.schema.json
    hazard.schema.json
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

## POI Design Guidance

For future spot and POI expansion on the Leaflet-based world map, see
[`poi-design-guidelines.md`](./poi-design-guidelines.md).

This guideline defines lore-alignment rules, required evidence fields, category
proposals, naming rules, and the planned path toward `pois.json`.

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
- `safety` - Maximize safety (penalizes danger level)
- `cost` - Minimize gold cost

**Filters:**
- `--avoid-danger-level N` - Skip routes with danger >= N
- `--no-air` - Exclude air routes (default: air routes are included)
- `--no-sea` - Exclude sea routes (default: sea routes are included)
- `--allow-restricted` - Include routes with status `restricted` (permits required). Does not affect `seasonal` routes.
- `--month N` - Travel month (1-12); seasonal routes only operate in their active months. If omitted, seasonal routes are included but their seasonal availability is not evaluated.

**Route status handling (v0.1):**
- `active` - always included
- `seasonal` - included if `--month` matches `active_months`; if `--month` omitted, included without evaluation
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
