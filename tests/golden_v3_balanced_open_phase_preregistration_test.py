from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT / "scripts/map-production/"
    "generate_style_candidate_k3_golden_v3_balanced_open_phase_v3.py"
)
SPEC = importlib.util.spec_from_file_location(
    "golden_v3_balanced_open_phase_v3", MODULE_PATH
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load balanced-open-phase-v3 generator")
generator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generator
SPEC.loader.exec_module(generator)


class GoldenV3BalancedOpenPhasePreregistrationTest(unittest.TestCase):
    """Synthetic-only tests: no production raster or candidate is opened."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.authority = generator.load_authority()
        cls.v1 = generator.load_v1_helper(cls.authority)

    def repair_config(self) -> dict[str, object]:
        config = copy.deepcopy(self.authority["derivation"]["construction_repair"])
        config["per_stage_pixel_budget_rational"] = [1, 1]
        config["combined_pixel_budget_rational"] = [1, 1]
        return config

    def test_authority_is_self_hashed_and_strict_authority_is_unchanged(self) -> None:
        authority = self.authority
        self.assertEqual(
            generator.authority_self_hash(authority),
            authority["canonical_self_sha256"],
        )
        strict = authority["strict_audit_authority"]
        self.assertEqual(
            strict["sha256"],
            "c27b41e6336974c5ce5fe11c86cefc67ed35851650680c33379c3510444884d7",
        )
        self.assertEqual(
            hashlib.sha256((ROOT / strict["path"]).read_bytes()).hexdigest(),
            strict["sha256"],
        )
        changed = copy.deepcopy(authority)
        changed["derivation"]["amplitude_construction"]["matching_iterations_exact"] = 5
        with self.assertRaisesRegex(generator.DerivationError, "self-hash"):
            generator.validate_authority(changed)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "authority.json"
            path.write_text(json.dumps(authority), encoding="utf-8")
            with self.assertRaisesRegex(generator.DerivationError, "canonical pretty"):
                generator.load_authority(path)

    def test_bound_text_bytes_and_runtime_match_the_v1_authority(self) -> None:
        generator.check_bound_sources(self.authority, root=ROOT, require_tracked=False)
        self.assertEqual(self.authority["runtime"], self.v1.EXPECTED_RUNTIME)
        changed = copy.deepcopy(self.authority)
        changed["runtime"]["common"]["python_version"] = "3.12.9"
        changed["canonical_self_sha256"] = generator.authority_self_hash(changed)
        with (
            mock.patch.object(generator, "check_bound_sources"),
            mock.patch.object(generator, "load_v1_helper", return_value=self.v1),
            mock.patch.object(generator, "load_v1_authority", return_value={}),
            self.assertRaisesRegex(generator.DerivationError, "runtime differs"),
        ):
            generator.validate_only(changed)

    def test_exact_four_records_and_every_parameter_is_closed(self) -> None:
        records = self.authority["candidates"]["records"]
        self.assertEqual(
            [record["candidate_id"] for record in records],
            [
                "E150-M500",
                "E150-M550",
                "E200-M500",
                "E200-M550",
            ],
        )
        self.assertEqual(
            [record["amplitude_depth_rational"] for record in records],
            [[3, 20], [3, 20], [1, 5], [1, 5]],
        )
        self.assertEqual(
            [record["g8_to_g24_gain_rational"] for record in records],
            [[5, 1], [11, 2], [5, 1], [11, 2]],
        )
        self.assertTrue(
            all(record["g4_to_g8_gain_rational"] == [7, 4] for record in records)
        )
        self.assertTrue(
            all(record["sub2_gain_rational"] == [0, 1] for record in records)
        )
        for key in (
            "amplitude_depth_rational",
            "sub2_gain_rational",
            "g2_to_g4_gain_rational",
            "g4_to_g8_gain_rational",
            "g8_to_g24_gain_rational",
            "statistical_overall_gain_rational",
            "dev20_g24_gain_rational",
        ):
            changed = copy.deepcopy(self.authority)
            changed["candidates"]["records"][0][key] = [99, 1]
            changed["canonical_self_sha256"] = generator.authority_self_hash(changed)
            with self.assertRaises(generator.DerivationError, msg=key):
                generator.validate_authority(changed)
        changed = copy.deepcopy(self.authority)
        changed["candidates"]["records"].append(copy.deepcopy(records[0]))
        changed["canonical_self_sha256"] = generator.authority_self_hash(changed)
        with self.assertRaises(generator.DerivationError):
            generator.validate_authority(changed)

    def test_plain_integer_closure_rejects_float_and_bool(self) -> None:
        mutations = (
            (
                "5.0 box width",
                lambda value: value["derivation"]["filters"]["construction_boxes"][
                    "widths"
                ].__setitem__(0, 5.0),
            ),
            (
                "true rational numerator",
                lambda value: value["candidates"]["records"][0][
                    "g2_to_g4_gain_rational"
                ].__setitem__(0, True),
            ),
            (
                "float kernel coefficient",
                lambda value: value["derivation"]["filters"]["G2"][
                    "coefficients"
                ].__setitem__(0, 71851.0),
            ),
            (
                "true repair integer",
                lambda value: value["derivation"]["construction_repair"].__setitem__(
                    "maximum_repairs_per_stage_per_body", True
                ),
            ),
            (
                "float mask q bits",
                lambda value: value["derivation"]["filters"][
                    "masked_normalization"
                ].__setitem__("mask_q_bits", 20.0),
            ),
            (
                "float signal q bits",
                lambda value: value["derivation"]["construction_repair"].__setitem__(
                    "signal_q_bits", 12.0
                ),
            ),
            (
                "false erosion radius",
                lambda value: value["derivation"]["amplitude_construction"][
                    "lag_decorrelation"
                ]["support_erosions_px"].__setitem__(1, False),
            ),
            (
                "true correlation numerator",
                lambda value: value["derivation"]["final_certificate"][
                    "maximum_absolute_correlation_rational"
                ].__setitem__(0, True),
            ),
            (
                "float nested lag coordinate",
                lambda value: value["derivation"]["unit_whitening"][
                    "lag_decorrelation"
                ]["lags_xy"][0].__setitem__(0, 32.0),
            ),
            (
                "float repair budget numerator",
                lambda value: value["derivation"]["construction_repair"][
                    "per_stage_pixel_budget_rational"
                ].__setitem__(0, 1.0),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                changed = copy.deepcopy(self.authority)
                mutate(changed)
                changed["canonical_self_sha256"] = generator.authority_self_hash(
                    changed
                )
                with self.assertRaises(generator.DerivationError):
                    generator.validate_authority(changed)
        generator.validate_authority(self.authority)

    def test_seed_table_is_unique_deterministic_and_candidate_independent(self) -> None:
        observed = []
        for body_index in range(8):
            for band_id in generator.BAND_IDS:
                first = generator.derive_seed(body_index, band_id)
                replay = generator.derive_seed(body_index, band_id)
                self.assertEqual(first, replay)
                observed.append(first)
        self.assertEqual(len({seed for seed, _ in observed}), 40)
        self.assertEqual(len({digest for _, digest in observed}), 40)
        self.assertTrue(
            generator._exact_json_equal(
                self.authority["derivation"]["seed_rule"],
                generator.EXPECTED_SEED_RULE,
            )
        )
        for vector in self.authority["derivation"]["seed_rule"]["test_vectors"]:
            body_index = generator.BODY_IDS.index(vector["body_id"])
            seed, digest = generator.derive_seed(body_index, vector["band_id"])
            self.assertEqual(digest, vector["sha256"])
            self.assertEqual(seed, vector["uint64"])
            self.assertEqual(
                vector["label"],
                f"{generator.SEED_ROOT}:{vector['body_id']}:{vector['band_id']}",
            )
        self.assertTrue(
            self.authority["derivation"]["phase_policy"][
                "same_phase_table_for_all_candidates"
            ]
        )
        with self.assertRaises(generator.DerivationError):
            generator.derive_seed(8, "g2-g4")
        with self.assertRaises(generator.DerivationError):
            generator.derive_seed(0, "candidate-specific")

    def test_independent_band_synthesis_consumes_exactly_three_fixed_seeds(
        self,
    ) -> None:
        class FakeV1:
            def __init__(self) -> None:
                self.seeds: list[int] = []
                self.filter_calls: list[tuple[str, int]] = []

            def synthesize_statistical_phase(
                self,
                shape: tuple[int, int],
                body: np.ndarray,
                statistics: object,
                seed: int,
            ) -> np.ndarray:
                del body, statistics
                self.seeds.append(seed)
                return np.full(shape, len(self.seeds) * 100, dtype=np.int64)

            def q30_filter(
                self, values: np.ndarray, record: dict[str, object]
            ) -> np.ndarray:
                tag = str(record["tag"])
                self.filter_calls.append((tag, int(values[0, 0])))
                return values + {"G2": 2, "G4": 4, "G8": 8, "G24": 24}[tag]

            @staticmethod
            def _checked_subtract_int64(
                left: np.ndarray, right: np.ndarray, *, label: str
            ) -> np.ndarray:
                del label
                return left - right

        fake = FakeV1()
        mask = np.ones((9, 11), dtype=bool)
        kernels = {name: {"tag": name} for name in ("G2", "G4", "G8", "G24")}
        observed = generator.synthesize_independent_bands(
            mask.shape, mask, object(), 3, kernels, v1=fake
        )
        expected = [
            generator.derive_seed(3, band)[0] for band in ("g2-g4", "g4-g8", "g8-g24")
        ]
        self.assertEqual(fake.seeds, expected)
        self.assertEqual(len(set(fake.seeds)), 3)
        self.assertEqual(
            fake.filter_calls,
            [
                ("G2", 100),
                ("G4", 100),
                ("G4", 200),
                ("G8", 200),
                ("G8", 300),
                ("G24", 300),
            ],
        )
        self.assertTrue(np.all(observed.g2_to_g4 == -2))
        self.assertTrue(np.all(observed.g4_to_g8 == -4))
        self.assertTrue(np.all(observed.g8_to_g24 == -16))

    def test_g2_and_construction_box_kernels_are_exact(self) -> None:
        coefficients = generator.G2_COEFFICIENTS
        self.assertEqual(coefficients, coefficients[::-1])
        self.assertEqual(sum(coefficients), generator.Q30)
        payload = json.dumps(list(coefficients), separators=(",", ":")).encode()
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(), generator.G2_CANONICAL_SHA256
        )
        for width in (5, 17, 33):
            box = generator._uniform_q30_coefficients(width)
            self.assertEqual(len(box), width)
            self.assertEqual(box, box[::-1])
            self.assertEqual(sum(box), generator.Q30)
            constant = np.full((7, 9), -11 * generator.Q16, dtype=np.int64)
            filtered = generator.box_filter_q30(constant, width, self.v1)
            self.assertTrue(np.array_equal(filtered, constant))

    def test_telescoping_band_algebra_and_sub2_absence(self) -> None:
        source = np.arange(13 * 15, dtype=np.int64).reshape(13, 15) * 127
        kernels = self.v1.load_authority()["derivation"]["fixed_filters"]["kernels"]
        g2 = self.v1.q30_filter(
            source, {"coefficients": list(generator.G2_COEFFICIENTS)}
        )
        g4 = self.v1.q30_filter(source, kernels["G4"])
        g8 = self.v1.q30_filter(source, kernels["G8"])
        g24 = self.v1.q30_filter(source, kernels["G24"])
        reconstructed = (source - g2) + (g2 - g4) + (g4 - g8) + (g8 - g24) + g24
        self.assertTrue(np.array_equal(reconstructed, source))
        bands = generator.IndependentBands(
            g2_to_g4=np.asarray([8, -8], dtype=np.int64),
            g4_to_g8=np.asarray([12, -12], dtype=np.int64),
            g8_to_g24=np.asarray([16, -16], dtype=np.int64),
        )
        observed = generator.compose_statistical_field(
            bands, self.authority["candidates"]["records"][0], v1=self.v1
        )
        self.assertEqual(observed.tolist(), [109, -109])
        changed = copy.deepcopy(self.authority["candidates"]["records"][0])
        changed["sub2_gain_rational"] = [1, 10]
        with self.assertRaisesRegex(generator.DerivationError, "sub2"):
            generator.compose_statistical_field(bands, changed, v1=self.v1)

    def test_amplitude_unit_whitening_and_quiet_reserve_are_fixed(self) -> None:
        kernels = self.v1.load_authority()["derivation"]["fixed_filters"]["kernels"]
        mask = np.ones((96, 112), dtype=bool)
        yy, xx = np.indices(mask.shape)
        source = ((xx * 17 + yy * 29) % 31 - 15).astype(np.int64) * generator.Q16
        total, amplitude = generator.derive_amplitude_q16(
            source, mask, kernels["G8"], v1=self.v1
        )
        unit, replay_amplitude = generator.derive_unit_q16(
            source, mask, kernels["G8"], v1=self.v1
        )
        self.assertTrue(np.array_equal(amplitude, replay_amplitude))
        self.assertLessEqual(
            abs(int(np.sum(total[mask], dtype=np.int64))),
            int(np.count_nonzero(mask)) // 2,
        )
        self.assertLessEqual(
            abs(generator._rms_q16(unit, mask, self.v1) - generator.Q16), 2
        )

        quiet_config = self.authority["derivation"]["quiet_reserve"]
        quiet, clipped = generator.apply_quiet_reserve(
            source, mask, kernels["G4"], quiet_config, v1=self.v1
        )
        replay, replay_clipped = generator.apply_quiet_reserve(
            source, mask, kernels["G4"], quiet_config, v1=self.v1
        )
        self.assertTrue(np.array_equal(quiet, replay))
        self.assertEqual(clipped, replay_clipped)
        high = quiet - generator.masked_kernel_filter_q30(
            quiet, mask, kernels["G4"], v1=self.v1
        )
        self.assertLessEqual(int(np.max(np.abs(high[mask]))), 5 * generator.Q16)

        amplitude_config = copy.deepcopy(
            self.authority["derivation"]["amplitude_construction"]
        )
        amplitude_config["lag_decorrelation"] = {
            **amplitude_config["lag_decorrelation"],
            "lags_xy": [[8, 0], [0, 8]],
            "support_erosions_px": [0],
            "minimum_pairs_per_record": 128,
            "minimum_eligible_lags_per_support": 2,
            "maximum_absolute_correlation_rational": [1, 1],
            "fixed_sweeps": 4,
        }
        target, certificate = generator.construct_target_amplitude(
            source,
            mask,
            1234567,
            [3, 20],
            kernels["G4"],
            amplitude_config,
            v1=self.v1,
        )
        self.assertEqual(certificate.eligible_records, 2)
        self.assertGreater(int(target[mask].min()), 0)
        matched = generator.match_target_amplitude(
            source,
            target,
            mask,
            kernels["G8"],
            amplitude_config,
            v1=self.v1,
        )
        matched_replay = generator.match_target_amplitude(
            source,
            target,
            mask,
            kernels["G8"],
            amplitude_config,
            v1=self.v1,
        )
        self.assertTrue(np.array_equal(matched, matched_replay))

    def test_broad_lag_certificate_passes_seeded_field_and_rejects_periodicity(
        self,
    ) -> None:
        kernels = self.v1.load_authority()["derivation"]["fixed_filters"]["kernels"]
        config = self.authority["derivation"]["amplitude_construction"]
        mask = np.ones((320, 320), dtype=bool)
        mask[:8, :] = False
        mask[-8:, :] = False
        mask[:, :8] = False
        mask[:, -8:] = False
        source = ((np.indices(mask.shape).sum(axis=0) % 31) - 15).astype(
            np.int64
        ) * generator.Q16
        _, certificate = generator.construct_target_amplitude(
            source,
            mask,
            1_234_567,
            [3, 20],
            kernels["G4"],
            config,
            v1=self.v1,
        )
        self.assertGreaterEqual(certificate.eligible_records, 12)
        self.assertLessEqual(certificate.maximum_correlation_q20, (1 << 20) // 128)

        _, xx = np.indices(mask.shape)
        periodic = np.where((xx // 32) % 2, generator.Q16, -generator.Q16)
        with self.assertRaisesRegex(generator.DerivationError, "decorrelation"):
            generator.lag_certificate(
                periodic,
                mask,
                kernels["G4"],
                config["lag_decorrelation"],
                v1=self.v1,
            )

    def test_lag_whitening_traces_both_sweep_parities_exactly(self) -> None:
        kernels = self.v1.load_authority()["derivation"]["fixed_filters"]["kernels"]
        config = copy.deepcopy(
            self.authority["derivation"]["amplitude_construction"]["lag_decorrelation"]
        )
        config.update(
            {
                "lags_xy": [[2, 0], [0, 3]],
                "support_erosions_px": [0, 1],
                "fixed_sweeps": 2,
            }
        )
        mask = np.ones((24, 24), dtype=bool)
        yy, xx = np.indices(mask.shape)
        values = ((xx * 7 + yy * 11) % 23 - 11).astype(np.int64) * generator.Q16
        events: list[tuple[object, ...]] = []

        def traced_erode(selected: np.ndarray, radius: int) -> np.ndarray:
            events.append(("erosion", radius))
            return selected

        def traced_pearson(
            _field: np.ndarray,
            _support: np.ndarray,
            dx: int,
            dy: int,
            *,
            minimum_pairs: int,
        ) -> None:
            events.append(("lag", dx, dy, minimum_pairs))
            return None

        certificate = generator.LagCertificate(4, 0, 1, 0)
        with (
            mock.patch.object(generator, "disk_erode", side_effect=traced_erode),
            mock.patch.object(
                generator, "_pearson_components", side_effect=traced_pearson
            ),
            mock.patch.object(generator, "lag_certificate", return_value=certificate),
        ):
            _, observed_certificate = generator.whiten_lagged_field(
                values,
                mask,
                kernels["G4"],
                config,
                v1=self.v1,
            )
        minimum_pairs = config["minimum_pairs_per_record"]
        self.assertEqual(
            events,
            [
                ("erosion", 0),
                ("lag", 2, 0, minimum_pairs),
                ("lag", 0, 3, minimum_pairs),
                ("erosion", 1),
                ("lag", 2, 0, minimum_pairs),
                ("lag", 0, 3, minimum_pairs),
                ("erosion", 1),
                ("lag", 0, -3, minimum_pairs),
                ("lag", -2, 0, minimum_pairs),
                ("erosion", 0),
                ("lag", 0, -3, minimum_pairs),
                ("lag", -2, 0, minimum_pairs),
            ],
        )
        self.assertEqual(observed_certificate, certificate)

    def test_short_dark_repair_dissolves_short_line_and_preserves_long_one(
        self,
    ) -> None:
        mask = np.ones((64, 64), dtype=bool)
        values = np.zeros(mask.shape, dtype=np.int64)
        values[31, 25:35] = -10 * generator.Q16
        config = self.repair_config()
        repaired, count, touched = generator.repair_short_dark_components(
            values,
            mask,
            config["short_dark"],
            maximum_repairs=64,
            pixel_budget=mask.size,
            v1=self.v1,
        )
        self.assertGreater(count, 0)
        self.assertGreater(int(np.count_nonzero(touched)), 0)
        self.assertFalse(np.array_equal(repaired, values))
        long_values = np.zeros(mask.shape, dtype=np.int64)
        long_values[20, 10:45] = -10 * generator.Q16
        preserved, count, touched = generator.repair_short_dark_components(
            long_values,
            mask,
            config["short_dark"],
            maximum_repairs=64,
            pixel_budget=mask.size,
            v1=self.v1,
        )
        self.assertEqual(count, 0)
        self.assertFalse(np.any(touched))
        self.assertTrue(np.array_equal(preserved, long_values))
        with self.assertRaisesRegex(generator.DerivationError, "pixel budget"):
            generator.repair_short_dark_components(
                values,
                mask,
                config["short_dark"],
                maximum_repairs=64,
                pixel_budget=1,
                v1=self.v1,
            )
        with self.assertRaisesRegex(generator.DerivationError, "fully locked"):
            generator.repair_short_dark_components(
                values,
                mask,
                config["short_dark"],
                maximum_repairs=64,
                pixel_budget=mask.size,
                v1=self.v1,
                mutable=np.zeros(mask.shape, dtype=bool),
            )

    def test_cross_close_four_connect_topology_and_luma_vectors(self) -> None:
        rgb = np.asarray(
            [
                [
                    [0, 0, 0],
                    [255, 255, 255],
                    [255, 0, 0],
                    [0, 255, 0],
                    [0, 0, 255],
                    [1, 2, 3],
                ]
            ],
            dtype=np.uint8,
        )
        self.assertEqual(
            generator.construction_luma_u8(rgb).tolist()[0],
            [0, 255, 76, 150, 29, 2],
        )
        kernels = self.v1.load_authority()["derivation"]["fixed_filters"]["kernels"]
        checker_y, checker_x = np.indices((64, 64))
        checker = np.where((checker_x + checker_y) % 2, 1, -1).astype(np.int64)
        checker_mask = np.ones(checker.shape, dtype=bool)
        fields = generator.derive_final_fields_q12(
            checker,
            checker_mask,
            kernels["G8"],
            v1=self.v1,
        )
        self.assertTrue(np.array_equal(fields.total_q12, checker * generator.Q12))
        self.assertFalse(np.any(fields.amplitude_q12))
        self.assertLessEqual(
            abs(
                generator._rms_q16(fields.unit_q12, checker_mask, self.v1)
                - generator.Q12
            ),
            1,
        )

        core = np.ones((32, 32), dtype=bool)
        visible = np.zeros(core.shape, dtype=bool)
        visible[8:24, 8] = True
        visible[8:24, 23] = True
        visible[8, 8:24] = True
        visible[23, 8:24] = True
        self.assertIsNotNone(
            generator._first_enclosed_background(
                visible, core, 4, close_cross=True, minimum_area=4
            )
        )
        open_arc = visible.copy()
        open_arc[8, 14:19] = False
        self.assertIsNone(
            generator._first_enclosed_background(
                open_arc, core, 4, close_cross=True, minimum_area=4
            )
        )

        tiny = np.ones((12, 12), dtype=bool)
        tiny[5, 5:8] = False
        self.assertIsNone(
            generator._first_enclosed_background(
                tiny, core[:12, :12], 4, close_cross=False, minimum_area=4
            )
        )
        tiny[6, 5] = False
        self.assertIsNotNone(
            generator._first_enclosed_background(
                tiny, core[:12, :12], 4, close_cross=False, minimum_area=4
            )
        )

        diagonal = np.ones((12, 12), dtype=bool)
        diagonal[5, 5] = False
        diagonal[4, 4] = False
        diagonal[3, 3] = False
        diagonal[2, 2] = False
        diagonal[1, 1] = False
        diagonal[0, 0] = False
        self.assertIsNotNone(
            generator._first_enclosed_background(
                diagonal, core[:12, :12], 4, close_cross=False, minimum_area=1
            )
        )
        self.assertIsNone(
            generator._first_enclosed_background(
                diagonal, core[:12, :12], 8, close_cross=False, minimum_area=1
            )
        )

    def test_final_rgb_topology_repair_is_luma_aligned_and_budgeted(self) -> None:
        kernels = self.v1.load_authority()["derivation"]["fixed_filters"]["kernels"]
        body = np.ones((64, 64), dtype=bool)
        yy, xx = np.indices(body.shape)
        foundation_luma = (110 + (3 * xx + 5 * yy) % 21).astype(np.uint8)
        foundation = np.repeat(foundation_luma[..., None], 3, axis=2)
        candidate = foundation.copy()
        candidate[20:44, 20] += 16
        candidate[20:44, 43] += 16
        candidate[20, 20:44] += 16
        candidate[43, 20:44] += 16
        config = self.repair_config()
        repaired, count, touched = generator.repair_final_rgb_topology(
            candidate,
            foundation,
            [body],
            body,
            [np.zeros(body.shape, dtype=bool)],
            config,
            kernels,
            v1=self.v1,
        )
        self.assertGreater(count, 0)
        self.assertGreater(touched, 0)
        final_delta = (
            generator.construction_luma_u8(repaired).astype(np.int64)
            - generator.construction_luma_u8(foundation).astype(np.int64)
        ) * generator.Q12
        self.assertEqual(
            generator.topology_hole_count(
                final_delta,
                body,
                config["open_topology"],
                kernels,
                v1=self.v1,
            ),
            0,
        )
        channel_differences = repaired.astype(np.int16)
        self.assertTrue(
            np.array_equal(
                channel_differences[..., 0] - channel_differences[..., 1],
                candidate[..., 0].astype(np.int16) - candidate[..., 1].astype(np.int16),
            )
        )

        config = self.repair_config()
        config["combined_pixel_budget_rational"] = [1, 4096]
        with self.assertRaisesRegex(generator.DerivationError, "combined"):
            generator.repair_final_rgb_topology(
                foundation,
                foundation,
                [body],
                body,
                [np.eye(64, dtype=bool)],
                config,
                kernels,
                v1=self.v1,
            )

        path_mask = np.ones((9, 9), dtype=bool)
        path_hole = np.zeros(path_mask.shape, dtype=bool)
        path_hole[4, 4] = True
        forbidden = np.zeros(path_mask.shape, dtype=bool)
        forbidden[1:4, 4] = True
        path = generator._minimum_cost_path_to_boundary(
            path_hole,
            path_mask,
            np.zeros(path_mask.shape, dtype=np.int64),
            generator.Q12,
            forbidden=forbidden,
        )
        self.assertFalse(any(forbidden[y, x] for y, x in path))
        wall = np.zeros(path_mask.shape, dtype=bool)
        wall[3:6, 3:6] = True
        wall[4, 4] = False
        with self.assertRaisesRegex(generator.DerivationError, "cannot reach"):
            generator._minimum_cost_path_to_boundary(
                path_hole,
                path_mask,
                np.zeros(path_mask.shape, dtype=np.int64),
                generator.Q12,
                forbidden=wall,
            )
        config = self.repair_config()
        config["maximum_repairs_per_stage_per_body"] = 0
        with self.assertRaisesRegex(generator.DerivationError, "did not converge"):
            generator.repair_final_rgb_topology(
                candidate,
                foundation,
                [body],
                body,
                [np.zeros(body.shape, dtype=bool)],
                config,
                kernels,
                v1=self.v1,
            )

    def test_v1_finalization_preserves_all_locks_and_outside_foundation(self) -> None:
        shape = (30, 40)
        foundation = np.full((*shape, 3), 31, dtype=np.uint8)
        baseline = foundation.copy()
        baseline[5:25, 5:35] = 47
        candidate = np.full((*shape, 3), 211, dtype=np.uint8)
        masks = []
        for index in range(8):
            mask = np.zeros(shape, dtype=bool)
            row = 6 + (index // 4) * 10
            column = 6 + (index % 4) * 8
            mask[row : row + 3, column : column + 3] = True
            masks.append(mask)
        union = np.logical_or.reduce(masks)
        permission = np.ones(shape, dtype=bool)
        protected = np.zeros(shape, dtype=bool)
        road = np.zeros(shape, dtype=bool)
        alpha = np.zeros(shape, dtype=bool)
        permission[6, 6] = False
        protected[6, 14] = True
        road[6, 22] = True
        alpha[6, 30] = True
        locked = ~permission | protected | road | alpha
        baseline[~union] = foundation[~union]
        output = self.v1.finalize_candidate_rgb(
            candidate,
            foundation,
            baseline,
            permission,
            protected,
            road,
            alpha,
            masks,
        )
        self.assertTrue(np.array_equal(output[~union], foundation[~union]))
        self.assertTrue(np.array_equal(output[locked], baseline[locked]))
        self.assertTrue(np.all(output[union & ~locked] == 211))

    def test_body8_uses_equal_body_aggregate_and_no_eighth_statistic(self) -> None:
        records = []
        for index in range(7):
            records.append(
                self.v1.BodyStatistics(
                    median_lab_q16=np.asarray(
                        [index, index + 10, index + 20], dtype=np.int64
                    ),
                    radial_power_q16=np.full(16, index + 1, dtype=np.int64),
                    quantiles_q16=np.full(17, (index + 1) * 7, dtype=np.int64),
                )
            )
        aggregate = self.v1.aggregate_body_statistics(records)
        self.assertEqual(aggregate.median_lab_q16.tolist(), [3, 13, 23])
        self.assertEqual(aggregate.radial_power_q16.tolist(), [4] * 16)
        self.assertEqual(aggregate.quantiles_q16.tolist(), [28] * 17)
        with self.assertRaises(self.v1.DerivationError):
            self.v1.aggregate_body_statistics(records + [records[0]])

    def test_source_hash_closure_rejects_unbound_or_changed_bytes(self) -> None:
        authority = copy.deepcopy(self.authority)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, record in enumerate(
                authority["input_policy"]["source_bindings"]
            ):
                relative = f"bound/source-{index}.txt"
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                payload = f"source-{index}\n".encode()
                path.write_bytes(payload)
                record["path"] = relative
                record["sha256"] = hashlib.sha256(payload).hexdigest()
            authority["canonical_self_sha256"] = generator.authority_self_hash(
                authority
            )
            generator.check_bound_sources(authority, root=root, require_tracked=False)
            changed_path = (
                root / authority["input_policy"]["source_bindings"][0]["path"]
            )
            changed_path.write_bytes(b"changed\n")
            with self.assertRaisesRegex(generator.DerivationError, "SHA-256"):
                generator.check_bound_sources(
                    authority, root=root, require_tracked=False
                )

    def test_forbidden_import_read_and_cli_override_closure(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        forbidden_modules = {
            "audit_style_candidate_k3_golden_v3",
            "golden_v3_strict_metric_core",
            "audit_style_candidate_k3_golden_v2",
        }
        self.assertTrue(imports.isdisjoint(forbidden_modules))
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("HoughLinesP", called_attributes)
        self.assertNotIn("GaussianBlur", called_attributes)
        self.assertNotIn("measurement-inside.png", source)
        self.assertNotIn("texture-reference.png", source)
        self.assertNotIn("qa/automated", source)
        self.assertNotIn("DEVELOPMENT-STATUS.md", source)
        parser = generator.build_parser()
        self.assertEqual(
            {action.dest for action in parser._actions},
            {
                "help",
                "validate_only",
                "preflight",
                "emit",
                "compare_seals",
            },
        )
        with (
            mock.patch.object(generator, "load_authority", return_value=self.authority),
            mock.patch.object(generator, "validate_only") as validate,
            mock.patch.object(
                generator,
                "preflight",
                side_effect=AssertionError("validate-only must not preflight"),
            ),
            mock.patch.object(
                generator,
                "build_payloads",
                side_effect=AssertionError("validate-only must not build"),
            ),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            self.assertEqual(generator.main([]), 0)
            validate.assert_called_once_with(self.authority)

    def test_preflight_snapshots_only_the_v1_emit_allowlist(self) -> None:
        allowed = [
            "strict-audit-authority-reference-only",
            "v18-byte-authority",
            "v19-body-control",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bindings = []
            original: dict[str, bytes] = {}
            for index, role in enumerate(allowed):
                relative = f"inputs/source-{index}.bin"
                payload = f"immutable-{role}".encode()
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
                original[role] = payload
                bindings.append(
                    {
                        "role": role,
                        "path": relative,
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "use": "synthetic snapshot",
                    }
                )
            synthetic = {
                "input_policy": {
                    "candidate_generator_read_allowlist_roles": allowed,
                    "source_bindings": bindings,
                }
            }
            snapshot = generator.snapshot_v1_emit_inputs(
                synthetic, root=root, require_tracked=False
            )
            self.assertEqual(
                [role for role, _, _ in snapshot.records],
                allowed[1:],
            )
            for record in bindings:
                (root / record["path"]).write_bytes(b"mutated after preflight")
                if record["role"] in generator.V1_EMIT_REFERENCE_ONLY_ROLES:
                    with self.assertRaisesRegex(generator.DerivationError, "absent"):
                        snapshot.payload(record["role"])
                else:
                    self.assertEqual(
                        snapshot.payload(record["role"]), original[record["role"]]
                    )

        sentinel_snapshot = generator.BoundInputSnapshot(())
        sentinel_context = (self.v1, {"sentinel": True})
        with (
            mock.patch.object(
                generator, "_validated_v1_context", return_value=sentinel_context
            ) as context_call,
            mock.patch.object(
                generator,
                "snapshot_v1_emit_inputs",
                return_value=sentinel_snapshot,
            ) as snapshot_call,
        ):
            observed = generator.preflight(self.authority)
        self.assertEqual(observed, (*sentinel_context, sentinel_snapshot))
        context_call.assert_called_once_with(self.authority)
        snapshot_call.assert_called_once_with(sentinel_context[1])

        self.assertNotIn(
            "strict-audit-authority-reference-only", generator.TEXT_ONLY_ROLES
        )
        with (
            mock.patch.object(generator, "check_bound_sources") as check,
            mock.patch.object(generator, "load_v1_helper", return_value=self.v1),
            mock.patch.object(generator, "load_v1_authority", return_value={}),
        ):
            generator._validated_v1_context(self.authority)
        check.assert_called_once_with(self.authority, roles=generator.TEXT_ONLY_ROLES)

        prepare = next(
            node
            for node in ast.walk(ast.parse(MODULE_PATH.read_text(encoding="utf-8")))
            if isinstance(node, ast.FunctionDef) and node.name == "_prepare_bodies"
        )
        prepare_attributes = {
            node.func.attr
            for node in ast.walk(prepare)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertTrue(
            prepare_attributes.isdisjoint(
                {
                    "read_bytes",
                    "read_text",
                    "_decode_bound_rgb",
                    "_decode_bound_gray",
                    "_decode_bound_mask",
                    "_load_bound_json",
                    "_import_bound_module",
                }
            )
        )

        v1_authority = self.v1.load_authority()
        emit_roles = (
            set(
                v1_authority["input_policy"]["candidate_generator_read_allowlist_roles"]
            )
            - generator.V1_EMIT_REFERENCE_ONLY_ROLES
        )
        paths = {
            record["path"]
            for record in v1_authority["input_policy"]["source_bindings"]
            if record["role"] in emit_roles
        }
        self.assertFalse(
            any(path.startswith("world/map-production/candidates/") for path in paths)
        )
        forbidden_fragments = (
            "strict-audit",
            "strict_metric_core",
            "audit_style_candidate",
            "measurement-inside",
            "texture-reference",
            "rejection-audit",
            "DEVELOPMENT-STATUS",
            "tmp/",
        )
        self.assertFalse(
            any(fragment in path for path in paths for fragment in forbidden_fragments)
        )

    def test_exclusive_publication_and_cross_profile_seal_comparison(self) -> None:
        authority = copy.deepcopy(self.authority)
        required_profiles = authority["cli_contract"]["required_comparison_profile_ids"]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)

            def receipt() -> generator.ConstructionReceipt:
                certificate = generator.LagCertificate(
                    eligible_records=96,
                    maximum_numerator=0,
                    maximum_variance_product=1,
                    maximum_correlation_q20=0,
                )
                return generator.ConstructionReceipt(
                    amplitude_matching_iterations=4,
                    amplitude_certificate=certificate,
                    unit_certificate=certificate,
                    quiet_clipped_pixels=0,
                    short_dark_repairs=0,
                    short_dark_pixels=0,
                    topology_repairs=0,
                    topology_pixels=0,
                )

            def candidate_payloads(
                root: Path, *, changed: bool = False
            ) -> list[generator.CandidatePayload]:
                payloads = []
                for index, record in enumerate(authority["candidates"]["records"]):
                    payload = f"synthetic-png-{index}".encode()
                    if changed and index == 3:
                        payload += b"-changed"
                    payloads.append(
                        generator.CandidatePayload(
                            path=root / record["output_path"],
                            payload=payload,
                            receipt=receipt(),
                        )
                    )
                return payloads

            def publish(root: Path, *, changed: bool = False) -> Path:
                return generator.publish_payloads_exclusive(
                    authority,
                    candidate_payloads(root, changed=changed),
                    root=root,
                )

            actual_left = publish(base / "actual-left")
            actual_right = publish(base / "actual-right")
            actual_seal = generator._load_output_seal(actual_left, authority)
            self.assertEqual(
                actual_seal["runtime_attestation"],
                generator.obtain_runtime_attestation(authority),
            )
            with self.assertRaisesRegex(generator.DerivationError, "two required"):
                generator.compare_profile_seals(authority, actual_left, actual_right)
            with self.assertRaises(TypeError):
                generator.publish_payloads_exclusive(
                    authority,
                    candidate_payloads(base / "mislabeled"),
                    root=base / "mislabeled",
                    runtime_profile_id=required_profiles[1],
                )
            with self.assertRaisesRegex(generator.DerivationError, "reservation"):
                publish(base / "actual-left")

            def synthetic_seal(
                root: Path, profile_id: str, *, changed: bool = False
            ) -> Path:
                records = []
                for index, (record, item) in enumerate(
                    zip(
                        authority["candidates"]["records"],
                        candidate_payloads(root, changed=changed),
                        strict=True,
                    )
                ):
                    records.append(
                        {
                            "candidate_id": record["candidate_id"],
                            "path": record["output_path"],
                            "sha256": hashlib.sha256(item.payload).hexdigest(),
                            "bytes": len(item.payload),
                            "construction_receipt": generator.construction_receipt_json(
                                item.receipt
                            ),
                        }
                    )
                seal = {
                    "schema_id": "sstory.k3.golden-v3.balanced-open-phase-v3-output-seal.v1",
                    "authority_self_sha256": authority["canonical_self_sha256"],
                    "statistics_firewall_sha256": generator.source_bindings(authority)[
                        "sealed-v19-statistics-firewall"
                    ]["sha256"],
                    "runtime_attestation": generator.expected_runtime_attestation(
                        authority, profile_id
                    ),
                    "candidate_count": 4,
                    "candidates": records,
                }
                payload = generator.canonical_output_seal_json(seal)
                generator.validate_output_seal_payload(payload, authority)
                path = root / authority["cli_contract"]["seal_path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
                return path

            left = synthetic_seal(base / "synthetic-left", required_profiles[0])
            right = synthetic_seal(base / "synthetic-right", required_profiles[1])
            self.assertEqual(
                generator.compare_profile_seals(authority, left, right),
                tuple(required_profiles),
            )
            changed = synthetic_seal(
                base / "synthetic-changed", required_profiles[1], changed=True
            )
            with self.assertRaisesRegex(generator.DerivationError, "hashes/bytes"):
                generator.compare_profile_seals(authority, left, changed)
            with self.assertRaisesRegex(generator.DerivationError, "two required"):
                generator.compare_profile_seals(authority, left, left)
            invalid_payload = json.loads(right.read_text(encoding="utf-8"))
            invalid_payload["runtime_attestation"]["common"]["opencv_threads"] = True
            with self.assertRaisesRegex(generator.DerivationError, "attestation"):
                generator.validate_output_seal_payload(
                    generator.canonical_output_seal_json(invalid_payload), authority
                )
            for label, mutate, message in (
                (
                    "float seal count",
                    lambda value: value.__setitem__("candidate_count", 4.0),
                    "candidate count",
                ),
                (
                    "float matching iterations",
                    lambda value: value["candidates"][0][
                        "construction_receipt"
                    ].__setitem__("amplitude_matching_iterations", 4.0),
                    "iteration receipt",
                ),
                (
                    "true certificate numerator",
                    lambda value: value["candidates"][0]["construction_receipt"][
                        "amplitude_lag_certificate"
                    ].__setitem__("maximum_numerator", True),
                    "certificate value",
                ),
                (
                    "false receipt count",
                    lambda value: value["candidates"][0][
                        "construction_receipt"
                    ].__setitem__("quiet_clipped_pixels", False),
                    "receipt count",
                ),
            ):
                with self.subTest(label=label):
                    invalid = json.loads(right.read_text(encoding="utf-8"))
                    mutate(invalid)
                    with self.assertRaisesRegex(generator.DerivationError, message):
                        generator.validate_output_seal_payload(
                            generator.canonical_output_seal_json(invalid), authority
                        )
            forged = json.loads(right.read_text(encoding="utf-8"))
            forged_certificate = forged["candidates"][0]["construction_receipt"][
                "amplitude_lag_certificate"
            ]
            forged_certificate["maximum_numerator"] = 1
            forged_certificate["maximum_variance_product"] = 1
            forged_certificate["maximum_correlation_q20"] = 0
            with self.assertRaisesRegex(generator.DerivationError, "certificate ratio"):
                generator.validate_output_seal_payload(
                    generator.canonical_output_seal_json(forged), authority
                )
            nonseal = base / "not-a-seal.png"
            nonseal.write_bytes(b"synthetic bytes that must not be opened")
            with self.assertRaisesRegex(
                generator.DerivationError, "fixed manifest filename"
            ):
                generator.compare_profile_seals(authority, nonseal, right)

            real_write = generator._write_exclusive_file
            for failure_call in (3, 5):
                with self.subTest(failure_call=failure_call):
                    failure_root = base / f"failure-{failure_call}"
                    calls = 0

                    def fail_during_stage(path: Path, payload: bytes) -> None:
                        nonlocal calls
                        calls += 1
                        if calls == failure_call:
                            raise OSError("synthetic staged write failure")
                        real_write(path, payload)

                    with (
                        mock.patch.object(
                            generator,
                            "_write_exclusive_file",
                            side_effect=fail_during_stage,
                        ),
                        self.assertRaisesRegex(
                            generator.DerivationError, "staged publication"
                        ),
                    ):
                        publish(failure_root)
                    output = (
                        failure_root / authority["cli_contract"]["output_directory"]
                    )
                    staging = (
                        failure_root / authority["cli_contract"]["staging_directory"]
                    )
                    self.assertFalse(output.exists())
                    self.assertFalse(staging.exists())

            def assert_staging_tamper_rejected(
                label: str,
                tamper: object,
                message: str,
            ) -> None:
                tamper_root = base / f"tamper-{label}"
                calls = 0

                def write_then_tamper(path: Path, payload: bytes) -> None:
                    nonlocal calls
                    real_write(path, payload)
                    calls += 1
                    if calls == 5:
                        tamper(path.parent)

                with (
                    mock.patch.object(
                        generator,
                        "_write_exclusive_file",
                        side_effect=write_then_tamper,
                    ),
                    self.assertRaisesRegex(generator.DerivationError, message),
                ):
                    publish(tamper_root)
                output = tamper_root / authority["cli_contract"]["output_directory"]
                staging = tamper_root / authority["cli_contract"]["staging_directory"]
                self.assertFalse(output.exists())
                self.assertFalse(staging.exists())

            assert_staging_tamper_rejected(
                "extra",
                lambda staging: (staging / "extra.bin").write_bytes(b"extra"),
                "staging file closure",
            )

            def swap_payload(staging: Path) -> None:
                names = [
                    Path(record["output_path"]).name
                    for record in authority["candidates"]["records"][:2]
                ]
                first = staging / names[0]
                second = staging / names[1]
                first_bytes = first.read_bytes()
                second_bytes = second.read_bytes()
                first.write_bytes(second_bytes)
                second.write_bytes(first_bytes)

            assert_staging_tamper_rejected(
                "swapped-payloads", swap_payload, "staged candidate bytes changed"
            )

            external_file = base / "external-link-target.bin"
            external_file.write_bytes(b"external")
            probe_link = base / "link-probe"
            symlink_supported = False
            try:
                probe_link.symlink_to(external_file)
                symlink_supported = probe_link.is_symlink()
            except OSError:
                pass
            finally:
                if probe_link.is_symlink():
                    probe_link.unlink()
            if symlink_supported:

                def replace_with_link(staging: Path) -> None:
                    name = Path(
                        authority["candidates"]["records"][0]["output_path"]
                    ).name
                    staged = staging / name
                    staged.unlink()
                    staged.symlink_to(external_file)

                assert_staging_tamper_rejected(
                    "link-file", replace_with_link, "link or junction"
                )

            def assert_external_ancestor_rejected(kind: str) -> bool:
                ancestor_root = base / f"ancestor-{kind}"
                external = base / f"external-{kind}"
                ancestor_root.mkdir()
                external.mkdir()
                linked = ancestor_root / "tmp"
                if kind == "symlink":
                    linked.symlink_to(external, target_is_directory=True)
                else:
                    completed = subprocess.run(
                        [
                            "cmd.exe",
                            "/d",
                            "/c",
                            "mklink",
                            "/J",
                            str(linked),
                            str(external),
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    if completed.returncode != 0:
                        return False
                try:
                    with self.assertRaisesRegex(
                        generator.DerivationError, "link or junction ancestor"
                    ):
                        publish(ancestor_root)
                finally:
                    if linked.is_symlink():
                        linked.unlink()
                    elif hasattr(linked, "is_junction") and linked.is_junction():
                        linked.rmdir()
                return True

            if symlink_supported:
                with self.subTest(kind="external ancestor symlink"):
                    assert_external_ancestor_rejected("symlink")
            if os.name == "nt":
                with self.subTest(kind="external ancestor junction"):
                    assert_external_ancestor_rejected("junction")

            race_root = base / "rename-race"
            real_rename = generator._rename_directory_noreplace

            def reserve_target_before_rename(source: Path, target: Path) -> None:
                target.mkdir()
                real_rename(source, target)

            with (
                mock.patch.object(
                    generator,
                    "_rename_directory_noreplace",
                    side_effect=reserve_target_before_rename,
                ),
                self.assertRaisesRegex(generator.DerivationError, "staged publication"),
            ):
                publish(race_root)
            race_output = race_root / authority["cli_contract"]["output_directory"]
            race_staging = race_root / authority["cli_contract"]["staging_directory"]
            self.assertTrue(race_output.is_dir())
            self.assertEqual(list(race_output.iterdir()), [])
            self.assertFalse(race_staging.exists())


if __name__ == "__main__":
    unittest.main()
