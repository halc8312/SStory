from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts/map-production"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import render_style_candidate_h20_multiband as h20  # noqa: E402


def test_locked_sources_and_pyramid_contract() -> None:
    assert h20._sha(h20.DEFAULT_H4) == h20.LOCKS["h4"]
    assert h20._sha(h20.DEFAULT_H5) == h20.LOCKS["h5"]
    assert h20._sha(h20.DEFAULT_H9) == h20.LOCKS["h9"]
    assert h20.PYRAMID_LEVELS >= 5


def test_output_must_stay_in_prototype_root(tmp_path: Path) -> None:
    with pytest.raises(h20.H20Error, match="output must stay"):
        h20.render(output_dir=tmp_path)


def test_multiband_reconstruction_is_identity_with_source_only() -> None:
    rng = np.random.default_rng(20)
    source = rng.integers(0, 256, (64, 64, 3), np.uint8)
    mask = np.ones((64, 64), bool)
    rows = tuple((1.0,) for _ in range(h20.PYRAMID_LEVELS + 1))
    candidate = h20._spectral_composite(source, (source,), rows, mask, 4.0)
    assert np.max(np.abs(candidate.astype(np.int16) - source.astype(np.int16))) <= 1


def test_second_iteration_is_bounded_and_fails_closed_on_triangle_contract() -> None:
    output = h20.DEFAULT_OUTPUT_ROOT / h20.DEFAULT_ITERATION
    report = h20.render(output_dir=output, replace=True)
    assert report["status"] == "iteration_2_failed_automated"
    assert report["gate_status"][
        "registered_triangle_signature_reduction_at_least_90_percent"
    ] is False
    assert all(
        value
        for name, value in report["gate_status"].items()
        if name != "registered_triangle_signature_reduction_at_least_90_percent"
    ), report["gate_status"]
    assert report["full_resolution_protection"]["changed_fraction"] < 0.25
    assert report["full_resolution_protection"]["protected_violation_pixels"] == 0
    assert all(
        value == 0
        for value in report["full_resolution_protection"]["exact_guard_changed_pixels"].values()
    )
    assert report["alignment"]["subpixel_median_verified"] is True
    assert report["perspective_proxy"]["reduction_fraction"] < 0.90
    with Image.open(output / f"{h20.STEM}.png") as master:
        assert master.size == h20.CANVAS
        assert master.mode == "RGB"
    with Image.open(output / f"{h20.STEM}.contact-sheet.png") as contact:
        assert contact.size == (1536, 2048)
