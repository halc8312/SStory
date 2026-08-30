from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import subprocess
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


def create_directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", os.fspath(link), os.fspath(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise OSError(result.stderr or result.stdout or "mklink /J failed")
    else:
        link.symlink_to(target, target_is_directory=True)


def remove_directory_link(link: Path) -> None:
    if hasattr(link, "is_junction") and link.is_junction():
        link.rmdir()
    else:
        link.unlink()


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

        authority = promotion.load_authority()
        self.strict_report = {
            "schema_version": "1.0.0",
            "id": "style-candidate-k-v3-golden-v3-strict-independent-pixel-audit",
            "algorithm": "sstory-k3-golden-v3-strict-independent-pixel-audit-v1",
            "authority_sha256": authority.strict_module.EXPECTED_AUTHORITY_SHA256,
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
            authority.strict_module.canonical_json(self.strict_report)
        )

        derivation_authority = json.loads(
            authority.derivation_authority.data.decode("utf-8")
        )
        sealed_candidates = []
        for index, record in enumerate(derivation_authority["candidates"]["records"]):
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
                        "statistics_firewall_sha256": derivation_authority[
                            "derivation"
                        ]["v19_statistical_authority"]["future_artifact_sha256"],
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
        self.four_candidate_seal_paths = self.seal_paths
        self.four_candidate_seal_bindings = self.seal_bindings
        self.four_candidate_seal_summaries = copy.deepcopy(self.seal_summaries)

        view_root = self.evidence_root / "views"
        view_root.mkdir()
        self.views: list[Path] = []
        with Image.open(self.candidate) as source_image:
            source_image.load()
            for view_id in VIEW_IDS:
                crop, size = VIEW_DEFINITIONS[view_id]
                working = (
                    source_image.copy() if crop is None else source_image.crop(crop)
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
                reviewer=("golden-v3-root-vision-authorization/Root Vision Authority"),
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
        self.use_balanced_open_generation()

    @staticmethod
    def _write_json(path: Path, document: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
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
            mock.patch.object(promotion, "utc_now", return_value="2000-01-01T00:30:00Z")
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
                            "sstory.k3.golden-v3.balanced-phase-v2-output-seal.v1"
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

    def use_balanced_open_generation(self) -> None:
        authority = promotion.load_authority()
        balanced_open = json.loads(
            authority.balanced_open_authority.data.decode("utf-8")
        )
        self.generation_contract_id = promotion.BALANCED_OPEN_PHASE_V3
        self.candidate_id = "E150-M500"
        certificate = {
            "eligible_records": 96,
            "maximum_numerator": 0,
            "maximum_variance_product": 1,
            "maximum_correlation_q20": 0,
        }
        construction_receipt = {
            "amplitude_matching_iterations": 4,
            "amplitude_lag_certificate": copy.deepcopy(certificate),
            "unit_lag_certificate": copy.deepcopy(certificate),
            "quiet_clipped_pixels": 0,
            "short_dark_repairs": 0,
            "short_dark_pixels": 0,
            "topology_repairs": 0,
            "topology_pixels": 0,
        }
        candidates = []
        for index, record in enumerate(balanced_open["candidates"]["records"]):
            selected = record["candidate_id"] == self.candidate_id
            candidates.append(
                {
                    "candidate_id": record["candidate_id"],
                    "path": record["output_path"],
                    "sha256": (
                        self.candidate_sha256
                        if selected
                        else hashlib.sha256(
                            f"synthetic-balanced-open-nonselected-{index}".encode(
                                "ascii"
                            )
                        ).hexdigest()
                    ),
                    "bytes": self.candidate.stat().st_size if selected else index + 201,
                    "construction_receipt": copy.deepcopy(construction_receipt),
                }
            )
        profiles = balanced_open["cli_contract"]["required_comparison_profile_ids"]
        self.seal_paths = tuple(
            self.evidence_root / f"synthetic-balanced-open-{index}-seal.json"
            for index in range(len(profiles))
        )
        firewall_sha = promotion.balanced_open_derivation.source_bindings(
            balanced_open
        )["sealed-v19-statistics-firewall"]["sha256"]
        for path, profile in zip(self.seal_paths, profiles, strict=True):
            path.write_bytes(
                promotion.balanced_open_derivation.canonical_output_seal_json(
                    {
                        "schema_id": (
                            "sstory.k3.golden-v3.balanced-open-phase-v3-output-seal.v1"
                        ),
                        "authority_self_sha256": balanced_open["canonical_self_sha256"],
                        "statistics_firewall_sha256": firewall_sha,
                        "runtime_attestation": (
                            promotion.balanced_open_derivation.expected_runtime_attestation(
                                balanced_open, profile
                            )
                        ),
                        "candidate_count": 4,
                        "candidates": copy.deepcopy(candidates),
                    }
                )
            )
        candidate = promotion._bind(
            self.candidate,
            label="synthetic balanced-open candidate",
            trackable=False,
        )
        selected_path = next(
            record["output_path"]
            for record in balanced_open["candidates"]["records"]
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
                {
                    "path": relative(self.paths.master),
                    "sha256": digest(self.paths.master),
                },
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
            authority.strict_implementation.sha256,
            "b039b970d8a7140a7326942c139a7d2e0420736e3b48fe4162364736313abb5a",
        )
        self.assertEqual(
            [item.sha256 for item in authority.strict_dependencies],
            [
                "92100794ff519fb77c7bca89af74897dcc422c9bb341582d31355d6b98cd229a",
                "21607b7618e765bbcabc1c36c6880e465b2c08edbebfdea8a9855089d5bd8e69",
                "eb4d89da6669e6cda94e43e395d997b870b3c361576dbfb396373dee88562384",
            ],
        )
        self.assertIs(promotion.strict_audit, authority.strict_module)
        self.assertEqual(
            authority.derivation_authority.sha256,
            "b1e5550ea73189540dae5469ee16521df8b5e3a39b689a349882e811d0ed44ac",
        )
        self.assertEqual(set(authority.document["runtime_bindings"].values()), {None})
        self.assertFalse(authority.document["promotion_performed"])
        freeze = authority.document["freeze_scope"]
        self.assertEqual(
            freeze["active_generation_contract_id"],
            promotion.BALANCED_OPEN_PHASE_V3,
        )
        self.assertEqual(freeze["candidate_evaluations_before_freeze"], 0)
        self.assertEqual(freeze["candidate_images_read_before_freeze"], 0)
        self.assertEqual(freeze["audit_results_read_before_freeze"], 0)
        self.assertFalse(freeze["threshold_selection_from_candidate_values"])
        self.assertEqual(
            authority.document["failure_policy"]["manifest_writer_model"],
            "single-cooperative-writer-respecting-fixed-exclusive-lock",
        )
        self.assertEqual(
            authority.document["failure_policy"]["noncooperative_namespace_race"],
            "atomic-retention-plus-unknown-manual-reconciliation",
        )
        self.assertEqual(
            authority.document["failure_policy"]["noncooperative_guarantee"],
            "manifest-target-bytes-atomically-retained-no-silent-success-not-conditional-inode-overwrite-prevention",
        )
        self.assertEqual(
            authority.document["failure_policy"]["windows_backup_namespace"],
            "exclusive-unpredictable-reservation; post-close-noncooperative-backup-basename-replacement-excluded",
        )
        self.assertEqual(
            freeze["legacy_contract_status"],
            {
                promotion.FOUR_CANDIDATE_V1: (
                    "evaluated-and-rejected-before-this-revision; compatibility-only"
                ),
                promotion.BALANCED_PHASE_V2: (
                    "evaluated-and-rejected-before-this-revision; compatibility-only"
                ),
            },
        )
        self.assertEqual(authority.document["schema_version"], "3.0.0")
        self.assertEqual(
            authority.derivation_generator.sha256,
            "5a38aece70641c8bda224e076ed41bdd09de0ad9421590cb7aae729936e63b76",
        )
        self.assertEqual(
            authority.balanced_authority.sha256,
            "f108d6e8c66d9e64723e53b881b6931131573f260e6bf43c96a9efafd5eabe80",
        )
        self.assertEqual(
            authority.balanced_generator.sha256,
            "da33c03ac0724086803b500b8f13ad6edf09898f6489870197738b86e3587981",
        )
        self.assertEqual(
            authority.balanced_open_authority.sha256,
            "3c914b573a2415a06dff195f0b4f155082b15667d12409dd9195ead67c2e05a9",
        )
        self.assertEqual(
            authority.balanced_open_generator.sha256,
            "ca09af2760c3d0acb958e0e6e7afa92f010aef2593eda2e712c3a8f4e0e76b52",
        )
        balanced_open = json.loads(
            authority.balanced_open_authority.data.decode("utf-8")
        )
        self.assertEqual(
            balanced_open["canonical_self_sha256"],
            "38693b232f55b559152240ef5f56e1467ea0985318a68c4e22cbb1551d6f2f9c",
        )
        bindings = {
            item["role"]: item
            for item in balanced_open["input_policy"]["source_bindings"]
        }
        self.assertEqual(
            bindings["balanced-open-phase-v3-synthetic-tests"]["sha256"],
            "93026720eefb800906229b66915d6b7bc78d3633e9ed27b3d0cbe99e1b490d17",
        )
        self.assertEqual(
            authority.promotion_implementation_sha256,
            promotion.EXPECTED_IMPLEMENTATION_SELF_SHA256,
        )
        self.assertEqual(
            promotion._implementation_self_sha256(
                authority.promotion_implementation.data
            ),
            promotion.EXPECTED_IMPLEMENTATION_SELF_SHA256,
        )
        graph_references = {
            (raw_path, location): claimed
            for raw_path, claimed, location, _ in phase5._phase5_json_path_references(
                authority.document
            )
        }
        self.assertIsNone(
            graph_references[
                (
                    authority.promotion_implementation.relative,
                    "$.promotion_implementation.path",
                )
            ]
        )
        self.assertEqual(
            graph_references[
                (
                    authority.strict_implementation.relative,
                    "$.authorities.strict_audit_implementation.path",
                )
            ],
            authority.strict_implementation.sha256,
        )

    def test_runtime_modules_are_loaded_only_from_sha_bound_bytes(self) -> None:
        tree = ast.parse(Path(promotion.__file__).read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertFalse(
            any(
                name.startswith("generate_style_candidate_k3_golden_v3")
                for name in imported
            )
        )
        self.assertNotIn("audit_style_candidate_k3_golden_v3", imported)
        self.assertTrue(
            {
                "audit_style_candidate_k3_golden_v2",
                "build_style_candidate_k3_sparse_ridgeline_v19",
                "golden_v3_strict_metric_core",
                "promote_style_candidate_k3_golden_v2",
                "importlib",
            }.isdisjoint(imported)
        )
        authority = promotion.load_authority()
        self.assertIs(promotion.derivation, authority.derivation_module)
        self.assertIs(promotion.balanced_derivation, authority.balanced_module)
        self.assertIs(
            promotion.balanced_open_derivation, authority.balanced_open_module
        )
        self.assertIs(promotion.strict_audit, authority.strict_module)
        self.assertIs(
            authority.strict_module.v19, authority.strict_dependency_modules[0]
        )
        self.assertIs(
            authority.strict_module.v2, authority.strict_dependency_modules[1]
        )
        self.assertIs(
            authority.strict_module.strict, authority.strict_dependency_modules[2]
        )

    def test_authority_load_never_imports_unbound_legacy_promoter(self) -> None:
        script = f"""
import builtins
import sys
sys.path.insert(0, {str(SCRIPT_DIR)!r})
real_import = builtins.__import__
attempted = []
def guarded_import(name, *args, **kwargs):
    if name == 'promote_style_candidate_k3_golden_v2':
        attempted.append(name)
        raise AssertionError('unbound legacy promoter import attempted')
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
import promote_style_candidate_k3_golden_v3 as promotion
promotion.load_authority()
assert attempted == []
assert 'promote_style_candidate_k3_golden_v2' not in sys.modules
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_strict_auditor_tamper_fails_before_module_execution(self) -> None:
        original_bind = promotion._bind

        def bind_with_tampered_auditor(
            path: str | Path, *, label: str, trackable: bool = True
        ) -> promotion.BoundArtifact:
            binding = original_bind(path, label=label, trackable=trackable)
            if label != "Golden-v3 strict audit implementation":
                return binding
            payload = binding.data + b"\n# synthetic constant-preserving tamper\n"
            return replace(
                binding,
                _data=payload,
                sha256=hashlib.sha256(payload).hexdigest(),
            )

        with (
            mock.patch.object(
                promotion, "_bind", side_effect=bind_with_tampered_auditor
            ),
            mock.patch.object(
                promotion, "_load_bound_module", wraps=promotion._load_bound_module
            ) as loader,
            self.assertRaisesRegex(
                promotion.GoldenV3PromotionError,
                "strict audit implementation SHA-256 mismatch",
            ),
        ):
            promotion.load_authority()
        loader.assert_not_called()

    def test_strict_auditor_dependency_tamper_fails_before_execution(self) -> None:
        original_bind = promotion._bind
        labels = (
            "Golden-v3 strict audit v19 dependency",
            "Golden-v3 strict audit v2 dependency",
            "Golden-v3 strict audit core dependency",
        )
        for tampered_label in labels:
            with self.subTest(label=tampered_label):

                def bind_with_tampered_dependency(
                    path: str | Path, *, label: str, trackable: bool = True
                ) -> promotion.BoundArtifact:
                    binding = original_bind(path, label=label, trackable=trackable)
                    if label != tampered_label:
                        return binding
                    payload = binding.data + b"\n# synthetic dependency tamper\n"
                    return replace(
                        binding,
                        _data=payload,
                        sha256=hashlib.sha256(payload).hexdigest(),
                    )

                with (
                    mock.patch.object(
                        promotion,
                        "_bind",
                        side_effect=bind_with_tampered_dependency,
                    ),
                    mock.patch.object(
                        promotion,
                        "_load_bound_module",
                        wraps=promotion._load_bound_module,
                    ) as loader,
                    self.assertRaisesRegex(
                        promotion.GoldenV3PromotionError,
                        "dependency SHA-256 mismatch",
                    ),
                ):
                    promotion.load_authority()
                loader.assert_not_called()

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
            self.fixture.four_candidate_seal_paths,
            authority=authority,
            generation_contract_id=promotion.FOUR_CANDIDATE_V1,
            candidate_id="F094-M148",
            candidate=sealed_candidate,
        )
        self.assertEqual(len(bindings), 2)
        self.assertEqual(len(summaries), 2)
        self.assertTrue(all(item["payload_utf8"].endswith("\n") for item in summaries))

        duplicate_profile = json.loads(
            self.fixture.four_candidate_seal_paths[1].read_text("utf-8")
        )
        duplicate_profile["runtime_profile_id"] = json.loads(
            self.fixture.four_candidate_seal_paths[0].read_text("utf-8")
        )["runtime_profile_id"]
        self.fixture.four_candidate_seal_paths[1].write_bytes(
            promotion.derivation.canonical_output_seal_json(duplicate_profile)
        )
        with self.assertRaisesRegex(
            promotion.GoldenV3PromotionError, "distinct runtime profiles"
        ):
            promotion._validate_generation_seals(
                self.fixture.four_candidate_seal_paths,
                authority=authority,
                generation_contract_id=promotion.FOUR_CANDIDATE_V1,
                candidate_id="F094-M148",
                candidate=sealed_candidate,
            )

    def test_promotes_exclusively_and_phase5_revalidates_v3(self) -> None:
        result = self.fixture.promote()
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["candidate_id"], "E150-M500")
        self.assertEqual(
            self.fixture.paths.raw.read_bytes(), self.fixture.candidate.read_bytes()
        )
        self.assertEqual(
            self.fixture.paths.master.read_bytes(), self.fixture.candidate.read_bytes()
        )
        receipt = json.loads(self.fixture.paths.receipt.read_text(encoding="utf-8"))
        self.assertTrue(receipt["promotion_performed"])
        self.assertEqual(receipt["candidate"]["sha256"], self.fixture.candidate_sha256)
        authority = promotion.load_authority()
        self.assertEqual(
            receipt["promotion_implementation"]["sha256"],
            authority.promotion_implementation.sha256,
        )
        self.assertNotEqual(
            authority.promotion_implementation.sha256,
            authority.promotion_implementation_sha256,
        )
        self.assertEqual(
            receipt["strict_audit_implementation"],
            promotion._artifact(authority.strict_implementation),
        )
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        strict_implementation = next(
            item
            for item in manifest["jobs"][0]["inputs"]
            if item["role"] == promotion.V3_STRICT_IMPLEMENTATION_ROLE
        )
        self.assertEqual(
            {key: strict_implementation[key] for key in ("path", "sha256")},
            promotion._artifact(authority.strict_implementation),
        )

        evidence = self.fixture.verify_phase5()
        self.assertEqual(evidence["evidence_contract_version"], "v3")
        self.assertEqual(evidence["job_id"], promotion.JOB_ID)
        self.assertEqual(evidence["review_target"], evidence["master"])
        self.assertEqual(len(evidence["manifest_vision_reports"]), 2)
        self.assertEqual(len(evidence["blind_packet_views"]), 5)

    def test_phase5_graph_binder_accepts_raw_implementation_binding(self) -> None:
        self.fixture.promote()
        manifest_binding = promotion._bind(
            self.fixture.manifest,
            label="synthetic aggregate production manifest",
        )
        golden_style = {
            "path": relative(self.fixture.paths.master),
            "sha256": digest(self.fixture.paths.master),
        }
        registry = phase5.bind_manifest_golden_evidence(golden_style, manifest_binding)
        authority = promotion.load_authority()
        implementation = authority.promotion_implementation
        self.assertIn(implementation.identity, registry)
        self.assertEqual(
            registry[implementation.identity].sha256,
            implementation.sha256,
        )
        strict_implementation = authority.strict_implementation
        self.assertIn(strict_implementation.identity, registry)
        self.assertEqual(
            registry[strict_implementation.identity].sha256,
            strict_implementation.sha256,
        )
        v1_document = json.loads(authority.derivation_authority.data)
        v1_sources = v1_document["input_policy"]["source_bindings"]
        self.assertEqual(len(v1_sources), 28)
        registry_by_path = {item.relative: item.sha256 for item in registry.values()}
        for source in v1_sources:
            self.assertEqual(registry_by_path.get(source["path"]), source["sha256"])
        with (
            phase5.bound_artifact_context(registry),
            mock.patch.object(
                promotion,
                "_recomputed_strict_report",
                return_value=copy.deepcopy(self.fixture.strict_report),
            ),
        ):
            evidence = phase5.verify_manifest_golden_style(
                golden_style, self.fixture.manifest
            )
        self.assertEqual(evidence["evidence_contract_version"], "v3")

    def test_phase5_revalidates_synthetic_legacy_balanced_phase_v2_provenance(
        self,
    ) -> None:
        self.fixture.use_balanced_generation()
        with mock.patch.object(promotion, "_require_active_generation_contract"):
            result = self.fixture.promote()
        self.assertEqual(result["candidate_id"], "B125-M400")
        self.assertEqual(result["generation_contract_id"], promotion.BALANCED_PHASE_V2)
        receipt = json.loads(self.fixture.paths.receipt.read_text(encoding="utf-8"))
        self.assertEqual(receipt["generation_contract_id"], promotion.BALANCED_PHASE_V2)
        self.assertEqual(
            receipt["generation_authority"]["sha256"],
            promotion.load_authority().balanced_authority.sha256,
        )
        self.assertEqual(
            receipt["generation_generator"]["sha256"],
            promotion.load_authority().balanced_generator.sha256,
        )
        manifest_binding = promotion._bind(
            self.fixture.manifest,
            label="synthetic legacy aggregate production manifest",
        )
        golden_style = {
            "path": relative(self.fixture.paths.master),
            "sha256": digest(self.fixture.paths.master),
        }
        registry = phase5.bind_manifest_golden_evidence(golden_style, manifest_binding)
        legacy_authority = promotion.load_authority().balanced_authority
        self.assertIn(legacy_authority.identity, registry)
        with phase5.bound_artifact_context(registry):
            evidence = self.fixture.verify_phase5()
        self.assertEqual(
            evidence["generation_contract_id"], promotion.BALANCED_PHASE_V2
        )

    def test_balanced_open_phase_v3_promotes_with_canonical_phase5_provenance(
        self,
    ) -> None:
        self.fixture.use_balanced_open_generation()
        result = self.fixture.promote()
        self.assertEqual(result["candidate_id"], "E150-M500")
        self.assertEqual(
            result["generation_contract_id"], promotion.BALANCED_OPEN_PHASE_V3
        )
        receipt = json.loads(self.fixture.paths.receipt.read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema_version"], "3.0.0")
        self.assertEqual(
            receipt["generation_contract_id"], promotion.BALANCED_OPEN_PHASE_V3
        )
        self.assertEqual(
            receipt["generation_authority"]["sha256"],
            promotion.load_authority().balanced_open_authority.sha256,
        )
        self.assertEqual(
            receipt["generation_generator"]["sha256"],
            promotion.load_authority().balanced_open_generator.sha256,
        )
        evidence = self.fixture.verify_phase5()
        self.assertEqual(
            evidence["generation_contract_id"], promotion.BALANCED_OPEN_PHASE_V3
        )

    def test_new_promotion_rejects_legacy_generation_contracts(self) -> None:
        for contract_id, candidate_id in (
            (promotion.FOUR_CANDIDATE_V1, "F094-M148"),
            (promotion.BALANCED_PHASE_V2, "B125-M400"),
        ):
            with self.subTest(contract_id=contract_id):
                with self.assertRaisesRegex(
                    promotion.GoldenV3PromotionError, "verification-only"
                ):
                    promotion.promote_candidate(
                        generation_contract_id=contract_id,
                        candidate_id=candidate_id,
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

    def test_mixed_balanced_v2_and_balanced_open_v3_seals_fail(self) -> None:
        self.fixture.use_balanced_generation()
        balanced_v2_seal = self.fixture.seal_paths[0]
        self.fixture.use_balanced_open_generation()
        candidate = promotion._bind(
            self.fixture.candidate,
            label="synthetic mixed-balanced-generation candidate",
            trackable=False,
        )
        contract = promotion.load_authority().document["generation_contract"][
            "contracts"
        ][promotion.BALANCED_OPEN_PHASE_V3]
        sealed_candidate = replace(candidate, relative=contract["output_paths"][0])
        with self.assertRaises(promotion.GoldenV3PromotionError):
            promotion._validate_generation_seals(
                (self.fixture.seal_paths[0], balanced_v2_seal),
                authority=promotion.load_authority(),
                generation_contract_id=promotion.BALANCED_OPEN_PHASE_V3,
                candidate_id=self.fixture.candidate_id,
                candidate=sealed_candidate,
            )

    def test_balanced_open_phase5_rejects_construction_receipt_tamper(self) -> None:
        self.fixture.use_balanced_open_generation()
        self.fixture.promote()
        receipt = json.loads(self.fixture.paths.receipt.read_text(encoding="utf-8"))
        summary = receipt["generation_seals"][0]
        seal = json.loads(summary["payload_utf8"])
        seal["candidates"][0]["construction_receipt"][
            "amplitude_matching_iterations"
        ] = 5
        payload = promotion.balanced_open_derivation.canonical_output_seal_json(seal)
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
            phase5.Phase5BuildError, "iteration receipt changed"
        ):
            self.fixture.verify_phase5()

    def test_mixed_v1_and_balanced_seals_fail_before_promotion(self) -> None:
        v1_seal = self.fixture.four_candidate_seal_paths[0]
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

    def test_balanced_phase5_rejects_structured_runtime_attestation_tamper(
        self,
    ) -> None:
        self.fixture.use_balanced_generation()
        with mock.patch.object(promotion, "_require_active_generation_contract"):
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
        with self.assertRaisesRegex(phase5.Phase5BuildError, "runtime attestation"):
            self.fixture.verify_phase5()

    def test_phase5_rejects_mixed_v1_and_balanced_generation_evidence(self) -> None:
        self.fixture.use_balanced_generation()
        with mock.patch.object(promotion, "_require_active_generation_contract"):
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
            promotion.load_authority().strict_module.canonical_json(forged)
        )
        with (
            self.fixture.promotion_patches(),
            self.assertRaisesRegex(
                promotion.GoldenV3PromotionError, "passed must be True"
            ),
        ):
            promotion.promote_candidate(
                generation_contract_id=promotion.BALANCED_OPEN_PHASE_V3,
                candidate_id=self.fixture.candidate_id,
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

        with (
            mock.patch.object(
                promotion, "_write_exclusive", side_effect=collide_on_master
            ),
            self.assertRaisesRegex(
                promotion.GoldenV3PromotionError, "refusing to overwrite"
            ),
        ):
            self.fixture.promote()
        self.assertEqual(
            self.fixture.paths.raw.read_bytes(), self.fixture.candidate.read_bytes()
        )
        self.assertEqual(self.fixture.paths.master.read_bytes(), sentinel)
        self.assertFalse(self.fixture.paths.receipt.exists())

    def test_manifest_cas_failure_retains_fail_closed_evidence(self) -> None:
        manifest_before = self.fixture.manifest.read_bytes()
        with (
            mock.patch.object(
                promotion,
                "_conditional_manifest_replace",
                side_effect=promotion.GoldenV3PromotionError(
                    "synthetic compare-and-swap failure"
                ),
            ),
            self.assertRaisesRegex(
                promotion.GoldenV3PromotionError, "synthetic compare-and-swap failure"
            ),
        ):
            self.fixture.promote()
        self.assertEqual(self.fixture.manifest.read_bytes(), manifest_before)
        self.assertEqual(
            self.fixture.paths.raw.read_bytes(), self.fixture.candidate.read_bytes()
        )
        self.assertEqual(
            self.fixture.paths.master.read_bytes(), self.fixture.candidate.read_bytes()
        )
        self.assertTrue(self.fixture.paths.receipt.is_file())

    def test_cleanup_preserves_same_byte_replacement(self) -> None:
        path = self.fixture.candidate_root / "owned-cleanup-test.bin"
        payload = b"same bytes do not prove ownership"
        owned = promotion._write_exclusive(
            path, payload, label="synthetic cleanup ownership test"
        )
        original = self.fixture.candidate_root / "owned-cleanup-original.bin"
        path.replace(original)
        path.write_bytes(payload)
        promotion._cleanup_created([owned])
        self.assertEqual(path.read_bytes(), payload)
        self.assertEqual(original.read_bytes(), payload)

    def test_exclusive_write_failure_retains_fail_closed_debris(self) -> None:
        path = self.fixture.candidate_root / "failed-exclusive-write.bin"
        with (
            mock.patch.object(
                promotion,
                "_bind",
                side_effect=promotion.GoldenV3PromotionError(
                    "synthetic post-write binding failure"
                ),
            ),
            self.assertRaisesRegex(
                promotion.GoldenV3PromotionError, "post-write binding failure"
            ),
        ):
            promotion._write_exclusive(
                path,
                b"owned failure payload",
                label="synthetic failed exclusive write",
            )
        self.assertEqual(path.read_bytes(), b"owned failure payload")

    def test_anchored_write_rejects_parent_symlink_swap(self) -> None:
        parent = self.fixture.candidate_root / "anchored-parent"
        moved = self.fixture.candidate_root / "anchored-parent-moved"
        outside = self.fixture.candidate_root / "anchored-outside"
        parent.mkdir()
        outside.mkdir()
        target = parent / "target.bin"

        def swap_parent(_: Path) -> None:
            parent.rename(moved)
            try:
                create_directory_link(parent, outside)
            except OSError as exc:
                moved.rename(parent)
                raise unittest.SkipTest(
                    f"directory symlinks are unavailable: {exc}"
                ) from exc

        try:
            with (
                mock.patch.object(
                    promotion, "_before_output_open_hook", side_effect=swap_parent
                ),
                self.assertRaises((OSError, promotion.GoldenV3PromotionError)),
            ):
                promotion._write_exclusive(
                    target, b"must stay local", label="synthetic anchored output"
                )
            self.assertFalse((outside / target.name).exists())
        finally:
            if parent.is_symlink() or (
                hasattr(parent, "is_junction") and parent.is_junction()
            ):
                remove_directory_link(parent)
            if moved.exists() and not parent.exists():
                moved.rename(parent)

    def test_cleanup_rejects_swapped_parent_symlink(self) -> None:
        parent = self.fixture.candidate_root / "cleanup-parent"
        moved = self.fixture.candidate_root / "cleanup-parent-moved"
        outside = self.fixture.candidate_root / "cleanup-outside"
        parent.mkdir()
        outside.mkdir()
        path = parent / "target.bin"
        payload = b"outside sentinel"
        owned = promotion._write_exclusive(
            path, payload, label="synthetic swapped-parent cleanup"
        )
        parent.rename(moved)
        (outside / path.name).write_bytes(payload)
        try:
            create_directory_link(parent, outside)
        except OSError as exc:
            moved.rename(parent)
            raise unittest.SkipTest(
                f"directory symlinks are unavailable: {exc}"
            ) from exc
        try:
            promotion._cleanup_created([owned])
            self.assertEqual((outside / path.name).read_bytes(), payload)
            self.assertEqual((moved / path.name).read_bytes(), payload)
        finally:
            remove_directory_link(parent)
            moved.rename(parent)

    def test_manifest_commit_unknown_retains_exact_evidence(self) -> None:
        manifest_before = self.fixture.manifest.read_bytes()
        with (
            mock.patch.object(
                promotion,
                "_conditional_manifest_replace",
                side_effect=promotion.GoldenV3ManifestCommitUnknownError(
                    "synthetic unknown commit state"
                ),
            ),
            self.assertRaisesRegex(
                promotion.GoldenV3ManifestCommitUnknownError,
                "synthetic unknown commit state",
            ),
        ):
            self.fixture.promote()
        self.assertTrue(self.fixture.paths.raw.is_file())
        self.assertTrue(self.fixture.paths.master.is_file())
        self.assertTrue(self.fixture.paths.receipt.is_file())
        self.assertEqual(self.fixture.manifest.read_bytes(), manifest_before)

    def test_manifest_cas_target_swap_is_unknown_and_retains_both(self) -> None:
        manifest_before = self.fixture.manifest.read_bytes()
        detached = self.fixture.evidence_root / "detached-expected-manifest.json"
        concurrent = b'{"synthetic":"concurrent-manifest"}\n'
        primitive_name = (
            "_windows_replace_file" if os.name == "nt" else "_linux_exchange_names"
        )
        primitive = getattr(promotion, primitive_name)

        def swap_target_then_commit(*args: object) -> None:
            self.fixture.manifest.replace(detached)
            self.fixture.manifest.write_bytes(concurrent)
            primitive(*args)

        with (
            mock.patch.object(
                promotion, primitive_name, side_effect=swap_target_then_commit
            ),
            self.assertRaises(promotion.GoldenV3ManifestCommitUnknownError),
        ):
            self.fixture.promote()
        self.assertEqual(detached.read_bytes(), manifest_before)
        retained = list(
            self.fixture.evidence_root.glob(".production-manifest.json.k3-golden-v3-*")
        )
        self.assertTrue(any(item.read_bytes() == concurrent for item in retained))
        projected = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        self.assertEqual(projected["jobs"][0]["id"], promotion.JOB_ID)
        self.assertTrue(self.fixture.paths.raw.is_file())
        self.assertTrue(self.fixture.paths.master.is_file())
        self.assertTrue(self.fixture.paths.receipt.is_file())

    def test_manifest_cas_rejects_same_byte_identity_swap_before_commit(self) -> None:
        manifest_before = self.fixture.manifest.read_bytes()
        detached = self.fixture.evidence_root / "detached-same-byte-manifest.json"

        def swap_same_bytes(path: Path) -> None:
            path.replace(detached)
            path.write_bytes(manifest_before)

        with (
            mock.patch.object(
                promotion,
                "_before_manifest_replace_hook",
                side_effect=swap_same_bytes,
            ),
            self.assertRaisesRegex(
                promotion.GoldenV3PromotionError, "expected snapshot changed"
            ),
        ):
            self.fixture.promote()
        self.assertEqual(detached.read_bytes(), manifest_before)
        self.assertEqual(self.fixture.manifest.read_bytes(), manifest_before)
        retained = list(
            self.fixture.evidence_root.glob(
                ".production-manifest.json.k3-golden-v3-*.tmp"
            )
        )
        self.assertTrue(retained)

    def test_manifest_cas_rejects_bytes_only_mutation_before_commit(self) -> None:
        mutated = b'{"synthetic":"mutated-in-place"}\n'

        def mutate_bytes(path: Path) -> None:
            path.write_bytes(mutated)

        with (
            mock.patch.object(
                promotion, "_before_manifest_replace_hook", side_effect=mutate_bytes
            ),
            self.assertRaisesRegex(
                promotion.GoldenV3PromotionError, "expected snapshot changed"
            ),
        ):
            self.fixture.promote()
        self.assertEqual(self.fixture.manifest.read_bytes(), mutated)
        self.assertTrue(
            list(
                self.fixture.evidence_root.glob(
                    ".production-manifest.json.k3-golden-v3-*.tmp"
                )
            )
        )

    def test_manifest_cas_post_validation_same_byte_swap_is_unknown(self) -> None:
        manifest_before = self.fixture.manifest.read_bytes()
        detached = self.fixture.evidence_root / "detached-post-check-manifest.json"
        primitive_name = (
            "_windows_replace_file" if os.name == "nt" else "_linux_exchange_names"
        )
        primitive = getattr(promotion, primitive_name)

        def swap_same_bytes_then_commit(*args: object) -> None:
            self.fixture.manifest.replace(detached)
            self.fixture.manifest.write_bytes(manifest_before)
            primitive(*args)

        with (
            mock.patch.object(
                promotion, primitive_name, side_effect=swap_same_bytes_then_commit
            ),
            self.assertRaises(promotion.GoldenV3ManifestCommitUnknownError),
        ):
            self.fixture.promote()
        self.assertEqual(detached.read_bytes(), manifest_before)
        projected = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        self.assertEqual(projected["jobs"][0]["id"], promotion.JOB_ID)

    def test_manifest_cas_existing_lock_is_never_overwritten(self) -> None:
        lock = self.fixture.manifest.with_name(
            f".{self.fixture.manifest.name}.k3-golden-v3.lock"
        )
        sentinel = b"preexisting-lock"
        lock.write_bytes(sentinel)
        manifest_before = self.fixture.manifest.read_bytes()
        with self.assertRaisesRegex(
            promotion.GoldenV3PromotionError, "lock already exists"
        ):
            self.fixture.promote()
        self.assertEqual(lock.read_bytes(), sentinel)
        self.assertEqual(self.fixture.manifest.read_bytes(), manifest_before)

    def test_manifest_cas_existing_temporary_is_never_overwritten(self) -> None:
        temporary = self.fixture.manifest.with_name(
            f".{self.fixture.manifest.name}.k3-golden-v3-collision.tmp"
        )
        sentinel = b"preexisting-temporary"
        temporary.write_bytes(sentinel)
        ids = [mock.Mock(hex="collision"), mock.Mock(hex="backup")]
        manifest_before = self.fixture.manifest.read_bytes()
        with (
            mock.patch.object(promotion.uuid, "uuid4", side_effect=ids),
            self.assertRaises(FileExistsError),
        ):
            self.fixture.promote()
        self.assertEqual(temporary.read_bytes(), sentinel)
        self.assertEqual(self.fixture.manifest.read_bytes(), manifest_before)

    def test_manifest_cas_existing_backup_is_never_overwritten(self) -> None:
        backup = self.fixture.manifest.with_name(
            f".{self.fixture.manifest.name}.k3-golden-v3-backup-collision.backup"
        )
        sentinel = b"unrelated-preexisting-backup"
        ids = [mock.Mock(hex="temporary-safe"), mock.Mock(hex="backup-collision")]
        manifest_before = self.fixture.manifest.read_bytes()

        def collide_backup(_: Path) -> None:
            backup.write_bytes(sentinel)

        with (
            mock.patch.object(promotion.uuid, "uuid4", side_effect=ids),
            mock.patch.object(
                promotion,
                "_before_manifest_replace_hook",
                side_effect=collide_backup,
            ),
            self.assertRaises(FileExistsError),
        ):
            self.fixture.promote()
        self.assertEqual(backup.read_bytes(), sentinel)
        self.assertEqual(self.fixture.manifest.read_bytes(), manifest_before)

    def test_manifest_cas_primitive_failure_retains_projected_debris(self) -> None:
        primitive_name = (
            "_windows_replace_file" if os.name == "nt" else "_linux_exchange_names"
        )
        manifest_before = self.fixture.manifest.read_bytes()
        with (
            mock.patch.object(
                promotion,
                primitive_name,
                side_effect=OSError("synthetic pre-commit primitive failure"),
            ),
            self.assertRaisesRegex(OSError, "synthetic pre-commit primitive failure"),
        ):
            self.fixture.promote()
        self.assertEqual(self.fixture.manifest.read_bytes(), manifest_before)
        retained = list(
            self.fixture.evidence_root.glob(
                ".production-manifest.json.k3-golden-v3-*.tmp"
            )
        )
        self.assertTrue(retained)
        self.assertTrue(
            any(promotion.JOB_ID.encode() in item.read_bytes() for item in retained)
        )

    def test_manifest_cas_third_state_is_unknown_and_retained(self) -> None:
        detached = self.fixture.evidence_root / "detached-third-state-manifest.json"
        third_state = b'{"synthetic":"third-state"}\n'
        primitive_name = (
            "_windows_replace_file" if os.name == "nt" else "_linux_exchange_names"
        )

        def install_third_state_then_fail(*_: object) -> None:
            self.fixture.manifest.replace(detached)
            self.fixture.manifest.write_bytes(third_state)
            raise OSError("synthetic indeterminate primitive failure")

        with (
            mock.patch.object(
                promotion, primitive_name, side_effect=install_third_state_then_fail
            ),
            self.assertRaises(promotion.GoldenV3ManifestCommitUnknownError),
        ):
            self.fixture.promote()
        self.assertEqual(self.fixture.manifest.read_bytes(), third_state)
        retained = list(
            self.fixture.evidence_root.glob(
                ".production-manifest.json.k3-golden-v3-*.tmp"
            )
        )
        self.assertTrue(
            any(promotion.JOB_ID.encode() in item.read_bytes() for item in retained)
        )

    def test_manifest_cas_ancestor_swap_never_touches_outside(self) -> None:
        parent = self.fixture.evidence_root / "manifest-parent"
        moved = self.fixture.evidence_root / "manifest-parent-moved"
        outside = self.fixture.evidence_root / "manifest-outside"
        parent.mkdir()
        outside.mkdir()
        manifest = parent / "manifest.json"
        outside_manifest = outside / manifest.name
        original = b'{"jobs":[]}\n'
        sentinel = b'{"outside":"sentinel"}\n'
        manifest.write_bytes(original)
        outside_manifest.write_bytes(sentinel)
        expected = promotion._bind(manifest, label="synthetic manifest CAS ancestor")
        swapped = False

        def swap_parent(_: Path) -> None:
            nonlocal swapped
            try:
                parent.rename(moved)
                create_directory_link(parent, outside)
                swapped = True
            except OSError:
                if moved.exists() and not parent.exists():
                    moved.rename(parent)

        try:
            with mock.patch.object(
                promotion, "_before_manifest_replace_hook", side_effect=swap_parent
            ):
                if os.name == "nt":
                    result = promotion._conditional_manifest_replace(
                        manifest, {"jobs": [{"id": "projected"}]}, expected=expected
                    )
                    self.assertEqual(result.cleanup_status, "debris")
                else:
                    with self.assertRaises(
                        promotion.GoldenV3ManifestCommitUnknownError
                    ):
                        promotion._conditional_manifest_replace(
                            manifest,
                            {"jobs": [{"id": "projected"}]},
                            expected=expected,
                        )
            self.assertEqual(outside_manifest.read_bytes(), sentinel)
        finally:
            if swapped:
                remove_directory_link(parent)
                moved.rename(parent)

    def test_manifest_cas_confirms_post_replace_base_exception(self) -> None:
        if os.name == "nt":
            primitive_name = "_windows_replace_file"
        else:
            primitive_name = "_linux_exchange_names"
        primitive = getattr(promotion, primitive_name)

        def commit_then_interrupt(*args: object) -> None:
            primitive(*args)
            raise KeyboardInterrupt("synthetic post-replace interruption")

        with mock.patch.object(
            promotion, primitive_name, side_effect=commit_then_interrupt
        ):
            result = self.fixture.promote()
        self.assertEqual(result["status"], "accepted")
        self.assertTrue(self.fixture.paths.raw.is_file())
        self.assertTrue(self.fixture.paths.master.is_file())
        self.assertTrue(self.fixture.paths.receipt.is_file())
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["jobs"][0]["id"], promotion.JOB_ID)

    def test_commit_boundary_base_exception_retains_exact_evidence(self) -> None:
        def commit_then_interrupt(
            path: Path,
            value: dict[str, object],
            *,
            expected: promotion.BoundArtifact,
        ) -> None:
            self.assertEqual(path.resolve(), expected.path)
            path.write_bytes(promotion._canonical_json(value))
            raise KeyboardInterrupt("synthetic post-commit interruption")

        with (
            mock.patch.object(
                promotion,
                "_conditional_manifest_replace",
                side_effect=commit_then_interrupt,
            ),
            self.assertRaisesRegex(
                KeyboardInterrupt, "synthetic post-commit interruption"
            ),
        ):
            self.fixture.promote()
        self.assertTrue(self.fixture.paths.raw.is_file())
        self.assertTrue(self.fixture.paths.master.is_file())
        self.assertTrue(self.fixture.paths.receipt.is_file())
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["jobs"][0]["id"], promotion.JOB_ID)

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

    def test_embedded_cross_profile_seal_tamper_retains_fail_closed_evidence(
        self,
    ) -> None:
        summary = self.fixture.seal_summaries[0]
        seal = json.loads(summary["payload_utf8"])
        selected = next(
            item
            for item in seal["candidates"]
            if item["candidate_id"] == self.fixture.candidate_id
        )
        selected["sha256"] = "0" * 64
        payload = promotion.balanced_open_derivation.canonical_output_seal_json(seal)
        summary["payload_utf8"] = payload.decode("utf-8")
        summary["sha256"] = hashlib.sha256(payload).hexdigest()
        with self.assertRaisesRegex(
            promotion.GoldenV3PromotionError,
            "embedded cross-profile generation seals disagree",
        ):
            self.fixture.promote()
        self.assertTrue(self.fixture.paths.raw.is_file())
        self.assertTrue(self.fixture.paths.master.is_file())
        self.assertTrue(self.fixture.paths.receipt.is_file())
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["jobs"], [])

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

    def test_phase5_rejects_strict_report_json_type_smuggling(self) -> None:
        self.fixture.promote()
        original_report = copy.deepcopy(self.fixture.strict_report)
        original_receipt = json.loads(
            self.fixture.paths.receipt.read_text(encoding="utf-8")
        )
        original_manifest = json.loads(
            self.fixture.manifest.read_text(encoding="utf-8")
        )
        mutations = (
            ("passed must be True", lambda report: report.__setitem__("passed", 1)),
            (
                "promotion_or_golden_designation_performed must be False",
                lambda report: report.__setitem__(
                    "promotion_or_golden_designation_performed", 0
                ),
            ),
            (
                "candidate binding does not match",
                lambda report: report["candidate"].__setitem__(
                    "bytes", float(report["candidate"]["bytes"])
                ),
            ),
        )
        for expected_error, mutate in mutations:
            with self.subTest(field=expected_error):
                report = copy.deepcopy(original_report)
                receipt = copy.deepcopy(original_receipt)
                manifest = copy.deepcopy(original_manifest)
                mutate(report)
                self.fixture.strict_report_path.write_bytes(
                    promotion.load_authority().strict_module.canonical_json(report)
                )
                report_sha = digest(self.fixture.strict_report_path)
                receipt["strict_audit_report"]["sha256"] = report_sha
                self.fixture._write_json(self.fixture.paths.receipt, receipt)
                for item in manifest["jobs"][0]["inputs"]:
                    if item["role"] == promotion.V3_STRICT_REPORT_ROLE:
                        item["sha256"] = report_sha
                    elif item["role"] == promotion.V3_ACCEPTANCE_RECEIPT_ROLE:
                        item["sha256"] = digest(self.fixture.paths.receipt)
                self.fixture._write_json(self.fixture.manifest, manifest)
                with self.assertRaisesRegex(phase5.Phase5BuildError, expected_error):
                    self.fixture.verify_phase5()

    def test_phase5_rejects_equal_float_receipt_fields_after_coherent_rehash(
        self,
    ) -> None:
        self.fixture.promote()
        original_receipt = json.loads(
            self.fixture.paths.receipt.read_text(encoding="utf-8")
        )
        original_manifest = json.loads(
            self.fixture.manifest.read_text(encoding="utf-8")
        )
        mutations = (
            (
                "candidate byte count changed",
                lambda receipt: receipt["candidate"].__setitem__(
                    "bytes", float(receipt["candidate"]["bytes"])
                ),
            ),
            (
                "review summary changed",
                lambda receipt: receipt["reviews"][0].__setitem__(
                    "score", float(receipt["reviews"][0]["score"])
                ),
            ),
            (
                "frozen header changed",
                lambda receipt: receipt.__setitem__("acceptance_threshold", 94.0),
            ),
        )
        for expected_error, mutate in mutations:
            with self.subTest(field=expected_error):
                receipt = copy.deepcopy(original_receipt)
                manifest = copy.deepcopy(original_manifest)
                mutate(receipt)
                self.fixture._write_json(self.fixture.paths.receipt, receipt)
                receipt_input = next(
                    item
                    for item in manifest["jobs"][0]["inputs"]
                    if item["role"] == promotion.V3_ACCEPTANCE_RECEIPT_ROLE
                )
                receipt_input["sha256"] = digest(self.fixture.paths.receipt)
                self.fixture._write_json(self.fixture.manifest, manifest)
                with self.assertRaisesRegex(phase5.Phase5BuildError, expected_error):
                    self.fixture.verify_phase5()

    def test_phase5_rejects_noncanonical_receipt_after_coherent_rehash(self) -> None:
        self.fixture.promote()
        receipt = json.loads(self.fixture.paths.receipt.read_text(encoding="utf-8"))
        self.fixture.paths.receipt.write_bytes(
            json.dumps(receipt, separators=(",", ":")).encode("utf-8")
        )
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        receipt_input = next(
            item
            for item in manifest["jobs"][0]["inputs"]
            if item["role"] == promotion.V3_ACCEPTANCE_RECEIPT_ROLE
        )
        receipt_input["sha256"] = digest(self.fixture.paths.receipt)
        self.fixture._write_json(self.fixture.manifest, manifest)
        with self.assertRaisesRegex(
            phase5.Phase5BuildError, "receipt bytes are not canonical"
        ):
            self.fixture.verify_phase5()

    def test_phase5_rejects_promotion_implementation_binding_tamper(self) -> None:
        self.fixture.promote()
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        implementation = next(
            item
            for item in manifest["jobs"][0]["inputs"]
            if item["role"] == promotion.V3_PROMOTION_IMPLEMENTATION_ROLE
        )
        implementation["sha256"] = "0" * 64
        self.fixture._write_json(self.fixture.manifest, manifest)
        with self.assertRaisesRegex(
            phase5.Phase5BuildError, "promotion implementation changed"
        ):
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
        receipt["candidate_id"] = "E150-M550"
        for summary in receipt["generation_seals"]:
            seal = json.loads(summary["payload_utf8"])
            forged = next(
                item
                for item in seal["candidates"]
                if item["candidate_id"] == "E150-M550"
            )
            forged["sha256"] = self.fixture.candidate_sha256
            forged["bytes"] = self.fixture.candidate.stat().st_size
            payload = promotion.balanced_open_derivation.canonical_output_seal_json(
                seal
            )
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
    def test_phase5_import_does_not_execute_legacy_v2_auditor(self) -> None:
        script = f"""
import sys
sys.path.insert(0, {str(SCRIPT_DIR)!r})
import build_phase5_assets as phase5
assert phase5._golden_v2_promotion is None
assert 'promote_style_candidate_k3_golden_v2' not in sys.modules
assert 'audit_style_candidate_k3_golden_v2' not in sys.modules
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

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
