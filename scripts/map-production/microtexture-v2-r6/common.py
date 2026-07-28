"""Shared r6 trust root, operational blind, one-shot loaders, and Git preflight."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import platform
import re
import subprocess
import sys
import unicodedata
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import numpy._core._multiarray_umath as numpy_core_binary
import scipy
import scipy.ndimage._nd_image as scipy_ndimage_binary
from PIL import _imaging as pillow_imaging_binary
from PIL import __version__ as pillow_version

from metrics_v2_r6 import (
    METRIC_FIELDS,
    RAW_INTEGER_FIELDS,
    REFERENCE_KEYS,
    SCORE_FIELDS,
    recompute_branch_scores,
)


CODE_ROOT = Path(__file__).resolve().parent
SPEC_PATH = CODE_ROOT / "preregistered-spec.json"
# Replaced with the final byte hash only after every authority file is frozen.
SPEC_SHA256 = "9de51e74c8aec518b2b9c6f08201244f06eaf3df9ceba61907efad4044ea6587"
BINDINGS_PATH = CODE_ROOT / "implementation-bindings.json"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def require_exact_keys(value: Any, keys: set[str], context: str) -> None:
    actual = set(value) if isinstance(value, dict) else set()
    if not isinstance(value, dict) or actual != keys:
        raise RuntimeError(
            f"{context} keyset drift: missing={sorted(keys - actual)}, "
            f"extra={sorted(actual - keys)}"
        )


def require_exact_int(value: Any, context: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise RuntimeError(f"{context} must be an exact integer >= {minimum}")
    return value


def require_exact_real(
    value: Any,
    context: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise RuntimeError(f"{context} must be a finite real number (bool forbidden)")
    result = float(value)
    if minimum is not None and result < minimum:
        raise RuntimeError(f"{context} must be >= {minimum}")
    if maximum is not None and result > maximum:
        raise RuntimeError(f"{context} must be <= {maximum}")
    return result


ENDPOINT_DEFINITION_KEYS = {
    "id",
    "population",
    "expected_result",
    "minimum_unique_clusters",
    "calibration_minimum",
    "holdout_minimum",
}
EXPECTED_ENDPOINT_IDS = [
    "clean_acceptance",
    "warning_acceptance",
    "reject_detection",
    "severity3_detection",
    "grain_reject_detection",
    "tiny_speck_reject_detection",
    "microblob_reject_detection",
    "spot_reject_detection",
    "short_line_reject_detection",
    "parallel_bundle_reject_detection",
]
EXPECTED_ENDPOINT_DEFINITIONS = [
    {
        "id": "clean_acceptance",
        "population": "disposition_clean",
        "expected_result": "accept",
        "minimum_unique_clusters": 15,
        "calibration_minimum": 0.95,
        "holdout_minimum": 0.95,
    },
    {
        "id": "warning_acceptance",
        "population": "disposition_warning",
        "expected_result": "accept",
        "minimum_unique_clusters": 10,
        "calibration_minimum": 0.75,
        "holdout_minimum": 0.75,
    },
    {
        "id": "reject_detection",
        "population": "disposition_reject",
        "expected_result": "reject",
        "minimum_unique_clusters": 30,
        "calibration_minimum": 0.95,
        "holdout_minimum": 0.95,
    },
    {
        "id": "severity3_detection",
        "population": "severity_3",
        "expected_result": "reject",
        "minimum_unique_clusters": 4,
        "calibration_minimum": 1.0,
        "holdout_minimum": 1.0,
    },
    {
        "id": "grain_reject_detection",
        "population": "grain_visible_reject",
        "expected_result": "reject",
        "minimum_unique_clusters": 8,
        "calibration_minimum": 0.80,
        "holdout_minimum": 0.75,
    },
    {
        "id": "tiny_speck_reject_detection",
        "population": "tiny_speck_visible_reject",
        "expected_result": "reject",
        "minimum_unique_clusters": 4,
        "calibration_minimum": 0.75,
        "holdout_minimum": 0.75,
    },
    {
        "id": "microblob_reject_detection",
        "population": "microblob_visible_reject",
        "expected_result": "reject",
        "minimum_unique_clusters": 4,
        "calibration_minimum": 0.75,
        "holdout_minimum": 0.75,
    },
    {
        "id": "spot_reject_detection",
        "population": "spot_visible_reject",
        "expected_result": "reject",
        "minimum_unique_clusters": 8,
        "calibration_minimum": 0.80,
        "holdout_minimum": 0.75,
    },
    {
        "id": "short_line_reject_detection",
        "population": "short_line_visible_reject",
        "expected_result": "reject",
        "minimum_unique_clusters": 8,
        "calibration_minimum": 0.80,
        "holdout_minimum": 0.75,
    },
    {
        "id": "parallel_bundle_reject_detection",
        "population": "parallel_bundle_visible_reject",
        "expected_result": "reject",
        "minimum_unique_clusters": 6,
        "calibration_minimum": 0.80,
        "holdout_minimum": 0.75,
    },
]
CONTACT_SHEET_VIEW_KEYS = {"id", "scale_percent", "source_crop_xywh"}
CONTACT_SHEET_KEYS = {
    "views",
    "resize",
    "columns",
    "rows_per_page",
    "panel_dimensions",
    "label_height",
    "sheet_mode",
    "sheet_background_l",
    "label_band_position",
    "label_origin_in_slot",
    "panel_origin_in_slot",
    "label_panel_overlap_forbidden",
    "label_fill_l",
    "label_font",
    "sheet_dimensions",
    "expected_controls_per_split",
    "expected_pages_per_view",
    "expected_pages_per_split",
    "all_220_source_panels_unique_in_every_view",
    "all_four_400_percent_quadrants_required",
    "label_binding",
}
CONTACT_SHEET_LABEL_FONT = (
    "fixed built-in 3x5 lowercase hexadecimal bitmap, scale 2, one scale-unit "
    "column gap"
)
CONTACT_SHEET_LABEL_BINDING = (
    "manifest SHA plus exact ordered full path, SHA, and item-code bundle "
    "regenerated from secret-derived controls"
)
PUBLIC_PRE_MARKER_VALIDATION = (
    "schema, authority bindings, code coverage, completeness, reviewed-view "
    "booleans, per-record disposition/severity/visible consistency, canonical ev3 "
    "evidence syntax, public flag/evidence binding, tiny-speck cardinality, and "
    "parallel l/p locator binding only; image-hash equality and private sentinel "
    "membership must not be used to correct labels before consumption"
)
VISION_SEMANTIC_RUBRIC = {
    "id": "microtexture-v2-r6-injected-morphology-only/3",
    "application": "apply identically to every anonymous record before reveal",
    "judgment_target": (
        "synthetic morphology visibly distinct from the permitted clean substrate; "
        "absolute nonuniformity alone is not an artifact"
    ),
    "native_clean_variation": (
        "broad edge-free low-frequency nonperiodic parchment clouding, smooth mottling, "
        "gentle tone drift, and sparse isolated soft irregular low-contrast organic "
        "flecks remain clean and set no visible flag; a faint diffuse or soft-edged "
        "pinprick first noticed only at 400 percent is also clean"
    ),
    "cross_scale_evidence_gate": (
        "count a morphology only when it is directly visible without enhancement in "
        "the full-200 panel and can be reidentified at the same location in the "
        "corresponding 400-percent quadrant; 400-percent-only impressions set no flag"
    ),
    "grain_visible": (
        "dense or coherent periodic/directional high-frequency texture beyond broad "
        "permitted mottling"
    ),
    "tiny_speck_visible": (
        "at least three independently locatable separated point-like hard cores of "
        "similar footprint and polarity; every counted core is uniquely locatable at "
        "400 percent, returns toward local background in every direction within roughly "
        "one core width, is clearly sharper or higher contrast than the soft substrate, "
        "and matches the same visible center at full-200; diffuse, feathered, irregular "
        "soft flecks, solitary cores, and mere tonal extrema are excluded"
    ),
    "microblob_visible": (
        "localized compact blobs with separable centers or boundaries; broad edge-free "
        "low-frequency permitted clouding is excluded"
    ),
    "short_line_visible": (
        "discrete straight finite dashes or lines; smooth tonal contours and permitted "
        "fiber-like variation are excluded"
    ),
    "parallel_bundle_visible": (
        "true only when one candidate pair satisfies every condition: each of two "
        "same-polarity non-touching finite strokes is independently visible in "
        "full-200; both strokes can be reidentified together in one corresponding "
        "400-percent quadrant; the pair uses one shared evidence locator whose "
        "3-by-3 sector is selected by the midpoint between the two stroke midpoints "
        "and the strokes need not be wholly contained in that sector; the minimum "
        "undirected centerline-angle difference modulo 180 degrees is at most 10 "
        "degrees; the minimum edge-to-edge perpendicular gap is greater than zero "
        "and no greater than the arithmetic mean of the two visible centerline "
        "lengths; and overlap of the two centerline projections on their mean axis "
        "is at least 50 percent of the shorter visible centerline length. Scattered, "
        "crossing, touching, merged, opposite-polarity, or merely similarly angled "
        "dashes are insufficient"
    ),
    "parallel_bundle_implies_short_line": True,
    "flags_nonexclusive": True,
    "positive_flag_evidence_recording": (
        "for every true visible flag, notes identify the evidence that is visible in "
        "full-200 and reidentified in the corresponding 400-percent quadrant; tiny "
        "speck identifies at least three distinct locations; a parallel bundle uses "
        "the same pair-midpoint locator for l and p; inability to record required "
        "evidence leaves the flag false"
    ),
    "evidence_notes_contract": {
        "exact_form": "ev3:g=<set>;t=<set>;b=<set>;l=<set>;p=<set>",
        "locator_form": "(NW|NE|SW|SE)-R[1-3]C[1-3]-N(01..99)",
        "locator_meaning": (
            "the quadrant and 3-by-3 sector reidentifying the same evidence in "
            "full-200 and the corresponding 400-percent view; N is a record-local "
            "distinct evidence ordinal and may distinguish multiple centers in one "
            "sector"
        ),
        "empty_set": "-",
        "canonicalization": (
            "ASCII only; clauses occur exactly once in g,t,b,l,p order; no "
            "whitespace, free text, trailing delimiter, duplicate locator, or "
            "noncanonical locator order; locator order is NW,NE,SW,SE then row, "
            "column, ordinal"
        ),
        "flag_binding": (
            "a false visible flag requires '-' and a true visible flag requires a "
            "nonempty locator set"
        ),
        "tiny_speck_cardinality": ("t=true requires at least three distinct locators"),
        "parallel_binding": (
            "p=true requires l=true and every p locator must occur identically in "
            "the l locator set"
        ),
        "clean_binding": "clean requires exactly ev3:g=-;t=-;b=-;l=-;p=-",
    },
    "warning": (
        "an observed morphology that passes every applicable evidence predicate but "
        "is weak, severity 1; warning is not an uncertainty category"
    ),
    "reject_severity_2": (
        "clearly visible localized or repeated synthetic morphology, severity 2"
    ),
    "reject_severity_3": (
        "dominant, high-contrast, or field-wide synthetic morphology, severity 3"
    ),
    "recording_protocol": (
        "record and verify every decision against the exact printed anonymous code "
        "before moving to the next page; delayed page-row-only transcription is "
        "forbidden"
    ),
    "blind_prohibitions": (
        "source/reference/hash/diff/family/role/polarity/sentinel/duplicate inference "
        "or comparison is forbidden before label sealing"
    ),
    "private_audit_policy": (
        "private sentinel checks occur only after marker and label sealing; failure "
        "closes the edition and never authorizes relabeling"
    ),
}

POPULATION_ANCHOR_SCHEDULE = {
    "revision": "dev-r8-soft-unit-schedule-v1",
    "fresh_from_closed_dev_r7": True,
    "r7_parameter_nonce_reuse_forbidden": True,
    "r8_per_family_residue_rotation": {
        "calibration": {
            "artifact-fine-grain": 1,
            "artifact-speck": 3,
            "artifact-microblob": 5,
            "artifact-short-dash": 7,
            "artifact-parallel-bundle": 9,
        },
        "holdout": {
            "artifact-fine-grain": 2,
            "artifact-speck": 4,
            "artifact-microblob": 6,
            "artifact-short-dash": 8,
            "artifact-parallel-bundle": 10,
        },
    },
    "r8_parameter_nonce_bases": {
        "calibration_artifact": 73000,
        "holdout_artifact": 83000,
        "calibration_protocol_zero": 51000,
        "holdout_protocol_zero": 61000,
        "calibration_duplicate_audit": [91000, 91001, 91002],
        "holdout_duplicate_audit": [101000, 101001, 101002],
    },
    "private_until_one_shot_marker": True,
    "public_manifest_exposure_forbidden": True,
    "generation_design_tiers_are_truth": False,
    "tier_counts_per_artifact_family": {
        "clean-candidate": 5,
        "warning-candidate": 4,
        "clear-reject-candidate": 7,
        "dominant-reject-candidate": 4,
    },
    "artifact_families_covered": [
        "artifact-fine-grain",
        "artifact-speck",
        "artifact-microblob",
        "artifact-short-dash",
        "artifact-parallel-bundle",
    ],
    "tier_variant_index_modulo_three_residues_per_family": [0, 1, 2],
    "all_100_artifact_clusters_reviewed_and_evaluated": True,
    "subset_selection_forbidden": True,
    "top_up_forbidden": True,
    "replacement_forbidden": True,
    "key_resampling_forbidden": True,
    "actual_sealed_vision_labels_are_decisive": True,
    "blind_key_selection_forbidden_for": [
        "split",
        "family",
        "generation-design-tier",
        "variant-index",
        "parameter-tuple",
    ],
    "blind_key_allowed_uses": [
        "foundation-assignment",
        "private-reference-transform",
        "sparse-placement-within-frozen-packing-invariants",
        "private-identities-and-anonymous-codes",
        "public-record-order",
    ],
    "development_premeasurement_safety_floor_formula": (
        "max(M+2,ceil(1.25*M)) for each unchanged formal endpoint minimum M"
    ),
    "development_premeasurement_safety_floors": {
        "clean_acceptance": 19,
        "warning_acceptance": 13,
        "reject_detection": 38,
        "severity3_detection": 6,
        "grain_reject_detection": 10,
        "tiny_speck_reject_detection": 6,
        "microblob_reject_detection": 6,
        "spot_reject_detection": 10,
        "short_line_reject_detection": 10,
        "parallel_bundle_reject_detection": 8,
    },
}

RENDERING_INVARIANTS = {
    "hard_speck_integer_core_contract": (
        "artifact-speck uses an unblurred exact one-pixel core at an integer-lattice "
        "center whose unsigned requested-delta peak equals amplitude_l; "
        "shoulder_fraction is tier-bound to clean=0, warning=0.05, and both reject "
        "tiers=0.08 on only the four axial neighbours; every encoded core remains "
        "the unique local extremum of its polarity"
    ),
    "hard_speck_separation_contract": (
        "artifact-speck requires minimum_separation_px at least 10 and integer "
        "centers whose pairwise Chebyshev separation is at least that frozen "
        "parameter, so core and optional four-neighbour supports are disjoint with "
        "uninjected pixels between them"
    ),
    "hard_speck_quadrant_stratification_contract": (
        "artifact-speck integer centers use deterministic round-robin packing "
        "across the four exact metric-window quadrants with quadrant counts differing "
        "by at most one; a count of at least four covers every quadrant"
    ),
    "microblob_separation_contract": (
        "artifact-microblob uses integer centers and a finite Gaussian truncated at "
        "explicit support_radius_px; minimum_separation_px is at least "
        "2*support_radius_px+1, supports have a positive uninjected gap, and every "
        "center has unsigned requested-delta peak amplitude_l"
    ),
    "parallel_geometry_contract": (
        "each artifact-parallel-bundle pair uses an exact 0- or 90-degree axis, "
        "equal even-integer length_px, even-integer centerline spacing_px, zero axial "
        "offset and therefore 100 percent axial overlap; edge gap equals "
        "spacing_px-width_px and satisfies 1<=gap<=length_px; every same-polarity "
        "non-touching pair is wholly contained in exactly one 400-percent quadrant"
    ),
    "sparse_deterministic_packing_contract": (
        "speck, microblob, short-dash, and parallel-bundle centers use a bounded "
        "deterministic candidate permutation and deterministic first-fit acceptance "
        "stratified across the four exact quadrants with count difference at most "
        "one; short-dash separation is at least ceil(length_px)+width_px+3 and "
        "parallel-bundle separation is at least "
        "max(length_px,spacing_px)+width_px+3; failure to place the full requested "
        "count raises without adaptive count, parameter, tier, split, or key "
        "replacement"
    ),
}


def validate_contact_sheet_view_partition(
    settings: Any, metric_window_xywh: Any
) -> None:
    context = "r6 contact-sheet views"
    if (
        not isinstance(metric_window_xywh, list)
        or len(metric_window_xywh) != 4
        or any(type(value) is not int for value in metric_window_xywh)
    ):
        raise RuntimeError(f"{context} metric window must use exact integers")
    mx, my, metric_width, metric_height = metric_window_xywh
    if (
        mx < 0
        or my < 0
        or metric_width <= 0
        or metric_height <= 0
        or metric_width % 2
        or metric_height % 2
    ):
        raise RuntimeError(f"{context} metric window cannot be quartered exactly")
    if not isinstance(settings, dict):
        raise RuntimeError(f"{context} settings must be an object")
    require_exact_keys(settings, CONTACT_SHEET_KEYS, context)
    views = settings.get("views")
    if not isinstance(views, list) or len(views) != 5:
        raise RuntimeError(f"{context} must contain exactly five views")
    half_width, half_height = metric_width // 2, metric_height // 2
    expected = [
        ("full-200", 200, [mx, my, metric_width, metric_height]),
        ("northwest-400", 400, [mx, my, half_width, half_height]),
        (
            "northeast-400",
            400,
            [mx + half_width, my, half_width, half_height],
        ),
        (
            "southwest-400",
            400,
            [mx, my + half_height, half_width, half_height],
        ),
        (
            "southeast-400",
            400,
            [mx + half_width, my + half_height, half_width, half_height],
        ),
    ]
    normalized: list[tuple[str, int, list[int]]] = []
    for index, view in enumerate(views):
        require_exact_keys(view, CONTACT_SHEET_VIEW_KEYS, f"{context}[{index}]")
        view_id = view["id"]
        scale = view["scale_percent"]
        crop = view["source_crop_xywh"]
        if (
            not isinstance(view_id, str)
            or not view_id
            or type(scale) is not int
            or not isinstance(crop, list)
            or len(crop) != 4
            or any(type(value) is not int for value in crop)
        ):
            raise RuntimeError(f"{context}[{index}] exact type contract drift")
        normalized.append((view_id, scale, crop))
    if normalized != expected:
        raise RuntimeError(f"{context} exact id/order/scale/crop drift")
    panel = settings.get("panel_dimensions")
    if (
        not isinstance(panel, list)
        or len(panel) != 2
        or any(type(value) is not int or value <= 0 for value in panel)
    ):
        raise RuntimeError(f"{context} panel dimensions must be exact integers")
    panel_width, panel_height = panel
    for view_id, scale, (_, _, width, height) in normalized:
        if width * scale != panel_width * 100 or height * scale != panel_height * 100:
            raise RuntimeError(f"{context} {view_id} does not exactly fill its panel")
    if (
        settings.get("columns") != 2
        or settings.get("rows_per_page") != 3
        or settings.get("label_height") != 30
        or settings.get("sheet_mode") != "L"
        or settings.get("sheet_background_l") != 238
        or settings.get("label_band_position") != "above-panel"
        or settings.get("label_origin_in_slot") != [8, 18]
        or settings.get("panel_origin_in_slot") != [0, 30]
        or settings.get("label_panel_overlap_forbidden") is not True
        or settings.get("label_fill_l") != 0
        or settings.get("label_font") != CONTACT_SHEET_LABEL_FONT
        or settings.get("sheet_dimensions") != [1024, 1242]
        or settings.get("label_binding") != CONTACT_SHEET_LABEL_BINDING
    ):
        raise RuntimeError(f"{context} exact above-panel layout drift")
    if (
        settings.get("resize") != "nearest"
        or settings.get("all_four_400_percent_quadrants_required") is not True
    ):
        raise RuntimeError(f"{context} resize/quadrant requirement drift")
    coverage = np.zeros((metric_height, metric_width), dtype=np.uint8)
    for view_id, _, (left, top, width, height) in normalized[1:]:
        relative_left, relative_top = left - mx, top - my
        if (
            relative_left < 0
            or relative_top < 0
            or relative_left + width > metric_width
            or relative_top + height > metric_height
        ):
            raise RuntimeError(f"{context} {view_id} escapes the metric window")
        coverage[
            relative_top : relative_top + height,
            relative_left : relative_left + width,
        ] += 1
    if coverage.size != metric_width * metric_height or not np.all(coverage == 1):
        raise RuntimeError(f"{context} quadrants have overlap or gaps")


def validate_preregistered_spec(value: dict[str, Any]) -> None:
    history = value.get("history")
    if not isinstance(history, dict):
        raise RuntimeError("r6 development history must be an object")
    if (
        history.get("dev_r6_status") != "failed-and-closed-before-measurement"
        or history.get("dev_r6_role")
        != "development-only premeasurement population-feasibility failure evidence; "
        "the one-shot edition closed before any numeric measurement, and no dev-r6 "
        "key, control, label, identity, placement, parameter schedule, metric, "
        "threshold, or artifact root is reusable"
        or history.get("dev_r7_status") != "failed-and-closed-after-measurement"
        or history.get("dev_r7_role")
        != "development-only score-saturation failure evidence; both splits passed "
        "the population gate, measurement ran once, no endpoint-admissible threshold "
        "existed, and no dev-r7 key, control, label, pixel, identity, measurement, "
        "threshold diagnostic, parameter nonce, or artifact root is reusable"
        or history.get("dev_r7_failure_audit")
        != "world/map-production/qa/microtexture-v2-r6-dev-r7-development-failure.json"
        or history.get("dev_r7_failure_audit_sha256")
        != "00ab198c5e0be28775436d22927e9bd8523304f41e2c310d6e81c0cf2ea7131f"
        or history.get("dev_r8_status") != "fresh-development-only"
        or history.get("dev_r8_role")
        != "fresh one-shot development role used only to verify the preregistered "
        "soft-unit metric and revision-3 schedule before formal r6 generation; it "
        "requires a tracked runner, a fresh isolated root, a fresh cryptographic "
        "blind key, revision-3 public and parameter nonces, newly generated controls "
        "and anonymous identities, and fresh sealed Root plus independent Vision "
        "labels, and it can never become or supply formal authority"
    ):
        raise RuntimeError("r6 closed-development provenance contract drift")
    roots = value.get("roots")
    expected_root_keys = {
        "blind_key_environment",
        "blind_key_format",
        "formal_blind_key_operational_requirement",
        "formal_blind_key_artifact_or_log_persistence_forbidden",
        "artifact_root_environment",
        "artifact_root_required_repo_relative",
        "code_root_required_repo_relative",
        "code_root_policy",
    }
    require_exact_keys(roots, expected_root_keys, "r6 roots")
    if roots["formal_blind_key_artifact_or_log_persistence_forbidden"] is not True:
        raise RuntimeError("r6 formal blind-key persistence contract drift")
    expected_development_secret_handling = {
        "scope": "non-authority dev-r8 only; no development key, root, output, or commitment can become formal authority",
        "fresh_key_generation": "secrets.token_bytes(32) inside the tracked development runner",
        "ignored_private_key_required_repo_relative": "tmp/map-production/microtexture-v2-r6-dev-r8/private/development-key.bin",
        "gitignore_required_repo_relative": ".gitignore",
        "gitignore_required_pattern": "/tmp*/",
        "gitignore_must_be_tracked_and_worktree_bytes_must_match_captured_head": True,
        "ignored_private_key_must_be_absent_from_head_and_index_and_git_ignored": True,
        "ignored_private_key_persistence_required_for_one_shot_analysis_and_closed_postmortem": True,
        "key_value_logging_or_git_tracking_forbidden": True,
        "vision_process_key_read_or_inheritance_forbidden": True,
        "same_principal_attack_non_claim_applies": True,
        "closed_private_root_retained_for_forensic_reproducibility": True,
        "key_reuse_in_any_successor_or_formal_operation_forbidden": True,
    }
    if (
        value.get("development_probe_secret_handling")
        != expected_development_secret_handling
    ):
        raise RuntimeError("r6 development blind-key persistence contract drift")
    selection = value.get("threshold_selection")
    if not isinstance(selection, dict):
        raise RuntimeError("r6 threshold_selection must be an object")
    gate = selection.get("hard_gate")
    require_exact_keys(
        gate,
        {"metric", "direction", "threshold_count", "complete_hard_composite"},
        "r6 hard gate spec",
    )
    if (
        gate["metric"] != "hard_composite_score"
        or gate["direction"] != "maximum"
        or require_exact_int(gate["threshold_count"], "hard threshold_count", 1) != 1
        or not isinstance(gate["complete_hard_composite"], str)
    ):
        raise RuntimeError("r6 single hard-gate contract drift")
    admissibility = selection.get("admissibility")
    require_exact_keys(
        admissibility,
        {
            "clean_cluster_acceptance_minimum",
            "warning_cluster_acceptance_minimum",
        },
        "r6 threshold admissibility",
    )
    for field in (
        "clean_cluster_acceptance_minimum",
        "warning_cluster_acceptance_minimum",
    ):
        require_exact_real(
            admissibility[field],
            f"threshold admissibility {field}",
            minimum=0.0,
            maximum=1.0,
        )
    if selection.get("endpoint_truth_aggregation") != {
        "unit": "artifact-condition-cluster",
        "members_per_cluster": 2,
        "disposition_precedence": ["reject", "warning", "clean"],
        "severity_aggregation": "maximum",
        "visible_flag_aggregation": "logical-or",
        "metric_equivalent_polarity_pair_prediction": "single-shared-prediction",
    }:
        raise RuntimeError("r6 endpoint truth aggregation contract drift")
    if selection.get("authority_candidate_gate") != {
        "all_endpoint_count_passed_required": True,
        "all_endpoint_rate_passed_required": True,
        "diagnostic_admissibility_scope": "clean-warning-only",
        "diagnostic_best_authority_forbidden": True,
        "diagnostic_best_location": "threshold-selection-audit-only",
        "no_candidate_status": "no-endpoint-admissible-threshold",
        "population_feasibility_order": "post-marker-post-label-seal-"
        "post-private-audit-pre-measurement-pre-threshold-selection",
        "population_failure_policy": "raise a post-marker failure before numeric "
        "measurement; consume and close the edition without a frozen threshold",
    }:
        raise RuntimeError("r6 endpoint authority-candidate contract drift")
    if selection.get("selection_status_state_machine") != {
        "no-endpoint-admissible-threshold": {
            "hard_threshold": None,
            "passed": False,
            "freeze_forbidden": True,
        },
        "selected-and-passed": {
            "hard_threshold": "selected nonnegative scalar",
            "passed": True,
            "freeze_required": True,
        },
    }:
        raise RuntimeError("r6 selection status state-machine drift")
    if "no_admissible_report_binding" in selection:
        raise RuntimeError("r6 legacy no-admissible report binding is forbidden")
    if selection.get("no_endpoint_admissible_report_binding") != {
        "hard_threshold": None,
        "passed": False,
        "endpoint_performance_and_results_source": "diagnostic-best-candidate",
        "diagnostic_threshold_location": "threshold-selection-audit-only",
        "threshold_file_forbidden": True,
    }:
        raise RuntimeError("r6 no-endpoint-admissible report binding is missing")
    endpoints = selection.get("endpoint_definitions")
    if not isinstance(endpoints, list) or [item.get("id") for item in endpoints] != (
        EXPECTED_ENDPOINT_IDS
    ):
        raise RuntimeError("r6 endpoint id/order contract drift")
    populations: set[str] = set()
    for index, endpoint in enumerate(endpoints):
        require_exact_keys(endpoint, ENDPOINT_DEFINITION_KEYS, f"endpoint[{index}]")
        if (
            not isinstance(endpoint["population"], str)
            or not endpoint["population"]
            or endpoint["population"] in populations
            or endpoint["expected_result"] not in {"accept", "reject"}
        ):
            raise RuntimeError(f"endpoint[{index}] population/result contract drift")
        populations.add(endpoint["population"])
        require_exact_int(
            endpoint["minimum_unique_clusters"],
            f"endpoint[{index}] minimum_unique_clusters",
            1,
        )
        for split in ("calibration", "holdout"):
            require_exact_real(
                endpoint[f"{split}_minimum"],
                f"endpoint[{index}] {split}_minimum",
                minimum=0.0,
                maximum=1.0,
            )
    if endpoints != EXPECTED_ENDPOINT_DEFINITIONS:
        raise RuntimeError("r6 endpoint count/rate contract drift")
    contact = value.get("contact_sheets")
    if not isinstance(contact, dict) or not isinstance(contact.get("views"), list):
        raise RuntimeError("r6 contact-sheet spec must define views")
    validate_contact_sheet_view_partition(
        contact, value["canvas"]["metric_window"]["xywh"]
    )
    for field, expected in (
        ("expected_controls_per_split", 220),
        ("expected_pages_per_view", 37),
        ("expected_pages_per_split", 185),
    ):
        if (
            require_exact_int(contact.get(field), f"contact_sheets.{field}", 1)
            != expected
        ):
            raise RuntimeError(f"contact_sheets.{field} contract drift")
    label_paths = value.get("labels", {}).get("exact_artifact_paths")
    if label_paths != {
        "calibration": "controls/calibration/labels-calibration.json",
        "holdout": "controls/holdout/labels-holdout.json",
    }:
        raise RuntimeError("r6 exact reviewed-label artifact paths drift")
    sealed_label_paths = value.get("labels", {}).get("sealed_authority_paths")
    if sealed_label_paths != {
        "calibration": "sealed-inputs/calibration-reviewed-labels.json",
        "holdout": "sealed-inputs/holdout-reviewed-labels.json",
    }:
        raise RuntimeError("r6 sealed reviewed-label authority paths drift")
    corpus = value.get("foundation_corpus")
    require_exact_keys(
        corpus,
        {
            "role",
            "source_dimensions",
            "vision_qualification_minimum_score",
            "source_crop_xywh",
            "metric_window_xywh_within_source_crop",
            "rgb_to_l",
            "foundations",
            "generation_chain",
            "generation_chain_sha256",
            "generation_receipt",
            "generation_receipt_sha256",
            "root_vision_review",
            "root_vision_review_sha256",
            "independent_vision_reviews",
            "rejected_candidates_forbidden",
            "foundation_assignment",
            "formal_preflight",
        },
        "r6 foundation corpus",
    )
    if (
        corpus["source_dimensions"] != [1536, 1024]
        or corpus["vision_qualification_minimum_score"] != 94
        or corpus["source_crop_xywh"] != [512, 320, 512, 384]
        or corpus["metric_window_xywh_within_source_crop"] != [128, 96, 256, 192]
        or corpus["rejected_candidates_forbidden"] != []
    ):
        raise RuntimeError("r6 foundation geometry/rejection contract drift")
    foundations = corpus["foundations"]
    if (
        not isinstance(foundations, list)
        or [item.get("id") for item in foundations] != ["v15", "v16", "v17"]
        or any(set(item) != {"id", "path", "sha256"} for item in foundations)
        or any(
            re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None
            for item in foundations
        )
    ):
        raise RuntimeError("r6 foundation source binding drift")
    reviews = corpus["independent_vision_reviews"]
    if (
        not isinstance(reviews, list)
        or len(reviews) != 2
        or any(set(item) != {"path", "sha256"} for item in reviews)
        or any(
            re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None for item in reviews
        )
    ):
        raise RuntimeError("r6 foundation independent review binding drift")
    definition = value.get("metric_definition")
    if not isinstance(definition, dict):
        raise RuntimeError("r6 metric definition must be an object")
    references = definition.get("score_reference_constants")
    require_exact_keys(references, REFERENCE_KEYS, "r6 score references")
    for key in REFERENCE_KEYS:
        require_exact_real(references[key], f"r6 score reference {key}", minimum=1e-12)
    if references != {
        "grain_occupancy_per_mp": 2400.0,
        "grain_rms_l": 0.875,
        "tiny_mass_l": 15.0,
        "tiny_component_count": 9.0,
        "multiscale_blob_strength_l_sqrt_px": 4.0,
        "finite_line_peak_l": 4.5,
        "finite_line_top4_mean_l": 2.25,
        "parallel_pair_peak_l": 4.5,
        "parallel_matched_pair_count": 2.0,
    }:
        raise RuntimeError("r6 soft-unit reference revision drift")
    if (
        definition.get("score_reference_revision") != "dev-r8-soft-unit-robustness-v1"
        or definition.get("score_reference_changes_from_closed_dev_r7")
        != {
            "grain_rms_l": {"from": 0.7, "to": 0.875},
            "tiny_mass_l": {"from": 20.0, "to": 15.0},
            "finite_line_top4_mean_l": {"from": 4.5, "to": 2.25},
        }
        or definition.get("score_reference_revision_guardrails")
        != {
            "basis": "aggregate-only closed dev-r7 development diagnostics before "
            "fresh dev-r8 generation",
            "single_reference_candidates_passed": 0,
            "two_reference_candidates_passed": 1,
            "chosen_three_reference_diagnostic_threshold": 0.7027857840028129,
            "chosen_three_reference_calibration_score_gap": 0.025614718437003,
            "chosen_three_reference_holdout_score_gap": 0.025614718437003,
            "chosen_third_reference_purpose": "increase the minimum calibration/"
            "holdout decision-boundary distance without changing endpoint results",
            "raw_metrics_unchanged": True,
            "branch_composition_unchanged": True,
            "endpoint_counts_and_rates_unchanged": True,
            "fresh_dev_r8_required": True,
            "dev_r7_threshold_or_measurement_reuse_for_formal_forbidden": True,
        }
    ):
        raise RuntimeError("r6 soft-unit reference provenance drift")
    if (
        definition.get("hard_metric")
        != {
            "name": "hard_composite_score",
            "formula": "max(grain_score, spot_score, finite_line_score, parallel_bundle_score)",
            "direction": "maximum",
        }
        or definition.get("raw_metric_recomputation_required") is not True
        or definition.get("parallel_pair_ratio_diagnostic_only") is not True
        or definition.get("diagnostic_branch_flag_cutoff") != 0.5
        or definition.get("artifact_dependent_score_denominators_forbidden") is not True
        or definition.get("score_normalization")
        != "unit_soft(x, reference)=0 when x<=0 else (2/pi)*atan(x/reference), "
        "where reference is a frozen fixed half-scale and every finite positive "
        "input maps strictly monotonically into (0,1); grain=max(min(unit_soft "
        "occupancy,unit_soft rms),coherence_0_to_1*unit_soft rms); spot=max(unit_soft "
        "tiny mass,unit_soft tiny component count,unit_soft multiscale blob); "
        "finite-line=max(unit_soft peak,unit_soft top4); parallel=min(unit_soft "
        "absolute weaker-pair peak,unit_soft matched-pair count); hard=max four "
        "branches"
    ):
        raise RuntimeError("r6 hard composite definition drift")
    expected_metric_parameters = {
        "grain_parameters": {
            "highpass_sigma_px": 4.0,
            "absolute_floor_l": 3.0,
            "coherence_low_sigma_px": 0.6,
            "coherence_high_sigma_px": 2.5,
            "coherence_min_period_px": 2,
            "coherence_max_period_px": 13,
            "coherence_angles_degrees": list(range(0, 180, 15)),
        },
        "spot_parameters": {
            "component_floor_l": 4.5,
            "tiny_area_max_pixels": 12,
            "tiny_top_count": 9,
            "blob_area_min_pixels": 4,
            "blob_area_max_pixels": 400,
            "blob_elongation_maximum": 2.5,
            "blob_sigmas_px": [0.8, 1.2, 1.8, 2.6, 3.6],
        },
        "finite_line_parameters": {
            "angles_degrees": list(range(0, 180, 15)),
            "lengths_px": [5, 9, 15, 23],
            "core_half_width_px": 0.5,
            "flank_inner_px": 1.0,
            "flank_outer_px": 4.0,
            "nms_size_px": 5,
            "response_floor_l": 4.5,
            "peaks_per_filter": 64,
            "duplicate_peak_radius_px": 4,
        },
        "parallel_pair_parameters": {
            "response_floor_l": 4.5,
            "peaks_per_filter": 64,
            "nms_size_px": 5,
            "minimum_matched_pair_count": 2,
            "along_maximum_px": 15.5,
            "perpendicular_minimum_px": 4.0,
            "perpendicular_maximum_px": 24.0,
        },
    }
    if (
        definition.get("density_unit_pixels") != 1_000_000
        or definition.get("gaussian_mode") != "reflect"
        or definition.get("gaussian_truncate") != 4.0
        or any(
            definition.get(name) != expected
            for name, expected in expected_metric_parameters.items()
        )
        or definition.get("parallel_pair_response_source")
        != "absolute normalized core-only raw-delta line mean; finite-line "
        "center-surround flank responses are forbidden as parallel evidence"
        or definition.get("parallel_pair_evidence_coupling")
        != "pair peak and greedy matched-pair count must come from the same "
        "angle/length filter and same matching; fewer than two matched pairs is "
        "canonical zero bundle evidence; select the single filter maximizing its "
        "actual bounded parallel score with deterministic tie-breaks"
    ):
        raise RuntimeError("r6 frozen metric parameter drift")
    one_shot = value.get("one_shot_failure_reporting", {})
    if (
        one_shot.get("completion_report_schema")
        != "microtexture-v2-r6-stage-completion/2"
        or one_shot.get("completion_report_paths")
        != {
            "calibration": "completions/calibration.json",
            "locked-clean-reference": "completions/locked-clean-reference.json",
            "holdout": "completions/holdout.json",
        }
        or one_shot.get("completion_exact_binding_fields")
        != [
            "manifest_sha256",
            "labels_sha256",
            "frozen_thresholds_sha256",
            "threshold_authority_receipt_sha256",
            "locked_clean_reference_sha256",
        ]
        or one_shot.get("completion_is_exclusive_final_stage_operation") is not True
        or one_shot.get("normal_endpoint_failure_writes_passed_false_completion")
        is not True
        or one_shot.get(
            "authority_loaders_require_completion_and_reject_failure_coexistence"
        )
        is not True
        or one_shot.get(
            "terminal_authority_reload_after_completion_required_for_all_stages"
        )
        is not True
    ):
        raise RuntimeError("r6 final stage-completion contract drift")
    if (
        value.get("holdout_pass_targets", {}).get(
            "terminal_report_authority_reload_required"
        )
        is not True
        or value.get("public_identity_policy", {}).get(
            "authority_reload_secret_rebinding_required"
        )
        is not True
    ):
        raise RuntimeError("r6 terminal authority reload contract drift")
    if (
        value.get("locked_clean_reference", {}).get(
            "vision_qualification_minimum_score"
        )
        != 94
    ):
        raise RuntimeError("r6 locked-clean Vision qualification threshold drift")
    locked_revalidation = value.get("locked_clean_reference", {}).get(
        "holdout_preflight_revalidation"
    )
    require_exact_keys(
        locked_revalidation,
        {
            "required_at",
            "exact_path_fields",
            "requirements",
            "numeric_measurement_forbidden",
        },
        "locked-clean holdout preflight revalidation",
    )
    if (
        locked_revalidation["required_at"]
        != ["holdout-control-generation", "holdout-evaluation-before-marker"]
        or locked_revalidation["exact_path_fields"]
        != [
            "repo_relative_path",
            "generation_chain",
            "generation_receipt",
            "root_vision_review",
            "independent_vision_review",
        ]
        or locked_revalidation["requirements"]
        != [
            "tracked at the current receipt HEAD",
            "working bytes identical to that HEAD",
            "SHA-256 identical to this preregistration",
        ]
        or locked_revalidation["numeric_measurement_forbidden"] is not True
    ):
        raise RuntimeError("locked-clean holdout preflight contract drift")
    anchor_schedule = value.get("population_anchor_schedule")
    if anchor_schedule != POPULATION_ANCHOR_SCHEDULE:
        raise RuntimeError("r6 private population-anchor schedule drift")
    formal_minima = {
        endpoint["id"]: int(endpoint["minimum_unique_clusters"])
        for endpoint in EXPECTED_ENDPOINT_DEFINITIONS
    }
    derived_safety_floors = {
        endpoint_id: max(minimum + 2, math.ceil(1.25 * minimum))
        for endpoint_id, minimum in formal_minima.items()
    }
    if (
        anchor_schedule["development_premeasurement_safety_floors"]
        != derived_safety_floors
        or sum(anchor_schedule["tier_counts_per_artifact_family"].values()) != 20
        or len(anchor_schedule["artifact_families_covered"]) != 5
    ):
        raise RuntimeError("r6 population-anchor arithmetic/cardinality drift")

    rendering = value.get("rendering")
    rendering_keys = {
        "quantization",
        "requested_delta_hash",
        "encoded_png_hash",
        "public_payload_binding",
        "public_commitment_domain",
        "commitment_equality_hiding",
        "single_read_validation",
        "sparse_injection_domain",
        "artifact_nonzero_contract",
        "sparse_parameter_crossing_contract",
        "fine_grain_contract",
        "sparse_position_contract",
        "hard_speck_integer_core_contract",
        "hard_speck_separation_contract",
        "hard_speck_quadrant_stratification_contract",
        "microblob_separation_contract",
        "parallel_geometry_contract",
        "sparse_deterministic_packing_contract",
        "protocol_zero_contract",
        "duplicate_audit_contract",
    }
    require_exact_keys(rendering, rendering_keys, "r6 rendering contract")
    if any(
        rendering.get(key) != expected for key, expected in RENDERING_INVARIANTS.items()
    ):
        raise RuntimeError("r6 rendering invariant drift")
    if (
        rendering.get("commitment_equality_hiding")
        != "domain separation plus the opaque code makes all 660 commitments unique "
        "even when private requested deltas repeat; repeated or cross-lane "
        "commitments are rejected"
        or rendering.get("artifact_nonzero_contract")
        != "all 100 artifact clusters encode a nonzero requested delta and a "
        "control that differs from its reference; zero-count conditions are "
        "forbidden from artifact endpoint populations"
        or rendering.get("sparse_parameter_crossing_contract")
        != "the 20 conditions in every sparse family cross count, size or length, "
        "amplitude, width, and spacing through frozen nonmonotone permutations; "
        "calibration and holdout use different offsets and nonce ranges"
    ):
        raise RuntimeError("r6 rendering population cardinality drift")

    cluster = value.get("independent_condition_clusters")
    if not isinstance(cluster, dict):
        raise RuntimeError("private cluster contract must be an object")
    for field, expected in (
        ("expected_unique_clusters_per_split", 118),
        ("expected_protocol_zero_clusters_per_split", 16),
        ("expected_duplicate_audit_clusters_per_split", 2),
        ("expected_artifact_clusters_per_split", 100),
        ("expected_artifact_clusters_per_family", 20),
    ):
        if require_exact_int(cluster.get(field), field, 1) != expected:
            raise RuntimeError(f"private cluster contract drift: {field}")
    if cluster.get("identity_includes") != [
        "split",
        "public_nonce",
        "private_role",
        "family",
        "variant_index",
        "parameters",
        "duplicate_audit_group",
        "foundation_id",
    ] or cluster.get("identity_excludes") != ["polarity", "replicate"]:
        raise RuntimeError("private cluster identity contract drift")

    labels_contract = value.get("labels", {})
    if labels_contract.get("vision_observation_rubric") != VISION_SEMANTIC_RUBRIC:
        raise RuntimeError("r6 Vision observation rubric drift")
    private_audits = labels_contract.get("post_marker_private_audits")
    if (
        labels_contract.get("public_pre_marker_validation")
        != PUBLIC_PRE_MARKER_VALIDATION
        or not isinstance(private_audits, dict)
        or set(private_audits)
        != {
            "ordering",
            "protocol_zero",
            "duplicate_clean",
            "duplicate_artifact",
            "failure_policy",
        }
        or any(
            not isinstance(item, str) or not item for item in private_audits.values()
        )
    ):
        raise RuntimeError("r6 private Vision audit contract drift")

    catalog = value.get("control_catalog_authority")
    if not isinstance(catalog, dict):
        raise RuntimeError("r6 control catalog authority must be an object")
    require_exact_keys(
        catalog,
        {
            "exact_variant_source",
            "records_per_split",
            "private_role_records_per_split",
            "artifact_contract",
            "protocol_zero_contract",
            "duplicate_audit_contract",
            "split_separation",
            "foundation_assignment",
            "private_reference_transform",
        },
        "r6 control catalog authority",
    )
    if require_exact_int(
        catalog.get("records_per_split"), "catalog records", 1
    ) != 220 or catalog.get("private_role_records_per_split") != {
        "artifact": 200,
        "protocol-zero": 16,
        "duplicate-audit": 4,
    }:
        raise RuntimeError("r6 control catalog cardinality drift")
    if catalog.get("artifact_contract") != (
        "five morphology families, exactly 20 nonzero conditions per family, paired "
        "dark/light polarities, one replicate per polarity, and no zero-count "
        "artifact condition"
    ):
        raise RuntimeError("r6 artifact catalog contract drift")
    if catalog.get("split_separation") != (
        "calibration and holdout use disjoint public nonces, parameter nonces, "
        "HMAC identities, opaque codes, control ids, and nonzero requested-delta "
        "hashes; exact-zero sentinels intentionally share the canonical all-zero "
        "requested-delta hash"
    ):
        raise RuntimeError("r6 split-separation contract drift")
    if catalog.get("private_reference_transform") != {
        "primitive": "full-output HMAC-SHA-256 counter-mode PRF coefficient grids",
        "identity": "full private record identity including polarity and replicate",
        "control_grid_hw": [7, 9],
        "maximum_displacement_px": 1.75,
        "maximum_tone_l": 0.75,
        "interpolation_order": 1,
        "coefficient_interpolation_order": 3,
        "boundary_mode": "reflect",
        "encoded_luminance_minimum": 16,
        "encoded_luminance_maximum": 243,
        "public_reference_files_forbidden": True,
        "all_220_private_reference_hashes_unique": True,
        "all_220_public_control_hashes_unique": True,
        "purpose": (
            "remove exact byte-level known-foundation, control/reference equality, "
            "pair-midpoint, and duplicate-equality oracles from the review surface "
            "while preserving a visually clean locally warped foundation; this is "
            "defense in depth, not a claim that visible morphology is "
            "cryptographically hidden"
        ),
    }:
        raise RuntimeError("r6 private reference-transform contract drift")

    expected_families = {
        "artifact-fine-grain": ("artifact", [-1, 1], 20, 40),
        "artifact-speck": ("artifact", [-1, 1], 20, 40),
        "artifact-microblob": ("artifact", [-1, 1], 20, 40),
        "artifact-short-dash": ("artifact", [-1, 1], 20, 40),
        "artifact-parallel-bundle": ("artifact", [-1, 1], 20, 40),
        "protocol-zero": ("protocol-zero", [1], 16, 16),
        "duplicate-audit": ("duplicate-audit", [1], 2, 4),
    }
    families = value.get("control_families")
    if not isinstance(families, list) or len(families) != len(expected_families):
        raise RuntimeError("r6 control family catalog drift")
    family_ids = [family.get("id") for family in families if isinstance(family, dict)]
    if len(family_ids) != len(families) or set(family_ids) != set(expected_families):
        raise RuntimeError("r6 control family id drift")
    for family in families:
        family_id = family["id"]
        private_role, polarities, clusters, records = expected_families[family_id]
        base_keys = {
            "id",
            "private_role",
            "polarities",
            "expected_clusters_per_split",
            "expected_records_per_split",
        }
        expected_keys = (
            base_keys | {"replicates_per_cluster", "groups"}
            if family_id == "duplicate-audit"
            else base_keys
        )
        require_exact_keys(family, expected_keys, f"r6 family {family_id}")
        if (
            family["private_role"] != private_role
            or family["polarities"] != polarities
            or require_exact_int(
                family["expected_clusters_per_split"],
                f"{family_id} clusters",
                1,
            )
            != clusters
            or require_exact_int(
                family["expected_records_per_split"],
                f"{family_id} records",
                1,
            )
            != records
        ):
            raise RuntimeError(f"r6 family contract drift: {family_id}")
        if family_id == "duplicate-audit" and (
            family["replicates_per_cluster"] != 2
            or family["groups"] != ["clean", "artifact"]
        ):
            raise RuntimeError("r6 duplicate-audit family contract drift")
    for split_name in ("calibration", "holdout"):
        split_contract = value.get("splits", {}).get(split_name, {})
        if (
            split_contract.get("public_nonce") != f"r6-{split_name}-v3"
            or split_contract.get("default_replicates_per_variant") != 1
            or split_contract.get("duplicate_audit_replicates_per_variant") != 2
        ):
            raise RuntimeError(f"r6 split replicate contract drift: {split_name}")
    blind = value.get("blind_derivation", {})
    if (
        blind.get("key_commitment_message") != "microtexture-v2-r6/key-commitment/v3"
        or blind.get("seed_message_prefix") != "microtexture-v2-r6/render-seed/v3/"
        or blind.get("code_message_prefix") != "microtexture-v2-r6/opaque-code/v3/"
        or blind.get("formal_secret_value_artifact_or_log_persistence_forbidden")
        is not True
    ):
        raise RuntimeError("r6 revision-3 blind derivation domain drift")
    if (
        cluster.get("message_prefix")
        != "microtexture-v2-r6/private-condition-cluster/v3/"
        or value.get("rendering", {}).get("public_commitment_domain")
        != "microtexture-v2-r6/public-payload-commitment/v4/"
        "{control|reference|delta}/{anonymous_code}/{raw-sha256-bytes}"
    ):
        raise RuntimeError("r6 revision-3 private/public commitment domain drift")
    metric_window = value["canvas"]["metric_window"]
    if (
        metric_window.get("xywh") != [128, 96, 256, 192]
        or require_exact_int(metric_window.get("pixels"), "metric-window pixels", 1)
        != 49152
        or value["metric_definition"].get("expected_shape_hw") != [192, 256]
    ):
        raise RuntimeError("r6 metric-window contract drift")
    selection = value.get("threshold_selection", {})
    if (
        selection.get("endpoint_eligible_private_role") != "artifact"
        or selection.get("protocol_zero_and_duplicate_audit_excluded") is not True
    ):
        raise RuntimeError("r6 endpoint private-role eligibility drift")
    public_policy = value.get("public_identity_policy", {})
    if (
        set(public_policy.get("forbidden_fields", []))
        != FORBIDDEN_PUBLIC_IDENTITY_FIELDS
    ):
        raise RuntimeError("r6 public identity/payload leak allowlist drift")
    for field in (
        "blindness_scope",
        "review_surface",
        "reviewer_access_contract",
        "same_principal_attack_non_claim",
    ):
        if not isinstance(public_policy.get(field), str) or not public_policy[field]:
            raise RuntimeError(f"r6 public identity policy missing {field}")
    if (
        value["contact_sheets"].get("all_220_source_panels_unique_in_every_view")
        is not True
    ):
        raise RuntimeError("r6 public panel uniqueness contract drift")


def load_spec() -> dict[str, Any]:
    payload = SPEC_PATH.read_bytes()
    if sha256_bytes(payload) != SPEC_SHA256:
        raise RuntimeError("r6 preregistered spec SHA drift")
    value = json.loads(payload.decode("utf-8"))
    if (
        value.get("schema_version") != "microtexture-v2-r6-preregistered-spec/3"
        or not all(
            value.get(key) is True
            for key in (
                "authority",
                "created_before_control_generation",
                "created_before_metric_threshold_selection",
            )
        )
        or value.get("production_candidate_inputs_forbidden") is not True
        or value.get("preregistered_foundation_inputs_required") is not True
    ):
        raise RuntimeError("r6 preregistration authority flag/schema drift")
    validate_preregistered_spec(value)
    return value


def blind_key() -> bytes:
    value = os.environ.get("MICROTEXTURE_V2_R6_BLIND_KEY")
    if value is None:
        raise RuntimeError("MICROTEXTURE_V2_R6_BLIND_KEY is required")
    if re.fullmatch(r"(?:[0-9a-f]{64}|[0-9A-F]{64})", value) is None:
        raise RuntimeError(
            "MICROTEXTURE_V2_R6_BLIND_KEY must be exactly 64 all-lowercase "
            "or all-uppercase hexadecimal characters"
        )
    decoded = bytes.fromhex(value)
    if len(decoded) != 32:
        raise RuntimeError("decoded blind key must be exactly 32 bytes")
    return decoded


def blind_commitment(key: bytes) -> str:
    message = load_spec()["blind_derivation"]["key_commitment_message"].encode("ascii")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def blind_hmac(key: bytes, message: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha256).digest()


def runtime_fingerprint() -> dict[str, str]:
    components = {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "scipy_version": scipy.__version__,
        "pillow_version": pillow_version,
        "zlib_version": zlib.ZLIB_VERSION,
        "zlib_runtime_version": zlib.ZLIB_RUNTIME_VERSION,
        "platform": platform.platform(),
        "byteorder": sys.byteorder,
        "python_executable_sha256": sha256_bytes(Path(sys.executable).read_bytes()),
        "numpy_core_binary_sha256": sha256_bytes(
            Path(numpy_core_binary.__file__).read_bytes()
        ),
        "scipy_ndimage_binary_sha256": sha256_bytes(
            Path(scipy_ndimage_binary.__file__).read_bytes()
        ),
        "pillow_imaging_binary_sha256": sha256_bytes(
            Path(pillow_imaging_binary.__file__).read_bytes()
        ),
    }
    return {
        **components,
        "fingerprint_sha256": sha256_bytes(canonical_json_bytes(components)),
    }


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc_timestamp(value: Any, context: str) -> datetime:
    if not isinstance(value, str):
        raise RuntimeError(f"{context} must be ISO-8601 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RuntimeError(f"{context} is not ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise RuntimeError(f"{context} must use the UTC timezone")
    return parsed.astimezone(timezone.utc)


def _git(code_root: Path, *arguments: str) -> bytes:
    environment = os.environ.copy()
    environment.pop("MICROTEXTURE_V2_R6_BLIND_KEY", None)
    result = subprocess.run(
        ["git", *arguments],
        cwd=code_root,
        check=False,
        capture_output=True,
        env=environment,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Git preflight failed: {' '.join(arguments)}: {detail}")
    return result.stdout


def repository_root() -> Path:
    return Path(
        _git(CODE_ROOT, "rev-parse", "--show-toplevel").decode().strip()
    ).resolve()


def artifact_root(repository: Path) -> Path:
    raw = os.environ.get("MICROTEXTURE_V2_R6_ARTIFACT_ROOT")
    if raw is None:
        raise RuntimeError("MICROTEXTURE_V2_R6_ARTIFACT_ROOT is required")
    required_relative = "tmp/map-production/microtexture-v2-r6-artifacts"
    actual = Path(os.path.abspath(raw))
    expected = Path(os.path.abspath(os.fspath(repository / required_relative)))
    if os.path.normcase(os.fspath(actual)) != os.path.normcase(os.fspath(expected)):
        raise RuntimeError(f"artifact root must be exactly {expected}")
    exact_artifact_path_without_links(
        repository,
        actual,
        required_relative,
        must_exist=False,
    )
    if actual == CODE_ROOT or CODE_ROOT in actual.parents:
        raise RuntimeError("artifact root must be separate from CODE_ROOT")
    return actual


def exact_artifact_path_without_links(
    root: Path,
    provided: Path,
    expected_relative: str,
    *,
    must_exist: bool,
) -> Path:
    root_lexical = Path(os.path.abspath(os.fspath(root)))
    actual = Path(os.path.abspath(os.fspath(provided)))
    expected = Path(os.path.abspath(os.fspath(root_lexical / expected_relative)))
    if os.path.normcase(os.fspath(actual)) != os.path.normcase(os.fspath(expected)):
        raise RuntimeError(
            f"artifact path must be exactly {expected}; aliases are forbidden"
        )
    try:
        relative = actual.relative_to(root_lexical)
    except ValueError as error:
        raise RuntimeError(f"path escapes exact artifact root: {actual}") from error
    current = root_lexical
    components = [current]
    for part in relative.parts:
        current = current / part
        components.append(current)
    for component in components:
        try:
            component_stat = os.lstat(component)
        except FileNotFoundError:
            continue
        junction_probe = getattr(component, "is_junction", None)
        is_junction = bool(junction_probe()) if callable(junction_probe) else False
        attributes = getattr(component_stat, "st_file_attributes", 0)
        is_reparse = bool(attributes & 0x400)
        if component.is_symlink() or is_junction or is_reparse:
            raise RuntimeError(
                f"artifact path contains a link/reparse point: {component}"
            )
    if must_exist and (not actual.exists() or not actual.is_file()):
        raise RuntimeError(f"exact artifact input is not a regular file: {actual}")
    return actual


def write_bytes_exclusive(root: Path, path: Path, payload: bytes) -> None:
    root_lexical = Path(os.path.abspath(os.fspath(root)))
    path_lexical = Path(os.path.abspath(os.fspath(path)))
    try:
        relative = path_lexical.relative_to(root_lexical).as_posix()
    except ValueError as error:
        raise RuntimeError(
            f"path escapes exact artifact root: {path_lexical}"
        ) from error
    checked = exact_artifact_path_without_links(
        root, path_lexical, relative, must_exist=False
    )
    checked.parent.mkdir(parents=True, exist_ok=True)
    checked = exact_artifact_path_without_links(
        root, path_lexical, relative, must_exist=False
    )
    if checked.exists() or checked.is_symlink():
        raise FileExistsError(f"exclusive artifact already exists: {checked}")
    descriptor = os.open(checked, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        verified = exact_artifact_path_without_links(
            root, path_lexical, relative, must_exist=True
        )
        if verified.read_bytes() != payload:
            raise RuntimeError(f"exclusive artifact post-write byte drift: {verified}")
    except BaseException:
        try:
            cleanup = exact_artifact_path_without_links(
                root, path_lexical, relative, must_exist=False
            )
            if cleanup.exists() and cleanup.is_file():
                cleanup.unlink()
        except BaseException:
            pass
        raise


def write_json_exclusive(root: Path, path: Path, value: Any) -> str:
    payload = canonical_json_bytes(value)
    write_bytes_exclusive(root, path, payload)
    return sha256_bytes(payload)


def _stage_artifact_paths(stage: str) -> tuple[str, str]:
    if stage not in {"calibration", "locked-clean-reference", "holdout"}:
        raise RuntimeError(f"invalid one-shot stage: {stage}")
    settings = load_spec()["one_shot_failure_reporting"]
    return (
        settings["completion_report_paths"][stage],
        settings["exception_report_paths"][stage],
    )


def validate_stage_completion_structure(value: Any, context: str) -> None:
    require_exact_keys(value, STAGE_COMPLETION_KEYS, context)
    require_exact_keys(value["bindings"], STAGE_COMPLETION_BINDING_KEYS, context)
    if (
        value["artifact"] != "microtexture-v2-r6-stage-completion"
        or value["schema_version"] != "microtexture-v2-r6-stage-completion/2"
        or value["stage"] not in {"calibration", "locked-clean-reference", "holdout"}
        or re.fullmatch(r"[0-9a-f]{64}", value["spec_sha256"] or "") is None
        or re.fullmatch(r"[0-9a-f]{64}", value["blind_key_commitment"] or "") is None
        or re.fullmatch(r"[0-9a-f]{64}", value["evaluation_marker_sha256"] or "")
        is None
        or re.fullmatch(r"[0-9a-f]{64}", value["normal_report_sha256"] or "") is None
        or re.fullmatch(r"[0-9a-f]{40}", value["captured_git_head"] or "") is None
        or not isinstance(value["runtime"], dict)
        or re.fullmatch(r"[0-9a-f]{64}", value["implementation_bindings_sha256"] or "")
        is None
        or type(value["one_shot_consumed"]) is not bool
        or value["one_shot_consumed"] is not True
        or type(value["passed"]) is not bool
        or not isinstance(value["result_status"], str)
        or not value["result_status"]
    ):
        raise RuntimeError(f"{context} header/type drift")
    for field, digest in value["bindings"].items():
        if digest is not None and re.fullmatch(r"[0-9a-f]{64}", digest or "") is None:
            raise RuntimeError(f"{context} invalid binding: {field}")
    parse_utc_timestamp(value["completed_at"], f"{context} completed_at")


def write_stage_completion_exclusive(
    *,
    stage: str,
    state: dict[str, Any],
    marker_sha: str,
    report_sha: str,
    passed: bool,
    result_status: str,
    bindings: dict[str, str | None],
) -> None:
    require_exact_keys(bindings, STAGE_COMPLETION_BINDING_KEYS, f"{stage} completion")
    completion = {
        "artifact": "microtexture-v2-r6-stage-completion",
        "schema_version": "microtexture-v2-r6-stage-completion/2",
        "stage": stage,
        "spec_sha256": SPEC_SHA256,
        "blind_key_commitment": state["blind_key_commitment"],
        "evaluation_marker_sha256": marker_sha,
        "normal_report_sha256": report_sha,
        "captured_git_head": state["captured_head"],
        "runtime": state["runtime"],
        "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        "completed_at": utc_timestamp(),
        "one_shot_consumed": True,
        "passed": passed,
        "result_status": result_status,
        "bindings": bindings,
    }
    validate_stage_completion_structure(completion, f"{stage} completion")
    completion_relative, failure_relative = _stage_artifact_paths(stage)
    root = state["artifact_root"]
    failure_path = exact_artifact_path_without_links(
        root,
        root / failure_relative,
        failure_relative,
        must_exist=False,
    )
    if failure_path.exists():
        raise RuntimeError(f"{stage} failure report precludes normal completion")
    completion_path = exact_artifact_path_without_links(
        root,
        root / completion_relative,
        completion_relative,
        must_exist=False,
    )
    payload = canonical_json_bytes(completion)
    write_bytes_exclusive(root, completion_path, payload)


def load_stage_completion(
    *,
    stage: str,
    state: dict[str, Any],
    expected_marker_sha: str,
    expected_report_sha: str,
    expected_captured_head: str,
    expected_passed: bool,
    expected_result_status: str,
    expected_bindings: dict[str, str | None],
    marker_started_at: datetime,
    report_evaluated_at: datetime,
    frozen_at: datetime | None = None,
) -> tuple[dict[str, Any], str]:
    require_exact_keys(
        expected_bindings,
        STAGE_COMPLETION_BINDING_KEYS,
        f"{stage} expected completion bindings",
    )
    completion_relative, failure_relative = _stage_artifact_paths(stage)
    root = state["artifact_root"]
    failure_path = exact_artifact_path_without_links(
        root,
        root / failure_relative,
        failure_relative,
        must_exist=False,
    )
    if failure_path.exists():
        raise RuntimeError(f"{stage} failure report coexists with normal completion")
    completion_path = exact_artifact_path_without_links(
        root,
        root / completion_relative,
        completion_relative,
        must_exist=True,
    )
    payload = completion_path.read_bytes()
    completion = json.loads(payload.decode("utf-8"))
    validate_stage_completion_structure(completion, f"{stage} completion")
    if (
        completion["stage"] != stage
        or completion["spec_sha256"] != SPEC_SHA256
        or completion["blind_key_commitment"] != state["blind_key_commitment"]
        or completion["evaluation_marker_sha256"] != expected_marker_sha
        or completion["normal_report_sha256"] != expected_report_sha
        or completion["captured_git_head"] != expected_captured_head
        or completion["runtime"] != state["runtime"]
        or completion["implementation_bindings_sha256"]
        != state["implementation_bindings_sha256"]
        or completion["passed"] is not expected_passed
        or completion["result_status"] != expected_result_status
        or completion["bindings"] != expected_bindings
    ):
        raise RuntimeError(f"{stage} completion trust-chain binding drift")
    completed_at = parse_utc_timestamp(
        completion["completed_at"], f"{stage} completion completed_at"
    )
    if marker_started_at > report_evaluated_at or report_evaluated_at > completed_at:
        raise RuntimeError(f"{stage} marker/report/completion timestamp order drift")
    if frozen_at is not None and frozen_at > completed_at:
        raise RuntimeError(f"{stage} frozen/completion timestamp order drift")
    return completion, sha256_bytes(payload)


def validate_implementation_bindings() -> dict[str, Any]:
    value = json.loads(BINDINGS_PATH.read_text(encoding="utf-8"))
    require_exact_keys(
        value,
        {"artifact", "schema_version", "authority", "spec_sha256", "files"},
        "implementation bindings",
    )
    if (
        value["artifact"] != "microtexture-v2-r6-implementation-bindings"
        or value["schema_version"] != "microtexture-v2-r6-implementation-bindings/3"
        or value["authority"] is not True
        or value["spec_sha256"] != SPEC_SHA256
    ):
        raise RuntimeError("r6 implementation binding header drift")
    expected = set(load_spec()["authority_files"]) - {"implementation-bindings.json"}
    if set(value["files"]) != expected:
        raise RuntimeError("r6 implementation binding file set drift")
    for relative, expected_sha in value["files"].items():
        path = (CODE_ROOT / relative).resolve()
        if (
            CODE_ROOT not in path.parents
            or sha256_bytes(path.read_bytes()) != expected_sha
        ):
            raise RuntimeError(f"r6 implementation SHA drift: {relative}")
    return value


def _tracked_worktree_bytes(
    repository: Path, captured_head: str, relative: str
) -> bytes:
    path = (repository / relative).resolve()
    try:
        path.relative_to(repository)
    except ValueError as error:
        raise RuntimeError(f"tracked path escapes repository: {relative}") from error
    working = path.read_bytes()
    committed = _git(CODE_ROOT, "show", f"{captured_head}:{relative}")
    if working != committed:
        raise RuntimeError(f"working bytes differ from captured HEAD: {relative}")
    return working


def verify_tracked_development_history(
    repository: Path, captured_head: str, spec: dict[str, Any]
) -> bytes:
    """Bind the closed dev-r7 audit without exposing its private corpus."""

    history = spec["history"]
    relative = history["dev_r7_failure_audit"]
    payload = _tracked_worktree_bytes(repository, captured_head, relative)
    if sha256_bytes(payload) != history["dev_r7_failure_audit_sha256"]:
        raise RuntimeError("closed dev-r7 failure audit tracked SHA drift")
    value = json.loads(payload.decode("utf-8"))
    if (
        value.get("artifact") != "microtexture-v2-r6-dev-r7-development-failure-audit"
        or value.get("schema_version")
        != "microtexture-v2-r6-development-failure-audit/2"
        or value.get("authority") is not False
        or value.get("formal_use_forbidden") is not True
        or value.get("development_edition") != "r7"
        or value.get("outcome") != "failed_closed"
        or value.get("measurement_started") is not True
        or value.get("selection_status") != "no-endpoint-admissible-threshold"
        or value.get("development_hard_threshold") is not None
        or value.get("holdout_endpoint_performance") is not None
        or value.get("one_shot_contract", {}).get("r7_closed") is not True
        or value.get("vision_review", {}).get(
            "root_and_initial_independent_exact_logical_agreement"
        )
        is not False
        or value.get("vision_review", {}).get(
            "calibration_root_independent_initial_logical_difference_count"
        )
        != 31
        or value.get("vision_review", {}).get(
            "holdout_root_independent_initial_logical_difference_count"
        )
        != 39
        or value.get("vision_review", {}).get(
            "root_and_independent_logical_decisions_reconciled"
        )
        is not True
        or value.get("vision_review", {}).get(
            "canonical_matches_root_exactly_after_reconciliation"
        )
        is not True
        or value.get("vision_review", {}).get(
            "calibration_initial_independent_decisions_sha256"
        )
        != "f18fe9504a416257aecb06c3027f475288c4aabdec2b911078b436a52651e24f"
        or value.get("vision_review", {}).get(
            "holdout_initial_independent_decisions_sha256"
        )
        != "8776462a9d052697814373b408510b2227cda3b6206655953e5c0f5f382e3dfb"
        or value.get("secret_handling", {}).get("blind_key_present_in_this_artifact")
        is not False
        or value.get("secret_handling", {}).get("blind_key_value_logged_or_tracked")
        is not False
        or value.get("secret_handling", {}).get(
            "development_blind_key_persisted_in_ignored_closed_private_root"
        )
        is not True
        or value.get("secret_handling", {}).get("development_blind_key_reuse_forbidden")
        is not True
    ):
        raise RuntimeError("closed dev-r7 failure audit semantic drift")
    return payload


def assert_head_unchanged(captured_head: str) -> None:
    if _git(CODE_ROOT, "rev-parse", "HEAD").decode().strip() != captured_head:
        raise RuntimeError("Git HEAD changed during r6 operation")


def assert_git_ancestor(ancestor: str, descendant: str) -> None:
    try:
        _git(CODE_ROOT, "merge-base", "--is-ancestor", ancestor, descendant)
    except RuntimeError as error:
        raise RuntimeError(
            "formal calibration HEAD is not an ancestor of the current r6 HEAD"
        ) from error


def verify_tracked_locked_clean_reference_provenance(
    repository: Path, captured_head: str, locked: dict[str, Any]
) -> bytes:
    bindings = (
        ("repo_relative_path", "sha256"),
        ("generation_chain", "generation_chain_sha256"),
        ("generation_receipt", "generation_receipt_sha256"),
        ("root_vision_review", "root_vision_review_sha256"),
        ("independent_vision_review", "independent_vision_review_sha256"),
    )
    payloads: dict[str, bytes] = {}
    for path_field, hash_field in bindings:
        payload = _tracked_worktree_bytes(repository, captured_head, locked[path_field])
        if sha256_bytes(payload) != locked[hash_field]:
            raise RuntimeError(f"locked-clean-reference {path_field} tracked SHA drift")
        payloads[path_field] = payload
    return payloads["repo_relative_path"]


def verify_tracked_foundation_corpus_provenance(
    repository: Path, captured_head: str, corpus: dict[str, Any]
) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for foundation in corpus["foundations"]:
        payload = _tracked_worktree_bytes(repository, captured_head, foundation["path"])
        if sha256_bytes(payload) != foundation["sha256"]:
            raise RuntimeError(f"r6 foundation {foundation['id']} tracked SHA drift")
        payloads[foundation["id"]] = payload
    for path_field, hash_field in (
        ("generation_chain", "generation_chain_sha256"),
        ("generation_receipt", "generation_receipt_sha256"),
        ("root_vision_review", "root_vision_review_sha256"),
    ):
        payload = _tracked_worktree_bytes(repository, captured_head, corpus[path_field])
        if sha256_bytes(payload) != corpus[hash_field]:
            raise RuntimeError(f"r6 foundation {path_field} tracked SHA drift")
    for index, review in enumerate(corpus["independent_vision_reviews"]):
        payload = _tracked_worktree_bytes(repository, captured_head, review["path"])
        if sha256_bytes(payload) != review["sha256"]:
            raise RuntimeError(
                f"r6 foundation independent review {index} tracked SHA drift"
            )
    return payloads


def operation_preflight(
    *, require_receipt: bool, include_locked_clean_reference: bool = False
) -> dict[str, Any]:
    spec = load_spec()
    key = blind_key()
    commitment = blind_commitment(key)
    repository = repository_root()
    captured_head = _git(CODE_ROOT, "rev-parse", "HEAD").decode().strip()
    branch = (
        _git(CODE_ROOT, "symbolic-ref", "--quiet", "--short", "HEAD").decode().strip()
    )
    upstream_ref = (
        _git(
            CODE_ROOT,
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            f"{branch}@{{upstream}}",
        )
        .decode()
        .strip()
    )
    upstream_head = _git(CODE_ROOT, "rev-parse", upstream_ref).decode().strip()
    if captured_head != upstream_head:
        raise RuntimeError(
            "captured HEAD is not equal to the current branch upstream ref"
        )
    try:
        code_relative_root = CODE_ROOT.relative_to(repository)
    except ValueError as error:
        raise RuntimeError("CODE_ROOT is outside repository") from error
    required_code_root = Path(spec["roots"]["code_root_required_repo_relative"])
    if code_relative_root != required_code_root:
        raise RuntimeError(f"CODE_ROOT must be exactly {required_code_root.as_posix()}")
    for relative in spec["authority_files"]:
        _tracked_worktree_bytes(
            repository, captured_head, (code_relative_root / relative).as_posix()
        )
    bindings = validate_implementation_bindings()
    verify_tracked_development_history(repository, captured_head, spec)
    state = {
        "repository": repository,
        "artifact_root": artifact_root(repository),
        "captured_head": captured_head,
        "upstream_ref": upstream_ref,
        "runtime": runtime_fingerprint(),
        "blind_key_commitment": commitment,
        "implementation_bindings_sha256": sha256_bytes(BINDINGS_PATH.read_bytes()),
        "bindings": bindings,
    }
    state["foundation_bytes"] = verify_tracked_foundation_corpus_provenance(
        repository, captured_head, spec["foundation_corpus"]
    )
    if include_locked_clean_reference:
        locked = spec["locked_clean_reference"]
        locked_bytes = verify_tracked_locked_clean_reference_provenance(
            repository, captured_head, locked
        )
        state["locked_clean_reference_bytes"] = locked_bytes
    if require_receipt:
        receipt, receipt_sha = load_threshold_authority_receipt(state)
        state["threshold_authority"] = receipt
        state["threshold_authority_sha256"] = receipt_sha
    assert_head_unchanged(captured_head)
    return state


HARD_THRESHOLD_KEYS = {
    "metric",
    "direction",
    "threshold",
    "calibration_clean_cluster_acceptance",
    "calibration_warning_cluster_acceptance",
    "calibration_reject_cluster_detection",
    "calibration_severity3_cluster_detection",
    "selection_objective",
}
FROZEN_KEYS = {
    "artifact",
    "schema_version",
    "authority",
    "spec_sha256",
    "blind_key_commitment",
    "calibration_manifest_sha256",
    "calibration_report_sha256",
    "calibration_evaluation_marker_sha256",
    "calibration_captured_git_head",
    "frozen_at",
    "runtime",
    "hard_gate",
    "hard_threshold",
    "endpoint_definitions",
    "implementation_bindings_sha256",
    "holdout_allowed_count",
    "threshold_changes_forbidden",
}
CALIBRATION_REPORT_KEYS = {
    "artifact",
    "schema_version",
    "spec_sha256",
    "blind_key_commitment",
    "manifest_sha256",
    "labels_sha256",
    "evaluation_marker_sha256",
    "evaluated_at",
    "captured_git_head",
    "runtime",
    "implementation_bindings_sha256",
    "hard_gate",
    "hard_threshold",
    "selection_status",
    "endpoint_performance",
    "results_by_code",
    "diagnostic_flags_by_code",
    "passed",
    "measurements",
    "identity_reveal",
    "threshold_selection_audit",
    "one_shot_consumed",
    "failure",
}
LOCKED_CLEAN_REFERENCE_REPORT_KEYS = {
    "artifact",
    "schema_version",
    "spec_sha256",
    "blind_key_commitment",
    "frozen_thresholds_sha256",
    "locked_clean_reference_sha256",
    "source_crop_xywh",
    "metric_window_xywh_within_source_crop",
    "effective_source_xywh",
    "evaluation_marker_sha256",
    "evaluated_at",
    "captured_git_head",
    "runtime",
    "implementation_bindings_sha256",
    "metrics",
    "hard_threshold",
    "hard_composite_accepted",
    "passed",
    "one_shot_consumed",
    "failure",
}
HOLDOUT_REPORT_KEYS = {
    "artifact",
    "schema_version",
    "authority",
    "spec_sha256",
    "blind_key_commitment",
    "manifest_sha256",
    "labels_sha256",
    "evaluation_marker_sha256",
    "frozen_thresholds_sha256",
    "threshold_authority_receipt_sha256",
    "evaluated_at",
    "captured_git_head",
    "runtime",
    "implementation_bindings_sha256",
    "hard_gate",
    "hard_threshold",
    "endpoint_performance",
    "results_by_code",
    "diagnostic_flags_by_code",
    "passed",
    "measurements",
    "identity_reveal",
    "threshold_changes_authorized",
    "one_shot_consumed",
    "failure",
}
RECEIPT_KEYS = {
    "artifact",
    "schema_version",
    "approval",
    "reviewer_id",
    "review_mode",
    "reviewed_at",
    "spec_sha256",
    "frozen_thresholds_sha256",
    "calibration_report_sha256",
    "calibration_manifest_sha256",
    "locked_clean_reference_report_sha256",
    "implementation_bindings_sha256",
    "blind_key_commitment",
    "runtime",
    "calibration_captured_git_head",
    "locked_clean_reference_captured_git_head",
}
VISION_LABEL_KEYS = {
    "artifact",
    "schema_version",
    "split",
    "spec_sha256",
    "manifest_sha256",
    "implementation_bindings_sha256",
    "blind_key_commitment",
    "runtime",
    "contact_sheet_bundle",
    "reviewer",
    "items",
}
VISION_LABEL_ITEM_KEYS = {
    "anonymous_code",
    "disposition",
    "grain_visible",
    "tiny_speck_visible",
    "microblob_visible",
    "short_line_visible",
    "parallel_bundle_visible",
    "severity_0_to_3",
    "reviewed_at_200_percent",
    "reviewed_at_all_400_percent_quadrants",
    "notes",
}
VISION_EVIDENCE_BINDINGS = (
    ("g", "grain_visible"),
    ("t", "tiny_speck_visible"),
    ("b", "microblob_visible"),
    ("l", "short_line_visible"),
    ("p", "parallel_bundle_visible"),
)
VISION_EVIDENCE_LOCATOR_PATTERN = re.compile(
    r"(NW|NE|SW|SE)-R([1-3])C([1-3])-N(0[1-9]|[1-9][0-9])"
)
CONTROL_MANIFEST_KEYS = {
    "artifact",
    "schema_version",
    "split",
    "spec_sha256",
    "implementation_bindings_sha256",
    "blind_key_commitment",
    "captured_git_head",
    "runtime",
    "frozen_thresholds_sha256",
    "threshold_authority_receipt_sha256",
    "record_count",
    "records",
    "contact_sheet_bundle",
    "warning",
}
CONTROL_RECORD_KEYS = {
    "anonymous_code",
    "control_commitment",
    "reference_commitment",
    "delta_commitment",
}
CONTROL_SHEET_KEYS = {
    "view_id",
    "scale_percent",
    "source_crop_xywh",
    "page_index",
    "path",
    "sha256",
    "item_codes",
}
FORBIDDEN_PUBLIC_IDENTITY_FIELDS = {
    "family",
    "family_id",
    "control_id",
    "variant",
    "variant_id",
    "role",
    "polarity",
    "parameters",
    "cluster_id",
    "condition_cluster_id",
    "private_role",
    "foundation_id",
    "duplicate_audit_group",
    "control_png",
    "reference_png",
    "control_path",
    "reference_path",
    "control_sha256",
    "reference_sha256",
    "delta_float32_sha256",
}

CALIBRATION_MARKER_KEYS = {
    "artifact",
    "schema_version",
    "spec_sha256",
    "blind_key_commitment",
    "manifest_sha256",
    "labels_sha256",
    "captured_git_head",
    "runtime",
    "implementation_bindings_sha256",
    "started_at",
    "one_shot_consumed",
}
LOCKED_CLEAN_REFERENCE_MARKER_KEYS = {
    "artifact",
    "schema_version",
    "spec_sha256",
    "blind_key_commitment",
    "frozen_thresholds_sha256",
    "captured_git_head",
    "runtime",
    "implementation_bindings_sha256",
    "started_at",
    "one_shot_consumed",
}
HOLDOUT_MARKER_KEYS = {
    "artifact",
    "schema_version",
    "spec_sha256",
    "blind_key_commitment",
    "manifest_sha256",
    "labels_sha256",
    "frozen_thresholds_sha256",
    "threshold_authority_receipt_sha256",
    "captured_git_head",
    "runtime",
    "implementation_bindings_sha256",
    "started_at",
    "one_shot_consumed",
}
FAILURE_KEYS = {"phase", "type", "message"}
ONE_SHOT_FAILURE_REPORT_KEYS = {
    "artifact",
    "schema_version",
    "stage",
    "spec_sha256",
    "blind_key_commitment",
    "evaluation_marker_sha256",
    "captured_git_head",
    "runtime",
    "implementation_bindings_sha256",
    "failed_at",
    "one_shot_consumed",
    "bindings",
    "failure",
}
ONE_SHOT_FAILURE_BINDING_KEYS = {
    "manifest_sha256",
    "labels_sha256",
    "frozen_thresholds_sha256",
    "threshold_authority_receipt_sha256",
}
STAGE_COMPLETION_KEYS = {
    "artifact",
    "schema_version",
    "stage",
    "spec_sha256",
    "blind_key_commitment",
    "evaluation_marker_sha256",
    "normal_report_sha256",
    "captured_git_head",
    "runtime",
    "implementation_bindings_sha256",
    "completed_at",
    "one_shot_consumed",
    "passed",
    "result_status",
    "bindings",
}
STAGE_COMPLETION_BINDING_KEYS = {
    "manifest_sha256",
    "labels_sha256",
    "frozen_thresholds_sha256",
    "threshold_authority_receipt_sha256",
    "locked_clean_reference_sha256",
}
ENDPOINT_PERFORMANCE_KEYS = {
    "record_count",
    "unique_cluster_count",
    "minimum_unique_clusters",
    "cluster_macro_rate",
    "minimum_rate",
    "count_passed",
    "rate_passed",
    "passed",
}
RESULT_KEYS = {"passed", "failed_hard_gate", "hard_metric_value"}
MEASUREMENT_KEYS = {"anonymous_code", "metrics"}
METRIC_KEYS = set(METRIC_FIELDS)
METRIC_INTEGER_KEYS = set(RAW_INTEGER_FIELDS)
IDENTITY_REVEAL_KEYS = {
    "anonymous_code",
    "family",
    "control_id",
    "condition_cluster_id",
    "variant_index",
    "replicate",
    "polarity",
    "parameters",
    "control_sha256",
    "reference_sha256",
    "delta_float32_sha256",
    "private_role",
    "foundation_id",
    "duplicate_audit_group",
}
THRESHOLD_AUDIT_KEYS = {
    "candidate_count",
    "admissible_candidate_count",
    "selected_threshold",
    "selected_objective",
    "diagnostic_candidate_count",
    "diagnostic_best_threshold",
    "diagnostic_best_objective",
    "candidates",
}
THRESHOLD_AUDIT_CANDIDATE_KEYS = {
    "threshold",
    "admissible",
    "inadmissible_reasons",
    "objective",
    "clean_cluster_count",
    "warning_cluster_count",
    "clean_cluster_acceptance",
    "warning_cluster_acceptance",
    "all_endpoints_passed",
}


def _forbid_public_identity(value: Any, context: str) -> None:
    if isinstance(value, dict):
        leaked = set(value) & FORBIDDEN_PUBLIC_IDENTITY_FIELDS
        if leaked:
            raise RuntimeError(f"identity leak in {context}: {sorted(leaked)}")
        for child in value.values():
            _forbid_public_identity(child, context)
    elif isinstance(value, list):
        for child in value:
            _forbid_public_identity(child, context)


def _vision_evidence_locator_sort_key(locator: str) -> tuple[int, int, int, int]:
    matched = VISION_EVIDENCE_LOCATOR_PATTERN.fullmatch(locator)
    if matched is None:
        raise RuntimeError("Vision evidence locator grammar drift")
    quadrant, row, column, ordinal = matched.groups()
    return (
        {"NW": 0, "NE": 1, "SW": 2, "SE": 3}[quadrant],
        int(row),
        int(column),
        int(ordinal),
    )


def _validate_vision_evidence_notes(
    item: dict[str, Any], context: str, code: str
) -> None:
    notes = item.get("notes")
    if (
        not isinstance(notes, str)
        or not notes.isascii()
        or any(character.isspace() for character in notes)
        or not notes.startswith("ev3:")
    ):
        raise RuntimeError(f"{context} evidence notes contract drift: {code}")
    clauses = notes[4:].split(";")
    if len(clauses) != len(VISION_EVIDENCE_BINDINGS):
        raise RuntimeError(f"{context} evidence notes contract drift: {code}")
    evidence: dict[str, tuple[str, ...]] = {}
    for clause, (flag, field) in zip(clauses, VISION_EVIDENCE_BINDINGS):
        prefix = f"{flag}="
        if not clause.startswith(prefix):
            raise RuntimeError(f"{context} evidence notes contract drift: {code}")
        encoded = clause[len(prefix) :]
        if encoded == "-":
            locators: tuple[str, ...] = ()
        else:
            locators = tuple(encoded.split(","))
            if (
                not locators
                or any(
                    VISION_EVIDENCE_LOCATOR_PATTERN.fullmatch(locator) is None
                    for locator in locators
                )
                or len(locators) != len(set(locators))
                or list(locators)
                != sorted(locators, key=_vision_evidence_locator_sort_key)
            ):
                raise RuntimeError(f"{context} evidence notes contract drift: {code}")
        if bool(locators) is not item[field]:
            raise RuntimeError(f"{context} evidence flag binding drift: {code}/{flag}")
        evidence[flag] = locators
    if len(evidence["t"]) not in {0} and len(evidence["t"]) < 3:
        raise RuntimeError(f"{context} tiny-speck evidence cardinality drift: {code}")
    if evidence["p"] and (
        not item["short_line_visible"] or not set(evidence["p"]).issubset(evidence["l"])
    ):
        raise RuntimeError(f"{context} parallel evidence binding drift: {code}")


def validate_vision_labels_payload(
    value: Any,
    split: str,
    manifest: dict[str, Any],
    manifest_sha: str,
    state: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    context = f"{split} labels"
    require_exact_keys(value, VISION_LABEL_KEYS, context)
    _forbid_public_identity(value, context)
    if (
        value["artifact"] != "microtexture-v2-r6-root-vision-labels"
        or value["schema_version"] != "microtexture-v2-r6-root-vision-labels/2"
        or value["split"] != split
        or value["spec_sha256"] != SPEC_SHA256
        or value["manifest_sha256"] != manifest_sha
        or value["implementation_bindings_sha256"]
        != state["implementation_bindings_sha256"]
        or value["blind_key_commitment"] != state["blind_key_commitment"]
        or value["runtime"] != manifest["runtime"]
        or value["contact_sheet_bundle"] != manifest["contact_sheet_bundle"]
        or value["reviewer"] != "Root"
    ):
        raise RuntimeError(f"{context} authority/manifest/sheet drift")
    expected_codes = {record["anonymous_code"] for record in manifest["records"]}
    items = value["items"]
    if not isinstance(items, list) or len(items) != len(expected_codes):
        raise RuntimeError(f"{context} item count drift")
    labels: dict[str, dict[str, Any]] = {}
    visible_fields = (
        "grain_visible",
        "tiny_speck_visible",
        "microblob_visible",
        "short_line_visible",
        "parallel_bundle_visible",
    )
    boolean_fields = (
        *visible_fields,
        "reviewed_at_200_percent",
        "reviewed_at_all_400_percent_quadrants",
    )
    for index, item in enumerate(items):
        require_exact_keys(item, VISION_LABEL_ITEM_KEYS, f"{context}[{index}]")
        code, disposition = item["anonymous_code"], item["disposition"]
        if (
            not isinstance(code, str)
            or re.fullmatch(r"[0-9a-f]{24}", code) is None
            or code in labels
            or disposition not in {"clean", "warning", "reject"}
        ):
            raise RuntimeError(f"{context} invalid code/disposition")
        for name in boolean_fields:
            if type(item[name]) is not bool:
                raise RuntimeError(f"{context} incomplete boolean: {code}/{name}")
        if (
            not item["reviewed_at_200_percent"]
            or not item["reviewed_at_all_400_percent_quadrants"]
        ):
            raise RuntimeError(
                f"{context} full-200 and all four 400-percent quadrants required: {code}"
            )
        severity = item["severity_0_to_3"]
        visible = any(item[name] for name in visible_fields)
        consistent = (
            (disposition == "clean" and severity == 0 and not visible)
            or (disposition == "warning" and severity == 1 and visible)
            or (disposition == "reject" and severity in {2, 3} and visible)
        )
        if (
            type(severity) is not int
            or not consistent
            or not isinstance(item["notes"], str)
        ):
            raise RuntimeError(
                f"{context} disposition/severity/visibility contradiction: {code}"
            )
        _validate_vision_evidence_notes(item, context, code)
        labels[code] = item
    if set(labels) != expected_codes:
        raise RuntimeError(f"{context} label coverage drift")
    return labels


def validate_private_vision_label_audits(
    labels: dict[str, dict[str, Any]],
    private_rows: list[dict[str, Any]],
    context: str,
) -> None:
    """Consume blinded reliability sentinels only after the one-shot marker.

    The public label validator deliberately does not compare image hashes or
    reveal sentinel membership.  Callers must first seal the reviewed bytes,
    create the durable marker, and privately regenerate the catalog.
    """

    rows_by_code: dict[str, dict[str, Any]] = {}
    role_counts = {"artifact": 0, "protocol-zero": 0, "duplicate-audit": 0}
    duplicate_groups: dict[str, list[str]] = {"clean": [], "artifact": []}
    for index, row in enumerate(private_rows):
        if not isinstance(row, dict):
            raise RuntimeError(f"{context} private row must be an object: {index}")
        code = row.get("anonymous_code")
        role = row.get("private_role")
        group = row.get("duplicate_audit_group")
        if (
            not isinstance(code, str)
            or code in rows_by_code
            or role not in role_counts
            or group not in {None, "clean", "artifact"}
            or ((role == "duplicate-audit") is (group is None))
        ):
            raise RuntimeError(f"{context} private sentinel identity drift: {index}")
        rows_by_code[code] = row
        role_counts[role] += 1
        if role == "duplicate-audit":
            duplicate_groups[group].append(code)
    if set(rows_by_code) != set(labels) or role_counts != {
        "artifact": 200,
        "protocol-zero": 16,
        "duplicate-audit": 4,
    }:
        raise RuntimeError(f"{context} private sentinel coverage drift")
    if any(len(codes) != 2 for codes in duplicate_groups.values()):
        raise RuntimeError(f"{context} duplicate-audit membership drift")

    visible_fields = (
        "grain_visible",
        "tiny_speck_visible",
        "microblob_visible",
        "short_line_visible",
        "parallel_bundle_visible",
    )
    semantic_fields = ("disposition", "severity_0_to_3", *visible_fields)

    def require_clean(code: str, audit_name: str) -> None:
        label = labels[code]
        if (
            label["disposition"] != "clean"
            or label["severity_0_to_3"] != 0
            or any(label[field] for field in visible_fields)
        ):
            raise RuntimeError(f"{context} {audit_name} was not labeled clean: {code}")

    for code, row in rows_by_code.items():
        if row["private_role"] == "protocol-zero":
            require_clean(code, "protocol-zero sentinel")

    for group, codes in duplicate_groups.items():
        signatures = {
            tuple(labels[code][field] for field in semantic_fields) for code in codes
        }
        if len(signatures) != 1:
            raise RuntimeError(
                f"{context} duplicate-audit semantic disagreement: {sorted(codes)}"
            )
        if group == "clean":
            for code in codes:
                require_clean(code, "clean duplicate-audit sentinel")
        else:
            for code in codes:
                label = labels[code]
                if (
                    label["disposition"] != "reject"
                    or label["severity_0_to_3"] not in {2, 3}
                    or label["short_line_visible"] is not True
                ):
                    raise RuntimeError(
                        f"{context} obvious-artifact duplicate sentinel was not "
                        f"rejected as a short line: {code}"
                    )


def load_control_manifest(
    split: str,
    state: dict[str, Any],
    *,
    expected_captured_head: str,
    verify_payload_hashes: bool,
) -> tuple[dict[str, Any], str]:
    if split not in {"calibration", "holdout"}:
        raise RuntimeError("invalid control-manifest split")
    root, spec = state["artifact_root"], load_spec()
    relative = f"controls/{split}/manifest.json"
    path = exact_artifact_path_without_links(
        root, root / relative, relative, must_exist=True
    )
    payload = path.read_bytes()
    manifest = json.loads(payload.decode("utf-8"))
    require_exact_keys(manifest, CONTROL_MANIFEST_KEYS, f"{split} manifest")
    _forbid_public_identity(manifest, f"{split} manifest")
    expected_receipt_sha = (
        state.get("threshold_authority_sha256") if split == "holdout" else None
    )
    expected_frozen_sha = (
        state.get("threshold_authority", {}).get("frozen_thresholds_sha256")
        if split == "holdout"
        else None
    )
    if (
        manifest["artifact"] != "microtexture-v2-r6-control-manifest"
        or manifest["schema_version"] != "microtexture-v2-r6-control-manifest/3"
        or manifest["split"] != split
        or manifest["spec_sha256"] != SPEC_SHA256
        or manifest["implementation_bindings_sha256"]
        != state["implementation_bindings_sha256"]
        or manifest["blind_key_commitment"] != state["blind_key_commitment"]
        or manifest["captured_git_head"] != expected_captured_head
        or manifest["runtime"] != state["runtime"]
        or manifest["frozen_thresholds_sha256"] != expected_frozen_sha
        or manifest["threshold_authority_receipt_sha256"] != expected_receipt_sha
        or not isinstance(manifest["warning"], str)
        or not manifest["warning"]
    ):
        raise RuntimeError(f"{split} manifest trust-chain drift")
    expected_count = int(spec["contact_sheets"]["expected_controls_per_split"])
    records = manifest["records"]
    if (
        not isinstance(records, list)
        or require_exact_int(manifest["record_count"], f"{split} record_count", 1)
        != expected_count
        or len(records) != expected_count
    ):
        raise RuntimeError(f"{split} manifest record count drift")
    codes: list[str] = []
    for index, record in enumerate(records):
        require_exact_keys(record, CONTROL_RECORD_KEYS, f"{split} record[{index}]")
        code = record["anonymous_code"]
        if (
            not isinstance(code, str)
            or re.fullmatch(r"[0-9a-f]{24}", code) is None
            or any(
                re.fullmatch(r"[0-9a-f]{64}", record[field] or "") is None
                for field in (
                    "control_commitment",
                    "reference_commitment",
                    "delta_commitment",
                )
            )
        ):
            raise RuntimeError(f"{split} manifest record identity/hash drift")
        codes.append(code)
    if codes != sorted(codes) or len(codes) != len(set(codes)):
        raise RuntimeError(f"{split} manifest code order/collision drift")
    commitments = [
        record[field]
        for record in records
        for field in (
            "control_commitment",
            "reference_commitment",
            "delta_commitment",
        )
    ]
    if len(commitments) != len(set(commitments)):
        raise RuntimeError(f"{split} public payload commitment collision")
    sheets = manifest["contact_sheet_bundle"]
    expected_sheet_count = int(spec["contact_sheets"]["expected_pages_per_split"])
    if not isinstance(sheets, list) or len(sheets) != expected_sheet_count:
        raise RuntimeError(f"{split} contact-sheet bundle count drift")
    per_page = int(spec["contact_sheets"]["columns"]) * int(
        spec["contact_sheets"]["rows_per_page"]
    )
    code_pages = [
        codes[start : start + per_page] for start in range(0, len(codes), per_page)
    ]
    expected_entries = []
    for view in spec["contact_sheets"]["views"]:
        for page_index, item_codes in enumerate(code_pages, 1):
            expected_entries.append(
                {
                    "view_id": view["id"],
                    "scale_percent": view["scale_percent"],
                    "source_crop_xywh": view["source_crop_xywh"],
                    "page_index": page_index,
                    "path": (
                        f"controls/{split}/contact-sheets/{view['id']}-"
                        f"page-{page_index:03d}.png"
                    ),
                    "item_codes": item_codes,
                }
            )
    for index, (sheet, expected) in enumerate(zip(sheets, expected_entries)):
        require_exact_keys(sheet, CONTROL_SHEET_KEYS, f"{split} sheet[{index}]")
        if (
            any(sheet[key] != value for key, value in expected.items())
            or re.fullmatch(r"[0-9a-f]{64}", sheet["sha256"] or "") is None
        ):
            raise RuntimeError(f"{split} contact-sheet binding drift: {index}")
        if verify_payload_hashes:
            sheet_path = exact_artifact_path_without_links(
                root,
                root / sheet["path"],
                sheet["path"],
                must_exist=True,
            )
            if sha256_bytes(sheet_path.read_bytes()) != sheet["sha256"]:
                raise RuntimeError(f"{split} actual contact-sheet SHA drift: {index}")
    return manifest, sha256_bytes(payload)


def validate_secret_catalog_report_binding(
    report: dict[str, Any],
    manifest: dict[str, Any],
    split: str,
    state: dict[str, Any],
) -> None:
    from control_catalog import (  # Imported lazily to avoid a module cycle.
        contact_sheet_pages,
        expected_controls,
        validate_manifest_public_bindings,
    )

    spec = load_spec()
    key = blind_key()
    if blind_commitment(key) != state["blind_key_commitment"]:
        raise RuntimeError(f"{split} blind key changed during authority reload")
    expected = expected_controls(spec, split, key)
    validate_manifest_public_bindings(manifest, expected)
    expected_pages = contact_sheet_pages(spec, split, expected)
    expected_bundle = [page.manifest_entry() for page in expected_pages]
    if manifest["contact_sheet_bundle"] != expected_bundle:
        raise RuntimeError(f"{split} secret-derived contact-sheet bundle drift")
    expected_by_public_tuple = {
        control.public_binding_tuple: control for control in expected
    }
    expected_reveal: dict[str, dict[str, Any]] = {}
    for record in manifest["records"]:
        public_tuple = (
            record["anonymous_code"],
            record["control_commitment"],
            record["reference_commitment"],
            record["delta_commitment"],
        )
        control = expected_by_public_tuple[public_tuple]
        expected_reveal[control.anonymous_code] = {
            "anonymous_code": control.anonymous_code,
            "family": control.family,
            "private_role": control.private_role,
            "foundation_id": control.foundation_id,
            "duplicate_audit_group": control.duplicate_audit_group,
            "control_id": control.control_id,
            "condition_cluster_id": control.condition_cluster_id,
            "variant_index": control.variant_index,
            "replicate": control.replicate,
            "polarity": control.polarity,
            "parameters": control.parameters,
            "control_sha256": control.control_sha256,
            "reference_sha256": control.reference_sha256,
            "delta_float32_sha256": control.delta_float32_sha256,
        }
    actual_reveal = {item["anonymous_code"]: item for item in report["identity_reveal"]}
    if actual_reveal != expected_reveal:
        raise RuntimeError(f"{split} secret-derived identity reveal drift")


_DISPOSITION_PRECEDENCE = {"clean": 0, "warning": 1, "reject": 2}
_VISIBLE_TRUTH_FIELDS = (
    "grain_visible",
    "tiny_speck_visible",
    "microblob_visible",
    "short_line_visible",
    "parallel_bundle_visible",
)


def _endpoint_population_predicates() -> dict[str, Any]:
    return {
        "disposition_clean": lambda truth: truth["disposition"] == "clean",
        "disposition_warning": lambda truth: truth["disposition"] == "warning",
        "disposition_reject": lambda truth: truth["disposition"] == "reject",
        "severity_3": lambda truth: truth["severity_0_to_3"] == 3,
        "grain_visible_reject": lambda truth: truth["disposition"] == "reject"
        and truth["grain_visible"],
        "tiny_speck_visible_reject": lambda truth: truth["disposition"] == "reject"
        and truth["tiny_speck_visible"],
        "microblob_visible_reject": lambda truth: truth["disposition"] == "reject"
        and truth["microblob_visible"],
        "spot_visible_reject": lambda truth: truth["disposition"] == "reject"
        and (truth["tiny_speck_visible"] or truth["microblob_visible"]),
        "short_line_visible_reject": lambda truth: truth["disposition"] == "reject"
        and truth["short_line_visible"],
        "parallel_bundle_visible_reject": lambda truth: truth["disposition"] == "reject"
        and truth["parallel_bundle_visible"],
    }


def endpoint_population_codes(
    population: str, labels: dict[str, dict[str, Any]]
) -> list[str]:
    """Return record-level members; authority evaluation uses cluster truth below."""

    predicates = _endpoint_population_predicates()
    if population not in predicates:
        raise RuntimeError(f"unknown endpoint population: {population}")
    return [code for code, label in labels.items() if predicates[population](label)]


def aggregate_condition_cluster_truth(
    labels: dict[str, dict[str, Any]], clusters: dict[str, str]
) -> dict[str, dict[str, Any]]:
    """Aggregate artifact truth by condition cluster, conservatively and once.

    Disposition uses ``reject > warning > clean``, severity uses the maximum,
    and each visible-artifact flag is ORed across the metric-equivalent polarity
    members.  Codes and private identities are deliberately absent from the
    returned truth objects.
    """

    if not isinstance(labels, dict) or not isinstance(clusters, dict) or not clusters:
        raise RuntimeError("condition-cluster truth inputs must be non-empty objects")
    if not set(clusters).issubset(labels):
        raise RuntimeError("condition-cluster truth label coverage drift")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for code, cluster_id in clusters.items():
        if (
            not isinstance(code, str)
            or not code
            or not isinstance(cluster_id, str)
            or not cluster_id
        ):
            raise RuntimeError("condition-cluster truth identity drift")
        grouped.setdefault(cluster_id, []).append(labels[code])

    result: dict[str, dict[str, Any]] = {}
    for cluster_id, members in sorted(grouped.items()):
        dispositions = [member.get("disposition") for member in members]
        if any(
            disposition not in _DISPOSITION_PRECEDENCE for disposition in dispositions
        ):
            raise RuntimeError("condition-cluster truth disposition drift")
        severities = [member.get("severity_0_to_3") for member in members]
        if any(
            type(severity) is not int or not 0 <= severity <= 3
            for severity in severities
        ):
            raise RuntimeError("condition-cluster truth severity drift")
        for field in _VISIBLE_TRUTH_FIELDS:
            if any(type(member.get(field)) is not bool for member in members):
                raise RuntimeError(f"condition-cluster truth {field} drift")
        result[cluster_id] = {
            "disposition": max(
                dispositions, key=lambda value: _DISPOSITION_PRECEDENCE[value]
            ),
            "severity_0_to_3": max(severities),
            **{
                field: any(member[field] for member in members)
                for field in _VISIBLE_TRUTH_FIELDS
            },
        }
    return result


def endpoint_population_clusters(
    population: str, cluster_truth: dict[str, dict[str, Any]]
) -> list[str]:
    predicates = _endpoint_population_predicates()
    if population not in predicates:
        raise RuntimeError(f"unknown endpoint population: {population}")
    return [
        cluster_id
        for cluster_id, truth in cluster_truth.items()
        if predicates[population](truth)
    ]


def endpoint_population_count_audit(
    labels: dict[str, dict[str, Any]],
    clusters: dict[str, str],
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Return a measurement-independent endpoint population audit."""

    cluster_truth = aggregate_condition_cluster_truth(labels, clusters)
    endpoints: dict[str, Any] = {}
    for endpoint in spec["threshold_selection"]["endpoint_definitions"]:
        count = len(endpoint_population_clusters(endpoint["population"], cluster_truth))
        minimum = int(endpoint["minimum_unique_clusters"])
        endpoints[endpoint["id"]] = {
            "unique_cluster_count": count,
            "minimum_unique_clusters": minimum,
            "count_passed": count >= minimum,
        }
    return {
        "passed": all(item["count_passed"] for item in endpoints.values()),
        "endpoints": endpoints,
    }


def validate_endpoint_population_counts(
    labels: dict[str, dict[str, Any]],
    clusters: dict[str, str],
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Fail closed before measurement/selection when endpoint counts are short."""

    member_counts: dict[str, int] = {}
    for cluster_id in clusters.values():
        member_counts[cluster_id] = member_counts.get(cluster_id, 0) + 1
    if any(count != 2 for count in member_counts.values()):
        raise RuntimeError(
            "artifact condition clusters must contain exactly one polarity pair"
        )
    audit = endpoint_population_count_audit(labels, clusters, spec)
    if not audit["passed"]:
        shortages = [
            f"{endpoint_id}={item['unique_cluster_count']}<{item['minimum_unique_clusters']}"
            for endpoint_id, item in audit["endpoints"].items()
            if not item["count_passed"]
        ]
        raise RuntimeError(
            "endpoint population minimums are not satisfied: " + ", ".join(shortages)
        )
    return audit


def metric_equivalent_cluster_scores(
    measured: dict[str, dict[str, Any]],
    clusters: dict[str, str],
    metric: str,
) -> dict[str, float]:
    """Assert exact pair equivalence and return one score per cluster."""

    if not set(clusters).issubset(measured):
        raise RuntimeError("metric-equivalent cluster measurement coverage drift")
    members_by_cluster: dict[str, list[str]] = {}
    for code, cluster_id in clusters.items():
        members_by_cluster.setdefault(cluster_id, []).append(code)
    scores: dict[str, float] = {}
    for cluster_id, codes in sorted(members_by_cluster.items()):
        first_metrics = measured[codes[0]].get("metrics")
        if not isinstance(first_metrics, dict) or metric not in first_metrics:
            raise RuntimeError(
                f"metric-equivalent condition cluster metric missing: {cluster_id}"
            )
        if any(measured[code].get("metrics") != first_metrics for code in codes[1:]):
            raise RuntimeError(
                f"metric-equivalent condition cluster metric drift: {cluster_id}"
            )
        scores[cluster_id] = require_exact_real(
            first_metrics[metric],
            f"metric-equivalent condition cluster score[{cluster_id}]",
            minimum=0.0,
        )
    return scores


def cluster_macro_rate(
    codes: list[str],
    rejected_by_code: dict[str, bool],
    clusters: dict[str, str],
    expected_result: str,
) -> tuple[float, int, int]:
    grouped: dict[str, list[bool]] = {}
    for code in codes:
        cluster_id = clusters[code]
        grouped.setdefault(cluster_id, [])
        grouped[cluster_id].append(bool(rejected_by_code[code]))
    if not grouped:
        return 0.0, 0, 0
    cluster_scores: list[float] = []
    for observed in grouped.values():
        if len(set(observed)) != 1:
            raise RuntimeError(
                "metric-equivalent cluster received conflicting predictions"
            )
        correct = observed[0] if expected_result == "reject" else not observed[0]
        cluster_scores.append(float(correct))
    return float(sum(cluster_scores) / len(cluster_scores)), len(codes), len(grouped)


def evaluate_endpoints_from_measurements(
    threshold: float,
    measured: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    clusters: dict[str, str],
    split: str,
    spec: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if split not in {"calibration", "holdout"}:
        raise RuntimeError("invalid endpoint-evaluation split")
    if (
        set(measured) != set(labels)
        or not clusters
        or not set(clusters).issubset(measured)
    ):
        raise RuntimeError(f"{split} endpoint input code coverage drift")
    gate = spec["threshold_selection"]["hard_gate"]
    metric, direction = gate["metric"], gate["direction"]
    rejected = {
        code: (
            float(record["metrics"][metric]) > threshold
            if direction == "maximum"
            else float(record["metrics"][metric]) < threshold
        )
        for code, record in measured.items()
    }
    cluster_scores = metric_equivalent_cluster_scores(measured, clusters, metric)
    rejected_by_cluster = {
        cluster_id: (score > threshold if direction == "maximum" else score < threshold)
        for cluster_id, score in cluster_scores.items()
    }
    for code, cluster_id in clusters.items():
        rejected[code] = rejected_by_cluster[cluster_id]
    results = {
        code: {
            "passed": not failed,
            "failed_hard_gate": bool(failed),
            "hard_metric_value": float(measured[code]["metrics"][metric]),
        }
        for code, failed in rejected.items()
    }
    cluster_truth = aggregate_condition_cluster_truth(labels, clusters)
    performance: dict[str, Any] = {}
    for endpoint in spec["threshold_selection"]["endpoint_definitions"]:
        population_clusters = set(
            endpoint_population_clusters(endpoint["population"], cluster_truth)
        )
        codes = sorted(
            code
            for code, cluster_id in clusters.items()
            if cluster_id in population_clusters
        )
        rate, record_count, cluster_count = cluster_macro_rate(
            codes, rejected, clusters, endpoint["expected_result"]
        )
        minimum = float(endpoint[f"{split}_minimum"])
        minimum_clusters = int(endpoint["minimum_unique_clusters"])
        performance[endpoint["id"]] = {
            "record_count": record_count,
            "unique_cluster_count": cluster_count,
            "minimum_unique_clusters": minimum_clusters,
            "cluster_macro_rate": rate,
            "minimum_rate": minimum,
            "count_passed": cluster_count >= minimum_clusters,
            "rate_passed": rate >= minimum,
            "passed": cluster_count >= minimum_clusters and rate >= minimum,
        }
    return performance, results


def threshold_candidates(values: list[float]) -> list[float]:
    unique = sorted(set(float(value) for value in values))
    if not unique or any(not math.isfinite(value) for value in unique):
        raise RuntimeError("threshold metric values must be finite")
    epsilon = max(abs(unique[0]), abs(unique[-1]), 1.0) * 1e-9
    return sorted(
        {
            0.0,
            max(0.0, unique[0] - epsilon),
            *((left + right) / 2 for left, right in zip(unique, unique[1:])),
            unique[-1] + epsilon,
        }
    )


def select_hard_threshold_from_measurements(
    measured: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    clusters: dict[str, str],
    spec: dict[str, Any],
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any],
    dict[str, dict[str, Any]],
    str,
    dict[str, Any],
]:
    selection = spec["threshold_selection"]
    metric = selection["hard_gate"]["metric"]
    direction = selection["hard_gate"]["direction"]
    validate_endpoint_population_counts(labels, clusters, spec)
    cluster_scores = metric_equivalent_cluster_scores(measured, clusters, metric)
    authority_candidates: list[
        tuple[tuple[float, ...], float, dict[str, Any], dict[str, Any]]
    ] = []
    diagnostic_candidates: list[
        tuple[tuple[float, ...], float, dict[str, Any], dict[str, Any]]
    ] = []
    candidate_audit: list[dict[str, Any]] = []
    for threshold in threshold_candidates(list(cluster_scores.values())):
        performance, results = evaluate_endpoints_from_measurements(
            threshold, measured, labels, clusters, "calibration", spec
        )
        clean = performance["clean_acceptance"]
        warning = performance["warning_acceptance"]
        diagnostic_admissible = clean["count_passed"] and warning["count_passed"]
        diagnostic_admissible = diagnostic_admissible and clean[
            "cluster_macro_rate"
        ] >= float(selection["admissibility"]["clean_cluster_acceptance_minimum"])
        diagnostic_admissible = diagnostic_admissible and warning[
            "cluster_macro_rate"
        ] >= float(selection["admissibility"]["warning_cluster_acceptance_minimum"])
        inadmissible_reasons: list[str] = []
        for endpoint_id, endpoint in performance.items():
            if not endpoint["count_passed"]:
                inadmissible_reasons.append(f"{endpoint_id}-cluster-count")
            if not endpoint["rate_passed"]:
                inadmissible_reasons.append(f"{endpoint_id}-rate")
        all_endpoints_passed = not inadmissible_reasons
        objective = tuple(_selected_objective(performance, float(threshold), direction))
        candidate_audit.append(
            {
                "threshold": float(threshold),
                "admissible": all_endpoints_passed,
                "inadmissible_reasons": inadmissible_reasons,
                "objective": list(objective),
                "clean_cluster_count": clean["unique_cluster_count"],
                "warning_cluster_count": warning["unique_cluster_count"],
                "clean_cluster_acceptance": clean["cluster_macro_rate"],
                "warning_cluster_acceptance": warning["cluster_macro_rate"],
                "all_endpoints_passed": all_endpoints_passed,
            }
        )
        candidate = (objective, float(threshold), performance, results)
        if diagnostic_admissible:
            diagnostic_candidates.append(candidate)
        if all_endpoints_passed:
            authority_candidates.append(candidate)
    if not diagnostic_candidates:
        raise RuntimeError("no clean/warning-admissible diagnostic threshold")
    (
        diagnostic_objective,
        diagnostic_threshold,
        diagnostic_performance,
        diagnostic_results,
    ) = max(diagnostic_candidates, key=lambda item: item[0])
    audit = {
        "candidate_count": len(candidate_audit),
        "admissible_candidate_count": len(authority_candidates),
        "selected_threshold": None,
        "selected_objective": None,
        "diagnostic_candidate_count": len(diagnostic_candidates),
        "diagnostic_best_threshold": diagnostic_threshold,
        "diagnostic_best_objective": list(diagnostic_objective),
        "candidates": candidate_audit,
    }
    if not authority_candidates:
        return (
            None,
            diagnostic_performance,
            diagnostic_results,
            "no-endpoint-admissible-threshold",
            audit,
        )
    selected_objective, threshold, performance, results = max(
        authority_candidates, key=lambda item: item[0]
    )
    audit["selected_threshold"] = threshold
    audit["selected_objective"] = list(selected_objective)
    hard_threshold = {
        "metric": metric,
        "direction": direction,
        "threshold": threshold,
        "calibration_clean_cluster_acceptance": performance["clean_acceptance"][
            "cluster_macro_rate"
        ],
        "calibration_warning_cluster_acceptance": performance["warning_acceptance"][
            "cluster_macro_rate"
        ],
        "calibration_reject_cluster_detection": performance["reject_detection"][
            "cluster_macro_rate"
        ],
        "calibration_severity3_cluster_detection": performance["severity3_detection"][
            "cluster_macro_rate"
        ],
        "selection_objective": selection["objective_order"],
    }
    require_exact_keys(hard_threshold, HARD_THRESHOLD_KEYS, "selected hard threshold")
    validate_hard_threshold(hard_threshold, spec)
    return hard_threshold, performance, results, "selected-and-passed", audit


def validate_report_evaluation_bindings(
    report: dict[str, Any],
    manifest: dict[str, Any],
    labels: dict[str, dict[str, Any]],
    split: str,
    spec: dict[str, Any],
) -> None:
    context = f"{split} report evaluation bindings"
    records = manifest.get("records")
    if not isinstance(records, list):
        raise RuntimeError(f"{context} manifest records must be a list")
    records_by_code: dict[str, dict[str, Any]] = {}
    for record in records:
        code = record.get("anonymous_code") if isinstance(record, dict) else None
        if not isinstance(code, str) or code in records_by_code:
            raise RuntimeError(f"{context} manifest code drift")
        records_by_code[code] = record
    reveal_by_code = {
        item["anonymous_code"]: item for item in report["identity_reveal"]
    }
    if set(records_by_code) != set(reveal_by_code):
        raise RuntimeError(f"{context} manifest/reveal code coverage drift")
    measured = {item["anonymous_code"]: item for item in report["measurements"]}
    eligible_role = spec["threshold_selection"]["endpoint_eligible_private_role"]
    clusters = {
        item["anonymous_code"]: item["condition_cluster_id"]
        for item in report["identity_reveal"]
        if item["private_role"] == eligible_role
    }
    if split == "calibration":
        expected_threshold, expected_endpoints, expected_results, status, audit = (
            select_hard_threshold_from_measurements(measured, labels, clusters, spec)
        )
        if (
            report["hard_threshold"] != expected_threshold
            or report["endpoint_performance"] != expected_endpoints
            or report["results_by_code"] != expected_results
            or report["selection_status"] != status
            or report["threshold_selection_audit"] != audit
            or report["passed"] is not (status == "selected-and-passed")
        ):
            raise RuntimeError(f"{context} full selector recomputation drift")
    elif split == "holdout":
        threshold = float(report["hard_threshold"]["threshold"])
        expected_endpoints, expected_results = evaluate_endpoints_from_measurements(
            threshold, measured, labels, clusters, split, spec
        )
        if (
            report["endpoint_performance"] != expected_endpoints
            or report["results_by_code"] != expected_results
            or report["passed"]
            is not all(endpoint["passed"] for endpoint in expected_endpoints.values())
        ):
            raise RuntimeError(f"{context} endpoint recomputation drift")
    else:
        raise RuntimeError(f"{context} invalid split")


def validate_failure(value: Any, context: str) -> None:
    if value is None:
        return
    require_exact_keys(value, FAILURE_KEYS, f"{context} failure")
    for key in FAILURE_KEYS:
        if not isinstance(value[key], str) or not value[key] or len(value[key]) > 512:
            raise RuntimeError(f"{context} failure field is invalid: {key}")


def validate_metric_values(metrics: Any, spec: dict[str, Any], context: str) -> None:
    require_exact_keys(metrics, METRIC_KEYS, context)
    expected_pixels = int(spec["canvas"]["metric_window"]["pixels"])
    for key in METRIC_INTEGER_KEYS:
        require_exact_int(metrics[key], f"{context}.{key}", 0)
    if metrics["eligible_pixels"] != expected_pixels:
        raise RuntimeError(f"{context}.eligible_pixels contract drift")
    for key in METRIC_KEYS - METRIC_INTEGER_KEYS:
        require_exact_real(metrics[key], f"{context}.{key}", minimum=0.0)
    for key in ("grain_coherence_2_to_13", "parallel_pair_ratio"):
        require_exact_real(
            metrics[key],
            f"{context}.{key}",
            minimum=0.0,
            maximum=1.0,
        )
    for key in SCORE_FIELDS:
        require_exact_real(metrics[key], f"{context}.{key}", minimum=0.0, maximum=1.0)
    recomputed = recompute_branch_scores(metrics, spec["metric_definition"])
    if any(float(metrics[key]) != value for key, value in recomputed.items()):
        raise RuntimeError(f"{context} branch/composite recomputation drift")


def validate_endpoint_performance(
    value: Any, spec: dict[str, Any], split: str, context: str
) -> None:
    definitions = {
        endpoint["id"]: endpoint
        for endpoint in spec["threshold_selection"]["endpoint_definitions"]
    }
    require_exact_keys(value, set(definitions), context)
    for endpoint_id, endpoint in value.items():
        definition = definitions[endpoint_id]
        require_exact_keys(
            endpoint, ENDPOINT_PERFORMANCE_KEYS, f"{context}.{endpoint_id}"
        )
        record_count = require_exact_int(
            endpoint["record_count"], f"{context}.{endpoint_id}.record_count", 0
        )
        cluster_count = require_exact_int(
            endpoint["unique_cluster_count"],
            f"{context}.{endpoint_id}.unique_cluster_count",
            0,
        )
        minimum_clusters = require_exact_int(
            endpoint["minimum_unique_clusters"],
            f"{context}.{endpoint_id}.minimum_unique_clusters",
            1,
        )
        if cluster_count > record_count:
            raise RuntimeError(f"{context}.{endpoint_id} cluster count exceeds records")
        expected_minimum_clusters = definition["minimum_unique_clusters"]
        if minimum_clusters != expected_minimum_clusters:
            raise RuntimeError(f"{context}.{endpoint_id} minimum cluster drift")
        rate = require_exact_real(
            endpoint["cluster_macro_rate"],
            f"{context}.{endpoint_id}.cluster_macro_rate",
            minimum=0.0,
            maximum=1.0,
        )
        minimum_rate = require_exact_real(
            endpoint["minimum_rate"],
            f"{context}.{endpoint_id}.minimum_rate",
            minimum=0.0,
            maximum=1.0,
        )
        if minimum_rate != float(definition[f"{split}_minimum"]):
            raise RuntimeError(f"{context}.{endpoint_id} minimum rate drift")
        for key in ("count_passed", "rate_passed", "passed"):
            if type(endpoint[key]) is not bool:
                raise RuntimeError(f"{context}.{endpoint_id}.{key} must be exact bool")
        count_passed = cluster_count >= minimum_clusters
        rate_passed = rate >= minimum_rate
        if (
            endpoint["count_passed"] is not count_passed
            or endpoint["rate_passed"] is not rate_passed
            or endpoint["passed"] is not (count_passed and rate_passed)
        ):
            raise RuntimeError(f"{context}.{endpoint_id} pass recomputation drift")


def validate_threshold_selection_audit(
    value: Any, spec: dict[str, Any], context: str
) -> None:
    require_exact_keys(value, THRESHOLD_AUDIT_KEYS, context)
    candidates = value["candidates"]
    if not isinstance(candidates, list):
        raise RuntimeError(f"{context}.candidates must be a list")
    candidate_count = require_exact_int(value["candidate_count"], context, 1)
    admissible_count = require_exact_int(
        value["admissible_candidate_count"], context, 0
    )
    if candidate_count != len(candidates):
        raise RuntimeError(f"{context} candidate count drift")
    observed_admissible = 0
    observed_thresholds: list[float] = []
    admissible_objectives: list[tuple[float, ...]] = []
    diagnostic_candidates: list[dict[str, Any]] = []
    diagnostic_objectives: list[tuple[float, ...]] = []
    allowed_reasons = {
        reason
        for endpoint_id in EXPECTED_ENDPOINT_IDS
        for reason in (f"{endpoint_id}-cluster-count", f"{endpoint_id}-rate")
    }
    endpoint_definitions = {
        endpoint["id"]: endpoint
        for endpoint in spec["threshold_selection"]["endpoint_definitions"]
    }
    clean_definition = endpoint_definitions["clean_acceptance"]
    warning_definition = endpoint_definitions["warning_acceptance"]
    diagnostic_admissibility = spec["threshold_selection"]["admissibility"]
    for index, candidate in enumerate(candidates):
        item_context = f"{context}.candidates[{index}]"
        require_exact_keys(candidate, THRESHOLD_AUDIT_CANDIDATE_KEYS, item_context)
        observed_thresholds.append(
            require_exact_real(
                candidate["threshold"], f"{item_context}.threshold", minimum=0.0
            )
        )
        if (
            type(candidate["admissible"]) is not bool
            or type(candidate["all_endpoints_passed"]) is not bool
        ):
            raise RuntimeError(f"{item_context} booleans must be exact")
        reasons = candidate["inadmissible_reasons"]
        if not isinstance(reasons, list) or any(
            not isinstance(reason, str) or not reason for reason in reasons
        ):
            raise RuntimeError(f"{item_context} reasons must be non-empty strings")
        if len(reasons) != len(set(reasons)) or any(
            reason not in allowed_reasons for reason in reasons
        ):
            raise RuntimeError(f"{item_context} inadmissible reasons drift")
        if candidate["admissible"] is not candidate["all_endpoints_passed"]:
            raise RuntimeError(f"{item_context} endpoint admissibility drift")
        objective = candidate["objective"]
        if not isinstance(objective, list) or len(objective) != len(
            spec["threshold_selection"]["objective_order"]
        ):
            raise RuntimeError(f"{item_context} objective drift")
        normalized_objective = tuple(
            require_exact_real(component, f"{item_context}.objective")
            for component in objective
        )
        for component in normalized_objective[:6]:
            if not 0.0 <= component <= 1.0:
                raise RuntimeError(f"{item_context} objective rate drift")
        if candidate["admissible"]:
            observed_admissible += 1
            if reasons:
                raise RuntimeError(f"{item_context} admissible objective drift")
            admissible_objectives.append(normalized_objective)
        elif not reasons:
            raise RuntimeError(f"{item_context} inadmissible audit drift")
        for key in ("clean_cluster_count", "warning_cluster_count"):
            require_exact_int(candidate[key], f"{item_context}.{key}", 0)
        for key in ("clean_cluster_acceptance", "warning_cluster_acceptance"):
            require_exact_real(
                candidate[key], f"{item_context}.{key}", minimum=0.0, maximum=1.0
            )
        diagnostic_admissible = (
            candidate["clean_cluster_count"]
            >= int(clean_definition["minimum_unique_clusters"])
            and candidate["warning_cluster_count"]
            >= int(warning_definition["minimum_unique_clusters"])
            and float(candidate["clean_cluster_acceptance"])
            >= float(diagnostic_admissibility["clean_cluster_acceptance_minimum"])
            and float(candidate["warning_cluster_acceptance"])
            >= float(diagnostic_admissibility["warning_cluster_acceptance_minimum"])
        )
        if diagnostic_admissible:
            diagnostic_candidates.append(candidate)
            diagnostic_objectives.append(normalized_objective)
    if observed_admissible != admissible_count:
        raise RuntimeError(f"{context} admissible count drift")
    if observed_thresholds != sorted(set(observed_thresholds)):
        raise RuntimeError(f"{context} thresholds must be unique and increasing")
    diagnostic_count = require_exact_int(
        value["diagnostic_candidate_count"],
        f"{context}.diagnostic_candidate_count",
        1,
    )
    if diagnostic_count != len(diagnostic_candidates):
        raise RuntimeError(f"{context} diagnostic candidate count drift")
    diagnostic_threshold = require_exact_real(
        value["diagnostic_best_threshold"],
        f"{context}.diagnostic_best_threshold",
        minimum=0.0,
    )
    diagnostic_objective = value["diagnostic_best_objective"]
    if not isinstance(diagnostic_objective, list) or len(diagnostic_objective) != len(
        spec["threshold_selection"]["objective_order"]
    ):
        raise RuntimeError(f"{context}.diagnostic_best_objective drift")
    for component in diagnostic_objective:
        require_exact_real(component, f"{context}.diagnostic_best_objective")
    diagnostic_matching = [
        candidate
        for candidate in diagnostic_candidates
        if float(candidate["threshold"]) == diagnostic_threshold
    ]
    if (
        len(diagnostic_matching) != 1
        or diagnostic_matching[0]["objective"] != diagnostic_objective
        or tuple(float(component) for component in diagnostic_objective)
        != max(diagnostic_objectives)
    ):
        raise RuntimeError(f"{context} diagnostic best candidate/objective drift")
    if admissible_count == 0:
        if (
            value["selected_threshold"] is not None
            or value["selected_objective"] is not None
        ):
            raise RuntimeError(f"{context} selected an inadmissible threshold")
    else:
        require_exact_real(
            value["selected_threshold"], f"{context}.selected_threshold", minimum=0.0
        )
        selected_objective = value["selected_objective"]
        if not isinstance(selected_objective, list) or len(selected_objective) != len(
            spec["threshold_selection"]["objective_order"]
        ):
            raise RuntimeError(f"{context}.selected_objective drift")
        for component in selected_objective:
            require_exact_real(component, f"{context}.selected_objective")
        selected_threshold = float(value["selected_threshold"])
        matching = [
            candidate
            for candidate in candidates
            if candidate["admissible"]
            and float(candidate["threshold"]) == selected_threshold
        ]
        if (
            len(matching) != 1
            or matching[0]["objective"] != selected_objective
            or tuple(float(component) for component in selected_objective)
            != max(admissible_objectives)
        ):
            raise RuntimeError(f"{context} selected candidate/objective drift")


def validate_results_measurements_and_reveal(
    report: dict[str, Any],
    spec: dict[str, Any],
    split: str,
    context: str,
    hard_threshold: dict[str, Any] | None,
) -> None:
    if split not in {"calibration", "holdout"}:
        raise RuntimeError(f"{context} invalid split")
    measurements = report["measurements"]
    reveal = report["identity_reveal"]
    results = report["results_by_code"]
    diagnostics = report["diagnostic_flags_by_code"]
    expected_count = int(spec["contact_sheets"]["expected_controls_per_split"])
    if not isinstance(measurements, list) or len(measurements) != expected_count:
        raise RuntimeError(f"{context} measurement count drift")
    measurement_by_code: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(measurements):
        require_exact_keys(item, MEASUREMENT_KEYS, f"{context}.measurements[{index}]")
        code = item["anonymous_code"]
        if (
            not isinstance(code, str)
            or re.fullmatch(r"[0-9a-f]{24}", code) is None
            or code in measurement_by_code
        ):
            raise RuntimeError(f"{context} invalid/duplicate measurement code")
        validate_metric_values(item["metrics"], spec, f"{context}.metrics[{code}]")
        measurement_by_code[code] = item["metrics"]
    codes = set(measurement_by_code)
    require_exact_keys(results, codes, f"{context}.results_by_code")
    require_exact_keys(diagnostics, codes, f"{context}.diagnostic_flags_by_code")
    allowed_flags = {
        "grain-branch-diagnostic",
        "spot-branch-diagnostic",
        "finite-line-branch-diagnostic",
        "parallel-bundle-branch-diagnostic",
    }
    for code in codes:
        result = results[code]
        require_exact_keys(result, RESULT_KEYS, f"{context}.result[{code}]")
        if (
            type(result["passed"]) is not bool
            or type(result["failed_hard_gate"]) is not bool
        ):
            raise RuntimeError(f"{context}.result[{code}] booleans must be exact")
        metric_value = require_exact_real(
            result["hard_metric_value"],
            f"{context}.result[{code}].hard_metric_value",
            minimum=0.0,
        )
        hard_metric = spec["threshold_selection"]["hard_gate"]["metric"]
        if metric_value != float(measurement_by_code[code][hard_metric]):
            raise RuntimeError(f"{context}.result[{code}] metric binding drift")
        if result["passed"] is not (not result["failed_hard_gate"]):
            raise RuntimeError(f"{context}.result[{code}] pass complement drift")
        if hard_threshold is not None:
            threshold = float(hard_threshold["threshold"])
            failed = (
                metric_value > threshold
                if hard_threshold["direction"] == "maximum"
                else metric_value < threshold
            )
            if result["failed_hard_gate"] is not failed:
                raise RuntimeError(
                    f"{context}.result[{code}] threshold recomputation drift"
                )
        flags = diagnostics[code]
        if (
            not isinstance(flags, list)
            or len(flags) != len(set(flags))
            or any(flag not in allowed_flags for flag in flags)
        ):
            raise RuntimeError(f"{context}.diagnostic_flags[{code}] drift")
        expected_flags: list[str] = []
        metrics = measurement_by_code[code]
        for metric, name in (
            ("grain_score", "grain-branch-diagnostic"),
            ("spot_score", "spot-branch-diagnostic"),
            ("finite_line_score", "finite-line-branch-diagnostic"),
            ("parallel_bundle_score", "parallel-bundle-branch-diagnostic"),
        ):
            if float(metrics[metric]) > 0.5:
                expected_flags.append(name)
        if flags != expected_flags:
            raise RuntimeError(
                f"{context}.diagnostic_flags[{code}] recomputation drift"
            )
    if not isinstance(reveal, list) or len(reveal) != expected_count:
        raise RuntimeError(f"{context} identity reveal count drift")
    reveal_codes: set[str] = set()
    control_ids: set[str] = set()
    cluster_ids: set[str] = set()
    family_specs = {family["id"]: family for family in spec["control_families"]}
    allowed_families = set(family_specs)
    allowed_foundations = {
        item["id"] for item in spec["foundation_corpus"]["foundations"]
    }
    cluster_members: dict[str, list[dict[str, Any]]] = {}
    observed_records_per_family = {family_id: 0 for family_id in family_specs}
    for index, item in enumerate(reveal):
        require_exact_keys(item, IDENTITY_REVEAL_KEYS, f"{context}.identity[{index}]")
        code = item["anonymous_code"]
        if code not in codes or code in reveal_codes:
            raise RuntimeError(f"{context} identity code drift")
        reveal_codes.add(code)
        for field in ("control_id", "condition_cluster_id"):
            if re.fullmatch(r"[0-9a-f]{24}", item[field] or "") is None:
                raise RuntimeError(f"{context}.identity[{index}].{field} drift")
        if item["control_id"] in control_ids:
            raise RuntimeError(f"{context} duplicate control identity")
        control_ids.add(item["control_id"])
        cluster_ids.add(item["condition_cluster_id"])
        cluster_members.setdefault(item["condition_cluster_id"], []).append(item)
        for field in ("control_sha256", "reference_sha256", "delta_float32_sha256"):
            if re.fullmatch(r"[0-9a-f]{64}", item[field] or "") is None:
                raise RuntimeError(f"{context}.identity[{index}].{field} drift")
        if (
            item["family"] not in allowed_families
            or require_exact_int(item["variant_index"], "variant_index", 0) < 0
            or require_exact_int(item["replicate"], "replicate", 0) < 0
            or type(item["polarity"]) is not int
            or item["polarity"] not in {-1, 1}
            or not isinstance(item["parameters"], dict)
            or item["private_role"]
            not in {"artifact", "protocol-zero", "duplicate-audit"}
            or item["foundation_id"] not in allowed_foundations
            or item["duplicate_audit_group"] not in {None, "clean", "artifact"}
        ):
            raise RuntimeError(f"{context}.identity[{index}] type drift")
        if (item["private_role"] == "duplicate-audit") is (
            item["duplicate_audit_group"] is None
        ):
            raise RuntimeError(
                f"{context}.identity[{index}] duplicate-audit binding drift"
            )
        family = family_specs[item["family"]]
        if (
            item["polarity"] not in family["polarities"]
            or item["private_role"] != family["private_role"]
        ):
            raise RuntimeError(f"{context}.identity[{index}] catalog binding drift")
        role = item["private_role"]
        variant_index = item["variant_index"]
        replicate = item["replicate"]
        if role == "artifact":
            valid_member = (
                0 <= variant_index < 20
                and replicate == 0
                and item["duplicate_audit_group"] is None
            )
        elif role == "protocol-zero":
            valid_member = (
                item["family"] == "protocol-zero"
                and 0 <= variant_index < 16
                and replicate == 0
                and item["polarity"] == 1
                and item["duplicate_audit_group"] is None
            )
        else:
            expected_group = {0: "clean", 1: "artifact"}.get(variant_index)
            valid_member = (
                item["family"] == "duplicate-audit"
                and replicate in {0, 1}
                and item["polarity"] == 1
                and item["duplicate_audit_group"] == expected_group
            )
        if not valid_member:
            raise RuntimeError(
                f"{context}.identity[{index}] role-specific catalog drift"
            )
        observed_records_per_family[item["family"]] += 1
    if reveal_codes != codes:
        raise RuntimeError(f"{context} identity reveal coverage drift")
    if (
        len({item["control_sha256"] for item in reveal}) != expected_count
        or len({item["reference_sha256"] for item in reveal}) != expected_count
    ):
        raise RuntimeError(f"{context} private payload uniqueness drift")
    expected_clusters = int(
        spec["independent_condition_clusters"]["expected_unique_clusters_per_split"]
    )
    if len(control_ids) != expected_count or len(cluster_ids) != expected_clusters:
        raise RuntimeError(f"{context} identity cardinality drift")
    expected_records_per_family = {
        family_id: int(family["expected_records_per_split"])
        for family_id, family in family_specs.items()
    }
    if observed_records_per_family != expected_records_per_family:
        raise RuntimeError(f"{context} per-family record cardinality drift")
    observed_clusters_per_family = {family_id: 0 for family_id in family_specs}
    observed_clusters_per_role = {
        "artifact": 0,
        "protocol-zero": 0,
        "duplicate-audit": 0,
    }
    expected_zero_metrics: dict[str, Any] = {key: 0.0 for key in METRIC_KEYS}
    for key in METRIC_INTEGER_KEYS:
        expected_zero_metrics[key] = 0
    expected_zero_metrics["eligible_pixels"] = int(
        spec["canvas"]["metric_window"]["pixels"]
    )
    for cluster_id, members in cluster_members.items():
        private_identities = {
            (
                item["private_role"],
                item["family"],
                item["foundation_id"],
                item["duplicate_audit_group"],
                item["variant_index"],
                canonical_json_bytes(item["parameters"]),
            )
            for item in members
        }
        if len(private_identities) != 1:
            raise RuntimeError(
                f"{context} cluster private-identity drift: {cluster_id}"
            )
        family_id = members[0]["family"]
        family = family_specs[family_id]
        role = members[0]["private_role"]
        expected_members = {
            "artifact": [(-1, 0), (1, 0)],
            "protocol-zero": [(1, 0)],
            "duplicate-audit": [(1, 0), (1, 1)],
        }[role]
        actual_members = sorted(
            (item["polarity"], item["replicate"]) for item in members
        )
        if actual_members != expected_members:
            raise RuntimeError(
                f"{context} cluster polarity/replicate drift: {cluster_id}"
            )
        reference_hashes = {item["reference_sha256"] for item in members}
        control_hashes = {item["control_sha256"] for item in members}
        delta_hashes = {item["delta_float32_sha256"] for item in members}
        if role in {"artifact", "duplicate-audit"} and (
            len(reference_hashes) != 2 or len(control_hashes) != 2
        ):
            raise RuntimeError(
                f"{context} private reference/control uniqueness drift: {cluster_id}"
            )
        if role == "artifact" and len(delta_hashes) != 2:
            raise RuntimeError(
                f"{context} artifact polarity delta SHA drift: {cluster_id}"
            )
        if role == "protocol-zero" and any(
            item["control_sha256"] != item["reference_sha256"] for item in members
        ):
            raise RuntimeError(f"{context} protocol-zero byte drift: {cluster_id}")
        member_metrics = [
            measurement_by_code[item["anonymous_code"]] for item in members
        ]
        if role in {"artifact", "duplicate-audit"} and any(
            metrics != member_metrics[0] for metrics in member_metrics[1:]
        ):
            raise RuntimeError(f"{context} paired metric symmetry drift: {cluster_id}")
        member_results = [results[item["anonymous_code"]] for item in members]
        if role in {"artifact", "duplicate-audit"} and any(
            result != member_results[0] for result in member_results[1:]
        ):
            raise RuntimeError(
                f"{context} paired one-prediction result drift: {cluster_id}"
            )
        if role == "protocol-zero" and member_metrics != [expected_zero_metrics]:
            raise RuntimeError(f"{context} protocol-zero metric drift: {cluster_id}")
        if role == "duplicate-audit":
            if len(delta_hashes) != 1:
                raise RuntimeError(
                    f"{context} semantic-audit requested-delta drift: {cluster_id}"
                )
            clean_group = members[0]["duplicate_audit_group"] == "clean"
            byte_equal = [
                item["control_sha256"] == item["reference_sha256"] for item in members
            ]
            if any(value is not clean_group for value in byte_equal):
                raise RuntimeError(
                    f"{context} semantic-audit zero/nonzero drift: {cluster_id}"
                )
            if clean_group and any(
                metrics != expected_zero_metrics for metrics in member_metrics
            ):
                raise RuntimeError(
                    f"{context} clean duplicate-audit metric drift: {cluster_id}"
                )
        observed_clusters_per_family[family_id] += 1
        observed_clusters_per_role[role] += 1
    expected_clusters_per_family = {
        family_id: int(family["expected_clusters_per_split"])
        for family_id, family in family_specs.items()
    }
    if observed_clusters_per_family != expected_clusters_per_family:
        raise RuntimeError(f"{context} per-family cluster cardinality drift")
    cluster_contract = spec["independent_condition_clusters"]
    expected_clusters_per_role = {
        "artifact": int(cluster_contract["expected_artifact_clusters_per_split"]),
        "protocol-zero": int(
            cluster_contract["expected_protocol_zero_clusters_per_split"]
        ),
        "duplicate-audit": int(
            cluster_contract["expected_duplicate_audit_clusters_per_split"]
        ),
    }
    if observed_clusters_per_role != expected_clusters_per_role:
        raise RuntimeError(f"{context} per-role cluster cardinality drift")


def _validate_normal_report_flags(report: dict[str, Any], context: str) -> None:
    validate_failure(report["failure"], context)
    if report["failure"] is not None:
        raise RuntimeError(f"{context} normal report cannot contain a failure")
    for key in ("passed", "one_shot_consumed"):
        if type(report[key]) is not bool:
            raise RuntimeError(f"{context}.{key} must be exact bool")
    if report["one_shot_consumed"] is not True:
        raise RuntimeError(f"{context} must record the consumed one-shot")
    parse_utc_timestamp(report["evaluated_at"], f"{context} evaluated_at")


def _calibration_candidate_thresholds(
    report: dict[str, Any], spec: dict[str, Any]
) -> list[float]:
    metric = spec["threshold_selection"]["hard_gate"]["metric"]
    eligible_role = spec["threshold_selection"]["endpoint_eligible_private_role"]
    measured = {item["anonymous_code"]: item for item in report["measurements"]}
    clusters = {
        item["anonymous_code"]: item["condition_cluster_id"]
        for item in report["identity_reveal"]
        if item["private_role"] == eligible_role
    }
    scores = metric_equivalent_cluster_scores(measured, clusters, metric)
    return threshold_candidates(list(scores.values()))


def _selected_objective(
    endpoints: dict[str, Any], threshold: float, direction: str
) -> list[float]:
    artifact_rates = [
        float(endpoints[name]["cluster_macro_rate"])
        for name in (
            "grain_reject_detection",
            "tiny_speck_reject_detection",
            "microblob_reject_detection",
            "short_line_reject_detection",
            "parallel_bundle_reject_detection",
        )
    ]
    return [
        min(artifact_rates),
        float(endpoints["spot_reject_detection"]["cluster_macro_rate"]),
        float(endpoints["reject_detection"]["cluster_macro_rate"]),
        float(endpoints["severity3_detection"]["cluster_macro_rate"]),
        float(endpoints["clean_acceptance"]["cluster_macro_rate"]),
        float(endpoints["warning_acceptance"]["cluster_macro_rate"]),
        -threshold if direction == "maximum" else threshold,
    ]


def _validate_current_candidate_binding(
    candidate: dict[str, Any], endpoints: dict[str, Any], context: str
) -> None:
    clean = endpoints["clean_acceptance"]
    warning = endpoints["warning_acceptance"]
    expected = {
        "clean_cluster_count": clean["unique_cluster_count"],
        "warning_cluster_count": warning["unique_cluster_count"],
        "clean_cluster_acceptance": clean["cluster_macro_rate"],
        "warning_cluster_acceptance": warning["cluster_macro_rate"],
        "all_endpoints_passed": all(
            endpoint["passed"] for endpoint in endpoints.values()
        ),
    }
    if any(candidate[key] != value for key, value in expected.items()):
        raise RuntimeError(f"{context} endpoint/candidate binding drift")


def validate_calibration_report_nested(report: Any, spec: dict[str, Any]) -> None:
    context = "calibration report"
    require_exact_keys(report, CALIBRATION_REPORT_KEYS, context)
    if (
        report["artifact"] != "microtexture-v2-r6-calibration-report"
        or report["schema_version"] != "microtexture-v2-r6-calibration-report/2"
        or report["spec_sha256"] != SPEC_SHA256
    ):
        raise RuntimeError(f"{context} identity/schema drift")
    _validate_normal_report_flags(report, context)
    gate = spec["threshold_selection"]["hard_gate"]
    if report["hard_gate"] != gate:
        raise RuntimeError(f"{context} hard-gate drift")
    validate_endpoint_performance(
        report["endpoint_performance"], spec, "calibration", context
    )
    validate_threshold_selection_audit(
        report["threshold_selection_audit"],
        spec,
        f"{context}.threshold_selection_audit",
    )
    audit = report["threshold_selection_audit"]
    expected_candidates = _calibration_candidate_thresholds(report, spec)
    actual_candidates = [float(item["threshold"]) for item in audit["candidates"]]
    if actual_candidates != expected_candidates:
        raise RuntimeError(f"{context} threshold candidate derivation drift")
    endpoints = report["endpoint_performance"]
    all_endpoints_passed = all(endpoint["passed"] for endpoint in endpoints.values())
    status = report["selection_status"]
    threshold = report["hard_threshold"]
    if status == "no-endpoint-admissible-threshold":
        if (
            threshold is not None
            or audit["admissible_candidate_count"] != 0
            or report["passed"] is not False
        ):
            raise RuntimeError(f"{context} no-endpoint-admissible status drift")
        current_candidate = next(
            (
                item
                for item in audit["candidates"]
                if float(item["threshold"]) == float(audit["diagnostic_best_threshold"])
            ),
            None,
        )
        if current_candidate is None:
            raise RuntimeError(f"{context} diagnostic candidate binding drift")
        evaluation_threshold = {
            "metric": gate["metric"],
            "direction": gate["direction"],
            "threshold": current_candidate["threshold"],
        }
    elif status == "selected-and-passed":
        validate_hard_threshold(threshold, spec)
        if audit["admissible_candidate_count"] < 1 or float(
            threshold["threshold"]
        ) != float(audit["selected_threshold"]):
            raise RuntimeError(f"{context} selected threshold/audit drift")
        current_candidate = next(
            (
                item
                for item in audit["candidates"]
                if float(item["threshold"]) == float(threshold["threshold"])
            ),
            None,
        )
        if current_candidate is None or not current_candidate["admissible"]:
            raise RuntimeError(f"{context} selected candidate missing/inadmissible")
        expected_objective = _selected_objective(
            endpoints, float(threshold["threshold"]), threshold["direction"]
        )
        if audit["selected_objective"] != expected_objective:
            raise RuntimeError(f"{context} selected objective recomputation drift")
        rate_bindings = {
            "calibration_clean_cluster_acceptance": "clean_acceptance",
            "calibration_warning_cluster_acceptance": "warning_acceptance",
            "calibration_reject_cluster_detection": "reject_detection",
            "calibration_severity3_cluster_detection": "severity3_detection",
        }
        if any(
            float(threshold[target]) != float(endpoints[source]["cluster_macro_rate"])
            for target, source in rate_bindings.items()
        ):
            raise RuntimeError(f"{context} hard-threshold endpoint binding drift")
        if not all_endpoints_passed or report["passed"] is not True:
            raise RuntimeError(f"{context} selected status/pass drift")
        evaluation_threshold = threshold
    else:
        raise RuntimeError(f"{context} selection status drift")
    _validate_current_candidate_binding(current_candidate, endpoints, context)
    validate_results_measurements_and_reveal(
        report, spec, "calibration", context, evaluation_threshold
    )


def validate_holdout_report_nested(
    report: Any,
    spec: dict[str, Any],
    expected_hard_threshold: dict[str, Any] | None = None,
) -> None:
    context = "holdout report"
    require_exact_keys(report, HOLDOUT_REPORT_KEYS, context)
    if (
        report["artifact"] != "microtexture-v2-r6-holdout-report"
        or report["schema_version"] != "microtexture-v2-r6-holdout-report/2"
        or report["authority"] is not True
        or report["spec_sha256"] != SPEC_SHA256
    ):
        raise RuntimeError(f"{context} identity/schema/authority drift")
    _validate_normal_report_flags(report, context)
    if (
        type(report["threshold_changes_authorized"]) is not bool
        or report["threshold_changes_authorized"] is not False
    ):
        raise RuntimeError(f"{context} threshold-change authorization drift")
    if report["hard_gate"] != spec["threshold_selection"]["hard_gate"]:
        raise RuntimeError(f"{context} hard-gate drift")
    validate_hard_threshold(report["hard_threshold"], spec)
    if (
        expected_hard_threshold is not None
        and report["hard_threshold"] != expected_hard_threshold
    ):
        raise RuntimeError(f"{context} frozen hard-threshold drift")
    validate_endpoint_performance(
        report["endpoint_performance"], spec, "holdout", context
    )
    all_endpoints_passed = all(
        endpoint["passed"] for endpoint in report["endpoint_performance"].values()
    )
    if report["passed"] is not all_endpoints_passed:
        raise RuntimeError(f"{context} endpoint/pass recomputation drift")
    validate_results_measurements_and_reveal(
        report, spec, "holdout", context, report["hard_threshold"]
    )


def validate_locked_clean_reference_report_nested(
    report: Any,
    spec: dict[str, Any],
    expected_hard_threshold: dict[str, Any] | None = None,
) -> None:
    context = "locked-clean-reference report"
    require_exact_keys(report, LOCKED_CLEAN_REFERENCE_REPORT_KEYS, context)
    if (
        report["artifact"] != "microtexture-v2-r6-locked-clean-reference-report"
        or report["schema_version"]
        != "microtexture-v2-r6-locked-clean-reference-report/2"
        or report["spec_sha256"] != SPEC_SHA256
    ):
        raise RuntimeError(f"{context} identity/schema drift")
    _validate_normal_report_flags(report, context)
    for key in ("hard_composite_accepted",):
        if type(report[key]) is not bool:
            raise RuntimeError(f"{context}.{key} must be exact bool")
    validate_metric_values(report["metrics"], spec, f"{context}.metrics")
    validate_hard_threshold(report["hard_threshold"], spec)
    if (
        expected_hard_threshold is not None
        and report["hard_threshold"] != expected_hard_threshold
    ):
        raise RuntimeError(f"{context} frozen hard-threshold drift")
    threshold = report["hard_threshold"]
    metric_value = float(report["metrics"][threshold["metric"]])
    limit = float(threshold["threshold"])
    failed = (
        metric_value > limit
        if threshold["direction"] == "maximum"
        else metric_value < limit
    )
    accepted = not failed
    if (
        report["hard_composite_accepted"] is not accepted
        or report["passed"] is not accepted
    ):
        raise RuntimeError(f"{context} threshold/pass recomputation drift")


def validate_hard_threshold(value: Any, spec: dict[str, Any]) -> None:
    require_exact_keys(value, HARD_THRESHOLD_KEYS, "hard threshold")
    gate = spec["threshold_selection"]["hard_gate"]
    if value["metric"] != gate["metric"] or value["direction"] != gate["direction"]:
        raise RuntimeError("hard-threshold gate binding drift")
    for key in (
        "threshold",
        "calibration_clean_cluster_acceptance",
        "calibration_warning_cluster_acceptance",
        "calibration_reject_cluster_detection",
        "calibration_severity3_cluster_detection",
    ):
        if not isinstance(value[key], (int, float)) or not math.isfinite(
            float(value[key])
        ):
            raise RuntimeError(f"hard threshold non-finite {key}")
    if (
        type(value["threshold"]) not in {int, float}
        or not 0.0 <= float(value["threshold"]) <= 1.0
    ):
        raise RuntimeError("hard composite threshold must be within 0..1")
    for key in (
        "calibration_clean_cluster_acceptance",
        "calibration_warning_cluster_acceptance",
        "calibration_reject_cluster_detection",
        "calibration_severity3_cluster_detection",
    ):
        if type(value[key]) not in {int, float} or not 0.0 <= float(value[key]) <= 1.0:
            raise RuntimeError(f"hard threshold rate is outside 0..1: {key}")
    if value["selection_objective"] != spec["threshold_selection"]["objective_order"]:
        raise RuntimeError("hard-threshold objective binding drift")


def _verify_marker(
    root: Path,
    relative: str,
    expected_sha: str,
    expected_keys: set[str],
    expected_values: dict[str, Any],
) -> dict[str, Any]:
    marker_path = exact_artifact_path_without_links(
        root, root / relative, relative, must_exist=True
    )
    payload = marker_path.read_bytes()
    if sha256_bytes(payload) != expected_sha:
        raise RuntimeError(f"one-shot marker SHA drift: {relative}")
    marker = json.loads(payload.decode("utf-8"))
    require_exact_keys(marker, expected_keys, f"one-shot marker {relative}")
    for key, expected in expected_values.items():
        if marker[key] != expected:
            raise RuntimeError(f"one-shot marker binding drift: {relative}/{key}")
    if marker["one_shot_consumed"] is not True:
        raise RuntimeError(f"one-shot marker is not consumed: {relative}")
    parse_utc_timestamp(marker["started_at"], f"one-shot marker {relative} started_at")
    return marker


def load_calibration_report(
    state: dict[str, Any], *, require_completion: bool = True
) -> tuple[dict[str, Any], str, dict[str, Any] | None, str | None]:
    root, spec = state["artifact_root"], load_spec()
    _, failure_relative = _stage_artifact_paths("calibration")
    failure_path = exact_artifact_path_without_links(
        root,
        root / failure_relative,
        failure_relative,
        must_exist=False,
    )
    if failure_path.exists():
        raise RuntimeError(
            "calibration failure report exists; normal report is not authority"
        )
    report_relative = "reports/calibration-report.json"
    report_path = exact_artifact_path_without_links(
        root, root / report_relative, report_relative, must_exist=True
    )
    report_bytes = report_path.read_bytes()
    report_sha = sha256_bytes(report_bytes)
    report = json.loads(report_bytes.decode("utf-8"))
    validate_calibration_report_nested(report, spec)
    if (
        report["spec_sha256"] != SPEC_SHA256
        or report["blind_key_commitment"] != state["blind_key_commitment"]
        or report["runtime"] != state["runtime"]
        or report["implementation_bindings_sha256"]
        != state["implementation_bindings_sha256"]
        or report["hard_gate"] != spec["threshold_selection"]["hard_gate"]
    ):
        raise RuntimeError("calibration report trust-chain binding drift")
    marker = _verify_marker(
        root,
        "markers/calibration-evaluation-started.json",
        report["evaluation_marker_sha256"],
        CALIBRATION_MARKER_KEYS,
        {
            "artifact": "microtexture-v2-r6-calibration-evaluation-started",
            "schema_version": "microtexture-v2-r6-calibration-marker/2",
            "spec_sha256": SPEC_SHA256,
            "blind_key_commitment": state["blind_key_commitment"],
            "manifest_sha256": report["manifest_sha256"],
            "labels_sha256": report["labels_sha256"],
            "captured_git_head": report["captured_git_head"],
            "runtime": state["runtime"],
            "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        },
    )
    marker_started_at = parse_utc_timestamp(
        marker["started_at"], "calibration marker started_at"
    )
    evaluated_at = parse_utc_timestamp(
        report["evaluated_at"], "calibration report evaluated_at"
    )
    if marker_started_at > evaluated_at:
        raise RuntimeError("calibration report predates its one-shot marker")
    assert_git_ancestor(report["captured_git_head"], state["captured_head"])
    manifest, manifest_sha = load_control_manifest(
        "calibration",
        state,
        expected_captured_head=report["captured_git_head"],
        verify_payload_hashes=True,
    )
    if manifest_sha != report["manifest_sha256"]:
        raise RuntimeError("actual calibration manifest SHA mismatch")
    labels_relative = spec["labels"]["sealed_authority_paths"]["calibration"]
    labels_path = exact_artifact_path_without_links(
        root,
        root / labels_relative,
        labels_relative,
        must_exist=True,
    )
    labels_bytes = labels_path.read_bytes()
    labels_sha = sha256_bytes(labels_bytes)
    if labels_sha != report["labels_sha256"]:
        raise RuntimeError("actual calibration labels SHA mismatch")
    labels_payload = json.loads(labels_bytes.decode("utf-8"))
    labels = validate_vision_labels_payload(
        labels_payload,
        "calibration",
        manifest,
        manifest_sha,
        state,
    )
    validate_secret_catalog_report_binding(report, manifest, "calibration", state)
    validate_private_vision_label_audits(
        labels, report["identity_reveal"], "calibration sealed labels"
    )
    validate_report_evaluation_bindings(report, manifest, labels, "calibration", spec)

    frozen_relative = "thresholds-frozen.json"
    frozen_path = exact_artifact_path_without_links(
        root, root / frozen_relative, frozen_relative, must_exist=False
    )
    frozen: dict[str, Any] | None = None
    frozen_sha: str | None = None
    frozen_at: datetime | None = None
    if report["passed"]:
        frozen_path = exact_artifact_path_without_links(
            root, root / frozen_relative, frozen_relative, must_exist=True
        )
        frozen_bytes = frozen_path.read_bytes()
        frozen_sha = sha256_bytes(frozen_bytes)
        frozen = json.loads(frozen_bytes.decode("utf-8"))
        require_exact_keys(frozen, FROZEN_KEYS, "frozen thresholds")
        if (
            frozen["artifact"] != "microtexture-v2-r6-thresholds-frozen"
            or frozen["schema_version"] != "microtexture-v2-r6-thresholds/2"
            or frozen["authority"] is not True
            or frozen["spec_sha256"] != SPEC_SHA256
            or frozen["blind_key_commitment"] != state["blind_key_commitment"]
            or frozen["runtime"] != state["runtime"]
            or frozen["implementation_bindings_sha256"]
            != state["implementation_bindings_sha256"]
            or frozen["hard_gate"] != spec["threshold_selection"]["hard_gate"]
            or frozen["endpoint_definitions"]
            != spec["threshold_selection"]["endpoint_definitions"]
            or frozen["holdout_allowed_count"] != 1
            or frozen["threshold_changes_forbidden"] is not True
            or frozen["calibration_manifest_sha256"] != manifest_sha
            or frozen["calibration_report_sha256"] != report_sha
            or frozen["calibration_evaluation_marker_sha256"]
            != report["evaluation_marker_sha256"]
            or frozen["calibration_captured_git_head"] != report["captured_git_head"]
            or frozen["hard_gate"] != report["hard_gate"]
            or frozen["hard_threshold"] != report["hard_threshold"]
            or report["selection_status"] != "selected-and-passed"
        ):
            raise RuntimeError("calibration report/frozen binding drift")
        validate_hard_threshold(frozen["hard_threshold"], spec)
        frozen_at = parse_utc_timestamp(frozen["frozen_at"], "threshold frozen_at")
        if evaluated_at > frozen_at:
            raise RuntimeError("thresholds were frozen before calibration evaluation")
    elif frozen_path.exists():
        raise RuntimeError("failed calibration must not produce frozen thresholds")

    if require_completion:
        load_stage_completion(
            stage="calibration",
            state=state,
            expected_marker_sha=report["evaluation_marker_sha256"],
            expected_report_sha=report_sha,
            expected_captured_head=report["captured_git_head"],
            expected_passed=report["passed"],
            expected_result_status=report["selection_status"],
            expected_bindings={
                "manifest_sha256": manifest_sha,
                "labels_sha256": labels_sha,
                "frozen_thresholds_sha256": frozen_sha,
                "threshold_authority_receipt_sha256": None,
                "locked_clean_reference_sha256": None,
            },
            marker_started_at=marker_started_at,
            report_evaluated_at=evaluated_at,
            frozen_at=frozen_at,
        )
    return report, report_sha, frozen, frozen_sha


def load_frozen_thresholds(state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    report, _, frozen, frozen_sha = load_calibration_report(state)
    if report["passed"] is not True or frozen is None or frozen_sha is None:
        raise RuntimeError("calibration did not produce passing frozen authority")
    return frozen, frozen_sha


def load_locked_clean_reference_report(
    state: dict[str, Any], *, require_completion: bool = True
) -> tuple[
    dict[str, Any],
    str,
    dict[str, Any],
    str,
    dict[str, Any] | None,
]:
    spec = load_spec()
    frozen, frozen_sha = load_frozen_thresholds(state)
    root = state["artifact_root"]
    _, failure_relative = _stage_artifact_paths("locked-clean-reference")
    locked_failure = exact_artifact_path_without_links(
        root,
        root / failure_relative,
        failure_relative,
        must_exist=False,
    )
    if locked_failure.exists():
        raise RuntimeError(
            "locked-clean-reference failure report exists; normal report is not authority"
        )
    locked_spec = spec["locked_clean_reference"]
    locked_relative = locked_spec["report_repo_relative_artifact_path"]
    locked_path = exact_artifact_path_without_links(
        root,
        root / locked_relative,
        locked_relative,
        must_exist=True,
    )
    locked_bytes = locked_path.read_bytes()
    locked_sha = sha256_bytes(locked_bytes)
    locked = json.loads(locked_bytes.decode("utf-8"))
    validate_locked_clean_reference_report_nested(
        locked, spec, frozen["hard_threshold"]
    )
    locked_marker = _verify_marker(
        root,
        "markers/locked-clean-reference-validation-started.json",
        locked["evaluation_marker_sha256"],
        LOCKED_CLEAN_REFERENCE_MARKER_KEYS,
        {
            "artifact": "microtexture-v2-r6-locked-clean-reference-validation-started",
            "schema_version": "microtexture-v2-r6-locked-clean-reference-marker/2",
            "spec_sha256": SPEC_SHA256,
            "blind_key_commitment": state["blind_key_commitment"],
            "frozen_thresholds_sha256": frozen_sha,
            "captured_git_head": frozen["calibration_captured_git_head"],
            "runtime": state["runtime"],
            "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        },
    )
    frozen_at = parse_utc_timestamp(frozen["frozen_at"], "threshold frozen_at")
    locked_evaluated_at = parse_utc_timestamp(
        locked["evaluated_at"], "locked-clean-reference evaluated_at"
    )
    if locked_evaluated_at < frozen_at:
        raise RuntimeError(
            "locked-clean-reference evaluation predates threshold freeze"
        )
    locked_started_at = parse_utc_timestamp(
        locked_marker["started_at"], "locked-clean-reference marker started_at"
    )
    if locked_started_at < frozen_at:
        raise RuntimeError("locked-clean-reference marker predates threshold freeze")
    if locked_started_at > locked_evaluated_at:
        raise RuntimeError("locked-clean-reference report predates its marker")
    if (
        locked["artifact"] != "microtexture-v2-r6-locked-clean-reference-report"
        or locked["schema_version"]
        != "microtexture-v2-r6-locked-clean-reference-report/2"
        or locked["spec_sha256"] != SPEC_SHA256
        or locked["runtime"] != state["runtime"]
        or locked["implementation_bindings_sha256"]
        != state["implementation_bindings_sha256"]
        or locked["frozen_thresholds_sha256"] != frozen_sha
        or locked["blind_key_commitment"] != state["blind_key_commitment"]
        or locked["locked_clean_reference_sha256"] != locked_spec["sha256"]
        or locked["source_crop_xywh"] != locked_spec["source_crop_xywh"]
        or locked["metric_window_xywh_within_source_crop"]
        != locked_spec["metric_window_xywh_within_source_crop"]
        or locked["effective_source_xywh"] != locked_spec["effective_source_xywh"]
        or locked["hard_threshold"] != frozen["hard_threshold"]
        or locked["captured_git_head"] != frozen["calibration_captured_git_head"]
    ):
        raise RuntimeError("locked-clean-reference report trust-chain binding drift")
    completion = None
    if require_completion:
        completion, _ = load_stage_completion(
            stage="locked-clean-reference",
            state=state,
            expected_marker_sha=locked["evaluation_marker_sha256"],
            expected_report_sha=locked_sha,
            expected_captured_head=locked["captured_git_head"],
            expected_passed=locked["passed"],
            expected_result_status=(
                "accepted" if locked["hard_composite_accepted"] else "rejected"
            ),
            expected_bindings={
                "manifest_sha256": None,
                "labels_sha256": None,
                "frozen_thresholds_sha256": frozen_sha,
                "threshold_authority_receipt_sha256": None,
                "locked_clean_reference_sha256": locked_spec["sha256"],
            },
            marker_started_at=locked_started_at,
            report_evaluated_at=locked_evaluated_at,
            frozen_at=frozen_at,
        )
    return locked, locked_sha, frozen, frozen_sha, completion


def load_threshold_authority_receipt(
    state: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    spec = load_spec()
    relative = spec["external_threshold_authority"]["receipt_repo_relative_path"]
    payload = _tracked_worktree_bytes(
        state["repository"], state["captured_head"], relative
    )
    receipt = json.loads(payload.decode("utf-8"))
    require_exact_keys(receipt, RECEIPT_KEYS, "threshold authority receipt")
    locked, locked_sha, frozen, frozen_sha, completion = (
        load_locked_clean_reference_report(state)
    )
    if (
        locked["passed"] is not True
        or locked["failure"] is not None
        or locked["one_shot_consumed"] is not True
        or locked["hard_composite_accepted"] is not True
        or completion is None
        or completion["passed"] is not True
    ):
        raise RuntimeError("locked-clean-reference report is not a passing validation")
    frozen_at = parse_utc_timestamp(frozen["frozen_at"], "threshold frozen_at")
    locked_evaluated_at = parse_utc_timestamp(
        locked["evaluated_at"], "locked-clean-reference evaluated_at"
    )
    locked_completed_at = parse_utc_timestamp(
        completion["completed_at"], "locked-clean-reference completion completed_at"
    )
    expected = spec["external_threshold_authority"]
    reviewer = receipt["reviewer_id"]
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise RuntimeError("threshold authority reviewer_id must be non-empty")
    normalized_reviewer = " ".join(
        unicodedata.normalize("NFKC", reviewer).casefold().split()
    )
    eligible_reviewers = {
        " ".join(unicodedata.normalize("NFKC", value).casefold().split())
        for value in expected["eligible_reviewer_ids"]
    }
    if normalized_reviewer not in eligible_reviewers:
        raise RuntimeError("threshold authority reviewer is not preregistered/eligible")
    if receipt["review_mode"] != expected["required_review_mode"]:
        raise RuntimeError("threshold authority review mode drift")
    reviewed_at = parse_utc_timestamp(
        receipt["reviewed_at"], "threshold authority reviewed_at"
    )
    if reviewed_at < max(frozen_at, locked_evaluated_at, locked_completed_at):
        raise RuntimeError(
            "threshold authority review predates freeze/locked completion"
        )
    tolerance = timedelta(seconds=int(expected["clock_future_tolerance_seconds"]))
    if reviewed_at > datetime.now(timezone.utc) + tolerance:
        raise RuntimeError("threshold authority reviewed_at is in the future")
    if (
        receipt["artifact"] != "microtexture-v2-r6-threshold-authority"
        or receipt["schema_version"] != expected["schema_version"]
        or receipt["approval"] != expected["required_approval"]
        or receipt["spec_sha256"] != SPEC_SHA256
        or receipt["frozen_thresholds_sha256"] != frozen_sha
        or receipt["calibration_report_sha256"] != frozen["calibration_report_sha256"]
        or receipt["calibration_manifest_sha256"]
        != frozen["calibration_manifest_sha256"]
        or receipt["locked_clean_reference_report_sha256"] != locked_sha
        or receipt["implementation_bindings_sha256"]
        != state["implementation_bindings_sha256"]
        or receipt["blind_key_commitment"] != state["blind_key_commitment"]
        or receipt["runtime"] != state["runtime"]
        or receipt["calibration_captured_git_head"]
        != frozen["calibration_captured_git_head"]
        or receipt["locked_clean_reference_captured_git_head"]
        != locked["captured_git_head"]
    ):
        raise RuntimeError(
            "external threshold authority receipt binding/approval drift"
        )
    return receipt, sha256_bytes(payload)


def load_holdout_report(
    state: dict[str, Any], *, require_completion: bool = True
) -> tuple[dict[str, Any], str]:
    if "threshold_authority" not in state or "threshold_authority_sha256" not in state:
        raise RuntimeError(
            "holdout report reload requires validated threshold authority"
        )
    root, spec = state["artifact_root"], load_spec()
    _, failure_relative = _stage_artifact_paths("holdout")
    failure_path = exact_artifact_path_without_links(
        root,
        root / failure_relative,
        failure_relative,
        must_exist=False,
    )
    if failure_path.exists():
        raise RuntimeError(
            "holdout failure report exists; normal report is not authority"
        )
    frozen, frozen_sha = load_frozen_thresholds(state)
    if frozen_sha != state["threshold_authority"]["frozen_thresholds_sha256"]:
        raise RuntimeError("holdout reload receipt/frozen SHA drift")
    manifest, manifest_sha = load_control_manifest(
        "holdout",
        state,
        expected_captured_head=state["captured_head"],
        verify_payload_hashes=True,
    )
    report_relative = "reports/holdout-report.json"
    report_path = exact_artifact_path_without_links(
        root,
        root / report_relative,
        report_relative,
        must_exist=True,
    )
    report_bytes = report_path.read_bytes()
    report_sha = sha256_bytes(report_bytes)
    report = json.loads(report_bytes.decode("utf-8"))
    validate_holdout_report_nested(report, spec, frozen["hard_threshold"])
    if (
        report["spec_sha256"] != SPEC_SHA256
        or report["blind_key_commitment"] != state["blind_key_commitment"]
        or report["manifest_sha256"] != manifest_sha
        or report["frozen_thresholds_sha256"] != frozen_sha
        or report["threshold_authority_receipt_sha256"]
        != state["threshold_authority_sha256"]
        or report["captured_git_head"] != state["captured_head"]
        or report["runtime"] != state["runtime"]
        or report["implementation_bindings_sha256"]
        != state["implementation_bindings_sha256"]
        or report["hard_gate"] != frozen["hard_gate"]
        or report["hard_threshold"] != frozen["hard_threshold"]
    ):
        raise RuntimeError("holdout report trust-chain binding drift")
    marker = _verify_marker(
        root,
        "markers/holdout-evaluation-started.json",
        report["evaluation_marker_sha256"],
        HOLDOUT_MARKER_KEYS,
        {
            "artifact": "microtexture-v2-r6-holdout-evaluation-started",
            "schema_version": "microtexture-v2-r6-holdout-marker/2",
            "spec_sha256": SPEC_SHA256,
            "blind_key_commitment": state["blind_key_commitment"],
            "manifest_sha256": manifest_sha,
            "labels_sha256": report["labels_sha256"],
            "frozen_thresholds_sha256": frozen_sha,
            "threshold_authority_receipt_sha256": state["threshold_authority_sha256"],
            "captured_git_head": state["captured_head"],
            "runtime": state["runtime"],
            "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        },
    )
    marker_started_at = parse_utc_timestamp(
        marker["started_at"], "holdout marker started_at"
    )
    evaluated_at = parse_utc_timestamp(report["evaluated_at"], "holdout evaluated_at")
    reviewed_at = parse_utc_timestamp(
        state["threshold_authority"]["reviewed_at"], "threshold authority reviewed_at"
    )
    if reviewed_at > marker_started_at or marker_started_at > evaluated_at:
        raise RuntimeError("holdout receipt/marker/report timestamp order drift")
    labels_relative = spec["labels"]["sealed_authority_paths"]["holdout"]
    labels_path = exact_artifact_path_without_links(
        root,
        root / labels_relative,
        labels_relative,
        must_exist=True,
    )
    labels_bytes = labels_path.read_bytes()
    labels_sha = sha256_bytes(labels_bytes)
    if labels_sha != report["labels_sha256"]:
        raise RuntimeError("actual sealed holdout labels SHA mismatch")
    labels_payload = json.loads(labels_bytes.decode("utf-8"))
    labels = validate_vision_labels_payload(
        labels_payload, "holdout", manifest, manifest_sha, state
    )
    validate_secret_catalog_report_binding(report, manifest, "holdout", state)
    validate_private_vision_label_audits(
        labels, report["identity_reveal"], "holdout sealed labels"
    )
    validate_report_evaluation_bindings(report, manifest, labels, "holdout", spec)
    if require_completion:
        load_stage_completion(
            stage="holdout",
            state=state,
            expected_marker_sha=report["evaluation_marker_sha256"],
            expected_report_sha=report_sha,
            expected_captured_head=report["captured_git_head"],
            expected_passed=report["passed"],
            expected_result_status="passed" if report["passed"] else "failed",
            expected_bindings={
                "manifest_sha256": manifest_sha,
                "labels_sha256": labels_sha,
                "frozen_thresholds_sha256": frozen_sha,
                "threshold_authority_receipt_sha256": state[
                    "threshold_authority_sha256"
                ],
                "locked_clean_reference_sha256": spec["locked_clean_reference"][
                    "sha256"
                ],
            },
            marker_started_at=marker_started_at,
            report_evaluated_at=evaluated_at,
            frozen_at=parse_utc_timestamp(frozen["frozen_at"], "threshold frozen_at"),
        )
    return report, report_sha
