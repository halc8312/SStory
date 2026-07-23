import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageOps


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import render_candidate_h8_localized_plan_edit as h8  # noqa: E402


class CandidateH8LocalizedPlanEditTest(unittest.TestCase):
    def test_render_is_localized_and_emits_complete_review_evidence(self):
        h8.DEFAULT_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".candidate-h8-test-", dir=h8.DEFAULT_OUTPUT_ROOT
        ) as temporary:
            output_dir = Path(temporary)
            report = h8.render(output_dir=output_dir)
            master_path = output_dir / h8.MASTER_NAME
            mask_path = output_dir / h8.MASK_NAME
            contact_path = output_dir / h8.CONTACT_NAME
            provenance_path = output_dir / h8.REPORT_NAME

            self.assertEqual(report["protected_pixel_equality"]["protected_violation_pixels"], 0)
            self.assertEqual(report["protected_pixel_equality"]["protected_pixel_equality_percent"], 100.0)
            self.assertFalse(report["constraints"]["histogram_or_rank_transfer_used"])
            self.assertFalse(report["constraints"]["full_image_blur_used"])
            self.assertEqual(json.loads(provenance_path.read_text(encoding="utf-8")), report)

            with (
                Image.open(h8.DEFAULT_H5).convert("RGB") as source,
                Image.open(master_path).convert("RGB") as master,
                Image.open(mask_path).convert("RGB") as semantic,
                Image.open(contact_path) as contact,
            ):
                self.assertEqual(master.size, h8.CANVAS)
                self.assertEqual(contact.size, (1176, 768))
                allowed = semantic.convert("L").point(lambda value: 255 if value else 0)
                protected = ImageOps.invert(allowed)
                difference = ImageChops.difference(source, master).convert("L")
                violation = ImageChops.multiply(difference, protected)
                self.assertIsNone(violation.getbbox())
                self.assertIsNotNone(difference.getbbox())


if __name__ == "__main__":
    unittest.main()
