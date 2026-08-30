#!/usr/bin/env python3
"""Emit one review-only Golden-v2 candidate into the TEMP namespace.

This command is deliberately narrower than the Golden-v2 promoter.  It binds
the fixed renderer inventory, runs two fresh read-closed replays, constructs
the five canonical review views, and independently recomputes every pixel
gate.  It does not create Root or blind Vision evidence and it cannot promote
or accept an image.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from PIL import Image

import generate_style_candidate_k3_golden_v2_controls as audit_controls
import promote_style_candidate_k3_golden_v2 as promotion
import render_style_candidate_k3_golden_v2 as fixed_renderer
from production_common import REPO_ROOT, load_json, parse_rfc3339, utc_now
from release_bound_artifact import BoundArtifactError, bind_file
from release_path_safety import ReleasePathError, assert_no_reparse_components


DEFAULT_CONFIG = (
    REPO_ROOT
    / "world/map-production/controls/style-candidate-k-v3-golden-v2/renderer-config.json"
)
RENDERER = REPO_ROOT / "scripts/map-production/render_style_candidate_k3_golden_v2.py"
TEMP_ROOT = (REPO_ROOT / "tmp/map-production").resolve()
EMISSION_ID = "style-candidate-k-v3-golden-v2-emission"
PNG_SAVE_OPTIONS = {"format": "PNG", "compress_level": 9, "optimize": False}
EXPECTED_RENDERER_IDENTITY = {
    "changed_pixels": 237_342,
    "outside_permission": 0,
    "protected_features": 0,
    "road_calm_18px": 0,
    "alpha_zero_changed": 0,
    "body_outside_full_alpha": 0,
    "contour_outside_body": 0,
    "contour_grayscale_mismatch": 0,
}
OWNED_OUTPUT_NAMES = frozenset(
    {
        "candidate.png",
        "replay.png",
        "emission.json",
        *(f"view-{name}.png" for name in promotion.VIEW_ORDER),
    }
)


class GoldenV2EmissionError(RuntimeError):
    """Raised before an incomplete or unbound TEMP emission can survive."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def _artifact(path: Path) -> dict[str, str]:
    try:
        return bind_file(path, label=str(path), trackable=True).artifact()
    except (BoundArtifactError, ReleasePathError) as exc:
        raise GoldenV2EmissionError(str(exc)) from exc


def _assert_frozen_audit_controls() -> None:
    expected = {
        audit_controls.AUDIT_CONTROL: audit_controls.EXPECTED_AUDIT_CONTROL_SHA256,
        **{
            audit_controls.MASK_PATHS[name]: digest
            for name, digest in audit_controls.EXPECTED_MASK_PNG_SHA256.items()
        },
    }
    for path, digest in expected.items():
        binding = _artifact(path)
        if binding["sha256"] != digest:
            raise GoldenV2EmissionError(
                f"frozen Golden-v2 audit control changed: {binding['path']}"
            )


def _source_record(
    path: Path, data: bytes, *, size: tuple[int, int]
) -> dict[str, Any]:
    return {
        "path": _relative(path),
        "sha256": _sha256(data),
        "bytes": len(data),
        "mode": "RGB",
        "size": list(size),
    }


def _require_exact_keys(value: Any, keys: set[str], *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        observed = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise GoldenV2EmissionError(
            f"{label} keys changed: expected={sorted(keys)}, observed={observed}"
        )
    return value


def _load_fixed_config(path: Path) -> dict[str, Any]:
    if path.resolve() != DEFAULT_CONFIG.resolve():
        raise GoldenV2EmissionError(
            f"config is fixed to {_relative(DEFAULT_CONFIG)}"
        )
    config = _require_exact_keys(
        load_json(path),
        {
            "schema_version",
            "interface",
            "seed",
            "expected_output",
            "replay_contract",
            "frozen_renderer",
            "donors",
            "controls",
        },
        label="renderer config",
    )
    try:
        config_payload = path.read_bytes()
    except OSError as exc:
        raise GoldenV2EmissionError(f"cannot bind fixed renderer config: {exc}") from exc
    if _sha256(config_payload) != fixed_renderer.CONFIG_SHA256:
        raise GoldenV2EmissionError("renderer config bytes changed")
    expected = _require_exact_keys(
        config["expected_output"],
        {"png_sha256", "pixel_sha256", "png_bytes", "width", "height", "mode"},
        label="renderer config expected_output",
    )
    exact = {
        "schema_version": fixed_renderer.SCHEMA_VERSION,
        "interface": fixed_renderer.INTERFACE,
        "seed": fixed_renderer.SEED,
        "expected_output": fixed_renderer.EXPECTED_OUTPUT,
        "replay_contract": {
            "path": fixed_renderer.REPLAY_CONTRACT_PATH,
            "sha256": fixed_renderer.REPLAY_CONTRACT_SHA256,
        },
        "frozen_renderer": {
            "path": fixed_renderer.FROZEN_RENDERER_PATH,
            "sha256": fixed_renderer.FROZEN_RENDERER_SHA256,
        },
        "donors": list(fixed_renderer.EXPECTED_DONORS),
        "controls": list(fixed_renderer.EXPECTED_CONTROLS),
    }
    if config != exact or expected != fixed_renderer.EXPECTED_OUTPUT:
        raise GoldenV2EmissionError("renderer config authority changed")
    for group in ("donors", "controls"):
        items = config[group]
        if (
            not isinstance(items, list)
            or not items
            or not all(isinstance(item, str) and item for item in items)
            or len(items) != len(set(items))
        ):
            raise GoldenV2EmissionError(
                f"renderer config {group} must be a non-empty unique path array"
            )
    return config


def _reproduction(config_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    donors = [_artifact(REPO_ROOT / item) for item in config["donors"]]
    controls = [_artifact(REPO_ROOT / item) for item in config["controls"]]
    audit_root = "world/map-production/controls/style-candidate-k-v3-golden-v2"
    mask_paths = {
        "measurement_inside": f"{audit_root}/masks/measurement-inside.png",
        "texture_reference": f"{audit_root}/masks/texture-reference.png",
        "permission": f"{audit_root}/masks/permission.png",
        "protected_features": f"{audit_root}/masks/protected-features.png",
        "road_calm_18px": f"{audit_root}/masks/road-calm-18px.png",
        "selected_components": f"{audit_root}/masks/selected-components.png",
    }
    reproduction: dict[str, Any] = {
        "renderer": _artifact(RENDERER),
        "config": _artifact(config_path),
        "seed": config["seed"],
        "donors": donors,
        "controls": controls,
        "argv": [],
        "environment": dict(promotion.FIXED_RENDERER_ENVIRONMENT),
        "timeout_seconds": promotion.RENDERER_TIMEOUT_SECONDS,
        "read_closure_runner": _artifact(promotion.READ_CLOSURE_RUNNER_PATH),
        "pixel_auditor": _artifact(Path(promotion.pixel_auditor.__file__).resolve()),
        "pixel_audit": {
            "baseline": _artifact(
                REPO_ROOT
                / "world/map-production/style-assets/k3-v18-reconstruction-base.png"
            ),
            "control": _artifact(REPO_ROOT / f"{audit_root}/audit-control.json"),
            "masks": {
                name: _artifact(REPO_ROOT / mask_paths[name])
                for name in promotion.pixel_auditor.MASK_NAMES
            },
        },
    }
    validated_groups = {
        "donors": [
            bind_file(
                REPO_ROOT / item,
                label=f"renderer donor {index}",
                trackable=True,
            )
            for index, item in enumerate(config["donors"])
        ],
        "controls": [
            bind_file(
                REPO_ROOT / item,
                label=f"renderer control {index}",
                trackable=True,
            )
            for index, item in enumerate(config["controls"])
        ],
    }
    renderer_binding = bind_file(
        RENDERER, label="fixed Golden-v2 renderer", trackable=True
    )
    config_binding = bind_file(
        config_path, label="fixed Golden-v2 renderer config", trackable=True
    )
    reproduction["argv"] = promotion._canonical_reproduction_argv(
        renderer=renderer_binding,
        config=config_binding,
        seed=config["seed"],
        donors=validated_groups["donors"],
        controls=validated_groups["controls"],
    )
    return reproduction


def _fixed_environment() -> dict[str, str]:
    environment = dict(promotion.FIXED_RENDERER_ENVIRONMENT)
    for key in promotion.PLATFORM_RUNTIME_ENVIRONMENT_KEYS:
        value = os.environ.get(key)
        if value:
            environment[key] = value
    return environment


def _run_read_closed(
    reproduction: dict[str, Any], validated: dict[str, Any], output: Path
) -> None:
    renderer_argv = list(reproduction["argv"][2:])
    renderer_argv[-1] = str(output)
    argv = [
        sys.executable,
        validated["read_closure_runner"].relative,
        "--workspace-root",
        str(REPO_ROOT),
        "--renderer",
        validated["renderer"].relative,
        "--output",
        str(output),
    ]
    for declared in (
        validated["config"],
        *validated["donors"],
        *validated["controls"],
    ):
        argv.extend(("--allow-read", declared.relative))
    argv.extend(("--", *renderer_argv))
    try:
        result = subprocess.run(
            argv,
            cwd=REPO_ROOT,
            check=False,
            shell=False,
            env=_fixed_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=validated["timeout_seconds"],
        )
    except subprocess.TimeoutExpired as exc:
        raise GoldenV2EmissionError(
            f"fresh read-closed replay timed out after {validated['timeout_seconds']}s"
        ) from exc
    except OSError as exc:
        raise GoldenV2EmissionError(f"cannot launch fresh read-closed replay: {exc}") from exc
    if result.returncode:
        diagnostic = result.stderr.decode("utf-8", errors="replace").strip()
        raise GoldenV2EmissionError(
            f"fresh read-closed replay exited {result.returncode}: {diagnostic}"
        )
    try:
        receipt = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GoldenV2EmissionError(
            "fixed renderer must emit one UTF-8 JSON execution receipt"
        ) from exc
    receipt = _require_exact_keys(
        receipt,
        {
            "schema_version",
            "interface",
            "seed",
            "output",
            "png_sha256",
            "pixel_sha256",
            "png_bytes",
            "size",
            "mode",
            "identity",
            "passed",
        },
        label="fixed renderer receipt",
    )
    if (
        receipt["schema_version"] != fixed_renderer.SCHEMA_VERSION
        or receipt["interface"] != fixed_renderer.INTERFACE
        or receipt["seed"] != reproduction["seed"]
        or os.path.normcase(os.path.abspath(str(receipt["output"])))
        != os.path.normcase(os.path.abspath(output))
        or receipt["png_sha256"] != fixed_renderer.EXPECTED_PNG_SHA256
        or receipt["pixel_sha256"] != fixed_renderer.EXPECTED_PIXEL_SHA256
        or receipt["png_bytes"] != fixed_renderer.EXPECTED_PNG_BYTES
        or receipt["size"] != list(promotion.EXPECTED_SIZE)
        or receipt["mode"] != "RGB"
        or receipt["identity"] != EXPECTED_RENDERER_IDENTITY
        or receipt["passed"] is not True
    ):
        raise GoldenV2EmissionError(
            f"fixed renderer execution receipt changed: {receipt!r}"
        )


def _read_candidate(path: Path, expected: dict[str, Any]) -> tuple[bytes, Image.Image]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise GoldenV2EmissionError(f"renderer did not create its sole output: {exc}") from exc
    if _sha256(data) != expected["png_sha256"] or len(data) != expected["png_bytes"]:
        raise GoldenV2EmissionError("renderer output does not match frozen PNG bytes")
    try:
        with Image.open(io.BytesIO(data)) as opened:
            opened.load()
            if (
                opened.format != "PNG"
                or opened.mode != "RGB"
                or opened.size != promotion.EXPECTED_SIZE
                or opened.info.get("icc_profile") is not None
                or "transparency" in opened.info
            ):
                raise GoldenV2EmissionError(
                    "renderer output must be untagged native RGB PNG at 1536x1024"
                )
            image = opened.copy()
    except OSError as exc:
        raise GoldenV2EmissionError(f"renderer output is not a readable PNG: {exc}") from exc
    pixel_digest = _sha256(image.tobytes())
    if pixel_digest != expected["pixel_sha256"]:
        image.close()
        raise GoldenV2EmissionError("renderer output pixel identity changed")
    return data, image


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, **PNG_SAVE_OPTIONS)
    return buffer.getvalue()


def _write_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _strict_json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def _cleanup_created_root(root: Path, *, expected_parent: Path) -> None:
    """Remove only this emitter's known files; leave unexpected debris untouched."""

    if root.parent.resolve() != expected_parent.resolve():
        return
    try:
        assert_no_reparse_components(root, label="Golden-v2 cleanup root")
    except ReleasePathError:
        return
    for name in OWNED_OUTPUT_NAMES:
        path = root / name
        try:
            if path.is_dir():
                return
            path.unlink(missing_ok=True)
        except OSError:
            return
    try:
        root.rmdir()
    except OSError:
        pass


def _self_validate(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GoldenV2EmissionError(f"cannot re-read emitted JSON: {exc}") from exc
    _require_exact_keys(
        document, set(promotion.EMISSION_REQUIRED_KEYS), label="TEMP emission"
    )
    if (
        document["schema_version"] != "1.0.0"
        or document["id"] != EMISSION_ID
        or document["job_id"] != promotion.JOB_ID
        or document["status"] != promotion.EMISSION_STATUS
        or document["temporary_review_only"] is not True
        or document["previously_accepted"] is not False
        or document["golden_accepted"] is not False
    ):
        raise GoldenV2EmissionError("TEMP emission lifecycle fields changed")
    parse_rfc3339(document["created_at"])
    reproduction = promotion._validate_reproduction_contract(document)
    candidate_record = document["candidate"]
    candidate = promotion._bind_source_record(candidate_record, label="emitted candidate")
    candidate_image = promotion._assert_source_image_record(
        candidate_record,
        candidate,
        label="emitted candidate",
        expected_size=promotion.EXPECTED_SIZE,
    )
    try:
        report = promotion._independent_pixel_audit(candidate, reproduction)
        promotion._assert_pixel_claims_match(document, report, label="TEMP emission")
        view_records = promotion._require_exact_keys(
            document["views"], set(promotion.VIEW_ORDER), label="TEMP emission.views"
        )
        for name in promotion.VIEW_ORDER:
            record = view_records[name]
            binding = promotion._bind_source_record(record, label=f"emitted view {name}")
            view = promotion._assert_source_image_record(
                record,
                binding,
                label=f"emitted view {name}",
                expected_size=promotion.VIEW_DEFINITIONS[name][1],
            )
            try:
                promotion._assert_exact_view_pixels(candidate_image, name, view)
            finally:
                view.close()
        replay_record = document["determinism"]["replay"]
        replay = promotion._bind_source_record(replay_record, label="emitted replay")
        promotion._assert_source_image_record(
            replay_record,
            replay,
            label="emitted replay",
            expected_size=promotion.EXPECTED_SIZE,
        ).close()
        promotion._assert_metric_contract(
            metrics=document["metrics"],
            geometry=document["geometry"],
            identity=document["identity"],
            determinism=document["determinism"],
            replay=replay,
            candidate=candidate,
            persistent=False,
        )
    finally:
        candidate_image.close()
    return document


def emit(output_root: Path, *, config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    final_root = Path(os.path.abspath(output_root))
    assert_no_reparse_components(final_root, label="Golden-v2 TEMP output")
    try:
        relative = final_root.relative_to(TEMP_ROOT)
    except ValueError as exc:
        raise GoldenV2EmissionError(
            f"output root must stay under {TEMP_ROOT}"
        ) from exc
    if not relative.parts:
        raise GoldenV2EmissionError("output root may not equal the TEMP namespace root")
    if final_root.exists() or os.path.lexists(final_root):
        raise GoldenV2EmissionError(f"refusing to replace existing output root: {final_root}")
    final_root.parent.mkdir(parents=True, exist_ok=True)
    assert_no_reparse_components(final_root.parent, label="Golden-v2 TEMP output parent")

    config = _load_fixed_config(config_path)
    _assert_frozen_audit_controls()
    reproduction = _reproduction(config_path, config)
    try:
        validated = promotion._validate_reproduction_contract(
            {"reproduction": reproduction}
        )
    except promotion.K3GoldenPromotionV2Error as exc:
        raise GoldenV2EmissionError(str(exc)) from exc

    stage = final_root.parent / f".{final_root.name}.staging-{uuid.uuid4().hex}"
    if stage.exists() or os.path.lexists(stage):
        raise GoldenV2EmissionError("unavailable private staging path")
    stage.mkdir()
    published = False
    try:
        stage_candidate = stage / "candidate.png"
        stage_replay = stage / "replay.png"
        _run_read_closed(reproduction, validated, stage_candidate)
        _run_read_closed(reproduction, validated, stage_replay)
        candidate_bytes, candidate_image = _read_candidate(
            stage_candidate, config["expected_output"]
        )
        try:
            replay_bytes, replay_image = _read_candidate(
                stage_replay, config["expected_output"]
            )
            replay_image.close()
            if replay_bytes != candidate_bytes:
                raise GoldenV2EmissionError("two fresh read-closed replays differ")

            candidate_binding = bind_file(
                stage_candidate, label="fresh candidate", trackable=False
            )
            report = promotion._independent_pixel_audit(candidate_binding, validated)

            final_candidate = final_root / "candidate.png"
            final_replay = final_root / "replay.png"
            views: dict[str, dict[str, Any]] = {}
            for name in promotion.VIEW_ORDER:
                view_image = promotion._expected_view(candidate_image, name)
                try:
                    view_bytes = _png_bytes(view_image)
                    stage_view = stage / f"view-{name}.png"
                    _write_exclusive(stage_view, view_bytes)
                    views[name] = _source_record(
                        final_root / stage_view.name,
                        view_bytes,
                        size=promotion.VIEW_DEFINITIONS[name][1],
                    )
                finally:
                    view_image.close()

            document = {
                "schema_version": "1.0.0",
                "id": EMISSION_ID,
                "job_id": promotion.JOB_ID,
                "status": promotion.EMISSION_STATUS,
                "created_at": utc_now(),
                "temporary_review_only": True,
                "previously_accepted": False,
                "golden_accepted": False,
                "candidate": _source_record(
                    final_candidate, candidate_bytes, size=promotion.EXPECTED_SIZE
                ),
                "views": views,
                "metrics": report["metrics"],
                "geometry": report["geometry"],
                "identity": report["identity"],
                "determinism": {
                    "independent_in_memory_builds": 2,
                    "replay": _source_record(
                        final_replay, replay_bytes, size=promotion.EXPECTED_SIZE
                    ),
                    "byte_identical": True,
                    "passed": True,
                },
                "reproduction": reproduction,
            }
            _write_exclusive(stage / "emission.json", _strict_json_bytes(document))
        finally:
            candidate_image.close()

        if final_root.exists() or os.path.lexists(final_root):
            raise GoldenV2EmissionError("output root appeared during emission")
        os.rename(stage, final_root)
        published = True
        verified = _self_validate(final_root / "emission.json")
        return {
            "status": promotion.EMISSION_STATUS,
            "temporary_review_only": True,
            "emission": _relative(final_root / "emission.json"),
            "candidate_sha256": verified["candidate"]["sha256"],
            "replay_sha256": verified["determinism"]["replay"]["sha256"],
            "metrics": verified["metrics"],
            "geometry": verified["geometry"],
            "identity": verified["identity"],
            "root_review_created": False,
            "blind_reviews_created": 0,
        }
    except Exception:
        cleanup = final_root if published else stage
        if cleanup.exists() or os.path.lexists(cleanup):
            _cleanup_created_root(cleanup, expected_parent=final_root.parent)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--temporary-output-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    try:
        result = emit(args.temporary_output_root, config_path=args.config)
    except (
        GoldenV2EmissionError,
        promotion.K3GoldenPromotionV2Error,
        BoundArtifactError,
        ReleasePathError,
        OSError,
        ValueError,
    ) as exc:
        print(f"Golden-v2 TEMP emission failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
