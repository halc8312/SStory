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


H4 = _load_module("style_candidate_h4_compatibility", "audit_style_candidate_h4.py")
H5 = _load_module("style_candidate_h5_audit", "audit_style_candidate_h5.py")
EXPECTED_H4_REPORT_SHA256 = (
    "05b83500cea3eaa107a4373d0d935b6b0ab785fdd3e33fa22be183172fdbf78f"
)


class CandidateH5AuditTest(unittest.TestCase):
    def _audit_h5_to(self, report_path: Path):
        return H5.audit(
            final_path=H5.DEFAULT_FINAL,
            raw_path=H5.DEFAULT_RAW,
            prompt_path=H5.DEFAULT_PROMPT,
            reference_b1_path=H5.DEFAULT_REFERENCE_B1,
            vision_schema_path=H5.DEFAULT_VISION_SCHEMA,
            report_path=report_path,
        )

    def test_h4_report_regenerates_byte_identically(self) -> None:
        committed = H4.DEFAULT_REPORT.read_bytes()
        self.assertEqual(hashlib.sha256(committed).hexdigest(), EXPECTED_H4_REPORT_SHA256)
        with tempfile.TemporaryDirectory() as raw_directory:
            regenerated_path = Path(raw_directory) / "h4.json"
            H4.audit(
                final_path=H4.DEFAULT_FINAL,
                raw_path=H4.DEFAULT_RAW,
                prompt_path=H4.DEFAULT_PROMPT,
                reference_b1_path=H4.DEFAULT_REFERENCE_B1,
                vision_schema_path=H4.DEFAULT_VISION_SCHEMA,
                report_path=regenerated_path,
            )
            regenerated = regenerated_path.read_bytes()
        self.assertEqual(regenerated, committed)

    def test_repository_h5_records_all_proxy_results_without_relaxation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            report_path = Path(raw_directory) / "h5.json"
            report = self._audit_h5_to(report_path)
            written = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(written, report)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["decision"], "automated-gates-failed")
        self.assertEqual(
            report["failed_gates"],
            ["palette_continuity_with_b1", "downsample_readability_proxy"],
        )
        self.assertEqual(
            report["artifacts"]["final"]["sha256"], H5.EXPECTED_SHA256["final"]
        )
        self.assertEqual(
            report["artifacts"]["raw"]["sha256"], H5.EXPECTED_SHA256["raw"]
        )
        self.assertEqual(
            report["artifacts"]["prompt"]["sha256"], H5.EXPECTED_SHA256["prompt"]
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

    def test_h5_semantic_checks_remain_owned_by_vision(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            report = self._audit_h5_to(Path(raw_directory) / "h5.json")

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

    def test_h5_audit_refuses_to_overwrite_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            report_path = Path(raw_directory) / "occupied.json"
            report_path.write_text("occupied", encoding="utf-8")
            with self.assertRaisesRegex(H5.H5AuditError, "refusing to overwrite"):
                self._audit_h5_to(report_path)

    def test_h5_prompt_hash_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            prompt_path = Path(raw_directory) / "prompt.txt"
            prompt_path.write_text("changed prompt", encoding="utf-8")
            with self.assertRaisesRegex(H5.H5AuditError, "prompt SHA-256 mismatch"):
                H5.audit(
                    final_path=H5.DEFAULT_FINAL,
                    raw_path=H5.DEFAULT_RAW,
                    prompt_path=prompt_path,
                    reference_b1_path=H5.DEFAULT_REFERENCE_B1,
                    vision_schema_path=H5.DEFAULT_VISION_SCHEMA,
                    report_path=Path(raw_directory) / "h5.json",
                )


if __name__ == "__main__":
    unittest.main()
