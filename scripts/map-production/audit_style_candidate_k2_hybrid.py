#!/usr/bin/env python3
"""Run the fail-closed automated audit for the approved K2 hybrid candidate.

The H4 boundary, B1-palette, exact-clone, and downsample gates are called
unchanged.  Geometry uses the locked K1 warp helper's exact water predicates
and distance implementation, with K2's stricter thresholds applied to all six
reported measures.  The local composite is rebuilt in memory so persisted
edit masks and pre-calibration leakage are independently checked without
rewriting any candidate artifact.

These deterministic proxies do not make a Golden or semantic Vision decision.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any, Sequence

import cv2
import numpy as np
from PIL import Image

import audit_style_candidate_h17 as h17
import audit_style_candidate_h4 as h4


REPO_ROOT = Path(__file__).resolve().parents[2]
JOB_ID = "style-candidate-k-v2-hybrid"
DEFAULT_RAW = REPO_ROOT / f"world/map-production/candidates/{JOB_ID}-raw.png"
DEFAULT_FINAL = REPO_ROOT / f"world/map-production/candidates/{JOB_ID}.png"
DEFAULT_RECEIPT = (
    REPO_ROOT
    / f"world/map-production/prompts/{JOB_ID}.provenance-receipt.json"
)
DEFAULT_REPORT = (
    REPO_ROOT / f"world/map-production/qa/automated/{JOB_ID}.json"
)
GUIDE = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-i-v1-composition-guide.png"
)
B1_REFERENCE = REPO_ROOT / "world/map-production/candidates/style-candidate-b-v1.png"
H4_REFERENCE = h4.DEFAULT_FINAL
VISION_SCHEMA = h4.DEFAULT_VISION_SCHEMA
K1_SOURCE = (
    REPO_ROOT
    / "world/map-production/candidates/style-candidate-k-v1-full-board.png"
)
K2_BUILDER = REPO_ROOT / "scripts/map-production/build_style_candidate_k2_hybrid.py"
H4_AUDITOR = REPO_ROOT / "scripts/map-production/audit_style_candidate_h4.py"
H17_AUDITOR = REPO_ROOT / "scripts/map-production/audit_style_candidate_h17.py"
CONTROL_ROOT = REPO_ROOT / "world/map-production/controls/style-candidate-k-v2-hybrid"
WARP_BASE = CONTROL_ROOT / "k1-geometry-warp-base.png"
WARP_BUILDER = REPO_ROOT / "scripts/map-production/build_style_candidate_k2_geometry_warp.py"
WARP_REPORT = CONTROL_ROOT / "k1-geometry-warp-report.json"
DONOR_ROOT = CONTROL_ROOT
HIGHLAND_DONOR = DONOR_ROOT / "highland-calm-v2.png"
FIELDS_DONOR = DONOR_ROOT / "fields-calm-v2.png"
CAPITAL_DONOR = DONOR_ROOT / "capital-organic-v2.png"
CRISP_CAPITAL = DONOR_ROOT / "crisp-capital-wall-gates-source.png"
PLATE_PROMPT = (
    REPO_ROOT
    / "world/map-production/prompts/style-candidate-k-v2-local-correction-plate.generation.txt"
)
CAPITAL_PROMPT = (
    REPO_ROOT
    / "world/map-production/prompts/style-candidate-k-v2-capital-organic-donor.generation.txt"
)
HIGHLAND_PROMPT = (
    REPO_ROOT
    / "world/map-production/prompts/style-candidate-k-v2-highland-calm-donor.generation.txt"
)
FIELDS_PROMPT = (
    REPO_ROOT
    / "world/map-production/prompts/style-candidate-k-v2-fields-calm-donor.generation.txt"
)
MASK_ROOT = REPO_ROOT / "world/map-production/qa/masks"
MASK_PATHS = {
    "highland": MASK_ROOT / f"{JOB_ID}-highland-edit-mask-v1.png",
    "fields": MASK_ROOT / f"{JOB_ID}-fields-edit-mask-v1.png",
    "capital": MASK_ROOT / f"{JOB_ID}-capital-edit-mask-v1.png",
    "geometry": MASK_ROOT / f"{JOB_ID}-geometry-edit-mask-v1.png",
    "union": MASK_ROOT / f"{JOB_ID}-edit-mask-v1.png",
}

EXPECTED_SIZE = (1536, 1024)
APPROVED_CANDIDATE_SHA256 = (
    "25b8d6211d1f2970cd59af363c521429863c340780d182253d161a951ed9eb92"
)
EXPECTED_SHA256 = {
    "raw": APPROVED_CANDIDATE_SHA256,
    "final": APPROVED_CANDIDATE_SHA256,
    "receipt": "221c9e6385223d10ce3abe19736877c95ce78489d326f516c6fa3f5acce73167",
    "guide": "52f85e45b61bf889de709d8ea9601bd5865d6021bfbc617473a9e957a6ab8bbc",
    "b1": "4d505def78acc752ee2611cb73d112cc9a3048f611cb05233274a1eb2ae42003",
    "h4": "b4fc951af5d29c78bb98b5ee5007395b5fc3c1addc7070d76ac8074545259837",
    "vision_schema": "e31b505baae56dfa8ac1b4995e9355620e516b87f81544a08b83ff0ebb0f32db",
    "k1": "7e769137c90bad26740bdd095f1795ef1f27ec22d3be1db3e8c0423d4f11540a",
    "k2_builder": "f594d686a356b4ca9e041488f5f8cbd3d33d7a9b6cc1ef446b33e10979f7d16c",
    "h4_auditor": "6521883260ed3c979ed974708a402e1d7b60227cb97e6dcbc04693d68e7e612f",
    "h17_auditor": "192a132a36d62e15fbaed19629a1ea0245cb3b966baebd0589f238ab7693b190",
    "warp_base": "c21c5c07515f2bcc11d0ab8e613f3a6e52ec407606cb5afac4f5946579e62e9a",
    "warp_builder": "e1d74785ec90bf5c6b3f14f043e3432142dcd7a9cfb0cf2acb4f4dcd7034c624",
    "warp_report": "5996f71b8cc9ae3de1309f9f32aa33c6653c93ad5271eee8d87afccb5ea9bb2a",
    "highland_donor": "2ada272aa25955f35e445b2fd98b02e171d47a01c185adddde7bb617f6dac1d8",
    "fields_donor": "d92ef6322b59197373d142eca89263376a4072acbf8f09718763c5da4b956a6a",
    "capital_donor": "7cefcbb1cda73e59e97ecfffa44e24684047d9959e41e714f66a6b2c6169f9aa",
    "crisp_capital": "9908e9930b91359976f63873796a3fbbec19405d546a7ca655959e1be1eee504",
    "plate_prompt": "16c3436e3af856c01c372eefd3c673f205264d55ee844390ed2cf504a7f64b29",
    "capital_prompt": "bf6db9f71fea8c75024a51e165399c002dd612f242367a288b79a7557b6761d0",
    "highland_prompt": "8e4597440c25be096fae444a706757b7527dc0c353a67399b711d7a9d5ebd05c",
    "fields_prompt": "5cab7125396709a1dd3328fd18bbe50d525a6264c0fd0a2bc1e6b96e0c90ee12",
    "mask_highland": "59402816ee289913d3e3c7134fc2f3301ffc180271dfcc7994ab0f95f12b7d44",
    "mask_fields": "2fa5471dc6f1cfcaf0201d088f0bd74c4a5fb3b131ed650b6163cbeae7fc6e8a",
    "mask_capital": "bae4f8e266c646e828b5e3bc49cf072bb2f07032d44b4e3169874cd38ca2041d",
    "mask_geometry": "5e98a94f9f35f4c591e8da30247cb7b7078a42f42bfbc8d6aea48ae323acdf8c",
    "mask_union": "a419fd398e5339c7df26c84c5d130fbc6161f7c8d9981e678234a8c7f1156e16",
}

GEOMETRY_THRESHOLDS = {
    "minimum_stable_land_water_agreement": 0.98,
    "minimum_candidate_boundary_within_8px": 0.95,
    "minimum_guide_boundary_within_8px": 0.95,
    "maximum_candidate_boundary_distance_p95_px": 8.0,
    "maximum_guide_boundary_distance_p95_px": 8.0,
}


class K2AuditError(ValueError):
    """Raised when locked K2 audit evidence cannot be reproduced safely."""


def _assert_input(path: Path, expected: str, label: str) -> None:
    try:
        h4._assert_input(path, expected, label)
    except h4.H4AuditError as exc:
        raise K2AuditError(str(exc)) from exc


def _repo_path(value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or "\\" in value or ":" in value or ".." in pure.parts:
        raise K2AuditError(f"receipt path must be repository-relative: {value!r}")
    return REPO_ROOT.joinpath(*pure.parts)


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise K2AuditError(f"cannot load locked helper module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _rgb_array(path: Path) -> np.ndarray:
    with Image.open(path) as opened:
        return np.asarray(opened.convert("RGB"), dtype=np.uint8).copy()


def _mask_array(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    with Image.open(path) as opened:
        opened.load()
        values = np.asarray(opened.convert("L"), dtype=np.uint8).copy()
        record = {
            "mode": opened.mode,
            "width": opened.width,
            "height": opened.height,
            "unique_values": [int(value) for value in np.unique(values)],
        }
    return values > 0, record


def _locked_inputs(
    raw_path: Path,
    final_path: Path,
    receipt_path: Path,
) -> None:
    records = (
        (raw_path, EXPECTED_SHA256["raw"], "K2 raw"),
        (final_path, EXPECTED_SHA256["final"], "K2 review candidate"),
        (receipt_path, EXPECTED_SHA256["receipt"], "K2 provenance receipt"),
        (GUIDE, EXPECTED_SHA256["guide"], "I1 canonical geometry guide"),
        (B1_REFERENCE, EXPECTED_SHA256["b1"], "B1 palette reference"),
        (H4_REFERENCE, EXPECTED_SHA256["h4"], "H4 semantic reference"),
        (VISION_SCHEMA, EXPECTED_SHA256["vision_schema"], "Vision QA schema"),
        (K1_SOURCE, EXPECTED_SHA256["k1"], "K1 source"),
        (K2_BUILDER, EXPECTED_SHA256["k2_builder"], "K2 builder"),
        (H4_AUDITOR, EXPECTED_SHA256["h4_auditor"], "unchanged H4 gates"),
        (H17_AUDITOR, EXPECTED_SHA256["h17_auditor"], "H17 semantic proxies"),
        (WARP_BASE, EXPECTED_SHA256["warp_base"], "K1 geometry-warp base"),
        (WARP_BUILDER, EXPECTED_SHA256["warp_builder"], "K1 warp geometry helper"),
        (WARP_REPORT, EXPECTED_SHA256["warp_report"], "K1 warp report"),
        (HIGHLAND_DONOR, EXPECTED_SHA256["highland_donor"], "highland donor"),
        (FIELDS_DONOR, EXPECTED_SHA256["fields_donor"], "fields donor"),
        (CAPITAL_DONOR, EXPECTED_SHA256["capital_donor"], "capital donor"),
        (CRISP_CAPITAL, EXPECTED_SHA256["crisp_capital"], "capital wall donor"),
        (PLATE_PROMPT, EXPECTED_SHA256["plate_prompt"], "local-correction plate prompt"),
        (CAPITAL_PROMPT, EXPECTED_SHA256["capital_prompt"], "capital donor prompt"),
        (HIGHLAND_PROMPT, EXPECTED_SHA256["highland_prompt"], "highland donor prompt"),
        (FIELDS_PROMPT, EXPECTED_SHA256["fields_prompt"], "fields donor prompt"),
    )
    for name, path in MASK_PATHS.items():
        records += (
            (path, EXPECTED_SHA256[f"mask_{name}"], f"K2 {name} edit mask"),
        )
    for path, expected, label in records:
        _assert_input(path, expected, label)


def _require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise K2AuditError(
            f"K2 receipt changed {label}: expected {expected!r}, got {actual!r}"
        )


def _require_artifact_record(
    record: Any,
    path: Path,
    expected_sha256: str,
    label: str,
) -> None:
    if not isinstance(record, dict):
        raise K2AuditError(f"K2 receipt lacks {label} artifact record")
    _require_equal(record.get("path"), h4._relative(path), f"{label}.path")
    _require_equal(record.get("sha256"), expected_sha256, f"{label}.sha256")
    if _repo_path(record["path"]).resolve() != path.resolve():
        raise K2AuditError(f"K2 receipt {label} resolves outside its locked path")


def validate_receipt(receipt_path: Path = DEFAULT_RECEIPT) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise K2AuditError("K2 provenance receipt is not valid UTF-8 JSON") from exc

    _require_equal(receipt.get("schema_version"), "2.0.0", "schema_version")
    _require_equal(
        receipt.get("id"),
        "style-candidate-k-v2-hybrid-local-repair-provenance",
        "id",
    )
    _require_equal(receipt.get("proof_only"), False, "proof_only")
    _require_equal(
        receipt.get("promotion_state"),
        "review-only-pending-strict-audit-and-root-vision",
        "promotion_state",
    )

    builder = receipt.get("builder")
    if not isinstance(builder, dict):
        raise K2AuditError("K2 receipt lacks builder record")
    _require_equal(builder.get("path"), h4._relative(K2_BUILDER), "builder.path")
    _require_equal(builder.get("sha256"), EXPECTED_SHA256["k2_builder"], "builder.sha256")
    _require_equal(builder.get("seed"), 120260720, "builder.seed")

    inputs = receipt.get("inputs")
    if not isinstance(inputs, dict):
        raise K2AuditError("K2 receipt lacks inputs")
    _require_artifact_record(
        inputs.get("k1_original_source"), K1_SOURCE, EXPECTED_SHA256["k1"], "K1 source"
    )
    warp = inputs.get("k1_geometry_warp_base")
    _require_artifact_record(warp, WARP_BASE, EXPECTED_SHA256["warp_base"], "warp base")
    _require_equal(warp.get("builder_path"), h4._relative(WARP_BUILDER), "warp builder path")
    _require_equal(warp.get("builder_sha256"), EXPECTED_SHA256["warp_builder"], "warp builder SHA-256")
    _require_equal(warp.get("report_path"), h4._relative(WARP_REPORT), "warp report path")
    _require_equal(warp.get("report_sha256"), EXPECTED_SHA256["warp_report"], "warp report SHA-256")
    _require_artifact_record(
        inputs.get("i1_geometry_control"), GUIDE, EXPECTED_SHA256["guide"], "I1 control"
    )
    _require_artifact_record(
        inputs.get("b1_reference"), B1_REFERENCE, EXPECTED_SHA256["b1"], "B1 reference"
    )

    expected_donors = (
        ("highland", HIGHLAND_DONOR, "highland_donor", [930, 0, 1536, 560]),
        ("fields", FIELDS_DONOR, "fields_donor", [940, 470, 1536, 980]),
        ("capital", CAPITAL_DONOR, "capital_donor", [640, 290, 1050, 730]),
        ("capital-wall-gates-only", CRISP_CAPITAL, "crisp_capital", None),
    )
    donors = inputs.get("crop_donors")
    if not isinstance(donors, list) or len(donors) != len(expected_donors):
        raise K2AuditError("K2 receipt must retain exactly four ordered donor records")
    for record, (semantic, path, hash_key, crop) in zip(donors, expected_donors):
        _require_equal(record.get("semantic"), semantic, f"{semantic} donor semantic")
        _require_artifact_record(record, path, EXPECTED_SHA256[hash_key], f"{semantic} donor")
        if crop is not None:
            _require_equal(record.get("crop_xyxy"), crop, f"{semantic} donor crop")

    expected_prompt_lineage = (
        ("full-board local correction plate", PLATE_PROMPT, "plate_prompt"),
        ("capital organic crop donor", CAPITAL_PROMPT, "capital_prompt"),
        ("highland calm crop donor", HIGHLAND_PROMPT, "highland_prompt"),
        ("fields calm crop donor", FIELDS_PROMPT, "fields_prompt"),
    )
    prompt_lineage = inputs.get("imagegen_prompt_lineage")
    if not isinstance(prompt_lineage, list) or len(prompt_lineage) != len(
        expected_prompt_lineage
    ):
        raise K2AuditError("K2 receipt must retain four ordered ImageGen prompt records")
    for record, (role, prompt_path, hash_key) in zip(
        prompt_lineage, expected_prompt_lineage
    ):
        _require_equal(record.get("role"), role, f"{role} prompt role")
        _require_equal(
            record.get("prompt_path"), h4._relative(prompt_path), f"{role} prompt path"
        )
        _require_equal(
            record.get("prompt_sha256"), EXPECTED_SHA256[hash_key], f"{role} prompt SHA-256"
        )
        generated_source = record.get("original_generated_source_path")
        if not isinstance(generated_source, str) or not generated_source.startswith(
            "C:/Users/User/.codex/generated_images/"
        ):
            raise K2AuditError(f"K2 receipt lost original generated source for {role}")
    _require_equal(
        inputs.get("imagegen_metadata_limits"),
        {
            "exact_model": "unavailable",
            "snapshot": "unavailable",
            "generation_ids": "unavailable",
            "inference_forbidden": True,
        },
        "ImageGen metadata limits",
    )

    receipt_masks = receipt.get("masks")
    if not isinstance(receipt_masks, dict) or set(receipt_masks) != set(MASK_PATHS):
        raise K2AuditError("K2 receipt mask set changed")
    for name, path in MASK_PATHS.items():
        _require_artifact_record(
            receipt_masks[name], path, EXPECTED_SHA256[f"mask_{name}"], f"{name} mask"
        )

    outputs = receipt.get("outputs")
    if not isinstance(outputs, dict):
        raise K2AuditError("K2 receipt lacks outputs")
    _require_artifact_record(
        outputs.get("raw"), DEFAULT_RAW, EXPECTED_SHA256["raw"], "raw output"
    )
    _require_artifact_record(
        outputs.get("review_candidate"),
        DEFAULT_FINAL,
        EXPECTED_SHA256["final"],
        "review output",
    )
    _require_equal(outputs["raw"].get("bytes"), DEFAULT_RAW.stat().st_size, "raw bytes")
    _require_equal(
        outputs["review_candidate"].get("bytes"), DEFAULT_FINAL.stat().st_size, "review bytes"
    )
    _require_equal(
        outputs["review_candidate"].get("raw_byte_identity"), True, "raw byte identity"
    )

    construction = receipt.get("construction")
    if not isinstance(construction, dict):
        raise K2AuditError("K2 receipt lacks construction record")
    required_construction = {
        "canvas": [1536, 1024],
        "mode": "RGB",
        "no_final_board_upscale": True,
        "imagegen_calls_by_this_builder": 0,
        "upstream_imagegen_calls_with_verbatim_prompts": 4,
        "whole_board_synthesis": False,
    }
    for key, expected in required_construction.items():
        _require_equal(construction.get(key), expected, f"construction.{key}")
    local = construction.get("local_change_budget_before_style_calibration")
    if not isinstance(local, dict):
        raise K2AuditError("K2 receipt lacks pre-style local-change metrics")
    _require_equal(local.get("outside_allowed_mask_changed_pixels"), 0, "pre-style leakage pixels")
    _require_equal(local.get("outside_allowed_mask_max_channel_delta"), 0, "pre-style leakage delta")
    style = construction.get("style_calibration")
    if not isinstance(style, dict):
        raise K2AuditError("K2 receipt lacks style-calibration record")
    for key in (
        "spatial_pixel_reassignment",
        "histogram_or_cdf_matching",
        "palette_quantization",
    ):
        _require_equal(style.get(key), False, f"style_calibration.{key}")
    fields = construction.get("fields")
    if not isinstance(fields, dict) or not isinstance(fields.get("parcels"), list):
        raise K2AuditError("K2 receipt lacks field parcel records")
    _require_equal(
        [item.get("parcel") for item in fields["parcels"]],
        list(range(1, 9)),
        "field parcel identifiers",
    )
    capital = construction.get("capital")
    if not isinstance(capital, dict):
        raise K2AuditError("K2 receipt lacks capital record")
    for key, expected in {
        "outer_wall_center_xy": [842, 510],
        "outer_wall_radius_px": 138,
        "exact_gate_count": 5,
        "complete_interior_rings_added": 0,
        "uniform_radial_spokes_added": 0,
    }.items():
        _require_equal(capital.get(key), expected, f"capital.{key}")
    geometry = construction.get("geometry_linework")
    if not isinstance(geometry, dict):
        raise K2AuditError("K2 receipt lacks geometry-linework record")
    _require_equal(geometry.get("maximum_line_width_px"), 2, "geometry line width")
    _require_equal(
        geometry.get("warped_water_and_port_pixels_changed"), 0, "water/port geometry edits"
    )

    assertions = receipt.get("assertions")
    required_assertions = {
        "k1_geometry_warp_is_byte_source_base": True,
        "donors_confined_to_named_masks": True,
        "no_broad_water_or_land_projection": True,
        "no_cloudy_low_frequency_synthesis": True,
        "no_global_cdf_or_multiset_palette_mapping": True,
        "style_calibration_has_no_spatial_pixel_reassignment": True,
        "maximum_canonical_line_width_px": 2,
        "exact_field_parcel_count": 8,
        "capital_exact_outer_wall_and_five_gates": True,
        "manifest_untouched": True,
        "docs_untouched": True,
        "renderer_untouched": True,
        "golden_accepted": False,
    }
    if not isinstance(assertions, dict):
        raise K2AuditError("K2 receipt lacks assertions")
    for key, expected in required_assertions.items():
        _require_equal(assertions.get(key), expected, f"assertions.{key}")

    return receipt, {
        "passed": True,
        "receipt_sha256_locked": True,
        "builder_sha256_locked": True,
        "ordered_donor_count": len(donors),
        "ordered_verbatim_prompt_count": len(prompt_lineage),
        "imagegen_calls_by_this_builder": construction["imagegen_calls_by_this_builder"],
        "upstream_imagegen_calls_with_verbatim_prompts": construction[
            "upstream_imagegen_calls_with_verbatim_prompts"
        ],
        "no_final_board_upscale": construction["no_final_board_upscale"],
        "spatial_pixel_reassignment": style["spatial_pixel_reassignment"],
        "histogram_or_cdf_matching": style["histogram_or_cdf_matching"],
        "golden_accepted": assertions["golden_accepted"],
        "promotion_state": receipt["promotion_state"],
    }


def _image_contract(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    required = {
        "format": "PNG",
        "mode": "RGB",
        "width": EXPECTED_SIZE[0],
        "height": EXPECTED_SIZE[1],
        "bit_depth": 8,
        "png_color_type": 2,
        "alpha_or_transparency_present": False,
    }
    record_results = {
        name: all(record[key] == value for key, value in required.items())
        for name, record in records.items()
    }
    reference_profile = h4._profile_signature(records["reference_b1"])
    profile_matches = all(
        h4._profile_signature(record) == reference_profile
        for record in records.values()
    )
    return {
        "passed": all(record_results.values()) and profile_matches,
        "required": required,
        "records_passed": record_results,
        "profile_matches_b1": profile_matches,
        "images": records,
    }


def _capital_permission(builder: ModuleType, base: np.ndarray, masks: dict[str, Any]) -> np.ndarray:
    yy, xx = np.mgrid[0 : EXPECTED_SIZE[1], 0 : EXPECTED_SIZE[0]]
    old_radius = np.hypot(xx - 858.0, yy - 506.0)
    new_radius = np.hypot(xx - 842.0, yy - 510.0)
    gray = cv2.cvtColor(base, cv2.COLOR_RGB2GRAY)
    local_background = cv2.medianBlur(gray, 9)
    old_wall_ink = (
        (np.abs(old_radius - 135.0) <= 3.0)
        & (new_radius > 143.0)
        & ((local_background.astype(np.int16) - gray.astype(np.int16)) >= 7)
    )
    old_wall_ink &= ~builder.dilate(masks["road_edge"], 5)
    inner = new_radius <= 132.0
    annulus = (new_radius >= 131.0) & (new_radius <= 143.0)
    northwest_bastion = ((xx - 746.0) ** 2 + (yy - 409.0) ** 2) <= 18.0**2
    portals = np.zeros((EXPECTED_SIZE[1], EXPECTED_SIZE[0]), np.uint8)
    for point in ((842, 372), (704, 511), (980, 510), (842, 648), (932, 607)):
        cv2.circle(portals, point, 13, 255, -1, cv2.LINE_8)
    crisp = (annulus | (portals > 0)) & ~northwest_bastion
    wall = np.zeros_like(portals)
    cv2.circle(wall, (842, 510), 138, 255, 1, cv2.LINE_AA)
    gates = builder.line_mask(
        [
            [(842, 372), (842, 394)],
            [(704, 511), (728, 511)],
            [(980, 510), (956, 510)],
            [(842, 648), (842, 624)],
            [(932, 607), (918, 589)],
        ],
        1,
    )
    return old_wall_ink | inner | crisp | (wall > 0) | gates


def reconstruct_local_composite(
    receipt: dict[str, Any],
    final_path: Path = DEFAULT_FINAL,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rebuild the pre-style composite and prove masks/output independently."""

    builder = _load_module(K2_BUILDER, "locked_k2_hybrid_builder_for_audit")
    base = _rgb_array(WARP_BASE)
    masks = builder.canonical_masks()
    canvas = base.copy()
    highland_crop = builder.crop_resize(HIGHLAND_DONOR, builder.CROPS["highland"])
    fields_crop = builder.crop_resize(FIELDS_DONOR, builder.CROPS["fields"])
    capital_crop = builder.crop_resize(CAPITAL_DONOR, builder.CROPS["capital"])
    crisp_capital = _rgb_array(CRISP_CAPITAL)

    highland_edit, highland_record = builder.apply_highland(
        canvas, base, highland_crop, masks
    )
    fields_edit, fields_record = builder.apply_fields(canvas, base, fields_crop, masks)
    capital_edit, capital_record = builder.apply_capital(
        canvas, base, capital_crop, crisp_capital, masks
    )
    geometry_edit, geometry_record = builder.apply_geometry_linework(canvas, base, masks)
    components = {
        "highland": highland_edit,
        "fields": fields_edit,
        "capital": capital_edit,
        "geometry": geometry_edit,
    }
    union = np.logical_or.reduce(list(components.values()))

    road_guard = builder.dilate(masks["road_edge"], 12)
    field_edges = np.zeros_like(union)
    for points in builder.FIELDS:
        field_edges |= builder.line_mask([points], 1, closed=True) & ~road_guard
    permissions = {
        "highland": (
            masks["highland"]
            & ~builder.dilate(masks["road_edge"], 12)
            & ~builder.dilate(masks["city"], 5)
        ),
        "fields": (masks["field_union"] & ~road_guard) | field_edges,
        "capital": _capital_permission(builder, base, masks),
        "geometry": builder.line_mask(builder.ROADS, 2),
    }
    allowed_union = np.logical_or.reduce(list(permissions.values()))

    mask_checks: dict[str, dict[str, Any]] = {}
    persisted_masks: dict[str, np.ndarray] = {}
    for name in (*components, "union"):
        persisted, png_record = _mask_array(MASK_PATHS[name])
        expected = union if name == "union" else components[name]
        persisted_masks[name] = persisted
        mask_checks[name] = {
            **png_record,
            "changed_pixels": int(expected.sum()),
            "byte_exact_boolean_identity": bool(np.array_equal(persisted, expected)),
            "binary_0_255": png_record["unique_values"] in ([0], [0, 255], [255]),
        }

    component_leakage = {
        name: {
            "changed_pixels": int(changed.sum()),
            "allowed_pixels": int(permissions[name].sum()),
            "outside_allowed_pixels": int((changed & ~permissions[name]).sum()),
            "passed": not bool(np.any(changed & ~permissions[name])),
        }
        for name, changed in components.items()
    }
    actual_changed = np.any(canvas != base, axis=2)
    local_metrics = builder.changed_metrics(base, canvas, allowed_union)
    operation_records_match = {
        "highland": highland_record == receipt["construction"]["highland"],
        "fields": fields_record == receipt["construction"]["fields"],
        "capital": capital_record == receipt["construction"]["capital"],
        "geometry": geometry_record == receipt["construction"]["geometry_linework"],
    }
    receipt_local_metrics_match = (
        local_metrics
        == receipt["construction"]["local_change_budget_before_style_calibration"]
    )

    b1 = _rgb_array(B1_REFERENCE)
    calibrated, style_record = builder.gentle_style_calibration(canvas, b1)
    approved = _rgb_array(final_path)
    calibrated_delta = np.abs(calibrated.astype(np.int16) - approved.astype(np.int16))
    final_reproduced = bool(np.array_equal(calibrated, approved))

    local_passed = all(
        item["byte_exact_boolean_identity"] and item["binary_0_255"]
        for item in mask_checks.values()
    )
    local_passed &= all(item["passed"] for item in component_leakage.values())
    local_passed &= bool(np.array_equal(actual_changed, union))
    local_passed &= not bool(np.any(actual_changed & ~allowed_union))
    local_passed &= all(operation_records_match.values())
    local_passed &= receipt_local_metrics_match
    local_passed &= final_reproduced
    local_passed &= style_record == receipt["construction"]["style_calibration"]

    parcel_pixels = [int((fields_edit & parcel).sum()) for parcel in masks["fields"]]
    semantic_contract = {
        "passed": bool(
            len(masks["fields"]) == 8
            and len(parcel_pixels) == 8
            and all(value > 0 for value in parcel_pixels)
            and component_leakage["highland"]["passed"]
            and component_leakage["capital"]["passed"]
            and receipt["construction"]["capital"]["exact_gate_count"] == 5
            and receipt["construction"]["capital"]["complete_interior_rings_added"] == 0
            and receipt["construction"]["capital"]["uniform_radial_spokes_added"] == 0
        ),
        "method": (
            "locked-builder reconstruction plus exact canonical permission masks; "
            "artistic calmness and motif semantics remain Vision-only"
        ),
        "semantic_claim": None,
        "fields": {
            "canonical_parcel_count": len(masks["fields"]),
            "nonempty_edited_parcel_count": sum(value > 0 for value in parcel_pixels),
            "edited_pixels_per_parcel": parcel_pixels,
            "outside_canonical_permission_pixels": component_leakage["fields"]["outside_allowed_pixels"],
        },
        "highland": {
            "edited_pixels": int(highland_edit.sum()),
            "permission_pixels": int(permissions["highland"].sum()),
            "outside_canonical_permission_pixels": component_leakage["highland"]["outside_allowed_pixels"],
        },
        "capital": {
            "edited_pixels": int(capital_edit.sum()),
            "outside_canonical_permission_pixels": component_leakage["capital"]["outside_allowed_pixels"],
            "outer_wall_center_xy": receipt["construction"]["capital"]["outer_wall_center_xy"],
            "outer_wall_radius_px": receipt["construction"]["capital"]["outer_wall_radius_px"],
            "exact_gate_count": receipt["construction"]["capital"]["exact_gate_count"],
            "complete_interior_rings_added": receipt["construction"]["capital"]["complete_interior_rings_added"],
            "uniform_radial_spokes_added": receipt["construction"]["capital"]["uniform_radial_spokes_added"],
        },
    }

    summary = {
        "passed": bool(local_passed),
        "method": (
            "deterministic in-memory reconstruction from the locked builder and "
            "locked donors; no candidate or contact artifact is written"
        ),
        "persisted_mask_checks": mask_checks,
        "component_permission_leakage": component_leakage,
        "union_matches_actual_pre_style_delta": bool(np.array_equal(actual_changed, union)),
        "outside_independent_allowed_union_pixels": int((actual_changed & ~allowed_union).sum()),
        "pre_style_metrics": local_metrics,
        "receipt_pre_style_metrics_match": receipt_local_metrics_match,
        "operation_records_match_receipt": operation_records_match,
        "style_record_matches_receipt": style_record
        == receipt["construction"]["style_calibration"],
        "approved_final_reproduced_pixel_exactly": final_reproduced,
        "approved_final_differing_pixels": int(np.any(calibrated_delta > 0, axis=2).sum()),
        "approved_final_max_channel_delta": int(calibrated_delta.max()),
    }
    return summary, semantic_contract


def strict_geometry_pass(metrics: dict[str, Any]) -> bool:
    return bool(
        metrics["stable_land_water_agreement"]
        >= GEOMETRY_THRESHOLDS["minimum_stable_land_water_agreement"]
        and metrics["candidate_boundary_within_8px"]
        >= GEOMETRY_THRESHOLDS["minimum_candidate_boundary_within_8px"]
        and metrics["guide_boundary_within_8px"]
        >= GEOMETRY_THRESHOLDS["minimum_guide_boundary_within_8px"]
        and metrics["candidate_boundary_distance_p95_px"]
        <= GEOMETRY_THRESHOLDS["maximum_candidate_boundary_distance_p95_px"]
        and metrics["guide_boundary_distance_p95_px"]
        <= GEOMETRY_THRESHOLDS["maximum_guide_boundary_distance_p95_px"]
    )


def geometry_metrics(guide: Image.Image, candidate: Image.Image) -> dict[str, Any]:
    warp_helper = _load_module(WARP_BUILDER, "locked_k1_geometry_warp_for_k2_audit")
    guide_array = np.asarray(guide, dtype=np.uint8)
    candidate_array = np.asarray(candidate, dtype=np.uint8)
    metrics = warp_helper.geometry_metrics(
        warp_helper.guide_water_mask(guide_array),
        warp_helper.k1_water_mask(candidate_array),
    )
    metrics["passed"] = strict_geometry_pass(metrics)
    metrics["thresholds"] = GEOMETRY_THRESHOLDS
    metrics["method"] = (
        "locked K1 warp helper: fixed guide/candidate cool-water segmentation, "
        "17px transition guard, and bidirectional L2 distance transforms"
    )
    metrics["helper"] = h4._artifact(WARP_BUILDER)
    metrics["limitation"] = (
        "This color-segmentation proxy covers land/water and its boundary. Root "
        "Vision must still inspect exact roads, city, port, and semantic regions."
    )
    return metrics


def _vision_handoff() -> dict[str, Any]:
    return {
        "status": "required-pending-root-vision",
        "schema": h4._artifact(VISION_SCHEMA),
        "automated_audit_is_not_vision": True,
        "automated_audit_is_not_golden_acceptance": True,
        "required_focus": [
            "fields: independent broken marks, nonperiodic drift, calm gaps, and no CAD or wallpaper cadence",
            "highland: broad planar tone, sparse short independent hatches, and no chains or contours",
            "capital: irregular shared-boundary fabric, varied tiny footprints, one exact outer wall, and five exact junctions",
            "water and forest: sparse print material, quiet gaps, no connected cells, loops, glyphs, or repeated stamps",
            "exact coast, islands, river/delta, roads, city, port footprint, seams, text or pseudo-text, plan projection, and borderless edges",
        ],
    }


def audit(
    *,
    final_path: Path = DEFAULT_FINAL,
    raw_path: Path = DEFAULT_RAW,
    receipt_path: Path = DEFAULT_RECEIPT,
    report_path: Path = DEFAULT_REPORT,
    replace: bool = False,
) -> dict[str, Any]:
    if report_path.exists() and not replace:
        raise K2AuditError(f"refusing to overwrite existing output: {report_path}")
    _locked_inputs(raw_path, final_path, receipt_path)
    receipt, provenance = validate_receipt(receipt_path)
    raw_final_identity = h4.files_are_byte_identical(raw_path, final_path)

    records: dict[str, dict[str, Any]] = {}
    images: dict[str, Image.Image] = {}
    for name, path in (
        ("raw", raw_path),
        ("final", final_path),
        ("reference_b1", B1_REFERENCE),
        ("reference_h4", H4_REFERENCE),
    ):
        records[name], images[name] = h4.inspect_png(path)
    guide = Image.open(GUIDE).convert("RGB")
    try:
        image_contract = _image_contract(records)
        boundary = h4.boundary_metrics(images["final"])
        palette = h4.palette_continuity_metrics(
            images["final"], images["reference_b1"]
        )
        repetition = h4.exact_repetition_metrics(images["final"])
        downsample = h4.downsample_readability_metrics(images["final"])
        semantic_repetition = h17.semantic_repetition_proxies(
            images["final"], images["reference_h4"]
        )
        geometry = geometry_metrics(guide, images["final"])
    finally:
        guide.close()
        for image in images.values():
            image.close()

    local_reconstruction, semantic_contract = reconstruct_local_composite(
        receipt, final_path
    )
    automated_gates = {
        "sha256_locked_inputs": True,
        "raw_final_byte_identity": raw_final_identity,
        "locked_provenance_receipt": provenance["passed"],
        "image_contract_alpha_profile": image_contract["passed"],
        "pre_style_local_mask_leakage_and_reconstruction": local_reconstruction["passed"],
        "boundary_proxy_unchanged_h4": boundary["passed"],
        "palette_continuity_with_b1_unchanged_h4": palette["passed"],
        "no_large_exact_repetition_proxy_unchanged_h4": repetition["passed"],
        "downsample_readability_proxy_unchanged_h4": downsample["passed"],
        "semantic_repetition_proxies_vs_h4": semantic_repetition["passed"],
        "field_highland_capital_structural_contract": semantic_contract["passed"],
        "strict_canonical_geometry_alignment": geometry["passed"],
    }
    failed_gates = [name for name, passed in automated_gates.items() if not passed]
    report = {
        "schema_version": "1.0.0",
        "id": f"{JOB_ID}-automated-audit",
        "status": "passed" if not failed_gates else "failed",
        "scope": "automated locked-artifact, provenance, raster, and geometry proxies only",
        "decision": (
            "automated-gates-passed-pending-root-vision"
            if not failed_gates
            else "automated-gates-failed-pending-root-vision-decision"
        ),
        "failed_gates": failed_gates,
        "decision_authority": False,
        "formal_qa": False,
        "golden_accepted": False,
        "manifest_mutation": False,
        "docs_mutation": False,
        "renderer_mutation": False,
        "generated_by": h4._artifact(Path(__file__).resolve()),
        "artifacts": {
            "raw": h4._artifact(raw_path),
            "final_review_candidate": {
                **h4._artifact(final_path),
                "review_only": True,
                "accepted": False,
            },
            "provenance_receipt": h4._artifact(receipt_path),
            "deterministic_builder": h4._artifact(K2_BUILDER),
            "canonical_geometry_guide": h4._artifact(GUIDE),
            "reference_b1": h4._artifact(B1_REFERENCE),
            "reference_h4": h4._artifact(H4_REFERENCE),
            "geometry_warp_base": h4._artifact(WARP_BASE),
            "edit_masks": {
                name: h4._artifact(path) for name, path in MASK_PATHS.items()
            },
        },
        "identity": {
            "passed": raw_final_identity,
            "raw_final_byte_identical": raw_final_identity,
            "approved_sha256": APPROVED_CANDIDATE_SHA256,
        },
        "provenance": provenance,
        "image_contract": image_contract,
        "local_pre_style_reconstruction": local_reconstruction,
        "boundary": boundary,
        "palette_continuity_with_b1": palette,
        "exact_repetition": repetition,
        "downsample_readability": downsample,
        "semantic_repetition_proxies_vs_h4": semantic_repetition,
        "field_highland_capital_contract": semantic_contract,
        "guide_geometry_alignment": geometry,
        "automated_gates": automated_gates,
        "vision_handoff": _vision_handoff(),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final", type=Path, default=DEFAULT_FINAL)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="replace an existing report after re-running every locked check",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = audit(
            final_path=args.final.resolve(),
            raw_path=args.raw.resolve(),
            receipt_path=args.receipt.resolve(),
            report_path=args.report.resolve(),
            replace=args.replace,
        )
    except (K2AuditError, OSError, ValueError) as exc:
        print(f"Candidate K2 hybrid automated audit failed: {exc}")
        return 1
    geometry = report["guide_geometry_alignment"]
    print(
        f"Candidate K2 hybrid status={report['status']} "
        f"sha256={report['artifacts']['final_review_candidate']['sha256']} "
        f"stable={geometry['stable_land_water_agreement']} "
        f"within8={geometry['candidate_boundary_within_8px']}/"
        f"{geometry['guide_boundary_within_8px']} "
        f"p95={geometry['candidate_boundary_distance_p95_px']}/"
        f"{geometry['guide_boundary_distance_p95_px']}"
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
