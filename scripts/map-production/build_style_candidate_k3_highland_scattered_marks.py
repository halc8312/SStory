#!/usr/bin/env python3
"""Build at most four TEMP-only highland scattered-mark probes.

The probe removes v18's dense local weave with a fixed median operator, then
places source-authored short dark fragments extracted from the frozen v18
highland and a hash-locked ImageGen highland donor.  Fragment silhouettes and
pigment deltas come from connected source pixels; the tool draws no synthetic
terrain geometry.  Placement is deterministic, non-periodic, density-weighted
Poisson sampling with source-derived broad gaps and locally de-correlated
rotations.

This module is exploration-only.  It must never write a persistent candidate,
specification, manifest, prompt, or control asset.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts/map-production"
OUT = ROOT / "tmp/map-production/k3-semantic-cleanup-v19-scattered-marks"
V18 = ROOT / (
    "world/map-production/style-assets/k3-v18-reconstruction-base.png"
)
V8 = ROOT / (
    "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/"
    "highland-planar-v8.png"
)
P8 = ROOT / (
    "world/map-production/prompts/"
    "style-candidate-k-v3-highland-planar-donor-v8.generation.txt"
)
HARNESS = SCRIPTS / "build_style_candidate_k3_highland_phase_synthesis.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

EXPECTED = {
    V18: "013320af2f3296200a7d0b179e3a495f1e7905462213a6c645d85669dec02882",
    V8: "95e4533d711e2cce1e196a951d2d3895cfc868246147c1c2c4768aeaad5fed9a",
    P8: "8b2054e551f6f0e9764911fc5d95feab8d328d0b2e3f145207514a9a7f338258",
}

TARGET_BOX = (930, 0, 1536, 560)
PNG = {"format": "PNG", "compress_level": 9, "optimize": False}
CANDIDATE_LIMIT = 4
ORIENTATION_BINS = 12
LOCAL_ORIENTATION_RADIUS_PX = 48.0
LOCAL_PARALLEL_DELTA_DEGREES = 12.0


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


harness = load_module("scattered_marks_harness", HARNESS)
harness.OUT = OUT
k3 = harness.k3


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def angular_delta(first: float, second: float) -> float:
    delta = abs(first - second) % 180.0
    return min(delta, 180.0 - delta)


@dataclass(frozen=True)
class Fragment:
    source: str
    source_component: int
    residual: np.ndarray
    matte: np.ndarray
    principal_angle_degrees: float
    area_px: int
    span_px: int
    sha256: str


def principal_orientation(mask: np.ndarray) -> tuple[float, float]:
    ys, xs = np.nonzero(mask)
    if len(xs) < 2:
        return 0.0, 1.0
    coordinates = np.column_stack((xs, ys)).astype(np.float64)
    coordinates -= coordinates.mean(axis=0, keepdims=True)
    covariance = coordinates.T @ coordinates / max(len(coordinates) - 1, 1)
    values, vectors = np.linalg.eigh(covariance)
    order = np.argsort(values)[::-1]
    major = vectors[:, order[0]]
    major_value = max(float(values[order[0]]), 1e-9)
    minor_value = max(float(values[order[1]]), 1e-9)
    angle = math.degrees(math.atan2(float(major[1]), float(major[0]))) % 180.0
    return angle, math.sqrt(major_value / minor_value)


def has_hole(mask: np.ndarray) -> bool:
    contours, hierarchy = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
    )
    if hierarchy is None:
        return False
    return any(int(item[3]) >= 0 for item in hierarchy[0])


def fragment_digest(residual: np.ndarray, matte: np.ndarray) -> str:
    digest = hashlib.sha256()
    digest.update(np.asarray(residual, np.int16).tobytes())
    digest.update(np.asarray(matte, np.uint8).tobytes())
    return digest.hexdigest()


def extract_fragments(
    source_l: np.ndarray,
    permission: np.ndarray,
    *,
    source_name: str,
    dark_threshold: int,
) -> tuple[list[Fragment], np.ndarray, dict[str, Any]]:
    if source_l.shape != permission.shape:
        raise RuntimeError(f"fragment permission shape mismatch for {source_name}")
    background = cv2.medianBlur(source_l, 15).astype(np.int16)
    dark = background - source_l.astype(np.int16)
    source_core = k3.erode(permission, 3)
    seeds = (dark >= dark_threshold) & source_core
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        seeds.astype(np.uint8), 8
    )
    fragments: list[Fragment] = []
    selected_source_pixels = np.zeros(source_l.shape, bool)
    seen: set[str] = set()
    rejection_counts: dict[str, int] = {
        "area_or_span": 0,
        "aspect": 0,
        "fill": 0,
        "hole": 0,
        "duplicate": 0,
    }
    for component in range(1, count):
        area = int(stats[component, cv2.CC_STAT_AREA])
        width = int(stats[component, cv2.CC_STAT_WIDTH])
        height = int(stats[component, cv2.CC_STAT_HEIGHT])
        span = max(width, height)
        if not (12 <= area <= 180 and 8 <= span <= 28):
            rejection_counts["area_or_span"] += 1
            continue
        left = int(stats[component, cv2.CC_STAT_LEFT])
        top = int(stats[component, cv2.CC_STAT_TOP])
        local = labels[top : top + height, left : left + width] == component
        angle, aspect = principal_orientation(local)
        if not (1.35 <= aspect <= 6.5):
            rejection_counts["aspect"] += 1
            continue
        fill = area / max(width * height, 1)
        if fill > 0.78:
            rejection_counts["fill"] += 1
            continue
        if has_hole(local):
            rejection_counts["hole"] += 1
            continue
        # Keep the exact connected source pixels and their exact local-dark
        # pigment deltas.  The two-pixel empty frame supports later rotation;
        # it contributes no generated mark geometry.
        residual = np.zeros((height + 4, width + 4), np.int16)
        matte = np.zeros((height + 4, width + 4), np.uint8)
        # Preserve the source shape and source ordering of pigment strength,
        # while capping the applied local-dark tail below the unchanged
        # structural-ink threshold.  This prevents one source fragment from
        # becoming several synthetic Hough strokes after rotation.
        local_delta = np.clip(-dark[top : top + height, left : left + width], -25, 0)
        residual[2:-2, 2:-2][local] = local_delta[local]
        matte[2:-2, 2:-2][local] = 255
        digest = fragment_digest(residual, matte)
        if digest in seen:
            rejection_counts["duplicate"] += 1
            continue
        seen.add(digest)
        selected_source_pixels[top : top + height, left : left + width] |= local
        fragments.append(
            Fragment(
                source=source_name,
                source_component=component,
                residual=residual,
                matte=matte,
                principal_angle_degrees=angle,
                area_px=area,
                span_px=span,
                sha256=digest,
            )
        )
    if len(fragments) < 40:
        raise RuntimeError(
            f"too few source-authored fragments from {source_name}: {len(fragments)}"
        )
    return fragments, selected_source_pixels, {
        "source": source_name,
        "detector": "median15 local-dark connected pixels",
        "dark_threshold_lab_l": dark_threshold,
        "connected_components_seen": count - 1,
        "accepted_unique_fragments": len(fragments),
        "accepted_source_pixels": int(selected_source_pixels.sum()),
        "area_range_px": [12, 180],
        "span_range_px": [8, 28],
        "principal_aspect_range": [1.35, 6.5],
        "maximum_fill_fraction": 0.78,
        "holes_allowed": False,
        "rejections": rejection_counts,
    }


def source_density_field(
    selected: np.ndarray,
    target_shape: tuple[int, int],
    *,
    shift_xy: tuple[int, int],
) -> np.ndarray:
    # Broad placement density comes only from the donor's real fragment
    # distribution.  It is never rendered into the candidate.
    density = cv2.GaussianBlur(
        selected.astype(np.float32),
        (0, 0),
        sigmaX=72.0,
        sigmaY=72.0,
        borderType=cv2.BORDER_REFLECT,
    )
    density = cv2.resize(
        density,
        (target_shape[1], target_shape[0]),
        interpolation=cv2.INTER_AREA,
    )
    density = np.roll(density, shift=(shift_xy[1], shift_xy[0]), axis=(0, 1))
    low, high = np.quantile(density, (0.12, 0.88))
    normalized = np.clip((density - low) / max(float(high - low), 1e-6), 0.0, 1.0)
    return normalized.astype(np.float32)


def poisson_centers(
    permission: np.ndarray,
    density: np.ndarray,
    *,
    count: int,
    minimum_distance: float,
    seed: int,
) -> list[tuple[int, int]]:
    center_permission = k3.erode(permission, 13)
    ys, xs = np.nonzero(center_permission)
    if len(xs) == 0:
        raise RuntimeError("empty center permission")
    rng = np.random.default_rng(seed)
    points: list[tuple[int, int]] = []
    minimum_squared = minimum_distance * minimum_distance
    attempts = 0
    maximum_attempts = 500_000
    while len(points) < count and attempts < maximum_attempts:
        attempts += 1
        index = int(rng.integers(0, len(xs)))
        x, y = int(xs[index]), int(ys[index])
        # A small non-zero floor avoids a hard synthetic density boundary,
        # while a squared donor-density response preserves broad real gaps.
        acceptance = 0.025 + 0.975 * float(density[y, x]) ** 2
        if float(rng.random()) > acceptance:
            continue
        if any((x - px) ** 2 + (y - py) ** 2 < minimum_squared for px, py in points):
            continue
        points.append((x, y))
    if len(points) != count:
        raise RuntimeError(
            f"Poisson placement stopped at {len(points)}/{count} after {attempts} attempts"
        )
    return points


def rotated_fragment(
    fragment: Fragment, rotation_degrees: float
) -> tuple[np.ndarray, np.ndarray]:
    height, width = fragment.matte.shape
    diagonal = int(math.ceil(math.hypot(width, height))) + 4
    source_center = ((width - 1) / 2.0, (height - 1) / 2.0)
    target_center = ((diagonal - 1) / 2.0, (diagonal - 1) / 2.0)
    matrix = cv2.getRotationMatrix2D(source_center, rotation_degrees, 1.0)
    matrix[0, 2] += target_center[0] - source_center[0]
    matrix[1, 2] += target_center[1] - source_center[1]
    residual = cv2.warpAffine(
        fragment.residual,
        matrix,
        (diagonal, diagonal),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    matte = cv2.warpAffine(
        fragment.matte,
        matrix,
        (diagonal, diagonal),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    active = matte > 0
    ys, xs = np.nonzero(active)
    if len(xs) == 0:
        raise RuntimeError("rotation erased a source fragment")
    left, right = int(xs.min()), int(xs.max()) + 1
    top, bottom = int(ys.min()), int(ys.max()) + 1
    return residual[top:bottom, left:right], matte[top:bottom, left:right]


def assign_fragments_and_rotations(
    centers: list[tuple[int, int]],
    pools: dict[str, list[Fragment]],
    *,
    v8_fraction: float,
    seed: int,
) -> list[tuple[tuple[int, int], Fragment, float, float]]:
    rng = np.random.default_rng(seed)
    v8_count = round(len(centers) * v8_fraction)
    source_schedule = ["imagegen-v8"] * v8_count + ["v18-highland"] * (
        len(centers) - v8_count
    )
    rng.shuffle(source_schedule)
    source_indices = {
        source: iter(rng.permutation(len(pool)).tolist())
        for source, pool in pools.items()
    }
    base_bins = np.tile(
        np.arange(ORIENTATION_BINS),
        int(math.ceil(len(centers) / ORIENTATION_BINS)),
    )[: len(centers)]
    rng.shuffle(base_bins)
    placed: list[tuple[tuple[int, int], Fragment, float, float]] = []
    for index, (center, source) in enumerate(zip(centers, source_schedule)):
        fragment = pools[source][next(source_indices[source])]
        start_bin = int(base_bins[index])
        chosen: tuple[float, float] | None = None
        for offset in range(ORIENTATION_BINS):
            orientation_bin = (start_bin + 5 * offset) % ORIENTATION_BINS
            target_orientation = (
                (orientation_bin + 0.5) * 180.0 / ORIENTATION_BINS
                + float(rng.uniform(-4.5, 4.5))
            ) % 180.0
            conflict = False
            for other_center, _, _, other_orientation in placed:
                if math.hypot(
                    center[0] - other_center[0], center[1] - other_center[1]
                ) <= LOCAL_ORIENTATION_RADIUS_PX and angular_delta(
                    target_orientation, other_orientation
                ) <= LOCAL_PARALLEL_DELTA_DEGREES:
                    conflict = True
                    break
            if not conflict:
                rotation = (
                    target_orientation - fragment.principal_angle_degrees
                ) % 180.0
                chosen = rotation, target_orientation
                break
        if chosen is None:
            raise RuntimeError("cannot satisfy local orientation separation")
        placed.append((center, fragment, chosen[0], chosen[1]))
    return placed


def placement_contract(
    placed: list[tuple[tuple[int, int], Fragment, float, float]],
) -> dict[str, Any]:
    pairs: list[dict[str, Any]] = []
    for first in range(len(placed)):
        center_a, _, _, angle_a = placed[first]
        for second in range(first + 1, len(placed)):
            center_b, _, _, angle_b = placed[second]
            distance = math.hypot(
                center_a[0] - center_b[0], center_a[1] - center_b[1]
            )
            delta = angular_delta(angle_a, angle_b)
            if (
                distance <= LOCAL_ORIENTATION_RADIUS_PX
                and delta <= LOCAL_PARALLEL_DELTA_DEGREES
            ):
                pairs.append(
                    {
                        "indices": [first, second],
                        "distance_px": round(distance, 6),
                        "angle_delta_degrees": round(delta, 6),
                    }
                )
    orientations = np.asarray([item[3] for item in placed], np.float64)
    radians = np.deg2rad(orientations * 2.0)
    global_coherence = abs(np.mean(np.exp(1j * radians))) if len(radians) else 1.0
    histogram, _ = np.histogram(orientations, bins=ORIENTATION_BINS, range=(0, 180))
    return {
        "placed_fragments": len(placed),
        "orientation_bins": ORIENTATION_BINS,
        "orientation_histogram": histogram.astype(int).tolist(),
        "global_axial_orientation_coherence": round(float(global_coherence), 9),
        "local_neighbor_radius_px": LOCAL_ORIENTATION_RADIUS_PX,
        "local_parallel_delta_degrees": LOCAL_PARALLEL_DELTA_DEGREES,
        "local_parallel_pair_count": len(pairs),
        "local_parallel_triple_count": 0 if not pairs else None,
        "examples": pairs[:8],
        "passed": bool(len(pairs) == 0 and global_coherence <= 0.16),
    }


def compose_plate(
    baseline_crop: np.ndarray,
    permission_crop: np.ndarray,
    placed: list[tuple[tuple[int, int], Fragment, float, float]],
    *,
    mark_gain: float,
    median5_fraction: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    lab = cv2.cvtColor(baseline_crop, cv2.COLOR_RGB2LAB)
    original_l = lab[..., 0]
    # A bounded mix of two fixed source-only median operators retains enough
    # v18 macro contrast for downsample readability while remaining below the
    # unchanged weave-activity threshold.  Neither operator draws geometry.
    median5 = cv2.medianBlur(original_l, 5).astype(np.float32)
    median7 = cv2.medianBlur(original_l, 7).astype(np.float32)
    quiet_l = (1.0 - median5_fraction) * median7 + median5_fraction * median5
    source_counts = {"imagegen-v8": 0, "v18-highland": 0}
    used_hashes: list[str] = []
    changed_mark_pixels = np.zeros(permission_crop.shape, bool)
    for center, fragment, rotation, _ in placed:
        residual, matte = rotated_fragment(fragment, rotation)
        height, width = matte.shape
        left = center[0] - width // 2
        top = center[1] - height // 2
        right, bottom = left + width, top + height
        if left < 0 or top < 0 or right > quiet_l.shape[1] or bottom > quiet_l.shape[0]:
            raise RuntimeError("rotated fragment left target crop")
        active = matte > 0
        local_permission = permission_crop[top:bottom, left:right]
        if np.any(active & ~local_permission):
            raise RuntimeError("rotated fragment left highland permission")
        local = quiet_l[top:bottom, left:right]
        local[active] += mark_gain * residual[active].astype(np.float32)
        changed_mark_pixels[top:bottom, left:right] |= active
        source_counts[fragment.source] += 1
        used_hashes.append(fragment.sha256)
    local_lab = lab.copy()
    local_lab[..., 0] = np.clip(np.rint(quiet_l), 0, 255).astype(np.uint8)
    return cv2.cvtColor(local_lab, cv2.COLOR_LAB2RGB), {
        "quiet_substrate": "bounded v18 Lab-L median5/median7 mix; v18 a/b unchanged",
        "median5_fraction": median5_fraction,
        "median7_fraction": 1.0 - median5_fraction,
        "synthetic_geometry_drawn": False,
        "source_component_shapes_preserved": True,
        "rotation_resampling": "OpenCV INTER_NEAREST; no interpolation-created pigment",
        "mark_gain": mark_gain,
        "mark_pixels_before_boundary_composite": int(changed_mark_pixels.sum()),
        "source_counts": source_counts,
        "used_fragment_sha256": used_hashes,
        "unique_fragment_sha256": len(set(used_hashes)),
    }


def main() -> None:
    for path, digest in EXPECTED.items():
        if not path.is_file() or sha256(path) != digest:
            raise RuntimeError(f"frozen input missing or hash-mismatched: {path}")
    persistent = (k3.RAW, k3.FINAL, k3.RECEIPT, k3.AUDIT)
    if any(path.exists() for path in persistent):
        raise RuntimeError("persistent K3 output unexpectedly exists")
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty TEMP exploration: {OUT}")

    baseline = np.asarray(Image.open(V18).convert("RGB"), np.uint8)
    donor_v8 = np.asarray(Image.open(V8).convert("RGB"), np.uint8)
    masks = k3.derive_masks()
    left, top, right, bottom = TARGET_BOX
    baseline_crop = baseline[top:bottom, left:right]
    permission_crop = masks["highland_edit"][top:bottom, left:right]
    v18_l = cv2.cvtColor(baseline_crop, cv2.COLOR_RGB2LAB)[..., 0]
    v8_l = cv2.cvtColor(donor_v8, cv2.COLOR_RGB2LAB)[..., 0]

    v18_fragments, v18_selected, v18_extraction = extract_fragments(
        v18_l,
        permission_crop,
        source_name="v18-highland",
        dark_threshold=12,
    )
    v8_fragments, v8_selected, v8_extraction = extract_fragments(
        v8_l,
        np.ones(v8_l.shape, bool),
        source_name="imagegen-v8",
        dark_threshold=9,
    )
    pools = {"v18-highland": v18_fragments, "imagegen-v8": v8_fragments}

    recipes = (
        {
            "name": "scattered-070-r36-g095-m058",
            "count": 70,
            "minimum_distance": 36.0,
            "mark_gain": 0.95,
            "median5_fraction": 0.58,
            "v8_fraction": 0.42,
            "seed": 1901,
            "density_shift_xy": [0, 0],
        },
        {
            "name": "scattered-080-r34-g095-m062",
            "count": 80,
            "minimum_distance": 34.0,
            "mark_gain": 0.95,
            "median5_fraction": 0.62,
            "v8_fraction": 0.42,
            "seed": 1907,
            "density_shift_xy": [79, 31],
        },
        {
            "name": "scattered-088-r33-g092-m066",
            "count": 88,
            "minimum_distance": 33.0,
            "mark_gain": 0.92,
            "median5_fraction": 0.66,
            "v8_fraction": 0.42,
            "seed": 1913,
            "density_shift_xy": [151, 73],
        },
        {
            "name": "scattered-096-r32-g090-m070",
            "count": 96,
            "minimum_distance": 32.0,
            "mark_gain": 0.90,
            "median5_fraction": 0.70,
            "v8_fraction": 0.42,
            "seed": 1931,
            "density_shift_xy": [233, 109],
        },
    )
    if len(recipes) > CANDIDATE_LIMIT:
        raise RuntimeError("candidate limit exceeded")

    OUT.mkdir(parents=True, exist_ok=True)
    baseline_weave = harness.weave(baseline, masks["highland_edit"])
    baseline_activity = float(baseline_weave["activity_fraction"])
    alpha = k3.boundary_locked_alpha(
        masks["highland_edit"], full_by_px=7.0, locked_boundary_px=2.0
    )
    records: dict[str, Any] = {}
    for recipe in recipes:
        density = source_density_field(
            v8_selected,
            permission_crop.shape,
            shift_xy=tuple(recipe["density_shift_xy"]),
        )
        centers = poisson_centers(
            permission_crop,
            density,
            count=int(recipe["count"]),
            minimum_distance=float(recipe["minimum_distance"]),
            seed=int(recipe["seed"]),
        )
        placed = assign_fragments_and_rotations(
            centers,
            pools,
            v8_fraction=float(recipe["v8_fraction"]),
            seed=int(recipe["seed"]) + 100_000,
        )
        placement = placement_contract(placed)
        if not placement["passed"]:
            raise RuntimeError(f"placement contract failed: {recipe['name']}")
        local_plate, composition = compose_plate(
            baseline_crop,
            permission_crop,
            placed,
            mark_gain=float(recipe["mark_gain"]),
            median5_fraction=float(recipe["median5_fraction"]),
        )
        donor_canvas = baseline.copy()
        donor_canvas[top:bottom, left:right] = local_plate
        candidate = k3.composite_with_alpha(baseline, donor_canvas, alpha)
        record = harness.evaluate(
            str(recipe["name"]), candidate, baseline, masks, baseline_activity
        )
        record["recipe"] = recipe
        record["placement_contract"] = placement
        record["composition"] = composition
        records[str(recipe["name"])] = record

    aggregate = {
        "schema_version": "1.0.0",
        "status": "TEMP-only scattered source-mark exploration; no acceptance authority",
        "temporary_review_only": True,
        "decision_authority": False,
        "persistent_outputs_emitted": False,
        "thresholds_changed": False,
        "candidate_limit": CANDIDATE_LIMIT,
        "candidate_count": len(records),
        "inputs": {
            "v18": {"path": relative(V18), "sha256": EXPECTED[V18]},
            "imagegen_v8": {"path": relative(V8), "sha256": EXPECTED[V8]},
            "imagegen_v8_exact_prompt": {
                "path": relative(P8),
                "sha256": EXPECTED[P8],
            },
            "full_gate_harness": {
                "path": relative(HARNESS),
                "sha256": sha256(HARNESS),
            },
        },
        "operation": {
            "semantic_change": "highland permitted interior material only",
            "target_crop_xyxy": list(TARGET_BOX),
            "source_fragment_extraction": [v18_extraction, v8_extraction],
            "v18_selected_source_pixels": int(v18_selected.sum()),
            "imagegen_v8_selected_source_pixels": int(v8_selected.sum()),
            "placement": (
                "deterministic inhomogeneous Poisson rejection sampling; broad density "
                "field derived from blurred locations of accepted ImageGen v8 fragments"
            ),
            "random_generator": "NumPy PCG64 with per-recipe fixed integer seed",
            "component_reuse_within_candidate": False,
            "synthetic_geometry_drawn": False,
            "source_component_pixel_shapes_used": True,
            "boundary_alpha": {"locked_boundary_px": 2.0, "full_by_px": 7.0},
        },
        "v18_weave": baseline_weave,
        "records": records,
    }
    report_path = OUT / "scattered-marks-search.json"
    report_path.write_text(json.dumps(aggregate, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "report": {"path": relative(report_path), "sha256": sha256(report_path)},
                "variants": {
                    name: {
                        "status": record["status"],
                        "failed_gates": record["failed_gates"],
                        "activity": record["weave_reduction"]["candidate"][
                            "activity_fraction"
                        ],
                        "orientation": record["weave_reduction"]["orientation"][
                            "global_gradient_orientation_coherence"
                        ],
                        "strict_highland": record["strict_content"]["highland"],
                        "palette": record["global_gates"]["palette"],
                        "downsample": record["global_gates"]["downsample"],
                        "placement_contract": record["placement_contract"],
                        "candidate": record["candidate"],
                        "contacts": record["contacts"],
                    }
                    for name, record in records.items()
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
