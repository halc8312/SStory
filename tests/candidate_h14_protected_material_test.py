from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import audit_style_candidate_h4 as h4  # noqa: E402
import render_candidate_h14_protected_material as h14  # noqa: E402


class CandidateH14ProtectedMaterialTest(unittest.TestCase):
    def test_render_is_deterministic_protected_and_uses_unchanged_h4_gates(self):
        h14.DEFAULT_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".candidate-h14-test-", dir=h14.DEFAULT_OUTPUT_ROOT
        ) as temporary:
            report = h14.render(output_dir=Path(temporary))
            written = json.loads(
                (Path(temporary) / h14.REPORT_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual(written, report)
            self.assertEqual(
                report["status"], "preview_rejected_automated_and_author_vision"
            )
            self.assertFalse(report["golden_reference"])
            self.assertEqual(
                report["full_resolution_forest_edit_protection"][
                    "protected_violation_pixels"
                ],
                0,
            )
            self.assertEqual(
                report["full_resolution_forest_edit_protection"][
                    "protected_pixel_equality_percent"
                ],
                100.0,
            )
            thresholds = report["unchanged_h4_absolute_thresholds"]
            self.assertEqual(
                thresholds["minimum_rgb_histogram_intersection"],
                h4.MIN_RGB_HISTOGRAM_INTERSECTION,
            )
            self.assertEqual(
                thresholds["minimum_hsv_histogram_intersection"],
                h4.MIN_HSV_HISTOGRAM_INTERSECTION,
            )
            self.assertEqual(
                thresholds["minimum_rgb_bhattacharyya"],
                h4.MIN_RGB_BHATTACHARYYA,
            )
            self.assertEqual(
                thresholds["maximum_mean_channel_delta"],
                h4.MAX_MEAN_CHANNEL_DELTA,
            )
            self.assertEqual(
                thresholds["minimum_25_percent_macrocoverage"],
                h4.DOWNSAMPLE_THRESHOLDS[0.25][
                    "minimum_macrocell_contrast_coverage"
                ],
            )
            self.assertTrue(
                report["geometry_contract"]["city_and_port_restored_byte_identical_to_h9"]
            )
            self.assertFalse(
                report["palette_calibration"]["h11_or_b1_coordinate_sampling_used"]
            )
            for output_name in (
                "master",
                "semantic_mask",
                "overview",
                "native_review",
                "zoom_200_review",
                "zoom_400_review",
                "contact_sheet",
            ):
                self.assertIn(output_name, report["outputs"])

    def test_failed_gates_are_recorded_without_lowering_thresholds(self):
        h14.DEFAULT_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".candidate-h14-gates-", dir=h14.DEFAULT_OUTPUT_ROOT
        ) as temporary:
            report = h14.render(output_dir=Path(temporary))
            gate_status = report["automated_gate_status"]
            self.assertFalse(gate_status["palette_continuity_b1"])
            self.assertFalse(gate_status["downsample_readability"])
            self.assertFalse(gate_status["component_circularity_reduction"])
            self.assertTrue(gate_status["boundary"])
            self.assertTrue(gate_status["exact_repetition"])
            self.assertTrue(gate_status["forest_edit_full_resolution_protection"])
            self.assertTrue(gate_status["round_stamp_component_reduction"])
            shape = report["forest_shape_metrics"]
            self.assertGreaterEqual(
                shape["round_stamp_like_component_reduction_percent"], 65.0
            )
            palette = report["automated_metrics"]["palette_continuity_b1"]
            self.assertLess(
                palette["rgb_histogram_intersection"],
                h4.MIN_RGB_HISTOGRAM_INTERSECTION,
            )
            self.assertLess(
                palette["hsv_histogram_intersection"],
                h4.MIN_HSV_HISTOGRAM_INTERSECTION,
            )
            self.assertLessEqual(
                palette["maximum_mean_channel_delta"], h4.MAX_MEAN_CHANNEL_DELTA
            )
            readability = report["automated_metrics"]["downsample_readability"]
            by_scale = {item["scale"]: item for item in readability["scales"]}
            self.assertLess(
                by_scale[0.25]["macrocell_contrast_coverage"],
                h4.DOWNSAMPLE_THRESHOLDS[0.25][
                    "minimum_macrocell_contrast_coverage"
                ],
            )
            review = report["self_vision_review"]
            self.assertTrue(review["immediate_failure_detected"])
            self.assertEqual(
                review["decision"],
                "do_not_promote_or_request_independent_acceptance_review",
            )

    def test_refuses_overwrite_and_outside_preview_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(h14.H14RenderError, "must stay under"):
                h14.render(output_dir=Path(temporary))
        h14.DEFAULT_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".candidate-h14-overwrite-", dir=h14.DEFAULT_OUTPUT_ROOT
        ) as temporary:
            output = Path(temporary)
            (output / h14.MASTER_NAME).write_bytes(b"occupied")
            with self.assertRaisesRegex(h14.H14RenderError, "refusing to overwrite"):
                h14.render(output_dir=output)


if __name__ == "__main__":
    unittest.main()
