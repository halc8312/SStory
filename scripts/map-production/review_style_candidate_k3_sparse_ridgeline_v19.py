#!/usr/bin/env python3
"""Transactionally emit the five TEMP-only v19 Root Vision review views."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

import build_style_candidate_k3_sparse_ridgeline_v19 as v19


VIEW_DEFINITIONS = {
    "native": (None, (1536, 1024)),
    "full25": (None, (384, 256)),
    "full50": (None, (768, 512)),
    "highland200": ((930, 0, 1536, 560), (1212, 1120)),
    "highland400": ((930, 0, 1536, 560), (2424, 2240)),
}
PNG_OPTIONS = {"format": "PNG", "compress_level": 9, "optimize": False}


class ReviewEmitError(RuntimeError):
    """Raised before a partial review bundle can become visible."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _repo_tmp_root() -> Path:
    return Path(__file__).resolve().parents[2] / "tmp"


def _require_temp_output(path: Path) -> Path:
    resolved = path.resolve()
    allowed_roots = {_repo_tmp_root().resolve(), Path(tempfile.gettempdir()).resolve()}
    if not any(resolved == root or resolved.is_relative_to(root) for root in allowed_roots):
        raise ReviewEmitError(
            f"review output must stay below repository tmp or OS TEMP: {resolved}"
        )
    if resolved.exists() or resolved.is_symlink():
        raise ReviewEmitError(f"refusing existing review output root: {resolved}")
    return resolved


def _view(candidate: np.ndarray, name: str) -> bytes:
    crop, size = VIEW_DEFINITIONS[name]
    with Image.fromarray(candidate, "RGB") as source:
        working = source.crop(crop) if crop is not None else source.copy()
        try:
            rendered = working.resize(size, Image.Resampling.LANCZOS)
            try:
                buffer = BytesIO()
                rendered.save(buffer, **PNG_OPTIONS)
                return buffer.getvalue()
            finally:
                rendered.close()
        finally:
            working.close()


def _write_new(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def emit_review_bundle(contract_path: Path, output_root: Path) -> dict[str, Any]:
    final = _require_temp_output(Path(output_root))
    parent = final.parent
    parent.mkdir(parents=True, exist_ok=True)
    stage = parent / f".{final.name}.staging-{uuid.uuid4().hex}"
    if stage.exists() or stage.is_symlink():
        raise ReviewEmitError(f"review staging path unexpectedly exists: {stage}")
    first = v19.reconstruct_from_contract(Path(contract_path))
    second = v19.reconstruct_from_contract(Path(contract_path))
    if not np.array_equal(first.candidate, second.candidate):
        raise ReviewEmitError("independent in-memory replays differ")
    artifacts: dict[str, dict[str, Any]] = {}
    try:
        stage.mkdir(parents=False, exist_ok=False)
        for name in VIEW_DEFINITIONS:
            payload = _view(first.candidate, name)
            target = stage / f"{name}.png"
            _write_new(target, payload)
            with Image.open(BytesIO(payload)) as opened:
                opened.load()
                artifacts[name] = {
                    "path": f"{name}.png",
                    "sha256": _sha256(payload),
                    "bytes": len(payload),
                    "mode": opened.mode,
                    "size": list(opened.size),
                }
        receipt = {
            "schema_version": "1.0.0",
            "id": "style-candidate-k-v3-sparse-ridgeline-v19-root-vision-bundle",
            "status": "pending-root-vision",
            "temporary_review_only": True,
            "decision_authority": False,
            "candidate_pixel_sha256": v19.array_sha256(first.candidate),
            "independent_replay_equal": True,
            "view_order": list(VIEW_DEFINITIONS),
            "png_count": len(artifacts),
            "artifacts": artifacts,
            "identity": first.identity,
            "selected_body_count": len(first.components),
            "root_vision_required": True,
        }
        receipt_bytes = (
            json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        ).encode("utf-8")
        _write_new(stage / "review.json", receipt_bytes)
        files = sorted(item.name for item in stage.iterdir() if item.is_file())
        expected = sorted([f"{name}.png" for name in VIEW_DEFINITIONS] + ["review.json"])
        if files != expected:
            raise ReviewEmitError(
                f"review inventory is not exactly five PNGs plus JSON: {files}"
            )
        if len(list(stage.glob("*.png"))) != 5:
            raise ReviewEmitError("review transaction did not contain exactly five PNGs")
        if final.exists() or final.is_symlink():
            raise ReviewEmitError("review output appeared during transaction")
        os.replace(stage, final)
        return receipt
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-contract", type=Path, required=True)
    parser.add_argument("--temporary-output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = emit_review_bundle(args.replay_contract, args.temporary_output_root)
    except (ReviewEmitError, v19.ReplayError) as exc:
        parser.exit(2, f"v19 review emit failed closed: {exc}\n")
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "output_root": str(args.temporary_output_root.resolve()),
                "png_count": receipt["png_count"],
                "receipt": "review.json",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
