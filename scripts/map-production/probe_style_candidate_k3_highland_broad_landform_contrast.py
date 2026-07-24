#!/usr/bin/env python3
"""TEMP-only Lab-L contrast refinements of broad-landform v1 variant D.

The four-candidate v1 probe remains frozen and intact.  This follow-up first
reconstructs v1 D byte-exactly from its locked ImageGen donor, then compresses
the complete pre-alpha D Lab-L plate about the registered v18 target median at
exactly three fixed factors.  Lab a/b, spatial coordinates, masks, roads,
guards, protected features, and every pixel outside the highland permission
are unchanged.

Review contacts are emitted only after the unchanged complete acceptance-gate
harness, the highland-specific semantic diagnostics, and explicit byte-identity
checks all pass.  Nothing outside tmp/ is written.
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
OUT = ROOT / (
    "tmp/map-production/"
    "k3-semantic-cleanup-v19-broad-landform-contrast-refinement"
)
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
V1_D = ROOT / (
    "tmp/map-production/k3-semantic-cleanup-v19-broad-landform-probe/"
    "broad-landform-d-s260-g012/broad-landform-d-s260-g012.png"
)
V1_REPORT = ROOT / (
    "tmp/map-production/k3-semantic-cleanup-v19-broad-landform-probe/"
    "broad-landform-search.json"
)
BASE_PROBE = SCRIPTS / "probe_style_candidate_k3_highland_broad_landform.py"
HARNESS = SCRIPTS / "build_style_candidate_k3_highland_phase_synthesis.py"

EXPECTED = {
    V18: "013320af2f3296200a7d0b179e3a495f1e7905462213a6c645d85669dec02882",
    DONOR: "67fdedc66e9c2b0a7d8b0f7af6c4e093838f0df3c1130bfde83d8ea4a84b116b",
    PROMPT: "64c8b133bb41e2eb08e5ea6cabc2541f7058c3d4088ce98904acddaae99cae83",
    V1_D: "50bbb17b02d0ed933116d34a1812c433451057d9e23cd2a76748a5a55bf5f8c1",
    V1_REPORT: "19aa469e3d21a91ef3473de75687f491ff566a0ac80669e43e77bd3af60daf2d",
}

PNG = {"format": "PNG", "compress_level": 9, "optimize": False}
CANDIDATE_LIMIT = 3
RECIPES: tuple[dict[str, Any], ...] = (
    {"name": "broad-landform-d-lcontrast-055", "lab_l_contrast": 0.55},
    {"name": "broad-landform-d-lcontrast-065", "lab_l_contrast": 0.65},
    {"name": "broad-landform-d-lcontrast-075", "lab_l_contrast": 0.75},
)
D_RECIPE = {
    "name": "broad-landform-d-s260-g012",
    "highpass_sigma_px": 2.6,
    "highpass_gain": 0.12,
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base_probe = load_module("broad_landform_v1_authority", BASE_PROBE)
harness = load_module("broad_landform_contrast_full_gate_harness", HARNESS)
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


def locked(path: Path, digest: str) -> dict[str, str]:
    if not path.is_file():
        raise RuntimeError(f"frozen input missing: {path}")
    actual = sha256(path)
    if actual != digest:
        raise RuntimeError(f"frozen input hash mismatch: {path}: {actual}")
    return {"path": relative(path), "sha256": actual}


def contrast_plate(
    d_plate_rgb: np.ndarray,
    target_median_l: float,
    factor: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    lab = cv2.cvtColor(d_plate_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    before_l = lab[..., 0].copy()
    lab[..., 0] = target_median_l + factor * (before_l - target_median_l)
    encoded = np.clip(np.rint(lab), 0, 255).astype(np.uint8)
    after_l = encoded[..., 0].astype(np.float32)
    return cv2.cvtColor(encoded, cv2.COLOR_LAB2RGB), {
        "operation": "complete pre-alpha D Lab-L contrast compression about registered target median",
        "target_median_lab_l": round(float(target_median_l), 6),
        "lab_l_contrast_factor": factor,
        "lab_a_b_changed_before_rgb_encoding": False,
        "input_lab_l_quantiles": [
            round(float(value), 6)
            for value in np.quantile(before_l, (0.01, 0.05, 0.50, 0.95, 0.99))
        ],
        "output_lab_l_quantiles": [
            round(float(value), 6)
            for value in np.quantile(after_l, (0.01, 0.05, 0.50, 0.95, 0.99))
        ],
        "spatial_transform": "none",
        "geometry_drawn": False,
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
    if len(RECIPES) > CANDIDATE_LIMIT:
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
    frozen_v1_d = np.asarray(Image.open(V1_D).convert("RGB"), np.uint8)
    k3.validate_source()
    masks = k3.derive_masks()
    permission = masks["highland_edit"]
    registration_mask = k3.erode(permission, 28)
    registered_lab, registration = base_probe.register_lab_median(
        donor, baseline, registration_mask
    )
    d_plate_rgb, d_filtering = base_probe.variant_plate(
        registered_lab, D_RECIPE
    )
    alpha = k3.boundary_locked_alpha(
        permission, full_by_px=7.0, locked_boundary_px=2.0
    )

    reconstructed = baseline.copy()
    reconstructed_render = k3.composite_with_alpha(
        baseline, d_plate_rgb, alpha
    )
    reconstructed[permission] = reconstructed_render[permission]
    reconstruction = {
        "expected_v1_d": frozen[relative(V1_D)],
        "reconstructed_sha256": hashlib.sha256(reconstructed.tobytes()).hexdigest(),
        "differing_pixels": int(
            np.count_nonzero(np.any(reconstructed != frozen_v1_d, axis=2))
        ),
        "passed_pixel_exact": bool(np.array_equal(reconstructed, frozen_v1_d)),
    }
    # The raster byte hash includes PNG encoding while this equality check is
    # the stronger semantic proof that the decoded source pixels are exact.
    if not reconstruction["passed_pixel_exact"]:
        raise RuntimeError("cannot reconstruct frozen v1 D pixels exactly")

    alpha_record = {
        "constructor": "k3.boundary_locked_alpha",
        "locked_boundary_px": 2.0,
        "full_by_px": 7.0,
        "zero_pixels_inside_permission": int(
            np.count_nonzero(permission & (alpha == 0.0))
        ),
        "fractional_pixels": int(
            np.count_nonzero(permission & (alpha > 0.0) & (alpha < 1.0))
        ),
        "full_pixels_inside_permission": int(
            np.count_nonzero(permission & (alpha == 1.0))
        ),
        "nonzero_pixels_outside_permission": int(
            np.count_nonzero(~permission & (alpha != 0.0))
        ),
    }
    baseline_weave = harness.weave(baseline, permission)
    baseline_activity = float(baseline_weave["activity_fraction"])
    target_median_l = float(registration["target_v18_median_lab"][0])
    records: dict[str, Any] = {}
    original_save_contacts = harness.save_contacts
    try:
        harness.save_contacts = lambda candidate, directory: {}
        for recipe in RECIPES:
            plate, operation = contrast_plate(
                d_plate_rgb,
                target_median_l,
                float(recipe["lab_l_contrast"]),
            )
            rendered = k3.composite_with_alpha(baseline, plate, alpha)
            candidate = baseline.copy()
            candidate[permission] = rendered[permission]
            identity = base_probe.guard_identity(candidate, baseline, masks)
            record = harness.evaluate(
                str(recipe["name"]),
                candidate,
                baseline,
                masks,
                baseline_activity,
            )
            highland_semantic = record["semantic_diagnostic"]["highland"]
            record["schema_version"] = "1.0.0"
            record["persistent_candidate_emitted"] = False
            record["lineage"] = {
                "frozen_v18": frozen[relative(V18)],
                "imagegen_control": frozen[relative(DONOR)],
                "exact_generation_prompt": frozen[relative(PROMPT)],
                "frozen_v1_d": frozen[relative(V1_D)],
                "frozen_v1_report": frozen[relative(V1_REPORT)],
            }
            record["method"] = {
                "v1_d_registration": registration,
                "v1_d_filtering": d_filtering,
                "contrast_refinement": operation,
                "boundary_alpha": alpha_record,
                "same_coordinate_full_context": True,
            }
            record["v1_d_reconstruction"] = reconstruction
            record["road_guard_protected_outside_identity"] = identity
            record["automated_gates"]["exact_k2_source_lock"] = bool(
                sha256(k3.SOURCE) == k3.EXPECTED_SOURCE
            )
            record["automated_gates"][
                "road_guard_protected_outside_byte_exact"
            ] = identity["passed"]
            record["automated_gates"][
                "highland_semantic_cleanup_proxies"
            ] = bool(highland_semantic["passed"])
            record["failed_gates"] = [
                name
                for name, passed in record["automated_gates"].items()
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
                "contacts_emitted_only_after_all_numeric_gates"
            ] = True
            record["contacts"] = (
                original_save_contacts(
                    candidate, OUT / str(recipe["name"]) / "contacts"
                )
                if passed
                else {}
            )
            record["recipe"] = recipe
            rewrite_candidate_report(record)
            records[str(recipe["name"])] = record
    finally:
        harness.save_contacts = original_save_contacts

    if k3.SPEC.read_bytes() != spec_bytes_before or sha256(k3.SPEC) != spec_sha_before:
        raise RuntimeError("persistent K3 specification changed during TEMP probe")
    if any(path.exists() for path in persistent):
        raise RuntimeError("TEMP probe emitted a persistent K3 output")

    aggregate = {
        "schema_version": "1.0.0",
        "status": "TEMP-only broad-landform Lab-L contrast refinement; no acceptance authority",
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
            "frozen_v1_d": frozen[relative(V1_D)],
            "frozen_v1_report": frozen[relative(V1_REPORT)],
            "base_probe": {
                "path": relative(BASE_PROBE),
                "sha256": sha256(BASE_PROBE),
            },
            "full_gate_harness": {
                "path": relative(HARNESS),
                "sha256": sha256(HARNESS),
            },
        },
        "v1_d_reconstruction": reconstruction,
        "operation": {
            "v1_d_registration": registration,
            "v1_d_filtering": d_filtering,
            "boundary_alpha": alpha_record,
            "candidate_recipes": list(RECIPES),
            "all_lab_l_contrast_compressed": True,
            "lab_a_b_pre_encoding_unchanged": True,
            "spatial_transform": "none",
        },
        "v18_weave": baseline_weave,
        "records": records,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    report_path = OUT / "broad-landform-contrast-search.json"
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
                "v1_d_reconstruction": reconstruction,
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
                        "orientation": record["weave_reduction"]["orientation"][
                            "global_gradient_orientation_coherence"
                        ],
                        "highland_semantic": record["semantic_diagnostic"][
                            "highland"
                        ],
                        "strict_highland": record["strict_content"]["highland"],
                        "palette": record["global_gates"]["palette"],
                        "downsample": record["global_gates"]["downsample"],
                        "identity": record[
                            "road_guard_protected_outside_identity"
                        ],
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
