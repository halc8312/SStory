#!/usr/bin/env python3
"""Generate a 512 px WebP XYZ pyramid and deterministic metadata from a master image."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from production_common import ID_PATTERN, REPO_ROOT, dump_json, utc_now


GENERATOR_ID = "sstory-map-production/generate_tiles.py@1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def portable_source_path(path: Path) -> str:
    """Return a reproducible path without leaking a workstation absolute path."""

    resolved = path.resolve()
    try:
        relative = resolved.relative_to(REPO_ROOT.resolve())
    except ValueError:
        # The hash and dimensions identify an external source. Keep only its
        # basename so public metadata remains portable across machines.
        return resolved.name
    # Test and build scratch roots are deliberately ignored by Git. Treat them
    # like external sources even when TEMP lives inside the checkout so a
    # machine-specific temporary directory never enters persistent metadata.
    top_level = relative.parts[0].lower() if relative.parts else ""
    if top_level.startswith("tmp") or top_level == "output":
        return resolved.name
    return relative.as_posix()


def default_max_zoom(width: int, height: int, tile_size: int) -> int:
    ratio = max(width, height) / tile_size
    return max(0, math.ceil(math.log2(ratio))) if ratio > 1 else 0


def validate_output_target(output: Path) -> Path:
    resolved = output.resolve()
    filesystem_root = Path(resolved.anchor).resolve()
    forbidden = {filesystem_root, REPO_ROOT.resolve(), Path.home().resolve()}
    if resolved in forbidden or len(resolved.parts) < 2:
        raise ValueError(f"Refusing broad output directory: {resolved}")
    return resolved


def existing_output_is_owned(output: Path) -> bool:
    metadata_path = output / "metadata.json"
    if not metadata_path.is_file():
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return metadata.get("generated_by") == GENERATOR_ID


def generate_pyramid(
    source_path: Path,
    output_path: Path,
    *,
    map_id: str,
    min_zoom: int,
    max_zoom: int | None,
    tile_size: int = 512,
    quality: int = 88,
    lossless: bool = False,
    background: str = "#00000000",
    bounds: tuple[float, float, float, float] | None = None,
    coordinate_system: str | None = None,
    url_template: str = "{z}/{x}/{y}.webp",
    overwrite: bool = False,
) -> dict[str, Any]:
    try:
        from PIL import Image, ImageColor, ImageOps
    except ImportError as exc:
        raise RuntimeError("Pillow is required: py -m pip install Pillow") from exc

    if not source_path.is_file():
        raise ValueError(f"Master image does not exist: {source_path}")
    source_path = source_path.resolve()
    output_path = validate_output_target(output_path)
    try:
        source_path.relative_to(output_path)
    except ValueError:
        pass
    else:
        raise ValueError(
            "Master image must not be inside the tile output directory; "
            "overwriting that directory could destroy the source"
        )
    if not ID_PATTERN.fullmatch(map_id):
        raise ValueError("map_id must use lowercase kebab/snake case")
    if output_path.exists() and not output_path.is_dir():
        raise ValueError(f"Output path exists and is not a directory: {output_path}")
    if output_path.exists() and any(output_path.iterdir()):
        if not overwrite:
            raise ValueError(f"Output directory is not empty: {output_path}; use --overwrite")
        if not existing_output_is_owned(output_path):
            raise ValueError(
                f"Refusing to overwrite unrecognized directory (missing owned metadata.json): {output_path}"
            )
    if tile_size < 128 or tile_size > 1024 or tile_size & (tile_size - 1):
        raise ValueError("tile_size must be a power of two between 128 and 1024")
    if not 1 <= quality <= 100:
        raise ValueError("quality must be between 1 and 100")
    if bounds is not None:
        west, south, east, north = bounds
        if not all(math.isfinite(value) for value in bounds):
            raise ValueError("bounds must contain only finite numbers")
        if west >= east or south >= north:
            raise ValueError("bounds must satisfy west < east and south < north")
    effective_coordinate_system = coordinate_system or (
        "EA-WORLD-1" if bounds is not None else "pixel"
    )
    allowed_coordinate_systems = {
        "EA-WORLD-1",
        "eternia-geographic",
        "eternia-world",
        "pixel",
    }
    if effective_coordinate_system not in allowed_coordinate_systems:
        raise ValueError(
            "coordinate_system must be one of "
            + ", ".join(sorted(allowed_coordinate_systems))
        )

    with Image.open(source_path) as opened:
        master = ImageOps.exif_transpose(opened).convert("RGBA")
        width, height = master.size
        native_zoom = default_max_zoom(width, height, tile_size) if max_zoom is None else max_zoom
        if min_zoom < 0 or native_zoom < min_zoom or native_zoom > 24:
            raise ValueError("zoom range must satisfy 0 <= min_zoom <= max_zoom <= 24")
        try:
            fill = ImageColor.getcolor(background, "RGBA")
        except ValueError as exc:
            raise ValueError(f"Invalid --background color: {background!r}") from exc

        output_path.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=f".{output_path.name}.building-", dir=output_path.parent)
        )
        levels: list[dict[str, Any]] = []
        tile_digests: list[tuple[str, str]] = []
        try:
            for zoom in range(min_zoom, native_zoom + 1):
                factor = 2 ** (native_zoom - zoom)
                level_width = max(1, math.ceil(width / factor))
                level_height = max(1, math.ceil(height / factor))
                level_image = (
                    master
                    if (level_width, level_height) == master.size
                    else master.resize((level_width, level_height), Image.Resampling.LANCZOS)
                )
                columns = math.ceil(level_width / tile_size)
                rows = math.ceil(level_height / tile_size)
                for x in range(columns):
                    x_dir = staging / str(zoom) / str(x)
                    x_dir.mkdir(parents=True, exist_ok=True)
                    for y in range(rows):
                        left, top = x * tile_size, y * tile_size
                        right, bottom = min(left + tile_size, level_width), min(
                            top + tile_size, level_height
                        )
                        tile = Image.new("RGBA", (tile_size, tile_size), fill)
                        tile.paste(level_image.crop((left, top, right, bottom)), (0, 0))
                        tile_path = x_dir / f"{y}.webp"
                        save_options: dict[str, Any] = {
                            "format": "WEBP",
                            "lossless": lossless,
                            "method": 6,
                            "exact": True,
                        }
                        if not lossless:
                            save_options["quality"] = quality
                        tile.save(tile_path, **save_options)
                        relative = tile_path.relative_to(staging).as_posix()
                        tile_digests.append((relative, sha256_file(tile_path)))
                levels.append(
                    {
                        "zoom": zoom,
                        "width": level_width,
                        "height": level_height,
                        "columns": columns,
                        "rows": rows,
                        "tile_count": columns * rows,
                    }
                )

            set_digest = hashlib.sha256()
            for relative, digest in sorted(tile_digests):
                set_digest.update(relative.encode("utf-8"))
                set_digest.update(b"\0")
                set_digest.update(digest.encode("ascii"))
                set_digest.update(b"\n")

            metadata: dict[str, Any] = {
                "schema_version": "1.0.0",
                "type": "sstory-xyz-raster",
                "generated_by": GENERATOR_ID,
                "generated_at": utc_now(),
                "map_id": map_id,
                "scheme": "xyz",
                "format": "webp",
                "tile_size": tile_size,
                "minzoom": min_zoom,
                "maxzoom": native_zoom,
                "native_zoom": native_zoom,
                "tiles": [url_template],
                "coordinate_reference_system": effective_coordinate_system,
                # Retain the original key for existing consumers while the
                # canonical source uses ``coordinate_reference_system``.
                "coordinate_system": effective_coordinate_system,
                "bounds": list(bounds) if bounds else [0, 0, width, height],
                "master": {
                    "path": portable_source_path(source_path),
                    "sha256": sha256_file(source_path),
                    "width": width,
                    "height": height,
                    "mode": "RGBA",
                },
                "encoding": {
                    "quality": None if lossless else quality,
                    "lossless": lossless,
                    "background": background,
                },
                "levels": levels,
                "tile_count": len(tile_digests),
                "tile_set_sha256": set_digest.hexdigest(),
            }
            dump_json(staging / "metadata.json", metadata)

            backup_root: Path | None = None
            backup_path: Path | None = None
            if output_path.exists():
                # A sibling rename is recoverable and works on Windows, where a
                # non-empty directory cannot be atomically replaced in place.
                # Do not recursively delete the old public tile set until the new
                # one has been installed successfully.
                backup_root = Path(
                    tempfile.mkdtemp(
                        prefix=f".{output_path.name}.previous-",
                        dir=output_path.parent,
                    )
                )
                backup_path = backup_root / "previous"
                os.replace(output_path, backup_path)
            try:
                os.replace(staging, output_path)
            except Exception as install_error:
                if backup_path is not None and backup_path.exists():
                    try:
                        os.replace(backup_path, output_path)
                    except OSError as rollback_error:
                        raise RuntimeError(
                            "Could not install the new tile set or restore the previous "
                            f"one; recovery copy remains at {backup_path}: {rollback_error}"
                        ) from install_error
                raise
            if backup_root is not None:
                shutil.rmtree(backup_root)
            return metadata
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--map-id", required=True)
    parser.add_argument("--min-zoom", type=int, default=0)
    parser.add_argument("--max-zoom", type=int)
    parser.add_argument("--tile-size", type=int, default=512)
    parser.add_argument("--quality", type=int, default=88)
    parser.add_argument("--lossless", action="store_true")
    parser.add_argument("--background", default="#00000000")
    parser.add_argument(
        "--bounds",
        nargs=4,
        type=float,
        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
    )
    parser.add_argument(
        "--coordinate-system",
        choices=("EA-WORLD-1", "eternia-geographic", "eternia-world", "pixel"),
        help="tile bounds coordinate system (defaults to EA-WORLD-1 with --bounds, otherwise pixel)",
    )
    parser.add_argument("--url-template", default="{z}/{x}/{y}.webp")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        metadata = generate_pyramid(
            args.master,
            args.output,
            map_id=args.map_id,
            min_zoom=args.min_zoom,
            max_zoom=args.max_zoom,
            tile_size=args.tile_size,
            quality=args.quality,
            lossless=args.lossless,
            background=args.background,
            bounds=tuple(args.bounds) if args.bounds else None,
            coordinate_system=args.coordinate_system,
            url_template=args.url_template,
            overwrite=args.overwrite,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Tile generation failed: {exc}", file=sys.stderr)
        return 1
    if args.as_json:
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
    else:
        print(f"XYZ WebP pyramid generated: {args.output}")
        print(
            f"  {metadata['master']['width']}x{metadata['master']['height']} master; "
            f"z{metadata['minzoom']}..z{metadata['maxzoom']}; "
            f"{metadata['tile_count']} tiles at {metadata['tile_size']}px"
        )
        print(f"  Tile-set SHA-256: {metadata['tile_set_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
