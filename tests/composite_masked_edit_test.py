from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"

sys.path.insert(0, str(SCRIPT_DIR))

from composite_masked_edit import build_mask, composite  # noqa: E402


def _decoded_raster_identity(image: Image.Image) -> tuple[str, tuple[int, int], bytes]:
    image.load()
    return image.mode, image.size, image.tobytes()


class CompositeMaskedEditTests(unittest.TestCase):
    def test_repository_b_masks_keep_decoded_identity_and_distribution_hashes(
        self,
    ) -> None:
        controls = REPO_ROOT / "world/map-production/controls"
        expected = {
            1: "1c785d69d23ae1570f29c0322deed517928f6a5c2b4e2a11d2361965bf27c62b",
            2: "c2f66b62b9f3fcb02ac03127dbd4f70d98addb83de1d7b62959eefc109652d5d",
        }
        for version, expected_hash in expected.items():
            control_path = controls / f"style-candidate-b-mountain-mask-v{version}.json"
            stored_path = control_path.with_suffix(".png")
            control = json.loads(control_path.read_text(encoding="utf-8"))
            regenerated = build_mask(control)
            try:
                with Image.open(stored_path) as stored:
                    self.assertEqual(
                        _decoded_raster_identity(regenerated),
                        _decoded_raster_identity(stored),
                    )
            finally:
                regenerated.close()

            self.assertEqual(
                hashlib.sha256(stored_path.read_bytes()).hexdigest(), expected_hash
            )

    def test_decoded_identity_ignores_png_compression_but_detects_one_pixel(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temporary:
            root = Path(temporary)
            first_path = root / "first.png"
            second_path = root / "second.png"
            changed_path = root / "changed.png"
            raster = Image.new("L", (16, 16))
            raster.putdata(bytes((index * 41) % 256 for index in range(256)))
            try:
                raster.save(
                    first_path, format="PNG", compress_level=0, optimize=False
                )
                raster.save(
                    second_path, format="PNG", compress_level=9, optimize=False
                )
                changed = raster.copy()
                changed.putpixel((6, 10), (changed.getpixel((6, 10)) + 1) % 256)
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
            with (
                Image.open(first_path) as first,
                Image.open(second_path) as second,
                Image.open(changed_path) as changed,
            ):
                self.assertEqual(
                    _decoded_raster_identity(first),
                    _decoded_raster_identity(second),
                )
                self.assertNotEqual(
                    _decoded_raster_identity(first),
                    _decoded_raster_identity(changed),
                )

    def test_legacy_control_reproduces_the_previous_mask_byte_for_byte(self) -> None:
        control = {
            "schema_version": "1.0.0",
            "canvas": {"width": 48, "height": 36},
            "include_polygons": [
                {"id": "area", "points": [[4, 3], [43, 3], [43, 32], [4, 32]]}
            ],
            "exclude_strokes": [
                {"id": "road-a", "width": 3, "points": [[5, 12], [42, 17]]},
                {"id": "road-b", "width": 5, "points": [[18, 4], [25, 31]]},
            ],
            "feather_inside_px": 4,
        }

        # This is the exact algorithm used before feather_px was introduced.
        legacy = Image.new("L", (48, 36), 0)
        draw = ImageDraw.Draw(legacy)
        draw.polygon([(4, 3), (43, 3), (43, 32), (4, 32)], fill=255)
        draw.line([(5, 12), (42, 17)], fill=0, width=3, joint="curve")
        draw.line([(18, 4), (25, 31)], fill=0, width=5, joint="curve")
        legacy = ImageChops.darker(legacy, legacy.filter(ImageFilter.GaussianBlur(radius=4)))

        self.assertEqual(build_mask(control).tobytes(), legacy.tobytes())

    def test_each_include_polygon_can_use_an_independent_feather_before_union(self) -> None:
        control = {
            "schema_version": "1.0.0",
            "canvas": {"width": 80, "height": 48},
            "include_polygons": [
                {
                    "id": "tight",
                    "points": [[3, 4], [35, 4], [35, 43], [3, 43]],
                    "feather_inside_px": 1,
                },
                {
                    "id": "soft",
                    "points": [[30, 4], [76, 4], [76, 43], [30, 43]],
                    "feather_inside_px": 6,
                },
            ],
            "exclude_strokes": [
                {"id": "road", "width": 3, "feather_px": 1, "points": [[8, 24], [72, 24]]}
            ],
            "feather_inside_px": 4,
        }

        tight = Image.new("L", (80, 48), 0)
        ImageDraw.Draw(tight).polygon([(3, 4), (35, 4), (35, 43), (3, 43)], fill=255)
        tight = ImageChops.darker(tight, tight.filter(ImageFilter.GaussianBlur(radius=1)))
        soft = Image.new("L", (80, 48), 0)
        ImageDraw.Draw(soft).polygon([(30, 4), (76, 4), (76, 43), (30, 43)], fill=255)
        soft = ImageChops.darker(soft, soft.filter(ImageFilter.GaussianBlur(radius=6)))
        expected_include = ImageChops.lighter(tight, soft)

        mask = build_mask(control)

        self.assertGreater(expected_include.getpixel((12, 8)), expected_include.getpixel((66, 8)))
        self.assertEqual(mask.getpixel((40, 24)), 0)
        self.assertEqual(mask.getpixel((12, 8)), expected_include.getpixel((12, 8)))
        self.assertEqual(mask.getpixel((66, 8)), expected_include.getpixel((66, 8)))

    def test_include_strokes_create_rounded_local_edit_corridors(self) -> None:
        control = {
            "schema_version": "1.0.0",
            "canvas": {"width": 96, "height": 64},
            "include_strokes": [
                {
                    "id": "ridge-a",
                    "points": [[12, 18], [42, 18], [60, 28]],
                    "width": 18,
                    "feather_inside_px": 3,
                },
                {
                    "id": "ridge-b",
                    "points": [[35, 50], [72, 46]],
                    "width": 12,
                    "feather_inside_px": 1,
                },
            ],
            "exclude_strokes": [
                {"id": "road", "points": [[8, 24], [88, 40]], "width": 3, "feather_px": 1}
            ],
            "feather_inside_px": 4,
        }

        mask = build_mask(control)

        self.assertEqual(mask.size, (96, 64))
        self.assertGreater(mask.getpixel((12, 18)), 200)
        self.assertGreater(mask.getpixel((72, 46)), 200)
        self.assertEqual(mask.getpixel((48, 32)), 0)
        self.assertEqual(mask.getpixel((4, 4)), 0)
        self.assertEqual(mask.getpixel((92, 60)), 0)

    def test_include_control_requires_a_polygon_or_stroke(self) -> None:
        with self.assertRaisesRegex(ValueError, "include polygon or include stroke"):
            build_mask(
                {
                    "schema_version": "1.0.0",
                    "canvas": {"width": 32, "height": 24},
                    "include_polygons": [],
                    "include_strokes": [],
                }
            )

    def test_candidate_d_guide_is_mostly_white_and_never_black(self) -> None:
        control_path = REPO_ROOT / "world/map-production/controls/style-candidate-d-mountain-mask-v1.json"
        guide_path = REPO_ROOT / "world/map-production/controls/style-candidate-d-ridge-guide-v1.json"
        stored_mask_path = control_path.with_suffix(".png")
        control = json.loads(control_path.read_text(encoding="utf-8"))
        guide = json.loads(guide_path.read_text(encoding="utf-8"))
        mask = build_mask(control)

        with Image.open(stored_mask_path) as stored_mask:
            self.assertEqual(stored_mask.convert("L").tobytes(), mask.tobytes())

        for region in guide["regions"]:
            footprint = Image.new("1", mask.size, 0)
            draw = ImageDraw.Draw(footprint)
            for ridge in region["ridge_chains"]:
                points = [tuple(point) for point in ridge["source_pixels_path"]]
                width = ridge["width_px"] + 4  # include the rendered guide outline
                draw.line(points, fill=1, width=width, joint="curve")
                radius = width // 2
                for x, y in (points[0], points[-1]):
                    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=1)
                for hatch in ridge["hatches"]:
                    draw.line(
                        [tuple(point) for point in hatch["source_pixels_path"]],
                        fill=1,
                        width=6,
                    )
            values = [
                value
                for value, selected in zip(mask.get_flattened_data(), footprint.get_flattened_data())
                if selected
            ]
            self.assertTrue(values)
            self.assertEqual(sum(value == 0 for value in values), 0)
            if region["id"] == "south_east_range":
                white_ratio = sum(value == 255 for value in values) / len(values)
                self.assertGreaterEqual(white_ratio, 0.80)

    def test_candidate_d_localized_ridge_mask_is_reproducible_and_road_safe(self) -> None:
        controls = REPO_ROOT / "world/map-production/controls"
        control_path = controls / "style-candidate-d-ridge-edit-mask-v2.json"
        stored_path = control_path.with_suffix(".png")
        control = json.loads(control_path.read_text(encoding="utf-8"))
        mask = build_mask(control)

        self.assertEqual(len(control["include_strokes"]), 10)
        self.assertTrue(all(item["width"] == 160 for item in control["include_strokes"]))
        with Image.open(stored_path) as stored:
            self.assertEqual(stored.convert("L").tobytes(), mask.tobytes())
        histogram = mask.histogram()
        self.assertEqual(sum(histogram[1:]), 378_548)
        self.assertEqual(1536 * 1024 - sum(histogram[1:]), 1_194_316)
        for road in control["exclude_strokes"]:
            for x, y in road["points"]:
                self.assertEqual(mask.getpixel((x, y)), 0)
        for ridge in control["include_strokes"]:
            for x, y in ridge["points"]:
                self.assertGreaterEqual(mask.getpixel((x, y)), 250)

    def test_each_exclude_stroke_can_use_an_independent_feather(self) -> None:
        control = {
            "schema_version": "1.0.0",
            "canvas": {"width": 64, "height": 40},
            "include_polygons": [
                {"id": "area", "points": [[0, 0], [63, 0], [63, 39], [0, 39]]}
            ],
            "exclude_strokes": [
                {"id": "tight", "width": 3, "feather_px": 1, "points": [[8, 10], [55, 10]]},
                {"id": "soft", "width": 3, "feather_px": 5, "points": [[8, 29], [55, 29]]},
            ],
            "feather_inside_px": 0,
        }

        mask = build_mask(control)

        self.assertEqual(mask.getpixel((32, 10)), 0)
        self.assertEqual(mask.getpixel((32, 29)), 0)
        self.assertGreater(mask.getpixel((32, 14)), mask.getpixel((32, 25)))
        self.assertGreaterEqual(mask.getpixel((32, 16)), 250)
        self.assertLess(mask.getpixel((32, 23)), 255)

    def test_protected_pixels_are_identical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base_path = root / "base.png"
            edit_path = root / "edit.png"
            control_path = root / "mask.json"
            output_path = root / "output.png"
            mask_path = root / "mask.png"
            Image.new("RGB", (32, 24), (20, 40, 60)).save(base_path)
            Image.new("RGB", (32, 24), (200, 180, 160)).save(edit_path)
            control_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "canvas": {"width": 32, "height": 24},
                        "include_polygons": [{"id": "area", "points": [[8, 6], [24, 6], [24, 18], [8, 18]]}],
                        "exclude_strokes": [
                            {"id": "road", "width": 3, "feather_px": 1, "points": [[8, 12], [24, 12]]}
                        ],
                        "feather_inside_px": 2,
                    }
                ),
                encoding="utf-8",
            )

            report = composite(base_path, edit_path, control_path, output_path, mask_path)
            output = Image.open(output_path).convert("RGB")

            self.assertEqual(output.getpixel((2, 2)), (20, 40, 60))
            self.assertEqual(output.getpixel((16, 12)), (20, 40, 60))
            self.assertNotEqual(output.getpixel((16, 9)), (20, 40, 60))
            self.assertEqual(report["outside_mask_max_channel_difference"], 0)
            self.assertGreater(report["protected_pixels_verified"], 0)
            self.assertTrue(mask_path.exists())


if __name__ == "__main__":
    unittest.main()
