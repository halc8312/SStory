#!/usr/bin/env python3
"""Render Candidate D's deterministic disconnected-ridge topology guide."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

try:
    from PIL import Image, ImageColor, ImageDraw, ImageOps
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Pillow is required: py -m pip install Pillow") from exc


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SPEC = REPO_ROOT / "world/map-production/controls/style-candidate-d-ridge-guide-v1.json"
DEFAULT_OUTPUT = DEFAULT_SPEC.with_suffix(".png")
SCALE = 3


class RidgeGuideError(ValueError):
    """Raised when the guide contract or output request is invalid."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path(value: Any, label: str, width: int, height: int) -> list[tuple[float, float]]:
    if not isinstance(value, list) or len(value) < 2:
        raise RidgeGuideError(f"{label} must contain at least two source-pixel points")
    result: list[tuple[float, float]] = []
    for index, point in enumerate(value):
        if not (
            isinstance(point, list)
            and len(point) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in point)
        ):
            raise RidgeGuideError(f"{label}[{index}] is not an [x, y] point")
        x, y = float(point[0]), float(point[1])
        if not (0 <= x < width and 0 <= y < height):
            raise RidgeGuideError(f"{label}[{index}] lies outside the canvas")
        result.append((x, y))
    return result


def path_length(points: Sequence[tuple[float, float]]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def _point_segment_distance(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    if dx == dy == 0:
        return math.dist(point, start)
    amount = max(
        0.0,
        min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (dx * dx + dy * dy)),
    )
    projection = start[0] + amount * dx, start[1] + amount * dy
    return math.dist(point, projection)


def _orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]
) -> bool:
    return (
        _orientation(a, b, c) * _orientation(a, b, d) <= 0
        and _orientation(c, d, a) * _orientation(c, d, b) <= 0
        and max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0]))
        and max(min(a[1], b[1]), min(c[1], d[1])) <= min(max(a[1], b[1]), max(c[1], d[1]))
    )


def segment_distance(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]
) -> float:
    if _segments_intersect(a, b, c, d):
        return 0.0
    return min(
        _point_segment_distance(a, c, d),
        _point_segment_distance(b, c, d),
        _point_segment_distance(c, a, b),
        _point_segment_distance(d, a, b),
    )


def polyline_distance(
    first: Sequence[tuple[float, float]], second: Sequence[tuple[float, float]]
) -> float:
    return min(
        segment_distance(a, b, c, d)
        for a, b in zip(first, first[1:])
        for c, d in zip(second, second[1:])
    )


def load_and_validate_spec(path: Path = DEFAULT_SPEC) -> dict[str, Any]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if spec.get("coordinate_space") != "source-pixels-y-down":
        raise RidgeGuideError("coordinate_space must be source-pixels-y-down")
    canvas = spec.get("canvas", {})
    if canvas != {"width": 1536, "height": 1024}:
        raise RidgeGuideError("Candidate D guide canvas must be exactly 1536x1024")
    width, height = canvas["width"], canvas["height"]
    constraints = spec.get("constraints", {})
    expected_count = constraints.get("ridge_chains_per_region")
    if expected_count != 5:
        raise RidgeGuideError("each Candidate D mountain region must contain five ridges")
    regions = spec.get("regions")
    if not isinstance(regions, list) or {region.get("id") for region in regions} != {
        "north_east_range",
        "south_east_range",
    }:
        raise RidgeGuideError("north-east and south-east regions are required")

    roads: list[tuple[list[tuple[float, float]], float]] = []
    for road in spec.get("road_avoidance", {}).get("corridors", []):
        roads.append(
            (
                _path(road.get("source_pixels_path"), f"road {road.get('id')}", width, height),
                float(road.get("width_px", 0)),
            )
        )
    if len(roads) != 2:
        raise RidgeGuideError("the east and south-east road corridors are required")

    minimum_clearance = float(constraints.get("minimum_road_clearance_px", 20))
    minimum_gap = float(constraints.get("minimum_chain_gap_px", 24))
    maximum_length = float(constraints.get("maximum_chain_length_px", 240))
    all_ridges: list[tuple[str, list[tuple[float, float]], float]] = []
    for region in regions:
        ridges = region.get("ridge_chains")
        if not isinstance(ridges, list) or len(ridges) != expected_count:
            raise RidgeGuideError(f"{region.get('id')} must contain exactly five ridges")
        for ridge in ridges:
            ridge_id = str(ridge.get("id"))
            if ridge.get("path_role") != "independent-wide-short-ridge-centerline":
                raise RidgeGuideError(f"{ridge_id} has the wrong path role")
            center = _path(ridge.get("source_pixels_path"), ridge_id, width, height)
            ridge_width = float(ridge.get("width_px", 0))
            length = path_length(center)
            if not (90 <= length <= maximum_length):
                raise RidgeGuideError(f"{ridge_id} is not a short ridge chain: {length:.1f}px")
            if math.dist(center[0], center[-1]) < 48:
                raise RidgeGuideError(f"{ridge_id} endpoints are too close; loop-like topology refused")
            hatches = ridge.get("hatches")
            if not isinstance(hatches, list) or not (1 <= len(hatches) <= 2):
                raise RidgeGuideError(f"{ridge_id} must have only one or two short hatches")
            for hatch in hatches:
                hatch_path = _path(hatch.get("source_pixels_path"), f"{ridge_id} hatch", width, height)
                if hatch.get("path_role") != "detached-one-sided-short-hatch" or path_length(hatch_path) > 18:
                    raise RidgeGuideError(f"{ridge_id} has an invalid hatch")
                band_gap = polyline_distance(hatch_path, center) - ridge_width / 2
                if not (4 <= band_gap <= 8):
                    raise RidgeGuideError(
                        f"{ridge_id} hatch must remain 4-8px clear of its ridge band; got {band_gap:.1f}px"
                    )
                for road, road_width in roads:
                    required = minimum_clearance + road_width / 2
                    if polyline_distance(hatch_path, road) < required:
                        raise RidgeGuideError(f"{ridge_id} hatch violates road clearance")
            for road, road_width in roads:
                required = minimum_clearance + road_width / 2 + ridge_width / 2
                if polyline_distance(center, road) < required:
                    raise RidgeGuideError(f"{ridge_id} violates road clearance")
            all_ridges.append((ridge_id, center, ridge_width))

    for index, (first_id, first, first_width) in enumerate(all_ridges):
        for second_id, second, second_width in all_ridges[index + 1 :]:
            required = minimum_gap + first_width / 2 + second_width / 2
            if polyline_distance(first, second) < required:
                raise RidgeGuideError(f"{first_id} and {second_id} are not disconnected")
    return spec


def _scaled(points: Sequence[Sequence[float]]) -> list[tuple[int, int]]:
    return [(round(point[0] * SCALE), round(point[1] * SCALE)) for point in points]


def _rounded_line(draw: ImageDraw.ImageDraw, points: list[tuple[int, int]], fill: str, width: int) -> None:
    draw.line(points, fill=fill, width=width, joint="curve")
    radius = width // 2
    for x, y in (points[0], points[-1]):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)


def _variable_band(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[int, int]],
    outline: tuple[int, int, int, int],
    band: tuple[int, int, int, int],
    width: int,
    variation: int,
) -> None:
    widths = [width + ((index * 5 + 1) % (variation * 2 + 1) - variation) for index in range(len(points) - 1)]
    for index, (start, end) in enumerate(zip(points, points[1:])):
        _rounded_line(draw, [start, end], outline, (widths[index] + 4) * SCALE)
    for index, (start, end) in enumerate(zip(points, points[1:])):
        _rounded_line(draw, [start, end], band, widths[index] * SCALE)


def render_guide(
    spec_path: Path = DEFAULT_SPEC,
    output_path: Path = DEFAULT_OUTPUT,
    *,
    force: bool = False,
) -> Path:
    spec_path = spec_path.resolve()
    output_path = output_path.resolve()
    spec = load_and_validate_spec(spec_path)
    if output_path.exists() and not force:
        raise RidgeGuideError(f"refusing to overwrite existing output: {output_path}")
    source_path = (REPO_ROOT / spec["source_image"]["path"]).resolve()
    if sha256_file(source_path) != spec["source_image"]["sha256"]:
        raise RidgeGuideError("source image SHA-256 does not match the guide specification")
    width, height = spec["canvas"]["width"], spec["canvas"]["height"]
    with Image.open(source_path) as opened:
        source = ImageOps.exif_transpose(opened).convert("RGB")
        if source.size != (width, height):
            raise RidgeGuideError("source image dimensions do not match the guide canvas")
        gray = ImageOps.grayscale(source).convert("RGB")
        paper = Image.new("RGB", source.size, (244, 242, 229))
        base = Image.blend(paper, gray, float(spec["rendering"]["parent_map_opacity"]))

    overlay = Image.new("RGBA", (width * SCALE, height * SCALE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    outline_alpha = round(float(spec["rendering"]["ridge_outline_opacity"]) * 255)
    band_alpha = round(float(spec["rendering"]["ridge_band_opacity"]) * 255)
    outline = ImageColor.getrgb(spec["rendering"]["ridge_outline_color"]) + (outline_alpha,)
    band = ImageColor.getrgb(spec["rendering"]["ridge_band_color"]) + (band_alpha,)
    hatch = ImageColor.getrgb(spec["rendering"]["hatch_color"]) + (band_alpha,)
    variation = int(spec["rendering"]["ridge_width_variation_px"])
    for region in spec["regions"]:
        for ridge in region["ridge_chains"]:
            points = _scaled(ridge["source_pixels_path"])
            ridge_width = int(ridge["width_px"])
            _variable_band(draw, points, outline, band, ridge_width, variation)
            for item in ridge["hatches"]:
                hatch_points = _scaled(item["source_pixels_path"])
                _rounded_line(draw, hatch_points, outline, 6 * SCALE)
                _rounded_line(draw, hatch_points, hatch, 4 * SCALE)
    overlay = overlay.resize((width, height), Image.Resampling.LANCZOS)
    result = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(output_path, format="PNG", compress_level=9, optimize=False)
    overlay.close()
    base.close()
    result.close()
    return output_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        output = render_guide(args.spec, args.output, force=args.force)
    except (OSError, json.JSONDecodeError, RidgeGuideError) as exc:
        print(f"ridge guide render failed: {exc}")
        return 1
    print(f"ridge guide rendered: {output} sha256={sha256_file(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
