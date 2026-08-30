import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "map-production" / "render_world_master.py"
SPEC = importlib.util.spec_from_file_location("render_world_master", MODULE_PATH)
render_world_master = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(render_world_master)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class WorldMasterRendererTests(unittest.TestCase):
    def test_small_render_is_deterministic_and_records_canonical_inventory(self):
        source_dir = REPO_ROOT / "world" / "map-production" / "source"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_png = root / "first.png"
            first_json = root / "first.json"
            second_png = root / "second.png"
            second_json = root / "second.json"

            first = render_world_master.write_master(
                first_png,
                first_json,
                source_dir=source_dir,
                width=600,
                height=400,
                seed=20260719,
            )
            second = render_world_master.write_master(
                second_png,
                second_json,
                source_dir=source_dir,
                width=600,
                height=400,
                seed=20260719,
            )

            self.assertEqual(sha256(first_png), sha256(second_png))
            self.assertEqual(first["output"]["sha256"], sha256(first_png))
            self.assertEqual(second["output"]["sha256"], sha256(second_png))
            self.assertEqual(first["canonical_inventory"]["continents"]["count"], 5)
            self.assertEqual(first["canonical_inventory"]["regions"]["count"], 14)
            self.assertEqual(first["canonical_inventory"]["routes"]["count"], 33)
            self.assertEqual(
                len(first["canonical_inventory"]["routes"]["ids"]), 33
            )
            self.assertFalse(
                first["canonical_transform"]["source_coordinates_modified"]
            )
            self.assertFalse(first["style"]["contains_text"])
            self.assertFalse(first["style"]["font_rendering_used"])
            self.assertEqual(first["style"]["profile"], "style-candidate-b-v1")
            self.assertEqual(
                first["artifact_role"],
                "canonical-generation-control-and-qa-overlay",
            )
            self.assertFalse(first["publication"]["public_basemap"])

            saved = json.loads(first_json.read_text(encoding="utf-8"))
            self.assertEqual(saved["output"]["sha256"], sha256(first_png))
            with Image.open(first_png) as image:
                self.assertEqual(image.size, (600, 400))
                self.assertEqual(image.mode, "RGB")
                self.assertGreater(len(image.getcolors(maxcolors=1_000_000)), 100)

    def test_different_seed_changes_only_rendered_microdetail_contract(self):
        sources = render_world_master.load_sources(
            REPO_ROOT / "world" / "map-production" / "source"
        )
        first = render_world_master.render_master(
            sources, width=320, height=256, seed=1
        )
        second = render_world_master.render_master(
            sources, width=320, height=256, seed=2
        )
        try:
            self.assertNotEqual(first.tobytes(), second.tobytes())
            transform = render_world_master.CanvasTransform(320, 256)
            self.assertEqual(transform.point([0, 0]), (0, 0))
            self.assertEqual(transform.point([10000, 10000]), (319, 255))
            self.assertEqual(transform.point([5000, 5000]), (160, 128))
        finally:
            first.close()
            second.close()

    def test_existing_png_or_metadata_is_never_overwritten(self):
        source_dir = REPO_ROOT / "world" / "map-production" / "source"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            png = root / "master.png"
            metadata = root / "master.json"
            png.write_bytes(b"user-owned")
            with self.assertRaisesRegex(
                render_world_master.RenderError, "refusing to overwrite"
            ):
                render_world_master.write_master(
                    png,
                    metadata,
                    source_dir=source_dir,
                    width=320,
                    height=256,
                )
            self.assertEqual(png.read_bytes(), b"user-owned")
            self.assertFalse(metadata.exists())

            png.unlink()
            metadata.write_text('{"owner":"user"}\n', encoding="utf-8")
            with self.assertRaisesRegex(
                render_world_master.RenderError, "refusing to overwrite"
            ):
                render_world_master.write_master(
                    png,
                    metadata,
                    source_dir=source_dir,
                    width=320,
                    height=256,
                )
            self.assertFalse(png.exists())
            self.assertEqual(
                metadata.read_text(encoding="utf-8"), '{"owner":"user"}\n'
            )


if __name__ == "__main__":
    unittest.main()
