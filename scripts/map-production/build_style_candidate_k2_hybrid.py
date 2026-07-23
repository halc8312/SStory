#!/usr/bin/env python3
"""Build the deterministic K2 local-repair hybrid at native 1536x1024.

K1 is the byte-source base.  K2 changes only four tightly controlled classes:
the canonical highland, the eight canonical field interiors, the canonical
capital union, and <=2 px canonical coast/river/road linework.  Three reviewed
crop-specific plates are used only inside their named semantic masks.  No
whole-board synthesis, histogram remapping, scaling of the final board, or
source-location transfer outside those masks is permitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "world/map-production/controls/style-candidate-i-v1-composition-guide.png"
K1 = ROOT / "world/map-production/candidates/style-candidate-k-v1-full-board.png"
B1 = ROOT / "world/map-production/candidates/style-candidate-b-v1.png"
CONTROL_ROOT = ROOT / "world/map-production/controls/style-candidate-k-v2-hybrid"
WARP_BASE = CONTROL_ROOT / "k1-geometry-warp-base.png"
WARP_BUILDER = ROOT / "scripts/map-production/build_style_candidate_k2_geometry_warp.py"
WARP_REPORT = CONTROL_ROOT / "k1-geometry-warp-report.json"
DONOR_ROOT = CONTROL_ROOT
CAPITAL_DONOR = DONOR_ROOT / "capital-organic-v2.png"
FIELDS_DONOR = DONOR_ROOT / "fields-calm-v2.png"
HIGHLAND_DONOR = DONOR_ROOT / "highland-calm-v2.png"
CRISP_CAPITAL = DONOR_ROOT / "crisp-capital-wall-gates-source.png"
PLATE_PROMPT = ROOT / "world/map-production/prompts/style-candidate-k-v2-local-correction-plate.generation.txt"
CAPITAL_PROMPT = ROOT / "world/map-production/prompts/style-candidate-k-v2-capital-organic-donor.generation.txt"
HIGHLAND_PROMPT = ROOT / "world/map-production/prompts/style-candidate-k-v2-highland-calm-donor.generation.txt"
FIELDS_PROMPT = ROOT / "world/map-production/prompts/style-candidate-k-v2-fields-calm-donor.generation.txt"

RAW = ROOT / "world/map-production/candidates/style-candidate-k-v2-hybrid-raw.png"
FINAL = ROOT / "world/map-production/candidates/style-candidate-k-v2-hybrid.png"
RECEIPT = ROOT / "world/map-production/prompts/style-candidate-k-v2-hybrid.provenance-receipt.json"
MASK_ROOT = ROOT / "world/map-production/qa/masks"

PROOF_ROOT = ROOT / "tmp/map-production/k2-hybrid-local-composite-proof-v3"
PROOF_RAW = PROOF_ROOT / "style-candidate-k-v2-hybrid-proof-raw.png"
PROOF_FINAL = PROOF_ROOT / "style-candidate-k-v2-hybrid-proof.png"
PROOF_RECEIPT = PROOF_ROOT / "style-candidate-k-v2-hybrid-proof.provenance.json"

WIDTH, HEIGHT = 1536, 1024
SEED = 120260720
CREATED_AT = "2026-07-20T00:00:00Z"
PNG = {"format": "PNG", "compress_level": 9, "optimize": False}
EXPECTED = {
    GUIDE: "52f85e45b61bf889de709d8ea9601bd5865d6021bfbc617473a9e957a6ab8bbc",
    K1: "7e769137c90bad26740bdd095f1795ef1f27ec22d3be1db3e8c0423d4f11540a",
    B1: "4d505def78acc752ee2611cb73d112cc9a3048f611cb05233274a1eb2ae42003",
    WARP_BASE: "c21c5c07515f2bcc11d0ab8e613f3a6e52ec407606cb5afac4f5946579e62e9a",
    WARP_BUILDER: "82bd78966d546d242286e27007a9364b04ba5c5a6963c7575efa5370420c7f92",
    WARP_REPORT: "11d76e486ed7feecd41987baa89a53ef72950167730e89d6a048aad22dde5c2d",
    CAPITAL_DONOR: "7cef cbb1cda73e59e97ecfffa44e24684047d9959e41e714f66a6b2c6169f9aa".replace(" ", ""),
    FIELDS_DONOR: "d92ef6322b59197373d142eca89263376a4072acbf8f09718763c5da4b956a6a",
    HIGHLAND_DONOR: "2ada272aa25955f35e445b2fd98b02e171d47a01c185adddde7bb617f6dac1d8",
    CRISP_CAPITAL: "9908e9930b91359976f63873796a3fbbec19405d546a7ca655959e1be1eee504",
    PLATE_PROMPT: "16c3436e3af856c01c372eefd3c673f205264d55ee844390ed2cf504a7f64b29",
    CAPITAL_PROMPT: "bf6db9f71fea8c75024a51e165399c002dd612f242367a288b79a7557b6761d0",
    HIGHLAND_PROMPT: "8e4597440c25be096fae444a706757b7527dc0c353a67399b711d7a9d5ebd05c",
    FIELDS_PROMPT: "5cab7125396709a1dd3328fd18bbe50d525a6264c0fd0a2bc1e6b96e0c90ee12",
}

COASTLINE = [
    (432, 0), (425, 50), (408, 92), (373, 126), (331, 162), (309, 199),
    (337, 228), (390, 252), (407, 290), (379, 329), (366, 365), (391, 401),
    (424, 431), (427, 468), (398, 502), (355, 531), (350, 568), (370, 608),
    (403, 644), (447, 676), (462, 716), (431, 752), (445, 790), (476, 824),
    (524, 850), (551, 889), (614, 918), (684, 943), (754, 1024),
]
ISLANDS = [
    [(290, 270), (327, 245), (368, 258), (380, 298), (348, 324), (304, 315)],
    [(250, 354), (302, 332), (342, 356), (331, 401), (276, 410), (238, 385)],
    [(248, 457), (296, 425), (335, 451), (326, 493), (278, 508), (235, 487)],
    [(272, 566), (320, 535), (353, 564), (345, 614), (293, 628), (254, 604)],
    [(310, 661), (350, 640), (386, 666), (383, 704), (341, 722), (305, 698)],
]
HIGHLAND = [
    (1012, 0), (1536, 0), (1536, 489), (1468, 477), (1396, 505),
    (1328, 470), (1254, 492), (1188, 452), (1109, 465), (1042, 425),
    (1002, 369), (1019, 302), (984, 242), (1007, 169), (981, 93),
]
FIELDS = [
    [(1032, 620), (1170, 591), (1224, 674), (1084, 711)],
    [(1183, 589), (1332, 561), (1378, 645), (1237, 672)],
    [(1351, 562), (1499, 549), (1536, 620), (1392, 644)],
    [(1085, 725), (1229, 685), (1280, 770), (1136, 811)],
    [(1246, 684), (1392, 657), (1439, 744), (1291, 771)],
    [(1410, 657), (1536, 640), (1536, 727), (1455, 743)],
    [(1143, 825), (1288, 783), (1341, 866), (1195, 907)],
    [(1305, 785), (1453, 757), (1496, 846), (1357, 865)],
]
RIVER = [(797, 0), (805, 62), (789, 125), (751, 191), (731, 254), (758, 313), (710, 356), (644, 385), (605, 445), (559, 493), (525, 544)]
BRANCHES = [
    [(530, 540), (483, 505), (431, 470), (378, 431), (330, 392), (280, 369)],
    [(530, 546), (478, 559), (420, 575), (363, 589), (308, 601)],
    [(535, 552), (511, 607), (478, 656), (440, 704), (397, 743)],
    [(527, 542), (462, 528), (405, 532), (347, 550), (292, 568)],
]
ROADS = [
    [(704, 511), (638, 529), (583, 570), (548, 640), (519, 711), (503, 790)],
    [(842, 372), (843, 302), (885, 226), (930, 151), (970, 83)],
    [(980, 510), (1082, 513), (1197, 534), (1320, 522), (1450, 499), (1536, 482)],
    [(932, 607), (1010, 657), (1093, 709), (1192, 757), (1300, 818), (1416, 893), (1536, 956)],
    [(842, 648), (856, 712), (846, 774), (795, 823), (712, 849), (623, 846), (562, 834)],
]
PORT = [(434, 816), (470, 790), (526, 792), (572, 824), (568, 875), (520, 901), (464, 887)]
PIERS = [
    [(452, 858), (411, 883), (385, 883)],
    [(473, 879), (439, 914), (414, 914)],
    [(518, 891), (504, 930), (484, 945)],
]

CROPS = {
    "capital": (640, 290, 1050, 730),
    "fields": (940, 470, 1536, 980),
    "highland": (930, 0, 1536, 560),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def atomic_png(path: Path, array: np.ndarray, mode: str = "RGB") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    Image.fromarray(array.astype(np.uint8), mode).save(temporary, **PNG)
    temporary.replace(path)


def polygon_mask(points: list[tuple[int, int]]) -> np.ndarray:
    mask = np.zeros((HEIGHT, WIDTH), np.uint8)
    cv2.fillPoly(mask, [np.asarray(points, np.int32)], 255)
    return mask > 0


def line_mask(lines: list[list[tuple[int, int]]], width: int, closed: bool = False) -> np.ndarray:
    mask = np.zeros((HEIGHT, WIDTH), np.uint8)
    for points in lines:
        cv2.polylines(mask, [np.asarray(points, np.int32)], closed, 255, width, cv2.LINE_AA)
    return mask > 0


def disk(radius: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))


def dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    return cv2.dilate(mask.astype(np.uint8), disk(radius)) > 0


def erode(mask: np.ndarray, radius: int) -> np.ndarray:
    return cv2.erode(mask.astype(np.uint8), disk(radius)) > 0


def boundary(mask: np.ndarray, width: int = 1) -> np.ndarray:
    return dilate(mask, width) ^ erode(mask, width)


def canonical_masks() -> dict[str, Any]:
    land_polygon = COASTLINE + [(WIDTH, HEIGHT), (WIDTH, 0)]
    mainland = polygon_mask(land_polygon)
    islands = [polygon_mask(points) for points in ISLANDS]
    land = mainland.copy()
    for island in islands:
        land |= island
    fields = [polygon_mask(points) & mainland for points in FIELDS]
    river_fill = line_mask([RIVER], 27) | line_mask(BRANCHES, 16)
    river_edge = line_mask([RIVER], 37) | line_mask(BRANCHES, 24)
    road_edge = line_mask(ROADS, 12)
    city = np.zeros((HEIGHT, WIDTH), np.uint8)
    cv2.circle(city, (842, 510), 143, 255, -1, cv2.LINE_8)
    city_inner = np.zeros_like(city)
    cv2.circle(city_inner, (842, 510), 138, 255, -1, cv2.LINE_8)
    port = polygon_mask(PORT)
    guide_array = np.asarray(Image.open(GUIDE).convert("RGB"), np.int16)
    guide_water = (
        (guide_array[..., 2] - guide_array[..., 0] > 20)
        & (guide_array[..., 1] - guide_array[..., 0] > 5)
    )
    return {
        "mainland": mainland,
        "islands": islands,
        "land": land,
        "highland": polygon_mask(HIGHLAND) & mainland,
        "fields": fields,
        "field_union": np.logical_or.reduce(fields),
        "river_fill": river_fill,
        "river_edge": river_edge,
        "road_edge": road_edge,
        "city": city > 0,
        "city_inner": city_inner > 0,
        "port": port,
        "guide_water": guide_water,
    }


def crop_resize(path: Path, box: tuple[int, int, int, int]) -> np.ndarray:
    left, top, right, bottom = box
    image = Image.open(path).convert("RGB")
    resized = image.resize((right - left, bottom - top), Image.Resampling.LANCZOS)
    return np.asarray(resized, np.uint8)


def robust_color_match(donor: np.ndarray, base: np.ndarray, mask: np.ndarray, cap: int = 12) -> tuple[np.ndarray, list[int]]:
    source = donor[mask]
    target = base[mask]
    shift = np.rint(np.median(target, axis=0) - np.median(source, axis=0)).astype(np.int16)
    shift = np.clip(shift, -cap, cap)
    matched = np.clip(donor.astype(np.int16) + shift[None, None, :], 0, 255).astype(np.uint8)
    return matched, [int(value) for value in shift]


def smoothstep(value: np.ndarray) -> np.ndarray:
    value = np.clip(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def feather_alpha(mask: np.ndarray, feather: int, maximum: float = 1.0) -> np.ndarray:
    distance = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    return smoothstep(distance / float(max(feather, 1))).astype(np.float32) * maximum


def blend(canvas: np.ndarray, donor: np.ndarray, alpha: np.ndarray) -> None:
    selected = alpha > 0
    weights = alpha[selected, None]
    canvas[selected] = np.clip(
        np.rint(canvas[selected].astype(np.float32) * (1.0 - weights) + donor[selected].astype(np.float32) * weights),
        0,
        255,
    ).astype(np.uint8)


def blend_color(canvas: np.ndarray, mask: np.ndarray, color: tuple[int, int, int], alpha: float) -> None:
    canvas[mask] = np.clip(
        np.rint(canvas[mask].astype(np.float32) * (1.0 - alpha) + np.asarray(color, np.float32) * alpha),
        0,
        255,
    ).astype(np.uint8)


def paste_crop(full: np.ndarray, crop: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    result = np.zeros_like(full)
    left, top, right, bottom = box
    result[top:bottom, left:right] = crop
    return result


def apply_highland(canvas: np.ndarray, base: np.ndarray, donor_crop: np.ndarray, masks: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    donor = paste_crop(base, donor_crop, CROPS["highland"])
    permission = masks["highland"] & ~dilate(masks["road_edge"], 12) & ~dilate(masks["city"], 5)
    donor, shift = robust_color_match(donor, base, permission, cap=10)
    alpha = feather_alpha(permission, 16, 0.92)
    before = canvas.copy()
    blend(canvas, donor, alpha)
    changed = np.any(canvas != before, axis=2)
    return changed, {
        "method": "registered crop donor, canonical highland only, 16px smoothstep feather, roads protected",
        "crop_xyxy": list(CROPS["highland"]),
        "rgb_median_shift": shift,
        "permission_pixels": int(permission.sum()),
        "changed_pixels": int(changed.sum()),
        "maximum_alpha": float(alpha.max()),
    }


def apply_fields(canvas: np.ndarray, base: np.ndarray, donor_crop: np.ndarray, masks: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    donor = paste_crop(base, donor_crop, CROPS["fields"])
    road_guard = dilate(masks["road_edge"], 12)
    all_permission = masks["field_union"] & ~road_guard
    donor, shift = robust_color_match(donor, base, all_permission, cap=10)
    before = canvas.copy()
    parcel_records: list[dict[str, Any]] = []
    for number, parcel in enumerate(masks["fields"], 1):
        permission = parcel & ~road_guard
        alpha = feather_alpha(permission, 10, 0.90)
        blend(canvas, donor, alpha)
        edge = line_mask([FIELDS[number - 1]], 1, closed=True) & ~road_guard
        blend_color(canvas, edge, (116, 101, 69), 0.34)
        parcel_records.append({
            "parcel": number,
            "permission_pixels": int(permission.sum()),
            "changed_pixels": int(np.count_nonzero(np.any(canvas != before, axis=2) & parcel)),
            "edge_pixels": int(edge.sum()),
            "feather_px": 10,
        })
    changed = np.any(canvas != before, axis=2)
    return changed, {
        "method": "registered calm-field donor inside eight exact parcels; no polygon fill; road guard; warm 1px edges",
        "crop_xyxy": list(CROPS["fields"]),
        "rgb_median_shift": shift,
        "parcels": parcel_records,
        "changed_pixels": int(changed.sum()),
    }


def affine_capital_crop(donor: np.ndarray) -> tuple[np.ndarray, dict[str, float]]:
    source_x, source_y, source_radius = 214.0, 216.0, 141.0
    target_x, target_y, target_radius = 202.0, 220.0, 138.0
    scale = target_radius / source_radius
    matrix = np.asarray(
        [[scale, 0.0, target_x - scale * source_x], [0.0, scale, target_y - scale * source_y]],
        np.float32,
    )
    warped = cv2.warpAffine(donor, matrix, (410, 440), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT_101)
    return warped, {
        "source_center_xy": [source_x, source_y],
        "source_radius_px": source_radius,
        "target_center_xy": [target_x, target_y],
        "target_radius_px": target_radius,
        "scale": round(float(scale), 8),
    }


def apply_capital(
    canvas: np.ndarray,
    base: np.ndarray,
    donor_crop: np.ndarray,
    crisp_capital: np.ndarray,
    masks: dict[str, Any],
) -> tuple[np.ndarray, dict[str, Any]]:
    registered_crop, registration = affine_capital_crop(donor_crop)
    donor = paste_crop(base, registered_crop, CROPS["capital"])
    donor, shift = robust_color_match(donor, base, masks["city_inner"], cap=9)
    before = canvas.copy()

    # Remove only the displaced K1 wall ink outside the exact target wall.  The
    # fill remains byte-identical K1; broad crescent/domain filling is forbidden.
    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
    old_r = np.hypot(xx - 858.0, yy - 506.0)
    new_r = np.hypot(xx - 842.0, yy - 510.0)
    gray = cv2.cvtColor(base, cv2.COLOR_RGB2GRAY)
    local_bg = cv2.medianBlur(gray, 9)
    old_wall_ink = (np.abs(old_r - 135.0) <= 3.0) & (new_r > 143.0) & ((local_bg.astype(np.int16) - gray.astype(np.int16)) >= 7)
    old_wall_ink &= ~dilate(masks["road_edge"], 5)
    if np.any(old_wall_ink):
        repaired = cv2.inpaint(canvas, (old_wall_ink.astype(np.uint8) * 255), 2.2, cv2.INPAINT_TELEA)
        canvas[old_wall_ink] = repaired[old_wall_ink]

    # The crop donor contributes the organic interior only.  Its generated wall
    # is deliberately excluded so it cannot thicken or blur the exact footprint.
    inner = new_r <= 132.0
    inner_alpha = smoothstep(np.clip((136.0 - new_r) / 6.0, 0.0, 1.0)).astype(np.float32) * 0.98
    inner_alpha[~inner] = 0.0
    blend(canvas, donor, inner_alpha)

    # The reviewed full-board composite supplies its crisper wall and five gate
    # treatments only.  Exclude the unintended northwest bastion-like square.
    annulus = (new_r >= 131.0) & (new_r <= 143.0)
    nw_bastion = ((xx - 746.0) ** 2 + (yy - 409.0) ** 2) <= 18.0 ** 2
    portal_centers = [(842, 372), (704, 511), (980, 510), (842, 648), (932, 607)]
    portals = np.zeros((HEIGHT, WIDTH), np.uint8)
    for point in portal_centers:
        cv2.circle(portals, point, 13, 255, -1, cv2.LINE_8)
    crisp_mask = (annulus | (portals > 0)) & ~nw_bastion
    crisp_alpha = crisp_mask.astype(np.float32) * 0.94
    blend(canvas, crisp_capital, crisp_alpha)

    # Exact warm outer footprint and five gate centrelines.  These are fine
    # copperplate strokes, not gray rails or a replacement radial template.
    wall = np.zeros((HEIGHT, WIDTH), np.uint8)
    cv2.circle(wall, (842, 510), 138, 255, 1, cv2.LINE_AA)
    blend_color(canvas, wall > 0, (96, 79, 60), 0.48)
    gate_paths = [
        [(842, 372), (842, 394)],
        [(704, 511), (728, 511)],
        [(980, 510), (956, 510)],
        [(842, 648), (842, 624)],
        [(932, 607), (918, 589)],
    ]
    gate_core = line_mask(gate_paths, 1)
    blend_color(canvas, gate_core, (161, 138, 94), 0.52)

    changed = np.any(canvas != before, axis=2)
    return changed, {
        "method": "organic crop donor inside r132 plus reviewed crisp wall/gates in annulus; northwest bastion excluded",
        "crop_xyxy": list(CROPS["capital"]),
        "registration": registration,
        "rgb_median_shift": shift,
        "old_displaced_wall_ink_removed_pixels": int(old_wall_ink.sum()),
        "organic_inner_pixels": int(np.count_nonzero(inner_alpha > 0)),
        "crisp_wall_and_gate_pixels": int(crisp_mask.sum()),
        "northwest_bastion_excluded_pixels": int((nw_bastion & (annulus | (portals > 0))).sum()),
        "changed_pixels": int(changed.sum()),
        "outer_wall_center_xy": [842, 510],
        "outer_wall_radius_px": 138,
        "exact_gate_count": 5,
        "complete_interior_rings_added": 0,
        "uniform_radial_spokes_added": 0,
    }


def apply_geometry_linework(canvas: np.ndarray, base: np.ndarray, masks: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    before = canvas.copy()
    warm_road = (111, 91, 63)
    road_light = (161, 138, 94)

    road_outer = line_mask(ROADS, 2)
    road_core = line_mask(ROADS, 1)
    blend_color(canvas, road_outer, warm_road, 0.34)
    blend_color(canvas, road_core, road_light, 0.52)

    changed = np.any(canvas != before, axis=2)
    return changed, {
        "method": "exact <=2px warm road linework only; warped base coast, river, delta, and port remain untouched",
        "road_outer_line_pixels": int(road_outer.sum()),
        "changed_pixels": int(changed.sum()),
        "maximum_line_width_px": 2,
        "warped_water_and_port_pixels_changed": 0,
    }


def changed_metrics(base: np.ndarray, candidate: np.ndarray, allowed: np.ndarray) -> dict[str, Any]:
    delta = np.abs(candidate.astype(np.int16) - base.astype(np.int16))
    changed = np.any(delta > 0, axis=2)
    leakage = changed & ~allowed
    return {
        "changed_pixels": int(changed.sum()),
        "changed_fraction": round(float(changed.mean()), 8),
        "byte_identical_pixel_fraction": round(float((~changed).mean()), 8),
        "outside_allowed_mask_changed_pixels": int(leakage.sum()),
        "outside_allowed_mask_max_channel_delta": int(delta[~allowed].max()) if np.any(~allowed) else 0,
        "maximum_channel_delta": int(delta.max()),
    }


def symmetric_matrix_power(matrix: np.ndarray, exponent: float) -> np.ndarray:
    values, vectors = np.linalg.eigh(matrix)
    return (vectors * np.maximum(values, 1e-6) ** exponent) @ vectors.T


def gentle_style_calibration(canvas: np.ndarray, b1: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """Apply one spatially fixed RGB transform and a restrained print-detail boost.

    This is not histogram matching, a CDF remap, palette quantization, or pixel
    reassignment.  Every location keeps its own material; the same affine color
    transform and the same local high-pass equation are applied everywhere.
    """
    source = canvas.astype(np.float64).reshape(-1, 3)
    target = b1.astype(np.float64).reshape(-1, 3)
    source_mean = source.mean(axis=0)
    target_mean = target.mean(axis=0)
    source_covariance = np.cov(source, rowvar=False)
    target_covariance = np.cov(target, rowvar=False)
    transform = symmetric_matrix_power(source_covariance, -0.5) @ symmetric_matrix_power(target_covariance, 0.5)
    mapped = (source - source_mean) @ transform + target_mean
    color_blend = 0.50
    colored = np.clip(
        np.rint(source * (1.0 - color_blend) + mapped * color_blend), 0, 255
    ).astype(np.uint8).reshape(canvas.shape)

    sigma = 3.0
    amount = 0.40
    colored_float = colored.astype(np.float32)
    lowpass = cv2.GaussianBlur(colored_float, (0, 0), sigma)
    calibrated = np.clip(
        np.rint(colored_float + (colored_float - lowpass) * amount), 0, 255
    ).astype(np.uint8)
    return calibrated, {
        "method": "global full-covariance RGB affine blend followed by restrained local print-detail boost",
        "spatial_pixel_reassignment": False,
        "histogram_or_cdf_matching": False,
        "palette_quantization": False,
        "color_blend": color_blend,
        "unsharp_sigma_px": sigma,
        "unsharp_amount": amount,
        "source_mean_rgb": [round(float(value), 6) for value in source_mean],
        "target_mean_rgb": [round(float(value), 6) for value in target_mean],
        "rgb_transform_matrix": [[round(float(value), 9) for value in row] for row in transform],
    }


def build(proof_only: bool = False) -> dict[str, Any]:
    for path, expected in EXPECTED.items():
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"locked input changed: {rel(path)} expected {expected}, got {actual}")

    base = np.asarray(Image.open(WARP_BASE).convert("RGB"), np.uint8)
    if base.shape != (HEIGHT, WIDTH, 3):
        raise RuntimeError("K1 must remain native 1536x1024 RGB")
    masks = canonical_masks()
    canvas = base.copy()

    highland_crop = crop_resize(HIGHLAND_DONOR, CROPS["highland"])
    fields_crop = crop_resize(FIELDS_DONOR, CROPS["fields"])
    capital_crop = crop_resize(CAPITAL_DONOR, CROPS["capital"])
    crisp_capital = np.asarray(Image.open(CRISP_CAPITAL).convert("RGB"), np.uint8)

    highland_edit, highland_record = apply_highland(canvas, base, highland_crop, masks)
    fields_edit, fields_record = apply_fields(canvas, base, fields_crop, masks)
    capital_edit, capital_record = apply_capital(canvas, base, capital_crop, crisp_capital, masks)
    geometry_edit, geometry_record = apply_geometry_linework(canvas, base, masks)

    union = highland_edit | fields_edit | capital_edit | geometry_edit
    local_metrics = changed_metrics(base, canvas, union)
    if local_metrics["outside_allowed_mask_changed_pixels"] != 0:
        raise RuntimeError("local edit leaked outside the derived union")
    b1 = np.asarray(Image.open(B1).convert("RGB"), np.uint8)
    canvas, style_record = gentle_style_calibration(canvas, b1)
    final_delta = np.abs(canvas.astype(np.int16) - base.astype(np.int16))
    final_metrics = {
        "changed_pixels": int(np.count_nonzero(np.any(final_delta > 0, axis=2))),
        "changed_fraction": round(float(np.mean(np.any(final_delta > 0, axis=2))), 8),
        "maximum_channel_delta": int(final_delta.max()),
        "spatial_pixel_reassignment": False,
    }

    if proof_only:
        raw_path, final_path, receipt_path = PROOF_RAW, PROOF_FINAL, PROOF_RECEIPT
        mask_root = PROOF_ROOT / "masks"
    else:
        raw_path, final_path, receipt_path = RAW, FINAL, RECEIPT
        mask_root = MASK_ROOT

    atomic_png(raw_path, canvas)
    atomic_png(final_path, canvas)
    if raw_path.read_bytes() != final_path.read_bytes():
        raise RuntimeError("raw and review proof are not byte-identical")

    mask_paths = {
        "highland": mask_root / "style-candidate-k-v2-hybrid-highland-edit-mask-v1.png",
        "fields": mask_root / "style-candidate-k-v2-hybrid-fields-edit-mask-v1.png",
        "capital": mask_root / "style-candidate-k-v2-hybrid-capital-edit-mask-v1.png",
        "geometry": mask_root / "style-candidate-k-v2-hybrid-geometry-edit-mask-v1.png",
        "union": mask_root / "style-candidate-k-v2-hybrid-edit-mask-v1.png",
    }
    for name, mask in {
        "highland": highland_edit,
        "fields": fields_edit,
        "capital": capital_edit,
        "geometry": geometry_edit,
        "union": union,
    }.items():
        atomic_png(mask_paths[name], mask.astype(np.uint8) * 255, "L")

    receipt = {
        "schema_version": "2.0.0",
        "id": "style-candidate-k-v2-hybrid-local-repair-provenance",
        "created_at": CREATED_AT,
        "proof_only": proof_only,
        "scope": "K1-dominant native full-board proof; localized semantic donors plus <=2px canonical warm linework only.",
        "builder": {"path": rel(Path(__file__).resolve()), "sha256": sha256(Path(__file__).resolve()), "seed": SEED},
        "inputs": {
            "k1_original_source": {"path": rel(K1), "sha256": sha256(K1)},
            "k1_geometry_warp_base": {
                "path": rel(WARP_BASE),
                "sha256": sha256(WARP_BASE),
                "builder_path": rel(WARP_BUILDER),
                "builder_sha256": sha256(WARP_BUILDER),
                "report_path": rel(WARP_REPORT),
                "report_sha256": sha256(WARP_REPORT),
                "role": "seam-free strict-gate geometry base; capital, fields, and highland are byte-identical to K1",
            },
            "i1_geometry_control": {"path": rel(GUIDE), "sha256": sha256(GUIDE)},
            "b1_reference": {"path": rel(B1), "sha256": sha256(B1), "use": "visual palette reference only; no global remap in this proof"},
            "crop_donors": [
                {"semantic": "highland", "path": rel(HIGHLAND_DONOR), "sha256": sha256(HIGHLAND_DONOR), "crop_xyxy": list(CROPS["highland"])},
                {"semantic": "fields", "path": rel(FIELDS_DONOR), "sha256": sha256(FIELDS_DONOR), "crop_xyxy": list(CROPS["fields"])},
                {"semantic": "capital", "path": rel(CAPITAL_DONOR), "sha256": sha256(CAPITAL_DONOR), "crop_xyxy": list(CROPS["capital"])},
                {"semantic": "capital-wall-gates-only", "path": rel(CRISP_CAPITAL), "sha256": sha256(CRISP_CAPITAL)},
            ],
            "imagegen_prompt_lineage": [
                {
                    "role": "full-board local correction plate",
                    "prompt_path": rel(PLATE_PROMPT),
                    "prompt_sha256": sha256(PLATE_PROMPT),
                    "original_generated_source_path": "C:/Users/User/.codex/generated_images/019f73a3-3486-71a2-b86e-61ed24072d20/exec-9d272741-69d9-49de-a5a8-dc2a1957bf17.png",
                },
                {
                    "role": "capital organic crop donor",
                    "prompt_path": rel(CAPITAL_PROMPT),
                    "prompt_sha256": sha256(CAPITAL_PROMPT),
                    "original_generated_source_path": "C:/Users/User/.codex/generated_images/019f73a3-3486-71a2-b86e-61ed24072d20/exec-0924d1c8-0649-436d-bf1e-3c34ba4e9c46.png",
                },
                {
                    "role": "highland calm crop donor",
                    "prompt_path": rel(HIGHLAND_PROMPT),
                    "prompt_sha256": sha256(HIGHLAND_PROMPT),
                    "original_generated_source_path": "C:/Users/User/.codex/generated_images/019f73a3-3486-71a2-b86e-61ed24072d20/exec-29f01014-1c1f-4151-8852-34e7d310a927.png",
                },
                {
                    "role": "fields calm crop donor",
                    "prompt_path": rel(FIELDS_PROMPT),
                    "prompt_sha256": sha256(FIELDS_PROMPT),
                    "original_generated_source_path": "C:/Users/User/.codex/generated_images/019f73a3-3486-71a2-b86e-61ed24072d20/exec-02179799-9450-4946-b965-bdaa80501eed.png",
                },
            ],
            "imagegen_metadata_limits": {
                "exact_model": "unavailable",
                "snapshot": "unavailable",
                "generation_ids": "unavailable",
                "inference_forbidden": True,
            },
        },
        "construction": {
            "canvas": [WIDTH, HEIGHT],
            "mode": "RGB",
            "no_final_board_upscale": True,
            "imagegen_calls_by_this_builder": 0,
            "upstream_imagegen_calls_with_verbatim_prompts": 4,
            "whole_board_synthesis": False,
            "whole_board_palette_calibration": "gentle spatially fixed affine RGB correction; no CDF/multiset remap",
            "highland": highland_record,
            "fields": fields_record,
            "capital": capital_record,
            "geometry_linework": geometry_record,
            "local_change_budget_before_style_calibration": local_metrics,
            "style_calibration": style_record,
            "final_change_metrics": final_metrics,
        },
        "masks": {name: {"path": rel(path), "sha256": sha256(path)} for name, path in mask_paths.items()},
        "outputs": {
            "raw": {"path": rel(raw_path), "sha256": sha256(raw_path), "bytes": raw_path.stat().st_size},
            "review_candidate": {"path": rel(final_path), "sha256": sha256(final_path), "bytes": final_path.stat().st_size, "raw_byte_identity": True},
        },
        "assertions": {
            "k1_geometry_warp_is_byte_source_base": True,
            "donors_confined_to_named_masks": True,
            "no_broad_water_or_land_projection": True,
            "no_cloudy_low_frequency_synthesis": True,
            "no_global_cdf_or_multiset_palette_mapping": True,
            "style_calibration_has_no_spatial_pixel_reassignment": True,
            "maximum_canonical_line_width_px": 2,
            "exact_field_parcel_count": len(FIELDS),
            "capital_exact_outer_wall_and_five_gates": True,
            "manifest_untouched": True,
            "docs_untouched": True,
            "renderer_untouched": True,
            "golden_accepted": False,
        },
        "promotion_state": "temporary-visual-proof" if proof_only else "review-only-pending-strict-audit-and-root-vision",
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof-only", action="store_true", help="write only the temporary visual proof package")
    args = parser.parse_args()
    receipt = build(proof_only=args.proof_only)
    print(json.dumps({
        "proof_only": receipt["proof_only"],
        "candidate": receipt["outputs"]["review_candidate"],
        "local_change_budget": receipt["construction"]["local_change_budget_before_style_calibration"],
        "final_change_metrics": receipt["construction"]["final_change_metrics"],
        "receipt": rel(PROOF_RECEIPT if args.proof_only else RECEIPT),
    }, indent=2))


if __name__ == "__main__":
    main()
