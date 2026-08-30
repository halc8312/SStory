import copy
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import build_phase5_assets as phase5  # noqa: E402
import phase5_vision_evidence as vision_evidence  # noqa: E402
import promote_phase5_renderer_outputs as promoter  # noqa: E402
import release_bound_artifact as bound_artifacts  # noqa: E402
import release_path_safety as path_safety  # noqa: E402
import render_phase5_parent_control_masks as parent_control_renderer  # noqa: E402
import write_phase5_source_indexes as writer  # noqa: E402
from tests.phase5_assets_test import (  # noqa: E402
    artifact,
    complete_report,
    write_automated_report,
    write_canonical_provenance_report,
    write_golden_manifest_with_two_reviews,
    write_provenance_report,
)


def write_json(path: Path, value, *, sort_keys: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=sort_keys) + "\n",
        encoding="utf-8",
    )


class RendererPromotionTests(unittest.TestCase):
    def setUp(self):
        promoter.RENDERER_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        promoter.TRACKED_MASTER_ROOT.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="release-tooling-", dir=promoter.RENDERER_TMP_ROOT
        )
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name)
        self.destination = (
            promoter.TRACKED_MASTER_ROOT / f".release-tooling-test-{uuid.uuid4().hex}"
        )
        self.addCleanup(lambda: shutil.rmtree(self.destination, ignore_errors=True))
        self.backup = self.destination.with_name(
            f".{self.destination.name}.promotion-backup-foreign-owner"
        )
        self.addCleanup(lambda: shutil.rmtree(self.backup, ignore_errors=True))

        def cleanup_transaction_debris() -> None:
            for pattern in (
                f".{self.destination.name}.promoting-*",
                f".{self.destination.name}.promotion-*",
            ):
                for path in self.destination.parent.glob(pattern):
                    if path.is_dir() and not path.is_symlink():
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        path.unlink(missing_ok=True)

        self.addCleanup(cleanup_transaction_debris)

    def _fixture(self, payload: bytes = b"renderer-output-v1") -> None:
        asset = self.source / "sheet.png"
        asset.write_bytes(payload)
        source_prefix = promoter._repo_path(self.source, "source")
        recorded_prefix = source_prefix.upper() if os.name == "nt" else source_prefix
        asset_suffix = "SHEET.PNG" if os.name == "nt" else "sheet.png"
        report_suffix = "SHEET.REPORT.JSON" if os.name == "nt" else "sheet.RePoRt.JsOn"
        child = self.source / "sheet.RePoRt.JsOn"
        write_json(
            child,
            {
                "output": {
                    "path": f"{recorded_prefix}/{asset_suffix}",
                    "sha256": promoter.sha256_file(asset),
                },
                "report_path": f"{recorded_prefix}/{report_suffix}",
                f"{recorded_prefix}/{asset_suffix}": "path stored as a JSON key",
            },
        )
        batch = self.source / "batch.JSON"
        write_json(
            batch,
            {
                "report_path": f"{recorded_prefix}/{report_suffix}",
                "report_sha256": promoter.sha256_file(child),
                "literal": f"prefix:{recorded_prefix}/sheet.png",
            },
        )

    def test_promotion_rewrites_values_and_keys_and_refreshes_mixed_case_json(self):
        self._fixture()
        result = promoter.promote_renderer_outputs(self.source, self.destination)

        self.assertTrue(result["valid"])
        self.assertEqual(result["file_count"], 3)
        self.assertEqual(result["json_file_count"], 2)
        destination_prefix = promoter._repo_path(self.destination, "destination")
        child_path = self.destination / "sheet.RePoRt.JsOn"
        child = json.loads(child_path.read_text(encoding="utf-8"))
        self.assertEqual(child["output"]["path"], f"{destination_prefix}/sheet.png")
        self.assertIn(f"{destination_prefix}/sheet.png", child)
        batch = json.loads(
            (self.destination / "batch.JSON").read_text(encoding="utf-8")
        )
        self.assertEqual(
            batch["report_path"], f"{destination_prefix}/sheet.RePoRt.JsOn"
        )
        self.assertEqual(batch["report_sha256"], promoter.sha256_file(child_path))
        self.assertTrue(batch["literal"].casefold().startswith("prefix:tmp/"))

    def test_existing_destination_requires_explicit_force(self):
        self._fixture()
        promoter.promote_renderer_outputs(self.source, self.destination)
        with self.assertRaisesRegex(
            promoter.RendererPromotionError, "refusing to overwrite"
        ):
            promoter.promote_renderer_outputs(self.source, self.destination)

        shutil.rmtree(self.source)
        self.source.mkdir(parents=True)
        self._fixture(b"renderer-output-v2")
        if not promoter._atomic_force_supported():
            with self.assertRaisesRegex(
                promoter.RendererPromotionError, "atomic directory exchange"
            ):
                promoter.promote_renderer_outputs(
                    self.source, self.destination, force=True
                )
            self.assertEqual(
                (self.destination / "sheet.png").read_bytes(), b"renderer-output-v1"
            )
            return
        result = promoter.promote_renderer_outputs(
            self.source, self.destination, force=True
        )
        self.assertTrue(result["valid"])
        self.assertEqual(
            (self.destination / "sheet.png").read_bytes(), b"renderer-output-v2"
        )

    def test_source_mutation_after_initial_validation_aborts_install(self):
        self._fixture()
        original_prepare = promoter._prepare_promotion

        def prepare_then_mutate(*args, **kwargs):
            prepared = original_prepare(*args, **kwargs)
            (self.source / "sheet.png").write_bytes(b"mutated-after-binding")
            return prepared

        with mock.patch.object(
            promoter, "_prepare_promotion", side_effect=prepare_then_mutate
        ):
            with self.assertRaisesRegex(
                promoter.RendererPromotionError, "changed after.*snapshot"
            ):
                promoter.promote_renderer_outputs(self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_external_mutation_cannot_be_legitimated_by_staged_rehash(self):
        self._fixture()
        external = promoter.TRACKED_MASTER_ROOT / (
            f".release-tooling-external-{uuid.uuid4().hex}.bin"
        )
        external.write_bytes(b"external-v1")
        self.addCleanup(lambda: external.unlink(missing_ok=True))
        report = self.source / "external.json"
        write_json(report, {"external": artifact(external)})
        original_prepare = promoter._prepare_promotion

        def mutate_then_prepare(*args, **kwargs):
            external.write_bytes(b"external-v2")
            return original_prepare(*args, **kwargs)

        with mock.patch.object(
            promoter, "_prepare_promotion", side_effect=mutate_then_prepare
        ):
            with self.assertRaisesRegex(
                promoter.RendererPromotionError, "changed after.*snapshot"
            ):
                promoter.promote_renderer_outputs(self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_remaining_windows_tmp_alias_aborts_without_installing(self):
        asset = self.source / "sheet.png"
        asset.write_bytes(b"renderer-output")
        source_prefix = promoter._repo_path(self.source, "source")
        stale = (
            "TMP/map-production/unrelated/output.png"
            if os.name == "nt"
            else "tmp/map-production/unrelated/output.png"
        )
        write_json(
            self.source / "report.JSON",
            {
                "output": {
                    "path": f"{source_prefix}/sheet.png",
                    "sha256": promoter.sha256_file(asset),
                },
                stale: "tmp alias stored as a JSON key",
            },
        )
        with self.assertRaisesRegex(
            promoter.RendererPromotionError, "retains tmp references"
        ):
            promoter.promote_renderer_outputs(self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_stale_backup_is_never_restored_or_removed(self):
        self._fixture()
        promoter.promote_renderer_outputs(self.source, self.destination)
        installed_before = promoter._tree_hashes(self.destination)
        self.backup.mkdir()
        (self.backup / "owner.txt").write_text("stale-owner", encoding="utf-8")

        with self.assertRaisesRegex(
            promoter.RendererPromotionError, "stale promotion backup"
        ):
            promoter.promote_renderer_outputs(self.source, self.destination, force=True)
        self.assertEqual(promoter._tree_hashes(self.destination), installed_before)
        self.assertEqual(
            (self.backup / "owner.txt").read_text(encoding="utf-8"),
            "stale-owner",
        )

    def test_stale_promoting_tree_is_detected_and_preserved(self):
        self._fixture()
        orphan = self.destination.with_name(
            f".{self.destination.name}.promoting-foreign-owner"
        )
        orphan.mkdir()
        (orphan / "owner.txt").write_text("foreign-owner", encoding="utf-8")

        with self.assertRaisesRegex(
            promoter.RendererPromotionError, "transaction debris"
        ):
            promoter.promote_renderer_outputs(self.source, self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual(
            (orphan / "owner.txt").read_text(encoding="utf-8"),
            "foreign-owner",
        )

    def test_destination_lock_does_not_relabel_body_file_exists(self):
        lock = self.destination.with_name(f".{self.destination.name}.promotion.lock")
        with self.assertRaisesRegex(FileExistsError, "body race"):
            with promoter._exclusive_destination_lock(self.destination):
                raise FileExistsError("body race")
        self.assertFalse(lock.exists())

    def test_git_control_entries_are_rejected_before_copy(self):
        self._fixture()
        (self.source / ".gitignore").write_text("*.png\n", encoding="utf-8")
        with self.assertRaisesRegex(
            promoter.RendererPromotionError, "forbidden Git control entry"
        ):
            promoter.promote_renderer_outputs(self.source, self.destination)
        self.assertFalse(self.destination.exists())

        (self.source / ".gitignore").unlink()
        git_dir = self.source / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[core]\n", encoding="utf-8")
        with self.assertRaisesRegex(
            promoter.RendererPromotionError, "forbidden Git control entry"
        ):
            promoter.promote_renderer_outputs(self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_release_paths_reject_git_ads_and_drive_relative_spellings(self):
        cases = (
            ("world/.git/config", "Git control directory"),
            ("world/map-production/master.png:payload", "alternate data stream"),
            ("C:world/map-production/master.png", "drive-relative"),
        )
        for raw_path, diagnostic in cases:
            with self.subTest(raw_path=raw_path):
                with self.assertRaisesRegex(path_safety.ReleasePathError, diagnostic):
                    path_safety.canonical_repo_relative(
                        raw_path, label="adversarial release path"
                    )

    def test_baseexception_after_install_restores_force_backup(self):
        if not promoter._atomic_force_supported():
            self.skipTest("atomic directory exchange is unavailable")
        self._fixture()
        promoter.promote_renderer_outputs(self.source, self.destination)
        before = promoter._tree_hashes(self.destination)
        original_tree_hashes = promoter._tree_hashes

        def interrupt_installed_tree(root: Path):
            if promoter.same_path(root, self.destination):
                raise KeyboardInterrupt("synthetic post-install interrupt")
            return original_tree_hashes(root)

        with mock.patch.object(
            promoter, "_tree_hashes", side_effect=interrupt_installed_tree
        ):
            with self.assertRaises(KeyboardInterrupt):
                promoter.promote_renderer_outputs(
                    self.source, self.destination, force=True
                )
        self.assertEqual(promoter._tree_hashes(self.destination), before)
        self.assertEqual(
            list(self.destination.parent.glob(f".{self.destination.name}.promotion-*")),
            [],
        )

    def test_no_force_concurrent_destination_is_not_clobbered(self):
        self._fixture()
        original_prepare = promoter._prepare_promotion

        def prepare_and_race(*args, **kwargs):
            prepared = original_prepare(*args, **kwargs)
            self.destination.mkdir()
            (self.destination / "competitor.txt").write_text(
                "competitor", encoding="utf-8"
            )
            return prepared

        with mock.patch.object(
            promoter, "_prepare_promotion", side_effect=prepare_and_race
        ):
            with self.assertRaisesRegex(
                promoter.RendererPromotionError, "appeared during no-clobber"
            ):
                promoter.promote_renderer_outputs(self.source, self.destination)
        self.assertEqual(
            (self.destination / "competitor.txt").read_text(encoding="utf-8"),
            "competitor",
        )

    @unittest.skipUnless(os.name == "nt", "NTFS junction test is Windows-only")
    def test_source_junction_is_rejected_without_traversal(self):
        target_parent = tempfile.TemporaryDirectory(
            prefix="junction-target-", dir=promoter.RENDERER_TMP_ROOT
        )
        self.addCleanup(target_parent.cleanup)
        target = Path(target_parent.name)
        (target / "payload.bin").write_bytes(b"junction-payload")
        junction = self.source / "linked-output"
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            self.skipTest(f"junction creation unsupported: {result.stderr.strip()}")

        def remove_junction() -> None:
            if junction.exists():
                os.rmdir(junction)

        self.addCleanup(remove_junction)
        with self.assertRaisesRegex(
            promoter.RendererPromotionError, "junction, or reparse point"
        ):
            promoter.promote_renderer_outputs(self.source, self.destination)


class SourceIndexWriterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix=".phase5-release-tooling-test-", dir=REPO_ROOT
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        writer.TRACKED_RELEASE_ROOT.mkdir(parents=True, exist_ok=True)
        self.output_root = writer.TRACKED_RELEASE_ROOT / (
            f".source-index-writer-test-{uuid.uuid4().hex}"
        )
        self.output_root.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(self.output_root, ignore_errors=True))

        catalog, catalog_by_id, derived = phase5.load_contract(
            phase5.DEFAULT_CONTRACT, phase5.DEFAULT_MAP_SHEETS
        )
        self.catalog = catalog
        self.catalog_by_id = catalog_by_id
        self.real_contracts = derived["sheets"]
        self.contracts = {
            sheet_id: {**contract, "width": 8, "height": 8}
            for sheet_id, contract in self.real_contracts.items()
        }
        self.load_contract_result = (
            self.catalog,
            self.catalog_by_id,
            {"sheets": self.contracts},
        )
        self.world_id = next(iter(writer.EXPECTED_WORLD_IDS))
        self.continent_ids = sorted(writer.EXPECTED_CONTINENT_IDS)
        self.direct_ids = sorted(writer.EXPECTED_DIRECT_IDS)

        self.golden = self.root / "golden.png"
        Image.new("RGB", (32, 24), "gold").save(self.golden)
        self.dummy_manifest, _ = write_golden_manifest_with_two_reviews(
            self.root, master=self.golden
        )
        self.master = self.root / "master.png"
        Image.new("RGB", (8, 8), "white").save(self.master)
        self.provenance = self.root / "provenance.json"
        self.automated = self.root / "automated.json"
        self.vision = self.root / "vision.json"
        for path, value in (
            (self.provenance, {"kind": "provenance"}),
            (self.automated, {"status": "passed"}),
            (self.vision, {"decision": "accepted"}),
        ):
            write_json(path, value)

    def _canonical_vision_receipt(self, master: Path, sheet_id: str) -> dict[str, str]:
        version = vision_evidence.CANONICAL_EVIDENCE_ROOT / (
            f"test-{uuid.uuid4().hex}"
        )
        self.addCleanup(lambda: shutil.rmtree(version, ignore_errors=True))
        registry = vision_evidence.load_focus_registry()
        entry = registry.entry(sheet_id)
        source = vision_evidence.bind_file(
            master, label=f"{sheet_id} source-index integration master"
        )
        focus_box = list(entry["box_px"])
        source_size, views = vision_evidence.render_view_artifacts(source, focus_box)
        document = vision_evidence.build_canonical_receipt(
            sheet_id=sheet_id,
            source=source,
            source_size=source_size,
            focus_registry=registry.binding,
            focus_box=focus_box,
            views=views,
        )
        receipt = (
            version
            / sheet_id
            / vision_evidence.PERSISTENT_RECEIPT_FILENAME
        )
        receipt.parent.mkdir(parents=True)
        receipt.write_bytes(vision_evidence.stable_json_bytes(document))
        return artifact(receipt)

    def _integration_vision_receipt(
        self, root: Path, master: Path, sheet_id: str
    ) -> dict[str, str]:
        receipt = root / "fixture-vision-evidence" / sheet_id / "view-bundle.json"
        document = {
            "fixture_schema_version": "1.0.0",
            "sheet_id": sheet_id,
            "source": artifact(master),
            "focus_registry": artifact(vision_evidence.DEFAULT_FOCUS_REGISTRY),
        }
        receipt.parent.mkdir(parents=True)
        receipt.write_bytes(vision_evidence.stable_json_bytes(document))
        return artifact(receipt)

    def _validate_integration_vision_evidence(
        self,
        report: dict,
        *,
        sheet_id: str,
        master_path: Path,
        master_sha256: str,
        focus_registry_path=None,
    ) -> vision_evidence.VisionEvidenceBindings:
        bundle = report.get("vision_bundle")
        if not isinstance(bundle, dict) or (
            bundle.get("reviewer_confirmed_exact_five") is not True
        ):
            raise vision_evidence.Phase5VisionEvidenceError(
                "integration reviewer did not confirm the exact-five bundle"
            )
        source = vision_evidence.bind_file(
            master_path, label=f"{sheet_id} integration Vision source"
        )
        if source.sha256 != master_sha256:
            raise vision_evidence.Phase5VisionEvidenceError(
                f"{sheet_id} integration Vision source hash mismatch"
            )
        if (
            report.get("image_path") != source.relative
            or report.get("image_sha256") != source.sha256
        ):
            raise vision_evidence.Phase5VisionEvidenceError(
                f"{sheet_id} integration Vision report source binding mismatch"
            )

        receipt_spec = bundle.get("receipt")
        if not isinstance(receipt_spec, dict):
            raise vision_evidence.Phase5VisionEvidenceError(
                f"{sheet_id} integration Vision receipt is missing"
            )
        receipt = vision_evidence.bind_file(
            receipt_spec.get("path"),
            label=f"{sheet_id} integration Vision receipt",
        )
        if receipt.sha256 != receipt_spec.get("sha256"):
            raise vision_evidence.Phase5VisionEvidenceError(
                f"{sheet_id} integration Vision receipt hash mismatch"
            )

        registry_path = (
            vision_evidence.DEFAULT_FOCUS_REGISTRY
            if focus_registry_path is None
            else Path(focus_registry_path)
        )
        if not path_safety.same_path(
            registry_path, vision_evidence.DEFAULT_FOCUS_REGISTRY
        ):
            raise vision_evidence.Phase5VisionEvidenceError(
                "integration Vision fixture requires the canonical focus registry"
            )
        registry = vision_evidence.bind_file(
            registry_path, label="integration canonical focus registry"
        )
        document = receipt.json_object()
        expected = {
            "fixture_schema_version": "1.0.0",
            "sheet_id": sheet_id,
            "source": source.artifact(),
            "focus_registry": registry.artifact(),
        }
        if document != expected or (
            vision_evidence.stable_json_bytes(document) != receipt.data
        ):
            raise vision_evidence.Phase5VisionEvidenceError(
                f"{sheet_id} integration Vision receipt binding mismatch"
            )
        return vision_evidence.VisionEvidenceBindings(source, receipt, registry)

    def _assert_integration_vision_calls(
        self, validator: mock.Mock, records: dict[str, dict]
    ) -> None:
        expected = sorted(
            (
                sheet_id,
                record["path"],
                record["sha256"],
            )
            for sheet_id, record in records.items()
            for _ in record["vision_reports"]
            for _ in range(2)  # Pre-install and installed-candidate validation.
        )
        actual = []
        for recorded_call in validator.call_args_list:
            self.assertEqual(len(recorded_call.args), 1)
            self.assertEqual(
                set(recorded_call.kwargs),
                {"sheet_id", "master_path", "master_sha256"},
            )
            actual.append(
                (
                    recorded_call.kwargs["sheet_id"],
                    phase5.repo_path(Path(recorded_call.kwargs["master_path"])),
                    recorded_call.kwargs["master_sha256"],
                )
            )
        self.assertEqual(sorted(actual), expected)

    def _record(self, sheet_id: str) -> dict:
        sheet_type = self.catalog_by_id[sheet_id]["sheet_type"]
        return {
            "sheet_id": sheet_id,
            "kind": (
                phase5.CANONICAL_RENDER_SOURCE_KIND
                if sheet_type in writer.DIRECT_TYPES
                else "composite_master"
            ),
            "path": phase5.repo_path(self.master),
            "provenance_report": phase5.repo_path(self.provenance),
            "automated_report": phase5.repo_path(self.automated),
            "vision_reports": [phase5.repo_path(self.vision)],
        }

    def _bundle(self, name: str, sheet_ids: list[str], *, records=None) -> Path:
        path = self.root / name
        write_json(
            path,
            {
                "schema_version": "1.0.0",
                "release_id": "world-v3",
                "records": (
                    records
                    if records is not None
                    else [self._record(sheet_id) for sheet_id in sheet_ids]
                ),
            },
            sort_keys=False,
        )
        return path

    def _mocked_validation(self):
        return (
            mock.patch.object(
                writer.phase5, "load_contract", return_value=self.load_contract_result
            ),
            mock.patch.object(
                writer.phase5,
                "verify_manifest_golden_style",
                return_value={"master": artifact(self.golden)},
            ),
            mock.patch.object(writer.phase5, "preflight_source_entry"),
        )

    def _write_mocked(self, **kwargs):
        patches = self._mocked_validation()
        kwargs.setdefault("base_manifest_path", self.dummy_manifest)
        with patches[0], patches[1], patches[2]:
            return writer.write_source_index(**kwargs)

    def _real_direct_candidate(self) -> tuple[Path, Path, Path, str]:
        root = self.root / "real-evidence"
        root.mkdir()
        golden = root / "golden.png"
        Image.new("RGB", (32, 24), "gold").save(golden)
        manifest, golden_reports = write_golden_manifest_with_two_reviews(
            root, master=golden
        )
        renderer = root / "canonical_renderer.py"
        renderer.write_text(
            "# deterministic canonical renderer fixture\n", encoding="utf-8"
        )
        material_atlas = root / "material-atlas.png"
        Image.new("RGB", (16, 16), "tan").save(material_atlas)
        inverse_roles = {
            value: key for key, value in phase5.RENDERER_SOURCE_ROLE_MAP.items()
        }
        sheet_id = min(
            self.direct_ids,
            key=lambda candidate: (
                self.real_contracts[candidate]["width"]
                * self.real_contracts[candidate]["height"]
            ),
        )
        sheet = self.catalog_by_id[sheet_id]
        contract = self.real_contracts[sheet_id]
        size = (contract["width"], contract["height"])
        master = root / f"{sheet_id}-master.png"
        Image.new("RGB", size, (220, 210, 180)).save(master)
        observed_land = root / f"{sheet_id}-observed-land.png"
        observed_transport = root / f"{sheet_id}-observed-transport.png"
        Image.new("L", size, 255).save(observed_land)
        Image.new("L", size, 255).save(observed_transport)
        renderer_report = root / f"{sheet_id}-renderer-report.JSON"
        write_json(
            renderer_report,
            {
                "status": "passed",
                "coordinate_reference_system": "EA-WORLD-1",
                "generated_by": {
                    "id": phase5.CANONICAL_RENDERER_ID,
                    **artifact(renderer),
                },
                "inputs": {
                    "golden_style": {"status": "locked", **artifact(golden)},
                    "material_atlas": {
                        "status": "locked",
                        **artifact(material_atlas),
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
                    "source_coordinates_modified": False,
                    "world_crop_or_upscale_used": False,
                },
                "outputs": {
                    "master": {
                        **artifact(master),
                        "width": size[0],
                        "height": size[1],
                        "format": "PNG",
                        "mode": "RGB",
                    },
                    "observed_land_sea_mask": artifact(observed_land),
                    "observed_transport_mask": artifact(observed_transport),
                },
            },
        )
        provenance = write_canonical_provenance_report(
            root,
            sheet_id=sheet_id,
            master=master,
            golden_style=artifact(golden),
            golden_vision_reports=golden_reports,
            renderer=renderer,
            renderer_report=renderer_report,
            material_atlas=material_atlas,
        )
        automated = write_automated_report(
            root,
            sheet_id=sheet_id,
            master=master,
            provenance=provenance,
            source_kind=phase5.CANONICAL_RENDER_SOURCE_KIND,
        )
        vision_specs = []
        vision_receipt = self._canonical_vision_receipt(master, sheet_id)
        reviewers = ("Canonical Reviewer A", "Canonical Reviewer B")
        for review_index, reviewer in enumerate(
            reviewers[: phase5.required_review_count(sheet)]
        ):
            vision_path = root / f"{sheet_id}-vision-{review_index + 1}.json"
            report = complete_report(
                phase5.job_id_for_sheet(sheet_id),
                phase5.repo_path(master),
                reviewer,
                phase5.acceptance_threshold(sheet),
            )
            report["vision_bundle"]["receipt"] = vision_receipt
            write_json(vision_path, report)
            vision_specs.append(artifact(vision_path))
        record = {
            "sheet_id": sheet_id,
            "kind": phase5.CANONICAL_RENDER_SOURCE_KIND,
            **artifact(master),
            "provenance_report": provenance,
            "automated_report": automated,
            "vision_reports": vision_specs,
        }
        candidate = root / "real-production-dimension-source-index.json"
        write_json(
            candidate,
            {
                "schema_version": "1.3.0",
                "coordinate_reference_system": "EA-WORLD-1",
                "golden_style": artifact(golden),
                "sources": [record],
            },
            sort_keys=False,
        )
        return candidate, golden, manifest, sheet_id

    def _integration_direct_fixture(
        self,
    ) -> tuple[dict[str, dict], Path, Path]:
        root = self.root / "idx22-idx23-direct-evidence"
        root.mkdir()
        golden = root / "golden.png"
        Image.new("RGB", (32, 24), "gold").save(golden)
        manifest, golden_reports = write_golden_manifest_with_two_reviews(
            root, master=golden
        )
        renderer = root / "canonical_renderer.py"
        renderer.write_text("# integration renderer fixture\n", encoding="utf-8")
        material_atlas = root / "material-atlas.png"
        Image.new("RGB", (16, 16), "tan").save(material_atlas)
        inverse_roles = {
            value: key for key, value in phase5.RENDERER_SOURCE_ROLE_MAP.items()
        }
        records: dict[str, dict] = {}
        for position, sheet_id in enumerate(self.direct_ids):
            sheet = self.catalog_by_id[sheet_id]
            master = root / f"{sheet_id}-master.png"
            Image.new("RGB", (8, 8), (220 - position, 210, 180)).save(master)
            observed_land = root / f"{sheet_id}-observed-land.png"
            observed_transport = root / f"{sheet_id}-observed-transport.png"
            Image.new("L", (8, 8), 255).save(observed_land)
            Image.new("L", (8, 8), 255).save(observed_transport)
            renderer_report = root / f"{sheet_id}-renderer-report.json"
            write_json(
                renderer_report,
                {
                    "status": "passed",
                    "coordinate_reference_system": "EA-WORLD-1",
                    "generated_by": {
                        "id": phase5.CANONICAL_RENDERER_ID,
                        **artifact(renderer),
                    },
                    "inputs": {
                        "golden_style": {"status": "locked", **artifact(golden)},
                        "material_atlas": {
                            "status": "locked",
                            **artifact(material_atlas),
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
                },
            )
            provenance = write_canonical_provenance_report(
                root,
                sheet_id=sheet_id,
                master=master,
                golden_style=artifact(golden),
                golden_vision_reports=golden_reports,
                renderer=renderer,
                renderer_report=renderer_report,
                material_atlas=material_atlas,
            )
            automated = write_automated_report(
                root,
                sheet_id=sheet_id,
                master=master,
                provenance=provenance,
                source_kind=phase5.CANONICAL_RENDER_SOURCE_KIND,
            )
            vision_specs = []
            vision_receipt = self._integration_vision_receipt(
                root, master, sheet_id
            )
            reviewers = ("Integration Reviewer A", "Integration Reviewer B")
            for review_index, reviewer in enumerate(
                reviewers[: phase5.required_review_count(sheet)]
            ):
                vision_path = root / f"{sheet_id}-vision-{review_index + 1}.json"
                report = complete_report(
                    phase5.job_id_for_sheet(sheet_id),
                    phase5.repo_path(master),
                    reviewer,
                    phase5.acceptance_threshold(sheet),
                )
                report["vision_bundle"]["receipt"] = vision_receipt
                write_json(
                    vision_path,
                    report,
                )
                vision_specs.append(artifact(vision_path))
            records[sheet_id] = {
                "sheet_id": sheet_id,
                "kind": phase5.CANONICAL_RENDER_SOURCE_KIND,
                **artifact(master),
                "provenance_report": provenance,
                "automated_report": automated,
                "vision_reports": vision_specs,
            }
        return records, golden, manifest

    def _integration_composite_records(
        self,
        root_name: str,
        parent_ids: list[str],
        child_sources: dict[str, dict],
        *,
        child_source_index_path: Path,
        omit_child_for: str | None = None,
    ) -> dict[str, dict]:
        root = self.root / root_name
        root.mkdir()
        parent_index, parent_report, parent_control_specs = (
            self._integration_parent_control_fixture()
        )
        records: dict[str, dict] = {}
        for position, sheet_id in enumerate(parent_ids):
            sheet = self.catalog_by_id[sheet_id]
            expected_children = sorted(
                phase5._expected_composite_children(sheet, self.catalog_by_id)
            )
            if sheet_id == omit_child_for:
                expected_children = expected_children[1:]
            children = [
                {
                    "sheet_id": child_id,
                    "path": child_sources[child_id]["path"],
                    "sha256": child_sources[child_id]["sha256"],
                    "native_zoom": self.contracts[child_id]["native_zoom"],
                }
                for child_id in expected_children
            ]
            master = root / f"{sheet_id}-master.png"
            Image.new("RGB", (8, 8), (180, 190 + position, 200)).save(master)
            land_control = phase5.resolve_repo_artifact(
                parent_control_specs[sheet_id]["land_sea_control"]["path"],
                f"{sheet_id} integration parent land control",
            )
            route_control = phase5.resolve_repo_artifact(
                parent_control_specs[sheet_id]["transport_control"]["path"],
                f"{sheet_id} integration parent transport control",
            )
            observed_land = root / f"{sheet_id}-observed-land.png"
            observed_transport = root / f"{sheet_id}-observed-transport.png"
            with Image.open(land_control) as opened:
                observed = opened.copy()
            observed.putpixel((0, 0), 0 if observed.getpixel((0, 0)) else 255)
            observed.save(observed_land, format="PNG", compress_level=9)
            observed.close()
            with Image.open(route_control) as opened:
                observed = opened.copy()
            for x in range(observed.width):
                observed.putpixel((x, 4), 255)
            observed.save(observed_transport, format="PNG", compress_level=9)
            observed.close()
            provenance = write_provenance_report(
                root,
                sheet_id=sheet_id,
                master=master,
                method="deterministic-parent-composite",
                children=children,
            )
            provenance_path = phase5.resolve_repo_artifact(
                provenance["path"], f"{sheet_id} integration provenance"
            )
            provenance_document = json.loads(
                provenance_path.read_text(encoding="utf-8")
            )
            provenance_document["inputs"]["source_index"] = artifact(
                child_source_index_path
            )
            structured = provenance_document["artifacts"][0]["provenance"]
            structured.update(
                {
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
                        "land_sea": artifact(observed_land),
                        "transport": artifact(observed_transport),
                    },
                    "composition": {
                        "child_order": [
                            item["sheet_id"]
                            for item in sorted(
                                children,
                                key=lambda item: (
                                    item["native_zoom"],
                                    item["sheet_id"],
                                ),
                            )
                        ],
                        "resampling": "LANCZOS-downsample-only",
                        "upscaled_child_count": 0,
                        "base_rendered_at_parent_native_resolution": True,
                    },
                }
            )
            write_json(provenance_path, provenance_document)
            provenance = artifact(provenance_path)
            automated = write_automated_report(
                root,
                sheet_id=sheet_id,
                master=master,
                provenance=provenance,
                source_kind="composite_master",
            )
            automated_path = phase5.resolve_repo_artifact(
                automated["path"], f"{sheet_id} integration automated QA"
            )
            automated_document = json.loads(automated_path.read_text(encoding="utf-8"))
            automated_document["parent_controls"] = {
                "index": artifact(parent_index),
                "report": artifact(parent_report),
            }
            automated_document["geography"] = {
                "land_sea": {
                    "passed": True,
                    "control": {
                        key: parent_control_specs[sheet_id]["land_sea_control"][key]
                        for key in ("path", "sha256")
                    },
                    "observed": artifact(observed_land),
                    "minimum_match_ratio": 0.98,
                    "match_ratio": 63 / 64,
                },
                "transport": {
                    "passed": True,
                    "control": {
                        key: parent_control_specs[sheet_id]["transport_control"][key]
                        for key in ("path", "sha256")
                    },
                    "observed": artifact(observed_transport),
                    "tolerance_px": 1,
                    "minimum_within_tolerance_ratio": 0.95,
                    "control_within_tolerance_ratio": 1.0,
                    "observed_within_tolerance_ratio": 1.0,
                },
            }
            write_json(automated_path, automated_document)
            automated = artifact(automated_path)
            vision_specs = []
            vision_receipt = self._integration_vision_receipt(
                root, master, sheet_id
            )
            reviewers = ("Composite Reviewer A", "Composite Reviewer B")
            for review_index, reviewer in enumerate(
                reviewers[: phase5.required_review_count(sheet)]
            ):
                vision_path = root / f"{sheet_id}-vision-{review_index + 1}.json"
                report = complete_report(
                    phase5.job_id_for_sheet(sheet_id),
                    phase5.repo_path(master),
                    reviewer,
                    phase5.acceptance_threshold(sheet),
                )
                report["vision_bundle"]["receipt"] = vision_receipt
                write_json(
                    vision_path,
                    report,
                )
                vision_specs.append(artifact(vision_path))
            records[sheet_id] = {
                "sheet_id": sheet_id,
                "kind": "composite_master",
                **artifact(master),
                "provenance_report": provenance,
                "automated_report": automated,
                "vision_reports": vision_specs,
            }
        return records

    def _integration_parent_control_fixture(
        self,
    ) -> tuple[Path, Path, dict[str, dict]]:
        existing = getattr(self, "_integration_parent_controls", None)
        if existing is not None:
            return existing
        root = self.root / "idx22-idx23-parent-controls"
        root.mkdir()
        sheets = []
        controls_by_sheet: dict[str, dict] = {}
        for sheet_id in parent_control_renderer.EXPECTED_PARENT_IDS:
            control_dir = root / sheet_id / "qa"
            control_dir.mkdir(parents=True)
            land = control_dir / "land-sea-control.png"
            route = control_dir / "transport-control.png"
            Image.new("L", (8, 8), 255).save(land, format="PNG")
            route_image = Image.new("L", (8, 8), 0)
            for x in range(route_image.width):
                route_image.putpixel((x, 3), 255)
            route_image.save(route, format="PNG")
            route_image.close()
            controls = {
                "land_sea_control": {
                    **artifact(land),
                    "width": 8,
                    "height": 8,
                    "format": "PNG",
                    "color_mode": "L",
                    "binary_values": [255],
                    "on_pixel_count": 64,
                },
                "transport_control": {
                    **artifact(route),
                    "width": 8,
                    "height": 8,
                    "format": "PNG",
                    "color_mode": "L",
                    "binary_values": [0, 255],
                    "on_pixel_count": 8,
                },
            }
            controls_by_sheet[sheet_id] = controls
            catalog_sheet = self.catalog_by_id[sheet_id]
            contract = self.contracts[sheet_id]
            sheets.append(
                {
                    "sheet_id": sheet_id,
                    "sheet_type": catalog_sheet["sheet_type"],
                    "parent_id": catalog_sheet.get("parent_id"),
                    "source_feature_id": catalog_sheet.get("source_feature_id"),
                    "bounds": contract["bounds"],
                    "native_zoom": contract["native_zoom"],
                    "pixel_bounds": contract["pixel_bounds"],
                    "width": 8,
                    "height": 8,
                    "qa_controls": controls,
                    "metrics": {
                        "total_pixel_count": 64,
                        "land_pixel_count": 64,
                        "water_pixel_count": 0,
                        "transport_pixel_count": 8,
                    },
                }
            )
        index = root / "index.json"
        index_document = {"sheets": sheets}
        write_json(index, index_document, sort_keys=False)
        report = root / "report.json"
        report_document = {
            "index": artifact(index),
            "outputs": [
                {
                    "sheet_id": sheet_id,
                    "role": role,
                    "path": record["path"],
                    "sha256": record["sha256"],
                }
                for sheet_id, controls in controls_by_sheet.items()
                for role, record in controls.items()
            ],
        }
        write_json(report, report_document, sort_keys=False)
        self._integration_parent_control_documents = (
            index_document,
            report_document,
        )
        self._integration_parent_controls = (index, report, controls_by_sheet)
        return self._integration_parent_controls

    def test_real_preflight_uses_true_production_dimensions_and_context(self):
        candidate, golden, manifest, sheet_id = self._real_direct_candidate()
        contract = self.real_contracts[sheet_id]
        self.assertEqual(
            (contract["width"], contract["height"]),
            (2377, 1147),
        )
        canonical_inputs = writer._bind_canonical_inputs(
            phase5.DEFAULT_MAP_SHEETS,
            phase5.DEFAULT_CONTRACT,
            phase5.DEFAULT_CANONICAL_CONTROL_INDEX,
        )
        writer._validate_candidate(
            candidate,
            golden_style=artifact(golden),
            base_manifest=writer._bind_repo_file(
                manifest, "real production-dimension manifest"
            ),
            canonical_inputs=canonical_inputs,
            catalog_by_id=self.catalog_by_id,
            contracts=self.real_contracts,
        )

    def test_artifact_graph_uses_report_relative_provenance_paths_exclusively(self):
        basename = f"phase5-evidence-collision-{uuid.uuid4().hex}.bin"
        repo_root_artifact = REPO_ROOT / basename
        repo_root_artifact.write_bytes(b"repository-root-bytes")
        self.addCleanup(lambda: repo_root_artifact.unlink(missing_ok=True))
        report_root = self.root / "collision-report"
        report_root.mkdir()
        report_artifact = report_root / basename
        report_artifact.write_bytes(b"report-relative-bytes")
        report = report_root / "provenance.json"
        write_json(
            report,
            {
                "schema_version": "1.0.0",
                "generated_by": phase5.GENERATOR_ID,
                "inputs": {
                    "explicit_repo_root": {
                        "path": basename,
                        "sha256": phase5.sha256_file(repo_root_artifact),
                    }
                },
                "artifacts": [
                    {
                        "sheet_id": "collision_fixture",
                        "path": basename,
                        "sha256": phase5.sha256_file(report_artifact),
                    }
                ],
            },
        )

        writer._audit_artifact_graph([artifact(report)])

    def test_git_ignore_check_observes_new_nested_ignore_file(self):
        nested = self.root / "dynamic-ignore"
        nested.mkdir()
        candidate = nested / "new-artifact.bin"
        path_safety.require_trackable_path(
            candidate,
            label="pre-ignore candidate",
            must_exist=False,
        )
        (nested / ".gitignore").write_text("new-artifact.bin\n", encoding="utf-8")

        with self.assertRaisesRegex(path_safety.ReleasePathError, "ignored by Git"):
            path_safety.require_trackable_path(
                candidate,
                label="post-ignore candidate",
                must_exist=False,
            )

    def test_real_idx22_and_idx23_composite_child_sets_are_enforced(self):
        locked_child = artifact(self.master)

        def verify_parent(parent_id: str) -> set[str]:
            sheet = self.catalog_by_id[parent_id]
            expected = phase5._expected_composite_children(sheet, self.catalog_by_id)
            sources = {
                child_id: {
                    "sha256": locked_child["sha256"],
                    "provenance_report": artifact(self.provenance),
                    "automated_report": artifact(self.automated),
                    "vision_reports": [artifact(self.vision)],
                }
                for child_id in expected
            }
            phase5._verify_composite_provenance(
                {
                    "children": [
                        {"sheet_id": child_id, **locked_child}
                        for child_id in sorted(expected)
                    ],
                    "acceptance_inferred": False,
                },
                sheet=sheet,
                catalog_by_id=self.catalog_by_id,
                sources=sources,
                label=f"real {parent_id} child provenance",
            )
            return expected

        continent_id = self.continent_ids[0]
        continent_children = verify_parent(continent_id)
        self.assertTrue(continent_children)
        self.assertTrue(continent_children <= set(self.direct_ids))
        world_children = verify_parent(self.world_id)
        self.assertEqual(world_children, set(self.continent_ids))
        self.assertGreater(self.real_contracts[self.world_id]["width"], 8)
        self.assertGreater(self.real_contracts[self.world_id]["height"], 8)

    def test_idx22_idx23_writer_preflight_accepts_and_rejects_child_evidence(self):
        direct, golden, manifest = self._integration_direct_fixture()
        base_idx17 = self.root / "integration-base-idx17.json"
        write_json(
            base_idx17,
            {
                "schema_version": "1.3.0",
                "coordinate_reference_system": "EA-WORLD-1",
                "golden_style": artifact(golden),
                "sources": writer._ordered_sources(direct, self.catalog),
            },
            sort_keys=False,
        )
        valid_continents = self._integration_composite_records(
            "valid-continent-evidence",
            self.continent_ids,
            direct,
            child_source_index_path=base_idx17,
        )
        invalid_continent_id = self.continent_ids[0]
        invalid_continents = self._integration_composite_records(
            "invalid-continent-evidence",
            self.continent_ids,
            direct,
            child_source_index_path=base_idx17,
            omit_child_for=invalid_continent_id,
        )
        valid_continent_bundle = self._bundle(
            "valid-continent-records.json",
            [],
            records=list(valid_continents.values()),
        )
        invalid_continent_bundle = self._bundle(
            "invalid-continent-records.json",
            [],
            records=list(invalid_continents.values()),
        )
        invalid_idx22 = self.output_root / "invalid-preflight-idx22.json"
        idx22 = self.output_root / "valid-preflight-idx22.json"

        parent_documents = self._integration_parent_control_documents
        with (
            mock.patch.object(
                writer.phase5, "load_contract", return_value=self.load_contract_result
            ),
            mock.patch.object(
                parent_control_renderer,
                "load_validated_parent_control_bundle",
                return_value=parent_documents,
            ),
            mock.patch.object(
                parent_control_renderer,
                "load_validated_parent_control_bundle_snapshot",
                return_value=parent_documents,
            ),
            mock.patch.object(
                writer.phase5,
                "_bound_directory_snapshot",
                return_value=contextlib.nullcontext(
                    self._integration_parent_controls[0].parent
                ),
            ),
            mock.patch.object(
                writer.phase5.vision_evidence,
                "validate_report_vision_bundle",
                autospec=True,
                side_effect=self._validate_integration_vision_evidence,
            ) as validate_vision,
        ):
            with self.assertRaisesRegex(
                writer.SourceIndexWriterError, "child coverage mismatch"
            ):
                writer.write_source_index(
                    stage="idx22",
                    record_paths=[invalid_continent_bundle],
                    output_path=invalid_idx22,
                    base_index_path=base_idx17,
                    base_manifest_path=manifest,
                )
            self.assertFalse(invalid_idx22.exists())
            validate_vision.reset_mock()
            idx22_result = writer.write_source_index(
                stage="idx22",
                record_paths=[valid_continent_bundle],
                output_path=idx22,
                base_index_path=base_idx17,
                base_manifest_path=manifest,
            )
            self._assert_integration_vision_calls(
                validate_vision, {**direct, **valid_continents}
            )

        self.assertEqual(idx22_result["source_count"], 22)
        valid_world = self._integration_composite_records(
            "valid-world-evidence",
            [self.world_id],
            valid_continents,
            child_source_index_path=idx22,
        )
        invalid_world = self._integration_composite_records(
            "invalid-world-evidence",
            [self.world_id],
            valid_continents,
            child_source_index_path=idx22,
            omit_child_for=self.world_id,
        )
        valid_world_bundle = self._bundle(
            "valid-world-record.json", [], records=list(valid_world.values())
        )
        invalid_world_bundle = self._bundle(
            "invalid-world-record.json", [], records=list(invalid_world.values())
        )
        invalid_idx23 = self.output_root / "invalid-preflight-idx23.json"
        idx23 = self.output_root / "valid-preflight-idx23.json"

        with (
            mock.patch.object(
                writer.phase5, "load_contract", return_value=self.load_contract_result
            ),
            mock.patch.object(
                parent_control_renderer,
                "load_validated_parent_control_bundle",
                return_value=parent_documents,
            ),
            mock.patch.object(
                parent_control_renderer,
                "load_validated_parent_control_bundle_snapshot",
                return_value=parent_documents,
            ),
            mock.patch.object(
                writer.phase5,
                "_bound_directory_snapshot",
                return_value=contextlib.nullcontext(
                    self._integration_parent_controls[0].parent
                ),
            ),
            mock.patch.object(
                writer.phase5.vision_evidence,
                "validate_report_vision_bundle",
                autospec=True,
                side_effect=self._validate_integration_vision_evidence,
            ) as validate_vision,
        ):
            with self.assertRaisesRegex(
                writer.SourceIndexWriterError, "child coverage mismatch"
            ):
                writer.write_source_index(
                    stage="idx23",
                    record_paths=[invalid_world_bundle],
                    output_path=invalid_idx23,
                    base_index_path=idx22,
                    base_manifest_path=manifest,
                )
            self.assertFalse(invalid_idx23.exists())
            validate_vision.reset_mock()
            idx23_result = writer.write_source_index(
                stage="idx23",
                record_paths=[valid_world_bundle],
                output_path=idx23,
                base_index_path=idx22,
                base_manifest_path=manifest,
            )
            self._assert_integration_vision_calls(
                validate_vision,
                {**direct, **valid_continents, **valid_world},
            )

        self.assertEqual(idx23_result["source_count"], 23)
        indexed, _, _ = phase5.load_source_index(idx23, set(self.contracts))
        self.assertEqual(set(indexed), set(self.contracts))

    def test_bound_catalog_change_aborts_before_install(self):
        catalog_copy = self.root / "map-sheets-copy.json"
        contract_copy = self.root / "resolution-contract-copy.json"
        shutil.copyfile(phase5.DEFAULT_MAP_SHEETS, catalog_copy)
        shutil.copyfile(phase5.DEFAULT_CONTRACT, contract_copy)
        bundle = self._bundle("bound-direct.json", self.direct_ids)
        output = self.output_root / "bound-change-idx17.json"

        def mutate_bound_catalog(*args, **kwargs):
            catalog_copy.write_bytes(catalog_copy.read_bytes() + b" ")

        with (
            mock.patch.object(phase5, "DEFAULT_MAP_SHEETS", catalog_copy),
            mock.patch.object(phase5, "DEFAULT_CONTRACT", contract_copy),
            mock.patch.object(
                writer.phase5,
                "load_contract",
                return_value=self.load_contract_result,
            ),
            mock.patch.object(
                writer, "_validate_candidate", side_effect=mutate_bound_catalog
            ),
        ):
            with self.assertRaisesRegex(
                writer.SourceIndexWriterError, "changed after.*snapshot"
            ):
                writer.write_source_index(
                    stage="idx17",
                    record_paths=[bundle],
                    output_path=output,
                    golden_style_path=self.golden,
                    base_manifest_path=self.dummy_manifest,
                    catalog_path=catalog_copy,
                    contract_path=contract_copy,
                )
        self.assertFalse(output.exists())

    def test_consumer_digest_is_for_the_exact_parsed_index_bytes(self):
        sheet_id = self.direct_ids[0]
        index = self.root / "exact-index.json"
        document = {
            "schema_version": "1.3.0",
            "coordinate_reference_system": "EA-WORLD-1",
            "golden_style": artifact(self.golden),
            "sources": [
                {
                    "sheet_id": sheet_id,
                    "kind": "master",
                    **artifact(self.master),
                }
            ],
        }
        write_json(index, document)
        parsed_bytes = index.read_bytes()
        expected_digest = phase5.hashlib.sha256(parsed_bytes).hexdigest()
        original_bind_graph = phase5.bind_phase5_artifact_graph

        def bind_then_mutate(roots):
            bindings = original_bind_graph(roots)
            index.write_bytes(parsed_bytes + b" ")
            return bindings

        with mock.patch.object(
            phase5, "bind_phase5_artifact_graph", side_effect=bind_then_mutate
        ):
            indexed, digest, _ = phase5.load_source_index(index, {sheet_id})
        self.assertEqual(digest, expected_digest)
        with self.assertRaisesRegex(
            bound_artifacts.BoundArtifactError, "changed after.*snapshot"
        ):
            bound_artifacts.assert_bindings_unchanged(
                phase5.source_index_bound_artifacts(indexed)
            )

    def test_consumer_rejects_ignored_transitive_master(self):
        ignored_root = REPO_ROOT / "tmp" / f"phase5-consumer-{uuid.uuid4().hex}"
        ignored_root.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(ignored_root, ignore_errors=True))
        ignored_master = ignored_root / "master.png"
        Image.new("RGB", (8, 8), "red").save(ignored_master)
        sheet_id = self.direct_ids[0]
        index = self.root / "ignored-transitive-index.json"
        write_json(
            index,
            {
                "schema_version": "1.3.0",
                "coordinate_reference_system": "EA-WORLD-1",
                "golden_style": artifact(self.golden),
                "sources": [
                    {
                        "sheet_id": sheet_id,
                        "kind": "master",
                        **artifact(ignored_master),
                    }
                ],
            },
        )
        with self.assertRaisesRegex(phase5.Phase5BuildError, "volatile|ignored"):
            phase5.load_source_index(index, {sheet_id})

    def test_large_bindings_spill_under_owned_repo_snapshot_root(self):
        large = self.root / "large-artifact.bin"
        large.write_bytes(b"x" * (bound_artifacts.MEMORY_SNAPSHOT_LIMIT + 1))
        bound = bound_artifacts.bind_file(large, label="large fixture")
        self.assertIsNone(bound._data)
        self.assertIsNotNone(bound.snapshot_path)
        assert bound.snapshot_path is not None
        self.assertTrue(
            bound.snapshot_path.is_relative_to(bound_artifacts.SNAPSHOT_PARENT)
        )
        self.assertEqual(bound.sha256, phase5.sha256_file(large))
        snapshot = bound.snapshot_path
        bound._finalizer()
        self.assertFalse(snapshot.exists())

    def test_snapshot_debris_scanner_reports_foreign_crash_arena(self):
        bound_artifacts.SNAPSHOT_PARENT.mkdir(parents=True, exist_ok=True)
        debris = bound_artifacts.SNAPSHOT_PARENT / (
            f"{bound_artifacts.SNAPSHOT_PREFIX}foreign-{uuid.uuid4().hex}"
        )
        debris.mkdir()
        self.addCleanup(lambda: shutil.rmtree(debris, ignore_errors=True))
        (debris / bound_artifacts.SNAPSHOT_MARKER).write_text(
            '{"pid": -1, "token": "foreign"}\n', encoding="utf-8"
        )
        self.assertIn(debris, bound_artifacts.snapshot_transaction_debris())

    def test_incremental_idx17_idx22_idx23_are_deterministic_and_schema_valid(self):
        direct_bundle = self._bundle("direct.json", self.direct_ids)
        continent_bundle = self._bundle("continents.json", self.continent_ids)
        world_bundle = self._bundle("world.json", [self.world_id])
        idx17 = self.output_root / "idx17.json"
        idx17_copy = self.output_root / "idx17-copy.json"
        idx22 = self.output_root / "idx22.json"
        idx23 = self.output_root / "idx23.json"

        first = self._write_mocked(
            stage="idx17",
            record_paths=[direct_bundle],
            output_path=idx17,
            golden_style_path=self.golden,
        )
        self._write_mocked(
            stage="idx17",
            record_paths=[direct_bundle],
            output_path=idx17_copy,
            golden_style_path=self.golden,
        )
        self.assertEqual(first["source_count"], 17)
        self.assertEqual(idx17.read_bytes(), idx17_copy.read_bytes())
        third = self._write_mocked(
            stage="idx22",
            record_paths=[continent_bundle],
            output_path=idx22,
            base_index_path=idx17,
        )
        fourth = self._write_mocked(
            stage="idx23",
            record_paths=[world_bundle],
            output_path=idx23,
            base_index_path=idx22,
        )
        self.assertEqual(third["source_count"], 22)
        self.assertEqual(fourth["source_count"], 23)
        for target_stage, index_path, tiles_requested in (
            ("idx22", idx17, False),
            ("idx23", idx22, False),
            ("final", idx23, True),
        ):
            staged_sources, _, _ = phase5.load_source_index(
                index_path, set(self.contracts)
            )
            stage_contract = phase5.target_stage_contract(
                target_stage=target_stage,
                catalog_by_id=self.catalog_by_id,
                contracts=self.contracts,
                sources=staged_sources,
                tiles_requested=tiles_requested,
                allow_provisional=False,
            )
            self.assertEqual(
                tuple(staged_sources), stage_contract.source_sheet_ids
            )
        indexed, _, golden = phase5.load_source_index(idx23, set(self.contracts))
        self.assertEqual(set(indexed), set(self.contracts))
        self.assertEqual(golden["sha256"], phase5.sha256_file(self.golden))

    def test_writer_refuses_overwrite_and_never_restores_stale_backup(self):
        bundle = self._bundle("direct.json", self.direct_ids)
        output = self.output_root / "idx17.json"
        self._write_mocked(
            stage="idx17",
            record_paths=[bundle],
            output_path=output,
            golden_style_path=self.golden,
        )
        before = output.read_bytes()
        with self.assertRaisesRegex(
            writer.SourceIndexWriterError, "refusing to overwrite"
        ):
            self._write_mocked(
                stage="idx17",
                record_paths=[bundle],
                output_path=output,
                golden_style_path=self.golden,
            )

        backup = output.with_name(f".{output.name}.backup-foreign-owner")
        backup.write_bytes(b"stale-backup-owner")
        self.addCleanup(lambda: backup.unlink(missing_ok=True))
        with self.assertRaisesRegex(
            writer.SourceIndexWriterError, "stale source-index backup"
        ):
            self._write_mocked(
                stage="idx17",
                record_paths=[bundle],
                output_path=output,
                golden_style_path=self.golden,
                force=True,
            )
        self.assertEqual(output.read_bytes(), before)
        self.assertEqual(backup.read_bytes(), b"stale-backup-owner")

    def test_no_force_concurrent_output_is_not_clobbered(self):
        bundle = self._bundle("direct.json", self.direct_ids)
        output = self.output_root / "raced-idx17.json"
        validation_calls = 0

        def validate_and_race(*args, **kwargs):
            nonlocal validation_calls
            validation_calls += 1
            if validation_calls == 1:
                output.write_bytes(b"concurrent-owner")

        patches = self._mocked_validation()
        with (
            patches[0],
            patches[1],
            patches[2],
            mock.patch.object(
                writer, "_validate_candidate", side_effect=validate_and_race
            ),
        ):
            with self.assertRaisesRegex(
                writer.SourceIndexWriterError, "appeared during no-clobber"
            ):
                writer.write_source_index(
                    stage="idx17",
                    record_paths=[bundle],
                    output_path=output,
                    golden_style_path=self.golden,
                    base_manifest_path=self.dummy_manifest,
                )
        self.assertEqual(output.read_bytes(), b"concurrent-owner")

    def test_identical_byte_link_racer_is_not_mistaken_for_owned_output(self):
        bundle = self._bundle("identical-race-direct.json", self.direct_ids)
        output = self.output_root / "identical-race-idx17.json"
        original_link = os.link
        racer_bytes: bytes | None = None

        def race_candidate_link(source, destination, *args, **kwargs):
            nonlocal racer_bytes
            if writer.same_path(Path(destination), output):
                racer_bytes = Path(source).read_bytes()
                output.write_bytes(racer_bytes)
                raise FileExistsError("identical-byte concurrent owner")
            return original_link(source, destination, *args, **kwargs)

        patches = self._mocked_validation()
        with (
            patches[0],
            patches[1],
            patches[2],
            mock.patch.object(writer.os, "link", side_effect=race_candidate_link),
        ):
            with self.assertRaisesRegex(
                writer.SourceIndexWriterError, "atomic no-clobber"
            ):
                writer.write_source_index(
                    stage="idx17",
                    record_paths=[bundle],
                    output_path=output,
                    golden_style_path=self.golden,
                    base_manifest_path=self.dummy_manifest,
                )
        self.assertIsNotNone(racer_bytes)
        self.assertEqual(output.read_bytes(), racer_bytes)

    def test_output_lock_does_not_relabel_body_file_exists(self):
        output = self.output_root / "lock-body.json"
        lock = output.with_name(f".{output.name}.source-index.lock")
        with self.assertRaisesRegex(FileExistsError, "body race"):
            with writer._exclusive_output_lock(output):
                raise FileExistsError("body race")
        self.assertFalse(lock.exists())

    def test_stale_candidate_is_detected_and_preserved(self):
        bundle = self._bundle("candidate-debris-direct.json", self.direct_ids)
        output = self.output_root / "candidate-debris-idx17.json"
        orphan = output.with_name(f".{output.name}.foreign-owner.candidate")
        orphan.write_bytes(b"foreign-candidate")

        with self.assertRaisesRegex(
            writer.SourceIndexWriterError, "transaction debris"
        ):
            self._write_mocked(
                stage="idx17",
                record_paths=[bundle],
                output_path=output,
                golden_style_path=self.golden,
            )
        self.assertFalse(output.exists())
        self.assertEqual(orphan.read_bytes(), b"foreign-candidate")

    def test_baseexception_after_install_restores_source_index_backup(self):
        original_bundle = self._bundle("rollback-original.json", self.direct_ids)
        output = self.output_root / "rollback-idx17.json"
        self._write_mocked(
            stage="idx17",
            record_paths=[original_bundle],
            output_path=output,
            golden_style_path=self.golden,
        )
        before = output.read_bytes()
        write_json(self.vision, {"decision": "accepted", "revision": 2})
        replacement_bundle = self._bundle("rollback-replacement.json", self.direct_ids)
        validation_calls = 0

        def interrupt_second_validation(*args, **kwargs):
            nonlocal validation_calls
            validation_calls += 1
            if validation_calls == 2:
                raise KeyboardInterrupt("synthetic installed-index interrupt")

        patches = self._mocked_validation()
        with (
            patches[0],
            patches[1],
            patches[2],
            mock.patch.object(
                writer,
                "_validate_candidate",
                side_effect=interrupt_second_validation,
            ),
        ):
            with self.assertRaises(KeyboardInterrupt):
                writer.write_source_index(
                    stage="idx17",
                    record_paths=[replacement_bundle],
                    output_path=output,
                    golden_style_path=self.golden,
                    base_manifest_path=self.dummy_manifest,
                    force=True,
                )
        self.assertEqual(output.read_bytes(), before)
        self.assertEqual(
            list(output.parent.glob(f".{output.name}.backup-*")),
            [],
        )

    def test_force_writer_never_unlinks_live_destination(self):
        bundle = self._bundle("atomic-force-direct.json", self.direct_ids)
        output = self.output_root / "atomic-force-idx17.json"
        output.write_bytes(b"old-destination")
        original_unlink = Path.unlink

        def validate_root(path, **_kwargs):
            bound = writer._bind_repo_file(path, "synthetic candidate validation")
            return {bound.identity: bound}

        def forbid_destination_unlink(path, *args, **kwargs):
            if writer.same_path(path, output):
                raise AssertionError("live destination was unlinked")
            return original_unlink(path, *args, **kwargs)

        patches = self._mocked_validation()
        with (
            patches[0],
            patches[1],
            patches[2],
            mock.patch.object(writer, "_validate_candidate", side_effect=validate_root),
            mock.patch.object(Path, "unlink", new=forbid_destination_unlink),
        ):
            result = writer.write_source_index(
                stage="idx17",
                record_paths=[bundle],
                output_path=output,
                golden_style_path=self.golden,
                base_manifest_path=self.dummy_manifest,
                force=True,
            )
        self.assertTrue(result["committed"])
        self.assertNotEqual(output.read_bytes(), b"old-destination")

    def test_postcommit_backup_cleanup_failure_returns_committed_success(self):
        bundle = self._bundle("cleanup-force-direct.json", self.direct_ids)
        output = self.output_root / "cleanup-force-idx17.json"
        output.write_bytes(b"old-destination")
        original_unlink = Path.unlink

        def validate_root(path, **_kwargs):
            bound = writer._bind_repo_file(path, "synthetic candidate validation")
            return {bound.identity: bound}

        def fail_backup_cleanup(path, *args, **kwargs):
            if path.name.startswith(f".{output.name}.backup-"):
                raise PermissionError("synthetic committed cleanup failure")
            return original_unlink(path, *args, **kwargs)

        self.addCleanup(
            lambda: [
                path.unlink(missing_ok=True)
                for path in output.parent.glob(f".{output.name}.backup-*")
            ]
        )
        patches = self._mocked_validation()
        with (
            patches[0],
            patches[1],
            patches[2],
            mock.patch.object(writer, "_validate_candidate", side_effect=validate_root),
            mock.patch.object(Path, "unlink", new=fail_backup_cleanup),
        ):
            result = writer.write_source_index(
                stage="idx17",
                record_paths=[bundle],
                output_path=output,
                golden_style_path=self.golden,
                base_manifest_path=self.dummy_manifest,
                force=True,
            )
        self.assertTrue(result["valid"])
        self.assertTrue(result["committed"])
        self.assertFalse(result["cleanup"]["complete"])
        self.assertNotEqual(output.read_bytes(), b"old-destination")

    def test_late_vision_mutation_rolls_back_force_replacement(self):
        bundle = self._bundle("late-mutation-direct.json", self.direct_ids)
        output = self.output_root / "late-mutation-idx17.json"
        output.write_bytes(b"old-destination")
        calls = 0

        def validate_then_mutate(path, **_kwargs):
            nonlocal calls
            calls += 1
            bound = writer._bind_repo_file(path, "synthetic candidate validation")
            if calls == 2:
                self.vision.write_bytes(self.vision.read_bytes() + b" ")
            return {bound.identity: bound}

        patches = self._mocked_validation()
        with (
            patches[0],
            patches[1],
            patches[2],
            mock.patch.object(
                writer, "_validate_candidate", side_effect=validate_then_mutate
            ),
        ):
            with self.assertRaisesRegex(
                writer.SourceIndexWriterError, "changed after.*snapshot"
            ):
                writer.write_source_index(
                    stage="idx17",
                    record_paths=[bundle],
                    output_path=output,
                    golden_style_path=self.golden,
                    base_manifest_path=self.dummy_manifest,
                    force=True,
                )
        self.assertEqual(output.read_bytes(), b"old-destination")
        self.assertEqual(list(output.parent.glob(f".{output.name}.backup-*")), [])

    def test_writer_rejects_tmp_artifact_before_schema_or_preflight(self):
        ignored_root = REPO_ROOT / "tmp" / f"phase5-writer-test-{uuid.uuid4().hex}"
        ignored_root.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(ignored_root, ignore_errors=True))
        ignored_master = ignored_root / "master.png"
        Image.new("RGB", (8, 8), "red").save(ignored_master)
        records = [self._record(sheet_id) for sheet_id in self.direct_ids]
        records[0]["path"] = phase5.repo_path(ignored_master)
        bundle = self._bundle("tmp-artifact.json", [], records=records)
        with self.assertRaisesRegex(writer.SourceIndexWriterError, "volatile|ignored"):
            self._write_mocked(
                stage="idx17",
                record_paths=[bundle],
                output_path=self.output_root / "tmp-artifact-idx17.json",
                golden_style_path=self.golden,
            )

    def test_writer_rejects_stale_hash_and_wrong_stage_delta(self):
        records = [self._record(sheet_id) for sheet_id in self.direct_ids]
        records[0]["sha256"] = "0" * 64
        stale = self._bundle("stale.json", [], records=records)
        with self.assertRaisesRegex(writer.SourceIndexWriterError, "sha256 mismatch"):
            self._write_mocked(
                stage="idx17",
                record_paths=[stale],
                output_path=self.output_root / "stale-idx17.json",
                golden_style_path=self.golden,
            )

        incomplete = self._bundle("incomplete.json", self.direct_ids[:-1])
        with self.assertRaisesRegex(
            writer.SourceIndexWriterError, "requires exactly its next-stage"
        ):
            self._write_mocked(
                stage="idx17",
                record_paths=[incomplete],
                output_path=self.output_root / "incomplete-idx17.json",
                golden_style_path=self.golden,
            )

    def test_noncanonical_catalog_composition_is_rejected(self):
        altered = copy.deepcopy(self.catalog)
        region = next(
            sheet for sheet in altered["sheets"] if sheet.get("sheet_type") == "region"
        )
        original_id = region["id"]
        region["id"] = "sheet_region_substituted"
        altered_by_id = {sheet["id"]: sheet for sheet in altered["sheets"]}
        altered_contracts = dict(self.contracts)
        altered_contracts[region["id"]] = altered_contracts.pop(original_id)
        bundle = self._bundle("direct.json", self.direct_ids)
        with mock.patch.object(
            writer.phase5,
            "load_contract",
            return_value=(altered, altered_by_id, {"sheets": altered_contracts}),
        ):
            with self.assertRaisesRegex(
                writer.SourceIndexWriterError, "canonical bounded catalog composition"
            ):
                writer.write_source_index(
                    stage="idx17",
                    record_paths=[bundle],
                    output_path=self.output_root / "altered-idx17.json",
                    golden_style_path=self.golden,
                    base_manifest_path=self.dummy_manifest,
                )


if __name__ == "__main__":
    unittest.main()
