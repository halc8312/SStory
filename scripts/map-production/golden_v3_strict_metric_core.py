#!/usr/bin/env python3
"""Candidate-independent integer metrics for the K3 Golden-v3 strict audit.

This module intentionally contains no candidate path, accepted output hash, or
threshold-selection logic.  Its fixed-point operations consume a preregistered
authority document and derive every signal from final RGB pixels plus frozen
foundation/body masks.  A/unit/total, energy, and repetition gate decisions
use integer cross-products; their rounded decimal values are report-only.
The separately inherited v2 primary values retain their frozen six-decimal
definitions and are compared to the new v3 primary intervals as such.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Any, Iterable, Mapping, Sequence

import cv2
import numpy as np


Q_SIGNAL_BITS = 12
Q_SIGNAL = 1 << Q_SIGNAL_BITS
Q_MASK_BITS = 20
Q_MASK = 1 << Q_MASK_BITS
Q_NUMERATOR_EXTRA_BITS = 2
Q_NUMERATOR_EXTRA = 1 << Q_NUMERATOR_EXTRA_BITS
Q_KERNEL_BITS = 30
Q_KERNEL = 1 << Q_KERNEL_BITS
BODY_VALUES = (32, 64, 96, 128, 160, 192, 224, 255)
INT64_MAX = int(np.iinfo(np.int64).max)
INT64_MIN = int(np.iinfo(np.int64).min)

EXPECTED_LUMA_CONTRACT = {
    "formula": "(19595*R + 38470*G + 7471*B + 32768) >> 16",
    "coefficients_sum": 65_536,
    "delta": "candidate_luma - foundation_v19_luma",
}
EXPECTED_SIGNAL_CONTRACT = {
    "fixed_point_q_bits": Q_SIGNAL_BITS,
    "normalized_mask_weight_q_bits": Q_MASK_BITS,
    "normalized_numerator_extra_q_bits": Q_NUMERATOR_EXTRA_BITS,
    "body_core_erosion_px": 12,
    "body_core_structuring_element": "integer offsets dx^2+dy^2<=144",
    "minimum_body_core_pixels": 512,
    "total": "T_i is the body-centered signed final luma delta in Q12",
    "A": (
        "E_i is sqrt(mask-normalized Gaussian-sigma8(T_i^2)); T_i^2 is rounded "
        "to Q12 before filtering; A_i is E_i body-centered"
    ),
    "unit": (
        "U_i is T_i/max(E_i,1.0 L), body-centered, then normalized to unit RMS "
        "in Q12"
    ),
    "rounding": "nearest-ties-away-from-zero",
    "integer_square_root_rounding": (
        "floor (math.isqrt) for amplitude and unit-RMS normalization"
    ),
    "aggregation": (
        "derive and filter each body independently; sum exact energy numerators "
        "and denominators only over 12px-eroded body cores"
    ),
}


class StrictMetricError(RuntimeError):
    """Raised when a strict metric cannot be measured authoritatively."""


def _absolute_int64(values: np.ndarray) -> np.ndarray:
    source = np.asarray(values, dtype=np.int64)
    if np.any(source == INT64_MIN):
        raise StrictMetricError("signed int64 minimum cannot be represented as an absolute value")
    return np.abs(source)


@dataclass(frozen=True)
class IntegerGaussianKernel:
    sigma_px: int
    radius_px: int
    coefficients_q30: tuple[int, ...]

    @classmethod
    def from_authority(cls, sigma: int, record: Mapping[str, Any]) -> "IntegerGaussianKernel":
        if set(record) != {"radius_px", "coefficients_q30"}:
            raise StrictMetricError(f"sigma-{sigma} kernel field set drifted")
        radius = record["radius_px"]
        coefficients = record["coefficients_q30"]
        if isinstance(radius, bool) or not isinstance(radius, int) or radius != 4 * sigma:
            raise StrictMetricError(f"sigma-{sigma} kernel radius must equal truncate-4")
        if (
            not isinstance(coefficients, list)
            or len(coefficients) != 2 * radius + 1
            or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in coefficients)
        ):
            raise StrictMetricError(f"sigma-{sigma} Q30 coefficients are invalid")
        values = tuple(int(value) for value in coefficients)
        if values != values[::-1] or sum(values) != Q_KERNEL:
            raise StrictMetricError(f"sigma-{sigma} Q30 kernel is not symmetric/unit-sum")
        return cls(sigma_px=sigma, radius_px=radius, coefficients_q30=values)


def load_kernels(authority: Mapping[str, Any]) -> dict[int, IntegerGaussianKernel]:
    source = authority.get("integer_gaussian")
    if not isinstance(source, dict) or set(source) != {
        "q_bits",
        "truncate",
        "border",
        "rounding",
        "kernels",
    }:
        raise StrictMetricError("integer_gaussian authority field set drifted")
    if (
        source["q_bits"] != Q_KERNEL_BITS
        or source["truncate"] != 4
        or source["border"] != "half-sample-symmetric-reflect"
        or source["rounding"] != "nearest-ties-away-from-zero-after-each-pass"
    ):
        raise StrictMetricError("integer Gaussian arithmetic authority drifted")
    records = source["kernels"]
    if not isinstance(records, dict) or set(records) != {"2", "4", "8"}:
        raise StrictMetricError("integer Gaussian sigma set must be exactly 2,4,8")
    return {
        sigma: IntegerGaussianKernel.from_authority(sigma, records[str(sigma)])
        for sigma in (2, 4, 8)
    }


def validate_authority_contract(authority: Mapping[str, Any]) -> None:
    """Bind the executable numeric constants to their frozen JSON contract."""

    if authority.get("luma") != EXPECTED_LUMA_CONTRACT:
        raise StrictMetricError("luma arithmetic authority drifted")
    if authority.get("signal_definition") != EXPECTED_SIGNAL_CONTRACT:
        raise StrictMetricError("signal arithmetic authority drifted")
    strict_contract = authority.get("strict_field_contract")
    if not isinstance(strict_contract, Mapping):
        raise StrictMetricError("strict field authority is missing")
    if (
        strict_contract.get("body_core_erosion_px")
        != EXPECTED_SIGNAL_CONTRACT["body_core_erosion_px"]
        or strict_contract.get("minimum_body_core_pixels")
        != EXPECTED_SIGNAL_CONTRACT["minimum_body_core_pixels"]
    ):
        raise StrictMetricError("body core authority disagrees with signal definition")
    load_kernels(authority)


def _round_divide_array(numerator: np.ndarray, denominator: int | np.ndarray) -> np.ndarray:
    values = np.asarray(numerator, dtype=np.int64)
    divisors = np.asarray(denominator, dtype=np.int64)
    if np.any(divisors <= 0):
        raise StrictMetricError("integer division requires a positive denominator")
    absolute = _absolute_int64(values)
    half = divisors // 2
    try:
        overflow = np.any(absolute > np.int64(INT64_MAX) - half)
    except ValueError as exc:
        raise StrictMetricError("integer division operands are not broadcast-compatible") from exc
    if overflow:
        raise StrictMetricError("integer division rounding would overflow int64")
    quotient = (absolute + half) // divisors
    return np.where(values < 0, -quotient, quotient).astype(np.int64)


def round_divide_scalar(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise StrictMetricError("integer division requires a positive denominator")
    sign = -1 if numerator < 0 else 1
    absolute = abs(int(numerator))
    return sign * ((absolute + denominator // 2) // denominator)


def _convolve_axis_q30(
    values: np.ndarray,
    kernel: IntegerGaussianKernel,
    *,
    axis: int,
) -> np.ndarray:
    source = np.asarray(values, dtype=np.int64)
    if source.ndim != 2:
        raise StrictMetricError("integer Gaussian input must be a 2-D array")
    maximum = int(np.max(_absolute_int64(source))) if source.size else 0
    if maximum > INT64_MAX // Q_KERNEL:
        raise StrictMetricError("integer Gaussian accumulator would overflow int64")
    radius = kernel.radius_px
    padding = ((radius, radius), (0, 0)) if axis == 0 else ((0, 0), (radius, radius))
    padded = np.pad(source, padding, mode="symmetric")
    accumulator = np.zeros(source.shape, dtype=np.int64)
    for offset, coefficient in enumerate(kernel.coefficients_q30):
        if axis == 0:
            sample = padded[offset : offset + source.shape[0], :]
        else:
            sample = padded[:, offset : offset + source.shape[1]]
        accumulator += sample * np.int64(coefficient)
    return _round_divide_array(accumulator, Q_KERNEL)


def gaussian_q30(values: np.ndarray, kernel: IntegerGaussianKernel) -> np.ndarray:
    """Apply the exact stored separable kernel with symmetric reflection."""

    horizontal = _convolve_axis_q30(values, kernel, axis=1)
    return _convolve_axis_q30(horizontal, kernel, axis=0)


def masked_gaussian_q30(
    values: np.ndarray,
    mask: np.ndarray,
    kernel: IntegerGaussianKernel,
) -> np.ndarray:
    """Return G(X*M)/G(M) in the input fixed-point scale."""

    field = np.asarray(values, dtype=np.int64)
    selected = np.asarray(mask, dtype=bool)
    if field.shape != selected.shape or field.ndim != 2:
        raise StrictMetricError("masked Gaussian field/mask shape mismatch")
    if not np.any(selected):
        raise StrictMetricError("masked Gaussian support is empty")
    yy, xx = np.nonzero(selected)
    radius = kernel.radius_px
    y0 = max(0, int(yy.min()) - radius)
    y1 = min(field.shape[0], int(yy.max()) + radius + 1)
    x0 = max(0, int(xx.min()) - radius)
    x1 = min(field.shape[1], int(xx.max()) + radius + 1)
    local_mask = selected[y0:y1, x0:x1]
    local_field = field[y0:y1, x0:x1]
    maximum_local = int(np.max(_absolute_int64(local_field[local_mask])))
    if maximum_local > INT64_MAX // Q_NUMERATOR_EXTRA:
        raise StrictMetricError("masked Gaussian numerator scaling would overflow int64")
    numerator = gaussian_q30(
        np.where(local_mask, local_field * np.int64(Q_NUMERATOR_EXTRA), 0),
        kernel,
    )
    denominator = gaussian_q30(local_mask.astype(np.int64) * Q_MASK, kernel)
    if np.any(denominator[local_mask] <= 0):
        raise StrictMetricError("masked Gaussian support denominator collapsed")
    maximum_numerator = int(np.max(_absolute_int64(numerator[local_mask])))
    if maximum_numerator > INT64_MAX // Q_MASK:
        raise StrictMetricError("masked Gaussian normalization would overflow int64")
    normalized = np.zeros(field.shape, dtype=np.int64)
    local_normalized = np.zeros(local_field.shape, dtype=np.int64)
    local_normalized[local_mask] = _round_divide_array(
        numerator[local_mask] * np.int64(Q_MASK),
        denominator[local_mask] * np.int64(Q_NUMERATOR_EXTRA),
    )
    target = normalized[y0:y1, x0:x1]
    target[local_mask] = local_normalized[local_mask]
    return normalized


def luma_u8(rgb: np.ndarray) -> np.ndarray:
    """Return deterministic integer BT.601-like luma; coefficients sum to 65536."""

    image = np.asarray(rgb)
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise StrictMetricError("RGB input must be uint8 HxWx3")
    values = image.astype(np.int64)
    luma = (
        19_595 * values[..., 0]
        + 38_470 * values[..., 1]
        + 7_471 * values[..., 2]
        + 32_768
    ) >> 16
    return luma.astype(np.int16)


def disk_erode(mask: np.ndarray, radius_px: int) -> np.ndarray:
    selected = np.asarray(mask, dtype=bool)
    if selected.ndim != 2 or radius_px < 0:
        raise StrictMetricError("binary erosion mask/radius is invalid")
    if radius_px == 0:
        return selected.copy()
    coordinates = np.arange(-radius_px, radius_px + 1, dtype=np.int32)
    yy, xx = np.meshgrid(coordinates, coordinates, indexing="ij")
    kernel = ((xx * xx + yy * yy) <= radius_px * radius_px).astype(np.uint8)
    return cv2.erode(
        selected.astype(np.uint8),
        kernel,
        iterations=1,
        borderType=cv2.BORDER_CONSTANT,
        borderValue=0,
    ) > 0


def decode_body_masks(
    indexed: np.ndarray,
    *,
    body_values: Sequence[int] = BODY_VALUES,
) -> tuple[list[np.ndarray], np.ndarray]:
    labels = np.asarray(indexed)
    if labels.ndim != 2 or labels.dtype != np.uint8:
        raise StrictMetricError("body control must be uint8 HxW")
    expected_values = {0, *(int(value) for value in body_values)}
    if set(int(value) for value in np.unique(labels)) != expected_values:
        raise StrictMetricError("body control value set drifted")
    masks = [labels == np.uint8(value) for value in body_values]
    union = np.logical_or.reduce(masks)
    total, _ = cv2.connectedComponents(
        union.astype(np.uint8), connectivity=8, ltype=cv2.CV_32S
    )
    if total - 1 != len(body_values):
        raise StrictMetricError("body control must contain exactly eight non-touching components")
    for index, mask in enumerate(masks):
        count, _ = cv2.connectedComponents(
            mask.astype(np.uint8), connectivity=8, ltype=cv2.CV_32S
        )
        if count != 2:
            raise StrictMetricError(f"body-{index:02d} is empty or fragmented")
    return masks, union


def _integer_sqrt_array(values: np.ndarray) -> np.ndarray:
    """Apply the authority's floor integer-square-root element by element."""

    source = np.asarray(values, dtype=np.int64)
    if np.any(source < 0):
        raise StrictMetricError("integer square-root input became negative")
    flattened = np.fromiter(
        (math.isqrt(int(value)) for value in source.ravel()),
        dtype=np.int64,
        count=source.size,
    )
    return flattened.reshape(source.shape)


def _center_q(values: np.ndarray, mask: np.ndarray) -> np.ndarray:
    selected = np.asarray(mask, dtype=bool)
    count = int(np.count_nonzero(selected))
    if count == 0:
        raise StrictMetricError("cannot center an empty signal")
    mean = round_divide_scalar(int(np.sum(values[selected], dtype=np.int64)), count)
    result = np.zeros(values.shape, dtype=np.int64)
    result[selected] = values[selected].astype(np.int64) - mean
    return result


def derive_body_fields(
    delta_luma: np.ndarray,
    body: np.ndarray,
    kernels: Mapping[int, IntegerGaussianKernel],
) -> dict[str, np.ndarray]:
    """Derive total, amplitude A, and unit fields from final-pixel luma delta."""

    delta = np.asarray(delta_luma)
    selected = np.asarray(body, dtype=bool)
    if delta.shape != selected.shape or delta.ndim != 2:
        raise StrictMetricError("body field delta/mask shape mismatch")
    if not np.any(selected):
        raise StrictMetricError("body field mask is empty")
    total = np.zeros(delta.shape, dtype=np.int64)
    total[selected] = delta[selected].astype(np.int64) * Q_SIGNAL
    total = _center_q(total, selected)

    # Keep the squared field in Q12 before convolution.  This is both the
    # frozen definition and an overflow guard: a uint8 luma delta can never
    # make a Q12 sample exceed signed-int64 convolution bounds.
    maximum_total = int(np.max(_absolute_int64(total[selected])))
    if maximum_total > math.isqrt(INT64_MAX):
        raise StrictMetricError("body total square would overflow int64")
    squared_q12 = _round_divide_array(total * total, Q_SIGNAL)
    amplitude_squared_q12 = masked_gaussian_q30(
        squared_q12, selected, kernels[8]
    )
    amplitude = np.zeros(delta.shape, dtype=np.int64)
    amplitude[selected] = _integer_sqrt_array(
        np.maximum(amplitude_squared_q12[selected], 0) * np.int64(Q_SIGNAL)
    )
    amplitude_centered = _center_q(amplitude, selected)

    denominator = np.maximum(amplitude, Q_SIGNAL)
    unit_raw = np.zeros(delta.shape, dtype=np.int64)
    unit_raw[selected] = _round_divide_array(
        total[selected] * np.int64(Q_SIGNAL), denominator[selected]
    )
    unit_centered = _center_q(unit_raw, selected)
    count = int(np.count_nonzero(selected))
    rms_squared = round_divide_scalar(sum_squares(unit_centered, selected), count)
    rms = math.isqrt(max(rms_squared, 0))
    if rms <= 0:
        raise StrictMetricError("body unit-RMS normalization collapsed")
    unit = np.zeros(delta.shape, dtype=np.int64)
    unit[selected] = _round_divide_array(
        unit_centered[selected] * np.int64(Q_SIGNAL), rms
    )
    return {"A": amplitude_centered, "unit": unit, "total": total}


def highpass_q(
    values: np.ndarray,
    body: np.ndarray,
    kernel: IntegerGaussianKernel,
) -> np.ndarray:
    selected = np.asarray(body, dtype=bool)
    low = masked_gaussian_q30(values, selected, kernel)
    result = np.zeros(values.shape, dtype=np.int64)
    result[selected] = values[selected].astype(np.int64) - low[selected]
    return result


def sum_squares(values: np.ndarray, mask: np.ndarray) -> int:
    selected = np.asarray(mask, dtype=bool)
    samples = np.asarray(values, dtype=np.int64)[selected]
    if samples.size == 0:
        raise StrictMetricError("energy support is empty")
    maximum = int(np.max(_absolute_int64(samples)))
    if maximum and maximum > math.isqrt(INT64_MAX // int(samples.size)):
        raise StrictMetricError("energy accumulation would overflow int64")
    return int(np.sum(samples * samples, dtype=np.int64))


def _ensure_pair_products_safe(left: np.ndarray, right: np.ndarray) -> None:
    if left.size != right.size or left.size == 0:
        raise StrictMetricError("pair-product support is invalid")
    maximum_left = int(np.max(_absolute_int64(left)))
    maximum_right = int(np.max(_absolute_int64(right)))
    count = int(left.size)
    if (
        maximum_left > math.isqrt(INT64_MAX // count)
        or maximum_right > math.isqrt(INT64_MAX // count)
        or (
            maximum_left
            and maximum_right > INT64_MAX // count // maximum_left
        )
    ):
        raise StrictMetricError("correlation accumulation would overflow int64")


def ratio_le(numerator: int, denominator: int, limit_numerator: int, limit_denominator: int) -> bool:
    if numerator < 0 or denominator <= 0 or limit_numerator < 0 or limit_denominator <= 0:
        raise StrictMetricError("invalid exact ratio comparison")
    return int(numerator) * int(limit_denominator) <= int(denominator) * int(limit_numerator)


def energy_percent_ge(
    numerator_energy: int,
    denominator_energy: int,
    threshold_percent: int,
) -> bool:
    if numerator_energy < 0 or denominator_energy <= 0 or threshold_percent < 0:
        raise StrictMetricError("invalid exact energy comparison")
    return 10_000 * int(numerator_energy) >= threshold_percent**2 * int(denominator_energy)


def correlation_le(
    covariance_numerator: int,
    variance_product: int,
    limit_numerator: int,
    limit_denominator: int,
) -> bool:
    if variance_product <= 0 or limit_numerator < 0 or limit_denominator <= 0:
        raise StrictMetricError("invalid exact correlation comparison")
    left = limit_denominator**2 * abs(int(covariance_numerator)) ** 2
    right = limit_numerator**2 * int(variance_product)
    return left <= right


def _decimal_ratio(numerator: int, denominator: int, *, square_root: bool = False) -> float:
    if denominator <= 0:
        raise StrictMetricError("cannot report a ratio with zero denominator")
    with localcontext() as context:
        context.prec = 50
        value = Decimal(int(numerator)) / Decimal(int(denominator))
        if square_root:
            value = value.sqrt()
        return float(format(value, ".6f"))


def _shift_slices(shape: tuple[int, int], dx: int, dy: int) -> tuple[tuple[slice, slice], tuple[slice, slice]]:
    height, width = shape
    if abs(dx) >= width or abs(dy) >= height or (dx == 0 and dy == 0):
        raise StrictMetricError("repetition lag escaped the raster")
    left_y = slice(max(0, dy), min(height, height + dy))
    left_x = slice(max(0, dx), min(width, width + dx))
    right_y = slice(max(0, -dy), min(height, height - dy))
    right_x = slice(max(0, -dx), min(width, width - dx))
    return (left_y, left_x), (right_y, right_x)


def pearson_integer(
    field: np.ndarray,
    support: np.ndarray,
    dx: int,
    dy: int,
    *,
    minimum_pairs: int,
) -> dict[str, int] | None:
    left_slice, right_slice = _shift_slices(field.shape, dx, dy)
    pair = np.asarray(support, dtype=bool)[left_slice] & np.asarray(support, dtype=bool)[right_slice]
    count = int(np.count_nonzero(pair))
    if count < minimum_pairs:
        return None
    left = np.asarray(field, dtype=np.int64)[left_slice][pair]
    right = np.asarray(field, dtype=np.int64)[right_slice][pair]
    _ensure_pair_products_safe(left, right)
    sum_left = int(np.sum(left, dtype=np.int64))
    sum_right = int(np.sum(right, dtype=np.int64))
    covariance = count * int(np.sum(left * right, dtype=np.int64)) - sum_left * sum_right
    variance_left = count * int(np.sum(left * left, dtype=np.int64)) - sum_left * sum_left
    variance_right = count * int(np.sum(right * right, dtype=np.int64)) - sum_right * sum_right
    if variance_left <= 0 or variance_right <= 0:
        return None
    return {
        "pairs": count,
        "covariance_numerator": abs(covariance),
        "variance_product": variance_left * variance_right,
    }


def _binary_closed_holes(excursion: np.ndarray, core: np.ndarray, minimum_area: int) -> int:
    selected = np.asarray(core, dtype=bool)
    visible = np.asarray(excursion, dtype=bool) & selected
    cross = np.asarray([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8)
    closed = cv2.morphologyEx(
        visible.astype(np.uint8), cv2.MORPH_CLOSE, cross, iterations=1
    ) > 0
    background = selected & ~closed
    eroded = cv2.erode(
        selected.astype(np.uint8),
        cross,
        iterations=1,
        borderType=cv2.BORDER_CONSTANT,
        borderValue=0,
    ) > 0
    boundary = selected & ~eroded
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        background.astype(np.uint8), connectivity=4, ltype=cv2.CV_32S
    )
    holes = 0
    for component in range(1, count):
        area = int(stats[component, cv2.CC_STAT_AREA])
        if area >= minimum_area and not np.any((labels == component) & boundary):
            holes += 1
    return holes


def closed_loop_count(
    total_fields: Sequence[np.ndarray],
    bodies: Sequence[np.ndarray],
    cores: Sequence[np.ndarray],
    kernels: Mapping[int, IntegerGaussianKernel],
    *,
    floor_l_q: int,
    minimum_hole_area: int,
) -> dict[str, Any]:
    records: list[dict[str, int]] = []
    for body_index, (total, body, core) in enumerate(zip(total_fields, bodies, cores, strict=True)):
        for sigma in (4, 8):
            detail = highpass_q(total, body, kernels[sigma])
            for polarity in (-1, 1):
                holes = _binary_closed_holes(
                    polarity * detail >= floor_l_q,
                    core,
                    minimum_hole_area,
                )
                records.append(
                    {
                        "body_index": body_index,
                        "sigma_px": sigma,
                        "polarity": polarity,
                        "closed_holes": holes,
                    }
                )
    return {"count": sum(record["closed_holes"] for record in records), "records": records}


def white_crest_particle_count(
    candidate: np.ndarray,
    foundation: np.ndarray,
    total_fields: Sequence[np.ndarray],
    bodies: Sequence[np.ndarray],
    cores: Sequence[np.ndarray],
    kernel4: IntegerGaussianKernel,
    *,
    local_floor_l_q: int,
    minimum_delta_luma: int,
    minimum_candidate_luma: int,
    maximum_rgb_range: int,
) -> dict[str, Any]:
    candidate_luma = luma_u8(candidate)
    foundation_luma = luma_u8(foundation)
    delta = candidate_luma.astype(np.int16) - foundation_luma.astype(np.int16)
    rgb_range = candidate.max(axis=2).astype(np.int16) - candidate.min(axis=2).astype(np.int16)
    records: list[dict[str, Any]] = []
    total_count = 0
    for body_index, (total, body, core) in enumerate(zip(total_fields, bodies, cores, strict=True)):
        detail = highpass_q(total, body, kernel4)
        white = (
            np.asarray(core, dtype=bool)
            & (detail >= local_floor_l_q)
            & (delta >= minimum_delta_luma)
            & (candidate_luma >= minimum_candidate_luma)
            & (rgb_range <= maximum_rgb_range)
        )
        count, _, stats, _ = cv2.connectedComponentsWithStats(
            white.astype(np.uint8), connectivity=8, ltype=cv2.CV_32S
        )
        areas = [int(stats[index, cv2.CC_STAT_AREA]) for index in range(1, count)]
        total_count += len(areas)
        records.append({"body_index": body_index, "component_count": len(areas), "areas": areas})
    return {"count": total_count, "records": records}


def lock_counts(
    candidate: np.ndarray,
    baseline: np.ndarray,
    *,
    permission: np.ndarray,
    protected: np.ndarray,
    road_calm: np.ndarray,
    alpha_zero: np.ndarray,
) -> dict[str, int]:
    if candidate.shape != baseline.shape or candidate.dtype != np.uint8 or baseline.dtype != np.uint8:
        raise StrictMetricError("candidate/baseline RGB contract mismatch")
    changed = np.any(candidate != baseline, axis=2)
    return {
        "outside_permission": int(np.count_nonzero(changed & ~np.asarray(permission, dtype=bool))),
        "protected_features": int(np.count_nonzero(changed & np.asarray(protected, dtype=bool))),
        "road_calm_18px": int(np.count_nonzero(changed & np.asarray(road_calm, dtype=bool))),
        "alpha_zero": int(np.count_nonzero(changed & np.asarray(alpha_zero, dtype=bool))),
    }


def primary_gates(metrics: Mapping[str, Any], thresholds: Mapping[str, Any]) -> dict[str, bool]:
    texture = metrics["texture_inside_to_outside_ratio"]
    return {
        "coverage_50_min_365": int(metrics["coverage_50"]) >= int(thresholds["coverage_50_min"]),
        "coverage_25_min_338": int(metrics["coverage_25"]) >= int(thresholds["coverage_25_min"]),
        "quiet_fraction_range_0_908_0_925": (
            float(thresholds["quiet_fraction_min"])
            <= float(metrics["quiet_fraction"])
            <= float(thresholds["quiet_fraction_max"])
        ),
        "dash_bundle_pairs_zero": int(metrics["dash_bundle_pairs"]) == int(thresholds["dash_bundle_pairs_exact"]),
        "orientation_coherence_max_0_14": float(metrics["orientation_coherence"])
        <= float(thresholds["orientation_coherence_max"]),
        "texture_ratio_4_range_0_615_0_64": (
            float(thresholds["texture_ratio_4_min"])
            <= float(texture["4"])
            <= float(thresholds["texture_ratio_4_max"])
        ),
        "texture_ratio_8_range_1_10_1_20": (
            float(thresholds["texture_ratio_8_min"])
            <= float(texture["8"])
            <= float(thresholds["texture_ratio_8_max"])
        ),
    }


def measure_strict_fields(
    delta_luma: np.ndarray,
    bodies: Sequence[np.ndarray],
    kernels: Mapping[int, IntegerGaussianKernel],
    contract: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, np.ndarray]], list[np.ndarray]]:
    """Measure A/unit/total energy and repetition without applying gate rounding."""

    erosion = int(contract["body_core_erosion_px"])
    minimum_core = int(contract["minimum_body_core_pixels"])
    minimum_pairs = int(contract["repetition"]["minimum_pairs_per_lag"])
    minimum_lags = int(contract["repetition"]["minimum_eligible_lags_per_body"])
    minimum_total_lags = int(contract["repetition"]["minimum_eligible_lags_total"])
    lags = [tuple(int(value) for value in pair) for pair in contract["repetition"]["lags_xy"]]
    fields: list[dict[str, np.ndarray]] = []
    cores: list[np.ndarray] = []
    for index, body in enumerate(bodies):
        core = disk_erode(body, erosion)
        if int(np.count_nonzero(core)) < minimum_core:
            raise StrictMetricError(f"body-{index:02d} strict core is too small")
        cores.append(core)
        fields.append(derive_body_fields(delta_luma, body, kernels))

    sub8: dict[str, Any] = {}
    highpasses: dict[str, list[dict[int, np.ndarray]]] = {name: [] for name in ("A", "unit", "total")}
    for name in ("A", "unit", "total"):
        numerator = 0
        denominator = 0
        for field, body, core in zip(fields, bodies, cores, strict=True):
            details = {sigma: highpass_q(field[name], body, kernels[sigma]) for sigma in (2, 4, 8)}
            highpasses[name].append(details)
            numerator += sum_squares(details[2], core)
            denominator += sum_squares(details[8], core)
        if denominator <= 0:
            raise StrictMetricError(f"{name} sub8 denominator collapsed")
        sub8[name] = {
            "numerator": numerator,
            "denominator": denominator,
            "fraction": _decimal_ratio(numerator, denominator),
        }

    energy_records: list[dict[str, Any]] = []
    for index, (field, core, details) in enumerate(
        zip(fields, cores, highpasses["unit"], strict=True)
    ):
        denominator = sum_squares(field["unit"], core)
        if denominator <= 0:
            raise StrictMetricError(f"body-{index:02d} unit energy denominator collapsed")
        record: dict[str, Any] = {"body_index": index, "denominator": denominator}
        for sigma in (4, 8):
            numerator = sum_squares(details[sigma], core)
            record[f"sigma{sigma}"] = {
                "numerator": numerator,
                "energy_percent": 100.0 * _decimal_ratio(numerator, denominator, square_root=True),
            }
        energy_records.append(record)

    repetition_records: dict[str, Any] = {}
    for name in ("A", "unit"):
        body_records: list[dict[str, Any]] = []
        maximum: dict[str, int] | None = None
        for body_index, (core, details) in enumerate(zip(cores, highpasses[name], strict=True)):
            lag_records: list[dict[str, Any]] = []
            for dx, dy in lags:
                result = pearson_integer(details[4], core, dx, dy, minimum_pairs=minimum_pairs)
                if result is None:
                    continue
                record = {"lag_xy": [dx, dy], **result}
                lag_records.append(record)
                if maximum is None or (
                    result["covariance_numerator"] ** 2 * maximum["variance_product"]
                    > maximum["covariance_numerator"] ** 2 * result["variance_product"]
                ):
                    maximum = result
            if len(lag_records) < minimum_lags:
                raise StrictMetricError(f"body-{body_index:02d} {name} has too few eligible repetition lags")
            body_records.append({"body_index": body_index, "lags": lag_records})
        if maximum is None:
            raise StrictMetricError(f"{name} repetition measurement collapsed")
        repetition_records[name] = {
            "maximum": {
                **maximum,
                "absolute_correlation": _decimal_ratio(
                    maximum["covariance_numerator"] ** 2,
                    maximum["variance_product"],
                    square_root=True,
                ),
            },
            "bodies": body_records,
        }

    total_lag_records: list[dict[str, Any]] = []
    total_maximum: dict[str, int] | None = None
    for dx, dy in lags:
        left_chunks: list[np.ndarray] = []
        right_chunks: list[np.ndarray] = []
        for core, details in zip(cores, highpasses["total"], strict=True):
            left_slice, right_slice = _shift_slices(core.shape, dx, dy)
            pair = core[left_slice] & core[right_slice]
            if np.any(pair):
                left_chunks.append(details[4][left_slice][pair])
                right_chunks.append(details[4][right_slice][pair])
        if not left_chunks:
            continue
        left = np.concatenate(left_chunks).astype(np.int64)
        right = np.concatenate(right_chunks).astype(np.int64)
        count = int(left.size)
        if count < minimum_pairs * len(bodies):
            continue
        _ensure_pair_products_safe(left, right)
        sum_left = int(np.sum(left, dtype=np.int64))
        sum_right = int(np.sum(right, dtype=np.int64))
        covariance = abs(count * int(np.sum(left * right, dtype=np.int64)) - sum_left * sum_right)
        variance_left = count * int(np.sum(left * left, dtype=np.int64)) - sum_left * sum_left
        variance_right = count * int(np.sum(right * right, dtype=np.int64)) - sum_right * sum_right
        if variance_left <= 0 or variance_right <= 0:
            continue
        result = {
            "pairs": count,
            "covariance_numerator": covariance,
            "variance_product": variance_left * variance_right,
        }
        total_lag_records.append({"lag_xy": [dx, dy], **result})
        if total_maximum is None or (
            result["covariance_numerator"] ** 2 * total_maximum["variance_product"]
            > total_maximum["covariance_numerator"] ** 2 * result["variance_product"]
        ):
            total_maximum = result
    if total_maximum is None or len(total_lag_records) < minimum_total_lags:
        raise StrictMetricError("total repetition has too few eligible lags")
    repetition_records["total"] = {
        "maximum": {
            **total_maximum,
            "absolute_correlation": _decimal_ratio(
                total_maximum["covariance_numerator"] ** 2,
                total_maximum["variance_product"],
                square_root=True,
            ),
        },
        "lags": total_lag_records,
    }
    return {"sub8": sub8, "per_body_unit_energy": energy_records, "repetition": repetition_records}, fields, cores


def strict_field_gates(measurements: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, bool]:
    sub8_limit = contract["sub8_energy_fraction_max"]
    gates: dict[str, bool] = {}
    for name in ("A", "unit", "total"):
        record = measurements["sub8"][name]
        gates[f"sub8_{name}_max_0_42"] = ratio_le(
            int(record["numerator"]),
            int(record["denominator"]),
            int(sub8_limit["numerator"]),
            int(sub8_limit["denominator"]),
        )
    energy_thresholds = contract["per_body_unit_energy_min_percent"]
    for record in measurements["per_body_unit_energy"]:
        body_index = int(record["body_index"])
        denominator = int(record["denominator"])
        for sigma in (4, 8):
            gates[f"body_{body_index:02d}_unit_sigma{sigma}_energy_min_{energy_thresholds[str(sigma)]}"] = energy_percent_ge(
                int(record[f"sigma{sigma}"]["numerator"]),
                denominator,
                int(energy_thresholds[str(sigma)]),
            )
    limits = contract["repetition"]["maximum_absolute_correlation"]
    for name in ("A", "unit", "total"):
        limit = limits[name]
        maximum = measurements["repetition"][name]["maximum"]
        gates[f"repetition_{name}_max_{limit['numerator']}_over_{limit['denominator']}"] = correlation_le(
            int(maximum["covariance_numerator"]),
            int(maximum["variance_product"]),
            int(limit["numerator"]),
            int(limit["denominator"]),
        )
    return gates
