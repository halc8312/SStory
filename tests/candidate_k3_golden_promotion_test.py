from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import build_phase5_assets as phase5  # noqa: E402
import create_qa_report  # noqa: E402
import promote_style_candidate_k3_golden as promotion  # noqa: E402
from release_bound_artifact import bind_file  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def artifact(path: Path) -> dict[str, object]:
    with Image.open(path) as image:
        image.load()
        return {
            "path": relative(path),
            "sha256": digest(path),
            "bytes": path.stat().st_size,
            "mode": image.mode,
            "size": list(image.size),
        }


class PromotionFixture:
    def __init__(self) -> None:
        source_parent = REPO_ROOT / "tmp" / "map-production"
        source_parent.mkdir(parents=True, exist_ok=True)
        self.source_temp = tempfile.TemporaryDirectory(
            prefix="k3-golden-source-test-", dir=source_parent
        )
        self.persistent_temp = tempfile.TemporaryDirectory(
            prefix=".k3-golden-promotion-test-", dir=REPO_ROOT
        )
        self.source_root = Path(self.source_temp.name)
        self.root = Path(self.persistent_temp.name)
        self.manifest_path = self.root / "production-manifest.json"
        self.manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "project_id": "k3-promotion-test",
                    "map_id": "eternal-arcadia",
                    "coordinate_system": "EA-WORLD-1",
                    "jobs": [],
                }
            ),
            encoding="utf-8",
        )
        self.paths = promotion.PromotionPaths(
            manifest=self.manifest_path,
            raw=self.root / "candidates" / "k3-raw.png",
            final=self.root / "candidates" / "k3-final.png",
            receipt=self.root / "prompts" / "k3-receipt.json",
            audit=self.root / "qa" / "automated" / "k3-audit.json",
            v19_parent=self.root / "controls" / "v19.png",
            v18_lineage=self.root / "controls" / "v18-rejected.png",
            masks_dir=self.root / "qa" / "masks",
            evidence_dir=self.root / "qa" / "evidence",
            v19_receipt=self.root / "prompts" / "v19-normalized.json",
            lineage_dir=self.root / "controls" / "lineage",
        )
        self.v19 = self.source_root / "parent-v19.png"
        Image.new("RGB", promotion.EXPECTED_SIZE, (141, 120, 85)).save(self.v19)
        self.v18 = (
            REPO_ROOT
            / "world/map-production/style-assets/k3-v18-reconstruction-base.png"
        )
        if digest(self.v18) != promotion.REJECTED_V18_SHA256:
            raise AssertionError("frozen v18 test lineage is missing or stale")

        lineage_root = self.root / "lineage-contract"
        lineage_root.mkdir(parents=True, exist_ok=True)
        self.v19_builder = lineage_root / "build-v19.py"
        self.v19_builder.write_text(
            "import argparse, hashlib, json, shutil\n"
            "p=argparse.ArgumentParser(); p.add_argument('--replay-contract', required=True); p.add_argument('--output', required=True); a=p.parse_args()\n"
            "c=json.load(open(a.replay_contract, encoding='utf-8'))\n"
            "m=c['control_atlas_metadata']; assert hashlib.sha256(open(m['path'], 'rb').read()).hexdigest() == m['sha256']\n"
            "b=c['canonical_body_control']; assert hashlib.sha256(open(b['path'], 'rb').read()).hexdigest() == b['sha256']\n"
            "shutil.copyfile(c['generated_layout_control']['path'], a.output)\n",
            encoding="utf-8",
        )
        self.layout_control = lineage_root / "layout-control.png"
        self.layout_control.write_bytes(self.v19.read_bytes())
        self.control_atlas_metadata = lineage_root / "control-atlas-metadata.json"
        self.control_atlas_metadata.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "id": "synthetic-v52-control-atlas-metadata",
                    "guide_sha256": "1" * 64,
                    "body_order": [f"body-{index:02d}" for index in range(1, 9)],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.canonical_body_control = lineage_root / "canonical-body-control.png"
        Image.new("L", promotion.EXPECTED_SIZE, 32).save(
            self.canonical_body_control
        )
        self.imagegen_prompt = lineage_root / "imagegen-prompt.txt"
        self.imagegen_prompt.write_text("exact synthetic ImageGen prompt\n", encoding="utf-8")
        self.authority_paths: dict[str, Path] = {}
        for role in sorted(promotion.REQUIRED_V19_AUTHORITY_ROLES):
            path = lineage_root / f"{role}.authority.txt"
            path.write_text(f"synthetic authority: {role}\n", encoding="utf-8")
            self.authority_paths[role] = path
        metadata_document = json.loads(
            self.control_atlas_metadata.read_text(encoding="utf-8")
        )
        metadata_document["guide"] = {
            "path": relative(self.authority_paths["v52-control-atlas"]),
            "sha256": digest(self.authority_paths["v52-control-atlas"]),
        }
        metadata_document["canonical_body_control"] = {
            "path": relative(self.canonical_body_control),
            "sha256": digest(self.canonical_body_control),
        }
        self.control_atlas_metadata.write_text(
            json.dumps(metadata_document) + "\n", encoding="utf-8"
        )
        self.generation_receipt = lineage_root / "generation-receipt.json"
        self.generation_receipt.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "status": "generated",
                    "prompt": {
                        "path": relative(self.imagegen_prompt),
                        "sha256": digest(self.imagegen_prompt),
                    },
                    "references_in_call_order": [
                        {
                            "role": "absolute-coordinate-and-semantic-authority-v18",
                            "path": relative(self.v18),
                            "sha256": digest(self.v18),
                        },
                        {
                            "role": "exact-eight-affine-control-atlas-v52",
                            "path": relative(
                                self.authority_paths[
                                    "v52-control-atlas"
                                ]
                            ),
                            "sha256": digest(
                                self.authority_paths[
                                    "v52-control-atlas"
                                ]
                            ),
                        },
                        {
                            "role": "fine-copperplate-material-reference-v38",
                            "path": relative(
                                self.authority_paths[
                                    "v55-copperplate-material-reference"
                                ]
                            ),
                            "sha256": digest(
                                self.authority_paths[
                                    "v55-copperplate-material-reference"
                                ]
                            ),
                        },
                        {
                            "role": "palette-and-parchment-authority-h4",
                            "path": relative(
                                self.authority_paths[
                                    "v55-palette-parchment-reference"
                                ]
                            ),
                            "sha256": digest(
                                self.authority_paths[
                                    "v55-palette-parchment-reference"
                                ]
                            ),
                        },
                    ],
                    "output": {
                        "path": relative(self.layout_control),
                        "sha256": digest(self.layout_control),
                    },
                    "root_vision_review": {
                        "path": relative(
                            self.authority_paths["v55-root-vision-review"]
                        ),
                        "sha256": digest(
                            self.authority_paths["v55-root-vision-review"]
                        ),
                    },
                    "control_atlas_metadata": {
                        "path": relative(self.control_atlas_metadata),
                        "sha256": digest(self.control_atlas_metadata),
                    },
                    "canonical_body_control": {
                        "path": relative(self.canonical_body_control),
                        "sha256": digest(self.canonical_body_control),
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.v19_receipt = lineage_root / "v19-provenance.json"
        self.source_contract = promotion.PromotionSourceContract(
            v20_root=self.source_root,
            v19_candidate=self.v19,
            v19_receipt=self.v19_receipt,
            v19_builder=self.v19_builder,
            generated_layout_control=self.layout_control,
            control_atlas_metadata=self.control_atlas_metadata,
            canonical_body_control=self.canonical_body_control,
            imagegen_prompt=self.imagegen_prompt,
            generation_receipt=self.generation_receipt,
            test_only_allow_dynamic_temp_root=True,
            test_only_expected_authorities=tuple(
                (role, path, digest(path))
                for role, path in self.authority_paths.items()
            ),
        )
        self.v19_receipt.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "id": promotion.EXACT_V19_RECEIPT_ID,
                    "status": promotion.EXACT_V19_STATUS,
                    "authority_inventory_complete": True,
                    "candidate": artifact(self.v19),
                    "base_v18": artifact(self.v18),
                    "reconstruction_builder": {
                        "path": relative(self.v19_builder),
                        "sha256": digest(self.v19_builder),
                    },
                    "generated_layout_control": {
                        "path": relative(self.layout_control),
                        "sha256": digest(self.layout_control),
                    },
                    "control_atlas_metadata": {
                        "path": relative(self.control_atlas_metadata),
                        "sha256": digest(self.control_atlas_metadata),
                    },
                    "canonical_body_control": {
                        "path": relative(self.canonical_body_control),
                        "sha256": digest(self.canonical_body_control),
                    },
                    "imagegen_prompt": {
                        "path": relative(self.imagegen_prompt),
                        "sha256": digest(self.imagegen_prompt),
                    },
                    "generation_receipt": {
                        "path": relative(self.generation_receipt),
                        "sha256": digest(self.generation_receipt),
                    },
                    "authorities": [
                        {
                            "role": role,
                            "path": relative(path),
                            "sha256": digest(path),
                        }
                        for role, path in self.authority_paths.items()
                    ],
                    "replay": {
                        "interface": promotion.V19_REPLAY_INTERFACE,
                        "byte_exact": True,
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        expected_v20 = promotion._v20_expected_paths(self.source_contract)
        self.candidate = expected_v20["candidate"]
        Image.new("RGB", promotion.EXPECTED_SIZE, (142, 121, 86)).save(self.candidate)

        source_artifacts: dict[str, dict[str, object]] = {
            "candidate": artifact(self.candidate)
        }
        for key in sorted(promotion.REQUIRED_V20_ARTIFACTS - {"candidate"}):
            image_path = expected_v20[key]
            mode = "L" if key in {"permission", "alpha", "actual_change"} else "RGB"
            color = 255 if mode == "L" else (140, 120, 90)
            Image.new(mode, (24, 16), color).save(image_path)
            source_artifacts[key] = artifact(image_path)

        def source_record(raw: str) -> dict[str, str]:
            path = REPO_ROOT / raw
            return {"path": raw, "sha256": digest(path)}

        donor = dict(promotion.EXACT_FIELDS_DONOR)
        self.receipt = {
            "schema_version": "1.0.0",
            "id": promotion.EXACT_V20_RECEIPT_ID,
            "status": promotion.EXACT_V20_STATUS,
            "temporary_review_only": True,
            "persistent_candidate_emitted": False,
            "golden_accepted": False,
            "v19_input": {
                "path": relative(self.v19),
                "expected_sha256": digest(self.v19),
                "actual_sha256": digest(self.v19),
                "caller_bound_at_invocation": True,
                "provenance_receipt": {
                    "path": relative(self.v19_receipt),
                    "sha256": digest(self.v19_receipt),
                },
            },
            "lineage": {
                "v18_reference": {
                    "path": relative(self.v18),
                    "sha256": digest(self.v18),
                },
                "v19_changed_pixels_vs_v18": 1,
                "v19_changed_pixels_outside_highland_permission": 0,
                "v18_exact_carry_differences": {},
            },
            **{
                key: source_record(path)
                for key, path in promotion.EXACT_SOURCE_PATHS.items()
            },
            "fields_donor": {
                **donor,
                "validated_by_existing_k3_donor_contract": True,
            },
            "construction": {
                "semantic_change": "legacy field-parcel margin cadence cleanup only",
                "global_transform_applied": False,
            },
            "metrics": {"identity": {"actual_change_pixels": 36676}},
            "automated_gates": {
                key: True for key in sorted(promotion.REQUIRED_V20_GATES)
            },
            "failed_gates": [],
            "artifacts": source_artifacts,
            "vision_handoff": {
                "required": True,
                "decision_authority": "Root Vision",
                "acceptance_threshold": 94,
                "immediate_failure_policy": "zero immediate failures",
                "review_views": [],
                "candidate_must_not_be_promoted_before_acceptance": True,
            },
        }
        self.source_receipt = (
            self.source_root
            / f"{promotion.V20_STEM}.provenance-receipt.json"
        )
        self.persist_source_receipt()

    def persist_source_receipt(self) -> None:
        self.source_receipt.write_text(
            json.dumps(self.receipt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def persist_v19_receipt(self, receipt: dict[str, object]) -> None:
        self.v19_receipt.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.receipt["v19_input"]["provenance_receipt"]["sha256"] = digest(
            self.v19_receipt
        )
        self.persist_source_receipt()

    def persist_generation_receipt(self, receipt: dict[str, object]) -> None:
        self.generation_receipt.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        v19_receipt = json.loads(
            self.v19_receipt.read_text(encoding="utf-8")
        )
        v19_receipt["generation_receipt"]["sha256"] = digest(
            self.generation_receipt
        )
        self.persist_v19_receipt(v19_receipt)

    def cleanup(self) -> None:
        self.persistent_temp.cleanup()
        self.source_temp.cleanup()

    @staticmethod
    def fake_audit(**values):
        return {
            "schema_version": "1.0.0",
            "id": "style-candidate-k-v3-semantic-cleanup-automated-report",
            "job_id": promotion.JOB_ID,
            "status": "passed",
            "image_path": values["final_artifact"]["path"],
            "image_sha256": values["final_artifact"]["sha256"],
            "decision_authority": False,
            "acceptance_inferred": False,
            "golden_accepted": False,
            "raw": values["raw_artifact"],
            "candidate": values["final_artifact"],
            "provenance_receipt": values["normalized_receipt"],
            "source_temporary_receipt_sha256": values[
                "source_receipt_sha256"
            ],
            "automated_gates": {"synthetic-persistent-audit": True},
            "failed_gates": [],
        }

    def prepare(self) -> dict:
        return promotion.prepare_promotion(
            source_receipt_path=self.source_receipt,
            authorized_by="Promotion Test",
            paths=self.paths,
            source_contract=self.source_contract,
            audit_builder=self.fake_audit,
        )

    def review(self, path: Path, reviewer: str) -> dict:
        report = create_qa_report.build_report(
            promotion.JOB_ID,
            relative(self.paths.final),
            reviewer=reviewer,
            golden=True,
            threshold=94,
            image_sha256=digest(self.paths.final),
            review_mode="blind-independent",
        )
        report["status"] = "complete"
        report["decision"] = "accepted"
        report["summary"] = "Complete blind review of the exact candidate bytes."
        for view in report["review_views"]:
            view["complete"] = True
            view["evidence"] = "inspected"
        for failure in report["immediate_failures"]:
            failure["detected"] = False
            failure["evidence"] = "not detected"
        for score in report["scores"]:
            score["score"] = score["maximum"]
            score["notes"] = "meets contract"
        report["total_score"] = 100
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report), encoding="utf-8")
        return report


class CandidateK3GoldenPromotionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = PromotionFixture()

    def tearDown(self) -> None:
        self.fixture.cleanup()

    def test_exact_v19_authority_roles_and_known_source_hashes_are_closed(self) -> None:
        self.assertEqual(
            promotion.REQUIRED_V19_AUTHORITY_ROLES,
            {
                "canonical-k3-spec",
                "v55-root-vision-review",
                "v55-robust-recipe-verification",
                "v52-control-atlas",
                "v55-copperplate-material-reference",
                "v55-palette-parchment-reference",
            },
        )
        self.assertEqual(
            set(promotion.EXPECTED_V19_AUTHORITY_ARTIFACTS),
            promotion.REQUIRED_V19_AUTHORITY_ROLES,
        )
        for role, record in promotion.EXPECTED_V19_AUTHORITY_ARTIFACTS.items():
            with self.subTest(role=role):
                path = REPO_ROOT / record["path"]
                self.assertTrue(path.is_file())
                self.assertEqual(digest(path), record["sha256"])

        fixed_sources = {
            "reconstruction_builder": (
                promotion.DEFAULT_SOURCE_CONTRACT.v19_builder
            ),
            "generated_layout_control": (
                promotion.DEFAULT_SOURCE_CONTRACT.generated_layout_control
            ),
            "control_atlas_metadata": (
                promotion.DEFAULT_SOURCE_CONTRACT.control_atlas_metadata
            ),
            "canonical_body_control": (
                promotion.DEFAULT_SOURCE_CONTRACT.canonical_body_control
            ),
            "imagegen_prompt": promotion.DEFAULT_SOURCE_CONTRACT.imagegen_prompt,
            "generation_receipt": (
                promotion.DEFAULT_SOURCE_CONTRACT.generation_receipt
            ),
        }
        self.assertEqual(
            set(fixed_sources), set(promotion.EXPECTED_V19_FIXED_SOURCE_SHA256)
        )
        for role, path in fixed_sources.items():
            with self.subTest(fixed_source=role):
                self.assertTrue(path.is_file())
                self.assertEqual(
                    digest(path),
                    promotion.EXPECTED_V19_FIXED_SOURCE_SHA256[role],
                )
        known_sources = {
            "013320af2f3296200a7d0b179e3a495f1e7905462213a6c645d85669dec02882": (
                REPO_ROOT
                / "world/map-production/style-assets/k3-v18-reconstruction-base.png"
            ),
            "67b9ffeca574ca144e8c54fc67b7f5c2757a02422b1fab73135efb89ad8cc156": (
                REPO_ROOT
                / "world/map-production/style-assets/highland-calm-spacing-reference-v45.png"
            ),
            "98aa5a14d7b1c2ba413e604403057ec05d0787cfd35d3c9dd770e88b850488aa": (
                REPO_ROOT
                / "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/"
                "highland-context-sparse-ridgeline-v20.png"
            ),
            "c7fcd3da5fba6fe08f10fd1e0fe16bdb2884a0a04386de828f923d660de8f1a2": (
                REPO_ROOT
                / "world/map-production/style-assets/highland-detail-exemplar-v1.png"
            ),
            "b4fc951af5d29c78bb98b5ee5007395b5fc3c1addc7070d76ac8074545259837": (
                REPO_ROOT
                / "world/map-production/candidates/"
                "style-candidate-h-v4-plan-view-golden-board.png"
            ),
            "2ae715fc2800a03adde89a26bd3d663f1bafe179ed845cef09dd616ed1453d3f": (
                REPO_ROOT
                / "world/map-production/style-assets/"
                "k3-v55-topographic-contour-atlas.png"
            ),
            "c168f1419d04ffaff313433064bab2b12844041e3845540c8bb6e29c2ef317c4": (
                REPO_ROOT
                / "world/map-production/controls/"
                "style-candidate-k-v3-semantic-cleanup/"
                "k3-v52-eight-ridge-control-atlas.png"
            ),
        }
        self.assertEqual(
            set(promotion.KNOWN_NON_GOLDEN_SOURCE_SHA256),
            set(known_sources),
        )
        for expected_sha256, path in known_sources.items():
            with self.subTest(path=path.name):
                binding = bind_file(path, label=f"known source {path.name}")
                self.assertEqual(binding.sha256, expected_sha256)
                with self.assertRaisesRegex(
                    promotion.K3GoldenPromotionError,
                    "known non-Golden/source candidate bytes",
                ):
                    promotion._assert_candidate_is_not_known_non_golden_source(
                        binding
                    )

    def test_prepare_requires_exact_v19_authority_role_set(self) -> None:
        original_manifest = self.fixture.manifest_path.read_bytes()
        original = json.loads(
            self.fixture.v19_receipt.read_text(encoding="utf-8")
        )
        cases: list[dict[str, object]] = []

        missing = copy.deepcopy(original)
        missing["authorities"] = missing["authorities"][:-1]
        cases.append(missing)

        extra = copy.deepcopy(original)
        extra["authorities"].append(
            {
                "role": "undeclared-v19-authority",
                "path": relative(
                    self.fixture.authority_paths["canonical-k3-spec"]
                ),
                "sha256": digest(
                    self.fixture.authority_paths["canonical-k3-spec"]
                ),
            }
        )
        cases.append(extra)

        for receipt in cases:
            with self.subTest(
                roles=[record["role"] for record in receipt["authorities"]]
            ):
                self.fixture.persist_v19_receipt(receipt)
                with self.assertRaisesRegex(
                    promotion.K3GoldenPromotionError,
                    "authority roles must match the exact builder contract",
                ):
                    self.fixture.prepare()
                self.assertEqual(
                    self.fixture.manifest_path.read_bytes(), original_manifest
                )
                self.assertFalse(self.fixture.paths.raw.exists())

    def test_prepare_requires_exact_v19_authority_paths_and_hashes(self) -> None:
        original_manifest = self.fixture.manifest_path.read_bytes()
        original = json.loads(
            self.fixture.v19_receipt.read_text(encoding="utf-8")
        )
        cases: list[dict[str, object]] = []

        wrong_path = copy.deepcopy(original)
        target = next(
            record
            for record in wrong_path["authorities"]
            if record["role"] == "v52-control-atlas"
        )
        substitute = self.fixture.authority_paths["canonical-k3-spec"]
        target["path"] = relative(substitute)
        target["sha256"] = digest(substitute)
        cases.append(wrong_path)

        wrong_sha = copy.deepcopy(original)
        target = next(
            record
            for record in wrong_sha["authorities"]
            if record["role"] == "v55-root-vision-review"
        )
        target["sha256"] = "0" * 64
        cases.append(wrong_sha)

        for receipt in cases:
            with self.subTest(
                authorities=[
                    (record["role"], record["path"], record["sha256"])
                    for record in receipt["authorities"]
                ]
            ):
                self.fixture.persist_v19_receipt(receipt)
                with self.assertRaisesRegex(
                    promotion.K3GoldenPromotionError,
                    "exact canonical path/SHA-256",
                ):
                    self.fixture.prepare()
                self.assertEqual(
                    self.fixture.manifest_path.read_bytes(), original_manifest
                )
                self.assertFalse(self.fixture.paths.raw.exists())

    def test_generation_receipt_rejects_undeclared_nested_binding(self) -> None:
        original_manifest = self.fixture.manifest_path.read_bytes()
        generation = json.loads(
            self.fixture.generation_receipt.read_text(encoding="utf-8")
        )
        undeclared = self.fixture.root / "lineage-contract" / "undeclared.txt"
        undeclared.write_text("not a declared v19 authority\n", encoding="utf-8")
        generation["undeclared_input"] = {
            "path": relative(undeclared),
            "sha256": digest(undeclared),
        }
        self.fixture.persist_generation_receipt(generation)

        with self.assertRaisesRegex(
            promotion.K3GoldenPromotionError,
            "generation receipt contains undeclared nested authority",
        ):
            self.fixture.prepare()
        self.assertEqual(self.fixture.manifest_path.read_bytes(), original_manifest)
        self.assertFalse(self.fixture.paths.raw.exists())

    def test_control_metadata_rejects_undeclared_nested_binding(self) -> None:
        original_manifest = self.fixture.manifest_path.read_bytes()
        metadata = json.loads(
            self.fixture.control_atlas_metadata.read_text(encoding="utf-8")
        )
        undeclared = self.fixture.root / "lineage-contract" / "undeclared.txt"
        undeclared.write_text("not a declared control authority\n", encoding="utf-8")
        metadata["undeclared_input"] = {
            "path": relative(undeclared),
            "sha256": digest(undeclared),
        }
        self.fixture.control_atlas_metadata.write_text(
            json.dumps(metadata) + "\n", encoding="utf-8"
        )
        generation = json.loads(
            self.fixture.generation_receipt.read_text(encoding="utf-8")
        )
        generation["control_atlas_metadata"]["sha256"] = digest(
            self.fixture.control_atlas_metadata
        )
        self.fixture.persist_generation_receipt(generation)
        receipt = json.loads(
            self.fixture.v19_receipt.read_text(encoding="utf-8")
        )
        receipt["control_atlas_metadata"]["sha256"] = digest(
            self.fixture.control_atlas_metadata
        )
        self.fixture.persist_v19_receipt(receipt)

        with self.assertRaisesRegex(
            promotion.K3GoldenPromotionError,
            "control-atlas metadata contains undeclared nested authority",
        ):
            self.fixture.prepare()
        self.assertEqual(self.fixture.manifest_path.read_bytes(), original_manifest)
        self.assertFalse(self.fixture.paths.raw.exists())

    def test_prepare_rejects_control_metadata_and_generated_source_tamper(self) -> None:
        original_manifest = self.fixture.manifest_path.read_bytes()
        for label, target in (
            ("control-atlas metadata", self.fixture.control_atlas_metadata),
            ("canonical body control", self.fixture.canonical_body_control),
            ("generated layout control", self.fixture.layout_control),
        ):
            original = target.read_bytes()
            with self.subTest(label=label):
                target.write_bytes(original + b"tampered")
                try:
                    with self.assertRaisesRegex(
                        promotion.K3GoldenPromotionError,
                        "SHA-256 mismatch",
                    ):
                        self.fixture.prepare()
                finally:
                    target.write_bytes(original)
                self.assertEqual(
                    self.fixture.manifest_path.read_bytes(), original_manifest
                )
                self.assertFalse(self.fixture.paths.raw.exists())

    def test_prepare_stops_at_automated_qa_and_normalizes_every_path(self) -> None:
        result = self.fixture.prepare()
        self.assertEqual(result["status"], "automated-qa")
        self.assertFalse(result["golden_accepted"])
        self.assertEqual(self.fixture.paths.raw.read_bytes(), self.fixture.paths.final.read_bytes())
        manifest = json.loads(self.fixture.manifest_path.read_text(encoding="utf-8"))
        job = manifest["jobs"][0]
        self.assertEqual(job["status"], "automated-qa")
        self.assertEqual(
            [event["state"] for event in job["history"]],
            ["planned", "inputs-ready", "generated", "automated-qa"],
        )
        self.assertNotIn("vision", job["qa"])
        for document_path in (
            self.fixture.paths.receipt,
            self.fixture.paths.audit,
            self.fixture.paths.v19_receipt,
            self.fixture.manifest_path,
        ):
            document = json.loads(document_path.read_text(encoding="utf-8"))
            promotion._assert_persistent_graph(document)
            serialized = json.dumps(document)
            self.assertNotIn("tmp/", serialized)
            self.assertNotIn("C:/", serialized)
            self.assertNotIn("F:/", serialized)

        normalized_v19 = json.loads(
            self.fixture.paths.v19_receipt.read_text(encoding="utf-8")
        )
        metadata = normalized_v19["control_atlas_metadata"]
        self.assertEqual(
            metadata["path"], relative(self.fixture.control_atlas_metadata)
        )
        self.assertEqual(
            metadata["sha256"], digest(self.fixture.control_atlas_metadata)
        )
        body_control = normalized_v19["canonical_body_control"]
        self.assertEqual(
            body_control["path"], relative(self.fixture.canonical_body_control)
        )
        self.assertEqual(
            body_control["sha256"], digest(self.fixture.canonical_body_control)
        )

        manifest_inputs = {
            item["role"]: item
            for item in manifest["jobs"][0]["inputs"]
            if isinstance(item, dict) and isinstance(item.get("role"), str)
        }
        metadata_input = manifest_inputs["v19-control-atlas-metadata"]
        self.assertEqual(
            metadata_input["path"], relative(self.fixture.control_atlas_metadata)
        )
        self.assertEqual(
            metadata_input["sha256"], digest(self.fixture.control_atlas_metadata)
        )
        body_control_input = manifest_inputs["v19-canonical-body-control"]
        self.assertEqual(
            body_control_input["path"],
            relative(self.fixture.canonical_body_control),
        )
        self.assertEqual(
            body_control_input["sha256"],
            digest(self.fixture.canonical_body_control),
        )

        for bad_path in (
            "tmp/map-production/control-atlas-metadata.json",
            self.fixture.control_atlas_metadata.resolve().as_posix(),
        ):
            with self.subTest(persistent_path=bad_path):
                with self.assertRaises(promotion.K3GoldenPromotionError):
                    promotion._assert_persistent_graph(
                        {
                            "control_atlas_metadata": {
                                "path": bad_path,
                                "sha256": digest(
                                    self.fixture.control_atlas_metadata
                                ),
                            }
                        }
                    )

    def test_prepare_rejects_v18_stale_gate_and_overwrite_without_manifest_change(self) -> None:
        original_manifest = self.fixture.manifest_path.read_bytes()
        rejected = copy.deepcopy(self.fixture.receipt)
        original_candidate = self.fixture.candidate.read_bytes()
        self.fixture.candidate.write_bytes(self.fixture.v18.read_bytes())
        rejected["artifacts"]["candidate"] = artifact(self.fixture.candidate)
        self.fixture.receipt = rejected
        self.fixture.persist_source_receipt()
        with self.assertRaisesRegex(promotion.K3GoldenPromotionError, "rejected v18"):
            self.fixture.prepare()
        self.assertEqual(self.fixture.manifest_path.read_bytes(), original_manifest)
        self.assertFalse(self.fixture.paths.raw.exists())
        self.fixture.candidate.write_bytes(original_candidate)

        stale = copy.deepcopy(self.fixture.receipt)
        stale["artifacts"]["candidate"] = artifact(self.fixture.candidate)
        first_gate = next(iter(stale["automated_gates"]))
        stale["automated_gates"][first_gate] = False
        stale["failed_gates"] = [first_gate]
        self.fixture.receipt = stale
        self.fixture.persist_source_receipt()
        with self.assertRaisesRegex(promotion.K3GoldenPromotionError, "not all passed"):
            self.fixture.prepare()
        self.assertEqual(self.fixture.manifest_path.read_bytes(), original_manifest)
        self.assertFalse(self.fixture.paths.raw.exists())

        self.fixture.receipt = copy.deepcopy(stale)
        self.fixture.receipt["automated_gates"][first_gate] = True
        self.fixture.receipt["failed_gates"] = []
        self.fixture.persist_source_receipt()
        with self.assertRaisesRegex(
            promotion.K3GoldenPromotionError, "audit did not pass"
        ):
            promotion.prepare_promotion(
                source_receipt_path=self.fixture.source_receipt,
                authorized_by="Promotion Test",
                paths=self.fixture.paths,
                source_contract=self.fixture.source_contract,
                audit_builder=lambda **_: {
                    "status": "failed",
                    "failed_gates": ["synthetic"],
                },
            )
        self.assertFalse(self.fixture.paths.raw.exists())
        self.assertFalse(self.fixture.paths.receipt.exists())
        self.assertEqual(self.fixture.manifest_path.read_bytes(), original_manifest)

        self.fixture.paths.final.parent.mkdir(parents=True, exist_ok=True)
        self.fixture.paths.final.write_bytes(b"do-not-overwrite")
        with self.assertRaisesRegex(promotion.K3GoldenPromotionError, "refusing to overwrite"):
            self.fixture.prepare()
        self.assertEqual(self.fixture.paths.final.read_bytes(), b"do-not-overwrite")
        self.assertFalse(self.fixture.paths.raw.exists())
        self.assertEqual(self.fixture.manifest_path.read_bytes(), original_manifest)

    def test_accept_failures_leave_manifest_at_automated_qa(self) -> None:
        self.fixture.prepare()
        review_a_path = self.fixture.root / "qa" / "review-a.json"
        review_b_path = self.fixture.root / "qa" / "review-b.json"
        base_a = self.fixture.review(review_a_path, "Reviewer Alpha")
        base_b = self.fixture.review(review_b_path, "Reviewer Beta")
        automated_manifest = self.fixture.manifest_path.read_bytes()

        def attempt(paths: list[Path]) -> None:
            with self.assertRaises(promotion.K3GoldenPromotionError):
                promotion.accept_promotion(
                    review_paths=paths,
                    authorized_by="Acceptance Test",
                    manifest_path=self.fixture.manifest_path,
                )
            self.assertEqual(self.fixture.manifest_path.read_bytes(), automated_manifest)

        attempt([review_a_path])
        attempt([review_a_path, review_a_path])

        cases = []
        duplicate = copy.deepcopy(base_b)
        duplicate["reviewer"] = " reviewer alpha "
        cases.append(duplicate)
        unicode_alias = copy.deepcopy(base_b)
        unicode_alias["reviewer"] = "Ｒｅｖｉｅｗｅｒ\u3000Ａｌｐｈａ"
        cases.append(unicode_alias)
        nonblind = copy.deepcopy(base_b)
        nonblind["review_mode"] = "self"
        cases.append(nonblind)
        low = copy.deepcopy(base_b)
        low["scores"][-1]["score"] = 3
        low["total_score"] = 93
        cases.append(low)
        failure = copy.deepcopy(base_b)
        failure["immediate_failures"][0]["detected"] = True
        cases.append(failure)
        stale_sha = copy.deepcopy(base_b)
        stale_sha["image_sha256"] = "0" * 64
        cases.append(stale_sha)
        for report in cases:
            review_b_path.write_text(json.dumps(report), encoding="utf-8")
            attempt([review_a_path, review_b_path])
        review_a_path.write_text(json.dumps(base_a), encoding="utf-8")

    def test_prepare_fails_closed_without_exact_v19_graph_or_temp_namespace(self) -> None:
        original = copy.deepcopy(self.fixture.receipt)
        del self.fixture.receipt["v19_input"]["provenance_receipt"]
        self.fixture.persist_source_receipt()
        with self.assertRaisesRegex(
            promotion.K3GoldenPromotionError, "missing exact v19 provenance contract"
        ):
            self.fixture.prepare()
        self.assertFalse(self.fixture.paths.raw.exists())

        self.fixture.receipt = original
        self.fixture.persist_source_receipt()
        outside = self.fixture.root / self.fixture.source_receipt.name
        outside.write_bytes(self.fixture.source_receipt.read_bytes())
        with self.assertRaisesRegex(
            promotion.K3GoldenPromotionError, "exact TEMP contract path"
        ):
            promotion.prepare_promotion(
                source_receipt_path=outside,
                authorized_by="Promotion Test",
                paths=self.fixture.paths,
                source_contract=self.fixture.source_contract,
                audit_builder=self.fixture.fake_audit,
            )

    def test_prepare_replays_v19_instead_of_trusting_opaque_png(self) -> None:
        self.fixture.v19_builder.write_text(
            "import argparse, json, shutil\n"
            "p=argparse.ArgumentParser(); p.add_argument('--replay-contract', required=True); p.add_argument('--output', required=True); a=p.parse_args()\n"
            "c=json.load(open(a.replay_contract, encoding='utf-8'))\n"
            "shutil.copyfile(c['base_v18']['path'], a.output)\n",
            encoding="utf-8",
        )
        v19_receipt = json.loads(self.fixture.v19_receipt.read_text(encoding="utf-8"))
        v19_receipt["reconstruction_builder"]["sha256"] = digest(
            self.fixture.v19_builder
        )
        self.fixture.v19_receipt.write_text(json.dumps(v19_receipt), encoding="utf-8")
        self.fixture.receipt["v19_input"]["provenance_receipt"]["sha256"] = digest(
            self.fixture.v19_receipt
        )
        self.fixture.persist_source_receipt()
        with self.assertRaisesRegex(
            promotion.K3GoldenPromotionError, "not byte-identical"
        ):
            self.fixture.prepare()

    def test_prepare_detects_late_persistent_and_manifest_mutations(self) -> None:
        original_validate = promotion._validate_projected_manifest
        permission = (
            self.fixture.paths.masks_dir
            / f"{promotion.JOB_ID}-v20-{promotion._artifact_name('permission')}"
        )
        reference = self.fixture.paths.lineage_dir / "reference-b1.png"
        targets = [
            self.fixture.paths.raw,
            self.fixture.paths.v19_parent,
            permission,
            reference,
        ]
        original_manifest = self.fixture.manifest_path.read_bytes()
        for target in targets:
            with self.subTest(target=target.name):
                def tamper(path, projected, *, target=target):
                    original_validate(path, projected)
                    target.write_bytes(b"late mutation")

                with mock.patch.object(
                    promotion, "_validate_projected_manifest", side_effect=tamper
                ):
                    with self.assertRaisesRegex(
                        promotion.K3GoldenPromotionError, "changed"
                    ):
                        self.fixture.prepare()
                self.assertEqual(self.fixture.manifest_path.read_bytes(), original_manifest)
                self.assertFalse(self.fixture.paths.raw.exists())

        def overwrite_manifest(path, projected):
            original_validate(path, projected)
            self.fixture.manifest_path.write_bytes(original_manifest + b" ")

        with mock.patch.object(
            promotion,
            "_validate_projected_manifest",
            side_effect=overwrite_manifest,
        ):
            with self.assertRaisesRegex(
                promotion.K3GoldenPromotionError, "original production manifest changed"
            ):
                self.fixture.prepare()
        self.fixture.manifest_path.write_bytes(original_manifest)
        self.assertFalse(self.fixture.paths.raw.exists())

    def test_prepare_detects_late_v55_source_and_control_mutations(self) -> None:
        original_validate = promotion._validate_projected_manifest
        original_manifest = self.fixture.manifest_path.read_bytes()
        for target in (
            self.fixture.layout_control,
            self.fixture.control_atlas_metadata,
            self.fixture.canonical_body_control,
        ):
            original = target.read_bytes()
            with self.subTest(target=target.name):
                def tamper(path, projected, *, target=target, original=original):
                    original_validate(path, projected)
                    target.write_bytes(original + b"late mutation")

                try:
                    with mock.patch.object(
                        promotion, "_validate_projected_manifest", side_effect=tamper
                    ):
                        with self.assertRaisesRegex(
                            promotion.K3GoldenPromotionError, "changed"
                        ):
                            self.fixture.prepare()
                finally:
                    target.write_bytes(original)
                self.assertEqual(
                    self.fixture.manifest_path.read_bytes(), original_manifest
                )
                self.assertFalse(self.fixture.paths.raw.exists())

    def test_accept_detects_late_manifest_and_reachable_input_mutations(self) -> None:
        self.fixture.prepare()
        review_a = self.fixture.root / "qa" / "review-a.json"
        review_b = self.fixture.root / "qa" / "review-b.json"
        self.fixture.review(review_a, "Reviewer Alpha")
        self.fixture.review(review_b, "Reviewer Beta")
        manifest_bytes = self.fixture.manifest_path.read_bytes()
        permission = (
            self.fixture.paths.masks_dir
            / f"{promotion.JOB_ID}-v20-{promotion._artifact_name('permission')}"
        )
        reference = self.fixture.paths.lineage_dir / "reference-b1.png"
        targets = [
            self.fixture.paths.raw,
            self.fixture.paths.v19_parent,
            permission,
            reference,
            self.fixture.manifest_path,
        ]
        original_validate = promotion._validate_projected_manifest
        for target in targets:
            original_bytes = target.read_bytes()
            with self.subTest(target=target.name):
                def tamper(path, projected, *, target=target):
                    original_validate(path, projected)
                    target.write_bytes(original_bytes + b"late mutation")

                with mock.patch.object(
                    promotion, "_validate_projected_manifest", side_effect=tamper
                ):
                    with self.assertRaisesRegex(
                        promotion.K3GoldenPromotionError, "changed"
                    ):
                        promotion.accept_promotion(
                            review_paths=[review_a, review_b],
                            authorized_by="Acceptance Test",
                            manifest_path=self.fixture.manifest_path,
                        )
                target.write_bytes(original_bytes)
                self.assertEqual(self.fixture.manifest_path.read_bytes(), manifest_bytes)

    def test_two_valid_reviews_accept_and_phase5_binds_normalized_graph(self) -> None:
        self.fixture.prepare()
        review_a = self.fixture.root / "qa" / "review-a.json"
        review_b = self.fixture.root / "qa" / "review-b.json"
        self.fixture.review(review_a, "Reviewer Alpha")
        self.fixture.review(review_b, "Reviewer Beta")

        result = promotion.accept_promotion(
            review_paths=[review_a, review_b],
            authorized_by="Acceptance Test",
            manifest_path=self.fixture.manifest_path,
        )

        self.assertEqual(result["status"], "accepted")
        manifest = json.loads(self.fixture.manifest_path.read_text(encoding="utf-8"))
        job = manifest["jobs"][0]
        self.assertEqual(job["status"], "accepted")
        self.assertEqual(
            [event["state"] for event in job["history"]][-2:],
            ["vision-qa", "accepted"],
        )
        master = job["master"]
        binding = bind_file(
            self.fixture.manifest_path, label="accepted fixture manifest", trackable=True
        )
        registry = phase5.bind_manifest_golden_evidence(
            {"path": master["path"], "sha256": master["sha256"]}, binding
        )
        self.assertGreater(len(registry), 6)
        evidence = phase5.verify_manifest_golden_style(
            {"path": master["path"], "sha256": master["sha256"]},
            self.fixture.manifest_path,
        )
        self.assertEqual(evidence["job_id"], promotion.JOB_ID)
        self.assertEqual(len(evidence["manifest_vision_reports"]), 2)


if __name__ == "__main__":
    unittest.main()
