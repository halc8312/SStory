#!/usr/bin/env python3
"""Sync canonical map data (world/map-data/data) to the GitHub Pages copy (docs/data/map).

Usage:
    python world/map-data/scripts/sync_map_data.py           # copy out-of-date files
    python world/map-data/scripts/sync_map_data.py --check   # verify only (exit 1 on drift)
"""

from __future__ import annotations

import argparse
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_DIR = REPO_ROOT / "world" / "map-data" / "data"
DEST_DIR = REPO_ROOT / "docs" / "data" / "map"

SYNCED_FILES = (
    "continents.json",
    "regions.json",
    "nodes.json",
    "routes.json",
    "hazards.json",
    "pois.json",
    "pixel-mapping.json",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="only verify that docs copies match the canonical data; do not write",
    )
    args = parser.parse_args()

    missing_sources = [name for name in SYNCED_FILES if not (SOURCE_DIR / name).exists()]
    if missing_sources:
        print(f"Canonical data files missing in {SOURCE_DIR}: {', '.join(missing_sources)}")
        return 1

    stale = []
    for name in SYNCED_FILES:
        dest_path = DEST_DIR / name
        if not dest_path.exists() or dest_path.read_bytes() != (SOURCE_DIR / name).read_bytes():
            stale.append(name)

    if args.check:
        if stale:
            print("Map data out of sync between world/map-data/data and docs/data/map:")
            for name in stale:
                print(f"  - {name}")
            print("Run: python world/map-data/scripts/sync_map_data.py")
            return 1
        print(f"Map data in sync ({len(SYNCED_FILES)} files).")
        return 0

    if not stale:
        print(f"docs/data/map is already up to date ({len(SYNCED_FILES)} files).")
        return 0

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    for name in stale:
        (DEST_DIR / name).write_bytes((SOURCE_DIR / name).read_bytes())
        print(f"Synced world/map-data/data/{name} -> docs/data/map/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
