from __future__ import annotations

import ast
import copy
import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    REPO_ROOT
    / "scripts/map-production/generate_style_candidate_k3_golden_v3_four_candidate_phase_v1.py"
)
SPEC = importlib.util.spec_from_file_location("golden_v3_four_candidate_phase_v1", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load four-candidate derivation module")
generator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generator
SPEC.loader.exec_module(generator)

EXTRACTOR_PATH = (
    REPO_ROOT
    / "scripts/map-production/extract_style_candidate_k3_golden_v3_v19_statistics.py"
)
EXTRACTOR_SPEC = importlib.util.spec_from_file_location(
    "golden_v3_v19_statistics_extractor_for_roundtrip", EXTRACTOR_PATH
)
if EXTRACTOR_SPEC is None or EXTRACTOR_SPEC.loader is None:
    raise RuntimeError("cannot load v19 statistics extractor for synthetic roundtrip")
extractor = importlib.util.module_from_spec(EXTRACTOR_SPEC)
sys.modules[EXTRACTOR_SPEC.name] = extractor
EXTRACTOR_SPEC.loader.exec_module(extractor)


class GoldenV3FourCandidatePhasePreregistrationTest(unittest.TestCase):
    """Synthetic-only tests: no production raster or candidate is opened."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.authority = generator.load_authority()

    def synthetic_statistics_record(self) -> dict[str, object]:
        support_hashes = self.authority["derivation"]["coverage_anchors"][
            "bodies_1_through_7_support_sha256_by_control_value"
        ]
        bodies: dict[str, object] = {}
        for body_value in reversed(generator.BODY_VALUES[:7]):
            bodies[str(body_value)] = {
                "quantiles_q16": [index * 31 - 248 for index in range(17)],
                "radial_power_q16": [generator.Q16] + [0] * 15,
                "median_lab_q16": [
                    (body_value // 32 + 20) * generator.Q16,
                    128 * generator.Q16,
                    127 * generator.Q16,
                ],
                "support_sha256": support_hashes[str(body_value)],
            }
        return {
            "source_hashes": dict(reversed(list(extractor.expected_source_hashes().items()))),
            "body_statistics": bodies,
            "record_id": extractor.RECORD_ID,
            "schema_id": extractor.SCHEMA_ID,
        }

    def test_authority_closes_exactly_the_four_factorial_records(self) -> None:
        records = self.authority["candidates"]["records"]
        self.assertEqual(
            [record["candidate_id"] for record in records],
            ["F094-M148", "F094-M155", "F097-M148", "F097-M155"],
        )
        self.assertEqual(
            [record["fine_retention_rational"] for record in records],
            [[47, 50], [47, 50], [97, 100], [97, 100]],
        )
        self.assertEqual(
            [record["mid_gain_rational"] for record in records],
            [[37, 25], [31, 20], [37, 25], [31, 20]],
        )
        self.assertEqual(self.authority["candidates"]["exact_count"], 4)

    def test_authority_rejects_an_extra_or_changed_candidate(self) -> None:
        extra = copy.deepcopy(self.authority)
        extra["candidates"]["records"].append(copy.deepcopy(extra["candidates"]["records"][0]))
        with self.assertRaises(generator.DerivationError):
            generator.validate_authority(extra)
        changed = copy.deepcopy(self.authority)
        changed["candidates"]["records"][0]["mid_gain_rational"] = [3, 2]
        with self.assertRaises(generator.DerivationError):
            generator.validate_authority(changed)

    def test_statistics_firewall_authority_is_sealed_and_source_bound(self) -> None:
        config = self.authority["derivation"]["v19_statistical_authority"]
        self.assertEqual(config["firewall_status"], "sealed-canonical-statistics-authority")
        self.assertEqual(config["future_artifact_path"], generator.STATISTICS_FIREWALL_PATH)
        self.assertEqual(
            config["future_artifact_sha256"], generator.STATISTICS_FIREWALL_SHA256
        )
        policy = self.authority["input_policy"]
        self.assertEqual(policy["exact_source_binding_count"], 28)
        self.assertEqual(len(policy["source_bindings"]), 28)
        binding = generator.source_bindings(self.authority)[
            "sealed-v19-statistics-firewall"
        ]
        self.assertEqual(binding["path"], generator.STATISTICS_FIREWALL_PATH)
        self.assertEqual(binding["sha256"], generator.STATISTICS_FIREWALL_SHA256)

    def test_sealed_loader_accepts_only_sha_bound_synthetic_canonical_bytes(self) -> None:
        payload = extractor.canonical_statistics_json(self.synthetic_statistics_record())
        digest = generator.sha256_bytes(payload)
        authority = copy.deepcopy(self.authority)
        relative = "synthetic/v19-statistics-firewall.json"
        config = authority["derivation"]["v19_statistical_authority"]
        config["future_artifact_path"] = relative
        config["future_artifact_sha256"] = digest
        binding = generator.source_bindings(authority)[
            "sealed-v19-statistics-firewall"
        ]
        binding["path"] = relative
        binding["sha256"] = digest
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / relative
            path.parent.mkdir(parents=True)
            path.write_bytes(payload)
            with (
                mock.patch.object(generator, "ROOT", root),
                mock.patch.object(generator, "STATISTICS_FIREWALL_PATH", relative),
                mock.patch.object(generator, "STATISTICS_FIREWALL_SHA256", digest),
            ):
                records = generator.load_statistics_firewall(authority)
                path.write_bytes(payload + b" ")
                with self.assertRaisesRegex(generator.DerivationError, "SHA-256 changed"):
                    generator.load_statistics_firewall(authority)
        self.assertEqual(len(records), 7)

    def test_sealed_emit_dispatch_checks_firewall_without_raster_decode(self) -> None:
        profile = self.authority["runtime"]["allowed_profiles"][0]["id"]
        with (
            mock.patch.object(generator, "_runtime_gate", return_value=profile),
            mock.patch.object(generator, "check_bound_sources") as source_check,
            mock.patch.object(generator, "emit") as emit_mock,
            mock.patch.object(
                generator,
                "_decode_bound_rgb",
                side_effect=AssertionError("unexpected RGB decode"),
            ) as rgb,
            mock.patch.object(
                generator,
                "_decode_bound_gray",
                side_effect=AssertionError("unexpected control decode"),
            ) as gray,
            mock.patch.object(
                generator,
                "_decode_bound_mask",
                side_effect=AssertionError("unexpected mask decode"),
            ) as mask,
            mock.patch("sys.stdout", new_callable=io.StringIO),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(generator.main(["--emit"]), 0)
        source_check.assert_called_once()
        checked_roles = source_check.call_args.kwargs["roles"]
        self.assertEqual(
            checked_roles,
            set(
                self.authority["input_policy"][
                    "candidate_generator_read_allowlist_roles"
                ]
            ),
        )
        self.assertIn("sealed-v19-statistics-firewall", checked_roles)
        emit_mock.assert_called_once()
        self.assertEqual(emit_mock.call_args.args[1], profile)
        rgb.assert_not_called()
        gray.assert_not_called()
        mask.assert_not_called()

    def test_statistics_schema_is_one_dimensional_and_excludes_body_255(self) -> None:
        schema = self.authority["derivation"]["v19_statistical_authority"][
            "artifact_schema"
        ]
        self.assertEqual(
            schema["exact_top_keys"],
            ["schema_id", "record_id", "source_hashes", "body_statistics"],
        )
        self.assertEqual(
            schema["body_statistics_exact_keys"],
            ["32", "64", "96", "128", "160", "192", "224"],
        )
        self.assertNotIn("255", schema["body_statistics_exact_keys"])
        self.assertEqual(schema["radial_bin_count"], 16)
        self.assertEqual(schema["quantile_count"], 17)
        self.assertEqual(
            set(schema["source_hashes_exact_keys"]),
            {
                "v19_contour_field_array_sha256",
                "v19_final_pixel_array_sha256",
                "v19_renderer_sha256",
                "v19_replay_contract_sha256",
                "v19_statistics_extractor_sha256",
                "v19_transitive_inputs_sha256",
            },
        )

    def test_extractor_canonical_synthetic_record_roundtrips_in_body_order(self) -> None:
        record = self.synthetic_statistics_record()
        payload = extractor.canonical_statistics_json(record)
        parsed = generator.parse_statistics_firewall_payload(payload, self.authority)
        self.assertEqual(len(parsed), 7)
        self.assertEqual(
            [int(item.median_lab_q16[0]) for item in parsed],
            [
                (body_value // 32 + 20) * generator.Q16
                for body_value in generator.BODY_VALUES[:7]
            ],
        )
        self.assertEqual(payload, generator.canonical_statistics_json(record))
        self.assertEqual(
            extractor.statistics_extractor_sha256(),
            "26ea56e203ffb8b9899d8d04042bfd8e9d0e14281f2b55fe55bc99b270cca955",
        )

    def test_firewall_rejects_duplicate_keys_and_noncanonical_bytes(self) -> None:
        record = self.synthetic_statistics_record()
        payload = extractor.canonical_statistics_json(record)
        duplicate = payload.replace(
            b'"schema_id":', b'"schema_id":"duplicate","schema_id":', 1
        )
        with self.assertRaisesRegex(generator.DerivationError, "duplicate JSON key"):
            generator.parse_statistics_firewall_payload(duplicate, self.authority)
        noncanonical = (json.dumps(record, indent=2) + "\n").encode("utf-8")
        with self.assertRaisesRegex(generator.DerivationError, "extractor-canonical"):
            generator.parse_statistics_firewall_payload(noncanonical, self.authority)

    def test_firewall_rejects_bool_range_lab_psd_and_quantile_violations(self) -> None:
        mutations = {
            "non-bool": lambda body: body["median_lab_q16"].__setitem__(0, True),
            "signed Q16.16": lambda body: body["quantiles_q16"].__setitem__(
                16, generator.Q16_MAX + 1
            ),
            "encoded Lab": lambda body: body["median_lab_q16"].__setitem__(
                0, 255 * generator.Q16 + 1
            ),
            "outside [0,1]": lambda body: body["radial_power_q16"].__setitem__(
                0, generator.Q16 + 1
            ),
            "neither zero nor normalized": lambda body: body.__setitem__(
                "radial_power_q16", [1] * 16
            ),
            "not monotone": lambda body: body["quantiles_q16"].__setitem__(0, 999),
        }
        for expected_message, mutate in mutations.items():
            with self.subTest(expected_message=expected_message):
                record = self.synthetic_statistics_record()
                body = record["body_statistics"]["32"]
                mutate(body)
                payload = generator.canonical_statistics_json(record)
                with self.assertRaisesRegex(
                    generator.DerivationError, re.escape(expected_message)
                ):
                    generator.parse_statistics_firewall_payload(payload, self.authority)

    def test_firewall_source_hashes_are_six_key_authority_bound(self) -> None:
        record = self.synthetic_statistics_record()
        record["source_hashes"]["v19_statistics_extractor_sha256"] = "0" * 64
        with self.assertRaisesRegex(generator.DerivationError, "six-source identity"):
            generator.parse_statistics_firewall_payload(
                generator.canonical_statistics_json(record), self.authority
            )

    def test_integer_q30_filter_preserves_signed_constant_exactly(self) -> None:
        record = {"coefficients": [generator.Q30 // 4, generator.Q30 // 2, generator.Q30 // 4]}
        for value in (7 * generator.Q16, -9 * generator.Q16):
            source = np.full((5, 7), value, dtype=np.int64)
            self.assertTrue(np.array_equal(generator.q30_filter(source, record), source))

    def test_q30_filter_is_half_sample_symmetric_and_rounds_each_pass(self) -> None:
        record = {"coefficients": [generator.Q30 // 4, generator.Q30 // 2, generator.Q30 // 4]}
        source = np.asarray([[0, 4, 8]], dtype=np.int64) * generator.Q16
        observed = generator.q30_filter(source, record)
        expected = np.asarray([[1, 4, 7]], dtype=np.int64) * generator.Q16
        self.assertTrue(np.array_equal(observed, expected))

    def test_exact_factorial_equation_uses_rationals_and_written_order(self) -> None:
        bands = generator.PhaseBands(
            sub4=np.asarray([100, -100, 1, -1], dtype=np.int64),
            g4_to_g8=np.asarray([10, 10, 10, 10], dtype=np.int64),
            g8_to_g24=np.asarray([20, 20, 20, 20], dtype=np.int64),
        )
        coarse = np.asarray([30, 30, 30, 30], dtype=np.int64)
        observed = generator.exact_luma_equation_q16(
            1000, bands, coarse, (47, 50), (37, 25)
        )
        self.assertEqual(observed.tolist(), [1164, 976, 1071, 1069])

    def test_fixed_point_math_rejects_int64_wraparound_before_operation(self) -> None:
        with self.assertRaisesRegex(generator.DerivationError, "INT64_MIN"):
            generator.round_divide_ties_away(
                np.asarray([generator.INT64_MIN], dtype=np.int64), 1
            )
        with self.assertRaisesRegex(generator.DerivationError, "rounding bias"):
            generator.round_divide_ties_away(
                np.asarray([generator.INT64_MAX], dtype=np.int64), 3
            )
        with self.assertRaisesRegex(generator.DerivationError, "multiplication"):
            generator.rational_multiply(
                np.asarray([generator.INT64_MAX // 2 + 1], dtype=np.int64), 2, 1
            )
        record = {
            "coefficients": [
                generator.Q30 // 4,
                generator.Q30 // 2,
                generator.Q30 // 4,
            ]
        }
        with self.assertRaisesRegex(generator.DerivationError, "Q30 convolution"):
            generator.q30_filter(
                np.full(
                    (2, 2), generator.INT64_MAX // generator.Q30 + 1, dtype=np.int64
                ),
                record,
            )
        overflowing_bands = generator.PhaseBands(
            sub4=np.asarray([0], dtype=np.int64),
            g4_to_g8=np.asarray([1], dtype=np.int64),
            g8_to_g24=np.asarray([0], dtype=np.int64),
        )
        with self.assertRaisesRegex(generator.DerivationError, "overflow"):
            generator.exact_luma_equation_q16(
                generator.INT64_MAX,
                overflowing_bands,
                np.asarray([0], dtype=np.int64),
                (1, 1),
                (1, 1),
            )

    def test_q16_to_u8_rounds_ties_away_then_clips(self) -> None:
        values = np.asarray(
            [generator.Q16 // 2, -generator.Q16 // 2, generator.Q16 + generator.Q16 // 2,
             300 * generator.Q16],
            dtype=np.int64,
        )
        self.assertEqual(generator.q16_to_u8(values).tolist(), [1, 0, 2, 255])

    def test_type7_quantile_interpolation_is_inclusive_and_integer(self) -> None:
        knots = np.arange(17, dtype=np.int64) * 160
        observed = generator.interpolate_type7_quantiles(knots, 5)
        self.assertEqual(observed.tolist(), [0, 640, 1280, 1920, 2560])

    def test_body8_uses_equal_body_aggregate_and_no_eighth_statistic(self) -> None:
        records = []
        for index in range(7):
            records.append(
                generator.BodyStatistics(
                    median_lab_q16=np.asarray([index, index + 10, index + 20], dtype=np.int64),
                    radial_power_q16=np.full(16, index + 1, dtype=np.int64),
                    quantiles_q16=np.full(17, (index + 1) * 7, dtype=np.int64),
                )
            )
        aggregate = generator.aggregate_body_statistics(records)
        self.assertEqual(aggregate.median_lab_q16.tolist(), [3, 13, 23])
        self.assertEqual(aggregate.radial_power_q16.tolist(), [4] * 16)
        self.assertEqual(aggregate.quantiles_q16.tolist(), [28] * 17)

    def test_phase_is_seeded_deterministic_and_rank_maps_once(self) -> None:
        body = np.zeros((12, 14), dtype=bool)
        body[2:10, 3:11] = True
        statistics = generator.BodyStatistics(
            median_lab_q16=np.asarray([40, 50, 60], dtype=np.int64) * generator.Q16,
            radial_power_q16=np.full(16, generator.Q16 // 16, dtype=np.int64),
            quantiles_q16=np.arange(-8, 9, dtype=np.int64) * 100,
        )
        first = generator.synthesize_statistical_phase(body.shape, body, statistics, 123)
        replay = generator.synthesize_statistical_phase(body.shape, body, statistics, 123)
        distinct = generator.synthesize_statistical_phase(body.shape, body, statistics, 456)
        self.assertTrue(np.array_equal(first, replay))
        self.assertFalse(np.array_equal(first[body], distinct[body]))
        expected_distribution = generator.interpolate_type7_quantiles(
            statistics.quantiles_q16, int(body.sum())
        )
        self.assertTrue(np.array_equal(np.sort(first[body]), expected_distribution))
        self.assertTrue(np.all(first[~body] == 0))

    def test_phase_support_crop_is_tight_plus_g24_radius_zeros(self) -> None:
        body = np.zeros((20, 30), dtype=bool)
        body[7:10, 12:17] = True
        cropped = generator.phase_support_crop(body)
        self.assertEqual(cropped.shape, (3 + 192, 5 + 192))
        self.assertTrue(
            np.array_equal(cropped[96:99, 96:101], np.ones((3, 5), dtype=bool))
        )
        self.assertEqual(int(cropped.sum()), 15)

    def test_all_four_lock_classes_restore_byte_exact_v18(self) -> None:
        baseline = np.arange(6 * 7 * 3, dtype=np.uint8).reshape(6, 7, 3)
        candidate = np.full_like(baseline, 255)
        permission = np.ones((6, 7), dtype=bool)
        permission[0, 0] = False
        protected = np.zeros((6, 7), dtype=bool)
        protected[1, 1] = True
        road = np.zeros((6, 7), dtype=bool)
        road[2, 2] = True
        alpha_zero = np.zeros((6, 7), dtype=bool)
        alpha_zero[3, 3] = True
        output = generator.restore_v18_locks(
            candidate, baseline, permission, protected, road, alpha_zero
        )
        locked = ~permission | protected | road | alpha_zero
        self.assertTrue(np.array_equal(output[locked], baseline[locked]))
        self.assertTrue(np.all(output[~locked] == 255))

    def test_finalization_restores_every_byte_outside_exact_v20_union(self) -> None:
        foundation = np.arange(6 * 7 * 3, dtype=np.uint8).reshape(6, 7, 3)
        baseline = foundation.copy()
        candidate = np.full_like(foundation, 251)
        supports = [np.zeros((6, 7), dtype=bool) for _ in generator.BODY_VALUES]
        support_points = [(1, 1), (1, 3), (1, 5), (2, 2), (2, 4), (3, 1), (3, 3), (3, 5)]
        for support, point in zip(supports, support_points, strict=True):
            support[point] = True
        body_union = np.logical_or.reduce(supports)
        permission = np.ones((6, 7), dtype=bool)
        permission[0, 0] = False
        protected = np.zeros((6, 7), dtype=bool)
        protected[1, 1] = True
        road = np.zeros((6, 7), dtype=bool)
        alpha_zero = np.zeros((6, 7), dtype=bool)
        baseline[1, 1] = np.asarray([7, 8, 9], dtype=np.uint8)

        output = generator.finalize_candidate_rgb(
            candidate,
            foundation,
            baseline,
            permission,
            protected,
            road,
            alpha_zero,
            supports,
        )
        self.assertTrue(np.array_equal(output[~body_union], foundation[~body_union]))
        self.assertTrue(np.array_equal(output[1, 1], baseline[1, 1]))

        conflicting_baseline = baseline.copy()
        conflicting_baseline[0, 0, 0] ^= np.uint8(1)
        with self.assertRaisesRegex(generator.DerivationError, "disagree"):
            generator.finalize_candidate_rgb(
                candidate,
                foundation,
                conflicting_baseline,
                permission,
                protected,
                road,
                alpha_zero,
                supports,
            )

    def test_cli_has_no_candidate_parameter_or_output_override(self) -> None:
        parser = generator.build_parser()
        default = parser.parse_args([])
        self.assertFalse(default.emit)
        self.assertFalse(default.check)
        explicit = parser.parse_args(["--emit"])
        self.assertTrue(explicit.emit)
        compared = parser.parse_args(["--compare-seals", "left.json", "right.json"])
        self.assertEqual(compared.compare_seals, [Path("left.json"), Path("right.json")])
        destinations = {action.dest for action in parser._actions}
        self.assertEqual(destinations, {"help", "check", "emit", "compare_seals"})

    def test_exclusive_final_reservation_publishes_once_without_overwrite(self) -> None:
        authority = copy.deepcopy(self.authority)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payloads = [
                (root / record["output_path"], f"synthetic-{index}".encode("ascii"))
                for index, record in enumerate(authority["candidates"]["records"])
            ]
            profile_id = authority["runtime"]["allowed_profiles"][0]["id"]
            generator.publish_payloads_exclusive(
                authority, payloads, runtime_profile_id=profile_id, root=root
            )
            for path, payload in payloads:
                self.assertEqual(path.read_bytes(), payload)
            seal = root / authority["cli_contract"]["seal_path"]
            self.assertTrue(seal.is_file())
            before = {path: path.read_bytes() for path, _ in payloads}
            with self.assertRaisesRegex(generator.DerivationError, "reservation"):
                generator.publish_payloads_exclusive(
                    authority, payloads, runtime_profile_id=profile_id, root=root
                )
            self.assertEqual({path: path.read_bytes() for path, _ in payloads}, before)

    def test_compare_only_cli_requires_cross_profile_four_png_byte_equality(self) -> None:
        authority = copy.deepcopy(self.authority)
        profiles = [
            profile["id"] for profile in authority["runtime"]["allowed_profiles"]
        ]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)

            def publish(root: Path, profile_id: str, *, changed: bool = False) -> Path:
                payloads = []
                for index, record in enumerate(authority["candidates"]["records"]):
                    payload = f"same-synthetic-png-{index}".encode("ascii")
                    if changed and index == 3:
                        payload += b"-changed"
                    payloads.append((root / record["output_path"], payload))
                generator.publish_payloads_exclusive(
                    authority,
                    payloads,
                    runtime_profile_id=profile_id,
                    root=root,
                )
                return root / authority["cli_contract"]["seal_path"]

            left = publish(base / "profile-a", profiles[0])
            right = publish(base / "profile-b", profiles[1])
            self.assertEqual(
                generator.compare_profile_seals(authority, left, right),
                (profiles[0], profiles[1]),
            )
            with self.assertRaisesRegex(generator.DerivationError, "distinct"):
                generator.compare_profile_seals(authority, left, left)
            with (
                mock.patch.object(
                    generator, "load_authority", return_value=authority
                ),
                mock.patch.object(
                    generator, "_runtime_gate", return_value=profiles[2]
                ),
                mock.patch.object(
                    generator,
                    "check_bound_sources",
                    side_effect=AssertionError("compare-only must not read bound sources"),
                ),
                mock.patch.object(
                    generator,
                    "_decode_bound_rgb",
                    side_effect=AssertionError("compare-only must not decode PNGs"),
                ) as decoder,
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                self.assertEqual(
                    generator.main(
                        ["--compare-seals", str(left), str(right)]
                    ),
                    0,
                )
                decoder.assert_not_called()
                self.assertIn("exactly four PNG payloads", stdout.getvalue())

            changed = publish(base / "profile-c", profiles[2], changed=True)
            with self.assertRaisesRegex(generator.DerivationError, "hashes/bytes differ"):
                generator.compare_profile_seals(authority, left, changed)

    def test_runtime_and_emit_read_allowlist_are_frozen(self) -> None:
        self.assertEqual(self.authority["runtime"], generator.EXPECTED_RUNTIME)
        self.assertEqual(
            [
                profile["id"]
                for profile in generator.EXPECTED_RUNTIME["allowed_profiles"]
            ],
            [
                "windows-local-opencv-python-4.13.0.92",
                "windows-ci-opencv-python-headless-4.13.0.92",
                "linux-ci-opencv-python-headless-4.13.0.92",
            ],
        )
        allowlist = set(
            self.authority["input_policy"]["candidate_generator_read_allowlist_roles"]
        )
        self.assertNotIn(
            "v19-statistics-firewall-extractor-provenance-only", allowlist
        )
        self.assertNotIn("v19-byte-closed-replay-module", allowlist)
        self.assertNotIn("v21-dev20-search-summary", allowlist)
        self.assertIn("sealed-v19-statistics-firewall", allowlist)
        self.assertIn(
            "sealed-v19-statistics-firewall",
            generator.source_bindings(self.authority),
        )

    def test_generator_has_no_forbidden_replay_or_summary_calls(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn('discard("sealed-v19-statistics-firewall")', source)
        tree = ast.parse(source)
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertTrue(
            {"load_replay_inputs", "reconstruct", "_validate_search_summary"}.isdisjoint(
                called_attributes
            )
        )
        imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertFalse(
            any("build_style_candidate_k3_sparse_ridgeline_v19" in ast.unparse(node) for node in imports)
        )


if __name__ == "__main__":
    unittest.main()
