from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/map-production/render_style_candidate_h16_micro_inpaint.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("h16", SCRIPT)
assert SPEC and SPEC.loader
h16 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(h16)


class H16Test(unittest.TestCase):
    def test_iteration_one_artifacts_are_local_and_protected(self) -> None:
        h16.DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".candidate-h16-test-", dir=h16.DEFAULT_OUTPUT.parent
        ) as temporary:
            output_dir = Path(temporary)
            report = h16.render(output_dir=output_dir)
            protection = report["full_resolution_protection"]
            locality = report["component_local_repair"]
            self.assertEqual(protection["protected_violation_pixels"], 0)
            self.assertLess(protection["allowed_edit_coverage_percent"], 25.0)
            self.assertFalse(locality["wide_region_replacement_used"])
            self.assertGreater(locality["highland_detected_components"], 0)
            self.assertLessEqual(
                locality["maximum_individual_dilated_component_pixels"], 1250
            )
            self.assertEqual(
                report["perspective_proxies"][
                    "shoreline_displacement_pixels_outside_port"
                ],
                0,
            )
            for name in (h16.MASTER, h16.MASK, h16.CONTACT, h16.REPORT):
                self.assertTrue((output_dir / name).is_file())


if __name__ == "__main__":
    unittest.main()
