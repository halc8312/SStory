import hashlib
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import assemble_phase5_composite_records as bundle  # noqa: E402
import build_phase5_assets as phase5  # noqa: E402
import create_qa_report  # noqa: E402
import write_phase5_source_indexes as writer  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path: Path) -> dict[str, str]:
    return {"path": phase5.repo_path(path), "sha256": digest(path)}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def accepted_vision(
    *,
    job_id: str,
    image: Path,
    reviewer: str,
    golden: bool,
    threshold: int,
    vision_receipt: dict[str, str] | None = None,
) -> dict:
    report = create_qa_report.build_report(
        job_id,
        phase5.repo_path(image),
        reviewer=reviewer,
        golden=golden,
        threshold=threshold,
        image_sha256=digest(image),
        review_mode="blind-independent",
        vision_bundle_receipt=vision_receipt,
    )
    if vision_receipt is not None:
        report["vision_bundle"]["reviewer_confirmed_exact_five"] = True
    report["created_at"] = "2026-07-21T00:00:00Z"
    report["status"] = "complete"
    report["decision"] = "accepted"
    report["summary"] = "Complete independent fixture review."
    for view in report["review_views"]:
        view["complete"] = True
        view["evidence"] = "checked"
    for failure in report["immediate_failures"]:
        failure["detected"] = False
        failure["evidence"] = "not detected"
    for score in report["scores"]:
        score["score"] = score["maximum"]
        score["notes"] = "checked"
    report["total_score"] = 100
    return report


class CompositeBundleFixture:
    def __init__(self, root: Path, *, stage: str = "idx22"):
        self.root = root
        self.stage = stage
        self.build_root = root / "composites"
        self.masters = self.build_root / "masters"
        self.automated = root / "automated"
        self.vision = root / "vision"
        self.output = root / f"{stage}-composite-records.json"
        for directory in (self.masters, self.automated, self.vision):
            directory.mkdir(parents=True)

        catalog, catalog_by_id, derived = phase5.load_contract(
            phase5.DEFAULT_CONTRACT, phase5.DEFAULT_MAP_SHEETS
        )
        self.catalog = catalog
        self.catalog_by_id = catalog_by_id
        self.contracts = {
            sheet_id: {**contract, "width": 8, "height": 8}
            for sheet_id, contract in derived["sheets"].items()
        }
        self.load_contract_result = (
            self.catalog,
            self.catalog_by_id,
            {"sheets": self.contracts},
        )
        base_stage = bundle.STAGE_BASE[stage]
        self.base_ids = writer._expected_stage_ids(base_stage, self.catalog_by_id)
        self.expected_ids = writer._expected_new_ids(stage, self.catalog_by_id)
        self.ordered_base_ids = self._ordered(self.base_ids)
        self.ordered_expected_ids = self._ordered(self.expected_ids)

        self.golden = root / "golden.png"
        Image.new("RGB", (4, 4), (210, 190, 130)).save(self.golden)
        self.golden_report_paths: list[Path] = []
        for position, reviewer in enumerate(("Golden Reviewer A", "Golden Reviewer B")):
            path = root / f"golden-review-{position + 1}.json"
            write_json(
                path,
                accepted_vision(
                    job_id="style-candidate-k-v3-golden",
                    image=self.golden,
                    reviewer=reviewer,
                    golden=True,
                    threshold=94,
                ),
            )
            self.golden_report_paths.append(path)

        self.direct_provenance = root / "direct-golden-provenance.json"
        write_json(
            self.direct_provenance,
            {
                "inputs": {
                    "golden_style": artifact(self.golden),
                    "golden_vision_reports": [
                        artifact(path) for path in self.golden_report_paths
                    ],
                }
            },
        )
        self.dummy_evidence = root / "base-evidence.json"
        write_json(self.dummy_evidence, {"fixture": True})

        self.child_masters: dict[str, Path] = {}
        base_records: list[dict] = []
        for position, sheet_id in enumerate(self.ordered_base_ids):
            child = root / "children" / f"{sheet_id}.png"
            child.parent.mkdir(parents=True, exist_ok=True)
            Image.new(
                "RGB",
                (8, 8),
                (40 + position % 180, 70 + position % 150, 90 + position % 140),
            ).save(child)
            self.child_masters[sheet_id] = child
            provenance = (
                self.direct_provenance
                if sheet_id in writer.EXPECTED_DIRECT_IDS
                else self.dummy_evidence
            )
            base_records.append(
                {
                    "sheet_id": sheet_id,
                    "kind": writer._kind_for_sheet(self.catalog_by_id[sheet_id]),
                    **artifact(child),
                    "provenance_report": artifact(provenance),
                    "automated_report": artifact(self.dummy_evidence),
                    "vision_reports": [artifact(self.dummy_evidence)],
                }
            )
        self.base_index = root / f"world-v3-source-index-{base_stage}.json"
        write_json(
            self.base_index,
            {
                "schema_version": "1.3.0",
                "coordinate_reference_system": "EA-WORLD-1",
                "golden_style": artifact(self.golden),
                "sources": base_records,
            },
        )

        self.observed_mask = self.build_root / "qa" / "observed.png"
        self.observed_mask.parent.mkdir(parents=True)
        Image.new("L", (8, 8), 255).save(self.observed_mask)
        self.build_report = self.build_root / "build-report.json"
        self.vision_paths: dict[str, Path] = {}
        self.vision_receipts: dict[str, Path] = {}
        artifact_by_id: dict[str, dict] = {}
        for sheet_id in self.ordered_base_ids:
            imported = self.masters / f"{sheet_id}.png"
            shutil.copy2(self.child_masters[sheet_id], imported)
            artifact_by_id[sheet_id] = {
                "sheet_id": sheet_id,
                "path": f"masters/{sheet_id}.png",
                "manifest_path": phase5.repo_path(imported),
                "sha256": digest(imported),
                "width": 8,
                "height": 8,
                "method": (
                    phase5.CANONICAL_RENDER_METHOD
                    if sheet_id in writer.EXPECTED_DIRECT_IDS
                    else "verified-composite-master-import"
                ),
                "accepted": True,
                "provisional": False,
            }
        for position, sheet_id in enumerate(self.ordered_expected_ids):
            master = self.masters / f"{sheet_id}.png"
            Image.new("RGB", (8, 8), (160, 170 + position, 185)).save(master)
            children = []
            expected_children = phase5._expected_composite_children(
                self.catalog_by_id[sheet_id], self.catalog_by_id
            )
            for child_id in expected_children:
                child = self.child_masters[child_id]
                children.append(
                    {
                        "sheet_id": child_id,
                        **artifact(child),
                        "native_zoom": self.contracts[child_id]["native_zoom"],
                    }
                )
            child_order = [
                child["sheet_id"]
                for child in sorted(
                    children,
                    key=lambda child: (child["native_zoom"], child["sheet_id"]),
                )
            ]
            artifact_by_id[sheet_id] = {
                "sheet_id": sheet_id,
                "path": f"masters/{sheet_id}.png",
                "manifest_path": phase5.repo_path(master),
                "sha256": digest(master),
                "width": 8,
                "height": 8,
                "method": "deterministic-parent-composite",
                "accepted": False,
                "provisional": True,
                "provenance": {
                    "kind": "deterministic-parent-composite",
                    "children": children,
                    "acceptance_inferred": False,
                    "canonical_native_base": {
                        "renderer": artifact(phase5.CANONICAL_RENDERER_PATH),
                        "resolution_contract": artifact(phase5.DEFAULT_CONTRACT),
                        "material_atlas": artifact(
                            phase5.DEFAULT_PHASE5_MATERIAL_ATLAS
                        ),
                        "canon_sources": [
                            {"role": role, **artifact(path)}
                            for role, path in phase5.CANONICAL_GEOJSON_SOURCES.items()
                        ],
                        "render_stats_sha256": "0" * 64,
                        "source_coordinates_modified": False,
                        "world_crop_or_upscale_used": False,
                    },
                    "observed_masks": {
                        "land_sea": artifact(self.observed_mask),
                        "transport": artifact(self.observed_mask),
                    },
                    "composition": {
                        "child_order": child_order,
                        "resampling": "LANCZOS-downsample-only",
                        "upscaled_child_count": 0,
                        "base_rendered_at_parent_native_resolution": True,
                    },
                },
            }
            automated = self.automated / f"{sheet_id}.phase5.json"
            write_json(
                automated,
                {
                    "job_id": phase5.job_id_for_sheet(sheet_id),
                    "sheet_id": sheet_id,
                    "status": "passed",
                    "source_kind": "composite_master",
                    "master": artifact(master),
                    # Filled after the shared build report is written.
                    "provenance_report": None,
                },
            )
            vision = self.vision / f"{phase5.job_id_for_sheet(sheet_id)}-review.json"
            vision_receipt = self.root / "evidence" / f"{sheet_id}.view-bundle.json"
            write_json(vision_receipt, {"sheet_id": sheet_id, "fixture": True})
            write_json(
                vision,
                accepted_vision(
                    job_id=phase5.job_id_for_sheet(sheet_id),
                    image=master,
                    reviewer=f"Composite Reviewer {position + 1}",
                    golden=False,
                    threshold=90,
                    vision_receipt=artifact(vision_receipt),
                ),
            )
            self.vision_paths[sheet_id] = vision
            self.vision_receipts[sheet_id] = vision_receipt

        output_ids = writer._expected_stage_ids(stage, self.catalog_by_id)
        ordered_output_ids = self._ordered(output_ids)
        deferred_ids = (
            writer._expected_stage_ids("idx23", self.catalog_by_id) - output_ids
        )
        self.build_document = {
            "schema_version": phase5.BUILD_REPORT_SCHEMA_VERSION,
            "generated_by": phase5.GENERATOR_ID,
            "generated_at": "2026-07-21T00:00:00Z",
            "coordinate_reference_system": "EA-WORLD-1",
            "target_stage": stage,
            "generated_composite_sheet_ids": self.ordered_expected_ids,
            "deferred_sheet_ids": self._ordered(deferred_ids),
            "inputs": {
                "builder_script": artifact(phase5.BUILDER_SCRIPT_PATH),
                "catalog": artifact(phase5.DEFAULT_MAP_SHEETS),
                "resolution_contract": artifact(phase5.DEFAULT_CONTRACT),
                "source_index": artifact(self.base_index),
            },
            "bounded_sheet_count": len(ordered_output_ids),
            "materialized_master_count": len(ordered_output_ids),
            "accepted_master_count": len(self.ordered_base_ids),
            "provisional_master_count": len(self.ordered_expected_ids),
            "planned_only_count": 0,
            "tiles_requested": False,
            "public_tile_release": None,
            "artifacts": [artifact_by_id[sheet_id] for sheet_id in ordered_output_ids],
        }
        self._write_build_report()

    def _ordered(self, ids: set[str]) -> list[str]:
        return [
            sheet["id"] for sheet in self.catalog["sheets"] if sheet.get("id") in ids
        ]

    def _write_build_report(self) -> None:
        write_json(self.build_report, self.build_document)
        for sheet_id in self.ordered_expected_ids:
            path = self.automated / f"{sheet_id}.phase5.json"
            report = json.loads(path.read_text(encoding="utf-8"))
            report["provenance_report"] = artifact(self.build_report)
            write_json(path, report)

    def assemble(self, *, force: bool = False) -> dict:
        def fixture_vision_evidence(
            report: dict,
            *,
            sheet_id: str,
            master_path: Path,
            master_sha256: str,
            focus_registry_path=None,
        ):
            del focus_registry_path
            source = bundle.vision_evidence.bind_file(
                master_path, label=f"{sheet_id} fixture Vision source"
            )
            if source.sha256 != master_sha256:
                raise bundle.vision_evidence.Phase5VisionEvidenceError(
                    "fixture Vision source hash mismatch"
                )
            receipt_spec = report["vision_bundle"]["receipt"]
            receipt = bundle.vision_evidence.bind_file(
                receipt_spec["path"], label=f"{sheet_id} fixture Vision receipt"
            )
            if receipt.sha256 != receipt_spec["sha256"]:
                raise bundle.vision_evidence.Phase5VisionEvidenceError(
                    "fixture Vision receipt hash mismatch"
                )
            registry = bundle.vision_evidence.bind_file(
                bundle.vision_evidence.DEFAULT_FOCUS_REGISTRY,
                label="fixture canonical focus registry",
            )
            return bundle.vision_evidence.VisionEvidenceBindings(
                source, receipt, registry
            )

        with (
            mock.patch.object(
                bundle.phase5, "load_contract", return_value=self.load_contract_result
            ),
            mock.patch.object(bundle.phase5, "validate_automated_qa_report"),
            mock.patch.object(
                bundle.vision_evidence,
                "validate_report_vision_bundle",
                side_effect=fixture_vision_evidence,
            ),
        ):
            return bundle.assemble_composite_record_bundle(
                stage=self.stage,
                base_index_path=self.base_index,
                build_report_path=self.build_report,
                masters_root=self.masters,
                automated_root=self.automated,
                vision_root=self.vision,
                output_path=self.output,
                force=force,
            )


class Phase5CompositeRecordBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = (
            REPO_ROOT / f".phase5-composite-record-bundle-test-{uuid.uuid4().hex}"
        )
        self.root.mkdir()
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.fixture = CompositeBundleFixture(self.root)

    def test_idx22_bundle_is_deterministic_and_writer_compatible(self):
        document = self.fixture.assemble()
        first = self.fixture.output.read_bytes()
        self.assertEqual(document["schema_version"], "1.0.0")
        self.assertEqual(document["release_id"], "world-v3")
        self.assertEqual(
            [record["sheet_id"] for record in document["records"]],
            self.fixture.ordered_expected_ids,
        )
        self.assertEqual(len(document["records"]), 5)
        for record in document["records"]:
            self.assertEqual(record["kind"], "composite_master")
            self.assertEqual(len(record["vision_reports"]), 1)
            self.assertEqual(
                record["provenance_report"], artifact(self.fixture.build_report)
            )
        loaded = writer.load_records([self.fixture.output])
        self.assertEqual(set(loaded), writer.EXPECTED_CONTINENT_IDS)
        self.fixture.assemble(force=True)
        self.assertEqual(self.fixture.output.read_bytes(), first)

    def test_idx23_world_bundle_is_supported(self):
        fixture = CompositeBundleFixture(self.root / "world", stage="idx23")
        document = fixture.assemble()
        self.assertEqual(len(document["records"]), 1)
        self.assertEqual(document["records"][0]["sheet_id"], "sheet_world")
        self.assertEqual(document["records"][0]["kind"], "composite_master")

    def test_idx23_rejects_regenerated_continent_claim(self):
        fixture = CompositeBundleFixture(self.root / "regenerated", stage="idx23")
        continent_id = next(
            sheet_id
            for sheet_id in fixture.ordered_base_ids
            if fixture.catalog_by_id[sheet_id]["sheet_type"] == "continent"
        )
        record = next(
            item
            for item in fixture.build_document["artifacts"]
            if item["sheet_id"] == continent_id
        )
        record["method"] = "deterministic-parent-composite"
        fixture._write_build_report()
        with self.assertRaisesRegex(
            bundle.CompositeRecordBundleError,
            "target-stage contract|verified-composite-master-import",
        ):
            fixture.assemble()

    def test_rejects_base_index_order_and_exact_child_index_tampering(self):
        base = json.loads(self.fixture.base_index.read_text(encoding="utf-8"))
        base["sources"] = list(reversed(base["sources"]))
        write_json(self.fixture.base_index, base)
        with self.assertRaisesRegex(
            bundle.CompositeRecordBundleError, "order mismatch"
        ):
            self.fixture.assemble()

        self.fixture = CompositeBundleFixture(self.root / "child-index")
        self.fixture.build_document["inputs"]["source_index"]["sha256"] = "0" * 64
        self.fixture._write_build_report()
        with self.assertRaisesRegex(
            bundle.CompositeRecordBundleError,
            "hash mismatch|sha256 mismatch|exact artifact",
        ):
            self.fixture.assemble()

    def test_rejects_child_coverage_and_build_artifact_order(self):
        first = self.fixture.build_document["artifacts"][0]
        first["provenance"]["children"] = first["provenance"]["children"][1:]
        self.fixture._write_build_report()
        with self.assertRaisesRegex(
            bundle.CompositeRecordBundleError, "child coverage mismatch"
        ):
            self.fixture.assemble()

        self.fixture = CompositeBundleFixture(self.root / "artifact-order")
        self.fixture.build_document["artifacts"][0:2] = reversed(
            self.fixture.build_document["artifacts"][0:2]
        )
        self.fixture._write_build_report()
        with self.assertRaisesRegex(
            bundle.CompositeRecordBundleError, "coverage/order mismatch"
        ):
            self.fixture.assemble()

    def test_rejects_future_composite_hidden_or_reported_at_idx22(self):
        hidden_world = self.fixture.masters / "sheet_world.png"
        Image.new("RGB", (8, 8), "navy").save(hidden_world)
        with self.assertRaisesRegex(
            bundle.CompositeRecordBundleError, "non-stage files"
        ):
            self.fixture.assemble()

        self.fixture = CompositeBundleFixture(self.root / "reported-future")
        world = self.fixture.masters / "sheet_world.png"
        Image.new("RGB", (8, 8), "navy").save(world)
        self.fixture.build_document["artifacts"].insert(
            0,
            {
                "sheet_id": "sheet_world",
                "path": "masters/sheet_world.png",
                "manifest_path": phase5.repo_path(world),
                "sha256": digest(world),
                "width": 8,
                "height": 8,
                "method": "deterministic-parent-composite",
                "accepted": False,
                "provisional": True,
            },
        )
        self.fixture._write_build_report()
        with self.assertRaisesRegex(
            bundle.CompositeRecordBundleError, "coverage/order mismatch"
        ):
            self.fixture.assemble()

    def test_rejects_wrong_target_generated_and_deferred_stage_fields(self):
        cases = (
            ("target_stage", "idx23", "target-stage contract"),
            ("generated_composite_sheet_ids", [], "generated_composite"),
            ("deferred_sheet_ids", [], "deferred_sheet"),
        )
        for position, (key, value, message) in enumerate(cases):
            with self.subTest(key=key):
                fixture = CompositeBundleFixture(
                    self.root / f"wrong-stage-field-{position}"
                )
                fixture.build_document[key] = value
                fixture._write_build_report()
                with self.assertRaisesRegex(bundle.CompositeRecordBundleError, message):
                    fixture.assemble()

    def test_rejects_stale_master_and_build_report_hashes(self):
        sheet_id = self.fixture.ordered_expected_ids[0]
        master = self.fixture.masters / f"{sheet_id}.png"
        Image.new("RGB", (8, 8), "black").save(master)
        with self.assertRaisesRegex(bundle.CompositeRecordBundleError, "hash|sha256"):
            self.fixture.assemble()

        self.fixture = CompositeBundleFixture(self.root / "provenance-hash")
        automated = self.fixture.automated / (
            f"{self.fixture.ordered_expected_ids[0]}.phase5.json"
        )
        report = json.loads(automated.read_text(encoding="utf-8"))
        report["provenance_report"]["sha256"] = "0" * 64
        write_json(automated, report)
        with self.assertRaisesRegex(
            bundle.CompositeRecordBundleError, "hash mismatch|sha256 mismatch"
        ):
            self.fixture.assemble()

    def test_rejects_golden_reviewer_but_allows_one_non_golden_reviewer_per_sheet(self):
        first_id = self.fixture.ordered_expected_ids[0]
        review = self.fixture.vision_paths[first_id]
        report = json.loads(review.read_text(encoding="utf-8"))
        report["reviewer"] = "  GOLDEN   REVIEWER A "
        write_json(review, report)
        with self.assertRaisesRegex(
            bundle.CompositeRecordBundleError, "distinct from every Golden reviewer"
        ):
            self.fixture.assemble()

        self.fixture = CompositeBundleFixture(self.root / "duplicate-reviewer")
        first_id, second_id = self.fixture.ordered_expected_ids[:2]
        first = json.loads(
            self.fixture.vision_paths[first_id].read_text(encoding="utf-8")
        )
        second_path = self.fixture.vision_paths[second_id]
        second = json.loads(second_path.read_text(encoding="utf-8"))
        second["reviewer"] = first["reviewer"].swapcase()
        write_json(second_path, second)
        document = self.fixture.assemble()
        self.assertEqual(len(document["records"]), 5)

    def test_rejects_incomplete_views_low_score_and_extra_review(self):
        sheet_id = self.fixture.ordered_expected_ids[0]
        path = self.fixture.vision_paths[sheet_id]
        report = json.loads(path.read_text(encoding="utf-8"))
        report["review_views"][0]["complete"] = False
        write_json(path, report)
        with self.assertRaisesRegex(
            bundle.CompositeRecordBundleError, "invalid|complete"
        ):
            self.fixture.assemble()

        self.fixture = CompositeBundleFixture(self.root / "low-score")
        sheet_id = self.fixture.ordered_expected_ids[0]
        path = self.fixture.vision_paths[sheet_id]
        report = json.loads(path.read_text(encoding="utf-8"))
        report["scores"][0]["score"] -= 11
        report["total_score"] = 89
        write_json(path, report)
        with self.assertRaisesRegex(bundle.CompositeRecordBundleError, "at least 90"):
            self.fixture.assemble()

        self.fixture = CompositeBundleFixture(self.root / "extra-review")
        sheet_id = self.fixture.ordered_expected_ids[0]
        original = self.fixture.vision_paths[sheet_id]
        shutil.copy2(original, original.with_name(f"{original.stem}-extra.json"))
        with self.assertRaisesRegex(
            bundle.CompositeRecordBundleError, "exactly one.*found 2"
        ):
            self.fixture.assemble()

    def test_rejects_nonpassing_automated_report(self):
        sheet_id = self.fixture.ordered_expected_ids[0]
        path = self.fixture.automated / f"{sheet_id}.phase5.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["status"] = "failed"
        write_json(path, report)
        with self.assertRaisesRegex(
            bundle.CompositeRecordBundleError, "not an accepted composite audit"
        ):
            self.fixture.assemble()

    def test_atomic_no_clobber_and_post_install_rollback(self):
        existing = self.root / "existing.json"
        temporary = self.root / ".existing.json.tmp"
        existing.write_bytes(b"existing\n")
        temporary.write_bytes(b"candidate\n")
        with self.assertRaisesRegex(
            bundle.CompositeRecordBundleError, "appeared during validation"
        ):
            bundle._install_payload(
                temporary=temporary,
                output_path=existing,
                force=False,
                payload_sha256=hashlib.sha256(b"candidate\n").hexdigest(),
                validate_commit_inputs=lambda: None,
            )
        self.assertEqual(existing.read_bytes(), b"existing\n")

        output = self.root / "rollback.json"
        temporary = self.root / ".rollback.json.tmp"
        temporary.write_bytes(b"candidate\n")
        calls = 0

        def fail_after_install() -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise bundle.CompositeRecordBundleError("post-install drift")

        with self.assertRaisesRegex(
            bundle.CompositeRecordBundleError, "post-install drift"
        ):
            bundle._install_payload(
                temporary=temporary,
                output_path=output,
                force=False,
                payload_sha256=hashlib.sha256(b"candidate\n").hexdigest(),
                validate_commit_inputs=fail_after_install,
            )
        self.assertFalse(output.exists())

        output = self.root / "cleanup-resistant.json"
        temporary = self.root / ".cleanup-resistant.json.tmp"
        temporary.write_bytes(b"candidate\n")
        original_unlink = Path.unlink

        def fail_only_temporary(path: Path, *args, **kwargs) -> None:
            if path == temporary:
                raise OSError("simulated sharing violation")
            original_unlink(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", fail_only_temporary):
            bundle._install_payload(
                temporary=temporary,
                output_path=output,
                force=False,
                payload_sha256=hashlib.sha256(b"candidate\n").hexdigest(),
                validate_commit_inputs=lambda: None,
            )
        self.assertEqual(output.read_bytes(), b"candidate\n")

    def test_force_rollback_restores_previous_output(self):
        output = self.root / "force-rollback.json"
        temporary = self.root / ".force-rollback.json.tmp"
        output.write_bytes(b"previous\n")
        temporary.write_bytes(b"candidate\n")
        calls = 0

        def fail_after_install() -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise bundle.CompositeRecordBundleError("bound input drift")

        with self.assertRaisesRegex(
            bundle.CompositeRecordBundleError, "bound input drift"
        ):
            bundle._install_payload(
                temporary=temporary,
                output_path=output,
                force=True,
                payload_sha256=hashlib.sha256(b"candidate\n").hexdigest(),
                validate_commit_inputs=fail_after_install,
            )
        self.assertEqual(output.read_bytes(), b"previous\n")

    def test_vision_namespace_is_rechecked_at_commit(self):
        sheet_id = self.fixture.ordered_expected_ids[0]
        job_id = phase5.job_id_for_sheet(sheet_id)
        snapshot = bundle._vision_namespace_snapshot(self.fixture.vision, job_id)
        original = self.fixture.vision_paths[sheet_id]
        shutil.copy2(original, original.with_name(f"{original.stem}-late.json"))
        with self.assertRaisesRegex(
            bundle.CompositeRecordBundleError, "namespace changed"
        ):
            bundle._assert_commit_inputs(
                bindings={},
                vision_root=self.fixture.vision,
                vision_namespaces={sheet_id: snapshot},
            )


if __name__ == "__main__":
    unittest.main()
