#!/usr/bin/env python3
"""Sync canonical POI data to the GitHub Pages copy."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORLD_POIS_PATH = REPO_ROOT / "world" / "map-data" / "data" / "pois.json"
DOCS_POIS_PATH = REPO_ROOT / "docs" / "data" / "map" / "pois.json"


def main() -> int:
    source_bytes = WORLD_POIS_PATH.read_bytes()
    DOCS_POIS_PATH.parent.mkdir(parents=True, exist_ok=True)

    if DOCS_POIS_PATH.exists() and DOCS_POIS_PATH.read_bytes() == source_bytes:
        print("docs/data/map/pois.json is already up to date.")
        return 0

    DOCS_POIS_PATH.write_bytes(source_bytes)
    print("Synced world/map-data/data/pois.json -> docs/data/map/pois.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
