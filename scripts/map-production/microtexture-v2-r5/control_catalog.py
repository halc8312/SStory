"""Secret-keyed deterministic private control catalog for r5."""

from __future__ import annotations

import hashlib
import io
import json
import math
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from common import (
    blind_hmac,
    canonical_json_bytes,
    sha256_bytes,
    validate_contact_sheet_view_partition,
)


@dataclass(frozen=True)
class ExpectedControl:
    family: str
    private_role: str
    foundation_id: str
    duplicate_audit_group: str | None
    control_id: str
    condition_cluster_id: str
    variant_index: int
    replicate: int
    polarity: int
    parameters: dict[str, Any]
    anonymous_code: str
    reference: np.ndarray
    requested_delta: np.ndarray
    control: np.ndarray
    reference_png: bytes
    control_png: bytes
    reference_sha256: str
    control_sha256: str
    delta_float32_sha256: str
    control_commitment: str
    reference_commitment: str
    delta_commitment: str

    @property
    def public_binding_tuple(self) -> tuple[str, str, str, str]:
        return (
            self.anonymous_code,
            self.control_commitment,
            self.reference_commitment,
            self.delta_commitment,
        )


@dataclass(frozen=True)
class ContactSheetPage:
    view_id: str
    scale_percent: int
    source_crop_xywh: tuple[int, int, int, int]
    page_index: int
    path: str
    item_codes: tuple[str, ...]
    png_bytes: bytes
    sha256: str

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "view_id": self.view_id,
            "scale_percent": self.scale_percent,
            "source_crop_xywh": list(self.source_crop_xywh),
            "page_index": self.page_index,
            "path": self.path,
            "sha256": self.sha256,
            "item_codes": list(self.item_codes),
        }


_HEX_GLYPHS = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "a": ("010", "101", "111", "101", "101"),
    "b": ("110", "101", "110", "101", "110"),
    "c": ("111", "100", "100", "100", "111"),
    "d": ("110", "101", "101", "101", "110"),
    "e": ("111", "100", "110", "100", "111"),
    "f": ("111", "100", "110", "100", "100"),
}


_REPO_ROOT = Path(__file__).resolve().parents[3]
_FOUNDATION_SOURCE_CROP_XYWH = (512, 320, 512, 384)
_FOUNDATIONS = (
    (
        "v10",
        "world/map-production/style-assets/"
        "microtexture-v2-r5-foundation-imagegen-v10.png",
        "df37429388f42649611388172d1dd60890f5a7d6b3437937181f0c078b76b5d5",
    ),
    (
        "v11",
        "world/map-production/style-assets/"
        "microtexture-v2-r5-foundation-imagegen-v11.png",
        "6dbb2126ac795d509cd248d95f81a4c5d91c8258d2a4845ea4030d96fdb0ee2f",
    ),
    (
        "v12",
        "world/map-production/style-assets/"
        "microtexture-v2-r5-foundation-imagegen-v12.png",
        "e05ca849d950d5b8c5eadcf85ba6cb246b1cecaa284a49e6f85722d253a7e44e",
    ),
)


@lru_cache(maxsize=1)
def _foundation_bank() -> dict[str, np.ndarray]:
    left, top, width, height = _FOUNDATION_SOURCE_CROP_XYWH
    bank: dict[str, np.ndarray] = {}
    for foundation_id, relative_path, expected_sha256 in _FOUNDATIONS:
        path = _REPO_ROOT / relative_path
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise RuntimeError(f"r5 foundation SHA drift: {foundation_id}")
        with Image.open(io.BytesIO(payload)) as opened:
            opened.load()
            if opened.mode != "RGB" or opened.size != (1536, 1024):
                raise RuntimeError(
                    f"r5 foundation image contract drift: {foundation_id}"
                )
            rgb = np.asarray(
                opened.crop((left, top, left + width, top + height)),
                dtype=np.uint8,
            )
        if rgb.shape != (height, width, 3):
            raise RuntimeError(f"r5 foundation crop geometry drift: {foundation_id}")
        values = rgb.astype(np.float32)
        luminance = (
            np.float32(0.299) * values[:, :, 0]
            + np.float32(0.587) * values[:, :, 1]
            + np.float32(0.114) * values[:, :, 2]
        ).astype(np.float32)
        luminance.setflags(write=False)
        bank[foundation_id] = luminance
    if set(bank) != {"v10", "v11", "v12"}:
        raise RuntimeError("r5 foundation allowlist drift")
    return bank


def _draw_hex_label(
    sheet: np.ndarray, code: str, origin_x: int, origin_y: int, fill: int
) -> None:
    glyph_scale = 2
    advance = 8
    for character_index, character in enumerate(code):
        glyph = _HEX_GLYPHS[character]
        x_base = origin_x + character_index * advance
        for row, bits in enumerate(glyph):
            for column, bit in enumerate(bits):
                if bit == "1":
                    y0 = origin_y + row * glyph_scale
                    x0 = x_base + column * glyph_scale
                    sheet[y0 : y0 + glyph_scale, x0 : x0 + glyph_scale] = np.uint8(fill)


def _hmac_material(
    key: bytes, prefix: str, identity: dict[str, Any], lane: str
) -> bytes:
    return blind_hmac(
        key,
        prefix.encode("ascii")
        + lane.encode("ascii")
        + b"/"
        + canonical_json_bytes(identity),
    )


def _public_payload_commitment(
    key: bytes, anonymous_code: str, lane: str, payload_sha256: str
) -> str:
    if lane not in {"control", "reference", "delta"}:
        raise RuntimeError("invalid r5 public payload-commitment lane")
    return blind_hmac(
        key,
        b"microtexture-v2-r5/public-payload-commitment/v3/"
        + lane.encode("ascii")
        + b"/"
        + anonymous_code.encode("ascii")
        + b"/"
        + bytes.fromhex(payload_sha256),
    ).hex()


def _hmac_prf_grid(
    *,
    key: bytes,
    prefix: str,
    identity: dict[str, Any],
    lane: str,
    shape: tuple[int, int],
) -> np.ndarray:
    """Derive a coefficient grid directly from an HMAC-SHA-256 PRF."""

    count = shape[0] * shape[1]
    values: list[float] = []
    counter = 0
    identity_bytes = canonical_json_bytes(identity)
    domain = (
        prefix.encode("ascii")
        + b"private-reference-transform-v4/"
        + lane.encode("ascii")
        + b"/"
        + identity_bytes
        + b"/"
    )
    while len(values) < count:
        digest = blind_hmac(key, domain + counter.to_bytes(4, "big"))
        for offset in range(0, len(digest), 8):
            integer = int.from_bytes(digest[offset : offset + 8], "big")
            values.append((integer / float((1 << 64) - 1)) * 2.0 - 1.0)
            if len(values) == count:
                break
        counter += 1
    return np.asarray(values, dtype=np.float32).reshape(shape)


def _private_reference_transform(
    reference: np.ndarray,
    *,
    key: bytes,
    prefix: str,
    identity: dict[str, Any],
    settings: dict[str, Any],
) -> np.ndarray:
    """Create a unique clean private reference without a public equality oracle."""

    if reference.ndim != 2 or reference.dtype != np.float32:
        raise RuntimeError("invalid r5 private reference-transform source")
    grid_height, grid_width = [int(value) for value in settings["control_grid_hw"]]
    maximum_displacement = float(settings["maximum_displacement_px"])
    maximum_tone = float(settings["maximum_tone_l"])
    interpolation_order = int(settings["interpolation_order"])
    coefficient_interpolation_order = int(settings["coefficient_interpolation_order"])
    boundary_mode = str(settings["boundary_mode"])
    safety_minimum = int(settings["encoded_luminance_minimum"])
    safety_maximum = int(settings["encoded_luminance_maximum"])
    if (
        (grid_height, grid_width) != (7, 9)
        or maximum_displacement != 1.75
        or maximum_tone != 0.75
        or interpolation_order != 1
        or coefficient_interpolation_order != 3
        or boundary_mode != "reflect"
        or (safety_minimum, safety_maximum) != (16, 243)
    ):
        raise RuntimeError("r5 private reference-transform parameter drift")

    height, width = reference.shape
    target_y, target_x = np.meshgrid(
        np.linspace(0.0, grid_height - 1, height, dtype=np.float32),
        np.linspace(0.0, grid_width - 1, width, dtype=np.float32),
        indexing="ij",
    )

    def field(lane: str, scale: float) -> np.ndarray:
        grid = _hmac_prf_grid(
            key=key,
            prefix=prefix,
            identity=identity,
            lane=lane,
            shape=(grid_height, grid_width),
        )
        expanded = ndimage.map_coordinates(
            grid,
            (target_y, target_x),
            order=coefficient_interpolation_order,
            mode=boundary_mode,
            prefilter=True,
        )
        return np.clip(expanded, -1.0, 1.0).astype(np.float32) * np.float32(scale)

    displacement_y = field("displacement-y", maximum_displacement)
    displacement_x = field("displacement-x", maximum_displacement)
    tone = field("tone", maximum_tone)
    source_y, source_x = np.meshgrid(
        np.arange(height, dtype=np.float32),
        np.arange(width, dtype=np.float32),
        indexing="ij",
    )
    warped = ndimage.map_coordinates(
        reference,
        (source_y + displacement_y, source_x + displacement_x),
        order=interpolation_order,
        mode=boundary_mode,
        prefilter=False,
    )
    encoded = np.clip(np.rint(warped + tone), safety_minimum, safety_maximum).astype(
        np.uint8
    )
    if encoded.shape != reference.shape:
        raise RuntimeError("r5 private reference-transform geometry drift")
    return encoded


def _normalize_rms(values: np.ndarray, target: float) -> np.ndarray:
    centered = values.astype(np.float32) - np.float32(values.mean())
    rms = float(np.sqrt(np.mean(centered * centered)))
    return centered * np.float32(target / max(rms, 1e-12))


def _positions(
    rng: np.random.Generator,
    count: int,
    roi_xywh: tuple[int, int, int, int],
    margin: int,
) -> list[tuple[float, float]]:
    left, top, width, height = roi_xywh
    if count < 0:
        raise RuntimeError("sparse-control count cannot be negative")
    if margin * 2 >= width or margin * 2 >= height:
        raise RuntimeError("sparse-control margin consumes the r5 metric window")
    return [
        (
            float(rng.uniform(left + margin, left + width - margin)),
            float(rng.uniform(top + margin, top + height - margin)),
        )
        for _ in range(count)
    ]


def _line_mask(
    height: int, width: int, lines: list[tuple[float, float, float, float, int]]
) -> np.ndarray:
    image = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(image)
    for x0, y0, x1, y1, line_width in lines:
        draw.line((x0, y0, x1, y1), fill=255, width=max(1, line_width))
    return np.asarray(image, dtype=np.float32) / np.float32(255.0)


def _retain_metric_support(
    field: np.ndarray,
    rng: np.random.Generator,
    metric_window_xywh: tuple[int, int, int, int],
    support_fraction: float,
) -> np.ndarray:
    if not 0.0 < support_fraction <= 1.0:
        raise RuntimeError("r5 fine-grain support fraction must be within (0, 1]")
    if support_fraction == 1.0:
        return field
    left, top, width, height = metric_window_xywh
    region = field[top : top + height, left : left + width]
    candidate_y, candidate_x = np.nonzero(np.abs(region) > np.float32(0.5001))
    if not candidate_y.size:
        raise RuntimeError("r5 fine-grain sparse support has no encodable candidate")
    target_count = min(
        candidate_y.size,
        max(1, int(math.ceil(width * height * support_fraction))),
    )
    selected = rng.choice(candidate_y.size, size=target_count, replace=False)
    retained = np.zeros_like(field)
    retained[top + candidate_y[selected], left + candidate_x[selected]] = region[
        candidate_y[selected], candidate_x[selected]
    ]
    return retained


def _render_unsigned_delta(
    family: str,
    parameters: dict[str, Any],
    rng: np.random.Generator,
    height: int,
    width: int,
    metric_window_xywh: tuple[int, int, int, int],
) -> np.ndarray:
    zero = np.zeros((height, width), dtype=np.float32)
    if family == "protocol-zero":
        return zero
    if family in {"artifact-speck", "artifact-microblob"}:
        count = int(parameters["count_in_metric_window"])
        diameter = int(parameters["diameter_px"])
        yy, xx = np.mgrid[0:height, 0:width]
        field = zero.copy()
        for x, y in _positions(rng, count, metric_window_xywh, diameter + 2):
            radius = max(0.5, diameter * 0.45 / 2)
            distance_squared = (xx - x) ** 2 + (yy - y) ** 2
            support_radius = diameter * 0.5 + 1.5
            field += (
                np.exp(-distance_squared / (2 * radius**2))
                * (distance_squared <= support_radius**2)
            ).astype(np.float32)
        return np.minimum(field, 1.0) * np.float32(parameters["amplitude_l"])
    if family == "artifact-fine-grain":
        yy, xx = np.mgrid[0:height, 0:width]
        if parameters["pattern"] == "fine-band":
            angle, phase = (
                float(rng.uniform(0, math.pi)),
                float(rng.uniform(0, 2 * math.pi)),
            )
            wave = np.sin(
                2
                * math.pi
                * (xx * math.cos(angle) + yy * math.sin(angle))
                / float(parameters["wavelength_px"])
                + phase
            )
            field = _normalize_rms(wave.astype(np.float32), float(parameters["rms_l"]))
            return _retain_metric_support(
                field,
                rng,
                metric_window_xywh,
                float(parameters["support_fraction_in_metric_window"]),
            )
        if parameters["pattern"] == "halftone":
            field = np.sin(math.pi * xx / float(parameters["cell_px"])) * np.sin(
                math.pi * yy / float(parameters["cell_px"])
            )
            return _retain_metric_support(
                field.astype(np.float32) * np.float32(parameters["amplitude_l"]),
                rng,
                metric_window_xywh,
                float(parameters["support_fraction_in_metric_window"]),
            )
        raise RuntimeError("unknown r5 fine-grain pattern")
    if family == "artifact-short-dash":
        count = int(parameters["count_in_metric_window"])
        length = float(parameters["length_px"])
        lines = []
        for x, y in _positions(
            rng, count, metric_window_xywh, int(math.ceil(length / 2)) + 3
        ):
            angle = float(rng.uniform(0, math.pi))
            dx, dy = math.cos(angle) * length / 2, math.sin(angle) * length / 2
            lines.append((x - dx, y - dy, x + dx, y + dy, int(parameters["width_px"])))
        return _line_mask(height, width, lines) * np.float32(parameters["amplitude_l"])
    if family == "artifact-parallel-bundle":
        count = int(parameters["pair_count_in_metric_window"])
        length, spacing = (
            float(parameters["length_px"]),
            float(parameters["spacing_px"]),
        )
        lines = []
        for x, y in _positions(
            rng,
            count,
            metric_window_xywh,
            int(math.ceil((length + spacing) / 2)) + 3,
        ):
            angle = float(rng.uniform(0, math.pi))
            ux, uy, nx, ny = (
                math.cos(angle),
                math.sin(angle),
                -math.sin(angle),
                math.cos(angle),
            )
            for offset in (-spacing / 2, spacing / 2):
                cx, cy = x + nx * offset, y + ny * offset
                lines.append(
                    (
                        cx - ux * length / 2,
                        cy - uy * length / 2,
                        cx + ux * length / 2,
                        cy + uy * length / 2,
                        int(parameters["width_px"]),
                    )
                )
        return _line_mask(height, width, lines) * np.float32(parameters["amplitude_l"])
    raise RuntimeError(f"unknown family: {family}")


def _artifact_variants(split: str) -> dict[str, list[dict[str, Any]]]:
    if split == "calibration":
        nonce_base, offset = 1000, 0
        band_scales = (2.8, 3.6, 4.8, 6.2, 8.0, 10.5)
        band_levels = (0.42, 0.8, 1.6, 2.5, 3.7, 5.1)
        half_scales = (3, 4, 5, 7, 9, 11)
        half_levels = (0.75, 0.95, 2.2, 3.4, 5.0, 6.8)
        speck_levels = (1.2, 10.0, 8.0, 1.6, 4.0, 3.2, 1.8, 8.0, 3.6, 4.0, 9.0, 1.5)
        microblob_levels = (
            1.2,
            7.4,
            3.2,
            1.5,
            3.5,
            10.6,
            1.2,
            9.0,
            1.4,
            7.4,
            9.8,
            1.8,
        )
        short_dash_levels = (
            1.2,
            9.0,
            6.6,
            1.5,
            3.2,
            5.8,
            9.8,
            7.4,
            3.5,
            9.0,
            6.6,
            10.6,
        )
        parallel_levels = (
            1.2,
            9.4,
            7.0,
            1.5,
            3.3,
            6.2,
            10.2,
            7.8,
            1.5,
            9.4,
            7.0,
            3.2,
        )
    elif split == "holdout":
        nonce_base, offset = 5000, 1
        band_scales = (3.1, 4.1, 5.3, 6.9, 8.8, 11.4)
        band_levels = (0.4, 0.9, 1.8, 2.7, 4.0, 5.3)
        half_scales = (4, 5, 6, 8, 10, 12)
        half_levels = (0.55, 0.8, 2.4, 3.7, 5.3, 7.1)
        speck_levels = (12.0, 1.2, 9.0, 1.0, 4.0, 8.5, 3.8, 1.8, 8.0, 4.2, 1.4, 9.5)
        microblob_levels = (
            1.3,
            7.8,
            3.4,
            1.6,
            3.7,
            10.8,
            1.3,
            9.3,
            1.5,
            7.8,
            10.1,
            1.9,
        )
        short_dash_levels = (
            1.3,
            9.3,
            6.9,
            1.6,
            3.4,
            6.1,
            10.1,
            7.7,
            3.4,
            9.3,
            6.9,
            10.8,
        )
        parallel_levels = (
            1.3,
            9.7,
            7.3,
            1.6,
            3.5,
            6.5,
            10.5,
            8.1,
            1.6,
            9.7,
            7.3,
            3.2,
        )
    else:
        raise ValueError("invalid split")

    grain = [
        {
            "condition_nonce": nonce_base + index,
            "pattern": "fine-band",
            "wavelength_px": wavelength,
            "rms_l": level,
            "support_fraction_in_metric_window": 0.001 if index == 0 else 1.0,
        }
        for index, (wavelength, level) in enumerate(zip(band_scales, band_levels))
    ]
    grain.extend(
        {
            "condition_nonce": nonce_base + 6 + index,
            "pattern": "halftone",
            "cell_px": cell,
            "amplitude_l": level,
            "support_fraction_in_metric_window": 0.001 if index == 0 else 1.0,
        }
        for index, (cell, level) in enumerate(zip(half_scales, half_levels))
    )

    speck = [
        {
            "condition_nonce": nonce_base + 100 + index,
            "diameter_px": 1 + ((index * 2 + offset) % 3),
            "amplitude_l": speck_levels[index],
            "count_in_metric_window": 4 + ((index * 5 + offset) % 18),
        }
        for index in range(12)
    ]
    microblob = [
        {
            "condition_nonce": nonce_base + 200 + index,
            "diameter_px": 4 + ((index * 5 + offset) % 13),
            "amplitude_l": microblob_levels[index],
            "count_in_metric_window": 2 + ((index * 7 + offset) % 13),
        }
        for index in range(12)
    ]
    short_dash = [
        {
            "condition_nonce": nonce_base + 300 + index,
            "length_px": 4 + ((index * 7 + offset) % 21),
            "width_px": 1 + ((index * 3 + offset) % 4),
            "amplitude_l": short_dash_levels[index],
            "count_in_metric_window": 2 + ((index * 5 + offset) % 13),
        }
        for index in range(12)
    ]
    parallel = [
        {
            "condition_nonce": nonce_base + 400 + index,
            "length_px": 6 + ((index * 7 + offset) % 19),
            "width_px": 1 + ((index * 3 + offset) % 4),
            "spacing_px": 4 + ((index * 5 + offset) % 21),
            "amplitude_l": parallel_levels[index],
            "pair_count_in_metric_window": 2 + ((index * 5 + offset) % 13),
        }
        for index in range(12)
    ]
    result = {
        "artifact-fine-grain": grain,
        "artifact-speck": speck,
        "artifact-microblob": microblob,
        "artifact-short-dash": short_dash,
        "artifact-parallel-bundle": parallel,
    }
    if any(len(variants) != 12 for variants in result.values()):
        raise RuntimeError("r5 bounded artifact variant contract drift")
    for family, variants in result.items():
        if len({canonical_json_bytes(item) for item in variants}) != 12:
            raise RuntimeError(f"r5 duplicate artifact condition: {family}")
    return result


def _encode_png(values: np.ndarray, compression: int) -> bytes:
    stream = io.BytesIO()
    Image.fromarray(values.astype(np.uint8), mode="L").save(
        stream, format="PNG", compress_level=compression, optimize=False
    )
    return stream.getvalue()


def _expected_controls_bounded(
    spec: dict[str, Any], split: str, key: bytes
) -> list[ExpectedControl]:
    if split not in {"calibration", "holdout"}:
        raise ValueError("invalid split")
    height, width = int(spec["canvas"]["height"]), int(spec["canvas"]["width"])
    if (width, height) != (512, 384):
        raise RuntimeError("r5 foundation canvas contract drift")
    metric_window_xywh = tuple(
        int(value) for value in spec["canvas"]["metric_window"]["xywh"]
    )
    if metric_window_xywh != (128, 96, 256, 192):
        raise RuntimeError("r5 exact metric-window geometry drift")
    bank = _foundation_bank()
    prefix = spec["blind_derivation"]["seed_message_prefix"]
    code_prefix = spec["blind_derivation"]["code_message_prefix"]
    public_nonce = spec["splits"][split]["public_nonce"]
    compression = int(spec["canvas"]["png_compress_level"])
    controls: list[ExpectedControl] = []

    def emit(
        *,
        private_role: str,
        family: str,
        variant_index: int,
        replicate: int,
        polarity: int,
        parameters: dict[str, Any],
        duplicate_audit_group: str | None,
        render_family: str,
    ) -> None:
        cluster_seed_identity = {
            "split": split,
            "public_nonce": public_nonce,
            "private_role": private_role,
            "family": family,
            "variant_index": variant_index,
            "parameters": parameters,
            "duplicate_audit_group": duplicate_audit_group,
        }
        if private_role in {"artifact", "protocol-zero"}:
            assignment_scope = {
                "split": split,
                "public_nonce": public_nonce,
                "private_role": private_role,
                "family": family,
            }
            foundation_offset = int.from_bytes(
                _hmac_material(key, prefix, assignment_scope, "foundation-offset-v3")[
                    :8
                ],
                "big",
            ) % len(_FOUNDATIONS)
            foundation_index = (variant_index + foundation_offset) % len(_FOUNDATIONS)
        else:
            foundation_index = int.from_bytes(
                _hmac_material(
                    key, prefix, cluster_seed_identity, "foundation-assignment-v3"
                )[:8],
                "big",
            ) % len(_FOUNDATIONS)
        foundation_id = _FOUNDATIONS[foundation_index][0]
        cluster_identity = {
            **cluster_seed_identity,
            "foundation_id": foundation_id,
        }
        delta_seed = int.from_bytes(
            _hmac_material(key, prefix, cluster_identity, "delta-v3"), "big"
        )
        unsigned = _render_unsigned_delta(
            render_family,
            parameters,
            np.random.default_rng(delta_seed),
            height,
            width,
            metric_window_xywh,
        ).astype(np.float32)
        requested = (unsigned * np.float32(polarity)).astype(np.float32)
        reference_float = bank[foundation_id]
        reference_identity = {
            **cluster_identity,
            "replicate": replicate,
            "polarity": polarity,
        }
        reference = _private_reference_transform(
            reference_float,
            key=key,
            prefix=prefix,
            identity=reference_identity,
            settings=spec["control_catalog_authority"]["private_reference_transform"],
        )
        encoded_requested = np.rint(requested).astype(np.int16)
        encoded_control = reference.astype(np.int16) + encoded_requested
        if np.any(encoded_control < 0) or np.any(encoded_control > 255):
            raise RuntimeError(
                "r5 encoded control exceeded the luminance safety margin"
            )
        control = encoded_control.astype(np.uint8)
        if private_role == "protocol-zero" or (
            private_role == "duplicate-audit" and duplicate_audit_group == "clean"
        ):
            if np.any(requested != 0) or not np.array_equal(control, reference):
                raise RuntimeError("r5 zero protocol control/reference drift")
        else:
            if not np.any(requested != 0) or np.array_equal(control, reference):
                raise RuntimeError(
                    "r5 nonzero artifact collapsed during encoding: "
                    f"{split}/{family}/v{variant_index}/r{replicate}/p{polarity}"
                )
        if render_family in {
            "artifact-speck",
            "artifact-microblob",
            "artifact-short-dash",
            "artifact-parallel-bundle",
        }:
            left, top, window_width, window_height = metric_window_xywh
            outside = requested.copy()
            outside[top : top + window_height, left : left + window_width] = 0
            if np.any(outside != 0):
                raise RuntimeError(f"{split}/{render_family} escaped metric window")
        reference_png = _encode_png(reference, compression)
        control_png = _encode_png(control, compression)
        identity = {
            **cluster_identity,
            "replicate": replicate,
            "polarity": polarity,
        }
        identity_bytes = canonical_json_bytes(identity)
        anonymous_code = blind_hmac(
            key, code_prefix.encode("ascii") + identity_bytes
        ).hex()[: int(spec["blind_derivation"]["opaque_code_hex_characters"])]
        control_id = blind_hmac(
            key, b"microtexture-v2-r5/private-control-id/v3/" + identity_bytes
        ).hex()[:24]
        condition_cluster_id = blind_hmac(
            key,
            spec["independent_condition_clusters"]["message_prefix"].encode("ascii")
            + canonical_json_bytes(cluster_identity),
        ).hex()[:24]
        reference_sha256 = sha256_bytes(reference_png)
        control_sha256 = sha256_bytes(control_png)
        delta_float32_sha256 = sha256_bytes(
            np.ascontiguousarray(requested, dtype="<f4").tobytes()
        )
        controls.append(
            ExpectedControl(
                family=family,
                private_role=private_role,
                foundation_id=foundation_id,
                duplicate_audit_group=duplicate_audit_group,
                control_id=control_id,
                condition_cluster_id=condition_cluster_id,
                variant_index=variant_index,
                replicate=replicate,
                polarity=polarity,
                parameters=json.loads(json.dumps(parameters)),
                anonymous_code=anonymous_code,
                reference=reference,
                requested_delta=requested,
                control=control,
                reference_png=reference_png,
                control_png=control_png,
                reference_sha256=reference_sha256,
                control_sha256=control_sha256,
                delta_float32_sha256=delta_float32_sha256,
                control_commitment=_public_payload_commitment(
                    key, anonymous_code, "control", control_sha256
                ),
                reference_commitment=_public_payload_commitment(
                    key, anonymous_code, "reference", reference_sha256
                ),
                delta_commitment=_public_payload_commitment(
                    key, anonymous_code, "delta", delta_float32_sha256
                ),
            )
        )

    for family, variants in _artifact_variants(split).items():
        for variant_index, parameters in enumerate(variants):
            for polarity in (-1, 1):
                emit(
                    private_role="artifact",
                    family=family,
                    variant_index=variant_index,
                    replicate=0,
                    polarity=polarity,
                    parameters=parameters,
                    duplicate_audit_group=None,
                    render_family=family,
                )

    zero_nonce_base = 9000 if split == "calibration" else 19000
    for variant_index in range(16):
        emit(
            private_role="protocol-zero",
            family="protocol-zero",
            variant_index=variant_index,
            replicate=0,
            polarity=1,
            parameters={"protocol_nonce": zero_nonce_base + variant_index},
            duplicate_audit_group=None,
            render_family="protocol-zero",
        )

    clean_audit_parameters = {
        "audit_nonce": 29000 if split == "calibration" else 39000,
        "audit_kind": "clean-isomorphic-replicate",
    }
    artifact_audit_parameters = {
        "audit_nonce": 29001 if split == "calibration" else 39001,
        "audit_kind": "obvious-artifact-isomorphic-replicate",
        "condition_nonce": 29002 if split == "calibration" else 39002,
        "length_px": 18 if split == "calibration" else 20,
        "width_px": 3,
        "amplitude_l": 10.4 if split == "calibration" else 10.8,
        "count_in_metric_window": 10 if split == "calibration" else 11,
    }
    for replicate in range(2):
        emit(
            private_role="duplicate-audit",
            family="duplicate-audit",
            variant_index=0,
            replicate=replicate,
            polarity=1,
            parameters=clean_audit_parameters,
            duplicate_audit_group="clean",
            render_family="protocol-zero",
        )
        emit(
            private_role="duplicate-audit",
            family="duplicate-audit",
            variant_index=1,
            replicate=replicate,
            polarity=1,
            parameters=artifact_audit_parameters,
            duplicate_audit_group="artifact",
            render_family="artifact-short-dash",
        )

    if len(controls) != 140:
        raise RuntimeError("r5 bounded corpus record count drift")
    role_counts = Counter(control.private_role for control in controls)
    if role_counts != Counter(
        {"artifact": 120, "protocol-zero": 16, "duplicate-audit": 4}
    ):
        raise RuntimeError("r5 private-role cardinality drift")
    if {control.foundation_id for control in controls} - {"v10", "v11", "v12"}:
        raise RuntimeError("r5 rejected foundation entered corpus")
    zero_foundations = {
        control.foundation_id
        for control in controls
        if control.private_role == "protocol-zero"
    }
    if zero_foundations != {"v10", "v11", "v12"}:
        raise RuntimeError("r5 protocol-zero foundation coverage drift")
    codes = [control.anonymous_code for control in controls]
    control_ids = [control.control_id for control in controls]
    if len(codes) != len(set(codes)) or len(control_ids) != len(set(control_ids)):
        raise RuntimeError("r5 private identity collision")
    if len({control.control_sha256 for control in controls}) != len(controls):
        raise RuntimeError("r5 public control payload equality leak")
    if len({control.reference_sha256 for control in controls}) != len(controls):
        raise RuntimeError("r5 private reference-instance cardinality drift")
    for view in spec["contact_sheets"]["views"]:
        left, top, view_width, view_height = [
            int(value) for value in view["source_crop_xywh"]
        ]
        view_hashes = {
            sha256_bytes(
                np.ascontiguousarray(
                    control.control[top : top + view_height, left : left + view_width]
                ).tobytes()
            )
            for control in controls
        }
        if len(view_hashes) != len(controls):
            raise RuntimeError(
                f"r5 public contact-sheet panel equality leak: {view['id']}"
            )

    artifact_clusters: dict[str, list[ExpectedControl]] = {}
    for control in controls:
        if control.private_role == "artifact":
            artifact_clusters.setdefault(control.condition_cluster_id, []).append(
                control
            )
    if len(artifact_clusters) != 60:
        raise RuntimeError("r5 artifact cluster cardinality drift")
    family_clusters = Counter(group[0].family for group in artifact_clusters.values())
    if set(family_clusters.values()) != {12} or len(family_clusters) != 5:
        raise RuntimeError("r5 artifact family cluster cardinality drift")
    for cluster_id, pair in artifact_clusters.items():
        if len(pair) != 2 or {item.polarity for item in pair} != {-1, 1}:
            raise RuntimeError(f"r5 polarity pair drift: {cluster_id}")
        dark = next(item for item in pair if item.polarity == -1)
        light = next(item for item in pair if item.polarity == 1)
        if dark.reference_png == light.reference_png or not np.array_equal(
            dark.requested_delta, -light.requested_delta
        ):
            raise RuntimeError(f"r5 polarity render drift: {cluster_id}")
        dark_encoded = dark.control.astype(np.int16) - dark.reference.astype(np.int16)
        light_encoded = light.control.astype(np.int16) - light.reference.astype(
            np.int16
        )
        if not np.array_equal(dark_encoded, -light_encoded):
            raise RuntimeError(f"r5 encoded polarity symmetry drift: {cluster_id}")

    for group_name in ("clean", "artifact"):
        pair = [
            control
            for control in controls
            if control.duplicate_audit_group == group_name
        ]
        if len(pair) != 2 or len({item.anonymous_code for item in pair}) != 2:
            raise RuntimeError(f"r5 duplicate audit membership drift: {group_name}")
        left, right = pair
        if (
            left.condition_cluster_id != right.condition_cluster_id
            or left.foundation_id != right.foundation_id
            or left.delta_float32_sha256 != right.delta_float32_sha256
            or not np.array_equal(left.requested_delta, right.requested_delta)
            or left.reference_png == right.reference_png
            or left.control_png == right.control_png
        ):
            raise RuntimeError(f"r5 semantic replicate audit drift: {group_name}")
        left_encoded = left.control.astype(np.int16) - left.reference.astype(np.int16)
        right_encoded = right.control.astype(np.int16) - right.reference.astype(
            np.int16
        )
        if not np.array_equal(left_encoded, right_encoded):
            raise RuntimeError(
                f"r5 semantic replicate encoded-residual drift: {group_name}"
            )
        if group_name == "clean":
            if (
                left.control_png != left.reference_png
                or right.control_png != right.reference_png
            ):
                raise RuntimeError("r5 clean semantic replicate is not exact-zero")
        elif (
            left.control_png == left.reference_png
            or right.control_png == right.reference_png
        ):
            raise RuntimeError(
                "r5 artifact semantic replicate collapsed during encoding"
            )
    return controls


def expected_controls(
    spec: dict[str, Any], split: str, key: bytes
) -> list[ExpectedControl]:
    return _expected_controls_bounded(spec, split, key)


def contact_sheet_pages(
    spec: dict[str, Any], split: str, controls: list[ExpectedControl]
) -> list[ContactSheetPage]:
    settings = spec["contact_sheets"]
    validate_contact_sheet_view_partition(
        settings, spec["canvas"]["metric_window"]["xywh"]
    )
    metric_window = tuple(
        int(value) for value in spec["canvas"]["metric_window"]["xywh"]
    )
    expected_count = int(settings["expected_controls_per_split"])
    if len(controls) != expected_count:
        raise RuntimeError(f"{split} control count must be exactly {expected_count}")
    by_code = {control.anonymous_code: control for control in controls}
    if len(by_code) != len(controls):
        raise RuntimeError("contact-sheet opaque code collision")
    codes = sorted(by_code)
    columns = int(settings["columns"])
    rows = int(settings["rows_per_page"])
    per_page = columns * rows
    panel_width, panel_height = [int(value) for value in settings["panel_dimensions"]]
    label_height = int(settings["label_height"])
    sheet_width, sheet_height = [int(value) for value in settings["sheet_dimensions"]]
    if sheet_width != columns * panel_width or sheet_height != rows * (
        panel_height + label_height
    ):
        raise RuntimeError("contact-sheet dimensions disagree with panel grid")
    label_x, label_y = [int(value) for value in settings["label_origin_in_panel"]]
    pages: list[ContactSheetPage] = []
    expected_view_ids: set[str] = set()
    for view in settings["views"]:
        view_id = str(view["id"])
        if not view_id or view_id in expected_view_ids:
            raise RuntimeError(
                "contact-sheet view identifiers must be unique/non-empty"
            )
        expected_view_ids.add(view_id)
        scale = int(view["scale_percent"])
        crop_xywh = tuple(int(value) for value in view["source_crop_xywh"])
        left, top, crop_width, crop_height = crop_xywh
        integer_scale = int(scale) // 100
        if (
            int(scale) % 100
            or crop_width * integer_scale != panel_width
            or crop_height * integer_scale != panel_height
        ):
            raise RuntimeError("contact-sheet scale/crop does not exactly fill panel")
        if (
            left < 0
            or top < 0
            or crop_width <= 0
            or crop_height <= 0
            or left + crop_width > int(spec["canvas"]["width"])
            or top + crop_height > int(spec["canvas"]["height"])
        ):
            raise RuntimeError(f"contact-sheet view {view_id} escapes the canvas")
        if view_id == "full-200" and crop_xywh != metric_window:
            raise RuntimeError("full-200 sheet is not the exact metric window")
        for page_index, start in enumerate(range(0, len(codes), per_page), 1):
            item_codes = tuple(codes[start : start + per_page])
            sheet = np.full(
                (sheet_height, sheet_width),
                int(settings["sheet_background_l"]),
                dtype=np.uint8,
            )
            for slot, code in enumerate(item_codes):
                source = by_code[code].control
                crop = source[top : top + crop_height, left : left + crop_width]
                display = np.repeat(
                    np.repeat(crop, integer_scale, axis=0), integer_scale, axis=1
                )
                column, row = slot % columns, slot // columns
                x = column * panel_width
                y = row * (panel_height + label_height)
                sheet[y : y + panel_height, x : x + panel_width] = display
                _draw_hex_label(
                    sheet, code, x + label_x, y + label_y, int(settings["label_fill_l"])
                )
            payload = _encode_png(sheet, int(spec["canvas"]["png_compress_level"]))
            relative = (
                f"controls/{split}/contact-sheets/{view_id}-page-{page_index:03d}.png"
            )
            pages.append(
                ContactSheetPage(
                    view_id,
                    int(scale),
                    crop_xywh,
                    page_index,
                    relative,
                    item_codes,
                    payload,
                    sha256_bytes(payload),
                )
            )
    expected_pages = int(settings["expected_pages_per_split"])
    if len(pages) != expected_pages:
        raise RuntimeError(
            f"{split} must have exactly {expected_pages} contact-sheet pages"
        )
    for view_id in expected_view_ids:
        if sum(page.view_id == view_id for page in pages) != int(
            settings["expected_pages_per_view"]
        ):
            raise RuntimeError(f"{split}/{view_id} contact-sheet page count drift")
    for page_index in range(1, int(settings["expected_pages_per_view"]) + 1):
        item_bundles = {
            page.item_codes for page in pages if page.page_index == page_index
        }
        if len(item_bundles) != 1:
            raise RuntimeError(
                f"{split}/page-{page_index:03d} view item-code order drift"
            )
    return pages


def validate_manifest_public_bindings(
    manifest: dict[str, Any], expected: list[ExpectedControl]
) -> None:
    expected_counter = Counter(control.public_binding_tuple for control in expected)
    actual_counter = Counter(
        (
            record["anonymous_code"],
            record["control_commitment"],
            record["reference_commitment"],
            record["delta_commitment"],
        )
        for record in manifest["records"]
    )
    if expected_counter != actual_counter or any(
        count != 1 for count in expected_counter.values()
    ):
        raise RuntimeError("secret-derived exact public binding tuple multiset drift")


def bind_manifest_to_expected(
    manifest: dict[str, Any], spec: dict[str, Any], split: str, key: bytes
) -> dict[tuple[str, str, str, str], ExpectedControl]:
    expected = expected_controls(spec, split, key)
    validate_manifest_public_bindings(manifest, expected)
    expected_codes = {control.anonymous_code for control in expected}
    if expected_codes != {record["anonymous_code"] for record in manifest["records"]}:
        raise RuntimeError("secret-derived opaque code set drift")
    return {control.public_binding_tuple: control for control in expected}
