import copy
import hashlib
import json
import shutil
import sys
import tempfile
import threading
import unittest
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts" / "map-production"
sys.path.insert(0, str(SCRIPT_DIR))

import render_phase5_parent_control_masks as parent_controls  # noqa: E402
import render_phase5_reviewed_master as reviewed_renderer  # noqa: E402
import audit_phase5_master as parent_audit  # noqa: E402
import build_phase5_assets as phase5  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path: Path) -> dict[str, str]:
    return {
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": digest(path),
    }


def copy_canonical_inputs(root: Path) -> tuple[Path, Path, Path]:
    source = root / "source"
    source.mkdir(parents=True)
    for filename in parent_controls.SOURCE_FILES.values():
        shutil.copy2(parent_controls.DEFAULT_SOURCE_DIR / filename, source / filename)
    catalog = source / "map-sheets.json"
    shutil.copy2(parent_controls.DEFAULT_MAP_SHEETS, catalog)
    contract = root / "resolution-contract.json"
    shutil.copy2(parent_controls.DEFAULT_CONTRACT, contract)
    return source, contract, catalog


class Phase5ParentControlMaskRendererTests(unittest.TestCase):
    def test_exact_six_parent_bundle_is_binary_and_hash_locked(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temporary:
            root = Path(temporary)
            output = root / "parent-controls"
            index, report = parent_controls.generate_parent_controls(output)

            self.assertEqual(
                tuple(sheet["sheet_id"] for sheet in index["sheets"]),
                parent_controls.EXPECTED_PARENT_IDS,
            )
            self.assertEqual(index["summary"]["sheet_count"], 6)
            self.assertEqual(index["summary"]["world_sheet_count"], 1)
            self.assertEqual(index["summary"]["continent_sheet_count"], 5)
            self.assertEqual(index["summary"]["control_mask_count"], 12)
            self.assertEqual(index["summary"]["input_artifact_count"], 14)
            self.assertFalse(
                index["render_contract"]["direct17_control_index_required"]
            )
            self.assertFalse(
                index["render_contract"]["observed_renderer_builders_consumed"]
            )
            self.assertFalse(index["render_contract"]["parent_observed_masks_consumed"])
            self.assertFalse(index["render_contract"]["composited_masters_consumed"])

            expected_layout = {
                item["sheet_id"]: (item["width"], item["height"])
                for item in parent_controls.EXPECTED_PARENT_LAYOUT
            }
            records = []
            for sheet in index["sheets"]:
                size = expected_layout[sheet["sheet_id"]]
                self.assertEqual((sheet["width"], sheet["height"]), size)
                self.assertEqual(
                    sheet["metrics"]["total_pixel_count"], size[0] * size[1]
                )
                self.assertEqual(
                    sheet["metrics"]["land_pixel_count"]
                    + sheet["metrics"]["water_pixel_count"],
                    size[0] * size[1],
                )
                for record in sheet["qa_controls"].values():
                    records.append(record)
                    path = REPO_ROOT / record["path"]
                    self.assertEqual(record["sha256"], digest(path))
                    with Image.open(path) as opened:
                        opened.load()
                        self.assertEqual(opened.size, size)
                        self.assertEqual(opened.format, "PNG")
                        self.assertEqual(opened.mode, "L")
                        values = {
                            value
                            for value, count in enumerate(opened.histogram())
                            if count
                        }
                    self.assertLessEqual(values, {0, 255})
                    self.assertEqual(record["binary_values"], sorted(values))
            self.assertEqual(len(records), 12)

            index_path = output / "index.json"
            report_path = output / "report.json"
            self.assertNotIn(b"\r\n", index_path.read_bytes())
            self.assertNotIn(b"\r\n", report_path.read_bytes())
            self.assertEqual(report["index"]["sha256"], digest(index_path))
            self.assertEqual(
                report["index"]["path"], index_path.relative_to(REPO_ROOT).as_posix()
            )
            self.assertEqual(len(report["outputs"]), 12)
            self.assertEqual(
                json.loads(report_path.read_text(encoding="utf-8")), report
            )
            for artifact in report["outputs"]:
                self.assertEqual(
                    artifact["sha256"], digest(REPO_ROOT / artifact["path"])
                )
            self.assertEqual(
                {
                    (sheet["sheet_id"], role): (
                        parent_controls.raster_semantic_sha256_file(
                            REPO_ROOT / record["path"]
                        )
                    )
                    for sheet in index["sheets"]
                    for role, record in sheet["qa_controls"].items()
                },
                parent_controls.EXPECTED_CONTROL_RASTER_SHA256,
            )

            executable_roles = tuple(
                item["role"] for item in index["inputs"]["executable_inputs"]
            )
            self.assertEqual(
                executable_roles, parent_controls.EXPECTED_EXECUTABLE_ROLES
            )
            executable_by_role = {
                item["role"]: item for item in index["inputs"]["executable_inputs"]
            }
            for role, expected_path in (
                ("generator", parent_controls.GENERATOR_PATH),
                ("production-common", parent_controls.PRODUCTION_COMMON_PATH),
                (
                    "canonical-source-contract",
                    parent_controls.RENDER_WORLD_MASTER_PATH,
                ),
                (
                    "resolution-contract-validator",
                    parent_controls.RESOLUTION_VALIDATOR_PATH,
                ),
            ):
                self.assertEqual(
                    executable_by_role[role]["sha256"], digest(expected_path)
                )

            duplicate_role = copy.deepcopy(index)
            duplicate_role["inputs"]["executable_inputs"][3]["role"] = "generator"
            with self.assertRaisesRegex(parent_controls.ParentControlError, "role set"):
                parent_controls._validate_input_role_sets(duplicate_role["inputs"])
            with self.assertRaisesRegex(parent_controls.ParentControlError, "invalid"):
                parent_controls._validate_schema(
                    duplicate_role,
                    parent_controls.DEFAULT_INDEX_SCHEMA,
                    "mutated parent control index",
                )

            missing_sheet = copy.deepcopy(index)
            missing_sheet["sheets"][5]["sheet_id"] = "sheet_world"
            with self.assertRaisesRegex(parent_controls.ParentControlError, "invalid"):
                parent_controls._validate_schema(
                    missing_sheet,
                    parent_controls.DEFAULT_INDEX_SCHEMA,
                    "mutated parent control index",
                )

            # A semantically identical but byte-different index is still stale:
            # the report locks the exact checked artifact, not merely its fields.
            index_path.write_text(
                json.dumps(index, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                parent_controls.ParentControlError, "does not hash-lock"
            ):
                parent_controls._load_bundle_documents(output)

    def test_runtime_compatibility_excludes_python_patch_and_zlib_identity(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temporary:
            snapshot_root = Path(temporary) / "parent-controls"
            shutil.copytree(parent_controls.DEFAULT_OUTPUT_ROOT, snapshot_root)
            with (
                mock.patch.object(
                    parent_controls.platform,
                    "python_version",
                    return_value="3.12.999-host-build",
                ),
                mock.patch.object(zlib, "ZLIB_VERSION", "host-zlib-compile"),
                mock.patch.object(zlib, "ZLIB_RUNTIME_VERSION", "host-zlib-runtime"),
            ):
                index, report = (
                    parent_controls.load_validated_parent_control_bundle_snapshot(
                        snapshot_root
                    )
                )

            compatibility = index["inputs"]["runtime_compatibility"]
            self.assertEqual(
                compatibility, parent_controls.EXPECTED_RUNTIME_COMPATIBILITY
            )
            self.assertEqual(report["inputs"]["runtime_compatibility"], compatibility)
            self.assertNotIn("python_version", compatibility)
            self.assertNotIn("zlib_compile_version", compatibility)
            self.assertNotIn("zlib_runtime_version", compatibility)

            real_version = parent_controls.importlib.metadata.version

            def incompatible_version(distribution):
                if distribution == "Pillow":
                    return "12.3.1"
                return real_version(distribution)

            with mock.patch.object(
                parent_controls.importlib.metadata,
                "version",
                side_effect=incompatible_version,
            ):
                with self.assertRaisesRegex(
                    parent_controls.ParentControlError,
                    "runtime compatibility mismatch",
                ):
                    parent_controls.load_parent_inputs()

    def test_raster_semantic_hash_ignores_png_encoding_but_detects_one_pixel(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temporary:
            root = Path(temporary)
            first_path = root / "first.png"
            second_path = root / "second.png"
            changed_path = root / "changed.png"
            raster = Image.new("L", (16, 16))
            raster.putdata(bytes((index * 37) % 256 for index in range(256)))
            try:
                raster.save(
                    first_path, format="PNG", compress_level=0, optimize=False
                )
                raster.save(
                    second_path, format="PNG", compress_level=9, optimize=False
                )
                changed = raster.copy()
                changed.putpixel((9, 3), (changed.getpixel((9, 3)) + 1) % 256)
                try:
                    changed.save(
                        changed_path,
                        format="PNG",
                        compress_level=9,
                        optimize=False,
                    )
                finally:
                    changed.close()
            finally:
                raster.close()

            self.assertNotEqual(digest(first_path), digest(second_path))
            self.assertEqual(
                parent_controls.raster_semantic_sha256_file(first_path),
                parent_controls.raster_semantic_sha256_file(second_path),
            )
            self.assertNotEqual(
                parent_controls.raster_semantic_sha256_file(first_path),
                parent_controls.raster_semantic_sha256_file(changed_path),
            )

    def test_semantic_fields_are_recomputed_instead_of_schema_trusted(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temporary:
            output = Path(temporary) / "parent-controls"
            index, report = parent_controls.generate_parent_controls(output)
            original_index = copy.deepcopy(index)
            original_report = copy.deepcopy(report)

            cases = []

            def stale_metrics(changed_index, changed_report):
                changed_index["sheets"][0]["metrics"]["land_pixel_count"] += 1

            cases.append(("metrics", stale_metrics, "index semantic fields"))

            def stale_dimensions(changed_index, changed_report):
                changed_index["sheets"][0]["qa_controls"]["land_sea_control"][
                    "width"
                ] += 1

            cases.append(("dimensions", stale_dimensions, "index semantic fields"))

            def stale_runtime(changed_index, changed_report):
                changed_index["inputs"]["runtime_compatibility"]["python_series"] = (
                    "fabricated"
                )
                changed_report["inputs"] = copy.deepcopy(changed_index["inputs"])

            cases.append(("runtime", stale_runtime, "invalid"))

            def stale_report_claim(changed_index, changed_report):
                changed_report["checks"]["native_dimensions"]["sheets"][0]["width"] += 1

            cases.append(("report", stale_report_claim, "report semantic fields"))

            for name, mutate, diagnostic in cases:
                with self.subTest(name=name):
                    changed_index = copy.deepcopy(original_index)
                    changed_report = copy.deepcopy(original_report)
                    mutate(changed_index, changed_report)
                    (output / "index.json").write_text(
                        json.dumps(changed_index, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    changed_report["index"] = artifact(output / "index.json")
                    (output / "report.json").write_text(
                        json.dumps(changed_report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        parent_controls.ParentControlError, diagnostic
                    ):
                        parent_controls._load_bundle_documents(output)

            changed_index = copy.deepcopy(original_index)
            changed_report = copy.deepcopy(original_report)
            changed_record = changed_index["sheets"][0]["qa_controls"][
                "land_sea_control"
            ]
            changed_path = REPO_ROOT / changed_record["path"]
            with Image.open(changed_path) as opened:
                changed_mask = opened.copy()
            original_pixel = changed_mask.getpixel((0, 0))
            changed_mask.putpixel((0, 0), 0 if original_pixel else 255)
            changed_mask.save(changed_path, format="PNG", compress_level=9)
            changed_mask.close()
            changed_record["sha256"] = digest(changed_path)
            changed_record["on_pixel_count"] += -1 if original_pixel else 1
            for output_record in changed_report["outputs"]:
                if (
                    output_record["sheet_id"] == "sheet_world"
                    and output_record["role"] == "land_sea_control"
                ):
                    output_record["sha256"] = changed_record["sha256"]
            (output / "index.json").write_text(
                json.dumps(changed_index, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            changed_report["index"] = artifact(output / "index.json")
            (output / "report.json").write_text(
                json.dumps(changed_report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                parent_controls.ParentControlError, "reviewed canonical set"
            ):
                parent_controls._load_bundle_documents(output)
            with self.assertRaisesRegex(
                parent_controls.ParentControlError, "canonical repository path"
            ):
                parent_controls.load_validated_parent_control_bundle(
                    output / "index.json"
                )

    def test_snapshot_audit_never_reopens_logical_parent_control_files(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temporary:
            snapshot_root = Path(temporary) / "bound-parent-control-snapshot"
            shutil.copytree(parent_controls.DEFAULT_OUTPUT_ROOT, snapshot_root)
            canonical_root = parent_controls.DEFAULT_OUTPUT_ROOT.resolve()
            real_path_open = Path.open

            def reject_logical_control_reopen(path_self, *args, **kwargs):
                lexical = Path(parent_controls.os.path.abspath(path_self))
                try:
                    lexical.relative_to(canonical_root)
                except ValueError:
                    return real_path_open(path_self, *args, **kwargs)
                raise AssertionError(
                    f"semantic audit reopened logical control path: {path_self}"
                )

            with mock.patch.object(Path, "open", reject_logical_control_reopen):
                index, report = (
                    parent_controls.load_validated_parent_control_bundle_snapshot(
                        snapshot_root
                    )
                )
            self.assertEqual(index["summary"]["control_mask_count"], 12)
            self.assertEqual(
                report["index"]["path"],
                (parent_controls.DEFAULT_OUTPUT_ROOT / "index.json")
                .relative_to(REPO_ROOT)
                .as_posix(),
            )

            with self.assertRaisesRegex(
                parent_controls.ParentControlError, "canonical logical root"
            ):
                parent_controls.load_validated_parent_control_bundle_snapshot(
                    snapshot_root,
                    logical_root=Path(temporary) / "forged-logical-root",
                )

    def test_bound_snapshot_preserves_tree_and_has_zero_logical_reopens(self):
        canonical_root = parent_controls.DEFAULT_OUTPUT_ROOT.resolve()
        canonical_files = sorted(
            path for path in canonical_root.rglob("*") if path.is_file()
        )
        bindings = {}
        for path in canonical_files:
            bound = phase5.bind_file(
                path,
                label=(f"parent control {path.relative_to(canonical_root).as_posix()}"),
                trackable=True,
            )
            bindings[bound.identity] = bound

        real_path_open = Path.open
        logical_reopens = []

        def reject_logical_control_reopen(path_self, *args, **kwargs):
            lexical = Path(parent_controls.os.path.abspath(path_self))
            try:
                relative = lexical.relative_to(canonical_root)
            except ValueError:
                return real_path_open(path_self, *args, **kwargs)
            logical_reopens.append(relative.as_posix())
            raise AssertionError(
                f"bound audit reopened logical control path: {path_self}"
            )

        with (
            phase5.bound_artifact_context(bindings),
            mock.patch.object(Path, "open", reject_logical_control_reopen),
            phase5._bound_directory_snapshot(
                canonical_root, "parent control regression snapshot"
            ) as snapshot_root,
        ):
            snapshot_files = sorted(
                path.relative_to(snapshot_root).as_posix()
                for path in snapshot_root.rglob("*")
                if path.is_file()
            )
            index, _ = parent_controls.load_validated_parent_control_bundle_snapshot(
                snapshot_root,
                logical_root=canonical_root,
            )

        self.assertEqual(len(canonical_files), 14)
        self.assertEqual(
            snapshot_files,
            [path.relative_to(canonical_root).as_posix() for path in canonical_files],
        )
        self.assertEqual(index["summary"]["control_mask_count"], 12)
        self.assertEqual(logical_reopens, [])

    def test_regeneration_is_byte_deterministic_and_uses_no_observed_or_direct17_input(
        self,
    ):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temporary:
            root = Path(temporary)
            output = root / "parent-controls"
            real_path_open = Path.open

            def guarded_path_open(path_self, *args, **kwargs):
                normalized = path_self.resolve().as_posix().lower()
                forbidden = ("phase5-metatiles", "observed-masks", "/masters/")
                if any(token in normalized for token in forbidden):
                    raise AssertionError(
                        f"forbidden parent-control dependency: {path_self}"
                    )
                return real_path_open(path_self, *args, **kwargs)

            forbidden_call = AssertionError(
                "parent controls must not call a master/observed-mask renderer"
            )
            with (
                mock.patch.object(Path, "open", guarded_path_open),
                mock.patch.object(
                    reviewed_renderer,
                    "_build_land_masks",
                    side_effect=forbidden_call,
                ),
                mock.patch.object(
                    reviewed_renderer,
                    "_build_transport_mask",
                    side_effect=forbidden_call,
                ),
            ):
                first_index, first_report = parent_controls.generate_parent_controls(
                    output
                )
                verified_index, verified_report = parent_controls.verify_existing(
                    output
                )

            self.assertEqual(first_index, verified_index)
            self.assertEqual(first_report, verified_report)
            serialized_inputs = json.dumps(first_index["inputs"], sort_keys=True)
            self.assertNotIn("phase5-metatiles", serialized_inputs)
            self.assertNotIn("observed", serialized_inputs)
            self.assertNotIn("/masters/", serialized_inputs.replace("\\", "/"))
            independence = first_report["checks"]["independent_control_path"]
            self.assertTrue(independence["passed"])
            self.assertFalse(independence["direct17_control_index_consumed"])
            self.assertFalse(independence["observed_renderer_builders_consumed"])
            self.assertFalse(independence["parent_observed_masks_consumed"])
            self.assertFalse(independence["composited_masters_consumed"])

    def test_unexpected_ids_dimensions_crs_escape_and_overwrite_fail_closed(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temporary:
            root = Path(temporary)

            source, contract, catalog = copy_canonical_inputs(root / "bad-id")
            document = json.loads(catalog.read_text(encoding="utf-8"))
            document["sheets"][1]["id"] = "sheet_continent_intruder"
            with self.assertRaisesRegex(
                parent_controls.ParentControlError, "parent sheet IDs"
            ):
                parent_controls._catalog_by_id(document)
            with self.assertRaisesRegex(
                parent_controls.ParentControlError, "canonical source directory"
            ):
                parent_controls.load_parent_inputs(source_dir=source)

            source, contract, catalog = copy_canonical_inputs(root / "bad-dimensions")
            document = json.loads(contract.read_text(encoding="utf-8"))
            document["world_raster"]["width_px"] = 4097
            with self.assertRaisesRegex(
                parent_controls.ParentControlError, "world raster dimensions"
            ):
                parent_controls._validate_contract_anchor(document)

            source, contract, catalog = copy_canonical_inputs(root / "bad-crs")
            document = json.loads(catalog.read_text(encoding="utf-8"))
            document["coordinate_reference_system"] = "EPSG:4326"
            with self.assertRaisesRegex(parent_controls.ParentControlError, "CRS"):
                parent_controls._catalog_by_id(document)

            source, contract, catalog = copy_canonical_inputs(root / "bad-source-crs")
            landmasses = source / "landmasses.geojson"
            document = json.loads(landmasses.read_text(encoding="utf-8"))
            document["coordinate_reference_system"] = "EPSG:4326"
            landmasses.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(
                parent_controls.ParentControlError, "EA-WORLD-1"
            ):
                parent_controls.load_canonical_sources(source)

            outside = REPO_ROOT.parent / "phase5-parent-controls-outside-repo"
            with self.assertRaisesRegex(
                parent_controls.ParentControlError, "inside the repository"
            ):
                parent_controls.generate_parent_controls(outside)

            occupied = root / "occupied"
            occupied.mkdir()
            sentinel = occupied / "user-owned.txt"
            sentinel.write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(
                parent_controls.ParentControlError, "overwrite"
            ):
                parent_controls.generate_parent_controls(occupied)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")
            self.assertEqual(list(occupied.iterdir()), [sentinel])

    def test_exact_output_root_reservation_has_one_cross_platform_winner(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temporary:
            output = Path(temporary) / "raced-output"
            barrier = threading.Barrier(2)

            def contender():
                barrier.wait(timeout=5)
                try:
                    return parent_controls._reserve_output_root(output)
                except parent_controls.ParentControlError as exc:
                    return exc

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: contender(), range(2)))

            winners = [
                value
                for value in results
                if isinstance(value, parent_controls.OutputReservation)
            ]
            losers = [
                value
                for value in results
                if isinstance(value, parent_controls.ParentControlError)
            ]
            self.assertEqual(len(winners), 1)
            self.assertEqual(len(losers), 1)
            self.assertIn("rather than overwriting", str(losers[0]))
            self.assertEqual(winners[0].root, output)
            self.assertEqual(winners[0].marker.parent, output)
            self.assertTrue(winners[0].marker.is_file())
            self.assertEqual(list(output.iterdir()), [winners[0].marker])

    @unittest.skipIf(parent_controls.os.name == "nt", "POSIX commit regression")
    def test_posix_commit_rejects_final_root_move_and_restores_marker(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temporary:
            root = Path(temporary)
            output = root / "posix-commit-output"
            displaced = root / "posix-commit-displaced"
            reservation = parent_controls._reserve_output_root(output)
            stage = root / "posix-commit-stage"
            stage.mkdir()
            (stage / "sheet_world").mkdir()
            (stage / "index.json").write_text("{}\n", encoding="utf-8")
            (stage / "report.json").write_text("{}\n", encoding="utf-8")
            real_unlink = parent_controls.os.unlink
            swap_count = 0

            def move_destination_before_marker_unlink(
                path, *args, dir_fd=None, **kwargs
            ):
                nonlocal swap_count
                if path == reservation.marker.name and dir_fd is not None:
                    swap_count += 1
                    reservation.root.rename(displaced)
                    reservation.root.mkdir()
                    (reservation.root / "foreign-owner.txt").write_text(
                        "preserve\n", encoding="utf-8"
                    )
                return real_unlink(path, *args, dir_fd=dir_fd, **kwargs)

            with (
                mock.patch.object(
                    parent_controls.os,
                    "unlink",
                    side_effect=move_destination_before_marker_unlink,
                ),
                mock.patch.object(
                    parent_controls,
                    "_load_bundle_documents",
                    return_value=({}, {}),
                ),
            ):
                with self.assertRaisesRegex(
                    parent_controls.ParentControlError,
                    "changed during POSIX commit.*restored",
                ):
                    parent_controls._install_reserved_output(stage, reservation)

            self.assertEqual(swap_count, 1)
            self.assertEqual(
                (displaced / reservation.marker.name).read_text(encoding="ascii"),
                f"{parent_controls.GENERATOR_ID}\n{reservation.token}\n",
            )
            self.assertEqual(
                (output / "foreign-owner.txt").read_text(encoding="utf-8"),
                "preserve\n",
            )
            self.assertFalse((output / "index.json").exists())

    def test_reservation_swaps_reparse_and_failed_install_remain_inert(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temporary:
            root = Path(temporary)

            interrupted_output = root / "interrupted-acquisition"
            with mock.patch.object(
                parent_controls.os,
                "write",
                side_effect=KeyboardInterrupt("injected acquisition interrupt"),
            ):
                with self.assertRaisesRegex(
                    KeyboardInterrupt, "injected acquisition interrupt"
                ):
                    parent_controls._reserve_output_root(interrupted_output)
            self.assertFalse(interrupted_output.exists())

            foreign_marker_output = root / "foreign-marker-acquisition"
            real_open = parent_controls.os.open

            def install_foreign_marker(path, flags, mode=0o777):
                foreign_flags = (
                    parent_controls.os.O_CREAT
                    | parent_controls.os.O_EXCL
                    | parent_controls.os.O_WRONLY
                    | getattr(parent_controls.os, "O_BINARY", 0)
                )
                descriptor = real_open(path, foreign_flags, 0o600)
                try:
                    parent_controls.os.write(descriptor, b"foreign-owner\n")
                finally:
                    parent_controls.os.close(descriptor)
                raise FileExistsError("injected marker race")

            with mock.patch.object(
                parent_controls.os,
                "open",
                side_effect=install_foreign_marker,
            ):
                with self.assertRaisesRegex(FileExistsError, "injected marker race"):
                    parent_controls._reserve_output_root(foreign_marker_output)
            foreign_marker = (
                foreign_marker_output / ".phase5-parent-control-reservation"
            )
            self.assertEqual(
                foreign_marker.read_text(encoding="ascii"), "foreign-owner\n"
            )

            marker_output = root / "marker-swap"
            marker_reservation = parent_controls._reserve_output_root(marker_output)
            displaced_marker = marker_output / "displaced-marker"
            marker_reservation.marker.rename(displaced_marker)
            marker_reservation.marker.write_text(
                f"{parent_controls.GENERATOR_ID}\n{marker_reservation.token}\n",
                encoding="ascii",
            )
            marker_stage = root / "marker-stage"
            marker_stage.mkdir()
            (marker_stage / "index.json").write_text("{}\n", encoding="utf-8")
            (marker_stage / "report.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(
                parent_controls.ParentControlError, "marker identity"
            ):
                parent_controls._install_reserved_output(
                    marker_stage, marker_reservation
                )
            self.assertFalse((marker_output / "index.json").exists())

            root_output = root / "root-swap"
            root_reservation = parent_controls._reserve_output_root(root_output)
            displaced_root = root / "displaced-root"
            root_output.rename(displaced_root)
            root_output.mkdir()
            (root_output / root_reservation.marker.name).write_text(
                f"{parent_controls.GENERATOR_ID}\n{root_reservation.token}\n",
                encoding="ascii",
            )
            root_stage = root / "root-stage"
            root_stage.mkdir()
            (root_stage / "index.json").write_text("{}\n", encoding="utf-8")
            (root_stage / "report.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(
                parent_controls.ParentControlError, "root identity"
            ):
                parent_controls._install_reserved_output(root_stage, root_reservation)
            self.assertFalse((root_output / "index.json").exists())

            failed_output = root / "failed-install"
            failed_reservation = parent_controls._reserve_output_root(failed_output)
            failed_stage = root / "failed-stage"
            failed_stage.mkdir()
            (failed_stage / "sheet_world").mkdir()
            (failed_stage / "index.json").write_text("{}\n", encoding="utf-8")
            (failed_stage / "report.json").write_text("{}\n", encoding="utf-8")
            real_rename = parent_controls.os.rename
            rename_count = 0

            def fail_after_first_install(source, destination, *args, **kwargs):
                nonlocal rename_count
                rename_count += 1
                if rename_count == 2:
                    raise OSError("injected install failure")
                return real_rename(source, destination, *args, **kwargs)

            with mock.patch.object(
                parent_controls.os, "rename", side_effect=fail_after_first_install
            ):
                with self.assertRaisesRegex(OSError, "injected install failure"):
                    parent_controls._install_reserved_output(
                        failed_stage, failed_reservation
                    )
            self.assertTrue(failed_reservation.marker.is_file())
            self.assertFalse((failed_output / "report.json").exists())
            with self.assertRaisesRegex(
                parent_controls.ParentControlError, "non-canonical file tree"
            ):
                parent_controls._load_bundle_documents(failed_output)

            with mock.patch.object(
                parent_controls, "_stat_is_reparse", return_value=True
            ):
                with self.assertRaisesRegex(
                    parent_controls.ParentControlError, "reparse point"
                ):
                    parent_controls._validated_output_root(root / "reparse-output")

            if parent_controls.os.name == "nt":
                locked_output = root / "locked-install"
                locked_reservation = parent_controls._reserve_output_root(locked_output)
                locked_stage = root / "locked-stage"
                locked_stage.mkdir()
                (locked_stage / "sheet_world").mkdir()
                (locked_stage / "index.json").write_text("{}\n", encoding="utf-8")
                (locked_stage / "report.json").write_text("{}\n", encoding="utf-8")
                real_move = parent_controls._move_into_reservation
                swap_attempted = False

                def attempt_toc_tou_swap(source, name, reservation, guard):
                    nonlocal swap_attempted
                    if not swap_attempted:
                        swap_attempted = True
                        with self.assertRaises(OSError):
                            reservation.root.rename(root / "locked-root-displaced")
                    return real_move(source, name, reservation, guard)

                with (
                    mock.patch.object(
                        parent_controls,
                        "_move_into_reservation",
                        side_effect=attempt_toc_tou_swap,
                    ),
                    mock.patch.object(
                        parent_controls,
                        "_load_bundle_documents",
                        return_value=({}, {}),
                    ),
                ):
                    parent_controls._install_reserved_output(
                        locked_stage, locked_reservation
                    )
                self.assertTrue(swap_attempted)
                self.assertFalse(locked_reservation.marker.exists())
                self.assertTrue((locked_output / "report.json").is_file())

    def test_real_parent_bundle_binds_auditor_and_rejects_self_control(self):
        sheet_id = "sheet_continent_grimoire"
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temporary:
            root = Path(temporary)
            output = root / "parent-controls"
            index, _ = parent_controls.generate_parent_controls(output)
            self.enterContext(
                mock.patch.object(parent_controls, "DEFAULT_OUTPUT_ROOT", output)
            )
            record = next(
                item for item in index["sheets"] if item["sheet_id"] == sheet_id
            )
            _, catalog_by_id, derived = phase5.load_contract(
                phase5.DEFAULT_CONTRACT, phase5.DEFAULT_MAP_SHEETS
            )
            raw_contract = json.loads(
                phase5.DEFAULT_CONTRACT.read_text(encoding="utf-8")
            )
            render_sheet = {
                **derived["sheets"][sheet_id],
                "source_feature_id": catalog_by_id[sheet_id].get("source_feature_id"),
            }
            sources = reviewed_renderer.load_sources(parent_controls.DEFAULT_SOURCE_DIR)
            observed = reviewed_renderer.render_observed_masks(
                sources, raw_contract, render_sheet
            )
            observed_land = root / "observed-land.png"
            observed_route = root / "observed-route.png"
            try:
                observed["land_sea"].save(
                    observed_land, format="PNG", compress_level=9, optimize=False
                )
                observed["transport"].save(
                    observed_route, format="PNG", compress_level=9, optimize=False
                )
            finally:
                for image in observed.values():
                    image.close()

            land_control_path = (
                REPO_ROOT / record["qa_controls"]["land_sea_control"]["path"]
            )
            route_control_path = (
                REPO_ROOT / record["qa_controls"]["transport_control"]["path"]
            )
            binding = parent_audit._verify_parent_mask_bindings(
                sheet_id=sheet_id,
                control_index_path=output / "index.json",
                contract_path=phase5.DEFAULT_CONTRACT,
                catalog_path=phase5.DEFAULT_MAP_SHEETS,
                catalog_by_id=catalog_by_id,
                contracts_by_id=derived["sheets"],
                land_control_spec=artifact(land_control_path),
                land_observed_spec=artifact(observed_land),
                route_control_spec=artifact(route_control_path),
                route_observed_spec=artifact(observed_route),
            )
            self.assertEqual(binding["index"], artifact(output / "index.json"))
            self.assertEqual(binding["report"], artifact(output / "report.json"))

            master = root / "composite-master.png"
            Image.new(
                "RGB",
                (record["width"], record["height"]),
                (196, 180, 132),
            ).save(master, format="PNG", compress_level=6, optimize=False)
            child_source_index = root / "child-source-index.json"
            child_source_index.write_text("{}\n", encoding="utf-8")
            structured_provenance = {
                "kind": "deterministic-parent-composite",
                "canonical_native_base": {
                    "renderer": artifact(phase5.CANONICAL_RENDERER_PATH),
                    "resolution_contract": artifact(phase5.DEFAULT_CONTRACT),
                    "material_atlas": artifact(phase5.DEFAULT_PHASE5_MATERIAL_ATLAS),
                    "canon_sources": [
                        {"role": role, **artifact(path)}
                        for role, path in phase5.CANONICAL_GEOJSON_SOURCES.items()
                    ],
                    "source_coordinates_modified": False,
                    "world_crop_or_upscale_used": False,
                },
                "observed_masks": {
                    "land_sea": artifact(observed_land),
                    "transport": artifact(observed_route),
                },
            }
            provenance = root / "composite-provenance.json"
            provenance.write_text(
                json.dumps({"inputs": {"source_index": artifact(child_source_index)}}),
                encoding="utf-8",
            )
            with (
                mock.patch.object(
                    parent_audit, "load_source_index", return_value=({}, None, None)
                ),
                mock.patch.object(parent_audit, "verify_master_provenance"),
                mock.patch.object(
                    parent_audit,
                    "provenance_artifact_record",
                    return_value={"provenance": structured_provenance},
                ),
                mock.patch.object(
                    phase5,
                    "provenance_artifact_record",
                    return_value={"provenance": structured_provenance},
                ),
            ):
                audit_report = parent_audit.audit_phase5_master(
                    sheet_id=sheet_id,
                    source_kind="composite_master",
                    master_path=master,
                    provenance_path=provenance,
                    land_sea_control_path=land_control_path,
                    land_sea_observed_path=observed_land,
                    transport_control_path=route_control_path,
                    transport_observed_path=observed_route,
                    transport_tolerance_px=8,
                    child_source_index_path=child_source_index,
                    parent_control_index_path=output / "index.json",
                )
                tampered_lock = copy.deepcopy(audit_report)
                tampered_lock["parent_controls"]["report"]["sha256"] = "0" * 64
                with self.assertRaisesRegex(
                    phase5.Phase5BuildError, "parent_controls.report.*sha256 mismatch"
                ):
                    phase5.validate_automated_qa_report(
                        tampered_lock,
                        entry={
                            "kind": "composite_master",
                            **artifact(master),
                            "provenance_report": artifact(provenance),
                        },
                        sheet=catalog_by_id[sheet_id],
                        master_path=artifact(master)["path"],
                        job_id=phase5.job_id_for_sheet(sheet_id),
                        contract=derived["sheets"][sheet_id],
                    )
            self.assertEqual(audit_report["status"], "passed")
            self.assertEqual(audit_report["source_kind"], "composite_master")
            self.assertEqual(
                audit_report["geography"]["land_sea"]["control"],
                artifact(land_control_path),
            )

            _, land_control = phase5.load_binary_mask(
                artifact(land_control_path),
                label="integration land control",
                expected_size=(record["width"], record["height"]),
            )
            _, land_observed = phase5.load_binary_mask(
                artifact(observed_land),
                label="integration observed land",
                expected_size=(record["width"], record["height"]),
            )
            _, route_control = phase5.load_binary_mask(
                artifact(route_control_path),
                label="integration route control",
                expected_size=(record["width"], record["height"]),
            )
            _, route_observed = phase5.load_binary_mask(
                artifact(observed_route),
                label="integration observed route",
                expected_size=(record["width"], record["height"]),
            )
            try:
                land_ratio = phase5.land_sea_match_ratio(land_control, land_observed)
                self.assertGreaterEqual(land_ratio, phase5.MINIMUM_LAND_SEA_MATCH_RATIO)
                self.assertLess(land_ratio, 1.0)
                route_ratios = phase5.transport_within_tolerance_ratios(
                    route_control, route_observed, 8
                )
                self.assertGreaterEqual(
                    min(route_ratios),
                    phase5.MINIMUM_TRANSPORT_WITHIN_TOLERANCE_RATIO,
                )
                self.assertNotEqual(route_control.tobytes(), route_observed.tobytes())
            finally:
                land_control.close()
                land_observed.close()
                route_control.close()
                route_observed.close()

            byte_copy = root / "observed-byte-copy.png"
            shutil.copyfile(land_control_path, byte_copy)
            with self.assertRaisesRegex(phase5.Phase5BuildError, "byte-identical"):
                parent_audit._verify_parent_mask_bindings(
                    sheet_id=sheet_id,
                    control_index_path=output / "index.json",
                    contract_path=phase5.DEFAULT_CONTRACT,
                    catalog_path=phase5.DEFAULT_MAP_SHEETS,
                    catalog_by_id=catalog_by_id,
                    contracts_by_id=derived["sheets"],
                    land_control_spec=artifact(land_control_path),
                    land_observed_spec=artifact(byte_copy),
                    route_control_spec=artifact(route_control_path),
                    route_observed_spec=artifact(observed_route),
                )

            reencoded_copy = root / "observed-reencoded-copy.png"
            with Image.open(land_control_path) as control_image:
                control_image.save(
                    reencoded_copy,
                    format="PNG",
                    compress_level=1,
                    optimize=False,
                )
            self.assertNotEqual(digest(land_control_path), digest(reencoded_copy))
            with self.assertRaisesRegex(phase5.Phase5BuildError, "decodes identically"):
                parent_audit._verify_parent_mask_bindings(
                    sheet_id=sheet_id,
                    control_index_path=output / "index.json",
                    contract_path=phase5.DEFAULT_CONTRACT,
                    catalog_path=phase5.DEFAULT_MAP_SHEETS,
                    catalog_by_id=catalog_by_id,
                    contracts_by_id=derived["sheets"],
                    land_control_spec=artifact(land_control_path),
                    land_observed_spec=artifact(reencoded_copy),
                    route_control_spec=artifact(route_control_path),
                    route_observed_spec=artifact(observed_route),
                )

    def test_composite_audit_requires_explicit_parent_control_index(self):
        sheet_id = "sheet_world"
        sheet = {"id": sheet_id, "sheet_type": "world"}
        contract = {"width": 1, "height": 1}
        derived = {"sheets": {sheet_id: contract}}
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temporary:
            root = Path(temporary)
            with mock.patch.object(
                parent_audit,
                "load_contract",
                return_value=({}, {sheet_id: sheet}, derived),
            ):
                with self.assertRaisesRegex(
                    phase5.Phase5BuildError, "--parent-control-index"
                ):
                    parent_audit.audit_phase5_master(
                        sheet_id=sheet_id,
                        source_kind="composite_master",
                        master_path=root / "missing-master.png",
                        provenance_path=root / "missing-provenance.json",
                        land_sea_control_path=root / "missing-land-control.png",
                        land_sea_observed_path=root / "missing-land-observed.png",
                        transport_control_path=root / "missing-route-control.png",
                        transport_observed_path=root / "missing-route-observed.png",
                        transport_tolerance_px=0,
                        child_source_index_path=root / "child-source-index.json",
                    )


if __name__ == "__main__":
    unittest.main()
