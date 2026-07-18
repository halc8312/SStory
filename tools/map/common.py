#!/usr/bin/env python3
"""Shared paths and JSON loading for the map tools.

Paths are anchored to the repository root so the tools work from any
working directory.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "world" / "map-data" / "data"
EXPORT_DIR = REPO_ROOT / "world" / "map-data" / "exports"


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)
