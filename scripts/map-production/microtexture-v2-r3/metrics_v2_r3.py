"""r3 metrics with a public deterministic null and spatial parallel fallback."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
from scipy import ndimage

from common import canonical_json_bytes


@dataclass(frozen=True)
class Ridge:
    center_x: float
    center_y: float
    angle_degrees: float
    length_px: float
    width_px: float
    energy: float


def _gaussian(values: np.ndarray, sigma: float, truncate: float) -> np.ndarray:
    return ndimage.gaussian_filter(
        values.astype(np.float32), sigma=sigma, mode="reflect", truncate=truncate
    ).astype(np.float32)


def _components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    labels, count = ndimage.label(
        mask.astype(bool), structure=np.ones((3, 3), dtype=np.uint8)
    )
    return labels.astype(np.int32), int(count)


def _component_records(
    labels: np.ndarray, count: int, high: np.ndarray, threshold: float
) -> list[tuple[int, float]]:
    records = []
    for index, slices in enumerate(ndimage.find_objects(labels, max_label=count), 1):
        if slices is None:
            continue
        local = labels[slices] == index
        area = int(local.sum())
        if area:
            records.append(
                (
                    area,
                    float(
                        np.maximum(high[slices][local] - np.float32(threshold), 0).sum()
                    ),
                )
            )
    return records


def _ridges(
    delta: np.ndarray, eligible: np.ndarray, definition: dict[str, Any]
) -> tuple[list[Ridge], np.ndarray]:
    sigma, truncate = (
        float(definition["ridge_sigma_px"]),
        float(definition["gaussian_truncate"]),
    )
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
    first, second = trace * 0.5 + radius, trace * 0.5 - radius
    major, minor = (
        np.maximum(np.abs(first), np.abs(second)),
        np.minimum(np.abs(first), np.abs(second)),
    )
    response = np.maximum(major - minor, 0).astype(np.float32)
    labels, count = _components(
        eligible
        & (response >= np.float32(definition["ridge_response_floor"]))
        & (major >= 1.5 * np.maximum(minor, 1e-7))
    )
    minimum, maximum = [float(value) for value in definition["short_ridge_length_px"]]
    result: list[Ridge] = []
    for index in range(1, count + 1):
        yy, xx = np.nonzero(labels == index)
        if len(xx) < 2:
            continue
        coordinates = np.column_stack((xx.astype(np.float64), yy.astype(np.float64)))
        centered = coordinates - coordinates.mean(axis=0)
        eigenvalues, eigenvectors = np.linalg.eigh(
            centered.T @ centered / len(coordinates)
        )
        order = np.argsort(eigenvalues)[::-1]
        eigenvalues, direction = (
            np.maximum(eigenvalues[order], 0),
            eigenvectors[:, order[0]],
        )
        length = 4 * math.sqrt(float(eigenvalues[0]) + 1 / 12)
        width = 4 * math.sqrt(float(eigenvalues[1]) + 1 / 12)
        if minimum <= length <= maximum and width <= float(
            definition["short_ridge_width_max_px"]
        ):
            result.append(
                Ridge(
                    float(xx.mean()),
                    float(yy.mean()),
                    math.degrees(math.atan2(float(direction[1]), float(direction[0])))
                    % 180,
                    length,
                    width,
                    float(response[labels == index].sum()),
                )
            )
    result.sort(
        key=lambda item: (
            item.center_y,
            item.center_x,
            item.length_px,
            item.angle_degrees,
        )
    )
    return result, response


def _parallel_counts(
    ridges: list[Ridge], definition: dict[str, Any]
) -> tuple[int, int]:
    observed = opportunity = 0
    for left_index, left in enumerate(ridges):
        for right in ridges[left_index + 1 :]:
            if math.hypot(
                left.center_x - right.center_x, left.center_y - right.center_y
            ) > float(definition["parallel_center_distance_max_px"]):
                continue
            opportunity += 1
            delta = abs(left.angle_degrees - right.angle_degrees)
            if min(delta, 180 - delta) <= float(
                definition["parallel_angle_max_degrees"]
            ):
                observed += 1
    return observed, opportunity


def _parallel_null(
    ridges: list[Ridge], definition: dict[str, Any]
) -> tuple[int, int, float, float, float]:
    observed, opportunity = _parallel_counts(ridges, definition)
    geometry = [
        {
            "x": ridge.center_x,
            "y": ridge.center_y,
            "length": ridge.length_px,
            "angle": ridge.angle_degrees,
        }
        for ridge in ridges
    ]
    geometry_digest = hashlib.sha256(canonical_json_bytes(geometry)).digest()
    seed = int(definition["parallel_null"]["seed_hex"], 16) ^ int.from_bytes(
        geometry_digest[:8], "big"
    )
    rng = np.random.default_rng(seed)
    angles = np.asarray([ridge.angle_degrees for ridge in ridges], dtype=np.float64)
    counts = np.empty(int(definition["parallel_null"]["iterations"]), dtype=np.float64)
    for index in range(len(counts)):
        permuted = [
            replace(ridge, angle_degrees=float(angle))
            for ridge, angle in zip(ridges, rng.permutation(angles))
        ]
        counts[index] = _parallel_counts(permuted, definition)[0]
    mean, standard_deviation = float(counts.mean()), float(counts.std(ddof=0))
    excess_z = (observed - mean) / max(
        standard_deviation,
        float(definition["parallel_null"]["standard_deviation_floor"]),
    )
    return observed, opportunity, mean, standard_deviation, float(excess_z)


def measure(
    control: np.ndarray, reference: np.ndarray, definition: dict[str, Any]
) -> dict[str, Any]:
    if control.shape != reference.shape or control.ndim != 2:
        raise ValueError("control/reference shape drift")
    delta = control.astype(np.float32) - reference.astype(np.float32)
    eligible = np.ones(delta.shape, dtype=bool)
    per_mp = float(definition["density_unit_pixels"]) / delta.size
    fine = np.abs(
        delta
        - _gaussian(
            delta,
            float(definition["fine_sigma_px"]),
            float(definition["gaussian_truncate"]),
        )
    )
    broad = np.abs(
        delta
        - _gaussian(
            delta,
            float(definition["broad_sigma_px"]),
            float(definition["gaussian_truncate"]),
        )
    )
    primary = float(definition["primary_jnd_threshold_l"])
    labels, count = _components(fine >= primary)
    records = _component_records(labels, count, fine, primary)
    speck_min, speck_max = [int(value) for value in definition["speck_area_px"]]
    blob_min, blob_max = [int(value) for value in definition["microblob_area_px"]]
    specks = [record for record in records if speck_min <= record[0] <= speck_max]
    blobs = [record for record in records if blob_min <= record[0] <= blob_max]
    micro = np.zeros(delta.shape, dtype=bool)
    for index in range(1, count + 1):
        area = int(np.count_nonzero(labels == index))
        if speck_min <= area <= blob_max:
            micro |= labels == index
    parent = (broad >= float(definition["broad_parent_floor_l"])) & (
        broad >= float(definition["broad_parent_ratio"]) * np.maximum(fine, 1e-7)
    )
    parent_fraction = (
        float(np.count_nonzero(parent & micro) / micro.sum()) if np.any(micro) else 1.0
    )
    ridges, response = _ridges(delta, eligible, definition)
    observed, opportunity, null_mean, null_std, excess_z = _parallel_null(
        ridges, definition
    )
    result = {
        "eligible_pixels": int(delta.size),
        "speck_density_per_mp": float(len(specks) * per_mp),
        "microblob_excess_energy_per_mp": float(
            sum(record[1] for record in blobs) * per_mp
        ),
        "fine_to_broad_energy_ratio": float(
            np.mean(fine**2) / max(float(np.mean(broad**2)), 1e-12)
        ),
        "broad_parent_support_fraction": parent_fraction,
        "short_ridge_count": len(ridges),
        "short_ridge_density_per_mp": float(len(ridges) * per_mp),
        "short_ridge_response_energy_per_mp": float(
            sum(ridge.energy for ridge in ridges) * per_mp
        ),
        "parallel_bundle_pair_count": observed,
        "parallel_bundle_density_per_mp": float(observed * per_mp),
        "parallel_neighbor_opportunity_count": opportunity,
        "parallel_neighbor_pair_fraction": float(observed / opportunity)
        if opportunity
        else 0.0,
        "parallel_bundle_null_mean": null_mean,
        "parallel_bundle_null_standard_deviation": null_std,
        "parallel_bundle_excess_z": excess_z,
        "ridge_response_rms": float(np.sqrt(np.mean(response**2))),
    }
    if any(
        isinstance(value, float) and not math.isfinite(value)
        for value in result.values()
    ):
        raise RuntimeError("non-finite r3 metric")
    return result
