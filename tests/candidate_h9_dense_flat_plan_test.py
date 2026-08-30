import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageOps


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import render_candidate_h9_dense_flat_plan as h9  # noqa: E402


class CandidateH9DenseFlatPlanTest(unittest.TestCase):
    def test_render_is_dense_flat_and_protected(self):
        h9.DEFAULT_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".candidate-h9-test-", dir=h9.DEFAULT_OUTPUT_ROOT
        ) as temporary:
            output_dir = Path(temporary)
            report = h9.render(output_dir=output_dir)
            master_path = output_dir / h9.MASTER_NAME
            mask_path = output_dir / h9.MASK_NAME
            provenance_path = output_dir / h9.REPORT_NAME

            self.assertEqual(
                report["protected_pixel_equality"]["protected_violation_pixels"], 0
            )
            self.assertEqual(
                report["protected_pixel_equality"][
                    "protected_pixel_equality_percent"
                ],
                100.0,
            )
            stats = report["render_stats"]
            self.assertGreaterEqual(stats["city_flat_building_footprints"], 350)
            self.assertLessEqual(stats["city_flat_building_footprints"], 550)
            self.assertGreaterEqual(stats["port_flat_building_footprints"], 45)
            self.assertLessEqual(stats["port_flat_building_footprints"], 80)
            self.assertGreaterEqual(stats["port_flat_piers"], 6)
            self.assertLessEqual(stats["port_flat_piers"], 10)
            canopy = report["canopy_component_audit"]
            self.assertGreater(canopy["component_count_reduction"], 0)
            self.assertGreater(canopy["area_weighted_circularity_reduction_percent"], 0)
            self.assertGreater(canopy["round_stamp_like_component_reduction_percent"], 0)
            self.assertEqual(
                json.loads(provenance_path.read_text(encoding="utf-8")), report
            )

            with (
                Image.open(h9.DEFAULT_H5).convert("RGB") as source,
                Image.open(master_path).convert("RGB") as master,
                Image.open(mask_path).convert("RGB") as semantic,
            ):
                allowed = semantic.convert("L").point(lambda value: 255 if value else 0)
                protected = ImageOps.invert(allowed)
                allowed_pixels = sum(allowed.histogram()[1:])
                protected_pixels = sum(protected.histogram()[1:])
                changed_pixels = 0
                violation_pixels = 0
                allowed_values = allowed.tobytes()
                for source_pixel, master_pixel, is_allowed in zip(
                    source.get_flattened_data(),
                    master.get_flattened_data(),
                    allowed_values,
                ):
                    if source_pixel == master_pixel:
                        continue
                    changed_pixels += 1
                    if not is_allowed:
                        violation_pixels += 1
                self.assertEqual(
                    report["semantic_mask"]["allowed_edit_pixels"], allowed_pixels
                )
                self.assertEqual(
                    report["protected_pixel_equality"]["protected_pixels"],
                    protected_pixels,
                )
                self.assertEqual(
                    report["protected_pixel_equality"]["changed_pixels"],
                    changed_pixels,
                )
                self.assertEqual(
                    allowed_pixels + protected_pixels, h9.CANVAS[0] * h9.CANVAS[1]
                )
                self.assertEqual(violation_pixels, 0)
                self.assertGreater(changed_pixels, 0)


if __name__ == "__main__":
    unittest.main()
