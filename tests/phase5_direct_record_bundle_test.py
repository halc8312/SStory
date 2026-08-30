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

import assemble_phase5_direct_records as bundle  # noqa: E402
import build_phase5_assets as phase5  # noqa: E402
import create_qa_report  # noqa: E402
import write_phase5_source_indexes as source_index_writer  # noqa: E402
from tests.phase5_assets_test import (  # noqa: E402
    write_golden_manifest_with_two_reviews,
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path: Path) -> dict[str, str]:
    return {"path": phase5.repo_path(path), "sha256": digest(path)}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def accepted_vision_report(
    *,
    job_id: str,
    image_path: str,
    image_sha256: str,
    reviewer: str,
    threshold: int,
    vision_receipt: dict[str, str],
) -> dict:
    report = create_qa_report.build_report(
        job_id,
        image_path,
        reviewer=reviewer,
        golden=False,
        threshold=threshold,
        image_sha256=image_sha256,
        review_mode="blind-independent",
        vision_bundle_receipt=vision_receipt,
    )
    report["vision_bundle"]["reviewer_confirmed_exact_five"] = True
    report["created_at"] = "2026-07-21T00:00:00Z"
    report["status"] = "complete"
    report["decision"] = "accepted"
    report["summary"] = "Complete independent direct-master review fixture."
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


class DirectRecordBundleFixture:
    def __init__(self, root: Path):
        self.root = root
        self.masters = root / "masters"
        self.automated = root / "automated"
        self.vision = root / "vision"
        self.output = root / "direct17-records.json"
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
        self.ordered_ids = [
            sheet["id"]
            for sheet in catalog["sheets"]
            if sheet.get("id") in bundle.EXPECTED_DIRECT_IDS
        ]

        self.golden = root / "golden.png"
        Image.new("RGB", (4, 4), (210, 190, 130)).save(self.golden)
        self.base_manifest, self.golden_reviews = (
            write_golden_manifest_with_two_reviews(root, master=self.golden)
        )

        self.provenance_paths: dict[str, Path] = {}
        self.automated_paths: dict[str, Path] = {}
        self.vision_paths: dict[str, list[Path]] = {}
        self.vision_receipts: dict[str, Path] = {}
        for position, sheet_id in enumerate(self.ordered_ids):
            self._write_sheet(sheet_id, position)

    def _write_sheet(self, sheet_id: str, position: int) -> None:
        master = self.masters / f"{sheet_id}.png"
        color = (
            40 + (position * 11) % 180,
            60 + (position * 17) % 170,
            80 + (position * 23) % 160,
        )
        Image.new("RGB", (8, 8), color).save(master)
        observed_land = self.masters / f"{sheet_id}.observed-land-sea-mask.png"
        observed_transport = self.masters / f"{sheet_id}.observed-transport-mask.png"
        Image.new("L", (8, 8), 255).save(observed_land)
        Image.new("L", (8, 8), 255).save(observed_transport)

        inverse_roles = {
            canonical: renderer
            for renderer, canonical in phase5.RENDERER_SOURCE_ROLE_MAP.items()
        }
        renderer_report = self.masters / f"{sheet_id}.report.json"
        renderer_document = {
            "status": "passed",
            "coordinate_reference_system": "EA-WORLD-1",
            "generated_by": {
                "id": phase5.CANONICAL_RENDERER_ID,
                **artifact(phase5.CANONICAL_RENDERER_PATH),
            },
            "inputs": {
                "golden_style": {"status": "locked", **artifact(self.golden)},
                "material_atlas": {
                    "status": "locked",
                    **artifact(phase5.DEFAULT_PHASE5_MATERIAL_ATLAS),
                },
                "canonical_control_index": artifact(
                    phase5.DEFAULT_CANONICAL_CONTROL_INDEX
                ),
            },
            "sheet": {"sheet_id": sheet_id},
            "map_sheets": artifact(phase5.DEFAULT_MAP_SHEETS),
            "resolution_contract": artifact(phase5.DEFAULT_CONTRACT),
            "sources": [
                {"role": inverse_roles[role], **artifact(path)}
                for role, path in phase5.CANONICAL_GEOJSON_SOURCES.items()
            ],
            "anchoring": {"seed": 731_942},
            "transform": {
                "rounding": "half-away-from-zero",
                "source_coordinates_modified": False,
                "world_crop_or_upscale_used": False,
            },
            "outputs": {
                "master": {
                    **artifact(master),
                    "width": 8,
                    "height": 8,
                    "format": "PNG",
                    "mode": "RGB",
                },
                "observed_land_sea_mask": artifact(observed_land),
                "observed_transport_mask": artifact(observed_transport),
            },
        }
        write_json(renderer_report, renderer_document)

        provenance_path = self.masters / f"{sheet_id}.canonical-provenance.json"
        provenance_document = {
            "$schema": (
                "https://sstory.example/schemas/"
                "phase5-canonical-render-provenance.schema.json"
            ),
            "schema_version": "1.0.0",
            "type": "sstory-phase5-deterministic-canonical-render-provenance",
            "generated_by": phase5.GENERATOR_ID,
            "coordinate_reference_system": "EA-WORLD-1",
            "sheet_id": sheet_id,
            "inputs": {
                "golden_style": artifact(self.golden),
                "golden_vision_reports": self.golden_reviews,
                "renderer": artifact(phase5.CANONICAL_RENDERER_PATH),
                "renderer_report": artifact(renderer_report),
                "renderer_settings": {
                    "seed": 731_942,
                    "parameters": {
                        "coordinate_quantization": "half-away-from-zero",
                        "source_coordinates_modified": False,
                    },
                },
                "material_atlas": artifact(phase5.DEFAULT_PHASE5_MATERIAL_ATLAS),
                "map_catalog": artifact(phase5.DEFAULT_MAP_SHEETS),
                "resolution_contract": artifact(phase5.DEFAULT_CONTRACT),
                "control_index": artifact(phase5.DEFAULT_CANONICAL_CONTROL_INDEX),
                "canon_sources": [
                    {"role": role, **artifact(path)}
                    for role, path in phase5.CANONICAL_GEOJSON_SOURCES.items()
                ],
            },
            "artifacts": [
                {
                    "sheet_id": sheet_id,
                    "path": master.name,
                    "sha256": digest(master),
                    "width": 8,
                    "height": 8,
                    "format": "PNG",
                    "color_mode": "RGB",
                    "method": phase5.CANONICAL_RENDER_METHOD,
                    "provenance": {
                        "kind": phase5.CANONICAL_RENDER_METHOD,
                        "acceptance_inferred": False,
                    },
                }
            ],
            "created_at": "2026-07-21T00:00:00Z",
        }
        write_json(provenance_path, provenance_document)
        self.provenance_paths[sheet_id] = provenance_path

        automated_path = self.automated / f"{sheet_id}.phase5.json"
        band_metrics = phase5.unpainted_band_metrics(master, "fixture master")
        automated_document = {
            "$schema": "https://sstory.example/schemas/phase5-automated-qa.schema.json",
            "schema_version": "1.0.0",
            "type": "sstory-phase5-automated-master-qa",
            "coordinate_reference_system": "EA-WORLD-1",
            "generated_by": phase5.AUTOMATED_QA_GENERATOR_ID,
            "job_id": phase5.job_id_for_sheet(sheet_id),
            "sheet_id": sheet_id,
            "status": "passed",
            "source_kind": phase5.CANONICAL_RENDER_SOURCE_KIND,
            "master": {
                **artifact(master),
                "width": 8,
                "height": 8,
                "format": "PNG",
                "color_mode": "RGB",
            },
            "provenance_report": artifact(provenance_path),
            "checks": {
                "dimensions": {
                    "passed": True,
                    "expected_width": 8,
                    "expected_height": 8,
                    "actual_width": 8,
                    "actual_height": 8,
                },
                "encoding": {
                    "passed": True,
                    "expected_format": "PNG",
                    "actual_format": "PNG",
                    "expected_color_mode": "RGB",
                    "actual_color_mode": "RGB",
                },
                "digest": {
                    "passed": True,
                    "expected_sha256": digest(master),
                    "actual_sha256": digest(master),
                },
                "coverage": {
                    "passed": True,
                    "algorithm": "provenance-destination-coverage-v1",
                    "expected_pixel_count": 64,
                    "covered_pixel_count": 64,
                    "uncovered_pixel_count": 0,
                    "overlap_pixel_count": 0,
                },
                "unpainted_bands": {
                    "passed": True,
                    "algorithm": "coverage-and-axis-band-scan-v1",
                    "tested_fill_rgb": [0, 0, 0],
                    **band_metrics,
                },
                "seams": {
                    "passed": True,
                    "minimum_overlap_ssim": phase5.MINIMUM_ALLOWED_OVERLAP_SSIM,
                    "maximum_rgb_mean_difference": phase5.MAXIMUM_RGB_MEAN_DIFFERENCE,
                    "maximum_rgb_p95_difference": phase5.MAXIMUM_RGB_P95_DIFFERENCE,
                    "expected_count": 0,
                    "evaluated_count": 0,
                    "minimum_observed_ssim": None,
                    "maximum_observed_rgb_mean_difference": None,
                    "maximum_observed_rgb_p95_difference": None,
                    "evidence": [],
                },
            },
            "geography": {
                "land_sea": {
                    "passed": True,
                    "control": artifact(observed_land),
                    "observed": artifact(observed_land),
                    "minimum_match_ratio": phase5.MINIMUM_LAND_SEA_MATCH_RATIO,
                    "match_ratio": 1.0,
                },
                "transport": {
                    "passed": True,
                    "control": artifact(observed_transport),
                    "observed": artifact(observed_transport),
                    "tolerance_px": 0,
                    "minimum_within_tolerance_ratio": (
                        phase5.MINIMUM_TRANSPORT_WITHIN_TOLERANCE_RATIO
                    ),
                    "control_within_tolerance_ratio": 1.0,
                    "observed_within_tolerance_ratio": 1.0,
                },
            },
            "created_at": "2026-07-21T00:00:00Z",
        }
        write_json(automated_path, automated_document)
        self.automated_paths[sheet_id] = automated_path

        vision_receipt = self.root / "evidence" / f"{sheet_id}.view-bundle.json"
        write_json(vision_receipt, {"sheet_id": sheet_id, "fixture": True})
        self.vision_receipts[sheet_id] = vision_receipt

        threshold = 90 if sheet_id in bundle.EXPECTED_STANDARD_REVIEW_IDS else 94
        review_count = 1 if threshold == 90 else 2
        reports: list[Path] = []
        for review_number in range(1, review_count + 1):
            vision_path = self.vision / (
                f"{phase5.job_id_for_sheet(sheet_id)}-review{review_number}.json"
            )
            write_json(
                vision_path,
                accepted_vision_report(
                    job_id=phase5.job_id_for_sheet(sheet_id),
                    image_path=phase5.repo_path(master),
                    image_sha256=digest(master),
                    reviewer=f"Reviewer {position + 1} {review_number}",
                    threshold=threshold,
                    vision_receipt=artifact(vision_receipt),
                ),
            )
            reports.append(vision_path)
        self.vision_paths[sheet_id] = reports

    def validate_fixture_vision_evidence(
        self,
        report: dict,
        *,
        sheet_id: str,
        master_path: Path,
        master_sha256: str,
        focus_registry_path=None,
    ):
        """Bind compact fixture evidence without weakening production validation."""

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
        return bundle.vision_evidence.VisionEvidenceBindings(source, receipt, registry)

    def assemble(self, *, force: bool = False) -> dict:
        with (
            mock.patch.object(
                bundle.phase5, "load_contract", return_value=self.load_contract_result
            ),
            mock.patch.object(
                bundle.phase5.vision_evidence,
                "validate_report_vision_bundle",
                side_effect=self.validate_fixture_vision_evidence,
            ),
        ):
            return bundle.assemble_direct_record_bundle(
                masters_root=self.masters,
                automated_root=self.automated,
                vision_root=self.vision,
                output_path=self.output,
                force=force,
            )


class Phase5DirectRecordBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = REPO_ROOT / f".phase5-direct-record-bundle-test-{uuid.uuid4().hex}"
        self.root.mkdir()
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.writer_root = source_index_writer.TRACKED_RELEASE_ROOT / self.root.name
        self.addCleanup(lambda: shutil.rmtree(self.writer_root, ignore_errors=True))
        self.fixture = DirectRecordBundleFixture(self.root)

    def test_assembles_deterministic_writer_compatible_bundle(self):
        document = self.fixture.assemble()
        first_bytes = self.fixture.output.read_bytes()

        self.assertEqual(document["schema_version"], "1.0.0")
        self.assertEqual(document["release_id"], "world-v3")
        self.assertEqual(len(document["records"]), 17)
        self.assertEqual(
            [record["sheet_id"] for record in document["records"]],
            self.fixture.ordered_ids,
        )
        for record in document["records"]:
            self.assertEqual(record["kind"], phase5.CANONICAL_RENDER_SOURCE_KIND)
            self.assertNotIn("width", record)
            self.assertNotIn("height", record)
            expected_reviews = (
                1 if record["sheet_id"] in bundle.EXPECTED_STANDARD_REVIEW_IDS else 2
            )
            self.assertEqual(len(record["vision_reports"]), expected_reviews)

        loaded = source_index_writer.load_records([self.fixture.output])
        self.assertEqual(set(loaded), bundle.EXPECTED_DIRECT_IDS)

        writer_output = self.writer_root / "world-v3-source-index-idx17.json"
        with (
            mock.patch.object(
                source_index_writer.phase5,
                "load_contract",
                return_value=self.fixture.load_contract_result,
            ),
            mock.patch.object(
                bundle.phase5.vision_evidence,
                "validate_report_vision_bundle",
                side_effect=self.fixture.validate_fixture_vision_evidence,
            ),
        ):
            writer_result = source_index_writer.write_source_index(
                stage="idx17",
                record_paths=[self.fixture.output],
                output_path=writer_output,
                golden_style_path=self.fixture.golden,
                base_manifest_path=self.fixture.base_manifest,
            )
        self.assertTrue(writer_result["valid"])
        self.assertTrue(writer_result["committed"])
        self.assertEqual(writer_result["source_count"], 17)
        indexed, _, golden = phase5.load_source_index(
            writer_output, set(self.fixture.contracts)
        )
        self.assertEqual(set(indexed), bundle.EXPECTED_DIRECT_IDS)
        self.assertEqual(golden, artifact(self.fixture.golden))

        self.fixture.assemble(force=True)
        self.assertEqual(self.fixture.output.read_bytes(), first_bytes)

    def test_requires_two_strict_reviews_and_rejects_pending_or_rejected(self):
        strict_id = next(
            sheet_id
            for sheet_id in self.fixture.ordered_ids
            if sheet_id in bundle.EXPECTED_STRICT_REVIEW_IDS
        )
        second = self.fixture.vision_paths[strict_id][1]
        second_bytes = second.read_bytes()
        second.unlink()
        with self.assertRaisesRegex(
            bundle.DirectRecordBundleError, "requires 2 distinct accepted"
        ):
            self.fixture.assemble()
        second.write_bytes(second_bytes)

        standard_id = next(iter(bundle.EXPECTED_STANDARD_REVIEW_IDS))
        report_path = self.fixture.vision_paths[standard_id][0]
        original = json.loads(report_path.read_text(encoding="utf-8"))
        for status, decision in (("draft", "pending"), ("complete", "rejected")):
            changed = {**original, "status": status, "decision": decision}
            write_json(report_path, changed)
            with self.assertRaisesRegex(
                bundle.DirectRecordBundleError, "must be complete and accepted"
            ):
                self.fixture.assemble()

    def test_rejects_duplicate_reviewers(self):
        strict_id = next(
            sheet_id
            for sheet_id in self.fixture.ordered_ids
            if sheet_id in bundle.EXPECTED_STRICT_REVIEW_IDS
        )
        first_path, second_path = self.fixture.vision_paths[strict_id]
        first = json.loads(first_path.read_text(encoding="utf-8"))
        second = json.loads(second_path.read_text(encoding="utf-8"))
        second["reviewer"] = first["reviewer"].swapcase()
        write_json(second_path, second)
        with self.assertRaisesRegex(
            bundle.DirectRecordBundleError, "duplicate reviewer"
        ):
            self.fixture.assemble()

    def test_rejects_stale_master_hash_and_wrong_dimensions(self):
        sheet_id = self.fixture.ordered_ids[0]
        provenance_path = self.fixture.provenance_paths[sheet_id]
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        provenance["artifacts"][0]["sha256"] = "0" * 64
        write_json(provenance_path, provenance)
        with self.assertRaisesRegex(bundle.DirectRecordBundleError, "sha256 mismatch"):
            self.fixture.assemble()

        self.fixture = DirectRecordBundleFixture(self.root / "dimensions")
        master = self.fixture.masters / f"{self.fixture.ordered_ids[0]}.png"
        Image.new("RGB", (7, 8), "white").save(master)
        with self.assertRaisesRegex(
            bundle.DirectRecordBundleError, "dimensions mismatch"
        ):
            self.fixture.assemble()

    def test_rejects_missing_artifacts_and_missing_hashes(self):
        sheet_id = self.fixture.ordered_ids[0]
        self.fixture.automated_paths[sheet_id].unlink()
        with self.assertRaisesRegex(bundle.DirectRecordBundleError, "does not exist"):
            self.fixture.assemble()

        self.fixture = DirectRecordBundleFixture(self.root / "missing-hash")
        automated_path = self.fixture.automated_paths[self.fixture.ordered_ids[0]]
        automated = json.loads(automated_path.read_text(encoding="utf-8"))
        del automated["geography"]["land_sea"]["control"]["sha256"]
        write_json(automated_path, automated)
        with self.assertRaisesRegex(
            bundle.DirectRecordBundleError, "sha256 is required"
        ):
            self.fixture.assemble()

    def test_rejects_volatile_and_external_nested_paths(self):
        sheet_id = self.fixture.ordered_ids[0]
        provenance_path = self.fixture.provenance_paths[sheet_id]
        original = json.loads(provenance_path.read_text(encoding="utf-8"))

        volatile = json.loads(json.dumps(original))
        volatile["inputs"]["golden_style"] = {
            "path": "tmp/forbidden-golden.png",
            "sha256": "0" * 64,
        }
        write_json(provenance_path, volatile)
        with self.assertRaisesRegex(
            bundle.DirectRecordBundleError, "volatile|temporary|ignored"
        ):
            self.fixture.assemble()

        external = json.loads(json.dumps(original))
        external["inputs"]["golden_style"] = {
            "path": "C:/outside/golden.png",
            "sha256": "0" * 64,
        }
        write_json(provenance_path, external)
        with self.assertRaisesRegex(
            bundle.DirectRecordBundleError, "outside|escapes|repository-relative"
        ):
            self.fixture.assemble()

    def test_rejects_mixed_golden_locks_across_direct_masters(self):
        sheet_id = self.fixture.ordered_ids[1]
        alternate_golden = self.root / "alternate-golden.png"
        Image.new("RGB", (4, 4), (120, 100, 80)).save(alternate_golden)

        renderer_path = self.fixture.masters / f"{sheet_id}.report.json"
        renderer = json.loads(renderer_path.read_text(encoding="utf-8"))
        renderer["inputs"]["golden_style"] = {
            "status": "locked",
            **artifact(alternate_golden),
        }
        write_json(renderer_path, renderer)

        provenance_path = self.fixture.provenance_paths[sheet_id]
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        provenance["inputs"]["golden_style"] = artifact(alternate_golden)
        provenance["inputs"]["renderer_report"] = artifact(renderer_path)
        write_json(provenance_path, provenance)

        automated_path = self.fixture.automated_paths[sheet_id]
        automated = json.loads(automated_path.read_text(encoding="utf-8"))
        automated["provenance_report"] = artifact(provenance_path)
        write_json(automated_path, automated)

        with self.assertRaisesRegex(
            bundle.DirectRecordBundleError,
            "same locked Golden style and review artifacts",
        ):
            self.fixture.assemble()


if __name__ == "__main__":
    unittest.main()
