from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    REPO_ROOT / "scripts/map-production/render_candidate_g3_hachure_skeleton.py"
)
SPEC = importlib.util.spec_from_file_location("candidate_g3_hachure_skeleton", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

CONTROL_PATH = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-g-v3-hachure-skeleton.json"
)
OUTPUT_PATH = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-g-v3-hachure-skeleton.png"
)
G2_PROMPT = (
    REPO_ROOT
    / "world/map-production/prompts/"
    "style-candidate-g-v2-orthographic-hachure.generation.txt"
)
G3_PROMPT = (
    REPO_ROOT
    / "world/map-production/prompts/"
    "style-candidate-g-v3-hachure-skeleton.generation.txt"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decoded_raster_identity(path: Path) -> tuple[str, tuple[int, int], bytes]:
    with Image.open(path) as opened:
        opened.load()
        return opened.mode, opened.size, opened.tobytes()


class CandidateG3HachureSkeletonTest(unittest.TestCase):
    def test_committed_source_renders_exact_rgb_skeleton(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sstory-g3-skeleton-", dir=REPO_ROOT) as raw:
            regenerated = Path(raw) / "skeleton.png"
            metrics = MODULE.render(CONTROL_PATH, regenerated)

            self.assertEqual(
                _decoded_raster_identity(regenerated),
                _decoded_raster_identity(OUTPUT_PATH),
            )
            self.assertEqual(
                _sha256(CONTROL_PATH),
                "d6d68f39861802aa28ebf4a42fece89433da80fe616a79fdba57a34aca3baeb6",
            )
            self.assertEqual(
                _sha256(OUTPUT_PATH),
                "dc8978b184755de6ba21f10a120bfb413b0976fed642b106065eff82dee34da3",
            )
            self.assertEqual(metrics["landform_count"], 6)
            self.assertEqual(metrics["main_massif_count"], 2)
            self.assertEqual(metrics["foothill_count"], 4)
            self.assertEqual(metrics["rise_group_count"], 4)
            self.assertEqual(metrics["open_saddle_count"], 2)
            self.assertEqual(metrics["foothill_segment_counts"], [8, 9, 10, 11])
            self.assertEqual(metrics["segment_count"], 79)
            self.assertEqual(metrics["closed_path_count"], 0)
            self.assertEqual(metrics["long_parallel_band_count"], 0)
            self.assertEqual(metrics["radial_convergence_failure_count"], 0)
            self.assertEqual(metrics["reused_normalized_template_count"], 0)
            self.assertTrue(
                all(
                    entry["outside_footprint_ink_pixels"] == 0
                    and entry["connected_components"] == entry["segment_count"]
                    and entry["ink_pixels"] >= 400
                    for entry in metrics["landforms"]
                )
            )
            self.assertTrue(
                all(
                    group["radial_alignment_fraction"] <= 0.5
                    for entry in metrics["landforms"]
                    for group in entry["groups"]
                )
            )
            self.assertTrue(
                all(
                    comparison["normalized_iou"] <= 0.72
                    for comparison in metrics["normalized_template_comparisons"]
                )
            )

            with Image.open(regenerated) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.mode, "RGB")
                self.assertEqual(image.size, (1536, 1024))
                self.assertEqual(
                    set(image.get_flattened_data()),
                    {(240, 238, 232), (54, 48, 42)},
                )

    def test_source_is_hash_locked_to_the_unchanged_g2_footprints(self) -> None:
        control = json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
        reference = control["footprint_reference"]
        self.assertEqual(
            reference,
            {
                "source_path": (
                    "world/map-production/controls/"
                    "style-candidate-g-v2-topology-guide.json"
                ),
                "source_sha256": (
                    "9646d14a89dfd7fd9dccba3d1d3bd14fe9b492623d8850d2d7524c5ff42adc01"
                ),
                "raster_path": (
                    "world/map-production/controls/"
                    "style-candidate-g-v2-topology-guide.png"
                ),
                "raster_sha256": (
                    "a6c8815d5f1a769a6ebfeda8478cf52f586fdb3fd11156c734c3e43d9b6b188f"
                ),
            },
        )
        self.assertEqual(
            _sha256(REPO_ROOT / reference["source_path"]),
            reference["source_sha256"],
        )
        self.assertEqual(
            _sha256(REPO_ROOT / reference["raster_path"]),
            reference["raster_sha256"],
        )

    def test_prompt_changes_only_reference_explanations(self) -> None:
        g2 = G2_PROMPT.read_text(encoding="utf-8")
        g3 = G3_PROMPT.read_text(encoding="utf-8")
        self.assertEqual(g2.splitlines()[:3], g3.splitlines()[:3])

        fixed_start = "THE ONE PERMITTED EDIT\n"
        fixed_end = "OUTPUT CONTRACT\n"
        g2_fixed = g2.split(fixed_start, 1)[1].split(fixed_end, 1)[0]
        g3_fixed = g3.split(fixed_start, 1)[1].split(fixed_end, 1)[0]
        self.assertEqual(g2_fixed, g3_fixed)

        self.assertIn("Image 1 > Image 2 > Image 3", g3)
        self.assertIn("sole compositing permission", g3)
        self.assertIn("Image 3 is conditioning only", g3)
        self.assertIn("Image 3 is a geometry-only skeleton", g3)

    def test_radial_convergence_fails_closed(self) -> None:
        control = json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
        control["render_contract"]["maximum_radial_alignment_fraction"] = 0
        with self.assertRaisesRegex(MODULE.SkeletonError, "radial convergence"):
            MODULE.prepare(control)

    def test_reused_foothill_segment_count_fails_closed(self) -> None:
        control = json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
        central = control["landforms"][2]["groups"][0]["segments"]
        central.pop()
        with self.assertRaisesRegex(MODULE.SkeletonError, "distinct segment counts"):
            MODULE.prepare(control)

    def test_ink_outside_its_locked_footprint_fails_closed(self) -> None:
        control = json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
        segment = control["landforms"][1]["groups"][0]["segments"][0]
        segment["points"] = [[770, 380], [794, 367]]
        with self.assertRaisesRegex(MODULE.SkeletonError, "outside its locked G2 footprint"):
            MODULE.prepare(control)

    def test_renderer_never_overwrites_an_existing_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sstory-g3-skeleton-", dir=REPO_ROOT) as raw:
            output = Path(raw) / "skeleton.png"
            sentinel = b"keep-me"
            output.write_bytes(sentinel)
            with self.assertRaisesRegex(MODULE.SkeletonError, "refusing to overwrite"):
                MODULE.render(CONTROL_PATH, output)
            self.assertEqual(output.read_bytes(), sentinel)


if __name__ == "__main__":
    unittest.main()
