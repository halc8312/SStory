from __future__ import annotations

import importlib.util
import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
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


K3 = load("candidate_k3_semantic_cleanup_builder", "build_style_candidate_k3_semantic_cleanup.py")
AUDIT = load("candidate_k3_semantic_cleanup_audit", "audit_style_candidate_k3_semantic_cleanup.py")


class CandidateK3SemanticCleanupPreflightTest(unittest.TestCase):
    def _frozen_v18(self) -> np.ndarray:
        self.assertTrue(K3.TEMP_FINAL.is_file())
        self.assertEqual(
            K3.sha256(K3.TEMP_FINAL),
            "013320af2f3296200a7d0b179e3a495f1e7905462213a6c645d85669dec02882",
        )
        return np.asarray(Image.open(K3.TEMP_FINAL).convert("RGB"), np.uint8)

    def _forced_flat_highland_candidate(
        self,
    ) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
        baseline = self._frozen_v18()
        masks = K3.derive_masks()
        permission = masks["highland_edit"]
        measurement = AUDIT.highland_fully_editable_support(masks)
        baseline_lab = cv2.cvtColor(baseline, cv2.COLOR_RGB2LAB)
        median_lab = np.rint(np.median(baseline_lab[measurement], axis=0)).astype(
            np.uint8
        )
        flat_lab = np.empty_like(baseline_lab)
        flat_lab[:] = median_lab
        flat_rgb = cv2.cvtColor(flat_lab, cv2.COLOR_LAB2RGB)
        alpha = K3.boundary_locked_alpha(
            permission,
            full_by_px=K3.HIGHLAND_ALPHA_FULL_BY_PX,
            locked_boundary_px=K3.HIGHLAND_ALPHA_LOCKED_BOUNDARY_PX,
        )
        rendered = K3.composite_with_alpha(baseline, flat_rgb, alpha)
        candidate = baseline.copy()
        candidate[permission] = rendered[permission]
        return candidate, baseline, masks

    def test_source_and_new_id_spec_are_locked_while_output_is_held(self) -> None:
        self.assertEqual(K3.sha256(K3.SOURCE), K3.EXPECTED_SOURCE)
        spec = K3.load_spec()
        self.assertEqual(spec["id"], "style-candidate-k-v3-semantic-cleanup")
        self.assertEqual(spec["status"], "prepared-donors-locked-output-held")
        self.assertFalse(spec["output_authorized"])
        self.assertTrue(all(item["status"] == "ready" for item in spec["donor_slots"].values()))
        self.assertEqual(spec["donor_slots"]["forest"]["registration_crop_xyxy"], [300, 0, 1020, 440])
        self.assertEqual(spec["donor_slots"]["highland"]["registration_crop_xyxy"], [930, 0, 1536, 560])
        self.assertEqual(
            spec["donor_slots"]["highland"]["sha256"],
            "c30fd2f4fc3774148b48a6380522c532fe33c4bf54b6100eaa5160fd9b9e1cfd",
        )
        self.assertTrue(spec["donor_slots"]["highland"]["path"].endswith("highland-planar-v4.png"))
        self.assertNotIn("highland-planar-v3-rejected", json.dumps(spec))
        self.assertEqual(spec["donor_slots"]["fields"]["registration_crop_xyxy"], [940, 470, 1536, 980])
        self.assertTrue(
            spec["style_calibration"]["spatial_pixel_reassignment_forbidden"]
        )
        self.assertTrue(
            spec["style_calibration"]["cdf_or_exact_multiset_remap_forbidden"]
        )
        self.assertNotIn("style-candidate-k-v2", K3.RAW.name)
        self.assertNotIn("style-candidate-k-v2", K3.FINAL.name)
        self.assertEqual(K3.HIGHLAND_ALPHA_LOCKED_BOUNDARY_PX, 2.0)
        self.assertEqual(K3.HIGHLAND_ALPHA_FULL_BY_PX, 5.0)

    def test_edit_union_is_only_three_semantics_and_disjoint_from_every_guard(self) -> None:
        masks = K3.derive_masks()
        expected = masks["forest_edit"] | masks["highland_edit"] | masks["fields_edit"]
        np.testing.assert_array_equal(masks["edit_union"], expected)
        self.assertEqual(len(masks["field_edits"]), 8)
        self.assertTrue(all(int(item.sum()) > 0 for item in masks["field_edits"]))
        parcel_union = np.logical_or.reduce(masks["field_edits"])
        np.testing.assert_array_equal(masks["field_parcel_edit"], parcel_union)
        np.testing.assert_array_equal(
            masks["fields_edit"],
            parcel_union,
        )
        self.assertEqual(masks["field_strict_interior_erosion_px"], 12)
        self.assertEqual(len(masks["field_legacy_edits"]), 8)
        for strict, legacy in zip(masks["field_edits"], masks["field_legacy_edits"]):
            np.testing.assert_array_equal(strict, K3.erode(legacy, 12))
        self.assertEqual(
            [int(item.sum()) for item in masks["field_edits"]],
            [8356, 8063, 6743, 5729, 8534, 4568, 7788, 7748],
        )
        self.assertEqual(int(masks["field_parcel_legacy_edit"].sum()), 100574)
        self.assertEqual(int(masks["field_parcel_edit"].sum()), 57529)
        self.assertEqual(int(masks["field_legacy_margin_scope"].sum()), 43045)
        corridor = masks["agricultural_corridor_envelope"]
        self.assertGreater(int(corridor.sum()), 0)
        self.assertEqual(int(np.count_nonzero(corridor & parcel_union)), 0)
        self.assertEqual(int(np.count_nonzero(corridor & masks["guards"]["roads"])), 0)
        self.assertEqual(int(np.count_nonzero(corridor & masks["guards"]["field_boundaries"])), 0)
        self.assertEqual(int(np.count_nonzero(corridor & masks["protected_features"])), 0)
        self.assertTrue(np.all(masks["field_labels"][corridor] == 9))
        eligible_agriculture = masks["agricultural_envelope"].copy()
        for guard in masks["guards"].values():
            eligible_agriculture &= ~guard
        np.testing.assert_array_equal(
            masks["field_channel_legacy_scope"], eligible_agriculture
        )
        self.assertEqual(int(masks["field_channel_legacy_scope"].sum()), 102051)
        self.assertEqual(int(masks["field_restore_scope"].sum()), 44522)
        np.testing.assert_array_equal(
            masks["field_restore_scope"],
            masks["field_legacy_margin_scope"] | corridor,
        )
        self.assertEqual(
            int(np.count_nonzero(
                masks["fields_edit"] & masks["agricultural_corridor_envelope"]
            )),
            0,
        )
        wide_road_guard = masks["permission_exclusions"]["forest_highland_road_guard"]
        self.assertEqual(int(np.count_nonzero(masks["forest_edit"] & wide_road_guard)), 0)
        self.assertEqual(int(np.count_nonzero(masks["highland_edit"] & wide_road_guard)), 0)
        self.assertEqual(int(np.count_nonzero(masks["fields_edit"] & wide_road_guard)), 0)
        self.assertEqual(
            int(np.count_nonzero(
                masks["fields_edit"]
                & masks["permission_exclusions"]["field_exact_road_core"]
            )),
            0,
        )
        self.assertEqual(
            sorted(int(value) for value in np.unique(masks["field_labels"]) if value),
            list(range(1, 10)),
        )
        for name, guard in masks["guards"].items():
            self.assertEqual(int(np.count_nonzero(masks["edit_union"] & guard)), 0, name)
        self.assertEqual(int(np.count_nonzero(masks["edit_union"] & masks["protected_features"])), 0)
        np.testing.assert_array_equal(masks["outside_identity"], ~masks["edit_union"])

    def test_prepare_is_deterministic_and_emits_no_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = K3.prepare(root)
            first_bytes = (root / "style-candidate-k-v3-semantic-cleanup-preflight.json").read_bytes()
            second = K3.prepare(root)
            second_bytes = (root / "style-candidate-k-v3-semantic-cleanup-preflight.json").read_bytes()
            self.assertEqual(first, second)
            self.assertEqual(first_bytes, second_bytes)
            self.assertEqual(first["status"], "prepared-donors-locked-output-held")
            self.assertTrue(first["all_donors_ready"])
            self.assertFalse(first["candidate_output_authorized"])
            self.assertFalse(first["candidate_emitted"])
            self.assertEqual(first["mask_contract"]["protected_overlap_pixels"], 0)
            self.assertEqual(first["mask_contract"]["field_parcel_count"], 8)
            self.assertGreater(first["mask_contract"]["agricultural_corridor_envelope_pixels"], 0)
            self.assertEqual(first["mask_contract"]["quiet_field_region_count"], 9)
            self.assertTrue(all(not exists for exists in first["future_outputs_exist"].values()))

    def test_persistent_output_and_default_audit_paths_remain_fail_closed(self) -> None:
        with self.assertRaisesRegex(K3.K3BuildError, "output is held"):
            K3.build_candidate(allow_output=False)
        with self.assertRaisesRegex(K3.K3BuildError, "persistent K3 raster writing remains intentionally disabled"):
            K3.build_candidate(allow_output=True)
        with self.assertRaisesRegex(AUDIT.K3AuditError, "persistent K3 candidate is intentionally absent"):
            AUDIT.audit_candidate(K3.FINAL)

    def test_closed_forest_icons_are_detected(self) -> None:
        masks = K3.derive_masks()
        image = np.full((K3.HEIGHT, K3.WIDTH, 3), 160, np.uint8)
        for center in ((520, 120), (610, 185), (720, 240)):
            cv2.circle(image, center, 7, (70, 60, 45), 2, cv2.LINE_8)
        result = AUDIT.closed_icon_proxy(image, masks["forest_edit"])
        self.assertFalse(result["passed"])
        self.assertGreater(result["closed_loop_tree_cell_icon_count"], 0)

    def test_highland_parallel_dash_bundle_is_detected(self) -> None:
        masks = K3.derive_masks()
        image = np.full((K3.HEIGHT, K3.WIDTH, 3), 160, np.uint8)
        for y in (180, 186, 192):
            cv2.line(image, (1160, y), (1168, y + 3), (70, 60, 45), 1, cv2.LINE_8)
        result = AUDIT.dash_bundle_proxy(image, masks["highland_edit"])
        self.assertFalse(result["passed"])
        self.assertGreater(result["parallel_multi_stroke_bundle_pair_count"], 0)

    def test_highland_semantic_full_alpha_support_excludes_forced_boundary_false_positive(self) -> None:
        candidate, _, masks = self._forced_flat_highland_candidate()
        whole_permission = AUDIT.dash_bundle_proxy(
            candidate, masks["highland_edit"]
        )
        self.assertFalse(whole_permission["passed"])
        self.assertGreater(
            whole_permission["parallel_multi_stroke_bundle_pair_count"], 0
        )

        highland = AUDIT.semantic_cleanup_metrics(candidate, masks)["highland"]
        self.assertEqual(
            highland["measurement"],
            {
                "method": (
                    "boundary_locked_alpha(highland_edit, full_by_px=5.0, "
                    "locked_boundary_px=2.0) == 1.0"
                ),
                "alpha_function": "k3.boundary_locked_alpha",
                "locked_boundary_px": 2.0,
                "full_by_px": 5.0,
                "required_alpha_value": 1.0,
                "pixels": int(
                    AUDIT.highland_fully_editable_support(masks).sum()
                ),
                "reason": (
                    "Exactly matches the production highland alpha==1 support; "
                    "locked and fractional transition pixels are excluded while "
                    "every fully editable pixel remains measured."
                ),
            },
        )
        self.assertGreaterEqual(
            highland["quiet_fraction"], highland["minimum_quiet_fraction"]
        )
        self.assertEqual(highland["minimum_quiet_fraction"], 0.85)
        self.assertEqual(highland["dash_bundle_proxy"]["threshold"], 0)
        self.assertEqual(
            highland["orientation_substrate_proxy"]["maximum"], 0.22
        )
        self.assertEqual(
            highland["dash_bundle_proxy"][
                "parallel_multi_stroke_bundle_pair_count"
            ],
            0,
        )
        self.assertTrue(highland["orientation_substrate_proxy"]["passed"])
        self.assertTrue(highland["passed"])

    def test_highland_semantic_full_alpha_support_still_rejects_frozen_v18_weave(self) -> None:
        v18 = self._frozen_v18()
        masks = K3.derive_masks()
        highland = AUDIT.semantic_cleanup_metrics(v18, masks)["highland"]
        self.assertEqual(highland["measurement"]["full_by_px"], 5.0)
        self.assertLess(
            highland["quiet_fraction"], highland["minimum_quiet_fraction"]
        )
        self.assertGreater(
            highland["dash_bundle_proxy"][
                "parallel_multi_stroke_bundle_pair_count"
            ],
            0,
        )
        self.assertFalse(highland["passed"])

    def test_highland_semantic_measurement_equals_production_alpha_full_support(self) -> None:
        masks = K3.derive_masks()
        alpha = K3.boundary_locked_alpha(
            masks["highland_edit"],
            full_by_px=K3.HIGHLAND_ALPHA_FULL_BY_PX,
            locked_boundary_px=K3.HIGHLAND_ALPHA_LOCKED_BOUNDARY_PX,
        )
        expected = alpha == np.float32(1.0)
        actual = AUDIT.highland_fully_editable_support(masks)
        np.testing.assert_array_equal(actual, expected)
        self.assertEqual(int(actual.sum()), int(np.count_nonzero(alpha == 1.0)))
        self.assertEqual(int(np.count_nonzero(actual & (alpha != 1.0))), 0)

    def test_highland_semantic_detects_dash_bundle_inside_full_alpha_support(self) -> None:
        candidate, _, masks = self._forced_flat_highland_candidate()
        support = AUDIT.highland_fully_editable_support(masks)
        patch: tuple[int, int] | None = None
        for y in range(12, K3.HEIGHT - 12):
            row = support[y - 8 : y + 9].all(axis=0)
            run = 0
            for x, allowed in enumerate(row):
                run = run + 1 if allowed else 0
                if run >= 24:
                    patch = (x - 23, y)
                    break
            if patch is not None:
                break
        self.assertIsNotNone(patch)
        left, center_y = patch
        for offset in (-6, 0, 5):
            cv2.line(
                candidate,
                (left + 4, center_y + offset),
                (left + 12, center_y + offset + 3),
                (70, 60, 45),
                1,
                cv2.LINE_8,
            )
        highland = AUDIT.semantic_cleanup_metrics(candidate, masks)["highland"]
        self.assertGreater(
            highland["dash_bundle_proxy"][
                "parallel_multi_stroke_bundle_pair_count"
            ],
            0,
        )
        self.assertFalse(highland["dash_bundle_proxy"]["passed"])
        self.assertFalse(highland["passed"])

    def test_highland_semantic_full_alpha_audit_preserves_outside_and_protected_bytes(self) -> None:
        candidate, baseline, masks = self._forced_flat_highland_candidate()
        before_audit = candidate.copy()
        AUDIT.semantic_cleanup_metrics(candidate, masks)
        np.testing.assert_array_equal(candidate, before_audit)

        changed = np.any(candidate != baseline, axis=2)
        self.assertEqual(
            int(np.count_nonzero(changed & ~masks["highland_edit"])), 0
        )
        self.assertEqual(
            int(np.count_nonzero(changed & masks["protected_features"])), 0
        )
        for name, guard in masks["guards"].items():
            self.assertEqual(int(np.count_nonzero(changed & guard)), 0, name)

    def test_field_rows_and_continuous_furrows_are_detected(self) -> None:
        masks = K3.derive_masks()
        image = np.full((K3.HEIGHT, K3.WIDTH, 3), 160, np.uint8)
        for permission in masks["field_edits"]:
            ys, xs = np.nonzero(permission)
            for y in range(int(ys.min()), int(ys.max()) + 1, 7):
                eligible = np.nonzero(permission[y])[0]
                if len(eligible) >= 24:
                    cv2.line(image, (int(eligible.min()), y), (int(eligible.max()), y), (70, 60, 45), 1, cv2.LINE_8)
        result = AUDIT.field_metrics(image, masks["field_edits"])
        self.assertFalse(result["passed"])
        self.assertTrue(any(item["continuous_furrow_count"] > 0 for item in result["parcels"]))

    def test_agricultural_corridor_is_a_separate_strict_content_and_identity_region(self) -> None:
        masks = K3.derive_masks()
        corridor = masks["agricultural_corridor_envelope"]
        image = np.full((K3.HEIGHT, K3.WIDTH, 3), 160, np.uint8)
        ys = np.nonzero(corridor)[0]
        for y in range(int(ys.min()), int(ys.max()) + 1, 5):
            eligible = np.nonzero(corridor[y])[0]
            if len(eligible) >= 18:
                cv2.line(
                    image,
                    (int(eligible.min()), y),
                    (int(eligible.max()), y),
                    (65, 58, 43),
                    1,
                    cv2.LINE_8,
                )
        content = AUDIT.strict_content_metrics(image, masks)
        self.assertIn("agricultural_corridor_envelope", content)
        self.assertFalse(content["agricultural_corridor_envelope"]["passed"])

        identity = AUDIT._identity_metrics(K3.validate_source().copy(), masks)
        self.assertIn("agricultural_corridor_envelope", identity["replacement_fraction"])
        self.assertIn("agricultural_corridor_envelope", identity["boundary"])

    def test_low_frequency_blotch_gate_v1_accepts_k2_and_rejects_frozen_v10(self) -> None:
        masks = K3.derive_masks()
        baseline = AUDIT.low_frequency_blotch_metrics(K3.validate_source(), masks)
        self.assertTrue(baseline["passed"])
        self.assertTrue(all(item["passed"] for item in baseline["regions"]))

        v10 = ROOT / "tmp/map-production/k3-semantic-cleanup-proof-v10/style-candidate-k-v3-semantic-cleanup-proof-v10.png"
        self.assertTrue(v10.is_file())
        self.assertEqual(
            K3.sha256(v10),
            "d1c835e62ec7e9c2f7f42709aa1600ee42c0ddcc98f02d41daf3a1f1449feb24",
        )
        rejected = AUDIT.low_frequency_blotch_metrics(
            np.asarray(Image.open(v10).convert("RGB"), np.uint8), masks
        )
        self.assertFalse(rejected["passed"])
        failed_fields = [
            item for item in rejected["regions"]
            if item["region"].startswith("parcel_") and not item["passed"]
        ]
        self.assertEqual(len(failed_fields), 8)

    def test_v18_fields_use_only_same_coordinate_continuous_transform(self) -> None:
        source = inspect.getsource(K3.procedural_fields_canvas)
        for forbidden in (
            "np.argsort",
            "np.sort(",
            "np.quantile",
            "rank_scalar",
            "target_order",
            "source_order",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("inner - outer", source)
        self.assertIn('"spatial_pixel_reassignment_used": False', source)
        self.assertIn('"sorting_or_distribution_remap_used": False', source)

        build_source = inspect.getsource(K3.build_temporary_proof)
        self.assertNotIn("procedural_fields_canvas(", build_source)
        self.assertIn("fields_canvas = v17.copy()", build_source)
        self.assertIn(
            'result[masks["field_parcel_edit"]] = fields_canvas',
            build_source,
        )
        self.assertNotIn("boundary_local_rgb_match(", build_source)

    def test_v18_identity_gate_locks_strict_v17_carry_and_k2_restore_scope(self) -> None:
        masks = K3.derive_masks()
        base = K3.validate_source()
        self.assertEqual(K3.sha256(K3.V17_PROOF), K3.EXPECTED_V17_PROOF)
        v17 = np.asarray(Image.open(K3.V17_PROOF).convert("RGB"), np.uint8)
        candidate = v17.copy()
        candidate[masks["field_restore_scope"]] = base[masks["field_restore_scope"]]

        identity = AUDIT._identity_metrics(candidate, masks)
        self.assertTrue(identity["passed"])
        self.assertTrue(identity["field_channel_outside_strict_k2_exact"])
        self.assertTrue(identity["frozen_v17"]["strict_field_interiors_exact"])
        self.assertEqual(
            identity["frozen_v17"]["differing_pixels_outside_restore_scope"],
            0,
        )
        self.assertGreater(
            identity["frozen_v17"]["differing_pixels_inside_restore_scope"],
            0,
        )
        self.assertEqual(identity["boundary"]["fields"]["median_channel_delta"], 0)
        self.assertEqual(identity["boundary"]["fields"]["p95_channel_delta"], 0)

    def test_v18_dark_row_components_are_covered_and_protected_cores_stay_excluded(self) -> None:
        masks = K3.derive_masks()
        raw = masks["agricultural_approach_dark_components_raw"]
        eligible = masks["agricultural_approach_dark_components"]
        corridor = masks["agricultural_corridor_envelope"]
        self.assertEqual(int(raw.sum()), 251)
        self.assertEqual(int(eligible.sum()), 225)
        self.assertEqual(int(np.count_nonzero(eligible & ~corridor)), 0)

        count, labels, _, _ = cv2.connectedComponentsWithStats(
            raw.astype(np.uint8), 8
        )
        self.assertEqual(count - 1, 10)
        self.assertTrue(all(
            int(np.count_nonzero(eligible & (labels == component))) > 0
            for component in range(1, count)
        ))
        uncovered = raw & ~corridor
        np.testing.assert_array_equal(uncovered, raw & masks["guards"]["roads"])
        self.assertEqual(int(np.count_nonzero(corridor & masks["guards"]["roads"])), 0)
        self.assertEqual(
            int(np.count_nonzero(corridor & masks["guards"]["field_boundaries"])), 0
        )
        self.assertEqual(int(corridor.sum()), 1477)
        corridor_count, _, _, _ = cv2.connectedComponentsWithStats(
            corridor.astype(np.uint8), 8
        )
        self.assertEqual(corridor_count - 1, 4)

    def test_v18_corridor_is_exact_k2_without_plate_inpaint_or_blur(self) -> None:
        source = inspect.getsource(K3.agricultural_corridor_canvas)
        for forbidden in (
            "donor_source",
            "Image.fromarray",
            ".resize(",
            "np.linalg.lstsq",
            "np.quantile",
            "np.argsort",
            "boundary_local_rgb_match",
            "medianBlur",
            "bilateralFilter",
            "GaussianBlur",
            "inpaint(",
        ):
            self.assertNotIn(forbidden, source)

        masks = K3.derive_masks()
        base = K3.validate_source()
        canvas, record = K3.agricultural_corridor_canvas(
            base,
            masks["agricultural_corridor_envelope"],
        )
        np.testing.assert_array_equal(canvas, base)
        self.assertEqual(record["actual_canvas_change_pixels"], 0)
        self.assertEqual(record["actual_canvas_change_outside_permission_pixels"], 0)
        self.assertEqual(record["k2_exact_pixels"], int(masks["agricultural_corridor_envelope"].sum()))
        self.assertFalse(record["plate_used"])
        self.assertFalse(record["inpaint_used"])
        self.assertFalse(record["blur_used"])
        self.assertFalse(record["spatial_pixel_reassignment_used"])
        self.assertFalse(record["sorting_or_distribution_remap_used"])
        self.assertFalse(record["global_affine_plate_used"])


if __name__ == "__main__":
    unittest.main()
