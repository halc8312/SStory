"""Deterministic bounded r6 residual-window metrics.

The detector is deliberately delta-only.  Four independently auditable branch
scores cover dense/coherent grain, sparse spots/blobs, finite lines, and
parallel bundles.  Every branch is monotonically normalized against positive
reference constants frozen in the preregistered metric definition; no score is
divided by an observed occupancy or other artifact-dependent penalty.

``recompute_branch_scores`` is the authority helper for validators.  Reports
must not trust serialized branch or composite scores without recomputing them
from the raw measurements and the frozen definition.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

import numpy as np
from scipy import ndimage


RAW_FLOAT_FIELDS = {
    "grain_occupancy_per_mp",
    "grain_rms_l",
    "grain_coherence_2_to_13",
    "tiny_mass_l",
    "multiscale_blob_strength_l_sqrt_px",
    "finite_line_peak_l",
    "finite_line_top4_mean_l",
    "parallel_pair_peak_l",
    "parallel_pair_ratio",
}
RAW_INTEGER_FIELDS = {
    "eligible_pixels",
    "tiny_component_count",
    "blob_component_count",
    "finite_line_nms_peak_count",
    "parallel_matched_pair_count",
}
SCORE_FIELDS = {
    "grain_score",
    "spot_score",
    "finite_line_score",
    "parallel_bundle_score",
    "hard_composite_score",
}
METRIC_FIELDS = RAW_FLOAT_FIELDS | RAW_INTEGER_FIELDS | SCORE_FIELDS

REFERENCE_KEYS = {
    "grain_occupancy_per_mp",
    "grain_rms_l",
    "tiny_mass_l",
    "tiny_component_count",
    "multiscale_blob_strength_l_sqrt_px",
    "finite_line_peak_l",
    "finite_line_top4_mean_l",
    "parallel_pair_peak_l",
    "parallel_matched_pair_count",
}


def _finite_nonnegative(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be a non-negative finite real")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"{context} must be a non-negative finite real")
    return result


def _positive(value: Any, context: str) -> float:
    result = _finite_nonnegative(value, context)
    if result <= 0.0:
        raise ValueError(f"{context} must be positive")
    return result


def _unit(value: float, reference: float) -> float:
    """Map evidence monotonically to ``[0, 1)`` around a fixed half-scale."""

    if value <= 0.0:
        return 0.0
    return float((2.0 / math.pi) * math.atan(value / reference))


def _score_references(definition: dict[str, Any]) -> dict[str, float]:
    source = definition.get("score_reference_constants")
    if not isinstance(source, dict) or set(source) != REFERENCE_KEYS:
        raise ValueError(
            "score_reference_constants must contain the exact r6 reference keys"
        )
    return {
        key: _positive(source[key], f"score_reference_constants.{key}")
        for key in sorted(REFERENCE_KEYS)
    }


def recompute_branch_scores(
    raw_metrics: dict[str, Any], definition: dict[str, Any]
) -> dict[str, float]:
    """Recompute all bounded branch scores and their hard maximum.

    This public helper intentionally consumes only raw metric fields.  It is
    suitable for calibration, holdout, frozen-threshold, and locked-reference
    report validators.
    """

    references = _score_references(definition)
    required = RAW_FLOAT_FIELDS | RAW_INTEGER_FIELDS
    missing = sorted(required - set(raw_metrics))
    if missing:
        raise ValueError(f"missing raw r6 metrics: {missing}")

    raw: dict[str, float] = {}
    for key in RAW_FLOAT_FIELDS:
        raw[key] = _finite_nonnegative(raw_metrics[key], f"raw_metrics.{key}")
    for key in RAW_INTEGER_FIELDS:
        value = raw_metrics[key]
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise ValueError(f"raw_metrics.{key} must be a non-negative integer")
        if int(value) < 0:
            raise ValueError(f"raw_metrics.{key} must be a non-negative integer")
        raw[key] = float(value)
    for key in ("grain_coherence_2_to_13", "parallel_pair_ratio"):
        if raw[key] > 1.0:
            raise ValueError(f"raw_metrics.{key} must be within 0..1")

    grain_rms = _unit(raw["grain_rms_l"], references["grain_rms_l"])
    grain_dense = min(
        _unit(
            raw["grain_occupancy_per_mp"],
            references["grain_occupancy_per_mp"],
        ),
        grain_rms,
    )
    grain_coherent = raw["grain_coherence_2_to_13"] * grain_rms
    grain_score = max(grain_dense, grain_coherent)

    spot_score = max(
        _unit(raw["tiny_mass_l"], references["tiny_mass_l"]),
        _unit(
            raw["tiny_component_count"],
            references["tiny_component_count"],
        ),
        _unit(
            raw["multiscale_blob_strength_l_sqrt_px"],
            references["multiscale_blob_strength_l_sqrt_px"],
        ),
    )
    finite_line_score = max(
        _unit(raw["finite_line_peak_l"], references["finite_line_peak_l"]),
        _unit(
            raw["finite_line_top4_mean_l"],
            references["finite_line_top4_mean_l"],
        ),
    )
    parallel_bundle_score = min(
        _unit(raw["parallel_pair_peak_l"], references["parallel_pair_peak_l"]),
        _unit(
            raw["parallel_matched_pair_count"],
            references["parallel_matched_pair_count"],
        ),
    )
    hard_composite_score = max(
        grain_score,
        spot_score,
        finite_line_score,
        parallel_bundle_score,
    )
    result = {
        "grain_score": float(grain_score),
        "spot_score": float(spot_score),
        "finite_line_score": float(finite_line_score),
        "parallel_bundle_score": float(parallel_bundle_score),
        "hard_composite_score": float(hard_composite_score),
    }
    if any(
        not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in result.values()
    ):
        raise RuntimeError("non-finite or unbounded r6 branch score")
    return result


def _gaussian(values: np.ndarray, sigma: float, truncate: float) -> np.ndarray:
    return ndimage.gaussian_filter(
        values.astype(np.float32, copy=False),
        sigma=float(sigma),
        mode="reflect",
        truncate=float(truncate),
    ).astype(np.float32)


def _grain_metrics(
    delta: np.ndarray, definition: dict[str, Any]
) -> tuple[float, float, float]:
    parameters = definition["grain_parameters"]
    truncate = float(definition["gaussian_truncate"])
    highpass = delta - _gaussian(
        delta,
        _positive(parameters["highpass_sigma_px"], "grain highpass sigma"),
        truncate,
    )
    absolute = np.abs(highpass)
    floor = _positive(parameters["absolute_floor_l"], "grain absolute floor")
    per_mp = float(definition["density_unit_pixels"]) / delta.size
    occupancy = float(np.count_nonzero(absolute >= floor) * per_mp)
    rms = float(np.sqrt(np.mean(highpass.astype(np.float64) ** 2)))

    low_sigma = _positive(parameters["coherence_low_sigma_px"], "coherence low sigma")
    high_sigma = _positive(
        parameters["coherence_high_sigma_px"], "coherence high sigma"
    )
    if high_sigma <= low_sigma:
        raise ValueError("coherence high sigma must exceed low sigma")
    band = _gaussian(delta, low_sigma, truncate) - _gaussian(
        delta, high_sigma, truncate
    )
    band = band.astype(np.float64)
    band -= float(np.mean(band))
    if not np.any(band):
        return occupancy, rms, 0.0

    minimum_period = int(parameters["coherence_min_period_px"])
    maximum_period = int(parameters["coherence_max_period_px"])
    if minimum_period < 2 or maximum_period < minimum_period:
        raise ValueError("invalid grain coherence period bounds")
    angles = [int(value) for value in parameters["coherence_angles_degrees"]]
    if not angles:
        raise ValueError("grain coherence angles cannot be empty")
    offsets: set[tuple[int, int]] = set()
    for period in range(minimum_period, maximum_period + 1):
        for angle_degrees in angles:
            angle = math.radians(angle_degrees)
            dx = int(round(period * math.cos(angle)))
            dy = int(round(period * math.sin(angle)))
            if dx or dy:
                offsets.add((dy, dx))

    height, width = band.shape
    coherence = 0.0
    for dy, dx in sorted(offsets):
        if abs(dy) >= height or abs(dx) >= width:
            continue
        left_y = slice(max(0, dy), min(height, height + dy))
        left_x = slice(max(0, dx), min(width, width + dx))
        right_y = slice(max(0, -dy), min(height, height - dy))
        right_x = slice(max(0, -dx), min(width, width - dx))
        left = band[left_y, left_x]
        right = band[right_y, right_x]
        denominator = math.sqrt(
            float(np.sum(left * left, dtype=np.float64))
            * float(np.sum(right * right, dtype=np.float64))
        )
        if denominator > 0.0:
            correlation = abs(
                float(np.sum(left * right, dtype=np.float64)) / denominator
            )
            coherence = max(coherence, correlation)
    return occupancy, rms, float(min(coherence, 1.0))


def _component_descriptors(
    field: np.ndarray,
    floor: float,
) -> list[tuple[int, float, float, float]]:
    """Return ``(area, peak, excess_mass, elongation)`` for signed components."""

    descriptors: list[tuple[int, float, float, float]] = []
    structure = np.ones((3, 3), dtype=np.uint8)
    for polarity in (1.0, -1.0):
        signed = field * np.float32(polarity)
        labels, count = ndimage.label(signed >= floor, structure=structure)
        if not count:
            continue
        for component_index, component_slice in enumerate(
            ndimage.find_objects(labels), start=1
        ):
            if component_slice is None:
                continue
            local_mask = labels[component_slice] == component_index
            local_values = signed[component_slice][local_mask].astype(np.float64)
            area = int(local_values.size)
            if not area:
                continue
            local_y, local_x = np.nonzero(local_mask)
            weights = local_values
            weight_sum = float(np.sum(weights, dtype=np.float64))
            center_x = float(np.sum(local_x * weights) / weight_sum)
            center_y = float(np.sum(local_y * weights) / weight_sum)
            dx = local_x.astype(np.float64) - center_x
            dy = local_y.astype(np.float64) - center_y
            covariance = np.array(
                [
                    [
                        float(np.sum(weights * dx * dx) / weight_sum),
                        float(np.sum(weights * dx * dy) / weight_sum),
                    ],
                    [
                        float(np.sum(weights * dx * dy) / weight_sum),
                        float(np.sum(weights * dy * dy) / weight_sum),
                    ],
                ],
                dtype=np.float64,
            )
            eigenvalues = np.linalg.eigvalsh(covariance)
            elongation = math.sqrt(
                (float(eigenvalues[1]) + 0.25) / (float(eigenvalues[0]) + 0.25)
            )
            descriptors.append(
                (
                    area,
                    float(np.max(local_values)),
                    float(np.sum(np.maximum(local_values - floor, 0.0))),
                    float(elongation),
                )
            )
    return descriptors


def _spot_metrics(
    delta: np.ndarray, definition: dict[str, Any]
) -> tuple[int, float, int, float]:
    parameters = definition["spot_parameters"]
    floor = _positive(parameters["component_floor_l"], "spot component floor")
    tiny_area_maximum = int(parameters["tiny_area_max_pixels"])
    tiny_top_count = int(parameters["tiny_top_count"])
    if tiny_area_maximum < 1 or tiny_top_count < 1:
        raise ValueError("tiny component bounds must be positive")

    raw_components = _component_descriptors(delta, floor)
    tiny_components = [
        descriptor
        for descriptor in raw_components
        if descriptor[0] <= tiny_area_maximum
    ]
    tiny_masses = sorted(
        (descriptor[2] for descriptor in tiny_components), reverse=True
    )[:tiny_top_count]
    tiny_mass = float(sum(tiny_masses))

    blob_area_minimum = int(parameters["blob_area_min_pixels"])
    blob_area_maximum = int(parameters["blob_area_max_pixels"])
    elongation_maximum = _positive(
        parameters["blob_elongation_maximum"], "blob elongation maximum"
    )
    if blob_area_minimum < 1 or blob_area_maximum < blob_area_minimum:
        raise ValueError("invalid blob component area bounds")
    sigmas = [_positive(value, "blob sigma") for value in parameters["blob_sigmas_px"]]
    if not sigmas:
        raise ValueError("blob sigma list cannot be empty")

    truncate = float(definition["gaussian_truncate"])
    best_strength = 0.0
    best_count = 0
    for sigma in sigmas:
        smoothed = _gaussian(delta, sigma, truncate)
        qualified: list[tuple[int, float, float, float]] = []
        for descriptor in _component_descriptors(smoothed, floor):
            area, peak, _, elongation = descriptor
            if (
                blob_area_minimum <= area <= blob_area_maximum
                and elongation <= elongation_maximum
            ):
                qualified.append(descriptor)
                strength = max(peak - floor, 0.0) * math.sqrt(area) / elongation
                best_strength = max(best_strength, float(strength))
        best_count = max(best_count, len(qualified))
    return len(tiny_components), tiny_mass, best_count, float(best_strength)


@lru_cache(maxsize=256)
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
    core_count = int(np.count_nonzero(core))
    flank_count = int(np.count_nonzero(flank))
    if not core_count or not flank_count:
        raise RuntimeError("empty r6 finite-line kernel support")
    kernel = np.zeros(along.shape, dtype=np.float32)
    kernel[core] = np.float32(1.0 / core_count)
    kernel[flank] = np.float32(-1.0 / flank_count)
    if abs(float(kernel.sum(dtype=np.float64))) > 1e-6:
        raise RuntimeError("r6 finite-line kernel lost zero-sum contract")
    kernel.setflags(write=False)
    return kernel


def _line_bank(
    delta: np.ndarray, definition: dict[str, Any]
) -> list[tuple[int, float, np.ndarray]]:
    parameters = definition["finite_line_parameters"]
    angles = [int(value) for value in parameters["angles_degrees"]]
    lengths = [float(value) for value in parameters["lengths_px"]]
    if angles != list(range(0, 180, 15)):
        raise ValueError("r6 finite-line angles must be exactly 0..165 by 15 degrees")
    if lengths != [5.0, 9.0, 15.0, 23.0]:
        raise ValueError("r6 finite-line lengths must be exactly 5, 9, 15, 23 px")
    core_half_width = _positive(
        parameters["core_half_width_px"], "line core half width"
    )
    flank_inner = _positive(parameters["flank_inner_px"], "line flank inner")
    flank_outer = _positive(parameters["flank_outer_px"], "line flank outer")
    if flank_outer <= flank_inner:
        raise ValueError("line flank outer must exceed flank inner")
    result: list[tuple[int, float, np.ndarray]] = []
    for length in lengths:
        for angle in angles:
            response = np.abs(
                ndimage.convolve(
                    delta,
                    _line_kernel(
                        angle,
                        length,
                        core_half_width,
                        flank_inner,
                        flank_outer,
                    ),
                    mode="reflect",
                )
            ).astype(np.float32)
            result.append((angle, length, response))
    return result


@lru_cache(maxsize=256)
def _parallel_core_kernel(
    angle_degrees: int, length_px: float, core_half_width_px: float
) -> np.ndarray:
    half_length = float(length_px) * 0.5
    radius = int(math.ceil(math.hypot(half_length, core_half_width_px))) + 2
    yy, xx = np.mgrid[-radius : radius + 1, -radius : radius + 1]
    angle = math.radians(int(angle_degrees))
    along = xx * math.cos(angle) + yy * math.sin(angle)
    perpendicular = -xx * math.sin(angle) + yy * math.cos(angle)
    core = (np.abs(along) <= half_length) & (
        np.abs(perpendicular) <= float(core_half_width_px)
    )
    core_count = int(np.count_nonzero(core))
    if not core_count:
        raise RuntimeError("empty r6 parallel core kernel support")
    kernel = np.zeros(along.shape, dtype=np.float32)
    kernel[core] = np.float32(1.0 / core_count)
    kernel.setflags(write=False)
    return kernel


def _parallel_core_bank(
    delta: np.ndarray, definition: dict[str, Any]
) -> list[tuple[int, float, np.ndarray]]:
    line_parameters = definition["finite_line_parameters"]
    angles = [int(value) for value in line_parameters["angles_degrees"]]
    lengths = [float(value) for value in line_parameters["lengths_px"]]
    core_half_width = _positive(
        line_parameters["core_half_width_px"], "parallel core half width"
    )
    result: list[tuple[int, float, np.ndarray]] = []
    for length in lengths:
        for angle in angles:
            response = np.abs(
                ndimage.convolve(
                    delta,
                    _parallel_core_kernel(angle, length, core_half_width),
                    mode="reflect",
                )
            ).astype(np.float32)
            result.append((angle, length, response))
    return result


def _nms_peaks(
    response: np.ndarray,
    nms_size: int,
    response_floor: float,
    peak_limit: int,
) -> list[tuple[float, int, int]]:
    if nms_size < 1 or nms_size % 2 != 1 or peak_limit < 1:
        raise ValueError("NMS size must be positive odd and peak limit positive")
    local_maximum = ndimage.maximum_filter(response, size=nms_size, mode="reflect")
    maxima = (
        (response == local_maximum) & (response >= response_floor) & (response > 0.0)
    )
    plateau_labels, plateau_count = ndimage.label(
        maxima, structure=np.ones((3, 3), dtype=np.uint8)
    )
    peaks: list[tuple[float, int, int]] = []
    for plateau_index, plateau_slice in enumerate(
        ndimage.find_objects(plateau_labels), start=1
    ):
        if plateau_slice is None:
            continue
        local_y, local_x = np.nonzero(plateau_labels[plateau_slice] == plateau_index)
        if not local_y.size:
            continue
        absolute_y = local_y + int(plateau_slice[0].start)
        absolute_x = local_x + int(plateau_slice[1].start)
        values = response[absolute_y, absolute_x]
        best_value = float(np.max(values))
        candidates = sorted(
            (int(y), int(x))
            for y, x, value in zip(
                absolute_y.tolist(), absolute_x.tolist(), values.tolist()
            )
            if float(value) == best_value
        )
        best_y, best_x = candidates[0]
        peaks.append((best_value, best_y, best_x))
    return sorted(peaks, key=lambda item: (-item[0], item[1], item[2]))[:peak_limit]


def _finite_line_metrics(
    bank: list[tuple[int, float, np.ndarray]], definition: dict[str, Any]
) -> tuple[float, float, int]:
    parameters = definition["finite_line_parameters"]
    nms_size = int(parameters["nms_size_px"])
    response_floor = _positive(parameters["response_floor_l"], "line response floor")
    peak_limit = int(parameters["peaks_per_filter"])
    duplicate_radius = int(parameters["duplicate_peak_radius_px"])
    if duplicate_radius < 0:
        raise ValueError("duplicate peak radius must be non-negative")

    global_peak = 0.0
    candidates: list[tuple[float, int, int, int, float]] = []
    for angle, length, response in bank:
        global_peak = max(global_peak, float(np.max(response)))
        peaks = _nms_peaks(response, nms_size, response_floor, peak_limit)
        candidates.extend((value, y, x, angle, length) for value, y, x in peaks)

    selected: list[tuple[float, int, int, int, float]] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (-item[0], item[1], item[2], item[3], item[4]),
    ):
        _, y, x, _, _ = candidate
        if all(
            max(abs(y - other_y), abs(x - other_x)) > duplicate_radius
            for _, other_y, other_x, _, _ in selected
        ):
            selected.append(candidate)
            if len(selected) == 4:
                break
    # Missing peaks are explicit zeroes, so the top-4 mean is monotone as new
    # spatially distinct peaks appear.
    top4_mean = float(sum(item[0] for item in selected) / 4.0)
    return global_peak, top4_mean, len(selected)


def _parallel_metrics(
    bank: list[tuple[int, float, np.ndarray]], definition: dict[str, Any]
) -> tuple[float, float, int]:
    parameters = definition["parallel_pair_parameters"]
    response_floor = _positive(
        parameters["response_floor_l"], "parallel response floor"
    )
    peak_limit = int(parameters["peaks_per_filter"])
    nms_size = int(parameters["nms_size_px"])
    minimum_pair_count = int(parameters["minimum_matched_pair_count"])
    along_maximum = _positive(parameters["along_maximum_px"], "parallel along maximum")
    perpendicular_minimum = _positive(
        parameters["perpendicular_minimum_px"], "parallel perpendicular minimum"
    )
    perpendicular_maximum = _positive(
        parameters["perpendicular_maximum_px"], "parallel perpendicular maximum"
    )
    if (
        perpendicular_maximum <= perpendicular_minimum
        or peak_limit < 2
        or minimum_pair_count < 2
    ):
        raise ValueError("invalid parallel pair geometry or peak limit")

    references = _score_references(definition)
    best_key: tuple[float, float, int, int, float] | None = None
    selected_pair_peak = 0.0
    selected_pair_count = 0
    global_core_peak = 0.0
    for angle_degrees, length, response in bank:
        global_core_peak = max(global_core_peak, float(np.max(response)))
        peaks = _nms_peaks(response, nms_size, response_floor, peak_limit)
        angle = math.radians(angle_degrees)
        ux, uy = math.cos(angle), math.sin(angle)
        nx, ny = -uy, ux
        candidates: list[tuple[float, int, int]] = []
        for left_index, (left_response, left_y, left_x) in enumerate(peaks):
            for right_index in range(left_index + 1, len(peaks)):
                right_response, right_y, right_x = peaks[right_index]
                dx, dy = right_x - left_x, right_y - left_y
                along = abs(dx * ux + dy * uy)
                perpendicular = abs(dx * nx + dy * ny)
                if (
                    along <= along_maximum
                    and perpendicular_minimum <= perpendicular <= perpendicular_maximum
                ):
                    candidates.append(
                        (
                            float(min(left_response, right_response)),
                            left_index,
                            right_index,
                        )
                    )
        used: set[int] = set()
        selected_pairs: list[float] = []
        for strength, left_index, right_index in sorted(
            candidates, key=lambda item: (-item[0], item[1], item[2])
        ):
            if left_index in used or right_index in used:
                continue
            used.add(left_index)
            used.add(right_index)
            selected_pairs.append(strength)
        pair_peak = max(selected_pairs, default=0.0)
        pair_count = len(selected_pairs)
        if pair_count < minimum_pair_count:
            pair_peak = 0.0
            pair_count = 0
        score = min(
            _unit(pair_peak, references["parallel_pair_peak_l"]),
            _unit(pair_count, references["parallel_matched_pair_count"]),
        )
        candidate_key = (score, pair_peak, pair_count, -angle_degrees, -length)
        if best_key is None or candidate_key > best_key:
            best_key = candidate_key
            selected_pair_peak = pair_peak
            selected_pair_count = pair_count

    ratio = selected_pair_peak / global_core_peak if global_core_peak > 0.0 else 0.0
    return (
        float(selected_pair_peak),
        float(min(max(ratio, 0.0), 1.0)),
        selected_pair_count,
    )


def _zero_raw_metrics(eligible_pixels: int) -> dict[str, Any]:
    result: dict[str, Any] = {key: 0.0 for key in RAW_FLOAT_FIELDS}
    result.update({key: 0 for key in RAW_INTEGER_FIELDS})
    result["eligible_pixels"] = int(eligible_pixels)
    return result


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
            f"r6 metric input must be exact HxW {expected_shape}; "
            f"control={control.shape}, reference={reference.shape}"
        )
    control_float = control.astype(np.float32)
    reference_float = reference.astype(np.float32)
    if not np.all(np.isfinite(control_float)) or not np.all(
        np.isfinite(reference_float)
    ):
        raise ValueError("r6 metric input must be finite")
    delta = control_float - reference_float
    if not np.all(np.isfinite(delta)):
        raise ValueError("r6 metric delta must be finite")
    if not np.any(delta):
        raw = _zero_raw_metrics(delta.size)
        return {**raw, **recompute_branch_scores(raw, definition)}

    grain_occupancy, grain_rms, grain_coherence = _grain_metrics(delta, definition)
    tiny_count, tiny_mass, blob_count, blob_strength = _spot_metrics(delta, definition)
    line_bank = _line_bank(delta, definition)
    line_peak, line_top4, line_peak_count = _finite_line_metrics(line_bank, definition)
    parallel_bank = _parallel_core_bank(delta, definition)
    pair_peak, pair_ratio, pair_count = _parallel_metrics(parallel_bank, definition)
    raw = {
        "eligible_pixels": int(delta.size),
        "grain_occupancy_per_mp": float(grain_occupancy),
        "grain_rms_l": float(grain_rms),
        "grain_coherence_2_to_13": float(grain_coherence),
        "tiny_component_count": int(tiny_count),
        "tiny_mass_l": float(tiny_mass),
        "blob_component_count": int(blob_count),
        "multiscale_blob_strength_l_sqrt_px": float(blob_strength),
        "finite_line_peak_l": float(line_peak),
        "finite_line_top4_mean_l": float(line_top4),
        "finite_line_nms_peak_count": int(line_peak_count),
        "parallel_pair_peak_l": float(pair_peak),
        "parallel_pair_ratio": float(pair_ratio),
        "parallel_matched_pair_count": int(pair_count),
    }
    result = {**raw, **recompute_branch_scores(raw, definition)}
    if set(result) != METRIC_FIELDS:
        raise RuntimeError("r6 metric field-set drift")
    if any(
        isinstance(value, float) and not math.isfinite(value)
        for value in result.values()
    ):
        raise RuntimeError("non-finite r6 metric")
    return result
