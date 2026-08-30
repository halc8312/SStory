from __future__ import annotations

import json
import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts/map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import audit_style_candidate_h9 as audit_h9  # noqa: E402
import render_candidate_h9_dense_flat_plan as h9  # noqa: E402


EXPECTED_REPORT_SHA256 = (
    "1bc01c99cf00be200ec78fd4a44a4824f86c92c134b848b0c202a811581ab60a"
)


class CandidateH9AutomatedAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._report_directory = tempfile.TemporaryDirectory()
        cls.report_path = Path(cls._report_directory.name) / "h9.json"
        cls.report = audit_h9.audit(report_path=cls.report_path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._report_directory.cleanup()

    def _audit_to(self, report_path: Path):
        return audit_h9.audit(report_path=report_path)

    def test_repository_candidate_records_required_golden_failures(self) -> None:
        report = self.report
        written = json.loads(self.report_path.read_text(encoding="utf-8"))

        self.assertEqual(written, report)
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["golden_eligible"])
        self.assertEqual(
            report["decision"],
            "automated-gates-failed-not-eligible-for-golden",
        )
        self.assertEqual(
            report["failed_gates"],
            [
                "palette_continuity_with_b1",
                "downsample_readability_proxy",
            ],
        )
        self.assertTrue(
            report["threshold_policy"][
                "legacy_h4_b1_golden_thresholds_unchanged"
            ]
        )
        self.assertTrue(
            report["threshold_policy"]["h5_non_regression_is_supplemental_only"]
        )

    def test_repository_report_regenerates_byte_identically(self) -> None:
        committed = audit_h9.DEFAULT_REPORT.read_bytes()
        self.assertEqual(
            hashlib.sha256(committed).hexdigest(), EXPECTED_REPORT_SHA256
        )
        self.assertEqual(self.report_path.read_bytes(), committed)

    def test_full_resolution_protection_and_semantics_are_exact(self) -> None:
        protection = self.report["full_resolution_protection"]
        self.assertTrue(protection["passed"])
        self.assertEqual(protection["canvas_pixels"], 1536 * 1024)
        self.assertEqual(
            protection["semantic_color_counts"], audit_h9.EXPECTED_MASK_COUNTS
        )
        self.assertEqual(
            protection["allowed_edit_pixels"], audit_h9.EXPECTED_ALLOWED_PIXELS
        )
        self.assertEqual(protection["changed_pixels"], 92_742)
        self.assertEqual(protection["protected_violation_pixels"], 0)
        self.assertEqual(protection["protected_pixel_equality_percent"], 100.0)
        self.assertEqual(
            protection["changed_pixels_by_zone"],
            {
                "protected": 0,
                "forest_gap_fill": 13_316,
                "port": 28_817,
                "city": 50_609,
            },
        )

    def test_city_port_forest_and_local_readability_gates_pass(self) -> None:
        urban = self.report["urban_plan_metrics"]
        self.assertTrue(urban["passed"])
        self.assertEqual(
            urban["city"]["independent_exact_fill_components_area_ge_2"], 344
        )
        self.assertEqual(
            urban["port"]["independent_exact_fill_components_area_ge_2"], 54
        )
        self.assertEqual(
            urban["city"]["generator_stats"]["city_flat_building_footprints"],
            354,
        )
        self.assertEqual(
            urban["port"]["generator_stats"]["port_flat_piers"], 8
        )

        forest = self.report["forest_metrics"]
        self.assertTrue(forest["passed"])
        self.assertEqual(forest["gap_fill_pixels"], 13_316)
        self.assertEqual(forest["component_count_reduction"], 278)
        self.assertGreaterEqual(
            forest["area_weighted_circularity_reduction_percent"], 20.0
        )
        self.assertGreaterEqual(
            forest["round_stamp_like_component_reduction_percent"], 20.0
        )

        local = self.report["edited_zone_readability_supplemental"]
        self.assertTrue(local["passed"])
        self.assertEqual(
            [zone["id"] for zone in local["zones"]],
            ["city", "port", "forest"],
        )
        self.assertTrue(all(zone["passed"] for zone in local["zones"]))

    def test_required_raster_gates_are_not_hidden_by_h5_non_regression(self) -> None:
        report = self.report
        palette = report["palette_continuity_b1_required"]
        self.assertFalse(palette["passed"])
        self.assertLess(
            palette["rgb_histogram_intersection"],
            palette["thresholds"]["minimum_rgb_histogram_intersection"],
        )
        self.assertTrue(report["palette_continuity_h5_supplemental"]["passed"])

        downsample = report["downsample_readability_required"]
        self.assertFalse(downsample["passed"])
        by_scale = {item["scale"]: item for item in downsample["scales"]}
        self.assertTrue(by_scale[0.5]["passed"])
        self.assertFalse(by_scale[0.25]["passed"])
        self.assertLess(
            by_scale[0.25]["macrocell_contrast_coverage"],
            by_scale[0.25]["thresholds"][
                "minimum_macrocell_contrast_coverage"
            ],
        )

    def test_atlas_receipt_is_partial_crop_only_and_honest(self) -> None:
        receipt = self.report["atlas_receipt"]
        self.assertTrue(receipt["passed"])
        self.assertTrue(
            receipt["raw_invocation_absences_recorded_without_inference"]
        )
        self.assertTrue(receipt["whole_image_explicitly_rejected"])
        self.assertEqual(len(receipt["accepted_crops"]), 6)
        self.assertEqual(len(receipt["rejected_zones"]), 3)
        self.assertTrue(all(item["passed"] for item in receipt["accepted_crops"]))
        self.assertTrue(all(item["passed"] for item in receipt["rejected_zones"]))

    def test_formal_provenance_and_contact_are_reconstructed(self) -> None:
        report = self.report
        self.assertTrue(report["formal_provenance"]["passed"])
        self.assertTrue(
            report["formal_provenance"][
                "self_review_has_no_acceptance_authority"
            ]
        )
        self.assertTrue(report["contact_sheet"]["passed"])
        self.assertTrue(
            report["contact_sheet"][
                "pixel_identical_to_deterministic_reconstruction"
            ]
        )
        self.assertEqual(report["contact_sheet"]["panel_count"], 10)

    def test_audit_refuses_overwrite_and_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            occupied = temporary_path / "occupied.json"
            occupied.write_text("occupied", encoding="utf-8")
            with self.assertRaisesRegex(
                audit_h9.H9AuditError, "refusing to overwrite"
            ):
                self._audit_to(occupied)

            tampered = temporary_path / "tampered.png"
            shutil.copyfile(audit_h9.DEFAULT_FINAL, tampered)
            with tampered.open("ab") as handle:
                handle.write(b"tampered")
            with self.assertRaisesRegex(
                audit_h9.H9AuditError, "final SHA-256 mismatch"
            ):
                audit_h9.audit(
                    final_path=tampered,
                    report_path=temporary_path / "tampered-report.json",
                )

    def test_formal_mode_rejects_a_custom_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                h9.H9RenderError,
                "--formal cannot be combined with a custom --output-dir",
            ):
                h9.render(output_dir=Path(temporary), formal=True)


if __name__ == "__main__":
    unittest.main()
