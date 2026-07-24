"""Regression tests for deterministic low-frequency plate calibration."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts/map-production/calibrate_luminance_plate.py"
SPEC = importlib.util.spec_from_file_location("plate_calibration", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
calibration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(calibration)

SCHEMA = (
    REPO_ROOT / "world/map-production/schemas/luminance-plate-calibration.schema.json"
)
SCHEMA_V2 = (
    REPO_ROOT
    / "world/map-production/schemas/luminance-plate-calibration-v2.schema.json"
)
E3_CONTROL = (
    REPO_ROOT / "world/map-production/controls/style-candidate-e-v3-calibration-v1.json"
)
E4_CONTROL = (
    REPO_ROOT / "world/map-production/controls/style-candidate-e-v4-calibration-v1.json"
)
E5_CONTROL = (
    REPO_ROOT / "world/map-production/controls/style-candidate-e-v5-calibration-v1.json"
)
F2_CONTROL = (
    REPO_ROOT / "world/map-production/controls/style-candidate-f-v2-calibration-v1.json"
)
F3_CONTROL = (
    REPO_ROOT / "world/map-production/controls/style-candidate-f-v3-calibration-v1.json"
)
F5_CONTROL = (
    REPO_ROOT / "world/map-production/controls/style-candidate-f-v5-calibration-v1.json"
)
E3_OUTPUT = (
    REPO_ROOT
    / "world/map-production/candidates/style-candidate-e-v3-south-east-calibrated-plate.png"
)
E3_SUPPORT = (
    REPO_ROOT
    / "world/map-production/qa/automated/style-candidate-e-v3-calibration-support.png"
)
E3_FIELD = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-e-v3-calibration-field-v1.png"
)
E3_REPORT = (
    REPO_ROOT
    / "world/map-production/qa/automated/style-candidate-e-v3-calibration.json"
)
E4_OUTPUT = (
    REPO_ROOT
    / "world/map-production/candidates/style-candidate-e-v4-minimum-areal-support-plate.png"
)
E4_SUPPORT = (
    REPO_ROOT
    / "world/map-production/qa/automated/style-candidate-e-v4-calibration-support.png"
)
E4_FIELD = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-e-v4-calibration-field-v1.png"
)
E4_REPORT = (
    REPO_ROOT
    / "world/map-production/qa/automated/style-candidate-e-v4-calibration.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def semantic_sha256(path: Path) -> str:
    from PIL import Image

    with Image.open(path) as opened:
        opened.load()
        return calibration._raster_semantic_sha256(opened)


class LuminancePlateCalibrationTest(unittest.TestCase):
    maxDiff = None

    def _targets(self, root: Path) -> tuple[Path, Path, Path, Path]:
        return (
            root / "output.png",
            root / "support.png",
            root / "field.png",
            root / "report.json",
        )

    def _run(
        self,
        control: Path,
        root: Path,
        *,
        schema: Path = SCHEMA,
    ) -> dict[str, object]:
        output, support, field, report = self._targets(root)
        return calibration.calibrate(
            control_path=control,
            schema_path=schema,
            output_path=output,
            support_output_path=support,
            field_output_path=field,
            report_path=report,
        )

    def _assert_rejected_without_artifacts(
        self,
        control: dict[str, object],
        error_pattern: str,
        *,
        prefix: str,
        schema: Path = SCHEMA_V2,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix=prefix) as directory:
            root = Path(directory)
            control_path = root / "control.json"
            control_path.write_text(
                json.dumps(control, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(calibration.CalibrationError, error_pattern):
                self._run(control_path, root, schema=schema)
            self.assertFalse(any(path.exists() for path in self._targets(root)))
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_committed_artifacts_match_deterministic_reports(self) -> None:
        e3 = json.loads(E3_REPORT.read_text(encoding="utf-8"))
        e4 = json.loads(E4_REPORT.read_text(encoding="utf-8"))
        for report, output, support, field in (
            (e3, E3_OUTPUT, E3_SUPPORT, E3_FIELD),
            (e4, E4_OUTPUT, E4_SUPPORT, E4_FIELD),
        ):
            self.assertEqual(report["output_sha256"], sha256(output))
            self.assertEqual(report["support_sha256"], sha256(support))
            self.assertEqual(report["field_sha256"], sha256(field))
            self.assertEqual(report["operation"]["outside_permission_changed_pixels"], 0)
            self.assertEqual(report["operation"]["clipping_pixels"], 0)
            self.assertEqual(report["operation"]["maximum_rgb_delta_spread_levels"], 0)
            self.assertEqual(report["operation"]["chroma_changed_pixels"], 0)
        self.assertEqual(e3["full_transfer_preflight"]["status"], "rejected")
        self.assertEqual(
            e3["full_transfer_preflight"]["failure"],
            "north_east_range quadrant 3 P90 is 1.0",
        )
        self.assertEqual(e4["full_transfer_preflight"]["status"], "passed")
        self.assertEqual(
            [
                item["p90_absolute_delta_levels"]
                for item in e4["transfer_preflight_metrics"][
                    "region_quadrant_metrics"
                ]
            ],
            [4.0, 4.0, 2.0, 6.0, 4.0, 2.0, 6.0, 4.0],
        )

    def test_legacy_schema_is_immutable_for_e3_and_e4_evidence(self) -> None:
        self.assertEqual(
            sha256(SCHEMA),
            "66e92280c8e9827f5d685409dca0690053c425d14273d99828856617f0c7e07f",
        )

    def test_e3_regional_gain_replay_is_decoded_raster_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sstory-e3-replay-") as directory:
            root = Path(directory)
            report = self._run(E3_CONTROL, root)
            output, support, field, _ = self._targets(root)
            self.assertEqual(semantic_sha256(output), semantic_sha256(E3_OUTPUT))
            self.assertEqual(semantic_sha256(support), semantic_sha256(E3_SUPPORT))
            self.assertEqual(semantic_sha256(field), semantic_sha256(E3_FIELD))
            self.assertEqual(report["output_sha256"], sha256(output))
            self.assertEqual(report["support_sha256"], sha256(support))
            self.assertEqual(report["field_sha256"], sha256(field))
            self.assertEqual(report["full_transfer_preflight"]["status"], "rejected")

    def test_e4_minimum_support_replay_is_decoded_raster_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sstory-e4-replay-") as directory:
            root = Path(directory)
            report = self._run(E4_CONTROL, root)
            output, support, field, _ = self._targets(root)
            self.assertEqual(semantic_sha256(output), semantic_sha256(E4_OUTPUT))
            self.assertEqual(semantic_sha256(support), semantic_sha256(E4_SUPPORT))
            self.assertEqual(semantic_sha256(field), semantic_sha256(E4_FIELD))
            self.assertEqual(report["output_sha256"], sha256(output))
            self.assertEqual(report["support_sha256"], sha256(support))
            self.assertEqual(report["field_sha256"], sha256(field))
            self.assertEqual(report["full_transfer_preflight"]["status"], "passed")

    def test_raster_semantic_hash_ignores_png_encoding_but_detects_one_pixel(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory(prefix="sstory-plate-raster-hash-") as directory:
            root = Path(directory)
            first_path = root / "first.png"
            second_path = root / "second.png"
            changed_path = root / "changed.png"
            raster = Image.new("L", (16, 16))
            raster.putdata(bytes((index * 29) % 256 for index in range(256)))
            try:
                raster.save(
                    first_path, format="PNG", compress_level=0, optimize=False
                )
                raster.save(
                    second_path, format="PNG", compress_level=9, optimize=False
                )
                changed = raster.copy()
                changed.putpixel((5, 11), (changed.getpixel((5, 11)) + 1) % 256)
                try:
                    changed.save(
                        changed_path,
                        format="PNG",
                        compress_level=9,
                        optimize=False,
                    )
                finally:
                    changed.close()
            finally:
                raster.close()

            self.assertNotEqual(first_path.read_bytes(), second_path.read_bytes())
            self.assertEqual(
                semantic_sha256(first_path), semantic_sha256(second_path)
            )
            self.assertNotEqual(
                semantic_sha256(first_path), semantic_sha256(changed_path)
            )

    def test_unknown_control_key_fails_without_partial_artifacts(self) -> None:
        control = json.loads(E3_CONTROL.read_text(encoding="utf-8"))
        control["unexpected"] = True
        with tempfile.TemporaryDirectory(prefix="sstory-calibration-invalid-") as directory:
            root = Path(directory)
            control_path = root / "control.json"
            control_path.write_text(json.dumps(control), encoding="utf-8")
            with self.assertRaises(calibration.CalibrationError):
                self._run(control_path, root)
            self.assertFalse(any(path.exists() for path in self._targets(root)))
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_wrong_source_hash_fails_without_partial_artifacts(self) -> None:
        control = json.loads(E3_CONTROL.read_text(encoding="utf-8"))
        control["source_image"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory(prefix="sstory-calibration-hash-") as directory:
            root = Path(directory)
            control_path = root / "control.json"
            control_path.write_text(json.dumps(control), encoding="utf-8")
            with self.assertRaises(calibration.CalibrationError):
                self._run(control_path, root)
            self.assertFalse(any(path.exists() for path in self._targets(root)))
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_amplitude_minus_one_ablation_cannot_publish(self) -> None:
        control = json.loads(E4_CONTROL.read_text(encoding="utf-8"))
        control["calibration"]["minimum_areal_support"]["amplitude_levels"] = -1
        with tempfile.TemporaryDirectory(prefix="sstory-calibration-ablation-") as directory:
            root = Path(directory)
            control_path = root / "control.json"
            control_path.write_text(json.dumps(control), encoding="utf-8")
            with self.assertRaisesRegex(
                calibration.CalibrationError,
                "region_quadrant_p90_absolute_delta_levels mismatch",
            ):
                self._run(control_path, root)
            self.assertFalse(any(path.exists() for path in self._targets(root)))
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_non_default_control_rejects_default_output_mix(self) -> None:
        self.assertEqual(
            calibration.main(["--control", str(E4_CONTROL)]),
            1,
        )

    def test_v2_topology_mesh_requires_exact_grid_cardinality(self) -> None:
        control = json.loads(E5_CONTROL.read_text(encoding="utf-8"))
        control["calibration"]["topology_mesh"]["grid"]["values"].pop()
        with tempfile.TemporaryDirectory(prefix="sstory-topology-cardinality-") as directory:
            root = Path(directory)
            control_path = root / "control.json"
            control_path.write_text(json.dumps(control), encoding="utf-8")
            with self.assertRaisesRegex(
                calibration.CalibrationError,
                "grid values must equal width multiplied by height",
            ):
                self._run(control_path, root, schema=SCHEMA_V2)
            self.assertFalse(any(path.exists() for path in self._targets(root)))
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_v2_topology_mesh_cannot_coexist_with_legacy_operation(self) -> None:
        control = json.loads(E5_CONTROL.read_text(encoding="utf-8"))
        control["calibration"]["minimum_areal_support"] = {
            "region_id": "north_east_range",
            "target_quadrant": 3,
            "shape": "cosine-squared-ellipse",
            "center": [1040, 440],
            "radii": [180, 140],
            "amplitude_levels": -2,
            "apply_transfer_region_feather": True,
            "purpose": "invalid coexistence fixture",
        }
        with tempfile.TemporaryDirectory(prefix="sstory-topology-oneof-") as directory:
            root = Path(directory)
            control_path = root / "control.json"
            control_path.write_text(json.dumps(control), encoding="utf-8")
            with self.assertRaisesRegex(
                calibration.CalibrationError,
                "calibration control schema failed",
            ):
                self._run(control_path, root, schema=SCHEMA_V2)
            self.assertFalse(any(path.exists() for path in self._targets(root)))
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_v2_topology_zones_reject_duplicate_zone_ids_without_artifacts(self) -> None:
        control = json.loads(F2_CONTROL.read_text(encoding="utf-8"))
        zones = control["calibration"]["topology_zones"]["zones"]
        zones[1]["id"] = zones[0]["id"]
        with tempfile.TemporaryDirectory(prefix="sstory-zone-ids-") as directory:
            root = Path(directory)
            control_path = root / "control.json"
            control_path.write_text(json.dumps(control), encoding="utf-8")
            with self.assertRaisesRegex(
                calibration.CalibrationError,
                "topology_zones zone ids must be unique",
            ):
                self._run(control_path, root, schema=SCHEMA_V2)
            self.assertFalse(any(path.exists() for path in self._targets(root)))
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_v2_topology_zones_require_complete_role_hierarchy(self) -> None:
        control = json.loads(F2_CONTROL.read_text(encoding="utf-8"))
        zones = control["calibration"]["topology_zones"]["zones"]
        zones[0]["role"] = "foothill"
        with tempfile.TemporaryDirectory(prefix="sstory-zone-roles-") as directory:
            root = Path(directory)
            control_path = root / "control.json"
            control_path.write_text(json.dumps(control), encoding="utf-8")
            with self.assertRaisesRegex(
                calibration.CalibrationError,
                "requires exactly one dominant-massif",
            ):
                self._run(control_path, root, schema=SCHEMA_V2)
            self.assertFalse(any(path.exists() for path in self._targets(root)))
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_v2_topology_zones_cannot_coexist_with_mesh(self) -> None:
        control = json.loads(F2_CONTROL.read_text(encoding="utf-8"))
        mesh = json.loads(E5_CONTROL.read_text(encoding="utf-8"))["calibration"][
            "topology_mesh"
        ]
        control["calibration"]["topology_mesh"] = mesh
        with tempfile.TemporaryDirectory(prefix="sstory-zone-oneof-") as directory:
            root = Path(directory)
            control_path = root / "control.json"
            control_path.write_text(json.dumps(control), encoding="utf-8")
            with self.assertRaisesRegex(
                calibration.CalibrationError,
                "calibration control schema failed",
            ):
                self._run(control_path, root, schema=SCHEMA_V2)
            self.assertFalse(any(path.exists() for path in self._targets(root)))
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_compact_schema_lock_path_and_sha_fail_closed(self) -> None:
        cases: list[tuple[str, dict[str, object], str]] = []

        wrong_path = json.loads(F5_CONTROL.read_text(encoding="utf-8"))
        wrong_path["schema_lock"] = {
            "path": SCHEMA.relative_to(REPO_ROOT).as_posix(),
            "sha256": sha256(SCHEMA),
        }
        cases.append(("path", wrong_path, "schema path differs from the locked schema"))

        wrong_sha = json.loads(F5_CONTROL.read_text(encoding="utf-8"))
        wrong_sha["schema_lock"]["sha256"] = "0" * 64
        cases.append(("sha", wrong_sha, "locked calibration schema SHA-256 mismatch"))

        for label, control, error_pattern in cases:
            with self.subTest(label=label):
                self._assert_rejected_without_artifacts(
                    control,
                    error_pattern,
                    prefix=f"sstory-compact-schema-lock-{label}-",
                )

    def test_compact_zlib_runtime_is_provenance_only_and_distribution_stays_locked(
        self,
    ) -> None:
        control = json.loads(F5_CONTROL.read_text(encoding="utf-8"))
        numeric_contract = control["numeric_contract"]
        self.assertEqual(
            numeric_contract["raster_semantic_hash"],
            "sstory-raster-semantic-v1",
        )
        self.assertEqual(
            numeric_contract["zlib_runtime_policy"],
            "provenance-only",
        )
        self.assertNotIn("zlib_runtime_version", numeric_contract)

        raster_path = REPO_ROOT / control["transfer_control"]["raster_path"]
        self.assertEqual(
            sha256(raster_path),
            control["transfer_control"]["raster_sha256"],
        )
        with mock.patch.object(calibration.zlib, "ZLIB_RUNTIME_VERSION", "1.3"):
            calibration._validate_inputs(control, F5_CONTROL, SCHEMA_V2)

        wrong_distribution = json.loads(F5_CONTROL.read_text(encoding="utf-8"))
        wrong_distribution["transfer_control"]["raster_sha256"] = "0" * 64
        with mock.patch.object(calibration.zlib, "ZLIB_RUNTIME_VERSION", "1.3"):
            self._assert_rejected_without_artifacts(
                wrong_distribution,
                "transfer raster SHA-256 mismatch",
                prefix="sstory-compact-distribution-sha-",
            )

    def test_compact_unknown_key_is_rejected_without_artifacts(self) -> None:
        control = json.loads(F5_CONTROL.read_text(encoding="utf-8"))
        control["calibration"]["topology_compact_ridges"]["unexpected"] = True
        self._assert_rejected_without_artifacts(
            control,
            "calibration control schema failed",
            prefix="sstory-compact-unknown-key-",
        )

    def test_compact_endpoint_height_is_rejected_without_artifacts(self) -> None:
        control = json.loads(F5_CONTROL.read_text(encoding="utf-8"))
        nodes = control["calibration"]["topology_compact_ridges"]["regions"][0][
            "primitives"
        ][0]["nodes"]
        nodes[0]["height"] = 0.1
        with mock.patch.object(calibration.zlib, "ZLIB_RUNTIME_VERSION", "1.3"):
            self._assert_rejected_without_artifacts(
                control,
                "endpoints must have zero height",
                prefix="sstory-compact-endpoint-height-",
            )

    def test_compact_duplicate_primitive_and_node_ids_are_rejected(self) -> None:
        duplicate_primitive = json.loads(F5_CONTROL.read_text(encoding="utf-8"))
        primitives = duplicate_primitive["calibration"]["topology_compact_ridges"][
            "regions"
        ][0]["primitives"]
        primitives[1]["id"] = primitives[0]["id"]

        duplicate_node = json.loads(F5_CONTROL.read_text(encoding="utf-8"))
        nodes = duplicate_node["calibration"]["topology_compact_ridges"]["regions"][
            0
        ]["primitives"][0]["nodes"]
        nodes[1]["id"] = nodes[0]["id"]

        for label, control, error_pattern in (
            ("primitive", duplicate_primitive, "primitive ids must be globally unique"),
            ("node", duplicate_node, "node ids must be globally unique"),
        ):
            with self.subTest(label=label):
                self._assert_rejected_without_artifacts(
                    control,
                    error_pattern,
                    prefix=f"sstory-compact-duplicate-{label}-",
                )

    def test_signed_tail_transform_contract(self) -> None:
        activation_scale = 0.06
        extrema_scale = 0.18
        transform = calibration._signed_tail_transform

        self.assertEqual(transform(0.0, activation_scale, extrema_scale), 0.0)

        positive_values = [0.001, 0.006, 0.02, 0.06, 0.12, 0.3, 1.0]
        transformed = [
            transform(value, activation_scale, extrema_scale)
            for value in positive_values
        ]
        self.assertTrue(
            all(left < right for left, right in zip(transformed, transformed[1:]))
        )

        for value, actual in zip(positive_values, transformed):
            with self.subTest(value=value):
                self.assertAlmostEqual(
                    transform(-value, activation_scale, extrema_scale),
                    -actual,
                    places=15,
                )
                self.assertLessEqual(abs(actual), abs(value))

        small_tail = activation_scale / 10
        attenuated_tail = transform(
            small_tail,
            activation_scale,
            extrema_scale,
        )
        self.assertGreater(attenuated_tail, 0)
        self.assertLess(attenuated_tail, small_tail * 0.11)

    def test_signed_tail_transform_rejects_nonfinite_or_nonpositive_inputs(self) -> None:
        invalid_cases = (
            (math.nan, 0.06, 0.18),
            (math.inf, 0.06, 0.18),
            (0.1, 0.0, 0.18),
            (0.1, -0.06, 0.18),
            (0.1, 0.06, 0.0),
            (0.1, 0.06, -0.18),
        )
        for value, activation_scale, extrema_scale in invalid_cases:
            with self.subTest(
                value=value,
                activation_scale=activation_scale,
                extrema_scale=extrema_scale,
            ):
                with self.assertRaises(calibration.CalibrationError):
                    calibration._signed_tail_transform(
                        value,
                        activation_scale,
                        extrema_scale,
                    )

    def test_existing_f2_and_f3_f4_v2_controls_remain_schema_compatible(self) -> None:
        for control_path in (F2_CONTROL, F3_CONTROL):
            with self.subTest(control=control_path.name):
                control = json.loads(control_path.read_text(encoding="utf-8"))
                calibration._validate_schema(control, SCHEMA_V2)


if __name__ == "__main__":
    unittest.main()
