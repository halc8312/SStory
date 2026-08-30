from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    REPO_ROOT
    / "scripts"
    / "map-production"
    / "extract_style_candidate_k3_golden_v3_v19_statistics.py"
)
SPEC = importlib.util.spec_from_file_location("golden_v3_v19_statistics", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load v19 statistics extractor")
STATS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATS)


class GoldenV3V19StatisticsFirewallTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import numpy as np

        cls.np = np

    def _synthetic_inputs(self):
        np = self.np
        contour = np.array(
            [
                [0.0, 0.25, -0.25, 0.5, 0.75, 1.0],
                [1.25, -1.0, -0.5, 0.0, 0.5, 1.0],
                [1.5, 1.0, 0.25, -0.75, -1.25, 0.75],
                [2.0, 1.25, 0.5, -0.5, -1.5, 0.25],
                [2.5, 1.75, 1.0, -0.25, -2.0, 0.0],
            ],
            dtype=np.float32,
        )
        support = np.array(
            [
                [0, 1, 1, 1, 0, 0],
                [1, 1, 0, 1, 1, 0],
                [1, 0, 1, 1, 1, 0],
                [0, 1, 1, 0, 1, 1],
                [0, 0, 1, 1, 1, 0],
            ],
            dtype=bool,
        )
        lab = np.zeros((5, 6, 3), dtype=np.uint8)
        lab[..., 0] = np.arange(30, dtype=np.uint8).reshape(5, 6)
        lab[..., 1] = 128
        lab[..., 2] = np.flipud(lab[..., 0])
        return contour, lab, support

    def _valid_record(self) -> dict:
        bodies = {}
        for index, control_value in enumerate(STATS.BODY_CONTROL_VALUES):
            bodies[str(control_value)] = {
                "support_sha256": STATS.EXPECTED_SUPPORT_SHA256[control_value],
                "median_lab_q16": [
                    (40 + index) * STATS.Q_SCALE,
                    128 * STATS.Q_SCALE,
                    127 * STATS.Q_SCALE,
                ],
                "radial_power_q16": [STATS.Q_SCALE]
                + [0] * (STATS.RADIAL_POWER_LENGTH - 1),
                "quantiles_q16": [
                    (position - 8 + index) * STATS.Q_SCALE
                    for position in STATS.QUANTILE_NUMERATORS
                ],
            }
        return {
            "schema_id": STATS.SCHEMA_ID,
            "record_id": STATS.RECORD_ID,
            "source_hashes": STATS.expected_source_hashes(),
            "body_statistics": bodies,
        }

    def test_frozen_schema_and_numerical_conventions(self) -> None:
        self.assertEqual(STATS.SCHEMA_ID, "sstory.k3.golden-v3.v19-contour-statistics.v1")
        self.assertEqual(
            STATS.RECORD_ID, "k3-golden-v3-v19-contour-field-bodies-32-224"
        )
        self.assertEqual(STATS.BODY_CONTROL_VALUES, (32, 64, 96, 128, 160, 192, 224))
        self.assertNotIn(255, STATS.BODY_CONTROL_VALUES)
        self.assertEqual(STATS.Q_TOTAL_BITS, 32)
        self.assertEqual(STATS.Q_FRACTION_BITS, 16)
        self.assertEqual(STATS.Q_SCALE, 65_536)
        self.assertEqual(STATS.SPATIAL_PADDING_PIXELS, 8)
        self.assertEqual(STATS.RADIAL_POWER_LENGTH, 16)
        self.assertEqual(STATS.QUANTILE_DENOMINATOR, 16)
        self.assertEqual(STATS.QUANTILE_NUMERATORS, tuple(range(17)))
        self.assertEqual(STATS.QUANTILE_LENGTH, 17)
        self.assertEqual(
            STATS.BODY_STATISTIC_KEYS,
            {
                "support_sha256",
                "median_lab_q16",
                "radial_power_q16",
                "quantiles_q16",
            },
        )
        self.assertEqual(
            STATS.SOURCE_HASH_KEYS,
            {
                "v19_contour_field_array_sha256",
                "v19_final_pixel_array_sha256",
                "v19_renderer_sha256",
                "v19_replay_contract_sha256",
                "v19_statistics_extractor_sha256",
                "v19_transitive_inputs_sha256",
            },
        )
        self.assertEqual(
            STATS.SOURCE_HASH_KEY_ORDER,
            (
                "v19_contour_field_array_sha256",
                "v19_final_pixel_array_sha256",
                "v19_renderer_sha256",
                "v19_replay_contract_sha256",
                "v19_statistics_extractor_sha256",
                "v19_transitive_inputs_sha256",
            ),
        )
        STATS.validate_schema_definition()

    def test_tiny_synthetic_measurement_is_byte_deterministic(self) -> None:
        contour, lab, support = self._synthetic_inputs()
        first = STATS._measure_body(contour, lab, support, self.np)
        second = STATS._measure_body(contour.copy(), lab.copy(), support.copy(), self.np)
        expected = {
            "median_lab_q16": [950272, 8388608, 950272],
            "quantiles_q16": [
                -131072,
                -97280,
                -79872,
                -62464,
                -40960,
                -16384,
                -10240,
                7168,
                16384,
                16384,
                26624,
                32768,
                32768,
                59392,
                79872,
                81920,
                98304,
            ],
            "radial_power_q16": [
                0,
                760,
                3864,
                5965,
                6349,
                7293,
                8131,
                6440,
                6866,
                4391,
                3762,
                4801,
                4093,
                2003,
                800,
                18,
            ],
        }
        self.assertEqual(first, expected)
        self.assertEqual(second, expected)
        self.assertEqual(len(first["median_lab_q16"]), 3)
        self.assertEqual(len(first["radial_power_q16"]), 16)
        self.assertEqual(len(first["quantiles_q16"]), 17)
        self.assertEqual(sum(first["radial_power_q16"]), STATS.Q_SCALE)

    def test_radial_power_removes_dc_and_constant_support_has_zero_power(self) -> None:
        contour, lab, support = self._synthetic_inputs()
        baseline = STATS._measure_body(contour, lab, support, self.np)
        shifted = STATS._measure_body(contour + self.np.float32(17.0), lab, support, self.np)
        self.assertEqual(shifted["radial_power_q16"], baseline["radial_power_q16"])
        constant = self.np.full(contour.shape, 4.25, dtype=self.np.float32)
        measured = STATS._measure_body(constant, lab, support, self.np)
        self.assertEqual(measured["radial_power_q16"], [0] * 16)

    def test_type7_interpolation_ties_and_nearest_even_q16_are_fixed(self) -> None:
        np = self.np
        tied = np.asarray([0.0, 0.0, 0.0, 4.0], dtype=np.float64)
        self.assertEqual(STATS._type7_quantile(tied, 0, 16), 0.0)
        self.assertEqual(STATS._type7_quantile(tied, 8, 16), 0.0)
        self.assertEqual(STATS._type7_quantile(tied, 12, 16), 1.0)
        self.assertEqual(STATS._type7_quantile(tied, 16, 16), 4.0)
        self.assertEqual(STATS._quantize_q16(0.5 / STATS.Q_SCALE, "tie-even"), 0)
        self.assertEqual(STATS._quantize_q16(1.5 / STATS.Q_SCALE, "tie-even"), 2)
        with self.assertRaisesRegex(STATS.StatisticsFirewallError, "non-finite"):
            STATS._quantize_q16(float("nan"), "synthetic")

    def test_exact_schema_rejects_unknown_forbidden_and_wrong_shaped_values(self) -> None:
        valid = self._valid_record()
        self.assertIs(STATS.validate_statistics_record(valid), valid)

        mutations = []
        top_metadata = copy.deepcopy(valid)
        top_metadata["metadata"] = {}
        mutations.append(top_metadata)

        body_phase = copy.deepcopy(valid)
        body_phase["body_statistics"]["32"]["phase"] = [0, 1]
        mutations.append(body_phase)

        body_255 = copy.deepcopy(valid)
        body_255["body_statistics"]["255"] = copy.deepcopy(
            body_255["body_statistics"]["224"]
        )
        mutations.append(body_255)

        prompt_hash = copy.deepcopy(valid)
        prompt_hash["source_hashes"]["prompt_sha256"] = "0" * 64
        mutations.append(prompt_hash)

        short_psd = copy.deepcopy(valid)
        short_psd["body_statistics"]["32"]["radial_power_q16"].pop()
        mutations.append(short_psd)

        bool_q = copy.deepcopy(valid)
        bool_q["body_statistics"]["32"]["quantiles_q16"][0] = True
        mutations.append(bool_q)

        descending_cdf = copy.deepcopy(valid)
        descending_cdf["body_statistics"]["32"]["quantiles_q16"][1] = -99_999_999
        mutations.append(descending_cdf)

        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                with self.assertRaises(STATS.StatisticsFirewallError):
                    STATS.validate_statistics_record(mutation)

    def test_synthetic_q16_firewall_rejects_bool_bounds_lab_and_bad_psd(self) -> None:
        valid = self._valid_record()
        STATS.validate_statistics_record(valid)

        for field, index in (
            ("median_lab_q16", 0),
            ("radial_power_q16", 0),
            ("quantiles_q16", 0),
        ):
            mutation = copy.deepcopy(valid)
            mutation["body_statistics"]["32"][field][index] = True
            with self.subTest(rule="bool", field=field):
                with self.assertRaisesRegex(
                    STATS.StatisticsFirewallError, "must be a JSON integer"
                ):
                    STATS.validate_statistics_record(mutation)

        signed_low = copy.deepcopy(valid)
        signed_low["body_statistics"]["32"]["quantiles_q16"][0] = STATS.Q_MIN - 1
        signed_high = copy.deepcopy(valid)
        signed_high["body_statistics"]["32"]["quantiles_q16"][-1] = STATS.Q_MAX + 1
        for label, mutation in (("signed-low", signed_low), ("signed-high", signed_high)):
            with self.subTest(rule=label):
                with self.assertRaisesRegex(
                    STATS.StatisticsFirewallError, "outside signed Q16.16 range"
                ):
                    STATS.validate_statistics_record(mutation)

        lab_low = copy.deepcopy(valid)
        lab_low["body_statistics"]["32"]["median_lab_q16"][0] = -1
        lab_high = copy.deepcopy(valid)
        lab_high["body_statistics"]["32"]["median_lab_q16"][2] = (
            255 * STATS.Q_SCALE + 1
        )
        for label, mutation in (("lab-low", lab_low), ("lab-high", lab_high)):
            with self.subTest(rule=label):
                with self.assertRaisesRegex(
                    STATS.StatisticsFirewallError, "outside uint8 Lab"
                ):
                    STATS.validate_statistics_record(mutation)

        psd_negative = copy.deepcopy(valid)
        psd_negative["body_statistics"]["32"]["radial_power_q16"][0] = -1
        psd_over_unity = copy.deepcopy(valid)
        psd_over_unity["body_statistics"]["32"]["radial_power_q16"][0] = (
            STATS.Q_SCALE + 1
        )
        psd_not_normalized = copy.deepcopy(valid)
        psd_not_normalized["body_statistics"]["32"]["radial_power_q16"] = [1] * 16
        for label, mutation in (
            ("psd-negative", psd_negative),
            ("psd-over-unity", psd_over_unity),
            ("psd-not-normalized", psd_not_normalized),
        ):
            with self.subTest(rule=label):
                with self.assertRaises(STATS.StatisticsFirewallError):
                    STATS.validate_statistics_record(mutation)

    def test_output_key_firewall_contains_no_coordinates_pixels_phase_or_refs(self) -> None:
        record = self._valid_record()
        STATS.validate_statistics_record(record)
        self.assertEqual(set(record), STATS.TOP_LEVEL_KEYS)
        self.assertEqual(set(record["source_hashes"]), STATS.SOURCE_HASH_KEYS)
        for body in record["body_statistics"].values():
            self.assertEqual(set(body), STATS.BODY_STATISTIC_KEYS)
        rendered = STATS.canonical_statistics_json(record).decode("ascii")
        for forbidden_key in (
            '"coordinates"',
            '"x"',
            '"y"',
            '"crop"',
            '"padding"',
            '"phase"',
            '"rgb"',
            '"chroma"',
            '"prompt"',
            '"material"',
            '"metadata"',
            '"pixels"',
            '"arrays"',
        ):
            self.assertNotIn(forbidden_key, rendered)

    def test_canonical_json_and_exclusive_create_are_fail_closed(self) -> None:
        record = self._valid_record()
        payload = STATS.canonical_statistics_json(record)
        self.assertTrue(payload.endswith(b"\n"))
        self.assertNotIn(b"\n", payload[:-1])
        self.assertNotIn(b": ", payload)
        self.assertEqual(payload, STATS.canonical_statistics_json(json.loads(payload)))

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "synthetic-statistics.json"
            STATS._exclusive_create(output, payload)
            self.assertEqual(STATS.load_canonical_statistics(output), record)
            with self.assertRaisesRegex(
                STATS.StatisticsFirewallError, "refusing to overwrite"
            ):
                STATS._exclusive_create(output, payload)

            noncanonical = Path(temporary) / "noncanonical.json"
            noncanonical.write_text(json.dumps(record, indent=2), encoding="utf-8")
            with self.assertRaisesRegex(
                STATS.StatisticsFirewallError, "not canonical JSON"
            ):
                STATS.load_canonical_statistics(noncanonical)

    def test_import_and_default_check_do_not_load_v19_or_pixel_packages(self) -> None:
        probe = r'''
import importlib.util
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
before = set(sys.modules)
spec = importlib.util.spec_from_file_location("isolated_statistics_probe", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
status = module.main([])
introduced = sorted(set(sys.modules) - before)
forbidden = [
    name for name in introduced
    if name == "numpy" or name.startswith("numpy.")
    or name == "cv2" or name.startswith("cv2.")
    or name == "PIL" or name.startswith("PIL.")
    or "v19_statistics_replay" in name
]
print(json.dumps({"status": status, "forbidden": forbidden}, sort_keys=True))
'''
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, "-I", "-c", probe, str(SCRIPT_PATH)],
            cwd=REPO_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result, {"forbidden": [], "status": 0})

        tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
        imported_roots = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
        self.assertTrue({"numpy", "cv2", "PIL"}.isdisjoint(imported_roots))

    def test_check_binds_renderer_contract_and_historical_array_hashes(self) -> None:
        before = set(sys.modules)
        source_hashes = STATS.check_sources(REPO_ROOT)
        introduced = set(sys.modules) - before
        self.assertEqual(source_hashes, STATS.expected_source_hashes())
        self.assertEqual(
            source_hashes["v19_statistics_extractor_sha256"],
            hashlib.sha256(SCRIPT_PATH.read_bytes()).hexdigest(),
        )
        self.assertFalse(
            any(
                name == "cv2"
                or name.startswith("cv2.")
                or name == "PIL"
                or name.startswith("PIL.")
                or "v19_statistics_replay" in name
                for name in introduced
            )
        )
        renderer = (
            REPO_ROOT
            / "scripts"
            / "map-production"
            / "build_style_candidate_k3_sparse_ridgeline_v19.py"
        ).read_bytes()
        self.assertIn(
            STATS.EXPECTED_V19_CONTOUR_FIELD_ARRAY_SHA256.encode("ascii"), renderer
        )
        self.assertIn(STATS.EXPECTED_V19_FINAL_PIXEL_ARRAY_SHA256.encode("ascii"), renderer)


if __name__ == "__main__":
    unittest.main()
