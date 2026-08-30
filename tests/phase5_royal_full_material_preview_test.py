import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import audit_phase5_royal_full_material_preview as audit  # noqa: E402
import render_phase5_reviewed_master as renderer  # noqa: E402


class Phase5RoyalFullMaterialPreviewTests(unittest.TestCase):
    def test_contact_source_boxes_cover_all_required_scales_without_overflow(self):
        image = Image.new("RGB", (2294, 1421))
        try:
            boxes = {
                scale: audit._source_box(image, (850, 670), scale, (768, 480))
                for scale in (0.25, 0.5, 1.0, 2.0, 4.0)
            }
            self.assertEqual(boxes[0.25], (0, 0, 2294, 1421))
            for box in boxes.values():
                self.assertGreaterEqual(box[0], 0)
                self.assertGreaterEqual(box[1], 0)
                self.assertLessEqual(box[2], image.width)
                self.assertLessEqual(box[3], image.height)
                self.assertGreater(box[2], box[0])
                self.assertGreater(box[3], box[1])
        finally:
            image.close()

    def test_semantic_autocorrelation_rejects_a_repeated_patch_field(self):
        rows, columns = np.indices((64, 64))
        tile = ((columns // 8 + rows // 16) % 4) * 42 + 54
        repeated = np.tile(tile, (5, 5)).astype(np.uint8)
        image = Image.fromarray(repeated).convert("RGB")
        mask = Image.new("L", image.size, 255)
        try:
            record = audit.semantic_far_patch_autocorrelation(
                image,
                mask,
                "synthetic-repeat",
            )
            self.assertTrue(record["applicable"])
            self.assertFalse(record["passed"])
            self.assertGreaterEqual(
                record["p99_best_far_patch_normalized_correlation"], 0.99
            )
        finally:
            mask.close()
            image.close()

    def test_full_spatial_mode_is_fail_closed_to_royal_single_sheet(self):
        with self.assertRaisesRegex(
            renderer.ReviewedMasterError,
            "Royal-only prototype",
        ):
            renderer.write_reviewed_master(
                sheet_id="sheet_region_soaring_mountains_region",
                material_transfer_mode=renderer.FULL_SPATIAL_MATERIAL_MODE,
            )
        with self.assertRaisesRegex(
            renderer.ReviewedMasterError,
            "Royal-only",
        ):
            renderer.write_generation_batch(
                material_transfer_mode=renderer.FULL_SPATIAL_MATERIAL_MODE,
            )


if __name__ == "__main__":
    unittest.main()
