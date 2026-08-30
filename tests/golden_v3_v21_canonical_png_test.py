from __future__ import annotations

import hashlib
import io
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import render_style_candidate_k3_overhead_relief_v21 as renderer  # noqa: E402


CONTROL_ROOT = (
    REPO_ROOT / "world/map-production/controls/style-candidate-k-v3-golden-v3"
)
EXPECTED_MASK_SHA256 = {
    "measurement-inside.png": "1aac375cde9136d64ab05b30cca8b4110c15724488d1c1515c041e5823b87724",
    "texture-reference.png": "5b6b34db3307667ad658f5bfd8f73e4f849576b61c6847185f75fdb72220ea1e",
    "permission.png": "efa65224fd9a1f7623d6a3770b1f7006912e92318ae86c9643a90ba95d22b5dc",
    "protected-features.png": "8863e1937fbe3c57e36db26606db7cd73ac4fc805ef4d6cfbbe69008448b2f19",
    "road-calm-18px.png": "b4fd7dbb0957c2f31499f9cc5366d252bc3013128b6f818d0cb52ae9b9056d98",
    "selected-components.png": "6dbef7b3fe7f82ddada5d8b8759fb3e3405341a563350e45752fbbe00c0cbeb8",
}


class GoldenV3V21CanonicalPngTest(unittest.TestCase):
    def test_runtime_versions_are_exactly_pinned(self) -> None:
        renderer._runtime_gate()

    def test_all_audit_masks_reencode_to_identical_manual_png_bytes(self) -> None:
        for name, expected_sha256 in EXPECTED_MASK_SHA256.items():
            with self.subTest(name=name):
                path = CONTROL_ROOT / "masks" / name
                payload = path.read_bytes()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), expected_sha256)
                with Image.open(io.BytesIO(payload)) as opened:
                    self.assertEqual(opened.mode, "L")
                    self.assertEqual(opened.size, (renderer.WIDTH, renderer.HEIGHT))
                    values = np.asarray(opened, dtype=np.uint8).copy()
                self.assertEqual(set(int(value) for value in np.unique(values)), {0, 255})
                self.assertEqual(renderer._mask_png(values == 255), payload)

    def test_gray_body_control_reencodes_to_identical_manual_png_bytes(self) -> None:
        path = CONTROL_ROOT / "v20-canonical-body-control.png"
        payload = path.read_bytes()
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "aad51a5a92ee0de7c84ecfef4ba9f44c6e99af5add404ebec0f712c808b5e713",
        )
        with Image.open(io.BytesIO(payload)) as opened:
            self.assertEqual(opened.mode, "L")
            values = np.asarray(opened, dtype=np.uint8).copy()
        self.assertEqual(renderer._gray_png(values), payload)

    def test_rgb_foundation_reencodes_to_identical_manual_png_bytes(self) -> None:
        path = CONTROL_ROOT / "foundation-v19-canonical.png"
        payload = path.read_bytes()
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "2f80740f1ef6a6abec2774ab01294e92069f96809ae94473ee723b0aa8b6f214",
        )
        with Image.open(io.BytesIO(payload)) as opened:
            self.assertEqual(opened.mode, "RGB")
            values = np.asarray(opened, dtype=np.uint8).copy()
        self.assertEqual(renderer._rgb_png(values), payload)

    def test_default_v21_reconstruction_stays_exact_rejected_dev20_intermediate(self) -> None:
        inputs = renderer.load_replay_inputs(
            REPO_ROOT / renderer.REPLAY_CONTRACT_PATH,
            expected_contract_sha256=renderer.REPLAY_CONTRACT_SHA256,
        )
        result = renderer.reconstruct(inputs)
        payload = renderer.png_bytes(result.candidate, verify_expected=False)
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "29bc29d8f743442fab5fd263e3aad7094e56f69852cab6bd09deeb3fef92ad22",
        )
        self.assertEqual(
            renderer.array_sha256(result.candidate),
            "56d02af395f4d4f0216337da5600eac4cb3a4f8f988133fbce5d69df25486197",
        )


if __name__ == "__main__":
    unittest.main()
