#!/usr/bin/env python3
"""Validate POI JSON syntax, sync state, schema conformance, and references."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
WORLD_POIS_PATH = REPO_ROOT / "world" / "map-data" / "data" / "pois.json"
DOCS_POIS_PATH = REPO_ROOT / "docs" / "data" / "map" / "pois.json"
SCHEMA_PATH = REPO_ROOT / "world" / "map-data" / "schemas" / "poi.schema.json"
NODES_PATH = REPO_ROOT / "world" / "map-data" / "data" / "nodes.json"
REGIONS_PATH = REPO_ROOT / "world" / "map-data" / "data" / "regions.json"
CONTINENTS_PATH = REPO_ROOT / "world" / "map-data" / "data" / "continents.json"


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Required file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def find_duplicates(values: list[str]) -> list[str]:
    counter = Counter(values)
    return sorted(value for value, count in counter.items() if count > 1)


def main() -> int:
    errors: list[str] = []

    try:
        world_pois = load_json(WORLD_POIS_PATH)
        docs_pois = load_json(DOCS_POIS_PATH)
        schema = load_json(SCHEMA_PATH)
        nodes = load_json(NODES_PATH)
        regions = load_json(REGIONS_PATH)
        continents = load_json(CONTINENTS_PATH)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1

    if WORLD_POIS_PATH.read_bytes() != DOCS_POIS_PATH.read_bytes():
        errors.append(
            "world/map-data/data/pois.json and docs/data/map/pois.json differ. "
            "Run: python world/map-data/scripts/sync_pois_to_docs.py"
        )

    if not isinstance(world_pois, list):
        errors.append("world/map-data/data/pois.json must contain a top-level array.")
        world_pois = []

    if not isinstance(docs_pois, list):
        errors.append("docs/data/map/pois.json must contain a top-level array.")

    required_fields = schema.get("items", {}).get("required", [])
    node_ids = {node.get("id") for node in nodes if isinstance(node, dict)}
    region_ids = {region.get("id") for region in regions if isinstance(region, dict)}
    continent_ids = {
        continent.get("id") for continent in continents if isinstance(continent, dict)
    }

    poi_ids = [
        poi.get("id")
        for poi in world_pois
        if isinstance(poi, dict) and isinstance(poi.get("id"), str)
    ]
    duplicate_ids = find_duplicates(poi_ids)
    if duplicate_ids:
        errors.append(f"Duplicate POI IDs found: {', '.join(duplicate_ids)}")

    for index, poi in enumerate(world_pois, start=1):
        if not isinstance(poi, dict):
            errors.append(f"POI entry #{index} is not an object.")
            continue

        poi_id = poi.get("id", f"<index:{index}>")

        missing_fields = [field for field in required_fields if field not in poi]
        if missing_fields:
            errors.append(
                f"POI {poi_id}: missing required fields: {', '.join(missing_fields)}"
            )

        nearest_node_id = poi.get("nearest_node_id")
        if "nearest_node_id" in poi and nearest_node_id not in node_ids:
            errors.append(
                f"POI {poi_id}: nearest_node_id '{nearest_node_id}' does not exist."
            )

        continent_id = poi.get("continent_id")
        if "continent_id" in poi and continent_id not in continent_ids:
            errors.append(
                f"POI {poi_id}: continent_id '{continent_id}' does not exist."
            )

        region_id = poi.get("region_id")
        if "region_id" in poi and region_id not in region_ids:
            errors.append(f"POI {poi_id}: region_id '{region_id}' does not exist.")

    try:
        import jsonschema
    except ImportError:
        errors.append("jsonschema is not installed. Run: pip install jsonschema")
    else:
        validator = jsonschema.Draft7Validator(schema)
        schema_errors = sorted(validator.iter_errors(world_pois), key=lambda err: err.path)
        for schema_error in schema_errors:
            path_text = ".".join(str(part) for part in schema_error.path) or "<root>"
            errors.append(f"Schema validation error at {path_text}: {schema_error.message}")

    if errors:
        print("POI validation failed.")
        for error in errors:
            print(f"- {error}")
        return 1

    print("POI validation passed.")
    print(f"  POIs: {len(world_pois)}")
    print("  Sync: world/map-data/data/pois.json == docs/data/map/pois.json")
    print("  References: continent_id / region_id / nearest_node_id verified")
    print("  Schema: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
