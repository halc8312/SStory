from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath

import jsonschema


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts/map-production"
sys.path.insert(0, str(SCRIPT_DIR))
MODULE_PATH = SCRIPT_DIR / "audit_style_candidates_h10_h13.py"
SPEC = importlib.util.spec_from_file_location("h10_h13_rejection_audit", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


EXPECTED = {
    10: {
        "status": "failed",
        "failed_gates": ["palette_continuity_with_b1"],
        "rgb": 0.685099,
        "hsv": 0.546844,
        "bhattacharyya": 0.893971,
        "maximum_mean_delta": 13.67663,
        "coverage_25": 0.851562,
        "downsample_passed": True,
        "vision_score": 65,
    },
    11: {
        "status": "passed",
        "failed_gates": [],
        "rgb": 0.751536,
        "hsv": 0.631582,
        "bhattacharyya": 0.930908,
        "maximum_mean_delta": 5.313231,
        "coverage_25": 0.903646,
        "downsample_passed": True,
        "vision_score": 68,
    },
    12: {
        "status": "failed",
        "failed_gates": [
            "palette_continuity_with_b1",
            "downsample_readability_proxy",
        ],
        "rgb": 0.707662,
        "hsv": 0.620138,
        "bhattacharyya": 0.903503,
        "maximum_mean_delta": 1.887271,
        "coverage_25": 0.815104,
        "downsample_passed": False,
        "vision_score": 66,
    },
    13: {
        "status": "failed",
        "failed_gates": [
            "palette_continuity_with_b1",
            "downsample_readability_proxy",
        ],
        "rgb": 0.680064,
        "hsv": 0.548055,
        "bhattacharyya": 0.895404,
        "maximum_mean_delta": 6.642775,
        "coverage_25": 0.802083,
        "downsample_passed": False,
        "vision_score": 62,
    },
}


class CandidateH10H13RejectionAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory()
        cls.report_dir = Path(cls._temporary_directory.name)
        cls.reports = {
            number: MODULE.audit_candidate(
                candidate,
                report_path=cls.report_dir / f"h{number}.json",
            )
            for number, candidate in MODULE.CANDIDATES.items()
        }

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary_directory.cleanup()

    def test_unchanged_h4_gate_results_are_locked(self) -> None:
        for number, expected in EXPECTED.items():
            report = self.reports[number]
            self.assertEqual(report["status"], expected["status"])
            self.assertEqual(report["failed_gates"], expected["failed_gates"])
            palette = report["palette_continuity"]
            self.assertEqual(palette["rgb_histogram_intersection"], expected["rgb"])
            self.assertEqual(palette["hsv_histogram_intersection"], expected["hsv"])
            self.assertEqual(palette["rgb_bhattacharyya"], expected["bhattacharyya"])
            self.assertEqual(
                palette["maximum_mean_channel_delta"],
                expected["maximum_mean_delta"],
            )
            scales = {
                item["scale"]: item
                for item in report["downsample_readability"]["scales"]
            }
            self.assertEqual(
                scales[0.25]["macrocell_contrast_coverage"],
                expected["coverage_25"],
            )
            self.assertEqual(
                report["downsample_readability"]["passed"],
                expected["downsample_passed"],
            )

    def test_h11_proxy_pass_does_not_claim_vision_or_golden_acceptance(self) -> None:
        report = self.reports[11]
        self.assertTrue(all(report["automated_gates"].values()))
        self.assertEqual(
            report["decision"], "automated-gates-passed-pending-vision"
        )
        self.assertTrue(report["identity"]["raw_only_rejected_trial"])
        self.assertFalse(report["identity"]["adopted_final_exists"])
        self.assertTrue(
            report["vision_handoff"]["automated_audit_is_not_golden_acceptance"]
        )

    def test_failed_gates_remain_failed_in_reports(self) -> None:
        self.assertFalse(
            self.reports[10]["automated_gates"]["palette_continuity_with_b1"]
        )
        for number in (12, 13):
            gates = self.reports[number]["automated_gates"]
            self.assertFalse(gates["palette_continuity_with_b1"])
            self.assertFalse(gates["downsample_readability_proxy"])

    def test_raw_only_identity_is_explicit_and_not_a_fake_final(self) -> None:
        for report in self.reports.values():
            identity = report["audit_engine"]["raw_final_identity"]
            self.assertFalse(identity["applicable"])
            self.assertIsNone(identity["passed"])
            self.assertNotIn("final", report["artifacts"])
            self.assertTrue(report["artifacts"]["raw"]["path"].endswith("-raw.png"))

    def test_receipts_preserve_unknown_generation_metadata_and_repo_paths(self) -> None:
        for candidate in MODULE.CANDIDATES.values():
            receipt = json.loads(candidate.receipt_path.read_text(encoding="utf-8"))
            limitations = receipt["provenance_limitations"]
            self.assertEqual(limitations["model"], "unknown")
            self.assertEqual(limitations["model_snapshot"], "unavailable")
            self.assertEqual(limitations["generation_id"], "unavailable")
            self.assertIsNone(limitations["generation_timestamp_utc"])
            paths = [receipt["prompt"]["path"], receipt["output"]["path"]]
            paths.extend(item["path"] for item in receipt["inputs"])
            for value in paths:
                pure = PurePosixPath(value)
                self.assertFalse(pure.is_absolute())
                self.assertNotIn("\\", value)
                self.assertNotIn(":", value)
                self.assertNotIn("..", pure.parts)

    def test_audit_refuses_to_overwrite_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            report_path = Path(raw_directory) / "occupied.json"
            report_path.write_text("occupied", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.CandidateAuditError, "overwrite"):
                MODULE.audit_candidate(MODULE.CANDIDATES[10], report_path=report_path)

    def test_hash_guard_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            changed = Path(raw_directory) / "changed.txt"
            changed.write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.CandidateAuditError, "SHA-256 mismatch"):
                MODULE._assert_input(changed, "0" * 64, "changed fixture")

    def test_committed_automated_reports_regenerate_byte_identically(self) -> None:
        for number, candidate in MODULE.CANDIDATES.items():
            generated = self.report_dir / f"h{number}.json"
            self.assertEqual(generated.read_bytes(), candidate.report_path.read_bytes())

    def test_root_vision_reports_are_schema_valid_and_rejected(self) -> None:
        schema = json.loads(MODULE.VISION_SCHEMA.read_text(encoding="utf-8"))
        validator = jsonschema.Draft7Validator(
            schema, format_checker=jsonschema.FormatChecker()
        )
        for number, candidate in MODULE.CANDIDATES.items():
            path = REPO_ROOT / f"world/map-production/qa/{candidate.job_id}.json"
            report = json.loads(path.read_text(encoding="utf-8"))
            validator.validate(report)
            self.assertEqual(report["image_path"], MODULE.h4._relative(candidate.raw_path))
            self.assertEqual(report["status"], "complete")
            self.assertFalse(report["golden_reference"])
            self.assertEqual(report["decision"], "rejected")
            self.assertEqual(report["acceptance_threshold"], 94)
            self.assertEqual(report["total_score"], EXPECTED[number]["vision_score"])
            self.assertLess(report["total_score"], report["acceptance_threshold"])
            failures = {item["id"]: item for item in report["immediate_failures"]}
            self.assertTrue(failures["repetition"]["detected"])


if __name__ == "__main__":
    unittest.main()
