from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import build_style_candidate_k3_sparse_ridgeline_v19 as v19  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def binding(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": digest(path)}


class SparseRidgelineV19ReplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        scratch_parent = REPO_ROOT / "tmp" / "test-temp"
        scratch_parent.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(
            prefix="k3-v19-replay-test-", dir=scratch_parent
        )
        cls.scratch = Path(cls.temporary.name)
        cls.base = (
            REPO_ROOT
            / "world/map-production/style-assets/k3-v18-reconstruction-base.png"
        )
        cls.layout = (
            REPO_ROOT
            / "world/map-production/style-assets/k3-v55-topographic-contour-atlas.png"
        )
        cls.canonical_body_control = (
            REPO_ROOT
            / "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/"
            "k3-v52-canonical-body-control.png"
        )
        cls.control_atlas_metadata = (
            REPO_ROOT
            / "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/"
            "k3-v52-eight-ridge-control-atlas.json"
        )
        cls.prompt = (
            REPO_ROOT
            / "world/map-production/prompts/"
            "style-candidate-k-v3-highland-contour-atlas-v55.generation.txt"
        )
        cls.generation_receipt = (
            REPO_ROOT
            / "world/map-production/prompts/"
            "style-candidate-k-v3-highland-contour-atlas-v55.generation-receipt.json"
        )
        cls.authority_paths = {
            "canonical-k3-spec": (
                REPO_ROOT
                / "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/spec.json"
            ),
            "v55-root-vision-review": (
                REPO_ROOT
                / "world/map-production/qa/"
                "style-candidate-k-v3-highland-source-v55-root-vision.json"
            ),
            "v55-robust-recipe-verification": (
                REPO_ROOT
                / "world/map-production/qa/automated/"
                "style-candidate-k-v3-sparse-ridgeline-v19-preflight.json"
            ),
            "v52-control-atlas": (
                REPO_ROOT
                / "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/"
                "k3-v52-eight-ridge-control-atlas.png"
            ),
            "v55-copperplate-material-reference": (
                REPO_ROOT
                / "world/map-production/style-assets/highland-detail-exemplar-v1.png"
            ),
            "v55-palette-parchment-reference": (
                REPO_ROOT
                / "world/map-production/candidates/"
                "style-candidate-h-v4-plan-view-golden-board.png"
            ),
        }
        for path in (
            cls.base,
            cls.layout,
            cls.canonical_body_control,
            cls.control_atlas_metadata,
            cls.prompt,
            cls.generation_receipt,
            *cls.authority_paths.values(),
        ):
            if not path.is_file():
                raise AssertionError(f"missing frozen v19 replay fixture: {path}")
        cls.contract = {
            "schema_version": "1.0.0",
            "interface": v19.INTERFACE,
            "base_v18": binding(cls.base),
            "generated_layout_control": binding(cls.layout),
            "canonical_body_control": binding(cls.canonical_body_control),
            "control_atlas_metadata": binding(cls.control_atlas_metadata),
            "imagegen_prompt": binding(cls.prompt),
            "generation_receipt": binding(cls.generation_receipt),
            "authorities": [
                {"role": role, **binding(path)}
                for role, path in cls.authority_paths.items()
            ],
        }
        cls.contract_path = cls.scratch / "replay-contract.json"
        cls.contract_path.write_text(
            json.dumps(cls.contract, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        cls.first = v19.reconstruct_from_contract(cls.contract_path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def _write_contract(self, value: dict[str, object], name: str) -> Path:
        path = self.scratch / name
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def test_replay_is_byte_deterministic_in_memory(self) -> None:
        second = v19.reconstruct_from_contract(self.contract_path)
        self.assertTrue(np.array_equal(self.first.candidate, second.candidate))
        self.assertEqual(
            v19.array_sha256(self.first.candidate), v19.EXPECTED_PIXEL_SHA256
        )
        self.assertEqual(
            v19.array_sha256(second.candidate), v19.EXPECTED_PIXEL_SHA256
        )
        encoded = v19.png_bytes(self.first.candidate)
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), v19.EXPECTED_PNG_SHA256)
        self.assertEqual(len(encoded), v19.EXPECTED_PNG_BYTES)
        self.assertEqual(list(self.scratch.glob("*.png")), [])

    def test_tampered_bindings_and_interface_fail_closed(self) -> None:
        tampered_prompt = self.scratch / "tampered-prompt.txt"
        tampered_prompt.write_bytes(self.prompt.read_bytes() + b"tamper")
        tampered = copy.deepcopy(self.contract)
        tampered["imagegen_prompt"]["path"] = str(tampered_prompt)
        with self.assertRaisesRegex(v19.ReplayError, "SHA-256 mismatch"):
            v19.load_replay_inputs(
                self._write_contract(tampered, "tampered-prompt-contract.json")
            )

        tampered = copy.deepcopy(self.contract)
        tampered["interface"] = "sstory-k3-sparse-ridgeline-v19-replay-v0"
        with self.assertRaisesRegex(v19.ReplayError, "interface/schema mismatch"):
            v19.load_replay_inputs(
                self._write_contract(tampered, "tampered-interface-contract.json")
            )

        tampered = copy.deepcopy(self.contract)
        tampered["unexpected"] = True
        with self.assertRaisesRegex(v19.ReplayError, "exact closed input graph"):
            v19.load_replay_inputs(
                self._write_contract(tampered, "open-schema-contract.json")
            )

        tampered = copy.deepcopy(self.contract)
        tampered["canonical_body_control"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(v19.ReplayError, "SHA-256 mismatch"):
            v19.load_replay_inputs(
                self._write_contract(tampered, "tampered-body-control-contract.json")
            )

        tampered = copy.deepcopy(self.contract)
        tampered["authorities"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(v19.ReplayError, "SHA-256 mismatch"):
            v19.load_replay_inputs(
                self._write_contract(tampered, "tampered-authority-contract.json")
            )

    def test_exact_lock_containment_and_eight_body_gate(self) -> None:
        result = self.first
        changed = np.any(result.candidate != result.baseline, axis=2)
        alpha_zero = result.alpha == np.float32(0.0)
        self.assertEqual(len(result.components), 8)
        self.assertEqual(
            [component["body_pixels"] for component in result.components],
            [12370, 11618, 11142, 15929, 13473, 10915, 9379, 1777],
        )
        self.assertEqual(
            [component["material_pixels"] for component in result.components],
            [12370, 11618, 11142, 15929, 13473, 10915, 9379, 1777],
        )
        self.assertEqual(
            [component["ink_nonzero_pixels"] for component in result.components],
            [11516, 10836, 10371, 14663, 12485, 10083, 8711, 1638],
        )
        self.assertEqual(int(result.body.sum()), 86603)
        self.assertEqual(int(result.core.sum()), 86603)
        self.assertTrue(np.array_equal(result.core, result.body))
        self.assertEqual(
            v19.array_sha256(result.body.astype(np.uint8)),
            v19.EXPECTED_BODY_UNION_SHA256,
        )
        self.assertEqual(
            v19.array_sha256(result.contour_field),
            v19.EXPECTED_INTERMEDIATE_SHA256["field"],
        )
        self.assertEqual(
            v19.array_sha256(result.contour_owner),
            v19.EXPECTED_INTERMEDIATE_SHA256["owner"],
        )
        self.assertFalse(np.any(result.core & ~result.body))
        self.assertFalse(np.any(result.body & ~result.inside))
        self.assertFalse(np.any(changed & ~result.permission))
        self.assertFalse(np.any(changed & result.protected))
        self.assertFalse(np.any(changed & result.road_calm))
        self.assertFalse(np.any(changed & alpha_zero))
        self.assertEqual(
            result.identity,
            {
                "changed_pixels": 237342,
                "outside_permission": 0,
                "protected_features": 0,
                "road_calm_18px": 0,
                "alpha_zero_changed": 0,
                "body_outside_full_alpha": 0,
                "contour_outside_body": 0,
                "contour_grayscale_mismatch": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
