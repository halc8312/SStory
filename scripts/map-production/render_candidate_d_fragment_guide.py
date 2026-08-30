#!/usr/bin/env python3
"""Render Candidate D's deterministic ridge-fragment control guide."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Any, Sequence

try:
    from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageOps
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Pillow is required: py -m pip install Pillow") from exc


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SPEC = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-d-ridge-fragment-guide-v2.json"
)
DEFAULT_OUTPUT = DEFAULT_SPEC.with_suffix(".png")
EXPECTED_SOURCE_PATH = "world/map-production/candidates/style-candidate-d-v2-flat-relief-bands.png"
EXPECTED_SOURCE_SHA256 = "c968d4422277c9d6ef4aea8186d220d100e741053e9fe658cee80fd3d9bc3cc7"
EXPECTED_TOPOLOGY_PATH = "world/map-production/controls/style-candidate-d-ridge-guide-v1.json"
EXPECTED_TOPOLOGY_SHA256 = "094f23f2a9515add9fccc6f52868d720ac53c40ca4985b804dd0da8a48062a13"
EXPECTED_REGION_IDS = ("north_east_range", "south_east_range")
EXPECTED_COLORS = {
    "paper_color": "#F5F2E5",
    "geometry_zone_color": "#00D4E8",
    "crest_fragment_zone_color": "#F500A8",
    "hatch_zone_color": "#9AEC00",
}
SCALE = 4


def _load_topology_module() -> Any:
    module_path = REPO_ROOT / "scripts/map-production/render_candidate_d_ridge_guide.py"
    module_spec = importlib.util.spec_from_file_location(
        "candidate_d_v1_topology_renderer", module_path
    )
    if module_spec is None or module_spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"cannot load v1 topology validator: {module_path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


TOPOLOGY = _load_topology_module()


class FragmentGuideError(ValueError):
    """Raised when the fragment-guide contract or output request is invalid."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _number(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise FragmentGuideError(f"{label} must be a finite number")
    return float(value)


def _points(value: Any, label: str, width: int, height: int) -> list[tuple[float, float]]:
    if not isinstance(value, list) or len(value) < 2:
        raise FragmentGuideError(f"{label} must contain at least two source-pixel points")
    result: list[tuple[float, float]] = []
    for index, point in enumerate(value):
        if not isinstance(point, list) or len(point) != 2:
            raise FragmentGuideError(f"{label}[{index}] is not an [x, y] point")
        x = _number(point[0], f"{label}[{index}][0]")
        y = _number(point[1], f"{label}[{index}][1]")
        if not (0 <= x < width and 0 <= y < height):
            raise FragmentGuideError(f"{label}[{index}] lies outside the canvas")
        result.append((x, y))
    return result


def path_length(points: Sequence[tuple[float, float]]) -> float:
    return sum(math.dist(first, second) for first, second in zip(points, points[1:]))


def point_at_distance(
    points: Sequence[tuple[float, float]], distance: float
) -> tuple[float, float]:
    remaining = max(0.0, distance)
    for first, second in zip(points, points[1:]):
        segment_length = math.dist(first, second)
        if remaining <= segment_length:
            if segment_length == 0:
                return first
            amount = remaining / segment_length
            return (
                first[0] + (second[0] - first[0]) * amount,
                first[1] + (second[1] - first[1]) * amount,
            )
        remaining -= segment_length
    return points[-1]


def subpath_between(
    points: Sequence[tuple[float, float]], start: float, end: float
) -> list[tuple[float, float]]:
    """Return the portion of a polyline between two arc-length offsets."""

    result = [point_at_distance(points, start)]
    travelled = 0.0
    for index, (first, second) in enumerate(zip(points, points[1:])):
        travelled += math.dist(first, second)
        if start < travelled < end:
            candidate = points[index + 1]
            if candidate != result[-1]:
                result.append(candidate)
    last = point_at_distance(points, end)
    if last != result[-1]:
        result.append(last)
    return result


def _validate_rendering(rendering: Any) -> None:
    if not isinstance(rendering, dict):
        raise FragmentGuideError("rendering must be an object")
    opacity = _number(rendering.get("parent_context_opacity"), "parent_context_opacity")
    if not (0 < opacity <= 0.12):
        raise FragmentGuideError("parent context must remain very faint (opacity <= 0.12)")
    if rendering.get("geometry_zone_outline_drawn") is not False:
        raise FragmentGuideError("cyan geometry zones must have no outline")
    if rendering.get("continuous_centerline_drawn") is not False:
        raise FragmentGuideError("a continuous centerline is forbidden")
    if rendering.get("labels_or_legend_baked_into_raster") is not False:
        raise FragmentGuideError("text and legends are forbidden")
    if rendering.get("render_primitive") != "soft-alpha-zones-only":
        raise FragmentGuideError("render_primitive must be soft-alpha-zones-only")
    for field, expected in EXPECTED_COLORS.items():
        if rendering.get(field) != expected:
            raise FragmentGuideError(f"{field} must remain {expected}")
        try:
            ImageColor.getrgb(expected)
        except ValueError as exc:  # pragma: no cover - constants are checked defensively
            raise FragmentGuideError(f"{field} is invalid") from exc
    for prefix in ("geometry_zone", "crest_fragment_zone", "hatch_zone"):
        try:
            ImageColor.getrgb(str(rendering[f"{prefix}_color"]))
        except (KeyError, ValueError) as exc:
            raise FragmentGuideError(f"{prefix}_color is invalid") from exc
        alpha = _number(rendering.get(f"{prefix}_opacity"), f"{prefix}_opacity")
        blur = _number(rendering.get(f"{prefix}_blur_radius_px"), f"{prefix}_blur_radius_px")
        if not (0 < alpha <= 1) or blur <= 0:
            raise FragmentGuideError(f"{prefix} must have positive opacity and blur")
    if _number(
        rendering.get("geometry_zone_blur_radius_px"), "geometry_zone_blur_radius_px"
    ) < 2:
        raise FragmentGuideError("cyan geometry-zone edges must remain visibly soft")
    crest_width = _number(
        rendering.get("crest_fragment_zone_width_px"),
        "crest_fragment_zone_width_px",
    )
    if not (4 <= crest_width <= 8):
        raise FragmentGuideError("crest-fragment zone width must be 4-8px")


def _validated_reference(
    reference: Any,
    *,
    label: str,
    expected_path: str,
    expected_hash: str,
) -> Path:
    if not isinstance(reference, dict):
        raise FragmentGuideError(f"{label} must be an object")
    if reference.get("path") != expected_path:
        raise FragmentGuideError(f"{label} path must remain {expected_path}")
    if reference.get("sha256") != expected_hash:
        raise FragmentGuideError(f"{label} SHA-256 must remain {expected_hash}")
    resolved = (REPO_ROOT / expected_path).resolve()
    if sha256_file(resolved) != expected_hash:
        raise FragmentGuideError(f"{label} file SHA-256 does not match the control")
    return resolved


def load_and_validate_spec(path: Path = DEFAULT_SPEC) -> dict[str, Any]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if spec.get("schema_version") != "2.0.0":
        raise FragmentGuideError("schema_version must be 2.0.0")
    if spec.get("id") != "style-candidate-d-ridge-fragment-guide-v2":
        raise FragmentGuideError("unexpected fragment-guide id")
    if spec.get("coordinate_space") != "source-pixels-y-down":
        raise FragmentGuideError("coordinate_space must be source-pixels-y-down")
    if spec.get("canvas") != {"width": 1536, "height": 1024}:
        raise FragmentGuideError("Candidate D fragment guide canvas must be exactly 1536x1024")
    width, height = 1536, 1024

    source_path = _validated_reference(
        spec.get("source_context"),
        label="source context",
        expected_path=EXPECTED_SOURCE_PATH,
        expected_hash=EXPECTED_SOURCE_SHA256,
    )
    with Image.open(source_path) as source:
        if source.size != (width, height):
            raise FragmentGuideError("source context dimensions must be exactly 1536x1024")

    topology_path = _validated_reference(
        spec.get("topology_control"),
        label="v1 topology control",
        expected_path=EXPECTED_TOPOLOGY_PATH,
        expected_hash=EXPECTED_TOPOLOGY_SHA256,
    )
    try:
        topology = TOPOLOGY.load_and_validate_spec(topology_path)
    except (OSError, json.JSONDecodeError, TOPOLOGY.RidgeGuideError) as exc:
        raise FragmentGuideError(f"v1 topology control is invalid: {exc}") from exc

    constraints = spec.get("constraints")
    if not isinstance(constraints, dict):
        raise FragmentGuideError("constraints must be an object")
    if constraints.get("ridge_count") != 10:
        raise FragmentGuideError("ridge_count must be exactly ten")
    if constraints.get("ridges_per_region") != 5:
        raise FragmentGuideError("each region must contain exactly five ridges")
    if constraints.get("crest_fragment_zones_per_ridge") != 3:
        raise FragmentGuideError("each ridge must contain exactly three crest-fragment zones")
    if constraints.get("detached_hatch_zones_per_ridge") != 1:
        raise FragmentGuideError("each ridge must contain exactly one detached hatch zone")
    if constraints.get("ridge_geometry_width_px") != [37, 43]:
        raise FragmentGuideError("ridge_geometry_width_px must remain [37, 43]")
    length_range = constraints.get("crest_fragment_length_px")
    if length_range != [12, 24]:
        raise FragmentGuideError("crest_fragment_length_px must remain [12, 24]")
    minimum_gap = _number(
        constraints.get("minimum_crest_fragment_gap_px"),
        "minimum_crest_fragment_gap_px",
    )
    if minimum_gap < 24:
        raise FragmentGuideError("crest-fragment gaps must be at least 24px")
    if constraints.get("minimum_road_clearance_px") != topology["constraints"].get(
        "minimum_road_clearance_px"
    ):
        raise FragmentGuideError("minimum road clearance must exactly match the v1 topology")
    _validate_rendering(spec.get("rendering"))

    topology_regions = topology["regions"]
    regions = spec.get("regions")
    if not isinstance(regions, list) or [item.get("id") for item in regions] != list(
        EXPECTED_REGION_IDS
    ):
        raise FragmentGuideError("north-east then south-east fragment regions are required")

    total_ridges = 0
    for region, topology_region in zip(regions, topology_regions):
        if region.get("id") != topology_region.get("id"):
            raise FragmentGuideError("fragment region order must exactly match the v1 topology")
        ridge_controls = region.get("ridge_controls")
        topology_ridges = topology_region.get("ridge_chains")
        if not isinstance(ridge_controls, list) or len(ridge_controls) != 5:
            raise FragmentGuideError(f"{region.get('id')} must contain exactly five ridges")
        if [item.get("id") for item in ridge_controls] != [
            item.get("id") for item in topology_ridges
        ]:
            raise FragmentGuideError(f"{region.get('id')} ridge ids/order must match v1")

        for ridge, topology_ridge in zip(ridge_controls, topology_ridges):
            ridge_id = str(ridge.get("id"))
            geometry = ridge.get("geometry_zone")
            if not isinstance(geometry, dict):
                raise FragmentGuideError(f"{ridge_id} geometry_zone must be an object")
            if geometry.get("path_role") != "soft-no-outline-cyan-geometry-zone":
                raise FragmentGuideError(f"{ridge_id} has the wrong geometry-zone role")
            if geometry.get("source_pixels_path") != topology_ridge.get("source_pixels_path"):
                raise FragmentGuideError(f"{ridge_id} path must exactly match the v1 topology")
            if geometry.get("width_px") != topology_ridge.get("width_px"):
                raise FragmentGuideError(f"{ridge_id} width must exactly match the v1 topology")
            ridge_width = _number(geometry.get("width_px"), f"{ridge_id} width_px")
            if not (37 <= ridge_width <= 43):
                raise FragmentGuideError(f"{ridge_id} must remain an approximately 40px zone")
            center = _points(
                geometry.get("source_pixels_path"), f"{ridge_id} geometry path", width, height
            )
            center_length = path_length(center)

            fragments = ridge.get("crest_fragment_zones")
            if not isinstance(fragments, list) or len(fragments) != 3:
                raise FragmentGuideError(
                    f"{ridge_id} must contain exactly three crest-fragment zones"
                )
            intervals: list[tuple[float, float]] = []
            fragment_ids: set[str] = set()
            for fragment in fragments:
                fragment_id = str(fragment.get("id"))
                if fragment_id in fragment_ids:
                    raise FragmentGuideError(f"{ridge_id} crest-fragment ids must be unique")
                fragment_ids.add(fragment_id)
                if fragment.get("path_role") != "detached-magenta-crest-fragment-zone":
                    raise FragmentGuideError(f"{fragment_id} has the wrong path role")
                start_fraction = _number(
                    fragment.get("start_fraction"), f"{fragment_id} start_fraction"
                )
                fragment_length = _number(fragment.get("length_px"), f"{fragment_id} length_px")
                if not (0 <= start_fraction < 1):
                    raise FragmentGuideError(f"{fragment_id} start_fraction lies outside its ridge")
                if not (12 <= fragment_length <= 24):
                    raise FragmentGuideError(f"{fragment_id} length must be 12-24px")
                start = start_fraction * center_length
                end = start + fragment_length
                if end > center_length:
                    raise FragmentGuideError(f"{fragment_id} extends beyond its ridge")
                intervals.append((start, end))

            if intervals != sorted(intervals):
                raise FragmentGuideError(f"{ridge_id} crest-fragment zones must be ordered")
            for first, second in zip(intervals, intervals[1:]):
                arc_gap = second[0] - first[1]
                visible_gap = math.dist(
                    point_at_distance(center, first[1]),
                    point_at_distance(center, second[0]),
                )
                if arc_gap < minimum_gap or visible_gap < minimum_gap:
                    raise FragmentGuideError(
                        f"{ridge_id} crest-fragment gap must be at least {minimum_gap:g}px"
                    )

            hatches = ridge.get("hatch_zones")
            if not isinstance(hatches, list) or len(hatches) != 1:
                raise FragmentGuideError(
                    f"{ridge_id} must contain exactly one detached hatch zone"
                )
            hatch = hatches[0]
            if hatch.get("path_role") != "detached-lime-hatch-zone":
                raise FragmentGuideError(f"{ridge_id} has the wrong hatch-zone role")
            topology_hatches = topology_ridge.get("hatches")
            if not isinstance(topology_hatches, list) or len(topology_hatches) != 1:
                raise FragmentGuideError(f"{ridge_id} v1 topology must contain one hatch")
            if hatch.get("source_pixels_path") != topology_hatches[0].get("source_pixels_path"):
                raise FragmentGuideError(f"{ridge_id} hatch path must exactly match the v1 topology")
            hatch_width = _number(hatch.get("width_px"), f"{ridge_id} hatch width_px")
            if not (3 <= hatch_width <= 6):
                raise FragmentGuideError(f"{ridge_id} hatch zone width must be 3-6px")
            hatch_path = _points(
                hatch.get("source_pixels_path"), f"{ridge_id} hatch path", width, height
            )
            edge_gap = (
                TOPOLOGY.polyline_distance(center, hatch_path)
                - ridge_width / 2
                - hatch_width / 2
            )
            if edge_gap <= 2:
                raise FragmentGuideError(f"{ridge_id} lime hatch zone is not visibly detached")
            total_ridges += 1

    if total_ridges != 10:
        raise FragmentGuideError("fragment guide must contain exactly ten ridges")
    return spec


def _scaled(points: Sequence[tuple[float, float]]) -> list[tuple[int, int]]:
    return [(round(x * SCALE), round(y * SCALE)) for x, y in points]


def _rounded_line(
    draw: ImageDraw.ImageDraw,
    points: Sequence[tuple[float, float]],
    width_px: float,
) -> None:
    scaled = _scaled(points)
    line_width = max(1, round(width_px * SCALE))
    draw.line(scaled, fill=255, width=line_width, joint="curve")
    radius = line_width / 2
    for x, y in (scaled[0], scaled[-1]):
        draw.ellipse(
            (round(x - radius), round(y - radius), round(x + radius), round(y + radius)),
            fill=255,
        )


def _soft_mask(mask: Image.Image, blur_radius_px: float, size: tuple[int, int]) -> Image.Image:
    blurred = mask.filter(ImageFilter.GaussianBlur(radius=blur_radius_px * SCALE))
    return blurred.resize(size, Image.Resampling.LANCZOS)


def _color_layer(
    mask: Image.Image, color: str, opacity: float, size: tuple[int, int]
) -> Image.Image:
    rgb = ImageColor.getrgb(color)
    alpha_lut = [round(value * opacity) for value in range(256)]
    alpha = mask.point(alpha_lut)
    layer = Image.new("RGBA", size, rgb + (0,))
    layer.putalpha(alpha)
    alpha.close()
    return layer


def render_guide(spec_path: Path = DEFAULT_SPEC, output_path: Path = DEFAULT_OUTPUT) -> Path:
    spec_path = spec_path.resolve()
    output_path = output_path.resolve()
    spec = load_and_validate_spec(spec_path)
    if output_path.exists():
        raise FragmentGuideError(f"refusing to overwrite existing output: {output_path}")

    width, height = spec["canvas"]["width"], spec["canvas"]["height"]
    size = (width, height)
    source_path = (REPO_ROOT / spec["source_context"]["path"]).resolve()
    with Image.open(source_path) as opened:
        source = ImageOps.exif_transpose(opened).convert("RGB")
        gray = ImageOps.grayscale(source).convert("RGB")
        paper = Image.new("RGB", size, ImageColor.getrgb(spec["rendering"]["paper_color"]))
        base = Image.blend(
            paper, gray, float(spec["rendering"]["parent_context_opacity"])
        ).convert("RGBA")
        paper.close()
        gray.close()
        source.close()

    scaled_size = (width * SCALE, height * SCALE)
    geometry_mask = Image.new("L", scaled_size, 0)
    crest_mask = Image.new("L", scaled_size, 0)
    hatch_mask = Image.new("L", scaled_size, 0)
    geometry_draw = ImageDraw.Draw(geometry_mask)
    crest_draw = ImageDraw.Draw(crest_mask)
    hatch_draw = ImageDraw.Draw(hatch_mask)
    crest_width = float(spec["rendering"]["crest_fragment_zone_width_px"])

    for region in spec["regions"]:
        for ridge in region["ridge_controls"]:
            geometry = ridge["geometry_zone"]
            center = [tuple(map(float, point)) for point in geometry["source_pixels_path"]]
            center_length = path_length(center)
            _rounded_line(geometry_draw, center, float(geometry["width_px"]))
            for fragment in ridge["crest_fragment_zones"]:
                start = float(fragment["start_fraction"]) * center_length
                end = start + float(fragment["length_px"])
                _rounded_line(crest_draw, subpath_between(center, start, end), crest_width)
            hatch = ridge["hatch_zones"][0]
            hatch_points = [tuple(map(float, point)) for point in hatch["source_pixels_path"]]
            _rounded_line(hatch_draw, hatch_points, float(hatch["width_px"]))

    rendering = spec["rendering"]
    masks_and_prefixes = (
        (geometry_mask, "geometry_zone"),
        (crest_mask, "crest_fragment_zone"),
        (hatch_mask, "hatch_zone"),
    )
    result = base
    for high_res_mask, prefix in masks_and_prefixes:
        softened = _soft_mask(
            high_res_mask, float(rendering[f"{prefix}_blur_radius_px"]), size
        )
        layer = _color_layer(
            softened,
            str(rendering[f"{prefix}_color"]),
            float(rendering[f"{prefix}_opacity"]),
            size,
        )
        composited = Image.alpha_composite(result, layer)
        if result is not base:
            result.close()
        result = composited
        layer.close()
        softened.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rgb_result = result.convert("RGB")
    rgb_result.save(output_path, format="PNG", compress_level=9, optimize=False)
    rgb_result.close()
    result.close()
    base.close()
    geometry_mask.close()
    crest_mask.close()
    hatch_mask.close()
    return output_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        output = render_guide(args.spec, args.output)
    except (OSError, json.JSONDecodeError, FragmentGuideError) as exc:
        print(f"fragment guide render failed: {exc}")
        return 1
    print(f"fragment guide rendered: {output} sha256={sha256_file(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
