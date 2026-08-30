#!/usr/bin/env python3
"""Crop deterministic per-sheet generation controls from the world control."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Sequence

try:
    from PIL import Image, ImageOps
except ImportError as exc:  # pragma: no cover - CLI environment failure
    raise RuntimeError("Pillow is required: py -m pip install Pillow") from exc

from production_common import ID_PATTERN, REPO_ROOT, ValidationFailure, load_json


GENERATOR_ID = "sstory-map-production/render_sheet_controls.py@1"
DEFAULT_CONTROL = (
    REPO_ROOT / "world" / "map-production" / "controls" / "world-control-v1.png"
)
DEFAULT_CONTROL_METADATA = DEFAULT_CONTROL.with_suffix(".json")
DEFAULT_MAP_SHEETS = (
    REPO_ROOT / "world" / "map-production" / "source" / "map-sheets.json"
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "world" / "map-production" / "controls" / "sheets"
)
WORLD_EXTENT = 10000.0
DEFAULT_LONG_EDGE = 1536
SHORT_EDGE_QUANTUM = 16
SUPPORTED_SHEET_TYPES = frozenset(
    {"world", "continent", "region", "corridor", "settlement"}
)


class SheetControlError(ValueError):
    """Raised for invalid inputs or a refused output operation."""


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
    except ValueError:
        return resolved.as_posix()


def _is_finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def validate_sheet_bounds(value: Any, sheet_id: str) -> tuple[float, float, float, float]:
    if not (
        isinstance(value, list)
        and len(value) == 4
        and all(_is_finite_number(coordinate) for coordinate in value)
    ):
        raise SheetControlError(
            f"sheet {sheet_id!r} has no bounded [min_x, min_y, max_x, max_y] extent"
        )
    min_x, min_y, max_x, max_y = value
    if not (
        0 <= min_x < max_x <= WORLD_EXTENT
        and 0 <= min_y < max_y <= WORLD_EXTENT
    ):
        raise SheetControlError(
            f"sheet {sheet_id!r} bounds must be an ordered subset of EA-WORLD-1"
        )
    return float(min_x), float(min_y), float(max_x), float(max_y)


def load_sheet_catalog(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    try:
        catalog = load_json(path)
    except ValidationFailure as exc:
        raise SheetControlError(str(exc)) from exc
    if not isinstance(catalog, dict) or not isinstance(catalog.get("sheets"), list):
        raise SheetControlError(f"{path}: sheets must be an array")
    if catalog.get("coordinate_reference_system") != "EA-WORLD-1":
        raise SheetControlError(f"{path}: coordinate_reference_system must be EA-WORLD-1")

    sheets: dict[str, dict[str, Any]] = {}
    for index, sheet in enumerate(catalog["sheets"]):
        if not isinstance(sheet, dict):
            raise SheetControlError(f"{path}: sheets[{index}] must be an object")
        sheet_id = sheet.get("id")
        if not isinstance(sheet_id, str) or not ID_PATTERN.fullmatch(sheet_id):
            raise SheetControlError(f"{path}: sheets[{index}].id is invalid")
        if sheet_id in sheets:
            raise SheetControlError(f"{path}: duplicate sheet id {sheet_id!r}")
        sheets[sheet_id] = sheet
    return catalog, sheets


def bounded_sheets(sheets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for sheet in sheets.values():
        if sheet.get("sheet_type") not in SUPPORTED_SHEET_TYPES:
            continue
        try:
            validate_sheet_bounds(sheet.get("bounds"), str(sheet.get("id")))
        except SheetControlError:
            continue
        selected.append(sheet)
    return selected


def select_sheets(
    sheets: dict[str, dict[str, Any]],
    *,
    sheet_ids: Sequence[str] | None = None,
    select_all: bool = False,
) -> list[dict[str, Any]]:
    if select_all:
        return bounded_sheets(sheets)
    if not sheet_ids:
        raise SheetControlError("select at least one --sheet-id or pass --all")
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sheet_id in sheet_ids:
        if sheet_id in seen:
            continue
        seen.add(sheet_id)
        sheet = sheets.get(sheet_id)
        if sheet is None:
            raise SheetControlError(f"unknown sheet id: {sheet_id!r}")
        if sheet.get("sheet_type") not in SUPPORTED_SHEET_TYPES:
            raise SheetControlError(
                f"sheet {sheet_id!r} type {sheet.get('sheet_type')!r} is not a supported control type"
            )
        validate_sheet_bounds(sheet.get("bounds"), sheet_id)
        selected.append(sheet)
    return selected


def continuous_pixel_bounds(
    bounds: tuple[float, float, float, float], width: int, height: int
) -> tuple[float, float, float, float]:
    scale_x = (width - 1) / WORLD_EXTENT
    scale_y = (height - 1) / WORLD_EXTENT
    return (
        bounds[0] * scale_x,
        bounds[1] * scale_y,
        bounds[2] * scale_x,
        bounds[3] * scale_y,
    )


def integer_crop_box(
    pixel_bounds: tuple[float, float, float, float], width: int, height: int
) -> tuple[int, int, int, int]:
    # Include every source pixel touched by the continuous EA-WORLD-1 extent.
    left = max(0, math.floor(pixel_bounds[0]))
    top = max(0, math.floor(pixel_bounds[1]))
    right = min(width, math.ceil(pixel_bounds[2]) + 1)
    bottom = min(height, math.ceil(pixel_bounds[3]) + 1)
    if left >= right or top >= bottom:
        raise SheetControlError("sheet bounds collapse to an empty source crop")
    return left, top, right, bottom


def _round_to_quantum(value: float, quantum: int) -> int:
    return max(quantum, int(math.floor(value / quantum + 0.5)) * quantum)


def output_dimensions(
    bounds: tuple[float, float, float, float],
    *,
    source_width: int,
    source_height: int,
    long_edge: int = DEFAULT_LONG_EDGE,
) -> tuple[int, int]:
    if long_edge < 256 or long_edge > 8192 or long_edge % SHORT_EDGE_QUANTUM:
        raise SheetControlError(
            f"long edge must be a multiple of {SHORT_EDGE_QUANTUM} between 256 and 8192"
        )
    span_x = (bounds[2] - bounds[0]) * (source_width - 1) / WORLD_EXTENT
    span_y = (bounds[3] - bounds[1]) * (source_height - 1) / WORLD_EXTENT
    if span_x >= span_y:
        short = min(long_edge, _round_to_quantum(long_edge * span_y / span_x, SHORT_EDGE_QUANTUM))
        return long_edge, short
    short = min(long_edge, _round_to_quantum(long_edge * span_x / span_y, SHORT_EDGE_QUANTUM))
    return short, long_edge


def _contained_content_size(
    pixel_bounds: tuple[float, float, float, float],
    target_size: tuple[int, int],
) -> tuple[int, int]:
    span_x = pixel_bounds[2] - pixel_bounds[0]
    span_y = pixel_bounds[3] - pixel_bounds[1]
    source_aspect = span_x / span_y
    target_aspect = target_size[0] / target_size[1]
    if source_aspect >= target_aspect:
        return target_size[0], max(1, round(target_size[0] / source_aspect))
    return max(1, round(target_size[1] * source_aspect)), target_size[1]


def _edge_extend_content(
    content: Image.Image, target_size: tuple[int, int]
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Fill aspect-quantization padding by repeating the content edge pixels."""

    target_width, target_height = target_size
    content_width, content_height = content.size
    offset_x = (target_width - content_width) // 2
    offset_y = (target_height - content_height) // 2
    canvas = Image.new(content.mode, target_size)
    canvas.paste(content, (offset_x, offset_y))

    left_pad = offset_x
    top_pad = offset_y
    right_pad = target_width - content_width - offset_x
    bottom_pad = target_height - content_height - offset_y
    if left_pad:
        strip = content.crop((0, 0, 1, content_height)).resize(
            (left_pad, content_height), Image.Resampling.NEAREST
        )
        canvas.paste(strip, (0, offset_y))
    if right_pad:
        strip = content.crop((content_width - 1, 0, content_width, content_height)).resize(
            (right_pad, content_height), Image.Resampling.NEAREST
        )
        canvas.paste(strip, (offset_x + content_width, offset_y))
    if top_pad:
        row = canvas.crop((0, offset_y, target_width, offset_y + 1)).resize(
            (target_width, top_pad), Image.Resampling.NEAREST
        )
        canvas.paste(row, (0, 0))
    if bottom_pad:
        row = canvas.crop(
            (0, offset_y + content_height - 1, target_width, offset_y + content_height)
        ).resize((target_width, bottom_pad), Image.Resampling.NEAREST)
        canvas.paste(row, (0, offset_y + content_height))
    return canvas, (left_pad, top_pad, right_pad, bottom_pad)


def render_exact_extent(
    source: Image.Image,
    pixel_bounds: tuple[float, float, float, float],
    target_size: tuple[int, int],
) -> tuple[Image.Image, tuple[int, int, int, int], tuple[int, int]]:
    """Sample the exact fractional extent at one uniform scale, without stretching."""

    content_size = _contained_content_size(pixel_bounds, target_size)
    content = source.transform(
        content_size,
        Image.Transform.EXTENT,
        data=pixel_bounds,
        resample=Image.Resampling.BICUBIC,
    )
    try:
        rendered, padding = _edge_extend_content(content, target_size)
        return rendered, padding, content_size
    finally:
        content.close()


def load_control_metadata(path: Path, control_path: Path) -> tuple[dict[str, Any], str]:
    try:
        metadata = load_json(path)
    except ValidationFailure as exc:
        raise SheetControlError(str(exc)) from exc
    if not isinstance(metadata, dict):
        raise SheetControlError(f"{path}: control metadata must be an object")
    expected_hash = metadata.get("output", {}).get("sha256")
    actual_hash = sha256_file(control_path)
    if expected_hash != actual_hash:
        raise SheetControlError(
            f"source control SHA-256 mismatch: metadata={expected_hash!r}, actual={actual_hash}"
        )
    return metadata, sha256_file(path)


def _copy_exclusive(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as input_handle, destination.open("xb") as output_handle:
        shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)


def _sheet_record(sheet: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "id",
        "name",
        "sheet_type",
        "parent_id",
        "secondary_parent_ids",
        "source_feature_id",
        "bounds",
        "zoom_range",
        "native_zoom",
        "review_status",
        "geometry_confidence",
        "priority",
    )
    return {field: sheet[field] for field in fields if field in sheet}


def render_one_sheet(
    source: Image.Image,
    sheet: dict[str, Any],
    *,
    source_control_path: Path,
    source_control_metadata_path: Path,
    source_control_metadata: dict[str, Any],
    source_control_metadata_sha256: str,
    map_sheets_path: Path,
    map_sheets_sha256: str,
    output_dir: Path,
    long_edge: int = DEFAULT_LONG_EDGE,
) -> dict[str, Any]:
    sheet_id = str(sheet.get("id"))
    bounds = validate_sheet_bounds(sheet.get("bounds"), sheet_id)
    pixel_extent = continuous_pixel_bounds(bounds, source.width, source.height)
    crop_box = integer_crop_box(pixel_extent, source.width, source.height)
    target_size = output_dimensions(
        bounds,
        source_width=source.width,
        source_height=source.height,
        long_edge=long_edge,
    )

    png_path = (output_dir / f"{sheet_id}.png").resolve()
    json_path = (output_dir / f"{sheet_id}.json").resolve()
    for target in (png_path, json_path):
        if target.exists():
            raise SheetControlError(f"refusing to overwrite existing output: {target}")

    rendered, padding, content_size = render_exact_extent(
        source, pixel_extent, target_size
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{sheet_id}.", suffix=".png", dir=output_dir
    )
    os.close(fd)
    temporary_png = Path(temporary_name)
    temporary_json = temporary_png.with_suffix(".json")
    installed_png = False
    installed_json = False
    try:
        rendered.save(temporary_png, format="PNG", compress_level=6, optimize=False)
        output_sha256 = sha256_file(temporary_png)
        metadata: dict[str, Any] = {
            "schema_version": "1.0.0",
            "type": "sstory-sheet-generation-control",
            "generated_by": GENERATOR_ID,
            "artifact_role": "image-generation-reference-and-qa-overlay",
            "coordinate_reference_system": "EA-WORLD-1",
            "sheet": _sheet_record(sheet),
            "source_control": {
                "path": repo_path(source_control_path),
                "sha256": sha256_file(source_control_path),
                "metadata_path": repo_path(source_control_metadata_path),
                "metadata_sha256": source_control_metadata_sha256,
                "width": source.width,
                "height": source.height,
                "verified_metadata_output_sha256": source_control_metadata.get("output", {}).get("sha256"),
            },
            "map_sheets": {
                "path": repo_path(map_sheets_path),
                "sha256": map_sheets_sha256,
            },
            "pixel_mapping": {
                "x_scale": (source.width - 1) / WORLD_EXTENT,
                "y_scale": (source.height - 1) / WORLD_EXTENT,
                "continuous_pixel_bounds": [round(value, 6) for value in pixel_extent],
                "pixel_bounds": list(crop_box),
                "pixel_bounds_semantics": "Pillow half-open [left, top, right, bottom], conservatively includes every touched source pixel",
            },
            "rendering": {
                "long_edge_px": long_edge,
                "short_edge_quantum_px": SHORT_EDGE_QUANTUM,
                "target_size": list(target_size),
                "content_size": list(content_size),
                "conservative_source_crop_size": [
                    crop_box[2] - crop_box[0],
                    crop_box[3] - crop_box[1],
                ],
                "content_padding_px": {
                    "left": padding[0],
                    "top": padding[1],
                    "right": padding[2],
                    "bottom": padding[3],
                },
                "resampling": "Pillow fractional EXTENT with BICUBIC at uniform contain scale",
                "padding": "nearest edge-pixel extension",
                "stretch": False,
                "labels_baked_into_raster": False,
            },
            "output": {
                "path": repo_path(png_path),
                "metadata_path": repo_path(json_path),
                "format": "PNG",
                "mode": rendered.mode,
                "width": rendered.width,
                "height": rendered.height,
                "bytes": temporary_png.stat().st_size,
                "sha256": output_sha256,
            },
        }
        temporary_json.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _copy_exclusive(temporary_png, png_path)
        installed_png = True
        try:
            _copy_exclusive(temporary_json, json_path)
            installed_json = True
        except Exception:
            png_path.unlink(missing_ok=True)
            installed_png = False
            raise
        return metadata
    finally:
        rendered.close()
        temporary_png.unlink(missing_ok=True)
        temporary_json.unlink(missing_ok=True)
        if installed_png and not installed_json:
            png_path.unlink(missing_ok=True)


def generate_sheet_controls(
    *,
    sheet_ids: Sequence[str] | None = None,
    select_all: bool = False,
    source_control_path: Path = DEFAULT_CONTROL,
    source_control_metadata_path: Path = DEFAULT_CONTROL_METADATA,
    map_sheets_path: Path = DEFAULT_MAP_SHEETS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    long_edge: int = DEFAULT_LONG_EDGE,
) -> list[dict[str, Any]]:
    source_control_path = source_control_path.resolve()
    source_control_metadata_path = source_control_metadata_path.resolve()
    map_sheets_path = map_sheets_path.resolve()
    output_dir = output_dir.resolve()
    if not source_control_path.is_file():
        raise SheetControlError(f"source control does not exist: {source_control_path}")
    if not source_control_metadata_path.is_file():
        raise SheetControlError(
            f"source control metadata does not exist: {source_control_metadata_path}"
        )
    if output_dir.exists() and not output_dir.is_dir():
        raise SheetControlError(f"output path exists and is not a directory: {output_dir}")
    if output_dir in {
        Path(output_dir.anchor).resolve(),
        REPO_ROOT.resolve(),
        Path.home().resolve(),
    }:
        raise SheetControlError(f"refusing broad output directory: {output_dir}")

    _, sheets = load_sheet_catalog(map_sheets_path)
    selected = select_sheets(sheets, sheet_ids=sheet_ids, select_all=select_all)
    # Refuse the whole batch before rendering anything when a known target exists.
    for sheet in selected:
        sheet_id = sheet["id"]
        for suffix in (".png", ".json"):
            target = output_dir / f"{sheet_id}{suffix}"
            if target.exists():
                raise SheetControlError(f"refusing to overwrite existing output: {target}")

    control_metadata, control_metadata_sha256 = load_control_metadata(
        source_control_metadata_path, source_control_path
    )
    map_sheets_sha256 = sha256_file(map_sheets_path)
    with Image.open(source_control_path) as opened:
        source = ImageOps.exif_transpose(opened).convert("RGB")
        expected_width = control_metadata.get("output", {}).get("width")
        expected_height = control_metadata.get("output", {}).get("height")
        if (expected_width, expected_height) != source.size:
            source.close()
            raise SheetControlError(
                "source control dimensions do not match its metadata: "
                f"metadata={(expected_width, expected_height)}, actual={source.size}"
            )
        try:
            return [
                render_one_sheet(
                    source,
                    sheet,
                    source_control_path=source_control_path,
                    source_control_metadata_path=source_control_metadata_path,
                    source_control_metadata=control_metadata,
                    source_control_metadata_sha256=control_metadata_sha256,
                    map_sheets_path=map_sheets_path,
                    map_sheets_sha256=map_sheets_sha256,
                    output_dir=output_dir,
                    long_edge=long_edge,
                )
                for sheet in selected
            ]
        finally:
            source.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--sheet-id",
        action="append",
        dest="sheet_ids",
        help="bounded sheet ID; repeat to generate a small batch",
    )
    selection.add_argument("--all", action="store_true", dest="select_all")
    parser.add_argument("--source-control", type=Path, default=DEFAULT_CONTROL)
    parser.add_argument(
        "--source-metadata", type=Path, default=DEFAULT_CONTROL_METADATA
    )
    parser.add_argument("--map-sheets", type=Path, default=DEFAULT_MAP_SHEETS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--long-edge", type=int, default=DEFAULT_LONG_EDGE)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        generated = generate_sheet_controls(
            sheet_ids=args.sheet_ids,
            select_all=args.select_all,
            source_control_path=args.source_control,
            source_control_metadata_path=args.source_metadata,
            map_sheets_path=args.map_sheets,
            output_dir=args.output_dir,
            long_edge=args.long_edge,
        )
    except (OSError, SheetControlError) as exc:
        print(f"sheet control render failed: {exc}")
        return 1
    for metadata in generated:
        print(
            f"sheet control rendered: {metadata['sheet']['id']} "
            f"{metadata['output']['width']}x{metadata['output']['height']} "
            f"sha256={metadata['output']['sha256']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
