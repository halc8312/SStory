#!/usr/bin/env python3
"""
Map Data Validator

Validates the structured map data files for consistency and correctness.
Checks: unique IDs, valid references, schema compliance, value ranges.
"""

import json
import os
import sys
from pathlib import Path

# Constants
DATA_DIR = Path("world/map-data/data")
SCHEMA_DIR = Path("world/map-data/schemas")

# Value sets
VALID_ROUTE_TYPES = {"road", "rail", "sea", "air", "caravan", "submarine", "tunnel", "underwater_tunnel", "ice_road", "warp", "forbidden_path"}
VALID_ROUTE_MODES = {"stagecoach", "express_carriage", "magic_train", "wind_magic_ship", "sailing_ship", "airship", "griffin", "caravan", "sand_vehicle", "submarine", "tidal_train", "walking", "spirit_warp", "chrono_tunnel"}
VALID_ROUTE_STATUS = {"active", "seasonal", "restricted", "forbidden", "experimental", "dangerous", "closed"}
VALID_NODE_TYPES = {"capital", "city", "town", "port", "airport", "air_terminal", "carriage_terminal", "inn", "checkpoint", "oasis", "caravan_lodge", "floating_island", "underwater_city", "submarine_terminal", "warp_gate", "forbidden_gate", "landmark", "ruin"}
VALID_HAZARD_TYPES = {"sandstorm", "pirate_sea", "ice_sea", "time_distortion", "forbidden_zone", "monster_sea", "volcanic_zone", "avalanche", "spirit_anomaly", "fog", "storm"}
VALID_CONFIDENCE = {"canon", "estimated", "inferred", "placeholder"}

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

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
    continent_ids = {c['id'] for c in continents}
    all_ids.update(continent_ids)
    errors = validate_continents(continents, all_ids)
    all_errors.extend([(f"continents.json: {e}", "continent") for e in errors])
    print(f"Continents: {len(continents)}")

    # Regions
    regions = load_json(DATA_DIR / "regions.json")
    region_ids = {r['id'] for r in regions}
    all_ids.update(region_ids)
    errors = validate_regions(regions, all_ids, continent_ids)
    all_errors.extend([(f"regions.json: {e}", "region") for e in errors])
    print(f"Regions: {len(regions)}")

    # Nodes
    nodes = load_json(DATA_DIR / "nodes.json")
    node_ids = {n['id'] for n in nodes}
    all_ids.update(node_ids)
    errors = validate_nodes(nodes, all_ids, continent_ids, region_ids)
    all_errors.extend([(f"nodes.json: {e}", "node") for e in errors])
    print(f"Nodes: {len(nodes)}")

    # Routes
    routes = load_json(DATA_DIR / "routes.json")
    errors = validate_routes(routes, all_ids, node_ids)
    all_errors.extend([(f"routes.json: {e}", "route") for e in errors])
    print(f"Routes: {len(routes)}")

    # Hazards
    hazards = load_json(DATA_DIR / "hazards.json")
    errors = validate_hazards(hazards, all_ids, continent_ids)
    all_errors.extend([(f"hazards.json: {e}", "hazard") for e in errors])
    print(f"Hazards: {len(hazards)}")

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
