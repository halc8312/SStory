#!/usr/bin/env python3
"""Canonical focus and exact-five evidence validation for Phase 5 Vision QA."""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, PngImagePlugin, UnidentifiedImageError

from production_common import REPO_ROOT
from release_bound_artifact import BoundArtifact, BoundArtifactError, bind_file
from release_path_safety import ReleasePathError, require_trackable_path, same_path
from validate_manifest import schema_errors
import validate_resolution_contract as resolution_contract


FOCUS_REGISTRY_SCHEMA_VERSION = "1.0.0"
CANONICAL_RECEIPT_SCHEMA_VERSION = "1.1.0"
BUNDLE_TYPE = "sstory-phase5-root-vision-view-bundle"
VIEW_ORDER = ("native", "full25", "full50", "focus200", "focus400")
VIEW_FILENAMES = {view_id: f"{view_id}.png" for view_id in VIEW_ORDER}
RECEIPT_FILENAME = "receipt.json"
PERSISTENT_RECEIPT_FILENAME = "view-bundle.json"
BUNDLE_INVENTORY = (*VIEW_FILENAMES.values(), RECEIPT_FILENAME)
FOCUS_CROP_SIZE_PX = 512
ROUNDING_RULE = "positive-integer-round-half-up-minimum-1"
ROUNDING_FORMULA = "max(1,floor(source_dimension*numerator/denominator+0.5))"
INTERPOLATION = "Pillow.Image.Resampling.LANCZOS"
PNG_OPTIONS: dict[str, Any] = {
    "format": "PNG",
    "compress_level": 9,
    "optimize": False,
}

DEFAULT_FOCUS_REGISTRY = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "controls"
    / "phase5-vision-focus-boxes.json"
)
DEFAULT_FOCUS_REGISTRY_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "phase5-vision-focus-boxes.schema.json"
)
DEFAULT_RECEIPT_SCHEMA = (
    REPO_ROOT
    / "world"
    / "map-production"
    / "schemas"
    / "phase5-vision-bundle-receipt.schema.json"
)
DEFAULT_MAP_SHEETS = (
    REPO_ROOT / "world" / "map-production" / "source" / "map-sheets.json"
)
DEFAULT_RESOLUTION_CONTRACT = (
    REPO_ROOT / "world" / "map-production" / "spec" / "resolution-contract.json"
)
CANONICAL_EVIDENCE_ROOT = REPO_ROOT / "world" / "map-production" / "qa" / "evidence"


class Phase5VisionEvidenceError(RuntimeError):
    """Raised when canonical Phase 5 Vision evidence is incomplete or stale."""


@dataclass(frozen=True)
class FocusRegistry:
    binding: BoundArtifact
    entries: dict[str, dict[str, Any]]
    ordered_sheet_ids: tuple[str, ...]
    supporting_bindings: tuple[BoundArtifact, ...] = ()

    def entry(self, sheet_id: str) -> dict[str, Any]:
        try:
            return self.entries[sheet_id]
        except KeyError as exc:
            raise Phase5VisionEvidenceError(
                f"canonical focus registry has no entry for {sheet_id!r}"
            ) from exc

    def assert_unchanged(self) -> None:
        self.binding.assert_unchanged()
        for binding in self.supporting_bindings:
            binding.assert_unchanged()


@dataclass(frozen=True)
class VisionEvidenceBindings:
    source: BoundArtifact
    receipt: BoundArtifact
    registry: BoundArtifact
    supporting: tuple[BoundArtifact, ...] = ()


def stable_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=False,
        )
        + "\n"
    ).encode("utf-8")


def _json_object(binding: BoundArtifact, label: str) -> dict[str, Any]:
    try:
        return binding.json_object()
    except BoundArtifactError as exc:
        raise Phase5VisionEvidenceError(
            f"{label} is not valid UTF-8 JSON: {exc}"
        ) from exc


def _schema(binding: BoundArtifact, label: str) -> dict[str, Any]:
    value = _json_object(binding, label)
    if not isinstance(value, dict):  # Defensive; _json_object already guarantees this.
        raise Phase5VisionEvidenceError(f"{label} must contain an object")
    return value


def _validate_schema(document: Any, schema: dict[str, Any], label: str) -> None:
    errors = schema_errors(document, schema)
    if errors:
        raise Phase5VisionEvidenceError(
            f"{label} schema validation failed: {errors[0]}"
        )


def _bind_hashed_artifact(
    value: Any,
    *,
    label: str,
    expected_path: Path | None = None,
) -> BoundArtifact:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise Phase5VisionEvidenceError(f"{label} must contain exactly path and sha256")
    raw_path = value.get("path")
    claimed = value.get("sha256")
    if not isinstance(raw_path, str) or not isinstance(claimed, str):
        raise Phase5VisionEvidenceError(f"{label} must contain string path and sha256")
    try:
        binding = bind_file(raw_path, label=label, trackable=True)
    except (BoundArtifactError, ReleasePathError) as exc:
        raise Phase5VisionEvidenceError(str(exc)) from exc
    if binding.sha256 != claimed:
        raise Phase5VisionEvidenceError(
            f"{label}.sha256 mismatch: receipt={claimed}, actual={binding.sha256}"
        )
    if expected_path is not None and not same_path(binding.path, expected_path):
        raise Phase5VisionEvidenceError(
            f"{label}.path must name canonical artifact {expected_path}"
        )
    return binding


def _validate_bound_resolution_inputs(
    contract: BoundArtifact,
    catalog: BoundArtifact,
) -> dict[str, Any]:
    """Derive resolution records only from the two bound byte snapshots."""

    try:
        with tempfile.TemporaryDirectory(
            prefix="sstory-phase5-vision-resolution-"
        ) as temporary_name:
            snapshot_root = Path(temporary_name)
            contract_snapshot = snapshot_root / "resolution-contract.json"
            catalog_snapshot = snapshot_root / "map-sheets.json"
            contract_snapshot.write_bytes(contract.data)
            catalog_snapshot.write_bytes(catalog.data)
            derived = resolution_contract.validate_resolution_contract(
                contract_snapshot,
                catalog_snapshot,
                check_catalog=True,
            )
    except (BoundArtifactError, OSError) as exc:
        raise Phase5VisionEvidenceError(
            f"cannot validate bound focus-registry resolution inputs: {exc}"
        ) from exc
    if not isinstance(derived, dict):
        raise Phase5VisionEvidenceError(
            "bound focus-registry resolution validation returned a non-object"
        )
    return derived


def load_focus_registry(path: str | Path | None = None) -> FocusRegistry:
    """Bind and validate the exact 23-entry canonical focus registry."""

    registry_path = DEFAULT_FOCUS_REGISTRY if path is None else path
    try:
        registry_binding = bind_file(
            registry_path, label="Phase 5 canonical focus registry", trackable=True
        )
        schema_binding = bind_file(
            DEFAULT_FOCUS_REGISTRY_SCHEMA,
            label="Phase 5 focus registry schema",
            trackable=True,
        )
    except (BoundArtifactError, ReleasePathError) as exc:
        raise Phase5VisionEvidenceError(str(exc)) from exc
    document = _json_object(registry_binding, "Phase 5 canonical focus registry")
    schema = _schema(schema_binding, "Phase 5 focus registry schema")
    _validate_schema(document, schema, "Phase 5 canonical focus registry")

    catalog = _bind_hashed_artifact(
        document.get("map_catalog"),
        label="focus registry map_catalog",
        expected_path=DEFAULT_MAP_SHEETS,
    )
    contract = _bind_hashed_artifact(
        document.get("resolution_contract"),
        label="focus registry resolution_contract",
        expected_path=DEFAULT_RESOLUTION_CONTRACT,
    )
    derived = _validate_bound_resolution_inputs(contract, catalog)
    if not derived.get("valid"):
        errors = derived.get("errors")
        detail = errors[0] if isinstance(errors, list) and errors else "unknown error"
        raise Phase5VisionEvidenceError(
            f"focus registry canonical resolution inputs are invalid: {detail}"
        )
    records = derived.get("sheets")
    if not isinstance(records, list) or len(records) != 23:
        raise Phase5VisionEvidenceError(
            "focus registry requires exactly 23 bounded resolution records"
        )
    expected_ids = tuple(record.get("sheet_id") for record in records)
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise Phase5VisionEvidenceError("focus registry entries must be an array")
    actual_ids = tuple(entry.get("sheet_id") for entry in entries)
    if actual_ids != expected_ids or len(set(actual_ids)) != 23:
        raise Phase5VisionEvidenceError(
            "focus registry entries must match the exact canonical 23-sheet order"
        )

    by_id: dict[str, dict[str, Any]] = {}
    for record, entry in zip(records, entries):
        sheet_id = record["sheet_id"]
        expected_size = [record["width"], record["height"]]
        if entry.get("source_size") != expected_size:
            raise Phase5VisionEvidenceError(
                f"focus registry {sheet_id} source_size mismatch: "
                f"expected={expected_size}, actual={entry.get('source_size')}"
            )
        box = entry.get("box_px")
        if not (
            isinstance(box, list)
            and len(box) == 4
            and all(
                isinstance(value, int) and not isinstance(value, bool) for value in box
            )
        ):
            raise Phase5VisionEvidenceError(
                f"focus registry {sheet_id} box_px is invalid"
            )
        x0, y0, x1, y1 = box
        width, height = expected_size
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise Phase5VisionEvidenceError(
                f"focus registry {sheet_id} box_px lies outside source_size"
            )
        if (x1 - x0, y1 - y0) != (FOCUS_CROP_SIZE_PX, FOCUS_CROP_SIZE_PX):
            raise Phase5VisionEvidenceError(
                f"focus registry {sheet_id} must use one exact "
                f"{FOCUS_CROP_SIZE_PX}x{FOCUS_CROP_SIZE_PX} crop"
            )
        by_id[sheet_id] = entry

    try:
        registry_binding.assert_unchanged()
        schema_binding.assert_unchanged()
        catalog.assert_unchanged()
        contract.assert_unchanged()
    except BoundArtifactError as exc:
        raise Phase5VisionEvidenceError(str(exc)) from exc
    return FocusRegistry(
        registry_binding,
        by_id,
        expected_ids,
        (schema_binding, catalog, contract),
    )


def _round_half_up_scaled(value: int, numerator: int, denominator: int) -> int:
    return max(1, (2 * value * numerator + denominator) // (2 * denominator))


def _encode_png(image: Image.Image) -> bytes:
    if image.mode != "RGB":
        raise Phase5VisionEvidenceError(f"review view must be RGB, found {image.mode}")
    image.info.clear()
    buffer = BytesIO()
    image.save(buffer, pnginfo=PngImagePlugin.PngInfo(), **PNG_OPTIONS)
    return buffer.getvalue()


def _view_artifact(view_id: str, image: Image.Image) -> dict[str, Any]:
    payload = _encode_png(image)
    return {
        "id": view_id,
        "path": VIEW_FILENAMES[view_id],
        "sha256": hashlib.sha256(payload).hexdigest(),
        "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
        "bytes": len(payload),
        "mode": "RGB",
        "size": list(image.size),
    }


def render_view_artifacts(
    source: BoundArtifact, focus_box: Sequence[int]
) -> tuple[tuple[int, int], list[dict[str, Any]]]:
    """Recompute the exact encoded and pixel hashes for all canonical views."""

    try:
        with source.open_binary() as handle, Image.open(handle) as opened:
            opened.load()
            if opened.format != "PNG" or opened.mode != "RGB":
                raise Phase5VisionEvidenceError(
                    "Phase 5 Vision source must be a native RGB PNG"
                )
            image = opened.copy()
    except (OSError, UnidentifiedImageError, BoundArtifactError) as exc:
        raise Phase5VisionEvidenceError(
            f"cannot decode Phase 5 Vision source: {exc}"
        ) from exc
    image.info.clear()
    try:
        if not (
            len(focus_box) == 4
            and all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in focus_box
            )
        ):
            raise Phase5VisionEvidenceError(
                "canonical focus box must contain four integers"
            )
        x0, y0, x1, y1 = focus_box
        if not (0 <= x0 < x1 <= image.width and 0 <= y0 < y1 <= image.height):
            raise Phase5VisionEvidenceError(
                "canonical focus box lies outside source image"
            )
        views: list[dict[str, Any]] = []
        native = image.copy()
        try:
            views.append(_view_artifact("native", native))
        finally:
            native.close()
        for view_id, numerator, denominator in (
            ("full25", 1, 4),
            ("full50", 1, 2),
        ):
            resized = image.resize(
                (
                    _round_half_up_scaled(image.width, numerator, denominator),
                    _round_half_up_scaled(image.height, numerator, denominator),
                ),
                Image.Resampling.LANCZOS,
            )
            try:
                views.append(_view_artifact(view_id, resized))
            finally:
                resized.close()
        crop = image.crop((x0, y0, x1, y1))
        try:
            for view_id, scale in (("focus200", 2), ("focus400", 4)):
                resized = crop.resize(
                    (crop.width * scale, crop.height * scale),
                    Image.Resampling.LANCZOS,
                )
                try:
                    views.append(_view_artifact(view_id, resized))
                finally:
                    resized.close()
        finally:
            crop.close()
        if [view["id"] for view in views] != list(VIEW_ORDER):
            raise Phase5VisionEvidenceError("canonical exact-five view order drifted")
        return image.size, views
    finally:
        image.close()


def build_canonical_receipt(
    *,
    sheet_id: str,
    source: BoundArtifact,
    source_size: tuple[int, int],
    focus_registry: BoundArtifact,
    focus_box: Sequence[int],
    views: list[dict[str, Any]],
) -> dict[str, Any]:
    """Construct the schema-1.1 hash-only receipt persisted in tracked evidence."""

    x0, y0, x1, y1 = focus_box
    canonical_views = [
        {
            **{key: value for key, value in view.items() if key != "path"},
            "filename": view["path"],
        }
        for view in views
    ]
    return {
        "schema_version": CANONICAL_RECEIPT_SCHEMA_VERSION,
        "type": BUNDLE_TYPE,
        "sheet_id": sheet_id,
        "view_order": list(VIEW_ORDER),
        "inventory": list(BUNDLE_INVENTORY),
        "source": {
            "path": source.relative,
            "sha256": source.sha256,
            "bytes": source.signature[2],
            "mode": "RGB",
            "size": list(source_size),
        },
        "focus_registry": focus_registry.artifact(),
        "focus": {
            "box_px": list(focus_box),
            "crop_size": [x1 - x0, y1 - y0],
            "coordinate_convention": "left-top-inclusive_right-bottom-exclusive",
        },
        "rendering": {
            "full_size_rounding": ROUNDING_RULE,
            "full_size_rounding_formula": ROUNDING_FORMULA,
            "interpolation": {
                "native": "none",
                "full25": INTERPOLATION,
                "full50": INTERPOLATION,
                "focus200": INTERPOLATION,
                "focus400": INTERPOLATION,
            },
            "transforms": {
                "native": {"kind": "identity"},
                "full25": {"kind": "full-frame-resize", "scale": [1, 4]},
                "full50": {"kind": "full-frame-resize", "scale": [1, 2]},
                "focus200": {"kind": "focus-crop-resize", "scale": [2, 1]},
                "focus400": {"kind": "focus-crop-resize", "scale": [4, 1]},
            },
            "png": {
                "format": "PNG",
                "mode": "RGB",
                "compress_level": 9,
                "optimize": False,
                "metadata": {},
            },
        },
        "views": canonical_views,
    }


def validate_persistent_receipt_location(
    path: str | Path, sheet_id: str
) -> tuple[Path, str]:
    """Resolve one exact canonical receipt path without creating any component."""

    try:
        resolved, relative = require_trackable_path(
            path,
            label="Phase 5 persistent Vision receipt",
            must_exist=False,
            require_file=False,
        )
        evidence_root, _ = require_trackable_path(
            CANONICAL_EVIDENCE_ROOT,
            label="Phase 5 canonical evidence root",
            require_file=False,
        )
    except ReleasePathError as exc:
        raise Phase5VisionEvidenceError(str(exc)) from exc
    try:
        nested = resolved.relative_to(evidence_root)
    except ValueError as exc:
        raise Phase5VisionEvidenceError(
            "persistent Vision receipt must be below world/map-production/qa/evidence"
        ) from exc
    if (
        len(nested.parts) != 3
        or nested.parts[-2] != sheet_id
        or nested.name != PERSISTENT_RECEIPT_FILENAME
    ):
        raise Phase5VisionEvidenceError(
            "persistent Vision receipt must use "
            "<evidence-root>/<version>/<sheet-id>/view-bundle.json"
        )
    return resolved, relative


def bind_report_receipt(value: Any, *, sheet_id: str) -> BoundArtifact:
    """Bind the receipt artifact named by a QA report without validating the master."""

    if not isinstance(value, dict):
        raise Phase5VisionEvidenceError("vision_bundle must be an object")
    if value.get("reviewer_confirmed_exact_five") is not True:
        raise Phase5VisionEvidenceError(
            "Vision reviewer must explicitly confirm the exact-five bundle"
        )
    receipt = _bind_hashed_artifact(
        value.get("receipt"), label=f"{sheet_id} persistent Vision receipt"
    )
    expected_path, _ = validate_persistent_receipt_location(receipt.path, sheet_id)
    if not same_path(receipt.path, expected_path):
        raise Phase5VisionEvidenceError("persistent Vision receipt path changed")
    return receipt


def validate_report_vision_bundle(
    report: dict[str, Any],
    *,
    sheet_id: str,
    master_path: str | Path,
    master_sha256: str,
    focus_registry_path: str | Path | None = None,
) -> VisionEvidenceBindings:
    """Recompute and bind one accepted report's exact-five evidence chain."""

    receipt = bind_report_receipt(report.get("vision_bundle"), sheet_id=sheet_id)
    try:
        source = bind_file(master_path, label=f"{sheet_id} Vision source master")
        receipt_schema_binding = bind_file(
            DEFAULT_RECEIPT_SCHEMA,
            label="Phase 5 Vision bundle receipt schema",
        )
    except (BoundArtifactError, ReleasePathError) as exc:
        raise Phase5VisionEvidenceError(str(exc)) from exc
    if source.sha256 != master_sha256:
        raise Phase5VisionEvidenceError(
            f"{sheet_id} Vision source master SHA-256 changed"
        )
    registry = load_focus_registry(focus_registry_path)
    entry = registry.entry(sheet_id)
    document = _json_object(receipt, f"{sheet_id} persistent Vision receipt")
    schema = _schema(receipt_schema_binding, "Phase 5 Vision receipt schema")
    _validate_schema(document, schema, f"{sheet_id} persistent Vision receipt")
    if stable_json_bytes(document) != receipt.data:
        raise Phase5VisionEvidenceError(
            f"{sheet_id} persistent Vision receipt is not canonical JSON"
        )
    if document.get("sheet_id") != sheet_id:
        raise Phase5VisionEvidenceError(f"{sheet_id} Vision receipt sheet_id mismatch")
    if document.get("focus_registry") != registry.binding.artifact():
        raise Phase5VisionEvidenceError(
            f"{sheet_id} Vision receipt does not bind the canonical focus registry"
        )
    source_size, views = render_view_artifacts(source, entry["box_px"])
    if list(source_size) != entry["source_size"]:
        raise Phase5VisionEvidenceError(
            f"{sheet_id} Vision source dimensions differ from canonical focus registry"
        )
    expected = build_canonical_receipt(
        sheet_id=sheet_id,
        source=source,
        source_size=source_size,
        focus_registry=registry.binding,
        focus_box=entry["box_px"],
        views=views,
    )
    if document != expected:
        raise Phase5VisionEvidenceError(
            f"{sheet_id} persistent Vision receipt is stale or has a view/focus/inventory mismatch"
        )
    try:
        source.assert_unchanged()
        receipt.assert_unchanged()
        registry.assert_unchanged()
        receipt_schema_binding.assert_unchanged()
    except BoundArtifactError as exc:
        raise Phase5VisionEvidenceError(str(exc)) from exc
    return VisionEvidenceBindings(
        source,
        receipt,
        registry.binding,
        (receipt_schema_binding, *registry.supporting_bindings),
    )
