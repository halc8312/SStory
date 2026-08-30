#!/usr/bin/env python3
"""Validate the finite deep-zoom resolution contract and project map sheets.

Normal validation treats the contract as the proposed Phase 5 production
profile and calculates every bounded sheet on that profile.  ``--check-catalog``
additionally requires the current catalog's tile/metatile profile and bounded
sheet ``zoom_range``/``native_zoom`` fields to match the contract.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Sequence

from production_common import REPO_ROOT, ValidationFailure, load_json


DEFAULT_CONTRACT = (
    REPO_ROOT / "world" / "map-production" / "spec" / "resolution-contract.json"
)
DEFAULT_MAP_SHEETS = (
    REPO_ROOT / "world" / "map-production" / "source" / "map-sheets.json"
)
SUPPORTED_SHEET_TYPES = ("world", "continent", "region", "corridor", "settlement")


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _fraction(value: int | float) -> Fraction:
    """Convert JSON numbers through their decimal spelling for stable rounding."""

    return Fraction(str(value))


def _required_object(
    owner: dict[str, Any], field: str, label: str, errors: list[str]
) -> dict[str, Any] | None:
    value = owner.get(field)
    if not isinstance(value, dict):
        errors.append(f"{label}.{field} must be an object")
        return None
    return value


def _required_integer(
    owner: dict[str, Any],
    field: str,
    label: str,
    errors: list[str],
    *,
    minimum: int | None = None,
) -> int | None:
    value = owner.get(field)
    if not _integer(value) or (minimum is not None and value < minimum):
        qualifier = f" at least {minimum}" if minimum is not None else ""
        errors.append(f"{label}.{field} must be an integer{qualifier}")
        return None
    return value


def validate_contract_structure(contract: Any) -> list[str]:
    """Validate fields needed to recalculate the global raster grid."""

    errors: list[str] = []
    if not isinstance(contract, dict):
        return ["resolution contract must contain a JSON object"]
    if contract.get("schema_version") != "1.0.0":
        errors.append("resolution contract schema_version must be '1.0.0'")
    if contract.get("type") != "sstory-finite-deep-zoom-resolution-contract":
        errors.append("resolution contract type is unsupported")
    if contract.get("coordinate_reference_system") != "EA-WORLD-1":
        errors.append("resolution contract coordinate_reference_system must be EA-WORLD-1")

    extent = _required_object(contract, "world_extent", "contract", errors)
    if extent is not None:
        values = [extent.get(field) for field in ("min_x", "min_y", "max_x", "max_y")]
        if not all(_finite_number(value) for value in values):
            errors.append("contract.world_extent must define four finite numbers")
        elif not (values[0] < values[2] and values[1] < values[3]):
            errors.append("contract.world_extent minimums must be less than maximums")

    world = _required_object(contract, "world_raster", "contract", errors)
    if world is not None:
        _required_integer(world, "width_px", "contract.world_raster", errors, minimum=1)
        _required_integer(world, "height_px", "contract.world_raster", errors, minimum=1)
        _required_integer(world, "native_zoom", "contract.world_raster", errors, minimum=0)

    order = contract.get("sheet_type_order")
    if order != list(SUPPORTED_SHEET_TYPES):
        errors.append(
            "contract.sheet_type_order must be " + ", ".join(SUPPORTED_SHEET_TYPES)
        )

    lod = _required_object(contract, "lod_by_sheet_type", "contract", errors)
    if lod is not None:
        if set(lod) != set(SUPPORTED_SHEET_TYPES):
            errors.append("contract.lod_by_sheet_type must define exactly the five bounded sheet types")
        previous_native: int | None = None
        previous_maximum: int | None = None
        for sheet_type in SUPPORTED_SHEET_TYPES:
            entry = lod.get(sheet_type)
            label = f"contract.lod_by_sheet_type.{sheet_type}"
            if not isinstance(entry, dict):
                errors.append(f"{label} must be an object")
                continue
            zoom_range = entry.get("zoom_range")
            native = entry.get("native_zoom")
            if not (
                isinstance(zoom_range, list)
                and len(zoom_range) == 2
                and all(_integer(value) and value >= 0 for value in zoom_range)
                and zoom_range[0] <= zoom_range[1]
            ):
                errors.append(f"{label}.zoom_range must contain two ascending non-negative integers")
                continue
            if not _integer(native) or not zoom_range[0] <= native <= zoom_range[1]:
                errors.append(f"{label}.native_zoom must be an integer inside zoom_range")
                continue
            if previous_native is not None and native <= previous_native:
                errors.append(
                    f"{label}.native_zoom must be greater than the preceding LOD native zoom"
                )
            if previous_maximum is not None and zoom_range[0] != previous_maximum:
                errors.append(
                    f"{label}.zoom_range must start at the preceding LOD maximum "
                    f"({previous_maximum})"
                )
            if not isinstance(entry.get("production_method"), str) or not entry["production_method"]:
                errors.append(f"{label}.production_method must be a non-empty string")
            previous_native = native
            previous_maximum = zoom_range[1]
        if world is not None and isinstance(lod.get("world"), dict):
            if lod["world"].get("native_zoom") != world.get("native_zoom"):
                errors.append(
                    "contract world LOD native_zoom must equal world_raster.native_zoom"
                )

    formula = _required_object(contract, "pixel_bounds_formula", "contract", errors)
    if formula is not None:
        expected_formula = {
            "coordinate_order": ["min_x", "min_y", "max_x", "max_y"],
            "scale_base": 2,
            "scale_exponent": "sheet_native_zoom-minus-world_native_zoom",
            "minimum_rounding": "floor",
            "maximum_rounding": "ceil",
            "x_base_pixels": "world_raster.width_px",
            "y_base_pixels": "world_raster.height_px",
            "x_denominator": "world_extent.max_x-minus-min_x",
            "y_denominator": "world_extent.max_y-minus-min_y",
        }
        for field, expected in expected_formula.items():
            if formula.get(field) != expected:
                errors.append(
                    f"contract.pixel_bounds_formula.{field} must be {expected!r}"
                )

    tiles = _required_object(contract, "tile_profile", "contract", errors)
    if tiles is not None:
        tile_size = _required_integer(
            tiles, "tile_size_px", "contract.tile_profile", errors, minimum=1
        )
        expected_tile_coordinates = {
            "scheme": "xyz",
            "coordinate_scope": "sheet-local",
            "tile_origin": "top-left",
            "y_axis": "down",
        }
        for field, expected in expected_tile_coordinates.items():
            if tiles.get(field) != expected:
                errors.append(
                    f"contract.tile_profile.{field} must be {expected!r}"
                )
        if tiles.get("public_format") != "webp":
            errors.append("contract.tile_profile.public_format must be 'webp'")
    else:
        tile_size = None

    metatiles = _required_object(contract, "metatile_profile", "contract", errors)
    if metatiles is not None:
        metatile_size = _required_integer(
            metatiles,
            "metatile_size_px",
            "contract.metatile_profile",
            errors,
            minimum=1,
        )
        gutter = _required_integer(
            metatiles,
            "gutter_each_side_px",
            "contract.metatile_profile",
            errors,
            minimum=0,
        )
        stride = _required_integer(
            metatiles, "stride_px", "contract.metatile_profile", errors, minimum=1
        )
        if None not in (metatile_size, gutter, stride):
            expected_stride = metatile_size - 2 * gutter
            if stride != expected_stride or expected_stride <= 0:
                errors.append(
                    "contract.metatile_profile.stride_px must equal "
                    "metatile_size_px - 2 * gutter_each_side_px"
                )
            if tile_size is not None and metatile_size % tile_size:
                errors.append(
                    "contract.metatile_profile.metatile_size_px must be divisible by tile_size_px"
                )
        applicable = metatiles.get("applicable_sheet_types")
        if applicable != ["region", "corridor", "settlement"]:
            errors.append(
                "contract.metatile_profile.applicable_sheet_types must be "
                "region, corridor, settlement"
            )

    unbounded = _required_object(contract, "unbounded_sheet_policy", "contract", errors)
    if unbounded is not None:
        if unbounded.get("action") != "skip":
            errors.append("contract.unbounded_sheet_policy.action must be 'skip'")
        if unbounded.get("allowed_sheet_types") != ["district", "block"]:
            errors.append(
                "contract.unbounded_sheet_policy.allowed_sheet_types must be district, block"
            )
        if unbounded.get("required_review_status") != "planned":
            errors.append(
                "contract.unbounded_sheet_policy.required_review_status must be 'planned'"
            )
        if unbounded.get("required_geometry_confidence") != "unresolved":
            errors.append(
                "contract.unbounded_sheet_policy.required_geometry_confidence must be 'unresolved'"
            )

    overzoom = _required_object(contract, "overzoom_policy", "contract", errors)
    if overzoom is not None:
        if overzoom.get("allowed") is not False:
            errors.append("contract.overzoom_policy.allowed must be false")
        if overzoom.get("maximum_source_scale") != 1:
            errors.append("contract.overzoom_policy.maximum_source_scale must be 1")
        if overzoom.get("behavior_outside_deeper_sheet") != (
            "clamp-to-deepest-intersecting-native-zoom"
        ):
            errors.append(
                "contract.overzoom_policy.behavior_outside_deeper_sheet is unsupported"
            )
        if overzoom.get("parent_visibility_until_child_ready") is not True:
            errors.append(
                "contract.overzoom_policy.parent_visibility_until_child_ready must be true"
            )

    summary = _required_object(contract, "expected_summary", "contract", errors)
    if summary is not None:
        for field in (
            "bounded_sheet_count",
            "unbounded_skipped_count",
            "total_master_pixels",
            "generation_master_pixels",
            "generation_metatile_count",
        ):
            _required_integer(summary, field, "contract.expected_summary", errors, minimum=0)
    return errors


def calculate_pixel_bounds(
    bounds: Sequence[int | float], sheet_native_zoom: int, contract: dict[str, Any]
) -> tuple[int, int, int, int]:
    """Map one EA-WORLD-1 extent to the exact global pixel grid."""

    extent = contract["world_extent"]
    world = contract["world_raster"]
    formula = contract["pixel_bounds_formula"]
    exponent = sheet_native_zoom - world["native_zoom"]
    base = formula["scale_base"]
    scale = Fraction(base**exponent, 1) if exponent >= 0 else Fraction(1, base ** -exponent)
    x_span = _fraction(extent["max_x"]) - _fraction(extent["min_x"])
    y_span = _fraction(extent["max_y"]) - _fraction(extent["min_y"])

    left_value = (
        (_fraction(bounds[0]) - _fraction(extent["min_x"]))
        / x_span
        * world["width_px"]
        * scale
    )
    right_value = (
        (_fraction(bounds[2]) - _fraction(extent["min_x"]))
        / x_span
        * world["width_px"]
        * scale
    )
    top_value = (
        (_fraction(bounds[1]) - _fraction(extent["min_y"]))
        / y_span
        * world["height_px"]
        * scale
    )
    bottom_value = (
        (_fraction(bounds[3]) - _fraction(extent["min_y"]))
        / y_span
        * world["height_px"]
        * scale
    )
    return (
        math.floor(left_value),
        math.floor(top_value),
        math.ceil(right_value),
        math.ceil(bottom_value),
    )


def metatile_axis_count(length: int, size: int, stride: int) -> int:
    """Return the minimum metatile count covering an axis with fixed overlap."""

    if length <= 0 or size <= 0 or stride <= 0:
        raise ValueError("length, size, and stride must be positive")
    if length <= size:
        return 1
    return 1 + math.ceil((length - size) / stride)


def _validate_catalog_bounds(
    value: Any, sheet_id: str, contract: dict[str, Any]
) -> tuple[tuple[int | float, int | float, int | float, int | float] | None, list[str]]:
    errors: list[str] = []
    if not (
        isinstance(value, list)
        and len(value) == 4
        and all(_finite_number(coordinate) for coordinate in value)
    ):
        return None, [f"sheet {sheet_id!r} bounds must contain four finite numbers"]
    min_x, min_y, max_x, max_y = value
    extent = contract["world_extent"]
    if not (
        extent["min_x"] <= min_x < max_x <= extent["max_x"]
        and extent["min_y"] <= min_y < max_y <= extent["max_y"]
    ):
        errors.append(f"sheet {sheet_id!r} bounds must stay inside world_extent")
        return None, errors
    return (min_x, min_y, max_x, max_y), errors


def _parent_ids(sheet: dict[str, Any]) -> Iterable[str]:
    parent = sheet.get("parent_id")
    if isinstance(parent, str):
        yield parent
    secondary = sheet.get("secondary_parent_ids")
    if isinstance(secondary, list):
        yield from (value for value in secondary if isinstance(value, str))


def validate_resolution_contract(
    contract_path: Path = DEFAULT_CONTRACT,
    map_sheets_path: Path = DEFAULT_MAP_SHEETS,
    *,
    check_catalog: bool = False,
) -> dict[str, Any]:
    """Validate the contract and return all derived sheet-resolution evidence."""

    errors: list[str] = []
    try:
        contract = load_json(contract_path)
    except ValidationFailure as exc:
        contract = None
        errors.append(str(exc))
    try:
        catalog = load_json(map_sheets_path)
    except ValidationFailure as exc:
        catalog = None
        errors.append(str(exc))

    result: dict[str, Any] = {
        "valid": False,
        "contract": str(contract_path),
        "map_sheets": str(map_sheets_path),
        "check_catalog": check_catalog,
        "bounded_sheet_count": 0,
        "unbounded_skipped_count": 0,
        "unbounded_skipped_sheet_ids": [],
        "total_master_pixels": 0,
        "total_master_megapixels": 0.0,
        "generation_master_pixels": 0,
        "generation_metatile_count": 0,
        "catalog_profile_mismatch_count": 0,
        "catalog_profile_mismatches": [],
        "catalog_zoom_mismatch_count": 0,
        "catalog_zoom_mismatches": [],
        "sheets": [],
        "errors": errors,
    }
    if contract is None or catalog is None:
        return result

    contract_errors = validate_contract_structure(contract)
    errors.extend(contract_errors)
    if contract_errors:
        return result
    if not isinstance(catalog, dict):
        errors.append("map-sheets catalog must contain a JSON object")
        return result
    if catalog.get("coordinate_reference_system") != contract["coordinate_reference_system"]:
        errors.append(
            "map-sheets coordinate_reference_system must match the resolution contract"
        )
    sheet_values = catalog.get("sheets")
    if not isinstance(sheet_values, list):
        errors.append("map-sheets catalog must contain a sheets array")
        return result

    contract_tile_profile = contract["tile_profile"]
    contract_metatile_profile = contract["metatile_profile"]
    expected_catalog_profile = {
        "tile_size_px": contract_tile_profile["tile_size_px"],
        "public_format": contract_tile_profile["public_format"],
        "metatile_size_px": contract_metatile_profile["metatile_size_px"],
        "metatile_gutter_each_side_px": contract_metatile_profile[
            "gutter_each_side_px"
        ],
    }
    catalog_profile = catalog.get("tile_profile")
    profile_mismatches: list[str] = []
    for field, expected in expected_catalog_profile.items():
        actual = catalog_profile.get(field) if isinstance(catalog_profile, dict) else None
        if actual != expected:
            profile_mismatches.append(
                f"map-sheets.tile_profile.{field} catalog profile mismatch: "
                f"catalog={actual!r}, contract={expected!r}"
            )
    if check_catalog:
        errors.extend(profile_mismatches)

    lod = contract["lod_by_sheet_type"]
    metatile = contract_metatile_profile
    applicable = set(metatile["applicable_sheet_types"])
    unbounded_policy = contract["unbounded_sheet_policy"]
    allowed_unbounded = set(unbounded_policy["allowed_sheet_types"])
    sheets_by_id: dict[str, dict[str, Any]] = {}
    derived_by_id: dict[str, dict[str, Any]] = {}
    skipped_ids: list[str] = []
    zoom_mismatches: list[str] = []
    total_pixels = 0
    generation_pixels = 0
    generation_metatiles = 0

    for index, sheet in enumerate(sheet_values):
        label = f"map-sheets.sheets[{index}]"
        if not isinstance(sheet, dict):
            errors.append(f"{label} must be an object")
            continue
        sheet_id = sheet.get("id")
        if not isinstance(sheet_id, str) or not sheet_id:
            errors.append(f"{label}.id must be a non-empty string")
            continue
        if sheet_id in sheets_by_id:
            errors.append(f"map-sheets contains duplicate sheet id {sheet_id!r}")
            continue
        sheets_by_id[sheet_id] = sheet
        sheet_type = sheet.get("sheet_type")
        bounds_value = sheet.get("bounds")

        if bounds_value is None:
            if sheet_type not in allowed_unbounded:
                errors.append(
                    f"unbounded sheet {sheet_id!r} type {sheet_type!r} is not allowed by the contract"
                )
            if sheet.get("review_status") != unbounded_policy["required_review_status"]:
                errors.append(
                    f"unbounded sheet {sheet_id!r} must have review_status "
                    f"{unbounded_policy['required_review_status']!r}"
                )
            if sheet.get("geometry_confidence") != unbounded_policy["required_geometry_confidence"]:
                errors.append(
                    f"unbounded sheet {sheet_id!r} must have geometry_confidence "
                    f"{unbounded_policy['required_geometry_confidence']!r}"
                )
            skipped_ids.append(sheet_id)
            continue

        if sheet_type not in lod:
            errors.append(
                f"bounded sheet {sheet_id!r} type {sheet_type!r} has no LOD contract"
            )
            continue
        bounds, bounds_errors = _validate_catalog_bounds(bounds_value, sheet_id, contract)
        errors.extend(bounds_errors)
        if bounds is None:
            continue

        expected_lod = lod[sheet_type]
        native_zoom = expected_lod["native_zoom"]
        pixel_bounds = calculate_pixel_bounds(bounds, native_zoom, contract)
        width = pixel_bounds[2] - pixel_bounds[0]
        height = pixel_bounds[3] - pixel_bounds[1]
        pixels = width * height
        record: dict[str, Any] = {
            "sheet_id": sheet_id,
            "sheet_type": sheet_type,
            "bounds": list(bounds),
            "zoom_range": list(expected_lod["zoom_range"]),
            "native_zoom": native_zoom,
            "pixel_bounds": list(pixel_bounds),
            "width": width,
            "height": height,
            "pixels": pixels,
            "production_method": expected_lod["production_method"],
            "metatiles": None,
        }
        if sheet_type in applicable:
            columns = metatile_axis_count(
                width, metatile["metatile_size_px"], metatile["stride_px"]
            )
            rows = metatile_axis_count(
                height, metatile["metatile_size_px"], metatile["stride_px"]
            )
            count = columns * rows
            record["metatiles"] = {
                "columns": columns,
                "rows": rows,
                "count": count,
                "size_px": metatile["metatile_size_px"],
                "gutter_each_side_px": metatile["gutter_each_side_px"],
                "stride_px": metatile["stride_px"],
            }
            generation_pixels += pixels
            generation_metatiles += count

        total_pixels += pixels
        derived_by_id[sheet_id] = record

        actual_zoom = sheet.get("zoom_range")
        actual_native = sheet.get("native_zoom")
        if actual_zoom != expected_lod["zoom_range"] or actual_native != native_zoom:
            zoom_mismatches.append(
                f"sheet {sheet_id!r} catalog zoom mismatch: "
                f"zoom_range={actual_zoom!r}, native_zoom={actual_native!r}; "
                f"contract expects zoom_range={expected_lod['zoom_range']!r}, "
                f"native_zoom={native_zoom!r}"
            )

    for sheet_id, record in derived_by_id.items():
        sheet = sheets_by_id[sheet_id]
        child_native = record["native_zoom"]
        for parent_id in _parent_ids(sheet):
            parent_record = derived_by_id.get(parent_id)
            if parent_record is None:
                errors.append(
                    f"bounded sheet {sheet_id!r} references a missing or unbounded parent "
                    f"{parent_id!r}"
                )
            elif child_native <= parent_record["native_zoom"]:
                errors.append(
                    f"sheet LOD is not monotonic: {sheet_id!r} native z{child_native} must "
                    f"be greater than parent {parent_id!r} native z{parent_record['native_zoom']}"
                )

    expected_summary = contract["expected_summary"]
    actual_summary = {
        "bounded_sheet_count": len(derived_by_id),
        "unbounded_skipped_count": len(skipped_ids),
        "total_master_pixels": total_pixels,
        "generation_master_pixels": generation_pixels,
        "generation_metatile_count": generation_metatiles,
    }
    for field, actual in actual_summary.items():
        expected = expected_summary[field]
        if actual != expected:
            errors.append(
                f"contract.expected_summary.{field} mismatch: expected={expected}, actual={actual}"
            )

    if check_catalog:
        errors.extend(zoom_mismatches)

    records = [
        derived_by_id[sheet["id"]]
        for sheet in sheet_values
        if isinstance(sheet, dict) and sheet.get("id") in derived_by_id
    ]
    result.update(
        {
            "bounded_sheet_count": len(records),
            "unbounded_skipped_count": len(skipped_ids),
            "unbounded_skipped_sheet_ids": skipped_ids,
            "total_master_pixels": total_pixels,
            "total_master_megapixels": round(total_pixels / 1_000_000, 1),
            "generation_master_pixels": generation_pixels,
            "generation_metatile_count": generation_metatiles,
            "catalog_profile_mismatch_count": len(profile_mismatches),
            "catalog_profile_mismatches": profile_mismatches,
            "catalog_zoom_mismatch_count": len(zoom_mismatches),
            "catalog_zoom_mismatches": zoom_mismatches,
            "sheets": records,
            "valid": not errors,
        }
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--map-sheets", type=Path, default=DEFAULT_MAP_SHEETS)
    parser.add_argument(
        "--check-catalog",
        action="store_true",
        help=(
            "also require the map-sheets tile/metatile profile and bounded "
            "zoom_range/native_zoom values to match the contract"
        ),
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_resolution_contract(
        args.contract,
        args.map_sheets,
        check_catalog=args.check_catalog,
    )
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["valid"]:
        print(f"Resolution contract validation passed: {args.contract}")
        print(
            f"  Bounded sheets={result['bounded_sheet_count']}; "
            f"unbounded skipped={result['unbounded_skipped_count']}"
        )
        print(
            f"  Master pixels={result['total_master_pixels']:,} "
            f"({result['total_master_megapixels']:.1f} MP); "
            f"ImageGen metatiles={result['generation_metatile_count']}"
        )
        for sheet in result["sheets"]:
            metatiles = sheet["metatiles"]
            metatile_text = (
                "-"
                if metatiles is None
                else f"{metatiles['columns']}x{metatiles['rows']}={metatiles['count']}"
            )
            print(
                f"  {sheet['sheet_id']}: z{sheet['native_zoom']} "
                f"pixels={sheet['pixel_bounds']} size={sheet['width']}x{sheet['height']} "
                f"metatiles={metatile_text}"
            )
        pending_catalog_mismatches = (
            result["catalog_profile_mismatch_count"]
            + result["catalog_zoom_mismatch_count"]
        )
        if pending_catalog_mismatches and not args.check_catalog:
            print(
                f"  Catalog resolution migration pending: "
                f"{pending_catalog_mismatches} mismatch(es); pass --check-catalog "
                "to enforce them."
            )
    else:
        print(f"Resolution contract validation failed: {args.contract}", file=sys.stderr)
        for error in result["errors"]:
            print(f"- {error}", file=sys.stderr)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
