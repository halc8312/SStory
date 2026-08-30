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
MODULE_PATH = SCRIPT_DIR / "render_candidate_h3_organic_tonal_relief.py"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location(
    "candidate_h3_organic_tonal_relief", MODULE_PATH
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CandidateH3OrganicTonalReliefTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(
            prefix="sstory-h3-prototype-", dir=REPO_ROOT
        )
        cls.output_dir = Path(cls._temporary.name) / "all"
        cls.report = MODULE.render_all(cls.output_dir)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_single_diagnostic_and_locked_source_topology_pass(self) -> None:
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
        self.assertEqual(len(self.report["variants"]), 1)
        variant = self.report["variants"][0]
        self.assertEqual(variant["slug"], "balanced")
        self.assertEqual(variant["status"], "passed")
        self.assertEqual(variant["immediate_failures"], [])

        output = REPO_ROOT / variant["output_path"]
        self.assertEqual(MODULE.h1._sha256(output), variant["output_sha256"])
        with Image.open(output) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.size, (1536, 1024))

        expected_comparisons = {
            "comparison-full.png",
            "comparison-north-east.png",
            "comparison-south-east.png",
            "comparison-scale-25.png",
            "comparison-scale-50.png",
            "comparison-scale-100.png",
        }
        self.assertEqual(
            {Path(item["path"]).name for item in self.report["comparisons"]},
            expected_comparisons,
        )
        for item in self.report["comparisons"]:
            path = REPO_ROOT / item["path"]
            self.assertTrue(path.is_file())
            self.assertEqual(MODULE.h1._sha256(path), item["sha256"])

    def test_protected_pixels_saddles_and_subtractive_operation_are_exact(self) -> None:
        contract = self.report["global_contract"]
        self.assertEqual(contract["road_core_width_px"], 16)
        self.assertEqual(
            contract["detail_selection_operator"], "high-frequency-and-dark"
        )
        self.assertFalse(contract["uses_g3_segment_orientations"])
        self.assertFalse(contract["visible_line_glyphs_allowed"])
        self.assertFalse(contract["plain_blurred_ellipse_allowed"])
        self.assertEqual(contract["footprint_wash_delta_range"], [0, 3])

        metrics = self.report["variants"][0]["metrics"]
        gates = metrics["gates"]
        for gate_name in ("outside_g2_permission", "road_core", "detail_core"):
            self.assertEqual(gates[gate_name]["changed_pixels"], 0)
            self.assertEqual(gates[gate_name]["maximum_channel_difference"], 0)
        self.assertEqual(gates["road_core"]["width_px"], 16)
        self.assertEqual(gates["road_core"]["protected_pixels"], 27606)
        self.assertEqual(
            gates["detail_core"]["selection_operator"],
            "high-frequency-and-dark",
        )
        self.assertEqual(gates["non_lighting"]["brightened_pixels"], 0)
        self.assertEqual(gates["non_lighting"]["maximum_channel_increase"], 0)
        self.assertEqual(gates["open_saddles"]["count"], 2)
        self.assertEqual(gates["open_saddles"]["changed_pixels"], 0)
        self.assertGreaterEqual(gates["open_saddles"]["minimum_width_px"], 26)
        self.assertGreater(gates["boundary_feather"]["partial_alpha_pixels"], 0)
        self.assertLessEqual(metrics["maximum_channel_difference"], 26)

    def test_renderer_has_no_terrain_line_system(self) -> None:
        no_lines = self.report["variants"][0]["metrics"]["gates"]["no_line_renderer"]
        self.assertTrue(no_lines["validated"])
        for key, value in no_lines.items():
            if key != "validated":
                self.assertEqual(value, 0, key)

        renderer_source = MODULE_PATH.read_text(encoding="utf-8").split(
            "def _full_comparison", maxsplit=1
        )[0]
        self.assertNotIn("ImageDraw", renderer_source)
        self.assertNotIn(".line(", renderer_source)
        self.assertNotIn("hachure_union", renderer_source)
        self.assertNotIn("crest_union", renderer_source)

    def test_two_unequal_main_lobes_and_four_distinct_foothills(self) -> None:
        metrics = self.report["variants"][0]["metrics"]
        landforms = metrics["landforms"]
        main = [item for item in landforms if item["role"] == "main-massif"]
        foothills = [item for item in landforms if item["role"] != "main-massif"]
        self.assertEqual(len(main), 2)
        self.assertEqual(len(foothills), 4)
        self.assertEqual(metrics["raw_tonal_component_count"], 8)
        self.assertEqual(metrics["gates"]["tonal_components"]["actual"], 8)
        self.assertEqual(
            metrics["gates"]["tonal_components"]["main_lobes_each"], [2, 2]
        )
        self.assertEqual(
            metrics["gates"]["tonal_components"]["foothill_lobes_each"],
            [1, 1, 1, 1],
        )

        for item in main:
            self.assertEqual(item["declared_lobe_count"], 2)
            self.assertEqual(item["raw_tonal_component_count"], 2)
            first, second = item["lobes"]
            self.assertNotEqual(first["radii_px"], second["radii_px"])
            self.assertNotEqual(
                first["declared_peak_delta_levels"],
                second["declared_peak_delta_levels"],
            )
            first_aspect = first["radii_px"][0] / first["radii_px"][1]
            second_aspect = second["radii_px"][0] / second["radii_px"][1]
            self.assertGreater(abs(first_aspect - second_aspect), 0.7)

        signatures = set()
        for item in foothills:
            self.assertEqual(item["declared_lobe_count"], 1)
            self.assertEqual(item["raw_tonal_component_count"], 1)
            lobe = item["lobes"][0]
            signatures.add(
                (
                    tuple(lobe["radii_px"]),
                    lobe["rotation_degrees"],
                    lobe["declared_peak_delta_levels"],
                    lobe["edge_noise_seed_sha256"],
                )
            )
        self.assertEqual(len(signatures), 4)

    def test_sha_noise_asymmetry_delta_ranges_and_downscale_survival(self) -> None:
        metrics = self.report["variants"][0]["metrics"]
        for scale in ("0.5", "0.25"):
            self.assertEqual(
                metrics["gates"]["downscale_survival"][scale],
                {"surviving_landforms": 6, "required_landforms": 6},
            )

        minimum_mismatch = self.report["variants"][0]["parameters"][
            "minimum_rotational_mismatch_fraction"
        ]
        for landform in metrics["landforms"]:
            lower, upper = (16, 26) if landform["role"] == "main-massif" else (13, 22)
            self.assertEqual(landform["saddle_changed_pixels"], 0)
            self.assertLessEqual(landform["footprint_wash_delta_levels"], 3)
            for readability in landform["readability"]:
                self.assertTrue(readability["survives"])
                self.assertGreaterEqual(
                    readability["signal_mean_max_channel_difference"],
                    readability["minimum_signal_mean"],
                )
                self.assertGreaterEqual(
                    readability["signal_to_background_ratio"],
                    readability["minimum_signal_to_background_ratio"],
                )
                self.assertGreaterEqual(
                    readability["strong_signal_pixels"],
                    readability["minimum_strong_signal_pixels"],
                )
            for lobe in landform["lobes"]:
                self.assertEqual(len(lobe["edge_noise_seed_sha256"]), 64)
                self.assertEqual(len(lobe["density_noise_seed_sha256"]), 64)
                self.assertEqual(lobe["support_component_count"], 1)
                self.assertEqual(lobe["saddle_support_pixels"], 0)
                self.assertGreaterEqual(
                    lobe["rotational_symmetry_mismatch_fraction"],
                    minimum_mismatch,
                )
                self.assertGreaterEqual(lobe["raw_peak_delta_levels"], lower)
                self.assertLessEqual(lobe["raw_peak_delta_levels"], upper)

    def test_candidate_pixels_and_metrics_are_deterministic(self) -> None:
        inputs = MODULE.h1.load_inputs()
        first = second = None
        try:
            first, first_report = MODULE._render_candidate(inputs)
            second, second_report = MODULE._render_candidate(inputs)
            self.assertEqual(first.tobytes(), second.tobytes())
            self.assertEqual(first_report, second_report)
        finally:
            inputs.close()
            if first is not None:
                first.close()
            if second is not None:
                second.close()

    def test_existing_diagnostic_is_not_overwritten_without_opt_in(self) -> None:
        report_path = self.output_dir / "report.json"
        sentinel = json.loads(report_path.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(
            MODULE.OrganicTonalReliefError, "refusing to overwrite"
        ):
            MODULE.render_all(self.output_dir)
        self.assertEqual(json.loads(report_path.read_text(encoding="utf-8")), sentinel)


if __name__ == "__main__":
    unittest.main()
