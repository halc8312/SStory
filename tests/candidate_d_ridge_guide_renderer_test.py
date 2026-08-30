import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
MODULE_PATH = SCRIPT_DIR / "render_candidate_d_ridge_guide.py"
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location("render_candidate_d_ridge_guide", MODULE_PATH)
ridge_guide = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ridge_guide)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CandidateDRidgeGuideRendererTests(unittest.TestCase):
    def test_spec_has_two_fields_of_five_disconnected_short_ridges(self):
        spec = ridge_guide.load_and_validate_spec()

        self.assertEqual(spec["canvas"], {"width": 1536, "height": 1024})
        self.assertEqual(
            [region["id"] for region in spec["regions"]],
            ["north_east_range", "south_east_range"],
        )
        for region in spec["regions"]:
            self.assertEqual(len(region["ridge_chains"]), 5)
            for ridge in region["ridge_chains"]:
                self.assertEqual(
                    ridge["path_role"], "independent-wide-short-ridge-centerline"
                )
                self.assertEqual(ridge["width_px"], 40)
                self.assertEqual(len(ridge["hatches"]), 1)
                self.assertEqual(
                    ridge["hatches"][0]["path_role"],
                    "detached-one-sided-short-hatch",
                )
        self.assertFalse(spec["rendering"]["center_line_drawn"])
        self.assertEqual(
            [road["source_pixels_path"] for road in spec["road_avoidance"]["corridors"]],
            [
                [[930, 505], [1050, 515], [1180, 540], [1270, 535], [1370, 490], [1535, 450]],
                [[910, 558], [1000, 610], [1090, 666], [1180, 725], [1270, 785], [1360, 840], [1450, 892], [1535, 936]],
            ],
        )

    def test_render_is_deterministic_exact_size_and_contains_visible_cyan_guide(self):
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = Path(first_dir) / "ridge-guide.png"
            second = Path(second_dir) / "ridge-guide.png"
            ridge_guide.render_guide(output_path=first)
            ridge_guide.render_guide(output_path=second)

            self.assertEqual(sha256(first), sha256(second))
            with Image.open(first) as image:
                self.assertEqual(image.size, (1536, 1024))
                self.assertEqual(image.mode, "RGB")
                pixels = image.load()
                cyan_samples = [(945, 122), (1030, 252), (806, 974), (1181, 875)]
                for point in cyan_samples:
                    red, green, blue = pixels[point[0], point[1]]
                    self.assertLess(red, 130)
                    self.assertGreater(green, 185)
                    self.assertGreater(blue, 195)
                    self.assertFalse(red > 240 and green > 240 and blue > 240)

    def test_renderer_refuses_overwrite_and_road_crossing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "owned.png"
            target.write_bytes(b"user-owned")
            with self.assertRaisesRegex(ridge_guide.RidgeGuideError, "refusing to overwrite"):
                ridge_guide.render_guide(output_path=target)
            self.assertEqual(target.read_bytes(), b"user-owned")

            mutated_path = Path(temp_dir) / "invalid.json"
            spec = json.loads(ridge_guide.DEFAULT_SPEC.read_text(encoding="utf-8"))
            spec["regions"][0]["ridge_chains"][0]["source_pixels_path"] = [
                [1000, 490],
                [1100, 520],
                [1200, 540],
            ]
            spec["regions"][0]["ridge_chains"][0]["hatches"] = [
                {
                    "path_role": "detached-one-sided-short-hatch",
                    "source_pixels_path": [[1094, 544], [1092, 558]],
                }
            ]
            mutated_path.write_text(json.dumps(spec), encoding="utf-8")
            with self.assertRaisesRegex(ridge_guide.RidgeGuideError, "road clearance"):
                ridge_guide.load_and_validate_spec(mutated_path)


if __name__ == "__main__":
    unittest.main()
