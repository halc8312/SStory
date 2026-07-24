#!/usr/bin/env python3
"""Prepare or build a fail-closed, temporary-only K3 semantic-cleanup proof.

The default action derives the exact permission/protection masks and emits no
raster. ``--temporary-proof`` may write review evidence below ``tmp/`` from the
locked K2 source and locked donors. Persistent K3 candidate paths stay disabled
until a later root authorization turn.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "world/map-production/candidates/style-candidate-k-v2-hybrid.png"
SPEC = ROOT / "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/spec.json"
PREFLIGHT_ROOT = ROOT / "tmp/map-production/k3-semantic-cleanup-preflight-v1"
TEMP_PROOF_ROOT = ROOT / "tmp/map-production/k3-semantic-cleanup-proof-v18"
TEMP_RAW = TEMP_PROOF_ROOT / "style-candidate-k-v3-semantic-cleanup-proof-v18-raw.png"
TEMP_FINAL = TEMP_PROOF_ROOT / "style-candidate-k-v3-semantic-cleanup-proof-v18.png"
TEMP_RECEIPT = TEMP_PROOF_ROOT / "style-candidate-k-v3-semantic-cleanup-proof-v18.provenance-receipt.json"
FIXTURE_ROOT = ROOT / "world/map-production/qa/fixtures/k3"
V3_FOREST_PROOF = FIXTURE_ROOT / "style-candidate-k-v3-semantic-cleanup-proof-v3.png"
EXPECTED_V3_FOREST_PROOF = "808922469b8e0fd9dafec0c71053867daf60498b60d53b5262c1acbbde2c5fe3"
V10_PROOF = FIXTURE_ROOT / "style-candidate-k-v3-semantic-cleanup-proof-v10.png"
EXPECTED_V10_PROOF = "d1c835e62ec7e9c2f7f42709aa1600ee42c0ddcc98f02d41daf3a1f1449feb24"
V17_PROOF = FIXTURE_ROOT / "style-candidate-k-v3-semantic-cleanup-proof-v17.png"
EXPECTED_V17_PROOF = "9e11125b30f4849ee23c3cb4c0a69ab070ff53401b419bc5699529ace8cd573c"
V18_REFERENCE = ROOT / "world/map-production/style-assets/k3-v18-reconstruction-base.png"
EXPECTED_V18_REFERENCE = "013320af2f3296200a7d0b179e3a495f1e7905462213a6c645d85669dec02882"
RAW = ROOT / "world/map-production/candidates/style-candidate-k-v3-semantic-cleanup-raw.png"
FINAL = ROOT / "world/map-production/candidates/style-candidate-k-v3-semantic-cleanup.png"
RECEIPT = ROOT / "world/map-production/prompts/style-candidate-k-v3-semantic-cleanup.provenance-receipt.json"
AUDIT = ROOT / "world/map-production/qa/automated/style-candidate-k-v3-semantic-cleanup.json"

EXPECTED_SOURCE = "25b8d6211d1f2970cd59af363c521429863c340780d182253d161a951ed9eb92"
WIDTH, HEIGHT = 1536, 1024
PNG = {"format": "PNG", "compress_level": 9, "optimize": False}
FOREST_TEXTURE_SOURCE_CROP = (200, 0, 1305, 675)
FOREST_TEXTURE_TARGET_CROP = (300, 0, 1020, 440)
FOREST_SEED = 103051
HIGHLAND_TEXTURE_SOURCE_CROP = (220, 50, 1160, 919)
HIGHLAND_SEED = 103081
FIELDS_SEED = 103111
HIGHLAND_ALPHA_LOCKED_BOUNDARY_PX = 2.0
HIGHLAND_ALPHA_FULL_BY_PX = 5.0

FOREST = [
    (438, 0), (956, 0), (940, 78), (975, 128), (948, 194), (912, 233),
    (929, 301), (875, 353), (801, 345), (746, 372), (675, 351), (618, 369),
    (548, 337), (483, 346), (422, 300), (405, 240), (382, 186), (409, 115),
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
AGRICULTURAL_APPROACH_CAP = [(1004, 682), (1036, 652), (1100, 688), (1086, 736)]
AGRICULTURAL_APPROACH_LOCAL_DARK_DELTA = 24.0
AGRICULTURAL_APPROACH_MIN_COMPONENT_AREA = 12
AGRICULTURAL_APPROACH_DILATION_PX = 5
AGRICULTURAL_OUTER_FEATHER_PX = 16.0
AGRICULTURAL_APPROACH_FEATHER_PX = 4.0
HIGHLAND_MARK_SPAN_RGB = (40.0, 35.0, 24.0)
HIGHLAND_MARK_LOCAL_DARK_THRESHOLD = 30.0
HIGHLAND_MARK_MIN_COMPONENT_AREA = 12
HIGHLAND_BACKGROUND_DARK_CAP = 12.0
HIGHLAND_PAPER_GRAIN_CAP = 12.0
SOIL_LOWPASS_SIGMA_PX = 10.0
SOIL_GRAIN_CAP = 2.0
FIELD_SOURCE_DARK_TAIL_THRESHOLD = 24.0
FIELD_STRICT_INTERIOR_EROSION_PX = 12
FIELD_BANDPASS_INNER_SIGMA_PX = 0.0
FIELD_BANDPASS_OUTER_SIGMA_PX = 12.0
FIELD_BANDPASS_GAIN_RGB = (0.25, 0.20625, 0.14375)
FIELD_BANDPASS_TONE_GAMMA = 0.8
FIELD_BANDPASS_TONE_PIVOT = 8.0
FIELD_MEDIAN_TINT_RGB = (0.0, 0.0, 0.0)
FIELD_FLECK_DOG_INNER_SIGMA_PX = 0.6
FIELD_FLECK_DOG_OUTER_SIGMA_PX = 3.0
FIELD_FLECK_DARK_THRESHOLD = -14.0
FIELD_FLECK_COMPONENT_AREA_RANGE = (2, 24)
FIELD_FLECK_MAXIMUM_ASPECT_RATIO = 3.0
FIELD_FLECK_MAXIMUM_SPAN_PX = 8
FIELD_FLECK_DARKEN_RGB = (12.0, 10.8, 7.2)
FIELD_FLECK_MAXIMUM_DENSITY = 0.025
FIELD_FOUR_PIXEL_LATTICE_RATIO_LIMIT = 1.35
FIELD_FOUR_PIXEL_CHECKER_MEAN_LIMIT = 0.25


class K3BuildError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def disk(radius: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))


def dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    return cv2.dilate(mask.astype(np.uint8), disk(radius)) > 0


def erode(mask: np.ndarray, radius: int) -> np.ndarray:
    return cv2.erode(mask.astype(np.uint8), disk(radius)) > 0


def polygon_mask(points: list[tuple[int, int]]) -> np.ndarray:
    mask = np.zeros((HEIGHT, WIDTH), np.uint8)
    cv2.fillPoly(mask, [np.asarray(points, np.int32)], 255)
    return mask > 0


def line_mask(lines: list[list[tuple[int, int]]], width: int, closed: bool = False) -> np.ndarray:
    mask = np.zeros((HEIGHT, WIDTH), np.uint8)
    for points in lines:
        cv2.polylines(mask, [np.asarray(points, np.int32)], closed, 255, width, cv2.LINE_AA)
    return mask > 0


def exact_line_mask(
    lines: list[list[tuple[int, int]]], width: int, closed: bool = False
) -> np.ndarray:
    mask = np.zeros((HEIGHT, WIDTH), np.uint8)
    for points in lines:
        cv2.polylines(mask, [np.asarray(points, np.int32)], closed, 255, width, cv2.LINE_8)
    return mask > 0


def derive_agricultural_approach_cleanup(
    agricultural_hull: np.ndarray,
    source_image: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Select only inherited K2 dark-row components west of the field hull."""
    source = validate_source() if source_image is None else source_image
    if source.shape != (HEIGHT, WIDTH, 3) or source.dtype != np.uint8:
        raise K3BuildError("bound K2 source snapshot has the wrong raster contract")
    gray = cv2.cvtColor(source, cv2.COLOR_RGB2GRAY).astype(np.float32)
    cap_only = polygon_mask(AGRICULTURAL_APPROACH_CAP) & ~agricultural_hull

    # Gaussian context is used only to derive a deterministic permission mask;
    # no blurred pixels are ever copied into the proof raster.
    local_background = cv2.GaussianBlur(gray, (0, 0), 5.0)
    seeds = cap_only & (
        (local_background - gray) >= AGRICULTURAL_APPROACH_LOCAL_DARK_DELTA
    )
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        seeds.astype(np.uint8), 8
    )
    kept_ids = [
        index
        for index in range(1, count)
        if int(stats[index, cv2.CC_STAT_AREA])
        >= AGRICULTURAL_APPROACH_MIN_COMPONENT_AREA
    ]
    retained = np.isin(labels, kept_ids) if kept_ids else np.zeros_like(seeds)
    cleanup = dilate(retained, AGRICULTURAL_APPROACH_DILATION_PX) & cap_only
    if not np.any(cleanup):
        raise K3BuildError("source-derived agricultural approach cleanup is empty")
    return cleanup, retained, {
        "source": relative(SOURCE),
        "source_sha256": EXPECTED_SOURCE,
        "legacy_search_cap_xy": [list(point) for point in AGRICULTURAL_APPROACH_CAP],
        "legacy_search_cap_outside_hull_pixels": int(cap_only.sum()),
        "detector": "K2 Gaussian-context minus exact grayscale, permission-mask derivation only",
        "local_context_sigma_px": 5.0,
        "minimum_local_dark_delta": AGRICULTURAL_APPROACH_LOCAL_DARK_DELTA,
        "minimum_connected_component_area": AGRICULTURAL_APPROACH_MIN_COMPONENT_AREA,
        "retained_connected_components": len(kept_ids),
        "retained_seed_pixels": int(retained.sum()),
        "cleanup_dilation_px": AGRICULTURAL_APPROACH_DILATION_PX,
        "cleanup_pixels": int(cleanup.sum()),
        "legacy_cap_pixels_not_recolored": int(np.count_nonzero(cap_only & ~cleanup)),
        "blurred_raster_pixels_used": False,
    }


def derive_masks(*, source_image: np.ndarray | None = None) -> dict[str, Any]:
    forest_shape = polygon_mask(FOREST)
    highland_shape = polygon_mask(HIGHLAND)
    field_shapes = [polygon_mask(points) for points in FIELDS]

    # Blind-B's repair contract is intentionally reconstructed from canonical
    # geometry rather than inherited from K2's earlier edit masks.
    coast_guard = dilate(line_mask([COASTLINE], 5), 12)
    island_guard = dilate(line_mask(ISLANDS, 5, closed=True), 12)
    water_guard = dilate(line_mask([RIVER], 37) | line_mask(BRANCHES, 24), 12)
    forest_highland_road_guard = line_mask(ROADS, 12)
    road_context = dilate(forest_highland_road_guard, 12)
    agricultural_exact_road_core = exact_line_mask(ROADS, 4)
    city = np.zeros((HEIGHT, WIDTH), np.uint8)
    cv2.circle(city, (842, 510), 143, 255, -1, cv2.LINE_8)
    city_guard = dilate(city > 0, 8)
    port_guard = dilate(polygon_mask(PORT) | line_mask(PIERS, 7), 12)
    canvas_guard = np.zeros((HEIGHT, WIDTH), bool)
    canvas_guard[:8, :] = True
    canvas_guard[-8:, :] = True
    canvas_guard[:, :8] = True
    canvas_guard[:, -8:] = True

    # Preserve only the exact 1-2px parcel-line core. Everything else inside
    # the agricultural block is eligible for semantic row removal.
    field_boundary_guard = exact_line_mask(FIELDS, 1, closed=True)
    forest_edit = (
        forest_shape
        & ~road_context & ~water_guard & ~coast_guard
        & ~city_guard & ~port_guard & ~canvas_guard
    )
    highland_edit = highland_shape & ~road_context & ~city_guard & ~canvas_guard
    field_legacy_edits = [
        shape & ~agricultural_exact_road_core & ~field_boundary_guard & ~canvas_guard
        for shape in field_shapes
    ]
    field_parcel_legacy_edit = np.logical_or.reduce(field_legacy_edits)
    field_edits = [
        erode(permission, FIELD_STRICT_INTERIOR_EROSION_PX)
        for permission in field_legacy_edits
    ]
    if any(not np.any(permission) for permission in field_edits):
        raise K3BuildError("v18 strict field-interior erosion emptied a parcel")
    field_parcel_edit = np.logical_or.reduce(field_edits)
    field_legacy_margin_scope = field_parcel_legacy_edit & ~field_parcel_edit
    field_vertices = np.asarray(
        [point for polygon in FIELDS for point in polygon], np.int32
    )
    field_hull = cv2.convexHull(field_vertices).reshape(-1, 2)
    agricultural_hull = polygon_mask([
        (int(point[0]), int(point[1])) for point in field_hull
    ])
    (
        agricultural_approach_cleanup,
        agricultural_approach_dark_components_raw,
        agricultural_approach_record,
    ) = (
        derive_agricultural_approach_cleanup(
            agricultural_hull, source_image=source_image
        )
    )
    agricultural_envelope = np.logical_or.reduce(field_shapes) | agricultural_approach_cleanup
    agricultural_corridor_envelope = (
        agricultural_envelope
        & ~agricultural_exact_road_core
        & ~field_boundary_guard
        & ~field_parcel_legacy_edit
        & ~city_guard & ~port_guard & ~water_guard & ~coast_guard
        & ~canvas_guard
    )
    field_channel_legacy_scope = (
        field_parcel_legacy_edit | agricultural_corridor_envelope
    )
    field_restore_scope = field_channel_legacy_scope & ~field_parcel_edit
    fields_edit = field_parcel_edit
    agricultural_approach_dark_components = (
        agricultural_approach_dark_components_raw & agricultural_corridor_envelope
    )
    agricultural_approach_record["eligible_component_pixels_inside_permission"] = int(
        agricultural_approach_dark_components.sum()
    )
    agricultural_approach_record["component_pixels_excluded_by_protected_cores"] = int(
        np.count_nonzero(
            agricultural_approach_dark_components_raw
            & ~agricultural_corridor_envelope
        )
    )
    edit_union = forest_edit | highland_edit | fields_edit
    protected_features = (
        coast_guard | island_guard | water_guard | agricultural_exact_road_core | city_guard
        | port_guard | field_boundary_guard | canvas_guard
    )
    outside_identity = ~edit_union
    labels = np.zeros((HEIGHT, WIDTH), np.uint8)
    for index, item in enumerate(field_edits, 1):
        labels[item] = index
    labels[agricultural_corridor_envelope] = 9
    return {
        "forest_shape": forest_shape,
        "highland_shape": highland_shape,
        "field_shapes": field_shapes,
        "forest_edit": forest_edit,
        "highland_edit": highland_edit,
        "field_edits": field_edits,
        "field_parcel_edit": field_parcel_edit,
        "field_legacy_edits": field_legacy_edits,
        "field_parcel_legacy_edit": field_parcel_legacy_edit,
        "field_legacy_margin_scope": field_legacy_margin_scope,
        "field_channel_legacy_scope": field_channel_legacy_scope,
        "field_restore_scope": field_restore_scope,
        "field_strict_interior_erosion_px": FIELD_STRICT_INTERIOR_EROSION_PX,
        "agricultural_hull": agricultural_hull,
        "agricultural_approach_cleanup": agricultural_approach_cleanup,
        "agricultural_approach_dark_components": agricultural_approach_dark_components,
        "agricultural_approach_dark_components_raw": agricultural_approach_dark_components_raw,
        "agricultural_approach_record": agricultural_approach_record,
        "agricultural_envelope": agricultural_envelope,
        "agricultural_corridor_envelope": agricultural_corridor_envelope,
        "fields_edit": fields_edit,
        "edit_union": edit_union,
        "protected_features": protected_features,
        "outside_identity": outside_identity,
        "field_labels": labels,
        "guards": {
            "coast": coast_guard,
            "islands": island_guard,
            "water": water_guard,
            "roads": agricultural_exact_road_core,
            "capital": city_guard,
            "port": port_guard,
            "field_boundaries": field_boundary_guard,
            "canvas": canvas_guard,
        },
        "permission_exclusions": {
            "forest_highland_road_context": road_context,
            "forest_highland_road_guard": forest_highland_road_guard,
            "field_exact_road_core": agricultural_exact_road_core,
        },
    }


def atomic_png(path: Path, array: np.ndarray, mode: str = "L") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    Image.fromarray(array.astype(np.uint8), mode).save(temporary, **PNG)
    temporary.replace(path)


def mask_artifact(path: Path, mask: np.ndarray) -> dict[str, Any]:
    atomic_png(path, mask.astype(np.uint8) * 255)
    return {"path": relative(path), "sha256": sha256(path), "pixels": int(mask.sum())}


def grayscale_artifact(path: Path, values: np.ndarray) -> dict[str, Any]:
    atomic_png(path, values.astype(np.uint8))
    return {
        "path": relative(path),
        "sha256": sha256(path),
        "nonzero_pixels": int(np.count_nonzero(values)),
        "maximum": int(np.max(values)),
    }


def load_spec() -> dict[str, Any]:
    value = json.loads(SPEC.read_text(encoding="utf-8"))
    if value.get("id") != "style-candidate-k-v3-semantic-cleanup":
        raise K3BuildError("K3 spec id mismatch")
    if value.get("source", {}).get("sha256") != EXPECTED_SOURCE:
        raise K3BuildError("K3 source lock mismatch in spec")
    calibration = value.get("style_calibration", {})
    if calibration.get("spatial_pixel_reassignment_forbidden") is not True:
        raise K3BuildError("K3 spec must forbid spatial pixel reassignment")
    if calibration.get("cdf_or_exact_multiset_remap_forbidden") is not True:
        raise K3BuildError("K3 spec must forbid CDF or exact-multiset remapping")
    return value


def validate_source() -> np.ndarray:
    if sha256(SOURCE) != EXPECTED_SOURCE:
        raise K3BuildError("exact rejected-evidence K2 source hash changed")
    source = np.asarray(Image.open(SOURCE).convert("RGB"), np.uint8)
    if source.shape != (HEIGHT, WIDTH, 3):
        raise K3BuildError("K3 source must be native 1536x1024 RGB")
    return source


def prepare(preflight_root: Path = PREFLIGHT_ROOT) -> dict[str, Any]:
    validate_source()
    spec = load_spec()
    masks = derive_masks()
    if np.any(masks["edit_union"] & masks["protected_features"]):
        raise K3BuildError("edit union overlaps a protected feature")
    if any(int(item.sum()) == 0 for item in masks["field_edits"]):
        raise K3BuildError("one or more field edit interiors are empty")

    mask_root = preflight_root / "masks"
    artifacts = {
        "forest_canonical": mask_artifact(mask_root / "style-candidate-k-v3-semantic-cleanup-forest-canonical-mask-v1.png", masks["forest_shape"]),
        "highland_canonical": mask_artifact(mask_root / "style-candidate-k-v3-semantic-cleanup-highland-canonical-mask-v1.png", masks["highland_shape"]),
        "forest_edit": mask_artifact(mask_root / "style-candidate-k-v3-semantic-cleanup-forest-edit-mask-v1.png", masks["forest_edit"]),
        "highland_edit": mask_artifact(mask_root / "style-candidate-k-v3-semantic-cleanup-highland-edit-mask-v1.png", masks["highland_edit"]),
        "fields_edit": mask_artifact(mask_root / "style-candidate-k-v3-semantic-cleanup-fields-edit-mask-v1.png", masks["fields_edit"]),
        "edit_union": mask_artifact(mask_root / "style-candidate-k-v3-semantic-cleanup-edit-mask-v1.png", masks["edit_union"]),
        "protected_features": mask_artifact(mask_root / "style-candidate-k-v3-semantic-cleanup-protected-mask-v1.png", masks["protected_features"]),
        "outside_identity": mask_artifact(mask_root / "style-candidate-k-v3-semantic-cleanup-outside-identity-mask-v1.png", masks["outside_identity"]),
    }
    label_path = mask_root / "style-candidate-k-v3-semantic-cleanup-field-labels-v1.png"
    atomic_png(label_path, masks["field_labels"])
    artifacts["field_labels"] = {
        "path": relative(label_path), "sha256": sha256(label_path),
        "labels": sorted(int(value) for value in np.unique(masks["field_labels"]) if value),
    }
    donor_ready: dict[str, bool] = {}
    for name, record in spec["donor_slots"].items():
        ready = bool(record.get("status") == "ready" and record.get("path") and record.get("sha256"))
        if ready:
            validate_donor_record(name, record)
        donor_ready[name] = ready
    crop_containment = {
        "forest": permission_outside_crop_pixels(masks["forest_edit"], spec["donor_slots"]["forest"]),
        "highland": permission_outside_crop_pixels(masks["highland_edit"], spec["donor_slots"]["highland"]),
        "fields": permission_outside_crop_pixels(masks["fields_edit"], spec["donor_slots"]["fields"]),
    }
    if any(crop_containment.values()):
        raise K3BuildError("one or more K3 permissions escape their locked registration crop")
    future_outputs = [RAW, FINAL, RECEIPT, AUDIT]
    report = {
        "schema_version": "1.0.0",
        "id": "style-candidate-k-v3-semantic-cleanup-preflight",
        "status": (
            "prepared-donors-locked-output-held"
            if all(donor_ready.values())
            else "prepared-awaiting-donors"
        ),
        "source": {"path": relative(SOURCE), "sha256": sha256(SOURCE)},
        "spec": {"path": relative(SPEC), "sha256": sha256(SPEC)},
        "mask_contract": {
            "forest_edit_pixels": int(masks["forest_edit"].sum()),
            "highland_edit_pixels": int(masks["highland_edit"].sum()),
            "field_edit_pixels": [int(item.sum()) for item in masks["field_edits"]],
            "field_parcel_count": len(masks["field_edits"]),
            "agricultural_corridor_envelope_pixels": int(
                masks["agricultural_corridor_envelope"].sum()
            ),
            "quiet_field_region_count": len(masks["field_edits"]) + 1,
            "edit_union_pixels": int(masks["edit_union"].sum()),
            "edit_union_fraction": round(float(masks["edit_union"].mean()), 8),
            "protected_overlap_pixels": int(np.count_nonzero(masks["edit_union"] & masks["protected_features"])),
            "outside_identity_pixels": int(masks["outside_identity"].sum()),
            "outside_identity_fraction": round(float(masks["outside_identity"].mean()), 8),
        },
        "guards": {name: int(mask.sum()) for name, mask in masks["guards"].items()},
        "donor_ready": donor_ready,
        "all_donors_ready": all(donor_ready.values()),
        "permission_outside_registration_crop_pixels": crop_containment,
        "candidate_output_authorized": bool(spec.get("output_authorized")),
        "future_outputs_exist": {relative(path): path.exists() for path in future_outputs},
        "candidate_emitted": False,
        "artifacts": artifacts,
        "semantic_thresholds": spec["semantic_targets"],
        "pre_style_invariants": {
            "outside_edit_union_must_be_byte_identical_to_k2": True,
            "protected_features_must_be_byte_identical_to_k2": True,
            "whole_image_style_calibration_runs_only_after_identity_gate": True,
        },
        "golden_accepted": False,
    }
    preflight_root.mkdir(parents=True, exist_ok=True)
    report_path = preflight_root / "style-candidate-k-v3-semantic-cleanup-preflight.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _repo_artifact(value: str) -> Path:
    path = (ROOT / value).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise K3BuildError(f"artifact escapes repository root: {value!r}") from exc
    return path


def validate_donor_record(name: str, record: dict[str, Any]) -> np.ndarray:
    if record.get("status") != "ready":
        raise K3BuildError(f"K3 donor slot is not ready: {name}")
    source_path = _repo_artifact(str(record.get("path", "")))
    if not source_path.is_file() or sha256(source_path) != record.get("sha256"):
        raise K3BuildError(f"donor missing or hash mismatch: {record.get('path')}")
    prompt_path = _repo_artifact(str(record.get("prompt_path", "")))
    if not prompt_path.is_file() or sha256(prompt_path) != record.get("prompt_sha256"):
        raise K3BuildError(f"donor prompt missing or hash mismatch: {record.get('prompt_path')}")
    with Image.open(source_path) as opened:
        opened.load()
        expected_size = tuple(int(value) for value in record.get("native_size", []))
        if opened.mode != "RGB" or opened.size != expected_size:
            raise K3BuildError(f"donor image contract mismatch: {name}")
        if opened.getbands() != ("R", "G", "B"):
            raise K3BuildError(f"donor carries alpha/transparency: {name}")
        if opened.info.get("transparency") is not None or opened.info.get("icc_profile"):
            raise K3BuildError(f"donor carries forbidden transparency/profile: {name}")
        return np.asarray(opened, np.uint8).copy()


def registration_crop(record: dict[str, Any]) -> tuple[int, int, int, int]:
    values = tuple(int(value) for value in record["registration_crop_xyxy"])
    if len(values) != 4:
        raise K3BuildError("registration crop must have four coordinates")
    left, top, right, bottom = values
    if not (0 <= left < right <= WIDTH and 0 <= top < bottom <= HEIGHT):
        raise K3BuildError(f"registration crop is outside the native canvas: {values}")
    return values


def permission_outside_crop_pixels(permission: np.ndarray, record: dict[str, Any]) -> int:
    left, top, right, bottom = registration_crop(record)
    crop = np.zeros((HEIGHT, WIDTH), bool)
    crop[top:bottom, left:right] = True
    return int(np.count_nonzero(permission & ~crop))


def donor_canvas(base: np.ndarray, record: dict[str, Any], source: np.ndarray) -> np.ndarray:
    left, top, right, bottom = registration_crop(record)
    resized = Image.fromarray(source, "RGB").resize(
        (right - left, bottom - top), Image.Resampling.LANCZOS
    )
    result = base.copy()
    result[top:bottom, left:right] = np.asarray(resized, np.uint8)
    return result


def robust_color_match(
    donor: np.ndarray,
    base: np.ndarray,
    permission: np.ndarray,
    cap: int = 6,
) -> tuple[np.ndarray, list[int]]:
    source = donor[permission]
    target = base[permission]
    shift = np.rint(np.median(target, axis=0) - np.median(source, axis=0)).astype(np.int16)
    shift = np.clip(shift, -cap, cap)
    matched = np.clip(donor.astype(np.int16) + shift[None, None, :], 0, 255).astype(np.uint8)
    return matched, [int(value) for value in shift]


def fractal_noise(
    rng: np.random.Generator,
    height: int,
    width: int,
    grids_hw: list[tuple[int, int]],
    weights: list[float],
) -> np.ndarray:
    layers = [
        cv2.resize(
            rng.random((rows, columns), dtype=np.float32),
            (width, height),
            interpolation=cv2.INTER_CUBIC,
        )
        for rows, columns in grids_hw
    ]
    combined = sum(weight * layer for weight, layer in zip(weights, layers))
    q05, q95 = np.quantile(combined, (0.05, 0.95))
    return np.clip(
        (combined - q05) / max(float(q95 - q05), 1e-6), 0.0, 1.0
    ).astype(np.float32)


def procedural_forest_canvas(
    base: np.ndarray,
    texture_source: np.ndarray,
    permission: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Register and attenuate Root-selected forest areal donor v3."""
    left, top, right, bottom = FOREST_TEXTURE_TARGET_CROP
    width, height = right - left, bottom - top
    source_crop = (0, 244, 1254, 1010)
    sx0, sy0, sx1, sy1 = source_crop
    donor_image = Image.fromarray(texture_source[sy0:sy1, sx0:sx1], "RGB").resize(
        (width, height), Image.Resampling.LANCZOS
    )
    donor = np.asarray(donor_image, np.uint8)
    gray = cv2.cvtColor(donor, cv2.COLOR_RGB2GRAY).astype(np.float32)
    q03, q97 = np.quantile(gray, (0.03, 0.97))
    tone = np.clip((gray - q03) / max(float(q97 - q03), 1e-6), 0.0, 1.0) ** 1.15
    dark = np.asarray((80, 76, 46), np.float32)
    light = np.asarray((126, 113, 76), np.float32)
    plate = dark[None, None, :] * (1.0 - tone[..., None]) + light[None, None, :] * tone[..., None]
    plate = np.clip(np.rint(plate), 0, 255).astype(np.uint8)

    canvas = base.copy()
    canvas[top:bottom, left:right] = plate
    strongest = tone <= 0.025
    neighbors = cv2.filter2D(strongest.astype(np.uint8), cv2.CV_16U, np.ones((3, 3), np.uint8))
    isolated = strongest & (neighbors <= 3)
    yy, xx = np.indices((height, width))
    sampled = isolated & (((xx * 73856093 + yy * 19349663) % 13) == 0)
    marks = np.zeros((HEIGHT, WIDTH), bool)
    marks[top:bottom, left:right] = sampled
    marks &= permission
    record = {
        "texture_authority": "forest-areal-v3",
        "texture_source_crop_xyxy": list(source_crop),
        "target_crop_xyxy": list(FOREST_TEXTURE_TARGET_CROP),
        "single_nonrepeating_global_crop": True,
        "post_resize_blur_applied": False,
        "luminance_quantiles": [round(float(q03), 6), round(float(q97), 6)],
        "tone_gamma": 1.15,
        "light_rgb": [126, 113, 76],
        "dark_rgb": [80, 76, 46],
        "contrast_attenuated": True,
        "semantic_mark_pixels_inside_permission": int(marks.sum()),
        "semantic_mark_sampling": "isolated strongest donor stipple sampled by fixed coordinate hash",
        "registered_imagegen_forest_used": True,
        "rejected_predecessors": [
            "forest-areal-v1: tangled curlicue microline masses",
            "procedural TEMP v1/v2: soft camouflage and airbrush-cloud reading",
        ],
    }
    return canvas, marks, record


def procedural_highland_canvas(
    base: np.ndarray,
    texture_source: np.ndarray,
    record: dict[str, Any],
    permission: np.ndarray,
) -> tuple[np.ndarray, list[int], dict[str, Any]]:
    left, top, right, bottom = registration_crop(record)
    width, height = right - left, bottom - top
    source_crop = (0, 47, 1254, 1206)
    sx0, sy0, sx1, sy1 = source_crop
    source = texture_source[sy0:sy1, sx0:sx1]
    donor = np.asarray(
        Image.fromarray(source, "RGB").resize((width, height), Image.Resampling.BOX),
        np.uint8,
    )
    gray = cv2.cvtColor(donor, cv2.COLOR_RGB2GRAY).astype(np.float32)
    local_context = cv2.GaussianBlur(gray, (0, 0), 8.0)
    local_dark = local_context - gray
    mark_seeds = local_dark >= HIGHLAND_MARK_LOCAL_DARK_THRESHOLD
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        mark_seeds.astype(np.uint8), 8
    )
    retained_ids = [
        index for index in range(1, count)
        if int(stats[index, cv2.CC_STAT_AREA]) >= HIGHLAND_MARK_MIN_COMPONENT_AREA
    ]
    marks = np.isin(labels, retained_ids) if retained_ids else np.zeros_like(mark_seeds)
    if not np.any(marks):
        raise K3BuildError("highland solid-mark selection is empty")
    mark_q99 = float(np.quantile(local_dark[marks], 0.99))
    mark_tone = np.clip(
        (local_dark - HIGHLAND_MARK_LOCAL_DARK_THRESHOLD)
        / max(mark_q99 - HIGHLAND_MARK_LOCAL_DARK_THRESHOLD, 1e-6),
        0.0,
        1.0,
    )
    mark_strength = np.where(marks, 0.75 + 0.25 * mark_tone, 0.0).astype(np.float32)

    # Start with exact local K2 color, cap only its inherited dark tail, then
    # add a bounded, sub-structural donor paper channel. Solid donor marks are
    # the only pixels receiving high contrast.
    base_gray = cv2.cvtColor(base, cv2.COLOR_RGB2GRAY)
    base_median = cv2.medianBlur(base_gray, 11).astype(np.float32)
    base_dark = base_median - base_gray.astype(np.float32)
    quiet_plate = base.astype(np.float32) + np.maximum(
        base_dark - HIGHLAND_BACKGROUND_DARK_CAP, 0.0
    )[..., None]
    broad_paper = (
        cv2.GaussianBlur(gray, (0, 0), 3.0)
        - cv2.GaussianBlur(gray, (0, 0), 18.0)
    )
    paper_scale = max(float(np.quantile(np.abs(broad_paper), 0.98)), 1e-6)
    paper = np.clip(
        broad_paper / paper_scale * HIGHLAND_PAPER_GRAIN_CAP,
        -HIGHLAND_PAPER_GRAIN_CAP,
        HIGHLAND_PAPER_GRAIN_CAP,
    )
    paper[marks] = 0.0
    tiny_grain = np.clip(
        gray - cv2.GaussianBlur(gray, (0, 0), 1.2), -2.0, 2.0
    )
    plate = quiet_plate[top:bottom, left:right].copy()
    plate += (paper + tiny_grain)[..., None] * np.asarray((1.0, 0.9, 0.7), np.float32)
    plate -= mark_strength[..., None] * np.asarray(HIGHLAND_MARK_SPAN_RGB, np.float32)
    canvas = base.copy()
    canvas[top:bottom, left:right] = np.clip(np.rint(plate), 0, 255).astype(np.uint8)
    full_marks = np.zeros((HEIGHT, WIDTH), bool)
    full_marks[top:bottom, left:right] = marks
    full_marks &= permission
    return canvas, [0, 0, 0], {
        "texture_authority": "highland-planar-v4",
        "texture_source_crop_xyxy": list(source_crop),
        "target_crop_xyxy": [left, top, right, bottom],
        "single_nonrepeating_global_crop": True,
        "resampling": "Pillow BOX area downsample",
        "solid_mark_detector": "Gaussian sigma=8 local-dark tail plus connected-component area",
        "solid_mark_local_dark_threshold": HIGHLAND_MARK_LOCAL_DARK_THRESHOLD,
        "solid_mark_minimum_component_area": HIGHLAND_MARK_MIN_COMPONENT_AREA,
        "solid_mark_connected_components": len(retained_ids),
        "solid_mark_pixels_inside_permission": int(full_marks.sum()),
        "solid_mark_span_rgb": list(HIGHLAND_MARK_SPAN_RGB),
        "quiet_background": "exact local K2 color with inherited dark tail capped",
        "quiet_background_dark_cap": HIGHLAND_BACKGROUND_DARK_CAP,
        "paper_grain_filter_sigma_px": [3.0, 18.0],
        "paper_grain_channel_cap": HIGHLAND_PAPER_GRAIN_CAP,
        "post_resize_blur_applied": False,
        "geometric_patch_overlay_used": False,
        "procedural_micrograin_added": False,
        "donor_low_frequency_reprojection_added": True,
        "hollow_ring_or_outline_layer_added": False,
        "color_match_shift_rgb": [0, 0, 0],
        "directional_marks_added": 0,
    }


def robust_local_ring_color(
    base: np.ndarray,
    permission: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Return one robust parcel color from its own inner K2 ring."""
    ring = erode(permission, 2) & ~erode(permission, 10)
    gray = cv2.cvtColor(base, cv2.COLOR_RGB2GRAY).astype(np.float32)
    local_median = cv2.medianBlur(gray.astype(np.uint8), 11).astype(np.float32)
    eligible = ring & ((local_median - gray) < 8.0)
    values = base[eligible].astype(np.float32)
    if len(values) < 64:
        raise K3BuildError("parcel local ring lacks robust color samples")
    center = np.median(values, axis=0)
    residual = np.max(np.abs(values - center[None, :]), axis=1)
    retained = values[residual <= np.quantile(residual, 0.80)]
    color = np.rint(np.median(retained, axis=0)).astype(np.uint8)
    return color, {
        "method": "single robust RGB median from parcel-local 2-10px K2 inner ring",
        "eligible_ring_pixels": int(eligible.sum()),
        "retained_ring_pixels": int(len(retained)),
        "rgb": [int(value) for value in color],
        "diffusion_or_inpaint_used": False,
        "distance_direction_interpolation_used": False,
    }


def neutral_ground_interpolation(
    base: np.ndarray,
    sample_mask: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Fit a robust local neutral-ground RGB plane from outside the field hull."""
    gray = cv2.cvtColor(base, cv2.COLOR_RGB2GRAY).astype(np.float32)
    local_median = cv2.medianBlur(gray.astype(np.uint8), 11).astype(np.float32)
    eligible = sample_mask & ((local_median - gray) < 10.0)
    ys, xs = np.nonzero(eligible)
    if len(xs) < 256:
        raise K3BuildError("neutral agricultural ground interpolation lacks samples")
    bucket_px = 32
    bucket_keys = (ys // bucket_px) * ((WIDTH + bucket_px - 1) // bucket_px) + (xs // bucket_px)
    unique_keys = np.unique(bucket_keys)
    bucket_x: list[float] = []
    bucket_y: list[float] = []
    bucket_rgb: list[np.ndarray] = []
    for key in unique_keys:
        selected = bucket_keys == key
        if int(np.count_nonzero(selected)) < 8:
            continue
        bucket_x.append(float(np.median(xs[selected])))
        bucket_y.append(float(np.median(ys[selected])))
        bucket_rgb.append(np.median(base[ys[selected], xs[selected]], axis=0))
    if len(bucket_x) < 6:
        raise K3BuildError("neutral agricultural ground interpolation lacks coordinate buckets")
    xs_sample = np.asarray(bucket_x, np.float64)
    ys_sample = np.asarray(bucket_y, np.float64)
    design = np.column_stack((
        np.ones_like(xs_sample),
        (xs_sample - WIDTH / 2.0) / WIDTH,
        (ys_sample - HEIGHT / 2.0) / HEIGHT,
    ))
    values = np.asarray(bucket_rgb, np.float64)
    coefficients, _, _, _ = np.linalg.lstsq(design, values, rcond=None)
    residual = np.max(np.abs(values - design @ coefficients), axis=1)
    keep = residual <= np.quantile(residual, 0.80)
    coefficients, _, _, _ = np.linalg.lstsq(
        design[keep], values[keep], rcond=None
    )
    coefficients[1:, :] = np.clip(coefficients[1:, :], -12.0, 12.0)
    coefficients[0, :] = np.median(
        values[keep] - design[keep, 1:] @ coefficients[1:, :], axis=0
    )
    yy, xx = np.indices((HEIGHT, WIDTH), dtype=np.float64)
    full_design = np.stack((
        np.ones_like(xx),
        (xx - WIDTH / 2.0) / WIDTH,
        (yy - HEIGHT / 2.0) / HEIGHT,
    ), axis=-1)
    plate = np.clip(np.rint(full_design @ coefficients), 0, 255).astype(np.uint8)
    return plate, {
        "method": "robust affine RGB interpolation from neutral K2 ring outside agricultural envelope",
        "eligible_sample_pixels": int(eligible.sum()),
        "coordinate_bucket_px": bucket_px,
        "coordinate_buckets": len(bucket_x),
        "fit_buckets": int(np.count_nonzero(keep)),
        "normalized_axis_rgb_gradient_cap": 12.0,
        "coefficients_rgb": [[round(float(value), 8) for value in row] for row in coefficients],
        "donor_low_frequency_used": False,
    }


def field_four_pixel_lattice_metrics(
    image: np.ndarray,
    permission: np.ndarray,
    *,
    left: int,
    top: int,
) -> dict[str, Any]:
    """Detect a surviving 4 px grid or checker phase in a continuous texture."""
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY).astype(np.float32)
    detrended = gray - cv2.GaussianBlur(gray, (0, 0), 4.0)
    horizontal_pairs = permission[:, 1:] & permission[:, :-1]
    horizontal_delta = np.abs(gray[:, 1:] - gray[:, :-1])
    horizontal_phase_means: list[float] = []
    for phase in range(4):
        columns = (
            np.arange(left + 1, left + image.shape[1], dtype=np.int32) % 4
        ) == phase
        selected = horizontal_pairs & columns[None, :]
        horizontal_phase_means.append(
            float(horizontal_delta[selected].mean()) if np.any(selected) else 0.0
        )
    vertical_pairs = permission[1:, :] & permission[:-1, :]
    vertical_delta = np.abs(gray[1:, :] - gray[:-1, :])
    vertical_phase_means: list[float] = []
    for phase in range(4):
        rows = (
            np.arange(top + 1, top + image.shape[0], dtype=np.int32) % 4
        ) == phase
        selected = vertical_pairs & rows[:, None]
        vertical_phase_means.append(
            float(vertical_delta[selected].mean()) if np.any(selected) else 0.0
        )

    def phase_ratio(values: list[float]) -> float:
        positive = [value for value in values if value > 0.0]
        if not positive:
            return 0.0
        return max(positive) / max(min(positive), 0.25)

    lattice_ratio = max(
        phase_ratio(horizontal_phase_means),
        phase_ratio(vertical_phase_means),
    )
    yy, xx = np.indices(permission.shape)
    texture_scale = max(float(detrended[permission].std()), 0.25)
    checker_phase_means: list[float] = []
    for phase_y in range(4):
        for phase_x in range(4):
            selected = (
                permission
                & (((yy + top) % 4) == phase_y)
                & (((xx + left) % 4) == phase_x)
            )
            checker_phase_means.append(
                float(detrended[selected].mean()) if np.any(selected) else 0.0
            )
    checker_mean_score = max(abs(value) for value in checker_phase_means) / texture_scale
    return {
        "method": (
            "four-coordinate-phase adjacent-delta ratio plus 4x4 detrended "
            "residue-class mean score"
        ),
        "period_px": 4,
        "horizontal_phase_mean_gray_delta": [
            round(value, 6) for value in horizontal_phase_means
        ],
        "vertical_phase_mean_gray_delta": [
            round(value, 6) for value in vertical_phase_means
        ],
        "maximum_phase_delta_ratio": round(lattice_ratio, 6),
        "maximum_allowed_phase_delta_ratio": FIELD_FOUR_PIXEL_LATTICE_RATIO_LIMIT,
        "checker_residue_mean_score": round(checker_mean_score, 6),
        "maximum_allowed_checker_residue_mean_score": FIELD_FOUR_PIXEL_CHECKER_MEAN_LIMIT,
        "passed": bool(
            lattice_ratio <= FIELD_FOUR_PIXEL_LATTICE_RATIO_LIMIT
            and checker_mean_score <= FIELD_FOUR_PIXEL_CHECKER_MEAN_LIMIT
        ),
    }


def procedural_fields_canvas(
    base: np.ndarray,
    donor_source: np.ndarray,
    record: dict[str, Any],
    permissions: list[np.ndarray],
) -> tuple[np.ndarray, list[list[int]], dict[str, Any]]:
    source_crops = [
        (0, 0, 418, 418), (418, 0, 836, 418), (836, 0, 1254, 418),
        (0, 418, 418, 836), (418, 418, 836, 836), (836, 418, 1254, 836),
        (0, 836, 418, 1254), (418, 836, 836, 1254),
    ]
    canvas = base.copy()
    shifts: list[list[int]] = []
    parcel_records: list[dict[str, Any]] = []
    gain_rgb = np.asarray(FIELD_BANDPASS_GAIN_RGB, np.float32)
    tint_rgb = np.asarray(FIELD_MEDIAN_TINT_RGB, np.float32)
    for index, permission in enumerate(permissions):
        ys, xs = np.nonzero(permission)
        left, right = int(xs.min()), int(xs.max()) + 1
        top, bottom = int(ys.min()), int(ys.max()) + 1
        width, height = right - left, bottom - top
        sx0, sy0, sx1, sy1 = source_crops[index]
        donor = np.asarray(
            Image.fromarray(donor_source[sy0:sy1, sx0:sx1], "RGB").resize(
                (width, height), Image.Resampling.BOX
            ),
            np.float32,
        )
        local_permission = permission[top:bottom, left:right]
        donor_gray = cv2.cvtColor(
            np.clip(np.rint(donor), 0, 255).astype(np.uint8),
            cv2.COLOR_RGB2GRAY,
        ).astype(np.float32)
        inner = (
            donor_gray
            if FIELD_BANDPASS_INNER_SIGMA_PX == 0.0
            else cv2.GaussianBlur(
                donor_gray, (0, 0), FIELD_BANDPASS_INNER_SIGMA_PX
            )
        )
        outer = cv2.GaussianBlur(
            donor_gray, (0, 0), FIELD_BANDPASS_OUTER_SIGMA_PX
        )
        bandpass = inner - outer
        signed_tone = (
            np.sign(bandpass)
            * FIELD_BANDPASS_TONE_PIVOT
            * np.power(
                np.abs(bandpass) / FIELD_BANDPASS_TONE_PIVOT,
                FIELD_BANDPASS_TONE_GAMMA,
            )
        )
        transformed = signed_tone[..., None] * gain_rgb[None, None, :]
        fleck_dog = cv2.GaussianBlur(
            donor_gray, (0, 0), FIELD_FLECK_DOG_INNER_SIGMA_PX
        ) - cv2.GaussianBlur(
            donor_gray, (0, 0), FIELD_FLECK_DOG_OUTER_SIGMA_PX
        )
        fleck_seed = (
            (fleck_dog <= FIELD_FLECK_DARK_THRESHOLD) & local_permission
        )
        component_count, component_labels, component_stats, _ = (
            cv2.connectedComponentsWithStats(fleck_seed.astype(np.uint8), 8)
        )
        fleck_mask = np.zeros(local_permission.shape, bool)
        selected_component_count = 0
        minimum_area, maximum_area = FIELD_FLECK_COMPONENT_AREA_RANGE
        for component in range(1, component_count):
            area = int(component_stats[component, cv2.CC_STAT_AREA])
            component_width = int(component_stats[component, cv2.CC_STAT_WIDTH])
            component_height = int(component_stats[component, cv2.CC_STAT_HEIGHT])
            aspect = max(
                component_width / max(component_height, 1),
                component_height / max(component_width, 1),
            )
            if (
                area < minimum_area
                or area > maximum_area
                or aspect >= FIELD_FLECK_MAXIMUM_ASPECT_RATIO
                or max(component_width, component_height)
                > FIELD_FLECK_MAXIMUM_SPAN_PX
            ):
                continue
            fleck_mask |= component_labels == component
            selected_component_count += 1
        fleck_density = float(fleck_mask[local_permission].mean())
        if fleck_density > FIELD_FLECK_MAXIMUM_DENSITY:
            raise K3BuildError(
                f"field parcel {index + 1} exceeds the fixed fleck density cap: "
                f"{fleck_density:.8f}"
            )
        transformed[fleck_mask] -= np.asarray(
            FIELD_FLECK_DARKEN_RGB, np.float32
        )
        desired_median = np.median(base[permission], axis=0) + tint_rgb
        affine_bias = desired_median - np.median(
            transformed[local_permission], axis=0
        )
        transformed += affine_bias[None, None, :]
        local = base[top:bottom, left:right].copy()
        local[local_permission] = np.clip(
            np.rint(transformed[local_permission]), 0, 255
        ).astype(np.uint8)
        final_shift = np.rint(
            desired_median - np.median(local[local_permission], axis=0)
        ).astype(np.int16)
        local[local_permission] = np.clip(
            local[local_permission].astype(np.int16) + final_shift[None, :],
            0,
            255,
        ).astype(np.uint8)
        final_median_delta = (
            np.median(local[local_permission], axis=0)
            - np.median(base[permission], axis=0)
        )
        lattice = field_four_pixel_lattice_metrics(
            local,
            local_permission,
            left=left,
            top=top,
        )
        if not lattice["passed"]:
            raise K3BuildError(
                f"field parcel {index + 1} failed the four-pixel lattice diagnostic: "
                f"{lattice}"
            )
        destination = canvas[top:bottom, left:right]
        destination[local_permission] = local[local_permission]
        canvas[top:bottom, left:right] = destination
        shift = [
            int(value)
            for value in np.rint(affine_bias).astype(np.int16) + final_shift
        ]
        shifts.append(shift)
        parcel_records.append({
            "parcel": index + 1,
            "source_crop_xyxy": list(source_crops[index]),
            "source_crop_nonoverlapping": True,
            "rotation_or_reflection": "none",
            "resampling": "Pillow BOX area downsample",
            "plate": (
                "same-coordinate fields-v2 donor gray band-pass followed only by "
                "continuous per-channel signed tone, affine gain, and bias"
            ),
            "bandpass_inner_sigma_px": FIELD_BANDPASS_INNER_SIGMA_PX,
            "bandpass_outer_sigma_px": FIELD_BANDPASS_OUTER_SIGMA_PX,
            "bandpass_definition": "same-coordinate donor-gray difference of Gaussians",
            "bandpass_gain_rgb": list(FIELD_BANDPASS_GAIN_RGB),
            "signed_tone_gamma": FIELD_BANDPASS_TONE_GAMMA,
            "signed_tone_pivot": FIELD_BANDPASS_TONE_PIVOT,
            "same_coordinate_solid_flecks": {
                "dog_inner_sigma_px": FIELD_FLECK_DOG_INNER_SIGMA_PX,
                "dog_outer_sigma_px": FIELD_FLECK_DOG_OUTER_SIGMA_PX,
                "fixed_dark_threshold": FIELD_FLECK_DARK_THRESHOLD,
                "component_area_range_px": list(FIELD_FLECK_COMPONENT_AREA_RANGE),
                "maximum_aspect_ratio_exclusive": FIELD_FLECK_MAXIMUM_ASPECT_RATIO,
                "maximum_component_span_px": FIELD_FLECK_MAXIMUM_SPAN_PX,
                "darken_rgb": list(FIELD_FLECK_DARKEN_RGB),
                "input_component_count": component_count - 1,
                "selected_component_count": selected_component_count,
                "selected_pixels": int(fleck_mask.sum()),
                "selected_density": round(fleck_density, 8),
                "maximum_density": FIELD_FLECK_MAXIMUM_DENSITY,
                "spatial_coordinate_preserved": True,
            },
            "affine_bias_rgb": [round(float(value), 6) for value in affine_bias],
            "spatial_coordinate_preserved": True,
            "spatial_pixel_reassignment_used": False,
            "sorting_or_distribution_remap_used": False,
            "donor_low_frequency_used": False,
            "post_composite_blur_applied": False,
            "preserved_median_tint_rgb": [
                round(float(value), 6) for value in tint_rgb
            ],
            "final_median_delta_from_k2_rgb": [
                round(float(value), 6) for value in final_median_delta
            ],
            "lattice_diagnostic": lattice,
            "color_match_shift_rgb": shift,
        })
    return canvas, shifts, {
        "texture_authority": "fields-quiet-v2",
        "unique_nonoverlapping_source_crops": True,
        "same_crop_reused": False,
        "transform_family": "same-coordinate continuous band-pass affine tone",
        "spatial_pixel_reassignment_used": False,
        "sorting_or_distribution_remap_used": False,
        "parcel_records": parcel_records,
        "directional_marks_added": 0,
    }


def agricultural_corridor_canvas(
    base: np.ndarray,
    permission: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any]]:
    if not np.any(permission):
        raise K3BuildError("agricultural corridor envelope permission is empty")
    # v17's single-change rule is an exact same-coordinate K2 restoration.
    # Returning a byte copy is intentional: no plate, interpolation, inpaint,
    # blur, donor, alpha, or color transform participates in this context.
    canvas = base.copy()
    return canvas, {
        "semantic": "agricultural_corridor_envelope",
        "source": relative(SOURCE),
        "source_sha256": EXPECTED_SOURCE,
        "permission_pixels": int(permission.sum()),
        "operation": "same-coordinate exact K2 byte restoration",
        "actual_canvas_change_pixels": 0,
        "actual_canvas_change_outside_permission_pixels": 0,
        "k2_exact_pixels": int(permission.sum()),
        "road_core_byte_locked": True,
        "road_core_rasterization": "OpenCV LINE_8 width=4px for agricultural semantics only",
        "parcel_line_core_byte_locked": True,
        "parcel_line_core_rasterization": "OpenCV LINE_8 width=1px",
        "permission_geometry": "source-derived west dark-row cleanup components only outside parcel permissions; full convex-hull gaps excluded",
        "same_coordinate_local_filter": False,
        "spatial_pixel_reassignment_used": False,
        "sorting_or_distribution_remap_used": False,
        "global_affine_plate_used": False,
        "plate_used": False,
        "inpaint_used": False,
        "blur_used": False,
        "donor_raster_used": False,
        "exact_road_and_parcel_cores_touched": 0,
        "directional_marks_added": 0,
    }


def feather_alpha(mask: np.ndarray, feather: int) -> np.ndarray:
    distance = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    # Back-load the smoothstep within the same locked feather width. Generated
    # donors can differ strongly at individual paper-grain pixels; quadratic
    # distance keeps the first three seam pixels within Blind-B's 2/5 delta
    # contract while still reaching exact full alpha at ``feather`` pixels.
    value = np.clip(distance / float(feather), 0.0, 1.0) ** 2
    return (value * value * (3.0 - 2.0 * value)).astype(np.float32)


def composite(base: np.ndarray, donor: np.ndarray, mask: np.ndarray, feather: int) -> np.ndarray:
    result = base.copy()
    alpha = feather_alpha(mask, feather)
    selected = alpha > 0
    weight = alpha[selected][:, None]
    result[selected] = np.clip(np.rint(
        base[selected].astype(np.float32) * (1.0 - weight)
        + donor[selected].astype(np.float32) * weight
    ), 0, 255).astype(np.uint8)
    return result


def boundary_locked_alpha(
    mask: np.ndarray,
    *,
    full_by_px: float,
    locked_boundary_px: float = 3,
) -> np.ndarray:
    if full_by_px <= locked_boundary_px:
        raise K3BuildError("full donor distance must exceed the locked boundary width")
    padded = np.pad(mask.astype(np.uint8), 1, mode="constant", constant_values=0)
    distance = cv2.distanceTransform(padded, cv2.DIST_L2, 5)[1:-1, 1:-1]
    value = np.clip(
        (distance - float(locked_boundary_px))
        / float(full_by_px - locked_boundary_px),
        0.0,
        1.0,
    )
    alpha = value * value * (3.0 - 2.0 * value)
    alpha[~mask] = 0.0
    return alpha.astype(np.float32)


def inward_edge_strength(mask: np.ndarray, width_px: float) -> np.ndarray:
    """Return a smooth boundary-to-interior weight for local color matching."""
    if width_px <= 1:
        raise K3BuildError("edge-match width must exceed one pixel")
    padded = np.pad(mask.astype(np.uint8), 1, mode="constant", constant_values=0)
    distance = cv2.distanceTransform(padded, cv2.DIST_L2, 5)[1:-1, 1:-1]
    value = np.clip((float(width_px) - distance) / (float(width_px) - 1.0), 0.0, 1.0)
    value = value * value * (3.0 - 2.0 * value)
    value[~mask] = 0.0
    return value.astype(np.float32)


def boundary_local_rgb_match(
    base: np.ndarray,
    donor: np.ndarray,
    permission: np.ndarray,
    strength: np.ndarray,
    *,
    window_px: int = 41,
    shift_cap: float = 16.0,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Match donor paper color locally at the envelope without blurring texture."""
    eligible = permission & (strength > 0)
    if not np.any(eligible):
        raise K3BuildError("agricultural boundary-local color match has no pixels")
    weight = eligible.astype(np.float32)
    denominator = cv2.boxFilter(
        weight, -1, (window_px, window_px), normalize=False,
        borderType=cv2.BORDER_REFLECT,
    )
    difference = base.astype(np.float32) - donor.astype(np.float32)
    shift_field = np.zeros_like(difference, np.float32)
    for channel in range(3):
        numerator = cv2.boxFilter(
            difference[..., channel] * weight,
            -1,
            (window_px, window_px),
            normalize=False,
            borderType=cv2.BORDER_REFLECT,
        )
        shift_field[..., channel] = numerator / np.maximum(denominator, 1e-6)
    shift_field = np.clip(shift_field, -shift_cap, shift_cap)
    applied = shift_field * strength[..., None]
    matched = donor.copy()
    matched[eligible] = np.clip(
        np.rint(donor[eligible].astype(np.float32) + applied[eligible]), 0, 255
    ).astype(np.uint8)
    applied_values = np.abs(applied[eligible])
    return matched, {
        "scope": "agricultural outer edge only",
        "eligible_pixels": int(eligible.sum()),
        "local_window_px": window_px,
        "maximum_channel_shift_cap": shift_cap,
        "p95_absolute_applied_channel_shift": round(float(np.percentile(applied_values, 95)), 6),
        "maximum_absolute_applied_channel_shift": round(float(np.max(applied_values)), 6),
        "output_texture_blurred": False,
        "global_transform_applied": False,
        "exact_road_and_parcel_cores_touched": 0,
    }


def composite_with_alpha(
    base: np.ndarray,
    donor: np.ndarray,
    alpha: np.ndarray,
) -> np.ndarray:
    result = base.copy()
    selected = alpha > 0
    weight = alpha[selected][:, None]
    result[selected] = np.clip(np.rint(
        base[selected].astype(np.float32) * (1.0 - weight)
        + donor[selected].astype(np.float32) * weight
    ), 0, 255).astype(np.uint8)
    return result


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def boundary_delta_metrics(base: np.ndarray, result: np.ndarray, permission: np.ndarray) -> dict[str, Any]:
    padded = np.pad(permission.astype(np.uint8), 1, mode="constant", constant_values=0)
    per_pixel_delta = np.max(
        np.abs(result.astype(np.int16) - base.astype(np.int16)), axis=2
    )
    distance = cv2.distanceTransform(padded, cv2.DIST_L2, 5)[1:-1, 1:-1]
    outermost = permission & (distance > 0.0) & (distance <= 1.000001)
    delta = per_pixel_delta[outermost]
    transition_band = permission & (distance <= 3.0)
    transition_delta = per_pixel_delta[transition_band]
    return {
        "method": "padded outermost L2 permission ring 0<d<=1px; per-pixel maximum RGB channel delta",
        "pixels": int(outermost.sum()),
        "median_channel_delta": round(float(np.median(delta)), 6) if delta.size else 0.0,
        "p95_channel_delta": round(float(np.percentile(delta, 95)), 6) if delta.size else 0.0,
        "diagnostic_first_3px_transition_band": {
            "pixels": int(transition_band.sum()),
            "median_max_channel_delta": round(float(np.median(transition_delta)), 6) if transition_delta.size else 0.0,
            "p95_max_channel_delta": round(float(np.percentile(transition_delta, 95)), 6) if transition_delta.size else 0.0,
        },
    }


def build_temporary_proof(*, replace: bool = False) -> dict[str, Any]:
    if any(path.exists() for path in (RAW, FINAL, RECEIPT, AUDIT)):
        raise K3BuildError("persistent K3 outputs must remain absent during temporary proof work")
    existing = (TEMP_RAW, TEMP_FINAL, TEMP_RECEIPT)
    if not replace and any(path.exists() for path in existing):
        raise K3BuildError("temporary K3 proof already exists; pass --replace-temporary explicitly")

    spec = load_spec()
    if spec.get("output_authorized"):
        raise K3BuildError("temporary proof requires persistent output_authorized to remain false")
    donors = {
        name: validate_donor_record(name, record)
        for name, record in spec["donor_slots"].items()
    }
    base = validate_source()
    masks = derive_masks()
    if not V17_PROOF.is_file() or sha256(V17_PROOF) != EXPECTED_V17_PROOF:
        raise K3BuildError("frozen TEMP v17 proof is missing or hash-mismatched")
    v17 = np.asarray(Image.open(V17_PROOF).convert("RGB"), np.uint8)
    if not np.any(masks["agricultural_corridor_envelope"]):
        raise K3BuildError("agricultural corridor envelope permission is empty")
    if np.any(masks["edit_union"] & masks["protected_features"]):
        raise K3BuildError("semantic permissions overlap a byte-locked feature")
    for name, permission in (
        ("forest", masks["forest_edit"]),
        ("highland", masks["highland_edit"]),
        ("fields", masks["fields_edit"]),
    ):
        if permission_outside_crop_pixels(permission, spec["donor_slots"][name]):
            raise K3BuildError(f"{name} permission escapes its registration crop")

    forest_canvas, forest_marks, forest_record = procedural_forest_canvas(
        base, donors["forest"], masks["forest_edit"]
    )
    highland_canvas, highland_shift, highland_record = procedural_highland_canvas(
        base,
        donors["highland"],
        spec["donor_slots"]["highland"],
        masks["highland_edit"],
    )
    fields_canvas = v17.copy()
    fields_shifts: list[list[int]] = []
    fields_record = {
        "semantic": "eight strict field-parcel interiors",
        "operation": "byte-exact frozen v17 strict-interior carry",
        "strict_interior_erosion_px": FIELD_STRICT_INTERIOR_EROSION_PX,
        "strict_interior_pixels": int(masks["field_parcel_edit"].sum()),
        "legacy_field_channel_pixels": int(masks["field_channel_legacy_scope"].sum()),
        "outer_feather_applied": False,
        "field_donor_rerendered": False,
    }
    corridor_canvas, corridor_record = agricultural_corridor_canvas(
        base,
        masks["agricultural_corridor_envelope"],
    )

    fields_edge_match_record = {
        "enabled": False,
        "reason": "v18 carries frozen v17 strict-interior bytes and applies no field feather",
    }
    result = base.copy()
    alphas: dict[str, np.ndarray] = {}
    transition_contract = {
        "forest": {"locked_boundary_px": 2, "full_by_px": 5},
        "highland": {
            "locked_boundary_px": HIGHLAND_ALPHA_LOCKED_BOUNDARY_PX,
            "full_by_px": HIGHLAND_ALPHA_FULL_BY_PX,
        },
        "fields": {
            "mode": "hard strict-interior frozen v17 carry",
            "erosion_px": FIELD_STRICT_INTERIOR_EROSION_PX,
            "outside_feather_px": 0,
        },
        "agricultural_corridor_envelope": {
            "mode": "same-coordinate exact K2 restoration",
            "alpha_applied": False,
        },
        "agricultural_outer_envelope": {
            "mode": "disabled for field channel",
            "maximum_alpha": 0,
        },
        "agricultural_west_row_cleanup": {
            "mode": "disabled for field channel",
            "maximum_alpha": 0,
        },
    }
    agricultural_hull_outer_alpha = np.zeros((HEIGHT, WIDTH), np.float32)
    agricultural_approach_alpha = np.zeros((HEIGHT, WIDTH), np.float32)
    agricultural_outer_alpha = np.zeros((HEIGHT, WIDTH), np.float32)
    source_tail_override_pixels: dict[str, int] = {}
    for name, donor, permission in (
        ("forest", forest_canvas, masks["forest_edit"]),
        ("highland", highland_canvas, masks["highland_edit"]),
    ):
        transition = transition_contract[name]
        alphas[name] = boundary_locked_alpha(
            permission,
            full_by_px=transition["full_by_px"],
            locked_boundary_px=transition["locked_boundary_px"],
        )
        result = composite_with_alpha(result, donor, alphas[name])
    alphas["fields"] = masks["field_parcel_edit"].astype(np.float32)
    result[masks["field_parcel_edit"]] = fields_canvas[masks["field_parcel_edit"]]
    source_tail_override_pixels["fields"] = 0
    alphas["agricultural_corridor_envelope"] = np.zeros(
        (HEIGHT, WIDTH), np.float32
    )
    source_tail_override_pixels["agricultural_corridor_envelope"] = 0
    if not np.array_equal(
        corridor_canvas[masks["agricultural_corridor_envelope"]],
        base[masks["agricultural_corridor_envelope"]],
    ):
        raise K3BuildError("TEMP v18 corridor restoration canvas is not exact K2")
    alphas["agricultural_outer_envelope"] = agricultural_outer_alpha
    alphas["agricultural_hull_outer_envelope"] = agricultural_hull_outer_alpha
    alphas["agricultural_west_row_cleanup"] = agricultural_approach_alpha

    changed = np.any(result != base, axis=2)
    if not V3_FOREST_PROOF.is_file() or sha256(V3_FOREST_PROOF) != EXPECTED_V3_FOREST_PROOF:
        raise K3BuildError("accepted TEMP v3 forest proof is missing or hash-mismatched")
    v3 = np.asarray(Image.open(V3_FOREST_PROOF).convert("RGB"), np.uint8)
    forest_carry_delta = np.abs(
        result.astype(np.int16) - v3.astype(np.int16)
    )[masks["forest_edit"]]
    forest_carry_differing_pixels = int(np.count_nonzero(np.any(forest_carry_delta > 0, axis=1)))
    if forest_carry_differing_pixels:
        raise K3BuildError("TEMP v18 changed Root-accepted TEMP v3 forest pixels")
    if not V10_PROOF.is_file() or sha256(V10_PROOF) != EXPECTED_V10_PROOF:
        raise K3BuildError("frozen TEMP v10 proof is missing or hash-mismatched")
    v10 = np.asarray(Image.open(V10_PROOF).convert("RGB"), np.uint8)
    highland_v10_differing_pixels = int(np.count_nonzero(np.any(
        result[masks["highland_edit"]] != v10[masks["highland_edit"]], axis=1
    )))
    forest_v10_differing_pixels = int(np.count_nonzero(np.any(
        result[masks["forest_edit"]] != v10[masks["forest_edit"]], axis=1
    )))
    if highland_v10_differing_pixels or forest_v10_differing_pixels:
        raise K3BuildError("TEMP v18 failed byte-exact v10 highland/forest carry")
    field_strict_interior_v17_differing_pixels = int(np.count_nonzero(np.any(
        result[masks["field_parcel_edit"]]
        != v17[masks["field_parcel_edit"]],
        axis=1,
    )))
    field_restore_scope = masks["field_restore_scope"]
    field_legacy_margin_scope = masks["field_legacy_margin_scope"]
    v17_difference = np.any(result != v17, axis=2)
    v17_differing_pixels = int(np.count_nonzero(v17_difference))
    v17_differing_outside_field_restore_scope_pixels = int(np.count_nonzero(
        v17_difference & ~field_restore_scope
    ))
    v17_differing_inside_field_restore_scope_pixels = int(np.count_nonzero(
        v17_difference & field_restore_scope
    ))
    field_channel_outside_strict_k2_differing_pixels = int(np.count_nonzero(
        np.any(result != base, axis=2) & field_restore_scope
    ))
    field_legacy_margin_k2_differing_pixels = int(np.count_nonzero(
        np.any(result != base, axis=2) & field_legacy_margin_scope
    ))
    corridor_k2_differing_pixels = int(np.count_nonzero(
        np.any(result != base, axis=2)
        & masks["agricultural_corridor_envelope"]
    ))
    if field_strict_interior_v17_differing_pixels:
        raise K3BuildError("TEMP v18 changed frozen TEMP v17 strict field interiors")
    if v17_differing_outside_field_restore_scope_pixels:
        raise K3BuildError("TEMP v18 differs from TEMP v17 outside field restore scope")
    if not v17_differing_inside_field_restore_scope_pixels:
        raise K3BuildError("TEMP v18 did not restore any rejected TEMP v17 field margins")
    if field_channel_outside_strict_k2_differing_pixels:
        raise K3BuildError("TEMP v18 field channel outside strict interiors is not K2 exact")
    if field_legacy_margin_k2_differing_pixels or corridor_k2_differing_pixels:
        raise K3BuildError("TEMP v18 did not restore every field margin and corridor pixel to K2")
    changed_outside = int(np.count_nonzero(changed & ~masks["edit_union"]))
    changed_protected = int(np.count_nonzero(changed & masks["protected_features"]))
    changed_named_guards = {
        name: int(np.count_nonzero(changed & guard))
        for name, guard in masks["guards"].items()
    }
    if changed_outside or changed_protected or any(changed_named_guards.values()):
        raise K3BuildError("temporary K3 proof changed byte-locked K2 pixels")
    replacement = {
        "forest": round(float(changed[masks["forest_edit"]].mean()), 6),
        "highland": round(float(changed[masks["highland_edit"]].mean()), 6),
        "fields": [round(float(changed[item].mean()), 6) for item in masks["field_edits"]],
        "agricultural_corridor_envelope": round(
            float(changed[masks["agricultural_corridor_envelope"]].mean()), 6
        ),
    }
    if (
        replacement["forest"] < 0.80
        or replacement["highland"] < 0.80
        or any(value < 0.75 for value in replacement["fields"])
        or replacement["agricultural_corridor_envelope"] != 0.0
    ):
        raise K3BuildError("temporary K3 proof failed edit/restoration coverage")

    boundary = {
        "forest": boundary_delta_metrics(base, result, masks["forest_edit"]),
        "highland": boundary_delta_metrics(base, result, masks["highland_edit"]),
        "fields": boundary_delta_metrics(
            base, result, masks["field_parcel_legacy_edit"]
        ),
        "field_strict_interiors_diagnostic": boundary_delta_metrics(
            base, result, masks["field_parcel_edit"]
        ),
        "agricultural_corridor_envelope": boundary_delta_metrics(
            base, result, masks["agricultural_corridor_envelope"]
        ),
        "field_parcels": [
            boundary_delta_metrics(base, result, permission)
            for permission in masks["field_legacy_edits"]
        ],
    }
    boundary_records = [
        boundary["forest"],
        boundary["highland"],
        boundary["fields"],
        boundary["agricultural_corridor_envelope"],
    ]
    if any(record["median_channel_delta"] > 2 or record["p95_channel_delta"] > 5 for record in boundary_records):
        raise K3BuildError(f"temporary K3 proof boundary delta gate failed: {boundary}")

    mask_root = TEMP_PROOF_ROOT / "masks"
    artifacts: dict[str, Any] = {}
    for name, mask in (
        ("forest-canonical", masks["forest_shape"]),
        ("highland-canonical", masks["highland_shape"]),
        ("forest-permission", masks["forest_edit"]),
        ("highland-permission", masks["highland_edit"]),
        ("agricultural-hull", masks["agricultural_hull"]),
        ("agricultural-west-row-cleanup", masks["agricultural_approach_cleanup"]),
        ("agricultural-envelope", masks["agricultural_envelope"]),
        ("fields-permission", masks["fields_edit"]),
        ("field-strict-interiors-permission", masks["field_parcel_edit"]),
        ("field-legacy-channel-scope", masks["field_channel_legacy_scope"]),
        (
            "field-restored-k2-margin-scope",
            masks["field_restore_scope"],
        ),
        ("field-legacy-parcel-margin-scope", masks["field_legacy_margin_scope"]),
        ("field-exact-border-core", masks["guards"]["field_boundaries"]),
        (
            "agricultural-corridor-envelope-permission",
            masks["agricultural_corridor_envelope"],
        ),
        ("permission-union", masks["edit_union"]),
        ("protected-features", masks["protected_features"]),
        ("outside-identity", masks["outside_identity"]),
        ("forest-semantic-marks", forest_marks),
        ("actual-change", changed),
    ):
        artifacts[name] = mask_artifact(mask_root / f"style-candidate-k-v3-{name}-mask-v1.png", mask)
    for name, alpha in alphas.items():
        artifacts[f"{name}-alpha"] = grayscale_artifact(
            mask_root / f"style-candidate-k-v3-{name}-alpha-mask-v1.png",
            np.rint(alpha * 255).astype(np.uint8),
        )

    atomic_png(TEMP_RAW, result, "RGB")
    TEMP_FINAL.parent.mkdir(parents=True, exist_ok=True)
    temporary_final = TEMP_FINAL.with_name(TEMP_FINAL.name + ".new")
    shutil.copyfile(TEMP_RAW, temporary_final)
    temporary_final.replace(TEMP_FINAL)
    if TEMP_RAW.read_bytes() != TEMP_FINAL.read_bytes():
        raise K3BuildError("temporary raw/final proof bytes differ")

    receipt = {
        "schema_version": "1.0.0",
        "id": "style-candidate-k-v3-semantic-cleanup-temporary-proof",
        "status": "temporary-proof-built-pending-automated-and-root-vision-review",
        "temporary_review_only": True,
        "persistent_candidate_emitted": False,
        "golden_accepted": False,
        "source": {"path": relative(SOURCE), "sha256": sha256(SOURCE)},
        "spec": {"path": relative(SPEC), "sha256": sha256(SPEC)},
        "builder": {"path": relative(Path(__file__).resolve()), "sha256": sha256(Path(__file__).resolve())},
        "donors": {
            name: {
                **record,
                "actual_sha256": sha256(_repo_artifact(record["path"])),
                "used_as_raster_authority": name != "fields",
                "used_as_texture_authority": name != "fields",
                "validated_but_not_directly_rerendered": name == "fields",
            }
            for name, record in spec["donor_slots"].items()
        },
        "construction": {
            "forest": forest_record,
            "highland": highland_record,
            "fields": fields_record,
            "agricultural_corridor_envelope": corridor_record,
            "agricultural_inherited_dark_tail_override": {
                "enabled": False,
                "method": "disabled for both fields and corridor in v18",
                "field_threshold": FIELD_SOURCE_DARK_TAIL_THRESHOLD,
                "selected_pixels": source_tail_override_pixels,
                "outermost_permission_ring_touched": False,
                "exact_road_and_parcel_cores_touched": 0,
            },
            "agricultural_corridor_outermost_tail_lift": {
                "enabled": False,
                "selected_pixels": 0,
                "rgb_channel_lift": 0,
                "reason": "v18 keeps every corridor permission pixel at exact K2",
            },
            "agricultural_approach_cleanup": masks["agricultural_approach_record"],
            "agricultural_outer_envelope_feather": {
                "enabled": False,
                "legacy_configured_width_px": AGRICULTURAL_OUTER_FEATHER_PX,
                "legacy_west_row_cleanup_width_px": AGRICULTURAL_APPROACH_FEATHER_PX,
                "applied_width_px": 0,
                "method": "disabled; v18 restores all pixels outside the 12px-eroded strict interiors to exact K2",
                "color_match": {
                    "fields": fields_edge_match_record,
                    "corridor": "disabled; exact K2 byte restoration",
                },
                "corridor_alpha_applied": False,
                "internal_road_and_parcel_cores_exact": True,
            },
            "highland_color_match_shift_rgb": highland_shift,
            "fields_color_match_shift_rgb_per_parcel": fields_shifts,
            "boundary_transition": {
                "per_semantic": transition_contract,
                "padded_distance_transform": True,
            },
            "highland_fully_editable_support": {
                "method": (
                    "boundary_locked_alpha(highland_edit, "
                    "full_by_px=HIGHLAND_ALPHA_FULL_BY_PX, "
                    "locked_boundary_px=HIGHLAND_ALPHA_LOCKED_BOUNDARY_PX) == 1.0"
                ),
                "locked_boundary_px": HIGHLAND_ALPHA_LOCKED_BOUNDARY_PX,
                "full_by_px": HIGHLAND_ALPHA_FULL_BY_PX,
                "alpha_value": 1.0,
                "pixels": int(np.count_nonzero(alphas["highland"] == 1.0)),
            },
            "maximum_alpha": {
                name: round(float(alpha.max()), 6)
                for name, alpha in alphas.items()
            },
            "global_transform_applied": False,
        },
        "identity": {
            "changed_outside_permission_union_pixels": changed_outside,
            "changed_protected_feature_pixels": changed_protected,
            "changed_pixels_by_named_guard": changed_named_guards,
            "replacement_fraction": replacement,
            "accepted_v3_forest_carried_pixel_exactly": True,
            "accepted_v3_forest_differing_pixels": forest_carry_differing_pixels,
            "frozen_v10_forest_highland_carried_pixel_exactly": True,
            "frozen_v10_forest_differing_pixels": forest_v10_differing_pixels,
            "frozen_v10_highland_differing_pixels": highland_v10_differing_pixels,
            "frozen_v17_baseline": {
                "path": relative(V17_PROOF),
                "sha256": sha256(V17_PROOF),
            },
            "frozen_v17_strict_field_interiors_carried_pixel_exactly": True,
            "frozen_v17_strict_field_interior_pixels": int(
                masks["field_parcel_edit"].sum()
            ),
            "frozen_v17_strict_field_interior_differing_pixels": field_strict_interior_v17_differing_pixels,
            "frozen_v17_differing_pixels": v17_differing_pixels,
            "frozen_v17_differing_pixels_outside_field_restore_scope": v17_differing_outside_field_restore_scope_pixels,
            "frozen_v17_differing_pixels_inside_field_restore_scope": v17_differing_inside_field_restore_scope_pixels,
            "field_restore_scope_pixels": int(field_restore_scope.sum()),
            "field_legacy_margin_scope_pixels": int(field_legacy_margin_scope.sum()),
            "field_channel_outside_strict_k2_exact": True,
            "field_channel_outside_strict_k2_differing_pixels": field_channel_outside_strict_k2_differing_pixels,
            "field_legacy_margin_k2_exact": True,
            "field_legacy_margin_k2_differing_pixels": field_legacy_margin_k2_differing_pixels,
            "corridor_k2_exact": True,
            "corridor_k2_differing_pixels": corridor_k2_differing_pixels,
            "boundary_channel_delta": boundary,
            "raw_final_byte_identical": True,
        },
        "artifacts": {
            "raw": {"path": relative(TEMP_RAW), "sha256": sha256(TEMP_RAW)},
            "final": {"path": relative(TEMP_FINAL), "sha256": sha256(TEMP_FINAL)},
            "masks": artifacts,
        },
    }
    atomic_json(TEMP_RECEIPT, receipt)
    if any(path.exists() for path in (RAW, FINAL, RECEIPT, AUDIT)):
        raise K3BuildError("temporary proof unexpectedly emitted a persistent K3 artifact")
    return receipt


def build_candidate(allow_output: bool) -> dict[str, Any]:
    if not allow_output:
        raise K3BuildError("K3 output is held; pass --allow-output only after root authorization")
    raise K3BuildError(
        "persistent K3 raster writing remains intentionally disabled; only the "
        "separate --temporary-proof path is authorized in this turn"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--temporary-proof", action="store_true", help="write fixed tmp-only review evidence")
    actions.add_argument("--allow-output", action="store_true", help="request the still disabled persistent path")
    parser.add_argument("--replace-temporary", action="store_true", help="replace an existing fixed tmp-only proof")
    parser.add_argument("--preflight-root", type=Path, default=PREFLIGHT_ROOT)
    args = parser.parse_args()
    if args.replace_temporary and not args.temporary_proof:
        parser.error("--replace-temporary requires --temporary-proof")
    if args.temporary_proof:
        receipt = build_temporary_proof(replace=args.replace_temporary)
        print(json.dumps({
            "status": receipt["status"],
            "path": receipt["artifacts"]["final"]["path"],
            "sha256": receipt["artifacts"]["final"]["sha256"],
            "persistent_candidate_emitted": receipt["persistent_candidate_emitted"],
        }, indent=2))
    elif args.allow_output:
        build_candidate(allow_output=True)
    else:
        report = prepare(args.preflight_root)
        print(json.dumps({
            "status": report["status"],
            "source": report["source"],
            "edit_union_fraction": report["mask_contract"]["edit_union_fraction"],
            "all_donors_ready": report["all_donors_ready"],
            "candidate_emitted": report["candidate_emitted"],
        }, indent=2))


if __name__ == "__main__":
    main()
