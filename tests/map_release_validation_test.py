import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import validate_manifest  # noqa: E402
import validate_release  # noqa: E402


TIMESTAMP = "2026-07-19T00:00:00Z"
QA_SCHEMA = REPO_ROOT / "world" / "map-production" / "schemas" / "qa-report.schema.json"
MANIFEST_SCHEMA = (
    REPO_ROOT / "world" / "map-production" / "schemas" / "production-manifest.schema.json"
)


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def qa_report(job_id, image_path, image_sha256, reviewer, created_at):
    maxima = (25, 15, 15, 15, 10, 10, 10)
    return {
        "schema_version": "1.0.0",
        "job_id": job_id,
        "image_path": image_path,
        "image_sha256": image_sha256,
        "created_at": created_at,
        "reviewer": reviewer,
        "status": "complete",
        "golden_reference": True,
        "review_mode": "blind-independent",
        "acceptance_threshold": 94,
        "review_views": [
            {
                "id": f"view-{index}",
                "label": f"View {index}",
                "complete": True,
                "evidence": f"Evidence {index}",
                "notes": "Checked.",
            }
            for index in range(10)
        ],
        "immediate_failures": [
            {
                "id": f"failure-{index}",
                "label": f"Failure {index}",
                "detected": False,
                "evidence": "Not detected.",
            }
            for index in range(8)
        ],
        "scores": [
            {
                "id": f"score-{index}",
                "label": f"Score {index}",
                "maximum": maximum,
                "score": maximum,
                "notes": "Pass.",
            }
            for index, maximum in enumerate(maxima)
        ],
        "total_score": 100,
        "decision": "accepted",
        "summary": "Accepted after complete independent inspection.",
        "required_changes": [],
    }


class ReleaseFixture:
    def __init__(self, root: Path):
        self.root = root
        self.qa_dir = root / "world" / "map-production" / "qa"
        self.master_path = root / "world" / "map-production" / "masters" / "golden.png"
        self.raw_path = root / "world" / "map-production" / "masters" / "golden-raw.png"
        self.prompt_path = root / "world" / "map-production" / "prompts" / "golden.md"
        self.tiles_path = root / "docs" / "assets" / "tiles" / "golden"
        self.metadata_path = self.tiles_path / "metadata.json"
        self.manifest_path = root / "world" / "map-production" / "production-manifest.json"
        self.map_sheets_path = root / "world" / "map-production" / "source" / "map-sheets.json"
        self.resolution_contract_path = (
            root / "world" / "map-production" / "spec" / "resolution-contract.json"
        )

        self.master_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (512, 512), (30, 80, 140)).save(self.master_path)
        self.raw_path.write_bytes(self.master_path.read_bytes())
        self.prompt_path.parent.mkdir(parents=True, exist_ok=True)
        self.prompt_path.write_text("locked golden prompt\n", encoding="utf-8")

        tile_path = self.tiles_path / "0" / "0" / "0.webp"
        tile_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (512, 512), (30, 80, 140, 255)).save(
            tile_path, format="WEBP", lossless=True, method=6, exact=True
        )
        tile_digest = validate_release.sha256_file(tile_path)
        tile_set_digest = validate_release._tile_set_digest(
            [("0/0/0.webp", tile_digest)]
        )
        master_relative = "world/map-production/masters/golden.png"
        raw_relative = "world/map-production/masters/golden-raw.png"
        master_hash = validate_release.sha256_file(self.master_path)
        prompt_hash = validate_release.sha256_file(self.prompt_path)
        tile_bytes = tile_path.stat().st_size

        self.metadata = {
            "schema_version": "1.0.0",
            "type": "sstory-xyz-raster",
            "generated_by": "unit-test",
            "generated_at": TIMESTAMP,
            "map_id": "golden-world",
            "scheme": "xyz",
            "coordinate_scope": "sheet-local",
            "tile_origin": "top-left",
            "x_axis": "right",
            "y_axis": "down",
            "edge_padding": "transparent",
            "format": "webp",
            "tile_size": 512,
            "minzoom": 0,
            "maxzoom": 0,
            "native_zoom": 0,
            "tiles": ["{z}/{x}/{y}.webp"],
            "coordinate_reference_system": "EA-WORLD-1",
            "coordinate_system": "EA-WORLD-1",
            "bounds": [0, 0, 10000, 10000],
            "master": {
                "path": master_relative,
                "sha256": master_hash,
                "width": 512,
                "height": 512,
                "mode": "RGBA",
            },
            "encoding": {"quality": 88, "lossless": False, "background": "#00000000"},
            "levels": [
                {
                    "zoom": 0,
                    "width": 512,
                    "height": 512,
                    "columns": 1,
                    "rows": 1,
                    "tile_count": 1,
                    "bytes": tile_bytes,
                }
            ],
            "tile_count": 1,
            "total_bytes": tile_bytes,
            "tile_set_sha256": tile_set_digest,
        }
        write_json(self.metadata_path, self.metadata)

        job_id = "golden-world-v1"
        review_a = qa_report(
            job_id, master_relative, master_hash, "Reviewer Alpha", TIMESTAMP
        )
        review_b = qa_report(
            job_id,
            master_relative,
            master_hash,
            "Reviewer Beta",
            "2026-07-19T00:01:00Z",
        )
        self.review_a_path = self.qa_dir / "golden-world-v1-review-a.json"
        self.review_b_path = self.qa_dir / "golden-world-v1-review-b.json"
        write_json(self.review_a_path, review_a)
        write_json(self.review_b_path, review_b)
        self.automated_path = self.qa_dir / "automated" / "golden-world-v1.json"
        write_json(
            self.automated_path,
            {
                "schema_version": "1.0.0",
                "type": "unit-test-automated-qa",
                "job_id": job_id,
                "image_path": master_relative,
                "status": "passed",
            },
        )

        self.manifest = {
            "schema_version": "1.0.0",
            "project_id": "release-validator-test",
            "map_id": "eternal-arcadia",
            "coordinate_system": "EA-WORLD-1",
            "jobs": [
                {
                    "id": job_id,
                    "sheet_id": "sheet_world",
                    "status": "tiled",
                    "bounds": {"west": 0, "south": 0, "east": 10000, "north": 10000},
                    "zoom": {"min": 0, "max": 0, "native": 0},
                    "acceptance_threshold": 94,
                    "inputs": [
                        {
                            "path": raw_relative,
                            "sha256": master_hash,
                            "role": "golden-raw-output",
                        },
                        {
                            "path": "world/map-production/qa/golden-world-v1-review-a.json",
                            "sha256": validate_release.sha256_file(self.review_a_path),
                            "role": "independent-vision-review-a",
                        },
                        {
                            "path": "world/map-production/qa/golden-world-v1-review-b.json",
                            "sha256": validate_release.sha256_file(self.review_b_path),
                            "role": "independent-vision-review-b",
                        },
                        {
                            "path": "world/map-production/prompts/golden.md",
                            "sha256": prompt_hash,
                            "role": "locked-prompt",
                        }
                    ],
                    "generation": {
                        "model": "unit-test",
                        "prompt_path": "world/map-production/prompts/golden.md",
                        "prompt_sha256": prompt_hash,
                        "attempt": 1,
                    },
                    "master": {
                        "path": master_relative,
                        "sha256": master_hash,
                        "width": 512,
                        "height": 512,
                        "color_profile": "sRGB",
                    },
                    "qa": {
                        "automated": {
                            "status": "passed",
                            "report_path": "world/map-production/qa/automated/golden-world-v1.json",
                        },
                        "vision": {
                            "decision": "accepted",
                            "score": 100,
                            "report_path": "world/map-production/qa/golden-world-v1-review-a.json",
                            "reviewer": "Reviewer Alpha",
                            "reviewed_at": TIMESTAMP,
                        },
                    },
                    "output": {
                        "tiles_path": "docs/assets/tiles/golden",
                        "metadata_path": "docs/assets/tiles/golden/metadata.json",
                        "tile_set_sha256": tile_set_digest,
                    },
                    "history": [
                        {"state": "planned", "at": TIMESTAMP, "actor": "test"},
                        {"state": "inputs-ready", "at": TIMESTAMP, "actor": "test"},
                        {"state": "generated", "at": TIMESTAMP, "actor": "test"},
                        {"state": "automated-qa", "at": TIMESTAMP, "actor": "test"},
                        {"state": "vision-qa", "at": TIMESTAMP, "actor": "test"},
                        {"state": "accepted", "at": TIMESTAMP, "actor": "test"},
                        {"state": "tiled", "at": TIMESTAMP, "actor": "test"},
                    ],
                }
            ],
        }
        write_json(self.manifest_path, self.manifest)
        self.map_sheets = {
            "schema_version": "0.1.0",
            "coordinate_reference_system": "EA-WORLD-1",
            "tile_profile": {
                "tile_size_px": 512,
                "metatile_size_px": 1024,
                "metatile_gutter_each_side_px": 256,
                "public_format": "webp",
                "master_format": "png",
                "labels_baked_into_raster": False,
            },
            "sheets": [
                {
                    "id": "sheet_world",
                    "sheet_type": "world",
                    "bounds": [0, 0, 10000, 10000],
                    "zoom_range": [0, 0],
                    "native_zoom": 0,
                    "review_status": "provisional",
                    "geometry_confidence": "estimated",
                }
            ],
        }
        write_json(self.map_sheets_path, self.map_sheets)
        self.resolution_contract = {
            "schema_version": "1.0.0",
            "type": "sstory-finite-deep-zoom-resolution-contract",
            "coordinate_reference_system": "EA-WORLD-1",
            "world_extent": {
                "min_x": 0,
                "min_y": 0,
                "max_x": 10000,
                "max_y": 10000,
            },
            "world_raster": {"width_px": 512, "height_px": 512, "native_zoom": 0},
            "sheet_type_order": [
                "world",
                "continent",
                "region",
                "corridor",
                "settlement",
            ],
            "lod_by_sheet_type": {
                "world": {
                    "zoom_range": [0, 0],
                    "native_zoom": 0,
                    "production_method": "deterministic-composite",
                },
                "continent": {
                    "zoom_range": [0, 1],
                    "native_zoom": 1,
                    "production_method": "deterministic-composite",
                },
                "region": {
                    "zoom_range": [1, 2],
                    "native_zoom": 2,
                    "production_method": "imagegen-metatile",
                },
                "corridor": {
                    "zoom_range": [2, 3],
                    "native_zoom": 3,
                    "production_method": "imagegen-metatile",
                },
                "settlement": {
                    "zoom_range": [3, 4],
                    "native_zoom": 4,
                    "production_method": "imagegen-metatile",
                },
            },
            "pixel_bounds_formula": {
                "coordinate_order": ["min_x", "min_y", "max_x", "max_y"],
                "scale_base": 2,
                "scale_exponent": "sheet_native_zoom-minus-world_native_zoom",
                "minimum_rounding": "floor",
                "maximum_rounding": "ceil",
                "x_base_pixels": "world_raster.width_px",
                "y_base_pixels": "world_raster.height_px",
                "x_denominator": "world_extent.max_x-minus-min_x",
                "y_denominator": "world_extent.max_y-minus-min_y",
            },
            "tile_profile": {
                "scheme": "xyz",
                "coordinate_scope": "sheet-local",
                "tile_origin": "top-left",
                "y_axis": "down",
                "tile_size_px": 512,
                "public_format": "webp",
            },
            "metatile_profile": {
                "metatile_size_px": 1024,
                "gutter_each_side_px": 256,
                "stride_px": 512,
                "applicable_sheet_types": ["region", "corridor", "settlement"],
            },
            "unbounded_sheet_policy": {
                "action": "skip",
                "allowed_sheet_types": ["district", "block"],
                "required_review_status": "planned",
                "required_geometry_confidence": "unresolved",
            },
            "overzoom_policy": {
                "allowed": False,
                "maximum_source_scale": 1,
                "behavior_outside_deeper_sheet": (
                    "clamp-to-deepest-intersecting-native-zoom"
                ),
                "parent_visibility_until_child_ready": True,
            },
            "expected_summary": {
                "bounded_sheet_count": 1,
                "unbounded_skipped_count": 0,
                "total_master_pixels": 262144,
                "generation_master_pixels": 0,
                "generation_metatile_count": 0,
            },
        }
        write_json(self.resolution_contract_path, self.resolution_contract)

    def validate(self, **overrides):
        options = {
            "manifest_schema_path": MANIFEST_SCHEMA,
            "qa_schema_path": QA_SCHEMA,
            "qa_dir": self.qa_dir,
            "map_sheets_path": self.map_sheets_path,
            "resolution_contract_path": self.resolution_contract_path,
            "repo_root": self.root,
        }
        options.update(overrides)
        return validate_release.validate_release(self.manifest_path, **options)

    def persist(self):
        write_json(self.metadata_path, self.metadata)
        write_json(self.manifest_path, self.manifest)

    def rewrite_master(self, width, height):
        Image.new("RGB", (width, height), (30, 80, 140)).save(self.master_path)
        master_hash = validate_release.sha256_file(self.master_path)
        manifest_master = self.manifest["jobs"][0]["master"]
        manifest_master.update(
            {"sha256": master_hash, "width": width, "height": height}
        )
        self.metadata["master"].update(
            {"sha256": master_hash, "width": width, "height": height}
        )
        self.persist()

    def rewrite_tile(self, *, zoom=0, tile_size=512, tile_format="webp"):
        for path in self.tiles_path.rglob("*"):
            if path.is_file() and path != self.metadata_path:
                path.unlink()
        tile_path = self.tiles_path / str(zoom) / "0" / f"0.{tile_format}"
        tile_path.parent.mkdir(parents=True, exist_ok=True)
        save_options = (
            {"lossless": True, "method": 6, "exact": True}
            if tile_format == "webp"
            else {}
        )
        Image.new("RGBA", (tile_size, tile_size), (30, 80, 140, 255)).save(
            tile_path,
            format=tile_format.upper(),
            **save_options,
        )
        tile_digest = validate_release.sha256_file(tile_path)
        tile_set_digest = validate_release._tile_set_digest(
            [(f"{zoom}/0/0.{tile_format}", tile_digest)]
        )
        tile_bytes = tile_path.stat().st_size
        self.metadata.update(
            {
                "format": tile_format,
                "tile_size": tile_size,
                "minzoom": zoom,
                "maxzoom": zoom,
                "native_zoom": zoom,
                "tiles": [f"{{z}}/{{x}}/{{y}}.{tile_format}"],
                "tile_count": 1,
                "total_bytes": tile_bytes,
                "tile_set_sha256": tile_set_digest,
            }
        )
        self.metadata["levels"] = [
            {
                "zoom": zoom,
                "width": tile_size,
                "height": tile_size,
                "columns": 1,
                "rows": 1,
                "tile_count": 1,
                "bytes": tile_bytes,
            }
        ]
        self.manifest["jobs"][0]["output"]["tile_set_sha256"] = tile_set_digest
        self.persist()

    def rewrite_sheet_local_grid(self, width, height, *, opaque_padding=False):
        Image.new("RGB", (width, height), (30, 80, 140)).save(self.master_path)
        self.raw_path.write_bytes(self.master_path.read_bytes())
        master_hash = validate_release.sha256_file(self.master_path)
        for path in self.tiles_path.rglob("*"):
            if path.is_file() and path != self.metadata_path:
                path.unlink()

        columns = (width + 511) // 512
        rows = (height + 511) // 512
        tile_digests = []
        total_bytes = 0
        for column in range(columns):
            for row in range(rows):
                content_width = min(512, width - column * 512)
                content_height = min(512, height - row * 512)
                fill = (30, 80, 140, 255) if opaque_padding else (0, 0, 0, 0)
                image = Image.new("RGBA", (512, 512), fill)
                if not opaque_padding:
                    image.paste(
                        (30, 80, 140, 255),
                        (0, 0, content_width, content_height),
                    )
                tile_path = self.tiles_path / "0" / str(column) / f"{row}.webp"
                tile_path.parent.mkdir(parents=True, exist_ok=True)
                image.save(tile_path, format="WEBP", lossless=True, method=6, exact=True)
                relative = f"0/{column}/{row}.webp"
                tile_digests.append((relative, validate_release.sha256_file(tile_path)))
                total_bytes += tile_path.stat().st_size

        tile_set_digest = validate_release._tile_set_digest(tile_digests)
        self.metadata["master"].update(
            {"sha256": master_hash, "width": width, "height": height}
        )
        self.metadata["levels"] = [
            {
                "zoom": 0,
                "width": width,
                "height": height,
                "columns": columns,
                "rows": rows,
                "tile_count": columns * rows,
                "bytes": total_bytes,
            }
        ]
        self.metadata.update(
            {
                "tile_count": columns * rows,
                "total_bytes": total_bytes,
                "tile_set_sha256": tile_set_digest,
            }
        )
        self.manifest["jobs"][0]["master"].update(
            {"sha256": master_hash, "width": width, "height": height}
        )
        raw_input = next(
            item
            for item in self.manifest["jobs"][0]["inputs"]
            if item["role"] == "golden-raw-output"
        )
        raw_input["sha256"] = master_hash
        for review_path in (self.review_a_path, self.review_b_path):
            report = json.loads(review_path.read_text(encoding="utf-8"))
            report["image_sha256"] = master_hash
            write_json(review_path, report)
            review_relative = review_path.relative_to(self.root).as_posix()
            review_input = next(
                item
                for item in self.manifest["jobs"][0]["inputs"]
                if item.get("path") == review_relative
            )
            review_input["sha256"] = validate_release.sha256_file(review_path)
        self.manifest["jobs"][0]["output"]["tile_set_sha256"] = tile_set_digest
        self.resolution_contract["world_raster"].update(
            {"width_px": width, "height_px": height}
        )
        self.resolution_contract["expected_summary"]["total_master_pixels"] = width * height
        self.persist()
        write_json(self.resolution_contract_path, self.resolution_contract)


class MapReleaseValidationTests(unittest.TestCase):
    def make_fixture(self, temp_dir):
        return ReleaseFixture(Path(temp_dir))

    def test_complete_strict_release_recomputes_all_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            result = fixture.validate(
                strict_release=True,
            )

        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["golden_job_id"], "golden-world-v1")
        self.assertEqual(result["independent_reviews"], 2)
        self.assertEqual(result["tiles_checked"], 1)
        self.assertGreater(result["tile_bytes_checked"], 0)
        self.assertEqual((result["covered_sheets"], result["required_sheets"]), (1, 1))

    def test_direct17_release_gate_requires_exact_hashed_blind_non_golden_reviews(self):
        def configure(fixture, mutation=None):
            job = fixture.manifest["jobs"][0]
            job["sheet_id"] = "sheet_region_royal_capital_region"
            reports = {
                "a": json.loads(fixture.review_a_path.read_text(encoding="utf-8")),
                "b": json.loads(fixture.review_b_path.read_text(encoding="utf-8")),
            }
            for report in reports.values():
                report["golden_reference"] = False
            if mutation is not None:
                mutation(job, reports)
            write_json(fixture.review_a_path, reports["a"])
            write_json(fixture.review_b_path, reports["b"])
            for item in job["inputs"]:
                if item.get("role") == "independent-vision-review-a":
                    item["sha256"] = validate_release.sha256_file(fixture.review_a_path)
                elif item.get("role") == "independent-vision-review-b":
                    item["sha256"] = validate_release.sha256_file(fixture.review_b_path)
            fixture.persist()

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            configure(fixture)
            valid = fixture.validate()
        self.assertTrue(valid["valid"], valid["errors"])

        cases = {
            "missing-sha": (
                lambda _job, reports: reports["b"].pop("image_sha256"),
                "image_sha256",
            ),
            "wrong-mode": (
                lambda _job, reports: reports["b"].__setitem__("review_mode", "self"),
                "review_mode",
            ),
            "golden-true": (
                lambda _job, reports: reports["b"].__setitem__("golden_reference", True),
                "golden_reference",
            ),
            "missing-input": (
                lambda job, _reports: job.__setitem__(
                    "inputs",
                    [
                        item
                        for item in job["inputs"]
                        if item.get("role") != "independent-vision-review-b"
                    ],
                ),
                "must hash exactly",
            ),
            "unicode-reviewer-alias": (
                lambda _job, reports: reports["b"].__setitem__(
                    "reviewer", "Ｒｅｖｉｅｗｅｒ\u3000Ａｌｐｈａ"
                ),
                "duplicates a reviewer identity",
            ),
        }
        for name, (mutation, expected) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.make_fixture(temp_dir)
                configure(fixture, mutation)
                result = fixture.validate()
                self.assertFalse(result["valid"])
                self.assertTrue(
                    any(expected in error for error in result["errors"]),
                    result["errors"],
                )

    def test_cli_strict_release_is_the_explicit_publication_gate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                exit_code = validate_release.main(
                    [
                        str(fixture.manifest_path),
                        "--manifest-schema",
                        str(MANIFEST_SCHEMA),
                        "--qa-schema",
                        str(QA_SCHEMA),
                        "--qa-dir",
                        str(fixture.qa_dir),
                        "--map-sheets",
                        str(fixture.map_sheets_path),
                        "--resolution-contract",
                        str(fixture.resolution_contract_path),
                        "--repo-root",
                        str(fixture.root),
                        "--strict-release",
                    ]
                )

        self.assertEqual(exit_code, 0, output.getvalue())
        self.assertIn("independent reviews=2", output.getvalue())
        self.assertIn("Sheet coverage=1/1", output.getvalue())

    def test_planned_manifest_stays_valid_normally_but_fails_release_gates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            job = fixture.manifest["jobs"][0]
            for field in ("inputs", "generation", "master", "qa", "output"):
                job.pop(field)
            job["status"] = "planned"
            job["history"] = [{"state": "planned", "at": TIMESTAMP, "actor": "test"}]
            write_json(fixture.manifest_path, fixture.manifest)

            _, normal_errors = validate_manifest.validate_manifest(
                fixture.manifest_path, MANIFEST_SCHEMA, check_files=False
            )
            integrity_only = fixture.validate()
            strict = fixture.validate(
                strict_release=True,
            )

        self.assertEqual(normal_errors, [])
        self.assertTrue(integrity_only["valid"], integrity_only["errors"])
        self.assertFalse(strict["valid"])
        self.assertTrue(any("golden-reference" in error for error in strict["errors"]))
        self.assertTrue(any("required sheet" in error for error in strict["errors"]))

    def test_qa_schema_and_manifest_report_values_are_enforced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            report = json.loads(fixture.review_a_path.read_text(encoding="utf-8"))
            report.pop("reviewer")
            report["decision"] = "revise"
            report["total_score"] = 99
            write_json(fixture.review_a_path, report)

            result = fixture.validate()

        self.assertFalse(result["valid"])
        self.assertTrue(any("schema violation" in error and "reviewer" in error for error in result["errors"]))
        self.assertTrue(any("qa.vision.decision mismatch" in error for error in result["errors"]))
        self.assertTrue(any("qa.vision.score mismatch" in error for error in result["errors"]))
        self.assertTrue(any("total_score" in error and "score sum" in error for error in result["errors"]))

    def test_auxiliary_root_vision_records_are_not_routed_to_qa_report_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            records = {
                "source-authority-root-vision.json": {
                    "schema_version": "1.0.0",
                    "status": "accepted-as-source-authority",
                    "reviewer": "Root Vision",
                    "source": {"path": "source.png", "sha256": "0" * 64},
                    "decision": {"vision_score": 94},
                },
                "derived-source-root-vision.json": {
                    "schema_version": "1.0.0",
                    "candidate": "derived-source-v1",
                    "image_path": "source.png",
                    "image_sha256": "0" * 64,
                    "reviewer": "Root Vision",
                    "decision": "approved-only-as-derived-source",
                    "total_score": 95,
                    "immediate_failures": [],
                },
            }
            for name, record in records.items():
                write_json(fixture.qa_dir / name, record)

            result = fixture.validate()

        self.assertTrue(result["valid"], result["errors"])

    def test_manifest_bound_vision_record_is_always_schema_validated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            auxiliary = fixture.qa_dir / "source-authority-root-vision.json"
            write_json(
                auxiliary,
                {
                    "schema_version": "1.0.0",
                    "reviewer": "Root Vision",
                    "decision": "approved-only-as-source-authority",
                },
            )
            fixture.manifest["jobs"][0]["qa"]["vision"]["report_path"] = (
                "world/map-production/qa/source-authority-root-vision.json"
            )
            fixture.persist()

            result = fixture.validate()

        self.assertFalse(result["valid"])
        self.assertTrue(
            any("schema violation" in error and "job_id" in error for error in result["errors"]),
            result["errors"],
        )

    def test_unbound_malformed_job_review_still_uses_qa_report_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            malformed = qa_report(
                "orphan-review",
                "world/map-production/masters/golden.png",
                fixture.manifest["jobs"][0]["master"]["sha256"],
                "Reviewer Gamma",
                "2026-07-19T00:02:00Z",
            )
            malformed.pop("job_id")
            write_json(fixture.qa_dir / "orphan-malformed.json", malformed)

            result = fixture.validate()

        self.assertFalse(result["valid"])
        self.assertTrue(
            any("schema violation" in error and "job_id" in error for error in result["errors"]),
            result["errors"],
        )

    def test_master_and_input_hashes_and_dimensions_are_recalculated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            Image.new("RGB", (64, 96), (180, 20, 20)).save(fixture.master_path)
            fixture.prompt_path.write_text("tampered prompt\n", encoding="utf-8")

            result = fixture.validate()

        self.assertFalse(result["valid"])
        self.assertTrue(any("inputs[3].sha256 mismatch" in error for error in result["errors"]))
        self.assertTrue(any("master.sha256 mismatch" in error for error in result["errors"]))
        self.assertTrue(any("master dimensions mismatch" in error for error in result["errors"]))

    def test_tile_presence_bytes_dimensions_and_hash_are_recalculated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            tile_path = fixture.tiles_path / "0" / "0" / "0.webp"
            Image.new("RGB", (64, 64), (250, 250, 10)).save(tile_path, format="WEBP")

            result = fixture.validate()

        self.assertFalse(result["valid"])
        self.assertTrue(any("total_bytes mismatch" in error for error in result["errors"]))
        self.assertTrue(any("tile dimensions mismatch" in error for error in result["errors"]))
        self.assertTrue(any("tile_set_sha256 mismatch" in error for error in result["errors"]))

    def test_missing_tile_and_missing_sheet_are_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            (fixture.tiles_path / "0" / "0" / "0.webp").unlink()
            fixture.map_sheets["sheets"].append(
                {
                    "id": "sheet_region_missing",
                    "sheet_type": "region",
                    "bounds": [100, 100, 200, 200],
                    "review_status": "provisional",
                }
            )
            write_json(fixture.map_sheets_path, fixture.map_sheets)

            result = fixture.validate(require_sheet_coverage=True)

        self.assertFalse(result["valid"])
        self.assertTrue(any("missing tile" in error for error in result["errors"]))
        self.assertTrue(any("sheet_region_missing" in error for error in result["errors"]))

    def test_golden_gate_requires_two_distinct_accepted_reviewers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            fixture.review_b_path.unlink()

            result = fixture.validate(
                require_golden_accepted=True,
                minimum_independent_reviews=2,
            )

        self.assertFalse(result["valid"])
        self.assertEqual(result["independent_reviews"], 1)
        self.assertTrue(any("2 required" in error for error in result["errors"]))

    def test_golden_gate_rejects_review_bound_to_stale_image_sha(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            review = json.loads(fixture.review_b_path.read_text(encoding="utf-8"))
            review["image_sha256"] = "0" * 64
            write_json(fixture.review_b_path, review)

            result = fixture.validate(
                require_golden_accepted=True,
                minimum_independent_reviews=2,
            )

        self.assertFalse(result["valid"])
        self.assertEqual(result["independent_reviews"], 1)

    def test_golden_gate_rejects_nonblind_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            review = json.loads(fixture.review_b_path.read_text(encoding="utf-8"))
            review["review_mode"] = "self"
            write_json(fixture.review_b_path, review)

            result = fixture.validate(
                require_golden_accepted=True,
                minimum_independent_reviews=2,
            )

        self.assertFalse(result["valid"])
        self.assertEqual(result["independent_reviews"], 1)
        self.assertTrue(any("review_mode" in error for error in result["errors"]))

    def test_golden_gate_requires_distinct_byte_identical_raw_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            fixture.manifest["jobs"][0]["inputs"] = [
                item
                for item in fixture.manifest["jobs"][0]["inputs"]
                if item["role"] != "golden-raw-output"
            ]
            fixture.persist()

            result = fixture.validate(require_golden_accepted=True)

        self.assertFalse(result["valid"])
        self.assertTrue(any("golden-raw-output" in error for error in result["errors"]))

    def test_automated_subdirectory_report_never_counts_as_vision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            fixture.review_b_path.unlink()
            write_json(
                fixture.automated_path,
                qa_report(
                    "golden-world-v1",
                    "world/map-production/masters/golden.png",
                    fixture.manifest["jobs"][0]["master"]["sha256"],
                    "Reviewer Beta",
                    "2026-07-19T00:01:00Z",
                ),
            )

            result = fixture.validate(
                require_golden_accepted=True,
                minimum_independent_reviews=2,
            )

        self.assertFalse(result["valid"])
        self.assertEqual(result["independent_reviews"], 1)

    def test_manifest_automated_reference_never_counts_even_if_vision_shaped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            fixture.review_b_path.unlink()
            root_automated = fixture.qa_dir / "vision-shaped-automated.json"
            write_json(
                root_automated,
                qa_report(
                    "golden-world-v1",
                    "world/map-production/masters/golden.png",
                    fixture.manifest["jobs"][0]["master"]["sha256"],
                    "Reviewer Beta",
                    "2026-07-19T00:01:00Z",
                ),
            )
            fixture.manifest["jobs"][0]["qa"]["automated"]["report_path"] = (
                "world/map-production/qa/vision-shaped-automated.json"
            )
            fixture.persist()

            result = fixture.validate(
                require_golden_accepted=True,
                minimum_independent_reviews=2,
            )

        self.assertFalse(result["valid"])
        self.assertEqual(result["independent_reviews"], 1)

    def test_nested_vision_report_is_discovered_recursively(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            nested = fixture.qa_dir / "independent" / "reviewer-beta.json"
            nested.parent.mkdir(parents=True, exist_ok=True)
            fixture.review_b_path.replace(nested)
            review_input = next(
                item
                for item in fixture.manifest["jobs"][0]["inputs"]
                if item["role"] == "independent-vision-review-b"
            )
            review_input["path"] = "world/map-production/qa/independent/reviewer-beta.json"
            fixture.persist()

            result = fixture.validate(
                require_golden_accepted=True,
                minimum_independent_reviews=2,
            )

        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["independent_reviews"], 2)

    def test_unbound_matching_review_never_counts_for_golden_gate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            fixture.manifest["jobs"][0]["inputs"] = [
                item
                for item in fixture.manifest["jobs"][0]["inputs"]
                if item["role"] != "independent-vision-review-b"
            ]
            fixture.persist()

            result = fixture.validate(
                require_golden_accepted=True,
                minimum_independent_reviews=2,
            )

        self.assertFalse(result["valid"])
        self.assertEqual(result["independent_reviews"], 1)
        self.assertTrue(any("manifest-bound" in error for error in result["errors"]))

    def test_golden_gate_rejects_extra_role_and_unhashed_primary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            fixture.manifest["jobs"][0]["inputs"].append(
                {
                    "path": "world/map-production/qa/golden-world-v1-review-b.json",
                    "sha256": validate_release.sha256_file(fixture.review_b_path),
                    "role": "independent-vision-review-c",
                }
            )
            fixture.persist()
            extra = fixture.validate(
                require_golden_accepted=True,
                minimum_independent_reviews=2,
            )
        self.assertFalse(extra["valid"])
        self.assertTrue(
            any("unexpected Vision review role" in error for error in extra["errors"])
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            job = fixture.manifest["jobs"][0]
            third = fixture.qa_dir / "golden-world-v1-review-c.json"
            write_json(
                third,
                qa_report(
                    job["id"],
                    job["master"]["path"],
                    job["master"]["sha256"],
                    "Reviewer Gamma",
                    "2026-07-19T00:02:00Z",
                ),
            )
            job["qa"]["vision"].update(
                {
                    "report_path": "world/map-production/qa/golden-world-v1-review-c.json",
                    "reviewer": "Reviewer Gamma",
                }
            )
            fixture.persist()
            unhashed = fixture.validate(
                require_golden_accepted=True,
                minimum_independent_reviews=2,
            )
        self.assertFalse(unhashed["valid"])
        self.assertTrue(
            any(
                "primary qa.vision report must be one of its two manifest-hashed reviews"
                in error
                for error in unhashed["errors"]
            ),
            unhashed["errors"],
        )

    def test_non_integer_sheet_dimensions_require_transparent_right_bottom_padding(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            fixture.rewrite_sheet_local_grid(700, 650)
            valid = fixture.validate()

            fixture.rewrite_sheet_local_grid(700, 650, opaque_padding=True)
            invalid = fixture.validate()

        self.assertTrue(valid["valid"], valid["errors"])
        self.assertFalse(invalid["valid"])
        self.assertTrue(any("right-edge padding" in error for error in invalid["errors"]))
        self.assertTrue(any("bottom-edge padding" in error for error in invalid["errors"]))

    def test_planned_or_unresolved_sheets_are_excluded_unless_requested(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            fixture.map_sheets["sheets"].append(
                {
                    "id": "sheet_block_unresolved",
                    "sheet_type": "block",
                    "bounds": None,
                    "review_status": "planned",
                }
            )
            write_json(fixture.map_sheets_path, fixture.map_sheets)

            normal = fixture.validate(require_sheet_coverage=True)
            include_planned = fixture.validate(
                require_sheet_coverage=True,
                include_planned_sheets=True,
            )

        self.assertTrue(normal["valid"], normal["errors"])
        self.assertFalse(include_planned["valid"])
        self.assertTrue(any("sheet_block_unresolved" in error for error in include_planned["errors"]))

    def test_strict_coverage_rejects_job_bounds_outside_the_sheet_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            fixture.manifest["jobs"][0]["bounds"]["east"] = 9000
            fixture.metadata["bounds"] = [0, 0, 9000, 10000]
            fixture.persist()

            non_strict = fixture.validate(require_sheet_coverage=True)
            strict = fixture.validate(strict_release=True)

        self.assertTrue(non_strict["valid"], non_strict["errors"])
        self.assertFalse(strict["valid"])
        self.assertEqual(strict["covered_sheets"], 0)
        self.assertTrue(
            any("resolution contract bounds mismatch" in error for error in strict["errors"])
        )

    def test_strict_coverage_rejects_job_zoom_outside_the_sheet_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            fixture.manifest["jobs"][0]["zoom"] = {"min": 1, "max": 1, "native": 1}
            fixture.rewrite_tile(zoom=1)

            strict = fixture.validate(strict_release=True)

        self.assertFalse(strict["valid"])
        self.assertEqual(strict["covered_sheets"], 0)
        self.assertTrue(
            any("resolution contract zoom mismatch" in error for error in strict["errors"])
        )

    def test_strict_coverage_rejects_wrong_contract_master_dimensions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            fixture.rewrite_master(64, 96)

            strict = fixture.validate(strict_release=True)

        self.assertFalse(strict["valid"])
        self.assertEqual(strict["covered_sheets"], 0)
        self.assertTrue(
            any(
                "resolution contract master dimensions mismatch" in error
                for error in strict["errors"]
            )
        )

    def test_strict_coverage_rejects_wrong_contract_tile_size(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            fixture.rewrite_tile(tile_size=64)

            strict = fixture.validate(strict_release=True)

        self.assertFalse(strict["valid"])
        self.assertEqual(strict["covered_sheets"], 0)
        self.assertTrue(
            any(
                "resolution contract tiled metadata tile_size mismatch" in error
                for error in strict["errors"]
            )
        )

    def test_strict_coverage_rejects_wrong_contract_tile_format(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            fixture.rewrite_tile(tile_format="png")

            strict = fixture.validate(strict_release=True)

        self.assertFalse(strict["valid"])
        self.assertEqual(strict["covered_sheets"], 0)
        self.assertTrue(
            any(
                "resolution contract tiled metadata format mismatch" in error
                for error in strict["errors"]
            )
        )

    def test_historical_revise_and_rejected_jobs_are_not_contract_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            wrong_resolution = {
                "west": 10,
                "south": 10,
                "east": 20,
                "north": 20,
            }
            fixture.manifest["jobs"].extend(
                [
                    {
                        "id": "historical-style-revise",
                        "sheet_id": "style-candidate-old",
                        "status": "revise",
                        "bounds": wrong_resolution,
                        "zoom": {"min": 9, "max": 9, "native": 9},
                        "history": [
                            {"state": "planned", "at": TIMESTAMP, "actor": "test"},
                            {"state": "inputs-ready", "at": TIMESTAMP, "actor": "test"},
                            {"state": "generated", "at": TIMESTAMP, "actor": "test"},
                            {"state": "automated-qa", "at": TIMESTAMP, "actor": "test"},
                            {"state": "vision-qa", "at": TIMESTAMP, "actor": "test"},
                            {"state": "accepted", "at": TIMESTAMP, "actor": "test"},
                            {"state": "tiled", "at": TIMESTAMP, "actor": "test"},
                            {"state": "revise", "at": TIMESTAMP, "actor": "test"},
                        ],
                    },
                    {
                        "id": "historical-style-rejected",
                        "sheet_id": "style-candidate-retired",
                        "status": "rejected",
                        "bounds": wrong_resolution,
                        "zoom": {"min": 9, "max": 9, "native": 9},
                        "history": [
                            {"state": "planned", "at": TIMESTAMP, "actor": "test"},
                            {"state": "inputs-ready", "at": TIMESTAMP, "actor": "test"},
                            {"state": "generated", "at": TIMESTAMP, "actor": "test"},
                            {"state": "rejected", "at": TIMESTAMP, "actor": "test"},
                        ],
                    },
                ]
            )
            write_json(fixture.manifest_path, fixture.manifest)

            strict = fixture.validate(strict_release=True)

        self.assertTrue(strict["valid"], strict["errors"])
        self.assertEqual((strict["covered_sheets"], strict["required_sheets"]), (1, 1))

    def test_strict_contract_allows_an_accepted_job_before_tiling(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            job = fixture.manifest["jobs"][0]
            job["status"] = "accepted"
            job.pop("output")
            job["history"].pop()
            write_json(fixture.manifest_path, fixture.manifest)

            strict = fixture.validate(strict_release=True)

        self.assertTrue(strict["valid"], strict["errors"])
        self.assertEqual((strict["covered_sheets"], strict["required_sheets"]), (1, 1))

    def test_strict_contract_does_not_cover_a_tiled_job_without_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            fixture.manifest["jobs"][0].pop("output")
            write_json(fixture.manifest_path, fixture.manifest)

            strict = fixture.validate(strict_release=True)

        self.assertFalse(strict["valid"])
        self.assertEqual(strict["covered_sheets"], 0)
        self.assertTrue(
            any(
                "resolution contract tiled metadata could not be validated" in error
                for error in strict["errors"]
            )
        )

    def test_strict_contract_requires_the_catalog_resolution_migration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(temp_dir)
            fixture.map_sheets["sheets"][0]["zoom_range"] = [0, 1]
            fixture.map_sheets["sheets"][0]["native_zoom"] = 1
            write_json(fixture.map_sheets_path, fixture.map_sheets)

            non_strict = fixture.validate(require_sheet_coverage=True)
            strict = fixture.validate(strict_release=True)

        self.assertTrue(non_strict["valid"], non_strict["errors"])
        self.assertFalse(strict["valid"])
        self.assertTrue(
            any("catalog zoom mismatch" in error for error in strict["errors"])
        )


if __name__ == "__main__":
    unittest.main()
