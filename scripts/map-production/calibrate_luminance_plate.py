#!/usr/bin/env python3
"""Calibrate one bounded low-frequency plate operation and preflight its transfer."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import io
import json
import math
import os
import sys
import tempfile
import zlib
from array import array
from pathlib import Path
from typing import Any, Sequence

import PIL
from jsonschema import Draft202012Validator, FormatChecker
from PIL import Image, ImageDraw, ImageFilter, ImageOps


REPO_ROOT = Path(__file__).resolve().parents[2]
RELIEF_SCRIPT = REPO_ROOT / "scripts/map-production/transfer_low_frequency_relief.py"
DEFAULT_SCHEMA = (
    REPO_ROOT
    / "world/map-production/schemas/luminance-plate-calibration.schema.json"
)
DEFAULT_CONTROL = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-e-v3-calibration-v1.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "world/map-production/candidates/style-candidate-e-v3-south-east-calibrated-plate.png"
)
DEFAULT_SUPPORT_OUTPUT = (
    REPO_ROOT
    / "world/map-production/qa/automated/style-candidate-e-v3-calibration-support.png"
)
DEFAULT_FIELD_OUTPUT = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-e-v3-calibration-field-v1.png"
)
DEFAULT_REPORT = (
    REPO_ROOT
    / "world/map-production/qa/automated/style-candidate-e-v3-calibration.json"
)


class CalibrationError(ValueError):
    """Raised before publication when a calibration contract is not satisfied."""


def _reject_constant(value: str) -> None:
    raise CalibrationError(f"non-finite JSON number is forbidden: {value}")


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
        )
    except CalibrationError:
        raise
    except Exception as error:
        raise CalibrationError(f"cannot parse {label}: {path}: {error}") from error


def _load_relief_module() -> Any:
    spec = importlib.util.spec_from_file_location("plate_relief", RELIEF_SCRIPT)
    if spec is None or spec.loader is None:
        raise CalibrationError(f"cannot load transfer module: {RELIEF_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _raster_semantic_sha256(image: Image.Image) -> str:
    """Hash mode, dimensions, and decoded pixels without PNG container bytes."""

    digest = hashlib.sha256()
    digest.update(b"sstory-raster-semantic-v1\0")
    digest.update(image.mode.encode("ascii"))
    digest.update(b"\0")
    digest.update(image.width.to_bytes(8, "big"))
    digest.update(image.height.to_bytes(8, "big"))
    digest.update(image.tobytes())
    return digest.hexdigest()


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _resolve_repo_path(raw: str, label: str) -> Path:
    path = (REPO_ROOT / raw).resolve()
    try:
        path.relative_to(REPO_ROOT.resolve())
    except ValueError as error:
        raise CalibrationError(f"{label} must stay inside the repository: {raw}") from error
    return path


def _validate_schema(control: Any, schema_path: Path) -> None:
    schema = _load_json(schema_path, "calibration schema")
    if not isinstance(schema, dict):
        raise CalibrationError("calibration schema root must be an object")
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as error:
        raise CalibrationError(f"invalid calibration schema: {error}") from error
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(control), key=lambda item: list(item.path))
    if errors:
        rendered = []
        for error in errors:
            location = "/" + "/".join(str(part) for part in error.path)
            rendered.append(f"{location}: {error.message}")
        raise CalibrationError("calibration control schema failed: " + "; ".join(rendered))


def _functional_control(control: dict[str, Any], ignored: Sequence[str]) -> dict[str, Any]:
    normalized = copy.deepcopy(control)
    for key in ignored:
        normalized.pop(key, None)
    return normalized


def _validate_inputs(
    control: dict[str, Any],
    control_path: Path,
    schema_path: Path,
) -> tuple[Path, Path, dict[str, Any], Any, Any]:
    calibration = control.get("calibration")
    compact_requested = isinstance(calibration, dict) and (
        "topology_compact_ridges" in calibration
    )
    if compact_requested:
        if control.get("schema_version") != "1.2.0":
            raise CalibrationError(
                "topology_compact_ridges requires calibration schema_version 1.2.0"
            )
        schema_lock = control.get("schema_lock")
        if not isinstance(schema_lock, dict) or set(schema_lock) != {"path", "sha256"}:
            raise CalibrationError(
                "topology_compact_ridges requires an exact schema_lock path and SHA-256"
            )
        locked_schema_path = _resolve_repo_path(schema_lock["path"], "schema_lock.path")
        if schema_path.resolve() != locked_schema_path.resolve():
            raise CalibrationError(
                "topology_compact_ridges schema path differs from the locked schema"
            )
        if not locked_schema_path.is_file():
            raise CalibrationError(f"locked calibration schema does not exist: {locked_schema_path}")
        actual_schema_hash = _sha256_file(locked_schema_path)
        if actual_schema_hash != schema_lock["sha256"]:
            raise CalibrationError(
                "locked calibration schema SHA-256 mismatch: "
                f"expected {schema_lock['sha256']}, got {actual_schema_hash}"
            )
    _validate_schema(control, schema_path)
    if PIL.__version__ != control["numeric_contract"]["pillow_version"]:
        raise CalibrationError(
            "Pillow version mismatch: "
            f"expected {control['numeric_contract']['pillow_version']}, got {PIL.__version__}"
        )

    if compact_requested:
        expected_numeric_contract = {
            "python_version": "3.12.10",
            "raster_semantic_hash": "sstory-raster-semantic-v1",
            "zlib_runtime_policy": "provenance-only",
            "topology_float_mode": "python-array-binary64-row-major",
            "primitive_evaluation_order": "canonical-id-ascending-product-union",
            "topology_quantization": (
                "round-half-even-at-l8-intermediate-and-final-plate-boundaries"
            ),
            "gradient_boundary": "clamp-to-edge",
            "deterministic_replay": "two-independent-derivations-byte-identical",
        }
        numeric_contract = control["numeric_contract"]
        for key, expected in expected_numeric_contract.items():
            if numeric_contract.get(key) != expected:
                raise CalibrationError(
                    f"topology_compact_ridges numeric contract mismatch for {key}: "
                    f"expected {expected!r}, got {numeric_contract.get(key)!r}"
                )
        if sys.version.split()[0] != numeric_contract["python_version"]:
            raise CalibrationError(
                "Python version mismatch: "
                f"expected {numeric_contract['python_version']}, got {sys.version.split()[0]}"
            )
    source_path = _resolve_repo_path(control["source_image"]["path"], "source_image.path")
    transfer_path = _resolve_repo_path(
        control["transfer_control"]["path"], "transfer_control.path"
    )
    raster_path = _resolve_repo_path(
        control["transfer_control"]["raster_path"],
        "transfer_control.raster_path",
    )
    reference_path = _resolve_repo_path(
        control["transfer_control"]["functional_reference_path"],
        "transfer_control.functional_reference_path",
    )
    for path, label, expected in (
        (source_path, "source image", control["source_image"]["sha256"]),
        (transfer_path, "transfer control", control["transfer_control"]["sha256"]),
        (raster_path, "transfer raster", control["transfer_control"]["raster_sha256"]),
        (
            reference_path,
            "functional transfer reference",
            control["transfer_control"]["functional_reference_sha256"],
        ),
    ):
        if not path.is_file():
            raise CalibrationError(f"{label} does not exist: {path}")
        actual = _sha256_file(path)
        if actual != expected:
            raise CalibrationError(
                f"{label} SHA-256 mismatch: expected {expected}, got {actual}"
            )

    transfer_control = _load_json(transfer_path, "transfer control")
    reference_control = _load_json(reference_path, "functional transfer reference")
    if not isinstance(transfer_control, dict) or not isinstance(reference_control, dict):
        raise CalibrationError("transfer controls must be JSON objects")
    ignored = control["transfer_control"]["allowed_metadata_differences"]
    if _functional_control(transfer_control, ignored) != _functional_control(
        reference_control, ignored
    ):
        raise CalibrationError(
            "transfer control differs functionally from the locked reference"
        )

    relief = _load_relief_module()
    composite = relief._load_composite_module()
    rendered_mask = composite.build_mask(transfer_control)
    try:
        rendered_hash = _raster_semantic_sha256(rendered_mask)
        try:
            with Image.open(raster_path) as opened:
                opened.load()
                if (
                    opened.format != "PNG"
                    or opened.mode != rendered_mask.mode
                    or opened.size != rendered_mask.size
                ):
                    raise CalibrationError(
                        "locked transfer raster encoding does not match the rendered mask"
                    )
                expected_raster_hash = _raster_semantic_sha256(opened)
        except CalibrationError:
            raise
        except (OSError, ValueError) as error:
            raise CalibrationError(
                f"cannot decode locked transfer raster: {raster_path}: {error}"
            ) from error
    finally:
        rendered_mask.close()
    if rendered_hash != expected_raster_hash:
        raise CalibrationError(
            "rendered transfer mask pixels do not equal the locked raster: "
            f"expected {expected_raster_hash}, got {rendered_hash}"
        )

    if transfer_control.get("canvas") != control.get("canvas"):
        raise CalibrationError("calibration and transfer canvases must match exactly")
    source_declared = transfer_control.get("source_image")
    if not isinstance(source_declared, dict):
        raise CalibrationError("transfer control must declare source_image")
    base_path = _resolve_repo_path(source_declared["path"], "transfer source_image.path")
    if not base_path.is_file() or _sha256_file(base_path) != source_declared.get("sha256"):
        raise CalibrationError("transfer pixel-authoritative base is missing or hash-mismatched")

    if control_path.resolve() in {
        source_path.resolve(),
        transfer_path.resolve(),
        raster_path.resolve(),
        reference_path.resolve(),
    }:
        raise CalibrationError("calibration control must be distinct from every input")
    return source_path, transfer_path, transfer_control, relief, composite


def _find_region(control: dict[str, Any], region_id: str) -> dict[str, Any]:
    matches = [
        polygon
        for polygon in control.get("include_polygons", [])
        if polygon.get("id") == region_id
    ]
    if len(matches) != 1:
        raise CalibrationError(
            f"operation region_id must match exactly one transfer polygon: {region_id}"
        )
    return matches[0]


def _high_frequency_metrics(
    image: Image.Image,
    radius: int,
    quantile: Any,
) -> dict[str, float]:
    luminance = ImageOps.grayscale(image)
    blurred = luminance.filter(ImageFilter.GaussianBlur(radius=radius))
    try:
        values = bytes(luminance.get_flattened_data())
        blurred_values = bytes(blurred.get_flattened_data())
    finally:
        luminance.close()
        blurred.close()
    residual = [abs(left - right) for left, right in zip(values, blurred_values)]
    return {
        "rms_levels": round(
            math.sqrt(sum(value * value for value in residual) / max(1, len(residual))),
            6,
        ),
        "p99_levels": round(quantile(residual, 0.99), 4),
        "maximum_levels": float(max(residual, default=0)),
    }


def _warped_point(x: float, y: float) -> tuple[float, float]:
    return (
        x
        + 14 * math.sin(2 * math.pi * (y + 37) / 347)
        + 7 * math.sin(2 * math.pi * (x + y + 91) / 521),
        y
        + 11 * math.sin(2 * math.pi * (x + 53) / 293)
        - 6 * math.sin(2 * math.pi * (x - 2 * y + 127) / 467),
    )


def _warped_coordinates(size: tuple[int, int]) -> tuple[array, array]:
    width, height = size
    warped_x = array("f")
    warped_y = array("f")
    for y in range(height):
        for x in range(width):
            transformed_x, transformed_y = _warped_point(x, y)
            warped_x.append(transformed_x)
            warped_y.append(transformed_y)
    return warped_x, warped_y


def _accumulate_ridge_segment(
    elevation: array,
    size: tuple[int, int],
    warped_x_values: array,
    warped_y_values: array,
    first: dict[str, Any],
    second: dict[str, Any],
) -> None:
    width, height = size
    x0, y0 = first["point"]
    x1, y1 = second["point"]
    half_width0 = float(first["half_width_px"])
    half_width1 = float(second["half_width_px"])
    height0 = float(first["height_levels"])
    height1 = float(second["height_levels"])
    dx = x1 - x0
    dy = y1 - y0
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        raise CalibrationError("topology_ridges consecutive ridge nodes must differ")
    reach = math.ceil(3 * max(half_width0, half_width1) + 24)
    minimum_x = max(0, min(x0, x1) - reach)
    maximum_x = min(width - 1, max(x0, x1) + reach)
    minimum_y = max(0, min(y0, y1) - reach)
    maximum_y = min(height - 1, max(y0, y1) + reach)
    for y in range(minimum_y, maximum_y + 1):
        row = y * width
        for x in range(minimum_x, maximum_x + 1):
            index = row + x
            warped_x = warped_x_values[index]
            warped_y = warped_y_values[index]
            projection = (
                (warped_x - x0) * dx + (warped_y - y0) * dy
            ) / length_squared
            progress = max(0.0, min(1.0, projection))
            closest_x = x0 + progress * dx
            closest_y = y0 + progress * dy
            half_width = half_width0 + progress * (half_width1 - half_width0)
            distance = math.hypot(
                warped_x - closest_x,
                warped_y - closest_y,
            )
            if distance > 3 * half_width:
                continue
            local_height = height0 + progress * (height1 - height0)
            contribution = local_height * math.exp(-((distance / half_width) ** 2.4))
            if contribution > elevation[index]:
                elevation[index] = contribution


def _accumulate_foothill(
    elevation: array,
    size: tuple[int, int],
    warped_x_values: array,
    warped_y_values: array,
    foothill: dict[str, Any],
) -> None:
    width, height = size
    center_x, center_y = foothill["center"]
    axis_x, axis_y = foothill["axes_px"]
    angle = math.radians(foothill["angle_degrees"])
    cosine = math.cos(angle)
    sine = math.sin(angle)
    reach = math.ceil(2 * max(axis_x, axis_y) + 24)
    minimum_x = max(0, center_x - reach)
    maximum_x = min(width - 1, center_x + reach)
    minimum_y = max(0, center_y - reach)
    maximum_y = min(height - 1, center_y + reach)
    amplitude = float(foothill["height_levels"])
    phase = float(foothill["phase_radians"])
    for y in range(minimum_y, maximum_y + 1):
        row = y * width
        for x in range(minimum_x, maximum_x + 1):
            index = row + x
            warped_x = warped_x_values[index]
            warped_y = warped_y_values[index]
            delta_x = warped_x - center_x
            delta_y = warped_y - center_y
            along = cosine * delta_x + sine * delta_y
            across = -sine * delta_x + cosine * delta_y
            normalized_along = along / axis_x
            normalized_across = across / axis_y
            warped_along = (
                normalized_along
                + 0.16 * normalized_across * normalized_across
                - 0.08 * math.sin(math.pi * normalized_across + phase)
            )
            warped_across = (
                normalized_across
                + 0.10 * normalized_along * normalized_across
                + 0.06 * math.sin(math.pi * normalized_along - phase)
            )
            rho = (
                abs(warped_along) ** 2.6 + abs(warped_across) ** 2.2
            ) ** (1 / 2.4)
            if rho > 2:
                continue
            contribution = amplitude * math.exp(-(rho**4))
            if contribution > elevation[index]:
                elevation[index] = contribution


def _continuous_ridge_field(
    size: tuple[int, int],
    warped_x_values: array,
    warped_y_values: array,
    definition: dict[str, Any],
    operation: dict[str, Any],
) -> tuple[array, dict[str, Any]]:
    width, height = size
    pixel_count = width * height
    elevation = array("f", [0.0]) * pixel_count
    nodes = definition["ridge_nodes"]
    for first, second in zip(nodes, nodes[1:]):
        _accumulate_ridge_segment(
            elevation,
            size,
            warped_x_values,
            warped_y_values,
            first,
            second,
        )
    for foothill in definition["foothills"]:
        _accumulate_foothill(
            elevation,
            size,
            warped_x_values,
            warped_y_values,
            foothill,
        )

    elevation_image = Image.new("L", size)
    elevation_image.putdata(
        [max(0, min(255, round(value))) for value in elevation]
    )
    smoothed = elevation_image.filter(
        ImageFilter.GaussianBlur(radius=operation["elevation_smoothing_radius_px"])
    )
    try:
        values = bytes(smoothed.get_flattened_data())
    finally:
        elevation_image.close()
        smoothed.close()

    gradient_step = int(operation["hillshade_gradient_step_px"])
    gradient_scale = float(operation["hillshade_gradient_scale"])
    light_x, light_y, light_z = operation["light_vector_xyz"]
    light_length = math.sqrt(light_x * light_x + light_y * light_y + light_z * light_z)
    light_x /= light_length
    light_y /= light_length
    light_z /= light_length
    hillshade_weight = float(operation["hillshade_weight"])
    elevation_weight = float(operation["elevation_weight"])
    field = array("f", [0.0]) * pixel_count
    maximum_elevation = max(values, default=1) or 1
    for y in range(height):
        negative_y = max(0, y - gradient_step)
        positive_y = min(height - 1, y + gradient_step)
        row = y * width
        negative_row = negative_y * width
        positive_row = positive_y * width
        for x in range(width):
            negative_x = max(0, x - gradient_step)
            positive_x = min(width - 1, x + gradient_step)
            gradient_x = (
                values[row + positive_x] - values[row + negative_x]
            ) / max(1, positive_x - negative_x) / maximum_elevation
            gradient_y = (
                values[positive_row + x] - values[negative_row + x]
            ) / max(1, positive_y - negative_y) / maximum_elevation
            normal_x = -gradient_scale * gradient_x
            normal_y = -gradient_scale * gradient_y
            normal_length = math.sqrt(
                normal_x * normal_x + normal_y * normal_y + 1
            )
            dot = (
                normal_x * light_x + normal_y * light_y + light_z
            ) / normal_length
            field[row + x] = (
                hillshade_weight * (dot - light_z)
                + elevation_weight * values[row + x] / maximum_elevation
            )
    encoding_scale = float(operation["intermediate_field_scale"])
    encoded_values = [128 + round(value * encoding_scale) for value in field]
    if min(encoded_values, default=128) < 0 or max(encoded_values, default=128) > 255:
        raise CalibrationError("topology_ridges intermediate hillshade encoding clipped")
    encoded = Image.new("L", size)
    encoded.putdata(encoded_values)
    smoothed_field = encoded.filter(
        ImageFilter.GaussianBlur(radius=operation["hillshade_smoothing_radius_px"])
    )
    try:
        smoothed_values = bytes(smoothed_field.get_flattened_data())
    finally:
        encoded.close()
        smoothed_field.close()
    field = array(
        "f",
        ((value - 128) / encoding_scale for value in smoothed_values),
    )
    return field, {
        "ridge_node_ids": [node["id"] for node in nodes],
        "ridge_node_roles": [node["role"] for node in nodes],
        "foothill_ids": [foothill["id"] for foothill in definition["foothills"]],
        "maximum_elevation_levels": maximum_elevation,
        "minimum_continuous_field": round(min(field, default=0), 6),
        "maximum_continuous_field": round(max(field, default=0), 6),
    }


def _smoothstep5(progress: float) -> float:
    return progress**3 * (10 + progress * (-15 + 6 * progress))


def _signed_tail_transform(
    value: float,
    activation_scale: float,
    extrema_scale: float,
) -> float:
    if not all(math.isfinite(item) for item in (value, activation_scale, extrema_scale)):
        raise CalibrationError("signed tail transform inputs must be finite")
    if activation_scale <= 0 or extrema_scale <= 0:
        raise CalibrationError("signed tail transform scales must be positive")
    tail_attenuated = value * math.tanh(abs(value) / activation_scale)
    return extrema_scale * math.tanh(tail_attenuated / extrema_scale)


def _catmull_rom_coordinate(
    before: float,
    start: float,
    end: float,
    after: float,
    progress: float,
) -> float:
    squared = progress * progress
    cubed = squared * progress
    return 0.5 * (
        2 * start
        + (-before + end) * progress
        + (2 * before - 5 * start + 4 * end - after) * squared
        + (-before + 3 * start - 3 * end + after) * cubed
    )


def _dense_compact_nodes(
    nodes: list[dict[str, Any]],
    subdivisions: int,
) -> list[dict[str, float]]:
    dense: list[dict[str, float]] = []
    for index in range(len(nodes) - 1):
        start = nodes[index]
        end = nodes[index + 1]
        if index:
            before_point = nodes[index - 1]["point"]
        else:
            before_point = [
                2 * start["point"][axis] - end["point"][axis]
                for axis in range(2)
            ]
        if index + 2 < len(nodes):
            after_point = nodes[index + 2]["point"]
        else:
            after_point = [
                2 * end["point"][axis] - start["point"][axis]
                for axis in range(2)
            ]
        for step in range(subdivisions):
            progress = step / subdivisions
            eased = _smoothstep5(progress)
            dense.append(
                {
                    "x": _catmull_rom_coordinate(
                        before_point[0],
                        start["point"][0],
                        end["point"][0],
                        after_point[0],
                        progress,
                    ),
                    "y": _catmull_rom_coordinate(
                        before_point[1],
                        start["point"][1],
                        end["point"][1],
                        after_point[1],
                        progress,
                    ),
                    "height": start["height"]
                    + eased * (end["height"] - start["height"]),
                    "lit_width": start["lit_half_width_px"]
                    + eased
                    * (end["lit_half_width_px"] - start["lit_half_width_px"]),
                    "shadow_width": start["shadow_half_width_px"]
                    + eased
                    * (
                        end["shadow_half_width_px"]
                        - start["shadow_half_width_px"]
                    ),
                }
            )
    final = nodes[-1]
    dense.append(
        {
            "x": float(final["point"][0]),
            "y": float(final["point"][1]),
            "height": float(final["height"]),
            "lit_width": float(final["lit_half_width_px"]),
            "shadow_width": float(final["shadow_half_width_px"]),
        }
    )
    arc_length = 0.0
    dense[0]["arc_length"] = 0.0
    for first, second in zip(dense, dense[1:]):
        arc_length += math.hypot(
            second["x"] - first["x"],
            second["y"] - first["y"],
        )
        second["arc_length"] = arc_length
    return dense


def _proper_segments_intersect(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> bool:
    def cross(
        origin: tuple[float, float],
        left: tuple[float, float],
        right: tuple[float, float],
    ) -> float:
        return (left[0] - origin[0]) * (right[1] - origin[1]) - (
            left[1] - origin[1]
        ) * (right[0] - origin[0])

    first_cross_start = cross(first_start, first_end, second_start)
    first_cross_end = cross(first_start, first_end, second_end)
    second_cross_start = cross(second_start, second_end, first_start)
    second_cross_end = cross(second_start, second_end, first_end)
    return (
        first_cross_start * first_cross_end < 0
        and second_cross_start * second_cross_end < 0
    )


def _compact_primitive_elevation(
    size: tuple[int, int],
    primitive: dict[str, Any],
    operation: dict[str, Any],
    allowed_bbox: list[int],
) -> tuple[array, dict[str, Any]]:
    width, height = size
    pixel_count = width * height
    dense = _dense_compact_nodes(
        primitive["nodes"],
        int(operation["spline_subdivisions"]),
    )
    if any(
        not math.isfinite(value)
        for node in dense
        for value in node.values()
    ):
        raise CalibrationError(
            f"topology_compact_ridges produced non-finite spline values in "
            f"{primitive['id']}"
        )
    minimum_allowed_x, minimum_allowed_y, maximum_allowed_x, maximum_allowed_y = (
        allowed_bbox
    )
    if any(
        not (
            minimum_allowed_x <= node["x"] <= maximum_allowed_x
            and minimum_allowed_y <= node["y"] <= maximum_allowed_y
        )
        for node in dense
    ):
        raise CalibrationError(
            "topology_compact_ridges spline leaves the declared allowed_bbox in "
            f"{primitive['id']}"
        )
    dense_segments = [
        ((first["x"], first["y"]), (second["x"], second["y"]))
        for first, second in zip(dense, dense[1:])
    ]
    for first_index, first_segment in enumerate(dense_segments):
        for second_index in range(first_index + 2, len(dense_segments)):
            if _proper_segments_intersect(
                first_segment[0],
                first_segment[1],
                dense_segments[second_index][0],
                dense_segments[second_index][1],
            ):
                raise CalibrationError(
                    "topology_compact_ridges spline self-intersects in "
                    f"{primitive['id']}"
                )
    elevation = array("d", [0.0]) * pixel_count
    total_arc_length = dense[-1]["arc_length"]
    endpoint_taper = float(operation["endpoint_taper_px"])
    light_x, light_y, _ = operation["light_vector_xyz"]
    for first, second in zip(dense, dense[1:]):
        dx = second["x"] - first["x"]
        dy = second["y"] - first["y"]
        length_squared = dx * dx + dy * dy
        if length_squared == 0:
            raise CalibrationError(
                f"topology_compact_ridges produced a zero-length dense segment in "
                f"{primitive['id']}"
            )
        length = math.sqrt(length_squared)
        positive_normal_x = -dy / length
        positive_normal_y = dx / length
        positive_side_is_lit = (
            positive_normal_x * light_x + positive_normal_y * light_y >= 0
        )
        reach = math.ceil(
            max(
                first["lit_width"],
                first["shadow_width"],
                second["lit_width"],
                second["shadow_width"],
            )
        )
        minimum_x = max(0, math.floor(min(first["x"], second["x"]) - reach))
        maximum_x = min(
            width - 1,
            math.ceil(max(first["x"], second["x"]) + reach),
        )
        minimum_y = max(0, math.floor(min(first["y"], second["y"]) - reach))
        maximum_y = min(
            height - 1,
            math.ceil(max(first["y"], second["y"]) + reach),
        )
        for y in range(minimum_y, maximum_y + 1):
            row = y * width
            for x in range(minimum_x, maximum_x + 1):
                projection = (
                    (x - first["x"]) * dx + (y - first["y"]) * dy
                ) / length_squared
                progress = max(0.0, min(1.0, projection))
                closest_x = first["x"] + progress * dx
                closest_y = first["y"] + progress * dy
                signed_distance = (
                    dx * (y - closest_y) - dy * (x - closest_x)
                ) / length
                point_is_positive = signed_distance >= 0
                if point_is_positive == positive_side_is_lit:
                    half_width = first["lit_width"] + progress * (
                        second["lit_width"] - first["lit_width"]
                    )
                else:
                    half_width = first["shadow_width"] + progress * (
                        second["shadow_width"] - first["shadow_width"]
                    )
                ratio_squared = (signed_distance * signed_distance) / (
                    half_width * half_width
                )
                if ratio_squared >= 1:
                    continue
                local_arc = first["arc_length"] + progress * (
                    second["arc_length"] - first["arc_length"]
                )
                start_taper = _smoothstep5(
                    max(0.0, min(1.0, local_arc / endpoint_taper))
                )
                end_taper = _smoothstep5(
                    max(
                        0.0,
                        min(1.0, (total_arc_length - local_arc) / endpoint_taper),
                    )
                )
                local_height = first["height"] + progress * (
                    second["height"] - first["height"]
                )
                kernel = 1 - ratio_squared
                contribution = (
                    local_height
                    * start_taper
                    * end_taper
                    * kernel
                    * kernel
                    * kernel
                )
                if not 0 <= contribution <= 1 or not math.isfinite(contribution):
                    raise CalibrationError(
                        f"topology_compact_ridges contribution outside [0,1] in "
                        f"{primitive['id']}"
                    )
                index = row + x
                if contribution > elevation[index]:
                    elevation[index] = contribution
    return elevation, {
        "id": primitive["id"],
        "role": primitive["role"],
        "node_ids": [node["id"] for node in primitive["nodes"]],
        "support_pixels": sum(value > 0 for value in elevation),
        "maximum_elevation": round(max(elevation, default=0), 6),
        "arc_length_px": round(total_arc_length, 6),
        "dense_curve_bbox": [
            round(min(node["x"] for node in dense), 6),
            round(min(node["y"] for node in dense), 6),
            round(max(node["x"] for node in dense), 6),
            round(max(node["y"] for node in dense), 6),
        ],
    }


def _compact_ridge_network_field(
    size: tuple[int, int],
    definition: dict[str, Any],
    operation: dict[str, Any],
) -> tuple[array, bytearray, dict[str, Any]]:
    width, height = size
    pixel_count = width * height
    combined_elevation = array("d", [0.0]) * pixel_count
    contribution_count = bytearray(pixel_count)
    metrics = []
    for primitive in sorted(definition["primitives"], key=lambda item: item["id"]):
        elevation, primitive_metrics = _compact_primitive_elevation(
            size,
            primitive,
            operation,
            definition["allowed_bbox"],
        )
        for index, value in enumerate(elevation):
            if value <= 0:
                continue
            contribution_count[index] += 1
            combined_elevation[index] += (1 - combined_elevation[index]) * value
        metrics.append(primitive_metrics)

    if any(not 0 <= value <= 1 or not math.isfinite(value) for value in combined_elevation):
        raise CalibrationError(
            f"topology_compact_ridges union outside [0,1] in {definition['region_id']}"
        )
    encoded_elevation = Image.new("L", size)
    encoded_elevation.putdata([round(value * 255) for value in combined_elevation])
    smoothed_elevation = encoded_elevation.filter(
        ImageFilter.GaussianBlur(radius=operation["elevation_smoothing_radius_px"])
    )
    try:
        elevation_values = bytes(smoothed_elevation.get_flattened_data())
    finally:
        encoded_elevation.close()
        smoothed_elevation.close()

    gradient_step = int(operation["hillshade_gradient_step_px"])
    vertical_scale = float(operation["hillshade_vertical_scale"])
    light_x, light_y, light_z = operation["light_vector_xyz"]
    light_length = math.sqrt(light_x * light_x + light_y * light_y + light_z * light_z)
    if not math.isfinite(light_length) or light_length <= 0:
        raise CalibrationError("topology_compact_ridges light vector must be finite and nonzero")
    light_x /= light_length
    light_y /= light_length
    light_z /= light_length
    tanh_gain = float(operation["hillshade_tanh_gain"])
    balance = float(operation["hillshade_balance"])
    asymmetry = float(operation["hillshade_asymmetry"])
    asymmetry_scale = float(operation["hillshade_asymmetry_scale"])
    raw = array("d", [0.0]) * pixel_count
    for y in range(height):
        negative_y = max(0, y - gradient_step)
        positive_y = min(height - 1, y + gradient_step)
        row = y * width
        negative_row = negative_y * width
        positive_row = positive_y * width
        for x in range(width):
            index = row + x
            if combined_elevation[index] <= 0:
                continue
            negative_x = max(0, x - gradient_step)
            positive_x = min(width - 1, x + gradient_step)
            gradient_x = (
                elevation_values[row + positive_x]
                - elevation_values[row + negative_x]
            ) / max(1, positive_x - negative_x) / 255
            gradient_y = (
                elevation_values[positive_row + x]
                - elevation_values[negative_row + x]
            ) / max(1, positive_y - negative_y) / 255
            normal_x = -vertical_scale * gradient_x
            normal_y = -vertical_scale * gradient_y
            normal_length = math.sqrt(normal_x * normal_x + normal_y * normal_y + 1)
            dot = (
                normal_x * light_x + normal_y * light_y + light_z
            ) / normal_length
            shaped = math.tanh(tanh_gain * (dot - light_z))
            raw[index] = shaped * (
                balance - asymmetry * math.tanh(shaped / asymmetry_scale)
            )

    encoding_scale = float(operation["intermediate_field_scale"])
    encoded_values = [128 + round(value * encoding_scale) for value in raw]
    if min(encoded_values, default=128) < 0 or max(encoded_values, default=128) > 255:
        raise CalibrationError(
            f"topology_compact_ridges hillshade clipped in {definition['region_id']}"
        )
    encoded_field = Image.new("L", size)
    encoded_field.putdata(encoded_values)
    smoothed_field = encoded_field.filter(
        ImageFilter.GaussianBlur(radius=operation["hillshade_smoothing_radius_px"])
    )
    try:
        smoothed_values = bytes(smoothed_field.get_flattened_data())
    finally:
        encoded_field.close()
        smoothed_field.close()
    if (
        operation["field_tail_transform"]
        != "signed-tail-attenuation-then-tanh-extrema-cap"
    ):
        raise CalibrationError("unsupported topology_compact_ridges field tail transform")
    result = array("d", [0.0]) * pixel_count
    tail_activation_scale = float(operation["field_tail_activation_scale"])
    extrema_scale = float(operation["field_extrema_scale"])
    for index, support in enumerate(combined_elevation):
        if support > 0:
            value = (smoothed_values[index] - 128) / encoding_scale
            result[index] = _signed_tail_transform(
                value,
                tail_activation_scale,
                extrema_scale,
            )
    support_mask = bytearray(1 if value > 0 else 0 for value in combined_elevation)
    return result, support_mask, {
        "region_id": definition["region_id"],
        "primitives": metrics,
        "union_support_pixels": sum(value > 0 for value in combined_elevation),
        "maximum_primitive_contributors": max(contribution_count, default=0),
        "overlap_pixels": sum(value > 1 for value in contribution_count),
        "minimum_combined_field": round(min(result, default=0), 6),
        "maximum_combined_field": round(max(result, default=0), 6),
    }


def _derive_calibration(
    source: Image.Image,
    transfer_control: dict[str, Any],
    calibration: dict[str, Any],
    relief: Any,
    composite: Any,
) -> tuple[Image.Image, Image.Image, Image.Image, dict[str, Any]]:
    width, height = source.size
    pixel_count = width * height
    source_values = source.tobytes()
    deltas = [0] * pixel_count
    permission = bytearray(pixel_count)
    operation_metrics: dict[str, Any]
    topology_residual_contract: tuple[bytes, bytes, bytes] | None = None

    if "regional_gain" in calibration:
        operation = calibration["regional_gain"]
        polygon = _find_region(transfer_control, operation["region_id"])
        region = composite.build_mask(
            relief._one_region_control(
                transfer_control,
                polygon,
                include_exclusions=False,
            )
        )
        road_guard = relief._draw_strokes(
            transfer_control.get("exclude_strokes", []),
            source.size,
            width_override=int(
                transfer_control["low_frequency_transfer"]["road_signal_guard_width_px"]
            ),
        )
        luminance = ImageOps.grayscale(source)
        low_pass = luminance.filter(
            ImageFilter.GaussianBlur(radius=calibration["low_pass"]["radius_px"])
        )
        try:
            region_values = bytes(region.get_flattened_data())
            guard_values = bytes(road_guard.get_flattened_data())
            low_values = bytes(low_pass.get_flattened_data())
            sample = [
                low_values[index]
                for index, alpha in enumerate(region_values)
                if alpha == 255 and guard_values[index] == 0
            ]
            median = relief._quantile(sample, 0.5)
            gain_delta = float(operation["gain"]) - 1.0
            for index, alpha in enumerate(region_values):
                if alpha == 0:
                    continue
                permission[index] = alpha
                deltas[index] = round(
                    (low_values[index] - median) * gain_delta * alpha / 255
                )
        finally:
            region.close()
            road_guard.close()
            luminance.close()
            low_pass.close()
        operation_metrics = {
            "type": "regional-low-pass-gain",
            "region_id": operation["region_id"],
            "low_pass_radius_px": calibration["low_pass"]["radius_px"],
            "gain": operation["gain"],
            "low_pass_median_levels": round(median, 4),
            "sample_pixels": len(sample),
        }
    elif "minimum_areal_support" in calibration:
        operation = calibration["minimum_areal_support"]
        polygon = _find_region(transfer_control, operation["region_id"])
        region = composite.build_mask(
            relief._one_region_control(
                transfer_control,
                polygon,
                include_exclusions=False,
            )
        )
        try:
            region_values = bytes(region.get_flattened_data())
        finally:
            region.close()
        center_x, center_y = operation["center"]
        radius_x, radius_y = operation["radii"]
        amplitude = operation["amplitude_levels"]
        for y in range(max(0, center_y - radius_y), min(height, center_y + radius_y + 1)):
            row = y * width
            for x in range(max(0, center_x - radius_x), min(width, center_x + radius_x + 1)):
                normalized_x = (x - center_x) / radius_x
                normalized_y = (y - center_y) / radius_y
                radius_squared = normalized_x * normalized_x + normalized_y * normalized_y
                if radius_squared >= 1.0:
                    continue
                index = row + x
                region_alpha = region_values[index]
                if region_alpha == 0:
                    continue
                radius = math.sqrt(radius_squared)
                weight = math.cos(math.pi / 2 * radius) ** 2
                operation_delta = round(amplitude * weight)
                permission[index] = round(255 * weight * region_alpha / 255)
                deltas[index] = round(operation_delta * region_alpha / 255)
        operation_metrics = {
            "type": "minimum-areal-support",
            "region_id": operation["region_id"],
            "target_quadrant": operation["target_quadrant"],
            "shape": operation["shape"],
            "center": operation["center"],
            "radii": operation["radii"],
            "amplitude_levels": amplitude,
        }
    elif "topology_mesh" in calibration:
        operation = calibration["topology_mesh"]
        region_ids = operation["preflight_region_ids"]
        for region_id in region_ids:
            _find_region(transfer_control, region_id)

        mesh = operation["grid"]
        mesh_width = int(mesh["width"])
        mesh_height = int(mesh["height"])
        mesh_values = mesh["values"]
        if len(mesh_values) != mesh_width * mesh_height:
            raise CalibrationError(
                "topology_mesh grid values must equal width multiplied by height"
            )
        grid = Image.new("L", (mesh_width, mesh_height))
        grid.putdata(mesh_values)
        surface = grid.resize(source.size, Image.Resampling.BICUBIC)
        smoothed_surface = surface.filter(
            ImageFilter.GaussianBlur(radius=operation["smoothing_radius_px"])
        )
        luminance = ImageOps.grayscale(source)
        source_low_pass = luminance.filter(
            ImageFilter.GaussianBlur(radius=operation["source_low_pass_radius_px"])
        )
        try:
            target_values = bytes(smoothed_surface.get_flattened_data())
            source_low_values = bytes(source_low_pass.get_flattened_data())
            source_luminance_values = bytes(luminance.get_flattened_data())
            topology_residual_contract = (
                target_values,
                source_low_values,
                source_luminance_values,
            )
            envelope = operation["permission_envelope"]
            zero_through_x = envelope["zero_through_x"]
            opaque_from_x = envelope["opaque_from_x"]
            if not 0 <= zero_through_x < opaque_from_x < width:
                raise CalibrationError(
                    "topology_mesh permission envelope must satisfy "
                    "0 <= zero_through_x < opaque_from_x < canvas width"
                )
            ramp_width = opaque_from_x - zero_through_x
            for x in range(zero_through_x + 1, width):
                if x >= opaque_from_x:
                    alpha = 255
                else:
                    progress = (x - zero_through_x) / ramp_width
                    alpha = round(255 * (0.5 - 0.5 * math.cos(math.pi * progress)))
                for y in range(height):
                    index = y * width + x
                    permission[index] = alpha
                    deltas[index] = round(
                        (target_values[index] - source_low_values[index]) * alpha / 255
                    )
        finally:
            grid.close()
            surface.close()
            smoothed_surface.close()
            luminance.close()
            source_low_pass.close()
        operation_metrics = {
            "type": "topology-mesh-replacement",
            "preflight_region_ids": region_ids,
            "grid_width": mesh_width,
            "grid_height": mesh_height,
            "grid_minimum_level": min(mesh_values),
            "grid_maximum_level": max(mesh_values),
            "interpolation": operation["interpolation"],
            "smoothing_radius_px": operation["smoothing_radius_px"],
            "source_low_pass_radius_px": operation["source_low_pass_radius_px"],
            "permission_envelope": operation["permission_envelope"],
            "preserve_high_frequency_residual": operation[
                "preserve_high_frequency_residual"
            ],
        }
    elif "topology_zones" in calibration:
        operation = calibration["topology_zones"]
        region_ids = operation["preflight_region_ids"]
        for region_id in region_ids:
            _find_region(transfer_control, region_id)

        zones = operation["zones"]
        zone_ids = [zone["id"] for zone in zones]
        if len(zone_ids) != len(set(zone_ids)):
            raise CalibrationError("topology_zones zone ids must be unique")
        for region_id in region_ids:
            roles = [
                zone["role"]
                for zone in zones
                if zone["region_id"] == region_id
            ]
            required_once = ("dominant-massif", "shaded-slope", "saddle")
            if any(roles.count(role) != 1 for role in required_once):
                raise CalibrationError(
                    "topology_zones requires exactly one dominant-massif, "
                    f"shaded-slope, and saddle in {region_id}"
                )
            foothill_count = roles.count("foothill")
            if not 2 <= foothill_count <= 3 or len(roles) != 3 + foothill_count:
                raise CalibrationError(
                    f"topology_zones requires two or three foothills and no "
                    f"unknown roles in {region_id}"
                )
        for zone in zones:
            for x, y in zone["points"]:
                if not 0 <= x < width or not 0 <= y < height:
                    raise CalibrationError(
                        f"topology_zones point outside canvas in {zone['id']}: "
                        f"[{x}, {y}]"
                    )

        surface = Image.new("L", source.size, operation["base_level"])
        draw = ImageDraw.Draw(surface)
        for zone in zones:
            draw.polygon(
                [tuple(point) for point in zone["points"]],
                fill=zone["level"],
            )
        smoothed_surface = surface.filter(
            ImageFilter.GaussianBlur(radius=operation["smoothing_radius_px"])
        )
        luminance = ImageOps.grayscale(source)
        source_low_pass = luminance.filter(
            ImageFilter.GaussianBlur(radius=operation["source_low_pass_radius_px"])
        )
        try:
            target_values = bytes(smoothed_surface.get_flattened_data())
            source_low_values = bytes(source_low_pass.get_flattened_data())
            source_luminance_values = bytes(luminance.get_flattened_data())
            topology_residual_contract = (
                target_values,
                source_low_values,
                source_luminance_values,
            )
            envelope = operation["permission_envelope"]
            zero_through_x = envelope["zero_through_x"]
            opaque_from_x = envelope["opaque_from_x"]
            if not 0 <= zero_through_x < opaque_from_x < width:
                raise CalibrationError(
                    "topology_zones permission envelope must satisfy "
                    "0 <= zero_through_x < opaque_from_x < canvas width"
                )
            ramp_width = opaque_from_x - zero_through_x
            for x in range(zero_through_x + 1, width):
                if x >= opaque_from_x:
                    alpha = 255
                else:
                    progress = (x - zero_through_x) / ramp_width
                    alpha = round(255 * (0.5 - 0.5 * math.cos(math.pi * progress)))
                for y in range(height):
                    index = y * width + x
                    permission[index] = alpha
                    deltas[index] = round(
                        (target_values[index] - source_low_values[index]) * alpha / 255
                    )
        finally:
            surface.close()
            smoothed_surface.close()
            luminance.close()
            source_low_pass.close()
        operation_metrics = {
            "type": "topology-zones-replacement",
            "preflight_region_ids": region_ids,
            "base_level": operation["base_level"],
            "zones": [
                {
                    "id": zone["id"],
                    "region_id": zone["region_id"],
                    "role": zone["role"],
                    "level": zone["level"],
                    "point_count": len(zone["points"]),
                }
                for zone in zones
            ],
            "zone_minimum_level": min(zone["level"] for zone in zones),
            "zone_maximum_level": max(zone["level"] for zone in zones),
            "draw_order": "array-order-later-zones-overpaint-earlier-zones",
            "smoothing_radius_px": operation["smoothing_radius_px"],
            "source_low_pass_radius_px": operation["source_low_pass_radius_px"],
            "permission_envelope": operation["permission_envelope"],
            "preserve_high_frequency_residual": operation[
                "preserve_high_frequency_residual"
            ],
        }
    elif "topology_ridges" in calibration:
        operation = calibration["topology_ridges"]
        region_ids = operation["preflight_region_ids"]
        definitions = operation["regions"]
        if [definition["region_id"] for definition in definitions] != region_ids:
            raise CalibrationError(
                "topology_ridges regions must match preflight_region_ids in order"
            )
        for region_id in region_ids:
            _find_region(transfer_control, region_id)
        for definition in definitions:
            nodes = definition["ridge_nodes"]
            node_ids = [node["id"] for node in nodes]
            if len(node_ids) != len(set(node_ids)):
                raise CalibrationError(
                    f"topology_ridges ridge node ids must be unique in "
                    f"{definition['region_id']}"
                )
            saddle_indices = [
                index for index, node in enumerate(nodes) if node["role"] == "saddle"
            ]
            if len(saddle_indices) != 1 or saddle_indices[0] in {0, len(nodes) - 1}:
                raise CalibrationError(
                    "topology_ridges requires exactly one interior saddle node in "
                    f"{definition['region_id']}"
                )
            if sum(node["role"] == "crest" for node in nodes) < 2:
                raise CalibrationError(
                    f"topology_ridges requires at least two crest nodes in "
                    f"{definition['region_id']}"
                )
            foothill_ids = [item["id"] for item in definition["foothills"]]
            if len(foothill_ids) != len(set(foothill_ids)):
                raise CalibrationError(
                    f"topology_ridges foothill ids must be unique in "
                    f"{definition['region_id']}"
                )

        combined_target_delta = array("f", [0.0]) * pixel_count
        full_mask = composite.build_mask(transfer_control)
        guard = relief._draw_strokes(
            transfer_control.get("exclude_strokes", []),
            source.size,
            width_override=int(
                transfer_control["low_frequency_transfer"][
                    "road_signal_guard_width_px"
                ]
            ),
        )
        full_mask_values = bytes(full_mask.get_flattened_data())
        guard_values = bytes(guard.get_flattened_data())
        region_operation_metrics: list[dict[str, Any]] = []
        warped_x_values, warped_y_values = _warped_coordinates(source.size)
        try:
            for definition in definitions:
                polygon = _find_region(transfer_control, definition["region_id"])
                region = composite.build_mask(
                    relief._one_region_control(
                        transfer_control,
                        polygon,
                        include_exclusions=False,
                    )
                )
                try:
                    region_values = bytes(region.get_flattened_data())
                finally:
                    region.close()
                raw_field, primitive_metrics = _continuous_ridge_field(
                    source.size,
                    warped_x_values,
                    warped_y_values,
                    definition,
                    operation,
                )
                samples = [
                    raw_field[index]
                    for index, alpha in enumerate(region_values)
                    if alpha == 255
                    and full_mask_values[index] == 255
                    and guard_values[index] == 0
                ]
                raw_q10 = relief._quantile(samples, 0.1)
                raw_q90 = relief._quantile(samples, 0.9)
                raw_span = raw_q90 - raw_q10
                if raw_span <= 0:
                    raise CalibrationError(
                        f"topology_ridges raw span is zero in {definition['region_id']}"
                    )
                gain = operation["target_input_q90_q10_levels"] / raw_span
                for index, value in enumerate(raw_field):
                    combined_target_delta[index] += value * gain
                region_operation_metrics.append(
                    {
                        "region_id": definition["region_id"],
                        **primitive_metrics,
                        "raw_q10_levels": round(raw_q10, 6),
                        "raw_q90_levels": round(raw_q90, 6),
                        "raw_q90_q10_levels": round(raw_span, 6),
                        "target_span_gain": round(gain, 6),
                    }
                )
        finally:
            full_mask.close()
            guard.close()

        minimum_target = min(combined_target_delta, default=0)
        maximum_target = max(combined_target_delta, default=0)
        if minimum_target < -120 or maximum_target > 120:
            raise CalibrationError(
                "topology_ridges normalized target exceeds the safe plate range"
            )
        target_values = bytes(
            max(0, min(255, 128 + round(value)))
            for value in combined_target_delta
        )
        luminance = ImageOps.grayscale(source)
        source_low_pass = luminance.filter(
            ImageFilter.GaussianBlur(radius=operation["source_low_pass_radius_px"])
        )
        try:
            source_low_values = bytes(source_low_pass.get_flattened_data())
            source_luminance_values = bytes(luminance.get_flattened_data())
            topology_residual_contract = (
                target_values,
                source_low_values,
                source_luminance_values,
            )
            envelope = operation["permission_envelope"]
            zero_through_x = envelope["zero_through_x"]
            opaque_from_x = envelope["opaque_from_x"]
            if not 0 <= zero_through_x < opaque_from_x < width:
                raise CalibrationError(
                    "topology_ridges permission envelope must satisfy "
                    "0 <= zero_through_x < opaque_from_x < canvas width"
                )
            ramp_width = opaque_from_x - zero_through_x
            for x in range(zero_through_x + 1, width):
                if x >= opaque_from_x:
                    alpha = 255
                else:
                    progress = (x - zero_through_x) / ramp_width
                    alpha = round(255 * (0.5 - 0.5 * math.cos(math.pi * progress)))
                for y in range(height):
                    index = y * width + x
                    permission[index] = alpha
                    deltas[index] = round(
                        (target_values[index] - source_low_values[index]) * alpha / 255
                    )
        finally:
            luminance.close()
            source_low_pass.close()
        operation_metrics = {
            "type": "topology-continuous-ridges-replacement",
            "preflight_region_ids": region_ids,
            "regions": region_operation_metrics,
            "target_input_q90_q10_levels": operation[
                "target_input_q90_q10_levels"
            ],
            "elevation_smoothing_radius_px": operation[
                "elevation_smoothing_radius_px"
            ],
            "hillshade_gradient_step_px": operation["hillshade_gradient_step_px"],
            "hillshade_gradient_scale": operation["hillshade_gradient_scale"],
            "light_vector_xyz": operation["light_vector_xyz"],
            "hillshade_weight": operation["hillshade_weight"],
            "elevation_weight": operation["elevation_weight"],
            "intermediate_field_scale": operation["intermediate_field_scale"],
            "hillshade_smoothing_radius_px": operation[
                "hillshade_smoothing_radius_px"
            ],
            "normalized_target_minimum_levels": round(minimum_target, 6),
            "normalized_target_maximum_levels": round(maximum_target, 6),
            "source_low_pass_radius_px": operation["source_low_pass_radius_px"],
            "permission_envelope": operation["permission_envelope"],
            "preserve_high_frequency_residual": operation[
                "preserve_high_frequency_residual"
            ],
        }
    else:
        operation = calibration["topology_compact_ridges"]
        region_ids = operation["preflight_region_ids"]
        definitions = operation["regions"]
        if [definition["region_id"] for definition in definitions] != region_ids:
            raise CalibrationError(
                "topology_compact_ridges regions must match preflight_region_ids "
                "in order"
            )
        for region_id in region_ids:
            _find_region(transfer_control, region_id)
        all_primitive_ids: set[str] = set()
        all_node_ids: set[str] = set()
        for definition in definitions:
            minimum_x, minimum_y, maximum_x, maximum_y = definition["allowed_bbox"]
            if not (
                0 <= minimum_x < maximum_x < width
                and 0 <= minimum_y < maximum_y < height
            ):
                raise CalibrationError(
                    "topology_compact_ridges allowed_bbox must be ordered and inside "
                    f"the canvas in {definition['region_id']}"
                )
            primitives = definition["primitives"]
            roles = [primitive["role"] for primitive in primitives]
            if roles.count("main-ridge") != 1 or roles.count("foothill") != 2:
                raise CalibrationError(
                    "topology_compact_ridges requires one main-ridge and two "
                    f"foothills in {definition['region_id']}"
                )
            primitive_ids = [primitive["id"] for primitive in primitives]
            if (
                len(primitive_ids) != len(set(primitive_ids))
                or any(item in all_primitive_ids for item in primitive_ids)
            ):
                raise CalibrationError(
                    "topology_compact_ridges primitive ids must be globally unique"
                )
            all_primitive_ids.update(primitive_ids)
            for primitive in primitives:
                nodes = primitive["nodes"]
                node_ids = [node["id"] for node in nodes]
                if (
                    len(node_ids) != len(set(node_ids))
                    or any(item in all_node_ids for item in node_ids)
                ):
                    raise CalibrationError(
                        "topology_compact_ridges node ids must be globally unique"
                    )
                all_node_ids.update(node_ids)
                if any(
                    first["point"] == second["point"]
                    for first, second in zip(nodes, nodes[1:])
                ):
                    raise CalibrationError(
                        f"topology_compact_ridges consecutive points must differ in "
                        f"{primitive['id']}"
                    )
                if nodes[0]["height"] != 0 or nodes[-1]["height"] != 0:
                    raise CalibrationError(
                        f"topology_compact_ridges endpoints must have zero height "
                        f"in {primitive['id']}"
                    )
                if any(node["height"] <= 0 for node in nodes[1:-1]):
                    raise CalibrationError(
                        "topology_compact_ridges requires every interior height to "
                        f"be positive in {primitive['id']}"
                    )
                for node in nodes:
                    minimum_width = min(
                        node["lit_half_width_px"],
                        node["shadow_half_width_px"],
                    )
                    maximum_width = max(
                        node["lit_half_width_px"],
                        node["shadow_half_width_px"],
                    )
                    if maximum_width / minimum_width > 3:
                        raise CalibrationError(
                            "topology_compact_ridges lit/shadow width ratio exceeds "
                            f"3 in {node['id']}"
                        )
                node_roles = [node["role"] for node in nodes]
                if primitive["role"] == "main-ridge":
                    if node_roles.count("saddle") != 1 or node_roles.count("crest") < 2:
                        raise CalibrationError(
                            "topology_compact_ridges main-ridge requires one saddle "
                            f"and at least two crests in {primitive['id']}"
                        )
                elif node_roles.count("crest") != 1 or "saddle" in node_roles:
                    raise CalibrationError(
                        "topology_compact_ridges foothill requires exactly one crest "
                        f"and no saddle in {primitive['id']}"
                    )

        combined_target_delta = array("d", [0.0]) * pixel_count
        region_owner = bytearray(pixel_count)
        full_mask = composite.build_mask(transfer_control)
        guard = relief._draw_strokes(
            transfer_control.get("exclude_strokes", []),
            source.size,
            width_override=int(
                transfer_control["low_frequency_transfer"][
                    "road_signal_guard_width_px"
                ]
            ),
        )
        full_mask_values = bytes(full_mask.get_flattened_data())
        guard_values = bytes(guard.get_flattened_data())
        region_operation_metrics: list[dict[str, Any]] = []
        try:
            for region_number, definition in enumerate(definitions, start=1):
                polygon = _find_region(transfer_control, definition["region_id"])
                region = composite.build_mask(
                    relief._one_region_control(
                        transfer_control,
                        polygon,
                        include_exclusions=False,
                    )
                )
                try:
                    region_values = bytes(region.get_flattened_data())
                finally:
                    region.close()
                raw_field, region_support, field_metrics = _compact_ridge_network_field(
                    source.size,
                    definition,
                    operation,
                )
                for index, supported in enumerate(region_support):
                    if not supported:
                        continue
                    if region_owner[index]:
                        raise CalibrationError(
                            "topology_compact_ridges region supports overlap between "
                            "independently normalized regions"
                        )
                    region_owner[index] = region_number
                samples = [
                    raw_field[index]
                    for index, alpha in enumerate(region_values)
                    if alpha == 255
                    and full_mask_values[index] == 255
                    and guard_values[index] == 0
                ]
                if not samples:
                    raise CalibrationError(
                        "topology_compact_ridges has no unguarded opaque calibration "
                        f"samples in {definition['region_id']}"
                    )
                raw_q10 = relief._quantile(samples, 0.1)
                raw_q90 = relief._quantile(samples, 0.9)
                raw_span = raw_q90 - raw_q10
                if raw_span <= 0:
                    raise CalibrationError(
                        "topology_compact_ridges raw span is zero in "
                        f"{definition['region_id']}"
                    )
                gain = operation["target_input_q90_q10_levels"] / raw_span
                if gain > operation["maximum_target_span_gain"]:
                    raise CalibrationError(
                        "topology_compact_ridges target span gain exceeds its maximum "
                        f"in {definition['region_id']}: {gain}"
                    )
                for index, value in enumerate(raw_field):
                    combined_target_delta[index] += value * gain
                region_operation_metrics.append(
                    {
                        **field_metrics,
                        "raw_q10_levels": round(raw_q10, 6),
                        "raw_q90_levels": round(raw_q90, 6),
                        "raw_q90_q10_levels": round(raw_span, 6),
                        "target_span_gain": round(gain, 6),
                    }
                )
        finally:
            full_mask.close()
            guard.close()

        minimum_target = min(combined_target_delta, default=0)
        maximum_target = max(combined_target_delta, default=0)
        if minimum_target < -120 or maximum_target > 120:
            raise CalibrationError(
                "topology_compact_ridges normalized target exceeds the safe plate range"
            )
        integer_target_values = [128 + round(value) for value in combined_target_delta]
        if min(integer_target_values, default=128) < 0 or max(
            integer_target_values, default=128
        ) > 255:
            raise CalibrationError(
                "topology_compact_ridges target conversion would leave the L8 range"
            )
        target_values = bytes(integer_target_values)
        luminance = ImageOps.grayscale(source)
        source_low_pass = luminance.filter(
            ImageFilter.GaussianBlur(radius=operation["source_low_pass_radius_px"])
        )
        try:
            source_low_values = bytes(source_low_pass.get_flattened_data())
            source_luminance_values = bytes(luminance.get_flattened_data())
            topology_residual_contract = (
                target_values,
                source_low_values,
                source_luminance_values,
            )
            envelope = operation["permission_envelope"]
            zero_through_x = envelope["zero_through_x"]
            opaque_from_x = envelope["opaque_from_x"]
            if not 0 <= zero_through_x < opaque_from_x < width:
                raise CalibrationError(
                    "topology_compact_ridges permission envelope must satisfy "
                    "0 <= zero_through_x < opaque_from_x < canvas width"
                )
            ramp_width = opaque_from_x - zero_through_x
            for x in range(zero_through_x + 1, width):
                if x >= opaque_from_x:
                    alpha = 255
                else:
                    progress = (x - zero_through_x) / ramp_width
                    alpha = round(255 * (0.5 - 0.5 * math.cos(math.pi * progress)))
                for y in range(height):
                    index = y * width + x
                    permission[index] = alpha
                    deltas[index] = round(
                        (target_values[index] - source_low_values[index]) * alpha / 255
                    )
        finally:
            luminance.close()
            source_low_pass.close()
        operation_metrics = {
            "type": "topology-compact-ridge-network-replacement",
            "preflight_region_ids": region_ids,
            "regions": region_operation_metrics,
            "target_input_q90_q10_levels": operation[
                "target_input_q90_q10_levels"
            ],
            "maximum_target_span_gain": operation["maximum_target_span_gain"],
            "spline": operation["spline"],
            "spline_subdivisions": operation["spline_subdivisions"],
            "cross_section_kernel": operation["cross_section_kernel"],
            "primitive_composition": operation["primitive_composition"],
            "elevation_smoothing_radius_px": operation[
                "elevation_smoothing_radius_px"
            ],
            "hillshade_gradient_step_px": operation["hillshade_gradient_step_px"],
            "hillshade_vertical_scale": operation["hillshade_vertical_scale"],
            "light_vector_xyz": operation["light_vector_xyz"],
            "hillshade_tanh_gain": operation["hillshade_tanh_gain"],
            "hillshade_balance": operation["hillshade_balance"],
            "hillshade_asymmetry": operation["hillshade_asymmetry"],
            "hillshade_asymmetry_scale": operation[
                "hillshade_asymmetry_scale"
            ],
            "intermediate_field_scale": operation["intermediate_field_scale"],
            "hillshade_smoothing_radius_px": operation[
                "hillshade_smoothing_radius_px"
            ],
            "field_tail_transform": operation["field_tail_transform"],
            "field_tail_activation_scale": operation[
                "field_tail_activation_scale"
            ],
            "field_extrema_scale": operation["field_extrema_scale"],
            "normalized_target_minimum_levels": round(minimum_target, 6),
            "normalized_target_maximum_levels": round(maximum_target, 6),
            "source_low_pass_radius_px": operation["source_low_pass_radius_px"],
            "permission_envelope": operation["permission_envelope"],
            "preserve_high_frequency_residual": operation[
                "preserve_high_frequency_residual"
            ],
        }

    output_values = bytearray(source_values)
    clipping_pixels = 0
    maximum_rgb_delta_spread = 0
    chroma_changed_pixels = 0
    outside_permission_changed_pixels = 0
    changed_pixels = 0
    minimum_delta = 0
    maximum_delta = 0
    for pixel_index, delta in enumerate(deltas):
        offset = pixel_index * 3
        original = source_values[offset : offset + 3]
        changed_channels = [original[channel] + delta for channel in range(3)]
        if any(value < 0 or value > 255 for value in changed_channels):
            clipping_pixels += 1
            continue
        output_values[offset : offset + 3] = bytes(changed_channels)
        actual_deltas = [
            output_values[offset + channel] - original[channel] for channel in range(3)
        ]
        maximum_rgb_delta_spread = max(
            maximum_rgb_delta_spread,
            max(actual_deltas) - min(actual_deltas),
        )
        source_chroma = (original[0] - original[1], original[1] - original[2])
        output_chroma = (
            output_values[offset] - output_values[offset + 1],
            output_values[offset + 1] - output_values[offset + 2],
        )
        if source_chroma != output_chroma:
            chroma_changed_pixels += 1
        if bytes(output_values[offset : offset + 3]) != original:
            changed_pixels += 1
            if permission[pixel_index] == 0:
                outside_permission_changed_pixels += 1
        minimum_delta = min(minimum_delta, delta)
        maximum_delta = max(maximum_delta, delta)

    if clipping_pixels:
        raise CalibrationError(f"calibration would clip {clipping_pixels} RGB pixels")
    output = Image.frombytes("RGB", source.size, bytes(output_values))
    opaque_residual_identity_mismatch_pixels = 0
    if topology_residual_contract is not None:
        target_values, source_low_values, source_luminance_values = (
            topology_residual_contract
        )
        output_luminance = ImageOps.grayscale(output)
        try:
            output_luminance_values = bytes(output_luminance.get_flattened_data())
        finally:
            output_luminance.close()
        opaque_residual_identity_mismatch_pixels = sum(
            output_luminance_values[index] - target_values[index]
            != source_luminance_values[index] - source_low_values[index]
            for index, alpha in enumerate(permission)
            if alpha == 255
        )
    support = Image.frombytes("L", source.size, bytes(permission))
    field = Image.new("L", source.size)
    field.putdata([128 + value for value in deltas])
    metrics = {
        **operation_metrics,
        "support_pixels": sum(value > 0 for value in permission),
        "opaque_support_pixels": sum(value == 255 for value in permission),
        "changed_pixels": changed_pixels,
        "outside_permission_changed_pixels": outside_permission_changed_pixels,
        "left_48_percent_changed_pixels": sum(
            bytes(output_values[index * 3 : index * 3 + 3])
            != source_values[index * 3 : index * 3 + 3]
            for y in range(height)
            for index in range(y * width, y * width + int(width * 0.48))
        ),
        "minimum_channel_delta_levels": minimum_delta,
        "maximum_channel_delta_levels": maximum_delta,
        "maximum_absolute_channel_delta_levels": max(abs(minimum_delta), abs(maximum_delta)),
        "clipping_pixels": clipping_pixels,
        "maximum_rgb_delta_spread_levels": maximum_rgb_delta_spread,
        "chroma_changed_pixels": chroma_changed_pixels,
        "opaque_residual_identity_mismatch_pixels": (
            opaque_residual_identity_mismatch_pixels
        ),
    }
    return output, support, field, metrics


def _preflight_metrics(
    plate: Image.Image,
    transfer_path: Path,
    transfer_control: dict[str, Any],
    relief: Any,
) -> dict[str, Any]:
    base_path = _resolve_repo_path(
        transfer_control["source_image"]["path"], "transfer source_image.path"
    )
    transfer_contract, _ = relief._validate_control(
        transfer_control,
        transfer_path,
        base_path,
    )
    with Image.open(base_path) as opened:
        base = ImageOps.exif_transpose(opened).convert("RGB")
    base_luminance = ImageOps.grayscale(base)
    plate_luminance = ImageOps.grayscale(plate)
    mask: Image.Image | None = None
    try:
        applied, unmasked, region_metrics, mask = relief.derive_field(
            base_luminance,
            plate_luminance,
            transfer_control,
            transfer_contract,
        )
        mask_values = bytes(mask.get_flattened_data())
        quadrants = relief._region_quadrant_metrics(
            transfer_control,
            applied,
            mask_values,
        )
        composite = relief._load_composite_module()
        topology_values = bytearray(plate.width * plate.height)
        for polygon in transfer_control["include_polygons"]:
            region = composite.build_mask(
                relief._one_region_control(
                    transfer_control,
                    polygon,
                    include_exclusions=False,
                )
            )
            try:
                values = bytes(region.get_flattened_data())
            finally:
                region.close()
            for index, value in enumerate(values):
                topology_values[index] = max(topology_values[index], value)
        topology_trace_field = (
            applied
            if transfer_contract.get("relief_method") == "direct_plate"
            else unmasked
        )
        traceable = relief._traceable_components(
            topology_trace_field,
            bytes(topology_values),
            plate.size,
            transfer_contract,
        )
        road_indices = relief._road_core_indices(transfer_control, plate.size)
        road_changed = sum(applied[index] != 0 for index in road_indices)
        outside_changed = sum(
            applied[index] != 0 and mask_values[index] == 0
            for index in range(len(applied))
        )
        active = [index for index, value in enumerate(mask_values) if value > 0]
        maximum_absolute = max((abs(applied[index]) for index in active), default=0)
        field = Image.new("L", plate.size)
        field.putdata([128 + value for value in applied])
        blurred = field.filter(ImageFilter.GaussianBlur(radius=8))
        try:
            blurred_values = bytes(blurred.get_flattened_data())
        finally:
            blurred.close()
            field.close()
        high_frequency = [
            applied[index] - (blurred_values[index] - 128)
            for index in range(len(applied))
        ]
        active_hf = relief._high_frequency_metrics(high_frequency, active)
        return {
            "region_metrics": region_metrics,
            "region_quadrant_metrics": quadrants,
            "traceable_components": len(traceable),
            "road_changed_pixels": road_changed,
            "outside_mask_changed_pixels": outside_changed,
            "maximum_absolute_delta_levels": maximum_absolute,
            "active_high_frequency": active_hf,
        }
    finally:
        base.close()
        base_luminance.close()
        plate_luminance.close()
        if mask is not None:
            mask.close()


def _assert_expected_preflight(
    metrics: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    regions = {item["id"]: item for item in metrics["region_metrics"]}
    checks = {
        "north_east_input_q90_q10_levels": regions["north_east_range"][
            "input_plate_q90_q10_levels"
        ],
        "south_east_input_q90_q10_levels": regions["south_east_range"][
            "input_plate_q90_q10_levels"
        ],
        "north_east_bandpass_q90_q10_levels": regions["north_east_range"][
            "bandpass_q90_q10_levels"
        ],
        "south_east_bandpass_q90_q10_levels": regions["south_east_range"][
            "bandpass_q90_q10_levels"
        ],
        "north_east_final_q90_q10_levels": regions["north_east_range"][
            "final_q90_q10_levels"
        ],
        "south_east_final_q90_q10_levels": regions["south_east_range"][
            "final_q90_q10_levels"
        ],
        "region_quadrant_p90_absolute_delta_levels": [
            item["p90_absolute_delta_levels"]
            for item in metrics["region_quadrant_metrics"]
        ],
        "traceable_components": metrics["traceable_components"],
        "road_changed_pixels": metrics["road_changed_pixels"],
        "outside_mask_changed_pixels": metrics["outside_mask_changed_pixels"],
        "maximum_absolute_delta_levels": metrics["maximum_absolute_delta_levels"],
        "maximum_active_high_frequency_p99_levels": metrics[
            "active_high_frequency"
        ]["p99_levels"],
    }
    for key, actual in checks.items():
        if actual != expected[key]:
            raise CalibrationError(
                f"transfer preflight {key} mismatch: expected {expected[key]!r}, got {actual!r}"
            )


def _run_full_transfer_preflight(
    plate_png: bytes,
    transfer_path: Path,
    transfer_control: dict[str, Any],
    expected_status: str,
    expected_failure: str | None,
    relief: Any,
) -> dict[str, Any]:
    base_path = _resolve_repo_path(
        transfer_control["source_image"]["path"], "transfer source_image.path"
    )
    with tempfile.TemporaryDirectory(prefix="sstory-plate-preflight-") as directory:
        root = Path(directory)
        plate_path = root / "plate.png"
        plate_path.write_bytes(plate_png)
        outputs = {
            "candidate": root / "candidate.png",
            "mask": root / "mask.png",
            "field": root / "field.png",
            "report": root / "report.json",
        }
        try:
            report = relief.transfer(
                base_path=base_path,
                generated_path=plate_path,
                control_path=transfer_path,
                output_path=outputs["candidate"],
                mask_output_path=outputs["mask"],
                field_output_path=outputs["field"],
                report_path=outputs["report"],
            )
        except Exception as error:
            if expected_status != "rejected":
                raise CalibrationError(
                    f"full transfer preflight unexpectedly failed: {error}"
                ) from error
            if str(error) != expected_failure:
                raise CalibrationError(
                    "full transfer preflight failed for an unexpected reason: "
                    f"expected {expected_failure!r}, got {str(error)!r}"
                ) from error
            if any(path.exists() for path in outputs.values()):
                raise CalibrationError("rejected transfer preflight published partial outputs")
            if list(root.glob(".*.tmp")):
                raise CalibrationError("rejected transfer preflight left temporary artifacts")
            return {
                "status": "rejected",
                "failure": str(error),
                "published_candidate": False,
                "published_mask": False,
                "published_field": False,
                "published_report": False,
            }
        if expected_status != "passed":
            raise CalibrationError("full transfer preflight unexpectedly passed")
        if not all(path.is_file() for path in outputs.values()):
            raise CalibrationError("passed transfer preflight did not publish all four outputs")
        return {
            "status": "passed",
            "output_sha256": report["output_sha256"],
            "mask_sha256": report["mask_sha256"],
            "field_sha256": report["field_sha256"],
            "region_metrics": report["region_metrics"],
            "region_quadrant_metrics": report["region_quadrant_metrics"],
            "traceable_components": len(report["traceable_low_frequency_components"]),
            "road_changed_pixels": report["road_changed_pixels"],
            "outside_mask_changed_pixels": report["outside_mask_changed_pixels"],
            "maximum_absolute_delta_levels": report["maximum_absolute_delta_levels"],
            "active_high_frequency": report["active_high_frequency"],
        }


def _atomic_commit(artifacts: Sequence[tuple[Path, bytes]]) -> None:
    targets = [path.resolve() for path, _ in artifacts]
    if len(targets) != len(set(targets)):
        raise CalibrationError("calibration output paths must be distinct")
    existing = [path for path, _ in artifacts if path.exists()]
    if existing:
        raise CalibrationError(f"refusing to overwrite existing output: {existing[0]}")
    temporary: list[tuple[Path, Path]] = []
    committed: list[Path] = []
    try:
        for target, data in artifacts:
            target.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                mode="wb",
                delete=False,
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
            )
            temporary_path = Path(handle.name)
            try:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                handle.close()
            temporary.append((temporary_path, target))
        for temporary_path, target in temporary:
            os.replace(temporary_path, target)
            committed.append(target)
    except Exception:
        for temporary_path, _ in temporary:
            if temporary_path.exists():
                temporary_path.unlink()
        for target in committed:
            if target.exists():
                target.unlink()
        raise


def calibrate(
    *,
    control_path: Path,
    schema_path: Path,
    output_path: Path,
    support_output_path: Path,
    field_output_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    output_paths = (output_path, support_output_path, field_output_path, report_path)
    if len({path.resolve() for path in output_paths}) != len(output_paths):
        raise CalibrationError("output, support, field, and report paths must be distinct")
    if any(path.exists() for path in output_paths):
        existing = next(path for path in output_paths if path.exists())
        raise CalibrationError(f"refusing to overwrite existing output: {existing}")
    control = _load_json(control_path, "calibration control")
    if not isinstance(control, dict):
        raise CalibrationError("calibration control root must be an object")
    source_path, transfer_path, transfer_control, relief, composite = _validate_inputs(
        control,
        control_path,
        schema_path,
    )
    protected_inputs = {
        control_path.resolve(),
        schema_path.resolve(),
        source_path.resolve(),
        transfer_path.resolve(),
        _resolve_repo_path(
            control["transfer_control"]["raster_path"],
            "transfer_control.raster_path",
        ).resolve(),
        _resolve_repo_path(
            control["transfer_control"]["functional_reference_path"],
            "transfer_control.functional_reference_path",
        ).resolve(),
    }
    schema_lock = control.get("schema_lock")
    if isinstance(schema_lock, dict) and isinstance(schema_lock.get("path"), str):
        protected_inputs.add(
            _resolve_repo_path(schema_lock["path"], "schema_lock.path").resolve()
        )
    if any(path.resolve() in protected_inputs for path in output_paths):
        raise CalibrationError("calibration outputs must be distinct from every input")

    expected_size = (control["canvas"]["width"], control["canvas"]["height"])
    with Image.open(source_path) as opened:
        if opened.format != "PNG" or opened.mode != control["source_image"]["mode"]:
            raise CalibrationError("source image must be the declared RGB PNG")
        source = ImageOps.exif_transpose(opened).copy()
    if source.size != expected_size or source.mode != "RGB":
        source.close()
        raise CalibrationError(
            f"source image must be RGB at exact size {expected_size}, got {source.mode} {source.size}"
        )

    output: Image.Image | None = None
    support: Image.Image | None = None
    field: Image.Image | None = None
    try:
        safety = control["safety"]
        output, support, field, operation_metrics = _derive_calibration(
            source,
            transfer_control,
            control["calibration"],
            relief,
            composite,
        )
        deterministic_replay: dict[str, Any] = {
            "required": safety["require_deterministic_png"],
            "performed": False,
        }
        if "topology_compact_ridges" in control["calibration"]:
            replay_output: Image.Image | None = None
            replay_support: Image.Image | None = None
            replay_field: Image.Image | None = None
            try:
                (
                    replay_output,
                    replay_support,
                    replay_field,
                    replay_operation_metrics,
                ) = _derive_calibration(
                    source,
                    transfer_control,
                    control["calibration"],
                    relief,
                    composite,
                )
                image_pairs = (
                    ("plate", output, replay_output),
                    ("support", support, replay_support),
                    ("field", field, replay_field),
                )
                replay_hashes: dict[str, dict[str, str]] = {}
                for label, first_image, second_image in image_pairs:
                    first_pixels = first_image.tobytes()
                    second_pixels = second_image.tobytes()
                    first_png = _png_bytes(first_image)
                    second_png = _png_bytes(second_image)
                    if (
                        first_image.mode != second_image.mode
                        or first_image.size != second_image.size
                        or first_pixels != second_pixels
                        or first_png != second_png
                    ):
                        raise CalibrationError(
                            f"deterministic replay mismatch for {label}"
                        )
                    replay_hashes[label] = {
                        "raw_pixels_sha256": _sha256_bytes(first_pixels),
                        "png_sha256": _sha256_bytes(first_png),
                    }
                if replay_operation_metrics != operation_metrics:
                    raise CalibrationError(
                        "deterministic replay mismatch for operation metrics"
                    )
                deterministic_replay = {
                    "required": True,
                    "performed": True,
                    "derivations": 2,
                    "byte_identical": True,
                    "artifacts": replay_hashes,
                }
            finally:
                for replay_image in (replay_output, replay_support, replay_field):
                    if replay_image is not None:
                        replay_image.close()
        if operation_metrics["outside_permission_changed_pixels"] != 0:
            raise CalibrationError("calibration changed pixels outside its permission mask")
        if operation_metrics["clipping_pixels"] > safety["maximum_clipping_pixels"]:
            raise CalibrationError("calibration clipping gate failed")
        if (
            operation_metrics["maximum_rgb_delta_spread_levels"]
            > safety["maximum_rgb_delta_spread_levels"]
        ):
            raise CalibrationError("equal-channel calibration gate failed")
        if operation_metrics["chroma_changed_pixels"] != 0:
            raise CalibrationError("calibration changed source chroma")
        if (
            safety["require_source_high_frequency_residual_preserved"]
            and operation_metrics["opaque_residual_identity_mismatch_pixels"] != 0
        ):
            raise CalibrationError("opaque source residual identity gate failed")
        if (
            operation_metrics["maximum_absolute_channel_delta_levels"]
            > safety["maximum_absolute_raw_channel_delta_levels"]
        ):
            raise CalibrationError("raw calibration delta exceeds its maximum")

        source_hf = _high_frequency_metrics(
            source,
            safety["raw_high_frequency_gaussian_radius_px"],
            relief._quantile,
        )
        output_hf = _high_frequency_metrics(
            output,
            safety["raw_high_frequency_gaussian_radius_px"],
            relief._quantile,
        )
        if output_hf["rms_levels"] > safety["maximum_raw_high_frequency_rms_levels"]:
            raise CalibrationError(f"raw high-frequency RMS is {output_hf['rms_levels']}")
        if output_hf["p99_levels"] > safety["maximum_raw_high_frequency_p99_levels"]:
            raise CalibrationError(f"raw high-frequency P99 is {output_hf['p99_levels']}")
        if output_hf["maximum_levels"] > safety["maximum_raw_high_frequency_levels"]:
            raise CalibrationError(
                f"raw high-frequency maximum is {output_hf['maximum_levels']}"
            )

        plate_png = _png_bytes(output)
        support_png = _png_bytes(support)
        field_png = _png_bytes(field)
        preflight_metrics = _preflight_metrics(
            output,
            transfer_path,
            transfer_control,
            relief,
        )
        _assert_expected_preflight(
            preflight_metrics,
            control["expected_transfer_preflight"],
        )
        transfer_preflight = _run_full_transfer_preflight(
            plate_png,
            transfer_path,
            transfer_control,
            safety["expected_transfer_preflight_status"],
            safety["expected_transfer_failure"],
            relief,
        )
        if transfer_preflight["status"] != control["expected_transfer_preflight"]["status"]:
            raise CalibrationError("transfer preflight status does not match control")

        report = {
            "schema_version": "1.0.0",
            "id": control["report_id"],
            "status": "passed",
            "created_at": control["created_at"],
            "control_path": _relative(control_path),
            "schema_path": _relative(schema_path),
            "source_path": _relative(source_path),
            "transfer_control_path": _relative(transfer_path),
            "output_path": _relative(output_path),
            "support_output_path": _relative(support_output_path),
            "field_output_path": _relative(field_output_path),
            "operation": operation_metrics,
            "numeric_contract": control["numeric_contract"],
            "runtime": {
                "python_version": sys.version.split()[0],
                "pillow_version": PIL.__version__,
                "zlib_compile_version": zlib.ZLIB_VERSION,
                "zlib_runtime_version": zlib.ZLIB_RUNTIME_VERSION,
            },
            "deterministic_replay": deterministic_replay,
            "source_high_frequency": source_hf,
            "output_high_frequency": output_hf,
            "transfer_preflight_metrics": preflight_metrics,
            "full_transfer_preflight": transfer_preflight,
            "source_sha256": _sha256_file(source_path),
            "control_sha256": _sha256_file(control_path),
            "schema_sha256": _sha256_file(schema_path),
            "transfer_control_sha256": _sha256_file(transfer_path),
            "output_sha256": _sha256_bytes(plate_png),
            "support_sha256": _sha256_bytes(support_png),
            "field_sha256": _sha256_bytes(field_png),
        }
        report_bytes = (
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        _atomic_commit(
            (
                (output_path, plate_png),
                (support_output_path, support_png),
                (field_output_path, field_png),
                (report_path, report_bytes),
            )
        )
        return report
    finally:
        source.close()
        if output is not None:
            output.close()
        if support is not None:
            support.close()
        if field is not None:
            field.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", type=Path, default=DEFAULT_CONTROL)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=DEFAULT_SUPPORT_OUTPUT)
    parser.add_argument("--field-output", type=Path, default=DEFAULT_FIELD_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.control.resolve() != DEFAULT_CONTROL.resolve() and any(
        path.resolve() == default.resolve()
        for path, default in (
            (args.output, DEFAULT_OUTPUT),
            (args.support_output, DEFAULT_SUPPORT_OUTPUT),
            (args.field_output, DEFAULT_FIELD_OUTPUT),
            (args.report, DEFAULT_REPORT),
        )
    ):
        print(
            "Luminance plate calibration failed without publishing outputs: "
            "a non-default control requires explicit output, support, field, and report paths"
        )
        return 1
    try:
        report = calibrate(
            control_path=args.control,
            schema_path=args.schema,
            output_path=args.output,
            support_output_path=args.support_output,
            field_output_path=args.field_output,
            report_path=args.report,
        )
    except Exception as error:
        print(
            "Luminance plate calibration failed without publishing outputs: "
            f"{error}"
        )
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
