#!/usr/bin/env python3
"""Build two TEMP-only full-alpha K3 world-micrograin v5 candidates.

The locked full-context ImageGen broad-landform donor is recomposed from frozen
v18 with the production highland alpha contract (locked=2, full-by=5).  The
same D sigma-2.6/high-pass-0.12 plate and Lab-L contrast 0.65 used by v2 are
retained.  Sparse, isolated one-pixel dry-paper grain is then added only inside
the exact ``boundary_locked_alpha(...) == 1`` support.

Every point is validated through the actual RGB round-trip.  A coordinate is
accepted only when a paired dark/light requested amplitude produces decoded
absolute Lab-L deltas in [7, 9] for both pixels.  Counts are deterministically
calibrated against the real activity-mask delta.  At most two candidate rasters
are emitted and contacts are written only after every hard and custom gate.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts/map-production"
OUT = ROOT / "tmp/map-production/k3-semantic-cleanup-v19-world-micrograin-v5"
V18 = ROOT / (
    "world/map-production/style-assets/k3-v18-reconstruction-base.png"
)
DONOR = ROOT / (
    "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/"
    "highland-context-broad-landform-v19.png"
)
PROMPT = ROOT / (
    "world/map-production/prompts/"
    "style-candidate-k-v3-highland-broad-landform-v19.generation.txt"
)
OLD_V2_BASE = ROOT / (
    "tmp/map-production/"
    "k3-semantic-cleanup-v19-broad-landform-contrast-refinement/"
    "broad-landform-d-lcontrast-065/broad-landform-d-lcontrast-065.png"
)
OLD_V2_REPORT = ROOT / (
    "tmp/map-production/"
    "k3-semantic-cleanup-v19-broad-landform-contrast-refinement/"
    "broad-landform-contrast-search.json"
)
OLD_V4_REPORT = ROOT / (
    "tmp/map-production/k3-semantic-cleanup-v19-world-micrograin-v4/"
    "world-micrograin-v4-search.json"
)
OLD_ERODE7_REAUDIT = ROOT / (
    "tmp/map-production/"
    "k3-semantic-cleanup-v19-broad-landform-core-reaudit/"
    "broad-landform-core-reaudit.json"
)
BASE_PROBE = SCRIPTS / "probe_style_candidate_k3_highland_broad_landform.py"
BUILDER = SCRIPTS / "build_style_candidate_k3_semantic_cleanup.py"
AUDIT = SCRIPTS / "audit_style_candidate_k3_semantic_cleanup.py"
HARNESS = SCRIPTS / "build_style_candidate_k3_highland_phase_synthesis.py"

EXPECTED = {
    V18: "013320af2f3296200a7d0b179e3a495f1e7905462213a6c645d85669dec02882",
    DONOR: "67fdedc66e9c2b0a7d8b0f7af6c4e093838f0df3c1130bfde83d8ea4a84b116b",
    PROMPT: "64c8b133bb41e2eb08e5ea6cabc2541f7058c3d4088ce98904acddaae99cae83",
    OLD_V2_BASE: "20ee2a0f75a9a65213d2882347292ee76f4125a95adf217e4428d7bc9af1ff22",
    OLD_V2_REPORT: "87ecf4771a9db6c9d7f6b384656a92a8ef63ac0d86b82d9cbed9220db23d97de",
    OLD_V4_REPORT: "e52090c16e687299f205d1e3db719b9d31d99f9f78ba12355aff59565026d0bd",
    OLD_ERODE7_REAUDIT: "c45ff1ce40a04800632f5d538a16ee8377d06a6204222bafc9b569a4a73c0050",
    BUILDER: "740e7da9abd94fe0f161779facb71adc4ef7e03cff498f50034de1728270dec9",
    AUDIT: "d77f27d4be992600b100c2b070c2fbedb680801d2e8283e9bf7ea2dbedd48936",
}

CANDIDATE_LIMIT = 2
TARGET_ADDED_ACTIVE_FRACTIONS = (0.052, 0.055)
ALLOWED_ADDED_ACTIVE_RANGE = (0.050, 0.056)
TARGET_TOLERANCE = 0.004
MINIMUM_CHEBYSHEV_DISTANCE_PX = 4
POINT_MARGIN_INSIDE_SUPPORT_PX = 2
BASE_ACTIVITY_CLEARANCE_PX = 2
ALLOWED_DECODED_AMPLITUDE_RANGE_LAB_L = (7, 9)
AMPLITUDE_TRIALS_LAB_L = (8, 7, 9)
REGULAR_GRID_MAXIMUM_MODULO_BIN_SHARE = 0.40
WORLD_SEED_NAMESPACE = "EA-WORLD-1"
WORLD_SEED_PURPOSE = "K3-HIGHLAND-FULLALPHA-DRY-PAPER-MICROGRAIN-v5"
WORLD_SEED_MATERIAL = f"{WORLD_SEED_NAMESPACE}\0{WORLD_SEED_PURPOSE}"
WORLD_SEED_SHA256 = hashlib.sha256(WORLD_SEED_MATERIAL.encode("utf-8")).hexdigest()
WORLD_SEED_UINT64 = int(WORLD_SEED_SHA256[:16], 16)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base_probe = load_module("world_micrograin_v5_broad_authority", BASE_PROBE)
harness = load_module("world_micrograin_v5_full_gate_harness", HARNESS)
harness.OUT = OUT
k3 = harness.k3
audit = harness.audit


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def locked(path: Path, digest: str) -> dict[str, str]:
    if not path.is_file():
        raise RuntimeError(f"frozen input missing: {path}")
    actual = sha256(path)
    if actual != digest:
        raise RuntimeError(f"frozen input hash mismatch: {path}: {actual}")
    return {"path": relative(path), "sha256": actual}


def broad_landform_plate(
    donor: np.ndarray,
    baseline: np.ndarray,
    masks: dict[str, Any],
) -> tuple[np.ndarray, dict[str, Any]]:
    registration_mask = k3.erode(masks["highland_edit"], 28)
    registered_lab, registration = base_probe.register_lab_median(
        donor, baseline, registration_mask
    )
    d_rgb, filtering = base_probe.variant_plate(
        registered_lab,
        {
            "name": "broad-landform-d-s260-g012",
            "highpass_sigma_px": 2.6,
            "highpass_gain": 0.12,
        },
    )
    lab = cv2.cvtColor(d_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    target_median_l = float(registration["target_v18_median_lab"][0])
    lab[..., 0] = target_median_l + 0.65 * (lab[..., 0] - target_median_l)
    plate = cv2.cvtColor(
        np.clip(np.rint(lab), 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB
    )
    return plate, {
        "registration": registration,
        "d_filtering": filtering,
        "lab_l_contrast_factor": 0.65,
        "lab_l_contrast_center": target_median_l,
        "spatial_transform": "none; native full-context coordinates",
    }


def composite_highland(
    baseline: np.ndarray,
    plate: np.ndarray,
    permission: np.ndarray,
    *,
    full_by_px: float,
) -> tuple[np.ndarray, np.ndarray]:
    alpha = k3.boundary_locked_alpha(
        permission,
        full_by_px=full_by_px,
        locked_boundary_px=k3.HIGHLAND_ALPHA_LOCKED_BOUNDARY_PX,
    )
    rendered = k3.composite_with_alpha(baseline, plate, alpha)
    candidate = baseline.copy()
    candidate[permission] = rendered[permission]
    return candidate, alpha


def pack_world_coordinates(
    eligible: np.ndarray,
    requested_count: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, dict[str, Any]]:
    ys, xs = np.nonzero(eligible)
    order = rng.permutation(len(xs))
    blocked = np.zeros(eligible.shape, bool)
    radius = MINIMUM_CHEBYSHEV_DISTANCE_PX - 1
    points: list[tuple[int, int]] = []
    for index in order:
        x = int(xs[index])
        y = int(ys[index])
        if blocked[y, x]:
            continue
        points.append((x, y))
        blocked[
            max(0, y - radius) : min(eligible.shape[0], y + radius + 1),
            max(0, x - radius) : min(eligible.shape[1], x + radius + 1),
        ] = True
        if len(points) == requested_count:
            break
    if len(points) != requested_count:
        raise RuntimeError(f"point packing stopped at {len(points)}/{requested_count}")
    return np.asarray(points, np.int32), {
        "eligible_pixels": int(eligible.sum()),
        "requested_coordinates": requested_count,
        "packed_coordinates": len(points),
        "selection": "seeded world-coordinate permutation plus Chebyshev rejection",
    }


def encode_delta(
    base_rgb: np.ndarray,
    requested_delta: int,
) -> tuple[np.ndarray, int] | None:
    source = base_rgb.reshape((1, 1, 3))
    source_lab = cv2.cvtColor(source, cv2.COLOR_RGB2LAB)
    target_lab = source_lab.copy()
    target_lab[0, 0, 0] = np.uint8(
        np.clip(int(source_lab[0, 0, 0]) + requested_delta, 0, 255)
    )
    encoded = cv2.cvtColor(target_lab, cv2.COLOR_LAB2RGB)
    decoded = cv2.cvtColor(encoded, cv2.COLOR_RGB2LAB)
    actual_delta = int(decoded[0, 0, 0]) - int(source_lab[0, 0, 0])
    if (
        np.sign(actual_delta) != np.sign(requested_delta)
        or not (
            ALLOWED_DECODED_AMPLITUDE_RANGE_LAB_L[0]
            <= abs(actual_delta)
            <= ALLOWED_DECODED_AMPLITUDE_RANGE_LAB_L[1]
        )
        or np.array_equal(encoded[0, 0], base_rgb)
    ):
        return None
    return encoded[0, 0].copy(), actual_delta


def validate_point_pairs(
    base: np.ndarray,
    raw_points: np.ndarray,
    rng: np.random.Generator,
    required_count: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    accepted_points: list[tuple[int, int]] = []
    accepted_rgb: list[np.ndarray] = []
    requested: list[int] = []
    actual: list[int] = []
    attempted_pairs = 0
    rejected_pairs = 0
    amplitude_pair_counts = {str(value): 0 for value in AMPLITUDE_TRIALS_LAB_L}
    for pair_index in range(0, len(raw_points) - 1, 2):
        attempted_pairs += 1
        pair = raw_points[pair_index : pair_index + 2]
        first_sign = 1 if int(rng.integers(0, 2)) else -1
        trial_order = rng.permutation(AMPLITUDE_TRIALS_LAB_L)
        accepted_pair: tuple[np.ndarray, int, np.ndarray, int, int] | None = None
        first_x, first_y = (int(value) for value in pair[0])
        second_x, second_y = (int(value) for value in pair[1])
        for amplitude_value in trial_order:
            amplitude = int(amplitude_value)
            first = encode_delta(base[first_y, first_x], first_sign * amplitude)
            second = encode_delta(base[second_y, second_x], -first_sign * amplitude)
            if first is not None and second is not None:
                accepted_pair = (
                    first[0], first[1], second[0], second[1], amplitude
                )
                break
        if accepted_pair is None:
            rejected_pairs += 1
            continue
        first_rgb, first_actual, second_rgb, second_actual, amplitude = accepted_pair
        accepted_points.extend(((first_x, first_y), (second_x, second_y)))
        accepted_rgb.extend((first_rgb, second_rgb))
        requested.extend((first_sign * amplitude, -first_sign * amplitude))
        actual.extend((first_actual, second_actual))
        amplitude_pair_counts[str(amplitude)] += 1
        if len(accepted_points) >= required_count:
            break
    if len(accepted_points) < required_count:
        raise RuntimeError(
            f"validated point pairs stopped at {len(accepted_points)}/{required_count}"
        )
    return (
        np.asarray(accepted_points[:required_count], np.int32),
        np.asarray(accepted_rgb[:required_count], np.uint8),
        np.column_stack(
            (
                np.asarray(requested[:required_count], np.int16),
                np.asarray(actual[:required_count], np.int16),
            )
        ),
        {
            "per_point_rgb_roundtrip_validation": True,
            "attempted_pairs": attempted_pairs,
            "rejected_pairs": rejected_pairs,
            "accepted_pairs": required_count // 2,
            "amplitude_pair_counts": amplitude_pair_counts,
            "allowed_decoded_absolute_lab_l": list(
                ALLOWED_DECODED_AMPLITUDE_RANGE_LAB_L
            ),
            "pair_contract": "same requested amplitude, opposite sign, both decoded in range or whole pair rejected",
        },
    )


def render_prefix(
    base: np.ndarray,
    points: np.ndarray,
    encoded_rgb: np.ndarray,
    count: int,
) -> np.ndarray:
    candidate = base.copy()
    selected = points[:count]
    candidate[selected[:, 1], selected[:, 0]] = encoded_rgb[:count]
    return candidate


def added_active_fraction(
    candidate: np.ndarray,
    base_active: np.ndarray,
    support: np.ndarray,
) -> float:
    active = audit.activity_mask(candidate, support)
    return float(((active & ~base_active & support)[support]).mean())


def calibrate_prefix(
    base: np.ndarray,
    points: np.ndarray,
    encoded_rgb: np.ndarray,
    base_active: np.ndarray,
    support: np.ndarray,
    target: float,
) -> tuple[int, float, list[dict[str, Any]]]:
    cache: dict[int, float] = {}

    def measure(count: int) -> float:
        count = max(2, min(len(points) - len(points) % 2, count - count % 2))
        if count not in cache:
            cache[count] = added_active_fraction(
                render_prefix(base, points, encoded_rgb, count),
                base_active,
                support,
            )
        return cache[count]

    low = 2
    high = len(points) - len(points) % 2
    while low <= high:
        middle = ((low + high) // 4) * 2
        value = measure(middle)
        if value < target:
            low = middle + 2
        else:
            high = middle - 2
    candidates = sorted(set(cache) | {
        max(2, min(len(points) - len(points) % 2, value - value % 2))
        for value in range(max(2, high - 24), min(len(points), low + 24) + 1, 2)
    })
    for count in candidates:
        measure(count)
    best_count = min(cache, key=lambda count: (abs(cache[count] - target), count))
    trials = [
        {"point_count": count, "actual_added_active_fraction": round(value, 9)}
        for count, value in sorted(cache.items())
    ]
    return best_count, cache[best_count], trials


def chebyshev_violation_count(points: np.ndarray) -> int:
    occupied = {(int(x), int(y)) for x, y in points}
    violations: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    radius = MINIMUM_CHEBYSHEV_DISTANCE_PX - 1
    for x, y in occupied:
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx == 0 and dy == 0:
                    continue
                other = (x + dx, y + dy)
                if other in occupied:
                    violations.add(tuple(sorted(((x, y), other))))
    return len(violations)


def regular_grid_proxy(points: np.ndarray) -> dict[str, Any]:
    xs = points[:, 0]
    ys = points[:, 1]
    periods: list[dict[str, Any]] = []
    maximum = 0.0
    for period in (4, 5, 7, 8, 11, 13, 16):
        x_counts = np.bincount(xs % period, minlength=period)
        y_counts = np.bincount(ys % period, minlength=period)
        share = max(float(x_counts.max()), float(y_counts.max())) / len(points)
        maximum = max(maximum, share)
        periods.append(
            {
                "period_px": period,
                "maximum_x_or_y_modulo_bin_share": round(share, 9),
            }
        )
    return {
        "periods": periods,
        "maximum_modulo_bin_share": round(maximum, 9),
        "maximum_allowed": REGULAR_GRID_MAXIMUM_MODULO_BIN_SHARE,
        "passed": maximum <= REGULAR_GRID_MAXIMUM_MODULO_BIN_SHARE,
    }


def micrograin_contract(
    candidate: np.ndarray,
    base: np.ndarray,
    support: np.ndarray,
    base_active: np.ndarray,
    points: np.ndarray,
    delta_pairs: np.ndarray,
    target: float,
    calibration: dict[str, Any],
) -> dict[str, Any]:
    changed = np.any(candidate != base, axis=2)
    requested = delta_pairs[:, 0]
    actual = delta_pairs[:, 1]
    active = audit.activity_mask(candidate, support)
    added_fraction = float(((active & ~base_active & support)[support]).mean())
    components, _, stats, _ = cv2.connectedComponentsWithStats(
        changed.astype(np.uint8), 8
    )
    areas = stats[1:, cv2.CC_STAT_AREA].astype(int)
    lines = cv2.HoughLinesP(
        changed.astype(np.uint8) * 255,
        1,
        np.pi / 180,
        threshold=3,
        minLineLength=3,
        maxLineGap=1,
    )
    distance_violations = chebyshev_violation_count(points)
    grid = regular_grid_proxy(points)
    gates = {
        "exactly_one_changed_pixel_per_validated_point": bool(
            int(changed.sum()) == len(points)
            and np.all(changed[points[:, 1], points[:, 0]])
        ),
        "exact_full_alpha_support_only": bool(
            np.count_nonzero(changed & ~support) == 0
        ),
        "decoded_absolute_lab_l_7_to_9": bool(
            int(np.abs(actual).min()) >= 7 and int(np.abs(actual).max()) <= 9
        ),
        "dark_light_exact_balance": bool(
            np.count_nonzero(requested < 0) == np.count_nonzero(requested > 0)
            and np.count_nonzero(actual < 0) == np.count_nonzero(actual > 0)
            and int(requested.sum()) == 0
        ),
        "chebyshev_distance_at_least_4": distance_violations == 0,
        "isolated_one_pixel_components": bool(
            components - 1 == len(points)
            and len(areas) == len(points)
            and np.all(areas == 1)
        ),
        "no_hough_line": lines is None,
        "no_regular_grid_proxy": grid["passed"],
        "actual_added_active_fraction_0_050_to_0_056": bool(
            ALLOWED_ADDED_ACTIVE_RANGE[0]
            <= added_fraction
            <= ALLOWED_ADDED_ACTIVE_RANGE[1]
        ),
        "recorded_target_delta_at_most_0_004": bool(
            abs(added_fraction - target) <= TARGET_TOLERANCE
        ),
    }
    return {
        "status": "hard-gated world-coordinate paper texture; not semantic geometry",
        "point_count": len(points),
        "changed_pixels": int(changed.sum()),
        "changed_pixels_outside_exact_full_alpha_support": int(
            np.count_nonzero(changed & ~support)
        ),
        "requested_lab_l": {
            "minimum_absolute_amplitude": int(np.abs(requested).min()),
            "maximum_absolute_amplitude": int(np.abs(requested).max()),
            "dark_points": int(np.count_nonzero(requested < 0)),
            "light_points": int(np.count_nonzero(requested > 0)),
            "signed_sum": int(requested.sum()),
        },
        "decoded_lab_l": {
            "minimum_absolute_amplitude": int(np.abs(actual).min()),
            "maximum_absolute_amplitude": int(np.abs(actual).max()),
            "dark_points": int(np.count_nonzero(actual < 0)),
            "light_points": int(np.count_nonzero(actual > 0)),
            "signed_sum": int(actual.sum()),
        },
        "minimum_chebyshev_distance_px": MINIMUM_CHEBYSHEV_DISTANCE_PX,
        "chebyshev_distance_violation_pairs": distance_violations,
        "connected_components": {
            "count": components - 1,
            "minimum_area_px": int(areas.min()),
            "maximum_area_px": int(areas.max()),
        },
        "hough_line_count": 0 if lines is None else len(lines),
        "regular_grid_proxy": grid,
        "active_dilation": {
            "measurement_support": "production boundary_locked_alpha(...) == 1",
            "base_active_fraction": round(float(base_active[support].mean()), 9),
            "candidate_active_fraction": round(float(active[support].mean()), 9),
            "target_added_fraction": target,
            "actual_added_fraction": round(added_fraction, 9),
            "allowed_range": list(ALLOWED_ADDED_ACTIVE_RANGE),
            "target_tolerance": TARGET_TOLERANCE,
            "calibration": calibration,
        },
        "gates": gates,
        "passed": all(gates.values()),
    }


def rewrite_candidate_report(record: dict[str, Any]) -> None:
    report_path = ROOT / record["report"]["path"]
    payload = dict(record)
    payload.pop("report", None)
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    record["report"] = {
        "path": relative(report_path),
        "sha256": sha256(report_path),
    }


def apply_hard_gates(
    record: dict[str, Any],
    identity: dict[str, Any],
    *,
    custom_contract: dict[str, Any] | None,
) -> bool:
    highland = record["semantic_diagnostic"]["highland"]
    record["road_guard_protected_outside_identity"] = identity
    record["automated_gates"]["exact_k2_source_lock"] = bool(
        sha256(k3.SOURCE) == k3.EXPECTED_SOURCE
    )
    record["automated_gates"][
        "road_guard_protected_outside_byte_exact"
    ] = identity["passed"]
    record["automated_gates"]["highland_semantic_cleanup_proxies"] = bool(
        highland["passed"]
    )
    if custom_contract is not None:
        record["automated_gates"]["world_micrograin_contract"] = bool(
            custom_contract["passed"]
        )
    record["failed_gates"] = [
        gate for gate, passed in record["automated_gates"].items() if not passed
    ]
    passed = not record["failed_gates"]
    record["status"] = (
        "passed-automated-gates-pending-root-vision"
        if passed
        else "failed-automated-gates"
    )
    record["vision_handoff"]["required"] = passed
    record["vision_handoff"]["contacts_emitted_only_after_all_hard_gates"] = True
    return passed


def main() -> None:
    if len(TARGET_ADDED_ACTIVE_FRACTIONS) > CANDIDATE_LIMIT:
        raise RuntimeError("candidate limit exceeded")
    frozen = {relative(path): locked(path, digest) for path, digest in EXPECTED.items()}
    persistent = (k3.RAW, k3.FINAL, k3.RECEIPT, k3.AUDIT)
    if any(path.exists() for path in persistent):
        raise RuntimeError("persistent K3 output unexpectedly exists")
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty TEMP exploration: {OUT}")

    spec_bytes_before = k3.SPEC.read_bytes()
    spec_sha_before = sha256(k3.SPEC)
    baseline = np.asarray(Image.open(V18).convert("RGB"), np.uint8)
    donor = np.asarray(Image.open(DONOR).convert("RGB"), np.uint8)
    old_v2 = np.asarray(Image.open(OLD_V2_BASE).convert("RGB"), np.uint8)
    k3.validate_source()
    masks = k3.derive_masks()
    permission = masks["highland_edit"]
    plate, broad_method = broad_landform_plate(donor, baseline, masks)
    old_v2_reconstructed, alpha7 = composite_highland(
        baseline, plate, permission, full_by_px=7.0
    )
    if not np.array_equal(old_v2_reconstructed, old_v2):
        raise RuntimeError("broad-landform formula did not reconstruct frozen v2")
    broad_base, production_alpha = composite_highland(
        baseline,
        plate,
        permission,
        full_by_px=k3.HIGHLAND_ALPHA_FULL_BY_PX,
    )
    support = audit.highland_fully_editable_support(masks)
    if not np.array_equal(support, production_alpha == np.float32(1.0)):
        raise RuntimeError("audit support differs from recomposed production alpha")
    alpha_change_support = permission & (production_alpha != alpha7)
    difference_v2 = np.any(broad_base != old_v2, axis=2)
    if np.count_nonzero(difference_v2 & ~alpha_change_support):
        raise RuntimeError("full-by-5 recompose changed pixels outside alpha delta")

    baseline_weave = harness.weave(baseline, permission)
    baseline_activity = float(baseline_weave["activity_fraction"])
    original_save_contacts = harness.save_contacts
    try:
        harness.save_contacts = lambda candidate, directory: {}
        base_record = harness.evaluate(
            "fullalpha5-broad-landform-base",
            broad_base,
            baseline,
            masks,
            baseline_activity,
        )
        base_identity = base_probe.guard_identity(broad_base, baseline, masks)
        apply_hard_gates(base_record, base_identity, custom_contract=None)
        base_record["schema_version"] = "1.0.0"
        base_record["persistent_candidate_emitted"] = False
        base_record["lineage"] = {
            "frozen_v18": frozen[relative(V18)],
            "imagegen_control": frozen[relative(DONOR)],
            "exact_generation_prompt": frozen[relative(PROMPT)],
            "frozen_full_by_7_v2": frozen[relative(OLD_V2_BASE)],
        }
        base_record["method"] = {
            **broad_method,
            "alpha": {
                "function": "k3.boundary_locked_alpha",
                "locked_boundary_px": k3.HIGHLAND_ALPHA_LOCKED_BOUNDARY_PX,
                "full_by_px": k3.HIGHLAND_ALPHA_FULL_BY_PX,
                "full_support_method": "alpha == 1.0",
                "full_support_pixels": int(support.sum()),
            },
            "old_v2_full_by_7_pixel_exact_reconstruction": True,
            "differing_pixels_vs_old_v2": int(difference_v2.sum()),
            "differences_confined_to_alpha_contract_delta": True,
        }
        base_record["contacts"] = {}
        rewrite_candidate_report(base_record)

        base_active = audit.activity_mask(broad_base, support)
        eligible = k3.erode(support, POINT_MARGIN_INSIDE_SUPPORT_PX)
        eligible &= ~k3.dilate(base_active, BASE_ACTIVITY_CLEARANCE_PX)
        rng = np.random.default_rng(WORLD_SEED_UINT64)
        raw_points, packing = pack_world_coordinates(eligible, 5200, rng)
        points, encoded_rgb, delta_pairs, validation = validate_point_pairs(
            broad_base, raw_points, rng, 2600
        )

        calibration_results: list[tuple[float, int, float, list[dict[str, Any]]]] = []
        for target in TARGET_ADDED_ACTIVE_FRACTIONS:
            count, actual_fraction, trials = calibrate_prefix(
                broad_base,
                points,
                encoded_rgb,
                base_active,
                support,
                target,
            )
            calibration_results.append((target, count, actual_fraction, trials))
        if calibration_results[1][1] <= calibration_results[0][1]:
            raise RuntimeError("density calibration did not produce increasing prefixes")

        records: dict[str, Any] = {}
        for index, (target, count, calibrated_fraction, trials) in enumerate(
            calibration_results, 1
        ):
            name = f"world-micrograin-v5-{index}-f{int(target * 1000):03d}"
            candidate = render_prefix(broad_base, points, encoded_rgb, count)
            contract = micrograin_contract(
                candidate,
                broad_base,
                support,
                base_active,
                points[:count],
                delta_pairs[:count],
                target,
                {
                    "selected_point_count": count,
                    "selected_actual_added_fraction": round(calibrated_fraction, 9),
                    "trials": trials,
                },
            )
            identity = base_probe.guard_identity(candidate, baseline, masks)
            changed_base = np.any(candidate != broad_base, axis=2)
            exact_base_identity = {
                "differing_pixels_vs_fullalpha5_base": int(changed_base.sum()),
                "differing_pixels_outside_exact_full_alpha_support": int(
                    np.count_nonzero(changed_base & ~support)
                ),
                "outside_support_byte_exact": bool(
                    np.array_equal(candidate[~support], broad_base[~support])
                ),
            }
            record = harness.evaluate(
                name,
                candidate,
                baseline,
                masks,
                baseline_activity,
            )
            passed = apply_hard_gates(
                record, identity, custom_contract=contract
            )
            record["schema_version"] = "1.0.0"
            record["persistent_candidate_emitted"] = False
            record["lineage"] = {
                "frozen_v18": frozen[relative(V18)],
                "imagegen_control": frozen[relative(DONOR)],
                "exact_generation_prompt": frozen[relative(PROMPT)],
                "frozen_old_v4_report_hold_only": frozen[relative(OLD_V4_REPORT)],
                "frozen_erode7_reaudit_hold_only": frozen[
                    relative(OLD_ERODE7_REAUDIT)
                ],
                "fullalpha5_base": base_record["candidate"],
                "fullalpha5_base_report": base_record["report"],
            }
            record["method"] = {
                "seed": {
                    "namespace": WORLD_SEED_NAMESPACE,
                    "purpose": WORLD_SEED_PURPOSE,
                    "material_utf8_sha256": WORLD_SEED_SHA256,
                    "numpy_pcg64_seed_uint64": WORLD_SEED_UINT64,
                    "coordinate_system": "1536x1024 native map, origin top-left, x east, y south",
                    "semantic_geometry_added": False,
                },
                "packing": packing,
                "rgb_roundtrip_point_validation": validation,
                "prefix_point_count": count,
                "target_added_active_fraction": target,
                "measurement_support": base_record["method"]["alpha"],
            }
            record["world_micrograin_contract"] = contract
            record["base_spatial_identity"] = exact_base_identity
            record["vision_handoff"]["required_checks"] = [
                "broad 80-220px landforms remain readable at 25% and 50%",
                "isolated grain reads as dry paper rather than dot scatter at 200% and 400%",
                "no line, connected component, regular grid, or directional texture",
                "no highland panel seam and no production-alpha boundary change",
            ]
            record["contacts"] = (
                original_save_contacts(candidate, OUT / name / "contacts")
                if passed
                else {}
            )
            rewrite_candidate_report(record)
            records[name] = record
    finally:
        harness.save_contacts = original_save_contacts

    if k3.SPEC.read_bytes() != spec_bytes_before or sha256(k3.SPEC) != spec_sha_before:
        raise RuntimeError("persistent K3 specification changed during TEMP probe")
    if any(path.exists() for path in persistent):
        raise RuntimeError("TEMP probe emitted a persistent K3 output")

    aggregate = {
        "schema_version": "1.0.0",
        "status": "TEMP-only full-alpha broad-landform plus EA-WORLD-1 micrograin v5",
        "temporary_review_only": True,
        "decision_authority": False,
        "persistent_outputs_emitted": False,
        "thresholds_changed": False,
        "candidate_limit": CANDIDATE_LIMIT,
        "candidate_count": len(records),
        "inputs": {
            "frozen_v18": frozen[relative(V18)],
            "imagegen_control": frozen[relative(DONOR)],
            "exact_generation_prompt": frozen[relative(PROMPT)],
            "old_v2_full_by_7": frozen[relative(OLD_V2_BASE)],
            "old_v2_report": frozen[relative(OLD_V2_REPORT)],
            "old_v4_report_hold_only": frozen[relative(OLD_V4_REPORT)],
            "old_erode7_reaudit_hold_only": frozen[relative(OLD_ERODE7_REAUDIT)],
            "production_builder": frozen[relative(BUILDER)],
            "production_audit": frozen[relative(AUDIT)],
            "full_gate_harness": {
                "path": relative(HARNESS),
                "sha256": sha256(HARNESS),
            },
        },
        "fullalpha5_broad_landform_base": base_record,
        "operation": {
            "broad_landform": broad_method,
            "production_alpha": base_record["method"]["alpha"],
            "seed": records[next(iter(records))]["method"]["seed"],
            "target_added_active_fractions": list(TARGET_ADDED_ACTIVE_FRACTIONS),
            "allowed_added_active_range": list(ALLOWED_ADDED_ACTIVE_RANGE),
            "candidate_point_counts": [item[1] for item in calibration_results],
            "candidate_actual_added_active_fractions": [
                round(item[2], 9) for item in calibration_results
            ],
        },
        "v18_weave": baseline_weave,
        "records": records,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    report_path = OUT / "world-micrograin-v5-search.json"
    report_path.write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report": {
                    "path": relative(report_path),
                    "sha256": sha256(report_path),
                },
                "fullalpha5_base": {
                    "status": base_record["status"],
                    "failed_gates": base_record["failed_gates"],
                    "candidate": base_record["candidate"],
                    "highland_semantic": base_record["semantic_diagnostic"][
                        "highland"
                    ],
                },
                "variants": {
                    name: {
                        "status": record["status"],
                        "failed_gates": record["failed_gates"],
                        "activity": record["weave_reduction"]["candidate"][
                            "activity_fraction"
                        ],
                        "activity_ratio": record["weave_reduction"][
                            "candidate_to_v18_activity_ratio"
                        ],
                        "highland_semantic": record["semantic_diagnostic"][
                            "highland"
                        ],
                        "micrograin": record["world_micrograin_contract"],
                        "strict_highland": record["strict_content"]["highland"],
                        "semantic_repetition": record["global_gates"][
                            "semantic_repetition"
                        ],
                        "palette": record["global_gates"]["palette"],
                        "downsample": record["global_gates"]["downsample"],
                        "candidate": record["candidate"],
                        "contacts": record["contacts"],
                    }
                    for name, record in records.items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
