# Map Tools - Eternal Arcadia

Python command-line tools for working with Eternal Arcadia map data.

## Overview

These tools provide validation, route finding, data export, and visualization capabilities for the structured map data system.

**Requirements:**
- Python 3.10+ (standard library only, no external dependencies)

## Tools

### validate_map_data.py

Validates all map data files for consistency, referential integrity, and basic structural checks.

```bash
python tools/map/validate_map_data.py
```

**Checks:**
- All IDs are unique across datasets
- Required fields present in every record
- All foreign key references exist (continent_id, region_id, node references)
- Enum values are valid
- Value ranges are correct (danger_level 0-5, coordinates 0-10000, etc.)
- Confidence levels are valid

**Exit codes:**
- 0 = success
- 1 = validation failed (errors printed to stderr)

---

### route_finder.py

Finds optimal routes between two nodes using Dijkstra's algorithm.

```bash
python tools/map/route_finder.py --from <node_id> --to <node_id> [options]
```

**Arguments:**
- `--from NODE_ID` - Starting node ID (required)
- `--to NODE_ID` - Destination node ID (required)
- `--weight {time,distance,safety,cost}` - Optimization metric (default: time)

**Filtering options:**
- `--avoid-danger-level N` - Exclude routes with danger >= N (e.g., 4 = avoid very dangerous)
- `--no-air` - Exclude air routes (default: air routes included)
- `--no-sea` - Exclude sea routes (default: sea routes included)
- `--allow-restricted` - Include routes with status `restricted` (does not affect seasonal routes)
- `--month N` - Travel month (1-12); seasonal routes only operate in their active months. If not specified, seasonal routes are included without month-based filtering (availability uncertain).

**Route status:**
- `active` - Regularly operating
- `seasonal` - Seasonal operation (controlled by `--month` and `active_months`)
- `restricted` - Permits required (requires `--allow-restricted`)
- `forbidden` - Always excluded in v0.1 (no option to include)
- `experimental` / `dangerous` / `closed` - Always excluded

**Examples:**

```bash
# Fastest time from Astralis to Jade Port (default includes air/sea routes)
python tools/map/route_finder.py --from astralis --to jade_port --weight time

# Exclude air routes
python tools/map/route_finder.py --from astralis --to jade_port --weight time --no-air

# Exclude sea routes
python tools/map/route_finder.py --from port_zephia --to time_port --weight safety --no-sea

# Seasonal northern ocean route in summer (month 7); avoid high danger
python tools/map/route_finder.py --from port_zephia --to time_port --weight safety --avoid-danger-level 4 --month 7

# Check winter exclusion of seasonal northern ocean route (month 12)
python tools/map/route_finder.py --from port_zephia --to time_port --weight safety --avoid-danger-level 4 --month 12
```

**Output:**
- Route name and total optimized metric
- Segments with route names, types, modes, times, distances, danger levels
- Overall danger summary

---

### export_geojson.py

Exports map data to GeoJSON format for interoperability with GIS software and web maps.

```bash
python tools/map/export_geojson.py
```

**Outputs** (to `world/map-data/exports/`):
- `world_transport.geojson` - Combined FeatureCollection (nodes + routes + hazards)
- `nodes.geojson` - Point features for all nodes
- `routes.geojson` - LineString features for all routes
- `hazards.geojson` - Point features for hazard centers (radius in properties)

**Coordinate system:** Internal x/y coordinates (0-10000 range) used directly. No real-world projection in v0.1.

---

### render_static_network.py

Generates a simple static SVG visualization of the transport network.

```bash
python tools/map/render_static_network.py
```

**Output:** `world/map-data/exports/world_transport_network.svg`

**Features:**
- Routes drawn as colored lines by type
- Nodes drawn as circles sized/colored by importance
- Labels for major nodes
- Hover tooltips (in browser/vector viewer)

**Color scheme:**
- Roads: brown
- Sea: blue
- Air: pink
- Rail: green
- Caravan: gold
- Special: purple

---

## Data Format

All data stored in `world/map-data/data/` as JSON. See `world/map-data/README.md` for detailed schema documentation.

**Key files:**
- `continents.json` - 5 major continents
- `regions.json` - 13 regions
- `nodes.json` - locations (cities, ports, airports, etc.); count varies with data updates
- `routes.json` - transportation paths; count varies with data updates
- `hazards.json` - danger zones; count varies

## Common Tasks

### Validate everything before committing
```bash
python tools/map/validate_map_data.py
```

### Test route connectivity
```bash
python tools/map/route_finder.py --from astralis --to jade_port --weight time
```

### Generate exports for web use
```bash
python tools/map/export_geojson.py
```

### Create a preview image
```bash
python tools/map/render_static_network.py
```

## Troubleshooting

**"No route found"** - Check that nodes exist and are connected via routes. Use `--no-air`/`--no-sea` to exclude route types if needed. Restricted routes require `--allow-restricted`. Seasonal routes require appropriate `--month` (1-12) and are only available in their active months.

## Development Notes

- All scripts must run from repository root
- No external dependencies (Python stdlib only for v0.1)
- Output files in `exports/` are generated and should not be committed (except for documentation)
- Data files use UTF-8 encoding
- ID format: `^[a-z][a-z0-9_]*$` (lowercase snake_case)

## Future Enhancements

- v0.2: Add CLI output format options (JSON, table, plain)
- v0.2: Add route comparison mode
- v0.2: Support multi-stop routing
- v1.0: Web API integration
- v1.0: Real-time traffic/weather simulation
