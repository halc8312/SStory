from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    REPO_ROOT / "scripts/map-production/render_candidate_d_fragment_guide.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location(
    "render_candidate_d_fragment_guide", MODULE_PATH
)
fragment_guide = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
MODULE_SPEC.loader.exec_module(fragment_guide)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CandidateDFragmentGuideRendererTests(unittest.TestCase):
    def test_spec_hash_locks_source_and_v1_five_plus_five_topology(self) -> None:
        spec = fragment_guide.load_and_validate_spec()
        topology = fragment_guide.TOPOLOGY.load_and_validate_spec(
            REPO_ROOT / spec["topology_control"]["path"]
        )

        self.assertEqual(spec["canvas"], {"width": 1536, "height": 1024})
        self.assertEqual(
            spec["source_context"],
            {
                "path": fragment_guide.EXPECTED_SOURCE_PATH,
                "role": "very-faint-location-context-only",
                "sha256": fragment_guide.EXPECTED_SOURCE_SHA256,
            },
        )
        self.assertEqual(
            spec["topology_control"]["sha256"],
            fragment_guide.EXPECTED_TOPOLOGY_SHA256,
        )
        self.assertEqual(
            [region["id"] for region in spec["regions"]],
            ["north_east_range", "south_east_range"],
        )
        self.assertEqual(
            [len(region["ridge_controls"]) for region in spec["regions"]], [5, 5]
        )

        for region, topology_region in zip(spec["regions"], topology["regions"]):
            for ridge, topology_ridge in zip(
                region["ridge_controls"], topology_region["ridge_chains"]
            ):
                self.assertEqual(ridge["id"], topology_ridge["id"])
                self.assertEqual(
                    ridge["geometry_zone"]["source_pixels_path"],
                    topology_ridge["source_pixels_path"],
                )
                self.assertEqual(ridge["geometry_zone"]["width_px"], 40)
                self.assertEqual(
                    ridge["hatch_zones"][0]["source_pixels_path"],
                    topology_ridge["hatches"][0]["source_pixels_path"],
                )

    def test_each_ridge_has_three_18px_fragments_with_24px_or_larger_gaps(self) -> None:
        spec = fragment_guide.load_and_validate_spec()
        for region in spec["regions"]:
            for ridge in region["ridge_controls"]:
                center = [
                    tuple(point) for point in ridge["geometry_zone"]["source_pixels_path"]
                ]
                center_length = fragment_guide.path_length(center)
                fragments = ridge["crest_fragment_zones"]
                self.assertEqual(len(fragments), 3)
                self.assertEqual([item["length_px"] for item in fragments], [18, 18, 18])
                intervals = [
                    (
                        item["start_fraction"] * center_length,
                        item["start_fraction"] * center_length + item["length_px"],
                    )
                    for item in fragments
                ]
                for first, second in zip(intervals, intervals[1:]):
                    self.assertGreaterEqual(second[0] - first[1], 24)
                    self.assertGreaterEqual(
                        fragment_guide.math.dist(
                            fragment_guide.point_at_distance(center, first[1]),
                            fragment_guide.point_at_distance(center, second[0]),
                        ),
                        24,
                    )
                self.assertEqual(len(ridge["hatch_zones"]), 1)
                self.assertFalse(spec["rendering"]["geometry_zone_outline_drawn"])
                self.assertFalse(spec["rendering"]["continuous_centerline_drawn"])
                self.assertFalse(spec["rendering"]["labels_or_legend_baked_into_raster"])

    def test_render_is_deterministic_stored_exact_size_and_color_coded(self) -> None:
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = Path(first_dir) / "fragment-guide.png"
            second = Path(second_dir) / "fragment-guide.png"
            fragment_guide.render_guide(output_path=first)
            fragment_guide.render_guide(output_path=second)

            self.assertEqual(sha256(first), sha256(second))
            self.assertEqual(sha256(first), sha256(fragment_guide.DEFAULT_OUTPUT))
            with Image.open(first) as image:
                self.assertEqual(image.size, (1536, 1024))
                self.assertEqual(image.mode, "RGB")
                for region in fragment_guide.load_and_validate_spec()["regions"]:
                    for ridge in region["ridge_controls"]:
                        center = [
                            tuple(point)
                            for point in ridge["geometry_zone"]["source_pixels_path"]
                        ]
                        center_length = fragment_guide.path_length(center)

                        cyan_point = fragment_guide.point_at_distance(
                            center, center_length * 0.32
                        )
                        cyan = image.getpixel(tuple(round(value) for value in cyan_point))
                        self.assertGreater(cyan[1], cyan[0] + 45)
                        self.assertGreater(cyan[2], cyan[0] + 45)

                        for fragment in ridge["crest_fragment_zones"]:
                            magenta_point = fragment_guide.point_at_distance(
                                center,
                                fragment["start_fraction"] * center_length
                                + fragment["length_px"] / 2,
                            )
                            magenta = image.getpixel(
                                tuple(round(value) for value in magenta_point)
                            )
                            self.assertGreater(magenta[0], magenta[1] + 80)
                            self.assertGreater(magenta[2], magenta[1] + 45)

                        hatch_path = ridge["hatch_zones"][0]["source_pixels_path"]
                        lime_point = tuple(
                            round((first_value + second_value) / 2)
                            for first_value, second_value in zip(
                                hatch_path[0], hatch_path[-1]
                            )
                        )
                        lime = image.getpixel(lime_point)
                        self.assertGreater(lime[1], lime[0] + 25)
                        self.assertGreater(lime[1], lime[2] + 80)

    def test_renderer_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "owned.png"
            target.write_bytes(b"user-owned")
            with self.assertRaisesRegex(
                fragment_guide.FragmentGuideError, "refusing to overwrite"
            ):
                fragment_guide.render_guide(output_path=target)
            self.assertEqual(target.read_bytes(), b"user-owned")

    def test_validator_rejects_bad_fragment_counts_gaps_paths_and_topology_hash(self) -> None:
        original = json.loads(fragment_guide.DEFAULT_SPEC.read_text(encoding="utf-8"))
        mutations = []

        missing_fragment = copy.deepcopy(original)
        missing_fragment["regions"][0]["ridge_controls"][0][
            "crest_fragment_zones"
        ].pop()
        mutations.append((missing_fragment, "exactly three"))

        narrow_gap = copy.deepcopy(original)
        narrow_gap["regions"][0]["ridge_controls"][0]["crest_fragment_zones"][1][
            "start_fraction"
        ] = 0.20
        mutations.append((narrow_gap, "gap must be at least"))

        moved_path = copy.deepcopy(original)
        moved_path["regions"][1]["ridge_controls"][2]["geometry_zone"][
            "source_pixels_path"
        ][0][0] += 1
        mutations.append((moved_path, "path must exactly match"))

        wrong_hash = copy.deepcopy(original)
        wrong_hash["topology_control"]["sha256"] = "0" * 64
        mutations.append((wrong_hash, "SHA-256 must remain"))

        with tempfile.TemporaryDirectory() as temp_dir:
            for index, (mutated, message) in enumerate(mutations):
                path = Path(temp_dir) / f"invalid-{index}.json"
                path.write_text(json.dumps(mutated), encoding="utf-8")
                with self.subTest(message=message):
                    with self.assertRaisesRegex(
                        fragment_guide.FragmentGuideError, message
                    ):
                        fragment_guide.load_and_validate_spec(path)


if __name__ == "__main__":
    unittest.main()
