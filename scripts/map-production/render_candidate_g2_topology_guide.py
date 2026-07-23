#!/usr/bin/env python3
"""Render and preflight the smooth, fully in-canvas Candidate G2 guide."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTROL = (
    REPO_ROOT / "world/map-production/controls/style-candidate-g-v2-topology-guide.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "world/map-production/controls/style-candidate-g-v2-topology-guide.png"
)
EXPECTED_SHAPES = (
    ("ne-main-massif", "north_east_range", "main-massif"),
    ("ne-west-foothill", "north_east_range", "foothill-a"),
    ("ne-central-foothill", "north_east_range", "foothill-b"),
    ("se-main-massif", "south_east_range", "main-massif"),
    ("se-west-foothill", "south_east_range", "foothill-a"),
    ("se-east-foothill", "south_east_range", "foothill-b"),
)


class GuideError(ValueError):
    """Raised before publication when the G2 guide is invalid."""


@dataclass(frozen=True)
class PreparedShape:
    identifier: str
    rgb: tuple[int, int, int]
    points: tuple[tuple[int, int], ...]
    bounds: tuple[int, int, int, int]


def _rgb(value: object, label: str) -> tuple[int, int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(
            not isinstance(item, int) or isinstance(item, bool) or not 0 <= item <= 255
            for item in value
        )
    ):
        raise GuideError(f"{label} must be three RGB bytes")
    return value[0], value[1], value[2]


def sample_closed_catmull_rom(
    knots: Sequence[tuple[int, int]], samples_per_segment: int
) -> tuple[tuple[int, int], ...]:
    """Sample a closed uniform Catmull-Rom outline with deterministic rounding."""

    sampled: list[tuple[int, int]] = []
    count = len(knots)
    for index in range(count):
        p0 = knots[(index - 1) % count]
        p1 = knots[index]
        p2 = knots[(index + 1) % count]
        p3 = knots[(index + 2) % count]
        for sample_index in range(samples_per_segment):
            t = sample_index / samples_per_segment
            t2 = t * t
            t3 = t2 * t
            x = 0.5 * (
                2 * p1[0]
                + (-p0[0] + p2[0]) * t
                + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3
            )
            y = 0.5 * (
                2 * p1[1]
                + (-p0[1] + p2[1]) * t
                + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3
            )
            point = (round(x), round(y))
            if not sampled or sampled[-1] != point:
                sampled.append(point)
    if len(sampled) < 24:
        raise GuideError("a smooth closed outline requires at least 24 raster points")
    return tuple(sampled)


def _component_count(mask: Image.Image) -> int:
    width, height = mask.size
    pixels = mask.tobytes()
    visited = bytearray(len(pixels))
    components = 0
    for start, value in enumerate(pixels):
        if value == 0 or visited[start]:
            continue
        components += 1
        stack = [start]
        visited[start] = 1
        while stack:
            current = stack.pop()
            x = current % width
            for neighbor in (
                current - 1 if x else -1,
                current + 1 if x + 1 < width else -1,
                current - width if current >= width else -1,
                current + width if current < width * (height - 1) else -1,
            ):
                if neighbor >= 0 and pixels[neighbor] and not visited[neighbor]:
                    visited[neighbor] = 1
                    stack.append(neighbor)
    return components


def _axis_aligned_gap(
    left: tuple[int, int, int, int], right: tuple[int, int, int, int]
) -> int:
    horizontal = max(0, right[0] - left[2] - 1, left[0] - right[2] - 1)
    vertical = max(0, right[1] - left[3] - 1, left[1] - right[3] - 1)
    return max(horizontal, vertical)


def prepare(control: dict[str, Any]) -> tuple[list[PreparedShape], dict[str, Any]]:
    expected_root = {
        "schema_version",
        "id",
        "coordinate_space",
        "canvas",
        "background_rgb",
        "render_contract",
        "shapes",
        "purpose",
    }
    if set(control) != expected_root:
        raise GuideError("control root keys differ from the strict G2 contract")
    if control["schema_version"] != "2.0.0":
        raise GuideError("G2 guide schema_version must be 2.0.0")
    if control["coordinate_space"] != "source-pixels-y-down":
        raise GuideError("unsupported coordinate_space")
    if control["canvas"] != {"width": 1536, "height": 1024}:
        raise GuideError("Candidate G2 guide canvas must be exactly 1536x1024")
    _rgb(control["background_rgb"], "background_rgb")

    contract = control["render_contract"]
    if not isinstance(contract, dict) or set(contract) != {
        "curve",
        "samples_per_segment",
        "minimum_canvas_inset_px",
        "minimum_shape_gap_px",
    }:
        raise GuideError("render_contract keys differ from the strict G2 contract")
    if contract["curve"] != "closed-uniform-catmull-rom":
        raise GuideError("G2 guide requires closed-uniform-catmull-rom curves")
    samples = contract["samples_per_segment"]
    inset = contract["minimum_canvas_inset_px"]
    minimum_gap = contract["minimum_shape_gap_px"]
    if (
        not isinstance(samples, int)
        or isinstance(samples, bool)
        or not 8 <= samples <= 64
    ):
        raise GuideError("samples_per_segment must be an integer in 8..64")
    if inset != 64:
        raise GuideError("minimum_canvas_inset_px must be exactly 64")
    if (
        not isinstance(minimum_gap, int)
        or isinstance(minimum_gap, bool)
        or minimum_gap < 1
    ):
        raise GuideError("minimum_shape_gap_px must be a positive integer")

    shapes = control["shapes"]
    if not isinstance(shapes, list) or len(shapes) != len(EXPECTED_SHAPES):
        raise GuideError("Candidate G2 guide requires exactly six ordered shapes")

    width = control["canvas"]["width"]
    height = control["canvas"]["height"]
    prepared: list[PreparedShape] = []
    masks: list[Image.Image] = []
    try:
        for index, (shape, expected) in enumerate(zip(shapes, EXPECTED_SHAPES)):
            if not isinstance(shape, dict) or set(shape) != {
                "id",
                "region_id",
                "role",
                "rgb",
                "knots",
            }:
                raise GuideError(
                    f"shape {index} keys differ from the strict G2 contract"
                )
            identity = (shape["id"], shape["region_id"], shape["role"])
            if identity != expected:
                raise GuideError(
                    f"shape order/identity mismatch at index {index}: {identity!r}"
                )
            knots_raw = shape["knots"]
            if not isinstance(knots_raw, list) or len(knots_raw) < 8:
                raise GuideError(
                    f"shape {shape['id']} requires at least eight curve knots"
                )
            knots: list[tuple[int, int]] = []
            for point in knots_raw:
                if (
                    not isinstance(point, list)
                    or len(point) != 2
                    or any(
                        not isinstance(value, int) or isinstance(value, bool)
                        for value in point
                    )
                ):
                    raise GuideError(f"shape {shape['id']} has an invalid knot")
                knots.append((point[0], point[1]))
            points = sample_closed_catmull_rom(knots, samples)
            if any(
                x < inset
                or y < inset
                or x > width - inset - 1
                or y > height - inset - 1
                for x, y in points
            ):
                raise GuideError(
                    f"shape {shape['id']} violates the {inset}px canvas inset"
                )
            bounds = (
                min(point[0] for point in points),
                min(point[1] for point in points),
                max(point[0] for point in points),
                max(point[1] for point in points),
            )
            mask = Image.new("L", (width, height), 0)
            ImageDraw.Draw(mask).polygon(points, fill=255)
            cropped = mask.crop((bounds[0], bounds[1], bounds[2] + 1, bounds[3] + 1))
            try:
                component_count = _component_count(cropped)
            finally:
                cropped.close()
            if component_count != 1:
                mask.close()
                raise GuideError(
                    f"shape {shape['id']} is not one complete connected footprint"
                )
            for previous_mask, previous_shape in zip(masks, prepared):
                left_bytes = previous_mask.tobytes()
                right_bytes = mask.tobytes()
                overlap = any(
                    left and right for left, right in zip(left_bytes, right_bytes)
                )
                if overlap:
                    mask.close()
                    raise GuideError(
                        f"shapes {previous_shape.identifier} and {shape['id']} overlap"
                    )
                gap = _axis_aligned_gap(previous_shape.bounds, bounds)
                if gap < minimum_gap:
                    mask.close()
                    raise GuideError(
                        f"shapes {previous_shape.identifier} and {shape['id']} have only "
                        f"{gap}px axis-aligned gap; require {minimum_gap}px"
                    )
            prepared.append(
                PreparedShape(
                    shape["id"],
                    _rgb(shape["rgb"], f"{shape['id']}.rgb"),
                    points,
                    bounds,
                )
            )
            masks.append(mask)

        metrics = {
            "schema_version": control["schema_version"],
            "curve": contract["curve"],
            "shape_count": len(prepared),
            "samples_per_segment": samples,
            "minimum_canvas_inset_px": inset,
            "minimum_shape_gap_px": minimum_gap,
            "shapes": [
                {
                    "id": shape.identifier,
                    "bounds": list(shape.bounds),
                    "raster_points": len(shape.points),
                }
                for shape in prepared
            ],
        }
        return prepared, metrics
    finally:
        for mask in masks:
            mask.close()


def load_and_prepare(
    control_path: Path,
) -> tuple[dict[str, Any], list[PreparedShape], dict[str, Any]]:
    control = json.loads(control_path.read_text(encoding="utf-8"))
    if not isinstance(control, dict):
        raise GuideError("control root must be an object")
    prepared, metrics = prepare(control)
    return control, prepared, metrics


def render(control_path: Path, output_path: Path) -> dict[str, Any]:
    if output_path.exists():
        raise GuideError(f"refusing to overwrite existing output: {output_path}")
    control, shapes, metrics = load_and_prepare(control_path)
    image = Image.new(
        "RGB",
        (control["canvas"]["width"], control["canvas"]["height"]),
        _rgb(control["background_rgb"], "background_rgb"),
    )
    try:
        draw = ImageDraw.Draw(image)
        for shape in shapes:
            draw.polygon(shape.points, fill=shape.rgb)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, format="PNG", optimize=True)
    finally:
        image.close()
    return metrics


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", type=Path, default=DEFAULT_CONTROL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.preflight_only:
            _control, _shapes, metrics = load_and_prepare(args.control)
        else:
            metrics = render(args.control, args.output)
    except Exception as error:
        print(f"Candidate G2 topology guide failed: {error}")
        return 1
    print(json.dumps(metrics, ensure_ascii=False, sort_keys=True))
    if not args.preflight_only:
        print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
