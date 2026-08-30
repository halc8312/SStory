import json
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema

try:
    from PIL import Image
except ImportError:  # The tile CLI reports the installation command at runtime.
    Image = None


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import check_transition  # noqa: E402
import create_qa_report  # noqa: E402
import generate_tiles  # noqa: E402
import production_common  # noqa: E402
import validate_geojson  # noqa: E402
import validate_manifest  # noqa: E402


TIMESTAMP = "2026-07-18T00:00:00Z"


def planned_manifest():
    return {
        "schema_version": "1.0.0",
        "project_id": "sstory-map",
        "map_id": "eternia",
        "coordinate_system": "eternia-geographic",
        "jobs": [
            {
                "id": "golden-astralis",
                "sheet_id": "astralis",
                "status": "planned",
                "bounds": {"west": 19, "south": 44, "east": 21, "north": 46},
                "zoom": {"min": 6, "max": 12, "native": 12},
                "acceptance_threshold": 94,
                "history": [
                    {"state": "planned", "at": TIMESTAMP, "actor": "test"}
                ],
            }
        ],
    }


class ManifestValidationTests(unittest.TestCase):
    def test_json_loader_rejects_nonstandard_nan_constant(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "nan.json"
            path.write_text('{"value": NaN}\n', encoding="utf-8")

            with self.assertRaisesRegex(
                production_common.ValidationFailure, "non-standard numeric constant"
            ):
                production_common.load_json(path)

    def test_valid_planned_manifest_passes_schema_and_semantics(self):
        manifest = planned_manifest()
        schema = production_common.load_json(production_common.DEFAULT_MANIFEST_SCHEMA)

        self.assertEqual(validate_manifest.schema_errors(manifest, schema), [])
        self.assertEqual(production_common.validate_manifest_semantics(manifest), [])

    def test_manifest_accepts_canonical_ea_world_coordinate_system(self):
        manifest = planned_manifest()
        manifest["coordinate_system"] = "EA-WORLD-1"
        schema = production_common.load_json(production_common.DEFAULT_MANIFEST_SCHEMA)

        self.assertEqual(validate_manifest.schema_errors(manifest, schema), [])

    def test_manifest_paths_are_portable_repository_relative_paths(self):
        schema = production_common.load_json(production_common.DEFAULT_MANIFEST_SCHEMA)
        manifest = planned_manifest()
        manifest["style_guide_path"] = "world/map-production/spec/style-bible.md"
        self.assertEqual(validate_manifest.schema_errors(manifest, schema), [])

        for invalid_path in (
            "../outside.md",
            "world/../outside.md",
            "C:/outside.md",
            "/outside.md",
            r"world\map-production\spec\style-bible.md",
        ):
            with self.subTest(path=invalid_path):
                manifest["style_guide_path"] = invalid_path
                self.assertTrue(validate_manifest.schema_errors(manifest, schema))

    def test_file_checks_resolve_paths_from_repository_root(self):
        manifest = planned_manifest()
        manifest["style_guide_path"] = "world/map-production/spec/style-bible.md"
        job = manifest["jobs"][0]
        job["status"] = "inputs-ready"
        job["inputs"] = [
            {"path": "world/map-production/README.md", "role": "production-overview"}
        ]
        job["history"].append(
            {"state": "inputs-ready", "at": TIMESTAMP, "actor": "test"}
        )

        errors = production_common.validate_manifest_semantics(
            manifest,
            manifest_path=Path("world/map-production/manifests/test.json"),
            check_files=True,
        )

        self.assertEqual(errors, [])

    def test_invalid_history_and_acceptance_gate_are_reported(self):
        manifest = planned_manifest()
        job = manifest["jobs"][0]
        job["status"] = "accepted"
        job["history"].append(
            {"state": "accepted", "at": TIMESTAMP, "actor": "test"}
        )

        errors = production_common.validate_manifest_semantics(manifest)

        self.assertTrue(any("illegal transition" in error for error in errors))
        self.assertTrue(any("master is required" in error for error in errors))
        self.assertTrue(any("qa.automated is required" in error for error in errors))
        self.assertTrue(any("qa.vision is required" in error for error in errors))

    def test_transition_command_is_dry_run_by_default_and_can_apply(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.json"
            production_common.dump_json(path, planned_manifest())

            self.assertEqual(
                check_transition.main([str(path), "golden-astralis", "inputs-ready"]),
                0,
            )
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["jobs"][0]["status"], "planned")

            self.assertEqual(
                check_transition.main(
                    [
                        str(path),
                        "golden-astralis",
                        "inputs-ready",
                        "--apply",
                        "--actor",
                        "unit-test",
                        "--at",
                        "2026-07-18T01:00:00Z",
                    ]
                ),
                0,
            )
            updated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(updated["jobs"][0]["status"], "inputs-ready")
            self.assertEqual(updated["jobs"][0]["history"][-1]["actor"], "unit-test")

    def test_transition_check_files_validates_newly_required_inputs(self):
        manifest = planned_manifest()
        manifest["jobs"][0]["inputs"] = [
            {"path": "world/map-production/does-not-exist.geojson"}
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.json"
            production_common.dump_json(path, manifest)

            result = check_transition.main(
                [
                    str(path),
                    "golden-astralis",
                    "inputs-ready",
                    "--check-files",
                ]
            )

        self.assertEqual(result, 1)


class GeoJsonValidationTests(unittest.TestCase):
    def test_ea_world_coordinate_reference_system_uses_world_extent(self):
        collection = {
            "type": "FeatureCollection",
            "coordinate_reference_system": "EA-WORLD-1",
            "features": [
                {
                    "type": "Feature",
                    "id": "world-anchor",
                    "properties": {"id": "world-anchor"},
                    "geometry": {"type": "Point", "coordinates": [5000, 7500]},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ea-world.geojson"
            production_common.dump_json(path, collection)
            summary, errors = validate_geojson.validate_files([path], [])

        self.assertEqual(errors, [])
        self.assertEqual(summary["geometries"], 1)

    def test_valid_geometry_and_canonical_reference_pass(self):
        collection = {
            "type": "FeatureCollection",
            "coordinate_system": "eternia-geographic",
            "features": [
                {
                    "type": "Feature",
                    "id": "elysion",
                    "properties": {"id": "elysion"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0, 30], [40, 30], [40, 55], [0, 55], [0, 30]]],
                    },
                },
                {
                    "type": "Feature",
                    "id": "capital-road",
                    "properties": {"id": "capital-road", "continent_id": "elysion"},
                    "geometry": {"type": "LineString", "coordinates": [[20, 45], [25, 50]]},
                },
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "valid.geojson"
            production_common.dump_json(path, collection)
            summary, errors = validate_geojson.validate_files([path], [])

        self.assertEqual(errors, [])
        self.assertEqual(summary["features"], 2)

    def test_open_ring_and_unknown_reference_fail(self):
        collection = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "broken-region",
                    "properties": {"id": "broken-region", "continent_id": "missing"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]],
                    },
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "invalid.geojson"
            production_common.dump_json(path, collection)
            _, errors = validate_geojson.validate_files([path], [])

        self.assertTrue(any("is not closed" in error for error in errors))
        self.assertTrue(any("unknown id 'missing'" in error for error in errors))

    def test_named_reference_catalog_collections_are_supported(self):
        collection = {
            "type": "FeatureCollection",
            "coordinate_reference_system": "EA-WORLD-1",
            "features": [
                {
                    "type": "Feature",
                    "id": "sky-port-footprint",
                    "properties": {
                        "id": "sky-port-footprint",
                        "node_id": "sky-port",
                        "vertical_layer_id": "upper-sky",
                    },
                    "geometry": {"type": "Point", "coordinates": [4000, 2000]},
                }
            ],
        }
        gazetteer = {"entries": [{"id": "sky-port"}]}
        layers = {"layers": [{"id": "upper-sky"}]}
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "source.geojson"
            gazetteer_path = root / "gazetteer.json"
            layers_path = root / "layers.json"
            production_common.dump_json(source_path, collection)
            production_common.dump_json(gazetteer_path, gazetteer)
            production_common.dump_json(layers_path, layers)
            _, errors = validate_geojson.validate_files(
                [source_path], [gazetteer_path, layers_path]
            )

        self.assertEqual(errors, [])


class TileGenerationTests(unittest.TestCase):
    def test_portable_source_path_hides_ignored_repo_scratch_roots(self):
        scratch_master = production_common.REPO_ROOT / "tmp-test-fixture" / "master.png"
        output_master = production_common.REPO_ROOT / "output" / "master.png"

        self.assertEqual(generate_tiles.portable_source_path(scratch_master), "master.png")
        self.assertEqual(generate_tiles.portable_source_path(output_master), "master.png")

    @unittest.skipIf(Image is None, "Pillow is not installed")
    def test_generates_padded_512_webp_xyz_pyramid_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            master = root / "master.png"
            output = root / "tiles"
            Image.new("RGB", (1025, 513), (24, 96, 160)).save(master)

            metadata = generate_tiles.generate_pyramid(
                master,
                output,
                map_id="test-map",
                min_zoom=0,
                max_zoom=2,
            )

            self.assertEqual(metadata["tile_size"], 512)
            self.assertEqual(metadata["tile_count"], 9)
            self.assertEqual(
                [(level["columns"], level["rows"]) for level in metadata["levels"]],
                [(1, 1), (2, 1), (3, 2)],
            )
            tile_paths = sorted(output.glob("*/*/*.webp"))
            self.assertEqual(len(tile_paths), 9)
            with Image.open(output / "2" / "2" / "1.webp") as edge_tile:
                self.assertEqual(edge_tile.size, (512, 512))
                self.assertEqual(edge_tile.format, "WEBP")
            saved_metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(saved_metadata["tile_set_sha256"], metadata["tile_set_sha256"])
            self.assertEqual(saved_metadata["master"]["path"], "master.png")
            self.assertFalse(Path(saved_metadata["master"]["path"]).is_absolute())

    @unittest.skipIf(Image is None, "Pillow is not installed")
    def test_bounds_default_to_canonical_ea_world_coordinate_system(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            master = root / "master.png"
            Image.new("RGB", (128, 128), (24, 96, 160)).save(master)

            metadata = generate_tiles.generate_pyramid(
                master,
                root / "tiles",
                map_id="test-map",
                min_zoom=0,
                max_zoom=0,
                tile_size=128,
                bounds=(0, 0, 10000, 10000),
            )

        self.assertEqual(metadata["coordinate_reference_system"], "EA-WORLD-1")
        self.assertEqual(metadata["coordinate_system"], "EA-WORLD-1")

    @unittest.skipIf(Image is None, "Pillow is not installed")
    def test_refuses_master_inside_owned_output_before_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "tiles"
            output.mkdir()
            production_common.dump_json(
                output / "metadata.json", {"generated_by": generate_tiles.GENERATOR_ID}
            )
            master = output / "master.png"
            Image.new("RGB", (128, 128), (24, 96, 160)).save(master)

            with self.assertRaisesRegex(ValueError, "must not be inside"):
                generate_tiles.generate_pyramid(
                    master,
                    output,
                    map_id="test-map",
                    min_zoom=0,
                    max_zoom=0,
                    tile_size=128,
                    overwrite=True,
                )

            self.assertTrue(master.is_file())
            self.assertTrue((output / "metadata.json").is_file())


class QaReportTests(unittest.TestCase):
    def test_template_matches_schema_and_scoring_contract(self):
        report = create_qa_report.build_report(
            "golden-astralis",
            "masters/golden-astralis.png",
            reviewer="Codex Vision QA",
            golden=True,
            image_sha256="a" * 64,
        )
        schema_path = REPO_ROOT / "world" / "map-production" / "schemas" / "qa-report.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        jsonschema.Draft7Validator(schema, format_checker=jsonschema.FormatChecker()).validate(report)
        self.assertEqual(sum(axis["maximum"] for axis in report["scores"]), 100)
        self.assertEqual(report["acceptance_threshold"], 94)
        self.assertEqual(report["image_sha256"], "a" * 64)
        self.assertEqual(report["review_mode"], "blind-independent")
        markdown = create_qa_report.markdown_report(report)
        self.assertTrue(markdown.startswith("---\n"))
        self.assertIn('type: "analysis"', markdown)
        self.assertIn('analysis_type: "feature-evaluation"', markdown)
        self.assertIn("四方向の隣接合成", markdown)
        self.assertIn("Immediate-failure gate", markdown)

    def test_complete_report_cannot_keep_draft_placeholders(self):
        report = create_qa_report.build_report(
            "golden-astralis",
            "world/map-production/masters/golden-astralis.png",
            reviewer="Codex Vision QA",
            golden=True,
            image_sha256="b" * 64,
        )
        report["status"] = "complete"
        schema_path = REPO_ROOT / "world" / "map-production" / "schemas" / "qa-report.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        errors = list(
            jsonschema.Draft7Validator(
                schema, format_checker=jsonschema.FormatChecker()
            ).iter_errors(report)
        )

        paths = [tuple(error.absolute_path) for error in errors]
        self.assertTrue(any(path and path[-1] == "complete" for path in paths))
        self.assertTrue(any(path and path[-1] == "detected" for path in paths))
        self.assertTrue(any(path and path[-1] == "score" for path in paths))


if __name__ == "__main__":
    unittest.main()
