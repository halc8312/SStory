from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts/map-production"
sys.path.insert(0, str(SCRIPT_DIR))


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V20 = load(
    "candidate_k3_field_margin_cleanup_v20_builder",
    "build_style_candidate_k3_field_margin_cleanup_v20.py",
)
from release_bound_artifact import bind_file  # noqa: E402


class CandidateK3FieldMarginCleanupV20Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        V20.TEMP_PARENT.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(
            prefix="v20-field-margin-test-", dir=V20.TEMP_PARENT
        )
        cls.root = Path(cls.temporary.name)
        cls.controls = V20.derive_v20_controls()

        with Image.open(V20.V18_REFERENCE) as opened:
            v19 = np.asarray(opened.convert("RGB"), np.uint8).copy()
        ys, xs = np.nonzero(cls.controls["masks"]["highland_edit"])
        y, x = int(ys[len(ys) // 2]), int(xs[len(xs) // 2])
        v19[y, x, 0] = np.uint8((int(v19[y, x, 0]) + 1) % 256)
        cls.v19_path = cls.root / "synthetic-highland-only-v19.png"
        Image.fromarray(v19, "RGB").save(cls.v19_path, **V20.PNG_OPTIONS)
        cls.v19_sha256 = V20.sha256(cls.v19_path)
        cls.output_root = cls.root / "proof-v20"
        cls.receipt = V20.build_temporary_v20(
            v19_path=cls.v19_path,
            expected_v19_sha256=cls.v19_sha256,
            output_root=cls.output_root,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_exact_permission_and_canonical_alpha_contract(self) -> None:
        controls = self.controls
        masks = controls["masks"]
        permission = controls["permission"]
        alpha = controls["alpha"]
        distance = controls["inward_distance"]
        self.assertEqual(int(masks["field_legacy_margin_scope"].sum()), 43_045)
        self.assertEqual(int(permission.sum()), 40_583)
        self.assertEqual(controls["alpha_counts"], {
            "positive": 37_369,
            "full": 27_997,
            "partial": 9_372,
        })
        np.testing.assert_array_equal(
            permission,
            masks["field_legacy_margin_scope"]
            & ~masks["permission_exclusions"]["forest_highland_road_guard"]
            & ~masks["protected_features"],
        )
        self.assertFalse(np.any(alpha[~permission]))
        self.assertFalse(np.any(alpha[distance <= 2.0 + 1e-6]))
        self.assertTrue(np.all(alpha[permission & (distance >= 5.0 - 1e-6)] == 1.0))
        for forbidden in controls["forbidden"].values():
            self.assertEqual(int(np.count_nonzero(permission & forbidden)), 0)

    def test_build_is_temp_only_bound_and_passes_exact_approved_metrics(self) -> None:
        receipt = self.receipt
        self.assertEqual(receipt["status"], "passed-automated-pending-root-vision")
        self.assertTrue(receipt["temporary_review_only"])
        self.assertFalse(receipt["persistent_candidate_emitted"])
        self.assertFalse(receipt["golden_accepted"])
        self.assertEqual(receipt["v19_input"]["expected_sha256"], self.v19_sha256)
        self.assertEqual(receipt["v19_input"]["actual_sha256"], self.v19_sha256)
        self.assertTrue(all(receipt["automated_gates"].values()))
        self.assertEqual(receipt["failed_gates"], [])

        identity = receipt["metrics"]["identity"]
        self.assertEqual(identity["actual_change_pixels"], 36_676)
        for name, count in identity.items():
            if name == "actual_change_pixels":
                continue
            self.assertEqual(count, 0, name)

        cadence = receipt["metrics"]["semantic"]["parcel_boundary_cadence"]
        self.assertEqual(cadence["baseline"]["total_small_comma_component_count"], 475)
        self.assertEqual(cadence["baseline"]["total_closed_loop_count"], 167)
        self.assertEqual(cadence["candidate"]["total_small_comma_component_count"], 349)
        self.assertEqual(cadence["candidate"]["total_closed_loop_count"], 36)
        self.assertFalse(cadence["candidate"]["immediate_row_detected"])
        self.assertLessEqual(
            cadence["candidate"]["maximum_dominant_nearest_spacing_share"],
            0.40,
        )
        self.assertLessEqual(
            cadence["candidate"]["maximum_closed_loop_count_per_parcel"], 12
        )

    def test_output_preserves_every_explicit_byte_lock(self) -> None:
        candidate_path = ROOT / self.receipt["artifacts"]["candidate"]["path"]
        with Image.open(self.v19_path) as opened:
            base = np.asarray(opened.convert("RGB"), np.uint8)
        with Image.open(candidate_path) as opened:
            result = np.asarray(opened.convert("RGB"), np.uint8)
        changed = np.any(result != base, axis=2)
        masks = self.controls["masks"]
        self.assertFalse(np.any(changed & ~self.controls["permission"]))
        self.assertFalse(np.any(changed & masks["field_parcel_edit"]))
        self.assertFalse(np.any(changed & masks["guards"]["field_boundaries"]))
        self.assertFalse(np.any(
            changed & masks["permission_exclusions"]["forest_highland_road_guard"]
        ))
        self.assertFalse(np.any(changed & masks["agricultural_corridor_envelope"]))
        self.assertFalse(np.any(changed & masks["guards"]["capital"]))
        self.assertFalse(np.any(changed & masks["protected_features"]))
        self.assertFalse(np.any(changed & ~masks["field_parcel_legacy_edit"]))

    def test_receipt_binds_candidate_masks_and_eight_vision_contacts(self) -> None:
        artifacts = self.receipt["artifacts"]
        contacts = [key for key in artifacts if key.startswith("contact:")]
        self.assertEqual(len(contacts), 8)
        self.assertIn("contact:full_25", artifacts)
        self.assertIn("contact:full_50", artifacts)
        for crop in ("west", "east", "south"):
            self.assertIn(f"contact:fields_{crop}_200", artifacts)
            self.assertIn(f"contact:fields_{crop}_400", artifacts)
        for record in artifacts.values():
            path = ROOT / record["path"]
            self.assertTrue(path.is_file())
            self.assertEqual(V20.sha256(path), record["sha256"])
        receipt_path = self.output_root / f"{V20.STEM}.provenance-receipt.json"
        persisted = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted, self.receipt)
        self.assertTrue(self.receipt["vision_handoff"]["required"])
        self.assertTrue(
            self.receipt["vision_handoff"]
            ["candidate_must_not_be_promoted_before_acceptance"]
        )

    def test_persistent_audit_rechecks_v20_without_claiming_acceptance(self) -> None:
        candidate_path = ROOT / self.receipt["artifacts"]["candidate"]["path"]
        raw_path = self.root / "persistent-audit-raw-copy.png"
        raw_path.write_bytes(candidate_path.read_bytes())
        image_sha256 = V20.sha256(candidate_path)
        donor_slot = V20.k3.load_spec()["donor_slots"]["fields"]
        authority_paths = {
            "k3-source": V20.k3.SOURCE,
            "k3-spec": V20.k3.SPEC,
            "reference-b1": V20.k3_audit.k2_audit.B1_REFERENCE,
            "reference-h4": V20.k3_audit.k2_audit.H4_REFERENCE,
            "geometry-guide": V20.k3_audit.k2_audit.GUIDE,
            "fields-donor": ROOT / donor_slot["path"],
            "fields-donor-prompt": ROOT / donor_slot["prompt_path"],
            "audit-h4-code": Path(V20.k3_audit.h4.__file__),
            "audit-h17-code": Path(V20.k3_audit.h17.__file__),
            "audit-k2-code": Path(V20.k3_audit.k2_audit.__file__),
            "audit-v20-code": Path(V20.__file__),
            "audit-k3-code": Path(V20.k3.__file__),
            "audit-k3-main-code": Path(V20.k3_audit.__file__),
        }
        authority_bindings = {
            role: bind_file(path, label=f"test audit authority {role}")
            for role, path in authority_paths.items()
        }
        report = V20.k3_audit.persistent_v20_audit(
            raw_path=raw_path,
            final_path=candidate_path,
            v19_path=self.v19_path,
            raw_artifact={"path": V20.relative(raw_path), "sha256": image_sha256},
            final_artifact={
                "path": V20.relative(candidate_path),
                "sha256": image_sha256,
            },
            normalized_receipt={
                "path": "world/map-production/prompts/synthetic-test-receipt.json",
                "sha256": "1" * 64,
            },
            source_receipt_sha256="2" * 64,
            source_receipt=self.receipt,
            authorized_by="unit test",
            authority_bindings=authority_bindings,
            artifact_bindings={
                "raw": bind_file(raw_path, label="test raw snapshot", trackable=False),
                "final": bind_file(candidate_path, label="test final snapshot", trackable=False),
                "v19": bind_file(self.v19_path, label="test v19 snapshot", trackable=False),
            },
            reported_authorities={
                role: binding.artifact()
                for role, binding in authority_bindings.items()
            },
        )
        self.assertEqual(report["status"], "passed")
        self.assertFalse(report["decision_authority"])
        self.assertFalse(report["acceptance_inferred"])
        self.assertFalse(report["golden_accepted"])
        self.assertEqual(report["failed_gates"], [])

    def test_bad_hash_and_non_temp_output_fail_closed(self) -> None:
        with self.assertRaisesRegex(V20.V20FieldMarginError, "SHA-256 mismatch"):
            V20._load_v19_base(self.v19_path, "0" * 64, self.controls)
        with tempfile.TemporaryDirectory() as outside:
            with self.assertRaisesRegex(V20.V20FieldMarginError, "must stay below"):
                V20.validate_temp_path(Path(outside) / "proof", directory=True)

    def test_claimed_v19_change_outside_highland_is_rejected(self) -> None:
        with Image.open(V20.V18_REFERENCE) as opened:
            invalid = np.asarray(opened.convert("RGB"), np.uint8).copy()
        ys, xs = np.nonzero(self.controls["masks"]["forest_edit"])
        y, x = int(ys[len(ys) // 2]), int(xs[len(xs) // 2])
        invalid[y, x, 1] = np.uint8((int(invalid[y, x, 1]) + 1) % 256)
        path = self.root / "invalid-v19-forest-change.png"
        Image.fromarray(invalid, "RGB").save(path, **V20.PNG_OPTIONS)
        with self.assertRaisesRegex(V20.V20FieldMarginError, "outside the highland"):
            V20._load_v19_base(path, V20.sha256(path), self.controls)

    def test_existing_outputs_require_explicit_replace(self) -> None:
        with self.assertRaisesRegex(V20.V20FieldMarginError, "refusing to overwrite"):
            V20.build_temporary_v20(
                v19_path=self.v19_path,
                expected_v19_sha256=self.v19_sha256,
                output_root=self.output_root,
            )


if __name__ == "__main__":
    unittest.main()
