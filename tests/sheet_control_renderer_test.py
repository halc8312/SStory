import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
MODULE_PATH = SCRIPT_DIR / "render_sheet_controls.py"
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location("render_sheet_controls", MODULE_PATH)
render_sheet_controls = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(render_sheet_controls)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SheetControlRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.sheets = render_sheet_controls.load_sheet_catalog(
            render_sheet_controls.DEFAULT_MAP_SHEETS
        )

    def test_all_selects_the_23_bounded_supported_sheets(self):
        selected = render_sheet_controls.select_sheets(
            self.sheets, select_all=True
        )

        self.assertEqual(len(selected), 23)
        self.assertNotIn(
            "sheet_district_astralis_royal_quarter",
            {sheet["id"] for sheet in selected},
        )
        self.assertNotIn(
            "sheet_block_astralis_palace_square",
            {sheet["id"] for sheet in selected},
        )

    def test_corridor_dimensions_follow_world_raster_ratio_and_quantum(self):
        sheet = self.sheets["sheet_corridor_astralis_port_zephia"]
        bounds = render_sheet_controls.validate_sheet_bounds(
            sheet["bounds"], sheet["id"]
        )

        dimensions = render_sheet_controls.output_dimensions(
            bounds, source_width=4096, source_height=2730
        )
        pixels = render_sheet_controls.continuous_pixel_bounds(
            bounds, 4096, 2730
        )

        self.assertEqual(dimensions, (1536, 832))
        self.assertEqual(dimensions[0], 1536)
        self.assertEqual(dimensions[1] % 16, 0)
        self.assertEqual(
            [round(value, 3) for value in pixels],
            [1576.575, 873.28, 2027.025, 1118.89],
        )

    def test_single_sheet_is_deterministic_and_records_hashes_and_no_stretch(self):
        sheet_id = "sheet_corridor_astralis_port_zephia"
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = render_sheet_controls.generate_sheet_controls(
                sheet_ids=[sheet_id], output_dir=Path(first_dir)
            )[0]
            second = render_sheet_controls.generate_sheet_controls(
                sheet_ids=[sheet_id], output_dir=Path(second_dir)
            )[0]
            first_png = Path(first_dir) / f"{sheet_id}.png"
            second_png = Path(second_dir) / f"{sheet_id}.png"

            self.assertEqual(sha256(first_png), sha256(second_png))
            self.assertEqual(first["output"]["sha256"], sha256(first_png))
            self.assertEqual(first["sheet"]["bounds"], [3850, 3200, 4950, 4100])
            self.assertEqual(first["pixel_mapping"]["pixel_bounds"], [1576, 873, 2029, 1120])
            self.assertEqual(first["output"]["width"], 1536)
            self.assertEqual(first["output"]["height"], 832)
            self.assertFalse(first["rendering"]["stretch"])
            self.assertEqual(
                first["source_control"]["sha256"],
                sha256(render_sheet_controls.DEFAULT_CONTROL),
            )
            self.assertEqual(
                first["source_control"]["metadata_sha256"],
                sha256(render_sheet_controls.DEFAULT_CONTROL_METADATA),
            )
            saved = json.loads(
                (Path(first_dir) / f"{sheet_id}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved["output"]["sha256"], first["output"]["sha256"])

    def test_unknown_unbounded_and_existing_targets_are_refused(self):
        with self.assertRaisesRegex(
            render_sheet_controls.SheetControlError, "unknown sheet id"
        ):
            render_sheet_controls.select_sheets(
                self.sheets, sheet_ids=["sheet_missing"]
            )
        with self.assertRaisesRegex(
            render_sheet_controls.SheetControlError, "not a supported control type"
        ):
            render_sheet_controls.select_sheets(
                self.sheets,
                sheet_ids=["sheet_district_astralis_royal_quarter"],
            )

        sheet_id = "sheet_corridor_astralis_port_zephia"
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            owned = output / f"{sheet_id}.png"
            owned.write_bytes(b"user-owned")
            with self.assertRaisesRegex(
                render_sheet_controls.SheetControlError,
                "refusing to overwrite existing output",
            ):
                render_sheet_controls.generate_sheet_controls(
                    sheet_ids=[sheet_id], output_dir=output
                )
            self.assertEqual(owned.read_bytes(), b"user-owned")
            self.assertFalse((output / f"{sheet_id}.json").exists())


if __name__ == "__main__":
    unittest.main()
