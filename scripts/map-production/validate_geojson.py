#!/usr/bin/env python3
"""Validate production GeoJSON geometry, stable IDs, and canonical references."""

from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from production_common import ID_PATTERN, ValidationFailure, load_json


DEFAULT_REFERENCE_PROPERTIES = frozenset(
    {
        "continent_id",
        "region_id",
        "parent_id",
        "nearest_node_id",
        "node_id",
        "node_ids",
        "from_node_id",
        "to_node_id",
        "from_id",
        "to_id",
        "hazard_id",
        "poi_id",
        "route_id",
        "settlement_id",
        "landmass_id",
        "sheet_id",
        "vertical_layer_id",
    }
)


def expand_paths(raw_paths: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for raw in raw_paths:
        candidate = Path(raw)
        if candidate.is_dir():
            paths.extend(sorted(candidate.rglob("*.geojson")))
        elif any(character in raw for character in "*?["):
            paths.extend(Path(match) for match in sorted(glob.glob(raw, recursive=True)))
        else:
            paths.append(candidate)
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def feature_id(feature: dict[str, Any]) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    top_level = feature.get("id")
    properties = feature.get("properties")
    property_id = properties.get("id") if isinstance(properties, dict) else None
    if top_level is not None and property_id is not None and top_level != property_id:
        errors.append(f"feature.id {top_level!r} differs from properties.id {property_id!r}")
    value = top_level if top_level is not None else property_id
    if not isinstance(value, str) or not value:
        errors.append("feature requires a non-empty string id or properties.id")
        return None, errors
    if not ID_PATTERN.fullmatch(value):
        errors.append(f"feature id is not stable lowercase kebab/snake case: {value!r}")
    return value, errors


def coordinate_mode(collection: dict[str, Any], requested: str) -> str:
    if requested != "auto":
        return requested
    declared = collection.get("coordinate_reference_system")
    legacy_declared = collection.get("coordinate_system")
    if declared is not None and legacy_declared is not None:
        if str(declared).casefold() != str(legacy_declared).casefold():
            raise ValidationFailure(
                "coordinate_reference_system and coordinate_system disagree: "
                f"{declared!r} != {legacy_declared!r}"
            )
    if declared is None:
        declared = legacy_declared
    metadata = collection.get("metadata")
    if declared is None and isinstance(metadata, dict):
        declared = metadata.get("coordinate_reference_system", metadata.get("coordinate_system"))
    normalized = str(declared or "geographic").casefold()
    if normalized in {"epsg:4326", "crs84", "wgs84", "eternia-geographic", "geographic"}:
        return "geographic"
    if normalized in {"ea-world-1", "eternia-world", "world", "world-10000"}:
        return "world"
    if normalized in {"pixel", "pixels", "image"}:
        return "pixel"
    if normalized in {"unbounded", "cartesian"}:
        return "unbounded"
    raise ValidationFailure(f"Unknown coordinate_system declaration: {declared!r}")


def validate_position(position: Any, label: str, mode: str) -> list[str]:
    if not isinstance(position, list) or len(position) < 2:
        return [f"{label} must be a coordinate array with at least two values"]
    if len(position) > 3:
        return [f"{label} has {len(position)} dimensions; only 2D/3D coordinates are supported"]
    errors: list[str] = []
    for index, value in enumerate(position):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            errors.append(f"{label}[{index}] must be a finite number")
    if errors:
        return errors
    x, y = position[0], position[1]
    if mode == "geographic" and not (-180 <= x <= 180 and -90 <= y <= 90):
        errors.append(f"{label} longitude/latitude is outside [-180,180]/[-90,90]")
    elif mode == "world" and not (0 <= x <= 10000 and 0 <= y <= 10000):
        errors.append(f"{label} is outside the Eternia world range 0..10000")
    elif mode == "pixel" and (x < 0 or y < 0):
        errors.append(f"{label} pixel coordinates must be non-negative")
    return errors


def _same_position(left: list[Any], right: list[Any]) -> bool:
    return left[:2] == right[:2]


def _distinct_positions(positions: list[Any]) -> int:
    return len(
        {
            (position[0], position[1])
            for position in positions
            if isinstance(position, list)
            and len(position) >= 2
            and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in position[:2])
        }
    )


def validate_line(coordinates: Any, label: str, mode: str) -> list[str]:
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return [f"{label} must contain at least two positions"]
    errors = [
        error
        for index, position in enumerate(coordinates)
        for error in validate_position(position, f"{label}[{index}]", mode)
    ]
    if _distinct_positions(coordinates) < 2:
        errors.append(f"{label} must contain at least two distinct positions")
    return errors


def validate_ring(coordinates: Any, label: str, mode: str) -> list[str]:
    if not isinstance(coordinates, list) or len(coordinates) < 4:
        return [f"{label} must contain at least four positions"]
    errors = [
        error
        for index, position in enumerate(coordinates)
        for error in validate_position(position, f"{label}[{index}]", mode)
    ]
    if not all(isinstance(position, list) and len(position) >= 2 for position in coordinates):
        return errors
    if not _same_position(coordinates[0], coordinates[-1]):
        errors.append(f"{label} is not closed (first and last positions differ)")
    if _distinct_positions(coordinates[:-1]) < 3:
        errors.append(f"{label} must contain at least three distinct vertices")
    if not errors:
        area_twice = sum(
            left[0] * right[1] - right[0] * left[1]
            for left, right in zip(coordinates, coordinates[1:])
        )
        if math.isclose(area_twice, 0.0, abs_tol=1e-12):
            errors.append(f"{label} has zero area")
    return errors


def validate_geometry(geometry: Any, label: str, mode: str) -> list[str]:
    if not isinstance(geometry, dict):
        return [f"{label} must be a geometry object, not null"]
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Point":
        return validate_position(coordinates, f"{label}.coordinates", mode)
    if geometry_type == "MultiPoint":
        if not isinstance(coordinates, list) or not coordinates:
            return [f"{label}.coordinates must contain at least one position"]
        return [
            error
            for index, position in enumerate(coordinates)
            for error in validate_position(position, f"{label}.coordinates[{index}]", mode)
        ]
    if geometry_type == "LineString":
        return validate_line(coordinates, f"{label}.coordinates", mode)
    if geometry_type == "MultiLineString":
        if not isinstance(coordinates, list) or not coordinates:
            return [f"{label}.coordinates must contain at least one line"]
        return [
            error
            for index, line in enumerate(coordinates)
            for error in validate_line(line, f"{label}.coordinates[{index}]", mode)
        ]
    if geometry_type == "Polygon":
        if not isinstance(coordinates, list) or not coordinates:
            return [f"{label}.coordinates must contain at least one ring"]
        return [
            error
            for index, ring in enumerate(coordinates)
            for error in validate_ring(ring, f"{label}.coordinates[{index}]", mode)
        ]
    if geometry_type == "MultiPolygon":
        if not isinstance(coordinates, list) or not coordinates:
            return [f"{label}.coordinates must contain at least one polygon"]
        errors: list[str] = []
        for polygon_index, polygon in enumerate(coordinates):
            if not isinstance(polygon, list) or not polygon:
                errors.append(f"{label}.coordinates[{polygon_index}] must contain at least one ring")
                continue
            for ring_index, ring in enumerate(polygon):
                errors.extend(
                    validate_ring(
                        ring,
                        f"{label}.coordinates[{polygon_index}][{ring_index}]",
                        mode,
                    )
                )
        return errors
    if geometry_type == "GeometryCollection":
        geometries = geometry.get("geometries")
        if not isinstance(geometries, list) or not geometries:
            return [f"{label}.geometries must contain at least one geometry"]
        return [
            error
            for index, child in enumerate(geometries)
            for error in validate_geometry(child, f"{label}.geometries[{index}]", mode)
        ]
    return [f"{label}.type is unsupported: {geometry_type!r}"]


def iter_catalog_records(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, list):
        yield from (item for item in value if isinstance(item, dict))
    elif isinstance(value, dict) and value.get("type") == "FeatureCollection":
        for feature in value.get("features", []):
            if isinstance(feature, dict):
                properties = feature.get("properties")
                record = dict(properties) if isinstance(properties, dict) else {}
                if "id" not in record and isinstance(feature.get("id"), str):
                    record["id"] = feature["id"]
                yield record
    elif isinstance(value, dict):
        # Canonical catalogs in this repository use domain-specific collection
        # names. Supporting the known names lets callers pass the source
        # gazetteer, map-sheet catalog, or vertical-layer catalog directly rather
        # than manufacturing a validator-only ``items`` wrapper.
        for collection_name in ("items", "entries", "sheets", "layers"):
            records = value.get(collection_name)
            if isinstance(records, list):
                yield from (item for item in records if isinstance(item, dict))
                break


def reference_values(properties: dict[str, Any], names: set[str]) -> Iterable[tuple[str, Any]]:
    for name in names:
        if name in properties:
            yield name, properties[name]
    explicit = properties.get("references")
    if isinstance(explicit, dict):
        yield from ((f"references.{name}", value) for name, value in explicit.items())


def validate_files(
    paths: list[Path],
    reference_paths: list[Path],
    *,
    requested_mode: str = "auto",
    reference_properties: set[str] | None = None,
) -> tuple[dict[str, int], list[str]]:
    errors: list[str] = []
    collections: list[tuple[Path, dict[str, Any], str]] = []
    all_ids: set[str] = set()
    id_locations: dict[str, str] = {}
    feature_count = 0

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
        try:
            mode = coordinate_mode(value, requested_mode)
        except ValidationFailure as exc:
            errors.append(f"{path}: {exc}")
            continue
        collections.append((path, value, mode))
        for index, feature in enumerate(features):
            feature_count += 1
            label = f"{path}: features[{index}]"
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                errors.append(f"{label} must be a GeoJSON Feature")
                continue
            identifier, id_errors = feature_id(feature)
            errors.extend(f"{label}: {error}" for error in id_errors)
            if identifier:
                if identifier in id_locations:
                    errors.append(
                        f"{label}: duplicate feature id {identifier!r}; first seen at {id_locations[identifier]}"
                    )
                else:
                    all_ids.add(identifier)
                    id_locations[identifier] = label

    for path in reference_paths:
        try:
            value = load_json(path)
        except ValidationFailure as exc:
            errors.append(str(exc))
            continue
        for record in iter_catalog_records(value):
            identifier = record.get("id")
            if isinstance(identifier, str):
                all_ids.add(identifier)

    names = set(DEFAULT_REFERENCE_PROPERTIES) if reference_properties is None else reference_properties
    geometry_count = 0
    for path, collection, mode in collections:
        for index, feature in enumerate(collection["features"]):
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                continue
            label = f"{path}: features[{index}]"
            geometry_count += 1
            errors.extend(validate_geometry(feature.get("geometry"), f"{label}.geometry", mode))
            properties = feature.get("properties")
            if not isinstance(properties, dict):
                errors.append(f"{label}.properties must be an object")
                continue
            for property_name, value in reference_values(properties, names):
                references = value if isinstance(value, list) else [value]
                if not references:
                    errors.append(f"{label}.properties.{property_name} cannot be empty")
                for reference in references:
                    if not isinstance(reference, str):
                        errors.append(f"{label}.properties.{property_name} references must be strings")
                    elif reference not in all_ids:
                        errors.append(
                            f"{label}.properties.{property_name} references unknown id {reference!r}"
                        )

    return {
        "files": len(collections),
        "features": feature_count,
        "geometries": geometry_count,
        "catalog_ids": len(all_ids),
    }, errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("geojson", nargs="+", help="GeoJSON files, directories, or glob patterns")
    parser.add_argument(
        "--reference-data",
        action="append",
        default=[],
        type=Path,
        help="canonical JSON/GeoJSON ID catalog (repeatable)",
    )
    parser.add_argument(
        "--coordinate-system",
        choices=("auto", "geographic", "world", "pixel", "unbounded"),
        default="auto",
    )
    parser.add_argument(
        "--reference-property",
        action="append",
        default=[],
        help="additional properties whose values must resolve to known IDs",
    )
    parser.add_argument(
        "--no-default-references",
        action="store_true",
        help="only validate properties named with --reference-property",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = expand_paths(args.geojson)
    if not paths:
        print("No GeoJSON inputs matched.", file=sys.stderr)
        return 2
    names = set(args.reference_property)
    if not args.no_default_references:
        names.update(DEFAULT_REFERENCE_PROPERTIES)
    summary, errors = validate_files(
        paths,
        args.reference_data,
        requested_mode=args.coordinate_system,
        reference_properties=names,
    )
    result = {"valid": not errors, **summary, "errors": errors}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif errors:
        print("GeoJSON validation failed.", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
    else:
        print("GeoJSON validation passed.")
        print(
            f"  Files: {summary['files']}; features: {summary['features']}; "
            f"geometries: {summary['geometries']}; catalog IDs: {summary['catalog_ids']}"
        )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
