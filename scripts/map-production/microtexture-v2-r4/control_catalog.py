"""Secret-keyed deterministic private control catalog for r4."""

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

from common import (
    blind_hmac,
    canonical_json_bytes,
    sha256_bytes,
    validate_contact_sheet_view_partition,
)


@dataclass(frozen=True)
class ExpectedControl:
    family: str
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
    rng: np.random.Generator,
    count: int,
    roi_xywh: tuple[int, int, int, int],
    margin: int,
) -> list[tuple[float, float]]:
    left, top, width, height = roi_xywh
    if count < 0:
        raise RuntimeError("sparse-control count cannot be negative")
    if margin * 2 >= width or margin * 2 >= height:
        raise RuntimeError("sparse-control margin consumes the r4 metric window")
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


def _render_delta(
    family: str,
    parameters: dict[str, Any],
    polarity: int,
    rng: np.random.Generator,
    height: int,
    width: int,
    metric_window_xywh: tuple[int, int, int, int],
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
        count = int(parameters["count_in_metric_window"])
        length = float(parameters["length_px"])
        lines = []
        for x, y in _positions(
            rng, count, metric_window_xywh, int(math.ceil(length / 2)) + 3
        ):
            angle = float(rng.uniform(0, math.pi))
            dx, dy = math.cos(angle) * length / 2, math.sin(angle) * length / 2
            lines.append((x - dx, y - dy, x + dx, y + dy, int(parameters["width_px"])))
        return (
            sign
            * _line_mask(height, width, lines)
            * np.float32(parameters["amplitude_l"])
        )
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
    metric_window_xywh = tuple(
        int(value) for value in spec["canvas"]["metric_window"]["xywh"]
    )
    metric_left, metric_top, metric_width, metric_height = metric_window_xywh
    if (
        metric_window_xywh != (128, 96, 256, 192)
        or metric_left + metric_width > width
        or metric_top + metric_height > height
        or metric_width * metric_height
        != int(spec["canvas"]["metric_window"]["pixels"])
    ):
        raise RuntimeError("r4 exact metric-window geometry drift")
    prefix = spec["blind_derivation"]["seed_message_prefix"]
    code_prefix = spec["blind_derivation"]["code_message_prefix"]
    variant_key = f"{split}_variants"
    sparse_count_fields = {
        "artifact-speck": "count_in_metric_window",
        "artifact-microblob": "count_in_metric_window",
        "artifact-short-dash": "count_in_metric_window",
        "artifact-parallel-bundle": "pair_count_in_metric_window",
    }
    for family in spec["control_families"]:
        count_field = sparse_count_fields.get(family["id"])
        if count_field is None:
            continue
        counts = [variant.get(count_field) for variant in family[variant_key]]
        if counts != list(range(10)) or any(type(value) is not int for value in counts):
            raise RuntimeError(
                f"{split}/{family['id']} sparse counts must be exact integers 0..9"
            )
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
                    cluster_identity = {
                        key: identity[key]
                        for key in (
                            "split",
                            "public_nonce",
                            "family",
                            "variant_index",
                            "parameters",
                        )
                    }
                    render_identity = {
                        key: identity[key]
                        for key in (
                            "split",
                            "public_nonce",
                            "family",
                            "variant_index",
                            "replicate",
                            "parameters",
                        )
                    }
                    reference_seed = int.from_bytes(
                        _hmac_material(key, prefix, render_identity, "reference")[:8],
                        "big",
                    )
                    delta_seed = int.from_bytes(
                        _hmac_material(key, prefix, render_identity, "delta")[:8], "big"
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
                        metric_window_xywh,
                    ).astype(np.float32)
                    if family["id"] in sparse_count_fields:
                        x, y, window_width, window_height = metric_window_xywh
                        outside = requested.copy()
                        outside[y : y + window_height, x : x + window_width] = 0
                        if np.any(outside != 0):
                            raise RuntimeError(
                                f"{split}/{family['id']} sparse delta escaped metric window"
                            )
                        exact_count = int(parameters[sparse_count_fields[family["id"]]])
                        inside = requested[y : y + window_height, x : x + window_width]
                        if (exact_count == 0) != bool(np.all(inside == 0)):
                            raise RuntimeError(
                                f"{split}/{family['id']} zero/nonzero sparse boundary drift"
                            )
                    reference = np.clip(np.rint(reference_float), 0, 255).astype(
                        np.uint8
                    )
                    control = np.clip(
                        np.rint(reference_float + requested), 0, 255
                    ).astype(np.uint8)
                    if family["id"] in sparse_count_fields:
                        exact_count = int(parameters[sparse_count_fields[family["id"]]])
                        encoded_is_zero = np.array_equal(control, reference)
                        if (exact_count == 0) != encoded_is_zero:
                            raise RuntimeError(
                                f"{split}/{family['id']} encoded sparse boundary drift"
                            )
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
                        b"microtexture-v2-r4/private-control-id/v2/" + identity_bytes,
                    ).hex()[:24]
                    condition_cluster_id = blind_hmac(
                        key,
                        spec["independent_condition_clusters"]["message_prefix"].encode(
                            "ascii"
                        )
                        + canonical_json_bytes(cluster_identity),
                    ).hex()[:24]
                    controls.append(
                        ExpectedControl(
                            family["id"],
                            control_id,
                            condition_cluster_id,
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
    control_ids = [control.control_id for control in controls]
    if len(control_ids) != len(set(control_ids)):
        raise RuntimeError("HMAC private-control-id collision")
    clusters: dict[str, list[ExpectedControl]] = {}
    for control in controls:
        clusters.setdefault(control.condition_cluster_id, []).append(control)
    cluster_contract = spec["independent_condition_clusters"]
    if len(clusters) != int(cluster_contract["expected_unique_clusters_per_split"]):
        raise RuntimeError(f"{split} private-condition-cluster cardinality drift")
    family_cluster_counts = Counter(group[0].family for group in clusters.values())
    clean_cluster_count = sum(
        count
        for family, count in family_cluster_counts.items()
        if family.startswith("clean-")
    )
    artifact_cluster_count = sum(
        count
        for family, count in family_cluster_counts.items()
        if family.startswith("artifact-")
    )
    if clean_cluster_count != int(
        cluster_contract["expected_clean_clusters_per_split"]
    ):
        raise RuntimeError(f"{split} clean private-cluster cardinality drift")
    if artifact_cluster_count != int(
        cluster_contract["expected_artifact_clusters_per_split"]
    ):
        raise RuntimeError(f"{split} artifact private-cluster cardinality drift")
    for family, count in family_cluster_counts.items():
        if family.startswith("artifact-") and count != int(
            cluster_contract["expected_artifact_clusters_per_family"]
        ):
            raise RuntimeError(f"{split}/{family} private-cluster cardinality drift")
    for cluster_id, group in clusters.items():
        identities = {
            (
                control.family,
                control.variant_index,
                canonical_json_bytes(control.parameters),
            )
            for control in group
        }
        if len(identities) != 1:
            raise RuntimeError(
                f"HMAC private-condition-cluster collision: {cluster_id}"
            )
        if group[0].family.startswith("clean-"):
            if len(group) != 1 or group[0].polarity != 1:
                raise RuntimeError(f"{split} clean cluster pairing drift")
            continue
        by_polarity = {control.polarity: control for control in group}
        if len(group) != 2 or set(by_polarity) != {-1, 1}:
            raise RuntimeError(f"{split} artifact cluster polarity pairing drift")
        dark, light = by_polarity[-1], by_polarity[1]
        if dark.reference_png != light.reference_png or not np.array_equal(
            dark.reference, light.reference
        ):
            raise RuntimeError(f"{split} paired-polarity reference drift")
        if not np.array_equal(dark.requested_delta, -light.requested_delta):
            raise RuntimeError(f"{split} paired-polarity requested-delta drift")
    return controls


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
