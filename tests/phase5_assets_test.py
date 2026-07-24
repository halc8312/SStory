import copy
import hashlib
import io
import json
import math
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from PIL import Image, PngImagePlugin


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import build_phase5_assets as phase5  # noqa: E402
import audit_phase5_master as phase5_audit  # noqa: E402
import candidate_k3_golden_promotion_v2_test as golden_v2_fixture  # noqa: E402
import release_bound_artifact as bound_artifacts  # noqa: E402
import render_phase5_parent_control_masks as parent_control_renderer  # noqa: E402
import render_phase5_reviewed_master as reviewed_renderer  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path: Path) -> dict[str, str]:
    return {"path": phase5.repo_path(path), "sha256": digest(path)}


def bound_registry(*paths: Path) -> dict[str, bound_artifacts.BoundArtifact]:
    bindings = [
        bound_artifacts.bind_file(path, label=f"test source {path.name}")
        for path in paths
    ]
    return {binding.identity: binding for binding in bindings}


def complete_report(
    job_id: str,
    image_path: str,
    reviewer: str,
    threshold: int,
    *,
    golden: bool = False,
) -> dict:
    image_sha256 = digest(
        phase5.resolve_repo_artifact(image_path, "test reviewed image")
    )
    report = phase5.build_report(
        job_id,
        image_path,
        reviewer=reviewer,
        golden=golden,
        threshold=threshold,
        image_sha256=image_sha256,
        review_mode="blind-independent",
    )
    report["status"] = "complete"
    report["decision"] = "accepted"
    report["summary"] = "Synthetic accepted evidence for a unit test."
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


def write_golden_manifest(
    root: Path,
    *,
    master: Path,
    job_id: str = "golden-style-fixture-v1",
) -> tuple[Path, Path]:
    master_path = phase5.repo_path(master)
    report = complete_report(job_id, master_path, "Golden Reviewer", 94, golden=True)
    report_path = root / f"{job_id}-vision.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    second = complete_report(job_id, master_path, "Golden Reviewer B", 94, golden=True)
    second_path = root / f"{job_id}-vision-b.json"
    second_path.write_text(json.dumps(second), encoding="utf-8")
    raw_path = root / f"{job_id}-raw.png"
    shutil.copyfile(master, raw_path)
    with Image.open(master) as image:
        width, height = image.size
    manifest = {
        "jobs": [
            {
                "id": job_id,
                "status": "accepted",
                "acceptance_threshold": 94,
                "inputs": [
                    {**artifact(raw_path), "role": "golden-raw-output"},
                    {**artifact(report_path), "role": "independent-vision-review-a"},
                    {**artifact(second_path), "role": "independent-vision-review-b"},
                ],
                "master": {
                    **artifact(master),
                    "width": width,
                    "height": height,
                    "color_profile": "sRGB",
                },
                "qa": {
                    "vision": {
                        "decision": "accepted",
                        "score": 100,
                        "report_path": phase5.repo_path(report_path),
                        "reviewer": "Golden Reviewer",
                        "reviewed_at": "2026-07-19T00:00:00Z",
                    }
                },
            }
        ]
    }
    manifest_path = root / "production-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, report_path


def write_generation_receipt(
    root: Path,
    *,
    sheet_id: str,
    column: int,
    row: int,
    golden_style: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    tile = root / f"{sheet_id}-{column}-{row}-tile.png"
    Image.new("RGB", (2048, 2048), "green").save(tile)
    raw_tile = root / f"{sheet_id}-{column}-{row}-raw.png"
    Image.new("RGB", (2048, 2048), "blue").save(raw_tile)
    context = root / f"{sheet_id}-{column}-{row}-context.txt"
    context.write_text("locked synthetic context", encoding="utf-8")
    context_spec = artifact(context)
    golden_style_spec = golden_style or context_spec
    tile_spec = artifact(tile)
    raw_tile_spec = artifact(raw_tile)
    postprocess_report = {
        "$schema": "https://sstory.example/schemas/phase5-postprocess-report.schema.json",
        "schema_version": "1.0.0",
        "type": "sstory-phase5-deterministic-protected-composite-report",
        "coordinate_reference_system": "EA-WORLD-1",
        "generated_by": phase5.POSTPROCESS_GENERATOR_ID,
        "mode": "deterministic-protected-composite",
        "sheet_id": sheet_id,
        "column": column,
        "row": row,
        "raw_output": raw_tile_spec,
        "control": context_spec,
        "output": tile_spec,
        "protected_layers": ["land-sea", "transport", "detail"],
        "created_at": "2026-07-19T00:00:00Z",
    }
    postprocess_report_path = root / f"{sheet_id}-{column}-{row}-postprocess.json"
    postprocess_report_path.write_text(json.dumps(postprocess_report), encoding="utf-8")
    receipt = {
        "$schema": (
            "https://sstory.example/schemas/phase5-generation-receipt.schema.json"
        ),
        "schema_version": "1.1.0",
        "type": "sstory-phase5-metatile-generation-receipt",
        "coordinate_reference_system": "EA-WORLD-1",
        "sheet_id": sheet_id,
        "column": column,
        "row": row,
        "generation_order": "row-major",
        "attempt": 1,
        "single_change": {"confirmed": True, "instruction": "Synthetic fixture."},
        "tool": {
            "mode": "codex-built-in-imagegen",
            "image_model": "synthetic-test-model",
        },
        "requested_output": {
            "width": 2048,
            "height": 2048,
            "format": "PNG",
            "color_mode": "RGB",
        },
        "actual_output": {
            "width": 2048,
            "height": 2048,
            "format": "PNG",
            "color_mode": "RGB",
        },
        "raw_output": raw_tile_spec,
        "prompt": context_spec,
        "control": context_spec,
        "parent": context_spec,
        "neighbors": {"north": None, "east": None, "south": None, "west": None},
        "inputs": [
            {"role": "golden-style", **golden_style_spec},
            {"role": "geometry-control", **context_spec},
            {"role": "parent-context", **context_spec},
        ],
        "postprocess": {
            "mode": "deterministic-protected-composite",
            "control": context_spec,
            "report": artifact(postprocess_report_path),
        },
        "output": tile_spec,
        "created_at": "2026-07-19T00:00:00Z",
    }
    receipt_path = root / f"{sheet_id}-{column}-{row}-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return tile_spec, artifact(receipt_path)


def write_automated_report(
    root: Path,
    *,
    sheet_id: str,
    master: Path,
    provenance: dict[str, str],
    source_kind: str,
) -> dict[str, str]:
    with Image.open(master) as image:
        width, height = image.size
    land = root / f"{sheet_id}-land-mask.png"
    route = root / f"{sheet_id}-route-mask.png"
    Image.new("L", (width, height), 255).save(land)
    Image.new("L", (width, height), 255).save(route)
    master_spec = artifact(master)
    band_metrics = phase5.unpainted_band_metrics(master, f"{sheet_id} test master")
    report = {
        "$schema": "https://sstory.example/schemas/phase5-automated-qa.schema.json",
        "schema_version": "1.0.0",
        "type": "sstory-phase5-automated-master-qa",
        "coordinate_reference_system": "EA-WORLD-1",
        "generated_by": phase5.AUTOMATED_QA_GENERATOR_ID,
        "job_id": phase5.job_id_for_sheet(sheet_id),
        "sheet_id": sheet_id,
        "status": "passed",
        "source_kind": source_kind,
        "master": {
            **master_spec,
            "width": width,
            "height": height,
            "format": "PNG",
            "color_mode": "RGB",
        },
        "provenance_report": provenance,
        "checks": {
            "dimensions": {
                "passed": True,
                "expected_width": width,
                "expected_height": height,
                "actual_width": width,
                "actual_height": height,
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
                "expected_sha256": master_spec["sha256"],
                "actual_sha256": master_spec["sha256"],
            },
            "coverage": {
                "passed": True,
                "algorithm": "provenance-destination-coverage-v1",
                "expected_pixel_count": width * height,
                "covered_pixel_count": width * height,
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
                "minimum_overlap_ssim": 0.9,
                "maximum_rgb_mean_difference": 4,
                "maximum_rgb_p95_difference": 10,
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
                "control": artifact(land),
                "observed": artifact(land),
                "minimum_match_ratio": 0.98,
                "match_ratio": 1.0,
            },
            "transport": {
                "passed": True,
                "control": artifact(route),
                "observed": artifact(route),
                "tolerance_px": 0,
                "minimum_within_tolerance_ratio": 0.95,
                "control_within_tolerance_ratio": 1.0,
                "observed_within_tolerance_ratio": 1.0,
            },
        },
        "created_at": "2026-07-19T00:00:00Z",
    }
    path = root / f"{sheet_id}-automated.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return artifact(path)


def write_provenance_report(
    root: Path,
    *,
    sheet_id: str,
    master: Path,
    method: str = "guarded-metatile-assembly",
    children: list[dict] | None = None,
) -> dict[str, str]:
    if method == "guarded-metatile-assembly":
        tile, receipt = write_generation_receipt(
            root, sheet_id=sheet_id, column=0, row=0
        )
        provenance = {
            "kind": method,
            "inputs": [
                {
                    "column": 0,
                    "row": 0,
                    **tile,
                    "receipt": receipt,
                }
            ],
            "seams": [],
            "minimum_overlap_ssim": 0.90,
            "maximum_rgb_mean_difference": 4.0,
            "maximum_rgb_p95_difference": 10,
        }
    else:
        provenance = {
            "kind": method,
            "children": children or [],
            "acceptance_inferred": False,
        }
    with Image.open(master) as image:
        width, height = image.size
    report = {
        "schema_version": (
            phase5.BUILD_REPORT_SCHEMA_VERSION
            if method == "deterministic-parent-composite"
            else "1.0.0"
        ),
        "generated_by": phase5.GENERATOR_ID,
        "coordinate_reference_system": "EA-WORLD-1",
        "inputs": {
            "catalog": artifact(phase5.DEFAULT_MAP_SHEETS),
            "resolution_contract": artifact(phase5.DEFAULT_CONTRACT),
            "control_master": artifact(phase5.DEFAULT_CONTROL_MASTER),
            "style_master": None,
        },
        "artifacts": [
            {
                "sheet_id": sheet_id,
                "path": master.name,
                "sha256": digest(master),
                "width": width,
                "height": height,
                "method": method,
                "provenance": provenance,
            }
        ],
    }
    path = root / f"{sheet_id}-provenance.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return artifact(path)


def write_golden_manifest_with_two_reviews(
    root: Path,
    *,
    master: Path,
) -> tuple[Path, list[dict[str, str]]]:
    manifest_path, primary_path = write_golden_manifest(root, master=master)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    review_specs = [
        {"path": item["path"], "sha256": item["sha256"]}
        for item in manifest["jobs"][0]["inputs"]
        if item["role"].startswith("independent-vision-review-")
    ]
    self_check = [
        item for item in review_specs if item["path"] == phase5.repo_path(primary_path)
    ]
    if len(review_specs) != 2 or len(self_check) != 1:
        raise AssertionError("Golden fixture must contain exactly two reviews")
    return manifest_path, review_specs


def write_canonical_provenance_report(
    root: Path,
    *,
    sheet_id: str,
    master: Path,
    golden_style: dict[str, str],
    golden_vision_reports: list[dict[str, str]],
    renderer: Path,
    renderer_report: Path,
    material_atlas: Path,
    control_index: Path = phase5.DEFAULT_CANONICAL_CONTROL_INDEX,
) -> dict[str, str]:
    with Image.open(master) as image:
        width, height = image.size
    report = {
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
            "golden_style": golden_style,
            "golden_vision_reports": golden_vision_reports,
            "renderer": artifact(renderer),
            "renderer_report": artifact(renderer_report),
            "renderer_settings": {
                "seed": 731_942,
                "parameters": {
                    "texture_space": "global-world-coordinate-v1",
                    "labels_baked_into_raster": False,
                },
            },
            "material_atlas": artifact(material_atlas),
            "map_catalog": artifact(phase5.DEFAULT_MAP_SHEETS),
            "resolution_contract": artifact(phase5.DEFAULT_CONTRACT),
            "control_index": artifact(control_index),
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
                "width": width,
                "height": height,
                "format": "PNG",
                "color_mode": "RGB",
                "method": phase5.CANONICAL_RENDER_METHOD,
                "provenance": {
                    "kind": phase5.CANONICAL_RENDER_METHOD,
                    "acceptance_inferred": False,
                },
            }
        ],
        "created_at": "2026-07-20T00:00:00Z",
    }
    path = root / f"{sheet_id}-canonical-provenance.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return artifact(path)


def canonical_fixture(
    root: Path,
    *,
    sheet: dict,
    control_index: Path = phase5.DEFAULT_CANONICAL_CONTROL_INDEX,
) -> tuple[dict, Path, Path, dict]:
    master = root / f"{sheet['id']}-master.png"
    Image.new("RGB", (8, 8), "white").save(master)
    golden = root / "golden.png"
    Image.new("RGB", (32, 24), "gold").save(golden)
    manifest_path, golden_reports = write_golden_manifest_with_two_reviews(
        root, master=golden
    )
    golden_evidence = phase5.verify_manifest_golden_style(
        artifact(golden), manifest_path
    )
    renderer = root / "canonical_renderer.py"
    renderer.write_text(
        "# deterministic canonical renderer fixture\n", encoding="utf-8"
    )
    material_atlas = root / "material-atlas.png"
    Image.new("RGB", (16, 16), "tan").save(material_atlas)
    observed_land = root / f"{sheet['id']}-renderer-observed-land.png"
    observed_transport = root / f"{sheet['id']}-renderer-observed-transport.png"
    Image.new("L", (8, 8), 255).save(observed_land)
    Image.new("L", (8, 8), 255).save(observed_transport)
    renderer_report = root / f"{sheet['id']}-renderer-report.json"
    inverse_roles = {
        value: key for key, value in phase5.RENDERER_SOURCE_ROLE_MAP.items()
    }
    renderer_report.write_text(
        json.dumps(
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
                    "canonical_control_index": artifact(control_index),
                },
                "sheet": {"sheet_id": sheet["id"]},
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
            }
        ),
        encoding="utf-8",
    )
    provenance = write_canonical_provenance_report(
        root,
        sheet_id=sheet["id"],
        master=master,
        golden_style=artifact(golden),
        golden_vision_reports=golden_reports,
        renderer=renderer,
        renderer_report=renderer_report,
        material_atlas=material_atlas,
        control_index=control_index,
    )
    automated = write_automated_report(
        root,
        sheet_id=sheet["id"],
        master=master,
        provenance=provenance,
        source_kind=phase5.CANONICAL_RENDER_SOURCE_KIND,
    )
    threshold = phase5.acceptance_threshold(sheet)
    vision_specs = []
    for index, reviewer in enumerate(("Canonical Reviewer A", "Canonical Reviewer B")):
        report_path = root / f"{sheet['id']}-vision-{index + 1}.json"
        report_path.write_text(
            json.dumps(
                complete_report(
                    phase5.job_id_for_sheet(sheet["id"]),
                    phase5.repo_path(master),
                    reviewer,
                    threshold,
                )
            ),
            encoding="utf-8",
        )
        vision_specs.append(artifact(report_path))
    entry = {
        "sheet_id": sheet["id"],
        "kind": phase5.CANONICAL_RENDER_SOURCE_KIND,
        **artifact(master),
        "provenance_report": provenance,
        "automated_report": automated,
        "vision_reports": vision_specs,
        phase5.INTERNAL_GOLDEN_STYLE_KEY: artifact(golden),
        phase5.INTERNAL_CANONICAL_CONTEXT_KEY: phase5.canonical_render_context(
            catalog_path=phase5.DEFAULT_MAP_SHEETS,
            contract_path=phase5.DEFAULT_CONTRACT,
            control_index_path=control_index,
            golden_evidence=golden_evidence,
        ),
    }
    return entry, master, manifest_path, golden_evidence


class Phase5AssetPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog, cls.catalog_by_id, derived = phase5.load_contract(
            phase5.DEFAULT_CONTRACT,
            phase5.DEFAULT_MAP_SHEETS,
        )
        cls.contract_result = derived["result"]
        cls.contracts = derived["sheets"]

    def _sources_for_target_stage(self, target_stage: str) -> dict[str, dict]:
        sources: dict[str, dict] = {}
        for sheet_id in self.contracts:
            sheet_type = self.catalog_by_id[sheet_id]["sheet_type"]
            include = (
                sheet_type in phase5.GENERATION_TYPES
                if target_stage == "idx22"
                else (sheet_type != "world" if target_stage == "idx23" else True)
            )
            if not include:
                continue
            sources[sheet_id] = {
                "sheet_id": sheet_id,
                "kind": (
                    phase5.CANONICAL_RENDER_SOURCE_KIND
                    if sheet_type in phase5.GENERATION_TYPES
                    else "composite_master"
                ),
            }
        return sources

    def _valid_stage_report(
        self, target_stage: str
    ) -> tuple[phase5.TargetStageContract, dict]:
        contract = phase5.target_stage_contract(
            target_stage=target_stage,
            catalog_by_id=self.catalog_by_id,
            contracts=self.contracts,
            sources=self._sources_for_target_stage(target_stage),
            tiles_requested=target_stage == "final",
            allow_provisional=False,
        )
        generated = set(contract.generated_composite_sheet_ids)
        artifacts = []
        for sheet_id in contract.output_sheet_ids:
            sheet_type = self.catalog_by_id[sheet_id]["sheet_type"]
            method = (
                phase5.CANONICAL_RENDER_METHOD
                if sheet_type in phase5.GENERATION_TYPES
                else (
                    "deterministic-parent-composite"
                    if sheet_id in generated
                    else "verified-composite-master-import"
                )
            )
            artifacts.append(
                {
                    "sheet_id": sheet_id,
                    "method": method,
                    "accepted": sheet_id not in generated,
                    "provisional": sheet_id in generated,
                }
            )
        return contract, {
            "schema_version": phase5.BUILD_REPORT_SCHEMA_VERSION,
            "generated_by": phase5.GENERATOR_ID,
            "coordinate_reference_system": "EA-WORLD-1",
            "inputs": {
                "builder_script": artifact(phase5.BUILDER_SCRIPT_PATH),
            },
            "target_stage": target_stage,
            "generated_composite_sheet_ids": list(
                contract.generated_composite_sheet_ids
            ),
            "deferred_sheet_ids": list(contract.deferred_sheet_ids),
            "bounded_sheet_count": len(contract.output_sheet_ids),
            "materialized_master_count": len(contract.output_sheet_ids),
            "accepted_master_count": len(contract.output_sheet_ids) - len(generated),
            "provisional_master_count": len(generated),
            "planned_only_count": 0,
            "tiles_requested": target_stage == "final",
            "artifacts": artifacts,
        }

    def test_canonical_renderer_identity_matches_reviewed_renderer(self):
        expected = "sstory-map-production/render_phase5_reviewed_master.py@2.6"
        self.assertEqual(
            reviewed_renderer.GENERATOR_ID,
            expected,
        )
        self.assertEqual(
            phase5.CANONICAL_RENDERER_ID,
            expected,
        )

    def test_repository_plan_is_23_sheets_and_99_metatiles(self):
        actions = phase5.plan_actions(
            self.catalog_by_id,
            self.contracts,
            {},
            allow_provisional=False,
        )

        self.assertEqual(len(actions), 23)
        self.assertEqual(self.contract_result["generation_metatile_count"], 99)
        self.assertEqual(
            sum(
                action["metatiles"]["count"]
                for action in actions
                if action["metatiles"] is not None
            ),
            99,
        )
        self.assertEqual(
            sum(action["action"].startswith("blocked-") for action in actions),
            17,
        )
        self.assertEqual(
            sum(
                action["action"] == "deterministic-parent-composite"
                for action in actions
            ),
            6,
        )

    def test_repository_execute_plan_treats_manifest_as_aggregate_boundary(self):
        args = phase5.build_parser().parse_args(["plan"])
        result = phase5.execute_build(args)

        self.assertTrue(result["valid"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["bounded_sheet_count"], 23)
        self.assertEqual(result["generation_metatile_count"], 99)

    def test_build_cli_requires_target_stage(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            phase5.build_parser().parse_args(["build"])
        args = phase5.build_parser().parse_args(["build", "--target-stage", "idx22"])
        self.assertEqual(args.target_stage, "idx22")

    def test_target_stage_contract_is_exact_and_tiles_are_final_only(self):
        idx22_sources = self._sources_for_target_stage("idx22")
        idx22 = phase5.target_stage_contract(
            target_stage="idx22",
            catalog_by_id=self.catalog_by_id,
            contracts=self.contracts,
            sources=idx22_sources,
            tiles_requested=False,
            allow_provisional=False,
        )
        self.assertEqual(len(idx22.source_sheet_ids), 17)
        self.assertEqual(len(idx22.output_sheet_ids), 22)
        self.assertEqual(len(idx22.generated_composite_sheet_ids), 5)
        self.assertEqual(idx22.deferred_sheet_ids, ("sheet_world",))

        idx23 = phase5.target_stage_contract(
            target_stage="idx23",
            catalog_by_id=self.catalog_by_id,
            contracts=self.contracts,
            sources=self._sources_for_target_stage("idx23"),
            tiles_requested=False,
            allow_provisional=False,
        )
        self.assertEqual(len(idx23.source_sheet_ids), 22)
        self.assertEqual(idx23.generated_composite_sheet_ids, ("sheet_world",))
        self.assertEqual(idx23.deferred_sheet_ids, ())

        final = phase5.target_stage_contract(
            target_stage="final",
            catalog_by_id=self.catalog_by_id,
            contracts=self.contracts,
            sources=self._sources_for_target_stage("final"),
            tiles_requested=True,
            allow_provisional=False,
        )
        self.assertEqual(len(final.source_sheet_ids), 23)
        self.assertEqual(final.generated_composite_sheet_ids, ())

        with self.assertRaisesRegex(phase5.Phase5BuildError, "forbids --tiles"):
            phase5.target_stage_contract(
                target_stage="idx22",
                catalog_by_id=self.catalog_by_id,
                contracts=self.contracts,
                sources=idx22_sources,
                tiles_requested=True,
                allow_provisional=False,
            )
        with self.assertRaisesRegex(phase5.Phase5BuildError, "requires --tiles"):
            phase5.target_stage_contract(
                target_stage="final",
                catalog_by_id=self.catalog_by_id,
                contracts=self.contracts,
                sources=self._sources_for_target_stage("final"),
                tiles_requested=False,
                allow_provisional=False,
            )

    def test_target_stage_rejects_coverage_kind_order_and_provisional_inputs(self):
        sources = self._sources_for_target_stage("idx22")
        missing = dict(sources)
        missing.pop(next(iter(missing)))
        with self.assertRaisesRegex(phase5.Phase5BuildError, "exact source-index"):
            phase5.target_stage_contract(
                target_stage="idx22",
                catalog_by_id=self.catalog_by_id,
                contracts=self.contracts,
                sources=missing,
                tiles_requested=False,
                allow_provisional=False,
            )
        wrong_kind = copy.deepcopy(sources)
        wrong_kind[next(iter(wrong_kind))]["kind"] = "master"
        with self.assertRaisesRegex(phase5.Phase5BuildError, "requires kind"):
            phase5.target_stage_contract(
                target_stage="idx22",
                catalog_by_id=self.catalog_by_id,
                contracts=self.contracts,
                sources=wrong_kind,
                tiles_requested=False,
                allow_provisional=False,
            )
        reversed_sources = dict(reversed(list(sources.items())))
        with self.assertRaisesRegex(phase5.Phase5BuildError, "order mismatch"):
            phase5.target_stage_contract(
                target_stage="idx22",
                catalog_by_id=self.catalog_by_id,
                contracts=self.contracts,
                sources=reversed_sources,
                tiles_requested=False,
                allow_provisional=False,
            )
        with self.assertRaisesRegex(phase5.Phase5BuildError, "forbid provisional"):
            phase5.target_stage_contract(
                target_stage="idx22",
                catalog_by_id=self.catalog_by_id,
                contracts=self.contracts,
                sources=sources,
                tiles_requested=False,
                allow_provisional=True,
            )

    def test_stage_materialization_call_counts_and_future_images_absent(self):
        expected = {
            "idx22": (17, 0, 5),
            "idx23": (17, 5, 1),
            "final": (17, 6, 0),
        }
        for target_stage, expected_counts in expected.items():
            with (
                self.subTest(target_stage=target_stage),
                tempfile.TemporaryDirectory(
                    prefix=".phase5-stage-materialization-test-", dir=REPO_ROOT
                ) as temporary,
            ):
                root = Path(temporary)
                staging = root / "staging"
                final_root = root / "final"
                calls = {"direct": [], "imported": [], "composite": []}

                def fake_asset(kwargs: dict, method: str) -> phase5.BuiltAsset:
                    sheet = kwargs["sheet"]
                    contract = kwargs["contract"]
                    path = staging / "masters" / f"{sheet['id']}.png"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (1, 1), "white").save(path)
                    return phase5.BuiltAsset(
                        sheet=sheet,
                        contract=contract,
                        job_id=phase5.job_id_for_sheet(sheet["id"]),
                        method=method,
                        stage_path=path,
                        final_manifest_path=phase5.repo_path(
                            final_root / "masters" / path.name
                        ),
                        sha256="0" * 64,
                    )

                def fake_direct(**kwargs):
                    calls["direct"].append(kwargs["sheet"]["id"])
                    return fake_asset(kwargs, phase5.CANONICAL_RENDER_METHOD)

                def fake_imported(**kwargs):
                    calls["imported"].append(kwargs["sheet"]["id"])
                    return fake_asset(kwargs, "verified-composite-master-import")

                def fake_composite(**kwargs):
                    calls["composite"].append(kwargs["sheet"]["id"])
                    return fake_asset(kwargs, "deterministic-parent-composite")

                sources = self._sources_for_target_stage(target_stage)
                contract = phase5.target_stage_contract(
                    target_stage=target_stage,
                    catalog_by_id=self.catalog_by_id,
                    contracts=self.contracts,
                    sources=sources,
                    tiles_requested=target_stage == "final",
                    allow_provisional=False,
                )
                with (
                    patch.object(phase5, "build_generation_asset", fake_direct),
                    patch.object(phase5, "build_imported_master_asset", fake_imported),
                    patch.object(phase5, "build_composite_asset", fake_composite),
                ):
                    assets = phase5.materialize_target_stage_assets(
                        stage_contract=contract,
                        contracts=self.contracts,
                        catalog_by_id=self.catalog_by_id,
                        sources=sources,
                        staging_root=staging,
                        final_root=final_root,
                        control_master=phase5.DEFAULT_CONTROL_MASTER,
                        style_master=None,
                        minimum_ssim=0.9,
                        resolution_contract_path=phase5.DEFAULT_CONTRACT,
                    )
                self.assertEqual(
                    tuple(
                        len(calls[key]) for key in ("direct", "imported", "composite")
                    ),
                    expected_counts,
                )
                self.assertEqual(set(assets), set(contract.output_sheet_ids))
                if target_stage == "idx22":
                    self.assertFalse((staging / "masters" / "sheet_world.png").exists())
                if target_stage == "idx23":
                    self.assertEqual(calls["composite"], ["sheet_world"])
                if target_stage == "final":
                    self.assertEqual(calls["composite"], [])

    def test_stage_mismatch_fails_before_output_or_staging_creation(self):
        with tempfile.TemporaryDirectory(
            prefix=".phase5-stage-preflight-test-", dir=REPO_ROOT
        ) as temporary:
            output = Path(temporary) / "must-not-exist"
            args = phase5.build_parser().parse_args(
                [
                    "build",
                    "--target-stage",
                    "idx22",
                    "--source-index",
                    str(Path(temporary) / "wrong-index.json"),
                    "--output-root",
                    str(output),
                ]
            )
            with (
                patch.object(
                    phase5, "load_source_index", return_value=({}, None, None)
                ),
                patch.object(phase5, "_prepare_output_root") as prepare,
                self.assertRaisesRegex(phase5.Phase5BuildError, "exact source-index"),
            ):
                phase5.execute_build(args)
            prepare.assert_not_called()
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(temporary).glob(".*.building-*")), [])

    def test_existing_output_is_rejected_before_any_source_preflight(self):
        with tempfile.TemporaryDirectory(
            prefix=".phase5-existing-output-test-", dir=REPO_ROOT
        ) as temporary:
            output = Path(temporary) / "occupied"
            output.mkdir()
            sentinel = output / "owner.txt"
            sentinel.write_text("foreign", encoding="utf-8")
            args = phase5.build_parser().parse_args(
                [
                    "build",
                    "--target-stage",
                    "idx22",
                    "--style-master",
                    str(Path(temporary) / "missing-style.png"),
                    "--source-index",
                    str(Path(temporary) / "missing-index.json"),
                    "--output-root",
                    str(output),
                ]
            )
            with (
                patch.object(phase5, "bind_file") as bind,
                patch.object(phase5, "load_source_index") as load_index,
                self.assertRaisesRegex(
                    phase5.Phase5BuildError, "refusing to overwrite"
                ),
            ):
                phase5.execute_build(args)
            bind.assert_not_called()
            load_index.assert_not_called()
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "foreign")
            self.assertEqual(list(Path(temporary).glob(".*.phase5-build.lock")), [])
            self.assertEqual(list(Path(temporary).glob(".*.building-*")), [])

    def test_build_output_root_must_be_trackable_and_nonvolatile(self):
        output = REPO_ROOT / "tmp" / "map-production" / "never-create-phase5-build"
        with self.assertRaisesRegex(phase5.Phase5BuildError, "volatile or ignored"):
            phase5._preflight_output_root(output)
        self.assertFalse(output.exists())

    def test_atomic_output_install_rolls_back_and_never_replaces_existing(self):
        with tempfile.TemporaryDirectory(
            prefix=".phase5-stage-rollback-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            staging = root / "staging"
            final = root / "final"
            staging.mkdir()
            (staging / "sentinel.txt").write_text("candidate", encoding="utf-8")
            identity = phase5._install_staged_output(staging, final)
            self.assertTrue(final.is_dir())
            phase5._rollback_installed_output(final, staging, identity)
            self.assertFalse(final.exists())
            self.assertEqual(
                (staging / "sentinel.txt").read_text(encoding="utf-8"),
                "candidate",
            )

            occupied = root / "occupied"
            occupied.mkdir()
            (occupied / "owner.txt").write_text("foreign", encoding="utf-8")
            with self.assertRaisesRegex(phase5.Phase5BuildError, "appeared"):
                phase5._install_staged_output(staging, occupied)
            self.assertEqual(
                (occupied / "owner.txt").read_text(encoding="utf-8"), "foreign"
            )

    def test_execute_build_rolls_back_after_install_on_exception_and_interrupt(self):
        sources = self._sources_for_target_stage("final")
        golden = artifact(phase5.DEFAULT_CONTROL_MASTER)
        accepted = phase5.QAEvidence(
            provenance_path="fixture-provenance.json",
            automated_path="fixture-automated.json",
            vision_paths=("fixture-vision.json",),
            primary_score=100,
            primary_reviewer="Fixture Reviewer",
        )

        for failure in (
            phase5.Phase5BuildError("post-install validation failure"),
            KeyboardInterrupt("post-install interrupt"),
        ):
            with (
                self.subTest(failure=type(failure).__name__),
                tempfile.TemporaryDirectory(
                    prefix=".phase5-execute-rollback-test-", dir=REPO_ROOT
                ) as temporary,
            ):
                root = Path(temporary)
                output = root / "final-build"
                source_index = root / "idx23.json"
                args = phase5.build_parser().parse_args(
                    [
                        "build",
                        "--target-stage",
                        "final",
                        "--tiles",
                        "--source-index",
                        str(source_index),
                        "--output-root",
                        str(output),
                    ]
                )

                def fake_materialize(**kwargs):
                    staging = kwargs["staging_root"]
                    final_root = kwargs["final_root"]
                    result = {}
                    for sheet_id in kwargs["stage_contract"].output_sheet_ids:
                        sheet = self.catalog_by_id[sheet_id]
                        path = staging / "masters" / f"{sheet_id}.png"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        Image.new("RGB", (1, 1), "white").save(path)
                        result[sheet_id] = phase5.BuiltAsset(
                            sheet=sheet,
                            contract=self.contracts[sheet_id],
                            job_id=phase5.job_id_for_sheet(sheet_id),
                            method=(
                                phase5.CANONICAL_RENDER_METHOD
                                if sheet["sheet_type"] in phase5.GENERATION_TYPES
                                else "verified-composite-master-import"
                            ),
                            stage_path=path,
                            final_manifest_path=phase5.repo_path(
                                final_root / "masters" / path.name
                            ),
                            sha256=phase5.sha256_file(path),
                            accepted_evidence=accepted,
                            source_entry=sources[sheet_id],
                        )
                    return result

                publication = {
                    "valid": True,
                    "errors": [],
                    "tile_count": phase5.EXPECTED_PHASE5_TILE_COUNT,
                    "tile_bytes": 1234,
                }
                with (
                    patch.object(
                        phase5,
                        "load_source_index",
                        return_value=(sources, "1" * 64, golden),
                    ),
                    patch.object(
                        phase5, "bind_manifest_golden_evidence", return_value={}
                    ),
                    patch.object(
                        phase5,
                        "verify_manifest_golden_style",
                        return_value={"job_id": "fixture-golden"},
                    ),
                    patch.object(phase5, "canonical_render_context", return_value={}),
                    patch.object(phase5, "preflight_source_entry"),
                    patch.object(
                        phase5,
                        "materialize_target_stage_assets",
                        side_effect=fake_materialize,
                    ),
                    patch.object(phase5, "build_tiles_for_accepted"),
                    patch.object(
                        phase5,
                        "build_sheet_tile_index",
                        return_value={
                            "bounded_sheet_count": 23,
                            "sheets": [{} for _ in range(22)],
                        },
                    ),
                    patch.object(
                        phase5,
                        "validate_public_tile_release",
                        return_value=publication,
                    ),
                    patch.object(
                        phase5,
                        "create_job",
                        side_effect=lambda asset, **_: {
                            "id": f"rollback-{asset.sheet['id']}",
                            "sheet_id": asset.sheet["id"],
                            "status": "tiled",
                        },
                    ),
                    patch.object(phase5, "write_qa_scaffolds", return_value=[]),
                    patch.object(phase5, "_assert_bound_registry_unchanged"),
                    patch.object(phase5, "validate_manifest", side_effect=failure),
                ):
                    with self.assertRaises(type(failure)):
                        phase5.execute_build(args)
                self.assertFalse(output.exists())
                self.assertEqual(list(root.glob(".*.phase5-build.lock")), [])
                self.assertEqual(list(root.glob(".*.building-*")), [])

    def test_canonical_contract_recomputes_exactly_1350_tiles(self):
        total = 0
        for contract in self.contracts.values():
            native = contract["native_zoom"]
            minimum = contract["zoom_range"][0]
            for zoom in range(minimum, native + 1):
                divisor = 2 ** (native - zoom)
                width = math.ceil(contract["width"] / divisor)
                height = math.ceil(contract["height"] / divisor)
                total += math.ceil(width / 512) * math.ceil(height / 512)
        self.assertEqual(total, phase5.EXPECTED_PHASE5_TILE_COUNT)
        self.assertEqual(total, 1350)

    def test_stage_reports_pin_methods_acceptance_and_provisional_counts(self):
        for target_stage in phase5.TARGET_STAGES:
            with self.subTest(target_stage=target_stage):
                _, report = self._valid_stage_report(target_stage)
                self.assertEqual(phase5._build_report_stage_errors(report), [])
                generated = report["generated_composite_sheet_ids"]
                if generated:
                    record = next(
                        item
                        for item in report["artifacts"]
                        if item["sheet_id"] == generated[0]
                    )
                    record["method"] = "verified-composite-master-import"
                    self.assertTrue(phase5._build_report_stage_errors(report))

    def test_stage_reports_reject_wrong_generator_and_crs(self):
        _, report = self._valid_stage_report("idx22")
        for key, value in (
            ("generated_by", "foreign-builder@1"),
            ("coordinate_reference_system", "EPSG:3857"),
        ):
            with self.subTest(key=key):
                changed = copy.deepcopy(report)
                changed[key] = value
                errors = phase5._build_report_stage_errors(changed)
                self.assertTrue(any(key in error for error in errors))

    def test_installed_inventory_rejects_hidden_future_master_and_qa(self):
        contract, report = self._valid_stage_report("idx22")
        masters, masks, scaffolds = phase5._expected_stage_inventory_paths(
            contract, self.catalog_by_id
        )
        report["qa_scaffolds"] = sorted(scaffolds)
        with tempfile.TemporaryDirectory(
            prefix=".phase5-stage-inventory-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            for relative in masters | masks | scaffolds:
                path = root.joinpath(*relative.split("/"))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")
            self.assertEqual(phase5._installed_stage_inventory_errors(root, report), [])
            hidden_world = root / "masters" / "sheet_world.png"
            hidden_world.write_bytes(b"future")
            errors = phase5._installed_stage_inventory_errors(root, report)
            self.assertTrue(any("sheet_world.png" in error for error in errors))
            hidden_world.unlink()
            hidden_qa = root / "qa" / "phase5-sheet-world-v1-review1.json"
            hidden_qa.write_text("{}", encoding="utf-8")
            errors = phase5._installed_stage_inventory_errors(root, report)
            self.assertTrue(
                any("installed QA inventory mismatch" in error for error in errors)
            )

    def test_idx17_to_idx22_to_idx23_to_final_contract_end_to_end(self):
        idx22 = phase5.target_stage_contract(
            target_stage="idx22",
            catalog_by_id=self.catalog_by_id,
            contracts=self.contracts,
            sources=self._sources_for_target_stage("idx22"),
            tiles_requested=False,
            allow_provisional=False,
        )

        def accepted_sources(
            stage: phase5.TargetStageContract,
        ) -> dict[str, dict]:
            return {
                sheet_id: {
                    "sheet_id": sheet_id,
                    "kind": (
                        phase5.CANONICAL_RENDER_SOURCE_KIND
                        if self.catalog_by_id[sheet_id]["sheet_type"]
                        in phase5.GENERATION_TYPES
                        else "composite_master"
                    ),
                }
                for sheet_id in stage.output_sheet_ids
            }

        idx23_sources = accepted_sources(idx22)
        idx23 = phase5.target_stage_contract(
            target_stage="idx23",
            catalog_by_id=self.catalog_by_id,
            contracts=self.contracts,
            sources=idx23_sources,
            tiles_requested=False,
            allow_provisional=False,
        )
        self.assertEqual(tuple(idx23_sources), idx23.source_sheet_ids)
        self.assertEqual(idx23.generated_composite_sheet_ids, ("sheet_world",))

        final_sources = accepted_sources(idx23)
        final = phase5.target_stage_contract(
            target_stage="final",
            catalog_by_id=self.catalog_by_id,
            contracts=self.contracts,
            sources=final_sources,
            tiles_requested=True,
            allow_provisional=False,
        )
        self.assertEqual(tuple(final_sources), final.source_sheet_ids)
        self.assertEqual(len(final.output_sheet_ids), 23)
        self.assertEqual(final.generated_composite_sheet_ids, ())

    def test_source_index_is_validated_against_the_checked_in_schema(self):
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            path = Path(temporary) / "sources.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.3.0",
                        "coordinate_reference_system": "EA-WORLD-1",
                        "golden_style": artifact(phase5.DEFAULT_CONTROL_MASTER),
                        "sources": [],
                        "unexpected": "must fail closed",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                phase5.Phase5BuildError, "invalid source index"
            ):
                phase5.load_source_index(path, set(self.contracts))

    def test_source_index_requires_a_hash_locked_receipt_for_every_metatile(self):
        sheet_id = "sheet_region_emerald_plains_region"
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            tile = root / "tile.png"
            Image.new("RGB", (2048, 2048), "green").save(tile)
            path = root / "sources.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.3.0",
                        "coordinate_reference_system": "EA-WORLD-1",
                        "golden_style": artifact(tile),
                        "sources": [
                            {
                                "sheet_id": sheet_id,
                                "kind": "metatiles",
                                "tiles": [{"column": 0, "row": 0, **artifact(tile)}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                phase5.Phase5BuildError, "invalid source index"
            ):
                phase5.load_source_index(path, set(self.contracts))

    def test_canonical_render_master_is_accepted_through_its_distinct_method(self):
        sheet = self.catalog_by_id["sheet_region_royal_capital_region"]
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            entry, master, _, _ = canonical_fixture(root, sheet=sheet)
            public_entry = {
                key: value
                for key, value in entry.items()
                if not key.startswith("_phase5_")
            }
            source_index = root / "canonical-source-index.json"
            source_index.write_text(
                json.dumps(
                    {
                        "schema_version": "1.3.0",
                        "coordinate_reference_system": "EA-WORLD-1",
                        "golden_style": entry[phase5.INTERNAL_GOLDEN_STYLE_KEY],
                        "sources": [public_entry],
                    }
                ),
                encoding="utf-8",
            )
            loaded, _, _ = phase5.load_source_index(source_index, set(self.contracts))
            self.assertEqual(
                loaded[sheet["id"]]["kind"],
                phase5.CANONICAL_RENDER_SOURCE_KIND,
            )
            loaded_entry = loaded[sheet["id"]]
            loaded_entry[phase5.INTERNAL_CANONICAL_CONTEXT_KEY] = entry[
                phase5.INTERNAL_CANONICAL_CONTEXT_KEY
            ]
            entry = loaded_entry

            incomplete_index = json.loads(source_index.read_text(encoding="utf-8"))
            del incomplete_index["sources"][0]["automated_report"]
            source_index.write_text(json.dumps(incomplete_index), encoding="utf-8")
            with self.assertRaisesRegex(
                phase5.Phase5BuildError, "invalid source index"
            ):
                phase5.load_source_index(source_index, set(self.contracts))

            contract = {**self.contracts[sheet["id"]], "width": 8, "height": 8}
            evidence = phase5.accepted_evidence(
                entry,
                sheet=sheet,
                master_path=phase5.repo_path(master),
                job_id=phase5.job_id_for_sheet(sheet["id"]),
                contract=contract,
                catalog_by_id=self.catalog_by_id,
                sources={sheet["id"]: entry},
            )
            self.assertIsNotNone(evidence)
            self.assertEqual(len(evidence.vision_paths), 2)
            phase5.preflight_source_entry(
                entry,
                sheet=sheet,
                contract=contract,
                catalog_by_id=self.catalog_by_id,
                sources={sheet["id"]: entry},
            )
            imported = phase5.build_imported_master_asset(
                sheet=sheet,
                contract=contract,
                source_entry=entry,
                staging_root=root / "staging",
                final_root=root / "final",
                catalog_by_id=self.catalog_by_id,
                sources={sheet["id"]: entry},
            )
            self.assertTrue(imported.accepted)
            self.assertEqual(imported.method, phase5.CANONICAL_RENDER_METHOD)
            job = phase5.create_job(
                imported,
                assets_by_sheet={sheet["id"]: imported},
                catalog_path=phase5.DEFAULT_MAP_SHEETS,
                contract_path=phase5.DEFAULT_CONTRACT,
                control_master=phase5.DEFAULT_CONTROL_MASTER,
                style_master=None,
            )
            self.assertEqual(job["status"], "accepted")
            self.assertIn(phase5.CANONICAL_RENDER_METHOD, job["notes"])

            actions = phase5.plan_actions(
                self.catalog_by_id,
                self.contracts,
                {sheet["id"]: entry},
                allow_provisional=False,
            )
            action = next(item for item in actions if item["sheet_id"] == sheet["id"])
            self.assertEqual(
                action["action"], "verified-canonical-render-master-import"
            )

    def test_canonical_render_master_auditor_builds_checked_context(self):
        sheet = self.catalog_by_id["sheet_region_royal_capital_region"]
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            land_mask = root / "land.png"
            route_mask = root / "route.png"
            Image.new("L", (8, 8), 255).save(land_mask)
            Image.new("L", (8, 8), 255).save(route_mask)
            control_index = root / "control-index.json"
            control_index.write_text(
                json.dumps(
                    {
                        "sheets": [
                            {
                                "sheet_id": sheet["id"],
                                "qa_controls": {
                                    "land_sea_control": artifact(land_mask),
                                    "transport_control": artifact(route_mask),
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            entry, master, manifest_path, _ = canonical_fixture(
                root, sheet=sheet, control_index=control_index
            )
            contract = {**self.contracts[sheet["id"]], "width": 8, "height": 8}
            observed_land = root / f"{sheet['id']}-renderer-observed-land.png"
            observed_route = root / f"{sheet['id']}-renderer-observed-transport.png"
            provenance_path = phase5.resolve_repo_artifact(
                entry["provenance_report"]["path"],
                "canonical auditor provenance",
            )
            derived = {"sheets": {sheet["id"]: contract}}

            with patch.object(
                phase5_audit,
                "load_contract",
                return_value=(self.catalog, self.catalog_by_id, derived),
            ):
                report = phase5_audit.audit_phase5_master(
                    sheet_id=sheet["id"],
                    source_kind=phase5.CANONICAL_RENDER_SOURCE_KIND,
                    master_path=master,
                    provenance_path=provenance_path,
                    land_sea_control_path=land_mask,
                    land_sea_observed_path=observed_land,
                    transport_control_path=route_mask,
                    transport_observed_path=observed_route,
                    transport_tolerance_px=0,
                    base_manifest_path=manifest_path,
                    canonical_control_index_path=control_index,
                )

            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["source_kind"], phase5.CANONICAL_RENDER_SOURCE_KIND)
            self.assertEqual(report["checks"]["seams"]["expected_count"], 0)
            self.assertEqual(report["checks"]["seams"]["evaluated_count"], 0)
            with patch.object(
                phase5_audit,
                "load_contract",
                return_value=(self.catalog, self.catalog_by_id, derived),
            ):
                with self.assertRaisesRegex(
                    phase5.Phase5BuildError,
                    "observed mask is not the renderer output artifact",
                ):
                    phase5_audit.audit_phase5_master(
                        sheet_id=sheet["id"],
                        source_kind=phase5.CANONICAL_RENDER_SOURCE_KIND,
                        master_path=master,
                        provenance_path=provenance_path,
                        land_sea_control_path=land_mask,
                        land_sea_observed_path=land_mask,
                        transport_control_path=route_mask,
                        transport_observed_path=observed_route,
                        transport_tolerance_px=0,
                        base_manifest_path=manifest_path,
                        canonical_control_index_path=control_index,
                    )

    def test_renderer_report_promotes_to_complete_canonical_provenance_only_after_golden(
        self,
    ):
        sheet = self.catalog_by_id["sheet_region_royal_capital_region"]
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            entry, master, manifest_path, _ = canonical_fixture(root, sheet=sheet)
            renderer_report = root / f"{sheet['id']}-renderer-report.json"
            output = root / f"{sheet['id']}-promoted-provenance.json"
            document = phase5.write_canonical_render_provenance(
                renderer_report_path=renderer_report,
                output_path=output,
                base_manifest_path=manifest_path,
                created_at="2026-07-20T00:00:00Z",
            )
            self.assertEqual(document["sheet_id"], sheet["id"])
            self.assertEqual(len(document["inputs"]["golden_vision_reports"]), 2)
            self.assertEqual(len(document["inputs"]["canon_sources"]), 6)
            for role in (
                "renderer",
                "renderer_report",
                "material_atlas",
                "control_index",
            ):
                self.assertEqual(len(document["inputs"][role]["sha256"]), 64)

            promoted = copy.deepcopy(entry)
            promoted["provenance_report"] = artifact(output)
            contract = {**self.contracts[sheet["id"]], "width": 8, "height": 8}
            phase5.verify_master_provenance(
                promoted,
                sheet=sheet,
                master_path=phase5.repo_path(master),
                contract=contract,
                catalog_by_id=self.catalog_by_id,
                sources={sheet["id"]: promoted},
            )

            pending = json.loads(renderer_report.read_text(encoding="utf-8"))
            pending["status"] = "pending-golden-style"
            pending_path = root / "pending-renderer-report.json"
            pending_path.write_text(json.dumps(pending), encoding="utf-8")
            with self.assertRaisesRegex(
                phase5.Phase5BuildError, "pending; accepted Golden style is required"
            ):
                phase5.write_canonical_render_provenance(
                    renderer_report_path=pending_path,
                    output_path=root / "must-not-exist.json",
                    base_manifest_path=manifest_path,
                )

    def test_canonical_render_provenance_rejects_locked_input_tampering(self):
        sheet = self.catalog_by_id["sheet_region_royal_capital_region"]
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            entry, master, _, _ = canonical_fixture(root, sheet=sheet)
            contract = {**self.contracts[sheet["id"]], "width": 8, "height": 8}
            provenance_path = phase5.resolve_repo_artifact(
                entry["provenance_report"]["path"], "canonical fixture provenance"
            )
            original = json.loads(provenance_path.read_text(encoding="utf-8"))

            cases = [
                (
                    "renderer-hash",
                    lambda value: value["inputs"]["renderer"].__setitem__(
                        "sha256", "0" * 64
                    ),
                    "sha256 mismatch",
                ),
                (
                    "renderer-not-executable-source",
                    lambda value: value["inputs"].__setitem__(
                        "renderer", artifact(master)
                    ),
                    "executable source artifact",
                ),
                (
                    "golden-mismatch",
                    lambda value: value["inputs"].__setitem__(
                        "golden_style", value["inputs"]["renderer"]
                    ),
                    "does not match the manifest Golden artifact",
                ),
                (
                    "catalog-mismatch",
                    lambda value: value["inputs"].__setitem__(
                        "map_catalog", value["inputs"]["renderer"]
                    ),
                    "does not match the build input",
                ),
                (
                    "missing-canonical-source",
                    lambda value: value["inputs"]["canon_sources"].pop(),
                    "is invalid",
                ),
                (
                    "missing-seed",
                    lambda value: value["inputs"]["renderer_settings"].pop("seed"),
                    "is invalid",
                ),
                (
                    "master-hash",
                    lambda value: value["artifacts"][0].__setitem__("sha256", "0" * 64),
                    "master hash does not match",
                ),
            ]
            for name, mutate, message in cases:
                with self.subTest(name=name):
                    changed = copy.deepcopy(original)
                    mutate(changed)
                    provenance_path.write_text(json.dumps(changed), encoding="utf-8")
                    changed_entry = copy.deepcopy(entry)
                    changed_entry["provenance_report"]["sha256"] = digest(
                        provenance_path
                    )
                    with self.assertRaisesRegex(phase5.Phase5BuildError, message):
                        phase5.accepted_evidence(
                            changed_entry,
                            sheet=sheet,
                            master_path=phase5.repo_path(master),
                            job_id=phase5.job_id_for_sheet(sheet["id"]),
                            contract=contract,
                            catalog_by_id=self.catalog_by_id,
                            sources={sheet["id"]: changed_entry},
                        )

            changed = copy.deepcopy(original)
            changed["inputs"]["renderer_settings"]["seed"] = 1
            provenance_path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(phase5.Phase5BuildError, "sha256 mismatch"):
                phase5.accepted_evidence(
                    entry,
                    sheet=sheet,
                    master_path=phase5.repo_path(master),
                    job_id=phase5.job_id_for_sheet(sheet["id"]),
                    contract=contract,
                    catalog_by_id=self.catalog_by_id,
                    sources={sheet["id"]: entry},
                )

    def test_canonical_render_provenance_rejects_stale_renderer_generation(self):
        sheet = self.catalog_by_id["sheet_region_royal_capital_region"]
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            _, _, manifest_path, _ = canonical_fixture(root, sheet=sheet)
            renderer_report = root / f"{sheet['id']}-renderer-report.json"
            document = json.loads(renderer_report.read_text(encoding="utf-8"))
            document["generated_by"]["id"] = (
                "sstory-map-production/render_phase5_reviewed_master.py@2.5"
            )
            renderer_report.write_text(json.dumps(document), encoding="utf-8")
            output = root / "must-not-exist.json"

            with self.assertRaisesRegex(phase5.Phase5BuildError, "wrong generator id"):
                phase5.write_canonical_render_provenance(
                    renderer_report_path=renderer_report,
                    output_path=output,
                    base_manifest_path=manifest_path,
                )
            self.assertFalse(output.exists())

    def test_canonical_render_rejects_incomplete_golden_and_wrong_sheet_type(self):
        sheet = self.catalog_by_id["sheet_region_royal_capital_region"]
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            entry, master, _, _ = canonical_fixture(root, sheet=sheet)
            contract = {**self.contracts[sheet["id"]], "width": 8, "height": 8}
            incomplete = copy.deepcopy(entry)
            golden_evidence = incomplete[phase5.INTERNAL_CANONICAL_CONTEXT_KEY][
                "golden_evidence"
            ]
            golden_evidence["manifest_vision_reports"] = [
                golden_evidence["vision_report_artifact"]
            ]
            with self.assertRaisesRegex(
                phase5.Phase5BuildError, "exactly two independent Vision reports"
            ):
                phase5.accepted_evidence(
                    incomplete,
                    sheet=sheet,
                    master_path=phase5.repo_path(master),
                    job_id=phase5.job_id_for_sheet(sheet["id"]),
                    contract=contract,
                    catalog_by_id=self.catalog_by_id,
                    sources={sheet["id"]: incomplete},
                )

            with self.assertRaisesRegex(
                phase5.Phase5BuildError, "dimensions must match"
            ):
                phase5.preflight_source_entry(
                    entry,
                    sheet=sheet,
                    contract={**contract, "width": 9},
                    catalog_by_id=self.catalog_by_id,
                    sources={sheet["id"]: entry},
                )

            world = self.catalog_by_id["sheet_world"]
            world_entry, _, manifest_path, _ = canonical_fixture(root, sheet=world)
            public_world_entry = {
                key: value
                for key, value in world_entry.items()
                if not key.startswith("_phase5_")
            }
            source_index = root / "wrong-sheet-type-index.json"
            source_index.write_text(
                json.dumps(
                    {
                        "schema_version": "1.3.0",
                        "coordinate_reference_system": "EA-WORLD-1",
                        "golden_style": world_entry[phase5.INTERNAL_GOLDEN_STYLE_KEY],
                        "sources": [public_world_entry],
                    }
                ),
                encoding="utf-8",
            )
            args = phase5.build_parser().parse_args(
                [
                    "plan",
                    "--base-manifest",
                    str(manifest_path),
                    "--source-index",
                    str(source_index),
                ]
            )
            with self.assertRaisesRegex(
                phase5.Phase5BuildError,
                "allowed only for region, corridor, or settlement",
            ):
                phase5.execute_build(args)

    def test_all_99_planned_metatiles_fail_schema_without_receipts(self):
        schema = json.loads(
            phase5.DEFAULT_SOURCE_INDEX_SCHEMA.read_text(encoding="utf-8")
        )
        metatile_schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "$ref": "#/definitions/metatile",
            "definitions": schema["definitions"],
        }
        checked = 0
        for sheet_id, contract in self.contracts.items():
            plan = phase5.metatile_plan(contract)
            if plan is None:
                continue
            for tile in plan["tiles"]:
                source_tile = {
                    "column": tile["column"],
                    "row": tile["row"],
                    "path": "tmp/missing-receipt.png",
                    "sha256": "0" * 64,
                }
                errors = phase5.schema_errors(source_tile, metatile_schema)
                self.assertTrue(
                    any(
                        "'receipt' is a required property" in error for error in errors
                    ),
                    f"{sheet_id} ({tile['column']}, {tile['row']})",
                )
                checked += 1
        self.assertEqual(checked, 99)

    def test_manifest_golden_style_gate_rejects_forged_acceptance(self):
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            master = root / "golden.png"
            Image.new("RGB", (32, 24), "gold").save(master)
            manifest_path, report_path = write_golden_manifest(root, master=master)
            golden_style = artifact(master)
            evidence = phase5.verify_manifest_golden_style(golden_style, manifest_path)
            self.assertEqual(evidence["job_id"], "golden-style-fixture-v1")
            original_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            third_report = complete_report(
                "golden-style-fixture-v1",
                phase5.repo_path(master),
                "Golden Reviewer C",
                94,
                golden=True,
            )
            third_path = root / "golden-style-fixture-v1-vision-c.json"
            third_path.write_text(json.dumps(third_report), encoding="utf-8")

            manifest_cases = [
                (
                    "duplicate",
                    lambda value: value["jobs"].append(
                        {**copy.deepcopy(value["jobs"][0]), "id": "golden-duplicate-v1"}
                    ),
                    "exactly one",
                ),
                (
                    "status",
                    lambda value: value["jobs"][0].__setitem__("status", "revise"),
                    "status accepted",
                ),
                (
                    "threshold",
                    lambda value: value["jobs"][0].__setitem__(
                        "acceptance_threshold", 90
                    ),
                    "at least 94",
                ),
                (
                    "vision-decision",
                    lambda value: value["jobs"][0]["qa"]["vision"].__setitem__(
                        "decision", "revise"
                    ),
                    "decision must be accepted",
                ),
                (
                    "vision-score",
                    lambda value: value["jobs"][0]["qa"]["vision"].__setitem__(
                        "score", 93
                    ),
                    "score must be at least 94",
                ),
                (
                    "vision-reviewer",
                    lambda value: value["jobs"][0]["qa"]["vision"].__setitem__(
                        "reviewer", "Another Reviewer"
                    ),
                    "reviewer is inconsistent",
                ),
                (
                    "missing-raw",
                    lambda value: value["jobs"][0].__setitem__(
                        "inputs",
                        [
                            item
                            for item in value["jobs"][0]["inputs"]
                            if item["role"] != "golden-raw-output"
                        ],
                    ),
                    "exactly one golden-raw-output",
                ),
                (
                    "unexpected-review-role",
                    lambda value: value["jobs"][0]["inputs"].append(
                        {**artifact(third_path), "role": "independent-vision-review-c"}
                    ),
                    "unexpected Vision review role",
                ),
                (
                    "unhashed-primary",
                    lambda value: value["jobs"][0]["qa"]["vision"].update(
                        {
                            "report_path": phase5.repo_path(third_path),
                            "reviewer": "Golden Reviewer C",
                        }
                    ),
                    "primary Vision report must be one of its two manifest-hashed reviews",
                ),
            ]
            for name, mutate, message in manifest_cases:
                with self.subTest(name=name):
                    changed = copy.deepcopy(original_manifest)
                    mutate(changed)
                    manifest_path.write_text(json.dumps(changed), encoding="utf-8")
                    with self.assertRaisesRegex(phase5.Phase5BuildError, message):
                        phase5.verify_manifest_golden_style(golden_style, manifest_path)

            manifest_path.write_text(json.dumps(original_manifest), encoding="utf-8")
            original_report = json.loads(report_path.read_text(encoding="utf-8"))
            report_cases = [
                (
                    "not-golden",
                    lambda value: value.__setitem__("golden_reference", False),
                    "golden_reference must be true",
                ),
                (
                    "stale-image-sha",
                    lambda value: value.__setitem__("image_sha256", "0" * 64),
                    "image_sha256 mismatch",
                ),
                (
                    "nonblind",
                    lambda value: value.__setitem__("review_mode", "self"),
                    "review_mode",
                ),
                (
                    "draft",
                    lambda value: value.__setitem__("status", "draft"),
                    "complete and accepted",
                ),
                (
                    "immediate-failure",
                    lambda value: value["immediate_failures"][0].__setitem__(
                        "detected", True
                    ),
                    "unresolved immediate failures",
                ),
            ]
            for name, mutate, message in report_cases:
                with self.subTest(name=name):
                    changed = copy.deepcopy(original_report)
                    mutate(changed)
                    report_path.write_text(json.dumps(changed), encoding="utf-8")
                    with self.assertRaisesRegex(phase5.Phase5BuildError, message):
                        phase5.verify_manifest_golden_style(golden_style, manifest_path)

            report_path.write_text(json.dumps(original_report), encoding="utf-8")
            second_spec = next(
                item
                for item in original_manifest["jobs"][0]["inputs"]
                if item["role"] == "independent-vision-review-b"
            )
            second_path = phase5.resolve_repo_artifact(
                second_spec["path"], "secondary Golden review"
            )
            original_second = second_path.read_bytes()
            aliased = json.loads(original_second.decode("utf-8"))
            aliased["reviewer"] = "Ｇｏｌｄｅｎ\u3000Ｒｅｖｉｅｗｅｒ"
            second_path.write_text(json.dumps(aliased), encoding="utf-8")
            alias_manifest = copy.deepcopy(original_manifest)
            next(
                item
                for item in alias_manifest["jobs"][0]["inputs"]
                if item["role"] == "independent-vision-review-b"
            )["sha256"] = digest(second_path)
            manifest_path.write_text(json.dumps(alias_manifest), encoding="utf-8")
            with self.assertRaisesRegex(
                phase5.Phase5BuildError, "two distinct blind-independent reviewers"
            ):
                phase5.verify_manifest_golden_style(golden_style, manifest_path)
            second_path.write_bytes(original_second)
            manifest_path.write_text(json.dumps(original_manifest), encoding="utf-8")
            Image.new("RGB", (32, 24), "black").save(master)
            with self.assertRaisesRegex(phase5.Phase5BuildError, "sha256 mismatch"):
                phase5.verify_manifest_golden_style(golden_style, manifest_path)

    def test_manifest_golden_style_v2_rejects_rehashed_lineage_png_metadata(self):
        fixture = golden_v2_fixture.PromotionFixture()
        try:
            fixture.prepare()
            reviews = [fixture.root / "review-a.json", fixture.root / "review-b.json"]
            fixture.build_review(
                reviews[0], "independent-vision-review-a/Reviewer Alpha"
            )
            fixture.build_review(
                reviews[1], "independent-vision-review-b/Reviewer Beta"
            )
            golden_v2_fixture.promotion.accept_promotion(
                review_paths=reviews,
                authorized_by="Phase 5 fixture",
                paths=fixture.paths,
            )

            renderer_calls: list[list[str]] = []
            original_run = golden_v2_fixture.promotion.subprocess.run

            def observe_renderer(*args: object, **kwargs: object) -> object:
                command = args[0]
                if (
                    isinstance(command, list)
                    and len(command) >= 2
                    and command[0] == sys.executable
                    and command[1]
                    == phase5.repo_path(
                        golden_v2_fixture.promotion.READ_CLOSURE_RUNNER_PATH
                    )
                ):
                    renderer_calls.append(command)
                return original_run(*args, **kwargs)

            replay_root = REPO_ROOT / "tmp/map-production/k3-golden-v2-replay"
            before_runs = (
                set(replay_root.glob("run-*")) if replay_root.exists() else set()
            )
            with patch.object(
                golden_v2_fixture.promotion.subprocess,
                "run",
                side_effect=observe_renderer,
            ):
                evidence = phase5.verify_manifest_golden_style(
                    artifact(fixture.paths.final), fixture.manifest
                )
            self.assertEqual(len(renderer_calls), 2)
            self.assertEqual(
                set(replay_root.glob("run-*")) if replay_root.exists() else set(),
                before_runs,
            )
            self.assertEqual(len(evidence["blind_packet_views"]), 5)
            self.assertEqual(len(evidence["manifest_vision_reports"]), 2)

            # Re-encode identical native pixels with the two required fields
            # plus a hidden lineage field, then consistently rewrite every
            # downstream SHA. Pixel/hash-only validation would accept this.
            packet_path = next(fixture.paths.blind_packet_dir.glob("*.json"))
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            forged_view = fixture.root / "qa" / "blind-packets" / "forged-native.png"
            forged_view.parent.mkdir(parents=True, exist_ok=True)
            source_view = phase5.resolve_repo_artifact(
                packet["views"][0]["path"], "source anonymous native view"
            )
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text("sstory-blind-contract", "phase4-v2")
            metadata.add_text("sstory-blind-view", "native")
            metadata.add_text("lineage", "forbidden-source")
            with Image.open(source_view) as source_image:
                source_image.save(
                    forged_view,
                    format="PNG",
                    compress_level=9,
                    optimize=False,
                    pnginfo=metadata,
                )
            packet["views"][0] = {"id": "native", **artifact(forged_view)}
            packet_payload = json.dumps(packet).encode("utf-8")
            packet_sha = hashlib.sha256(packet_payload).hexdigest()
            packet_path = packet_path.with_name(f"{packet_sha}.json")
            packet_path.write_bytes(packet_payload)
            packet_artifact = artifact(packet_path)

            provenance = json.loads(fixture.paths.receipt.read_text(encoding="utf-8"))
            provenance["blind_packet"] = packet_artifact
            fixture.paths.receipt.write_text(json.dumps(provenance), encoding="utf-8")
            provenance_sha = digest(fixture.paths.receipt)

            audit = json.loads(fixture.paths.audit.read_text(encoding="utf-8"))
            audit["blind_packet"] = packet_artifact
            audit["provenance_receipt"]["sha256"] = provenance_sha
            fixture.paths.audit.write_text(json.dumps(audit), encoding="utf-8")
            audit_sha = digest(fixture.paths.audit)

            review_shas: dict[str, str] = {}
            for review_path in reviews:
                review = json.loads(review_path.read_text(encoding="utf-8"))
                review["image_path"] = packet_artifact["path"]
                review["image_sha256"] = packet_sha
                review_path.write_text(json.dumps(review), encoding="utf-8")
                review_shas[phase5.repo_path(review_path)] = digest(review_path)

            acceptance = json.loads(
                fixture.paths.final_receipt.read_text(encoding="utf-8")
            )
            acceptance["blind_packet"] = packet_artifact
            acceptance["promotion_provenance"]["sha256"] = provenance_sha
            acceptance["automated_audit"]["sha256"] = audit_sha
            for review in acceptance["reviews"]:
                review["sha256"] = review_shas[review["path"]]
            fixture.paths.final_receipt.write_text(
                json.dumps(acceptance), encoding="utf-8"
            )
            acceptance_sha = digest(fixture.paths.final_receipt)

            manifest = json.loads(fixture.manifest.read_text(encoding="utf-8"))
            job = manifest["jobs"][0]
            rewritten = {
                "promotion-provenance": provenance_sha,
                "persistent-automated-audit": audit_sha,
                "golden-acceptance-receipt": acceptance_sha,
                **{
                    role: review_shas[path]
                    for role, path in zip(
                        phase5.INDEPENDENT_VISION_REVIEW_ROLES,
                        (phase5.repo_path(path) for path in reviews),
                    )
                },
            }
            for input_spec in job["inputs"]:
                if input_spec["role"] == "blind-review-packet":
                    input_spec.update(packet_artifact)
                if input_spec["role"] in rewritten:
                    input_spec["sha256"] = rewritten[input_spec["role"]]
            fixture.manifest.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(
                phase5.Phase5BuildError, "anonymous PNG metadata/chunk contract"
            ):
                phase5.verify_manifest_golden_style(
                    artifact(fixture.paths.final), fixture.manifest
                )
        finally:
            fixture.cleanup()

    def test_manifest_golden_style_v2_rejects_passing_value_metric_forgery(self):
        fixture = golden_v2_fixture.PromotionFixture()
        try:
            fixture.prepare()
            reviews = [fixture.root / "review-a.json", fixture.root / "review-b.json"]
            fixture.build_review(
                reviews[0], "independent-vision-review-a/Reviewer Alpha"
            )
            fixture.build_review(
                reviews[1], "independent-vision-review-b/Reviewer Beta"
            )
            golden_v2_fixture.promotion.accept_promotion(
                review_paths=reviews,
                authorized_by="Phase 5 fixture",
                paths=fixture.paths,
            )

            provenance = json.loads(fixture.paths.receipt.read_text(encoding="utf-8"))
            # Keep the forged value above the fixed gate.  A threshold-only
            # validator would accept this passing claim, but the Phase 5
            # validator must require exact equality with recomputed pixels.
            provenance["metrics"]["coverage_50"] += 1
            fixture.paths.receipt.write_text(json.dumps(provenance), encoding="utf-8")
            provenance_sha = digest(fixture.paths.receipt)

            audit = json.loads(fixture.paths.audit.read_text(encoding="utf-8"))
            audit["metrics"]["coverage_50"] = provenance["metrics"]["coverage_50"]
            audit["provenance_receipt"]["sha256"] = provenance_sha
            fixture.paths.audit.write_text(json.dumps(audit), encoding="utf-8")
            audit_sha = digest(fixture.paths.audit)

            acceptance = json.loads(
                fixture.paths.final_receipt.read_text(encoding="utf-8")
            )
            acceptance["promotion_provenance"]["sha256"] = provenance_sha
            acceptance["automated_audit"]["sha256"] = audit_sha
            fixture.paths.final_receipt.write_text(
                json.dumps(acceptance), encoding="utf-8"
            )
            acceptance_sha = digest(fixture.paths.final_receipt)

            manifest = json.loads(fixture.manifest.read_text(encoding="utf-8"))
            rewritten = {
                "promotion-provenance": provenance_sha,
                "persistent-automated-audit": audit_sha,
                "golden-acceptance-receipt": acceptance_sha,
            }
            for input_spec in manifest["jobs"][0]["inputs"]:
                if input_spec["role"] in rewritten:
                    input_spec["sha256"] = rewritten[input_spec["role"]]
            fixture.manifest.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(
                phase5.Phase5BuildError, "independently recomputed pixels"
            ):
                phase5.verify_manifest_golden_style(
                    artifact(fixture.paths.final), fixture.manifest
                )
        finally:
            fixture.cleanup()

    def test_manifest_golden_style_refuses_partial_v2_legacy_fallback(self):
        fixture = golden_v2_fixture.PromotionFixture()
        try:
            fixture.prepare()
            reviews = [fixture.root / "review-a.json", fixture.root / "review-b.json"]
            fixture.build_review(
                reviews[0], "independent-vision-review-a/Reviewer Alpha"
            )
            fixture.build_review(
                reviews[1], "independent-vision-review-b/Reviewer Beta"
            )
            golden_v2_fixture.promotion.accept_promotion(
                review_paths=reviews,
                authorized_by="Phase 5 fixture",
                paths=fixture.paths,
            )

            # Re-point both reviews at the master so the legacy v1 validator
            # would otherwise accept them, then remove only the v2 acceptance
            # receipt and blind packet roles.  Eleven prepared v2 roles remain
            # and must make fallback impossible.
            review_digests: dict[str, str] = {}
            for review_path in reviews:
                report = json.loads(review_path.read_text(encoding="utf-8"))
                report["image_path"] = phase5.repo_path(fixture.paths.final)
                report["image_sha256"] = digest(fixture.paths.final)
                review_path.write_text(json.dumps(report), encoding="utf-8")
                review_digests[phase5.repo_path(review_path)] = digest(review_path)

            manifest = json.loads(fixture.manifest.read_text(encoding="utf-8"))
            job = manifest["jobs"][0]
            job["inputs"] = [
                item
                for item in job["inputs"]
                if item["role"]
                not in {
                    phase5.GOLDEN_ACCEPTANCE_RECEIPT_ROLE,
                    phase5.GOLDEN_BLIND_PACKET_ROLE,
                }
            ]
            for item in job["inputs"]:
                if item["role"] in phase5.INDEPENDENT_VISION_REVIEW_ROLES:
                    item["sha256"] = review_digests[item["path"]]
            remaining_prepared = {
                item["role"]
                for item in job["inputs"]
                if item["role"] in golden_v2_fixture.promotion.PREPARED_INPUT_ROLES
            }
            self.assertEqual(len(remaining_prepared), 11)
            fixture.manifest.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(
                phase5.Phase5BuildError,
                "v2 evidence is incomplete; refusing legacy fallback",
            ):
                phase5.verify_manifest_golden_style(
                    artifact(fixture.paths.final), fixture.manifest
                )
        finally:
            fixture.cleanup()

    def test_selected_golden_binding_skips_unrelated_rejected_history(self):
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            golden = root / "golden.png"
            Image.new("RGB", (32, 24), "gold").save(golden)
            manifest_path, _ = write_golden_manifest_with_two_reviews(
                root, master=golden
            )

            stale_target = root / "historical-script.py"
            stale_target.write_text("# current historical script\n", encoding="utf-8")
            stale_report = root / "historical-report.json"
            stale_report.write_text(
                json.dumps(
                    {
                        "implementation": {
                            "script_path": phase5.repo_path(stale_target),
                            "script_sha256": "0" * 64,
                        }
                    }
                ),
                encoding="utf-8",
            )
            rejected_master = root / "rejected.png"
            Image.new("RGB", (8, 8), "black").save(rejected_master)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["jobs"].append(
                {
                    "id": "historical-rejected-v1",
                    "status": "rejected",
                    "master": artifact(rejected_master),
                    "inputs": [
                        {
                            **artifact(stale_report),
                            "role": "historical-preflight",
                        }
                    ],
                }
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            manifest_binding = bound_artifacts.bind_file(
                manifest_path, label="aggregate base manifest"
            )

            with self.assertRaisesRegex(
                phase5.Phase5BuildError, "historical-report.*hash mismatch"
            ):
                phase5.bind_phase5_artifact_graph((manifest_binding,))

            registry = phase5.bind_manifest_golden_evidence(
                artifact(golden), manifest_binding
            )
            with phase5.bound_artifact_context(registry):
                evidence = phase5.verify_manifest_golden_style(
                    artifact(golden), manifest_path
                )

            self.assertEqual(evidence["job_id"], "golden-style-fixture-v1")
            self.assertIn(manifest_binding.identity, registry)
            self.assertNotIn(bound_artifacts.path_identity(stale_report), registry)
            self.assertNotIn(bound_artifacts.path_identity(stale_target), registry)

    def test_selected_golden_and_manifest_bindings_detect_late_mutation(self):
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            golden = root / "golden.png"
            Image.new("RGB", (32, 24), "gold").save(golden)
            manifest_path, review_specs = write_golden_manifest_with_two_reviews(
                root, master=golden
            )
            manifest_binding = bound_artifacts.bind_file(
                manifest_path, label="mutation-checked base manifest"
            )
            registry = phase5.bind_manifest_golden_evidence(
                artifact(golden), manifest_binding
            )
            second_review = phase5.resolve_repo_artifact(
                review_specs[1]["path"], "selected second Golden review"
            )

            for target in (manifest_path, second_review):
                with self.subTest(target=target.name):
                    original = target.read_bytes()
                    metadata = target.stat()
                    try:
                        target.write_bytes(b"x" * len(original))
                        os.utime(
                            target,
                            ns=(metadata.st_atime_ns, metadata.st_mtime_ns),
                        )
                        with self.assertRaisesRegex(
                            phase5.Phase5BuildError, "changed after.*snapshot"
                        ):
                            phase5._assert_bound_registry_unchanged(registry)
                    finally:
                        target.write_bytes(original)
                        os.utime(
                            target,
                            ns=(metadata.st_atime_ns, metadata.st_mtime_ns),
                        )
                    phase5._assert_bound_registry_unchanged(registry)

    def test_plan_with_source_index_locks_every_receipt_to_manifest_golden(self):
        sheet_id = "sheet_region_moonlit_forest_region"
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            golden = root / "golden.png"
            Image.new("RGB", (32, 24), "gold").save(golden)
            golden_style = artifact(golden)
            manifest_path, _ = write_golden_manifest(root, master=golden)
            tile, receipt_spec = write_generation_receipt(
                root,
                sheet_id=sheet_id,
                column=0,
                row=0,
                golden_style=golden_style,
            )
            source_index = {
                "schema_version": "1.3.0",
                "coordinate_reference_system": "EA-WORLD-1",
                "golden_style": golden_style,
                "sources": [
                    {
                        "sheet_id": sheet_id,
                        "kind": "metatiles",
                        "tiles": [
                            {
                                "column": 0,
                                "row": 0,
                                **tile,
                                "receipt": receipt_spec,
                            }
                        ],
                    }
                ],
            }
            source_index_path = root / "source-index.json"
            source_index_path.write_text(json.dumps(source_index), encoding="utf-8")
            args = phase5.build_parser().parse_args(
                [
                    "plan",
                    "--base-manifest",
                    str(manifest_path),
                    "--source-index",
                    str(source_index_path),
                ]
            )
            result = phase5.execute_build(args)
            self.assertTrue(result["valid"])
            self.assertEqual(result["golden_style_job_id"], "golden-style-fixture-v1")
            action = next(
                item for item in result["actions"] if item["sheet_id"] == sheet_id
            )
            self.assertEqual(action["action"], "guarded-metatile-assembly")

            receipt_path = phase5.resolve_repo_artifact(
                receipt_spec["path"], "Golden mismatch receipt"
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            golden_input = next(
                item for item in receipt["inputs"] if item["role"] == "golden-style"
            )
            golden_input.update(receipt["prompt"])
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            source_index["sources"][0]["tiles"][0]["receipt"]["sha256"] = digest(
                receipt_path
            )
            source_index_path.write_text(json.dumps(source_index), encoding="utf-8")
            with self.assertRaisesRegex(
                phase5.Phase5BuildError, "does not match source index golden_style"
            ):
                phase5.execute_build(args)

    def test_generation_receipt_cross_links_fail_closed_under_tampering(self):
        sheet_id = "sheet_region_receipt_test"
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            tile, receipt_spec = write_generation_receipt(
                root, sheet_id=sheet_id, column=0, row=0
            )
            entry = {
                "kind": "metatiles",
                "tiles": [{"column": 0, "row": 0, **tile, "receipt": receipt_spec}],
            }
            plan = {"metatile_size_px": 2048}
            phase5.verify_generation_receipts(entry, sheet_id=sheet_id, plan=plan)
            receipt_path = phase5.resolve_repo_artifact(
                receipt_spec["path"], "test receipt"
            )
            original = json.loads(receipt_path.read_text(encoding="utf-8"))
            golden_input = next(
                item for item in original["inputs"] if item["role"] == "golden-style"
            )
            phase5.verify_generation_receipts(
                entry,
                sheet_id=sheet_id,
                plan=plan,
                golden_style=golden_input,
            )
            with self.assertRaisesRegex(
                phase5.Phase5BuildError, "does not match source index golden_style"
            ):
                phase5.verify_generation_receipts(
                    entry,
                    sheet_id=sheet_id,
                    plan=plan,
                    golden_style=tile,
                )

            cases = [
                (
                    "coordinate",
                    lambda value: value.__setitem__("column", 1),
                    "coordinates",
                ),
                (
                    "attempt",
                    lambda value: value.__setitem__("attempt", 6),
                    "invalid",
                ),
                (
                    "generation-order",
                    lambda value: value.__setitem__("generation_order", "column-major"),
                    "invalid",
                ),
                (
                    "single-change",
                    lambda value: value["single_change"].__setitem__(
                        "confirmed", False
                    ),
                    "invalid",
                ),
                (
                    "tool-mode",
                    lambda value: value["tool"].__setitem__("mode", "manual-cli"),
                    "invalid",
                ),
                (
                    "actual-dimensions",
                    lambda value: value["actual_output"].__setitem__("width", 1024),
                    "invalid",
                ),
                (
                    "input-hash",
                    lambda value: value["inputs"][0].__setitem__("sha256", "0" * 64),
                    "sha256 mismatch",
                ),
                (
                    "raw-is-final",
                    lambda value: value.__setitem__("raw_output", value["output"]),
                    "must be distinct",
                ),
                (
                    "postprocess-report-hash",
                    lambda value: value["postprocess"]["report"].__setitem__(
                        "sha256", "0" * 64
                    ),
                    "sha256 mismatch",
                ),
                (
                    "output-path",
                    lambda value: value.__setitem__("output", value["prompt"]),
                    "output does not match",
                ),
                (
                    "boundary-neighbor",
                    lambda value: (
                        value["neighbors"].__setitem__("north", value["control"]),
                        value["inputs"].append(
                            {"role": "neighbor-north", **value["control"]}
                        ),
                    ),
                    "lock absence",
                ),
            ]
            for name, mutate, message in cases:
                with self.subTest(name=name):
                    changed = copy.deepcopy(original)
                    mutate(changed)
                    receipt_path.write_text(json.dumps(changed), encoding="utf-8")
                    entry["tiles"][0]["receipt"]["sha256"] = digest(receipt_path)
                    with self.assertRaisesRegex(phase5.Phase5BuildError, message):
                        phase5.verify_generation_receipts(
                            entry, sheet_id=sheet_id, plan=plan
                        )

            postprocess_path = phase5.resolve_repo_artifact(
                original["postprocess"]["report"]["path"],
                "postprocess fixture report",
            )
            postprocess = json.loads(postprocess_path.read_text(encoding="utf-8"))
            postprocess["output"]["sha256"] = "0" * 64
            postprocess_path.write_text(json.dumps(postprocess), encoding="utf-8")
            changed = copy.deepcopy(original)
            changed["postprocess"]["report"]["sha256"] = digest(postprocess_path)
            receipt_path.write_text(json.dumps(changed), encoding="utf-8")
            entry["tiles"][0]["receipt"]["sha256"] = digest(receipt_path)
            with self.assertRaisesRegex(phase5.Phase5BuildError, "stale or mismatched"):
                phase5.verify_generation_receipts(entry, sheet_id=sheet_id, plan=plan)

    def test_automated_qa_is_recomputed_and_rejects_stale_claims(self):
        sheet = {
            "id": "sheet_continent_automated_test",
            "sheet_type": "continent",
        }
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            master = root / "master.png"
            Image.new("RGB", (8, 8), "white").save(master)
            provenance = write_provenance_report(
                root,
                sheet_id=sheet["id"],
                master=master,
            )
            report_spec = write_automated_report(
                root,
                sheet_id=sheet["id"],
                master=master,
                provenance=provenance,
                source_kind="master",
            )
            report_path = phase5.resolve_repo_artifact(
                report_spec["path"], "automated test report"
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            entry = {
                "sheet_id": sheet["id"],
                "kind": "master",
                **artifact(master),
                "provenance_report": provenance,
            }
            kwargs = {
                "entry": entry,
                "sheet": sheet,
                "master_path": phase5.repo_path(master),
                "job_id": phase5.job_id_for_sheet(sheet["id"]),
                "contract": {"width": 8, "height": 8},
            }
            phase5.validate_automated_qa_report(report, **kwargs)

            cases = [
                (
                    "master-digest",
                    lambda value: value["master"].__setitem__("sha256", "0" * 64),
                    "master path or digest",
                ),
                (
                    "provenance",
                    lambda value: value["provenance_report"].__setitem__(
                        "sha256", "0" * 64
                    ),
                    "not the reviewed provenance",
                ),
                (
                    "coverage",
                    lambda value: value["checks"]["coverage"].__setitem__(
                        "covered_pixel_count", 63
                    ),
                    "coverage is inconsistent",
                ),
                (
                    "fake-seam",
                    lambda value: value["checks"]["seams"].__setitem__(
                        "expected_count", 1
                    ),
                    "seams is inconsistent",
                ),
                (
                    "land-ratio",
                    lambda value: value["geography"]["land_sea"].__setitem__(
                        "match_ratio", 0.99
                    ),
                    "land/sea mask evidence",
                ),
                (
                    "transport-ratio",
                    lambda value: value["geography"]["transport"].__setitem__(
                        "control_within_tolerance_ratio", 0.99
                    ),
                    "transport mask evidence",
                ),
            ]
            for name, mutate, message in cases:
                with self.subTest(name=name):
                    changed = copy.deepcopy(report)
                    mutate(changed)
                    with self.assertRaisesRegex(phase5.Phase5BuildError, message):
                        phase5.validate_automated_qa_report(changed, **kwargs)

            observed_path = phase5.resolve_repo_artifact(
                report["geography"]["land_sea"]["observed"]["path"],
                "observed mask",
            )
            Image.new("L", (8, 8), 0).save(observed_path)
            with self.assertRaisesRegex(phase5.Phase5BuildError, "sha256 mismatch"):
                phase5.validate_automated_qa_report(report, **kwargs)

    def test_row_major_receipts_use_only_north_and_west_generation_inputs(self):
        sheet_id = "sheet_region_row_major_test"
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            tile_records: dict[tuple[int, int], dict] = {}
            for row in range(2):
                for column in range(2):
                    tile, receipt = write_generation_receipt(
                        root, sheet_id=sheet_id, column=column, row=row
                    )
                    tile_records[(column, row)] = {
                        "column": column,
                        "row": row,
                        **tile,
                        "receipt": receipt,
                    }

            for (column, row), record in tile_records.items():
                receipt_path = phase5.resolve_repo_artifact(
                    record["receipt"]["path"], "row-major receipt"
                )
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                for direction, neighbor_position, role in (
                    ("north", (column, row - 1), "neighbor-north"),
                    ("west", (column - 1, row), "neighbor-west"),
                ):
                    neighbor = tile_records.get(neighbor_position)
                    if neighbor is None:
                        continue
                    neighbor_artifact = {
                        "path": neighbor["path"],
                        "sha256": neighbor["sha256"],
                    }
                    receipt["neighbors"][direction] = neighbor_artifact
                    receipt["inputs"].append({"role": role, **neighbor_artifact})
                receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
                record["receipt"]["sha256"] = digest(receipt_path)

            entry = {"kind": "metatiles", "tiles": list(tile_records.values())}
            plan = {"metatile_size_px": 2048}
            phase5.verify_generation_receipts(entry, sheet_id=sheet_id, plan=plan)

            first = tile_records[(0, 0)]
            first_receipt_path = phase5.resolve_repo_artifact(
                first["receipt"]["path"], "first row-major receipt"
            )
            first_receipt = json.loads(first_receipt_path.read_text(encoding="utf-8"))
            future = tile_records[(1, 0)]
            future_artifact = {"path": future["path"], "sha256": future["sha256"]}
            first_receipt["neighbors"]["east"] = future_artifact
            first_receipt["inputs"].append(
                {"role": "continuation-reference", **future_artifact}
            )
            first_receipt_path.write_text(json.dumps(first_receipt), encoding="utf-8")
            first["receipt"]["sha256"] = digest(first_receipt_path)
            with self.assertRaisesRegex(phase5.Phase5BuildError, "future row-major"):
                phase5.verify_generation_receipts(entry, sheet_id=sheet_id, plan=plan)

            first_receipt["neighbors"]["east"] = None
            first_receipt["inputs"] = [
                item
                for item in first_receipt["inputs"]
                if item["role"] != "continuation-reference"
            ]
            future_receipt_path = phase5.resolve_repo_artifact(
                future["receipt"]["path"], "future raw receipt"
            )
            future_receipt = json.loads(future_receipt_path.read_text(encoding="utf-8"))
            first_receipt["inputs"].append(
                {
                    "role": "continuation-reference",
                    **future_receipt["raw_output"],
                }
            )
            first_receipt_path.write_text(json.dumps(first_receipt), encoding="utf-8")
            first["receipt"]["sha256"] = digest(first_receipt_path)
            with self.assertRaisesRegex(phase5.Phase5BuildError, "future row-major"):
                phase5.verify_generation_receipts(entry, sheet_id=sheet_id, plan=plan)
            first_receipt["inputs"] = [
                item
                for item in first_receipt["inputs"]
                if item["role"] != "continuation-reference"
            ]
            first_receipt_path.write_text(json.dumps(first_receipt), encoding="utf-8")
            first["receipt"]["sha256"] = digest(first_receipt_path)
            last = tile_records[(1, 1)]
            last_receipt_path = phase5.resolve_repo_artifact(
                last["receipt"]["path"], "last row-major receipt"
            )
            last_receipt = json.loads(last_receipt_path.read_text(encoding="utf-8"))
            last_receipt["neighbors"]["west"] = None
            last_receipt["inputs"] = [
                item
                for item in last_receipt["inputs"]
                if item["role"] != "neighbor-west"
            ]
            last_receipt_path.write_text(json.dumps(last_receipt), encoding="utf-8")
            last["receipt"]["sha256"] = digest(last_receipt_path)
            with self.assertRaisesRegex(phase5.Phase5BuildError, "does not match"):
                phase5.verify_generation_receipts(entry, sheet_id=sheet_id, plan=plan)

    def test_noop_protected_composite_allows_same_digest_on_distinct_paths(self):
        sheet_id = "sheet_region_noop_composite_test"
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            tile, receipt_spec = write_generation_receipt(
                root, sheet_id=sheet_id, column=0, row=0
            )
            receipt_path = phase5.resolve_repo_artifact(
                receipt_spec["path"], "no-op receipt"
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            raw_path = phase5.resolve_repo_artifact(
                receipt["raw_output"]["path"], "no-op raw output"
            )
            final_path = phase5.resolve_repo_artifact(
                receipt["output"]["path"], "no-op final output"
            )
            shutil.copyfile(final_path, raw_path)
            receipt["raw_output"]["sha256"] = digest(raw_path)
            postprocess_path = phase5.resolve_repo_artifact(
                receipt["postprocess"]["report"]["path"],
                "no-op postprocess report",
            )
            postprocess = json.loads(postprocess_path.read_text(encoding="utf-8"))
            postprocess["raw_output"]["sha256"] = digest(raw_path)
            postprocess_path.write_text(json.dumps(postprocess), encoding="utf-8")
            receipt["postprocess"]["report"]["sha256"] = digest(postprocess_path)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            receipt_spec["sha256"] = digest(receipt_path)
            entry = {
                "kind": "metatiles",
                "tiles": [{"column": 0, "row": 0, **tile, "receipt": receipt_spec}],
            }
            self.assertEqual(
                receipt["raw_output"]["sha256"], receipt["output"]["sha256"]
            )
            self.assertNotEqual(
                receipt["raw_output"]["path"], receipt["output"]["path"]
            )
            phase5.verify_generation_receipts(
                entry, sheet_id=sheet_id, plan={"metatile_size_px": 2048}
            )

    def test_band_and_geography_algorithms_reject_failed_evidence(self):
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            banded = Image.new("RGB", (100, 100), "white")
            for x in range(100):
                banded.putpixel((x, 0), (0, 0, 0))
            banded_path = root / "banded.png"
            banded.save(banded_path)
            metrics = phase5.unpainted_band_metrics(banded_path, "banded fixture")
            self.assertEqual(metrics["fully_black_row_count"], 1)
            self.assertEqual(metrics["black_band_count"], 1)

            land_control = Image.new("L", (100, 100), 255)
            land_observed = land_control.copy()
            for x in range(100):
                for y in range(3):
                    land_observed.putpixel((x, y), 0)
            self.assertLess(
                phase5.land_sea_match_ratio(land_control, land_observed),
                phase5.MINIMUM_LAND_SEA_MATCH_RATIO,
            )
            land_control.close()
            land_observed.close()

            route_control = Image.new("L", (100, 100), 0)
            route_observed = Image.new("L", (100, 100), 0)
            for y in range(100):
                route_control.putpixel((10, y), 255)
                route_observed.putpixel((30, y), 255)
            ratios = phase5.transport_within_tolerance_ratios(
                route_control, route_observed, 8
            )
            route_control.close()
            route_observed.close()
            self.assertLess(ratios[0], phase5.MINIMUM_TRANSPORT_WITHIN_TOLERANCE_RATIO)
            self.assertLess(ratios[1], phase5.MINIMUM_TRANSPORT_WITHIN_TOLERANCE_RATIO)

    def test_auditor_cli_requires_all_geometry_mask_evidence(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                phase5_audit.build_parser().parse_args(
                    [
                        "--sheet-id",
                        "sheet_region_emerald_plains_region",
                        "--source-kind",
                        "master",
                        "--master",
                        "master.png",
                        "--provenance-report",
                        "provenance.json",
                        "--output",
                        "qa.json",
                    ]
                )

    def test_auditor_builds_a_strict_report_from_real_contract_fixture(self):
        sheet_id = "sheet_region_port_zephia_region"
        contract = self.contracts[sheet_id]
        plan = phase5.metatile_plan(contract)
        self.assertIsNotNone(plan)
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            first_tile, first_receipt = write_generation_receipt(
                root, sheet_id=sheet_id, column=0, row=0
            )
            second_tile, second_receipt = write_generation_receipt(
                root, sheet_id=sheet_id, column=1, row=0
            )
            for receipt_spec, direction, neighbor, role in (
                (second_receipt, "west", first_tile, "neighbor-west"),
            ):
                receipt_path = phase5.resolve_repo_artifact(
                    receipt_spec["path"], "fixture receipt"
                )
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                receipt["neighbors"][direction] = neighbor
                receipt["inputs"].append({"role": role, **neighbor})
                receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
                receipt_spec["sha256"] = digest(receipt_path)

            master = root / "master.png"
            Image.new("RGB", (contract["width"], contract["height"]), "white").save(
                master
            )
            provenance = {
                "kind": "guarded-metatile-assembly",
                "inputs": [
                    {
                        "column": 0,
                        "row": 0,
                        **first_tile,
                        "receipt": first_receipt,
                    },
                    {
                        "column": 1,
                        "row": 0,
                        **second_tile,
                        "receipt": second_receipt,
                    },
                ],
                "seams": [
                    {
                        "axis": "x",
                        "column": 0,
                        "row": 0,
                        "effective_box_px": [
                            plan["stride_px"],
                            0,
                            plan["metatile_size_px"],
                            contract["height"],
                        ],
                        "ssim": 1.0,
                        "rgb_mean_abs_difference": 0.0,
                        "rgb_p95_abs_difference": 0,
                    }
                ],
                "minimum_overlap_ssim": 0.9,
                "maximum_rgb_mean_difference": 4.0,
                "maximum_rgb_p95_difference": 10,
            }
            provenance_report = {
                "schema_version": "1.0.0",
                "generated_by": phase5.GENERATOR_ID,
                "coordinate_reference_system": "EA-WORLD-1",
                "inputs": {
                    "catalog": artifact(phase5.DEFAULT_MAP_SHEETS),
                    "resolution_contract": artifact(phase5.DEFAULT_CONTRACT),
                    "control_master": artifact(phase5.DEFAULT_CONTROL_MASTER),
                    "style_master": None,
                },
                "artifacts": [
                    {
                        "sheet_id": sheet_id,
                        "path": master.name,
                        "sha256": digest(master),
                        "width": contract["width"],
                        "height": contract["height"],
                        "method": "guarded-metatile-assembly",
                        "provenance": provenance,
                    }
                ],
            }
            provenance_path = root / "build-report.json"
            provenance_path.write_text(json.dumps(provenance_report), encoding="utf-8")
            land_mask = root / "land.png"
            route_mask = root / "route.png"
            Image.new("L", (contract["width"], contract["height"]), 255).save(land_mask)
            Image.new("L", (contract["width"], contract["height"]), 255).save(
                route_mask
            )

            report = phase5_audit.audit_phase5_master(
                sheet_id=sheet_id,
                source_kind="master",
                master_path=master,
                provenance_path=provenance_path,
                land_sea_control_path=land_mask,
                land_sea_observed_path=land_mask,
                transport_control_path=route_mask,
                transport_observed_path=route_mask,
                transport_tolerance_px=0,
            )
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["checks"]["seams"]["evaluated_count"], 1)
            self.assertEqual(report["checks"]["seams"]["minimum_observed_ssim"], 1.0)

            missing_seam = copy.deepcopy(provenance)
            missing_seam["seams"] = []
            with self.assertRaisesRegex(phase5.Phase5BuildError, "coverage mismatch"):
                phase5._verify_assembly_provenance(
                    missing_seam,
                    sheet_id=sheet_id,
                    contract=contract,
                    label="missing seam fixture",
                )
            duplicate_seam = copy.deepcopy(provenance)
            duplicate_seam["seams"].append(copy.deepcopy(duplicate_seam["seams"][0]))
            with self.assertRaisesRegex(
                phase5.Phase5BuildError, "duplicates effective seam"
            ):
                phase5._verify_assembly_provenance(
                    duplicate_seam,
                    sheet_id=sheet_id,
                    contract=contract,
                    label="duplicate seam fixture",
                )
            wrong_box = copy.deepcopy(provenance)
            wrong_box["seams"][0]["effective_box_px"][1] = 1
            with self.assertRaisesRegex(
                phase5.Phase5BuildError, "does not match the plan"
            ):
                phase5._verify_assembly_provenance(
                    wrong_box,
                    sheet_id=sheet_id,
                    contract=contract,
                    label="wrong seam box fixture",
                )

    def test_composite_job_records_hashed_child_master_inputs(self):
        parent_sheet = self.catalog_by_id["sheet_world"]
        child_sheet = self.catalog_by_id["sheet_continent_elysion"]
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            parent_path = root / "parent.png"
            child_path = root / "child.png"
            Image.new("RGB", (2, 2), "navy").save(parent_path)
            Image.new("RGB", (2, 2), "green").save(child_path)
            child = phase5.BuiltAsset(
                sheet=child_sheet,
                contract=self.contracts[child_sheet["id"]],
                job_id=phase5.job_id_for_sheet(child_sheet["id"]),
                method="deterministic-parent-composite",
                stage_path=child_path,
                final_manifest_path=phase5.repo_path(child_path),
                sha256=digest(child_path),
                provisional=True,
            )
            parent = phase5.BuiltAsset(
                sheet=parent_sheet,
                contract=self.contracts[parent_sheet["id"]],
                job_id=phase5.job_id_for_sheet(parent_sheet["id"]),
                method="deterministic-parent-composite",
                stage_path=parent_path,
                final_manifest_path=phase5.repo_path(parent_path),
                sha256=digest(parent_path),
                source_entry={"composite_children": [child_sheet["id"]]},
                provisional=True,
            )

            job = phase5.create_job(
                parent,
                assets_by_sheet={
                    parent_sheet["id"]: parent,
                    child_sheet["id"]: child,
                },
                catalog_path=phase5.DEFAULT_MAP_SHEETS,
                contract_path=phase5.DEFAULT_CONTRACT,
                control_master=phase5.DEFAULT_CONTROL_MASTER,
                style_master=None,
            )

            child_inputs = [
                item for item in job["inputs"] if item["role"] == "child-sheet-master"
            ]
            self.assertEqual(len(child_inputs), 1)
            self.assertEqual(child_inputs[0]["sha256"], digest(child_path))

    def test_metatile_plan_crops_gutters_into_exact_contract_dimensions(self):
        corridor = self.contracts["sheet_corridor_astralis_port_zephia"]
        plan = phase5.metatile_plan(corridor)

        self.assertIsNotNone(plan)
        self.assertEqual(plan["count"], 15)
        self.assertEqual(plan["master_size"], [7210, 3932])
        self.assertEqual(plan["tiles"][0]["canvas_origin_px"], [0, 0])
        self.assertEqual(plan["tiles"][0]["source_core_box_px"], [0, 0, 1792, 1792])
        self.assertEqual(plan["tiles"][-1]["canvas_origin_px"], [6144, 3072])
        self.assertEqual(
            plan["tiles"][-1]["destination_box_px"], [6400, 3328, 7210, 3932]
        )
        self.assertEqual(plan["tiles"][-1]["source_core_box_px"], [256, 256, 1066, 860])

    def test_every_generation_plan_covers_master_without_gap_or_overlap(self):
        formerly_broken = {
            "sheet_region_moonlit_forest_region",
            "sheet_region_lumiera_arch_region",
            "sheet_region_emerald_belt_region",
            "sheet_region_marineport_region",
            "sheet_settlement_astralis",
            "sheet_settlement_port_zephia",
        }
        checked = set()
        for sheet_id, contract in self.contracts.items():
            plan = phase5.metatile_plan(contract)
            if plan is None:
                continue
            boxes = [tuple(record["destination_box_px"]) for record in plan["tiles"]]
            area = sum(
                (right - left) * (bottom - top) for left, top, right, bottom in boxes
            )
            self.assertEqual(area, contract["width"] * contract["height"], sheet_id)
            for index, box in enumerate(boxes):
                left, top, right, bottom = box
                self.assertGreaterEqual(left, 0, sheet_id)
                self.assertGreaterEqual(top, 0, sheet_id)
                self.assertLessEqual(right, contract["width"], sheet_id)
                self.assertLessEqual(bottom, contract["height"], sheet_id)
                for other in boxes[index + 1 :]:
                    overlap_width = min(right, other[2]) - max(left, other[0])
                    overlap_height = min(bottom, other[3]) - max(top, other[1])
                    self.assertFalse(
                        overlap_width > 0 and overlap_height > 0,
                        f"{sheet_id} overlaps {box} and {other}",
                    )
            if sheet_id in formerly_broken:
                checked.add(sheet_id)
        self.assertEqual(checked, formerly_broken)

        moonlit = phase5.metatile_plan(
            self.contracts["sheet_region_moonlit_forest_region"]
        )
        self.assertEqual(moonlit["count"], 1)
        self.assertEqual(moonlit["tiles"][0]["source_core_box_px"], [0, 0, 1967, 1694])
        self.assertEqual(moonlit["tiles"][0]["destination_box_px"], [0, 0, 1967, 1694])

    def test_stitcher_uses_matching_overlap_and_emits_only_core_pixels(self):
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            left_path = root / "left.png"
            right_path = root / "right.png"
            output_path = root / "master.png"
            left = Image.new("RGB", (4, 4))
            right = Image.new("RGB", (4, 4))
            for x in range(4):
                for y in range(4):
                    left.putpixel((x, y), (x * 20, y * 10, 0))
                    right.putpixel(
                        (x, y),
                        ((x + 2) * 20, y * 10, 0) if y < 2 else (255, 0, 255),
                    )
            left.save(left_path)
            right.save(right_path)
            plan = {
                "sheet_id": "sheet_region_test",
                "master_size": [6, 2],
                "metatile_size_px": 4,
                "gutter_each_side_px": 1,
                "stride_px": 2,
                "columns": 2,
                "rows": 1,
                "count": 2,
                "tiles": [
                    {
                        "column": 0,
                        "row": 0,
                        "source_core_box_px": [0, 0, 3, 2],
                        "destination_box_px": [0, 0, 3, 2],
                    },
                    {
                        "column": 1,
                        "row": 0,
                        "source_core_box_px": [1, 0, 4, 2],
                        "destination_box_px": [3, 0, 6, 2],
                    },
                ],
            }
            result = phase5.stitch_metatiles(
                {
                    "kind": "metatiles",
                    "tiles": [
                        {"column": 0, "row": 0, **artifact(left_path)},
                        {"column": 1, "row": 0, **artifact(right_path)},
                    ],
                    phase5.INTERNAL_BOUND_ARTIFACTS_KEY: bound_registry(
                        left_path, right_path
                    ),
                },
                plan,
                output_path,
                minimum_ssim=0.99,
            )

            self.assertEqual(len(result["seams"]), 1)
            self.assertGreaterEqual(result["seams"][0]["ssim"], 0.99)
            self.assertEqual(result["seams"][0]["effective_box_px"], [2, 0, 4, 2])
            self.assertEqual(result["seams"][0]["rgb_mean_abs_difference"], 0)
            self.assertEqual(result["seams"][0]["rgb_p95_abs_difference"], 0)
            with Image.open(output_path) as stitched:
                self.assertEqual(stitched.size, (6, 2))
                self.assertEqual(
                    [stitched.getpixel((x, 0))[0] for x in range(6)],
                    [0, 20, 40, 60, 80, 100],
                )

    def test_stitcher_assembles_bound_bytes_when_live_metatile_changes_after_hash(self):
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            tile_path = root / "tile.png"
            output_path = root / "master.png"
            Image.new("RGB", (4, 4), "white").save(tile_path)
            original_bytes = tile_path.read_bytes()
            original_stat = tile_path.stat()
            binding = bound_artifacts.bind_file(tile_path, label="metatile fixture")
            entry = {
                "kind": "metatiles",
                "tiles": [{"column": 0, "row": 0, **artifact(tile_path)}],
                phase5.INTERNAL_BOUND_ARTIFACTS_KEY: {binding.identity: binding},
            }
            plan = {
                "sheet_id": "sheet_region_bound_snapshot",
                "master_size": [4, 4],
                "metatile_size_px": 4,
                "gutter_each_side_px": 0,
                "stride_px": 4,
                "columns": 1,
                "rows": 1,
                "count": 1,
                "tiles": [
                    {
                        "column": 0,
                        "row": 0,
                        "source_core_box_px": [0, 0, 4, 4],
                        "destination_box_px": [0, 0, 4, 4],
                    }
                ],
            }
            original_verify = phase5.verify_hashed_file
            swapped = False

            def swap_after_verification(spec, label):
                nonlocal swapped
                result = original_verify(spec, label)
                if not swapped and result[0] == tile_path.resolve():
                    Image.new("RGB", (4, 4), "black").save(tile_path)
                    os.utime(
                        tile_path,
                        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
                    )
                    swapped = True
                return result

            try:
                with patch.object(
                    phase5, "verify_hashed_file", side_effect=swap_after_verification
                ):
                    phase5.stitch_metatiles(
                        entry,
                        plan,
                        output_path,
                        minimum_ssim=0.99,
                    )
            finally:
                tile_path.write_bytes(original_bytes)
                os.utime(
                    tile_path,
                    ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
                )

            self.assertTrue(swapped)
            binding.assert_unchanged()
            with Image.open(output_path) as stitched:
                self.assertEqual(stitched.getpixel((0, 0)), (255, 255, 255))
                self.assertEqual(stitched.getpixel((3, 3)), (255, 255, 255))

    def test_create_job_records_bound_master_and_provenance_inputs(self):
        sheet = self.catalog_by_id["sheet_region_emerald_plains_region"]
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            master_path = root / "master.png"
            provenance_path = root / "provenance.json"
            Image.new("RGB", (4, 4), "white").save(master_path)
            provenance_path.write_text('{"state":"bound"}\n', encoding="utf-8")
            bindings = [
                bound_artifacts.bind_file(path, label=f"bound {path.name}")
                for path in (master_path, provenance_path)
            ]
            registry = {binding.identity: binding for binding in bindings}
            source_entry = {
                "kind": "master",
                **artifact(master_path),
                "provenance_report": artifact(provenance_path),
                phase5.INTERNAL_BOUND_ARTIFACTS_KEY: registry,
            }
            asset = phase5.BuiltAsset(
                sheet=sheet,
                contract=self.contracts[sheet["id"]],
                job_id=phase5.job_id_for_sheet(sheet["id"]),
                method="verified-master-import",
                stage_path=None,
                final_manifest_path=None,
                sha256=None,
                source_entry=source_entry,
            )
            originals = {
                path: (path.read_bytes(), path.stat())
                for path in (master_path, provenance_path)
            }
            try:
                for path, (data, metadata) in originals.items():
                    path.write_bytes(b"x" * len(data))
                    os.utime(
                        path,
                        ns=(metadata.st_atime_ns, metadata.st_mtime_ns),
                    )
                job = phase5.create_job(
                    asset,
                    assets_by_sheet={sheet["id"]: asset},
                    catalog_path=phase5.DEFAULT_MAP_SHEETS,
                    contract_path=phase5.DEFAULT_CONTRACT,
                    control_master=phase5.DEFAULT_CONTROL_MASTER,
                    style_master=None,
                )
            finally:
                for path, (data, metadata) in originals.items():
                    path.write_bytes(data)
                    os.utime(
                        path,
                        ns=(metadata.st_atime_ns, metadata.st_mtime_ns),
                    )

            records = {record["role"]: record for record in job["inputs"]}
            self.assertEqual(
                records["sheet-raster-source"],
                {**bindings[0].artifact(), "role": "sheet-raster-source"},
            )
            self.assertEqual(
                records["hash-locked-master-provenance"],
                {
                    **bindings[1].artifact(),
                    "role": "hash-locked-master-provenance",
                },
            )
            for binding in bindings:
                binding.assert_unchanged()

    def test_create_job_records_bound_metatile_inputs(self):
        sheet = self.catalog_by_id["sheet_region_emerald_plains_region"]
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            tile_path = Path(temporary) / "tile.png"
            Image.new("RGB", (4, 4), "white").save(tile_path)
            binding = bound_artifacts.bind_file(tile_path, label="bound metatile")
            source_entry = {
                "kind": "metatiles",
                "tiles": [{"column": 0, "row": 0, **artifact(tile_path)}],
                phase5.INTERNAL_BOUND_ARTIFACTS_KEY: {binding.identity: binding},
            }
            asset = phase5.BuiltAsset(
                sheet=sheet,
                contract=self.contracts[sheet["id"]],
                job_id=phase5.job_id_for_sheet(sheet["id"]),
                method="guarded-metatile-assembly",
                stage_path=None,
                final_manifest_path=None,
                sha256=None,
                source_entry=source_entry,
            )
            original_bytes = tile_path.read_bytes()
            original_stat = tile_path.stat()
            try:
                tile_path.write_bytes(b"x" * len(original_bytes))
                os.utime(
                    tile_path,
                    ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
                )
                job = phase5.create_job(
                    asset,
                    assets_by_sheet={sheet["id"]: asset},
                    catalog_path=phase5.DEFAULT_MAP_SHEETS,
                    contract_path=phase5.DEFAULT_CONTRACT,
                    control_master=phase5.DEFAULT_CONTROL_MASTER,
                    style_master=None,
                )
            finally:
                tile_path.write_bytes(original_bytes)
                os.utime(
                    tile_path,
                    ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
                )

            record = next(
                item
                for item in job["inputs"]
                if item["role"] == "guarded-imagegen-metatile"
            )
            self.assertEqual(
                record,
                {**binding.artifact(), "role": "guarded-imagegen-metatile"},
            )
            binding.assert_unchanged()

    def test_create_job_rejects_source_entry_without_byte_bindings(self):
        sheet = self.catalog_by_id["sheet_region_emerald_plains_region"]
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            master_path = Path(temporary) / "master.png"
            Image.new("RGB", (4, 4), "white").save(master_path)
            asset = phase5.BuiltAsset(
                sheet=sheet,
                contract=self.contracts[sheet["id"]],
                job_id=phase5.job_id_for_sheet(sheet["id"]),
                method="verified-master-import",
                stage_path=None,
                final_manifest_path=None,
                sha256=None,
                source_entry={"kind": "master", **artifact(master_path)},
            )

            with self.assertRaisesRegex(
                phase5.Phase5BuildError, "require immutable source-index byte bindings"
            ):
                phase5.create_job(
                    asset,
                    assets_by_sheet={sheet["id"]: asset},
                    catalog_path=phase5.DEFAULT_MAP_SHEETS,
                    contract_path=phase5.DEFAULT_CONTRACT,
                    control_master=phase5.DEFAULT_CONTROL_MASTER,
                    style_master=None,
                )

    def test_publication_evidence_records_bound_artifacts(self):
        sheet = self.catalog_by_id["sheet_region_emerald_plains_region"]
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            paths = [
                root / "provenance.json",
                root / "automated.json",
                root / "vision-1.json",
                root / "vision-2.json",
            ]
            for index, path in enumerate(paths):
                path.write_text(f'{{"record":{index}}}\n', encoding="utf-8")
            bindings = [
                bound_artifacts.bind_file(path, label=f"bound {path.name}")
                for path in paths
            ]
            registry = {binding.identity: binding for binding in bindings}
            asset = phase5.BuiltAsset(
                sheet=sheet,
                contract=self.contracts[sheet["id"]],
                job_id=phase5.job_id_for_sheet(sheet["id"]),
                method="verified-master-import",
                stage_path=None,
                final_manifest_path=None,
                sha256=None,
                accepted_evidence=phase5.QAEvidence(
                    provenance_path=phase5.repo_path(paths[0]),
                    automated_path=phase5.repo_path(paths[1]),
                    vision_paths=(
                        phase5.repo_path(paths[2]),
                        phase5.repo_path(paths[3]),
                    ),
                    primary_score=95,
                    primary_reviewer="Bound Reviewer",
                ),
            )
            originals = {path: (path.read_bytes(), path.stat()) for path in paths}
            try:
                for path, (data, metadata) in originals.items():
                    path.write_bytes(b"x" * len(data))
                    os.utime(
                        path,
                        ns=(metadata.st_atime_ns, metadata.st_mtime_ns),
                    )
                with phase5.bound_artifact_context(registry):
                    evidence = phase5._tile_index_evidence(asset)
            finally:
                for path, (data, metadata) in originals.items():
                    path.write_bytes(data)
                    os.utime(
                        path,
                        ns=(metadata.st_atime_ns, metadata.st_mtime_ns),
                    )

            self.assertEqual(evidence["provenance"], bindings[0].artifact())
            self.assertEqual(evidence["automated_qa"], bindings[1].artifact())
            self.assertEqual(
                evidence["vision_reviews"],
                [bindings[2].artifact(), bindings[3].artifact()],
            )
            for binding in bindings:
                binding.assert_unchanged()

    def test_manifest_uses_preparsed_bound_object_after_live_file_changes(self):
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            manifest_path = Path(temporary) / "base-manifest.json"
            original = {
                "schema_version": "1.0.0",
                "jobs": [{"id": "bound-base-job"}],
            }
            manifest_path.write_text(json.dumps(original), encoding="utf-8")
            binding = bound_artifacts.bind_file(
                manifest_path, label="bound base manifest"
            )
            bound_object = binding.json_object()
            original_bytes = manifest_path.read_bytes()
            original_stat = manifest_path.stat()
            try:
                manifest_path.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0.0",
                            "jobs": [{"id": "late-live-job"}],
                        }
                    ),
                    encoding="utf-8",
                )
                result = phase5._manifest(
                    bound_object,
                    [{"id": "new-phase5-job"}],
                )
            finally:
                manifest_path.write_bytes(original_bytes)
                os.utime(
                    manifest_path,
                    ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
                )

            self.assertEqual(
                [job["id"] for job in result["jobs"]],
                ["bound-base-job", "new-phase5-job"],
            )
            binding.assert_unchanged()

    def test_rgb_color_gate_rejects_equal_luminance_overlap(self):
        first = Image.new("RGB", (8, 8), (255, 0, 0))
        second = Image.new("RGB", (8, 8), (0, 130, 0))
        try:
            ssim, rgb_mean, rgb_p95 = phase5.overlap_similarity(first, second)
        finally:
            first.close()
            second.close()
        self.assertGreaterEqual(ssim, 0.99)
        self.assertGreater(rgb_mean, phase5.MAXIMUM_RGB_MEAN_DIFFERENCE)
        self.assertGreater(rgb_p95, phase5.MAXIMUM_RGB_P95_DIFFERENCE)

        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            left_path = root / "left.png"
            right_path = root / "right.png"
            Image.new("RGB", (4, 4), (255, 0, 0)).save(left_path)
            Image.new("RGB", (4, 4), (0, 130, 0)).save(right_path)
            plan = {
                "sheet_id": "sheet_region_color_gate",
                "master_size": [6, 2],
                "metatile_size_px": 4,
                "gutter_each_side_px": 1,
                "stride_px": 2,
                "columns": 2,
                "rows": 1,
                "count": 2,
                "tiles": [
                    {
                        "column": 0,
                        "row": 0,
                        "source_core_box_px": [0, 0, 3, 2],
                        "destination_box_px": [0, 0, 3, 2],
                    },
                    {
                        "column": 1,
                        "row": 0,
                        "source_core_box_px": [1, 0, 4, 2],
                        "destination_box_px": [3, 0, 6, 2],
                    },
                ],
            }
            with self.assertRaisesRegex(phase5.Phase5BuildError, "rgb_mean"):
                phase5.stitch_metatiles(
                    {
                        "kind": "metatiles",
                        "tiles": [
                            {"column": 0, "row": 0, **artifact(left_path)},
                            {"column": 1, "row": 0, **artifact(right_path)},
                        ],
                        phase5.INTERNAL_BOUND_ARTIFACTS_KEY: bound_registry(
                            left_path, right_path
                        ),
                    },
                    plan,
                    root / "master.png",
                    minimum_ssim=0.90,
                )

    def test_rgb_p95_gate_catches_sparse_shift_below_mean_limit(self):
        first = Image.new("RGB", (10, 10), "black")
        second = Image.new("RGB", (10, 10), "black")
        for x in range(8):
            first.putpixel((x, 0), (50, 0, 0))
            second.putpixel((x, 0), (0, 26, 0))
        try:
            ssim, rgb_mean, rgb_p95 = phase5.overlap_similarity(first, second)
        finally:
            first.close()
            second.close()
        self.assertGreaterEqual(ssim, 0.99)
        self.assertLess(rgb_mean, phase5.MAXIMUM_RGB_MEAN_DIFFERENCE)
        self.assertGreater(rgb_p95, phase5.MAXIMUM_RGB_P95_DIFFERENCE)

    def test_94_point_sheet_requires_two_distinct_hashed_reviewers(self):
        sheet = self.catalog_by_id["sheet_region_royal_capital_region"]
        job_id = phase5.job_id_for_sheet(sheet["id"])
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            master = root / "master.png"
            Image.new("RGB", (2, 2), "white").save(master)
            master_path = phase5.repo_path(master)
            provenance = write_provenance_report(
                root,
                sheet_id=sheet["id"],
                master=master,
            )
            automated_spec = write_automated_report(
                root,
                sheet_id=sheet["id"],
                master=master,
                provenance=provenance,
                source_kind="master",
            )
            report_specs = []
            for filename, reviewer in (
                ("review-a.json", "Reviewer A"),
                ("review-b.json", "Reviewer B"),
            ):
                path = root / filename
                path.write_text(
                    json.dumps(
                        complete_report(job_id, master_path, reviewer, 94),
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                report_specs.append(artifact(path))
                report_document = json.loads(path.read_text(encoding="utf-8"))
                self.assertFalse(report_document["golden_reference"])
                self.assertEqual(report_document["review_mode"], "blind-independent")
                self.assertEqual(report_document["image_sha256"], digest(master))
            entry = {
                "sheet_id": sheet["id"],
                "kind": "master",
                **artifact(master),
                "provenance_report": provenance,
                "automated_report": automated_spec,
                "vision_reports": report_specs,
            }

            evidence = phase5.accepted_evidence(
                entry,
                sheet=sheet,
                master_path=master_path,
                job_id=job_id,
            )
            self.assertEqual(evidence.primary_score, 100)
            self.assertEqual(len(evidence.vision_paths), 2)

            wrongly_golden = copy.deepcopy(entry)
            wrongly_golden_path = root / "wrongly-golden.json"
            wrongly_golden_report = complete_report(
                job_id, master_path, "Reviewer C", 94
            )
            wrongly_golden_report["golden_reference"] = True
            wrongly_golden_path.write_text(
                json.dumps(wrongly_golden_report), encoding="utf-8"
            )
            wrongly_golden["vision_reports"][1] = artifact(wrongly_golden_path)
            with self.assertRaisesRegex(
                phase5.Phase5BuildError, "golden_reference must be false"
            ):
                phase5.accepted_evidence(
                    wrongly_golden,
                    sheet=sheet,
                    master_path=master_path,
                    job_id=job_id,
                )

            score_mismatch = complete_report(job_id, master_path, "Reviewer C", 94)
            score_mismatch["total_score"] = 99
            with self.assertRaisesRegex(phase5.Phase5BuildError, "score sum"):
                phase5._accepted_report(
                    score_mismatch,
                    job_id=job_id,
                    image_path=master_path,
                    image_sha256=digest(master),
                    golden_reference=False,
                    threshold=94,
                    label="score mismatch",
                )

            duplicate = copy.deepcopy(entry)
            duplicate_report_path = phase5.resolve_repo_artifact(
                duplicate["vision_reports"][1]["path"], "duplicate report"
            )
            duplicate_report = complete_report(job_id, master_path, "Reviewer A", 94)
            duplicate_report_path.write_text(
                json.dumps(duplicate_report, ensure_ascii=False), encoding="utf-8"
            )
            duplicate["vision_reports"][1]["sha256"] = digest(duplicate_report_path)
            with self.assertRaisesRegex(phase5.Phase5BuildError, "duplicate reviewer"):
                phase5.accepted_evidence(
                    duplicate,
                    sheet=sheet,
                    master_path=master_path,
                    job_id=job_id,
                )

    def test_acceptance_requires_hash_locked_provenance_and_complete_reports(self):
        sheet = self.catalog_by_id["sheet_region_emerald_plains_region"]
        job_id = phase5.job_id_for_sheet(sheet["id"])
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            master = root / "master.png"
            Image.new("RGB", (2, 2), "white").save(master)
            master_path = phase5.repo_path(master)
            automated = root / "automated.json"
            vision = root / "vision.json"
            automated.write_text(
                json.dumps(complete_report(job_id, master_path, "Automated QA", 90)),
                encoding="utf-8",
            )
            vision.write_text(
                json.dumps(complete_report(job_id, master_path, "Vision A", 90)),
                encoding="utf-8",
            )
            entry = {
                "sheet_id": sheet["id"],
                "kind": "master",
                **artifact(master),
                "automated_report": artifact(automated),
                "vision_reports": [artifact(vision)],
            }
            with self.assertRaisesRegex(phase5.Phase5BuildError, "provenance_report"):
                phase5.accepted_evidence(
                    entry,
                    sheet=sheet,
                    master_path=master_path,
                    job_id=job_id,
                )

            source_index = root / "missing-provenance-index.json"
            source_index.write_text(
                json.dumps(
                    {
                        "schema_version": "1.3.0",
                        "coordinate_reference_system": "EA-WORLD-1",
                        "golden_style": artifact(master),
                        "sources": [entry],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                phase5.Phase5BuildError, "invalid source index"
            ):
                phase5.load_source_index(source_index, set(self.contracts))

            entry["provenance_report"] = write_provenance_report(
                root,
                sheet_id=sheet["id"],
                master=master,
            )
            entry["provenance_report"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(phase5.Phase5BuildError, "sha256 mismatch"):
                phase5.accepted_evidence(
                    entry,
                    sheet=sheet,
                    master_path=master_path,
                    job_id=job_id,
                )

    def test_reviewed_continent_and_world_composites_can_be_accepted(self):
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            region_sheet = {
                "id": "sheet_region_child",
                "sheet_type": "region",
                "parent_id": "sheet_continent_parent",
            }
            continent_sheet = {
                "id": "sheet_continent_parent",
                "sheet_type": "continent",
                "parent_id": "sheet_world_parent",
            }
            world_sheet = {
                "id": "sheet_world_parent",
                "sheet_type": "world",
                "parent_id": None,
            }
            catalog = {
                item["id"]: item
                for item in (region_sheet, continent_sheet, world_sheet)
            }
            region_master = root / "region.png"
            continent_master = root / "continent.png"
            world_master = root / "world.png"
            Image.new("RGB", (8, 8), "green").save(region_master)
            Image.new("RGB", (8, 8), "tan").save(continent_master)
            Image.new("RGB", (8, 8), "navy").save(world_master)

            child_source_index = root / "composite-child-source-index.json"
            child_source_index.write_text(
                json.dumps({"sources": [artifact(region_master)]}),
                encoding="utf-8",
            )
            parent_root = root / "parent-controls"
            parent_root.mkdir()
            parent_sheets = []
            parent_controls: dict[str, dict] = {}
            for sheet in (continent_sheet, world_sheet):
                qa_root = parent_root / sheet["id"] / "qa"
                qa_root.mkdir(parents=True)
                land_path = qa_root / "land-sea-control.png"
                route_path = qa_root / "transport-control.png"
                Image.new("L", (8, 8), 255).save(land_path)
                route_image = Image.new("L", (8, 8), 0)
                for x in range(8):
                    route_image.putpixel((x, 3), 255)
                route_image.save(route_path)
                route_image.close()
                controls = {
                    "land_sea_control": {
                        **artifact(land_path),
                        "width": 8,
                        "height": 8,
                        "format": "PNG",
                        "color_mode": "L",
                        "binary_values": [255],
                        "on_pixel_count": 64,
                    },
                    "transport_control": {
                        **artifact(route_path),
                        "width": 8,
                        "height": 8,
                        "format": "PNG",
                        "color_mode": "L",
                        "binary_values": [0, 255],
                        "on_pixel_count": 8,
                    },
                }
                parent_controls[sheet["id"]] = controls
                parent_sheets.append({"sheet_id": sheet["id"], "qa_controls": controls})
            parent_index_path = parent_root / "index.json"
            parent_index_document = {"sheets": parent_sheets}
            parent_index_path.write_text(
                json.dumps(parent_index_document), encoding="utf-8"
            )
            parent_report_path = parent_root / "report.json"
            parent_report_document = {"index": artifact(parent_index_path)}
            parent_report_path.write_text(
                json.dumps(parent_report_document), encoding="utf-8"
            )
            self.enterContext(
                patch.object(
                    parent_control_renderer,
                    "load_validated_parent_control_bundle",
                    return_value=(parent_index_document, parent_report_document),
                )
            )

            region_source = {
                "sheet_id": region_sheet["id"],
                "kind": "master",
                **artifact(region_master),
                "provenance_report": {"path": "claimed", "sha256": "0" * 64},
                "automated_report": {"path": "claimed", "sha256": "0" * 64},
                "vision_reports": [{"path": "claimed", "sha256": "0" * 64}],
            }
            continent_children = [
                {
                    "sheet_id": region_sheet["id"],
                    **artifact(region_master),
                    "native_zoom": 1,
                }
            ]
            continent_provenance = write_provenance_report(
                root,
                sheet_id=continent_sheet["id"],
                master=continent_master,
                method="deterministic-parent-composite",
                children=continent_children,
            )

            def reports_for(
                sheet: dict,
                master: Path,
                provenance: dict[str, str],
            ) -> tuple[dict, dict, list[dict]]:
                controls = parent_controls[sheet["id"]]
                land_control_path = phase5.resolve_repo_artifact(
                    controls["land_sea_control"]["path"], "test parent land control"
                )
                route_control_path = phase5.resolve_repo_artifact(
                    controls["transport_control"]["path"],
                    "test parent transport control",
                )
                observed_land = root / f"{sheet['id']}-observed-land.png"
                observed_route = root / f"{sheet['id']}-observed-route.png"
                with Image.open(land_control_path) as opened:
                    observed = opened.copy()
                observed.putpixel((0, 0), 0)
                observed.save(observed_land)
                observed.close()
                with Image.open(route_control_path) as opened:
                    observed = opened.copy()
                for x in range(8):
                    observed.putpixel((x, 4), 255)
                observed.save(observed_route)
                observed.close()

                provenance_path = phase5.resolve_repo_artifact(
                    provenance["path"], "test composite provenance"
                )
                provenance_document = json.loads(
                    provenance_path.read_text(encoding="utf-8")
                )
                provenance_document["inputs"]["source_index"] = artifact(
                    child_source_index
                )
                structured = provenance_document["artifacts"][0]["provenance"]
                children = structured["children"]
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
                            "transport": artifact(observed_route),
                        },
                        "composition": {
                            "child_order": [
                                child["sheet_id"]
                                for child in sorted(
                                    children,
                                    key=lambda child: (
                                        child["native_zoom"],
                                        child["sheet_id"],
                                    ),
                                )
                            ],
                            "resampling": "LANCZOS-downsample-only",
                            "upscaled_child_count": 0,
                            "base_rendered_at_parent_native_resolution": True,
                        },
                    }
                )
                provenance_path.write_text(
                    json.dumps(provenance_document), encoding="utf-8"
                )
                provenance = artifact(provenance_path)
                job_id = phase5.job_id_for_sheet(sheet["id"])
                image_path = phase5.repo_path(master)
                vision_path = root / f"{sheet['id']}-vision.json"
                vision_path.write_text(
                    json.dumps(complete_report(job_id, image_path, "Vision A", 90)),
                    encoding="utf-8",
                )
                automated = write_automated_report(
                    root,
                    sheet_id=sheet["id"],
                    master=master,
                    provenance=provenance,
                    source_kind="composite_master",
                )
                automated_path = phase5.resolve_repo_artifact(
                    automated["path"], "test composite automated report"
                )
                automated_document = json.loads(
                    automated_path.read_text(encoding="utf-8")
                )
                automated_document["parent_controls"] = {
                    "index": artifact(parent_index_path),
                    "report": artifact(parent_report_path),
                }
                automated_document["geography"] = {
                    "land_sea": {
                        "passed": True,
                        "control": {
                            key: controls["land_sea_control"][key]
                            for key in ("path", "sha256")
                        },
                        "observed": artifact(observed_land),
                        "minimum_match_ratio": 0.98,
                        "match_ratio": 63 / 64,
                    },
                    "transport": {
                        "passed": True,
                        "control": {
                            key: controls["transport_control"][key]
                            for key in ("path", "sha256")
                        },
                        "observed": artifact(observed_route),
                        "tolerance_px": 1,
                        "minimum_within_tolerance_ratio": 0.95,
                        "control_within_tolerance_ratio": 1.0,
                        "observed_within_tolerance_ratio": 1.0,
                    },
                }
                automated_path.write_text(
                    json.dumps(automated_document), encoding="utf-8"
                )
                return provenance, artifact(automated_path), [artifact(vision_path)]

            continent_provenance, continent_automated, continent_vision = reports_for(
                continent_sheet, continent_master, continent_provenance
            )
            continent_source = {
                "sheet_id": continent_sheet["id"],
                "kind": "composite_master",
                **artifact(continent_master),
                "provenance_report": continent_provenance,
                "automated_report": continent_automated,
                "vision_reports": continent_vision,
            }
            sources = {
                region_sheet["id"]: region_source,
                continent_sheet["id"]: continent_source,
            }
            contract = {"width": 8, "height": 8}
            continent_evidence = phase5.accepted_evidence(
                continent_source,
                sheet=continent_sheet,
                master_path=phase5.repo_path(continent_master),
                job_id=phase5.job_id_for_sheet(continent_sheet["id"]),
                contract=contract,
                catalog_by_id=catalog,
                sources=sources,
            )
            self.assertEqual(continent_evidence.primary_score, 100)
            phase5.preflight_source_entry(
                continent_source,
                sheet=continent_sheet,
                contract=contract,
                catalog_by_id=catalog,
                sources=sources,
            )

            world_children = [
                {
                    "sheet_id": continent_sheet["id"],
                    **artifact(continent_master),
                    "native_zoom": 1,
                }
            ]
            world_provenance = write_provenance_report(
                root,
                sheet_id=world_sheet["id"],
                master=world_master,
                method="deterministic-parent-composite",
                children=world_children,
            )
            world_provenance, world_automated, world_vision = reports_for(
                world_sheet, world_master, world_provenance
            )
            world_source = {
                "sheet_id": world_sheet["id"],
                "kind": "composite_master",
                **artifact(world_master),
                "provenance_report": world_provenance,
                "automated_report": world_automated,
                "vision_reports": world_vision,
            }
            sources[world_sheet["id"]] = world_source
            index_path = root / "reviewed-composite-index.json"
            index_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.3.0",
                        "coordinate_reference_system": "EA-WORLD-1",
                        "golden_style": artifact(world_master),
                        "sources": [world_source],
                    }
                ),
                encoding="utf-8",
            )
            indexed, _, _ = phase5.load_source_index(index_path, set(catalog))
            self.assertEqual(indexed[world_sheet["id"]]["kind"], "composite_master")

            incomplete_index = copy.deepcopy(
                json.loads(index_path.read_text(encoding="utf-8"))
            )
            del incomplete_index["sources"][0]["automated_report"]
            index_path.write_text(json.dumps(incomplete_index), encoding="utf-8")
            with self.assertRaisesRegex(
                phase5.Phase5BuildError, "invalid source index"
            ):
                phase5.load_source_index(index_path, set(catalog))

            world_evidence = phase5.accepted_evidence(
                world_source,
                sheet=world_sheet,
                master_path=phase5.repo_path(world_master),
                job_id=phase5.job_id_for_sheet(world_sheet["id"]),
                contract=contract,
                catalog_by_id=catalog,
                sources=sources,
            )
            self.assertEqual(world_evidence.primary_score, 100)
            phase5.preflight_source_entry(
                world_source,
                sheet=world_sheet,
                contract=contract,
                catalog_by_id=catalog,
                sources=sources,
            )
            imported = phase5.build_imported_master_asset(
                sheet=world_sheet,
                contract=contract,
                source_entry=world_source,
                staging_root=root / "staging",
                final_root=root / "final",
                catalog_by_id=catalog,
                sources=sources,
                require_accepted=True,
            )
            self.assertTrue(imported.accepted)
            self.assertEqual(imported.method, "verified-composite-master-import")

            mismatched_sources = copy.deepcopy(sources)
            mismatched_sources[continent_sheet["id"]]["sha256"] = "0" * 64
            with self.assertRaisesRegex(phase5.Phase5BuildError, "hash"):
                phase5.accepted_evidence(
                    world_source,
                    sheet=world_sheet,
                    master_path=phase5.repo_path(world_master),
                    job_id=phase5.job_id_for_sheet(world_sheet["id"]),
                    contract=contract,
                    catalog_by_id=catalog,
                    sources=mismatched_sources,
                )

    def test_continent_composition_routes_all_17_generation_masters_once(self):
        continents = [
            sheet
            for sheet in self.catalog_by_id.values()
            if sheet.get("sheet_type") == "continent"
        ]
        routed = [
            child_id
            for continent in continents
            for child_id in phase5._expected_composite_children(
                continent, self.catalog_by_id
            )
        ]
        expected = {
            sheet_id
            for sheet_id, sheet in self.catalog_by_id.items()
            if sheet.get("sheet_type") in phase5.GENERATION_TYPES
        }
        self.assertEqual(len(routed), 17)
        self.assertEqual(set(routed), expected)
        self.assertEqual(len(routed), len(set(routed)))

    def test_parent_compositor_rejects_any_child_upscale(self):
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            child_path = root / "child.png"
            Image.new("RGB", (4, 4), "green").save(child_path)
            child = phase5.BuiltAsset(
                sheet={
                    "id": "sheet_region_child",
                    "bounds": [0, 0, 10, 10],
                },
                contract={"width": 4, "height": 4},
                job_id="child-v1",
                method="fixture",
                stage_path=child_path,
                final_manifest_path=phase5.repo_path(child_path),
                sha256=digest(child_path),
            )
            base = Image.new("RGB", (10, 10), "tan")
            try:
                with self.assertRaisesRegex(
                    phase5.Phase5BuildError, "would be upscaled"
                ):
                    phase5.composite_children(base, [0, 0, 10, 10], [child])
            finally:
                base.close()

    def test_parent_compositor_places_higher_native_zoom_children_last(self):
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            children = []
            for sheet_id, zoom, color in (
                ("sheet_settlement_high", 8, "blue"),
                ("sheet_region_low", 5, "red"),
            ):
                path = root / f"{sheet_id}.png"
                Image.new("RGB", (40, 40), color).save(path)
                children.append(
                    phase5.BuiltAsset(
                        sheet={"id": sheet_id, "bounds": [0, 0, 10, 10]},
                        contract={"width": 40, "height": 40, "native_zoom": zoom},
                        job_id=f"{sheet_id}-v1",
                        method="fixture",
                        stage_path=path,
                        final_manifest_path=phase5.repo_path(path),
                        sha256=digest(path),
                    )
                )
            base = Image.new("RGB", (10, 10), "tan")
            try:
                used = phase5.composite_children(base, [0, 0, 10, 10], children)
                self.assertEqual(used, ["sheet_region_low", "sheet_settlement_high"])
                blue = base.getpixel((5, 5))
                self.assertGreater(blue[2], blue[0])
            finally:
                base.close()

    def test_schema2_index_fails_closed_for_partial_or_provisional_assets(self):
        sheet = self.catalog_by_id["sheet_region_emerald_plains_region"]
        contract = self.contracts[sheet["id"]]
        with tempfile.TemporaryDirectory(
            prefix=".phase5-assets-test-", dir=REPO_ROOT
        ) as temporary:
            root = Path(temporary)
            generated_path = root / "generated.png"
            accepted_path = root / "accepted.png"
            Image.new("RGB", (8, 8), "green").save(generated_path)
            Image.new("RGB", (8, 8), "blue").save(accepted_path)
            generated = phase5.BuiltAsset(
                sheet=sheet,
                contract={**contract, "width": 8, "height": 8},
                job_id="phase5-generated-test-v1",
                method="provisional-style-seed",
                stage_path=generated_path,
                final_manifest_path=phase5.repo_path(generated_path),
                sha256=digest(generated_path),
                provisional=True,
            )
            accepted = phase5.BuiltAsset(
                sheet={**sheet, "id": "sheet_region_accepted_test"},
                contract={**contract, "width": 8, "height": 8},
                job_id="phase5-accepted-test-v1",
                method="verified-master-import",
                stage_path=accepted_path,
                final_manifest_path=phase5.repo_path(accepted_path),
                sha256=digest(accepted_path),
                accepted_evidence=phase5.QAEvidence(
                    provenance_path="world/map-production/build-report.json",
                    automated_path="world/map-production/qa/automated.json",
                    vision_paths=("world/map-production/qa/review.json",),
                    primary_score=95,
                    primary_reviewer="Reviewer",
                ),
            )

            with self.assertRaisesRegex(
                phase5.Phase5BuildError, "exactly all 23 bounded sheets"
            ):
                phase5.build_sheet_tile_index(
                    [generated, accepted],
                    root,
                    release_id="world-v3",
                    generated_at="2026-07-19T00:00:00Z",
                )
            self.assertFalse((root / "public").exists())


if __name__ == "__main__":
    unittest.main()
