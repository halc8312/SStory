#!/usr/bin/env python3
"""Validate the non-GeoJSON EA-WORLD-1 map-production source catalogs."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from production_common import ID_PATTERN, REPO_ROOT, ValidationFailure, load_json


COORDINATE_REFERENCE_SYSTEM = "EA-WORLD-1"
WORLD_MIN = 0
WORLD_MAX = 10000

DEFAULT_SOURCE_DIR = REPO_ROOT / "world" / "map-production" / "source"
DEFAULT_DATA_DIR = REPO_ROOT / "world" / "map-data" / "data"

CANONICAL_FILES = {
    "continent": "continents.json",
    "region": "regions.json",
    "node": "nodes.json",
    "poi": "pois.json",
}

SHEET_TYPES = frozenset(
    {"world", "continent", "region", "corridor", "settlement", "district", "block"}
)


def is_number(value: Any) -> bool:
    """Return whether value is a finite JSON number (excluding bool)."""

    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def validate_identifier(value: Any, label: str) -> list[str]:
    if not isinstance(value, str) or not value:
        return [f"{label} must be a non-empty string"]
    if not ID_PATTERN.fullmatch(value):
        return [f"{label} must be a stable lowercase kebab/snake-case ID: {value!r}"]
    return []


def validate_ea_position(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or len(value) != 2:
        return [f"{label} must be an [x, y] array"]
    errors: list[str] = []
    for index, coordinate in enumerate(value):
        if not is_number(coordinate):
            errors.append(f"{label}[{index}] must be a finite number")
    if errors:
        return errors
    x, y = value
    if not (WORLD_MIN <= x <= WORLD_MAX and WORLD_MIN <= y <= WORLD_MAX):
        errors.append(f"{label} is outside EA-WORLD-1 bounds 0..10000")
    return errors


def validate_bounds(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or len(value) != 4:
        return [f"{label} must be [min_x, min_y, max_x, max_y]"]
    errors: list[str] = []
    for index, coordinate in enumerate(value):
        if not is_number(coordinate):
            errors.append(f"{label}[{index}] must be a finite number")
    if errors:
        return errors
    min_x, min_y, max_x, max_y = value
    if not all(WORLD_MIN <= coordinate <= WORLD_MAX for coordinate in value):
        errors.append(f"{label} is outside EA-WORLD-1 bounds 0..10000")
    if min_x >= max_x or min_y >= max_y:
        errors.append(f"{label} must have min_x < max_x and min_y < max_y")
    return errors


def validate_common_document(value: Any, label: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label}: top-level value must be an object"]
    errors: list[str] = []
    if not isinstance(value.get("schema_version"), str) or not value["schema_version"]:
        errors.append(f"{label}: schema_version must be a non-empty string")
    if value.get("coordinate_reference_system") != COORDINATE_REFERENCE_SYSTEM:
        errors.append(
            f"{label}: coordinate_reference_system must be {COORDINATE_REFERENCE_SYSTEM!r}"
        )
    if not isinstance(value.get("status"), str) or not value["status"]:
        errors.append(f"{label}: status must be a non-empty string")
    source_refs = value.get("source_refs")
    if not isinstance(source_refs, list) or not all(
        isinstance(reference, str) and reference for reference in source_refs
    ):
        errors.append(f"{label}: source_refs must be an array of non-empty strings")
    return errors


def load_canonical_data(
    data_dir: Path,
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, list[tuple[str, dict[str, Any]]]], list[str]]:
    """Load the four data catalogs indexed by qualified and unqualified IDs."""

    errors: list[str] = []
    qualified: dict[tuple[str, str], dict[str, Any]] = {}
    by_id: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)

    for kind, filename in CANONICAL_FILES.items():
        path = data_dir / filename
        try:
            value = load_json(path)
        except ValidationFailure as exc:
            errors.append(str(exc))
            continue
        if not isinstance(value, list):
            errors.append(f"{path}: top-level value must be an array")
            continue
        for index, record in enumerate(value):
            label = f"{path}: records[{index}]"
            if not isinstance(record, dict):
                errors.append(f"{label} must be an object")
                continue
            identifier = record.get("id")
            errors.extend(validate_identifier(identifier, f"{label}.id"))
            if not isinstance(identifier, str) or not identifier:
                continue
            key = (kind, identifier)
            if key in qualified:
                errors.append(f"{label}: duplicate canonical {kind} id {identifier!r}")
                continue
            qualified[key] = record
            by_id[identifier].append((kind, record))

    return qualified, dict(by_id), errors


def load_source_feature_ids(source_dir: Path) -> tuple[set[str], list[str]]:
    """Load IDs from Phase 1 GeoJSON solely to resolve map-sheet source references."""

    errors: list[str] = []
    source_ids: set[str] = set()
    id_locations: dict[str, str] = {}
    paths = sorted(source_dir.glob("*.geojson"))
    if not paths:
        errors.append(f"{source_dir}: no GeoJSON source files found")
        return source_ids, errors

    for path in paths:
        try:
            value = load_json(path)
        except ValidationFailure as exc:
            errors.append(str(exc))
            continue
        if not isinstance(value, dict) or value.get("type") != "FeatureCollection":
            errors.append(f"{path}: top-level value must be a GeoJSON FeatureCollection")
            continue
        features = value.get("features")
        if not isinstance(features, list):
            errors.append(f"{path}: features must be an array")
            continue
        for index, feature in enumerate(features):
            label = f"{path}: features[{index}]"
            if not isinstance(feature, dict):
                errors.append(f"{label} must be an object")
                continue
            properties = feature.get("properties")
            property_id = properties.get("id") if isinstance(properties, dict) else None
            identifier = feature.get("id", property_id)
            if feature.get("id") is not None and property_id is not None:
                if feature["id"] != property_id:
                    errors.append(
                        f"{label}: feature.id {feature['id']!r} differs from properties.id {property_id!r}"
                    )
            errors.extend(validate_identifier(identifier, f"{label}.id"))
            if not isinstance(identifier, str) or not identifier:
                continue
            if identifier in id_locations:
                errors.append(
                    f"{label}: duplicate source feature id {identifier!r}; "
                    f"first seen at {id_locations[identifier]}"
                )
            else:
                source_ids.add(identifier)
                id_locations[identifier] = label

    return source_ids, errors


def validate_gazetteer(
    value: Any,
    canonical: dict[tuple[str, str], dict[str, Any]],
    *,
    label: str = "gazetteer.json",
) -> list[str]:
    errors = validate_common_document(value, label)
    if not isinstance(value, dict):
        return errors

    entries = value.get("entries")
    if not isinstance(entries, list):
        errors.append(f"{label}: entries must be an array")
        return errors

    entry_count = value.get("entry_count")
    if isinstance(entry_count, bool) or not isinstance(entry_count, int) or entry_count < 0:
        errors.append(f"{label}: entry_count must be a non-negative integer")
    elif entry_count != len(entries):
        errors.append(
            f"{label}: entry_count is {entry_count}, but entries contains {len(entries)} records"
        )

    seen_keys: dict[str, int] = {}
    seen_qualified: dict[tuple[str, str], int] = {}

    for index, entry in enumerate(entries):
        entry_label = f"{label}: entries[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{entry_label} must be an object")
            continue

        key = entry.get("key")
        kind = entry.get("kind")
        identifier = entry.get("id")
        name = entry.get("name")

        if not isinstance(key, str) or not key:
            errors.append(f"{entry_label}.key must be a non-empty string")
        elif key in seen_keys:
            errors.append(
                f"{entry_label}: duplicate gazetteer key {key!r}; "
                f"first seen at entries[{seen_keys[key]}]"
            )
        else:
            seen_keys[key] = index

        if kind not in CANONICAL_FILES:
            errors.append(
                f"{entry_label}.kind must be one of {', '.join(sorted(CANONICAL_FILES))}"
            )
        errors.extend(validate_identifier(identifier, f"{entry_label}.id"))
        if not isinstance(name, str) or not name:
            errors.append(f"{entry_label}.name must be a non-empty string")
        if not isinstance(entry.get("source_ref"), str) or not entry["source_ref"]:
            errors.append(f"{entry_label}.source_ref must be a non-empty string")

        qualified = (kind, identifier)
        if isinstance(kind, str) and isinstance(identifier, str):
            expected_key = f"{kind}:{identifier}"
            if key != expected_key:
                errors.append(f"{entry_label}.key must be {expected_key!r}")
            if qualified in seen_qualified:
                errors.append(
                    f"{entry_label}: duplicate gazetteer {kind} id {identifier!r}; "
                    f"first seen at entries[{seen_qualified[qualified]}]"
                )
            else:
                seen_qualified[qualified] = index

            canonical_record = canonical.get(qualified)
            if canonical_record is None:
                errors.append(
                    f"{entry_label}: {kind} id {identifier!r} is not present in canonical data"
                )
            elif name != canonical_record.get("name"):
                errors.append(
                    f"{entry_label}.name {name!r} differs from canonical name "
                    f"{canonical_record.get('name')!r}"
                )

        position = entry.get("map_position")
        if position is not None:
            errors.extend(validate_ea_position(position, f"{entry_label}.map_position"))
        elif kind != "poi":
            errors.append(f"{entry_label}.map_position may be null only for POIs")

        if "legacy_position" in entry:
            legacy_position = entry["legacy_position"]
            if not isinstance(legacy_position, list) or len(legacy_position) != 3 or not all(
                is_number(coordinate) for coordinate in legacy_position
            ):
                errors.append(f"{entry_label}.legacy_position must be a finite [x, y, z] array")

    present = set(seen_qualified)
    missing = sorted(set(canonical) - present)
    unexpected = sorted(present - set(canonical))
    for kind, identifier in missing:
        errors.append(f"{label}: missing canonical gazetteer entry {kind}:{identifier}")
    for kind, identifier in unexpected:
        errors.append(f"{label}: unexpected non-canonical gazetteer entry {kind}:{identifier}")

    return errors


def _sheet_parent_ids(sheet: dict[str, Any]) -> Iterable[str]:
    parent_id = sheet.get("parent_id")
    if isinstance(parent_id, str):
        yield parent_id
    secondary = sheet.get("secondary_parent_ids", [])
    if isinstance(secondary, list):
        yield from (identifier for identifier in secondary if isinstance(identifier, str))


def _cycle_errors(sheets: dict[str, dict[str, Any]], label: str) -> list[str]:
    errors: list[str] = []
    state: dict[str, int] = {}
    stack: list[str] = []
    reported: set[frozenset[str]] = set()

    def visit(identifier: str) -> None:
        state[identifier] = 1
        stack.append(identifier)
        for parent_id in _sheet_parent_ids(sheets[identifier]):
            if parent_id not in sheets:
                continue
            if state.get(parent_id, 0) == 0:
                visit(parent_id)
            elif state.get(parent_id) == 1:
                start = stack.index(parent_id)
                cycle = stack[start:] + [parent_id]
                cycle_key = frozenset(cycle)
                if cycle_key not in reported:
                    errors.append(f"{label}: sheet parent cycle detected: {' -> '.join(cycle)}")
                    reported.add(cycle_key)
        stack.pop()
        state[identifier] = 2

    for identifier in sheets:
        if state.get(identifier, 0) == 0:
            visit(identifier)
    return errors


def _usable_bounds(value: Any) -> tuple[float, float, float, float] | None:
    if not (
        isinstance(value, list)
        and len(value) == 4
        and all(is_number(coordinate) for coordinate in value)
    ):
        return None
    min_x, min_y, max_x, max_y = value
    if min_x >= max_x or min_y >= max_y:
        return None
    return min_x, min_y, max_x, max_y


def _bounds_contain_point(
    bounds: tuple[float, float, float, float], position: list[Any]
) -> bool:
    if not (
        isinstance(position, list)
        and len(position) == 2
        and all(is_number(coordinate) for coordinate in position)
    ):
        return False
    min_x, min_y, max_x, max_y = bounds
    x, y = position
    return min_x <= x <= max_x and min_y <= y <= max_y


def _bounds_contain_bounds(
    parent: tuple[float, float, float, float],
    child: tuple[float, float, float, float],
) -> bool:
    return (
        parent[0] <= child[0]
        and parent[1] <= child[1]
        and parent[2] >= child[2]
        and parent[3] >= child[3]
    )


def _geometry_bounds(geometry: Any) -> tuple[float, float, float, float] | None:
    """Return a finite 2D extent from a GeoJSON geometry coordinate tree."""

    if not isinstance(geometry, dict):
        return None
    coordinates = geometry.get("coordinates")
    points: list[tuple[float, float]] = []

    def visit(value: Any) -> None:
        if not isinstance(value, list):
            return
        if len(value) >= 2 and is_number(value[0]) and is_number(value[1]):
            points.append((value[0], value[1]))
            return
        for child in value:
            visit(child)

    visit(coordinates)
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def validate_map_sheet_coverage(
    map_sheets: Any,
    gazetteer: Any,
    settlement_footprints: Any,
    *,
    label: str = "map-sheets.json",
    gazetteer_label: str = "gazetteer.json",
    footprints_label: str = "settlement-footprints.geojson",
) -> list[str]:
    """Check production-sheet containment without treating work areas as borders."""

    errors: list[str] = []
    if not isinstance(map_sheets, dict) or not isinstance(map_sheets.get("sheets"), list):
        return [f"{label}: sheets must be an array before coverage can be checked"]
    if not isinstance(gazetteer, dict) or not isinstance(gazetteer.get("entries"), list):
        return [f"{gazetteer_label}: entries must be an array before coverage can be checked"]
    if not (
        isinstance(settlement_footprints, dict)
        and isinstance(settlement_footprints.get("features"), list)
    ):
        return [
            f"{footprints_label}: features must be an array before coverage can be checked"
        ]

    sheets = {
        sheet.get("id"): sheet
        for sheet in map_sheets["sheets"]
        if isinstance(sheet, dict) and isinstance(sheet.get("id"), str)
    }
    region_sheets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sheet in sheets.values():
        source_feature_id = sheet.get("source_feature_id")
        if sheet.get("sheet_type") == "region" and isinstance(source_feature_id, str):
            region_sheets[source_feature_id].append(sheet)

    region_ids: set[str] = set()
    for entry in gazetteer["entries"]:
        if isinstance(entry, dict) and entry.get("kind") == "node":
            region_id = entry.get("region_id")
            if isinstance(region_id, str):
                region_ids.add(region_id)
    for feature in settlement_footprints["features"]:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        region_id = properties.get("region_id") if isinstance(properties, dict) else None
        if isinstance(region_id, str):
            region_ids.add(region_id)

    usable_region_sheets: dict[str, dict[str, Any]] = {}
    for region_id in sorted(region_ids):
        candidates = region_sheets.get(region_id, [])
        if len(candidates) != 1:
            errors.append(
                f"{label}: region {region_id!r} must map to exactly one region sheet; "
                f"found {len(candidates)}"
            )
        else:
            usable_region_sheets[region_id] = candidates[0]

    for index, entry in enumerate(gazetteer["entries"]):
        if not isinstance(entry, dict) or entry.get("kind") != "node":
            continue
        region_id = entry.get("region_id")
        position = entry.get("map_position")
        if not isinstance(region_id, str) or validate_ea_position(
            position, f"{gazetteer_label}: entries[{index}].map_position"
        ):
            continue
        sheet = usable_region_sheets.get(region_id)
        if sheet is None:
            continue
        bounds = _usable_bounds(sheet.get("bounds"))
        if bounds is None:
            continue
        if not _bounds_contain_point(bounds, position):
            errors.append(
                f"{label}: region sheet {sheet.get('id')!r} bounds {list(bounds)} "
                f"do not contain gazetteer node {entry.get('id')!r} at {position}"
            )

    for index, feature in enumerate(settlement_footprints["features"]):
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            continue
        region_id = properties.get("region_id")
        if not isinstance(region_id, str):
            continue
        sheet = usable_region_sheets.get(region_id)
        if sheet is None:
            continue
        bounds = _usable_bounds(sheet.get("bounds"))
        footprint_bounds = _geometry_bounds(feature.get("geometry"))
        if bounds is None or footprint_bounds is None:
            continue
        if not _bounds_contain_bounds(bounds, footprint_bounds):
            feature_identifier = feature.get("id", properties.get("id"))
            errors.append(
                f"{label}: region sheet {sheet.get('id')!r} bounds {list(bounds)} "
                f"do not contain settlement footprint {feature_identifier!r} bounds "
                f"{list(footprint_bounds)} from {footprints_label}: features[{index}]"
            )

    for child in sheets.values():
        child_bounds = _usable_bounds(child.get("bounds"))
        if child_bounds is None:
            continue
        for parent_id in _sheet_parent_ids(child):
            parent = sheets.get(parent_id)
            if parent is None:
                continue
            parent_type = parent.get("sheet_type")
            child_type = child.get("sheet_type")
            checks_child = (
                (parent_type == "continent" and child_type == "region")
                or parent_type == "region"
            )
            if not checks_child:
                continue
            parent_bounds = _usable_bounds(parent.get("bounds"))
            if parent_bounds is None:
                continue
            if not _bounds_contain_bounds(parent_bounds, child_bounds):
                relationship = (
                    "child region sheet"
                    if parent_type == "continent" and child_type == "region"
                    else "child sheet"
                )
                errors.append(
                    f"{label}: {parent_type} sheet {parent_id!r} bounds "
                    f"{list(parent_bounds)} do not contain {relationship} "
                    f"{child.get('id')!r} bounds {list(child_bounds)}"
                )

    return errors


def validate_map_sheets(
    value: Any,
    source_feature_ids: set[str],
    *,
    label: str = "map-sheets.json",
) -> list[str]:
    errors = validate_common_document(value, label)
    if not isinstance(value, dict):
        return errors

    if value.get("bounds_order") != ["min_x", "min_y", "max_x", "max_y"]:
        errors.append(
            f"{label}: bounds_order must be ['min_x', 'min_y', 'max_x', 'max_y']"
        )
    if not isinstance(value.get("tile_profile"), dict):
        errors.append(f"{label}: tile_profile must be an object")

    sheets_value = value.get("sheets")
    if not isinstance(sheets_value, list) or not sheets_value:
        errors.append(f"{label}: sheets must be a non-empty array")
        return errors

    sheets: dict[str, dict[str, Any]] = {}
    locations: dict[str, int] = {}

    for index, sheet in enumerate(sheets_value):
        sheet_label = f"{label}: sheets[{index}]"
        if not isinstance(sheet, dict):
            errors.append(f"{sheet_label} must be an object")
            continue
        identifier = sheet.get("id")
        errors.extend(validate_identifier(identifier, f"{sheet_label}.id"))
        if isinstance(identifier, str) and identifier:
            if identifier in sheets:
                errors.append(
                    f"{sheet_label}: duplicate sheet id {identifier!r}; "
                    f"first seen at sheets[{locations[identifier]}]"
                )
            else:
                sheets[identifier] = sheet
                locations[identifier] = index

        if not isinstance(sheet.get("name"), str) or not sheet["name"]:
            errors.append(f"{sheet_label}.name must be a non-empty string")
        sheet_type = sheet.get("sheet_type")
        if sheet_type not in SHEET_TYPES:
            errors.append(f"{sheet_label}.sheet_type is unsupported: {sheet_type!r}")

        parent_id = sheet.get("parent_id")
        if parent_id is not None and not isinstance(parent_id, str):
            errors.append(f"{sheet_label}.parent_id must be a string or null")
        if sheet_type == "world" and parent_id is not None:
            errors.append(f"{sheet_label}: a world sheet cannot have a parent")
        if sheet_type != "world" and parent_id is None:
            errors.append(f"{sheet_label}: non-world sheets require parent_id")

        secondary = sheet.get("secondary_parent_ids", [])
        if not isinstance(secondary, list) or not all(
            isinstance(parent, str) and parent for parent in secondary
        ):
            errors.append(f"{sheet_label}.secondary_parent_ids must be an array of IDs")
        elif len(secondary) != len(set(secondary)):
            errors.append(f"{sheet_label}.secondary_parent_ids contains duplicates")

        source_feature_id = sheet.get("source_feature_id")
        if source_feature_id is not None and not isinstance(source_feature_id, str):
            errors.append(f"{sheet_label}.source_feature_id must be a string or null")
        elif isinstance(source_feature_id, str) and source_feature_id not in source_feature_ids:
            errors.append(
                f"{sheet_label}.source_feature_id references unknown source feature "
                f"{source_feature_id!r}"
            )

        bounds = sheet.get("bounds")
        if bounds is not None:
            errors.extend(validate_bounds(bounds, f"{sheet_label}.bounds"))
        elif not (
            sheet.get("review_status") == "planned"
            and sheet.get("geometry_confidence") == "unresolved"
        ):
            errors.append(
                f"{sheet_label}.bounds may be null only for planned, unresolved sheets"
            )

        zoom_range = sheet.get("zoom_range")
        if not (
            isinstance(zoom_range, list)
            and len(zoom_range) == 2
            and all(isinstance(zoom, int) and not isinstance(zoom, bool) for zoom in zoom_range)
            and 0 <= zoom_range[0] <= zoom_range[1]
        ):
            errors.append(f"{sheet_label}.zoom_range must be two ascending non-negative integers")
        native_zoom = sheet.get("native_zoom")
        if not isinstance(native_zoom, int) or isinstance(native_zoom, bool):
            errors.append(f"{sheet_label}.native_zoom must be an integer")
        elif (
            isinstance(zoom_range, list)
            and len(zoom_range) == 2
            and all(isinstance(zoom, int) and not isinstance(zoom, bool) for zoom in zoom_range)
            and not (zoom_range[0] <= native_zoom <= zoom_range[1])
        ):
            errors.append(f"{sheet_label}.native_zoom must be inside zoom_range")

        for field in ("review_status", "geometry_confidence"):
            if not isinstance(sheet.get(field), str) or not sheet[field]:
                errors.append(f"{sheet_label}.{field} must be a non-empty string")

    for identifier, sheet in sheets.items():
        for parent_id in _sheet_parent_ids(sheet):
            if parent_id == identifier:
                errors.append(f"{label}: sheet {identifier!r} cannot parent itself")
            elif parent_id not in sheets:
                errors.append(
                    f"{label}: sheet {identifier!r} references unknown parent {parent_id!r}"
                )

    errors.extend(_cycle_errors(sheets, label))
    return errors


def canonical_z(record: dict[str, Any]) -> Any:
    for container_name in ("position", "center"):
        container = record.get(container_name)
        if isinstance(container, dict) and "z" in container:
            return container["z"]
    return None


def validate_vertical_layers(
    value: Any,
    canonical_by_id: dict[str, list[tuple[str, dict[str, Any]]]],
    *,
    label: str = "vertical-layers.json",
) -> list[str]:
    errors = validate_common_document(value, label)
    if not isinstance(value, dict):
        return errors

    axis = value.get("axis")
    if not isinstance(axis, dict) or axis.get("name") != "z":
        errors.append(f"{label}: axis must be an object whose name is 'z'")
    if not isinstance(value.get("unbounded_policy"), dict):
        errors.append(f"{label}: unbounded_policy must be an object")

    layers_value = value.get("layers")
    if not isinstance(layers_value, list) or not layers_value:
        errors.append(f"{label}: layers must be a non-empty array")
        return errors

    layers: list[dict[str, Any]] = []
    layer_ids: dict[str, int] = {}
    render_orders: dict[int, int] = {}
    assigned: dict[str, tuple[int, str]] = {}

    for index, layer in enumerate(layers_value):
        layer_label = f"{label}: layers[{index}]"
        if not isinstance(layer, dict):
            errors.append(f"{layer_label} must be an object")
            continue
        layers.append(layer)
        identifier = layer.get("id")
        errors.extend(validate_identifier(identifier, f"{layer_label}.id"))
        if isinstance(identifier, str) and identifier:
            if identifier in layer_ids:
                errors.append(
                    f"{layer_label}: duplicate layer id {identifier!r}; "
                    f"first seen at layers[{layer_ids[identifier]}]"
                )
            else:
                layer_ids[identifier] = index
        if not isinstance(layer.get("name"), str) or not layer["name"]:
            errors.append(f"{layer_label}.name must be a non-empty string")

        z_min = layer.get("z_min_inclusive")
        z_max = layer.get("z_max_exclusive")
        if not is_number(z_min) or not is_number(z_max):
            errors.append(f"{layer_label}: z bounds must be finite numbers")
        elif z_min >= z_max:
            errors.append(f"{layer_label}: z_min_inclusive must be less than z_max_exclusive")

        render_order = layer.get("render_order")
        if not isinstance(render_order, int) or isinstance(render_order, bool):
            errors.append(f"{layer_label}.render_order must be an integer")
        elif render_order in render_orders:
            errors.append(
                f"{layer_label}: duplicate render_order {render_order}; "
                f"first seen at layers[{render_orders[render_order]}]"
            )
        else:
            render_orders[render_order] = index

        for field in ("review_status", "geometry_confidence"):
            if not isinstance(layer.get(field), str) or not layer[field]:
                errors.append(f"{layer_label}.{field} must be a non-empty string")

        feature_ids = layer.get("current_feature_ids")
        if not isinstance(feature_ids, list):
            errors.append(f"{layer_label}.current_feature_ids must be an array")
            continue
        for feature_index, feature_id in enumerate(feature_ids):
            feature_label = f"{layer_label}.current_feature_ids[{feature_index}]"
            errors.extend(validate_identifier(feature_id, feature_label))
            if not isinstance(feature_id, str) or not feature_id:
                continue
            if feature_id in assigned:
                first_index, first_layer = assigned[feature_id]
                errors.append(
                    f"{feature_label}: feature {feature_id!r} is already assigned to "
                    f"layer {first_layer!r} at layers[{first_index}]"
                )
            else:
                assigned[feature_id] = (index, str(identifier))

            records = canonical_by_id.get(feature_id, [])
            if not records:
                errors.append(f"{feature_label}: unknown canonical feature id {feature_id!r}")
                continue
            if len(records) > 1:
                kinds = ", ".join(sorted(kind for kind, _ in records))
                errors.append(
                    f"{feature_label}: ambiguous canonical feature id {feature_id!r} "
                    f"appears as {kinds}"
                )
                continue
            z = canonical_z(records[0][1])
            if not is_number(z):
                errors.append(f"{feature_label}: canonical feature has no finite z value")
            elif is_number(z_min) and is_number(z_max) and not (z_min <= z < z_max):
                errors.append(
                    f"{feature_label}: canonical z={z} is outside layer interval "
                    f"[{z_min}, {z_max})"
                )

    intervals = [
        layer
        for layer in layers
        if is_number(layer.get("z_min_inclusive")) and is_number(layer.get("z_max_exclusive"))
    ]
    intervals.sort(key=lambda layer: layer["z_min_inclusive"])
    for previous, current in zip(intervals, intervals[1:]):
        previous_max = previous["z_max_exclusive"]
        current_min = current["z_min_inclusive"]
        if current_min < previous_max:
            errors.append(
                f"{label}: vertical intervals overlap between {previous.get('id')!r} "
                f"and {current.get('id')!r}"
            )
        elif current_min > previous_max:
            errors.append(
                f"{label}: vertical interval gap between {previous.get('id')!r} "
                f"and {current.get('id')!r}"
            )
        previous_order = previous.get("render_order")
        current_order = current.get("render_order")
        if (
            isinstance(previous_order, int)
            and not isinstance(previous_order, bool)
            and isinstance(current_order, int)
            and not isinstance(current_order, bool)
            and current_order <= previous_order
        ):
            errors.append(
                f"{label}: render_order must increase with z from {previous.get('id')!r} "
                f"to {current.get('id')!r}"
            )

    return errors


def validate_source_catalog(
    source_dir: Path = DEFAULT_SOURCE_DIR,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> tuple[dict[str, int], list[str]]:
    errors: list[str] = []
    canonical, canonical_by_id, canonical_errors = load_canonical_data(data_dir)
    errors.extend(canonical_errors)
    source_feature_ids, source_errors = load_source_feature_ids(source_dir)
    errors.extend(source_errors)

    documents: dict[str, Any] = {}
    for filename in ("gazetteer.json", "map-sheets.json", "vertical-layers.json"):
        path = source_dir / filename
        try:
            documents[filename] = load_json(path)
        except ValidationFailure as exc:
            errors.append(str(exc))
    footprints_filename = "settlement-footprints.geojson"
    footprints_path = source_dir / footprints_filename
    try:
        documents[footprints_filename] = load_json(footprints_path)
    except ValidationFailure as exc:
        errors.append(str(exc))

    if "gazetteer.json" in documents:
        errors.extend(
            validate_gazetteer(
                documents["gazetteer.json"],
                canonical,
                label=str(source_dir / "gazetteer.json"),
            )
        )
    if "map-sheets.json" in documents:
        errors.extend(
            validate_map_sheets(
                documents["map-sheets.json"],
                source_feature_ids,
                label=str(source_dir / "map-sheets.json"),
            )
        )
    if all(
        filename in documents
        for filename in (
            "map-sheets.json",
            "gazetteer.json",
            footprints_filename,
        )
    ):
        errors.extend(
            validate_map_sheet_coverage(
                documents["map-sheets.json"],
                documents["gazetteer.json"],
                documents[footprints_filename],
                label=str(source_dir / "map-sheets.json"),
                gazetteer_label=str(source_dir / "gazetteer.json"),
                footprints_label=str(footprints_path),
            )
        )
    if "vertical-layers.json" in documents:
        errors.extend(
            validate_vertical_layers(
                documents["vertical-layers.json"],
                canonical_by_id,
                label=str(source_dir / "vertical-layers.json"),
            )
        )

    gazetteer = documents.get("gazetteer.json")
    sheets = documents.get("map-sheets.json")
    vertical = documents.get("vertical-layers.json")
    summary = {
        "canonical_records": len(canonical),
        "source_features": len(source_feature_ids),
        "gazetteer_entries": len(gazetteer.get("entries", [])) if isinstance(gazetteer, dict) else 0,
        "map_sheets": len(sheets.get("sheets", [])) if isinstance(sheets, dict) else 0,
        "vertical_layers": len(vertical.get("layers", [])) if isinstance(vertical, dict) else 0,
    }
    return summary, errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help=f"map-production source directory (default: {DEFAULT_SOURCE_DIR})",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"canonical map-data directory (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary, errors = validate_source_catalog(args.source_dir, args.data_dir)
    result = {"valid": not errors, **summary, "errors": errors}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif errors:
        print("Map-production source catalog validation failed.", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
    else:
        print("Map-production source catalog validation passed.")
        print(
            f"  Canonical records: {summary['canonical_records']}; "
            f"source features: {summary['source_features']}; "
            f"gazetteer entries: {summary['gazetteer_entries']}; "
            f"map sheets: {summary['map_sheets']}; "
            f"vertical layers: {summary['vertical_layers']}"
        )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
