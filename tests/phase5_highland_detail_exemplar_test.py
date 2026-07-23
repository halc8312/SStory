import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import phase5_highland_detail_exemplar as exemplar  # noqa: E402
import render_phase5_reviewed_master as reviewed  # noqa: E402


class Phase5HighlandDetailExemplarTests(unittest.TestCase):
    def _locked_profile(self) -> dict:
        return {
            "status": "locked",
            "contract_id": exemplar.CONTRACT_ID,
            "path": "world/map-production/style-assets/highland-detail-exemplar-v1.png",
            "sha256": exemplar.EXPECTED_EXEMPLAR_SHA256,
            "format": "PNG",
            "mode": "RGB",
            "width": 1536,
            "height": 1024,
            "profile": {
                "method": exemplar.PROFILE_METHOD,
                "whole_raster_aggregate_only": True,
                "derived_luma_amplitude_levels": 3,
                "derived_occupancy_fraction": 0.34,
                "source_pixels_retained": 0,
                "source_geometry_retained": False,
                "source_coordinates_retained": False,
                "source_palette_retained": False,
                "source_labels_retained": False,
            },
            "provenance": {
                "prompt": {
                    "path": "world/map-production/prompts/highland-detail-exemplar-v1.generation.txt",
                    "sha256": exemplar.EXPECTED_PROMPT_SHA256,
                },
                "generation_receipt": {
                    "path": "world/map-production/prompts/highland-detail-exemplar-v1.provenance-receipt.json",
                    "sha256": exemplar.EXPECTED_PROVENANCE_RECEIPT_SHA256,
                },
                "root_vision_review": {
                    "path": "world/map-production/qa/highland-detail-exemplar-v1-root-vision.json",
                    "sha256": exemplar.EXPECTED_ROOT_VISION_REVIEW_SHA256,
                },
            },
            "allowed_transfer": "aggregate-material-detail-statistics-only",
            "copied_pixels": 0,
            "source_geometry_used": False,
            "source_absolute_coordinates_used": False,
            "source_global_palette_used": False,
            "source_labels_used": False,
        }

    def test_production_identity_is_exact_and_opt_in(self):
        self.assertEqual(
            exemplar.DEFAULT_EXEMPLAR_PATH,
            REPO_ROOT
            / "world"
            / "map-production"
            / "style-assets"
            / "highland-detail-exemplar-v1.png",
        )
        self.assertEqual(
            exemplar.EXPECTED_EXEMPLAR_SHA256,
            "c7fcd3da5fba6fe08f10fd1e0fe16bdb2884a0a04386de828f923d660de8f1a2",
        )
        self.assertEqual(exemplar.EXPECTED_EXEMPLAR_SIZE, (1536, 1024))
        lock = exemplar.validate_production_exemplar()
        self.assertEqual(
            lock["provenance"]["prompt"]["sha256"],
            exemplar.EXPECTED_PROMPT_SHA256,
        )
        self.assertEqual(
            lock["provenance"]["generation_receipt"]["sha256"],
            exemplar.EXPECTED_PROVENANCE_RECEIPT_SHA256,
        )
        self.assertEqual(
            lock["provenance"]["root_vision_review"]["sha256"],
            exemplar.EXPECTED_ROOT_VISION_REVIEW_SHA256,
        )
        self.assertEqual(
            exemplar.TARGET_SHEET_ID,
            "sheet_region_soaring_mountains_region",
        )
        self.assertEqual(
            exemplar.TARGET_FEATURE_ID,
            "elysion_soaring_mountains_axis",
        )
        self.assertFalse(
            reviewed.parse_args([]).highland_detail_exemplar,
        )
        self.assertTrue(
            reviewed.parse_args(
                ["--highland-detail-exemplar"]
            ).highland_detail_exemplar,
        )

    def test_non_target_sheet_is_byte_for_byte_no_op_without_asset_access(self):
        image = Image.new("RGBA", (24, 18), (151, 127, 91, 213))
        land_mask = Image.new("L", image.size, 255)
        before = image.tobytes()
        try:
            with mock.patch.object(
                exemplar,
                "apply_production_exemplar",
                side_effect=AssertionError("non-target path touched the bridge"),
            ):
                result = reviewed._apply_highland_detail_exemplar(
                    image,
                    {},
                    land_mask,
                    object(),
                    {"sheet_id": "sheet_region_royal_capital_region"},
                    123,
                    enabled=True,
                )
            self.assertIsNone(result)
            self.assertEqual(image.tobytes(), before)
        finally:
            land_mask.close()
            image.close()

    def test_low_level_non_target_gate_does_not_validate_or_mutate(self):
        image = Image.new("RGB", (20, 14), (130, 110, 80))
        canonical = Image.new("L", image.size, 255)
        protected = Image.new("L", image.size, 0)
        before = image.tobytes()
        try:
            with mock.patch.object(
                exemplar,
                "validate_production_exemplar",
                side_effect=AssertionError("non-target sheet opened the exemplar"),
            ):
                result = exemplar.apply_production_exemplar(
                    image,
                    canonical,
                    protected,
                    sheet_id="sheet_region_moonlit_forest_region",
                    feature_id=exemplar.TARGET_FEATURE_ID,
                    global_pixel_origin=(10, 20),
                    seed=7,
                    enabled=True,
                )
            self.assertIsNone(result)
            self.assertEqual(image.tobytes(), before)
        finally:
            protected.close()
            canonical.close()
            image.close()

    def test_locked_raster_validation_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "exemplar.png"
            path.write_bytes(b"not-the-reviewed-raster")
            with mock.patch.object(exemplar, "DEFAULT_EXEMPLAR_PATH", path):
                with self.assertRaisesRegex(
                    exemplar.HighlandDetailExemplarError,
                    "SHA-256 mismatch",
                ):
                    exemplar.validate_production_exemplar()

        image = Image.new("RGB", (16, 16), (120, 100, 70))
        canonical = Image.new("L", image.size, 255)
        protected = Image.new("L", image.size, 0)
        before = image.tobytes()
        try:
            with tempfile.TemporaryDirectory() as directory:
                missing = Path(directory) / "missing.png"
                with mock.patch.object(exemplar, "DEFAULT_EXEMPLAR_PATH", missing):
                    with self.assertRaisesRegex(
                        exemplar.HighlandDetailExemplarError,
                        "does not exist",
                    ):
                        exemplar.apply_production_exemplar(
                            image,
                            canonical,
                            protected,
                            sheet_id=exemplar.TARGET_SHEET_ID,
                            feature_id=exemplar.TARGET_FEATURE_ID,
                            global_pixel_origin=(0, 0),
                            seed=11,
                            enabled=True,
                        )
            self.assertEqual(image.tobytes(), before)
        finally:
            protected.close()
            canonical.close()
            image.close()

    def test_valid_lock_extracts_only_whole_raster_scalar_statistics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "exemplar.png"
            source = Image.new("RGB", (48, 32))
            source.putdata(
                [
                    (
                        70 + (x * 7 + y * 3) % 120,
                        62 + (x * 5 + y * 9) % 120,
                        48 + (x * 11 + y * 2) % 120,
                    )
                    for y in range(source.height)
                    for x in range(source.width)
                ]
            )
            try:
                source.save(path, format="PNG", compress_level=9)
            finally:
                source.close()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with (
                mock.patch.object(exemplar, "DEFAULT_EXEMPLAR_PATH", path),
                mock.patch.object(exemplar, "EXPECTED_EXEMPLAR_SHA256", digest),
                mock.patch.object(exemplar, "EXPECTED_EXEMPLAR_SIZE", (48, 32)),
                mock.patch.object(
                    exemplar,
                    "_validate_provenance_graph",
                    return_value=self._locked_profile()["provenance"],
                ),
            ):
                lock = exemplar.validate_production_exemplar()

        profile = lock["profile"]
        self.assertEqual(profile["method"], exemplar.PROFILE_METHOD)
        self.assertTrue(profile["whole_raster_aggregate_only"])
        self.assertEqual(len(profile["luma_high_pass_bands"]), 3)
        self.assertEqual(profile["source_pixels_retained"], 0)
        self.assertFalse(profile["source_geometry_retained"])
        self.assertFalse(profile["source_coordinates_retained"])
        self.assertFalse(profile["source_palette_retained"])
        self.assertFalse(profile["source_labels_retained"])
        self.assertNotIn("pixels", profile)
        self.assertNotIn("coordinates", profile)
        self.assertNotIn("palette", profile)
        self.assertNotIn("crop", profile)
        self.assertNotIn("rgb", profile)

    def test_application_is_deterministic_and_contained_by_both_masks(self):
        original = Image.new("RGBA", (40, 30), (132, 107, 76, 211))
        first = original.copy()
        second = original.copy()
        canonical = Image.new("L", original.size, 0)
        protected = Image.new("L", original.size, 0)
        ImageDraw.Draw(canonical).rectangle((4, 3, 35, 26), fill=255)
        ImageDraw.Draw(protected).rectangle((15, 8, 23, 21), fill=255)
        try:
            with mock.patch.object(
                exemplar,
                "validate_production_exemplar",
                return_value=self._locked_profile(),
            ):
                first_record = exemplar.apply_production_exemplar(
                    first,
                    canonical,
                    protected,
                    sheet_id=exemplar.TARGET_SHEET_ID,
                    feature_id=exemplar.TARGET_FEATURE_ID,
                    global_pixel_origin=(4833, 3330),
                    seed=0xEA20260719,
                    enabled=True,
                )
                second_record = exemplar.apply_production_exemplar(
                    second,
                    canonical,
                    protected,
                    sheet_id=exemplar.TARGET_SHEET_ID,
                    feature_id=exemplar.TARGET_FEATURE_ID,
                    global_pixel_origin=(4833, 3330),
                    seed=0xEA20260719,
                    enabled=True,
                )

            self.assertEqual(first.tobytes(), second.tobytes())
            changed = 0
            for y in range(original.height):
                for x in range(original.width):
                    before = original.getpixel((x, y))
                    after = first.getpixel((x, y))
                    if after == before:
                        continue
                    changed += 1
                    self.assertGreaterEqual(canonical.getpixel((x, y)), 128)
                    self.assertLess(protected.getpixel((x, y)), 128)
                    deltas = tuple(after[index] - before[index] for index in range(3))
                    self.assertEqual(deltas[0], deltas[1])
                    self.assertEqual(deltas[1], deltas[2])
                    self.assertEqual(after[3], before[3])
            self.assertGreater(changed, 0)
            self.assertEqual(
                first_record["application"]["changed_pixels"],
                changed,
            )
            self.assertEqual(first_record, second_record)
            for field in (
                "changes_outside_canonical_mountain_mask",
                "changes_inside_protected_mask",
                "source_pixels_copied",
            ):
                self.assertEqual(first_record["application"][field], 0)
            for field in (
                "source_geometry_used",
                "source_absolute_coordinates_used",
                "source_global_palette_used",
                "labels_transferred",
                "roads_transferred",
                "water_transferred",
                "protected_topology_transferred",
                "destination_chroma_modified",
                "destination_alpha_modified",
            ):
                self.assertFalse(first_record["application"][field])
        finally:
            protected.close()
            canonical.close()
            second.close()
            first.close()
            original.close()

    def test_renderer_passes_exact_canonical_axis_and_topology_guard_masks(self):
        target = {
            "type": "Feature",
            "id": exemplar.TARGET_FEATURE_ID,
            "properties": {
                "id": exemplar.TARGET_FEATURE_ID,
                "terrain_type": "mountain_axis",
                "region_id": "soaring_mountains_region",
                "nominal_width": 12,
            },
            "geometry": {
                "type": "LineString",
                "coordinates": [[10, 50], [90, 50]],
            },
        }
        sources = {
            "terrain": {"features": [target]},
            "settlements": {"features": []},
            "hydrography": {"features": []},
            "transport": {
                "features": [
                    {
                        "type": "Feature",
                        "id": "road-crossing",
                        "properties": {"id": "road-crossing"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[50, 10], [50, 90]],
                        },
                    }
                ]
            },
        }
        contract = {
            "world_extent": {
                "min_x": 0,
                "min_y": 0,
                "max_x": 100,
                "max_y": 100,
            },
            "world_raster": {
                "width_px": 100,
                "height_px": 100,
                "native_zoom": 0,
            },
            "pixel_bounds_formula": {"scale_base": 2},
        }
        sheet = {
            "sheet_id": exemplar.TARGET_SHEET_ID,
            "sheet_type": "region",
            "bounds": [0, 0, 100, 100],
            "native_zoom": 0,
            "pixel_bounds": [0, 0, 100, 100],
            "width": 100,
            "height": 100,
        }
        transform = reviewed.SheetCanvasTransform(contract, sheet)
        image = Image.new("RGBA", (100, 100), (140, 120, 90, 255))
        land_mask = Image.new("L", image.size, 255)
        captured: dict[str, object] = {}

        def capture(
            destination: Image.Image,
            canonical_mask: Image.Image,
            protected_mask: Image.Image,
            **kwargs,
        ) -> dict:
            captured["canonical"] = canonical_mask.copy()
            captured["protected"] = protected_mask.copy()
            captured["kwargs"] = kwargs
            return {"status": "captured", "application": {}}

        try:
            with mock.patch.object(
                exemplar,
                "apply_production_exemplar",
                side_effect=capture,
            ):
                result = reviewed._apply_highland_detail_exemplar(
                    image,
                    sources,
                    land_mask,
                    transform,
                    sheet,
                    97,
                    enabled=True,
                )
            self.assertEqual(result["status"], "captured")
            self.assertTrue(
                result["application"]["canonical_target_centerline_guarded"]
            )
            canonical = captured["canonical"]
            protected = captured["protected"]
            self.assertIsInstance(canonical, Image.Image)
            self.assertIsInstance(protected, Image.Image)
            try:
                self.assertEqual(canonical.getpixel((25, 50)), 255)
                self.assertEqual(canonical.getpixel((25, 20)), 0)
                self.assertEqual(protected.getpixel((50, 50)), 255)
                self.assertEqual(protected.getpixel((25, 50)), 255)
                self.assertEqual(canonical.getpixel((25, 54)), 255)
                self.assertEqual(protected.getpixel((25, 54)), 0)
            finally:
                protected.close()
                canonical.close()
            kwargs = captured["kwargs"]
            self.assertEqual(kwargs["sheet_id"], exemplar.TARGET_SHEET_ID)
            self.assertEqual(kwargs["feature_id"], exemplar.TARGET_FEATURE_ID)
            self.assertEqual(kwargs["global_pixel_origin"], (0, 0))
            self.assertTrue(kwargs["enabled"])
        finally:
            land_mask.close()
            image.close()

    def test_renderer_rejects_ambiguous_or_retyped_target_feature(self):
        canonical = {
            "type": "Feature",
            "id": exemplar.TARGET_FEATURE_ID,
            "properties": {
                "id": exemplar.TARGET_FEATURE_ID,
                "terrain_type": "mountain_axis",
                "region_id": "soaring_mountains_region",
            },
            "geometry": {
                "type": "LineString",
                "coordinates": [[0, 0], [1, 1]],
            },
        }
        with self.assertRaisesRegex(reviewed.ReviewedMasterError, "exactly one"):
            reviewed._highland_detail_target_feature(
                {"terrain": {"features": [canonical, dict(canonical)]}}
            )
        changed = {
            **canonical,
            "properties": {
                **canonical["properties"],
                "terrain_type": "arcane_highlands",
            },
        }
        with self.assertRaisesRegex(
            reviewed.ReviewedMasterError,
            "identity or geometry changed",
        ):
            reviewed._highland_detail_target_feature(
                {"terrain": {"features": [changed]}}
            )


if __name__ == "__main__":
    unittest.main()
