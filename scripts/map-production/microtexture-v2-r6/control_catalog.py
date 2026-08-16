"""Secret-keyed deterministic private control catalog for r6."""

from __future__ import annotations

import hashlib
import io
import json
import math
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from common import (
    blind_hmac,
    canonical_json_bytes,
    sha256_bytes,
    validate_contact_sheet_view_partition,
)


@dataclass(frozen=True)
class ExpectedControl:
    family: str
    private_role: str
    foundation_id: str
    duplicate_audit_group: str | None
    control_id: str
    condition_cluster_id: str
    variant_index: int
    replicate: int
    polarity: int
    parameters: dict[str, Any]
    anonymous_code: str
    reference: np.ndarray
    requested_delta: np.ndarray
    control: np.ndarray
    reference_png: bytes
    control_png: bytes
    reference_sha256: str
    control_sha256: str
    delta_float32_sha256: str
    control_commitment: str
    reference_commitment: str
    delta_commitment: str

    @property
    def public_binding_tuple(self) -> tuple[str, str, str, str]:
        return (
            self.anonymous_code,
            self.control_commitment,
            self.reference_commitment,
            self.delta_commitment,
        )


@dataclass(frozen=True)
class ContactSheetPage:
    view_id: str
    scale_percent: int
    source_crop_xywh: tuple[int, int, int, int]
    page_index: int
    path: str
    item_codes: tuple[str, ...]
    png_bytes: bytes
    sha256: str

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "view_id": self.view_id,
            "scale_percent": self.scale_percent,
            "source_crop_xywh": list(self.source_crop_xywh),
            "page_index": self.page_index,
            "path": self.path,
            "sha256": self.sha256,
            "item_codes": list(self.item_codes),
        }


_HEX_GLYPHS = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "a": ("010", "101", "111", "101", "101"),
    "b": ("110", "101", "110", "101", "110"),
    "c": ("111", "100", "100", "100", "111"),
    "d": ("110", "101", "101", "101", "110"),
    "e": ("111", "100", "110", "100", "111"),
    "f": ("111", "100", "110", "100", "100"),
}


_REPO_ROOT = Path(__file__).resolve().parents[3]
_FOUNDATION_SOURCE_CROP_XYWH = (512, 320, 512, 384)
_R17_SCHEDULE_REVISION = (
    "dev-r17-protocol-zero-reference-prequalification-schedule-v1"
)
_R18_SCHEDULE_REVISION = (
    "dev-r18-symmetric-direct-visible-speck-reinforcement-schedule-v1"
)
_R19_SCHEDULE_REVISION = (
    "dev-r19-duplicate-reject-severity-band-equivalence-schedule-v1"
)
_SCHEDULE_REVISION = (
    "dev-r20-strong-finite-duplicate-short-line-sentinel-schedule-v1"
)
_R19_PUBLIC_PAYLOAD_COMMITMENT_PREFIX = (
    b"microtexture-v2-r6/public-payload-commitment/v15/"
)
_PUBLIC_PAYLOAD_COMMITMENT_PREFIX = b"microtexture-v2-r6/public-payload-commitment/v16/"
_PUBLIC_R15_WARNING_ANCHOR_REVISION = (
    "dev-r14-quantized-direct-visible-sparse-warning-v1"
)
_PUBLIC_WARNING_ANCHOR_REVISION = (
    "dev-r16-six-per-sparse-family-direct-visible-warning-v1"
)
_PUBLIC_WARNING_CONVERSION_REVISION = (
    "dev-r16-one-clean-one-clear-per-sparse-family-v1"
)
_PUBLIC_MICROBLOB_REJECT_ANCHOR_REVISION = (
    "dev-r15-calibration-quantized-microblob-reject-v1"
)
_R19_PRIVATE_REFERENCE_TRANSFORM_PREFIX = b"private-reference-transform-v14/"
_R19_FOUNDATION_OFFSET_LANE = "foundation-offset-v13"
_R19_FOUNDATION_ASSIGNMENT_LANE = "foundation-assignment-v13"
_R19_DELTA_LANE = "delta-v13"
_R19_PRIVATE_CONTROL_ID_PREFIX = b"microtexture-v2-r6/private-control-id/v13/"
_R19_ARTIFACT_NONCE_BASES = {"calibration": 1173000, "holdout": 1183000}
_R19_PROTOCOL_ZERO_NONCE_BASES = {"calibration": 1151000, "holdout": 1161000}
_R19_DUPLICATE_AUDIT_NONCES = {
    "calibration": (1191000, 1191001, 1191002),
    "holdout": (1201000, 1201001, 1201002),
}
_PRIVATE_REFERENCE_TRANSFORM_PREFIX = b"private-reference-transform-v15/"
_FOUNDATION_OFFSET_LANE = "foundation-offset-v14"
_FOUNDATION_ASSIGNMENT_LANE = "foundation-assignment-v14"
_DELTA_LANE = "delta-v14"
_PRIVATE_CONTROL_ID_PREFIX = b"microtexture-v2-r6/private-control-id/v14/"
_ARTIFACT_NONCE_BASES = {"calibration": 1273000, "holdout": 1283000}
_PROTOCOL_ZERO_NONCE_BASES = {"calibration": 1251000, "holdout": 1261000}
_DUPLICATE_AUDIT_NONCES = {
    "calibration": (1291000, 1291001, 1291002),
    "holdout": (1301000, 1301001, 1301002),
}
_R20_PUBLIC_NONCES = {
    "calibration": "r6-calibration-v15",
    "holdout": "r6-holdout-v15",
}
_R20_RENDER_SEED_PREFIX = "microtexture-v2-r6/render-seed/v15/"
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
_R17_REFERENCE_PREQUALIFICATION_STATIC_SCORES_SHA256 = (
    "1413b6a4f7dba56cc264a5a5c32a6f101041fa77c8ac82541baaa6843dc81d1f"
)
_R17_REFERENCE_PREQUALIFICATION_STATIC_SELECTED_INDEX = 1
_R17_PRESERVED_R16_ARTIFACT_MORPHOLOGY_SHA256 = (
    "c60917c79ae36278d17cc7ccaa93d798cac17500d2d678b41b0cdea34ff66b30"
)
_R18_SPECK_REINFORCEMENT_REVISION = (
    "dev-r18-symmetric-reject-speck-direct-visible-cross-v1"
)
_R18_SPECK_REINFORCEMENT_MANIFEST = {
    "revision": _R18_SPECK_REINFORCEMENT_REVISION,
    "inherited_schedule_revision": _R17_SCHEDULE_REVISION,
    "schedule_revision": _R18_SCHEDULE_REVISION,
    "sanitized_r17_basis": {
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
    "family": "artifact-speck",
    "target_tiers": ["clear-reject-candidate", "dominant-reject-candidate"],
    "target_conditions_per_split": 10,
    "clear_reject_conditions_per_split": 6,
    "dominant_reject_conditions_per_split": 4,
    "tiny_speck_development_floor": 6,
    "tiny_speck_structural_miss_budget": 4,
    "spot_development_floor": 10,
    "spot_endpoint_relation": "tiny_speck_visible OR microblob_visible",
    "direct_visibility_contract": {
        "diameter_px": 1,
        "minimum_core_count": 4,
        "maximum_core_count": 7,
        "minimum_center_amplitude_l": 11.2,
        "maximum_center_amplitude_l": 12.0,
        "minimum_encoded_axial_shoulder_l": 5,
        "minimum_separation_px": 30,
        "quadrant_stratified": True,
        "returns_to_uninjected_background_outside_one_axial_neighbor": True,
        "microblob_blur_forbidden": True,
        "vision_truth_guaranteed": False,
    },
    "preservation_contract": {
        "clean_morphologies_unchanged": True,
        "warning_morphologies_unchanged": True,
        "all_non_speck_morphologies_unchanged": True,
        "design_tier_membership_unchanged": True,
        "artifact_condition_count_per_split_unchanged": 100,
        "metric_threshold_population_and_rate_contracts_unchanged": True,
    },
    "splits": {
        "calibration": {
            3: {"design_tier": "clear-reject-candidate", "diameter_px": 1, "amplitude_l": 11.2, "count_in_metric_window": 4, "shoulder_fraction": 0.42, "minimum_separation_px": 30},
            5: {"design_tier": "clear-reject-candidate", "diameter_px": 1, "amplitude_l": 11.4, "count_in_metric_window": 4, "shoulder_fraction": 0.44, "minimum_separation_px": 32},
            6: {"design_tier": "dominant-reject-candidate", "diameter_px": 1, "amplitude_l": 11.8, "count_in_metric_window": 4, "shoulder_fraction": 0.50, "minimum_separation_px": 34},
            7: {"design_tier": "clear-reject-candidate", "diameter_px": 1, "amplitude_l": 11.3, "count_in_metric_window": 5, "shoulder_fraction": 0.46, "minimum_separation_px": 30},
            8: {"design_tier": "clear-reject-candidate", "diameter_px": 1, "amplitude_l": 11.5, "count_in_metric_window": 5, "shoulder_fraction": 0.48, "minimum_separation_px": 32},
            12: {"design_tier": "dominant-reject-candidate", "diameter_px": 1, "amplitude_l": 11.9, "count_in_metric_window": 5, "shoulder_fraction": 0.52, "minimum_separation_px": 34},
            15: {"design_tier": "clear-reject-candidate", "diameter_px": 1, "amplitude_l": 11.4, "count_in_metric_window": 6, "shoulder_fraction": 0.50, "minimum_separation_px": 30},
            16: {"design_tier": "dominant-reject-candidate", "diameter_px": 1, "amplitude_l": 12.0, "count_in_metric_window": 6, "shoulder_fraction": 0.54, "minimum_separation_px": 34},
            17: {"design_tier": "dominant-reject-candidate", "diameter_px": 1, "amplitude_l": 12.0, "count_in_metric_window": 7, "shoulder_fraction": 0.56, "minimum_separation_px": 36},
            19: {"design_tier": "clear-reject-candidate", "diameter_px": 1, "amplitude_l": 11.6, "count_in_metric_window": 6, "shoulder_fraction": 0.52, "minimum_separation_px": 32},
        },
        "holdout": {
            1: {"design_tier": "dominant-reject-candidate", "diameter_px": 1, "amplitude_l": 11.9, "count_in_metric_window": 4, "shoulder_fraction": 0.50, "minimum_separation_px": 35},
            3: {"design_tier": "clear-reject-candidate", "diameter_px": 1, "amplitude_l": 11.3, "count_in_metric_window": 4, "shoulder_fraction": 0.42, "minimum_separation_px": 31},
            4: {"design_tier": "clear-reject-candidate", "diameter_px": 1, "amplitude_l": 11.5, "count_in_metric_window": 4, "shoulder_fraction": 0.44, "minimum_separation_px": 33},
            6: {"design_tier": "clear-reject-candidate", "diameter_px": 1, "amplitude_l": 11.4, "count_in_metric_window": 5, "shoulder_fraction": 0.46, "minimum_separation_px": 31},
            9: {"design_tier": "dominant-reject-candidate", "diameter_px": 1, "amplitude_l": 12.0, "count_in_metric_window": 5, "shoulder_fraction": 0.52, "minimum_separation_px": 35},
            10: {"design_tier": "clear-reject-candidate", "diameter_px": 1, "amplitude_l": 11.6, "count_in_metric_window": 5, "shoulder_fraction": 0.48, "minimum_separation_px": 33},
            11: {"design_tier": "clear-reject-candidate", "diameter_px": 1, "amplitude_l": 11.5, "count_in_metric_window": 6, "shoulder_fraction": 0.50, "minimum_separation_px": 31},
            13: {"design_tier": "dominant-reject-candidate", "diameter_px": 1, "amplitude_l": 11.9, "count_in_metric_window": 6, "shoulder_fraction": 0.54, "minimum_separation_px": 35},
            14: {"design_tier": "dominant-reject-candidate", "diameter_px": 1, "amplitude_l": 12.0, "count_in_metric_window": 7, "shoulder_fraction": 0.56, "minimum_separation_px": 37},
            18: {"design_tier": "clear-reject-candidate", "diameter_px": 1, "amplitude_l": 11.7, "count_in_metric_window": 6, "shoulder_fraction": 0.52, "minimum_separation_px": 33},
        },
    },
}
_R18_SPECK_REINFORCEMENT_MANIFEST_SHA256 = (
    "355c6c588c3d698288a3545752c13cea734db85e1e7a9a95416cbe3163f633d4"
)
_R18_FULL_ARTIFACT_MORPHOLOGY_SHA256 = (
    "9eb2326011658d095fe7ae5b1ded80ae3af890483633622e2c7ad34e03385365"
)
_R18_PRESERVED_R17_MORPHOLOGY_SHA256 = (
    "03559cb9f26908f6ed59bd8327250c5d63e77e6e96c34d7f08a47e8cb59a7fdf"
)
_R19_DUPLICATE_EQUIVALENCE_POLICY_REVISION = (
    "dev-r19-reject-ordinal-band-duplicate-equivalence-v1"
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
            _R18_FULL_ARTIFACT_MORPHOLOGY_SHA256
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
_R20_DUPLICATE_SENTINEL_REVISION = (
    "dev-r20-keyed-axial-short-line-duplicate-sentinel-v1"
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
        "full_artifact_morphology_sha256": _R18_FULL_ARTIFACT_MORPHOLOGY_SHA256,
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
_R15_WARNING_ACCEPTANCE_ANCHORS = {
    "revision": _PUBLIC_R15_WARNING_ANCHOR_REVISION,
    "splits": {
        "calibration": {
            "artifact-speck": {
                2: {"design_tier": "warning-candidate", "diameter_px": 1, "amplitude_l": 7.1, "count_in_metric_window": 4, "shoulder_fraction": 0.05, "minimum_separation_px": 12},
                10: {"design_tier": "warning-candidate", "diameter_px": 1, "amplitude_l": 7.3, "count_in_metric_window": 4, "shoulder_fraction": 0.05, "minimum_separation_px": 14},
                11: {"design_tier": "warning-candidate", "diameter_px": 1, "amplitude_l": 7.7, "count_in_metric_window": 4, "shoulder_fraction": 0.05, "minimum_separation_px": 16},
                18: {"design_tier": "warning-candidate", "diameter_px": 1, "amplitude_l": 7.9, "count_in_metric_window": 4, "shoulder_fraction": 0.05, "minimum_separation_px": 18},
            },
            "artifact-microblob": {
                4: {"design_tier": "warning-candidate", "diameter_px": 5, "amplitude_l": 6.8, "count_in_metric_window": 2, "support_radius_px": 5, "minimum_separation_px": 14},
                5: {"design_tier": "warning-candidate", "diameter_px": 6, "amplitude_l": 6.6, "count_in_metric_window": 2, "support_radius_px": 5, "minimum_separation_px": 14},
                12: {"design_tier": "warning-candidate", "diameter_px": 7, "amplitude_l": 6.4, "count_in_metric_window": 2, "support_radius_px": 6, "minimum_separation_px": 16},
                14: {"design_tier": "warning-candidate", "diameter_px": 8, "amplitude_l": 6.2, "count_in_metric_window": 2, "support_radius_px": 7, "minimum_separation_px": 18},
            },
            "artifact-short-dash": {
                6: {"design_tier": "warning-candidate", "length_px": 8, "width_px": 1, "amplitude_l": 7.2, "count_in_metric_window": 1, "minimum_separation_px": 12},
                8: {"design_tier": "warning-candidate", "length_px": 10, "width_px": 1, "amplitude_l": 7.0, "count_in_metric_window": 1, "minimum_separation_px": 14},
                17: {"design_tier": "warning-candidate", "length_px": 12, "width_px": 1, "amplitude_l": 6.8, "count_in_metric_window": 1, "minimum_separation_px": 16},
                19: {"design_tier": "warning-candidate", "length_px": 14, "width_px": 1, "amplitude_l": 6.6, "count_in_metric_window": 1, "minimum_separation_px": 18},
            },
            "artifact-parallel-bundle": {
                0: {"design_tier": "warning-candidate", "length_px": 8, "width_px": 1, "spacing_px": 4, "amplitude_l": 7.2, "pair_count_in_metric_window": 1, "minimum_bundle_separation_px": 12},
                2: {"design_tier": "warning-candidate", "length_px": 10, "width_px": 1, "spacing_px": 4, "amplitude_l": 7.0, "pair_count_in_metric_window": 1, "minimum_bundle_separation_px": 14},
                11: {"design_tier": "warning-candidate", "length_px": 12, "width_px": 1, "spacing_px": 4, "amplitude_l": 6.8, "pair_count_in_metric_window": 1, "minimum_bundle_separation_px": 16},
                13: {"design_tier": "warning-candidate", "length_px": 12, "width_px": 1, "spacing_px": 6, "amplitude_l": 6.6, "pair_count_in_metric_window": 1, "minimum_bundle_separation_px": 16},
            },
        },
        "holdout": {
            "artifact-speck": {
                0: {"design_tier": "warning-candidate", "diameter_px": 1, "amplitude_l": 7.2, "count_in_metric_window": 4, "shoulder_fraction": 0.05, "minimum_separation_px": 13},
                5: {"design_tier": "warning-candidate", "diameter_px": 1, "amplitude_l": 7.4, "count_in_metric_window": 4, "shoulder_fraction": 0.05, "minimum_separation_px": 15},
                12: {"design_tier": "warning-candidate", "diameter_px": 1, "amplitude_l": 7.6, "count_in_metric_window": 4, "shoulder_fraction": 0.05, "minimum_separation_px": 17},
                16: {"design_tier": "warning-candidate", "diameter_px": 1, "amplitude_l": 7.8, "count_in_metric_window": 4, "shoulder_fraction": 0.05, "minimum_separation_px": 19},
            },
            "artifact-microblob": {
                6: {"design_tier": "warning-candidate", "diameter_px": 5, "amplitude_l": 6.9, "count_in_metric_window": 2, "support_radius_px": 5, "minimum_separation_px": 14},
                10: {"design_tier": "warning-candidate", "diameter_px": 6, "amplitude_l": 6.7, "count_in_metric_window": 2, "support_radius_px": 5, "minimum_separation_px": 14},
                15: {"design_tier": "warning-candidate", "diameter_px": 7, "amplitude_l": 6.3, "count_in_metric_window": 2, "support_radius_px": 6, "minimum_separation_px": 16},
                17: {"design_tier": "warning-candidate", "diameter_px": 8, "amplitude_l": 6.1, "count_in_metric_window": 2, "support_radius_px": 7, "minimum_separation_px": 18},
            },
            "artifact-short-dash": {
                0: {"design_tier": "warning-candidate", "length_px": 8, "width_px": 1, "amplitude_l": 7.3, "count_in_metric_window": 1, "minimum_separation_px": 12},
                4: {"design_tier": "warning-candidate", "length_px": 10, "width_px": 1, "amplitude_l": 7.1, "count_in_metric_window": 1, "minimum_separation_px": 14},
                9: {"design_tier": "warning-candidate", "length_px": 12, "width_px": 1, "amplitude_l": 6.9, "count_in_metric_window": 1, "minimum_separation_px": 16},
                11: {"design_tier": "warning-candidate", "length_px": 14, "width_px": 1, "amplitude_l": 6.7, "count_in_metric_window": 1, "minimum_separation_px": 18},
            },
            "artifact-parallel-bundle": {
                3: {"design_tier": "warning-candidate", "length_px": 8, "width_px": 1, "spacing_px": 4, "amplitude_l": 7.3, "pair_count_in_metric_window": 1, "minimum_bundle_separation_px": 12},
                5: {"design_tier": "warning-candidate", "length_px": 10, "width_px": 1, "spacing_px": 6, "amplitude_l": 7.1, "pair_count_in_metric_window": 1, "minimum_bundle_separation_px": 14},
                15: {"design_tier": "warning-candidate", "length_px": 12, "width_px": 1, "spacing_px": 4, "amplitude_l": 6.9, "pair_count_in_metric_window": 1, "minimum_bundle_separation_px": 16},
                19: {"design_tier": "warning-candidate", "length_px": 12, "width_px": 1, "spacing_px": 6, "amplitude_l": 6.7, "pair_count_in_metric_window": 1, "minimum_bundle_separation_px": 16},
            },
        },
    },
}
_R16_WARNING_CONVERSION_SOURCES = {
    "calibration": {
        "artifact-speck": {0: "clean-candidate", 1: "clear-reject-candidate"},
        "artifact-microblob": {15: "clean-candidate", 16: "clear-reject-candidate"},
        "artifact-short-dash": {9: "clean-candidate", 16: "clear-reject-candidate"},
        "artifact-parallel-bundle": {3: "clean-candidate", 10: "clear-reject-candidate"},
    },
    "holdout": {
        "artifact-speck": {19: "clean-candidate", 17: "clear-reject-candidate"},
        "artifact-microblob": {13: "clean-candidate", 11: "clear-reject-candidate"},
        "artifact-short-dash": {7: "clean-candidate", 5: "clear-reject-candidate"},
        "artifact-parallel-bundle": {8: "clean-candidate", 13: "clear-reject-candidate"},
    },
}
_R16_WARNING_CONVERSION_ANCHORS = {
    "calibration": {
        "artifact-speck": {
            0: {"design_tier": "warning-candidate", "diameter_px": 1, "amplitude_l": 7.5, "count_in_metric_window": 4, "shoulder_fraction": 0.05, "minimum_separation_px": 13},
            1: {"design_tier": "warning-candidate", "diameter_px": 1, "amplitude_l": 7.6, "count_in_metric_window": 4, "shoulder_fraction": 0.05, "minimum_separation_px": 15},
        },
        "artifact-microblob": {
            15: {"design_tier": "warning-candidate", "diameter_px": 4, "amplitude_l": 7.0, "count_in_metric_window": 4, "support_radius_px": 2, "minimum_separation_px": 12},
            16: {"design_tier": "warning-candidate", "diameter_px": 6, "amplitude_l": 7.2, "count_in_metric_window": 4, "support_radius_px": 3, "minimum_separation_px": 15},
        },
        "artifact-short-dash": {
            9: {"design_tier": "warning-candidate", "length_px": 6, "width_px": 1, "amplitude_l": 7.4, "count_in_metric_window": 2, "minimum_separation_px": 10},
            16: {"design_tier": "warning-candidate", "length_px": 16, "width_px": 1, "amplitude_l": 6.4, "count_in_metric_window": 1, "minimum_separation_px": 20},
        },
        "artifact-parallel-bundle": {
            3: {"design_tier": "warning-candidate", "length_px": 8, "width_px": 1, "spacing_px": 6, "amplitude_l": 7.4, "pair_count_in_metric_window": 1, "minimum_bundle_separation_px": 14},
            10: {"design_tier": "warning-candidate", "length_px": 10, "width_px": 1, "spacing_px": 6, "amplitude_l": 6.4, "pair_count_in_metric_window": 1, "minimum_bundle_separation_px": 14},
        },
    },
    "holdout": {
        "artifact-speck": {
            19: {"design_tier": "warning-candidate", "diameter_px": 1, "amplitude_l": 7.5, "count_in_metric_window": 4, "shoulder_fraction": 0.05, "minimum_separation_px": 14},
            17: {"design_tier": "warning-candidate", "diameter_px": 1, "amplitude_l": 8.0, "count_in_metric_window": 4, "shoulder_fraction": 0.05, "minimum_separation_px": 16},
        },
        "artifact-microblob": {
            13: {"design_tier": "warning-candidate", "diameter_px": 4, "amplitude_l": 7.1, "count_in_metric_window": 4, "support_radius_px": 2, "minimum_separation_px": 13},
            11: {"design_tier": "warning-candidate", "diameter_px": 6, "amplitude_l": 7.3, "count_in_metric_window": 4, "support_radius_px": 3, "minimum_separation_px": 16},
        },
        "artifact-short-dash": {
            7: {"design_tier": "warning-candidate", "length_px": 6, "width_px": 1, "amplitude_l": 7.5, "count_in_metric_window": 2, "minimum_separation_px": 10},
            5: {"design_tier": "warning-candidate", "length_px": 16, "width_px": 1, "amplitude_l": 6.5, "count_in_metric_window": 1, "minimum_separation_px": 20},
        },
        "artifact-parallel-bundle": {
            8: {"design_tier": "warning-candidate", "length_px": 8, "width_px": 1, "spacing_px": 6, "amplitude_l": 7.5, "pair_count_in_metric_window": 1, "minimum_bundle_separation_px": 14},
            13: {"design_tier": "warning-candidate", "length_px": 10, "width_px": 1, "spacing_px": 4, "amplitude_l": 6.5, "pair_count_in_metric_window": 1, "minimum_bundle_separation_px": 14},
        },
    },
}
_WARNING_ACCEPTANCE_ANCHORS = {
    "revision": _PUBLIC_WARNING_ANCHOR_REVISION,
    "splits": {
        split: {
            family: {
                **_R15_WARNING_ACCEPTANCE_ANCHORS["splits"][split][family],
                **_R16_WARNING_CONVERSION_ANCHORS[split][family],
            }
            for family in (
                "artifact-speck",
                "artifact-microblob",
                "artifact-short-dash",
                "artifact-parallel-bundle",
            )
        }
        for split in ("calibration", "holdout")
    },
}
_CALIBRATION_MICROBLOB_CLEAR_REJECT_ANCHORS = {
    "revision": _PUBLIC_MICROBLOB_REJECT_ANCHOR_REVISION,
    "entries": {
        1: {"design_tier": "clear-reject-candidate", "diameter_px": 4, "amplitude_l": 11.6, "count_in_metric_window": 64, "support_radius_px": 2, "minimum_separation_px": 13},
        2: {"design_tier": "clear-reject-candidate", "diameter_px": 4, "amplitude_l": 11.8, "count_in_metric_window": 64, "support_radius_px": 2, "minimum_separation_px": 14},
        9: {"design_tier": "clear-reject-candidate", "diameter_px": 4, "amplitude_l": 11.4, "count_in_metric_window": 64, "support_radius_px": 2, "minimum_separation_px": 12},
        13: {"design_tier": "clear-reject-candidate", "diameter_px": 6, "amplitude_l": 11.6, "count_in_metric_window": 44, "support_radius_px": 3, "minimum_separation_px": 16},
        16: {"design_tier": "clear-reject-candidate", "diameter_px": 5, "amplitude_l": 12.0, "count_in_metric_window": 52, "support_radius_px": 3, "minimum_separation_px": 15},
        17: {"design_tier": "clear-reject-candidate", "diameter_px": 6, "amplitude_l": 11.8, "count_in_metric_window": 44, "support_radius_px": 3, "minimum_separation_px": 17},
        18: {"design_tier": "clear-reject-candidate", "diameter_px": 6, "amplitude_l": 11.4, "count_in_metric_window": 44, "support_radius_px": 3, "minimum_separation_px": 15},
    },
}
_FOUNDATIONS = (
    (
        "v15",
        "world/map-production/style-assets/"
        "microtexture-v2-r6-foundation-imagegen-v15.png",
        "15695cf533d0aa495a83cbd35657e1d68244538e79028e83bbb32d952db0379f",
    ),
    (
        "v16",
        "world/map-production/style-assets/"
        "microtexture-v2-r6-foundation-imagegen-v16.png",
        "4e6cd844c88cf550d8f85da65d63525f99c58fd599a06d7a568c38412e54712f",
    ),
    (
        "v17",
        "world/map-production/style-assets/"
        "microtexture-v2-r6-foundation-imagegen-v17.png",
        "fa08d0921ee319a279038e84e5318a8b0e759ff3ac55fb439a635329c9e8b6ea",
    ),
)


@lru_cache(maxsize=1)
def _foundation_bank() -> dict[str, np.ndarray]:
    left, top, width, height = _FOUNDATION_SOURCE_CROP_XYWH
    bank: dict[str, np.ndarray] = {}
    for foundation_id, relative_path, expected_sha256 in _FOUNDATIONS:
        path = _REPO_ROOT / relative_path
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise RuntimeError(f"r6 foundation SHA drift: {foundation_id}")
        with Image.open(io.BytesIO(payload)) as opened:
            opened.load()
            if opened.mode != "RGB" or opened.size != (1536, 1024):
                raise RuntimeError(
                    f"r6 foundation image contract drift: {foundation_id}"
                )
            rgb = np.asarray(
                opened.crop((left, top, left + width, top + height)),
                dtype=np.uint8,
            )
        if rgb.shape != (height, width, 3):
            raise RuntimeError(f"r6 foundation crop geometry drift: {foundation_id}")
        values = rgb.astype(np.float32)
        luminance = (
            np.float32(0.299) * values[:, :, 0]
            + np.float32(0.587) * values[:, :, 1]
            + np.float32(0.114) * values[:, :, 2]
        ).astype(np.float32)
        luminance.setflags(write=False)
        bank[foundation_id] = luminance
    if set(bank) != {"v15", "v16", "v17"}:
        raise RuntimeError("r6 foundation allowlist drift")
    return bank


def _draw_hex_label(
    sheet: np.ndarray, code: str, origin_x: int, origin_y: int, fill: int
) -> None:
    glyph_scale = 2
    advance = 8
    for character_index, character in enumerate(code):
        glyph = _HEX_GLYPHS[character]
        x_base = origin_x + character_index * advance
        for row, bits in enumerate(glyph):
            for column, bit in enumerate(bits):
                if bit == "1":
                    y0 = origin_y + row * glyph_scale
                    x0 = x_base + column * glyph_scale
                    sheet[y0 : y0 + glyph_scale, x0 : x0 + glyph_scale] = np.uint8(fill)


def _hmac_material(
    key: bytes, prefix: str, identity: dict[str, Any], lane: str
) -> bytes:
    return blind_hmac(
        key,
        prefix.encode("ascii")
        + lane.encode("ascii")
        + b"/"
        + canonical_json_bytes(identity),
    )


def _public_payload_commitment(
    key: bytes, anonymous_code: str, lane: str, payload_sha256: str
) -> str:
    if lane not in {"control", "reference", "delta"}:
        raise RuntimeError("invalid r6 public payload-commitment lane")
    return blind_hmac(
        key,
        _PUBLIC_PAYLOAD_COMMITMENT_PREFIX
        + lane.encode("ascii")
        + b"/"
        + anonymous_code.encode("ascii")
        + b"/"
        + bytes.fromhex(payload_sha256),
    ).hex()


def _hmac_prf_grid_integers(
    *,
    key: bytes,
    prefix: str,
    identity: dict[str, Any],
    lane: str,
    shape: tuple[int, int],
    candidate_index: int,
    private_reference_transform_prefix: bytes | None = None,
) -> tuple[int, ...]:
    """Derive exact uint64 coefficient material for one r17 candidate."""

    candidate_count = int(_R17_REFERENCE_PREQUALIFICATION_MANIFEST["candidate_count"])
    expected_shape = tuple(
        int(value)
        for value in _R17_REFERENCE_PREQUALIFICATION_MANIFEST["coefficient_grid_hw"]
    )
    if (
        not 0 <= candidate_index < candidate_count
        or shape != expected_shape
        or lane
        not in _R17_REFERENCE_PREQUALIFICATION_MANIFEST["score_lane_integer_weights"]
    ):
        raise RuntimeError("r17 reference-prequalification candidate contract drift")
    count = shape[0] * shape[1]
    values: list[int] = []
    counter = 0
    identity_bytes = canonical_json_bytes(identity)
    candidate_domain = f"candidate/{candidate_index:02d}/".encode("ascii")
    domain = (
        prefix.encode("ascii")
        + (
            _PRIVATE_REFERENCE_TRANSFORM_PREFIX
            if private_reference_transform_prefix is None
            else private_reference_transform_prefix
        )
        + candidate_domain
        + lane.encode("ascii")
        + b"/"
        + identity_bytes
        + b"/"
    )
    while len(values) < count:
        digest = blind_hmac(key, domain + counter.to_bytes(4, "big"))
        for offset in range(0, len(digest), 8):
            integer = int.from_bytes(digest[offset : offset + 8], "big")
            values.append(integer)
            if len(values) == count:
                break
        counter += 1
    return tuple(values)


def _hmac_prf_grid(
    *,
    key: bytes,
    prefix: str,
    identity: dict[str, Any],
    lane: str,
    shape: tuple[int, int],
    candidate_index: int,
    private_reference_transform_prefix: bytes | None = None,
) -> np.ndarray:
    """Map exact r17 candidate material to the established float32 grid."""

    maximum = float((1 << 64) - 1)
    integers = _hmac_prf_grid_integers(
        key=key,
        prefix=prefix,
        identity=identity,
        lane=lane,
        shape=shape,
        candidate_index=candidate_index,
        private_reference_transform_prefix=private_reference_transform_prefix,
    )
    values = [(integer / maximum) * 2.0 - 1.0 for integer in integers]
    return np.asarray(values, dtype=np.float32).reshape(shape)


def _reference_prequalification_candidate_scores(
    *,
    key: bytes,
    prefix: str,
    identity: dict[str, Any],
    private_reference_transform_prefix: bytes | None = None,
) -> tuple[tuple[int, int, int, int, int], ...]:
    """Score HMAC coefficient candidates without pixels, labels, or deltas."""

    manifest = _R17_REFERENCE_PREQUALIFICATION_MANIFEST
    grid_height, grid_width = [int(value) for value in manifest["coefficient_grid_hw"]]
    maximum = (1 << 64) - 1
    scores: list[tuple[int, int, int, int, int]] = []
    for candidate_index in range(int(manifest["candidate_count"])):
        weighted_jumps: list[int] = []
        weighted_magnitudes: list[int] = []
        for lane, raw_weight in manifest["score_lane_integer_weights"].items():
            weight = int(raw_weight)
            values = _hmac_prf_grid_integers(
                key=key,
                prefix=prefix,
                identity=identity,
                lane=str(lane),
                shape=(grid_height, grid_width),
                candidate_index=candidate_index,
                private_reference_transform_prefix=(
                    private_reference_transform_prefix
                ),
            )
            for y in range(grid_height):
                for x in range(grid_width):
                    index = y * grid_width + x
                    value = values[index]
                    weighted_magnitudes.append(weight * abs(2 * value - maximum))
                    if x + 1 < grid_width:
                        weighted_jumps.append(weight * abs(value - values[index + 1]))
                    if y + 1 < grid_height:
                        weighted_jumps.append(
                            weight * abs(value - values[index + grid_width])
                        )
        if not weighted_jumps or not weighted_magnitudes:
            raise RuntimeError("r17 reference-prequalification score is empty")
        scores.append(
            (
                max(weighted_jumps),
                sum(weighted_jumps),
                max(weighted_magnitudes),
                sum(weighted_magnitudes),
                candidate_index,
            )
        )
    return tuple(scores)


def _select_reference_prequalification_candidate(
    *,
    key: bytes,
    prefix: str,
    identity: dict[str, Any],
    private_reference_transform_prefix: bytes | None = None,
) -> tuple[int, tuple[tuple[int, int, int, int, int], ...]]:
    scores = _reference_prequalification_candidate_scores(
        key=key,
        prefix=prefix,
        identity=identity,
        private_reference_transform_prefix=private_reference_transform_prefix,
    )
    selected_index = min(range(len(scores)), key=scores.__getitem__)
    if scores[selected_index] > scores[0]:
        raise RuntimeError("r17 reference prequalification worsened candidate zero")
    return selected_index, scores


@lru_cache(maxsize=1)
def _validate_dev_r17_reference_prequalification_design() -> None:
    manifest = _R17_REFERENCE_PREQUALIFICATION_MANIFEST
    if (
        set(manifest)
        != {
            "revision",
            "applies_to_private_roles",
            "candidate_count",
            "coefficient_grid_hw",
            "candidate_domain",
            "score_lane_integer_weights",
            "score_terms_in_lexicographic_order",
            "selection_rule",
            "selection_uses_pixels",
            "selection_uses_requested_delta",
            "selection_uses_labels_or_decisions",
            "selection_branches_on_private_role",
            "selected_score_not_worse_than_candidate_zero",
            "truth_guarantee_claimed",
        }
        or manifest["revision"] != _R17_REFERENCE_PREQUALIFICATION_REVISION
        or manifest["applies_to_private_roles"]
        != ["artifact", "protocol-zero", "duplicate-audit"]
        or manifest["candidate_count"] != 8
        or manifest["coefficient_grid_hw"] != [7, 9]
        or manifest["candidate_domain"] != "candidate/{index:02d}/"
        or manifest["score_lane_integer_weights"]
        != {"displacement-y": 7, "displacement-x": 7, "tone": 3}
        or manifest["score_terms_in_lexicographic_order"]
        != [
            "maximum-weighted-orthogonal-neighbor-jump",
            "sum-weighted-orthogonal-neighbor-jumps",
            "maximum-weighted-centered-coefficient-magnitude",
            "sum-weighted-centered-coefficient-magnitudes",
            "candidate-index",
        ]
        or manifest["selection_rule"] != "lexicographic-minimum"
        or manifest["selection_uses_pixels"] is not False
        or manifest["selection_uses_requested_delta"] is not False
        or manifest["selection_uses_labels_or_decisions"] is not False
        or manifest["selection_branches_on_private_role"] is not False
        or manifest["selected_score_not_worse_than_candidate_zero"] is not True
        or manifest["truth_guarantee_claimed"] is not False
        or sha256_bytes(canonical_json_bytes(manifest))
        != _R17_REFERENCE_PREQUALIFICATION_MANIFEST_SHA256
    ):
        raise RuntimeError("r17 reference-prequalification manifest drift")

    static_key = hashlib.sha256(
        b"microtexture-v2-r6/dev-r17/reference-prequalification/static-key"
    ).digest()
    static_identity = {
        "split": "calibration",
        "public_nonce": "r6-calibration-v12",
        "private_role": "protocol-zero",
        "family": "protocol-zero",
        "variant_index": 0,
        "parameters": {
            "schedule_revision": _R17_SCHEDULE_REVISION,
            "protocol_nonce": 951000,
        },
        "duplicate_audit_group": None,
        "foundation_id": "v15",
        "replicate": 0,
        "polarity": 1,
    }
    selected_index, scores = _select_reference_prequalification_candidate(
        key=static_key,
        prefix="microtexture-v2-r6/render-seed/v12/",
        identity=static_identity,
        private_reference_transform_prefix=b"private-reference-transform-v12/",
    )
    scores_sha = sha256_bytes(
        canonical_json_bytes(
            {
                "revision": _R17_REFERENCE_PREQUALIFICATION_REVISION,
                "scores": [list(score) for score in scores],
            }
        )
    )
    if (
        selected_index != _R17_REFERENCE_PREQUALIFICATION_STATIC_SELECTED_INDEX
        or scores_sha != _R17_REFERENCE_PREQUALIFICATION_STATIC_SCORES_SHA256
        or scores[selected_index] != min(scores)
        or scores[selected_index] > scores[0]
    ):
        raise RuntimeError("r17 reference-prequalification static vector drift")


def _private_reference_transform(
    reference: np.ndarray,
    *,
    key: bytes,
    prefix: str,
    identity: dict[str, Any],
    settings: dict[str, Any],
) -> np.ndarray:
    """Create a unique clean private reference without a public equality oracle."""

    if reference.ndim != 2 or reference.dtype != np.float32:
        raise RuntimeError("invalid r6 private reference-transform source")
    grid_height, grid_width = [int(value) for value in settings["control_grid_hw"]]
    maximum_displacement = float(settings["maximum_displacement_px"])
    maximum_tone = float(settings["maximum_tone_l"])
    interpolation_order = int(settings["interpolation_order"])
    coefficient_interpolation_order = int(settings["coefficient_interpolation_order"])
    boundary_mode = str(settings["boundary_mode"])
    safety_minimum = int(settings["encoded_luminance_minimum"])
    safety_maximum = int(settings["encoded_luminance_maximum"])
    if (
        (grid_height, grid_width) != (7, 9)
        or maximum_displacement != 1.75
        or maximum_tone != 0.75
        or interpolation_order != 1
        or coefficient_interpolation_order != 3
        or boundary_mode != "reflect"
        or (safety_minimum, safety_maximum) != (16, 243)
    ):
        raise RuntimeError("r6 private reference-transform parameter drift")

    candidate_index, _candidate_scores = _select_reference_prequalification_candidate(
        key=key,
        prefix=prefix,
        identity=identity,
    )

    height, width = reference.shape
    target_y, target_x = np.meshgrid(
        np.linspace(0.0, grid_height - 1, height, dtype=np.float32),
        np.linspace(0.0, grid_width - 1, width, dtype=np.float32),
        indexing="ij",
    )

    def field(lane: str, scale: float) -> np.ndarray:
        grid = _hmac_prf_grid(
            key=key,
            prefix=prefix,
            identity=identity,
            lane=lane,
            shape=(grid_height, grid_width),
            candidate_index=candidate_index,
        )
        expanded = ndimage.map_coordinates(
            grid,
            (target_y, target_x),
            order=coefficient_interpolation_order,
            mode=boundary_mode,
            prefilter=True,
        )
        return np.clip(expanded, -1.0, 1.0).astype(np.float32) * np.float32(scale)

    displacement_y = field("displacement-y", maximum_displacement)
    displacement_x = field("displacement-x", maximum_displacement)
    tone = field("tone", maximum_tone)
    source_y, source_x = np.meshgrid(
        np.arange(height, dtype=np.float32),
        np.arange(width, dtype=np.float32),
        indexing="ij",
    )
    warped = ndimage.map_coordinates(
        reference,
        (source_y + displacement_y, source_x + displacement_x),
        order=interpolation_order,
        mode=boundary_mode,
        prefilter=False,
    )
    encoded = np.clip(np.rint(warped + tone), safety_minimum, safety_maximum).astype(
        np.uint8
    )
    if encoded.shape != reference.shape:
        raise RuntimeError("r6 private reference-transform geometry drift")
    return encoded


def _normalize_rms(values: np.ndarray, target: float) -> np.ndarray:
    centered = values.astype(np.float32) - np.float32(values.mean())
    rms = float(np.sqrt(np.mean(centered * centered)))
    return centered * np.float32(target / max(rms, 1e-12))


def _metric_quadrants(
    metric_window_xywh: tuple[int, int, int, int],
) -> tuple[tuple[int, int, int, int], ...]:
    left, top, width, height = metric_window_xywh
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise RuntimeError("r6 metric window cannot form four exact quadrants")
    half_width, half_height = width // 2, height // 2
    return (
        (left, top, half_width, half_height),
        (left + half_width, top, half_width, half_height),
        (left, top + half_height, half_width, half_height),
        (left + half_width, top + half_height, half_width, half_height),
    )


def _chebyshev_distance(first: tuple[int, int], second: tuple[int, int]) -> int:
    return max(abs(first[0] - second[0]), abs(first[1] - second[1]))


def _stratified_separated_integer_positions(
    rng: np.random.Generator,
    count: int,
    metric_window_xywh: tuple[int, int, int, int],
    *,
    margin: int,
    minimum_separation_px: int,
) -> list[tuple[int, int]]:
    """Pack seeded integer centers evenly across the four exact 400% quadrants."""

    if count <= 0:
        raise RuntimeError("sparse-control count must be positive")
    if margin < 0 or minimum_separation_px <= 0:
        raise RuntimeError("invalid r6 deterministic-packing geometry")
    quadrants = _metric_quadrants(metric_window_xywh)
    quadrant_order = [int(value) for value in rng.permutation(len(quadrants))]

    def lattice_fallback() -> list[tuple[int, int]]:
        # Keep centers away from the two internal quadrant boundaries far enough
        # that independently selected quadrant lattices cannot violate the global
        # Chebyshev separation.  Outer boundaries retain the caller's support
        # margin.  The centered, sep-spaced grids make this path bounded rather
        # than another randomized packing attempt.
        internal_guard = max(
            0,
            math.ceil(
                (minimum_separation_px - (2 * margin + 1)) / 2,
            ),
        )
        quadrant_counts = Counter(
            quadrant_order[item_index % len(quadrants)] for item_index in range(count)
        )
        lattice_pools: dict[int, list[tuple[int, int]]] = {}
        for quadrant_index, (left, top, width, height) in enumerate(quadrants):
            x_min, x_max = left + margin, left + width - margin - 1
            y_min, y_max = top + margin, top + height - margin - 1
            if quadrant_index % 2 == 0:
                x_max -= internal_guard
            else:
                x_min += internal_guard
            if quadrant_index < 2:
                y_max -= internal_guard
            else:
                y_min += internal_guard
            if x_min > x_max or y_min > y_max:
                raise RuntimeError("r6 fallback guard consumes a 400% quadrant")

            x_slack = (x_max - x_min) % minimum_separation_px
            y_slack = (y_max - y_min) % minimum_separation_px
            x_start = x_min + x_slack // 2
            y_start = y_min + y_slack // 2
            candidates = [
                (x, y)
                for y in range(y_start, y_max + 1, minimum_separation_px)
                for x in range(x_start, x_max + 1, minimum_separation_px)
            ]
            required = quadrant_counts[quadrant_index]
            if len(candidates) < required:
                raise RuntimeError(
                    "r6 deterministic sparse lattice lacks quadrant capacity"
                )
            permutation = rng.permutation(len(candidates))
            lattice_pools[quadrant_index] = [
                candidates[int(index)] for index in permutation[:required]
            ]

        return [
            lattice_pools[quadrant_order[item_index % len(quadrants)]].pop()
            for item_index in range(count)
        ]

    candidate_pools: dict[int, list[tuple[int, int]]] = {}
    for quadrant_index, (left, top, width, height) in enumerate(quadrants):
        x_min, x_max = left + margin, left + width - margin - 1
        y_min, y_max = top + margin, top + height - margin - 1
        if x_min > x_max or y_min > y_max:
            raise RuntimeError("r6 packing margin consumes a 400% quadrant")
        candidates = [
            (x, y) for y in range(y_min, y_max + 1) for x in range(x_min, x_max + 1)
        ]
        permutation = rng.permutation(len(candidates))
        candidate_pools[quadrant_index] = [
            candidates[int(index)] for index in permutation
        ]

    selected: list[tuple[int, int]] = []
    selected_quadrants: list[int] = []
    for item_index in range(count):
        quadrant_index = quadrant_order[item_index % len(quadrants)]
        pool = candidate_pools[quadrant_index]
        position: tuple[int, int] | None = None
        while pool:
            candidate = pool.pop()
            if all(
                _chebyshev_distance(candidate, existing) >= minimum_separation_px
                for existing in selected
            ):
                position = candidate
                break
        if position is None:
            selected = lattice_fallback()
            break
        selected.append(position)
        selected_quadrants.append(quadrant_index)

    if len(selected) == count and len(selected_quadrants) != count:
        selected_quadrants = [
            quadrant_order[item_index % len(quadrants)] for item_index in range(count)
        ]

    quadrant_counts = Counter(selected_quadrants)
    counts = [quadrant_counts[index] for index in range(4)]
    if max(counts) - min(counts) > 1:
        raise RuntimeError("r6 sparse packing lost four-quadrant stratification")
    if any(
        _chebyshev_distance(first, second) < minimum_separation_px
        for first_index, first in enumerate(selected)
        for second in selected[first_index + 1 :]
    ):
        raise RuntimeError("r6 sparse packing violated Chebyshev separation")
    return selected


def _line_mask(
    height: int, width: int, lines: list[tuple[float, float, float, float, int]]
) -> np.ndarray:
    image = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(image)
    for x0, y0, x1, y1, line_width in lines:
        draw.line((x0, y0, x1, y1), fill=255, width=max(1, line_width))
    return np.asarray(image, dtype=np.float32) / np.float32(255.0)


def _retain_metric_support(
    field: np.ndarray,
    rng: np.random.Generator,
    metric_window_xywh: tuple[int, int, int, int],
    support_fraction: float,
) -> np.ndarray:
    if not 0.0 < support_fraction <= 1.0:
        raise RuntimeError("r6 fine-grain support fraction must be within (0, 1]")
    if support_fraction == 1.0:
        return field
    left, top, width, height = metric_window_xywh
    region = field[top : top + height, left : left + width]
    candidate_y, candidate_x = np.nonzero(np.abs(region) > np.float32(0.5001))
    if not candidate_y.size:
        raise RuntimeError("r6 fine-grain sparse support has no encodable candidate")
    target_count = min(
        candidate_y.size,
        max(1, int(math.ceil(width * height * support_fraction))),
    )
    selected = rng.choice(candidate_y.size, size=target_count, replace=False)
    retained = np.zeros_like(field)
    retained[top + candidate_y[selected], left + candidate_x[selected]] = region[
        candidate_y[selected], candidate_x[selected]
    ]
    return retained


def _r20_obvious_artifact_duplicate_parameters(split: str) -> dict[str, Any]:
    if split not in {"calibration", "holdout"}:
        raise ValueError("invalid r20 duplicate-sentinel split")
    _, artifact_audit_nonce, artifact_condition_nonce = _DUPLICATE_AUDIT_NONCES[
        split
    ]
    return {
        "schedule_revision": _SCHEDULE_REVISION,
        "audit_nonce": artifact_audit_nonce,
        "audit_kind": "obvious-artifact-isomorphic-replicate",
        "condition_nonce": artifact_condition_nonce,
        "sentinel_revision": _R20_DUPLICATE_SENTINEL_REVISION,
        "length_px": 24,
        "width_px": 3,
        "amplitude_l": 12.0,
        "count_in_metric_window": 12,
        "bars_per_exact_metric_quadrant": 3,
        "minimum_separation_px": 32,
        "center_margin_px": 14,
        "minimum_support_guard_px": 2,
    }


def _validate_r20_duplicate_sentinel_raster(
    field: np.ndarray,
    centers: list[tuple[int, int]],
    orientations: list[str],
    metric_window_xywh: tuple[int, int, int, int],
) -> None:
    """Prove the finite native-pixel geometry promised by the r20 sentinel."""

    if field.shape != (384, 512) or field.dtype != np.float32:
        raise RuntimeError("r20 duplicate sentinel canvas/dtype drift")
    nonzero = field != np.float32(0.0)
    if (
        len(centers) != 12
        or len(orientations) != 12
        or set(orientations) != {"horizontal", "vertical"}
        or int(np.count_nonzero(nonzero)) != 864
        or np.unique(field[nonzero]).tolist() != [12.0]
    ):
        raise RuntimeError("r20 duplicate sentinel finite raster drift")
    if any(
        _chebyshev_distance(first, second) < 32
        for first_index, first in enumerate(centers)
        for second in centers[first_index + 1 :]
    ):
        raise RuntimeError("r20 duplicate sentinel center separation drift")

    left, top, metric_width, metric_height = metric_window_xywh
    outside = nonzero.copy()
    outside[top : top + metric_height, left : left + metric_width] = False
    if np.any(outside):
        raise RuntimeError("r20 duplicate sentinel escaped metric window")

    labels, component_count = ndimage.label(
        nonzero, structure=np.ones((3, 3), dtype=np.uint8)
    )
    if int(component_count) != 12:
        raise RuntimeError("r20 duplicate sentinel component-count drift")
    quadrants = _metric_quadrants(metric_window_xywh)
    quadrant_component_counts = Counter()
    quadrant_orientations: dict[int, set[str]] = {
        index: set() for index in range(4)
    }
    for component_index in range(1, int(component_count) + 1):
        yy, xx = np.nonzero(labels == component_index)
        if yy.size != 72:
            raise RuntimeError("r20 duplicate sentinel component area drift")
        min_x, max_x = int(xx.min()), int(xx.max())
        min_y, max_y = int(yy.min()), int(yy.max())
        shape = (max_y - min_y + 1, max_x - min_x + 1)
        if shape not in {(3, 24), (24, 3)}:
            raise RuntimeError("r20 duplicate sentinel component shape drift")
        orientation = "horizontal" if shape == (3, 24) else "vertical"
        containing = [
            quadrant_index
            for quadrant_index, (q_left, q_top, q_width, q_height) in enumerate(
                quadrants
            )
            if min_x >= q_left + 2
            and max_x <= q_left + q_width - 3
            and min_y >= q_top + 2
            and max_y <= q_top + q_height - 3
        ]
        if len(containing) != 1:
            raise RuntimeError("r20 duplicate sentinel quadrant containment drift")
        quadrant_index = containing[0]
        quadrant_component_counts[quadrant_index] += 1
        quadrant_orientations[quadrant_index].add(orientation)
    if (
        [quadrant_component_counts[index] for index in range(4)] != [3, 3, 3, 3]
        or any(
            quadrant_orientations[index] != {"horizontal", "vertical"}
            for index in range(4)
        )
    ):
        raise RuntimeError("r20 duplicate sentinel quadrant/orientation drift")


def _render_r20_duplicate_obvious_short_line_sentinel(
    parameters: dict[str, Any],
    rng: np.random.Generator,
    height: int,
    width: int,
    metric_window_xywh: tuple[int, int, int, int],
) -> np.ndarray:
    expected_parameters = [
        _r20_obvious_artifact_duplicate_parameters(split)
        for split in ("calibration", "holdout")
    ]
    if (
        parameters not in expected_parameters
        or (height, width) != (384, 512)
        or metric_window_xywh != (128, 96, 256, 192)
    ):
        raise RuntimeError("r20 duplicate sentinel parameter/geometry drift")
    centers = _stratified_separated_integer_positions(
        rng,
        12,
        metric_window_xywh,
        margin=14,
        minimum_separation_px=32,
    )
    quadrants = _metric_quadrants(metric_window_xywh)
    center_quadrants: list[int] = []
    for x, y in centers:
        matches = [
            index
            for index, (left, top, q_width, q_height) in enumerate(quadrants)
            if left <= x < left + q_width and top <= y < top + q_height
        ]
        if len(matches) != 1:
            raise RuntimeError("r20 duplicate sentinel center quadrant drift")
        center_quadrants.append(matches[0])
    phases = [int(value) for value in rng.integers(0, 2, size=4)]
    local_indices = Counter()
    orientations: list[str] = []
    field = np.zeros((height, width), dtype=np.float32)
    for (x, y), quadrant_index in zip(centers, center_quadrants, strict=True):
        local_index = local_indices[quadrant_index]
        local_indices[quadrant_index] += 1
        phase = phases[quadrant_index]
        if phase == 0:
            orientation = ("horizontal", "horizontal", "vertical")[local_index]
        else:
            orientation = ("vertical", "vertical", "horizontal")[local_index]
        orientations.append(orientation)
        if orientation == "horizontal":
            field[y - 1 : y + 2, x - 12 : x + 12] = np.float32(12.0)
        else:
            field[y - 12 : y + 12, x - 1 : x + 2] = np.float32(12.0)
    _validate_r20_duplicate_sentinel_raster(
        field, centers, orientations, metric_window_xywh
    )
    return field


def _r20_zero_key_duplicate_sentinel_delta(split: str) -> np.ndarray:
    """Return a public static vector without consuming any development material."""

    key = bytes(32)
    parameters = _r20_obvious_artifact_duplicate_parameters(split)
    cluster_seed_identity = {
        "split": split,
        "public_nonce": _R20_PUBLIC_NONCES[split],
        "private_role": "duplicate-audit",
        "family": "duplicate-audit",
        "variant_index": 1,
        "parameters": parameters,
        "duplicate_audit_group": "artifact",
    }
    foundation_index = int.from_bytes(
        _hmac_material(
            key,
            _R20_RENDER_SEED_PREFIX,
            cluster_seed_identity,
            _FOUNDATION_ASSIGNMENT_LANE,
        )[:8],
        "big",
    ) % len(_FOUNDATIONS)
    cluster_identity = {
        **cluster_seed_identity,
        "foundation_id": _FOUNDATIONS[foundation_index][0],
    }
    delta_seed = int.from_bytes(
        _hmac_material(
            key, _R20_RENDER_SEED_PREFIX, cluster_identity, _DELTA_LANE
        ),
        "big",
    )
    return _render_r20_duplicate_obvious_short_line_sentinel(
        parameters,
        np.random.default_rng(delta_seed),
        384,
        512,
        (128, 96, 256, 192),
    )


def _render_unsigned_delta(
    family: str,
    parameters: dict[str, Any],
    rng: np.random.Generator,
    height: int,
    width: int,
    metric_window_xywh: tuple[int, int, int, int],
) -> np.ndarray:
    zero = np.zeros((height, width), dtype=np.float32)
    if family == "protocol-zero":
        return zero
    if family == "duplicate-obvious-short-line-sentinel":
        return _render_r20_duplicate_obvious_short_line_sentinel(
            parameters, rng, height, width, metric_window_xywh
        )
    if family == "artifact-speck":
        count = int(parameters["count_in_metric_window"])
        amplitude = float(parameters["amplitude_l"])
        separation = int(parameters["minimum_separation_px"])
        shoulder_fraction = float(parameters["shoulder_fraction"])
        if (
            int(parameters["diameter_px"]) != 1
            or separation < 10
            or not 0.0 <= shoulder_fraction < 1.0
        ):
            raise RuntimeError("r6 hard-core speck parameter drift")
        tier = str(parameters["design_tier"])
        reinforcement_revision = parameters.get(
            "direct_visibility_reinforcement_revision"
        )
        if reinforcement_revision is None:
            expected_shoulder = {
                "clean-candidate": 0.0,
                "warning-candidate": 0.05,
                "clear-reject-candidate": 0.08,
                "dominant-reject-candidate": 0.08,
            }.get(tier)
            if expected_shoulder is None or not math.isclose(
                shoulder_fraction, expected_shoulder, abs_tol=1e-12
            ):
                raise RuntimeError("r6 tier-bound speck shoulder contract drift")
            if tier == "clean-candidate" and not (
                count <= 2 and 0.8 <= amplitude <= 1.4
            ):
                raise RuntimeError("r6 clean-candidate speck contract drift")
            if tier in {
                "clear-reject-candidate",
                "dominant-reject-candidate",
            } and not (count >= 6 and 10.0 <= amplitude <= 12.0):
                raise RuntimeError("r6 strong speck contract drift")
        elif reinforcement_revision == _R18_SPECK_REINFORCEMENT_REVISION:
            encoded_shoulder_l = int(np.rint(amplitude * shoulder_fraction))
            if (
                tier
                not in {"clear-reject-candidate", "dominant-reject-candidate"}
                or not 4 <= count <= 7
                or not 11.2 <= amplitude <= 12.0
                or not 0.42 <= shoulder_fraction <= 0.56
                or separation < 30
                or encoded_shoulder_l < 5
            ):
                raise RuntimeError("r18 direct-visible speck contract drift")
        else:
            raise RuntimeError("unknown speck reinforcement revision")
        centers = _stratified_separated_integer_positions(
            rng,
            count,
            metric_window_xywh,
            margin=1,
            minimum_separation_px=separation,
        )
        field = zero.copy()
        for x, y in centers:
            field[y, x] = np.float32(1.0)
            if shoulder_fraction > 0.0:
                shoulder = np.float32(shoulder_fraction)
                field[y - 1, x] = max(field[y - 1, x], shoulder)
                field[y + 1, x] = max(field[y + 1, x], shoulder)
                field[y, x - 1] = max(field[y, x - 1], shoulder)
                field[y, x + 1] = max(field[y, x + 1], shoulder)
        expected_support = count * (5 if shoulder_fraction > 0.0 else 1)
        if (
            int(np.count_nonzero(field == np.float32(1.0))) != count
            or int(np.count_nonzero(field)) != expected_support
        ):
            raise RuntimeError("r6 speck core/4-neighbour support drift")
        return field * np.float32(amplitude)
    if family == "artifact-microblob":
        count = int(parameters["count_in_metric_window"])
        diameter = int(parameters["diameter_px"])
        support_radius = int(parameters["support_radius_px"])
        separation = int(parameters["minimum_separation_px"])
        if diameter < 4 or support_radius < 2 or separation < 2 * support_radius + 1:
            raise RuntimeError("r6 finite microblob parameter drift")
        yy, xx = np.mgrid[0:height, 0:width]
        field = zero.copy()
        centers = _stratified_separated_integer_positions(
            rng,
            count,
            metric_window_xywh,
            margin=support_radius + 1,
            minimum_separation_px=separation,
        )
        sigma = max(0.75, diameter / 2.355)
        for x, y in centers:
            distance_squared = (xx - x) ** 2 + (yy - y) ** 2
            blob = (
                np.exp(-distance_squared / (2 * sigma**2))
                * (distance_squared <= support_radius**2)
            ).astype(np.float32)
            field = np.maximum(field, blob)
        if int(np.count_nonzero(field == np.float32(1.0))) != count:
            raise RuntimeError("r6 finite microblob center cardinality drift")
        return field * np.float32(parameters["amplitude_l"])
    if family == "artifact-fine-grain":
        yy, xx = np.mgrid[0:height, 0:width]
        if parameters["pattern"] == "fine-band":
            angle, phase = (
                float(rng.uniform(0, math.pi)),
                float(rng.uniform(0, 2 * math.pi)),
            )
            wave = np.sin(
                2
                * math.pi
                * (xx * math.cos(angle) + yy * math.sin(angle))
                / float(parameters["wavelength_px"])
                + phase
            )
            field = _normalize_rms(wave.astype(np.float32), float(parameters["rms_l"]))
            return _retain_metric_support(
                field,
                rng,
                metric_window_xywh,
                float(parameters["support_fraction_in_metric_window"]),
            )
        if parameters["pattern"] == "halftone":
            field = np.sin(math.pi * xx / float(parameters["cell_px"])) * np.sin(
                math.pi * yy / float(parameters["cell_px"])
            )
            return _retain_metric_support(
                field.astype(np.float32) * np.float32(parameters["amplitude_l"]),
                rng,
                metric_window_xywh,
                float(parameters["support_fraction_in_metric_window"]),
            )
        raise RuntimeError("unknown r6 fine-grain pattern")
    if family == "artifact-short-dash":
        count = int(parameters["count_in_metric_window"])
        length = float(parameters["length_px"])
        line_width = int(parameters["width_px"])
        separation = int(parameters["minimum_separation_px"])
        if separation < int(math.ceil(length)) + line_width + 3:
            raise RuntimeError("r6 short-dash separation contract drift")
        centers = _stratified_separated_integer_positions(
            rng,
            count,
            metric_window_xywh,
            margin=int(math.ceil(length / 2)) + line_width + 2,
            minimum_separation_px=separation,
        )
        lines = []
        for x, y in centers:
            angle = float(rng.uniform(0, math.pi))
            dx, dy = math.cos(angle) * length / 2, math.sin(angle) * length / 2
            lines.append((x - dx, y - dy, x + dx, y + dy, line_width))
        return _line_mask(height, width, lines) * np.float32(parameters["amplitude_l"])
    if family == "artifact-parallel-bundle":
        count = int(parameters["pair_count_in_metric_window"])
        length, spacing = (
            float(parameters["length_px"]),
            float(parameters["spacing_px"]),
        )
        line_width = int(parameters["width_px"])
        edge_gap = spacing - line_width
        if not (1.0 <= edge_gap <= length):
            raise RuntimeError("r6 parallel edge-gap contract drift")
        if int(length) % 2 or int(spacing) % 2:
            raise RuntimeError("r6 parallel deterministic integer geometry drift")
        bundle_separation = int(parameters["minimum_bundle_separation_px"])
        if bundle_separation < int(max(length, spacing)) + line_width + 3:
            raise RuntimeError("r6 parallel bundle packing contract drift")
        containment_margin = (
            int(math.ceil(max(length, spacing) / 2 + line_width / 2)) + 2
        )
        centers = _stratified_separated_integer_positions(
            rng,
            count,
            metric_window_xywh,
            margin=containment_margin,
            minimum_separation_px=bundle_separation,
        )
        quadrants = _metric_quadrants(metric_window_xywh)
        lines = []
        fully_contained_pairs = 0
        for pair_index, (x, y) in enumerate(centers):
            angle = 0.0 if int(rng.integers(0, 2)) == 0 else math.pi / 2
            ux, uy, nx, ny = (
                math.cos(angle),
                math.sin(angle),
                -math.sin(angle),
                math.cos(angle),
            )
            pair_lines = []
            for offset in (-spacing / 2, spacing / 2):
                cx, cy = x + nx * offset, y + ny * offset
                pair_lines.append(
                    (
                        cx - ux * length / 2,
                        cy - uy * length / 2,
                        cx + ux * length / 2,
                        cy + uy * length / 2,
                        line_width,
                    )
                )
            first, second = pair_lines
            first_axis = (first[2] - first[0]) * ux + (first[3] - first[1]) * uy
            second_axis = (second[2] - second[0]) * ux + (second[3] - second[1]) * uy
            first_midpoint = ((first[0] + first[2]) / 2, (first[1] + first[3]) / 2)
            second_midpoint = (
                (second[0] + second[2]) / 2,
                (second[1] + second[3]) / 2,
            )
            perpendicular_distance = abs(
                (second_midpoint[0] - first_midpoint[0]) * nx
                + (second_midpoint[1] - first_midpoint[1]) * ny
            )
            axial_offset = abs(
                (second_midpoint[0] - first_midpoint[0]) * ux
                + (second_midpoint[1] - first_midpoint[1]) * uy
            )
            if not (
                math.isclose(first_axis, length, abs_tol=1e-9)
                and math.isclose(second_axis, length, abs_tol=1e-9)
                and math.isclose(perpendicular_distance, spacing, abs_tol=1e-9)
                and math.isclose(axial_offset, 0.0, abs_tol=1e-9)
            ):
                raise RuntimeError(f"r6 parallel pair geometry drift: {pair_index}")
            containing_quadrants = 0
            extent = line_width / 2 + 1
            for left, top, quadrant_width, quadrant_height in quadrants:
                right, bottom = left + quadrant_width, top + quadrant_height
                if all(
                    left <= min(x0, x1) - extent
                    and max(x0, x1) + extent < right
                    and top <= min(y0, y1) - extent
                    and max(y0, y1) + extent < bottom
                    for x0, y0, x1, y1, _ in pair_lines
                ):
                    containing_quadrants += 1
            if containing_quadrants != 1:
                raise RuntimeError(
                    f"r6 parallel pair escaped exact 400% quadrant: {pair_index}"
                )
            fully_contained_pairs += 1
            lines.extend(pair_lines)
        if fully_contained_pairs < 1:
            raise RuntimeError("r6 parallel corpus lacks a quadrant-contained pair")
        return _line_mask(height, width, lines) * np.float32(parameters["amplitude_l"])
    raise RuntimeError(f"unknown family: {family}")


def _artifact_variants(
    split: str,
    *,
    _include_r16_warning_rebalance: bool = True,
    _include_r18_speck_reinforcement: bool = True,
    _schedule_revision_override: str | None = None,
    _artifact_nonce_bases_override: dict[str, int] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    artifact_nonce_bases = (
        _ARTIFACT_NONCE_BASES
        if _artifact_nonce_bases_override is None
        else _artifact_nonce_bases_override
    )
    if split == "calibration":
        nonce_base = artifact_nonce_bases[split]
        grain = [
            {
                "design_tier": "clean-candidate",
                "pattern": "fine-band",
                "wavelength_px": 3.2,
                "rms_l": 0.58,
                "support_fraction_in_metric_window": 0.0010,
            },
            {
                "design_tier": "warning-candidate",
                "pattern": "fine-band",
                "wavelength_px": 7.4,
                "rms_l": 1.30,
                "support_fraction_in_metric_window": 0.35,
            },
            {
                "design_tier": "clear-reject-candidate",
                "pattern": "fine-band",
                "wavelength_px": 4.1,
                "rms_l": 3.20,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "pattern": "fine-band",
                "wavelength_px": 3.0,
                "rms_l": 6.80,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "clean-candidate",
                "pattern": "halftone",
                "cell_px": 9,
                "amplitude_l": 0.90,
                "support_fraction_in_metric_window": 0.0010,
            },
            {
                "design_tier": "warning-candidate",
                "pattern": "halftone",
                "cell_px": 13,
                "amplitude_l": 3.00,
                "support_fraction_in_metric_window": 0.25,
            },
            {
                "design_tier": "clear-reject-candidate",
                "pattern": "fine-band",
                "wavelength_px": 8.8,
                "rms_l": 3.50,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "pattern": "halftone",
                "cell_px": 7,
                "amplitude_l": 10.00,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "clean-candidate",
                "pattern": "fine-band",
                "wavelength_px": 11.0,
                "rms_l": 0.62,
                "support_fraction_in_metric_window": 0.0020,
            },
            {
                "design_tier": "warning-candidate",
                "pattern": "fine-band",
                "wavelength_px": 5.6,
                "rms_l": 1.80,
                "support_fraction_in_metric_window": 0.45,
            },
            {
                "design_tier": "clear-reject-candidate",
                "pattern": "halftone",
                "cell_px": 11,
                "amplitude_l": 6.80,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "pattern": "fine-band",
                "wavelength_px": 4.8,
                "rms_l": 7.20,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "clean-candidate",
                "pattern": "halftone",
                "cell_px": 15,
                "amplitude_l": 1.00,
                "support_fraction_in_metric_window": 0.0015,
            },
            {
                "design_tier": "clear-reject-candidate",
                "pattern": "fine-band",
                "wavelength_px": 12.0,
                "rms_l": 3.80,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "warning-candidate",
                "pattern": "halftone",
                "cell_px": 8,
                "amplitude_l": 3.80,
                "support_fraction_in_metric_window": 0.40,
            },
            {
                "design_tier": "clear-reject-candidate",
                "pattern": "fine-band",
                "wavelength_px": 6.7,
                "rms_l": 4.20,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "clean-candidate",
                "pattern": "fine-band",
                "wavelength_px": 9.6,
                "rms_l": 0.65,
                "support_fraction_in_metric_window": 0.0010,
            },
            {
                "design_tier": "clear-reject-candidate",
                "pattern": "halftone",
                "cell_px": 10,
                "amplitude_l": 7.50,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "pattern": "fine-band",
                "wavelength_px": 8.0,
                "rms_l": 7.80,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "clear-reject-candidate",
                "pattern": "fine-band",
                "wavelength_px": 11.6,
                "rms_l": 4.50,
                "support_fraction_in_metric_window": 1.0,
            },
        ]
        speck = [
            {
                "design_tier": "clean-candidate",
                "diameter_px": 1,
                "amplitude_l": 0.8,
                "count_in_metric_window": 1,
                "shoulder_fraction": 0.0,
                "minimum_separation_px": 12,
            },
            {
                "design_tier": "warning-candidate",
                "diameter_px": 1,
                "amplitude_l": 4.5,
                "count_in_metric_window": 3,
                "shoulder_fraction": 0.05,
                "minimum_separation_px": 12,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 10.0,
                "count_in_metric_window": 6,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 12,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 12.0,
                "count_in_metric_window": 16,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 12,
            },
            {
                "design_tier": "clean-candidate",
                "diameter_px": 1,
                "amplitude_l": 1.0,
                "count_in_metric_window": 2,
                "shoulder_fraction": 0.0,
                "minimum_separation_px": 14,
            },
            {
                "design_tier": "warning-candidate",
                "diameter_px": 1,
                "amplitude_l": 5.2,
                "count_in_metric_window": 4,
                "shoulder_fraction": 0.05,
                "minimum_separation_px": 14,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 10.4,
                "count_in_metric_window": 7,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 14,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 11.8,
                "count_in_metric_window": 18,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 14,
            },
            {
                "design_tier": "clean-candidate",
                "diameter_px": 1,
                "amplitude_l": 1.2,
                "count_in_metric_window": 1,
                "shoulder_fraction": 0.0,
                "minimum_separation_px": 16,
            },
            {
                "design_tier": "warning-candidate",
                "diameter_px": 1,
                "amplitude_l": 6.2,
                "count_in_metric_window": 5,
                "shoulder_fraction": 0.05,
                "minimum_separation_px": 16,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 10.8,
                "count_in_metric_window": 8,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 16,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 12.0,
                "count_in_metric_window": 14,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 16,
            },
            {
                "design_tier": "clean-candidate",
                "diameter_px": 1,
                "amplitude_l": 1.4,
                "count_in_metric_window": 2,
                "shoulder_fraction": 0.0,
                "minimum_separation_px": 18,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 11.0,
                "count_in_metric_window": 10,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 18,
            },
            {
                "design_tier": "warning-candidate",
                "diameter_px": 1,
                "amplitude_l": 7.2,
                "count_in_metric_window": 4,
                "shoulder_fraction": 0.05,
                "minimum_separation_px": 18,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 11.4,
                "count_in_metric_window": 12,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 18,
            },
            {
                "design_tier": "clean-candidate",
                "diameter_px": 1,
                "amplitude_l": 0.9,
                "count_in_metric_window": 1,
                "shoulder_fraction": 0.0,
                "minimum_separation_px": 20,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 10.2,
                "count_in_metric_window": 6,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 20,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 11.6,
                "count_in_metric_window": 12,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 20,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 11.8,
                "count_in_metric_window": 9,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 20,
            },
        ]
        microblob = [
            {
                "design_tier": "clean-candidate",
                "diameter_px": 4,
                "amplitude_l": 0.8,
                "count_in_metric_window": 1,
                "support_radius_px": 4,
                "minimum_separation_px": 12,
            },
            {
                "design_tier": "warning-candidate",
                "diameter_px": 6,
                "amplitude_l": 4.0,
                "count_in_metric_window": 3,
                "support_radius_px": 5,
                "minimum_separation_px": 14,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 8,
                "amplitude_l": 9.0,
                "count_in_metric_window": 6,
                "support_radius_px": 7,
                "minimum_separation_px": 18,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "diameter_px": 14,
                "amplitude_l": 12.0,
                "count_in_metric_window": 14,
                "support_radius_px": 12,
                "minimum_separation_px": 28,
            },
            {
                "design_tier": "clean-candidate",
                "diameter_px": 5,
                "amplitude_l": 1.0,
                "count_in_metric_window": 2,
                "support_radius_px": 5,
                "minimum_separation_px": 14,
            },
            {
                "design_tier": "warning-candidate",
                "diameter_px": 7,
                "amplitude_l": 5.0,
                "count_in_metric_window": 4,
                "support_radius_px": 6,
                "minimum_separation_px": 16,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 9,
                "amplitude_l": 9.5,
                "count_in_metric_window": 7,
                "support_radius_px": 8,
                "minimum_separation_px": 20,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "diameter_px": 12,
                "amplitude_l": 11.5,
                "count_in_metric_window": 16,
                "support_radius_px": 10,
                "minimum_separation_px": 24,
            },
            {
                "design_tier": "clean-candidate",
                "diameter_px": 6,
                "amplitude_l": 1.2,
                "count_in_metric_window": 1,
                "support_radius_px": 5,
                "minimum_separation_px": 14,
            },
            {
                "design_tier": "warning-candidate",
                "diameter_px": 8,
                "amplitude_l": 5.8,
                "count_in_metric_window": 5,
                "support_radius_px": 7,
                "minimum_separation_px": 18,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 10,
                "amplitude_l": 10.0,
                "count_in_metric_window": 8,
                "support_radius_px": 8,
                "minimum_separation_px": 20,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "diameter_px": 16,
                "amplitude_l": 12.0,
                "count_in_metric_window": 12,
                "support_radius_px": 13,
                "minimum_separation_px": 30,
            },
            {
                "design_tier": "clean-candidate",
                "diameter_px": 4,
                "amplitude_l": 1.4,
                "count_in_metric_window": 2,
                "support_radius_px": 4,
                "minimum_separation_px": 12,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 11,
                "amplitude_l": 10.4,
                "count_in_metric_window": 9,
                "support_radius_px": 9,
                "minimum_separation_px": 22,
            },
            {
                "design_tier": "warning-candidate",
                "diameter_px": 5,
                "amplitude_l": 6.2,
                "count_in_metric_window": 4,
                "support_radius_px": 5,
                "minimum_separation_px": 14,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 13,
                "amplitude_l": 10.8,
                "count_in_metric_window": 10,
                "support_radius_px": 11,
                "minimum_separation_px": 26,
            },
            {
                "design_tier": "clean-candidate",
                "diameter_px": 5,
                "amplitude_l": 0.9,
                "count_in_metric_window": 1,
                "support_radius_px": 5,
                "minimum_separation_px": 14,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 7,
                "amplitude_l": 9.2,
                "count_in_metric_window": 6,
                "support_radius_px": 6,
                "minimum_separation_px": 16,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "diameter_px": 15,
                "amplitude_l": 11.8,
                "count_in_metric_window": 14,
                "support_radius_px": 12,
                "minimum_separation_px": 28,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 12,
                "amplitude_l": 11.0,
                "count_in_metric_window": 8,
                "support_radius_px": 10,
                "minimum_separation_px": 24,
            },
        ]
        short_dash = [
            {
                "design_tier": "clean-candidate",
                "length_px": 4,
                "width_px": 1,
                "amplitude_l": 0.8,
                "count_in_metric_window": 1,
                "minimum_separation_px": 8,
            },
            {
                "design_tier": "warning-candidate",
                "length_px": 7,
                "width_px": 1,
                "amplitude_l": 4.0,
                "count_in_metric_window": 2,
                "minimum_separation_px": 12,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 12,
                "width_px": 2,
                "amplitude_l": 9.0,
                "count_in_metric_window": 5,
                "minimum_separation_px": 18,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "length_px": 24,
                "width_px": 3,
                "amplitude_l": 12.0,
                "count_in_metric_window": 12,
                "minimum_separation_px": 32,
            },
            {
                "design_tier": "clean-candidate",
                "length_px": 5,
                "width_px": 1,
                "amplitude_l": 1.0,
                "count_in_metric_window": 2,
                "minimum_separation_px": 10,
            },
            {
                "design_tier": "warning-candidate",
                "length_px": 8,
                "width_px": 1,
                "amplitude_l": 4.8,
                "count_in_metric_window": 3,
                "minimum_separation_px": 13,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 14,
                "width_px": 2,
                "amplitude_l": 9.5,
                "count_in_metric_window": 6,
                "minimum_separation_px": 20,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "length_px": 22,
                "width_px": 3,
                "amplitude_l": 11.5,
                "count_in_metric_window": 14,
                "minimum_separation_px": 30,
            },
            {
                "design_tier": "clean-candidate",
                "length_px": 6,
                "width_px": 1,
                "amplitude_l": 1.2,
                "count_in_metric_window": 1,
                "minimum_separation_px": 11,
            },
            {
                "design_tier": "warning-candidate",
                "length_px": 10,
                "width_px": 2,
                "amplitude_l": 5.5,
                "count_in_metric_window": 4,
                "minimum_separation_px": 16,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 16,
                "width_px": 2,
                "amplitude_l": 10.0,
                "count_in_metric_window": 7,
                "minimum_separation_px": 22,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "length_px": 26,
                "width_px": 3,
                "amplitude_l": 12.0,
                "count_in_metric_window": 10,
                "minimum_separation_px": 34,
            },
            {
                "design_tier": "clean-candidate",
                "length_px": 7,
                "width_px": 1,
                "amplitude_l": 1.4,
                "count_in_metric_window": 2,
                "minimum_separation_px": 12,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 18,
                "width_px": 2,
                "amplitude_l": 10.5,
                "count_in_metric_window": 8,
                "minimum_separation_px": 24,
            },
            {
                "design_tier": "warning-candidate",
                "length_px": 6,
                "width_px": 1,
                "amplitude_l": 6.0,
                "count_in_metric_window": 3,
                "minimum_separation_px": 11,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 20,
                "width_px": 3,
                "amplitude_l": 11.0,
                "count_in_metric_window": 9,
                "minimum_separation_px": 26,
            },
            {
                "design_tier": "clean-candidate",
                "length_px": 5,
                "width_px": 1,
                "amplitude_l": 0.9,
                "count_in_metric_window": 1,
                "minimum_separation_px": 10,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 10,
                "width_px": 2,
                "amplitude_l": 9.2,
                "count_in_metric_window": 5,
                "minimum_separation_px": 16,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "length_px": 20,
                "width_px": 3,
                "amplitude_l": 11.8,
                "count_in_metric_window": 12,
                "minimum_separation_px": 28,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 14,
                "width_px": 2,
                "amplitude_l": 10.8,
                "count_in_metric_window": 6,
                "minimum_separation_px": 20,
            },
        ]
        parallel = [
            {
                "design_tier": "clean-candidate",
                "length_px": 8,
                "width_px": 1,
                "spacing_px": 2,
                "amplitude_l": 0.8,
                "pair_count_in_metric_window": 1,
                "minimum_bundle_separation_px": 14,
            },
            {
                "design_tier": "warning-candidate",
                "length_px": 10,
                "width_px": 1,
                "spacing_px": 4,
                "amplitude_l": 4.5,
                "pair_count_in_metric_window": 1,
                "minimum_bundle_separation_px": 16,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 14,
                "width_px": 2,
                "spacing_px": 4,
                "amplitude_l": 10.0,
                "pair_count_in_metric_window": 3,
                "minimum_bundle_separation_px": 20,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "length_px": 26,
                "width_px": 3,
                "spacing_px": 8,
                "amplitude_l": 12.0,
                "pair_count_in_metric_window": 9,
                "minimum_bundle_separation_px": 34,
            },
            {
                "design_tier": "clean-candidate",
                "length_px": 10,
                "width_px": 1,
                "spacing_px": 2,
                "amplitude_l": 1.0,
                "pair_count_in_metric_window": 1,
                "minimum_bundle_separation_px": 16,
            },
            {
                "design_tier": "warning-candidate",
                "length_px": 12,
                "width_px": 2,
                "spacing_px": 4,
                "amplitude_l": 5.0,
                "pair_count_in_metric_window": 2,
                "minimum_bundle_separation_px": 18,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 16,
                "width_px": 2,
                "spacing_px": 6,
                "amplitude_l": 10.4,
                "pair_count_in_metric_window": 4,
                "minimum_bundle_separation_px": 22,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "length_px": 24,
                "width_px": 3,
                "spacing_px": 10,
                "amplitude_l": 11.7,
                "pair_count_in_metric_window": 10,
                "minimum_bundle_separation_px": 32,
            },
            {
                "design_tier": "clean-candidate",
                "length_px": 12,
                "width_px": 1,
                "spacing_px": 4,
                "amplitude_l": 1.2,
                "pair_count_in_metric_window": 1,
                "minimum_bundle_separation_px": 18,
            },
            {
                "design_tier": "warning-candidate",
                "length_px": 14,
                "width_px": 2,
                "spacing_px": 6,
                "amplitude_l": 6.0,
                "pair_count_in_metric_window": 2,
                "minimum_bundle_separation_px": 20,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 18,
                "width_px": 2,
                "spacing_px": 8,
                "amplitude_l": 10.8,
                "pair_count_in_metric_window": 5,
                "minimum_bundle_separation_px": 24,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "length_px": 28,
                "width_px": 3,
                "spacing_px": 12,
                "amplitude_l": 12.0,
                "pair_count_in_metric_window": 8,
                "minimum_bundle_separation_px": 36,
            },
            {
                "design_tier": "clean-candidate",
                "length_px": 8,
                "width_px": 1,
                "spacing_px": 2,
                "amplitude_l": 1.4,
                "pair_count_in_metric_window": 1,
                "minimum_bundle_separation_px": 14,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 20,
                "width_px": 3,
                "spacing_px": 6,
                "amplitude_l": 11.0,
                "pair_count_in_metric_window": 6,
                "minimum_bundle_separation_px": 26,
            },
            {
                "design_tier": "warning-candidate",
                "length_px": 8,
                "width_px": 1,
                "spacing_px": 4,
                "amplitude_l": 6.5,
                "pair_count_in_metric_window": 2,
                "minimum_bundle_separation_px": 14,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 22,
                "width_px": 2,
                "spacing_px": 10,
                "amplitude_l": 11.2,
                "pair_count_in_metric_window": 5,
                "minimum_bundle_separation_px": 28,
            },
            {
                "design_tier": "clean-candidate",
                "length_px": 10,
                "width_px": 1,
                "spacing_px": 2,
                "amplitude_l": 0.9,
                "pair_count_in_metric_window": 1,
                "minimum_bundle_separation_px": 16,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 12,
                "width_px": 2,
                "spacing_px": 4,
                "amplitude_l": 10.2,
                "pair_count_in_metric_window": 3,
                "minimum_bundle_separation_px": 18,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "length_px": 22,
                "width_px": 3,
                "spacing_px": 8,
                "amplitude_l": 11.8,
                "pair_count_in_metric_window": 9,
                "minimum_bundle_separation_px": 30,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 16,
                "width_px": 2,
                "spacing_px": 6,
                "amplitude_l": 11.5,
                "pair_count_in_metric_window": 4,
                "minimum_bundle_separation_px": 22,
            },
        ]
    elif split == "holdout":
        nonce_base = artifact_nonce_bases[split]
        grain = [
            {
                "design_tier": "clear-reject-candidate",
                "pattern": "halftone",
                "cell_px": 12,
                "amplitude_l": 7.10,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "clean-candidate",
                "pattern": "fine-band",
                "wavelength_px": 3.4,
                "rms_l": 0.60,
                "support_fraction_in_metric_window": 0.0012,
            },
            {
                "design_tier": "warning-candidate",
                "pattern": "fine-band",
                "wavelength_px": 7.8,
                "rms_l": 1.45,
                "support_fraction_in_metric_window": 0.30,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "pattern": "fine-band",
                "wavelength_px": 3.3,
                "rms_l": 7.00,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "clear-reject-candidate",
                "pattern": "fine-band",
                "wavelength_px": 4.5,
                "rms_l": 3.35,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "clean-candidate",
                "pattern": "halftone",
                "cell_px": 10,
                "amplitude_l": 0.95,
                "support_fraction_in_metric_window": 0.0010,
            },
            {
                "design_tier": "warning-candidate",
                "pattern": "halftone",
                "cell_px": 14,
                "amplitude_l": 3.20,
                "support_fraction_in_metric_window": 0.28,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "pattern": "halftone",
                "cell_px": 8,
                "amplitude_l": 10.40,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "clear-reject-candidate",
                "pattern": "fine-band",
                "wavelength_px": 9.2,
                "rms_l": 3.65,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "clean-candidate",
                "pattern": "fine-band",
                "wavelength_px": 11.6,
                "rms_l": 0.64,
                "support_fraction_in_metric_window": 0.0018,
            },
            {
                "design_tier": "warning-candidate",
                "pattern": "fine-band",
                "wavelength_px": 6.0,
                "rms_l": 1.95,
                "support_fraction_in_metric_window": 0.42,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "pattern": "fine-band",
                "wavelength_px": 5.1,
                "rms_l": 7.40,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "clear-reject-candidate",
                "pattern": "halftone",
                "cell_px": 9,
                "amplitude_l": 7.60,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "clean-candidate",
                "pattern": "halftone",
                "cell_px": 16,
                "amplitude_l": 1.05,
                "support_fraction_in_metric_window": 0.0014,
            },
            {
                "design_tier": "clear-reject-candidate",
                "pattern": "fine-band",
                "wavelength_px": 11.4,
                "rms_l": 4.00,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "warning-candidate",
                "pattern": "halftone",
                "cell_px": 9,
                "amplitude_l": 4.00,
                "support_fraction_in_metric_window": 0.38,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "pattern": "fine-band",
                "wavelength_px": 8.4,
                "rms_l": 8.00,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "clean-candidate",
                "pattern": "fine-band",
                "wavelength_px": 10.2,
                "rms_l": 0.68,
                "support_fraction_in_metric_window": 0.0010,
            },
            {
                "design_tier": "clear-reject-candidate",
                "pattern": "fine-band",
                "wavelength_px": 7.1,
                "rms_l": 4.35,
                "support_fraction_in_metric_window": 1.0,
            },
            {
                "design_tier": "clear-reject-candidate",
                "pattern": "fine-band",
                "wavelength_px": 11.8,
                "rms_l": 4.70,
                "support_fraction_in_metric_window": 1.0,
            },
        ]
        speck = [
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 10.3,
                "count_in_metric_window": 7,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 13,
            },
            {
                "design_tier": "clean-candidate",
                "diameter_px": 1,
                "amplitude_l": 0.9,
                "count_in_metric_window": 1,
                "shoulder_fraction": 0.0,
                "minimum_separation_px": 13,
            },
            {
                "design_tier": "warning-candidate",
                "diameter_px": 1,
                "amplitude_l": 4.8,
                "count_in_metric_window": 3,
                "shoulder_fraction": 0.05,
                "minimum_separation_px": 13,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 11.9,
                "count_in_metric_window": 17,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 13,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 10.6,
                "count_in_metric_window": 8,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 15,
            },
            {
                "design_tier": "clean-candidate",
                "diameter_px": 1,
                "amplitude_l": 1.1,
                "count_in_metric_window": 2,
                "shoulder_fraction": 0.0,
                "minimum_separation_px": 15,
            },
            {
                "design_tier": "warning-candidate",
                "diameter_px": 1,
                "amplitude_l": 5.5,
                "count_in_metric_window": 4,
                "shoulder_fraction": 0.05,
                "minimum_separation_px": 15,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 12.0,
                "count_in_metric_window": 15,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 15,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 11.0,
                "count_in_metric_window": 9,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 17,
            },
            {
                "design_tier": "clean-candidate",
                "diameter_px": 1,
                "amplitude_l": 1.3,
                "count_in_metric_window": 1,
                "shoulder_fraction": 0.0,
                "minimum_separation_px": 17,
            },
            {
                "design_tier": "warning-candidate",
                "diameter_px": 1,
                "amplitude_l": 6.5,
                "count_in_metric_window": 5,
                "shoulder_fraction": 0.05,
                "minimum_separation_px": 17,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 11.7,
                "count_in_metric_window": 13,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 17,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 11.3,
                "count_in_metric_window": 11,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 19,
            },
            {
                "design_tier": "clean-candidate",
                "diameter_px": 1,
                "amplitude_l": 1.4,
                "count_in_metric_window": 2,
                "shoulder_fraction": 0.0,
                "minimum_separation_px": 19,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 10.1,
                "count_in_metric_window": 6,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 19,
            },
            {
                "design_tier": "warning-candidate",
                "diameter_px": 1,
                "amplitude_l": 7.0,
                "count_in_metric_window": 4,
                "shoulder_fraction": 0.05,
                "minimum_separation_px": 19,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 11.8,
                "count_in_metric_window": 12,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 21,
            },
            {
                "design_tier": "clean-candidate",
                "diameter_px": 1,
                "amplitude_l": 0.8,
                "count_in_metric_window": 1,
                "shoulder_fraction": 0.0,
                "minimum_separation_px": 21,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 11.6,
                "count_in_metric_window": 10,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 21,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 11.9,
                "count_in_metric_window": 8,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 21,
            },
        ]
        microblob = [
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 9,
                "amplitude_l": 9.3,
                "count_in_metric_window": 7,
                "support_radius_px": 8,
                "minimum_separation_px": 20,
            },
            {
                "design_tier": "clean-candidate",
                "diameter_px": 4,
                "amplitude_l": 0.9,
                "count_in_metric_window": 1,
                "support_radius_px": 4,
                "minimum_separation_px": 12,
            },
            {
                "design_tier": "warning-candidate",
                "diameter_px": 6,
                "amplitude_l": 4.3,
                "count_in_metric_window": 3,
                "support_radius_px": 5,
                "minimum_separation_px": 14,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "diameter_px": 15,
                "amplitude_l": 11.9,
                "count_in_metric_window": 15,
                "support_radius_px": 12,
                "minimum_separation_px": 28,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 8,
                "amplitude_l": 9.7,
                "count_in_metric_window": 6,
                "support_radius_px": 7,
                "minimum_separation_px": 18,
            },
            {
                "design_tier": "clean-candidate",
                "diameter_px": 5,
                "amplitude_l": 1.1,
                "count_in_metric_window": 2,
                "support_radius_px": 5,
                "minimum_separation_px": 14,
            },
            {
                "design_tier": "warning-candidate",
                "diameter_px": 7,
                "amplitude_l": 5.2,
                "count_in_metric_window": 4,
                "support_radius_px": 6,
                "minimum_separation_px": 16,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "diameter_px": 13,
                "amplitude_l": 11.6,
                "count_in_metric_window": 16,
                "support_radius_px": 11,
                "minimum_separation_px": 26,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 11,
                "amplitude_l": 10.2,
                "count_in_metric_window": 9,
                "support_radius_px": 9,
                "minimum_separation_px": 22,
            },
            {
                "design_tier": "clean-candidate",
                "diameter_px": 6,
                "amplitude_l": 1.3,
                "count_in_metric_window": 1,
                "support_radius_px": 5,
                "minimum_separation_px": 14,
            },
            {
                "design_tier": "warning-candidate",
                "diameter_px": 8,
                "amplitude_l": 6.0,
                "count_in_metric_window": 5,
                "support_radius_px": 7,
                "minimum_separation_px": 18,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "diameter_px": 16,
                "amplitude_l": 12.0,
                "count_in_metric_window": 13,
                "support_radius_px": 13,
                "minimum_separation_px": 30,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 12,
                "amplitude_l": 10.6,
                "count_in_metric_window": 10,
                "support_radius_px": 10,
                "minimum_separation_px": 24,
            },
            {
                "design_tier": "clean-candidate",
                "diameter_px": 4,
                "amplitude_l": 1.4,
                "count_in_metric_window": 2,
                "support_radius_px": 4,
                "minimum_separation_px": 12,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 7,
                "amplitude_l": 9.1,
                "count_in_metric_window": 6,
                "support_radius_px": 6,
                "minimum_separation_px": 16,
            },
            {
                "design_tier": "warning-candidate",
                "diameter_px": 5,
                "amplitude_l": 6.4,
                "count_in_metric_window": 4,
                "support_radius_px": 5,
                "minimum_separation_px": 14,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "diameter_px": 14,
                "amplitude_l": 11.8,
                "count_in_metric_window": 14,
                "support_radius_px": 12,
                "minimum_separation_px": 28,
            },
            {
                "design_tier": "clean-candidate",
                "diameter_px": 5,
                "amplitude_l": 0.8,
                "count_in_metric_window": 1,
                "support_radius_px": 5,
                "minimum_separation_px": 14,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 13,
                "amplitude_l": 11.0,
                "count_in_metric_window": 8,
                "support_radius_px": 11,
                "minimum_separation_px": 26,
            },
            {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 10,
                "amplitude_l": 10.8,
                "count_in_metric_window": 8,
                "support_radius_px": 8,
                "minimum_separation_px": 20,
            },
        ]
        short_dash = [
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 13,
                "width_px": 2,
                "amplitude_l": 9.3,
                "count_in_metric_window": 5,
                "minimum_separation_px": 19,
            },
            {
                "design_tier": "clean-candidate",
                "length_px": 4,
                "width_px": 1,
                "amplitude_l": 0.9,
                "count_in_metric_window": 1,
                "minimum_separation_px": 8,
            },
            {
                "design_tier": "warning-candidate",
                "length_px": 7,
                "width_px": 1,
                "amplitude_l": 4.3,
                "count_in_metric_window": 2,
                "minimum_separation_px": 12,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "length_px": 25,
                "width_px": 3,
                "amplitude_l": 11.9,
                "count_in_metric_window": 13,
                "minimum_separation_px": 33,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 15,
                "width_px": 2,
                "amplitude_l": 9.7,
                "count_in_metric_window": 6,
                "minimum_separation_px": 21,
            },
            {
                "design_tier": "clean-candidate",
                "length_px": 5,
                "width_px": 1,
                "amplitude_l": 1.1,
                "count_in_metric_window": 2,
                "minimum_separation_px": 10,
            },
            {
                "design_tier": "warning-candidate",
                "length_px": 9,
                "width_px": 1,
                "amplitude_l": 5.0,
                "count_in_metric_window": 3,
                "minimum_separation_px": 14,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "length_px": 23,
                "width_px": 3,
                "amplitude_l": 11.6,
                "count_in_metric_window": 14,
                "minimum_separation_px": 31,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 17,
                "width_px": 2,
                "amplitude_l": 10.2,
                "count_in_metric_window": 7,
                "minimum_separation_px": 23,
            },
            {
                "design_tier": "clean-candidate",
                "length_px": 6,
                "width_px": 1,
                "amplitude_l": 1.3,
                "count_in_metric_window": 1,
                "minimum_separation_px": 11,
            },
            {
                "design_tier": "warning-candidate",
                "length_px": 11,
                "width_px": 2,
                "amplitude_l": 5.8,
                "count_in_metric_window": 4,
                "minimum_separation_px": 17,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "length_px": 27,
                "width_px": 3,
                "amplitude_l": 12.0,
                "count_in_metric_window": 10,
                "minimum_separation_px": 35,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 19,
                "width_px": 2,
                "amplitude_l": 10.7,
                "count_in_metric_window": 8,
                "minimum_separation_px": 25,
            },
            {
                "design_tier": "clean-candidate",
                "length_px": 7,
                "width_px": 1,
                "amplitude_l": 1.4,
                "count_in_metric_window": 2,
                "minimum_separation_px": 12,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 11,
                "width_px": 2,
                "amplitude_l": 9.1,
                "count_in_metric_window": 5,
                "minimum_separation_px": 17,
            },
            {
                "design_tier": "warning-candidate",
                "length_px": 6,
                "width_px": 1,
                "amplitude_l": 6.2,
                "count_in_metric_window": 3,
                "minimum_separation_px": 11,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "length_px": 21,
                "width_px": 3,
                "amplitude_l": 11.8,
                "count_in_metric_window": 12,
                "minimum_separation_px": 29,
            },
            {
                "design_tier": "clean-candidate",
                "length_px": 5,
                "width_px": 1,
                "amplitude_l": 0.8,
                "count_in_metric_window": 1,
                "minimum_separation_px": 10,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 21,
                "width_px": 3,
                "amplitude_l": 11.2,
                "count_in_metric_window": 9,
                "minimum_separation_px": 27,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 15,
                "width_px": 2,
                "amplitude_l": 10.9,
                "count_in_metric_window": 6,
                "minimum_separation_px": 21,
            },
        ]
        parallel = [
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 16,
                "width_px": 2,
                "spacing_px": 6,
                "amplitude_l": 10.2,
                "pair_count_in_metric_window": 4,
                "minimum_bundle_separation_px": 22,
            },
            {
                "design_tier": "clean-candidate",
                "length_px": 8,
                "width_px": 1,
                "spacing_px": 2,
                "amplitude_l": 0.9,
                "pair_count_in_metric_window": 1,
                "minimum_bundle_separation_px": 14,
            },
            {
                "design_tier": "warning-candidate",
                "length_px": 10,
                "width_px": 1,
                "spacing_px": 4,
                "amplitude_l": 4.8,
                "pair_count_in_metric_window": 1,
                "minimum_bundle_separation_px": 16,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "length_px": 26,
                "width_px": 3,
                "spacing_px": 10,
                "amplitude_l": 11.9,
                "pair_count_in_metric_window": 9,
                "minimum_bundle_separation_px": 34,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 14,
                "width_px": 2,
                "spacing_px": 4,
                "amplitude_l": 10.0,
                "pair_count_in_metric_window": 3,
                "minimum_bundle_separation_px": 20,
            },
            {
                "design_tier": "clean-candidate",
                "length_px": 10,
                "width_px": 1,
                "spacing_px": 2,
                "amplitude_l": 1.1,
                "pair_count_in_metric_window": 1,
                "minimum_bundle_separation_px": 16,
            },
            {
                "design_tier": "warning-candidate",
                "length_px": 12,
                "width_px": 2,
                "spacing_px": 4,
                "amplitude_l": 5.3,
                "pair_count_in_metric_window": 2,
                "minimum_bundle_separation_px": 18,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "length_px": 24,
                "width_px": 3,
                "spacing_px": 8,
                "amplitude_l": 11.7,
                "pair_count_in_metric_window": 10,
                "minimum_bundle_separation_px": 32,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 20,
                "width_px": 3,
                "spacing_px": 6,
                "amplitude_l": 10.8,
                "pair_count_in_metric_window": 6,
                "minimum_bundle_separation_px": 26,
            },
            {
                "design_tier": "clean-candidate",
                "length_px": 12,
                "width_px": 1,
                "spacing_px": 4,
                "amplitude_l": 1.3,
                "pair_count_in_metric_window": 1,
                "minimum_bundle_separation_px": 18,
            },
            {
                "design_tier": "warning-candidate",
                "length_px": 14,
                "width_px": 2,
                "spacing_px": 6,
                "amplitude_l": 6.2,
                "pair_count_in_metric_window": 2,
                "minimum_bundle_separation_px": 20,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "length_px": 28,
                "width_px": 3,
                "spacing_px": 12,
                "amplitude_l": 12.0,
                "pair_count_in_metric_window": 8,
                "minimum_bundle_separation_px": 36,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 18,
                "width_px": 2,
                "spacing_px": 8,
                "amplitude_l": 11.0,
                "pair_count_in_metric_window": 5,
                "minimum_bundle_separation_px": 24,
            },
            {
                "design_tier": "clean-candidate",
                "length_px": 8,
                "width_px": 1,
                "spacing_px": 2,
                "amplitude_l": 1.4,
                "pair_count_in_metric_window": 1,
                "minimum_bundle_separation_px": 14,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 12,
                "width_px": 2,
                "spacing_px": 4,
                "amplitude_l": 10.1,
                "pair_count_in_metric_window": 3,
                "minimum_bundle_separation_px": 18,
            },
            {
                "design_tier": "warning-candidate",
                "length_px": 8,
                "width_px": 1,
                "spacing_px": 4,
                "amplitude_l": 6.7,
                "pair_count_in_metric_window": 2,
                "minimum_bundle_separation_px": 14,
            },
            {
                "design_tier": "dominant-reject-candidate",
                "length_px": 22,
                "width_px": 3,
                "spacing_px": 8,
                "amplitude_l": 11.8,
                "pair_count_in_metric_window": 9,
                "minimum_bundle_separation_px": 30,
            },
            {
                "design_tier": "clean-candidate",
                "length_px": 10,
                "width_px": 1,
                "spacing_px": 2,
                "amplitude_l": 0.8,
                "pair_count_in_metric_window": 1,
                "minimum_bundle_separation_px": 16,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 22,
                "width_px": 2,
                "spacing_px": 10,
                "amplitude_l": 11.4,
                "pair_count_in_metric_window": 5,
                "minimum_bundle_separation_px": 28,
            },
            {
                "design_tier": "clear-reject-candidate",
                "length_px": 16,
                "width_px": 2,
                "spacing_px": 6,
                "amplitude_l": 11.6,
                "pair_count_in_metric_window": 4,
                "minimum_bundle_separation_px": 22,
            },
        ]
    else:
        raise ValueError("invalid split")

    result = {
        "artifact-fine-grain": grain,
        "artifact-speck": speck,
        "artifact-microblob": microblob,
        "artifact-short-dash": short_dash,
        "artifact-parallel-bundle": parallel,
    }
    rotations = {
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
    }[split]
    for family, offset in rotations.items():
        variants = result[family]
        permuted: list[dict[str, Any] | None] = [None] * len(variants)
        for residue in range(3):
            indices = list(range(residue, len(variants), 3))
            shift = offset % len(indices)
            sources = indices[shift:] + indices[:shift]
            for target, source in zip(indices, sources, strict=True):
                permuted[target] = variants[source]
        if any(item is None for item in permuted):
            raise RuntimeError(f"r6 residue-preserving permutation drift: {family}")
        result[family] = [item for item in permuted if item is not None]

    warning_anchors = _R15_WARNING_ACCEPTANCE_ANCHORS["splits"][split]
    if set(warning_anchors) != {
        "artifact-speck",
        "artifact-microblob",
        "artifact-short-dash",
        "artifact-parallel-bundle",
    }:
        raise RuntimeError(f"r15 predecessor warning-anchor family coverage drift: {split}")
    for family, replacements in warning_anchors.items():
        if len(replacements) != 4:
            raise RuntimeError(
                f"r15 predecessor warning-anchor count drift: {split}/{family}"
            )
        for index, replacement in replacements.items():
            if result[family][index]["design_tier"] != "warning-candidate":
                raise RuntimeError(
                    f"r15 predecessor warning anchor replaced a non-warning tier: "
                    f"{split}/{family}/{index}"
                )
            result[family][index] = dict(replacement)

    if split == "calibration":
        replacements = _CALIBRATION_MICROBLOB_CLEAR_REJECT_ANCHORS["entries"]
        if len(replacements) != 7:
            raise RuntimeError("r15 calibration microblob clear-anchor count drift")
        for index, replacement in replacements.items():
            if (
                result["artifact-microblob"][index]["design_tier"]
                != "clear-reject-candidate"
            ):
                raise RuntimeError(
                    f"r15 calibration microblob anchor replaced a non-clear tier: "
                    f"{index}"
                )
            result["artifact-microblob"][index] = dict(replacement)

    speck_reject_counts = {
        "calibration": {
            "clear-reject-candidate": (32, 36, 40, 44, 48, 52, 56),
            "dominant-reject-candidate": (64, 72, 80, 88),
        },
        "holdout": {
            "clear-reject-candidate": (34, 38, 42, 46, 50, 54, 58),
            "dominant-reject-candidate": (68, 76, 84, 90),
        },
    }[split]
    speck_reject_tier_indices: Counter[str] = Counter()
    for parameters in result["artifact-speck"]:
        tier = str(parameters["design_tier"])
        tier_counts = speck_reject_counts.get(tier)
        if tier_counts is None:
            continue
        tier_index = speck_reject_tier_indices[tier]
        if tier_index >= len(tier_counts):
            raise RuntimeError(f"r15 speck reject-tier count overflow: {split}/{tier}")
        parameters["count_in_metric_window"] = tier_counts[tier_index]
        parameters["minimum_separation_px"] = 10
        speck_reject_tier_indices[tier] += 1
    for tier, expected_counts in speck_reject_counts.items():
        actual_counts = tuple(
            int(parameters["count_in_metric_window"])
            for parameters in result["artifact-speck"]
            if parameters["design_tier"] == tier
        )
        if actual_counts != expected_counts:
            raise RuntimeError(f"r15 speck reject-tier schedule drift: {split}/{tier}")

    if _include_r16_warning_rebalance:
        warning_anchors = _WARNING_ACCEPTANCE_ANCHORS["splits"][split]
        conversion_sources = _R16_WARNING_CONVERSION_SOURCES[split]
        if set(warning_anchors) != set(conversion_sources) or set(
            warning_anchors
        ) != {
            "artifact-speck",
            "artifact-microblob",
            "artifact-short-dash",
            "artifact-parallel-bundle",
        }:
            raise RuntimeError(f"r16 warning-rebalance family coverage drift: {split}")
        for family, replacements in warning_anchors.items():
            if len(replacements) != 6 or len(conversion_sources[family]) != 2:
                raise RuntimeError(
                    f"r16 warning-rebalance cardinality drift: {split}/{family}"
                )
            for index, replacement in replacements.items():
                expected_source_tier = conversion_sources[family].get(
                    index, "warning-candidate"
                )
                if result[family][index]["design_tier"] != expected_source_tier:
                    raise RuntimeError(
                        f"r16 warning anchor predecessor-tier drift: "
                        f"{split}/{family}/{index}"
                    )
                result[family][index] = dict(replacement)

    if _include_r18_speck_reinforcement:
        replacements = _R18_SPECK_REINFORCEMENT_MANIFEST["splits"][split]
        if len(replacements) != 10:
            raise RuntimeError(f"r18 speck replacement cardinality drift: {split}")
        for index, replacement in replacements.items():
            source = result["artifact-speck"][index]
            if source["design_tier"] != replacement["design_tier"] or source[
                "design_tier"
            ] not in {"clear-reject-candidate", "dominant-reject-candidate"}:
                raise RuntimeError(
                    f"r18 speck replacement source-tier drift: {split}/{index}"
                )
            result["artifact-speck"][index] = {
                **replacement,
                "direct_visibility_reinforcement_revision": (
                    _R18_SPECK_REINFORCEMENT_REVISION
                ),
            }

    family_nonce_offsets = {
        "artifact-fine-grain": 0,
        "artifact-speck": 100,
        "artifact-microblob": 200,
        "artifact-short-dash": 300,
        "artifact-parallel-bundle": 400,
    }
    schedule_revision = (
        (_SCHEDULE_REVISION if _schedule_revision_override is None else _schedule_revision_override)
        if _include_r18_speck_reinforcement
        else _R17_SCHEDULE_REVISION
    )
    for family, variants in result.items():
        for index, parameters in enumerate(variants):
            parameters["schedule_revision"] = schedule_revision
            parameters["condition_nonce"] = (
                nonce_base + family_nonce_offsets[family] + index
            )
    if any(len(variants) != 20 for variants in result.values()):
        raise RuntimeError("r6 bounded artifact variant contract drift")
    predecessor_tier_counts = Counter(
        {
            "clean-candidate": 5,
            "warning-candidate": 4,
            "clear-reject-candidate": 7,
            "dominant-reject-candidate": 4,
        }
    )
    sparse_r16_tier_counts = Counter(
        {
            "clean-candidate": 4,
            "warning-candidate": 6,
            "clear-reject-candidate": 6,
            "dominant-reject-candidate": 4,
        }
    )
    for family, variants in result.items():
        if len({canonical_json_bytes(item) for item in variants}) != 20:
            raise RuntimeError(f"r6 duplicate artifact condition: {family}")
        expected_tier_counts = (
            sparse_r16_tier_counts
            if _include_r16_warning_rebalance and family != "artifact-fine-grain"
            else predecessor_tier_counts
        )
        tier_counts = Counter(str(item["design_tier"]) for item in variants)
        if tier_counts != expected_tier_counts:
            raise RuntimeError(f"r16 design-tier cardinality drift: {family}")
        for tier in expected_tier_counts:
            residues = {
                index % len(_FOUNDATIONS)
                for index, item in enumerate(variants)
                if item["design_tier"] == tier
            }
            if residues != {0, 1, 2}:
                raise RuntimeError(
                    f"r6 design tier lacks mod-3 foundation coverage: {family}/{tier}"
                )
    return result


def _validate_dev_r17_morphology_schedules() -> None:
    _validate_dev_r17_reference_prequalification_design()
    sparse_families = (
        "artifact-speck",
        "artifact-microblob",
        "artifact-short-dash",
        "artifact-parallel-bundle",
    )
    splits = ("calibration", "holdout")

    def morphology(parameters: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in parameters.items()
            if key not in {"schedule_revision", "condition_nonce"}
        }

    def fallback_quadrant_capacity(*, margin: int, separation: int) -> int:
        """Return the least capacity of the renderer's four bounded lattices."""

        internal_guard = max(
            0,
            math.ceil((separation - (2 * margin + 1)) / 2),
        )
        capacities: list[int] = []
        for quadrant_index, (left, top, width, height) in enumerate(
            _metric_quadrants((128, 96, 256, 192))
        ):
            x_min, x_max = left + margin, left + width - margin - 1
            y_min, y_max = top + margin, top + height - margin - 1
            if quadrant_index % 2 == 0:
                x_max -= internal_guard
            else:
                x_min += internal_guard
            if quadrant_index < 2:
                y_max -= internal_guard
            else:
                y_min += internal_guard
            if x_min > x_max or y_min > y_max:
                return 0
            x_start = x_min + ((x_max - x_min) % separation) // 2
            y_start = y_min + ((y_max - y_min) % separation) // 2
            x_count = ((x_max - x_start) // separation) + 1
            y_count = ((y_max - y_start) // separation) + 1
            capacities.append(x_count * y_count)
        return min(capacities)

    if (
        _R17_SCHEDULE_REVISION
        != "dev-r17-protocol-zero-reference-prequalification-schedule-v1"
        or _PUBLIC_WARNING_ANCHOR_REVISION
        != "dev-r16-six-per-sparse-family-direct-visible-warning-v1"
        or _PUBLIC_WARNING_CONVERSION_REVISION
        != "dev-r16-one-clean-one-clear-per-sparse-family-v1"
        or _PUBLIC_MICROBLOB_REJECT_ANCHOR_REVISION
        != "dev-r15-calibration-quantized-microblob-reject-v1"
    ):
        raise RuntimeError("r17 inherited morphology authority drift")

    predecessor = {
        split: _artifact_variants(
            split,
            _include_r16_warning_rebalance=False,
            _include_r18_speck_reinforcement=False,
        )
        for split in splits
    }
    current = {
        split: _artifact_variants(
            split, _include_r18_speck_reinforcement=False
        )
        for split in splits
    }
    current_morphology = {
        split: {
            family: [morphology(parameters) for parameters in variants]
            for family, variants in current[split].items()
        }
        for split in splits
    }
    if (
        sum(
            len(variants)
            for families in current_morphology.values()
            for variants in families.values()
        )
        != 200
        or sha256_bytes(canonical_json_bytes(current_morphology))
        != _R17_PRESERVED_R16_ARTIFACT_MORPHOLOGY_SHA256
    ):
        raise RuntimeError("r17 preserved r16 artifact morphology drift")

    r15_warning_manifest = {
        "revision": _R15_WARNING_ACCEPTANCE_ANCHORS["revision"],
        "splits": {
            split: {
                family: [
                    {"variant_index": index, "parameters": parameters}
                    for index, parameters in sorted(
                        _R15_WARNING_ACCEPTANCE_ANCHORS["splits"][split][family].items()
                    )
                ]
                for family in sparse_families
            }
            for split in splits
        },
    }
    if sha256_bytes(canonical_json_bytes(r15_warning_manifest)) != (
        "5e997df4c7d4e0c6106b3060437235a7f665b08a6b02e00a86f4a4f024dc77e6"
    ):
        raise RuntimeError("r16 inherited r15 warning-anchor manifest SHA drift")

    anchor_manifest = {
        "revision": _WARNING_ACCEPTANCE_ANCHORS["revision"],
        "splits": {
            split: {
                family: [
                    {"variant_index": index, "parameters": parameters}
                    for index, parameters in sorted(
                        _WARNING_ACCEPTANCE_ANCHORS["splits"][split][family].items()
                    )
                ]
                for family in sparse_families
            }
            for split in splits
        },
    }
    if sha256_bytes(canonical_json_bytes(anchor_manifest)) != (
        "bfc0e95e402c4f5751212c67759940c8c01802bb0a938899304ec4db576aa5df"
    ):
        raise RuntimeError("r16 warning-anchor manifest SHA drift")

    conversion_manifest = {
        "revision": _PUBLIC_WARNING_CONVERSION_REVISION,
        "splits": {
            split: {
                family: [
                    {
                        "variant_index": index,
                        "source_tier": source_tier,
                        "source_parameters": morphology(
                            predecessor[split][family][index]
                        ),
                        "warning_parameters": _R16_WARNING_CONVERSION_ANCHORS[split][
                            family
                        ][index],
                    }
                    for index, source_tier in sorted(
                        _R16_WARNING_CONVERSION_SOURCES[split][family].items()
                    )
                ]
                for family in sparse_families
            }
            for split in splits
        },
    }
    if sha256_bytes(canonical_json_bytes(conversion_manifest)) != (
        "0f0f4e0865249d34ff8f83537f60dcaee1c2ee0fd64836551b6aa754251fb8e7"
    ):
        raise RuntimeError("r16 warning conversion manifest SHA drift")

    for split in splits:
        warning_tuple_sets: dict[str, set[bytes]] = {}
        for family in sparse_families:
            entries = anchor_manifest["splits"][split][family]
            conversions = conversion_manifest["splits"][split][family]
            warning_indices = {entry["variant_index"] for entry in entries}
            if (
                len(entries) != 6
                or Counter(index % len(_FOUNDATIONS) for index in warning_indices)
                != Counter({0: 2, 1: 2, 2: 2})
                or Counter(item["source_tier"] for item in conversions)
                != Counter({"clean-candidate": 1, "clear-reject-candidate": 1})
            ):
                raise RuntimeError(
                    f"r16 warning tier/residue conversion drift: {split}/{family}"
                )
            for entry in entries:
                index = entry["variant_index"]
                actual = morphology(current[split][family][index])
                if actual != entry["parameters"]:
                    raise RuntimeError(
                        f"r16 warning anchor morphology drift: {split}/{family}/{index}"
                    )
                parameters = entry["parameters"]
                amplitude = float(parameters["amplitude_l"])
                if (
                    parameters["design_tier"] != "warning-candidate"
                    or not 6.0 <= amplitude <= 8.0
                    or int(np.rint(amplitude)) not in {6, 7, 8}
                ):
                    raise RuntimeError(
                        f"r16 warning weak-amplitude contract drift: "
                        f"{split}/{family}/{index}"
                    )
                if family == "artifact-speck":
                    valid = (
                        parameters["diameter_px"] == 1
                        and parameters["count_in_metric_window"] == 4
                        and parameters["shoulder_fraction"] == 0.05
                        and parameters["minimum_separation_px"] >= 10
                    )
                    packing_count = int(parameters["count_in_metric_window"])
                    packing_margin = 1
                    packing_separation = int(parameters["minimum_separation_px"])
                elif family == "artifact-microblob":
                    valid = (
                        4 <= parameters["diameter_px"] <= 8
                        and parameters["count_in_metric_window"] in {2, 4}
                        and 2 <= parameters["support_radius_px"] <= 7
                        and parameters["minimum_separation_px"]
                        >= 2 * parameters["support_radius_px"] + 1
                    )
                    packing_count = int(parameters["count_in_metric_window"])
                    packing_margin = int(parameters["support_radius_px"]) + 1
                    packing_separation = int(parameters["minimum_separation_px"])
                elif family == "artifact-short-dash":
                    valid = (
                        parameters["width_px"] == 1
                        and parameters["count_in_metric_window"] in {1, 2}
                        and 6 <= parameters["length_px"] <= 16
                        and parameters["minimum_separation_px"]
                        >= parameters["length_px"] + parameters["width_px"] + 3
                    )
                    packing_count = int(parameters["count_in_metric_window"])
                    packing_margin = (
                        int(math.ceil(float(parameters["length_px"]) / 2))
                        + int(parameters["width_px"])
                        + 2
                    )
                    packing_separation = int(parameters["minimum_separation_px"])
                else:
                    valid = (
                        parameters["width_px"] == 1
                        and parameters["pair_count_in_metric_window"] == 1
                        and parameters["length_px"] % 2 == 0
                        and parameters["spacing_px"] % 2 == 0
                        and parameters["minimum_bundle_separation_px"]
                        >= max(parameters["length_px"], parameters["spacing_px"])
                        + parameters["width_px"]
                        + 3
                    )
                    packing_count = int(parameters["pair_count_in_metric_window"])
                    packing_margin = (
                        int(
                            math.ceil(
                                max(
                                    float(parameters["length_px"]),
                                    float(parameters["spacing_px"]),
                                )
                                / 2
                                + float(parameters["width_px"]) / 2
                            )
                        )
                        + 2
                    )
                    packing_separation = int(parameters["minimum_bundle_separation_px"])
                if not valid:
                    raise RuntimeError(
                        f"r16 warning direct-visible geometry drift: "
                        f"{split}/{family}/{index}"
                    )
                if fallback_quadrant_capacity(
                    margin=packing_margin,
                    separation=packing_separation,
                ) < math.ceil(packing_count / 4):
                    raise RuntimeError(
                        f"r16 warning bounded-lattice capacity drift: "
                        f"{split}/{family}/{index}"
                    )
                rendered = _render_unsigned_delta(
                    family,
                    parameters,
                    np.random.default_rng(160000 + index),
                    384,
                    512,
                    (128, 96, 256, 192),
                )
                outside = rendered.copy()
                outside[96:288, 128:384] = 0
                if not np.any(rendered) or np.any(outside):
                    raise RuntimeError(
                        f"r16 warning packing/render contract drift: "
                        f"{split}/{family}/{index}"
                    )
            for conversion in conversions:
                index = conversion["variant_index"]
                source = morphology(predecessor[split][family][index])
                target = morphology(current[split][family][index])
                amplitude_direction_ok = (
                    float(source["amplitude_l"]) < float(target["amplitude_l"])
                    if conversion["source_tier"] == "clean-candidate"
                    else float(target["amplitude_l"]) < float(source["amplitude_l"])
                )
                if (
                    source != conversion["source_parameters"]
                    or source["design_tier"] != conversion["source_tier"]
                    or target != conversion["warning_parameters"]
                    or {
                        key: value
                        for key, value in source.items()
                        if key != "design_tier"
                    }
                    == {
                        key: value
                        for key, value in target.items()
                        if key != "design_tier"
                    }
                    or not amplitude_direction_ok
                ):
                    raise RuntimeError(
                        f"r16 non-metadata warning conversion drift: "
                        f"{split}/{family}/{index}"
                    )
            warning_tuple_sets[family] = {
                canonical_json_bytes(entry["parameters"]) for entry in entries
            }
            if len(warning_tuple_sets[family]) != 6:
                raise RuntimeError(
                    f"r16 warning morphology uniqueness drift: {split}/{family}"
                )

        for family in sparse_families:
            other_split = "holdout" if split == "calibration" else "calibration"
            other_tuples = {
                canonical_json_bytes(entry["parameters"])
                for entry in anchor_manifest["splits"][other_split][family]
            }
            if warning_tuple_sets[family] & other_tuples:
                raise RuntimeError(
                    f"r16 split warning morphology tuple overlap: {family}"
                )

    allowed_full_split_overlap = {
        "artifact-speck": set(),
        "artifact-microblob": set(),
        "artifact-short-dash": set(),
        "artifact-parallel-bundle": {
            canonical_json_bytes(
                {
                    "design_tier": "dominant-reject-candidate",
                    "length_px": 22,
                    "width_px": 3,
                    "spacing_px": 8,
                    "amplitude_l": 11.8,
                    "pair_count_in_metric_window": 9,
                    "minimum_bundle_separation_px": 30,
                }
            ),
            canonical_json_bytes(
                {
                    "design_tier": "dominant-reject-candidate",
                    "length_px": 28,
                    "width_px": 3,
                    "spacing_px": 12,
                    "amplitude_l": 12.0,
                    "pair_count_in_metric_window": 8,
                    "minimum_bundle_separation_px": 36,
                }
            ),
        },
    }
    for family in sparse_families:
        calibration_tuples = {
            canonical_json_bytes(morphology(parameters))
            for parameters in current["calibration"][family]
        }
        holdout_tuples = {
            canonical_json_bytes(morphology(parameters))
            for parameters in current["holdout"][family]
        }
        if calibration_tuples & holdout_tuples != allowed_full_split_overlap[family]:
            raise RuntimeError(f"r16 full split morphology overlap drift: {family}")

    microblob_anchor_manifest = {
        "revision": _CALIBRATION_MICROBLOB_CLEAR_REJECT_ANCHORS["revision"],
        "split": "calibration",
        "family": "artifact-microblob",
        "entries": [
            {"variant_index": index, "parameters": parameters}
            for index, parameters in sorted(
                _CALIBRATION_MICROBLOB_CLEAR_REJECT_ANCHORS["entries"].items()
            )
        ],
    }
    if sha256_bytes(canonical_json_bytes(microblob_anchor_manifest)) != (
        "dd2ce7fd13f624bd065e8c7a6bacc2ab8bd593821dec8d46250a40e57ef64833"
    ):
        raise RuntimeError("r16 inherited r15 microblob anchor SHA drift")
    predecessor_microblob = predecessor["calibration"]["artifact-microblob"]
    final_microblob = current["calibration"]["artifact-microblob"]
    converted_microblob_index = 16
    for entry in microblob_anchor_manifest["entries"]:
        index = entry["variant_index"]
        if morphology(predecessor_microblob[index]) != entry["parameters"]:
            raise RuntimeError(f"r16 inherited r15 microblob source drift: {index}")
        if index != converted_microblob_index and (
            morphology(final_microblob[index]) != entry["parameters"]
        ):
            raise RuntimeError(
                f"r16 preserved r15 microblob clear-anchor drift: {index}"
            )
    remaining_microblob_entries = [
        entry
        for entry in microblob_anchor_manifest["entries"]
        if entry["variant_index"] != converted_microblob_index
    ]
    active_microblob_anchor_manifest = {
        "revision": _CALIBRATION_MICROBLOB_CLEAR_REJECT_ANCHORS["revision"],
        "split": "calibration",
        "family": "artifact-microblob",
        "entries": remaining_microblob_entries,
    }
    if sha256_bytes(canonical_json_bytes(active_microblob_anchor_manifest)) != (
        "2c207dfb5249d42056e164e7553091a9a617d8b673aecfb5ea25e4d757651f0c"
    ):
        raise RuntimeError("r16 active r15 microblob anchor SHA drift")
    if Counter(
        (
            int(entry["parameters"]["diameter_px"]),
            int(entry["parameters"]["support_radius_px"]),
            int(entry["parameters"]["count_in_metric_window"]),
        )
        for entry in remaining_microblob_entries
    ) != Counter({(4, 2, 64): 3, (6, 3, 44): 3}) or {
        entry["variant_index"] % len(_FOUNDATIONS)
        for entry in remaining_microblob_entries
    } != {0, 1, 2}:
        raise RuntimeError("r16 preserved r15 microblob compact matrix drift")
    for diameter in (4, 6):
        ladder = {
            entry["variant_index"] % len(_FOUNDATIONS): float(
                entry["parameters"]["amplitude_l"]
            )
            for entry in remaining_microblob_entries
            if int(entry["parameters"]["diameter_px"]) == diameter
        }
        if ladder != {0: 11.4, 1: 11.6, 2: 11.8}:
            raise RuntimeError(
                f"r16 preserved r15 microblob residue ladder drift: {diameter}"
            )

    expected_active_speck_reject_counts = {
        "calibration": {
            "clear-reject-candidate": (36, 40, 44, 48, 52, 56),
            "dominant-reject-candidate": (64, 72, 80, 88),
        },
        "holdout": {
            "clear-reject-candidate": (34, 38, 42, 46, 50, 58),
            "dominant-reject-candidate": (68, 76, 84, 90),
        },
    }
    for split, expected_by_tier in expected_active_speck_reject_counts.items():
        for tier, expected_counts in expected_by_tier.items():
            actual_counts = tuple(
                int(parameters["count_in_metric_window"])
                for parameters in current[split]["artifact-speck"]
                if parameters["design_tier"] == tier
            )
            if actual_counts != expected_counts:
                raise RuntimeError(
                    f"r16 active speck reject-count drift: {split}/{tier}"
                )

    predecessor_morphology = {
        split: {
            family: [morphology(parameters) for parameters in variants]
            for family, variants in predecessor[split].items()
        }
        for split in splits
    }
    if sha256_bytes(canonical_json_bytes(predecessor_morphology)) != (
        "7adf59546337cded9910d17fbff5d383fc36e1058e69f98ed633890c2dd60f5b"
    ):
        raise RuntimeError("r16 predecessor morphology SHA drift")

    changed_morphology = {
        (split, family, index)
        for split in splits
        for family, variants in current[split].items()
        for index, parameters in enumerate(variants)
        if morphology(parameters) != morphology(predecessor[split][family][index])
    }
    expected_changed_morphology = {
        (split, family, index)
        for split in splits
        for family in sparse_families
        for index in _R16_WARNING_CONVERSION_SOURCES[split][family]
    }
    if (
        changed_morphology != expected_changed_morphology
        or len(changed_morphology) != 16
    ):
        raise RuntimeError("r16 exact morphology change-set drift")

    preserved_morphology: dict[str, dict[str, list[dict[str, Any]]]] = {}
    preserved_nonwarning_morphology: dict[str, dict[str, list[dict[str, Any]]]] = {}
    sparse_preserved_count = 0
    for split in splits:
        preserved_morphology[split] = {}
        preserved_nonwarning_morphology[split] = {}
        for family, variants in current[split].items():
            converted = set(_R16_WARNING_CONVERSION_SOURCES[split].get(family, {}))
            entries: list[dict[str, Any]] = []
            for index, parameters in enumerate(variants):
                if index in converted:
                    continue
                actual = morphology(parameters)
                expected = morphology(predecessor[split][family][index])
                if actual != expected:
                    raise RuntimeError(
                        f"r16 nonconversion morphology drift: {split}/{family}/{index}"
                    )
                entries.append({"variant_index": index, "parameters": actual})
            preserved_morphology[split][family] = entries
            nonwarning_entries = [
                entry
                for entry in entries
                if entry["parameters"]["design_tier"] != "warning-candidate"
            ]
            preserved_nonwarning_morphology[split][family] = nonwarning_entries
            if family in sparse_families:
                sparse_preserved_count += len(entries)
    if (
        sum(
            len(entries)
            for families in preserved_morphology.values()
            for entries in families.values()
        )
        != 184
        or sparse_preserved_count != 144
    ):
        raise RuntimeError("r16 preserved morphology cardinality drift")
    if sha256_bytes(canonical_json_bytes(preserved_morphology)) != (
        "b8e7429a62e78c6e67efbfa6ec8b3b2fb0f16fb07f61ea9c7590f83f1b637ecd"
    ):
        raise RuntimeError("r16 preserved morphology SHA drift")
    if sha256_bytes(canonical_json_bytes(preserved_nonwarning_morphology)) != (
        "72212f11b453526bd6cec7e11420bcb9a0df7bbae2e097168393a5ee0c9a48b4"
    ):
        raise RuntimeError("r16 preserved nonwarning morphology SHA drift")

    expected_sparse_tiers = Counter(
        {
            "clean-candidate": 4,
            "warning-candidate": 6,
            "clear-reject-candidate": 6,
            "dominant-reject-candidate": 4,
        }
    )
    expected_grain_tiers = Counter(
        {
            "clean-candidate": 5,
            "warning-candidate": 4,
            "clear-reject-candidate": 7,
            "dominant-reject-candidate": 4,
        }
    )
    for split in splits:
        if (
            Counter(
                parameters["design_tier"]
                for parameters in current[split]["artifact-fine-grain"]
            )
            != expected_grain_tiers
        ):
            raise RuntimeError(f"r16 fine-grain tier-count drift: {split}")
        for family in sparse_families:
            variants = current[split][family]
            morphology_tuples = {
                canonical_json_bytes(morphology(item)) for item in variants
            }
            if len(morphology_tuples) != 20:
                raise RuntimeError(
                    f"r16 sparse family morphology uniqueness drift: {split}/{family}"
                )
            if Counter(parameters["design_tier"] for parameters in variants) != (
                expected_sparse_tiers
            ):
                raise RuntimeError(f"r16 sparse tier-count drift: {split}/{family}")
            for tier in expected_sparse_tiers:
                if {
                    index % len(_FOUNDATIONS)
                    for index, parameters in enumerate(variants)
                    if parameters["design_tier"] == tier
                } != {0, 1, 2}:
                    raise RuntimeError(
                        f"r16 sparse tier mod-3 coverage drift: {split}/{family}/{tier}"
                    )
        total_tiers = Counter(
            parameters["design_tier"]
            for variants in current[split].values()
            for parameters in variants
        )
        if (
            total_tiers
            != Counter(
                {
                    "clean-candidate": 21,
                    "warning-candidate": 28,
                    "clear-reject-candidate": 31,
                    "dominant-reject-candidate": 20,
                }
            )
            or sum(
                1
                for family in sparse_families
                for parameters in current[split][family]
                if parameters["design_tier"] == "warning-candidate"
            )
            != 24
            or total_tiers["clear-reject-candidate"]
            + total_tiers["dominant-reject-candidate"]
            != 51
        ):
            raise RuntimeError(f"r16 structural population-margin drift: {split}")

    expected_grain_periods = {
        "calibration": {
            "clear-reject-candidate": (
                ("fine-band", 8.8),
                ("halftone", 11),
                ("fine-band", 12.0),
                ("fine-band", 6.7),
                ("halftone", 10),
                ("fine-band", 11.6),
                ("fine-band", 4.1),
            ),
            "dominant-reject-candidate": (
                ("halftone", 7),
                ("fine-band", 4.8),
                ("fine-band", 8.0),
                ("fine-band", 3.0),
            ),
        },
        "holdout": {
            "clear-reject-candidate": (
                ("halftone", 9),
                ("fine-band", 11.4),
                ("fine-band", 7.1),
                ("fine-band", 11.8),
                ("halftone", 12),
                ("fine-band", 4.5),
                ("fine-band", 9.2),
            ),
            "dominant-reject-candidate": (
                ("fine-band", 5.1),
                ("fine-band", 8.4),
                ("fine-band", 3.3),
                ("halftone", 8),
            ),
        },
    }
    split_tuples: dict[str, set[tuple[str, float]]] = {}
    for split, expected_by_tier in expected_grain_periods.items():
        grain = _artifact_variants(
            split, _include_r18_speck_reinforcement=False
        )["artifact-fine-grain"]
        split_tuples[split] = set()
        for tier, expected in expected_by_tier.items():
            actual = tuple(
                (
                    str(parameters["pattern"]),
                    float(parameters.get("wavelength_px", parameters.get("cell_px"))),
                )
                for parameters in grain
                if parameters["design_tier"] == tier
            )
            if actual != expected:
                raise RuntimeError(f"r16 grain reject period drift: {split}/{tier}")
            if any(not 2.0 < period < 13.0 for _, period in actual):
                raise RuntimeError(
                    f"r16 grain reject period escaped metric support: {split}/{tier}"
                )
            split_tuples[split].update(actual)
    if split_tuples["calibration"] & split_tuples["holdout"]:
        raise RuntimeError("r16 calibration/holdout grain pattern-period overlap")


def dev_r18_authority_binding() -> dict[str, Any]:
    """Return the frozen public r18 predecessor catalog authority."""

    return {
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
        "protocol_zero_nonce_bases": {
            "calibration": 1051000,
            "holdout": 1061000,
        },
        "duplicate_audit_nonces": {
            "calibration": [1091000, 1091001, 1091002],
            "holdout": [1101000, 1101001, 1101002],
        },
        "speck_reinforcement_revision": _R18_SPECK_REINFORCEMENT_REVISION,
        "speck_reinforcement_manifest_sha256": (
            _R18_SPECK_REINFORCEMENT_MANIFEST_SHA256
        ),
        "full_artifact_morphology_sha256": (
            _R18_FULL_ARTIFACT_MORPHOLOGY_SHA256
        ),
        "preserved_r17_morphology_sha256": (
            _R18_PRESERVED_R17_MORPHOLOGY_SHA256
        ),
    }


def dev_r19_authority_binding() -> dict[str, Any]:
    """Return the tracked, public r19 catalog authority without runtime material."""

    return {
        "schedule_revision": _R19_SCHEDULE_REVISION,
        "duplicate_equivalence_policy_revision": (
            _R19_DUPLICATE_EQUIVALENCE_POLICY_REVISION
        ),
        "duplicate_equivalence_policy_manifest_sha256": (
            _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST_SHA256
        ),
        "sanitized_r18_basis_sha256": _R19_SANITIZED_R18_BASIS_SHA256,
        "public_payload_commitment_prefix": (
            _R19_PUBLIC_PAYLOAD_COMMITMENT_PREFIX.decode("ascii")
        ),
        "private_reference_transform_prefix": (
            _R19_PRIVATE_REFERENCE_TRANSFORM_PREFIX.decode("ascii")
        ),
        "foundation_offset_lane": _R19_FOUNDATION_OFFSET_LANE,
        "foundation_assignment_lane": _R19_FOUNDATION_ASSIGNMENT_LANE,
        "delta_lane": _R19_DELTA_LANE,
        "private_control_id_prefix": (
            _R19_PRIVATE_CONTROL_ID_PREFIX.decode("ascii")
        ),
        "artifact_nonce_bases": dict(_R19_ARTIFACT_NONCE_BASES),
        "protocol_zero_nonce_bases": dict(_R19_PROTOCOL_ZERO_NONCE_BASES),
        "duplicate_audit_nonces": {
            split: list(values)
            for split, values in _R19_DUPLICATE_AUDIT_NONCES.items()
        },
        "speck_reinforcement_revision": _R18_SPECK_REINFORCEMENT_REVISION,
        "speck_reinforcement_manifest_sha256": (
            _R18_SPECK_REINFORCEMENT_MANIFEST_SHA256
        ),
        "predecessor_full_artifact_morphology_sha256": (
            _R18_FULL_ARTIFACT_MORPHOLOGY_SHA256
        ),
        "full_artifact_morphology_sha256": (
            _R18_FULL_ARTIFACT_MORPHOLOGY_SHA256
        ),
        "exact_morphology_change_count_across_splits": 0,
    }


def dev_r20_authority_binding() -> dict[str, Any]:
    """Return the tracked, public r20 catalog authority without runtime material."""

    return {
        "schedule_revision": _SCHEDULE_REVISION,
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
            _PUBLIC_PAYLOAD_COMMITMENT_PREFIX.decode("ascii")
        ),
        "private_reference_transform_prefix": (
            _PRIVATE_REFERENCE_TRANSFORM_PREFIX.decode("ascii")
        ),
        "foundation_offset_lane": _FOUNDATION_OFFSET_LANE,
        "foundation_assignment_lane": _FOUNDATION_ASSIGNMENT_LANE,
        "delta_lane": _DELTA_LANE,
        "private_control_id_prefix": _PRIVATE_CONTROL_ID_PREFIX.decode("ascii"),
        "artifact_nonce_bases": dict(_ARTIFACT_NONCE_BASES),
        "protocol_zero_nonce_bases": dict(_PROTOCOL_ZERO_NONCE_BASES),
        "duplicate_audit_nonces": {
            split: list(values) for split, values in _DUPLICATE_AUDIT_NONCES.items()
        },
        "speck_reinforcement_revision": _R18_SPECK_REINFORCEMENT_REVISION,
        "speck_reinforcement_manifest_sha256": (
            _R18_SPECK_REINFORCEMENT_MANIFEST_SHA256
        ),
        "predecessor_full_artifact_morphology_sha256": (
            _R18_FULL_ARTIFACT_MORPHOLOGY_SHA256
        ),
        "full_artifact_morphology_sha256": (
            _R18_FULL_ARTIFACT_MORPHOLOGY_SHA256
        ),
        "exact_morphology_change_count_across_splits": 0,
        "obvious_artifact_duplicate_sentinel_change_count_across_splits": 2,
        "clean_duplicate_construction_change_count_across_splits": 0,
    }


def _validate_dev_r18_morphology_schedules() -> None:
    """Prove the bounded r18 overlay and its unchanged r17 complement."""

    _validate_dev_r17_morphology_schedules()
    splits = ("calibration", "holdout")
    family = "artifact-speck"

    r18_binding = dev_r18_authority_binding()
    if (
        _R18_SCHEDULE_REVISION
        != "dev-r18-symmetric-direct-visible-speck-reinforcement-schedule-v1"
        or r18_binding["public_payload_commitment_prefix"]
        != "microtexture-v2-r6/public-payload-commitment/v14/"
        or r18_binding["private_reference_transform_prefix"]
        != "private-reference-transform-v13/"
        or r18_binding["foundation_offset_lane"] != "foundation-offset-v12"
        or r18_binding["foundation_assignment_lane"]
        != "foundation-assignment-v12"
        or r18_binding["delta_lane"] != "delta-v12"
        or r18_binding["private_control_id_prefix"]
        != "microtexture-v2-r6/private-control-id/v12/"
        or r18_binding["artifact_nonce_bases"]
        != {"calibration": 1073000, "holdout": 1083000}
        or r18_binding["protocol_zero_nonce_bases"]
        != {"calibration": 1051000, "holdout": 1061000}
        or r18_binding["duplicate_audit_nonces"]
        != {
            "calibration": [1091000, 1091001, 1091002],
            "holdout": [1101000, 1101001, 1101002],
        }
    ):
        raise RuntimeError("r18 schedule/domain/nonce authority drift")

    r18_nonces: dict[str, set[int]] = {}
    r17_nonces: dict[str, set[int]] = {}
    for split in splits:
        r18_nonces[split] = {
            r18_binding["artifact_nonce_bases"][split] + family_offset + index
            for family_offset in (0, 100, 200, 300, 400)
            for index in range(20)
        } | {
            r18_binding["protocol_zero_nonce_bases"][split] + index
            for index in range(16)
        } | set(r18_binding["duplicate_audit_nonces"][split])
        r17_artifact_base = 973000 if split == "calibration" else 983000
        r17_zero_base = 951000 if split == "calibration" else 961000
        r17_duplicate = (
            (991000, 991001, 991002)
            if split == "calibration"
            else (1001000, 1001001, 1001002)
        )
        r17_nonces[split] = {
            r17_artifact_base + family_offset + index
            for family_offset in (0, 100, 200, 300, 400)
            for index in range(20)
        } | {r17_zero_base + index for index in range(16)} | set(r17_duplicate)
        if len(r18_nonces[split]) != 119 or r18_nonces[split] & r17_nonces[split]:
            raise RuntimeError(f"r18 fresh nonce-space drift: {split}")
    if r18_nonces["calibration"] & r18_nonces["holdout"]:
        raise RuntimeError("r18 calibration/holdout nonce-space overlap")

    manifest = _R18_SPECK_REINFORCEMENT_MANIFEST
    if set(manifest) != {
        "revision",
        "inherited_schedule_revision",
        "schedule_revision",
        "sanitized_r17_basis",
        "family",
        "target_tiers",
        "target_conditions_per_split",
        "clear_reject_conditions_per_split",
        "dominant_reject_conditions_per_split",
        "tiny_speck_development_floor",
        "tiny_speck_structural_miss_budget",
        "spot_development_floor",
        "spot_endpoint_relation",
        "direct_visibility_contract",
        "preservation_contract",
        "splits",
    }:
        raise RuntimeError("r18 speck manifest top-level schema drift")
    basis = manifest["sanitized_r17_basis"]
    holdout_basis = basis.get("holdout", {})
    if (
        set(basis)
        != {
            "calibration_formal_and_development_endpoint_floors_passed",
            "holdout",
            "private_audits_passed",
            "metric_or_threshold_evaluation_performed",
        }
        or basis["calibration_formal_and_development_endpoint_floors_passed"]
        is not True
        or basis["private_audits_passed"] is not True
        or basis["metric_or_threshold_evaluation_performed"] is not False
        or set(holdout_basis)
        != {
            "tiny_speck_reject_detection",
            "spot_reject_detection",
            "all_other_endpoints_passed",
        }
        or holdout_basis["all_other_endpoints_passed"] is not True
        or holdout_basis["tiny_speck_reject_detection"]
        != {"observed": 0, "formal_minimum": 4, "development_minimum": 6}
        or holdout_basis["spot_reject_detection"]
        != {"observed": 9, "formal_minimum": 8, "development_minimum": 10}
    ):
        raise RuntimeError("r18 sanitized r17 aggregate drift")
    direct_contract = manifest["direct_visibility_contract"]
    preservation_contract = manifest["preservation_contract"]
    if (
        manifest["revision"] != _R18_SPECK_REINFORCEMENT_REVISION
        or manifest["inherited_schedule_revision"] != _R17_SCHEDULE_REVISION
        or manifest["schedule_revision"] != _R18_SCHEDULE_REVISION
        or manifest["family"] != family
        or manifest["target_tiers"]
        != ["clear-reject-candidate", "dominant-reject-candidate"]
        or manifest["target_conditions_per_split"] != 10
        or manifest["clear_reject_conditions_per_split"] != 6
        or manifest["dominant_reject_conditions_per_split"] != 4
        or manifest["tiny_speck_development_floor"] != 6
        or manifest["tiny_speck_structural_miss_budget"] != 4
        or manifest["spot_development_floor"] != 10
        or manifest["spot_endpoint_relation"]
        != "tiny_speck_visible OR microblob_visible"
        or manifest["target_conditions_per_split"]
        - manifest["tiny_speck_development_floor"]
        != manifest["tiny_speck_structural_miss_budget"]
        or manifest["spot_development_floor"]
        - holdout_basis["spot_reject_detection"]["observed"]
        != 1
        or manifest["target_conditions_per_split"]
        < manifest["spot_development_floor"]
        or direct_contract
        != {
            "diameter_px": 1,
            "minimum_core_count": 4,
            "maximum_core_count": 7,
            "minimum_center_amplitude_l": 11.2,
            "maximum_center_amplitude_l": 12.0,
            "minimum_encoded_axial_shoulder_l": 5,
            "minimum_separation_px": 30,
            "quadrant_stratified": True,
            "returns_to_uninjected_background_outside_one_axial_neighbor": True,
            "microblob_blur_forbidden": True,
            "vision_truth_guaranteed": False,
        }
        or preservation_contract
        != {
            "clean_morphologies_unchanged": True,
            "warning_morphologies_unchanged": True,
            "all_non_speck_morphologies_unchanged": True,
            "design_tier_membership_unchanged": True,
            "artifact_condition_count_per_split_unchanged": 100,
            "metric_threshold_population_and_rate_contracts_unchanged": True,
        }
        or set(manifest["splits"]) != set(splits)
        or sha256_bytes(canonical_json_bytes(manifest))
        != _R18_SPECK_REINFORCEMENT_MANIFEST_SHA256
    ):
        raise RuntimeError("r18 speck reinforcement authority drift")

    expected_indices = {
        "calibration": {3, 5, 6, 7, 8, 12, 15, 16, 17, 19},
        "holdout": {1, 3, 4, 6, 9, 10, 11, 13, 14, 18},
    }
    replacement_keys = {
        "design_tier",
        "diameter_px",
        "amplitude_l",
        "count_in_metric_window",
        "shoulder_fraction",
        "minimum_separation_px",
    }
    for split in splits:
        replacements = manifest["splits"][split]
        if set(replacements) != expected_indices[split] or any(
            set(replacement) != replacement_keys
            for replacement in replacements.values()
        ):
            raise RuntimeError(f"r18 speck replacement schema drift: {split}")

    def morphology(parameters: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in parameters.items()
            if key not in {"schedule_revision", "condition_nonce"}
        }

    inherited = {
        split: _artifact_variants(
            split, _include_r18_speck_reinforcement=False
        )
        for split in splits
    }
    current = {split: _artifact_variants(split) for split in splits}
    expected_change_set = {
        (split, family, index)
        for split in splits
        for index in expected_indices[split]
    }
    actual_change_set = {
        (split, candidate_family, index)
        for split in splits
        for candidate_family, variants in current[split].items()
        for index, parameters in enumerate(variants)
        if morphology(parameters)
        != morphology(inherited[split][candidate_family][index])
    }
    if actual_change_set != expected_change_set or len(actual_change_set) != 20:
        raise RuntimeError("r18 exact speck morphology change-set drift")

    preserved_r17: dict[str, dict[str, list[dict[str, Any]]]] = {}
    full_r18: dict[str, dict[str, list[dict[str, Any]]]] = {}
    target_profiles: dict[str, Counter[tuple[str, int, float]]] = {}
    target_geometry: dict[
        str, dict[tuple[str, int, float], tuple[float, int]]
    ] = {}
    target_tuples: dict[str, set[bytes]] = {}
    expected_total_tiers = Counter(
        {
            "clean-candidate": 21,
            "warning-candidate": 28,
            "clear-reject-candidate": 31,
            "dominant-reject-candidate": 20,
        }
    )
    for split in splits:
        preserved_r17[split] = {}
        full_r18[split] = {}
        target_tiers: Counter[str] = Counter()
        target_profiles[split] = Counter()
        target_geometry[split] = {}
        target_tuples[split] = set()
        for candidate_family, variants in current[split].items():
            if len(variants) != 20:
                raise RuntimeError(
                    f"r18 artifact family cardinality drift: {split}/{candidate_family}"
                )
            full_r18[split][candidate_family] = [
                morphology(parameters) for parameters in variants
            ]
            preserved_entries: list[dict[str, Any]] = []
            for index, parameters in enumerate(variants):
                actual = morphology(parameters)
                source = morphology(inherited[split][candidate_family][index])
                if (split, candidate_family, index) not in expected_change_set:
                    if actual != source:
                        raise RuntimeError(
                            f"r18 preserved r17 morphology drift: "
                            f"{split}/{candidate_family}/{index}"
                        )
                    preserved_entries.append(
                        {"variant_index": index, "parameters": actual}
                    )
                    continue

                replacement = manifest["splits"][split][index]
                expected = {
                    **replacement,
                    "direct_visibility_reinforcement_revision": (
                        _R18_SPECK_REINFORCEMENT_REVISION
                    ),
                }
                if (
                    candidate_family != family
                    or actual != expected
                    or source["design_tier"] != actual["design_tier"]
                ):
                    raise RuntimeError(
                        f"r18 speck target morphology drift: {split}/{index}"
                    )
                count = int(actual["count_in_metric_window"])
                amplitude = float(actual["amplitude_l"])
                shoulder_fraction = float(actual["shoulder_fraction"])
                separation = int(actual["minimum_separation_px"])
                if (
                    int(actual["diameter_px"]) != direct_contract["diameter_px"]
                    or not direct_contract["minimum_core_count"]
                    <= count
                    <= direct_contract["maximum_core_count"]
                    or not direct_contract["minimum_center_amplitude_l"]
                    <= amplitude
                    <= direct_contract["maximum_center_amplitude_l"]
                    or int(np.rint(amplitude * shoulder_fraction))
                    < direct_contract["minimum_encoded_axial_shoulder_l"]
                    or separation < direct_contract["minimum_separation_px"]
                ):
                    raise RuntimeError(
                        f"r18 speck direct-visible parameter drift: {split}/{index}"
                    )

                rendered = _render_unsigned_delta(
                    family,
                    actual,
                    np.random.default_rng(180000 + index),
                    384,
                    512,
                    (128, 96, 256, 192),
                )
                outside = rendered.copy()
                outside[96:288, 128:384] = 0
                core_y, core_x = np.nonzero(rendered == np.float32(amplitude))
                quadrant_counts = Counter(
                    (0 if x < 256 else 1) + (0 if y < 192 else 2)
                    for y, x in zip(core_y, core_x, strict=True)
                )
                if (
                    np.any(outside)
                    or int(np.count_nonzero(rendered)) != count * 5
                    or len(core_x) != count
                    or set(quadrant_counts) != {0, 1, 2, 3}
                    or max(quadrant_counts.values())
                    - min(quadrant_counts.values())
                    > 1
                ):
                    raise RuntimeError(
                        f"r18 speck render/stratification drift: {split}/{index}"
                    )
                target_tiers[actual["design_tier"]] += 1
                target_profiles[split][
                    (actual["design_tier"], count, shoulder_fraction)
                ] += 1
                profile = (actual["design_tier"], count, shoulder_fraction)
                if profile in target_geometry[split]:
                    raise RuntimeError(
                        f"r18 duplicate split structural profile: {split}/{index}"
                    )
                target_geometry[split][profile] = (amplitude, separation)
                target_tuples[split].add(canonical_json_bytes(actual))
            preserved_r17[split][candidate_family] = preserved_entries

        if (
            sum(len(variants) for variants in current[split].values()) != 100
            or Counter(
                parameters["design_tier"]
                for variants in current[split].values()
                for parameters in variants
            )
            != expected_total_tiers
            or target_tiers
            != Counter(
                {
                    "clear-reject-candidate": 6,
                    "dominant-reject-candidate": 4,
                }
            )
            or len(target_tuples[split]) != 10
        ):
            raise RuntimeError(f"r18 population/target cardinality drift: {split}")

    if (
        target_profiles["calibration"] != target_profiles["holdout"]
        or target_tuples["calibration"] & target_tuples["holdout"]
        or set(target_geometry["calibration"]) != set(target_geometry["holdout"])
        or any(
            holdout_separation != calibration_separation + 1
            or abs(holdout_amplitude - calibration_amplitude) > 0.100000000001
            for profile, (
                calibration_amplitude,
                calibration_separation,
            ) in target_geometry["calibration"].items()
            for holdout_amplitude, holdout_separation in [
                target_geometry["holdout"][profile]
            ]
        )
    ):
        raise RuntimeError("r18 symmetric split morphology matrix drift")
    if (
        sum(
            len(entries)
            for families in preserved_r17.values()
            for entries in families.values()
        )
        != 180
        or sha256_bytes(canonical_json_bytes(preserved_r17))
        != _R18_PRESERVED_R17_MORPHOLOGY_SHA256
    ):
        raise RuntimeError("r18 preserved r17 morphology SHA drift")
    if (
        sum(
            len(variants)
            for families in full_r18.values()
            for variants in families.values()
        )
        != 200
        or sha256_bytes(canonical_json_bytes(full_r18))
        != _R18_FULL_ARTIFACT_MORPHOLOGY_SHA256
    ):
        raise RuntimeError("r18 full artifact morphology SHA drift")


def _validate_dev_r19_morphology_schedules() -> None:
    """Prove r19 changes identity/audit policy, never artifact morphology."""

    _validate_dev_r18_morphology_schedules()
    splits = ("calibration", "holdout")
    binding = dev_r19_authority_binding()
    if set(binding) != {
        "schedule_revision",
        "duplicate_equivalence_policy_revision",
        "duplicate_equivalence_policy_manifest_sha256",
        "sanitized_r18_basis_sha256",
        "public_payload_commitment_prefix",
        "private_reference_transform_prefix",
        "foundation_offset_lane",
        "foundation_assignment_lane",
        "delta_lane",
        "private_control_id_prefix",
        "artifact_nonce_bases",
        "protocol_zero_nonce_bases",
        "duplicate_audit_nonces",
        "speck_reinforcement_revision",
        "speck_reinforcement_manifest_sha256",
        "predecessor_full_artifact_morphology_sha256",
        "full_artifact_morphology_sha256",
        "exact_morphology_change_count_across_splits",
    }:
        raise RuntimeError("r19 catalog authority schema drift")
    if binding != {
        "schedule_revision": (
            "dev-r19-duplicate-reject-severity-band-equivalence-schedule-v1"
        ),
        "duplicate_equivalence_policy_revision": (
            "dev-r19-reject-ordinal-band-duplicate-equivalence-v1"
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
        "protocol_zero_nonce_bases": {
            "calibration": 1151000,
            "holdout": 1161000,
        },
        "duplicate_audit_nonces": {
            "calibration": [1191000, 1191001, 1191002],
            "holdout": [1201000, 1201001, 1201002],
        },
        "speck_reinforcement_revision": (
            "dev-r18-symmetric-reject-speck-direct-visible-cross-v1"
        ),
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
    }:
        raise RuntimeError("r19 catalog authority value drift")

    basis = _R19_SANITIZED_R18_BASIS
    artifact_pair = basis.get("calibration", {}).get("duplicate_artifact_pair", {})
    short_line_only = {
        "grain_visible": False,
        "tiny_speck_visible": False,
        "microblob_visible": False,
        "short_line_visible": True,
        "parallel_bundle_visible": False,
    }
    if (
        set(basis)
        != {
            "calibration",
            "holdout",
            "population_aggregation_started",
            "numeric_measurement_started",
            "metric_evaluation_started",
            "threshold_search_started",
        }
        or basis["calibration"].get("duplicate_clean_audit_passed") is not True
        or basis["calibration"].get("protocol_zero_audit_passed") is not True
        or set(artifact_pair)
        != {
            "agreed_disposition",
            "agreed_visible_flags",
            "observed_severity_0_to_3_values",
            "only_label_difference",
        }
        or artifact_pair["agreed_disposition"] != "reject"
        or artifact_pair["agreed_visible_flags"] != short_line_only
        or artifact_pair["observed_severity_0_to_3_values"] != [2, 3]
        or artifact_pair["only_label_difference"] != "severity_0_to_3"
        or basis["holdout"]
        != {
            "duplicate_clean_audit_passed": True,
            "duplicate_artifact_audit_passed": True,
            "protocol_zero_audit_passed": True,
        }
        or any(
            basis[field] is not False
            for field in (
                "population_aggregation_started",
                "numeric_measurement_started",
                "metric_evaluation_started",
                "threshold_search_started",
            )
        )
        or sha256_bytes(canonical_json_bytes(basis))
        != _R19_SANITIZED_R18_BASIS_SHA256
    ):
        raise RuntimeError("r19 sanitized r18 basis drift")

    policy = _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST
    pair_equivalence = policy.get("pair_equivalence", {})
    if (
        set(policy)
        != {
            "revision",
            "scope",
            "pair_equivalence",
            "unchanged_semantics",
            "obvious_artifact_required_label",
            "preservation_contract",
        }
        or policy["revision"] != _R19_DUPLICATE_EQUIVALENCE_POLICY_REVISION
        or policy["scope"]
        != {"private_role": "duplicate-audit", "duplicate_audit_group": "artifact"}
        or pair_equivalence.get("disposition")
        != {"comparison": "exact-across-pair", "required_value": "reject"}
        or pair_equivalence.get("visible_flags")
        != {
            "comparison": "exact-across-pair",
            "fields": [
                "grain_visible",
                "tiny_speck_visible",
                "microblob_visible",
                "short_line_visible",
                "parallel_bundle_visible",
            ],
        }
        or pair_equivalence.get("severity_0_to_3")
        != {
            "comparison": "per-member-inclusive-ordinal-band",
            "allowed_values": [2, 3],
            "exact_across_pair_required": False,
        }
        or policy.get("unchanged_semantics")
        != {
            "clean_duplicate_pair_full_semantic_equality_required": True,
            "warning_semantics_unchanged": True,
            "all_non_scoped_duplicate_comparisons_unchanged": True,
        }
        or policy.get("obvious_artifact_required_label")
        != {
            "disposition": "reject",
            "severity_0_to_3_allowed_values": [2, 3],
            "short_line_visible_required": True,
        }
        or policy.get("preservation_contract")
        != {
            "artifact_morphology_change_count_across_splits": 0,
            "full_artifact_morphology_sha256": (
                _R18_FULL_ARTIFACT_MORPHOLOGY_SHA256
            ),
            "tier_cardinality_minimum_metric_threshold_and_rate_contracts_unchanged": (
                True
            ),
            "reference_prequalification_unchanged": True,
            "bilateral_initial_visible_flag_gate_unchanged": True,
            "vision_truth_guaranteed": False,
        }
        or sha256_bytes(canonical_json_bytes(policy))
        != _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST_SHA256
    ):
        raise RuntimeError("r19 duplicate-equivalence policy drift")

    r18_binding = dev_r18_authority_binding()
    current_nonces: dict[str, set[int]] = {}
    predecessor_nonces: dict[str, set[int]] = {}
    for split in splits:
        current_nonces[split] = {
            _R19_ARTIFACT_NONCE_BASES[split] + family_offset + index
            for family_offset in (0, 100, 200, 300, 400)
            for index in range(20)
        } | {
            _R19_PROTOCOL_ZERO_NONCE_BASES[split] + index for index in range(16)
        } | set(_R19_DUPLICATE_AUDIT_NONCES[split])
        predecessor_nonces[split] = {
            r18_binding["artifact_nonce_bases"][split] + family_offset + index
            for family_offset in (0, 100, 200, 300, 400)
            for index in range(20)
        } | {
            r18_binding["protocol_zero_nonce_bases"][split] + index
            for index in range(16)
        } | set(r18_binding["duplicate_audit_nonces"][split])
        if (
            len(current_nonces[split]) != 119
            or current_nonces[split] & predecessor_nonces[split]
        ):
            raise RuntimeError(f"r19 fresh nonce-space drift: {split}")
    if current_nonces["calibration"] & current_nonces["holdout"]:
        raise RuntimeError("r19 calibration/holdout nonce-space overlap")

    def morphology(parameters: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in parameters.items()
            if key not in {"schedule_revision", "condition_nonce"}
        }

    full_r19: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for split in splits:
        variants = _artifact_variants(
            split,
            _schedule_revision_override=_R19_SCHEDULE_REVISION,
            _artifact_nonce_bases_override=_R19_ARTIFACT_NONCE_BASES,
        )
        full_r19[split] = {
            family: [morphology(parameters) for parameters in family_variants]
            for family, family_variants in variants.items()
        }
        if any(
            parameters.get("schedule_revision") != _R19_SCHEDULE_REVISION
            for family_variants in variants.values()
            for parameters in family_variants
        ):
            raise RuntimeError(f"r19 artifact schedule revision drift: {split}")
    if (
        sum(
            len(variants)
            for families in full_r19.values()
            for variants in families.values()
        )
        != 200
        or sha256_bytes(canonical_json_bytes(full_r19))
        != _R18_FULL_ARTIFACT_MORPHOLOGY_SHA256
    ):
        raise RuntimeError("r19 preserved full r18 artifact morphology drift")


def _validate_dev_r20_morphology_schedules() -> None:
    """Prove r20 changes only the obvious duplicate-sentinel construction."""

    _validate_dev_r19_morphology_schedules()
    splits = ("calibration", "holdout")
    binding = dev_r20_authority_binding()
    if set(binding) != {
        "schedule_revision",
        "duplicate_equivalence_policy_revision",
        "duplicate_equivalence_policy_manifest_sha256",
        "sanitized_r19_basis_sha256",
        "duplicate_sentinel_revision",
        "duplicate_sentinel_manifest_sha256",
        "public_payload_commitment_prefix",
        "private_reference_transform_prefix",
        "foundation_offset_lane",
        "foundation_assignment_lane",
        "delta_lane",
        "private_control_id_prefix",
        "artifact_nonce_bases",
        "protocol_zero_nonce_bases",
        "duplicate_audit_nonces",
        "speck_reinforcement_revision",
        "speck_reinforcement_manifest_sha256",
        "predecessor_full_artifact_morphology_sha256",
        "full_artifact_morphology_sha256",
        "exact_morphology_change_count_across_splits",
        "obvious_artifact_duplicate_sentinel_change_count_across_splits",
        "clean_duplicate_construction_change_count_across_splits",
    }:
        raise RuntimeError("r20 catalog authority schema drift")
    if binding != {
        "schedule_revision": (
            "dev-r20-strong-finite-duplicate-short-line-sentinel-schedule-v1"
        ),
        "duplicate_equivalence_policy_revision": (
            "dev-r19-reject-ordinal-band-duplicate-equivalence-v1"
        ),
        "duplicate_equivalence_policy_manifest_sha256": (
            _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST_SHA256
        ),
        "sanitized_r19_basis_sha256": _R20_SANITIZED_R19_BASIS_SHA256,
        "duplicate_sentinel_revision": (
            "dev-r20-keyed-axial-short-line-duplicate-sentinel-v1"
        ),
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
        "protocol_zero_nonce_bases": {
            "calibration": 1251000,
            "holdout": 1261000,
        },
        "duplicate_audit_nonces": {
            "calibration": [1291000, 1291001, 1291002],
            "holdout": [1301000, 1301001, 1301002],
        },
        "speck_reinforcement_revision": (
            "dev-r18-symmetric-reject-speck-direct-visible-cross-v1"
        ),
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
    }:
        raise RuntimeError("r20 catalog authority value drift")

    visible_flag_keys = {
        "grain_visible",
        "tiny_speck_visible",
        "microblob_visible",
        "short_line_visible",
        "parallel_bundle_visible",
    }
    basis = _R20_SANITIZED_R19_BASIS
    if (
        set(basis)
        != {
            "failure_class",
            "calibration",
            "holdout",
            "population_aggregation_started",
            "numeric_measurement_started",
            "metric_evaluation_started",
            "threshold_search_started",
        }
        or basis["failure_class"]
        != "holdout-artifact-duplicate-obvious-short-line-clean-miss"
        or any(
            set(basis[split])
            != {
                "duplicate_clean_audit_passed",
                "duplicate_artifact_pair",
                "protocol_zero_audit_passed",
                "duplicate_audit_passed",
            }
            for split in splits
        )
        or any(
            set(basis[split]["duplicate_artifact_pair"])
            != {
                "member_count",
                "agreed_disposition",
                "agreed_severity_0_to_3",
                "agreed_visible_flags",
                "required_obvious_artifact_contract_passed",
            }
            or set(
                basis[split]["duplicate_artifact_pair"]["agreed_visible_flags"]
            )
            != visible_flag_keys
            for split in splits
        )
        or basis["calibration"]
        != {
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
        }
        or basis["holdout"]
        != {
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
        }
        or any(
            basis[field] is not False
            for field in (
                "population_aggregation_started",
                "numeric_measurement_started",
                "metric_evaluation_started",
                "threshold_search_started",
            )
        )
        or sha256_bytes(canonical_json_bytes(basis))
        != _R20_SANITIZED_R19_BASIS_SHA256
    ):
        raise RuntimeError("r20 sanitized r19 basis drift")

    policy = _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST
    if (
        sha256_bytes(canonical_json_bytes(policy))
        != _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST_SHA256
        or policy["pair_equivalence"]["severity_0_to_3"]
        != {
            "comparison": "per-member-inclusive-ordinal-band",
            "allowed_values": [2, 3],
            "exact_across_pair_required": False,
        }
        or policy["preservation_contract"]["vision_truth_guaranteed"] is not False
    ):
        raise RuntimeError("r20 preserved r19 duplicate policy drift")

    sentinel = _R20_DUPLICATE_SENTINEL_MANIFEST
    if (
        set(sentinel)
        != {
            "revision",
            "scope",
            "construction",
            "raster_contract",
            "pair_equality_contract",
            "zero_key_static_delta_float32_sha256",
            "preservation_contract",
        }
        or sentinel["revision"] != _R20_DUPLICATE_SENTINEL_REVISION
        or sentinel["scope"]
        != {
            "private_role": "duplicate-audit",
            "duplicate_audit_group": "artifact",
        }
        or sentinel["construction"]
        != {
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
            "orientation_contract": (
                "keyed-phase-2-to-1-horizontal-or-vertical-per-quadrant"
            ),
            "placement_contract": "fresh-keyed-split-and-condition-derived",
        }
        or sentinel["raster_contract"]
        != {
            "connected_component_count": 12,
            "pixels_per_component": 72,
            "nonzero_pixel_count": 864,
            "nonzero_values_exact": [12.0],
            "component_shapes_hw": [[3, 24], [24, 3]],
            "each_quadrant_contains_horizontal_and_vertical": True,
            "all_support_inside_one_exact_metric_quadrant_per_component": True,
            "all_support_inside_metric_window": True,
        }
        or sentinel["pair_equality_contract"]
        != {
            "requested_delta_float32_exact": True,
            "decoded_residual_exact": True,
            "metric_values_exact": True,
            "reference_bytes_distinct": True,
            "control_bytes_distinct": True,
            "anonymous_codes_and_control_ids_distinct": True,
        }
        or sentinel["preservation_contract"]
        != {
            "clean_duplicate_construction_unchanged": True,
            "artifact_catalog_morphology_change_count_across_splits": 0,
            "full_artifact_morphology_sha256": (
                _R18_FULL_ARTIFACT_MORPHOLOGY_SHA256
            ),
            "duplicate_equivalence_policy_revision": (
                _R19_DUPLICATE_EQUIVALENCE_POLICY_REVISION
            ),
            "duplicate_equivalence_policy_manifest_sha256": (
                _R19_DUPLICATE_EQUIVALENCE_POLICY_MANIFEST_SHA256
            ),
            "tier_metric_threshold_population_and_rate_contracts_unchanged": True,
            "vision_truth_guaranteed": False,
        }
        or sha256_bytes(canonical_json_bytes(sentinel))
        != _R20_DUPLICATE_SENTINEL_MANIFEST_SHA256
    ):
        raise RuntimeError("r20 duplicate sentinel manifest drift")

    zero_key_deltas = {
        split: _r20_zero_key_duplicate_sentinel_delta(split) for split in splits
    }
    zero_key_hashes = {
        split: sha256_bytes(
            np.ascontiguousarray(delta, dtype="<f4").tobytes()
        )
        for split, delta in zero_key_deltas.items()
    }
    if (
        zero_key_hashes != sentinel["zero_key_static_delta_float32_sha256"]
        or zero_key_hashes["calibration"] == zero_key_hashes["holdout"]
        or np.array_equal(
            zero_key_deltas["calibration"], zero_key_deltas["holdout"]
        )
    ):
        raise RuntimeError("r20 duplicate sentinel split-keyed static vector drift")

    r19_binding = dev_r19_authority_binding()
    current_nonces: dict[str, set[int]] = {}
    predecessor_nonces: dict[str, set[int]] = {}
    for split in splits:
        current_nonces[split] = {
            _ARTIFACT_NONCE_BASES[split] + family_offset + index
            for family_offset in (0, 100, 200, 300, 400)
            for index in range(20)
        } | {
            _PROTOCOL_ZERO_NONCE_BASES[split] + index for index in range(16)
        } | set(_DUPLICATE_AUDIT_NONCES[split])
        predecessor_nonces[split] = {
            r19_binding["artifact_nonce_bases"][split] + family_offset + index
            for family_offset in (0, 100, 200, 300, 400)
            for index in range(20)
        } | {
            r19_binding["protocol_zero_nonce_bases"][split] + index
            for index in range(16)
        } | set(r19_binding["duplicate_audit_nonces"][split])
        if (
            len(current_nonces[split]) != 119
            or current_nonces[split] & predecessor_nonces[split]
        ):
            raise RuntimeError(f"r20 fresh nonce-space drift: {split}")
    if current_nonces["calibration"] & current_nonces["holdout"]:
        raise RuntimeError("r20 calibration/holdout nonce-space overlap")

    def morphology(parameters: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in parameters.items()
            if key not in {"schedule_revision", "condition_nonce"}
        }

    full_r20: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for split in splits:
        variants = _artifact_variants(split)
        full_r20[split] = {
            family: [morphology(parameters) for parameters in family_variants]
            for family, family_variants in variants.items()
        }
        if any(
            parameters.get("schedule_revision") != _SCHEDULE_REVISION
            for family_variants in variants.values()
            for parameters in family_variants
        ):
            raise RuntimeError(f"r20 artifact schedule revision drift: {split}")
    if (
        sum(
            len(variants)
            for families in full_r20.values()
            for variants in families.values()
        )
        != 200
        or sha256_bytes(canonical_json_bytes(full_r20))
        != _R18_FULL_ARTIFACT_MORPHOLOGY_SHA256
    ):
        raise RuntimeError("r20 preserved full r19 artifact morphology drift")


def _encode_png(values: np.ndarray, compression: int) -> bytes:
    stream = io.BytesIO()
    Image.fromarray(values.astype(np.uint8), mode="L").save(
        stream, format="PNG", compress_level=compression, optimize=False
    )
    return stream.getvalue()


def _expected_controls_bounded(
    spec: dict[str, Any], split: str, key: bytes
) -> list[ExpectedControl]:
    if split not in {"calibration", "holdout"}:
        raise ValueError("invalid split")
    height, width = int(spec["canvas"]["height"]), int(spec["canvas"]["width"])
    if (width, height) != (512, 384):
        raise RuntimeError("r6 foundation canvas contract drift")
    metric_window_xywh = tuple(
        int(value) for value in spec["canvas"]["metric_window"]["xywh"]
    )
    if metric_window_xywh != (128, 96, 256, 192):
        raise RuntimeError("r6 exact metric-window geometry drift")
    bank = _foundation_bank()
    prefix = spec["blind_derivation"]["seed_message_prefix"]
    code_prefix = spec["blind_derivation"]["code_message_prefix"]
    public_nonce = spec["splits"][split]["public_nonce"]
    compression = int(spec["canvas"]["png_compress_level"])
    controls: list[ExpectedControl] = []

    def emit(
        *,
        private_role: str,
        family: str,
        variant_index: int,
        replicate: int,
        polarity: int,
        parameters: dict[str, Any],
        duplicate_audit_group: str | None,
        render_family: str,
    ) -> None:
        cluster_seed_identity = {
            "split": split,
            "public_nonce": public_nonce,
            "private_role": private_role,
            "family": family,
            "variant_index": variant_index,
            "parameters": parameters,
            "duplicate_audit_group": duplicate_audit_group,
        }
        if private_role in {"artifact", "protocol-zero"}:
            assignment_scope = {
                "split": split,
                "public_nonce": public_nonce,
                "private_role": private_role,
                "family": family,
            }
            foundation_offset = int.from_bytes(
                _hmac_material(key, prefix, assignment_scope, _FOUNDATION_OFFSET_LANE)[
                    :8
                ],
                "big",
            ) % len(_FOUNDATIONS)
            foundation_index = (variant_index + foundation_offset) % len(_FOUNDATIONS)
        else:
            foundation_index = int.from_bytes(
                _hmac_material(
                    key, prefix, cluster_seed_identity, _FOUNDATION_ASSIGNMENT_LANE
                )[:8],
                "big",
            ) % len(_FOUNDATIONS)
        foundation_id = _FOUNDATIONS[foundation_index][0]
        cluster_identity = {
            **cluster_seed_identity,
            "foundation_id": foundation_id,
        }
        delta_seed = int.from_bytes(
            _hmac_material(key, prefix, cluster_identity, _DELTA_LANE), "big"
        )
        unsigned = _render_unsigned_delta(
            render_family,
            parameters,
            np.random.default_rng(delta_seed),
            height,
            width,
            metric_window_xywh,
        ).astype(np.float32)
        requested = (unsigned * np.float32(polarity)).astype(np.float32)
        reference_float = bank[foundation_id]
        reference_identity = {
            **cluster_identity,
            "replicate": replicate,
            "polarity": polarity,
        }
        reference = _private_reference_transform(
            reference_float,
            key=key,
            prefix=prefix,
            identity=reference_identity,
            settings=spec["control_catalog_authority"]["private_reference_transform"],
        )
        encoded_requested = np.rint(requested).astype(np.int16)
        encoded_control = reference.astype(np.int16) + encoded_requested
        if np.any(encoded_control < 0) or np.any(encoded_control > 255):
            raise RuntimeError(
                "r6 encoded control exceeded the luminance safety margin"
            )
        control = encoded_control.astype(np.uint8)
        if private_role == "protocol-zero" or (
            private_role == "duplicate-audit" and duplicate_audit_group == "clean"
        ):
            if np.any(requested != 0) or not np.array_equal(control, reference):
                raise RuntimeError("r6 zero protocol control/reference drift")
        else:
            if not np.any(requested != 0) or np.array_equal(control, reference):
                raise RuntimeError(
                    "r6 nonzero artifact collapsed during encoding: "
                    f"{split}/{family}/v{variant_index}/r{replicate}/p{polarity}"
                )
        if render_family in {
            "artifact-speck",
            "artifact-microblob",
            "artifact-short-dash",
            "artifact-parallel-bundle",
            "duplicate-obvious-short-line-sentinel",
        }:
            left, top, window_width, window_height = metric_window_xywh
            outside = requested.copy()
            outside[top : top + window_height, left : left + window_width] = 0
            if np.any(outside != 0):
                raise RuntimeError(f"{split}/{render_family} escaped metric window")
        reference_png = _encode_png(reference, compression)
        control_png = _encode_png(control, compression)
        identity = {
            **cluster_identity,
            "replicate": replicate,
            "polarity": polarity,
        }
        identity_bytes = canonical_json_bytes(identity)
        anonymous_code = blind_hmac(
            key, code_prefix.encode("ascii") + identity_bytes
        ).hex()[: int(spec["blind_derivation"]["opaque_code_hex_characters"])]
        control_id = blind_hmac(key, _PRIVATE_CONTROL_ID_PREFIX + identity_bytes).hex()[
            :24
        ]
        condition_cluster_id = blind_hmac(
            key,
            spec["independent_condition_clusters"]["message_prefix"].encode("ascii")
            + canonical_json_bytes(cluster_identity),
        ).hex()[:24]
        reference_sha256 = sha256_bytes(reference_png)
        control_sha256 = sha256_bytes(control_png)
        delta_float32_sha256 = sha256_bytes(
            np.ascontiguousarray(requested, dtype="<f4").tobytes()
        )
        controls.append(
            ExpectedControl(
                family=family,
                private_role=private_role,
                foundation_id=foundation_id,
                duplicate_audit_group=duplicate_audit_group,
                control_id=control_id,
                condition_cluster_id=condition_cluster_id,
                variant_index=variant_index,
                replicate=replicate,
                polarity=polarity,
                parameters=json.loads(json.dumps(parameters)),
                anonymous_code=anonymous_code,
                reference=reference,
                requested_delta=requested,
                control=control,
                reference_png=reference_png,
                control_png=control_png,
                reference_sha256=reference_sha256,
                control_sha256=control_sha256,
                delta_float32_sha256=delta_float32_sha256,
                control_commitment=_public_payload_commitment(
                    key, anonymous_code, "control", control_sha256
                ),
                reference_commitment=_public_payload_commitment(
                    key, anonymous_code, "reference", reference_sha256
                ),
                delta_commitment=_public_payload_commitment(
                    key, anonymous_code, "delta", delta_float32_sha256
                ),
            )
        )

    _validate_dev_r20_morphology_schedules()
    artifact_variants = _artifact_variants(split)
    for family, variants in artifact_variants.items():
        for variant_index, parameters in enumerate(variants):
            for polarity in (-1, 1):
                emit(
                    private_role="artifact",
                    family=family,
                    variant_index=variant_index,
                    replicate=0,
                    polarity=polarity,
                    parameters=parameters,
                    duplicate_audit_group=None,
                    render_family=family,
                )

    zero_nonce_base = _PROTOCOL_ZERO_NONCE_BASES[split]
    for variant_index in range(16):
        emit(
            private_role="protocol-zero",
            family="protocol-zero",
            variant_index=variant_index,
            replicate=0,
            polarity=1,
            parameters={
                "schedule_revision": _SCHEDULE_REVISION,
                "protocol_nonce": zero_nonce_base + variant_index,
            },
            duplicate_audit_group=None,
            render_family="protocol-zero",
        )

    clean_audit_nonce, artifact_audit_nonce, artifact_condition_nonce = (
        _DUPLICATE_AUDIT_NONCES[split]
    )
    clean_audit_parameters = {
        "schedule_revision": _SCHEDULE_REVISION,
        "audit_nonce": clean_audit_nonce,
        "audit_kind": "clean-isomorphic-replicate",
    }
    artifact_audit_parameters = _r20_obvious_artifact_duplicate_parameters(split)
    if (
        artifact_audit_parameters["audit_nonce"] != artifact_audit_nonce
        or artifact_audit_parameters["condition_nonce"]
        != artifact_condition_nonce
    ):
        raise RuntimeError(f"r20 duplicate sentinel nonce binding drift: {split}")
    for replicate in range(2):
        emit(
            private_role="duplicate-audit",
            family="duplicate-audit",
            variant_index=0,
            replicate=replicate,
            polarity=1,
            parameters=clean_audit_parameters,
            duplicate_audit_group="clean",
            render_family="protocol-zero",
        )
        emit(
            private_role="duplicate-audit",
            family="duplicate-audit",
            variant_index=1,
            replicate=replicate,
            polarity=1,
            parameters=artifact_audit_parameters,
            duplicate_audit_group="artifact",
            render_family="duplicate-obvious-short-line-sentinel",
        )

    if len(controls) != 220:
        raise RuntimeError("r6 bounded corpus record count drift")
    role_counts = Counter(control.private_role for control in controls)
    if role_counts != Counter(
        {"artifact": 200, "protocol-zero": 16, "duplicate-audit": 4}
    ):
        raise RuntimeError("r6 private-role cardinality drift")
    if {control.foundation_id for control in controls} - {"v15", "v16", "v17"}:
        raise RuntimeError("r6 rejected foundation entered corpus")
    zero_foundations = {
        control.foundation_id
        for control in controls
        if control.private_role == "protocol-zero"
    }
    if zero_foundations != {"v15", "v16", "v17"}:
        raise RuntimeError("r6 protocol-zero foundation coverage drift")
    codes = [control.anonymous_code for control in controls]
    control_ids = [control.control_id for control in controls]
    if len(codes) != len(set(codes)) or len(control_ids) != len(set(control_ids)):
        raise RuntimeError("r6 private identity collision")
    if len({control.control_sha256 for control in controls}) != len(controls):
        raise RuntimeError("r6 public control payload equality leak")
    if len({control.reference_sha256 for control in controls}) != len(controls):
        raise RuntimeError("r6 private reference-instance cardinality drift")
    for view in spec["contact_sheets"]["views"]:
        left, top, view_width, view_height = [
            int(value) for value in view["source_crop_xywh"]
        ]
        view_hashes = {
            sha256_bytes(
                np.ascontiguousarray(
                    control.control[top : top + view_height, left : left + view_width]
                ).tobytes()
            )
            for control in controls
        }
        if len(view_hashes) != len(controls):
            raise RuntimeError(
                f"r6 public contact-sheet panel equality leak: {view['id']}"
            )

    artifact_clusters: dict[str, list[ExpectedControl]] = {}
    for control in controls:
        if control.private_role == "artifact":
            artifact_clusters.setdefault(control.condition_cluster_id, []).append(
                control
            )
    if len(artifact_clusters) != 100:
        raise RuntimeError("r6 artifact cluster cardinality drift")
    family_clusters = Counter(group[0].family for group in artifact_clusters.values())
    if set(family_clusters.values()) != {20} or len(family_clusters) != 5:
        raise RuntimeError("r6 artifact family cluster cardinality drift")
    for cluster_id, pair in artifact_clusters.items():
        if len(pair) != 2 or {item.polarity for item in pair} != {-1, 1}:
            raise RuntimeError(f"r6 polarity pair drift: {cluster_id}")
        dark = next(item for item in pair if item.polarity == -1)
        light = next(item for item in pair if item.polarity == 1)
        if dark.reference_png == light.reference_png or not np.array_equal(
            dark.requested_delta, -light.requested_delta
        ):
            raise RuntimeError(f"r6 polarity render drift: {cluster_id}")
        dark_encoded = dark.control.astype(np.int16) - dark.reference.astype(np.int16)
        light_encoded = light.control.astype(np.int16) - light.reference.astype(
            np.int16
        )
        if not np.array_equal(dark_encoded, -light_encoded):
            raise RuntimeError(f"r6 encoded polarity symmetry drift: {cluster_id}")

    for group_name in ("clean", "artifact"):
        pair = [
            control
            for control in controls
            if control.duplicate_audit_group == group_name
        ]
        if (
            len(pair) != 2
            or len({item.anonymous_code for item in pair}) != 2
            or len({item.control_id for item in pair}) != 2
        ):
            raise RuntimeError(f"r6 duplicate audit membership drift: {group_name}")
        left, right = pair
        if (
            left.condition_cluster_id != right.condition_cluster_id
            or left.foundation_id != right.foundation_id
            or left.delta_float32_sha256 != right.delta_float32_sha256
            or not np.array_equal(left.requested_delta, right.requested_delta)
            or left.reference_png == right.reference_png
            or left.control_png == right.control_png
        ):
            raise RuntimeError(f"r6 semantic replicate audit drift: {group_name}")
        left_encoded = left.control.astype(np.int16) - left.reference.astype(np.int16)
        right_encoded = right.control.astype(np.int16) - right.reference.astype(
            np.int16
        )
        if not np.array_equal(left_encoded, right_encoded):
            raise RuntimeError(
                f"r6 semantic replicate encoded-residual drift: {group_name}"
            )
        if group_name == "clean":
            if (
                left.control_png != left.reference_png
                or right.control_png != right.reference_png
            ):
                raise RuntimeError("r6 clean semantic replicate is not exact-zero")
        elif (
            left.control_png == left.reference_png
            or right.control_png == right.reference_png
        ):
            raise RuntimeError(
                "r6 artifact semantic replicate collapsed during encoding"
            )
        if group_name == "artifact":
            expected_parameters = _r20_obvious_artifact_duplicate_parameters(split)
            requested_nonzero = left.requested_delta[
                left.requested_delta != np.float32(0.0)
            ]
            if (
                left.parameters != expected_parameters
                or right.parameters != expected_parameters
                or int(requested_nonzero.size) != 864
                or np.unique(requested_nonzero).tolist() != [12.0]
                or not np.array_equal(
                    left_encoded,
                    np.rint(left.requested_delta).astype(np.int16),
                )
                or not np.array_equal(
                    right_encoded,
                    np.rint(right.requested_delta).astype(np.int16),
                )
            ):
                raise RuntimeError(
                    "r20 obvious duplicate strong finite payload drift"
                )
    return controls


def expected_controls(
    spec: dict[str, Any], split: str, key: bytes
) -> list[ExpectedControl]:
    return _expected_controls_bounded(spec, split, key)


def contact_sheet_pages(
    spec: dict[str, Any], split: str, controls: list[ExpectedControl]
) -> list[ContactSheetPage]:
    settings = spec["contact_sheets"]
    validate_contact_sheet_view_partition(
        settings, spec["canvas"]["metric_window"]["xywh"]
    )
    metric_window = tuple(
        int(value) for value in spec["canvas"]["metric_window"]["xywh"]
    )
    expected_count = int(settings["expected_controls_per_split"])
    if len(controls) != expected_count:
        raise RuntimeError(f"{split} control count must be exactly {expected_count}")
    by_code = {control.anonymous_code: control for control in controls}
    if len(by_code) != len(controls):
        raise RuntimeError("contact-sheet opaque code collision")
    codes = sorted(by_code)
    columns = int(settings["columns"])
    rows = int(settings["rows_per_page"])
    per_page = columns * rows
    panel_width, panel_height = [int(value) for value in settings["panel_dimensions"]]
    label_height = int(settings["label_height"])
    sheet_width, sheet_height = [int(value) for value in settings["sheet_dimensions"]]
    if sheet_width != columns * panel_width or sheet_height != rows * (
        panel_height + label_height
    ):
        raise RuntimeError("contact-sheet dimensions disagree with panel grid")
    label_x, label_y = [int(value) for value in settings["label_origin_in_slot"]]
    panel_x, panel_y = [int(value) for value in settings["panel_origin_in_slot"]]
    pages: list[ContactSheetPage] = []
    expected_view_ids: set[str] = set()
    for view in settings["views"]:
        view_id = str(view["id"])
        if not view_id or view_id in expected_view_ids:
            raise RuntimeError(
                "contact-sheet view identifiers must be unique/non-empty"
            )
        expected_view_ids.add(view_id)
        scale = int(view["scale_percent"])
        crop_xywh = tuple(int(value) for value in view["source_crop_xywh"])
        left, top, crop_width, crop_height = crop_xywh
        integer_scale = int(scale) // 100
        if (
            int(scale) % 100
            or crop_width * integer_scale != panel_width
            or crop_height * integer_scale != panel_height
        ):
            raise RuntimeError("contact-sheet scale/crop does not exactly fill panel")
        if (
            left < 0
            or top < 0
            or crop_width <= 0
            or crop_height <= 0
            or left + crop_width > int(spec["canvas"]["width"])
            or top + crop_height > int(spec["canvas"]["height"])
        ):
            raise RuntimeError(f"contact-sheet view {view_id} escapes the canvas")
        if view_id == "full-200" and crop_xywh != metric_window:
            raise RuntimeError("full-200 sheet is not the exact metric window")
        for page_index, start in enumerate(range(0, len(codes), per_page), 1):
            item_codes = tuple(codes[start : start + per_page])
            sheet = np.full(
                (sheet_height, sheet_width),
                int(settings["sheet_background_l"]),
                dtype=np.uint8,
            )
            for slot, code in enumerate(item_codes):
                source = by_code[code].control
                crop = source[top : top + crop_height, left : left + crop_width]
                display = np.repeat(
                    np.repeat(crop, integer_scale, axis=0), integer_scale, axis=1
                )
                column, row = slot % columns, slot // columns
                slot_x = column * panel_width
                slot_y = row * (panel_height + label_height)
                x, y = slot_x + panel_x, slot_y + panel_y
                sheet[y : y + panel_height, x : x + panel_width] = display
                _draw_hex_label(
                    sheet,
                    code,
                    slot_x + label_x,
                    slot_y + label_y,
                    int(settings["label_fill_l"]),
                )
            payload = _encode_png(sheet, int(spec["canvas"]["png_compress_level"]))
            relative = (
                f"controls/{split}/contact-sheets/{view_id}-page-{page_index:03d}.png"
            )
            pages.append(
                ContactSheetPage(
                    view_id,
                    int(scale),
                    crop_xywh,
                    page_index,
                    relative,
                    item_codes,
                    payload,
                    sha256_bytes(payload),
                )
            )
    expected_pages = int(settings["expected_pages_per_split"])
    if len(pages) != expected_pages:
        raise RuntimeError(
            f"{split} must have exactly {expected_pages} contact-sheet pages"
        )
    for view_id in expected_view_ids:
        if sum(page.view_id == view_id for page in pages) != int(
            settings["expected_pages_per_view"]
        ):
            raise RuntimeError(f"{split}/{view_id} contact-sheet page count drift")
    for page_index in range(1, int(settings["expected_pages_per_view"]) + 1):
        item_bundles = {
            page.item_codes for page in pages if page.page_index == page_index
        }
        if len(item_bundles) != 1:
            raise RuntimeError(
                f"{split}/page-{page_index:03d} view item-code order drift"
            )
    return pages


def validate_manifest_public_bindings(
    manifest: dict[str, Any], expected: list[ExpectedControl]
) -> None:
    expected_counter = Counter(control.public_binding_tuple for control in expected)
    actual_counter = Counter(
        (
            record["anonymous_code"],
            record["control_commitment"],
            record["reference_commitment"],
            record["delta_commitment"],
        )
        for record in manifest["records"]
    )
    if expected_counter != actual_counter or any(
        count != 1 for count in expected_counter.values()
    ):
        raise RuntimeError("secret-derived exact public binding tuple multiset drift")


def bind_manifest_to_expected(
    manifest: dict[str, Any], spec: dict[str, Any], split: str, key: bytes
) -> dict[tuple[str, str, str, str], ExpectedControl]:
    expected = expected_controls(spec, split, key)
    validate_manifest_public_bindings(manifest, expected)
    expected_codes = {control.anonymous_code for control in expected}
    if expected_codes != {record["anonymous_code"] for record in manifest["records"]}:
        raise RuntimeError("secret-derived opaque code set drift")
    return {control.public_binding_tuple: control for control in expected}
