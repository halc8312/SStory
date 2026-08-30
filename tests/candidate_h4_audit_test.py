from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts/map-production"
sys.path.insert(0, str(SCRIPT_DIR))
MODULE_PATH = SCRIPT_DIR / "audit_style_candidate_h4.py"
SPEC = importlib.util.spec_from_file_location("style_candidate_h4_audit", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CandidateH4AuditTest(unittest.TestCase):
    def _audit_to(self, report_path: Path):
        return MODULE.audit(
            final_path=MODULE.DEFAULT_FINAL,
            raw_path=MODULE.DEFAULT_RAW,
            prompt_path=MODULE.DEFAULT_PROMPT,
            reference_b1_path=MODULE.DEFAULT_REFERENCE_B1,
            vision_schema_path=MODULE.DEFAULT_VISION_SCHEMA,
            report_path=report_path,
        )

    def test_repository_h4_passes_all_automated_gates(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            report_path = Path(raw_directory) / "report.json"
            report = self._audit_to(report_path)
            written = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(written, report)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(
            report["decision"], "automated-gates-passed-pending-vision"
        )
        self.assertTrue(all(report["automated_gates"].values()))
        self.assertEqual(
            report["artifacts"]["final"]["sha256"],
            MODULE.EXPECTED_SHA256["final"],
        )
        self.assertTrue(report["identity"]["raw_final_byte_identical"])

        contract = report["image_contract"]
        self.assertTrue(contract["passed"])
        self.assertTrue(contract["alpha_free"])
        self.assertTrue(contract["profile_matches_b1"])
        final = contract["images"]["final"]
        self.assertEqual((final["width"], final["height"]), (1536, 1024))
        self.assertEqual((final["format"], final["mode"]), ("PNG", "RGB"))
        self.assertEqual(final["png_color_type"], 2)
        self.assertFalse(final["alpha_or_transparency_present"])

        self.assertFalse(report["boundary"]["solid_color_signal_detected"])
        self.assertFalse(report["boundary"]["decorative_frame_proxy_detected"])
        self.assertTrue(report["palette_continuity"]["passed"])
        self.assertEqual(report["exact_repetition"]["duplicate_groups"], 0)
        self.assertTrue(report["downsample_readability"]["passed"])
        self.assertTrue(
            all(item["passed"] for item in report["downsample_readability"]["scales"])
        )

    def test_text_and_perspective_are_explicitly_deferred_to_vision(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            report = self._audit_to(Path(raw_directory) / "report.json")

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
        self.assertTrue(
            report["vision_handoff"]["automated_audit_is_not_golden_acceptance"]
        )

    def test_audit_refuses_to_overwrite_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            report_path = Path(raw_directory) / "occupied.json"
            report_path.write_text("occupied", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.H4AuditError, "refusing to overwrite"):
                self._audit_to(report_path)

    def test_prompt_hash_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            prompt_path = Path(raw_directory) / "prompt.txt"
            prompt_path.write_text("changed prompt", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.H4AuditError, "prompt SHA-256 mismatch"):
                MODULE.audit(
                    final_path=MODULE.DEFAULT_FINAL,
                    raw_path=MODULE.DEFAULT_RAW,
                    prompt_path=prompt_path,
                    reference_b1_path=MODULE.DEFAULT_REFERENCE_B1,
                    vision_schema_path=MODULE.DEFAULT_VISION_SCHEMA,
                    report_path=Path(raw_directory) / "report.json",
                )

    def test_boundary_proxy_detects_a_solid_frame(self) -> None:
        image = Image.new("RGB", (320, 240))
        image.putdata(
            [
                (
                    (x * 17 + y * 3) % 256,
                    (x * 7 + y * 19) % 256,
                    (x * 11 + y * 13) % 256,
                )
                for y in range(image.height)
                for x in range(image.width)
            ]
        )
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, image.width - 1, image.height - 1), outline=(8, 8, 8), width=20)
        try:
            metrics = MODULE.boundary_metrics(image)
        finally:
            image.close()
        self.assertFalse(metrics["passed"])
        self.assertTrue(metrics["solid_color_signal_detected"])

    def test_repetition_proxy_detects_a_large_exact_clone(self) -> None:
        image = Image.new("RGB", (384, 256))
        image.putdata(
            [
                (
                    (x * 29 + y * 5 + x * y) % 256,
                    (x * 13 + y * 31 + x * y * 3) % 256,
                    (x * 7 + y * 11 + x * y * 5) % 256,
                )
                for y in range(image.height)
                for x in range(image.width)
            ]
        )
        clone = image.crop((0, 0, 128, 128))
        try:
            image.paste(clone, (192, 64))
            metrics = MODULE.exact_repetition_metrics(image)
        finally:
            clone.close()
            image.close()
        scale = next(
            item for item in metrics["scales"] if item["block_size_px"] == 128
        )
        self.assertFalse(metrics["passed"])
        self.assertGreater(scale["duplicate_groups"], 0)


if __name__ == "__main__":
    unittest.main()
