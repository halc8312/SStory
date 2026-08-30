"""Secret-keyed deterministic private control catalog for r3."""

from __future__ import annotations

import io
import json
import math
from collections import Counter
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from common import blind_hmac, canonical_json_bytes, sha256_bytes


@dataclass(frozen=True)
class ExpectedControl:
    family: str
    control_id: str
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

    @property
    def public_hash_tuple(self) -> tuple[str, str, str, str]:
        return (
            self.anonymous_code,
            self.control_sha256,
            self.reference_sha256,
            self.delta_float32_sha256,
        )


@dataclass(frozen=True)
class ContactSheetPage:
    scale_percent: int
    page_index: int
    path: str
    item_codes: tuple[str, ...]
    png_bytes: bytes
    sha256: str

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "scale_percent": self.scale_percent,
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


def _normalize_rms(values: np.ndarray, target: float) -> np.ndarray:
    centered = values.astype(np.float32) - np.float32(values.mean())
    rms = float(np.sqrt(np.mean(centered * centered)))
    return centered * np.float32(target / max(rms, 1e-12))


def _reference(
    rng: np.random.Generator, height: int, width: int, neutral: float
) -> np.ndarray:
    noise = rng.standard_normal((height + 192, width + 192), dtype=np.float32)
    paper = ndimage.gaussian_filter(noise, sigma=46.0, mode="reflect", truncate=4.0)
    paper = _normalize_rms(paper, 2.25)
    return (paper[96 : 96 + height, 96 : 96 + width] + np.float32(neutral)).astype(
        np.float32
    )


def _positions(
    rng: np.random.Generator, count: int, height: int, width: int, margin: int
) -> list[tuple[float, float]]:
    result = [(width * 0.5, height * 0.5)]
    for _ in range(max(0, count - 1)):
        result.append(
            (
                float(rng.uniform(margin, width - margin)),
                float(rng.uniform(margin, height - margin)),
            )
        )
    return result[:count]


def _density_count(value: float, height: int, width: int) -> int:
    return max(1, int(round(value * height * width / 1_000_000.0)))


def _line_mask(
    height: int, width: int, lines: list[tuple[float, float, float, float, int]]
) -> np.ndarray:
    image = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(image)
    for x0, y0, x1, y1, line_width in lines:
        draw.line((x0, y0, x1, y1), fill=255, width=max(1, line_width))
    return np.asarray(image, dtype=np.float32) / np.float32(255.0)


def _render_delta(
    family: str,
    parameters: dict[str, Any],
    polarity: int,
    rng: np.random.Generator,
    height: int,
    width: int,
) -> np.ndarray:
    sign = np.float32(polarity)
    zero = np.zeros((height, width), dtype=np.float32)
    if family == "clean-zero":
        return zero
    noise = rng.standard_normal((height, width), dtype=np.float32)
    if family == "clean-lowpass":
        return sign * _normalize_rms(
            ndimage.gaussian_filter(
                noise, float(parameters["sigma_px"]), mode="reflect"
            ),
            float(parameters["rms_l"]),
        )
    if family == "clean-matern-like":
        correlation = float(parameters["correlation_px"])
        field = np.float32(0.35) * ndimage.gaussian_filter(
            noise, correlation * 0.35, mode="reflect"
        ) + ndimage.gaussian_filter(noise, correlation, mode="reflect")
        return sign * _normalize_rms(field, float(parameters["rms_l"]))
    if family == "clean-broad-shoulder":
        yy, xx = np.mgrid[0:height, 0:width]
        radius = float(parameters["width_px"])
        field = np.exp(
            -((xx - width / 2) ** 2 + (yy - height / 2) ** 2) / (2 * radius**2)
        ).astype(np.float32)
        field -= field.mean()
        return (
            sign
            * field
            * np.float32(
                float(parameters["amplitude_l"])
                / max(float(np.max(np.abs(field))), 1e-12)
            )
        )
    if family == "clean-multiscale":
        field = np.zeros_like(noise)
        for sigma, weight in zip(parameters["sigma_px"], parameters["weights"]):
            field += np.float32(weight) * ndimage.gaussian_filter(
                noise, float(sigma), mode="reflect"
            )
        return sign * _normalize_rms(field, float(parameters["rms_l"]))
    if family in {"artifact-speck", "artifact-microblob"}:
        count = _density_count(float(parameters["count_per_mp"]), height, width)
        diameter = int(parameters["diameter_px"])
        yy, xx = np.mgrid[0:height, 0:width]
        field = zero.copy()
        for x, y in _positions(rng, count, height, width, diameter + 2):
            radius = max(0.5, diameter * 0.45 / 2)
            field += np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * radius**2)).astype(
                np.float32
            )
        return sign * np.minimum(field, 1.0) * np.float32(parameters["amplitude_l"])
    if family == "artifact-fine-band":
        yy, xx = np.mgrid[0:height, 0:width]
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
        return sign * _normalize_rms(
            wave.astype(np.float32), float(parameters["rms_l"])
        )
    if family == "artifact-short-dash":
        count = _density_count(float(parameters["count_per_mp"]), height, width)
        length = float(parameters["length_px"])
        lines = []
        for index, (x, y) in enumerate(
            _positions(rng, count, height, width, int(length) + 2)
        ):
            angle = 0.0 if index == 0 else float(rng.uniform(0, math.pi))
            dx, dy = math.cos(angle) * length / 2, math.sin(angle) * length / 2
            lines.append((x - dx, y - dy, x + dx, y + dy, int(parameters["width_px"])))
        return (
            sign
            * _line_mask(height, width, lines)
            * np.float32(parameters["amplitude_l"])
        )
    if family == "artifact-parallel-bundle":
        count = _density_count(float(parameters["pairs_per_mp"]), height, width)
        length, spacing = (
            float(parameters["length_px"]),
            float(parameters["spacing_px"]),
        )
        lines = []
        for index, (x, y) in enumerate(
            _positions(rng, count, height, width, int(length + spacing) + 2)
        ):
            angle = math.pi / 7 if index == 0 else float(rng.uniform(0, math.pi))
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
        return (
            sign
            * _line_mask(height, width, lines)
            * np.float32(parameters["amplitude_l"])
        )
    if family == "artifact-halftone":
        yy, xx = np.mgrid[0:height, 0:width]
        field = np.sin(math.pi * xx / float(parameters["cell_px"])) * np.sin(
            math.pi * yy / float(parameters["cell_px"])
        )
        return sign * field.astype(np.float32) * np.float32(parameters["amplitude_l"])
    raise RuntimeError(f"unknown family: {family}")


def _encode_png(values: np.ndarray, compression: int) -> bytes:
    stream = io.BytesIO()
    Image.fromarray(values.astype(np.uint8), mode="L").save(
        stream, format="PNG", compress_level=compression, optimize=False
    )
    return stream.getvalue()


def expected_controls(
    spec: dict[str, Any], split: str, key: bytes
) -> list[ExpectedControl]:
    if split not in {"calibration", "holdout"}:
        raise ValueError("invalid split")
    height, width = int(spec["canvas"]["height"]), int(spec["canvas"]["width"])
    prefix = spec["blind_derivation"]["seed_message_prefix"]
    code_prefix = spec["blind_derivation"]["code_message_prefix"]
    variant_key = f"{split}_variants"
    controls: list[ExpectedControl] = []
    for family in spec["control_families"]:
        for variant_index, parameters in enumerate(family[variant_key]):
            for polarity in family["polarities"]:
                for replicate in range(
                    int(spec["splits"][split]["replicates_per_variant"])
                ):
                    identity = {
                        "split": split,
                        "public_nonce": spec["splits"][split]["public_nonce"],
                        "family": family["id"],
                        "variant_index": variant_index,
                        "replicate": replicate,
                        "polarity": polarity,
                        "parameters": parameters,
                    }
                    reference_seed = int.from_bytes(
                        _hmac_material(key, prefix, identity, "reference")[:8], "big"
                    )
                    delta_seed = int.from_bytes(
                        _hmac_material(key, prefix, identity, "delta")[:8], "big"
                    )
                    reference_float = _reference(
                        np.random.default_rng(reference_seed),
                        height,
                        width,
                        float(spec["canvas"]["neutral_luminance"]),
                    )
                    requested = _render_delta(
                        family["id"],
                        parameters,
                        int(polarity),
                        np.random.default_rng(delta_seed),
                        height,
                        width,
                    ).astype(np.float32)
                    reference = np.clip(np.rint(reference_float), 0, 255).astype(
                        np.uint8
                    )
                    control = np.clip(
                        np.rint(reference_float + requested), 0, 255
                    ).astype(np.uint8)
                    reference_png = _encode_png(
                        reference, int(spec["canvas"]["png_compress_level"])
                    )
                    control_png = _encode_png(
                        control, int(spec["canvas"]["png_compress_level"])
                    )
                    identity_bytes = canonical_json_bytes(identity)
                    anonymous_code = blind_hmac(
                        key, code_prefix.encode("ascii") + identity_bytes
                    ).hex()[
                        : int(spec["blind_derivation"]["opaque_code_hex_characters"])
                    ]
                    control_id = blind_hmac(
                        key,
                        b"microtexture-v2-r3/private-control-id/v1/" + identity_bytes,
                    ).hex()[:24]
                    controls.append(
                        ExpectedControl(
                            family["id"],
                            control_id,
                            variant_index,
                            replicate,
                            int(polarity),
                            json.loads(json.dumps(parameters)),
                            anonymous_code,
                            reference,
                            requested,
                            control,
                            reference_png,
                            control_png,
                            sha256_bytes(reference_png),
                            sha256_bytes(control_png),
                            sha256_bytes(
                                np.ascontiguousarray(requested, dtype="<f4").tobytes()
                            ),
                        )
                    )
    codes = [control.anonymous_code for control in controls]
    if len(codes) != len(set(codes)):
        raise RuntimeError("HMAC opaque-code collision")
    return controls


def contact_sheet_pages(
    spec: dict[str, Any], split: str, controls: list[ExpectedControl]
) -> list[ContactSheetPage]:
    settings = spec["contact_sheets"]
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
    for scale in settings["scales_percent"]:
        crop_width, crop_height = [
            int(value) for value in settings["source_crop_by_scale"][str(scale)]
        ]
        integer_scale = int(scale) // 100
        if (
            int(scale) % 100
            or crop_width * integer_scale != panel_width
            or crop_height * integer_scale != panel_height
        ):
            raise RuntimeError("contact-sheet scale/crop does not exactly fill panel")
        for page_index, start in enumerate(range(0, len(codes), per_page), 1):
            item_codes = tuple(codes[start : start + per_page])
            sheet = np.full(
                (sheet_height, sheet_width),
                int(settings["sheet_background_l"]),
                dtype=np.uint8,
            )
            for slot, code in enumerate(item_codes):
                source = by_code[code].control
                top = (source.shape[0] - crop_height) // 2
                left = (source.shape[1] - crop_width) // 2
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
            relative = f"controls/{split}/contact-sheets/{int(scale)}pct-page-{page_index:03d}.png"
            pages.append(
                ContactSheetPage(
                    int(scale),
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
    for scale in settings["scales_percent"]:
        if sum(page.scale_percent == int(scale) for page in pages) != int(
            settings["expected_pages_per_scale"]
        ):
            raise RuntimeError(f"{split}/{scale}% contact-sheet page count drift")
    return pages


def validate_manifest_public_bindings(
    manifest: dict[str, Any], expected: list[ExpectedControl]
) -> None:
    expected_counter = Counter(control.public_hash_tuple for control in expected)
    actual_counter = Counter(
        (
            record["anonymous_code"],
            record["control_sha256"],
            record["reference_sha256"],
            record["delta_float32_sha256"],
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
    return {control.public_hash_tuple: control for control in expected}
