#!/usr/bin/env python3
"""Hermetically replay the byte-frozen K3 sparse-ridgeline v19 raster.

The promoter copies this single file and every declared authority into an
otherwise empty scratch directory.  Consequently this module deliberately has
no project-local imports and resolves no repository-relative inputs.  Every
byte read by the renderer must be named and SHA-256-bound by the replay
contract.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import PIL
from PIL import Image


WIDTH, HEIGHT = 1536, 1024
SHAPE = (HEIGHT, WIDTH, 3)
INTERFACE = "sstory-k3-sparse-ridgeline-v19-replay-v2"
SCHEMA_VERSION = "1.0.0"
PNG_OPTIONS = {"format": "PNG", "compress_level": 9, "optimize": False}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

EXPECTED_RUNTIME = {
    "python_major_minor": "3.12",
    "opencv": "4.13.0",
    "numpy": "2.3.5",
    "pillow": "12.3.0",
}
EXPECTED_BASE_SHA256 = (
    "013320af2f3296200a7d0b179e3a495f1e7905462213a6c645d85669dec02882"
)
EXPECTED_LAYOUT_SHA256 = (
    "2ae715fc2800a03adde89a26bd3d663f1bafe179ed845cef09dd616ed1453d3f"
)
EXPECTED_CANONICAL_BODY_CONTROL_SHA256 = (
    "7527b0be4d7a042c5fd33e499b96806bcbbd6a1b614086c7c0fbdf308b83666b"
)
EXPECTED_CONTROL_ATLAS_METADATA_SHA256 = (
    "f9a1eab4a8e417bcd688ceae8db1e8f01dc21835842e69339dda70f461eab768"
)
EXPECTED_PROMPT_SHA256 = (
    "6a4dc3cc69ff4b6a2f03edd76a1408c839ad32a6497726aff7c4057e81a5ac43"
)
EXPECTED_GENERATION_RECEIPT_SHA256 = (
    "05b9c19008daf348e17850322f3052ff023652c2709e53127e9f64500478dc09"
)
EXPECTED_PIXEL_SHA256 = (
    "f613b6579c637b6f93f12b7ffd332fd79e0b1cba1f5f992b578bf74adcedd1c3"
)
EXPECTED_PNG_SHA256 = (
    "f2cb6e72ad1fb6e46a8ef0ed881418fd2f7d465edc514113d498714d4d94820a"
)
EXPECTED_PNG_BYTES = 3_630_310

AUTHORITY_SHA256 = {
    "canonical-k3-spec": "49d681f16f061583638a778a0fd0fc8b7b3a977d21320ee0c51b9b593040890e",
    "v55-root-vision-review": "626ea739be2aa63a55d73f31064ef697301db4244a6102834b7886930e76cd90",
    "v55-robust-recipe-verification": "64de26a0b9ee59e3a6e100297802a201d3a14db9fff022c097d6e881015a6fd3",
    "v52-control-atlas": "c168f1419d04ffaff313433064bab2b12844041e3845540c8bb6e29c2ef317c4",
    "v55-copperplate-material-reference": "c7fcd3da5fba6fe08f10fd1e0fe16bdb2884a0a04386de828f923d660de8f1a2",
    "v55-palette-parchment-reference": "b4fc951af5d29c78bb98b5ee5007395b5fc3c1addc7070d76ac8074545259837",
}
IMAGE_AUTHORITY_ROLES = frozenset(
    {
        "v52-control-atlas",
        "v55-copperplate-material-reference",
        "v55-palette-parchment-reference",
    }
)

GENERATION_RECEIPT_ID = "k3-v55-contour-atlas-source"

ROAD_CALM_PX = 18
HIGHLAND_ALPHA_LOCKED_BOUNDARY_PX = 2.0
HIGHLAND_ALPHA_FULL_BY_PX = 5.0
FOUNDATION_PAPER_AMPLITUDE_L = np.float32(1.4)
FOUNDATION_PAPER_SEED = 0x3400A5
FOUNDATION_BROAD_SIGMA = 64.0
FOUNDATION_FINE_SIGMA = 1.8
FOUNDATION_FINE_CLIP_LAB = np.asarray([1.6, 0.8, 0.8], dtype=np.float32)
BODY_L_DELTA = np.float32(-35.0)
MATERIAL_CLOSE_KERNEL_PX = 9
MATERIAL_BACKGROUND_SIGMA = 3.0
MATERIAL_RELIEF_SIGMA = 7.0
MATERIAL_RELIEF_AMPLITUDE = np.float32(5.0)
MATERIAL_RELIEF_SCALE_QUANTILE = 95.0
MATERIAL_SHARP_DENOMINATOR = np.float32(80.0)
MATERIAL_RED_CHROMA_GAIN = np.float32(10.0)
MATERIAL_BLUE_CHROMA_GAIN = np.float32(-15.0)
GRAY_SEARCH_RADIUS = 4
BODY_VALUES = (32, 64, 96, 128, 160, 192, 224, 255)
EXPECTED_BODY_PIXELS = (12_370, 11_618, 11_142, 15_929, 13_473, 10_915, 9_379, 1_777)
EXPECTED_BODY_SHA256 = (
    "22411dccde51d280322d6357bf3bfd7103c83316df75d5e153c4d4628e573d94",
    "f528cfa39a95ea1f49c9cefaa35848f7ce7bb9b0939eab325501aabfd04f2f0e",
    "5c7219a4a67dd2be266011791b7ff04e2c19e996088ebd39c61760ab0e9240c9",
    "b3ff40a24077abb168a1490a1b23b8841d024243ec201a3833799bc8c7d38d81",
    "b28ce325cc9a0abffafa3c4d4cf94bb85b468973fbef972cc2f082148f657ccd",
    "6e2dcb974dfb2596c861916719c637df70b5a16095527abcaa9dba4f377f545a",
    "df6ef1892510bf62dc55d46fbe25b365e16d9ec194284245341ebcc712ea0bc9",
    "f48bab150218955f5680545bb127e388bc3daf951d4221bb1de29f062840ba1f",
)
EXPECTED_BODY_UNION_PIXELS = 86_603
EXPECTED_BODY_UNION_SHA256 = "46de962497e114d0d822ef70422c2628188a6c50c2fa73376e16f7af41f805e2"

EXPECTED_ARRAYS = {
    "permission": (241_773, "615b76de692199a4c7d4d0e07980632d695b4073e5c9d16a979e61159461c764"),
    "road_calm": (103_237, "f9171849ffd1569ad04f57e7113383f9e3d4ca5b706b53691eab844313c53528"),
    "protected": (305_163, "cb3951519bf6c57760e60135592984bf7f3ce6da0915d528fe8f74a205f28c2f"),
    "editable": (241_585, "431a98a02f523a75bdff08dd46bfcc18f63e06c2cc4b612f7552eec9f517d647"),
    "alpha": (238_028, "a844f19a26e80490529c5148712f991b78354fb65ea5117dc135725658921247"),
    "inside": (233_333, "8b53cbf60dfc4ddf867b6abbd97295b121b54d0322fa897cb09236db7a7b0452"),
    "region": (229_467, "0ddde1da6305457ed503c41afee632a431048f3ab27e6ff67c4c4920b78feced"),
    "annulus": (71_096, "22226e0f08ffcd480af7b35e3554e17c149ad6d007ad2dd6daddddc5a82cf1a9"),
    "quiet_annulus": (3_184, "5dcf64c18c2467847c7e3fe7c09e8bc68dd578d007ac9eacde62c9c969c4925f"),
    "paper_unit": (1_572_864, "1bd3a7b6679221b0f98819fb1988b308b3396b12544fe1f432c3e1f09102de52"),
    "foundation": (4_718_220, "ad19c90e324833201dcf0b3051b0c6991934ff4bc046578acaa3440addb8f3f5"),
    "body": (86_603, EXPECTED_BODY_UNION_SHA256),
    "core": (86_603, EXPECTED_BODY_UNION_SHA256),
    "candidate": (4_718_220, EXPECTED_PIXEL_SHA256),
}

EXPECTED_INTERMEDIATE_SHA256 = {
    "base_lab": "6417f7e3684df7a510b8f3254c43dcd7f71757bc6c41ac97611829ae319d49d7",
    "paper": "1bd3a7b6679221b0f98819fb1988b308b3396b12544fe1f432c3e1f09102de52",
    "broad": "ccfb6d3864675161343246f7bac4ebc77be4e232acb508902de438c202adefff",
    "smooth18": "4356e2772c3e10b06d489e87f0849d2998ad9223e0a1be4a6c72c24807943d95",
    "fine": "d83ab20f58210a7483a9f317511d735572e4bf6377e77b6a145405b9e6c9bb2a",
    "target": "949628d7c0182c27c94c20edb786e01f71a811400aae29c56d77fde9156bbfc4",
    "encoded_lab": "a177e9386f33b8ae698324fd07fd6f8bceadbdf6586155646892dc00cbc49a64",
    "encoded_rgb": "2ee902d41351d47f067269b5ec428d9beb5c5dc5be5669f590bd8054361f1bba",
    "plate": "d420a4d0ad7bee8286689f85ab829e26d09dd4e81e04c932de78baee7564d367",
    "foundation": "ad19c90e324833201dcf0b3051b0c6991934ff4bc046578acaa3440addb8f3f5",
    "foundation_lab": "ff9762aa592bdfd4d8f30dce6725815d52d4b04e00b2cc5987f5a3b6624d05da",
    "hard_target": "7484eb7fb4326d2613e7ab3ea6d0192135a6efb1d44ad1c257bfc625cee66777",
    "hard_lab": "ff6ca303e1d18ef0fa87b32304ee598942a4c7b9126a9e5ec14a0a3245f91c24",
    "hard_rgb_full": "4c5b8492c81822e20c915272a6e276901ce22427371f29727c73673bda67430e",
    "hard_candidate": "71f5d2bec73b441f820175cf7837b79cce89091a25ccd8e423d5939f743237d7",
    "hard_gray": "e4a95148678c5b3031afd9d76bc7e0e3e7e84316f3a08f89acb6bb95192e7fc0",
    "field": "a9b27c4a0cc6bf3a80702794853d5053d024e22b16088597fa4b32fd06e8b022",
    "owner": "513d81aa30e97f272466a9ce7009c01ecc40a28286aba70f770de44bd596e3d0",
    "core": EXPECTED_BODY_UNION_SHA256,
    "target_gray": "26c88c19352e2deec18d97fa9c0e9c145079bb89d4d9b2f0ac200dcd60ac5f51",
    "candidate": EXPECTED_PIXEL_SHA256,
}

FOREST = (
    (438, 0), (956, 0), (940, 78), (975, 128), (948, 194), (912, 233),
    (929, 301), (875, 353), (801, 345), (746, 372), (675, 351), (618, 369),
    (548, 337), (483, 346), (422, 300), (405, 240), (382, 186), (409, 115),
)
HIGHLAND = (
    (1012, 0), (1536, 0), (1536, 489), (1468, 477), (1396, 505),
    (1328, 470), (1254, 492), (1188, 452), (1109, 465), (1042, 425),
    (1002, 369), (1019, 302), (984, 242), (1007, 169), (981, 93),
)
FIELDS = (
    ((1032, 620), (1170, 591), (1224, 674), (1084, 711)),
    ((1183, 589), (1332, 561), (1378, 645), (1237, 672)),
    ((1351, 562), (1499, 549), (1536, 620), (1392, 644)),
    ((1085, 725), (1229, 685), (1280, 770), (1136, 811)),
    ((1246, 684), (1392, 657), (1439, 744), (1291, 771)),
    ((1410, 657), (1536, 640), (1536, 727), (1455, 743)),
    ((1143, 825), (1288, 783), (1341, 866), (1195, 907)),
    ((1305, 785), (1453, 757), (1496, 846), (1357, 865)),
)
COASTLINE = (
    (432, 0), (425, 50), (408, 92), (373, 126), (331, 162), (309, 199),
    (337, 228), (390, 252), (407, 290), (379, 329), (366, 365), (391, 401),
    (424, 431), (427, 468), (398, 502), (355, 531), (350, 568), (370, 608),
    (403, 644), (447, 676), (462, 716), (431, 752), (445, 790), (476, 824),
    (524, 850), (551, 889), (614, 918), (684, 943), (754, 1024),
)
ISLANDS = (
    ((290, 270), (327, 245), (368, 258), (380, 298), (348, 324), (304, 315)),
    ((250, 354), (302, 332), (342, 356), (331, 401), (276, 410), (238, 385)),
    ((248, 457), (296, 425), (335, 451), (326, 493), (278, 508), (235, 487)),
    ((272, 566), (320, 535), (353, 564), (345, 614), (293, 628), (254, 604)),
    ((310, 661), (350, 640), (386, 666), (383, 704), (341, 722), (305, 698)),
)
RIVER = ((797, 0), (805, 62), (789, 125), (751, 191), (731, 254), (758, 313), (710, 356), (644, 385), (605, 445), (559, 493), (525, 544))
BRANCHES = (
    ((530, 540), (483, 505), (431, 470), (378, 431), (330, 392), (280, 369)),
    ((530, 546), (478, 559), (420, 575), (363, 589), (308, 601)),
    ((535, 552), (511, 607), (478, 656), (440, 704), (397, 743)),
    ((527, 542), (462, 528), (405, 532), (347, 550), (292, 568)),
)
ROADS = (
    ((704, 511), (638, 529), (583, 570), (548, 640), (519, 711), (503, 790)),
    ((842, 372), (843, 302), (885, 226), (930, 151), (970, 83)),
    ((980, 510), (1082, 513), (1197, 534), (1320, 522), (1450, 499), (1536, 482)),
    ((932, 607), (1010, 657), (1093, 709), (1192, 757), (1300, 818), (1416, 893), (1536, 956)),
    ((842, 648), (856, 712), (846, 774), (795, 823), (712, 849), (623, 846), (562, 834)),
)
PORT = ((434, 816), (470, 790), (526, 792), (572, 824), (568, 875), (520, 901), (464, 887))
PIERS = (
    ((452, 858), (411, 883), (385, 883)),
    ((473, 879), (439, 914), (414, 914)),
    ((518, 891), (504, 930), (484, 945)),
)


class ReplayError(RuntimeError):
    """Raised before any replay output is emitted."""


@dataclass(frozen=True)
class BoundInput:
    role: str
    path: Path
    sha256: str
    data: bytes


@dataclass(frozen=True)
class ReplayInputs:
    base: np.ndarray
    layout: np.ndarray
    canonical_body_control: np.ndarray
    control_atlas_metadata: dict[str, Any]
    control_atlas: np.ndarray
    material_reference: np.ndarray
    palette_reference: np.ndarray
    bindings: dict[str, BoundInput]


@dataclass(frozen=True)
class BuildResult:
    candidate: np.ndarray
    baseline: np.ndarray
    permission: np.ndarray
    protected: np.ndarray
    road_calm: np.ndarray
    editable: np.ndarray
    alpha: np.ndarray
    inside: np.ndarray
    body: np.ndarray
    core: np.ndarray
    contour_field: np.ndarray
    contour_owner: np.ndarray
    components: tuple[dict[str, Any], ...]
    identity: dict[str, int]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def array_sha256(values: np.ndarray) -> str:
    return sha256_bytes(np.ascontiguousarray(values).tobytes())


def _assert_intermediate(name: str, values: np.ndarray) -> None:
    expected = EXPECTED_INTERMEDIATE_SHA256[name]
    actual = array_sha256(values)
    if actual != expected:
        raise ReplayError(
            f"frozen {name} intermediate changed: sha256={actual}/{expected}"
        )


def _load_json_bytes(data: bytes, label: str) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-standard numeric constant {value!r}")

    try:
        value = json.loads(data.decode("utf-8"), parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReplayError(f"{label} is not canonical UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ReplayError(f"{label} must contain one JSON object")
    return value


def _runtime_gate() -> None:
    actual = {
        "python_major_minor": ".".join(platform.python_version().split(".")[:2]),
        "opencv": cv2.__version__,
        "numpy": np.__version__,
        "pillow": PIL.__version__,
    }
    if actual != EXPECTED_RUNTIME or sys.byteorder != "little":
        raise ReplayError(
            f"byte-exact replay runtime mismatch: expected={EXPECTED_RUNTIME}, "
            f"actual={actual}, byteorder={sys.byteorder!r}"
        )
    cv2.setNumThreads(1)
    cv2.setRNGSeed(0x4538)


def _record_path(record: Any, label: str, contract_dir: Path) -> tuple[Path, str]:
    if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
        raise ReplayError(f"{label} must contain exactly path and sha256")
    raw_path, claimed = record["path"], record["sha256"]
    if not isinstance(raw_path, str) or not raw_path:
        raise ReplayError(f"{label}.path must be a non-empty string")
    if not isinstance(claimed, str) or not SHA256_PATTERN.fullmatch(claimed):
        raise ReplayError(f"{label}.sha256 must be lowercase SHA-256")
    candidate = Path(raw_path)
    candidate = candidate if candidate.is_absolute() else contract_dir / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ReplayError(f"{label} is missing or unreadable: {exc}") from exc
    if candidate.is_symlink() or not resolved.is_file():
        raise ReplayError(f"{label} must be a regular non-symlink file")
    return resolved, claimed


def _bind(record: Any, label: str, role: str, contract_dir: Path) -> BoundInput:
    path, claimed = _record_path(record, label, contract_dir)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReplayError(f"cannot read {label}: {exc}") from exc
    actual = sha256_bytes(data)
    if actual != claimed:
        raise ReplayError(f"{label} SHA-256 mismatch: expected {claimed}, got {actual}")
    return BoundInput(role=role, path=path, sha256=actual, data=data)


def _image(binding: BoundInput, label: str) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(binding.data)) as opened:
            opened.load()
            if opened.format != "PNG" or opened.mode != "RGB" or opened.size != (WIDTH, HEIGHT):
                raise ReplayError(
                    f"{label} must be RGB PNG {WIDTH}x{HEIGHT}; got "
                    f"{opened.format!r}/{opened.mode!r}/{opened.size!r}"
                )
            return np.asarray(opened, dtype=np.uint8).copy()
    except (OSError, ValueError) as exc:
        raise ReplayError(f"{label} is not a valid bound PNG: {exc}") from exc


def _indexed_image(binding: BoundInput, label: str) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(binding.data)) as opened:
            opened.load()
            if opened.format != "PNG" or opened.mode != "L" or opened.size != (WIDTH, HEIGHT):
                raise ReplayError(
                    f"{label} must be L PNG {WIDTH}x{HEIGHT}; got "
                    f"{opened.format!r}/{opened.mode!r}/{opened.size!r}"
                )
            return np.asarray(opened, dtype=np.uint8).copy()
    except (OSError, ValueError) as exc:
        raise ReplayError(f"{label} is not a valid bound indexed PNG: {exc}") from exc


def _validate_generation_receipt(binding: BoundInput) -> None:
    value = _load_json_bytes(binding.data, "generation_receipt")
    expected_keys = {
        "schema_version",
        "generation_id",
        "status",
        "authority_inventory_complete",
        "generated_at",
        "generator",
        "operation", "prompt", "references_in_call_order", "output",
        "root_vision_review", "derivation_contract",
    }
    if set(value) != expected_keys:
        raise ReplayError("generation_receipt does not have the exact closed schema")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("generation_id") != GENERATION_RECEIPT_ID
        or value.get("status") != "approved-derived-source"
        or value.get("authority_inventory_complete") is not True
        or value.get("generated_at") != "2026-07-23T06:35:28.7209071+09:00"
        or value.get("generator") != "image_gen.imagegen"
        or value.get("operation") != "controlled-contour-atlas-edit"
    ):
        raise ReplayError("generation_receipt identity/status/generator mismatch")
    prompt = value.get("prompt")
    if (
        not isinstance(prompt, dict)
        or prompt.get("sha256") != EXPECTED_PROMPT_SHA256
        or prompt.get("exact_prompt_preserved") is not True
    ):
        raise ReplayError("generation_receipt prompt/output binding mismatch")
    output = value.get("output")
    if (
        not isinstance(output, dict)
        or output.get("sha256") != EXPECTED_LAYOUT_SHA256
        or output.get("bytes") != 2_096_511
        or output.get("size") != [WIDTH, HEIGHT]
        or output.get("mode") != "RGB"
    ):
        raise ReplayError("generation_receipt output binding mismatch")
    review = value.get("root_vision_review")
    if (
        not isinstance(review, dict)
        or review.get("sha256") != AUTHORITY_SHA256["v55-root-vision-review"]
        or review.get("decision") != "approved-only-as-derived-contour-topology-source"
        or review.get("score") != 95
        or review.get("direct_golden_accepted") is not False
    ):
        raise ReplayError("generation_receipt Root Vision binding mismatch")
    references = value.get("references_in_call_order")
    if not isinstance(references, list) or len(references) != 1:
        raise ReplayError("generation_receipt reference inventory changed")
    reference = references[0]
    if (
        not isinstance(reference, dict)
        or reference.get("role") != "exact-eight-affine-control-atlas"
        or reference.get("sha256") != AUTHORITY_SHA256["v52-control-atlas"]
    ):
        raise ReplayError("generation_receipt reference order or SHA-256 changed")
    derivation = value.get("derivation_contract")
    metadata = derivation.get("control_metadata", {}) if isinstance(derivation, dict) else {}
    if (
        not isinstance(derivation, dict)
        or metadata.get("sha256") != EXPECTED_CONTROL_ATLAS_METADATA_SHA256
        or derivation.get("source_role") != "topology-and-line-material-authority-only"
        or derivation.get("atlas_layout_or_background_must_not_be_promoted") is not True
        or derivation.get("reverse_each_body_with_recorded_atlas_to_source_affine") is not True
        or derivation.get("restore_protected_and_outside_pixels_from_v18") is not True
        or derivation.get("direct_golden_accepted") is not False
    ):
        raise ReplayError("generation_receipt derivation contract changed")


def _validate_control_atlas_metadata(value: dict[str, Any]) -> None:
    if (
        value.get("schema") != "k3-v52-imagegen-control-atlas-recipe-v1"
        or value.get("status") != "accepted-as-persistent-control-and-hermetic-replay-authority"
        or value.get("authority_inventory_complete") is not True
    ):
        raise ReplayError("control_atlas_metadata identity/status changed")
    guide = value.get("guide", {})
    canonical = value.get("canonical_body_control", {})
    validation = value.get("validation", {})
    if (
        guide.get("sha256") != AUTHORITY_SHA256["v52-control-atlas"]
        or guide.get("width") != WIDTH or guide.get("height") != HEIGHT
        or guide.get("mode") != "RGB"
        or canonical.get("sha256") != EXPECTED_CANONICAL_BODY_CONTROL_SHA256
        or canonical.get("bytes") != 6_154
        or canonical.get("width") != WIDTH or canonical.get("height") != HEIGHT
        or canonical.get("mode") != "L"
        or canonical.get("background_value") != 0
        or canonical.get("body_values_in_order") != list(BODY_VALUES)
        or canonical.get("anti_alias") is not False
        or canonical.get("union_pixels") != EXPECTED_BODY_UNION_PIXELS
        or canonical.get("union_sha256_uint8") != EXPECTED_BODY_UNION_SHA256
        or validation.get("source_body_count") != 8
        or validation.get("atlas_body_count") != 8
        or validation.get("source_bodies_separated") is not True
        or validation.get("atlas_bodies_separated") is not True
        or validation.get("affine_inverse_recorded_per_body") is not True
    ):
        raise ReplayError("control_atlas_metadata binding/validation changed")
    bodies = value.get("bodies")
    if not isinstance(bodies, list) or len(bodies) != 8:
        raise ReplayError("control_atlas_metadata must describe exactly eight bodies")
    for index, (record, body_value, pixels, digest) in enumerate(
        zip(bodies, BODY_VALUES, EXPECTED_BODY_PIXELS, EXPECTED_BODY_SHA256, strict=True),
        start=1,
    ):
        if (
            not isinstance(record, dict)
            or record.get("body_id") != f"body-{index:02d}"
            or record.get("canonical_control_value") != body_value
            or record.get("source_mask_pixels") != pixels
            or record.get("source_mask_sha256_uint8") != digest
            or np.asarray(record.get("source_to_atlas_affine"), dtype=object).shape != (2, 3)
            or np.asarray(record.get("atlas_to_source_affine"), dtype=object).shape != (2, 3)
            or record.get("resampling") != "OpenCV INTER_NEAREST"
        ):
            raise ReplayError(f"control_atlas_metadata body-{index:02d} changed")


def _validate_authority_documents(
    bindings: dict[str, BoundInput], metadata: dict[str, Any]
) -> None:
    spec = _load_json_bytes(bindings["canonical-k3-spec"].data, "canonical-k3-spec")
    if spec.get("schema_version") != SCHEMA_VERSION or spec.get("id") != "style-candidate-k-v3-semantic-cleanup":
        raise ReplayError("canonical K3 specification identity changed")
    if spec.get("source", {}).get("sha256") != "25b8d6211d1f2970cd59af363c521429863c340780d182253d161a951ed9eb92":
        raise ReplayError("canonical K3 specification source lock changed")

    review = _load_json_bytes(bindings["v55-root-vision-review"].data, "v55-root-vision-review")
    if (
        review.get("image_sha256") != EXPECTED_LAYOUT_SHA256
        or review.get("dimensions") != [WIDTH, HEIGHT]
        or review.get("mode") != "RGB"
        or review.get("decision") != "approved-only-as-derived-contour-topology-source"
        or review.get("golden_reference") is not False
        or review.get("total_score") != 95
        or review.get("observed_landform_count") != 8
    ):
        raise ReplayError("v55 Root Vision review contract changed")
    required = review.get("required_derivation")
    if not isinstance(required, list) or len(required) != 4:
        raise ReplayError("v55 Root Vision derivation requirements are incomplete")

    proof = _load_json_bytes(
        bindings["v55-robust-recipe-verification"].data,
        "v55-robust-recipe-verification",
    )
    active_sources = proof.get("active_sources", {})
    recipe = proof.get("recipe", {})
    geometry = proof.get("geometry", {})
    material = proof.get("material_transfer", {})
    intermediate = proof.get("intermediate_sha256", {})
    metrics = proof.get("metrics", {})
    determinism = proof.get("determinism", {})
    identity = proof.get("identity", {})
    gates = proof.get("gates", {})
    if (
        proof.get("source", {}).get("sha256") != EXPECTED_LAYOUT_SHA256
        or proof.get("status") != "passed-write-free-preflight"
        or active_sources.get("canonical_body_control", {}).get("sha256")
        != EXPECTED_CANONICAL_BODY_CONTROL_SHA256
        or active_sources.get("control_atlas_metadata", {}).get("sha256")
        != EXPECTED_CONTROL_ATLAS_METADATA_SHA256
        or active_sources.get("generated_contour_atlas", {}).get("sha256")
        != EXPECTED_LAYOUT_SHA256
        or recipe.get("foundation", {}).get("paper_amplitude_lab_l") != 1.4
        or recipe.get("body_l_delta") != -35.0
        or recipe.get("material_transfer", {}).get("close_kernel_px")
        != MATERIAL_CLOSE_KERNEL_PX
        or recipe.get("material_transfer", {}).get("background_sigma_px")
        != MATERIAL_BACKGROUND_SIGMA
        or recipe.get("material_transfer", {}).get("relief_sigma_px")
        != MATERIAL_RELIEF_SIGMA
        or recipe.get("material_transfer", {}).get("relief_amplitude_gray")
        != float(MATERIAL_RELIEF_AMPLITUDE)
        or recipe.get("material_transfer", {}).get("sharp_ink_denominator")
        != float(MATERIAL_SHARP_DENOMINATOR)
        or recipe.get("material_transfer", {}).get("red_chroma_gain")
        != float(MATERIAL_RED_CHROMA_GAIN)
        or recipe.get("material_transfer", {}).get("blue_chroma_gain")
        != float(MATERIAL_BLUE_CHROMA_GAIN)
        or geometry.get("selected_component_count") != 8
        or geometry.get("per_body_pixels") != list(EXPECTED_BODY_PIXELS)
        or geometry.get("body_pixels") != EXPECTED_BODY_UNION_PIXELS
        or geometry.get("mask_sha256") != EXPECTED_ARRAYS["body"][1]
        or material.get("total_pixels") != EXPECTED_BODY_UNION_PIXELS
        or material.get("nonempty_body_count") != 8
        or material.get("per_body_pixels") != list(EXPECTED_BODY_PIXELS)
        or material.get("outside_carrier_pixels") != 0
        or material.get("mask_sha256") != EXPECTED_ARRAYS["core"][1]
        or intermediate.get("field") != EXPECTED_INTERMEDIATE_SHA256["field"]
        or intermediate.get("owner") != EXPECTED_INTERMEDIATE_SHA256["owner"]
        or intermediate.get("target_gray")
        != EXPECTED_INTERMEDIATE_SHA256["target_gray"]
        or intermediate.get("candidate") != EXPECTED_PIXEL_SHA256
        or metrics.get("coverage_50") != 367
        or metrics.get("coverage_25") != 338
        or metrics.get("quiet_fraction") != 0.912177
        or metrics.get("dash_bundle_pairs") != 0
        or metrics.get("orientation_coherence") != 0.05625
        or metrics.get("texture_inside_to_outside_ratio", {}).get("4") != 0.614135
        or metrics.get("texture_inside_to_outside_ratio", {}).get("8") != 0.981493
        or determinism.get("expected_raw_rgb_sha256") != EXPECTED_PIXEL_SHA256
        or determinism.get("expected_png_sha256") != EXPECTED_PNG_SHA256
        or determinism.get("expected_png_bytes") != EXPECTED_PNG_BYTES
        or determinism.get("passed") is not True
        or any(
            gates.get(key) is not True
            for key in (
                "fixed_passed",
                "preferred_passed",
                "robust_margin_passed",
                "exactly_eight_bodies",
                "all_material_pixels_transferred",
                "all_material_support_inside_carrier",
                "all_body_luminance_deltas_dark_only",
                "material_target_gray_exact",
                "outside_permission_exact",
                "protected_features_exact",
                "road_calm_18px_exact",
                "alpha_zero_exact",
            )
        )
        or any(
            identity.get(key) != 0
            for key in (
                "outside_permission",
                "protected_features",
                "road_calm_18px",
                "alpha_zero_changed",
                "body_outside_full_alpha",
                "contour_outside_body",
                "contour_grayscale_mismatch",
            )
        )
    ):
        raise ReplayError("v55 robust recipe authority changed")
    _validate_control_atlas_metadata(metadata)


def load_replay_inputs(contract_path: Path) -> ReplayInputs:
    _runtime_gate()
    try:
        contract_bytes = contract_path.resolve(strict=True).read_bytes()
    except OSError as exc:
        raise ReplayError(f"cannot read replay contract: {exc}") from exc
    contract = _load_json_bytes(contract_bytes, "replay contract")
    exact_keys = {
        "schema_version", "interface", "base_v18", "generated_layout_control",
        "canonical_body_control", "control_atlas_metadata", "imagegen_prompt",
        "generation_receipt", "authorities",
    }
    if set(contract) != exact_keys:
        raise ReplayError("replay contract must contain the exact closed input graph")
    if contract.get("schema_version") != SCHEMA_VERSION or contract.get("interface") != INTERFACE:
        raise ReplayError("replay contract interface/schema mismatch")
    contract_dir = contract_path.resolve().parent
    bindings: dict[str, BoundInput] = {}
    bindings["base_v18"] = _bind(contract["base_v18"], "base_v18", "base_v18", contract_dir)
    bindings["generated_layout_control"] = _bind(
        contract["generated_layout_control"], "generated_layout_control",
        "generated_layout_control", contract_dir,
    )
    bindings["canonical_body_control"] = _bind(
        contract["canonical_body_control"], "canonical_body_control",
        "canonical_body_control", contract_dir,
    )
    bindings["control_atlas_metadata"] = _bind(
        contract["control_atlas_metadata"], "control_atlas_metadata",
        "control_atlas_metadata", contract_dir,
    )
    bindings["imagegen_prompt"] = _bind(
        contract["imagegen_prompt"], "imagegen_prompt", "imagegen_prompt", contract_dir
    )
    bindings["generation_receipt"] = _bind(
        contract["generation_receipt"], "generation_receipt", "generation_receipt", contract_dir
    )
    if bindings["base_v18"].sha256 != EXPECTED_BASE_SHA256:
        raise ReplayError("base_v18 is not the frozen v18 authority")
    if bindings["generated_layout_control"].sha256 != EXPECTED_LAYOUT_SHA256:
        raise ReplayError("generated_layout_control is not the frozen v55 source")
    if bindings["canonical_body_control"].sha256 != EXPECTED_CANONICAL_BODY_CONTROL_SHA256:
        raise ReplayError("canonical_body_control is not the frozen indexed authority")
    if bindings["control_atlas_metadata"].sha256 != EXPECTED_CONTROL_ATLAS_METADATA_SHA256:
        raise ReplayError("control_atlas_metadata is not the frozen affine authority")
    if bindings["imagegen_prompt"].sha256 != EXPECTED_PROMPT_SHA256:
        raise ReplayError("imagegen_prompt is not the exact v55 prompt")
    if bindings["generation_receipt"].sha256 != EXPECTED_GENERATION_RECEIPT_SHA256:
        raise ReplayError("generation_receipt is not the frozen v55 receipt")

    raw_authorities = contract.get("authorities")
    if not isinstance(raw_authorities, list):
        raise ReplayError("authorities must be an array")
    roles: set[str] = set()
    for index, raw in enumerate(raw_authorities):
        if not isinstance(raw, dict) or set(raw) != {"role", "path", "sha256"}:
            raise ReplayError(f"authorities[{index}] must contain exactly role/path/sha256")
        role = raw.get("role")
        if not isinstance(role, str) or role in roles:
            raise ReplayError(f"authorities[{index}] has a missing or duplicate role")
        roles.add(role)
        binding = _bind(
            {"path": raw["path"], "sha256": raw["sha256"]},
            f"authorities[{index}]/{role}", role, contract_dir,
        )
        expected_sha = AUTHORITY_SHA256.get(role)
        if expected_sha is None or binding.sha256 != expected_sha:
            raise ReplayError(f"authority role or frozen SHA-256 mismatch: {role!r}")
        bindings[role] = binding
    if roles != set(AUTHORITY_SHA256):
        raise ReplayError(
            f"authority role set mismatch: missing={sorted(set(AUTHORITY_SHA256)-roles)}, "
            f"extra={sorted(roles-set(AUTHORITY_SHA256))}"
        )
    metadata = _load_json_bytes(
        bindings["control_atlas_metadata"].data, "control_atlas_metadata"
    )
    _validate_generation_receipt(bindings["generation_receipt"])
    _validate_authority_documents(bindings, metadata)
    authority_images = {
        role: _image(bindings[role], role) for role in IMAGE_AUTHORITY_ROLES
    }
    base = _image(bindings["base_v18"], "base_v18")
    layout = _image(bindings["generated_layout_control"], "generated_layout_control")
    return ReplayInputs(
        base=base,
        layout=layout,
        canonical_body_control=_indexed_image(
            bindings["canonical_body_control"], "canonical_body_control"
        ),
        control_atlas_metadata=metadata,
        control_atlas=authority_images["v52-control-atlas"],
        material_reference=authority_images["v55-copperplate-material-reference"],
        palette_reference=authority_images["v55-palette-parchment-reference"],
        bindings=bindings,
    )


def disk(radius: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))


def dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    return cv2.dilate(mask.astype(np.uint8), disk(radius)) > 0


def erode(mask: np.ndarray, radius: int) -> np.ndarray:
    return cv2.erode(mask.astype(np.uint8), disk(radius)) > 0


def polygon_mask(points: Any) -> np.ndarray:
    result = np.zeros((HEIGHT, WIDTH), np.uint8)
    cv2.fillPoly(result, [np.asarray(points, np.int32)], 255)
    return result > 0


def line_mask(lines: Any, width: int, *, closed: bool = False, antialiased: bool = True) -> np.ndarray:
    result = np.zeros((HEIGHT, WIDTH), np.uint8)
    line_type = cv2.LINE_AA if antialiased else cv2.LINE_8
    for points in lines:
        cv2.polylines(result, [np.asarray(points, np.int32)], closed, 255, width, line_type)
    return result > 0


def gaussian(values: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(
        values.astype(np.float32), (0, 0), sigmaX=sigma, sigmaY=sigma,
        borderType=cv2.BORDER_REFLECT,
    )


def boundary_locked_alpha(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask.astype(np.uint8), 1, mode="constant", constant_values=0)
    distance = cv2.distanceTransform(padded, cv2.DIST_L2, 5)[1:-1, 1:-1]
    value = np.clip(
        (distance - HIGHLAND_ALPHA_LOCKED_BOUNDARY_PX)
        / (HIGHLAND_ALPHA_FULL_BY_PX - HIGHLAND_ALPHA_LOCKED_BOUNDARY_PX),
        0.0, 1.0,
    )
    alpha = value * value * (3.0 - 2.0 * value)
    alpha[~mask] = 0.0
    return alpha.astype(np.float32)


def composite_with_alpha(base: np.ndarray, donor: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    result = base.copy()
    selected = alpha > 0
    weight = alpha[selected][:, None]
    result[selected] = np.clip(
        np.rint(base[selected].astype(np.float32) * (1.0 - weight) + donor[selected].astype(np.float32) * weight),
        0, 255,
    ).astype(np.uint8)
    return result


def derive_controls() -> dict[str, np.ndarray]:
    forest_shape = polygon_mask(FOREST)
    highland_shape = polygon_mask(HIGHLAND)
    field_shapes = [polygon_mask(points) for points in FIELDS]
    coast_guard = dilate(line_mask((COASTLINE,), 5), 12)
    island_guard = dilate(line_mask(ISLANDS, 5, closed=True), 12)
    water_guard = dilate(line_mask((RIVER,), 37) | line_mask(BRANCHES, 24), 12)
    road_guard_aa = line_mask(ROADS, 12)
    road_context = dilate(road_guard_aa, 12)
    exact_road_core = line_mask(ROADS, 4, antialiased=False)
    city = np.zeros((HEIGHT, WIDTH), np.uint8)
    cv2.circle(city, (842, 510), 143, 255, -1, cv2.LINE_8)
    city_guard = dilate(city > 0, 8)
    port_guard = dilate(polygon_mask(PORT) | line_mask(PIERS, 7), 12)
    canvas_guard = np.zeros((HEIGHT, WIDTH), bool)
    canvas_guard[:8, :] = True
    canvas_guard[-8:, :] = True
    canvas_guard[:, :8] = True
    canvas_guard[:, -8:] = True
    field_boundary = line_mask(FIELDS, 1, closed=True, antialiased=False)
    legacy_fields = [
        shape & ~exact_road_core & ~field_boundary & ~canvas_guard
        for shape in field_shapes
    ]
    fields_edit = np.logical_or.reduce([erode(item, 12) for item in legacy_fields])
    permission = highland_shape & ~road_context & ~city_guard & ~canvas_guard
    protected = (
        coast_guard | island_guard | water_guard | exact_road_core | city_guard
        | port_guard | field_boundary | canvas_guard
    )
    road_calm = dilate(exact_road_core, ROAD_CALM_PX)
    editable = permission & ~road_calm & ~protected
    alpha = boundary_locked_alpha(permission)
    alpha *= editable.astype(np.float32)
    inside = boundary_locked_alpha(permission) == np.float32(1.0)
    return {
        "forest_shape": forest_shape,
        "fields_edit": fields_edit,
        "coast_guard": coast_guard,
        "water_guard": water_guard,
        "permission": permission,
        "protected": protected,
        "road_calm": road_calm,
        "editable": editable,
        "alpha": alpha,
        "inside": inside,
    }


def paper_authority_mask(baseline_l: np.ndarray, controls: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    permission = controls["permission"]
    outside_distance = cv2.distanceTransform((~permission).astype(np.uint8), cv2.DIST_L2, 5)
    excluded = (
        controls["protected"] | controls["road_calm"]
        | dilate(controls["water_guard"], 12) | dilate(controls["coast_guard"], 8)
        | controls["forest_shape"] | controls["fields_edit"]
    )
    annulus = (~permission) & (outside_distance >= 20.0) & (outside_distance <= 180.0) & ~excluded
    gradient = np.hypot(
        cv2.Sobel(baseline_l, cv2.CV_32F, 1, 0, ksize=3),
        cv2.Sobel(baseline_l, cv2.CV_32F, 0, 1, ksize=3),
    )
    residual = baseline_l - gaussian(baseline_l, 8.0)
    gradient_limit = float(np.percentile(gradient[annulus], 15.0))
    residual_limit = float(np.percentile(np.abs(residual[annulus]), 25.0))
    quiet = annulus & (gradient <= gradient_limit) & (np.abs(residual) <= residual_limit)
    if int(quiet.sum()) < 2048:
        raise ReplayError("safe v18 paper-authority annulus is too small")
    return annulus, quiet


def splitmix64_array(values: np.ndarray) -> np.ndarray:
    values = values.astype(np.uint64, copy=False)
    values = values + np.uint64(0x9E3779B97F4A7C15)
    values = (values ^ (values >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    values = (values ^ (values >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return values ^ (values >> np.uint64(31))


def synthesize_isotropic_paper(baseline_l: np.ndarray, annulus: np.ndarray, quiet: np.ndarray) -> np.ndarray:
    residual = baseline_l - gaussian(baseline_l, 8.0)
    quiet_values = residual[quiet].astype(np.float64)
    center = float(np.median(quiet_values))
    low, high = np.percentile(quiet_values - center, (1.0, 99.0))
    spectral_source = np.clip(residual - center, low, high) * annulus.astype(np.float32)
    power = np.abs(np.fft.fft2(spectral_source)) ** 2 / max(int(annulus.sum()), 1)
    fy = np.fft.fftfreq(HEIGHT) * HEIGHT
    fx = np.fft.fftfreq(WIDTH) * WIDTH
    radius = np.rint(np.hypot(fy[:, None], fx[None, :])).astype(np.int32)
    radial_sum = np.bincount(radius.ravel(), weights=power.ravel())
    radial_count = np.bincount(radius.ravel())
    radial_power = radial_sum / np.maximum(radial_count, 1)
    radial_power = cv2.GaussianBlur(
        radial_power.astype(np.float32).reshape(1, -1), (0, 0),
        sigmaX=1.5, sigmaY=0.0, borderType=cv2.BORDER_REFLECT,
    ).ravel()
    radial_power[:3] = 0.0
    amplitude = np.sqrt(np.maximum(radial_power[radius], 0.0))
    yy, xx = np.indices((HEIGHT, WIDTH), dtype=np.uint64)
    hashed = splitmix64_array(
        xx * np.uint64(0xD6E8FEB86659FD93)
        ^ yy * np.uint64(0xA5A3564E27F8862D)
        ^ np.uint64(FOUNDATION_PAPER_SEED)
    )
    white = ((hashed >> np.uint64(11)).astype(np.float64) / float(1 << 53)) - 0.5
    white_fft = np.fft.fft2(white)
    phase = white_fft / np.maximum(np.abs(white_fft), 1e-12)
    synthesized = np.fft.ifft2(amplitude * phase).real.astype(np.float32)
    synthesized -= float(np.mean(synthesized))
    order = np.argsort(synthesized, axis=None, kind="stable")
    learned = np.sort(np.clip(quiet_values - center, low, high))
    quantiles = np.linspace(0.0, 1.0, learned.size, dtype=np.float64)
    targets = np.interp(
        np.linspace(0.0, 1.0, synthesized.size, dtype=np.float64),
        quantiles, learned,
    ).astype(np.float32)
    mapped = np.empty(synthesized.size, np.float32)
    mapped[order] = targets
    mapped = mapped.reshape(synthesized.shape)
    mapped -= float(np.mean(mapped))
    return (mapped / max(float(np.percentile(np.abs(mapped), 95.0)), 1e-6)).astype(np.float32)


def build_foundation(baseline: np.ndarray, controls: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    baseline_lab = cv2.cvtColor(baseline, cv2.COLOR_RGB2LAB).astype(np.float32)
    _assert_intermediate("base_lab", baseline_lab)
    annulus, quiet = paper_authority_mask(baseline_lab[..., 0], controls)
    paper = synthesize_isotropic_paper(baseline_lab[..., 0], annulus, quiet)
    _assert_intermediate("paper", paper)
    weight = controls["editable"].astype(np.float32)

    def normalized_broad(values: np.ndarray) -> np.ndarray:
        numerator = cv2.GaussianBlur(
            values * weight, (0, 0), sigmaX=FOUNDATION_BROAD_SIGMA,
            sigmaY=FOUNDATION_BROAD_SIGMA, borderType=cv2.BORDER_REFLECT,
        )
        denominator = cv2.GaussianBlur(
            weight, (0, 0), sigmaX=FOUNDATION_BROAD_SIGMA,
            sigmaY=FOUNDATION_BROAD_SIGMA, borderType=cv2.BORDER_REFLECT,
        )
        return numerator / np.maximum(denominator, np.float32(1e-6))

    broad = np.stack(
        [normalized_broad(baseline_lab[..., channel]) for channel in range(3)],
        axis=2,
    )
    _assert_intermediate("broad", broad)
    smooth18 = np.stack(
        [
            cv2.GaussianBlur(
                baseline_lab[..., channel], (0, 0),
                sigmaX=FOUNDATION_FINE_SIGMA, sigmaY=FOUNDATION_FINE_SIGMA,
                borderType=cv2.BORDER_REFLECT,
            )
            for channel in range(3)
        ],
        axis=2,
    )
    _assert_intermediate("smooth18", smooth18)
    fine = np.clip(
        baseline_lab - smooth18,
        -FOUNDATION_FINE_CLIP_LAB,
        FOUNDATION_FINE_CLIP_LAB,
    )
    _assert_intermediate("fine", fine)
    target = broad + fine
    target[..., 0] += FOUNDATION_PAPER_AMPLITUDE_L * paper
    _assert_intermediate("target", target)
    encoded_lab = np.clip(np.rint(target), 0, 255).astype(np.uint8)
    _assert_intermediate("encoded_lab", encoded_lab)
    encoded = cv2.cvtColor(encoded_lab, cv2.COLOR_LAB2RGB)
    _assert_intermediate("encoded_rgb", encoded)
    plate = baseline.copy()
    plate[controls["editable"]] = encoded[controls["editable"]]
    _assert_intermediate("plate", plate)
    foundation = composite_with_alpha(baseline, plate, controls["alpha"])
    foundation[controls["alpha"] == np.float32(0.0)] = baseline[
        controls["alpha"] == np.float32(0.0)
    ]
    _assert_intermediate("foundation", foundation)
    return foundation, annulus, quiet, paper


def _assert_array(name: str, values: np.ndarray) -> None:
    expected_count, expected_sha = EXPECTED_ARRAYS[name]
    count = int(np.count_nonzero(values))
    digest = array_sha256(values)
    if count != expected_count or digest != expected_sha:
        raise ReplayError(
            f"frozen {name} invariant changed: count={count}/{expected_count}, "
            f"sha256={digest}/{expected_sha}"
        )


def _enforce_locks(candidate: np.ndarray, baseline: np.ndarray, controls: dict[str, np.ndarray]) -> None:
    alpha_zero = controls["alpha"] == np.float32(0.0)
    candidate[alpha_zero] = baseline[alpha_zero]
    candidate[~controls["permission"]] = baseline[~controls["permission"]]
    candidate[controls["protected"] | controls["road_calm"]] = baseline[
        controls["protected"] | controls["road_calm"]
    ]


def _decode_body_masks(
    indexed: np.ndarray, metadata: dict[str, Any]
) -> tuple[list[np.ndarray], np.ndarray, list[dict[str, Any]]]:
    observed_values = tuple(int(value) for value in np.unique(indexed))
    if observed_values != (0, *BODY_VALUES):
        raise ReplayError(f"canonical body control values changed: {observed_values}")
    body_masks: list[np.ndarray] = []
    components: list[dict[str, Any]] = []
    union = np.zeros((HEIGHT, WIDTH), dtype=bool)
    for index, (value, expected_pixels, expected_digest, metadata_record) in enumerate(
        zip(
            BODY_VALUES,
            EXPECTED_BODY_PIXELS,
            EXPECTED_BODY_SHA256,
            metadata["bodies"],
            strict=True,
        ),
        start=1,
    ):
        body = indexed == value
        pixels = int(body.sum())
        digest = array_sha256(body.astype(np.uint8))
        if pixels != expected_pixels or digest != expected_digest:
            raise ReplayError(
                f"canonical body-{index:02d} changed: pixels={pixels}/{expected_pixels}, "
                f"sha256={digest}/{expected_digest}"
            )
        if np.any(union & body):
            raise ReplayError(f"canonical body-{index:02d} overlaps a prior body")
        union |= body
        body_masks.append(body)
        components.append(
            {
                "body_id": f"body-{index:02d}",
                "canonical_control_value": value,
                "body_pixels": pixels,
                "body_sha256": digest,
                "source_to_atlas_affine": metadata_record["source_to_atlas_affine"],
                "atlas_to_source_affine": metadata_record["atlas_to_source_affine"],
            }
        )
    if (
        int(union.sum()) != EXPECTED_BODY_UNION_PIXELS
        or array_sha256(union.astype(np.uint8)) != EXPECTED_BODY_UNION_SHA256
    ):
        raise ReplayError("canonical eight-body union changed")
    return body_masks, union, components


def _hard_body_foundation(
    foundation: np.ndarray,
    body: np.ndarray,
    baseline: np.ndarray,
    controls: dict[str, np.ndarray],
) -> np.ndarray:
    foundation_lab = cv2.cvtColor(foundation, cv2.COLOR_RGB2LAB).astype(np.float32)
    _assert_intermediate("foundation_lab", foundation_lab)
    target = foundation_lab.copy()
    target[..., 0][body] += BODY_L_DELTA
    _assert_intermediate("hard_target", target)
    encoded_lab = np.clip(np.rint(target), 0, 255).astype(np.uint8)
    _assert_intermediate("hard_lab", encoded_lab)
    encoded_rgb = cv2.cvtColor(encoded_lab, cv2.COLOR_LAB2RGB)
    _assert_intermediate("hard_rgb_full", encoded_rgb)
    hard = foundation.copy()
    hard[body] = encoded_rgb[body]
    _enforce_locks(hard, baseline, controls)
    _assert_intermediate("hard_candidate", hard)
    return hard


def _solve_green_for_exact_gray(
    target_gray: np.ndarray,
    red: np.ndarray,
    blue: np.ndarray,
) -> np.ndarray:
    """Solve one green channel while preserving OpenCV BT.601 gray exactly."""
    ideal = np.rint(
        (
            target_gray.astype(np.float64)
            - 0.299 * red.astype(np.float64)
            - 0.114 * blue.astype(np.float64)
        )
        / 0.587
    ).astype(np.int32)
    best = np.clip(ideal, 0, 255).astype(np.uint8)
    best_score = np.full(best.shape, 999, dtype=np.int16)
    found = np.zeros(best.shape, dtype=bool)
    for delta in range(-GRAY_SEARCH_RADIUS, GRAY_SEARCH_RADIUS + 1):
        green = np.clip(ideal + delta, 0, 255).astype(np.uint8)
        trial = np.stack((red, green, blue), axis=1)
        observed = cv2.cvtColor(
            trial.reshape(-1, 1, 3), cv2.COLOR_RGB2GRAY
        ).reshape(-1)
        score = abs(delta)
        take = (observed == target_gray) & (score < best_score)
        best[take] = green[take]
        best_score[take] = score
        found[take] = True
    if not np.all(found):
        raise ReplayError(
            "grayscale-preserving v55 material correction failed for "
            f"{int(np.count_nonzero(~found))} pixels"
        )
    return best


def _apply_v55_full_material(
    hard: np.ndarray,
    source: np.ndarray,
    body_masks: list[np.ndarray],
    metadata: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[dict[str, Any]]]:
    """Reverse-affine every v55 body pixel into its exact canonical carrier."""
    hard_gray = cv2.cvtColor(hard, cv2.COLOR_RGB2GRAY).astype(np.float32)
    _assert_intermediate("hard_gray", hard_gray)
    field = np.zeros((HEIGHT, WIDTH), dtype=np.float32)
    owner = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    target_field = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    candidate = hard.copy()
    records: list[dict[str, Any]] = []
    close_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (MATERIAL_CLOSE_KERNEL_PX, MATERIAL_CLOSE_KERNEL_PX),
    )
    for index, (body, record) in enumerate(
        zip(body_masks, metadata["bodies"], strict=True), start=1
    ):
        inverse = np.asarray(record["atlas_to_source_affine"], dtype=np.float64)
        warped = cv2.warpAffine(
            source,
            inverse,
            (WIDTH, HEIGHT),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT,
        )
        source_gray = cv2.cvtColor(warped, cv2.COLOR_RGB2GRAY).astype(np.float32)
        closed = cv2.morphologyEx(source_gray, cv2.MORPH_CLOSE, close_kernel)
        background = cv2.GaussianBlur(
            closed,
            (0, 0),
            sigmaX=MATERIAL_BACKGROUND_SIGMA,
            sigmaY=MATERIAL_BACKGROUND_SIGMA,
            borderType=cv2.BORDER_REFLECT,
        )
        ink = np.maximum(background - source_gray, np.float32(0.0))
        low = cv2.GaussianBlur(
            ink,
            (0, 0),
            sigmaX=MATERIAL_RELIEF_SIGMA,
            sigmaY=MATERIAL_RELIEF_SIGMA,
            borderType=cv2.BORDER_REFLECT,
        )
        median = float(np.median(low[body]))
        centered = low - np.float32(median)
        scale = max(
            float(
                np.percentile(
                    np.abs(centered[body]), MATERIAL_RELIEF_SCALE_QUANTILE
                )
            ),
            1e-6,
        )
        relief = (
            np.clip(centered / np.float32(scale), -1.0, 1.0)
            * MATERIAL_RELIEF_AMPLITUDE
        )
        target_gray = np.clip(
            np.rint(hard_gray + relief), 0, 255
        ).astype(np.uint8)

        values = warped[body]
        local_gray = source_gray[body]
        sharp = np.clip(
            ink[body] / MATERIAL_SHARP_DENOMINATOR, 0.0, 1.0
        )
        red_offset = (
            values[:, 0].astype(np.float32)
            - local_gray
            + MATERIAL_RED_CHROMA_GAIN * sharp
        )
        blue_offset = (
            values[:, 2].astype(np.float32)
            - local_gray
            + MATERIAL_BLUE_CHROMA_GAIN * sharp
        )
        local_target = target_gray[body].astype(np.float32)
        red = np.clip(np.rint(local_target + red_offset), 0, 255).astype(np.uint8)
        blue = np.clip(np.rint(local_target + blue_offset), 0, 255).astype(np.uint8)
        if np.any((red == 0) | (red == 255) | (blue == 0) | (blue == 255)):
            raise ReplayError(f"body-{index:02d} v55 chroma mapping clipped")
        green = _solve_green_for_exact_gray(target_gray[body], red, blue)
        output = np.stack((red, green, blue), axis=1)
        observed = cv2.cvtColor(
            output.reshape(-1, 1, 3), cv2.COLOR_RGB2GRAY
        ).reshape(-1)
        if not np.array_equal(observed, target_gray[body]):
            raise ReplayError(f"body-{index:02d} v55 material gray drifted")

        candidate[body] = output
        field[body] = relief[body]
        owner[body] = index
        target_field[body] = target_gray[body]
        records.append(
            {
                "material_pixels": int(body.sum()),
                "ink_nonzero_pixels": int(np.count_nonzero(ink[body])),
                "low_frequency_median": median,
                "low_frequency_p95_absolute_deviation": scale,
            }
        )
    _assert_intermediate("field", field)
    _assert_intermediate("owner", owner)
    _assert_intermediate("target_gray", target_field)
    _assert_intermediate("candidate", candidate)
    return candidate, field, owner, target_field, records


def reconstruct(inputs: ReplayInputs) -> BuildResult:
    baseline = inputs.base
    source = inputs.layout
    if baseline.shape != SHAPE or source.shape != SHAPE:
        raise ReplayError("bound RGB raster dimensions changed after decoding")
    if inputs.canonical_body_control.shape != (HEIGHT, WIDTH):
        raise ReplayError("canonical body control dimensions changed after decoding")
    for authority in (
        inputs.control_atlas, inputs.material_reference, inputs.palette_reference
    ):
        if authority.shape != SHAPE:
            raise ReplayError("bound authority raster dimensions changed after decoding")
    cv2.setRNGSeed(0x4538)
    controls = derive_controls()
    for name in ("permission", "road_calm", "protected", "editable", "alpha", "inside"):
        _assert_array(name, controls[name])
    foundation, annulus, quiet, paper = build_foundation(baseline, controls)
    _assert_array("annulus", annulus)
    _assert_array("quiet_annulus", quiet)
    _assert_array("paper_unit", paper)

    body_masks, body, components = _decode_body_masks(
        inputs.canonical_body_control, inputs.control_atlas_metadata
    )
    if np.any(body & ~controls["inside"]):
        raise ReplayError("a canonical body escaped official full-alpha support")
    _assert_array("body", body.astype(np.uint8))
    hard = _hard_body_foundation(foundation, body, baseline, controls)
    candidate, field, owner, target_gray, material_records = (
        _apply_v55_full_material(
            hard, source, body_masks, inputs.control_atlas_metadata
        )
    )
    core = body.copy()
    _assert_intermediate("core", core.astype(np.uint8))
    _assert_array("core", core.astype(np.uint8))
    if len(material_records) != len(components):
        raise ReplayError("v55 material record count changed")
    for component, material in zip(components, material_records, strict=True):
        component.update(material)
    _enforce_locks(candidate, baseline, controls)
    changed = np.any(candidate != baseline, axis=2)
    alpha_zero = controls["alpha"] == np.float32(0.0)
    contour_gray_mismatch = int(
        np.count_nonzero(
            cv2.cvtColor(candidate, cv2.COLOR_RGB2GRAY)[core]
            != target_gray[core]
        )
    )
    identity = {
        "changed_pixels": int(changed.sum()),
        "outside_permission": int(np.count_nonzero(changed & ~controls["permission"])),
        "protected_features": int(np.count_nonzero(changed & controls["protected"])),
        "road_calm_18px": int(np.count_nonzero(changed & controls["road_calm"])),
        "alpha_zero_changed": int(np.count_nonzero(changed & alpha_zero)),
        "body_outside_full_alpha": int(np.count_nonzero(body & ~controls["inside"])),
        "contour_outside_body": int(np.count_nonzero(core & ~body)),
        "contour_grayscale_mismatch": contour_gray_mismatch,
    }
    expected_identity = {
        "changed_pixels": 237_342,
        "outside_permission": 0,
        "protected_features": 0,
        "road_calm_18px": 0,
        "alpha_zero_changed": 0,
        "body_outside_full_alpha": 0,
        "contour_outside_body": 0,
        "contour_grayscale_mismatch": 0,
    }
    if identity != expected_identity:
        raise ReplayError(f"exact identity/lock contract changed: {identity}")
    _assert_array("candidate", candidate)
    return BuildResult(
        candidate=candidate,
        baseline=baseline.copy(),
        permission=controls["permission"],
        protected=controls["protected"],
        road_calm=controls["road_calm"],
        editable=controls["editable"],
        alpha=controls["alpha"],
        inside=controls["inside"],
        body=body,
        core=core,
        contour_field=field,
        contour_owner=owner,
        components=tuple(components),
        identity=identity,
    )


def reconstruct_from_contract(contract_path: Path) -> BuildResult:
    return reconstruct(load_replay_inputs(Path(contract_path)))


def png_bytes(candidate: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    with Image.fromarray(candidate, "RGB") as image:
        image.save(buffer, **PNG_OPTIONS)
    payload = buffer.getvalue()
    digest = sha256_bytes(payload)
    if len(payload) != EXPECTED_PNG_BYTES or digest != EXPECTED_PNG_SHA256:
        raise ReplayError(
            f"canonical PNG encoding changed: bytes={len(payload)}/{EXPECTED_PNG_BYTES}, "
            f"sha256={digest}/{EXPECTED_PNG_SHA256}"
        )
    return payload


def _atomic_new_file(path: Path, payload: bytes, input_paths: set[Path]) -> None:
    resolved_parent = path.parent.resolve()
    resolved_output = (resolved_parent / path.name).resolve()
    if resolved_output in input_paths:
        raise ReplayError("output must not overwrite a replay input")
    if path.exists() or path.is_symlink():
        raise ReplayError(f"refusing to overwrite replay output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.new-{os.getpid()}-{uuid.uuid4().hex}")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists() or path.is_symlink():
            raise ReplayError(f"replay output appeared during transaction: {path}")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def replay_to_output(contract_path: Path, output_path: Path) -> dict[str, Any]:
    contract_path = Path(contract_path)
    output_path = Path(output_path)
    inputs = load_replay_inputs(contract_path)
    result = reconstruct(inputs)
    payload = png_bytes(result.candidate)
    _atomic_new_file(
        output_path,
        payload,
        {binding.path.resolve() for binding in inputs.bindings.values()},
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "interface": INTERFACE,
        "output": str(output_path.resolve()),
        "png_sha256": sha256_bytes(payload),
        "pixel_sha256": array_sha256(result.candidate),
        "size": [WIDTH, HEIGHT],
        "mode": "RGB",
        "selected_body_count": len(result.components),
        "identity": result.identity,
        "passed": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = replay_to_output(args.replay_contract, args.output)
    except ReplayError as exc:
        parser.exit(2, f"v19 replay failed closed: {exc}\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
