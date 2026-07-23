#!/usr/bin/env python3
"""Build four TEMP-only K3 highland world-coordinate micrograin probes.

The frozen v2 Lab-L-0.65 broad-landform candidate is the complete visual base.
Only isolated one-pixel dry-paper grain is added inside the fully editable
``erode(highland_edit, 7)`` core.  Coordinates come from the fixed
``EA-WORLD-1`` seed namespace and stay in native 1536x1024 world coordinates.
They do not describe semantic terrain geometry.

All variants use an even prefix of one deterministic non-contact point stream.
Dark/light Lab-L deltas are exactly balanced, requested amplitudes are 7-9,
Chebyshev separation is at least four pixels, and no connected mark, line, or
regular lattice is allowed.  Existing thresholds remain unchanged.  Review
contacts are emitted only for candidates passing every hard gate.
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
OUT = ROOT / "tmp/map-production/k3-semantic-cleanup-v19-world-micrograin-v4"
V18 = ROOT / (
    "tmp/map-production/k3-semantic-cleanup-proof-v18/"
    "style-candidate-k-v3-semantic-cleanup-proof-v18.png"
)
BASE = ROOT / (
    "tmp/map-production/"
    "k3-semantic-cleanup-v19-broad-landform-contrast-refinement/"
    "broad-landform-d-lcontrast-065/broad-landform-d-lcontrast-065.png"
)
BASE_REPORT = ROOT / (
    "tmp/map-production/"
    "k3-semantic-cleanup-v19-broad-landform-contrast-refinement/"
    "broad-landform-contrast-search.json"
)
AUDIT = SCRIPTS / "audit_style_candidate_k3_semantic_cleanup.py"
HARNESS = SCRIPTS / "build_style_candidate_k3_highland_phase_synthesis.py"
BASE_PROBE = SCRIPTS / "probe_style_candidate_k3_highland_broad_landform.py"

EXPECTED = {
    V18: "013320af2f3296200a7d0b179e3a495f1e7905462213a6c645d85669dec02882",
    BASE: "20ee2a0f75a9a65213d2882347292ee76f4125a95adf217e4428d7bc9af1ff22",
    BASE_REPORT: "87ecf4771a9db6c9d7f6b384656a92a8ef63ac0d86b82d9cbed9220db23d97de",
    AUDIT: "3ae2981c6e20de68c512c9a4e63fe4c544f5361fbd6ea9335f2071d3027e8dc7",
}

WORLD_SEED_NAMESPACE = "EA-WORLD-1"
WORLD_SEED_PURPOSE = "K3-HIGHLAND-DRY-PAPER-MICROGRAIN-v4"
WORLD_SEED_MATERIAL = f"{WORLD_SEED_NAMESPACE}\0{WORLD_SEED_PURPOSE}"
WORLD_SEED_SHA256 = hashlib.sha256(WORLD_SEED_MATERIAL.encode("utf-8")).hexdigest()
WORLD_SEED_UINT64 = int(WORLD_SEED_SHA256[:16], 16)

CANDIDATE_LIMIT = 4
TARGET_ADDED_ACTIVE_FRACTIONS = (0.025, 0.035, 0.045, 0.055)
MINIMUM_CHEBYSHEV_DISTANCE_PX = 4
CORE_EROSION_PX = 7
POINT_MARGIN_INSIDE_CORE_PX = 2
BASE_ACTIVITY_CLEARANCE_PX = 2
AMPLITUDES_LAB_L = (7, 8, 9)
TARGET_TOLERANCE = 0.004
REGULAR_GRID_MAXIMUM_MODULO_BIN_SHARE = 0.40
PNG = {"format": "PNG", "compress_level": 9, "optimize": False}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base_probe = load_module("world_micrograin_v4_identity_authority", BASE_PROBE)
harness = load_module("world_micrograin_v4_full_gate_harness", HARNESS)
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


def point_counts(core_pixels: int) -> tuple[int, ...]:
    """Estimate even prefix sizes for five active pixels per isolated dot."""
    counts: list[int] = []
    for target in TARGET_ADDED_ACTIVE_FRACTIONS:
        estimate = int(round(target * core_pixels / 5.0))
        estimate += estimate % 2
        counts.append(estimate)
    if any(second <= first for first, second in zip(counts, counts[1:])):
        raise RuntimeError("non-increasing deterministic density prefixes")
    return tuple(counts)


def generate_point_pool(
    eligible: np.ndarray,
    count: int,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Return seeded native coordinates and exactly balanced signed deltas."""
    ys, xs = np.nonzero(eligible)
    if len(xs) < count:
        raise RuntimeError("too few eligible world-coordinate pixels")
    rng = np.random.default_rng(WORLD_SEED_UINT64)
    order = rng.permutation(len(xs))
    blocked = np.zeros(eligible.shape, bool)
    points: list[tuple[int, int]] = []
    radius = MINIMUM_CHEBYSHEV_DISTANCE_PX - 1
    for source_index in order:
        x = int(xs[source_index])
        y = int(ys[source_index])
        if blocked[y, x]:
            continue
        points.append((x, y))
        left = max(0, x - radius)
        right = min(eligible.shape[1], x + radius + 1)
        top = max(0, y - radius)
        bottom = min(eligible.shape[0], y + radius + 1)
        blocked[top:bottom, left:right] = True
        if len(points) == count:
            break
    if len(points) != count:
        raise RuntimeError(f"point packing stopped at {len(points)}/{count}")

    point_array = np.asarray(points, np.int32)
    pair_count = count // 2
    pair_amplitudes = rng.choice(AMPLITUDES_LAB_L, size=pair_count, replace=True)
    pair_flips = rng.integers(0, 2, size=pair_count, dtype=np.int8)
    deltas = np.empty(count, np.int16)
    for pair, amplitude in enumerate(pair_amplitudes):
        first = 2 * pair
        sign = 1 if int(pair_flips[pair]) else -1
        deltas[first] = sign * int(amplitude)
        deltas[first + 1] = -sign * int(amplitude)
    return point_array, deltas, {
        "seed_namespace": WORLD_SEED_NAMESPACE,
        "seed_purpose": WORLD_SEED_PURPOSE,
        "seed_material_utf8_sha256": WORLD_SEED_SHA256,
        "numpy_pcg64_seed_uint64": WORLD_SEED_UINT64,
        "coordinate_system": {
            "canvas_px": [k3.WIDTH, k3.HEIGHT],
            "origin": "native map top-left",
            "x_axis": "east/right",
            "y_axis": "south/down",
            "coordinates_resampled_or_transformed": False,
        },
        "selection": "seeded random permutation plus Chebyshev rejection",
        "point_stream_is_world_coordinate_texture_not_semantic_geometry": True,
        "packed_points": count,
    }


def render_prefix(
    base: np.ndarray,
    points: np.ndarray,
    deltas: np.ndarray,
    count: int,
) -> np.ndarray:
    candidate = base.copy()
    selected = points[:count]
    selected_deltas = deltas[:count]
    xs = selected[:, 0]
    ys = selected[:, 1]
    base_pixels = base[ys, xs].reshape((-1, 1, 3))
    lab_pixels = cv2.cvtColor(base_pixels, cv2.COLOR_RGB2LAB)
    target_l = np.clip(
        lab_pixels[:, 0, 0].astype(np.int16) + selected_deltas,
        0,
        255,
    ).astype(np.uint8)
    lab_pixels[:, 0, 0] = target_l
    candidate_pixels = cv2.cvtColor(lab_pixels, cv2.COLOR_LAB2RGB)[:, 0, :]
    candidate[ys, xs] = candidate_pixels
    return candidate


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
        "method": "maximum x/y modulo-bin occupancy for periods 4,5,7,8,11,13,16",
        "periods": periods,
        "maximum_modulo_bin_share": round(maximum, 9),
        "maximum_allowed": REGULAR_GRID_MAXIMUM_MODULO_BIN_SHARE,
        "passed": maximum <= REGULAR_GRID_MAXIMUM_MODULO_BIN_SHARE,
    }


def micrograin_contract(
    candidate: np.ndarray,
    base: np.ndarray,
    core: np.ndarray,
    base_active: np.ndarray,
    points: np.ndarray,
    deltas: np.ndarray,
    target_fraction: float,
) -> dict[str, Any]:
    changed = np.any(candidate != base, axis=2)
    selected = points[: len(deltas)]
    xs = selected[:, 0]
    ys = selected[:, 1]
    candidate_lab = cv2.cvtColor(candidate, cv2.COLOR_RGB2LAB)
    base_lab = cv2.cvtColor(base, cv2.COLOR_RGB2LAB)
    actual_l = (
        candidate_lab[ys, xs, 0].astype(np.int16)
        - base_lab[ys, xs, 0].astype(np.int16)
    )
    after_active = audit.activity_mask(candidate, core)
    added_active = after_active & ~base_active & core
    added_fraction = float(added_active[core].mean())

    component_count, _, component_stats, _ = cv2.connectedComponentsWithStats(
        changed.astype(np.uint8), 8
    )
    component_areas = component_stats[1:, cv2.CC_STAT_AREA].astype(int)
    lines = cv2.HoughLinesP(
        changed.astype(np.uint8) * 255,
        1,
        np.pi / 180,
        threshold=3,
        minLineLength=3,
        maxLineGap=1,
    )
    grid = regular_grid_proxy(selected)
    distance_violations = chebyshev_violation_count(selected)
    requested_dark = int(np.count_nonzero(deltas < 0))
    requested_light = int(np.count_nonzero(deltas > 0))
    actual_dark = int(np.count_nonzero(actual_l < 0))
    actual_light = int(np.count_nonzero(actual_l > 0))
    actual_amplitude = np.abs(actual_l)

    gates = {
        "exactly_one_changed_pixel_per_seed_point": bool(
            int(changed.sum()) == len(selected)
            and np.all(changed[ys, xs])
        ),
        "fully_editable_core_only": bool(
            np.count_nonzero(changed & ~core) == 0
        ),
        "requested_lab_l_amplitude_7_to_9": bool(
            np.all(np.isin(np.abs(deltas), AMPLITUDES_LAB_L))
        ),
        "decoded_lab_l_amplitude_7_to_9": bool(
            len(actual_amplitude)
            and int(actual_amplitude.min()) >= 7
            and int(actual_amplitude.max()) <= 9
        ),
        "dark_light_exact_balance": bool(
            requested_dark == requested_light
            and actual_dark == actual_light
            and requested_dark == actual_dark
        ),
        "chebyshev_distance_at_least_4": distance_violations == 0,
        "isolated_one_pixel_components": bool(
            component_count - 1 == len(selected)
            and len(component_areas) == len(selected)
            and np.all(component_areas == 1)
        ),
        "no_hough_line": lines is None,
        "no_regular_grid_proxy": grid["passed"],
        "added_active_dilation_fraction_approximately_2_to_6_percent": bool(
            0.02 <= added_fraction <= 0.06
            and abs(added_fraction - target_fraction) <= TARGET_TOLERANCE
        ),
    }
    return {
        "status": "hard-gated world-coordinate paper texture; not semantic geometry",
        "point_count": len(selected),
        "changed_pixels": int(changed.sum()),
        "changed_pixels_outside_fully_editable_core": int(
            np.count_nonzero(changed & ~core)
        ),
        "requested_lab_l": {
            "minimum_absolute_amplitude": int(np.abs(deltas).min()),
            "maximum_absolute_amplitude": int(np.abs(deltas).max()),
            "dark_points": requested_dark,
            "light_points": requested_light,
            "signed_sum": int(deltas.sum()),
        },
        "decoded_lab_l": {
            "minimum_absolute_amplitude": int(actual_amplitude.min()),
            "maximum_absolute_amplitude": int(actual_amplitude.max()),
            "dark_points": actual_dark,
            "light_points": actual_light,
            "signed_sum": int(actual_l.sum()),
        },
        "minimum_chebyshev_distance_px": MINIMUM_CHEBYSHEV_DISTANCE_PX,
        "chebyshev_distance_violation_pairs": distance_violations,
        "connected_components": {
            "count": component_count - 1,
            "minimum_area_px": int(component_areas.min()) if len(component_areas) else 0,
            "maximum_area_px": int(component_areas.max()) if len(component_areas) else 0,
        },
        "hough_line_count": 0 if lines is None else len(lines),
        "regular_grid_proxy": grid,
        "active_dilation": {
            "method": "audit.activity_mask after minus base activity, inside erode(highland_edit,7)",
            "base_active_fraction": round(float(base_active[core].mean()), 9),
            "candidate_active_fraction": round(float(after_active[core].mean()), 9),
            "target_added_fraction": target_fraction,
            "actual_added_fraction": round(added_fraction, 9),
            "allowed_range": [0.02, 0.06],
            "target_tolerance": TARGET_TOLERANCE,
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
    base = np.asarray(Image.open(BASE).convert("RGB"), np.uint8)
    k3.validate_source()
    masks = k3.derive_masks()
    core = k3.erode(masks["highland_edit"], CORE_EROSION_PX)
    if np.count_nonzero(core & masks["protected_features"]):
        raise RuntimeError("fully editable core overlaps protected features")
    base_active = audit.activity_mask(base, core)
    point_permission = k3.erode(core, POINT_MARGIN_INSIDE_CORE_PX)
    point_permission &= ~k3.dilate(base_active, BASE_ACTIVITY_CLEARANCE_PX)
    counts = point_counts(int(core.sum()))
    points, deltas, seed_record = generate_point_pool(
        point_permission, max(counts)
    )

    baseline_weave = harness.weave(baseline, masks["highland_edit"])
    baseline_activity = float(baseline_weave["activity_fraction"])
    records: dict[str, Any] = {}
    original_save_contacts = harness.save_contacts
    try:
        harness.save_contacts = lambda candidate, directory: {}
        for index, (target_fraction, count) in enumerate(
            zip(TARGET_ADDED_ACTIVE_FRACTIONS, counts), 1
        ):
            name = f"world-micrograin-{index}-f{int(target_fraction * 1000):03d}"
            candidate = render_prefix(base, points, deltas, count)
            contract = micrograin_contract(
                candidate,
                base,
                core,
                base_active,
                points[:count],
                deltas[:count],
                target_fraction,
            )
            identity_v18 = base_probe.guard_identity(candidate, baseline, masks)
            changed_base = np.any(candidate != base, axis=2)
            alpha_boundary = masks["highland_edit"] & ~core
            base_identity = {
                "differing_pixels_vs_base": int(changed_base.sum()),
                "differing_pixels_outside_fully_editable_core": int(
                    np.count_nonzero(changed_base & ~core)
                ),
                "differing_pixels_in_alpha_boundary_or_transition": int(
                    np.count_nonzero(changed_base & alpha_boundary)
                ),
                "alpha_boundary_byte_exact_base": bool(
                    np.array_equal(candidate[alpha_boundary], base[alpha_boundary])
                ),
            }
            record = harness.evaluate(
                name,
                candidate,
                baseline,
                masks,
                baseline_activity,
            )
            highland_semantic = record["semantic_diagnostic"]["highland"]
            if highland_semantic["measurement"]["erosion_px"] != CORE_EROSION_PX:
                raise RuntimeError("highland semantic measurement is not the 7px core")
            record["schema_version"] = "1.0.0"
            record["persistent_candidate_emitted"] = False
            record["lineage"] = {
                "frozen_v18": frozen[relative(V18)],
                "broad_landform_v2_lcontrast_065_base": frozen[relative(BASE)],
                "base_full_report": frozen[relative(BASE_REPORT)],
                "production_audit": frozen[relative(AUDIT)],
            }
            record["method"] = {
                "seed": seed_record,
                "prefix_points": count,
                "target_added_active_fraction": target_fraction,
                "fully_editable_core": {
                    "permission": "erode(highland_edit, 7)",
                    "erosion_px": CORE_EROSION_PX,
                    "pixels": int(core.sum()),
                },
                "lab_l_amplitudes": list(AMPLITUDES_LAB_L),
                "minimum_chebyshev_distance_px": MINIMUM_CHEBYSHEV_DISTANCE_PX,
                "semantic_geometry_added": False,
                "alpha_boundary_recomposed": False,
            }
            record["world_micrograin_contract"] = contract
            record["base_spatial_identity"] = base_identity
            record["road_guard_protected_outside_identity"] = identity_v18
            record["automated_gates"]["exact_k2_source_lock"] = bool(
                sha256(k3.SOURCE) == k3.EXPECTED_SOURCE
            )
            record["automated_gates"][
                "road_guard_protected_outside_byte_exact"
            ] = identity_v18["passed"]
            record["automated_gates"][
                "alpha_boundary_and_base_outside_core_byte_exact"
            ] = bool(
                base_identity["differing_pixels_vs_base"] > 0
                and base_identity["differing_pixels_outside_fully_editable_core"] == 0
                and base_identity[
                    "differing_pixels_in_alpha_boundary_or_transition"
                ]
                == 0
                and base_identity["alpha_boundary_byte_exact_base"]
            )
            record["automated_gates"][
                "highland_semantic_cleanup_proxies"
            ] = bool(highland_semantic["passed"])
            record["automated_gates"]["world_micrograin_contract"] = contract[
                "passed"
            ]
            record["failed_gates"] = [
                gate
                for gate, passed in record["automated_gates"].items()
                if not passed
            ]
            passed = not record["failed_gates"]
            record["status"] = (
                "passed-automated-gates-pending-root-vision"
                if passed
                else "failed-automated-gates"
            )
            record["vision_handoff"]["required"] = passed
            record["vision_handoff"][
                "contacts_emitted_only_after_all_hard_gates"
            ] = True
            record["vision_handoff"]["required_checks"] = [
                "broad landform masses remain readable at 25% and 50%",
                "one-pixel grain reads as dry paper rather than dots at 200%/400%",
                "no line, connected mark, grid, repeated icon, or directional texture",
                "no pasted highland panel or alpha-boundary change",
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
        "status": "TEMP-only EA-WORLD-1 highland dry-paper micrograin v4; no acceptance authority",
        "temporary_review_only": True,
        "decision_authority": False,
        "persistent_outputs_emitted": False,
        "thresholds_changed": False,
        "candidate_limit": CANDIDATE_LIMIT,
        "candidate_count": len(records),
        "inputs": {
            "frozen_v18": frozen[relative(V18)],
            "broad_landform_v2_lcontrast_065_base": frozen[relative(BASE)],
            "base_full_report": frozen[relative(BASE_REPORT)],
            "production_audit": frozen[relative(AUDIT)],
            "full_gate_harness": {
                "path": relative(HARNESS),
                "sha256": sha256(HARNESS),
            },
        },
        "operation": {
            "seed": seed_record,
            "target_added_active_fractions": list(TARGET_ADDED_ACTIVE_FRACTIONS),
            "prefix_point_counts": list(counts),
            "fully_editable_core": {
                "permission": "erode(highland_edit, 7)",
                "erosion_px": CORE_EROSION_PX,
                "pixels": int(core.sum()),
            },
            "point_margin_inside_core_px": POINT_MARGIN_INSIDE_CORE_PX,
            "base_activity_clearance_px": BASE_ACTIVITY_CLEARANCE_PX,
            "lab_l_amplitudes": list(AMPLITUDES_LAB_L),
            "minimum_chebyshev_distance_px": MINIMUM_CHEBYSHEV_DISTANCE_PX,
            "semantic_geometry_added": False,
            "alpha_boundary_recomposed": False,
        },
        "v18_weave": baseline_weave,
        "records": records,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    report_path = OUT / "world-micrograin-v4-search.json"
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
