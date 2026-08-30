#!/usr/bin/env python3
"""Composite an ImageGen edit through a versioned pixel mask.

The base image is copied byte-for-pixel outside the binary mask. Feathering is
restricted to the inside of the mask so a generated edit cannot leak into
protected geography.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps


def load_control(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "1.0.0":
        raise ValueError("unsupported mask-control schema_version")
    canvas = data.get("canvas")
    if not isinstance(canvas, dict) or not all(isinstance(canvas.get(key), int) for key in ("width", "height")):
        raise ValueError("mask control requires integer canvas.width and canvas.height")
    polygons = data.get("include_polygons", [])
    strokes = data.get("include_strokes", [])
    if not isinstance(polygons, list):
        raise ValueError("include_polygons must be an array")
    if not isinstance(strokes, list):
        raise ValueError("include_strokes must be an array")
    if not polygons and not strokes:
        raise ValueError("mask control requires at least one include polygon or include stroke")
    return data


def _non_negative_integer(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _validated_include_polygons(control: dict[str, Any]) -> list[dict[str, Any]]:
    polygons = control.get("include_polygons", [])
    for polygon in polygons:
        points = polygon.get("points", [])
        if len(points) < 3:
            raise ValueError(f"include polygon {polygon.get('id')!r} requires at least three points")
        if "feather_inside_px" in polygon:
            _non_negative_integer(
                polygon["feather_inside_px"],
                f"include polygon {polygon.get('id')!r} feather_inside_px",
            )
    return polygons


def _draw_include_polygon(polygon: dict[str, Any], size: tuple[int, int]) -> Image.Image:
    binary = Image.new("L", size, 0)
    draw = ImageDraw.Draw(binary)
    points = [tuple(point) for point in polygon["points"]]
    draw.polygon(points, fill=255)
    return binary


def _draw_include_polygons(polygons: list[dict[str, Any]], size: tuple[int, int]) -> Image.Image:
    binary = Image.new("L", size, 0)
    draw = ImageDraw.Draw(binary)
    for polygon in polygons:
        draw.polygon([tuple(point) for point in polygon["points"]], fill=255)
    return binary


def _validated_include_strokes(control: dict[str, Any]) -> list[dict[str, Any]]:
    strokes = control.get("include_strokes", [])
    for stroke in strokes:
        points = stroke.get("points", [])
        width = stroke.get("width")
        if len(points) < 2 or not isinstance(width, int) or isinstance(width, bool) or width < 1:
            raise ValueError(f"include stroke {stroke.get('id')!r} is invalid")
        if "feather_inside_px" in stroke:
            _non_negative_integer(
                stroke["feather_inside_px"],
                f"include stroke {stroke.get('id')!r} feather_inside_px",
            )
    return strokes


def _draw_include_stroke(stroke: dict[str, Any], size: tuple[int, int]) -> Image.Image:
    binary = Image.new("L", size, 0)
    draw = ImageDraw.Draw(binary)
    points = [tuple(point) for point in stroke["points"]]
    width = stroke["width"]
    draw.line(points, fill=255, width=width, joint="curve")
    radius = width // 2
    for x, y in (points[0], points[-1]):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
    return binary


def _validated_exclude_strokes(control: dict[str, Any]) -> list[dict[str, Any]]:
    strokes = control.get("exclude_strokes", [])
    if not isinstance(strokes, list):
        raise ValueError("exclude_strokes must be an array")
    for stroke in strokes:
        points = [tuple(point) for point in stroke.get("points", [])]
        width = stroke.get("width")
        if len(points) < 2 or not isinstance(width, int) or isinstance(width, bool) or width < 1:
            raise ValueError(f"exclude stroke {stroke.get('id')!r} is invalid")
        if "feather_px" in stroke:
            _non_negative_integer(stroke["feather_px"], f"exclude stroke {stroke.get('id')!r} feather_px")
    return strokes


def _build_legacy_mask(
    include_binary: Image.Image,
    strokes: list[dict[str, Any]],
    radius: int,
) -> Image.Image:
    """Reproduce the pre-per-stroke algorithm exactly for old controls."""

    binary = include_binary.copy()
    draw = ImageDraw.Draw(binary)
    for stroke in strokes:
        points = [tuple(point) for point in stroke["points"]]
        draw.line(points, fill=0, width=stroke["width"], joint="curve")
    if radius == 0:
        return binary
    softened = binary.filter(ImageFilter.GaussianBlur(radius=radius))
    return ImageChops.darker(binary, softened)


def _feather_include_inside(include_binary: Image.Image, radius: int) -> Image.Image:
    if radius == 0:
        return include_binary
    softened = include_binary.filter(ImageFilter.GaussianBlur(radius=radius))
    return ImageChops.darker(include_binary, softened)


def _exclude_stroke(mask: Image.Image, stroke: dict[str, Any], radius: int) -> Image.Image:
    stroke_binary = Image.new("L", mask.size, 0)
    draw = ImageDraw.Draw(stroke_binary)
    points = [tuple(point) for point in stroke["points"]]
    draw.line(points, fill=255, width=stroke["width"], joint="curve")

    if radius == 0:
        protected = stroke_binary
    else:
        # The geometric stroke remains fully protected while the blurred copy
        # creates a controllable transition outside it.
        softened = stroke_binary.filter(ImageFilter.GaussianBlur(radius=radius))
        protected = ImageChops.lighter(stroke_binary, softened)
    return ImageChops.darker(mask, ImageOps.invert(protected))


def build_mask(control: dict[str, Any]) -> Image.Image:
    canvas = control["canvas"]
    size = (canvas["width"], canvas["height"])
    polygons = _validated_include_polygons(control)
    include_strokes = _validated_include_strokes(control)
    if not polygons and not include_strokes:
        raise ValueError("mask control requires at least one include polygon or include stroke")
    include_binary = _draw_include_polygons(polygons, size)
    strokes = _validated_exclude_strokes(control)
    radius = _non_negative_integer(control.get("feather_inside_px", 0), "feather_inside_px")
    has_polygon_feather = any("feather_inside_px" in polygon for polygon in polygons)

    # Controls created before per-stroke feathering must stay byte-for-byte
    # reproducible, including the way one Gaussian blur treated outer edges
    # and all excluded strokes as a single shape.
    if (
        not include_strokes
        and not has_polygon_feather
        and not any("feather_px" in stroke for stroke in strokes)
    ):
        return _build_legacy_mask(include_binary, strokes, radius)

    if has_polygon_feather or include_strokes:
        # Feather each independently configured region before taking their
        # alpha union. This prevents a narrow polygon or stroke from inheriting
        # the transition radius required by a much larger neighboring region.
        mask = Image.new("L", size, 0)
        for polygon in polygons:
            polygon_binary = _draw_include_polygon(polygon, size)
            polygon_radius = polygon.get("feather_inside_px", radius)
            polygon_mask = _feather_include_inside(polygon_binary, polygon_radius)
            mask = ImageChops.lighter(mask, polygon_mask)
        for stroke in include_strokes:
            stroke_binary = _draw_include_stroke(stroke, size)
            stroke_radius = stroke.get("feather_inside_px", radius)
            stroke_mask = _feather_include_inside(stroke_binary, stroke_radius)
            mask = ImageChops.lighter(mask, stroke_mask)
    else:
        mask = _feather_include_inside(include_binary, radius)
    for stroke in strokes:
        stroke_radius = stroke.get("feather_px", radius)
        mask = _exclude_stroke(mask, stroke, stroke_radius)
    return mask


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def composite(base_path: Path, edit_path: Path, control_path: Path, output_path: Path, mask_output: Path | None) -> dict[str, Any]:
    control = load_control(control_path)
    base = Image.open(base_path).convert("RGB")
    edit = Image.open(edit_path).convert("RGB")
    expected = (control["canvas"]["width"], control["canvas"]["height"])
    if base.size != expected or edit.size != expected:
        raise ValueError(f"base/edit dimensions must both equal control canvas {expected}")

    mask = build_mask(control)
    output = Image.composite(edit, base, mask)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.save(output_path, format="PNG", optimize=True)
    if mask_output is not None:
        mask_output.parent.mkdir(parents=True, exist_ok=True)
        mask.save(mask_output, format="PNG", optimize=True)

    protected = mask.point(lambda value: 255 if value == 0 else 0)
    outside_difference = ImageChops.difference(output, base)
    outside_difference = Image.composite(outside_difference, Image.new("RGB", expected), protected)
    outside_extrema = max(channel[1] for channel in outside_difference.getextrema())
    if outside_extrema != 0:
        raise RuntimeError("protected pixels changed outside the edit mask")

    histogram = mask.histogram()
    alpha_pixels = sum(histogram[1:])
    opaque_pixels = histogram[255]
    return {
        "schema_version": "1.0.0",
        "base_path": base_path.as_posix(),
        "edit_path": edit_path.as_posix(),
        "control_path": control_path.as_posix(),
        "output_path": output_path.as_posix(),
        "width": expected[0],
        "height": expected[1],
        "masked_pixels": alpha_pixels,
        "opaque_mask_pixels": opaque_pixels,
        "protected_pixels_verified": expected[0] * expected[1] - alpha_pixels,
        "outside_mask_max_channel_difference": outside_extrema,
        "output_sha256": sha256(output_path),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--base", required=True, type=Path)
    result.add_argument("--edit", required=True, type=Path)
    result.add_argument("--control", required=True, type=Path)
    result.add_argument("--output", required=True, type=Path)
    result.add_argument("--mask-output", type=Path)
    result.add_argument("--report", type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    report = composite(args.base, args.edit, args.control, args.output, args.mask_output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
