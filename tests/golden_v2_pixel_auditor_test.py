from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import audit_style_candidate_k3_golden_v2 as auditor  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_rgb(path: Path, values: np.ndarray) -> None:
    with Image.fromarray(values.astype(np.uint8), mode="RGB") as image:
        image.save(path, format="PNG", compress_level=9, optimize=False)


def save_mask(path: Path, values: np.ndarray) -> None:
    encoded = np.where(values, 255, 0).astype(np.uint8)
    with Image.fromarray(encoded, mode="L") as image:
        image.save(path, format="PNG", compress_level=9, optimize=False)


@dataclass(frozen=True)
class MemoryBinding:
    data: bytes
    sha256: str
    path: Path | None = None


class GoldenV2PixelFixture:
    width = 384
    height = 256

    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="golden-v2-pixel-audit-")
        self.root = Path(self.temporary.name)
        yy, xx = np.indices((self.height, self.width))
        checker = ((xx // 4 + yy // 4) % 2).astype(np.uint8)
        gray = np.where(checker == 0, 74, 186).astype(np.uint8)
        candidate = np.repeat(gray[..., None], 3, axis=2)

        # A bounded quiet island keeps the fixed quiet/orientation/dash probes
        # independent from the high-contrast global readability fixture.
        candidate[104:152, 160:224] = np.uint8(130)
        candidate[128, 192] = np.uint8(92)
        self.candidate_values = candidate
        self.baseline_values = candidate.copy()
        self.candidate = self.root / "candidate.png"
        self.baseline = self.root / "baseline.png"
        save_rgb(self.candidate, candidate)

        measurement = np.zeros((self.height, self.width), dtype=bool)
        measurement[116:140, 172:212] = True
        selected = np.zeros_like(measurement)
        for y in (120, 132):
            for x in (176, 184, 192, 200):
                selected[y : y + 2, x : x + 2] = True
        # Preserve the exact grayscale texture denominator while making each
        # authorized component differ in native RGB pixels.
        self.baseline_values[selected] = np.array([131, 130, 128], dtype=np.uint8)
        save_rgb(self.baseline, self.baseline_values)
        permission = measurement.copy()
        permission[108:112, 164:168] = True
        protected = np.zeros_like(measurement)
        protected[108:110, 164:166] = True
        road_calm = np.zeros_like(measurement)
        road_calm[110:112, 166:168] = True
        self.mask_values = {
            "measurement_inside": measurement,
            "texture_reference": measurement.copy(),
            "permission": permission,
            "protected_features": protected,
            "road_calm_18px": road_calm,
            "selected_components": selected,
        }
        self.mask_paths: dict[str, Path] = {}
        for name, values in self.mask_values.items():
            path = self.root / f"{name}.png"
            save_mask(path, values)
            self.mask_paths[name] = path
        self.control = self.root / "audit-control.json"
        self.write_control()

    def close(self) -> None:
        self.temporary.cleanup()

    def write_control(
        self,
        *,
        candidate: Path | None = None,
        baseline: Path | None = None,
        mask_paths: dict[str, Path] | None = None,
    ) -> None:
        candidate = candidate or self.candidate
        baseline = baseline or self.baseline
        mask_paths = mask_paths or self.mask_paths
        record = {
            "schema_version": auditor.SCHEMA_VERSION,
            "id": auditor.CONTROL_ID,
            "algorithm": auditor.ALGORITHM,
            "image": {
                "mode": "RGB",
                "size": [self.width, self.height],
            },
            "candidate": {"sha256": sha256(candidate)},
            "baseline": {
                "reproduction_role": auditor.BASELINE_REPRODUCTION_ROLE,
                "sha256": sha256(baseline),
            },
            "masks": {
                name: {
                    "reproduction_role": auditor.MASK_REPRODUCTION_ROLES[name],
                    "path": path.relative_to(self.root).as_posix(),
                    "sha256": sha256(path),
                }
                for name, path in mask_paths.items()
            },
        }
        self.control.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )


class GoldenV2PixelAuditorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = GoldenV2PixelFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_passing_fixture_recomputes_every_field_deterministically(self) -> None:
        first = auditor.audit_candidate(
            self.fixture.candidate,
            self.fixture.baseline,
            self.fixture.control,
        )
        second = auditor.audit_candidate(
            self.fixture.candidate,
            self.fixture.baseline,
            self.fixture.control,
        )

        self.assertEqual(first, second)
        self.assertTrue(first["passed"], first["failed_gates"])
        self.assertEqual(
            first["metrics"],
            {
                "coverage_50": 376,
                "coverage_25": 376,
                "quiet_fraction": 0.978125,
                "dash_bundle_pairs": 0,
                "orientation_coherence": 0.0,
                "texture_inside_to_outside_ratio": {"4": 1.0, "8": 1.0},
            },
        )
        self.assertEqual(first["geometry"], {"selected_component_count": 8})
        self.assertEqual(first["geometry_proof"]["mask_component_count"], 8)
        self.assertEqual(first["geometry_proof"]["valid_component_count"], 8)
        self.assertEqual(
            first["geometry_proof"]["thresholds"], auditor.GEOMETRY_THRESHOLDS
        )
        self.assertTrue(
            all(item["valid"] for item in first["geometry_proof"]["components"])
        )
        self.assertTrue(
            all(
                item["changed_fraction"] == 1.0
                and item["changed_x_span_fraction"] == 1.0
                and item["changed_y_span_fraction"] == 1.0
                for item in first["geometry_proof"]["components"]
            )
        )
        self.assertEqual(
            first["identity"],
            {
                "outside_permission": 0,
                "protected_features": 0,
                "road_calm_18px": 0,
            },
        )
        self.assertTrue(all(first["gates"].values()))

    def test_bound_snapshots_and_reproduction_role_mask_map_are_supported(self) -> None:
        def binding(path: Path, *, keep_path: bool = False) -> MemoryBinding:
            data = path.read_bytes()
            return MemoryBinding(
                data=data,
                sha256=hashlib.sha256(data).hexdigest(),
                path=path if keep_path else None,
            )

        mask_bindings = {
            auditor.MASK_REPRODUCTION_ROLES[name]: binding(path)
            for name, path in self.fixture.mask_paths.items()
        }
        report = auditor.audit_candidate(
            binding(self.fixture.candidate),
            binding(self.fixture.baseline),
            binding(self.fixture.control),
            mask_bindings=mask_bindings,
        )
        control = auditor.load_audit_control(binding(self.fixture.control))

        self.assertTrue(report["passed"])
        self.assertEqual(
            control.mask_reproduction_roles,
            auditor.MASK_REPRODUCTION_ROLES,
        )

    def test_recomputed_identity_rejects_changed_forbidden_pixels(self) -> None:
        tampered = self.fixture.candidate_values.copy()
        tampered[0, 0] = np.uint8(0)
        tampered[108, 164] = np.uint8(0)
        tampered[110, 166] = np.uint8(0)
        candidate = self.fixture.root / "tampered-candidate.png"
        save_rgb(candidate, tampered)
        self.fixture.write_control(candidate=candidate)

        report = auditor.audit_candidate(
            candidate,
            self.fixture.baseline,
            self.fixture.control,
        )

        self.assertFalse(report["passed"])
        self.assertEqual(
            report["identity"],
            {
                "outside_permission": 1,
                "protected_features": 1,
                "road_calm_18px": 1,
            },
        )
        self.assertIn("outside_permission_zero", report["failed_gates"])
        self.assertIn("protected_features_zero", report["failed_gates"])
        self.assertIn("road_calm_18px_zero", report["failed_gates"])

    def test_geometry_requires_mask_components_with_real_pixel_changes(self) -> None:
        seven = self.fixture.mask_values["selected_components"].copy()
        seven[132:134, 200:202] = False
        selected = self.fixture.root / "selected-components-seven.png"
        save_mask(selected, seven)
        paths = dict(self.fixture.mask_paths)
        paths["selected_components"] = selected
        self.fixture.write_control(mask_paths=paths)

        report = auditor.audit_candidate(
            self.fixture.candidate,
            self.fixture.baseline,
            self.fixture.control,
        )

        self.assertEqual(report["geometry"], {"selected_component_count": 7})
        self.assertFalse(report["passed"])
        self.assertIn("selected_component_count_exact_8", report["failed_gates"])

    def test_identical_candidate_and_baseline_cannot_be_proved_by_eight_islands(
        self,
    ) -> None:
        identical = self.fixture.root / "identical-baseline.png"
        identical.write_bytes(self.fixture.candidate.read_bytes())
        self.fixture.write_control(baseline=identical)
        report = auditor.audit_candidate(
            self.fixture.candidate,
            identical,
            self.fixture.control,
        )
        self.assertEqual(report["geometry"], {"selected_component_count": 0})
        self.assertEqual(report["geometry_proof"]["mask_component_count"], 8)
        self.assertEqual(report["geometry_proof"]["valid_component_count"], 0)
        self.assertFalse(report["passed"])
        self.assertIn("selected_component_count_exact_8", report["failed_gates"])

    def test_five_percent_stipple_in_eight_full_span_islands_is_not_geometry(
        self,
    ) -> None:
        selected_values = np.zeros(
            (self.fixture.height, self.fixture.width), dtype=bool
        )
        baseline_values = self.fixture.candidate_values.copy()
        for y in (116, 126):
            for x in (172, 182, 192, 202):
                selected_values[y : y + 9, x : x + 9] = True
                # Four corner pixels cover the full x/y bbox but only 4/81
                # (4.938%) of this nominal five-percent stipple component.
                for dy, dx in ((0, 0), (0, 8), (8, 0), (8, 8)):
                    baseline_values[y + dy, x + dx] = np.array(
                        [131, 130, 128], dtype=np.uint8
                    )

        baseline = self.fixture.root / "five-percent-stipple-baseline.png"
        selected = self.fixture.root / "five-percent-stipple-selected.png"
        save_rgb(baseline, baseline_values)
        save_mask(selected, selected_values)
        paths = dict(self.fixture.mask_paths)
        paths["selected_components"] = selected
        self.fixture.write_control(baseline=baseline, mask_paths=paths)

        report = auditor.audit_candidate(
            self.fixture.candidate,
            baseline,
            self.fixture.control,
        )

        self.assertEqual(report["geometry"], {"selected_component_count": 0})
        self.assertEqual(report["geometry_proof"]["mask_component_count"], 8)
        self.assertEqual(report["geometry_proof"]["valid_component_count"], 0)
        for component in report["geometry_proof"]["components"]:
            self.assertEqual(component["changed_fraction"], 0.049383)
            self.assertEqual(component["changed_x_span_fraction"], 1.0)
            self.assertEqual(component["changed_y_span_fraction"], 1.0)
            self.assertFalse(component["valid"])
        self.assertFalse(report["passed"])
        self.assertIn("selected_component_count_exact_8", report["failed_gates"])

    def test_stale_sha_and_nonbinary_mask_fail_closed(self) -> None:
        control = json.loads(self.fixture.control.read_text(encoding="utf-8"))
        control["candidate"]["sha256"] = "0" * 64
        self.fixture.control.write_text(json.dumps(control), encoding="utf-8")
        with self.assertRaisesRegex(
            auditor.GoldenV2PixelAuditError, "candidate SHA-256"
        ):
            auditor.audit_candidate(
                self.fixture.candidate,
                self.fixture.baseline,
                self.fixture.control,
            )

        invalid = self.fixture.root / "nonbinary-permission.png"
        values = np.zeros((self.fixture.height, self.fixture.width), np.uint8)
        values[116:140, 172:212] = np.uint8(128)
        with Image.fromarray(values, mode="L") as image:
            image.save(invalid, format="PNG", compress_level=9, optimize=False)
        paths = dict(self.fixture.mask_paths)
        paths["permission"] = invalid
        self.fixture.write_control(mask_paths=paths)
        with self.assertRaisesRegex(auditor.GoldenV2PixelAuditError, "only 0 and 255"):
            auditor.audit_candidate(
                self.fixture.candidate,
                self.fixture.baseline,
                self.fixture.control,
            )

    def test_control_paths_and_binding_sets_are_strict(self) -> None:
        control = json.loads(self.fixture.control.read_text(encoding="utf-8"))
        control["masks"]["permission"]["path"] = "../permission.png"
        self.fixture.control.write_text(json.dumps(control), encoding="utf-8")
        with self.assertRaisesRegex(
            auditor.GoldenV2PixelAuditError, "normalized relative POSIX"
        ):
            auditor.load_audit_control(self.fixture.control)

        self.fixture.write_control()
        with self.assertRaisesRegex(
            auditor.GoldenV2PixelAuditError, "exact semantic-name"
        ):
            auditor.audit_candidate(
                self.fixture.candidate,
                self.fixture.baseline,
                self.fixture.control,
                mask_bindings={"permission": self.fixture.mask_paths["permission"]},
            )


if __name__ == "__main__":
    unittest.main()
