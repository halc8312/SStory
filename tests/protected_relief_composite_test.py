from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageChops, ImageDraw, ImageStat


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts/map-production/composite_protected_relief.py"
SPEC = importlib.util.spec_from_file_location("protected_relief_composite", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

SCHEMA_PATH = (
    REPO_ROOT / "world/map-production/schemas/protected-relief-composite-v1.schema.json"
)
G1_CONTROL = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-g-v1-generation-control-v1.json"
)
G2_CONTROL = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-g-v2-generation-control-v1.json"
)
G3_CONTROL = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-g-v3-generation-control-v2.json"
)
G4_CONTROL = (
    REPO_ROOT / "world/map-production/controls/"
    "style-candidate-g-v4-narrow-protection-control-v3.json"
)
G2_PREFLIGHT = (
    REPO_ROOT / "world/map-production/qa/automated/"
    "style-candidate-g-v2-generation-preflight.json"
)
G3_PREFLIGHT = (
    REPO_ROOT / "world/map-production/qa/automated/"
    "style-candidate-g-v3-generation-preflight.json"
)
G2_MASK = (
    REPO_ROOT / "world/map-production/qa/automated/style-candidate-g-v2-edit-mask.png"
)
G3_BASE = (
    REPO_ROOT
    / "world/map-production/candidates/style-candidate-d-v4-erase-route-marks.png"
)
G3_RAW = (
    REPO_ROOT / "world/map-production/candidates/"
    "style-candidate-g-v3-hachure-skeleton-raw.png"
)
G4_SCHEMA = (
    REPO_ROOT / "world/map-production/schemas/protected-relief-composite-v3.schema.json"
)
G4_OUTPUT = (
    REPO_ROOT
    / "world/map-production/candidates/style-candidate-g-v4-narrow-protection.png"
)
G4_MASK = (
    REPO_ROOT
    / "world/map-production/qa/automated/style-candidate-g-v4-edit-mask.png"
)
G4_PROTECTION = (
    REPO_ROOT
    / "world/map-production/qa/automated/style-candidate-g-v4-protection.png"
)

LEGACY_ARTIFACTS = (
    (
        G1_CONTROL,
        REPO_ROOT / "world/map-production/candidates/"
        "style-candidate-g-v1-direct-cartographic-relief-raw.png",
        REPO_ROOT / "world/map-production/candidates/"
        "style-candidate-g-v1-direct-cartographic-relief.png",
        REPO_ROOT
        / "world/map-production/qa/automated/style-candidate-g-v1-edit-mask.png",
        REPO_ROOT
        / "world/map-production/qa/automated/style-candidate-g-v1-protection.png",
    ),
    (
        G2_CONTROL,
        REPO_ROOT / "world/map-production/candidates/"
        "style-candidate-g-v2-orthographic-hachure-raw.png",
        REPO_ROOT / "world/map-production/candidates/"
        "style-candidate-g-v2-orthographic-hachure.png",
        G2_MASK,
        REPO_ROOT
        / "world/map-production/qa/automated/style-candidate-g-v2-protection.png",
    ),
    (
        G3_CONTROL,
        G3_RAW,
        REPO_ROOT
        / "world/map-production/candidates/style-candidate-g-v3-hachure-skeleton.png",
        REPO_ROOT
        / "world/map-production/qa/automated/style-candidate-g-v3-edit-mask.png",
        REPO_ROOT
        / "world/map-production/qa/automated/style-candidate-g-v3-protection.png",
    ),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _semantic_sha256(path: Path) -> str:
    with Image.open(path) as opened:
        opened.load()
        return MODULE._raster_semantic_sha256(opened)


class ProtectedReliefCompositeTest(unittest.TestCase):
    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(REPO_ROOT).as_posix()

    def _build_fixture(self, root: Path) -> dict[str, Path]:
        size = (512, 320)
        background = (128, 128, 128)
        colors = {
            "main-massif": (206, 74, 62),
            "foothill-a": (232, 151, 61),
            "foothill-b": (126, 93, 178),
        }
        shape_contract = (
            (
                "ne-main-massif",
                "north_east_range",
                "main-massif",
                [[210, 20], [350, 20], [370, 60], [340, 110], [220, 110]],
            ),
            (
                "ne-west-foothill",
                "north_east_range",
                "foothill-a",
                [[25, 55], [90, 45], [110, 80], [85, 120], [30, 110]],
            ),
            (
                "ne-central-foothill",
                "north_east_range",
                "foothill-b",
                [[125, 60], [185, 55], [200, 90], [175, 125], [125, 115]],
            ),
            (
                "se-main-massif",
                "south_east_range",
                "main-massif",
                [[210, 190], [350, 190], [375, 235], [340, 285], [220, 285]],
            ),
            (
                "se-west-foothill",
                "south_east_range",
                "foothill-a",
                [[25, 210], [90, 205], [110, 245], [85, 290], [25, 280]],
            ),
            (
                "se-east-foothill",
                "south_east_range",
                "foothill-b",
                [[400, 215], [475, 210], [500, 250], [475, 295], [405, 285]],
            ),
        )

        base_path = root / "base.png"
        base = Image.new("RGB", size, (170, 150, 115))
        base_draw = ImageDraw.Draw(base)
        base_draw.line([(135, 90), (185, 90)], fill=(45, 40, 35), width=3)
        base.save(base_path, format="PNG", optimize=True)
        base.close()

        generated_path = root / "generated.png"
        generated = Image.new("RGB", size, (220, 205, 175))
        generated.save(generated_path, format="PNG", optimize=True)
        generated.close()

        guide_path = root / "guide.png"
        guide = Image.new("RGB", size, background)
        guide_draw = ImageDraw.Draw(guide)
        shapes = []
        for identifier, region_id, role, points in shape_contract:
            guide_draw.polygon([tuple(point) for point in points], fill=colors[role])
            shapes.append(
                {
                    "id": identifier,
                    "region_id": region_id,
                    "role": role,
                    "rgb": list(colors[role]),
                    "points": points,
                }
            )
        guide.save(guide_path, format="PNG", optimize=True)
        guide.close()

        guide_source_path = root / "guide.json"
        guide_source_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "id": "test-guide",
                    "coordinate_space": "source-pixels-y-down",
                    "canvas": {"width": size[0], "height": size[1]},
                    "background_rgb": list(background),
                    "shapes": shapes,
                    "purpose": "test fixture",
                }
            ),
            encoding="utf-8",
        )
        prompt_path = root / "prompt.md"
        prompt_path.write_text("test prompt\n", encoding="utf-8")

        control = {
            "schema_version": "1.0.0",
            "schema_lock": {
                "path": self._relative(SCHEMA_PATH),
                "sha256": _sha256(SCHEMA_PATH),
            },
            "id": "test-g1-generation-control",
            "coordinate_space": "source-pixels-y-down",
            "canvas": {"width": size[0], "height": size[1]},
            "prompt": {
                "path": self._relative(prompt_path),
                "sha256": _sha256(prompt_path),
            },
            "references": [
                {
                    "index": 1,
                    "path": self._relative(base_path),
                    "sha256": _sha256(base_path),
                    "format": "PNG",
                    "mode": "RGB",
                    "role": "pixel-authoritative-base",
                },
                {
                    "index": 2,
                    "path": self._relative(guide_path),
                    "sha256": _sha256(guide_path),
                    "format": "PNG",
                    "mode": "RGB",
                    "role": "flat-color-topology-guide",
                },
            ],
            "guide_contract": {
                "source_control": {
                    "path": self._relative(guide_source_path),
                    "sha256": _sha256(guide_source_path),
                },
                "background_rgb": list(background),
                "active_colors": [
                    {
                        "role": "main-massif",
                        "rgb": list(colors["main-massif"]),
                        "expected_components": 2,
                    },
                    {
                        "role": "foothill-a",
                        "rgb": list(colors["foothill-a"]),
                        "expected_components": 2,
                    },
                    {
                        "role": "foothill-b",
                        "rgb": list(colors["foothill-b"]),
                        "expected_components": 2,
                    },
                ],
                "expected_components": 6,
                "permission_feather_inside_px": 4,
            },
            "road_protection": {
                "guard_width_px": 64,
                "feather_px": 2,
                "strokes": [
                    {"id": "north_road", "points": [[280, 0], [280, 135]]},
                    {"id": "east_road", "points": [[0, 155], [511, 155]]},
                    {
                        "id": "south_east_road",
                        "points": [[280, 175], [475, 300]],
                    },
                ],
            },
            "detail_protection": {
                "gaussian_radius_px": 2,
                "high_frequency_threshold_levels": 10,
                "dark_luminance_max": 90,
                "feather_px": 1,
            },
            "purpose": "test fixture",
        }
        control_path = root / "control.json"
        control_path.write_text(json.dumps(control), encoding="utf-8")
        return {
            "base": base_path,
            "generated": generated_path,
            "guide": guide_path,
            "guide_source": guide_source_path,
            "prompt": prompt_path,
            "control": control_path,
        }

    def _outputs(self, root: Path) -> dict[str, Path]:
        return {
            "output": root / "output.png",
            "mask": root / "mask.png",
            "protection": root / "protection.png",
            "report": root / "report.json",
        }

    def _run(self, fixture: dict[str, Path], outputs: dict[str, Path]) -> dict:
        return MODULE.composite(
            control_path=fixture["control"],
            generated_path=fixture["generated"],
            output_path=outputs["output"],
            mask_output_path=outputs["mask"],
            protection_output_path=outputs["protection"],
            report_path=outputs["report"],
        )

    def _assert_no_temporary_files(self, root: Path) -> None:
        self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_committed_g1_generation_control_preflights(self) -> None:
        report = MODULE.preflight(G1_CONTROL)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["guide"]["active_pixels"], 193377)
        self.assertEqual(report["guide"]["components"], 6)
        self.assertEqual(
            [(entry["index"], entry["role"]) for entry in report["reference_order"]],
            [
                (1, "pixel-authoritative-base"),
                (2, "flat-color-topology-guide"),
            ],
        )
        self.assertEqual(
            report["road_order"],
            ["north_road", "east_road", "south_east_road"],
        )
        self.assertEqual(report["road_guard_width_px"], 64)

    def test_committed_g2_generation_control_preflights_smooth_guide(self) -> None:
        report = MODULE.preflight(G2_CONTROL)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["guide"]["active_pixels"], 227663)
        self.assertEqual(report["guide"]["components"], 6)
        self.assertEqual(report["road_guard_width_px"], 64)
        self.assertEqual(
            report["prompt_path"],
            "world/map-production/prompts/"
            "style-candidate-g-v2-orthographic-hachure.generation.txt",
        )

        g1 = json.loads(G1_CONTROL.read_text(encoding="utf-8"))
        g2 = json.loads(G2_CONTROL.read_text(encoding="utf-8"))
        self.assertEqual(g2["road_protection"], g1["road_protection"])
        self.assertEqual(g2["detail_protection"], g1["detail_protection"])
        self.assertEqual(json.loads(G2_PREFLIGHT.read_text(encoding="utf-8")), report)

    def test_committed_g3_generation_control_preflights_three_references(self) -> None:
        report = MODULE.preflight(G3_CONTROL)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["guide"]["active_pixels"], 227663)
        self.assertEqual(report["guide"]["components"], 6)
        self.assertEqual(
            [(entry["index"], entry["role"]) for entry in report["reference_order"]],
            [
                (1, "pixel-authoritative-base"),
                (2, "flat-color-topology-guide"),
                (3, "open-hachure-skeleton-guide"),
            ],
        )
        self.assertEqual(report["permission_source_reference_index"], 2)
        self.assertEqual(report["skeleton_permission_contribution"], "none")
        self.assertEqual(report["skeleton"]["landform_count"], 6)
        self.assertEqual(report["skeleton"]["rise_group_count"], 4)
        self.assertEqual(report["skeleton"]["open_saddle_count"], 2)
        self.assertEqual(report["skeleton"]["foothill_count"], 4)
        self.assertEqual(report["skeleton"]["closed_path_count"], 0)
        self.assertEqual(report["skeleton"]["long_parallel_band_count"], 0)
        self.assertEqual(json.loads(G3_PREFLIGHT.read_text(encoding="utf-8")), report)

        g2 = json.loads(G2_CONTROL.read_text(encoding="utf-8"))
        g3 = json.loads(G3_CONTROL.read_text(encoding="utf-8"))
        self.assertEqual(g3["references"][:2], g2["references"])
        self.assertEqual(g3["guide_contract"], g2["guide_contract"])
        self.assertEqual(g3["road_protection"], g2["road_protection"])
        self.assertEqual(g3["detail_protection"], g2["detail_protection"])

    def test_committed_g4_control_locks_only_the_narrow_protection_change(self) -> None:
        report = MODULE.preflight(G4_CONTROL)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["schema_path"], self._relative(G4_SCHEMA))
        self.assertEqual(report["road_guard_width_px"], 16)
        self.assertEqual(
            report["protection_policy"],
            "narrow-structural-intersection-v1",
        )
        self.assertEqual(
            report["generated_input"],
            {
                "path": self._relative(G3_RAW),
                "sha256": _sha256(G3_RAW),
                "format": "PNG",
                "mode": "RGB",
                "width": 1536,
                "height": 1024,
            },
        )

        g3 = json.loads(G3_CONTROL.read_text(encoding="utf-8"))
        g4 = json.loads(G4_CONTROL.read_text(encoding="utf-8"))
        for unchanged in (
            "canvas",
            "coordinate_space",
            "prompt",
            "references",
            "guide_contract",
            "skeleton_contract",
        ):
            self.assertEqual(g4[unchanged], g3[unchanged], unchanged)
        self.assertEqual(g4["generated_input"]["sha256"], _sha256(G3_RAW))
        self.assertEqual(
            g4["road_protection"]["strokes"], g3["road_protection"]["strokes"]
        )
        self.assertEqual(g4["road_protection"]["guard_width_px"], 16)
        self.assertEqual(g4["road_protection"]["feather_px"], 3)
        self.assertEqual(
            g4["detail_protection"],
            {
                "selection_operator": "high-frequency-and-dark",
                "gaussian_radius_px": 3,
                "high_frequency_threshold_levels": 18,
                "dark_luminance_max": 105,
                "feather_px": 1,
            },
        )

    def test_v3_schema_and_generated_input_lock_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sstory-g4-contract-", dir=REPO_ROOT
        ) as raw:
            root = Path(raw)
            control_path = root / "control.json"
            original = json.loads(G4_CONTROL.read_text(encoding="utf-8"))

            cases = []
            broad_road = json.loads(json.dumps(original))
            broad_road["road_protection"]["guard_width_px"] = 64
            cases.append(("broad-road", broad_road, "schema validation failed"))

            union_detail = json.loads(json.dumps(original))
            union_detail["detail_protection"]["selection_operator"] = (
                "high-frequency-or-dark"
            )
            cases.append(("union-detail", union_detail, "schema validation failed"))

            missing_operator = json.loads(json.dumps(original))
            del missing_operator["detail_protection"]["selection_operator"]
            cases.append(
                ("missing-operator", missing_operator, "schema validation failed")
            )

            wrong_raw_hash = json.loads(json.dumps(original))
            wrong_raw_hash["generated_input"]["sha256"] = "0" * 64
            cases.append(
                ("raw-hash", wrong_raw_hash, "generated input SHA-256 mismatch")
            )

            for label, candidate, error_pattern in cases:
                with self.subTest(label=label):
                    control_path.write_text(json.dumps(candidate), encoding="utf-8")
                    with self.assertRaisesRegex(
                        MODULE.ProtectedReliefError, error_pattern
                    ):
                        MODULE.preflight(control_path)

    def test_v3_generated_path_must_equal_the_locked_raw_path(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sstory-g4-path-", dir=REPO_ROOT
        ) as raw:
            root = Path(raw)
            outputs = self._outputs(root)
            with self.assertRaisesRegex(
                MODULE.ProtectedReliefError,
                "path differs from the v3 generated_input lock",
            ):
                MODULE.composite(
                    control_path=G4_CONTROL,
                    generated_path=G3_BASE,
                    output_path=outputs["output"],
                    mask_output_path=outputs["mask"],
                    protection_output_path=outputs["protection"],
                    report_path=outputs["report"],
                )
            self.assertTrue(all(not path.exists() for path in outputs.values()))

    def test_v3_intersection_is_a_strict_subset_of_the_legacy_union(self) -> None:
        g3 = json.loads(G3_CONTROL.read_text(encoding="utf-8"))
        g4 = json.loads(G4_CONTROL.read_text(encoding="utf-8"))
        with Image.open(G3_BASE) as base:
            legacy = MODULE._detail_core(base, g3)
            narrow = MODULE._detail_core(base, g4)
        try:
            self.assertEqual(MODULE._count_selected(legacy), 626255)
            self.assertEqual(MODULE._count_selected(narrow), 177238)
            outside_legacy = ImageChops.subtract(narrow, legacy)
            try:
                self.assertEqual(MODULE._count_selected(outside_legacy), 0)
            finally:
                outside_legacy.close()
        finally:
            legacy.close()
            narrow.close()

    def test_v3_branch_preserves_all_committed_g1_to_g3_decoded_rasters(self) -> None:
        for (
            control,
            generated,
            expected_output,
            expected_mask,
            expected_protection,
        ) in LEGACY_ARTIFACTS:
            with (
                self.subTest(control=control.name),
                tempfile.TemporaryDirectory(
                    prefix="sstory-legacy-protected-", dir=REPO_ROOT
                ) as raw,
            ):
                root = Path(raw)
                outputs = self._outputs(root)
                MODULE.composite(
                    control_path=control,
                    generated_path=generated,
                    output_path=outputs["output"],
                    mask_output_path=outputs["mask"],
                    protection_output_path=outputs["protection"],
                    report_path=outputs["report"],
                )
                self.assertEqual(
                    _semantic_sha256(outputs["output"]),
                    _semantic_sha256(expected_output),
                )
                self.assertEqual(
                    _semantic_sha256(outputs["mask"]),
                    _semantic_sha256(expected_mask),
                )
                self.assertEqual(
                    _semantic_sha256(outputs["protection"]),
                    _semantic_sha256(expected_protection),
                )

    def test_g4_narrow_policy_recovers_all_six_landform_footprints(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sstory-g4-diagnostic-", dir=REPO_ROOT
        ) as raw:
            root = Path(raw)
            outputs = self._outputs(root)
            report = MODULE.composite(
                control_path=G4_CONTROL,
                generated_path=G3_RAW,
                output_path=outputs["output"],
                mask_output_path=outputs["mask"],
                protection_output_path=outputs["protection"],
                report_path=outputs["report"],
            )

            self.assertEqual(
                report["parameters"]["protection_policy"],
                "narrow-structural-intersection-v1",
            )
            self.assertTrue(report["parameters"]["generated_input_locked"])
            self.assertEqual(
                report["parameters"]["selection_operator"],
                "high-frequency-and-dark",
            )
            self.assertEqual(report["metrics"]["permission_pixels"], 227663)
            self.assertEqual(report["metrics"]["editable_pixels"], 206223)
            self.assertEqual(report["metrics"]["road_core_pixels"], 27606)
            self.assertEqual(report["metrics"]["road_core_permission_pixels"], 7422)
            self.assertEqual(report["metrics"]["detail_core_pixels"], 177238)
            self.assertEqual(report["metrics"]["detail_core_permission_pixels"], 14765)
            for metric in report["metrics"]["gates"].values():
                self.assertEqual(metric["changed_pixels"], 0)
                self.assertEqual(metric["maximum_channel_difference"], 0)

            for role, expected in (
                ("output", G4_OUTPUT),
                ("mask", G4_MASK),
                ("protection", G4_PROTECTION),
            ):
                self.assertEqual(
                    _semantic_sha256(outputs[role]),
                    _semantic_sha256(expected),
                )
                self.assertEqual(report[f"{role}_sha256"], _sha256(outputs[role]))

            guide_source_path = (
                REPO_ROOT / "world/map-production/controls/"
                "style-candidate-g-v2-topology-guide.json"
            )
            source = json.loads(guide_source_path.read_text(encoding="utf-8"))
            samples = source["render_contract"]["samples_per_segment"]
            control = json.loads(G4_CONTROL.read_text(encoding="utf-8"))
            with (
                Image.open(G3_BASE) as base,
                Image.open(outputs["output"]) as output,
                Image.open(outputs["mask"]) as edit_mask,
            ):
                delta = ImageChops.difference(output, base)
                bands = delta.split()
                maximum_delta = ImageChops.lighter(
                    ImageChops.lighter(bands[0], bands[1]), bands[2]
                )
                over_five = maximum_delta.point(lambda value: 255 if value > 5 else 0)
                road_core = MODULE._draw_road_core(control, base.size)
                detail_core = MODULE._detail_core(base, control)
                try:
                    for shape in source["shapes"]:
                        footprint = Image.new("L", base.size, 0)
                        points = MODULE._sample_closed_catmull_rom(
                            [tuple(point) for point in shape["knots"]], samples
                        )
                        ImageDraw.Draw(footprint).polygon(points, fill=255)
                        try:
                            pixels = MODULE._count_selected(footprint)
                            edit_support = ImageChops.darker(edit_mask, footprint)
                            changed_support = ImageChops.darker(over_five, footprint)
                            road_overlap = ImageChops.darker(road_core, footprint)
                            detail_overlap = ImageChops.darker(detail_core, footprint)
                            try:
                                support_fraction = (
                                    MODULE._count_selected(edit_support) / pixels
                                )
                                changed_fraction = (
                                    MODULE._count_selected(changed_support) / pixels
                                )
                                road_fraction = (
                                    MODULE._count_selected(road_overlap) / pixels
                                )
                                detail_fraction = (
                                    MODULE._count_selected(detail_overlap) / pixels
                                )
                                mad = (
                                    sum(ImageStat.Stat(delta, mask=footprint).mean) / 3
                                )
                            finally:
                                edit_support.close()
                                changed_support.close()
                                road_overlap.close()
                                detail_overlap.close()

                            if shape["role"] == "main-massif":
                                self.assertGreaterEqual(support_fraction, 0.90)
                            else:
                                self.assertGreaterEqual(support_fraction, 0.70)
                                self.assertGreaterEqual(changed_fraction, 0.40)
                                self.assertGreaterEqual(mad, 5.0)
                            self.assertLessEqual(road_fraction, 0.13)
                            self.assertLessEqual(detail_fraction, 0.17)
                        finally:
                            footprint.close()
                finally:
                    delta.close()
                    for band in bands:
                        band.close()
                    maximum_delta.close()
                    over_five.close()
                    road_core.close()
                    detail_core.close()

    def test_g3_reference_three_never_changes_the_g2_derived_mask(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sstory-g3-protected-", dir=REPO_ROOT
        ) as raw:
            root = Path(raw)
            generated = root / "generated.png"
            with Image.open(G3_BASE) as base:
                base.save(generated, format="PNG", optimize=True)
            outputs = self._outputs(root)
            report = MODULE.composite(
                control_path=G3_CONTROL,
                generated_path=generated,
                output_path=outputs["output"],
                mask_output_path=outputs["mask"],
                protection_output_path=outputs["protection"],
                report_path=outputs["report"],
            )

            self.assertEqual(
                _semantic_sha256(outputs["mask"]),
                _semantic_sha256(G2_MASK),
            )
            self.assertEqual(report["metrics"]["permission_pixels"], 227663)
            self.assertEqual(
                report["parameters"]["permission_source_reference_index"], 2
            )
            self.assertEqual(
                report["parameters"]["skeleton_permission_contribution"], "none"
            )
            self.assertEqual(report["skeleton"]["landform_count"], 6)
            self.assertEqual(
                report["mask_sha256"],
                _sha256(outputs["mask"]),
            )

    def test_raster_semantic_hash_ignores_png_encoding_but_detects_one_pixel(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sstory-raster-semantic-", dir=REPO_ROOT
        ) as raw:
            root = Path(raw)
            first_path = root / "first.png"
            second_path = root / "second.png"
            changed_path = root / "changed.png"
            raster = Image.new("L", (16, 16))
            raster.putdata(bytes((index * 17) % 256 for index in range(256)))
            try:
                raster.save(
                    first_path, format="PNG", compress_level=0, optimize=False
                )
                raster.save(
                    second_path, format="PNG", compress_level=9, optimize=False
                )
                changed = raster.copy()
                changed.putpixel((7, 9), (changed.getpixel((7, 9)) + 1) % 256)
                try:
                    changed.save(
                        changed_path,
                        format="PNG",
                        compress_level=9,
                        optimize=False,
                    )
                finally:
                    changed.close()
            finally:
                raster.close()

            self.assertNotEqual(first_path.read_bytes(), second_path.read_bytes())
            self.assertEqual(
                _semantic_sha256(first_path), _semantic_sha256(second_path)
            )
            self.assertNotEqual(
                _semantic_sha256(first_path), _semantic_sha256(changed_path)
            )

    def test_g3_reference_three_hash_order_mode_and_dimensions_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sstory-g3-contract-", dir=REPO_ROOT
        ) as raw:
            root = Path(raw)
            control_path = root / "control.json"
            original = json.loads(G3_CONTROL.read_text(encoding="utf-8"))

            wrong_hash = json.loads(json.dumps(original))
            wrong_hash["references"][2]["sha256"] = "0" * 64
            control_path.write_text(json.dumps(wrong_hash), encoding="utf-8")
            with self.assertRaisesRegex(
                MODULE.ProtectedReliefError, "SHA-256 mismatch"
            ):
                MODULE.preflight(control_path)

            wrong_order = json.loads(json.dumps(original))
            wrong_order["references"][1], wrong_order["references"][2] = (
                wrong_order["references"][2],
                wrong_order["references"][1],
            )
            control_path.write_text(json.dumps(wrong_order), encoding="utf-8")
            with self.assertRaisesRegex(
                MODULE.ProtectedReliefError, "schema validation"
            ):
                MODULE.preflight(control_path)

            wrong_mode_path = root / "wrong-mode.png"
            wrong_mode = Image.new("L", (1536, 1024), 0)
            wrong_mode.save(wrong_mode_path, format="PNG")
            wrong_mode.close()
            wrong_mode_control = json.loads(json.dumps(original))
            wrong_mode_control["references"][2]["path"] = self._relative(
                wrong_mode_path
            )
            wrong_mode_control["references"][2]["sha256"] = _sha256(wrong_mode_path)
            control_path.write_text(json.dumps(wrong_mode_control), encoding="utf-8")
            with self.assertRaisesRegex(
                MODULE.ProtectedReliefError, "reference 3 skeleton mode must be RGB"
            ):
                MODULE.preflight(control_path)

            wrong_size_path = root / "wrong-size.png"
            wrong_size = Image.new("RGB", (512, 512), (1, 2, 3))
            wrong_size.save(wrong_size_path, format="PNG")
            wrong_size.close()
            wrong_size_control = json.loads(json.dumps(original))
            wrong_size_control["references"][2]["path"] = self._relative(
                wrong_size_path
            )
            wrong_size_control["references"][2]["sha256"] = _sha256(wrong_size_path)
            control_path.write_text(json.dumps(wrong_size_control), encoding="utf-8")
            with self.assertRaisesRegex(
                MODULE.ProtectedReliefError,
                "reference 3 skeleton dimensions must be",
            ):
                MODULE.preflight(control_path)

    def test_composite_preserves_outside_roads_and_detail_core(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sstory-g1-protected-", dir=REPO_ROOT
        ) as raw:
            root = Path(raw)
            fixture = self._build_fixture(root)
            outputs = self._outputs(root)
            report = self._run(fixture, outputs)

            self.assertEqual(report["status"], "passed")
            for metric in report["metrics"]["gates"].values():
                self.assertEqual(metric["changed_pixels"], 0)
                self.assertEqual(metric["maximum_channel_difference"], 0)
            self.assertGreater(report["metrics"]["editable_pixels"], 0)
            self.assertGreater(report["metrics"]["road_core_pixels"], 0)
            self.assertGreater(report["metrics"]["detail_core_pixels"], 0)

            with (
                Image.open(fixture["base"]) as base,
                Image.open(fixture["generated"]) as generated,
                Image.open(outputs["output"]) as output,
                Image.open(outputs["mask"]) as mask,
                Image.open(outputs["protection"]) as protection,
            ):
                self.assertEqual(output.mode, "RGB")
                self.assertEqual(mask.mode, "L")
                self.assertEqual(protection.mode, "L")
                self.assertEqual(output.getpixel((5, 5)), base.getpixel((5, 5)))
                self.assertEqual(output.getpixel((280, 60)), base.getpixel((280, 60)))
                self.assertEqual(output.getpixel((150, 90)), base.getpixel((150, 90)))
                self.assertEqual(
                    output.getpixel((60, 80)), generated.getpixel((60, 80))
                )
                self.assertEqual(mask.getpixel((280, 60)), 0)
                self.assertEqual(protection.getpixel((280, 60)), 255)

            self.assertEqual(_sha256(outputs["output"]), report["output_sha256"])
            self.assertEqual(_sha256(outputs["mask"]), report["mask_sha256"])
            self.assertEqual(
                _sha256(outputs["protection"]), report["protection_sha256"]
            )
            stored_report = json.loads(outputs["report"].read_text(encoding="utf-8"))
            self.assertEqual(stored_report, report)
            self._assert_no_temporary_files(root)

    def test_reference_hash_and_order_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sstory-g1-protected-", dir=REPO_ROOT
        ) as raw:
            root = Path(raw)
            fixture = self._build_fixture(root)
            control = json.loads(fixture["control"].read_text(encoding="utf-8"))
            cases = []

            wrong_hash = json.loads(json.dumps(control))
            wrong_hash["prompt"]["sha256"] = "0" * 64
            cases.append(("hash", wrong_hash, "generation prompt SHA-256 mismatch"))

            wrong_order = json.loads(json.dumps(control))
            wrong_order["references"].reverse()
            cases.append(("order", wrong_order, "schema validation failed"))

            for label, candidate, error_pattern in cases:
                with self.subTest(label=label):
                    fixture["control"].write_text(
                        json.dumps(candidate), encoding="utf-8"
                    )
                    with self.assertRaisesRegex(
                        MODULE.ProtectedReliefError, error_pattern
                    ):
                        MODULE.preflight(fixture["control"])
            self._assert_no_temporary_files(root)

    def test_generated_mode_failure_leaves_no_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sstory-g1-protected-", dir=REPO_ROOT
        ) as raw:
            root = Path(raw)
            fixture = self._build_fixture(root)
            outputs = self._outputs(root)
            rgba = Image.new("RGBA", (512, 320), (1, 2, 3, 255))
            rgba.save(fixture["generated"], format="PNG")
            rgba.close()

            with self.assertRaisesRegex(
                MODULE.ProtectedReliefError, "generated image mode must be RGB"
            ):
                self._run(fixture, outputs)
            self.assertTrue(all(not path.exists() for path in outputs.values()))
            self._assert_no_temporary_files(root)

    def test_no_overwrite_preserves_sentinel_and_creates_nothing_else(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sstory-g1-protected-", dir=REPO_ROOT
        ) as raw:
            root = Path(raw)
            fixture = self._build_fixture(root)
            outputs = self._outputs(root)
            sentinel = b"keep-me"
            outputs["output"].write_bytes(sentinel)

            with self.assertRaisesRegex(
                MODULE.ProtectedReliefError, "refusing to overwrite existing output"
            ):
                self._run(fixture, outputs)
            self.assertEqual(outputs["output"].read_bytes(), sentinel)
            self.assertTrue(
                all(
                    not path.exists()
                    for key, path in outputs.items()
                    if key != "output"
                )
            )
            self._assert_no_temporary_files(root)

    def test_atomic_install_failure_rolls_back_every_output(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sstory-g1-protected-", dir=REPO_ROOT
        ) as raw:
            root = Path(raw)
            fixture = self._build_fixture(root)
            outputs = self._outputs(root)
            real_link = MODULE.os.link
            calls = 0

            def fail_second(source, target):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected install failure")
                return real_link(source, target)

            with mock.patch.object(MODULE.os, "link", side_effect=fail_second):
                with self.assertRaisesRegex(OSError, "injected install failure"):
                    self._run(fixture, outputs)
            self.assertTrue(all(not path.exists() for path in outputs.values()))
            self._assert_no_temporary_files(root)

    def test_full_detail_protection_rejects_empty_editable_support(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sstory-g1-protected-", dir=REPO_ROOT
        ) as raw:
            root = Path(raw)
            fixture = self._build_fixture(root)
            outputs = self._outputs(root)
            control = json.loads(fixture["control"].read_text(encoding="utf-8"))
            control["detail_protection"]["dark_luminance_max"] = 254
            fixture["control"].write_text(json.dumps(control), encoding="utf-8")

            with self.assertRaisesRegex(
                MODULE.ProtectedReliefError, "removed all editable support"
            ):
                self._run(fixture, outputs)
            self.assertTrue(all(not path.exists() for path in outputs.values()))
            self._assert_no_temporary_files(root)


if __name__ == "__main__":
    unittest.main()
