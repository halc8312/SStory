import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import build_phase5_assets as phase5  # noqa: E402
import render_phase5_metatile_controls as controls  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Phase5MetatileControlRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = controls.load_plan_inputs()

    def test_dry_run_locks_all_17_sheets_and_99_row_major_tiles(self):
        summary = controls.dry_run()

        self.assertEqual(summary["sheet_count"], 17)
        self.assertEqual(summary["metatile_count"], 99)
        self.assertEqual(summary["prior_neighbor_context_count"], 120)

        checked = 0
        for sheet_id, contract in self.inputs["sheet_contracts"].items():
            actual = controls.build_metatile_plan(contract)
            expected = phase5.metatile_plan(contract)
            self.assertEqual(
                {key: value for key, value in actual.items() if key != "tiles"},
                {key: value for key, value in expected.items() if key != "tiles"},
                sheet_id,
            )
            for actual_tile, expected_tile in zip(actual["tiles"], expected["tiles"]):
                self.assertEqual(
                    {
                        key: actual_tile[key]
                        for key in (
                            "column",
                            "row",
                            "canvas_origin_px",
                            "source_core_box_px",
                            "destination_box_px",
                        )
                    },
                    expected_tile,
                    sheet_id,
                )
            self.assertEqual(
                [tile["sheet_sequence"] for tile in actual["tiles"]],
                list(range(actual["count"])),
            )
            checked += actual["count"]
        self.assertEqual(checked, 99)

    def test_one_tile_is_deterministic_and_partition_is_exhaustive(self):
        sheet_id = "sheet_region_royal_capital_region"
        contract = self.inputs["sheet_contracts"][sheet_id]
        plan = controls.build_metatile_plan(contract)
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as first_root, tempfile.TemporaryDirectory(
            dir=REPO_ROOT
        ) as second_root:
            outputs = []
            logical_output = REPO_ROOT / "tmp-phase5-control-test-logical"
            for root_value in (first_root, second_root):
                output = Path(root_value) / "prototype"
                output.mkdir()
                tile = controls.render_tile_assets(
                    plan_inputs=self.inputs,
                    sheet=self.inputs["catalog_by_id"][sheet_id],
                    sheet_contract=contract,
                    tile_plan=plan["tiles"][0],
                    physical_output=output,
                    logical_output=logical_output,
                )
                tile["prior_neighbors"] = {"north": None, "west": None}
                tile["future_seam_targets"] = {
                    "east": {"column": 1, "row": 0},
                    "south": None,
                }
                protected = controls._write_protected_control(
                    tile,
                    sheet_id=sheet_id,
                    source_inputs=self.inputs["source_inputs"],
                    schema_path=controls.DEFAULT_PROTECTED_SCHEMA,
                )
                outputs.append((output, tile, protected))

            first, first_tile, first_control = outputs[0]
            second, second_tile, second_control = outputs[1]
            first_files = sorted(
                path.relative_to(first).as_posix()
                for path in first.rglob("*")
                if path.is_file()
            )
            second_files = sorted(
                path.relative_to(second).as_posix()
                for path in second.rglob("*")
                if path.is_file()
            )
            self.assertEqual(first_files, second_files)
            for relative in first_files:
                self.assertEqual(digest(first / relative), digest(second / relative), relative)

            partition = first_tile["partition"]
            self.assertEqual(partition["overlap_pixel_count"], 0)
            self.assertEqual(partition["unclassified_pixel_count"], 0)
            self.assertEqual(
                partition["land_pixel_count"]
                + partition["water_pixel_count"]
                + partition["unknown_pixel_count"],
                controls.PIXEL_COUNT,
            )
            self.assertEqual(first_control["sha256"], second_control["sha256"])
            protected_path = first / sheet_id / "c00-r00" / "protected-control.json"
            document = json.loads(protected_path.read_text(encoding="utf-8"))
            controls.validate_schema(
                document,
                controls.DEFAULT_PROTECTED_SCHEMA,
                "prototype protected control",
            )
            self.assertEqual(document["detail"]["status"], "explicit-empty")
            self.assertEqual(
                document["unknown_fallback"]["source"], document["parent_context"]
            )
            with Image.open(first / sheet_id / "c00-r00" / "detail-mask.png") as mask:
                self.assertEqual(mask.mode, "L")
                self.assertEqual(mask.getextrema(), (0, 0))

    def test_neighbor_bindings_are_prior_only_and_future_has_no_artifact(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temporary:
            root = Path(temporary)
            tiles = []
            for column, color in ((0, "red"), (1, "blue")):
                directory = root / f"c{column:02d}-r00"
                directory.mkdir()
                path = directory / "geometry-control.png"
                Image.new("RGB", (2048, 2048), color).save(path)
                spec = controls.image_artifact(path, expected_mode="RGB")
                tiles.append(
                    {
                        "column": column,
                        "row": 0,
                        "physical_dir": directory,
                        "logical_dir": directory,
                        "specs": {"visual_geometry_control": spec},
                    }
                )

            count = controls.bind_prior_contexts(tiles, columns=2, rows=1)
            self.assertEqual(count, 1)
            self.assertIsNone(tiles[0]["prior_neighbors"]["north"])
            self.assertIsNone(tiles[0]["prior_neighbors"]["west"])
            self.assertEqual(
                tiles[0]["future_seam_targets"]["east"], {"column": 1, "row": 0}
            )
            west = tiles[1]["prior_neighbors"]["west"]
            self.assertEqual(west["receipt_role"], "neighbor-west")
            self.assertEqual(west["source_tile"], {"column": 0, "row": 0})
            self.assertEqual(
                west["geometry_context"]["sha256"],
                tiles[0]["specs"]["visual_geometry_control"]["sha256"],
            )
            self.assertIsNone(tiles[1]["future_seam_targets"]["east"])
            self.assertFalse((tiles[0]["physical_dir"] / "neighbor-east-context.png").exists())
            self.assertFalse((tiles[0]["physical_dir"] / "neighbor-south-context.png").exists())

    def test_overlap_and_stale_index_claims_fail_closed(self):
        land = Image.new("L", (2048, 2048), 255)
        water = Image.new("L", (2048, 2048), 255)
        unknown = Image.new("L", (2048, 2048), 0)
        try:
            with self.assertRaisesRegex(controls.Phase5ControlError, "partition failed"):
                controls.partition_metrics(land, water, unknown)
        finally:
            land.close()
            water.close()
            unknown.close()

        actual = {"inputs": {"canon_sources": [{"sha256": "0" * 64}]}}
        expected = {"inputs": {"canon_sources": [{"sha256": "1" * 64}]}}
        difference = controls._first_difference(actual, expected)
        self.assertIn("canon_sources", difference)
        self.assertIn("sha256", difference)


if __name__ == "__main__":
    unittest.main()
