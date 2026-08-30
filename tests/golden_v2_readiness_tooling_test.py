from __future__ import annotations

import sys
import unittest
import uuid
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts/map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import create_golden_v2_review_template as review_template  # noqa: E402
import emit_style_candidate_k3_golden_v2 as emitter  # noqa: E402
import generate_style_candidate_k3_golden_v2_controls as controls  # noqa: E402
import promote_style_candidate_k3_golden_v2 as promotion  # noqa: E402
from production_common import load_json  # noqa: E402
from validate_manifest import schema_errors  # noqa: E402


@dataclass(frozen=True)
class PacketStub:
    relative: str
    sha256: str


class GoldenV2ReadinessToolingTest(unittest.TestCase):
    def test_tracked_audit_controls_exactly_rederive_v19_pixel_claims(self) -> None:
        report = controls.verify_controls()

        self.assertEqual(report["status"], "verified")
        self.assertEqual(
            report["candidate_sha256"],
            "f2cb6e72ad1fb6e46a8ef0ed881418fd2f7d465edc514113d498714d4d94820a",
        )
        self.assertEqual(report["metrics"], controls.EXPECTED_METRICS)
        self.assertEqual(
            report["audit_control_sha256"],
            controls.EXPECTED_AUDIT_CONTROL_SHA256,
        )
        expected_files = {
            controls.AUDIT_CONTROL.relative_to(REPO_ROOT).as_posix(): (
                controls.EXPECTED_AUDIT_CONTROL_SHA256
            ),
            **{
                controls.MASK_PATHS[name].relative_to(REPO_ROOT).as_posix(): digest
                for name, digest in controls.EXPECTED_MASK_PNG_SHA256.items()
            },
        }
        self.assertEqual(report["files"], expected_files)

    def test_reproduction_inventory_is_fixed_and_validates(self) -> None:
        config = emitter._load_fixed_config(emitter.DEFAULT_CONFIG)
        reproduction = emitter._reproduction(emitter.DEFAULT_CONFIG, config)
        validated = promotion._validate_reproduction_contract(
            {"reproduction": reproduction}
        )

        self.assertEqual(reproduction["seed"], config["seed"])
        self.assertEqual(
            [binding.relative for binding in validated["donors"]], config["donors"]
        )
        self.assertEqual(
            [binding.relative for binding in validated["controls"]], config["controls"]
        )
        self.assertEqual(
            set(validated["pixel_audit"]["masks"]),
            set(promotion.pixel_auditor.MASK_NAMES),
        )

    def test_emitter_refuses_non_temp_output_before_rendering(self) -> None:
        with self.assertRaisesRegex(
            emitter.GoldenV2EmissionError, "must stay under"
        ):
            emitter.emit(REPO_ROOT / "world/map-production/not-temp-golden-v2")

    def test_real_temp_emission_and_root_draft_remain_unaccepted(self) -> None:
        parent = REPO_ROOT / "tmp/map-production/test-temp"
        parent.mkdir(parents=True, exist_ok=True)
        output_root = parent / f"golden-v2-emitter-{uuid.uuid4().hex}"
        draft_path = output_root / "root-review-draft.json"
        try:
            result = emitter.emit(output_root)
            document = emitter._self_validate(output_root / "emission.json")
            draft_result = review_template.create_root_template(
                emission_path=output_root / "emission.json",
                reviewer="template-test-only",
                output=draft_path,
            )
            draft = load_json(draft_path)

            self.assertEqual(result["status"], promotion.EMISSION_STATUS)
            self.assertTrue(result["temporary_review_only"])
            self.assertFalse(result["root_review_created"])
            self.assertEqual(result["blind_reviews_created"], 0)
            self.assertEqual(
                document["candidate"]["sha256"],
                "f2cb6e72ad1fb6e46a8ef0ed881418fd2f7d465edc514113d498714d4d94820a",
            )
            self.assertEqual(
                document["determinism"]["replay"]["sha256"],
                document["candidate"]["sha256"],
            )
            self.assertEqual(document["metrics"], controls.EXPECTED_METRICS)
            self.assertEqual(document["geometry"], controls.EXPECTED_GEOMETRY)
            self.assertEqual(document["identity"], controls.EXPECTED_IDENTITY)
            self.assertEqual(draft_result["status"], "draft")
            self.assertEqual(draft["decision"], "pending")
            self.assertFalse(draft["authorizes_blind_review"])
            self.assertIsNone(draft["total_score"])
            self.assertTrue(
                all(item["complete"] is False for item in draft["review_views"])
            )
            self.assertTrue(
                all(
                    item["detected"] is None and item["evidence"] == ""
                    for item in draft["immediate_failures"]
                )
            )
        finally:
            draft_path.unlink(missing_ok=True)
            emitter._cleanup_created_root(output_root, expected_parent=parent)

    def test_blind_template_is_schema_valid_but_contains_no_review_claim(self) -> None:
        packet = PacketStub(
            relative=(
                "world/map-production/qa/blind-packets/phase4-k3-v2/"
                + "1" * 64
                + ".json"
            ),
            sha256="1" * 64,
        )
        report = review_template.build_blind_report(
            packet=packet, role="a", reviewer_id=" Reviewer Example "
        )

        errors = schema_errors(report, load_json(promotion.QA_REPORT_SCHEMA))
        self.assertEqual(errors, [])
        self.assertEqual(report["status"], "draft")
        self.assertEqual(report["decision"], "pending")
        self.assertIsNone(report["total_score"])
        self.assertEqual(len(report["review_views"]), 10)
        self.assertTrue(
            all(
                item["complete"] is False
                and item["evidence"] == ""
                and item["notes"] == ""
                for item in report["review_views"]
            )
        )
        self.assertEqual(
            tuple(item["id"] for item in report["immediate_failures"]),
            promotion.PHASE4_IMMEDIATE_FAILURE_IDS,
        )
        self.assertTrue(
            all(
                item["detected"] is None and item["evidence"] == ""
                for item in report["immediate_failures"]
            )
        )
        self.assertTrue(all(item["score"] is None for item in report["scores"]))

    def test_root_failure_template_uses_exact_phase4_ids(self) -> None:
        failures = review_template._failure_drafts()
        self.assertEqual(
            tuple(item["id"] for item in failures),
            promotion.PHASE4_IMMEDIATE_FAILURE_IDS,
        )
        self.assertTrue(
            all(
                item == {"id": item["id"], "detected": None, "evidence": ""}
                for item in failures
            )
        )


if __name__ == "__main__":
    unittest.main()
