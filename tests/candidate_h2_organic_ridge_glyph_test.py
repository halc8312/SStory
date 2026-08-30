from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts/map-production"
MODULE_PATH = SCRIPT_DIR / "render_candidate_h2_organic_ridge_glyph.py"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location(
    "candidate_h2_organic_ridge_glyph", MODULE_PATH
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CandidateH2OrganicRidgeGlyphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(
            prefix="sstory-h2-prototype-", dir=REPO_ROOT
        )
        cls.output_dir = Path(cls._temporary.name) / "all"
        cls.report = MODULE.render_all(cls.output_dir)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_single_diagnostic_variant_and_locked_source_topology(self) -> None:
        self.assertEqual(self.report["status"], "passed")
        self.assertEqual(
            self.report["source_metrics"],
            {
                "landform_count": 6,
                "main_massif_count": 2,
                "foothill_count": 4,
                "open_saddle_count": 2,
                "permission_pixels": 227663,
                "g3_segment_count": 79,
            },
        )
        self.assertEqual(
            [variant["slug"] for variant in self.report["variants"]],
            ["balanced"],
        )
        self.assertEqual(self.report["global_contract"]["variant_count"], 1)

        variant = self.report["variants"][0]
        self.assertEqual(variant["status"], "passed")
        self.assertEqual(variant["immediate_failures"], [])
        output = REPO_ROOT / variant["output_path"]
        self.assertTrue(output.is_file())
        self.assertEqual(MODULE.h1._sha256(output), variant["output_sha256"])
        with Image.open(output) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.size, (1536, 1024))

        for name in (
            "comparison-full.png",
            "comparison-north-east.png",
            "comparison-south-east.png",
            "report.json",
        ):
            self.assertTrue((self.output_dir / name).is_file(), name)

    def test_fixed_protection_and_subtractive_contract_is_exact(self) -> None:
        contract = self.report["global_contract"]
        self.assertEqual(contract["road_core_width_px"], 16)
        self.assertEqual(
            contract["detail_selection_operator"], "high-frequency-and-dark"
        )
        self.assertEqual(
            contract["render_operation"],
            "subtractive-only non-lighting RGB delta",
        )
        self.assertFalse(contract["uses_g3_segment_orientations"])
        self.assertFalse(contract["closed_contours_allowed"])
        self.assertFalse(contract["broad_direction_fields_allowed"])

        metrics = self.report["variants"][0]["metrics"]
        gates = metrics["gates"]
        for gate_name in ("outside_g2_permission", "road_core", "detail_core"):
            self.assertEqual(gates[gate_name]["changed_pixels"], 0)
            self.assertEqual(gates[gate_name]["maximum_channel_difference"], 0)
        self.assertEqual(
            gates["detail_core"]["selection_operator"],
            "high-frequency-and-dark",
        )
        self.assertEqual(gates["non_lighting"]["brightened_pixels"], 0)
        self.assertEqual(gates["non_lighting"]["maximum_channel_increase"], 0)
        self.assertGreater(gates["boundary_feather"]["partial_alpha_pixels"], 0)
        self.assertEqual(metrics["road_core_pixels"], 27606)

    def test_each_landform_uses_short_open_non_convergent_structure(self) -> None:
        landforms = self.report["variants"][0]["metrics"]["landforms"]
        self.assertEqual(len(landforms), 6)
        main = [item for item in landforms if item["role"] == "main-massif"]
        foothills = [item for item in landforms if item["role"] != "main-massif"]
        self.assertEqual(len(main), 2)
        self.assertEqual(len(foothills), 4)

        for item in landforms:
            self.assertEqual(item["closed_contour_count"], 0)
            self.assertEqual(item["long_outline_count"], 0)
            self.assertEqual(item["saddle_changed_pixels"], 0)
            self.assertLessEqual(item["maximum_crest_length_px"], 45)
            self.assertLessEqual(item["maximum_endpoints_per_8px_bucket"], 4)
            self.assertLessEqual(item["line_coverage_fraction"], 0.08)
            self.assertLessEqual(item["strong_changed_fraction"], 0.15)
            self.assertGreater(item["readability"][0]["strong_pixels"], 0)
            self.assertGreater(item["readability"][1]["strong_pixels"], 0)

        for item in main:
            self.assertEqual(item["rise_spine_counts"], [3, 3])
            self.assertEqual(item["declared_hachure_count"], 0)
            self.assertEqual(item["open_crest_count"], 6)
            self.assertGreaterEqual(item["readability"][1]["strong_pixels"], 80)

        for item in foothills:
            self.assertEqual(item["open_crest_count"], 1)
            self.assertTrue(item["one_sided_hachures"])
            self.assertGreaterEqual(item["declared_hachure_count"], 2)
            self.assertLessEqual(item["declared_hachure_count"], 4)
            self.assertGreaterEqual(item["readability"][1]["strong_pixels"], 12)

        signatures = {
            (
                tuple(item["crest_bearings_degrees"]),
                item["declared_hachure_count"],
                tuple(item["declared_hachure_length_range_px"]),
            )
            for item in foothills
        }
        self.assertEqual(len(signatures), 4)

    def test_balanced_output_and_report_metrics_are_byte_deterministic(self) -> None:
        first_dir = Path(self._temporary.name) / "determinism-a"
        second_dir = Path(self._temporary.name) / "determinism-b"
        first = MODULE.render_all(first_dir)
        second = MODULE.render_all(second_dir)
        self.assertEqual(
            (first_dir / "h2-balanced.png").read_bytes(),
            (second_dir / "h2-balanced.png").read_bytes(),
        )
        self.assertEqual(
            first["variants"][0]["metrics"], second["variants"][0]["metrics"]
        )
        self.assertEqual(
            first["variants"][0]["output_sha256"],
            second["variants"][0]["output_sha256"],
        )

    def test_existing_diagnostic_is_not_overwritten_without_opt_in(self) -> None:
        report_path = self.output_dir / "report.json"
        sentinel = json.loads(report_path.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(
            MODULE.RidgeGlyphPrototypeError, "refusing to overwrite"
        ):
            MODULE.render_all(self.output_dir)
        self.assertEqual(json.loads(report_path.read_text(encoding="utf-8")), sentinel)


if __name__ == "__main__":
    unittest.main()
