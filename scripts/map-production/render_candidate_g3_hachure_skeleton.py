#!/usr/bin/env python3
"""Render and fail-closed preflight the Candidate G3 hachure skeleton."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTROL = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-g-v3-hachure-skeleton.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-g-v3-hachure-skeleton.png"
)
EXPECTED_LANDFORMS = (
    ("ne-main-massif", "north_east_range", "main-massif", (206, 74, 62)),
    ("ne-west-foothill", "north_east_range", "foothill-a", (232, 151, 61)),
    ("ne-central-foothill", "north_east_range", "foothill-b", (126, 93, 178)),
    ("se-main-massif", "south_east_range", "main-massif", (206, 74, 62)),
    ("se-west-foothill", "south_east_range", "foothill-a", (232, 151, 61)),
    ("se-east-foothill", "south_east_range", "foothill-b", (126, 93, 178)),
)


class SkeletonError(ValueError):
    """Raised before a G3 skeleton is accepted or published."""


@dataclass(frozen=True)
class PreparedLandform:
    identifier: str
    role: str
    groups: tuple[tuple[str, tuple[tuple[tuple[int, int], ...], ...]], ...]
    saddle_clear_box: tuple[int, int, int, int] | None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_repo_path(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise SkeletonError(f"{label} must be a nonempty POSIX repo-relative path")
    candidate = Path(value)
    if candidate.is_absolute():
        raise SkeletonError(f"{label} must be repo-relative")
    resolved = (REPO_ROOT / candidate).resolve()
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError as error:
        raise SkeletonError(f"{label} escapes the repository") from error
    return resolved


def _locked_path(reference: dict[str, Any], key: str, label: str) -> Path:
    path = _resolve_repo_path(reference[key], f"{label}.{key}")
    expected = reference[f"{key.removesuffix('_path')}_sha256"]
    if not path.is_file():
        raise SkeletonError(f"{label} is missing: {path}")
    if _sha256(path) != expected:
        raise SkeletonError(f"{label} SHA-256 mismatch")
    return path


def _rgb(value: object, label: str) -> tuple[int, int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(
            not isinstance(item, int)
            or isinstance(item, bool)
            or not 0 <= item <= 255
            for item in value
        )
    ):
        raise SkeletonError(f"{label} must be three RGB bytes")
    return value[0], value[1], value[2]


def _point(value: object, size: tuple[int, int], label: str) -> tuple[int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(not isinstance(item, int) or isinstance(item, bool) for item in value)
    ):
        raise SkeletonError(f"{label} must be an integer [x, y] point")
    point = value[0], value[1]
    if not 0 <= point[0] < size[0] or not 0 <= point[1] < size[1]:
        raise SkeletonError(f"{label} is outside the canvas")
    return point


def _polyline_length(points: Sequence[tuple[int, int]]) -> float:
    return sum(
        math.hypot(right[0] - left[0], right[1] - left[1])
        for left, right in zip(points, points[1:])
    )


def _orientation_bin(
    points: Sequence[tuple[int, int]], bin_degrees: int
) -> int:
    start = points[0]
    end = points[-1]
    angle = math.degrees(math.atan2(end[1] - start[1], end[0] - start[0])) % 180
    return int(angle // bin_degrees)


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
            y = current // width
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx = x + dx
                    ny = y + dy
                    if not 0 <= nx < width or not 0 <= ny < height:
                        continue
                    neighbor = ny * width + nx
                    if pixels[neighbor] and not visited[neighbor]:
                        visited[neighbor] = 1
                        stack.append(neighbor)
    return components


def _radial_alignment_fraction(
    segments: Sequence[tuple[tuple[int, int], ...]],
) -> float:
    midpoints = [
        (
            (points[0][0] + points[-1][0]) / 2,
            (points[0][1] + points[-1][1]) / 2,
        )
        for points in segments
    ]
    center_x = sum(point[0] for point in midpoints) / len(midpoints)
    center_y = sum(point[1] for point in midpoints) / len(midpoints)
    aligned = 0
    for points, midpoint in zip(segments, midpoints):
        direction_x = points[-1][0] - points[0][0]
        direction_y = points[-1][1] - points[0][1]
        radial_x = midpoint[0] - center_x
        radial_y = midpoint[1] - center_y
        denominator = math.hypot(direction_x, direction_y) * math.hypot(
            radial_x, radial_y
        )
        cosine = (
            abs((direction_x * radial_x + direction_y * radial_y) / denominator)
            if denominator
            else 0
        )
        if cosine >= 0.9:
            aligned += 1
    return aligned / len(segments)


def _normalized_template(mask: Image.Image, size: int) -> bytes:
    bounds = mask.getbbox()
    if bounds is None:
        raise SkeletonError("cannot normalize an empty landform skeleton")
    cropped = mask.crop(bounds)
    resized: Image.Image | None = None
    try:
        resized = cropped.resize((size, size), resample=Image.Resampling.NEAREST)
        return bytes(255 if value else 0 for value in resized.tobytes())
    finally:
        cropped.close()
        if resized is not None:
            resized.close()


def _load_footprint_reference(
    control: dict[str, Any], size: tuple[int, int]
) -> tuple[Image.Image, dict[str, Any]]:
    reference = control["footprint_reference"]
    if not isinstance(reference, dict) or set(reference) != {
        "source_path",
        "source_sha256",
        "raster_path",
        "raster_sha256",
    }:
        raise SkeletonError("footprint_reference differs from the strict contract")
    source_path = _locked_path(reference, "source_path", "footprint source")
    raster_path = _locked_path(reference, "raster_path", "footprint raster")
    try:
        source = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SkeletonError("cannot decode the footprint source") from error
    if not isinstance(source, dict):
        raise SkeletonError("footprint source root must be an object")
    if source.get("schema_version") != "2.0.0":
        raise SkeletonError("footprint source must be the G2 2.0.0 guide")
    if source.get("canvas") != {"width": size[0], "height": size[1]}:
        raise SkeletonError("footprint source canvas differs from the skeleton")
    shapes = source.get("shapes")
    if not isinstance(shapes, list) or len(shapes) != len(EXPECTED_LANDFORMS):
        raise SkeletonError("footprint source must contain six ordered G2 shapes")
    for index, (shape, expected) in enumerate(zip(shapes, EXPECTED_LANDFORMS)):
        if not isinstance(shape, dict):
            raise SkeletonError(f"footprint shape {index} must be an object")
        identity = (
            shape.get("id"),
            shape.get("region_id"),
            shape.get("role"),
            tuple(shape.get("rgb", ())),
        )
        if identity != expected:
            raise SkeletonError(
                f"footprint shape order/identity mismatch at index {index}: {identity!r}"
            )
    try:
        with Image.open(raster_path) as opened:
            opened.load()
            if opened.format != "PNG":
                raise SkeletonError("footprint raster format must be PNG")
            if opened.mode != "RGB":
                raise SkeletonError("footprint raster mode must be RGB")
            if opened.size != size:
                raise SkeletonError("footprint raster dimensions differ from the skeleton")
            return opened.copy(), {
                "source_path": source_path.relative_to(REPO_ROOT).as_posix(),
                "source_sha256": _sha256(source_path),
                "raster_path": raster_path.relative_to(REPO_ROOT).as_posix(),
                "raster_sha256": _sha256(raster_path),
            }
    except SkeletonError:
        raise
    except (OSError, ValueError) as error:
        raise SkeletonError("cannot decode the footprint raster") from error


def prepare(
    control: dict[str, Any],
) -> tuple[list[PreparedLandform], dict[str, Any], Image.Image]:
    expected_root = {
        "schema_version",
        "id",
        "coordinate_space",
        "canvas",
        "footprint_reference",
        "render_contract",
        "landforms",
        "purpose",
    }
    if set(control) != expected_root:
        raise SkeletonError("control root keys differ from the strict G3 contract")
    if control["schema_version"] != "1.0.0":
        raise SkeletonError("G3 skeleton schema_version must be 1.0.0")
    if control["coordinate_space"] != "source-pixels-y-down":
        raise SkeletonError("unsupported coordinate_space")
    if control["canvas"] != {"width": 1536, "height": 1024}:
        raise SkeletonError("Candidate G3 skeleton canvas must be exactly 1536x1024")
    if not isinstance(control["purpose"], str) or not control["purpose"].strip():
        raise SkeletonError("purpose must be a nonempty string")
    size = (1536, 1024)

    contract = control["render_contract"]
    expected_contract = {
        "background_rgb",
        "stroke_rgb",
        "stroke_width_px",
        "minimum_segment_length_px",
        "maximum_segment_length_px",
        "minimum_unique_lengths_per_landform",
        "minimum_orientation_bins_per_landform",
        "orientation_bin_degrees",
        "minimum_ink_pixels_per_landform",
        "minimum_saddle_clearance_px",
        "minimum_main_rise_segment_count_delta",
        "maximum_radial_alignment_fraction",
        "normalized_template_size_px",
        "maximum_normalized_template_iou",
        "require_disconnected_segments",
        "require_distinct_foothill_segment_counts",
    }
    if not isinstance(contract, dict) or set(contract) != expected_contract:
        raise SkeletonError("render_contract keys differ from the strict G3 contract")
    background = _rgb(contract["background_rgb"], "background_rgb")
    stroke = _rgb(contract["stroke_rgb"], "stroke_rgb")
    if background == stroke:
        raise SkeletonError("background and stroke colors must differ")
    integer_contract = {
        "stroke_width_px": (1, 5),
        "minimum_segment_length_px": (8, 42),
        "maximum_segment_length_px": (18, 48),
        "minimum_unique_lengths_per_landform": (3, 12),
        "minimum_orientation_bins_per_landform": (3, 12),
        "orientation_bin_degrees": (10, 30),
        "minimum_ink_pixels_per_landform": (100, 5000),
        "minimum_saddle_clearance_px": (16, 96),
        "minimum_main_rise_segment_count_delta": (1, 12),
        "normalized_template_size_px": (32, 128),
    }
    for key, (minimum, maximum) in integer_contract.items():
        value = contract[key]
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not minimum <= value <= maximum
        ):
            raise SkeletonError(f"{key} must be an integer in {minimum}..{maximum}")
    if contract["minimum_segment_length_px"] >= contract["maximum_segment_length_px"]:
        raise SkeletonError("segment length bounds must be strictly increasing")
    if 180 % contract["orientation_bin_degrees"]:
        raise SkeletonError("orientation_bin_degrees must divide 180 exactly")
    for key, maximum in (
        ("maximum_radial_alignment_fraction", 0.75),
        ("maximum_normalized_template_iou", 0.95),
    ):
        value = contract[key]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not 0 <= value <= maximum
        ):
            raise SkeletonError(f"{key} must be a number in 0..{maximum}")
    for key in (
        "require_disconnected_segments",
        "require_distinct_foothill_segment_counts",
    ):
        if contract[key] is not True:
            raise SkeletonError(f"{key} must be true for the G3 contract")

    footprint, footprint_metrics = _load_footprint_reference(control, size)
    prepared: list[PreparedLandform] = []
    segment_ids: set[str] = set()
    group_ids: set[str] = set()
    output = Image.new("RGB", size, background)
    landform_metrics: list[dict[str, Any]] = []
    foothill_templates: list[tuple[str, int, bytes]] = []
    try:
        landforms = control["landforms"]
        if not isinstance(landforms, list) or len(landforms) != 6:
            raise SkeletonError("Candidate G3 skeleton requires six ordered landforms")
        for index, (landform, expected) in enumerate(
            zip(landforms, EXPECTED_LANDFORMS)
        ):
            if not isinstance(landform, dict) or set(landform) != {
                "id",
                "region_id",
                "role",
                "footprint_rgb",
                "saddle_clear_box",
                "groups",
            }:
                raise SkeletonError(
                    f"landform {index} keys differ from the strict G3 contract"
                )
            identity = (
                landform["id"],
                landform["region_id"],
                landform["role"],
                _rgb(landform["footprint_rgb"], f"landform {index} footprint_rgb"),
            )
            if identity != expected:
                raise SkeletonError(
                    f"landform order/identity mismatch at index {index}: {identity!r}"
                )
            groups = landform["groups"]
            expected_groups = 2 if landform["role"] == "main-massif" else 1
            expected_kind = "rise" if expected_groups == 2 else "foothill"
            if not isinstance(groups, list) or len(groups) != expected_groups:
                raise SkeletonError(
                    f"landform {landform['id']} requires {expected_groups} groups"
                )
            saddle_raw = landform["saddle_clear_box"]
            saddle: tuple[int, int, int, int] | None
            if expected_groups == 2:
                if (
                    not isinstance(saddle_raw, list)
                    or len(saddle_raw) != 4
                    or any(
                        not isinstance(item, int) or isinstance(item, bool)
                        for item in saddle_raw
                    )
                ):
                    raise SkeletonError(
                        f"main landform {landform['id']} requires a saddle clear box"
                    )
                saddle = tuple(saddle_raw)
                if not (
                    0 <= saddle[0] < saddle[2] < size[0]
                    and 0 <= saddle[1] < saddle[3] < size[1]
                ):
                    raise SkeletonError(
                        f"landform {landform['id']} has an invalid saddle clear box"
                    )
                if saddle[2] - saddle[0] < contract["minimum_saddle_clearance_px"]:
                    raise SkeletonError(
                        f"landform {landform['id']} saddle is narrower than the contract"
                    )
            else:
                if saddle_raw is not None:
                    raise SkeletonError(
                        f"foothill {landform['id']} must not declare a saddle"
                    )
                saddle = None

            normalized_groups: list[
                tuple[str, tuple[tuple[tuple[int, int], ...], ...]]
            ] = []
            group_metrics: list[dict[str, Any]] = []
            all_lengths: list[float] = []
            orientation_bins: set[int] = set()
            landform_layer = Image.new("L", size, 0)
            try:
                layer_draw = ImageDraw.Draw(landform_layer)
                for group in groups:
                    if not isinstance(group, dict) or set(group) != {
                        "id",
                        "kind",
                        "segments",
                    }:
                        raise SkeletonError(
                            f"landform {landform['id']} group keys differ from contract"
                        )
                    if group["kind"] != expected_kind:
                        raise SkeletonError(
                            f"landform {landform['id']} group kind must be {expected_kind}"
                        )
                    group_id = group["id"]
                    if not isinstance(group_id, str) or not group_id or group_id in group_ids:
                        raise SkeletonError("group ids must be nonempty and globally unique")
                    group_ids.add(group_id)
                    segments = group["segments"]
                    if not isinstance(segments, list) or not 8 <= len(segments) <= 20:
                        raise SkeletonError(
                            f"group {group_id} requires 8..20 short segments"
                        )
                    normalized_segments: list[tuple[tuple[int, int], ...]] = []
                    for segment in segments:
                        if not isinstance(segment, dict) or set(segment) != {
                            "id",
                            "points",
                        }:
                            raise SkeletonError(
                                f"group {group_id} segment keys differ from contract"
                            )
                        segment_id = segment["id"]
                        if (
                            not isinstance(segment_id, str)
                            or not segment_id
                            or segment_id in segment_ids
                        ):
                            raise SkeletonError(
                                "segment ids must be nonempty and globally unique"
                            )
                        segment_ids.add(segment_id)
                        points_raw = segment["points"]
                        if not isinstance(points_raw, list) or not 2 <= len(points_raw) <= 3:
                            raise SkeletonError(
                                f"segment {segment_id} requires two or three points"
                            )
                        points = tuple(
                            _point(value, size, f"segment {segment_id} point")
                            for value in points_raw
                        )
                        if len(set(points)) != len(points) or points[0] == points[-1]:
                            raise SkeletonError(
                                f"segment {segment_id} must be open with unique points"
                            )
                        length = _polyline_length(points)
                        if not (
                            contract["minimum_segment_length_px"]
                            <= length
                            <= contract["maximum_segment_length_px"]
                        ):
                            raise SkeletonError(
                                f"segment {segment_id} length {length:.3f}px is outside "
                                "the short-segment contract"
                            )
                        all_lengths.append(length)
                        orientation_bins.add(
                            _orientation_bin(
                                points, contract["orientation_bin_degrees"]
                            )
                        )
                        layer_draw.line(
                            points,
                            fill=255,
                            width=contract["stroke_width_px"],
                        )
                        normalized_segments.append(points)
                    radial_fraction = _radial_alignment_fraction(
                        normalized_segments
                    )
                    if radial_fraction > contract[
                        "maximum_radial_alignment_fraction"
                    ]:
                        raise SkeletonError(
                            f"group {group_id} has radial convergence fraction "
                            f"{radial_fraction:.6f}; maximum is "
                            f"{contract['maximum_radial_alignment_fraction']:.6f}"
                        )
                    normalized_groups.append(
                        (group_id, tuple(normalized_segments))
                    )
                    group_metrics.append(
                        {
                            "id": group_id,
                            "kind": group["kind"],
                            "segment_count": len(normalized_segments),
                            "radial_alignment_fraction": round(
                                radial_fraction, 6
                            ),
                        }
                    )

                if len({round(value) for value in all_lengths}) < contract[
                    "minimum_unique_lengths_per_landform"
                ]:
                    raise SkeletonError(
                        f"landform {landform['id']} lacks unequal segment lengths"
                    )
                if len(orientation_bins) < contract[
                    "minimum_orientation_bins_per_landform"
                ]:
                    raise SkeletonError(
                        f"landform {landform['id']} lacks fall-line direction diversity"
                    )
                if expected_groups == 2:
                    group_segment_counts = [
                        entry["segment_count"] for entry in group_metrics
                    ]
                    if abs(group_segment_counts[0] - group_segment_counts[1]) < contract[
                        "minimum_main_rise_segment_count_delta"
                    ]:
                        raise SkeletonError(
                            f"landform {landform['id']} has equal-size rise motifs; "
                            "the two rise groups need a stronger segment-count delta"
                        )

                layer_bytes = landform_layer.tobytes()
                footprint_bytes = footprint.tobytes()
                expected_rgb = identity[3]
                outside = 0
                ink_pixels = 0
                for pixel_index, ink in enumerate(layer_bytes):
                    if not ink:
                        continue
                    ink_pixels += 1
                    offset = pixel_index * 3
                    if tuple(footprint_bytes[offset : offset + 3]) != expected_rgb:
                        outside += 1
                if outside:
                    raise SkeletonError(
                        f"landform {landform['id']} has {outside} ink pixels outside its "
                        "locked G2 footprint"
                    )
                if ink_pixels < contract["minimum_ink_pixels_per_landform"]:
                    raise SkeletonError(
                        f"landform {landform['id']} has only {ink_pixels} native-scale "
                        "ink pixels"
                    )
                connected_components = _component_count(landform_layer)
                if (
                    contract["require_disconnected_segments"]
                    and connected_components != len(all_lengths)
                ):
                    raise SkeletonError(
                        f"landform {landform['id']} has {connected_components} "
                        f"connected ink components for {len(all_lengths)} segments"
                    )
                if saddle is not None:
                    saddle_crop = landform_layer.crop(saddle)
                    try:
                        if saddle_crop.getbbox() is not None:
                            raise SkeletonError(
                                f"landform {landform['id']} closes its required saddle"
                            )
                    finally:
                        saddle_crop.close()

                if landform["role"] != "main-massif":
                    foothill_templates.append(
                        (
                            landform["id"],
                            len(all_lengths),
                            _normalized_template(
                                landform_layer,
                                contract["normalized_template_size_px"],
                            ),
                        )
                    )

                output.paste(stroke, mask=landform_layer)
                prepared.append(
                    PreparedLandform(
                        landform["id"],
                        landform["role"],
                        tuple(normalized_groups),
                        saddle,
                    )
                )
                landform_metrics.append(
                    {
                        "id": landform["id"],
                        "role": landform["role"],
                        "group_count": len(normalized_groups),
                        "segment_count": len(all_lengths),
                        "minimum_segment_length_px": round(min(all_lengths), 6),
                        "maximum_segment_length_px": round(max(all_lengths), 6),
                        "unique_rounded_lengths": len(
                            {round(value) for value in all_lengths}
                        ),
                        "orientation_bins": len(orientation_bins),
                        "ink_pixels": ink_pixels,
                        "outside_footprint_ink_pixels": outside,
                        "saddle_clear": saddle is not None,
                        "connected_components": connected_components,
                        "groups": group_metrics,
                    }
                )
            finally:
                landform_layer.close()

        foothill_counts = [entry[1] for entry in foothill_templates]
        if (
            contract["require_distinct_foothill_segment_counts"]
            and len(set(foothill_counts)) != len(foothill_counts)
        ):
            raise SkeletonError(
                "all four foothills must use distinct segment counts to reject "
                "translated templates"
            )
        template_comparisons: list[dict[str, Any]] = []
        reused_pairs: list[list[str]] = []
        for left_index, (left_id, _left_count, left) in enumerate(
            foothill_templates
        ):
            for right_id, _right_count, right in foothill_templates[
                left_index + 1 :
            ]:
                intersection = sum(
                    bool(left_value) and bool(right_value)
                    for left_value, right_value in zip(left, right)
                )
                union = sum(
                    bool(left_value) or bool(right_value)
                    for left_value, right_value in zip(left, right)
                )
                iou = intersection / union if union else 1.0
                template_comparisons.append(
                    {
                        "left": left_id,
                        "right": right_id,
                        "normalized_iou": round(iou, 6),
                    }
                )
                if iou > contract["maximum_normalized_template_iou"]:
                    reused_pairs.append([left_id, right_id])
        if reused_pairs:
            raise SkeletonError(
                "foothill normalized templates exceed the reuse threshold: "
                + repr(reused_pairs)
            )

        metrics = {
            "schema_version": control["schema_version"],
            "status": "passed",
            "canvas": control["canvas"],
            "mode": "RGB",
            "background_rgb": list(background),
            "stroke_rgb": list(stroke),
            "stroke_width_px": contract["stroke_width_px"],
            "footprint_reference": footprint_metrics,
            "landform_count": len(prepared),
            "main_massif_count": sum(
                item.role == "main-massif" for item in prepared
            ),
            "foothill_count": sum(item.role != "main-massif" for item in prepared),
            "rise_group_count": sum(
                len(item.groups) for item in prepared if item.role == "main-massif"
            ),
            "open_saddle_count": sum(
                item.saddle_clear_box is not None for item in prepared
            ),
            "segment_count": sum(
                entry["segment_count"] for entry in landform_metrics
            ),
            "maximum_declared_segment_length_px": contract[
                "maximum_segment_length_px"
            ],
            "closed_path_count": 0,
            "long_parallel_band_count": 0,
            "radial_convergence_failure_count": 0,
            "reused_normalized_template_count": 0,
            "foothill_segment_counts": foothill_counts,
            "normalized_template_comparisons": template_comparisons,
            "landforms": landform_metrics,
        }
        return prepared, metrics, output
    except Exception:
        output.close()
        raise
    finally:
        footprint.close()


def load_and_prepare(
    control_path: Path,
) -> tuple[dict[str, Any], list[PreparedLandform], dict[str, Any], Image.Image]:
    try:
        control = json.loads(control_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SkeletonError(f"cannot decode skeleton control: {control_path}") from error
    if not isinstance(control, dict):
        raise SkeletonError("skeleton control root must be an object")
    prepared, metrics, image = prepare(control)
    return control, prepared, metrics, image


def render_to_image(control_path: Path) -> tuple[Image.Image, dict[str, Any]]:
    _control, _prepared, metrics, image = load_and_prepare(control_path)
    return image, metrics


def render(control_path: Path, output_path: Path) -> dict[str, Any]:
    if output_path.exists():
        raise SkeletonError(f"refusing to overwrite existing output: {output_path}")
    image, metrics = render_to_image(control_path)
    try:
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
    image: Image.Image | None = None
    try:
        if args.preflight_only:
            _control, _prepared, metrics, image = load_and_prepare(args.control)
        else:
            metrics = render(args.control, args.output)
    except Exception as error:
        print(f"Candidate G3 hachure skeleton failed: {error}")
        return 1
    finally:
        if image is not None:
            image.close()
    print(json.dumps(metrics, ensure_ascii=False, sort_keys=True))
    if not args.preflight_only:
        print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
