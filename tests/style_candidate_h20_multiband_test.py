from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts/map-production"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import render_style_candidate_h20_multiband as h20  # noqa: E402


class H20MultibandTest(unittest.TestCase):
    def test_locked_sources_and_pyramid_contract(self) -> None:
        self.assertEqual(h20._sha(h20.DEFAULT_H4), h20.LOCKS["h4"])
        self.assertEqual(h20._sha(h20.DEFAULT_H5), h20.LOCKS["h5"])
        self.assertEqual(h20._sha(h20.DEFAULT_H9), h20.LOCKS["h9"])
        self.assertGreaterEqual(h20.PYRAMID_LEVELS, 5)

    def test_output_must_stay_in_prototype_root(self) -> None:
        outside_parent = ROOT / "tmp/map-production"
        outside_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".candidate-h20-outside-", dir=outside_parent
        ) as temporary:
            with self.assertRaisesRegex(h20.H20Error, "output must stay"):
                h20.render(output_dir=Path(temporary))

    def test_multiband_reconstruction_is_identity_with_source_only(self) -> None:
        rng = np.random.default_rng(20)
        source = rng.integers(0, 256, (64, 64, 3), np.uint8)
        mask = np.ones((64, 64), bool)
        rows = tuple((1.0,) for _ in range(h20.PYRAMID_LEVELS + 1))
        candidate = h20._spectral_composite(source, (source,), rows, mask, 4.0)
        maximum_delta = np.max(
            np.abs(candidate.astype(np.int16) - source.astype(np.int16))
        )
        self.assertLessEqual(maximum_delta, 1)

    def test_second_iteration_is_bounded_and_fails_closed_on_triangle_contract(
        self,
    ) -> None:
        h20.DEFAULT_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".candidate-h20-test-", dir=h20.DEFAULT_OUTPUT_ROOT
        ) as temporary:
            output = Path(temporary)
            report = h20.render(output_dir=output)
            self.assertEqual(report["status"], "iteration_2_failed_automated")
            self.assertFalse(
                report["gate_status"][
                    "registered_triangle_signature_reduction_at_least_90_percent"
                ]
            )
            self.assertTrue(
                all(
                    value
                    for name, value in report["gate_status"].items()
                    if name
                    != "registered_triangle_signature_reduction_at_least_90_percent"
                ),
                report["gate_status"],
            )
            protection = report["full_resolution_protection"]
            self.assertLess(protection["changed_fraction"], 0.25)
            self.assertEqual(protection["protected_violation_pixels"], 0)
            self.assertTrue(
                all(
                    value == 0
                    for value in protection["exact_guard_changed_pixels"].values()
                )
            )
            self.assertTrue(report["alignment"]["subpixel_median_verified"])
            self.assertLess(report["perspective_proxy"]["reduction_fraction"], 0.90)
            with Image.open(output / f"{h20.STEM}.png") as master:
                self.assertEqual(master.size, h20.CANVAS)
                self.assertEqual(master.mode, "RGB")
            with Image.open(output / f"{h20.STEM}.contact-sheet.png") as contact:
                self.assertEqual(contact.size, (1536, 2048))


if __name__ == "__main__":
    unittest.main()
