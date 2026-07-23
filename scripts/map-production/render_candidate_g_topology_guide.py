#!/usr/bin/env python3
"""Render the flat six-shape Candidate G topology conditioning guide."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTROL = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-g-v1-topology-guide.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-g-v1-topology-guide.png"
)


class GuideError(ValueError):
    """Raised before publication when the topology guide is invalid."""


def _rgb(value: object, label: str) -> tuple[int, int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(not isinstance(item, int) or not 0 <= item <= 255 for item in value)
    ):
        raise GuideError(f"{label} must be three RGB bytes")
    return value[0], value[1], value[2]


def render(control_path: Path, output_path: Path) -> None:
    if output_path.exists():
        raise GuideError(f"refusing to overwrite existing output: {output_path}")
    control = json.loads(control_path.read_text(encoding="utf-8"))
    if set(control) != {
        "schema_version",
        "id",
        "coordinate_space",
        "canvas",
        "background_rgb",
        "shapes",
        "purpose",
    }:
        raise GuideError("control root keys differ from the strict contract")
    if control["schema_version"] != "1.0.0":
        raise GuideError("unsupported schema_version")
    if control["coordinate_space"] != "source-pixels-y-down":
        raise GuideError("unsupported coordinate_space")
    canvas = control["canvas"]
    if canvas != {"width": 1536, "height": 1024}:
        raise GuideError("Candidate G guide canvas must be exactly 1536x1024")
    shapes = control["shapes"]
    if not isinstance(shapes, list) or len(shapes) != 6:
        raise GuideError("Candidate G guide requires exactly six shapes")
    identifiers = [shape.get("id") for shape in shapes]
    if any(not isinstance(item, str) or not item for item in identifiers):
        raise GuideError("every shape requires a nonempty id")
    if len(identifiers) != len(set(identifiers)):
        raise GuideError("shape ids must be unique")
    expected_roles = {
        "north_east_range": {"main-massif", "foothill-a", "foothill-b"},
        "south_east_range": {"main-massif", "foothill-a", "foothill-b"},
    }
    actual_roles = {region_id: set() for region_id in expected_roles}
    image = Image.new(
        "RGB",
        (canvas["width"], canvas["height"]),
        _rgb(control["background_rgb"], "background_rgb"),
    )
    draw = ImageDraw.Draw(image)
    try:
        for shape in shapes:
            if set(shape) != {"id", "region_id", "role", "rgb", "points"}:
                raise GuideError(f"shape {shape.get('id')} keys differ from the contract")
            region_id = shape["region_id"]
            if region_id not in expected_roles:
                raise GuideError(f"unknown region_id: {region_id}")
            actual_roles[region_id].add(shape["role"])
            points = shape["points"]
            if not isinstance(points, list) or len(points) < 5:
                raise GuideError(f"shape {shape['id']} requires at least five points")
            normalized_points: list[tuple[int, int]] = []
            for point in points:
                if (
                    not isinstance(point, list)
                    or len(point) != 2
                    or any(not isinstance(item, int) for item in point)
                    or not 0 <= point[0] < canvas["width"]
                    or not 0 <= point[1] < canvas["height"]
                ):
                    raise GuideError(f"shape {shape['id']} has an invalid point")
                normalized_points.append((point[0], point[1]))
            draw.polygon(normalized_points, fill=_rgb(shape["rgb"], f"{shape['id']}.rgb"))
        if actual_roles != expected_roles:
            raise GuideError("each region requires one main massif and two foothills")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, format="PNG", optimize=True)
    finally:
        image.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", type=Path, default=DEFAULT_CONTROL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        render(args.control, args.output)
    except Exception as error:
        print(f"Candidate G topology guide failed: {error}")
        return 1
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
