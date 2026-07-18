#!/usr/bin/env python3
"""
Map Data Validator

Validates the structured map data files for consistency and correctness.
Checks: unique IDs, valid references, basic structural checks, value ranges.
"""

import sys

from jsonschema import Draft7Validator
from jsonschema.exceptions import SchemaError

try:
    from tools.map.common import DATA_DIR, load_json
except ImportError:  # run as a script from tools/map
    from common import DATA_DIR, load_json

# Value sets
VALID_ROUTE_TYPES = {"road", "rail", "sea", "air", "caravan", "submarine", "tunnel", "underwater_tunnel", "ice_road", "warp", "forbidden_path"}
VALID_ROUTE_MODES = {"stagecoach", "express_carriage", "magic_train", "wind_magic_ship", "sailing_ship", "airship", "griffin", "caravan", "sand_vehicle", "submarine", "tidal_train", "walking", "spirit_warp", "chrono_tunnel"}
VALID_ROUTE_STATUS = {"active", "seasonal", "restricted", "forbidden", "experimental", "dangerous", "closed"}
VALID_NODE_TYPES = {"capital", "city", "town", "port", "airport", "air_terminal", "carriage_terminal", "inn", "checkpoint", "oasis", "caravan_lodge", "floating_island", "underwater_city", "submarine_terminal", "warp_gate", "forbidden_gate", "landmark", "ruin"}
VALID_HAZARD_TYPES = {"sandstorm", "pirate_sea", "ice_sea", "time_distortion", "forbidden_zone", "monster_sea", "volcanic_zone", "avalanche", "spirit_anomaly", "fog", "storm"}
VALID_CONFIDENCE = {"canon", "estimated", "inferred", "placeholder"}
SCHEMA_DIR = DATA_DIR.parent / "schemas"


def validate_json_schema(data, schema_filename, *, collection):
    """Validate canonical map data against its checked-in Draft 7 schema."""
    schema = load_json(SCHEMA_DIR / schema_filename)
    try:
        Draft7Validator.check_schema(schema)
    except SchemaError as error:
        return [f"invalid schema {schema_filename}: {error.message}"]

    validator = Draft7Validator(schema)
    if collection:
        if not isinstance(data, list):
            return ["root must be an array"]
        instances = enumerate(data)
    else:
        instances = [(None, data)]

    errors = []
    for index, instance in instances:
        schema_errors = sorted(
            validator.iter_errors(instance),
            key=lambda error: tuple(str(part) for part in error.path),
        )
        for schema_error in schema_errors:
            path_parts = [str(part) for part in schema_error.path]
            if index is not None:
                path_parts.insert(0, str(index))
            location = ".".join(path_parts) or "<root>"
            errors.append(f"schema violation at {location}: {schema_error.message}")
    return errors


def collect_ids(records):
    """Collect string IDs without crashing on malformed records."""
    if not isinstance(records, list):
        return set()
    return {
        record["id"]
        for record in records
        if isinstance(record, dict) and isinstance(record.get("id"), str)
    }


def data_count(data):
    """Return a printable collection size for validation output."""
    return len(data) if isinstance(data, (list, dict)) else 0


def validate_continents(continents, all_ids):
    errors = []
    ids = [c['id'] for c in continents]
    if len(ids) != len(set(ids)):
        errors.append("Duplicate continent IDs found")
    all_ids.update(ids)

    for c in continents:
        if c.get('type') != 'continent':
            errors.append(f"Continent {c['id']}: type must be 'continent'")
        if 'center' not in c:
            errors.append(f"Continent {c['id']}: missing center")
        else:
            center = c['center']
            if not (0 <= center.get('x', -1) <= 10000 and 0 <= center.get('y', -1) <= 10000):
                errors.append(f"Continent {c['id']}: center coordinates out of range")
        if c.get('confidence') not in VALID_CONFIDENCE:
            errors.append(f"Continent {c['id']}: invalid confidence level")
    return errors

def validate_regions(regions, all_ids, continent_ids):
    errors = []
    ids = [r['id'] for r in regions]
    if len(ids) != len(set(ids)):
        errors.append("Duplicate region IDs found")
    all_ids.update(ids)

    for r in regions:
        if r.get('continent_id') not in continent_ids:
            errors.append(f"Region {r['id']}: invalid continent_id '{r.get('continent_id')}'")
        if r.get('confidence') not in VALID_CONFIDENCE:
            errors.append(f"Region {r['id']}: invalid confidence level")
    return errors

def validate_nodes(nodes, all_ids, continent_ids, region_ids):
    errors = []
    ids = [n['id'] for n in nodes]
    if len(ids) != len(set(ids)):
        errors.append("Duplicate node IDs found")
    all_ids.update(ids)

    for n in nodes:
        if n.get('continent_id') not in continent_ids:
            errors.append(f"Node {n['id']}: invalid continent_id '{n.get('continent_id')}'")
        region_id = n.get('region_id')
        if region_id and region_id not in region_ids:
            errors.append(f"Node {n['id']}: invalid region_id '{region_id}'")
        if n.get('type') not in VALID_NODE_TYPES:
            errors.append(f"Node {n['id']}: invalid type '{n.get('type')}'")
        if n.get('confidence') not in VALID_CONFIDENCE:
            errors.append(f"Node {n['id']}: invalid confidence level")
    return errors

def validate_routes(routes, all_ids, node_ids):
    errors = []
    ids = [r['id'] for r in routes]
    if len(ids) != len(set(ids)):
        errors.append("Duplicate route IDs found")

    for r in routes:
        if r.get('from') not in node_ids:
            errors.append(f"Route {r['id']}: invalid from node '{r.get('from')}'")
        if r.get('to') not in node_ids:
            errors.append(f"Route {r['id']}: invalid to node '{r.get('to')}'")
        if r.get('type') not in VALID_ROUTE_TYPES:
            errors.append(f"Route {r['id']}: invalid type '{r.get('type')}'")
        if r.get('mode') not in VALID_ROUTE_MODES:
            errors.append(f"Route {r['id']}: invalid mode '{r.get('mode')}'")
        if r.get('status') not in VALID_ROUTE_STATUS:
            errors.append(f"Route {r['id']}: invalid status '{r.get('status')}'")
        if not (0 <= r.get('danger_level', -1) <= 5):
            errors.append(f"Route {r['id']}: danger_level must be 0-5")
        if r.get('confidence') not in VALID_CONFIDENCE:
            errors.append(f"Route {r['id']}: invalid confidence level")
    return errors

def validate_hazards(hazards, all_ids, continent_ids):
    errors = []
    ids = [h['id'] for h in hazards]
    if len(ids) != len(set(ids)):
        errors.append("Duplicate hazard IDs found")

    for h in hazards:
        if h.get('continent_id') not in continent_ids:
            errors.append(f"Hazard {h['id']}: invalid continent_id '{h.get('continent_id')}'")
        if h.get('type') not in VALID_HAZARD_TYPES:
            errors.append(f"Hazard {h['id']}: invalid type '{h.get('type')}'")
        if not (0 <= h.get('severity', -1) <= 5):
            errors.append(f"Hazard {h['id']}: severity must be 0-5")
        if h.get('confidence') not in VALID_CONFIDENCE:
            errors.append(f"Hazard {h['id']}: invalid confidence level")
    return errors


def validate_pixel_mapping(pixel_mapping, node_ids, continent_ids, hazard_ids):
    """Validate image-space coordinates and one-to-one canonical ID coverage."""
    errors = []
    if not isinstance(pixel_mapping, dict):
        return ["root must be an object"]

    width = pixel_mapping.get("image_width")
    height = pixel_mapping.get("image_height")
    if not isinstance(width, (int, float)) or isinstance(width, bool) or width <= 0:
        errors.append("image_width must be a positive number")
    if not isinstance(height, (int, float)) or isinstance(height, bool) or height <= 0:
        errors.append("image_height must be a positive number")

    expected_groups = {
        "nodes": set(node_ids),
        "continents": set(continent_ids),
        "hazards": set(hazard_ids),
    }
    for group_name, expected_ids in expected_groups.items():
        coordinates = pixel_mapping.get(group_name)
        if not isinstance(coordinates, dict):
            errors.append(f"{group_name} must be an object")
            continue

        actual_ids = set(coordinates)
        for missing_id in sorted(expected_ids - actual_ids):
            errors.append(f"{group_name}: missing canonical ID '{missing_id}'")
        for unknown_id in sorted(actual_ids - expected_ids):
            errors.append(f"{group_name}: unknown ID '{unknown_id}'")

        for item_id, coordinate in coordinates.items():
            if not isinstance(coordinate, dict):
                errors.append(f"{group_name}.{item_id}: coordinate must be an object")
                continue
            x = coordinate.get("x")
            y = coordinate.get("y")
            if not isinstance(x, (int, float)) or isinstance(x, bool):
                errors.append(f"{group_name}.{item_id}: x must be a number")
            elif isinstance(width, (int, float)) and not isinstance(width, bool) and not 0 <= x <= width:
                errors.append(f"{group_name}.{item_id}: x outside image bounds")
            if not isinstance(y, (int, float)) or isinstance(y, bool):
                errors.append(f"{group_name}.{item_id}: y must be a number")
            elif isinstance(height, (int, float)) and not isinstance(height, bool) and not 0 <= y <= height:
                errors.append(f"{group_name}.{item_id}: y outside image bounds")

    radius_scale = pixel_mapping.get("hazard_radius_scale")
    if (
        not isinstance(radius_scale, (int, float))
        or isinstance(radius_scale, bool)
        or radius_scale <= 0
    ):
        errors.append("hazard_radius_scale must be a positive number")

    allowed_keys = {
        "image_width", "image_height", "nodes", "continents", "hazards", "hazard_radius_scale"
    }
    for extra_key in sorted(set(pixel_mapping) - allowed_keys):
        errors.append(f"unexpected property '{extra_key}'")
    return errors

def main():
    print("Map Data Validation")
    print("=" * 50)

    all_ids = set()
    continent_ids = set()
    region_ids = set()
    node_ids = set()
    all_errors = []

    # Continents
    continents = load_json(DATA_DIR / "continents.json")
    continent_ids = collect_ids(continents)
    all_ids.update(continent_ids)
    schema_errors = validate_json_schema(
        continents, "continent.schema.json", collection=True
    )
    all_errors.extend([(f"continents.json: {e}", "continent-schema") for e in schema_errors])
    errors = [] if schema_errors else validate_continents(continents, all_ids)
    all_errors.extend([(f"continents.json: {e}", "continent") for e in errors])
    print(f"Continents: {data_count(continents)}")

    # Regions
    regions = load_json(DATA_DIR / "regions.json")
    region_ids = collect_ids(regions)
    all_ids.update(region_ids)
    schema_errors = validate_json_schema(regions, "region.schema.json", collection=True)
    all_errors.extend([(f"regions.json: {e}", "region-schema") for e in schema_errors])
    errors = [] if schema_errors else validate_regions(regions, all_ids, continent_ids)
    all_errors.extend([(f"regions.json: {e}", "region") for e in errors])
    print(f"Regions: {data_count(regions)}")

    # Nodes
    nodes = load_json(DATA_DIR / "nodes.json")
    node_ids = collect_ids(nodes)
    all_ids.update(node_ids)
    schema_errors = validate_json_schema(nodes, "node.schema.json", collection=True)
    all_errors.extend([(f"nodes.json: {e}", "node-schema") for e in schema_errors])
    errors = [] if schema_errors else validate_nodes(nodes, all_ids, continent_ids, region_ids)
    all_errors.extend([(f"nodes.json: {e}", "node") for e in errors])
    print(f"Nodes: {data_count(nodes)}")

    # Routes
    routes = load_json(DATA_DIR / "routes.json")
    schema_errors = validate_json_schema(routes, "route.schema.json", collection=True)
    all_errors.extend([(f"routes.json: {e}", "route-schema") for e in schema_errors])
    errors = [] if schema_errors else validate_routes(routes, all_ids, node_ids)
    all_errors.extend([(f"routes.json: {e}", "route") for e in errors])
    print(f"Routes: {data_count(routes)}")

    # Hazards
    hazards = load_json(DATA_DIR / "hazards.json")
    hazard_ids = collect_ids(hazards)
    schema_errors = validate_json_schema(hazards, "hazard.schema.json", collection=True)
    all_errors.extend([(f"hazards.json: {e}", "hazard-schema") for e in schema_errors])
    errors = [] if schema_errors else validate_hazards(hazards, all_ids, continent_ids)
    all_errors.extend([(f"hazards.json: {e}", "hazard") for e in errors])
    print(f"Hazards: {data_count(hazards)}")

    # Pixel mapping for the published high-resolution world map
    pixel_mapping = load_json(DATA_DIR / "pixel-mapping.json")
    schema_errors = validate_json_schema(
        pixel_mapping, "pixel-mapping.schema.json", collection=False
    )
    all_errors.extend(
        [(f"pixel-mapping.json: {e}", "pixel-mapping-schema") for e in schema_errors]
    )
    errors = [] if schema_errors else validate_pixel_mapping(
        pixel_mapping, node_ids, continent_ids, hazard_ids
    )
    all_errors.extend([(f"pixel-mapping.json: {e}", "pixel-mapping") for e in errors])
    mapping_nodes = pixel_mapping.get("nodes", {}) if isinstance(pixel_mapping, dict) else {}
    print(f"Pixel mappings: {data_count(mapping_nodes)} nodes")

    print("=" * 50)
    if all_errors:
        print(f"VALIDATION FAILED with {len(all_errors)} error(s):")
        for err, cat in all_errors:
            print(f"  [{cat}] {err}")
        sys.exit(1)
    else:
        print("Map data validation passed.")
        print(f"  Continents: {len(continents)}")
        print(f"  Regions: {len(regions)}")
        print(f"  Nodes: {len(nodes)}")
        print(f"  Routes: {len(routes)}")
        print(f"  Hazards: {len(hazards)}")
        sys.exit(0)

if __name__ == "__main__":
    main()
