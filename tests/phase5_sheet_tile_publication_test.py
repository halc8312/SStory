import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urljoin

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import build_phase5_assets as phase5  # noqa: E402
import generate_tiles  # noqa: E402
import publish_phase5_tiles as publisher  # noqa: E402


TIMESTAMP = "2026-07-19T16:36:13Z"
RELEASE_ID = "world-v3-test"


class Phase5SheetTilePublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(
            prefix=".phase5-sheet-publication-test-", dir=REPO_ROOT
        )
        cls.root = Path(cls.temporary.name)
        cls.build_root = cls.root / "build"
        cls.public_root = cls.build_root / "public"
        cls.master = cls.root / "accepted-master-evidence.png"
        Image.new("RGB", (8, 8), (90, 120, 80)).save(cls.master)
        cls.evidence_file = cls.root / "accepted-evidence.json"
        cls.evidence_file.write_text('{"accepted":true}\n', encoding="utf-8")
        cls.evidence_path = phase5.repo_path(cls.evidence_file)
        cls.evidence = phase5.QAEvidence(
            provenance_path=cls.evidence_path,
            automated_path=cls.evidence_path,
            vision_paths=(cls.evidence_path,),
            primary_score=96,
            primary_reviewer="Fixture Reviewer",
        )
        _, cls.catalog_by_id, derived = phase5.load_contract(
            phase5.DEFAULT_CONTRACT, phase5.DEFAULT_MAP_SHEETS
        )
        cls.contracts = derived["sheets"]
        cls.tile_template = cls.root / "tile.webp"
        Image.new("RGBA", (512, 512), (80, 110, 140, 255)).save(
            cls.tile_template, format="WEBP", lossless=True, method=6, exact=True
        )
        cls.tile_sha = phase5.sha256_file(cls.tile_template)
        cls.edge_tile_cache = {}

        def edge_tile(width, height):
            key = (width, height)
            cached = cls.edge_tile_cache.get(key)
            if cached is None:
                cached = cls.root / f"tile-{width}x{height}.webp"
                image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
                image.paste((80, 110, 140, 255), (0, 0, width, height))
                image.save(cached, format="WEBP", lossless=True, method=6, exact=True)
                cls.edge_tile_cache[key] = cached
            return cached

        cls.assets = []
        for sheet_id, contract in cls.contracts.items():
            sheet = cls.catalog_by_id[sheet_id]
            manifest_relative = phase5._public_manifest_path(sheet, RELEASE_ID)
            manifest_path = cls.public_root / Path(*manifest_relative.parts)
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
                    tile_dir = manifest_path.parent / str(zoom) / str(column)
                    tile_dir.mkdir(parents=True, exist_ok=True)
                    for row in range(rows):
                        relative = f"{zoom}/{column}/{row}.webp"
                        content_width = min(512, width - column * 512)
                        content_height = min(512, height - row * 512)
                        tile_path = tile_dir / f"{row}.webp"
                        shutil.copyfile(edge_tile(content_width, content_height), tile_path)
                        tile_digests.append((relative, phase5.sha256_file(tile_path)))
            metadata = {
                "schema_version": "1.0.0",
                "type": "sstory-xyz-raster",
                "generated_by": generate_tiles.GENERATOR_ID,
                "generated_at": TIMESTAMP,
                "release_id": RELEASE_ID,
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
                    "path": phase5.repo_path(cls.master),
                    "sha256": phase5.sha256_file(cls.master),
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
            cls.assets.append(
                phase5.BuiltAsset(
                    sheet=sheet,
                    contract=contract,
                    job_id=phase5.job_id_for_sheet(sheet_id),
                    method="verified-master-import",
                    stage_path=cls.master,
                    final_manifest_path=phase5.repo_path(cls.master),
                    sha256=phase5.sha256_file(cls.master),
                    accepted_evidence=cls.evidence,
                    tiled_output={
                        "tiles_path": phase5.repo_path(manifest_path.parent),
                        "metadata_path": phase5.repo_path(manifest_path),
                        "tile_set_sha256": metadata["tile_set_sha256"],
                    },
                )
            )
        evidence_binding = phase5.bind_file(
            cls.evidence_file,
            label="sheet publication fixture accepted evidence",
            trackable=False,
        )
        with phase5.bound_artifact_context((evidence_binding,)):
            cls.index = phase5.build_sheet_tile_index(
                cls.assets,
                cls.build_root,
                release_id=RELEASE_ID,
                generated_at=TIMESTAMP,
            )
        cls.validation = phase5.validate_public_tile_release(
            cls.public_root, release_id=RELEASE_ID
        )

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_schema2_index_covers_root_plus_all_22_descendants(self):
        self.assertTrue(self.validation["valid"], self.validation["errors"])
        self.assertEqual(self.validation["bounded_sheet_count"], 23)
        self.assertEqual(
            self.validation["tile_count"], phase5.EXPECTED_PHASE5_TILE_COUNT
        )
        self.assertEqual(self.validation["tile_count"], 1350)
        self.assertEqual(self.index["root_id"], "sheet_world")
        self.assertEqual(self.index["root"]["sheet_type"], "world")
        self.assertEqual(len(self.index["sheets"]), 22)
        self.assertEqual(
            {self.index["root"]["sheet_id"], *(entry["sheet_id"] for entry in self.index["sheets"])},
            set(self.contracts),
        )
        self.assertTrue(
            all(entry["review_status"] == "accepted" for entry in self.index["sheets"])
        )
        self.assertTrue(all(entry["status"] == "tiled" for entry in self.index["sheets"]))

    def test_repository_legacy_index_is_an_empty_deprecated_placeholder(self):
        placeholder = json.loads(
            (REPO_ROOT / "docs" / "data" / "map" / "region-rasters.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(placeholder["deprecated"])
        self.assertEqual(placeholder["replacement_type"], "sstory-sheet-tile-index@2.0.0")
        self.assertEqual(placeholder["rasters"], [])

    def test_manifest_urls_resolve_from_index_and_tiles_from_each_manifest(self):
        index_url = "https://example.test/docs/data/map/sheet-tiles-v3.json"
        entries = [self.index["root"], *self.index["sheets"]]
        for entry in entries:
            resolved_manifest = urljoin(index_url, entry["manifest_url"])
            expected_relative = phase5._public_manifest_path(
                self.catalog_by_id[entry["sheet_id"]], RELEASE_ID
            )
            self.assertEqual(
                resolved_manifest,
                "https://example.test/docs/" + expected_relative.as_posix(),
            )
            manifest_path = self.public_root / Path(*expected_relative.parts)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                urljoin(resolved_manifest, manifest["tiles"][0]),
                resolved_manifest.removesuffix("metadata.json") + "{z}/{x}/{y}.webp",
            )

    def test_sheet_local_pixel_contract_covers_right_bottom_and_corner_padding(self):
        good = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        good.paste((10, 20, 30, 255), (0, 0, 188, 138))
        self.assertEqual(
            phase5._sheet_local_tile_pixel_errors(
                good,
                level_width=700,
                level_height=650,
                column=1,
                row=1,
                label="corner",
            ),
            [],
        )

        fully_opaque_edge = Image.new("RGBA", (512, 512), (10, 20, 30, 255))
        failures = phase5._sheet_local_tile_pixel_errors(
            fully_opaque_edge,
            level_width=700,
            level_height=650,
            column=1,
            row=1,
            label="corner",
        )
        self.assertTrue(any("right-edge padding" in error for error in failures))
        self.assertTrue(any("bottom-edge padding" in error for error in failures))

    def test_sheet_local_y_axis_uses_row_as_downward_pixel_offset(self):
        tile = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        tile.paste((10, 20, 30, 255), (0, 0, 512, 88))
        self.assertEqual(
            phase5._sheet_local_tile_pixel_errors(
                tile,
                level_width=512,
                level_height=600,
                column=0,
                row=1,
                label="bottom",
            ),
            [],
        )
        tile.putpixel((0, 88), (10, 20, 30, 255))
        self.assertTrue(
            any(
                "bottom-edge padding" in error
                for error in phase5._sheet_local_tile_pixel_errors(
                    tile,
                    level_width=512,
                    level_height=600,
                    column=0,
                    row=1,
                    label="bottom",
                )
            )
        )

    def test_parent_tampering_is_rejected_without_reading_tiles(self):
        canonical = self.public_root / Path(*phase5.PUBLIC_INDEX_CANONICAL_PATH.parts)
        compatibility = (
            self.public_root / Path(*phase5.PUBLIC_INDEX_COMPATIBILITY_PATH.parts)
        )
        original = canonical.read_bytes()
        changed = json.loads(original)
        target = next(
            entry
            for entry in changed["sheets"]
            if entry["sheet_id"] == "sheet_region_royal_capital_region"
        )
        target["parent_id"] = "sheet_continent_lumiera"
        phase5.dump_json(canonical, changed)
        shutil.copyfile(canonical, compatibility)
        try:
            result = phase5.validate_public_tile_release(
                self.public_root, release_id=RELEASE_ID, verify_tiles=False
            )
            self.assertFalse(result["valid"])
            self.assertTrue(
                any("parent_id mismatch" in error for error in result["errors"]),
                result["errors"],
            )
        finally:
            canonical.write_bytes(original)
            compatibility.write_bytes(original)

    def test_builder_emits_deterministic_versioned_manifests_not_full_webps(self):
        with tempfile.TemporaryDirectory(
            prefix=".phase5-tile-builder-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)

            def assets_for_run():
                return [
                    phase5.BuiltAsset(
                        sheet=self.catalog_by_id[sheet_id],
                        contract={**contract, "width": 8, "height": 8},
                        job_id=phase5.job_id_for_sheet(sheet_id),
                        method="verified-master-import",
                        stage_path=self.master,
                        final_manifest_path=phase5.repo_path(self.master),
                        sha256=phase5.sha256_file(self.master),
                        accepted_evidence=self.evidence,
                    )
                    for sheet_id, contract in self.contracts.items()
                ]

            def fast_fixture_pyramid(source, output, **kwargs):
                levels = []
                tile_digests = []
                for zoom in range(kwargs["min_zoom"], kwargs["max_zoom"] + 1):
                    factor = 2 ** (kwargs["max_zoom"] - zoom)
                    width = max(1, math.ceil(8 / factor))
                    height = max(1, math.ceil(8 / factor))
                    tile_path = output / str(zoom) / "0" / "0.webp"
                    tile_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(self.tile_template, tile_path)
                    relative = f"{zoom}/0/0.webp"
                    tile_digests.append((relative, self.tile_sha))
                    levels.append(
                        {
                            "zoom": zoom,
                            "width": width,
                            "height": height,
                            "columns": 1,
                            "rows": 1,
                            "tile_count": 1,
                        }
                    )
                metadata = {
                    "schema_version": "1.0.0",
                    "type": "sstory-xyz-raster",
                    "generated_by": generate_tiles.GENERATOR_ID,
                    "generated_at": "replaced-by-builder",
                    "map_id": kwargs["map_id"],
                    "scheme": "xyz",
                    "format": "webp",
                    "tile_size": kwargs["tile_size"],
                    "minzoom": kwargs["min_zoom"],
                    "maxzoom": kwargs["max_zoom"],
                    "native_zoom": kwargs["max_zoom"],
                    "tiles": [kwargs["url_template"]],
                    "coordinate_reference_system": kwargs["coordinate_system"],
                    "coordinate_system": kwargs["coordinate_system"],
                    "bounds": list(kwargs["bounds"]),
                    "master": {
                        "path": phase5.repo_path(source),
                        "sha256": phase5.sha256_file(source),
                        "width": 8,
                        "height": 8,
                        "mode": "RGBA",
                    },
                    "encoding": {
                        "quality": kwargs["quality"],
                        "lossless": False,
                        "background": "#00000000",
                    },
                    "levels": levels,
                    "tile_count": len(tile_digests),
                    "tile_set_sha256": phase5._tile_set_digest(tile_digests),
                }
                phase5.dump_json(output / "metadata.json", metadata)
                return metadata

            outputs = []
            with patch.object(
                phase5, "generate_pyramid", side_effect=fast_fixture_pyramid
            ):
                for name in ("first", "second"):
                    staging = root / name
                    final = root / f"{name}-final"
                    assets = assets_for_run()
                    phase5.build_tiles_for_accepted(
                        assets,
                        staging,
                        final,
                        webp_quality=80,
                        release_id=RELEASE_ID,
                        generated_at=TIMESTAMP,
                    )
                    outputs.append(staging / "public")
                    world_manifest = (
                        staging
                        / "public"
                        / Path(
                            *phase5._public_manifest_path(
                                self.catalog_by_id["sheet_world"], RELEASE_ID
                            ).parts
                        )
                    )
                    region_manifest = (
                        staging
                        / "public"
                        / Path(
                            *phase5._public_manifest_path(
                                self.catalog_by_id[
                                    "sheet_region_royal_capital_region"
                                ],
                                RELEASE_ID,
                            ).parts
                        )
                    )
                    self.assertTrue(world_manifest.is_file())
                    self.assertTrue(region_manifest.is_file())
                    metadata = json.loads(region_manifest.read_text(encoding="utf-8"))
                    self.assertEqual(metadata["type"], "sstory-xyz-raster")
                    self.assertEqual(metadata["tile_size"], 512)
                    self.assertEqual(metadata["release_id"], RELEASE_ID)
                    self.assertEqual(metadata["tiles"], ["{z}/{x}/{y}.webp"])
                    schema = json.loads(
                        phase5.DEFAULT_TILE_MANIFEST_SCHEMA.read_text(encoding="utf-8")
                    )
                    self.assertEqual(phase5.schema_errors(metadata, schema), [])
                    self.assertFalse(
                        (staging / "public" / "region-rasters").exists()
                    )

            def tree_hashes(path):
                return {
                    candidate.relative_to(path).as_posix(): phase5.sha256_file(candidate)
                    for candidate in path.rglob("*")
                    if candidate.is_file()
                }

            self.assertEqual(tree_hashes(outputs[0]), tree_hashes(outputs[1]))

    def test_publication_copies_version_immutably_and_replaces_legacy_alias(self):
        docs_root = self.root / "docs-target"
        legacy_index = docs_root / "data" / "map" / "region-rasters.json"
        legacy_index.parent.mkdir(parents=True, exist_ok=True)
        legacy_index.write_text('{"schema_version":"1.0.0","rasters":[]}\n', encoding="utf-8")
        source_validation = {
            "valid": True,
            "public_tile_release": self.validation,
            "errors": [],
        }
        with patch.object(
            publisher.phase5, "validate_build_root", return_value=source_validation
        ):
            dry_run = publisher.publish_release(
                self.build_root, docs_root, dry_run=True
            )
            self.assertTrue(dry_run["valid"])
            self.assertFalse(Path(dry_run["destination"]).is_absolute())
            result = publisher.publish_release(self.build_root, docs_root)
            self.assertTrue(result["valid"])
            self.assertEqual(result["bounded_sheet_count"], 23)
            self.assertEqual(result["tile_count"], self.validation["tile_count"])
            published_index = json.loads(legacy_index.read_text(encoding="utf-8"))
            self.assertEqual(published_index["type"], "sstory-sheet-tile-index")
            self.assertEqual(published_index["schema_version"], "2.0.0")
            with self.assertRaisesRegex(publisher.PublicationError, "immutable release"):
                publisher.publish_release(self.build_root, docs_root)


if __name__ == "__main__":
    unittest.main()
