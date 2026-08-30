import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageStat


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"

sys.path.insert(0, str(SCRIPT_DIR))

import render_phase5_reviewed_master as reviewed  # noqa: E402
import validate_resolution_contract as resolution  # noqa: E402


EXPECTED_GENERATION_SHEETS = (
    "sheet_region_royal_capital_region",
    "sheet_region_silver_plains_region",
    "sheet_region_soaring_mountains_region",
    "sheet_region_moonlit_forest_region",
    "sheet_region_emerald_plains_region",
    "sheet_region_port_zephia_region",
    "sheet_region_lumiera_arch_region",
    "sheet_region_emerald_belt_region",
    "sheet_region_red_sea_desert_region",
    "sheet_region_jade_oasis_region",
    "sheet_region_marineport_region",
    "sheet_region_atlantia_region",
    "sheet_region_time_port_region",
    "sheet_region_ethernia_core_region",
    "sheet_corridor_astralis_port_zephia",
    "sheet_settlement_astralis",
    "sheet_settlement_port_zephia",
)


class Phase5ReviewedMasterRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed.DEFAULT_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(
            prefix=".phase5-reviewed-renderer-test-",
            dir=reviewed.DEFAULT_OUTPUT_ROOT,
        )
        cls.output_dir = Path(cls.temporary.name)
        cls.report = reviewed.write_reviewed_master(
            output_dir=cls.output_dir,
            emit_masks=True,
        )
        cls.sources, cls.contract, cls.sheet, cls.validation = (
            reviewed.load_render_context()
        )

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_contract_locks_the_requested_sheet_and_exact_native_dimensions(self):
        self.assertTrue(self.validation["valid"], self.validation["errors"])
        self.assertEqual(
            self.sheet,
            {
                "sheet_id": "sheet_region_soaring_mountains_region",
                "sheet_type": "region",
                "bounds": [2950, 3050, 4300, 4200],
                "zoom_range": [4, 5],
                "native_zoom": 5,
                "pixel_bounds": [4833, 3330, 7046, 4587],
                "width": 2213,
                "height": 1257,
                "pixels": 2_781_741,
                "production_method": "imagegen-metatile",
                "metatiles": {
                    "columns": 2,
                    "rows": 1,
                    "count": 2,
                    "size_px": 2048,
                    "gutter_each_side_px": 256,
                    "stride_px": 1536,
                },
                "source_feature_id": "soaring_mountains_region",
            },
        )

    def test_exact_17_generation_sheet_contract_and_cli_modes(self):
        self.assertEqual(reviewed.generation_sheet_ids(), EXPECTED_GENERATION_SHEETS)
        self.assertEqual(len(reviewed.generation_sheet_ids()), 17)
        self.assertTrue(reviewed.parse_args(["--all-generation"]).all_generation)
        self.assertTrue(
            reviewed.parse_args(["--representative-six"]).representative_six
        )
        self.assertTrue(
            reviewed.parse_args(["--all-generation-masks"]).all_generation_masks
        )
        with self.assertRaises(SystemExit):
            reviewed.parse_args(["--all-generation", "--representative-six"])

    def test_writer_emits_rgb_master_contacts_and_observed_masks(self):
        sheet_id = "sheet_region_soaring_mountains_region"
        master = self.output_dir / f"{sheet_id}.png"
        contact = self.output_dir / f"{sheet_id}.contact-sheet.png"
        report_path = self.output_dir / f"{sheet_id}.report.json"
        land_sea = self.output_dir / f"{sheet_id}.observed-land-sea-mask.png"
        transport = self.output_dir / f"{sheet_id}.observed-transport-mask.png"
        self.assertEqual(
            sorted(path.name for path in self.output_dir.iterdir()),
            sorted(
                (
                    master.name,
                    contact.name,
                    report_path.name,
                    land_sea.name,
                    transport.name,
                )
            ),
        )
        with Image.open(master) as image:
            image.load()
            self.assertEqual(
                (image.format, image.mode, image.size), ("PNG", "RGB", (2213, 1257))
            )
        with Image.open(contact) as image:
            image.load()
            self.assertEqual(
                (image.format, image.mode, image.size), ("PNG", "RGB", (1568, 288))
            )
        for mask_path in (land_sea, transport):
            with Image.open(mask_path) as image:
                image.load()
                self.assertEqual(
                    (image.format, image.mode, image.size), ("PNG", "L", (2213, 1257))
                )

        document = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(document, self.report)
        self.assertEqual(document["generated_by"]["id"], reviewed.GENERATOR_ID)
        self.assertEqual(document["status"], "pending-golden-style")
        self.assertEqual(document["inputs"]["golden_style"]["status"], "pending-h7")
        material_atlas = document["inputs"]["material_atlas"]
        self.assertEqual(material_atlas["status"], "locked")
        self.assertEqual(material_atlas["sha256"], reviewed.MATERIAL_ATLAS_SHA256)
        self.assertEqual(
            material_atlas["renderer_sha256"],
            document["generated_by"]["sha256"],
        )
        self.assertEqual(
            set(material_atlas["safe_crops"]),
            set(reviewed.MATERIAL_ATLAS_CROPS),
        )
        self.assertFalse(
            material_atlas["transfer_filter"]["roads_rivers_coasts_cities_buildings_transferred"]
        )
        self.assertTrue(
            material_atlas["transfer_filter"]["explicit_zero_mean_per_channel"]
        )
        self.assertTrue(
            material_atlas["placement"]["deterministic_low_frequency_strength_noise"]
        )
        self.assertEqual(
            material_atlas["placement"]["semantic_mask_feather_px_range"],
            [64, 160],
        )
        self.assertEqual(
            material_atlas["placement"]["parent_mask_outside_pixels_modified"],
            0,
        )
        self.assertFalse(document["style"]["contains_text"])
        self.assertFalse(document["style"]["font_rendering_used"])
        self.assertFalse(document["style"]["contains_frame"])
        self.assertFalse(document["transform"]["source_coordinates_modified"])
        self.assertFalse(document["transform"]["world_crop_or_upscale_used"])
        self.assertTrue(document["anchoring"]["same_world_coordinate_same_pattern"])
        self.assertFalse(document["stroke_contract"]["canonical_centerlines_modified"])
        self.assertEqual(len(document["sources"]), 6)
        for source in document["sources"]:
            self.assertEqual(len(source["sha256"]), 64)
        terrain = next(
            source for source in document["sources"] if source["role"] == "terrain"
        )
        self.assertIn(
            "elysion_soaring_mountains_axis", terrain["intersecting_feature_ids"]
        )

    def test_mask_only_batch_matches_all_17_hash_locked_controls(self):
        with tempfile.TemporaryDirectory(
            prefix=".phase5-mask-only-test-",
            dir=reviewed.DEFAULT_OUTPUT_ROOT,
        ) as directory:
            output_dir = Path(directory)
            report = reviewed.write_generation_mask_batch(output_dir=output_dir)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["sheet_count"], 17)
            self.assertEqual(
                [item["sheet_id"] for item in report["results"]],
                list(EXPECTED_GENERATION_SHEETS),
            )
            self.assertGreaterEqual(
                min(item["land_sea_match_ratio"] for item in report["results"]),
                0.9999999,
            )
            self.assertGreaterEqual(
                min(
                    item["transport_exact_match_ratio"]
                    for item in report["results"]
                ),
                0.9999999,
            )
            output_names = {path.name for path in output_dir.iterdir()}
            self.assertEqual(len(output_names), 35)
            self.assertFalse(
                any(name.endswith(".contact-sheet.png") for name in output_names)
            )

    def test_render_is_deterministic_and_does_not_mutate_source_coordinates(self):
        canonical_before = json.dumps(
            self.sources,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        image, stats = reviewed.render_reviewed_master(
            self.sources,
            self.contract,
            self.sheet,
        )
        try:
            buffer = io.BytesIO()
            image.save(buffer, **reviewed.PNG_OPTIONS)
            digest = hashlib.sha256(buffer.getvalue()).hexdigest()
        finally:
            image.close()
        canonical_after = json.dumps(
            self.sources,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(canonical_before, canonical_after)
        self.assertEqual(digest, self.report["outputs"]["master"]["sha256"])
        self.assertEqual(stats, self.report["render_stats"])

    def test_global_transform_and_hash_grid_are_sheet_independent(self):
        first = reviewed.SheetCanvasTransform(self.contract, self.sheet)
        overlap_bounds = [3000, 3100, 4400, 4250]
        pixel_bounds = resolution.calculate_pixel_bounds(
            overlap_bounds,
            self.sheet["native_zoom"],
            self.contract,
        )
        second_sheet = {
            **self.sheet,
            "bounds": overlap_bounds,
            "pixel_bounds": list(pixel_bounds),
            "width": pixel_bounds[2] - pixel_bounds[0],
            "height": pixel_bounds[3] - pixel_bounds[1],
        }
        second = reviewed.SheetCanvasTransform(self.contract, second_sheet)
        world_point = (3540.0, 3480.0)
        self.assertEqual(
            first.global_point(world_point), second.global_point(world_point)
        )
        self.assertEqual(
            (
                first.point(world_point)[0] + first.pixel_bounds[0],
                first.point(world_point)[1] + first.pixel_bounds[1],
            ),
            (
                second.point(world_point)[0] + second.pixel_bounds[0],
                second.point(world_point)[1] + second.pixel_bounds[1],
            ),
        )
        self.assertEqual(
            (
                first.point_fast(world_point)[0] + first.pixel_bounds[0],
                first.point_fast(world_point)[1] + first.pixel_bounds[1],
            ),
            (
                second.point_fast(world_point)[0] + second.pixel_bounds[0],
                second.point_fast(world_point)[1] + second.pixel_bounds[1],
            ),
        )

        def anchors(transform):
            return {
                (grid_x, grid_y): (world_x, world_y, digest)
                for grid_x, grid_y, world_x, world_y, digest in reviewed.iter_anchored_grid(
                    transform,
                    cell_world=19,
                    namespace="same-feature:test-anchor",
                    seed=reviewed.DEFAULT_SEED,
                )
            }

        first_anchors = anchors(first)
        second_anchors = anchors(second)
        shared = first_anchors.keys() & second_anchors.keys()
        self.assertGreater(len(shared), 100)
        for key in shared:
            self.assertEqual(first_anchors[key], second_anchors[key])

    def test_region_washes_match_at_same_world_pixels_across_overlapping_sheets(self):
        def sheet_for(bounds):
            pixel_bounds = resolution.calculate_pixel_bounds(
                bounds, 5, self.contract
            )
            return {
                "bounds": bounds,
                "native_zoom": 5,
                "pixel_bounds": list(pixel_bounds),
                "width": pixel_bounds[2] - pixel_bounds[0],
                "height": pixel_bounds[3] - pixel_bounds[1],
            }

        first_transform = reviewed.SheetCanvasTransform(
            self.contract, sheet_for([3000, 3000, 3500, 3500])
        )
        second_transform = reviewed.SheetCanvasTransform(
            self.contract, sheet_for([3150, 3100, 3650, 3600])
        )
        feature = {
            "type": "Feature",
            "properties": {
                "id": "overlap_region",
                "region_type": "forest_region",
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [3050, 3050],
                        [3550, 3050],
                        [3550, 3550],
                        [3050, 3550],
                        [3050, 3050],
                    ]
                ],
            },
        }
        images = []
        masks = []
        try:
            for transform in (first_transform, second_transform):
                image = Image.new("RGBA", (transform.width, transform.height), (193, 173, 118, 255))
                land = Image.new("L", image.size, 255)
                reviewed._draw_region_washes(image, [feature], land, transform)
                images.append(image)
                masks.append(land)

            global_left, global_top = first_transform.global_point((3250, 3250))
            global_right, global_bottom = first_transform.global_point((3400, 3400))

            def local_box(transform):
                left, top, _, _ = transform.pixel_bounds
                return (
                    global_left - left,
                    global_top - top,
                    global_right - left,
                    global_bottom - top,
                )

            first_crop = images[0].crop(local_box(first_transform))
            second_crop = images[1].crop(local_box(second_transform))
            try:
                self.assertIsNone(ImageChops.difference(first_crop, second_crop).getbbox())
            finally:
                first_crop.close()
                second_crop.close()
        finally:
            for image in images:
                image.close()
            for mask in masks:
                mask.close()

    def test_region_wash_skips_non_intersecting_feature_without_tinting_land(self):
        transform = reviewed.SheetCanvasTransform(self.contract, self.sheet)
        image = Image.new("RGBA", (transform.width, transform.height), (193, 173, 118, 255))
        before = image.copy()
        land = Image.new("L", image.size, 255)
        feature = {
            "type": "Feature",
            "properties": {"id": "outside", "region_type": "forest_region"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
                ],
            },
        }
        try:
            reviewed._draw_region_washes(image, [feature], land, transform)
            self.assertIsNone(ImageChops.difference(before, image).getbbox())
        finally:
            before.close()
            land.close()
            image.close()

    def test_pixel_stroke_caps_keep_exact_centerlines_thin_at_native_zoom(self):
        stats = self.report["render_stats"]
        caps = reviewed.STROKE_CAPS_PX["region"]
        self.assertLessEqual(stats["river_core_max_px"], caps["river"])
        self.assertLessEqual(stats["river_casing_max_px"], caps["river_casing"])
        self.assertLessEqual(stats["road_core_max_px"], caps["road"])
        self.assertLessEqual(stats["road_casing_max_px"], caps["road_casing"])
        self.assertEqual(stats["river_centerline_coordinate_offsets"], 0)
        self.assertEqual(stats["transport_centerline_coordinate_offsets"], 0)
        self.assertEqual(stats["coast_centerline_coordinate_offsets"], 0)

    def test_flat_canopy_settlement_and_forbidden_symbol_contract(self):
        stats = self.report["render_stats"]
        self.assertGreater(stats["forest_canopy_masses"], 100)
        self.assertGreater(stats["forest_density_micro_marks"], 500)
        self.assertGreater(stats["forest_clearings"], 0)
        self.assertGreater(stats["mountain_short_strokes"], 500)
        self.assertGreater(stats["mountain_irregular_rocks"], 80)
        self.assertGreater(stats["mountain_hypsometric_bands"], 0)
        self.assertGreater(stats["mountain_ridge_axes"], 0)
        self.assertGreater(stats["settlement_building_footprints"], 500)
        self.assertGreater(stats["settlement_main_streets"], 0)
        self.assertGreater(stats["settlement_secondary_streets"], 0)
        self.assertGreater(stats["settlement_lanes"], 0)
        self.assertGreater(stats["settlement_courtyards"], 100)
        self.assertGreater(stats["settlement_environs_parcels"], 0)
        self.assertGreater(stats["capital_landscape_parcels"], 100)
        self.assertGreater(stats["capital_landscape_villages"], 0)
        self.assertGreater(stats["riparian_vegetation"], 0)
        self.assertGreater(stats["wetland_marks"], 0)
        self.assertGreater(stats["bridge_footprints"], 0)
        self.assertGreaterEqual(stats["settlement_cell_world_min"], 1.5)
        self.assertLessEqual(stats["settlement_cell_world_max"], 3.0)
        self.assertEqual(stats["settlement_rectangular_grid_blocks"], 0)
        self.assertEqual(stats["material_atlas_safe_crop_count"], 5)
        self.assertGreater(stats["material_atlas_patches"], 0)
        self.assertEqual(stats["material_atlas_outside_parent_pixel_changes"], 0)
        self.assertEqual(stats["material_atlas_low_frequency_shapes_transferred"], 0)
        self.assertEqual(stats["material_atlas_semantic_shapes_transferred"], 0)
        self.assertTrue(stats["material_atlas_zero_mean_checks_passed"])
        self.assertTrue(stats["material_atlas_boundary_contrast_checks_passed"])
        self.assertLessEqual(
            stats["material_atlas_maximum_boundary_contrast_luma_levels"],
            stats["material_atlas_boundary_contrast_limit_luma_levels"],
        )
        for name, crop in stats["material_atlas_crops"].items():
            residual = crop["residual_zero_mean"]
            if residual is None:
                continue
            self.assertTrue(residual["explicit_zero_mean_per_channel"], name)
            self.assertEqual(residual["post_zero_mean_rgb_levels"], [0.0, 0.0, 0.0])
            self.assertTrue(residual["weighted_variants_passed"], name)
            self.assertLessEqual(
                crop["application"]["strength"],
                crop["application"]["strength_limit"],
            )
            self.assertGreaterEqual(
                crop["application"]["semantic_mask_feather_px"], 64
            )
            self.assertLessEqual(
                crop["application"]["semantic_mask_feather_px"], 160
            )
            self.assertTrue(crop["semantic_boundary_contrast"]["passed"], name)
        self.assertEqual(stats["forbidden_total"], 0)
        self.assertEqual(
            {counter: stats[counter] for counter in reviewed.FORBIDDEN_COUNTERS},
            {counter: 0 for counter in reviewed.FORBIDDEN_COUNTERS},
        )
        self.assertGreater(stats["river_canonical_control_vertices_preserved"], 0)
        self.assertIn("Catmull-Rom", stats["river_visual_interpolation"])

    def test_zoom_lod_adds_real_detail_from_region_to_settlement(self):
        region = reviewed._settlement_lod_profile(5, "capital")
        corridor = reviewed._settlement_lod_profile(7, "capital")
        settlement = reviewed._settlement_lod_profile(8, "capital")
        self.assertEqual(
            [region["level"], corridor["level"], settlement["level"]],
            ["district-block", "parcel", "building"],
        )
        self.assertGreater(region["cell_world"], corridor["cell_world"])
        self.assertGreater(corridor["cell_world"], settlement["cell_world"])

    def test_all_canonical_terrain_types_have_plan_view_vocabulary(self):
        terrain_types = {
            feature["properties"]["terrain_type"]
            for feature in self.sources["terrain"]["features"]
        }
        self.assertEqual(terrain_types, reviewed.SUPPORTED_TERRAIN_TYPES)
        self.assertEqual(
            set(self.report["render_stats"]["terrain_types_supported"]),
            terrain_types,
        )
        for terrain_type in (
            "temperate_plains",
            "hot_desert",
            "volcanic_land",
            "arcane_highlands",
            "tundra_permafrost",
            "floating_island_chain",
        ):
            self.assertIn(f"terrain_{terrain_type}", self.report["render_stats"])
        self.assertIn("terrain_mountain_axis", self.report["render_stats"])
        self.assertIn("terrain_gorge_axis", self.report["render_stats"])
        self.assertIn("temperate_forest_clusters", self.report["render_stats"])
        self.assertIn("tropical_forest_clusters", self.report["render_stats"])

    def test_contact_sheet_records_25_50_and_100_percent_views(self):
        panels = self.report["outputs"]["contact_sheet"]["panel_order"]
        self.assertEqual(
            [panel["label"] for panel in panels],
            ["25-percent", "50-percent", "100-percent"],
        )
        self.assertEqual(
            [panel["effective_scale"] for panel in panels],
            [0.25, 0.5, 1.0],
        )
        self.assertTrue(all(panel["panel_size_px"] == [512, 288] for panel in panels))

    def test_representative_ecology_contact_sheet_is_unlabelled_and_ordered(self):
        with tempfile.TemporaryDirectory(
            prefix=".phase5-reviewed-contact-test-",
            dir=reviewed.DEFAULT_OUTPUT_ROOT,
        ) as directory:
            root = Path(directory)
            paths = []
            for index, sheet_id in enumerate(reviewed.REPRESENTATIVE_SHEET_IDS):
                path = root / f"{sheet_id}.png"
                Image.new("RGB", (80 + index, 60 + index), (90 + index, 80, 60)).save(
                    path,
                    **reviewed.PNG_OPTIONS,
                )
                paths.append(path)
            contact, panels = reviewed.render_ecology_contact_sheet(
                paths,
                reviewed.REPRESENTATIVE_SHEET_IDS,
            )
            try:
                self.assertEqual(contact.mode, "RGB")
                self.assertEqual(contact.size, (1464, 612))
                self.assertEqual(
                    [panel["sheet_id"] for panel in panels],
                    list(reviewed.REPRESENTATIVE_SHEET_IDS),
                )
            finally:
                contact.close()

    def test_golden_style_requires_an_exact_path_and_sha_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "future-h7-golden.png"
            Image.new("RGB", (96, 64), (126, 111, 77)).save(path)
            digest = reviewed.sha256_file(path)
            record = reviewed._golden_style_lock(path, digest)
            self.assertEqual(record["status"], "locked")
            self.assertEqual(record["sha256"], digest)
            self.assertTrue(record["derived_style_statistics"])
            self.assertEqual(record["copied_pixels"], 0)
            self.assertFalse(record["used_as_geometry"])
            with self.assertRaisesRegex(reviewed.ReviewedMasterError, "mismatch"):
                reviewed._golden_style_lock(path, "0" * 64)
        with self.assertRaisesRegex(reviewed.ReviewedMasterError, "both a path"):
            reviewed._golden_style_lock(Path("missing.png"), None)

    def test_pending_golden_statistics_are_explicitly_preview_only_and_unpromotable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pending-golden.png"
            image = Image.new("RGB", (96, 64), (126, 111, 77))
            draw = ImageDraw.Draw(image)
            for offset in range(4, 92, 9):
                draw.line((offset, 3, offset - 7, 60), fill=(61, 55, 40), width=1)
            image.save(path)
            image.close()
            record = reviewed._golden_style_lock(
                path,
                reviewed.sha256_file(path),
                preview_only=True,
            )
            self.assertEqual(record["status"], "locked-preview-only")
            self.assertFalse(record["promotion_eligible"])
            profile = record["style_profile"]
            self.assertEqual(
                profile["profile_type"],
                "non-spatial-cartographic-style-statistics",
            )
            transfer = profile["transfer_contract"]
            self.assertFalse(transfer["used_as_geometry"])
            self.assertEqual(transfer["copied_pixels"], 0)
            self.assertEqual(transfer["copied_masks"], 0)
            self.assertEqual(transfer["copied_coordinates"], 0)
            self.assertFalse(transfer["local_descriptors_retained"])
            self.assertFalse(transfer["whole_image_histogram_matching"])
            self.assertEqual(len(profile["profile_sha256"]), 64)
        with self.assertRaisesRegex(reviewed.ReviewedMasterError, "preview-only"):
            reviewed._golden_style_lock(None, None, preview_only=True)

    def test_capital_parcel_vertices_are_shared_ea_coordinates_not_sheet_rectangles(self):
        first = reviewed._capital_parcel_vertex_world(
            71,
            83,
            cell_world=47.0,
            capital_id="astralis",
            seed=reviewed.DEFAULT_SEED,
        )
        second = reviewed._capital_parcel_vertex_world(
            71,
            83,
            cell_world=47.0,
            capital_id="astralis",
            seed=reviewed.DEFAULT_SEED,
        )
        neighbor_shared = reviewed._capital_parcel_vertex_world(
            71,
            83,
            cell_world=47.0,
            capital_id="astralis",
            seed=reviewed.DEFAULT_SEED,
        )
        self.assertEqual(first, second)
        self.assertEqual(first, neighbor_shared)
        self.assertNotEqual(first[0], 71 * 47.0)
        self.assertNotEqual(first[1], 83 * 47.0)

    def test_new_flat_material_and_transport_contract_counters_are_explicit(self):
        stats = self.report["render_stats"]
        self.assertEqual(stats["capital_landscape_isolated_rectangular_parcels"], 0)
        self.assertGreater(stats["capital_landscape_shared_boundary_edges"], 0)
        self.assertEqual(stats["capital_landscape_quiet_corridors"], 2)
        self.assertGreater(
            stats["capital_landscape_canonical_settlement_pixels_protected"], 0
        )
        self.assertEqual(stats["transport_canonical_thread_visible_inside_urban"], 1)
        self.assertEqual(stats["transport_inside_urban_control_only"], 1)
        self.assertFalse(stats["golden_style_statistics_applied"])
        self.assertEqual(stats["golden_style_copied_pixels"], 0)
        self.assertFalse(stats["golden_style_used_as_geometry"])

    def test_material_atlas_locks_exact_original_safe_crop_rectangles_and_hashes(self):
        record = reviewed._material_atlas_record()
        self.assertEqual(record["sha256"], reviewed.MATERIAL_ATLAS_SHA256)
        self.assertEqual(
            (record["width"], record["height"]),
            reviewed.MATERIAL_ATLAS_SIZE,
        )
        self.assertEqual(
            set(record["safe_crops"]),
            {
                "connected_forest",
                "cultivated_hatching",
                "wetland",
                "neutral_parchment",
                "flat_rock_hachure",
            },
        )
        for name, spec in reviewed.MATERIAL_ATLAS_CROPS.items():
            crop = record["safe_crops"][name]
            self.assertEqual(crop["rect_px"], list(spec["rect_px"]))
            self.assertEqual(crop["raw_rgb_sha256"], spec["raw_rgb_sha256"])
            self.assertEqual(crop["frequency_transfer"], "signed-rgb-high-pass-only")
            self.assertTrue(crop["zero_mean_per_channel"])
            self.assertLessEqual(crop["strength"], crop["strength_limit"])
            self.assertGreaterEqual(crop["semantic_mask_feather_px"], 64)
            self.assertLessEqual(crop["semantic_mask_feather_px"], 160)
            self.assertTrue(crop["usage_masks"])
        self.assertEqual(
            record["excluded_material"],
            list(reviewed.MATERIAL_ATLAS_EXCLUSIONS),
        )

    def test_atlas_crop_compositor_preserves_every_pixel_outside_parent_mask(self):
        bounds = [3000, 3000, 3100, 3100]
        pixel_bounds = resolution.calculate_pixel_bounds(bounds, 5, self.contract)
        sheet = {
            "bounds": bounds,
            "native_zoom": 5,
            "pixel_bounds": list(pixel_bounds),
            "width": pixel_bounds[2] - pixel_bounds[0],
            "height": pixel_bounds[3] - pixel_bounds[1],
        }
        transform = reviewed.SheetCanvasTransform(self.contract, sheet)
        image = Image.new("RGBA", (transform.width, transform.height), (151, 127, 84, 255))
        before = image.copy()
        mask = Image.new("L", image.size, 0)
        ImageDraw.Draw(mask).ellipse((18, 14, image.width - 19, image.height - 15), fill=255)
        with Image.open(reviewed.DEFAULT_MATERIAL_ATLAS) as atlas:
            atlas.load()
            spec = reviewed.MATERIAL_ATLAS_CROPS["connected_forest"]
            crop = atlas.convert("RGB").crop(tuple(spec["rect_px"]))
        try:
            stats = reviewed._apply_atlas_crop_material(
                image,
                mask,
                transform,
                reviewed.DEFAULT_SEED,
                "connected_forest",
                crop,
            )
            difference = ImageChops.difference(before, image).convert("L")
            outside = ImageOps.invert(mask)
            outside_difference = ImageChops.multiply(difference, outside)
            self.assertIsNone(outside_difference.getbbox())
            self.assertEqual(stats["outside_parent_pixel_changes"], 0)
            self.assertGreater(stats["patches"], 0)
        finally:
            crop.close()
            mask.close()
            before.close()
            image.close()

    def test_atlas_residual_is_exactly_zero_mean_per_rgb_channel(self):
        with Image.open(reviewed.DEFAULT_MATERIAL_ATLAS) as atlas_source:
            atlas = atlas_source.convert("RGB")
        try:
            for name, spec in reviewed.MATERIAL_ATLAS_CROPS.items():
                crop = atlas.crop(tuple(spec["rect_px"]))
                try:
                    residual, stats = reviewed._zero_mean_high_frequency_residual(
                        crop
                    )
                    try:
                        self.assertEqual(
                            stats["post_zero_mean_rgb_levels"],
                            [0.0, 0.0, 0.0],
                            name,
                        )
                        self.assertTrue(
                            stats["explicit_zero_mean_per_channel"], name
                        )
                        self.assertFalse(
                            stats["source_low_frequency_colour_copied"], name
                        )
                        means = ImageStat.Stat(residual).mean
                        for mean in means:
                            self.assertAlmostEqual(mean, 128.0, places=9)
                    finally:
                        residual.close()
                finally:
                    crop.close()
        finally:
            atlas.close()

    def test_full_spatial_preview_record_retains_only_approved_crop_material(self):
        record = reviewed._material_atlas_record(
            transfer_mode=reviewed.FULL_SPATIAL_MATERIAL_MODE
        )
        self.assertEqual(
            record["transfer_mode"], reviewed.FULL_SPATIAL_MATERIAL_MODE
        )
        self.assertEqual(
            record["transfer_filter"]["frequency_band"],
            "full-approved-spatial",
        )
        self.assertTrue(
            record["transfer_filter"]["low_frequency_semantic_shapes_retained"]
        )
        self.assertFalse(
            record["transfer_filter"][
                "roads_rivers_coasts_cities_buildings_transferred"
            ]
        )
        self.assertTrue(
            record["placement"]["deterministic_nonperiodic_source_selection"]
        )
        for name, crop in record["safe_crops"].items():
            self.assertEqual(
                crop["frequency_transfer"], "full-approved-spatial-material", name
            )
            self.assertTrue(crop["low_frequency_material_retained"], name)
            self.assertGreater(crop["patch_world"], crop["stride_world"], name)

    def test_full_spatial_quilt_is_deterministic_and_cannot_escape_parent_mask(self):
        bounds = [3000, 3000, 3120, 3120]
        pixel_bounds = resolution.calculate_pixel_bounds(bounds, 5, self.contract)
        sheet = {
            "bounds": bounds,
            "native_zoom": 5,
            "pixel_bounds": list(pixel_bounds),
            "width": pixel_bounds[2] - pixel_bounds[0],
            "height": pixel_bounds[3] - pixel_bounds[1],
        }
        transform = reviewed.SheetCanvasTransform(self.contract, sheet)
        mask = Image.new("L", (transform.width, transform.height), 0)
        ImageDraw.Draw(mask).ellipse(
            (12, 10, transform.width - 13, transform.height - 11), fill=255
        )
        clip = Image.new("L", mask.size, 255)
        first = Image.new("RGBA", mask.size, (183, 164, 112, 255))
        second = first.copy()
        before = first.copy()
        with Image.open(reviewed.DEFAULT_MATERIAL_ATLAS) as atlas_source:
            atlas = atlas_source.convert("RGB")
            spec = reviewed.MATERIAL_ATLAS_CROPS["connected_forest"]
            crop = atlas.crop(tuple(spec["rect_px"]))
        try:
            records = []
            for target in (first, second):
                records.append(
                    reviewed._apply_atlas_crop_full_spatial_material(
                        target,
                        mask,
                        transform,
                        reviewed.DEFAULT_SEED,
                        "connected_forest",
                        crop,
                        canonical_clip=clip,
                        style_profile=None,
                    )
                )
            self.assertIsNone(ImageChops.difference(first, second).getbbox())
            self.assertEqual(records[0], records[1])
            self.assertGreater(records[0]["patches"], 0)
            self.assertGreater(records[0]["unique_source_window_transforms"], 1)
            self.assertTrue(
                records[0]["normalisation"]["source_low_frequency_material_retained"]
            )
            difference = ImageChops.difference(before, first).convert("L")
            inverse = ImageOps.invert(mask)
            outside = ImageChops.multiply(difference, inverse)
            try:
                self.assertIsNone(outside.getbbox())
            finally:
                difference.close()
                inverse.close()
                outside.close()
        finally:
            crop.close()
            atlas.close()
            before.close()
            first.close()
            second.close()
            clip.close()
            mask.close()

    def test_full_material_water_and_river_layers_stay_masked_and_planar(self):
        bounds = [3000, 3000, 3200, 3180]
        pixel_bounds = resolution.calculate_pixel_bounds(bounds, 5, self.contract)
        sheet = {
            "bounds": bounds,
            "native_zoom": 5,
            "pixel_bounds": list(pixel_bounds),
            "width": pixel_bounds[2] - pixel_bounds[0],
            "height": pixel_bounds[3] - pixel_bounds[1],
        }
        transform = reviewed.SheetCanvasTransform(self.contract, sheet)
        image = Image.new("RGBA", (transform.width, transform.height), (77, 113, 130, 255))
        before = image.copy()
        water = Image.new("L", image.size, 0)
        ImageDraw.Draw(water).rectangle(
            (8, 8, image.width - 9, image.height - 9), fill=255
        )
        try:
            water_stats = reviewed._draw_water_texture(
                image,
                water,
                transform,
                reviewed.DEFAULT_SEED,
                full_material_preview=True,
            )
            self.assertGreater(water_stats["water_mottle_patches"], 0)
            self.assertGreater(water_stats["water_symmetric_wavelets"], 0)
            difference = ImageChops.difference(before, image).convert("L")
            inverse = ImageOps.invert(water)
            outside = ImageChops.multiply(difference, inverse)
            try:
                self.assertIsNone(outside.getbbox())
            finally:
                difference.close()
                inverse.close()
                outside.close()

            river = {
                "type": "Feature",
                "properties": {
                    "id": "test_river",
                    "water_type": "river_system",
                    "nominal_width": 18,
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[3010, 3090], [3080, 3050], [3190, 3110]],
                },
            }
            river_stats = reviewed._draw_rivers(
                image,
                [river],
                transform,
                "region",
                reviewed.DEFAULT_SEED,
                full_material_preview=True,
            )
            self.assertEqual(river_stats["river_layered_channels"], 1)
            self.assertEqual(river_stats["river_inner_flow_threads"], 1)
            self.assertEqual(river_stats["river_uniform_solid_bands"], 0)
        finally:
            water.close()
            before.close()
            image.close()

    def test_river_catmull_rom_curve_preserves_every_canonical_vertex(self):
        canonical = [(5, 30), (35, 12), (62, 46), (96, 18), (130, 35)]
        curved, displacement = reviewed._catmull_rom_pixel_path(canonical)
        self.assertEqual(curved[0], canonical[0])
        self.assertEqual(curved[-1], canonical[-1])
        self.assertTrue(all(vertex in curved for vertex in canonical))
        self.assertGreater(len(curved), len(canonical))
        self.assertGreater(displacement, 0.0)
        self.assertLessEqual(displacement, 14.5)

    def test_batch_rejects_non_generation_sheet_before_writing(self):
        with self.assertRaisesRegex(reviewed.ReviewedMasterError, "non-generation"):
            reviewed.write_generation_batch(
                sheet_ids=("sheet_world",),
                output_dir=self.output_dir / "invalid-batch",
            )

    def test_output_safety_rejects_paths_outside_v2_root(self):
        with self.assertRaisesRegex(
            reviewed.ReviewedMasterError,
            "reviewed v2 output must stay below",
        ):
            reviewed._validate_output_dir(REPO_ROOT / "world")


if __name__ == "__main__":
    unittest.main()
