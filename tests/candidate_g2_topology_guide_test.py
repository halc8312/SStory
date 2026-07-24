from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts/map-production/render_candidate_g2_topology_guide.py"
SPEC = importlib.util.spec_from_file_location(
    "candidate_g2_topology_guide", MODULE_PATH
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

CONTROL_PATH = (
    REPO_ROOT / "world/map-production/controls/style-candidate-g-v2-topology-guide.json"
)
OUTPUT_PATH = (
    REPO_ROOT / "world/map-production/controls/style-candidate-g-v2-topology-guide.png"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decoded_raster_identity(path: Path) -> tuple[str, tuple[int, int], bytes]:
    with Image.open(path) as opened:
        opened.load()
        return opened.mode, opened.size, opened.tobytes()


class CandidateG2TopologyGuideTest(unittest.TestCase):
    def test_committed_guide_is_reproducible_complete_and_inset(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sstory-g2-guide-", dir=REPO_ROOT
        ) as raw:
            regenerated = Path(raw) / "guide.png"
            metrics = MODULE.render(CONTROL_PATH, regenerated)

            self.assertEqual(
                _decoded_raster_identity(regenerated),
                _decoded_raster_identity(OUTPUT_PATH),
            )
            self.assertEqual(
                _sha256(OUTPUT_PATH),
                "a6c8815d5f1a769a6ebfeda8478cf52f586fdb3fd11156c734c3e43d9b6b188f",
            )
            self.assertEqual(metrics["shape_count"], 6)
            self.assertEqual(metrics["minimum_canvas_inset_px"], 64)
            self.assertEqual(metrics["minimum_shape_gap_px"], 24)
            for shape in metrics["shapes"]:
                left, top, right, bottom = shape["bounds"]
                self.assertGreaterEqual(left, 64)
                self.assertGreaterEqual(top, 64)
                self.assertLessEqual(right, 1536 - 64 - 1)
                self.assertLessEqual(bottom, 1024 - 64 - 1)
                self.assertGreaterEqual(shape["raster_points"], 24)

            with Image.open(regenerated) as guide:
                self.assertEqual(guide.mode, "RGB")
                self.assertEqual(guide.size, (1536, 1024))
                self.assertEqual(
                    set(guide.get_flattened_data()),
                    {
                        (128, 128, 128),
                        (206, 74, 62),
                        (232, 151, 61),
                        (126, 93, 178),
                    },
                )

    def test_curve_that_reaches_edge_fails_preflight(self) -> None:
        control = json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
        control["shapes"][0]["knots"][0][0] = 20
        with self.assertRaisesRegex(MODULE.GuideError, "64px canvas inset"):
            MODULE.prepare(control)

    def test_touching_shapes_fail_detachment_contract(self) -> None:
        control = json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
        control["shapes"][2]["knots"] = control["shapes"][1]["knots"]
        with self.assertRaisesRegex(MODULE.GuideError, "overlap"):
            MODULE.prepare(control)

    def test_renderer_never_overwrites_an_existing_output(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sstory-g2-guide-", dir=REPO_ROOT
        ) as raw:
            output = Path(raw) / "guide.png"
            sentinel = b"keep-me"
            output.write_bytes(sentinel)
            with self.assertRaisesRegex(MODULE.GuideError, "refusing to overwrite"):
                MODULE.render(CONTROL_PATH, output)
            self.assertEqual(output.read_bytes(), sentinel)


if __name__ == "__main__":
    unittest.main()
