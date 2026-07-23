import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from PIL import Image, ImageChops, ImageOps


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import composite_phase5_protected_tile as compositor  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Phase5ProtectedTileCompositorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index_path = compositor.DEFAULT_INDEX
        cls.index = json.loads(cls.index_path.read_text(encoding="utf-8"))
        cls.tile = cls.index["sheets"][0]["tiles"][0]
        cls.control_path = REPO_ROOT / cls.tile["protected_control"]["path"]
        cls.control = json.loads(cls.control_path.read_text(encoding="utf-8"))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=REPO_ROOT)
        self.root = Path(self.temporary.name)
        self.raw_path = self.root / "raw.png"
        self.parent_path = self.root / "actual-parent.png"
        self.output_path = self.root / "final.png"
        self.report_path = self.root / "postprocess.json"
        Image.new("RGB", (2048, 2048), (17, 41, 83)).save(self.raw_path)
        Image.new("RGB", (2048, 2048), (219, 197, 151)).save(self.parent_path)

    def tearDown(self):
        self.temporary.cleanup()

    def composite(self, **overrides):
        arguments = {
            "index_path": self.index_path,
            "control_path": self.control_path,
            "raw_output_path": self.raw_path,
            "parent_context_path": self.parent_path,
            "output_path": self.output_path,
            "report_path": self.report_path,
            "created_at": "2026-07-19T12:34:56Z",
        }
        arguments.update(overrides)
        return compositor.composite_tile(**arguments)

    def test_composite_uses_actual_parent_and_preserves_only_canonical_layers(self):
        report = self.composite()

        self.assertTrue(self.output_path.is_file())
        self.assertTrue(self.report_path.is_file())
        self.assertEqual(report["generated_by"], compositor.GENERATOR_ID)
        self.assertEqual(report["raw_output"]["sha256"], digest(self.raw_path))
        self.assertEqual(report["output"]["sha256"], digest(self.output_path))
        self.assertEqual(
            report["image_contract"]["runtime_parent_context"]["sha256"],
            digest(self.parent_path),
        )
        self.assertNotEqual(
            report["image_contract"]["runtime_parent_context"]["sha256"],
            self.control["parent_context"]["sha256"],
        )
        self.assertEqual(
            [gate["name"] for gate in report["verification"]["gates"]],
            [
                "unknown-parent-fallback",
                "land-water-boundary",
                "transport",
                "detail",
                "known-generated-interior",
            ],
        )
        self.assertEqual(report["verification"]["total_mismatch_pixel_count"], 0)
        self.assertTrue(report["verification"]["passed"])

        controls = self.tile["authoritative_controls"]
        with (
            Image.open(self.output_path) as final,
            Image.open(self.raw_path) as raw,
            Image.open(self.parent_path) as parent,
            Image.open(REPO_ROOT / controls["land_mask"]["path"]) as land,
            Image.open(REPO_ROOT / controls["water_mask"]["path"]) as water,
            Image.open(REPO_ROOT / controls["known_mask"]["path"]) as known,
            Image.open(REPO_ROOT / controls["unknown_mask"]["path"]) as unknown,
            Image.open(REPO_ROOT / controls["transport_mask"]["path"]) as transport,
            Image.open(REPO_ROOT / controls["detail_mask"]["path"]) as detail,
        ):
            boundary = compositor.derive_land_water_boundary(land, water)
            protected = compositor._mask_union(boundary, transport, detail)
            known_interior = compositor._mask_without(known, protected)
            try:
                self.assertEqual(compositor._mismatch_count(final, parent, unknown), 0)
                self.assertEqual(
                    compositor._mismatch_count(final, raw, known_interior), 0
                )
                self.assertGreater(compositor._mask_count(known_interior), 0)
                self.assertGreater(compositor._mask_count(unknown), 0)
            finally:
                boundary.close()
                protected.close()
                known_interior.close()

        stored = json.loads(self.report_path.read_text(encoding="utf-8"))
        self.assertEqual(stored, report)
        compositor._validate_schema(
            stored,
            compositor.DEFAULT_REPORT_SCHEMA,
            "generated postprocess report",
        )

    def test_no_overwrite_preserves_both_published_artifacts(self):
        self.composite()
        original_output = self.output_path.read_bytes()
        original_report = self.report_path.read_bytes()

        with self.assertRaisesRegex(
            compositor.Phase5CompositeError, "refusing to overwrite"
        ):
            self.composite()

        self.assertEqual(self.output_path.read_bytes(), original_output)
        self.assertEqual(self.report_path.read_bytes(), original_report)

    def test_existing_report_prevents_partial_output_publication(self):
        self.report_path.write_text("user-owned", encoding="utf-8")

        with self.assertRaisesRegex(
            compositor.Phase5CompositeError, "refusing to overwrite"
        ):
            self.composite()

        self.assertFalse(self.output_path.exists())
        self.assertEqual(self.report_path.read_text(encoding="utf-8"), "user-owned")

    def test_invalid_raw_contract_fails_before_writing(self):
        Image.new("RGBA", (2048, 2048), (1, 2, 3, 255)).save(self.raw_path)

        with self.assertRaisesRegex(compositor.Phase5CompositeError, "native RGB PNG"):
            self.composite()

        self.assertFalse(self.output_path.exists())
        self.assertFalse(self.report_path.exists())

    def test_index_control_hash_mismatch_fails_closed(self):
        changed = json.loads(json.dumps(self.index))
        changed["sheets"][0]["tiles"][0]["protected_control"]["sha256"] = "0" * 64
        changed["sheets"][0]["tiles"][0]["receipt_bindings"]["postprocess_control"][
            "sha256"
        ] = "0" * 64
        changed_index = self.root / "changed-index.json"
        changed_index.write_text(json.dumps(changed), encoding="utf-8")

        with self.assertRaisesRegex(
            compositor.Phase5CompositeError, "does not match the indexed metatile"
        ):
            self.composite(index_path=changed_index)

        self.assertFalse(self.output_path.exists())
        self.assertFalse(self.report_path.exists())

    def test_masks_form_exact_exhaustive_partition(self):
        controls = self.tile["authoritative_controls"]
        with (
            Image.open(REPO_ROOT / controls["land_mask"]["path"]) as land,
            Image.open(REPO_ROOT / controls["water_mask"]["path"]) as water,
            Image.open(REPO_ROOT / controls["known_mask"]["path"]) as known,
            Image.open(REPO_ROOT / controls["unknown_mask"]["path"]) as unknown,
        ):
            union = ImageChops.lighter(land, water)
            inverse = ImageOps.invert(union)
            try:
                compositor._assert_masks_equal(known, union, "known")
                compositor._assert_masks_equal(unknown, inverse, "unknown")
                self.assertEqual(
                    compositor._mask_count(land)
                    + compositor._mask_count(water)
                    + compositor._mask_count(unknown),
                    compositor.PIXEL_COUNT,
                )
            finally:
                union.close()
                inverse.close()

    def test_report_schema_remains_backward_compatible(self):
        minimal = {
            "$schema": compositor.REPORT_SCHEMA_URL,
            "schema_version": "1.0.0",
            "type": "sstory-phase5-deterministic-protected-composite-report",
            "coordinate_reference_system": "EA-WORLD-1",
            "generated_by": compositor.GENERATOR_ID,
            "mode": "deterministic-protected-composite",
            "sheet_id": self.control["sheet_id"],
            "column": self.control["column"],
            "row": self.control["row"],
            "raw_output": {"path": "raw.png", "sha256": "0" * 64},
            "control": {"path": "control.json", "sha256": "1" * 64},
            "output": {"path": "output.png", "sha256": "2" * 64},
            "protected_layers": ["land-sea", "transport", "detail"],
            "created_at": "2026-07-19T12:34:56Z",
        }

        compositor._validate_schema(
            minimal,
            compositor.DEFAULT_REPORT_SCHEMA,
            "legacy postprocess report",
        )

    def test_cli_requires_explicit_runtime_parent(self):
        parser = compositor.build_parser()
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(
                    [
                        "--control",
                        str(self.control_path),
                        "--raw-output",
                        str(self.raw_path),
                        "--output",
                        str(self.output_path),
                        "--report",
                        str(self.report_path),
                    ]
                )


if __name__ == "__main__":
    unittest.main()
