from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    REPO_ROOT
    / "scripts/map-production/render_candidate_h1_deterministic_hachure.py"
)
SPEC = importlib.util.spec_from_file_location(
    "candidate_h1_deterministic_hachure", MODULE_PATH
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CandidateH1DeterministicHachureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(
            prefix="sstory-h1-prototype-", dir=REPO_ROOT
        )
        cls.output_dir = Path(cls._temporary.name) / "all"
        cls.report = MODULE.render_all(cls.output_dir)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_all_three_variants_pass_the_full_diagnostic_contract(self) -> None:
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
            [entry["slug"] for entry in self.report["variants"]],
            ["balanced", "quiet", "textured"],
        )
        for variant in self.report["variants"]:
            self.assertEqual(variant["status"], "passed")
            self.assertEqual(variant["immediate_failures"], [])
            self.assertEqual(len(variant["metrics"]["landforms"]), 6)
            output = REPO_ROOT / variant["output_path"]
            self.assertTrue(output.is_file())
            self.assertEqual(MODULE._sha256(output), variant["output_sha256"])
            with Image.open(output) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.mode, "RGB")
                self.assertEqual(image.size, (1536, 1024))

    def test_pixel_identity_non_lighting_and_visibility_gates_are_explicit(self) -> None:
        for variant in self.report["variants"]:
            metrics = variant["metrics"]
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
            self.assertLessEqual(metrics["maximum_channel_difference"], 56)
            for landform in metrics["landforms"]:
                minimum = 900 if landform["role"] == "main-massif" else 250
                self.assertGreaterEqual(landform["visible_hachure_pixels"], minimum)
                self.assertGreaterEqual(landform["orientation_bins_15_degrees"], 6)
                self.assertEqual(landform["radial_convergence_failure_count"], 0)
                self.assertLessEqual(
                    landform["tangential_alignment_fraction"], 0.20
                )
                self.assertLessEqual(
                    landform["maximum_endpoints_per_8px_bucket"], 4
                )
                self.assertEqual(
                    landform["saddle_hachure_pixels_after_protection"], 0
                )

    def test_balanced_variant_is_byte_deterministic(self) -> None:
        first_dir = Path(self._temporary.name) / "determinism-a"
        second_dir = Path(self._temporary.name) / "determinism-b"
        first = MODULE.render_all(first_dir, (MODULE.VARIANT_BY_SLUG["balanced"],))
        second = MODULE.render_all(second_dir, (MODULE.VARIANT_BY_SLUG["balanced"],))
        first_path = first_dir / "h1-balanced.png"
        second_path = second_dir / "h1-balanced.png"
        self.assertEqual(first_path.read_bytes(), second_path.read_bytes())
        self.assertEqual(
            first["variants"][0]["metrics"], second["variants"][0]["metrics"]
        )
        self.assertEqual(
            first["variants"][0]["output_sha256"],
            second["variants"][0]["output_sha256"],
        )

    def test_detail_selection_is_and_not_or(self) -> None:
        base = Image.new("RGB", (101, 101), (180, 180, 180))
        try:
            for y in range(40, 61):
                for x in range(40, 61):
                    base.putpixel((x, y), (80, 80, 80))
            base.putpixel((20, 20), (45, 45, 45))
            base.putpixel((80, 80), (255, 255, 255))
            details = MODULE.detail_core(base)
            try:
                self.assertEqual(details.getpixel((50, 50)), 0)
                self.assertEqual(details.getpixel((20, 20)), 255)
                self.assertEqual(details.getpixel((80, 80)), 0)
            finally:
                details.close()
        finally:
            base.close()

    def test_locked_input_hash_mismatch_fails_closed(self) -> None:
        tampered = Path(self._temporary.name) / "tampered.png"
        with Image.open(MODULE.BASE_PATH) as image:
            copy = image.convert("RGB")
            try:
                copy.putpixel((0, 0), tuple((value + 1) % 256 for value in copy.getpixel((0, 0))))
                copy.save(tampered, format="PNG")
            finally:
                copy.close()
        with self.assertRaisesRegex(MODULE.HachurePrototypeError, "SHA-256 mismatch"):
            MODULE._read_locked_image(
                tampered, MODULE.LOCKED_SHA256["base"], "tampered D4"
            )

    def test_existing_diagnostic_is_not_overwritten_without_opt_in(self) -> None:
        report_path = self.output_dir / "report.json"
        sentinel = json.loads(report_path.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(
            MODULE.HachurePrototypeError, "refusing to overwrite"
        ):
            MODULE.render_all(self.output_dir)
        self.assertEqual(
            json.loads(report_path.read_text(encoding="utf-8")), sentinel
        )


if __name__ == "__main__":
    unittest.main()
