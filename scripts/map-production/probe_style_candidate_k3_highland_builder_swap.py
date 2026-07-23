#!/usr/bin/env python3
"""Run a TEMP-only K3 production-builder highland donor swap.

This probe calls ``procedural_highland_canvas`` without changing its constants
or implementation.  It first proves that the current locked v4 donor
reconstructs the frozen v18 highland pixels exactly, then substitutes only the
locked v14, v15, and v17 donor rasters.  Candidates and reports are confined to
``tmp/map-production/k3-semantic-cleanup-v19-builder-swap``.  Persistent K3
outputs, the specification, manifests, controls, and prompts are read-only.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts/map-production"
sys.path.insert(0, str(SCRIPTS))

import audit_style_candidate_k3_semantic_cleanup as audit  # noqa: E402
import build_style_candidate_k3_semantic_cleanup as k3  # noqa: E402


OUT = ROOT / "tmp/map-production/k3-semantic-cleanup-v19-builder-swap"
V18 = (
    ROOT
    / "tmp/map-production/k3-semantic-cleanup-proof-v18"
    / "style-candidate-k-v3-semantic-cleanup-proof-v18.png"
)
EXPECTED_V18 = "013320af2f3296200a7d0b179e3a495f1e7905462213a6c645d85669dec02882"
TARGET_BOX = (930, 0, 1536, 560)
PNG = {"format": "PNG", "compress_level": 9, "optimize": False}

DONORS = {
    "v14": {
        "image": ROOT
        / "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/highland-planar-v14.png",
        "image_sha256": "2c8d0691bc16ad5d22410a29eea4619cfa2c2a1fa731a9b17ef123e66ffd65b0",
        "prompt": ROOT
        / "world/map-production/prompts/style-candidate-k-v3-highland-planar-donor-v14.generation.txt",
        "prompt_sha256": "06e782e46d9f1901f351721d152bc7513ab72bc4582fb7df4d23805902c621d0",
    },
    "v15": {
        "image": ROOT
        / "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/highland-planar-v15.png",
        "image_sha256": "5942a770e866fd1641156c141715cb55a473a65c7602a8075f0747e7b96e7602",
        "prompt": ROOT
        / "world/map-production/prompts/style-candidate-k-v3-highland-planar-donor-v15.generation.txt",
        "prompt_sha256": "d52572ef0af1a6801e305bd507ea2c19d224fe23fb1024931ba1e7c85b2c575e",
    },
    "v17": {
        "image": ROOT
        / "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/highland-inverse-aquatint-v17.png",
        "image_sha256": "4f64fcee2d5b1f0932f1d65fe460ba8bb1d4dff1b3ad68eafb75c0b7e72d9626",
        "prompt": ROOT
        / "world/map-production/prompts/style-candidate-k-v3-highland-inverse-aquatint-donor-v17.generation.txt",
        "prompt_sha256": "2483b3e00356dc51922f0130ddadfb2da098eaf306efc9008b6d228eb6436454",
    },
}


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
        raise RuntimeError(f"frozen input is missing: {path}")
    actual = sha256(path)
    if actual != digest:
        raise RuntimeError(f"frozen input hash mismatch: {path}: {actual}")
    return {"path": relative(path), "sha256": actual}


def gaussian(array: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(
        array.astype(np.float32),
        (0, 0),
        sigmaX=sigma,
        sigmaY=sigma,
        borderType=cv2.BORDER_REFLECT,
    )


def weave(image: np.ndarray, permission: np.ndarray) -> dict[str, Any]:
    """Use the existing v19 highland search proxy without threshold changes."""
    core = k3.erode(permission, 28)
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY).astype(np.float32)
    highpass = np.abs(gray - gaussian(gray, 1.6))
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(gx, gy)
    active = ((highpass >= 6.0) | (gradient >= 26.0)) & core
    return {
        "core_pixels": int(core.sum()),
        "activity_fraction": round(float(active[core].mean()), 9),
        "highpass_p95": round(float(np.percentile(highpass[core], 95)), 6),
        "gradient_p95": round(float(np.percentile(gradient[core], 95)), 6),
    }


def image_contract(path: Path) -> dict[str, Any]:
    with Image.open(path) as opened:
        passed = bool(
            opened.mode == "RGB"
            and opened.size == (k3.WIDTH, k3.HEIGHT)
            and opened.getbands() == ("R", "G", "B")
            and opened.info.get("transparency") is None
            and not opened.info.get("icc_profile")
        )
        return {
            "passed": passed,
            "mode": opened.mode,
            "size": list(opened.size),
            "bands": list(opened.getbands()),
            "info_keys": sorted(opened.info),
        }


def global_metrics(path: Path) -> dict[str, Any]:
    with (
        Image.open(path).convert("RGB") as candidate,
        Image.open(audit.k2_audit.B1_REFERENCE).convert("RGB") as b1,
        Image.open(audit.k2_audit.H4_REFERENCE).convert("RGB") as h4_reference,
        Image.open(audit.k2_audit.GUIDE).convert("RGB") as guide,
    ):
        return {
            "boundary": audit.h4.boundary_metrics(candidate),
            "palette": audit.h4.palette_continuity_metrics(candidate, b1),
            "exact_repetition": audit.h4.exact_repetition_metrics(candidate),
            "downsample": audit.h4.downsample_readability_metrics(candidate),
            "semantic_repetition": audit.h17.semantic_repetition_proxies(
                candidate, h4_reference
            ),
            "geometry": audit.k2_audit.geometry_metrics(guide, candidate),
        }


def save_contacts(
    candidate: np.ndarray, directory: Path
) -> dict[str, dict[str, Any]]:
    """Emit review derivatives only after every numeric gate passes."""
    directory.mkdir(parents=True, exist_ok=True)
    source = Image.fromarray(candidate, "RGB")
    definitions = (
        ("full25-lanczos.png", None, (384, 256)),
        ("full50-lanczos.png", None, (768, 512)),
        ("highland200-lanczos.png", TARGET_BOX, (1212, 1120)),
        ("highland400-lanczos.png", TARGET_BOX, (2424, 2240)),
    )
    records: dict[str, dict[str, Any]] = {}
    for name, crop, size in definitions:
        working = source.crop(crop) if crop is not None else source.copy()
        rendered = working.resize(size, Image.Resampling.LANCZOS)
        path = directory / name
        rendered.save(path, **PNG)
        rendered.close()
        working.close()
        records[name] = {
            "path": relative(path),
            "sha256": sha256(path),
            "size": list(size),
            "resampling": "Pillow LANCZOS; review derivative only",
        }
    source.close()
    return records


def production_candidate(
    base: np.ndarray,
    v18: np.ndarray,
    donor: np.ndarray,
    highland_record: dict[str, Any],
    masks: dict[str, Any],
) -> tuple[np.ndarray, dict[str, Any]]:
    permission = masks["highland_edit"]
    canvas, shift, method = k3.procedural_highland_canvas(
        base, donor, highland_record, permission
    )
    alpha = k3.boundary_locked_alpha(
        permission, full_by_px=5, locked_boundary_px=2
    )
    rendered = k3.composite_with_alpha(base, canvas, alpha)
    candidate = v18.copy()
    candidate[permission] = rendered[permission]
    if np.any(masks["forest_edit"] & permission):
        raise RuntimeError("forest/highland production permissions overlap")
    if np.any(masks["fields_edit"] & permission):
        raise RuntimeError("fields/highland production permissions overlap")
    return candidate, {
        "algorithm": "unmodified k3.procedural_highland_canvas plus production boundary_locked_alpha(locked=2,full=5)",
        "algorithm_constants": {
            "solid_mark_span_rgb": list(k3.HIGHLAND_MARK_SPAN_RGB),
            "solid_mark_local_dark_threshold": k3.HIGHLAND_MARK_LOCAL_DARK_THRESHOLD,
            "solid_mark_minimum_component_area": k3.HIGHLAND_MARK_MIN_COMPONENT_AREA,
            "quiet_background_dark_cap": k3.HIGHLAND_BACKGROUND_DARK_CAP,
            "paper_grain_channel_cap": k3.HIGHLAND_PAPER_GRAIN_CAP,
        },
        "color_match_shift_rgb": shift,
        "production_method_record": method,
        "alpha": {
            "locked_boundary_px": 2,
            "full_by_px": 5,
            "zero_pixels_inside_permission": int(
                np.count_nonzero(permission & (alpha == 0.0))
            ),
            "fractional_pixels": int(
                np.count_nonzero((alpha > 0.0) & (alpha < 1.0))
            ),
            "full_pixels": int(np.count_nonzero(alpha == 1.0)),
        },
    }


def solid_mark_diagnostics(
    donor: np.ndarray,
    highland_record: dict[str, Any],
) -> dict[str, Any]:
    """Mirror the production selector to explain fail-closed empty-mark exits."""
    left, top, right, bottom = k3.registration_crop(highland_record)
    width, height = right - left, bottom - top
    source_crop = (0, 47, 1254, 1206)
    sx0, sy0, sx1, sy1 = source_crop
    mapped = np.asarray(
        Image.fromarray(donor[sy0:sy1, sx0:sx1], "RGB").resize(
            (width, height), Image.Resampling.BOX
        ),
        np.uint8,
    )
    gray = cv2.cvtColor(mapped, cv2.COLOR_RGB2GRAY).astype(np.float32)
    local_context = cv2.GaussianBlur(gray, (0, 0), 8.0)
    local_dark = local_context - gray
    seeds = local_dark >= k3.HIGHLAND_MARK_LOCAL_DARK_THRESHOLD
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        seeds.astype(np.uint8), 8
    )
    component_areas = [
        int(stats[index, cv2.CC_STAT_AREA]) for index in range(1, count)
    ]
    retained = [
        area
        for area in component_areas
        if area >= k3.HIGHLAND_MARK_MIN_COMPONENT_AREA
    ]
    return {
        "source_crop_xyxy": list(source_crop),
        "target_size_wh": [width, height],
        "resampling": "Pillow BOX area downsample",
        "local_context_gaussian_sigma_px": 8.0,
        "local_dark_threshold": k3.HIGHLAND_MARK_LOCAL_DARK_THRESHOLD,
        "minimum_component_area": k3.HIGHLAND_MARK_MIN_COMPONENT_AREA,
        "local_dark_maximum": round(float(local_dark.max()), 6),
        "local_dark_quantiles": {
            "p95": round(float(np.quantile(local_dark, 0.95)), 6),
            "p99": round(float(np.quantile(local_dark, 0.99)), 6),
            "p999": round(float(np.quantile(local_dark, 0.999)), 6),
        },
        "seed_pixels": int(seeds.sum()),
        "connected_components_before_area_gate": len(component_areas),
        "maximum_component_area_before_area_gate": max(component_areas, default=0),
        "retained_components": len(retained),
        "retained_pixels": int(sum(retained)),
        "production_empty_mark_guard_will_raise": not retained,
    }


def evaluate(
    name: str,
    candidate: np.ndarray,
    base: np.ndarray,
    v18: np.ndarray,
    masks: dict[str, Any],
    baseline_activity: float,
    method: dict[str, Any],
    lineage: dict[str, Any],
) -> dict[str, Any]:
    directory = OUT / name
    directory.mkdir(parents=True, exist_ok=True)
    candidate_path = directory / f"{name}.png"
    Image.fromarray(candidate, "RGB").save(candidate_path, **PNG)

    permission = masks["highland_edit"]
    changed_v18 = np.any(candidate != v18, axis=2)
    changed_k2 = np.any(candidate != base, axis=2)
    strict = audit.strict_content_metrics(candidate, masks)
    semantic = audit.semantic_cleanup_metrics(candidate, masks)
    blotch = audit.low_frequency_blotch_metrics(candidate, masks)
    cadence = audit.parcel_boundary_cadence_metrics(candidate, masks)
    global_gates = global_metrics(candidate_path)
    contract = image_contract(candidate_path)
    candidate_weave = weave(candidate, permission)
    activity = float(candidate_weave["activity_fraction"])
    orientation = semantic["highland"]["orientation_substrate_proxy"]
    identity = {
        "differing_pixels_vs_v18": int(changed_v18.sum()),
        "differing_pixels_inside_highland_edit": int(
            np.count_nonzero(changed_v18 & permission)
        ),
        "differing_pixels_outside_highland_edit": int(
            np.count_nonzero(changed_v18 & ~permission)
        ),
        "differing_protected_feature_pixels_vs_v18": int(
            np.count_nonzero(changed_v18 & masks["protected_features"])
        ),
        "changed_pixels_vs_k2_outside_v18_edit_union": int(
            np.count_nonzero(changed_k2 & ~masks["edit_union"])
        ),
        "outside_highland_exact_v18": bool(
            np.array_equal(candidate[~permission], v18[~permission])
        ),
    }
    automated_gates = {
        "exact_k2_source_lock": sha256(k3.SOURCE) == k3.EXPECTED_SOURCE,
        "native_rgb_no_alpha_profile": contract["passed"],
        "v18_highland_only_spatial_identity": bool(
            identity["differing_pixels_inside_highland_edit"] > 0
            and identity["differing_pixels_outside_highland_edit"] == 0
            and identity["differing_protected_feature_pixels_vs_v18"] == 0
            and identity["outside_highland_exact_v18"]
        ),
        "semantic_cleanup_proxies": semantic["passed"],
        "strict_local_raster_and_structure": strict[
            "passed_automated_raster_and_structure"
        ],
        "low_frequency_blotch_v1": blotch["passed"],
        "measurable_weave_reduction_and_orientation": bool(
            activity <= 0.15
            and activity <= 0.25 * baseline_activity
            and orientation["passed"]
        ),
        "unchanged_boundary": global_gates["boundary"]["passed"],
        "unchanged_palette": global_gates["palette"]["passed"],
        "unchanged_exact_repetition": global_gates["exact_repetition"][
            "passed"
        ],
        "unchanged_downsample": global_gates["downsample"]["passed"],
        "unchanged_semantic_repetition": global_gates["semantic_repetition"][
            "passed"
        ],
        "unchanged_strict_geometry": global_gates["geometry"]["passed"],
    }
    failed = [key for key, passed in automated_gates.items() if not passed]
    record: dict[str, Any] = {
        "schema_version": "1.0.0",
        "status": (
            "passed-automated-gates-pending-root-vision"
            if not failed
            else "failed-automated-gates"
        ),
        "temporary_review_only": True,
        "decision_authority": False,
        "persistent_candidate_emitted": False,
        "golden_accepted": False,
        "candidate": {
            "path": relative(candidate_path),
            "sha256": sha256(candidate_path),
        },
        "lineage": lineage,
        "method": method,
        "image_contract": contract,
        "identity": identity,
        "weave_reduction": {
            "candidate": candidate_weave,
            "candidate_to_v18_activity_ratio": round(
                activity / max(baseline_activity, 1e-12), 9
            ),
            "thresholds": {
                "maximum_candidate_activity_fraction": 0.15,
                "maximum_candidate_to_v18_activity_ratio": 0.25,
                "maximum_orientation_coherence": audit.MAXIMUM_ORIENTATION_COHERENCE,
            },
            "orientation": orientation,
        },
        "strict_content": strict,
        "semantic_diagnostic": semantic,
        "low_frequency_blotch": blotch,
        "parcel_boundary_cadence_diagnostic": cadence,
        "global_gates": global_gates,
        "automated_gates": automated_gates,
        "failed_gates": failed,
        "contacts": {},
        "vision_handoff": {
            "required": not failed,
            "contacts_emitted_only_after_all_numeric_gates": True,
            "required_checks": [
                "repeating spots or object-like blobs",
                "loops, cells, glyphs, or woven substrate",
                "pasted-panel boundary or flat polygon read",
                "airbrush, cloud, camouflage, or smooth stain masses",
            ],
            "semantic_claim": None,
        },
    }
    if not failed:
        record["contacts"] = save_contacts(candidate, directory / "contacts")
    report_path = directory / f"{name}.full-audit.json"
    report_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    record["report"] = {
        "path": relative(report_path),
        "sha256": sha256(report_path),
    }
    return record


def main() -> None:
    persistent = (k3.RAW, k3.FINAL, k3.RECEIPT, k3.AUDIT)
    if any(path.exists() for path in persistent):
        raise RuntimeError("persistent K3 output unexpectedly exists")
    frozen_v18 = locked(V18, EXPECTED_V18)
    frozen_donors = {
        name: {
            "image": locked(record["image"], record["image_sha256"]),
            "prompt": locked(record["prompt"], record["prompt_sha256"]),
        }
        for name, record in DONORS.items()
    }

    spec_bytes_before = k3.SPEC.read_bytes()
    spec_sha_before = sha256(k3.SPEC)
    spec = k3.load_spec()
    highland_record = dict(spec["donor_slots"]["highland"])
    current_donor_path = ROOT / highland_record["path"]
    current_donor = k3.validate_donor_record("highland", highland_record)
    base = k3.validate_source()
    v18 = np.asarray(Image.open(V18).convert("RGB"), np.uint8)
    masks = k3.derive_masks()
    permission = masks["highland_edit"]

    reconstructed, reconstruction_method = production_candidate(
        base, v18, current_donor, highland_record, masks
    )
    reconstruction_difference = np.any(reconstructed != v18, axis=2)
    reconstruction = {
        "current_locked_donor": {
            "path": relative(current_donor_path),
            "sha256": sha256(current_donor_path),
        },
        "method": reconstruction_method,
        "differing_pixels_total": int(reconstruction_difference.sum()),
        "differing_pixels_inside_highland_edit": int(
            np.count_nonzero(reconstruction_difference & permission)
        ),
        "differing_pixels_outside_highland_edit": int(
            np.count_nonzero(reconstruction_difference & ~permission)
        ),
        "passed_exact_v18_reconstruction": bool(
            np.array_equal(reconstructed, v18)
        ),
    }
    if not reconstruction["passed_exact_v18_reconstruction"]:
        raise RuntimeError(
            "current production donor did not reconstruct frozen v18 exactly"
        )

    baseline_weave = weave(v18, permission)
    baseline_activity = float(baseline_weave["activity_fraction"])
    candidates: dict[str, Any] = {}
    for name, donor_record in DONORS.items():
        donor = np.asarray(Image.open(donor_record["image"]).convert("RGB"), np.uint8)
        try:
            candidate, method = production_candidate(
                base, v18, donor, highland_record, masks
            )
        except k3.K3BuildError as error:
            directory = OUT / f"builder-swap-{name}"
            directory.mkdir(parents=True, exist_ok=True)
            build_failure: dict[str, Any] = {
                "schema_version": "1.0.0",
                "status": "failed-production-build-before-candidate",
                "temporary_review_only": True,
                "decision_authority": False,
                "persistent_candidate_emitted": False,
                "golden_accepted": False,
                "candidate": None,
                "lineage": frozen_donors[name],
                "production_call": "unmodified k3.procedural_highland_canvas",
                "production_error": {
                    "type": type(error).__name__,
                    "message": str(error),
                },
                "solid_mark_diagnostics": solid_mark_diagnostics(
                    donor, highland_record
                ),
                "numeric_audit_started": False,
                "failed_gates": ["production_solid_mark_selection_nonempty"],
                "contacts": {},
                "vision_handoff": {
                    "required": False,
                    "reason": "no candidate exists; production builder failed closed before numeric audit",
                    "contacts_emitted_only_after_all_numeric_gates": True,
                },
            }
            report_path = directory / f"builder-swap-{name}.build-failure.json"
            report_path.write_text(
                json.dumps(build_failure, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            build_failure["report"] = {
                "path": relative(report_path),
                "sha256": sha256(report_path),
            }
            candidates[name] = build_failure
            continue
        candidates[name] = evaluate(
            f"builder-swap-{name}",
            candidate,
            base,
            v18,
            masks,
            baseline_activity,
            method,
            frozen_donors[name],
        )

    if k3.SPEC.read_bytes() != spec_bytes_before or sha256(k3.SPEC) != spec_sha_before:
        raise RuntimeError("specification changed during TEMP-only probe")
    if any(path.exists() for path in persistent):
        raise RuntimeError("TEMP-only probe emitted a persistent K3 output")

    summary = {
        "schema_version": "1.0.0",
        "id": "k3-semantic-cleanup-v19-production-builder-donor-swap",
        "status": (
            "numeric-candidate-found-pending-root-vision"
            if any(
                item["candidate"] is not None and not item["failed_gates"]
                for item in candidates.values()
            )
            else (
                "all-donor-swaps-failed-production-build"
                if all(item["candidate"] is None for item in candidates.values())
                else "no-candidate-passed-numeric-gates"
            )
        ),
        "temporary_review_only": True,
        "decision_authority": False,
        "persistent_outputs_emitted": False,
        "specification_unchanged": True,
        "production_algorithm_constants_changed": False,
        "frozen_v18": frozen_v18,
        "specification": {
            "path": relative(k3.SPEC),
            "sha256_before_and_after": spec_sha_before,
        },
        "exact_current_builder_reconstruction": reconstruction,
        "baseline_v18_weave": baseline_weave,
        "candidates": {
            name: {
                "status": record["status"],
                "candidate": record["candidate"],
                "report": record["report"],
                "failed_gates": record["failed_gates"],
                "contacts": record["contacts"],
                "key_metrics": (
                    {
                        "highland_strict": record["strict_content"]["highland"],
                        "highland_semantic": record["semantic_diagnostic"]["highland"],
                        "weave_reduction": record["weave_reduction"],
                        "palette": record["global_gates"]["palette"],
                        "downsample": record["global_gates"]["downsample"],
                    }
                    if record["candidate"] is not None
                    else {
                        "numeric_audit_started": False,
                        "solid_mark_diagnostics": record[
                            "solid_mark_diagnostics"
                        ],
                    }
                ),
            }
            for name, record in candidates.items()
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    summary_path = OUT / "builder-swap-summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": summary["status"],
                "summary": {
                    "path": relative(summary_path),
                    "sha256": sha256(summary_path),
                },
                "exact_current_builder_reconstruction": reconstruction[
                    "passed_exact_v18_reconstruction"
                ],
                "candidates": {
                    name: {
                        "status": record["status"],
                        "candidate": record["candidate"],
                        "report": record["report"],
                        "failed_gates": record["failed_gates"],
                        "contacts": record["contacts"],
                    }
                    for name, record in candidates.items()
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
