from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/map-production/render_style_candidate_h15_flat_height.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("h15", SCRIPT)
assert SPEC and SPEC.loader
h15 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(h15)


class H15Test(unittest.TestCase):
    def test_locked_protected_flat_preview(self) -> None:
        h15.DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=h15.DEFAULT_OUTPUT.parent) as temporary:
            report = h15.render(output_dir=Path(temporary))
            self.assertEqual(report["full_resolution_protection"]["protected_violation_pixels"], 0)
            self.assertGreaterEqual(report["perspective_proxies"]["city_flat_footprints"], 300)
            self.assertGreaterEqual(report["perspective_proxies"]["port_flat_footprints"], 50)
            self.assertEqual(report["perspective_proxies"]["city_side_faces"], 0)
            self.assertEqual(report["perspective_proxies"]["port_side_faces"], 0)
            for name in (h15.MASTER, h15.MASK, h15.CONTACT, h15.REPORT):
                self.assertTrue((Path(temporary) / name).is_file())


if __name__ == "__main__":
    unittest.main()
