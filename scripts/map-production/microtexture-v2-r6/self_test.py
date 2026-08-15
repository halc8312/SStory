"""Fast deterministic self-tests for the frozen r6 authority implementation."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import tempfile
import types
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

import calibration_harness
import common
import development_probe
import generate_controls
from calibration_harness import _cluster_macro_rate, _threshold_candidates
from common import write_json_exclusive
from control_catalog import (
    _ARTIFACT_NONCE_BASES,
    _CALIBRATION_MICROBLOB_CLEAR_REJECT_ANCHORS,
    _DELTA_LANE,
    _DUPLICATE_AUDIT_NONCES,
    _FOUNDATION_ASSIGNMENT_LANE,
    _FOUNDATION_OFFSET_LANE,
    _PRIVATE_CONTROL_ID_PREFIX,
    _PRIVATE_REFERENCE_TRANSFORM_PREFIX,
    _PROTOCOL_ZERO_NONCE_BASES,
    _PUBLIC_PAYLOAD_COMMITMENT_PREFIX,
    _SCHEDULE_REVISION,
    _WARNING_ACCEPTANCE_ANCHORS,
    _artifact_variants,
    _draw_hex_label,
    _render_unsigned_delta,
    _stratified_separated_integer_positions,
    contact_sheet_pages,
    expected_controls,
)
from metrics_v2_r6 import (
    METRIC_FIELDS,
    SCORE_FIELDS,
    _finite_line_metrics,
    _parallel_metrics,
    _spot_metrics,
    measure,
    recompute_branch_scores,
)


DEV_R7_FAILURE_AUDIT_RELATIVE = (
    "world/map-production/qa/microtexture-v2-r6-dev-r7-development-failure.json"
)
DEV_R7_FAILURE_AUDIT_SHA256 = (
    "00ab198c5e0be28775436d22927e9bd8523304f41e2c310d6e81c0cf2ea7131f"
)
DEV_R8_FAILURE_AUDIT_RELATIVE = (
    "world/map-production/qa/microtexture-v2-r6-dev-r8-development-failure.json"
)
DEV_R8_FAILURE_AUDIT_SHA256 = (
    "39c7472f8018cbbf25cbd029cb915c43696a07b6c52e8e586e02fe5a99dbc07d"
)
DEV_R9_FAILURE_AUDIT_RELATIVE = (
    "world/map-production/qa/microtexture-v2-r6-dev-r9-development-failure.json"
)
DEV_R9_FAILURE_AUDIT_SHA256 = (
    "10c832fb2b7131b942cad54c7412672a98a2f0401db1aae31ce2b1383952f202"
)
DEV_R10_FAILURE_AUDIT_RELATIVE = (
    "world/map-production/qa/microtexture-v2-r6-dev-r10-development-failure.json"
)
DEV_R10_FAILURE_AUDIT_SHA256 = (
    "9e5533453e7ec25bed75b54a67cb63129329aca392c1c7db4bf60d9c0a7393fa"
)
DEV_R11_FAILURE_AUDIT_RELATIVE = (
    "world/map-production/qa/microtexture-v2-r6-dev-r11-development-failure.json"
)
DEV_R11_FAILURE_AUDIT_SHA256 = (
    "a1dcf2354ec6b0bc81ae89f75eadc11f1a522be73de66032f94048d1a411ef04"
)
DEV_R12_FAILURE_AUDIT_RELATIVE = (
    "world/map-production/qa/microtexture-v2-r6-dev-r12-development-failure.json"
)
DEV_R12_FAILURE_AUDIT_SHA256 = (
    "d972da0d73d3e9b057a37941b186e0b7b16eaefe1e18a28ed3a7f9bbdadb60f6"
)
DEV_R13_FAILURE_AUDIT_RELATIVE = (
    "world/map-production/qa/microtexture-v2-r6-dev-r13-development-failure.json"
)
DEV_R13_FAILURE_AUDIT_SHA256 = (
    "2fbc67f05b3b5ec065f79e7f9118fd5d06b5966dd78c95da191c37761f215634"
)
DEV_R14_FAILURE_AUDIT_RELATIVE = (
    "world/map-production/qa/microtexture-v2-r6-dev-r14-development-failure.json"
)
DEV_R14_FAILURE_AUDIT_SHA256 = (
    "79acad1ef7972293e2697bd4c81edcc2c6ec017b4121e6609b94b95391c25476"
)


def _expected_warning_acceptance_anchors() -> dict[
    str, dict[str, dict[int, dict[str, object]]]
]:
    def speck(amplitude: float, separation: int) -> dict[str, object]:
        return {
            "design_tier": "warning-candidate",
            "diameter_px": 1,
            "amplitude_l": amplitude,
            "count_in_metric_window": 4,
            "shoulder_fraction": 0.05,
            "minimum_separation_px": separation,
        }

    def microblob(
        diameter: int,
        amplitude: float,
        support_radius: int,
        separation: int,
    ) -> dict[str, object]:
        return {
            "design_tier": "warning-candidate",
            "diameter_px": diameter,
            "amplitude_l": amplitude,
            "count_in_metric_window": 2,
            "support_radius_px": support_radius,
            "minimum_separation_px": separation,
        }

    def short_dash(
        length: int, amplitude: float, separation: int
    ) -> dict[str, object]:
        return {
            "design_tier": "warning-candidate",
            "length_px": length,
            "width_px": 1,
            "amplitude_l": amplitude,
            "count_in_metric_window": 1,
            "minimum_separation_px": separation,
        }

    def parallel_bundle(
        length: int,
        spacing: int,
        amplitude: float,
        separation: int,
    ) -> dict[str, object]:
        return {
            "design_tier": "warning-candidate",
            "length_px": length,
            "width_px": 1,
            "spacing_px": spacing,
            "amplitude_l": amplitude,
            "pair_count_in_metric_window": 1,
            "minimum_bundle_separation_px": separation,
        }

    return {
        "calibration": {
            "artifact-speck": {
                2: speck(7.1, 12),
                10: speck(7.3, 14),
                11: speck(7.7, 16),
                18: speck(7.9, 18),
            },
            "artifact-microblob": {
                4: microblob(5, 6.8, 5, 14),
                5: microblob(6, 6.6, 5, 14),
                12: microblob(7, 6.4, 6, 16),
                14: microblob(8, 6.2, 7, 18),
            },
            "artifact-short-dash": {
                6: short_dash(8, 7.2, 12),
                8: short_dash(10, 7.0, 14),
                17: short_dash(12, 6.8, 16),
                19: short_dash(14, 6.6, 18),
            },
            "artifact-parallel-bundle": {
                0: parallel_bundle(8, 4, 7.2, 12),
                2: parallel_bundle(10, 4, 7.0, 14),
                11: parallel_bundle(12, 4, 6.8, 16),
                13: parallel_bundle(12, 6, 6.6, 16),
            },
        },
        "holdout": {
            "artifact-speck": {
                0: speck(7.2, 13),
                5: speck(7.4, 15),
                12: speck(7.6, 17),
                16: speck(7.8, 19),
            },
            "artifact-microblob": {
                6: microblob(5, 6.9, 5, 14),
                10: microblob(6, 6.7, 5, 14),
                15: microblob(7, 6.3, 6, 16),
                17: microblob(8, 6.1, 7, 18),
            },
            "artifact-short-dash": {
                0: short_dash(8, 7.3, 12),
                4: short_dash(10, 7.1, 14),
                9: short_dash(12, 6.9, 16),
                11: short_dash(14, 6.7, 18),
            },
            "artifact-parallel-bundle": {
                3: parallel_bundle(8, 4, 7.3, 12),
                5: parallel_bundle(10, 6, 7.1, 14),
                15: parallel_bundle(12, 4, 6.9, 16),
                19: parallel_bundle(12, 6, 6.7, 16),
            },
        },
    }


def _warning_acceptance_anchor_manifest(
    anchors: dict[str, dict[str, dict[int, dict[str, object]]]],
) -> dict[str, object]:
    return {
        "revision": "dev-r14-quantized-direct-visible-sparse-warning-v1",
        "splits": {
            split: {
                family: [
                    {"variant_index": index, "parameters": parameters}
                    for index, parameters in sorted(rows.items())
                ]
                for family, rows in families.items()
            }
            for split, families in anchors.items()
        },
    }


def _expected_calibration_microblob_clear_reject_anchors() -> dict[
    int, dict[str, object]
]:
    def microblob(
        diameter: int,
        amplitude: float,
        count: int,
        support_radius: int,
        separation: int,
    ) -> dict[str, object]:
        return {
            "design_tier": "clear-reject-candidate",
            "diameter_px": diameter,
            "amplitude_l": amplitude,
            "count_in_metric_window": count,
            "support_radius_px": support_radius,
            "minimum_separation_px": separation,
        }

    return {
        1: microblob(4, 11.6, 64, 2, 13),
        2: microblob(4, 11.8, 64, 2, 14),
        9: microblob(4, 11.4, 64, 2, 12),
        13: microblob(6, 11.6, 44, 3, 16),
        16: microblob(5, 12.0, 52, 3, 15),
        17: microblob(6, 11.8, 44, 3, 17),
        18: microblob(6, 11.4, 44, 3, 15),
    }


def _calibration_microblob_clear_reject_anchor_manifest(
    anchors: dict[int, dict[str, object]],
) -> dict[str, object]:
    return {
        "revision": "dev-r15-calibration-quantized-microblob-reject-v1",
        "split": "calibration",
        "family": "artifact-microblob",
        "entries": [
            {"variant_index": index, "parameters": parameters}
            for index, parameters in sorted(anchors.items())
        ],
    }


def _vision_item(
    code: str,
    disposition: str,
    *,
    visible_field: str | None = None,
) -> dict[str, object]:
    evidence: dict[str, list[str]] = {flag: [] for flag in ("g", "t", "b", "l", "p")}
    item: dict[str, object] = {
        "anonymous_code": code,
        "disposition": disposition,
        "grain_visible": False,
        "tiny_speck_visible": False,
        "microblob_visible": False,
        "short_line_visible": False,
        "parallel_bundle_visible": False,
        "severity_0_to_3": {"clean": 0, "warning": 1, "reject": 2}[disposition],
        "reviewed_at_200_percent": True,
        "reviewed_at_all_400_percent_quadrants": True,
        "notes": "ev3:g=-;t=-;b=-;l=-;p=-",
    }
    if visible_field is not None:
        item[visible_field] = True
        flag = {
            "grain_visible": "g",
            "tiny_speck_visible": "t",
            "microblob_visible": "b",
            "short_line_visible": "l",
            "parallel_bundle_visible": "p",
        }[visible_field]
        evidence[flag] = ["NW-R2C2-N01"]
        if flag == "t":
            evidence[flag] = [
                "NW-R2C2-N01",
                "NE-R2C2-N01",
                "SE-R2C2-N01",
            ]
        if flag == "p":
            item["short_line_visible"] = True
            evidence["l"] = ["NW-R2C2-N01"]
        item["notes"] = "ev3:" + ";".join(
            f"{name}=" + (",".join(evidence[name]) if evidence[name] else "-")
            for name in ("g", "t", "b", "l", "p")
        )
    return item


def _vision_payload(
    split: str,
    items: list[dict[str, object]],
    manifest: dict[str, object],
    manifest_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    return {
        "artifact": "microtexture-v2-r6-root-vision-labels",
        "schema_version": "microtexture-v2-r6-root-vision-labels/2",
        "split": split,
        "spec_sha256": common.SPEC_SHA256,
        "manifest_sha256": manifest_sha,
        "implementation_bindings_sha256": state["implementation_bindings_sha256"],
        "blind_key_commitment": state["blind_key_commitment"],
        "runtime": manifest["runtime"],
        "contact_sheet_bundle": manifest["contact_sheet_bundle"],
        "reviewer": "Root",
        "items": items,
    }


def _private_label_audit_fixture() -> tuple[
    dict[str, dict[str, object]], list[dict[str, object]]
]:
    labels: dict[str, dict[str, object]] = {}
    rows: list[dict[str, object]] = []
    for index in range(220):
        code = f"{index:024x}"
        if index < 200:
            role, group = "artifact", None
            label = _vision_item(code, "clean")
        elif index < 216:
            role, group = "protocol-zero", None
            label = _vision_item(code, "clean")
        elif index < 218:
            role, group = "duplicate-audit", "clean"
            label = _vision_item(code, "clean")
        else:
            role, group = "duplicate-audit", "artifact"
            label = _vision_item(code, "reject", visible_field="short_line_visible")
        labels[code] = label
        rows.append(
            {
                "anonymous_code": code,
                "private_role": role,
                "duplicate_audit_group": group,
            }
        )
    return labels, rows


def _development_generation_documents(
    spec: dict[str, object],
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    bindings_sha = hashlib.sha256(
        (development_probe.CODE_ROOT / "implementation-bindings.json").read_bytes()
    ).hexdigest()
    state: dict[str, object] = {
        "development_edition": "r15",
        "spec_sha256": common.SPEC_SHA256,
        "public_nonces": development_probe._public_nonces(spec),
        "implementation_bindings_sha256": bindings_sha,
        "blind_key_commitment": "b" * 64,
        "captured_git_head": "c" * 40,
        "runtime": {"test_fixture": True},
    }
    boundary: dict[str, object] = {
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
    start: dict[str, object] = {
        "artifact": "microtexture-v2-r6-development-generation-start",
        "schema_version": "microtexture-v2-r6-development-generation-start/1",
        "authority": False,
        "formal_use_forbidden": True,
        "one_shot_consumed": True,
        "started_at": "2026-07-29T00:00:00Z",
        "development_boundary_sha256": hashlib.sha256(
            development_probe._json_bytes(boundary)
        ).hexdigest(),
        "state": state,
    }
    receipts: list[dict[str, object]] = []
    for split, fill in (("calibration", "1"), ("holdout", "2")):
        prefix = f"public/{split}"
        receipts.append(
            {
                "split": split,
                "record_count": 220,
                "contact_sheet_count": 185,
                "review_board_count": 37,
                "manifest_path": f"{prefix}/manifest.dev.json",
                "manifest_sha256": fill * 64,
                "blank_labels_path": f"{prefix}/labels.blank.dev.json",
                "blank_labels_sha256": fill * 64,
                "review_index_path": f"{prefix}/review-index.dev.json",
                "review_index_sha256": fill * 64,
            }
        )
    summary: dict[str, object] = {
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
        "splits": receipts,
    }
    seal: dict[str, object] = {
        "artifact": "microtexture-v2-r6-development-generation-seal",
        "schema_version": "microtexture-v2-r6-development-generation-seal/1",
        "authority": False,
        "formal_use_forbidden": True,
        "generation_start_sha256": hashlib.sha256(
            development_probe._json_bytes(start)
        ).hexdigest(),
        "generation_summary_sha256": hashlib.sha256(
            development_probe._json_bytes(summary)
        ).hexdigest(),
        "spec_sha256": state["spec_sha256"],
        "implementation_bindings_sha256": state[
            "implementation_bindings_sha256"
        ],
        "blind_key_commitment": state["blind_key_commitment"],
        "captured_git_head": state["captured_git_head"],
    }
    completion: dict[str, object] = {
        "artifact": "microtexture-v2-r6-development-generation-completion",
        "schema_version": "microtexture-v2-r6-development-generation-completion/1",
        "authority": False,
        "formal_use_forbidden": True,
        "completed_at": "2026-07-29T00:01:00Z",
        "generation_start_sha256": seal["generation_start_sha256"],
        "generation_summary_sha256": seal["generation_summary_sha256"],
        "generation_seal_sha256": hashlib.sha256(
            development_probe._json_bytes(seal)
        ).hexdigest(),
        "spec_sha256": state["spec_sha256"],
        "implementation_bindings_sha256": state[
            "implementation_bindings_sha256"
        ],
        "blind_key_commitment": state["blind_key_commitment"],
        "captured_git_head": state["captured_git_head"],
    }
    return state, boundary, start, summary, seal, completion


def _development_generation_split_results() -> list[dict[str, object]]:
    return [
        {
            "split": "calibration",
            "record_count": 220,
            "contact_sheet_count": 185,
            "review_board_count": 37,
            "manifest_path": "public/calibration/manifest.dev.json",
            "manifest_sha256": "1" * 64,
            "blank_labels_path": "public/calibration/labels.blank.dev.json",
            "blank_labels_sha256": "2" * 64,
            "review_index_path": "public/calibration/review-index.dev.json",
            "review_index_sha256": "3" * 64,
            "codes": ["calibration-code"],
            "control_ids": ["calibration-control"],
            "cluster_ids": ["calibration-cluster"],
            "nonzero_delta_hashes": ["4" * 64],
            "zero_delta_hashes": ["0" * 64],
        },
        {
            "split": "holdout",
            "record_count": 220,
            "contact_sheet_count": 185,
            "review_board_count": 37,
            "manifest_path": "public/holdout/manifest.dev.json",
            "manifest_sha256": "5" * 64,
            "blank_labels_path": "public/holdout/labels.blank.dev.json",
            "blank_labels_sha256": "6" * 64,
            "review_index_path": "public/holdout/review-index.dev.json",
            "review_index_sha256": "7" * 64,
            "codes": ["holdout-code"],
            "control_ids": ["holdout-control"],
            "cluster_ids": ["holdout-cluster"],
            "nonzero_delta_hashes": ["8" * 64],
            "zero_delta_hashes": ["0" * 64],
        },
    ]


class MicrotextureR6SelfTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = common.load_spec()
        if calibration_harness.SPEC_SHA256 != common.SPEC_SHA256:
            raise RuntimeError("r6 harness/spec trust root drift")

    def test_preregistered_counts_and_metric_window(self) -> None:
        self.assertEqual(
            self.spec["schema_version"], "microtexture-v2-r6-preregistered-spec/3"
        )
        self.assertEqual(
            self.spec["canvas"]["metric_window"]["xywh"], [128, 96, 256, 192]
        )
        self.assertEqual(self.spec["canvas"]["metric_window"]["pixels"], 49152)
        self.assertEqual(
            self.spec["contact_sheets"]["expected_controls_per_split"], 220
        )
        self.assertEqual(self.spec["contact_sheets"]["expected_pages_per_split"], 185)
        self.assertEqual(
            self.spec["threshold_selection"]["hard_gate"]["metric"],
            "hard_composite_score",
        )
        self.assertEqual(
            set(self.spec["metric_definition"]["score_reference_constants"]),
            {
                "grain_occupancy_per_mp",
                "grain_rms_l",
                "tiny_mass_l",
                "tiny_component_count",
                "multiscale_blob_strength_l_sqrt_px",
                "finite_line_peak_l",
                "finite_line_top4_mean_l",
                "parallel_pair_peak_l",
                "parallel_matched_pair_count",
            },
        )
        self.assertEqual(
            set(self.spec["threshold_selection"]["selection_status_state_machine"]),
            {"no-endpoint-admissible-threshold", "selected-and-passed"},
        )
        self.assertEqual(
            self.spec["threshold_selection"]["endpoint_truth_aggregation"][
                "disposition_precedence"
            ],
            ["reject", "warning", "clean"],
        )

    def test_vision_observation_rubric_is_exact_and_fail_closed(self) -> None:
        common.validate_preregistered_spec(self.spec)
        rubric = self.spec["labels"]["vision_observation_rubric"]
        self.assertEqual(rubric, common.VISION_SEMANTIC_RUBRIC)
        leaf_paths: list[tuple[str, ...]] = []

        def collect(value: object, prefix: tuple[str, ...] = ()) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    collect(child, (*prefix, key))
            else:
                leaf_paths.append(prefix)

        collect(rubric)
        for path in leaf_paths:
            changed = copy.deepcopy(self.spec)
            target = changed["labels"]["vision_observation_rubric"]
            for key in path[:-1]:
                target = target[key]
            original = target[path[-1]]
            target[path[-1]] = (
                not original if isinstance(original, bool) else original + " drift"
            )
            with (
                self.subTest(path=".".join(path)),
                self.assertRaisesRegex(RuntimeError, "Vision observation rubric drift"),
            ):
                common.validate_preregistered_spec(changed)

        mutations = []
        missing = copy.deepcopy(self.spec)
        del missing["labels"]["vision_observation_rubric"]["flags_nonexclusive"]
        mutations.append(missing)
        nested_missing = copy.deepcopy(self.spec)
        del nested_missing["labels"]["vision_observation_rubric"][
            "evidence_notes_contract"
        ]["clean_binding"]
        mutations.append(nested_missing)
        extra = copy.deepcopy(self.spec)
        extra["labels"]["vision_observation_rubric"]["unexpected"] = True
        mutations.append(extra)
        nested_extra = copy.deepcopy(self.spec)
        nested_extra["labels"]["vision_observation_rubric"]["evidence_notes_contract"][
            "unexpected"
        ] = True
        mutations.append(nested_extra)
        for changed in mutations:
            with self.assertRaisesRegex(
                RuntimeError, "Vision observation rubric drift"
            ):
                common.validate_preregistered_spec(changed)

        public_validation_drift = copy.deepcopy(self.spec)
        public_validation_drift["labels"]["public_pre_marker_validation"] += " drift"
        with self.assertRaisesRegex(
            RuntimeError, "private Vision audit contract drift"
        ):
            common.validate_preregistered_spec(public_validation_drift)

    def test_sparse_rendering_is_contained_in_metric_window(self) -> None:
        roi = (128, 96, 256, 192)
        outside = np.ones((384, 512), dtype=bool)
        outside[96:288, 128:384] = False
        probes = {
            "artifact-speck": {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 1,
                "amplitude_l": 10.0,
                "count_in_metric_window": 9,
                "shoulder_fraction": 0.08,
                "minimum_separation_px": 12,
            },
            "artifact-microblob": {
                "design_tier": "clear-reject-candidate",
                "diameter_px": 12,
                "amplitude_l": 9.0,
                "count_in_metric_window": 9,
                "support_radius_px": 10,
                "minimum_separation_px": 24,
            },
            "artifact-short-dash": {
                "design_tier": "clear-reject-candidate",
                "length_px": 24,
                "width_px": 4,
                "amplitude_l": 9.0,
                "count_in_metric_window": 9,
                "minimum_separation_px": 31,
            },
            "artifact-parallel-bundle": {
                "design_tier": "clear-reject-candidate",
                "length_px": 24,
                "width_px": 2,
                "spacing_px": 8,
                "amplitude_l": 9.0,
                "pair_count_in_metric_window": 9,
                "minimum_bundle_separation_px": 31,
            },
        }
        for index, (family, parameters) in enumerate(probes.items()):
            delta = _render_unsigned_delta(
                family,
                parameters,
                np.random.default_rng(100 + index),
                384,
                512,
                roi,
            )
            self.assertTrue(np.any(delta[~outside] != 0), family)
            self.assertTrue(np.all(delta[outside] == 0), family)
        zero = _render_unsigned_delta(
            "protocol-zero",
            {},
            np.random.default_rng(999),
            384,
            512,
            roi,
        )
        self.assertTrue(np.all(zero == 0))

    def test_parallel_visual_edge_gap_schedule_population_is_frozen(self) -> None:
        for split in ("calibration", "holdout"):
            variants = _artifact_variants(split)["artifact-parallel-bundle"]
            eligible = [
                item
                for item in variants
                if 0 < item["spacing_px"] - item["width_px"] <= item["length_px"]
            ]
            self.assertEqual(len(eligible), 20, split)
            self.assertEqual(
                sum(
                    item["design_tier"]
                    in {"clear-reject-candidate", "dominant-reject-candidate"}
                    for item in eligible
                ),
                11,
                split,
            )

    def test_population_anchor_schedule_and_speck_hard_cores_are_exact(self) -> None:
        anchor = self.spec["population_anchor_schedule"]
        expected_tiers = Counter(
            {
                "clean-candidate": 5,
                "warning-candidate": 4,
                "clear-reject-candidate": 7,
                "dominant-reject-candidate": 4,
            }
        )
        expected_shoulders = {
            "clean-candidate": 0.0,
            "warning-candidate": 0.05,
            "clear-reject-candidate": 0.08,
            "dominant-reject-candidate": 0.08,
        }
        self.assertEqual(anchor, common.POPULATION_ANCHOR_SCHEDULE)
        self.assertEqual(
            _SCHEDULE_REVISION,
            "dev-r15-calibration-microblob-reject-anchor-schedule-v1",
        )
        self.assertEqual(anchor["tier_counts_per_artifact_family"], dict(expected_tiers))
        self.assertEqual(anchor["revision"], _SCHEDULE_REVISION)
        self.assertTrue(anchor["fresh_from_closed_dev_r14"])
        self.assertTrue(anchor["r14_parameter_nonce_reuse_forbidden"])
        self.assertEqual(
            anchor["r15_per_family_residue_rotation"],
            {
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
        )
        self.assertEqual(
            anchor["r15_parameter_nonce_bases"],
            {
                "calibration_artifact": 773000,
                "holdout_artifact": 783000,
                "calibration_protocol_zero": 751000,
                "holdout_protocol_zero": 761000,
                "calibration_duplicate_audit": [791000, 791001, 791002],
                "holdout_duplicate_audit": [801000, 801001, 801002],
            },
        )
        self.assertEqual(
            anchor["grain_reject_anchor_schedule"],
            {
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
        )
        self.assertEqual(
            anchor["speck_reject_anchor_schedule"],
            {
                "calibration": {
                    "clear_counts": [32, 36, 40, 44, 48, 52, 56],
                    "dominant_counts": [64, 72, 80, 88],
                },
                "holdout": {
                    "clear_counts": [34, 38, 42, 46, 50, 54, 58],
                    "dominant_counts": [68, 76, 84, 90],
                },
                "diameter_px": 1,
                "minimum_separation_px": 10,
                "shoulder_fraction": 0.08,
                "amplitude_l_maximum": 12.0,
                "split_morphology_tuples_disjoint": True,
            },
        )
        split_nonces: dict[str, set[int]] = {}
        roi = (128, 96, 256, 192)
        outside = np.ones((384, 512), dtype=bool)
        outside[96:288, 128:384] = False
        for split in ("calibration", "holdout"):
            catalog = _artifact_variants(split)
            self.assertEqual(len(catalog), 5)
            split_nonces[split] = {
                int(item["condition_nonce"])
                for variants in catalog.values()
                for item in variants
            }
            self.assertEqual(len(split_nonces[split]), 100)
            for family, variants in catalog.items():
                self.assertEqual(len(variants), 20, (split, family))
                self.assertTrue(
                    all(
                        item["schedule_revision"]
                        == _SCHEDULE_REVISION
                        for item in variants
                    ),
                    (split, family),
                )
                self.assertEqual(
                    Counter(item["design_tier"] for item in variants),
                    expected_tiers,
                    (split, family),
                )
                for tier in expected_tiers:
                    residues = {
                        index % 3
                        for index, item in enumerate(variants)
                        if item["design_tier"] == tier
                    }
                    self.assertEqual(residues, {0, 1, 2}, (split, family, tier))

            for index, parameters in enumerate(catalog["artifact-speck"]):
                tier = parameters["design_tier"]
                self.assertEqual(
                    parameters["shoulder_fraction"], expected_shoulders[tier]
                )
                if tier == "clean-candidate":
                    self.assertLessEqual(parameters["count_in_metric_window"], 2)
                    self.assertLessEqual(parameters["amplitude_l"], 1.4)
                elif tier in {
                    "clear-reject-candidate",
                    "dominant-reject-candidate",
                }:
                    expected_counts = anchor["speck_reject_anchor_schedule"][split][
                        "clear_counts"
                        if tier == "clear-reject-candidate"
                        else "dominant_counts"
                    ]
                    tier_parameters = [
                        item
                        for item in catalog["artifact-speck"]
                        if item["design_tier"] == tier
                    ]
                    self.assertEqual(
                        [item["count_in_metric_window"] for item in tier_parameters],
                        expected_counts,
                    )
                    self.assertEqual(parameters["diameter_px"], 1)
                    self.assertEqual(parameters["minimum_separation_px"], 10)
                    self.assertEqual(parameters["shoulder_fraction"], 0.08)
                    self.assertLessEqual(parameters["amplitude_l"], 12.0)
                    self.assertGreaterEqual(parameters["amplitude_l"], 10.0)
                for seed_offset in range(4):
                    delta = _render_unsigned_delta(
                        "artifact-speck",
                        parameters,
                        np.random.default_rng(10000 + index * 4 + seed_offset),
                        384,
                        512,
                        roi,
                    )
                    amplitude = np.float32(parameters["amplitude_l"])
                    centers_yx = np.argwhere(delta == amplitude)
                    self.assertEqual(
                        len(centers_yx), parameters["count_in_metric_window"]
                    )
                    minimum = parameters["minimum_separation_px"]
                    self.assertTrue(
                        all(
                            max(abs(int(y1) - int(y2)), abs(int(x1) - int(x2)))
                            >= minimum
                            for center_index, (y1, x1) in enumerate(centers_yx)
                            for y2, x2 in centers_yx[center_index + 1 :]
                        )
                    )
                    if len(centers_yx) >= 4:
                        quadrants = {
                            (int(x >= 256), int(y >= 192)) for y, x in centers_yx
                        }
                        self.assertEqual(len(quadrants), 4)
                    self.assertTrue(np.all(delta[outside] == 0))
                    self.assertGreater(np.count_nonzero(np.rint(delta)), 0)
        self.assertTrue(split_nonces["calibration"].isdisjoint(split_nonces["holdout"]))
        self.assertEqual(min(split_nonces["calibration"]), 773000)
        self.assertEqual(max(split_nonces["calibration"]), 773419)
        self.assertEqual(min(split_nonces["holdout"]), 783000)
        self.assertEqual(max(split_nonces["holdout"]), 783419)
        self.assertEqual(
            self.spec["splits"]["calibration"]["public_nonce"],
            "r6-calibration-v10",
        )
        self.assertEqual(
            self.spec["splits"]["holdout"]["public_nonce"], "r6-holdout-v10"
        )
        self.assertEqual(
            self.spec["independent_condition_clusters"]["message_prefix"],
            "microtexture-v2-r6/private-condition-cluster/v10/",
        )
        self.assertEqual(
            self.spec["blind_derivation"]["seed_message_prefix"],
            "microtexture-v2-r6/render-seed/v10/",
        )
        self.assertEqual(
            self.spec["blind_derivation"]["code_message_prefix"],
            "microtexture-v2-r6/opaque-code/v10/",
        )
        self.assertEqual(
            self.spec["rendering"]["public_commitment_domain"],
            "microtexture-v2-r6/public-payload-commitment/v11/"
            "{control|reference|delta}/{anonymous_code}/{raw-sha256-bytes}",
        )
        self.assertEqual(
            self.spec["blind_derivation"]["key_commitment_message"],
            "microtexture-v2-r6/key-commitment/v9",
        )
        self.assertEqual(
            self.spec["rendering"]["hard_speck_reject_anchor_contract"],
            common.RENDERING_INVARIANTS["hard_speck_reject_anchor_contract"],
        )

    def test_dev_r15_inherited_warning_acceptance_anchor_matrix_is_exact(self) -> None:
        expected = _expected_warning_acceptance_anchors()
        self.assertEqual(
            _WARNING_ACCEPTANCE_ANCHORS,
            {
                "revision": "dev-r14-quantized-direct-visible-sparse-warning-v1",
                "splits": expected,
            },
        )
        manifest = _warning_acceptance_anchor_manifest(expected)
        manifest_sha = hashlib.sha256(
            common.canonical_json_bytes(manifest)
        ).hexdigest()
        self.assertEqual(
            manifest_sha,
            "5e997df4c7d4e0c6106b3060437235a7f665b08a6b02e00a86f4a4f024dc77e6",
        )

        anchor = self.spec["population_anchor_schedule"]
        self.assertEqual(
            anchor["warning_acceptance_anchor_revision"],
            "dev-r14-quantized-direct-visible-sparse-warning-v1",
        )
        self.assertEqual(anchor["warning_acceptance_anchor_conditions_per_split"], 16)
        self.assertEqual(
            anchor["warning_acceptance_anchor_conditions_per_family"],
            {
                "artifact-speck": 4,
                "artifact-microblob": 4,
                "artifact-short-dash": 4,
                "artifact-parallel-bundle": 4,
            },
        )
        self.assertEqual(
            anchor[
                "warning_acceptance_anchor_structural_miss_budget_against_development_floor"
            ],
            3,
        )
        self.assertFalse(anchor["warning_acceptance_anchor_truth_guarantee_claimed"])
        self.assertFalse(anchor["nonwarning_morphology_change_forbidden"])
        self.assertTrue(anchor["non_target_morphology_change_forbidden"])
        self.assertEqual(
            anchor["warning_acceptance_anchor_schedule_sha256"], manifest_sha
        )

        non_target = {
            split: {
                family: [
                    {
                        key: value
                        for key, value in parameters.items()
                        if key not in {"schedule_revision", "condition_nonce"}
                    }
                    for parameters in variants
                    if not (
                        split == "calibration"
                        and family == "artifact-microblob"
                        and parameters["design_tier"] == "clear-reject-candidate"
                    )
                ]
                for family, variants in _artifact_variants(split).items()
            }
            for split in ("calibration", "holdout")
        }
        non_target_sha = hashlib.sha256(
            common.canonical_json_bytes(non_target)
        ).hexdigest()
        self.assertEqual(
            non_target_sha,
            "d9b2cd55c575075268ebd5c69a3a39e1a5c4819089832e1bf330118dd2f2b869",
        )
        self.assertEqual(
            anchor["predecessor_non_target_morphology_sha256"], non_target_sha
        )

        for split in ("calibration", "holdout"):
            catalog = _artifact_variants(split)
            self.assertEqual(
                sum(len(rows) for rows in expected[split].values()), 16, split
            )
            self.assertNotIn("artifact-fine-grain", expected[split])
            for family, rows in expected[split].items():
                warning_indices = {
                    index
                    for index, parameters in enumerate(catalog[family])
                    if parameters["design_tier"] == "warning-candidate"
                }
                self.assertEqual(warning_indices, set(rows), (split, family))
                self.assertEqual({index % 3 for index in rows}, {0, 1, 2})
                for index, parameters in rows.items():
                    actual = {
                        key: value
                        for key, value in catalog[family][index].items()
                        if key not in {"schedule_revision", "condition_nonce"}
                    }
                    self.assertEqual(actual, parameters, (split, family, index))

        for family in expected["calibration"]:
            calibration = {
                common.canonical_json_bytes(parameters)
                for parameters in expected["calibration"][family].values()
            }
            holdout = {
                common.canonical_json_bytes(parameters)
                for parameters in expected["holdout"][family].values()
            }
            self.assertTrue(calibration.isdisjoint(holdout), family)

    def test_dev_r15_calibration_microblob_clear_reject_matrix_is_exact(
        self,
    ) -> None:
        expected = _expected_calibration_microblob_clear_reject_anchors()
        self.assertEqual(
            _CALIBRATION_MICROBLOB_CLEAR_REJECT_ANCHORS,
            {
                "revision": "dev-r15-calibration-quantized-microblob-reject-v1",
                "entries": expected,
            },
        )
        manifest = _calibration_microblob_clear_reject_anchor_manifest(expected)
        manifest_sha = hashlib.sha256(
            common.canonical_json_bytes(manifest)
        ).hexdigest()
        self.assertEqual(
            manifest_sha,
            "dd2ce7fd13f624bd065e8c7a6bacc2ab8bd593821dec8d46250a40e57ef64833",
        )

        anchor = self.spec["population_anchor_schedule"]
        self.assertEqual(
            anchor["calibration_microblob_clear_reject_anchor_manifest"],
            manifest,
        )
        self.assertEqual(
            anchor["calibration_microblob_clear_reject_anchor_conditions"], 7
        )
        self.assertFalse(
            anchor[
                "calibration_microblob_clear_reject_anchor_truth_guarantee_claimed"
            ]
        )
        self.assertEqual(
            anchor["calibration_microblob_clear_reject_anchor_schedule_sha256"],
            manifest_sha,
        )

        variants = _artifact_variants("calibration")["artifact-microblob"]
        clear_indices = {
            index
            for index, parameters in enumerate(variants)
            if parameters["design_tier"] == "clear-reject-candidate"
        }
        self.assertEqual(clear_indices, set(expected))
        self.assertEqual({index % 3 for index in clear_indices}, {0, 1, 2})
        for index, parameters in expected.items():
            actual = {
                key: value
                for key, value in variants[index].items()
                if key not in {"schedule_revision", "condition_nonce"}
            }
            self.assertEqual(actual, parameters, index)
            support_radius = int(parameters["support_radius_px"])
            self.assertIn(int(parameters["diameter_px"]), {4, 5, 6})
            self.assertGreaterEqual(float(parameters["amplitude_l"]), 11.4)
            self.assertGreaterEqual(int(parameters["count_in_metric_window"]), 44)
            self.assertGreaterEqual(
                int(parameters["minimum_separation_px"]),
                2 * support_radius + 1,
            )
        self.assertEqual(
            Counter(
                (
                    int(parameters["diameter_px"]),
                    int(parameters["support_radius_px"]),
                    int(parameters["count_in_metric_window"]),
                )
                for parameters in expected.values()
            ),
            Counter({(4, 2, 64): 3, (6, 3, 44): 3, (5, 3, 52): 1}),
        )
        self.assertEqual(
            tuple(int(np.rint(float(item["amplitude_l"]))) for item in expected.values()),
            (12, 12, 11, 12, 12, 12, 11),
        )

    def test_dev_r15_grain_reject_periods_are_inside_metric_support(self) -> None:
        anchor = self.spec["population_anchor_schedule"][
            "grain_reject_anchor_schedule"
        ]
        metric_minimum, metric_maximum = anchor[
            "metric_coherence_period_bounds_px"
        ]
        preferred_minimum, preferred_maximum = anchor[
            "preferred_reject_period_bounds_px"
        ]
        split_pattern_periods: dict[str, set[tuple[str, float]]] = {}
        for split in ("calibration", "holdout"):
            variants = _artifact_variants(split)["artifact-fine-grain"]
            split_pattern_periods[split] = set()
            for tier, anchor_key, expected_count in (
                ("clear-reject-candidate", "clear", 7),
                ("dominant-reject-candidate", "dominant", 4),
            ):
                actual = [
                    [
                        parameters["pattern"],
                        parameters.get(
                            "wavelength_px", parameters.get("cell_px")
                        ),
                    ]
                    for parameters in variants
                    if parameters["design_tier"] == tier
                ]
                self.assertEqual(actual, anchor[split][anchor_key])
                self.assertEqual(len(actual), expected_count)
                self.assertTrue(
                    all(
                        metric_minimum < float(period) < metric_maximum
                        and preferred_minimum <= float(period) <= preferred_maximum
                        for _, period in actual
                    )
                )
                split_pattern_periods[split].update(
                    (str(pattern), float(period)) for pattern, period in actual
                )
        self.assertTrue(anchor["split_pattern_period_tuples_disjoint"])
        self.assertTrue(
            split_pattern_periods["calibration"].isdisjoint(
                split_pattern_periods["holdout"]
            )
        )

    def test_dev_r15_domains_and_nonce_ranges_are_fresh_and_exact(self) -> None:
        self.assertEqual(
            _PUBLIC_PAYLOAD_COMMITMENT_PREFIX,
            b"microtexture-v2-r6/public-payload-commitment/v11/",
        )
        self.assertEqual(
            _PRIVATE_REFERENCE_TRANSFORM_PREFIX,
            b"private-reference-transform-v10/",
        )
        self.assertEqual(_FOUNDATION_OFFSET_LANE, "foundation-offset-v9")
        self.assertEqual(_FOUNDATION_ASSIGNMENT_LANE, "foundation-assignment-v9")
        self.assertEqual(_DELTA_LANE, "delta-v9")
        self.assertEqual(
            _PRIVATE_CONTROL_ID_PREFIX,
            b"microtexture-v2-r6/private-control-id/v9/",
        )
        self.assertEqual(
            _ARTIFACT_NONCE_BASES,
            {"calibration": 773000, "holdout": 783000},
        )
        self.assertEqual(
            _PROTOCOL_ZERO_NONCE_BASES,
            {"calibration": 751000, "holdout": 761000},
        )
        self.assertEqual(
            _DUPLICATE_AUDIT_NONCES,
            {
                "calibration": (791000, 791001, 791002),
                "holdout": (801000, 801001, 801002),
            },
        )
        nonce_ranges = [
            set(range(751000, 751016)),
            set(range(761000, 761016)),
            set(range(773000, 773420)),
            set(range(783000, 783420)),
            {791000, 791001, 791002},
            {801000, 801001, 801002},
        ]
        self.assertTrue(
            all(
                left.isdisjoint(right)
                for index, left in enumerate(nonce_ranges)
                for right in nonce_ranges[index + 1 :]
            )
        )
        closed_r14_ranges = [
            set(range(651000, 651016)),
            set(range(661000, 661016)),
            set(range(673000, 673420)),
            set(range(683000, 683420)),
            {691000, 691001, 691002},
            {701000, 701001, 701002},
        ]
        self.assertTrue(
            all(
                fresh.isdisjoint(closed)
                for fresh in nonce_ranges
                for closed in closed_r14_ranges
            )
        )

    def test_dev_r15_morphology_schedule_hashes_are_exact(self) -> None:
        expected = {
            "calibration": {
                "artifact-fine-grain": "add2823835c0e47be63cc92632eb728f3caa1a9a7f96d0bd2e2af49e051aedd8",
                "artifact-speck": "e439f6dfeac40b1712d82d2bd609773c5e36a6fc2871431292c08667dd921ff5",
                "artifact-microblob": "dfaad1cff9f96953689b9c7122575cf241aee21bc44f344ffb666dfa8b1a4bb8",
                "artifact-short-dash": "4d1ae47a3810abb3ac662ec4910b90fe9b3b2c6053371c459eb6d0aa7db771ac",
                "artifact-parallel-bundle": "35d5b6b91bb117c76bcf77610469644481438d6cc2e840c6fdb3051a7a9a8557",
            },
            "holdout": {
                "artifact-fine-grain": "1e1551e20f212acca19d502b055bf34722c4c4bafb6d698ab4b81e8ab5dcb88d",
                "artifact-speck": "dfbe0f14641fdb673c6832f6ce3327e839324fe7db086789b905cca58ddfc840",
                "artifact-microblob": "77ad8a3cb3c7f93b83d04d211ba1673c18da4b23521bbc40b39d03f7df4f6310",
                "artifact-short-dash": "8a720f29169b6911812c2a88b73e270186f176c4c3916f580b1b4a058407de7d",
                "artifact-parallel-bundle": "64819fa0b1d575fda7ee9e2073bbc2f72a836fc168e202e9169e06092ba40023",
            },
        }
        for split in ("calibration", "holdout"):
            for family, variants in _artifact_variants(split).items():
                morphology = [
                    {
                        key: value
                        for key, value in parameters.items()
                        if key not in {"schedule_revision", "condition_nonce"}
                    }
                    for parameters in variants
                ]
                self.assertEqual(
                    hashlib.sha256(common.canonical_json_bytes(morphology)).hexdigest(),
                    expected[split][family],
                    (split, family),
                )

    def test_dev_r15_runner_is_tracked_authority_with_isolated_root(self) -> None:
        self.assertEqual(development_probe.DEVELOPMENT_EDITION, "r15")
        self.assertEqual(
            common.SPEC_SHA256,
            "21199f17cdd7fff6f30c6f2a41cd2d5e465cd63de67b0d480a892423629d4aef",
        )
        self.assertEqual(
            development_probe.DEV_ROOT,
            common.repository_root()
            / "tmp"
            / "map-production"
            / "microtexture-v2-r6-dev-r15",
        )
        self.assertEqual(
            development_probe.FORMAL_ROOT,
            common.repository_root()
            / "tmp"
            / "map-production"
            / "microtexture-v2-r6-artifacts",
        )
        self.assertNotEqual(development_probe.DEV_ROOT, development_probe.FORMAL_ROOT)
        self.assertIn("development_probe.py", self.spec["authority_files"])
        secret_handling = self.spec["development_probe_secret_handling"]
        self.assertTrue(
            secret_handling[
                "ignored_private_key_persistence_required_for_one_shot_analysis_and_closed_postmortem"
            ]
        )
        self.assertTrue(secret_handling["key_value_logging_or_git_tracking_forbidden"])
        self.assertTrue(
            secret_handling["vision_process_key_read_or_inheritance_forbidden"]
        )
        self.assertTrue(
            secret_handling[
                "gitignore_must_be_tracked_and_worktree_bytes_must_match_captured_head"
            ]
        )
        self.assertTrue(
            secret_handling[
                "ignored_private_key_must_be_absent_from_head_and_index_and_git_ignored"
            ]
        )
        self.assertEqual(secret_handling["gitignore_required_pattern"], "/tmp*/")
        self.assertTrue(
            secret_handling["key_reuse_in_any_successor_or_formal_operation_forbidden"]
        )
        self.assertEqual(
            common.repository_root()
            / secret_handling["ignored_private_key_required_repo_relative"],
            development_probe.DEV_ROOT / "private" / "development-key.bin",
        )
        captured_head = development_probe._git_head()
        self.assertEqual(
            development_probe._validate_development_key_git_boundary(
                self.spec, captured_head
            ),
            development_probe.DEV_ROOT / "private" / "development-key.bin",
        )

    def test_dev_r15_runner_rejects_spec_bytes_outside_frozen_sha(self) -> None:
        frozen_sha = common.SPEC_SHA256
        with tempfile.TemporaryDirectory() as directory:
            code_root = Path(directory)
            source = (
                development_probe.CODE_ROOT / "preregistered-spec.json"
            ).read_bytes()
            (code_root / "preregistered-spec.json").write_bytes(source + b"\n")
            with mock.patch.object(development_probe, "CODE_ROOT", code_root):
                with self.assertRaisesRegex(RuntimeError, "spec SHA drift"):
                    development_probe._load_spec()
        self.assertEqual(common.SPEC_SHA256, frozen_sha)

    def test_dev_r15_runner_rejects_unignored_private_key_path(self) -> None:
        completed = development_probe.subprocess.CompletedProcess
        captured_head = development_probe._git_head()
        with (
            mock.patch.object(
                common, "_tracked_worktree_bytes", return_value=b"/tmp*/\n"
            ),
            mock.patch.object(common, "assert_head_unchanged"),
            mock.patch.object(
                development_probe.subprocess,
                "run",
                side_effect=[
                    completed(args=[], returncode=0, stdout="", stderr=""),
                    completed(args=[], returncode=1, stdout="", stderr=""),
                    completed(args=[], returncode=1, stdout="", stderr=""),
                ],
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "not Git-ignored"):
                development_probe._validate_development_key_git_boundary(
                    self.spec, captured_head
                )

    def test_dev_r15_runner_rejects_nontracked_ignore_source(self) -> None:
        completed = development_probe.subprocess.CompletedProcess
        key_relative = self.spec["development_probe_secret_handling"][
            "ignored_private_key_required_repo_relative"
        ]
        captured_head = development_probe._git_head()
        with (
            mock.patch.object(
                common, "_tracked_worktree_bytes", return_value=b"/tmp*/\n"
            ),
            mock.patch.object(common, "assert_head_unchanged"),
            mock.patch.object(
                development_probe.subprocess,
                "run",
                side_effect=[
                    completed(args=[], returncode=0, stdout="", stderr=""),
                    completed(args=[], returncode=1, stdout="", stderr=""),
                    completed(
                        args=[],
                        returncode=0,
                        stdout=f".git/info/exclude:1:/tmp*/\t{key_relative}\n",
                        stderr="",
                    ),
                ],
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "tracked root .gitignore"):
                development_probe._validate_development_key_git_boundary(
                    self.spec, captured_head
                )

    def test_dev_r15_generation_transaction_is_exact_and_sealed(self) -> None:
        state, boundary, start, summary, seal, completion = (
            _development_generation_documents(self.spec)
        )

        def write_documents(
            root: Path,
            current_boundary: dict[str, object],
            current_start: dict[str, object],
            current_summary: dict[str, object],
            current_seal: dict[str, object],
            current_completion: dict[str, object],
        ) -> None:
            root.mkdir(parents=True, exist_ok=True)
            (root / "DEV-ONLY.json").write_bytes(
                development_probe._json_bytes(current_boundary)
            )
            (root / "generation-start.dev.json").write_bytes(
                development_probe._json_bytes(current_start)
            )
            (root / "generation-summary.dev.json").write_bytes(
                development_probe._json_bytes(current_summary)
            )
            (root / "generation-seal.dev.json").write_bytes(
                development_probe._json_bytes(current_seal)
            )
            (root / "generation-completion.dev.json").write_bytes(
                development_probe._json_bytes(current_completion)
            )
            failure = root / "generation-failure.dev.json"
            if failure.exists():
                failure.unlink()

        def resign(
            current_summary: dict[str, object],
            current_seal: dict[str, object],
            current_completion: dict[str, object],
        ) -> None:
            current_seal["generation_summary_sha256"] = hashlib.sha256(
                development_probe._json_bytes(current_summary)
            ).hexdigest()
            current_completion["generation_summary_sha256"] = current_seal[
                "generation_summary_sha256"
            ]
            current_completion["generation_seal_sha256"] = hashlib.sha256(
                development_probe._json_bytes(current_seal)
            ).hexdigest()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "dev-r15"
            with mock.patch.object(development_probe, "DEV_ROOT", root):
                write_documents(root, boundary, start, summary, seal, completion)
                loaded_state, receipts, binding = (
                    development_probe._load_generation_state(
                        self.spec, common.SPEC_SHA256
                    )
                )
                self.assertEqual(loaded_state, state)
                self.assertEqual(set(receipts), {"calibration", "holdout"})
                self.assertEqual(
                    binding["generation_summary_sha256"],
                    seal["generation_summary_sha256"],
                )
                self.assertEqual(
                    binding["generation_start_sha256"],
                    seal["generation_start_sha256"],
                )
                self.assertEqual(
                    binding["generation_completion_sha256"],
                    hashlib.sha256(
                        development_probe._json_bytes(completion)
                    ).hexdigest(),
                )

                cases = [
                    (
                        "summary unknown field",
                        lambda _boundary, current_summary, _seal: current_summary.update(
                            {"unexpected": True}
                        ),
                        True,
                    ),
                    (
                        "boundary unknown field",
                        lambda current_boundary, _summary, _seal: current_boundary.update(
                            {"unexpected": True}
                        ),
                        False,
                    ),
                    (
                        "seal unknown field",
                        lambda _boundary, _summary, current_seal: current_seal.update(
                            {"unexpected": True}
                        ),
                        False,
                    ),
                    (
                        "false split separation",
                        lambda _boundary, current_summary, _seal: current_summary[
                            "split_separation"
                        ].update({"codes_disjoint": False}),
                        True,
                    ),
                    (
                        "duplicate split",
                        lambda _boundary, current_summary, _seal: current_summary.update(
                            {
                                "splits": [
                                    copy.deepcopy(current_summary["splits"][0]),
                                    copy.deepcopy(current_summary["splits"][0]),
                                ]
                            }
                        ),
                        True,
                    ),
                    (
                        "split order drift",
                        lambda _boundary, current_summary, _seal: current_summary[
                            "splits"
                        ].reverse(),
                        True,
                    ),
                    (
                        "record count drift",
                        lambda _boundary, current_summary, _seal: current_summary[
                            "splits"
                        ][0].update({"record_count": 219}),
                        True,
                    ),
                    (
                        "noninteger record count",
                        lambda _boundary, current_summary, _seal: current_summary[
                            "splits"
                        ][0].update({"record_count": 220.0}),
                        True,
                    ),
                    (
                        "noncanonical path",
                        lambda _boundary, current_summary, _seal: current_summary[
                            "splits"
                        ][0].update({"review_index_path": "../review-index.dev.json"}),
                        True,
                    ),
                ]
                for label, mutate, should_resign in cases:
                    with self.subTest(label=label):
                        current_boundary = copy.deepcopy(boundary)
                        current_start = copy.deepcopy(start)
                        current_summary = copy.deepcopy(summary)
                        current_seal = copy.deepcopy(seal)
                        current_completion = copy.deepcopy(completion)
                        mutate(current_boundary, current_summary, current_seal)
                        if should_resign:
                            resign(current_summary, current_seal, current_completion)
                        write_documents(
                            root,
                            current_boundary,
                            current_start,
                            current_summary,
                            current_seal,
                            current_completion,
                        )
                        with self.assertRaises(RuntimeError):
                            development_probe._load_generation_state(
                                self.spec, common.SPEC_SHA256
                            )

                changed_summary = copy.deepcopy(summary)
                changed_summary["authority"] = True
                write_documents(
                    root, boundary, start, changed_summary, seal, completion
                )
                with self.assertRaisesRegex(RuntimeError, "generation seal drift"):
                    development_probe._load_generation_state(
                        self.spec, common.SPEC_SHA256
                    )

                changed_start = copy.deepcopy(start)
                changed_start["unexpected"] = True
                write_documents(
                    root, boundary, changed_start, summary, seal, completion
                )
                with self.assertRaises(RuntimeError):
                    development_probe._load_generation_state(
                        self.spec, common.SPEC_SHA256
                    )

                changed_completion = copy.deepcopy(completion)
                changed_completion["unexpected"] = True
                write_documents(
                    root, boundary, start, summary, seal, changed_completion
                )
                with self.assertRaises(RuntimeError):
                    development_probe._load_generation_state(
                        self.spec, common.SPEC_SHA256
                    )

                for missing_name in (
                    "DEV-ONLY.json",
                    "generation-start.dev.json",
                    "generation-summary.dev.json",
                    "generation-seal.dev.json",
                    "generation-completion.dev.json",
                ):
                    with self.subTest(missing_name=missing_name):
                        write_documents(
                            root, boundary, start, summary, seal, completion
                        )
                        (root / missing_name).unlink()
                        with self.assertRaisesRegex(RuntimeError, "terminal artifacts"):
                            development_probe._load_generation_state(
                                self.spec, common.SPEC_SHA256
                            )

                write_documents(root, boundary, start, summary, seal, completion)
                (root / "generation-failure.dev.json").write_bytes(b"{}\n")
                with self.assertRaisesRegex(RuntimeError, "failed and closed"):
                    development_probe._load_generation_state(
                        self.spec, common.SPEC_SHA256
                    )

    def test_dev_r15_generate_success_reloads_exact_terminal_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "dev-r15"
            key_path = root / "private" / "development-key.bin"
            bindings_sha = hashlib.sha256(
                (
                    development_probe.CODE_ROOT / "implementation-bindings.json"
                ).read_bytes()
            ).hexdigest()
            split_results = _development_generation_split_results()

            def post_completion_reload() -> tuple[
                dict[str, object],
                dict[str, object],
                dict[str, str],
                dict[str, object],
            ]:
                loaded_state, _receipts, binding = (
                    development_probe._load_generation_state(
                        self.spec, common.SPEC_SHA256
                    )
                )
                return (
                    self.spec,
                    loaded_state,
                    binding,
                    {"calibration": {}, "holdout": {}},
                )

            output = io.StringIO()
            with (
                mock.patch.object(development_probe, "DEV_ROOT", root),
                mock.patch.object(development_probe, "_assert_development_boundary"),
                mock.patch.object(
                    development_probe,
                    "_load_spec",
                    return_value=(self.spec, common.SPEC_SHA256),
                ),
                mock.patch.object(
                    development_probe,
                    "_tracked_input_preflight",
                    return_value=("c" * 40, bindings_sha),
                ),
                mock.patch.object(
                    development_probe,
                    "_validate_development_key_git_boundary",
                    return_value=key_path,
                ),
                mock.patch.object(
                    development_probe.secrets,
                    "token_bytes",
                    return_value=b"k" * 32,
                ),
                mock.patch.object(
                    common, "blind_commitment", return_value="b" * 64
                ),
                mock.patch.object(
                    common,
                    "runtime_fingerprint",
                    return_value={"test_fixture": True},
                ),
                mock.patch.object(
                    common,
                    "utc_timestamp",
                    side_effect=[
                        "2026-07-29T00:00:00Z",
                        "2026-07-29T00:01:00Z",
                    ],
                ),
                mock.patch.object(
                    development_probe,
                    "_generate_split",
                    side_effect=copy.deepcopy(split_results),
                ),
                mock.patch.object(
                    development_probe,
                    "_review_preflight",
                    side_effect=post_completion_reload,
                ) as review_preflight,
                mock.patch("sys.stdout", output),
            ):
                development_probe.generate()

                loaded_state, receipts, binding = (
                    development_probe._load_generation_state(
                        self.spec, common.SPEC_SHA256
                    )
                )
            review_preflight.assert_called_once_with()
            self.assertEqual(loaded_state["development_edition"], "r15")
            self.assertEqual(set(receipts), {"calibration", "holdout"})
            self.assertFalse((root / "generation-failure.dev.json").exists())
            for name in (
                "generation-start.dev.json",
                "generation-summary.dev.json",
                "generation-seal.dev.json",
                "generation-completion.dev.json",
            ):
                self.assertTrue((root / name).is_file(), name)
            printed = json.loads(output.getvalue())
            for field, name in (
                ("generation_start_sha256", "generation-start.dev.json"),
                ("generation_summary_sha256", "generation-summary.dev.json"),
                ("generation_seal_sha256", "generation-seal.dev.json"),
                ("generation_completion_sha256", "generation-completion.dev.json"),
            ):
                digest = hashlib.sha256((root / name).read_bytes()).hexdigest()
                self.assertEqual(binding[field], digest)
                self.assertEqual(printed[field], digest)

    def test_dev_r15_postcompletion_reload_failure_is_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "dev-r15"
            key_path = root / "private" / "development-key.bin"
            with (
                mock.patch.object(development_probe, "DEV_ROOT", root),
                mock.patch.object(development_probe, "_assert_development_boundary"),
                mock.patch.object(
                    development_probe,
                    "_load_spec",
                    return_value=(self.spec, common.SPEC_SHA256),
                ),
                mock.patch.object(
                    development_probe,
                    "_tracked_input_preflight",
                    return_value=("c" * 40, "d" * 64),
                ),
                mock.patch.object(
                    development_probe,
                    "_validate_development_key_git_boundary",
                    return_value=key_path,
                ),
                mock.patch.object(
                    development_probe.secrets,
                    "token_bytes",
                    return_value=b"k" * 32,
                ),
                mock.patch.object(
                    common, "blind_commitment", return_value="b" * 64
                ),
                mock.patch.object(
                    common,
                    "runtime_fingerprint",
                    return_value={"test_fixture": True},
                ),
                mock.patch.object(
                    common,
                    "utc_timestamp",
                    side_effect=[
                        "2026-07-29T00:00:00Z",
                        "2026-07-29T00:01:00Z",
                        "2026-07-29T00:01:01Z",
                    ],
                ),
                mock.patch.object(
                    development_probe,
                    "_generate_split",
                    side_effect=copy.deepcopy(
                        _development_generation_split_results()
                    ),
                ),
                mock.patch.object(
                    development_probe,
                    "_review_preflight",
                    side_effect=RuntimeError("post-completion reload failed"),
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "post-completion reload failed"
                ):
                    development_probe.generate()
            self.assertTrue((root / "generation-completion.dev.json").is_file())
            self.assertTrue((root / "generation-failure.dev.json").is_file())
            failure = json.loads(
                (root / "generation-failure.dev.json").read_text(encoding="utf-8")
            )
            self.assertEqual(failure["error_type"], "RuntimeError")
            self.assertEqual(failure["message"], "post-completion reload failed")
            with mock.patch.object(development_probe, "DEV_ROOT", root):
                with self.assertRaisesRegex(RuntimeError, "failed and closed"):
                    development_probe._load_generation_state(
                        self.spec, common.SPEC_SHA256
                    )

    def test_dev_r15_generate_failures_are_durably_closed(self) -> None:
        secret_like = "a" * 64
        opaque_code_like = "c" * 24
        for error in (
            KeyboardInterrupt(),
            SystemExit(17),
            RuntimeError(
                f"key={secret_like} code={opaque_code_like} " + "x" * 700
            ),
        ):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "dev-r15"
                key_path = root / "private" / "development-key.bin"
                with (
                    mock.patch.object(development_probe, "DEV_ROOT", root),
                    mock.patch.object(development_probe, "_assert_development_boundary"),
                    mock.patch.object(
                        development_probe,
                        "_load_spec",
                        return_value=(self.spec, common.SPEC_SHA256),
                    ),
                    mock.patch.object(
                        development_probe,
                        "_tracked_input_preflight",
                        return_value=("c" * 40, "d" * 64),
                    ),
                    mock.patch.object(
                        development_probe,
                        "_validate_development_key_git_boundary",
                        return_value=key_path,
                    ),
                    mock.patch.object(
                        development_probe.secrets,
                        "token_bytes",
                        return_value=b"k" * 32,
                    ),
                    mock.patch.object(common, "blind_commitment", return_value="b" * 64),
                    mock.patch.object(
                        common,
                        "runtime_fingerprint",
                        return_value={"test_fixture": True},
                    ),
                    mock.patch.object(
                        common,
                        "utc_timestamp",
                        side_effect=[
                            "2026-07-29T00:00:00Z",
                            "2026-07-29T00:00:01Z",
                        ],
                    ),
                    mock.patch.object(
                        development_probe, "_generate_split", side_effect=error
                    ),
                ):
                    with self.assertRaises(type(error)):
                        development_probe.generate()
                self.assertTrue((root / "generation-start.dev.json").is_file())
                self.assertTrue((root / "generation-failure.dev.json").is_file())
                self.assertFalse((root / "generation-summary.dev.json").exists())
                self.assertFalse((root / "generation-completion.dev.json").exists())
                failure = json.loads(
                    (root / "generation-failure.dev.json").read_text(encoding="utf-8")
                )
                common.require_exact_keys(
                    failure,
                    development_probe._GENERATION_FAILURE_KEYS,
                    "test generation failure",
                )
                self.assertEqual(failure["error_type"], type(error).__name__)
                self.assertNotIn(secret_like, failure["message"])
                self.assertNotIn(opaque_code_like, failure["message"])
                self.assertLessEqual(len(failure["message"]), 512)
                if isinstance(error, RuntimeError):
                    self.assertIn("[redacted-key-like-value]", failure["message"])
                    self.assertIn("[redacted-opaque-code]", failure["message"])
                self.assertTrue(failure["development_closed"])

    def test_dev_r15_root_is_consumed_before_key_sampling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "dev-r15"
            key_path = root / "private" / "development-key.bin"
            with (
                mock.patch.object(development_probe, "DEV_ROOT", root),
                mock.patch.object(development_probe, "_assert_development_boundary"),
                mock.patch.object(
                    development_probe,
                    "_load_spec",
                    return_value=(self.spec, common.SPEC_SHA256),
                ),
                mock.patch.object(
                    development_probe,
                    "_tracked_input_preflight",
                    return_value=("c" * 40, "d" * 64),
                ),
                mock.patch.object(
                    development_probe,
                    "_validate_development_key_git_boundary",
                    return_value=key_path,
                ),
                mock.patch.object(
                    development_probe.secrets,
                    "token_bytes",
                    side_effect=KeyboardInterrupt(),
                ),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    development_probe.generate()
            self.assertTrue(root.is_dir())
            self.assertTrue((root / "private").is_dir())
            self.assertFalse(key_path.exists())
            self.assertFalse((root / "generation-start.dev.json").exists())
            with self.assertRaises(FileExistsError):
                root.mkdir(parents=True, exist_ok=False)

    def test_dev_r15_generation_stage_interruptions_never_create_completion(
        self,
    ) -> None:
        split_results = _development_generation_split_results()
        for failed_name in (
            "generation-summary.dev.json",
            "generation-seal.dev.json",
            "generation-completion.dev.json",
        ):
            with self.subTest(failed_name=failed_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "dev-r15"
                key_path = root / "private" / "development-key.bin"
                original_write = development_probe._write_json_exclusive

                def fail_stage(path: Path, value: object) -> str:
                    if path.name == failed_name:
                        raise OSError(f"injected interruption at {failed_name}")
                    return original_write(path, value)

                with (
                    mock.patch.object(development_probe, "DEV_ROOT", root),
                    mock.patch.object(development_probe, "_assert_development_boundary"),
                    mock.patch.object(
                        development_probe,
                        "_load_spec",
                        return_value=(self.spec, common.SPEC_SHA256),
                    ),
                    mock.patch.object(
                        development_probe,
                        "_tracked_input_preflight",
                        return_value=("c" * 40, "d" * 64),
                    ),
                    mock.patch.object(
                        development_probe,
                        "_validate_development_key_git_boundary",
                        return_value=key_path,
                    ),
                    mock.patch.object(
                        development_probe.secrets,
                        "token_bytes",
                        return_value=b"k" * 32,
                    ),
                    mock.patch.object(
                        common, "blind_commitment", return_value="b" * 64
                    ),
                    mock.patch.object(
                        common,
                        "runtime_fingerprint",
                        return_value={"test_fixture": True},
                    ),
                    mock.patch.object(
                        common, "utc_timestamp", return_value="2026-07-29T00:00:00Z"
                    ),
                    mock.patch.object(
                        development_probe,
                        "_generate_split",
                        side_effect=copy.deepcopy(split_results),
                    ),
                    mock.patch.object(
                        development_probe,
                        "_write_json_exclusive",
                        side_effect=fail_stage,
                    ),
                ):
                    with self.assertRaisesRegex(
                        OSError, f"injected interruption at {failed_name}"
                    ):
                        development_probe.generate()
                self.assertTrue((root / "generation-start.dev.json").is_file())
                self.assertTrue((root / "generation-failure.dev.json").is_file())
                self.assertFalse((root / "generation-completion.dev.json").exists())
                with self.assertRaises(FileExistsError):
                    root.mkdir(parents=True, exist_ok=False)

    def test_dev_r15_generation_failure_reporting_preserves_original_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "dev-r15"
            key_path = root / "private" / "development-key.bin"
            original_write = development_probe._write_json_exclusive

            def fail_failure_report(path: Path, value: object) -> str:
                if path.name == "generation-failure.dev.json":
                    raise OSError("failure report unavailable")
                return original_write(path, value)

            with (
                mock.patch.object(development_probe, "DEV_ROOT", root),
                mock.patch.object(development_probe, "_assert_development_boundary"),
                mock.patch.object(
                    development_probe,
                    "_load_spec",
                    return_value=(self.spec, common.SPEC_SHA256),
                ),
                mock.patch.object(
                    development_probe,
                    "_tracked_input_preflight",
                    return_value=("c" * 40, "d" * 64),
                ),
                mock.patch.object(
                    development_probe,
                    "_validate_development_key_git_boundary",
                    return_value=key_path,
                ),
                mock.patch.object(
                    development_probe.secrets, "token_bytes", return_value=b"k" * 32
                ),
                mock.patch.object(common, "blind_commitment", return_value="b" * 64),
                mock.patch.object(
                    common,
                    "runtime_fingerprint",
                    return_value={"test_fixture": True},
                ),
                mock.patch.object(
                    common,
                    "utc_timestamp",
                    side_effect=[
                        "2026-07-29T00:00:00Z",
                        "2026-07-29T00:00:01Z",
                    ],
                ),
                mock.patch.object(
                    development_probe,
                    "_generate_split",
                    side_effect=RuntimeError("original generation failure"),
                ),
                mock.patch.object(
                    development_probe,
                    "_write_json_exclusive",
                    side_effect=fail_failure_report,
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "original generation failure"
                ) as raised:
                    development_probe.generate()
            self.assertTrue(
                any(
                    "failure reporting also failed" in note
                    for note in getattr(raised.exception, "__notes__", [])
                )
            )

    def test_dev_r15_generation_failure_messages_are_sanitized(self) -> None:
        secret_like = "a" * 64
        opaque_code_like = "c" * 24
        message = development_probe._sanitized_error_message(
            RuntimeError(
                f"key={secret_like} code={opaque_code_like} " + "x" * 700
            )
        )
        self.assertNotIn(secret_like, message)
        self.assertNotIn(opaque_code_like, message)
        self.assertIn("[redacted-key-like-value]", message)
        self.assertIn("[redacted-opaque-code]", message)
        self.assertLessEqual(len(message), 512)
        self.assertEqual(
            development_probe._sanitized_error_message(RuntimeError()),
            "exception without a message",
        )

    def test_dev_r15_exclusive_binary_write_rejects_existing_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "surface.png"
            first = development_probe._write_bytes_exclusive(path, b"first")
            self.assertEqual(first, hashlib.sha256(b"first").hexdigest())
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                development_probe._write_bytes_exclusive(path, b"second")
            self.assertEqual(path.read_bytes(), b"first")

    def test_dev_r15_public_preflight_requires_exact_generation_runtime(self) -> None:
        state, _boundary, _start, summary, _seal, _completion = (
            _development_generation_documents(self.spec)
        )
        receipts = {
            receipt["split"]: receipt for receipt in summary["splits"]
        }
        binding = {
            "generation_start_sha256": "0" * 64,
            "generation_summary_sha256": "1" * 64,
            "generation_seal_sha256": "2" * 64,
            "generation_completion_sha256": "3" * 64,
        }
        with (
            mock.patch.object(development_probe, "_assert_development_boundary"),
            mock.patch.object(
                development_probe,
                "_load_spec",
                return_value=(self.spec, common.SPEC_SHA256),
            ),
            mock.patch.object(
                development_probe,
                "_load_generation_state",
                return_value=(state, receipts, binding),
            ),
            mock.patch.object(
                development_probe,
                "_tracked_input_preflight",
                return_value=(
                    state["captured_git_head"],
                    state["implementation_bindings_sha256"],
                ),
            ),
            mock.patch.object(
                common, "runtime_fingerprint", return_value={"different": True}
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "runtime changed"):
                development_probe._public_preflight()

        with (
            mock.patch.object(development_probe, "_assert_development_boundary"),
            mock.patch.object(
                development_probe,
                "_load_spec",
                return_value=(self.spec, common.SPEC_SHA256),
            ),
            mock.patch.object(
                development_probe,
                "_load_generation_state",
                return_value=(state, receipts, binding),
            ),
            mock.patch.object(
                development_probe,
                "_tracked_input_preflight",
                return_value=(
                    state["captured_git_head"],
                    state["implementation_bindings_sha256"],
                ),
            ),
            mock.patch.object(common, "runtime_fingerprint", return_value=state["runtime"]),
            mock.patch.object(
                development_probe,
                "_prepare_public_split",
                side_effect=lambda _spec, _state, split, _receipt: {"split": split},
            ),
        ):
            loaded_spec, loaded_state, loaded_binding, prepared = (
                development_probe._public_preflight()
            )
        self.assertIs(loaded_spec, self.spec)
        self.assertEqual(loaded_state, state)
        self.assertEqual(loaded_binding, binding)
        self.assertEqual(set(prepared), {"calibration", "holdout"})

    def test_dev_r15_review_preflight_validates_both_splits_before_vision(self) -> None:
        state, _boundary, _start, summary, _seal, _completion = (
            _development_generation_documents(self.spec)
        )
        receipts = {
            receipt["split"]: receipt for receipt in summary["splits"]
        }
        binding = {
            "generation_start_sha256": "0" * 64,
            "generation_summary_sha256": "1" * 64,
            "generation_seal_sha256": "2" * 64,
            "generation_completion_sha256": "3" * 64,
        }
        with (
            mock.patch.object(
                development_probe,
                "_generation_preflight",
                return_value=(self.spec, state, binding, receipts),
            ),
            mock.patch.object(
                development_probe,
                "_prepare_public_split",
                side_effect=lambda _spec, _state, split, _receipt, **_options: {
                    "split": split
                },
            ) as prepare,
        ):
            loaded_spec, loaded_state, loaded_binding, prepared = (
                development_probe._review_preflight()
            )
        self.assertIs(loaded_spec, self.spec)
        self.assertEqual(loaded_state, state)
        self.assertEqual(loaded_binding, binding)
        self.assertEqual(set(prepared), {"calibration", "holdout"})
        self.assertEqual(
            prepare.call_args_list,
            [
                mock.call(
                    self.spec,
                    state,
                    "calibration",
                    receipts["calibration"],
                    require_completed_decisions=False,
                ),
                mock.call(
                    self.spec,
                    state,
                    "holdout",
                    receipts["holdout"],
                    require_completed_decisions=False,
                ),
            ],
        )

    def test_dev_r15_generation_receipt_detects_post_generation_public_rewrites(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "dev-r15"
            public_root = root / "public" / "calibration"
            public_root.mkdir(parents=True)
            payloads = {
                "manifest_path": b"manifest-at-generation\n",
                "blank_labels_path": b"blank-labels-at-generation\n",
                "review_index_path": b"review-index-at-generation\n",
            }
            paths = development_probe._expected_generation_split_paths("calibration")
            receipt: dict[str, object] = {
                "split": "calibration",
                "record_count": 220,
                "contact_sheet_count": 185,
                "review_board_count": 37,
            }
            for field, relative in paths.items():
                target = root / Path(relative)
                target.write_bytes(payloads[field])
                receipt[field] = relative
                receipt[field.replace("_path", "_sha256")] = hashlib.sha256(
                    payloads[field]
                ).hexdigest()

            with mock.patch.object(development_probe, "DEV_ROOT", root):
                captured = development_probe._verify_public_generation_receipt(
                    "calibration", receipt
                )
                self.assertEqual(captured, payloads)

                for field, relative in paths.items():
                    with self.subTest(field=field):
                        target = root / Path(relative)
                        original = target.read_bytes()
                        target.write_bytes(original + b"joint-rewrite")
                        with self.assertRaisesRegex(RuntimeError, "receipt SHA drift"):
                            development_probe._verify_public_generation_receipt(
                                "calibration", receipt
                            )
                        target.write_bytes(original)

                wrong_path = copy.deepcopy(receipt)
                wrong_path["review_index_path"] = "public/holdout/review-index.dev.json"
                with self.assertRaisesRegex(RuntimeError, "receipt path drift"):
                    development_probe._verify_public_generation_receipt(
                        "calibration", wrong_path
                    )

    def test_dev_r15_secret_regeneration_binds_preflight_surface_bytes(self) -> None:
        split = "calibration"
        regenerated_sheets: list[types.SimpleNamespace] = []
        recorded_sheets: list[dict[str, object]] = []
        contact_payloads: dict[str, bytes] = {}
        for index in range(185):
            source_path = f"controls/{split}/contact-sheets/sheet-{index:03d}.png"
            payload = f"sheet-{index}".encode("ascii")
            entry = {
                "path": source_path,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "item_codes": [f"{index:024x}"],
            }
            regenerated_sheets.append(
                types.SimpleNamespace(
                    path=source_path,
                    png_bytes=payload,
                    manifest_entry=lambda entry=entry: copy.deepcopy(entry),
                )
            )
            recorded = copy.deepcopy(entry)
            recorded["path"] = f"public/{split}/contact-sheets/{Path(source_path).name}"
            recorded_sheets.append(recorded)
            contact_payloads[recorded["path"]] = payload

        board_payloads: dict[str, bytes] = {}
        board_results: dict[int, tuple[list[str], bytes]] = {}
        board_pages: list[dict[str, object]] = []
        for page_index in range(1, 38):
            path = f"public/{split}/review-boards/review-page-{page_index:03d}.png"
            codes = [f"{page_index:024x}"]
            payload = f"board-{page_index}".encode("ascii")
            board_results[page_index] = (codes, payload)
            board_payloads[path] = payload
            board_pages.append(
                {
                    "page_index": page_index,
                    "path": path,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "item_codes": codes,
                }
            )

        def board_payload(
            _controls: list[object], _views: list[dict[str, object]], page_index: int
        ) -> tuple[list[str], bytes]:
            return board_results[page_index]

        manifest = {"contact_sheet_bundle": recorded_sheets}
        review_index = {"pages": board_pages}
        with (
            mock.patch.object(
                development_probe,
                "contact_sheet_pages",
                return_value=regenerated_sheets,
            ),
            mock.patch.object(
                development_probe, "_review_board_payload", side_effect=board_payload
            ),
        ):
            development_probe._verify_regenerated_review_surfaces(
                self.spec,
                split,
                [object()],
                manifest,
                review_index,
                contact_payloads,
                board_payloads,
            )

            changed_sheets = dict(contact_payloads)
            first_sheet = next(iter(changed_sheets))
            changed_sheets[first_sheet] += b"rewritten"
            with self.assertRaisesRegex(RuntimeError, "contact-sheet byte drift"):
                development_probe._verify_regenerated_review_surfaces(
                    self.spec,
                    split,
                    [object()],
                    manifest,
                    review_index,
                    changed_sheets,
                    board_payloads,
                )

            changed_boards = dict(board_payloads)
            first_board = next(iter(changed_boards))
            changed_boards[first_board] += b"rewritten"
            with self.assertRaisesRegex(RuntimeError, "review-board byte drift"):
                development_probe._verify_regenerated_review_surfaces(
                    self.spec,
                    split,
                    [object()],
                    manifest,
                    review_index,
                    contact_payloads,
                    changed_boards,
                )

            boolean_page_index = copy.deepcopy(review_index)
            boolean_page_index["pages"][0]["page_index"] = True
            with self.assertRaisesRegex(RuntimeError, "review-board index drift"):
                development_probe._verify_regenerated_review_surfaces(
                    self.spec,
                    split,
                    [object()],
                    manifest,
                    boolean_page_index,
                    contact_payloads,
                    board_payloads,
                )

    def test_dev_r15_contact_sheet_layout_is_canonical_and_code_ordered(self) -> None:
        split = "calibration"
        codes = [f"{index:024x}" for index in range(220)]
        entries: list[dict[str, object]] = []
        for view in self.spec["contact_sheets"]["views"]:
            view_id = str(view["id"])
            for page_index in range(1, 38):
                entries.append(
                    {
                        "view_id": view_id,
                        "scale_percent": int(view["scale_percent"]),
                        "source_crop_xywh": [
                            int(value) for value in view["source_crop_xywh"]
                        ],
                        "page_index": page_index,
                        "path": (
                            f"public/{split}/contact-sheets/"
                            f"{view_id}-page-{page_index:03d}.png"
                        ),
                        "sha256": "a" * 64,
                        "item_codes": codes[
                            (page_index - 1) * 6 : page_index * 6
                        ],
                    }
                )
        development_probe._verify_contact_sheet_layout(
            entries, self.spec, split, codes
        )

        cases = []
        unknown = copy.deepcopy(entries)
        unknown[0]["unexpected"] = True
        cases.append(("unknown field", unknown))
        wrong_path = copy.deepcopy(entries)
        wrong_path[0]["path"] = "public/holdout/contact-sheets/wrong.png"
        cases.append(("noncanonical path", wrong_path))
        wrong_order = copy.deepcopy(entries)
        wrong_order[0]["item_codes"][:2] = reversed(
            wrong_order[0]["item_codes"][:2]
        )
        cases.append(("code order", wrong_order))
        reordered_entries = copy.deepcopy(entries)
        reordered_entries[0], reordered_entries[1] = (
            reordered_entries[1],
            reordered_entries[0],
        )
        cases.append(("entry order", reordered_entries))
        wrong_geometry = copy.deepcopy(entries)
        wrong_geometry[0]["source_crop_xywh"][0] += 1
        cases.append(("view geometry", wrong_geometry))
        boolean_page = copy.deepcopy(entries)
        boolean_page[0]["page_index"] = True
        cases.append(("boolean page index", boolean_page))
        for label, candidate in cases:
            with self.subTest(label=label):
                with self.assertRaises(RuntimeError):
                    development_probe._verify_contact_sheet_layout(
                        candidate, self.spec, split, codes
                    )

    def test_dev_r15_blank_labels_are_exact_private_free_and_unreviewed(self) -> None:
        codes = [f"{index:024x}" for index in range(220)]
        state = {
            "spec_sha256": common.SPEC_SHA256,
            "implementation_bindings_sha256": "a" * 64,
            "blind_key_commitment": "b" * 64,
            "runtime": {"test_fixture": True},
        }
        manifest = {
            "runtime": state["runtime"],
            "contact_sheet_bundle": [],
        }
        blank = {
            "artifact": "microtexture-v2-r6-root-vision-labels",
            "schema_version": "microtexture-v2-r6-root-vision-labels/2",
            "split": "calibration",
            "spec_sha256": state["spec_sha256"],
            "manifest_sha256": "c" * 64,
            "implementation_bindings_sha256": state[
                "implementation_bindings_sha256"
            ],
            "blind_key_commitment": state["blind_key_commitment"],
            "runtime": state["runtime"],
            "contact_sheet_bundle": [],
            "reviewer": "Root",
            "items": [
                {
                    "anonymous_code": code,
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
                for code in codes
            ],
        }
        development_probe._validate_blank_labels(
            blank, "calibration", manifest, "c" * 64, state, codes
        )

        mutations: list[tuple[str, dict[str, object]]] = []
        for label, path, replacement in (
            ("spec binding", ("spec_sha256",), "d" * 64),
            ("code", ("items", 0, "anonymous_code"), "f" * 24),
            ("disposition", ("items", 0, "disposition"), "clean"),
            ("visibility", ("items", 0, "grain_visible"), False),
            ("severity", ("items", 0, "severity_0_to_3"), 0),
            ("review completion", ("items", 0, "reviewed_at_200_percent"), False),
            ("notes", ("items", 0, "notes"), "premature"),
        ):
            changed = copy.deepcopy(blank)
            target = changed
            for component in path[:-1]:
                target = target[component]
            target[path[-1]] = replacement
            mutations.append((label, changed))
        changed = copy.deepcopy(blank)
        changed["items"][0], changed["items"][1] = (
            changed["items"][1],
            changed["items"][0],
        )
        mutations.append(("code order", changed))
        changed = copy.deepcopy(blank)
        changed["items"][0]["private_role"] = "artifact"
        mutations.append(("private identity leak", changed))
        changed = copy.deepcopy(blank)
        changed["items"][0]["unexpected"] = True
        mutations.append(("item keyset", changed))
        for label, mutation in mutations:
            with self.subTest(label=label), self.assertRaises(RuntimeError):
                development_probe._validate_blank_labels(
                    mutation,
                    "calibration",
                    manifest,
                    "c" * 64,
                    state,
                    codes,
                )

    def test_dev_r15_review_board_uses_contractual_30px_headers(self) -> None:
        self.assertEqual(development_probe.REVIEW_HEADER_HEIGHT, 30)
        self.assertEqual(development_probe.REVIEW_ROW_HEIGHT, 414)
        control = types.SimpleNamespace(
            anonymous_code="0" * 24,
            control=np.zeros(
                (
                    int(self.spec["canvas"]["height"]),
                    int(self.spec["canvas"]["width"]),
                ),
                dtype=np.uint8,
            ),
        )
        codes, payload = development_probe._review_board_payload(
            [control], self.spec["contact_sheets"]["views"], 1
        )
        self.assertEqual(codes, ["0" * 24])
        with Image.open(io.BytesIO(payload)) as board:
            self.assertEqual(board.size, (2560, 2484))

    def test_dev_r15_review_crops_require_complete_generation_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "dev-r15"
            with (
                mock.patch.object(development_probe, "DEV_ROOT", root),
                mock.patch.object(
                    development_probe,
                    "_generation_preflight",
                    side_effect=RuntimeError(
                        "development generation terminal artifacts are incomplete"
                    ),
                ),
                mock.patch.object(development_probe.Image, "open") as open_image,
            ):
                with self.assertRaisesRegex(RuntimeError, "terminal artifacts"):
                    development_probe.review_crops("calibration", 1)
            open_image.assert_not_called()
            self.assertFalse((root / "public" / "calibration" / "review-crops").exists())

    def test_dev_r15_review_crops_emit_native_full_200_without_resizing(self) -> None:
        split = "calibration"
        page_index = 1
        relative = "public/calibration/review-boards/review-page-001.png"
        height = development_probe.REVIEW_ROW_HEIGHT * 6
        board = Image.new("RGB", (2560, height), (17, 23, 31))
        source_values = np.empty((384, 512, 3), dtype=np.uint8)
        source_values[:, :, 0] = np.arange(512, dtype=np.uint16) % 256
        source_values[:, :, 1] = np.arange(384, dtype=np.uint16)[:, None] % 256
        source_values[:, :, 2] = (
            source_values[:, :, 0].astype(np.uint16)
            + source_values[:, :, 1].astype(np.uint16)
        ) % 256
        source_panel = Image.fromarray(source_values, mode="RGB")
        board.paste(source_panel, (0, development_probe.REVIEW_HEADER_HEIGHT))
        encoded = io.BytesIO()
        board.save(encoded, format="PNG", compress_level=6, optimize=False)
        board.close()
        source_panel.close()
        prepared = {
            split: {
                "review_board_payloads": {relative: encoded.getvalue()},
            }
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "dev-r15"
            with (
                mock.patch.object(development_probe, "DEV_ROOT", root),
                mock.patch.object(
                    development_probe,
                    "_review_preflight",
                    return_value=(self.spec, {}, {}, prepared),
                ),
            ):
                development_probe.review_crops(split, page_index)

            output_root = root / "public" / split / "review-crops"
            native_paths = [
                output_root
                / f"review-page-{page_index:03d}-row-{row}-full-200-native.png"
                for row in range(1, 7)
            ]
            self.assertTrue(all(path.is_file() for path in native_paths))
            with Image.open(native_paths[0]) as native:
                self.assertEqual(native.size, (512, 384))
                self.assertEqual(native.mode, "RGB")
                self.assertTrue(np.array_equal(np.asarray(native), source_values))

    def test_dev_r15_all_surfaces_precede_any_private_population_audit(self) -> None:
        events: list[str] = []
        prepared = {
            split: {
                "manifest": {},
                "review_index": {},
                "contact_sheet_payloads": {},
                "review_board_payloads": {},
                "labels": {},
            }
            for split in ("calibration", "holdout")
        }

        def regenerate(
            _spec: dict[str, object],
            _key: bytes,
            split: str,
            _manifest: dict[str, object],
        ) -> list[types.SimpleNamespace]:
            events.append(f"regenerate:{split}")
            return [
                types.SimpleNamespace(
                    anonymous_code=f"{len(events):024x}",
                    private_role="artifact",
                    duplicate_audit_group=None,
                )
            ]

        def verify(
            _spec: dict[str, object],
            split: str,
            *_arguments: object,
        ) -> None:
            events.append(f"surface:{split}")

        def private_audit(
            _labels: dict[str, object],
            _records: list[dict[str, object]],
            context: str,
        ) -> None:
            events.append(f"private:{context.split()[0]}")

        def eligible(
            _controls: list[types.SimpleNamespace],
            _spec: dict[str, object],
        ) -> dict[str, str]:
            split = "calibration" if "private:calibration" in events else "holdout"
            events.append(f"eligible:{split}")
            return {"code": "cluster"}

        def population(
            _labels: dict[str, object],
            _clusters: dict[str, str],
            _spec: dict[str, object],
            split: str,
        ) -> dict[str, object]:
            events.append(f"population:{split}")
            return {"passed": True}

        with (
            mock.patch.object(
                development_probe, "_regenerate_controls", side_effect=regenerate
            ),
            mock.patch.object(
                development_probe,
                "_verify_regenerated_review_surfaces",
                side_effect=verify,
            ),
            mock.patch.object(
                common,
                "validate_private_vision_label_audits",
                side_effect=private_audit,
            ),
            mock.patch.object(
                development_probe, "_eligible_clusters", side_effect=eligible
            ),
            mock.patch.object(
                development_probe, "_population_audit", side_effect=population
            ),
        ):
            development_probe._regenerate_and_audit_population(
                self.spec, b"key", prepared
            )

        first_private = next(
            index for index, event in enumerate(events) if event.startswith("private:")
        )
        self.assertEqual(
            events[:first_private],
            [
                "regenerate:calibration",
                "surface:calibration",
                "regenerate:holdout",
                "surface:holdout",
            ],
        )
        self.assertEqual(
            [event for event in events if event.startswith("private:")],
            ["private:calibration", "private:holdout"],
        )
        first_population = next(
            index for index, event in enumerate(events) if event.startswith("population:")
        )
        self.assertEqual(
            [
                event
                for event in events[:first_population]
                if event.startswith("private:")
            ],
            ["private:calibration", "private:holdout"],
        )

    def test_dev_r7_failure_audit_preserves_initial_and_reconciled_evidence(
        self,
    ) -> None:
        repository = common.repository_root()
        history = self.spec["history"]
        self.assertEqual(
            history["dev_r7_failure_audit"], DEV_R7_FAILURE_AUDIT_RELATIVE
        )
        self.assertEqual(
            history["dev_r7_failure_audit_sha256"], DEV_R7_FAILURE_AUDIT_SHA256
        )
        relative = history["dev_r7_failure_audit"]
        payload = (repository / relative).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), DEV_R7_FAILURE_AUDIT_SHA256)
        audit = json.loads(payload.decode("utf-8"))
        self.assertEqual(
            audit["schema_version"],
            "microtexture-v2-r6-development-failure-audit/2",
        )
        vision = audit["vision_review"]
        self.assertFalse(vision["root_and_initial_independent_exact_logical_agreement"])
        self.assertEqual(
            vision["calibration_root_independent_initial_logical_difference_count"],
            31,
        )
        self.assertEqual(
            vision["holdout_root_independent_initial_logical_difference_count"],
            39,
        )
        self.assertTrue(vision["root_and_independent_logical_decisions_reconciled"])
        self.assertTrue(vision["canonical_matches_root_exactly_after_reconciliation"])
        secret = audit["secret_handling"]
        self.assertFalse(secret["blind_key_present_in_this_artifact"])
        self.assertFalse(secret["blind_key_value_logged_or_tracked"])
        self.assertTrue(
            secret["development_blind_key_persisted_in_ignored_closed_private_root"]
        )
        self.assertTrue(secret["development_blind_key_reuse_forbidden"])

    def test_dev_r8_failure_audit_is_bound_closed_and_premeasurement(self) -> None:
        repository = common.repository_root()
        history = self.spec["history"]
        self.assertEqual(
            history["dev_r8_status"], "failed-and-closed-before-measurement"
        )
        self.assertEqual(
            history["dev_r8_failure_audit"], DEV_R8_FAILURE_AUDIT_RELATIVE
        )
        self.assertEqual(
            history["dev_r8_failure_audit_sha256"], DEV_R8_FAILURE_AUDIT_SHA256
        )
        self.assertEqual(
            history["dev_r9_status"], "failed-and-closed-after-measurement"
        )
        self.assertEqual(
            history["dev_r10_status"], "failed-and-closed-during-generation"
        )
        self.assertEqual(
            history["dev_r11_status"], "failed-and-closed-before-measurement"
        )
        self.assertEqual(
            history["dev_r12_status"], "failed-and-closed-before-measurement"
        )
        self.assertEqual(
            history["dev_r13_status"], "failed-and-closed-before-measurement"
        )

        payload = (repository / DEV_R8_FAILURE_AUDIT_RELATIVE).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), DEV_R8_FAILURE_AUDIT_SHA256)
        audit = json.loads(payload.decode("utf-8"))
        common.validate_dev_r8_failure_audit(audit)

        self.assertEqual(
            audit["schema_version"],
            "microtexture-v2-r6-development-failure-audit/2",
        )
        self.assertEqual(
            audit["selection_status"], "not_started_population_gate_failed"
        )
        self.assertFalse(audit["measurement_started"])
        self.assertIsNone(audit["development_hard_threshold"])
        self.assertIsNone(audit["holdout_endpoint_performance"])
        one_shot = audit["one_shot_contract"]
        self.assertTrue(one_shot["r8_closed"])
        self.assertFalse(one_shot["numeric_metric_called"])
        self.assertFalse(one_shot["threshold_search_started"])
        self.assertTrue(
            one_shot[
                "rerun_relabel_retune_subset_topup_resample_or_reuse_for_r8_forbidden"
            ]
        )

        population = audit["population_audit"]
        self.assertTrue(
            population["all_non_tiny_speck_formal_endpoint_minimums_passed"]
        )
        self.assertTrue(
            population[
                "all_non_tiny_speck_development_safety_floors_passed"
            ]
        )
        for split, count in (("calibration", 3), ("holdout", 1)):
            split_population = population[split]
            self.assertFalse(split_population["passed"])
            self.assertEqual(split_population["tiny_speck_reject_clusters"], count)
            self.assertEqual(
                split_population["formal_minimum_failures"],
                [f"tiny_speck_reject_detection:{count}<4"],
            )
            self.assertEqual(
                split_population["development_safety_floor_failures"],
                [f"tiny_speck_reject_detection:{count}<6"],
            )

        self.assertEqual(
            audit["absent_measurement_artifacts"],
            {
                "calibration_measurements_present": False,
                "holdout_measurements_present": False,
                "analysis_result_present": False,
            },
        )
        successor = audit["successor_constraints"]
        self.assertTrue(
            successor[
                "r8_key_controls_labels_pixels_identities_measurements_and_root_reuse_forbidden"
            ]
        )
        secret = audit["secret_handling"]
        self.assertFalse(secret["blind_key_present_in_this_artifact"])
        self.assertFalse(secret["blind_key_value_logged_or_tracked"])
        self.assertFalse(secret["development_blind_key_bytes_disclosed_in_this_audit"])
        self.assertFalse(secret["private_labels_measurements_identities_or_pixels_tracked"])
        self.assertTrue(secret["development_blind_key_reuse_forbidden"])

        mutations: list[tuple[dict[str, object], str]] = []
        changed = copy.deepcopy(audit)
        changed["selection_status"] = "selected-and-passed"
        mutations.append((changed, "header/outcome"))
        changed = copy.deepcopy(audit)
        changed["absent_measurement_artifacts"][
            "calibration_measurements_present"
        ] = True
        mutations.append((changed, "artifact-absence"))
        changed = copy.deepcopy(audit)
        changed["population_audit"]["calibration"]["formal_minimum_failures"] = [
            "grain_reject_detection:3<8"
        ]
        mutations.append((changed, "population evidence"))
        changed = copy.deepcopy(audit)
        changed["successor_constraints"][
            "r8_key_controls_labels_pixels_identities_measurements_and_root_reuse_forbidden"
        ] = False
        mutations.append((changed, "successor constraint"))
        changed = copy.deepcopy(audit)
        changed["secret_handling"]["blind_key_present_in_this_artifact"] = True
        mutations.append((changed, "secret-handling"))
        changed = copy.deepcopy(audit)
        changed["unexpected"] = True
        mutations.append((changed, "keyset drift"))
        for mutation, message in mutations:
            with self.assertRaisesRegex(RuntimeError, message):
                common.validate_dev_r8_failure_audit(mutation)

    def test_dev_r9_failure_audit_is_bound_closed_and_fail_closed(self) -> None:
        repository = common.repository_root()
        history = self.spec["history"]
        self.assertEqual(
            history["dev_r9_status"], "failed-and-closed-after-measurement"
        )
        self.assertEqual(
            history["dev_r9_failure_audit"], DEV_R9_FAILURE_AUDIT_RELATIVE
        )
        self.assertEqual(
            history["dev_r9_failure_audit_sha256"], DEV_R9_FAILURE_AUDIT_SHA256
        )

        payload = (repository / DEV_R9_FAILURE_AUDIT_RELATIVE).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), DEV_R9_FAILURE_AUDIT_SHA256)
        audit = json.loads(payload.decode("utf-8"))
        common.validate_dev_r9_failure_audit(audit)

        self.assertEqual(audit["outcome"], "failed_closed")
        self.assertTrue(audit["measurement_started"])
        self.assertEqual(
            audit["selection_status"], "no-endpoint-admissible-threshold"
        )
        self.assertIsNone(audit["development_hard_threshold"])
        self.assertIsNone(audit["holdout_endpoint_performance"])
        self.assertTrue(audit["one_shot_contract"]["r9_closed"])
        self.assertTrue(
            audit["population_audit"]["all_formal_endpoint_population_minimums_passed"]
        )
        self.assertTrue(
            audit["population_audit"]["all_development_safety_floors_passed"]
        )
        self.assertEqual(audit["threshold_failure"]["candidate_count"], 69)
        severity3 = audit["threshold_failure"]["diagnostic_best_endpoint_rates"][
            "severity3_detection"
        ]
        self.assertEqual(severity3["detected_clusters"], 25)
        self.assertEqual(severity3["eligible_clusters"], 26)
        self.assertFalse(severity3["passed"])
        self.assertFalse(audit["secret_handling"]["blind_key_present_in_this_artifact"])
        self.assertTrue(
            audit["successor_constraints"][
                "r9_key_controls_labels_pixels_identities_measurements_threshold_diagnostics_nonces_commitments_and_root_reuse_forbidden"
            ]
        )

        mutations: list[tuple[str, dict[str, object]]] = []
        changed = copy.deepcopy(audit)
        changed["outcome"] = "passed"
        mutations.append(("outcome", changed))
        changed = copy.deepcopy(audit)
        changed["measurement_started"] = False
        mutations.append(("measurement_started", changed))
        changed = copy.deepcopy(audit)
        changed["selection_status"] = "selected-and-passed"
        mutations.append(("selection_status", changed))
        changed = copy.deepcopy(audit)
        changed["development_hard_threshold"] = 0.7661276645021775
        mutations.append(("development_hard_threshold", changed))
        changed = copy.deepcopy(audit)
        changed["one_shot_contract"]["r9_closed"] = False
        mutations.append(("one_shot_contract.r9_closed", changed))
        changed = copy.deepcopy(audit)
        changed["population_audit"]["calibration"]["passed"] = False
        mutations.append(("population_audit.calibration.passed", changed))
        changed = copy.deepcopy(audit)
        changed["threshold_failure"]["candidate_count"] = 68
        mutations.append(("threshold_failure.candidate_count", changed))
        changed = copy.deepcopy(audit)
        changed["threshold_failure"]["diagnostic_best_endpoint_rates"][
            "severity3_detection"
        ]["detected_clusters"] = 26
        mutations.append(("severity3 diagnostic", changed))
        changed = copy.deepcopy(audit)
        changed["hash_bindings"]["captured_repository_head"] = "0" * 40
        mutations.append(("hash binding", changed))
        changed = copy.deepcopy(audit)
        changed["secret_handling"]["blind_key_present_in_this_artifact"] = True
        mutations.append(("key secrecy", changed))
        changed = copy.deepcopy(audit)
        changed["successor_constraints"][
            "r9_key_controls_labels_pixels_identities_measurements_threshold_diagnostics_nonces_commitments_and_root_reuse_forbidden"
        ] = False
        mutations.append(("reuse constraints", changed))
        for label, path in (
            ("root cause unknown field", ("root_cause",)),
            ("secret unknown field", ("secret_handling",)),
            ("successor unknown field", ("successor_constraints",)),
            (
                "population endpoint unknown field",
                (
                    "population_audit",
                    "calibration",
                    "endpoints",
                    "clean_acceptance",
                ),
            ),
            ("threshold unknown field", ("threshold_failure",)),
            (
                "minimal impossibility unknown field",
                ("threshold_failure", "minimal_impossibility"),
            ),
        ):
            changed = copy.deepcopy(audit)
            target = changed
            for component in path:
                target = target[component]
            target["unexpected"] = "forbidden"
            mutations.append((label, changed))
        for label, mutation in mutations:
            with self.subTest(label=label), self.assertRaises(RuntimeError):
                common.validate_dev_r9_failure_audit(mutation)

    def test_dev_r10_generation_interruption_audit_is_bound_and_fail_closed(
        self,
    ) -> None:
        repository = common.repository_root()
        history = self.spec["history"]
        self.assertEqual(
            history["dev_r10_status"], "failed-and-closed-during-generation"
        )
        self.assertEqual(
            history["dev_r10_failure_audit"], DEV_R10_FAILURE_AUDIT_RELATIVE
        )
        self.assertEqual(
            history["dev_r10_failure_audit_sha256"], DEV_R10_FAILURE_AUDIT_SHA256
        )
        self.assertEqual(
            history["dev_r11_status"], "failed-and-closed-before-measurement"
        )
        self.assertEqual(
            history["dev_r12_status"], "failed-and-closed-before-measurement"
        )
        self.assertEqual(
            history["dev_r13_status"], "failed-and-closed-before-measurement"
        )

        payload = (repository / DEV_R10_FAILURE_AUDIT_RELATIVE).read_bytes()
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(), DEV_R10_FAILURE_AUDIT_SHA256
        )
        audit = json.loads(payload.decode("utf-8"))
        common.validate_dev_r10_generation_failure_audit(audit)

        self.assertEqual(audit["failure_phase"], "generation")
        self.assertIsNone(audit["process_exit_code"])
        self.assertFalse(audit["termination_cause_inferred"])
        self.assertFalse(audit["measurement_started"])
        self.assertIsNone(audit["development_hard_threshold"])
        self.assertIsNone(audit["holdout_endpoint_performance"])
        one_shot = audit["one_shot_contract"]
        self.assertTrue(one_shot["generation_invocation_started_exactly_once"])
        self.assertFalse(one_shot["generation_completed"])
        self.assertFalse(one_shot["root_vision_started"])
        self.assertFalse(one_shot["independent_vision_started"])
        self.assertFalse(one_shot["analysis_started"])
        self.assertFalse(one_shot["numeric_metric_called"])
        self.assertTrue(one_shot["closed_root_retained_unchanged"])
        self.assertTrue(one_shot["r10_closed"])
        observed = audit["observed_public_state"]
        self.assertEqual(observed["completed_public_splits"], ["calibration"])
        self.assertEqual(observed["missing_public_splits"], ["holdout"])
        self.assertFalse(observed["generation_summary_present"])
        self.assertFalse(observed["generation_seal_present"])
        self.assertFalse(observed["generation_completion_present"])
        self.assertFalse(observed["generated_pixels_vision_reviewed_for_this_audit"])
        self.assertFalse(observed["private_root_contents_inspected_for_this_audit"])
        secret = audit["secret_handling"]
        self.assertFalse(secret["blind_key_present_in_this_artifact"])
        self.assertFalse(secret["blind_key_value_logged_or_tracked"])
        self.assertFalse(
            secret["blind_key_bytes_or_private_identity_inspected_for_this_audit"]
        )
        self.assertTrue(
            audit["successor_constraints"][
                "r10_root_key_controls_references_pixels_identities_codes_commitments_labels_measurements_nonces_and_partial_public_surfaces_reuse_forbidden"
            ]
        )

        mutations: list[tuple[str, dict[str, object]]] = []
        for label, path, replacement in (
            ("outcome", ("outcome",), "passed"),
            ("failure phase", ("failure_phase",), "analysis"),
            ("exit code", ("process_exit_code",), 1),
            ("cause inference", ("termination_cause_inferred",), True),
            ("measurement", ("measurement_started",), True),
            (
                "generation completion",
                ("one_shot_contract", "generation_completed"),
                True,
            ),
            ("Vision", ("one_shot_contract", "root_vision_started"), True),
            ("analysis", ("one_shot_contract", "analysis_started"), True),
            (
                "terminal summary",
                ("observed_public_state", "generation_summary_present"),
                True,
            ),
            (
                "closed root",
                ("observed_public_state", "closed_development_root"),
                "tmp/map-production/microtexture-v2-r6-dev-r11",
            ),
            (
                "captured HEAD",
                ("captured_generation_binding", "captured_repository_head"),
                "0" * 40,
            ),
            (
                "reuse constraint",
                (
                    "successor_constraints",
                    "r10_public_pixels_labels_or_outputs_must_not_be_used_for_successor_tuning",
                ),
                False,
            ),
            (
                "secret disclosure",
                ("secret_handling", "blind_key_present_in_this_artifact"),
                True,
            ),
        ):
            changed = copy.deepcopy(audit)
            target = changed
            for component in path[:-1]:
                target = target[component]
            target[path[-1]] = replacement
            mutations.append((label, changed))
        for label, path in (
            ("top-level unknown field", ()),
            ("one-shot unknown field", ("one_shot_contract",)),
            ("public-state unknown field", ("observed_public_state",)),
            ("binding unknown field", ("captured_generation_binding",)),
            ("successor unknown field", ("successor_constraints",)),
            ("secret unknown field", ("secret_handling",)),
        ):
            changed = copy.deepcopy(audit)
            target = changed
            for component in path:
                target = target[component]
            target["unexpected"] = "forbidden"
            mutations.append((label, changed))
        for label, mutation in mutations:
            with self.subTest(label=label), self.assertRaises(RuntimeError):
                common.validate_dev_r10_generation_failure_audit(mutation)

    def test_dev_r11_premeasurement_failure_audit_is_strict_closed_and_private_free(
        self,
    ) -> None:
        history = self.spec["history"]
        self.assertEqual(
            history["dev_r11_status"], "failed-and-closed-before-measurement"
        )
        self.assertEqual(
            history["dev_r11_failure_audit"], DEV_R11_FAILURE_AUDIT_RELATIVE
        )
        self.assertEqual(
            history["dev_r11_failure_audit_sha256"], DEV_R11_FAILURE_AUDIT_SHA256
        )
        self.assertEqual(
            history["dev_r12_status"], "failed-and-closed-before-measurement"
        )
        self.assertEqual(
            history["dev_r13_status"], "failed-and-closed-before-measurement"
        )
        payload = (
            common.repository_root() / DEV_R11_FAILURE_AUDIT_RELATIVE
        ).read_bytes()
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(), DEV_R11_FAILURE_AUDIT_SHA256
        )
        audit = json.loads(payload.decode("utf-8"))

        common.validate_dev_r11_premeasurement_failure_audit(audit)

        self.assertEqual(
            audit["failure_phase"],
            "private-sentinel-audit-before-population-audit",
        )
        self.assertFalse(audit["measurement_started"])
        self.assertIsNone(audit["development_hard_threshold"])
        self.assertIsNone(audit["holdout_endpoint_performance"])
        one_shot = audit["one_shot_contract"]
        self.assertTrue(one_shot["generation_completed_exactly_once"])
        self.assertTrue(one_shot["review_preflight_invoked_exactly_once"])
        self.assertFalse(one_shot["private_sentinel_audit_passed"])
        self.assertFalse(one_shot["population_audit_started"])
        self.assertFalse(one_shot["numeric_metric_called"])
        self.assertTrue(one_shot["r11_closed"])
        private_failure = audit["private_audit_failure"]
        self.assertFalse(
            private_failure[
                "anonymous_code_page_row_private_identity_or_pixel_binding_tracked"
            ]
        )
        secret = audit["secret_handling"]
        self.assertFalse(secret["blind_key_present_in_this_artifact"])
        self.assertFalse(secret["blind_key_value_logged_or_tracked"])
        self.assertFalse(secret["anonymous_code_to_private_identity_mapping_tracked"])
        self.assertFalse(secret["private_labels_identities_or_pixels_tracked"])

    def test_dev_r11_premeasurement_failure_audit_mutations_fail_closed(
        self,
    ) -> None:
        payload = (
            common.repository_root() / DEV_R11_FAILURE_AUDIT_RELATIVE
        ).read_bytes()
        audit = json.loads(payload.decode("utf-8"))
        mutations: list[tuple[str, tuple[str, ...], object]] = [
            ("outcome", ("outcome",), "passed"),
            (
                "noncanonical timestamp",
                ("audit_recorded_at",),
                "2026-07-29T19:47:17.6903258+00:00",
            ),
            (
                "metric call",
                ("one_shot_contract", "numeric_metric_called"),
                True,
            ),
            (
                "review count exact type",
                ("vision_review", "calibration_records_reviewed_by_root"),
                True,
            ),
            (
                "vision SHA syntax",
                ("vision_review", "calibration_root_decisions_sha256"),
                "G" * 64,
            ),
            (
                "reconciliation hash",
                (
                    "vision_review",
                    "calibration_final_independent_decisions_sha256",
                ),
                audit["vision_review"][
                    "calibration_initial_independent_decisions_sha256"
                ],
            ),
            (
                "private code mapping",
                (
                    "private_audit_failure",
                    "anonymous_code_page_row_private_identity_or_pixel_binding_tracked",
                ),
                True,
            ),
            (
                "embedded code-to-identity mapping",
                ("private_audit_failure", "interpretation"),
                audit["private_audit_failure"]["interpretation"]
                + " anonymous_code=0123456789abcdef01234567 maps to private-id-1.",
            ),
            (
                "population artifact",
                ("measurement_artifacts", "population_audit_present"),
                True,
            ),
            (
                "captured HEAD syntax",
                ("hash_bindings", "captured_repository_head"),
                "0" * 39,
            ),
            (
                "authority hash syntax",
                ("hash_bindings", "preregistered_spec_sha256"),
                "Z" * 64,
            ),
            (
                "population failure evaluated",
                ("root_cause", "population_or_metric_failure_evaluated"),
                True,
            ),
            (
                "successor reuse",
                (
                    "successor_constraints",
                    "r11_root_key_controls_references_pixels_identities_codes_commitments_labels_measurements_nonces_and_public_surfaces_reuse_forbidden",
                ),
                False,
            ),
            (
                "blind key disclosure",
                ("secret_handling", "blind_key_present_in_this_artifact"),
                True,
            ),
            (
                "private identity mapping",
                (
                    "secret_handling",
                    "anonymous_code_to_private_identity_mapping_tracked",
                ),
                True,
            ),
        ]
        for label, path, replacement in mutations:
            changed = copy.deepcopy(audit)
            target = changed
            for component in path[:-1]:
                target = target[component]
            target[path[-1]] = replacement
            with self.subTest(label=label), self.assertRaises(RuntimeError):
                common.validate_dev_r11_premeasurement_failure_audit(changed)

        for label, path in (
            ("top-level unknown field", ()),
            ("one-shot unknown field", ("one_shot_contract",)),
            ("vision unknown field", ("vision_review",)),
            ("private-failure unknown field", ("private_audit_failure",)),
            ("hash-binding unknown field", ("hash_bindings",)),
            ("successor unknown field", ("successor_constraints",)),
            ("secret unknown field", ("secret_handling",)),
        ):
            changed = copy.deepcopy(audit)
            target = changed
            for component in path:
                target = target[component]
            target["unexpected"] = "forbidden"
            with self.subTest(label=label), self.assertRaises(RuntimeError):
                common.validate_dev_r11_premeasurement_failure_audit(changed)

    def test_dev_r12_population_failure_audit_is_strict_closed_and_private_free(
        self,
    ) -> None:
        history = self.spec["history"]
        self.assertEqual(
            history["dev_r12_status"], "failed-and-closed-before-measurement"
        )
        self.assertEqual(
            history["dev_r12_failure_audit"], DEV_R12_FAILURE_AUDIT_RELATIVE
        )
        self.assertEqual(
            history["dev_r12_failure_audit_sha256"], DEV_R12_FAILURE_AUDIT_SHA256
        )
        self.assertEqual(
            history["dev_r13_status"], "failed-and-closed-before-measurement"
        )
        payload = (
            common.repository_root() / DEV_R12_FAILURE_AUDIT_RELATIVE
        ).read_bytes()
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(), DEV_R12_FAILURE_AUDIT_SHA256
        )
        audit = json.loads(payload.decode("utf-8"))

        common.validate_dev_r12_premeasurement_population_failure_audit(audit)

        self.assertEqual(
            audit["failure_phase"],
            "private-audits-passed-then-premeasurement-population-audit",
        )
        self.assertEqual(
            audit["failure_class"], "warning-cluster-population-shortfall"
        )
        self.assertFalse(audit["measurement_started"])
        self.assertEqual(
            audit["selection_status"], "not_started_population_gate_failed"
        )
        self.assertIsNone(audit["development_hard_threshold"])
        self.assertIsNone(audit["calibration_endpoint_performance"])
        self.assertIsNone(audit["holdout_endpoint_performance"])
        self.assertIsNone(audit["threshold_selection_audit"])

        one_shot = audit["one_shot_contract"]
        self.assertTrue(one_shot["generation_completed_exactly_once"])
        self.assertTrue(one_shot["review_preflight_invoked_exactly_once"])
        self.assertTrue(one_shot["private_sentinel_audit_passed"])
        self.assertTrue(one_shot["population_audit_started_exactly_once"])
        self.assertFalse(one_shot["population_audit_passed"])
        self.assertFalse(one_shot["numeric_metric_called"])
        self.assertTrue(one_shot["postmortem_invoked_exactly_once"])
        self.assertTrue(one_shot["r12_closed"])

        self.assertTrue(audit["private_audit"]["all_splits_passed"])
        population = audit["population_audit"]
        self.assertFalse(population["passed"])
        expected_warning_counts = {"calibration": 10, "holdout": 9}
        for split, count in expected_warning_counts.items():
            split_population = population["splits"][split]
            formal = split_population["formal_endpoint_minimums"]
            development = split_population["development_safety_floors"]
            self.assertEqual(
                formal["warning_acceptance"]["unique_cluster_count"], count
            )
            self.assertEqual(
                development["warning_acceptance"]["unique_cluster_count"], count
            )
            self.assertEqual(
                development["warning_acceptance"][
                    "development_minimum_unique_clusters"
                ],
                13,
            )
            self.assertFalse(
                development["warning_acceptance"]["count_passed"]
            )
            self.assertEqual(
                [
                    endpoint_id
                    for endpoint_id, endpoint in development.items()
                    if not endpoint["count_passed"]
                ],
                ["warning_acceptance"],
            )
        self.assertTrue(
            population["splits"]["calibration"]["formal_endpoint_minimums_passed"]
        )
        self.assertFalse(
            population["splits"]["holdout"]["formal_endpoint_minimums_passed"]
        )
        self.assertTrue(audit["postmortem"]["read_only"])
        self.assertFalse(audit["postmortem"]["raw_output_tracked"])
        self.assertFalse(
            audit["postmortem"][
                "used_to_relabel_resample_subset_topup_retune_or_select_a_threshold"
            ]
        )
        self.assertFalse(
            audit["secret_handling"]["blind_key_present_in_this_artifact"]
        )
        self.assertFalse(
            audit["secret_handling"][
                "anonymous_code_to_private_identity_mapping_tracked"
            ]
        )

    def test_dev_r12_population_failure_audit_mutations_fail_closed(self) -> None:
        payload = (
            common.repository_root() / DEV_R12_FAILURE_AUDIT_RELATIVE
        ).read_bytes()
        audit = json.loads(payload.decode("utf-8"))
        mutations: list[tuple[str, tuple[str, ...], object]] = [
            ("outcome", ("outcome",), "passed"),
            (
                "noncanonical timestamp",
                ("audit_recorded_at",),
                "2026-07-29T23:53:58.7591905+00:00",
            ),
            ("measurement", ("measurement_started",), True),
            (
                "metric call",
                ("one_shot_contract", "numeric_metric_called"),
                True,
            ),
            (
                "population pass",
                ("one_shot_contract", "population_audit_passed"),
                True,
            ),
            (
                "postmortem count",
                ("one_shot_contract", "postmortem_invoked_exactly_once"),
                False,
            ),
            (
                "review exact type",
                ("vision_review", "records_per_split_per_reviewer"),
                True,
            ),
            (
                "reconciliation SHA syntax",
                (
                    "vision_review",
                    "splits",
                    "calibration",
                    "canonical_final_decisions_sha256",
                ),
                "G" * 64,
            ),
            (
                "private mapping",
                (
                    "private_audit",
                    "anonymous_code_page_row_private_identity_or_pixel_binding_tracked",
                ),
                True,
            ),
            (
                "warning population count",
                (
                    "population_audit",
                    "splits",
                    "holdout",
                    "formal_endpoint_minimums",
                    "warning_acceptance",
                    "unique_cluster_count",
                ),
                10,
            ),
            (
                "development floor weakening",
                (
                    "population_audit",
                    "splits",
                    "calibration",
                    "development_safety_floors",
                    "warning_acceptance",
                    "development_minimum_unique_clusters",
                ),
                12,
            ),
            (
                "captured HEAD syntax",
                ("hash_bindings", "captured_repository_head"),
                "0" * 39,
            ),
            (
                "measurement artifact",
                (
                    "absent_measurement_artifacts",
                    "calibration_measurements_present",
                ),
                True,
            ),
            (
                "postmortem output tracked",
                ("postmortem", "raw_output_tracked"),
                True,
            ),
            (
                "successor reuse",
                (
                    "successor_constraints",
                    "r12_root_key_controls_references_pixels_identities_codes_commitments_labels_measurements_nonces_public_surfaces_and_postmortem_output_reuse_forbidden",
                ),
                False,
            ),
            (
                "blind key disclosure",
                ("secret_handling", "blind_key_present_in_this_artifact"),
                True,
            ),
        ]
        for label, path, replacement in mutations:
            changed = copy.deepcopy(audit)
            target = changed
            for component in path[:-1]:
                target = target[component]
            target[path[-1]] = replacement
            with self.subTest(label=label), self.assertRaises(RuntimeError):
                common.validate_dev_r12_premeasurement_population_failure_audit(
                    changed
                )

        for label, path in (
            ("top-level unknown field", ()),
            ("one-shot unknown field", ("one_shot_contract",)),
            ("vision unknown field", ("vision_review",)),
            ("vision split unknown field", ("vision_review", "splits", "holdout")),
            ("private-audit unknown field", ("private_audit",)),
            (
                "private split unknown field",
                ("private_audit", "splits", "calibration"),
            ),
            ("population unknown field", ("population_audit",)),
            (
                "population split unknown field",
                ("population_audit", "splits", "holdout"),
            ),
            ("failure-marker unknown field", ("failure_marker_summary",)),
            ("hash-binding unknown field", ("hash_bindings",)),
            ("absent-artifact unknown field", ("absent_measurement_artifacts",)),
            ("postmortem unknown field", ("postmortem",)),
            ("root-cause unknown field", ("root_cause",)),
            ("successor unknown field", ("successor_constraints",)),
            ("secret unknown field", ("secret_handling",)),
        ):
            changed = copy.deepcopy(audit)
            target = changed
            for component in path:
                target = target[component]
            target["unexpected"] = "forbidden"
            with self.subTest(label=label), self.assertRaises(RuntimeError):
                common.validate_dev_r12_premeasurement_population_failure_audit(
                    changed
                )

    def test_dev_r13_population_failure_audit_is_strict_closed_and_private_free(
        self,
    ) -> None:
        history = self.spec["history"]
        self.assertEqual(
            history["dev_r13_status"], "failed-and-closed-before-measurement"
        )
        self.assertEqual(
            history["dev_r13_failure_audit"], DEV_R13_FAILURE_AUDIT_RELATIVE
        )
        self.assertEqual(
            history["dev_r13_failure_audit_sha256"], DEV_R13_FAILURE_AUDIT_SHA256
        )
        self.assertEqual(
            history["dev_r14_status"], "failed-and-closed-before-measurement"
        )
        self.assertEqual(
            history["dev_r14_failure_audit"], DEV_R14_FAILURE_AUDIT_RELATIVE
        )
        self.assertEqual(
            history["dev_r14_failure_audit_sha256"], DEV_R14_FAILURE_AUDIT_SHA256
        )
        self.assertEqual(history["dev_r15_status"], "fresh-development-only")

        payload = (
            common.repository_root() / DEV_R13_FAILURE_AUDIT_RELATIVE
        ).read_bytes()
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(), DEV_R13_FAILURE_AUDIT_SHA256
        )
        audit = json.loads(payload.decode("utf-8"))
        common.validate_dev_r13_premeasurement_population_failure_audit(audit)

        self.assertEqual(
            audit["failure_phase"],
            "private-audits-passed-then-premeasurement-population-audit",
        )
        self.assertEqual(
            audit["failure_class"], "warning-cluster-population-shortfall"
        )
        self.assertFalse(audit["measurement_started"])
        self.assertEqual(
            audit["selection_status"], "not_started_population_gate_failed"
        )
        self.assertIsNone(audit["development_hard_threshold"])
        self.assertIsNone(audit["calibration_endpoint_performance"])
        self.assertIsNone(audit["holdout_endpoint_performance"])
        self.assertIsNone(audit["threshold_selection_audit"])

        one_shot = audit["one_shot_contract"]
        self.assertTrue(one_shot["generation_completed_exactly_once"])
        self.assertTrue(one_shot["root_vision_completed_before_private_reveal"])
        self.assertTrue(
            one_shot["independent_vision_completed_before_private_reveal"]
        )
        self.assertTrue(one_shot["all_440_records_reviewed_by_each_reviewer"])
        self.assertTrue(
            one_shot[
                "root_and_independent_decisions_reconciled_before_preflight"
            ]
        )
        self.assertTrue(one_shot["review_preflight_passed"])
        self.assertTrue(one_shot["labels_sealed_before_private_reveal"])
        self.assertTrue(one_shot["private_sentinel_audit_passed"])
        self.assertTrue(one_shot["population_audit_started_exactly_once"])
        self.assertFalse(one_shot["population_audit_passed"])
        self.assertTrue(one_shot["analysis_started_exactly_once"])
        self.assertFalse(one_shot["numeric_metric_called"])
        self.assertFalse(one_shot["threshold_search_started"])
        self.assertTrue(one_shot["postmortem_invoked_exactly_once"])
        self.assertTrue(one_shot["r13_closed"])

        vision = audit["vision_review"]
        self.assertEqual(vision["records_per_split_per_reviewer"], 220)
        self.assertEqual(vision["review_boards_per_split_per_reviewer"], 37)
        for split, difference_count in (("calibration", 62), ("holdout", 72)):
            review = vision["splits"][split]
            self.assertFalse(review["initial_exact_logical_agreement"])
            self.assertEqual(
                review["initial_logical_difference_count"], difference_count
            )
            self.assertTrue(review["reconciled"])
            self.assertEqual(
                review["root_final_decisions_sha256"],
                review["independent_final_decisions_sha256"],
            )
            self.assertEqual(
                review["root_final_decisions_sha256"],
                review["canonical_final_decisions_sha256"],
            )

        self.assertTrue(audit["private_audit"]["all_splits_passed"])
        population = audit["population_audit"]
        self.assertFalse(population["passed"])
        expected_warning_counts = {"calibration": 14, "holdout": 12}
        for split, count in expected_warning_counts.items():
            split_population = population["splits"][split]
            formal = split_population["formal_endpoint_minimums"]
            development = split_population["development_safety_floors"]
            self.assertEqual(
                formal["warning_acceptance"]["unique_cluster_count"], count
            )
            self.assertTrue(formal["warning_acceptance"]["count_passed"])
            self.assertEqual(
                development["warning_acceptance"]["unique_cluster_count"], count
            )
            self.assertEqual(
                development["warning_acceptance"][
                    "development_minimum_unique_clusters"
                ],
                13,
            )
            expected_development_pass = split == "calibration"
            self.assertEqual(
                development["warning_acceptance"]["count_passed"],
                expected_development_pass,
            )
            self.assertTrue(split_population["formal_endpoint_minimums_passed"])
            self.assertEqual(
                split_population["development_safety_floors_passed"],
                expected_development_pass,
            )
            self.assertEqual(split_population["passed"], expected_development_pass)
            self.assertEqual(
                [
                    endpoint_id
                    for endpoint_id, endpoint in development.items()
                    if not endpoint["count_passed"]
                ],
                [] if expected_development_pass else ["warning_acceptance"],
            )

        self.assertTrue(audit["postmortem"]["read_only"])
        self.assertFalse(audit["postmortem"]["raw_output_tracked"])
        self.assertFalse(
            audit["postmortem"][
                "used_to_relabel_resample_subset_topup_retune_or_select_a_threshold"
            ]
        )
        self.assertTrue(audit["failure_marker_summary"]["development_closed"])
        self.assertFalse(
            audit["secret_handling"]["blind_key_present_in_this_artifact"]
        )
        self.assertFalse(
            audit["secret_handling"][
                "anonymous_code_to_private_identity_mapping_tracked"
            ]
        )
        self.assertTrue(
            audit["successor_constraints"][
                "r13_root_key_controls_references_pixels_identities_codes_commitments_labels_measurements_nonces_public_surfaces_and_postmortem_output_reuse_forbidden"
            ]
        )

    def test_dev_r13_population_failure_audit_mutations_fail_closed(self) -> None:
        payload = (
            common.repository_root() / DEV_R13_FAILURE_AUDIT_RELATIVE
        ).read_bytes()
        audit = json.loads(payload.decode("utf-8"))
        mutations: list[tuple[str, tuple[str, ...], object]] = [
            ("outcome", ("outcome",), "passed"),
            (
                "noncanonical timestamp",
                ("audit_recorded_at",),
                "2026-08-15T05:48:52.1034314+00:00",
            ),
            ("measurement", ("measurement_started",), True),
            (
                "metric call",
                ("one_shot_contract", "numeric_metric_called"),
                True,
            ),
            (
                "population pass",
                ("one_shot_contract", "population_audit_passed"),
                True,
            ),
            (
                "analysis invocation",
                ("one_shot_contract", "analysis_started_exactly_once"),
                False,
            ),
            (
                "closed state",
                ("one_shot_contract", "r13_closed"),
                False,
            ),
            (
                "review exact type",
                ("vision_review", "records_per_split_per_reviewer"),
                True,
            ),
            (
                "initial difference count",
                (
                    "vision_review",
                    "splits",
                    "calibration",
                    "initial_logical_difference_count",
                ),
                61,
            ),
            (
                "reconciliation SHA syntax",
                (
                    "vision_review",
                    "splits",
                    "holdout",
                    "canonical_final_decisions_sha256",
                ),
                "G" * 64,
            ),
            (
                "private mapping",
                (
                    "private_audit",
                    "anonymous_code_page_row_private_identity_or_pixel_binding_tracked",
                ),
                True,
            ),
            (
                "warning population count",
                (
                    "population_audit",
                    "splits",
                    "holdout",
                    "formal_endpoint_minimums",
                    "warning_acceptance",
                    "unique_cluster_count",
                ),
                13,
            ),
            (
                "development floor weakening",
                (
                    "population_audit",
                    "splits",
                    "holdout",
                    "development_safety_floors",
                    "warning_acceptance",
                    "development_minimum_unique_clusters",
                ),
                12,
            ),
            (
                "captured HEAD syntax",
                ("hash_bindings", "captured_repository_head"),
                "0" * 39,
            ),
            (
                "measurement artifact",
                (
                    "absent_measurement_artifacts",
                    "calibration_measurements_present",
                ),
                True,
            ),
            (
                "postmortem output tracked",
                ("postmortem", "raw_output_tracked"),
                True,
            ),
            (
                "successor reuse",
                (
                    "successor_constraints",
                    "r13_root_key_controls_references_pixels_identities_codes_commitments_labels_measurements_nonces_public_surfaces_and_postmortem_output_reuse_forbidden",
                ),
                False,
            ),
            (
                "blind key disclosure",
                ("secret_handling", "blind_key_present_in_this_artifact"),
                True,
            ),
        ]
        for label, path, replacement in mutations:
            changed = copy.deepcopy(audit)
            target = changed
            for component in path[:-1]:
                target = target[component]
            target[path[-1]] = replacement
            with self.subTest(label=label), self.assertRaises(RuntimeError):
                common.validate_dev_r13_premeasurement_population_failure_audit(
                    changed
                )

        for label, path in (
            ("top-level unknown field", ()),
            ("one-shot unknown field", ("one_shot_contract",)),
            ("vision unknown field", ("vision_review",)),
            ("vision split unknown field", ("vision_review", "splits", "holdout")),
            ("private-audit unknown field", ("private_audit",)),
            (
                "private split unknown field",
                ("private_audit", "splits", "calibration"),
            ),
            ("population unknown field", ("population_audit",)),
            (
                "population split unknown field",
                ("population_audit", "splits", "holdout"),
            ),
            ("failure-marker unknown field", ("failure_marker_summary",)),
            ("hash-binding unknown field", ("hash_bindings",)),
            ("absent-artifact unknown field", ("absent_measurement_artifacts",)),
            ("postmortem unknown field", ("postmortem",)),
            ("root-cause unknown field", ("root_cause",)),
            ("successor unknown field", ("successor_constraints",)),
            ("secret unknown field", ("secret_handling",)),
        ):
            changed = copy.deepcopy(audit)
            target = changed
            for component in path:
                target = target[component]
            target["unexpected"] = "forbidden"
            with self.subTest(label=label), self.assertRaises(RuntimeError):
                common.validate_dev_r13_premeasurement_population_failure_audit(
                    changed
                )

    def test_dev_r14_population_failure_audit_is_strict_closed_and_private_free(
        self,
    ) -> None:
        payload = (
            common.repository_root() / DEV_R14_FAILURE_AUDIT_RELATIVE
        ).read_bytes()
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(), DEV_R14_FAILURE_AUDIT_SHA256
        )
        audit = json.loads(payload.decode("utf-8"))
        common.validate_dev_r14_premeasurement_population_failure_audit(audit)

        self.assertEqual(audit["development_edition"], "r14")
        self.assertEqual(audit["outcome"], "failed_closed")
        self.assertEqual(
            audit["failure_phase"],
            "private-audits-passed-then-premeasurement-population-audit",
        )
        self.assertEqual(
            audit["failure_class"],
            "development-safety-floor-microblob-shortfall",
        )
        self.assertFalse(audit["measurement_started"])
        self.assertEqual(
            audit["selection_status"], "not_started_population_gate_failed"
        )
        for field in (
            "development_hard_threshold",
            "calibration_endpoint_performance",
            "holdout_endpoint_performance",
            "threshold_selection_audit",
        ):
            self.assertIsNone(audit[field])

        one_shot = audit["one_shot_contract"]
        for field in (
            "generation_completed_exactly_once",
            "root_vision_completed_before_private_reveal",
            "independent_vision_completed_before_private_reveal",
            "all_440_records_reviewed_by_each_reviewer",
            "root_and_independent_decisions_reconciled_before_preflight",
            "review_preflight_invoked_exactly_once",
            "review_preflight_passed",
            "labels_sealed_before_private_reveal",
            "private_reveal_started_after_label_seal",
            "private_sentinel_audit_passed",
            "population_audit_started_exactly_once",
            "analysis_started_exactly_once",
            "postmortem_invoked_exactly_once",
            "failure_marker_created",
            "rerun_resume_relabel_retune_subset_topup_resample_or_reuse_for_r14_forbidden",
            "r14_closed",
        ):
            self.assertTrue(one_shot[field], field)
        for field in (
            "population_audit_passed",
            "numeric_metric_called",
            "threshold_search_started",
            "development_threshold_selected",
            "formal_cli_invoked",
            "formal_marker_created",
            "formal_threshold_created",
            "locked_clean_v18_decoded_or_measured",
        ):
            self.assertFalse(one_shot[field], field)

        vision = audit["vision_review"]
        self.assertEqual(vision["records_per_split_per_reviewer"], 220)
        self.assertEqual(vision["review_boards_per_split_per_reviewer"], 37)
        expected_reviews = {
            "calibration": {
                "root_initial_decisions_sha256": "bedb7e4be3491c6d1e5c51c42a0e7ddf86b757a6711cf0d54af9801149f45a99",
                "independent_initial_decisions_sha256": "a0483a39dc75fa82f3cd38c1ad1eccdf5befb86daefe66b8d90bfea5b388fbee",
                "initial_logical_difference_count": 69,
                "final_sha256": "e04386a90d202448769ca81155a959865fd5bfe7380c5380dc733c654f6efa8f",
                "completed_labels_sha256": "7973f80a28f4d6ef2d31766bdd271a1fee4eb01d504116db7086588c29c45bf1",
            },
            "holdout": {
                "root_initial_decisions_sha256": "ac82c2a045f767b68c6552d75097e492d113045e356dcaa5725e5d3a661b30a1",
                "independent_initial_decisions_sha256": "52dbd8c134274491df6e3fe4be086f0ee7f135a074e1ea46f8e867fc392bfe3e",
                "initial_logical_difference_count": 67,
                "final_sha256": "616d3517b5ec72a32925d86fb85928237410f15b9268851635da6ccdd3885bd1",
                "completed_labels_sha256": "35084d011f812aad0709af6f5babf02eb87ebc31e78e7612b8532dad9761a1c5",
            },
        }
        for split, expected in expected_reviews.items():
            review = vision["splits"][split]
            self.assertEqual(
                review["root_initial_decisions_sha256"],
                expected["root_initial_decisions_sha256"],
            )
            self.assertEqual(
                review["independent_initial_decisions_sha256"],
                expected["independent_initial_decisions_sha256"],
            )
            self.assertEqual(
                review["initial_logical_difference_count"],
                expected["initial_logical_difference_count"],
            )
            self.assertTrue(review["all_differences_reinspected_native_then_evidence"])
            self.assertTrue(review["reconciled"])
            self.assertEqual(
                review["root_final_decisions_sha256"], expected["final_sha256"]
            )
            self.assertEqual(
                review["independent_final_decisions_sha256"],
                expected["final_sha256"],
            )
            self.assertEqual(
                review["canonical_final_decisions_sha256"],
                expected["final_sha256"],
            )
            self.assertEqual(
                review["completed_labels_sha256"],
                expected["completed_labels_sha256"],
            )

        self.assertTrue(audit["private_audit"]["all_splits_passed"])
        population = audit["population_audit"]
        self.assertFalse(population["passed"])
        counts = {
            "calibration": [35, 15, 50, 13, 12, 12, 4, 16, 22, 11],
            "holdout": [31, 16, 53, 20, 11, 11, 9, 20, 22, 11],
        }
        formal_minima = [15, 10, 30, 4, 8, 4, 4, 8, 8, 6]
        development_floors = [19, 13, 38, 6, 10, 6, 6, 10, 10, 8]
        for split, split_counts in counts.items():
            split_population = population["splits"][split]
            formal = split_population["formal_endpoint_minimums"]
            development = split_population["development_safety_floors"]
            for index, endpoint_id in enumerate(common.EXPECTED_ENDPOINT_IDS):
                self.assertEqual(
                    formal[endpoint_id],
                    {
                        "unique_cluster_count": split_counts[index],
                        "minimum_unique_clusters": formal_minima[index],
                        "count_passed": split_counts[index] >= formal_minima[index],
                    },
                )
                self.assertEqual(
                    development[endpoint_id],
                    {
                        "unique_cluster_count": split_counts[index],
                        "development_minimum_unique_clusters": development_floors[
                            index
                        ],
                        "count_passed": split_counts[index]
                        >= development_floors[index],
                    },
                )
            expected_failed = (
                ["microblob_reject_detection"] if split == "calibration" else []
            )
            self.assertEqual(
                [
                    endpoint_id
                    for endpoint_id, endpoint in development.items()
                    if not endpoint["count_passed"]
                ],
                expected_failed,
            )
            self.assertTrue(split_population["formal_endpoint_minimums_passed"])
            self.assertEqual(
                split_population["development_safety_floors_passed"],
                split == "holdout",
            )
            self.assertEqual(split_population["passed"], split == "holdout")

        self.assertEqual(
            audit["hash_bindings"],
            {
                "captured_repository_head": "add29b765ed5d7b204a7f6f2a5d65033e855e4fe",
                "preregistered_spec_sha256": "9e76c949a7e6b126c6e44e8cc1acc89246812d58614a8513e757d18ce1f03833",
                "implementation_bindings_sha256": "88f138b312d3962bac50dc2f1b70b6fd47b41eee339aaf5495a74a7a13a23760",
                "dev_r13_failure_audit_sha256": DEV_R13_FAILURE_AUDIT_SHA256,
                "development_boundary_sha256": "73b9c00cd52dd05cf25e1302d80aa0b4a97cd3d2304170d0887f520351c7fd09",
                "generation_start_sha256": "391f6ef3cdb31fad2dbf6d049991a82a703912020b76c89ea52c63d0ef3e5a61",
                "generation_summary_sha256": "6a21e0110795726a8a43cf83d41b1321de8940bfedce622a2d66ba068ba54462",
                "generation_seal_sha256": "5d0cf91583e39a0dcf3109f36463f502721d8da60fc0026668e6c61cbfdf3693",
                "generation_completion_sha256": "c6065b3bb1124edeb77ad6931a1b5c841d5b12ff3c66f3176dca16262172bd4f",
                "blind_key_commitment": "994638c8e2126e6c77fa622386bae8f655d6ba5d2985758c0e9d73918649aebc",
                "calibration_manifest_sha256": "0ae90d95140d812c435ff0b284e664be7828cb9e7a62f4733e516cab5eaf3f3c",
                "calibration_blank_labels_sha256": "31d6852cf87ed3e8e37b74464fa448f66307b006f403e55737d425996771425d",
                "calibration_review_index_sha256": "7f41cadee5f3977df62a748dbc1dced9d117e7b874f7d4625056319f12263253",
                "holdout_manifest_sha256": "0651e9e8f165b5b6393af6b468c4b05894a8d6eea7ca70a6ab61500b3ae3a80c",
                "holdout_blank_labels_sha256": "be3c8e56fd1bc3a199e8c6081845205760ca10886057faa3788f0249159c1ca7",
                "holdout_review_index_sha256": "3393f92f94f9ca67b8c04f2ff9bebbc631bbd0f7a18ee3fba96a68f3783dfce2",
                "label_seal_receipt_sha256": "8eebd371c5e815d9170ac5a69efd04a6670206a0cb5504e90e468d2f29982f84",
                "population_audit_sha256": "62c825eca0f3b4b1476a70fa89393a1d5d45f50d03dad26dd3f4908d599c7137",
                "failure_marker_sha256": "9e2b917b9532490b51fb67eec7737597f472074f42b92ab828d1ba3d2f59ff5e",
            },
        )
        self.assertTrue(audit["postmortem"]["invoked_exactly_once"])
        self.assertTrue(audit["postmortem"]["read_only"])
        self.assertFalse(audit["postmortem"]["raw_output_tracked"])
        self.assertFalse(
            audit["postmortem"][
                "used_to_relabel_resample_subset_topup_retune_or_select_a_threshold"
            ]
        )
        self.assertTrue(audit["failure_marker_summary"]["development_closed"])
        self.assertFalse(audit["failure_marker_summary"]["measurement_started"])
        self.assertFalse(
            audit["secret_handling"]["blind_key_present_in_this_artifact"]
        )
        self.assertFalse(
            audit["secret_handling"][
                "anonymous_code_to_private_identity_mapping_tracked"
            ]
        )
        self.assertTrue(
            audit["successor_constraints"][
                "r14_root_key_controls_references_pixels_identities_codes_commitments_labels_measurements_nonces_public_surfaces_and_postmortem_output_reuse_forbidden"
            ]
        )

    def test_dev_r14_population_failure_audit_mutations_fail_closed(self) -> None:
        payload = (
            common.repository_root() / DEV_R14_FAILURE_AUDIT_RELATIVE
        ).read_bytes()
        audit = json.loads(payload.decode("utf-8"))
        mutations: list[tuple[str, tuple[str, ...], object]] = [
            ("outcome", ("outcome",), "passed"),
            (
                "noncanonical timestamp",
                ("audit_recorded_at",),
                "2026-08-15T08:38:46.7781772+00:00",
            ),
            ("failure class", ("failure_class",), "warning-cluster-population-shortfall"),
            ("measurement", ("measurement_started",), True),
            ("metric call", ("one_shot_contract", "numeric_metric_called"), True),
            (
                "population pass",
                ("one_shot_contract", "population_audit_passed"),
                True,
            ),
            ("closed state", ("one_shot_contract", "r14_closed"), False),
            (
                "review exact type",
                ("vision_review", "records_per_split_per_reviewer"),
                True,
            ),
            (
                "initial difference count",
                (
                    "vision_review",
                    "splits",
                    "calibration",
                    "initial_logical_difference_count",
                ),
                68,
            ),
            (
                "reconciliation SHA syntax",
                (
                    "vision_review",
                    "splits",
                    "holdout",
                    "canonical_final_decisions_sha256",
                ),
                "G" * 64,
            ),
            (
                "private mapping",
                (
                    "private_audit",
                    "anonymous_code_page_row_private_identity_or_pixel_binding_tracked",
                ),
                True,
            ),
            (
                "microblob population count",
                (
                    "population_audit",
                    "splits",
                    "calibration",
                    "formal_endpoint_minimums",
                    "microblob_reject_detection",
                    "unique_cluster_count",
                ),
                5,
            ),
            (
                "development floor weakening",
                (
                    "population_audit",
                    "splits",
                    "calibration",
                    "development_safety_floors",
                    "microblob_reject_detection",
                    "development_minimum_unique_clusters",
                ),
                4,
            ),
            (
                "calibration split pass",
                ("population_audit", "splits", "calibration", "passed"),
                True,
            ),
            (
                "captured HEAD syntax",
                ("hash_bindings", "captured_repository_head"),
                "0" * 39,
            ),
            (
                "generation binding",
                ("hash_bindings", "generation_completion_sha256"),
                "0" * 64,
            ),
            (
                "measurement artifact",
                (
                    "absent_measurement_artifacts",
                    "calibration_measurements_present",
                ),
                True,
            ),
            (
                "postmortem output tracked",
                ("postmortem", "raw_output_tracked"),
                True,
            ),
            (
                "successor reuse",
                (
                    "successor_constraints",
                    "r14_root_key_controls_references_pixels_identities_codes_commitments_labels_measurements_nonces_public_surfaces_and_postmortem_output_reuse_forbidden",
                ),
                False,
            ),
            (
                "blind key disclosure",
                ("secret_handling", "blind_key_present_in_this_artifact"),
                True,
            ),
        ]
        for label, path, replacement in mutations:
            changed = copy.deepcopy(audit)
            target = changed
            for component in path[:-1]:
                target = target[component]
            target[path[-1]] = replacement
            with self.subTest(label=label), self.assertRaises(RuntimeError):
                common.validate_dev_r14_premeasurement_population_failure_audit(
                    changed
                )

        for label, path in (
            ("top-level unknown field", ()),
            ("one-shot unknown field", ("one_shot_contract",)),
            ("vision unknown field", ("vision_review",)),
            ("vision split unknown field", ("vision_review", "splits", "holdout")),
            ("private-audit unknown field", ("private_audit",)),
            (
                "private split unknown field",
                ("private_audit", "splits", "calibration"),
            ),
            ("population unknown field", ("population_audit",)),
            (
                "population split unknown field",
                ("population_audit", "splits", "holdout"),
            ),
            ("failure-marker unknown field", ("failure_marker_summary",)),
            ("hash-binding unknown field", ("hash_bindings",)),
            ("absent-artifact unknown field", ("absent_measurement_artifacts",)),
            ("postmortem unknown field", ("postmortem",)),
            ("root-cause unknown field", ("root_cause",)),
            ("successor unknown field", ("successor_constraints",)),
            ("secret unknown field", ("secret_handling",)),
        ):
            changed = copy.deepcopy(audit)
            target = changed
            for component in path:
                target = target[component]
            target["unexpected"] = "forbidden"
            with self.subTest(label=label), self.assertRaises(RuntimeError):
                common.validate_dev_r14_premeasurement_population_failure_audit(
                    changed
                )

    def test_tracked_development_history_reads_through_dev_r14_in_order(self) -> None:
        repository = common.repository_root()
        captured_head = "c" * 40
        spec = copy.deepcopy(self.spec)
        history = spec["history"]
        history["dev_r14_failure_audit"] = DEV_R14_FAILURE_AUDIT_RELATIVE
        history["dev_r14_failure_audit_sha256"] = DEV_R14_FAILURE_AUDIT_SHA256
        relatives = [
            history[f"dev_r{edition}_failure_audit"]
            for edition in (7, 8, 9, 10, 11, 12, 13, 14)
        ]
        payloads = {
            relative: (repository / relative).read_bytes() for relative in relatives
        }

        def tracked_bytes(
            observed_repository: Path,
            observed_head: str,
            relative: str,
        ) -> bytes:
            self.assertEqual(observed_repository, repository)
            self.assertEqual(observed_head, captured_head)
            return payloads[relative]

        with mock.patch.object(
            common, "_tracked_worktree_bytes", side_effect=tracked_bytes
        ) as tracked:
            returned = common.verify_tracked_development_history(
                repository, captured_head, spec
            )
        self.assertEqual(returned, payloads[relatives[0]])
        self.assertEqual(
            [call.args[2] for call in tracked.call_args_list],
            relatives,
        )

        changed = copy.deepcopy(spec)
        changed["history"]["dev_r14_failure_audit_sha256"] = "0" * 64
        with (
            mock.patch.object(
                common, "_tracked_worktree_bytes", side_effect=tracked_bytes
            ),
            self.assertRaisesRegex(RuntimeError, "dev-r14 failure audit tracked SHA"),
        ):
            common.verify_tracked_development_history(
                repository, captured_head, changed
            )

    def test_dev_r14_history_and_dev_r15_guardrails_are_fail_closed(self) -> None:
        history = self.spec["history"]
        self.assertEqual(
            history["dev_r8_failure_audit"], DEV_R8_FAILURE_AUDIT_RELATIVE
        )
        self.assertEqual(
            history["dev_r8_failure_audit_sha256"], DEV_R8_FAILURE_AUDIT_SHA256
        )
        self.assertEqual(
            history["dev_r11_status"], "failed-and-closed-before-measurement"
        )
        self.assertEqual(
            history["dev_r11_failure_audit"], DEV_R11_FAILURE_AUDIT_RELATIVE
        )
        self.assertEqual(
            history["dev_r11_failure_audit_sha256"], DEV_R11_FAILURE_AUDIT_SHA256
        )
        self.assertEqual(
            history["dev_r12_status"], "failed-and-closed-before-measurement"
        )
        self.assertEqual(
            history["dev_r12_failure_audit"], DEV_R12_FAILURE_AUDIT_RELATIVE
        )
        self.assertEqual(
            history["dev_r12_failure_audit_sha256"], DEV_R12_FAILURE_AUDIT_SHA256
        )
        self.assertEqual(
            history["dev_r13_status"], "failed-and-closed-before-measurement"
        )
        self.assertEqual(
            history["dev_r13_failure_audit"], DEV_R13_FAILURE_AUDIT_RELATIVE
        )
        self.assertEqual(
            history["dev_r13_failure_audit_sha256"], DEV_R13_FAILURE_AUDIT_SHA256
        )
        self.assertEqual(
            history["dev_r14_status"], "failed-and-closed-before-measurement"
        )
        self.assertEqual(
            history["dev_r14_role"],
            "development-only premeasurement population failure evidence; both "
            "private audits passed, calibration microblob population 4 met formal "
            "minimum 4 but missed development floor 6, every other calibration endpoint "
            "and every holdout endpoint passed both minima, no numeric metric or threshold "
            "search started, and no dev-r14 root, key, control, reference, pixel, identity, "
            "code, commitment, label, measurement, nonce, public surface, or postmortem "
            "output is reusable",
        )
        self.assertEqual(
            history["dev_r14_failure_audit"], DEV_R14_FAILURE_AUDIT_RELATIVE
        )
        self.assertEqual(
            history["dev_r14_failure_audit_sha256"], DEV_R14_FAILURE_AUDIT_SHA256
        )
        self.assertEqual(history["dev_r15_status"], "fresh-development-only")
        self.assertEqual(
            history["dev_r15_role"],
            "fresh one-shot development role used only to verify the unchanged "
            "preregistered soft-unit metric after the closed dev-r14 calibration "
            "microblob development-floor failure; it changes only the seven calibration "
            "clear-reject microblob morphologies to preregistered compact finite-Gaussian "
            "anchors, preserves every other morphology and every endpoint minimum, "
            "requires a fresh isolated root, cryptographic blind key, identities, domains, "
            "nonces, controls, references, commitments, labels, and measurements, and can "
            "never become or supply formal authority",
        )
        guardrails = self.spec["metric_definition"][
            "score_reference_revision_guardrails"
        ]
        self.assertEqual(
            self.spec["metric_definition"]["score_reference_revision"],
            "dev-r8-soft-unit-robustness-v1",
        )
        self.assertTrue(guardrails["dev_r10_generation_interrupted_failed_closed"])
        self.assertTrue(
            guardrails["dev_r11_premeasurement_vision_gate_failed_closed"]
        )
        self.assertTrue(
            guardrails["dev_r12_premeasurement_population_gate_failed_closed"]
        )
        self.assertTrue(guardrails["fresh_successor_after_dev_r12_required"])
        self.assertTrue(
            guardrails[
                "dev_r8_measurement_or_threshold_reuse_forbidden_because_absent"
            ]
        )
        self.assertTrue(
            guardrails[
                "dev_r9_measurement_threshold_diagnostic_or_holdout_reuse_forbidden"
            ]
        )
        self.assertTrue(
            guardrails[
                "dev_r10_measurement_or_threshold_reuse_forbidden_because_absent"
            ]
        )
        self.assertTrue(
            guardrails[
                "dev_r11_measurement_or_threshold_reuse_forbidden_because_absent"
            ]
        )
        self.assertTrue(
            guardrails[
                "dev_r12_measurement_or_threshold_reuse_forbidden_because_absent"
            ]
        )
        self.assertNotIn("fresh_dev_r12_required", guardrails)
        self.assertNotIn("fresh_dev_r11_required", guardrails)
        self.assertNotIn("fresh_dev_r10_required", guardrails)
        self.assertNotIn("fresh_dev_r9_required", guardrails)
        self.assertNotIn("fresh_dev_r8_required", guardrails)

        for field, drift in (
            ("dev_r8_status", "failed-and-closed-after-measurement"),
            ("dev_r8_failure_audit", DEV_R7_FAILURE_AUDIT_RELATIVE),
            ("dev_r8_failure_audit_sha256", DEV_R7_FAILURE_AUDIT_SHA256),
            ("dev_r10_status", "fresh-development-only"),
            ("dev_r10_failure_audit", DEV_R9_FAILURE_AUDIT_RELATIVE),
            ("dev_r10_failure_audit_sha256", DEV_R9_FAILURE_AUDIT_SHA256),
            ("dev_r11_status", "formal-authority"),
            ("dev_r11_failure_audit", DEV_R10_FAILURE_AUDIT_RELATIVE),
            ("dev_r11_failure_audit_sha256", DEV_R10_FAILURE_AUDIT_SHA256),
            ("dev_r12_status", "fresh-development-only"),
            ("dev_r12_failure_audit", DEV_R11_FAILURE_AUDIT_RELATIVE),
            ("dev_r12_failure_audit_sha256", DEV_R11_FAILURE_AUDIT_SHA256),
            ("dev_r13_status", "formal-authority"),
            ("dev_r13_failure_audit", DEV_R12_FAILURE_AUDIT_RELATIVE),
            ("dev_r13_failure_audit_sha256", DEV_R12_FAILURE_AUDIT_SHA256),
            ("dev_r14_status", "formal-authority"),
            ("dev_r14_failure_audit", DEV_R13_FAILURE_AUDIT_RELATIVE),
            ("dev_r14_failure_audit_sha256", DEV_R13_FAILURE_AUDIT_SHA256),
            ("dev_r15_status", "formal-authority"),
        ):
            changed = copy.deepcopy(self.spec)
            changed["history"][field] = drift
            with self.assertRaisesRegex(
                RuntimeError, "closed-development provenance contract drift"
            ):
                common.validate_preregistered_spec(changed)
        changed = copy.deepcopy(self.spec)
        changed["history"]["unexpected"] = "forbidden"
        with self.assertRaisesRegex(RuntimeError, "development history keyset drift"):
            common.validate_preregistered_spec(changed)

    def test_population_anchor_authority_is_exact_and_fail_closed(self) -> None:
        common.validate_preregistered_spec(self.spec)
        anchor = self.spec["population_anchor_schedule"]
        self.assertEqual(
            anchor["development_premeasurement_safety_floors"],
            {
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
        )
        endpoints = {
            item["id"]: item
            for item in self.spec["threshold_selection"]["endpoint_definitions"]
        }
        self.assertEqual(endpoints["clean_acceptance"]["minimum_unique_clusters"], 15)
        self.assertEqual(endpoints["warning_acceptance"]["minimum_unique_clusters"], 10)
        self.assertEqual(endpoints["reject_detection"]["minimum_unique_clusters"], 30)
        self.assertEqual(
            endpoints["tiny_speck_reject_detection"]["minimum_unique_clusters"], 4
        )
        mutations: list[dict[str, object]] = []
        changed = copy.deepcopy(self.spec)
        changed["population_anchor_schedule"]["subset_selection_forbidden"] = False
        mutations.append(changed)
        changed = copy.deepcopy(self.spec)
        changed["population_anchor_schedule"]["tier_counts_per_artifact_family"][
            "clean-candidate"
        ] = 4
        mutations.append(changed)
        changed = copy.deepcopy(self.spec)
        changed["population_anchor_schedule"][
            "development_premeasurement_safety_floors"
        ]["tiny_speck_reject_detection"] = 5
        mutations.append(changed)
        changed = copy.deepcopy(self.spec)
        changed["population_anchor_schedule"][
            "non_target_morphology_change_forbidden"
        ] = False
        mutations.append(changed)
        changed = copy.deepcopy(self.spec)
        changed["population_anchor_schedule"][
            "calibration_microblob_clear_reject_anchor_manifest"
        ]["entries"][0]["variant_index"] = 0
        mutations.append(changed)
        changed = copy.deepcopy(self.spec)
        changed["population_anchor_schedule"][
            "calibration_microblob_clear_reject_anchor_schedule_sha256"
        ] = "0" * 64
        mutations.append(changed)
        changed = copy.deepcopy(self.spec)
        changed["population_anchor_schedule"]["unexpected"] = True
        mutations.append(changed)
        changed = copy.deepcopy(self.spec)
        del changed["population_anchor_schedule"]["key_resampling_forbidden"]
        mutations.append(changed)
        for mutation in mutations:
            with self.assertRaisesRegex(RuntimeError, "population-anchor"):
                common.validate_preregistered_spec(mutation)

    def test_imagegen_provenance_has_three_vision_acceptances(self) -> None:
        repository = Path(__file__).resolve().parents[3]

        def read_json(relative: str) -> dict[str, object]:
            return json.loads((repository / relative).read_text(encoding="utf-8"))

        def file_sha256(relative: str) -> str:
            return hashlib.sha256((repository / relative).read_bytes()).hexdigest()

        corpus = self.spec["foundation_corpus"]
        threshold = corpus["vision_qualification_minimum_score"]
        expected = {item["id"]: item["sha256"] for item in corpus["foundations"]}
        for item in corpus["foundations"]:
            self.assertEqual(file_sha256(item["path"]), item["sha256"])
        self.assertEqual(
            file_sha256(corpus["generation_chain"]),
            corpus["generation_chain_sha256"],
        )
        self.assertEqual(
            file_sha256(corpus["generation_receipt"]),
            corpus["generation_receipt_sha256"],
        )
        foundation_receipt = read_json(corpus["generation_receipt"])
        self.assertEqual(
            {
                item["id"]: (item["path"], item["sha256"])
                for item in foundation_receipt["adopted_outputs"]
            },
            {
                item["id"]: (item["path"], item["sha256"])
                for item in corpus["foundations"]
            },
        )
        self.assertEqual(
            (
                foundation_receipt["generation_chain"]["path"],
                foundation_receipt["generation_chain"]["sha256"],
            ),
            (corpus["generation_chain"], corpus["generation_chain_sha256"]),
        )
        root_review = read_json(corpus["root_vision_review"])
        independent_reviews = [
            read_json(binding["path"])
            for binding in corpus["independent_vision_reviews"]
        ]
        review_bindings = [
            {
                "path": corpus["root_vision_review"],
                "sha256": corpus["root_vision_review_sha256"],
            },
            *corpus["independent_vision_reviews"],
        ]
        for binding in review_bindings:
            self.assertEqual(file_sha256(binding["path"]), binding["sha256"])
        self.assertEqual(
            {
                item["path"]: item["sha256"]
                for item in foundation_receipt["review_bindings"]
            },
            {item["path"]: item["sha256"] for item in review_bindings},
        )
        self.assertEqual(
            {root_review["reviewer"]}
            | {review["reviewer"] for review in independent_reviews},
            {"Codex Root Vision", "Descartes the 2nd", "Ohm the 2nd"},
        )
        for review_index, review in enumerate([root_review, *independent_reviews]):
            results = review["candidates"] if review_index == 0 else review["results"]
            self.assertEqual({item["id"]: item["sha256"] for item in results}, expected)
            self.assertTrue(
                all(
                    item["decision"] == "approved" and item["score"] >= threshold
                    for item in results
                )
            )

        locked = self.spec["locked_clean_reference"]
        locked_threshold = locked["vision_qualification_minimum_score"]
        self.assertEqual(file_sha256(locked["repo_relative_path"]), locked["sha256"])
        for path_field, sha_field in (
            ("generation_chain", "generation_chain_sha256"),
            ("generation_receipt", "generation_receipt_sha256"),
            ("root_vision_review", "root_vision_review_sha256"),
            ("independent_vision_review", "independent_vision_review_sha256"),
        ):
            self.assertEqual(file_sha256(locked[path_field]), locked[sha_field])
        locked_receipt = read_json(locked["generation_receipt"])
        self.assertEqual(
            (
                locked_receipt["prompt_chain"]["path"],
                locked_receipt["prompt_chain"]["sha256"],
            ),
            (locked["generation_chain"], locked["generation_chain_sha256"]),
        )
        self.assertEqual(
            (
                locked_receipt["output"]["path"],
                locked_receipt["output"]["sha256"],
            ),
            (locked["repo_relative_path"], locked["sha256"]),
        )
        self.assertEqual(
            (
                locked_receipt["root_vision_review"]["path"],
                locked_receipt["root_vision_review"]["sha256"],
            ),
            (locked["root_vision_review"], locked["root_vision_review_sha256"]),
        )
        receipt_independent_reviews = {
            item["path"]: item["sha256"]
            for item in locked_receipt["independent_vision_reviews"]
        }
        self.assertEqual(
            receipt_independent_reviews[locked["independent_vision_review"]],
            locked["independent_vision_review_sha256"],
        )
        for path, expected_sha in receipt_independent_reviews.items():
            self.assertEqual(file_sha256(path), expected_sha)
        locked_paths = [
            locked["root_vision_review"],
            *[item["path"] for item in locked_receipt["independent_vision_reviews"]],
        ]
        locked_reviews = [read_json(path) for path in locked_paths]
        self.assertEqual(
            {review["reviewer"] for review in locked_reviews},
            {"Codex Root Vision", "Descartes the 2nd", "Ohm the 2nd"},
        )
        for review in locked_reviews:
            self.assertEqual(review["source"]["sha256"], locked["sha256"])
            self.assertGreaterEqual(review["score"], locked_threshold)
            self.assertEqual(
                review["decision"],
                "approved-as-r6-locked-clean-reference-candidate",
            )

    def test_sparse_positions_have_true_zero_and_no_forced_center(self) -> None:
        roi = (128, 96, 256, 192)
        with self.assertRaisesRegex(RuntimeError, "count must be positive"):
            _stratified_separated_integer_positions(
                np.random.default_rng(1),
                0,
                roi,
                margin=20,
                minimum_separation_px=10,
            )
        positions = _stratified_separated_integer_positions(
            np.random.default_rng(2),
            9,
            roi,
            margin=20,
            minimum_separation_px=10,
        )
        self.assertEqual(len(positions), 9)
        self.assertNotIn((256, 192), positions)
        self.assertTrue(all(148 <= x <= 363 and 116 <= y <= 267 for x, y in positions))
        self.assertTrue(
            all(
                max(abs(x1 - x2), abs(y1 - y2)) >= 10
                for index, (x1, y1) in enumerate(positions)
                for x2, y2 in positions[index + 1 :]
            )
        )

    def test_fine_grain_low_conditions_retain_sparse_nonzero_support(self) -> None:
        roi = (128, 96, 256, 192)
        outside = np.ones((384, 512), dtype=bool)
        outside[96:288, 128:384] = False
        for split in ("calibration", "holdout"):
            variants = _artifact_variants(split)["artifact-fine-grain"]
            self.assertEqual(len(variants), 20)
            sparse = [
                (index, parameters)
                for index, parameters in enumerate(variants)
                if parameters["design_tier"] == "clean-candidate"
            ]
            self.assertEqual(len(sparse), 5)
            for index, parameters in sparse:
                self.assertLessEqual(
                    parameters["support_fraction_in_metric_window"], 0.0022
                )
                delta = _render_unsigned_delta(
                    "artifact-fine-grain",
                    parameters,
                    np.random.default_rng(500 + index),
                    384,
                    512,
                    roi,
                )
                encoded = np.rint(delta).astype(np.int16)
                self.assertGreater(np.count_nonzero(encoded), 0)
                self.assertLessEqual(np.count_nonzero(encoded), 109)
                self.assertTrue(np.all(encoded[outside] == 0))

    def test_private_cluster_pairs_polarities_and_contact_sheet_geometry(self) -> None:
        controls = expected_controls(
            self.spec, "calibration", hashlib.sha256(b"r6-test-key").digest()
        )
        self.assertEqual(len(controls), 220)
        self.assertEqual(
            {item.foundation_id for item in controls}, {"v15", "v16", "v17"}
        )
        self.assertNotIn("v18", {item.foundation_id for item in controls})
        role_counts = {
            role: sum(item.private_role == role for item in controls)
            for role in {item.private_role for item in controls}
        }
        self.assertEqual(
            role_counts,
            {"artifact": 200, "protocol-zero": 16, "duplicate-audit": 4},
        )
        commitments = [
            commitment
            for item in controls
            for commitment in (
                item.control_commitment,
                item.reference_commitment,
                item.delta_commitment,
            )
        ]
        self.assertEqual(len(commitments), 660)
        self.assertEqual(len(set(commitments)), 660)
        self.assertEqual(len({item.control_sha256 for item in controls}), 220)
        self.assertEqual(len({item.reference_sha256 for item in controls}), 220)
        for view in self.spec["contact_sheets"]["views"]:
            left, top, width, height = view["source_crop_xywh"]
            panel_hashes = {
                hashlib.sha256(
                    np.ascontiguousarray(
                        item.control[top : top + height, left : left + width]
                    ).tobytes()
                ).hexdigest()
                for item in controls
            }
            self.assertEqual(len(panel_hashes), 220, view["id"])
        artifact_controls = [
            item for item in controls if item.private_role == "artifact"
        ]
        self.assertEqual(
            len({item.condition_cluster_id for item in artifact_controls}), 100
        )
        for cluster_id in {item.condition_cluster_id for item in artifact_controls}:
            pair = [
                item
                for item in artifact_controls
                if item.condition_cluster_id == cluster_id
            ]
            self.assertEqual({item.polarity for item in pair}, {-1, 1})
            dark = next(item for item in pair if item.polarity == -1)
            light = next(item for item in pair if item.polarity == 1)
            self.assertNotEqual(dark.reference_png, light.reference_png)
            self.assertTrue(
                np.array_equal(dark.requested_delta, -light.requested_delta)
            )
            dark_encoded_delta = dark.control.astype(np.int16) - dark.reference.astype(
                np.int16
            )
            light_encoded_delta = light.control.astype(
                np.int16
            ) - light.reference.astype(np.int16)
            self.assertTrue(
                np.array_equal(dark_encoded_delta, -light_encoded_delta),
                cluster_id,
            )
            x, y, width, height = self.spec["canvas"]["metric_window"]["xywh"]
            dark_metrics = measure(
                dark.control[y : y + height, x : x + width],
                dark.reference[y : y + height, x : x + width],
                self.spec["metric_definition"],
            )
            light_metrics = measure(
                light.control[y : y + height, x : x + width],
                light.reference[y : y + height, x : x + width],
                self.spec["metric_definition"],
            )
            self.assertEqual(dark_metrics, light_metrics, cluster_id)
        zero_controls = [
            item for item in controls if item.private_role == "protocol-zero"
        ]
        self.assertTrue(
            all(
                np.array_equal(item.control, item.reference)
                and not np.any(item.requested_delta)
                and item.control_sha256 == item.reference_sha256
                and item.control_commitment != item.reference_commitment
                for item in zero_controls
            )
        )
        for group in ("clean", "artifact"):
            duplicates = [
                item for item in controls if item.duplicate_audit_group == group
            ]
            self.assertEqual(len(duplicates), 2)
            self.assertNotEqual(duplicates[0].control_png, duplicates[1].control_png)
            self.assertNotEqual(
                duplicates[0].reference_png, duplicates[1].reference_png
            )
            self.assertTrue(
                np.array_equal(
                    duplicates[0].requested_delta, duplicates[1].requested_delta
                )
            )
            self.assertEqual(
                duplicates[0].delta_float32_sha256,
                duplicates[1].delta_float32_sha256,
            )
            encoded_residuals = [
                item.control.astype(np.int16) - item.reference.astype(np.int16)
                for item in duplicates
            ]
            self.assertTrue(np.array_equal(encoded_residuals[0], encoded_residuals[1]))
            if group == "clean":
                self.assertTrue(
                    all(
                        np.array_equal(item.control, item.reference)
                        for item in duplicates
                    )
                )
            else:
                self.assertTrue(
                    all(
                        not np.array_equal(item.control, item.reference)
                        for item in duplicates
                    )
                )
            x, y, width, height = self.spec["canvas"]["metric_window"]["xywh"]
            duplicate_metrics = [
                measure(
                    item.control[y : y + height, x : x + width],
                    item.reference[y : y + height, x : x + width],
                    self.spec["metric_definition"],
                )
                for item in duplicates
            ]
            self.assertEqual(duplicate_metrics[0], duplicate_metrics[1])
            for field in (
                "control_commitment",
                "reference_commitment",
                "delta_commitment",
            ):
                self.assertNotEqual(
                    getattr(duplicates[0], field), getattr(duplicates[1], field)
                )

        holdout_controls = expected_controls(
            self.spec, "holdout", hashlib.sha256(b"r6-test-key").digest()
        )
        self.assertNotEqual(
            self.spec["splits"]["calibration"]["public_nonce"],
            self.spec["splits"]["holdout"]["public_nonce"],
        )
        for field in ("anonymous_code", "control_id", "condition_cluster_id"):
            self.assertTrue(
                {getattr(item, field) for item in controls}.isdisjoint(
                    {getattr(item, field) for item in holdout_controls}
                ),
                field,
            )
        parameter_nonces = {
            value
            for item in controls
            for name, value in item.parameters.items()
            if name.endswith("_nonce")
        }
        holdout_parameter_nonces = {
            value
            for item in holdout_controls
            for name, value in item.parameters.items()
            if name.endswith("_nonce")
        }
        self.assertTrue(parameter_nonces)
        self.assertTrue(holdout_parameter_nonces)
        self.assertTrue(parameter_nonces.isdisjoint(holdout_parameter_nonces))
        nonzero_delta_hashes = {
            item.delta_float32_sha256 for item in controls if item.requested_delta.any()
        }
        holdout_nonzero_delta_hashes = {
            item.delta_float32_sha256
            for item in holdout_controls
            if item.requested_delta.any()
        }
        self.assertTrue(nonzero_delta_hashes.isdisjoint(holdout_nonzero_delta_hashes))
        zero_delta_hashes = {
            item.delta_float32_sha256
            for item in controls
            if not item.requested_delta.any()
        }
        holdout_zero_delta_hashes = {
            item.delta_float32_sha256
            for item in holdout_controls
            if not item.requested_delta.any()
        }
        self.assertEqual(len(zero_delta_hashes), 1)
        self.assertEqual(zero_delta_hashes, holdout_zero_delta_hashes)

    def test_contact_sheet_view_partition_rejects_schema_and_geometry_drift(
        self,
    ) -> None:
        settings = self.spec["contact_sheets"]
        metric = self.spec["canvas"]["metric_window"]["xywh"]
        common.validate_contact_sheet_view_partition(settings, metric)

        invalid_settings = []
        missing = copy.deepcopy(settings)
        missing["views"].pop()
        invalid_settings.append(missing)
        extra = copy.deepcopy(settings)
        extra["views"].append(copy.deepcopy(extra["views"][-1]))
        invalid_settings.append(extra)
        duplicate = copy.deepcopy(settings)
        duplicate["views"][2] = copy.deepcopy(duplicate["views"][1])
        invalid_settings.append(duplicate)
        swapped = copy.deepcopy(settings)
        swapped["views"][1]["id"], swapped["views"][2]["id"] = (
            swapped["views"][2]["id"],
            swapped["views"][1]["id"],
        )
        invalid_settings.append(swapped)
        overlap = copy.deepcopy(settings)
        overlap["views"][2]["source_crop_xywh"][0] -= 1
        invalid_settings.append(overlap)
        gap = copy.deepcopy(settings)
        gap["views"][2]["source_crop_xywh"][0] += 1
        invalid_settings.append(gap)
        outside_metric = copy.deepcopy(settings)
        outside_metric["views"][1]["source_crop_xywh"][0] = 0
        invalid_settings.append(outside_metric)
        full_drift = copy.deepcopy(settings)
        full_drift["views"][0]["source_crop_xywh"][0] += 1
        invalid_settings.append(full_drift)
        float_scale = copy.deepcopy(settings)
        float_scale["views"][1]["scale_percent"] = 400.0
        invalid_settings.append(float_scale)
        float_crop = copy.deepcopy(settings)
        float_crop["views"][1]["source_crop_xywh"][0] = 128.0
        invalid_settings.append(float_crop)
        negative_crop = copy.deepcopy(settings)
        negative_crop["views"][1]["source_crop_xywh"][2] = -128
        invalid_settings.append(negative_crop)
        non_nearest = copy.deepcopy(settings)
        non_nearest["resize"] = "bilinear"
        invalid_settings.append(non_nearest)
        false_quadrants = copy.deepcopy(settings)
        false_quadrants["all_four_400_percent_quadrants_required"] = 1
        invalid_settings.append(false_quadrants)
        below_panel = copy.deepcopy(settings)
        below_panel["label_band_position"] = "below-panel"
        invalid_settings.append(below_panel)
        legacy_label_origin = copy.deepcopy(settings)
        legacy_label_origin["label_origin_in_panel"] = [8, 392]
        del legacy_label_origin["label_origin_in_slot"]
        invalid_settings.append(legacy_label_origin)
        extra_legacy_label_origin = copy.deepcopy(settings)
        extra_legacy_label_origin["label_origin_in_panel"] = [8, 392]
        invalid_settings.append(extra_legacy_label_origin)
        label_origin_drift = copy.deepcopy(settings)
        label_origin_drift["label_origin_in_slot"] = [8, 8]
        invalid_settings.append(label_origin_drift)
        panel_origin_drift = copy.deepcopy(settings)
        panel_origin_drift["panel_origin_in_slot"] = [0, 0]
        invalid_settings.append(panel_origin_drift)
        overlap_allowed = copy.deepcopy(settings)
        overlap_allowed["label_panel_overlap_forbidden"] = False
        invalid_settings.append(overlap_allowed)
        font_drift = copy.deepcopy(settings)
        font_drift["label_font"] += " drift"
        invalid_settings.append(font_drift)
        binding_drift = copy.deepcopy(settings)
        binding_drift["label_binding"] += " drift"
        invalid_settings.append(binding_drift)
        for changed in invalid_settings:
            with self.assertRaises(RuntimeError):
                common.validate_contact_sheet_view_partition(changed, metric)

    def test_contact_sheet_code_band_precedes_each_exact_panel(self) -> None:
        controls = expected_controls(
            self.spec, "calibration", hashlib.sha256(b"r6-header-test").digest()
        )
        pages = contact_sheet_pages(self.spec, "calibration", controls)
        first = next(
            page
            for page in pages
            if page.view_id == "full-200" and page.page_index == 1
        )
        with Image.open(io.BytesIO(first.png_bytes)) as opened:
            sheet = np.array(opened, dtype=np.uint8)
        self.assertEqual(sheet.shape, (1242, 1024))
        by_code = {control.anonymous_code: control for control in controls}
        x, y, width, height = self.spec["canvas"]["metric_window"]["xywh"]
        for slot, code in enumerate(first.item_codes):
            column, row = slot % 2, slot // 2
            slot_x, slot_y = column * 512, row * 414
            header = sheet[slot_y : slot_y + 30, slot_x : slot_x + 512]
            panel = sheet[slot_y + 30 : slot_y + 414, slot_x : slot_x + 512]
            source = by_code[code].control[y : y + height, x : x + width]
            expected = np.repeat(np.repeat(source, 2, axis=0), 2, axis=1)
            expected_header = np.full((30, 512), 238, dtype=np.uint8)
            _draw_hex_label(expected_header, code, 8, 18, 0)
            self.assertTrue(np.array_equal(header, expected_header), (slot, code))
            self.assertTrue(np.all(header[:18] == 238), (slot, code))
            self.assertTrue(np.all(header[28:] == 238), (slot, code))
            self.assertTrue(np.array_equal(panel, expected), (slot, code))

    def test_authority_reload_rebinds_exact_secret_catalog_identity(self) -> None:
        reduced = copy.deepcopy(self.spec)
        key = bytes(range(32))
        controls = expected_controls(reduced, "calibration", key)
        pages = contact_sheet_pages(reduced, "calibration", controls)
        records = [
            {
                "anonymous_code": control.anonymous_code,
                "control_commitment": control.control_commitment,
                "reference_commitment": control.reference_commitment,
                "delta_commitment": control.delta_commitment,
            }
            for control in sorted(controls, key=lambda item: item.anonymous_code)
        ]
        runtime = {"fingerprint_sha256": "a" * 64}
        captured_head = "b" * 40
        commitment = ""
        manifest = {
            "artifact": "microtexture-v2-r6-control-manifest",
            "schema_version": "microtexture-v2-r6-control-manifest/3",
            "split": "calibration",
            "spec_sha256": common.SPEC_SHA256,
            "implementation_bindings_sha256": "c" * 64,
            "blind_key_commitment": commitment,
            "captured_git_head": captured_head,
            "runtime": runtime,
            "frozen_thresholds_sha256": None,
            "threshold_authority_receipt_sha256": None,
            "record_count": len(records),
            "records": records,
            "contact_sheet_bundle": [page.manifest_entry() for page in pages],
            "warning": "No identity fields; reveal is forbidden until labels and one-shot marker are accepted.",
        }
        report = {
            "identity_reveal": [
                {
                    "anonymous_code": control.anonymous_code,
                    "family": control.family,
                    "control_id": control.control_id,
                    "condition_cluster_id": control.condition_cluster_id,
                    "variant_index": control.variant_index,
                    "replicate": control.replicate,
                    "polarity": control.polarity,
                    "parameters": control.parameters,
                    "control_sha256": control.control_sha256,
                    "reference_sha256": control.reference_sha256,
                    "delta_float32_sha256": control.delta_float32_sha256,
                    "private_role": control.private_role,
                    "foundation_id": control.foundation_id,
                    "duplicate_audit_group": control.duplicate_audit_group,
                }
                for control in controls
            ]
        }
        with (
            mock.patch.object(common, "load_spec", return_value=reduced),
            mock.patch.object(common, "blind_key", return_value=key),
        ):
            commitment = common.blind_commitment(key)
            manifest["blind_key_commitment"] = commitment
            state = {"blind_key_commitment": commitment}
            common.validate_secret_catalog_report_binding(
                report, manifest, "calibration", state
            )
            changed = copy.deepcopy(report)
            changed["identity_reveal"][0]["control_id"] = "f" * 24
            with self.assertRaises(RuntimeError):
                common.validate_secret_catalog_report_binding(
                    changed, manifest, "calibration", state
                )
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                load_state = {
                    "artifact_root": root,
                    "blind_key_commitment": commitment,
                    "implementation_bindings_sha256": "c" * 64,
                    "runtime": runtime,
                }
                for page in pages:
                    common.write_bytes_exclusive(root, root / page.path, page.png_bytes)
                manifest_path = root / "controls/calibration/manifest.json"
                manifest_sha = common.write_json_exclusive(
                    root, manifest_path, manifest
                )
                loaded, loaded_sha = common.load_control_manifest(
                    "calibration",
                    load_state,
                    expected_captured_head=captured_head,
                    verify_payload_hashes=True,
                )
                self.assertEqual((loaded, loaded_sha), (manifest, manifest_sha))
                first_sheet = root / pages[0].path
                first_sheet.write_bytes(b"tampered")
                with self.assertRaises(RuntimeError):
                    common.load_control_manifest(
                        "calibration",
                        load_state,
                        expected_captured_head=captured_head,
                        verify_payload_hashes=True,
                    )

    def test_complete_catalog_reveal_enforces_role_cluster_contracts(self) -> None:
        controls = expected_controls(
            self.spec, "calibration", hashlib.sha256(b"r6-reveal-test-key").digest()
        )
        zero = np.zeros((192, 256), dtype=np.float32)
        zero_metrics = measure(zero, zero, self.spec["metric_definition"])
        reveal = [
            {
                "anonymous_code": control.anonymous_code,
                "family": control.family,
                "control_id": control.control_id,
                "condition_cluster_id": control.condition_cluster_id,
                "variant_index": control.variant_index,
                "replicate": control.replicate,
                "polarity": control.polarity,
                "parameters": control.parameters,
                "control_sha256": control.control_sha256,
                "reference_sha256": control.reference_sha256,
                "delta_float32_sha256": control.delta_float32_sha256,
                "private_role": control.private_role,
                "foundation_id": control.foundation_id,
                "duplicate_audit_group": control.duplicate_audit_group,
            }
            for control in controls
        ]
        report = {
            "measurements": [
                {
                    "anonymous_code": control.anonymous_code,
                    "metrics": copy.deepcopy(zero_metrics),
                }
                for control in controls
            ],
            "results_by_code": {
                control.anonymous_code: {
                    "hard_metric_value": 0.0,
                    "failed_hard_gate": False,
                    "passed": True,
                }
                for control in controls
            },
            "diagnostic_flags_by_code": {
                control.anonymous_code: [] for control in controls
            },
            "identity_reveal": reveal,
        }
        common.validate_results_measurements_and_reveal(
            report, self.spec, "calibration", "catalog reveal test", None
        )
        duplicate_index = next(
            index
            for index, item in enumerate(reveal)
            if item["private_role"] == "duplicate-audit"
            and item["duplicate_audit_group"] == "clean"
        )
        tampered_group = copy.deepcopy(report)
        tampered_group["identity_reveal"][duplicate_index]["duplicate_audit_group"] = (
            "artifact"
        )
        with self.assertRaises(RuntimeError):
            common.validate_results_measurements_and_reveal(
                tampered_group,
                self.spec,
                "calibration",
                "tampered duplicate group",
                None,
            )
        tampered_foundation = copy.deepcopy(report)
        original_foundation = reveal[duplicate_index]["foundation_id"]
        replacement_foundation = next(
            item["id"]
            for item in self.spec["foundation_corpus"]["foundations"]
            if item["id"] != original_foundation
        )
        tampered_foundation["identity_reveal"][duplicate_index]["foundation_id"] = (
            replacement_foundation
        )
        with self.assertRaisesRegex(RuntimeError, "cluster private-identity drift"):
            common.validate_results_measurements_and_reveal(
                tampered_foundation,
                self.spec,
                "calibration",
                "tampered duplicate foundation",
                None,
            )

        nonzero_metrics = copy.deepcopy(zero_metrics)
        nonzero_metrics["tiny_mass_l"] = 1.0
        nonzero_metrics.update(
            recompute_branch_scores(nonzero_metrics, self.spec["metric_definition"])
        )

        def replace_metrics(changed: dict[str, object], codes: list[str]) -> None:
            code_set = set(codes)
            for measurement in changed["measurements"]:
                if measurement["anonymous_code"] in code_set:
                    measurement["metrics"] = copy.deepcopy(nonzero_metrics)
            for code in codes:
                changed["results_by_code"][code]["hard_metric_value"] = nonzero_metrics[
                    "hard_composite_score"
                ]

        def codes_for(
            *, role: str, group: str | None = None, one_cluster: bool = False
        ) -> list[str]:
            matching = [
                item
                for item in reveal
                if item["private_role"] == role
                and item["duplicate_audit_group"] == group
            ]
            if not one_cluster:
                return [matching[0]["anonymous_code"]]
            cluster_id = matching[0]["condition_cluster_id"]
            return [
                item["anonymous_code"]
                for item in matching
                if item["condition_cluster_id"] == cluster_id
            ]

        protocol_nonzero = copy.deepcopy(report)
        replace_metrics(protocol_nonzero, codes_for(role="protocol-zero"))
        with self.assertRaisesRegex(RuntimeError, "protocol-zero metric drift"):
            common.validate_results_measurements_and_reveal(
                protocol_nonzero,
                self.spec,
                "calibration",
                "tampered protocol-zero metrics",
                None,
            )

        clean_duplicate_nonzero = copy.deepcopy(report)
        replace_metrics(
            clean_duplicate_nonzero,
            codes_for(role="duplicate-audit", group="clean", one_cluster=True),
        )
        with self.assertRaisesRegex(RuntimeError, "clean duplicate-audit metric drift"):
            common.validate_results_measurements_and_reveal(
                clean_duplicate_nonzero,
                self.spec,
                "calibration",
                "tampered clean duplicate metrics",
                None,
            )

        duplicate_unequal = copy.deepcopy(report)
        replace_metrics(
            duplicate_unequal,
            codes_for(role="duplicate-audit", group="artifact"),
        )
        with self.assertRaisesRegex(RuntimeError, "paired metric symmetry drift"):
            common.validate_results_measurements_and_reveal(
                duplicate_unequal,
                self.spec,
                "calibration",
                "tampered duplicate member metrics",
                None,
            )

        artifact_unequal = copy.deepcopy(report)
        replace_metrics(artifact_unequal, codes_for(role="artifact"))
        with self.assertRaisesRegex(RuntimeError, "paired metric symmetry drift"):
            common.validate_results_measurements_and_reveal(
                artifact_unequal,
                self.spec,
                "calibration",
                "tampered artifact polarity metrics",
                None,
            )

    def test_zero_metric_and_raw_score_recomputation_are_exact(self) -> None:
        definition = self.spec["metric_definition"]
        zero = np.zeros((192, 256), dtype=np.float32)
        result = measure(zero, zero, definition)
        common.validate_metric_values(result, self.spec, "test metrics")
        self.assertEqual(set(result), METRIC_FIELDS)
        self.assertEqual(result["eligible_pixels"], 49152)
        for field in METRIC_FIELDS - {"eligible_pixels"}:
            self.assertEqual(result[field], 0, field)
        self.assertEqual(
            recompute_branch_scores(result, definition),
            {field: result[field] for field in SCORE_FIELDS},
        )
        changed = copy.deepcopy(result)
        changed["spot_score"] = 0.25
        with self.assertRaisesRegex(RuntimeError, "recomputation drift"):
            common.validate_metric_values(changed, self.spec, "tampered metrics")
        with self.assertRaises(ValueError):
            measure(np.zeros((384, 512)), np.zeros((384, 512)), definition)
        for field, invalid in (
            ("eligible_pixels", True),
            ("tiny_mass_l", -1.0),
            ("parallel_pair_ratio", 1.01),
            ("hard_composite_score", 1.01),
        ):
            changed = copy.deepcopy(result)
            changed[field] = invalid
            with self.assertRaises(RuntimeError):
                common.validate_metric_values(changed, self.spec, "bad metrics")

    def test_polarity_symmetry_and_tiny_count_monotonic_ladder(self) -> None:
        definition = copy.deepcopy(self.spec["metric_definition"])
        definition["expected_shape_hw"] = [64, 80]
        zero = np.zeros((64, 80), dtype=np.float32)
        positions = [
            (8, 8),
            (8, 30),
            (8, 55),
            (25, 18),
            (25, 45),
            (42, 8),
            (42, 30),
            (42, 55),
            (55, 70),
        ]
        ladder = []
        for count in (1, 3, 6, 9):
            delta = zero.copy()
            for y, x in positions[:count]:
                delta[y, x] = 8.0
            positive = measure(delta, zero, definition)
            negative = measure(-delta, zero, definition)
            self.assertEqual(
                {field: positive[field] for field in SCORE_FIELDS},
                {field: negative[field] for field in SCORE_FIELDS},
            )
            ladder.append(positive)
        self.assertEqual(
            [item["tiny_component_count"] for item in ladder], [1, 3, 6, 9]
        )
        for field in ("tiny_mass_l", "spot_score"):
            values = [item[field] for item in ladder]
            self.assertEqual(values, sorted(values), field)

    def test_soft_unit_half_scale_and_no_finite_ceiling_for_every_branch(self) -> None:
        definition = self.spec["metric_definition"]
        references = definition["score_reference_constants"]
        zero = measure(
            np.zeros((192, 256), dtype=np.float32),
            np.zeros((192, 256), dtype=np.float32),
            definition,
        )
        cases = (
            (
                "grain_score",
                {
                    "grain_rms_l": references["grain_rms_l"],
                    "grain_coherence_2_to_13": 1.0,
                },
            ),
            (
                "grain_score",
                {
                    "grain_rms_l": references["grain_rms_l"],
                    "grain_occupancy_per_mp": references["grain_occupancy_per_mp"],
                },
            ),
            ("spot_score", {"tiny_mass_l": references["tiny_mass_l"]}),
            (
                "spot_score",
                {"tiny_component_count": int(references["tiny_component_count"])},
            ),
            (
                "spot_score",
                {
                    "multiscale_blob_strength_l_sqrt_px": references[
                        "multiscale_blob_strength_l_sqrt_px"
                    ]
                },
            ),
            (
                "finite_line_score",
                {"finite_line_peak_l": references["finite_line_peak_l"]},
            ),
            (
                "finite_line_score",
                {"finite_line_top4_mean_l": references["finite_line_top4_mean_l"]},
            ),
            (
                "parallel_bundle_score",
                {
                    "parallel_pair_peak_l": references["parallel_pair_peak_l"],
                    "parallel_matched_pair_count": int(
                        references["parallel_matched_pair_count"]
                    ),
                },
            ),
        )
        for branch, overrides in cases:
            raw = copy.deepcopy(zero)
            raw.update(overrides)
            scores = recompute_branch_scores(raw, definition)
            with self.subTest(branch=branch, overrides=overrides):
                self.assertAlmostEqual(scores[branch], 0.5, places=15)
                self.assertAlmostEqual(scores["hard_composite_score"], 0.5, places=15)
        ladder = []
        for multiple in (1.0, 2.0, 4.0, 10.0):
            raw = copy.deepcopy(zero)
            raw["tiny_mass_l"] = multiple * references["tiny_mass_l"]
            scores = recompute_branch_scores(raw, definition)
            ladder.append(scores["spot_score"])
        self.assertEqual(ladder, sorted(set(ladder)))
        self.assertEqual(ladder[0], 0.5)
        self.assertLess(ladder[-1], 1.0)
        self.assertAlmostEqual(ladder[-1], (2.0 / np.pi) * np.arctan(10.0), places=15)

    def test_finite_line_count_monotonic_ladder(self) -> None:
        definition = copy.deepcopy(self.spec["metric_definition"])
        definition["expected_shape_hw"] = [80, 96]
        zero = np.zeros((80, 96), dtype=np.float32)
        ladder = []
        for count in (1, 2, 3, 4):
            delta = zero.copy()
            for y in (20, 32, 44, 56)[:count]:
                delta[y, 24:72] = 8.0
            positive = measure(delta, zero, definition)
            negative = measure(-delta, zero, definition)
            self.assertEqual(
                {field: positive[field] for field in SCORE_FIELDS},
                {field: negative[field] for field in SCORE_FIELDS},
            )
            ladder.append(positive)
        for field in ("finite_line_top4_mean_l", "finite_line_score"):
            values = [item[field] for item in ladder]
            self.assertEqual(values, sorted(values), field)
        self.assertGreaterEqual(ladder[-1]["parallel_matched_pair_count"], 2)

    def test_absolute_morphology_floors_gate_weak_responses(self) -> None:
        definition = self.spec["metric_definition"]
        expected_floor = 4.5
        self.assertEqual(
            definition["spot_parameters"]["component_floor_l"], expected_floor
        )
        self.assertEqual(
            definition["finite_line_parameters"]["response_floor_l"], expected_floor
        )
        self.assertEqual(
            definition["parallel_pair_parameters"]["response_floor_l"],
            expected_floor,
        )

        weak_spot = np.zeros((32, 32), dtype=np.float32)
        weak_spot[16, 16] = np.float32(expected_floor - 0.01)
        strong_spot = weak_spot.copy()
        strong_spot[16, 16] = np.float32(expected_floor)
        self.assertEqual(_spot_metrics(weak_spot, definition)[0], 0)
        self.assertEqual(_spot_metrics(strong_spot, definition)[0], 1)

        weak_line_response = np.zeros((32, 32), dtype=np.float32)
        weak_line_response[16, 16] = np.float32(expected_floor - 0.01)
        strong_line_response = weak_line_response.copy()
        strong_line_response[16, 16] = np.float32(expected_floor)
        self.assertEqual(
            _finite_line_metrics([(0, 5.0, weak_line_response)], definition)[2],
            0,
        )
        self.assertEqual(
            _finite_line_metrics([(0, 5.0, strong_line_response)], definition)[2],
            1,
        )

        weak_parallel_response = np.zeros((64, 64), dtype=np.float32)
        for y, x in ((10, 10), (20, 10), (40, 30), (50, 30)):
            weak_parallel_response[y, x] = np.float32(expected_floor - 0.01)
        strong_parallel_response = np.where(
            weak_parallel_response > 0,
            np.float32(expected_floor),
            np.float32(0),
        )
        self.assertEqual(
            _parallel_metrics([(0, 15.0, weak_parallel_response)], definition)[2],
            0,
        )
        self.assertEqual(
            _parallel_metrics([(0, 15.0, strong_parallel_response)], definition)[2],
            2,
        )

    def test_weak_pair_ratio_cannot_drive_parallel_branch(self) -> None:
        definition = self.spec["metric_definition"]
        zero = np.zeros((192, 256), dtype=np.float32)
        raw = measure(zero, zero, definition)
        raw["parallel_pair_ratio"] = 0.999999
        raw["parallel_pair_peak_l"] = 0.01
        raw["parallel_matched_pair_count"] = 0
        scores = recompute_branch_scores(raw, definition)
        self.assertEqual(scores["parallel_bundle_score"], 0.0)
        self.assertEqual(scores["hard_composite_score"], 0.0)

    def test_parallel_branch_requires_distinct_same_filter_lines(self) -> None:
        definition = self.spec["metric_definition"]
        zero = np.zeros((192, 256), dtype=np.float32)

        def dash(length: int, width: int, amplitude: float) -> np.ndarray:
            result = zero.copy()
            top, left = 96 - width // 2, 128 - length // 2
            result[top : top + width, left : left + length] = amplitude
            return result

        for length, width, amplitude in (
            (6, 4, 10.0),
            (18, 4, 10.0),
            (24, 4, 11.0),
        ):
            metrics = measure(dash(length, width, amplitude), zero, definition)
            with self.subTest(length=length, width=width, amplitude=amplitude):
                self.assertEqual(metrics["parallel_pair_peak_l"], 0.0)
                self.assertEqual(metrics["parallel_matched_pair_count"], 0)
                self.assertEqual(metrics["parallel_bundle_score"], 0.0)

        reduced_definition = copy.deepcopy(definition)
        reduced_definition["expected_shape_hw"] = [64, 80]
        reduced_zero = np.zeros((64, 80), dtype=np.float32)
        for length in range(4, 25):
            for width in range(1, 5):
                single = reduced_zero.copy()
                top, left = 32 - width // 2, 40 - length // 2
                single[top : top + width, left : left + length] = 11.0
                metrics = measure(single, reduced_zero, reduced_definition)
                with self.subTest(catalog_length=length, catalog_width=width):
                    self.assertEqual(metrics["parallel_pair_peak_l"], 0.0)
                    self.assertEqual(metrics["parallel_matched_pair_count"], 0)
                    self.assertEqual(metrics["parallel_bundle_score"], 0.0)

        bundle = zero.copy()
        for top in (78, 94, 126, 142):
            bundle[top : top + 4, 116:140] = 11.0
        bundle_metrics = measure(bundle, zero, definition)
        self.assertGreater(bundle_metrics["parallel_pair_peak_l"], 0.0)
        self.assertGreater(bundle_metrics["parallel_matched_pair_count"], 0)
        self.assertGreater(bundle_metrics["parallel_bundle_score"], 0.0)

        strong_single_pair = np.zeros((64, 64), dtype=np.float32)
        strong_single_pair[10, 10] = 10.0
        strong_single_pair[20, 10] = 10.0
        weaker_two_pairs = np.zeros((64, 64), dtype=np.float32)
        for y, x in ((10, 30), (20, 30), (40, 30), (50, 30)):
            weaker_two_pairs[y, x] = 5.0
        pair_peak, pair_ratio, pair_count = _parallel_metrics(
            [
                (0, 23.0, strong_single_pair),
                (0, 15.0, weaker_two_pairs),
            ],
            definition,
        )
        self.assertEqual((pair_peak, pair_count), (5.0, 2))
        self.assertAlmostEqual(pair_ratio, 0.5)

    def test_r4_metric_names_and_thresholds_are_not_reusable(self) -> None:
        legacy_fields = {
            "microartifact_occupancy_per_mp",
            "microartifact_excess_energy_per_mp",
            "highpass_rms_l",
            "sparse_blob_score",
            "sparse_blob_peak_l",
            "sparse_blob_occupancy_pixels",
            "finite_line_occupancy_pixels",
            "parallel_valid_pair_count",
        }
        self.assertFalse(legacy_fields & METRIC_FIELDS)
        zero = np.zeros((192, 256), dtype=np.float32)
        changed = measure(zero, zero, self.spec["metric_definition"])
        changed["microartifact_occupancy_per_mp"] = 0.0
        with self.assertRaises(RuntimeError):
            common.validate_metric_values(changed, self.spec, "legacy metrics")
        threshold = {
            "metric": "microartifact_occupancy_per_mp",
            "direction": "maximum",
            "threshold": 0.5,
            "calibration_clean_cluster_acceptance": 1.0,
            "calibration_warning_cluster_acceptance": 1.0,
            "calibration_reject_cluster_detection": 1.0,
            "calibration_severity3_cluster_detection": 1.0,
            "selection_objective": self.spec["threshold_selection"]["objective_order"],
        }
        with self.assertRaises(RuntimeError):
            common.validate_hard_threshold(threshold, self.spec)

    def test_cluster_macro_is_invariant_to_duplicate_records(self) -> None:
        clusters = {"a": "x", "b": "x", "c": "y"}
        rejected = {"a": True, "b": True, "c": False}
        first = _cluster_macro_rate(["a", "c"], rejected, clusters, "reject")
        duplicate = _cluster_macro_rate(["a", "b", "c"], rejected, clusters, "reject")
        self.assertEqual(first[0], duplicate[0])
        self.assertEqual(first[2], duplicate[2])
        self.assertNotEqual(first[1], duplicate[1])

    def test_public_manifest_forbids_all_private_identity_fields(self) -> None:
        required = {
            "private_role",
            "foundation_id",
            "duplicate_audit_group",
            "control_sha256",
            "reference_sha256",
            "delta_float32_sha256",
        }
        self.assertTrue(required.issubset(common.FORBIDDEN_PUBLIC_IDENTITY_FIELDS))
        for field in sorted(required):
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(RuntimeError, "identity leak"),
            ):
                common._forbid_public_identity(
                    {"records": [{"anonymous_code": "a" * 24, field: "private-value"}]},
                    "calibration manifest",
                )

    def test_vision_evidence_notes_are_exact_and_fail_closed(self) -> None:
        code = "a" * 24
        manifest = {
            "runtime": {"fingerprint_sha256": "1" * 64},
            "contact_sheet_bundle": [],
            "records": [
                {
                    "anonymous_code": code,
                    "reference_commitment": "2" * 64,
                    "control_commitment": "3" * 64,
                    "delta_commitment": "4" * 64,
                }
            ],
        }
        state = {
            "implementation_bindings_sha256": "4" * 64,
            "blind_key_commitment": "5" * 64,
        }

        def validate(item: dict[str, object]) -> None:
            common.validate_vision_labels_payload(
                _vision_payload("calibration", [item], manifest, "6" * 64, state),
                "calibration",
                manifest,
                "6" * 64,
                state,
            )

        valid = [
            _vision_item(code, "clean"),
            _vision_item(code, "warning", visible_field="grain_visible"),
            _vision_item(code, "warning", visible_field="microblob_visible"),
            _vision_item(code, "reject", visible_field="short_line_visible"),
            _vision_item(code, "reject", visible_field="parallel_bundle_visible"),
        ]
        tiny_same_sector = _vision_item(
            code, "warning", visible_field="tiny_speck_visible"
        )
        tiny_same_sector["notes"] = (
            "ev3:g=-;t=NW-R1C1-N01,NW-R1C1-N02,NW-R1C1-N03;b=-;l=-;p=-"
        )
        valid.append(tiny_same_sector)
        combined = _vision_item(code, "reject", visible_field="parallel_bundle_visible")
        combined["microblob_visible"] = True
        combined["notes"] = "ev3:g=-;t=-;b=NW-R1C1-N01;l=NE-R2C2-N01;p=NE-R2C2-N01"
        valid.append(combined)
        for index, item in enumerate(valid):
            with self.subTest(valid=index):
                validate(item)

        invalid: list[dict[str, object]] = []
        invalid_notes = (
            "",
            "free-text",
            "ev3: g=-;t=-;b=-;l=-;p=-",
            "ev3:t=-;g=-;b=-;l=-;p=-",
            "ev3:g=-;t=-;b=-;l=-",
            "ev3:g=-;t=-;b=-;l=-;p=-;x=-",
            "ev3:g=-;t=-;b=-;l=-;p=-;",
            "ev3:g=NW-R1C1-N01;t=-;b=-;l=-;p=-",
            "ev3:g=nw-R1C1-N01;t=-;b=-;l=-;p=-",
            "ev3:g=NW-R0C1-N01;t=-;b=-;l=-;p=-",
            "ev3:g=NW-R1C4-N01;t=-;b=-;l=-;p=-",
            "ev3:g=NW-R1C1-N00;t=-;b=-;l=-;p=-",
        )
        for notes in invalid_notes:
            item = _vision_item(code, "clean")
            item["notes"] = notes
            invalid.append(item)

        duplicate = _vision_item(code, "warning", visible_field="tiny_speck_visible")
        duplicate["notes"] = "ev3:g=-;t=NW-R1C1-N01,NW-R1C1-N01,NW-R1C1-N02;b=-;l=-;p=-"
        invalid.append(duplicate)
        noncanonical = _vision_item(code, "warning", visible_field="tiny_speck_visible")
        noncanonical["notes"] = (
            "ev3:g=-;t=NE-R1C1-N01,NW-R1C1-N01,SE-R1C1-N01;b=-;l=-;p=-"
        )
        invalid.append(noncanonical)
        too_few_tiny = _vision_item(code, "warning", visible_field="tiny_speck_visible")
        too_few_tiny["notes"] = "ev3:g=-;t=NW-R1C1-N01,NE-R1C1-N01;b=-;l=-;p=-"
        invalid.append(too_few_tiny)
        missing_true = _vision_item(code, "warning", visible_field="short_line_visible")
        missing_true["notes"] = "ev3:g=-;t=-;b=-;l=-;p=-"
        invalid.append(missing_true)
        p_without_l = _vision_item(
            code, "reject", visible_field="parallel_bundle_visible"
        )
        p_without_l["short_line_visible"] = False
        p_without_l["notes"] = "ev3:g=-;t=-;b=-;l=-;p=NW-R2C2-N01"
        invalid.append(p_without_l)
        p_not_in_l = _vision_item(
            code, "reject", visible_field="parallel_bundle_visible"
        )
        p_not_in_l["notes"] = "ev3:g=-;t=-;b=-;l=NW-R2C2-N01;p=NE-R2C2-N01"
        invalid.append(p_not_in_l)

        for index, item in enumerate(invalid):
            with (
                self.subTest(invalid=index),
                self.assertRaisesRegex(RuntimeError, "(evidence|parallel)"),
            ):
                validate(item)

    def test_duplicate_semantics_are_private_post_marker_audits(self) -> None:
        first, second = "a" * 24, "b" * 24
        manifest = {
            "runtime": {"fingerprint_sha256": "1" * 64},
            "contact_sheet_bundle": [],
            "records": [
                {
                    "anonymous_code": first,
                    "reference_commitment": "2" * 64,
                    "control_commitment": "3" * 64,
                    "delta_commitment": "4" * 64,
                },
                {
                    "anonymous_code": second,
                    "reference_commitment": "5" * 64,
                    "control_commitment": "6" * 64,
                    "delta_commitment": "7" * 64,
                },
            ],
        }
        state = {
            "implementation_bindings_sha256": "4" * 64,
            "blind_key_commitment": "5" * 64,
        }
        payload = _vision_payload(
            "calibration",
            [
                _vision_item(first, "clean"),
                _vision_item(second, "warning", visible_field="short_line_visible"),
            ],
            manifest,
            "6" * 64,
            state,
        )
        public_labels = common.validate_vision_labels_payload(
            payload, "calibration", manifest, "6" * 64, state
        )
        self.assertEqual(
            [public_labels[code]["disposition"] for code in (first, second)],
            ["clean", "warning"],
        )

        labels, private_rows = _private_label_audit_fixture()
        clean_duplicate_codes = [
            row["anonymous_code"]
            for row in private_rows
            if row["duplicate_audit_group"] == "clean"
        ]
        labels[clean_duplicate_codes[1]] = _vision_item(
            clean_duplicate_codes[1],
            "warning",
            visible_field="short_line_visible",
        )
        with (
            mock.patch.object(calibration_harness, "measure") as measured,
            self.assertRaisesRegex(RuntimeError, "semantic disagreement"),
        ):
            common.validate_private_vision_label_audits(
                labels, private_rows, "post-marker audit"
            )
        measured.assert_not_called()

    def test_protocol_zero_semantics_are_private_post_marker_audits(self) -> None:
        code = "c" * 24
        manifest = {
            "runtime": {"fingerprint_sha256": "1" * 64},
            "contact_sheet_bundle": [],
            "records": [
                {
                    "anonymous_code": code,
                    "reference_commitment": "2" * 64,
                    "control_commitment": "3" * 64,
                    "delta_commitment": "4" * 64,
                }
            ],
        }
        state = {
            "implementation_bindings_sha256": "4" * 64,
            "blind_key_commitment": "5" * 64,
        }
        payload = _vision_payload(
            "calibration",
            [_vision_item(code, "reject", visible_field="microblob_visible")],
            manifest,
            "6" * 64,
            state,
        )
        public_labels = common.validate_vision_labels_payload(
            payload, "calibration", manifest, "6" * 64, state
        )
        self.assertEqual(public_labels[code]["disposition"], "reject")

        labels, private_rows = _private_label_audit_fixture()
        zero_code = next(
            row["anonymous_code"]
            for row in private_rows
            if row["private_role"] == "protocol-zero"
        )
        labels[zero_code] = _vision_item(
            zero_code, "reject", visible_field="microblob_visible"
        )
        with (
            mock.patch.object(calibration_harness, "measure") as measured,
            self.assertRaisesRegex(RuntimeError, "not labeled clean"),
        ):
            common.validate_private_vision_label_audits(
                labels, private_rows, "post-marker audit"
            )
        measured.assert_not_called()

    def test_obvious_artifact_duplicate_requires_matching_short_line_rejects(
        self,
    ) -> None:
        labels, private_rows = _private_label_audit_fixture()
        common.validate_private_vision_label_audits(
            labels, private_rows, "valid post-marker audit"
        )
        artifact_duplicate_codes = [
            row["anonymous_code"]
            for row in private_rows
            if row["duplicate_audit_group"] == "artifact"
        ]
        for code in artifact_duplicate_codes:
            labels[code] = _vision_item(
                code, "reject", visible_field="microblob_visible"
            )
        with (
            mock.patch.object(calibration_harness, "measure") as measured,
            self.assertRaisesRegex(RuntimeError, "obvious-artifact"),
        ):
            common.validate_private_vision_label_audits(
                labels, private_rows, "post-marker audit"
            )
        measured.assert_not_called()

    def test_endpoint_and_candidate_populations_are_artifact_only(self) -> None:
        scores = {
            "artifact-clean-dark": 0.1,
            "artifact-clean-light": 0.1,
            "artifact-reject-dark": 0.8,
            "artifact-reject-light": 0.8,
            "protocol-zero": 0.333333,
            "duplicate-audit": 0.777777,
        }
        measured = {
            code: {"anonymous_code": code, "metrics": {"hard_composite_score": value}}
            for code, value in scores.items()
        }
        labels = {
            "artifact-clean-dark": _vision_item("artifact-clean-dark", "clean"),
            "artifact-clean-light": _vision_item("artifact-clean-light", "clean"),
            "artifact-reject-dark": _vision_item(
                "artifact-reject-dark", "reject", visible_field="grain_visible"
            ),
            "artifact-reject-light": _vision_item(
                "artifact-reject-light", "reject", visible_field="grain_visible"
            ),
            "protocol-zero": _vision_item("protocol-zero", "clean"),
            "duplicate-audit": _vision_item(
                "duplicate-audit", "reject", visible_field="short_line_visible"
            ),
        }
        clusters = {
            "artifact-clean-dark": "cluster-clean",
            "artifact-clean-light": "cluster-clean",
            "artifact-reject-dark": "cluster-reject",
            "artifact-reject-light": "cluster-reject",
        }
        endpoints, _ = common.evaluate_endpoints_from_measurements(
            0.5, measured, labels, clusters, "calibration", self.spec
        )
        self.assertEqual(endpoints["clean_acceptance"]["record_count"], 2)
        self.assertEqual(endpoints["reject_detection"]["record_count"], 2)
        relaxed_spec = copy.deepcopy(self.spec)
        relaxed_spec["threshold_selection"]["admissibility"] = {
            "clean_cluster_acceptance_minimum": 0.0,
            "warning_cluster_acceptance_minimum": 0.0,
        }
        for endpoint in relaxed_spec["threshold_selection"]["endpoint_definitions"]:
            endpoint["minimum_unique_clusters"] = 0
            endpoint["calibration_minimum"] = 0.0
        _, _, _, _, audit = common.select_hard_threshold_from_measurements(
            measured, labels, clusters, relaxed_spec
        )
        expected = common.threshold_candidates([0.1, 0.8])
        self.assertEqual(
            [candidate["threshold"] for candidate in audit["candidates"]], expected
        )
        report = {
            "measurements": list(measured.values()),
            "identity_reveal": [
                {
                    "anonymous_code": code,
                    "private_role": role,
                    "condition_cluster_id": clusters.get(code),
                }
                for code, role in (
                    ("artifact-clean-dark", "artifact"),
                    ("artifact-clean-light", "artifact"),
                    ("artifact-reject-dark", "artifact"),
                    ("artifact-reject-light", "artifact"),
                    ("protocol-zero", "protocol-zero"),
                    ("duplicate-audit", "duplicate-audit"),
                )
            ],
        }
        self.assertEqual(
            common._calibration_candidate_thresholds(report, relaxed_spec), expected
        )

    def test_condition_cluster_truth_is_worst_case_and_single_population(self) -> None:
        clusters = {"dark": "shared-cluster", "light": "shared-cluster"}
        labels = {
            "dark": {
                "disposition": "reject",
                "severity_0_to_3": 3,
                "grain_visible": False,
                "tiny_speck_visible": True,
                "microblob_visible": False,
                "short_line_visible": False,
                "parallel_bundle_visible": False,
            },
            "light": {
                "disposition": "warning",
                "severity_0_to_3": 1,
                "grain_visible": False,
                "tiny_speck_visible": False,
                "microblob_visible": False,
                "short_line_visible": True,
                "parallel_bundle_visible": False,
            },
        }
        truth = common.aggregate_condition_cluster_truth(labels, clusters)
        self.assertEqual(
            truth,
            {
                "shared-cluster": {
                    "disposition": "reject",
                    "severity_0_to_3": 3,
                    "grain_visible": False,
                    "tiny_speck_visible": True,
                    "microblob_visible": False,
                    "short_line_visible": True,
                    "parallel_bundle_visible": False,
                }
            },
        )
        reversed_truth = common.aggregate_condition_cluster_truth(
            {"light": labels["light"], "dark": labels["dark"]},
            {"light": "shared-cluster", "dark": "shared-cluster"},
        )
        self.assertEqual(reversed_truth, truth)
        measured = {
            code: {
                "anonymous_code": code,
                "metrics": {"hard_composite_score": 0.9},
            }
            for code in clusters
        }
        endpoints, results = calibration_harness._evaluate_endpoints(
            0.5, measured, labels, clusters, "calibration"
        )
        self.assertEqual(
            endpoints["tiny_speck_reject_detection"]["unique_cluster_count"], 1
        )
        self.assertEqual(endpoints["warning_acceptance"]["unique_cluster_count"], 0)
        self.assertEqual(results["dark"], results["light"])

    def test_metric_equivalent_pair_is_required_before_selection(self) -> None:
        clusters = {"dark": "shared-cluster", "light": "shared-cluster"}
        measured = {
            "dark": {"metrics": {"hard_composite_score": 0.9}},
            "light": {"metrics": {"hard_composite_score": 0.8}},
        }
        with self.assertRaisesRegex(RuntimeError, "metric drift"):
            common.metric_equivalent_cluster_scores(
                measured, clusters, "hard_composite_score"
            )

    def test_endpoint_population_feasibility_is_exact_and_fail_closed(self) -> None:
        labels: dict[str, dict[str, object]] = {}
        clusters: dict[str, str] = {}

        def add_cluster(
            index: int,
            disposition: str,
            *,
            visible_field: str | None = None,
            severity: int | None = None,
        ) -> None:
            for polarity in ("dark", "light"):
                code = f"cluster-{index}-{polarity}"
                labels[code] = {
                    "disposition": disposition,
                    "severity_0_to_3": (
                        {"clean": 0, "warning": 1, "reject": 2}[disposition]
                        if severity is None
                        else severity
                    ),
                    "grain_visible": False,
                    "tiny_speck_visible": False,
                    "microblob_visible": False,
                    "short_line_visible": False,
                    "parallel_bundle_visible": False,
                }
                if visible_field is not None:
                    labels[code][visible_field] = True
                clusters[code] = f"cluster-{index}"

        for index in range(15):
            add_cluster(index, "clean")
        for index in range(15, 25):
            add_cluster(index, "warning", visible_field="grain_visible")
        reject_fields = (
            ["grain_visible"] * 8
            + ["tiny_speck_visible"] * 4
            + ["microblob_visible"] * 4
            + ["short_line_visible"] * 8
            + ["parallel_bundle_visible"] * 6
            + ["grain_visible"] * 5
        )
        for offset, visible_field in enumerate(reject_fields):
            add_cluster(
                25 + offset,
                "reject",
                visible_field=visible_field,
                severity=3 if offset < 4 else 2,
            )
        audit = common.validate_endpoint_population_counts(labels, clusters, self.spec)
        self.assertTrue(audit["passed"])
        self.assertEqual(
            audit["endpoints"]["grain_reject_detection"]["unique_cluster_count"],
            13,
        )
        changed = copy.deepcopy(labels)
        # Reduce the grain population to six, reproducing the r5 structural failure.
        for index in range(25, 32):
            for polarity in ("dark", "light"):
                code = f"cluster-{index}-{polarity}"
                changed[code]["grain_visible"] = False
                changed[code]["short_line_visible"] = True
        with self.assertRaisesRegex(RuntimeError, "grain_reject_detection=6<8"):
            common.validate_endpoint_population_counts(changed, clusters, self.spec)

    def test_threshold_candidates_and_exclusive_marker_are_fail_closed(self) -> None:
        self.assertEqual(
            _threshold_candidates([1.0, 3.0]),
            [0.0, 0.999999997, 2.0, 3.000000003],
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "marker.json"
            first_sha = write_json_exclusive(root, path, {"one_shot": True})
            self.assertEqual(len(first_sha), 64)
            with self.assertRaises(FileExistsError):
                write_json_exclusive(root, path, {"one_shot": True})

    def test_hard_threshold_rejects_boolean_negative_and_out_of_range_values(
        self,
    ) -> None:
        value = {
            "metric": "hard_composite_score",
            "direction": "maximum",
            "threshold": 0.5,
            "calibration_clean_cluster_acceptance": 1.0,
            "calibration_warning_cluster_acceptance": 0.8,
            "calibration_reject_cluster_detection": 0.95,
            "calibration_severity3_cluster_detection": 1.0,
            "selection_objective": self.spec["threshold_selection"]["objective_order"],
        }
        common.validate_hard_threshold(value, self.spec)
        for field, invalid in (
            ("threshold", -0.1),
            ("threshold", True),
            ("calibration_clean_cluster_acceptance", True),
            ("calibration_warning_cluster_acceptance", 1.01),
        ):
            changed = copy.deepcopy(value)
            changed[field] = invalid
            with self.assertRaises(RuntimeError):
                common.validate_hard_threshold(changed, self.spec)

    def test_single_threshold_selector_constrains_the_complete_gate(self) -> None:
        measured: dict[str, dict[str, object]] = {}
        labels: dict[str, dict[str, object]] = {}
        clusters: dict[str, str] = {}

        def add(
            code: str,
            value: float,
            disposition: str,
            severity: int,
            visible: str | None = None,
        ) -> None:
            for member in ("dark", "light"):
                record_code = f"{code}-{member}"
                measured[record_code] = {
                    "anonymous_code": record_code,
                    "metrics": {"hard_composite_score": value},
                }
                label = {
                    "disposition": disposition,
                    "severity_0_to_3": severity,
                    "grain_visible": False,
                    "tiny_speck_visible": False,
                    "microblob_visible": False,
                    "short_line_visible": False,
                    "parallel_bundle_visible": False,
                }
                if visible is not None:
                    label[visible] = True
                labels[record_code] = label
                clusters[record_code] = f"cluster-{code}"

        for index in range(15):
            add(f"clean-{index}", 0.0, "clean", 0)
        for index in range(10):
            add(
                f"warning-{index}",
                0.4 if index < 2 else 0.1,
                "warning",
                1,
                "grain_visible",
            )
        fields = (
            "grain_visible",
            "tiny_speck_visible",
            "microblob_visible",
            "short_line_visible",
            "parallel_bundle_visible",
        )
        for index in range(40):
            add(
                f"reject-{index}",
                0.3,
                "reject",
                3 if index < 4 else 2,
                fields[index // 8],
            )
        threshold, endpoints, _, status, audit = (
            calibration_harness._select_hard_threshold(measured, labels, clusters)
        )
        self.assertEqual(status, "selected-and-passed")
        self.assertIsNotNone(threshold)
        assert threshold is not None
        self.assertEqual(threshold["threshold"], 0.2)
        self.assertEqual(endpoints["warning_acceptance"]["cluster_macro_rate"], 0.8)
        self.assertEqual(endpoints["reject_detection"]["cluster_macro_rate"], 1.0)
        self.assertGreater(audit["admissible_candidate_count"], 0)
        self.assertEqual(audit["selected_threshold"], 0.2)
        common.validate_endpoint_performance(
            endpoints, self.spec, "calibration", "test endpoints"
        )
        common.validate_threshold_selection_audit(audit, self.spec, "test audit")
        changed_endpoints = copy.deepcopy(endpoints)
        changed_endpoints["clean_acceptance"]["record_count"] = True
        with self.assertRaises(RuntimeError):
            common.validate_endpoint_performance(
                changed_endpoints, self.spec, "calibration", "bad endpoints"
            )
        changed_audit = copy.deepcopy(audit)
        changed_audit["selected_objective"][0] = -1.0
        with self.assertRaises(RuntimeError):
            common.validate_threshold_selection_audit(
                changed_audit, self.spec, "bad audit"
            )

    def test_selector_never_promotes_a_diagnostic_only_threshold(self) -> None:
        measured: dict[str, dict[str, object]] = {}
        labels: dict[str, dict[str, object]] = {}
        clusters: dict[str, str] = {}

        def add_pair(
            cluster_index: int,
            score: float,
            disposition: str,
            *,
            visible_field: str | None = None,
            severity: int | None = None,
        ) -> None:
            for polarity in ("dark", "light"):
                code = f"c{cluster_index}-{polarity}"
                measured[code] = {
                    "anonymous_code": code,
                    "metrics": {"hard_composite_score": score},
                }
                labels[code] = {
                    "disposition": disposition,
                    "severity_0_to_3": (
                        {"clean": 0, "warning": 1, "reject": 2}[disposition]
                        if severity is None
                        else severity
                    ),
                    "grain_visible": False,
                    "tiny_speck_visible": False,
                    "microblob_visible": False,
                    "short_line_visible": False,
                    "parallel_bundle_visible": False,
                }
                if visible_field is not None:
                    labels[code][visible_field] = True
                clusters[code] = f"c{cluster_index}"

        for index in range(15):
            add_pair(index, 0.0, "clean")
        for index in range(15, 25):
            add_pair(index, 0.1, "warning", visible_field="grain_visible")
        visible_fields = (
            ["grain_visible"] * 8
            + ["tiny_speck_visible"] * 4
            + ["microblob_visible"] * 4
            + ["short_line_visible"] * 8
            + ["parallel_bundle_visible"] * 6
        )
        for offset, visible_field in enumerate(visible_fields):
            add_pair(
                25 + offset,
                0.0,
                "reject",
                visible_field=visible_field,
                severity=3 if offset < 4 else 2,
            )
        threshold, endpoints, results, status, audit = (
            calibration_harness._select_hard_threshold(measured, labels, clusters)
        )
        self.assertIsNone(threshold)
        self.assertEqual(status, "no-endpoint-admissible-threshold")
        self.assertEqual(audit["admissible_candidate_count"], 0)
        self.assertIsNone(audit["selected_threshold"])
        self.assertIsNone(audit["selected_objective"])
        self.assertIsInstance(audit["diagnostic_best_threshold"], float)
        self.assertTrue(results)
        self.assertFalse(all(item["passed"] for item in endpoints.values()))

    def test_locked_clean_report_rejects_raw_score_tamper(self) -> None:
        zero = np.zeros((192, 256), dtype=np.float32)
        zero_metrics = measure(zero, zero, self.spec["metric_definition"])
        threshold = {
            "metric": "hard_composite_score",
            "direction": "maximum",
            "threshold": 0.5,
            "calibration_clean_cluster_acceptance": 1.0,
            "calibration_warning_cluster_acceptance": 1.0,
            "calibration_reject_cluster_detection": 1.0,
            "calibration_severity3_cluster_detection": 1.0,
            "selection_objective": self.spec["threshold_selection"]["objective_order"],
        }
        report = {
            "artifact": "microtexture-v2-r6-locked-clean-reference-report",
            "schema_version": "microtexture-v2-r6-locked-clean-reference-report/2",
            "spec_sha256": common.SPEC_SHA256,
            "blind_key_commitment": "a" * 64,
            "frozen_thresholds_sha256": "b" * 64,
            "locked_clean_reference_sha256": "c" * 64,
            "source_crop_xywh": [512, 320, 512, 384],
            "metric_window_xywh_within_source_crop": [128, 96, 256, 192],
            "effective_source_xywh": [640, 416, 256, 192],
            "evaluation_marker_sha256": "d" * 64,
            "evaluated_at": "2026-01-01T00:00:00+00:00",
            "captured_git_head": "e" * 40,
            "runtime": {"fingerprint_sha256": "f" * 64},
            "implementation_bindings_sha256": "1" * 64,
            "metrics": zero_metrics,
            "hard_threshold": threshold,
            "hard_composite_accepted": True,
            "passed": True,
            "one_shot_consumed": True,
            "failure": None,
        }
        common.validate_locked_clean_reference_report_nested(
            report, self.spec, threshold
        )
        for field in ("tiny_mass_l", "spot_score", "hard_composite_score"):
            changed = copy.deepcopy(report)
            changed["metrics"][field] = 0.25
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(RuntimeError, "recomputation drift"),
            ):
                common.validate_locked_clean_reference_report_nested(
                    changed, self.spec, threshold
                )

    def test_runtime_fingerprint_binds_native_modules(self) -> None:
        fingerprint = common.runtime_fingerprint()
        for field in (
            "zlib_version",
            "zlib_runtime_version",
            "python_executable_sha256",
            "numpy_core_binary_sha256",
            "scipy_ndimage_binary_sha256",
            "pillow_imaging_binary_sha256",
            "fingerprint_sha256",
        ):
            self.assertIn(field, fingerprint)
            self.assertTrue(fingerprint[field])

    def test_post_marker_exception_writes_exact_failure_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            state = {
                "artifact_root": root,
                "blind_key_commitment": "a" * 64,
                "captured_head": "b" * 40,
                "runtime": {"fingerprint_sha256": "c" * 64},
                "implementation_bindings_sha256": "d" * 64,
            }
            calibration_harness._write_one_shot_failure_report(
                stage="calibration",
                state=state,
                marker_sha="e" * 64,
                bindings={
                    "manifest_sha256": "f" * 64,
                    "labels_sha256": "1" * 64,
                    "frozen_thresholds_sha256": None,
                    "threshold_authority_receipt_sha256": None,
                },
                phase="measure",
                error=RuntimeError("bad " + "9" * 64),
            )
            report = json.loads(
                (root / "reports/calibration-failure-report.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(set(report), common.ONE_SHOT_FAILURE_REPORT_KEYS)
            self.assertEqual(
                set(report["bindings"]), common.ONE_SHOT_FAILURE_BINDING_KEYS
            )
            self.assertTrue(report["one_shot_consumed"])
            self.assertIn("[redacted-64-hex]", report["failure"]["message"])

    def test_one_shot_guard_records_only_after_exact_marker_is_durable(
        self,
    ) -> None:
        marker = {"one_shot_consumed": True, "nonce": "marker-test"}
        marker_payload = common.canonical_json_bytes(marker)
        marker_sha = common.sha256_bytes(marker_payload)
        bindings = {
            "manifest_sha256": "1" * 64,
            "labels_sha256": "2" * 64,
            "frozen_thresholds_sha256": None,
            "threshold_authority_receipt_sha256": None,
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            state = {"artifact_root": root}
            with mock.patch.object(
                calibration_harness, "_record_post_marker_failure"
            ) as recorder:
                with self.assertRaises(KeyboardInterrupt):
                    with calibration_harness._one_shot_stage_guard(
                        stage="calibration",
                        state=state,
                        marker=marker,
                        marker_relative="markers/guard.json",
                        phase=lambda: "after-marker",
                        bindings=lambda: bindings,
                    ) as written_sha:
                        self.assertEqual(written_sha, marker_sha)
                        raise KeyboardInterrupt("stop")
                self.assertEqual(
                    (root / "markers/guard.json").read_bytes(), marker_payload
                )
                recorder.assert_called_once()
                call = recorder.call_args.kwargs
                self.assertEqual(call["marker_sha"], marker_sha)
                self.assertEqual(call["phase"], "after-marker")
                self.assertIsInstance(call["error"], KeyboardInterrupt)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            state = {"artifact_root": root}
            with (
                mock.patch.object(
                    calibration_harness,
                    "write_json_exclusive",
                    side_effect=OSError("marker-write-failed"),
                ),
                mock.patch.object(
                    calibration_harness, "_record_post_marker_failure"
                ) as recorder,
                self.assertRaisesRegex(OSError, "marker-write-failed"),
            ):
                with calibration_harness._one_shot_stage_guard(
                    stage="calibration",
                    state=state,
                    marker=marker,
                    marker_relative="markers/guard.json",
                    phase=lambda: "write-marker",
                    bindings=lambda: bindings,
                ):
                    self.fail("guard yielded after marker write failure")
            recorder.assert_not_called()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            state = {"artifact_root": root}

            def write_nondurable(write_root: Path, path: Path, _value: object) -> str:
                common.write_bytes_exclusive(write_root, path, b"wrong-marker")
                return marker_sha

            with (
                mock.patch.object(
                    calibration_harness,
                    "write_json_exclusive",
                    side_effect=write_nondurable,
                ),
                mock.patch.object(
                    calibration_harness, "_record_post_marker_failure"
                ) as recorder,
                self.assertRaises(KeyboardInterrupt),
            ):
                with calibration_harness._one_shot_stage_guard(
                    stage="calibration",
                    state=state,
                    marker=marker,
                    marker_relative="markers/guard.json",
                    phase=lambda: "after-marker",
                    bindings=lambda: bindings,
                ):
                    raise KeyboardInterrupt("stop")
            recorder.assert_not_called()

    def test_failure_report_second_fault_preserves_original_base_exception(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            state = {
                "artifact_root": root,
                "blind_key_commitment": "a" * 64,
                "captured_head": "b" * 40,
                "runtime": {"fingerprint_sha256": "c" * 64},
                "implementation_bindings_sha256": "d" * 64,
            }
            occupied = root / "reports/calibration-failure-report.json"
            write_json_exclusive(root, occupied, {"already": "occupied"})
            original = SystemExit("stop")
            calibration_harness._record_post_marker_failure(
                stage="calibration",
                state=state,
                marker_sha="e" * 64,
                bindings={
                    "manifest_sha256": "f" * 64,
                    "labels_sha256": "1" * 64,
                    "frozen_thresholds_sha256": None,
                    "threshold_authority_receipt_sha256": None,
                },
                phase="measure",
                error=original,
            )
            self.assertTrue(
                any("persistence also failed" in note for note in original.__notes__)
            )
            self.assertEqual(
                json.loads(occupied.read_text(encoding="utf-8")),
                {"already": "occupied"},
            )

            class NoteFailure(SystemExit):
                def add_note(self, note: str) -> None:
                    raise RuntimeError("note-failed")

            calibration_harness._record_post_marker_failure(
                stage="calibration",
                state=state,
                marker_sha="e" * 64,
                bindings={
                    "manifest_sha256": "f" * 64,
                    "labels_sha256": "1" * 64,
                    "frozen_thresholds_sha256": None,
                    "threshold_authority_receipt_sha256": None,
                },
                phase="measure",
                error=NoteFailure("stop"),
            )

    def test_completion_is_required_and_failure_coexistence_is_rejected(
        self,
    ) -> None:
        state_template = {
            "blind_key_commitment": "a" * 64,
            "captured_head": "b" * 40,
            "runtime": {"fingerprint_sha256": "c" * 64},
            "implementation_bindings_sha256": "d" * 64,
        }
        bindings = {
            "manifest_sha256": "e" * 64,
            "labels_sha256": "f" * 64,
            "frozen_thresholds_sha256": None,
            "threshold_authority_receipt_sha256": None,
            "locked_clean_reference_sha256": None,
        }
        marker_started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        report_evaluated_at = datetime(2026, 1, 2, tzinfo=timezone.utc)

        def reload(state: dict[str, object]) -> tuple[dict[str, object], str]:
            return common.load_stage_completion(
                stage="calibration",
                state=state,
                expected_marker_sha="1" * 64,
                expected_report_sha="2" * 64,
                expected_captured_head="b" * 40,
                expected_passed=False,
                expected_result_status="no-admissible-threshold",
                expected_bindings=bindings,
                marker_started_at=marker_started_at,
                report_evaluated_at=report_evaluated_at,
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            state = {**state_template, "artifact_root": root}
            common.write_json_exclusive(
                root, root / "reports/calibration-report.json", {"normal": True}
            )
            with self.assertRaises(RuntimeError):
                reload(state)
            common.write_stage_completion_exclusive(
                stage="calibration",
                state=state,
                marker_sha="1" * 64,
                report_sha="2" * 64,
                passed=False,
                result_status="no-admissible-threshold",
                bindings=bindings,
            )
            completion, completion_sha = reload(state)
            self.assertFalse(completion["passed"])
            self.assertEqual(len(completion_sha), 64)
            with self.assertRaisesRegex(RuntimeError, "trust-chain binding drift"):
                common.load_stage_completion(
                    stage="calibration",
                    state=state,
                    expected_marker_sha="1" * 64,
                    expected_report_sha="9" * 64,
                    expected_captured_head="b" * 40,
                    expected_passed=False,
                    expected_result_status="no-admissible-threshold",
                    expected_bindings=bindings,
                    marker_started_at=marker_started_at,
                    report_evaluated_at=report_evaluated_at,
                )
            common.write_json_exclusive(
                root,
                root / "reports/calibration-failure-report.json",
                {"failure": True},
            )
            with self.assertRaisesRegex(RuntimeError, "coexists"):
                reload(state)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            state = {**state_template, "artifact_root": root}
            common.write_json_exclusive(
                root,
                root / "reports/calibration-failure-report.json",
                {"failure": True},
            )
            with self.assertRaisesRegex(RuntimeError, "precludes"):
                common.write_stage_completion_exclusive(
                    stage="calibration",
                    state=state,
                    marker_sha="1" * 64,
                    report_sha="2" * 64,
                    passed=False,
                    result_status="no-admissible-threshold",
                    bindings=bindings,
                )

    def test_exact_artifact_io_rejects_links_and_dangling_reparse_points(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            regular = root / "nested/regular.bin"
            common.write_bytes_exclusive(root, regular, b"regular")
            self.assertEqual(regular.read_bytes(), b"regular")

            fake_reparse = root / "reports/dangling-junction.json"
            original_lstat = os.lstat

            def fake_lstat(path: os.PathLike[str] | str) -> object:
                if os.path.normcase(
                    os.path.abspath(os.fspath(path))
                ) == os.path.normcase(os.path.abspath(os.fspath(fake_reparse))):
                    return types.SimpleNamespace(
                        st_mode=0,
                        st_file_attributes=0x400,
                        st_reparse_tag=0,
                    )
                return original_lstat(path)

            with (
                mock.patch.object(common.os, "lstat", side_effect=fake_lstat),
                self.assertRaisesRegex(RuntimeError, "link/reparse"),
            ):
                common.exact_artifact_path_without_links(
                    root,
                    fake_reparse,
                    "reports/dangling-junction.json",
                    must_exist=False,
                )

            target = root / "target.bin"
            common.write_bytes_exclusive(root, target, b"unchanged")
            leaf_link = root / "leaf-link.bin"
            dangling_link = root / "dangling-link.bin"
            real_parent = root / "real-parent"
            parent_link = root / "parent-link"
            real_parent.mkdir()
            try:
                leaf_link.symlink_to(target)
                dangling_link.symlink_to(root / "missing-target.bin")
                parent_link.symlink_to(real_parent, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlink creation unavailable: {error}")
            for provided, relative in (
                (leaf_link, "leaf-link.bin"),
                (dangling_link, "dangling-link.bin"),
                (parent_link / "child.bin", "parent-link/child.bin"),
            ):
                with self.assertRaisesRegex(RuntimeError, "link/reparse"):
                    common.write_bytes_exclusive(root, provided, b"changed")
                with self.assertRaisesRegex(RuntimeError, "link/reparse"):
                    common.exact_artifact_path_without_links(
                        root, provided, relative, must_exist=False
                    )
            self.assertEqual(target.read_bytes(), b"unchanged")

    def test_holdout_entrypoints_revalidate_locked_provenance_before_work(
        self,
    ) -> None:
        sentinel = RuntimeError("preflight-stop")
        with mock.patch.object(
            generate_controls, "operation_preflight", side_effect=sentinel
        ) as preflight:
            with self.assertRaisesRegex(RuntimeError, "preflight-stop"):
                generate_controls.generate("holdout")
            preflight.assert_called_once_with(
                require_receipt=True, include_locked_clean_reference=True
            )
        with mock.patch.object(
            calibration_harness, "operation_preflight", side_effect=sentinel
        ) as preflight:
            with self.assertRaisesRegex(RuntimeError, "preflight-stop"):
                calibration_harness.holdout(Path("unused.json"))
            preflight.assert_called_once_with(
                require_receipt=True, include_locked_clean_reference=True
            )

    def test_locked_provenance_helper_checks_all_five_tracked_bindings(self) -> None:
        pairs = (
            ("repo_relative_path", "sha256"),
            ("generation_chain", "generation_chain_sha256"),
            ("generation_receipt", "generation_receipt_sha256"),
            ("root_vision_review", "root_vision_review_sha256"),
            ("independent_vision_review", "independent_vision_review_sha256"),
        )
        payloads = {path_field: path_field.encode("ascii") for path_field, _ in pairs}
        locked: dict[str, object] = {}
        for path_field, hash_field in pairs:
            locked[path_field] = f"tracked/{path_field}"
            locked[hash_field] = common.sha256_bytes(payloads[path_field])

        def tracked(_repository: Path, _head: str, relative: str) -> bytes:
            path_field = next(field for field, _ in pairs if relative == locked[field])
            return payloads[path_field]

        with mock.patch.object(
            common, "_tracked_worktree_bytes", side_effect=tracked
        ) as reader:
            result = common.verify_tracked_locked_clean_reference_provenance(
                Path("repository"), "a" * 40, locked
            )
            self.assertEqual(result, payloads["repo_relative_path"])
            self.assertEqual(reader.call_count, 5)
        for _, hash_field in pairs:
            changed = copy.deepcopy(locked)
            changed[hash_field] = "0" * 64
            with (
                mock.patch.object(
                    common, "_tracked_worktree_bytes", side_effect=tracked
                ),
                self.assertRaises(RuntimeError),
            ):
                common.verify_tracked_locked_clean_reference_provenance(
                    Path("repository"), "a" * 40, changed
                )
        with (
            mock.patch.object(
                common,
                "_tracked_worktree_bytes",
                side_effect=RuntimeError("missing tracked file"),
            ),
            self.assertRaisesRegex(RuntimeError, "missing tracked file"),
        ):
            common.verify_tracked_locked_clean_reference_provenance(
                Path("repository"), "a" * 40, locked
            )

    def test_foundation_provenance_helper_checks_all_eight_tracked_bindings(
        self,
    ) -> None:
        corpus: dict[str, object] = {
            "foundations": [
                {
                    "id": foundation_id,
                    "path": f"tracked/{foundation_id}",
                    "sha256": common.sha256_bytes(foundation_id.encode("ascii")),
                }
                for foundation_id in ("v15", "v16", "v17")
            ],
            "generation_chain": "tracked/generation-chain",
            "generation_chain_sha256": common.sha256_bytes(b"generation-chain"),
            "generation_receipt": "tracked/generation-receipt",
            "generation_receipt_sha256": common.sha256_bytes(b"generation-receipt"),
            "root_vision_review": "tracked/root-review",
            "root_vision_review_sha256": common.sha256_bytes(b"root-review"),
            "independent_vision_reviews": [
                {
                    "path": f"tracked/independent-{suffix}",
                    "sha256": common.sha256_bytes(
                        f"independent-{suffix}".encode("ascii")
                    ),
                }
                for suffix in ("a", "b")
            ],
        }
        paths_to_payloads = {
            item["path"]: item["id"].encode("ascii") for item in corpus["foundations"]
        }
        paths_to_payloads.update(
            {
                corpus["generation_chain"]: b"generation-chain",
                corpus["generation_receipt"]: b"generation-receipt",
                corpus["root_vision_review"]: b"root-review",
                **{
                    item["path"]: Path(item["path"]).name.encode("ascii")
                    for item in corpus["independent_vision_reviews"]
                },
            }
        )

        def tracked(_repository: Path, _head: str, relative: str) -> bytes:
            return paths_to_payloads[relative]

        binding_locations = (
            [
                ("foundation", index, item["path"])
                for index, item in enumerate(corpus["foundations"])
            ]
            + [
                ("field", hash_field, corpus[path_field])
                for path_field, hash_field in (
                    ("generation_chain", "generation_chain_sha256"),
                    ("generation_receipt", "generation_receipt_sha256"),
                    ("root_vision_review", "root_vision_review_sha256"),
                )
            ]
            + [
                ("review", index, item["path"])
                for index, item in enumerate(corpus["independent_vision_reviews"])
            ]
        )
        with mock.patch.object(
            common, "_tracked_worktree_bytes", side_effect=tracked
        ) as reader:
            result = common.verify_tracked_foundation_corpus_provenance(
                Path("repository"), "a" * 40, corpus
            )
            self.assertEqual(
                result, {key: key.encode("ascii") for key in ("v15", "v16", "v17")}
            )
            self.assertEqual(reader.call_count, 8)

        for kind, location, _ in binding_locations:
            changed = copy.deepcopy(corpus)
            if kind == "foundation":
                changed["foundations"][location]["sha256"] = "0" * 64
            elif kind == "field":
                changed[location] = "0" * 64
            else:
                changed["independent_vision_reviews"][location]["sha256"] = "0" * 64
            with (
                mock.patch.object(
                    common, "_tracked_worktree_bytes", side_effect=tracked
                ),
                self.assertRaises(RuntimeError),
            ):
                common.verify_tracked_foundation_corpus_provenance(
                    Path("repository"), "a" * 40, changed
                )

        for _, _, missing_path in binding_locations:

            def tracked_with_missing(
                _repository: Path,
                _head: str,
                relative: str,
                *,
                target: str = missing_path,
            ) -> bytes:
                if relative == target:
                    raise RuntimeError("missing tracked file")
                return paths_to_payloads[relative]

            with (
                mock.patch.object(
                    common,
                    "_tracked_worktree_bytes",
                    side_effect=tracked_with_missing,
                ),
                self.assertRaisesRegex(RuntimeError, "missing tracked file"),
            ):
                common.verify_tracked_foundation_corpus_provenance(
                    Path("repository"), "a" * 40, corpus
                )

    def test_population_shortage_prevents_measurement_in_both_harnesses(
        self,
    ) -> None:
        manifest_sha = "1" * 64
        labels_sha = "2" * 64
        frozen_sha = "3" * 64
        receipt_sha = "4" * 64
        state = {
            "artifact_root": Path("unused-artifact-root"),
            "blind_key_commitment": "5" * 64,
            "captured_head": "6" * 40,
            "runtime": {"fingerprint_sha256": "7" * 64},
            "implementation_bindings_sha256": "8" * 64,
            "threshold_authority": {"frozen_thresholds_sha256": frozen_sha},
            "threshold_authority_sha256": receipt_sha,
        }
        manifest = {"records": []}
        labels = {"a" * 24: _vision_item("a" * 24, "clean")}
        identities = [types.SimpleNamespace()]
        clusters = {"cluster": ("a" * 24, "b" * 24)}

        for stage, entrypoint in (
            ("calibration", calibration_harness.calibrate),
            ("holdout", calibration_harness.holdout),
        ):
            guard = mock.MagicMock()
            guard.__enter__.return_value = "9" * 64
            guard.__exit__.return_value = False
            shortage = RuntimeError(f"{stage} endpoint population shortage")
            with (
                self.subTest(stage=stage),
                mock.patch.object(
                    calibration_harness, "operation_preflight", return_value=state
                ),
                mock.patch.object(calibration_harness, "blind_key", return_value=b"k"),
                mock.patch.object(
                    calibration_harness,
                    "blind_commitment",
                    return_value=state["blind_key_commitment"],
                ),
                mock.patch.object(
                    calibration_harness,
                    "load_frozen_thresholds",
                    return_value=({"hard_threshold": {"threshold": 0.5}}, frozen_sha),
                ),
                mock.patch.object(
                    calibration_harness,
                    "_load_manifest",
                    return_value=(manifest, manifest_sha),
                ),
                mock.patch.object(
                    calibration_harness,
                    "_load_labels",
                    return_value=(labels, labels_sha, b"labels"),
                ),
                mock.patch.object(
                    calibration_harness,
                    "_prepare_sealed_label_path",
                    return_value=Path("sealed-labels.json"),
                ),
                mock.patch.object(
                    calibration_harness,
                    "_one_shot_stage_guard",
                    return_value=guard,
                ),
                mock.patch.object(
                    calibration_harness,
                    "_seal_labels_after_marker",
                    return_value=labels,
                ),
                mock.patch.object(
                    calibration_harness,
                    "_bind_after_marker",
                    return_value=identities,
                ),
                mock.patch.object(
                    calibration_harness,
                    "_validate_private_label_audits_after_marker",
                ) as private_audit,
                mock.patch.object(
                    calibration_harness,
                    "_eligible_condition_clusters",
                    return_value=clusters,
                ),
                mock.patch.object(
                    calibration_harness,
                    "validate_endpoint_population_counts",
                    side_effect=shortage,
                ) as population_gate,
                mock.patch.object(
                    calibration_harness, "_measure_records"
                ) as measure_records,
                self.assertRaisesRegex(RuntimeError, "endpoint population shortage"),
            ):
                entrypoint(Path("labels.json"))
            private_audit.assert_called_once()
            population_gate.assert_called_once_with(labels, clusters, self.spec)
            measure_records.assert_not_called()

    def test_reviewed_labels_require_exact_path_and_are_sealed_before_use(
        self,
    ) -> None:
        code = "a" * 24
        manifest_sha = "b" * 64
        runtime = {"fingerprint_sha256": "c" * 64}
        state_template = {
            "blind_key_commitment": "d" * 64,
            "runtime": runtime,
            "implementation_bindings_sha256": "e" * 64,
        }
        manifest = {
            "runtime": runtime,
            "contact_sheet_bundle": [],
            "records": [
                {
                    "anonymous_code": code,
                    "control_commitment": "1" * 64,
                    "reference_commitment": "2" * 64,
                    "delta_commitment": "3" * 64,
                }
            ],
        }
        labels_value = {
            "artifact": "microtexture-v2-r6-root-vision-labels",
            "schema_version": "microtexture-v2-r6-root-vision-labels/2",
            "split": "calibration",
            "spec_sha256": common.SPEC_SHA256,
            "manifest_sha256": manifest_sha,
            "implementation_bindings_sha256": "e" * 64,
            "blind_key_commitment": "d" * 64,
            "runtime": runtime,
            "contact_sheet_bundle": [],
            "reviewer": "Root",
            "items": [
                {
                    "anonymous_code": code,
                    "disposition": "clean",
                    "grain_visible": False,
                    "tiny_speck_visible": False,
                    "microblob_visible": False,
                    "short_line_visible": False,
                    "parallel_bundle_visible": False,
                    "severity_0_to_3": 0,
                    "reviewed_at_200_percent": True,
                    "reviewed_at_all_400_percent_quadrants": True,
                    "notes": "ev3:g=-;t=-;b=-;l=-;p=-",
                }
            ],
        }
        payload = common.canonical_json_bytes(labels_value)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            state = {**state_template, "artifact_root": root}
            input_relative = self.spec["labels"]["exact_artifact_paths"]["calibration"]
            input_path = root / input_relative
            common.write_bytes_exclusive(root, input_path, payload)
            alias_path = root / "alias-labels.json"
            common.write_bytes_exclusive(root, alias_path, payload)
            with self.assertRaises(RuntimeError):
                calibration_harness._load_labels(
                    alias_path, "calibration", manifest, manifest_sha, state
                )
            labels, labels_sha, loaded_payload = calibration_harness._load_labels(
                input_path, "calibration", manifest, manifest_sha, state
            )
            sealed_path = calibration_harness._prepare_sealed_label_path(
                "calibration", state
            )
            sealed_labels = calibration_harness._seal_labels_after_marker(
                split="calibration",
                original_payload=loaded_payload,
                expected_sha=labels_sha,
                sealed_path=sealed_path,
                manifest=manifest,
                manifest_sha=manifest_sha,
                state=state,
            )
            self.assertEqual(labels, sealed_labels)
            self.assertEqual(sealed_path.read_bytes(), payload)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            state = {**state_template, "artifact_root": root}
            input_relative = self.spec["labels"]["exact_artifact_paths"]["calibration"]
            input_path = root / input_relative
            common.write_bytes_exclusive(root, input_path, payload)
            _, labels_sha, loaded_payload = calibration_harness._load_labels(
                input_path, "calibration", manifest, manifest_sha, state
            )
            input_path.write_bytes(payload + b" ")
            sealed_path = calibration_harness._prepare_sealed_label_path(
                "calibration", state
            )
            with self.assertRaisesRegex(RuntimeError, "changed before sealing"):
                calibration_harness._seal_labels_after_marker(
                    split="calibration",
                    original_payload=loaded_payload,
                    expected_sha=labels_sha,
                    sealed_path=sealed_path,
                    manifest=manifest,
                    manifest_sha=manifest_sha,
                    state=state,
                )


if __name__ == "__main__":
    unittest.main()
