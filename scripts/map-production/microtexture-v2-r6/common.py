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
SPEC_SHA256 = "fbdaf2aa25a9f7046cf3a05e7cbfaa4822edd40af83d133e0a2cc8b44051ac54"
BINDINGS_PATH = CODE_ROOT / "implementation-bindings.json"
DEV_R20_CLOSED_STATUS = "failed-and-closed-before-measurement"
DEV_R20_CLOSED_ROLE = (
    "development-only premeasurement population failure evidence; both private "
    "audits passed, calibration tiny-speck population 0 and holdout tiny-speck "
    "population 1 each missed formal minimum 4 and development floor 6, every other "
    "endpoint passed both minima, no numeric metric or threshold search started, one "
    "read-only postmortem ran exactly once, all Root and Independent initial snapshots "
    "and receipts remain immutable, and no dev-r20 root, key, private material, "
    "control, reference, pixel, identity, code, commitment, label, decision, "
    "measurement, nonce, public surface, or postmortem output is reusable"
)
DEV_R20_FAILURE_AUDIT_REL = (
    "world/map-production/qa/microtexture-v2-r6-dev-r20-development-failure.json"
)
# Frozen only after the sanitized tracked audit was finalized byte-for-byte.
DEV_R20_FAILURE_AUDIT_RAW_SHA256 = (
    "e8689321135e8c5d3fb038fbaa7c3ccbe644999905f4a3d3834fa30969ff27c8"
)
# Frozen from canonical_json_bytes() over the same finalized semantic payload.
DEV_R20_FAILURE_AUDIT_CANONICAL_SHA256 = (
    "c176212723a240021d1379794231c47a1909ad3222c4f54e93db04c8230f7560"
)
DEV_R20_CLOSED_SECRET_SCOPE = (
    "closed non-authority dev-r20 only; the retained development key, root, output, "
    "and commitment are forensic evidence only and cannot become formal authority or "
    "be reused"
)
DEV_R20_CLOSED_REVIEWER_ACCESS_CONTRACT = (
    "the formal blind key remains only in a dedicated custodian process; every closed "
    "development blind key through dev-r20 remains only in its retained Git-ignored "
    "private probe root and is never reused; neither Vision review process may read or "
    "inherit any key or private audit role, and both must use visual page inspection "
    "only until both official initial snapshots and receipts exist before reconciliation "
    "and label sealing"
)
R20_DEVELOPMENT_BASIS = (
    "reference constants, strictly monotone bounded soft-unit score structure, "
    "worst-case truth aggregation, and fixed filters were designed from the "
    "revealed failed r5 report plus closed non-formal dev-r6/dev-r7 evidence; "
    "dev-r8 stopped before measurement because tiny-speck-visible rejects were 3 "
    "and 1 clusters; dev-r9 fixed that population deficit but failed after one "
    "measurement because warning acceptance and severity-3 detection had no common "
    "scalar threshold; dev-r10 was interrupted during generation before any Vision "
    "review or measurement; dev-r11 completed blind review but failed the private "
    "exact-zero sentinel gate before population aggregation or numeric measurement; "
    "dev-r12 passed private audits but closed before measurement because warning "
    "population was 10 calibration and 9 holdout against development floor 13, with "
    "holdout also below formal minimum 10; dev-r13 passed every formal population "
    "minimum but closed before measurement because holdout warning population 12 "
    "missed development floor 13; dev-r14 passed all formal minima and every holdout "
    "development floor but closed before measurement because calibration microblob "
    "population 4 missed development floor 6; dev-r15 passed both private audits but "
    "closed before measurement because warning population was 12 calibration and 9 "
    "holdout against development floor 13, with holdout also below formal minimum "
    "10; dev-r16 preserved the metric and every threshold/count/rate requirement and "
    "applied the frozen warning rebalance, but closed before population aggregation "
    "or measurement after one sealed holdout exact-zero sentinel received a "
    "severity-1 short-line warning; dev-r17 passed private audits and every "
    "calibration population floor but closed before measurement because holdout "
    "tiny-speck population 0 missed formal minimum 4 and development floor 6 and "
    "holdout spot population 9 missed development floor 10; dev-r18 preserved the "
    "other 180 r17 artifact morphologies, all tier cardinalities, population minima, "
    "metric, threshold, and rate contracts plus the r17 role-agnostic reference "
    "prequalification and bilateral initial flag gate, but closed before population "
    "audit or numeric measurement because calibration's obvious-artifact duplicate "
    "pair matched reject disposition and all five visible flags while using ordinal "
    "severities 2 and 3 under the then-exact severity check; fresh dev-r19 preserves "
    "all 200 dev-r18 artifact morphologies, every design tier, metric, threshold, "
    "population, and rate contract, and changes only duplicate semantic equivalence "
    "so reject severities 2 and 3 share one reject ordinal band while disposition "
    "and all five visible flags remain exact; every prior corpus remains "
    "development-only; dev-r19 then closed before population aggregation or numeric "
    "measurement because its holdout obvious-artifact duplicate pair was labeled "
    "clean severity 0 with no visible flags; dev-r20 preserved the full dev-r19 "
    "artifact catalog, tier/metric/threshold/population/rate contracts, reject severity-"
    "band policy, and clean duplicate, changed only the obvious-artifact duplicate "
    "construction to a keyed 12-bar finite axial short-line payload, passed both private "
    "audits, and then closed before measurement because calibration tiny-speck "
    "population 0 and holdout tiny-speck population 1 each missed formal minimum 4 and "
    "development floor 6 while every other endpoint passed both minima"
)


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


def _require_exact_json_value(value: Any, expected: Any, context: str) -> None:
    """Require exact JSON types, key sets, list ordering, and scalar values."""

    if type(value) is not type(expected):
        raise RuntimeError(
            f"{context} type drift: expected={type(expected).__name__}, "
            f"actual={type(value).__name__}"
        )
    if isinstance(expected, dict):
        require_exact_keys(value, set(expected), context)
        for key, expected_item in expected.items():
            _require_exact_json_value(value[key], expected_item, f"{context}.{key}")
        return
    if isinstance(expected, list):
        if len(value) != len(expected):
            raise RuntimeError(
                f"{context} length drift: expected={len(expected)}, actual={len(value)}"
            )
        for index, (item, expected_item) in enumerate(zip(value, expected)):
            _require_exact_json_value(item, expected_item, f"{context}[{index}]")
        return
    if value != expected:
        raise RuntimeError(f"{context} value drift")


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
        "similar footprint and polarity; every counted core is directly visible "
        "without enhancement in the native full-200 panel, is uniquely locatable at "
        "400 percent, returns toward local background in every direction within "
        "roughly one core width, is clearly sharper or higher contrast than the soft "
        "substrate, and matches the same visible center at full-200; diffuse, "
        "feathered, irregular soft flecks, solitary cores, mere tonal extrema, and "
        "extremely faint point impressions inferred only from 400 percent are excluded"
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
    "revision": "dev-r20-strong-finite-duplicate-short-line-sentinel-schedule-v1",
    "fresh_from_closed_dev_r18": True,
    "r18_parameter_nonce_reuse_forbidden": True,
    "r18_per_family_residue_rotation": {
        "calibration": {
            "artifact-fine-grain": 2,
            "artifact-speck": 4,
            "artifact-microblob": 6,
            "artifact-short-dash": 8,
            "artifact-parallel-bundle": 10,
        },
        "holdout": {
            "artifact-fine-grain": 3,
            "artifact-speck": 5,
            "artifact-microblob": 7,
            "artifact-short-dash": 9,
            "artifact-parallel-bundle": 11,
        },
    },
    "r19_parameter_nonce_bases": {
        "calibration_artifact": 1173000,
        "holdout_artifact": 1183000,
        "calibration_protocol_zero": 1151000,
        "holdout_protocol_zero": 1161000,
        "calibration_duplicate_audit": [1191000, 1191001, 1191002],
        "holdout_duplicate_audit": [1201000, 1201001, 1201002],
    },
    "inherited_r18_schedule_revision": (
        "dev-r18-symmetric-direct-visible-speck-reinforcement-schedule-v1"
    ),
    "private_reference_prequalification_manifest": {
        "revision": "dev-r17-role-agnostic-private-reference-coefficient-prequalification-v1",
        "applies_to_private_roles": [
            "artifact",
            "protocol-zero",
            "duplicate-audit",
        ],
        "candidate_count": 8,
        "coefficient_grid_hw": [7, 9],
        "candidate_domain": "candidate/{index:02d}/",
        "score_lane_integer_weights": {
            "displacement-y": 7,
            "displacement-x": 7,
            "tone": 3,
        },
        "score_terms_in_lexicographic_order": [
            "maximum-weighted-orthogonal-neighbor-jump",
            "sum-weighted-orthogonal-neighbor-jumps",
            "maximum-weighted-centered-coefficient-magnitude",
            "sum-weighted-centered-coefficient-magnitudes",
            "candidate-index",
        ],
        "selection_rule": "lexicographic-minimum",
        "selection_uses_pixels": False,
        "selection_uses_requested_delta": False,
        "selection_uses_labels_or_decisions": False,
        "selection_branches_on_private_role": False,
        "selected_score_not_worse_than_candidate_zero": True,
        "truth_guarantee_claimed": False,
    },
    "private_reference_prequalification_manifest_sha256": (
        "a3cfdec84b58bebec38f581c03fbe9947975bf93e11741477cd3bb22f0931119"
    ),
    "initial_decision_gate_manifest": {
        "revision": "dev-r17-bilateral-initial-visible-flag-intersection-gate-v1",
        "snapshot_files": {
            "root": "decisions-root.initial.dev.txt",
            "independent": "decisions-independent.initial.dev.txt",
        },
        "receipt_files": {
            "root": "decisions-root.initial.dev.txt.sha256",
            "independent": "decisions-independent.initial.dev.txt.sha256",
        },
        "receipt_format": "lowercase-sha256 two-spaces snapshot-basename newline",
        "final_files": [
            "vision-decisions.dev.txt",
            "decisions-root.dev.txt",
            "decisions-independent.dev.txt",
        ],
        "final_three_way_exact_bytes_required": True,
        "initial_snapshots_require_official_parser_coverage_and_code_binding": True,
        "visible_flags": ["g", "t", "b", "l", "p"],
        "final_visible_flag_set_relation": (
            "subset-of-root-initial-intersection-independent-initial"
        ),
        "reconciled_fields_not_restricted_by_this_gate": [
            "disposition",
            "severity_0_to_3",
            "notes",
        ],
        "private_role_input": False,
        "read_only_attribute_required_by_runner": False,
    },
    "initial_decision_gate_manifest_sha256": (
        "f042250290f80d4304923e3b564746e8311515f5c649811678db934bb3ad6ffd"
    ),
    "preserved_r17_artifact_morphology_conditions_across_splits": 180,
    "preserved_r17_artifact_morphology_sha256": (
        "03559cb9f26908f6ed59bd8327250c5d63e77e6e96c34d7f08a47e8cb59a7fdf"
    ),
    "r18_exact_morphology_change_count_across_splits": 20,
    "r18_speck_reinforcement_revision": (
        "dev-r18-symmetric-reject-speck-direct-visible-cross-v1"
    ),
    "r18_speck_reinforcement_manifest_sha256": (
        "355c6c588c3d698288a3545752c13cea734db85e1e7a9a95416cbe3163f633d4"
    ),
    "r18_full_artifact_morphology_sha256": (
        "9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365"
    ),
    "r18_target_speck_conditions_per_split": 10,
    "r18_target_speck_tiers_per_split": {
        "clear-reject-candidate": 6,
        "dominant-reject-candidate": 4,
    },
    "r18_tiny_speck_structural_miss_budget": 4,
    "r18_spot_detection_increment_required_from_sanitized_r17_holdout": 1,
    "r18_sanitized_r17_basis": {
        "calibration_formal_and_development_endpoint_floors_passed": True,
        "holdout": {
            "tiny_speck_reject_detection": {
                "observed": 0,
                "formal_minimum": 4,
                "development_minimum": 6,
            },
            "spot_reject_detection": {
                "observed": 9,
                "formal_minimum": 8,
                "development_minimum": 10,
            },
            "all_other_endpoints_passed": True,
        },
        "private_audits_passed": True,
        "metric_or_threshold_evaluation_performed": False,
    },
    "r18_sanitized_r17_basis_sha256": (
        "88860fea0dbdf5ebfa454bf7f038aae53c957808d4c4d344b1ea0fc8e54042e9"
    ),
    "r18_metric_threshold_population_and_rate_contract_changes_forbidden": True,
    "r19_preserved_r18_artifact_morphology_conditions_across_splits": 200,
    "r19_preserved_r18_artifact_morphology_sha256": (
        "9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365"
    ),
    "r19_exact_morphology_change_count_across_splits": 0,
    "r19_duplicate_equivalence_policy_revision": (
        "dev-r19-reject-ordinal-band-duplicate-equivalence-v1"
    ),
    "r19_duplicate_equivalence_policy_manifest": {
        "revision": "dev-r19-reject-ordinal-band-duplicate-equivalence-v1",
        "scope": {
            "private_role": "duplicate-audit",
            "duplicate_audit_group": "artifact",
        },
        "pair_equivalence": {
            "disposition": {
                "comparison": "exact-across-pair",
                "required_value": "reject",
            },
            "visible_flags": {
                "comparison": "exact-across-pair",
                "fields": [
                    "grain_visible",
                    "tiny_speck_visible",
                    "microblob_visible",
                    "short_line_visible",
                    "parallel_bundle_visible",
                ],
            },
            "severity_0_to_3": {
                "comparison": "per-member-inclusive-ordinal-band",
                "allowed_values": [2, 3],
                "exact_across_pair_required": False,
            },
        },
        "unchanged_semantics": {
            "clean_duplicate_pair_full_semantic_equality_required": True,
            "warning_semantics_unchanged": True,
            "all_non_scoped_duplicate_comparisons_unchanged": True,
        },
        "obvious_artifact_required_label": {
            "disposition": "reject",
            "severity_0_to_3_allowed_values": [2, 3],
            "short_line_visible_required": True,
        },
        "preservation_contract": {
            "artifact_morphology_change_count_across_splits": 0,
            "full_artifact_morphology_sha256": (
                "9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365"
            ),
            "tier_cardinality_minimum_metric_threshold_and_rate_contracts_unchanged": True,
            "reference_prequalification_unchanged": True,
            "bilateral_initial_visible_flag_gate_unchanged": True,
            "vision_truth_guaranteed": False,
        },
    },
    "r19_duplicate_equivalence_policy_manifest_sha256": (
        "292ebced789826a46ac792a10f716c70c1a4ed5960d5a299dd7a89e816143cc6"
    ),
    "r19_sanitized_r18_basis": {
        "calibration": {
            "duplicate_clean_audit_passed": True,
            "duplicate_artifact_pair": {
                "agreed_disposition": "reject",
                "agreed_visible_flags": {
                    "grain_visible": False,
                    "tiny_speck_visible": False,
                    "microblob_visible": False,
                    "short_line_visible": True,
                    "parallel_bundle_visible": False,
                },
                "observed_severity_0_to_3_values": [2, 3],
                "only_label_difference": "severity_0_to_3",
            },
            "protocol_zero_audit_passed": True,
        },
        "holdout": {
            "duplicate_clean_audit_passed": True,
            "duplicate_artifact_audit_passed": True,
            "protocol_zero_audit_passed": True,
        },
        "population_aggregation_started": False,
        "numeric_measurement_started": False,
        "metric_evaluation_started": False,
        "threshold_search_started": False,
    },
    "r19_sanitized_r18_basis_sha256": (
        "f4f4c80a406818da30ab18ac270eb466dda2ef42b4f301bde6ce2dea8698ade1"
    ),
    "r19_morphology_tier_minimum_metric_threshold_and_rate_changes_forbidden": True,
   'fresh_from_closed_dev_r19': True,
   'r19_parameter_nonce_reuse_forbidden': True,
   'r20_parameter_nonce_bases': {'calibration_artifact': 1273000,
                                 'holdout_artifact': 1283000,
                                 'calibration_protocol_zero': 1251000,
                                 'holdout_protocol_zero': 1261000,
                                 'calibration_duplicate_audit': [1291000,
                                                                 1291001,
                                                                 1291002],
                                 'holdout_duplicate_audit': [1301000, 1301001, 1301002]},
   'inherited_r19_schedule_revision': 'dev-r19-duplicate-reject-severity-band-equivalence-schedule-v1',
   'r20_predecessor_catalog_authority_sha256': 'f2edfca7ee3f696ddaf815b4be3f316973626ed5cc602cba3dbc5585203d5b37',
   'r20_preserved_r19_artifact_morphology_conditions_across_splits': 200,
   'r20_preserved_r19_artifact_morphology_sha256': '9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365',
   'r20_exact_morphology_change_count_across_splits': 0,
   'r20_duplicate_equivalence_policy_revision': 'dev-r19-reject-ordinal-band-duplicate-equivalence-v1',
   'r20_duplicate_equivalence_policy_manifest': {'revision': 'dev-r19-reject-ordinal-band-duplicate-equivalence-v1',
                                                 'scope': {'private_role': 'duplicate-audit',
                                                           'duplicate_audit_group': 'artifact'},
                                                 'pair_equivalence': {'disposition': {'comparison': 'exact-across-pair',
                                                                                      'required_value': 'reject'},
                                                                      'visible_flags': {'comparison': 'exact-across-pair',
                                                                                        'fields': ['grain_visible',
                                                                                                   'tiny_speck_visible',
                                                                                                   'microblob_visible',
                                                                                                   'short_line_visible',
                                                                                                   'parallel_bundle_visible']},
                                                                      'severity_0_to_3': {'comparison': 'per-member-inclusive-ordinal-band',
                                                                                          'allowed_values': [2,
                                                                                                             3],
                                                                                          'exact_across_pair_required': False}},
                                                 'unchanged_semantics': {'clean_duplicate_pair_full_semantic_equality_required': True,
                                                                         'warning_semantics_unchanged': True,
                                                                         'all_non_scoped_duplicate_comparisons_unchanged': True},
                                                 'obvious_artifact_required_label': {'disposition': 'reject',
                                                                                     'severity_0_to_3_allowed_values': [2,
                                                                                                                        3],
                                                                                     'short_line_visible_required': True},
                                                 'preservation_contract': {'artifact_morphology_change_count_across_splits': 0,
                                                                           'full_artifact_morphology_sha256': '9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365',
                                                                           'tier_cardinality_minimum_metric_threshold_and_rate_contracts_unchanged': True,
                                                                           'reference_prequalification_unchanged': True,
                                                                           'bilateral_initial_visible_flag_gate_unchanged': True,
                                                                           'vision_truth_guaranteed': False}},
   'r20_duplicate_equivalence_policy_manifest_sha256': '292ebced789826a46ac792a10f716c70c1a4ed5960d5a299dd7a89e816143cc6',
   'r20_duplicate_sentinel_revision': 'dev-r20-keyed-axial-short-line-duplicate-sentinel-v1',
   'r20_duplicate_sentinel_manifest': {'revision': 'dev-r20-keyed-axial-short-line-duplicate-sentinel-v1',
                                       'scope': {'private_role': 'duplicate-audit',
                                                 'duplicate_audit_group': 'artifact'},
                                       'construction': {'render_family': 'duplicate-obvious-short-line-sentinel',
                                                        'bar_count_in_metric_window': 12,
                                                        'bars_per_exact_metric_quadrant': 3,
                                                        'encoded_bar_length_px': 24,
                                                        'encoded_bar_width_px': 3,
                                                        'encoded_amplitude_l': 12.0,
                                                        'polarity': 1,
                                                        'minimum_center_chebyshev_separation_px': 32,
                                                        'center_margin_per_exact_metric_quadrant_px': 14,
                                                        'minimum_support_guard_px': 2,
                                                        'orientation_contract': 'keyed-phase-2-to-1-horizontal-or-vertical-per-quadrant',
                                                        'placement_contract': 'fresh-keyed-split-and-condition-derived'},
                                       'raster_contract': {'connected_component_count': 12,
                                                           'pixels_per_component': 72,
                                                           'nonzero_pixel_count': 864,
                                                           'nonzero_values_exact': [12.0],
                                                           'component_shapes_hw': [[3,
                                                                                    24],
                                                                                   [24,
                                                                                    3]],
                                                           'each_quadrant_contains_horizontal_and_vertical': True,
                                                           'all_support_inside_one_exact_metric_quadrant_per_component': True,
                                                           'all_support_inside_metric_window': True},
                                       'pair_equality_contract': {'requested_delta_float32_exact': True,
                                                                  'decoded_residual_exact': True,
                                                                  'metric_values_exact': True,
                                                                  'reference_bytes_distinct': True,
                                                                  'control_bytes_distinct': True,
                                                                  'anonymous_codes_and_control_ids_distinct': True},
                                       'zero_key_static_delta_float32_sha256': {'calibration': '0f34c8f787be57c7c0c074888a73ec15e007c63e98d5c5606d4d5d8bbc6de823',
                                                                                'holdout': '027140de4d34eb78c06b00c282b37caade6393ce6240165bfa65825a286a644f'},
                                       'preservation_contract': {'clean_duplicate_construction_unchanged': True,
                                                                 'artifact_catalog_morphology_change_count_across_splits': 0,
                                                                 'full_artifact_morphology_sha256': '9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365',
                                                                 'duplicate_equivalence_policy_revision': 'dev-r19-reject-ordinal-band-duplicate-equivalence-v1',
                                                                 'duplicate_equivalence_policy_manifest_sha256': '292ebced789826a46ac792a10f716c70c1a4ed5960d5a299dd7a89e816143cc6',
                                                                 'tier_metric_threshold_population_and_rate_contracts_unchanged': True,
                                                                 'vision_truth_guaranteed': False}},
   'r20_duplicate_sentinel_manifest_sha256': '2ee513f2a3182741fbf9df569a2c5137a7f25b4fd27d3fbba6b00344497b85a1',
   'r20_sanitized_r19_basis': {'failure_class': 'holdout-artifact-duplicate-obvious-short-line-clean-miss',
                               'calibration': {'duplicate_clean_audit_passed': True,
                                               'duplicate_artifact_pair': {'member_count': 2,
                                                                           'agreed_disposition': 'reject',
                                                                           'agreed_severity_0_to_3': 3,
                                                                           'agreed_visible_flags': {'grain_visible': False,
                                                                                                    'tiny_speck_visible': False,
                                                                                                    'microblob_visible': False,
                                                                                                    'short_line_visible': True,
                                                                                                    'parallel_bundle_visible': False},
                                                                           'required_obvious_artifact_contract_passed': True},
                                               'protocol_zero_audit_passed': True,
                                               'duplicate_audit_passed': True},
                               'holdout': {'duplicate_clean_audit_passed': True,
                                           'duplicate_artifact_pair': {'member_count': 2,
                                                                       'agreed_disposition': 'clean',
                                                                       'agreed_severity_0_to_3': 0,
                                                                       'agreed_visible_flags': {'grain_visible': False,
                                                                                                'tiny_speck_visible': False,
                                                                                                'microblob_visible': False,
                                                                                                'short_line_visible': False,
                                                                                                'parallel_bundle_visible': False},
                                                                       'required_obvious_artifact_contract_passed': False},
                                           'protocol_zero_audit_passed': True,
                                           'duplicate_audit_passed': False},
                               'population_aggregation_started': False,
                               'numeric_measurement_started': False,
                               'metric_evaluation_started': False,
                               'threshold_search_started': False},
   'r20_sanitized_r19_basis_sha256': '8a99bb7038b5936ac7e44ac339114dc46f78e5d2a8df923a7be0674693d85933',
   'r20_sanitized_r19_failure_audit_canonical_sha256': '54833ae6c35d7ec864f05fabefb8416844c63fe259780bda0ca309b6c31285e0',
   'r20_obvious_artifact_duplicate_sentinel_construction_changes_across_splits': 2,
   'r20_clean_duplicate_construction_changes_across_splits': 0,
   'r20_morphology_tier_minimum_metric_threshold_and_rate_changes_forbidden': True,
   'r20_duplicate_sentinel_vision_truth_guaranteed': False,
    "private_until_one_shot_marker": True,
    "public_manifest_exposure_forbidden": True,
    "generation_design_tiers_are_truth": False,
    "tier_counts_per_artifact_family": {
        "artifact-fine-grain": {
            "clean-candidate": 5,
            "warning-candidate": 4,
            "clear-reject-candidate": 7,
            "dominant-reject-candidate": 4,
        },
        "artifact-speck": {
            "clean-candidate": 4,
            "warning-candidate": 6,
            "clear-reject-candidate": 6,
            "dominant-reject-candidate": 4,
        },
        "artifact-microblob": {
            "clean-candidate": 4,
            "warning-candidate": 6,
            "clear-reject-candidate": 6,
            "dominant-reject-candidate": 4,
        },
        "artifact-short-dash": {
            "clean-candidate": 4,
            "warning-candidate": 6,
            "clear-reject-candidate": 6,
            "dominant-reject-candidate": 4,
        },
        "artifact-parallel-bundle": {
            "clean-candidate": 4,
            "warning-candidate": 6,
            "clear-reject-candidate": 6,
            "dominant-reject-candidate": 4,
        },
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
    "inherited_warning_acceptance_anchor_revision": "dev-r14-quantized-direct-visible-sparse-warning-v1",
    "inherited_warning_acceptance_anchor_conditions_per_split": 16,
    "inherited_warning_acceptance_anchor_schedule_sha256": "5e997df4c7d4e0c6106b3060437235a7f665b08a6b02e00a86f4a4f024dc77e6",
    "warning_acceptance_anchor_revision": "dev-r16-six-per-sparse-family-direct-visible-warning-v1",
    "warning_acceptance_anchor_conditions_per_split": 24,
    "warning_acceptance_anchor_conditions_per_family": {
        "artifact-speck": 6,
        "artifact-microblob": 6,
        "artifact-short-dash": 6,
        "artifact-parallel-bundle": 6,
    },
    "warning_acceptance_anchor_structural_miss_budget_against_development_floor": 11,
    "warning_acceptance_anchor_truth_guarantee_claimed": False,
    "warning_acceptance_anchor_schedule_sha256": "bfc0e95e402c4f5751212c67759940c8c01802bb0a938899304ec4db576aa5df",
    "warning_conversion_revision": "dev-r16-one-clean-one-clear-per-sparse-family-v1",
    "warning_conversion_conditions_per_split": 8,
    "warning_conversion_source_tiers_per_sparse_family": {
        "artifact-speck": {
            "clean-candidate": 1,
            "clear-reject-candidate": 1,
        },
        "artifact-microblob": {
            "clean-candidate": 1,
            "clear-reject-candidate": 1,
        },
        "artifact-short-dash": {
            "clean-candidate": 1,
            "clear-reject-candidate": 1,
        },
        "artifact-parallel-bundle": {
            "clean-candidate": 1,
            "clear-reject-candidate": 1,
        },
    },
    "warning_conversion_schedule_sha256": "0f0f4e0865249d34ff8f83537f60dcaee1c2ee0fd64836551b6aa754251fb8e7",
    "exact_morphology_change_count_across_splits": 16,
    "nonconversion_morphology_change_forbidden": True,
    "predecessor_full_morphology_sha256": "7adf59546337cded9910d17fbff5d383fc36e1058e69f98ed633890c2dd60f5b",
    "preserved_nonconversion_morphology_conditions_across_splits": 184,
    "preserved_nonconversion_morphology_sha256": "b8e7429a62e78c6e67efbfa6ec8b3b2fb0f16fb07f61ea9c7590f83f1b637ecd",
    "preserved_nonwarning_morphology_conditions_across_splits": 144,
    "preserved_nonwarning_morphology_sha256": "72212f11b453526bd6cec7e11420bcb9a0df7bbae2e097168393a5ee0c9a48b4",
    "calibration_microblob_clear_reject_anchor_manifest": {
        "revision": "dev-r15-calibration-quantized-microblob-reject-v1",
        "split": "calibration",
        "family": "artifact-microblob",
        "entries": [
            {
                "variant_index": 1,
                "parameters": {
                    "design_tier": "clear-reject-candidate",
                    "diameter_px": 4,
                    "amplitude_l": 11.6,
                    "count_in_metric_window": 64,
                    "support_radius_px": 2,
                    "minimum_separation_px": 13,
                },
            },
            {
                "variant_index": 2,
                "parameters": {
                    "design_tier": "clear-reject-candidate",
                    "diameter_px": 4,
                    "amplitude_l": 11.8,
                    "count_in_metric_window": 64,
                    "support_radius_px": 2,
                    "minimum_separation_px": 14,
                },
            },
            {
                "variant_index": 9,
                "parameters": {
                    "design_tier": "clear-reject-candidate",
                    "diameter_px": 4,
                    "amplitude_l": 11.4,
                    "count_in_metric_window": 64,
                    "support_radius_px": 2,
                    "minimum_separation_px": 12,
                },
            },
            {
                "variant_index": 13,
                "parameters": {
                    "design_tier": "clear-reject-candidate",
                    "diameter_px": 6,
                    "amplitude_l": 11.6,
                    "count_in_metric_window": 44,
                    "support_radius_px": 3,
                    "minimum_separation_px": 16,
                },
            },
            {
                "variant_index": 16,
                "parameters": {
                    "design_tier": "clear-reject-candidate",
                    "diameter_px": 5,
                    "amplitude_l": 12.0,
                    "count_in_metric_window": 52,
                    "support_radius_px": 3,
                    "minimum_separation_px": 15,
                },
            },
            {
                "variant_index": 17,
                "parameters": {
                    "design_tier": "clear-reject-candidate",
                    "diameter_px": 6,
                    "amplitude_l": 11.8,
                    "count_in_metric_window": 44,
                    "support_radius_px": 3,
                    "minimum_separation_px": 17,
                },
            },
            {
                "variant_index": 18,
                "parameters": {
                    "design_tier": "clear-reject-candidate",
                    "diameter_px": 6,
                    "amplitude_l": 11.4,
                    "count_in_metric_window": 44,
                    "support_radius_px": 3,
                    "minimum_separation_px": 15,
                },
            },
        ],
    },
    "calibration_microblob_clear_reject_anchor_conditions": 7,
    "calibration_microblob_clear_reject_anchor_truth_guarantee_claimed": False,
    "calibration_microblob_clear_reject_anchor_schedule_sha256": "dd2ce7fd13f624bd065e8c7a6bacc2ab8bd593821dec8d46250a40e57ef64833",
    "calibration_microblob_clear_reject_active_indices": [1, 2, 9, 13, 17, 18],
    "calibration_microblob_clear_reject_active_conditions": 6,
    "calibration_microblob_clear_reject_converted_to_warning_index": 16,
    "calibration_microblob_clear_reject_active_schedule_sha256": "2c207dfb5249d42056e164e7553091a9a617d8b673aecfb5ea25e4d757651f0c",
    "speck_reject_source_anchor_conditions_per_split": 10,
    "speck_reject_active_anchor_conditions_per_split": 10,
    "speck_reject_anchor_structural_miss_budget_against_development_floor": 4,
    "speck_reject_anchor_truth_guarantee_claimed": False,
    "speck_reject_anchor_schedule": {
        "revision": "dev-r18-symmetric-reject-speck-direct-visible-cross-v1",
        "inherited_schedule_revision": (
            "dev-r17-protocol-zero-reference-prequalification-schedule-v1"
        ),
        "family": "artifact-speck",
        "target_tiers": [
            "clear-reject-candidate",
            "dominant-reject-candidate",
        ],
        "target_indices": {
            "calibration": [3, 5, 6, 7, 8, 12, 15, 16, 17, 19],
            "holdout": [1, 3, 4, 6, 9, 10, 11, 13, 14, 18],
        },
        "target_conditions_per_split": 10,
        "clear_reject_conditions_per_split": 6,
        "dominant_reject_conditions_per_split": 4,
        "diameter_px": 1,
        "core_count_bounds": [4, 7],
        "center_amplitude_l_bounds": [11.2, 12.0],
        "shoulder_fraction_bounds": [0.42, 0.56],
        "minimum_encoded_axial_shoulder_l": 5,
        "minimum_separation_px": 30,
        "quadrant_stratified": True,
        "returns_to_uninjected_background_outside_one_axial_neighbor": True,
        "microblob_blur_forbidden": True,
        "split_structural_profiles_symmetric": True,
        "split_morphology_tuples_disjoint": True,
        "vision_truth_guaranteed": False,
    },
    "grain_reject_anchor_conditions_per_split": 11,
    "grain_reject_anchor_truth_guarantee_claimed": False,
    "grain_reject_anchor_schedule": {
        "metric_coherence_period_bounds_px": [2, 13],
        "preferred_reject_period_bounds_px": [3, 12],
        "calibration": {
            "clear": [
                ["fine-band", 8.8],
                ["halftone", 11],
                ["fine-band", 12.0],
                ["fine-band", 6.7],
                ["halftone", 10],
                ["fine-band", 11.6],
                ["fine-band", 4.1],
            ],
            "dominant": [
                ["halftone", 7],
                ["fine-band", 4.8],
                ["fine-band", 8.0],
                ["fine-band", 3.0],
            ],
        },
        "holdout": {
            "clear": [
                ["halftone", 9],
                ["fine-band", 11.4],
                ["fine-band", 7.1],
                ["fine-band", 11.8],
                ["halftone", 12],
                ["fine-band", 4.5],
                ["fine-band", 9.2],
            ],
            "dominant": [
                ["fine-band", 5.1],
                ["fine-band", 8.4],
                ["fine-band", 3.3],
                ["halftone", 8],
            ],
        },
        "split_pattern_period_tuples_disjoint": True,
    },
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

R20_POPULATION_ANCHOR_SCHEDULE_CHANGED_KEYS = (
    "revision",
    "fresh_from_closed_dev_r18",
    "r18_parameter_nonce_reuse_forbidden",
    "r18_per_family_residue_rotation",
    "r19_parameter_nonce_bases",
    "inherited_r18_schedule_revision",
    "preserved_r17_artifact_morphology_conditions_across_splits",
    "preserved_r17_artifact_morphology_sha256",
    "r18_exact_morphology_change_count_across_splits",
    "r18_speck_reinforcement_revision",
    "r18_speck_reinforcement_manifest_sha256",
    "r18_full_artifact_morphology_sha256",
    "r18_target_speck_conditions_per_split",
    "r18_target_speck_tiers_per_split",
    "r18_tiny_speck_structural_miss_budget",
    "r18_spot_detection_increment_required_from_sanitized_r17_holdout",
    "r18_sanitized_r17_basis",
    "r18_sanitized_r17_basis_sha256",
    "r18_metric_threshold_population_and_rate_contract_changes_forbidden",
    "r19_preserved_r18_artifact_morphology_conditions_across_splits",
    "r19_preserved_r18_artifact_morphology_sha256",
    "r19_exact_morphology_change_count_across_splits",
    "r19_duplicate_equivalence_policy_revision",
    "r19_duplicate_equivalence_policy_manifest",
    "r19_duplicate_equivalence_policy_manifest_sha256",
    "r19_sanitized_r18_basis",
    "r19_sanitized_r18_basis_sha256",
    "r19_morphology_tier_minimum_metric_threshold_and_rate_changes_forbidden",
    "speck_reject_source_anchor_conditions_per_split",
    "speck_reject_active_anchor_conditions_per_split",
    "speck_reject_anchor_structural_miss_budget_against_development_floor",
    "speck_reject_anchor_truth_guarantee_claimed",
    "speck_reject_anchor_schedule",
    "fresh_from_closed_dev_r19",
    "r19_parameter_nonce_reuse_forbidden",
    "r20_parameter_nonce_bases",
    "inherited_r19_schedule_revision",
    "r20_predecessor_catalog_authority_sha256",
    "r20_preserved_r19_artifact_morphology_conditions_across_splits",
    "r20_preserved_r19_artifact_morphology_sha256",
    "r20_exact_morphology_change_count_across_splits",
    "r20_duplicate_equivalence_policy_revision",
    "r20_duplicate_equivalence_policy_manifest",
    "r20_duplicate_equivalence_policy_manifest_sha256",
    "r20_duplicate_sentinel_revision",
    "r20_duplicate_sentinel_manifest",
    "r20_duplicate_sentinel_manifest_sha256",
    "r20_sanitized_r19_basis",
    "r20_sanitized_r19_basis_sha256",
    "r20_sanitized_r19_failure_audit_canonical_sha256",
    "r20_obvious_artifact_duplicate_sentinel_construction_changes_across_splits",
    "r20_clean_duplicate_construction_changes_across_splits",
    "r20_morphology_tier_minimum_metric_threshold_and_rate_changes_forbidden",
    "r20_duplicate_sentinel_vision_truth_guaranteed",
)
R20_INHERITED_SPECK_REJECT_ANCHOR_SCHEDULE_SHA256 = (
    "ed60c8f99b7338c4ca66246312b7d9a48648519257a3079ba06e0aba1e19e317"
)
R20_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES_SHA256 = (
    "3b87c5aabee0c8c8641d80496123a4f2dd58ca60f6da2bcf822e6bc7dfa80368"
)
R20_POPULATION_ANCHOR_SCHEDULE_KEYSET_SHA256 = (
    "b5c8211902bb03838e7fe402bbb48e0e7f7a9db37acd1856be3dca2c67b82134"
)

RENDERING_INVARIANTS = {
    "hard_speck_integer_core_contract": (
        "artifact-speck retains an unblurred exact one-pixel integer-lattice core; "
        "clean and warning conditions retain their inherited shoulders, while the ten "
        "preregistered reject targets per split use only four axial neighbours whose "
        "encoded magnitude is at least 5 L"
    ),
    "hard_speck_separation_contract": (
        "all inherited artifact-speck conditions retain their prior separation; the "
        "ten r18 reject targets per split require at least 30-pixel pairwise Chebyshev "
        "separation, disjoint one-neighbour crosses, and uninjected background beyond "
        "that support"
    ),
    "hard_speck_quadrant_stratification_contract": (
        "artifact-speck integer centers use deterministic round-robin packing "
        "across the four exact metric-window quadrants with quadrant counts differing "
        "by at most one; a count of at least four covers every quadrant"
    ),
    "hard_speck_reject_anchor_contract": (
        "the ten r18 target conditions per split preserve reject-tier membership and "
        "replace only their speck morphology with four through seven quadrant-stratified "
        "direct-visible one-pixel cores; this is a preregistered coverage reinforcement, "
        "not assigned Vision truth, and cannot bypass the post-seal population gate"
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
    require_exact_keys(
        history,
        {
            "r3_status",
            "r3_role",
            "r3_failure_audit",
            "r4_status",
            "r4_role",
            "r4_failure_audit",
            "r5_status",
            "r5_role",
            "r5_failure_audit",
            "dev_r6_status",
            "dev_r6_role",
            "dev_r7_status",
            "dev_r7_role",
            "dev_r7_failure_audit",
            "dev_r7_failure_audit_sha256",
            "dev_r8_status",
            "dev_r8_role",
            "dev_r8_failure_audit",
            "dev_r8_failure_audit_sha256",
            "dev_r9_status",
            "dev_r9_role",
            "dev_r9_failure_audit",
            "dev_r9_failure_audit_sha256",
            "dev_r10_status",
            "dev_r10_role",
            "dev_r10_failure_audit",
            "dev_r10_failure_audit_sha256",
            "dev_r11_status",
            "dev_r11_role",
            "dev_r11_failure_audit",
            "dev_r11_failure_audit_sha256",
            "dev_r12_status",
            "dev_r12_role",
            "dev_r12_failure_audit",
            "dev_r12_failure_audit_sha256",
            "dev_r13_status",
            "dev_r13_role",
            "dev_r13_failure_audit",
            "dev_r13_failure_audit_sha256",
            "dev_r14_status",
            "dev_r14_role",
            "dev_r14_failure_audit",
            "dev_r14_failure_audit_sha256",
            "dev_r15_status",
            "dev_r15_role",
            "dev_r15_failure_audit",
            "dev_r15_failure_audit_sha256",
            "dev_r16_status",
            "dev_r16_role",
            "dev_r16_failure_audit",
            "dev_r16_failure_audit_sha256",
            "dev_r17_status",
            "dev_r17_role",
            "dev_r17_failure_audit",
            "dev_r17_failure_audit_sha256",
            "dev_r18_status",
            "dev_r18_role",
            "dev_r18_failure_audit",
            "dev_r18_failure_audit_sha256",
            "dev_r19_status",
            "dev_r19_role",
            "dev_r19_failure_audit",
            "dev_r19_failure_audit_sha256",
            "dev_r20_status",
            "dev_r20_role",
            "dev_r20_failure_audit",
            "dev_r20_failure_audit_sha256",
        },
        "r6 development history",
    )
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
        or history.get("dev_r8_status")
        != "failed-and-closed-before-measurement"
        or history.get("dev_r8_role")
        != "development-only population-feasibility failure evidence; both splits "
        "failed only the tiny-speck-visible reject population endpoint after all 440 "
        "records were blindly reviewed and reconciled, the edition closed before any "
        "numeric metric call, and no dev-r8 key, control, label, pixel, identity, "
        "placement, parameter nonce, measurement, threshold, commitment, or artifact "
        "root is reusable"
        or history.get("dev_r8_failure_audit")
        != "world/map-production/qa/"
        "microtexture-v2-r6-dev-r8-development-failure.json"
        or history.get("dev_r8_failure_audit_sha256")
        != "39c7472f8018cbbf25cbd029cb915c43696a07b6c52e8e586e02fe5a99dbc07d"
        or history.get("dev_r9_status")
        != "failed-and-closed-after-measurement"
        or history.get("dev_r9_role")
        != "development-only threshold-feasibility failure evidence; both splits "
        "passed every population floor and were measured once, but calibration had "
        "no scalar threshold satisfying warning acceptance at least 0.75 together "
        "with severity-3 detection exactly 1.0, no threshold was selected, holdout "
        "endpoint performance was not evaluated, and no dev-r9 key, control, label, "
        "pixel, identity, measurement, threshold diagnostic, nonce, commitment, or "
        "artifact root is reusable"
        or history.get("dev_r9_failure_audit")
        != "world/map-production/qa/"
        "microtexture-v2-r6-dev-r9-development-failure.json"
        or history.get("dev_r9_failure_audit_sha256")
        != "10c832fb2b7131b942cad54c7412672a98a2f0401db1aae31ce2b1383952f202"
        or history.get("dev_r10_status")
        != "failed-and-closed-during-generation"
        or history.get("dev_r10_role")
        != "development-only generation-interruption evidence; one-shot generation "
        "started with a fresh key and produced the calibration public surface only; "
        "the required two-split generation did not reach terminal summary, seal, or "
        "completion, no Vision review or analysis started, and no dev-r10 root, key, "
        "control, reference, pixel, identity, code, commitment, label, measurement, "
        "nonce, or public surface is reusable"
        or history.get("dev_r10_failure_audit")
        != "world/map-production/qa/"
        "microtexture-v2-r6-dev-r10-development-failure.json"
        or history.get("dev_r10_failure_audit_sha256")
        != "9e5533453e7ec25bed75b54a67cb63129329aca392c1c7db4bf60d9c0a7393fa"
        or history.get("dev_r11_status")
        != "failed-and-closed-before-measurement"
        or history.get("dev_r11_role")
        != "development-only premeasurement Vision-gate failure evidence; "
        "generation and both blind reviews completed, labels were sealed, and the "
        "private sentinel audit then found one sealed holdout false positive on an "
        "exact-zero protocol sentinel before population aggregation or numeric "
        "measurement; no dev-r11 root, key, control, reference, pixel, identity, "
        "code, commitment, label, measurement, nonce, or public surface is reusable"
        or history.get("dev_r11_failure_audit")
        != "world/map-production/qa/"
        "microtexture-v2-r6-dev-r11-development-failure.json"
        or history.get("dev_r11_failure_audit_sha256")
        != "a1dcf2354ec6b0bc81ae89f75eadc11f1a522be73de66032f94048d1a411ef04"
        or history.get("dev_r12_status")
        != "failed-and-closed-before-measurement"
        or history.get("dev_r12_role")
        != "development-only premeasurement population failure evidence; both "
        "private audits passed, calibration warning population 10 met formal "
        "minimum 10 but missed development floor 13, holdout warning population 9 "
        "missed formal minimum 10 and development floor 13, every other endpoint "
        "passed both minima, no numeric metric or threshold search started, and no "
        "dev-r12 root, key, control, reference, pixel, identity, code, commitment, "
        "label, measurement, nonce, public surface, or postmortem output is reusable"
        or history.get("dev_r12_failure_audit")
        != "world/map-production/qa/"
        "microtexture-v2-r6-dev-r12-development-failure.json"
        or history.get("dev_r12_failure_audit_sha256")
        != "d972da0d73d3e9b057a37941b186e0b7b16eaefe1e18a28ed3a7f9bbdadb60f6"
        or history.get("dev_r13_status")
        != "failed-and-closed-before-measurement"
        or history.get("dev_r13_role")
        != "development-only premeasurement population failure evidence; both "
        "private audits passed, calibration warning population 14 passed formal "
        "minimum 10 and development floor 13, holdout warning population 12 passed "
        "formal minimum 10 but missed development floor 13, every other endpoint "
        "passed both minima, no numeric metric or threshold search started, and no "
        "dev-r13 root, key, control, reference, pixel, identity, code, commitment, "
        "label, measurement, nonce, public surface, or postmortem output is reusable"
        or history.get("dev_r13_failure_audit")
        != "world/map-production/qa/"
        "microtexture-v2-r6-dev-r13-development-failure.json"
        or history.get("dev_r13_failure_audit_sha256")
        != "2fbc67f05b3b5ec065f79e7f9118fd5d06b5966dd78c95da191c37761f215634"
        or history.get("dev_r14_status")
        != "failed-and-closed-before-measurement"
        or history.get("dev_r14_role")
        != "development-only premeasurement population failure evidence; both "
        "private audits passed, calibration microblob population 4 met formal "
        "minimum 4 but missed development floor 6, every other calibration endpoint "
        "and every holdout endpoint passed both minima, no numeric metric or threshold "
        "search started, and no dev-r14 root, key, control, reference, pixel, identity, "
        "code, commitment, label, measurement, nonce, public surface, or postmortem "
        "output is reusable"
        or history.get("dev_r14_failure_audit")
        != "world/map-production/qa/"
        "microtexture-v2-r6-dev-r14-development-failure.json"
        or history.get("dev_r14_failure_audit_sha256")
        != "79acad1ef7972293e2697bd4c81edcc2c6ec017b4121e6609b94b95391c25476"
        or history.get("dev_r15_status")
        != "failed-and-closed-before-measurement"
        or history.get("dev_r15_role")
        != "development-only premeasurement population failure evidence; both "
        "private audits passed, calibration warning population 12 met formal "
        "minimum 10 but missed development floor 13, holdout warning population 9 "
        "missed formal minimum 10 and development floor 13, every other endpoint "
        "passed both minima, no numeric metric or threshold search started, and no "
        "dev-r15 root, key, control, reference, pixel, identity, code, commitment, "
        "label, decision, measurement, nonce, public surface, or postmortem output "
        "is reusable"
        or history.get("dev_r15_failure_audit")
        != "world/map-production/qa/"
        "microtexture-v2-r6-dev-r15-development-failure.json"
        or history.get("dev_r15_failure_audit_sha256")
        != "faa420e63af8b3f647e045ae4d71ac2fbe32316175e68999cc16b3e278311200"
        or history.get("dev_r16_status")
        != "failed-and-closed-before-measurement"
        or history.get("dev_r16_role")
        != "development-only premeasurement Vision-gate failure evidence; generation, "
        "both blind 440-record reviews, reconciliation, official preflight, label "
        "sealing, and private reveal each completed exactly once, then the private "
        "audits failed on one sealed holdout severity-1 short-line warning false "
        "positive on an exact-zero protocol sentinel; population aggregation, numeric "
        "measurement, and threshold search never started, one read-only postmortem ran "
        "exactly once, all initial snapshots remain immutable, and no dev-r16 root, key, "
        "secret, control, reference, pixel, identity, code, commitment, label, decision, "
        "measurement, nonce, public surface, postmortem output, or private material is "
        "reusable"
        or history.get("dev_r16_failure_audit")
        != "world/map-production/qa/"
        "microtexture-v2-r6-dev-r16-development-failure.json"
        or history.get("dev_r16_failure_audit_sha256")
        != "4637978a7ac5d59c99ec076e527b7be6e5d2ad1c0477077e2587fda7091ca169"
        or history.get("dev_r17_status")
        != "failed-and-closed-before-measurement"
        or history.get("dev_r17_role")
        != "development-only premeasurement population failure evidence; both private "
        "audits passed, every calibration endpoint passed formal and development minima, "
        "holdout tiny-speck population 0 missed formal minimum 4 and development floor 6, "
        "holdout spot population 9 passed formal minimum 8 but missed development floor "
        "10, every other holdout endpoint passed both minima, no numeric metric or "
        "threshold search started, one read-only postmortem ran exactly once, all Root "
        "and Independent initial snapshots and receipts remain immutable, and no dev-r17 "
        "root, key, private material, control, reference, pixel, identity, code, "
        "commitment, label, decision, measurement, nonce, public surface, or postmortem "
        "output is reusable"
        or history.get("dev_r17_failure_audit")
        != "world/map-production/qa/"
        "microtexture-v2-r6-dev-r17-development-failure.json"
        or history.get("dev_r17_failure_audit_sha256")
        != "2177b04b6f79b75394cbdef6204423194603cd81e3a84b5a673c58393ccf5856"
        or history.get("dev_r18_status")
        != "failed-and-closed-before-population-audit"
        or history.get("dev_r18_role")
        != "development-only prepopulation private-audit failure evidence; generation, "
        "both blind 440-record reviews, bilateral reconciliation, official preflight, "
        "label sealing, private reveal, regeneration, and protocol-zero audits each "
        "completed exactly once, but calibration's obvious-artifact duplicate pair had "
        "identical reject dispositions and short-line flags with ordinal severities 2 "
        "and 3, so the then-exact severity semantic check failed before population "
        "audit or any numeric measurement; one read-only postmortem ran exactly once, "
        "all initial snapshots and receipts remain immutable, and no dev-r18 root, key, "
        "private material, control, reference, pixel, identity, code, commitment, label, "
        "decision, measurement, nonce, public surface, or postmortem output is reusable"
        or history.get("dev_r18_failure_audit")
        != "world/map-production/qa/"
        "microtexture-v2-r6-dev-r18-development-failure.json"
        or history.get("dev_r18_failure_audit_sha256")
        != "7800ab0f33363df30decb1c744e1b1ed3b7c822bb2f94fc4a17fd44d35541122"
        or history.get("dev_r19_status")
        != "failed-and-closed-before-population-audit"
        or history.get("dev_r19_role")
        != "development-only prepopulation private-audit failure evidence; generation, "
        "both blind 440-record reviews, bilateral reconciliation, official preflight, "
        "label sealing, private reveal, regeneration, and protocol-zero audits each "
        "completed exactly once, calibration clean and obvious-artifact duplicate "
        "groups plus the holdout clean duplicate group passed, but holdout's obvious-"
        "artifact duplicate pair was clean severity 0 with no visible flags, so the "
        "required rejected short-line artifact contract failed before population audit "
        "or any numeric measurement; one read-only postmortem ran exactly once, all "
        "initial snapshots and receipts remain immutable, and no dev-r19 root, key, "
        "private material, control, reference, pixel, identity, code, commitment, label, "
        "decision, measurement, nonce, public surface, or postmortem output is reusable"
        or history.get("dev_r19_failure_audit")
        != "world/map-production/qa/"
        "microtexture-v2-r6-dev-r19-development-failure.json"
        or history.get("dev_r19_failure_audit_sha256")
        != "96d93fe63be2ff6171ade926dbace188b6fd5eacf748a6f03a787781a5d248d0"
        or history.get("dev_r20_status") != DEV_R20_CLOSED_STATUS
        or history.get("dev_r20_role") != DEV_R20_CLOSED_ROLE
        or history.get("dev_r20_failure_audit") != DEV_R20_FAILURE_AUDIT_REL
        or history.get("dev_r20_failure_audit_sha256")
        != DEV_R20_FAILURE_AUDIT_RAW_SHA256
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
        "scope": DEV_R20_CLOSED_SECRET_SCOPE,
        "fresh_key_generation": "secrets.token_bytes(32) inside the tracked development runner",
        "ignored_private_key_required_repo_relative": "tmp/map-production/microtexture-v2-r6-dev-r20/private/development-key.bin",
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
        "development_root_existence_is_consumed_evidence": True,
        "generation_start_required_before_public_output": True,
        "catchable_post_start_generation_failure_uses_exclusive_failure_report": True,
        "generation_success_requires_summary_seal_and_completion": True,
        "public_generation_writes_are_exclusive": True,
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
            "fresh dev-r8 generation; dev-r8 stopped before measurement and therefore "
            "supplied no score or threshold evidence",
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
            "dev_r9_completed_failed_closed": True,
            "dev_r10_generation_interrupted_failed_closed": True,
            "dev_r11_premeasurement_vision_gate_failed_closed": True,
            "dev_r12_premeasurement_population_gate_failed_closed": True,
            "dev_r12_measurement_or_threshold_reuse_forbidden_because_absent": True,
            "fresh_successor_after_dev_r12_required": True,
            "dev_r13_premeasurement_population_gate_failed_closed": True,
            "dev_r13_measurement_or_threshold_reuse_forbidden_because_absent": True,
            "fresh_successor_after_dev_r13_required": True,
            "dev_r7_threshold_or_measurement_reuse_for_formal_forbidden": True,
            "dev_r8_measurement_or_threshold_reuse_forbidden_because_absent": True,
            "dev_r9_measurement_threshold_diagnostic_or_holdout_reuse_forbidden": True,
            "dev_r10_measurement_or_threshold_reuse_forbidden_because_absent": True,
            "dev_r11_measurement_or_threshold_reuse_forbidden_because_absent": True,
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
        or definition.get("development_basis") != R20_DEVELOPMENT_BASIS
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
    changed_schedule_values = {
        key: anchor_schedule[key]
        for key in R20_POPULATION_ANCHOR_SCHEDULE_CHANGED_KEYS
    }
    if (
        len(anchor_schedule) != 105
        or list(anchor_schedule) != list(POPULATION_ANCHOR_SCHEDULE)
        or sha256_bytes(canonical_json_bytes(sorted(anchor_schedule)))
        != R20_POPULATION_ANCHOR_SCHEDULE_KEYSET_SHA256
        or sha256_bytes(canonical_json_bytes(changed_schedule_values))
        != R20_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES_SHA256
        or sha256_bytes(
            canonical_json_bytes(anchor_schedule["speck_reject_anchor_schedule"])
        )
        != R20_INHERITED_SPECK_REJECT_ANCHOR_SCHEDULE_SHA256
        or sha256_bytes(
            canonical_json_bytes(anchor_schedule["r18_sanitized_r17_basis"])
        )
        != anchor_schedule["r18_sanitized_r17_basis_sha256"]
        or sha256_bytes(
            canonical_json_bytes(
                anchor_schedule["r19_duplicate_equivalence_policy_manifest"]
            )
        )
        != anchor_schedule["r19_duplicate_equivalence_policy_manifest_sha256"]
        or sha256_bytes(
            canonical_json_bytes(anchor_schedule["r19_sanitized_r18_basis"])
        )
        != anchor_schedule["r19_sanitized_r18_basis_sha256"]
        or sha256_bytes(
            canonical_json_bytes(
                anchor_schedule["r20_duplicate_equivalence_policy_manifest"]
            )
        )
        != anchor_schedule["r20_duplicate_equivalence_policy_manifest_sha256"]
        or sha256_bytes(
            canonical_json_bytes(anchor_schedule["r20_duplicate_sentinel_manifest"])
        )
        != anchor_schedule["r20_duplicate_sentinel_manifest_sha256"]
        or sha256_bytes(
            canonical_json_bytes(anchor_schedule["r20_sanitized_r19_basis"])
        )
        != anchor_schedule["r20_sanitized_r19_basis_sha256"]
    ):
        raise RuntimeError("r6 dev-r20 population-anchor authority digest drift")
    formal_minima = {
        endpoint["id"]: int(endpoint["minimum_unique_clusters"])
        for endpoint in EXPECTED_ENDPOINT_DEFINITIONS
    }
    derived_safety_floors = {
        endpoint_id: max(minimum + 2, math.ceil(1.25 * minimum))
        for endpoint_id, minimum in formal_minima.items()
    }
    expected_tier_counts = {
        "artifact-fine-grain": {
            "clean-candidate": 5,
            "warning-candidate": 4,
            "clear-reject-candidate": 7,
            "dominant-reject-candidate": 4,
        },
        **{
            family: {
                "clean-candidate": 4,
                "warning-candidate": 6,
                "clear-reject-candidate": 6,
                "dominant-reject-candidate": 4,
            }
            for family in (
                "artifact-speck",
                "artifact-microblob",
                "artifact-short-dash",
                "artifact-parallel-bundle",
            )
        },
    }
    if (
        anchor_schedule["development_premeasurement_safety_floors"]
        != derived_safety_floors
        or anchor_schedule["tier_counts_per_artifact_family"]
        != expected_tier_counts
        or any(sum(counts.values()) != 20 for counts in expected_tier_counts.values())
        or len(anchor_schedule["artifact_families_covered"]) != 5
        or anchor_schedule["inherited_warning_acceptance_anchor_conditions_per_split"]
        != 16
        or anchor_schedule["warning_acceptance_anchor_conditions_per_split"] != 24
        or sum(
            anchor_schedule["warning_acceptance_anchor_conditions_per_family"].values()
        )
        != 24
        or anchor_schedule[
            "warning_acceptance_anchor_structural_miss_budget_against_development_floor"
        ]
        != 11
        or anchor_schedule["warning_acceptance_anchor_truth_guarantee_claimed"]
        is not False
        or anchor_schedule["warning_conversion_conditions_per_split"] != 8
        or any(
            source_counts != {"clean-candidate": 1, "clear-reject-candidate": 1}
            for source_counts in anchor_schedule[
                "warning_conversion_source_tiers_per_sparse_family"
            ].values()
        )
        or anchor_schedule["exact_morphology_change_count_across_splits"] != 16
        or anchor_schedule["nonconversion_morphology_change_forbidden"] is not True
        or anchor_schedule[
            "preserved_nonconversion_morphology_conditions_across_splits"
        ]
        != 184
        or anchor_schedule[
            "preserved_nonwarning_morphology_conditions_across_splits"
        ]
        != 144
        or anchor_schedule["calibration_microblob_clear_reject_anchor_conditions"]
        != 7
        or anchor_schedule[
            "calibration_microblob_clear_reject_anchor_truth_guarantee_claimed"
        ]
        is not False
        or len(
            anchor_schedule["calibration_microblob_clear_reject_anchor_manifest"][
                "entries"
            ]
        )
        != 7
        or anchor_schedule["calibration_microblob_clear_reject_active_indices"]
        != [1, 2, 9, 13, 17, 18]
        or anchor_schedule["calibration_microblob_clear_reject_active_conditions"]
        != 6
        or anchor_schedule[
            "calibration_microblob_clear_reject_converted_to_warning_index"
        ]
        != 16
        or anchor_schedule["speck_reject_source_anchor_conditions_per_split"]
        != 10
        or anchor_schedule["speck_reject_active_anchor_conditions_per_split"]
        != 10
        or anchor_schedule[
            "speck_reject_anchor_structural_miss_budget_against_development_floor"
        ]
        != 4
        or anchor_schedule["r18_target_speck_conditions_per_split"] != 10
        or sum(anchor_schedule["r18_target_speck_tiers_per_split"].values()) != 10
        or anchor_schedule["r18_tiny_speck_structural_miss_budget"] != 4
        or anchor_schedule[
            "r18_spot_detection_increment_required_from_sanitized_r17_holdout"
        ]
        != 1
        or anchor_schedule[
            "preserved_r17_artifact_morphology_conditions_across_splits"
        ]
        + anchor_schedule["r18_exact_morphology_change_count_across_splits"]
        != 200
        or anchor_schedule[
            "r18_metric_threshold_population_and_rate_contract_changes_forbidden"
        ]
        is not True
        or anchor_schedule["fresh_from_closed_dev_r19"] is not True
        or anchor_schedule["r19_parameter_nonce_reuse_forbidden"] is not True
        or anchor_schedule[
            "r20_preserved_r19_artifact_morphology_conditions_across_splits"
        ]
        + anchor_schedule["r20_exact_morphology_change_count_across_splits"]
        != 200
        or anchor_schedule[
            "r20_obvious_artifact_duplicate_sentinel_construction_changes_across_splits"
        ]
        != 2
        or anchor_schedule[
            "r20_clean_duplicate_construction_changes_across_splits"
        ]
        != 0
        or anchor_schedule[
            "r20_morphology_tier_minimum_metric_threshold_and_rate_changes_forbidden"
        ]
        is not True
        or anchor_schedule["r20_duplicate_sentinel_vision_truth_guaranteed"]
        is not False
        or anchor_schedule["r20_duplicate_sentinel_manifest"]["construction"][
            "bar_count_in_metric_window"
        ]
        != 12
        or anchor_schedule["r20_duplicate_sentinel_manifest"]["construction"][
            "bars_per_exact_metric_quadrant"
        ]
        != 3
        or anchor_schedule["r20_duplicate_sentinel_manifest"]["raster_contract"][
            "nonzero_pixel_count"
        ]
        != 864
        or anchor_schedule["grain_reject_anchor_conditions_per_split"] != 11
        or anchor_schedule["grain_reject_anchor_truth_guarantee_claimed"] is not False
        or anchor_schedule["grain_reject_anchor_schedule"][
            "metric_coherence_period_bounds_px"
        ]
        != [2, 13]
        or anchor_schedule["grain_reject_anchor_schedule"][
            "preferred_reject_period_bounds_px"
        ]
        != [3, 12]
        or anchor_schedule["grain_reject_anchor_schedule"][
            "split_pattern_period_tuples_disjoint"
        ]
        is not True
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
        "hard_speck_reject_anchor_contract",
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
        or rendering.get("fine_grain_contract")
        != "artifact-fine-grain contains exactly 20 frozen nonzero oriented "
        "fine-band or halftone conditions per split with split-specific scale, "
        "amplitude, pattern, and metric-window support schedules; any sparse-support "
        "candidate retains deterministic nonzero support, every remaining condition "
        "retains its frozen full-support contract, and all eleven full-support "
        "reject-tier grain periods per split are statically constrained to the "
        "inclusive 3..12 pixel guard-banded interior of the unchanged 2..13 pixel "
        "coherence support"
        or rendering.get("duplicate_audit_contract")
        != "the clean semantic audit group retains its exact-zero construction; the "
        "obvious-artifact group uses the r20 fresh-keyed finite axial short-line "
        "sentinel; each group contains two separately coded records with distinct "
        "private reference and control bytes, equal requested-delta bytes, exact "
        "decoded-residual and metric equality, and labels satisfying the preserved "
        "dev-r19 reject-band policy"
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
        or private_audits.get("duplicate_artifact")
        != "the two separately coded obvious-artifact records must have exact "
        "disposition and exact values for all five visible flags across the pair, both "
        "must be reject with short_line_visible=true, and each severity must "
        "independently belong to the inclusive reject ordinal band {2,3}; severity "
        "equality within that band is not required"
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
            "private_identity_domains",
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
    if (
        catalog.get("exact_variant_source")
        != "the tracked control_catalog.py named by implementation-bindings.json; r20 "
        "preserves the full hash-bound r19 artifact morphology catalog and dev-r19 "
        "duplicate semantic-equivalence policy byte-for-byte, preserves the clean "
        "duplicate, and changes only the obvious-artifact duplicate sentinel "
        "construction"
        or catalog.get("artifact_contract")
        != "five morphology families, exactly 20 nonzero conditions per family, "
        "paired dark/light polarities, one replicate per polarity, and no zero-count "
        "artifact condition"
        or catalog.get("foundation_assignment")
        != "secret-HMAC-derived; cluster mates may share a v15/v16/v17 source asset "
        "but every record receives a distinct keyed private reference transform"
        or catalog.get("duplicate_audit_contract")
        != "one unchanged clean and one strengthened obvious-artifact private "
        "semantic-replicate cluster; the strengthened pair uses twelve keyed finite "
        "24-by-3 pixel positive-L axial bars, exactly three per metric quadrant with "
        "both orientations; pair deltas, decoded residuals, and metrics are exact while "
        "references, controls, codes, and control identities remain distinct and "
        "private"
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
    if catalog.get("private_identity_domains") != {
        "private_reference_transform_prefix": "private-reference-transform-v15/",
        "foundation_offset_lane": "foundation-offset-v14",
        "foundation_assignment_lane": "foundation-assignment-v14",
        "delta_lane": "delta-v14",
        "private_control_id_prefix": "microtexture-v2-r6/private-control-id/v14/",
    }:
        raise RuntimeError("r6 private identity domain contract drift")

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
            split_contract.get("public_nonce") != f"r6-{split_name}-v15"
            or split_contract.get("default_replicates_per_variant") != 1
            or split_contract.get("duplicate_audit_replicates_per_variant") != 2
        ):
            raise RuntimeError(f"r6 split replicate contract drift: {split_name}")
    blind = value.get("blind_derivation", {})
    if (
        blind.get("key_commitment_message") != "microtexture-v2-r6/key-commitment/v14"
        or blind.get("seed_message_prefix") != "microtexture-v2-r6/render-seed/v15/"
        or blind.get("code_message_prefix") != "microtexture-v2-r6/opaque-code/v15/"
        or blind.get("formal_secret_value_artifact_or_log_persistence_forbidden")
        is not True
    ):
        raise RuntimeError("r6 revision-15 blind derivation domain drift")
    if (
        cluster.get("message_prefix")
        != "microtexture-v2-r6/private-condition-cluster/v15/"
        or value.get("rendering", {}).get("public_commitment_domain")
        != "microtexture-v2-r6/public-payload-commitment/v16/"
        "{control|reference|delta}/{anonymous_code}/{raw-sha256-bytes}"
    ):
        raise RuntimeError("r6 revision-15/16 private/public commitment domain drift")
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
        public_policy.get("reviewer_access_contract")
        != DEV_R20_CLOSED_REVIEWER_ACCESS_CONTRACT
    ):
        raise RuntimeError("r6 dev-r20 reviewer-access contract drift")
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


def validate_dev_r8_failure_audit(value: Any) -> None:
    """Validate the sanitized, tracked dev-r8 premeasurement failure evidence."""

    context = "closed dev-r8 failure audit"
    require_exact_keys(
        value,
        {
            "artifact",
            "schema_version",
            "authority",
            "formal_use_forbidden",
            "audit_recorded_at",
            "development_edition",
            "outcome",
            "measurement_started",
            "selection_status",
            "development_hard_threshold",
            "holdout_endpoint_performance",
            "one_shot_contract",
            "vision_review",
            "population_audit",
            "hash_bindings",
            "absent_measurement_artifacts",
            "root_cause",
            "successor_constraints",
            "secret_handling",
        },
        context,
    )
    parse_utc_timestamp(value["audit_recorded_at"], f"{context}.audit_recorded_at")
    if (
        value["artifact"]
        != "microtexture-v2-r6-dev-r8-development-failure-audit"
        or value["schema_version"]
        != "microtexture-v2-r6-development-failure-audit/2"
        or value["authority"] is not False
        or value["formal_use_forbidden"] is not True
        or value["development_edition"] != "r8"
        or value["outcome"] != "failed_closed"
        or value["measurement_started"] is not False
        or value["selection_status"] != "not_started_population_gate_failed"
        or value["development_hard_threshold"] is not None
        or value["holdout_endpoint_performance"] is not None
    ):
        raise RuntimeError(f"{context} header/outcome drift")

    if value["one_shot_contract"] != {
        "generation_completed_exactly_once": True,
        "root_vision_completed_before_private_reveal": True,
        "independent_vision_completed_before_private_reveal": True,
        "labels_sealed_before_private_reveal": True,
        "analysis_started_exactly_once": True,
        "population_audit_passed_before_measurement": False,
        "numeric_metric_called": False,
        "threshold_search_started": False,
        "formal_cli_invoked": False,
        "formal_marker_created": False,
        "formal_threshold_created": False,
        "locked_clean_v18_decoded_or_measured": False,
        "rerun_relabel_retune_subset_topup_resample_or_reuse_for_r8_forbidden": True,
        "r8_closed": True,
    }:
        raise RuntimeError(f"{context} one-shot closure drift")

    if value["vision_review"] != {
        "calibration_records_reviewed_by_root": 220,
        "holdout_records_reviewed_by_root": 220,
        "calibration_records_reviewed_independently": 220,
        "holdout_records_reviewed_independently": 220,
        "logical_comparison_fields": [
            "page",
            "row",
            "anonymous_code",
            "disposition",
            "severity",
            "flags",
        ],
        "notes_and_ev3_locators_excluded_from_initial_logical_comparison": True,
        "root_and_initial_independent_exact_logical_agreement": False,
        "calibration_root_independent_initial_logical_difference_count": 32,
        "calibration_initial_difference_breakdown": {
            "identity": 0,
            "disposition": 23,
            "severity": 31,
            "flags": 3,
        },
        "holdout_root_independent_initial_logical_difference_count": 28,
        "holdout_initial_difference_breakdown": {
            "identity": 0,
            "disposition": 11,
            "severity": 24,
            "flags": 7,
        },
        "root_reinspected_every_initial_logical_difference": True,
        "root_and_independent_logical_decisions_reconciled": True,
        "canonical_root_and_final_independent_bytes_identical_after_reconciliation": True,
        "calibration_root_decisions_sha256": (
            "a27a038bd9310670d58b5bfb81367a83910cd3a70977cce63b9a4ac7fee3656e"
        ),
        "calibration_initial_independent_decisions_sha256": (
            "d9136e4836a574c7035c64277589644550a7512197b1fa0f4bc0f034196021d6"
        ),
        "calibration_final_independent_decisions_sha256": (
            "a27a038bd9310670d58b5bfb81367a83910cd3a70977cce63b9a4ac7fee3656e"
        ),
        "calibration_canonical_decisions_sha256": (
            "a27a038bd9310670d58b5bfb81367a83910cd3a70977cce63b9a4ac7fee3656e"
        ),
        "calibration_sealed_labels_sha256": (
            "5598120ff0a84e3170803ced7ce44f2f339a921c1f4c3d0987439d4c1f1790ad"
        ),
        "holdout_root_decisions_sha256": (
            "7bbe9ebb6016bb369c194fb4c766be0c25678143f45c2386f2111bc9bc853693"
        ),
        "holdout_initial_independent_decisions_sha256": (
            "93303d2ce6ce6737e60c6593b546c48125cb8d4023d715abd458057fbc175d85"
        ),
        "holdout_final_independent_decisions_sha256": (
            "7bbe9ebb6016bb369c194fb4c766be0c25678143f45c2386f2111bc9bc853693"
        ),
        "holdout_canonical_decisions_sha256": (
            "7bbe9ebb6016bb369c194fb4c766be0c25678143f45c2386f2111bc9bc853693"
        ),
        "holdout_sealed_labels_sha256": (
            "38b5f3f79ee9dcd4a4483f18114a6d51d0fba1f89d6ee826727336374a35ed4d"
        ),
    }:
        raise RuntimeError(f"{context} Vision reconciliation/hash drift")

    if value["population_audit"] != {
        "eligible_artifact_condition_clusters_per_split": 100,
        "all_eligible_artifact_condition_clusters_exact_polarity_pairs": True,
        "calibration": {
            "passed": False,
            "disposition_clusters": {"clean": 24, "warning": 26, "reject": 50},
            "severity3_reject_clusters": 33,
            "grain_reject_clusters": 12,
            "tiny_speck_reject_clusters": 3,
            "microblob_reject_clusters": 13,
            "spot_reject_clusters": 16,
            "short_line_reject_clusters": 22,
            "parallel_bundle_reject_clusters": 11,
            "formal_minimum_failures": ["tiny_speck_reject_detection:3<4"],
            "development_safety_floor_failures": [
                "tiny_speck_reject_detection:3<6"
            ],
        },
        "holdout": {
            "passed": False,
            "disposition_clusters": {"clean": 25, "warning": 27, "reject": 48},
            "severity3_reject_clusters": 31,
            "grain_reject_clusters": 11,
            "tiny_speck_reject_clusters": 1,
            "microblob_reject_clusters": 13,
            "spot_reject_clusters": 14,
            "short_line_reject_clusters": 23,
            "parallel_bundle_reject_clusters": 12,
            "formal_minimum_failures": ["tiny_speck_reject_detection:1<4"],
            "development_safety_floor_failures": [
                "tiny_speck_reject_detection:1<6"
            ],
        },
        "all_non_tiny_speck_formal_endpoint_minimums_passed": True,
        "all_non_tiny_speck_development_safety_floors_passed": True,
    }:
        raise RuntimeError(f"{context} population evidence drift")

    if value["hash_bindings"] != {
        "captured_repository_head": "2ad457bf67eb2fb08d3781277ea3e0a094cbac3b",
        "preregistered_spec_sha256": (
            "9de51e74c8aec518b2b9c6f08201244f06eaf3df9ceba61907efad4044ea6587"
        ),
        "implementation_bindings_sha256": (
            "ddf97277bcc8c5fcb3a3bd2b08fec9b82efab6e0d5104ca779d7e160e062ef5e"
        ),
        "dev_r7_failure_audit_sha256": (
            "00ab198c5e0be28775436d22927e9bd8523304f41e2c310d6e81c0cf2ea7131f"
        ),
        "development_boundary_sha256": (
            "0a19b23aa9137aebe7ed36ea5833593e27a1fdea4cb4b87c8529188064c3e43a"
        ),
        "generation_summary_sha256": (
            "7a6aad2ef0b2e33ba16ff93ba40f51d1566e501125263f3ff5f55603f161cf91"
        ),
        "blind_key_commitment": (
            "cc5d41fbe35e99dd9c6c111c5c4fd728777ad0c1deb66c65b83c9b42eae376ab"
        ),
        "calibration_manifest_sha256": (
            "91b349c3de58988df8a887badd56f985afaedb4ad65da50a9ee493b84dd4f2c2"
        ),
        "calibration_blank_labels_sha256": (
            "f98deb7dff75c63e7cbebef9d13cdf0454f180d5630c9089a0d309c2d43ecffe"
        ),
        "calibration_review_index_sha256": (
            "52e03a736b20493e45c6234912bdd0c7c135d9a9c833abf5be897f46fcf3cceb"
        ),
        "holdout_manifest_sha256": (
            "cb9f5b4ebeb83d7614e4c9213c09e3bf25efb68cc4a2c3cbd52bb3e155759971"
        ),
        "holdout_blank_labels_sha256": (
            "728e2330d6c686ea9616c5b27efafbcd9883e95fbac853f0e625f86e101c0257"
        ),
        "holdout_review_index_sha256": (
            "bc5492add9f9e68db34cb6f2cad1257b7a90655e2b21071681dcb9de50cc8e98"
        ),
        "label_seal_receipt_sha256": (
            "acdec32d2c99d0dd65891260e09fefa0b5375bca0e9f3115d622ea3c279fe7b4"
        ),
        "population_audit_sha256": (
            "7ce4b03e4ebc832612b8c5d972275bcf7324556e22938435d7e9e41608c26df3"
        ),
        "failure_marker_sha256": (
            "94f4b3319784d191b4972a8f6630a973ff398194120339740ded25da0fe84833"
        ),
    }:
        raise RuntimeError(f"{context} authority hash binding drift")

    if value["absent_measurement_artifacts"] != {
        "calibration_measurements_present": False,
        "holdout_measurements_present": False,
        "analysis_result_present": False,
    }:
        raise RuntimeError(f"{context} premeasurement artifact-absence drift")
    if value["root_cause"] != {
        "population_feasibility": (
            "Both splits failed only the tiny-speck-visible reject population "
            "endpoint. Every other formal population minimum and every other "
            "stricter development-only safety floor passed."
        ),
        "premature_measurement_ruled_out": (
            "The fail-close occurred before the first numeric metric call; no score, "
            "threshold candidate, selected threshold, or holdout endpoint result "
            "exists."
        ),
        "schedule_limitation": (
            "The frozen design tiers explored speck morphology but did not "
            "structurally guarantee that at least six distinct condition clusters "
            "per split would be judged both reject and tiny-speck-visible under "
            "blind Vision truth."
        ),
        "post_label_repair_forbidden": (
            "The sealed outcome cannot be repaired by relabeling, subsetting, "
            "top-up, replacement, key resampling, regeneration, or rerunning r8."
        ),
    }:
        raise RuntimeError(f"{context} root-cause drift")
    if value["successor_constraints"] != {
        "r8_data_role": "development_only_failure_evidence",
        "formal_r6_must_not_start_from_r8_failure": True,
        "successor_requires_fresh_preregistered_revision": True,
        "successor_requires_fresh_root_key_nonces_controls_identities_labels_and_measurements": True,
        "r8_key_controls_labels_pixels_identities_measurements_and_root_reuse_forbidden": True,
        "successor_must_be_committed_pushed_and_ci_green_before_generation": True,
        "formal_r6_root_and_environment_must_remain_absent": True,
        "formal_endpoint_population_and_rate_minima_must_not_be_weakened": True,
        "development_safety_floors_must_not_be_weakened": True,
    }:
        raise RuntimeError(f"{context} successor constraint drift")
    if value["secret_handling"] != {
        "blind_key_present_in_this_artifact": False,
        "blind_key_value_logged_or_tracked": False,
        "development_blind_key_persisted_in_ignored_closed_private_root": True,
        "development_blind_key_path": (
            "tmp/map-production/microtexture-v2-r6-dev-r8/private/"
            "development-key.bin"
        ),
        "development_blind_key_bytes": 32,
        "development_blind_key_bytes_disclosed_in_this_audit": False,
        "development_blind_key_reuse_forbidden": True,
        "private_labels_measurements_identities_or_pixels_tracked": False,
        "closed_temporary_artifact_root": (
            "tmp/map-production/microtexture-v2-r6-dev-r8"
        ),
    }:
        raise RuntimeError(f"{context} secret-handling drift")


def validate_dev_r9_failure_audit(value: Any) -> None:
    """Validate the sanitized, tracked dev-r9 post-measurement failure evidence."""

    context = "closed dev-r9 failure audit"
    require_exact_keys(
        value,
        {
            "artifact",
            "schema_version",
            "authority",
            "formal_use_forbidden",
            "audit_recorded_at",
            "development_edition",
            "outcome",
            "measurement_started",
            "selection_status",
            "development_hard_threshold",
            "holdout_endpoint_performance",
            "one_shot_contract",
            "vision_review",
            "population_audit",
            "threshold_failure",
            "hash_bindings",
            "measurement_artifacts",
            "root_cause",
            "successor_constraints",
            "secret_handling",
        },
        context,
    )
    parse_utc_timestamp(value["audit_recorded_at"], f"{context}.audit_recorded_at")
    if (
        value["artifact"]
        != "microtexture-v2-r6-dev-r9-development-failure-audit"
        or value["schema_version"]
        != "microtexture-v2-r6-development-failure-audit/2"
        or value["authority"] is not False
        or value["formal_use_forbidden"] is not True
        or value["development_edition"] != "r9"
        or value["outcome"] != "failed_closed"
        or value["measurement_started"] is not True
        or value["selection_status"] != "no-endpoint-admissible-threshold"
        or value["development_hard_threshold"] is not None
        or value["holdout_endpoint_performance"] is not None
    ):
        raise RuntimeError(f"{context} header/outcome drift")

    if value["one_shot_contract"] != {
        "generation_completed_exactly_once": True,
        "root_vision_completed_before_private_reveal": True,
        "independent_vision_completed_before_private_reveal": True,
        "labels_sealed_before_private_reveal": True,
        "population_audit_passed_before_measurement": True,
        "analysis_started_exactly_once": True,
        "numeric_metric_called": True,
        "threshold_search_started": True,
        "threshold_frozen": False,
        "formal_cli_invoked": False,
        "formal_marker_created": False,
        "formal_threshold_created": False,
        "locked_clean_v18_decoded_or_measured": False,
        "postmortem_invoked": False,
        "rerun_relabel_retune_subset_topup_resample_or_reuse_for_r9_forbidden": True,
        "r9_closed": True,
    }:
        raise RuntimeError(f"{context} one-shot closure drift")

    vision = value["vision_review"]
    require_exact_keys(
        vision,
        {
            "calibration_records_reviewed_by_root",
            "holdout_records_reviewed_by_root",
            "calibration_records_reviewed_independently",
            "holdout_records_reviewed_independently",
            "calibration_review_boards_reviewed_by_root",
            "holdout_review_boards_reviewed_by_root",
            "calibration_review_boards_reviewed_independently",
            "holdout_review_boards_reviewed_independently",
            "logical_comparison_fields",
            "notes_and_ev3_locators_excluded_from_logical_comparison",
            "contemporaneous_blind_comparison",
            "reproducible_final_root_vs_immutable_initial_independent",
            "root_reinspected_every_contemporaneous_logical_difference",
            "root_and_independent_logical_decisions_reconciled",
            "canonical_root_and_final_independent_bytes_identical_after_reconciliation",
            "calibration_root_decisions_sha256",
            "calibration_initial_independent_decisions_sha256",
            "calibration_final_independent_decisions_sha256",
            "calibration_canonical_decisions_sha256",
            "calibration_sealed_labels_sha256",
            "calibration_record_dispositions",
            "holdout_root_decisions_sha256",
            "holdout_initial_independent_decisions_sha256",
            "holdout_final_independent_decisions_sha256",
            "holdout_canonical_decisions_sha256",
            "holdout_sealed_labels_sha256",
            "holdout_record_dispositions",
        },
        f"{context}.vision_review",
    )
    if (
        any(
            vision[field] != 220
            for field in (
                "calibration_records_reviewed_by_root",
                "holdout_records_reviewed_by_root",
                "calibration_records_reviewed_independently",
                "holdout_records_reviewed_independently",
            )
        )
        or any(
            vision[field] != 37
            for field in (
                "calibration_review_boards_reviewed_by_root",
                "holdout_review_boards_reviewed_by_root",
                "calibration_review_boards_reviewed_independently",
                "holdout_review_boards_reviewed_independently",
            )
        )
        or vision["logical_comparison_fields"]
        != ["page", "row", "anonymous_code", "disposition", "severity", "flags"]
        or vision["notes_and_ev3_locators_excluded_from_logical_comparison"] is not True
        or vision["root_reinspected_every_contemporaneous_logical_difference"]
        is not True
        or vision["root_and_independent_logical_decisions_reconciled"] is not True
        or vision[
            "canonical_root_and_final_independent_bytes_identical_after_reconciliation"
        ]
        is not True
        or vision["calibration_record_dispositions"]
        != {"clean": 75, "warning": 51, "reject": 94}
        or vision["holdout_record_dispositions"]
        != {"clean": 71, "warning": 37, "reject": 112}
    ):
        raise RuntimeError(f"{context} Vision review cardinality/closure drift")
    contemporaneous = vision["contemporaneous_blind_comparison"]
    require_exact_keys(
        contemporaneous,
        {
            "calibration_logical_difference_count_recorded_before_reconciliation",
            "holdout_logical_difference_count_recorded_before_reconciliation",
            "initial_root_snapshot_persisted_immutably",
            "interpretation",
        },
        f"{context}.vision_review.contemporaneous_blind_comparison",
    )
    if (
        contemporaneous.get(
            "calibration_logical_difference_count_recorded_before_reconciliation"
        )
        != 47
        or contemporaneous.get(
            "holdout_logical_difference_count_recorded_before_reconciliation"
        )
        != 60
        or contemporaneous.get("initial_root_snapshot_persisted_immutably") is not False
    ):
        raise RuntimeError(f"{context} contemporaneous Vision comparison drift")
    reproducible = vision[
        "reproducible_final_root_vs_immutable_initial_independent"
    ]
    require_exact_keys(
        reproducible,
        {
            "calibration_logical_difference_count",
            "calibration_difference_breakdown",
            "holdout_logical_difference_count",
            "holdout_difference_breakdown",
            "interpretation",
        },
        f"{context}.vision_review.reproducible_comparison",
    )
    require_exact_keys(
        reproducible["calibration_difference_breakdown"],
        {"identity", "disposition", "severity", "flags"},
        f"{context}.vision_review.calibration_difference_breakdown",
    )
    require_exact_keys(
        reproducible["holdout_difference_breakdown"],
        {"identity", "disposition", "severity", "flags"},
        f"{context}.vision_review.holdout_difference_breakdown",
    )
    if (
        reproducible.get("calibration_logical_difference_count") != 63
        or reproducible.get("calibration_difference_breakdown")
        != {"identity": 0, "disposition": 21, "severity": 39, "flags": 38}
        or reproducible.get("holdout_logical_difference_count") != 69
        or reproducible.get("holdout_difference_breakdown")
        != {"identity": 0, "disposition": 23, "severity": 54, "flags": 35}
    ):
        raise RuntimeError(f"{context} reproducible Vision comparison drift")
    expected_vision_hashes = {
        "calibration_root_decisions_sha256": "4530db591b601d27c9ca486f91f635bd79af0a27baceee46b4de64f7d0995fd5",
        "calibration_initial_independent_decisions_sha256": "df9c2b26861c781652fbb720d01eea01b4bea1f23543ffa1e859902dc104f7fb",
        "calibration_final_independent_decisions_sha256": "4530db591b601d27c9ca486f91f635bd79af0a27baceee46b4de64f7d0995fd5",
        "calibration_canonical_decisions_sha256": "4530db591b601d27c9ca486f91f635bd79af0a27baceee46b4de64f7d0995fd5",
        "calibration_sealed_labels_sha256": "0e93ae0760d1581774d3e6bc5dc849a183c856faac3562d24143b08295976e87",
        "holdout_root_decisions_sha256": "61d1edac14007d116df1abe5d7051917b88677496b2b750d70aabc653175d2a5",
        "holdout_initial_independent_decisions_sha256": "52413e0afa2084c1256a5f892426dc8c0be256de99e85393cd7d66183a213502",
        "holdout_final_independent_decisions_sha256": "61d1edac14007d116df1abe5d7051917b88677496b2b750d70aabc653175d2a5",
        "holdout_canonical_decisions_sha256": "61d1edac14007d116df1abe5d7051917b88677496b2b750d70aabc653175d2a5",
        "holdout_sealed_labels_sha256": "56163027b7bfb303a15e5676b2f648d21a0c42797f1e7cc9af9a33179adbcb3a",
    }
    if any(vision.get(field) != expected for field, expected in expected_vision_hashes.items()):
        raise RuntimeError(f"{context} Vision hash binding drift")

    population = value["population_audit"]
    require_exact_keys(
        population,
        {
            "eligible_artifact_condition_clusters_per_split",
            "all_eligible_artifact_condition_clusters_exact_polarity_pairs",
            "all_formal_endpoint_population_minimums_passed",
            "all_development_safety_floors_passed",
            "calibration",
            "holdout",
        },
        f"{context}.population_audit",
    )
    if (
        population.get("eligible_artifact_condition_clusters_per_split") != 100
        or population.get("all_eligible_artifact_condition_clusters_exact_polarity_pairs")
        is not True
        or population.get("all_formal_endpoint_population_minimums_passed") is not True
        or population.get("all_development_safety_floors_passed") is not True
    ):
        raise RuntimeError(f"{context} population header drift")
    expected_population = {
        "calibration": {
            "disposition_clusters": {"clean": 27, "warning": 18, "reject": 55},
            "counts": [27, 18, 55, 26, 12, 11, 11, 22, 21, 11],
        },
        "holdout": {
            "disposition_clusters": {"clean": 25, "warning": 16, "reject": 59},
            "counts": [25, 16, 59, 16, 13, 13, 12, 25, 21, 10],
        },
    }
    floors = [19, 13, 38, 6, 10, 6, 6, 10, 10, 8]
    for split, expected in expected_population.items():
        split_value = population.get(split, {})
        require_exact_keys(
            split_value,
            {"passed", "disposition_clusters", "endpoints"},
            f"{context}.population_audit.{split}",
        )
        require_exact_keys(
            split_value["disposition_clusters"],
            {"clean", "warning", "reject"},
            f"{context}.population_audit.{split}.disposition_clusters",
        )
        require_exact_keys(
            split_value["endpoints"],
            set(EXPECTED_ENDPOINT_IDS),
            f"{context}.population_audit.{split}.endpoints",
        )
        for endpoint in EXPECTED_ENDPOINT_IDS:
            require_exact_keys(
                split_value["endpoints"][endpoint],
                {"clusters", "development_floor"},
                f"{context}.population_audit.{split}.endpoints.{endpoint}",
            )
        if (
            split_value.get("passed") is not True
            or split_value.get("disposition_clusters") != expected["disposition_clusters"]
            or list(split_value.get("endpoints", {})) != EXPECTED_ENDPOINT_IDS
            or [
                split_value["endpoints"][endpoint]["clusters"]
                for endpoint in EXPECTED_ENDPOINT_IDS
            ]
            != expected["counts"]
            or [
                split_value["endpoints"][endpoint]["development_floor"]
                for endpoint in EXPECTED_ENDPOINT_IDS
            ]
            != floors
        ):
            raise RuntimeError(f"{context} population evidence drift: {split}")

    threshold = value["threshold_failure"]
    require_exact_keys(
        threshold,
        {
            "candidate_count",
            "endpoint_admissible_candidate_count",
            "diagnostic_candidate_count",
            "diagnostic_best_threshold",
            "diagnostic_best_endpoint_rates",
            "minimal_impossibility",
            "holdout_interpretation",
        },
        f"{context}.threshold_failure",
    )
    require_exact_keys(
        threshold["diagnostic_best_endpoint_rates"],
        set(EXPECTED_ENDPOINT_IDS),
        f"{context}.threshold_failure.diagnostic_best_endpoint_rates",
    )
    require_exact_keys(
        threshold["minimal_impossibility"],
        {
            "highest_threshold_preserving_severity3_rate_1",
            "warning_acceptance_at_that_threshold",
            "first_candidate_reaching_warning_rate_0_75",
            "severity3_at_that_candidate",
            "conclusion",
        },
        f"{context}.threshold_failure.minimal_impossibility",
    )
    require_exact_keys(
        threshold["minimal_impossibility"]["warning_acceptance_at_that_threshold"],
        {"accepted", "eligible", "rate"},
        f"{context}.threshold_failure.warning_at_severity3_boundary",
    )
    require_exact_keys(
        threshold["minimal_impossibility"]["severity3_at_that_candidate"],
        {"detected", "eligible", "rate"},
        f"{context}.threshold_failure.severity3_at_warning_boundary",
    )
    if (
        threshold.get("candidate_count") != 69
        or threshold.get("endpoint_admissible_candidate_count") != 0
        or threshold.get("diagnostic_candidate_count") != 44
        or threshold.get("diagnostic_best_threshold") != 0.7661276645021775
        or threshold.get("diagnostic_best_endpoint_rates", {})
        .get("severity3_detection")
        != {
            "rate": 0.9615384615384616,
            "minimum": 1.0,
            "passed": False,
            "detected_clusters": 25,
            "eligible_clusters": 26,
        }
        or threshold.get("minimal_impossibility", {}).get(
            "highest_threshold_preserving_severity3_rate_1"
        )
        != 0.6194246388563148
        or threshold.get("minimal_impossibility", {})
        .get("warning_acceptance_at_that_threshold")
        != {"accepted": 12, "eligible": 18, "rate": 0.6666666666666666}
        or threshold.get("minimal_impossibility", {}).get(
            "first_candidate_reaching_warning_rate_0_75"
        )
        != 0.7661276645021775
        or threshold.get("minimal_impossibility", {}).get(
            "severity3_at_that_candidate"
        )
        != {"detected": 25, "eligible": 26, "rate": 0.9615384615384616}
        or threshold["minimal_impossibility"]["conclusion"]
        != "No scalar threshold can simultaneously satisfy calibration warning "
        "acceptance >= 0.75 and severity-3 detection = 1.0."
        or threshold["holdout_interpretation"]
        != "Holdout records were measured as part of the one-shot analysis, but "
        "holdout endpoint performance was not evaluated because calibration "
        "selected no endpoint-admissible threshold."
    ):
        raise RuntimeError(f"{context} threshold impossibility drift")
    endpoint_rates = threshold["diagnostic_best_endpoint_rates"]
    expected_rates = {
        "clean_acceptance": (1.0, 0.95, True),
        "warning_acceptance": (0.7777777777777778, 0.75, True),
        "reject_detection": (0.9818181818181818, 0.95, True),
        "grain_reject_detection": (0.9166666666666666, 0.8, True),
        "tiny_speck_reject_detection": (1.0, 0.75, True),
        "microblob_reject_detection": (1.0, 0.75, True),
        "spot_reject_detection": (1.0, 0.8, True),
        "short_line_reject_detection": (1.0, 0.8, True),
        "parallel_bundle_reject_detection": (1.0, 0.8, True),
    }
    if set(endpoint_rates) != set(EXPECTED_ENDPOINT_IDS):
        raise RuntimeError(f"{context} diagnostic endpoint set drift")
    require_exact_keys(
        endpoint_rates["severity3_detection"],
        {"rate", "minimum", "passed", "detected_clusters", "eligible_clusters"},
        f"{context}.threshold_failure.severity3_detection",
    )
    for endpoint, (rate, minimum, passed) in expected_rates.items():
        require_exact_keys(
            endpoint_rates[endpoint],
            {"rate", "minimum", "passed"},
            f"{context}.threshold_failure.{endpoint}",
        )
        if endpoint_rates[endpoint] != {
            "rate": rate,
            "minimum": minimum,
            "passed": passed,
        }:
            raise RuntimeError(f"{context} diagnostic endpoint drift: {endpoint}")

    expected_bindings = {
        "captured_repository_head": "9b3b8bb6154f3e13c5e734229f06690e9ab1f740",
        "preregistered_spec_sha256": "290b59349b813935d3e04a8df67cb4b469929b53a993f84e15e9e087b2bc62b1",
        "implementation_bindings_sha256": "d4a381c995ca972f7c01a82650ae4397f9494f497e391ce5f7f4772ee4cfe795",
        "dev_r8_failure_audit_sha256": "39c7472f8018cbbf25cbd029cb915c43696a07b6c52e8e586e02fe5a99dbc07d",
        "development_boundary_sha256": "f093bd41c3f5b00722ceb701e6106f2ecf4942e45764f5d753e446fe424691a0",
        "generation_summary_sha256": "412793d5952ab884973d632018f96d9848c4a1af242677a80ddadb3ce0661436",
        "blind_key_commitment": "9c2d6e3829fd6e243415fcf3c1ecb5388eab3d2e6c8433f102a8ba6edeea425b",
        "calibration_manifest_sha256": "1c0d795ba838b234d085424c8c922e8fe9767bf3cb84d395a9713a54ef40ad3f",
        "calibration_blank_labels_sha256": "f615b119816706d3810366f78173404693c017a6dbb0de4ad32683386437ffd5",
        "calibration_review_index_sha256": "52d0f598ee09d21435d94670054df1b4d0b061e286e2fefc8e425460b68f813c",
        "holdout_manifest_sha256": "e37dc376bc856c7ba16c9b332808105d15ec790e287220c88a017104ffe801ca",
        "holdout_blank_labels_sha256": "1ca556053cdd426c032f333e8c33f6ebebeedc0a3238a828e24b50895b915b90",
        "holdout_review_index_sha256": "c8b5a8205544fa173e71e01197dc6255a49dbc6049dd4bb8c49ed790dac00d36",
        "label_seal_receipt_sha256": "6361be6009c437c0a82ee25c5e88108588c8aef44fea8aa3e9c26edb9fa65713",
        "population_audit_sha256": "a6b59ed95d34e826a6aaca00149ce4c19fdb9a4822d74619faed0f33a04e46bf",
        "calibration_measurements_sha256": "0db0705653d5c851074bb2221032c5d462235d17e4e29a185f44bd022e984803",
        "holdout_measurements_sha256": "6f0887312bbb63c81d691583ab4c85502a8dab288cc0cb6b59b208455d7ff944",
        "analysis_result_sha256": "3052bff4871e371688adf6f477ca103812b1fab423372dee5af1095f7f95ee0b",
        "failure_marker_sha256": "ab3a9259d5e2324b135cde88dcc4a3719a973101f81493b10a06afccb5829bd5",
    }
    if value["hash_bindings"] != expected_bindings:
        raise RuntimeError(f"{context} authority hash binding drift")
    if value["measurement_artifacts"] != {
        "calibration_measurements_present": True,
        "holdout_measurements_present": True,
        "analysis_result_present": True,
        "failure_marker_present": True,
        "holdout_endpoint_result_present": False,
    }:
        raise RuntimeError(f"{context} measurement artifact-state drift")

    if value["root_cause"] != {
        "population_feasibility": "Both splits passed every formal population minimum and every stricter development-only safety floor; population was not the cause.",
        "threshold_impossibility": "The calibration warning-acceptance and severity-3-detection constraints occupy disjoint scalar-threshold ranges under the frozen metric.",
        "single_limiting_endpoint": "At the diagnostic-best candidate every endpoint except severity-3 detection passed; severity-3 detected 25 of 26 clusters where 26 of 26 was required.",
        "generic_failure_message_clarification": "The runner's message mentions calibration and holdout generically. The evidence shows calibration selected no threshold; holdout endpoint performance was therefore not evaluated, rather than evaluated and failed.",
        "post_label_repair_forbidden": "The sealed outcome cannot be repaired by relabeling, subsetting, top-up, replacement, key resampling, regeneration, retuning, or rerunning r9.",
    }:
        raise RuntimeError(f"{context} root-cause drift")

    successor = value["successor_constraints"]
    if successor != {
        "r9_data_role": "development_only_failure_evidence",
        "formal_r6_must_not_start_from_r9_failure": True,
        "successor_requires_fresh_preregistered_revision": True,
        "successor_requires_fresh_root_key_nonces_controls_identities_labels_and_measurements": True,
        "r9_key_controls_labels_pixels_identities_measurements_threshold_diagnostics_nonces_commitments_and_root_reuse_forbidden": True,
        "successor_must_be_committed_pushed_and_ci_green_before_generation": True,
        "formal_r6_root_and_environment_must_remain_absent": True,
        "formal_endpoint_population_and_rate_minima_must_not_be_weakened": True,
        "development_safety_floors_must_not_be_weakened": True,
        "diagnostic_threshold_must_not_be_promoted_or_reused": True,
        "holdout_measurements_must_not_be_examined_reused_or_tuned_against": True,
    }:
        raise RuntimeError(f"{context} successor constraint drift")
    secret = value["secret_handling"]
    if secret != {
        "blind_key_present_in_this_artifact": False,
        "blind_key_value_logged_or_tracked": False,
        "development_blind_key_persisted_in_ignored_closed_private_root": True,
        "development_blind_key_path": "tmp/map-production/microtexture-v2-r6-dev-r9/private/development-key.bin",
        "development_blind_key_bytes": 32,
        "development_blind_key_bytes_disclosed_in_this_audit": False,
        "development_blind_key_reuse_forbidden": True,
        "private_labels_measurements_identities_or_pixels_tracked": False,
        "postmortem_raw_output_tracked": False,
        "closed_temporary_artifact_root": "tmp/map-production/microtexture-v2-r6-dev-r9",
    }:
        raise RuntimeError(f"{context} secret-handling drift")


def validate_dev_r10_generation_failure_audit(value: Any) -> None:
    """Validate the sanitized tracked dev-r10 generation-interruption evidence."""

    context = "closed dev-r10 generation-interruption audit"
    require_exact_keys(
        value,
        {
            "artifact",
            "schema_version",
            "authority",
            "formal_use_forbidden",
            "audit_recorded_at",
            "development_edition",
            "outcome",
            "failure_phase",
            "failure_class",
            "process_exit_code",
            "termination_cause_inferred",
            "operator_observation",
            "measurement_started",
            "development_hard_threshold",
            "holdout_endpoint_performance",
            "one_shot_contract",
            "observed_public_state",
            "captured_generation_binding",
            "successor_constraints",
            "secret_handling",
        },
        context,
    )
    parse_utc_timestamp(value["audit_recorded_at"], f"{context}.audit_recorded_at")
    if (
        value["artifact"]
        != "microtexture-v2-r6-dev-r10-development-generation-interruption-audit"
        or value["schema_version"]
        != "microtexture-v2-r6-development-generation-interruption-audit/1"
        or value["authority"] is not False
        or value["formal_use_forbidden"] is not True
        or value["development_edition"] != "r10"
        or value["outcome"] != "failed_closed"
        or value["failure_phase"] != "generation"
        or value["failure_class"]
        != "unknown-process-termination-after-monitor-loss"
        or value["process_exit_code"] is not None
        or value["termination_cause_inferred"] is not False
        or value["operator_observation"]
        != "The execution-monitor session became unavailable; a subsequent "
        "operating-system process scan found no matching development_probe.py "
        "generate process. The terminal generation summary, seal, and completion "
        "artifacts were absent."
        or value["measurement_started"] is not False
        or value["development_hard_threshold"] is not None
        or value["holdout_endpoint_performance"] is not None
    ):
        raise RuntimeError(f"{context} header/outcome drift")
    if value["one_shot_contract"] != {
        "generation_invocation_started_exactly_once": True,
        "fresh_key_sampling_started_exactly_once": True,
        "development_root_created": True,
        "generation_completed": False,
        "root_vision_started": False,
        "independent_vision_started": False,
        "labels_sealed": False,
        "private_reveal_started": False,
        "preflight_invoked": False,
        "analysis_started": False,
        "numeric_metric_called": False,
        "threshold_search_started": False,
        "threshold_frozen": False,
        "postmortem_invoked": False,
        "formal_cli_invoked": False,
        "formal_marker_created": False,
        "formal_threshold_created": False,
        "locked_clean_v18_decoded_or_measured": False,
        "rerun_resume_topup_relabel_key_resampling_or_reuse_for_r10_forbidden": True,
        "closed_root_retained_unchanged": True,
        "r10_closed": True,
    }:
        raise RuntimeError(f"{context} one-shot contract drift")
    observed = value["observed_public_state"]
    require_exact_keys(
        observed,
        {
            "closed_development_root",
            "development_boundary_present",
            "development_boundary_last_write_utc",
            "development_boundary_sha256",
            "generation_summary_present",
            "generation_seal_present",
            "generation_completion_present",
            "completed_public_splits",
            "missing_public_splits",
            "calibration_records",
            "calibration_contact_sheet_pngs",
            "calibration_review_board_pngs",
            "holdout_records",
            "holdout_contact_sheet_pngs",
            "holdout_review_board_pngs",
            "calibration_manifest_sha256",
            "calibration_blank_labels_sha256",
            "calibration_review_index_sha256",
            "generated_pixels_vision_reviewed_for_this_audit",
            "private_root_contents_inspected_for_this_audit",
        },
        f"{context}.observed_public_state",
    )
    parse_utc_timestamp(
        observed["development_boundary_last_write_utc"],
        f"{context}.development_boundary_last_write_utc",
    )
    if observed != {
        "closed_development_root": "tmp/map-production/microtexture-v2-r6-dev-r10",
        "development_boundary_present": True,
        "development_boundary_last_write_utc": "2026-07-29T02:07:56.7630737Z",
        "development_boundary_sha256": "e0ddba922a9f2d02e2af43397674860b4e8fb5f85a705f9f304a70c20f4da07b",
        "generation_summary_present": False,
        "generation_seal_present": False,
        "generation_completion_present": False,
        "completed_public_splits": ["calibration"],
        "missing_public_splits": ["holdout"],
        "calibration_records": 220,
        "calibration_contact_sheet_pngs": 185,
        "calibration_review_board_pngs": 37,
        "holdout_records": 0,
        "holdout_contact_sheet_pngs": 0,
        "holdout_review_board_pngs": 0,
        "calibration_manifest_sha256": "54d665b91a15ae950adb80d93f8471d17a9d8d9b247c2a6c79921b43ac4d8b94",
        "calibration_blank_labels_sha256": "e8e462ab06b85216139d2bf61ad434b1b46669b65473df00b3e2357bfa5c996a",
        "calibration_review_index_sha256": "8d6d3876eb86b6782e26ccc77829e39da519bf0903e8e8ce3c39e698a0d8be0d",
        "generated_pixels_vision_reviewed_for_this_audit": False,
        "private_root_contents_inspected_for_this_audit": False,
    }:
        raise RuntimeError(f"{context} observed public state drift")
    if value["captured_generation_binding"] != {
        "captured_repository_head": "80a7c2f41b77edc56e19ad0880c4352a8aea2d18",
        "preregistered_spec_sha256": "d5c370a7f87d334a261d197adfd6e1929801436d7b4247affb766a5a5ef162f6",
        "implementation_bindings_sha256": "e920acd8fd56559cc90bad43e9c80f667d5daffa445f22a341f9a54c4f4db750",
        "development_runner_sha256": "23d82f9fe467f2682ea32397d195686113bfa292c2086652201622d524e69d53",
        "blind_key_commitment": "8f2e2e235376fa35a308043448f783374ad526292178a08772cd513c3b45e9fd",
        "public_nonces": {
            "calibration": "r6-calibration-v5",
            "holdout": "r6-holdout-v5",
        },
        "runtime_fingerprint_sha256": "6e29f4219eb5e13085ab992894f57095b5e5802dc549f96fe628c353d8503e2d",
    }:
        raise RuntimeError(f"{context} captured binding drift")
    if value["successor_constraints"] != {
        "r10_data_role": "development_only_generation_interruption_evidence",
        "formal_r6_must_not_start_from_r10_failure": True,
        "successor_requires_fresh_preregistered_revision": True,
        "successor_requires_fresh_root_key_public_nonces_hmac_domains_parameter_nonces_controls_references_identities_codes_commitments_labels_and_measurements": True,
        "r10_root_key_controls_references_pixels_identities_codes_commitments_labels_measurements_nonces_and_partial_public_surfaces_reuse_forbidden": True,
        "r10_public_pixels_labels_or_outputs_must_not_be_used_for_successor_tuning": True,
        "unchanged_preregistered_morphology_metric_threshold_population_and_rate_contract_required": True,
        "successor_authority_must_be_committed_pushed_and_dual_ci_green_before_generation": True,
        "formal_r6_root_and_environment_must_remain_absent": True,
    }:
        raise RuntimeError(f"{context} successor constraint drift")
    if value["secret_handling"] != {
        "blind_key_present_in_this_artifact": False,
        "blind_key_value_logged_or_tracked": False,
        "blind_key_bytes_or_private_identity_inspected_for_this_audit": False,
        "private_labels_measurements_identities_or_pixels_tracked": False,
        "development_blind_key_and_private_material_reuse_forbidden": True,
        "closed_temporary_artifact_root": "tmp/map-production/microtexture-v2-r6-dev-r10",
    }:
        raise RuntimeError(f"{context} secret-handling drift")


def validate_dev_r11_premeasurement_failure_audit(value: Any) -> None:
    """Validate sanitized, closed dev-r11 premeasurement Vision-gate evidence."""

    context = "closed dev-r11 premeasurement failure audit"
    require_exact_keys(
        value,
        {
            "artifact",
            "schema_version",
            "authority",
            "formal_use_forbidden",
            "audit_recorded_at",
            "development_edition",
            "outcome",
            "failure_phase",
            "failure_class",
            "measurement_started",
            "development_hard_threshold",
            "holdout_endpoint_performance",
            "one_shot_contract",
            "vision_review",
            "private_audit_failure",
            "measurement_artifacts",
            "hash_bindings",
            "root_cause",
            "successor_constraints",
            "secret_handling",
        },
        context,
    )
    timestamp = value["audit_recorded_at"]
    if not isinstance(timestamp, str) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z", timestamp
    ) is None:
        raise RuntimeError(f"{context}.audit_recorded_at must be canonical UTC text")
    parse_utc_timestamp(timestamp, f"{context}.audit_recorded_at")
    expected_header = {
        "artifact": "microtexture-v2-r6-dev-r11-development-premeasurement-failure-audit",
        "schema_version": "microtexture-v2-r6-development-premeasurement-failure-audit/1",
        "authority": False,
        "formal_use_forbidden": True,
        "development_edition": "r11",
        "outcome": "failed_closed",
        "failure_phase": "private-sentinel-audit-before-population-audit",
        "failure_class": "sealed-vision-false-positive-on-protocol-zero-sentinel",
        "measurement_started": False,
        "development_hard_threshold": None,
        "holdout_endpoint_performance": None,
    }
    for field, expected in expected_header.items():
        _require_exact_json_value(value[field], expected, f"{context}.{field}")

    _require_exact_json_value(
        value["one_shot_contract"],
        {
            "generation_completed_exactly_once": True,
            "root_vision_completed_before_private_reveal": True,
            "independent_vision_completed_before_private_reveal": True,
            "all_440_records_reviewed_by_each_reviewer": True,
            "root_and_independent_decisions_reconciled_before_preflight": True,
            "review_preflight_invoked_exactly_once": True,
            "review_preflight_passed": True,
            "labels_sealed_before_private_reveal": True,
            "private_reveal_started_after_label_seal": True,
            "private_sentinel_audit_passed": False,
            "population_audit_started": False,
            "population_audit_passed": False,
            "analysis_started_exactly_once": True,
            "numeric_metric_called": False,
            "threshold_search_started": False,
            "threshold_frozen": False,
            "postmortem_invoked": False,
            "formal_cli_invoked": False,
            "formal_marker_created": False,
            "formal_threshold_created": False,
            "locked_clean_v18_decoded_or_measured": False,
            "rerun_resume_relabel_retune_subset_topup_resample_or_reuse_for_r11_forbidden": True,
            "r11_closed": True,
        },
        f"{context}.one_shot_contract",
    )

    vision = value["vision_review"]
    _require_exact_json_value(
        vision,
        {
            "calibration_records_reviewed_by_root": 220,
            "holdout_records_reviewed_by_root": 220,
            "calibration_records_reviewed_independently": 220,
            "holdout_records_reviewed_independently": 220,
            "calibration_review_boards_reviewed_by_root": 37,
            "holdout_review_boards_reviewed_by_root": 37,
            "calibration_review_boards_reviewed_independently": 37,
            "holdout_review_boards_reviewed_independently": 37,
            "logical_comparison_fields": [
                "page",
                "row",
                "anonymous_code",
                "disposition",
                "severity",
                "flags",
            ],
            "notes_and_ev3_locators_excluded_from_initial_logical_comparison": True,
            "contemporaneous_blind_difference_counts_before_reconciliation": {
                "calibration": 66,
                "holdout": 88,
                "initial_root_snapshot_persisted_immutably": False,
            },
            "reproducible_final_root_vs_immutable_initial_independent": {
                "calibration_logical_difference_count": 66,
                "calibration_difference_breakdown": {
                    "identity": 0,
                    "disposition": 19,
                    "severity": 64,
                    "flags": 12,
                },
                "holdout_logical_difference_count": 84,
                "holdout_difference_breakdown": {
                    "identity": 0,
                    "disposition": 22,
                    "severity": 80,
                    "flags": 15,
                },
            },
            "root_reinspected_every_contemporaneous_logical_difference": True,
            "root_and_independent_logical_decisions_reconciled": True,
            "canonical_root_and_final_independent_bytes_identical_after_reconciliation": True,
            "calibration_root_decisions_sha256": "e293eb3432c61d787017bdb1e7852fe9225439cace89d494712b1e7ed37151df",
            "calibration_initial_independent_decisions_sha256": "89df8c754382d253fbd7000a41a53f8090e64ec929d3f3f8d15b26eab33c65f4",
            "calibration_final_independent_decisions_sha256": "e293eb3432c61d787017bdb1e7852fe9225439cace89d494712b1e7ed37151df",
            "calibration_canonical_decisions_sha256": "e293eb3432c61d787017bdb1e7852fe9225439cace89d494712b1e7ed37151df",
            "calibration_completed_labels_sha256": "f803c5bc02b1e657451ec8a2208fc0efc8ff06e68bf9aef03c3ae8f74cb175e8",
            "calibration_record_dispositions": {
                "clean": 80,
                "warning": 27,
                "reject": 113,
            },
            "holdout_root_decisions_sha256": "e85329b7d16bd4954df38dcd5d6315cc4ecb98ce20de95510c4215f69d2e50ca",
            "holdout_initial_independent_decisions_sha256": "99e993c901d17679d7049a8bcda8a937687b2480ebec10dc112f2b8e14824e22",
            "holdout_final_independent_decisions_sha256": "e85329b7d16bd4954df38dcd5d6315cc4ecb98ce20de95510c4215f69d2e50ca",
            "holdout_canonical_decisions_sha256": "e85329b7d16bd4954df38dcd5d6315cc4ecb98ce20de95510c4215f69d2e50ca",
            "holdout_completed_labels_sha256": "4162b170e2dd6bf2d30fb1052b32988f3f58eb67d19ee923fac436d640c62937",
            "holdout_record_dispositions": {
                "clean": 78,
                "warning": 16,
                "reject": 126,
            },
        },
        f"{context}.vision_review",
    )
    vision_hash_fields = {
        field for field in vision if field.endswith("_sha256")
    }
    if vision_hash_fields != {
        "calibration_root_decisions_sha256",
        "calibration_initial_independent_decisions_sha256",
        "calibration_final_independent_decisions_sha256",
        "calibration_canonical_decisions_sha256",
        "calibration_completed_labels_sha256",
        "holdout_root_decisions_sha256",
        "holdout_initial_independent_decisions_sha256",
        "holdout_final_independent_decisions_sha256",
        "holdout_canonical_decisions_sha256",
        "holdout_completed_labels_sha256",
    } or any(
        re.fullmatch(r"[0-9a-f]{64}", vision[field]) is None
        for field in vision_hash_fields
    ):
        raise RuntimeError(f"{context}.vision_review SHA-256 binding drift")
    for split in ("calibration", "holdout"):
        root_sha = vision[f"{split}_root_decisions_sha256"]
        if (
            root_sha != vision[f"{split}_final_independent_decisions_sha256"]
            or root_sha != vision[f"{split}_canonical_decisions_sha256"]
            or root_sha == vision[f"{split}_initial_independent_decisions_sha256"]
        ):
            raise RuntimeError(f"{context}.{split} reconciliation hash drift")

    _require_exact_json_value(
        value["private_audit_failure"],
        {
            "affected_split": "holdout",
            "affected_record_count": 1,
            "expected_private_role": "protocol-zero",
            "sealed_disposition_was_nonclean": True,
            "sealed_visible_flag_included_tiny_speck": True,
            "anonymous_code_page_row_private_identity_or_pixel_binding_tracked": False,
            "interpretation": "One sealed holdout Vision decision counted extremely faint point impressions as cross-scale tiny-speck morphology. Secret regeneration then proved that record was an exact-zero protocol sentinel, so the edition failed closed before population aggregation or any numeric metric call.",
        },
        f"{context}.private_audit_failure",
    )
    _require_exact_json_value(
        value["measurement_artifacts"],
        {
            "population_audit_present": False,
            "calibration_measurements_present": False,
            "holdout_measurements_present": False,
            "analysis_result_present": False,
            "failure_marker_present": True,
        },
        f"{context}.measurement_artifacts",
    )

    bindings = value["hash_bindings"]
    _require_exact_json_value(
        bindings,
        {
            "captured_repository_head": "44cc6ec2c2d2f26784843835e63bdf90d81e2fb0",
            "preregistered_spec_sha256": "4cbfe943d0938aa0df4cbb03db253ccd169e7bf8dcf65e4ea0bbf102836fc59f",
            "implementation_bindings_sha256": "4f5ce900fcf1da857aa34b39466cf8660ec0374bedfab0702a874d7b85ef0b12",
            "development_boundary_sha256": "71b929aee554fa83b7e290c5e4445b1190b04cf08d1d44cabb2769d5505aa3e3",
            "generation_start_sha256": "4a7bde9113d6c3431347aff053f2a487e347ae2203980606e9d0d9f17ff38c06",
            "generation_summary_sha256": "75d0d8c80106a306f5492ede9a324ddb732bc9bc33d9ded4c3c97003405ad296",
            "generation_seal_sha256": "699a5e982475d35a19d711782b8bd91f965bad7a1699108cb8ee9d50cd72c785",
            "generation_completion_sha256": "a25f3a0851a0355be040a49f241bede1031d2e4e498cc66ada87797bf49edaae",
            "blind_key_commitment": "a43d64581445094b2cc550b6476280fe94498a6c11df111e58c1eef3ba248a39",
            "calibration_manifest_sha256": "7b2ad19a6cf9bdebd7168584da8526e5b238b19ca31a1ea1d3fd914fbd9690f5",
            "calibration_blank_labels_sha256": "e7665cc2faa43c1af9a9b947aa10cf7edcc618c0eafc199167ccbe00e73ec8b5",
            "calibration_review_index_sha256": "704c30f698eead31ec573181261ffa82b2fc48f3480ae064e79d6700a915f1a9",
            "holdout_manifest_sha256": "92567c207fa3ea58d48dfd96d4074634cb6b4a7d35d25b4bda0197b4e8660939",
            "holdout_blank_labels_sha256": "b2980977351a4dc451b6c1c41ee1e989b048e41aa53a1027b2e272c6ceee989b",
            "holdout_review_index_sha256": "63292a039d16fc7d64aef8ddfbe4bff51132c27f40bdc6ee98f882b95db05177",
            "label_seal_receipt_sha256": "488a4fd3507e6ba721d6ae70f1851305952caa96db274b1e2f3da6cac2ae4f5a",
            "failure_marker_sha256": "83e135ebee60748b08687ec8037568ced1d5f92cf812030209f1388fba077154",
        },
        f"{context}.hash_bindings",
    )
    if re.fullmatch(r"[0-9a-f]{40}", bindings["captured_repository_head"]) is None:
        raise RuntimeError(f"{context} captured repository HEAD drift")
    for field, digest in bindings.items():
        if field == "captured_repository_head":
            continue
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise RuntimeError(f"{context}.{field} must be lowercase SHA-like hex")

    _require_exact_json_value(
        value["root_cause"],
        {
            "generation_or_runtime_failure": False,
            "decision_reconciliation_failure": False,
            "population_or_metric_failure_evaluated": False,
            "vision_gate_failure": "A private exact-zero sentinel received a sealed nonclean label because extremely faint 400-percent point impressions were over-counted as morphology despite the preregistered requirement that each core be directly visible without enhancement in full-200.",
            "post_label_repair_forbidden": "The sealed dev-r11 outcome cannot be repaired by relabeling, rerunning, resuming, replacing, subsetting, topping up, resampling the key, or reusing any dev-r11 control or decision.",
        },
        f"{context}.root_cause",
    )
    _require_exact_json_value(
        value["successor_constraints"],
        {
            "r11_data_role": "development_only_premeasurement_vision_gate_failure_evidence",
            "formal_r6_must_not_start_from_r11_failure": True,
            "successor_requires_fresh_preregistered_revision": True,
            "successor_requires_fresh_root_key_public_nonces_hmac_domains_parameter_nonces_controls_references_identities_codes_commitments_labels_and_measurements": True,
            "r11_root_key_controls_references_pixels_identities_codes_commitments_labels_measurements_nonces_and_public_surfaces_reuse_forbidden": True,
            "unchanged_preregistered_morphology_metric_threshold_population_and_rate_contract_required": True,
            "full_200_direct_visibility_gate_must_be_applied_without_enhancement_or_400_only_inference": True,
            "successor_authority_must_be_committed_pushed_and_dual_ci_green_before_generation": True,
            "formal_r6_root_and_environment_must_remain_absent": True,
        },
        f"{context}.successor_constraints",
    )
    _require_exact_json_value(
        value["secret_handling"],
        {
            "blind_key_present_in_this_artifact": False,
            "blind_key_value_logged_or_tracked": False,
            "anonymous_code_to_private_identity_mapping_tracked": False,
            "private_labels_identities_or_pixels_tracked": False,
            "postmortem_invoked": False,
            "development_blind_key_and_private_material_reuse_forbidden": True,
            "closed_temporary_artifact_root": "tmp/map-production/microtexture-v2-r6-dev-r11",
        },
        f"{context}.secret_handling",
    )


def validate_dev_r12_premeasurement_population_failure_audit(value: Any) -> None:
    """Validate the exact sanitized dev-r12 population-gate failure evidence."""

    context = "closed dev-r12 premeasurement population failure audit"
    require_exact_keys(
        value,
        {
            "artifact",
            "schema_version",
            "authority",
            "formal_use_forbidden",
            "audit_recorded_at",
            "development_edition",
            "outcome",
            "failure_phase",
            "failure_class",
            "measurement_started",
            "selection_status",
            "development_hard_threshold",
            "calibration_endpoint_performance",
            "holdout_endpoint_performance",
            "threshold_selection_audit",
            "one_shot_contract",
            "vision_review",
            "private_audit",
            "population_audit",
            "failure_marker_summary",
            "hash_bindings",
            "absent_measurement_artifacts",
            "postmortem",
            "root_cause",
            "successor_constraints",
            "secret_handling",
        },
        context,
    )
    timestamp = value["audit_recorded_at"]
    if not isinstance(timestamp, str) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z", timestamp
    ) is None:
        raise RuntimeError(f"{context}.audit_recorded_at must be canonical UTC text")
    parse_utc_timestamp(timestamp, f"{context}.audit_recorded_at")
    expected_header = {
        "artifact": "microtexture-v2-r6-dev-r12-development-premeasurement-population-failure-audit",
        "schema_version": "microtexture-v2-r6-development-premeasurement-population-failure-audit/1",
        "authority": False,
        "formal_use_forbidden": True,
        "development_edition": "r12",
        "outcome": "failed_closed",
        "failure_phase": "private-audits-passed-then-premeasurement-population-audit",
        "failure_class": "warning-cluster-population-shortfall",
        "measurement_started": False,
        "selection_status": "not_started_population_gate_failed",
        "development_hard_threshold": None,
        "calibration_endpoint_performance": None,
        "holdout_endpoint_performance": None,
        "threshold_selection_audit": None,
    }
    for field, expected in expected_header.items():
        _require_exact_json_value(value[field], expected, f"{context}.{field}")

    # This semantic digest is over canonical JSON, independently of formatting. It
    # makes every nested key, type, ordering, count, claim, and historical hash an
    # exact closed-edition contract while the tracked-history check separately binds
    # the pretty-printed file bytes.
    if sha256_bytes(canonical_json_bytes(value)) != (
        "5f5e6b301145837bdb0ad9358ba59a0c630eb4649b126a591918048f03744ebb"
    ):
        raise RuntimeError(f"{context} canonical semantic digest drift")

    vision = value["vision_review"]
    if (
        vision["records_per_split_per_reviewer"] != 220
        or vision["review_boards_per_split_per_reviewer"] != 37
        or vision["logical_comparison_fields"]
        != ["page", "row", "anonymous_code", "disposition", "severity", "flags"]
        or vision["evidence_notes_excluded_from_logical_comparison"] is not True
        or vision["initial_snapshots_persisted_immutably"] is not True
        or vision["all_differences_reinspected_native_then_evidence"] is not True
        or vision["final_reconciled"] is not True
        or vision["canonical_labels_equal_both_reviewers"] is not True
    ):
        raise RuntimeError(f"{context} Vision review contract drift")
    for split, initial_difference_count in (("calibration", 30), ("holdout", 44)):
        review = vision["splits"][split]
        if (
            review["initial_exact_logical_agreement"] is not False
            or review["initial_logical_difference_count"] != initial_difference_count
            or review["all_differences_reinspected_native_then_evidence"] is not True
            or review["reconciled"] is not True
            or review["root_initial_decisions_sha256"]
            == review["independent_initial_decisions_sha256"]
            or review["root_final_decisions_sha256"]
            != review["independent_final_decisions_sha256"]
            or review["root_final_decisions_sha256"]
            != review["canonical_final_decisions_sha256"]
        ):
            raise RuntimeError(f"{context} Vision reconciliation drift: {split}")

    expected_population_counts = {
        "calibration": [27, 10, 63, 58, 15, 11, 13, 24, 24, 12],
        "holdout": [27, 9, 64, 59, 15, 11, 14, 25, 24, 12],
    }
    formal_minima = [15, 10, 30, 4, 8, 4, 4, 8, 8, 6]
    development_floors = [19, 13, 38, 6, 10, 6, 6, 10, 10, 8]
    population = value["population_audit"]
    if (
        population["eligible_artifact_condition_clusters_per_split"] != 100
        or population["all_eligible_artifact_condition_clusters_exact_polarity_pairs"]
        is not True
        or population["passed"] is not False
    ):
        raise RuntimeError(f"{context} population summary drift")
    for split, counts in expected_population_counts.items():
        split_audit = population["splits"][split]
        formal = split_audit["formal_endpoint_minimums"]
        development = split_audit["development_safety_floors"]
        for index, endpoint_id in enumerate(EXPECTED_ENDPOINT_IDS):
            if formal[endpoint_id] != {
                "unique_cluster_count": counts[index],
                "minimum_unique_clusters": formal_minima[index],
                "count_passed": counts[index] >= formal_minima[index],
            } or development[endpoint_id] != {
                "unique_cluster_count": counts[index],
                "development_minimum_unique_clusters": development_floors[index],
                "count_passed": counts[index] >= development_floors[index],
            }:
                raise RuntimeError(
                    f"{context} population endpoint drift: {split}/{endpoint_id}"
                )

    for field, digest in value["hash_bindings"].items():
        expected_length = 40 if field == "captured_repository_head" else 64
        if not isinstance(digest, str) or re.fullmatch(
            rf"[0-9a-f]{{{expected_length}}}", digest
        ) is None:
            raise RuntimeError(f"{context} malformed hash binding: {field}")


def validate_dev_r13_premeasurement_population_failure_audit(value: Any) -> None:
    """Validate the exact sanitized dev-r13 population-gate failure evidence."""

    context = "closed dev-r13 premeasurement population failure audit"
    require_exact_keys(
        value,
        {
            "artifact",
            "schema_version",
            "authority",
            "formal_use_forbidden",
            "audit_recorded_at",
            "development_edition",
            "outcome",
            "failure_phase",
            "failure_class",
            "measurement_started",
            "selection_status",
            "development_hard_threshold",
            "calibration_endpoint_performance",
            "holdout_endpoint_performance",
            "threshold_selection_audit",
            "one_shot_contract",
            "vision_review",
            "private_audit",
            "population_audit",
            "failure_marker_summary",
            "hash_bindings",
            "absent_measurement_artifacts",
            "postmortem",
            "root_cause",
            "successor_constraints",
            "secret_handling",
        },
        context,
    )
    timestamp = value["audit_recorded_at"]
    if not isinstance(timestamp, str) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z", timestamp
    ) is None:
        raise RuntimeError(f"{context}.audit_recorded_at must be canonical UTC text")
    parse_utc_timestamp(timestamp, f"{context}.audit_recorded_at")
    expected_header = {
        "artifact": "microtexture-v2-r6-dev-r13-development-premeasurement-population-failure-audit",
        "schema_version": "microtexture-v2-r6-development-premeasurement-population-failure-audit/1",
        "authority": False,
        "formal_use_forbidden": True,
        "development_edition": "r13",
        "outcome": "failed_closed",
        "failure_phase": "private-audits-passed-then-premeasurement-population-audit",
        "failure_class": "warning-cluster-population-shortfall",
        "measurement_started": False,
        "selection_status": "not_started_population_gate_failed",
        "development_hard_threshold": None,
        "calibration_endpoint_performance": None,
        "holdout_endpoint_performance": None,
        "threshold_selection_audit": None,
    }
    for field, expected in expected_header.items():
        _require_exact_json_value(value[field], expected, f"{context}.{field}")

    if sha256_bytes(canonical_json_bytes(value)) != (
        "14a74805cf49e098964afbc573736d5b70d26ce6ada59e986cfc97614db27c5b"
    ):
        raise RuntimeError(f"{context} canonical semantic digest drift")

    vision = value["vision_review"]
    if (
        vision["records_per_split_per_reviewer"] != 220
        or vision["review_boards_per_split_per_reviewer"] != 37
        or vision["logical_comparison_fields"]
        != ["page", "row", "anonymous_code", "disposition", "severity", "flags"]
        or vision["evidence_notes_excluded_from_logical_comparison"] is not True
        or vision["initial_snapshots_persisted_immutably"] is not True
        or vision["all_differences_reinspected_native_then_evidence"] is not True
        or vision["final_reconciled"] is not True
        or vision["canonical_labels_equal_both_reviewers"] is not True
    ):
        raise RuntimeError(f"{context} Vision review contract drift")
    for split, initial_difference_count in (("calibration", 62), ("holdout", 72)):
        review = vision["splits"][split]
        if (
            review["initial_exact_logical_agreement"] is not False
            or review["initial_logical_difference_count"] != initial_difference_count
            or review["all_differences_reinspected_native_then_evidence"] is not True
            or review["reconciled"] is not True
            or review["root_initial_decisions_sha256"]
            == review["independent_initial_decisions_sha256"]
            or review["root_final_decisions_sha256"]
            != review["independent_final_decisions_sha256"]
            or review["root_final_decisions_sha256"]
            != review["canonical_final_decisions_sha256"]
        ):
            raise RuntimeError(f"{context} Vision reconciliation drift: {split}")

    expected_population_counts = {
        "calibration": [29, 14, 57, 17, 13, 11, 11, 22, 22, 11],
        "holdout": [27, 12, 61, 20, 13, 14, 12, 26, 22, 11],
    }
    formal_minima = [15, 10, 30, 4, 8, 4, 4, 8, 8, 6]
    development_floors = [19, 13, 38, 6, 10, 6, 6, 10, 10, 8]
    population = value["population_audit"]
    if (
        population["eligible_artifact_condition_clusters_per_split"] != 100
        or population["all_eligible_artifact_condition_clusters_exact_polarity_pairs"]
        is not True
        or population["passed"] is not False
    ):
        raise RuntimeError(f"{context} population summary drift")
    for split, counts in expected_population_counts.items():
        split_audit = population["splits"][split]
        formal = split_audit["formal_endpoint_minimums"]
        development = split_audit["development_safety_floors"]
        for index, endpoint_id in enumerate(EXPECTED_ENDPOINT_IDS):
            if formal[endpoint_id] != {
                "unique_cluster_count": counts[index],
                "minimum_unique_clusters": formal_minima[index],
                "count_passed": counts[index] >= formal_minima[index],
            } or development[endpoint_id] != {
                "unique_cluster_count": counts[index],
                "development_minimum_unique_clusters": development_floors[index],
                "count_passed": counts[index] >= development_floors[index],
            }:
                raise RuntimeError(
                    f"{context} population endpoint drift: {split}/{endpoint_id}"
                )

    for field, digest in value["hash_bindings"].items():
        expected_length = 40 if field == "captured_repository_head" else 64
        if not isinstance(digest, str) or re.fullmatch(
            rf"[0-9a-f]{{{expected_length}}}", digest
        ) is None:
            raise RuntimeError(f"{context} malformed hash binding: {field}")


def validate_dev_r14_premeasurement_population_failure_audit(value: Any) -> None:
    """Validate the exact sanitized dev-r14 population-gate failure evidence."""

    context = "closed dev-r14 premeasurement population failure audit"
    require_exact_keys(
        value,
        {
            "artifact",
            "schema_version",
            "authority",
            "formal_use_forbidden",
            "audit_recorded_at",
            "development_edition",
            "outcome",
            "failure_phase",
            "failure_class",
            "measurement_started",
            "selection_status",
            "development_hard_threshold",
            "calibration_endpoint_performance",
            "holdout_endpoint_performance",
            "threshold_selection_audit",
            "one_shot_contract",
            "vision_review",
            "private_audit",
            "population_audit",
            "failure_marker_summary",
            "hash_bindings",
            "absent_measurement_artifacts",
            "postmortem",
            "root_cause",
            "successor_constraints",
            "secret_handling",
        },
        context,
    )
    timestamp = value["audit_recorded_at"]
    if not isinstance(timestamp, str) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z", timestamp
    ) is None:
        raise RuntimeError(f"{context}.audit_recorded_at must be canonical UTC text")
    parse_utc_timestamp(timestamp, f"{context}.audit_recorded_at")
    expected_header = {
        "artifact": "microtexture-v2-r6-dev-r14-development-premeasurement-population-failure-audit",
        "schema_version": "microtexture-v2-r6-development-premeasurement-population-failure-audit/1",
        "authority": False,
        "formal_use_forbidden": True,
        "development_edition": "r14",
        "outcome": "failed_closed",
        "failure_phase": "private-audits-passed-then-premeasurement-population-audit",
        "failure_class": "development-safety-floor-microblob-shortfall",
        "measurement_started": False,
        "selection_status": "not_started_population_gate_failed",
        "development_hard_threshold": None,
        "calibration_endpoint_performance": None,
        "holdout_endpoint_performance": None,
        "threshold_selection_audit": None,
    }
    for field, expected in expected_header.items():
        _require_exact_json_value(value[field], expected, f"{context}.{field}")

    if sha256_bytes(canonical_json_bytes(value)) != (
        "8761abe586508348ebbbd1a9786777c8d702eb82f51f4808350e63954ee92a45"
    ):
        raise RuntimeError(f"{context} canonical semantic digest drift")

    vision = value["vision_review"]
    if (
        vision["records_per_split_per_reviewer"] != 220
        or vision["review_boards_per_split_per_reviewer"] != 37
        or vision["logical_comparison_fields"]
        != ["page", "row", "anonymous_code", "disposition", "severity", "flags"]
        or vision["evidence_notes_excluded_from_logical_comparison"] is not True
        or vision["initial_snapshots_persisted_immutably"] is not True
        or vision["all_differences_reinspected_native_then_evidence"] is not True
        or vision["final_reconciled"] is not True
        or vision["canonical_labels_equal_both_reviewers"] is not True
    ):
        raise RuntimeError(f"{context} Vision review contract drift")
    for split, initial_difference_count in (("calibration", 69), ("holdout", 67)):
        review = vision["splits"][split]
        if (
            review["initial_exact_logical_agreement"] is not False
            or review["initial_logical_difference_count"] != initial_difference_count
            or review["all_differences_reinspected_native_then_evidence"] is not True
            or review["reconciled"] is not True
            or review["root_initial_decisions_sha256"]
            == review["independent_initial_decisions_sha256"]
            or review["root_final_decisions_sha256"]
            != review["independent_final_decisions_sha256"]
            or review["root_final_decisions_sha256"]
            != review["canonical_final_decisions_sha256"]
        ):
            raise RuntimeError(f"{context} Vision reconciliation drift: {split}")

    expected_population_counts = {
        "calibration": [35, 15, 50, 13, 12, 12, 4, 16, 22, 11],
        "holdout": [31, 16, 53, 20, 11, 11, 9, 20, 22, 11],
    }
    formal_minima = [15, 10, 30, 4, 8, 4, 4, 8, 8, 6]
    development_floors = [19, 13, 38, 6, 10, 6, 6, 10, 10, 8]
    population = value["population_audit"]
    if (
        population["eligible_artifact_condition_clusters_per_split"] != 100
        or population["all_eligible_artifact_condition_clusters_exact_polarity_pairs"]
        is not True
        or population["passed"] is not False
    ):
        raise RuntimeError(f"{context} population summary drift")
    for split, counts in expected_population_counts.items():
        split_audit = population["splits"][split]
        formal = split_audit["formal_endpoint_minimums"]
        development = split_audit["development_safety_floors"]
        for index, endpoint_id in enumerate(EXPECTED_ENDPOINT_IDS):
            if formal[endpoint_id] != {
                "unique_cluster_count": counts[index],
                "minimum_unique_clusters": formal_minima[index],
                "count_passed": counts[index] >= formal_minima[index],
            } or development[endpoint_id] != {
                "unique_cluster_count": counts[index],
                "development_minimum_unique_clusters": development_floors[index],
                "count_passed": counts[index] >= development_floors[index],
            }:
                raise RuntimeError(
                    f"{context} population endpoint drift: {split}/{endpoint_id}"
                )

    for field, digest in value["hash_bindings"].items():
        expected_length = 40 if field == "captured_repository_head" else 64
        if not isinstance(digest, str) or re.fullmatch(
            rf"[0-9a-f]{{{expected_length}}}", digest
        ) is None:
            raise RuntimeError(f"{context} malformed hash binding: {field}")


def validate_dev_r15_premeasurement_population_failure_audit(value: Any) -> None:
    """Validate the exact sanitized dev-r15 population-gate failure evidence."""

    context = "closed dev-r15 premeasurement population failure audit"
    require_exact_keys(
        value,
        {
            "artifact",
            "schema_version",
            "authority",
            "formal_use_forbidden",
            "audit_recorded_at",
            "development_edition",
            "outcome",
            "failure_phase",
            "failure_class",
            "measurement_started",
            "selection_status",
            "development_hard_threshold",
            "calibration_endpoint_performance",
            "holdout_endpoint_performance",
            "threshold_selection_audit",
            "one_shot_contract",
            "vision_review",
            "private_audit",
            "population_audit",
            "failure_marker_summary",
            "hash_bindings",
            "absent_measurement_artifacts",
            "postmortem",
            "root_cause",
            "successor_constraints",
            "secret_handling",
        },
        context,
    )
    timestamp = value["audit_recorded_at"]
    if not isinstance(timestamp, str) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z", timestamp
    ) is None:
        raise RuntimeError(f"{context}.audit_recorded_at must be canonical UTC text")
    parse_utc_timestamp(timestamp, f"{context}.audit_recorded_at")
    expected_header = {
        "artifact": "microtexture-v2-r6-dev-r15-development-premeasurement-population-failure-audit",
        "schema_version": "microtexture-v2-r6-development-premeasurement-population-failure-audit/1",
        "authority": False,
        "formal_use_forbidden": True,
        "development_edition": "r15",
        "outcome": "failed_closed",
        "failure_phase": "private-audits-passed-then-premeasurement-population-audit",
        "failure_class": "warning-cluster-population-shortfall",
        "measurement_started": False,
        "selection_status": "not_started_population_gate_failed",
        "development_hard_threshold": None,
        "calibration_endpoint_performance": None,
        "holdout_endpoint_performance": None,
        "threshold_selection_audit": None,
    }
    for field, expected in expected_header.items():
        _require_exact_json_value(value[field], expected, f"{context}.{field}")

    if sha256_bytes(canonical_json_bytes(value)) != (
        "f153779020b1564b01c409115bdd823b6a3e30e0f444d6cf1076e139a369f63e"
    ):
        raise RuntimeError(f"{context} canonical semantic digest drift")

    expected_one_shot = {
        "generation_completed_exactly_once": True,
        "root_vision_completed_before_private_reveal": True,
        "independent_vision_completed_before_private_reveal": True,
        "all_440_records_reviewed_by_each_reviewer": True,
        "root_and_independent_decisions_reconciled_before_preflight": True,
        "review_preflight_invoked_exactly_once": True,
        "review_preflight_passed": True,
        "labels_sealed_before_private_reveal": True,
        "private_reveal_started_after_label_seal": True,
        "private_sentinel_audit_passed": True,
        "population_audit_started_exactly_once": True,
        "population_audit_passed": False,
        "analysis_started_exactly_once": True,
        "numeric_metric_called": False,
        "threshold_search_started": False,
        "development_threshold_selected": False,
        "postmortem_invoked_exactly_once": True,
        "formal_cli_invoked": False,
        "formal_marker_created": False,
        "formal_threshold_created": False,
        "locked_clean_v18_decoded_or_measured": False,
        "failure_marker_created": True,
        "rerun_resume_relabel_retune_subset_topup_resample_or_reuse_for_r15_forbidden": True,
        "r15_closed": True,
    }
    _require_exact_json_value(
        value["one_shot_contract"], expected_one_shot, f"{context}.one_shot_contract"
    )

    vision = value["vision_review"]
    require_exact_keys(
        vision,
        {
            "records_per_split_per_reviewer",
            "review_boards_per_split_per_reviewer",
            "logical_comparison_fields",
            "evidence_notes_excluded_from_logical_comparison",
            "initial_snapshots_persisted_immutably",
            "splits",
            "all_differences_reinspected_native_then_evidence",
            "final_reconciled",
            "canonical_labels_equal_both_reviewers",
            "total_initial_logical_and_notes_only_difference_count",
            "initial_independent_snapshots_preserved_after_dsl_drift_discovery",
            "reconciled_finals_passed_official_parser_and_ev3",
            "initial_independent_dsl_drift",
        },
        f"{context}.vision_review",
    )
    if (
        vision["records_per_split_per_reviewer"] != 220
        or vision["review_boards_per_split_per_reviewer"] != 37
        or vision["logical_comparison_fields"]
        != ["page", "row", "anonymous_code", "disposition", "severity", "flags"]
        or vision["evidence_notes_excluded_from_logical_comparison"] is not True
        or vision["initial_snapshots_persisted_immutably"] is not True
        or vision["all_differences_reinspected_native_then_evidence"] is not True
        or vision["final_reconciled"] is not True
        or vision["canonical_labels_equal_both_reviewers"] is not True
        or vision["total_initial_logical_and_notes_only_difference_count"] != 257
        or vision[
            "initial_independent_snapshots_preserved_after_dsl_drift_discovery"
        ]
        is not True
        or vision["reconciled_finals_passed_official_parser_and_ev3"] is not True
    ):
        raise RuntimeError(f"{context} Vision review contract drift")
    expected_dsl_drift = {
        "present": True,
        "systematic_noncanonical_flags_token": "lp",
        "required_canonical_flags_token": "l,p",
        "calibration_record_count": 29,
        "holdout_record_count": 30,
        "all_affected_records_intended_flag_set": ["l", "p"],
        "all_affected_records_l_and_p_locator_sets_identical": True,
        "independent_initial_snapshots_official_dsl_conformant": False,
        "independent_initial_snapshots_modified": False,
        "independent_initial_self_lint_pass_claim_correct": False,
        "self_lint_defect": "flags were concatenated without a delimiter and comma-separated canonical serialization was not enforced",
        "resolved_only_in_reconciled_final_after_all_differences_reinspected": True,
        "reconciled_final_official_parser_and_ev3_validation_passed": True,
    }
    _require_exact_json_value(
        vision["initial_independent_dsl_drift"],
        expected_dsl_drift,
        f"{context}.vision_review.initial_independent_dsl_drift",
    )
    expected_reviews = {
        "calibration": {
            "root_initial_decisions_sha256": "97d2eae9be3918534a9a7e70e047369dafc31c2b817ffc1e1d978ecbd5fadeea",
            "independent_initial_decisions_sha256": "85520c950c5d655f0ed6353a331b1057af117232df5096ee787591eb01c840d3",
            "initial_exact_logical_agreement": False,
            "initial_logical_difference_count": 65,
            "all_differences_reinspected_native_then_evidence": True,
            "reconciled": True,
            "root_final_decisions_sha256": "2663fa37ec88c65a1b3ec53f3f9612251690947de16ed5eec0ed9eb42bc71adb",
            "independent_final_decisions_sha256": "2663fa37ec88c65a1b3ec53f3f9612251690947de16ed5eec0ed9eb42bc71adb",
            "canonical_final_decisions_sha256": "2663fa37ec88c65a1b3ec53f3f9612251690947de16ed5eec0ed9eb42bc71adb",
            "completed_labels_sha256": "14055ae886dd3ed1883aea2e10452bf8bd04e67e60367b1148c00b3847a299e2",
            "initial_notes_only_difference_count": 51,
            "independent_initial_noncanonical_lp_record_count": 29,
            "independent_initial_official_dsl_conformant": False,
        },
        "holdout": {
            "root_initial_decisions_sha256": "a6865bc9af86aa4e63441eca702b16d190e32fac452ff0d8ee886338b120059d",
            "independent_initial_decisions_sha256": "f951fd6eb89118b971224b49c688f2ff7261bc47625e2dd677be2f34d70b9420",
            "initial_exact_logical_agreement": False,
            "initial_logical_difference_count": 44,
            "all_differences_reinspected_native_then_evidence": True,
            "reconciled": True,
            "root_final_decisions_sha256": "2437f1906940204e43736a4f07e048295d796f9c6174b394be80d41c3d2df1e3",
            "independent_final_decisions_sha256": "2437f1906940204e43736a4f07e048295d796f9c6174b394be80d41c3d2df1e3",
            "canonical_final_decisions_sha256": "2437f1906940204e43736a4f07e048295d796f9c6174b394be80d41c3d2df1e3",
            "completed_labels_sha256": "fd4757378e43074b42b0c73b313fdc5743489b71a7f6b68b1b6b1eed70f639e9",
            "initial_notes_only_difference_count": 97,
            "independent_initial_noncanonical_lp_record_count": 30,
            "independent_initial_official_dsl_conformant": False,
        },
    }
    _require_exact_json_value(
        vision["splits"], expected_reviews, f"{context}.vision_review.splits"
    )

    expected_population_counts = {
        "calibration": [29, 12, 59, 40, 15, 12, 11, 22, 22, 11],
        "holdout": [33, 9, 58, 44, 14, 11, 11, 22, 22, 11],
    }
    formal_minima = [15, 10, 30, 4, 8, 4, 4, 8, 8, 6]
    development_floors = [19, 13, 38, 6, 10, 6, 6, 10, 10, 8]
    population = value["population_audit"]
    if (
        population["eligible_artifact_condition_clusters_per_split"] != 100
        or population["all_eligible_artifact_condition_clusters_exact_polarity_pairs"]
        is not True
        or population["passed"] is not False
    ):
        raise RuntimeError(f"{context} population summary drift")
    for split, counts in expected_population_counts.items():
        split_audit = population["splits"][split]
        formal = split_audit["formal_endpoint_minimums"]
        development = split_audit["development_safety_floors"]
        expected_formal_pass = split == "calibration"
        if (
            split_audit["split"] != split
            or split_audit["condition_cluster_count"] != 100
            or split_audit["all_eligible_clusters_exact_polarity_pairs"] is not True
            or split_audit["formal_endpoint_minimums_passed"]
            is not expected_formal_pass
            or split_audit["development_safety_floors_passed"] is not False
            or split_audit["passed"] is not False
        ):
            raise RuntimeError(f"{context} population split summary drift: {split}")
        for index, endpoint_id in enumerate(EXPECTED_ENDPOINT_IDS):
            if formal[endpoint_id] != {
                "unique_cluster_count": counts[index],
                "minimum_unique_clusters": formal_minima[index],
                "count_passed": counts[index] >= formal_minima[index],
            } or development[endpoint_id] != {
                "unique_cluster_count": counts[index],
                "development_minimum_unique_clusters": development_floors[index],
                "count_passed": counts[index] >= development_floors[index],
            }:
                raise RuntimeError(
                    f"{context} population endpoint drift: {split}/{endpoint_id}"
                )

    expected_failure_marker = {
        "artifact": "microtexture-v2-r6-development-analysis-failure",
        "schema_version": "microtexture-v2-r6-development-analysis-failure/1",
        "authority": False,
        "formal_use_forbidden": True,
        "development_edition": "r15",
        "development_closed": True,
        "measurement_started": False,
        "error_type": "RuntimeError",
        "message": "development endpoint population premeasurement audit failed",
    }
    _require_exact_json_value(
        value["failure_marker_summary"],
        expected_failure_marker,
        f"{context}.failure_marker_summary",
    )
    expected_hash_bindings = {
        "captured_repository_head": "c0a81cc356507c280c9968d80ae8a3db59d75584",
        "preregistered_spec_sha256": "21199f17cdd7fff6f30c6f2a41cd2d5e465cd63de67b0d480a892423629d4aef",
        "implementation_bindings_sha256": "0b867b626a9cd7810aebd08c3aa6cb2711c2650de0cc57a9e5516f5fd7ef20ec",
        "dev_r14_failure_audit_sha256": "79acad1ef7972293e2697bd4c81edcc2c6ec017b4121e6609b94b95391c25476",
        "development_boundary_sha256": "b29d15d03fb018924b0aa77d1e12f3c5ee6402bc9a32a7c2ce9db8a50c267872",
        "generation_start_sha256": "1d0e7772accbe921516f2fc2083f08f0be4d281f7ba25244edfd3a9a0c26e312",
        "generation_summary_sha256": "0c915939e6d7092c1a8252e3f4a990955aebd37c4b816152b5e323a95b920958",
        "generation_seal_sha256": "b2466d8714f168a8a0056f682d42c5a095a136ee771a7272c63d3223fe7e8123",
        "generation_completion_sha256": "43c16120674641e65a6cc4852d4a08071ec050604dc5b53f4ece8539323ed9e4",
        "blind_key_commitment": "50d36e88e56f564e990722d0a1ba045b93788b1047e3d8956aa1fa1837872426",
        "calibration_manifest_sha256": "0de860967511971049decee047015043ab3e32f438117dd0ac80ceaeaf8bf0ef",
        "calibration_blank_labels_sha256": "537dcdc94c347b8f9af0404e8f5b72edfebf9084aa41457b45f9f8c6e184ebba",
        "calibration_review_index_sha256": "c3dd783b264e6b65e9d3ca51d0fb3a2d1af348c09f902064bbfef9ebee7cd219",
        "holdout_manifest_sha256": "89bea7a34bd79af44e654c4af74dee000ae7801b9a637f89c62d2ee4b52c2a4a",
        "holdout_blank_labels_sha256": "ad7ff815a6e1c827ded9985b8aa0ced1d6c552c46874929c1e7dd04b93aa246b",
        "holdout_review_index_sha256": "b275871ead7bcdf4510241c8bc662d047ebf5477e664225947067c4a67962055",
        "label_seal_receipt_sha256": "d5e94fddb35e055de2a111882bdff329050473baea1c30e369a093b04583eff6",
        "population_audit_sha256": "0f71e82e41b3f47fc61a062cfb40401df2c1827a858c2f7458129f7b9b5c73a1",
        "failure_marker_sha256": "93c5b87a010a49236023e282cc8b21c781a40d25ef8f3f93aba5ef003883d5af",
    }
    _require_exact_json_value(
        value["hash_bindings"], expected_hash_bindings, f"{context}.hash_bindings"
    )
    for field, digest in value["hash_bindings"].items():
        expected_length = 40 if field == "captured_repository_head" else 64
        if not isinstance(digest, str) or re.fullmatch(
            rf"[0-9a-f]{{{expected_length}}}", digest
        ) is None:
            raise RuntimeError(f"{context} malformed hash binding: {field}")

    _require_exact_json_value(
        value["absent_measurement_artifacts"],
        {
            "calibration_measurements_present": False,
            "holdout_measurements_present": False,
            "analysis_result_present": False,
            "holdout_endpoint_result_present": False,
        },
        f"{context}.absent_measurement_artifacts",
    )
    _require_exact_json_value(
        value["postmortem"],
        {
            "invoked_exactly_once": True,
            "read_only": True,
            "raw_output_tracked": False,
            "sanitized_aggregate_only_in_this_audit": True,
            "anonymous_code_to_private_identity_mapping_tracked": False,
            "used_to_relabel_resample_subset_topup_retune_or_select_a_threshold": False,
        },
        f"{context}.postmortem",
    )
    _require_exact_json_value(
        value["successor_constraints"],
        {
            "r15_data_role": "development_only_premeasurement_population_failure_evidence",
            "formal_r6_must_not_start_from_r15_failure": True,
            "successor_must_be_fully_fresh_r16": True,
            "successor_requires_fresh_preregistered_revision": True,
            "successor_requires_fresh_root_key_public_nonces_hmac_domains_parameter_nonces_controls_references_identities_codes_commitments_labels_and_measurements": True,
            "r15_root_key_controls_references_pixels_identities_codes_commitments_labels_measurements_nonces_public_surfaces_and_postmortem_output_reuse_forbidden": True,
            "formal_endpoint_population_and_rate_minima_must_not_be_weakened": True,
            "development_safety_floors_must_not_be_weakened": True,
            "formal_and_development_minima_must_remain_unchanged": True,
            "successor_may_use_only_this_sanitized_aggregate_failure_evidence": True,
            "successor_authority_must_be_committed_pushed_and_dual_ci_green_before_generation": True,
            "formal_r6_root_and_environment_must_remain_absent": True,
        },
        f"{context}.successor_constraints",
    )
    _require_exact_json_value(
        value["secret_handling"],
        {
            "blind_key_present_in_this_artifact": False,
            "blind_key_value_logged_or_tracked": False,
            "development_blind_key_path": "tmp/map-production/microtexture-v2-r6-dev-r15/private/development-key.bin",
            "development_blind_key_bytes": 32,
            "development_blind_key_reuse_forbidden": True,
            "anonymous_code_to_private_identity_mapping_tracked": False,
            "private_labels_measurements_identities_or_pixels_tracked": False,
            "postmortem_raw_output_tracked": False,
            "closed_temporary_artifact_root": "tmp/map-production/microtexture-v2-r6-dev-r15",
            "development_blind_key_path_is_git_ignored": True,
        },
        f"{context}.secret_handling",
    )


def validate_dev_r16_premeasurement_failure_audit(value: Any) -> None:
    """Validate sanitized, closed dev-r16 premeasurement Vision-gate evidence."""

    context = "closed dev-r16 premeasurement failure audit"
    require_exact_keys(
        value,
        {
            "artifact",
            "schema_version",
            "authority",
            "formal_use_forbidden",
            "audit_recorded_at",
            "development_edition",
            "outcome",
            "failure_phase",
            "failure_class",
            "measurement_started",
            "selection_status",
            "development_hard_threshold",
            "calibration_endpoint_performance",
            "holdout_endpoint_performance",
            "threshold_selection_audit",
            "one_shot_contract",
            "vision_review",
            "private_audit_failure",
            "failure_marker_summary",
            "hash_bindings",
            "measurement_artifacts",
            "postmortem",
            "root_cause",
            "successor_constraints",
            "secret_handling",
        },
        context,
    )
    timestamp = value["audit_recorded_at"]
    if not isinstance(timestamp, str) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z", timestamp
    ) is None:
        raise RuntimeError(f"{context}.audit_recorded_at must be canonical UTC text")
    parse_utc_timestamp(timestamp, f"{context}.audit_recorded_at")
    expected_header = {
        "artifact": "microtexture-v2-r6-dev-r16-development-premeasurement-failure-audit",
        "schema_version": "microtexture-v2-r6-development-premeasurement-failure-audit/1",
        "authority": False,
        "formal_use_forbidden": True,
        "development_edition": "r16",
        "outcome": "failed_closed",
        "failure_phase": "private-sentinel-audit-before-population-audit",
        "failure_class": "sealed-vision-false-positive-on-protocol-zero-sentinel",
        "measurement_started": False,
        "selection_status": "not_started_private_sentinel_gate_failed",
        "development_hard_threshold": None,
        "calibration_endpoint_performance": None,
        "holdout_endpoint_performance": None,
        "threshold_selection_audit": None,
    }
    for field, expected in expected_header.items():
        _require_exact_json_value(value[field], expected, f"{context}.{field}")

    if sha256_bytes(canonical_json_bytes(value)) != (
        "3e18c47f49b3e501333390366308f9224ab051c79c3e7f73fca30d29e3625d56"
    ):
        raise RuntimeError(f"{context} canonical semantic digest drift")

    expected_one_shot = {
        "generation_completed_exactly_once": True,
        "root_vision_completed_before_private_reveal": True,
        "independent_vision_completed_before_private_reveal": True,
        "all_440_records_reviewed_by_each_reviewer": True,
        "root_and_independent_decisions_reconciled_before_preflight": True,
        "review_preflight_invoked_exactly_once": True,
        "review_preflight_passed": True,
        "labels_sealed_before_private_reveal": True,
        "private_reveal_started_after_label_seal": True,
        "private_sentinel_audit_started_exactly_once": True,
        "private_sentinel_audit_passed": False,
        "population_audit_started": False,
        "population_audit_passed": False,
        "analysis_started_exactly_once": True,
        "numeric_metric_called": False,
        "threshold_search_started": False,
        "development_threshold_selected": False,
        "postmortem_invoked_exactly_once": True,
        "formal_cli_invoked": False,
        "formal_marker_created": False,
        "formal_threshold_created": False,
        "locked_clean_v18_decoded_or_measured": False,
        "failure_marker_created": True,
        "rerun_resume_relabel_retune_subset_topup_resample_or_reuse_for_r16_forbidden": True,
        "r16_closed": True,
    }
    _require_exact_json_value(
        value["one_shot_contract"],
        expected_one_shot,
        f"{context}.one_shot_contract",
    )

    vision = value["vision_review"]
    require_exact_keys(
        vision,
        {
            "records_per_split_per_reviewer",
            "review_boards_per_split_per_reviewer",
            "logical_comparison_fields",
            "evidence_notes_excluded_from_logical_comparison",
            "initial_snapshots_persisted_immutably",
            "initial_snapshots_official_decision_dsl_conformant",
            "splits",
            "all_differences_reinspected_native_then_evidence",
            "final_reconciled",
            "canonical_labels_equal_both_reviewers",
            "total_initial_logical_and_notes_only_difference_count",
            "initial_snapshots_preserved_after_reconciliation",
        },
        f"{context}.vision_review",
    )
    if (
        vision["records_per_split_per_reviewer"] != 220
        or vision["review_boards_per_split_per_reviewer"] != 37
        or vision["logical_comparison_fields"]
        != ["page", "row", "anonymous_code", "disposition", "severity", "flags"]
        or vision["evidence_notes_excluded_from_logical_comparison"] is not True
        or vision["initial_snapshots_persisted_immutably"] is not True
        or vision["initial_snapshots_official_decision_dsl_conformant"] is not True
        or vision["all_differences_reinspected_native_then_evidence"] is not True
        or vision["final_reconciled"] is not True
        or vision["canonical_labels_equal_both_reviewers"] is not True
        or vision["total_initial_logical_and_notes_only_difference_count"] != 291
        or vision["initial_snapshots_preserved_after_reconciliation"] is not True
    ):
        raise RuntimeError(f"{context} Vision review contract drift")
    expected_reviews = {
        "calibration": {
            "root_initial_decisions_sha256": "181debab34652f817a1b5b22f0c3eda41d29ba46aeb627b9e75c54b734d72ef6",
            "independent_initial_decisions_sha256": "ecef00bd6b039ff2965daa0dc5b1b752e629d3d09098e8d1e673ad57d1fffcc4",
            "initial_exact_logical_agreement": False,
            "initial_logical_difference_count": 72,
            "initial_notes_only_difference_count": 56,
            "all_differences_reinspected_native_then_evidence": True,
            "reconciled": True,
            "root_final_decisions_sha256": "127905a6606ede7ea4f05cc1a131f959d3e8e0d4a8ffa294dcd19d33649f2063",
            "independent_final_decisions_sha256": "127905a6606ede7ea4f05cc1a131f959d3e8e0d4a8ffa294dcd19d33649f2063",
            "canonical_final_decisions_sha256": "127905a6606ede7ea4f05cc1a131f959d3e8e0d4a8ffa294dcd19d33649f2063",
            "completed_labels_sha256": "f4baebebf66bcf0d00dee5829f719d6b92351d8ac9288efaae14a20c069221a2",
            "record_dispositions": {"clean": 70, "warning": 42, "reject": 108},
            "reconciled_final_official_parser_and_ev3_passed": True,
        },
        "holdout": {
            "root_initial_decisions_sha256": "6951222736a6f7fabb16835675fd468e299aa5fe82e260802848a8ad1086e556",
            "independent_initial_decisions_sha256": "8f25ad2da52ba0fcfb766c5d6d3554dd8aa177a368dac6ffa0cfff54eff4075c",
            "initial_exact_logical_agreement": False,
            "initial_logical_difference_count": 57,
            "initial_notes_only_difference_count": 106,
            "all_differences_reinspected_native_then_evidence": True,
            "reconciled": True,
            "root_final_decisions_sha256": "49b83499c74b40ad5e415e2c393e7acde3d1b1c4f5df610a76c52bb0b8f46121",
            "independent_final_decisions_sha256": "49b83499c74b40ad5e415e2c393e7acde3d1b1c4f5df610a76c52bb0b8f46121",
            "canonical_final_decisions_sha256": "49b83499c74b40ad5e415e2c393e7acde3d1b1c4f5df610a76c52bb0b8f46121",
            "completed_labels_sha256": "9b5241f2e0e0bf25d728af4a5283903edb7e804023c41aebb88fd494dab7880f",
            "record_dispositions": {"clean": 61, "warning": 50, "reject": 109},
            "reconciled_final_official_parser_and_ev3_passed": True,
        },
    }
    _require_exact_json_value(
        vision["splits"], expected_reviews, f"{context}.vision_review.splits"
    )
    total_differences = 0
    for split, review in vision["splits"].items():
        hash_fields = {field for field in review if field.endswith("_sha256")}
        if any(
            re.fullmatch(r"[0-9a-f]{64}", review[field]) is None
            for field in hash_fields
        ):
            raise RuntimeError(f"{context}.{split} Vision SHA-256 binding drift")
        final_sha = review["root_final_decisions_sha256"]
        if (
            review["root_initial_decisions_sha256"]
            == review["independent_initial_decisions_sha256"]
            or final_sha != review["independent_final_decisions_sha256"]
            or final_sha != review["canonical_final_decisions_sha256"]
            or sum(review["record_dispositions"].values()) != 220
        ):
            raise RuntimeError(f"{context}.{split} reconciliation contract drift")
        total_differences += review["initial_logical_difference_count"]
        total_differences += review["initial_notes_only_difference_count"]
    if total_differences != vision["total_initial_logical_and_notes_only_difference_count"]:
        raise RuntimeError(f"{context} Vision difference total drift")

    expected_private_failure = {
        "all_splits_passed": False,
        "affected_split": "holdout",
        "affected_record_count": 1,
        "expected_private_role": "protocol-zero",
        "anonymous_code_page_row_ev3_locator_private_identity_or_pixel_binding_tracked": False,
        "splits": {
            "calibration": {
                "protocol_zero_record_count": 16,
                "protocol_zero_clean_count": 16,
                "protocol_zero_warning_count": 0,
                "duplicate_audit_record_count": 4,
                "protocol_zero_audit_passed": True,
                "duplicate_audit_passed": True,
            },
            "holdout": {
                "protocol_zero_record_count": 16,
                "protocol_zero_clean_count": 15,
                "protocol_zero_warning_count": 1,
                "protocol_zero_warning_severity": 1,
                "protocol_zero_warning_visible_flags": ["l"],
                "duplicate_audit_record_count": 4,
                "protocol_zero_audit_passed": False,
                "duplicate_audit_passed": True,
            },
        },
        "interpretation": "One sealed holdout Vision decision saw a faint localized line impression and recorded a severity-1 short-line warning. Secret regeneration then proved that record was an exact-zero protocol sentinel, so the edition failed closed before population aggregation or any numeric metric call.",
    }
    _require_exact_json_value(
        value["private_audit_failure"],
        expected_private_failure,
        f"{context}.private_audit_failure",
    )

    expected_failure_marker = {
        "artifact": "microtexture-v2-r6-development-analysis-failure",
        "schema_version": "microtexture-v2-r6-development-analysis-failure/1",
        "authority": False,
        "formal_use_forbidden": True,
        "development_edition": "r16",
        "development_closed": True,
        "measurement_started": False,
        "error_type": "RuntimeError",
        "message": "holdout development sealed labels protocol-zero sentinel was not labeled clean: [redacted-opaque-code]",
    }
    _require_exact_json_value(
        value["failure_marker_summary"],
        expected_failure_marker,
        f"{context}.failure_marker_summary",
    )

    expected_hash_bindings = {
        "captured_repository_head": "d1b4c7a1a6247ce0cbea0eb6aed6a52a4cd5a4ea",
        "preregistered_spec_sha256": "ceb30ce754fd7601e6a3f12a98c52687650798893b7163901998747b38282493",
        "implementation_bindings_sha256": "b9c6394b0afd77b895ecb8519d00e75c61d00682e6663eea9a0c81b7b0584082",
        "dev_r15_failure_audit_sha256": "faa420e63af8b3f647e045ae4d71ac2fbe32316175e68999cc16b3e278311200",
        "development_boundary_sha256": "2c98248e220312a0562dc4679d879a9f6a08d881a3d1b7dcb76691201f22efd3",
        "generation_start_sha256": "4435bea9750e9b4aec84d2f9af484dcc93360640323270b5e7f36aeb79942799",
        "generation_summary_sha256": "8fd0cff826a46fd95123533320b10c2456d670daad82065d04464551c0506cc4",
        "generation_seal_sha256": "58aee92ae22e3436f8acfdb9c040609d2b96a696babcc2629ef7a1239139452e",
        "generation_completion_sha256": "4a72feffd045a96cf2941e766742e23a3402386804edafb68db81a2c29ddfebe",
        "blind_key_commitment": "f2ccdf7328e528b1cc1dc7c5989365a2b0e84c0b621769469d68deb82acacc91",
        "calibration_manifest_sha256": "0d97ea2ac1b4aaa86458d88b0972d715ca6c6dba1210c98c7463cb6a62ba490a",
        "calibration_blank_labels_sha256": "e247472d9c6350e5623c3cc8b49e22f43453859cbee6104392812a9e716cbecd",
        "calibration_review_index_sha256": "82ee79389c6ef2efabdbd92381ad868fa3834ea09884c867a4acd74516c841fc",
        "holdout_manifest_sha256": "8226ae847eb326818ba39ef96dcbb1cb965f35cd14f79bbe0df8ec0c239632da",
        "holdout_blank_labels_sha256": "9a81476652de59ac19beca321e08da22d9d3722cbad1a378bc2c3914920f46cd",
        "holdout_review_index_sha256": "9ba4be57fcf04b074973412a8948821c14b3eca85c134fe26dac00fe78de5995",
        "label_seal_receipt_sha256": "41894388953a7ee7f116429f8f437a77eed026c4b8d431387749071f75230184",
        "failure_marker_sha256": "34af6311d014914451959f4c983dab9b44191a04c261fa49b2b1ddef027d33d0",
    }
    _require_exact_json_value(
        value["hash_bindings"], expected_hash_bindings, f"{context}.hash_bindings"
    )
    for field, digest in value["hash_bindings"].items():
        expected_length = 40 if field == "captured_repository_head" else 64
        if not isinstance(digest, str) or re.fullmatch(
            rf"[0-9a-f]{{{expected_length}}}", digest
        ) is None:
            raise RuntimeError(f"{context} malformed hash binding: {field}")

    _require_exact_json_value(
        value["measurement_artifacts"],
        {
            "population_audit_present": False,
            "calibration_measurements_present": False,
            "holdout_measurements_present": False,
            "analysis_result_present": False,
            "threshold_selection_result_present": False,
            "holdout_endpoint_result_present": False,
            "failure_marker_present": True,
        },
        f"{context}.measurement_artifacts",
    )
    _require_exact_json_value(
        value["postmortem"],
        {
            "invoked_exactly_once": True,
            "read_only": True,
            "raw_output_tracked": False,
            "sanitized_aggregate_only_in_this_audit": True,
            "anonymous_code_page_row_ev3_locator_or_private_identity_mapping_tracked": False,
            "used_to_relabel_resample_subset_topup_retune_or_select_a_threshold": False,
        },
        f"{context}.postmortem",
    )
    _require_exact_json_value(
        value["root_cause"],
        {
            "generation_or_runtime_failure": False,
            "decision_reconciliation_failure": False,
            "population_or_metric_failure_evaluated": False,
            "vision_gate_failure": "A sealed holdout severity-1 short-line warning was a false positive on a privately regenerated exact-zero protocol sentinel; the faint localized impression was not generated morphology.",
            "premature_measurement_ruled_out": "The edition closed during the private sentinel audit before population aggregation and before the first numeric metric; no population, measurement, threshold, or endpoint result exists.",
            "postmortem": "One read-only invocation confirmed only the sanitized aggregate cause and tracked no raw output, code, page, locator, or private identity mapping.",
            "post_label_repair_forbidden": "The sealed dev-r16 outcome cannot be repaired by relabeling, rerunning, resuming, replacing, subsetting, topping up, resampling the key, regenerating, retuning, or reusing any dev-r16 material.",
        },
        f"{context}.root_cause",
    )
    _require_exact_json_value(
        value["successor_constraints"],
        {
            "r16_data_role": "development_only_premeasurement_vision_gate_failure_evidence",
            "formal_r6_must_not_start_from_r16_failure": True,
            "successor_must_be_fully_fresh_r17": True,
            "successor_requires_fresh_preregistered_revision": True,
            "successor_requires_fresh_root_key_public_nonces_hmac_domains_parameter_nonces_controls_references_identities_codes_commitments_labels_decisions_and_measurements": True,
            "r16_root_key_secrets_controls_references_pixels_identities_codes_commitments_labels_decisions_measurements_nonces_public_surfaces_and_postmortem_output_reuse_forbidden": True,
            "unchanged_preregistered_morphology_metric_threshold_population_and_rate_contract_required": True,
            "full_200_direct_visibility_gate_must_be_applied_without_enhancement_or_400_only_inference": True,
            "successor_purpose_is_general_reference_transform_prequalification_and_dual_initial_flag_corroboration_probe": True,
            "successor_may_use_only_this_sanitized_one_record_sentinel_aggregate": True,
            "successor_authority_must_be_committed_pushed_and_dual_ci_green_before_generation": True,
            "formal_r6_root_and_environment_must_remain_absent": True,
        },
        f"{context}.successor_constraints",
    )
    _require_exact_json_value(
        value["secret_handling"],
        {
            "blind_key_present_in_this_artifact": False,
            "blind_key_value_logged_or_tracked": False,
            "anonymous_code_to_private_identity_mapping_tracked": False,
            "private_labels_measurements_identities_or_pixels_tracked": False,
            "postmortem_raw_output_tracked": False,
            "development_blind_key_and_private_material_reuse_forbidden": True,
            "closed_development_root_reuse_forbidden": True,
        },
        f"{context}.secret_handling",
    )


def validate_dev_r17_premeasurement_population_failure_audit(value: Any) -> None:
    """Validate the exact sanitized dev-r17 population-gate failure evidence."""

    context = "closed dev-r17 premeasurement population failure audit"
    require_exact_keys(
        value,
        {
            "artifact",
            "schema_version",
            "authority",
            "formal_use_forbidden",
            "audit_recorded_at",
            "development_edition",
            "outcome",
            "failure_phase",
            "failure_class",
            "measurement_started",
            "selection_status",
            "development_hard_threshold",
            "calibration_endpoint_performance",
            "holdout_endpoint_performance",
            "threshold_selection_audit",
            "one_shot_contract",
            "vision_review",
            "private_audit",
            "population_audit",
            "failure_marker_summary",
            "hash_bindings",
            "absent_measurement_artifacts",
            "postmortem",
            "root_cause",
            "successor_constraints",
            "secret_handling",
        },
        context,
    )
    timestamp = value["audit_recorded_at"]
    if not isinstance(timestamp, str) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z", timestamp
    ) is None:
        raise RuntimeError(f"{context}.audit_recorded_at must be canonical UTC text")
    parse_utc_timestamp(timestamp, f"{context}.audit_recorded_at")

    expected_header = {
        "artifact": "microtexture-v2-r6-dev-r17-development-premeasurement-population-failure-audit",
        "schema_version": "microtexture-v2-r6-development-premeasurement-population-failure-audit/1",
        "authority": False,
        "formal_use_forbidden": True,
        "development_edition": "r17",
        "outcome": "failed_closed",
        "failure_phase": "private-audits-passed-then-premeasurement-population-audit",
        "failure_class": "holdout-tiny-speck-and-development-spot-population-shortfall",
        "measurement_started": False,
        "selection_status": "not_started_population_gate_failed",
        "development_hard_threshold": None,
        "calibration_endpoint_performance": None,
        "holdout_endpoint_performance": None,
        "threshold_selection_audit": None,
    }
    for field, expected in expected_header.items():
        _require_exact_json_value(value[field], expected, f"{context}.{field}")

    if sha256_bytes(canonical_json_bytes(value)) != (
        "94eeb3defeeef2696505f56f9bb9cd6aad1d78562d0378c90b7add9b61d84ab5"
    ):
        raise RuntimeError(f"{context} canonical semantic digest drift")

    expected_one_shot = {
        "generation_completed_exactly_once": True,
        "root_vision_completed_exactly_once_before_private_reveal": True,
        "independent_vision_completed_exactly_once_before_private_reveal": True,
        "all_440_records_reviewed_by_each_reviewer": True,
        "root_initial_snapshot_and_receipt_sealed_exactly_once": True,
        "independent_initial_snapshot_and_receipt_sealed_exactly_once": True,
        "root_and_independent_decisions_reconciled_exactly_once_before_preflight": True,
        "review_preflight_invoked_exactly_once": True,
        "review_preflight_passed": True,
        "labels_sealed_exactly_once_before_private_reveal": True,
        "private_reveal_started_after_label_seal": True,
        "private_audit_started_exactly_once": True,
        "private_sentinel_audit_passed": True,
        "population_audit_started_exactly_once": True,
        "population_audit_passed": False,
        "analysis_started_exactly_once": True,
        "numeric_metric_called": False,
        "threshold_search_started": False,
        "development_threshold_selected": False,
        "postmortem_invoked_exactly_once": True,
        "formal_cli_invoked": False,
        "formal_marker_created": False,
        "formal_threshold_created": False,
        "locked_clean_v18_decoded_or_measured": False,
        "failure_marker_created": True,
        "rerun_resume_relabel_retune_subset_topup_resample_or_reuse_for_r17_forbidden": True,
        "r17_closed": True,
    }
    _require_exact_json_value(
        value["one_shot_contract"],
        expected_one_shot,
        f"{context}.one_shot_contract",
    )

    expected_vision = {
        "records_per_split_per_reviewer": 220,
        "review_boards_per_split_per_reviewer": 37,
        "logical_comparison_fields": [
            "page",
            "row",
            "anonymous_code",
            "disposition",
            "severity",
            "flags",
        ],
        "evidence_notes_excluded_from_logical_comparison": True,
        "initial_snapshots_persisted_immutably": True,
        "initial_snapshots_official_decision_dsl_conformant": True,
        "initial_snapshot_receipts_verified": True,
        "splits": {
            "calibration": {
                "root_initial_decisions_sha256": "c129297ebfc7da8bbaa0837a55f19b014418cd72b060616a6e7442645ba1c83f",
                "root_initial_receipt_sha256": "a29e56cb01281535468620de55fd6c39d4801e77a0aa0f6f9ed46a7360f775c9",
                "independent_initial_decisions_sha256": "5f534b4d41f88fbbbc3737f4aa95630d867742d98f3d5f3c3813fe949035387c",
                "independent_initial_receipt_sha256": "edf3a9a3379d484c653ee659f784c211539f15e79996568a8fbf3535a893de49",
                "initial_exact_logical_agreement": False,
                "initial_logical_difference_count": 97,
                "initial_notes_only_difference_count": 17,
                "all_differences_reinspected_native_then_evidence": True,
                "reconciled": True,
                "root_final_decisions_sha256": "1d5c225877e8e8c50679816f6abde9c111df137168e0d86f18ae3a8ef9152c7b",
                "independent_final_decisions_sha256": "1d5c225877e8e8c50679816f6abde9c111df137168e0d86f18ae3a8ef9152c7b",
                "canonical_final_decisions_sha256": "1d5c225877e8e8c50679816f6abde9c111df137168e0d86f18ae3a8ef9152c7b",
                "completed_labels_sha256": "dc31f1d65dc4f9e08c2b1ab1da47f850be04fa59a187794bb4777a3ee4133fc7",
                "record_dispositions": {
                    "clean": 82,
                    "warning": 41,
                    "reject": 97,
                },
                "reconciled_final_official_parser_and_ev3_passed": True,
                "final_visible_flags_subset_of_both_initial_flag_sets": True,
            },
            "holdout": {
                "root_initial_decisions_sha256": "37b141a6f6462309fc47196360e173126cd42efec0801aadd311bc5ef18fe45e",
                "root_initial_receipt_sha256": "d4fafd0f4f93e96baea8ac3b81a42610970ec215ec920430a1459da368fc2d3e",
                "independent_initial_decisions_sha256": "fb1512533bf695aea9b1fcf255f7a8a1752a3ff33693be3235b3c668a0757e28",
                "independent_initial_receipt_sha256": "4f5fe9bfe8fe94752749293b923223a90ac6bf02413733ef7f8058f306f46309",
                "initial_exact_logical_agreement": False,
                "initial_logical_difference_count": 84,
                "initial_notes_only_difference_count": 60,
                "all_differences_reinspected_native_then_evidence": True,
                "reconciled": True,
                "root_final_decisions_sha256": "389eaf7163a9f4f4306bdffc57e4fefd27287f4e341106c22873ed9c1918b93d",
                "independent_final_decisions_sha256": "389eaf7163a9f4f4306bdffc57e4fefd27287f4e341106c22873ed9c1918b93d",
                "canonical_final_decisions_sha256": "389eaf7163a9f4f4306bdffc57e4fefd27287f4e341106c22873ed9c1918b93d",
                "completed_labels_sha256": "d7285d2b45242eecad0dfa16d8c5888e870e951ceb643fa13b17d8671f5458b9",
                "record_dispositions": {
                    "clean": 82,
                    "warning": 56,
                    "reject": 82,
                },
                "reconciled_final_official_parser_and_ev3_passed": True,
                "final_visible_flags_subset_of_both_initial_flag_sets": True,
            },
        },
        "all_differences_reinspected_native_then_evidence": True,
        "final_reconciled": True,
        "canonical_labels_equal_both_reviewers": True,
        "total_initial_logical_and_notes_only_difference_count": 258,
        "initial_snapshots_and_receipts_preserved_after_reconciliation": True,
        "bilateral_initial_visible_flag_intersection_gate": {
            "revision": "dev-r17-bilateral-initial-visible-flag-intersection-gate-v1",
            "manifest_sha256": "f042250290f80d4304923e3b564746e8311515f5c649811678db934bb3ad6ffd",
            "both_official_initial_snapshots_and_receipts_required": True,
            "final_visible_flag_set_relation": "subset-of-root-initial-intersection-independent-initial",
            "private_role_input": False,
            "passed": True,
        },
    }
    _require_exact_json_value(
        value["vision_review"], expected_vision, f"{context}.vision_review"
    )
    total_differences = 0
    for split, review in value["vision_review"]["splits"].items():
        hash_fields = {field for field in review if field.endswith("_sha256")}
        if any(
            re.fullmatch(r"[0-9a-f]{64}", review[field]) is None
            for field in hash_fields
        ):
            raise RuntimeError(f"{context}.{split} Vision SHA-256 binding drift")
        final_sha = review["root_final_decisions_sha256"]
        if (
            final_sha != review["independent_final_decisions_sha256"]
            or final_sha != review["canonical_final_decisions_sha256"]
            or sum(review["record_dispositions"].values()) != 220
        ):
            raise RuntimeError(f"{context}.{split} reconciliation contract drift")
        total_differences += review["initial_logical_difference_count"]
        total_differences += review["initial_notes_only_difference_count"]
    if total_differences != 258:
        raise RuntimeError(f"{context} Vision difference total drift")

    expected_private_audit = {
        "all_splits_passed": True,
        "anonymous_code_page_row_private_identity_or_pixel_binding_tracked": False,
        "splits": {
            split: {
                "record_count": 220,
                "artifact_record_count": 200,
                "protocol_zero_record_count": 16,
                "duplicate_audit_record_count": 4,
                "contact_sheet_count": 185,
                "review_board_count": 37,
                "regenerated_public_commitments_matched": True,
                "regenerated_contact_sheet_bytes_matched": True,
                "regenerated_review_board_bytes_matched": True,
                "protocol_zero_audit_passed": True,
                "duplicate_audit_passed": True,
            }
            for split in ("calibration", "holdout")
        },
    }
    _require_exact_json_value(
        value["private_audit"],
        expected_private_audit,
        f"{context}.private_audit",
    )

    population_counts = {
        "calibration": [27, 22, 51, 11, 11, 11, 10, 20, 20, 10],
        "holdout": [30, 30, 40, 28, 11, 0, 9, 9, 20, 10],
    }
    formal_minima = [15, 10, 30, 4, 8, 4, 4, 8, 8, 6]
    development_floors = [19, 13, 38, 6, 10, 6, 6, 10, 10, 8]
    expected_population_splits: dict[str, Any] = {}
    for split, counts in population_counts.items():
        formal = {
            endpoint_id: {
                "unique_cluster_count": counts[index],
                "minimum_unique_clusters": formal_minima[index],
                "count_passed": counts[index] >= formal_minima[index],
            }
            for index, endpoint_id in enumerate(EXPECTED_ENDPOINT_IDS)
        }
        development = {
            endpoint_id: {
                "unique_cluster_count": counts[index],
                "development_minimum_unique_clusters": development_floors[index],
                "count_passed": counts[index] >= development_floors[index],
            }
            for index, endpoint_id in enumerate(EXPECTED_ENDPOINT_IDS)
        }
        formal_passed = all(endpoint["count_passed"] for endpoint in formal.values())
        development_passed = all(
            endpoint["count_passed"] for endpoint in development.values()
        )
        expected_population_splits[split] = {
            "split": split,
            "condition_cluster_count": 100,
            "all_eligible_clusters_exact_polarity_pairs": True,
            "formal_endpoint_minimums": formal,
            "formal_endpoint_minimums_passed": formal_passed,
            "development_safety_floors": development,
            "development_safety_floors_passed": development_passed,
            "passed": formal_passed and development_passed,
        }
    _require_exact_json_value(
        value["population_audit"],
        {
            "eligible_artifact_condition_clusters_per_split": 100,
            "all_eligible_artifact_condition_clusters_exact_polarity_pairs": True,
            "splits": expected_population_splits,
            "passed": False,
        },
        f"{context}.population_audit",
    )

    _require_exact_json_value(
        value["failure_marker_summary"],
        {
            "artifact": "microtexture-v2-r6-development-analysis-failure",
            "schema_version": "microtexture-v2-r6-development-analysis-failure/1",
            "authority": False,
            "formal_use_forbidden": True,
            "development_edition": "r17",
            "development_closed": True,
            "measurement_started": False,
            "error_type": "RuntimeError",
            "message": "development endpoint population premeasurement audit failed",
        },
        f"{context}.failure_marker_summary",
    )
    expected_hash_bindings = {
        "captured_repository_head": "e58f936613e37886b6d4edded6494c3a34d8d6f7",
        "preregistered_spec_sha256": "523cf3229bf20c4f6737692e79270d6861b46371ee3ae1d107a094be6f1a84b7",
        "implementation_bindings_sha256": "a5caea5b971b27ccbd273d289f7c4a83fa2a6c1eb6a213d19cbb555687150a35",
        "dev_r16_failure_audit_sha256": "4637978a7ac5d59c99ec076e527b7be6e5d2ad1c0477077e2587fda7091ca169",
        "development_boundary_sha256": "8d6429929a81467feead59b8e3ea3bf1557f5dac14201fab096e0e3a7de9237a",
        "generation_start_sha256": "2d976e15ffb1fbf7ef2dc8579adf54b908b59eed4e7e5f64b61a3a16ce0dcd42",
        "generation_summary_sha256": "53a8ef9b909ff5166f7c1218eea175569de6629d49639e19cdfdd081060e148d",
        "generation_seal_sha256": "f05d2a45bd7660ec12ac119917462e907aa6529a5b575cf5381b546e22ede416",
        "generation_completion_sha256": "ddf34fd028e8e659c327cd1cd2c131be5bd2091ec29171f4e39d76349c6f349f",
        "blind_key_commitment": "1be08c146b7f4d9373faaeacde207a107ced8dea8b06f5b39b0c40b06832c719",
        "calibration_manifest_sha256": "0c56cf950f12817f73de06cfe0752784fb2afe544e78f9fc69a5c143e988a308",
        "calibration_blank_labels_sha256": "4ed1c547082e73d0be854f43f67ab1352e257c87b7fc1ca6a5ebc4487a57ad95",
        "calibration_review_index_sha256": "6e5ec142139ec42399d983218166addf619387ae76e0b501071aa6ca2d3b386e",
        "holdout_manifest_sha256": "7c574b6926be90c0b1374e3632fe88d660c87a2b8b9d3043557ebd6eb60e9b56",
        "holdout_blank_labels_sha256": "2eea50d0342a354d8aee39dafebfe115061d951850cb18bf4891d338b767f93b",
        "holdout_review_index_sha256": "01274d736943e568d5bf21400d21016ab89e69e79b8e684ccc304c3a67f9f486",
        "label_seal_receipt_sha256": "bc000f99dc6f4e801f33cd6608538aa15f9bffd41ad0e67b05c667a8ebcb3062",
        "population_audit_sha256": "ee6f42526085e2b828e65d768b043d852b16a62eb462ebca666bd4a7c4d6f45a",
        "failure_marker_sha256": "af3e89eb4e2372e5c92e0b637ff67a91a953a019ec51c970a23d05edcf7cf067",
    }
    _require_exact_json_value(
        value["hash_bindings"], expected_hash_bindings, f"{context}.hash_bindings"
    )
    for field, digest in value["hash_bindings"].items():
        expected_length = 40 if field == "captured_repository_head" else 64
        if not isinstance(digest, str) or re.fullmatch(
            rf"[0-9a-f]{{{expected_length}}}", digest
        ) is None:
            raise RuntimeError(f"{context} malformed hash binding: {field}")

    _require_exact_json_value(
        value["absent_measurement_artifacts"],
        {
            "calibration_measurements_present": False,
            "holdout_measurements_present": False,
            "analysis_result_present": False,
            "threshold_selection_result_present": False,
            "holdout_endpoint_result_present": False,
        },
        f"{context}.absent_measurement_artifacts",
    )
    _require_exact_json_value(
        value["postmortem"],
        {
            "invoked_exactly_once": True,
            "read_only": True,
            "raw_output_tracked": False,
            "sanitized_aggregate_only_in_this_audit": True,
            "anonymous_code_to_private_identity_mapping_tracked": False,
            "used_to_relabel_resample_subset_topup_retune_or_select_a_threshold": False,
        },
        f"{context}.postmortem",
    )
    _require_exact_json_value(
        value["root_cause"],
        {
            "generation_or_runtime_failure": False,
            "decision_reconciliation_failure": False,
            "private_audit_failure": False,
            "population_feasibility": "Calibration passed every formal endpoint minimum and development safety floor. Holdout tiny-speck reject population 0 missed formal minimum 4 and development floor 6; holdout spot reject population 9 passed formal minimum 8 but missed development floor 10; every other holdout endpoint passed both minima.",
            "premature_measurement_ruled_out": "The edition closed at the premeasurement population gate before the first numeric metric; no score, candidate threshold, selected threshold, or holdout endpoint result exists.",
            "postmortem": "One read-only invocation confirmed only the sanitized aggregate cause and supplied no raw output, mapping, repair, or tuning.",
            "repair_forbidden": "The sealed dev-r17 edition cannot be repaired by relabeling, rerunning, resuming, replacing, subsetting, topping up, resampling the key, regenerating, retuning, or reusing any dev-r17 material.",
        },
        f"{context}.root_cause",
    )
    _require_exact_json_value(
        value["successor_constraints"],
        {
            "r17_data_role": "development_only_premeasurement_population_failure_evidence",
            "formal_r6_must_not_start_from_r17_failure": True,
            "successor_preregistered_in_this_audit": False,
            "any_successor_must_be_fully_fresh": True,
            "successor_requires_fresh_preregistered_revision": True,
            "successor_requires_fresh_root_key_public_nonces_hmac_domains_parameter_nonces_controls_references_identities_codes_commitments_labels_decisions_and_measurements": True,
            "r17_root_key_private_material_controls_references_pixels_identities_codes_commitments_labels_decisions_measurements_nonces_public_surfaces_and_postmortem_output_reuse_forbidden": True,
            "formal_endpoint_population_and_rate_minima_must_not_be_weakened": True,
            "development_safety_floors_must_not_be_weakened": True,
            "formal_and_development_minima_must_remain_unchanged": True,
            "successor_may_use_only_this_sanitized_aggregate_failure_evidence": True,
            "successor_authority_must_be_committed_pushed_and_dual_ci_green_before_generation": True,
            "formal_r6_root_and_environment_must_remain_absent": True,
        },
        f"{context}.successor_constraints",
    )
    _require_exact_json_value(
        value["secret_handling"],
        {
            "blind_key_present_in_this_artifact": False,
            "blind_key_value_logged_or_tracked": False,
            "development_blind_key_path": "tmp/map-production/microtexture-v2-r6-dev-r17/private/development-key.bin",
            "development_blind_key_bytes": 32,
            "development_blind_key_reuse_forbidden": True,
            "anonymous_code_to_private_identity_mapping_tracked": False,
            "private_labels_measurements_identities_or_pixels_tracked": False,
            "postmortem_raw_output_tracked": False,
            "closed_temporary_artifact_root": "tmp/map-production/microtexture-v2-r6-dev-r17",
            "development_blind_key_path_is_git_ignored": True,
        },
        f"{context}.secret_handling",
    )


def validate_dev_r18_premeasurement_private_audit_failure(value: Any) -> None:
    """Validate the exact sanitized dev-r18 private duplicate-audit failure."""

    context = "closed dev-r18 prepopulation private-audit failure"
    require_exact_keys(
        value,
        {
            "artifact",
            "schema_version",
            "authority",
            "formal_use_forbidden",
            "audit_recorded_at",
            "development_edition",
            "outcome",
            "failure_phase",
            "failure_class",
            "measurement_started",
            "selection_status",
            "development_hard_threshold",
            "calibration_endpoint_performance",
            "holdout_endpoint_performance",
            "threshold_selection_audit",
            "one_shot_contract",
            "vision_review",
            "private_audit_failure",
            "failure_marker_summary",
            "hash_bindings",
            "measurement_artifacts",
            "postmortem",
            "root_cause",
            "successor_constraints",
            "secret_handling",
        },
        context,
    )
    timestamp = value["audit_recorded_at"]
    if not isinstance(timestamp, str) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z", timestamp
    ) is None:
        raise RuntimeError(f"{context}.audit_recorded_at must be canonical UTC text")
    parse_utc_timestamp(timestamp, f"{context}.audit_recorded_at")
    expected_header = {
        "artifact": "microtexture-v2-r6-dev-r18-development-private-audit-failure-audit",
        "schema_version": "microtexture-v2-r6-development-private-audit-failure-audit/1",
        "authority": False,
        "formal_use_forbidden": True,
        "development_edition": "r18",
        "outcome": "failed_closed",
        "failure_phase": "private-audit-before-population-audit",
        "failure_class": "calibration-artifact-duplicate-reject-severity-ordinal-mismatch",
        "measurement_started": False,
        "selection_status": "not_started_private_duplicate_gate_failed",
        "development_hard_threshold": None,
        "calibration_endpoint_performance": None,
        "holdout_endpoint_performance": None,
        "threshold_selection_audit": None,
    }
    for field, expected in expected_header.items():
        _require_exact_json_value(value[field], expected, f"{context}.{field}")
    if sha256_bytes(canonical_json_bytes(value)) != (
        "10c12737ef87d5bbea1fdde216fef2f533c3b52b4924eb6794b54d402a76c3c8"
    ):
        raise RuntimeError(f"{context} canonical semantic digest drift")

    _require_exact_json_value(
        value["one_shot_contract"],
        {
            "generation_completed_exactly_once": True,
            "root_vision_completed_exactly_once_before_private_reveal": True,
            "independent_vision_completed_exactly_once_before_private_reveal": True,
            "all_440_records_reviewed_by_each_reviewer": True,
            "root_initial_snapshot_and_receipt_sealed_exactly_once": True,
            "independent_initial_snapshot_and_receipt_sealed_exactly_once": True,
            "root_and_independent_decisions_reconciled_exactly_once_before_preflight": True,
            "review_preflight_invoked_exactly_once": True,
            "review_preflight_passed": True,
            "labels_sealed_exactly_once_before_private_reveal": True,
            "private_reveal_started_after_label_seal": True,
            "private_audit_started_exactly_once": True,
            "private_regeneration_and_public_surface_match_audit_passed": True,
            "protocol_zero_audits_passed_both_splits": True,
            "duplicate_audit_passed": False,
            "population_audit_started": False,
            "population_audit_passed": False,
            "analysis_started_exactly_once": True,
            "numeric_metric_called": False,
            "threshold_search_started": False,
            "development_threshold_selected": False,
            "postmortem_invoked_exactly_once": True,
            "formal_cli_invoked": False,
            "formal_marker_created": False,
            "formal_threshold_created": False,
            "locked_clean_v18_decoded_or_measured": False,
            "failure_marker_created": True,
            "rerun_resume_relabel_retune_subset_topup_resample_or_reuse_for_r18_forbidden": True,
            "r18_closed": True,
        },
        f"{context}.one_shot_contract",
    )

    vision = value["vision_review"]
    require_exact_keys(
        vision,
        {
            "records_per_split_per_reviewer",
            "review_boards_per_split_per_reviewer",
            "logical_comparison_fields",
            "evidence_notes_excluded_from_logical_comparison",
            "initial_snapshots_persisted_immutably",
            "initial_snapshots_official_decision_dsl_conformant",
            "initial_snapshot_receipts_verified",
            "splits",
            "all_differences_reinspected_native_then_evidence",
            "final_reconciled",
            "canonical_labels_equal_both_reviewers",
            "total_initial_logical_and_notes_only_difference_count",
            "initial_snapshots_and_receipts_preserved_after_reconciliation",
            "bilateral_initial_visible_flag_intersection_gate",
        },
        f"{context}.vision_review",
    )
    expected_split_keys = {
        "root_initial_decisions_sha256",
        "root_initial_receipt_sha256",
        "independent_initial_decisions_sha256",
        "independent_initial_receipt_sha256",
        "initial_exact_logical_agreement",
        "initial_logical_difference_count",
        "initial_notes_only_difference_count",
        "all_differences_reinspected_native_then_evidence",
        "reconciled",
        "root_final_decisions_sha256",
        "independent_final_decisions_sha256",
        "canonical_final_decisions_sha256",
        "completed_labels_sha256",
        "record_dispositions",
        "reconciled_final_official_parser_and_ev3_passed",
        "final_visible_flags_subset_of_both_initial_flag_sets",
    }
    if set(vision["splits"]) != {"calibration", "holdout"}:
        raise RuntimeError(f"{context} Vision split coverage drift")
    total_differences = 0
    for split, review in vision["splits"].items():
        require_exact_keys(review, expected_split_keys, f"{context}.vision_review.{split}")
        require_exact_keys(
            review["record_dispositions"],
            {"clean", "warning", "reject"},
            f"{context}.vision_review.{split}.record_dispositions",
        )
        hash_fields = {field for field in review if field.endswith("_sha256")}
        if any(
            not isinstance(review[field], str)
            or re.fullmatch(r"[0-9a-f]{64}", review[field]) is None
            for field in hash_fields
        ):
            raise RuntimeError(f"{context}.{split} Vision SHA-256 binding drift")
        final_sha = review["root_final_decisions_sha256"]
        if (
            review["initial_exact_logical_agreement"] is not False
            or review["all_differences_reinspected_native_then_evidence"] is not True
            or review["reconciled"] is not True
            or final_sha != review["independent_final_decisions_sha256"]
            or final_sha != review["canonical_final_decisions_sha256"]
            or sum(review["record_dispositions"].values()) != 220
            or review["reconciled_final_official_parser_and_ev3_passed"] is not True
            or review["final_visible_flags_subset_of_both_initial_flag_sets"] is not True
        ):
            raise RuntimeError(f"{context}.{split} reconciliation contract drift")
        total_differences += review["initial_logical_difference_count"]
        total_differences += review["initial_notes_only_difference_count"]
    if (
        vision["records_per_split_per_reviewer"] != 220
        or vision["review_boards_per_split_per_reviewer"] != 37
        or vision["logical_comparison_fields"]
        != ["page", "row", "anonymous_code", "disposition", "severity", "flags"]
        or total_differences != 306
        or total_differences
        != vision["total_initial_logical_and_notes_only_difference_count"]
    ):
        raise RuntimeError(f"{context} Vision review contract drift")
    _require_exact_json_value(
        vision["bilateral_initial_visible_flag_intersection_gate"],
        {
            "revision": "dev-r17-bilateral-initial-visible-flag-intersection-gate-v1",
            "manifest_sha256": "f042250290f80d4304923e3b564746e8311515f5c649811678db934bb3ad6ffd",
            "both_official_initial_snapshots_and_receipts_required": True,
            "final_visible_flag_set_relation": "subset-of-root-initial-intersection-independent-initial",
            "private_role_input": False,
            "passed": True,
        },
        f"{context}.vision_review.bilateral_initial_visible_flag_intersection_gate",
    )

    private_failure = value["private_audit_failure"]
    require_exact_keys(
        private_failure,
        {
            "all_splits_passed",
            "affected_split",
            "failed_audit",
            "private_regeneration_and_public_surface_match_audit_passed",
            "protocol_zero_audits_passed_both_splits",
            "anonymous_code_page_row_ev3_locator_private_identity_or_pixel_binding_tracked",
            "semantic_signature_at_failure",
            "splits",
            "calibration_artifact_duplicate_observation",
            "interpretation",
        },
        f"{context}.private_audit_failure",
    )
    expected_private_split_keys = {
        "record_count",
        "artifact_record_count",
        "protocol_zero_record_count",
        "protocol_zero_clean_count",
        "duplicate_audit_record_count",
        "duplicate_group_count",
        "contact_sheet_count",
        "review_board_count",
        "regenerated_public_commitments_matched",
        "regenerated_contact_sheet_bytes_matched",
        "regenerated_review_board_bytes_matched",
        "protocol_zero_audit_passed",
        "clean_duplicate_group_passed",
        "artifact_duplicate_group_passed",
        "duplicate_audit_passed",
    }
    for split, audit in private_failure["splits"].items():
        require_exact_keys(
            audit, expected_private_split_keys, f"{context}.private_audit.{split}"
        )
    _require_exact_json_value(
        private_failure["calibration_artifact_duplicate_observation"],
        {
            "record_count": 2,
            "dispositions": ["reject", "reject"],
            "severity_ordinals": [2, 3],
            "visible_flags_in_canonical_order": [["l"], ["l"]],
            "disposition_exact_match": True,
            "severity_ordinal_exact_match": False,
            "all_five_visible_flags_exact_match": True,
            "both_obvious_artifacts_individually_reject_severity_2_or_3_with_short_line_visible": True,
            "reject_severity_band_equivalence_would_pass": True,
        },
        f"{context}.private_audit_failure.calibration_artifact_duplicate_observation",
    )
    if (
        private_failure["all_splits_passed"] is not False
        or private_failure["affected_split"] != "calibration"
        or private_failure["failed_audit"]
        != "artifact-duplicate-semantic-equivalence"
        or private_failure["splits"]["calibration"]["duplicate_audit_passed"]
        is not False
        or private_failure["splits"]["holdout"]["duplicate_audit_passed"]
        is not True
    ):
        raise RuntimeError(f"{context} private duplicate-audit aggregate drift")

    expected_hash_bindings = {
        "captured_repository_head": "58bde6ea9cba726ea329b511205d7564509f2eb8",
        "preregistered_spec_sha256": "cc384d931ec70d32f5e8d44b5363d25e9f8c53de0f608743468b6b189b2f9230",
        "implementation_bindings_sha256": "c678a49390f817a1b179f52982da9e872e7d79b954462ba920b1ae26cb6944c3",
        "development_authority_manifest_sha256": "d4bf229f7ae961e47aa66368ac386c5d911c8a9c81a0703b6650bda5fa9660f1",
        "dev_r17_failure_audit_sha256": "2177b04b6f79b75394cbdef6204423194603cd81e3a84b5a673c58393ccf5856",
        "development_boundary_sha256": "5b4924ecc403ec8ed49b789c8a51778ea08a3cc9317124af5140872798706f9f",
        "generation_start_sha256": "08f0a562c679850742831a2902c3e46a8a65cd83c6963fd3ccf7d1da264933af",
        "generation_summary_sha256": "81380059b5703e00f66e52b4db182f90d88e1cb07f55f554312c52d193d1ab2a",
        "generation_seal_sha256": "f1957f8e86a97cd8224b37ac984c248797dbc08ce1523d193ea7a68f57a0feaf",
        "generation_completion_sha256": "3207080756d7a1d4bae186b6182d4ce93dc367d00ac00c77afd47f336979bc9f",
        "blind_key_commitment": "fcbcec82889b22c37cb8a545c819d48cc0fbe6bce91c62eea3ae1c8a8acf37da",
        "calibration_manifest_sha256": "b6e59b01488cc94e1a7c80e835b36d0d1112f19e75d1f58edcfce7abb95d5bc0",
        "calibration_blank_labels_sha256": "180e62eb7d8501d4c034fcc2f5cd1b71d399078857dfb842a99098b3ff25ea2e",
        "calibration_review_index_sha256": "5b9ad779271d0e538e49ad71b751e619d5fd3cbbcb5a541783ef3e1b1521d1a1",
        "holdout_manifest_sha256": "f73f4d81bbaf67f45a9fe21fcd865f82ffcde3c8e409b06fa8125faae3fccc13",
        "holdout_blank_labels_sha256": "18a677659bd4fcaeb869b28b000e72c8972926998d79947bf8e39052c368cb04",
        "holdout_review_index_sha256": "ca89fa0248c0e7f61febfffd919f4a086dff2cf0a69b52c35212ac17ebfff1c6",
        "label_seal_receipt_sha256": "189f451a2fb2bda81c3e22c48c5a5a37a6f5817e520a2b7c9ff236166b8d528b",
        "failure_marker_sha256": "cc0537cf80e312529ddecdb0facaf2d9526ee5df35f89282d34da6700d9177dd",
    }
    _require_exact_json_value(
        value["hash_bindings"], expected_hash_bindings, f"{context}.hash_bindings"
    )
    for field, digest in value["hash_bindings"].items():
        expected_length = 40 if field == "captured_repository_head" else 64
        if not isinstance(digest, str) or re.fullmatch(
            rf"[0-9a-f]{{{expected_length}}}", digest
        ) is None:
            raise RuntimeError(f"{context} malformed hash binding: {field}")

    exact_nested_keysets = {
        "failure_marker_summary": {
            "artifact",
            "schema_version",
            "authority",
            "formal_use_forbidden",
            "development_edition",
            "development_closed",
            "measurement_started",
            "error_type",
            "message",
        },
        "measurement_artifacts": {
            "sealed_calibration_labels_present",
            "sealed_holdout_labels_present",
            "label_seal_receipt_present",
            "failure_marker_present",
            "population_audit_present",
            "calibration_measurements_present",
            "holdout_measurements_present",
            "analysis_result_present",
            "threshold_selection_result_present",
            "holdout_endpoint_result_present",
        },
        "postmortem": {
            "invoked_exactly_once",
            "read_only",
            "raw_output_tracked",
            "sanitized_aggregate_only_in_this_audit",
            "anonymous_code_page_row_ev3_locator_or_private_identity_mapping_tracked",
            "used_to_relabel_resample_subset_topup_retune_or_select_a_threshold",
        },
        "root_cause": {
            "generation_or_runtime_failure",
            "decision_reconciliation_failure",
            "private_regeneration_or_public_surface_mismatch",
            "protocol_zero_failure",
            "duplicate_semantic_equivalence_failure",
            "population_or_metric_failure_evaluated",
            "premature_measurement_ruled_out",
            "postmortem",
            "repair_forbidden",
        },
        "successor_constraints": {
            "r18_data_role",
            "formal_r6_must_not_start_from_r18_failure",
            "successor_preregistered_in_this_audit",
            "any_successor_must_be_fully_fresh",
            "successor_requires_fresh_preregistered_revision",
            "successor_requires_fresh_root_key_public_nonces_hmac_domains_parameter_nonces_controls_references_identities_codes_commitments_labels_decisions_and_measurements",
            "r18_root_key_private_material_controls_references_pixels_identities_codes_commitments_labels_decisions_measurements_nonces_public_surfaces_and_postmortem_output_reuse_forbidden",
            "all_r18_morphologies_tiers_metric_threshold_population_and_rate_contracts_must_be_preserved",
            "only_duplicate_semantic_equivalence_may_change",
            "reject_severity_2_and_3_must_share_one_duplicate_equivalence_band",
            "duplicate_disposition_and_all_five_visible_flags_must_remain_exact",
            "clean_and_warning_duplicate_severity_must_remain_exact",
            "successor_may_use_only_this_sanitized_aggregate_failure_evidence",
            "successor_authority_must_be_committed_pushed_and_dual_ci_green_before_generation",
            "formal_r6_root_and_environment_must_remain_absent",
        },
        "secret_handling": {
            "blind_key_present_in_this_artifact",
            "blind_key_value_logged_or_tracked",
            "anonymous_code_to_private_identity_mapping_tracked",
            "private_labels_measurements_identities_or_pixels_tracked",
            "postmortem_raw_output_tracked",
            "development_blind_key_and_private_material_reuse_forbidden",
            "closed_development_root_reuse_forbidden",
        },
    }
    for field, keys in exact_nested_keysets.items():
        require_exact_keys(value[field], keys, f"{context}.{field}")


def validate_dev_r19_premeasurement_private_audit_failure(value: Any) -> None:
    """Validate the exact sanitized dev-r19 private duplicate-audit failure."""

    context = "closed dev-r19 prepopulation private-audit failure"
    require_exact_keys(
        value,
        {
            "artifact",
            "schema_version",
            "authority",
            "formal_use_forbidden",
            "audit_recorded_at",
            "development_edition",
            "outcome",
            "failure_phase",
            "failure_class",
            "measurement_started",
            "selection_status",
            "development_hard_threshold",
            "calibration_endpoint_performance",
            "holdout_endpoint_performance",
            "threshold_selection_audit",
            "one_shot_contract",
            "vision_review",
            "private_audit_failure",
            "failure_marker_summary",
            "hash_bindings",
            "measurement_artifacts",
            "postmortem",
            "root_cause",
            "successor_constraints",
            "secret_handling",
        },
        context,
    )
    timestamp = value["audit_recorded_at"]
    if (
        not isinstance(timestamp, str)
        or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z", timestamp
        )
        is None
    ):
        raise RuntimeError(f"{context}.audit_recorded_at must be canonical UTC text")
    parse_utc_timestamp(timestamp, f"{context}.audit_recorded_at")
    expected_header = {
        "artifact": "microtexture-v2-r6-dev-r19-development-private-audit-failure-audit",
        "schema_version": "microtexture-v2-r6-development-private-audit-failure-audit/1",
        "authority": False,
        "formal_use_forbidden": True,
        "development_edition": "r19",
        "outcome": "failed_closed",
        "failure_phase": "private-audit-before-population-audit",
        "failure_class": "holdout-artifact-duplicate-obvious-short-line-clean-miss",
        "measurement_started": False,
        "selection_status": "not_started_private_duplicate_gate_failed",
        "development_hard_threshold": None,
        "calibration_endpoint_performance": None,
        "holdout_endpoint_performance": None,
        "threshold_selection_audit": None,
    }
    for field, expected in expected_header.items():
        _require_exact_json_value(value[field], expected, f"{context}.{field}")
    if sha256_bytes(canonical_json_bytes(value)) != (
        "54833ae6c35d7ec864f05fabefb8416844c63fe259780bda0ca309b6c31285e0"
    ):
        raise RuntimeError(f"{context} canonical semantic digest drift")

    _require_exact_json_value(
        value["one_shot_contract"],
        {
            "generation_completed_exactly_once": True,
            "root_vision_completed_exactly_once_before_private_reveal": True,
            "independent_vision_completed_exactly_once_before_private_reveal": True,
            "all_440_records_reviewed_by_each_reviewer": True,
            "root_initial_snapshot_and_receipt_sealed_exactly_once": True,
            "independent_initial_snapshot_and_receipt_sealed_exactly_once": True,
            "root_and_independent_decisions_reconciled_exactly_once_before_preflight": True,
            "review_preflight_invoked_exactly_once": True,
            "review_preflight_passed": True,
            "labels_sealed_exactly_once_before_private_reveal": True,
            "private_reveal_started_after_label_seal": True,
            "private_audit_started_exactly_once": True,
            "private_regeneration_and_public_surface_match_audit_passed": True,
            "protocol_zero_audits_passed_both_splits": True,
            "duplicate_audit_passed": False,
            "population_audit_started": False,
            "population_audit_passed": False,
            "analysis_started_exactly_once": True,
            "numeric_metric_called": False,
            "threshold_search_started": False,
            "development_threshold_selected": False,
            "postmortem_invoked_exactly_once": True,
            "formal_cli_invoked": False,
            "formal_marker_created": False,
            "formal_threshold_created": False,
            "locked_clean_v18_decoded_or_measured": False,
            "failure_marker_created": True,
            "rerun_resume_relabel_retune_subset_topup_resample_or_reuse_for_r19_forbidden": True,
            "r19_closed": True,
        },
        f"{context}.one_shot_contract",
    )

    vision = value["vision_review"]
    require_exact_keys(
        vision,
        {
            "records_per_split_per_reviewer",
            "review_boards_per_split_per_reviewer",
            "logical_comparison_fields",
            "evidence_notes_excluded_from_logical_comparison",
            "initial_snapshots_persisted_immutably",
            "initial_snapshots_official_decision_dsl_conformant",
            "initial_snapshot_receipts_verified",
            "splits",
            "all_differences_reinspected_native_then_evidence",
            "final_reconciled",
            "canonical_labels_equal_both_reviewers",
            "total_initial_logical_and_notes_only_difference_count",
            "initial_snapshots_and_receipts_preserved_after_reconciliation",
            "bilateral_initial_visible_flag_intersection_gate",
        },
        f"{context}.vision_review",
    )
    expected_split_keys = {
        "root_initial_decisions_sha256",
        "root_initial_receipt_sha256",
        "independent_initial_decisions_sha256",
        "independent_initial_receipt_sha256",
        "initial_exact_logical_agreement",
        "initial_logical_difference_count",
        "initial_notes_only_difference_count",
        "all_differences_reinspected_native_then_evidence",
        "reconciled",
        "root_final_decisions_sha256",
        "independent_final_decisions_sha256",
        "canonical_final_decisions_sha256",
        "completed_labels_sha256",
        "record_dispositions",
        "reconciled_final_official_parser_and_ev3_passed",
        "final_visible_flags_subset_of_both_initial_flag_sets",
    }
    if set(vision["splits"]) != {"calibration", "holdout"}:
        raise RuntimeError(f"{context} Vision split coverage drift")
    total_differences = 0
    for split, review in vision["splits"].items():
        require_exact_keys(
            review, expected_split_keys, f"{context}.vision_review.{split}"
        )
        require_exact_keys(
            review["record_dispositions"],
            {"clean", "warning", "reject"},
            f"{context}.vision_review.{split}.record_dispositions",
        )
        hash_fields = {field for field in review if field.endswith("_sha256")}
        if any(
            not isinstance(review[field], str)
            or re.fullmatch(r"[0-9a-f]{64}", review[field]) is None
            for field in hash_fields
        ):
            raise RuntimeError(f"{context}.{split} Vision SHA-256 binding drift")
        final_sha = review["root_final_decisions_sha256"]
        if (
            review["initial_exact_logical_agreement"] is not False
            or review["all_differences_reinspected_native_then_evidence"] is not True
            or review["reconciled"] is not True
            or final_sha != review["independent_final_decisions_sha256"]
            or final_sha != review["canonical_final_decisions_sha256"]
            or sum(review["record_dispositions"].values()) != 220
            or review["reconciled_final_official_parser_and_ev3_passed"] is not True
            or review["final_visible_flags_subset_of_both_initial_flag_sets"]
            is not True
        ):
            raise RuntimeError(f"{context}.{split} reconciliation contract drift")
        total_differences += review["initial_logical_difference_count"]
        total_differences += review["initial_notes_only_difference_count"]
    if (
        vision["records_per_split_per_reviewer"] != 220
        or vision["review_boards_per_split_per_reviewer"] != 37
        or vision["logical_comparison_fields"]
        != ["page", "row", "anonymous_code", "disposition", "severity", "flags"]
        or total_differences != 312
        or total_differences
        != vision["total_initial_logical_and_notes_only_difference_count"]
    ):
        raise RuntimeError(f"{context} Vision review contract drift")
    _require_exact_json_value(
        vision["bilateral_initial_visible_flag_intersection_gate"],
        {
            "revision": "dev-r17-bilateral-initial-visible-flag-intersection-gate-v1",
            "manifest_sha256": "f042250290f80d4304923e3b564746e8311515f5c649811678db934bb3ad6ffd",
            "both_official_initial_snapshots_and_receipts_required": True,
            "final_visible_flag_set_relation": "subset-of-root-initial-intersection-independent-initial",
            "private_role_input": False,
            "passed": True,
        },
        f"{context}.vision_review.bilateral_initial_visible_flag_intersection_gate",
    )

    private_failure = value["private_audit_failure"]
    require_exact_keys(
        private_failure,
        {
            "all_splits_passed",
            "affected_split",
            "failed_audit",
            "private_regeneration_and_public_surface_match_audit_passed",
            "protocol_zero_audits_passed_both_splits",
            "anonymous_code_page_row_ev3_locator_private_identity_or_pixel_binding_tracked",
            "semantic_signature_at_failure",
            "splits",
            "calibration_duplicate_aggregate_observation",
            "holdout_artifact_duplicate_observation",
            "interpretation",
        },
        f"{context}.private_audit_failure",
    )
    expected_private_split_keys = {
        "record_count",
        "artifact_record_count",
        "protocol_zero_record_count",
        "protocol_zero_clean_count",
        "duplicate_audit_record_count",
        "duplicate_group_count",
        "contact_sheet_count",
        "review_board_count",
        "regenerated_public_commitments_matched",
        "regenerated_contact_sheet_bytes_matched",
        "regenerated_review_board_bytes_matched",
        "protocol_zero_audit_passed",
        "clean_duplicate_group_passed",
        "artifact_duplicate_group_passed",
        "duplicate_audit_passed",
    }
    for split, audit in private_failure["splits"].items():
        require_exact_keys(
            audit, expected_private_split_keys, f"{context}.private_audit.{split}"
        )
    _require_exact_json_value(
        private_failure["calibration_duplicate_aggregate_observation"],
        {
            "clean_duplicate": {
                "record_count": 2,
                "dispositions": ["clean", "clean"],
                "severity_ordinals": [0, 0],
                "visible_flags_in_canonical_order": [[], []],
                "semantic_equivalence_passed": True,
            },
            "artifact_duplicate": {
                "record_count": 2,
                "dispositions": ["reject", "reject"],
                "severity_ordinals": [3, 3],
                "severity_equivalence_classes": ["reject-band", "reject-band"],
                "visible_flags_in_canonical_order": [["l"], ["l"]],
                "disposition_exact_match": True,
                "severity_equivalence_class_match": True,
                "all_five_visible_flags_exact_match": True,
                "both_obvious_artifacts_individually_reject_severity_2_or_3_with_short_line_visible": True,
                "semantic_equivalence_and_obvious_artifact_contract_passed": True,
            },
        },
        f"{context}.private_audit_failure.calibration_duplicate_aggregate_observation",
    )
    _require_exact_json_value(
        private_failure["holdout_artifact_duplicate_observation"],
        {
            "record_count": 2,
            "dispositions": ["clean", "clean"],
            "severity_ordinals": [0, 0],
            "severity_equivalence_classes": ["clean-exact", "clean-exact"],
            "visible_flags_in_canonical_order": [[], []],
            "disposition_exact_match": True,
            "severity_equivalence_class_match": True,
            "all_five_visible_flags_exact_match": True,
            "both_records_clean_severity_zero_with_no_visible_flags": True,
            "required_obvious_artifact_contract": "each record reject severity 2 or 3 with short_line_visible true",
            "required_obvious_artifact_contract_passed": False,
        },
        f"{context}.private_audit_failure.holdout_artifact_duplicate_observation",
    )
    if (
        private_failure["all_splits_passed"] is not False
        or private_failure["affected_split"] != "holdout"
        or private_failure["failed_audit"]
        != "artifact-duplicate-obvious-artifact-contract"
        or private_failure["splits"]["calibration"]["duplicate_audit_passed"]
        is not True
        or private_failure["splits"]["holdout"]["duplicate_audit_passed"] is not False
    ):
        raise RuntimeError(f"{context} private duplicate-audit aggregate drift")

    expected_hash_bindings = {
        "captured_repository_head": "8fcb229f1ee49b0889e61828644ad3d3c594c0d4",
        "preregistered_spec_sha256": "1fbf850662373dee6368626024df1298feed1913558edcdb15691ed19dbf6414",
        "implementation_bindings_sha256": "01680d9484f5f13d4f73aa19c292031e4a72df803eac43bbe383de199b3a8968",
        "development_authority_manifest_sha256": "b96a98c0c6a35f227a9b81c80220af9ffa99621828a71d10a2ddecb84cccb963",
        "dev_r18_failure_audit_sha256": "7800ab0f33363df30decb1c744e1b1ed3b7c822bb2f94fc4a17fd44d35541122",
        "development_boundary_sha256": "e0231e2b1caf65d67c87b4d946a070dbf499fcd2dd7c9fe01934f90349841e89",
        "generation_start_sha256": "c18f6a1ce82585a6aa800dd3f695e9da43f7221368bc09daf09bae23354e6717",
        "generation_summary_sha256": "c53bfed5d4ee828f2240c3a7dc806a4b2ad535842ed095a73b8e4987c554f2c8",
        "generation_seal_sha256": "25460dbe3691c1fc6a7c771dd1fc4f6e8134c42f125875ef5b73c55632136148",
        "generation_completion_sha256": "1fb0a3d2d9e82f535d62dadc460471082320616397c51ab996ed73090ac86a47",
        "blind_key_commitment": "c84482d79047682475647c36ecc91eecb7b49e9a7dad29a5d85284ed9f577888",
        "calibration_manifest_sha256": "95d1b3c10dcdc4c74a4aa1ab394c0f6cfec688146e15f3874c978f1b334c5acb",
        "calibration_blank_labels_sha256": "f493bdb3552ca40a8cd4b4ce408c046755cd1ad8ac61af3f8f2531f3ae14906f",
        "calibration_review_index_sha256": "39a52c8635a4be4fb4cce155637c06dab3f5035fc13ea4b3c78044c5650bbd22",
        "holdout_manifest_sha256": "7293445860640b17737d3b9e2aad53068974732aedb01dbd0dbdf9f68944e8e0",
        "holdout_blank_labels_sha256": "059dd10b9ebecb0106f6df4ea9cee698fd004006af9e0abd0f44a3f8fd949fdc",
        "holdout_review_index_sha256": "0fbda402328d8a555e1023dd33245ff92446c0fa63b9b4930c8a43e381da102f",
        "label_seal_receipt_sha256": "9d4c5ca1f4c4eb8df8cbc9138ddce942037f026b8aa35a41ba34f36f623a7ccd",
        "failure_marker_sha256": "98aec4dd4f5e8ac5f0d4a5b8e96a19e785d0d1b3afa8d7a401dfa75ed2a3ea9d",
    }
    _require_exact_json_value(
        value["hash_bindings"], expected_hash_bindings, f"{context}.hash_bindings"
    )
    for field, digest in value["hash_bindings"].items():
        expected_length = 40 if field == "captured_repository_head" else 64
        if (
            not isinstance(digest, str)
            or re.fullmatch(rf"[0-9a-f]{{{expected_length}}}", digest) is None
        ):
            raise RuntimeError(f"{context} malformed hash binding: {field}")

    exact_nested_keysets = {
        "failure_marker_summary": {
            "artifact",
            "schema_version",
            "authority",
            "formal_use_forbidden",
            "development_edition",
            "development_closed",
            "measurement_started",
            "error_type",
            "message",
        },
        "measurement_artifacts": {
            "sealed_calibration_labels_present",
            "sealed_holdout_labels_present",
            "label_seal_receipt_present",
            "failure_marker_present",
            "population_audit_present",
            "calibration_measurements_present",
            "holdout_measurements_present",
            "analysis_result_present",
            "threshold_selection_result_present",
            "holdout_endpoint_result_present",
        },
        "postmortem": {
            "invoked_exactly_once",
            "read_only",
            "raw_output_tracked",
            "sanitized_aggregate_only_in_this_audit",
            "anonymous_code_page_row_ev3_locator_or_private_identity_mapping_tracked",
            "used_to_relabel_resample_subset_topup_retune_or_select_a_threshold",
        },
        "root_cause": {
            "generation_or_runtime_failure",
            "decision_reconciliation_failure",
            "private_regeneration_or_public_surface_mismatch",
            "protocol_zero_failure",
            "duplicate_obvious_artifact_contract_failure",
            "population_or_metric_failure_evaluated",
            "premature_measurement_ruled_out",
            "postmortem",
            "repair_forbidden",
        },
        "successor_constraints": {
            "r19_data_role",
            "formal_r6_must_not_start_from_r19_failure",
            "successor_preregistered_in_this_audit",
            "any_successor_must_be_fully_fresh",
            "successor_requires_fresh_preregistered_revision",
            "successor_requires_fresh_root_key_public_nonces_hmac_domains_parameter_nonces_controls_references_identities_codes_commitments_labels_decisions_and_measurements",
            "r19_root_key_private_material_controls_references_pixels_identities_codes_commitments_labels_decisions_measurements_nonces_public_surfaces_and_postmortem_output_reuse_forbidden",
            "closed_r19_morphologies_tiers_metric_threshold_population_and_rate_contracts_may_not_be_changed_in_place",
            "holdout_obvious_artifact_miss_may_not_be_repaired_in_place",
            "successor_may_change_any_contract_only_under_fresh_preregistered_authority",
            "successor_may_use_only_this_sanitized_aggregate_failure_evidence",
            "successor_authority_must_be_committed_pushed_and_dual_ci_green_before_generation",
            "formal_r6_root_and_environment_must_remain_absent",
        },
        "secret_handling": {
            "blind_key_present_in_this_artifact",
            "blind_key_value_logged_or_tracked",
            "anonymous_code_to_private_identity_mapping_tracked",
            "private_labels_measurements_identities_or_pixels_tracked",
            "postmortem_raw_output_tracked",
            "development_blind_key_and_private_material_reuse_forbidden",
            "closed_development_root_reuse_forbidden",
        },
    }
    for field, keys in exact_nested_keysets.items():
        require_exact_keys(value[field], keys, f"{context}.{field}")


def validate_dev_r20_premeasurement_failure(value: Any) -> None:
    """Validate the exact sanitized dev-r20 population-gate failure evidence."""

    context = "closed dev-r20 premeasurement population failure audit"
    require_exact_keys(
        value,
        {
            "artifact",
            "schema_version",
            "authority",
            "formal_use_forbidden",
            "audit_recorded_at",
            "development_edition",
            "outcome",
            "failure_phase",
            "failure_class",
            "measurement_started",
            "selection_status",
            "development_hard_threshold",
            "calibration_endpoint_performance",
            "holdout_endpoint_performance",
            "threshold_selection_audit",
            "one_shot_contract",
            "vision_review",
            "private_audit",
            "population_audit",
            "failure_marker_summary",
            "hash_bindings",
            "absent_measurement_artifacts",
            "postmortem",
            "root_cause",
            "successor_constraints",
            "secret_handling",
        },
        context,
    )
    timestamp = value["audit_recorded_at"]
    if (
        not isinstance(timestamp, str)
        or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z", timestamp
        )
        is None
    ):
        raise RuntimeError(f"{context}.audit_recorded_at must be canonical UTC text")
    parse_utc_timestamp(timestamp, f"{context}.audit_recorded_at")
    expected_header = {
        "artifact": "microtexture-v2-r6-dev-r20-development-premeasurement-population-failure-audit",
        "schema_version": "microtexture-v2-r6-development-premeasurement-population-failure-audit/1",
        "authority": False,
        "formal_use_forbidden": True,
        "development_edition": "r20",
        "outcome": "failed_closed",
        "failure_phase": "private-audits-passed-then-premeasurement-population-audit",
        "failure_class": "both-split-tiny-speck-population-shortfall",
        "measurement_started": False,
        "selection_status": "not_started_population_gate_failed",
        "development_hard_threshold": None,
        "calibration_endpoint_performance": None,
        "holdout_endpoint_performance": None,
        "threshold_selection_audit": None,
    }
    for field, expected in expected_header.items():
        _require_exact_json_value(value[field], expected, f"{context}.{field}")
    if sha256_bytes(canonical_json_bytes(value)) != (
        DEV_R20_FAILURE_AUDIT_CANONICAL_SHA256
    ):
        raise RuntimeError(f"{context} canonical semantic digest drift")

    _require_exact_json_value(
        value["one_shot_contract"],
        {
            "generation_completed_exactly_once": True,
            "root_vision_completed_exactly_once_before_private_reveal": True,
            "independent_vision_completed_exactly_once_before_private_reveal": True,
            "all_440_records_reviewed_by_each_reviewer": True,
            "root_initial_snapshot_and_receipt_sealed_exactly_once": True,
            "independent_initial_snapshot_and_receipt_sealed_exactly_once": True,
            "root_and_independent_decisions_reconciled_exactly_once_before_preflight": True,
            "review_preflight_invoked_exactly_once": True,
            "review_preflight_passed": True,
            "labels_sealed_exactly_once_before_private_reveal": True,
            "private_reveal_started_after_label_seal": True,
            "private_audit_started_exactly_once": True,
            "private_sentinel_audit_passed": True,
            "population_audit_started_exactly_once": True,
            "population_audit_passed": False,
            "analysis_started_exactly_once": True,
            "numeric_metric_called": False,
            "threshold_search_started": False,
            "development_threshold_selected": False,
            "postmortem_invoked_exactly_once": True,
            "formal_cli_invoked": False,
            "formal_marker_created": False,
            "formal_threshold_created": False,
            "locked_clean_v18_decoded_or_measured": False,
            "failure_marker_created": True,
            "rerun_resume_relabel_retune_subset_topup_resample_or_reuse_for_r20_forbidden": True,
            "r20_closed": True,
        },
        f"{context}.one_shot_contract",
    )

    vision = value["vision_review"]
    require_exact_keys(
        vision,
        {
            "records_per_split_per_reviewer",
            "review_boards_per_split_per_reviewer",
            "logical_comparison_fields",
            "evidence_notes_excluded_from_logical_comparison",
            "initial_snapshots_persisted_immutably",
            "initial_snapshots_official_decision_dsl_conformant",
            "initial_snapshot_receipts_verified",
            "splits",
            "all_differences_reinspected_native_then_evidence",
            "final_reconciled",
            "canonical_labels_equal_both_reviewers",
            "total_initial_logical_and_notes_only_difference_count",
            "initial_snapshots_and_receipts_preserved_after_reconciliation",
            "bilateral_initial_visible_flag_intersection_gate",
        },
        f"{context}.vision_review",
    )
    expected_review_keys = {
        "root_initial_decisions_sha256",
        "root_initial_receipt_sha256",
        "independent_initial_decisions_sha256",
        "independent_initial_receipt_sha256",
        "initial_exact_logical_agreement",
        "initial_logical_difference_count",
        "initial_notes_only_difference_count",
        "all_differences_reinspected_native_then_evidence",
        "reconciled",
        "root_final_decisions_sha256",
        "independent_final_decisions_sha256",
        "canonical_final_decisions_sha256",
        "completed_labels_sha256",
        "record_dispositions",
        "reconciled_final_official_parser_and_ev3_passed",
        "final_visible_flags_subset_of_both_initial_flag_sets",
    }
    expected_review_summary = {
        "calibration": {
            "differences": (78, 42),
            "final_sha256": (
                "5b8b74d8059c240b2b32b62c849e93793967334bb62dae82193fc1ac7ceb362b"
            ),
            "completed_labels_sha256": (
                "77cc8209f5e2d2ce7ea7806bca9cdcadbdbbba96fb01467edf073f963f1eb559"
            ),
            "record_dispositions": {"clean": 88, "warning": 46, "reject": 86},
        },
        "holdout": {
            "differences": (63, 81),
            "final_sha256": (
                "1f266a23f9086011db14e5ad47be75ae9e516fcd4007a3a587dd2ed3c6c365c0"
            ),
            "completed_labels_sha256": (
                "7fbbf24d9942c7eef184181a0480cb60ae36ebb63e1d5fa5fd6b61e2184514bd"
            ),
            "record_dispositions": {"clean": 70, "warning": 54, "reject": 96},
        },
    }
    if set(vision["splits"]) != set(expected_review_summary):
        raise RuntimeError(f"{context} Vision split coverage drift")
    total_differences = 0
    for split, expected in expected_review_summary.items():
        review = vision["splits"][split]
        require_exact_keys(review, expected_review_keys, f"{context}.vision.{split}")
        require_exact_keys(
            review["record_dispositions"],
            {"clean", "warning", "reject"},
            f"{context}.vision.{split}.record_dispositions",
        )
        hash_fields = {field for field in review if field.endswith("_sha256")}
        if any(
            not isinstance(review[field], str)
            or re.fullmatch(r"[0-9a-f]{64}", review[field]) is None
            for field in hash_fields
        ):
            raise RuntimeError(f"{context}.{split} Vision SHA-256 binding drift")
        logical, notes_only = expected["differences"]
        final_sha = expected["final_sha256"]
        if (
            review["initial_exact_logical_agreement"] is not False
            or review["initial_logical_difference_count"] != logical
            or review["initial_notes_only_difference_count"] != notes_only
            or review["all_differences_reinspected_native_then_evidence"] is not True
            or review["reconciled"] is not True
            or review["root_final_decisions_sha256"] != final_sha
            or review["independent_final_decisions_sha256"] != final_sha
            or review["canonical_final_decisions_sha256"] != final_sha
            or review["completed_labels_sha256"]
            != expected["completed_labels_sha256"]
            or review["record_dispositions"] != expected["record_dispositions"]
            or sum(review["record_dispositions"].values()) != 220
            or review["reconciled_final_official_parser_and_ev3_passed"] is not True
            or review["final_visible_flags_subset_of_both_initial_flag_sets"]
            is not True
        ):
            raise RuntimeError(f"{context}.{split} reconciliation contract drift")
        total_differences += logical + notes_only
    if (
        vision["records_per_split_per_reviewer"] != 220
        or vision["review_boards_per_split_per_reviewer"] != 37
        or vision["logical_comparison_fields"]
        != ["page", "row", "anonymous_code", "disposition", "severity", "flags"]
        or vision["evidence_notes_excluded_from_logical_comparison"] is not True
        or vision["initial_snapshots_persisted_immutably"] is not True
        or vision["initial_snapshots_official_decision_dsl_conformant"] is not True
        or vision["initial_snapshot_receipts_verified"] is not True
        or vision["all_differences_reinspected_native_then_evidence"] is not True
        or vision["final_reconciled"] is not True
        or vision["canonical_labels_equal_both_reviewers"] is not True
        or total_differences != 264
        or vision["total_initial_logical_and_notes_only_difference_count"] != 264
        or vision[
            "initial_snapshots_and_receipts_preserved_after_reconciliation"
        ]
        is not True
    ):
        raise RuntimeError(f"{context} Vision review contract drift")
    _require_exact_json_value(
        vision["bilateral_initial_visible_flag_intersection_gate"],
        {
            "revision": "dev-r17-bilateral-initial-visible-flag-intersection-gate-v1",
            "manifest_sha256": "f042250290f80d4304923e3b564746e8311515f5c649811678db934bb3ad6ffd",
            "both_official_initial_snapshots_and_receipts_required": True,
            "final_visible_flag_set_relation": "subset-of-root-initial-intersection-independent-initial",
            "private_role_input": False,
            "passed": True,
        },
        f"{context}.vision_review.bilateral_initial_visible_flag_intersection_gate",
    )

    _require_exact_json_value(
        value["private_audit"],
        {
            "all_splits_passed": True,
            "anonymous_code_page_row_private_identity_or_pixel_binding_tracked": False,
            "splits": {
                split: {
                    "record_count": 220,
                    "artifact_record_count": 200,
                    "protocol_zero_record_count": 16,
                    "duplicate_audit_record_count": 4,
                    "contact_sheet_count": 185,
                    "review_board_count": 37,
                    "regenerated_public_commitments_matched": True,
                    "regenerated_contact_sheet_bytes_matched": True,
                    "regenerated_review_board_bytes_matched": True,
                    "protocol_zero_audit_passed": True,
                    "duplicate_audit_passed": True,
                }
                for split in ("calibration", "holdout")
            },
        },
        f"{context}.private_audit",
    )

    population_counts = {
        "calibration": [26, 30, 44, 38, 11, 0, 10, 10, 23, 12],
        "holdout": [21, 30, 49, 40, 12, 1, 12, 13, 24, 14],
    }
    formal_minima = [15, 10, 30, 4, 8, 4, 4, 8, 8, 6]
    development_floors = [19, 13, 38, 6, 10, 6, 6, 10, 10, 8]
    expected_population_splits: dict[str, Any] = {}
    for split, counts in population_counts.items():
        formal = {
            endpoint_id: {
                "unique_cluster_count": counts[index],
                "minimum_unique_clusters": formal_minima[index],
                "count_passed": counts[index] >= formal_minima[index],
            }
            for index, endpoint_id in enumerate(EXPECTED_ENDPOINT_IDS)
        }
        development = {
            endpoint_id: {
                "unique_cluster_count": counts[index],
                "development_minimum_unique_clusters": development_floors[index],
                "count_passed": counts[index] >= development_floors[index],
            }
            for index, endpoint_id in enumerate(EXPECTED_ENDPOINT_IDS)
        }
        formal_passed = all(endpoint["count_passed"] for endpoint in formal.values())
        development_passed = all(
            endpoint["count_passed"] for endpoint in development.values()
        )
        expected_population_splits[split] = {
            "split": split,
            "condition_cluster_count": 100,
            "all_eligible_clusters_exact_polarity_pairs": True,
            "formal_endpoint_minimums": formal,
            "formal_endpoint_minimums_passed": formal_passed,
            "development_safety_floors": development,
            "development_safety_floors_passed": development_passed,
            "passed": formal_passed and development_passed,
        }
    _require_exact_json_value(
        value["population_audit"],
        {
            "eligible_artifact_condition_clusters_per_split": 100,
            "all_eligible_artifact_condition_clusters_exact_polarity_pairs": True,
            "splits": expected_population_splits,
            "passed": False,
        },
        f"{context}.population_audit",
    )

    _require_exact_json_value(
        value["failure_marker_summary"],
        {
            "artifact": "microtexture-v2-r6-development-analysis-failure",
            "schema_version": "microtexture-v2-r6-development-analysis-failure/1",
            "authority": False,
            "formal_use_forbidden": True,
            "development_edition": "r20",
            "development_closed": True,
            "measurement_started": False,
            "error_type": "RuntimeError",
            "message": "development endpoint population premeasurement audit failed",
        },
        f"{context}.failure_marker_summary",
    )
    expected_hash_bindings = {
        "captured_repository_head": "9c5849406a378ab280e2ea0817810078cb4ec791",
        "preregistered_spec_sha256": "7bf147420b6baed542c05da97591fcc28c357436e312fb2275845153edd56fbf",
        "implementation_bindings_sha256": "ee1c86a94cf0d393afc55b68405c1dd51f98cb4a01942eac679799d40b1ce923",
        "development_authority_manifest_sha256": "584deb41c74d8beeff030c33f1ed0116c4e583c9c60a41e010fb6233972b05a2",
        "dev_r19_failure_audit_sha256": "96d93fe63be2ff6171ade926dbace188b6fd5eacf748a6f03a787781a5d248d0",
        "development_boundary_sha256": "09ce5502e5f437382314c1cd5370e21614b56d1d0e11b52120aadacdb68b7bc5",
        "generation_start_sha256": "6da4c328ff76bf5000014559a9fac009f9de5e95dfae90a75d07557e019e211e",
        "generation_summary_sha256": "9d8499b0c71eef1a346c0c1fddbb30ba4d66ede7e8f41017aa5aa2502da473fa",
        "generation_seal_sha256": "ce5cd42f49a244bb24f297a86913ad66584faf8a74599cc3697c9a737bbe5dd8",
        "generation_completion_sha256": "b806e15b7e0336f37ff4bb0db2d4dd1e3e8209617fcaec857482f3fa5301cbc6",
        "blind_key_commitment": "5ebfccbed8cbed2b72ab5bbf4dd853315a2a35f093b8a1e3a8b3446d4a2f7e1a",
        "calibration_manifest_sha256": "240eb30274cd79fc746a4c8db261f9f137f58b62f158e57da85b0c2a5eff2aae",
        "calibration_blank_labels_sha256": "fc2b602f87b2ef6c39f925509ff10f8809094380c3998d086c130554d178bc9d",
        "calibration_review_index_sha256": "73ce760b07579205932bdb2f97f810b3fd93c051a69ade3770b1ab819cc592cc",
        "holdout_manifest_sha256": "c39f52a6c822b5d65ddd9ae7f695b23e2e360b6aaa8f7e0c17c0e1a10645fe71",
        "holdout_blank_labels_sha256": "ce7ecd44e80422b5085bdb51d466b52bd99bd80379a256d07538baa0b616fabb",
        "holdout_review_index_sha256": "b621373828b18b41c0543df9db348c3ae290dc741b7fd55c309d519cddf6b9b8",
        "label_seal_receipt_sha256": "035102d8de09f9a294aadf830a85927c85f5ab592fa0cc2da9bf8107258e018c",
        "population_audit_sha256": "b11dd5fb4920048c83b3f96761480f05735641ed05025586ec753ad2f7364f26",
        "failure_marker_sha256": "ea39ba6ac301fe7bd7c914fd21ec2a8e39e1a1faa43268b1a4c7df0ba0642bd4",
    }
    _require_exact_json_value(
        value["hash_bindings"], expected_hash_bindings, f"{context}.hash_bindings"
    )
    for field, digest in value["hash_bindings"].items():
        expected_length = 40 if field == "captured_repository_head" else 64
        if not isinstance(digest, str) or re.fullmatch(
            rf"[0-9a-f]{{{expected_length}}}", digest
        ) is None:
            raise RuntimeError(f"{context} malformed hash binding: {field}")

    _require_exact_json_value(
        value["absent_measurement_artifacts"],
        {
            "calibration_measurements_present": False,
            "holdout_measurements_present": False,
            "analysis_result_present": False,
            "threshold_selection_result_present": False,
            "holdout_endpoint_result_present": False,
        },
        f"{context}.absent_measurement_artifacts",
    )
    _require_exact_json_value(
        value["postmortem"],
        {
            "invoked_exactly_once": True,
            "read_only": True,
            "raw_output_tracked": False,
            "sanitized_aggregate_only_in_this_audit": True,
            "anonymous_code_to_private_identity_mapping_tracked": False,
            "used_to_relabel_resample_subset_topup_retune_or_select_a_threshold": False,
        },
        f"{context}.postmortem",
    )
    _require_exact_json_value(
        value["root_cause"],
        {
            "generation_or_runtime_failure": False,
            "decision_reconciliation_failure": False,
            "private_audit_failure": False,
            "population_feasibility": "Calibration tiny-speck reject population 0 and holdout tiny-speck reject population 1 each missed formal minimum 4 and development floor 6; every other endpoint in both splits passed both minima.",
            "premature_measurement_ruled_out": "The edition closed at the premeasurement population gate before the first numeric metric; no score, candidate threshold, selected threshold, or holdout endpoint result exists.",
            "postmortem": "One read-only invocation confirmed only the sanitized aggregate cause and supplied no raw output, code, page, row, locator, private identity mapping, repair, or tuning.",
            "repair_forbidden": "The sealed dev-r20 edition cannot be repaired by relabeling, rerunning, resuming, replacing, subsetting, topping up, resampling the key, regenerating, retuning, or reusing any dev-r20 material.",
        },
        f"{context}.root_cause",
    )
    _require_exact_json_value(
        value["successor_constraints"],
        {
            "r20_data_role": "development_only_premeasurement_population_failure_evidence",
            "formal_r6_must_not_start_from_r20_failure": True,
            "successor_preregistered_in_this_audit": False,
            "any_successor_must_be_fully_fresh": True,
            "successor_requires_fresh_preregistered_revision": True,
            "successor_requires_fresh_root_key_public_nonces_hmac_domains_parameter_nonces_controls_references_identities_codes_commitments_labels_decisions_and_measurements": True,
            "r20_root_key_private_material_controls_references_pixels_identities_codes_commitments_labels_decisions_measurements_nonces_public_surfaces_and_postmortem_output_reuse_forbidden": True,
            "formal_endpoint_population_and_rate_minima_must_not_be_weakened": True,
            "development_safety_floors_must_not_be_weakened": True,
            "formal_and_development_minima_must_remain_unchanged": True,
            "successor_may_use_only_this_sanitized_aggregate_failure_evidence": True,
            "successor_authority_must_be_committed_pushed_and_dual_ci_green_before_generation": True,
            "formal_r6_root_and_environment_must_remain_absent": True,
        },
        f"{context}.successor_constraints",
    )
    _require_exact_json_value(
        value["secret_handling"],
        {
            "blind_key_present_in_this_artifact": False,
            "blind_key_value_logged_or_tracked": False,
            "anonymous_code_to_private_identity_mapping_tracked": False,
            "private_labels_measurements_identities_or_pixels_tracked": False,
            "postmortem_raw_output_tracked": False,
            "development_blind_key_and_private_material_reuse_forbidden": True,
            "closed_development_root_reuse_forbidden": True,
        },
        f"{context}.secret_handling",
    )


def _verify_tracked_dev_r20_failure_audit(
    repository: Path, captured_head: str, spec: dict[str, Any]
) -> bytes:
    """Bind the retired dev-r20 status to its exact tracked sanitized audit."""

    history = spec.get("history")
    if not isinstance(history, dict) or (
        history.get("dev_r20_status") != DEV_R20_CLOSED_STATUS
        or history.get("dev_r20_role") != DEV_R20_CLOSED_ROLE
        or history.get("dev_r20_failure_audit") != DEV_R20_FAILURE_AUDIT_REL
        or history.get("dev_r20_failure_audit_sha256")
        != DEV_R20_FAILURE_AUDIT_RAW_SHA256
    ):
        raise RuntimeError("closed dev-r20 failure audit history binding drift")
    payload = _tracked_worktree_bytes(
        repository, captured_head, DEV_R20_FAILURE_AUDIT_REL
    )
    if sha256_bytes(payload) != DEV_R20_FAILURE_AUDIT_RAW_SHA256:
        raise RuntimeError("closed dev-r20 failure audit tracked SHA drift")
    validate_dev_r20_premeasurement_failure(json.loads(payload.decode("utf-8")))
    return payload


def verify_tracked_development_history(
    repository: Path, captured_head: str, spec: dict[str, Any]
) -> bytes:
    """Bind every closed development audit through retired dev-r20."""

    history = spec["history"]
    relative = history["dev_r7_failure_audit"]
    dev_r7_payload = _tracked_worktree_bytes(repository, captured_head, relative)
    if sha256_bytes(dev_r7_payload) != history["dev_r7_failure_audit_sha256"]:
        raise RuntimeError("closed dev-r7 failure audit tracked SHA drift")
    value = json.loads(dev_r7_payload.decode("utf-8"))
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

    relative = history["dev_r8_failure_audit"]
    dev_r8_payload = _tracked_worktree_bytes(repository, captured_head, relative)
    if sha256_bytes(dev_r8_payload) != history["dev_r8_failure_audit_sha256"]:
        raise RuntimeError("closed dev-r8 failure audit tracked SHA drift")
    validate_dev_r8_failure_audit(json.loads(dev_r8_payload.decode("utf-8")))

    relative = history["dev_r9_failure_audit"]
    dev_r9_payload = _tracked_worktree_bytes(repository, captured_head, relative)
    if sha256_bytes(dev_r9_payload) != history["dev_r9_failure_audit_sha256"]:
        raise RuntimeError("closed dev-r9 failure audit tracked SHA drift")
    validate_dev_r9_failure_audit(json.loads(dev_r9_payload.decode("utf-8")))

    relative = history["dev_r10_failure_audit"]
    dev_r10_payload = _tracked_worktree_bytes(repository, captured_head, relative)
    if sha256_bytes(dev_r10_payload) != history["dev_r10_failure_audit_sha256"]:
        raise RuntimeError("closed dev-r10 failure audit tracked SHA drift")
    validate_dev_r10_generation_failure_audit(
        json.loads(dev_r10_payload.decode("utf-8"))
    )

    relative = history["dev_r11_failure_audit"]
    dev_r11_payload = _tracked_worktree_bytes(repository, captured_head, relative)
    if sha256_bytes(dev_r11_payload) != history["dev_r11_failure_audit_sha256"]:
        raise RuntimeError("closed dev-r11 failure audit tracked SHA drift")
    validate_dev_r11_premeasurement_failure_audit(
        json.loads(dev_r11_payload.decode("utf-8"))
    )

    relative = history["dev_r12_failure_audit"]
    dev_r12_payload = _tracked_worktree_bytes(repository, captured_head, relative)
    if sha256_bytes(dev_r12_payload) != history["dev_r12_failure_audit_sha256"]:
        raise RuntimeError("closed dev-r12 failure audit tracked SHA drift")
    validate_dev_r12_premeasurement_population_failure_audit(
        json.loads(dev_r12_payload.decode("utf-8"))
    )

    relative = history["dev_r13_failure_audit"]
    dev_r13_payload = _tracked_worktree_bytes(repository, captured_head, relative)
    if sha256_bytes(dev_r13_payload) != history["dev_r13_failure_audit_sha256"]:
        raise RuntimeError("closed dev-r13 failure audit tracked SHA drift")
    validate_dev_r13_premeasurement_population_failure_audit(
        json.loads(dev_r13_payload.decode("utf-8"))
    )

    relative = history["dev_r14_failure_audit"]
    dev_r14_payload = _tracked_worktree_bytes(repository, captured_head, relative)
    if sha256_bytes(dev_r14_payload) != history["dev_r14_failure_audit_sha256"]:
        raise RuntimeError("closed dev-r14 failure audit tracked SHA drift")
    validate_dev_r14_premeasurement_population_failure_audit(
        json.loads(dev_r14_payload.decode("utf-8"))
    )

    relative = history["dev_r15_failure_audit"]
    dev_r15_payload = _tracked_worktree_bytes(repository, captured_head, relative)
    if sha256_bytes(dev_r15_payload) != history["dev_r15_failure_audit_sha256"]:
        raise RuntimeError("closed dev-r15 failure audit tracked SHA drift")
    validate_dev_r15_premeasurement_population_failure_audit(
        json.loads(dev_r15_payload.decode("utf-8"))
    )

    relative = history["dev_r16_failure_audit"]
    dev_r16_payload = _tracked_worktree_bytes(repository, captured_head, relative)
    if sha256_bytes(dev_r16_payload) != history["dev_r16_failure_audit_sha256"]:
        raise RuntimeError("closed dev-r16 failure audit tracked SHA drift")
    validate_dev_r16_premeasurement_failure_audit(
        json.loads(dev_r16_payload.decode("utf-8"))
    )

    relative = history["dev_r17_failure_audit"]
    dev_r17_payload = _tracked_worktree_bytes(repository, captured_head, relative)
    if sha256_bytes(dev_r17_payload) != history["dev_r17_failure_audit_sha256"]:
        raise RuntimeError("closed dev-r17 failure audit tracked SHA drift")
    validate_dev_r17_premeasurement_population_failure_audit(
        json.loads(dev_r17_payload.decode("utf-8"))
    )

    relative = history["dev_r18_failure_audit"]
    dev_r18_payload = _tracked_worktree_bytes(repository, captured_head, relative)
    if sha256_bytes(dev_r18_payload) != history["dev_r18_failure_audit_sha256"]:
        raise RuntimeError("closed dev-r18 failure audit tracked SHA drift")
    validate_dev_r18_premeasurement_private_audit_failure(
        json.loads(dev_r18_payload.decode("utf-8"))
    )

    expected_dev_r19_role = (
        "development-only prepopulation private-audit failure evidence; generation, "
        "both blind 440-record reviews, bilateral reconciliation, official preflight, "
        "label sealing, private reveal, regeneration, and protocol-zero audits each "
        "completed exactly once, calibration clean and obvious-artifact duplicate "
        "groups plus the holdout clean duplicate group passed, but holdout's "
        "obvious-artifact duplicate pair was clean severity 0 with no visible flags, "
        "so the required rejected short-line artifact contract failed before "
        "population audit or any numeric measurement; one read-only postmortem ran "
        "exactly once, all initial snapshots and receipts remain immutable, and no "
        "dev-r19 root, key, private material, control, reference, pixel, identity, "
        "code, commitment, label, decision, measurement, nonce, public surface, or "
        "postmortem output is reusable"
    )
    if (
        history.get("dev_r19_status")
        != "failed-and-closed-before-population-audit"
        or history.get("dev_r19_role") != expected_dev_r19_role
        or history.get("dev_r19_failure_audit")
        != "world/map-production/qa/microtexture-v2-r6-dev-r19-development-failure.json"
        or history.get("dev_r19_failure_audit_sha256")
        != "96d93fe63be2ff6171ade926dbace188b6fd5eacf748a6f03a787781a5d248d0"
    ):
        raise RuntimeError("closed dev-r19 failure audit history binding drift")
    relative = history["dev_r19_failure_audit"]
    dev_r19_payload = _tracked_worktree_bytes(repository, captured_head, relative)
    if sha256_bytes(dev_r19_payload) != history["dev_r19_failure_audit_sha256"]:
        raise RuntimeError("closed dev-r19 failure audit tracked SHA drift")
    validate_dev_r19_premeasurement_private_audit_failure(
        json.loads(dev_r19_payload.decode("utf-8"))
    )

    _verify_tracked_dev_r20_failure_audit(repository, captured_head, spec)

    # Preserve the historical return contract; callers use this function for its
    # fail-closed checks, but earlier code returned the dev-r7 payload.
    return dev_r7_payload


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


def _reject_closed_dev_r20_formal_operation() -> None:
    """Validate retirement evidence, then reject before formal root/key/env access."""

    spec = load_spec()
    # This path is derived from the tracked code location; do not consult the formal
    # artifact-root environment (or any blind-key source) on the retirement path.
    repository = CODE_ROOT.parents[2]
    captured_head = _git(CODE_ROOT, "rev-parse", "HEAD").decode().strip()
    _verify_tracked_dev_r20_failure_audit(repository, captured_head, spec)
    assert_head_unchanged(captured_head)
    raise RuntimeError(
        "formal r6 operation is blocked: dev-r20 failed and closed before measurement; "
        "no closed development material can authorize a formal run"
    )


def operation_preflight(
    *, require_receipt: bool, include_locked_clean_reference: bool = False
) -> dict[str, Any]:
    _reject_closed_dev_r20_formal_operation()
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

    def duplicate_semantic_signature(label: dict[str, Any]) -> tuple[Any, ...]:
        disposition = label["disposition"]
        severity = label["severity_0_to_3"]
        severity_equivalence: int | str = severity
        if disposition == "reject" and severity in {2, 3}:
            severity_equivalence = "reject-ordinal-band-2-or-3"
        return (
            disposition,
            severity_equivalence,
            *(label[field] for field in visible_fields),
        )

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
        signatures = {duplicate_semantic_signature(labels[code]) for code in codes}
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
