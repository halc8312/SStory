import copy
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
SOURCE_DIR = REPO_ROOT / "world" / "map-production" / "source"
DATA_DIR = REPO_ROOT / "world" / "map-data" / "data"
sys.path.insert(0, str(SCRIPT_DIR))

import validate_source_catalog  # noqa: E402


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class SourceCatalogValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.canonical, cls.canonical_by_id, canonical_errors = (
            validate_source_catalog.load_canonical_data(DATA_DIR)
        )
        cls.source_feature_ids, source_errors = (
            validate_source_catalog.load_source_feature_ids(SOURCE_DIR)
        )
        if canonical_errors or source_errors:
            raise AssertionError(canonical_errors + source_errors)
        cls.gazetteer = read_json(SOURCE_DIR / "gazetteer.json")
        cls.map_sheets = read_json(SOURCE_DIR / "map-sheets.json")
        cls.settlement_footprints = read_json(
            SOURCE_DIR / "settlement-footprints.geojson"
        )
        cls.vertical_layers = read_json(SOURCE_DIR / "vertical-layers.json")

    def test_repository_source_catalog_passes_and_cli_needs_no_arguments(self):
        summary, errors = validate_source_catalog.validate_source_catalog()

        self.assertEqual(errors, [])
        self.assertEqual(summary["canonical_records"], 87)
        self.assertEqual(summary["gazetteer_entries"], 87)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            exit_code = validate_source_catalog.main([])
        self.assertEqual(exit_code, 0)
        self.assertIn("validation passed", output.getvalue())

    def test_gazetteer_detects_count_duplicate_missing_and_world_bounds(self):
        value = copy.deepcopy(self.gazetteer)
        removed = value["entries"].pop()
        duplicate = copy.deepcopy(value["entries"][0])
        duplicate["map_position"] = [10001, 5000]
        value["entries"].append(duplicate)

        errors = validate_source_catalog.validate_gazetteer(value, self.canonical)

        self.assertTrue(any("duplicate gazetteer key" in error for error in errors))
        self.assertTrue(any("duplicate gazetteer continent id" in error for error in errors))
        self.assertTrue(
            any(
                f"missing canonical gazetteer entry {removed['kind']}:{removed['id']}" in error
                for error in errors
            )
        )
        self.assertTrue(any("outside EA-WORLD-1 bounds" in error for error in errors))

        value["entry_count"] -= 1
        errors = validate_source_catalog.validate_gazetteer(value, self.canonical)
        self.assertTrue(any("entry_count" in error and "entries contains" in error for error in errors))

    def test_map_sheets_detect_unknown_refs_cycle_and_invalid_bounds(self):
        value = copy.deepcopy(self.map_sheets)
        world = value["sheets"][0]
        continent = value["sheets"][1]
        world["parent_id"] = continent["id"]
        world["bounds"] = [-1, 0, 10000, 10000]
        continent["source_feature_id"] = "missing_source_feature"
        value["sheets"][2]["secondary_parent_ids"] = ["missing_sheet"]

        errors = validate_source_catalog.validate_map_sheets(
            value,
            self.source_feature_ids,
        )

        self.assertTrue(any("sheet parent cycle detected" in error for error in errors))
        self.assertTrue(any("unknown parent 'missing_sheet'" in error for error in errors))
        self.assertTrue(any("unknown source feature 'missing_source_feature'" in error for error in errors))
        self.assertTrue(any("outside EA-WORLD-1 bounds" in error for error in errors))

    def test_region_sheet_must_contain_owned_nodes_and_settlement_footprints(self):
        value = copy.deepcopy(self.map_sheets)
        royal = next(
            sheet
            for sheet in value["sheets"]
            if sheet["id"] == "sheet_region_royal_capital_region"
        )
        royal["bounds"] = [4000, 3650, 4300, 3850]

        errors = validate_source_catalog.validate_map_sheet_coverage(
            value,
            self.gazetteer,
            self.settlement_footprints,
        )

        self.assertTrue(
            any(
                "gazetteer node 'astralis_airport'" in error
                and "sheet_region_royal_capital_region" in error
                for error in errors
            )
        )
        self.assertTrue(
            any(
                "settlement footprint 'astralis'" in error
                and "sheet_region_royal_capital_region" in error
                for error in errors
            )
        )

    def test_continent_and_region_sheets_must_contain_bounded_children(self):
        value = copy.deepcopy(self.map_sheets)
        elysion = next(
            sheet
            for sheet in value["sheets"]
            if sheet["id"] == "sheet_continent_elysion"
        )
        royal = next(
            sheet
            for sheet in value["sheets"]
            if sheet["id"] == "sheet_region_royal_capital_region"
        )
        elysion["bounds"] = [3700, 3300, 4900, 4300]
        royal["bounds"] = [3850, 3250, 5000, 4450]

        errors = validate_source_catalog.validate_map_sheet_coverage(
            value,
            self.gazetteer,
            self.settlement_footprints,
        )

        self.assertTrue(
            any(
                "continent sheet 'sheet_continent_elysion'" in error
                and "child region sheet" in error
                for error in errors
            )
        )
        self.assertTrue(
            any(
                "region sheet 'sheet_region_royal_capital_region'" in error
                and "child sheet 'sheet_corridor_astralis_port_zephia'" in error
                for error in errors
            )
        )

    def test_vertical_layers_detect_interval_and_assignment_errors(self):
        value = copy.deepcopy(self.vertical_layers)
        value["layers"][1]["z_min_inclusive"] = -600
        value["layers"][4]["current_feature_ids"].append("elysion")

        errors = validate_source_catalog.validate_vertical_layers(
            value,
            self.canonical_by_id,
        )

        self.assertTrue(any("vertical intervals overlap" in error for error in errors))
        self.assertTrue(any("already assigned" in error and "elysion" in error for error in errors))
        self.assertTrue(any("canonical z=0" in error and "[700, 1100)" in error for error in errors))

    def test_primary_documents_require_object_structure_and_ea_world_crs(self):
        errors = validate_source_catalog.validate_gazetteer([], self.canonical)
        self.assertTrue(any("top-level value must be an object" in error for error in errors))

        value = copy.deepcopy(self.vertical_layers)
        value["coordinate_reference_system"] = "EPSG:4326"
        value["layers"] = "not-an-array"
        errors = validate_source_catalog.validate_vertical_layers(value, self.canonical_by_id)
        self.assertTrue(any("coordinate_reference_system" in error for error in errors))
        self.assertTrue(any("layers must be a non-empty array" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
