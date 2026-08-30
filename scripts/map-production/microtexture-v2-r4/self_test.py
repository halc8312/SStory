"""Fast deterministic self-tests for the frozen r4 authority implementation."""

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
    _positions,
    _render_delta,
    contact_sheet_pages,
    expected_controls,
)
from metrics_v2_r4 import measure


class MicrotextureR4SelfTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        development_sha = hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()
        common.SPEC_SHA256 = development_sha
        calibration_harness.SPEC_SHA256 = development_sha

    def test_preregistered_counts_and_metric_window(self) -> None:
        self.assertEqual(
            self.spec["schema_version"], "microtexture-v2-r4-preregistered-spec/2"
        )
        self.assertEqual(
            self.spec["canvas"]["metric_window"]["xywh"], [128, 96, 256, 192]
        )
        self.assertEqual(self.spec["canvas"]["metric_window"]["pixels"], 49152)
        for split in ("calibration", "holdout"):
            count = sum(
                len(family[f"{split}_variants"])
                * len(family["polarities"])
                * int(self.spec["splits"][split]["replicates_per_variant"])
                for family in self.spec["control_families"]
            )
            self.assertEqual(count, 140)

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
            delta = _render_delta(
                family,
                parameters,
                1,
                np.random.default_rng(100 + index),
                384,
                512,
                roi,
            )
            self.assertTrue(np.any(delta[~outside] != 0), family)
            self.assertTrue(np.all(delta[outside] == 0), family)
        zero = _render_delta(
            "artifact-speck",
            {"diameter_px": 3, "amplitude_l": 9.0, "count_in_metric_window": 0},
            1,
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

    def test_private_cluster_pairs_polarities_and_contact_sheet_geometry(self) -> None:
        reduced = copy.deepcopy(self.spec)
        clean = copy.deepcopy(reduced["control_families"][0])
        artifact = next(
            copy.deepcopy(family)
            for family in reduced["control_families"]
            if family["id"] == "artifact-short-dash"
        )
        clean["calibration_variants"] = clean["calibration_variants"][:1]
        artifact["calibration_variants"] = artifact["calibration_variants"][:10]
        reduced["control_families"] = [clean, artifact]
        reduced["independent_condition_clusters"][
            "expected_unique_clusters_per_split"
        ] = 11
        reduced["independent_condition_clusters"][
            "expected_clean_clusters_per_split"
        ] = 1
        reduced["independent_condition_clusters"][
            "expected_artifact_clusters_per_split"
        ] = 10
        reduced["contact_sheets"]["expected_controls_per_split"] = 21
        reduced["contact_sheets"]["expected_pages_per_view"] = 4
        reduced["contact_sheets"]["expected_pages_per_split"] = 20
        controls = expected_controls(reduced, "calibration", bytes(range(32)))
        self.assertEqual(len(controls), 21)
        artifact_controls = [
            item for item in controls if item.family == "artifact-short-dash"
        ]
        self.assertEqual(
            len({item.condition_cluster_id for item in artifact_controls}), 10
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
            self.assertEqual(dark.reference_png, light.reference_png)
            self.assertTrue(
                np.array_equal(dark.requested_delta, -light.requested_delta)
            )
        pages = contact_sheet_pages(reduced, "calibration", controls)
        self.assertEqual(
            sorted({page.view_id for page in pages}),
            [
                "full-200",
                "northeast-400",
                "northwest-400",
                "southeast-400",
                "southwest-400",
            ],
        )
        self.assertEqual(len(pages), 20)
        self.assertTrue(all(1 <= len(page.item_codes) <= 6 for page in pages))

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
        clean = copy.deepcopy(reduced["control_families"][0])
        artifact = next(
            copy.deepcopy(family)
            for family in reduced["control_families"]
            if family["id"] == "artifact-short-dash"
        )
        clean["calibration_variants"] = clean["calibration_variants"][:1]
        artifact["calibration_variants"] = artifact["calibration_variants"][:10]
        reduced["control_families"] = [clean, artifact]
        reduced["independent_condition_clusters"].update(
            {
                "expected_unique_clusters_per_split": 11,
                "expected_clean_clusters_per_split": 1,
                "expected_artifact_clusters_per_split": 10,
            }
        )
        reduced["contact_sheets"].update(
            {
                "expected_controls_per_split": 21,
                "expected_pages_per_view": 4,
                "expected_pages_per_split": 20,
            }
        )
        key = bytes(range(32))
        controls = expected_controls(reduced, "calibration", key)
        pages = contact_sheet_pages(reduced, "calibration", controls)
        records = [
            {
                "anonymous_code": control.anonymous_code,
                "control_png": (
                    f"controls/calibration/items/{control.anonymous_code}/control.png"
                ),
                "reference_png": (
                    f"controls/calibration/items/{control.anonymous_code}/reference.png"
                ),
                "control_sha256": control.control_sha256,
                "reference_sha256": control.reference_sha256,
                "delta_float32_sha256": control.delta_float32_sha256,
            }
            for control in sorted(controls, key=lambda item: item.anonymous_code)
        ]
        runtime = {"fingerprint_sha256": "a" * 64}
        captured_head = "b" * 40
        commitment = ""
        manifest = {
            "artifact": "microtexture-v2-r4-control-manifest",
            "schema_version": "microtexture-v2-r4-control-manifest/2",
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
                by_code = {control.anonymous_code: control for control in controls}
                for record in records:
                    control = by_code[record["anonymous_code"]]
                    common.write_bytes_exclusive(
                        root, root / record["control_png"], control.control_png
                    )
                    common.write_bytes_exclusive(
                        root, root / record["reference_png"], control.reference_png
                    )
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

    def test_metric_requires_exact_shape_and_hard_metric_is_vision_aligned(
        self,
    ) -> None:
        definition = self.spec["metric_definition"]
        zero = np.zeros((192, 256), dtype=np.float32)
        result = measure(zero, zero, definition)
        common.validate_metric_values(result, self.spec, "test metrics")
        self.assertEqual(result["eligible_pixels"], 49152)
        self.assertEqual(result["microartifact_occupancy_per_mp"], 0.0)
        impulse = zero.copy()
        impulse[96, 128] = 12.0
        detected = measure(impulse, zero, definition)
        self.assertGreater(detected["microartifact_occupancy_per_mp"], 0.0)
        self.assertGreater(detected["sparse_blob_score"], 0.0)
        with self.assertRaises(ValueError):
            measure(np.zeros((384, 512)), np.zeros((384, 512)), definition)
        for field, invalid in (
            ("eligible_pixels", True),
            ("microartifact_occupancy_per_mp", -1.0),
            ("parallel_pair_ratio", 1.01),
        ):
            changed = copy.deepcopy(result)
            changed[field] = invalid
            with self.assertRaises(RuntimeError):
                common.validate_metric_values(changed, self.spec, "bad metrics")

    def test_cluster_macro_is_invariant_to_duplicate_records(self) -> None:
        clusters = {"a": "x", "b": "x", "c": "y"}
        rejected = {"a": True, "b": True, "c": False}
        first = _cluster_macro_rate(["a", "c"], rejected, clusters, "reject")
        duplicate = _cluster_macro_rate(["a", "b", "c"], rejected, clusters, "reject")
        self.assertEqual(first[0], duplicate[0])
        self.assertEqual(first[2], duplicate[2])
        self.assertNotEqual(first[1], duplicate[1])

    def test_paired_records_have_record_level_endpoint_eligibility(self) -> None:
        measured = {
            "dark": {"metrics": {"microartifact_occupancy_per_mp": 3.0}},
            "light": {"metrics": {"microartifact_occupancy_per_mp": 0.0}},
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
            1.0,
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
            _threshold_candidates([1.0, 3.0]), [0.999999997, 2.0, 3.000000003]
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
            "metric": "microartifact_occupancy_per_mp",
            "direction": "maximum",
            "threshold": 10.0,
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
                "metrics": {"microartifact_occupancy_per_mp": value},
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
                4.0 if index < 2 else 1.0,
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
                3.0,
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
        self.assertEqual(threshold["threshold"], 2.0)
        self.assertEqual(endpoints["warning_acceptance"]["cluster_macro_rate"], 0.8)
        self.assertEqual(endpoints["reject_detection"]["cluster_macro_rate"], 1.0)
        self.assertGreater(audit["admissible_candidate_count"], 0)
        self.assertEqual(audit["selected_threshold"], 2.0)
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

    def test_full_calibration_report_is_recomputed_and_tampering_is_rejected(
        self,
    ) -> None:
        zero = np.zeros((192, 256), dtype=np.float32)
        zero_metrics = measure(zero, zero, self.spec["metric_definition"])
        measurements: list[dict[str, object]] = []
        reveal: list[dict[str, object]] = []
        records: list[dict[str, object]] = []
        labels: dict[str, dict[str, object]] = {}
        clusters: dict[str, str] = {}
        next_record = 0
        next_cluster = 0

        def add_record(
            family: str,
            variant: int,
            polarity: int,
            cluster_index: int,
            disposition: str,
        ) -> None:
            nonlocal next_record
            code = f"{next_record:024x}"
            control_id = f"{1000 + next_record:024x}"
            cluster_id = f"{5000 + cluster_index:024x}"
            control_sha = f"{10000 + next_record:064x}"
            reference_sha = f"{20000 + cluster_index:064x}"
            delta_sha = f"{30000 + next_record:064x}"
            metrics = copy.deepcopy(zero_metrics)
            metrics["microartifact_occupancy_per_mp"] = (
                100.0 if disposition == "reject" else 0.0
            )
            measurements.append({"anonymous_code": code, "metrics": metrics})
            reveal.append(
                {
                    "anonymous_code": code,
                    "family": family,
                    "control_id": control_id,
                    "condition_cluster_id": cluster_id,
                    "variant_index": variant,
                    "replicate": 0,
                    "polarity": polarity,
                    "parameters": copy.deepcopy(
                        family_by_id[family]["calibration_variants"][variant]
                    ),
                    "control_sha256": control_sha,
                    "reference_sha256": reference_sha,
                    "delta_float32_sha256": delta_sha,
                }
            )
            records.append(
                {
                    "anonymous_code": code,
                    "control_sha256": control_sha,
                    "reference_sha256": reference_sha,
                    "delta_float32_sha256": delta_sha,
                }
            )
            visible = disposition != "clean"
            labels[code] = {
                "disposition": disposition,
                "severity_0_to_3": (
                    0
                    if disposition == "clean"
                    else 1
                    if disposition == "warning"
                    else 3
                ),
                "grain_visible": visible,
                "tiny_speck_visible": disposition == "reject",
                "microblob_visible": disposition == "reject",
                "short_line_visible": disposition == "reject",
                "parallel_bundle_visible": disposition == "reject",
            }
            clusters[code] = cluster_id
            next_record += 1

        family_by_id = {
            family["id"]: family for family in self.spec["control_families"]
        }
        clean_families = [
            family["id"]
            for family in self.spec["control_families"]
            if family["role"] == "clean_reference"
        ]
        artifact_families = [
            family["id"]
            for family in self.spec["control_families"]
            if family["role"] == "artifact_probe"
        ]
        for family in clean_families:
            for variant in range(4):
                add_record(family, variant, 1, next_cluster, "clean")
                next_cluster += 1
        artifact_cluster_index = 0
        for family in artifact_families:
            for variant in range(10):
                for polarity in (-1, 1):
                    disposition = (
                        "warning"
                        if artifact_cluster_index < 10 and polarity == -1
                        else "reject"
                    )
                    add_record(family, variant, polarity, next_cluster, disposition)
                next_cluster += 1
                artifact_cluster_index += 1
        self.assertEqual((next_record, next_cluster), (140, 80))
        measured = {item["anonymous_code"]: item for item in measurements}
        threshold, endpoints, results, status, audit = (
            common.select_hard_threshold_from_measurements(
                measured, labels, clusters, self.spec
            )
        )
        self.assertEqual(status, "selected-and-passed")
        report = {
            "artifact": "microtexture-v2-r4-calibration-report",
            "schema_version": "microtexture-v2-r4-calibration-report/2",
            "spec_sha256": common.SPEC_SHA256,
            "blind_key_commitment": "a" * 64,
            "manifest_sha256": "b" * 64,
            "labels_sha256": "c" * 64,
            "evaluation_marker_sha256": "d" * 64,
            "evaluated_at": "2026-01-01T00:00:00+00:00",
            "captured_git_head": "e" * 40,
            "runtime": {"fingerprint_sha256": "f" * 64},
            "implementation_bindings_sha256": "1" * 64,
            "hard_gate": self.spec["threshold_selection"]["hard_gate"],
            "hard_threshold": threshold,
            "selection_status": status,
            "endpoint_performance": endpoints,
            "results_by_code": results,
            "diagnostic_flags_by_code": {
                item["anonymous_code"]: [] for item in measurements
            },
            "passed": True,
            "measurements": measurements,
            "identity_reveal": reveal,
            "threshold_selection_audit": audit,
            "one_shot_consumed": True,
            "failure": None,
        }
        manifest = {"records": records}
        common.validate_calibration_report_nested(report, self.spec)
        common.validate_report_evaluation_bindings(
            report, manifest, labels, "calibration", self.spec
        )
        mutations = []
        endpoint_tamper = copy.deepcopy(report)
        endpoint_tamper["endpoint_performance"]["clean_acceptance"][
            "cluster_macro_rate"
        ] = 0.5
        mutations.append(endpoint_tamper)
        result_tamper = copy.deepcopy(report)
        first_code = measurements[0]["anonymous_code"]
        result_tamper["results_by_code"][first_code]["failed_hard_gate"] = True
        mutations.append(result_tamper)
        audit_tamper = copy.deepcopy(report)
        audit_tamper["threshold_selection_audit"]["selected_threshold"] = 999.0
        mutations.append(audit_tamper)
        for changed in mutations:
            with self.assertRaises(RuntimeError):
                common.validate_calibration_report_nested(changed, self.spec)
        manifest_tamper = copy.deepcopy(manifest)
        manifest_tamper["records"][0]["control_sha256"] = "9" * 64
        with self.assertRaises(RuntimeError):
            common.validate_report_evaluation_bindings(
                report, manifest_tamper, labels, "calibration", self.spec
            )

        assert threshold is not None
        holdout_reveal = copy.deepcopy(reveal)
        for item in holdout_reveal:
            item["parameters"] = copy.deepcopy(
                family_by_id[item["family"]]["holdout_variants"][item["variant_index"]]
            )
        holdout_endpoints, holdout_results = (
            common.evaluate_endpoints_from_measurements(
                float(threshold["threshold"]),
                measured,
                labels,
                clusters,
                "holdout",
                self.spec,
            )
        )
        holdout_report = {
            "artifact": "microtexture-v2-r4-holdout-report",
            "schema_version": "microtexture-v2-r4-holdout-report/2",
            "authority": True,
            "spec_sha256": common.SPEC_SHA256,
            "blind_key_commitment": "a" * 64,
            "manifest_sha256": "b" * 64,
            "labels_sha256": "c" * 64,
            "evaluation_marker_sha256": "d" * 64,
            "frozen_thresholds_sha256": "2" * 64,
            "threshold_authority_receipt_sha256": "3" * 64,
            "evaluated_at": "2026-01-01T00:00:00+00:00",
            "captured_git_head": "e" * 40,
            "runtime": {"fingerprint_sha256": "f" * 64},
            "implementation_bindings_sha256": "1" * 64,
            "hard_gate": self.spec["threshold_selection"]["hard_gate"],
            "hard_threshold": threshold,
            "endpoint_performance": holdout_endpoints,
            "results_by_code": holdout_results,
            "diagnostic_flags_by_code": {
                item["anonymous_code"]: [] for item in measurements
            },
            "passed": all(
                endpoint["passed"] for endpoint in holdout_endpoints.values()
            ),
            "measurements": measurements,
            "identity_reveal": holdout_reveal,
            "threshold_changes_authorized": False,
            "one_shot_consumed": True,
            "failure": None,
        }
        common.validate_holdout_report_nested(holdout_report, self.spec, threshold)
        common.validate_report_evaluation_bindings(
            holdout_report, manifest, labels, "holdout", self.spec
        )
        changed_holdout = copy.deepcopy(holdout_report)
        changed_holdout["threshold_changes_authorized"] = True
        with self.assertRaises(RuntimeError):
            common.validate_holdout_report_nested(changed_holdout, self.spec, threshold)

        locked_report = {
            "artifact": "microtexture-v2-r4-locked-clean-reference-report",
            "schema_version": "microtexture-v2-r4-locked-clean-reference-report/2",
            "spec_sha256": common.SPEC_SHA256,
            "blind_key_commitment": "a" * 64,
            "frozen_thresholds_sha256": "2" * 64,
            "locked_clean_reference_sha256": "4" * 64,
            "source_crop_xywh": [512, 320, 512, 384],
            "metric_window_xywh_within_source_crop": [128, 96, 256, 192],
            "effective_source_xywh": [640, 416, 256, 192],
            "evaluation_marker_sha256": "d" * 64,
            "evaluated_at": "2026-01-01T00:00:00+00:00",
            "captured_git_head": "e" * 40,
            "runtime": {"fingerprint_sha256": "f" * 64},
            "implementation_bindings_sha256": "1" * 64,
            "metrics": copy.deepcopy(zero_metrics),
            "hard_threshold": threshold,
            "hard_composite_accepted": True,
            "passed": True,
            "one_shot_consumed": True,
            "failure": None,
        }
        common.validate_locked_clean_reference_report_nested(
            locked_report, self.spec, threshold
        )
        changed_locked = copy.deepcopy(locked_report)
        changed_locked["metrics"]["microartifact_occupancy_per_mp"] = (
            float(threshold["threshold"]) + 1.0
        )
        with self.assertRaises(RuntimeError):
            common.validate_locked_clean_reference_report_nested(
                changed_locked, self.spec, threshold
            )

        insufficient_labels = copy.deepcopy(labels)
        warning_code = next(
            code
            for code, label in insufficient_labels.items()
            if label["disposition"] == "warning"
        )
        insufficient_labels[warning_code].update(
            {
                "disposition": "reject",
                "severity_0_to_3": 3,
                "grain_visible": True,
                "tiny_speck_visible": True,
                "microblob_visible": True,
                "short_line_visible": True,
                "parallel_bundle_visible": True,
            }
        )
        (
            closed_threshold,
            closed_endpoints,
            closed_results,
            closed_status,
            closed_audit,
        ) = common.select_hard_threshold_from_measurements(
            measured, insufficient_labels, clusters, self.spec
        )
        self.assertIsNone(closed_threshold)
        self.assertEqual(closed_status, "no-admissible-threshold")
        closed_report = copy.deepcopy(report)
        closed_report.update(
            {
                "hard_threshold": closed_threshold,
                "endpoint_performance": closed_endpoints,
                "results_by_code": closed_results,
                "selection_status": closed_status,
                "threshold_selection_audit": closed_audit,
                "passed": False,
            }
        )
        common.validate_calibration_report_nested(closed_report, self.spec)
        common.validate_report_evaluation_bindings(
            closed_report,
            manifest,
            insufficient_labels,
            "calibration",
            self.spec,
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
            "records": [{"anonymous_code": code}],
        }
        labels_value = {
            "artifact": "microtexture-v2-r4-root-vision-labels",
            "schema_version": "microtexture-v2-r4-root-vision-labels/2",
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
