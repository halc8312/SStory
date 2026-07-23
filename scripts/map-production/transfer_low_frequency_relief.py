#!/usr/bin/env python3
"""Transfer a robust, bounded, non-traceable low-frequency relief field."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import math
import os
import tempfile
from collections import deque
from pathlib import Path
from typing import Any, Iterable, Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageOps


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSITE_MODULE_PATH = REPO_ROOT / "scripts/map-production/composite_masked_edit.py"
DEFAULT_BASE = REPO_ROOT / "world/map-production/candidates/style-candidate-d-v4-erase-route-marks.png"
DEFAULT_CONTROL = REPO_ROOT / "world/map-production/controls/style-candidate-d-v5-relief-mask-v1.json"
DEFAULT_OUTPUT = REPO_ROOT / "world/map-production/candidates/style-candidate-d-v5-broad-relief.png"
DEFAULT_MASK_OUTPUT = (
    REPO_ROOT / "world/map-production/qa/automated/style-candidate-d-v5-relief-transfer-mask.png"
)
DEFAULT_FIELD_OUTPUT = REPO_ROOT / "world/map-production/controls/style-candidate-d-v5-relief-field-v1.png"
DEFAULT_REPORT = REPO_ROOT / "world/map-production/qa/automated/style-candidate-d-v5-relief-transfer.json"


class ReliefTransferError(ValueError):
    """Raised when the transfer contract cannot be evaluated safely."""


class ReliefQualityError(ReliefTransferError):
    """Raised without publishing candidate outputs when a quality gate fails."""


def _load_composite_module() -> Any:
    spec = importlib.util.spec_from_file_location("relief_composite", COMPOSITE_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise ReliefTransferError(f"cannot load composite module: {COMPOSITE_MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _quantile(values: Sequence[int | float], fraction: float) -> float:
    if not values:
        raise ReliefTransferError("cannot calculate a quantile for an empty sample")
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def _rms(values: Iterable[float]) -> float:
    collected = list(values)
    if not collected:
        return 0.0
    return math.sqrt(sum(value * value for value in collected) / len(collected))


def _one_region_control(
    control: dict[str, Any],
    polygon: dict[str, Any],
    *,
    include_exclusions: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "canvas": control["canvas"],
        "include_polygons": [polygon],
        "exclude_strokes": control.get("exclude_strokes", []) if include_exclusions else [],
        "feather_inside_px": control.get("feather_inside_px", 0),
    }


def _one_stroke_control(control: dict[str, Any], stroke: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "canvas": control["canvas"],
        "include_strokes": [stroke],
        "exclude_strokes": control.get("exclude_strokes", []),
        "feather_inside_px": control.get("feather_inside_px", 0),
    }


def _draw_strokes(
    strokes: Sequence[dict[str, Any]],
    size: tuple[int, int],
    *,
    width_override: int | None = None,
) -> Image.Image:
    image = Image.new("1", size, 0)
    draw = ImageDraw.Draw(image)
    for stroke in strokes:
        points = [tuple(point) for point in stroke["points"]]
        width = width_override if width_override is not None else stroke["width"]
        draw.line(points, fill=1, width=width, joint="curve")
        radius = width // 2
        for x, y in (points[0], points[-1]):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=1)
    return image


def _road_core_indices(control: dict[str, Any], size: tuple[int, int]) -> list[int]:
    image = Image.new("1", size, 0)
    draw = ImageDraw.Draw(image)
    for stroke in control.get("exclude_strokes", []):
        draw.line(
            [tuple(point) for point in stroke["points"]],
            fill=1,
            width=stroke["width"],
            joint="curve",
        )
    try:
        return [index for index, value in enumerate(image.get_flattened_data()) if value]
    finally:
        image.close()


def _validate_control(
    control: dict[str, Any],
    control_path: Path,
    base_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if control.get("schema_version") != "1.0.0":
        raise ReliefTransferError("unsupported relief-control schema_version")
    transfer = control.get("low_frequency_transfer")
    if not isinstance(transfer, dict):
        raise ReliefTransferError("control requires low_frequency_transfer")
    source = control.get("source_image")
    if not isinstance(source, dict) or not isinstance(source.get("sha256"), str):
        raise ReliefTransferError("control requires a hash-locked source_image")
    if sha256_file(base_path) != source["sha256"]:
        raise ReliefTransferError("base SHA-256 does not match the control source_image")
    audit = control.get("audit_window_control")
    if not isinstance(audit, dict) or not isinstance(audit.get("path"), str):
        raise ReliefTransferError("control requires audit_window_control")
    audit_path = REPO_ROOT / audit["path"]
    if not audit_path.is_file() or sha256_file(audit_path) != audit.get("sha256"):
        raise ReliefTransferError("audit-window control is missing or its SHA-256 changed")
    if control_path.resolve() == audit_path.resolve():
        raise ReliefTransferError("the rounded audit-window control must not be the final transfer mask")
    audit_control = json.loads(audit_path.read_text(encoding="utf-8"))
    if (
        audit_control.get("schema_version") != "1.0.0"
        or audit_control.get("id") != "style-candidate-d-ridge-edit-mask-v2"
        or audit_control.get("canvas") != control.get("canvas")
        or len(audit_control.get("include_strokes", [])) != 10
    ):
        raise ReliefTransferError("audit-window control schema, id, canvas, or window count changed")
    required = {
        "robust_window_median_px",
        "robust_sample_stride_px",
        "robust_coarse_median_size",
        "robust_coarse_gaussian_radius_cells",
        "final_quantized_median_size",
        "input_difference_clip_levels",
        "road_signal_guard_width_px",
        "inner_gaussian_radius_px",
        "outer_gaussian_radius_px",
        "target_q90_q10_levels",
        "minimum_raw_q90_q10_levels",
        "maximum_normalization_gain",
        "maximum_absolute_delta_levels",
        "region_core_minimum_mask_value",
        "required_final_q90_q10_levels",
        "trace_threshold_levels",
        "trace_minimum_span_px",
        "trace_maximum_covariance_ratio",
        "trace_severe_covariance_ratio",
        "trace_covariance_maximum_bbox_occupancy",
        "trace_maximum_compactness",
        "trace_maximum_bbox_occupancy",
    }
    missing = sorted(required - transfer.keys())
    if missing:
        raise ReliefTransferError(f"low_frequency_transfer is missing: {missing}")
    allowed = required | {
        "signal_mode",
        "relief_method",
        "direct_plate_gaussian_radius_px",
        "required_input_plate_q90_q10_levels",
        "maximum_mean_absolute_delta_levels",
        "maximum_p95_absolute_delta_levels",
        "maximum_high_frequency_rms_levels",
        "maximum_high_frequency_p99_levels",
        "maximum_active_high_frequency_rms_levels",
        "maximum_active_high_frequency_p99_levels",
        "maximum_feather_high_frequency_p99_levels",
        "minimum_region_quadrant_p90_absolute_delta_levels",
    }
    unknown = sorted(transfer.keys() - allowed)
    if unknown:
        raise ReliefTransferError(
            f"low_frequency_transfer contains unknown keys: {unknown}"
        )
    signal_mode = transfer.get("signal_mode", "generated_minus_base")
    if signal_mode not in {"generated_minus_base", "luminance_delta_plate"}:
        raise ReliefTransferError(f"unsupported low-frequency signal_mode: {signal_mode}")
    report_id = control.get("transfer_report_id")
    if report_id is not None and (not isinstance(report_id, str) or not report_id):
        raise ReliefTransferError("transfer_report_id must be a non-empty string")
    if signal_mode == "luminance_delta_plate":
        plate_range = transfer.get("required_input_plate_q90_q10_levels")
        if (
            not isinstance(plate_range, list)
            or len(plate_range) != 2
            or any(not isinstance(value, (int, float)) for value in plate_range)
            or not 0 < plate_range[0] <= plate_range[1] <= 255
        ):
            raise ReliefTransferError(
                "luminance_delta_plate requires a valid "
                "required_input_plate_q90_q10_levels range"
            )
    relief_method = transfer.get("relief_method", "difference_of_gaussians")
    if relief_method not in {"difference_of_gaussians", "direct_plate"}:
        raise ReliefTransferError(f"unsupported relief_method: {relief_method}")
    direct_radius = transfer.get("direct_plate_gaussian_radius_px")
    if relief_method == "direct_plate":
        if signal_mode != "luminance_delta_plate":
            raise ReliefTransferError(
                "direct_plate relief_method requires luminance_delta_plate signal_mode"
            )
        if (
            not isinstance(direct_radius, (int, float))
            or isinstance(direct_radius, bool)
            or not 0 < direct_radius <= 256
        ):
            raise ReliefTransferError(
                "direct_plate relief_method requires a valid "
                "direct_plate_gaussian_radius_px"
            )
    elif direct_radius is not None:
        raise ReliefTransferError(
            "direct_plate_gaussian_radius_px is forbidden for difference_of_gaussians"
        )
    return transfer, audit_control


def _robust_region_band(
    base_values: bytes,
    generated_values: bytes,
    region_values: bytes,
    guard_values: bytes,
    size: tuple[int, int],
    transfer: dict[str, Any],
) -> list[int]:
    width, height = size
    window = int(transfer["robust_window_median_px"])
    stride = int(transfer["robust_sample_stride_px"])
    clip = int(transfer["input_difference_clip_levels"])
    signal_mode = transfer.get("signal_mode", "generated_minus_base")
    if signal_mode not in {"generated_minus_base", "luminance_delta_plate"}:
        raise ReliefTransferError(f"unsupported low-frequency signal_mode: {signal_mode}")
    plate_mode = signal_mode == "luminance_delta_plate"
    relief_method = transfer.get("relief_method", "difference_of_gaussians")
    if window < 32 or stride < 16 or stride > window or clip < 1:
        raise ReliefTransferError(
            "robust window, stride, and input clip must be positive and safe"
        )
    valid_differences = [
        (
            generated_values[index]
            if plate_mode
            else generated_values[index] - base_values[index]
        )
        for index, region_value in enumerate(region_values)
        if region_value > 0 and guard_values[index] == 0
    ]
    if not valid_differences:
        raise ReliefTransferError("region has no valid raw-difference samples")
    regional_median = _quantile(valid_differences, 0.5)
    if relief_method == "direct_plate":
        # Remove a constant plate cast before the two 8-bit Gaussian passes.
        # Otherwise independent numerator/denominator quantization can leave
        # one-level residuals after normalized convolution near guard edges.
        guarded_values = bytes(
            (
                max(0, min(255, round(128 + value - regional_median)))
                if not guard_values[index]
                else 0
            )
            for index, value in enumerate(generated_values)
        )
        valid_values = bytes(0 if value else 255 for value in guard_values)
        plate = Image.frombytes("L", size, guarded_values)
        valid = Image.frombytes("L", size, valid_values)
        smoothed_numerator = plate.filter(
            ImageFilter.GaussianBlur(
                radius=float(transfer["direct_plate_gaussian_radius_px"])
            )
        )
        smoothed_denominator = valid.filter(
            ImageFilter.GaussianBlur(
                radius=float(transfer["direct_plate_gaussian_radius_px"])
            )
        )
        try:
            numerator_values = bytes(smoothed_numerator.get_flattened_data())
            denominator_values = bytes(smoothed_denominator.get_flattened_data())
            if any(value == 0 for value in denominator_values):
                raise ReliefTransferError(
                    "direct_plate road-guard normalized convolution has zero support"
                )
            smoothed_values = bytes(
                max(0, min(255, round(numerator * 255 / denominator)))
                for numerator, denominator in zip(
                    numerator_values,
                    denominator_values,
                )
            )
            direct_samples = [
                smoothed_values[index]
                for index, region_value in enumerate(region_values)
                if region_value > 0 and guard_values[index] == 0
            ]
            direct_median = _quantile(direct_samples, 0.5)
            return [
                round(smoothed_values[index] - direct_median)
                for index in range(width * height)
            ]
        finally:
            plate.close()
            valid.close()
            smoothed_numerator.close()
            smoothed_denominator.close()
    grid_width = math.ceil(width / stride)
    grid_height = math.ceil(height / stride)
    coarse_values: list[int] = []
    for grid_y in range(grid_height):
        center_y = min(height - 1, grid_y * stride + stride // 2)
        start_y = max(0, center_y - window // 2)
        end_y = min(height, start_y + window)
        start_y = max(0, end_y - window)
        for grid_x in range(grid_width):
            center_x = min(width - 1, grid_x * stride + stride // 2)
            start_x = max(0, center_x - window // 2)
            end_x = min(width, start_x + window)
            start_x = max(0, end_x - window)
            samples = []
            for y in range(start_y, end_y):
                row = y * width
                for x in range(start_x, end_x):
                    index = row + x
                    if region_values[index] == 0 or guard_values[index]:
                        continue
                    raw_signal = (
                        generated_values[index]
                        if plate_mode
                        else generated_values[index] - base_values[index]
                    )
                    centered = raw_signal - regional_median
                    samples.append(max(-clip, min(clip, centered)))
            minimum_samples = max(32, ((end_x - start_x) * (end_y - start_y)) // 20)
            median = _quantile(samples, 0.5) if len(samples) >= minimum_samples else 0
            coarse_values.append(max(0, min(255, round(128 + median))))
    coarse = Image.new("L", (grid_width, grid_height))
    coarse.putdata(coarse_values)
    coarse_median_size = int(transfer["robust_coarse_median_size"])
    if coarse_median_size < 1 or coarse_median_size % 2 == 0:
        coarse.close()
        raise ReliefTransferError("robust coarse median size must be a positive odd integer")
    coarse_filtered = coarse.filter(ImageFilter.MedianFilter(size=coarse_median_size))
    coarse_gaussian_radius = float(transfer["robust_coarse_gaussian_radius_cells"])
    if coarse_gaussian_radius < 0:
        coarse.close()
        coarse_filtered.close()
        raise ReliefTransferError("robust coarse Gaussian radius must not be negative")
    coarse_smoothed = (
        coarse_filtered.filter(ImageFilter.GaussianBlur(radius=coarse_gaussian_radius))
        if coarse_gaussian_radius
        else coarse_filtered.copy()
    )
    upsampled = coarse_smoothed.resize(size, Image.Resampling.BICUBIC)
    inner_radius = float(transfer["inner_gaussian_radius_px"])
    outer_radius = float(transfer["outer_gaussian_radius_px"])
    if not 0 < inner_radius < outer_radius:
        coarse.close()
        coarse_filtered.close()
        coarse_smoothed.close()
        upsampled.close()
        raise ReliefTransferError("Gaussian radii must satisfy 0 < inner < outer")
    inner = upsampled.filter(ImageFilter.GaussianBlur(radius=inner_radius))
    outer = upsampled.filter(ImageFilter.GaussianBlur(radius=outer_radius))
    try:
        inner_values = bytes(inner.get_flattened_data())
        outer_values = bytes(outer.get_flattened_data())
        return [
            inner_values[index] - outer_values[index]
            for index in range(width * height)
        ]
    finally:
        coarse.close()
        coarse_filtered.close()
        coarse_smoothed.close()
        upsampled.close()
        inner.close()
        outer.close()


def derive_field(
    base_luminance: Image.Image,
    generated_luminance: Image.Image,
    control: dict[str, Any],
    transfer: dict[str, Any],
) -> tuple[list[int], list[int], list[dict[str, Any]], Image.Image]:
    """Return applied/unmasked integer fields, normalization metrics, and final mask."""

    composite_module = _load_composite_module()
    full_mask = composite_module.build_mask(control)
    size = base_luminance.size
    if full_mask.size != size or generated_luminance.size != size:
        full_mask.close()
        raise ReliefTransferError("base, generated image, and control canvas must match")
    guard_width = int(transfer["road_signal_guard_width_px"])
    guard = _draw_strokes(
        control.get("exclude_strokes", []),
        size,
        width_override=guard_width,
    )
    base_values = bytes(base_luminance.get_flattened_data())
    generated_values = bytes(generated_luminance.get_flattened_data())
    full_mask_values = bytes(full_mask.get_flattened_data())
    guard_values = bytes(guard.get_flattened_data())
    target_spread = float(transfer["target_q90_q10_levels"])
    minimum_spread = float(transfer["minimum_raw_q90_q10_levels"])
    maximum_gain = float(transfer["maximum_normalization_gain"])
    clamp = int(transfer["maximum_absolute_delta_levels"])
    core_minimum = int(transfer["region_core_minimum_mask_value"])
    final_median_size = int(transfer["final_quantized_median_size"])
    if final_median_size < 1 or final_median_size % 2 == 0:
        full_mask.close()
        guard.close()
        raise ReliefTransferError(
            "final quantized median size must be a positive odd integer"
        )
    applied = [0] * (size[0] * size[1])
    unmasked = [0] * (size[0] * size[1])
    assignments = bytearray(size[0] * size[1])
    metrics: list[dict[str, Any]] = []
    metric_core_indices: list[list[int]] = []
    try:
        for polygon in control["include_polygons"]:
            region_shape = composite_module.build_mask(
                _one_region_control(control, polygon, include_exclusions=False)
            )
            try:
                region_values = bytes(region_shape.get_flattened_data())
            finally:
                region_shape.close()
            overlap = 0
            for index, value in enumerate(region_values):
                if value == 0:
                    continue
                if assignments[index]:
                    overlap += 1
                assignments[index] += 1
            if overlap:
                raise ReliefTransferError(
                    f"region {polygon['id']} overlaps a previous region at {overlap} pixels"
                )
            band = _robust_region_band(
                base_values,
                generated_values,
                region_values,
                guard_values,
                size,
                transfer,
            )
            core_indices = [
                index
                for index, value in enumerate(region_values)
                if value >= core_minimum and full_mask_values[index] >= core_minimum
            ]
            plate_metrics: dict[str, Any] = {}
            if transfer.get("signal_mode") == "luminance_delta_plate":
                plate_sample = [
                    generated_values[index]
                    for index in core_indices
                    if guard_values[index] == 0
                ]
                plate_q10 = _quantile(plate_sample, 0.1)
                plate_q90 = _quantile(plate_sample, 0.9)
                plate_spread = plate_q90 - plate_q10
                required_plate_spread = transfer[
                    "required_input_plate_q90_q10_levels"
                ]
                if not required_plate_spread[0] <= plate_spread <= required_plate_spread[1]:
                    raise ReliefTransferError(
                        f"{polygon['id']} input plate Q90-Q10 is outside the required "
                        f"range: {plate_spread:.4f} not in {required_plate_spread}"
                    )
                plate_metrics = {
                    "input_plate_q10_levels": round(plate_q10, 4),
                    "input_plate_q90_levels": round(plate_q90, 4),
                    "input_plate_q90_q10_levels": round(plate_spread, 4),
                    "input_plate_q90_q10_percent": round(plate_spread / 255 * 100, 6),
                }
            sample = [band[index] for index in core_indices]
            median = _quantile(sample, 0.5)
            q10, q90 = _quantile(sample, 0.1), _quantile(sample, 0.9)
            spread = q90 - q10
            if spread < minimum_spread:
                raise ReliefTransferError(
                    f"{polygon['id']} robust low-frequency signal is too weak: {spread:.4f}"
                )
            gain = target_spread / spread
            if gain > maximum_gain:
                raise ReliefTransferError(
                    f"{polygon['id']} requires unsafe normalization gain {gain:.4f}"
                )
            for index, region_alpha in enumerate(region_values):
                if region_alpha == 0:
                    continue
                normalized = round(max(-clamp, min(clamp, (band[index] - median) * gain)))
                unmasked[index] = normalized
            metrics.append(
                {
                    "id": polygon["id"],
                    "opaque_core_pixels": len(core_indices),
                    "raw_median_levels": round(median, 4),
                    "raw_q10_levels": round(q10, 4),
                    "raw_q90_levels": round(q90, 4),
                    "raw_q90_q10_levels": round(spread, 4),
                    "bandpass_median_levels": round(median, 4),
                    "bandpass_q10_levels": round(q10, 4),
                    "bandpass_q90_levels": round(q90, 4),
                    "bandpass_q90_q10_levels": round(spread, 4),
                    "normalization_gain": round(gain, 6),
                    **plate_metrics,
                }
            )
            metric_core_indices.append(core_indices)

        quantized = Image.new("L", size)
        filtered_quantized: Image.Image | None = None
        try:
            quantized.putdata([128 + value for value in unmasked])
            filtered_quantized = quantized.filter(
                ImageFilter.MedianFilter(size=final_median_size)
            )
            filtered_values = bytes(filtered_quantized.get_flattened_data())
        finally:
            quantized.close()
            if filtered_quantized is not None:
                filtered_quantized.close()
        for index, assigned in enumerate(assignments):
            if not assigned:
                continue
            unmasked[index] = filtered_values[index] - 128
            applied[index] = round(unmasked[index] * full_mask_values[index] / 255)
        for metric, core_indices in zip(metrics, metric_core_indices):
            final_sample = [applied[index] for index in core_indices]
            final_q10 = _quantile(final_sample, 0.1)
            final_q90 = _quantile(final_sample, 0.9)
            metric.update(
                {
                    "final_q10_levels": round(final_q10, 4),
                    "final_q90_levels": round(final_q90, 4),
                    "final_q90_q10_levels": round(final_q90 - final_q10, 4),
                }
            )
    except Exception:
        full_mask.close()
        raise
    finally:
        guard.close()
    return applied, unmasked, metrics, full_mask


def _component_metrics(
    points: list[int],
    width: int,
    height: int,
) -> dict[str, Any]:
    xs = [index % width for index in points]
    ys = [index // width for index in points]
    minimum_x, maximum_x = min(xs), max(xs)
    minimum_y, maximum_y = min(ys), max(ys)
    box_width = maximum_x - minimum_x + 1
    box_height = maximum_y - minimum_y + 1
    area = len(points)
    mean_x = sum(xs) / area
    mean_y = sum(ys) / area
    covariance_xx = sum((x - mean_x) ** 2 for x in xs) / max(1, area - 1)
    covariance_yy = sum((y - mean_y) ** 2 for y in ys) / max(1, area - 1)
    covariance_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / max(1, area - 1)
    trace = covariance_xx + covariance_yy
    root = math.sqrt(max(0.0, (covariance_xx - covariance_yy) ** 2 + 4 * covariance_xy**2))
    eigen_minimum = max(0.0, (trace - root) / 2)
    eigen_maximum = max(0.0, (trace + root) / 2)
    covariance_ratio = (eigen_maximum + 0.1) / (eigen_minimum + 0.1)
    point_set = set(points)
    perimeter = 0
    for index in points:
        x, y = index % width, index // width
        for delta_x, delta_y in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            next_x, next_y = x + delta_x, y + delta_y
            if not (0 <= next_x < width and 0 <= next_y < height):
                perimeter += 1
            elif next_y * width + next_x not in point_set:
                perimeter += 1
    compactness = perimeter * perimeter / max(1.0, 4 * math.pi * area)
    return {
        "area_px": area,
        "bbox": [minimum_x, minimum_y, box_width, box_height],
        "maximum_span_px": max(box_width, box_height),
        "bbox_occupancy": round(area / (box_width * box_height), 6),
        "covariance_eigenvalue_ratio": round(covariance_ratio, 6),
        "compactness": round(compactness, 6),
    }


def _traceable_components(
    field: Sequence[int],
    core_mask: bytes,
    size: tuple[int, int],
    transfer: dict[str, Any],
) -> list[dict[str, Any]]:
    width, height = size
    threshold = int(transfer["trace_threshold_levels"])
    minimum_span = int(transfer["trace_minimum_span_px"])
    maximum_ratio = float(transfer["trace_maximum_covariance_ratio"])
    severe_ratio = float(transfer["trace_severe_covariance_ratio"])
    covariance_maximum_occupancy = float(
        transfer["trace_covariance_maximum_bbox_occupancy"]
    )
    maximum_compactness = float(transfer["trace_maximum_compactness"])
    maximum_low_occupancy = float(transfer["trace_maximum_bbox_occupancy"])
    neighbors = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))
    flagged: list[dict[str, Any]] = []
    for sign, label in ((1, "positive"), (-1, "negative")):
        binary = bytearray(
            1 if core_mask[index] > 0 and field[index] * sign >= threshold else 0
            for index in range(width * height)
        )
        for start in range(width * height):
            if binary[start] == 0:
                continue
            binary[start] = 0
            queue: deque[int] = deque([start])
            points: list[int] = []
            while queue:
                current = queue.popleft()
                points.append(current)
                x, y = current % width, current // width
                for delta_x, delta_y in neighbors:
                    next_x, next_y = x + delta_x, y + delta_y
                    if not (0 <= next_x < width and 0 <= next_y < height):
                        continue
                    next_index = next_y * width + next_x
                    if binary[next_index]:
                        binary[next_index] = 0
                        queue.append(next_index)
            metrics = _component_metrics(points, width, height)
            reasons = []
            if metrics["maximum_span_px"] >= minimum_span:
                if metrics["covariance_eigenvalue_ratio"] >= maximum_ratio and (
                    metrics["covariance_eigenvalue_ratio"] >= severe_ratio
                    or metrics["bbox_occupancy"] <= covariance_maximum_occupancy
                ):
                    reasons.append("elongated")
                if (
                    metrics["compactness"] >= maximum_compactness
                    and metrics["bbox_occupancy"] <= maximum_low_occupancy
                ):
                    reasons.append("winding-or-ring-like")
                if metrics["bbox_occupancy"] <= maximum_low_occupancy:
                    reasons.append("low-bbox-occupancy")
            if reasons:
                metrics["sign"] = label
                metrics["reasons"] = reasons
                flagged.append(metrics)
    return flagged


def _high_frequency_metrics(
    high_frequency: Sequence[int],
    indices: Sequence[int],
) -> dict[str, float]:
    values = [high_frequency[index] for index in indices]
    absolute = [abs(value) for value in values]
    return {
        "rms_levels": round(_rms(values), 6),
        "p99_levels": round(_quantile(absolute, 0.99), 6) if absolute else 0.0,
        "maximum_levels": float(max(absolute, default=0)),
    }


def _region_quadrant_metrics(
    control: dict[str, Any],
    applied: Sequence[int],
    full_mask_values: bytes,
) -> list[dict[str, Any]]:
    composite_module = _load_composite_module()
    width = control["canvas"]["width"]
    metrics = []
    for polygon in control["include_polygons"]:
        region = composite_module.build_mask(
            _one_region_control(control, polygon, include_exclusions=False)
        )
        try:
            region_values = bytes(region.get_flattened_data())
        finally:
            region.close()
        xs = [point[0] for point in polygon["points"]]
        ys = [point[1] for point in polygon["points"]]
        minimum_x, maximum_x = min(xs), max(xs)
        minimum_y, maximum_y = min(ys), max(ys)
        middle_x = (minimum_x + maximum_x) // 2
        middle_y = (minimum_y + maximum_y) // 2
        boxes = (
            (minimum_x, minimum_y, middle_x, middle_y),
            (middle_x, minimum_y, maximum_x + 1, middle_y),
            (minimum_x, middle_y, middle_x, maximum_y + 1),
            (middle_x, middle_y, maximum_x + 1, maximum_y + 1),
        )
        for index, (left, top, right, bottom) in enumerate(boxes, start=1):
            sample = []
            for y in range(max(0, top), min(control["canvas"]["height"], bottom)):
                row = y * width
                for x in range(max(0, left), min(width, right)):
                    pixel = row + x
                    if region_values[pixel] == 255 and full_mask_values[pixel] == 255:
                        sample.append(abs(applied[pixel]))
            metrics.append(
                {
                    "region_id": polygon["id"],
                    "quadrant": index,
                    "sample_pixels": len(sample),
                    "p90_absolute_delta_levels": round(_quantile(sample, 0.9), 4),
                }
            )
    return metrics


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _atomic_commit(artifacts: Sequence[tuple[Path, bytes]]) -> None:
    resolved = [path.resolve() for path, _ in artifacts]
    if len(resolved) != len(set(resolved)):
        raise ReliefTransferError("output, mask, field, and report paths must be distinct")
    existing = [path for path, _ in artifacts if path.exists()]
    if existing:
        raise ReliefTransferError(f"refusing to overwrite existing output: {existing[0]}")
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


def transfer(
    *,
    base_path: Path,
    generated_path: Path,
    control_path: Path,
    output_path: Path,
    mask_output_path: Path,
    field_output_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    output_paths = (output_path, mask_output_path, field_output_path, report_path)
    if len({path.resolve() for path in output_paths}) != len(output_paths):
        raise ReliefTransferError("output paths must be distinct")
    existing = [path for path in output_paths if path.exists()]
    if existing:
        raise ReliefTransferError(f"refusing to overwrite existing output: {existing[0]}")
    control = json.loads(control_path.read_text(encoding="utf-8"))
    transfer_contract, audit_control = _validate_control(control, control_path, base_path)
    expected_size = (control["canvas"]["width"], control["canvas"]["height"])
    with Image.open(base_path) as opened_base:
        base = ImageOps.exif_transpose(opened_base).convert("RGB")
    with Image.open(generated_path) as opened_generated:
        generated = ImageOps.exif_transpose(opened_generated).convert("RGB")
    if base.size != expected_size or generated.size != expected_size:
        base.close()
        generated.close()
        raise ReliefTransferError(f"base and generated image must both equal {expected_size}")
    base_luminance = base.convert("L")
    generated_luminance = generated.convert("L")
    output: Image.Image | None = None
    field: Image.Image | None = None
    mask: Image.Image | None = None
    try:
        applied, unmasked, region_metrics, mask = derive_field(
            base_luminance,
            generated_luminance,
            control,
            transfer_contract,
        )
        mask_values = bytes(mask.get_flattened_data())
        base_values = base.tobytes()
        output_values = bytearray(len(base_values))
        clipping_pixels = 0
        maximum_channel_delta_spread = 0
        for pixel_index, delta in enumerate(applied):
            offset = pixel_index * 3
            channel_deltas = []
            for channel in range(3):
                original = base_values[offset + channel]
                changed = max(0, min(255, original + delta))
                output_values[offset + channel] = changed
                channel_deltas.append(changed - original)
            if any(value != delta for value in channel_deltas):
                clipping_pixels += 1
            maximum_channel_delta_spread = max(
                maximum_channel_delta_spread,
                max(channel_deltas) - min(channel_deltas),
            )
        output = Image.frombytes("RGB", expected_size, bytes(output_values))
        field = Image.new("L", expected_size)
        field.putdata([128 + value for value in applied])
        full_mask_values = mask_values
        active_indices = [index for index, value in enumerate(mask_values) if value > 0]
        opaque_indices = [index for index, value in enumerate(mask_values) if value == 255]
        feather_indices = [index for index, value in enumerate(mask_values) if 0 < value < 255]
        absolute_deltas = [abs(applied[index]) for index in opaque_indices]
        active_absolute_deltas = [abs(applied[index]) for index in active_indices]
        mean_absolute_delta = sum(absolute_deltas) / max(1, len(absolute_deltas))
        p95_absolute_delta = _quantile(absolute_deltas, 0.95)
        maximum_absolute_delta = max(active_absolute_deltas, default=0)
        blurred_field = field.filter(ImageFilter.GaussianBlur(radius=8))
        try:
            blurred_values = bytes(blurred_field.get_flattened_data())
        finally:
            blurred_field.close()
        high_frequency = [
            applied[index] - (blurred_values[index] - 128)
            for index in range(expected_size[0] * expected_size[1])
        ]
        opaque_hf = _high_frequency_metrics(high_frequency, opaque_indices)
        active_hf = _high_frequency_metrics(high_frequency, active_indices)
        feather_hf = _high_frequency_metrics(high_frequency, feather_indices)

        composite_module = _load_composite_module()
        topology_core = Image.new("L", expected_size, 0)
        try:
            topology_values = bytearray(expected_size[0] * expected_size[1])
            for polygon in control["include_polygons"]:
                region = composite_module.build_mask(
                    _one_region_control(control, polygon, include_exclusions=False)
                )
                try:
                    values = bytes(region.get_flattened_data())
                finally:
                    region.close()
                for index, value in enumerate(values):
                    topology_values[index] = max(topology_values[index], value)
            topology_core.putdata(topology_values)
            topology_core_values = bytes(topology_core.get_flattened_data())
        finally:
            topology_core.close()
        topology_trace_field = (
            applied
            if transfer_contract.get("relief_method") == "direct_plate"
            else unmasked
        )
        traceable = _traceable_components(
            topology_trace_field,
            topology_core_values,
            expected_size,
            transfer_contract,
        )

        window_metrics = []
        for stroke in audit_control["include_strokes"]:
            window = composite_module.build_mask(_one_stroke_control(audit_control, stroke))
            try:
                window_values = bytes(window.get_flattened_data())
            finally:
                window.close()
            sample = [
                abs(applied[index])
                for index, value in enumerate(window_values)
                if value == 255 and mask_values[index] == 255
            ]
            window_metrics.append(
                {
                    "id": stroke["id"],
                    "role": "diagnostic-only",
                    "sample_pixels": len(sample),
                    "p90_absolute_delta_levels": round(_quantile(sample, 0.9), 4),
                }
            )
        quadrant_metrics = _region_quadrant_metrics(
            control,
            applied,
            full_mask_values,
        )
        road_indices = _road_core_indices(control, expected_size)
        road_changed_pixels = sum(
            base_values[index * 3 : index * 3 + 3]
            != output_values[index * 3 : index * 3 + 3]
            for index in road_indices
        )
        outside_mask_changed_pixels = sum(
            value == 0
            and base_values[index * 3 : index * 3 + 3]
            != output_values[index * 3 : index * 3 + 3]
            for index, value in enumerate(mask_values)
        )
        protected_pixels = sum(value == 0 for value in mask_values)
        masked_pixels = len(active_indices)
        opaque_pixels = len(opaque_indices)

        failures: list[str] = []
        final_range = transfer_contract["required_final_q90_q10_levels"]
        for region in region_metrics:
            if not final_range[0] <= region["final_q90_q10_levels"] <= final_range[1]:
                failures.append(
                    f"{region['id']} final Q90-Q10 is {region['final_q90_q10_levels']}"
                )
        if mean_absolute_delta > transfer_contract["maximum_mean_absolute_delta_levels"]:
            failures.append(f"mean absolute delta is {mean_absolute_delta:.4f}")
        if p95_absolute_delta > transfer_contract["maximum_p95_absolute_delta_levels"]:
            failures.append(f"P95 absolute delta is {p95_absolute_delta:.4f}")
        if maximum_absolute_delta > transfer_contract["maximum_absolute_delta_levels"]:
            failures.append(f"maximum absolute delta is {maximum_absolute_delta}")
        if opaque_hf["rms_levels"] > transfer_contract["maximum_high_frequency_rms_levels"]:
            failures.append(f"opaque high-frequency RMS is {opaque_hf['rms_levels']}")
        if opaque_hf["p99_levels"] > transfer_contract["maximum_high_frequency_p99_levels"]:
            failures.append(f"opaque high-frequency P99 is {opaque_hf['p99_levels']}")
        if active_hf["rms_levels"] > transfer_contract["maximum_active_high_frequency_rms_levels"]:
            failures.append(f"active high-frequency RMS is {active_hf['rms_levels']}")
        if active_hf["p99_levels"] > transfer_contract["maximum_active_high_frequency_p99_levels"]:
            failures.append(f"active high-frequency P99 is {active_hf['p99_levels']}")
        if feather_hf["p99_levels"] > transfer_contract["maximum_feather_high_frequency_p99_levels"]:
            failures.append(f"feather high-frequency P99 is {feather_hf['p99_levels']}")
        if traceable:
            failures.append(f"found {len(traceable)} traceable low-frequency components")
        minimum_quadrant = transfer_contract["minimum_region_quadrant_p90_absolute_delta_levels"]
        for quadrant in quadrant_metrics:
            if quadrant["p90_absolute_delta_levels"] < minimum_quadrant:
                failures.append(
                    f"{quadrant['region_id']} quadrant {quadrant['quadrant']} P90 is "
                    f"{quadrant['p90_absolute_delta_levels']}"
                )
        if clipping_pixels:
            failures.append(f"equal-channel transfer clipped at {clipping_pixels} pixels")
        if maximum_channel_delta_spread > 1:
            failures.append(
                f"maximum RGB delta spread is {maximum_channel_delta_spread} levels"
            )
        if road_changed_pixels:
            failures.append(f"changed {road_changed_pixels} protected road pixels")
        if outside_mask_changed_pixels:
            failures.append(f"changed {outside_mask_changed_pixels} outside-mask pixels")
        if failures:
            raise ReliefQualityError("; ".join(failures))

        output_png = _png_bytes(output)
        mask_png = _png_bytes(mask)
        field_png = _png_bytes(field)
        report = {
            "schema_version": "1.0.0",
            "id": control.get(
                "transfer_report_id", "style-candidate-d-v5-relief-transfer"
            ),
            "status": "passed",
            "signal_mode": transfer_contract.get(
                "signal_mode", "generated_minus_base"
            ),
            "base_path": _relative(base_path),
            "generated_path": _relative(generated_path),
            "control_path": _relative(control_path),
            "output_path": _relative(output_path),
            "mask_output_path": _relative(mask_output_path),
            "field_output_path": _relative(field_output_path),
            "parameters": transfer_contract,
            "region_metrics": region_metrics,
            "region_quadrant_metrics": quadrant_metrics,
            "audit_window_metrics": window_metrics,
            "traceable_low_frequency_components": traceable,
            "topology_mask_scope": "all nonzero polygon-mask pixels including feather",
            "topology_trace_field": (
                "applied-final-delta"
                if transfer_contract.get("relief_method") == "direct_plate"
                else "unmasked-normalized-delta"
            ),
            "masked_pixels": masked_pixels,
            "opaque_mask_pixels": opaque_pixels,
            "feather_mask_pixels": len(feather_indices),
            "protected_pixels_verified": protected_pixels,
            "road_pixels_verified": len(road_indices),
            "road_changed_pixels": road_changed_pixels,
            "outside_mask_changed_pixels": outside_mask_changed_pixels,
            "mean_absolute_delta_levels": round(mean_absolute_delta, 6),
            "p95_absolute_delta_levels": round(p95_absolute_delta, 6),
            "maximum_absolute_delta_levels": maximum_absolute_delta,
            "opaque_high_frequency": opaque_hf,
            "active_high_frequency": active_hf,
            "feather_high_frequency": feather_hf,
            "equal_channel_clipping_pixels": clipping_pixels,
            "maximum_rgb_delta_spread_levels": maximum_channel_delta_spread,
            "base_sha256": sha256_file(base_path),
            "generated_sha256": sha256_file(generated_path),
            "control_sha256": sha256_file(control_path),
            "mask_sha256": _sha256_bytes(mask_png),
            "field_sha256": _sha256_bytes(field_png),
            "output_sha256": _sha256_bytes(output_png),
        }
        report_bytes = (
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        _atomic_commit(
            (
                (output_path, output_png),
                (mask_output_path, mask_png),
                (field_output_path, field_png),
                (report_path, report_bytes),
            )
        )
        return report
    finally:
        base_luminance.close()
        generated_luminance.close()
        base.close()
        generated.close()
        if output is not None:
            output.close()
        if field is not None:
            field.close()
        if mask is not None:
            mask.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--control", type=Path, default=DEFAULT_CONTROL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--mask-output", type=Path, default=DEFAULT_MASK_OUTPUT)
    parser.add_argument("--field-output", type=Path, default=DEFAULT_FIELD_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.control.resolve() != DEFAULT_CONTROL.resolve() and any(
        path.resolve() == default.resolve()
        for path, default in (
            (args.output, DEFAULT_OUTPUT),
            (args.mask_output, DEFAULT_MASK_OUTPUT),
            (args.field_output, DEFAULT_FIELD_OUTPUT),
            (args.report, DEFAULT_REPORT),
        )
    ):
        print(
            "Low-frequency relief transfer failed without publishing outputs: "
            "a non-default control requires explicit candidate, mask, field, and "
            "report output paths"
        )
        return 1
    try:
        report = transfer(
            base_path=args.base.resolve(),
            generated_path=args.generated.resolve(),
            control_path=args.control.resolve(),
            output_path=args.output.resolve(),
            mask_output_path=args.mask_output.resolve(),
            field_output_path=args.field_output.resolve(),
            report_path=args.report.resolve(),
        )
    except (OSError, json.JSONDecodeError, ReliefTransferError, KeyError, TypeError) as exc:
        print(f"Low-frequency relief transfer failed without publishing outputs: {exc}")
        return 1
    print(
        "Low-frequency relief transfer passed: "
        f"masked_pixels={report['masked_pixels']} "
        f"max_delta={report['maximum_absolute_delta_levels']} "
        f"outside_changed={report['outside_mask_changed_pixels']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
