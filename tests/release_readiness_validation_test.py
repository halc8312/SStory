import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import validate_release_readiness  # noqa: E402
import validate_phase6_browser_qa  # noqa: E402
import build_phase5_assets as phase5  # noqa: E402
import generate_tiles  # noqa: E402


READINESS_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "release-readiness.schema.json"
)


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def valid_result(**overrides):
    result = {
        "valid": True,
        "jobs_checked": 3,
        "required_sheets": 23,
        "covered_sheets": 0,
        "errors": [],
    }
    result.update(overrides)
    return result


def create_browser_qa_bundle(root: Path) -> tuple[dict, dict]:
    bundle = root.joinpath(*validate_release_readiness.BROWSER_QA_BUNDLE_PATH.parts)
    receipt_path = bundle / validate_release_readiness.BROWSER_QA_RECEIPT_NAME
    browser_receipt = {
        "release_id": "world-v3",
        "result": "pass",
        "tested_url": "http://127.0.0.1:8765/pages/interactive-map-v3.html?release-preview=world-v3",
        "completed_at": "2026-07-20T00:00:00Z",
    }
    write_json(receipt_path, browser_receipt)
    _file_count, tree_sha = validate_release_readiness._browser_bundle_tree_evidence(
        bundle
    )
    owner = {
        "path": validate_release_readiness.BROWSER_QA_BUNDLE_PATH.as_posix(),
        "receipt_sha256": validate_release_readiness._sha256_file(receipt_path),
        "tree_sha256": tree_sha,
        "tested_url": browser_receipt["tested_url"],
        "completed_at": browser_receipt["completed_at"],
    }
    return owner, browser_receipt


def build_published_world_v3_fixture(root: Path) -> tuple[Path, dict]:
    """Create a complete real-file public release under a repository-local root."""

    release_id = "world-v3"
    timestamp = "2026-07-20T00:00:00Z"
    build_root = root / "build"
    public_root = build_root / "public"
    docs_root = root / "docs"
    master = root / "accepted-master-evidence.png"
    evidence_file = root / "accepted-evidence.json"
    Image.new("RGB", (8, 8), (90, 120, 80)).save(master)
    evidence_file.write_text('{"accepted":true}\n', encoding="utf-8")
    evidence_path = phase5.repo_path(evidence_file)
    evidence = phase5.QAEvidence(
        provenance_path=evidence_path,
        automated_path=evidence_path,
        vision_paths=(evidence_path,),
        primary_score=96,
        primary_reviewer="Fixture Reviewer",
    )
    _, catalog_by_id, derived = phase5.load_contract(
        phase5.DEFAULT_CONTRACT, phase5.DEFAULT_MAP_SHEETS
    )
    contracts = derived["sheets"]
    tile_cache = {}

    def edge_tile(width, height):
        key = (width, height)
        cached = tile_cache.get(key)
        if cached is None:
            cached = root / f"tile-{width}x{height}.webp"
            image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
            image.paste((80, 110, 140, 255), (0, 0, width, height))
            image.save(cached, format="WEBP", lossless=True, method=6, exact=True)
            tile_cache[key] = cached
        return cached

    assets = []
    for sheet_id, contract in contracts.items():
        sheet = catalog_by_id[sheet_id]
        relative_manifest = phase5._public_manifest_path(sheet, release_id)
        manifest_path = public_root / Path(*relative_manifest.parts)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        levels = []
        tile_digests = []
        for zoom in range(contract["zoom_range"][0], contract["native_zoom"] + 1):
            factor = 2 ** (contract["native_zoom"] - zoom)
            width = max(1, math.ceil(contract["width"] / factor))
            height = max(1, math.ceil(contract["height"] / factor))
            columns = math.ceil(width / 512)
            rows = math.ceil(height / 512)
            levels.append(
                {
                    "zoom": zoom,
                    "width": width,
                    "height": height,
                    "columns": columns,
                    "rows": rows,
                    "tile_count": columns * rows,
                }
            )
            for column in range(columns):
                for row in range(rows):
                    tile_path = manifest_path.parent / str(zoom) / str(column) / f"{row}.webp"
                    tile_path.parent.mkdir(parents=True, exist_ok=True)
                    content_width = min(512, width - column * 512)
                    content_height = min(512, height - row * 512)
                    shutil.copyfile(edge_tile(content_width, content_height), tile_path)
                    relative = f"{zoom}/{column}/{row}.webp"
                    tile_digests.append((relative, phase5.sha256_file(tile_path)))
        metadata = {
            "schema_version": "1.0.0",
            "type": "sstory-xyz-raster",
            "generated_by": generate_tiles.GENERATOR_ID,
            "generated_at": timestamp,
            "release_id": release_id,
            "map_id": sheet_id,
            "scheme": "xyz",
            "coordinate_scope": "sheet-local",
            "tile_origin": "top-left",
            "x_axis": "right",
            "y_axis": "down",
            "edge_padding": "transparent",
            "format": "webp",
            "tile_size": 512,
            "minzoom": contract["zoom_range"][0],
            "maxzoom": contract["native_zoom"],
            "native_zoom": contract["native_zoom"],
            "tiles": ["{z}/{x}/{y}.webp"],
            "coordinate_reference_system": "EA-WORLD-1",
            "coordinate_system": "EA-WORLD-1",
            "bounds": sheet["bounds"],
            "master": {
                "path": phase5.repo_path(master),
                "sha256": phase5.sha256_file(master),
                "width": contract["width"],
                "height": contract["height"],
                "mode": "RGBA",
            },
            "encoding": {
                "quality": 88,
                "lossless": False,
                "background": "#00000000",
            },
            "levels": levels,
            "tile_count": len(tile_digests),
            "tile_set_sha256": phase5._tile_set_digest(tile_digests),
        }
        phase5.dump_json(manifest_path, metadata)
        assets.append(
            phase5.BuiltAsset(
                sheet=sheet,
                contract=contract,
                job_id=phase5.job_id_for_sheet(sheet_id),
                method="verified-master-import",
                stage_path=master,
                final_manifest_path=phase5.repo_path(master),
                sha256=phase5.sha256_file(master),
                accepted_evidence=evidence,
                tiled_output={
                    "tiles_path": phase5.repo_path(manifest_path.parent),
                    "metadata_path": phase5.repo_path(manifest_path),
                    "tile_set_sha256": metadata["tile_set_sha256"],
                },
            )
        )

    evidence_binding = phase5.bind_file(
        evidence_file,
        label="published runtime fixture accepted evidence",
        trackable=False,
    )
    with phase5.bound_artifact_context((evidence_binding,)):
        phase5.build_sheet_tile_index(
            assets,
            build_root,
            release_id=release_id,
            generated_at=timestamp,
        )
    shutil.copytree(public_root, docs_root, dirs_exist_ok=True)
    html_path = docs_root / "pages" / "interactive-map-v3.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(
        """<!doctype html><html><head>
<meta name="ea-map-world-release" content="world-v3">
<meta name="ea-map-world-target-release" content="world-v3">
<meta name="ea-map-world-fallback-releases" content="world-v2,world-v1">
<meta name="ea-map-world-v3-manifest" content="../assets/images/maps/tiles/world-v3/metadata.json">
<meta name="ea-map-sheet-tile-index" content="../data/map/region-rasters.json">
<meta name="ea-map-cache-key" content="world-v3-release-test">
</head><body></body></html>
""",
        encoding="utf-8",
    )
    validation = phase5.validate_public_tile_release(
        docs_root, release_id=release_id, verify_tiles=True
    )
    if not validation["valid"]:
        raise AssertionError(validation["errors"])
    release_tree = docs_root / "assets" / "images" / "maps" / "tiles" / release_id
    file_count, tree_sha = validate_release_readiness._release_tree_evidence(release_tree)
    canonical = docs_root / "data" / "map" / "sheet-tiles-v3.json"
    compatibility = docs_root / "data" / "map" / "region-rasters.json"
    browser_qa_owner, _browser_receipt = create_browser_qa_bundle(root)
    receipt = {
        "$schema": "https://sstory.example/schemas/publication-receipt.schema.json",
        "schema_version": "1.0.0",
        "type": "sstory-map-publication-receipt",
        "release_id": release_id,
        "published_at": timestamp,
        "published_by": "unit-test",
        "canonical_index": {
            "path": "docs/data/map/sheet-tiles-v3.json",
            "sha256": phase5.sha256_file(canonical),
        },
        "compatibility_index": {
            "path": "docs/data/map/region-rasters.json",
            "sha256": phase5.sha256_file(compatibility),
        },
        "release_tree": {
            "path": "docs/assets/images/maps/tiles/world-v3",
            "file_count": file_count,
            "sha256": tree_sha,
        },
        "browser_qa": browser_qa_owner,
        "html": {
            "path": "docs/pages/interactive-map-v3.html",
            "sha256": phase5.sha256_file(html_path),
        },
        "runtime": {
            "active_release": "world-v3",
            "target_release": "world-v3",
            "fallback_releases": ["world-v2", "world-v1"],
            "cache_key": "world-v3-release-test",
            "world_v3_manifest": "../assets/images/maps/tiles/world-v3/metadata.json",
            "sheet_tile_index": "../data/map/region-rasters.json",
        },
        "validation": {
            "bounded_sheet_count": validation["bounded_sheet_count"],
            "tile_count": validation["tile_count"],
            "tile_bytes": validation["tile_bytes"],
        },
    }
    receipt_path = root / "world" / "map-production" / "releases" / "world-v3-publication-receipt.json"
    write_json(receipt_path, receipt)
    return receipt_path, receipt


class ReleaseReadinessValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.declaration = self.root / "world" / "map-production" / "release-readiness.json"
        self.manifest = self.root / "world" / "map-production" / "production-manifest.json"
        self.base = {
            "$schema": "schemas/release-readiness.schema.json",
            "schema_version": "1.0.0",
            "status": "in-progress",
            "manifest_path": "world/map-production/production-manifest.json",
        }
        write_json(self.manifest, {"jobs": []})
        write_json(self.declaration, self.base)

    def validate(self):
        return validate_release_readiness.validate_release_readiness(
            self.declaration,
            schema_path=READINESS_SCHEMA,
            repo_root=self.root,
        )

    def test_in_progress_runs_integrity_checks_without_strict_release(self):
        with mock.patch.object(
            validate_release_readiness.release_validator,
            "validate_release",
            return_value=valid_result(),
        ) as validator:
            result = self.validate()

        self.assertTrue(result["valid"])
        self.assertFalse(result["strict_release_required"])
        self.assertFalse(result["strict_release_executed"])
        self.assertEqual(validator.call_count, 2)
        integrity_call, coverage_call = validator.call_args_list
        self.assertFalse(integrity_call.kwargs["strict_release"])
        self.assertTrue(coverage_call.kwargs["require_sheet_coverage"])
        self.assertEqual(coverage_call.kwargs["sheet_minimum_state"], "accepted")

    def test_complete_accepted_coverage_requires_release_candidate_status(self):
        with mock.patch.object(
            validate_release_readiness.release_validator,
            "validate_release",
            side_effect=[
                valid_result(),
                valid_result(required_sheets=23, covered_sheets=23),
            ],
        ):
            result = self.validate()

        self.assertFalse(result["valid"])
        self.assertTrue(
            any("all 23 bounded sheets" in error for error in result["errors"])
        )

    def test_release_candidate_cannot_skip_strict_release(self):
        readiness = dict(self.base, status="release-candidate")
        write_json(self.declaration, readiness)
        with mock.patch.object(
            validate_release_readiness.release_validator,
            "validate_release",
            return_value=valid_result(required_sheets=23, covered_sheets=23),
        ) as validator:
            result = self.validate()

        self.assertTrue(result["valid"])
        self.assertTrue(result["strict_release_required"])
        self.assertTrue(result["strict_release_executed"])
        self.assertTrue(validator.call_args.kwargs["strict_release"])
        self.assertEqual(validator.call_args.kwargs["sheet_minimum_state"], "accepted")

    def test_published_declaration_requires_published_sheet_coverage(self):
        browser_owner, _browser_receipt = create_browser_qa_bundle(self.root)
        write_json(
            self.declaration,
            dict(
                self.base,
                status="published",
                publication_receipt_path=(
                    "world/map-production/releases/world-v3-publication-receipt.json"
                ),
                browser_qa_bundle=browser_owner,
            ),
        )
        with (
            mock.patch.object(
                validate_release_readiness.release_validator,
                "validate_release",
                return_value=valid_result(required_sheets=23, covered_sheets=23),
            ) as validator,
            mock.patch.object(
                validate_release_readiness,
                "_validate_published_runtime",
                return_value=({"release_id": "world-v3"}, []),
            ),
        ):
            result = self.validate()

        self.assertTrue(result["valid"])
        self.assertEqual(validator.call_args.kwargs["sheet_minimum_state"], "published")

    def test_published_without_persistent_receipt_fails_before_validation(self):
        write_json(self.declaration, dict(self.base, status="published"))
        with mock.patch.object(
            validate_release_readiness.release_validator,
            "validate_release",
        ) as validator:
            result = self.validate()

        self.assertFalse(result["valid"])
        self.assertTrue(
            any("publication_receipt_path" in error for error in result["errors"])
        )
        validator.assert_not_called()

    def test_strict_release_failure_is_propagated(self):
        write_json(self.declaration, dict(self.base, status="release-candidate"))
        with mock.patch.object(
            validate_release_readiness.release_validator,
            "validate_release",
            return_value=valid_result(valid=False, errors=["golden gate failed"]),
        ):
            result = self.validate()

        self.assertFalse(result["valid"])
        self.assertIn("release validation: golden gate failed", result["errors"])

    def test_validator_cannot_fail_silently(self):
        write_json(self.declaration, dict(self.base, status="release-candidate"))
        with mock.patch.object(
            validate_release_readiness.release_validator,
            "validate_release",
            return_value=valid_result(valid=False, errors=[]),
        ):
            result = self.validate()

        self.assertFalse(result["valid"])
        self.assertIn(
            "release validation failed without diagnostic details",
            result["errors"],
        )

    def test_in_progress_cannot_hide_staging_or_published_jobs(self):
        write_json(
            self.manifest,
            {
                "jobs": [
                    {"id": "sheet-a-v1", "status": "staging"},
                    {"id": "sheet-b-v1", "status": "published"},
                ]
            },
        )
        with mock.patch.object(
            validate_release_readiness.release_validator,
            "validate_release",
            return_value=valid_result(),
        ):
            result = self.validate()

        self.assertFalse(result["valid"])
        self.assertTrue(any("sheet-a-v1, sheet-b-v1" in error for error in result["errors"]))

    def test_schema_is_fail_closed_for_unknown_fields(self):
        readiness = dict(self.base, bypass_strict_release=True)
        write_json(self.declaration, readiness)
        with mock.patch.object(
            validate_release_readiness.release_validator,
            "validate_release",
        ) as validator:
            result = self.validate()

        self.assertFalse(result["valid"])
        self.assertTrue(any("Additional properties" in error for error in result["errors"]))
        validator.assert_not_called()

    def test_manifest_path_cannot_escape_the_repository(self):
        readiness = dict(self.base, manifest_path="../outside.json")
        write_json(self.declaration, readiness)
        with mock.patch.object(
            validate_release_readiness.release_validator,
            "validate_release",
        ) as validator:
            result = self.validate()

        self.assertFalse(result["valid"])
        self.assertTrue(any("must stay inside" in error for error in result["errors"]))
        validator.assert_not_called()


class PublishedRuntimeFileValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(
            prefix=".published-runtime-test-", dir=REPO_ROOT
        )
        cls.root = Path(cls.temporary.name)
        cls.receipt_path, cls.receipt = build_published_world_v3_fixture(cls.root)
        cls.manifest = (
            cls.root / "world" / "map-production" / "production-manifest.json"
        )
        cls.declaration = (
            cls.root / "world" / "map-production" / "release-readiness.json"
        )
        write_json(cls.manifest, {"jobs": []})
        write_json(
            cls.declaration,
            {
                "$schema": "schemas/release-readiness.schema.json",
                "schema_version": "1.0.0",
                "status": "published",
                "manifest_path": "world/map-production/production-manifest.json",
                "publication_receipt_path": (
                    "world/map-production/releases/world-v3-publication-receipt.json"
                ),
                "browser_qa_bundle": cls.receipt["browser_qa"],
            },
        )

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def validate(self):
        browser_receipt = json.loads(
            (
                self.root.joinpath(
                    *validate_release_readiness.BROWSER_QA_BUNDLE_PATH.parts
                )
                / validate_release_readiness.BROWSER_QA_RECEIPT_NAME
            ).read_text(encoding="utf-8")
        )
        with (
            mock.patch.object(
                validate_release_readiness.release_validator,
                "validate_release",
                return_value=valid_result(required_sheets=23, covered_sheets=23),
            ),
            mock.patch.object(
                validate_phase6_browser_qa,
                "validate_persisted_browser_qa_bundle",
                return_value=(browser_receipt, []),
            ),
        ):
            return validate_release_readiness.validate_release_readiness(
                self.declaration,
                schema_path=READINESS_SCHEMA,
                repo_root=self.root,
            )

    def test_real_file_published_world_v3_fixture_passes(self):
        result = self.validate()

        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(result["published_runtime_checked"])

    def test_partial_alias_swap_is_rejected_even_with_a_receipt(self):
        alias = self.root / "docs" / "data" / "map" / "region-rasters.json"
        original = alias.read_bytes()
        alias.write_bytes(original + b"\n")
        try:
            result = self.validate()
        finally:
            alias.write_bytes(original)

        self.assertFalse(result["valid"])
        self.assertTrue(
            any("byte-identical" in error for error in result["errors"]),
            result["errors"],
        )

    def test_html_active_release_cannot_lag_behind_published_world_v3(self):
        html = self.root / "docs" / "pages" / "interactive-map-v3.html"
        original_html = html.read_bytes()
        original_receipt = self.receipt_path.read_bytes()
        changed_html = original_html.replace(
            b'content="world-v3"', b'content="world-v1"', 1
        )
        html.write_bytes(changed_html)
        changed_receipt = json.loads(original_receipt)
        changed_receipt["html"]["sha256"] = phase5.sha256_file(html)
        write_json(self.receipt_path, changed_receipt)
        try:
            result = self.validate()
        finally:
            html.write_bytes(original_html)
            self.receipt_path.write_bytes(original_receipt)

        self.assertFalse(result["valid"])
        self.assertTrue(
            any("ea-map-world-release mismatch" in error for error in result["errors"]),
            result["errors"],
        )

    def test_process_crash_staging_artifact_is_rejected(self):
        stale = (
            self.root
            / "docs"
            / "data"
            / "map"
            / ".sheet-tiles-v3.json.world-v3.publishing"
        )
        stale.write_text("partial", encoding="utf-8")
        try:
            result = self.validate()
        finally:
            stale.unlink()

        self.assertFalse(result["valid"])
        self.assertTrue(
            any("staging artifacts" in error for error in result["errors"]),
            result["errors"],
        )

    def test_browser_qa_bundle_tree_tamper_is_rejected(self):
        bundle = self.root.joinpath(
            *validate_release_readiness.BROWSER_QA_BUNDLE_PATH.parts
        )
        extra = bundle / "undeclared-after-publication.txt"
        extra.write_text("tamper\n", encoding="utf-8")
        try:
            result = self.validate()
        finally:
            extra.unlink()

        self.assertFalse(result["valid"])
        self.assertTrue(
            any("browser QA bundle tree_sha256 mismatch" in error for error in result["errors"]),
            result["errors"],
        )

    def test_publication_receipt_must_repeat_exact_readiness_browser_owner(self):
        original = self.receipt_path.read_bytes()
        changed = json.loads(original)
        changed["browser_qa"]["tree_sha256"] = "0" * 64
        write_json(self.receipt_path, changed)
        try:
            result = self.validate()
        finally:
            self.receipt_path.write_bytes(original)

        self.assertFalse(result["valid"])
        self.assertTrue(
            any("must exactly match" in error for error in result["errors"]),
            result["errors"],
        )

    def test_publication_receipt_cannot_predate_browser_qa(self):
        original = self.receipt_path.read_bytes()
        changed = json.loads(original)
        changed["published_at"] = "2026-07-19T23:59:59Z"
        write_json(self.receipt_path, changed)
        try:
            result = self.validate()
        finally:
            self.receipt_path.write_bytes(original)

        self.assertFalse(result["valid"])
        self.assertTrue(
            any("precedes Phase 6 browser QA" in error for error in result["errors"]),
            result["errors"],
        )


if __name__ == "__main__":
    unittest.main()
