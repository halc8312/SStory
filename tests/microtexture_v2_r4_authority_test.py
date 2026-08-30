from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_ROOT = REPO_ROOT / "scripts/map-production/microtexture-v2-r4"
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

import calibration_harness as harness  # noqa: E402
import common  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MicrotextureV2R4AuthorityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = common.load_spec()

    def test_spec_and_implementation_bindings_are_exact(self) -> None:
        self.assertEqual(sha256(common.SPEC_PATH), common.SPEC_SHA256)
        bindings = common.validate_implementation_bindings()
        self.assertEqual(bindings["spec_sha256"], common.SPEC_SHA256)
        self.assertEqual(
            set(bindings["files"]),
            set(self.spec["authority_files"]) - {"implementation-bindings.json"},
        )

    def test_only_one_complete_hard_gate_is_preregistered(self) -> None:
        gate = self.spec["threshold_selection"]["hard_gate"]
        self.assertEqual(gate["threshold_count"], 1)
        self.assertEqual(gate["metric"], "microartifact_occupancy_per_mp")
        self.assertTrue(
            self.spec["threshold_selection"]["diagnostic_metrics_are_nonblocking"]
        )
        self.assertFalse(
            self.spec["metric_definition"][
                "diagnostic_reference_levels_development_only"
            ]["may_reject_or_change_threshold"]
        )

    def test_exact_vision_window_and_cluster_contract(self) -> None:
        self.assertEqual(
            self.spec["canvas"]["metric_window"]["xywh"], [128, 96, 256, 192]
        )
        views = self.spec["contact_sheets"]["views"]
        self.assertEqual(
            views,
            [
                {
                    "id": "full-200",
                    "scale_percent": 200,
                    "source_crop_xywh": [128, 96, 256, 192],
                },
                {
                    "id": "northwest-400",
                    "scale_percent": 400,
                    "source_crop_xywh": [128, 96, 128, 96],
                },
                {
                    "id": "northeast-400",
                    "scale_percent": 400,
                    "source_crop_xywh": [256, 96, 128, 96],
                },
                {
                    "id": "southwest-400",
                    "scale_percent": 400,
                    "source_crop_xywh": [128, 192, 128, 96],
                },
                {
                    "id": "southeast-400",
                    "scale_percent": 400,
                    "source_crop_xywh": [256, 192, 128, 96],
                },
            ],
        )
        common.validate_contact_sheet_view_partition(
            self.spec["contact_sheets"],
            self.spec["canvas"]["metric_window"]["xywh"],
        )
        self.assertEqual(
            self.spec["contact_sheets"]["expected_controls_per_split"], 140
        )
        self.assertEqual(self.spec["contact_sheets"]["expected_pages_per_view"], 24)
        self.assertEqual(self.spec["contact_sheets"]["expected_pages_per_split"], 120)
        self.assertEqual(
            self.spec["independent_condition_clusters"]["identity_excludes"],
            ["polarity", "replicate"],
        )
        clusters = self.spec["independent_condition_clusters"]
        self.assertEqual(clusters["expected_unique_clusters_per_split"], 80)
        self.assertEqual(clusters["expected_clean_clusters_per_split"], 20)
        self.assertEqual(clusters["expected_artifact_clusters_per_split"], 60)
        self.assertEqual(clusters["expected_artifact_clusters_per_family"], 10)

    def test_sparse_families_use_exact_zero_through_nine_counts(self) -> None:
        fields = {
            "artifact-speck": "count_in_metric_window",
            "artifact-microblob": "count_in_metric_window",
            "artifact-short-dash": "count_in_metric_window",
            "artifact-parallel-bundle": "pair_count_in_metric_window",
        }
        families = {family["id"]: family for family in self.spec["control_families"]}
        for family_id, field in fields.items():
            for split in ("calibration", "holdout"):
                values = [
                    variant[field]
                    for variant in families[family_id][f"{split}_variants"]
                ]
                self.assertEqual(values, list(range(10)))
                self.assertTrue(all(type(value) is int for value in values))

    def test_label_v2_separates_tiny_speck_and_microblob(self) -> None:
        fields = self.spec["labels"]["required_fields"]
        self.assertIn("tiny_speck_visible", fields)
        self.assertIn("microblob_visible", fields)
        self.assertNotIn("speck_visible", fields)
        self.assertIn("reviewed_at_all_400_percent_quadrants", fields)
        self.assertNotIn("reviewed_at_400_percent", fields)
        self.assertEqual(
            self.spec["labels"]["schema_version"],
            "microtexture-v2-r4-root-vision-labels/2",
        )
        self.assertEqual(
            self.spec["labels"]["exact_artifact_paths"],
            {
                "calibration": "controls/calibration/labels-calibration.json",
                "holdout": "controls/holdout/labels-holdout.json",
            },
        )
        self.assertEqual(
            self.spec["labels"]["sealed_authority_paths"],
            {
                "calibration": "sealed-inputs/calibration-reviewed-labels.json",
                "holdout": "sealed-inputs/holdout-reviewed-labels.json",
            },
        )
        endpoints = {
            endpoint["id"]: endpoint
            for endpoint in self.spec["threshold_selection"]["endpoint_definitions"]
        }
        self.assertIn("tiny_speck_reject_detection", endpoints)
        self.assertIn("microblob_reject_detection", endpoints)

    def test_locked_clean_reference_and_provenance_are_hash_bound(self) -> None:
        locked = self.spec["locked_clean_reference"]
        for path_field, hash_field in (
            ("repo_relative_path", "sha256"),
            ("generation_chain", "generation_chain_sha256"),
            ("generation_receipt", "generation_receipt_sha256"),
            ("root_vision_review", "root_vision_review_sha256"),
            ("independent_vision_review", "independent_vision_review_sha256"),
        ):
            self.assertEqual(sha256(REPO_ROOT / locked[path_field]), locked[hash_field])
        generation_receipt = json.loads(
            (REPO_ROOT / locked["generation_receipt"]).read_text(encoding="utf-8")
        )
        root_review = json.loads(
            (REPO_ROOT / locked["root_vision_review"]).read_text(encoding="utf-8")
        )
        independent_review = json.loads(
            (REPO_ROOT / locked["independent_vision_review"]).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(generation_receipt["output"]["sha256"], locked["sha256"])
        self.assertEqual(
            generation_receipt["prompt_chain"]["sha256"],
            locked["generation_chain_sha256"],
        )
        self.assertEqual(
            generation_receipt["root_vision_review"]["sha256"],
            locked["root_vision_review_sha256"],
        )
        self.assertEqual(
            generation_receipt["independent_vision_review"]["sha256"],
            locked["independent_vision_review_sha256"],
        )
        for review in (root_review, independent_review):
            self.assertEqual(review["source"]["sha256"], locked["sha256"])
            self.assertFalse(review["numeric_metric_evaluation_performed"])
            self.assertTrue(review["passed_for_declared_source_role"])
            self.assertEqual(review["score"], 97)
        self.assertTrue(locked["numeric_evaluation_before_freeze_forbidden"])
        self.assertTrue(locked["production_use_forbidden"])
        revalidation = locked["holdout_preflight_revalidation"]
        self.assertEqual(
            revalidation["required_at"],
            ["holdout-control-generation", "holdout-evaluation-before-marker"],
        )
        self.assertEqual(
            revalidation["exact_path_fields"],
            [
                "repo_relative_path",
                "generation_chain",
                "generation_receipt",
                "root_vision_review",
                "independent_vision_review",
            ],
        )
        self.assertTrue(revalidation["numeric_measurement_forbidden"])

    def test_runtime_and_one_shot_failure_contracts_are_exact(self) -> None:
        runtime = common.runtime_fingerprint()
        for key in (
            "zlib_version",
            "zlib_runtime_version",
            "python_executable_sha256",
            "numpy_core_binary_sha256",
            "scipy_ndimage_binary_sha256",
            "pillow_imaging_binary_sha256",
            "fingerprint_sha256",
        ):
            self.assertIn(key, runtime)
        self.assertIn("failure", common.CALIBRATION_REPORT_KEYS)
        self.assertIn("failure", common.LOCKED_CLEAN_REFERENCE_REPORT_KEYS)
        self.assertIn("failure", common.HOLDOUT_REPORT_KEYS)
        self.assertIn("calibration_captured_git_head", common.FROZEN_KEYS)
        self.assertIn("calibration_captured_git_head", common.RECEIPT_KEYS)
        self.assertIn("locked_clean_reference_captured_git_head", common.RECEIPT_KEYS)
        one_shot = self.spec["one_shot_failure_reporting"]
        self.assertEqual(
            one_shot["completion_report_paths"],
            {
                "calibration": "completions/calibration.json",
                "locked-clean-reference": "completions/locked-clean-reference.json",
                "holdout": "completions/holdout.json",
            },
        )
        self.assertTrue(one_shot["completion_is_exclusive_final_stage_operation"])
        self.assertTrue(
            one_shot[
                "authority_loaders_require_completion_and_reject_failure_coexistence"
            ]
        )
        self.assertEqual(
            inspect.signature(common.load_calibration_report)
            .parameters["require_completion"]
            .default,
            True,
        )
        self.assertEqual(
            inspect.signature(common.load_locked_clean_reference_report)
            .parameters["require_completion"]
            .default,
            True,
        )
        self.assertEqual(
            inspect.signature(common.load_holdout_report)
            .parameters["require_completion"]
            .default,
            True,
        )
        for validator in (
            common.validate_calibration_report_nested,
            common.validate_locked_clean_reference_report_nested,
            common.validate_holdout_report_nested,
            common.validate_report_evaluation_bindings,
            common.validate_secret_catalog_report_binding,
            common.validate_vision_labels_payload,
            common.verify_tracked_locked_clean_reference_provenance,
            common.validate_stage_completion_structure,
            common.load_stage_completion,
            common.load_holdout_report,
        ):
            self.assertTrue(callable(validator))

    def test_hash_bound_r4_self_tests_pass(self) -> None:
        environment = os.environ.copy()
        environment.pop("MICROTEXTURE_V2_R4_BLIND_KEY", None)
        result = subprocess.run(
            [sys.executable, str(CODE_ROOT / "self_test.py")],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )

    def test_each_stage_writes_completion_as_its_final_try_operation(self) -> None:
        expected_precompletion_loaders = {
            harness.calibrate: "load_calibration_report",
            harness.validate_locked_clean_reference: (
                "load_locked_clean_reference_report"
            ),
            harness.holdout: "load_holdout_report",
        }
        for function, loader_name in expected_precompletion_loaders.items():
            tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
            function_node = tree.body[0]
            self.assertIsInstance(function_node, ast.FunctionDef)
            stage_try = next(
                statement
                for statement in function_node.body
                if isinstance(statement, ast.Try)
            )
            final_statement = stage_try.body[-1]
            self.assertIsInstance(final_statement, ast.Expr)
            self.assertIsInstance(final_statement.value, ast.Call)
            self.assertEqual(
                getattr(final_statement.value.func, "id", None),
                "write_stage_completion_exclusive",
            )
            calls = [
                node
                for node in ast.walk(stage_try)
                if isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == loader_name
            ]
            self.assertEqual(len(calls), 1)
            require_completion = next(
                keyword
                for keyword in calls[0].keywords
                if keyword.arg == "require_completion"
            )
            self.assertIsInstance(require_completion.value, ast.Constant)
            self.assertIs(require_completion.value.value, False)
            self.assertTrue(
                any(
                    isinstance(handler.type, ast.Name)
                    and handler.type.id == "BaseException"
                    for handler in stage_try.handlers
                )
            )

    def test_r3_failure_is_tracked_and_closed(self) -> None:
        audit = json.loads(
            (
                REPO_ROOT
                / "world/map-production/qa/microtexture-v2-r3-calibration-failure.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(audit["outcome"], "failed_closed")
        self.assertTrue(audit["one_shot_contract"]["r3_closed"])
        self.assertFalse(audit["one_shot_contract"]["thresholds_frozen"])
        self.assertEqual(
            sha256(
                REPO_ROOT
                / "scripts/map-production/microtexture-v2-r3/preregistered-spec.json"
            ),
            audit["hash_bindings"]["preregistered_spec_sha256"],
        )
        self.assertEqual(
            sha256(
                REPO_ROOT
                / "scripts/map-production/microtexture-v2-r3/implementation-bindings.json"
            ),
            audit["hash_bindings"]["implementation_bindings_sha256"],
        )

    def test_cluster_macro_does_not_treat_duplicate_polarity_as_new_sample(
        self,
    ) -> None:
        clusters = {
            "dark": "condition-a",
            "light": "condition-a",
            "other": "condition-b",
        }
        rejected = {"dark": True, "light": True, "other": False}
        first = harness._cluster_macro_rate(
            ["dark", "other"], rejected, clusters, "reject"
        )
        paired = harness._cluster_macro_rate(
            ["dark", "light", "other"], rejected, clusters, "reject"
        )
        self.assertEqual(first[0], paired[0])
        self.assertEqual(first[2], paired[2])
        self.assertEqual(first[1] + 1, paired[1])

    def test_r4_tree_contains_no_legacy_locked_positive_contract(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in CODE_ROOT.iterdir()
            if path.is_file() and path.suffix in {".py", ".json", ".md"}
        )
        self.assertNotIn("locked_positive", text)
        self.assertNotIn("locked-positive", text)


if __name__ == "__main__":
    unittest.main()
