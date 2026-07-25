"""Fast deterministic self-tests for the frozen r5 authority implementation."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import numpy as np

import calibration_harness
import common
import generate_controls
from calibration_harness import _cluster_macro_rate, _threshold_candidates
from common import SPEC_PATH, write_json_exclusive
from control_catalog import (
    _artifact_variants,
    _positions,
    _render_unsigned_delta,
    contact_sheet_pages,
    expected_controls,
)
from metrics_v2_r5 import (
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
        "notes": "self-test",
    }
    if visible_field is not None:
        item[visible_field] = True
    return item


def _vision_payload(
    split: str,
    items: list[dict[str, object]],
    manifest: dict[str, object],
    manifest_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    return {
        "artifact": "microtexture-v2-r5-root-vision-labels",
        "schema_version": "microtexture-v2-r5-root-vision-labels/2",
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
    for index in range(140):
        code = f"{index:024x}"
        if index < 120:
            role, group = "artifact", None
            label = _vision_item(code, "clean")
        elif index < 136:
            role, group = "protocol-zero", None
            label = _vision_item(code, "clean")
        elif index < 138:
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


class MicrotextureR5SelfTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        development_sha = hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()
        common.SPEC_SHA256 = development_sha
        calibration_harness.SPEC_SHA256 = development_sha

    def test_preregistered_counts_and_metric_window(self) -> None:
        self.assertEqual(
            self.spec["schema_version"], "microtexture-v2-r5-preregistered-spec/2"
        )
        self.assertEqual(
            self.spec["canvas"]["metric_window"]["xywh"], [128, 96, 256, 192]
        )
        self.assertEqual(self.spec["canvas"]["metric_window"]["pixels"], 49152)
        self.assertEqual(
            self.spec["contact_sheets"]["expected_controls_per_split"], 140
        )
        self.assertEqual(self.spec["contact_sheets"]["expected_pages_per_split"], 120)
        self.assertEqual(
            self.spec["threshold_selection"]["hard_gate"]["metric"],
            "hard_composite_score",
        )

    def test_sparse_rendering_is_contained_in_metric_window(self) -> None:
        roi = (128, 96, 256, 192)
        outside = np.ones((384, 512), dtype=bool)
        outside[96:288, 128:384] = False
        probes = {
            "artifact-speck": {
                "diameter_px": 3,
                "amplitude_l": 8.0,
                "count_in_metric_window": 9,
            },
            "artifact-microblob": {
                "diameter_px": 12,
                "amplitude_l": 9.0,
                "count_in_metric_window": 9,
            },
            "artifact-short-dash": {
                "length_px": 24,
                "width_px": 4,
                "amplitude_l": 9.0,
                "count_in_metric_window": 9,
            },
            "artifact-parallel-bundle": {
                "length_px": 24,
                "width_px": 4,
                "spacing_px": 24,
                "amplitude_l": 9.0,
                "pair_count_in_metric_window": 9,
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

    def test_sparse_positions_have_true_zero_and_no_forced_center(self) -> None:
        roi = (128, 96, 256, 192)
        self.assertEqual(_positions(np.random.default_rng(1), 0, roi, 20), [])
        positions = _positions(np.random.default_rng(2), 9, roi, 20)
        self.assertEqual(len(positions), 9)
        self.assertNotIn((256.0, 192.0), positions)
        self.assertTrue(all(148 <= x <= 364 and 116 <= y <= 268 for x, y in positions))

    def test_fine_grain_low_conditions_retain_sparse_nonzero_support(self) -> None:
        roi = (128, 96, 256, 192)
        outside = np.ones((384, 512), dtype=bool)
        outside[96:288, 128:384] = False
        expected_sparse_pixels = 50
        for split in ("calibration", "holdout"):
            variants = _artifact_variants(split)["artifact-fine-grain"]
            self.assertEqual(len(variants), 12)
            for index, parameters in enumerate(variants):
                expected_fraction = 0.001 if index in {0, 6} else 1.0
                self.assertEqual(
                    parameters["support_fraction_in_metric_window"],
                    expected_fraction,
                )
            for index in (0, 6):
                delta = _render_unsigned_delta(
                    "artifact-fine-grain",
                    variants[index],
                    np.random.default_rng(500 + index),
                    384,
                    512,
                    roi,
                )
                encoded = np.rint(delta).astype(np.int16)
                self.assertEqual(np.count_nonzero(encoded), expected_sparse_pixels)
                self.assertTrue(np.all(encoded[outside] == 0))

    def test_private_cluster_pairs_polarities_and_contact_sheet_geometry(self) -> None:
        controls = expected_controls(
            self.spec, "calibration", hashlib.sha256(b"r5-test-key").digest()
        )
        self.assertEqual(len(controls), 140)
        role_counts = {
            role: sum(item.private_role == role for item in controls)
            for role in {item.private_role for item in controls}
        }
        self.assertEqual(
            role_counts,
            {"artifact": 120, "protocol-zero": 16, "duplicate-audit": 4},
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
        self.assertEqual(len(commitments), 420)
        self.assertEqual(len(set(commitments)), 420)
        self.assertEqual(len({item.control_sha256 for item in controls}), 140)
        self.assertEqual(len({item.reference_sha256 for item in controls}), 140)
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
            self.assertEqual(len(panel_hashes), 140, view["id"])
        artifact_controls = [
            item for item in controls if item.private_role == "artifact"
        ]
        self.assertEqual(
            len({item.condition_cluster_id for item in artifact_controls}), 60
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
        for changed in invalid_settings:
            with self.assertRaises(RuntimeError):
                common.validate_contact_sheet_view_partition(changed, metric)

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
            "artifact": "microtexture-v2-r5-control-manifest",
            "schema_version": "microtexture-v2-r5-control-manifest/3",
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
            self.spec, "calibration", hashlib.sha256(b"r5-reveal-test-key").digest()
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
            "artifact-clean": 0.1,
            "artifact-reject": 0.8,
            "protocol-zero": 0.333333,
            "duplicate-audit": 0.777777,
        }
        measured = {
            code: {"anonymous_code": code, "metrics": {"hard_composite_score": value}}
            for code, value in scores.items()
        }
        labels = {
            "artifact-clean": _vision_item("artifact-clean", "clean"),
            "artifact-reject": _vision_item(
                "artifact-reject", "reject", visible_field="grain_visible"
            ),
            "protocol-zero": _vision_item("protocol-zero", "clean"),
            "duplicate-audit": _vision_item(
                "duplicate-audit", "reject", visible_field="short_line_visible"
            ),
        }
        clusters = {
            "artifact-clean": "cluster-clean",
            "artifact-reject": "cluster-reject",
        }
        endpoints, _ = common.evaluate_endpoints_from_measurements(
            0.5, measured, labels, clusters, "calibration", self.spec
        )
        self.assertEqual(endpoints["clean_acceptance"]["record_count"], 1)
        self.assertEqual(endpoints["reject_detection"]["record_count"], 1)
        _, _, _, _, audit = common.select_hard_threshold_from_measurements(
            measured, labels, clusters, self.spec
        )
        expected = common.threshold_candidates([0.1, 0.8])
        self.assertEqual(
            [candidate["threshold"] for candidate in audit["candidates"]], expected
        )
        report = {
            "measurements": list(measured.values()),
            "identity_reveal": [
                {"anonymous_code": code, "private_role": role}
                for code, role in (
                    ("artifact-clean", "artifact"),
                    ("artifact-reject", "artifact"),
                    ("protocol-zero", "protocol-zero"),
                    ("duplicate-audit", "duplicate-audit"),
                )
            ],
        }
        self.assertEqual(
            common._calibration_candidate_thresholds(report, self.spec), expected
        )

    def test_paired_records_have_record_level_endpoint_eligibility(self) -> None:
        measured = {
            "dark": {"metrics": {"hard_composite_score": 0.9}},
            "light": {"metrics": {"hard_composite_score": 0.1}},
        }
        labels = {
            "dark": {
                "disposition": "reject",
                "severity_0_to_3": 2,
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
        endpoints, _ = calibration_harness._evaluate_endpoints(
            0.5,
            measured,
            labels,
            {"dark": "shared-cluster", "light": "shared-cluster"},
            "calibration",
        )
        self.assertEqual(
            endpoints["tiny_speck_reject_detection"]["cluster_macro_rate"], 1.0
        )
        self.assertEqual(endpoints["warning_acceptance"]["cluster_macro_rate"], 1.0)
        self.assertEqual(
            endpoints["tiny_speck_reject_detection"]["unique_cluster_count"], 1
        )
        self.assertEqual(endpoints["warning_acceptance"]["unique_cluster_count"], 1)

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
            measured[code] = {
                "anonymous_code": code,
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
            labels[code] = label
            clusters[code] = f"cluster-{code}"

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
            "artifact": "microtexture-v2-r5-locked-clean-reference-report",
            "schema_version": "microtexture-v2-r5-locked-clean-reference-report/2",
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
            "artifact": "microtexture-v2-r5-root-vision-labels",
            "schema_version": "microtexture-v2-r5-root-vision-labels/2",
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
                    "notes": "",
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
