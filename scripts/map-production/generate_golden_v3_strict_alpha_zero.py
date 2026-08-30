#!/usr/bin/env python3
"""Generate the frozen Golden-v3 alpha-zero mask from the v19 authority."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import numpy as np

import build_style_candidate_k3_sparse_ridgeline_v19 as v19
import render_style_candidate_k3_overhead_relief_v21 as v21


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / Path(
    "world/map-production/controls/style-candidate-k-v3-golden-v3/"
    "masks/alpha-zero.png"
)
EXPECTED_PNG_SHA256 = "786a87101c3a5e6ccae0222687d9db18dc6e06da13f1aa7d131d42166dc85709"
EXPECTED_PNG_BYTES = 1_574_076
EXPECTED_TRUE_PIXELS = 1_334_836
EXPECTED_MASK_ARRAY_SHA256 = "fd0abd26a95d9370c5e69f2a3e7901c86c2f5a2b10a229b88713a95a1f5e8186"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build() -> tuple[np.ndarray, bytes]:
    v19._runtime_gate()
    v21._runtime_gate()
    alpha = v19.derive_controls()["alpha"]
    if alpha.shape != (v21.HEIGHT, v21.WIDTH) or alpha.dtype != np.float32:
        raise RuntimeError("v19 alpha authority shape/type drifted")
    mask = alpha == np.float32(0.0)
    payload = v21._mask_png(mask)
    return mask, payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the frozen file without writing it",
    )
    args = parser.parse_args()
    mask, payload = build()
    observed = {
        "png_sha256": sha256(payload),
        "png_bytes": len(payload),
        "true_pixels": int(np.count_nonzero(mask)),
        "mask_array_sha256": sha256(np.ascontiguousarray(mask.astype(np.uint8)).tobytes()),
    }
    expected = {
        "png_sha256": EXPECTED_PNG_SHA256,
        "png_bytes": EXPECTED_PNG_BYTES,
        "true_pixels": EXPECTED_TRUE_PIXELS,
        "mask_array_sha256": EXPECTED_MASK_ARRAY_SHA256,
    }
    if expected["png_sha256"] != "0" * 64 and observed != expected:
        raise RuntimeError(f"alpha-zero authority drifted: {observed}")
    if args.check:
        try:
            existing = OUTPUT.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"cannot read frozen alpha-zero mask: {OUTPUT}") from exc
        if existing != payload:
            raise RuntimeError("frozen alpha-zero mask differs from deterministic replay")
    elif OUTPUT.exists():
        if OUTPUT.read_bytes() != payload:
            raise RuntimeError("refusing to overwrite a different alpha-zero mask")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        try:
            with OUTPUT.open("xb") as stream:
                stream.write(payload)
        except FileExistsError as exc:
            raise RuntimeError("alpha-zero mask appeared during exclusive creation") from exc
    print(observed)


if __name__ == "__main__":
    main()
