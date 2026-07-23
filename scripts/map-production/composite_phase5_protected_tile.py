#!/usr/bin/env python3
"""Build one Phase 5 protected metatile from a raw ImageGen PNG.

The checked control renderer currently supplies a deliberately simple parent
preview.  That preview remains hash-locked provenance, but it is not silently
used as the production fallback.  Callers must pass the actual parent raster
explicitly with ``--parent-context``.  Unknown pixels are copied from that
runtime parent byte-for-byte; known interiors retain the generated artwork;
only the canonical land/water boundary, transport, and reviewed detail masks
are protected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

try:
    from jsonschema import Draft7Validator, FormatChecker
    from PIL import Image, ImageChops, ImageFilter, ImageOps
except ImportError as exc:  # pragma: no cover - CLI environment failure
    raise RuntimeError(
        "Pillow and jsonschema are required: python -m pip install Pillow jsonschema"
    ) from exc

from production_common import (
    REPO_ROOT,
    ValidationFailure,
    load_json,
    parse_rfc3339,
    utc_now,
)


GENERATOR_ID = "sstory-map-production/composite_phase5_protected_tile.py@1"
INDEX_SCHEMA_URL = (
    "https://sstory.example/schemas/phase5-metatile-control-index.schema.json"
)
CONTROL_SCHEMA_URL = (
    "https://sstory.example/schemas/phase5-protected-control.schema.json"
)
REPORT_SCHEMA_URL = (
    "https://sstory.example/schemas/phase5-postprocess-report.schema.json"
)
DEFAULT_INDEX = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "controls"
    / "phase5-metatiles"
    / "index.json"
)
DEFAULT_INDEX_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "phase5-metatile-control-index.schema.json"
)
DEFAULT_CONTROL_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "phase5-protected-control.schema.json"
)
DEFAULT_REPORT_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "phase5-postprocess-report.schema.json"
)
METATILE_SIZE = 2048
PIXEL_COUNT = METATILE_SIZE * METATILE_SIZE
BOUNDARY_FILTER_SIZE = 5
PNG_SAVE_OPTIONS = {"format": "PNG", "compress_level": 9, "optimize": False}


class Phase5CompositeError(ValueError):
    """Raised when a protected composite cannot be proven safe."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise Phase5CompositeError(
            f"artifact must remain inside the repository: {path}"
        ) from exc


def _resolve_cli_path(path: Path, label: str, *, must_exist: bool) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise Phase5CompositeError(
            f"{label} must remain inside the repository: {path}"
        ) from exc
    if must_exist and not resolved.is_file():
        raise Phase5CompositeError(f"{label} does not exist as a file: {path}")
    return resolved


def _resolve_artifact_path(raw_path: Any, label: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path:
        raise Phase5CompositeError(f"{label} must be a repository-relative POSIX path")
    portable = PurePosixPath(raw_path)
    if (
        portable.is_absolute()
        or any(part in {"", ".", ".."} for part in portable.parts)
        or (portable.parts and portable.parts[0].endswith(":"))
    ):
        raise Phase5CompositeError(
            f"{label} must remain inside the repository: {raw_path!r}"
        )
    resolved = REPO_ROOT.joinpath(*portable.parts).resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise Phase5CompositeError(
            f"{label} must remain inside the repository: {raw_path!r}"
        ) from exc
    if not resolved.is_file():
        raise Phase5CompositeError(f"{label} does not exist: {raw_path}")
    return resolved


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = load_json(path)
    except ValidationFailure as exc:
        raise Phase5CompositeError(str(exc)) from exc
    if not isinstance(value, dict):
        raise Phase5CompositeError(f"{label} must contain a JSON object")
    return value


def _validate_schema(document: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = _load_json_object(schema_path, f"{label} schema")
    errors = sorted(
        Draft7Validator(schema, format_checker=FormatChecker()).iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        rendered = []
        for error in errors[:20]:
            location = ".".join(str(part) for part in error.absolute_path) or "<root>"
            rendered.append(f"{location}: {error.message}")
        raise Phase5CompositeError(f"{label} is invalid: " + "; ".join(rendered))


def _verify_artifact(spec: Any, label: str) -> Path:
    if not isinstance(spec, dict):
        raise Phase5CompositeError(f"{label} must be an artifact object")
    path = _resolve_artifact_path(spec.get("path"), f"{label}.path")
    expected = spec.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise Phase5CompositeError(f"{label}.sha256 must be a SHA-256 digest")
    actual = sha256_file(path)
    if actual != expected.lower():
        raise Phase5CompositeError(
            f"{label}.sha256 mismatch: control={expected.lower()}, actual={actual}"
        )
    return path


def _artifact_equal(first: Any, second: Any) -> bool:
    return (
        isinstance(first, dict)
        and isinstance(second, dict)
        and first.get("path") == second.get("path")
        and first.get("sha256") == second.get("sha256")
    )


def _load_exact_png(path: Path, label: str, mode: str) -> Image.Image:
    try:
        with Image.open(path) as opened:
            opened.load()
            if opened.size != (METATILE_SIZE, METATILE_SIZE):
                raise Phase5CompositeError(
                    f"{label} must be {METATILE_SIZE}x{METATILE_SIZE}, "
                    f"found {opened.size}"
                )
            if opened.format != "PNG" or opened.mode != mode:
                raise Phase5CompositeError(
                    f"{label} must be a native {mode} PNG, "
                    f"found format={opened.format}, mode={opened.mode}"
                )
            return opened.copy()
    except Phase5CompositeError:
        raise
    except (OSError, ValueError) as exc:
        raise Phase5CompositeError(f"cannot read {label} {path}: {exc}") from exc


def _image_artifact(path: Path, *, logical_path: Path | None = None) -> dict[str, Any]:
    with Image.open(path) as opened:
        opened.load()
        if (
            opened.size != (METATILE_SIZE, METATILE_SIZE)
            or opened.format != "PNG"
            or opened.mode != "RGB"
        ):
            raise Phase5CompositeError(
                f"image contract mismatch for {path}: "
                f"size={opened.size}, format={opened.format}, mode={opened.mode}"
            )
    return {
        "path": repo_path(logical_path or path),
        "sha256": sha256_file(path),
        "width": METATILE_SIZE,
        "height": METATILE_SIZE,
        "format": "PNG",
        "color_mode": "RGB",
    }


def _artifact_only(spec: dict[str, Any]) -> dict[str, str]:
    return {"path": spec["path"], "sha256": spec["sha256"]}


def _assert_binary(mask: Image.Image, label: str) -> None:
    histogram = mask.histogram()
    if sum(histogram[1:255]):
        raise Phase5CompositeError(f"{label} must contain only 0 and 255")


def _mask_count(mask: Image.Image) -> int:
    return mask.histogram()[255]


def _assert_masks_equal(first: Image.Image, second: Image.Image, label: str) -> None:
    difference = ImageChops.difference(first, second)
    try:
        if difference.getbbox() is not None:
            raise Phase5CompositeError(f"{label} masks differ")
    finally:
        difference.close()


def _mask_union(*masks: Image.Image) -> Image.Image:
    if not masks:
        return Image.new("L", (METATILE_SIZE, METATILE_SIZE), 0)
    result = masks[0].copy()
    for mask in masks[1:]:
        updated = ImageChops.lighter(result, mask)
        result.close()
        result = updated
    return result


def _mask_without(mask: Image.Image, excluded: Image.Image) -> Image.Image:
    inverse = ImageOps.invert(excluded)
    try:
        return ImageChops.multiply(mask, inverse)
    finally:
        inverse.close()


def derive_land_water_boundary(
    land_mask: Image.Image, water_mask: Image.Image
) -> Image.Image:
    """Return a symmetric narrow band only where canonical land touches water."""

    expanded_land = land_mask.filter(ImageFilter.MaxFilter(BOUNDARY_FILTER_SIZE))
    expanded_water = water_mask.filter(ImageFilter.MaxFilter(BOUNDARY_FILTER_SIZE))
    known = ImageChops.lighter(land_mask, water_mask)
    try:
        adjacency = ImageChops.multiply(expanded_land, expanded_water)
        try:
            boundary = ImageChops.multiply(adjacency, known)
        finally:
            adjacency.close()
    finally:
        expanded_land.close()
        expanded_water.close()
        known.close()
    _assert_binary(boundary, "derived land/water boundary")
    return boundary


def _mismatch_count(
    actual: Image.Image, expected: Image.Image, mask: Image.Image
) -> int:
    difference = ImageChops.difference(actual, expected)
    bands = difference.split()
    first_two = ImageChops.lighter(bands[0], bands[1])
    combined = ImageChops.lighter(first_two, bands[2])
    masked = ImageChops.multiply(combined, mask)
    try:
        return sum(masked.histogram()[1:])
    finally:
        difference.close()
        for band in bands:
            band.close()
        first_two.close()
        combined.close()
        masked.close()


def _gate(
    name: str,
    actual: Image.Image,
    expected: Image.Image,
    mask: Image.Image,
) -> dict[str, Any]:
    mismatch_count = _mismatch_count(actual, expected, mask)
    if mismatch_count:
        raise Phase5CompositeError(
            f"zero-difference gate {name!r} failed at {mismatch_count} pixels"
        )
    return {
        "name": name,
        "pixel_count": _mask_count(mask),
        "mismatch_pixel_count": 0,
        "passed": True,
    }


def _find_index_tile(
    index: dict[str, Any], control: dict[str, Any], control_path: Path
) -> dict[str, Any]:
    candidates = [
        tile
        for sheet in index["sheets"]
        if sheet["sheet_id"] == control["sheet_id"]
        for tile in sheet["tiles"]
        if (tile["column"], tile["row"]) == (control["column"], control["row"])
    ]
    if len(candidates) != 1:
        raise Phase5CompositeError(
            "control coordinates must identify exactly one metatile in the index"
        )
    tile = candidates[0]
    indexed_control = tile["protected_control"]
    actual_control = {
        "path": repo_path(control_path),
        "sha256": sha256_file(control_path),
    }
    if not _artifact_equal(indexed_control, actual_control):
        raise Phase5CompositeError(
            "protected control path/hash does not match the indexed metatile"
        )
    if not _artifact_equal(
        tile["receipt_bindings"]["postprocess_control"], indexed_control
    ):
        raise Phase5CompositeError("indexed postprocess-control binding is stale")
    return tile


def _verify_control_bindings(
    tile: dict[str, Any], control: dict[str, Any]
) -> dict[str, Path]:
    pairs = (
        (
            "visual_geometry_control",
            tile["visual_geometry_control"],
            control["visual_geometry_control"],
        ),
        ("parent_context", tile["parent_context"], control["parent_context"]),
        (
            "land_mask",
            tile["authoritative_controls"]["land_mask"],
            control["land_sea"]["land_mask"],
        ),
        (
            "water_mask",
            tile["authoritative_controls"]["water_mask"],
            control["land_sea"]["water_mask"],
        ),
        (
            "known_mask",
            tile["authoritative_controls"]["known_mask"],
            control["land_sea"]["known_mask"],
        ),
        (
            "unknown_mask",
            tile["authoritative_controls"]["unknown_mask"],
            control["land_sea"]["unknown_mask"],
        ),
        (
            "land_sea_overlay",
            tile["authoritative_controls"]["land_sea_overlay"],
            control["land_sea"]["authoritative_overlay"],
        ),
        (
            "transport_mask",
            tile["authoritative_controls"]["transport_mask"],
            control["transport"]["mask"],
        ),
        (
            "transport_overlay",
            tile["authoritative_controls"]["transport_overlay"],
            control["transport"]["authoritative_overlay"],
        ),
        (
            "detail_mask",
            tile["authoritative_controls"]["detail_mask"],
            control["detail"]["mask"],
        ),
        (
            "detail_overlay",
            tile["authoritative_controls"]["detail_overlay"],
            control["detail"]["authoritative_overlay"],
        ),
    )
    paths: dict[str, Path] = {}
    for label, indexed, controlled in pairs:
        if not _artifact_equal(indexed, controlled):
            raise Phase5CompositeError(
                f"index and protected control disagree for {label}"
            )
        paths[label] = _verify_artifact(controlled, f"control.{label}")

    unknown = control["unknown_fallback"]
    if not _artifact_equal(unknown["mask"], control["land_sea"]["unknown_mask"]):
        raise Phase5CompositeError(
            "unknown fallback mask is not the canonical unknown mask"
        )
    if not _artifact_equal(unknown["source"], control["parent_context"]):
        raise Phase5CompositeError(
            "unknown fallback provenance is not the checked parent"
        )
    if control["land_sea"]["partition"] != tile["authoritative_controls"]["partition"]:
        raise Phase5CompositeError(
            "index and protected control partition claims differ"
        )

    for index, context in enumerate(control["prior_neighbor_contexts"]):
        _verify_artifact(
            context["context"], f"control.prior_neighbor_contexts[{index}]"
        )
    for name in ("resolution_contract", "map_sheets"):
        _verify_artifact(
            control["source_inputs"][name], f"control.source_inputs.{name}"
        )
    for index, source in enumerate(control["source_inputs"]["canon_sources"]):
        _verify_artifact(source, f"control.source_inputs.canon_sources[{index}]")
    return paths


def _validate_partition(
    control: dict[str, Any],
    land: Image.Image,
    water: Image.Image,
    known: Image.Image,
    unknown: Image.Image,
) -> dict[str, Any]:
    for label, mask in (
        ("land", land),
        ("water", water),
        ("known", known),
        ("unknown", unknown),
    ):
        _assert_binary(mask, f"{label} mask")

    overlap = ImageChops.multiply(land, water)
    expected_known = ImageChops.lighter(land, water)
    expected_unknown = ImageOps.invert(expected_known)
    try:
        if overlap.getbbox() is not None:
            raise Phase5CompositeError("canonical land and water masks overlap")
        _assert_masks_equal(known, expected_known, "canonical known/land-water union")
        _assert_masks_equal(unknown, expected_unknown, "canonical unknown complement")
    finally:
        overlap.close()
        expected_known.close()
        expected_unknown.close()

    actual = {
        "algorithm": "canon-land-water-unknown-partition-v1",
        "pixel_count": PIXEL_COUNT,
        "land_pixel_count": _mask_count(land),
        "water_pixel_count": _mask_count(water),
        "unknown_pixel_count": _mask_count(unknown),
        "overlap_pixel_count": 0,
        "unclassified_pixel_count": 0,
    }
    if (
        actual["land_pixel_count"]
        + actual["water_pixel_count"]
        + actual["unknown_pixel_count"]
        != PIXEL_COUNT
    ):
        raise Phase5CompositeError("canonical masks do not exhaust the metatile")
    claimed = control["land_sea"]["partition"]
    for key, value in actual.items():
        if claimed[key] != value:
            raise Phase5CompositeError(
                f"partition claim {key} is stale: control={claimed[key]}, actual={value}"
            )
    return actual


def _new_stage_path(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{destination.name}.building-",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    return Path(raw_path)


def _publish_no_overwrite(staged: Path, destination: Path) -> None:
    try:
        os.link(staged, destination)
    except FileExistsError as exc:
        raise Phase5CompositeError(
            f"refusing to overwrite existing output: {destination}"
        ) from exc
    except OSError as exc:
        raise Phase5CompositeError(
            f"cannot atomically publish {destination}: {exc}"
        ) from exc
    staged.unlink()


def _validate_created_at(created_at: str) -> None:
    try:
        parse_rfc3339(created_at)
    except ValueError as exc:
        raise Phase5CompositeError(str(exc)) from exc


def composite_tile(
    *,
    index_path: Path,
    control_path: Path,
    raw_output_path: Path,
    parent_context_path: Path,
    output_path: Path,
    report_path: Path,
    created_at: str | None = None,
    index_schema_path: Path = DEFAULT_INDEX_SCHEMA,
    control_schema_path: Path = DEFAULT_CONTROL_SCHEMA,
    report_schema_path: Path = DEFAULT_REPORT_SCHEMA,
) -> dict[str, Any]:
    """Validate, compose, verify, and atomically publish one protected tile."""

    index_path = _resolve_cli_path(index_path, "control index", must_exist=True)
    control_path = _resolve_cli_path(control_path, "protected control", must_exist=True)
    raw_output_path = _resolve_cli_path(raw_output_path, "raw output", must_exist=True)
    parent_context_path = _resolve_cli_path(
        parent_context_path, "runtime parent context", must_exist=True
    )
    output_path = _resolve_cli_path(output_path, "output", must_exist=False)
    report_path = _resolve_cli_path(report_path, "report", must_exist=False)
    index_schema_path = _resolve_cli_path(
        index_schema_path, "index schema", must_exist=True
    )
    control_schema_path = _resolve_cli_path(
        control_schema_path, "control schema", must_exist=True
    )
    report_schema_path = _resolve_cli_path(
        report_schema_path, "report schema", must_exist=True
    )
    if output_path == report_path:
        raise Phase5CompositeError("output and report paths must be distinct")
    if raw_output_path == parent_context_path:
        raise Phase5CompositeError(
            "raw output and runtime parent context must be distinct files"
        )
    if output_path.exists() or report_path.exists():
        occupied = output_path if output_path.exists() else report_path
        raise Phase5CompositeError(f"refusing to overwrite existing output: {occupied}")

    timestamp = created_at or utc_now()
    _validate_created_at(timestamp)
    index = _load_json_object(index_path, "Phase 5 control index")
    control = _load_json_object(control_path, "Phase 5 protected control")
    if index.get("$schema") != INDEX_SCHEMA_URL:
        raise Phase5CompositeError("control index declares an unexpected schema")
    if control.get("$schema") != CONTROL_SCHEMA_URL:
        raise Phase5CompositeError("protected control declares an unexpected schema")
    _validate_schema(index, index_schema_path, "Phase 5 control index")
    _validate_schema(control, control_schema_path, "Phase 5 protected control")
    tile = _find_index_tile(index, control, control_path)
    paths = _verify_control_bindings(tile, control)

    raw = _load_exact_png(raw_output_path, "raw output", "RGB")
    runtime_parent = _load_exact_png(
        parent_context_path, "runtime parent context", "RGB"
    )
    land = _load_exact_png(paths["land_mask"], "land mask", "L")
    water = _load_exact_png(paths["water_mask"], "water mask", "L")
    known = _load_exact_png(paths["known_mask"], "known mask", "L")
    unknown = _load_exact_png(paths["unknown_mask"], "unknown mask", "L")
    land_sea_overlay = _load_exact_png(
        paths["land_sea_overlay"], "land/sea overlay", "RGB"
    )
    transport_mask = _load_exact_png(paths["transport_mask"], "transport mask", "L")
    transport_overlay = _load_exact_png(
        paths["transport_overlay"], "transport overlay", "RGB"
    )
    detail_mask = _load_exact_png(paths["detail_mask"], "detail mask", "L")
    detail_overlay = _load_exact_png(paths["detail_overlay"], "detail overlay", "RGB")
    staged_output: Path | None = None
    staged_report: Path | None = None
    published_output = False
    output_digest: str | None = None
    final = raw.copy()
    masks: list[Image.Image] = []
    try:
        partition = _validate_partition(control, land, water, known, unknown)
        _assert_binary(transport_mask, "transport mask")
        _assert_binary(detail_mask, "detail mask")
        boundary = derive_land_water_boundary(land, water)
        masks.append(boundary)

        transport_known = ImageChops.multiply(transport_mask, known)
        detail_known = ImageChops.multiply(detail_mask, known)
        masks.extend((transport_known, detail_known))
        protected_union = _mask_union(boundary, transport_known, detail_known)
        masks.append(protected_union)
        known_generated = _mask_without(known, protected_union)
        masks.append(known_generated)

        final.paste(land_sea_overlay, (0, 0), boundary)
        final.paste(transport_overlay, (0, 0), transport_known)
        final.paste(detail_overlay, (0, 0), detail_known)
        final.paste(runtime_parent, (0, 0), unknown)

        detail_effective = detail_known.copy()
        transport_without_detail = _mask_without(transport_known, detail_known)
        later_linear = _mask_union(transport_known, detail_known)
        boundary_effective = _mask_without(boundary, later_linear)
        masks.extend(
            (
                detail_effective,
                transport_without_detail,
                later_linear,
                boundary_effective,
            )
        )
        staged_output = _new_stage_path(output_path)
        final.save(staged_output, **PNG_SAVE_OPTIONS)
        persisted_final = _load_exact_png(
            staged_output, "staged protected output", "RGB"
        )
        try:
            gates = [
                _gate(
                    "unknown-parent-fallback",
                    persisted_final,
                    runtime_parent,
                    unknown,
                ),
                _gate(
                    "land-water-boundary",
                    persisted_final,
                    land_sea_overlay,
                    boundary_effective,
                ),
                _gate(
                    "transport",
                    persisted_final,
                    transport_overlay,
                    transport_without_detail,
                ),
                _gate(
                    "detail",
                    persisted_final,
                    detail_overlay,
                    detail_effective,
                ),
                _gate(
                    "known-generated-interior",
                    persisted_final,
                    raw,
                    known_generated,
                ),
            ]
        finally:
            persisted_final.close()
        total_mismatches = sum(gate["mismatch_pixel_count"] for gate in gates)
        if total_mismatches != 0:
            raise Phase5CompositeError("protected-composite exactness gates failed")

        output_image = _image_artifact(staged_output, logical_path=output_path)
        output_digest = output_image["sha256"]
        raw_image = _image_artifact(raw_output_path)
        parent_image = _image_artifact(parent_context_path)
        report = {
            "$schema": REPORT_SCHEMA_URL,
            "schema_version": "1.0.0",
            "type": "sstory-phase5-deterministic-protected-composite-report",
            "coordinate_reference_system": "EA-WORLD-1",
            "generated_by": GENERATOR_ID,
            "mode": "deterministic-protected-composite",
            "sheet_id": control["sheet_id"],
            "column": control["column"],
            "row": control["row"],
            "raw_output": _artifact_only(raw_image),
            "control": {
                "path": repo_path(control_path),
                "sha256": sha256_file(control_path),
            },
            "output": _artifact_only(output_image),
            "protected_layers": ["land-sea", "transport", "detail"],
            "created_at": timestamp,
            "image_contract": {
                "raw_output": raw_image,
                "runtime_parent_context": parent_image,
                "output": output_image,
            },
            "verification": {
                "algorithm": "phase5-protected-composite-v1",
                "land_water_boundary_filter_size_px": BOUNDARY_FILTER_SIZE,
                "partition": partition,
                "gates": gates,
                "total_mismatch_pixel_count": 0,
                "passed": True,
            },
        }
        _validate_schema(report, report_schema_path, "Phase 5 postprocess report")
        staged_report = _new_stage_path(report_path)
        staged_report.write_text(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
                sort_keys=False,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )

        _publish_no_overwrite(staged_output, output_path)
        staged_output = None
        published_output = True
        _publish_no_overwrite(staged_report, report_path)
        staged_report = None
        return report
    except Exception:
        if (
            published_output
            and output_path.is_file()
            and output_digest is not None
            and sha256_file(output_path) == output_digest
        ):
            output_path.unlink()
        raise
    finally:
        for path in (staged_output, staged_report):
            if path is not None:
                path.unlink(missing_ok=True)
        for image in (
            raw,
            runtime_parent,
            land,
            water,
            known,
            unknown,
            land_sea_overlay,
            transport_mask,
            transport_overlay,
            detail_mask,
            detail_overlay,
            final,
            *masks,
        ):
            image.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument(
        "--raw-output", "--raw", dest="raw_output", type=Path, required=True
    )
    parser.add_argument(
        "--parent-context",
        type=Path,
        required=True,
        help="actual 2048x2048 RGB parent raster; never inferred from the flat control preview",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--created-at", help="optional explicit RFC 3339 report timestamp"
    )
    parser.add_argument("--index-schema", type=Path, default=DEFAULT_INDEX_SCHEMA)
    parser.add_argument("--control-schema", type=Path, default=DEFAULT_CONTROL_SCHEMA)
    parser.add_argument("--report-schema", type=Path, default=DEFAULT_REPORT_SCHEMA)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = composite_tile(
            index_path=args.index,
            control_path=args.control,
            raw_output_path=args.raw_output,
            parent_context_path=args.parent_context,
            output_path=args.output,
            report_path=args.report,
            created_at=args.created_at,
            index_schema_path=args.index_schema,
            control_schema_path=args.control_schema,
            report_schema_path=args.report_schema,
        )
    except Phase5CompositeError as exc:
        print(f"Phase 5 protected-composite error: {exc}", file=sys.stderr)
        return 1
    print(
        "Phase 5 protected metatile published: "
        f"{report['sheet_id']} c{report['column']:02d}-r{report['row']:02d}, "
        f"sha256={report['output']['sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
