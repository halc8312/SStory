#!/usr/bin/env python3
"""Render the texture-free composition guide for Golden candidate I1.

This guide is deliberately semantic and low-detail.  It carries only the
required board arrangement and networks; it is not a source of visual style,
surface material, pictorial symbols, or lettering.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-i-v1-composition-guide.png"
)
METADATA = OUTPUT.with_suffix(".json")
WIDTH = 1536
HEIGHT = 1024
SCALE = 3

PALETTE = {
    "sea": "#426f79",
    "land": "#d6bd82",
    "coast": "#263e45",
    "river": "#5a8c92",
    "river_edge": "#31555d",
    "forest": "#67805d",
    "highland": "#a48b73",
    "field_a": "#b79c64",
    "field_b": "#c5aa6f",
    "urban": "#8e6654",
    "urban_line": "#513f38",
    "road": "#765e48",
    "road_core": "#ead398",
}


def _scaled_points(points: Iterable[tuple[float, float]]) -> list[tuple[int, int]]:
    return [(round(x * SCALE), round(y * SCALE)) for x, y in points]


def _polygon(
    draw: ImageDraw.ImageDraw,
    points: Iterable[tuple[float, float]],
    *,
    fill: str,
    outline: str | None = None,
    width: int = 1,
) -> None:
    scaled = _scaled_points(points)
    draw.polygon(scaled, fill=fill)
    if outline:
        draw.line(scaled + [scaled[0]], fill=outline, width=width * SCALE, joint="curve")


def _line(
    draw: ImageDraw.ImageDraw,
    points: Iterable[tuple[float, float]],
    *,
    fill: str,
    width: int,
) -> None:
    draw.line(
        _scaled_points(points),
        fill=fill,
        width=width * SCALE,
        joint="curve",
    )


def _ellipse(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    *,
    fill: str | None = None,
    outline: str | None = None,
    width: int = 1,
) -> None:
    draw.ellipse(
        tuple(round(value * SCALE) for value in box),
        fill=fill,
        outline=outline,
        width=width * SCALE,
    )


def _city_block(
    center: tuple[float, float],
    inner: float,
    outer: float,
    start_deg: float,
    end_deg: float,
) -> list[tuple[float, float]]:
    cx, cy = center
    inset = 1.8
    a0 = math.radians(start_deg + inset)
    a1 = math.radians(end_deg - inset)
    return [
        (cx + inner * math.cos(a0), cy + inner * math.sin(a0)),
        (cx + outer * math.cos(a0), cy + outer * math.sin(a0)),
        (cx + outer * math.cos(a1), cy + outer * math.sin(a1)),
        (cx + inner * math.cos(a1), cy + inner * math.sin(a1)),
    ]


def _draw_city(draw: ImageDraw.ImageDraw) -> None:
    center = (842.0, 510.0)
    _ellipse(
        draw,
        (704, 372, 980, 648),
        fill="#cfb47b",
        outline=PALETTE["urban_line"],
        width=5,
    )
    rings = ((31, 61, 12, 4), (69, 99, 18, 1), (107, 130, 24, 3))
    for inner, outer, count, offset in rings:
        step = 360 / count
        for index in range(count):
            start = offset + index * step
            _polygon(
                draw,
                _city_block(center, inner, outer, start, start + step),
                fill=PALETTE["urban"],
                outline=PALETTE["urban_line"],
                width=1,
            )
    for radius in (65, 103):
        _ellipse(
            draw,
            (842 - radius, 510 - radius, 842 + radius, 510 + radius),
            outline=PALETTE["road_core"],
            width=5,
        )
        _ellipse(
            draw,
            (842 - radius, 510 - radius, 842 + radius, 510 + radius),
            outline=PALETTE["road"],
            width=1,
        )
    for angle in (0, 45, 90, 135, 180, 225, 270, 315):
        radians = math.radians(angle)
        end = (842 + 135 * math.cos(radians), 510 + 135 * math.sin(radians))
        _line(draw, [center, end], fill=PALETTE["road_core"], width=6)
        _line(draw, [center, end], fill=PALETTE["road"], width=2)
    _ellipse(
        draw,
        (817, 485, 867, 535),
        fill="#ddc488",
        outline=PALETTE["urban_line"],
        width=3,
    )


def _draw_port(draw: ImageDraw.ImageDraw) -> None:
    harbor = [(434, 816), (470, 790), (526, 792), (572, 824), (568, 875), (520, 901), (464, 887)]
    _polygon(
        draw,
        harbor,
        fill="#caae75",
        outline=PALETTE["urban_line"],
        width=3,
    )
    blocks = [
        [(450, 816), (473, 805), (489, 817), (465, 832)],
        [(482, 801), (507, 803), (510, 824), (487, 822)],
        [(520, 808), (546, 822), (536, 841), (514, 828)],
        [(455, 840), (481, 830), (490, 851), (466, 862)],
        [(498, 837), (521, 835), (527, 858), (501, 861)],
        [(535, 849), (558, 858), (548, 879), (526, 870)],
        [(473, 869), (498, 858), (508, 882), (483, 890)],
    ]
    for block in blocks:
        _polygon(
            draw,
            block,
            fill=PALETTE["urban"],
            outline=PALETTE["urban_line"],
            width=1,
        )
    for pier in (
        [(452, 858), (411, 883), (385, 883)],
        [(473, 879), (439, 914), (414, 914)],
        [(518, 891), (504, 930), (484, 945)],
    ):
        _line(draw, pier, fill=PALETTE["urban_line"], width=7)
        _line(draw, pier, fill="#d6bd82", width=3)


def render() -> tuple[str, int]:
    canvas = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), PALETTE["sea"])
    draw = ImageDraw.Draw(canvas)

    coastline = [
        (432, 0), (425, 50), (408, 92), (373, 126), (331, 162),
        (309, 199), (337, 228), (390, 252), (407, 290), (379, 329),
        (366, 365), (391, 401), (424, 431), (427, 468), (398, 502),
        (355, 531), (350, 568), (370, 608), (403, 644), (447, 676),
        (462, 716), (431, 752), (445, 790), (476, 824), (524, 850),
        (551, 889), (614, 918), (684, 943), (754, 1024),
    ]
    land = coastline + [(1536, 1024), (1536, 0)]
    _polygon(draw, land, fill=PALETTE["land"])
    _line(draw, coastline, fill=PALETTE["coast"], width=5)

    islands = [
        [(290, 270), (327, 245), (368, 258), (380, 298), (348, 324), (304, 315)],
        [(250, 354), (302, 332), (342, 356), (331, 401), (276, 410), (238, 385)],
        [(248, 457), (296, 425), (335, 451), (326, 493), (278, 508), (235, 487)],
        [(272, 566), (320, 535), (353, 564), (345, 614), (293, 628), (254, 604)],
        [(310, 661), (350, 640), (386, 666), (383, 704), (341, 722), (305, 698)],
    ]
    for island in islands:
        _polygon(draw, island, fill=PALETTE["land"], outline=PALETTE["coast"], width=4)

    forest = [
        (438, 0), (956, 0), (940, 78), (975, 128), (948, 194),
        (912, 233), (929, 301), (875, 353), (801, 345), (746, 372),
        (675, 351), (618, 369), (548, 337), (483, 346), (422, 300),
        (405, 240), (382, 186), (409, 115),
    ]
    _polygon(draw, forest, fill=PALETTE["forest"], outline="#435440", width=4)

    highland = [
        (1012, 0), (1536, 0), (1536, 489), (1468, 477), (1396, 505),
        (1328, 470), (1254, 492), (1188, 452), (1109, 465), (1042, 425),
        (1002, 369), (1019, 302), (984, 242), (1007, 169), (981, 93),
    ]
    _polygon(draw, highland, fill=PALETTE["highland"], outline="#715f51", width=4)

    river = [(797, 0), (805, 62), (789, 125), (751, 191), (731, 254), (758, 313), (710, 356), (644, 385), (605, 445), (559, 493), (525, 544)]
    _line(draw, river, fill=PALETTE["river_edge"], width=37)
    _line(draw, river, fill=PALETTE["river"], width=27)
    branches = [
        [(530, 540), (483, 505), (431, 470), (378, 431), (330, 392), (280, 369)],
        [(530, 546), (478, 559), (420, 575), (363, 589), (308, 601)],
        [(535, 552), (511, 607), (478, 656), (440, 704), (397, 743)],
        [(527, 542), (462, 528), (405, 532), (347, 550), (292, 568)],
    ]
    for branch in branches:
        _line(draw, branch, fill=PALETTE["river_edge"], width=24)
        _line(draw, branch, fill=PALETTE["river"], width=16)

    # Sparse field parcels carry only land-use extents, never furrows or texture.
    field_polygons = [
        [(1032, 620), (1170, 591), (1224, 674), (1084, 711)],
        [(1183, 589), (1332, 561), (1378, 645), (1237, 672)],
        [(1351, 562), (1499, 549), (1536, 620), (1392, 644)],
        [(1085, 725), (1229, 685), (1280, 770), (1136, 811)],
        [(1246, 684), (1392, 657), (1439, 744), (1291, 771)],
        [(1410, 657), (1536, 640), (1536, 727), (1455, 743)],
        [(1143, 825), (1288, 783), (1341, 866), (1195, 907)],
        [(1305, 785), (1453, 757), (1496, 846), (1357, 865)],
    ]
    for index, field in enumerate(field_polygons):
        _polygon(
            draw,
            field,
            fill=PALETTE["field_a" if index % 2 == 0 else "field_b"],
            outline="#806b49",
            width=2,
        )

    roads: Sequence[Sequence[tuple[float, float]]] = (
        [(704, 511), (638, 529), (583, 570), (548, 640), (519, 711), (503, 790)],
        [(842, 372), (843, 302), (885, 226), (930, 151), (970, 83)],
        [(980, 510), (1082, 513), (1197, 534), (1320, 522), (1450, 499), (1536, 482)],
        [(932, 607), (1010, 657), (1093, 709), (1192, 757), (1300, 818), (1416, 893), (1536, 956)],
        [(842, 648), (856, 712), (846, 774), (795, 823), (712, 849), (623, 846), (562, 834)],
    )
    for road in roads:
        _line(draw, road, fill=PALETTE["road"], width=12)
        _line(draw, road, fill=PALETTE["road_core"], width=7)

    _draw_city(draw)
    _draw_port(draw)

    final = canvas.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_name(OUTPUT.name + ".new")
    final.save(temporary, format="PNG", optimize=False)
    temporary.replace(OUTPUT)
    canvas.close()
    final.close()

    payload = OUTPUT.read_bytes()
    sha256 = hashlib.sha256(payload).hexdigest()
    metadata = {
        "schema_version": "1.0.0",
        "id": "style-candidate-i-v1-composition-guide",
        "purpose": "geometry-only input for one ImageGen style-board generation",
        "output": {
            "path": OUTPUT.relative_to(REPO_ROOT).as_posix(),
            "sha256": sha256,
            "bytes": len(payload),
            "format": "PNG",
            "mode": "RGB",
            "width": WIDTH,
            "height": HEIGHT,
        },
        "renderer": {
            "path": Path(__file__).resolve().relative_to(REPO_ROOT).as_posix(),
            "supersample": SCALE,
            "resampling": "Pillow LANCZOS",
            "randomness": "none",
        },
        "encoded_composition": [
            "open sea on the left",
            "low irregular west and south-west coast with braided delta islands",
            "forest across the north and north-centre",
            "north-to-centre river splitting through the western delta",
            "dense circular plan city centred near x=842,y=510",
            "small flat coastal port near x=500,y=850",
            "roads connecting city, port, north, east, and lower-right fields",
            "irregular flat highland region in the upper-right",
            "large sparse field parcels in the lower-right",
            "unmarked quiet corridors between major regions",
        ],
        "explicit_non_authority": [
            "style",
            "palette of the generated candidate",
            "surface material",
            "microdetail",
            "lettering",
            "pictorial symbols",
        ],
        "forbidden_in_guide": [
            "source-image texture",
            "perspective pixels",
            "dots or CAD-like wallpaper",
            "labels or pseudo-writing",
            "illustrative terrain glyphs",
        ],
        "palette": PALETTE,
    }
    METADATA.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return sha256, len(payload)


if __name__ == "__main__":
    digest, byte_count = render()
    print(f"wrote {OUTPUT.relative_to(REPO_ROOT)} sha256={digest} bytes={byte_count}")
