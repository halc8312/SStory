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
        self.assertEqual(
            self.spec["population_anchor_schedule"]["tier_counts_per_artifact_family"],
            dict(expected_tiers),
        )
        self.assertEqual(
            self.spec["population_anchor_schedule"]["revision"],
            "dev-r8-soft-unit-schedule-v1",
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
                        item["schedule_revision"] == "dev-r8-soft-unit-schedule-v1"
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
                    self.assertGreaterEqual(parameters["count_in_metric_window"], 6)
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
        self.assertEqual(min(split_nonces["calibration"]), 73000)
        self.assertEqual(max(split_nonces["calibration"]), 73419)
        self.assertEqual(min(split_nonces["holdout"]), 83000)
        self.assertEqual(max(split_nonces["holdout"]), 83419)
        self.assertEqual(
            self.spec["splits"]["calibration"]["public_nonce"],
            "r6-calibration-v3",
        )
        self.assertEqual(
            self.spec["splits"]["holdout"]["public_nonce"], "r6-holdout-v3"
        )

    def test_dev_r8_runner_is_tracked_authority_with_isolated_root(self) -> None:
        self.assertEqual(development_probe.DEVELOPMENT_EDITION, "r8")
        self.assertEqual(
            development_probe.DEV_ROOT,
            common.repository_root()
            / "tmp"
            / "map-production"
            / "microtexture-v2-r6-dev-r8",
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

    def test_dev_r8_runner_rejects_unignored_private_key_path(self) -> None:
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

    def test_dev_r8_runner_rejects_nontracked_ignore_source(self) -> None:
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

    def test_dev_r7_failure_audit_preserves_initial_and_reconciled_evidence(
        self,
    ) -> None:
        repository = common.repository_root()
        relative = self.spec["history"]["dev_r7_failure_audit"]
        payload = (repository / relative).read_bytes()
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            self.spec["history"]["dev_r7_failure_audit_sha256"],
        )
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
