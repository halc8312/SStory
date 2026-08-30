#!/usr/bin/env python3
"""Build deterministic visual-review contacts for approved Candidate K2."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

import build_style_candidate_k2_hybrid as k2


ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "world/map-production/candidates/style-candidate-k-v2-hybrid.png"
GUIDE = ROOT / "world/map-production/controls/style-candidate-i-v1-composition-guide.png"
OUT = ROOT / "tmp/map-production/k2-hybrid-review-v1"
EXPECTED_CANDIDATE = "25b8d6211d1f2970cd59af363c521429863c340780d182253d161a951ed9eb92"
EXPECTED_GUIDE = "52f85e45b61bf889de709d8ea9601bd5865d6021bfbc617473a9e957a6ab8bbc"
PNG = {"format": "PNG", "compress_level": 9, "optimize": False}

REGIONS = {
    "sea": (0, 100, 370, 620),
    "delta": (225, 300, 605, 765),
    "forest": (375, 0, 980, 390),
    "port": (380, 740, 620, 980),
    "capital": (680, 335, 1005, 680),
    "fields": (995, 530, 1536, 935),
    "highland": (965, 0, 1536, 530),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_save(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    image.save(temporary, **PNG)
    temporary.replace(path)


def font(size: int) -> ImageFont.ImageFont:
    for path in ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/segoeui.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def crop_zoom(image: Image.Image, box: tuple[int, int, int, int], scale: int) -> Image.Image:
    crop = image.crop(box)
    return crop.resize((crop.width * scale, crop.height * scale), Image.Resampling.LANCZOS)


def labeled_panel(image: Image.Image, label: str, size: tuple[int, int]) -> Image.Image:
    width, height = size
    panel = Image.new("RGB", size, (30, 29, 25))
    available = (width - 16, height - 44)
    fitted = ImageOps.contain(image.convert("RGB"), available, Image.Resampling.LANCZOS)
    panel.paste(fitted, ((width - fitted.width) // 2, 36 + (available[1] - fitted.height) // 2))
    draw = ImageDraw.Draw(panel)
    draw.text((10, 8), label, fill=(232, 218, 181), font=font(18))
    return panel


def geometry_overlay(candidate: Image.Image) -> Image.Image:
    overlay = candidate.copy()
    draw = ImageDraw.Draw(overlay, "RGBA")
    draw.line(k2.COASTLINE, fill=(0, 238, 255, 225), width=3, joint="curve")
    for island in k2.ISLANDS:
        draw.line(island + [island[0]], fill=(0, 238, 255, 225), width=3, joint="curve")
    draw.line(k2.RIVER, fill=(50, 145, 255, 235), width=3, joint="curve")
    for branch in k2.BRANCHES:
        draw.line(branch, fill=(50, 145, 255, 235), width=3, joint="curve")
    for road in k2.ROADS:
        draw.line(road, fill=(255, 174, 38, 230), width=3, joint="curve")
    for parcel in k2.FIELDS:
        draw.line(parcel + [parcel[0]], fill=(103, 255, 93, 225), width=3, joint="curve")
    draw.line(k2.HIGHLAND + [k2.HIGHLAND[0]], fill=(213, 103, 255, 215), width=3, joint="curve")
    draw.ellipse((704, 372, 980, 648), outline=(255, 73, 99, 240), width=3)
    draw.line(k2.PORT + [k2.PORT[0]], fill=(255, 73, 99, 240), width=3, joint="curve")

    legend = [("coast/islands", (0, 238, 255)), ("river", (50, 145, 255)),
              ("roads", (255, 174, 38)), ("fields", (103, 255, 93)),
              ("highland", (213, 103, 255)), ("capital/port", (255, 73, 99))]
    draw.rounded_rectangle((1040, 18, 1518, 132), radius=8, fill=(24, 23, 20, 210), outline=(235, 220, 185, 220), width=1)
    for index, (label, color) in enumerate(legend):
        x = 1055 + (index % 3) * 155
        y = 35 + (index // 3) * 42
        draw.line((x, y + 9, x + 24, y + 9), fill=(*color, 255), width=4)
        draw.text((x + 31, y), label, fill=(242, 231, 202, 255), font=font(15))
    return overlay


def build() -> dict[str, object]:
    if sha256(CANDIDATE) != EXPECTED_CANDIDATE:
        raise RuntimeError("approved K2 candidate hash changed")
    if sha256(GUIDE) != EXPECTED_GUIDE:
        raise RuntimeError("canonical guide hash changed")
    OUT.mkdir(parents=True, exist_ok=True)

    candidate = Image.open(CANDIDATE).convert("RGB")
    artifacts: dict[str, Path] = {}

    native = OUT / "style-candidate-k-v2-hybrid-native.png"
    shutil.copyfile(CANDIDATE, native)
    artifacts["native"] = native

    for label, scale in (("25", 0.25), ("50", 0.50)):
        path = OUT / f"style-candidate-k-v2-hybrid-{label}.png"
        resized = candidate.resize((round(candidate.width * scale), round(candidate.height * scale)), Image.Resampling.LANCZOS)
        atomic_save(resized, path)
        artifacts[label] = path

    overlay_path = OUT / "style-candidate-k-v2-hybrid-geometry-overlay.png"
    atomic_save(geometry_overlay(candidate), overlay_path)
    artifacts["geometry_overlay"] = overlay_path

    zooms: dict[str, Image.Image] = {}
    for name in ("sea", "delta", "forest", "port"):
        image = crop_zoom(candidate, REGIONS[name], 2)
        path = OUT / f"style-candidate-k-v2-hybrid-{name}-200.png"
        atomic_save(image, path)
        artifacts[f"{name}_200"] = path
        zooms[f"{name} 200%"] = image
    for name in ("capital", "fields", "highland"):
        image = crop_zoom(candidate, REGIONS[name], 4)
        path = OUT / f"style-candidate-k-v2-hybrid-{name}-400.png"
        atomic_save(image, path)
        artifacts[f"{name}_400"] = path
        zooms[f"{name} 400%"] = image

    contact_200 = Image.new("RGB", (1536, 1024), (30, 29, 25))
    panels_200 = [
        labeled_panel(zooms["sea 200%"], "SEA 200%", (768, 512)),
        labeled_panel(zooms["delta 200%"], "COAST / DELTA 200%", (768, 512)),
        labeled_panel(zooms["forest 200%"], "FOREST 200%", (768, 512)),
        labeled_panel(zooms["port 200%"], "PORT 200%", (768, 512)),
    ]
    for index, panel in enumerate(panels_200):
        contact_200.paste(panel, ((index % 2) * 768, (index // 2) * 512))
    contact_200_path = OUT / "style-candidate-k-v2-hybrid-focus-200-contact.png"
    atomic_save(contact_200, contact_200_path)
    artifacts["focus_200_contact"] = contact_200_path

    contact_400 = Image.new("RGB", (1536, 512), (30, 29, 25))
    for index, label in enumerate(("capital 400%", "fields 400%", "highland 400%")):
        contact_400.paste(labeled_panel(zooms[label], label.upper(), (512, 512)), (index * 512, 0))
    contact_400_path = OUT / "style-candidate-k-v2-hybrid-focus-400-contact.png"
    atomic_save(contact_400, contact_400_path)
    artifacts["focus_400_contact"] = contact_400_path

    nine_sources = [
        (candidate.resize((384, 256), Image.Resampling.LANCZOS), "FULL 25%"),
        (candidate.resize((768, 512), Image.Resampling.LANCZOS), "FULL 50%"),
        (candidate, "FULL NATIVE"),
        (zooms["sea 200%"], "SEA 200%"),
        (zooms["delta 200%"], "DELTA 200%"),
        (zooms["forest 200%"], "FOREST 200%"),
        (zooms["capital 400%"], "CAPITAL 400%"),
        (zooms["fields 400%"], "FIELDS 400%"),
        (zooms["highland 400%"], "HIGHLAND 400%"),
    ]
    nine = Image.new("RGB", (1536, 1024), (30, 29, 25))
    for index, (image, label) in enumerate(nine_sources):
        x = (index % 3) * 512
        y = (index // 3) * 341
        nine.paste(labeled_panel(image, label, (512, 341)), (x, y))
    nine_path = OUT / "style-candidate-k-v2-hybrid-nine-contact.png"
    atomic_save(nine, nine_path)
    artifacts["nine_contact"] = nine_path

    manifest = {
        "schema_version": "1.0.0",
        "candidate": {"path": CANDIDATE.relative_to(ROOT).as_posix(), "sha256": sha256(CANDIDATE)},
        "guide": {"path": GUIDE.relative_to(ROOT).as_posix(), "sha256": sha256(GUIDE)},
        "interpolation": "Pillow LANCZOS for review scaling; candidate remains untouched",
        "regions_xyxy": {name: list(box) for name, box in REGIONS.items()},
        "artifacts": {
            name: {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path), "bytes": path.stat().st_size}
            for name, path in artifacts.items()
        },
    }
    manifest_path = OUT / "style-candidate-k-v2-hybrid-contacts.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    candidate.close()
    return manifest


if __name__ == "__main__":
    result = build()
    print(json.dumps({"output": OUT.relative_to(ROOT).as_posix(), "artifacts": len(result["artifacts"])}, indent=2))
