from __future__ import annotations

import argparse
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import subprocess
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[3]
CODE_ROOT = REPO_ROOT / "scripts" / "map-production" / "microtexture-v2-r6"
DEV_ROOT = REPO_ROOT / "tmp" / "map-production" / "microtexture-v2-r6-dev-r20"
FORMAL_ROOT = REPO_ROOT / "tmp" / "map-production" / "microtexture-v2-r6-artifacts"
PRIVATE_ANALYSIS_ROOT = DEV_ROOT / "private" / "analysis"
FORMAL_ENVIRONMENT = (
    "MICROTEXTURE_V2_R6_BLIND_KEY",
    "MICROTEXTURE_V2_R6_ARTIFACT_ROOT",
)
DEVELOPMENT_EDITION = "r20"
EXPECTED_RECORDS_PER_SPLIT = 220
EXPECTED_ARTIFACT_RECORDS_PER_SPLIT = 200
EXPECTED_ARTIFACT_CLUSTERS_PER_SPLIT = 100
EXPECTED_REVIEW_PAGES_PER_SPLIT = 37
EXPECTED_CONTACT_SHEETS_PER_SPLIT = 185
REVIEW_ROWS_PER_PAGE = 6
REVIEW_HEADER_HEIGHT = 30
REVIEW_PANEL_WIDTH = 512
REVIEW_PANEL_HEIGHT = 384
REVIEW_ROW_HEIGHT = REVIEW_HEADER_HEIGHT + REVIEW_PANEL_HEIGHT
DEVELOPMENT_POPULATION_FLOORS = {
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
}
_R17_PUBLIC_NONCES = {
    "calibration": "r6-calibration-v12",
    "holdout": "r6-holdout-v12",
}
_R17_PRIVATE_IDENTITY_DOMAINS = {
    "private_reference_transform_prefix": "private-reference-transform-v12/",
    "foundation_offset_lane": "foundation-offset-v11",
    "foundation_assignment_lane": "foundation-assignment-v11",
    "delta_lane": "delta-v11",
    "private_control_id_prefix": "microtexture-v2-r6/private-control-id/v11/",
}
_R17_PARAMETER_NONCE_BASES = {
    "calibration_artifact": 973000,
    "holdout_artifact": 983000,
    "calibration_protocol_zero": 951000,
    "holdout_protocol_zero": 961000,
    "calibration_duplicate_audit": [991000, 991001, 991002],
    "holdout_duplicate_audit": [1001000, 1001001, 1001002],
}
_R17_SCHEDULE_REVISION = "dev-r17-protocol-zero-reference-prequalification-schedule-v1"
_R18_PUBLIC_NONCES = {
    "calibration": "r6-calibration-v13",
    "holdout": "r6-holdout-v13",
}
_R18_PRIVATE_IDENTITY_DOMAINS = {
    "private_reference_transform_prefix": "private-reference-transform-v13/",
    "foundation_offset_lane": "foundation-offset-v12",
    "foundation_assignment_lane": "foundation-assignment-v12",
    "delta_lane": "delta-v12",
    "private_control_id_prefix": "microtexture-v2-r6/private-control-id/v12/",
}
_R18_PARAMETER_NONCE_BASES = {
    "calibration_artifact": 1073000,
    "holdout_artifact": 1083000,
    "calibration_protocol_zero": 1051000,
    "holdout_protocol_zero": 1061000,
    "calibration_duplicate_audit": [1091000, 1091001, 1091002],
    "holdout_duplicate_audit": [1101000, 1101001, 1101002],
}
_R18_SCHEDULE_REVISION = (
    "dev-r18-symmetric-direct-visible-speck-reinforcement-schedule-v1"
)
_R18_SPECK_REINFORCEMENT_REVISION = (
    "dev-r18-symmetric-reject-speck-direct-visible-cross-v1"
)
_R18_CLUSTER_PREFIX = "microtexture-v2-r6/private-condition-cluster/v13/"
_R18_KEY_COMMITMENT_MESSAGE = "microtexture-v2-r6/key-commitment/v12"
_R18_SEED_MESSAGE_PREFIX = "microtexture-v2-r6/render-seed/v13/"
_R18_CODE_MESSAGE_PREFIX = "microtexture-v2-r6/opaque-code/v13/"
_R18_PUBLIC_COMMITMENT_DOMAIN = (
    "microtexture-v2-r6/public-payload-commitment/v14/"
    "{control|reference|delta}/{anonymous_code}/{raw-sha256-bytes}"
)
_R18_ZERO_KEY_COMMITMENT_TEST_VECTOR = (
    "794a520cf9bfe76ec1aa1c49767a2dee701f3cd91e06c73f511e18c6ef9bc651"
)
_R19_PUBLIC_NONCES = {
    "calibration": "r6-calibration-v14",
    "holdout": "r6-holdout-v14",
}
_R19_PRIVATE_IDENTITY_DOMAINS = {
    "private_reference_transform_prefix": "private-reference-transform-v14/",
    "foundation_offset_lane": "foundation-offset-v13",
    "foundation_assignment_lane": "foundation-assignment-v13",
    "delta_lane": "delta-v13",
    "private_control_id_prefix": "microtexture-v2-r6/private-control-id/v13/",
}
_R19_PARAMETER_NONCE_BASES = {
    "calibration_artifact": 1173000,
    "holdout_artifact": 1183000,
    "calibration_protocol_zero": 1151000,
    "holdout_protocol_zero": 1161000,
    "calibration_duplicate_audit": [1191000, 1191001, 1191002],
    "holdout_duplicate_audit": [1201000, 1201001, 1201002],
}
_R19_SCHEDULE_REVISION = (
    "dev-r19-duplicate-reject-severity-band-equivalence-schedule-v1"
)
_R19_DUPLICATE_EQUIVALENCE_POLICY_REVISION = (
    "dev-r19-reject-ordinal-band-duplicate-equivalence-v1"
)
_R19_CLUSTER_PREFIX = "microtexture-v2-r6/private-condition-cluster/v14/"
_R19_KEY_COMMITMENT_MESSAGE = "microtexture-v2-r6/key-commitment/v13"
_R19_SEED_MESSAGE_PREFIX = "microtexture-v2-r6/render-seed/v14/"
_R19_CODE_MESSAGE_PREFIX = "microtexture-v2-r6/opaque-code/v14/"
_R19_PUBLIC_COMMITMENT_DOMAIN = (
    "microtexture-v2-r6/public-payload-commitment/v15/"
    "{control|reference|delta}/{anonymous_code}/{raw-sha256-bytes}"
)
_R19_ZERO_KEY_COMMITMENT_TEST_VECTOR = (
    "0ab9d139a2990f058a140474942a85fdab47eb8d6ad3959bcb845da54aa16498"
)
_R20_PUBLIC_NONCES = {
    "calibration": "r6-calibration-v15",
    "holdout": "r6-holdout-v15",
}
_R20_PRIVATE_IDENTITY_DOMAINS = {
    "private_reference_transform_prefix": "private-reference-transform-v15/",
    "foundation_offset_lane": "foundation-offset-v14",
    "foundation_assignment_lane": "foundation-assignment-v14",
    "delta_lane": "delta-v14",
    "private_control_id_prefix": "microtexture-v2-r6/private-control-id/v14/",
}
_R20_PARAMETER_NONCE_BASES = {
    "calibration_artifact": 1273000,
    "holdout_artifact": 1283000,
    "calibration_protocol_zero": 1251000,
    "holdout_protocol_zero": 1261000,
    "calibration_duplicate_audit": [1291000, 1291001, 1291002],
    "holdout_duplicate_audit": [1301000, 1301001, 1301002],
}
_R20_SCHEDULE_REVISION = (
    "dev-r20-strong-finite-duplicate-short-line-sentinel-schedule-v1"
)
_R20_DUPLICATE_SENTINEL_REVISION = (
    "dev-r20-keyed-axial-short-line-duplicate-sentinel-v1"
)
_R20_CLUSTER_PREFIX = "microtexture-v2-r6/private-condition-cluster/v15/"
_R20_KEY_COMMITMENT_MESSAGE = "microtexture-v2-r6/key-commitment/v14"
_R20_SEED_MESSAGE_PREFIX = "microtexture-v2-r6/render-seed/v15/"
_R20_CODE_MESSAGE_PREFIX = "microtexture-v2-r6/opaque-code/v15/"
_R20_PUBLIC_COMMITMENT_DOMAIN = (
    "microtexture-v2-r6/public-payload-commitment/v16/"
    "{control|reference|delta}/{anonymous_code}/{raw-sha256-bytes}"
)
_R20_ZERO_KEY_COMMITMENT_TEST_VECTOR = (
    "5c182b83ea230ab3f3fc19f26fcf3369f41d40cef5a50cbc8cf9f072d37d6383"
)
_R17_REFERENCE_PREQUALIFICATION_REVISION = (
    "dev-r17-role-agnostic-private-reference-coefficient-prequalification-v1"
)
_R17_REFERENCE_PREQUALIFICATION_MANIFEST = {
    "revision": _R17_REFERENCE_PREQUALIFICATION_REVISION,
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
}
_R17_REFERENCE_PREQUALIFICATION_MANIFEST_SHA256 = (
    "a3cfdec84b58bebec38f581c03fbe9947975bf93e11741477cd3bb22f0931119"
)
_R17_PRESERVED_R16_ARTIFACT_MORPHOLOGY_SHA256 = (
    "c60917c79ae36278d17cc7ccaa93d798cac17500d2d678b41b0cdea34ff66b30"
)
_R17_INITIAL_DECISION_GATE_REVISION = (
    "dev-r17-bilateral-initial-visible-flag-intersection-gate-v1"
)
_R17_INITIAL_DECISION_GATE_MANIFEST = {
    "revision": _R17_INITIAL_DECISION_GATE_REVISION,
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
}
_R17_INITIAL_DECISION_GATE_MANIFEST_SHA256 = (
    "f042250290f80d4304923e3b564746e8311515f5c649811678db934bb3ad6ffd"
)
_R18_CATALOG_AUTHORITY = {
    "schedule_revision": _R18_SCHEDULE_REVISION,
    "public_payload_commitment_prefix": (
        "microtexture-v2-r6/public-payload-commitment/v14/"
    ),
    "private_reference_transform_prefix": "private-reference-transform-v13/",
    "foundation_offset_lane": "foundation-offset-v12",
    "foundation_assignment_lane": "foundation-assignment-v12",
    "delta_lane": "delta-v12",
    "private_control_id_prefix": "microtexture-v2-r6/private-control-id/v12/",
    "artifact_nonce_bases": {"calibration": 1073000, "holdout": 1083000},
    "protocol_zero_nonce_bases": {"calibration": 1051000, "holdout": 1061000},
    "duplicate_audit_nonces": {
        "calibration": [1091000, 1091001, 1091002],
        "holdout": [1101000, 1101001, 1101002],
    },
    "speck_reinforcement_revision": _R18_SPECK_REINFORCEMENT_REVISION,
    "speck_reinforcement_manifest_sha256": (
        "355c6c588c3d698288a3545752c13cea734db85e1e7a9a95416cbe3163f633d4"
    ),
    "full_artifact_morphology_sha256": (
        "9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365"
    ),
    "preserved_r17_morphology_sha256": (
        "03559cb9f26908f6ed59bd8327250c5d63e77e6e96c34d7f08a47e8cb59a7fdf"
    ),
}
_R18_SANITIZED_R17_BASIS = {
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
}
_R18_SANITIZED_R17_BASIS_SHA256 = (
    "88860fea0dbdf5ebfa454bf7f038aae53c957808d4c4d344b1ea0fc8e54042e9"
)
_R18_PER_FAMILY_RESIDUE_ROTATION = {
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
}
_R18_SPECK_REJECT_ANCHOR_SCHEDULE = {
    "revision": _R18_SPECK_REINFORCEMENT_REVISION,
    "inherited_schedule_revision": _R17_SCHEDULE_REVISION,
    "family": "artifact-speck",
    "target_tiers": ["clear-reject-candidate", "dominant-reject-candidate"],
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
}
_R18_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES = {
    "revision": _R18_SCHEDULE_REVISION,
    "fresh_from_closed_dev_r17": True,
    "r17_parameter_nonce_reuse_forbidden": True,
    "r18_per_family_residue_rotation": _R18_PER_FAMILY_RESIDUE_ROTATION,
    "r18_parameter_nonce_bases": _R18_PARAMETER_NONCE_BASES,
    "inherited_r17_schedule_revision": _R17_SCHEDULE_REVISION,
    "preserved_r17_artifact_morphology_conditions_across_splits": 180,
    "preserved_r17_artifact_morphology_sha256": (
        _R18_CATALOG_AUTHORITY["preserved_r17_morphology_sha256"]
    ),
    "r18_exact_morphology_change_count_across_splits": 20,
    "r18_speck_reinforcement_revision": _R18_SPECK_REINFORCEMENT_REVISION,
    "r18_speck_reinforcement_manifest_sha256": (
        _R18_CATALOG_AUTHORITY["speck_reinforcement_manifest_sha256"]
    ),
    "r18_full_artifact_morphology_sha256": (
        _R18_CATALOG_AUTHORITY["full_artifact_morphology_sha256"]
    ),
    "r18_target_speck_conditions_per_split": 10,
    "r18_target_speck_tiers_per_split": {
        "clear-reject-candidate": 6,
        "dominant-reject-candidate": 4,
    },
    "r18_tiny_speck_structural_miss_budget": 4,
    "r18_spot_detection_increment_required_from_sanitized_r17_holdout": 1,
    "r18_sanitized_r17_basis": _R18_SANITIZED_R17_BASIS,
    "r18_sanitized_r17_basis_sha256": _R18_SANITIZED_R17_BASIS_SHA256,
    "r18_metric_threshold_population_and_rate_contract_changes_forbidden": True,
    "speck_reject_source_anchor_conditions_per_split": 10,
    "speck_reject_active_anchor_conditions_per_split": 10,
    "speck_reject_anchor_structural_miss_budget_against_development_floor": 4,
    "speck_reject_anchor_truth_guarantee_claimed": False,
    "speck_reject_anchor_schedule": _R18_SPECK_REJECT_ANCHOR_SCHEDULE,
}
_R18_POPULATION_ANCHOR_SCHEDULE_KEYS = {
    "revision",
    "fresh_from_closed_dev_r17",
    "r17_parameter_nonce_reuse_forbidden",
    "r18_per_family_residue_rotation",
    "r18_parameter_nonce_bases",
    "inherited_r17_schedule_revision",
    "private_reference_prequalification_manifest",
    "private_reference_prequalification_manifest_sha256",
    "initial_decision_gate_manifest",
    "initial_decision_gate_manifest_sha256",
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
    "private_until_one_shot_marker",
    "public_manifest_exposure_forbidden",
    "generation_design_tiers_are_truth",
    "tier_counts_per_artifact_family",
    "artifact_families_covered",
    "tier_variant_index_modulo_three_residues_per_family",
    "all_100_artifact_clusters_reviewed_and_evaluated",
    "subset_selection_forbidden",
    "top_up_forbidden",
    "replacement_forbidden",
    "key_resampling_forbidden",
    "actual_sealed_vision_labels_are_decisive",
    "inherited_warning_acceptance_anchor_revision",
    "inherited_warning_acceptance_anchor_conditions_per_split",
    "inherited_warning_acceptance_anchor_schedule_sha256",
    "warning_acceptance_anchor_revision",
    "warning_acceptance_anchor_conditions_per_split",
    "warning_acceptance_anchor_conditions_per_family",
    "warning_acceptance_anchor_structural_miss_budget_against_development_floor",
    "warning_acceptance_anchor_truth_guarantee_claimed",
    "warning_acceptance_anchor_schedule_sha256",
    "warning_conversion_revision",
    "warning_conversion_conditions_per_split",
    "warning_conversion_source_tiers_per_sparse_family",
    "warning_conversion_schedule_sha256",
    "exact_morphology_change_count_across_splits",
    "nonconversion_morphology_change_forbidden",
    "predecessor_full_morphology_sha256",
    "preserved_nonconversion_morphology_conditions_across_splits",
    "preserved_nonconversion_morphology_sha256",
    "preserved_nonwarning_morphology_conditions_across_splits",
    "preserved_nonwarning_morphology_sha256",
    "calibration_microblob_clear_reject_anchor_manifest",
    "calibration_microblob_clear_reject_anchor_conditions",
    "calibration_microblob_clear_reject_anchor_truth_guarantee_claimed",
    "calibration_microblob_clear_reject_anchor_schedule_sha256",
    "calibration_microblob_clear_reject_active_indices",
    "calibration_microblob_clear_reject_active_conditions",
    "calibration_microblob_clear_reject_converted_to_warning_index",
    "calibration_microblob_clear_reject_active_schedule_sha256",
    "speck_reject_source_anchor_conditions_per_split",
    "speck_reject_active_anchor_conditions_per_split",
    "speck_reject_anchor_structural_miss_budget_against_development_floor",
    "speck_reject_anchor_truth_guarantee_claimed",
    "speck_reject_anchor_schedule",
    "grain_reject_anchor_conditions_per_split",
    "grain_reject_anchor_truth_guarantee_claimed",
    "grain_reject_anchor_schedule",
    "blind_key_selection_forbidden_for",
    "blind_key_allowed_uses",
    "development_premeasurement_safety_floor_formula",
    "development_premeasurement_safety_floors",
}
_R18_SPECK_REJECT_ANCHOR_SCHEDULE_SHA256 = (
    "ed60c8f99b7338c4ca66246312b7d9a48648519257a3079ba06e0aba1e19e317"
)
_R18_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES_SHA256 = (
    "fdb3fbf506207a653e4b2bc07fff45e02100e3a9482cdf52001b2b62bd52c275"
)
_R18_POPULATION_ANCHOR_SCHEDULE_KEYSET_SHA256 = (
    "175139a0071273ac615068cdcd08658be5dcde1971e833aa55c3ca5cb55891cd"
)
_R18_HISTORY_STATUS = "fresh-development-only"
_R18_HISTORY_ROLE = (
    "fresh one-shot development role used only as a symmetric direct-visible "
    "reject-speck reinforcement probe after the closed dev-r17 premeasurement "
    "population failure; it may use only the sanitized aggregate that holdout "
    "tiny-speck population was 0 against formal minimum 4 and development floor 6 "
    "and holdout spot population was 9 against formal minimum 8 and development "
    "floor 10 while every other endpoint passed both minima, changes exactly the 10 "
    "existing reject-tier speck conditions per split, preserves the other 180 "
    "artifact morphologies plus the r17 role-agnostic reference prequalification "
    "and bilateral initial flag gate and every tier cardinality, population minimum, "
    "metric, threshold, and rate contract, requires a fresh isolated root, "
    "cryptographic blind key, identities, domains, nonces, controls, references, "
    "commitments, labels, decisions, and measurements, and can never become or "
    "supply formal authority"
)
_R18_EXACT_VARIANT_SOURCE = (
    "the tracked control_catalog.py named by implementation-bindings.json; r18 "
    "preserves the full r17 catalog except the exact twenty hash-bound "
    "artifact-speck reject morphologies preregistered in the tracked code"
)
_R18_SECRET_SCOPE = (
    "non-authority dev-r18 only; no development key, root, output, or commitment "
    "can become formal authority"
)
_R18_PRIVATE_KEY_REPO_RELATIVE = (
    "tmp/map-production/microtexture-v2-r6-dev-r18/private/development-key.bin"
)
_R18_REVIEWER_ACCESS_CONTRACT = (
    "the formal blind key remains only in a dedicated custodian process; the "
    "closed dev-r9, dev-r10, dev-r11, dev-r12, dev-r13, dev-r14, dev-r15, dev-r16, "
    "and dev-r17 blind keys remain only in their retained Git-ignored private probe "
    "roots and are never reused; the fresh dev-r18 blind key remains only in its "
    "separate Git-ignored private probe root and tracked custodian runner; neither "
    "Vision review process may read or inherit any key, and both must use visual "
    "page inspection only until both official initial snapshots and receipts exist "
    "before reconciliation and label sealing"
)
_R18_HARD_SPECK_INTEGER_CORE_CONTRACT = (
    "artifact-speck retains an unblurred exact one-pixel integer-lattice core; "
    "clean and warning conditions retain their inherited shoulders, while the ten "
    "preregistered reject targets per split use only four axial neighbours whose "
    "encoded magnitude is at least 5 L"
)
_R18_HARD_SPECK_SEPARATION_CONTRACT = (
    "all inherited artifact-speck conditions retain their prior separation; the "
    "ten r18 reject targets per split require at least 30-pixel pairwise Chebyshev "
    "separation, disjoint one-neighbour crosses, and uninjected background beyond "
    "that support"
)
_R18_HARD_SPECK_REJECT_ANCHOR_CONTRACT = (
    "the ten r18 target conditions per split preserve reject-tier membership and "
    "replace only their speck morphology with four through seven quadrant-stratified "
    "direct-visible one-pixel cores; this is a preregistered coverage reinforcement, "
    "not assigned Vision truth, and cannot bypass the post-seal population gate"
)
_R18_MATERIALIZED_SPEC_CHANGED_PATHS = {
    "history.dev_r18_status": _R18_HISTORY_STATUS,
    "history.dev_r18_role": _R18_HISTORY_ROLE,
    "development_probe_secret_handling.scope": _R18_SECRET_SCOPE,
    "development_probe_secret_handling.ignored_private_key_required_repo_relative": (
        _R18_PRIVATE_KEY_REPO_RELATIVE
    ),
    "splits.calibration.public_nonce": _R18_PUBLIC_NONCES["calibration"],
    "splits.holdout.public_nonce": _R18_PUBLIC_NONCES["holdout"],
    "independent_condition_clusters.message_prefix": _R18_CLUSTER_PREFIX,
    "control_catalog_authority.exact_variant_source": _R18_EXACT_VARIANT_SOURCE,
    "control_catalog_authority.private_identity_domains": (
        _R18_PRIVATE_IDENTITY_DOMAINS
    ),
    "blind_derivation.key_commitment_message": _R18_KEY_COMMITMENT_MESSAGE,
    "blind_derivation.seed_message_prefix": _R18_SEED_MESSAGE_PREFIX,
    "blind_derivation.code_message_prefix": _R18_CODE_MESSAGE_PREFIX,
    "rendering.public_commitment_domain": _R18_PUBLIC_COMMITMENT_DOMAIN,
    "rendering.hard_speck_integer_core_contract": (
        _R18_HARD_SPECK_INTEGER_CORE_CONTRACT
    ),
    "rendering.hard_speck_separation_contract": (
        _R18_HARD_SPECK_SEPARATION_CONTRACT
    ),
    "rendering.hard_speck_reject_anchor_contract": (
        _R18_HARD_SPECK_REJECT_ANCHOR_CONTRACT
    ),
    "public_identity_policy.reviewer_access_contract": (
        _R18_REVIEWER_ACCESS_CONTRACT
    ),
}
_R18_PROBE_AUTHORITY_MANIFEST = {
    "revision": "dev-r18-development-probe-authority-v1",
    "development_edition": "r18",
    "development_root_required_repo_relative": (
        "tmp/map-production/microtexture-v2-r6-dev-r18"
    ),
    "public_nonces": _R18_PUBLIC_NONCES,
    "blind_identity_domains": {
        "condition_cluster_prefix": _R18_CLUSTER_PREFIX,
        "key_commitment_message": _R18_KEY_COMMITMENT_MESSAGE,
        "seed_message_prefix": _R18_SEED_MESSAGE_PREFIX,
        "code_message_prefix": _R18_CODE_MESSAGE_PREFIX,
        "public_commitment_domain": _R18_PUBLIC_COMMITMENT_DOMAIN,
    },
    "zero_key_commitment_test_vector": _R18_ZERO_KEY_COMMITMENT_TEST_VECTOR,
    "private_identity_domains": _R18_PRIVATE_IDENTITY_DOMAINS,
    "parameter_nonce_bases": _R18_PARAMETER_NONCE_BASES,
    "schedule_revision": _R18_SCHEDULE_REVISION,
    "catalog_authority": _R18_CATALOG_AUTHORITY,
    "population_anchor_schedule_keyset_sha256": (
        _R18_POPULATION_ANCHOR_SCHEDULE_KEYSET_SHA256
    ),
    "population_anchor_schedule_changed_values_sha256": (
        _R18_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES_SHA256
    ),
    "speck_reject_anchor_schedule_sha256": (
        _R18_SPECK_REJECT_ANCHOR_SCHEDULE_SHA256
    ),
    "materialized_spec_changed_paths": _R18_MATERIALIZED_SPEC_CHANGED_PATHS,
    "inherited_reference_prequalification_manifest_sha256": (
        _R17_REFERENCE_PREQUALIFICATION_MANIFEST_SHA256
    ),
    "inherited_initial_decision_gate_manifest_sha256": (
        _R17_INITIAL_DECISION_GATE_MANIFEST_SHA256
    ),
    "development_population_floors": DEVELOPMENT_POPULATION_FLOORS,
    "sanitized_r17_basis": _R18_SANITIZED_R17_BASIS,
    "metric_threshold_population_and_rate_contract_changes_forbidden": True,
}
_R18_PROBE_AUTHORITY_MANIFEST_SHA256 = (
    "d4bf229f7ae961e47aa66368ac386c5d911c8a9c81a0703b6650bda5fa9660f1"
)
_R19_SANITIZED_R18_BASIS = {
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
}
_R19_SANITIZED_R18_BASIS_SHA256 = (
    "f4f4c80a406818da30ab18ac270eb466dda2ef42b4f301bde6ce2dea8698ade1"
)
_R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST = {
    "revision": _R19_DUPLICATE_EQUIVALENCE_POLICY_REVISION,
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
        "tier_cardinality_minimum_metric_threshold_and_rate_contracts_unchanged": (
            True
        ),
        "reference_prequalification_unchanged": True,
        "bilateral_initial_visible_flag_gate_unchanged": True,
        "vision_truth_guaranteed": False,
    },
}
_R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST_SHA256 = (
    "292ebced789826a46ac792a10f716c70c1a4ed5960d5a299dd7a89e816143cc6"
)
_R19_CATALOG_AUTHORITY = {
    "schedule_revision": _R19_SCHEDULE_REVISION,
    "duplicate_equivalence_policy_revision": (
        _R19_DUPLICATE_EQUIVALENCE_POLICY_REVISION
    ),
    "duplicate_equivalence_policy_manifest_sha256": (
        _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST_SHA256
    ),
    "sanitized_r18_basis_sha256": _R19_SANITIZED_R18_BASIS_SHA256,
    "public_payload_commitment_prefix": (
        "microtexture-v2-r6/public-payload-commitment/v15/"
    ),
    "private_reference_transform_prefix": "private-reference-transform-v14/",
    "foundation_offset_lane": "foundation-offset-v13",
    "foundation_assignment_lane": "foundation-assignment-v13",
    "delta_lane": "delta-v13",
    "private_control_id_prefix": "microtexture-v2-r6/private-control-id/v13/",
    "artifact_nonce_bases": {"calibration": 1173000, "holdout": 1183000},
    "protocol_zero_nonce_bases": {"calibration": 1151000, "holdout": 1161000},
    "duplicate_audit_nonces": {
        "calibration": [1191000, 1191001, 1191002],
        "holdout": [1201000, 1201001, 1201002],
    },
    "speck_reinforcement_revision": _R18_SPECK_REINFORCEMENT_REVISION,
    "speck_reinforcement_manifest_sha256": (
        "355c6c588c3d698288a3545752c13cea734db85e1e7a9a95416cbe3163f633d4"
    ),
    "predecessor_full_artifact_morphology_sha256": (
        "9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365"
    ),
    "full_artifact_morphology_sha256": (
        "9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365"
    ),
    "exact_morphology_change_count_across_splits": 0,
}
_R19_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES = {
    "revision": _R19_SCHEDULE_REVISION,
    "fresh_from_closed_dev_r18": True,
    "r18_parameter_nonce_reuse_forbidden": True,
    "r18_per_family_residue_rotation": _R18_PER_FAMILY_RESIDUE_ROTATION,
    "r19_parameter_nonce_bases": _R19_PARAMETER_NONCE_BASES,
    "inherited_r18_schedule_revision": _R18_SCHEDULE_REVISION,
    "preserved_r17_artifact_morphology_conditions_across_splits": 180,
    "preserved_r17_artifact_morphology_sha256": (
        _R18_CATALOG_AUTHORITY["preserved_r17_morphology_sha256"]
    ),
    "r18_exact_morphology_change_count_across_splits": 20,
    "r18_speck_reinforcement_revision": _R18_SPECK_REINFORCEMENT_REVISION,
    "r18_speck_reinforcement_manifest_sha256": (
        _R18_CATALOG_AUTHORITY["speck_reinforcement_manifest_sha256"]
    ),
    "r18_full_artifact_morphology_sha256": (
        _R18_CATALOG_AUTHORITY["full_artifact_morphology_sha256"]
    ),
    "r18_target_speck_conditions_per_split": 10,
    "r18_target_speck_tiers_per_split": {
        "clear-reject-candidate": 6,
        "dominant-reject-candidate": 4,
    },
    "r18_tiny_speck_structural_miss_budget": 4,
    "r18_spot_detection_increment_required_from_sanitized_r17_holdout": 1,
    "r18_sanitized_r17_basis": _R18_SANITIZED_R17_BASIS,
    "r18_sanitized_r17_basis_sha256": _R18_SANITIZED_R17_BASIS_SHA256,
    "r18_metric_threshold_population_and_rate_contract_changes_forbidden": True,
    "r19_preserved_r18_artifact_morphology_conditions_across_splits": 200,
    "r19_preserved_r18_artifact_morphology_sha256": (
        _R19_CATALOG_AUTHORITY["full_artifact_morphology_sha256"]
    ),
    "r19_exact_morphology_change_count_across_splits": 0,
    "r19_duplicate_equivalence_policy_revision": (
        _R19_DUPLICATE_EQUIVALENCE_POLICY_REVISION
    ),
    "r19_duplicate_equivalence_policy_manifest": (
        _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST
    ),
    "r19_duplicate_equivalence_policy_manifest_sha256": (
        _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST_SHA256
    ),
    "r19_sanitized_r18_basis": _R19_SANITIZED_R18_BASIS,
    "r19_sanitized_r18_basis_sha256": _R19_SANITIZED_R18_BASIS_SHA256,
    "r19_morphology_tier_minimum_metric_threshold_and_rate_changes_forbidden": True,
    "speck_reject_source_anchor_conditions_per_split": 10,
    "speck_reject_active_anchor_conditions_per_split": 10,
    "speck_reject_anchor_structural_miss_budget_against_development_floor": 4,
    "speck_reject_anchor_truth_guarantee_claimed": False,
    "speck_reject_anchor_schedule": _R18_SPECK_REJECT_ANCHOR_SCHEDULE,
}
_R19_POPULATION_ANCHOR_SCHEDULE_KEY_ORDER = (
    "revision",
    "fresh_from_closed_dev_r18",
    "r18_parameter_nonce_reuse_forbidden",
    "r18_per_family_residue_rotation",
    "r19_parameter_nonce_bases",
    "inherited_r18_schedule_revision",
    "private_reference_prequalification_manifest",
    "private_reference_prequalification_manifest_sha256",
    "initial_decision_gate_manifest",
    "initial_decision_gate_manifest_sha256",
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
    "private_until_one_shot_marker",
    "public_manifest_exposure_forbidden",
    "generation_design_tiers_are_truth",
    "tier_counts_per_artifact_family",
    "artifact_families_covered",
    "tier_variant_index_modulo_three_residues_per_family",
    "all_100_artifact_clusters_reviewed_and_evaluated",
    "subset_selection_forbidden",
    "top_up_forbidden",
    "replacement_forbidden",
    "key_resampling_forbidden",
    "actual_sealed_vision_labels_are_decisive",
    "inherited_warning_acceptance_anchor_revision",
    "inherited_warning_acceptance_anchor_conditions_per_split",
    "inherited_warning_acceptance_anchor_schedule_sha256",
    "warning_acceptance_anchor_revision",
    "warning_acceptance_anchor_conditions_per_split",
    "warning_acceptance_anchor_conditions_per_family",
    "warning_acceptance_anchor_structural_miss_budget_against_development_floor",
    "warning_acceptance_anchor_truth_guarantee_claimed",
    "warning_acceptance_anchor_schedule_sha256",
    "warning_conversion_revision",
    "warning_conversion_conditions_per_split",
    "warning_conversion_source_tiers_per_sparse_family",
    "warning_conversion_schedule_sha256",
    "exact_morphology_change_count_across_splits",
    "nonconversion_morphology_change_forbidden",
    "predecessor_full_morphology_sha256",
    "preserved_nonconversion_morphology_conditions_across_splits",
    "preserved_nonconversion_morphology_sha256",
    "preserved_nonwarning_morphology_conditions_across_splits",
    "preserved_nonwarning_morphology_sha256",
    "calibration_microblob_clear_reject_anchor_manifest",
    "calibration_microblob_clear_reject_anchor_conditions",
    "calibration_microblob_clear_reject_anchor_truth_guarantee_claimed",
    "calibration_microblob_clear_reject_anchor_schedule_sha256",
    "calibration_microblob_clear_reject_active_indices",
    "calibration_microblob_clear_reject_active_conditions",
    "calibration_microblob_clear_reject_converted_to_warning_index",
    "calibration_microblob_clear_reject_active_schedule_sha256",
    "speck_reject_source_anchor_conditions_per_split",
    "speck_reject_active_anchor_conditions_per_split",
    "speck_reject_anchor_structural_miss_budget_against_development_floor",
    "speck_reject_anchor_truth_guarantee_claimed",
    "speck_reject_anchor_schedule",
    "grain_reject_anchor_conditions_per_split",
    "grain_reject_anchor_truth_guarantee_claimed",
    "grain_reject_anchor_schedule",
    "blind_key_selection_forbidden_for",
    "blind_key_allowed_uses",
    "development_premeasurement_safety_floor_formula",
    "development_premeasurement_safety_floors",
)
_R19_POPULATION_ANCHOR_SCHEDULE_KEYS = set(
    _R19_POPULATION_ANCHOR_SCHEDULE_KEY_ORDER
)
_R19_POPULATION_ANCHOR_SCHEDULE_KEYSET_SHA256 = (
    "15e87ae2c17897bccae75722f1a8ffa9dd8f3aea2d8632929d83a62ac0675b0d"
)
_R19_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES_SHA256 = (
    "7065534770044e408d02dd82a4b96adbc74ba77a5e154a2c42697bb43c679c3c"
)
_R19_HISTORY_DEV_R18_STATUS = "failed-and-closed-before-population-audit"
_R19_HISTORY_DEV_R18_ROLE = (
    "development-only prepopulation private-audit failure evidence; generation, "
    "both blind 440-record reviews, bilateral reconciliation, official preflight, "
    "label sealing, private reveal, regeneration, and protocol-zero audits each "
    "completed exactly once, but calibration's obvious-artifact duplicate pair had "
    "identical reject dispositions and short-line flags with ordinal severities 2 "
    "and 3, so the then-exact severity semantic check failed before population audit "
    "or any numeric measurement; one read-only postmortem ran exactly once, all "
    "initial snapshots and receipts remain immutable, and no dev-r18 root, key, "
    "private material, control, reference, pixel, identity, code, commitment, label, "
    "decision, measurement, nonce, public surface, or postmortem output is reusable"
)
_R19_HISTORY_DEV_R18_FAILURE_AUDIT = (
    "world/map-production/qa/microtexture-v2-r6-dev-r18-development-failure.json"
)
_R19_HISTORY_DEV_R18_FAILURE_AUDIT_SHA256 = (
    "7800ab0f33363df30decb1c744e1b1ed3b7c822bb2f94fc4a17fd44d35541122"
)
_R19_HISTORY_STATUS = "fresh-development-only"
_R19_HISTORY_ROLE = (
    "fresh one-shot development role used only as a duplicate semantic-equivalence "
    "correction probe after the closed dev-r18 prepopulation private-audit failure; "
    "it preserves every dev-r18 morphology, design tier, metric, threshold, "
    "population, and rate contract, changes only duplicate semantic equivalence so "
    "reject severities 2 and 3 share one reject ordinal band while clean and warning "
    "severities remain exact and disposition plus all five visible flags remain exact, "
    "requires a fresh isolated root, cryptographic blind key, identities, domains, "
    "nonces, controls, references, commitments, labels, decisions, and measurements, "
    "and can never become or supply formal authority"
)
_R19_DEVELOPMENT_BASIS = (
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
    "development-only"
)
_R19_EXACT_VARIANT_SOURCE = (
    "the tracked control_catalog.py named by implementation-bindings.json; r19 "
    "preserves the full hash-bound r18 artifact morphology catalog byte-for-byte and "
    "changes only the preregistered duplicate-artifact reject severity equivalence "
    "policy"
)
_R19_SECRET_SCOPE = (
    "non-authority dev-r19 only; no development key, root, output, or commitment "
    "can become formal authority"
)
_R19_PRIVATE_KEY_REPO_RELATIVE = (
    "tmp/map-production/microtexture-v2-r6-dev-r19/private/development-key.bin"
)
_R19_REVIEWER_ACCESS_CONTRACT = (
    "the formal blind key remains only in a dedicated custodian process; the "
    "closed dev-r9, dev-r10, dev-r11, dev-r12, dev-r13, dev-r14, dev-r15, dev-r16, "
    "dev-r17, and dev-r18 blind keys remain only in their retained Git-ignored "
    "private probe roots and are never reused; the fresh dev-r19 blind key remains "
    "only in its separate Git-ignored private probe root and tracked custodian runner; "
    "neither Vision review process may read or inherit any key, and both must use "
    "visual page inspection only until both official initial snapshots and receipts "
    "exist before reconciliation and label sealing"
)
_R19_RENDERING_DUPLICATE_AUDIT_CONTRACT = (
    "the clean and obvious-artifact semantic audit groups each contain two separately "
    "coded records with distinct private reference/control bytes, equal "
    "requested-delta bytes, exact decoded-residual and metric equality, and labels "
    "satisfying the preregistered duplicate semantic-equivalence policy"
)
_R19_CATALOG_DUPLICATE_AUDIT_CONTRACT = (
    "one clean and one obvious-artifact private semantic-replicate cluster; each has "
    "two separately coded records with distinct secret-transformed references and "
    "controls, the same requested delta, exact decoded residual and metric equality, "
    "and labels satisfying the preregistered duplicate semantic-equivalence policy"
)
_R19_LABEL_DUPLICATE_ARTIFACT_CONTRACT = (
    "the two separately coded obvious-artifact records must have exact disposition "
    "and exact values for all five visible flags across the pair, both must be reject "
    "with short_line_visible=true, and each severity must independently belong to the "
    "inclusive reject ordinal band {2,3}; severity equality within that band is not "
    "required"
)
_R19_MATERIALIZED_SPEC_CHANGED_PATHS = {
    "history.dev_r18_status": _R19_HISTORY_DEV_R18_STATUS,
    "history.dev_r18_role": _R19_HISTORY_DEV_R18_ROLE,
    "history.dev_r18_failure_audit": _R19_HISTORY_DEV_R18_FAILURE_AUDIT,
    "history.dev_r18_failure_audit_sha256": (
        _R19_HISTORY_DEV_R18_FAILURE_AUDIT_SHA256
    ),
    "history.dev_r19_status": _R19_HISTORY_STATUS,
    "history.dev_r19_role": _R19_HISTORY_ROLE,
    "metric_definition.development_basis": _R19_DEVELOPMENT_BASIS,
    "development_probe_secret_handling.scope": _R19_SECRET_SCOPE,
    "development_probe_secret_handling.ignored_private_key_required_repo_relative": (
        _R19_PRIVATE_KEY_REPO_RELATIVE
    ),
    "splits.calibration.public_nonce": _R19_PUBLIC_NONCES["calibration"],
    "splits.holdout.public_nonce": _R19_PUBLIC_NONCES["holdout"],
    "independent_condition_clusters.message_prefix": _R19_CLUSTER_PREFIX,
    "control_catalog_authority.exact_variant_source": _R19_EXACT_VARIANT_SOURCE,
    "control_catalog_authority.private_identity_domains": (
        _R19_PRIVATE_IDENTITY_DOMAINS
    ),
    "control_catalog_authority.duplicate_audit_contract": (
        _R19_CATALOG_DUPLICATE_AUDIT_CONTRACT
    ),
    "blind_derivation.key_commitment_message": _R19_KEY_COMMITMENT_MESSAGE,
    "blind_derivation.seed_message_prefix": _R19_SEED_MESSAGE_PREFIX,
    "blind_derivation.code_message_prefix": _R19_CODE_MESSAGE_PREFIX,
    "rendering.public_commitment_domain": _R19_PUBLIC_COMMITMENT_DOMAIN,
    "rendering.duplicate_audit_contract": _R19_RENDERING_DUPLICATE_AUDIT_CONTRACT,
    "labels.post_marker_private_audits.duplicate_artifact": (
        _R19_LABEL_DUPLICATE_ARTIFACT_CONTRACT
    ),
    "public_identity_policy.reviewer_access_contract": (
        _R19_REVIEWER_ACCESS_CONTRACT
    ),
}
_R19_PROBE_AUTHORITY_MANIFEST = {
    "revision": "dev-r19-development-probe-authority-v1",
    "development_edition": "r19",
    "development_root_required_repo_relative": (
        "tmp/map-production/microtexture-v2-r6-dev-r19"
    ),
    "public_nonces": _R19_PUBLIC_NONCES,
    "blind_identity_domains": {
        "condition_cluster_prefix": _R19_CLUSTER_PREFIX,
        "key_commitment_message": _R19_KEY_COMMITMENT_MESSAGE,
        "seed_message_prefix": _R19_SEED_MESSAGE_PREFIX,
        "code_message_prefix": _R19_CODE_MESSAGE_PREFIX,
        "public_commitment_domain": _R19_PUBLIC_COMMITMENT_DOMAIN,
    },
    "zero_key_commitment_test_vector": _R19_ZERO_KEY_COMMITMENT_TEST_VECTOR,
    "private_identity_domains": _R19_PRIVATE_IDENTITY_DOMAINS,
    "parameter_nonce_bases": _R19_PARAMETER_NONCE_BASES,
    "schedule_revision": _R19_SCHEDULE_REVISION,
    "catalog_authority": _R19_CATALOG_AUTHORITY,
    "population_anchor_schedule_key_order": list(
        _R19_POPULATION_ANCHOR_SCHEDULE_KEY_ORDER
    ),
    "population_anchor_schedule_keyset_sha256": (
        _R19_POPULATION_ANCHOR_SCHEDULE_KEYSET_SHA256
    ),
    "population_anchor_schedule_changed_values_sha256": (
        _R19_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES_SHA256
    ),
    "inherited_speck_reject_anchor_schedule_sha256": (
        _R18_SPECK_REJECT_ANCHOR_SCHEDULE_SHA256
    ),
    "duplicate_equivalence_policy_manifest": (
        _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST
    ),
    "duplicate_equivalence_policy_manifest_sha256": (
        _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST_SHA256
    ),
    "materialized_spec_changed_paths": _R19_MATERIALIZED_SPEC_CHANGED_PATHS,
    "inherited_reference_prequalification_manifest_sha256": (
        _R17_REFERENCE_PREQUALIFICATION_MANIFEST_SHA256
    ),
    "inherited_initial_decision_gate_manifest_sha256": (
        _R17_INITIAL_DECISION_GATE_MANIFEST_SHA256
    ),
    "development_population_floors": DEVELOPMENT_POPULATION_FLOORS,
    "sanitized_r18_basis": _R19_SANITIZED_R18_BASIS,
    "sanitized_r18_basis_sha256": _R19_SANITIZED_R18_BASIS_SHA256,
    "predecessor_full_artifact_morphology_sha256": (
        _R19_CATALOG_AUTHORITY["predecessor_full_artifact_morphology_sha256"]
    ),
    "full_artifact_morphology_sha256": (
        _R19_CATALOG_AUTHORITY["full_artifact_morphology_sha256"]
    ),
    "exact_morphology_change_count_across_splits": 0,
    "morphology_tier_minimum_metric_threshold_and_rate_changes_forbidden": True,
}
_R19_PROBE_AUTHORITY_MANIFEST_SHA256 = (
    "b96a98c0c6a35f227a9b81c80220af9ffa99621828a71d10a2ddecb84cccb963"
)
_R20_SANITIZED_R19_BASIS = {
    "failure_class": "holdout-artifact-duplicate-obvious-short-line-clean-miss",
    "calibration": {
        "duplicate_clean_audit_passed": True,
        "duplicate_artifact_pair": {
            "member_count": 2,
            "agreed_disposition": "reject",
            "agreed_severity_0_to_3": 3,
            "agreed_visible_flags": {
                "grain_visible": False,
                "tiny_speck_visible": False,
                "microblob_visible": False,
                "short_line_visible": True,
                "parallel_bundle_visible": False,
            },
            "required_obvious_artifact_contract_passed": True,
        },
        "protocol_zero_audit_passed": True,
        "duplicate_audit_passed": True,
    },
    "holdout": {
        "duplicate_clean_audit_passed": True,
        "duplicate_artifact_pair": {
            "member_count": 2,
            "agreed_disposition": "clean",
            "agreed_severity_0_to_3": 0,
            "agreed_visible_flags": {
                "grain_visible": False,
                "tiny_speck_visible": False,
                "microblob_visible": False,
                "short_line_visible": False,
                "parallel_bundle_visible": False,
            },
            "required_obvious_artifact_contract_passed": False,
        },
        "protocol_zero_audit_passed": True,
        "duplicate_audit_passed": False,
    },
    "population_aggregation_started": False,
    "numeric_measurement_started": False,
    "metric_evaluation_started": False,
    "threshold_search_started": False,
}
_R20_SANITIZED_R19_BASIS_SHA256 = (
    "8a99bb7038b5936ac7e44ac339114dc46f78e5d2a8df923a7be0674693d85933"
)
_R20_DUPLICATE_SENTINEL_MANIFEST = {
    "revision": _R20_DUPLICATE_SENTINEL_REVISION,
    "scope": {
        "private_role": "duplicate-audit",
        "duplicate_audit_group": "artifact",
    },
    "construction": {
        "render_family": "duplicate-obvious-short-line-sentinel",
        "bar_count_in_metric_window": 12,
        "bars_per_exact_metric_quadrant": 3,
        "encoded_bar_length_px": 24,
        "encoded_bar_width_px": 3,
        "encoded_amplitude_l": 12.0,
        "polarity": 1,
        "minimum_center_chebyshev_separation_px": 32,
        "center_margin_per_exact_metric_quadrant_px": 14,
        "minimum_support_guard_px": 2,
        "orientation_contract": "keyed-phase-2-to-1-horizontal-or-vertical-per-quadrant",
        "placement_contract": "fresh-keyed-split-and-condition-derived",
    },
    "raster_contract": {
        "connected_component_count": 12,
        "pixels_per_component": 72,
        "nonzero_pixel_count": 864,
        "nonzero_values_exact": [12.0],
        "component_shapes_hw": [[3, 24], [24, 3]],
        "each_quadrant_contains_horizontal_and_vertical": True,
        "all_support_inside_one_exact_metric_quadrant_per_component": True,
        "all_support_inside_metric_window": True,
    },
    "pair_equality_contract": {
        "requested_delta_float32_exact": True,
        "decoded_residual_exact": True,
        "metric_values_exact": True,
        "reference_bytes_distinct": True,
        "control_bytes_distinct": True,
        "anonymous_codes_and_control_ids_distinct": True,
    },
    "zero_key_static_delta_float32_sha256": {
        "calibration": (
            "0f34c8f787be57c7c0c074888a73ec15e007c63e98d5c5606d4d5d8bbc6de823"
        ),
        "holdout": (
            "027140de4d34eb78c06b00c282b37caade6393ce6240165bfa65825a286a644f"
        ),
    },
    "preservation_contract": {
        "clean_duplicate_construction_unchanged": True,
        "artifact_catalog_morphology_change_count_across_splits": 0,
        "full_artifact_morphology_sha256": (
            "9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365"
        ),
        "duplicate_equivalence_policy_revision": (
            _R19_DUPLICATE_EQUIVALENCE_POLICY_REVISION
        ),
        "duplicate_equivalence_policy_manifest_sha256": (
            _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST_SHA256
        ),
        "tier_metric_threshold_population_and_rate_contracts_unchanged": True,
        "vision_truth_guaranteed": False,
    },
}
_R20_DUPLICATE_SENTINEL_MANIFEST_SHA256 = (
    "2ee513f2a3182741fbf9df569a2c5137a7f25b4fd27d3fbba6b00344497b85a1"
)
_R20_CATALOG_AUTHORITY = {
    "schedule_revision": _R20_SCHEDULE_REVISION,
    "duplicate_equivalence_policy_revision": (
        _R19_DUPLICATE_EQUIVALENCE_POLICY_REVISION
    ),
    "duplicate_equivalence_policy_manifest_sha256": (
        _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST_SHA256
    ),
    "sanitized_r19_basis_sha256": _R20_SANITIZED_R19_BASIS_SHA256,
    "duplicate_sentinel_revision": _R20_DUPLICATE_SENTINEL_REVISION,
    "duplicate_sentinel_manifest_sha256": (
        _R20_DUPLICATE_SENTINEL_MANIFEST_SHA256
    ),
    "public_payload_commitment_prefix": (
        "microtexture-v2-r6/public-payload-commitment/v16/"
    ),
    "private_reference_transform_prefix": "private-reference-transform-v15/",
    "foundation_offset_lane": "foundation-offset-v14",
    "foundation_assignment_lane": "foundation-assignment-v14",
    "delta_lane": "delta-v14",
    "private_control_id_prefix": "microtexture-v2-r6/private-control-id/v14/",
    "artifact_nonce_bases": {"calibration": 1273000, "holdout": 1283000},
    "protocol_zero_nonce_bases": {"calibration": 1251000, "holdout": 1261000},
    "duplicate_audit_nonces": {
        "calibration": [1291000, 1291001, 1291002],
        "holdout": [1301000, 1301001, 1301002],
    },
    "speck_reinforcement_revision": _R18_SPECK_REINFORCEMENT_REVISION,
    "speck_reinforcement_manifest_sha256": (
        "355c6c588c3d698288a3545752c13cea734db85e1e7a9a95416cbe3163f633d4"
    ),
    "predecessor_full_artifact_morphology_sha256": (
        "9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365"
    ),
    "full_artifact_morphology_sha256": (
        "9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365"
    ),
    "exact_morphology_change_count_across_splits": 0,
    "obvious_artifact_duplicate_sentinel_change_count_across_splits": 2,
    "clean_duplicate_construction_change_count_across_splits": 0,
}
_R20_PREDECESSOR_CATALOG_AUTHORITY_SHA256 = (
    "f2edfca7ee3f696ddaf815b4be3f316973626ed5cc602cba3dbc5585203d5b37"
)
_R20_SANITIZED_R19_FAILURE_AUDIT_CANONICAL_SHA256 = (
    "54833ae6c35d7ec864f05fabefb8416844c63fe259780bda0ca309b6c31285e0"
)
_R20_POPULATION_ANCHOR_SCHEDULE_ADDED_KEY_ORDER = (
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
_r19_schedule_history_end = (
    _R19_POPULATION_ANCHOR_SCHEDULE_KEY_ORDER.index(
        "r19_morphology_tier_minimum_metric_threshold_and_rate_changes_forbidden"
    )
    + 1
)
_R20_POPULATION_ANCHOR_SCHEDULE_KEY_ORDER = (
    _R19_POPULATION_ANCHOR_SCHEDULE_KEY_ORDER[:_r19_schedule_history_end]
    + _R20_POPULATION_ANCHOR_SCHEDULE_ADDED_KEY_ORDER
    + _R19_POPULATION_ANCHOR_SCHEDULE_KEY_ORDER[_r19_schedule_history_end:]
)
_R20_POPULATION_ANCHOR_SCHEDULE_KEYS = set(
    _R20_POPULATION_ANCHOR_SCHEDULE_KEY_ORDER
)
_R20_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES = {
    **_R19_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES,
    "revision": _R20_SCHEDULE_REVISION,
    "fresh_from_closed_dev_r19": True,
    "r19_parameter_nonce_reuse_forbidden": True,
    "r20_parameter_nonce_bases": _R20_PARAMETER_NONCE_BASES,
    "inherited_r19_schedule_revision": _R19_SCHEDULE_REVISION,
    "r20_predecessor_catalog_authority_sha256": (
        _R20_PREDECESSOR_CATALOG_AUTHORITY_SHA256
    ),
    "r20_preserved_r19_artifact_morphology_conditions_across_splits": 200,
    "r20_preserved_r19_artifact_morphology_sha256": (
        _R20_CATALOG_AUTHORITY["full_artifact_morphology_sha256"]
    ),
    "r20_exact_morphology_change_count_across_splits": 0,
    "r20_duplicate_equivalence_policy_revision": (
        _R19_DUPLICATE_EQUIVALENCE_POLICY_REVISION
    ),
    "r20_duplicate_equivalence_policy_manifest": (
        _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST
    ),
    "r20_duplicate_equivalence_policy_manifest_sha256": (
        _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST_SHA256
    ),
    "r20_duplicate_sentinel_revision": _R20_DUPLICATE_SENTINEL_REVISION,
    "r20_duplicate_sentinel_manifest": _R20_DUPLICATE_SENTINEL_MANIFEST,
    "r20_duplicate_sentinel_manifest_sha256": (
        _R20_DUPLICATE_SENTINEL_MANIFEST_SHA256
    ),
    "r20_sanitized_r19_basis": _R20_SANITIZED_R19_BASIS,
    "r20_sanitized_r19_basis_sha256": _R20_SANITIZED_R19_BASIS_SHA256,
    "r20_sanitized_r19_failure_audit_canonical_sha256": (
        _R20_SANITIZED_R19_FAILURE_AUDIT_CANONICAL_SHA256
    ),
    "r20_obvious_artifact_duplicate_sentinel_construction_changes_across_splits": 2,
    "r20_clean_duplicate_construction_changes_across_splits": 0,
    "r20_morphology_tier_minimum_metric_threshold_and_rate_changes_forbidden": True,
    "r20_duplicate_sentinel_vision_truth_guaranteed": False,
}
_R20_POPULATION_ANCHOR_SCHEDULE_KEYSET_SHA256 = (
    "b5c8211902bb03838e7fe402bbb48e0e7f7a9db37acd1856be3dca2c67b82134"
)
_R20_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES_SHA256 = (
    "3b87c5aabee0c8c8641d80496123a4f2dd58ca60f6da2bcf822e6bc7dfa80368"
)
_R20_HISTORY_DEV_R19_STATUS = "failed-and-closed-before-population-audit"
_R20_HISTORY_DEV_R19_ROLE = (
    "development-only prepopulation private-audit failure evidence; generation, both "
    "blind 440-record reviews, bilateral reconciliation, official preflight, label "
    "sealing, private reveal, regeneration, and protocol-zero audits each completed "
    "exactly once, calibration clean and obvious-artifact duplicate groups plus the "
    "holdout clean duplicate group passed, but holdout's obvious-artifact duplicate "
    "pair was clean severity 0 with no visible flags, so the required rejected short-"
    "line artifact contract failed before population audit or any numeric measurement; "
    "one read-only postmortem ran exactly once, all initial snapshots and receipts "
    "remain immutable, and no dev-r19 root, key, private material, control, reference, "
    "pixel, identity, code, commitment, label, decision, measurement, nonce, public "
    "surface, or postmortem output is reusable"
)
_R20_HISTORY_DEV_R19_FAILURE_AUDIT = (
    "world/map-production/qa/microtexture-v2-r6-dev-r19-development-failure.json"
)
_R20_HISTORY_DEV_R19_FAILURE_AUDIT_SHA256 = (
    "96d93fe63be2ff6171ade926dbace188b6fd5eacf748a6f03a787781a5d248d0"
)
_R20_HISTORY_STATUS = "fresh-development-only"
_R20_HISTORY_ROLE = (
    "fresh one-shot development role used only to strengthen the obvious-artifact "
    "duplicate sentinel after the closed dev-r19 prepopulation private-audit miss; "
    "it preserves all 200 dev-r19 artifact morphologies, every design tier, metric, "
    "threshold, population and rate contract, the dev-r19 reject severity-band "
    "duplicate policy, and the clean duplicate construction, and changes only the "
    "obvious-artifact duplicate payload to a fresh-keyed finite axial short-line "
    "sentinel with static geometry checks; Vision truth is not guaranteed, all "
    "identities and audit roles remain private, and it can never supply formal authority"
)
_R20_DEVELOPMENT_BASIS = (
    _R19_DEVELOPMENT_BASIS
    + "; dev-r19 then closed before population aggregation or numeric measurement "
    "because its holdout obvious-artifact duplicate pair was labeled clean severity "
    "0 with no visible flags; fresh dev-r20 preserves the full dev-r19 artifact "
    "catalog, tier/metric/threshold/population/rate contracts, reject severity-band "
    "policy, and clean duplicate, and changes only the obvious-artifact duplicate "
    "construction to a keyed 12-bar finite axial short-line payload whose native-pixel "
    "geometry is statically checked but whose Vision outcome is not guaranteed"
)
_R20_EXACT_VARIANT_SOURCE = (
    "the tracked control_catalog.py named by implementation-bindings.json; r20 "
    "preserves the full hash-bound r19 artifact morphology catalog and dev-r19 "
    "duplicate semantic-equivalence policy byte-for-byte, preserves the clean duplicate, "
    "and changes only the obvious-artifact duplicate sentinel construction"
)
_R20_SECRET_SCOPE = (
    "non-authority dev-r20 only; no development key, root, output, or commitment "
    "can become formal authority"
)
_R20_PRIVATE_KEY_REPO_RELATIVE = (
    "tmp/map-production/microtexture-v2-r6-dev-r20/private/development-key.bin"
)
_R20_REVIEWER_ACCESS_CONTRACT = (
    "the formal blind key remains only in a dedicated custodian process; every closed "
    "development blind key through dev-r19 remains only in its retained Git-ignored "
    "private probe root and is never reused; the fresh dev-r20 blind key remains only "
    "in its separate Git-ignored private probe root and tracked custodian runner; "
    "neither Vision review process may read or inherit any key or private audit role, "
    "and both must use visual page inspection only until both official initial "
    "snapshots and receipts exist before reconciliation and label sealing"
)
_R20_RENDERING_DUPLICATE_AUDIT_CONTRACT = (
    "the clean semantic audit group retains its exact-zero construction; the obvious-"
    "artifact group uses the r20 fresh-keyed finite axial short-line sentinel; each "
    "group contains two separately coded records with distinct private reference and "
    "control bytes, equal requested-delta bytes, exact decoded-residual and metric "
    "equality, and labels satisfying the preserved dev-r19 reject-band policy"
)
_R20_CATALOG_DUPLICATE_AUDIT_CONTRACT = (
    "one unchanged clean and one strengthened obvious-artifact private semantic-"
    "replicate cluster; the strengthened pair uses twelve keyed finite 24-by-3 pixel "
    "positive-L axial bars, exactly three per metric quadrant with both orientations; "
    "pair deltas, decoded residuals, and metrics are exact while references, controls, "
    "codes, and control identities remain distinct and private"
)
_R20_LABEL_DUPLICATE_ARTIFACT_CONTRACT = _R19_LABEL_DUPLICATE_ARTIFACT_CONTRACT
_R20_MATERIALIZED_SPEC_CHANGED_PATHS = {
    "history.dev_r19_status": _R20_HISTORY_DEV_R19_STATUS,
    "history.dev_r19_role": _R20_HISTORY_DEV_R19_ROLE,
    "history.dev_r19_failure_audit": _R20_HISTORY_DEV_R19_FAILURE_AUDIT,
    "history.dev_r19_failure_audit_sha256": (
        _R20_HISTORY_DEV_R19_FAILURE_AUDIT_SHA256
    ),
    "history.dev_r20_status": _R20_HISTORY_STATUS,
    "history.dev_r20_role": _R20_HISTORY_ROLE,
    "metric_definition.development_basis": _R20_DEVELOPMENT_BASIS,
    "development_probe_secret_handling.scope": _R20_SECRET_SCOPE,
    "development_probe_secret_handling.ignored_private_key_required_repo_relative": (
        _R20_PRIVATE_KEY_REPO_RELATIVE
    ),
    "splits.calibration.public_nonce": _R20_PUBLIC_NONCES["calibration"],
    "splits.holdout.public_nonce": _R20_PUBLIC_NONCES["holdout"],
    "independent_condition_clusters.message_prefix": _R20_CLUSTER_PREFIX,
    "control_catalog_authority.exact_variant_source": _R20_EXACT_VARIANT_SOURCE,
    "control_catalog_authority.private_identity_domains": (
        _R20_PRIVATE_IDENTITY_DOMAINS
    ),
    "control_catalog_authority.duplicate_audit_contract": (
        _R20_CATALOG_DUPLICATE_AUDIT_CONTRACT
    ),
    "blind_derivation.key_commitment_message": _R20_KEY_COMMITMENT_MESSAGE,
    "blind_derivation.seed_message_prefix": _R20_SEED_MESSAGE_PREFIX,
    "blind_derivation.code_message_prefix": _R20_CODE_MESSAGE_PREFIX,
    "rendering.public_commitment_domain": _R20_PUBLIC_COMMITMENT_DOMAIN,
    "rendering.duplicate_audit_contract": _R20_RENDERING_DUPLICATE_AUDIT_CONTRACT,
    "labels.post_marker_private_audits.duplicate_artifact": (
        _R20_LABEL_DUPLICATE_ARTIFACT_CONTRACT
    ),
    "public_identity_policy.reviewer_access_contract": (
        _R20_REVIEWER_ACCESS_CONTRACT
    ),
}
_R20_PROBE_AUTHORITY_MANIFEST = {
    "revision": "dev-r20-development-probe-authority-v1",
    "development_edition": DEVELOPMENT_EDITION,
    "development_root_required_repo_relative": (
        "tmp/map-production/microtexture-v2-r6-dev-r20"
    ),
    "public_nonces": _R20_PUBLIC_NONCES,
    "blind_identity_domains": {
        "condition_cluster_prefix": _R20_CLUSTER_PREFIX,
        "key_commitment_message": _R20_KEY_COMMITMENT_MESSAGE,
        "seed_message_prefix": _R20_SEED_MESSAGE_PREFIX,
        "code_message_prefix": _R20_CODE_MESSAGE_PREFIX,
        "public_commitment_domain": _R20_PUBLIC_COMMITMENT_DOMAIN,
    },
    "zero_key_commitment_test_vector": _R20_ZERO_KEY_COMMITMENT_TEST_VECTOR,
    "private_identity_domains": _R20_PRIVATE_IDENTITY_DOMAINS,
    "parameter_nonce_bases": _R20_PARAMETER_NONCE_BASES,
    "schedule_revision": _R20_SCHEDULE_REVISION,
    "catalog_authority": _R20_CATALOG_AUTHORITY,
    "predecessor_catalog_authority_sha256": (
        _R20_PREDECESSOR_CATALOG_AUTHORITY_SHA256
    ),
    "population_anchor_schedule_key_order": list(
        _R20_POPULATION_ANCHOR_SCHEDULE_KEY_ORDER
    ),
    "population_anchor_schedule_keyset_sha256": (
        _R20_POPULATION_ANCHOR_SCHEDULE_KEYSET_SHA256
    ),
    "population_anchor_schedule_changed_values_sha256": (
        _R20_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES_SHA256
    ),
    "inherited_speck_reject_anchor_schedule_sha256": (
        _R18_SPECK_REJECT_ANCHOR_SCHEDULE_SHA256
    ),
    "duplicate_equivalence_policy_manifest": (
        _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST
    ),
    "duplicate_equivalence_policy_manifest_sha256": (
        _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST_SHA256
    ),
    "duplicate_sentinel_manifest": _R20_DUPLICATE_SENTINEL_MANIFEST,
    "duplicate_sentinel_manifest_sha256": (
        _R20_DUPLICATE_SENTINEL_MANIFEST_SHA256
    ),
    "materialized_spec_changed_paths": _R20_MATERIALIZED_SPEC_CHANGED_PATHS,
    "inherited_reference_prequalification_manifest_sha256": (
        _R17_REFERENCE_PREQUALIFICATION_MANIFEST_SHA256
    ),
    "inherited_initial_decision_gate_manifest_sha256": (
        _R17_INITIAL_DECISION_GATE_MANIFEST_SHA256
    ),
    "development_population_floors": DEVELOPMENT_POPULATION_FLOORS,
    "sanitized_r19_basis": _R20_SANITIZED_R19_BASIS,
    "sanitized_r19_basis_sha256": _R20_SANITIZED_R19_BASIS_SHA256,
    "sanitized_r19_failure_audit_canonical_sha256": (
        _R20_SANITIZED_R19_FAILURE_AUDIT_CANONICAL_SHA256
    ),
    "predecessor_full_artifact_morphology_sha256": (
        _R20_CATALOG_AUTHORITY["predecessor_full_artifact_morphology_sha256"]
    ),
    "full_artifact_morphology_sha256": (
        _R20_CATALOG_AUTHORITY["full_artifact_morphology_sha256"]
    ),
    "exact_morphology_change_count_across_splits": 0,
    "obvious_artifact_duplicate_sentinel_change_count_across_splits": 2,
    "clean_duplicate_construction_change_count_across_splits": 0,
    "morphology_tier_minimum_metric_threshold_and_rate_changes_forbidden": True,
    "vision_truth_guaranteed": False,
}
_R20_PROBE_AUTHORITY_MANIFEST_SHA256 = (
    "584deb41c74d8beeff030c33f1ed0116c4e583c9c60a41e010fb6233972b05a2"
)
_R16_WARNING_ANCHOR_REVISION = (
    "dev-r16-six-per-sparse-family-direct-visible-warning-v1"
)
_R16_WARNING_CONVERSION_REVISION = (
    "dev-r16-one-clean-one-clear-per-sparse-family-v1"
)
_R16_MICROBLOB_ANCHOR_REVISION = (
    "dev-r15-calibration-quantized-microblob-reject-v1"
)
_R16_WARNING_ANCHOR_SHA256 = (
    "bfc0e95e402c4f5751212c67759940c8c01802bb0a938899304ec4db576aa5df"
)
_R16_WARNING_CONVERSION_SHA256 = (
    "0f0f4e0865249d34ff8f83537f60dcaee1c2ee0fd64836551b6aa754251fb8e7"
)
_R16_PREDECESSOR_MORPHOLOGY_SHA256 = (
    "7adf59546337cded9910d17fbff5d383fc36e1058e69f98ed633890c2dd60f5b"
)
_R16_PRESERVED_NONCONVERSION_MORPHOLOGY_SHA256 = (
    "b8e7429a62e78c6e67efbfa6ec8b3b2fb0f16fb07f61ea9c7590f83f1b637ecd"
)
_R16_PRESERVED_NONWARNING_MORPHOLOGY_SHA256 = (
    "72212f11b453526bd6cec7e11420bcb9a0df7bbae2e097168393a5ee0c9a48b4"
)
_R16_ACTIVE_MICROBLOB_ANCHOR_SHA256 = (
    "2c207dfb5249d42056e164e7553091a9a617d8b673aecfb5ea25e4d757651f0c"
)
_GENERATION_STATE_KEYS = {
    "development_edition",
    "development_authority_sha256",
    "spec_sha256",
    "public_nonces",
    "implementation_bindings_sha256",
    "blind_key_commitment",
    "captured_git_head",
    "runtime",
}
_GENERATION_START_KEYS = {
    "artifact",
    "schema_version",
    "authority",
    "formal_use_forbidden",
    "one_shot_consumed",
    "started_at",
    "development_boundary_sha256",
    "state",
}
_GENERATION_SUMMARY_KEYS = {
    "artifact",
    "schema_version",
    "authority",
    "formal_use_forbidden",
    "state",
    "split_separation",
    "splits",
}
_GENERATION_SPLIT_SEPARATION_KEYS = {
    "codes_disjoint",
    "control_ids_disjoint",
    "cluster_ids_disjoint",
    "nonzero_delta_hashes_disjoint",
    "canonical_all_zero_delta_hash_shared",
}
_GENERATION_SPLIT_RECEIPT_KEYS = {
    "split",
    "record_count",
    "contact_sheet_count",
    "review_board_count",
    "manifest_path",
    "manifest_sha256",
    "blank_labels_path",
    "blank_labels_sha256",
    "review_index_path",
    "review_index_sha256",
}
_GENERATION_SEAL_KEYS = {
    "artifact",
    "schema_version",
    "authority",
    "formal_use_forbidden",
    "generation_start_sha256",
    "generation_summary_sha256",
    "spec_sha256",
    "implementation_bindings_sha256",
    "blind_key_commitment",
    "captured_git_head",
}
_GENERATION_COMPLETION_KEYS = {
    "artifact",
    "schema_version",
    "authority",
    "formal_use_forbidden",
    "completed_at",
    "generation_start_sha256",
    "generation_summary_sha256",
    "generation_seal_sha256",
    "spec_sha256",
    "implementation_bindings_sha256",
    "blind_key_commitment",
    "captured_git_head",
}
_GENERATION_FAILURE_KEYS = {
    "artifact",
    "schema_version",
    "authority",
    "formal_use_forbidden",
    "failed_at",
    "generation_start_sha256",
    "error_type",
    "message",
    "development_closed",
}
_REVIEW_INDEX_KEYS = {
    "artifact",
    "schema_version",
    "authority",
    "formal_use_forbidden",
    "split",
    "spec_sha256",
    "views",
    "layout",
    "pages",
}
_REVIEW_INDEX_PAGE_KEYS = {"page_index", "path", "sha256", "item_codes"}
_DEVELOPMENT_MANIFEST_KEYS = {
    "artifact",
    "schema_version",
    "authority",
    "formal_use_forbidden",
    "split",
    "spec_sha256",
    "implementation_bindings_sha256",
    "blind_key_commitment",
    "captured_git_head",
    "runtime",
    "record_count",
    "records",
    "contact_sheet_bundle",
    "warning",
}
_DEVELOPMENT_MANIFEST_RECORD_KEYS = {
    "anonymous_code",
    "control_commitment",
    "reference_commitment",
    "delta_commitment",
}
_DEVELOPMENT_CONTACT_SHEET_KEYS = {
    "view_id",
    "scale_percent",
    "source_crop_xywh",
    "page_index",
    "path",
    "sha256",
    "item_codes",
}
sys.path.insert(0, str(CODE_ROOT))

import common  # noqa: E402
import control_catalog  # noqa: E402
from control_catalog import contact_sheet_pages, expected_controls  # noqa: E402
from metrics_v2_r6 import measure  # noqa: E402


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_json_exclusive(path: Path, value: Any) -> str:
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"development artifact already exists: {path}")
    payload = _json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    return _sha256(payload)


def _write_bytes_exclusive(path: Path, payload: bytes) -> str:
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"development artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(payload)
    return _sha256(payload)


def _read_json(path: Path) -> dict[str, Any]:
    return _read_json_payload(path.read_bytes(), str(path))


def _read_json_payload(payload: bytes, context: str) -> dict[str, Any]:
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"development JSON root must be an object: {context}")
    return value


def _sha256_file(path: Path) -> str:
    return _sha256(path.read_bytes())


def _is_link_like(path: Path) -> bool:
    is_junction = getattr(os.path, "isjunction", None)
    return path.is_symlink() or bool(is_junction and is_junction(path))


def _assert_no_link_like_ancestors(path: Path, lexical_root: Path) -> None:
    candidate = Path(os.path.abspath(path))
    root = Path(os.path.abspath(lexical_root))
    if candidate != root and root not in candidate.parents:
        raise RuntimeError(f"development path escapes lexical root: {path}")
    while True:
        if _is_link_like(candidate):
            raise RuntimeError(
                f"development path contains a symlink or junction: {candidate}"
            )
        if candidate == root:
            break
        candidate = candidate.parent


def _assert_development_boundary(*, root_must_not_exist: bool) -> None:
    configured = [name for name in FORMAL_ENVIRONMENT if os.environ.get(name)]
    if configured:
        raise RuntimeError(f"formal r6 environment is set: {configured}")
    if FORMAL_ROOT.exists() or _is_link_like(FORMAL_ROOT):
        raise RuntimeError("exact formal r6 artifact root already exists")
    resolved_repo = REPO_ROOT.resolve()
    resolved_dev = DEV_ROOT.resolve()
    resolved_formal = FORMAL_ROOT.resolve()
    if (
        resolved_dev == resolved_repo
        or resolved_repo not in resolved_dev.parents
        or resolved_repo not in resolved_formal.parents
        or resolved_dev == resolved_formal
        or resolved_dev in resolved_formal.parents
        or resolved_formal in resolved_dev.parents
    ):
        raise RuntimeError("development/formal root boundary is unsafe")
    _assert_no_link_like_ancestors(DEV_ROOT, REPO_ROOT)
    if root_must_not_exist and (DEV_ROOT.exists() or _is_link_like(DEV_ROOT)):
        raise RuntimeError(f"development root already exists: {DEV_ROOT}")


def _assert_private_analysis_boundary(*, analysis_must_exist: bool) -> None:
    _assert_development_boundary(root_must_not_exist=False)
    resolved_dev = DEV_ROOT.resolve(strict=True)
    expected_parent = (DEV_ROOT / "private").resolve(strict=True)
    resolved_parent = PRIVATE_ANALYSIS_ROOT.parent.resolve(strict=True)
    if (
        expected_parent != resolved_parent
        or resolved_dev not in resolved_parent.parents
    ):
        raise RuntimeError("development private-analysis parent escapes DEV_ROOT")
    _assert_no_link_like_ancestors(PRIVATE_ANALYSIS_ROOT.parent, REPO_ROOT)
    if analysis_must_exist:
        if not PRIVATE_ANALYSIS_ROOT.is_dir():
            raise RuntimeError("development private-analysis root is not a directory")
        _assert_no_link_like_ancestors(PRIVATE_ANALYSIS_ROOT, REPO_ROOT)
        resolved_analysis = PRIVATE_ANALYSIS_ROOT.resolve(strict=True)
        if (
            resolved_dev not in resolved_analysis.parents
            or resolved_analysis.parent != resolved_parent
        ):
            raise RuntimeError("development private-analysis root escapes DEV_ROOT")


def _validate_dev_r17_spec_authority(value: dict[str, Any]) -> None:
    sparse_families = (
        "artifact-speck",
        "artifact-microblob",
        "artifact-short-dash",
        "artifact-parallel-bundle",
    )
    public_nonces = {
        split: value.get("splits", {}).get(split, {}).get("public_nonce")
        for split in ("calibration", "holdout")
    }
    cluster_prefix = value.get("independent_condition_clusters", {}).get(
        "message_prefix"
    )
    private_domains = value.get("control_catalog_authority", {}).get(
        "private_identity_domains"
    )
    blind = value.get("blind_derivation", {})
    rendering = value.get("rendering", {})
    schedule = value.get("population_anchor_schedule", {})
    expected_rotations = {
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
    }
    fine_grain_tiers = {
        "clean-candidate": 5,
        "warning-candidate": 4,
        "clear-reject-candidate": 7,
        "dominant-reject-candidate": 4,
    }
    sparse_tiers = {
        "clean-candidate": 4,
        "warning-candidate": 6,
        "clear-reject-candidate": 6,
        "dominant-reject-candidate": 4,
    }
    expected_tiers = {
        "artifact-fine-grain": fine_grain_tiers,
        **{family: sparse_tiers for family in sparse_families},
    }
    expected_conversion_sources = {
        family: {"clean-candidate": 1, "clear-reject-candidate": 1}
        for family in sparse_families
    }
    if (
        public_nonces != _R17_PUBLIC_NONCES
        or cluster_prefix != "microtexture-v2-r6/private-condition-cluster/v12/"
        or private_domains != _R17_PRIVATE_IDENTITY_DOMAINS
        or blind.get("key_commitment_message")
        != "microtexture-v2-r6/key-commitment/v11"
        or blind.get("seed_message_prefix") != "microtexture-v2-r6/render-seed/v12/"
        or blind.get("code_message_prefix") != "microtexture-v2-r6/opaque-code/v12/"
        or rendering.get("public_commitment_domain")
        != "microtexture-v2-r6/public-payload-commitment/v13/"
        "{control|reference|delta}/{anonymous_code}/{raw-sha256-bytes}"
        or schedule.get("revision") != _R17_SCHEDULE_REVISION
        or schedule.get("fresh_from_closed_dev_r16") is not True
        or schedule.get("r16_parameter_nonce_reuse_forbidden") is not True
        or schedule.get("r17_per_family_residue_rotation") != expected_rotations
        or schedule.get("tier_counts_per_artifact_family") != expected_tiers
        or schedule.get("inherited_warning_acceptance_anchor_revision")
        != "dev-r14-quantized-direct-visible-sparse-warning-v1"
        or schedule.get("inherited_warning_acceptance_anchor_conditions_per_split")
        != 16
        or schedule.get("inherited_warning_acceptance_anchor_schedule_sha256")
        != "5e997df4c7d4e0c6106b3060437235a7f665b08a6b02e00a86f4a4f024dc77e6"
        or schedule.get("warning_acceptance_anchor_revision")
        != _R16_WARNING_ANCHOR_REVISION
        or schedule.get("warning_acceptance_anchor_schedule_sha256")
        != _R16_WARNING_ANCHOR_SHA256
        or schedule.get("calibration_microblob_clear_reject_anchor_manifest", {}).get(
            "revision"
        )
        != _R16_MICROBLOB_ANCHOR_REVISION
        or schedule.get("r17_parameter_nonce_bases") != _R17_PARAMETER_NONCE_BASES
        or schedule.get("private_reference_prequalification_manifest")
        != _R17_REFERENCE_PREQUALIFICATION_MANIFEST
        or schedule.get("private_reference_prequalification_manifest_sha256")
        != _R17_REFERENCE_PREQUALIFICATION_MANIFEST_SHA256
        or _sha256(
            common.canonical_json_bytes(
                schedule.get("private_reference_prequalification_manifest")
            )
        )
        != _R17_REFERENCE_PREQUALIFICATION_MANIFEST_SHA256
        or schedule.get("initial_decision_gate_manifest")
        != _R17_INITIAL_DECISION_GATE_MANIFEST
        or schedule.get("initial_decision_gate_manifest_sha256")
        != _R17_INITIAL_DECISION_GATE_MANIFEST_SHA256
        or _sha256(
            common.canonical_json_bytes(schedule.get("initial_decision_gate_manifest"))
        )
        != _R17_INITIAL_DECISION_GATE_MANIFEST_SHA256
        or schedule.get("preserved_r16_artifact_morphology_conditions_across_splits")
        != 200
        or schedule.get("preserved_r16_artifact_morphology_sha256")
        != _R17_PRESERVED_R16_ARTIFACT_MORPHOLOGY_SHA256
        or schedule.get("r17_exact_morphology_change_count_across_splits") != 0
        or schedule.get("warning_conversion_revision")
        != _R16_WARNING_CONVERSION_REVISION
        or schedule.get("warning_conversion_conditions_per_split") != 8
        or schedule.get("warning_conversion_source_tiers_per_sparse_family")
        != expected_conversion_sources
        or schedule.get("warning_conversion_schedule_sha256")
        != _R16_WARNING_CONVERSION_SHA256
        or schedule.get("exact_morphology_change_count_across_splits") != 16
        or schedule.get("nonconversion_morphology_change_forbidden") is not True
        or schedule.get("predecessor_full_morphology_sha256")
        != _R16_PREDECESSOR_MORPHOLOGY_SHA256
        or schedule.get("preserved_nonconversion_morphology_conditions_across_splits")
        != 184
        or schedule.get("preserved_nonconversion_morphology_sha256")
        != _R16_PRESERVED_NONCONVERSION_MORPHOLOGY_SHA256
        or schedule.get("preserved_nonwarning_morphology_conditions_across_splits")
        != 144
        or schedule.get("preserved_nonwarning_morphology_sha256")
        != _R16_PRESERVED_NONWARNING_MORPHOLOGY_SHA256
        or schedule.get("warning_acceptance_anchor_conditions_per_split") != 24
        or schedule.get("warning_acceptance_anchor_conditions_per_family")
        != {family: 6 for family in sparse_families}
        or schedule.get(
            "warning_acceptance_anchor_structural_miss_budget_against_development_floor"
        )
        != 11
        or schedule.get("calibration_microblob_clear_reject_anchor_conditions") != 7
        or schedule.get("calibration_microblob_clear_reject_anchor_schedule_sha256")
        != "dd2ce7fd13f624bd065e8c7a6bacc2ab8bd593821dec8d46250a40e57ef64833"
        or schedule.get("calibration_microblob_clear_reject_active_indices")
        != [1, 2, 9, 13, 17, 18]
        or schedule.get("calibration_microblob_clear_reject_active_conditions") != 6
        or schedule.get("calibration_microblob_clear_reject_converted_to_warning_index")
        != 16
        or schedule.get("calibration_microblob_clear_reject_active_schedule_sha256")
        != _R16_ACTIVE_MICROBLOB_ANCHOR_SHA256
        or schedule.get("speck_reject_source_anchor_conditions_per_split") != 11
        or schedule.get("speck_reject_active_anchor_conditions_per_split") != 10
        or schedule.get(
            "speck_reject_anchor_structural_miss_budget_against_development_floor"
        )
        != 4
    ):
        raise RuntimeError("development dev-r17 spec/domain authority drift")


def _development_blind_commitment(
    key: bytes, message: str = _R20_KEY_COMMITMENT_MESSAGE
) -> str:
    if len(key) != 32:
        raise RuntimeError("development blind key must contain exactly 32 bytes")
    return hmac.new(
        key, message.encode("ascii"), hashlib.sha256
    ).hexdigest()


def _project_materialized_r18_authority_to_r17(
    value: dict[str, Any],
) -> dict[str, Any]:
    """Reconstruct the inherited r17 authority for unchanged-field validation."""

    projected = deepcopy(value)
    for split, nonce in _R17_PUBLIC_NONCES.items():
        projected["splits"][split]["public_nonce"] = nonce
    projected["independent_condition_clusters"]["message_prefix"] = (
        "microtexture-v2-r6/private-condition-cluster/v12/"
    )
    projected["blind_derivation"].update(
        {
            "key_commitment_message": "microtexture-v2-r6/key-commitment/v11",
            "seed_message_prefix": "microtexture-v2-r6/render-seed/v12/",
            "code_message_prefix": "microtexture-v2-r6/opaque-code/v12/",
        }
    )
    projected["rendering"]["public_commitment_domain"] = (
        "microtexture-v2-r6/public-payload-commitment/v13/"
        "{control|reference|delta}/{anonymous_code}/{raw-sha256-bytes}"
    )
    projected["control_catalog_authority"]["private_identity_domains"] = deepcopy(
        _R17_PRIVATE_IDENTITY_DOMAINS
    )
    schedule = projected["population_anchor_schedule"]
    for key in (
        "fresh_from_closed_dev_r17",
        "r17_parameter_nonce_reuse_forbidden",
        "r18_per_family_residue_rotation",
        "r18_parameter_nonce_bases",
        "inherited_r17_schedule_revision",
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
    ):
        schedule.pop(key)
    schedule.update(
        {
            "revision": _R17_SCHEDULE_REVISION,
            "fresh_from_closed_dev_r16": True,
            "r16_parameter_nonce_reuse_forbidden": True,
            "r17_per_family_residue_rotation": deepcopy(
                _R18_PER_FAMILY_RESIDUE_ROTATION
            ),
            "r17_parameter_nonce_bases": deepcopy(_R17_PARAMETER_NONCE_BASES),
            "preserved_r16_artifact_morphology_conditions_across_splits": 200,
            "preserved_r16_artifact_morphology_sha256": (
                _R17_PRESERVED_R16_ARTIFACT_MORPHOLOGY_SHA256
            ),
            "r17_exact_morphology_change_count_across_splits": 0,
            "speck_reject_source_anchor_conditions_per_split": 11,
            "speck_reject_active_anchor_conditions_per_split": 10,
            "speck_reject_anchor_structural_miss_budget_against_development_floor": 4,
            "speck_reject_anchor_truth_guarantee_claimed": False,
            "speck_reject_anchor_schedule": {
                "calibration": {
                    "source_clear_counts": [32, 36, 40, 44, 48, 52, 56],
                    "active_clear_counts": [36, 40, 44, 48, 52, 56],
                    "dominant_counts": [64, 72, 80, 88],
                },
                "holdout": {
                    "source_clear_counts": [34, 38, 42, 46, 50, 54, 58],
                    "active_clear_counts": [34, 38, 42, 46, 50, 58],
                    "dominant_counts": [68, 76, 84, 90],
                },
                "diameter_px": 1,
                "minimum_separation_px": 10,
                "shoulder_fraction": 0.08,
                "amplitude_l_maximum": 12.0,
                "split_morphology_tuples_disjoint": True,
            },
        }
    )
    return projected


def _validate_dev_r18_probe_authority_manifest() -> None:
    manifest = _R18_PROBE_AUTHORITY_MANIFEST
    if (
        set(manifest)
        != {
            "revision",
            "development_edition",
            "development_root_required_repo_relative",
            "public_nonces",
            "blind_identity_domains",
            "zero_key_commitment_test_vector",
            "private_identity_domains",
            "parameter_nonce_bases",
            "schedule_revision",
            "catalog_authority",
            "population_anchor_schedule_keyset_sha256",
            "population_anchor_schedule_changed_values_sha256",
            "speck_reject_anchor_schedule_sha256",
            "materialized_spec_changed_paths",
            "inherited_reference_prequalification_manifest_sha256",
            "inherited_initial_decision_gate_manifest_sha256",
            "development_population_floors",
            "sanitized_r17_basis",
            "metric_threshold_population_and_rate_contract_changes_forbidden",
        }
        or manifest["revision"] != "dev-r18-development-probe-authority-v1"
        or manifest["development_edition"] != "r18"
        or manifest["development_root_required_repo_relative"]
        != "tmp/map-production/microtexture-v2-r6-dev-r18"
        or manifest["public_nonces"] != _R18_PUBLIC_NONCES
        or manifest["blind_identity_domains"]
        != {
            "condition_cluster_prefix": _R18_CLUSTER_PREFIX,
            "key_commitment_message": _R18_KEY_COMMITMENT_MESSAGE,
            "seed_message_prefix": _R18_SEED_MESSAGE_PREFIX,
            "code_message_prefix": _R18_CODE_MESSAGE_PREFIX,
            "public_commitment_domain": _R18_PUBLIC_COMMITMENT_DOMAIN,
        }
        or manifest["zero_key_commitment_test_vector"]
        != _R18_ZERO_KEY_COMMITMENT_TEST_VECTOR
        or manifest["private_identity_domains"]
        != _R18_PRIVATE_IDENTITY_DOMAINS
        or manifest["parameter_nonce_bases"] != _R18_PARAMETER_NONCE_BASES
        or manifest["schedule_revision"] != _R18_SCHEDULE_REVISION
        or manifest["catalog_authority"] != _R18_CATALOG_AUTHORITY
        or manifest["population_anchor_schedule_keyset_sha256"]
        != _R18_POPULATION_ANCHOR_SCHEDULE_KEYSET_SHA256
        or manifest["population_anchor_schedule_changed_values_sha256"]
        != _R18_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES_SHA256
        or manifest["speck_reject_anchor_schedule_sha256"]
        != _R18_SPECK_REJECT_ANCHOR_SCHEDULE_SHA256
        or manifest["materialized_spec_changed_paths"]
        != _R18_MATERIALIZED_SPEC_CHANGED_PATHS
        or _sha256(
            common.canonical_json_bytes(
                sorted(_R18_POPULATION_ANCHOR_SCHEDULE_KEYS)
            )
        )
        != _R18_POPULATION_ANCHOR_SCHEDULE_KEYSET_SHA256
        or _sha256(
            common.canonical_json_bytes(
                _R18_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES
            )
        )
        != _R18_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES_SHA256
        or _sha256(common.canonical_json_bytes(_R18_SPECK_REJECT_ANCHOR_SCHEDULE))
        != _R18_SPECK_REJECT_ANCHOR_SCHEDULE_SHA256
        or _sha256(common.canonical_json_bytes(_R18_SANITIZED_R17_BASIS))
        != _R18_SANITIZED_R17_BASIS_SHA256
        or manifest["inherited_reference_prequalification_manifest_sha256"]
        != _R17_REFERENCE_PREQUALIFICATION_MANIFEST_SHA256
        or manifest["inherited_initial_decision_gate_manifest_sha256"]
        != _R17_INITIAL_DECISION_GATE_MANIFEST_SHA256
        or manifest["development_population_floors"]
        != {
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
        }
        or manifest["sanitized_r17_basis"] != _R18_SANITIZED_R17_BASIS
        or manifest["development_population_floors"]["spot_reject_detection"]
        - manifest["sanitized_r17_basis"]["holdout"][
            "spot_reject_detection"
        ]["observed"]
        != 1
        or manifest["development_population_floors"][
            "tiny_speck_reject_detection"
        ]
        != manifest["sanitized_r17_basis"]["holdout"][
            "tiny_speck_reject_detection"
        ]["development_minimum"]
        or manifest[
            "metric_threshold_population_and_rate_contract_changes_forbidden"
        ]
        is not True
        or _sha256(common.canonical_json_bytes(manifest))
        != _R18_PROBE_AUTHORITY_MANIFEST_SHA256
        or control_catalog.dev_r18_authority_binding() != _R18_CATALOG_AUTHORITY
        or hmac.new(
            bytes(32),
            _R18_KEY_COMMITMENT_MESSAGE.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        != _R18_ZERO_KEY_COMMITMENT_TEST_VECTOR
    ):
        raise RuntimeError("development dev-r18 probe authority manifest drift")
    if (
        set(_R18_PUBLIC_NONCES.values()) & set(_R17_PUBLIC_NONCES.values())
        or set(_R18_PRIVATE_IDENTITY_DOMAINS.values())
        & set(_R17_PRIVATE_IDENTITY_DOMAINS.values())
        or {
            value
            for key, value in _R18_PARAMETER_NONCE_BASES.items()
            if not key.endswith("duplicate_audit")
        }
        & {
            value
            for key, value in _R17_PARAMETER_NONCE_BASES.items()
            if not key.endswith("duplicate_audit")
        }
        or {
            nonce
            for key, values in _R18_PARAMETER_NONCE_BASES.items()
            if key.endswith("duplicate_audit")
            for nonce in values
        }
        & {
            nonce
            for key, values in _R17_PARAMETER_NONCE_BASES.items()
            if key.endswith("duplicate_audit")
            for nonce in values
        }
        or _R18_CLUSTER_PREFIX
        == "microtexture-v2-r6/private-condition-cluster/v12/"
        or _R18_KEY_COMMITMENT_MESSAGE
        == "microtexture-v2-r6/key-commitment/v11"
        or _R18_SEED_MESSAGE_PREFIX == "microtexture-v2-r6/render-seed/v12/"
        or _R18_CODE_MESSAGE_PREFIX == "microtexture-v2-r6/opaque-code/v12/"
    ):
        raise RuntimeError("development dev-r18 freshness separation drift")
    control_catalog._validate_dev_r18_morphology_schedules()


def _validate_dev_r18_spec_authority(value: dict[str, Any]) -> None:
    _validate_dev_r18_probe_authority_manifest()
    schedule = value.get("population_anchor_schedule", {})
    history = value.get("history", {})
    rendering = value.get("rendering", {})
    handling = value.get("development_probe_secret_handling", {})
    catalog = value.get("control_catalog_authority", {})
    public_policy = value.get("public_identity_policy", {})
    if (
        not isinstance(schedule, dict)
        or set(schedule) != _R18_POPULATION_ANCHOR_SCHEDULE_KEYS
        or {
            key: schedule.get(key)
            for key in _R18_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES
        }
        != _R18_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES
        or _public_nonces(value) != _R18_PUBLIC_NONCES
        or value.get("independent_condition_clusters", {}).get("message_prefix")
        != _R18_CLUSTER_PREFIX
        or value.get("blind_derivation", {}).get("key_commitment_message")
        != _R18_KEY_COMMITMENT_MESSAGE
        or value.get("blind_derivation", {}).get("seed_message_prefix")
        != _R18_SEED_MESSAGE_PREFIX
        or value.get("blind_derivation", {}).get("code_message_prefix")
        != _R18_CODE_MESSAGE_PREFIX
        or rendering.get("public_commitment_domain")
        != _R18_PUBLIC_COMMITMENT_DOMAIN
        or rendering.get("hard_speck_integer_core_contract")
        != _R18_HARD_SPECK_INTEGER_CORE_CONTRACT
        or rendering.get("hard_speck_separation_contract")
        != _R18_HARD_SPECK_SEPARATION_CONTRACT
        or rendering.get("hard_speck_reject_anchor_contract")
        != _R18_HARD_SPECK_REJECT_ANCHOR_CONTRACT
        or catalog.get("private_identity_domains")
        != _R18_PRIVATE_IDENTITY_DOMAINS
        or catalog.get("exact_variant_source") != _R18_EXACT_VARIANT_SOURCE
        or handling.get("scope") != _R18_SECRET_SCOPE
        or handling.get("ignored_private_key_required_repo_relative")
        != _R18_PRIVATE_KEY_REPO_RELATIVE
        or public_policy.get("reviewer_access_contract")
        != _R18_REVIEWER_ACCESS_CONTRACT
        or history.get("dev_r18_status") != _R18_HISTORY_STATUS
        or history.get("dev_r18_role") != _R18_HISTORY_ROLE
    ):
        raise RuntimeError("development dev-r18 materialized spec authority drift")
    _validate_dev_r17_spec_authority(
        _project_materialized_r18_authority_to_r17(value)
    )


def _project_materialized_r19_authority_to_r18(
    value: dict[str, Any],
) -> dict[str, Any]:
    """Reconstruct the frozen r18 authority for inherited-byte validation."""

    projected = deepcopy(value)
    history = projected["history"]
    history["dev_r18_status"] = _R18_HISTORY_STATUS
    history["dev_r18_role"] = _R18_HISTORY_ROLE
    for key in (
        "dev_r18_failure_audit",
        "dev_r18_failure_audit_sha256",
        "dev_r19_status",
        "dev_r19_role",
    ):
        history.pop(key, None)
    projected["development_probe_secret_handling"].update(
        {
            "scope": _R18_SECRET_SCOPE,
            "ignored_private_key_required_repo_relative": (
                _R18_PRIVATE_KEY_REPO_RELATIVE
            ),
        }
    )
    for split, nonce in _R18_PUBLIC_NONCES.items():
        projected["splits"][split]["public_nonce"] = nonce
    projected["independent_condition_clusters"]["message_prefix"] = (
        _R18_CLUSTER_PREFIX
    )
    projected["blind_derivation"].update(
        {
            "key_commitment_message": _R18_KEY_COMMITMENT_MESSAGE,
            "seed_message_prefix": _R18_SEED_MESSAGE_PREFIX,
            "code_message_prefix": _R18_CODE_MESSAGE_PREFIX,
        }
    )
    projected["rendering"].update(
        {
            "public_commitment_domain": _R18_PUBLIC_COMMITMENT_DOMAIN,
            "duplicate_audit_contract": (
                "the clean and obvious-artifact semantic audit groups each contain "
                "two separately coded records with distinct private "
                "reference/control bytes, equal requested-delta bytes, exact "
                "decoded-residual and metric equality, and identical required "
                "semantic labels"
            ),
        }
    )
    projected["control_catalog_authority"].update(
        {
            "exact_variant_source": _R18_EXACT_VARIANT_SOURCE,
            "private_identity_domains": deepcopy(_R18_PRIVATE_IDENTITY_DOMAINS),
            "duplicate_audit_contract": (
                "one clean and one obvious-artifact private semantic-replicate "
                "cluster; each has two separately coded records with distinct "
                "secret-transformed references and controls, the same requested "
                "delta, exact decoded residual and metric equality, and identical "
                "required semantic labels"
            ),
        }
    )
    projected["labels"]["post_marker_private_audits"]["duplicate_artifact"] = (
        "the two separately coded obvious-artifact records must have identical "
        "semantic labels and both must be reject with severity 2 or 3 and "
        "short_line_visible=true"
    )
    projected["public_identity_policy"]["reviewer_access_contract"] = (
        _R18_REVIEWER_ACCESS_CONTRACT
    )
    schedule = projected["population_anchor_schedule"]
    for key in (
        "fresh_from_closed_dev_r18",
        "r18_parameter_nonce_reuse_forbidden",
        "r19_parameter_nonce_bases",
        "inherited_r18_schedule_revision",
        "r19_preserved_r18_artifact_morphology_conditions_across_splits",
        "r19_preserved_r18_artifact_morphology_sha256",
        "r19_exact_morphology_change_count_across_splits",
        "r19_duplicate_equivalence_policy_revision",
        "r19_duplicate_equivalence_policy_manifest",
        "r19_duplicate_equivalence_policy_manifest_sha256",
        "r19_sanitized_r18_basis",
        "r19_sanitized_r18_basis_sha256",
        "r19_morphology_tier_minimum_metric_threshold_and_rate_changes_forbidden",
    ):
        schedule.pop(key)
    schedule.update(
        {
            "revision": _R18_SCHEDULE_REVISION,
            "fresh_from_closed_dev_r17": True,
            "r17_parameter_nonce_reuse_forbidden": True,
            "r18_parameter_nonce_bases": deepcopy(_R18_PARAMETER_NONCE_BASES),
            "inherited_r17_schedule_revision": _R17_SCHEDULE_REVISION,
        }
    )
    return projected


def _validate_dev_r19_probe_authority_manifest() -> None:
    manifest = _R19_PROBE_AUTHORITY_MANIFEST
    if set(manifest) != {
        "revision",
        "development_edition",
        "development_root_required_repo_relative",
        "public_nonces",
        "blind_identity_domains",
        "zero_key_commitment_test_vector",
        "private_identity_domains",
        "parameter_nonce_bases",
        "schedule_revision",
        "catalog_authority",
        "population_anchor_schedule_key_order",
        "population_anchor_schedule_keyset_sha256",
        "population_anchor_schedule_changed_values_sha256",
        "inherited_speck_reject_anchor_schedule_sha256",
        "duplicate_equivalence_policy_manifest",
        "duplicate_equivalence_policy_manifest_sha256",
        "materialized_spec_changed_paths",
        "inherited_reference_prequalification_manifest_sha256",
        "inherited_initial_decision_gate_manifest_sha256",
        "development_population_floors",
        "sanitized_r18_basis",
        "sanitized_r18_basis_sha256",
        "predecessor_full_artifact_morphology_sha256",
        "full_artifact_morphology_sha256",
        "exact_morphology_change_count_across_splits",
        "morphology_tier_minimum_metric_threshold_and_rate_changes_forbidden",
    }:
        raise RuntimeError("development dev-r19 authority manifest schema drift")
    if (
        manifest["revision"] != "dev-r19-development-probe-authority-v1"
        or manifest["development_edition"] != "r19"
        or manifest["development_root_required_repo_relative"]
        != "tmp/map-production/microtexture-v2-r6-dev-r19"
        or manifest["public_nonces"] != _R19_PUBLIC_NONCES
        or manifest["blind_identity_domains"]
        != {
            "condition_cluster_prefix": _R19_CLUSTER_PREFIX,
            "key_commitment_message": _R19_KEY_COMMITMENT_MESSAGE,
            "seed_message_prefix": _R19_SEED_MESSAGE_PREFIX,
            "code_message_prefix": _R19_CODE_MESSAGE_PREFIX,
            "public_commitment_domain": _R19_PUBLIC_COMMITMENT_DOMAIN,
        }
        or manifest["zero_key_commitment_test_vector"]
        != _R19_ZERO_KEY_COMMITMENT_TEST_VECTOR
        or manifest["private_identity_domains"]
        != _R19_PRIVATE_IDENTITY_DOMAINS
        or manifest["parameter_nonce_bases"] != _R19_PARAMETER_NONCE_BASES
        or manifest["schedule_revision"] != _R19_SCHEDULE_REVISION
        or manifest["catalog_authority"] != _R19_CATALOG_AUTHORITY
        or manifest["population_anchor_schedule_key_order"]
        != list(_R19_POPULATION_ANCHOR_SCHEDULE_KEY_ORDER)
        or len(_R19_POPULATION_ANCHOR_SCHEDULE_KEY_ORDER) != 84
        or len(_R19_POPULATION_ANCHOR_SCHEDULE_KEYS) != 84
        or manifest["population_anchor_schedule_keyset_sha256"]
        != _R19_POPULATION_ANCHOR_SCHEDULE_KEYSET_SHA256
        or manifest["population_anchor_schedule_changed_values_sha256"]
        != _R19_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES_SHA256
        or manifest["inherited_speck_reject_anchor_schedule_sha256"]
        != _R18_SPECK_REJECT_ANCHOR_SCHEDULE_SHA256
        or manifest["duplicate_equivalence_policy_manifest"]
        != _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST
        or manifest["duplicate_equivalence_policy_manifest_sha256"]
        != _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST_SHA256
        or manifest["materialized_spec_changed_paths"]
        != _R19_MATERIALIZED_SPEC_CHANGED_PATHS
        or manifest["inherited_reference_prequalification_manifest_sha256"]
        != _R17_REFERENCE_PREQUALIFICATION_MANIFEST_SHA256
        or manifest["inherited_initial_decision_gate_manifest_sha256"]
        != _R17_INITIAL_DECISION_GATE_MANIFEST_SHA256
        or manifest["development_population_floors"]
        != DEVELOPMENT_POPULATION_FLOORS
        or manifest["sanitized_r18_basis"] != _R19_SANITIZED_R18_BASIS
        or manifest["sanitized_r18_basis_sha256"]
        != _R19_SANITIZED_R18_BASIS_SHA256
        or manifest["predecessor_full_artifact_morphology_sha256"]
        != "9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365"
        or manifest["full_artifact_morphology_sha256"]
        != manifest["predecessor_full_artifact_morphology_sha256"]
        or manifest["exact_morphology_change_count_across_splits"] != 0
        or manifest[
            "morphology_tier_minimum_metric_threshold_and_rate_changes_forbidden"
        ]
        is not True
        or _sha256(
            common.canonical_json_bytes(
                sorted(_R19_POPULATION_ANCHOR_SCHEDULE_KEYS)
            )
        )
        != _R19_POPULATION_ANCHOR_SCHEDULE_KEYSET_SHA256
        or _sha256(
            common.canonical_json_bytes(
                _R19_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES
            )
        )
        != _R19_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES_SHA256
        or _sha256(
            common.canonical_json_bytes(
                _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST
            )
        )
        != _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST_SHA256
        or _sha256(common.canonical_json_bytes(_R19_SANITIZED_R18_BASIS))
        != _R19_SANITIZED_R18_BASIS_SHA256
        or _sha256(common.canonical_json_bytes(manifest))
        != _R19_PROBE_AUTHORITY_MANIFEST_SHA256
        or manifest["development_root_required_repo_relative"]
        != "tmp/map-production/microtexture-v2-r6-dev-r19"
        or control_catalog.dev_r19_authority_binding() != _R19_CATALOG_AUTHORITY
        or control_catalog._R19_SANITIZED_R18_BASIS
        != _R19_SANITIZED_R18_BASIS
        or control_catalog._R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST
        != _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST
        or _development_blind_commitment(bytes(32), _R19_KEY_COMMITMENT_MESSAGE)
        != _R19_ZERO_KEY_COMMITMENT_TEST_VECTOR
    ):
        raise RuntimeError("development dev-r19 probe authority manifest drift")

    if (
        set(_R19_PUBLIC_NONCES.values()) & set(_R18_PUBLIC_NONCES.values())
        or set(_R19_PRIVATE_IDENTITY_DOMAINS.values())
        & set(_R18_PRIVATE_IDENTITY_DOMAINS.values())
        or set(manifest["blind_identity_domains"].values())
        & {
            _R18_CLUSTER_PREFIX,
            _R18_KEY_COMMITMENT_MESSAGE,
            _R18_SEED_MESSAGE_PREFIX,
            _R18_CODE_MESSAGE_PREFIX,
            _R18_PUBLIC_COMMITMENT_DOMAIN,
        }
        or {
            value
            for key, value in _R19_PARAMETER_NONCE_BASES.items()
            if not key.endswith("duplicate_audit")
        }
        & {
            value
            for key, value in _R18_PARAMETER_NONCE_BASES.items()
            if not key.endswith("duplicate_audit")
        }
        or {
            nonce
            for key, values in _R19_PARAMETER_NONCE_BASES.items()
            if key.endswith("duplicate_audit")
            for nonce in values
        }
        & {
            nonce
            for key, values in _R18_PARAMETER_NONCE_BASES.items()
            if key.endswith("duplicate_audit")
            for nonce in values
        }
    ):
        raise RuntimeError("development dev-r19 freshness separation drift")
    _validate_dev_r18_probe_authority_manifest()
    control_catalog._validate_dev_r19_morphology_schedules()


def _validate_dev_r19_spec_authority(value: dict[str, Any]) -> None:
    _validate_dev_r19_probe_authority_manifest()
    schedule = value.get("population_anchor_schedule", {})
    if (
        not isinstance(schedule, dict)
        or tuple(schedule) != _R19_POPULATION_ANCHOR_SCHEDULE_KEY_ORDER
        or set(schedule) != _R19_POPULATION_ANCHOR_SCHEDULE_KEYS
        or {
            key: schedule.get(key)
            for key in _R19_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES
        }
        != _R19_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES
    ):
        raise RuntimeError("development dev-r19 schedule authority drift")
    for dotted_path, expected in _R19_MATERIALIZED_SPEC_CHANGED_PATHS.items():
        actual: Any = value
        for component in dotted_path.split("."):
            if not isinstance(actual, dict) or component not in actual:
                raise RuntimeError(
                    f"development dev-r19 materialized path missing: {dotted_path}"
                )
            actual = actual[component]
        if actual != expected:
            raise RuntimeError(
                f"development dev-r19 materialized path drift: {dotted_path}"
            )
    _validate_dev_r18_spec_authority(
        _project_materialized_r19_authority_to_r18(value)
    )


def _project_materialized_r20_authority_to_r19(
    value: dict[str, Any],
) -> dict[str, Any]:
    """Reconstruct the frozen r19 authority for inherited-byte validation."""

    projected = deepcopy(value)
    history = projected["history"]
    history["dev_r19_status"] = _R19_HISTORY_STATUS
    history["dev_r19_role"] = _R19_HISTORY_ROLE
    for key in (
        "dev_r19_failure_audit",
        "dev_r19_failure_audit_sha256",
        "dev_r20_status",
        "dev_r20_role",
    ):
        history.pop(key, None)
    projected["metric_definition"]["development_basis"] = _R19_DEVELOPMENT_BASIS
    projected["development_probe_secret_handling"].update(
        {
            "scope": _R19_SECRET_SCOPE,
            "ignored_private_key_required_repo_relative": (
                _R19_PRIVATE_KEY_REPO_RELATIVE
            ),
        }
    )
    for split, nonce in _R19_PUBLIC_NONCES.items():
        projected["splits"][split]["public_nonce"] = nonce
    projected["independent_condition_clusters"]["message_prefix"] = (
        _R19_CLUSTER_PREFIX
    )
    projected["control_catalog_authority"].update(
        {
            "exact_variant_source": _R19_EXACT_VARIANT_SOURCE,
            "private_identity_domains": deepcopy(_R19_PRIVATE_IDENTITY_DOMAINS),
            "duplicate_audit_contract": _R19_CATALOG_DUPLICATE_AUDIT_CONTRACT,
        }
    )
    projected["blind_derivation"].update(
        {
            "key_commitment_message": _R19_KEY_COMMITMENT_MESSAGE,
            "seed_message_prefix": _R19_SEED_MESSAGE_PREFIX,
            "code_message_prefix": _R19_CODE_MESSAGE_PREFIX,
        }
    )
    projected["rendering"].update(
        {
            "public_commitment_domain": _R19_PUBLIC_COMMITMENT_DOMAIN,
            "duplicate_audit_contract": _R19_RENDERING_DUPLICATE_AUDIT_CONTRACT,
        }
    )
    projected["labels"]["post_marker_private_audits"]["duplicate_artifact"] = (
        _R19_LABEL_DUPLICATE_ARTIFACT_CONTRACT
    )
    projected["public_identity_policy"]["reviewer_access_contract"] = (
        _R19_REVIEWER_ACCESS_CONTRACT
    )
    schedule = projected["population_anchor_schedule"]
    for key in _R20_POPULATION_ANCHOR_SCHEDULE_ADDED_KEY_ORDER:
        schedule.pop(key)
    schedule["revision"] = _R19_SCHEDULE_REVISION
    projected["population_anchor_schedule"] = {
        key: schedule[key] for key in _R19_POPULATION_ANCHOR_SCHEDULE_KEY_ORDER
    }
    return projected


def _materialize_dev_r20_spec(value: dict[str, Any]) -> dict[str, Any]:
    """Overlay the tracked r19 spec with the exact in-code r20 probe authority."""

    _validate_dev_r19_spec_authority(value)
    materialized = deepcopy(value)
    schedule = dict(materialized["population_anchor_schedule"])
    schedule.update(deepcopy(_R20_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES))
    materialized["population_anchor_schedule"] = {
        key: schedule[key] for key in _R20_POPULATION_ANCHOR_SCHEDULE_KEY_ORDER
    }
    for dotted_path, expected in _R20_MATERIALIZED_SPEC_CHANGED_PATHS.items():
        components = dotted_path.split(".")
        target: Any = materialized
        for component in components[:-1]:
            if not isinstance(target, dict) or component not in target:
                raise RuntimeError(
                    f"development dev-r20 materialization path missing: {dotted_path}"
                )
            target = target[component]
        if not isinstance(target, dict):
            raise RuntimeError(
                f"development dev-r20 materialization parent drift: {dotted_path}"
            )
        target[components[-1]] = deepcopy(expected)
    return materialized


def _validate_dev_r20_probe_authority_manifest() -> None:
    manifest = _R20_PROBE_AUTHORITY_MANIFEST
    if set(manifest) != {
        "revision",
        "development_edition",
        "development_root_required_repo_relative",
        "public_nonces",
        "blind_identity_domains",
        "zero_key_commitment_test_vector",
        "private_identity_domains",
        "parameter_nonce_bases",
        "schedule_revision",
        "catalog_authority",
        "predecessor_catalog_authority_sha256",
        "population_anchor_schedule_key_order",
        "population_anchor_schedule_keyset_sha256",
        "population_anchor_schedule_changed_values_sha256",
        "inherited_speck_reject_anchor_schedule_sha256",
        "duplicate_equivalence_policy_manifest",
        "duplicate_equivalence_policy_manifest_sha256",
        "duplicate_sentinel_manifest",
        "duplicate_sentinel_manifest_sha256",
        "materialized_spec_changed_paths",
        "inherited_reference_prequalification_manifest_sha256",
        "inherited_initial_decision_gate_manifest_sha256",
        "development_population_floors",
        "sanitized_r19_basis",
        "sanitized_r19_basis_sha256",
        "sanitized_r19_failure_audit_canonical_sha256",
        "predecessor_full_artifact_morphology_sha256",
        "full_artifact_morphology_sha256",
        "exact_morphology_change_count_across_splits",
        "obvious_artifact_duplicate_sentinel_change_count_across_splits",
        "clean_duplicate_construction_change_count_across_splits",
        "morphology_tier_minimum_metric_threshold_and_rate_changes_forbidden",
        "vision_truth_guaranteed",
    }:
        raise RuntimeError("development dev-r20 authority manifest schema drift")
    if (
        manifest["revision"] != "dev-r20-development-probe-authority-v1"
        or manifest["development_edition"] != "r20"
        or manifest["development_root_required_repo_relative"]
        != "tmp/map-production/microtexture-v2-r6-dev-r20"
        or manifest["public_nonces"] != _R20_PUBLIC_NONCES
        or manifest["blind_identity_domains"]
        != {
            "condition_cluster_prefix": _R20_CLUSTER_PREFIX,
            "key_commitment_message": _R20_KEY_COMMITMENT_MESSAGE,
            "seed_message_prefix": _R20_SEED_MESSAGE_PREFIX,
            "code_message_prefix": _R20_CODE_MESSAGE_PREFIX,
            "public_commitment_domain": _R20_PUBLIC_COMMITMENT_DOMAIN,
        }
        or manifest["zero_key_commitment_test_vector"]
        != _R20_ZERO_KEY_COMMITMENT_TEST_VECTOR
        or manifest["private_identity_domains"] != _R20_PRIVATE_IDENTITY_DOMAINS
        or manifest["parameter_nonce_bases"] != _R20_PARAMETER_NONCE_BASES
        or manifest["schedule_revision"] != _R20_SCHEDULE_REVISION
        or manifest["catalog_authority"] != _R20_CATALOG_AUTHORITY
        or manifest["predecessor_catalog_authority_sha256"]
        != _R20_PREDECESSOR_CATALOG_AUTHORITY_SHA256
        or manifest["population_anchor_schedule_key_order"]
        != list(_R20_POPULATION_ANCHOR_SCHEDULE_KEY_ORDER)
        or len(_R20_POPULATION_ANCHOR_SCHEDULE_KEY_ORDER) != 105
        or len(_R20_POPULATION_ANCHOR_SCHEDULE_KEYS) != 105
        or manifest["population_anchor_schedule_keyset_sha256"]
        != _R20_POPULATION_ANCHOR_SCHEDULE_KEYSET_SHA256
        or manifest["population_anchor_schedule_changed_values_sha256"]
        != _R20_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES_SHA256
        or manifest["inherited_speck_reject_anchor_schedule_sha256"]
        != _R18_SPECK_REJECT_ANCHOR_SCHEDULE_SHA256
        or manifest["duplicate_equivalence_policy_manifest"]
        != _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST
        or manifest["duplicate_equivalence_policy_manifest_sha256"]
        != _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST_SHA256
        or manifest["duplicate_sentinel_manifest"]
        != _R20_DUPLICATE_SENTINEL_MANIFEST
        or manifest["duplicate_sentinel_manifest_sha256"]
        != _R20_DUPLICATE_SENTINEL_MANIFEST_SHA256
        or manifest["materialized_spec_changed_paths"]
        != _R20_MATERIALIZED_SPEC_CHANGED_PATHS
        or manifest["inherited_reference_prequalification_manifest_sha256"]
        != _R17_REFERENCE_PREQUALIFICATION_MANIFEST_SHA256
        or manifest["inherited_initial_decision_gate_manifest_sha256"]
        != _R17_INITIAL_DECISION_GATE_MANIFEST_SHA256
        or manifest["development_population_floors"] != DEVELOPMENT_POPULATION_FLOORS
        or manifest["sanitized_r19_basis"] != _R20_SANITIZED_R19_BASIS
        or manifest["sanitized_r19_basis_sha256"]
        != _R20_SANITIZED_R19_BASIS_SHA256
        or manifest["sanitized_r19_failure_audit_canonical_sha256"]
        != _R20_SANITIZED_R19_FAILURE_AUDIT_CANONICAL_SHA256
        or manifest["predecessor_full_artifact_morphology_sha256"]
        != "9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365"
        or manifest["full_artifact_morphology_sha256"]
        != manifest["predecessor_full_artifact_morphology_sha256"]
        or manifest["exact_morphology_change_count_across_splits"] != 0
        or manifest[
            "obvious_artifact_duplicate_sentinel_change_count_across_splits"
        ]
        != 2
        or manifest["clean_duplicate_construction_change_count_across_splits"] != 0
        or manifest[
            "morphology_tier_minimum_metric_threshold_and_rate_changes_forbidden"
        ]
        is not True
        or manifest["vision_truth_guaranteed"] is not False
        or _sha256(
            common.canonical_json_bytes(
                sorted(_R20_POPULATION_ANCHOR_SCHEDULE_KEYS)
            )
        )
        != _R20_POPULATION_ANCHOR_SCHEDULE_KEYSET_SHA256
        or _sha256(
            common.canonical_json_bytes(
                _R20_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES
            )
        )
        != _R20_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES_SHA256
        or _sha256(
            common.canonical_json_bytes(
                _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST
            )
        )
        != _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST_SHA256
        or _sha256(
            common.canonical_json_bytes(_R20_DUPLICATE_SENTINEL_MANIFEST)
        )
        != _R20_DUPLICATE_SENTINEL_MANIFEST_SHA256
        or _sha256(common.canonical_json_bytes(_R20_SANITIZED_R19_BASIS))
        != _R20_SANITIZED_R19_BASIS_SHA256
        or _sha256(common.canonical_json_bytes(_R19_CATALOG_AUTHORITY))
        != _R20_PREDECESSOR_CATALOG_AUTHORITY_SHA256
        or _sha256(common.canonical_json_bytes(manifest))
        != _R20_PROBE_AUTHORITY_MANIFEST_SHA256
        or DEV_ROOT.relative_to(REPO_ROOT).as_posix()
        != manifest["development_root_required_repo_relative"]
        or control_catalog.dev_r20_authority_binding() != _R20_CATALOG_AUTHORITY
        or control_catalog._R20_SANITIZED_R19_BASIS != _R20_SANITIZED_R19_BASIS
        or control_catalog._R20_DUPLICATE_SENTINEL_MANIFEST
        != _R20_DUPLICATE_SENTINEL_MANIFEST
        or control_catalog._R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST
        != _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST
        or _development_blind_commitment(bytes(32))
        != _R20_ZERO_KEY_COMMITMENT_TEST_VECTOR
    ):
        raise RuntimeError("development dev-r20 probe authority manifest drift")

    if (
        set(_R20_PUBLIC_NONCES.values()) & set(_R19_PUBLIC_NONCES.values())
        or set(_R20_PRIVATE_IDENTITY_DOMAINS.values())
        & set(_R19_PRIVATE_IDENTITY_DOMAINS.values())
        or set(manifest["blind_identity_domains"].values())
        & {
            _R19_CLUSTER_PREFIX,
            _R19_KEY_COMMITMENT_MESSAGE,
            _R19_SEED_MESSAGE_PREFIX,
            _R19_CODE_MESSAGE_PREFIX,
            _R19_PUBLIC_COMMITMENT_DOMAIN,
        }
        or {
            value
            for key, value in _R20_PARAMETER_NONCE_BASES.items()
            if not key.endswith("duplicate_audit")
        }
        & {
            value
            for key, value in _R19_PARAMETER_NONCE_BASES.items()
            if not key.endswith("duplicate_audit")
        }
        or {
            nonce
            for key, values in _R20_PARAMETER_NONCE_BASES.items()
            if key.endswith("duplicate_audit")
            for nonce in values
        }
        & {
            nonce
            for key, values in _R19_PARAMETER_NONCE_BASES.items()
            if key.endswith("duplicate_audit")
            for nonce in values
        }
    ):
        raise RuntimeError("development dev-r20 freshness separation drift")
    _validate_dev_r19_probe_authority_manifest()
    control_catalog._validate_dev_r20_morphology_schedules()


def _validate_dev_r20_spec_authority(value: dict[str, Any]) -> None:
    _validate_dev_r20_probe_authority_manifest()
    schedule = value.get("population_anchor_schedule", {})
    if (
        not isinstance(schedule, dict)
        or tuple(schedule) != _R20_POPULATION_ANCHOR_SCHEDULE_KEY_ORDER
        or set(schedule) != _R20_POPULATION_ANCHOR_SCHEDULE_KEYS
        or {
            key: schedule.get(key)
            for key in _R20_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES
        }
        != _R20_POPULATION_ANCHOR_SCHEDULE_CHANGED_VALUES
    ):
        raise RuntimeError("development dev-r20 schedule authority drift")
    for dotted_path, expected in _R20_MATERIALIZED_SPEC_CHANGED_PATHS.items():
        actual: Any = value
        for component in dotted_path.split("."):
            if not isinstance(actual, dict) or component not in actual:
                raise RuntimeError(
                    f"development dev-r20 materialized path missing: {dotted_path}"
                )
            actual = actual[component]
        if actual != expected:
            raise RuntimeError(
                f"development dev-r20 materialized path drift: {dotted_path}"
            )
    projected_r19 = _project_materialized_r20_authority_to_r19(value)
    _validate_dev_r19_spec_authority(projected_r19)
    if _materialize_dev_r20_spec(projected_r19) != value:
        raise RuntimeError("development dev-r20 materialized predecessor round-trip drift")


def _load_spec() -> tuple[dict[str, Any], str]:
    payload = (CODE_ROOT / "preregistered-spec.json").read_bytes()
    digest = _sha256(payload)
    if digest != common.SPEC_SHA256:
        raise RuntimeError("development preregistered spec SHA drift")
    value = json.loads(payload.decode("utf-8"))
    common.validate_preregistered_spec(value)
    _validate_dev_r20_spec_authority(value)
    return value, digest


def _public_nonces(spec: dict[str, Any]) -> dict[str, str]:
    nonces: dict[str, str] = {}
    for split in ("calibration", "holdout"):
        split_spec = spec.get("splits", {}).get(split)
        nonce = split_spec.get("public_nonce") if isinstance(split_spec, dict) else None
        if not isinstance(nonce, str) or not nonce:
            raise RuntimeError(f"{split} public nonce is missing from the spec")
        nonces[split] = nonce
    if len(set(nonces.values())) != len(nonces):
        raise RuntimeError("development split public nonces must be distinct")
    return nonces


def _validate_expected_control_population(controls: list[Any], split: str) -> None:
    if len(controls) != EXPECTED_RECORDS_PER_SPLIT:
        raise RuntimeError(f"{split} development control record-count drift")
    artifact_controls = [
        control for control in controls if control.private_role == "artifact"
    ]
    artifact_clusters = {control.condition_cluster_id for control in artifact_controls}
    cluster_counts = Counter(
        control.condition_cluster_id for control in artifact_controls
    )
    if (
        len(artifact_controls) != EXPECTED_ARTIFACT_RECORDS_PER_SPLIT
        or len(artifact_clusters) != EXPECTED_ARTIFACT_CLUSTERS_PER_SPLIT
        or any(count != 2 for count in cluster_counts.values())
    ):
        raise RuntimeError(f"{split} development artifact population drift")


def _git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


def _validate_development_key_git_boundary(
    spec: dict[str, Any], captured_head: str
) -> Path:
    handling = spec["development_probe_secret_handling"]
    key_relative = str(handling["ignored_private_key_required_repo_relative"])
    key_path = (REPO_ROOT / key_relative).resolve()
    required_path = (DEV_ROOT / "private" / "development-key.bin").resolve()
    if key_path != required_path:
        raise RuntimeError("development private-key path contract drift")

    gitignore_relative = str(handling["gitignore_required_repo_relative"])
    common._tracked_worktree_bytes(REPO_ROOT, captured_head, gitignore_relative)

    head_entry = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", captured_head, "--", key_relative],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if head_entry.returncode != 0:
        raise RuntimeError("development private-key HEAD inspection failed")
    if head_entry.stdout.strip():
        raise RuntimeError("development private-key path exists in captured HEAD")

    index_entry = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", key_relative],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if index_entry.returncode == 0:
        raise RuntimeError("development private-key path is tracked in the Git index")
    if index_entry.returncode != 1:
        raise RuntimeError("development private-key index inspection failed")

    ignored = subprocess.run(
        ["git", "check-ignore", "-v", "--no-index", "--", key_relative],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if ignored.returncode != 0:
        raise RuntimeError("development private-key path is not Git-ignored")
    metadata, separator, matched_path = ignored.stdout.rstrip("\r\n").rpartition("\t")
    source, first_colon, remainder = metadata.partition(":")
    line_number, second_colon, pattern = remainder.partition(":")
    if (
        separator != "\t"
        or matched_path != key_relative
        or first_colon != ":"
        or second_colon != ":"
        or source.replace("\\", "/") != gitignore_relative
        or not line_number.isdigit()
        or int(line_number) < 1
        or pattern != handling["gitignore_required_pattern"]
    ):
        raise RuntimeError(
            "development private-key ignore is not provided by the tracked root .gitignore"
        )
    common.assert_head_unchanged(captured_head)
    return key_path


def _tracked_input_preflight(spec: dict[str, Any], spec_sha: str) -> tuple[str, str]:
    captured_head = _git_head()
    branch = subprocess.check_output(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
    ).strip()
    upstream_ref = subprocess.check_output(
        [
            "git",
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            f"{branch}@{{upstream}}",
        ],
        cwd=REPO_ROOT,
        text=True,
    ).strip()
    upstream_head = subprocess.check_output(
        ["git", "rev-parse", upstream_ref], cwd=REPO_ROOT, text=True
    ).strip()
    if captured_head != upstream_head:
        raise RuntimeError("development HEAD is not equal to its upstream ref")
    repository = common.repository_root()
    code_relative = CODE_ROOT.relative_to(repository)
    if code_relative.as_posix() != spec["roots"]["code_root_required_repo_relative"]:
        raise RuntimeError("development CODE_ROOT contract drift")
    for relative in spec["authority_files"]:
        common._tracked_worktree_bytes(
            repository, captured_head, (code_relative / relative).as_posix()
        )
    bindings = common.validate_implementation_bindings()
    if bindings["spec_sha256"] != spec_sha:
        raise RuntimeError("development implementation/spec binding drift")
    common.verify_tracked_development_history(repository, captured_head, spec)
    common.verify_tracked_foundation_corpus_provenance(
        repository, captured_head, spec["foundation_corpus"]
    )
    _validate_development_key_git_boundary(spec, captured_head)
    common.assert_head_unchanged(captured_head)
    return captured_head, _sha256_file(CODE_ROOT / "implementation-bindings.json")


def _review_board_payload(
    controls: list[Any],
    views: list[dict[str, Any]],
    page_index: int,
) -> tuple[list[str], bytes]:
    panel_width, panel_height = 512, REVIEW_PANEL_HEIGHT
    header_height = REVIEW_HEADER_HEIGHT
    rows = REVIEW_ROWS_PER_PAGE
    selected = controls[(page_index - 1) * rows : page_index * rows]
    canvas = Image.new(
        "L", (panel_width * len(views), (panel_height + header_height) * rows), 32
    )
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=16)
    for row, control in enumerate(selected):
        for column, view in enumerate(views):
            left, top, width, height = [int(item) for item in view["source_crop_xywh"]]
            crop = Image.fromarray(control.control).crop(
                (left, top, left + width, top + height)
            )
            display = crop.resize(
                (panel_width, panel_height), resample=Image.Resampling.NEAREST
            )
            x = column * panel_width
            y = row * (panel_height + header_height)
            draw.text(
                (x + 6, y + 14),
                f"ROW {row + 1}  {control.anonymous_code}  {view['id']}",
                fill=255,
                font=font,
            )
            canvas.paste(display, (x, y + header_height))
    stream = io.BytesIO()
    canvas.save(stream, format="PNG", compress_level=6, optimize=False)
    return [item.anonymous_code for item in selected], stream.getvalue()


def _review_board(
    controls: list[Any],
    views: list[dict[str, Any]],
    page_index: int,
    output: Path,
) -> tuple[list[str], str]:
    codes, payload = _review_board_payload(controls, views, page_index)
    return codes, _write_bytes_exclusive(output, payload)


def _generate_split(
    spec: dict[str, Any],
    split: str,
    key: bytes,
    state: dict[str, Any],
) -> dict[str, Any]:
    controls = sorted(
        expected_controls(spec, split, key), key=lambda item: item.anonymous_code
    )
    _validate_expected_control_population(controls, split)
    pages = contact_sheet_pages(spec, split, controls)
    page_counts = Counter(page.view_id for page in pages)
    expected_views = {str(view["id"]) for view in spec["contact_sheets"]["views"]}
    if (
        len(pages) != EXPECTED_CONTACT_SHEETS_PER_SPLIT
        or set(page_counts) != expected_views
        or any(
            count != EXPECTED_REVIEW_PAGES_PER_SPLIT for count in page_counts.values()
        )
    ):
        raise RuntimeError(f"{split} development contact-sheet count drift")
    public_root = DEV_ROOT / "public" / split
    sheet_root = public_root / "contact-sheets"
    sheet_root.mkdir(parents=True, exist_ok=False)
    sheet_bundle: list[dict[str, Any]] = []
    for page in pages:
        name = Path(page.path).name
        target = sheet_root / name
        _write_bytes_exclusive(target, page.png_bytes)
        entry = page.manifest_entry()
        entry["path"] = target.relative_to(DEV_ROOT).as_posix()
        sheet_bundle.append(entry)

    records = [
        {
            "anonymous_code": control.anonymous_code,
            "control_commitment": control.control_commitment,
            "reference_commitment": control.reference_commitment,
            "delta_commitment": control.delta_commitment,
        }
        for control in controls
    ]
    manifest = {
        "artifact": "microtexture-v2-r6-development-control-manifest",
        "schema_version": "microtexture-v2-r6-development-control-manifest/1",
        "authority": False,
        "formal_use_forbidden": True,
        "split": split,
        "spec_sha256": state["spec_sha256"],
        "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        "blind_key_commitment": state["blind_key_commitment"],
        "captured_git_head": state["captured_git_head"],
        "runtime": state["runtime"],
        "record_count": len(records),
        "records": records,
        "contact_sheet_bundle": sheet_bundle,
        "warning": "DEVELOPMENT ONLY; not a formal r6 manifest or authority artifact.",
    }
    manifest_path = public_root / "manifest.dev.json"
    manifest_sha = _write_json_exclusive(manifest_path, manifest)
    labels = {
        "artifact": "microtexture-v2-r6-root-vision-labels",
        "schema_version": "microtexture-v2-r6-root-vision-labels/2",
        "split": split,
        "spec_sha256": state["spec_sha256"],
        "manifest_sha256": manifest_sha,
        "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        "blind_key_commitment": state["blind_key_commitment"],
        "runtime": state["runtime"],
        "contact_sheet_bundle": sheet_bundle,
        "reviewer": "Root",
        "items": [
            {
                "anonymous_code": control.anonymous_code,
                "disposition": None,
                "grain_visible": None,
                "tiny_speck_visible": None,
                "microblob_visible": None,
                "short_line_visible": None,
                "parallel_bundle_visible": None,
                "severity_0_to_3": None,
                "reviewed_at_200_percent": None,
                "reviewed_at_all_400_percent_quadrants": None,
                "notes": "",
            }
            for control in controls
        ],
    }
    labels_sha = _write_json_exclusive(public_root / "labels.blank.dev.json", labels)

    board_root = public_root / "review-boards"
    review_pages = []
    for page_index in range(1, EXPECTED_REVIEW_PAGES_PER_SPLIT + 1):
        target = board_root / f"review-page-{page_index:03d}.png"
        codes, digest = _review_board(
            controls, spec["contact_sheets"]["views"], page_index, target
        )
        review_pages.append(
            {
                "page_index": page_index,
                "path": target.relative_to(DEV_ROOT).as_posix(),
                "sha256": digest,
                "item_codes": codes,
            }
        )
    review_index = {
        "artifact": "microtexture-v2-r6-development-review-index",
        "schema_version": "microtexture-v2-r6-development-review-index/1",
        "authority": False,
        "formal_use_forbidden": True,
        "split": split,
        "spec_sha256": state["spec_sha256"],
        "views": [view["id"] for view in spec["contact_sheets"]["views"]],
        "layout": "one anonymous code per row with a black header above its panels; full-200 plus all four 400-percent quadrants",
        "pages": review_pages,
    }
    review_index_sha = _write_json_exclusive(
        public_root / "review-index.dev.json", review_index
    )
    return {
        "split": split,
        "record_count": len(controls),
        "contact_sheet_count": len(pages),
        "review_board_count": len(review_pages),
        "manifest_path": manifest_path.relative_to(DEV_ROOT).as_posix(),
        "manifest_sha256": manifest_sha,
        "blank_labels_path": (public_root / "labels.blank.dev.json")
        .relative_to(DEV_ROOT)
        .as_posix(),
        "blank_labels_sha256": labels_sha,
        "review_index_path": (public_root / "review-index.dev.json")
        .relative_to(DEV_ROOT)
        .as_posix(),
        "review_index_sha256": review_index_sha,
        "codes": [control.anonymous_code for control in controls],
        "control_ids": [control.control_id for control in controls],
        "cluster_ids": [control.condition_cluster_id for control in controls],
        "nonzero_delta_hashes": [
            control.delta_float32_sha256
            for control in controls
            if control.requested_delta.any()
        ],
        "zero_delta_hashes": [
            control.delta_float32_sha256
            for control in controls
            if not control.requested_delta.any()
        ],
    }


_FLAG_FIELDS = {
    "g": "grain_visible",
    "t": "tiny_speck_visible",
    "b": "microblob_visible",
    "l": "short_line_visible",
    "p": "parallel_bundle_visible",
}


def _checked_dev_file(relative: str, context: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise RuntimeError(f"{context} development path is invalid")
    path = DEV_ROOT / Path(relative)
    resolved_root = DEV_ROOT.resolve()
    resolved = path.resolve()
    if resolved_root not in resolved.parents or not path.is_file() or path.is_symlink():
        raise RuntimeError(f"{context} development path escaped or is not a file")
    return path


def _require_sha256(value: Any, context: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise RuntimeError(f"{context} must be a lowercase SHA-256 digest")


def _sanitized_error_message(error: BaseException) -> str:
    message = str(error).strip() or "exception without a message"
    message = re.sub(
        r"(?i)(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])",
        "[redacted-key-like-value]",
        message,
    )
    return re.sub(
        r"(?i)(?<![0-9a-f])[0-9a-f]{24}(?![0-9a-f])",
        "[redacted-opaque-code]",
        message,
    )[:512]


def _expected_generation_split_paths(split: str) -> dict[str, str]:
    prefix = f"public/{split}"
    return {
        "manifest_path": f"{prefix}/manifest.dev.json",
        "blank_labels_path": f"{prefix}/labels.blank.dev.json",
        "review_index_path": f"{prefix}/review-index.dev.json",
    }


def _validate_generation_summary(
    summary: dict[str, Any], state: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    common.require_exact_keys(
        summary, _GENERATION_SUMMARY_KEYS, "development generation summary"
    )
    if (
        summary.get("artifact")
        != "microtexture-v2-r6-development-generation-summary"
        or summary.get("schema_version")
        != "microtexture-v2-r6-development-generation-summary/1"
        or summary.get("authority") is not False
        or summary.get("formal_use_forbidden") is not True
        or summary.get("state") != state
    ):
        raise RuntimeError("development generation summary metadata drift")

    separation = summary.get("split_separation")
    common.require_exact_keys(
        separation,
        _GENERATION_SPLIT_SEPARATION_KEYS,
        "development generation split separation",
    )
    if any(separation[field] is not True for field in _GENERATION_SPLIT_SEPARATION_KEYS):
        raise RuntimeError("development generation split separation drift")

    raw_receipts = summary.get("splits")
    if not isinstance(raw_receipts, list) or len(raw_receipts) != 2:
        raise RuntimeError("development generation split receipt count drift")
    if [receipt.get("split") for receipt in raw_receipts if isinstance(receipt, dict)] != [
        "calibration",
        "holdout",
    ]:
        raise RuntimeError("development generation split receipt order drift")
    receipts: dict[str, dict[str, Any]] = {}
    for index, receipt in enumerate(raw_receipts):
        context = f"development generation split receipt[{index}]"
        common.require_exact_keys(receipt, _GENERATION_SPLIT_RECEIPT_KEYS, context)
        split = receipt.get("split")
        if split not in {"calibration", "holdout"} or split in receipts:
            raise RuntimeError(f"{context} split drift")
        expected_paths = _expected_generation_split_paths(split)
        if (
            type(receipt.get("record_count")) is not int
            or receipt.get("record_count") != EXPECTED_RECORDS_PER_SPLIT
            or type(receipt.get("contact_sheet_count")) is not int
            or receipt.get("contact_sheet_count")
            != EXPECTED_CONTACT_SHEETS_PER_SPLIT
            or type(receipt.get("review_board_count")) is not int
            or receipt.get("review_board_count")
            != EXPECTED_REVIEW_PAGES_PER_SPLIT
            or any(receipt.get(field) != value for field, value in expected_paths.items())
        ):
            raise RuntimeError(f"{context} count/path drift")
        for field in (
            "manifest_sha256",
            "blank_labels_sha256",
            "review_index_sha256",
        ):
            _require_sha256(receipt.get(field), f"{context}.{field}")
        receipts[split] = receipt
    if set(receipts) != {"calibration", "holdout"}:
        raise RuntimeError("development generation split receipt coverage drift")
    return receipts


def _verify_public_generation_receipt(
    split: str, receipt: dict[str, Any]
) -> dict[str, bytes]:
    expected_paths = _expected_generation_split_paths(split)
    captured: dict[str, bytes] = {}
    for path_field, expected_relative in expected_paths.items():
        if receipt.get(path_field) != expected_relative:
            raise RuntimeError(f"{split} generation receipt path drift: {path_field}")
        sha_field = path_field.replace("_path", "_sha256")
        path = _checked_dev_file(expected_relative, f"{split} generation receipt")
        payload = path.read_bytes()
        if _sha256(payload) != receipt.get(sha_field):
            raise RuntimeError(f"{split} generation receipt SHA drift: {path_field}")
        captured[path_field] = payload
    return captured


def _load_generation_state(
    spec: dict[str, Any], spec_sha: str
) -> tuple[
    dict[str, Any], dict[str, dict[str, Any]], dict[str, str]
]:
    boundary_path = DEV_ROOT / "DEV-ONLY.json"
    start_path = DEV_ROOT / "generation-start.dev.json"
    summary_path = DEV_ROOT / "generation-summary.dev.json"
    seal_path = DEV_ROOT / "generation-seal.dev.json"
    completion_path = DEV_ROOT / "generation-completion.dev.json"
    failure_path = DEV_ROOT / "generation-failure.dev.json"
    if failure_path.exists() or failure_path.is_symlink():
        raise RuntimeError("development generation is failed and closed")
    required_paths = (
        boundary_path,
        start_path,
        summary_path,
        seal_path,
        completion_path,
    )
    if any(not path.is_file() or path.is_symlink() for path in required_paths):
        raise RuntimeError("development generation terminal artifacts are incomplete")
    boundary_payload = boundary_path.read_bytes()
    start_payload = start_path.read_bytes()
    summary_payload = summary_path.read_bytes()
    seal_payload = seal_path.read_bytes()
    completion_payload = completion_path.read_bytes()
    boundary = _read_json_payload(boundary_payload, str(boundary_path))
    start = _read_json_payload(start_payload, str(start_path))
    summary = _read_json_payload(summary_payload, str(summary_path))
    seal = _read_json_payload(seal_payload, str(seal_path))
    completion = _read_json_payload(completion_payload, str(completion_path))
    generation_start_sha = _sha256(start_payload)
    generation_summary_sha = _sha256(summary_payload)
    generation_seal_sha = _sha256(seal_payload)
    generation_completion_sha = _sha256(completion_payload)
    state = summary.get("state")
    if not isinstance(state, dict):
        raise RuntimeError("development generation state is missing")
    common.require_exact_keys(state, _GENERATION_STATE_KEYS, "development generation state")
    common.require_exact_keys(start, _GENERATION_START_KEYS, "development generation start")
    common.require_exact_keys(
        boundary,
        {
            "artifact",
            "schema_version",
            "authority",
            "formal_use_forbidden",
            "formal_cli_invoked",
            "formal_marker_created",
            "formal_threshold_created",
            "locked_clean_v18_decoded_or_measured",
            "exact_formal_root_absent_before_generation",
            "formal_environment_absent_before_generation",
            *_GENERATION_STATE_KEYS,
        },
        "development generation boundary",
    )
    common.require_exact_keys(seal, _GENERATION_SEAL_KEYS, "development generation seal")
    common.require_exact_keys(
        completion,
        _GENERATION_COMPLETION_KEYS,
        "development generation completion",
    )
    expected_bindings_sha = _sha256_file(CODE_ROOT / "implementation-bindings.json")
    if (
        boundary.get("artifact")
        != "microtexture-v2-r6-development-only-boundary"
        or boundary.get("schema_version")
        != "microtexture-v2-r6-development-only-boundary/1"
        or boundary.get("authority") is not False
        or boundary.get("formal_use_forbidden") is not True
        or boundary.get("formal_cli_invoked") is not False
        or boundary.get("formal_marker_created") is not False
        or boundary.get("formal_threshold_created") is not False
        or boundary.get("locked_clean_v18_decoded_or_measured") is not False
        or boundary.get("exact_formal_root_absent_before_generation") is not True
        or boundary.get("formal_environment_absent_before_generation") is not True
        or state.get("development_edition") != DEVELOPMENT_EDITION
        or state.get("development_authority_sha256")
        != _R20_PROBE_AUTHORITY_MANIFEST_SHA256
        or state.get("spec_sha256") != spec_sha
        or state.get("public_nonces") != _public_nonces(spec)
        or state.get("implementation_bindings_sha256") != expected_bindings_sha
        or not isinstance(state.get("runtime"), dict)
        or {field: boundary[field] for field in _GENERATION_STATE_KEYS} != state
    ):
        raise RuntimeError("development generation boundary/state drift")
    if (
        start.get("artifact")
        != "microtexture-v2-r6-development-generation-start"
        or start.get("schema_version")
        != "microtexture-v2-r6-development-generation-start/1"
        or start.get("authority") is not False
        or start.get("formal_use_forbidden") is not True
        or start.get("one_shot_consumed") is not True
        or start.get("development_boundary_sha256") != _sha256(boundary_payload)
        or start.get("state") != state
    ):
        raise RuntimeError("development generation start drift")
    started_at = common.parse_utc_timestamp(
        start.get("started_at"), "development generation start.started_at"
    )
    for field in (
        "development_authority_sha256",
        "spec_sha256",
        "implementation_bindings_sha256",
        "blind_key_commitment",
    ):
        _require_sha256(state.get(field), f"development generation state.{field}")
    if (
        seal.get("artifact") != "microtexture-v2-r6-development-generation-seal"
        or seal.get("schema_version")
        != "microtexture-v2-r6-development-generation-seal/1"
        or seal.get("authority") is not False
        or seal.get("formal_use_forbidden") is not True
        or seal.get("generation_start_sha256") != generation_start_sha
        or seal.get("generation_summary_sha256") != generation_summary_sha
        or seal.get("spec_sha256") != state["spec_sha256"]
        or seal.get("implementation_bindings_sha256")
        != state["implementation_bindings_sha256"]
        or seal.get("blind_key_commitment") != state["blind_key_commitment"]
        or seal.get("captured_git_head") != state["captured_git_head"]
    ):
        raise RuntimeError("development generation seal drift")
    for field in ("generation_start_sha256", "generation_summary_sha256"):
        _require_sha256(
            seal.get(field),
            f"development generation seal.{field}",
        )
    if (
        completion.get("artifact")
        != "microtexture-v2-r6-development-generation-completion"
        or completion.get("schema_version")
        != "microtexture-v2-r6-development-generation-completion/1"
        or completion.get("authority") is not False
        or completion.get("formal_use_forbidden") is not True
        or completion.get("generation_start_sha256") != generation_start_sha
        or completion.get("generation_summary_sha256") != generation_summary_sha
        or completion.get("generation_seal_sha256") != generation_seal_sha
        or completion.get("spec_sha256") != state["spec_sha256"]
        or completion.get("implementation_bindings_sha256")
        != state["implementation_bindings_sha256"]
        or completion.get("blind_key_commitment") != state["blind_key_commitment"]
        or completion.get("captured_git_head") != state["captured_git_head"]
    ):
        raise RuntimeError("development generation completion drift")
    completed_at = common.parse_utc_timestamp(
        completion.get("completed_at"),
        "development generation completion.completed_at",
    )
    if completed_at < started_at:
        raise RuntimeError("development generation timestamp order drift")
    for field in (
        "generation_start_sha256",
        "generation_summary_sha256",
        "generation_seal_sha256",
    ):
        _require_sha256(
            completion.get(field),
            f"development generation completion.{field}",
        )
    receipts = _validate_generation_summary(summary, state)
    return state, receipts, {
        "generation_start_sha256": generation_start_sha,
        "generation_summary_sha256": generation_summary_sha,
        "generation_seal_sha256": generation_seal_sha,
        "generation_completion_sha256": generation_completion_sha,
    }


def _parse_decisions_payload(
    payload: bytes, context: str
) -> dict[tuple[int, int], dict[str, Any]]:
    decisions: dict[tuple[int, int], dict[str, Any]] = {}
    for line_number, raw_line in enumerate(
        payload.decode("utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=6)
        if len(parts) != 7:
            raise RuntimeError(f"decision DSL field drift: {context}:{line_number}")
        (
            page_text,
            row_text,
            anonymous_code,
            disposition,
            severity_text,
            flags_text,
            notes,
        ) = parts
        if (
            not page_text.isdigit()
            or not row_text.isdigit()
            or not severity_text.isdigit()
        ):
            raise RuntimeError(f"decision DSL numeric drift: {context}:{line_number}")
        page, row, severity = int(page_text), int(row_text), int(severity_text)
        key = (page, row)
        if key in decisions:
            raise RuntimeError(f"duplicate decision: {context}:{page_text}/{row_text}")
        if len(anonymous_code) != 24 or any(
            character not in "0123456789abcdef" for character in anonymous_code
        ):
            raise RuntimeError(
                f"decision DSL anonymous-code drift: {context}:{line_number}"
            )
        if flags_text == "-":
            flags: set[str] = set()
        else:
            flag_tokens = flags_text.split(",")
            flags = set(flag_tokens)
            canonical_flag_tokens = [flag for flag in _FLAG_FIELDS if flag in flags]
            if (
                "" in flags
                or not flags.issubset(_FLAG_FIELDS)
                or flag_tokens != canonical_flag_tokens
            ):
                raise RuntimeError(f"decision DSL flag drift: {context}:{line_number}")
        consistent = (
            (disposition == "clean" and severity == 0 and not flags)
            or (disposition == "warning" and severity == 1 and bool(flags))
            or (disposition == "reject" and severity in {2, 3} and bool(flags))
        )
        if not consistent or not notes:
            raise RuntimeError(f"decision DSL semantic drift: {context}:{line_number}")
        decision = {
            "anonymous_code": anonymous_code,
            "disposition": disposition,
            "severity_0_to_3": severity,
            **{field: flag in flags for flag, field in _FLAG_FIELDS.items()},
            "reviewed_at_200_percent": True,
            "reviewed_at_all_400_percent_quadrants": True,
            "notes": notes,
        }
        common._validate_vision_evidence_notes(decision, context, anonymous_code)
        decisions[key] = decision
    return decisions


def _validate_r17_initial_decision_gate_manifest() -> None:
    manifest = _R17_INITIAL_DECISION_GATE_MANIFEST
    if (
        manifest.get("revision") != _R17_INITIAL_DECISION_GATE_REVISION
        or manifest.get("snapshot_files")
        != {
            "root": "decisions-root.initial.dev.txt",
            "independent": "decisions-independent.initial.dev.txt",
        }
        or manifest.get("receipt_files")
        != {
            "root": "decisions-root.initial.dev.txt.sha256",
            "independent": "decisions-independent.initial.dev.txt.sha256",
        }
        or manifest.get("receipt_format")
        != "lowercase-sha256 two-spaces snapshot-basename newline"
        or manifest.get("final_files")
        != [
            "vision-decisions.dev.txt",
            "decisions-root.dev.txt",
            "decisions-independent.dev.txt",
        ]
        or manifest.get("final_three_way_exact_bytes_required") is not True
        or manifest.get(
            "initial_snapshots_require_official_parser_coverage_and_code_binding"
        )
        is not True
        or manifest.get("visible_flags") != ["g", "t", "b", "l", "p"]
        or manifest.get("final_visible_flag_set_relation")
        != "subset-of-root-initial-intersection-independent-initial"
        or manifest.get("reconciled_fields_not_restricted_by_this_gate")
        != ["disposition", "severity_0_to_3", "notes"]
        or manifest.get("private_role_input") is not False
        or manifest.get("read_only_attribute_required_by_runner") is not False
        or _sha256(common.canonical_json_bytes(manifest))
        != _R17_INITIAL_DECISION_GATE_MANIFEST_SHA256
    ):
        raise RuntimeError("development r17 initial-decision gate manifest drift")


def _read_verified_initial_decision_snapshot(
    split: str,
    reviewer: str,
) -> tuple[bytes, dict[tuple[int, int], dict[str, Any]], str, str]:
    snapshot_name = _R17_INITIAL_DECISION_GATE_MANIFEST["snapshot_files"].get(reviewer)
    receipt_name = _R17_INITIAL_DECISION_GATE_MANIFEST["receipt_files"].get(reviewer)
    if not isinstance(snapshot_name, str) or not isinstance(receipt_name, str):
        raise RuntimeError(f"{split} invalid initial-decision reviewer: {reviewer}")
    snapshot_relative = f"public/{split}/{snapshot_name}"
    receipt_relative = f"public/{split}/{receipt_name}"
    snapshot_path = _checked_dev_file(
        snapshot_relative,
        f"{split} {reviewer} initial Vision decisions",
    )
    receipt_path = _checked_dev_file(
        receipt_relative,
        f"{split} {reviewer} initial Vision decision receipt",
    )
    snapshot_payload = snapshot_path.read_bytes()
    snapshot_sha = _sha256(snapshot_payload)
    receipt_payload = receipt_path.read_bytes()
    expected_receipt = f"{snapshot_sha}  {snapshot_name}\n".encode("ascii")
    if receipt_payload != expected_receipt:
        raise RuntimeError(f"{split} {reviewer} initial Vision decision receipt drift")
    decisions = _parse_decisions_payload(
        snapshot_payload,
        str(snapshot_path),
    )
    return snapshot_payload, decisions, snapshot_sha, _sha256(receipt_payload)


def _verify_bundle_files(entries: Any, context: str) -> dict[str, bytes]:
    if not isinstance(entries, list) or not entries:
        raise RuntimeError(f"{context} bundle is empty")
    seen_paths: set[str] = set()
    captured: dict[str, bytes] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise RuntimeError(f"{context} bundle entry drift: {index}")
        relative, expected_sha = entry.get("path"), entry.get("sha256")
        if not isinstance(relative, str) or relative in seen_paths:
            raise RuntimeError(f"{context} duplicate/invalid path: {index}")
        seen_paths.add(relative)
        path = _checked_dev_file(relative, f"{context}[{index}]")
        payload = path.read_bytes()
        if _sha256(payload) != expected_sha:
            raise RuntimeError(f"{context} SHA drift: {relative}")
        captured[relative] = payload
    return captured


def _verify_contact_sheet_layout(
    entries: list[dict[str, Any]],
    spec: dict[str, Any],
    split: str,
    expected_codes: list[str],
) -> None:
    configured_views = spec["contact_sheets"]["views"]
    expected_views = [str(view["id"]) for view in configured_views]
    if len(expected_views) != 5 or len(set(expected_views)) != 5:
        raise RuntimeError(f"{split} development contact-sheet view drift")
    by_view_page: dict[tuple[str, int], list[str]] = {}
    for entry_index, entry in enumerate(entries):
        common.require_exact_keys(
            entry,
            _DEVELOPMENT_CONTACT_SHEET_KEYS,
            f"{split} development contact sheet[{entry_index}]",
        )
        expected_view_position = entry_index // EXPECTED_REVIEW_PAGES_PER_SPLIT
        expected_page_index = entry_index % EXPECTED_REVIEW_PAGES_PER_SPLIT + 1
        expected_view = configured_views[expected_view_position]
        expected_view_id = str(expected_view["id"])
        view_id = entry.get("view_id")
        page_index = entry.get("page_index")
        item_codes = entry.get("item_codes")
        key = (view_id, page_index)
        expected_path = (
            f"public/{split}/contact-sheets/"
            f"{expected_view_id}-page-{expected_page_index:03d}.png"
        )
        if (
            view_id != expected_view_id
            or type(page_index) is not int
            or page_index != expected_page_index
            or entry.get("scale_percent") != int(expected_view["scale_percent"])
            or entry.get("source_crop_xywh")
            != [int(value) for value in expected_view["source_crop_xywh"]]
            or entry.get("path") != expected_path
            or key in by_view_page
            or not isinstance(item_codes, list)
        ):
            raise RuntimeError(f"{split} development contact-sheet layout drift")
        _require_sha256(
            entry.get("sha256"),
            f"{split} development contact sheet[{entry_index}].sha256",
        )
        remaining = EXPECTED_RECORDS_PER_SPLIT - (
            (page_index - 1) * REVIEW_ROWS_PER_PAGE
        )
        expected_count = min(REVIEW_ROWS_PER_PAGE, remaining)
        expected_item_codes = expected_codes[
            (page_index - 1) * REVIEW_ROWS_PER_PAGE : page_index
            * REVIEW_ROWS_PER_PAGE
        ]
        if len(item_codes) != expected_count or item_codes != expected_item_codes:
            raise RuntimeError(
                f"{split}/{view_id} contact-sheet code-order drift: {page_index}"
            )
        by_view_page[key] = item_codes
    expected_keys = {
        (view_id, page_index)
        for view_id in expected_views
        for page_index in range(1, EXPECTED_REVIEW_PAGES_PER_SPLIT + 1)
    }
    if set(by_view_page) != expected_keys:
        raise RuntimeError(f"{split} development contact-sheet coverage drift")
    for page_index in range(1, EXPECTED_REVIEW_PAGES_PER_SPLIT + 1):
        code_orders = {
            tuple(by_view_page[(view_id, page_index)]) for view_id in expected_views
        }
        if len(code_orders) != 1:
            raise RuntimeError(
                f"{split} development contact-sheet cross-view order drift: "
                f"{page_index}"
            )


def _validate_blank_labels(
    value: dict[str, Any],
    split: str,
    manifest: dict[str, Any],
    manifest_sha: str,
    state: dict[str, Any],
    expected_codes: list[str],
) -> None:
    context = f"{split} development blank labels"
    common.require_exact_keys(value, common.VISION_LABEL_KEYS, context)
    common._forbid_public_identity(value, context)
    if (
        value.get("artifact") != "microtexture-v2-r6-root-vision-labels"
        or value.get("schema_version")
        != "microtexture-v2-r6-root-vision-labels/2"
        or value.get("split") != split
        or value.get("spec_sha256") != state["spec_sha256"]
        or value.get("manifest_sha256") != manifest_sha
        or value.get("implementation_bindings_sha256")
        != state["implementation_bindings_sha256"]
        or value.get("blind_key_commitment") != state["blind_key_commitment"]
        or value.get("runtime") != state["runtime"]
        or value.get("runtime") != manifest["runtime"]
        or value.get("contact_sheet_bundle") != manifest["contact_sheet_bundle"]
        or value.get("reviewer") != "Root"
    ):
        raise RuntimeError(f"{context} metadata/binding drift")
    items = value.get("items")
    if not isinstance(items, list) or len(items) != EXPECTED_RECORDS_PER_SPLIT:
        raise RuntimeError(f"{context} item-count drift")
    null_fields = (
        "disposition",
        "grain_visible",
        "tiny_speck_visible",
        "microblob_visible",
        "short_line_visible",
        "parallel_bundle_visible",
        "severity_0_to_3",
        "reviewed_at_200_percent",
        "reviewed_at_all_400_percent_quadrants",
    )
    for index, (item, expected_code) in enumerate(zip(items, expected_codes)):
        common.require_exact_keys(
            item,
            common.VISION_LABEL_ITEM_KEYS,
            f"{context}[{index}]",
        )
        if (
            item.get("anonymous_code") != expected_code
            or any(item.get(field) is not None for field in null_fields)
            or item.get("notes") != ""
        ):
            raise RuntimeError(f"{context} code/order/null-state drift: {index}")


def _prepare_public_split(
    spec: dict[str, Any],
    state: dict[str, Any],
    split: str,
    generation_receipt: dict[str, Any],
    *,
    require_completed_decisions: bool = True,
) -> dict[str, Any]:
    public_root = DEV_ROOT / "public" / split
    manifest_path = public_root / "manifest.dev.json"
    blank_labels_path = public_root / "labels.blank.dev.json"
    review_index_path = public_root / "review-index.dev.json"
    decisions_path = public_root / "vision-decisions.dev.txt"
    root_decisions_path = public_root / "decisions-root.dev.txt"
    independent_decisions_path = public_root / "decisions-independent.dev.txt"
    generation_payloads = _verify_public_generation_receipt(split, generation_receipt)
    manifest_payload = generation_payloads["manifest_path"]
    blank_labels_payload = generation_payloads["blank_labels_path"]
    review_index_payload = generation_payloads["review_index_path"]
    manifest = _read_json_payload(manifest_payload, str(manifest_path))
    blank_labels = _read_json_payload(blank_labels_payload, str(blank_labels_path))
    review_index = _read_json_payload(review_index_payload, str(review_index_path))
    manifest_sha = _sha256(manifest_payload)
    common.require_exact_keys(
        manifest, _DEVELOPMENT_MANIFEST_KEYS, f"{split} development manifest"
    )
    records = manifest.get("records")
    if (
        manifest.get("artifact") != "microtexture-v2-r6-development-control-manifest"
        or manifest.get("schema_version")
        != "microtexture-v2-r6-development-control-manifest/1"
        or manifest.get("authority") is not False
        or manifest.get("formal_use_forbidden") is not True
        or manifest.get("split") != split
        or manifest.get("spec_sha256") != state["spec_sha256"]
        or manifest.get("implementation_bindings_sha256")
        != state["implementation_bindings_sha256"]
        or manifest.get("blind_key_commitment") != state["blind_key_commitment"]
        or manifest.get("captured_git_head") != state["captured_git_head"]
        or manifest.get("runtime") != state["runtime"]
        or manifest.get("warning")
        != "DEVELOPMENT ONLY; not a formal r6 manifest or authority artifact."
        or not isinstance(records, list)
        or len(records) != EXPECTED_RECORDS_PER_SPLIT
        or type(manifest.get("record_count")) is not int
        or manifest.get("record_count") != EXPECTED_RECORDS_PER_SPLIT
        or not isinstance(manifest.get("contact_sheet_bundle"), list)
        or len(manifest["contact_sheet_bundle"]) != EXPECTED_CONTACT_SHEETS_PER_SPLIT
    ):
        raise RuntimeError(f"{split} development manifest drift")
    codes: list[str] = []
    for index, record in enumerate(records):
        common.require_exact_keys(
            record,
            _DEVELOPMENT_MANIFEST_RECORD_KEYS,
            f"{split} development manifest record[{index}]",
        )
        code = record.get("anonymous_code")
        if (
            not isinstance(code, str)
            or len(code) != 24
            or any(character not in "0123456789abcdef" for character in code)
        ):
            raise RuntimeError(f"{split} development manifest code format drift")
        for field in (
            "control_commitment",
            "reference_commitment",
            "delta_commitment",
        ):
            _require_sha256(
                record.get(field),
                f"{split} development manifest record[{index}].{field}",
            )
        codes.append(code)
    if (
        len(codes) != EXPECTED_RECORDS_PER_SPLIT
        or len(set(codes)) != EXPECTED_RECORDS_PER_SPLIT
        or codes != sorted(codes)
    ):
        raise RuntimeError(f"{split} development manifest code drift")
    _validate_blank_labels(
        blank_labels,
        split,
        manifest,
        manifest_sha,
        state,
        codes,
    )
    contact_sheet_payloads = _verify_bundle_files(
        manifest["contact_sheet_bundle"], f"{split} contact sheet"
    )
    _verify_contact_sheet_layout(manifest["contact_sheet_bundle"], spec, split, codes)

    common.require_exact_keys(
        review_index, _REVIEW_INDEX_KEYS, f"{split} development review-index"
    )
    pages = review_index.get("pages")
    expected_review_views = [
        str(view["id"]) for view in spec["contact_sheets"]["views"]
    ]
    if (
        review_index.get("artifact") != "microtexture-v2-r6-development-review-index"
        or review_index.get("schema_version")
        != "microtexture-v2-r6-development-review-index/1"
        or review_index.get("authority") is not False
        or review_index.get("formal_use_forbidden") is not True
        or review_index.get("split") != split
        or review_index.get("spec_sha256") != state["spec_sha256"]
        or review_index.get("views") != expected_review_views
        or review_index.get("layout")
        != "one anonymous code per row with a black header above its panels; full-200 plus all four 400-percent quadrants"
        or not isinstance(pages, list)
        or len(pages) != EXPECTED_REVIEW_PAGES_PER_SPLIT
    ):
        raise RuntimeError(f"{split} development review-index drift")
    page_rows: dict[tuple[int, int], str] = {}
    indexed_codes: list[str] = []
    review_board_payloads: dict[str, bytes] = {}
    for expected_page, page in enumerate(pages, start=1):
        common.require_exact_keys(
            page,
            _REVIEW_INDEX_PAGE_KEYS,
            f"{split} review page[{expected_page}]",
        )
        if (
            type(page.get("page_index")) is not int
            or page.get("page_index") != expected_page
        ):
            raise RuntimeError(f"{split} review page ordering drift")
        item_codes = page.get("item_codes")
        remaining = EXPECTED_RECORDS_PER_SPLIT - (
            (expected_page - 1) * REVIEW_ROWS_PER_PAGE
        )
        expected_count = min(REVIEW_ROWS_PER_PAGE, remaining)
        expected_page_codes = codes[
            (expected_page - 1) * REVIEW_ROWS_PER_PAGE : expected_page
            * REVIEW_ROWS_PER_PAGE
        ]
        if (
            not isinstance(item_codes, list)
            or len(item_codes) != expected_count
            or item_codes != expected_page_codes
        ):
            raise RuntimeError(f"{split} review page row-count drift: {expected_page}")
        relative = page.get("path")
        expected_relative = (
            f"public/{split}/review-boards/review-page-{expected_page:03d}.png"
        )
        if relative != expected_relative:
            raise RuntimeError(f"{split} review page path drift: {expected_page}")
        path = _checked_dev_file(relative, f"{split} review page {expected_page}")
        _require_sha256(page.get("sha256"), f"{split} review page SHA")
        payload = path.read_bytes()
        if _sha256(payload) != page.get("sha256"):
            raise RuntimeError(f"{split} review page SHA drift: {expected_page}")
        review_board_payloads[relative] = payload
        for row, code in enumerate(item_codes, start=1):
            page_rows[(expected_page, row)] = code
            indexed_codes.append(code)
    if (
        len(indexed_codes) != EXPECTED_RECORDS_PER_SPLIT
        or len(set(indexed_codes)) != EXPECTED_RECORDS_PER_SPLIT
        or set(indexed_codes) != set(codes)
    ):
        raise RuntimeError(f"{split} review-index code coverage drift")

    if not require_completed_decisions:
        return {
            "split": split,
            "manifest": manifest,
            "manifest_sha256": manifest_sha,
            "blank_labels": blank_labels,
            "blank_labels_sha256": _sha256(blank_labels_payload),
            "review_index": review_index,
            "review_index_sha256": _sha256(review_index_payload),
            "contact_sheet_payloads": contact_sheet_payloads,
            "review_board_payloads": review_board_payloads,
        }

    _validate_r17_initial_decision_gate_manifest()
    decision_relatives = {
        "canonical": f"public/{split}/vision-decisions.dev.txt",
        "root": f"public/{split}/decisions-root.dev.txt",
        "independent": f"public/{split}/decisions-independent.dev.txt",
    }
    decision_payloads = {
        reviewer: _checked_dev_file(
            relative, f"{split} {reviewer} Vision decisions"
        ).read_bytes()
        for reviewer, relative in decision_relatives.items()
    }
    if not (
        decision_payloads["canonical"]
        == decision_payloads["root"]
        == decision_payloads["independent"]
    ):
        raise RuntimeError(
            f"{split} final Vision decisions are not exact three-way bytes"
        )
    initial_snapshots = {
        reviewer: _read_verified_initial_decision_snapshot(split, reviewer)
        for reviewer in ("root", "independent")
    }
    decisions = _parse_decisions_payload(
        decision_payloads["canonical"], str(decisions_path)
    )
    root_decisions = _parse_decisions_payload(
        decision_payloads["root"], str(root_decisions_path)
    )
    independent_decisions = _parse_decisions_payload(
        decision_payloads["independent"], str(independent_decisions_path)
    )
    root_initial_decisions = initial_snapshots["root"][1]
    independent_initial_decisions = initial_snapshots["independent"][1]
    for reviewer, reviewed in (
        ("canonical Root", decisions),
        ("Root", root_decisions),
        ("independent", independent_decisions),
        ("initial Root", root_initial_decisions),
        ("initial independent", independent_initial_decisions),
    ):
        if set(reviewed) != set(page_rows):
            raise RuntimeError(f"{split} {reviewer} Vision decision coverage drift")
        if any(
            decision["anonymous_code"] != page_rows[key]
            for key, decision in reviewed.items()
        ):
            raise RuntimeError(f"{split} {reviewer} Vision printed-code binding drift")
    if decisions != root_decisions:
        raise RuntimeError(f"{split} canonical decisions are not exact Root decisions")
    logical_difference_count = sum(
        root_decisions[key] != independent_decisions[key]
        for key in sorted(root_decisions)
    )
    if logical_difference_count != 0:
        raise RuntimeError(
            f"{split} Root/independent Vision decisions are not reconciled"
        )
    visible_fields = tuple(_FLAG_FIELDS.values())
    for key in sorted(decisions):
        unsupported_final_flags = {
            field
            for field in visible_fields
            if decisions[key][field]
            and not (
                root_initial_decisions[key][field]
                and independent_initial_decisions[key][field]
            )
        }
        if unsupported_final_flags:
            raise RuntimeError(
                f"{split} final visible flags lack bilateral initial support"
            )
    by_code = {decision["anonymous_code"]: decision for decision in decisions.values()}
    completed = deepcopy(blank_labels)
    items = completed.get("items")
    if (
        completed.get("manifest_sha256") != manifest_sha
        or completed.get("spec_sha256") != state["spec_sha256"]
        or not isinstance(items, list)
        or len(items) != EXPECTED_RECORDS_PER_SPLIT
    ):
        raise RuntimeError(f"{split} blank label binding drift")
    for item in items:
        code = item.get("anonymous_code") if isinstance(item, dict) else None
        if code not in by_code:
            raise RuntimeError(f"{split} blank label code drift")
        item.update(by_code[code])
    labels = common.validate_vision_labels_payload(
        completed, split, manifest, manifest_sha, state
    )
    return {
        "split": split,
        "manifest": manifest,
        "manifest_sha256": manifest_sha,
        "blank_labels_sha256": _sha256(blank_labels_payload),
        "review_index": review_index,
        "contact_sheet_payloads": contact_sheet_payloads,
        "review_board_payloads": review_board_payloads,
        "completed_labels": completed,
        "labels": labels,
        "completed_labels_sha256": _sha256(_json_bytes(completed)),
        "review_index_sha256": _sha256(review_index_payload),
        "decisions_sha256": _sha256(decision_payloads["canonical"]),
        "root_decisions_sha256": _sha256(decision_payloads["root"]),
        "independent_decisions_sha256": _sha256(decision_payloads["independent"]),
        "root_initial_decisions_sha256": initial_snapshots["root"][2],
        "root_initial_decisions_receipt_sha256": initial_snapshots["root"][3],
        "independent_initial_decisions_sha256": initial_snapshots["independent"][2],
        "independent_initial_decisions_receipt_sha256": initial_snapshots[
            "independent"
        ][3],
        "initial_decision_gate_manifest_sha256": (
            _R17_INITIAL_DECISION_GATE_MANIFEST_SHA256
        ),
        "root_independent_logical_difference_count": logical_difference_count,
        "dispositions": dict(Counter(item["disposition"] for item in labels.values())),
    }


def _generation_preflight() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, str],
    dict[str, dict[str, Any]],
]:
    _assert_development_boundary(root_must_not_exist=False)
    spec, spec_sha = _load_spec()
    state, generation_receipts, generation_binding = _load_generation_state(
        spec, spec_sha
    )
    captured_head, bindings_sha = _tracked_input_preflight(spec, spec_sha)
    if (
        state.get("captured_git_head") != captured_head
        or state.get("implementation_bindings_sha256") != bindings_sha
        or state.get("runtime") != common.runtime_fingerprint()
    ):
        raise RuntimeError(
            "development captured authority or runtime changed after generation"
        )
    return spec, state, generation_binding, generation_receipts


def _public_preflight() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, str], dict[str, Any]
]:
    spec, state, generation_binding, generation_receipts = _generation_preflight()
    prepared = {
        split: _prepare_public_split(
            spec, state, split, generation_receipts[split]
        )
        for split in ("calibration", "holdout")
    }
    return spec, state, generation_binding, prepared


def _review_preflight() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, str], dict[str, Any]
]:
    spec, state, generation_binding, generation_receipts = _generation_preflight()
    prepared = {
        split: _prepare_public_split(
            spec,
            state,
            split,
            generation_receipts[split],
            require_completed_decisions=False,
        )
        for split in ("calibration", "holdout")
    }
    return spec, state, generation_binding, prepared


def preflight() -> None:
    _spec, _state, _generation_binding, prepared = _public_preflight()
    _assert_development_boundary(root_must_not_exist=False)
    print(
        json.dumps(
            {
                "authority": False,
                "formal_use_forbidden": True,
                "formal_root_absent": True,
                "key_read": False,
                "labels_written": False,
                "splits": {
                    split: {
                        "record_count": len(result["labels"]),
                        "completed_labels_sha256": result["completed_labels_sha256"],
                        "dispositions": result["dispositions"],
                    }
                    for split, result in prepared.items()
                },
            },
            ensure_ascii=False,
        )
    )


def _regenerate_controls(
    spec: dict[str, Any], key: bytes, split: str, manifest: dict[str, Any]
) -> list[Any]:
    controls = sorted(
        expected_controls(spec, split, key), key=lambda item: item.anonymous_code
    )
    _validate_expected_control_population(controls, split)
    by_code = {control.anonymous_code: control for control in controls}
    if (
        len(controls) != EXPECTED_RECORDS_PER_SPLIT
        or len(by_code) != EXPECTED_RECORDS_PER_SPLIT
    ):
        raise RuntimeError(f"{split} regenerated control coverage drift")
    manifest_codes: set[str] = set()
    for record in manifest["records"]:
        code = record["anonymous_code"]
        control = by_code.get(code)
        if (
            control is None
            or record.get("control_commitment") != control.control_commitment
            or record.get("reference_commitment") != control.reference_commitment
            or record.get("delta_commitment") != control.delta_commitment
        ):
            raise RuntimeError(f"{split} regenerated public commitment drift")
        manifest_codes.add(code)
    if manifest_codes != set(by_code):
        raise RuntimeError(f"{split} regenerated manifest code drift")
    return controls


def _verify_regenerated_review_surfaces(
    spec: dict[str, Any],
    split: str,
    controls: list[Any],
    manifest: dict[str, Any],
    review_index: dict[str, Any],
    contact_sheet_payloads: dict[str, bytes],
    review_board_payloads: dict[str, bytes],
) -> None:
    regenerated_sheets = contact_sheet_pages(spec, split, controls)
    recorded_sheets = manifest.get("contact_sheet_bundle")
    if (
        not isinstance(recorded_sheets, list)
        or len(recorded_sheets) != EXPECTED_CONTACT_SHEETS_PER_SPLIT
        or len(regenerated_sheets) != EXPECTED_CONTACT_SHEETS_PER_SPLIT
    ):
        raise RuntimeError(f"{split} regenerated contact-sheet coverage drift")
    expected_sheet_paths: set[str] = set()
    for index, (regenerated, recorded) in enumerate(
        zip(regenerated_sheets, recorded_sheets, strict=True)
    ):
        expected_entry = regenerated.manifest_entry()
        expected_entry["path"] = (
            f"public/{split}/contact-sheets/{Path(regenerated.path).name}"
        )
        if recorded != expected_entry:
            raise RuntimeError(
                f"{split} regenerated contact-sheet manifest drift: {index}"
            )
        expected_sheet_paths.add(expected_entry["path"])
        if contact_sheet_payloads.get(expected_entry["path"]) != regenerated.png_bytes:
            raise RuntimeError(
                f"{split} regenerated contact-sheet byte drift: {index}"
            )
    if set(contact_sheet_payloads) != expected_sheet_paths:
        raise RuntimeError(f"{split} regenerated contact-sheet capture drift")

    recorded_boards = review_index.get("pages")
    if (
        not isinstance(recorded_boards, list)
        or len(recorded_boards) != EXPECTED_REVIEW_PAGES_PER_SPLIT
    ):
        raise RuntimeError(f"{split} regenerated review-board coverage drift")
    expected_board_paths: set[str] = set()
    for page_index, recorded in enumerate(recorded_boards, start=1):
        codes, payload = _review_board_payload(
            controls, spec["contact_sheets"]["views"], page_index
        )
        expected_path = f"public/{split}/review-boards/review-page-{page_index:03d}.png"
        if (
            type(recorded.get("page_index")) is not int
            or recorded.get("page_index") != page_index
            or recorded.get("path") != expected_path
            or recorded.get("sha256") != _sha256(payload)
            or recorded.get("item_codes") != codes
        ):
            raise RuntimeError(
                f"{split} regenerated review-board index drift: {page_index}"
            )
        expected_board_paths.add(expected_path)
        if review_board_payloads.get(expected_path) != payload:
            raise RuntimeError(
                f"{split} regenerated review-board byte drift: {page_index}"
            )
    if set(review_board_payloads) != expected_board_paths:
        raise RuntimeError(f"{split} regenerated review-board capture drift")


def _eligible_clusters(controls: list[Any], spec: dict[str, Any]) -> dict[str, str]:
    eligible_role = spec["threshold_selection"]["endpoint_eligible_private_role"]
    clusters = {
        control.anonymous_code: control.condition_cluster_id
        for control in controls
        if control.private_role == eligible_role
    }
    if not clusters:
        raise RuntimeError("development eligible cluster set is empty")
    return clusters


def _exact_metric_window(values: np.ndarray, spec: dict[str, Any]) -> np.ndarray:
    expected_canvas = (int(spec["canvas"]["height"]), int(spec["canvas"]["width"]))
    if values.shape != expected_canvas:
        raise RuntimeError(f"development control canvas drift: {values.shape}")
    x, y, width, height = [
        int(value) for value in spec["canvas"]["metric_window"]["xywh"]
    ]
    crop = values[y : y + height, x : x + width]
    expected = tuple(
        int(value) for value in spec["metric_definition"]["expected_shape_hw"]
    )
    if crop.shape != expected:
        raise RuntimeError("development exact metric-window crop drift")
    return crop


def _measure_split(
    controls: list[Any], clusters: dict[str, str], spec: dict[str, Any], split: str
) -> dict[str, dict[str, Any]]:
    measured: dict[str, dict[str, Any]] = {}
    controls_by_code = {control.anonymous_code: control for control in controls}
    for index, control in enumerate(controls, start=1):
        metrics = measure(
            _exact_metric_window(control.control, spec),
            _exact_metric_window(control.reference, spec),
            spec["metric_definition"],
        )
        common.validate_metric_values(metrics, spec, f"{split} development metric")
        if control.private_role == "protocol-zero" and any(
            value != 0 for name, value in metrics.items() if name != "eligible_pixels"
        ):
            raise RuntimeError(f"{split} protocol-zero metric drift")
        measured[control.anonymous_code] = {
            "anonymous_code": control.anonymous_code,
            "metrics": metrics,
        }
        if index % 20 == 0 or index == len(controls):
            print(f"{split}: measured {index}/{len(controls)}", flush=True)
    members: dict[str, list[str]] = {}
    for code, cluster_id in clusters.items():
        members.setdefault(cluster_id, []).append(code)
    for cluster_id, codes in members.items():
        if (
            len(codes) != 2
            or measured[codes[0]]["metrics"] != measured[codes[1]]["metrics"]
        ):
            raise RuntimeError(
                f"{split} full metric-equivalent polarity-pair drift: {cluster_id}"
            )
    if set(measured) != set(controls_by_code):
        raise RuntimeError(f"{split} measurement coverage drift")
    return measured


def _population_audit(
    labels: dict[str, dict[str, Any]],
    clusters: dict[str, str],
    spec: dict[str, Any],
    split: str,
) -> dict[str, Any]:
    counts = Counter(clusters.values())
    exact_pairs = bool(counts) and all(count == 2 for count in counts.values())
    endpoint_audit = common.endpoint_population_count_audit(labels, clusters, spec)
    frozen_floors = spec.get("population_anchor_schedule", {}).get(
        "development_premeasurement_safety_floors"
    )
    if frozen_floors != DEVELOPMENT_POPULATION_FLOORS:
        raise RuntimeError(f"{split} development safety-floor authority drift")
    if set(endpoint_audit["endpoints"]) != set(DEVELOPMENT_POPULATION_FLOORS):
        raise RuntimeError(f"{split} development endpoint set drift")
    development_endpoints = {
        endpoint_id: {
            "unique_cluster_count": endpoint_audit["endpoints"][endpoint_id][
                "unique_cluster_count"
            ],
            "development_minimum_unique_clusters": minimum,
            "count_passed": endpoint_audit["endpoints"][endpoint_id][
                "unique_cluster_count"
            ]
            >= minimum,
        }
        for endpoint_id, minimum in DEVELOPMENT_POPULATION_FLOORS.items()
    }
    development_audit = {
        "passed": all(item["count_passed"] for item in development_endpoints.values()),
        "endpoints": development_endpoints,
    }
    return {
        "split": split,
        "condition_cluster_count": len(counts),
        "all_condition_clusters_exact_polarity_pairs": exact_pairs,
        **endpoint_audit,
        "formal_endpoint_minimums_passed": endpoint_audit["passed"],
        "development_safety_floor_audit": development_audit,
        "passed": exact_pairs
        and endpoint_audit["passed"]
        and development_audit["passed"],
    }


def _regenerate_and_audit_population(
    spec: dict[str, Any],
    key: bytes,
    prepared: dict[str, dict[str, Any]],
) -> tuple[
    dict[str, list[Any]],
    dict[str, dict[str, str]],
    dict[str, Any],
]:
    controls: dict[str, list[Any]] = {}
    for split, result in prepared.items():
        split_controls = _regenerate_controls(spec, key, split, result["manifest"])
        controls[split] = split_controls
        _verify_regenerated_review_surfaces(
            spec,
            split,
            split_controls,
            result["manifest"],
            result["review_index"],
            result["contact_sheet_payloads"],
            result["review_board_payloads"],
        )

    clusters: dict[str, dict[str, str]] = {}
    for split, result in prepared.items():
        split_controls = controls[split]
        common.validate_private_vision_label_audits(
            result["labels"],
            [
                {
                    "anonymous_code": control.anonymous_code,
                    "private_role": control.private_role,
                    "duplicate_audit_group": control.duplicate_audit_group,
                }
                for control in split_controls
            ],
            f"{split} development sealed labels",
        )
        clusters[split] = _eligible_clusters(split_controls, spec)

    population: dict[str, Any] = {}
    for split, result in prepared.items():
        population[split] = _population_audit(
            result["labels"], clusters[split], spec, split
        )
    return controls, clusters, population


def analyze() -> None:
    spec, state, generation_binding, prepared = _public_preflight()
    _assert_private_analysis_boundary(analysis_must_exist=False)
    if PRIVATE_ANALYSIS_ROOT.exists() or PRIVATE_ANALYSIS_ROOT.is_symlink():
        raise RuntimeError(
            "development analysis was already started; do not rerun or revise labels"
        )
    PRIVATE_ANALYSIS_ROOT.mkdir(parents=True, exist_ok=False)
    _assert_private_analysis_boundary(analysis_must_exist=True)
    measurement_started = False
    try:
        sealed: dict[str, Any] = {}
        for split, result in prepared.items():
            relative = Path("sealed-labels") / f"{split}.completed.dev.json"
            digest = _write_json_exclusive(
                PRIVATE_ANALYSIS_ROOT / relative, result["completed_labels"]
            )
            if digest != result["completed_labels_sha256"]:
                raise RuntimeError(f"{split} completed-label seal SHA drift")
            sealed[split] = {
                "path": relative.as_posix(),
                "sha256": digest,
                "manifest_sha256": result["manifest_sha256"],
                "blank_labels_sha256": result["blank_labels_sha256"],
                "review_index_sha256": result["review_index_sha256"],
                "decisions_sha256": result["decisions_sha256"],
                "root_decisions_sha256": result["root_decisions_sha256"],
                "independent_decisions_sha256": result["independent_decisions_sha256"],
                "root_initial_decisions_sha256": result[
                    "root_initial_decisions_sha256"
                ],
                "root_initial_decisions_receipt_sha256": result[
                    "root_initial_decisions_receipt_sha256"
                ],
                "independent_initial_decisions_sha256": result[
                    "independent_initial_decisions_sha256"
                ],
                "independent_initial_decisions_receipt_sha256": result[
                    "independent_initial_decisions_receipt_sha256"
                ],
                "initial_decision_gate_manifest_sha256": result[
                    "initial_decision_gate_manifest_sha256"
                ],
                "root_independent_logical_difference_count": result[
                    "root_independent_logical_difference_count"
                ],
                "record_count": len(result["labels"]),
                "dispositions": result["dispositions"],
            }
        seal_receipt = {
            "artifact": "microtexture-v2-r6-development-label-seal",
            "schema_version": "microtexture-v2-r6-development-label-seal/3",
            "authority": False,
            "formal_use_forbidden": True,
            "root_vision_blind_during_all_decisions": True,
            "private_key_read_after_both_label_files_sealed": True,
            "spec_sha256": state["spec_sha256"],
            "implementation_bindings_sha256": state["implementation_bindings_sha256"],
            "blind_key_commitment": state["blind_key_commitment"],
            **generation_binding,
            "splits": sealed,
        }
        seal_sha = _write_json_exclusive(
            PRIVATE_ANALYSIS_ROOT / "label-seal-receipt.dev.json", seal_receipt
        )

        key = (DEV_ROOT / "private" / "development-key.bin").read_bytes()
        if (
            len(key) != 32
            or _development_blind_commitment(key) != state["blind_key_commitment"]
        ):
            raise RuntimeError("development blind-key commitment drift")

        controls, clusters, population = _regenerate_and_audit_population(
            spec, key, prepared
        )
        population_artifact = {
            "artifact": "microtexture-v2-r6-development-premeasurement-population-audit",
            "schema_version": "microtexture-v2-r6-development-premeasurement-population-audit/1",
            "authority": False,
            "formal_use_forbidden": True,
            "measurement_started": False,
            "label_seal_receipt_sha256": seal_sha,
            "splits": population,
            "passed": all(item["passed"] for item in population.values()),
        }
        _write_json_exclusive(
            PRIVATE_ANALYSIS_ROOT / "population-audit.dev.json", population_artifact
        )
        if not population_artifact["passed"]:
            raise RuntimeError(
                "development endpoint population premeasurement audit failed"
            )
        for split, result in prepared.items():
            common.validate_endpoint_population_counts(
                result["labels"], clusters[split], spec
            )

        measurement_started = True
        measured = {
            split: _measure_split(controls[split], clusters[split], spec, split)
            for split in ("calibration", "holdout")
        }
        for split, values in measured.items():
            _write_json_exclusive(
                PRIVATE_ANALYSIS_ROOT / f"{split}-measurements.dev.json",
                {
                    "artifact": "microtexture-v2-r6-development-measurements",
                    "schema_version": "microtexture-v2-r6-development-measurements/1",
                    "authority": False,
                    "formal_use_forbidden": True,
                    "split": split,
                    "label_seal_receipt_sha256": seal_sha,
                    "measurements": [values[code] for code in sorted(values)],
                },
            )

        hard_threshold, calibration_endpoints, _calibration_results, status, audit = (
            common.select_hard_threshold_from_measurements(
                measured["calibration"],
                prepared["calibration"]["labels"],
                clusters["calibration"],
                spec,
            )
        )
        holdout_endpoints: dict[str, Any] | None = None
        if hard_threshold is not None:
            holdout_endpoints, _holdout_results = (
                common.evaluate_endpoints_from_measurements(
                    float(hard_threshold["threshold"]),
                    measured["holdout"],
                    prepared["holdout"]["labels"],
                    clusters["holdout"],
                    "holdout",
                    spec,
                )
            )
        passed = hard_threshold is not None and holdout_endpoints is not None
        passed = bool(
            passed
            and all(item["passed"] for item in calibration_endpoints.values())
            and all(item["passed"] for item in holdout_endpoints.values())
        )
        result_artifact = {
            "artifact": "microtexture-v2-r6-development-probe-result",
            "schema_version": "microtexture-v2-r6-development-probe-result/1",
            "authority": False,
            "formal_use_forbidden": True,
            "development_threshold_not_formal_authority": True,
            "formal_cli_invoked": False,
            "formal_marker_created": False,
            "locked_clean_v18_decoded_or_measured": False,
            "label_seal_receipt_sha256": seal_sha,
            "result_status": status,
            "passed": passed,
            "development_hard_threshold": hard_threshold,
            "calibration_endpoint_performance": calibration_endpoints,
            "holdout_endpoint_performance": holdout_endpoints,
            "threshold_selection_audit": audit,
        }
        _write_json_exclusive(
            PRIVATE_ANALYSIS_ROOT / "analysis-result.dev.json", result_artifact
        )
        if not passed:
            raise RuntimeError(
                "development metric schedule did not pass calibration and holdout"
            )
        _assert_development_boundary(root_must_not_exist=False)
        print(
            json.dumps(
                {
                    "authority": False,
                    "formal_use_forbidden": True,
                    "formal_root_absent": True,
                    "passed": True,
                    "result_status": status,
                    "development_threshold_not_formal_authority": True,
                    "calibration_endpoint_performance": calibration_endpoints,
                    "holdout_endpoint_performance": holdout_endpoints,
                },
                ensure_ascii=False,
            )
        )
    except BaseException as error:
        _assert_private_analysis_boundary(analysis_must_exist=True)
        failure_path = PRIVATE_ANALYSIS_ROOT / "FAILED.dev.json"
        if not failure_path.exists() and not failure_path.is_symlink():
            _write_json_exclusive(
                failure_path,
                {
                    "artifact": "microtexture-v2-r6-development-analysis-failure",
                    "schema_version": "microtexture-v2-r6-development-analysis-failure/1",
                    "authority": False,
                    "formal_use_forbidden": True,
                    "development_edition": DEVELOPMENT_EDITION,
                    "development_closed": True,
                    "measurement_started": measurement_started,
                    "error_type": type(error).__name__,
                    "message": _sanitized_error_message(error),
                },
            )
        _assert_development_boundary(root_must_not_exist=False)
        raise


def postmortem() -> None:
    """Read-only reveal for a closed development probe; never emits key material."""
    failure = PRIVATE_ANALYSIS_ROOT / "FAILED.dev.json"
    if not failure.is_file():
        raise RuntimeError("development postmortem requires a closed failed probe")
    spec, state, _generation_binding, prepared = _public_preflight()
    key = (DEV_ROOT / "private" / "development-key.bin").read_bytes()
    if len(key) != 32 or _development_blind_commitment(key) != state[
        "blind_key_commitment"
    ]:
        raise RuntimeError("development blind-key commitment drift")
    findings: dict[str, Any] = {}
    for split, result in prepared.items():
        controls = _regenerate_controls(spec, key, split, result["manifest"])
        page_by_code: dict[str, dict[str, int]] = {}
        index = _read_json(DEV_ROOT / "public" / split / "review-index.dev.json")
        for page in index["pages"]:
            for row, code in enumerate(page["item_codes"], start=1):
                page_by_code[code] = {"page": page["page_index"], "row": row}
        revealed = []
        speck_artifacts = []
        role_counts: Counter[str] = Counter()
        role_dispositions: dict[str, Counter[str]] = {}
        for control in controls:
            role_counts[control.private_role] += 1
            label = result["labels"][control.anonymous_code]
            role_dispositions.setdefault(control.private_role, Counter())[
                label["disposition"]
            ] += 1
            if control.private_role != "artifact":
                revealed.append(
                    {
                        **page_by_code[control.anonymous_code],
                        "private_role": control.private_role,
                        "duplicate_audit_group": control.duplicate_audit_group,
                        "disposition": label["disposition"],
                        "severity": label["severity_0_to_3"],
                        "visible_flags": [
                            flag for flag, field in _FLAG_FIELDS.items() if label[field]
                        ],
                        "notes": label["notes"],
                    }
                )
            elif control.family == "artifact-speck":
                speck_artifacts.append(
                    {
                        **page_by_code[control.anonymous_code],
                        "family": control.family,
                        "polarity": control.polarity,
                        "variant_index": control.variant_index,
                        "disposition": label["disposition"],
                        "severity": label["severity_0_to_3"],
                        "visible_flags": [
                            flag for flag, field in _FLAG_FIELDS.items() if label[field]
                        ],
                        "notes": label["notes"],
                    }
                )
        findings[split] = {
            "role_counts": dict(role_counts),
            "role_dispositions": {
                role: dict(counts) for role, counts in role_dispositions.items()
            },
            "non_artifact_rows": sorted(
                revealed, key=lambda item: (item["page"], item["row"])
            ),
            "artifact_speck_rows": sorted(
                speck_artifacts, key=lambda item: (item["page"], item["row"])
            ),
        }
    _assert_development_boundary(root_must_not_exist=False)
    print(
        json.dumps(
            {
                "authority": False,
                "formal_use_forbidden": True,
                "closed_development_probe_only": True,
                "findings": findings,
            },
            ensure_ascii=False,
        )
    )


def generate() -> None:
    _assert_development_boundary(root_must_not_exist=True)
    spec, spec_sha = _load_spec()
    captured_head, bindings_sha = _tracked_input_preflight(spec, spec_sha)
    key_path = _validate_development_key_git_boundary(spec, captured_head)
    DEV_ROOT.mkdir(parents=True, exist_ok=False)
    (DEV_ROOT / "private").mkdir()
    # The root is the earliest durable consumed-edition evidence. Sample the key
    # only after it exists so an interruption can never silently resample r20.
    key = secrets.token_bytes(32)
    state = {
        "development_edition": DEVELOPMENT_EDITION,
        "development_authority_sha256": _R20_PROBE_AUTHORITY_MANIFEST_SHA256,
        "spec_sha256": spec_sha,
        "public_nonces": _public_nonces(spec),
        "implementation_bindings_sha256": bindings_sha,
        "blind_key_commitment": _development_blind_commitment(key),
        "captured_git_head": captured_head,
        "runtime": common.runtime_fingerprint(),
    }
    with key_path.open("xb") as output:
        output.write(key)
        output.flush()
        os.fsync(output.fileno())
    boundary = {
        "artifact": "microtexture-v2-r6-development-only-boundary",
        "schema_version": "microtexture-v2-r6-development-only-boundary/1",
        "authority": False,
        "formal_use_forbidden": True,
        "formal_cli_invoked": False,
        "formal_marker_created": False,
        "formal_threshold_created": False,
        "locked_clean_v18_decoded_or_measured": False,
        "exact_formal_root_absent_before_generation": True,
        "formal_environment_absent_before_generation": True,
        **state,
    }
    boundary_sha = _write_json_exclusive(DEV_ROOT / "DEV-ONLY.json", boundary)
    generation_start_sha = _write_json_exclusive(
        DEV_ROOT / "generation-start.dev.json",
        {
            "artifact": "microtexture-v2-r6-development-generation-start",
            "schema_version": "microtexture-v2-r6-development-generation-start/1",
            "authority": False,
            "formal_use_forbidden": True,
            "one_shot_consumed": True,
            "started_at": common.utc_timestamp(),
            "development_boundary_sha256": boundary_sha,
            "state": state,
        },
    )
    try:
        results = [
            _generate_split(spec, split, key, state)
            for split in ("calibration", "holdout")
        ]
        calibration, holdout = results
        for field in ("codes", "control_ids", "cluster_ids", "nonzero_delta_hashes"):
            if set(calibration[field]) & set(holdout[field]):
                raise RuntimeError(f"development split separation failed: {field}")
        calibration_zero = set(calibration["zero_delta_hashes"])
        holdout_zero = set(holdout["zero_delta_hashes"])
        if len(calibration_zero) != 1 or calibration_zero != holdout_zero:
            raise RuntimeError("canonical all-zero requested-delta hash contract drift")
        public_results = [
            {
                key: value
                for key, value in result.items()
                if key
                not in {
                    "codes",
                    "control_ids",
                    "cluster_ids",
                    "nonzero_delta_hashes",
                    "zero_delta_hashes",
                }
            }
            for result in results
        ]
        generation_summary = {
            "artifact": "microtexture-v2-r6-development-generation-summary",
            "schema_version": "microtexture-v2-r6-development-generation-summary/1",
            "authority": False,
            "formal_use_forbidden": True,
            "state": state,
            "split_separation": {
                "codes_disjoint": True,
                "control_ids_disjoint": True,
                "cluster_ids_disjoint": True,
                "nonzero_delta_hashes_disjoint": True,
                "canonical_all_zero_delta_hash_shared": True,
            },
            "splits": public_results,
        }
        generation_summary_sha = _write_json_exclusive(
            DEV_ROOT / "generation-summary.dev.json", generation_summary
        )
        generation_seal_sha = _write_json_exclusive(
            DEV_ROOT / "generation-seal.dev.json",
            {
                "artifact": "microtexture-v2-r6-development-generation-seal",
                "schema_version": "microtexture-v2-r6-development-generation-seal/1",
                "authority": False,
                "formal_use_forbidden": True,
                "generation_start_sha256": generation_start_sha,
                "generation_summary_sha256": generation_summary_sha,
                "spec_sha256": state["spec_sha256"],
                "implementation_bindings_sha256": state[
                    "implementation_bindings_sha256"
                ],
                "blind_key_commitment": state["blind_key_commitment"],
                "captured_git_head": state["captured_git_head"],
            },
        )
        _assert_development_boundary(root_must_not_exist=False)
        generation_completion_sha = _write_json_exclusive(
            DEV_ROOT / "generation-completion.dev.json",
            {
                "artifact": "microtexture-v2-r6-development-generation-completion",
                "schema_version": (
                    "microtexture-v2-r6-development-generation-completion/1"
                ),
                "authority": False,
                "formal_use_forbidden": True,
                "completed_at": common.utc_timestamp(),
                "generation_start_sha256": generation_start_sha,
                "generation_summary_sha256": generation_summary_sha,
                "generation_seal_sha256": generation_seal_sha,
                "spec_sha256": state["spec_sha256"],
                "implementation_bindings_sha256": state[
                    "implementation_bindings_sha256"
                ],
                "blind_key_commitment": state["blind_key_commitment"],
                "captured_git_head": state["captured_git_head"],
            },
        )
        (
            verified_spec,
            verified_state,
            verified_generation_binding,
            verified_surfaces,
        ) = _review_preflight()
        expected_generation_binding = {
            "generation_start_sha256": generation_start_sha,
            "generation_summary_sha256": generation_summary_sha,
            "generation_seal_sha256": generation_seal_sha,
            "generation_completion_sha256": generation_completion_sha,
        }
        if (
            verified_spec != spec
            or verified_state != state
            or verified_generation_binding != expected_generation_binding
            or set(verified_surfaces) != {"calibration", "holdout"}
        ):
            raise RuntimeError("development generation post-completion reload drift")
    except BaseException as error:
        try:
            _write_json_exclusive(
                DEV_ROOT / "generation-failure.dev.json",
                {
                    "artifact": "microtexture-v2-r6-development-generation-failure",
                    "schema_version": (
                        "microtexture-v2-r6-development-generation-failure/1"
                    ),
                    "authority": False,
                    "formal_use_forbidden": True,
                    "failed_at": common.utc_timestamp(),
                    "generation_start_sha256": generation_start_sha,
                    "error_type": type(error).__name__,
                    "message": _sanitized_error_message(error),
                    "development_closed": True,
                },
            )
        except BaseException as reporting_error:
            try:
                error.add_note(
                    "generation failure reporting also failed: "
                    f"{type(reporting_error).__name__}: {reporting_error}"
                )
            except BaseException:
                pass
        raise
    print(
        json.dumps(
            {
                "development_root": str(DEV_ROOT),
                "authority": False,
                "formal_root_absent": True,
                "generation_start_sha256": generation_start_sha,
                "generation_summary_sha256": generation_summary_sha,
                "generation_seal_sha256": generation_seal_sha,
                "generation_completion_sha256": generation_completion_sha,
                "splits": public_results,
            },
            ensure_ascii=False,
        )
    )


def review_crops(split: str, page_index: int) -> None:
    if (
        split not in {"calibration", "holdout"}
        or not 1 <= page_index <= EXPECTED_REVIEW_PAGES_PER_SPLIT
    ):
        raise RuntimeError("review crop split/page drift")
    _spec, _state, _generation_binding, prepared = _review_preflight()
    relative = (
        f"public/{split}/review-boards/review-page-{page_index:03d}.png"
    )
    payload = prepared[split]["review_board_payloads"][relative]
    with Image.open(io.BytesIO(payload)) as board:
        if board.size != (2560, REVIEW_ROW_HEIGHT * REVIEW_ROWS_PER_PAGE):
            raise RuntimeError("review board dimensions drift")
        output_root = DEV_ROOT / "public" / split / "review-crops"
        output_root.mkdir(parents=True, exist_ok=True)
        evidence = board.convert("RGB")
        evidence_draw = ImageDraw.Draw(evidence)
        evidence_font = ImageFont.load_default(size=14)
        quadrant_ids = ("NW", "NE", "SW", "SE")
        for row_index in range(REVIEW_ROWS_PER_PAGE):
            image_top = row_index * REVIEW_ROW_HEIGHT + REVIEW_HEADER_HEIGHT
            for quadrant_column, quadrant_id in enumerate(quadrant_ids, start=1):
                panel_left = quadrant_column * 512
                for division in (1, 2):
                    x = panel_left + round(512 * division / 3)
                    y = image_top + 128 * division
                    evidence_draw.line(
                        (x, image_top, x, image_top + 383),
                        fill=(220, 32, 96),
                        width=2,
                    )
                    evidence_draw.line(
                        (panel_left, y, panel_left + 511, y),
                        fill=(220, 32, 96),
                        width=2,
                    )
                for sector_row in range(1, 4):
                    for sector_column in range(1, 4):
                        label = f"{quadrant_id}-R{sector_row}C{sector_column}"
                        label_x = panel_left + round(512 * (sector_column - 1) / 3) + 4
                        label_y = image_top + 128 * (sector_row - 1) + 4
                        evidence_draw.text(
                            (label_x + 1, label_y + 1),
                            label,
                            fill=(255, 255, 255),
                            font=evidence_font,
                        )
                        evidence_draw.text(
                            (label_x, label_y),
                            label,
                            fill=(190, 0, 70),
                            font=evidence_font,
                        )
        evidence.save(
            output_root / f"evidence-page-{page_index:03d}.png",
            format="PNG",
            compress_level=6,
            optimize=False,
        )
        for row in range(1, REVIEW_ROWS_PER_PAGE + 1):
            top = (row - 1) * REVIEW_ROW_HEIGHT
            output = output_root / f"review-page-{page_index:03d}-row-{row}.png"
            board.crop((0, top, 2560, top + REVIEW_ROW_HEIGHT)).save(
                output, format="PNG", compress_level=6, optimize=False
            )
            native_output = (
                output_root
                / f"review-page-{page_index:03d}-row-{row}-full-200-native.png"
            )
            board.crop(
                (
                    0,
                    top + REVIEW_HEADER_HEIGHT,
                    REVIEW_PANEL_WIDTH,
                    top + REVIEW_ROW_HEIGHT,
                )
            ).save(
                native_output, format="PNG", compress_level=6, optimize=False
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("generate", "preflight", "analyze", "postmortem", "review-crops"),
    )
    parser.add_argument("--split", choices=("calibration", "holdout"))
    parser.add_argument("--page", type=int)
    arguments = parser.parse_args()
    if arguments.command == "generate":
        generate()
    elif arguments.command == "preflight":
        preflight()
    elif arguments.command == "analyze":
        analyze()
    elif arguments.command == "review-crops":
        if arguments.split is None or arguments.page is None:
            parser.error("review-crops requires --split and --page")
        review_crops(arguments.split, arguments.page)
    else:
        postmortem()


if __name__ == "__main__":
    main()
