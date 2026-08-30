from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageChops, PngImagePlugin


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import emit_phase5_vision_views as emitter  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def save_pattern(path: Path, *, mode: str = "RGB") -> None:
    width, height = 11, 9
    if mode == "RGB":
        pixels = [
            (
                (x * 23 + y * 7) % 256,
                (x * 5 + y * 31) % 256,
                (x * 17 + y * 13) % 256,
            )
            for y in range(height)
            for x in range(width)
        ]
        image = Image.new("RGB", (width, height))
        image.putdata(pixels)
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("fixture-metadata", "must-not-propagate")
        image.save(
            path,
            format="PNG",
            compress_level=9,
            optimize=False,
            pnginfo=metadata,
        )
        image.close()
        return
    with Image.new(mode, (width, height), 127) as image:
        image.save(path, format="PNG", compress_level=9, optimize=False)


def mutate_rgb_pixel(path: Path) -> None:
    with Image.open(path) as opened:
        opened.load()
        image = opened.copy()
    try:
        red, green, blue = image.getpixel((0, 0))
        image.putpixel((0, 0), ((red + 1) % 256, green, blue))
        image.save(
            path,
            format="PNG",
            compress_level=9,
            optimize=False,
            pnginfo=PngImagePlugin.PngInfo(),
        )
    finally:
        image.close()


class VisionViewsFixture:
    def __init__(self) -> None:
        self.source_temp = tempfile.TemporaryDirectory(
            prefix=".phase5-vision-source-test-", dir=REPO_ROOT
        )
        output_parent = REPO_ROOT / "tmp" / "map-production"
        output_parent.mkdir(parents=True, exist_ok=True)
        self.output_temp = tempfile.TemporaryDirectory(
            prefix="phase5-vision-output-test-", dir=output_parent
        )
        self.source_root = Path(self.source_temp.name)
        self.output_root = Path(self.output_temp.name)
        self.source = self.source_root / "source.png"
        save_pattern(self.source)
        self.source_relative = repo_relative(self.source)
        self.source_sha256 = sha256(self.source)

    def close(self) -> None:
        self.output_temp.cleanup()
        self.source_temp.cleanup()

    def output(self, name: str) -> Path:
        return self.output_root / name

    def emit(
        self,
        name: str,
        *,
        focus_box: tuple[int, int, int, int] = (2, 1, 8, 7),
    ) -> dict[str, object]:
        with mock.patch.object(emitter, "_assert_git_tracked") as tracked:
            result = emitter.emit_phase5_vision_views(
                self.source_relative,
                self.output(name),
                source_sha256=self.source_sha256,
                focus_box=focus_box,
            )
        self.tracking_call_count = tracked.call_count
        return result


class Phase5VisionViewsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = VisionViewsFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_two_runs_are_byte_deterministic_and_exact_inventory(self) -> None:
        first = self.fixture.output("bundle-a")
        second = self.fixture.output("bundle-b")
        self.fixture.emit("bundle-a")
        self.fixture.emit("bundle-b")

        expected = sorted(
            [
                "native.png",
                "full25.png",
                "full50.png",
                "focus200.png",
                "focus400.png",
                "receipt.json",
            ]
        )
        self.assertEqual(expected, sorted(path.name for path in first.iterdir()))
        self.assertEqual(expected, sorted(path.name for path in second.iterdir()))
        for name in expected:
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
        self.assertEqual(2, self.fixture.tracking_call_count)

    def test_views_are_pixel_exact_and_receipt_is_fully_bound(self) -> None:
        output = self.fixture.output("pixel-exact")
        result = self.fixture.emit("pixel-exact")
        with Image.open(self.fixture.source) as opened:
            opened.load()
            source = opened.copy()
        crop = source.crop((2, 1, 8, 7))
        expected = {
            "native": source.copy(),
            "full25": source.resize((3, 2), Image.Resampling.LANCZOS),
            "full50": source.resize((6, 5), Image.Resampling.LANCZOS),
            "focus200": crop.resize((12, 12), Image.Resampling.LANCZOS),
            "focus400": crop.resize((24, 24), Image.Resampling.LANCZOS),
        }
        try:
            for view_id, expected_image in expected.items():
                with Image.open(output / f"{view_id}.png") as actual:
                    actual.load()
                    self.assertEqual("RGB", actual.mode)
                    self.assertEqual({}, actual.info)
                    self.assertEqual(expected_image.size, actual.size)
                    self.assertIsNone(
                        ImageChops.difference(expected_image, actual).getbbox()
                    )
        finally:
            for image in expected.values():
                image.close()
            crop.close()
            source.close()

        receipt_path = output / "receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(emitter.SCHEMA_VERSION, receipt["schema_version"])
        self.assertEqual(emitter.BUNDLE_TYPE, receipt["type"])
        self.assertEqual(list(emitter.VIEW_ORDER), receipt["view_order"])
        self.assertEqual(
            {
                "path": self.fixture.source_relative,
                "sha256": self.fixture.source_sha256,
                "bytes": self.fixture.source.stat().st_size,
                "mode": "RGB",
                "size": [11, 9],
            },
            receipt["source"],
        )
        self.assertEqual(
            {
                "box_px": [2, 1, 8, 7],
                "crop_size": [6, 6],
                "coordinate_convention": ("left-top-inclusive_right-bottom-exclusive"),
            },
            receipt["focus"],
        )
        self.assertEqual(
            emitter.ROUNDING_RULE, receipt["rendering"]["full_size_rounding"]
        )
        self.assertEqual({}, receipt["rendering"]["png"]["metadata"])
        self.assertEqual(
            ["native", "full25", "full50", "focus200", "focus400"],
            [view["id"] for view in receipt["views"]],
        )
        for view in receipt["views"]:
            path = output / view["path"]
            self.assertEqual(sha256(path), view["sha256"])
            self.assertEqual(path.stat().st_size, view["bytes"])
            self.assertEqual("RGB", view["mode"])
            with Image.open(path) as image:
                self.assertEqual(list(image.size), view["size"])
        self.assertEqual(sha256(receipt_path), result["receipt"]["sha256"])

    def test_invalid_or_outside_focus_box_is_rejected(self) -> None:
        cases = {
            "empty-x": (2, 1, 2, 7),
            "empty-y": (2, 4, 8, 4),
            "negative": (-1, 0, 3, 3),
            "outside-x": (2, 1, 12, 7),
            "outside-y": (2, 1, 8, 10),
        }
        for name, focus_box in cases.items():
            with self.subTest(name=name):
                with mock.patch.object(emitter, "_assert_git_tracked"):
                    with self.assertRaisesRegex(
                        emitter.Phase5VisionViewsError, "nonempty and fully inside"
                    ):
                        emitter.emit_phase5_vision_views(
                            self.fixture.source_relative,
                            self.fixture.output(name),
                            source_sha256=self.fixture.source_sha256,
                            focus_box=focus_box,
                        )
                self.assertFalse(self.fixture.output(name).exists())

    def test_non_rgb_source_is_rejected(self) -> None:
        source = self.fixture.source_root / "grayscale.png"
        save_pattern(source, mode="L")
        with mock.patch.object(emitter, "_assert_git_tracked"):
            with self.assertRaisesRegex(
                emitter.Phase5VisionViewsError, "mode must be RGB"
            ):
                emitter.emit_phase5_vision_views(
                    repo_relative(source),
                    self.fixture.output("non-rgb"),
                    source_sha256=sha256(source),
                    focus_box=(2, 1, 8, 7),
                )
        self.assertFalse(self.fixture.output("non-rgb").exists())

    def test_untracked_source_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            emitter.Phase5VisionViewsError, "already be tracked by Git"
        ):
            emitter.emit_phase5_vision_views(
                self.fixture.source_relative,
                self.fixture.output("untracked"),
                source_sha256=self.fixture.source_sha256,
                focus_box=(2, 1, 8, 7),
            )
        self.assertFalse(self.fixture.output("untracked").exists())

    def test_existing_output_is_rejected_without_modification(self) -> None:
        output = self.fixture.output("existing")
        output.mkdir()
        sentinel = output / "sentinel.txt"
        sentinel.write_text("keep\n", encoding="utf-8")
        with mock.patch.object(emitter, "_assert_git_tracked"):
            with self.assertRaisesRegex(
                emitter.Phase5VisionViewsError, "output already exists"
            ):
                emitter.emit_phase5_vision_views(
                    self.fixture.source_relative,
                    output,
                    source_sha256=self.fixture.source_sha256,
                    focus_box=(2, 1, 8, 7),
                )
        self.assertEqual("keep\n", sentinel.read_text(encoding="utf-8"))

    def test_late_failure_preserves_owned_staging_and_no_final_output(self) -> None:
        output = self.fixture.output("late-failure")
        with (
            mock.patch.object(emitter, "_assert_git_tracked"),
            mock.patch.object(
                emitter,
                "_rename_anchor_no_replace",
                side_effect=OSError("forced late failure"),
            ),
        ):
            with self.assertRaisesRegex(
                emitter.Phase5VisionViewsError, "debris was preserved"
            ):
                emitter.emit_phase5_vision_views(
                    self.fixture.source_relative,
                    output,
                    source_sha256=self.fixture.source_sha256,
                    focus_box=(2, 1, 8, 7),
                )
        self.assertFalse(output.exists())
        self.assertEqual(1, len(list(output.parent.glob(f".{output.name}.staging-*"))))

    def test_commit_boundary_rejects_native_and_source_mutation_before_rename(
        self,
    ) -> None:
        original_source = self.fixture.source.read_bytes()

        def mutate_native(**kwargs: object) -> None:
            staging = kwargs["staging"]
            assert isinstance(staging, Path)
            mutate_rgb_pixel(staging / "native.png")

        def mutate_source(**kwargs: object) -> None:
            del kwargs
            mutate_rgb_pixel(self.fixture.source)

        cases = {
            "native": mutate_native,
            "source": mutate_source,
        }
        for name, mutation in cases.items():
            with self.subTest(name=name):
                output = self.fixture.output(f"boundary-{name}")
                install = mock.Mock(wraps=emitter._install_owned_staging)
                try:
                    with (
                        mock.patch.object(emitter, "_assert_git_tracked"),
                        mock.patch.object(
                            emitter,
                            "_before_anchored_rename_hook",
                            side_effect=mutation,
                        ),
                        mock.patch.object(emitter, "_install_owned_staging", install),
                    ):
                        with self.assertRaises(emitter.Phase5VisionViewsError):
                            emitter.emit_phase5_vision_views(
                                self.fixture.source_relative,
                                output,
                                source_sha256=self.fixture.source_sha256,
                                focus_box=(2, 1, 8, 7),
                            )
                finally:
                    self.fixture.source.write_bytes(original_source)
                if name == "native":
                    install.assert_not_called()
                else:
                    install.assert_called_once()
                self.assertFalse(output.exists())
                self.assertEqual(
                    1, len(list(output.parent.glob(f".{output.name}.staging-*")))
                )

    def test_native_mutated_during_source_check_fails_final_snapshot(self) -> None:
        output = self.fixture.output("source-check-native-race")
        state: dict[str, Path] = {}
        original_source_check = emitter._assert_source_unchanged

        def capture_staging(**kwargs: object) -> None:
            staging = kwargs["staging"]
            assert isinstance(staging, Path)
            state["staging"] = staging

        def source_check_then_mutate(source: object) -> None:
            original_source_check(source)
            mutate_rgb_pixel(state["staging"] / "native.png")

        with (
            mock.patch.object(emitter, "_assert_git_tracked"),
            mock.patch.object(
                emitter,
                "_before_anchored_rename_hook",
                side_effect=capture_staging,
            ),
            mock.patch.object(
                emitter,
                "_assert_source_unchanged",
                side_effect=source_check_then_mutate,
            ),
        ):
            with self.assertRaisesRegex(
                emitter.Phase5VisionViewsError, "debris was preserved"
            ):
                emitter.emit_phase5_vision_views(
                    self.fixture.source_relative,
                    output,
                    source_sha256=self.fixture.source_sha256,
                    focus_box=(2, 1, 8, 7),
                )
        self.assertFalse(output.exists())
        self.assertEqual(1, len(list(output.parent.glob(f".{output.name}.staging-*"))))

    def test_all_six_entries_are_pinned_before_post_read_mutation(self) -> None:
        output = self.fixture.output("post-read-native-race")
        state: dict[str, object] = {
            "pins": [],
            "hook_calls": 0,
            "blocked": False,
            "mutated": False,
        }
        original_pin = emitter._pin_owned_entry
        original_read = emitter._read_owned_entry

        def observe_pin(
            staging: emitter.OwnedStaging, name: str
        ) -> emitter.PinnedBundleEntry:
            entry = original_pin(staging, name)
            pins = state["pins"]
            assert isinstance(pins, list)
            pins.append(entry)
            return entry

        def assert_all_pinned_then_read(
            staging: emitter.OwnedStaging,
            entry: emitter.PinnedBundleEntry,
        ) -> bytes:
            pins = state["pins"]
            assert isinstance(pins, list)
            # A prepared snapshot contributes the first six pins.  Every read
            # in either snapshot must start only after that snapshot's six.
            self.assertIn(len(pins), {6, 12})
            current = pins[-6:]
            self.assertTrue(
                all(
                    pinned.descriptor is not None or pinned.windows_handle is not None
                    for pinned in current
                )
            )
            payload = original_read(staging, entry)
            if staging.path == output and entry.name == "native.png":
                state["hook_calls"] = int(state["hook_calls"]) + 1
                try:
                    mutate_rgb_pixel(staging.path / entry.name)
                except OSError:
                    state["blocked"] = True
                else:
                    state["mutated"] = True
            return payload

        error: emitter.Phase5VisionViewsError | None = None
        result: dict[str, object] | None = None
        with (
            mock.patch.object(emitter, "_assert_git_tracked"),
            mock.patch.object(
                emitter,
                "_pin_owned_entry",
                side_effect=observe_pin,
            ),
            mock.patch.object(
                emitter,
                "_read_owned_entry",
                side_effect=assert_all_pinned_then_read,
            ),
        ):
            try:
                result = emitter.emit_phase5_vision_views(
                    self.fixture.source_relative,
                    output,
                    source_sha256=self.fixture.source_sha256,
                    focus_box=(2, 1, 8, 7),
                )
            except emitter.Phase5VisionViewsError as exc:
                error = exc

        self.assertEqual(1, state["hook_calls"])
        if os.name == "nt":
            self.assertTrue(state["blocked"])
            self.assertFalse(state["mutated"])
            self.assertIsNone(error)
            self.assertIsNotNone(result)
            self.assertTrue(output.is_dir())
        elif sys.platform.startswith("linux"):
            self.assertFalse(state["blocked"])
            self.assertTrue(state["mutated"])
            self.assertIsNone(result)
            self.assertIsInstance(error, emitter.Phase5VisionViewsError)
            assert error is not None
            self.assertNotIn("publication state is unknown", str(error))
            self.assertFalse(output.exists())
            self.assertEqual(
                1,
                len(list(output.parent.glob(f".{output.name}.staging-*"))),
            )

    def test_stable_corrupt_png_is_content_invalid_and_safely_rolled_back(
        self,
    ) -> None:
        output = self.fixture.output("stable-corrupt-png")
        state: dict[str, Path | bool] = {"corrupted": False}
        original_source_check = emitter._assert_source_unchanged

        def capture_staging(**kwargs: object) -> None:
            staging = kwargs["staging"]
            assert isinstance(staging, Path)
            state["staging"] = staging

        def source_check_then_corrupt(source: object) -> None:
            original_source_check(source)
            if not state["corrupted"]:
                staging = state["staging"]
                assert isinstance(staging, Path)
                (staging / "native.png").write_bytes(
                    b"stable bytes that are not a PNG\n"
                )
                state["corrupted"] = True

        with (
            mock.patch.object(emitter, "_assert_git_tracked"),
            mock.patch.object(
                emitter,
                "_before_anchored_rename_hook",
                side_effect=capture_staging,
            ),
            mock.patch.object(
                emitter,
                "_assert_source_unchanged",
                side_effect=source_check_then_corrupt,
            ),
        ):
            with self.assertRaises(emitter.Phase5VisionViewsError) as raised:
                emitter.emit_phase5_vision_views(
                    self.fixture.source_relative,
                    output,
                    source_sha256=self.fixture.source_sha256,
                    focus_box=(2, 1, 8, 7),
                )

        self.assertTrue(state["corrupted"])
        self.assertIn("cannot be reopened", str(raised.exception))
        self.assertNotIn("publication state is unknown", str(raised.exception))
        self.assertFalse(output.exists())
        preserved = list(output.parent.glob(f".{output.name}.staging-*"))
        self.assertEqual(1, len(preserved))
        self.assertEqual(
            b"stable bytes that are not a PNG\n",
            (preserved[0] / "native.png").read_bytes(),
        )

    def test_commit_linearization_order_has_no_post_snapshot_file_check(
        self,
    ) -> None:
        output = self.fixture.output("linearization-order")
        events: list[str] = []
        original_snapshot = emitter._snapshot_bundle
        original_source_check = emitter._assert_source_unchanged
        original_install = emitter._install_owned_staging

        def snapshot(*args: object, **kwargs: object) -> object:
            events.append("snapshot")
            return original_snapshot(*args, **kwargs)

        def source_check(*args: object, **kwargs: object) -> None:
            events.append("source")
            original_source_check(*args, **kwargs)

        def install(*args: object, **kwargs: object) -> None:
            original_install(*args, **kwargs)
            events.append("rename")

        with (
            mock.patch.object(emitter, "_assert_git_tracked"),
            mock.patch.object(emitter, "_snapshot_bundle", side_effect=snapshot),
            mock.patch.object(
                emitter, "_assert_source_unchanged", side_effect=source_check
            ),
            mock.patch.object(emitter, "_install_owned_staging", side_effect=install),
        ):
            emitter.emit_phase5_vision_views(
                self.fixture.source_relative,
                output,
                source_sha256=self.fixture.source_sha256,
                focus_box=(2, 1, 8, 7),
            )
        self.assertEqual(["snapshot", "source", "rename", "snapshot"], events)

    def test_missing_output_parent_never_reaches_path_mkdir_boundary(self) -> None:
        missing_parent = self.fixture.output_root / "missing-parent" / "nested"
        output = missing_parent / "bundle"
        with (
            mock.patch.object(emitter, "_assert_git_tracked"),
            mock.patch.object(
                Path,
                "mkdir",
                side_effect=AssertionError("unanchored mkdir must not run"),
            ) as mkdir,
        ):
            with self.assertRaisesRegex(
                emitter.Phase5VisionViewsError,
                "output parent must already exist",
            ):
                emitter.emit_phase5_vision_views(
                    self.fixture.source_relative,
                    output,
                    source_sha256=self.fixture.source_sha256,
                    focus_box=(2, 1, 8, 7),
                )
        mkdir.assert_not_called()
        self.assertFalse(missing_parent.exists())

    def test_nonprivate_parent_is_rejected_only_where_posix_requires_it(
        self,
    ) -> None:
        parent = self.fixture.output_root / "nonprivate-parent"
        parent.mkdir(mode=0o755)
        output = parent / "bundle"
        with mock.patch.object(emitter, "_assert_git_tracked"):
            if sys.platform.startswith("linux"):
                with self.assertRaisesRegex(
                    emitter.Phase5VisionViewsError,
                    "caller-provisioned private directory",
                ):
                    emitter.emit_phase5_vision_views(
                        self.fixture.source_relative,
                        output,
                        source_sha256=self.fixture.source_sha256,
                        focus_box=(2, 1, 8, 7),
                    )
                self.assertEqual([], list(parent.iterdir()))
            else:
                result = emitter.emit_phase5_vision_views(
                    self.fixture.source_relative,
                    output,
                    source_sha256=self.fixture.source_sha256,
                    focus_box=(2, 1, 8, 7),
                )
                self.assertTrue(result["valid"])
                self.assertTrue(output.is_dir())

    def test_staging_create_to_first_handle_boundary_never_owns_foreign(
        self,
    ) -> None:
        parent = self.fixture.output_root / "create-handle-race-parent"
        parent.mkdir(mode=0o700)
        output = parent / "bundle"
        moved_original = parent / "created-original"
        foreign_source = parent / "foreign-source"
        foreign_source.mkdir(mode=0o700)
        foreign_sentinel = foreign_source / "foreign-sentinel.txt"
        foreign_sentinel.write_text("foreign-safe\n", encoding="utf-8")
        state: dict[str, object] = {
            "called": False,
            "blocked": False,
            "swapped": False,
        }

        def exchange_before_first_handle(**kwargs: object) -> None:
            staging = kwargs["staging"]
            atomic_handle = kwargs["atomic_handle"]
            assert isinstance(staging, Path)
            assert isinstance(atomic_handle, bool)
            state.update(
                called=True,
                staging=staging,
                atomic_handle=atomic_handle,
            )
            try:
                staging.rename(moved_original)
            except OSError:
                state["blocked"] = True
                return
            state["swapped"] = True
            (moved_original / "created-original-sentinel.txt").write_text(
                "created-original-safe\n",
                encoding="utf-8",
            )
            foreign_source.rename(staging)

        error: BaseException | None = None
        result: dict[str, object] | None = None
        with (
            mock.patch.object(emitter, "_assert_git_tracked"),
            mock.patch.object(
                emitter,
                "_staging_create_boundary_hook",
                side_effect=exchange_before_first_handle,
            ),
        ):
            try:
                result = emitter.emit_phase5_vision_views(
                    self.fixture.source_relative,
                    output,
                    source_sha256=self.fixture.source_sha256,
                    focus_box=(2, 1, 8, 7),
                )
            except emitter.Phase5VisionViewsError as exc:
                error = exc

        self.assertTrue(state["called"])
        if os.name == "nt":
            self.assertTrue(state["atomic_handle"])
            self.assertTrue(state["blocked"])
            self.assertIsNone(error)
            self.assertIsNotNone(result)
            self.assertTrue(output.is_dir())
            self.assertEqual(
                ["foreign-sentinel.txt"],
                sorted(path.name for path in foreign_source.iterdir()),
            )
            self.assertFalse(moved_original.exists())
        elif sys.platform.startswith("linux"):
            self.assertFalse(state["atomic_handle"])
            self.assertTrue(state["swapped"])
            self.assertIsInstance(error, emitter.Phase5VisionViewsError)
            self.assertIsNone(result)
            self.assertFalse(output.exists())
            staging = state["staging"]
            assert isinstance(staging, Path)
            self.assertEqual(
                ["foreign-sentinel.txt"],
                sorted(path.name for path in staging.iterdir()),
            )
            self.assertEqual(
                ["created-original-sentinel.txt"],
                sorted(path.name for path in moved_original.iterdir()),
            )

    def test_parent_swap_before_anchor_open_never_writes_outside(self) -> None:
        parent = self.fixture.output_root / "mkdtemp-race-parent"
        parent.mkdir(mode=0o700)
        output = parent / "bundle"
        moved_parent = parent.with_name(f"{parent.name}-original")
        outside = self.fixture.output_root / "mkdtemp-race-outside"
        outside.mkdir()
        sentinel = outside / "sentinel.txt"
        sentinel.write_text("outside-safe\n", encoding="utf-8")
        used_symlink = False

        def exchange_parent(**kwargs: object) -> None:
            nonlocal used_symlink
            prepared = kwargs["parent"]
            assert isinstance(prepared, emitter.PreparedParent)
            prepared.path.rename(moved_parent)
            try:
                prepared.path.symlink_to(outside, target_is_directory=True)
                used_symlink = True
            except OSError:
                prepared.path.mkdir()

        try:
            with (
                mock.patch.object(emitter, "_assert_git_tracked"),
                mock.patch.object(
                    emitter,
                    "_before_parent_anchor_open_hook",
                    side_effect=exchange_parent,
                ),
            ):
                with self.assertRaises(emitter.Phase5VisionViewsError):
                    emitter.emit_phase5_vision_views(
                        self.fixture.source_relative,
                        output,
                        source_sha256=self.fixture.source_sha256,
                        focus_box=(2, 1, 8, 7),
                    )
            self.assertEqual("outside-safe\n", sentinel.read_text(encoding="utf-8"))
            self.assertEqual(
                ["sentinel.txt"], sorted(path.name for path in outside.iterdir())
            )
            self.assertEqual([], list(moved_parent.iterdir()))
        finally:
            if os.path.lexists(parent):
                if used_symlink:
                    parent.unlink()
                else:
                    parent.rmdir()
            if moved_parent.exists():
                moved_parent.rename(parent)

    def test_final_syscall_parent_exchange_cannot_touch_foreign_sentinel(
        self,
    ) -> None:
        parent = self.fixture.output_root / "anchored-rename-parent"
        parent.mkdir(mode=0o700)
        output = parent / "bundle"
        moved_parent = parent.with_name(f"{parent.name}-original")
        outside = self.fixture.output_root / "anchored-rename-outside"
        outside.mkdir()
        outside_sentinel = outside / "sentinel.txt"
        outside_sentinel.write_text("outside-safe\n", encoding="utf-8")
        state: dict[str, object] = {"blocked": False, "swapped": False}

        def exchange_at_syscall_boundary(**kwargs: object) -> None:
            self.assertIn("source_name", kwargs)
            self.assertIn("destination_name", kwargs)
            try:
                parent.rename(moved_parent)
            except OSError:
                state["blocked"] = True
                return
            state["swapped"] = True
            used_symlink = False
            try:
                parent.symlink_to(outside, target_is_directory=True)
                used_symlink = True
            except OSError:
                parent.mkdir()
            fake_output = parent / output.name
            fake_output.mkdir()
            fake_sentinel = fake_output / "do-not-touch.txt"
            fake_sentinel.write_text("foreign-output\n", encoding="utf-8")
            state.update(
                used_symlink=used_symlink,
                fake_output=fake_output,
                fake_sentinel=fake_sentinel,
            )

        error: BaseException | None = None
        result: dict[str, object] | None = None
        try:
            with (
                mock.patch.object(emitter, "_assert_git_tracked"),
                mock.patch.object(
                    emitter,
                    "_before_rename_syscall_hook",
                    side_effect=exchange_at_syscall_boundary,
                ),
            ):
                try:
                    result = emitter.emit_phase5_vision_views(
                        self.fixture.source_relative,
                        output,
                        source_sha256=self.fixture.source_sha256,
                        focus_box=(2, 1, 8, 7),
                    )
                except emitter.Phase5VisionViewsError as exc:
                    error = exc
            self.assertEqual(
                "outside-safe\n", outside_sentinel.read_text(encoding="utf-8")
            )
            fake_sentinel = state.get("fake_sentinel")
            if isinstance(fake_sentinel, Path):
                self.assertEqual(
                    "foreign-output\n", fake_sentinel.read_text(encoding="utf-8")
                )
            if state["blocked"]:
                self.assertIsNone(error)
                self.assertIsNotNone(result)
            else:
                self.assertIsInstance(error, emitter.Phase5VisionViewsError)
                self.assertIsNone(result)
        finally:
            fake_sentinel = state.get("fake_sentinel")
            fake_output = state.get("fake_output")
            if isinstance(fake_sentinel, Path) and fake_sentinel.exists():
                fake_sentinel.unlink()
            if isinstance(fake_output, Path) and fake_output.exists():
                fake_output.rmdir()
            if state["swapped"] and os.path.lexists(parent):
                if state.get("used_symlink"):
                    parent.unlink()
                else:
                    parent.rmdir()
            if moved_parent.exists():
                moved_parent.rename(parent)
        if state["blocked"]:
            self.assertTrue(output.is_dir())
        else:
            self.assertFalse(output.exists())
            self.assertEqual(1, len(list(parent.glob(f".{output.name}.staging-*"))))
        if os.name == "nt":
            self.assertTrue(state["blocked"])
        elif sys.platform.startswith("linux"):
            self.assertTrue(state["swapped"])

    def test_true_rename_boundary_never_installs_foreign_staging(self) -> None:
        output = self.fixture.output("staging-claim-race")
        moved_original = self.fixture.output("staging-claim-race-original")
        state: dict[str, object] = {
            "blocked": False,
            "swapped": False,
            "called": False,
        }

        def exchange_staging_at_syscall(**kwargs: object) -> None:
            staging = kwargs["staging"]
            destination_name = kwargs["destination_name"]
            assert isinstance(staging, Path)
            assert isinstance(destination_name, str)
            state["called"] = True
            self.assertEqual(output.name, destination_name)
            try:
                staging.rename(moved_original)
            except OSError:
                state["blocked"] = True
                return
            state["swapped"] = True
            staging.mkdir()
            (staging / "foreign-sentinel.txt").write_text(
                "foreign-staging\n", encoding="utf-8"
            )

        error: BaseException | None = None
        result: dict[str, object] | None = None
        with (
            mock.patch.object(emitter, "_assert_git_tracked"),
            mock.patch.object(
                emitter,
                "_before_rename_syscall_hook",
                side_effect=exchange_staging_at_syscall,
            ),
        ):
            try:
                result = emitter.emit_phase5_vision_views(
                    self.fixture.source_relative,
                    output,
                    source_sha256=self.fixture.source_sha256,
                    focus_box=(2, 1, 8, 7),
                )
            except emitter.Phase5VisionViewsError as exc:
                error = exc

        self.assertTrue(state["called"])
        if os.name == "nt":
            self.assertTrue(state["blocked"])
            self.assertIsNone(error)
            self.assertIsNotNone(result)
            self.assertTrue(output.is_dir())
            self.assertFalse(moved_original.exists())
        elif sys.platform.startswith("linux"):
            self.assertTrue(state["swapped"])
            self.assertIsInstance(error, emitter.Phase5VisionViewsError)
            self.assertIsNone(result)
            self.assertFalse(output.exists())
            self.assertEqual(
                sorted(
                    [
                        "focus200.png",
                        "focus400.png",
                        "full25.png",
                        "full50.png",
                        "native.png",
                        "receipt.json",
                    ]
                ),
                sorted(path.name for path in moved_original.iterdir()),
            )
            quarantines = list(output.parent.glob(f".{output.name}.foreign-*"))
            self.assertEqual(1, len(quarantines))
            self.assertEqual(
                "foreign-staging\n",
                (quarantines[0] / "foreign-sentinel.txt").read_text(encoding="utf-8"),
            )

    def test_staging_create_close_failure_does_not_override_primary(self) -> None:
        output = self.fixture.output("staging-create-close-primary")
        state: dict[str, object] = {
            "armed": False,
            "target": None,
            "close_calls": 0,
        }

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(emitter, "_assert_git_tracked"))
            if sys.platform.startswith("linux"):
                original_fstat = emitter.os.fstat
                original_close = emitter.os.close

                def arm_linux_create(**kwargs: object) -> None:
                    del kwargs
                    state["armed"] = True

                def fail_staging_fstat(descriptor: int) -> os.stat_result:
                    if state["armed"] and state["target"] is None:
                        state["target"] = descriptor
                        raise emitter.Phase5VisionViewsError(
                            "primary staging create failure"
                        )
                    return original_fstat(descriptor)

                def close_target_then_fail(descriptor: int) -> None:
                    original_close(descriptor)
                    if descriptor == state["target"]:
                        state["close_calls"] = int(state["close_calls"]) + 1
                        raise OSError("secondary staging create close failure")

                stack.enter_context(
                    mock.patch.object(
                        emitter,
                        "_staging_create_boundary_hook",
                        side_effect=arm_linux_create,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        emitter.os,
                        "fstat",
                        side_effect=fail_staging_fstat,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        emitter.os,
                        "close",
                        side_effect=close_target_then_fail,
                    )
                )
            elif os.name == "nt":
                original_create = emitter._windows_create_directory_handle
                original_close = emitter._windows_close_handle

                def capture_windows_create(parent_handle: int, name: str) -> int:
                    handle = original_create(parent_handle, name)
                    state["target"] = handle
                    return handle

                def fail_windows_create_hook(**kwargs: object) -> None:
                    del kwargs
                    raise emitter.Phase5VisionViewsError(
                        "primary staging create failure"
                    )

                def close_target_then_fail(handle: int) -> None:
                    original_close(handle)
                    if handle == state["target"]:
                        state["close_calls"] = int(state["close_calls"]) + 1
                        raise OSError("secondary staging create close failure")

                stack.enter_context(
                    mock.patch.object(
                        emitter,
                        "_windows_create_directory_handle",
                        side_effect=capture_windows_create,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        emitter,
                        "_staging_create_boundary_hook",
                        side_effect=fail_windows_create_hook,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        emitter,
                        "_windows_close_handle",
                        side_effect=close_target_then_fail,
                    )
                )
            else:
                self.skipTest("staging handle close contract is Windows/Linux only")

            with self.assertRaises(emitter.Phase5VisionViewsError) as raised:
                emitter.emit_phase5_vision_views(
                    self.fixture.source_relative,
                    output,
                    source_sha256=self.fixture.source_sha256,
                    focus_box=(2, 1, 8, 7),
                )

        self.assertIn("primary staging create failure", str(raised.exception))
        self.assertNotIn(
            "secondary staging create close failure", str(raised.exception)
        )
        self.assertEqual(1, state["close_calls"])

    def test_file_write_close_failure_does_not_override_primary(self) -> None:
        output = self.fixture.output("file-write-close-primary")
        state: dict[str, int | None] = {"target": None, "close_calls": 0}
        original_close = emitter.os.close

        def fail_write(descriptor: int, payload: bytes) -> None:
            del payload
            state["target"] = descriptor
            raise emitter.Phase5VisionViewsError("primary file write failure")

        def close_target_then_fail(descriptor: int) -> None:
            original_close(descriptor)
            if descriptor == state["target"]:
                state["close_calls"] = int(state["close_calls"] or 0) + 1
                raise OSError("secondary file write close failure")

        with (
            mock.patch.object(emitter, "_assert_git_tracked"),
            mock.patch.object(emitter, "_write_all", side_effect=fail_write),
            mock.patch.object(
                emitter.os,
                "close",
                side_effect=close_target_then_fail,
            ),
        ):
            with self.assertRaises(emitter.Phase5VisionViewsError) as raised:
                emitter.emit_phase5_vision_views(
                    self.fixture.source_relative,
                    output,
                    source_sha256=self.fixture.source_sha256,
                    focus_box=(2, 1, 8, 7),
                )

        self.assertIn("primary file write failure", str(raised.exception))
        self.assertNotIn("secondary file write close failure", str(raised.exception))
        self.assertEqual(1, state["close_calls"])

    def test_pinned_read_close_failure_does_not_override_primary(self) -> None:
        output = self.fixture.output("pinned-read-close-primary")
        pinned: list[int] = []
        state = {"close_calls": 0, "close_failed": False, "hook_failed": False}
        original_pin = emitter._pin_owned_entry
        original_read = emitter._read_owned_entry

        def capture_pin(
            staging: emitter.OwnedStaging, name: str
        ) -> emitter.PinnedBundleEntry:
            entry = original_pin(staging, name)
            handle = (
                entry.descriptor
                if entry.descriptor is not None
                else entry.windows_handle
            )
            assert handle is not None
            pinned.append(handle)
            return entry

        def fail_after_read(
            staging: emitter.OwnedStaging,
            entry: emitter.PinnedBundleEntry,
        ) -> bytes:
            payload = original_read(staging, entry)
            if not state["hook_failed"]:
                state["hook_failed"] = True
                raise emitter.Phase5VisionViewsError("primary pinned read failure")
            return payload

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(emitter, "_assert_git_tracked"))
            stack.enter_context(
                mock.patch.object(
                    emitter,
                    "_pin_owned_entry",
                    side_effect=capture_pin,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    emitter,
                    "_read_owned_entry",
                    side_effect=fail_after_read,
                )
            )
            if sys.platform.startswith("linux"):
                original_close = emitter.os.close

                def close_pin_then_maybe_fail(descriptor: int) -> None:
                    original_close(descriptor)
                    if descriptor in pinned:
                        state["close_calls"] += 1
                        if not state["close_failed"]:
                            state["close_failed"] = True
                            raise OSError("secondary pinned close failure")

                stack.enter_context(
                    mock.patch.object(
                        emitter.os,
                        "close",
                        side_effect=close_pin_then_maybe_fail,
                    )
                )
            elif os.name == "nt":
                original_close = emitter._windows_close_handle

                def close_pin_then_maybe_fail(handle: int) -> None:
                    original_close(handle)
                    if handle in pinned:
                        state["close_calls"] += 1
                        if not state["close_failed"]:
                            state["close_failed"] = True
                            raise OSError("secondary pinned close failure")

                stack.enter_context(
                    mock.patch.object(
                        emitter,
                        "_windows_close_handle",
                        side_effect=close_pin_then_maybe_fail,
                    )
                )
            else:
                self.skipTest("pinned handle close contract is Windows/Linux only")

            with self.assertRaises(emitter.Phase5VisionViewsError) as raised:
                emitter.emit_phase5_vision_views(
                    self.fixture.source_relative,
                    output,
                    source_sha256=self.fixture.source_sha256,
                    focus_box=(2, 1, 8, 7),
                )

        self.assertIn("primary pinned read failure", str(raised.exception))
        self.assertNotIn("secondary pinned close failure", str(raised.exception))
        self.assertEqual(6, state["close_calls"])

    def test_committed_output_survives_staging_handle_close_failure(self) -> None:
        output = self.fixture.output("committed-close-failure")
        original_close = emitter._close_owned_staging

        def close_then_fail(staging: emitter.OwnedStaging) -> None:
            original_close(staging)
            raise OSError("forced post-commit handle close failure")

        with (
            mock.patch.object(emitter, "_assert_git_tracked"),
            mock.patch.object(
                emitter,
                "_close_owned_staging",
                side_effect=close_then_fail,
            ) as close_mock,
        ):
            result = emitter.emit_phase5_vision_views(
                self.fixture.source_relative,
                output,
                source_sha256=self.fixture.source_sha256,
                focus_box=(2, 1, 8, 7),
            )

        self.assertTrue(result["valid"])
        close_mock.assert_called_once()
        self.assertTrue(output.is_dir())
        self.assertEqual(
            {
                "focus200.png",
                "focus400.png",
                "full25.png",
                "full50.png",
                "native.png",
                "receipt.json",
            },
            {path.name for path in output.iterdir()},
        )

    def test_committed_output_survives_parent_anchor_close_failure(self) -> None:
        output = self.fixture.output("committed-parent-close-failure")
        original_close = emitter._close_parent_anchor

        def close_then_fail(
            anchor: emitter.ParentAnchor,
            *,
            suppress_errors: bool = False,
        ) -> None:
            original_close(anchor, suppress_errors=suppress_errors)
            raise OSError("forced post-commit parent-anchor close failure")

        with (
            mock.patch.object(emitter, "_assert_git_tracked"),
            mock.patch.object(
                emitter,
                "_close_parent_anchor",
                side_effect=close_then_fail,
            ) as close_mock,
        ):
            result = emitter.emit_phase5_vision_views(
                self.fixture.source_relative,
                output,
                source_sha256=self.fixture.source_sha256,
                focus_box=(2, 1, 8, 7),
            )

        self.assertTrue(result["valid"])
        close_mock.assert_called_once()
        self.assertTrue((output / "receipt.json").is_file())

    def test_commit_retries_first_and_second_anchor_read_errors(self) -> None:
        for failures in (1, 2):
            with self.subTest(failures=failures):
                output = self.fixture.output(f"anchor-retry-{failures}")
                state = {"published": False, "faults": 0}
                original_rename = emitter._rename_anchor_no_replace
                original_assert = emitter._assert_anchor_visible

                def observe_rename(
                    staging: emitter.OwnedStaging,
                    destination_name: str,
                    **kwargs: object,
                ) -> None:
                    original_rename(staging, destination_name, **kwargs)
                    if destination_name == output.name:
                        state["published"] = True

                def flaky_anchor(anchor: emitter.ParentAnchor) -> None:
                    if state["published"] and state["faults"] < failures:
                        state["faults"] += 1
                        raise OSError("forced transient installed-anchor read")
                    original_assert(anchor)

                with (
                    mock.patch.object(emitter, "_assert_git_tracked"),
                    mock.patch.object(
                        emitter,
                        "_rename_anchor_no_replace",
                        side_effect=observe_rename,
                    ),
                    mock.patch.object(
                        emitter,
                        "_assert_anchor_visible",
                        side_effect=flaky_anchor,
                    ),
                ):
                    result = emitter.emit_phase5_vision_views(
                        self.fixture.source_relative,
                        output,
                        source_sha256=self.fixture.source_sha256,
                        focus_box=(2, 1, 8, 7),
                    )

                self.assertEqual(failures, state["faults"])
                self.assertTrue(result["valid"])
                self.assertTrue((output / "receipt.json").is_file())

    def test_permanent_installed_anchor_io_failure_is_unknown(self) -> None:
        output = self.fixture.output("anchor-permanent-unknown")
        state = {"published": False, "faults": 0}
        original_rename = emitter._rename_anchor_no_replace
        original_assert = emitter._assert_anchor_visible

        def observe_rename(
            staging: emitter.OwnedStaging,
            destination_name: str,
            **kwargs: object,
        ) -> None:
            original_rename(staging, destination_name, **kwargs)
            if destination_name == output.name:
                state["published"] = True

        def unreadable_anchor(anchor: emitter.ParentAnchor) -> None:
            if state["published"]:
                state["faults"] += 1
                raise OSError("forced permanent installed-anchor read")
            original_assert(anchor)

        with (
            mock.patch.object(emitter, "_assert_git_tracked"),
            mock.patch.object(
                emitter,
                "_rename_anchor_no_replace",
                side_effect=observe_rename,
            ),
            mock.patch.object(
                emitter,
                "_assert_anchor_visible",
                side_effect=unreadable_anchor,
            ),
        ):
            with self.assertRaisesRegex(
                emitter.Phase5VisionViewsError,
                "publication state is unknown",
            ):
                emitter.emit_phase5_vision_views(
                    self.fixture.source_relative,
                    output,
                    source_sha256=self.fixture.source_sha256,
                    focus_box=(2, 1, 8, 7),
                )

        self.assertEqual(3, state["faults"])
        self.assertTrue(output.is_dir())
        self.assertEqual(6, len(list(output.iterdir())))
        self.assertEqual([], list(output.parent.glob(f".{output.name}.staging-*")))

    @unittest.skipUnless(os.name == "nt", "Windows exact-handle commit test")
    def test_windows_commit_retries_first_and_second_identity_read_errors(
        self,
    ) -> None:
        expected_inventory = {
            "focus200.png",
            "focus400.png",
            "full25.png",
            "full50.png",
            "native.png",
            "receipt.json",
        }
        for failures in (1, 2):
            with self.subTest(failures=failures):
                output = self.fixture.output(f"identity-retry-{failures}")
                state = {"renamed": False, "faults": 0}
                original_rename = emitter._windows_rename_directory_handle_no_replace
                original_assert = emitter._assert_owned_staging

                def observe_rename(handle: int, destination: Path) -> None:
                    original_rename(handle, destination)
                    if destination == output:
                        state["renamed"] = True

                def flaky_identity(*args: object, **kwargs: object) -> None:
                    staging = args[0]
                    assert isinstance(staging, emitter.OwnedStaging)
                    if (
                        state["renamed"]
                        and staging.path == output
                        and state["faults"] < failures
                    ):
                        state["faults"] += 1
                        raise OSError("forced transient destination identity read")
                    original_assert(*args, **kwargs)

                with (
                    mock.patch.object(emitter, "_assert_git_tracked"),
                    mock.patch.object(
                        emitter,
                        "_windows_rename_directory_handle_no_replace",
                        side_effect=observe_rename,
                    ),
                    mock.patch.object(
                        emitter,
                        "_assert_owned_staging",
                        side_effect=flaky_identity,
                    ),
                ):
                    result = emitter.emit_phase5_vision_views(
                        self.fixture.source_relative,
                        output,
                        source_sha256=self.fixture.source_sha256,
                        focus_box=(2, 1, 8, 7),
                    )

                self.assertEqual(failures, state["faults"])
                self.assertTrue(result["valid"])
                self.assertEqual(
                    expected_inventory,
                    {path.name for path in output.iterdir()},
                )
                self.assertEqual(
                    [], list(output.parent.glob(f".{output.name}.staging-*"))
                )

    def test_commit_retries_first_and_second_byte_read_errors(self) -> None:
        for failures in (1, 2):
            with self.subTest(failures=failures):
                output = self.fixture.output(f"bytes-retry-{failures}")
                state = {"published": False, "faults": 0}
                original_rename = emitter._rename_anchor_no_replace
                original_read = emitter._read_owned_entry

                def observe_rename(
                    staging: emitter.OwnedStaging,
                    destination_name: str,
                    **kwargs: object,
                ) -> None:
                    original_rename(staging, destination_name, **kwargs)
                    if destination_name == output.name:
                        state["published"] = True

                def flaky_read(*args: object, **kwargs: object) -> bytes:
                    if state["published"] and state["faults"] < failures:
                        state["faults"] += 1
                        raise OSError("forced transient installed-byte read")
                    return original_read(*args, **kwargs)

                with (
                    mock.patch.object(emitter, "_assert_git_tracked"),
                    mock.patch.object(
                        emitter,
                        "_rename_anchor_no_replace",
                        side_effect=observe_rename,
                    ),
                    mock.patch.object(
                        emitter,
                        "_read_owned_entry",
                        side_effect=flaky_read,
                    ),
                ):
                    result = emitter.emit_phase5_vision_views(
                        self.fixture.source_relative,
                        output,
                        source_sha256=self.fixture.source_sha256,
                        focus_box=(2, 1, 8, 7),
                    )

                self.assertEqual(failures, state["faults"])
                self.assertTrue(result["valid"])
                self.assertEqual(
                    result["receipt"]["sha256"],
                    sha256(output / "receipt.json"),
                )

    def test_permanent_installed_byte_io_failure_is_unknown(self) -> None:
        output = self.fixture.output("bytes-permanent-unknown")
        state = {"published": False, "faults": 0}
        original_rename = emitter._rename_anchor_no_replace
        original_read = emitter._read_owned_entry

        def observe_rename(
            staging: emitter.OwnedStaging,
            destination_name: str,
            **kwargs: object,
        ) -> None:
            original_rename(staging, destination_name, **kwargs)
            if destination_name == output.name:
                state["published"] = True

        def unreadable_bytes(*args: object, **kwargs: object) -> bytes:
            if state["published"]:
                state["faults"] += 1
                raise OSError("forced permanent installed-byte read")
            return original_read(*args, **kwargs)

        with (
            mock.patch.object(emitter, "_assert_git_tracked"),
            mock.patch.object(
                emitter,
                "_rename_anchor_no_replace",
                side_effect=observe_rename,
            ),
            mock.patch.object(
                emitter,
                "_read_owned_entry",
                side_effect=unreadable_bytes,
            ),
        ):
            with self.assertRaisesRegex(
                emitter.Phase5VisionViewsError,
                "publication state is unknown",
            ):
                emitter.emit_phase5_vision_views(
                    self.fixture.source_relative,
                    output,
                    source_sha256=self.fixture.source_sha256,
                    focus_box=(2, 1, 8, 7),
                )

        self.assertEqual(3, state["faults"])
        self.assertTrue(output.is_dir())
        self.assertEqual(6, len(list(output.iterdir())))
        self.assertEqual([], list(output.parent.glob(f".{output.name}.staging-*")))

    @unittest.skipUnless(os.name == "nt", "Windows exact-handle commit test")
    def test_windows_unknown_commit_preserves_output_despite_close_failure(
        self,
    ) -> None:
        output = self.fixture.output("unknown-commit-close-failure")
        state = {"renamed": False, "faults": 0}
        original_rename = emitter._windows_rename_directory_handle_no_replace
        original_assert = emitter._assert_owned_staging
        original_close = emitter._close_owned_staging

        def observe_rename(handle: int, destination: Path) -> None:
            original_rename(handle, destination)
            if destination == output:
                state["renamed"] = True

        def unreadable_identity(*args: object, **kwargs: object) -> None:
            staging = args[0]
            assert isinstance(staging, emitter.OwnedStaging)
            if state["renamed"] and staging.path == output:
                state["faults"] += 1
                raise OSError("forced persistent destination identity read failure")
            original_assert(*args, **kwargs)

        def close_then_fail(staging: emitter.OwnedStaging) -> None:
            original_close(staging)
            raise OSError("forced unknown-state handle close failure")

        with (
            mock.patch.object(emitter, "_assert_git_tracked"),
            mock.patch.object(
                emitter,
                "_windows_rename_directory_handle_no_replace",
                side_effect=observe_rename,
            ),
            mock.patch.object(
                emitter,
                "_assert_owned_staging",
                side_effect=unreadable_identity,
            ),
            mock.patch.object(
                emitter,
                "_close_owned_staging",
                side_effect=close_then_fail,
            ) as close_mock,
        ):
            with self.assertRaisesRegex(
                emitter.Phase5VisionViewsError,
                "publication state is unknown",
            ):
                emitter.emit_phase5_vision_views(
                    self.fixture.source_relative,
                    output,
                    source_sha256=self.fixture.source_sha256,
                    focus_box=(2, 1, 8, 7),
                )

        self.assertEqual(3, state["faults"])
        close_mock.assert_called_once()
        self.assertTrue(output.is_dir())
        self.assertTrue((output / "receipt.json").is_file())
        self.assertEqual([], list(output.parent.glob(f".{output.name}.staging-*")))

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "Linux renameat2 unknown-publication test",
    )
    def test_linux_permanent_identity_io_failure_stays_unknown_without_rename(
        self,
    ) -> None:
        baseline = self.fixture.output("linux-unknown-baseline")
        self.fixture.emit("linux-unknown-baseline")
        expected_hashes = {
            path.name: sha256(path) for path in baseline.iterdir() if path.is_file()
        }
        self.assertEqual(6, len(expected_hashes))

        output = self.fixture.output("linux-unknown-output")
        state = {
            "published": False,
            "identity_faults": 0,
            "rename_calls": 0,
            "additional_renames": 0,
        }
        original_rename = emitter._linux_rename_anchor_no_replace
        original_assert = emitter._assert_owned_staging

        def observe_rename(
            anchor: emitter.ParentAnchor,
            source_name: str,
            destination_name: str,
        ) -> None:
            if state["published"]:
                state["additional_renames"] += 1
            original_rename(anchor, source_name, destination_name)
            state["rename_calls"] += 1
            if destination_name == output.name:
                state["published"] = True

        def permanently_unreadable_identity(*args: object, **kwargs: object) -> None:
            staging = args[0]
            assert isinstance(staging, emitter.OwnedStaging)
            if state["published"] and staging.path == output:
                state["identity_faults"] += 1
                raise OSError("forced permanent Linux destination identity I/O")
            original_assert(*args, **kwargs)

        with (
            mock.patch.object(emitter, "_assert_git_tracked"),
            mock.patch.object(
                emitter,
                "_linux_rename_anchor_no_replace",
                side_effect=observe_rename,
            ),
            mock.patch.object(
                emitter,
                "_assert_owned_staging",
                side_effect=permanently_unreadable_identity,
            ),
        ):
            with self.assertRaisesRegex(
                emitter.Phase5VisionViewsError,
                "publication state is unknown",
            ):
                emitter.emit_phase5_vision_views(
                    self.fixture.source_relative,
                    output,
                    source_sha256=self.fixture.source_sha256,
                    focus_box=(2, 1, 8, 7),
                )

        self.assertEqual(3, state["identity_faults"])
        self.assertEqual(2, state["rename_calls"])
        self.assertEqual(0, state["additional_renames"])
        self.assertEqual(
            expected_hashes,
            {path.name: sha256(path) for path in output.iterdir() if path.is_file()},
        )
        self.assertEqual([], list(output.parent.glob(f".{output.name}.staging-*")))
        self.assertEqual([], list(output.parent.glob(f".{output.name}.foreign-*")))

    def test_true_rename_hook_cannot_mutate_source_after_final_binding(self) -> None:
        output = self.fixture.output("rename-hook-source-mutation")
        original_source = self.fixture.source.read_bytes()

        def mutate_source_at_rename(**kwargs: object) -> None:
            self.assertEqual(output.name, kwargs["destination_name"])
            mutate_rgb_pixel(self.fixture.source)

        try:
            with (
                mock.patch.object(emitter, "_assert_git_tracked"),
                mock.patch.object(
                    emitter,
                    "_before_rename_syscall_hook",
                    side_effect=mutate_source_at_rename,
                ),
            ):
                with self.assertRaises(emitter.Phase5VisionViewsError):
                    emitter.emit_phase5_vision_views(
                        self.fixture.source_relative,
                        output,
                        source_sha256=self.fixture.source_sha256,
                        focus_box=(2, 1, 8, 7),
                    )
        finally:
            self.fixture.source.write_bytes(original_source)

        self.assertFalse(output.exists())
        self.assertEqual(
            1,
            len(list(output.parent.glob(f".{output.name}.staging-*"))),
        )

    def test_sha_mismatch_and_absolute_source_are_rejected(self) -> None:
        with mock.patch.object(emitter, "_assert_git_tracked"):
            with self.assertRaisesRegex(
                emitter.Phase5VisionViewsError, "SHA-256 mismatch"
            ):
                emitter.emit_phase5_vision_views(
                    self.fixture.source_relative,
                    self.fixture.output("wrong-sha"),
                    source_sha256="0" * 64,
                    focus_box=(2, 1, 8, 7),
                )
        with self.assertRaisesRegex(
            emitter.Phase5VisionViewsError,
            "repository-relative POSIX path|escapes the repository",
        ):
            emitter.emit_phase5_vision_views(
                str(self.fixture.source.resolve()),
                self.fixture.output("absolute-source"),
                source_sha256=self.fixture.source_sha256,
                focus_box=(2, 1, 8, 7),
            )

    def test_output_outside_temp_is_rejected(self) -> None:
        output = self.fixture.source_root / "persistent-bundle"
        with mock.patch.object(emitter, "_assert_git_tracked"):
            with self.assertRaisesRegex(
                emitter.Phase5VisionViewsError, "strict descendant"
            ):
                emitter.emit_phase5_vision_views(
                    self.fixture.source_relative,
                    output,
                    source_sha256=self.fixture.source_sha256,
                    focus_box=(2, 1, 8, 7),
                )
        self.assertFalse(output.exists())

    def test_os_temp_output_and_cli_json_result(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="phase5-vision-os-output-test-"
        ) as temporary:
            output = Path(temporary) / "bundle"
            stdout = io.StringIO()
            with (
                mock.patch.object(emitter, "_assert_git_tracked"),
                contextlib.redirect_stdout(stdout),
            ):
                returncode = emitter.main(
                    [
                        self.fixture.source_relative,
                        str(output),
                        "--source-sha256",
                        self.fixture.source_sha256,
                        "--focus-box",
                        "2,1,8,7",
                    ]
                )
            result = json.loads(stdout.getvalue())
            self.assertEqual(0, returncode)
            self.assertTrue(result["valid"])
            self.assertTrue(output.is_dir())
            self.assertEqual(list(emitter.VIEW_ORDER), result["view_order"])

    def test_cli_failure_is_json_and_uppercase_sha_is_accepted(self) -> None:
        success = self.fixture.output("uppercase-sha")
        with mock.patch.object(emitter, "_assert_git_tracked"):
            emitter.emit_phase5_vision_views(
                self.fixture.source_relative,
                success,
                source_sha256=self.fixture.source_sha256.upper(),
                focus_box=(2, 1, 8, 7),
            )
        self.assertTrue(success.is_dir())

        stdout = io.StringIO()
        with (
            mock.patch.object(emitter, "_assert_git_tracked"),
            contextlib.redirect_stdout(stdout),
        ):
            returncode = emitter.main(
                [
                    self.fixture.source_relative,
                    str(self.fixture.output("cli-failure")),
                    "--source-sha256",
                    "0" * 64,
                    "--focus-box",
                    "2,1,8,7",
                ]
            )
        result = json.loads(stdout.getvalue())
        self.assertEqual(1, returncode)
        self.assertFalse(result["valid"])
        self.assertIn("SHA-256 mismatch", result["error"])


if __name__ == "__main__":
    unittest.main()
