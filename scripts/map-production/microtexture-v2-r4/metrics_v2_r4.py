"""Vision-aligned r4 residual-window metrics.

Only ``microartifact_occupancy_per_mp`` is a hard-gate input. Blob, finite-line,
and parallel-pair measurements are deterministic, nonblocking diagnostics.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

import numpy as np
from scipy import ndimage


def _gaussian(values: np.ndarray, sigma: float, truncate: float) -> np.ndarray:
    return ndimage.gaussian_filter(
        values.astype(np.float32),
        sigma=float(sigma),
        mode="reflect",
        truncate=float(truncate),
    ).astype(np.float32)


@lru_cache(maxsize=128)
def _line_kernel(
    angle_degrees: int,
    length_px: float,
    core_half_width_px: float,
    flank_inner_px: float,
    flank_outer_px: float,
) -> np.ndarray:
    half_length = float(length_px) * 0.5
    radius = int(math.ceil(math.hypot(half_length, float(flank_outer_px)))) + 2
    yy, xx = np.mgrid[-radius : radius + 1, -radius : radius + 1]
    angle = math.radians(int(angle_degrees))
    cosine, sine = math.cos(angle), math.sin(angle)
    along = xx * cosine + yy * sine
    perpendicular = -xx * sine + yy * cosine
    core = (np.abs(along) <= half_length) & (
        np.abs(perpendicular) <= float(core_half_width_px)
    )
    flank = (
        (np.abs(along) <= half_length)
        & (np.abs(perpendicular) > float(flank_inner_px))
        & (np.abs(perpendicular) <= float(flank_outer_px))
    )
    core_count, flank_count = int(np.count_nonzero(core)), int(np.count_nonzero(flank))
    if not core_count or not flank_count:
        raise RuntimeError("empty r4 finite-line kernel support")
    kernel = np.zeros(along.shape, dtype=np.float32)
    kernel[core] = np.float32(1.0 / core_count)
    kernel[flank] = np.float32(-1.0 / flank_count)
    if abs(float(kernel.sum(dtype=np.float64))) > 1e-6:
        raise RuntimeError("r4 finite-line kernel lost zero-sum contract")
    kernel.setflags(write=False)
    return kernel


def _oriented_responses(
    delta: np.ndarray,
    angles: list[int],
    length_px: float,
    core_half_width_px: float,
    flank_inner_px: float,
    flank_outer_px: float,
) -> list[np.ndarray]:
    return [
        np.abs(
            ndimage.convolve(
                delta,
                _line_kernel(
                    int(angle),
                    float(length_px),
                    float(core_half_width_px),
                    float(flank_inner_px),
                    float(flank_outer_px),
                ),
                mode="reflect",
            )
        ).astype(np.float32)
        for angle in angles
    ]


def _sparse_blob_score(
    delta: np.ndarray, definition: dict[str, Any]
) -> tuple[float, float, int]:
    parameters = definition["diagnostic_parameters"]["sparse_blob"]
    sigma = float(parameters["hessian_sigma_px"])
    truncate = float(definition["gaussian_truncate"])
    dyy = ndimage.gaussian_filter(
        delta, sigma=sigma, order=(2, 0), mode="reflect", truncate=truncate
    )
    dxx = ndimage.gaussian_filter(
        delta, sigma=sigma, order=(0, 2), mode="reflect", truncate=truncate
    )
    dxy = ndimage.gaussian_filter(
        delta, sigma=sigma, order=(1, 1), mode="reflect", truncate=truncate
    )
    trace = dxx + dyy
    radius = np.sqrt(np.maximum(0.0, ((dxx - dyy) * 0.5) ** 2 + dxy**2))
    first = trace * 0.5 + radius
    second = trace * 0.5 - radius
    minimum = np.minimum(np.abs(first), np.abs(second))
    maximum = np.maximum(np.abs(first), np.abs(second))
    isotropic = (first * second > 0) & (
        minimum / np.maximum(maximum, np.float32(1e-12))
        > float(parameters["isotropy_ratio_minimum"])
    )
    response = np.where(isotropic, np.float32(sigma * sigma) * minimum, 0.0)
    local = np.abs(
        delta
        - _gaussian(
            delta,
            float(parameters["occupancy_sigma_px"]),
            truncate,
        )
    )
    occupancy = int(np.count_nonzero(local > float(parameters["occupancy_floor_l"])))
    peak = float(np.max(response))
    score = peak / (1.0 + occupancy / float(parameters["occupancy_penalty_divisor"]))
    return float(score), peak, occupancy


def _finite_line_score(
    delta: np.ndarray, definition: dict[str, Any]
) -> tuple[float, float, int]:
    parameters = definition["diagnostic_parameters"]["finite_line"]
    responses = _oriented_responses(
        delta,
        [int(value) for value in parameters["angles_degrees"]],
        float(parameters["core_length_px"]),
        float(parameters["core_half_width_px"]),
        float(parameters["flank_inner_px"]),
        float(parameters["flank_outer_px"]),
    )
    maximum = np.maximum.reduce(responses)
    top_count = min(int(parameters["top_response_count"]), maximum.size)
    top = np.partition(maximum.ravel(), maximum.size - top_count)[-top_count:]
    occupancy = int(np.count_nonzero(maximum > float(parameters["occupancy_floor_l"])))
    peak = float(np.max(maximum))
    score = float(np.mean(top)) / (
        1.0 + occupancy / float(parameters["occupancy_penalty_divisor"])
    )
    return float(score), peak, occupancy


def _parallel_pair_ratio(
    delta: np.ndarray, definition: dict[str, Any]
) -> tuple[float, float, int]:
    line_parameters = definition["diagnostic_parameters"]["finite_line"]
    parameters = definition["diagnostic_parameters"]["parallel_pair"]
    angles = [int(value) for value in line_parameters["angles_degrees"]]
    responses = _oriented_responses(
        delta,
        angles,
        float(parameters["filter_length_px"]),
        float(parameters["filter_core_half_width_px"]),
        float(parameters["filter_flank_inner_px"]),
        float(parameters["filter_flank_outer_px"]),
    )
    global_peak = max(float(np.max(response)) for response in responses)
    if global_peak <= 1e-12:
        return 0.0, 0.0, 0
    best_pair, valid_pairs = 0.0, 0
    nms_size = int(parameters["nms_size_px"])
    peak_limit = int(parameters["peaks_per_angle"])
    along_maximum = float(parameters["along_maximum_px"])
    perpendicular_minimum = float(parameters["perpendicular_minimum_px"])
    perpendicular_maximum = float(parameters["perpendicular_maximum_px"])
    for angle_degrees, response in zip(angles, responses):
        local_maximum = ndimage.maximum_filter(response, size=nms_size, mode="reflect")
        yy, xx = np.nonzero((response == local_maximum) & (response > 0))
        peaks = sorted(
            (
                (-float(response[y, x]), int(y), int(x))
                for y, x in zip(yy.tolist(), xx.tolist())
            )
        )[:peak_limit]
        angle = math.radians(angle_degrees)
        ux, uy = math.cos(angle), math.sin(angle)
        nx, ny = -uy, ux
        for left_index, (negative_left, left_y, left_x) in enumerate(peaks):
            left_response = -negative_left
            for negative_right, right_y, right_x in peaks[left_index + 1 :]:
                dx, dy = right_x - left_x, right_y - left_y
                along = abs(dx * ux + dy * uy)
                perpendicular = abs(dx * nx + dy * ny)
                if (
                    along <= along_maximum
                    and perpendicular_minimum <= perpendicular <= perpendicular_maximum
                ):
                    valid_pairs += 1
                    best_pair = max(best_pair, min(left_response, -negative_right))
    return float(best_pair / global_peak), float(best_pair), int(valid_pairs)


def measure(
    control: np.ndarray, reference: np.ndarray, definition: dict[str, Any]
) -> dict[str, Any]:
    expected_shape = tuple(int(value) for value in definition["expected_shape_hw"])
    if (
        control.shape != expected_shape
        or reference.shape != expected_shape
        or control.ndim != 2
        or reference.ndim != 2
    ):
        raise ValueError(
            f"r4 metric input must be exact HxW {expected_shape}; "
            f"control={control.shape}, reference={reference.shape}"
        )
    delta = control.astype(np.float32) - reference.astype(np.float32)
    hard = definition["hard_metric"]
    highpass = delta - _gaussian(
        delta,
        float(hard["highpass_sigma_px"]),
        float(definition["gaussian_truncate"]),
    )
    absolute = np.abs(highpass)
    per_mp = float(definition["density_unit_pixels"]) / delta.size
    floor = float(hard["absolute_floor_l"])
    occupancy = float(np.count_nonzero(absolute >= floor) * per_mp)
    excess = float(np.maximum(absolute - floor, 0).sum(dtype=np.float64) * per_mp)
    blob_score, blob_peak, blob_occupancy = _sparse_blob_score(delta, definition)
    line_score, line_peak, line_occupancy = _finite_line_score(delta, definition)
    parallel_ratio, parallel_peak, parallel_pairs = _parallel_pair_ratio(
        delta, definition
    )
    result = {
        "eligible_pixels": int(delta.size),
        "microartifact_occupancy_per_mp": occupancy,
        "microartifact_excess_energy_per_mp": excess,
        "highpass_rms_l": float(np.sqrt(np.mean(highpass**2))),
        "sparse_blob_score": blob_score,
        "sparse_blob_peak_l": blob_peak,
        "sparse_blob_occupancy_pixels": blob_occupancy,
        "finite_line_score": line_score,
        "finite_line_peak_l": line_peak,
        "finite_line_occupancy_pixels": line_occupancy,
        "parallel_pair_ratio": parallel_ratio,
        "parallel_pair_peak_l": parallel_peak,
        "parallel_valid_pair_count": parallel_pairs,
    }
    if any(
        isinstance(value, float) and not math.isfinite(value)
        for value in result.values()
    ):
        raise RuntimeError("non-finite r4 metric")
    return result
