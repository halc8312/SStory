from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from unittest import mock

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import build_phase5_assets as phase5  # noqa: E402
import create_qa_report  # noqa: E402
import promote_style_candidate_k3_golden_v3 as promotion  # noqa: E402


VIEW_IDS = ("native", "full25", "full50", "highland200", "highland400")
VIEW_DEFINITIONS = {
    "native": (None, (1536, 1024)),
    "full25": (None, (384, 256)),
    "full50": (None, (768, 512)),
    "highland200": ((930, 0, 1536, 560), (1212, 1120)),
    "highland400": ((930, 0, 1536, 560), (2424, 2240)),
}
EXTRA_REVIEW_VIEW_IDS = (
    "control-overlay",
    "parent-zoom",
    "neighbor-seams",
    "desktop",
    "mobile",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


class PromotionV3Fixture:
    """Candidate-blind synthetic evidence graph; no production candidate is read."""

    def __init__(self) -> None:
        self.generation_contract_id = promotion.FOUR_CANDIDATE_V1
        self.candidate_id = "F094-M148"
        self._temps = [
            tempfile.TemporaryDirectory(
                prefix=".golden-v3-promotion-test-",
                dir=REPO_ROOT / "world" / "map-production" / parent,
            )
            for parent in ("qa", "candidates", "prompts")
        ]
        self.evidence_root = Path(self._temps[0].name)
        self.candidate_root = Path(self._temps[1].name)
        self.prompt_root = Path(self._temps[2].name)
        self.manifest = self.evidence_root / "production-manifest.json"
        self.candidate = self.evidence_root / "synthetic-candidate.png"
        with Image.new("RGB", (1536, 1024), color=(71, 103, 149)) as image:
            image.save(self.candidate, format="PNG", compress_level=9)
        self.candidate_sha256 = digest(self.candidate)
        self.paths = promotion.PromotionPaths(
            manifest=self.manifest,
            raw=self.candidate_root / "golden-v3-raw.png",
            master=self.candidate_root / "golden-v3-master.png",
            receipt=self.prompt_root / "golden-v3-receipt.json",
        )
        self._write_json(
            self.manifest,
            {
                "schema_version": "1.0.0",
                "project_id": "golden-v3-promotion-test",
                "map_id": "eternal-arcadia",
                "coordinate_system": "EA-WORLD-1",
                "jobs": [],
            },
        )

        self.strict_report = {
            "schema_version": "1.0.0",
            "id": "style-candidate-k-v3-golden-v3-strict-independent-pixel-audit",
            "algorithm": "sstory-k3-golden-v3-strict-independent-pixel-audit-v1",
            "authority_sha256": promotion.strict_audit.EXPECTED_AUTHORITY_SHA256,
            "runtime_profile": "linux-ci-opencv-python-headless-4.13.0.92",
            "candidate": {
                "binding": "runtime-only",
                "sha256": self.candidate_sha256,
                "bytes": self.candidate.stat().st_size,
                "path_recorded": False,
            },
            "gates": {"synthetic-fixture-gate": True},
            "failed_gates": [],
            "passed": True,
            "promotion_or_golden_designation_performed": False,
        }
        self.strict_report_path = self.evidence_root / "strict-report.json"
        self.strict_report_path.write_bytes(
            promotion.strict_audit.canonical_json(self.strict_report)
        )

        authority = promotion.load_authority()
        derivation_authority = json.loads(
            authority.derivation_authority.data.decode("utf-8")
        )
        sealed_candidates = []
        for index, record in enumerate(
            derivation_authority["candidates"]["records"]
        ):
            selected = record["candidate_id"] == "F094-M148"
            sealed_candidates.append(
                {
                    "candidate_id": record["candidate_id"],
                    "path": record["output_path"],
                    "sha256": (
                        self.candidate_sha256
                        if selected
                        else hashlib.sha256(
                            f"synthetic-nonselected-{index}".encode("ascii")
                        ).hexdigest()
                    ),
                    "bytes": self.candidate.stat().st_size if selected else index + 1,
                }
            )
        seal_profiles = (
            "windows-ci-opencv-python-headless-4.13.0.92",
            "linux-ci-opencv-python-headless-4.13.0.92",
        )
        self.seal_paths = tuple(
            self.evidence_root / f"synthetic-{index}-seal.json"
            for index in range(len(seal_profiles))
        )
        for path, profile in zip(self.seal_paths, seal_profiles, strict=True):
            path.write_bytes(
                promotion.derivation.canonical_output_seal_json(
                    {
                        "schema_id": "sstory.k3.golden-v3.four-candidate-output-seal.v1",
                        "authority_sha256": promotion.derivation.AUTHORITY_SHA256,
                        "statistics_firewall_sha256": derivation_authority["derivation"][
                            "v19_statistical_authority"
                        ]["future_artifact_sha256"],
                        "runtime_profile_id": profile,
                        "candidate_count": 4,
                        "candidates": copy.deepcopy(sealed_candidates),
                    }
                )
            )
        self.seal_bindings = tuple(
            promotion._bind(path, label=f"synthetic seal {index}")
            for index, path in enumerate(self.seal_paths)
        )
        self.seal_summaries = [
            {
                "runtime_profile_id": profile,
                "sha256": binding.sha256,
            }
            for profile, binding in zip(seal_profiles, self.seal_bindings, strict=True)
        ]
        for summary, binding in zip(
            self.seal_summaries, self.seal_bindings, strict=True
        ):
            summary["payload_utf8"] = binding.data.decode("utf-8")

        view_root = self.evidence_root / "views"
        view_root.mkdir()
        self.views: list[Path] = []
        with Image.open(self.candidate) as source_image:
            source_image.load()
            for view_id in VIEW_IDS:
                crop, size = VIEW_DEFINITIONS[view_id]
                working = (
                    source_image.copy()
                    if crop is None
                    else source_image.crop(crop)
                )
                try:
                    rendered = working.resize(size, Image.Resampling.LANCZOS)
                    try:
                        path = view_root / f"{view_id}.png"
                        rendered.save(path, format="PNG", compress_level=9)
                    finally:
                        rendered.close()
                finally:
                    working.close()
                self.views.append(path)
        self.packet = {
            "schema_version": "1.0.0",
            "id": "sstory-k3-golden-v3-anonymous-five-view-packet-v1",
            "job_id": promotion.JOB_ID,
            "candidate_sha256": self.candidate_sha256,
            "candidate_bytes": self.candidate.stat().st_size,
            "view_order": list(VIEW_IDS),
            "views": [
                {"id": view_id, "path": relative(path), "sha256": digest(path)}
                for view_id, path in zip(VIEW_IDS, self.views, strict=True)
            ],
            "created_at": "2000-01-01T00:00:00Z",
        }
        self.packet_path = self.evidence_root / "blind-packet.json"
        self._write_json(self.packet_path, self.packet)

        self.root_review_path = self.evidence_root / "root-review.json"
        self.review_paths = (
            self.evidence_root / "review-a.json",
            self.evidence_root / "review-b.json",
        )
        self.reviews = {
            "root": self._build_review(
                reviewer=(
                    "golden-v3-root-vision-authorization/Root Vision Authority"
                ),
                golden=False,
                review_mode="self",
                created_at="2000-01-01T00:10:00Z",
            ),
            "a": self._build_review(
                reviewer="independent-vision-review-a/Reviewer Alpha",
                golden=True,
                review_mode="blind-independent",
                created_at="2000-01-01T00:20:00Z",
            ),
            "b": self._build_review(
                reviewer="independent-vision-review-b/Reviewer Beta",
                golden=True,
                review_mode="blind-independent",
                created_at="2000-01-01T00:21:00Z",
            ),
        }
        self.persist_reviews()

    @staticmethod
    def _write_json(path: Path, document: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode(
                "utf-8"
            )
        )

    def _build_review(
        self,
        *,
        reviewer: str,
        golden: bool,
        review_mode: str,
        created_at: str,
    ) -> dict[str, object]:
        report = create_qa_report.build_report(
            promotion.JOB_ID,
            relative(self.paths.master),
            reviewer=reviewer,
            golden=golden,
            threshold=94,
            image_sha256=self.candidate_sha256,
            review_mode=review_mode,
            vision_bundle_receipt={
                "path": relative(self.packet_path),
                "sha256": digest(self.packet_path),
            },
        )
        report["vision_bundle"]["reviewer_confirmed_exact_five"] = True
        report.update(
            {
                "created_at": created_at,
                "status": "complete",
                "decision": "accepted",
                "summary": "Synthetic candidate-blind review fixture.",
            }
        )
        report["review_views"] = [
            {
                "id": view_id,
                "label": view_id,
                "complete": True,
                "evidence": "synthetic fixture inspection",
                "notes": "candidate-blind unit test",
            }
            for view_id in (*VIEW_IDS, *EXTRA_REVIEW_VIEW_IDS)
        ]
        authority = promotion.load_authority().document
        report["immediate_failures"] = [
            {
                "id": failure_id,
                "label": failure_id,
                "detected": False,
                "evidence": "not detected in synthetic fixture",
            }
            for failure_id in authority["review_contract"]["immediate_failure_ids"]
        ]
        for score in report["scores"]:
            score["score"] = score["maximum"]
            score["notes"] = "synthetic fixture satisfies the axis"
        report["total_score"] = 100
        return report

    def persist_reviews(self) -> None:
        self._write_json(self.root_review_path, self.reviews["root"])
        self._write_json(self.review_paths[0], self.reviews["a"])
        self._write_json(self.review_paths[1], self.reviews["b"])

    def promotion_patches(self) -> ExitStack:
        stack = ExitStack()
        stack.enter_context(
            mock.patch.object(
                promotion,
                "_validate_generation_seals",
                return_value=(self.seal_bindings, copy.deepcopy(self.seal_summaries)),
            )
        )
        stack.enter_context(
            mock.patch.object(
                promotion,
                "_recomputed_strict_report",
                return_value=copy.deepcopy(self.strict_report),
            )
        )
        stack.enter_context(
            mock.patch.object(
                promotion, "utc_now", return_value="2000-01-01T00:30:00Z"
            )
        )
        return stack

    def use_balanced_generation(self) -> None:
        authority = promotion.load_authority()
        balanced = json.loads(authority.balanced_authority.data.decode("utf-8"))
        self.generation_contract_id = promotion.BALANCED_PHASE_V2
        self.candidate_id = "B125-M400"
        candidates = []
        for index, record in enumerate(balanced["candidates"]["records"]):
            selected = record["candidate_id"] == self.candidate_id
            candidates.append(
                {
                    "candidate_id": record["candidate_id"],
                    "path": record["output_path"],
                    "sha256": (
                        self.candidate_sha256
                        if selected
                        else hashlib.sha256(
                            f"synthetic-balanced-nonselected-{index}".encode("ascii")
                        ).hexdigest()
                    ),
                    "bytes": self.candidate.stat().st_size if selected else index + 101,
                }
            )
        profiles = balanced["cli_contract"]["required_comparison_profile_ids"]
        self.seal_paths = tuple(
            self.evidence_root / f"synthetic-balanced-{index}-seal.json"
            for index in range(len(profiles))
        )
        firewall_sha = promotion.balanced_derivation.source_bindings(balanced)[
            "sealed-v19-statistics-firewall"
        ]["sha256"]
        for path, profile in zip(self.seal_paths, profiles, strict=True):
            path.write_bytes(
                promotion.balanced_derivation.canonical_output_seal_json(
                    {
                        "schema_id": (
                            "sstory.k3.golden-v3."
                            "balanced-phase-v2-output-seal.v1"
                        ),
                        "authority_self_sha256": balanced["canonical_self_sha256"],
                        "statistics_firewall_sha256": firewall_sha,
                        "runtime_attestation": (
                            promotion.balanced_derivation.expected_runtime_attestation(
                                balanced, profile
                            )
                        ),
                        "candidate_count": 4,
                        "candidates": copy.deepcopy(candidates),
                    }
                )
            )
        candidate = promotion._bind(
            self.candidate, label="synthetic balanced candidate", trackable=False
        )
        selected_path = next(
            record["output_path"]
            for record in balanced["candidates"]["records"]
            if record["candidate_id"] == self.candidate_id
        )
        self.seal_bindings, self.seal_summaries = promotion._validate_generation_seals(
            self.seal_paths,
            authority=authority,
            generation_contract_id=self.generation_contract_id,
            candidate_id=self.candidate_id,
            candidate=replace(candidate, relative=selected_path),
        )

    def promote(self) -> dict[str, object]:
        with self.promotion_patches():
            return promotion.promote_candidate(
                generation_contract_id=self.generation_contract_id,
                candidate_id=self.candidate_id,
                candidate_path=self.candidate,
                generation_seal_paths=self.seal_paths,
                strict_audit_report_path=self.strict_report_path,
                root_review_path=self.root_review_path,
                blind_packet_path=self.packet_path,
                review_paths=self.review_paths,
                authorized_by="Synthetic Promotion Test",
                paths=self.paths,
            )

    def verify_phase5(self) -> dict[str, object]:
        with mock.patch.object(
            promotion,
            "_recomputed_strict_report",
            return_value=copy.deepcopy(self.strict_report),
        ):
            return phase5.verify_manifest_golden_style(
                {"path": relative(self.paths.master), "sha256": digest(self.paths.master)},
                self.manifest,
            )

    def assert_outputs_absent(self) -> None:
        self_test = unittest.TestCase()
        self_test.assertFalse(self.paths.raw.exists())
        self_test.assertFalse(self.paths.master.exists())
        self_test.assertFalse(self.paths.receipt.exists())

    def cleanup(self) -> None:
        for temporary in reversed(self._temps):
            temporary.cleanup()


class CandidateK3GoldenPromotionV3Test(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = PromotionV3Fixture()

    def tearDown(self) -> None:
        self.fixture.cleanup()

    def test_authority_is_candidate_blind_and_schema_bound(self) -> None:
        authority = promotion.load_authority()
        self.assertEqual(authority.binding.sha256, promotion.EXPECTED_AUTHORITY_SHA256)
        self.assertEqual(
            authority.strict_authority.sha256,
            "c27b41e6336974c5ce5fe11c86cefc67ed35851650680c33379c3510444884d7",
        )
        self.assertEqual(
            authority.derivation_authority.sha256,
            "b1e5550ea73189540dae5469ee16521df8b5e3a39b689a349882e811d0ed44ac",
        )
        self.assertEqual(set(authority.document["runtime_bindings"].values()), {None})
        self.assertFalse(authority.document["promotion_performed"])
        self.assertEqual(authority.document["candidate_evaluations_before_freeze"], 0)
        self.assertFalse(authority.document["threshold_selection_from_candidate_values"])
        self.assertEqual(authority.document["schema_version"], "2.0.0")
        self.assertEqual(
            authority.balanced_authority.sha256,
            "f108d6e8c66d9e64723e53b881b6931131573f260e6bf43c96a9efafd5eabe80",
        )
        self.assertEqual(
            authority.balanced_generator.sha256,
            "da33c03ac0724086803b500b8f13ad6edf09898f6489870197738b86e3587981",
        )

    def test_canonical_synthetic_seals_pass_real_cross_profile_validator(self) -> None:
        authority = promotion.load_authority()
        candidate = promotion._bind(
            self.fixture.candidate,
            label="synthetic runtime candidate",
            trackable=False,
        )
        sealed_path = next(
            record["output_path"]
            for record in json.loads(
                authority.derivation_authority.data.decode("utf-8")
            )["candidates"]["records"]
            if record["candidate_id"] == "F094-M148"
        )
        sealed_candidate = replace(candidate, relative=sealed_path)
        bindings, summaries = promotion._validate_generation_seals(
            self.fixture.seal_paths,
            authority=authority,
            generation_contract_id=promotion.FOUR_CANDIDATE_V1,
            candidate_id="F094-M148",
            candidate=sealed_candidate,
        )
        self.assertEqual(len(bindings), 2)
        self.assertEqual(len(summaries), 2)
        self.assertTrue(all(item["payload_utf8"].endswith("\n") for item in summaries))

        duplicate_profile = json.loads(self.fixture.seal_paths[1].read_text("utf-8"))
        duplicate_profile["runtime_profile_id"] = json.loads(
            self.fixture.seal_paths[0].read_text("utf-8")
        )["runtime_profile_id"]
        self.fixture.seal_paths[1].write_bytes(
            promotion.derivation.canonical_output_seal_json(duplicate_profile)
        )
        with self.assertRaisesRegex(
            promotion.GoldenV3PromotionError, "distinct runtime profiles"
        ):
            promotion._validate_generation_seals(
                self.fixture.seal_paths,
                authority=authority,
                generation_contract_id=promotion.FOUR_CANDIDATE_V1,
                candidate_id="F094-M148",
                candidate=sealed_candidate,
            )

    def test_promotes_exclusively_and_phase5_revalidates_v3(self) -> None:
        result = self.fixture.promote()
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["candidate_id"], "F094-M148")
        self.assertEqual(self.fixture.paths.raw.read_bytes(), self.fixture.candidate.read_bytes())
        self.assertEqual(
            self.fixture.paths.master.read_bytes(), self.fixture.candidate.read_bytes()
        )
        receipt = json.loads(self.fixture.paths.receipt.read_text(encoding="utf-8"))
        self.assertTrue(receipt["promotion_performed"])
        self.assertEqual(receipt["candidate"]["sha256"], self.fixture.candidate_sha256)

        evidence = self.fixture.verify_phase5()
        self.assertEqual(evidence["evidence_contract_version"], "v3")
        self.assertEqual(evidence["job_id"], promotion.JOB_ID)
        self.assertEqual(evidence["review_target"], evidence["master"])
        self.assertEqual(len(evidence["manifest_vision_reports"]), 2)
        self.assertEqual(len(evidence["blind_packet_views"]), 5)

    def test_balanced_phase_v2_promotes_with_canonical_phase5_provenance(self) -> None:
        self.fixture.use_balanced_generation()
        result = self.fixture.promote()
        self.assertEqual(result["candidate_id"], "B125-M400")
        self.assertEqual(
            result["generation_contract_id"], promotion.BALANCED_PHASE_V2
        )
        receipt = json.loads(self.fixture.paths.receipt.read_text(encoding="utf-8"))
        self.assertEqual(
            receipt["generation_contract_id"], promotion.BALANCED_PHASE_V2
        )
        self.assertEqual(
            receipt["generation_authority"]["sha256"],
            promotion.load_authority().balanced_authority.sha256,
        )
        self.assertEqual(
            receipt["generation_generator"]["sha256"],
            promotion.load_authority().balanced_generator.sha256,
        )
        evidence = self.fixture.verify_phase5()
        self.assertEqual(
            evidence["generation_contract_id"], promotion.BALANCED_PHASE_V2
        )

    def test_mixed_v1_and_balanced_seals_fail_before_promotion(self) -> None:
        v1_seal = self.fixture.seal_paths[0]
        self.fixture.use_balanced_generation()
        candidate = promotion._bind(
            self.fixture.candidate,
            label="synthetic mixed-generation candidate",
            trackable=False,
        )
        contract = promotion.load_authority().document["generation_contract"][
            "contracts"
        ][promotion.BALANCED_PHASE_V2]
        sealed_candidate = replace(candidate, relative=contract["output_paths"][0])
        with self.assertRaises(promotion.GoldenV3PromotionError):
            promotion._validate_generation_seals(
                (self.fixture.seal_paths[0], v1_seal),
                authority=promotion.load_authority(),
                generation_contract_id=promotion.BALANCED_PHASE_V2,
                candidate_id=self.fixture.candidate_id,
                candidate=sealed_candidate,
            )

    def test_balanced_phase5_rejects_structured_runtime_attestation_tamper(self) -> None:
        self.fixture.use_balanced_generation()
        self.fixture.promote()
        receipt = json.loads(self.fixture.paths.receipt.read_text(encoding="utf-8"))
        summary = receipt["generation_seals"][0]
        seal = json.loads(summary["payload_utf8"])
        seal["runtime_attestation"]["common"]["opencv_threads"] = 2
        payload = promotion.balanced_derivation.canonical_output_seal_json(seal)
        summary["payload_utf8"] = payload.decode("utf-8")
        summary["sha256"] = hashlib.sha256(payload).hexdigest()
        self.fixture._write_json(self.fixture.paths.receipt, receipt)
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        receipt_input = next(
            item
            for item in manifest["jobs"][0]["inputs"]
            if item["role"] == promotion.V3_ACCEPTANCE_RECEIPT_ROLE
        )
        receipt_input["sha256"] = digest(self.fixture.paths.receipt)
        self.fixture._write_json(self.fixture.manifest, manifest)
        with self.assertRaisesRegex(
            phase5.Phase5BuildError, "runtime attestation"
        ):
            self.fixture.verify_phase5()

    def test_phase5_rejects_mixed_v1_and_balanced_generation_evidence(self) -> None:
        self.fixture.use_balanced_generation()
        self.fixture.promote()
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        v1_authority = promotion.load_authority().derivation_authority
        manifest["jobs"][0]["inputs"].insert(
            4,
            {
                "path": v1_authority.relative,
                "sha256": v1_authority.sha256,
                "role": promotion.V3_DERIVATION_AUTHORITY_ROLE,
            },
        )
        self.fixture._write_json(self.fixture.manifest, manifest)
        with self.assertRaisesRegex(
            phase5.Phase5BuildError, "input role order changed"
        ):
            self.fixture.verify_phase5()

    def test_strict_report_tamper_fails_before_any_output(self) -> None:
        forged = copy.deepcopy(self.fixture.strict_report)
        forged["passed"] = False
        self.fixture.strict_report_path.write_bytes(
            promotion.strict_audit.canonical_json(forged)
        )
        with self.fixture.promotion_patches(), self.assertRaisesRegex(
            promotion.GoldenV3PromotionError, "passed must be True"
        ):
            promotion.promote_candidate(
                generation_contract_id=promotion.FOUR_CANDIDATE_V1,
                candidate_id="F094-M148",
                candidate_path=self.fixture.candidate,
                generation_seal_paths=self.fixture.seal_paths,
                strict_audit_report_path=self.fixture.strict_report_path,
                root_review_path=self.fixture.root_review_path,
                blind_packet_path=self.fixture.packet_path,
                review_paths=self.fixture.review_paths,
                authorized_by="Synthetic Promotion Test",
                paths=self.fixture.paths,
            )
        self.fixture.assert_outputs_absent()

    def test_nfkc_alias_reviewer_tamper_fails_before_any_output(self) -> None:
        self.fixture.reviews["a"]["reviewer"] = (
            "independent-vision-review-a/Ｒｏｏｔ　Ｖｉｓｉｏｎ　Ａｕｔｈｏｒｉｔｙ"
        )
        self.fixture.persist_reviews()
        with self.assertRaisesRegex(
            promotion.GoldenV3PromotionError, "identities must all be distinct"
        ):
            self.fixture.promote()
        self.fixture.assert_outputs_absent()

    def test_existing_output_is_never_overwritten(self) -> None:
        sentinel = b"do-not-overwrite"
        self.fixture.paths.master.write_bytes(sentinel)
        manifest_before = self.fixture.manifest.read_bytes()
        with self.assertRaisesRegex(
            promotion.GoldenV3PromotionError, "never overwrites"
        ):
            self.fixture.promote()
        self.assertEqual(self.fixture.paths.master.read_bytes(), sentinel)
        self.assertFalse(self.fixture.paths.raw.exists())
        self.assertFalse(self.fixture.paths.receipt.exists())
        self.assertEqual(self.fixture.manifest.read_bytes(), manifest_before)

    def test_master_collision_after_raw_creation_preserves_collision(self) -> None:
        sentinel = b"concurrent-master"
        original_write = promotion._write_exclusive

        def collide_on_master(path: Path, payload: bytes, *, label: str):
            if label == "Golden-v3 master":
                path.write_bytes(sentinel)
            return original_write(path, payload, label=label)

        with mock.patch.object(
            promotion, "_write_exclusive", side_effect=collide_on_master
        ), self.assertRaisesRegex(
            promotion.GoldenV3PromotionError, "refusing to overwrite"
        ):
            self.fixture.promote()
        self.assertFalse(self.fixture.paths.raw.exists())
        self.assertEqual(self.fixture.paths.master.read_bytes(), sentinel)
        self.assertFalse(self.fixture.paths.receipt.exists())

    def test_manifest_cas_failure_removes_all_new_outputs(self) -> None:
        with mock.patch.object(
            promotion.manifest_cas,
            "_conditional_manifest_replace",
            side_effect=promotion.manifest_cas.K3GoldenPromotionV2Error(
                "synthetic compare-and-swap failure"
            ),
        ), self.assertRaisesRegex(
            promotion.GoldenV3PromotionError, "synthetic compare-and-swap failure"
        ):
            self.fixture.promote()
        self.fixture.assert_outputs_absent()

    def test_manifest_commit_unknown_retains_exact_evidence(self) -> None:
        manifest_before = self.fixture.manifest.read_bytes()
        with mock.patch.object(
            promotion.manifest_cas,
            "_conditional_manifest_replace",
            side_effect=promotion.manifest_cas.ManifestCommitStateUnknownError(
                manifest=relative(self.fixture.manifest),
                reason="synthetic unknown commit state",
                debris=(),
                cleanup_failures=(),
            ),
        ), self.assertRaisesRegex(
            promotion.GoldenV3ManifestCommitUnknownError,
            "synthetic unknown commit state",
        ):
            self.fixture.promote()
        self.assertTrue(self.fixture.paths.raw.is_file())
        self.assertTrue(self.fixture.paths.master.is_file())
        self.assertTrue(self.fixture.paths.receipt.is_file())
        self.assertEqual(self.fixture.manifest.read_bytes(), manifest_before)

    def test_packet_view_tamper_fails_master_derivation_before_output(self) -> None:
        tampered_view = self.fixture.views[1]
        with Image.new("RGB", VIEW_DEFINITIONS["full25"][1], color=(5, 6, 7)) as image:
            image.save(tampered_view, format="PNG", compress_level=9)
        self.fixture.packet["views"][1]["sha256"] = digest(tampered_view)
        self.fixture._write_json(self.fixture.packet_path, self.fixture.packet)
        with self.assertRaisesRegex(
            promotion.GoldenV3PromotionError, "is not derived from the promoted master"
        ):
            self.fixture.promote()
        self.fixture.assert_outputs_absent()

    def test_review_must_attest_exact_packet_sha256(self) -> None:
        self.fixture.reviews["a"]["vision_bundle"]["receipt"]["sha256"] = "0" * 64
        self.fixture.persist_reviews()
        with self.assertRaisesRegex(
            promotion.GoldenV3PromotionError,
            "must attest the exact blind packet path/SHA-256",
        ):
            self.fixture.promote()
        self.fixture.assert_outputs_absent()

    def test_embedded_cross_profile_seal_tamper_cleans_outputs(self) -> None:
        summary = self.fixture.seal_summaries[0]
        seal = json.loads(summary["payload_utf8"])
        selected = next(
            item for item in seal["candidates"] if item["candidate_id"] == "F094-M148"
        )
        selected["sha256"] = "0" * 64
        payload = promotion.derivation.canonical_output_seal_json(seal)
        summary["payload_utf8"] = payload.decode("utf-8")
        summary["sha256"] = hashlib.sha256(payload).hexdigest()
        with self.assertRaisesRegex(
            promotion.GoldenV3PromotionError,
            "embedded cross-profile generation seals disagree",
        ):
            self.fixture.promote()
        self.fixture.assert_outputs_absent()

    def test_phase5_rejects_coherently_rehashed_receipt_tamper(self) -> None:
        self.fixture.promote()
        receipt = json.loads(self.fixture.paths.receipt.read_text(encoding="utf-8"))
        receipt["reviews"][0]["score"] = 99
        self.fixture._write_json(self.fixture.paths.receipt, receipt)
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        receipt_input = next(
            item
            for item in manifest["jobs"][0]["inputs"]
            if item["role"] == promotion.V3_ACCEPTANCE_RECEIPT_ROLE
        )
        receipt_input["sha256"] = digest(self.fixture.paths.receipt)
        self.fixture._write_json(self.fixture.manifest, manifest)
        with self.assertRaisesRegex(phase5.Phase5BuildError, "review summary changed"):
            self.fixture.verify_phase5()

    def test_phase5_rejects_coherently_relocated_raw_output(self) -> None:
        self.fixture.promote()
        relocated_raw = self.fixture.evidence_root / "relocated-raw.png"
        relocated_raw.write_bytes(self.fixture.paths.raw.read_bytes())

        receipt = json.loads(self.fixture.paths.receipt.read_text(encoding="utf-8"))
        receipt["raw"]["path"] = relative(relocated_raw)
        self.fixture._write_json(self.fixture.paths.receipt, receipt)

        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        raw_input = next(
            item
            for item in manifest["jobs"][0]["inputs"]
            if item["role"] == promotion.RAW_ROLE
        )
        raw_input["path"] = relative(relocated_raw)
        receipt_input = next(
            item
            for item in manifest["jobs"][0]["inputs"]
            if item["role"] == promotion.V3_ACCEPTANCE_RECEIPT_ROLE
        )
        receipt_input["sha256"] = digest(self.fixture.paths.receipt)
        self.fixture._write_json(self.fixture.manifest, manifest)

        with self.assertRaisesRegex(phase5.Phase5BuildError, "must stay below"):
            self.fixture.verify_phase5()

    def test_phase5_rejects_forged_generation_profile_summary(self) -> None:
        self.fixture.promote()
        receipt = json.loads(self.fixture.paths.receipt.read_text(encoding="utf-8"))
        receipt["generation_seals"][0]["runtime_profile_id"] = "forged-profile"
        self.fixture._write_json(self.fixture.paths.receipt, receipt)
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        receipt_input = next(
            item
            for item in manifest["jobs"][0]["inputs"]
            if item["role"] == promotion.V3_ACCEPTANCE_RECEIPT_ROLE
        )
        receipt_input["sha256"] = digest(self.fixture.paths.receipt)
        self.fixture._write_json(self.fixture.manifest, manifest)
        with self.assertRaisesRegex(
            phase5.Phase5BuildError, "generation seal .* profile changed"
        ):
            self.fixture.verify_phase5()

    def test_phase5_rejects_coherent_duplicate_sealed_candidate_sha(self) -> None:
        self.fixture.promote()
        receipt = json.loads(self.fixture.paths.receipt.read_text(encoding="utf-8"))
        receipt["candidate_id"] = "F094-M155"
        for summary in receipt["generation_seals"]:
            seal = json.loads(summary["payload_utf8"])
            forged = next(
                item
                for item in seal["candidates"]
                if item["candidate_id"] == "F094-M155"
            )
            forged["sha256"] = self.fixture.candidate_sha256
            forged["bytes"] = self.fixture.candidate.stat().st_size
            payload = promotion.derivation.canonical_output_seal_json(seal)
            summary["payload_utf8"] = payload.decode("utf-8")
            summary["sha256"] = hashlib.sha256(payload).hexdigest()
        self.fixture._write_json(self.fixture.paths.receipt, receipt)
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        receipt_input = next(
            item
            for item in manifest["jobs"][0]["inputs"]
            if item["role"] == promotion.V3_ACCEPTANCE_RECEIPT_ROLE
        )
        receipt_input["sha256"] = digest(self.fixture.paths.receipt)
        self.fixture._write_json(self.fixture.manifest, manifest)
        with self.assertRaisesRegex(
            phase5.Phase5BuildError, "candidate payloads are not unique"
        ):
            self.fixture.verify_phase5()

    def test_phase5_refuses_partial_v3_legacy_fallback(self) -> None:
        self.fixture.promote()
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        manifest["jobs"][0]["inputs"] = [
            item
            for item in manifest["jobs"][0]["inputs"]
            if item["role"] != promotion.V3_ACCEPTANCE_RECEIPT_ROLE
        ]
        self.fixture._write_json(self.fixture.manifest, manifest)
        with self.assertRaisesRegex(
            phase5.Phase5BuildError, "incomplete or mixed; refusing legacy fallback"
        ):
            self.fixture.verify_phase5()

    def test_phase5_refuses_mixed_v2_v3_evidence(self) -> None:
        self.fixture.promote()
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        manifest["jobs"][0]["inputs"].append(
            {
                "path": relative(self.fixture.paths.receipt),
                "sha256": digest(self.fixture.paths.receipt),
                "role": phase5.GOLDEN_ACCEPTANCE_RECEIPT_ROLE,
            }
        )
        self.fixture._write_json(self.fixture.manifest, manifest)
        with self.assertRaisesRegex(
            phase5.Phase5BuildError, "incomplete or mixed; refusing legacy fallback"
        ):
            self.fixture.verify_phase5()


class Phase5V3DispatchRegressionTest(unittest.TestCase):
    def test_packet_only_partial_v2_never_falls_back_to_v1(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix=".golden-v3-dispatch-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            master = root / "synthetic-master.bin"
            packet = root / "synthetic-packet.json"
            manifest_path = root / "manifest.json"
            master.write_bytes(b"synthetic master")
            packet.write_bytes(b"{}\n")
            golden_style = {"path": relative(master), "sha256": digest(master)}
            manifest = {
                "jobs": [
                    {
                        "id": "legacy-partial-v2-fixture",
                        "master": dict(golden_style),
                        "inputs": [
                            {
                                "path": relative(packet),
                                "sha256": digest(packet),
                                "role": phase5.GOLDEN_BLIND_PACKET_ROLE,
                            }
                        ],
                    }
                ]
            }
            manifest_path.write_bytes(
                (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
            )
            with self.assertRaisesRegex(
                phase5.Phase5BuildError,
                "v2 evidence is incomplete; refusing legacy fallback",
            ):
                phase5.verify_manifest_golden_style(golden_style, manifest_path)


if __name__ == "__main__":
    unittest.main()
