from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts/map-production"
sys.path.insert(0, str(SCRIPT_DIR))
MODULE_PATH = SCRIPT_DIR / "audit_style_candidate_h17.py"
SPEC = importlib.util.spec_from_file_location("candidate_h17_audit", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CandidateH17AutomatedAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary_directory.name)
        cls.report_path = cls.root / "h17.json"
        cls.contact_path = cls.root / "h17-contact.png"
        cls.report = MODULE.audit(
            report_path=cls.report_path,
            contact_path=cls.contact_path,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary_directory.cleanup()

    def test_unchanged_h4_gates_preserve_the_failure(self) -> None:
        self.assertEqual(self.report["status"], "failed")
        self.assertEqual(
            self.report["failed_gates"],
            [
                "palette_continuity_with_b1",
                "downsample_readability_proxy",
            ],
        )
        palette = self.report["palette_continuity"]
        self.assertEqual(palette["rgb_histogram_intersection"], 0.626617)
        self.assertEqual(palette["hsv_histogram_intersection"], 0.497589)
        self.assertEqual(palette["rgb_bhattacharyya"], 0.852648)
        self.assertEqual(palette["maximum_mean_channel_delta"], 11.07697)
        scales = {
            item["scale"]: item
            for item in self.report["downsample_readability"]["scales"]
        }
        self.assertFalse(scales[0.5]["passed"])
        self.assertFalse(scales[0.25]["passed"])
        self.assertEqual(scales[0.25]["macrocell_contrast_coverage"], 0.807292)

    def test_review_candidate_is_byte_identical_but_unaccepted(self) -> None:
        self.assertTrue(self.report["identity"]["raw_final_byte_identical"])
        final = self.report["artifacts"]["final_review_candidate"]
        self.assertTrue(final["review_only"])
        self.assertFalse(final["accepted"])
        self.assertFalse(self.report["golden_accepted"])
        self.assertFalse(self.report["manifest_mutation"])
        self.assertEqual(
            final["sha256"],
            "5eeee266f37ab418a4b136a6d66e67ccfe9268fa04a18cf7e96323e9b7d1506f",
        )

    def test_composition_and_repetition_proxies_do_not_claim_vision(self) -> None:
        composition = self.report["composition_preservation"]
        self.assertTrue(composition["passed"])
        self.assertEqual(
            composition["minimum_region_quarter_scale_ssim"], 0.642054
        )
        self.assertEqual(
            composition["feature_alignment"]["median_inlier_displacement_px"],
            0.607207,
        )
        self.assertEqual(composition["edge_alignment"]["f1"], 0.831552)
        repetition = self.report["semantic_repetition_proxies"]
        self.assertTrue(repetition["passed"])
        self.assertIsNone(repetition["semantic_claim"])
        handoff = self.report["vision_handoff"]
        self.assertEqual(handoff["status"], "not-performed")
        self.assertFalse(handoff["vision_report_created"])
        self.assertTrue(handoff["automated_audit_is_not_vision"])

    def test_receipt_preserves_unknown_metadata_and_h4_only_input(self) -> None:
        receipt = json.loads(MODULE.RECEIPT.read_text(encoding="utf-8"))
        limitations = receipt["provenance_limitations"]
        self.assertEqual(limitations["model"], "unknown")
        self.assertEqual(limitations["model_snapshot"], "unavailable")
        self.assertEqual(limitations["generation_id"], "unavailable")
        self.assertIsNone(limitations["generation_timestamp_utc"])
        self.assertEqual(len(receipt["inputs"]), 1)
        self.assertEqual(
            receipt["inputs"][0]["path"],
            "world/map-production/candidates/"
            "style-candidate-h-v4-plan-view-golden-board.png",
        )
        paths = [receipt["prompt"]["path"], receipt["output"]["path"]]
        paths.extend(item["path"] for item in receipt["inputs"])
        for value in paths:
            pure = PurePosixPath(value)
            self.assertFalse(pure.is_absolute())
            self.assertNotIn("\\", value)
            self.assertNotIn(":", value)
            self.assertNotIn("..", pure.parts)

    def test_contact_sheet_contains_all_requested_inspection_scales(self) -> None:
        self.assertTrue(self.contact_path.is_file())
        with Image.open(self.contact_path) as image:
            self.assertEqual(image.mode, "RGB")
            self.assertGreaterEqual(image.width, 3800)
            self.assertGreaterEqual(image.height, 5900)
        artifact = self.report["artifacts"]["local_contact_sheet"]
        self.assertFalse(artifact["repository_artifact"])
        self.assertFalse(artifact["vision_report"])

    def test_materialization_never_overwrites_nonidentical_file(self) -> None:
        changed = self.root / "changed.png"
        changed.write_bytes(b"not the candidate")
        with self.assertRaisesRegex(MODULE.H17AuditError, "non-identical"):
            MODULE.materialize_review_candidate(MODULE.RAW, changed)
        self.assertEqual(changed.read_bytes(), b"not the candidate")

    def test_committed_evidence_matches_locked_artifacts_and_outcome(self) -> None:
        committed = json.loads(MODULE.REPORT.read_text(encoding="utf-8"))
        self.assertEqual(
            committed["identity"]["locked_sha256"], MODULE.EXPECTED_SHA256
        )
        self.assertEqual(committed["automated_gates"], self.report["automated_gates"])
        self.assertEqual(committed["failed_gates"], self.report["failed_gates"])
        self.assertEqual(
            committed["artifacts"]["final_review_candidate"]["sha256"],
            self.report["artifacts"]["final_review_candidate"]["sha256"],
        )


if __name__ == "__main__":
    unittest.main()
