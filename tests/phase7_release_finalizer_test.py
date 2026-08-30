import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import finalize_phase7_release as finalizer  # noqa: E402


TIMESTAMP = "2026-07-20T01:00:00Z"
EARLIER = "2026-07-20T00:00:00Z"
MASTER_SHA = "1" * 64
TILE_SET_SHA = "2" * 64
EVIDENCE_SHA = "3" * 64


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


class Phase7ReleaseFinalizerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix=".phase7-finalizer-test-", dir=REPO_ROOT
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.build_root = self.root / "build"

        for relative in (
            finalizer.READINESS_SCHEMA_RELATIVE_PATH,
            finalizer.INDEX_SCHEMA_RELATIVE_PATH,
        ):
            source = REPO_ROOT.joinpath(*relative.parts)
            target = self.root.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

        catalog_source = REPO_ROOT.joinpath(*finalizer.CATALOG_RELATIVE_PATH.parts)
        self.catalog = json.loads(catalog_source.read_text(encoding="utf-8"))
        catalog_target = self.root.joinpath(*finalizer.CATALOG_RELATIVE_PATH.parts)
        write_json(catalog_target, self.catalog)
        self.bounded = [
            sheet
            for sheet in self.catalog["sheets"]
            if sheet.get("review_status") != "planned" and sheet.get("bounds") is not None
        ]
        self.assertEqual(len(self.bounded), 23)

        self.canonical_manifest = self.root.joinpath(
            *finalizer.MANIFEST_RELATIVE_PATH.parts
        )
        self.readiness_path = self.root.joinpath(
            *finalizer.READINESS_RELATIVE_PATH.parts
        )
        self.canonical_index = self.root.joinpath(
            *finalizer.CANONICAL_INDEX_RELATIVE_PATH.parts
        )
        self.compatibility_index = self.root.joinpath(
            *finalizer.COMPATIBILITY_INDEX_RELATIVE_PATH.parts
        )
        self.html_path = self.root.joinpath(*finalizer.HTML_RELATIVE_PATH.parts)
        self.receipt_path = self.root.joinpath(
            *finalizer.RECEIPT_RELATIVE_PATH.parts
        )
        self.browser_receipt = self.root / "output" / "playwright" / "world-v3" / "phase6-browser-qa-receipt.json"
        self.browser_receipt_payload = {
            "release_id": "world-v3",
            "result": "pass",
            "tested_url": "http://127.0.0.1:8765/pages/interactive-map-v3.html?release-preview=world-v3",
            "completed_at": "2026-07-20T00:30:00Z",
            "scenarios": [],
        }
        for index in range(4):
            relative = f"scenarios/scenario-{index}/snapshot.md"
            evidence_path = self.browser_receipt.parent / Path(relative)
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_path.write_text(f"scenario {index}\n", encoding="utf-8")
            self.browser_receipt_payload["scenarios"].append(
                {
                    "result": "pass",
                    "evidence": {
                        "snapshot": {
                            "path": relative,
                            "sha256": finalizer._sha256_file(evidence_path),
                        }
                    },
                }
            )
        write_json(self.browser_receipt, self.browser_receipt_payload)

        base_manifest = {
            "schema_version": "1.0.0",
            "project_id": "phase7-test",
            "map_id": "eternal-arcadia",
            "coordinate_system": "EA-WORLD-1",
            "updated_at": EARLIER,
            "jobs": [],
        }
        write_json(self.canonical_manifest, base_manifest)
        write_json(
            self.readiness_path,
            {
                "$schema": "schemas/release-readiness.schema.json",
                "schema_version": "1.0.0",
                "status": "in-progress",
                "manifest_path": finalizer.MANIFEST_RELATIVE_PATH.as_posix(),
                "notes": "Fixture remains in progress.",
            },
        )
        self.index = self._build_index()
        write_json(self.canonical_index, self.index)
        self.compatibility_index.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.canonical_index, self.compatibility_index)
        self.html_path.parent.mkdir(parents=True, exist_ok=True)
        self.html_path.write_text(
            """<!doctype html><html><head>
<meta name="ea-map-world-release" content="world-v1">
<meta name="ea-map-world-target-release" content="world-v3">
<meta name="ea-map-world-fallback-releases" content="world-v2,world-v1">
<meta name="ea-map-world-v3-manifest" content="../assets/images/maps/tiles/world-v3/metadata.json">
<meta name="ea-map-world-v2-manifest" content="../assets/images/maps/tiles/world-v2/metadata.json">
<meta name="ea-map-world-v1-manifest" content="../assets/images/maps/tiles/world-v1/metadata.json">
<meta name="ea-map-cache-key" content="world-v3-contract-test">
<meta name="ea-map-sheet-tile-index" content="../data/map/region-rasters.json">
</head><body></body></html>
""",
            encoding="utf-8",
        )
        source_manifest = dict(base_manifest)
        source_manifest["updated_at"] = EARLIER
        source_manifest["jobs"] = [self._build_job(sheet) for sheet in self.bounded]
        write_json(
            self.build_root / "production-manifest.phase5.json", source_manifest
        )

        self.public_result = {
            "valid": True,
            "release_id": "world-v3",
            "bounded_sheet_count": 23,
            "tile_count": 230,
            "tile_bytes": 123456,
            "errors": [],
        }
        self.build_result = {
            "valid": True,
            "public_tile_release": dict(self.public_result),
            "errors": [],
        }
        self.strict_result = {
            "valid": True,
            "required_sheets": 23,
            "covered_sheets": 23,
            "errors": [],
        }

    def _metadata_relative(self, sheet) -> PurePosixPath:
        release = finalizer.PUBLIC_RELEASE_RELATIVE_PATH
        if sheet["sheet_type"] == "world":
            return release / "metadata.json"
        return release / "sheets" / sheet["id"] / "metadata.json"

    def _manifest_url(self, sheet) -> str:
        relative = self._metadata_relative(sheet)
        return "../../" + relative.relative_to("docs").as_posix()

    def _build_index(self):
        entries = []
        for sheet in self.bounded:
            metadata_relative = self._metadata_relative(sheet)
            metadata_path = self.root.joinpath(*metadata_relative.parts)
            write_json(
                metadata_path,
                {
                    "release_id": "world-v3",
                    "map_id": sheet["id"],
                    "master": {"sha256": MASTER_SHA},
                    "tile_set_sha256": TILE_SET_SHA,
                },
            )
            entries.append(
                {
                    "id": sheet["id"],
                    "sheet_id": sheet["id"],
                    "name": sheet["name"],
                    "sheet_type": sheet["sheet_type"],
                    "parent_id": sheet.get("parent_id"),
                    "secondary_parent_ids": list(sheet.get("secondary_parent_ids", [])),
                    "source_feature_id": sheet.get("source_feature_id"),
                    "bounds": list(sheet["bounds"]),
                    "zoom_range": list(sheet["zoom_range"]),
                    "native_zoom": sheet["native_zoom"],
                    "review_status": "accepted",
                    "status": "tiled",
                    "manifest_url": self._manifest_url(sheet),
                    "priority": sheet["native_zoom"] * 1000,
                    "master_sha256": MASTER_SHA,
                    "manifest_sha256": finalizer._sha256_file(metadata_path),
                    "tile_set_sha256": TILE_SET_SHA,
                    "tile_count": 10,
                    "evidence": {
                        "provenance": {
                            "path": "world/map-production/qa/provenance.json",
                            "sha256": EVIDENCE_SHA,
                        },
                        "automated_qa": {
                            "path": "world/map-production/qa/automated/sheet.json",
                            "sha256": EVIDENCE_SHA,
                        },
                        "vision_reviews": [
                            {
                                "path": "world/map-production/qa/sheet-review.json",
                                "sha256": EVIDENCE_SHA,
                            }
                        ],
                    },
                }
            )
        root = next(entry for entry in entries if entry["sheet_type"] == "world")
        descendants = sorted(
            (entry for entry in entries if entry["sheet_type"] != "world"),
            key=lambda entry: entry["sheet_id"],
        )
        return {
            "$schema": "https://sstory.example/schemas/sheet-tile-index.schema.json",
            "schema_version": "2.0.0",
            "type": "sstory-sheet-tile-index",
            "coordinate_reference_system": "EA-WORLD-1",
            "bounds_order": ["min_x", "min_y", "max_x", "max_y"],
            "generated_by": "sstory-map-production/build_phase5_assets.py@2",
            "generated_at": EARLIER,
            "release_id": "world-v3",
            "bounded_sheet_count": 23,
            "root_id": "sheet_world",
            "root": root,
            "description": "Complete all-23 unit-test release.",
            "sheets": descendants,
        }

    def _build_job(self, sheet):
        return {
            "id": f"phase5-{sheet['id'].removeprefix('sheet_').replace('_', '-')}",
            "sheet_id": sheet["id"],
            "status": "tiled",
            "bounds": {
                "west": sheet["bounds"][0],
                "south": sheet["bounds"][1],
                "east": sheet["bounds"][2],
                "north": sheet["bounds"][3],
            },
            "zoom": {
                "min": sheet["zoom_range"][0],
                "max": sheet["zoom_range"][1],
                "native": sheet["native_zoom"],
            },
            "master": {"sha256": MASTER_SHA},
            "output": {
                "tiles_path": f"build/public/{sheet['id']}",
                "metadata_path": f"build/public/{sheet['id']}/metadata.json",
                "tile_set_sha256": TILE_SET_SHA,
            },
            "history": [
                {"state": "planned", "at": EARLIER, "actor": "fixture"},
                {"state": "inputs-ready", "at": EARLIER, "actor": "fixture"},
                {"state": "generated", "at": EARLIER, "actor": "fixture"},
                {"state": "automated-qa", "at": EARLIER, "actor": "fixture"},
                {"state": "vision-qa", "at": EARLIER, "actor": "fixture"},
                {"state": "accepted", "at": EARLIER, "actor": "fixture"},
                {"state": "tiled", "at": EARLIER, "actor": "fixture"},
            ],
        }

    def run_transition(self, target, **kwargs):
        browser_errors = kwargs.pop("browser_errors", [])
        browser_side_effect = kwargs.pop("browser_side_effect", None)
        if target == "published" and "browser_qa_receipt" not in kwargs:
            kwargs["browser_qa_receipt"] = self.browser_receipt
        with (
            mock.patch.object(
                finalizer.phase5,
                "validate_public_tile_release",
                return_value=self.public_result,
            ),
            mock.patch.object(
                finalizer.phase5,
                "validate_build_root",
                return_value=self.build_result,
            ),
            mock.patch.object(
                finalizer.release_validator,
                "validate_release",
                return_value=self.strict_result,
            ),
            mock.patch.object(
                finalizer.browser_qa_validator,
                "validate_browser_qa_receipt_file",
                return_value=(self.browser_receipt_payload, browser_errors),
                side_effect=browser_side_effect,
            ),
        ):
            return finalizer.finalize_release(
                target, repo_root=self.root, at=TIMESTAMP, **kwargs
            )

    def test_two_explicit_transitions_activate_v3_and_leave_receipt_last(self):
        candidate = self.run_transition(
            "release-candidate", build_root=self.build_root
        )
        self.assertTrue(candidate["valid"])
        self.assertFalse(candidate["receipt_created"])
        readiness = json.loads(self.readiness_path.read_text(encoding="utf-8"))
        self.assertEqual(readiness["status"], "release-candidate")
        self.assertNotIn("publication_receipt_path", readiness)
        manifest = json.loads(self.canonical_manifest.read_text(encoding="utf-8"))
        bounded_jobs = [
            job for job in manifest["jobs"] if job.get("sheet_id") in {s["id"] for s in self.bounded}
        ]
        self.assertEqual(len(bounded_jobs), 23)
        self.assertTrue(all(job["status"] == "staging" for job in bounded_jobs))
        self.assertTrue(
            all(job["output"]["metadata_path"].startswith("docs/") for job in bounded_jobs)
        )
        index = json.loads(self.canonical_index.read_text(encoding="utf-8"))
        self.assertTrue(
            all(
                entry["status"] == "staging"
                for entry in [index["root"], *index["sheets"]]
            )
        )
        self.assertEqual(
            self.canonical_index.read_bytes(), self.compatibility_index.read_bytes()
        )
        candidate_html = self.html_path.read_text(encoding="utf-8")
        self.assertIn(
            'name="ea-map-world-release" content="world-v1"',
            candidate_html,
        )
        candidate_cache_key = finalizer._release_cache_key(
            "release-candidate", self.canonical_index.read_bytes()
        )
        self.assertIn(
            f'name="ea-map-cache-key" content="{candidate_cache_key}"',
            candidate_html,
        )

        published = self.run_transition("published")
        self.assertTrue(published["valid"])
        self.assertTrue(published["receipt_required"])
        self.assertFalse(published["receipt_created"])
        self.assertEqual(
            published["browser_qa_receipt_sha256"],
            finalizer._sha256_file(self.browser_receipt),
        )
        self.assertFalse(self.receipt_path.exists())
        readiness = json.loads(self.readiness_path.read_text(encoding="utf-8"))
        self.assertEqual(readiness["status"], "published")
        self.assertEqual(
            readiness["publication_receipt_path"],
            finalizer.RECEIPT_RELATIVE_PATH.as_posix(),
        )
        bundle_owner = readiness["browser_qa_bundle"]
        self.assertEqual(
            bundle_owner["path"], finalizer.BROWSER_QA_BUNDLE_RELATIVE_PATH.as_posix()
        )
        bundle = self.root.joinpath(*finalizer.BROWSER_QA_BUNDLE_RELATIVE_PATH.parts)
        self.assertTrue(bundle.is_dir())
        self.assertEqual(
            bundle_owner["receipt_sha256"],
            finalizer._sha256_file(bundle / finalizer.BROWSER_QA_RECEIPT_NAME),
        )
        _file_count, bundle_tree_sha = finalizer._directory_tree_evidence(bundle)
        self.assertEqual(bundle_owner["tree_sha256"], bundle_tree_sha)
        self.assertEqual(bundle_owner["tested_url"], self.browser_receipt_payload["tested_url"])
        self.assertEqual(bundle_owner["completed_at"], "2026-07-20T00:30:00Z")
        manifest = json.loads(self.canonical_manifest.read_text(encoding="utf-8"))
        bounded_jobs = [
            job for job in manifest["jobs"] if job.get("sheet_id") in {s["id"] for s in self.bounded}
        ]
        self.assertEqual(len(bounded_jobs), 23)
        self.assertTrue(all(job["status"] == "published" for job in bounded_jobs))
        self.assertTrue(
            all(job["history"][-2]["state"] == "staging" for job in bounded_jobs)
        )
        self.assertTrue(
            all(job["history"][-1]["state"] == "published" for job in bounded_jobs)
        )
        html = self.html_path.read_text(encoding="utf-8")
        self.assertIn('name="ea-map-world-release" content="world-v3"', html)
        self.assertIn(
            'name="ea-map-world-fallback-releases" content="world-v2,world-v1"',
            html,
        )
        self.assertIn('name="ea-map-world-v2-manifest"', html)
        self.assertIn('name="ea-map-world-v1-manifest"', html)
        index = json.loads(self.canonical_index.read_text(encoding="utf-8"))
        self.assertTrue(
            all(
                entry["status"] == "published"
                for entry in [index["root"], *index["sheets"]]
            )
        )
        self.assertEqual(
            self.canonical_index.read_bytes(), self.compatibility_index.read_bytes()
        )
        published_cache_key = finalizer._release_cache_key(
            "published", self.canonical_index.read_bytes()
        )
        self.assertIn(
            f'name="ea-map-cache-key" content="{published_cache_key}"', html
        )

    def test_partial_22_job_build_is_refused_without_durable_changes(self):
        source_path = self.build_root / "production-manifest.phase5.json"
        source = json.loads(source_path.read_text(encoding="utf-8"))
        source["jobs"].pop()
        write_json(source_path, source)
        before = {
            path: path.read_bytes()
            for path in (
                self.canonical_manifest,
                self.readiness_path,
                self.canonical_index,
                self.compatibility_index,
                self.html_path,
            )
        }
        with self.assertRaisesRegex(
            finalizer.ReleaseFinalizationError, "exactly one job.*23 bounded"
        ):
            self.run_transition("release-candidate", build_root=self.build_root)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertFalse(self.receipt_path.exists())

    def test_tampered_published_metadata_is_refused_without_state_change(self):
        world_metadata = self.root.joinpath(
            *self._metadata_relative(
                next(sheet for sheet in self.bounded if sheet["sheet_type"] == "world")
            ).parts
        )
        world_metadata.write_bytes(world_metadata.read_bytes() + b" ")
        manifest_before = self.canonical_manifest.read_bytes()
        readiness_before = self.readiness_path.read_bytes()
        with self.assertRaisesRegex(
            finalizer.ReleaseFinalizationError, "metadata SHA-256 mismatch"
        ):
            self.run_transition("release-candidate", build_root=self.build_root)
        self.assertEqual(self.canonical_manifest.read_bytes(), manifest_before)
        self.assertEqual(self.readiness_path.read_bytes(), readiness_before)
        self.assertFalse(self.receipt_path.exists())

    def test_atomic_install_failure_restores_every_original_byte(self):
        paths = (
            self.canonical_manifest,
            self.readiness_path,
            self.canonical_index,
            self.compatibility_index,
            self.html_path,
        )
        before = {path: path.read_bytes() for path in paths}
        real_replace = finalizer.os.replace
        replace_calls = 0

        def fail_second_replace(source, destination):
            nonlocal replace_calls
            replace_calls += 1
            if replace_calls == 2:
                raise OSError("simulated alias swap failure")
            return real_replace(source, destination)

        with mock.patch.object(finalizer.os, "replace", side_effect=fail_second_replace):
            with self.assertRaisesRegex(OSError, "simulated alias swap failure"):
                self.run_transition(
                    "release-candidate", build_root=self.build_root
                )
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(
            list(self.root.rglob("*.phase7.publishing")), [], "staging files leaked"
        )
        self.assertFalse(self.receipt_path.exists())

    def test_published_transition_cannot_skip_release_candidate(self):
        before = self.readiness_path.read_bytes()
        with self.assertRaisesRegex(
            finalizer.ReleaseFinalizationError, "transition from 'release-candidate'"
        ):
            self.run_transition("published")
        self.assertEqual(self.readiness_path.read_bytes(), before)
        self.assertFalse(self.receipt_path.exists())

    def test_published_transition_requires_browser_qa_receipt(self):
        self.run_transition("release-candidate", build_root=self.build_root)
        before = {
            path: path.read_bytes()
            for path in (
                self.canonical_manifest,
                self.readiness_path,
                self.canonical_index,
                self.compatibility_index,
                self.html_path,
            )
        }
        with self.assertRaisesRegex(
            finalizer.ReleaseFinalizationError, "requires a Phase 6 browser QA PASS"
        ):
            self.run_transition("published", browser_qa_receipt=None)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_invalid_browser_qa_receipt_cannot_mutate_publication_state(self):
        self.run_transition("release-candidate", build_root=self.build_root)
        before = self.readiness_path.read_bytes()
        with self.assertRaisesRegex(
            finalizer.ReleaseFinalizationError, "browser QA receipt validation failed"
        ):
            self.run_transition(
                "published", browser_errors=["Royal nearest parent assertion failed"]
            )
        self.assertEqual(self.readiness_path.read_bytes(), before)

    def test_published_transition_rejects_a_mixed_release_candidate_cache_key(self):
        self.run_transition("release-candidate", build_root=self.build_root)
        html = self.html_path.read_text(encoding="utf-8")
        candidate_key = finalizer._release_cache_key(
            "release-candidate", self.canonical_index.read_bytes()
        )
        self.html_path.write_text(
            html.replace(candidate_key, "world-v3-contract-test"),
            encoding="utf-8",
        )
        before = {
            path: path.read_bytes()
            for path in (
                self.canonical_manifest,
                self.readiness_path,
                self.canonical_index,
                self.compatibility_index,
                self.html_path,
            )
        }

        with self.assertRaisesRegex(
            finalizer.ReleaseFinalizationError,
            "exact release-candidate HTML cache key",
        ):
            self.run_transition("published")

        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_published_swap_failure_rolls_back_files_and_canonical_qa_bundle(self):
        self.run_transition("release-candidate", build_root=self.build_root)
        tracked = (
            self.canonical_manifest,
            self.readiness_path,
            self.canonical_index,
            self.compatibility_index,
            self.html_path,
        )
        before = {path: path.read_bytes() for path in tracked}
        real_replace = finalizer.os.replace
        replace_calls = 0

        def fail_after_bundle_install(source, destination):
            nonlocal replace_calls
            replace_calls += 1
            if replace_calls == 2:
                raise OSError("simulated published file swap failure")
            return real_replace(source, destination)

        with mock.patch.object(
            finalizer.os, "replace", side_effect=fail_after_bundle_install
        ):
            with self.assertRaisesRegex(OSError, "published file swap failure"):
                self.run_transition("published")

        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        bundle = self.root.joinpath(*finalizer.BROWSER_QA_BUNDLE_RELATIVE_PATH.parts)
        self.assertFalse(bundle.exists())
        self.assertEqual(list(self.root.rglob("*.phase7.publishing")), [])

    def test_published_dry_run_does_not_leave_a_canonical_or_staged_qa_bundle(self):
        self.run_transition("release-candidate", build_root=self.build_root)
        before = self.readiness_path.read_bytes()

        result = self.run_transition("published", dry_run=True)

        self.assertTrue(result["valid"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(self.readiness_path.read_bytes(), before)
        bundle = self.root.joinpath(*finalizer.BROWSER_QA_BUNDLE_RELATIVE_PATH.parts)
        self.assertFalse(bundle.exists())
        self.assertEqual(list(self.root.rglob("*.phase7.publishing")), [])

    def test_qa_bundle_race_before_readiness_commit_rolls_back_publication(self):
        self.run_transition("release-candidate", build_root=self.build_root)
        tracked = (
            self.canonical_manifest,
            self.readiness_path,
            self.canonical_index,
            self.compatibility_index,
            self.html_path,
        )
        before = {path: path.read_bytes() for path in tracked}
        real_replace = finalizer.os.replace
        replace_calls = 0

        def mutate_bundle_after_html(source, destination):
            nonlocal replace_calls
            replace_calls += 1
            result = real_replace(source, destination)
            if replace_calls == 5:
                bundle = self.root.joinpath(
                    *finalizer.BROWSER_QA_BUNDLE_RELATIVE_PATH.parts
                )
                (bundle / "raced.txt").write_text("race\n", encoding="utf-8")
            return result

        with mock.patch.object(
            finalizer.os, "replace", side_effect=mutate_bundle_after_html
        ):
            with self.assertRaisesRegex(
                finalizer.ReleaseFinalizationError, "before the readiness commit"
            ):
                self.run_transition("published")

        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        bundle = self.root.joinpath(*finalizer.BROWSER_QA_BUNDLE_RELATIVE_PATH.parts)
        self.assertFalse(bundle.exists())

    def test_browser_qa_receipt_change_during_validation_is_rejected(self):
        self.run_transition("release-candidate", build_root=self.build_root)
        readiness_before = self.readiness_path.read_bytes()

        def mutate_receipt(path, **_kwargs):
            path.write_bytes(path.read_bytes() + b" ")
            return self.browser_receipt_payload, []

        with self.assertRaisesRegex(
            finalizer.ReleaseFinalizationError, "changed while it was being validated"
        ):
            self.run_transition("published", browser_side_effect=mutate_receipt)
        self.assertEqual(self.readiness_path.read_bytes(), readiness_before)


if __name__ == "__main__":
    unittest.main()
