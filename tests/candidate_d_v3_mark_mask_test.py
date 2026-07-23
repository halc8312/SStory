from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts/map-production/extract_candidate_d_v3_mark_mask.py"
SPEC = importlib.util.spec_from_file_location("candidate_d_v3_mark_mask", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CandidateDV3MarkMaskTest(unittest.TestCase):
    def test_repository_assets_extract_exactly_forty_components(self) -> None:
        base = MODULE._load_gray(MODULE.DEFAULT_BASE)
        candidate = MODULE._load_gray(MODULE.DEFAULT_CANDIDATE)
        try:
            components = MODULE.extract_components(base, candidate)
        finally:
            base.close()
            candidate.close()

        self.assertEqual(len(components), 40)
        self.assertEqual(len({item["component_id"] for item in components}), 40)
        self.assertTrue(all(25 <= item["area_px"] <= 120 for item in components))
        self.assertTrue(
            all(item["covariance_eigenvalue_ratio"] >= 8 for item in components)
        )
        north_east = sum(item["centroid"][1] < 420 for item in components)
        south_east = sum(item["centroid"][1] >= 760 for item in components)
        self.assertEqual((north_east, south_east), (23, 17))

    def test_generated_control_is_narrow_and_composite_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            report = MODULE.generate(
                base_path=MODULE.DEFAULT_BASE,
                candidate_path=MODULE.DEFAULT_CANDIDATE,
                fragment_guide_path=MODULE.DEFAULT_FRAGMENT_GUIDE,
                control_path=directory / "control.json",
                mask_path=directory / "mask.png",
                report_path=directory / "report.json",
            )
            control = json.loads((directory / "control.json").read_text(encoding="utf-8"))
            self.assertEqual(len(control["include_strokes"]), 88)
            self.assertEqual(report["automated_component_count"], 40)
            self.assertEqual(report["reviewed_target_count"], 44)
            self.assertEqual(len(report["reviewed_component_allowlist"]), 39)
            self.assertEqual(report["reviewed_false_positives"], ["mark_26"])
            self.assertEqual(len(report["reviewed_manual_strokes"]), 5)
            self.assertEqual(
                report["role_assignment"],
                "not-claimed-because-v3-does-not-preserve-four-marks-per-ridge",
            )
            self.assertGreater(report["mask_pixels"], 25_000)
            self.assertLess(report["mask_pixels"], 40_000)
            self.assertGreater(report["opaque_mask_pixels"], 15_000)
            self.assertEqual(
                report["reviewed_detected_target_pixels_without_opaque_core"], 0
            )
            self.assertEqual(report["masked_false_positive_pixels"], 0)
            self.assertEqual(report["manual_endpoint_core_failures"], [])
            self.assertEqual(report["outside_parent_edit_mask_pixels"], 0)
            with Image.open(directory / "mask.png") as mask:
                self.assertEqual(mask.mode, "L")
                self.assertEqual(mask.size, MODULE.CANVAS)
                self.assertEqual(mask.getextrema(), (0, 255))

    def test_generation_refuses_to_overwrite_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            control = directory / "control.json"
            control.write_text("occupied", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.MarkMaskError, "refusing to overwrite"):
                MODULE.generate(
                    base_path=MODULE.DEFAULT_BASE,
                    candidate_path=MODULE.DEFAULT_CANDIDATE,
                    fragment_guide_path=MODULE.DEFAULT_FRAGMENT_GUIDE,
                    control_path=control,
                    mask_path=directory / "mask.png",
                    report_path=directory / "report.json",
                )


if __name__ == "__main__":
    unittest.main()
