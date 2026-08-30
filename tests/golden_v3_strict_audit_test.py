from __future__ import annotations

import hashlib
import io
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "map-production"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import audit_style_candidate_k3_golden_v3 as audit  # noqa: E402
import generate_golden_v3_strict_alpha_zero as alpha_generator  # noqa: E402
import golden_v3_strict_metric_core as core  # noqa: E402


AUTHORITY_PATH = (
    ROOT
    / "world"
    / "map-production"
    / "spec"
    / "style-candidate-k3-golden-v3-strict-audit-authority.json"
)


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type)
    crc = zlib.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def _synthetic_rgb_png(
    *,
    bit_depth: int = 8,
    ancillary: tuple[tuple[bytes, bytes], ...] = (),
) -> bytes:
    width, height = 2, 1
    ihdr = struct.pack(">IIBBBBB", width, height, bit_depth, 2, 0, 0, 0)
    if bit_depth == 8:
        samples = bytes((10, 20, 30, 40, 50, 60))
    elif bit_depth == 16:
        samples = struct.pack(">6H", 10 << 8, 20 << 8, 30 << 8, 40 << 8, 50 << 8, 60 << 8)
    else:
        raise AssertionError("synthetic fixture supports only 8/16-bit truecolor")
    chunks = [_png_chunk(b"IHDR", ihdr)]
    chunks.extend(_png_chunk(name, data) for name, data in ancillary)
    chunks.extend(
        (
            _png_chunk(b"IDAT", zlib.compress(b"\x00" + samples)),
            _png_chunk(b"IEND", b""),
        )
    )
    return audit.PNG_SIGNATURE + b"".join(chunks)


class GoldenV3StrictAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.authority = json.loads(AUTHORITY_PATH.read_text(encoding="utf-8"))
        cls.kernels = core.load_kernels(cls.authority)

    def test_authority_is_candidate_unbound_and_hash_locked(self) -> None:
        loaded, digest = audit.load_authority(ROOT)
        self.assertIsNone(loaded["candidate_binding"])
        self.assertEqual(loaded["candidate_evaluations_before_freeze"], 0)
        self.assertFalse(loaded["threshold_selection_from_candidate_values"])
        self.assertEqual(digest, audit.EXPECTED_AUTHORITY_SHA256)
        core_path, core_payload = audit._bind_record(
            ROOT, loaded["strict_core_binding"], label="strict integer core"
        )
        self.assertEqual(core_path, Path(core.__file__).resolve())
        self.assertEqual(hashlib.sha256(core_payload).hexdigest(), loaded["strict_core_binding"]["sha256"])
        for name, record in loaded["runtime_bindings"].items():
            audit._bind_record(ROOT, record, label=f"runtime {name}")
        core.validate_authority_contract(loaded)
        audit._runtime_gate(loaded)

    def test_runtime_profiles_cover_local_and_both_ci_operating_systems(self) -> None:
        selected = audit._runtime_gate(self.authority)
        profiles = self.authority["runtime"]["allowed_profiles"]
        self.assertIn(selected, {profile["id"] for profile in profiles})
        self.assertEqual(
            {profile["platform_system"] for profile in profiles},
            {"Windows", "Linux"},
        )
        self.assertEqual(self.authority["runtime"]["common"]["python_version"], "3.12.10")
        self.assertEqual(
            {
                record["version"]
                for profile in profiles
                for record in profile["opencv_distributions"]
            },
            {"4.13.0.92"},
        )
        drifted = json.loads(json.dumps(self.authority))
        drifted["runtime"]["common"]["python_version"] = "3.12.9"
        with self.assertRaises(audit.GoldenV3StrictAuditError):
            audit._runtime_gate(drifted)

    def test_v2_shared_values_have_cross_platform_synthetic_golden_vector(self) -> None:
        height, width = 256, 384
        yy, xx = np.mgrid[:height, :width]
        cell_x = xx // 16
        cell_y = yy // 16
        amplitude = (7 * cell_x + 11 * cell_y) % 16
        sign = np.where(((xx // 4 + yy // 4) % 2) == 0, -1, 1)
        coverage_gray = np.clip(128 + amplitude * sign, 0, 255).astype(np.uint8)
        coverage_rgb = np.repeat(coverage_gray[..., None], 3, axis=2)

        pattern = ((3 * xx + 5 * yy + (xx * yy) % 7) % 7) - 3
        candidate_gray = (128 + pattern).astype(np.uint8)
        baseline_gray = (128 + 2 * pattern).astype(np.uint8)
        candidate = np.repeat(candidate_gray[..., None], 3, axis=2)
        baseline = np.repeat(baseline_gray[..., None], 3, axis=2)
        measurement = np.zeros((height, width), dtype=bool)
        measurement[16:-16, 16:-16] = True
        reference = np.ones((height, width), dtype=bool)

        self.assertEqual(audit.v2._coverage(coverage_rgb), (216, 78))
        self.assertEqual(audit.v2._quiet_fraction(candidate, measurement), 1.0)
        self.assertEqual(audit.v2._dash_bundle_pairs(candidate, measurement), 0)
        self.assertEqual(audit.v2._orientation_coherence(candidate, measurement), 0.0)
        self.assertEqual(
            audit.v2._texture_ratios(candidate, baseline, measurement, reference),
            {"4": 0.500962, "8": 0.500861},
        )

    def test_imported_module_path_mismatch_fails_closed(self) -> None:
        audit._require_imported_source(
            core, Path(core.__file__).resolve(), label="synthetic matching module"
        )
        fake_module = type("FakeModule", (), {"__file__": str(ROOT / "not-bound.py")})()
        with self.assertRaises(audit.GoldenV3StrictAuditError):
            audit._require_imported_source(
                fake_module,
                Path(core.__file__).resolve(),
                label="synthetic mismatched module",
            )

    def test_numeric_contract_drift_fails_closed(self) -> None:
        drifted = json.loads(json.dumps(self.authority))
        drifted["signal_definition"]["fixed_point_q_bits"] += 1
        with self.assertRaises(core.StrictMetricError):
            core.validate_authority_contract(drifted)
        drifted = json.loads(json.dumps(self.authority))
        drifted["luma"]["coefficients_sum"] -= 1
        with self.assertRaises(core.StrictMetricError):
            core.validate_authority_contract(drifted)

    def test_q30_kernels_are_symmetric_unit_sum_and_preserve_constant(self) -> None:
        mask = np.ones((19, 23), dtype=bool)
        constant = np.full(mask.shape, 7 * core.Q_SIGNAL, dtype=np.int64)
        for sigma, kernel in self.kernels.items():
            self.assertEqual(kernel.radius_px, sigma * 4)
            self.assertEqual(sum(kernel.coefficients_q30), core.Q_KERNEL)
            self.assertEqual(kernel.coefficients_q30, kernel.coefficients_q30[::-1])
            observed = core.masked_gaussian_q30(constant, mask, kernel)
            np.testing.assert_array_equal(observed, constant)

    def test_partial_mask_normalization_preserves_constant_at_body_boundary(self) -> None:
        mask = np.zeros((67, 71), dtype=bool)
        mask[11:55, 17:59] = True
        values = np.zeros(mask.shape, dtype=np.int64)
        values[mask] = 9 * core.Q_SIGNAL
        for kernel in self.kernels.values():
            observed = core.masked_gaussian_q30(values, mask, kernel)
            self.assertTrue(np.all(observed[~mask] == 0))
            self.assertLessEqual(
                int(np.max(np.abs(observed[mask] - 9 * core.Q_SIGNAL))), 1
            )

    def test_int64_minimum_and_bad_dependency_hash_fail_closed(self) -> None:
        with self.assertRaises(core.StrictMetricError):
            core._round_divide_array(np.asarray([core.INT64_MIN], dtype=np.int64), 2)
        with self.assertRaises(core.StrictMetricError):
            core._round_divide_array(np.asarray([core.INT64_MAX], dtype=np.int64), 2)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            artifact = root / "artifact.bin"
            artifact.write_bytes(b"synthetic-only")
            with self.assertRaises(audit.GoldenV3StrictAuditError):
                audit._bind_record(
                    root,
                    {"path": "artifact.bin", "sha256": "0" * 64},
                    label="synthetic bad binding",
                )

    def test_cli_returns_rejection_and_exclusively_preserves_evidence(self) -> None:
        synthetic_report = {"passed": False, "fixture": "synthetic-no-candidate-read"}
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            output = Path(temporary) / "strict-report.json"
            arguments = [
                "audit_style_candidate_k3_golden_v3.py",
                "--candidate",
                "synthetic-path-never-read.png",
                "--output",
                str(output),
            ]
            with (
                mock.patch.object(sys, "argv", arguments),
                mock.patch.object(audit, "audit_candidate", return_value=synthetic_report),
            ):
                self.assertEqual(audit.main(), 1)
            frozen = output.read_bytes()
            with (
                mock.patch.object(sys, "argv", arguments),
                mock.patch.object(audit, "audit_candidate", return_value={"passed": True}),
                self.assertRaises(SystemExit) as stopped,
            ):
                audit.main()
            self.assertEqual(stopped.exception.code, 2)
            self.assertEqual(output.read_bytes(), frozen)

    def test_candidate_png_structure_rejects_16bit_apng_and_color_metadata(self) -> None:
        accepted = _synthetic_rgb_png()
        decoded = audit._decode_rgb(
            accepted,
            size=(2, 1),
            label="synthetic 8-bit candidate",
            strict_candidate=True,
        )
        self.assertEqual(decoded.shape, (1, 2, 3))

        with self.assertRaisesRegex(audit.GoldenV3StrictAuditError, "8-bit truecolor"):
            audit._decode_rgb(
                _synthetic_rgb_png(bit_depth=16),
                size=(2, 1),
                label="synthetic 16-bit candidate",
                strict_candidate=True,
            )

        first = Image.new("RGB", (2, 1), (10, 20, 30))
        second = Image.new("RGB", (2, 1), (40, 50, 60))
        apng_buffer = io.BytesIO()
        first.save(
            apng_buffer,
            format="PNG",
            save_all=True,
            append_images=[second],
            duration=100,
            loop=0,
        )
        apng = apng_buffer.getvalue()
        self.assertIn(b"acTL", apng)
        with self.assertRaisesRegex(audit.GoldenV3StrictAuditError, "acTL"):
            audit._decode_rgb(
                apng,
                size=(2, 1),
                label="synthetic two-frame APNG",
                strict_candidate=True,
            )

        metadata_chunks = {
            b"gAMA": struct.pack(">I", 45_455),
            b"iCCP": b"profile\x00\x00synthetic",
            b"sRGB": b"\x00",
            b"cHRM": b"\x00" * 32,
            b"eXIf": b"synthetic-exif",
        }
        for name, data in metadata_chunks.items():
            with self.subTest(chunk=name.decode("ascii")):
                with self.assertRaisesRegex(
                    audit.GoldenV3StrictAuditError,
                    name.decode("ascii"),
                ):
                    audit._decode_rgb(
                        _synthetic_rgb_png(ancillary=((name, data),)),
                        size=(2, 1),
                        label="synthetic metadata candidate",
                        strict_candidate=True,
                    )

    def test_kernel_impulse_is_deterministic_and_reflects_at_border(self) -> None:
        impulse = np.zeros((17, 21), dtype=np.int64)
        impulse[0, 0] = core.Q_SIGNAL
        first = core.gaussian_q30(impulse, self.kernels[2])
        second = core.gaussian_q30(impulse, self.kernels[2])
        np.testing.assert_array_equal(first, second)
        self.assertGreater(int(first[0, 0]), int(first[-1, -1]))

    def test_A_unit_total_derivation_is_repeatable_on_synthetic_signal(self) -> None:
        yy, xx = np.mgrid[:96, :96]
        delta = (((7 * xx + 11 * yy) % 31) - 15).astype(np.int16)
        body = np.zeros(delta.shape, dtype=bool)
        body[2:-2, 2:-2] = True
        first = core.derive_body_fields(delta, body, self.kernels)
        second = core.derive_body_fields(delta, body, self.kernels)
        for name in ("A", "unit", "total"):
            np.testing.assert_array_equal(first[name], second[name])
        unit_energy = core.sum_squares(first["unit"], body)
        unit_rms = (unit_energy / int(np.count_nonzero(body))) ** 0.5
        self.assertLessEqual(abs(unit_rms - core.Q_SIGNAL), 2.0)

    def test_total_repetition_requires_four_lags_and_pools_same_body_pairs(self) -> None:
        shape = (8, 16)
        left = np.zeros(shape, dtype=bool)
        right = np.zeros(shape, dtype=bool)
        left[:, :8] = True
        right[:, 8:] = True
        pattern = np.arange(shape[0] * shape[1], dtype=np.int64).reshape(shape)

        def synthetic_fields(
            _delta: np.ndarray,
            body: np.ndarray,
            _kernels: object,
        ) -> dict[str, np.ndarray]:
            values = np.where(body, pattern * core.Q_SIGNAL, 0)
            return {name: values.copy() for name in ("A", "unit", "total")}

        contract = json.loads(json.dumps(self.authority["strict_field_contract"]))
        contract["body_core_erosion_px"] = 0
        contract["minimum_body_core_pixels"] = 1
        contract["repetition"]["lags_xy"] = [[1, 0], [2, 0], [3, 0], [4, 0]]
        contract["repetition"]["minimum_pairs_per_lag"] = 50
        contract["repetition"]["minimum_eligible_lags_per_body"] = 1
        contract["repetition"]["minimum_eligible_lags_total"] = 4
        fixed_pearson = {
            "pairs": 50,
            "covariance_numerator": 1,
            "variance_product": 400,
        }
        with (
            mock.patch.object(core, "derive_body_fields", side_effect=synthetic_fields),
            mock.patch.object(core, "highpass_q", side_effect=lambda values, _body, _kernel: values.copy()),
            mock.patch.object(core, "pearson_integer", return_value=fixed_pearson),
        ):
            with self.assertRaisesRegex(core.StrictMetricError, "too few eligible lags"):
                core.measure_strict_fields(
                    np.zeros(shape, dtype=np.int16),
                    [left, right],
                    self.kernels,
                    contract,
                )
            contract["repetition"]["minimum_eligible_lags_total"] = 1
            measured, _, _ = core.measure_strict_fields(
                np.zeros(shape, dtype=np.int16),
                [left, right],
                self.kernels,
                contract,
            )
        total = measured["repetition"]["total"]
        self.assertEqual(len(total["lags"]), 1)
        self.assertEqual(total["maximum"]["pairs"], 112)

    def test_exact_threshold_boundaries_are_not_report_rounding_dependent(self) -> None:
        self.assertTrue(core.ratio_le(42, 100, 21, 50))
        self.assertFalse(core.ratio_le(43, 100, 21, 50))
        self.assertTrue(core.energy_percent_ge(29 * 29, 10_000, 29))
        self.assertFalse(core.energy_percent_ge(29 * 29 - 1, 10_000, 29))
        self.assertTrue(core.energy_percent_ge(34 * 34, 10_000, 34))
        self.assertFalse(core.energy_percent_ge(34 * 34 - 1, 10_000, 34))
        self.assertTrue(core.correlation_le(1, 400, 1, 20))
        self.assertFalse(core.correlation_le(1, 399, 1, 20))
        self.assertTrue(core.correlation_le(7, 10_000, 7, 100))
        self.assertFalse(core.correlation_le(7, 9_999, 7, 100))

    def test_primary_gate_uses_new_strict_intervals(self) -> None:
        metrics = {
            "coverage_50": 365,
            "coverage_25": 338,
            "quiet_fraction": 0.908,
            "dash_bundle_pairs": 0,
            "orientation_coherence": 0.14,
            "texture_inside_to_outside_ratio": {"4": 0.615, "8": 1.2},
        }
        self.assertTrue(all(core.primary_gates(metrics, self.authority["primary_thresholds"]).values()))
        metrics["quiet_fraction"] = 0.926
        self.assertFalse(
            core.primary_gates(metrics, self.authority["primary_thresholds"])[
                "quiet_fraction_range_0_908_0_925"
            ]
        )

    def test_closed_loop_topology_distinguishes_ring_from_open_arc(self) -> None:
        core_mask = np.zeros((64, 64), dtype=bool)
        core_mask[4:-4, 4:-4] = True
        ring = np.zeros(core_mask.shape, dtype=np.uint8)
        cv2.circle(ring, (32, 32), 13, 1, 2, cv2.LINE_8)
        self.assertGreaterEqual(core._binary_closed_holes(ring > 0, core_mask, 4), 1)
        open_arc = ring.copy()
        open_arc[16:27, 28:37] = 0
        self.assertEqual(core._binary_closed_holes(open_arc > 0, core_mask, 4), 0)

    def test_white_crest_uses_final_relative_and_absolute_brightness(self) -> None:
        shape = (96, 96)
        body = np.ones(shape, dtype=bool)
        body[[0, -1], :] = False
        body[:, [0, -1]] = False
        strict_core = core.disk_erode(body, 12)
        foundation = np.full((*shape, 3), 200, dtype=np.uint8)
        candidate = foundation.copy()
        candidate[48, 48] = (240, 240, 240)
        delta = core.luma_u8(candidate).astype(np.int16) - core.luma_u8(foundation).astype(np.int16)
        total = np.zeros(shape, dtype=np.int64)
        total[body] = delta[body].astype(np.int64) * core.Q_SIGNAL
        detected = core.white_crest_particle_count(
            candidate,
            foundation,
            [total],
            [body],
            [strict_core],
            self.kernels[4],
            local_floor_l_q=round(4.5 * core.Q_SIGNAL),
            minimum_delta_luma=6,
            minimum_candidate_luma=224,
            maximum_rgb_range=18,
        )
        self.assertEqual(detected["count"], 1)
        unchanged = core.white_crest_particle_count(
            candidate,
            candidate,
            [np.zeros(shape, dtype=np.int64)],
            [body],
            [strict_core],
            self.kernels[4],
            local_floor_l_q=round(4.5 * core.Q_SIGNAL),
            minimum_delta_luma=6,
            minimum_candidate_luma=224,
            maximum_rgb_range=18,
        )
        self.assertEqual(unchanged["count"], 0)

    def test_each_identity_lock_detects_one_pixel(self) -> None:
        shape = (8, 8)
        baseline = np.zeros((*shape, 3), dtype=np.uint8)
        candidate = baseline.copy()
        candidate[3, 3] = (1, 0, 0)
        permission = np.ones(shape, dtype=bool)
        protected = np.zeros(shape, dtype=bool)
        road = np.zeros(shape, dtype=bool)
        alpha_zero = np.zeros(shape, dtype=bool)

        permission[3, 3] = False
        counts = core.lock_counts(
            candidate,
            baseline,
            permission=permission,
            protected=protected,
            road_calm=road,
            alpha_zero=alpha_zero,
        )
        self.assertEqual(counts["outside_permission"], 1)

        permission[3, 3] = True
        protected[3, 3] = True
        road[3, 3] = True
        alpha_zero[3, 3] = True
        counts = core.lock_counts(
            candidate,
            baseline,
            permission=permission,
            protected=protected,
            road_calm=road,
            alpha_zero=alpha_zero,
        )
        self.assertEqual(counts["protected_features"], 1)
        self.assertEqual(counts["road_calm_18px"], 1)
        self.assertEqual(counts["alpha_zero"], 1)

    def test_alpha_zero_mask_replays_from_v19_without_candidate(self) -> None:
        mask, payload = alpha_generator.build()
        tracked = alpha_generator.OUTPUT.read_bytes()
        self.assertEqual(payload, tracked)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), alpha_generator.EXPECTED_PNG_SHA256)
        self.assertEqual(int(np.count_nonzero(mask)), alpha_generator.EXPECTED_TRUE_PIXELS)
        self.assertEqual(
            hashlib.sha256(np.ascontiguousarray(mask.astype(np.uint8)).tobytes()).hexdigest(),
            alpha_generator.EXPECTED_MASK_ARRAY_SHA256,
        )
        self.assertTrue(alpha_generator.OUTPUT.is_absolute())

    def test_alpha_generator_check_only_and_mismatch_refusal(self) -> None:
        mask = np.asarray([[True, False], [False, True]], dtype=bool)
        payload = b"synthetic-alpha-zero-png-bytes"
        expected = {
            "EXPECTED_PNG_SHA256": hashlib.sha256(payload).hexdigest(),
            "EXPECTED_PNG_BYTES": len(payload),
            "EXPECTED_TRUE_PIXELS": 2,
            "EXPECTED_MASK_ARRAY_SHA256": hashlib.sha256(
                np.ascontiguousarray(mask.astype(np.uint8)).tobytes()
            ).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve() / "alpha-zero.png"
            output.write_bytes(payload)
            arguments = ["generate_golden_v3_strict_alpha_zero.py", "--check"]
            with (
                mock.patch.object(sys, "argv", arguments),
                mock.patch.object(alpha_generator, "OUTPUT", output),
                mock.patch.object(alpha_generator, "build", return_value=(mask, payload)),
                mock.patch.multiple(alpha_generator, **expected),
                mock.patch("builtins.print"),
            ):
                alpha_generator.main()
                output.write_bytes(b"different-existing-bytes")
                with self.assertRaisesRegex(RuntimeError, "differs"):
                    alpha_generator.main()


if __name__ == "__main__":
    unittest.main()
