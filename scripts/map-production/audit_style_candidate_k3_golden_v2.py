#!/usr/bin/env python3
"""Independently recompute the fixed K3 Golden-v2 pixel gates.

The promotion renderer is not trusted to report its own measurements.  This
module consumes three byte snapshots -- candidate, baseline, and a compact
control document -- then derives every automated Golden-v2 metric directly
from decoded pixels and SHA-256-bound binary masks.  The report deliberately
contains no timestamp, host path, or platform-specific value so the same
inputs produce the same JSON value on Windows and Linux.

``audit_candidate`` accepts normal ``Path`` objects or BoundArtifact-like
objects exposing ``data``, ``sha256``, and optionally ``path``.  Callers that
already hold bound mask snapshots should pass them with ``mask_bindings``;
otherwise mask paths are resolved relative to the control document.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import cv2
import numpy as np
from PIL import Image, ImageStat, UnidentifiedImageError


SCHEMA_VERSION = "1.0.0"
CONTROL_ID = "sstory-k3-golden-v2-pixel-audit-control"
REPORT_ID = "style-candidate-k-v3-golden-v2-independent-pixel-audit"
ALGORITHM = "sstory-k3-golden-v2-independent-pixel-audit-v2"
CONTROL_REPRODUCTION_ROLE = "golden-v2-pixel-audit-control"
BASELINE_REPRODUCTION_ROLE = "golden-v2-pixel-audit-baseline"

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MACROCELL_GRID = (24, 16)
MACROCELL_MINIMUM_LUMA_STDDEV = 6.0
MASK_NAMES = (
    "measurement_inside",
    "texture_reference",
    "permission",
    "protected_features",
    "road_calm_18px",
    "selected_components",
)
MASK_REPRODUCTION_ROLES = {
    name: f"golden-v2-mask-{name.replace('_', '-')}" for name in MASK_NAMES
}
METRIC_THRESHOLDS = {
    "coverage_50_min": 360,
    "coverage_25_min": 334,
    "quiet_fraction_min": 0.905,
    "dash_bundle_pairs_exact": 0,
    "orientation_coherence_max": 0.16,
    "texture_ratio_4_min": 0.61,
    "texture_ratio_8_min": 0.75,
    "texture_ratio_8_max": 1.22,
}
GEOMETRY_ALGORITHM = "selected-mask-components-with-material-extent-v2"
GEOMETRY_THRESHOLDS = {
    "minimum_changed_pixels": 4,
    "minimum_changed_fraction": 0.5,
    "minimum_changed_x_span_fraction": 0.5,
    "minimum_changed_y_span_fraction": 0.5,
    "minimum_peak_channel_delta": 1,
}
GATE_NAMES = frozenset(
    {
        "coverage_50_min_360",
        "coverage_25_min_334",
        "quiet_fraction_min_0_905",
        "dash_bundle_pairs_zero",
        "orientation_coherence_max_0_16",
        "texture_ratio_4_min_0_61",
        "texture_ratio_8_range_0_75_1_22",
        "selected_component_count_exact_8",
        "outside_permission_zero",
        "protected_features_zero",
        "road_calm_18px_zero",
    }
)
REPORT_REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "id",
        "algorithm",
        "control_sha256",
        "candidate_sha256",
        "baseline_sha256",
        "mask_sha256",
        "metrics",
        "geometry",
        "geometry_proof",
        "identity",
        "gates",
        "failed_gates",
        "passed",
    }
)


class GoldenV2PixelAuditError(RuntimeError):
    """Raised when independent pixel evidence cannot be trusted."""


@dataclass(frozen=True)
class ByteSnapshot:
    """One immutable in-memory byte snapshot used by the auditor."""

    data: bytes
    sha256: str
    path: Path | None


@dataclass(frozen=True)
class MaskRecord:
    """One mask reference normalized from the control document."""

    name: str
    reproduction_role: str
    path: PurePosixPath
    sha256: str


@dataclass(frozen=True)
class AuditControl:
    """Validated Golden-v2 audit control and its exact byte identity."""

    snapshot: ByteSnapshot
    size: tuple[int, int]
    candidate_sha256: str
    baseline_sha256: str
    baseline_reproduction_role: str
    masks: Mapping[str, MaskRecord]

    @property
    def control_sha256(self) -> str:
        return self.snapshot.sha256

    @property
    def mask_reproduction_roles(self) -> dict[str, str]:
        return {name: self.masks[name].reproduction_role for name in MASK_NAMES}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise GoldenV2PixelAuditError(f"{label} must be one lowercase SHA-256 digest")
    return value


def _require_exact_keys(
    value: Any, expected: set[str], *, label: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        observed = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise GoldenV2PixelAuditError(
            f"{label} key set mismatch: expected={sorted(expected)}, "
            f"observed={observed}"
        )
    return value


def _snapshot(value: Any, *, label: str) -> ByteSnapshot:
    """Read and verify a Path or BoundArtifact-like value exactly once."""

    if isinstance(value, (str, Path)):
        path = Path(value)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise GoldenV2PixelAuditError(
                f"cannot read {label}: {path}: {exc}"
            ) from exc
        return ByteSnapshot(data=data, sha256=_sha256(data), path=path.resolve())

    try:
        raw_data = value.data
        reported_sha256 = value.sha256
    except Exception as exc:
        raise GoldenV2PixelAuditError(
            f"{label} must be a Path or a bound object with data and sha256"
        ) from exc
    if not isinstance(raw_data, (bytes, bytearray, memoryview)):
        raise GoldenV2PixelAuditError(f"{label}.data must be bytes")
    data = bytes(raw_data)
    digest = _sha256(data)
    if _require_sha256(reported_sha256, label=f"{label}.sha256") != digest:
        raise GoldenV2PixelAuditError(f"{label} bound SHA-256 is stale")
    raw_path = getattr(value, "path", None)
    path = Path(raw_path).resolve() if raw_path is not None else None
    return ByteSnapshot(data=data, sha256=digest, path=path)


def _safe_relative_path(value: Any, *, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise GoldenV2PixelAuditError(
            f"{label} must be a non-empty portable relative POSIX path"
        )
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise GoldenV2PixelAuditError(
            f"{label} must be a normalized relative POSIX path"
        )
    if ":" in path.parts[0]:
        raise GoldenV2PixelAuditError(f"{label} must not contain a drive prefix")
    if path.as_posix() != value:
        raise GoldenV2PixelAuditError(f"{label} must already be normalized")
    return path


def load_audit_control(control_binding: Any) -> AuditControl:
    """Load and strictly validate one SHA-bound Golden-v2 control document."""

    snapshot = _snapshot(control_binding, label="audit control")
    try:
        record = json.loads(snapshot.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoldenV2PixelAuditError("audit control must be valid UTF-8 JSON") from exc
    record = _require_exact_keys(
        record,
        {
            "schema_version",
            "id",
            "algorithm",
            "image",
            "candidate",
            "baseline",
            "masks",
        },
        label="audit control",
    )
    if record["schema_version"] != SCHEMA_VERSION:
        raise GoldenV2PixelAuditError("audit control schema_version mismatch")
    if record["id"] != CONTROL_ID:
        raise GoldenV2PixelAuditError("audit control id mismatch")
    if record["algorithm"] != ALGORITHM:
        raise GoldenV2PixelAuditError("audit control algorithm mismatch")

    image = _require_exact_keys(record["image"], {"mode", "size"}, label="image")
    size = image["size"]
    if image["mode"] != "RGB":
        raise GoldenV2PixelAuditError("image.mode must be RGB")
    if (
        not isinstance(size, list)
        or len(size) != 2
        or any(
            not isinstance(item, int) or isinstance(item, bool) or item <= 0
            for item in size
        )
    ):
        raise GoldenV2PixelAuditError("image.size must be [positive width, height]")
    width, height = size
    if width > 16_384 or height > 16_384 or width * height > 100_000_000:
        raise GoldenV2PixelAuditError("image.size exceeds the bounded audit canvas")
    minimum_width = MACROCELL_GRID[0] * 4
    minimum_height = MACROCELL_GRID[1] * 4
    if width < minimum_width or height < minimum_height:
        raise GoldenV2PixelAuditError(
            f"image.size must be at least {minimum_width}x{minimum_height}"
        )

    candidate = _require_exact_keys(record["candidate"], {"sha256"}, label="candidate")
    baseline = _require_exact_keys(
        record["baseline"],
        {"reproduction_role", "sha256"},
        label="baseline",
    )
    if baseline["reproduction_role"] != BASELINE_REPRODUCTION_ROLE:
        raise GoldenV2PixelAuditError("baseline reproduction_role mismatch")

    raw_masks = _require_exact_keys(record["masks"], set(MASK_NAMES), label="masks")
    masks: dict[str, MaskRecord] = {}
    for name in MASK_NAMES:
        raw = _require_exact_keys(
            raw_masks[name],
            {"reproduction_role", "path", "sha256"},
            label=f"masks.{name}",
        )
        expected_role = MASK_REPRODUCTION_ROLES[name]
        if raw["reproduction_role"] != expected_role:
            raise GoldenV2PixelAuditError(
                f"masks.{name}.reproduction_role must be {expected_role!r}"
            )
        masks[name] = MaskRecord(
            name=name,
            reproduction_role=expected_role,
            path=_safe_relative_path(raw["path"], label=f"masks.{name}.path"),
            sha256=_require_sha256(raw["sha256"], label=f"masks.{name}.sha256"),
        )

    return AuditControl(
        snapshot=snapshot,
        size=(width, height),
        candidate_sha256=_require_sha256(candidate["sha256"], label="candidate.sha256"),
        baseline_sha256=_require_sha256(baseline["sha256"], label="baseline.sha256"),
        baseline_reproduction_role=BASELINE_REPRODUCTION_ROLE,
        masks=masks,
    )


def _decode_rgb(
    snapshot: ByteSnapshot, *, size: tuple[int, int], label: str
) -> np.ndarray:
    if not snapshot.data.startswith(PNG_SIGNATURE):
        raise GoldenV2PixelAuditError(f"{label} must be a PNG")
    try:
        with Image.open(io.BytesIO(snapshot.data)) as opened:
            if opened.format != "PNG":
                raise GoldenV2PixelAuditError(f"{label} must decode as PNG")
            opened.load()
            if (
                opened.mode != "RGB"
                or opened.getbands() != ("R", "G", "B")
                or opened.size != size
                or opened.info.get("transparency") is not None
                or opened.info.get("icc_profile")
            ):
                raise GoldenV2PixelAuditError(
                    f"{label} must be profile-free RGB PNG at {size}"
                )
            image = np.asarray(opened, dtype=np.uint8).copy()
    except (OSError, UnidentifiedImageError) as exc:
        raise GoldenV2PixelAuditError(f"cannot decode {label} PNG") from exc
    if image.shape != (size[1], size[0], 3):
        raise GoldenV2PixelAuditError(f"{label} decoded array shape mismatch")
    return image


def _decode_mask(
    snapshot: ByteSnapshot, *, size: tuple[int, int], label: str
) -> np.ndarray:
    if not snapshot.data.startswith(PNG_SIGNATURE):
        raise GoldenV2PixelAuditError(f"{label} must be a PNG")
    try:
        with Image.open(io.BytesIO(snapshot.data)) as opened:
            if opened.format != "PNG":
                raise GoldenV2PixelAuditError(f"{label} must decode as PNG")
            opened.load()
            if (
                opened.mode != "L"
                or opened.getbands() != ("L",)
                or opened.size != size
                or opened.info.get("transparency") is not None
                or opened.info.get("icc_profile")
            ):
                raise GoldenV2PixelAuditError(
                    f"{label} must be profile-free binary-L PNG at {size}"
                )
            values = np.asarray(opened, dtype=np.uint8).copy()
    except (OSError, UnidentifiedImageError) as exc:
        raise GoldenV2PixelAuditError(f"cannot decode {label} PNG") from exc
    unique = np.unique(values)
    if not all(int(value) in (0, 255) for value in unique):
        raise GoldenV2PixelAuditError(f"{label} must contain only 0 and 255")
    return values == np.uint8(255)


def _resolve_mask_snapshots(
    control: AuditControl, mask_bindings: Mapping[str, Any] | None
) -> dict[str, ByteSnapshot]:
    if mask_bindings is not None:
        semantic_keys = set(MASK_NAMES)
        role_to_name = {
            control.masks[name].reproduction_role: name for name in MASK_NAMES
        }
        if set(mask_bindings) == semantic_keys:
            values = {name: mask_bindings[name] for name in MASK_NAMES}
        elif set(mask_bindings) == set(role_to_name):
            values = {
                name: mask_bindings[control.masks[name].reproduction_role]
                for name in MASK_NAMES
            }
        else:
            raise GoldenV2PixelAuditError(
                "mask_bindings must have the exact semantic-name or reproduction-role set"
            )
        return {
            name: _snapshot(values[name], label=f"mask {name}") for name in MASK_NAMES
        }

    if control.snapshot.path is None:
        raise GoldenV2PixelAuditError(
            "pathless audit control requires explicitly bound mask_bindings"
        )
    parent = control.snapshot.path.parent.resolve()
    snapshots: dict[str, ByteSnapshot] = {}
    for name in MASK_NAMES:
        record = control.masks[name]
        candidate = parent.joinpath(*record.path.parts)
        resolved = candidate.resolve()
        try:
            resolved.relative_to(parent)
        except ValueError as exc:
            raise GoldenV2PixelAuditError(
                f"mask {name} escaped the control directory"
            ) from exc
        snapshots[name] = _snapshot(resolved, label=f"mask {name}")
    return snapshots


def _macrocell_coverage_count(gray: Image.Image) -> int:
    columns, rows = MACROCELL_GRID
    covered = 0
    for row in range(rows):
        top = row * gray.height // rows
        bottom = (row + 1) * gray.height // rows
        for column in range(columns):
            left = column * gray.width // columns
            right = (column + 1) * gray.width // columns
            with gray.crop((left, top, right, bottom)) as cell:
                if ImageStat.Stat(cell).stddev[0] >= MACROCELL_MINIMUM_LUMA_STDDEV:
                    covered += 1
    return covered


def _coverage(candidate: np.ndarray) -> tuple[int, int]:
    counts: list[int] = []
    with Image.fromarray(candidate, mode="RGB") as image:
        for scale in (0.5, 0.25):
            scaled = image.resize(
                (round(image.width * scale), round(image.height * scale)),
                Image.Resampling.LANCZOS,
            )
            try:
                with scaled.convert("L") as gray:
                    counts.append(_macrocell_coverage_count(gray))
            finally:
                scaled.close()
    return counts[0], counts[1]


def _gray_float(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY).astype(np.float32)


def _activity_mask(image: np.ndarray, permission: np.ndarray) -> np.ndarray:
    gray = _gray_float(image)
    low = cv2.GaussianBlur(gray, (0, 0), 1.6)
    high = np.abs(gray - low)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(gx, gy)
    active = ((high >= 6.0) | (gradient >= 26.0)) & permission
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    return cv2.dilate(active.astype(np.uint8), kernel) > 0


def _quiet_fraction(image: np.ndarray, measurement: np.ndarray) -> float:
    active = _activity_mask(image, measurement)
    return round(float(np.mean(~active[measurement])), 6)


def _hough_segments(
    image: np.ndarray, measurement: np.ndarray
) -> list[tuple[int, int, int, int]]:
    gray = _gray_float(image).astype(np.uint8)
    local = cv2.medianBlur(gray, 9)
    ink = ((local.astype(np.int16) - gray.astype(np.int16)) >= 7) & measurement
    cv2.setRNGSeed(0x4B33)
    lines = cv2.HoughLinesP(
        ink.astype(np.uint8) * 255,
        1,
        np.pi / 180,
        threshold=5,
        minLineLength=3,
        maxLineGap=1,
    )
    if lines is None:
        return []
    return [tuple(int(value) for value in line[0]) for line in lines]


def _dash_bundle_pairs(image: np.ndarray, measurement: np.ndarray) -> int:
    short: list[tuple[float, float, float]] = []
    for x0, y0, x1, y1 in _hough_segments(image, measurement):
        length = math.hypot(x1 - x0, y1 - y0)
        if 3 <= length <= 12:
            angle = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180
            short.append(((x0 + x1) / 2, (y0 + y1) / 2, angle))
    bundled: set[tuple[int, int]] = set()
    for first in range(len(short)):
        x0, y0, angle0 = short[first]
        for second in range(first + 1, len(short)):
            x1, y1, angle1 = short[second]
            angle_delta = abs(angle0 - angle1)
            angle_delta = min(angle_delta, 180 - angle_delta)
            if math.hypot(x1 - x0, y1 - y0) <= 11 and angle_delta <= 10:
                bundled.add((first, second))
    return len(bundled)


def _orientation_coherence(image: np.ndarray, measurement: np.ndarray) -> float:
    gray = _gray_float(image)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    active = _activity_mask(image, measurement) & measurement
    if not np.any(active):
        coherence = 0.0
    else:
        jxx = float(np.mean(gx[active] ** 2))
        jyy = float(np.mean(gy[active] ** 2))
        jxy = float(np.mean(gx[active] * gy[active]))
        coherence = math.sqrt((jxx - jyy) ** 2 + 4 * jxy**2) / max(jxx + jyy, 1e-6)
    return round(coherence, 6)


def _gaussian(values: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(
        values.astype(np.float32),
        (0, 0),
        sigmaX=sigma,
        sigmaY=sigma,
        borderType=cv2.BORDER_REFLECT,
    )


def _texture_ratios(
    candidate: np.ndarray,
    baseline: np.ndarray,
    measurement: np.ndarray,
    reference: np.ndarray,
) -> dict[str, float]:
    candidate_gray = _gray_float(candidate)
    baseline_gray = _gray_float(baseline)
    result: dict[str, float] = {}
    for sigma in (4, 8):
        candidate_energy = np.abs(
            candidate_gray - _gaussian(candidate_gray, float(sigma))
        )
        baseline_energy = np.abs(baseline_gray - _gaussian(baseline_gray, float(sigma)))
        numerator = float(np.mean(candidate_energy[measurement]))
        denominator = float(np.mean(baseline_energy[reference]))
        result[str(sigma)] = round(numerator / max(denominator, 1e-9), 6)
    return result


def _pixel_derived_geometry(
    selected: np.ndarray, candidate: np.ndarray, baseline: np.ndarray
) -> tuple[dict[str, int], dict[str, Any]]:
    """Prove each selected terrain component contains real candidate pixels.

    The selected mask identifies the eight authorized terrain regions, but it
    is not itself evidence that the renderer changed anything.  A component
    counts only when at least half its pixels differ from the SHA-bound
    baseline and those changed pixels span at least half of both mask axes.
    This prevents eight tiny or stippled deltas from masquerading as eight
    rendered terrain systems.
    """

    component_total, labels = cv2.connectedComponents(
        selected.astype(np.uint8), connectivity=8, ltype=cv2.CV_32S
    )
    channel_delta = np.max(
        np.abs(candidate.astype(np.int16) - baseline.astype(np.int16)), axis=2
    )
    significant = channel_delta >= GEOMETRY_THRESHOLDS["minimum_peak_channel_delta"]
    components: list[dict[str, Any]] = []
    valid_count = 0
    for component_id in range(1, component_total):
        region = labels == component_id
        mask_pixels = int(np.count_nonzero(region))
        changed = region & significant
        changed_pixels = int(np.count_nonzero(changed))
        changed_fraction = changed_pixels / mask_pixels
        peak_delta = int(np.max(channel_delta[region]))

        mask_y, mask_x = np.nonzero(region)
        mask_bbox = [
            int(mask_x.min()),
            int(mask_y.min()),
            int(mask_x.max()) + 1,
            int(mask_y.max()) + 1,
        ]
        changed_y, changed_x = np.nonzero(changed)
        if changed_pixels:
            changed_bbox: list[int] | None = [
                int(changed_x.min()),
                int(changed_y.min()),
                int(changed_x.max()) + 1,
                int(changed_y.max()) + 1,
            ]
            changed_x_span_fraction = (changed_bbox[2] - changed_bbox[0]) / (
                mask_bbox[2] - mask_bbox[0]
            )
            changed_y_span_fraction = (changed_bbox[3] - changed_bbox[1]) / (
                mask_bbox[3] - mask_bbox[1]
            )
        else:
            changed_bbox = None
            changed_x_span_fraction = 0.0
            changed_y_span_fraction = 0.0
        valid = (
            changed_pixels >= GEOMETRY_THRESHOLDS["minimum_changed_pixels"]
            and changed_fraction >= GEOMETRY_THRESHOLDS["minimum_changed_fraction"]
            and changed_x_span_fraction
            >= GEOMETRY_THRESHOLDS["minimum_changed_x_span_fraction"]
            and changed_y_span_fraction
            >= GEOMETRY_THRESHOLDS["minimum_changed_y_span_fraction"]
            and peak_delta >= GEOMETRY_THRESHOLDS["minimum_peak_channel_delta"]
        )
        valid_count += int(valid)
        components.append(
            {
                "component_id": component_id,
                "mask_pixels": mask_pixels,
                "changed_pixels": changed_pixels,
                "changed_fraction": round(changed_fraction, 6),
                "mask_bbox_xyxy": mask_bbox,
                "changed_bbox_xyxy": changed_bbox,
                "changed_x_span_fraction": round(changed_x_span_fraction, 6),
                "changed_y_span_fraction": round(changed_y_span_fraction, 6),
                "peak_channel_delta": peak_delta,
                "valid": valid,
            }
        )
    geometry = {"selected_component_count": valid_count}
    proof = {
        "algorithm": GEOMETRY_ALGORITHM,
        "thresholds": dict(GEOMETRY_THRESHOLDS),
        "mask_component_count": component_total - 1,
        "valid_component_count": valid_count,
        "components": components,
    }
    return geometry, proof


def audit_candidate(
    candidate_binding: Any,
    baseline_binding: Any,
    control_binding: Any,
    *,
    mask_bindings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return deterministic metrics, geometry, identity, and fixed gate results."""

    control = load_audit_control(control_binding)
    candidate_snapshot = _snapshot(candidate_binding, label="candidate")
    baseline_snapshot = _snapshot(baseline_binding, label="baseline")
    if candidate_snapshot.sha256 != control.candidate_sha256:
        raise GoldenV2PixelAuditError("candidate SHA-256 does not match audit control")
    if baseline_snapshot.sha256 != control.baseline_sha256:
        raise GoldenV2PixelAuditError("baseline SHA-256 does not match audit control")

    candidate = _decode_rgb(candidate_snapshot, size=control.size, label="candidate")
    baseline = _decode_rgb(baseline_snapshot, size=control.size, label="baseline")
    mask_snapshots = _resolve_mask_snapshots(control, mask_bindings)
    masks: dict[str, np.ndarray] = {}
    for name in MASK_NAMES:
        snapshot = mask_snapshots[name]
        if snapshot.sha256 != control.masks[name].sha256:
            raise GoldenV2PixelAuditError(
                f"mask {name} SHA-256 does not match audit control"
            )
        masks[name] = _decode_mask(snapshot, size=control.size, label=f"mask {name}")

    measurement = masks["measurement_inside"]
    texture_reference = masks["texture_reference"]
    permission = masks["permission"]
    selected = masks["selected_components"]
    if not np.any(measurement):
        raise GoldenV2PixelAuditError("measurement_inside mask must be non-empty")
    if not np.any(texture_reference):
        raise GoldenV2PixelAuditError("texture_reference mask must be non-empty")
    if not np.any(permission):
        raise GoldenV2PixelAuditError("permission mask must be non-empty")
    if not np.any(selected):
        raise GoldenV2PixelAuditError("selected_components mask must be non-empty")
    if np.any(measurement & ~permission):
        raise GoldenV2PixelAuditError("measurement_inside must be within permission")
    if np.any(selected & ~measurement):
        raise GoldenV2PixelAuditError(
            "selected_components must be within measurement_inside"
        )

    coverage_50, coverage_25 = _coverage(candidate)
    metrics = {
        "coverage_50": coverage_50,
        "coverage_25": coverage_25,
        "quiet_fraction": _quiet_fraction(candidate, measurement),
        "dash_bundle_pairs": _dash_bundle_pairs(candidate, measurement),
        "orientation_coherence": _orientation_coherence(candidate, measurement),
        "texture_inside_to_outside_ratio": _texture_ratios(
            candidate, baseline, measurement, texture_reference
        ),
    }
    geometry, geometry_proof = _pixel_derived_geometry(selected, candidate, baseline)
    changed = np.any(candidate != baseline, axis=2)
    identity = {
        "outside_permission": int(np.count_nonzero(changed & ~permission)),
        "protected_features": int(
            np.count_nonzero(changed & masks["protected_features"])
        ),
        "road_calm_18px": int(np.count_nonzero(changed & masks["road_calm_18px"])),
    }
    texture = metrics["texture_inside_to_outside_ratio"]
    gates = {
        "coverage_50_min_360": metrics["coverage_50"]
        >= METRIC_THRESHOLDS["coverage_50_min"],
        "coverage_25_min_334": metrics["coverage_25"]
        >= METRIC_THRESHOLDS["coverage_25_min"],
        "quiet_fraction_min_0_905": metrics["quiet_fraction"]
        >= METRIC_THRESHOLDS["quiet_fraction_min"],
        "dash_bundle_pairs_zero": metrics["dash_bundle_pairs"]
        == METRIC_THRESHOLDS["dash_bundle_pairs_exact"],
        "orientation_coherence_max_0_16": metrics["orientation_coherence"]
        <= METRIC_THRESHOLDS["orientation_coherence_max"],
        "texture_ratio_4_min_0_61": texture["4"]
        >= METRIC_THRESHOLDS["texture_ratio_4_min"],
        "texture_ratio_8_range_0_75_1_22": (
            METRIC_THRESHOLDS["texture_ratio_8_min"]
            <= texture["8"]
            <= METRIC_THRESHOLDS["texture_ratio_8_max"]
        ),
        "selected_component_count_exact_8": geometry["selected_component_count"] == 8,
        "outside_permission_zero": identity["outside_permission"] == 0,
        "protected_features_zero": identity["protected_features"] == 0,
        "road_calm_18px_zero": identity["road_calm_18px"] == 0,
    }
    if set(gates) != GATE_NAMES:  # pragma: no cover - guards maintenance drift
        raise GoldenV2PixelAuditError("internal fixed gate set drifted")
    failed_gates = sorted(name for name, passed in gates.items() if not passed)
    return {
        "schema_version": SCHEMA_VERSION,
        "id": REPORT_ID,
        "algorithm": ALGORITHM,
        "control_sha256": control.control_sha256,
        "candidate_sha256": candidate_snapshot.sha256,
        "baseline_sha256": baseline_snapshot.sha256,
        "mask_sha256": {name: mask_snapshots[name].sha256 for name in MASK_NAMES},
        "metrics": metrics,
        "geometry": geometry,
        "geometry_proof": geometry_proof,
        "identity": identity,
        "gates": gates,
        "failed_gates": failed_gates,
        "passed": not failed_gates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit_candidate(args.candidate, args.baseline, args.control)
    except GoldenV2PixelAuditError as exc:
        parser.exit(2, f"Golden-v2 pixel audit failed closed: {exc}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
