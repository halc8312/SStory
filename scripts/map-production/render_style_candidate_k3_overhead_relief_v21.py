#!/usr/bin/env python3
"""Render the deterministic K3 v21 sparse overhead-relief Golden attempt.

V21 is intentionally a new replay identity.  It starts from the frozen v19
foundation plate, replaces only the eight authorized highland bodies, and
uses sparse open crest/spur/saddle/valley paths.  No generated contour atlas
is read.  The fixed CLI accepts only the SHA-bound config and the exact
ordered donor/control graph declared below.

PNG serialization is implemented here rather than delegated to Pillow/zlib.
Every scanline uses filter 0 and the zlib stream consists only of explicitly
emitted DEFLATE stored blocks.  This makes candidate and mask bytes identical
across supported Windows and Linux hosts.
"""

from __future__ import annotations

import argparse
import binascii
import hashlib
import io
import json
import os
import platform
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import cv2
import numpy as np
import PIL
from PIL import Image, UnidentifiedImageError


WIDTH, HEIGHT = 1536, 1024
SHAPE = (HEIGHT, WIDTH, 3)
SCHEMA_VERSION = "1.0.0"
INTERFACE = "sstory-k3-sparse-overhead-relief-v21-replay-v1"
CONFIG_INTERFACE = "sstory-k3-golden-v3-v21-renderer-config-v1"
SEED = "k3-v21-sparse-overhead-relief-golden-v3-v1"
CONFIG_PATH = (
    "world/map-production/controls/style-candidate-k-v3-golden-v3/"
    "renderer-config-v21.json"
)
CONFIG_SHA256 = "0" * 64
REPLAY_CONTRACT_PATH = (
    "world/map-production/controls/style-candidate-k-v3-golden-v3/"
    "v21-replay-contract.json"
)
REPLAY_CONTRACT_SHA256 = (
    "12c8e2e70909ff4567a09f0c068ce2f2977b01744dc8372aa92eacd062d5dbd2"
)
EXPECTED_PIXEL_SHA256 = "0" * 64
EXPECTED_PNG_SHA256 = "0" * 64
EXPECTED_PNG_BYTES = 0
EXPECTED_OUTPUT = {
    "png_sha256": EXPECTED_PNG_SHA256,
    "pixel_sha256": EXPECTED_PIXEL_SHA256,
    "png_bytes": EXPECTED_PNG_BYTES,
    "width": WIDTH,
    "height": HEIGHT,
    "mode": "RGB",
}
EXPECTED_RUNTIME = {
    "python_major_minor": "3.12",
    "opencv": "4.13.0",
    "numpy": "2.3.5",
    "pillow": "12.3.0",
}
EXPECTED_DONORS: tuple[str, ...] = ()
EXPECTED_CONTROLS: tuple[str, ...] = ()
BODY_VALUES = (32, 64, 96, 128, 160, 192, 224, 255)
OCTAVE_FRAMES = (
    ((1.0, 0.0), (0.0, 1.0)),
    ((0.857167300702, 0.515038074910), (-0.515038074910, 0.857167300702)),
    ((0.681998360062, -0.731353701619), (0.731353701619, 0.681998360062)),
    ((0.292371704723, 0.956304755963), (-0.956304755963, 0.292371704723)),
)
POLAR_SPOKES_Q10 = (
    (1024, 0),
    (1004, 200),
    (946, 392),
    (851, 569),
    (724, 724),
    (569, 851),
    (392, 946),
    (200, 1004),
    (0, 1024),
    (-200, 1004),
    (-392, 946),
    (-569, 851),
    (-724, 724),
    (-851, 569),
    (-946, 392),
    (-1004, 200),
    (-1024, 0),
    (-1004, -200),
    (-946, -392),
    (-851, -569),
    (-724, -724),
    (-569, -851),
    (-392, -946),
    (-200, -1004),
    (0, -1024),
    (200, -1004),
    (392, -946),
    (569, -851),
    (724, -724),
    (851, -569),
    (946, -392),
    (1004, -200),
)
EXPECTED_BODY_PIXELS = (12370, 11618, 11142, 15929, 13473, 10915, 9379, 11302)
EXPECTED_BODY_SHA256 = (
    "22411dccde51d280322d6357bf3bfd7103c83316df75d5e153c4d4628e573d94",
    "f528cfa39a95ea1f49c9cefaa35848f7ce7bb9b0939eab325501aabfd04f2f0e",
    "5c7219a4a67dd2be266011791b7ff04e2c19e996088ebd39c61760ab0e9240c9",
    "b3ff40a24077abb168a1490a1b23b8841d024243ec201a3833799bc8c7d38d81",
    "b28ce325cc9a0abffafa3c4d4cf94bb85b468973fbef972cc2f082148f657ccd",
    "6e2dcb974dfb2596c861916719c637df70b5a16095527abcaa9dba4f377f545a",
    "df6ef1892510bf62dc55d46fbe25b365e16d9ec194284245341ebcc712ea0bc9",
    "4b2401163bdad2ced7782380aea31174f4d82e964e3ca43e88d3d05d86d4e7a5",
)
EXPECTED_BODY_UNION_PIXELS = 96128
EXPECTED_BODY_UNION_SHA256 = (
    "ffbb51bcf750c7f68aa3b8cc7a262746b82e956c0d95d5b34e926529162aa2bc"
)
EXPECTED_FOUNDATION_PIXEL_SHA256 = (
    "ad19c90e324833201dcf0b3051b0c6991934ff4bc046578acaa3440addb8f3f5"
)
EXPECTED_BASE_PIXEL_SHA256 = (
    "fcd03439476f9cce8cc3ea93ac43c63a64c0e9f55a2d1a6ab7b36360343ef64c"
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class V20ReplayError(RuntimeError):
    """Raised before an unbound or invalid v21 output can be emitted."""


@dataclass(frozen=True)
class BoundInput:
    role: str
    relative_path: str
    path: Path
    sha256: str
    data: bytes


@dataclass(frozen=True)
class ReplayInputs:
    baseline: np.ndarray
    foundation: np.ndarray
    v19_body_control: np.ndarray
    v20_body_control: np.ndarray
    marks: Mapping[str, Any]
    search_summary: Mapping[str, Any]
    permission: np.ndarray
    protected: np.ndarray
    road_calm: np.ndarray
    bindings: Mapping[str, BoundInput]


@dataclass(frozen=True)
class BuildResult:
    candidate: np.ndarray
    baseline: np.ndarray
    body: np.ndarray
    body_control: np.ndarray
    components: tuple[dict[str, Any], ...]
    identity: Mapping[str, int]
    morphology: Mapping[str, Any]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def array_sha256(values: np.ndarray) -> str:
    return sha256_bytes(np.ascontiguousarray(values).tobytes())


def _adler32(data: bytes) -> int:
    modulus = 65521
    first = 1
    second = 0
    for offset in range(0, len(data), 5552):
        block = data[offset : offset + 5552]
        for value in block:
            first += value
            second += first
        first %= modulus
        second %= modulus
    return (second << 16) | first


def _stored_zlib(data: bytes) -> bytes:
    """Return one canonical zlib stream made only of stored DEFLATE blocks."""

    output = bytearray(b"\x78\x01")
    if not data:
        output.extend(b"\x01\x00\x00\xff\xff")
    else:
        offset = 0
        while offset < len(data):
            block = data[offset : offset + 65535]
            offset += len(block)
            output.append(1 if offset == len(data) else 0)
            size = len(block)
            output.extend(struct.pack("<HH", size, 0xFFFF ^ size))
            output.extend(block)
    output.extend(struct.pack(">I", _adler32(data)))
    return bytes(output)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    if len(kind) != 4:
        raise ValueError("PNG chunk type must be four bytes")
    checksum = binascii.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def _canonical_png(
    rows: list[bytes], *, width: int, height: int, bit_depth: int, color_type: int
) -> bytes:
    if len(rows) != height:
        raise ValueError("canonical PNG row count changed")
    raw = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", _stored_zlib(raw))
        + _png_chunk(b"IEND", b"")
    )


def _mask_png(mask: np.ndarray) -> bytes:
    """Encode a boolean canvas as canonical binary 8-bit grayscale PNG.

    The Golden pixel auditor's frozen mask contract is mode ``L`` with only
    values 0 and 255.  Serialization is still fully manual and independent of
    Pillow/zlib compression bytes.
    """

    if mask.shape != (HEIGHT, WIDTH) or mask.dtype != np.bool_:
        raise V20ReplayError("audit mask must be a native boolean v21 canvas")
    values = mask.astype(np.uint8) * np.uint8(255)
    rows = [np.ascontiguousarray(row).tobytes() for row in values]
    return _canonical_png(
        rows, width=WIDTH, height=HEIGHT, bit_depth=8, color_type=0
    )


def _gray_png(values: np.ndarray) -> bytes:
    if values.shape != (HEIGHT, WIDTH) or values.dtype != np.uint8:
        raise V20ReplayError("gray control must be a native uint8 v21 canvas")
    rows = [np.ascontiguousarray(row).tobytes() for row in values]
    return _canonical_png(
        rows, width=WIDTH, height=HEIGHT, bit_depth=8, color_type=0
    )


def _rgb_png(values: np.ndarray) -> bytes:
    if values.shape != SHAPE or values.dtype != np.uint8:
        raise V20ReplayError("v21 candidate must be native uint8 RGB")
    rows = [np.ascontiguousarray(row).tobytes() for row in values]
    return _canonical_png(
        rows, width=WIDTH, height=HEIGHT, bit_depth=8, color_type=2
    )


def _json(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V20ReplayError(f"cannot decode {label}") from exc
    if not isinstance(value, dict):
        raise V20ReplayError(f"{label} must be a JSON object")
    return value


def _runtime_gate() -> None:
    actual = {
        "python_major_minor": ".".join(platform.python_version_tuple()[:2]),
        "opencv": cv2.__version__,
        "numpy": np.__version__,
        "pillow": PIL.__version__,
    }
    if actual != EXPECTED_RUNTIME or sys.byteorder != "little":
        raise V20ReplayError(
            f"v21 runtime mismatch: expected={EXPECTED_RUNTIME}, actual={actual}"
        )
    cv2.setNumThreads(1)
    cv2.setRNGSeed(0x4538)


def _safe_relative(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise V20ReplayError(f"{label} path must be a nonempty string")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or value != pure.as_posix():
        raise V20ReplayError(f"{label} path must be canonical repository-relative POSIX")
    return value


def _bind(root: Path, record: Any, *, role: str) -> BoundInput:
    if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
        raise V20ReplayError(f"{role} binding keys changed")
    relative = _safe_relative(record["path"], label=role)
    expected = record["sha256"]
    if not isinstance(expected, str) or not SHA256_PATTERN.fullmatch(expected):
        raise V20ReplayError(f"{role} SHA-256 is invalid")
    path = (root / Path(*PurePosixPath(relative).parts)).resolve()
    try:
        path.relative_to(root.resolve())
        data = path.read_bytes()
    except (OSError, ValueError) as exc:
        raise V20ReplayError(f"cannot read bound {role}: {relative}") from exc
    actual = sha256_bytes(data)
    if actual != expected:
        raise V20ReplayError(
            f"{role} SHA-256 mismatch: expected={expected}, actual={actual}"
        )
    return BoundInput(role, relative, path, actual, data)


def _decode_rgb(binding: BoundInput) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(binding.data)) as opened:
            opened.load()
            if opened.mode != "RGB" or opened.size != (WIDTH, HEIGHT):
                raise V20ReplayError(f"{binding.role} must be 1536x1024 RGB")
            return np.asarray(opened, dtype=np.uint8).copy()
    except (OSError, UnidentifiedImageError) as exc:
        raise V20ReplayError(f"cannot decode {binding.role}") from exc


def _decode_gray(binding: BoundInput) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(binding.data)) as opened:
            opened.load()
            if opened.size != (WIDTH, HEIGHT):
                raise V20ReplayError(f"{binding.role} dimensions changed")
            return np.asarray(opened.convert("L"), dtype=np.uint8).copy()
    except (OSError, UnidentifiedImageError) as exc:
        raise V20ReplayError(f"cannot decode {binding.role}") from exc


def _decode_mask(binding: BoundInput) -> np.ndarray:
    return _decode_gray(binding) > 0


def derive_v20_body_control(v19_control: np.ndarray, marks: Mapping[str, Any]) -> np.ndarray:
    if v19_control.shape != (HEIGHT, WIDTH) or v19_control.dtype != np.uint8:
        raise V20ReplayError("v19 body control dimensions/type changed")
    observed = tuple(int(value) for value in np.unique(v19_control))
    if observed != (0, *BODY_VALUES):
        raise V20ReplayError(f"v19 body values changed: {observed}")
    replacement = marks.get("replacement")
    if not isinstance(replacement, dict):
        raise V20ReplayError("marks replacement is missing")
    required = {
        "value",
        "original_pixels",
        "minimum_pixels",
        "polygon_xy",
        "smoothing_sigma",
        "threshold",
    }
    if set(replacement) != required or replacement["value"] != 255:
        raise V20ReplayError("replacement contract keys/value changed")
    original = v19_control == 255
    if int(original.sum()) != int(replacement["original_pixels"]):
        raise V20ReplayError("v19 pill pixel count changed")
    points = np.asarray(replacement["polygon_xy"], dtype=np.int32)
    if points.ndim != 2 or points.shape[0] < 10 or points.shape[1] != 2:
        raise V20ReplayError("replacement polygon is not substantive")
    raster = np.zeros((HEIGHT, WIDTH), np.uint8)
    cv2.fillPoly(raster, [points.reshape(-1, 1, 2)], 255, lineType=cv2.LINE_8)
    softened = cv2.GaussianBlur(
        raster.astype(np.float32),
        (0, 0),
        sigmaX=float(replacement["smoothing_sigma"]),
        sigmaY=float(replacement["smoothing_sigma"]),
        borderType=cv2.BORDER_CONSTANT,
    )
    new_body = softened >= float(replacement["threshold"])
    if int(new_body.sum()) < int(replacement["minimum_pixels"]):
        raise V20ReplayError("replacement body stayed too small")
    result = v19_control.copy()
    result[original] = 0
    if np.any((result != 0) & new_body):
        raise V20ReplayError("replacement body overlaps a retained system")
    result[new_body] = 255
    return result


def _validate_marks(marks: Mapping[str, Any]) -> None:
    if set(marks) != {"schema_version", "interface", "replacement", "styles", "systems"}:
        raise V20ReplayError("marks top-level keys changed")
    if marks["schema_version"] != SCHEMA_VERSION or marks["interface"] != (
        "sstory-k3-sparse-overhead-relief-v21-marks-v1"
    ):
        raise V20ReplayError("marks identity changed")
    styles = marks["styles"]
    if not isinstance(styles, dict) or set(styles) != {
        "lighting",
        "volume",
    }:
        raise V20ReplayError("marks styles changed")
    lighting = styles["lighting"]
    if not isinstance(lighting, dict) or set(lighting) != {"direction_xyz"}:
        raise V20ReplayError("relief lighting contract changed")
    direction = lighting["direction_xyz"]
    if (
        not isinstance(direction, list)
        or len(direction) != 3
        or not all(isinstance(value, (int, float)) for value in direction)
        or not 0.5 <= float(np.linalg.norm(np.asarray(direction, dtype=np.float64))) <= 20.0
    ):
        raise V20ReplayError("relief light direction changed")
    volume = styles["volume"]
    volume_keys = {
        "height_scale",
        "hillshade_exposure",
        "elevation_gain",
        "delta_limit",
        "edge_zero",
        "edge_full",
        "noise_wavelengths",
        "noise_amplitudes",
        "mass_gain",
        "domain_warp",
        "field_quantum",
        "shade_quantum",
    }
    if not isinstance(volume, dict) or set(volume) != volume_keys:
        raise V20ReplayError("volume relief style keys changed")
    if not (
        4.0 <= float(volume["height_scale"]) <= 16.0
        and 4.0 <= float(volume["hillshade_exposure"]) <= 60.0
        and 2.0 <= float(volume["elevation_gain"]) <= 20.0
        and 4.0 <= float(volume["delta_limit"]) <= 12.0
        and 3.0 <= float(volume["edge_zero"]) <= 5.0
        and 9.0 <= float(volume["edge_full"]) <= 12.0
        and volume["noise_wavelengths"] == [72, 41, 23, 13]
        and isinstance(volume["noise_amplitudes"], list)
        and len(volume["noise_amplitudes"]) == 4
        and all(0.01 <= float(value) <= 0.6 for value in volume["noise_amplitudes"])
        and 0.1 <= float(volume["mass_gain"]) <= 0.4
        and 4.0 <= float(volume["domain_warp"]) <= 14.0
        and int(volume["field_quantum"]) == 4096
        and int(volume["shade_quantum"]) == 256
    ):
        raise V20ReplayError("volume relief style bounds changed")
    systems = marks["systems"]
    if not isinstance(systems, list) or len(systems) != 8:
        raise V20ReplayError("marks must describe exactly eight systems")
    signatures: set[tuple[tuple[int, int], ...]] = set()
    stroke_counts = {"crest": 0, "spurs": 0, "valleys": 0}
    saddle_gaps = 0
    anchor_count = 0
    total_length = 0.0
    for index, (system, value) in enumerate(zip(systems, BODY_VALUES, strict=True)):
        required = {
            "body_id",
            "value",
            "base_l_delta",
            "base_a_delta",
            "base_b_delta",
            "crest",
            "spurs",
            "valleys",
            "saddle_gap",
            "relief_scale",
            "noise_salt",
            "noise_major_xy",
            "noise_minor_xy",
            "noise_aspect",
            "mass_anchors",
        }
        if not isinstance(system, dict) or set(system) != required:
            raise V20ReplayError(f"body-{index:02d} mark keys changed")
        if system["body_id"] != f"body-{index:02d}" or system["value"] != value:
            raise V20ReplayError(f"body-{index:02d} identity/order changed")
        if not all(isinstance(system[name], list) for name in ("spurs", "valleys")):
            raise V20ReplayError(f"body-{index:02d} path groups changed")
        if len(system["spurs"]) != 1 or len(system["valleys"]) > 1:
            raise V20ReplayError(f"body-{index:02d} relief density changed")
        gap = system["saddle_gap"]
        if gap is not None:
            if not isinstance(gap, dict) or set(gap) != {"center_fraction", "width"}:
                raise V20ReplayError(f"body-{index:02d} saddle gap changed")
            if not 0.3 <= float(gap["center_fraction"]) <= 0.7 or not 10.0 <= float(gap["width"]) <= 18.0:
                raise V20ReplayError(f"body-{index:02d} saddle gap bounds changed")
            saddle_gaps += 1
        if not 0.85 <= float(system["relief_scale"]) <= 1.15:
            raise V20ReplayError(f"body-{index:02d} relief scale changed")
        if not isinstance(system["noise_salt"], int) or not 1 <= system["noise_salt"] <= 65535:
            raise V20ReplayError(f"body-{index:02d} noise salt changed")
        noise_major = np.asarray(system["noise_major_xy"], dtype=np.float64)
        noise_minor = np.asarray(system["noise_minor_xy"], dtype=np.float64)
        if not (
            noise_major.shape == (2,)
            and noise_minor.shape == (2,)
            and abs(float(np.dot(noise_major, noise_major)) - 1.0) <= 2e-9
            and abs(float(np.dot(noise_minor, noise_minor)) - 1.0) <= 2e-9
            and abs(float(np.dot(noise_major, noise_minor))) <= 2e-9
            and 0.85 <= float(system["noise_aspect"]) <= 1.15
        ):
            raise V20ReplayError(f"body-{index:02d} noise frame changed")
        anchors = system["mass_anchors"]
        expected_anchors = (3, 4, 3, 4, 4, 3, 4, 4)[index]
        if not isinstance(anchors, list) or len(anchors) != expected_anchors:
            raise V20ReplayError(f"body-{index:02d} mass anchor count changed")
        for anchor in anchors:
            if not isinstance(anchor, dict) or set(anchor) != {
                "center_xy",
                "amplitude",
                "radius_long",
                "radius_short",
                "major_xy",
                "minor_xy",
                "source_normalized_xy",
                "source_degrees",
            }:
                raise V20ReplayError(f"body-{index:02d} mass anchor keys changed")
            center = anchor["center_xy"]
            major = np.asarray(anchor["major_xy"], dtype=np.float64)
            minor = np.asarray(anchor["minor_xy"], dtype=np.float64)
            if not (
                isinstance(center, list)
                and len(center) == 2
                and all(isinstance(value, int) for value in center)
                and -0.3 <= float(anchor["amplitude"]) <= 1.0
                and abs(float(anchor["amplitude"])) >= 0.2
                and 35.0 <= float(anchor["radius_short"]) <= float(anchor["radius_long"]) <= 120.0
                and major.shape == (2,)
                and minor.shape == (2,)
                and abs(float(np.dot(major, major)) - 1.0) <= 2e-9
                and abs(float(np.dot(minor, minor)) - 1.0) <= 2e-9
                and abs(float(np.dot(major, minor))) <= 2e-9
                and 0.0 <= float(anchor["source_normalized_xy"][0]) <= 1.0
                and 0.0 <= float(anchor["source_normalized_xy"][1]) <= 1.0
                and -180 <= int(anchor["source_degrees"]) <= 180
            ):
                raise V20ReplayError(f"body-{index:02d} mass anchor bounds changed")
            anchor_count += 1
        stroke_counts["crest"] += 1
        stroke_counts["spurs"] += len(system["spurs"])
        stroke_counts["valleys"] += len(system["valleys"])
        paths = [system["crest"], *system["spurs"], *system["valleys"]]
        for path in paths:
            if not isinstance(path, list) or len(path) < 2:
                raise V20ReplayError(f"body-{index:02d} contains an invalid path")
            normalized = tuple((int(point[0]), int(point[1])) for point in path)
            if normalized[0] == normalized[-1]:
                raise V20ReplayError(f"body-{index:02d} contains a closed contour")
            if normalized in signatures or tuple(reversed(normalized)) in signatures:
                raise V20ReplayError("relief path repetition detected")
            signatures.add(normalized)
            total_length += sum(
                ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
                for start, end in zip(normalized, normalized[1:])
            )
    if stroke_counts != {"crest": 8, "spurs": 8, "valleys": 5}:
        raise V20ReplayError(f"sparse relief stroke inventory changed: {stroke_counts}")
    if (
        saddle_gaps != 3
        or anchor_count != 29
        or len(signatures) != 21
        or not 650.0 <= total_length <= 1000.0
    ):
        raise V20ReplayError(
            "sparse relief budget changed: "
            f"saddle_gaps={saddle_gaps}, mass_anchors={anchor_count}, "
            f"paths={len(signatures)}, "
            f"length={total_length:.3f}"
        )


def _validate_search_summary(
    summary: Mapping[str, Any],
    marks: Mapping[str, Any],
    bindings: Mapping[str, BoundInput],
) -> None:
    required = {
        "schema_version",
        "interface",
        "status",
        "search_script",
        "input_marks_sha256",
        "selection_rule",
        "base_salts",
        "salt_offsets",
        "frame_catalog_order",
        "candidate_count_per_body",
        "criteria",
        "selected",
        "selected_topology_counts",
    }
    if not isinstance(summary, dict) or set(summary) != required:
        raise V20ReplayError("v21 finite-search summary keys changed")
    if (
        summary["schema_version"] != "1.0.0"
        or summary["interface"]
        != "sstory-k3-v21-relief-finite-search-summary-v1"
        or summary["status"] != "complete"
        or summary["selection_rule"]
        != "first passing candidate in salt_offset then cyclic frame order"
        or summary["base_salts"] != [101, 211, 307, 401, 503, 601, 701, 809]
        or summary["salt_offsets"]
        != [0, 37, 79, 131, 197, 269, 353, 449, 557, 677, 809, 953]
        or summary["frame_catalog_order"]
        != [f"frame-{index:02d}" for index in range(8)]
        or summary["candidate_count_per_body"] != 96
        or not isinstance(summary["input_marks_sha256"], str)
        or not SHA256_PATTERN.fullmatch(summary["input_marks_sha256"])
    ):
        raise V20ReplayError("v21 finite-search summary identity changed")
    script = summary["search_script"]
    script_binding = bindings["search_script"]
    if script != {
        "path": script_binding.relative_path,
        "sha256": script_binding.sha256,
    }:
        raise V20ReplayError("v21 finite-search script binding changed")
    expected_criteria = {
        "closed_crater_count_max": 0,
        "partial_dark_arc_count_max": 0,
        "near_vertical_residual_count_max": 0,
        "near_vertical_severe_count_max": 0,
        "relief_orientation_coherence_max": 0.4,
        "maximum_relative_jacobian_norm_max": 0.35,
        "minimum_mapping_determinant_min": 0.5,
        "maximum_mapping_determinant_max": 1.75,
    }
    if summary["criteria"] != expected_criteria or summary["selected_topology_counts"] != {
        "closed_crater_count": 0,
        "partial_dark_arc_count": 0,
        "near_vertical_residual_count": 0,
        "near_vertical_severe_count": 0,
    }:
        raise V20ReplayError("v21 finite-search diagnostics contract changed")
    selected = summary["selected"]
    systems = marks["systems"]
    if not isinstance(selected, list) or len(selected) != len(systems):
        raise V20ReplayError("v21 finite-search selection count changed")
    selected_keys = {
        "body_id",
        "evaluated_candidates",
        "salt",
        "frame_id",
        "noise_major_xy",
        "noise_minor_xy",
        "noise_aspect",
        "relief_minimum_l",
        "relief_maximum_l",
        "relief_orientation_coherence",
        "maximum_relative_jacobian_norm",
        "minimum_mapping_determinant",
        "maximum_mapping_determinant",
    }
    for index, (record, system) in enumerate(zip(selected, systems, strict=True)):
        if not isinstance(record, dict) or set(record) != selected_keys:
            raise V20ReplayError(f"body-{index:02d} finite-search record changed")
        if (
            record["body_id"] != system["body_id"]
            or record["salt"] != system["noise_salt"]
            or record["noise_major_xy"] != system["noise_major_xy"]
            or record["noise_minor_xy"] != system["noise_minor_xy"]
            or record["noise_aspect"] != system["noise_aspect"]
            or not 1 <= int(record["evaluated_candidates"]) <= 96
            or not 0.0 <= float(record["relief_orientation_coherence"]) <= 0.4
            or not 0.0
            <= float(record["maximum_relative_jacobian_norm"])
            <= 0.35
            or not 0.5 <= float(record["minimum_mapping_determinant"])
            or not float(record["maximum_mapping_determinant"]) <= 1.75
            or not float(record["relief_minimum_l"]) < 0.0
            or not float(record["relief_maximum_l"]) > 0.0
        ):
            raise V20ReplayError(f"body-{index:02d} finite-search selection changed")


def _decode_components(control: np.ndarray) -> tuple[list[np.ndarray], np.ndarray, tuple[dict[str, Any], ...]]:
    observed = tuple(int(value) for value in np.unique(control))
    if observed != (0, *BODY_VALUES):
        raise V20ReplayError(f"v21 body values changed: {observed}")
    body_masks: list[np.ndarray] = []
    union = np.zeros((HEIGHT, WIDTH), bool)
    records: list[dict[str, Any]] = []
    for index, value in enumerate(BODY_VALUES):
        body = control == value
        pixels = int(body.sum())
        digest = array_sha256(body.astype(np.uint8))
        if EXPECTED_BODY_PIXELS and (
            pixels != EXPECTED_BODY_PIXELS[index] or digest != EXPECTED_BODY_SHA256[index]
        ):
            raise V20ReplayError(f"body-{index:02d} frozen geometry changed")
        if np.any(union & body):
            raise V20ReplayError(f"body-{index:02d} overlaps another body")
        union |= body
        y, x = np.nonzero(body)
        records.append(
            {
                "body_id": f"body-{index:02d}",
                "value": value,
                "pixels": pixels,
                "sha256_uint8": digest,
                "bbox_xyxy": [int(x.min()), int(y.min()), int(x.max()) + 1, int(y.max()) + 1],
            }
        )
        body_masks.append(body)
    component_total, _ = cv2.connectedComponents(
        union.astype(np.uint8), connectivity=8, ltype=cv2.CV_32S
    )
    if component_total - 1 != 8:
        raise V20ReplayError("v21 bodies touch or fragment; expected eight components")
    union_pixels = int(union.sum())
    union_digest = array_sha256(union.astype(np.uint8))
    if EXPECTED_BODY_UNION_PIXELS and (
        union_pixels != EXPECTED_BODY_UNION_PIXELS
        or union_digest != EXPECTED_BODY_UNION_SHA256
    ):
        raise V20ReplayError("v21 body union changed")
    return body_masks, union, tuple(records)


def _smooth_path(path: Any) -> np.ndarray:
    points = np.asarray(path, dtype=np.float32)
    if points.ndim != 2 or points.shape[0] < 2 or points.shape[1] != 2:
        raise V20ReplayError("relief path control points changed")
    for _ in range(3):
        refined = [points[0]]
        for start, end in zip(points, points[1:]):
            refined.append(start * np.float32(0.75) + end * np.float32(0.25))
            refined.append(start * np.float32(0.25) + end * np.float32(0.75))
        refined.append(points[-1])
        points = np.asarray(refined, dtype=np.float32)
    sampled = [points[0]]
    for start, end in zip(points, points[1:]):
        distance = float(np.linalg.norm(end - start))
        steps = max(1, int(np.ceil(distance)))
        for step in range(1, steps + 1):
            sampled.append(start + (end - start) * np.float32(step / steps))
    return np.asarray(sampled, dtype=np.float32)


def _path_frame(
    path: Any, fraction: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    points = _smooth_path(path).astype(np.float64)
    vectors = points[1:] - points[:-1]
    lengths = np.sqrt(np.einsum("si,si->s", vectors, vectors))
    if np.any(lengths <= 1e-8):
        raise V20ReplayError("volume path contains a degenerate segment")
    cumulative = np.concatenate(
        (np.zeros(1, dtype=np.float64), np.cumsum(lengths, dtype=np.float64))
    )
    total = float(cumulative[-1])
    target = float(np.clip(fraction, 0.0, 1.0)) * total
    index = int(np.searchsorted(cumulative, target, side="right") - 1)
    index = max(0, min(index, len(vectors) - 1))
    local = (target - float(cumulative[index])) / float(lengths[index])
    center = points[index] + vectors[index] * local
    tangent = vectors[index] / lengths[index]
    normal = np.asarray((-tangent[1], tangent[0]), dtype=np.float64)
    return center, tangent, normal, total


def _add_anisotropic_lobe(
    height: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    *,
    center: np.ndarray,
    tangent: np.ndarray,
    sigma_parallel: float,
    sigma_perpendicular: float,
    amplitude: float,
) -> None:
    delta_x = grid_x - float(center[0])
    delta_y = grid_y - float(center[1])
    parallel = delta_x * float(tangent[0]) + delta_y * float(tangent[1])
    perpendicular = -delta_x * float(tangent[1]) + delta_y * float(tangent[0])
    exponent = -0.5 * (
        (parallel / float(sigma_parallel)) ** 2
        + (perpendicular / float(sigma_perpendicular)) ** 2
    )
    height += float(amplitude) * np.exp(exponent)


def _finite_gradient(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    gradient_x = np.empty_like(values, dtype=np.float64)
    gradient_y = np.empty_like(values, dtype=np.float64)
    gradient_x[:, 1:-1] = (values[:, 2:] - values[:, :-2]) * 0.5
    gradient_x[:, 0] = values[:, 1] - values[:, 0]
    gradient_x[:, -1] = values[:, -1] - values[:, -2]
    gradient_y[1:-1, :] = (values[2:, :] - values[:-2, :]) * 0.5
    gradient_y[0, :] = values[1, :] - values[0, :]
    gradient_y[-1, :] = values[-1, :] - values[-2, :]
    return gradient_x, gradient_y


def _quintic(values: np.ndarray) -> np.ndarray:
    return values * values * values * (
        values * (values * 6.0 - 15.0) + 10.0
    )


def _hash_lattice(
    lattice_x: np.ndarray, lattice_y: np.ndarray, salt: int
) -> np.ndarray:
    values = (
        lattice_x.astype(np.int64) * np.int64(374761393)
        + lattice_y.astype(np.int64) * np.int64(668265263)
        + np.int64(salt) * np.int64(1442695041)
    ) & np.int64(0xFFFFFFFF)
    values = ((values ^ (values >> 13)) * np.int64(1274126177)) & np.int64(
        0xFFFFFFFF
    )
    values = values ^ (values >> 16)
    return values.astype(np.float64) / 2147483647.5 - 1.0


def _value_noise(
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    *,
    wavelength: int,
    salt: int,
) -> np.ndarray:
    scaled_x = grid_x / float(wavelength)
    scaled_y = grid_y / float(wavelength)
    base_x = np.floor(scaled_x).astype(np.int64)
    base_y = np.floor(scaled_y).astype(np.int64)
    weight_x = _quintic(scaled_x - base_x)
    weight_y = _quintic(scaled_y - base_y)
    value_00 = _hash_lattice(base_x, base_y, salt)
    value_10 = _hash_lattice(base_x + 1, base_y, salt)
    value_01 = _hash_lattice(base_x, base_y + 1, salt)
    value_11 = _hash_lattice(base_x + 1, base_y + 1, salt)
    top = value_00 + (value_10 - value_00) * weight_x
    bottom = value_01 + (value_11 - value_01) * weight_x
    return top + (bottom - top) * weight_y


def _wendland_mass(
    grid_x: np.ndarray, grid_y: np.ndarray, anchor: Mapping[str, Any]
) -> np.ndarray:
    center_x, center_y = (float(value) for value in anchor["center_xy"])
    major = np.asarray(anchor["major_xy"], dtype=np.float64)
    minor = np.asarray(anchor["minor_xy"], dtype=np.float64)
    delta_x = grid_x - center_x
    delta_y = grid_y - center_y
    along = delta_x * major[0] + delta_y * major[1]
    across = delta_x * minor[0] + delta_y * minor[1]
    radius = np.sqrt(
        (along / float(anchor["radius_long"])) ** 2
        + (across / float(anchor["radius_short"])) ** 2
    )
    support = np.maximum(1.0 - radius, 0.0)
    return float(anchor["amplitude"]) * support**4 * (4.0 * radius + 1.0)


def _relief_topology_diagnostics(
    relief: np.ndarray, local_body: np.ndarray, distance_inside: np.ndarray
) -> Mapping[str, Any]:
    relief_q = np.rint(relief * 256.0).astype(np.int32)
    core = local_body & (distance_inside >= 12.0)
    relief_gx, relief_gy = _finite_gradient(relief)
    relief_gradient = np.hypot(relief_gx, relief_gy)
    oriented = core & (relief_gradient >= 0.2)
    if np.any(oriented):
        j_xx = float(np.mean(relief_gx[oriented] ** 2))
        j_yy = float(np.mean(relief_gy[oriented] ** 2))
        j_xy = float(np.mean(relief_gx[oriented] * relief_gy[oriented]))
        orientation_coherence = (
            np.sqrt((j_xx - j_yy) ** 2 + 4.0 * j_xy * j_xy)
            / max(j_xx + j_yy, 1e-12)
        )
    else:
        orientation_coherence = 0.0
    kernel_3 = np.ones((3, 3), dtype=np.uint8)
    core_boundary = core & (
        cv2.dilate((~core).astype(np.uint8), kernel_3, iterations=1) > 0
    )
    crater_count = 0
    crater_records: list[dict[str, Any]] = []
    partial_arc_count = 0
    partial_arc_records: list[dict[str, Any]] = []
    for threshold_q in (-256, -512, -768):
        dark = core & (relief_q <= threshold_q)
        closed_dark = (
            cv2.morphologyEx(
                dark.astype(np.uint8), cv2.MORPH_CLOSE, kernel_3, iterations=1
            )
            > 0
        ) & core
        component_total, labels = cv2.connectedComponents(
            (core & ~closed_dark).astype(np.uint8),
            connectivity=8,
            ltype=cv2.CV_32S,
        )
        for component_id in range(1, component_total):
            hole = labels == component_id
            area = int(np.count_nonzero(hole))
            if not 32 <= area <= 1024 or np.any(hole & core_boundary):
                continue
            immediate = (
                cv2.dilate(hole.astype(np.uint8), kernel_3, iterations=1) > 0
            ) & core & ~hole
            immediate_pixels = int(np.count_nonzero(immediate))
            if immediate_pixels == 0:
                continue
            dark_contact = int(np.count_nonzero(immediate & closed_dark))
            if 10 * dark_contact < 7 * immediate_pixels:
                continue
            ring = (
                cv2.dilate(hole.astype(np.uint8), kernel_3, iterations=4) > 0
            ) & closed_dark & ~hole
            ring_pixels = int(np.count_nonzero(ring))
            if ring_pixels == 0:
                continue
            hole_sum = int(np.sum(relief_q[hole], dtype=np.int64))
            ring_sum = int(np.sum(relief_q[ring], dtype=np.int64))
            if hole_sum * ring_pixels - ring_sum * area < 768 * area * ring_pixels:
                continue
            if int(np.percentile(relief_q[hole], 90, method="lower")) < threshold_q + 256:
                continue
            crater_count += 1
            crater_records.append(
                {
                    "threshold_q": threshold_q,
                    "area": area,
                    "dark_contact_numerator": dark_contact,
                    "dark_contact_denominator": immediate_pixels,
                }
            )

        _, dark_labels = cv2.connectedComponents(
            closed_dark.astype(np.uint8), connectivity=8, ltype=cv2.CV_32S
        )
        bright = core & (relief_q >= threshold_q + 256)
        bright_total, bright_labels = cv2.connectedComponents(
            bright.astype(np.uint8), connectivity=8, ltype=cv2.CV_32S
        )
        for bright_id in range(1, bright_total):
            seed_y, seed_x = np.nonzero(bright_labels == bright_id)
            seed_area = len(seed_x)
            if not 16 <= seed_area <= 1024:
                continue
            center_x = int((int(np.sum(seed_x)) + seed_area // 2) // seed_area)
            center_y = int((int(np.sum(seed_y)) + seed_area // 2) // seed_area)
            seed_mean_q = int(
                np.sum(relief_q[bright_labels == bright_id], dtype=np.int64)
                // seed_area
            )
            for radius in (8, 10, 12, 15, 18, 22, 26, 30, 36):
                occupied: list[bool] = []
                sampled_values: list[int] = []
                for unit_x, unit_y in POLAR_SPOKES_Q10:
                    labels_at_sector: list[int] = []
                    values_at_sector: list[int] = []
                    valid_sector = True
                    for sample_radius in (radius - 2, radius, radius + 2):
                        sample_x = center_x + round(sample_radius * unit_x / 1024)
                        sample_y = center_y + round(sample_radius * unit_y / 1024)
                        if (
                            not 0 <= sample_x < local_body.shape[1]
                            or not 0 <= sample_y < local_body.shape[0]
                            or not core[sample_y, sample_x]
                        ):
                            valid_sector = False
                            break
                        labels_at_sector.append(int(dark_labels[sample_y, sample_x]))
                        values_at_sector.append(int(relief_q[sample_y, sample_x]))
                    qualifying_label = 0
                    if valid_sector:
                        for label in sorted(set(labels_at_sector)):
                            if label > 0 and labels_at_sector.count(label) >= 2:
                                qualifying_label = label
                                break
                    occupied.append(qualifying_label > 0)
                    if qualifying_label > 0:
                        sampled_values.extend(
                            value
                            for label, value in zip(
                                labels_at_sector, values_at_sector, strict=True
                            )
                            if label == qualifying_label
                        )
                coverage = sum(occupied)
                doubled = occupied + occupied
                longest_run = 0
                current_run = 0
                for value in doubled:
                    current_run = current_run + 1 if value else 0
                    longest_run = min(32, max(longest_run, current_run))
                if (
                    coverage < 24
                    or longest_run < 20
                    or not sampled_values
                    or seed_mean_q
                    - int(sum(sampled_values) // len(sampled_values))
                    < 768
                ):
                    continue
                partial_arc_count += 1
                partial_arc_records.append(
                    {
                        "threshold_q": threshold_q,
                        "radius": radius,
                        "coverage": coverage,
                        "longest_run": longest_run,
                        "seed_area": seed_area,
                    }
                )

    vertical_count = 0
    vertical_severe_count = 0
    vertical_max_span = 0
    vertical_kernel = np.ones((3, 1), dtype=np.uint8)
    for polarity in (-1, 1):
        visible = core & (polarity * relief_q >= 512)
        visible = cv2.morphologyEx(
            visible.astype(np.uint8),
            cv2.MORPH_CLOSE,
            vertical_kernel,
            iterations=1,
        )
        component_total, labels = cv2.connectedComponents(
            visible,
            connectivity=8,
            ltype=cv2.CV_32S,
        )
        for component_id in range(1, component_total):
            component_y, component_x = np.nonzero(labels == component_id)
            area = len(component_x)
            if area < 18:
                continue
            y_span = int(component_y.max() - component_y.min() + 1)
            if y_span < 24:
                continue
            sum_x = int(np.sum(component_x, dtype=np.int64))
            sum_y = int(np.sum(component_y, dtype=np.int64))
            centered_x = area * component_x.astype(np.int64) - sum_x
            centered_y = area * component_y.astype(np.int64) - sum_y
            m_xx = int(np.sum(centered_x * centered_x, dtype=np.int64))
            m_yy = int(np.sum(centered_y * centered_y, dtype=np.int64))
            m_xy = int(np.sum(centered_x * centered_y, dtype=np.int64))
            difference = m_yy - m_xx
            if difference <= 0 or 7 * abs(2 * m_xy) > 4 * difference:
                continue
            anisotropy_left = 25 * (
                difference * difference + 4 * m_xy * m_xy
            )
            anisotropy_right = 9 * (m_xx + m_yy) * (m_xx + m_yy)
            if anisotropy_left < anisotropy_right:
                continue
            vertical_count += 1
            vertical_max_span = max(vertical_max_span, y_span)
            if y_span >= 40:
                vertical_severe_count += 1
    return {
        "relief_orientation_coherence": round(float(orientation_coherence), 6),
        "closed_crater_count": crater_count,
        "closed_craters": crater_records,
        "partial_dark_arc_count": partial_arc_count,
        "partial_dark_arcs": partial_arc_records,
        "near_vertical_residual_count": vertical_count,
        "near_vertical_severe_count": vertical_severe_count,
        "near_vertical_max_span": vertical_max_span,
    }


def _apply_volume_relief(
    lab: np.ndarray,
    body: np.ndarray,
    system: Mapping[str, Any],
    styles: Mapping[str, Any],
    *,
    relief_gain: float = 1.0,
) -> Mapping[str, Any]:
    ys, xs = np.nonzero(body)
    if len(xs) < 100:
        raise V20ReplayError("volume body became empty")
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    width, height_pixels = x1 - x0, y1 - y0
    diagonal = float(np.hypot(width, height_pixels))
    local_body = body[y0:y1, x0:x1]
    grid_y, grid_x = np.mgrid[y0:y1, x0:x1]
    grid_x = grid_x.astype(np.float64)
    grid_y = grid_y.astype(np.float64)
    distance_inside = cv2.distanceTransform(
        local_body.astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE
    ).astype(np.float64)

    anchors = system["mass_anchors"]
    anchor_centers: list[tuple[int, int]] = []
    mass_context = np.zeros(local_body.shape, dtype=np.float64)
    for anchor in anchors:
        center_x, center_y = (int(value) for value in anchor["center_xy"])
        local_x, local_y = center_x - x0, center_y - y0
        if (
            not 0 <= local_x < width
            or not 0 <= local_y < height_pixels
            or not local_body[local_y, local_x]
            or distance_inside[local_y, local_x] < 12.0
        ):
            raise V20ReplayError(f"{system['body_id']} mass anchor escaped erosion")
        if any(
            np.hypot(center_x - prior_x, center_y - prior_y) < 0.18 * diagonal
            for prior_x, prior_y in anchor_centers
        ):
            raise V20ReplayError(f"{system['body_id']} mass anchors collapsed")
        anchor_centers.append((center_x, center_y))
        mass_context += _wendland_mass(grid_x, grid_y, anchor)

    volume = styles["volume"]
    center_x = (x0 + x1 - 1) * 0.5
    center_y = (y0 + y1 - 1) * 0.5
    delta_x = grid_x - center_x
    delta_y = grid_y - center_y
    noise_major = np.asarray(system["noise_major_xy"], dtype=np.float64)
    noise_minor = np.asarray(system["noise_minor_xy"], dtype=np.float64)
    noise_x = delta_x * noise_major[0] + delta_y * noise_major[1]
    noise_y = (
        delta_x * noise_minor[0] + delta_y * noise_minor[1]
    ) * float(system["noise_aspect"])
    salt = int(system["noise_salt"])
    warp_scale = float(volume["domain_warp"])
    warp_delta_x = warp_scale * _value_noise(
        noise_x, noise_y, wavelength=72, salt=salt + 4001
    )
    warp_delta_y = warp_scale * _value_noise(
        noise_x, noise_y, wavelength=72, salt=salt + 8009
    )
    warped_x = noise_x + warp_delta_x
    warped_y = noise_y + warp_delta_y
    warp_x_dx, warp_x_dy = _finite_gradient(warp_delta_x)
    warp_y_dx, warp_y_dy = _finite_gradient(warp_delta_y)
    frame_matrix = np.asarray(
        [
            noise_major,
            noise_minor * float(system["noise_aspect"]),
        ],
        dtype=np.float64,
    )
    inverse_frame = np.linalg.inv(frame_matrix)
    relative_00 = warp_x_dx * inverse_frame[0, 0] + warp_x_dy * inverse_frame[1, 0]
    relative_01 = warp_x_dx * inverse_frame[0, 1] + warp_x_dy * inverse_frame[1, 1]
    relative_10 = warp_y_dx * inverse_frame[0, 0] + warp_y_dy * inverse_frame[1, 0]
    relative_11 = warp_y_dx * inverse_frame[0, 1] + warp_y_dy * inverse_frame[1, 1]
    squared_sum = (
        relative_00 * relative_00
        + relative_01 * relative_01
        + relative_10 * relative_10
        + relative_11 * relative_11
    )
    relative_det = relative_00 * relative_11 - relative_01 * relative_10
    discriminant = np.maximum(squared_sum * squared_sum - 4.0 * relative_det**2, 0.0)
    warp_norm = np.sqrt(0.5 * (squared_sum + np.sqrt(discriminant)))
    warp_mapping_det = (
        (1.0 + relative_00) * (1.0 + relative_11)
        - relative_01 * relative_10
    )
    warp_metrics = {
        "maximum_relative_jacobian_norm": round(float(warp_norm[local_body].max()), 6),
        "minimum_mapping_determinant": round(float(warp_mapping_det[local_body].min()), 6),
        "maximum_mapping_determinant": round(float(warp_mapping_det[local_body].max()), 6),
    }
    shade_terrain = np.zeros(local_body.shape, dtype=np.float64)
    for band_index, (wavelength, amplitude, frame) in enumerate(
        zip(
            volume["noise_wavelengths"],
            volume["noise_amplitudes"],
            OCTAVE_FRAMES,
            strict=True,
        )
    ):
        octave_major = np.asarray(frame[0], dtype=np.float64)
        octave_minor = np.asarray(frame[1], dtype=np.float64)
        octave_x = warped_x * octave_major[0] + warped_y * octave_major[1]
        octave_y = warped_x * octave_minor[0] + warped_y * octave_minor[1]
        shade_terrain += float(amplitude) * _value_noise(
            octave_x,
            octave_y,
            wavelength=int(wavelength),
            salt=salt + band_index * 997,
        )
    field_quantum = float(volume["field_quantum"])
    shade_terrain = np.rint(shade_terrain * field_quantum) / field_quantum
    terrain = (
        float(volume["mass_gain"]) * mass_context + shade_terrain
    )
    terrain = np.rint(terrain * field_quantum) / field_quantum

    body_values = terrain[local_body]
    ordered = np.sort(body_values)
    p10 = float(ordered[int((len(ordered) - 1) * 0.10)])
    p90 = float(ordered[int((len(ordered) - 1) * 0.90)])
    span = p90 - p10
    if span < 0.08:
        raise V20ReplayError(f"{system['body_id']} terrain span collapsed")
    midpoint = (p10 + p90) * 0.5
    normalized_elevation = (terrain - midpoint) / span

    shade_values = shade_terrain[local_body]
    shade_ordered = np.sort(shade_values)
    shade_p10 = float(shade_ordered[int((len(shade_ordered) - 1) * 0.10)])
    shade_p90 = float(shade_ordered[int((len(shade_ordered) - 1) * 0.90)])
    shade_span = shade_p90 - shade_p10
    if shade_span < 0.08:
        raise V20ReplayError(f"{system['body_id']} hillshade terrain collapsed")
    normalized_shade = (
        shade_terrain - (shade_p10 + shade_p90) * 0.5
    ) / shade_span

    gradient_x, gradient_y = _finite_gradient(normalized_shade)
    light = np.asarray(styles["lighting"]["direction_xyz"], dtype=np.float64)
    light /= float(np.linalg.norm(light))
    height_scale = float(volume["height_scale"])
    normal_x = -gradient_x * height_scale
    normal_y = -gradient_y * height_scale
    normal_z = np.ones_like(terrain, dtype=np.float64)
    normal_length = np.sqrt(
        normal_x * normal_x + normal_y * normal_y + normal_z * normal_z
    )
    lambert = (
        normal_x * light[0] + normal_y * light[1] + normal_z * light[2]
    ) / normal_length
    hillshade = (
        (lambert - light[2])
        * float(volume["hillshade_exposure"])
        * float(system["relief_scale"])
    )
    elevation = float(volume["elevation_gain"]) * np.tanh(normalized_elevation)
    combined = elevation + hillshade
    limit = float(volume["delta_limit"])
    relief = limit * np.tanh(combined / limit)
    edge_weight = _smoothstep(
        (distance_inside - float(volume["edge_zero"]))
        / (float(volume["edge_full"]) - float(volume["edge_zero"]))
    )
    relief *= edge_weight
    shade_quantum = float(volume["shade_quantum"])
    relief = np.rint(relief * shade_quantum) / shade_quantum
    if relief_gain != 1.0:
        if not np.isfinite(relief_gain) or not 1.0 <= relief_gain <= 1.25:
            raise V20ReplayError("experimental signed-relief gain escaped its bound")
        relief = np.rint(relief * relief_gain * shade_quantum) / shade_quantum

    local_lab = lab[y0:y1, x0:x1]
    for channel, key in enumerate(("base_l_delta", "base_a_delta", "base_b_delta")):
        delta = float(system[key]) * edge_weight
        local_lab[..., channel][local_body] += delta[local_body].astype(np.float32)
    local_lab[..., 0][local_body] += relief[local_body].astype(np.float32)

    body_y, body_x = np.nonzero(local_body)
    minimum_index = int(np.argmin(body_values))
    maximum_index = int(np.argmax(body_values))
    minimum_xy = (int(body_x[minimum_index] + x0), int(body_y[minimum_index] + y0))
    maximum_xy = (int(body_x[maximum_index] + x0), int(body_y[maximum_index] + y0))
    extrema_separation = float(
        np.hypot(maximum_xy[0] - minimum_xy[0], maximum_xy[1] - minimum_xy[1])
    )
    if extrema_separation < 0.10 * diagonal:
        raise V20ReplayError(f"{system['body_id']} terrain extrema collapsed")
    active = np.abs(relief[local_body]) >= 0.25
    if int(np.count_nonzero(active)) < 200:
        raise V20ReplayError(f"{system['body_id']} terrain relief became empty")
    topology = _relief_topology_diagnostics(relief, local_body, distance_inside)
    return {
        "mass_anchors": len(anchors),
        "terrain_p10": round(p10, 6),
        "terrain_p90": round(p90, 6),
        "terrain_p10_p90_span": round(span, 6),
        "hillshade_terrain_p10": round(shade_p10, 6),
        "hillshade_terrain_p90": round(shade_p90, 6),
        "hillshade_terrain_p10_p90_span": round(shade_span, 6),
        "terrain_minimum_xy": list(minimum_xy),
        "terrain_maximum_xy": list(maximum_xy),
        "terrain_extrema_separation": round(extrema_separation, 6),
        "elevation_minimum_l": round(float(elevation[local_body].min()), 6),
        "elevation_maximum_l": round(float(elevation[local_body].max()), 6),
        "hillshade_minimum_l": round(float(hillshade[local_body].min()), 6),
        "hillshade_maximum_l": round(float(hillshade[local_body].max()), 6),
        "relief_minimum_l": round(float(relief[local_body].min()), 6),
        "relief_maximum_l": round(float(relief[local_body].max()), 6),
        "edge_zero_pixels": int(
            np.count_nonzero(local_body & (distance_inside <= float(volume["edge_zero"])))
        ),
        "relief_pixels_ge_0_25": int(np.count_nonzero(active)),
        "topology": topology,
        "domain_warp": warp_metrics,
    }


def _stroke_mask(
    path: Any, width: int, gap: Mapping[str, Any] | None = None
) -> tuple[np.ndarray, np.ndarray, float]:
    points = _smooth_path(path)
    segment_lengths = np.linalg.norm(points[1:] - points[:-1], axis=1)
    cumulative = np.concatenate(
        (np.zeros(1, dtype=np.float32), np.cumsum(segment_lengths, dtype=np.float32))
    )
    total = float(cumulative[-1])
    if total < 2.0:
        raise V20ReplayError("relief path became too short")
    gap_start = gap_end = -1.0
    if gap is not None:
        center = total * float(gap["center_fraction"])
        gap_start = center - float(gap["width"]) / 2.0
        gap_end = center + float(gap["width"]) / 2.0
    raster = np.zeros((HEIGHT, WIDTH), np.uint8)
    for index, (start, end) in enumerate(zip(points, points[1:])):
        midpoint = float((cumulative[index] + cumulative[index + 1]) / 2.0)
        if gap_start <= midpoint <= gap_end:
            continue
        p0 = tuple(int(value) for value in np.rint(start))
        p1 = tuple(int(value) for value in np.rint(end))
        cv2.line(raster, p0, p1, 255, width, lineType=cv2.LINE_8)
    return raster.astype(np.float32) / np.float32(255.0), points, total


def _smoothstep(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, 0.0, 1.0)
    return clipped * clipped * (3.0 - 2.0 * clipped)


def _path_body_geometry(
    body: np.ndarray,
    path: Any,
    light_direction_xy: Any,
    *,
    start_taper: float,
    end_taper: float,
    gap: Mapping[str, Any] | None,
    gap_taper: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    """Return deterministic signed distance and along-path taper on body pixels.

    Positive distance always points toward one repository-bound global light
    direction, independent of control-point ordering.  Work is cropped to the
    body coordinates and evaluated in fixed-size chunks to avoid large,
    platform-dependent raster intermediates.
    """

    points = _smooth_path(path).astype(np.float64)
    starts = points[:-1]
    vectors = points[1:] - points[:-1]
    lengths = np.sqrt(np.einsum("si,si->s", vectors, vectors))
    if np.any(lengths <= 1e-8):
        raise V20ReplayError("relief path contains a degenerate segment")
    length_squared = lengths * lengths
    cumulative = np.concatenate(
        (np.zeros(1, dtype=np.float64), np.cumsum(lengths, dtype=np.float64))
    )
    total = float(cumulative[-1])
    if total < 2.0:
        raise V20ReplayError("relief path became too short")

    light = np.asarray(light_direction_xy, dtype=np.float64)
    light_norm = float(np.linalg.norm(light))
    if light.shape != (2,) or light_norm <= 1e-8:
        raise V20ReplayError("relief light direction is degenerate")
    light /= light_norm
    overall = points[-1] - points[0]
    overall_length = float(np.linalg.norm(overall))
    if overall_length <= 1e-8:
        raise V20ReplayError("relief path endpoint direction is degenerate")
    path_normal = np.asarray((-overall[1], overall[0]), dtype=np.float64)
    path_normal /= overall_length
    orientation = 1.0 if float(np.dot(path_normal, light)) >= 0.0 else -1.0

    ys, xs = np.nonzero(body)
    coordinates = np.column_stack((xs, ys)).astype(np.float64)
    oriented_distance = np.empty(len(coordinates), dtype=np.float64)
    along = np.empty(len(coordinates), dtype=np.float64)
    for offset in range(0, len(coordinates), 2048):
        stop = min(offset + 2048, len(coordinates))
        chunk = coordinates[offset:stop]
        relative = chunk[:, None, :] - starts[None, :, :]
        projection = np.einsum("nsi,si->ns", relative, vectors) / length_squared[None, :]
        projection = np.clip(projection, 0.0, 1.0)
        nearest = starts[None, :, :] + projection[..., None] * vectors[None, :, :]
        difference = chunk[:, None, :] - nearest
        squared_distance = np.einsum("nsi,nsi->ns", difference, difference)
        nearest_segment = np.argmin(squared_distance, axis=1)
        row = np.arange(stop - offset)
        chosen_projection = projection[row, nearest_segment]
        chosen_difference = difference[row, nearest_segment]
        chosen_vector = vectors[nearest_segment]
        chosen_length = lengths[nearest_segment]
        signed = (
            chosen_vector[:, 0] * chosen_difference[:, 1]
            - chosen_vector[:, 1] * chosen_difference[:, 0]
        ) / chosen_length
        oriented_distance[offset:stop] = signed * orientation
        along[offset:stop] = (
            cumulative[nearest_segment]
            + chosen_projection * chosen_length
        )

    weight = np.ones(len(coordinates), dtype=np.float64)
    if start_taper > 0.0:
        weight *= _smoothstep(along / float(start_taper))
    if end_taper > 0.0:
        weight *= _smoothstep((total - along) / float(end_taper))
    if gap is not None:
        if gap_taper <= 0.0:
            raise V20ReplayError("saddle gap requires a positive smooth taper")
        center = total * float(gap["center_fraction"])
        outside_gap = np.abs(along - center) - float(gap["width"]) / 2.0
        weight *= _smoothstep(outside_gap / float(gap_taper))
    return ys, xs, oriented_distance, weight, total


def _quantized_field(values: np.ndarray) -> np.ndarray:
    """Quantize LAB deltas so one-libm-ulp differences cannot alter output."""

    return np.rint(values * 256.0) / 256.0


def _apply_signed_path_field(
    lab: np.ndarray,
    body: np.ndarray,
    path: Any,
    style: Mapping[str, Any],
    light_direction_xy: Any,
    *,
    scale: float,
    gap: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    ys, xs, distance, weight, total = _path_body_geometry(
        body,
        path,
        light_direction_xy,
        start_taper=float(style["start_taper"]),
        end_taper=float(style["end_taper"]),
        gap=gap,
        gap_taper=float(style["gap_taper"]),
    )
    sigma = float(style["sigma"])
    normalized = distance / sigma
    delta = (
        float(style["amplitude_l"])
        * normalized
        * np.exp(-0.5 * normalized * normalized)
        * weight
        * float(scale)
    )
    delta[np.abs(normalized) > 3.5] = 0.0
    delta = _quantized_field(delta)
    lab[ys, xs, 0] += delta.astype(np.float32)

    line, _, _ = _stroke_mask(path, int(style["core_width"]), gap)
    inside_line = line * body.astype(np.float32)
    line_pixels = int(np.count_nonzero(inside_line))
    if line_pixels < 3:
        raise V20ReplayError("a ridge semantic path missed its system")
    lab[..., 0] += inside_line * np.float32(style["core_l_delta"])
    active = np.abs(delta) >= 0.25
    if int(np.count_nonzero(active)) < 20:
        raise V20ReplayError("a signed relief field became visually empty")
    return {
        "source_length": round(total, 6),
        "core_pixels": line_pixels,
        "field_pixels_ge_0_25": int(np.count_nonzero(active)),
        "minimum_l_delta": round(float(delta.min()), 6),
        "maximum_l_delta": round(float(delta.max()), 6),
    }


def _apply_even_path_field(
    lab: np.ndarray,
    body: np.ndarray,
    path: Any,
    style: Mapping[str, Any],
    light_direction_xy: Any,
    *,
    scale: float,
) -> Mapping[str, Any]:
    ys, xs, distance, weight, total = _path_body_geometry(
        body,
        path,
        light_direction_xy,
        start_taper=float(style["start_taper"]),
        end_taper=float(style["end_taper"]),
        gap=None,
        gap_taper=0.0,
    )
    normalized = np.abs(distance) / float(style["sigma"])
    delta = (
        float(style["amplitude_l"])
        * np.exp(-0.5 * normalized * normalized)
        * weight
        * float(scale)
    )
    delta[normalized > 3.5] = 0.0
    delta = _quantized_field(delta)
    lab[ys, xs, 0] += delta.astype(np.float32)
    active = np.abs(delta) >= 0.25
    if int(np.count_nonzero(active)) < 12:
        raise V20ReplayError("a valley relief field became visually empty")
    return {
        "source_length": round(total, 6),
        "field_pixels_ge_0_25": int(np.count_nonzero(active)),
        "minimum_l_delta": round(float(delta.min()), 6),
        "maximum_l_delta": round(float(delta.max()), 6),
    }


def reconstruct(
    inputs: ReplayInputs,
    *,
    relief_gain: float = 1.0,
    lab_l_carrier: np.ndarray | None = None,
) -> BuildResult:
    _runtime_gate()
    _validate_marks(inputs.marks)
    _validate_search_summary(inputs.search_summary, inputs.marks, inputs.bindings)
    if array_sha256(inputs.baseline) != EXPECTED_BASE_PIXEL_SHA256:
        raise V20ReplayError("baseline decoded pixel authority changed")
    if array_sha256(inputs.foundation) != EXPECTED_FOUNDATION_PIXEL_SHA256:
        raise V20ReplayError("foundation decoded pixel authority changed")
    derived = derive_v20_body_control(inputs.v19_body_control, inputs.marks)
    if not np.array_equal(derived, inputs.v20_body_control):
        raise V20ReplayError("frozen v20 body control differs from marks derivation")
    body_masks, body, components = _decode_components(inputs.v20_body_control)
    if np.any(body & ~inputs.permission):
        raise V20ReplayError("a v21 body escaped permission")
    if np.any(body & (inputs.protected | inputs.road_calm)):
        raise V20ReplayError("a v21 body overlaps protected or road-calm pixels")

    target = cv2.cvtColor(inputs.foundation, cv2.COLOR_RGB2LAB).astype(np.float32)
    systems = inputs.marks["systems"]
    styles = inputs.marks["styles"]
    path_records: list[dict[str, Any]] = []
    for index, (system, system_body) in enumerate(
        zip(systems, body_masks, strict=True)
    ):
        volume_record = _apply_volume_relief(
            target,
            system_body,
            system,
            styles,
            relief_gain=relief_gain,
        )
        path_records.append(
            {
                "body_id": f"body-{index:02d}",
                "saddle_gap": system["saddle_gap"],
                "volume": volume_record,
            }
        )
    for actual, expected in zip(
        path_records, inputs.search_summary["selected"], strict=True
    ):
        volume = actual["volume"]
        topology = volume["topology"]
        warp = volume["domain_warp"]
        if any(
            topology[name]
            for name in (
                "closed_crater_count",
                "partial_dark_arc_count",
                "near_vertical_residual_count",
                "near_vertical_severe_count",
            )
        ):
            raise V20ReplayError(f"{actual['body_id']} forbidden relief topology")
        observed = {
            "relief_minimum_l": volume["relief_minimum_l"],
            "relief_maximum_l": volume["relief_maximum_l"],
            "relief_orientation_coherence": topology[
                "relief_orientation_coherence"
            ],
            "maximum_relative_jacobian_norm": warp[
                "maximum_relative_jacobian_norm"
            ],
            "minimum_mapping_determinant": warp["minimum_mapping_determinant"],
            "maximum_mapping_determinant": warp["maximum_mapping_determinant"],
        }
        if relief_gain == 1.0:
            if any(observed[name] != expected[name] for name in observed):
                raise V20ReplayError(
                    f"{actual['body_id']} finite-search diagnostics changed"
                )
        else:
            invariant_names = (
                "maximum_relative_jacobian_norm",
                "minimum_mapping_determinant",
                "maximum_mapping_determinant",
            )
            if any(observed[name] != expected[name] for name in invariant_names):
                raise V20ReplayError(
                    f"{actual['body_id']} finite-search frame changed during gain sweep"
                )
            if observed["relief_orientation_coherence"] > 0.4:
                raise V20ReplayError(
                    f"{actual['body_id']} gained relief became directionally coherent"
                )

    if lab_l_carrier is not None:
        carrier = np.asarray(lab_l_carrier)
        if carrier.shape != (HEIGHT, WIDTH) or not np.issubdtype(
            carrier.dtype, np.floating
        ):
            raise V20ReplayError("experimental Lab-L carrier shape/type changed")
        if not np.all(np.isfinite(carrier)):
            raise V20ReplayError("experimental Lab-L carrier is non-finite")
        carrier_support = carrier != 0.0
        editable = inputs.permission & ~inputs.protected & ~inputs.road_calm
        if np.any(carrier_support & ~editable):
            raise V20ReplayError("experimental Lab-L carrier escaped editable support")
        target[..., 0] += carrier.astype(np.float32)

    encoded_lab = np.clip(np.rint(target), 0, 255).astype(np.uint8)
    candidate = cv2.cvtColor(encoded_lab, cv2.COLOR_LAB2RGB)
    candidate[~inputs.permission] = inputs.baseline[~inputs.permission]
    locked = inputs.protected | inputs.road_calm
    candidate[locked] = inputs.baseline[locked]
    changed = np.any(candidate != inputs.baseline, axis=2)
    identity = {
        "changed_pixels": int(changed.sum()),
        "outside_permission": int(np.count_nonzero(changed & ~inputs.permission)),
        "protected_features": int(np.count_nonzero(changed & inputs.protected)),
        "road_calm_18px": int(np.count_nonzero(changed & inputs.road_calm)),
        "body_outside_permission": int(np.count_nonzero(body & ~inputs.permission)),
        "selected_component_count": 8,
    }
    if any(
        identity[name]
        for name in (
            "outside_permission",
            "protected_features",
            "road_calm_18px",
            "body_outside_permission",
        )
    ):
        raise V20ReplayError(f"v21 protected-pixel identity failed: {identity}")
    morphology = {
        "system_count": 8,
        "closed_path_count": 0,
        "replacement_pixels": components[-1]["pixels"],
        "replacement_bbox_xyxy": components[-1]["bbox_xyxy"],
        "paths": path_records,
    }
    return BuildResult(
        candidate=candidate,
        baseline=inputs.baseline.copy(),
        body=body,
        body_control=inputs.v20_body_control.copy(),
        components=components,
        identity=identity,
        morphology=morphology,
    )


def load_replay_inputs(contract_path: Path, *, expected_contract_sha256: str | None = None) -> ReplayInputs:
    root = Path.cwd().resolve()
    path = contract_path if contract_path.is_absolute() else root / contract_path
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise V20ReplayError(f"cannot read v21 replay contract: {path}") from exc
    if expected_contract_sha256 is not None and sha256_bytes(payload) != expected_contract_sha256:
        raise V20ReplayError("v21 replay contract SHA-256 mismatch")
    contract = _json(payload, label="v21 replay contract")
    required = {
        "schema_version",
        "interface",
        "baseline_v18",
        "foundation_v19",
        "v19_body_control",
        "v20_body_control",
        "ridge_marks",
        "search_summary",
        "search_script",
        "permission_mask",
        "protected_mask",
        "road_calm_mask",
    }
    if set(contract) != required:
        raise V20ReplayError("v21 replay contract keys changed")
    if contract["schema_version"] != SCHEMA_VERSION or contract["interface"] != INTERFACE:
        raise V20ReplayError("v21 replay contract identity changed")
    bindings = {
        role: _bind(root, contract[key], role=role)
        for role, key in (
            ("baseline_v18", "baseline_v18"),
            ("foundation_v19", "foundation_v19"),
            ("v19_body_control", "v19_body_control"),
            ("v20_body_control", "v20_body_control"),
            ("ridge_marks", "ridge_marks"),
            ("search_summary", "search_summary"),
            ("search_script", "search_script"),
            ("permission_mask", "permission_mask"),
            ("protected_mask", "protected_mask"),
            ("road_calm_mask", "road_calm_mask"),
        )
    }
    return ReplayInputs(
        baseline=_decode_rgb(bindings["baseline_v18"]),
        foundation=_decode_rgb(bindings["foundation_v19"]),
        v19_body_control=_decode_gray(bindings["v19_body_control"]),
        v20_body_control=_decode_gray(bindings["v20_body_control"]),
        marks=_json(bindings["ridge_marks"].data, label="v21 relief marks"),
        search_summary=_json(
            bindings["search_summary"].data, label="v21 relief search summary"
        ),
        permission=_decode_mask(bindings["permission_mask"]),
        protected=_decode_mask(bindings["protected_mask"]),
        road_calm=_decode_mask(bindings["road_calm_mask"]),
        bindings=bindings,
    )


def reconstruct_from_contract(
    contract_path: Path, *, expected_contract_sha256: str | None = None
) -> BuildResult:
    return reconstruct(
        load_replay_inputs(
            Path(contract_path), expected_contract_sha256=expected_contract_sha256
        )
    )


def png_bytes(candidate: np.ndarray, *, verify_expected: bool = True) -> bytes:
    payload = _rgb_png(candidate)
    if verify_expected and (
        len(payload) != EXPECTED_PNG_BYTES
        or sha256_bytes(payload) != EXPECTED_PNG_SHA256
        or array_sha256(candidate) != EXPECTED_PIXEL_SHA256
    ):
        raise V20ReplayError("v21 canonical output bytes changed")
    return payload


def _canonical_argument(path: Path) -> str:
    return path.as_posix()


def load_fixed_config(path: Path) -> dict[str, Any]:
    if _canonical_argument(path) != CONFIG_PATH:
        raise V20ReplayError(f"--config must equal {CONFIG_PATH}")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise V20ReplayError("cannot read fixed v21 renderer config") from exc
    if sha256_bytes(payload) != CONFIG_SHA256:
        raise V20ReplayError("fixed v21 renderer config SHA-256 mismatch")
    config = _json(payload, label="v21 renderer config")
    required = {
        "schema_version",
        "interface",
        "seed",
        "expected_output",
        "replay_contract",
        "donors",
        "controls",
    }
    if set(config) != required:
        raise V20ReplayError("v21 renderer config keys changed")
    expected_contract = {
        "path": REPLAY_CONTRACT_PATH,
        "sha256": REPLAY_CONTRACT_SHA256,
    }
    if (
        config["schema_version"] != SCHEMA_VERSION
        or config["interface"] != CONFIG_INTERFACE
        or config["seed"] != SEED
        or config["expected_output"] != EXPECTED_OUTPUT
        or config["replay_contract"] != expected_contract
        or config["donors"] != list(EXPECTED_DONORS)
        or config["controls"] != list(EXPECTED_CONTROLS)
    ):
        raise V20ReplayError("v21 renderer config value changed")
    return config


def render_fixed(
    *, config_path: Path, output: Path, donors: list[Path], controls: list[Path]
) -> dict[str, Any]:
    config = load_fixed_config(config_path)
    observed_donors = tuple(_canonical_argument(path) for path in donors)
    observed_controls = tuple(_canonical_argument(path) for path in controls)
    if observed_donors != EXPECTED_DONORS:
        raise V20ReplayError("ordered donor graph changed")
    if observed_controls != EXPECTED_CONTROLS:
        raise V20ReplayError("ordered control graph changed")
    result = reconstruct_from_contract(
        Path(config["replay_contract"]["path"]),
        expected_contract_sha256=config["replay_contract"]["sha256"],
    )
    payload = png_bytes(result.candidate)
    if output.exists() or output.is_symlink():
        raise V20ReplayError(f"refusing to overwrite v21 output: {output}")
    if not output.parent.is_dir():
        raise V20ReplayError(
            f"v21 output parent must already exist: {output.parent}"
        )
    with output.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return {
        "schema_version": SCHEMA_VERSION,
        "interface": INTERFACE,
        "seed": SEED,
        "output": output.as_posix(),
        "png_sha256": sha256_bytes(payload),
        "pixel_sha256": array_sha256(result.candidate),
        "png_bytes": len(payload),
        "size": [WIDTH, HEIGHT],
        "mode": "RGB",
        "identity": dict(result.identity),
        "morphology": dict(result.morphology),
        "passed": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--donor", type=Path, action="append", default=[])
    parser.add_argument("--control", type=Path, action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        receipt = render_fixed(
            config_path=args.config,
            output=args.output,
            donors=args.donor,
            controls=args.control,
        )
    except (V20ReplayError, OSError, ValueError) as exc:
        parser.exit(2, f"v21 Golden renderer failed closed: {exc}\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
