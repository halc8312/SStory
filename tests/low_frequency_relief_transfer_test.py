from __future__ import annotations

import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts/map-production"
sys.path.insert(0, str(SCRIPT_DIR))
MODULE_PATH = SCRIPT_DIR / "transfer_low_frequency_relief.py"
SPEC = importlib.util.spec_from_file_location("low_frequency_relief_transfer", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class LowFrequencyReliefTransferTest(unittest.TestCase):
    def _control(self) -> dict:
        return {
            "schema_version": "1.0.0",
            "canvas": {"width": 256, "height": 256},
            "include_polygons": [
                {
                    "id": "mountain",
                    "points": [[0, 0], [255, 0], [255, 255], [0, 255]],
                    "feather_inside_px": 0,
                }
            ],
            "exclude_strokes": [
                {
                    "id": "road",
                    "points": [[12, 128], [244, 128]],
                    "width": 12,
                    "feather_px": 4,
                }
            ],
            "feather_inside_px": 0,
        }

    def _contract(self) -> dict:
        return {
            "inner_gaussian_radius_px": 12,
            "outer_gaussian_radius_px": 48,
            "robust_window_median_px": 128,
            "robust_sample_stride_px": 64,
            "robust_coarse_median_size": 3,
            # Two production cells equal 128 px; 0.5 cells is the scale-equivalent
            # setting for this 256 px fixture.
            "robust_coarse_gaussian_radius_cells": 0.5,
            "final_quantized_median_size": 5,
            "input_difference_clip_levels": 96,
            "road_signal_guard_width_px": 64,
            "target_q90_q10_levels": 7,
            "minimum_raw_q90_q10_levels": 3,
            "maximum_normalization_gain": 2,
            "maximum_absolute_delta_levels": 6,
            "region_core_minimum_mask_value": 255,
            "trace_threshold_levels": 3,
            "trace_minimum_span_px": 128,
            "trace_maximum_covariance_ratio": 10,
            "trace_severe_covariance_ratio": 40,
            "trace_covariance_maximum_bbox_occupancy": 0.5,
            "trace_maximum_compactness": 18,
            "trace_maximum_bbox_occupancy": 0.3,
        }

    def _direct_contract(self) -> dict:
        contract = self._contract()
        contract.update(
            {
                "signal_mode": "luminance_delta_plate",
                "relief_method": "direct_plate",
                "direct_plate_gaussian_radius_px": 32,
                "required_input_plate_q90_q10_levels": [1, 255],
            }
        )
        return contract

    def _generated(self, *, global_cast: int = 0, add_dashes: bool = False) -> Image.Image:
        broad = Image.new("L", (256, 256), 128 + global_cast)
        draw = ImageDraw.Draw(broad)
        draw.ellipse((18, 18, 154, 150), fill=176 + global_cast)
        draw.ellipse((112, 92, 244, 238), fill=80 + global_cast)
        broad = broad.filter(ImageFilter.GaussianBlur(radius=28))
        if add_dashes:
            draw = ImageDraw.Draw(broad)
            for x in range(24, 224, 18):
                draw.line((x, 72, x + 8, 72), fill=20, width=2)
        return broad

    def _assert_integer_sequences_equal(
        self,
        expected: list[int],
        actual: list[int],
    ) -> None:
        self.assertEqual(
            len(expected),
            len(actual),
            "integer sequence lengths differ",
        )
        mismatch_count = 0
        first_mismatch: tuple[int, int, int] | None = None
        maximum_absolute_delta = 0
        for index, (expected_value, actual_value) in enumerate(zip(expected, actual)):
            if expected_value == actual_value:
                continue
            mismatch_count += 1
            if first_mismatch is None:
                first_mismatch = (index, expected_value, actual_value)
            maximum_absolute_delta = max(
                maximum_absolute_delta,
                abs(expected_value - actual_value),
            )
        if mismatch_count:
            assert first_mismatch is not None
            index, expected_value, actual_value = first_mismatch
            self.fail(
                "integer sequences differ at "
                f"{mismatch_count} positions; first mismatch at index {index}: "
                f"{expected_value} != {actual_value}; maximum absolute delta "
                f"is {maximum_absolute_delta}"
            )

    def test_constant_color_cast_is_removed_before_transfer(self) -> None:
        base = Image.new("L", (256, 256), 128)
        without_cast = self._generated()
        with_cast = self._generated(global_cast=20)
        try:
            field_a, _, _, mask_a = MODULE.derive_field(
                base, without_cast, self._control(), self._contract()
            )
            field_b, _, _, mask_b = MODULE.derive_field(
                base, with_cast, self._control(), self._contract()
            )
        finally:
            base.close()
            without_cast.close()
            with_cast.close()
        try:
            self._assert_integer_sequences_equal(field_a, field_b)
        finally:
            mask_a.close()
            mask_b.close()

    def test_plate_mode_is_invariant_to_base_map_detail(self) -> None:
        flat_base = Image.new("L", (256, 256), 128)
        detailed_base = Image.new("L", (256, 256), 36)
        detailed_draw = ImageDraw.Draw(detailed_base)
        detailed_draw.rectangle((0, 0, 127, 255), fill=220)
        detailed_draw.line((0, 110, 255, 154), fill=8, width=40)
        generated = self._generated()
        contract = self._contract()
        contract["signal_mode"] = "luminance_delta_plate"
        contract["required_input_plate_q90_q10_levels"] = [1, 255]
        try:
            field_a, unmasked_a, metrics_a, mask_a = MODULE.derive_field(
                flat_base, generated, self._control(), contract
            )
            field_b, unmasked_b, metrics_b, mask_b = MODULE.derive_field(
                detailed_base, generated, self._control(), contract
            )
        finally:
            flat_base.close()
            detailed_base.close()
            generated.close()
        try:
            self._assert_integer_sequences_equal(field_a, field_b)
            self._assert_integer_sequences_equal(unmasked_a, unmasked_b)
            self.assertEqual(metrics_a, metrics_b)
            self.assertEqual(mask_a.tobytes(), mask_b.tobytes())
        finally:
            mask_a.close()
            mask_b.close()

    def test_plate_mode_removes_a_constant_plate_luminance_cast(self) -> None:
        base = Image.new("L", (256, 256), 128)
        without_cast = self._generated()
        with_cast = self._generated(global_cast=20)
        contract = self._contract()
        contract["signal_mode"] = "luminance_delta_plate"
        contract["required_input_plate_q90_q10_levels"] = [1, 255]
        try:
            field_a, unmasked_a, metrics_a, mask_a = MODULE.derive_field(
                base, without_cast, self._control(), contract
            )
            field_b, unmasked_b, metrics_b, mask_b = MODULE.derive_field(
                base, with_cast, self._control(), contract
            )
        finally:
            base.close()
            without_cast.close()
            with_cast.close()
        try:
            self._assert_integer_sequences_equal(field_a, field_b)
            self._assert_integer_sequences_equal(unmasked_a, unmasked_b)
            for region_a, region_b in zip(metrics_a, metrics_b):
                self.assertEqual(
                    region_a["input_plate_q90_q10_levels"],
                    region_b["input_plate_q90_q10_levels"],
                )
                self.assertEqual(
                    region_a["bandpass_q90_q10_levels"],
                    region_b["bandpass_q90_q10_levels"],
                )
                self.assertEqual(
                    region_a["final_q90_q10_levels"],
                    region_b["final_q90_q10_levels"],
                )
                self.assertEqual(
                    region_b["input_plate_q10_levels"]
                    - region_a["input_plate_q10_levels"],
                    20,
                )
                self.assertEqual(
                    region_b["input_plate_q90_levels"]
                    - region_a["input_plate_q90_levels"],
                    20,
                )
        finally:
            mask_a.close()
            mask_b.close()

    def test_direct_plate_is_invariant_to_base_map_detail(self) -> None:
        flat_base = Image.new("L", (256, 256), 128)
        detailed_base = Image.new("L", (256, 256), 36)
        detailed_draw = ImageDraw.Draw(detailed_base)
        detailed_draw.rectangle((0, 0, 127, 255), fill=220)
        detailed_draw.line((0, 110, 255, 154), fill=8, width=40)
        generated = self._generated()
        contract = self._direct_contract()
        try:
            field_a, unmasked_a, metrics_a, mask_a = MODULE.derive_field(
                flat_base, generated, self._control(), contract
            )
            field_b, unmasked_b, metrics_b, mask_b = MODULE.derive_field(
                detailed_base, generated, self._control(), contract
            )
        finally:
            flat_base.close()
            detailed_base.close()
            generated.close()
        try:
            self._assert_integer_sequences_equal(field_a, field_b)
            self._assert_integer_sequences_equal(unmasked_a, unmasked_b)
            self.assertEqual(metrics_a, metrics_b)
            self.assertEqual(mask_a.tobytes(), mask_b.tobytes())
        finally:
            mask_a.close()
            mask_b.close()

    def test_direct_plate_removes_a_constant_luminance_cast(self) -> None:
        base = Image.new("L", (256, 256), 128)
        without_cast = self._generated()
        with_cast = self._generated(global_cast=20)
        contract = self._direct_contract()
        try:
            field_a, unmasked_a, metrics_a, mask_a = MODULE.derive_field(
                base, without_cast, self._control(), contract
            )
            field_b, unmasked_b, metrics_b, mask_b = MODULE.derive_field(
                base, with_cast, self._control(), contract
            )
        finally:
            base.close()
            without_cast.close()
            with_cast.close()
        try:
            self._assert_integer_sequences_equal(field_a, field_b)
            self._assert_integer_sequences_equal(unmasked_a, unmasked_b)
            self.assertEqual(
                [
                    {key: value for key, value in metric.items() if not key.startswith("input_plate_q")}
                    for metric in metrics_a
                ],
                [
                    {key: value for key, value in metric.items() if not key.startswith("input_plate_q")}
                    for metric in metrics_b
                ],
            )
            self.assertEqual(mask_a.tobytes(), mask_b.tobytes())
        finally:
            mask_a.close()
            mask_b.close()

    def test_explicit_generated_minus_base_mode_preserves_legacy_results(self) -> None:
        base = Image.new("L", (256, 256), 128)
        generated = self._generated()
        legacy_contract = self._contract()
        explicit_contract = self._contract()
        explicit_contract["signal_mode"] = "generated_minus_base"
        try:
            field_a, unmasked_a, metrics_a, mask_a = MODULE.derive_field(
                base, generated, self._control(), legacy_contract
            )
            field_b, unmasked_b, metrics_b, mask_b = MODULE.derive_field(
                base, generated, self._control(), explicit_contract
            )
        finally:
            base.close()
            generated.close()
        try:
            self._assert_integer_sequences_equal(field_a, field_b)
            self._assert_integer_sequences_equal(unmasked_a, unmasked_b)
            self.assertEqual(metrics_a, metrics_b)
            self.assertEqual(mask_a.tobytes(), mask_b.tobytes())
        finally:
            mask_a.close()
            mask_b.close()

    def test_thin_dashes_are_not_copied_as_high_frequency_marks(self) -> None:
        base = Image.new("L", (256, 256), 128)
        generated = self._generated(add_dashes=True)
        try:
            field, unmasked, metrics, mask = MODULE.derive_field(
                base, generated, self._control(), self._contract()
            )
        finally:
            base.close()
            generated.close()
        try:
            display = Image.new("L", (256, 256))
            display.putdata([128 + value for value in field])
            softened = display.filter(ImageFilter.GaussianBlur(radius=4))
            residual = [
                field[index] - (value - 128)
                for index, value in enumerate(softened.get_flattened_data())
                if mask.getpixel((index % 256, index // 256)) == 255
            ]
            self.assertLessEqual(max(map(abs, residual)), 2)
            self.assertGreaterEqual(metrics[0]["final_q90_q10_levels"], 5)
            self.assertLessEqual(metrics[0]["final_q90_q10_levels"], 9)
            self.assertEqual(
                MODULE._traceable_components(
                    unmasked,
                    bytes([255]) * (256 * 256),
                    (256, 256),
                    self._contract(),
                ),
                [],
            )
            display.close()
            softened.close()
        finally:
            mask.close()

    def test_protected_road_core_receives_zero_delta(self) -> None:
        base = Image.new("L", (256, 256), 128)
        generated = self._generated()
        control = self._control()
        try:
            field, _, _, mask = MODULE.derive_field(
                base, generated, control, self._contract()
            )
        finally:
            base.close()
            generated.close()
        try:
            road_indices = MODULE._road_core_indices(control, (256, 256))
            self.assertTrue(road_indices)
            self.assertTrue(all(field[index] == 0 for index in road_indices))
        finally:
            mask.close()

    def test_direct_plate_excludes_road_signal_before_gaussian_smoothing(self) -> None:
        base = Image.new("L", (256, 256), 128)
        baseline = self._generated()
        with_road_signal = baseline.copy()
        ImageDraw.Draw(with_road_signal).line(
            (12, 128, 244, 128),
            fill=100,
            width=12,
        )
        control = self._control()
        contract = self._direct_contract()
        try:
            applied_a, unmasked_a, metrics_a, mask_a = MODULE.derive_field(
                base, baseline, control, contract
            )
            applied_b, unmasked_b, metrics_b, mask_b = MODULE.derive_field(
                base, with_road_signal, control, contract
            )
        finally:
            base.close()
            baseline.close()
            with_road_signal.close()
        try:
            self._assert_integer_sequences_equal(applied_a, applied_b)
            self._assert_integer_sequences_equal(unmasked_a, unmasked_b)
            self.assertEqual(metrics_a, metrics_b)
            self.assertEqual(mask_a.tobytes(), mask_b.tobytes())
        finally:
            mask_a.close()
            mask_b.close()

    def test_generated_road_line_cannot_leak_into_the_relief_field(self) -> None:
        base = Image.new("L", (256, 256), 128)
        baseline = self._generated()
        with_generated_road = baseline.copy()
        ImageDraw.Draw(with_generated_road).line((12, 128, 244, 128), fill=10, width=12)
        control = self._control()
        try:
            field_a, _, _, mask_a = MODULE.derive_field(
                base, baseline, control, self._contract()
            )
            field_b, _, _, mask_b = MODULE.derive_field(
                base, with_generated_road, control, self._contract()
            )
        finally:
            base.close()
            baseline.close()
            with_generated_road.close()
        try:
            self._assert_integer_sequences_equal(field_a, field_b)
        finally:
            mask_a.close()
            mask_b.close()

    def test_trace_gate_rejects_straight_winding_closed_and_seven_pixel_paths(self) -> None:
        size = (256, 256)
        core = bytes([255]) * (size[0] * size[1])
        cases = []

        straight = Image.new("L", size, 128)
        ImageDraw.Draw(straight).line((20, 64, 236, 64), fill=132, width=7)
        cases.append(straight)

        winding = Image.new("L", size, 128)
        ImageDraw.Draw(winding).line(
            [(16, 164), (64, 120), (112, 176), (168, 112), (240, 164)],
            fill=124,
            width=11,
            joint="curve",
        )
        cases.append(winding)

        ring = Image.new("L", size, 128)
        ImageDraw.Draw(ring).ellipse((36, 32, 220, 216), outline=132, width=12)
        cases.append(ring)

        broad_route = Image.new("L", size, 128)
        ImageDraw.Draw(broad_route).line((18, 220, 238, 108), fill=124, width=32)
        cases.append(broad_route)

        try:
            for image in cases:
                field = [value - 128 for value in image.get_flattened_data()]
                flagged = MODULE._traceable_components(
                    field,
                    core,
                    size,
                    self._contract(),
                )
                self.assertTrue(flagged)
        finally:
            for image in cases:
                image.close()

    def test_trace_gate_includes_feather_mask_pixels(self) -> None:
        size = (256, 256)
        field_image = Image.new("L", size, 128)
        ImageDraw.Draw(field_image).line((20, 8, 236, 8), fill=132, width=7)
        field = [value - 128 for value in field_image.get_flattened_data()]
        feather_only = bytearray(size[0] * size[1])
        for y in range(4, 13):
            for x in range(16, 241):
                feather_only[y * size[0] + x] = 64
        try:
            self.assertTrue(
                MODULE._traceable_components(
                    field,
                    bytes(feather_only),
                    size,
                    self._contract(),
                )
            )
        finally:
            field_image.close()

    def test_broad_areal_positive_fields_pass_the_trace_gate(self) -> None:
        base = Image.new("L", (256, 256), 128)
        positives = []

        overlapping = Image.new("L", (256, 256), 128)
        draw = ImageDraw.Draw(overlapping)
        draw.ellipse((10, 18, 170, 178), fill=184)
        draw.ellipse((86, 62, 244, 224), fill=76)
        positives.append(overlapping.filter(ImageFilter.GaussianBlur(radius=30)))
        overlapping.close()

        asymmetric = Image.new("L", (256, 256), 128)
        draw = ImageDraw.Draw(asymmetric)
        draw.polygon([(4, 30), (152, 8), (238, 88), (186, 180), (42, 232)], fill=176)
        draw.ellipse((112, 112, 252, 252), fill=82)
        positives.append(asymmetric.filter(ImageFilter.GaussianBlur(radius=34)))
        asymmetric.close()

        coarse = Image.new("L", (8, 8))
        coarse.putdata(
            [
                round(128 + 34 * math.sin((x + 1) * 0.83) * math.cos((y + 2) * 0.71))
                for y in range(8)
                for x in range(8)
            ]
        )
        random_areal = coarse.resize((256, 256), Image.Resampling.BICUBIC)
        positives.append(random_areal.filter(ImageFilter.GaussianBlur(radius=22)))
        coarse.close()
        random_areal.close()

        try:
            for generated in positives:
                _, unmasked, _, mask = MODULE.derive_field(
                    base,
                    generated,
                    self._control(),
                    self._contract(),
                )
                try:
                    flagged = MODULE._traceable_components(
                        unmasked,
                        bytes([255]) * (256 * 256),
                        (256, 256),
                        self._contract(),
                    )
                    self.assertEqual(flagged, [])
                finally:
                    mask.close()
        finally:
            base.close()
            for image in positives:
                image.close()

    def test_repository_v5_mask_is_byte_identical_to_reviewed_broad_mask(self) -> None:
        composite = MODULE._load_composite_module()
        controls = REPO_ROOT / "world/map-production/controls"
        old_control = composite.load_control(controls / "style-candidate-d-mountain-mask-v1.json")
        new_control = composite.load_control(controls / "style-candidate-d-v5-relief-mask-v1.json")
        old_mask = composite.build_mask(old_control)
        new_mask = composite.build_mask(new_control)
        try:
            self.assertEqual(old_mask.tobytes(), new_mask.tobytes())
        finally:
            old_mask.close()
            new_mask.close()

    def test_repository_e_v1_mask_is_byte_identical_to_v5_and_committed_png(self) -> None:
        composite = MODULE._load_composite_module()
        controls = REPO_ROOT / "world/map-production/controls"
        d_control = composite.load_control(controls / "style-candidate-d-v5-relief-mask-v1.json")
        e_control = composite.load_control(controls / "style-candidate-e-v1-relief-mask-v1.json")
        d_mask = composite.build_mask(d_control)
        e_mask = composite.build_mask(e_control)
        with Image.open(controls / "style-candidate-e-v1-relief-mask-v1.png") as opened:
            committed = opened.convert("L")
        try:
            self.assertEqual(d_mask.tobytes(), e_mask.tobytes())
            self.assertEqual(e_mask.tobytes(), committed.tobytes())
        finally:
            d_mask.close()
            e_mask.close()
            committed.close()

    def test_repository_f_v2_mask_is_byte_identical_to_f_v1_and_committed_png(self) -> None:
        composite = MODULE._load_composite_module()
        controls = REPO_ROOT / "world/map-production/controls"
        f1_control = composite.load_control(
            controls / "style-candidate-f-v1-relief-mask-v1.json"
        )
        f2_control = composite.load_control(
            controls / "style-candidate-f-v2-relief-mask-v1.json"
        )
        f1_mask = composite.build_mask(f1_control)
        f2_mask = composite.build_mask(f2_control)
        with Image.open(controls / "style-candidate-f-v2-relief-mask-v1.png") as opened:
            committed = opened.convert("L")
        try:
            self.assertEqual(f1_mask.tobytes(), f2_mask.tobytes())
            self.assertEqual(f2_mask.tobytes(), committed.tobytes())
        finally:
            f1_mask.close()
            f2_mask.close()
            committed.close()

    def test_quality_failure_publishes_no_partial_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            paths = {
                "output_path": directory / "candidate.png",
                "mask_output_path": directory / "mask.png",
                "field_output_path": directory / "field.png",
                "report_path": directory / "report.json",
            }
            with self.assertRaises(MODULE.ReliefTransferError):
                MODULE.transfer(
                    base_path=MODULE.DEFAULT_BASE,
                    generated_path=MODULE.DEFAULT_BASE,
                    control_path=MODULE.DEFAULT_CONTROL,
                    **paths,
                )
            self.assertTrue(all(not path.exists() for path in paths.values()))

    def test_unknown_signal_mode_publishes_no_partial_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            control = json.loads(MODULE.DEFAULT_CONTROL.read_text(encoding="utf-8"))
            control["low_frequency_transfer"]["signal_mode"] = "unknown-mode"
            control_path = directory / "invalid-control.json"
            control_path.write_text(
                json.dumps(control, ensure_ascii=False), encoding="utf-8"
            )
            paths = {
                "output_path": directory / "candidate.png",
                "mask_output_path": directory / "mask.png",
                "field_output_path": directory / "field.png",
                "report_path": directory / "report.json",
            }
            with self.assertRaisesRegex(
                MODULE.ReliefTransferError, "unsupported low-frequency signal_mode"
            ):
                MODULE.transfer(
                    base_path=MODULE.DEFAULT_BASE,
                    generated_path=MODULE.DEFAULT_BASE,
                    control_path=control_path,
                    **paths,
                )
            self.assertTrue(all(not path.exists() for path in paths.values()))

    def test_unknown_direct_option_is_rejected_fail_closed(self) -> None:
        repository_control = (
            REPO_ROOT
            / "world/map-production/controls/style-candidate-f-v1-relief-mask-v1.json"
        )
        control = json.loads(repository_control.read_text(encoding="utf-8"))
        control["low_frequency_transfer"]["direct_plate_gaussian_raduis_px"] = 32
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            control_path = directory / "invalid-control.json"
            control_path.write_text(json.dumps(control), encoding="utf-8")
            paths = {
                "output_path": directory / "candidate.png",
                "mask_output_path": directory / "mask.png",
                "field_output_path": directory / "field.png",
                "report_path": directory / "report.json",
            }
            with self.assertRaisesRegex(
                MODULE.ReliefTransferError,
                "low_frequency_transfer contains unknown keys",
            ):
                MODULE.transfer(
                    base_path=MODULE.DEFAULT_BASE,
                    generated_path=MODULE.DEFAULT_BASE,
                    control_path=control_path,
                    **paths,
                )
            self.assertTrue(all(not path.exists() for path in paths.values()))
            self.assertEqual(list(directory.glob(".*.tmp")), [])

    def test_production_shape_independent_plate_passes_every_e_v1_gate(self) -> None:
        control_path = (
            REPO_ROOT
            / "world/map-production/controls/style-candidate-e-v1-relief-mask-v1.json"
        )
        control = json.loads(control_path.read_text(encoding="utf-8"))
        size = (control["canvas"]["width"], control["canvas"]["height"])
        plate = Image.new("L", size, 128)
        draw = ImageDraw.Draw(plate)
        draw.ellipse((850, -90, 1260, 390), fill=146)
        draw.ellipse((1120, 110, 1600, 650), fill=110)
        draw.ellipse((780, 330, 1120, 690), fill=146)
        draw.ellipse((690, 700, 1130, 1110), fill=146)
        draw.ellipse((1030, 760, 1600, 1160), fill=110)
        draw.ellipse((1210, 620, 1580, 940), fill=110)
        smoothed = plate.filter(ImageFilter.GaussianBlur(radius=72))
        plate.close()
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            generated_path = directory / "independent-plate.png"
            generated_rgb = smoothed.convert("RGB")
            try:
                generated_rgb.save(generated_path)
            finally:
                generated_rgb.close()
                smoothed.close()
            paths = {
                "output_path": directory / "candidate.png",
                "mask_output_path": directory / "mask.png",
                "field_output_path": directory / "field.png",
                "report_path": directory / "report.json",
            }
            report = MODULE.transfer(
                base_path=MODULE.DEFAULT_BASE,
                generated_path=generated_path,
                control_path=control_path,
                **paths,
            )
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["id"], "style-candidate-e-v1-relief-transfer")
            self.assertEqual(report["signal_mode"], "luminance_delta_plate")
            self.assertTrue(all(path.exists() for path in paths.values()))
            self.assertTrue(
                all(
                    31 <= region["input_plate_q90_q10_levels"] <= 40
                    for region in report["region_metrics"]
                )
            )
            self.assertTrue(
                all(
                    5 <= region["final_q90_q10_levels"] <= 9
                    for region in report["region_metrics"]
                )
            )
            self.assertTrue(
                all(
                    quadrant["p90_absolute_delta_levels"] >= 2
                    for quadrant in report["region_quadrant_metrics"]
                )
            )
            self.assertEqual(report["traceable_low_frequency_components"], [])
            self.assertEqual(report["road_changed_pixels"], 0)
            self.assertEqual(report["outside_mask_changed_pixels"], 0)
            self.assertLessEqual(report["maximum_absolute_delta_levels"], 6)

    def test_production_shape_accepts_areal_relief_and_suppresses_a_48px_route(self) -> None:
        control = json.loads(MODULE.DEFAULT_CONTROL.read_text(encoding="utf-8"))
        contract = control["low_frequency_transfer"]
        size = (control["canvas"]["width"], control["canvas"]["height"])
        base = Image.new("L", size, 128)
        areal = Image.new("L", size, 128)
        draw = ImageDraw.Draw(areal)
        draw.ellipse((850, -90, 1260, 390), fill=178)
        draw.ellipse((1120, 110, 1600, 650), fill=78)
        draw.ellipse((690, 700, 1130, 1110), fill=176)
        draw.ellipse((1030, 760, 1600, 1160), fill=80)
        smoothed = areal.filter(ImageFilter.GaussianBlur(radius=82))
        areal.close()
        with_route = smoothed.copy()
        ImageDraw.Draw(with_route).line((900, 250, 1520, 250), fill=12, width=48)
        try:
            applied_a, unmasked_a, regions_a, mask_a = MODULE.derive_field(
                base, smoothed, control, contract
            )
            applied_b, _, _, mask_b = MODULE.derive_field(
                base, with_route, control, contract
            )
        finally:
            base.close()
            smoothed.close()
            with_route.close()
        try:
            difference = [abs(first - second) for first, second in zip(applied_a, applied_b)]
            self.assertLessEqual(
                max(difference),
                1,
                f"max={max(difference)} over1={sum(value > 1 for value in difference)}",
            )
            self.assertLessEqual(MODULE._quantile(difference, 0.99), 1)
            residual_indices = {
                index for index, value in enumerate(difference) if value > 1
            }
            self.assertFalse(residual_indices)
            self.assertTrue(
                all(5 <= item["final_q90_q10_levels"] <= 9 for item in regions_a)
            )
            mask_values = bytes(mask_a.get_flattened_data())
            quadrants = MODULE._region_quadrant_metrics(control, applied_a, mask_values)
            self.assertTrue(
                all(item["p90_absolute_delta_levels"] >= 2 for item in quadrants)
            )

            composite = MODULE._load_composite_module()
            topology = bytearray(size[0] * size[1])
            for polygon in control["include_polygons"]:
                region = composite.build_mask(
                    MODULE._one_region_control(
                        control, polygon, include_exclusions=False
                    )
                )
                try:
                    for index, value in enumerate(region.get_flattened_data()):
                        topology[index] = max(topology[index], value)
                finally:
                    region.close()
            self.assertEqual(
                MODULE._traceable_components(
                    unmasked_a,
                    bytes(topology),
                    size,
                    contract,
                ),
                [],
            )
        finally:
            mask_a.close()
            mask_b.close()


if __name__ == "__main__":
    unittest.main()
