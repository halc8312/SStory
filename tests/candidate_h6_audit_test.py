from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts/map-production"
sys.path.insert(0, str(SCRIPT_DIR))


def _load_module(name: str, filename: str):
    module_path = SCRIPT_DIR / filename
    spec = importlib.util.spec_from_file_location(name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


H4 = _load_module("audit_style_candidate_h4", "audit_style_candidate_h4.py")
H5 = _load_module("audit_style_candidate_h5", "audit_style_candidate_h5.py")
H6 = _load_module("audit_style_candidate_h6", "audit_style_candidate_h6.py")
EXPECTED_H4_REPORT_SHA256 = (
    "9f1d7b88b8696ec61e05810864e2236afffc088a6f58b042d699c77419829f31"
)
EXPECTED_H5_REPORT_SHA256 = (
    "43b82a26c7854a377e2a4a99229798bc2adb758eab3130565b98a90164bd473e"
)


class CandidateH6AuditTest(unittest.TestCase):
    def _audit_h6_to(self, report_path: Path):
        return H6.audit(
            final_path=H6.DEFAULT_FINAL,
            raw_path=H6.DEFAULT_RAW,
            prompt_path=H6.DEFAULT_PROMPT,
            reference_b1_path=H6.DEFAULT_REFERENCE_B1,
            vision_schema_path=H6.DEFAULT_VISION_SCHEMA,
            report_path=report_path,
        )

    def test_h4_and_h5_reports_regenerate_byte_identically(self) -> None:
        fixtures = (
            (H4, H4.DEFAULT_REPORT, EXPECTED_H4_REPORT_SHA256),
            (H5, H5.DEFAULT_REPORT, EXPECTED_H5_REPORT_SHA256),
        )
        with tempfile.TemporaryDirectory() as raw_directory:
            for module, committed_path, expected_sha256 in fixtures:
                committed = committed_path.read_bytes()
                self.assertEqual(
                    hashlib.sha256(committed).hexdigest(), expected_sha256
                )
                regenerated_path = (
                    Path(raw_directory) / f"{module.__name__}-regenerated.json"
                )
                module.audit(
                    final_path=module.DEFAULT_FINAL,
                    raw_path=module.DEFAULT_RAW,
                    prompt_path=module.DEFAULT_PROMPT,
                    reference_b1_path=module.DEFAULT_REFERENCE_B1,
                    vision_schema_path=module.DEFAULT_VISION_SCHEMA,
                    report_path=regenerated_path,
                )
                self.assertEqual(regenerated_path.read_bytes(), committed)

    def test_repository_h6_records_same_threshold_results(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            report_path = Path(raw_directory) / "h6.json"
            report = self._audit_h6_to(report_path)
            written = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(written, report)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["decision"], "automated-gates-failed")
        self.assertEqual(
            report["failed_gates"],
            ["palette_continuity_with_b1", "downsample_readability_proxy"],
        )
        self.assertEqual(
            report["artifacts"]["final"]["sha256"], H6.EXPECTED_SHA256["final"]
        )
        self.assertEqual(
            report["artifacts"]["raw"]["sha256"], H6.EXPECTED_SHA256["raw"]
        )
        self.assertEqual(
            report["artifacts"]["prompt"]["sha256"], H6.EXPECTED_SHA256["prompt"]
        )
        self.assertTrue(report["identity"]["raw_final_byte_identical"])

        final = report["image_contract"]["images"]["final"]
        self.assertTrue(report["image_contract"]["passed"])
        self.assertEqual((final["format"], final["mode"]), ("PNG", "RGB"))
        self.assertEqual((final["width"], final["height"]), (1536, 1024))
        self.assertFalse(final["alpha_or_transparency_present"])
        self.assertTrue(report["boundary"]["passed"])
        self.assertFalse(report["palette_continuity"]["passed"])
        self.assertTrue(report["exact_repetition"]["passed"])

        downsample_by_scale = {
            item["scale"]: item for item in report["downsample_readability"]["scales"]
        }
        self.assertTrue(downsample_by_scale[0.5]["passed"])
        self.assertFalse(downsample_by_scale[0.25]["passed"])
        self.assertFalse(report["downsample_readability"]["passed"])

    def test_h6_semantic_checks_remain_owned_by_vision(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            report = self._audit_h6_to(Path(raw_directory) / "h6.json")

        checks = {item["id"]: item for item in report["vision_handoff"]["checks"]}
        self.assertEqual(
            checks["generated_text_or_pseudotext"]["status"],
            "requires_vision_review",
        )
        self.assertIsNone(checks["generated_text_or_pseudotext"]["automated_claim"])
        self.assertEqual(
            checks["strict_orthographic_plan_view"]["status"],
            "requires_vision_review",
        )
        self.assertIsNone(checks["strict_orthographic_plan_view"]["automated_claim"])

    def test_h6_audit_refuses_to_overwrite_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            report_path = Path(raw_directory) / "occupied.json"
            report_path.write_text("occupied", encoding="utf-8")
            with self.assertRaisesRegex(H6.H6AuditError, "refusing to overwrite"):
                self._audit_h6_to(report_path)

    def test_h6_prompt_hash_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            prompt_path = Path(raw_directory) / "prompt.txt"
            prompt_path.write_text("changed prompt", encoding="utf-8")
            with self.assertRaisesRegex(H6.H6AuditError, "prompt SHA-256 mismatch"):
                H6.audit(
                    final_path=H6.DEFAULT_FINAL,
                    raw_path=H6.DEFAULT_RAW,
                    prompt_path=prompt_path,
                    reference_b1_path=H6.DEFAULT_REFERENCE_B1,
                    vision_schema_path=H6.DEFAULT_VISION_SCHEMA,
                    report_path=Path(raw_directory) / "h6.json",
                )


if __name__ == "__main__":
    unittest.main()
