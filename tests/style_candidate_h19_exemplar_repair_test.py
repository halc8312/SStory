from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/map-production/render_style_candidate_h19_exemplar_repair.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("h19", SCRIPT)
assert SPEC and SPEC.loader
h19 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = h19
SPEC.loader.exec_module(h19)


class H19ProofTest(unittest.TestCase):
    def test_crop_proof_is_bounded_unique_and_exact(self) -> None:
        proof_dir = h19.DEFAULT_OUTPUT / h19.DEFAULT_PROOF_ITERATION
        report_path = proof_dir / h19.PROOF_REPORT
        self.assertTrue(report_path.is_file(), "render the mandatory proof first")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertFalse(report["scope"]["full_master_written"])
        self.assertEqual(report["exact_protection"]["protected_violation_pixels"], 0)
        self.assertLess(
            report["exact_protection"]["allowed_edit_coverage_percent_full_canvas"],
            20.0,
        )
        self.assertEqual(
            report["method"]["patch_source_count"],
            report["method"]["unique_patch_source_count"],
        )
        self.assertFalse(report["method"]["broad_region_fill_used"])
        self.assertFalse(report["method"]["blur_or_inpaint_used_for_repair"])
        self.assertFalse(report["method"]["shoreline_touched"])
        self.assertGreater(report["method"]["detected_component_count"], 40)
        self.assertEqual(report["self_vision_review"]["status"], "rejected")
        self.assertTrue(report["self_vision_review"]["immediate_failure_detected"])
        for name in (
            h19.PROOF_SOURCE,
            h19.PROOF_REPAIRED,
            h19.PROOF_MASK,
            h19.PROOF_CONTACT,
            h19.PROOF_REPORT,
        ):
            self.assertTrue((proof_dir / name).is_file())

    def test_full_mode_remains_locked_before_vision(self) -> None:
        self.assertEqual(h19.main(["--mode", "full"]), 2)


if __name__ == "__main__":
    unittest.main()
