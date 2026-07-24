import hashlib
import json
import os
import shutil
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

import emit_phase5_vision_views as emitter  # noqa: E402
import phase5_vision_evidence as evidence  # noqa: E402
import create_qa_report  # noqa: E402
import build_phase5_assets as phase5  # noqa: E402
from validate_manifest import schema_errors  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(evidence.stable_json_bytes(value))


class Phase5VisionEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        token = uuid.uuid4().hex
        self.root = REPO_ROOT / f".phase5-vision-evidence-test-{token}"
        self.root.mkdir()
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        temporary_parent = REPO_ROOT / "tmp" / "map-production"
        temporary_parent.mkdir(parents=True, exist_ok=True)
        self.output_parent = Path(
            tempfile.mkdtemp(
                prefix="phase5-vision-evidence-output-",
                dir=temporary_parent,
            )
        )
        self.addCleanup(lambda: shutil.rmtree(self.output_parent, ignore_errors=True))
        self.evidence_version = evidence.CANONICAL_EVIDENCE_ROOT / f"test-{token}"
        self.addCleanup(
            lambda: shutil.rmtree(self.evidence_version, ignore_errors=True)
        )
        self.sheet_id = "sheet_world"
        self.master = self.root / f"{self.sheet_id}.png"
        Image.new("RGB", (512, 512), (90, 120, 150)).save(self.master)

        catalog = json.loads(evidence.DEFAULT_MAP_SHEETS.read_text(encoding="utf-8"))
        sheet_ids = [
            sheet["id"]
            for sheet in catalog["sheets"]
            if sheet.get("bounds") is not None
        ]
        self.derived = {
            "valid": True,
            "sheets": [
                {"sheet_id": sheet_id, "width": 512, "height": 512}
                for sheet_id in sheet_ids
            ],
            "errors": [],
        }
        self.registry = self.root / "focus-registry.json"
        registry_document = {
            "$schema": (
                "https://sstory.example/schemas/phase5-vision-focus-boxes.schema.json"
            ),
            "schema_version": "1.0.0",
            "type": "sstory-phase5-canonical-vision-focus-boxes",
            "coordinate_reference_system": "EA-WORLD-1",
            "coordinate_convention": ("left-top-inclusive_right-bottom-exclusive"),
            "focus_crop_size_px": 512,
            "map_catalog": {
                "path": "world/map-production/source/map-sheets.json",
                "sha256": digest(evidence.DEFAULT_MAP_SHEETS),
            },
            "resolution_contract": {
                "path": "world/map-production/spec/resolution-contract.json",
                "sha256": digest(evidence.DEFAULT_RESOLUTION_CONTRACT),
            },
            "entries": [
                {
                    "sheet_id": sheet_id,
                    "source_size": [512, 512],
                    "box_px": [0, 0, 512, 512],
                    "purpose": "Synthetic exact focus fixture.",
                }
                for sheet_id in sheet_ids
            ],
        }
        write_json(self.registry, registry_document)
        self.resolution_patch = mock.patch.object(
            evidence.resolution_contract,
            "validate_resolution_contract",
            return_value=self.derived,
        )
        self.resolution_patch.start()
        self.addCleanup(self.resolution_patch.stop)

        source = evidence.bind_file(self.master, label="synthetic Vision source")
        registry = evidence.load_focus_registry(self.registry)
        source_size, views = evidence.render_view_artifacts(source, [0, 0, 512, 512])
        self.receipt_document = evidence.build_canonical_receipt(
            sheet_id=self.sheet_id,
            source=source,
            source_size=source_size,
            focus_registry=registry.binding,
            focus_box=[0, 0, 512, 512],
            views=views,
        )
        self.receipt = (
            self.evidence_version / self.sheet_id / evidence.PERSISTENT_RECEIPT_FILENAME
        )
        write_json(self.receipt, self.receipt_document)
        self.report = {
            "vision_bundle": {
                "receipt": {
                    "path": self.receipt.relative_to(REPO_ROOT).as_posix(),
                    "sha256": digest(self.receipt),
                },
                "reviewer_confirmed_exact_five": True,
            }
        }

    def validate(self):
        return evidence.validate_report_vision_bundle(
            self.report,
            sheet_id=self.sheet_id,
            master_path=self.master,
            master_sha256=digest(self.master),
            focus_registry_path=self.registry,
        )

    def rewrite_receipt(self, document: dict) -> None:
        write_json(self.receipt, document)
        self.report["vision_bundle"]["receipt"]["sha256"] = digest(self.receipt)

    def output(self, label: str) -> Path:
        return self.output_parent / f"{label}-{uuid.uuid4().hex}"

    def local_resolution_registry(self, label: str) -> tuple[Path, Path, Path]:
        catalog = self.root / f"{label}-map-sheets.json"
        contract = self.root / f"{label}-resolution-contract.json"
        write_json(catalog, {"fixture": "original-catalog"})
        write_json(contract, {"fixture": "original-contract"})
        registry = self.root / f"{label}-focus-registry.json"
        document = json.loads(self.registry.read_text(encoding="utf-8"))
        document["map_catalog"] = {
            "path": catalog.relative_to(REPO_ROOT).as_posix(),
            "sha256": digest(catalog),
        }
        document["resolution_contract"] = {
            "path": contract.relative_to(REPO_ROOT).as_posix(),
            "sha256": digest(contract),
        }
        write_json(registry, document)
        return registry, catalog, contract

    def test_recomputes_exact_five_and_accepts_canonical_receipt(self):
        bindings = self.validate()
        self.assertEqual(bindings.source.sha256, digest(self.master))
        self.assertEqual(bindings.receipt.sha256, digest(self.receipt))
        self.assertEqual(len(self.receipt_document["views"]), 5)

    def test_focus_registry_derives_only_from_bound_snapshots_during_swaps(self):
        registry, catalog, contract = self.local_resolution_registry("swap")
        original_catalog = catalog.read_bytes()
        original_contract = contract.read_bytes()
        catalog_backup = catalog.with_suffix(".original")
        contract_backup = contract.with_suffix(".original")
        alternate_derived = json.loads(json.dumps(self.derived))
        alternate_derived["sheets"][0]["width"] = 513
        validator_paths: list[Path] = []

        def validate_snapshots(
            contract_path: Path,
            catalog_path: Path,
            *,
            check_catalog: bool,
        ) -> dict:
            self.assertTrue(check_catalog)
            validator_paths.extend((Path(contract_path), Path(catalog_path)))
            catalog.replace(catalog_backup)
            contract.replace(contract_backup)
            try:
                write_json(catalog, {"fixture": "alternate-catalog"})
                write_json(contract, {"fixture": "alternate-contract"})
                selected_catalog = Path(catalog_path).read_bytes()
                selected_contract = Path(contract_path).read_bytes()
                if (
                    selected_catalog == original_catalog
                    and selected_contract == original_contract
                ):
                    return self.derived
                return alternate_derived
            finally:
                catalog.unlink(missing_ok=True)
                contract.unlink(missing_ok=True)
                catalog_backup.replace(catalog)
                contract_backup.replace(contract)

        with (
            mock.patch.object(evidence, "DEFAULT_MAP_SHEETS", catalog),
            mock.patch.object(evidence, "DEFAULT_RESOLUTION_CONTRACT", contract),
            mock.patch.object(
                evidence.resolution_contract,
                "validate_resolution_contract",
                side_effect=validate_snapshots,
            ),
        ):
            loaded = evidence.load_focus_registry(registry)

        self.assertEqual(
            loaded.ordered_sheet_ids,
            tuple(record["sheet_id"] for record in self.derived["sheets"]),
        )
        self.assertEqual(catalog.read_bytes(), original_catalog)
        self.assertEqual(contract.read_bytes(), original_contract)
        self.assertEqual(len(validator_paths), 2)
        self.assertFalse(evidence.same_path(validator_paths[0], contract))
        self.assertFalse(evidence.same_path(validator_paths[1], catalog))
        self.assertFalse(validator_paths[0].exists())
        self.assertFalse(validator_paths[1].exists())

    def test_focus_registry_fails_closed_when_bound_input_changes(self):
        registry, catalog, contract = self.local_resolution_registry("mutation")
        original_contract = contract.read_bytes()

        def mutate_after_snapshot(
            contract_path: Path,
            catalog_path: Path,
            *,
            check_catalog: bool,
        ) -> dict:
            self.assertTrue(check_catalog)
            self.assertFalse(evidence.same_path(Path(contract_path), contract))
            self.assertFalse(evidence.same_path(Path(catalog_path), catalog))
            contract.write_bytes(original_contract + b" ")
            return self.derived

        try:
            with (
                mock.patch.object(evidence, "DEFAULT_MAP_SHEETS", catalog),
                mock.patch.object(evidence, "DEFAULT_RESOLUTION_CONTRACT", contract),
                mock.patch.object(
                    evidence.resolution_contract,
                    "validate_resolution_contract",
                    side_effect=mutate_after_snapshot,
                ),
            ):
                with self.assertRaisesRegex(
                    evidence.Phase5VisionEvidenceError,
                    "changed after its exact byte snapshot was bound",
                ):
                    evidence.load_focus_registry(registry)
        finally:
            contract.write_bytes(original_contract)

    def test_rejects_unconfirmed_missing_and_stale_receipt(self):
        self.report["vision_bundle"]["reviewer_confirmed_exact_five"] = False
        with self.assertRaisesRegex(
            evidence.Phase5VisionEvidenceError, "explicitly confirm"
        ):
            self.validate()
        self.report["vision_bundle"]["reviewer_confirmed_exact_five"] = True
        stale = json.loads(json.dumps(self.receipt_document))
        stale["views"][0]["sha256"] = "0" * 64
        self.rewrite_receipt(stale)
        with self.assertRaisesRegex(
            evidence.Phase5VisionEvidenceError, "stale|mismatch"
        ):
            self.validate()
        self.report.pop("vision_bundle")
        with self.assertRaisesRegex(evidence.Phase5VisionEvidenceError, "object"):
            self.validate()

    def test_rejects_focus_and_extra_view_inventory_drift(self):
        changed = json.loads(json.dumps(self.receipt_document))
        changed["focus"]["box_px"] = [0, 0, 511, 512]
        self.rewrite_receipt(changed)
        with self.assertRaisesRegex(
            evidence.Phase5VisionEvidenceError, "stale|mismatch"
        ):
            self.validate()

        extra = json.loads(json.dumps(self.receipt_document))
        extra["inventory"].insert(-1, "extra.png")
        extra["views"].append(dict(extra["views"][0], id="extra", filename="extra.png"))
        self.rewrite_receipt(extra)
        with self.assertRaisesRegex(
            evidence.Phase5VisionEvidenceError, "schema validation"
        ):
            self.validate()

    def test_rejects_symlinked_persistent_receipt(self):
        target = self.root / "receipt-target.json"
        target.write_bytes(self.receipt.read_bytes())
        self.receipt.unlink()
        try:
            os.symlink(target, self.receipt)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        self.report["vision_bundle"]["receipt"]["sha256"] = digest(target)
        with self.assertRaisesRegex(
            evidence.Phase5VisionEvidenceError,
            "symlink|junction|reparse",
        ):
            self.validate()

    def test_rejects_noncanonical_extra_receipt_nesting(self):
        nested = (
            self.evidence_version
            / "extra"
            / self.sheet_id
            / evidence.PERSISTENT_RECEIPT_FILENAME
        )
        nested.parent.mkdir(parents=True)
        write_json(nested, self.receipt_document)
        self.report["vision_bundle"]["receipt"] = {
            "path": nested.relative_to(REPO_ROOT).as_posix(),
            "sha256": digest(nested),
        }
        with self.assertRaisesRegex(
            evidence.Phase5VisionEvidenceError,
            "<evidence-root>/<version>/<sheet-id>",
        ):
            self.validate()

    def test_emitter_persists_same_canonical_receipt_bytes(self):
        output = self.output("canonical")
        shutil.rmtree(self.receipt.parent)
        with mock.patch.object(emitter, "_assert_git_tracked"):
            result = emitter.emit_phase5_vision_views(
                self.master.relative_to(REPO_ROOT).as_posix(),
                output,
                source_sha256=digest(self.master),
                focus_box=None,
                sheet_id=self.sheet_id,
                focus_registry_path=self.registry,
                evidence_receipt=self.receipt,
            )
        self.assertTrue(result["valid"])
        self.assertEqual(result["persistent_receipt"]["sha256"], digest(self.receipt))
        self.assertEqual(
            [evidence.PERSISTENT_RECEIPT_FILENAME],
            [path.name for path in self.receipt.parent.iterdir()],
        )
        self.report["vision_bundle"]["receipt"]["sha256"] = digest(self.receipt)
        self.validate()

    def test_emitter_never_clobbers_an_existing_evidence_directory(self):
        output = self.output("no-clobber")
        original = self.receipt.read_bytes()
        with mock.patch.object(emitter, "_assert_git_tracked"):
            with self.assertRaisesRegex(
                emitter.Phase5VisionViewsError,
                "output already exists|persistent Vision evidence transaction failed",
            ):
                emitter.emit_phase5_vision_views(
                    self.master.relative_to(REPO_ROOT).as_posix(),
                    output,
                    source_sha256=digest(self.master),
                    focus_box=None,
                    sheet_id=self.sheet_id,
                    focus_registry_path=self.registry,
                    evidence_receipt=self.receipt,
                )
        self.assertEqual(original, self.receipt.read_bytes())
        self.assertEqual(
            [evidence.PERSISTENT_RECEIPT_FILENAME],
            [path.name for path in self.receipt.parent.iterdir()],
        )
        self.assertFalse(output.exists())

    def test_partial_receipt_write_never_publishes_a_sheet_directory(self):
        output = self.output("partial-write")
        shutil.rmtree(self.receipt.parent)
        original_write = emitter._write_owned_file

        def fail_persistent_write(
            staging: emitter.OwnedStaging,
            name: str,
            payload: bytes,
            **kwargs: object,
        ) -> None:
            if name == evidence.PERSISTENT_RECEIPT_FILENAME:
                original_write(
                    staging,
                    name,
                    payload[: max(1, len(payload) // 2)],
                    **kwargs,
                )
                raise OSError("forced partial persistent receipt write")
            original_write(staging, name, payload, **kwargs)

        with (
            mock.patch.object(emitter, "_assert_git_tracked"),
            mock.patch.object(
                emitter,
                "_write_owned_file",
                side_effect=fail_persistent_write,
            ),
        ):
            with self.assertRaisesRegex(
                emitter.Phase5VisionViewsError,
                "partial persistent receipt write",
            ):
                emitter.emit_phase5_vision_views(
                    self.master.relative_to(REPO_ROOT).as_posix(),
                    output,
                    source_sha256=digest(self.master),
                    focus_box=None,
                    sheet_id=self.sheet_id,
                    focus_registry_path=self.registry,
                    evidence_receipt=self.receipt,
                )
        self.assertFalse(self.receipt.parent.exists())
        debris = list(self.evidence_version.glob(f".{self.sheet_id}.staging-*"))
        self.assertEqual(1, len(debris))
        partial = debris[0] / evidence.PERSISTENT_RECEIPT_FILENAME
        self.assertTrue(partial.is_file())
        self.assertLess(
            partial.stat().st_size,
            len(evidence.stable_json_bytes(self.receipt_document)),
        )
        self.assertFalse(output.exists())

    def test_final_evidence_rename_rechecks_source_and_focus_registry(self):
        original_source = self.master.read_bytes()
        original_registry = self.registry.read_bytes()
        for label in ("source", "registry"):
            with self.subTest(label=label):
                shutil.rmtree(self.receipt.parent, ignore_errors=True)
                output = self.output(f"final-binding-{label}")

                def mutate_binding(**kwargs: object) -> None:
                    if kwargs.get("destination_name") != self.sheet_id:
                        return
                    if label == "source":
                        self.master.write_bytes(original_source + b"\x00")
                    else:
                        self.registry.write_bytes(original_registry + b" ")

                try:
                    with (
                        mock.patch.object(emitter, "_assert_git_tracked"),
                        mock.patch.object(
                            emitter,
                            "_before_rename_syscall_hook",
                            side_effect=mutate_binding,
                        ),
                    ):
                        with self.assertRaisesRegex(
                            emitter.Phase5VisionViewsError,
                            "changed after its exact byte snapshot was bound",
                        ):
                            emitter.emit_phase5_vision_views(
                                self.master.relative_to(REPO_ROOT).as_posix(),
                                output,
                                source_sha256=digest(self.master),
                                focus_box=None,
                                sheet_id=self.sheet_id,
                                focus_registry_path=self.registry,
                                evidence_receipt=self.receipt,
                            )
                finally:
                    self.master.write_bytes(original_source)
                    self.registry.write_bytes(original_registry)
                self.assertFalse(self.receipt.parent.exists())
                self.assertFalse(output.exists())

    @unittest.skipUnless(
        os.name == "nt" or sys.platform.startswith("linux"),
        "anchored evidence transactions require Windows or Linux",
    )
    def test_parent_and_ancestor_swaps_cannot_redirect_evidence_install(self):
        for level in ("parent", "ancestor"):
            with self.subTest(level=level):
                local_root = self.root / f"{level}-evidence-root"
                version = local_root / "v1"
                version.mkdir(parents=True)
                receipt = version / self.sheet_id / evidence.PERSISTENT_RECEIPT_FILENAME
                output = self.output(f"swap-{level}")
                target = version if level == "parent" else local_root
                moved = target.with_name(f"{target.name}-moved")
                state = {"called": False, "swapped": False, "blocked": False}

                def swap_at_commit(**kwargs: object) -> None:
                    if kwargs.get("destination_name") != self.sheet_id:
                        return
                    state["called"] = True
                    try:
                        target.rename(moved)
                    except OSError:
                        state["blocked"] = True
                        return
                    state["swapped"] = True
                    if level == "parent":
                        target.mkdir()
                        replacement = target
                    else:
                        (target / version.name).mkdir(parents=True)
                        replacement = target / version.name
                    (replacement / "foreign-sentinel.txt").write_text(
                        "do-not-touch\n",
                        encoding="utf-8",
                    )

                result: dict | None = None
                raised: emitter.Phase5VisionViewsError | None = None
                try:
                    with (
                        mock.patch.object(
                            evidence,
                            "CANONICAL_EVIDENCE_ROOT",
                            local_root,
                        ),
                        mock.patch.object(emitter, "_assert_git_tracked"),
                        mock.patch.object(
                            emitter,
                            "_before_rename_syscall_hook",
                            side_effect=swap_at_commit,
                        ),
                    ):
                        try:
                            result = emitter.emit_phase5_vision_views(
                                self.master.relative_to(REPO_ROOT).as_posix(),
                                output,
                                source_sha256=digest(self.master),
                                focus_box=None,
                                sheet_id=self.sheet_id,
                                focus_registry_path=self.registry,
                                evidence_receipt=receipt,
                            )
                        except emitter.Phase5VisionViewsError as exc:
                            raised = exc
                    self.assertTrue(state["called"])
                    if state["blocked"]:
                        self.assertIsNone(raised)
                        self.assertIsNotNone(result)
                        self.assertTrue(receipt.is_file())
                    else:
                        self.assertTrue(state["swapped"])
                        self.assertIsInstance(
                            raised,
                            emitter.Phase5PublicationUnknownError,
                        )
                        replacement_version = (
                            target if level == "parent" else target / version.name
                        )
                        self.assertFalse((replacement_version / self.sheet_id).exists())
                        self.assertEqual(
                            "do-not-touch\n",
                            (replacement_version / "foreign-sentinel.txt").read_text(
                                encoding="utf-8"
                            ),
                        )
                finally:
                    if state["swapped"]:
                        shutil.rmtree(target, ignore_errors=True)
                        moved.rename(target)

    def test_artifact_graph_follows_receipt_bindings_not_temp_view_filenames(self):
        report_path = self.root / "qa-report.json"
        write_json(report_path, self.report)
        root = evidence.bind_file(report_path, label="synthetic QA report")

        graph = phase5.bind_phase5_artifact_graph([root])
        relative_paths = {binding.relative for binding in graph.values()}

        self.assertIn(root.relative, relative_paths)
        self.assertIn(self.receipt.relative_to(REPO_ROOT).as_posix(), relative_paths)
        self.assertIn(self.master.relative_to(REPO_ROOT).as_posix(), relative_paths)
        self.assertIn(self.registry.relative_to(REPO_ROOT).as_posix(), relative_paths)
        self.assertIn(
            evidence.DEFAULT_MAP_SHEETS.relative_to(REPO_ROOT).as_posix(),
            relative_paths,
        )
        self.assertIn(
            evidence.DEFAULT_RESOLUTION_CONTRACT.relative_to(REPO_ROOT).as_posix(),
            relative_paths,
        )
        self.assertFalse(
            relative_paths.intersection(self.receipt_document["inventory"]),
            "TEMP bundle filenames must not be interpreted as repository artifacts",
        )

    def test_qa_cli_requires_the_exact_receipt_bytes_in_the_git_index(self):
        tracked = evidence.bind_file(
            evidence.DEFAULT_MAP_SHEETS,
            label="known tracked index fixture",
            trackable=True,
        )
        create_qa_report._assert_git_index_matches(tracked)

        untracked = evidence.bind_file(
            self.receipt,
            label="untracked synthetic Vision receipt",
            trackable=True,
        )
        with self.assertRaisesRegex(
            evidence.BoundArtifactError,
            "must already be staged in the Git index",
        ):
            create_qa_report._assert_git_index_matches(untracked)

        output = self.root / "untracked-qa-report.json"
        result = create_qa_report.main(
            [
                "--job-id",
                "phase5-world-v1",
                "--image",
                self.master.relative_to(REPO_ROOT).as_posix(),
                "--image-sha256",
                digest(self.master),
                "--vision-bundle-receipt",
                self.receipt.relative_to(REPO_ROOT).as_posix(),
                "--format",
                "json",
                "--output",
                str(output),
            ]
        )
        self.assertEqual(result, 2)
        self.assertFalse(output.exists())

        with mock.patch.object(
            create_qa_report.subprocess,
            "run",
            return_value=mock.Mock(returncode=0, stdout=b"different", stderr=b""),
        ):
            with self.assertRaisesRegex(
                evidence.BoundArtifactError,
                "Git index bytes do not match",
            ):
                create_qa_report._assert_git_index_matches(tracked)

    def test_qa_schema_is_backward_compatible_but_phase5_acceptance_is_bound(self):
        receipt_spec = self.report["vision_bundle"]["receipt"]
        report = create_qa_report.build_report(
            "phase5-world-v1",
            self.master.relative_to(REPO_ROOT).as_posix(),
            reviewer="Synthetic Reviewer",
            golden=False,
            threshold=90,
            image_sha256=digest(self.master),
            review_mode="blind-independent",
            vision_bundle_receipt=receipt_spec,
        )
        self.assertFalse(report["vision_bundle"]["reviewer_confirmed_exact_five"])
        report["status"] = "complete"
        report["decision"] = "accepted"
        report["summary"] = "Synthetic exact-five schema acceptance."
        for view in report["review_views"]:
            view["complete"] = True
            view["evidence"] = "checked"
        for failure in report["immediate_failures"]:
            failure["detected"] = False
            failure["evidence"] = "not detected"
        for score in report["scores"]:
            score["score"] = score["maximum"]
        report["total_score"] = 100
        schema = json.loads(
            (
                REPO_ROOT
                / "world"
                / "map-production"
                / "schemas"
                / "qa-report.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertTrue(schema_errors(report, schema))
        report["vision_bundle"]["reviewer_confirmed_exact_five"] = True
        self.assertEqual(schema_errors(report, schema), [])

        legacy = create_qa_report.build_report(
            "legacy-map-review-v1",
            self.master.relative_to(REPO_ROOT).as_posix(),
            reviewer="Legacy Reviewer",
            golden=False,
        )
        self.assertNotIn("vision_bundle", legacy)
        self.assertEqual(schema_errors(legacy, schema), [])


if __name__ == "__main__":
    unittest.main()
