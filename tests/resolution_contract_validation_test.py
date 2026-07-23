import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
CONTRACT_PATH = (
    REPO_ROOT / "world" / "map-production" / "spec" / "resolution-contract.json"
)
MAP_SHEETS_PATH = (
    REPO_ROOT / "world" / "map-production" / "source" / "map-sheets.json"
)
sys.path.insert(0, str(SCRIPT_DIR))

import validate_resolution_contract  # noqa: E402


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


class ResolutionContractValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = read_json(CONTRACT_PATH)
        cls.catalog = read_json(MAP_SHEETS_PATH)

    def test_repository_contract_and_catalog_validation_reproduces_budget(self):
        result = validate_resolution_contract.validate_resolution_contract(
            check_catalog=True
        )

        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["bounded_sheet_count"], 23)
        self.assertEqual(result["unbounded_skipped_count"], 2)
        self.assertEqual(
            result["unbounded_skipped_sheet_ids"],
            [
                "sheet_district_astralis_royal_quarter",
                "sheet_block_astralis_palace_square",
            ],
        )
        self.assertEqual(result["total_master_pixels"], 233_802_632)
        self.assertEqual(result["total_master_megapixels"], 233.8)
        self.assertEqual(result["generation_master_pixels"], 190_786_183)
        self.assertEqual(result["generation_metatile_count"], 99)
        self.assertEqual(result["catalog_profile_mismatch_count"], 0)
        self.assertEqual(result["catalog_zoom_mismatch_count"], 0)
        self.assertEqual(
            self.catalog["tile_profile"],
            {
                "tile_size_px": 512,
                "metatile_size_px": 2048,
                "metatile_gutter_each_side_px": 256,
                "public_format": "webp",
                "master_format": "png",
                "labels_baked_into_raster": False,
            },
        )
        unbounded_resolution = {
            sheet["id"]: (sheet["zoom_range"], sheet["native_zoom"])
            for sheet in self.catalog["sheets"]
            if sheet["bounds"] is None
        }
        self.assertEqual(
            unbounded_resolution,
            {
                "sheet_district_astralis_royal_quarter": ([12, 14], 14),
                "sheet_block_astralis_palace_square": ([14, 16], 16),
            },
        )

    def test_all_sheet_dimensions_and_metatile_breakdown_are_deterministic(self):
        result = validate_resolution_contract.validate_resolution_contract()
        sheets = {sheet["sheet_id"]: sheet for sheet in result["sheets"]}

        self.assertEqual(len(sheets), 23)
        self.assertEqual(
            sheets["sheet_world"]["pixel_bounds"], [0, 0, 4096, 2730]
        )
        self.assertEqual(
            (sheets["sheet_world"]["width"], sheets["sheet_world"]["height"]),
            (4096, 2730),
        )
        self.assertEqual(
            sheets["sheet_region_royal_capital_region"]["pixel_bounds"],
            [5898, 3439, 8192, 4860],
        )
        corridor = sheets["sheet_corridor_astralis_port_zephia"]
        self.assertEqual(corridor["pixel_bounds"], [25231, 13977, 32441, 17909])
        self.assertEqual((corridor["width"], corridor["height"]), (7210, 3932))
        self.assertEqual(corridor["metatiles"]["count"], 15)
        astralis = sheets["sheet_settlement_astralis"]
        self.assertEqual(astralis["pixel_bounds"], [50462, 30576, 58328, 35119])
        self.assertEqual((astralis["width"], astralis["height"]), (7866, 4543))
        self.assertEqual(astralis["metatiles"]["count"], 15)

        metatiles_by_type = {
            sheet_type: sum(
                sheet["metatiles"]["count"]
                for sheet in sheets.values()
                if sheet["sheet_type"] == sheet_type
            )
            for sheet_type in ("region", "corridor", "settlement")
        }
        self.assertEqual(
            metatiles_by_type,
            {"region": 63, "corridor": 15, "settlement": 21},
        )

    def test_check_catalog_rejects_a_mutated_bounded_sheet(self):
        catalog = copy.deepcopy(self.catalog)
        royal = next(
            sheet
            for sheet in catalog["sheets"]
            if sheet["id"] == "sheet_region_royal_capital_region"
        )
        royal["zoom_range"] = [6, 8]
        royal["native_zoom"] = 8

        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_path = Path(temp_dir) / "map-sheets.json"
            write_json(catalog_path, catalog)
            result = validate_resolution_contract.validate_resolution_contract(
                map_sheets_path=catalog_path,
                check_catalog=True,
            )

        self.assertFalse(result["valid"])
        self.assertEqual(result["catalog_profile_mismatch_count"], 0)
        self.assertEqual(result["catalog_zoom_mismatch_count"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertTrue(
            any(
                "sheet_region_royal_capital_region" in error
                and "zoom_range=[6, 8], native_zoom=8" in error
                for error in result["errors"]
            )
        )

    def test_check_catalog_compares_all_resolution_profile_fields(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["tile_profile"].update(
            {
                "tile_size_px": 256,
                "public_format": "png",
                "metatile_size_px": 1024,
                "metatile_gutter_each_side_px": 128,
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_path = Path(temp_dir) / "map-sheets.json"
            write_json(catalog_path, catalog)
            result = validate_resolution_contract.validate_resolution_contract(
                map_sheets_path=catalog_path,
                check_catalog=True,
            )

        self.assertFalse(result["valid"])
        self.assertEqual(result["catalog_profile_mismatch_count"], 4)
        self.assertEqual(result["catalog_zoom_mismatch_count"], 0)
        for field in (
            "tile_size_px",
            "public_format",
            "metatile_size_px",
            "metatile_gutter_each_side_px",
        ):
            self.assertTrue(
                any(field in error for error in result["catalog_profile_mismatches"]),
                field,
            )

    def test_contract_rejects_non_monotonic_lod_and_invalid_metatile_stride(self):
        contract = copy.deepcopy(self.contract)
        contract["lod_by_sheet_type"]["region"]["native_zoom"] = 4
        contract["metatile_profile"]["stride_px"] = 1537
        contract["tile_profile"]["coordinate_scope"] = "global"

        errors = validate_resolution_contract.validate_contract_structure(contract)

        self.assertTrue(any("preceding LOD native zoom" in error for error in errors))
        self.assertTrue(any("stride_px must equal" in error for error in errors))
        self.assertTrue(any("coordinate_scope" in error for error in errors))

    def test_catalog_parent_lod_monotonicity_and_unbounded_skip_policy_are_enforced(self):
        catalog = copy.deepcopy(self.catalog)
        world = next(sheet for sheet in catalog["sheets"] if sheet["id"] == "sheet_world")
        world["parent_id"] = "sheet_settlement_astralis"
        district = next(
            sheet
            for sheet in catalog["sheets"]
            if sheet["id"] == "sheet_district_astralis_royal_quarter"
        )
        district["review_status"] = "ready"

        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_path = Path(temp_dir) / "map-sheets.json"
            write_json(catalog_path, catalog)
            result = validate_resolution_contract.validate_resolution_contract(
                map_sheets_path=catalog_path
            )

        self.assertFalse(result["valid"])
        self.assertTrue(any("sheet LOD is not monotonic" in error for error in result["errors"]))
        self.assertTrue(
            any("must have review_status 'planned'" in error for error in result["errors"])
        )

    def test_cli_default_and_check_catalog_pass(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            exit_code = validate_resolution_contract.main([])
        self.assertEqual(exit_code, 0)
        self.assertIn("Master pixels=233,802,632 (233.8 MP)", output.getvalue())
        self.assertIn("ImageGen metatiles=99", output.getvalue())
        self.assertNotIn("Catalog resolution migration pending", output.getvalue())

        with contextlib.redirect_stdout(io.StringIO()) as catalog_output:
            exit_code = validate_resolution_contract.main(["--check-catalog"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Resolution contract validation passed", catalog_output.getvalue())


if __name__ == "__main__":
    unittest.main()
