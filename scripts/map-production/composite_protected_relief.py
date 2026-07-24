#!/usr/bin/env python3
"""Composite Candidate G through guide-derived, pixel-exact protection masks."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from jsonschema import Draft202012Validator, FormatChecker
from PIL import Image, ImageChops, ImageDraw, ImageFilter


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTROL = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-g-v1-generation-control-v1.json"
)
SCHEMA_RELATIVE_PATHS = {
    "1.0.0": "world/map-production/schemas/protected-relief-composite-v1.schema.json",
    "2.0.0": "world/map-production/schemas/protected-relief-composite-v2.schema.json",
    "3.0.0": "world/map-production/schemas/protected-relief-composite-v3.schema.json",
}
EXPECTED_REFERENCE_ORDER_V1 = (
    (1, "pixel-authoritative-base"),
    (2, "flat-color-topology-guide"),
)
EXPECTED_REFERENCE_ORDER_V2 = EXPECTED_REFERENCE_ORDER_V1 + (
    (3, "open-hachure-skeleton-guide"),
)
SKELETON_RENDERER_PATH = (
    REPO_ROOT / "scripts/map-production/render_candidate_g3_hachure_skeleton.py"
)
EXPECTED_SHAPES = (
    ("ne-main-massif", "north_east_range", "main-massif"),
    ("ne-west-foothill", "north_east_range", "foothill-a"),
    ("ne-central-foothill", "north_east_range", "foothill-b"),
    ("se-main-massif", "south_east_range", "main-massif"),
    ("se-west-foothill", "south_east_range", "foothill-a"),
    ("se-east-foothill", "south_east_range", "foothill-b"),
)
EXPECTED_ROAD_ORDER = ("north_road", "east_road", "south_east_road")


class ProtectedReliefError(ValueError):
    """Raised before any Candidate G output is published."""


@dataclass
class ValidatedInputs:
    control_path: Path
    control: dict[str, Any]
    schema_path: Path
    prompt_path: Path
    generated_input_path: Path | None
    base_path: Path
    guide_path: Path
    guide_source_path: Path
    skeleton_path: Path | None
    skeleton_source_path: Path | None
    base: Image.Image
    guide: Image.Image
    skeleton: Image.Image | None
    permission_binary: Image.Image
    guide_metrics: dict[str, Any]
    skeleton_metrics: dict[str, Any] | None

    def close(self) -> None:
        self.base.close()
        self.guide.close()
        if self.skeleton is not None:
            self.skeleton.close()
        self.permission_binary.close()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _raster_semantic_sha256(image: Image.Image) -> str:
    """Hash decoded raster identity independently from its PNG encoding."""

    digest = hashlib.sha256()
    digest.update(b"sstory-raster-semantic-v1\0")
    digest.update(image.mode.encode("ascii"))
    digest.update(b"\0")
    digest.update(image.width.to_bytes(8, "big"))
    digest.update(image.height.to_bytes(8, "big"))
    digest.update(image.tobytes())
    return digest.hexdigest()


def _resolve_repo_path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ProtectedReliefError(
            f"{label} must be a nonempty POSIX repo-relative path"
        )
    candidate = Path(value)
    if candidate.is_absolute():
        raise ProtectedReliefError(f"{label} must be repo-relative")
    resolved = (REPO_ROOT / candidate).resolve()
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError as error:
        raise ProtectedReliefError(f"{label} escapes the repository") from error
    if resolved == REPO_ROOT:
        raise ProtectedReliefError(f"{label} must identify a file")
    return resolved


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProtectedReliefError(f"cannot read {label}: {path}") from error
    if not isinstance(value, dict):
        raise ProtectedReliefError(f"{label} root must be an object")
    return value


def _validate_sha(path: Path, expected: Any, label: str) -> str:
    if not path.is_file():
        raise ProtectedReliefError(f"{label} is missing: {path}")
    actual = _sha256_file(path)
    if actual != expected:
        raise ProtectedReliefError(f"{label} SHA-256 mismatch")
    return actual


def _schema_errors(control: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as error:
        raise ProtectedReliefError("protected-relief schema is invalid") from error
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(control), key=lambda item: list(item.path))
    return [
        f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
        for error in errors
    ]


def _load_control(control_path: Path) -> tuple[dict[str, Any], Path]:
    control_path = control_path.resolve()
    try:
        control_path.relative_to(REPO_ROOT)
    except ValueError as error:
        raise ProtectedReliefError(
            "generation control must be inside the repository"
        ) from error
    control = _load_json(control_path, "generation control")
    schema_lock = control.get("schema_lock")
    if not isinstance(schema_lock, dict):
        raise ProtectedReliefError("generation control requires schema_lock")
    schema_version = control.get("schema_version")
    expected_schema_path = SCHEMA_RELATIVE_PATHS.get(schema_version)
    if expected_schema_path is None:
        raise ProtectedReliefError(
            "generation control schema_version must be 1.0.0, 2.0.0, or 3.0.0"
        )
    if schema_lock.get("path") != expected_schema_path:
        raise ProtectedReliefError(
            "schema path differs from the locked protected-relief schema"
        )
    schema_path = _resolve_repo_path(schema_lock["path"], "schema_lock.path")
    _validate_sha(schema_path, schema_lock.get("sha256"), "protected-relief schema")
    schema = _load_json(schema_path, "protected-relief schema")
    errors = _schema_errors(control, schema)
    if errors:
        raise ProtectedReliefError(
            "generation control schema validation failed: " + "; ".join(errors)
        )
    return control, schema_path


def _load_locked_raster(
    entry: dict[str, Any],
    expected_size: tuple[int, int],
    label: str,
) -> tuple[Path, Image.Image]:
    path = _resolve_repo_path(entry["path"], f"{label}.path")
    _validate_sha(path, entry["sha256"], label)
    try:
        with Image.open(path) as opened:
            opened.load()
            if opened.format != entry["format"]:
                raise ProtectedReliefError(
                    f"{label} format must be {entry['format']}, got {opened.format}"
                )
            if opened.mode != entry["mode"]:
                raise ProtectedReliefError(
                    f"{label} mode must be {entry['mode']}, got {opened.mode}"
                )
            if opened.size != expected_size:
                raise ProtectedReliefError(
                    f"{label} dimensions must be {expected_size}, got {opened.size}"
                )
            return path, opened.copy()
    except ProtectedReliefError:
        raise
    except (OSError, ValueError) as error:
        raise ProtectedReliefError(f"cannot decode {label}: {path}") from error


def _role_colors(control: dict[str, Any]) -> dict[str, tuple[int, int, int]]:
    colors: dict[str, tuple[int, int, int]] = {}
    for entry in control["guide_contract"]["active_colors"]:
        rgb = tuple(entry["rgb"])
        if rgb in colors.values():
            raise ProtectedReliefError("guide active colors must be distinct")
        colors[entry["role"]] = rgb
    background = tuple(control["guide_contract"]["background_rgb"])
    if background in colors.values():
        raise ProtectedReliefError(
            "guide background must differ from every active color"
        )
    return colors


def _sample_closed_catmull_rom(
    knots: Sequence[tuple[int, int]], samples_per_segment: int
) -> list[tuple[int, int]]:
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
        raise ProtectedReliefError(
            "a smooth guide outline requires at least 24 raster points"
        )
    return sampled


def _axis_aligned_gap(
    left: tuple[int, int, int, int], right: tuple[int, int, int, int]
) -> int:
    horizontal = max(0, right[0] - left[2] - 1, left[0] - right[2] - 1)
    vertical = max(0, right[1] - left[3] - 1, left[1] - right[3] - 1)
    return max(horizontal, vertical)


def _render_guide_source(
    source: dict[str, Any],
    expected_size: tuple[int, int],
    background: tuple[int, int, int],
    role_colors: dict[str, tuple[int, int, int]],
) -> Image.Image:
    source_version = source.get("schema_version")
    expected_root = {
        "schema_version",
        "id",
        "coordinate_space",
        "canvas",
        "background_rgb",
        "shapes",
        "purpose",
    }
    if source_version == "2.0.0":
        expected_root.add("render_contract")
    if set(source) != expected_root:
        raise ProtectedReliefError(
            "guide source root keys differ from the strict contract"
        )
    if source_version not in {"1.0.0", "2.0.0"}:
        raise ProtectedReliefError("guide source schema_version must be 1.0.0 or 2.0.0")
    if source["coordinate_space"] != "source-pixels-y-down":
        raise ProtectedReliefError("guide source coordinate_space is unsupported")
    if source["canvas"] != {"width": expected_size[0], "height": expected_size[1]}:
        raise ProtectedReliefError(
            "guide source canvas differs from generation control"
        )
    if tuple(source["background_rgb"]) != background:
        raise ProtectedReliefError(
            "guide source background differs from generation control"
        )
    shapes = source["shapes"]
    if not isinstance(shapes, list) or len(shapes) != len(EXPECTED_SHAPES):
        raise ProtectedReliefError("guide source requires exactly six ordered shapes")

    smooth_contract: dict[str, Any] | None = None
    if source_version == "2.0.0":
        contract = source["render_contract"]
        if not isinstance(contract, dict) or set(contract) != {
            "curve",
            "samples_per_segment",
            "minimum_canvas_inset_px",
            "minimum_shape_gap_px",
        }:
            raise ProtectedReliefError(
                "guide render_contract differs from the strict G2 contract"
            )
        if contract["curve"] != "closed-uniform-catmull-rom":
            raise ProtectedReliefError(
                "G2 guide requires closed-uniform-catmull-rom curves"
            )
        if (
            not isinstance(contract["samples_per_segment"], int)
            or isinstance(contract["samples_per_segment"], bool)
            or not 8 <= contract["samples_per_segment"] <= 64
        ):
            raise ProtectedReliefError("G2 guide samples_per_segment must be in 8..64")
        if contract["minimum_canvas_inset_px"] != 64:
            raise ProtectedReliefError("G2 guide canvas inset must be exactly 64px")
        if (
            not isinstance(contract["minimum_shape_gap_px"], int)
            or isinstance(contract["minimum_shape_gap_px"], bool)
            or contract["minimum_shape_gap_px"] < 1
        ):
            raise ProtectedReliefError("G2 guide minimum_shape_gap_px must be positive")
        smooth_contract = contract

    rendered = Image.new("RGB", expected_size, background)
    draw = ImageDraw.Draw(rendered)
    smooth_bounds: list[tuple[int, int, int, int]] = []
    try:
        for index, (shape, expected) in enumerate(zip(shapes, EXPECTED_SHAPES)):
            expected_shape_keys = {
                "id",
                "region_id",
                "role",
                "rgb",
                "knots" if smooth_contract is not None else "points",
            }
            if not isinstance(shape, dict) or set(shape) != expected_shape_keys:
                raise ProtectedReliefError(
                    f"guide shape {index} keys differ from the contract"
                )
            identity = (shape["id"], shape["region_id"], shape["role"])
            if identity != expected:
                raise ProtectedReliefError(
                    f"guide shape order/identity mismatch at index {index}: {identity!r}"
                )
            if tuple(shape["rgb"]) != role_colors[shape["role"]]:
                raise ProtectedReliefError(
                    f"guide shape {shape['id']} has the wrong role color"
                )
            point_key = "knots" if smooth_contract is not None else "points"
            points = shape[point_key]
            minimum_points = 8 if smooth_contract is not None else 5
            if not isinstance(points, list) or len(points) < minimum_points:
                raise ProtectedReliefError(
                    f"guide shape {shape['id']} requires at least {minimum_points} {point_key}"
                )
            normalized: list[tuple[int, int]] = []
            for point in points:
                if (
                    not isinstance(point, list)
                    or len(point) != 2
                    or any(
                        not isinstance(value, int) or isinstance(value, bool)
                        for value in point
                    )
                    or not 0 <= point[0] < expected_size[0]
                    or not 0 <= point[1] < expected_size[1]
                ):
                    raise ProtectedReliefError(
                        f"guide shape {shape['id']} has an invalid {point_key[:-1]}"
                    )
                normalized.append((point[0], point[1]))
            if smooth_contract is not None:
                normalized = _sample_closed_catmull_rom(
                    normalized, smooth_contract["samples_per_segment"]
                )
                inset = smooth_contract["minimum_canvas_inset_px"]
                if any(
                    x < inset
                    or y < inset
                    or x > expected_size[0] - inset - 1
                    or y > expected_size[1] - inset - 1
                    for x, y in normalized
                ):
                    raise ProtectedReliefError(
                        f"guide shape {shape['id']} violates the {inset}px canvas inset"
                    )
                bounds = (
                    min(point[0] for point in normalized),
                    min(point[1] for point in normalized),
                    max(point[0] for point in normalized),
                    max(point[1] for point in normalized),
                )
                minimum_gap = smooth_contract["minimum_shape_gap_px"]
                for prior_bounds in smooth_bounds:
                    if _axis_aligned_gap(prior_bounds, bounds) < minimum_gap:
                        raise ProtectedReliefError(
                            f"guide shape {shape['id']} violates the {minimum_gap}px shape gap"
                        )
                smooth_bounds.append(bounds)
            draw.polygon(normalized, fill=role_colors[shape["role"]])
        return rendered
    except Exception:
        rendered.close()
        raise


def _classify_guide(
    guide: Image.Image,
    background: tuple[int, int, int],
    entries: list[dict[str, Any]],
) -> tuple[Image.Image, dict[str, Any]]:
    color_labels = {
        tuple(entry["rgb"]): index + 1 for index, entry in enumerate(entries)
    }
    labels = bytearray(guide.width * guide.height)
    counts = [0] * (len(entries) + 1)
    raw = guide.tobytes()
    for pixel_index in range(guide.width * guide.height):
        offset = pixel_index * 3
        rgb = (raw[offset], raw[offset + 1], raw[offset + 2])
        if rgb == background:
            continue
        label = color_labels.get(rgb)
        if label is None:
            raise ProtectedReliefError(
                f"guide contains undeclared RGB value {rgb} at pixel {pixel_index}"
            )
        labels[pixel_index] = label
        counts[label] += 1

    width = guide.width
    height = guide.height
    visited = bytearray(len(labels))
    component_counts = [0] * (len(entries) + 1)
    for start, label in enumerate(labels):
        if label == 0 or visited[start]:
            continue
        component_counts[label] += 1
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
                if (
                    neighbor >= 0
                    and not visited[neighbor]
                    and labels[neighbor] == label
                ):
                    visited[neighbor] = 1
                    stack.append(neighbor)

    total_components = 0
    color_metrics = []
    for label, entry in enumerate(entries, start=1):
        components = component_counts[label]
        if components != entry["expected_components"]:
            raise ProtectedReliefError(
                f"guide role {entry['role']} has {components} connected components; "
                f"expected {entry['expected_components']}"
            )
        if counts[label] == 0:
            raise ProtectedReliefError(f"guide role {entry['role']} has no pixels")
        total_components += components
        color_metrics.append(
            {
                "role": entry["role"],
                "rgb": entry["rgb"],
                "pixels": counts[label],
                "components": components,
            }
        )
    permission = Image.frombytes(
        "L",
        guide.size,
        bytes(255 if label else 0 for label in labels),
    )
    return permission, {
        "active_pixels": sum(counts),
        "background_pixels": len(labels) - sum(counts),
        "components": total_components,
        "colors": color_metrics,
    }


def _validate_roads(control: dict[str, Any], size: tuple[int, int]) -> None:
    strokes = control["road_protection"]["strokes"]
    identifiers = tuple(stroke["id"] for stroke in strokes)
    if identifiers != EXPECTED_ROAD_ORDER:
        raise ProtectedReliefError(
            f"road stroke order must be {EXPECTED_ROAD_ORDER!r}, got {identifiers!r}"
        )
    for stroke in strokes:
        previous: tuple[int, int] | None = None
        for raw_point in stroke["points"]:
            point = (raw_point[0], raw_point[1])
            if not 0 <= point[0] < size[0] or not 0 <= point[1] < size[1]:
                raise ProtectedReliefError(
                    f"road stroke {stroke['id']} has an out-of-bounds point"
                )
            if point == previous:
                raise ProtectedReliefError(
                    f"road stroke {stroke['id']} has duplicate consecutive points"
                )
            previous = point


def _load_skeleton_renderer() -> Any:
    module_name = "_sstory_candidate_g3_hachure_skeleton"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(module_name, SKELETON_RENDERER_PATH)
    if spec is None or spec.loader is None:
        raise ProtectedReliefError("cannot load the locked G3 skeleton renderer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _validate_skeleton_source(
    control: dict[str, Any],
    size: tuple[int, int],
    skeleton: Image.Image,
) -> tuple[Path, dict[str, Any]]:
    contract = control["skeleton_contract"]
    source_entry = contract["source_control"]
    source_path = _resolve_repo_path(
        source_entry["path"], "skeleton_contract.source_control.path"
    )
    _validate_sha(source_path, source_entry["sha256"], "skeleton source control")
    source = _load_json(source_path, "skeleton source control")
    footprint_reference = source.get("footprint_reference")
    if not isinstance(footprint_reference, dict):
        raise ProtectedReliefError(
            "skeleton source requires a locked G2 footprint_reference"
        )
    guide_source = control["guide_contract"]["source_control"]
    guide_raster = control["references"][1]
    expected_cross_links = {
        "source_path": guide_source["path"],
        "source_sha256": guide_source["sha256"],
        "raster_path": guide_raster["path"],
        "raster_sha256": guide_raster["sha256"],
    }
    if footprint_reference != expected_cross_links:
        raise ProtectedReliefError(
            "skeleton source is not cross-locked to reference 2 and its guide source"
        )

    renderer = _load_skeleton_renderer()
    rendered: Image.Image | None = None
    try:
        rendered, metrics = renderer.render_to_image(source_path)
    except Exception as error:
        raise ProtectedReliefError("skeleton source preflight failed") from error
    try:
        if rendered.mode != "RGB" or rendered.size != size:
            raise ProtectedReliefError(
                "skeleton source renderer produced the wrong mode or dimensions"
            )
        if rendered.tobytes() != skeleton.tobytes():
            raise ProtectedReliefError(
                "reference 3 skeleton pixels differ from its locked source control"
            )
    finally:
        rendered.close()

    expected_metrics = {
        "landform_count": contract["expected_landforms"],
        "rise_group_count": contract["expected_rise_groups"],
        "open_saddle_count": contract["expected_open_saddles"],
        "foothill_count": contract["expected_foothills"],
        "radial_convergence_failure_count": 0,
        "reused_normalized_template_count": 0,
        "closed_path_count": 0,
        "long_parallel_band_count": 0,
    }
    for key, expected in expected_metrics.items():
        if metrics.get(key) != expected:
            raise ProtectedReliefError(
                f"skeleton metric {key} must be {expected}, got {metrics.get(key)}"
            )
    if metrics.get("background_rgb") != contract["background_rgb"]:
        raise ProtectedReliefError("skeleton background differs from its contract")
    if metrics.get("stroke_rgb") != contract["stroke_rgb"]:
        raise ProtectedReliefError("skeleton stroke differs from its contract")
    if contract["permission_source_reference_index"] != 2:
        raise ProtectedReliefError(
            "only reference 2 may provide compositing permission"
        )
    if contract["permission_contribution"] != "none":
        raise ProtectedReliefError(
            "reference 3 may not contribute compositing permission"
        )
    return source_path, metrics


def _validate_inputs(control_path: Path) -> ValidatedInputs:
    control, schema_path = _load_control(control_path)
    size = (control["canvas"]["width"], control["canvas"]["height"])
    if control["schema_version"] == "1.0.0":
        expected_reference_order = EXPECTED_REFERENCE_ORDER_V1
    else:
        expected_reference_order = EXPECTED_REFERENCE_ORDER_V2
    reference_order = tuple(
        (reference["index"], reference["role"]) for reference in control["references"]
    )
    if reference_order != expected_reference_order:
        raise ProtectedReliefError(
            "generation reference order differs from the fixed contract"
        )
    reference_paths = [reference["path"] for reference in control["references"]]
    if len(reference_paths) != len(set(reference_paths)):
        raise ProtectedReliefError("generation references must use distinct paths")

    prompt_path = _resolve_repo_path(control["prompt"]["path"], "prompt.path")
    _validate_sha(prompt_path, control["prompt"]["sha256"], "generation prompt")
    base_path, base = _load_locked_raster(
        control["references"][0], size, "reference 1 base"
    )
    try:
        guide_path, guide = _load_locked_raster(
            control["references"][1], size, "reference 2 guide"
        )
    except Exception:
        base.close()
        raise

    skeleton_path: Path | None = None
    skeleton_source_path: Path | None = None
    skeleton: Image.Image | None = None
    skeleton_metrics: dict[str, Any] | None = None
    generated_input_path: Path | None = None
    permission: Image.Image | None = None
    try:
        if control["schema_version"] in {"2.0.0", "3.0.0"}:
            skeleton_path, skeleton = _load_locked_raster(
                control["references"][2], size, "reference 3 skeleton"
            )
        if control["schema_version"] == "3.0.0":
            generated_input_path, generated_input = _load_locked_raster(
                control["generated_input"], size, "generated input"
            )
            generated_input.close()
        role_colors = _role_colors(control)
        background = tuple(control["guide_contract"]["background_rgb"])
        source_entry = control["guide_contract"]["source_control"]
        guide_source_path = _resolve_repo_path(
            source_entry["path"], "guide_contract.source_control.path"
        )
        _validate_sha(guide_source_path, source_entry["sha256"], "guide source control")
        guide_source = _load_json(guide_source_path, "guide source control")
        rendered = _render_guide_source(
            guide_source,
            size,
            background,
            role_colors,
        )
        try:
            if rendered.tobytes() != guide.tobytes():
                raise ProtectedReliefError(
                    "reference 2 guide pixels differ from its locked source control"
                )
        finally:
            rendered.close()
        permission, metrics = _classify_guide(
            guide,
            background,
            control["guide_contract"]["active_colors"],
        )
        if metrics["components"] != control["guide_contract"]["expected_components"]:
            permission.close()
            permission = None
            raise ProtectedReliefError(
                "guide component count differs from the fixed contract"
            )
        if skeleton is not None:
            skeleton_source_path, skeleton_metrics = _validate_skeleton_source(
                control, size, skeleton
            )

        locked_paths = {
            schema_path.resolve(),
            prompt_path.resolve(),
            base_path.resolve(),
            guide_path.resolve(),
            guide_source_path.resolve(),
        }
        if skeleton_path is not None and skeleton_source_path is not None:
            locked_paths.update(
                {skeleton_path.resolve(), skeleton_source_path.resolve()}
            )
        if generated_input_path is not None:
            locked_paths.add(generated_input_path.resolve())
        expected_locked_paths = (
            8 if generated_input_path is not None else 7 if skeleton is not None else 5
        )
        if len(locked_paths) != expected_locked_paths:
            permission.close()
            permission = None
            raise ProtectedReliefError("locked generation input paths must be distinct")
        _validate_roads(control, size)
        return ValidatedInputs(
            control_path=control_path.resolve(),
            control=control,
            schema_path=schema_path,
            prompt_path=prompt_path,
            generated_input_path=generated_input_path,
            base_path=base_path,
            guide_path=guide_path,
            guide_source_path=guide_source_path,
            skeleton_path=skeleton_path,
            skeleton_source_path=skeleton_source_path,
            base=base,
            guide=guide,
            skeleton=skeleton,
            permission_binary=permission,
            guide_metrics=metrics,
            skeleton_metrics=skeleton_metrics,
        )
    except Exception:
        base.close()
        guide.close()
        if skeleton is not None:
            skeleton.close()
        if permission is not None:
            permission.close()
        raise


def _feather_inside(binary: Image.Image, radius: float) -> Image.Image:
    if radius == 0:
        return binary.copy()
    softened = binary.filter(ImageFilter.GaussianBlur(radius=radius))
    try:
        return ImageChops.darker(binary, softened)
    finally:
        softened.close()


def _draw_road_core(control: dict[str, Any], size: tuple[int, int]) -> Image.Image:
    width = control["road_protection"]["guard_width_px"]
    core = Image.new("L", size, 0)
    draw = ImageDraw.Draw(core)
    for stroke in control["road_protection"]["strokes"]:
        points = [tuple(point) for point in stroke["points"]]
        draw.line(points, fill=255, width=width, joint="curve")
        radius = width // 2
        for x, y in (points[0], points[-1]):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
    return core


def _protected_strength(core: Image.Image, feather: float) -> Image.Image:
    if feather == 0:
        return core.copy()
    softened = core.filter(ImageFilter.GaussianBlur(radius=feather))
    try:
        return ImageChops.lighter(core, softened)
    finally:
        softened.close()


def _subtract_protection(mask: Image.Image, protection: Image.Image) -> Image.Image:
    inverted = ImageChops.invert(protection)
    try:
        return ImageChops.darker(mask, inverted)
    finally:
        inverted.close()


def _detail_core(base: Image.Image, control: dict[str, Any]) -> Image.Image:
    parameters = control["detail_protection"]
    luminance = base.convert("L")
    blurred = luminance.filter(
        ImageFilter.GaussianBlur(radius=parameters["gaussian_radius_px"])
    )
    difference = ImageChops.difference(luminance, blurred)
    high_frequency = difference.point(
        lambda value: 255
        if value >= parameters["high_frequency_threshold_levels"]
        else 0
    )
    dark = luminance.point(
        lambda value: 255 if value <= parameters["dark_luminance_max"] else 0
    )
    try:
        if control["schema_version"] in {"1.0.0", "2.0.0"}:
            return ImageChops.lighter(high_frequency, dark)
        if parameters["selection_operator"] != "high-frequency-and-dark":
            raise ProtectedReliefError("unsupported v3 detail selection operator")
        return ImageChops.darker(high_frequency, dark)
    finally:
        luminance.close()
        blurred.close()
        difference.close()
        high_frequency.close()
        dark.close()


def _count_selected(mask: Image.Image) -> int:
    histogram = mask.histogram()
    return sum(histogram[1:])


def _histogram_quantile(histogram: list[int], quantile: float) -> int:
    sample_count = sum(histogram[1:])
    if sample_count == 0:
        return 0
    target = sample_count * quantile
    cumulative = 0
    for value in range(1, 256):
        cumulative += histogram[value]
        if cumulative >= target:
            return value
    return 255


def _difference_metrics(
    base_bytes: bytes,
    output_bytes: bytes,
    selection: bytes,
) -> dict[str, int]:
    changed = 0
    maximum = 0
    for pixel_index, selected in enumerate(selection):
        if not selected:
            continue
        offset = pixel_index * 3
        delta = max(
            abs(output_bytes[offset + channel] - base_bytes[offset + channel])
            for channel in range(3)
        )
        if delta:
            changed += 1
            maximum = max(maximum, delta)
    return {"changed_pixels": changed, "maximum_channel_difference": maximum}


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _validate_output_paths(
    targets: Sequence[Path],
    inputs: Sequence[Path],
) -> tuple[Path, ...]:
    resolved_targets = tuple(path.resolve() for path in targets)
    if len(set(resolved_targets)) != len(resolved_targets):
        raise ProtectedReliefError("all output paths must be distinct")
    resolved_inputs = {path.resolve() for path in inputs}
    for target in resolved_targets:
        try:
            target.relative_to(REPO_ROOT)
        except ValueError as error:
            raise ProtectedReliefError(
                "output paths must stay inside the repository"
            ) from error
        if target in resolved_inputs:
            raise ProtectedReliefError(f"output path aliases an input: {target}")
        if target.exists():
            raise ProtectedReliefError(
                f"refusing to overwrite existing output: {target}"
            )
        if target == REPO_ROOT:
            raise ProtectedReliefError("output path must identify a file")
    return resolved_targets


def _atomic_publish(payloads: Sequence[tuple[Path, bytes]]) -> None:
    staged: list[tuple[Path, Path]] = []
    committed: list[Path] = []
    try:
        for target, payload in payloads:
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
            staged.append((temporary, target))

        for temporary, target in staged:
            try:
                os.link(temporary, target)
            except FileExistsError as error:
                raise ProtectedReliefError(
                    f"refusing to overwrite concurrently created output: {target}"
                ) from error
            committed.append(target)
        for temporary, _target in staged:
            temporary.unlink(missing_ok=True)
    except Exception:
        for target in reversed(committed):
            target.unlink(missing_ok=True)
        for temporary, _target in staged:
            temporary.unlink(missing_ok=True)
        raise


def preflight(control_path: Path = DEFAULT_CONTROL) -> dict[str, Any]:
    validated = _validate_inputs(control_path)
    try:
        result = {
            "status": "passed",
            "control_path": _display_path(validated.control_path),
            "control_sha256": _sha256_file(validated.control_path),
            "schema_path": _display_path(validated.schema_path),
            "schema_sha256": _sha256_file(validated.schema_path),
            "prompt_path": _display_path(validated.prompt_path),
            "prompt_sha256": _sha256_file(validated.prompt_path),
            "reference_order": [
                {
                    "index": entry["index"],
                    "role": entry["role"],
                    "path": entry["path"],
                    "sha256": entry["sha256"],
                    "format": entry["format"],
                    "mode": entry["mode"],
                    "width": validated.base.width,
                    "height": validated.base.height,
                }
                for entry in validated.control["references"]
            ],
            "guide_source_path": _display_path(validated.guide_source_path),
            "guide_source_sha256": _sha256_file(validated.guide_source_path),
            "guide": validated.guide_metrics,
            "road_order": [
                stroke["id"]
                for stroke in validated.control["road_protection"]["strokes"]
            ],
            "road_guard_width_px": validated.control["road_protection"][
                "guard_width_px"
            ],
        }
        if (
            validated.skeleton_path is not None
            and validated.skeleton_source_path is not None
            and validated.skeleton_metrics is not None
        ):
            result.update(
                {
                    "skeleton_source_path": _display_path(
                        validated.skeleton_source_path
                    ),
                    "skeleton_source_sha256": _sha256_file(
                        validated.skeleton_source_path
                    ),
                    "skeleton": validated.skeleton_metrics,
                    "permission_source_reference_index": 2,
                    "skeleton_permission_contribution": "none",
                }
            )
        if validated.generated_input_path is not None:
            result.update(
                {
                    "protection_policy": validated.control["protection_policy"],
                    "generated_input": {
                        **validated.control["generated_input"],
                        "width": validated.base.width,
                        "height": validated.base.height,
                    },
                }
            )
        return result
    finally:
        validated.close()


def composite(
    *,
    control_path: Path,
    generated_path: Path,
    output_path: Path,
    mask_output_path: Path,
    protection_output_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    validated = _validate_inputs(control_path)
    generated: Image.Image | None = None
    permission_soft: Image.Image | None = None
    road_core: Image.Image | None = None
    road_strength: Image.Image | None = None
    detail_core: Image.Image | None = None
    detail_strength: Image.Image | None = None
    final_mask: Image.Image | None = None
    protection_core: Image.Image | None = None
    output: Image.Image | None = None
    try:
        size = validated.base.size
        generated_path = generated_path.resolve()
        try:
            generated_path.relative_to(REPO_ROOT)
        except ValueError as error:
            raise ProtectedReliefError(
                "generated image must be inside the repository"
            ) from error
        if not generated_path.is_file():
            raise ProtectedReliefError(f"generated image is missing: {generated_path}")
        locked_input_paths = {
            validated.control_path,
            validated.schema_path,
            validated.prompt_path,
            validated.base_path,
            validated.guide_path,
            validated.guide_source_path,
        }
        if validated.skeleton_path is not None:
            locked_input_paths.add(validated.skeleton_path)
        if validated.skeleton_source_path is not None:
            locked_input_paths.add(validated.skeleton_source_path)
        if validated.generated_input_path is not None:
            locked_input_paths.add(validated.generated_input_path)
            if generated_path != validated.generated_input_path:
                raise ProtectedReliefError(
                    "generated image path differs from the v3 generated_input lock"
                )
            _validate_sha(
                generated_path,
                validated.control["generated_input"]["sha256"],
                "generated input",
            )
        elif generated_path in locked_input_paths:
            raise ProtectedReliefError("generated image must not alias a locked input")
        try:
            with Image.open(generated_path) as opened:
                opened.load()
                if opened.format != "PNG":
                    raise ProtectedReliefError(
                        f"generated image format must be PNG, got {opened.format}"
                    )
                if opened.mode != "RGB":
                    raise ProtectedReliefError(
                        f"generated image mode must be RGB, got {opened.mode}"
                    )
                if opened.size != size:
                    raise ProtectedReliefError(
                        f"generated image dimensions must be {size}, got {opened.size}"
                    )
                generated = opened.copy()
        except ProtectedReliefError:
            raise
        except (OSError, ValueError) as error:
            raise ProtectedReliefError("cannot decode generated image") from error

        targets = _validate_output_paths(
            (output_path, mask_output_path, protection_output_path, report_path),
            tuple(locked_input_paths) + (generated_path,),
        )
        output_path, mask_output_path, protection_output_path, report_path = targets

        permission_soft = _feather_inside(
            validated.permission_binary,
            validated.control["guide_contract"]["permission_feather_inside_px"],
        )
        road_core = _draw_road_core(validated.control, size)
        road_strength = _protected_strength(
            road_core,
            validated.control["road_protection"]["feather_px"],
        )
        detail_core = _detail_core(validated.base, validated.control)
        detail_strength = _protected_strength(
            detail_core,
            validated.control["detail_protection"]["feather_px"],
        )

        final_mask = _subtract_protection(permission_soft, road_strength)
        without_detail = _subtract_protection(final_mask, detail_strength)
        final_mask.close()
        final_mask = without_detail
        # Protection cores are subtracted last and can never regain alpha through feathering.
        hard_zeroed = _subtract_protection(final_mask, road_core)
        final_mask.close()
        final_mask = _subtract_protection(hard_zeroed, detail_core)
        hard_zeroed.close()

        outside_permission = ImageChops.invert(validated.permission_binary)
        protection_core = ImageChops.lighter(outside_permission, road_core)
        outside_permission.close()
        combined_protection = ImageChops.lighter(protection_core, detail_core)
        protection_core.close()
        protection_core = combined_protection

        mask_histogram = final_mask.histogram()
        editable_pixels = sum(mask_histogram[1:])
        if editable_pixels == 0:
            raise ProtectedReliefError(
                "road/detail protection removed all editable support"
            )
        output = Image.composite(generated, validated.base, final_mask)

        base_bytes = validated.base.tobytes()
        output_bytes = output.tobytes()
        permission_values = validated.permission_binary.tobytes()
        outside_values = bytes(0 if value else 255 for value in permission_values)
        road_values = road_core.tobytes()
        detail_values = detail_core.tobytes()
        zero_mask_values = bytes(
            255 if value == 0 else 0 for value in final_mask.tobytes()
        )
        gates = {
            "outside_permission": _difference_metrics(
                base_bytes, output_bytes, outside_values
            ),
            "road_core": _difference_metrics(base_bytes, output_bytes, road_values),
            "detail_core": _difference_metrics(base_bytes, output_bytes, detail_values),
            "zero_mask": _difference_metrics(
                base_bytes, output_bytes, zero_mask_values
            ),
        }
        failed = [name for name, metric in gates.items() if metric["changed_pixels"]]
        if failed:
            raise ProtectedReliefError(
                "protected pixel identity failed for " + ", ".join(failed)
            )

        output_png = _png_bytes(output)
        mask_png = _png_bytes(final_mask)
        protection_png = _png_bytes(protection_core)
        road_permission = ImageChops.darker(validated.permission_binary, road_core)
        detail_permission = ImageChops.darker(validated.permission_binary, detail_core)
        try:
            road_permission_pixels = _count_selected(road_permission)
            detail_permission_pixels = _count_selected(detail_permission)
        finally:
            road_permission.close()
            detail_permission.close()
        report = {
            "schema_version": "1.0.0",
            "id": f"{validated.control['id']}-protected-composite",
            "status": "passed",
            "control_path": _display_path(validated.control_path),
            "control_sha256": _sha256_file(validated.control_path),
            "schema_path": _display_path(validated.schema_path),
            "schema_sha256": _sha256_file(validated.schema_path),
            "prompt_path": _display_path(validated.prompt_path),
            "prompt_sha256": _sha256_file(validated.prompt_path),
            "reference_order": [
                {
                    "index": entry["index"],
                    "role": entry["role"],
                    "path": entry["path"],
                    "sha256": entry["sha256"],
                }
                for entry in validated.control["references"]
            ],
            "generated_path": _display_path(generated_path),
            "generated_sha256": _sha256_file(generated_path),
            "output_path": _display_path(output_path),
            "mask_output_path": _display_path(mask_output_path),
            "protection_output_path": _display_path(protection_output_path),
            "report_path": _display_path(report_path),
            "guide": validated.guide_metrics,
            "parameters": {
                "permission_source": "exact-three-declared-flat-guide-colors",
                "permission_feather_inside_px": validated.control["guide_contract"][
                    "permission_feather_inside_px"
                ],
                "road_guard_width_px": validated.control["road_protection"][
                    "guard_width_px"
                ],
                "road_feather_px": validated.control["road_protection"]["feather_px"],
                "road_order": [
                    stroke["id"]
                    for stroke in validated.control["road_protection"]["strokes"]
                ],
                **validated.control["detail_protection"],
            },
            "metrics": {
                "permission_pixels": _count_selected(validated.permission_binary),
                "editable_pixels": editable_pixels,
                "opaque_editable_pixels": mask_histogram[255],
                "mean_editable_alpha": round(
                    sum(value * mask_histogram[value] for value in range(1, 256))
                    / editable_pixels,
                    6,
                ),
                "median_editable_alpha": _histogram_quantile(mask_histogram, 0.5),
                "p90_editable_alpha": _histogram_quantile(mask_histogram, 0.9),
                "road_core_pixels": _count_selected(road_core),
                "road_core_permission_pixels": road_permission_pixels,
                "detail_core_pixels": _count_selected(detail_core),
                "detail_core_permission_pixels": detail_permission_pixels,
                "protected_core_pixels": _count_selected(protection_core),
                "gates": gates,
            },
            "output_sha256": _sha256_bytes(output_png),
            "mask_sha256": _sha256_bytes(mask_png),
            "protection_sha256": _sha256_bytes(protection_png),
        }
        if (
            validated.skeleton_source_path is not None
            and validated.skeleton_metrics is not None
        ):
            report["skeleton_source_path"] = _display_path(
                validated.skeleton_source_path
            )
            report["skeleton_source_sha256"] = _sha256_file(
                validated.skeleton_source_path
            )
            report["skeleton"] = validated.skeleton_metrics
            report["parameters"].update(
                {
                    "permission_source_reference_index": 2,
                    "skeleton_permission_contribution": "none",
                }
            )
        if validated.generated_input_path is not None:
            report["parameters"].update(
                {
                    "protection_policy": validated.control["protection_policy"],
                    "generated_input_locked": True,
                }
            )
        report_bytes = (
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        _atomic_publish(
            (
                (output_path, output_png),
                (mask_output_path, mask_png),
                (protection_output_path, protection_png),
                (report_path, report_bytes),
            )
        )
        return report
    finally:
        validated.close()
        for image in (
            generated,
            permission_soft,
            road_core,
            road_strength,
            detail_core,
            detail_strength,
            final_mask,
            protection_core,
            output,
        ):
            if image is not None:
                image.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight_parser = subparsers.add_parser(
        "preflight", description="Validate the locked generation inputs and order."
    )
    preflight_parser.add_argument("--control", type=Path, default=DEFAULT_CONTROL)

    composite_parser = subparsers.add_parser(
        "composite",
        description="Publish a protected Candidate G composite transaction.",
    )
    composite_parser.add_argument("--control", type=Path, default=DEFAULT_CONTROL)
    composite_parser.add_argument("--generated", type=Path, required=True)
    composite_parser.add_argument("--output", type=Path, required=True)
    composite_parser.add_argument("--mask-output", type=Path, required=True)
    composite_parser.add_argument("--protection-output", type=Path, required=True)
    composite_parser.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "preflight":
            result = preflight(args.control)
        else:
            result = composite(
                control_path=args.control,
                generated_path=args.generated,
                output_path=args.output,
                mask_output_path=args.mask_output,
                protection_output_path=args.protection_output,
                report_path=args.report,
            )
    except Exception as error:
        print(f"Candidate G protected relief failed: {error}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
