#!/usr/bin/env python3
"""Probe a locked full-context ImageGen broad-landform control for K3.

Exactly four candidates are allowed.  The full-context donor stays in its
native 1536x1024 coordinates and is registered to frozen v18 with a per-channel
Lab median shift over the strict highland core.  Variant A uses that registered
donor directly.  Variants B-D attenuate, rather than replace, its high-pass
residual at three fixed scales so the generated broad landforms remain the
spatial authority.

This is a fail-closed TEMP-only exploration.  It cannot write a persistent
candidate, specification, manifest, prompt, or control asset.  Review contacts
are emitted only for variants passing the unchanged complete numeric harness
plus exact road/guard/protected/outside identity checks.
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
OUT = ROOT / "tmp/map-production/k3-semantic-cleanup-v19-broad-landform-probe"
V18 = ROOT / (
    "tmp/map-production/k3-semantic-cleanup-proof-v18/"
    "style-candidate-k-v3-semantic-cleanup-proof-v18.png"
)
DONOR = ROOT / (
    "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/"
    "highland-context-broad-landform-v19.png"
)
PROMPT = ROOT / (
    "world/map-production/prompts/"
    "style-candidate-k-v3-highland-broad-landform-v19.generation.txt"
)
HARNESS = SCRIPTS / "probe_style_candidate_k3_highland_builder_swap.py"

EXPECTED = {
    V18: "013320af2f3296200a7d0b179e3a495f1e7905462213a6c645d85669dec02882",
    DONOR: "67fdedc66e9c2b0a7d8b0f7af6c4e093838f0df3c1130bfde83d8ea4a84b116b",
    PROMPT: "64c8b133bb41e2eb08e5ea6cabc2541f7058c3d4088ce98904acddaae99cae83",
}

CANDIDATE_LIMIT = 4
PNG = {"format": "PNG", "compress_level": 9, "optimize": False}
RECIPES: tuple[dict[str, Any], ...] = (
    {
        "name": "broad-landform-a-direct",
        "highpass_sigma_px": None,
        "highpass_gain": 1.0,
    },
    {
        "name": "broad-landform-b-s120-g045",
        "highpass_sigma_px": 1.2,
        "highpass_gain": 0.45,
    },
    {
        "name": "broad-landform-c-s180-g025",
        "highpass_sigma_px": 1.8,
        "highpass_gain": 0.25,
    },
    {
        "name": "broad-landform-d-s260-g012",
        "highpass_sigma_px": 2.6,
        "highpass_gain": 0.12,
    },
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


harness = load_module("broad_landform_full_gate_harness", HARNESS)
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


def gaussian(array: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(
        array.astype(np.float32),
        (0, 0),
        sigmaX=sigma,
        sigmaY=sigma,
        borderType=cv2.BORDER_REFLECT,
    )


def locked(path: Path, digest: str) -> dict[str, str]:
    if not path.is_file():
        raise RuntimeError(f"frozen input missing: {path}")
    actual = sha256(path)
    if actual != digest:
        raise RuntimeError(f"frozen input hash mismatch: {path}: {actual}")
    return {"path": relative(path), "sha256": actual}


def validate_rgb_size(path: Path) -> dict[str, Any]:
    with Image.open(path) as opened:
        record = {
            "mode": opened.mode,
            "size": list(opened.size),
            "bands": list(opened.getbands()),
            "has_alpha_or_transparency": bool(
                "A" in opened.getbands() or opened.info.get("transparency") is not None
            ),
            "has_icc_profile": bool(opened.info.get("icc_profile")),
        }
    record["passed"] = bool(
        record["mode"] == "RGB"
        and record["size"] == [k3.WIDTH, k3.HEIGHT]
        and record["bands"] == ["R", "G", "B"]
        and not record["has_alpha_or_transparency"]
        and not record["has_icc_profile"]
    )
    if not record["passed"]:
        raise RuntimeError(f"native RGB input contract failed: {path}: {record}")
    return record


def register_lab_median(
    donor_rgb: np.ndarray,
    baseline_rgb: np.ndarray,
    registration_mask: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any]]:
    donor_lab = cv2.cvtColor(donor_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    baseline_lab = cv2.cvtColor(baseline_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    donor_median = np.median(donor_lab[registration_mask], axis=0)
    baseline_median = np.median(baseline_lab[registration_mask], axis=0)
    shift = baseline_median - donor_median
    registered = np.clip(donor_lab + shift.reshape(1, 1, 3), 0.0, 255.0)
    registered_median = np.median(registered[registration_mask], axis=0)
    return registered, {
        "colour_space": "OpenCV uint8 Lab coordinate system, float32 arithmetic",
        "method": "per-channel median shift at identical full-context coordinates",
        "registration_mask": "erode(highland_edit, 28px)",
        "registration_pixels": int(registration_mask.sum()),
        "donor_median_lab": [round(float(value), 6) for value in donor_median],
        "target_v18_median_lab": [
            round(float(value), 6) for value in baseline_median
        ],
        "shift_lab": [round(float(value), 6) for value in shift],
        "registered_median_lab": [
            round(float(value), 6) for value in registered_median
        ],
        "no_scale_rotation_crop_or_warp": True,
    }


def variant_plate(
    registered_lab: np.ndarray, recipe: dict[str, Any]
) -> tuple[np.ndarray, dict[str, Any]]:
    sigma = recipe["highpass_sigma_px"]
    gain = float(recipe["highpass_gain"])
    if sigma is None:
        composed = registered_lab
        operation = "registered Lab donor direct"
    else:
        lowpass = gaussian(registered_lab, float(sigma))
        highpass = registered_lab - lowpass
        composed = lowpass + gain * highpass
        operation = "registered Lab donor lowpass plus attenuated native highpass"
    encoded = np.clip(np.rint(composed), 0, 255).astype(np.uint8)
    return cv2.cvtColor(encoded, cv2.COLOR_LAB2RGB), {
        "operation": operation,
        "highpass_sigma_px": sigma,
        "highpass_gain": gain,
        "broad_lowpass_gain": 1.0,
        "channels_processed": ["Lab-L", "Lab-a", "Lab-b"],
        "spatial_transform": "none; native 1536x1024 same-coordinate donor",
    }


def guard_identity(
    candidate: np.ndarray,
    baseline: np.ndarray,
    masks: dict[str, Any],
) -> dict[str, Any]:
    changed = np.any(candidate != baseline, axis=2)
    permission_exclusions = np.zeros(changed.shape, bool)
    for exclusion in masks["permission_exclusions"].values():
        permission_exclusions |= exclusion
    guard_counts = {
        name: int(np.count_nonzero(changed & mask))
        for name, mask in sorted(masks["guards"].items())
    }
    record = {
        "differing_pixels_outside_highland_edit": int(
            np.count_nonzero(changed & ~masks["highland_edit"])
        ),
        "differing_pixels_in_permission_exclusions": int(
            np.count_nonzero(changed & permission_exclusions)
        ),
        "differing_pixels_in_protected_features": int(
            np.count_nonzero(changed & masks["protected_features"])
        ),
        "differing_pixels_by_guard": guard_counts,
    }
    record["passed"] = bool(
        record["differing_pixels_outside_highland_edit"] == 0
        and record["differing_pixels_in_permission_exclusions"] == 0
        and record["differing_pixels_in_protected_features"] == 0
        and all(count == 0 for count in guard_counts.values())
    )
    return record


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
    donor_contract = validate_rgb_size(DONOR)
    baseline_contract = validate_rgb_size(V18)
    persistent = (k3.RAW, k3.FINAL, k3.RECEIPT, k3.AUDIT)
    if any(path.exists() for path in persistent):
        raise RuntimeError("persistent K3 output unexpectedly exists")
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty TEMP exploration: {OUT}")

    spec_bytes_before = k3.SPEC.read_bytes()
    spec_sha_before = sha256(k3.SPEC)
    baseline = np.asarray(Image.open(V18).convert("RGB"), np.uint8)
    donor = np.asarray(Image.open(DONOR).convert("RGB"), np.uint8)
    base = k3.validate_source()
    masks = k3.derive_masks()
    permission = masks["highland_edit"]
    registration_mask = k3.erode(permission, 28)
    if not np.any(registration_mask):
        raise RuntimeError("empty strict highland registration core")
    registered_lab, registration = register_lab_median(
        donor, baseline, registration_mask
    )

    alpha = k3.boundary_locked_alpha(
        permission, full_by_px=7.0, locked_boundary_px=2.0
    )
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
    if alpha_record["nonzero_pixels_outside_permission"]:
        raise RuntimeError("boundary alpha escaped highland permission")

    baseline_weave = harness.weave(baseline, permission)
    baseline_activity = float(baseline_weave["activity_fraction"])
    records: dict[str, Any] = {}
    original_save_contacts = harness.save_contacts
    try:
        # Delay review derivatives until the harness and the explicit complete
        # guard identity gate have both passed.
        harness.save_contacts = lambda candidate, directory: {}
        for recipe in RECIPES:
            plate, filtering = variant_plate(registered_lab, recipe)
            rendered = k3.composite_with_alpha(baseline, plate, alpha)
            candidate = baseline.copy()
            candidate[permission] = rendered[permission]
            identity = guard_identity(candidate, baseline, masks)
            method = {
                "semantic_change": "highland permitted interior material only",
                "registration": registration,
                "filtering": filtering,
                "boundary_alpha": alpha_record,
                "source_geometry_authority": "frozen v18 outside highland_edit",
                "donor_geometry_authority": "locked ImageGen full-context raster inside highland_edit",
            }
            lineage = {
                "frozen_v18": frozen[relative(V18)],
                "imagegen_control": frozen[relative(DONOR)],
                "exact_generation_prompt": frozen[relative(PROMPT)],
            }
            record = harness.evaluate(
                str(recipe["name"]),
                candidate,
                base,
                baseline,
                masks,
                baseline_activity,
                method,
                lineage,
            )
            record["road_guard_protected_outside_identity"] = identity
            record["automated_gates"][
                "road_guard_protected_outside_byte_exact"
            ] = identity["passed"]
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
        "status": "TEMP-only broad-landform ImageGen probe; no acceptance authority",
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
            "donor_contract": donor_contract,
            "baseline_contract": baseline_contract,
            "full_gate_harness": {
                "path": relative(HARNESS),
                "sha256": sha256(HARNESS),
            },
        },
        "operation": {
            "registration": registration,
            "boundary_alpha": alpha_record,
            "same_coordinate_full_context": True,
            "crop_resize_rotate_warp": False,
            "candidate_recipes": list(RECIPES),
        },
        "v18_weave": baseline_weave,
        "records": records,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    report_path = OUT / "broad-landform-search.json"
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
                        "orientation": record["weave_reduction"]["orientation"][
                            "global_gradient_orientation_coherence"
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
