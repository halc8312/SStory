from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts/map-production"
sys.path.insert(0, str(SCRIPT_DIR))
MODULE_PATH = SCRIPT_DIR / "audit_style_candidate_k2_hybrid.py"
SPEC = importlib.util.spec_from_file_location("style_candidate_k2_hybrid_audit", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CandidateK2HybridAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.report_path = Path(cls._temporary.name) / "k2-audit.json"
        cls.report = MODULE.audit(report_path=cls.report_path)
        cls.written = json.loads(cls.report_path.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_approved_repository_candidate_passes_every_gate(self) -> None:
        self.assertEqual(self.written, self.report)
        self.assertEqual(self.report["status"], "passed")
        self.assertEqual(
            self.report["decision"], "automated-gates-passed-pending-root-vision"
        )
        self.assertEqual(self.report["failed_gates"], [])
        self.assertTrue(all(self.report["automated_gates"].values()))
        self.assertEqual(
            self.report["artifacts"]["final_review_candidate"]["sha256"],
            MODULE.APPROVED_CANDIDATE_SHA256,
        )
        self.assertTrue(self.report["identity"]["raw_final_byte_identical"])
        self.assertFalse(self.report["golden_accepted"])
        self.assertFalse(self.report["formal_qa"])

    def test_h4_raster_gates_are_reused_at_their_locked_thresholds(self) -> None:
        palette = self.report["palette_continuity_with_b1"]
        self.assertTrue(palette["passed"])
        self.assertEqual(
            palette["thresholds"],
            {
                "minimum_rgb_histogram_intersection": MODULE.h4.MIN_RGB_HISTOGRAM_INTERSECTION,
                "minimum_hsv_histogram_intersection": MODULE.h4.MIN_HSV_HISTOGRAM_INTERSECTION,
                "minimum_rgb_bhattacharyya": MODULE.h4.MIN_RGB_BHATTACHARYYA,
                "maximum_mean_channel_delta": MODULE.h4.MAX_MEAN_CHANNEL_DELTA,
            },
        )
        self.assertTrue(self.report["boundary"]["passed"])
        self.assertEqual(self.report["exact_repetition"]["duplicate_groups"], 0)
        self.assertTrue(self.report["downsample_readability"]["passed"])
        self.assertEqual(
            [item["thresholds"] for item in self.report["downsample_readability"]["scales"]],
            [MODULE.h4.DOWNSAMPLE_THRESHOLDS[0.5], MODULE.h4.DOWNSAMPLE_THRESHOLDS[0.25]],
        )

    def test_strict_geometry_gate_checks_both_directions_and_both_p95_values(self) -> None:
        geometry = self.report["guide_geometry_alignment"]
        self.assertTrue(geometry["passed"])
        self.assertGreaterEqual(geometry["stable_land_water_agreement"], 0.98)
        self.assertGreaterEqual(geometry["candidate_boundary_within_8px"], 0.95)
        self.assertGreaterEqual(geometry["guide_boundary_within_8px"], 0.95)
        self.assertLessEqual(geometry["candidate_boundary_distance_p95_px"], 8.0)
        self.assertLessEqual(geometry["guide_boundary_distance_p95_px"], 8.0)
        self.assertEqual(geometry["thresholds"], MODULE.GEOMETRY_THRESHOLDS)

        for field in (
            "candidate_boundary_distance_p95_px",
            "guide_boundary_distance_p95_px",
        ):
            failing = dict(geometry)
            failing[field] = 8.000001
            self.assertFalse(MODULE.strict_geometry_pass(failing), field)
        for field in (
            "candidate_boundary_within_8px",
            "guide_boundary_within_8px",
        ):
            failing = dict(geometry)
            failing[field] = 0.949999
            self.assertFalse(MODULE.strict_geometry_pass(failing), field)

    def test_pre_style_masks_have_zero_leakage_and_reproduce_final_pixels(self) -> None:
        local = self.report["local_pre_style_reconstruction"]
        self.assertTrue(local["passed"])
        self.assertEqual(local["outside_independent_allowed_union_pixels"], 0)
        self.assertTrue(local["union_matches_actual_pre_style_delta"])
        self.assertTrue(local["receipt_pre_style_metrics_match"])
        self.assertTrue(local["style_record_matches_receipt"])
        self.assertTrue(local["approved_final_reproduced_pixel_exactly"])
        self.assertEqual(local["approved_final_differing_pixels"], 0)
        self.assertEqual(local["approved_final_max_channel_delta"], 0)
        for record in local["persisted_mask_checks"].values():
            self.assertTrue(record["byte_exact_boolean_identity"])
            self.assertTrue(record["binary_0_255"])
        for record in local["component_permission_leakage"].values():
            self.assertTrue(record["passed"])
            self.assertEqual(record["outside_allowed_pixels"], 0)

    def test_field_highland_capital_contract_is_structural_not_vision_claim(self) -> None:
        contract = self.report["field_highland_capital_contract"]
        self.assertTrue(contract["passed"])
        self.assertIsNone(contract["semantic_claim"])
        self.assertEqual(contract["fields"]["canonical_parcel_count"], 8)
        self.assertEqual(contract["fields"]["nonempty_edited_parcel_count"], 8)
        self.assertTrue(all(value > 0 for value in contract["fields"]["edited_pixels_per_parcel"]))
        self.assertEqual(contract["highland"]["outside_canonical_permission_pixels"], 0)
        self.assertEqual(contract["capital"]["outside_canonical_permission_pixels"], 0)
        self.assertEqual(contract["capital"]["exact_gate_count"], 5)
        self.assertEqual(contract["capital"]["complete_interior_rings_added"], 0)
        self.assertEqual(contract["capital"]["uniform_radial_spokes_added"], 0)
        self.assertTrue(self.report["semantic_repetition_proxies_vs_h4"]["passed"])
        self.assertIsNone(
            self.report["semantic_repetition_proxies_vs_h4"]["semantic_claim"]
        )
        self.assertTrue(
            self.report["vision_handoff"]["automated_audit_is_not_golden_acceptance"]
        )

    def test_receipt_hash_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            tampered = Path(raw_directory) / "receipt.json"
            tampered.write_bytes(MODULE.DEFAULT_RECEIPT.read_bytes() + b"\n")
            with self.assertRaisesRegex(
                MODULE.K2AuditError, "provenance receipt SHA-256 mismatch"
            ):
                MODULE.audit(
                    receipt_path=tampered,
                    report_path=Path(raw_directory) / "report.json",
                )

    def test_audit_refuses_to_overwrite_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            occupied = Path(raw_directory) / "occupied.json"
            occupied.write_text("occupied", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.K2AuditError, "refusing to overwrite"):
                MODULE.audit(report_path=occupied)


if __name__ == "__main__":
    unittest.main()
