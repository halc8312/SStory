from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts/map-production"
sys.path.insert(0, str(SCRIPT_DIR))
MODULE_PATH = SCRIPT_DIR / "audit_candidate_d_v4_removal.py"
SPEC = importlib.util.spec_from_file_location("candidate_d_v4_removal_audit", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CandidateDV4RemovalAuditTest(unittest.TestCase):
    def test_repository_candidate_removes_only_the_reviewed_route_marks(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            report = MODULE.audit(
                base_path=MODULE.DEFAULT_BASE,
                before_path=MODULE.DEFAULT_BEFORE,
                after_path=MODULE.DEFAULT_AFTER,
                control_path=MODULE.DEFAULT_CONTROL,
                mask_path=MODULE.DEFAULT_MASK,
                composite_report_path=MODULE.DEFAULT_COMPOSITE_REPORT,
                report_path=Path(raw_directory) / "report.json",
            )

        self.assertEqual(report["reviewed_target_count"], 44)
        self.assertEqual(report["reviewed_automated_targets"], 39)
        self.assertEqual(report["automated_route_like_components_post_edit"], 0)
        self.assertEqual(report["preserved_false_positive_components_post_edit"], 1)
        self.assertEqual(report["preserved_false_positive_id"], "mark_26")
        self.assertEqual(report["masked_false_positive_pixels"], 0)
        self.assertEqual(report["false_positive_changed_pixels"], 0)
        self.assertEqual(report["manual_targets_with_post_edit_detected_pixels"], 0)
        self.assertTrue(
            all(item["pre_edit_detected_pixels"] > 0 for item in report["manual_targets"])
        )
        self.assertEqual(report["outside_mask_max_channel_difference"], 0)

    def test_audit_refuses_to_overwrite_a_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            report_path = Path(raw_directory) / "occupied.json"
            report_path.write_text("occupied", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.RemovalAuditError, "refusing to overwrite"):
                MODULE.audit(
                    base_path=MODULE.DEFAULT_BASE,
                    before_path=MODULE.DEFAULT_BEFORE,
                    after_path=MODULE.DEFAULT_AFTER,
                    control_path=MODULE.DEFAULT_CONTROL,
                    mask_path=MODULE.DEFAULT_MASK,
                    composite_report_path=MODULE.DEFAULT_COMPOSITE_REPORT,
                    report_path=report_path,
                )


if __name__ == "__main__":
    unittest.main()
