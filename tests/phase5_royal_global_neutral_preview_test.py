import inspect
import sys
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageStat


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import render_phase5_reviewed_master as renderer  # noqa: E402
import validate_resolution_contract as resolution  # noqa: E402


def _sheet(
    contract: dict,
    bounds: list[int],
    *,
    sheet_id: str = "synthetic-overlap",
) -> dict:
    pixel_bounds = resolution.calculate_pixel_bounds(bounds, 5, contract)
    return {
        "sheet_id": sheet_id,
        "sheet_type": "region",
        "bounds": bounds,
        "native_zoom": 5,
        "pixel_bounds": list(pixel_bounds),
        "width": pixel_bounds[2] - pixel_bounds[0],
        "height": pixel_bounds[3] - pixel_bounds[1],
    }


def _empty_sources() -> dict[str, dict]:
    return {
        role: {"type": "FeatureCollection", "features": []}
        for role in (
            "landmasses",
            "terrain",
            "regions",
            "hydrography",
            "transport",
            "settlements",
        )
    }


class Phase5RoyalGlobalNeutralPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = renderer._load_json(renderer.DEFAULT_CONTRACT)

    def test_global_neutral_material_does_not_accept_semantic_masks(self):
        parameters = inspect.signature(
            renderer._draw_global_neutral_land_material
        ).parameters
        self.assertNotIn("semantic_masks", parameters)
        self.assertNotIn("usage_masks", parameters)
        record = renderer._global_neutral_material_record()
        self.assertEqual(record["placement"]["semantic_usage_masks"], 0)
        self.assertFalse(record["source_semantic_geometry_transferred"])

    def test_global_neutral_material_is_zero_mean_and_band_limited(self):
        with Image.open(renderer.DEFAULT_GLOBAL_NEUTRAL_MATERIAL) as opened:
            source = opened.convert("RGB")
        try:
            residual, record = renderer._prepare_global_neutral_bandpass(source)
            try:
                self.assertEqual(ImageStat.Stat(residual).mean[0], 128.0)
                self.assertTrue(record["zero_mean_passed"])
                self.assertTrue(record["band_limited_by_construction"])
                self.assertFalse(record["source_rgb_or_colour_transferred"])
                self.assertFalse(record["source_broad_tone_transferred"])
                self.assertGreaterEqual(record["minimum_signed_luma_levels"], -18)
                self.assertLessEqual(record["maximum_signed_luma_levels"], 18)
            finally:
                residual.close()
        finally:
            source.close()

    def test_global_neutral_material_changes_no_water_or_line_guard_pixel(self):
        sheet = _sheet(self.contract, [3600, 3150, 3900, 3450])
        transform = renderer.SheetCanvasTransform(self.contract, sheet)
        image = Image.new("RGBA", (transform.width, transform.height), (190, 170, 116, 255))
        before = image.copy()
        land = Image.new("L", image.size, 0)
        ImageDraw.Draw(land).rectangle(
            (0, 0, image.width * 3 // 4, image.height - 1),
            fill=255,
        )
        sources = _empty_sources()
        sources["transport"]["features"].append(
            {
                "type": "Feature",
                "properties": {"id": "guard-road"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[3620, 3300], [3860, 3300]],
                },
            }
        )
        sources["hydrography"]["features"].append(
            {
                "type": "Feature",
                "properties": {"id": "guard-river"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[3750, 3170], [3750, 3420]],
                },
            }
        )
        clip = renderer._build_canonical_texture_clip(
            sources,
            land,
            transform,
            full_material_preview=False,
        )
        try:
            record = renderer._draw_global_neutral_land_material(
                image,
                sources,
                land,
                transform,
                renderer.DEFAULT_SEED,
            )
            difference = ImageChops.difference(before, image).convert("L")
            inverse_clip = ImageOps.invert(clip)
            forbidden = ImageChops.multiply(difference, inverse_clip)
            try:
                self.assertIsNone(forbidden.getbbox())
                self.assertEqual(record["global_neutral_water_pixel_changes"], 0)
                self.assertEqual(record["global_neutral_line_guard_pixel_changes"], 0)
            finally:
                difference.close()
                inverse_clip.close()
                forbidden.close()
        finally:
            clip.close()
            land.close()
            before.close()
            image.close()

    def test_global_neutral_material_matches_at_same_world_pixels_across_overlapping_sheets(self):
        first_sheet = _sheet(self.contract, [3600, 3150, 3950, 3500])
        second_sheet = _sheet(self.contract, [3800, 3300, 4150, 3650])
        first_transform = renderer.SheetCanvasTransform(self.contract, first_sheet)
        second_transform = renderer.SheetCanvasTransform(self.contract, second_sheet)
        sources = _empty_sources()
        images = [
            Image.new("RGBA", (first_transform.width, first_transform.height), (190, 170, 116, 255)),
            Image.new("RGBA", (second_transform.width, second_transform.height), (190, 170, 116, 255)),
        ]
        masks = [Image.new("L", image.size, 255) for image in images]
        try:
            renderer._draw_global_neutral_land_material(
                images[0],
                sources,
                masks[0],
                first_transform,
                renderer.DEFAULT_SEED,
            )
            renderer._draw_global_neutral_land_material(
                images[1],
                sources,
                masks[1],
                second_transform,
                renderer.DEFAULT_SEED,
            )
            left = max(first_transform.pixel_bounds[0], second_transform.pixel_bounds[0])
            top = max(first_transform.pixel_bounds[1], second_transform.pixel_bounds[1])
            right = min(first_transform.pixel_bounds[2], second_transform.pixel_bounds[2])
            bottom = min(first_transform.pixel_bounds[3], second_transform.pixel_bounds[3])
            first_crop = images[0].crop(
                (
                    left - first_transform.pixel_bounds[0],
                    top - first_transform.pixel_bounds[1],
                    right - first_transform.pixel_bounds[0],
                    bottom - first_transform.pixel_bounds[1],
                )
            )
            second_crop = images[1].crop(
                (
                    left - second_transform.pixel_bounds[0],
                    top - second_transform.pixel_bounds[1],
                    right - second_transform.pixel_bounds[0],
                    bottom - second_transform.pixel_bounds[1],
                )
            )
            try:
                self.assertIsNone(ImageChops.difference(first_crop, second_crop).getbbox())
            finally:
                first_crop.close()
                second_crop.close()
        finally:
            for mask in masks:
                mask.close()
            for image in images:
                image.close()

    def test_global_neutral_mode_is_royal_only_preview_only(self):
        self.assertIn(
            renderer.GLOBAL_NEUTRAL_BANDPASS_MODE,
            renderer.PREVIEW_ONLY_MATERIAL_MODES,
        )
        args = renderer.parse_args(["--global-neutral-bandpass-preview"])
        self.assertTrue(args.global_neutral_bandpass_preview)
        with self.assertRaisesRegex(renderer.ReviewedMasterError, "Royal-only"):
            renderer.write_reviewed_master(
                sheet_id="sheet_region_soaring_mountains_region",
                material_transfer_mode=renderer.GLOBAL_NEUTRAL_BANDPASS_MODE,
            )
        with self.assertRaisesRegex(renderer.ReviewedMasterError, "Royal-only"):
            renderer.write_generation_batch(
                material_transfer_mode=renderer.GLOBAL_NEUTRAL_BANDPASS_MODE,
            )

    def test_semantic_boundary_contrast_limit_is_common_and_strict(self):
        self.assertEqual(renderer.SEMANTIC_BOUNDARY_CONTRAST_LIMIT, 0.75)
        before = Image.new("RGB", (40, 40), (128, 128, 128))
        after = before.copy()
        parent = Image.new("L", before.size, 0)
        ImageDraw.Draw(parent).rectangle((8, 8, 31, 31), fill=255)
        clip = Image.new("L", before.size, 255)
        try:
            record = renderer._semantic_boundary_contrast(
                before,
                after,
                parent,
                clip,
            )
            self.assertEqual(record["limit_luma_levels"], 0.75)
            self.assertTrue(record["passed"])
        finally:
            clip.close()
            parent.close()
            after.close()
            before.close()


if __name__ == "__main__":
    unittest.main()
