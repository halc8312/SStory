#!/usr/bin/env python3
"""Render the frozen K3-v19 bytes through the Golden-v2 fixed CLI.

This adapter intentionally contains no rendering recipe.  It validates the
one tracked config, seed, and ordered donor/control inventory, loads the
byte-frozen v19 implementation from its declared control path, reconstructs
in memory, and writes only the single declared output.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import os
import sys
import sysconfig
import types
from pathlib import Path
from typing import Any, Sequence


SCHEMA_VERSION = "1.0.0"
INTERFACE = "sstory-k3-golden-v2-renderer-config-v1"
CONFIG_PATH = (
    "world/map-production/controls/style-candidate-k-v3-golden-v2/"
    "renderer-config.json"
)
CONFIG_SHA256 = (
    "94c094df66ec1641b78aa3b4cd42b3b3f32824a43b5021f1fb759e8e439e48e4"
)
SEED = "k3-v19-golden-v2-replay-v1"
FROZEN_RENDERER_PATH = (
    "scripts/map-production/build_style_candidate_k3_sparse_ridgeline_v19.py"
)
FROZEN_RENDERER_SHA256 = (
    "92100794ff519fb77c7bca89af74897dcc422c9bb341582d31355d6b98cd229a"
)
REPLAY_CONTRACT_PATH = (
    "world/map-production/controls/style-candidate-k-v3-golden-v2/"
    "v19-replay-contract.json"
)
REPLAY_CONTRACT_SHA256 = (
    "c8a4c4f2bb50905f0904cef050218d3fdafcafc7d11172a92db613774e02b0b6"
)
EXPECTED_PNG_SHA256 = (
    "f2cb6e72ad1fb6e46a8ef0ed881418fd2f7d465edc514113d498714d4d94820a"
)
EXPECTED_PIXEL_SHA256 = (
    "f613b6579c637b6f93f12b7ffd332fd79e0b1cba1f5f992b578bf74adcedd1c3"
)
EXPECTED_PNG_BYTES = 3_630_310
EXPECTED_DONORS = (
    "world/map-production/style-assets/k3-v18-reconstruction-base.png",
    "world/map-production/style-assets/k3-v55-topographic-contour-atlas.png",
    "world/map-production/style-assets/highland-detail-exemplar-v1.png",
    "world/map-production/candidates/style-candidate-h-v4-plan-view-golden-board.png",
)
EXPECTED_CONTROLS = (
    FROZEN_RENDERER_PATH,
    REPLAY_CONTRACT_PATH,
    "world/map-production/style-assets/k3-v18-reconstruction-base.png",
    (
        "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/"
        "k3-v52-canonical-body-control.png"
    ),
    (
        "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/"
        "k3-v52-eight-ridge-control-atlas.json"
    ),
    (
        "world/map-production/prompts/"
        "style-candidate-k-v3-highland-contour-atlas-v55.generation.txt"
    ),
    (
        "world/map-production/prompts/"
        "style-candidate-k-v3-highland-contour-atlas-v55.generation-receipt.json"
    ),
    "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/spec.json",
    "world/map-production/qa/style-candidate-k-v3-highland-source-v55-root-vision.json",
    (
        "world/map-production/qa/automated/"
        "style-candidate-k-v3-sparse-ridgeline-v19-preflight.json"
    ),
    (
        "world/map-production/controls/style-candidate-k-v3-semantic-cleanup/"
        "k3-v52-eight-ridge-control-atlas.png"
    ),
    (
        "world/map-production/controls/style-candidate-k-v3-golden-v2/"
        "audit-control.json"
    ),
    (
        "world/map-production/controls/style-candidate-k-v3-golden-v2/"
        "masks/measurement-inside.png"
    ),
    (
        "world/map-production/controls/style-candidate-k-v3-golden-v2/"
        "masks/texture-reference.png"
    ),
    (
        "world/map-production/controls/style-candidate-k-v3-golden-v2/"
        "masks/permission.png"
    ),
    (
        "world/map-production/controls/style-candidate-k-v3-golden-v2/"
        "masks/protected-features.png"
    ),
    (
        "world/map-production/controls/style-candidate-k-v3-golden-v2/"
        "masks/road-calm-18px.png"
    ),
    (
        "world/map-production/controls/style-candidate-k-v3-golden-v2/"
        "masks/selected-components.png"
    ),
)
EXPECTED_OUTPUT = {
    "png_sha256": EXPECTED_PNG_SHA256,
    "pixel_sha256": EXPECTED_PIXEL_SHA256,
    "png_bytes": EXPECTED_PNG_BYTES,
    "width": 1536,
    "height": 1024,
    "mode": "RGB",
}
CONFIG_KEYS = frozenset(
    {
        "schema_version",
        "interface",
        "seed",
        "expected_output",
        "replay_contract",
        "frozen_renderer",
        "donors",
        "controls",
    }
)


class GoldenV2RendererError(RuntimeError):
    """Raised before an output is opened when fixed authority changes."""


class _SingleOccurrenceAction(argparse.Action):
    """Reject duplicate singleton flags instead of silently taking the last."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        if getattr(namespace, self.dest, None) is not None:
            parser.error(f"{option_string} may be specified exactly once")
        setattr(namespace, self.dest, values)


class _PlainArrayMaskShim:
    """Prevent NumPy's unused masked-array package from lazy discovery."""

    @staticmethod
    def is_masked(value: Any) -> bool:
        del value
        return False

    @staticmethod
    def isMaskedArray(value: Any) -> bool:  # noqa: N802 - NumPy compatibility
        del value
        return False


def _load_json_without_discovery() -> types.ModuleType:
    """Load stdlib JSON from explicit files without package directory scans."""

    existing = sys.modules.get("json")
    if isinstance(existing, types.ModuleType) and all(
        hasattr(existing, name) for name in ("loads", "dumps", "JSONDecodeError")
    ):
        return existing

    stdlib = sysconfig.get_path("stdlib")
    if not isinstance(stdlib, str) or not stdlib:
        raise GoldenV2RendererError("cannot locate the fixed stdlib JSON runtime")
    package_root = os.path.join(stdlib, "json")
    package = types.ModuleType("json")
    package.__file__ = os.path.join(package_root, "__init__.py")
    package.__package__ = "json"
    package.__path__ = [package_root]
    package.__spec__ = None
    sys.modules["json"] = package

    def load_submodule(name: str) -> types.ModuleType:
        qualified = f"json.{name}"
        path = os.path.join(package_root, f"{name}.py")
        try:
            with open(path, "rb") as stream:
                source = stream.read()
            code = compile(source, path, "exec", dont_inherit=True)
        except OSError as exc:
            raise GoldenV2RendererError(
                f"cannot read fixed stdlib module {qualified}: {exc}"
            ) from exc
        module = types.ModuleType(qualified)
        module.__file__ = path
        module.__package__ = "json"
        module.__spec__ = None
        sys.modules[qualified] = module
        setattr(package, name, module)
        exec(code, module.__dict__)
        return module

    scanner = load_submodule("scanner")
    decoder = load_submodule("decoder")
    encoder = load_submodule("encoder")
    package.scanner = scanner
    package.decoder = decoder
    package.encoder = encoder
    package.JSONDecodeError = decoder.JSONDecodeError

    def loads(
        document: str,
        *,
        cls: Any = None,
        object_hook: Any = None,
        parse_float: Any = None,
        parse_int: Any = None,
        parse_constant: Any = None,
        object_pairs_hook: Any = None,
        **kwargs: Any,
    ) -> Any:
        decoder_class = decoder.JSONDecoder if cls is None else cls
        return decoder_class(
            object_hook=object_hook,
            parse_float=parse_float,
            parse_int=parse_int,
            parse_constant=parse_constant,
            object_pairs_hook=object_pairs_hook,
            **kwargs,
        ).decode(document)

    def dumps(
        value: Any,
        *,
        skipkeys: bool = False,
        ensure_ascii: bool = True,
        check_circular: bool = True,
        allow_nan: bool = True,
        cls: Any = None,
        indent: int | str | None = None,
        separators: tuple[str, str] | None = None,
        default: Any = None,
        sort_keys: bool = False,
        **kwargs: Any,
    ) -> str:
        encoder_class = encoder.JSONEncoder if cls is None else cls
        return encoder_class(
            skipkeys=skipkeys,
            ensure_ascii=ensure_ascii,
            check_circular=check_circular,
            allow_nan=allow_nan,
            sort_keys=sort_keys,
            indent=indent,
            separators=separators,
            default=default,
            **kwargs,
        ).encode(value)

    package.loads = loads
    package.dumps = dumps
    return package


json = _load_json_without_discovery()


def _load_numpy_fft_without_discovery(numpy_module: types.ModuleType) -> Any:
    """Prime the one lazy NumPy package used by frozen v19 without listing."""

    existing = sys.modules.get("numpy.fft")
    if existing is not None:
        numpy_module.__dict__["fft"] = existing
        return existing
    numpy_file = numpy_module.__dict__.get("__file__")
    extension_suffix = sysconfig.get_config_var("EXT_SUFFIX")
    if not isinstance(numpy_file, str) or not isinstance(extension_suffix, str):
        raise GoldenV2RendererError("cannot bind the fixed NumPy FFT runtime")
    fft_root = os.path.join(os.path.dirname(numpy_file), "fft")
    entries = {
        "__init__.py",
        "_helper.py",
        "_pocketfft.py",
        "helper.py",
        f"_pocketfft_umath{extension_suffix}",
    }
    loader_details = (
        (
            importlib.machinery.ExtensionFileLoader,
            importlib.machinery.EXTENSION_SUFFIXES,
        ),
        (importlib.machinery.SourceFileLoader, importlib.machinery.SOURCE_SUFFIXES),
        (
            importlib.machinery.SourcelessFileLoader,
            importlib.machinery.BYTECODE_SUFFIXES,
        ),
    )
    finder = importlib.machinery.FileFinder(fft_root, *loader_details)
    try:
        finder._path_mtime = os.stat(fft_root).st_mtime  # type: ignore[attr-defined]
    except OSError as exc:
        raise GoldenV2RendererError(f"cannot stat fixed NumPy FFT runtime: {exc}") from exc
    finder._path_cache = entries  # type: ignore[attr-defined]
    finder._relaxed_path_cache = {  # type: ignore[attr-defined]
        entry.casefold() for entry in entries
    }
    sys.path_importer_cache[fft_root] = finder
    try:
        loaded = __import__("numpy.fft", fromlist=("fft2", "ifft2", "fftfreq"))
    except Exception as exc:
        raise GoldenV2RendererError(
            f"cannot load fixed NumPy FFT runtime: {type(exc).__name__}: {exc}"
        ) from exc
    for name in ("fft2", "ifft2", "fftfreq"):
        if not callable(getattr(loaded, name, None)):
            raise GoldenV2RendererError(f"fixed NumPy FFT runtime lacks {name}")
    numpy_module.__dict__["fft"] = loaded
    return loaded


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_arg(path: Path) -> str:
    return path.as_posix()


def _root_identity(workspace_root: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(workspace_root)))


def _workspace_path(workspace_root: str | Path, relative: str) -> str:
    return os.path.normcase(
        os.path.abspath(
            os.path.join(_root_identity(workspace_root), relative.replace("/", os.sep))
        )
    )


def _load_json(data: bytes, *, label: str) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-standard numeric constant {value!r}")

    try:
        value = json.loads(data.decode("utf-8"), parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise GoldenV2RendererError(f"{label} is not canonical UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise GoldenV2RendererError(f"{label} must contain one JSON object")
    return value


def _read_bound(
    workspace_root: str | Path,
    relative: str,
    expected_sha256: str,
    *,
    label: str,
) -> bytes:
    path = _workspace_path(workspace_root, relative)
    try:
        with open(path, "rb") as stream:
            payload = stream.read()
    except OSError as exc:
        raise GoldenV2RendererError(f"cannot read {label}: {exc}") from exc
    observed = _sha256(payload)
    if observed != expected_sha256:
        raise GoldenV2RendererError(
            f"{label} SHA-256 mismatch: expected {expected_sha256}, got {observed}"
        )
    return payload


def load_fixed_config(
    workspace_root: str | Path, config_argument: Path
) -> dict[str, Any]:
    """Bind and validate the only approved config document."""

    if _canonical_arg(config_argument) != CONFIG_PATH:
        raise GoldenV2RendererError(f"--config must equal {CONFIG_PATH}")
    payload = _read_bound(
        workspace_root, CONFIG_PATH, CONFIG_SHA256, label="Golden-v2 renderer config"
    )
    config = _load_json(payload, label="Golden-v2 renderer config")
    if set(config) != CONFIG_KEYS:
        raise GoldenV2RendererError("renderer config does not have the exact closed schema")
    expected_replay = {
        "path": REPLAY_CONTRACT_PATH,
        "sha256": REPLAY_CONTRACT_SHA256,
    }
    expected_renderer = {
        "path": FROZEN_RENDERER_PATH,
        "sha256": FROZEN_RENDERER_SHA256,
    }
    if (
        config["schema_version"] != SCHEMA_VERSION
        or config["interface"] != INTERFACE
        or config["seed"] != SEED
        or config["expected_output"] != EXPECTED_OUTPUT
        or config["replay_contract"] != expected_replay
        or config["frozen_renderer"] != expected_renderer
        or config["donors"] != list(EXPECTED_DONORS)
        or config["controls"] != list(EXPECTED_CONTROLS)
    ):
        raise GoldenV2RendererError("renderer config authority changed")
    return config


def validate_invocation(
    workspace_root: str | Path,
    *,
    config: Path,
    seed: str,
    donors: Sequence[Path],
    controls: Sequence[Path],
) -> dict[str, Any]:
    """Validate config, seed, and the complete ordered CLI inventory."""

    document = load_fixed_config(workspace_root, config)
    if seed != SEED:
        raise GoldenV2RendererError(f"--seed must equal {SEED}")
    observed_donors = tuple(_canonical_arg(path) for path in donors)
    observed_controls = tuple(_canonical_arg(path) for path in controls)
    if observed_donors != EXPECTED_DONORS:
        raise GoldenV2RendererError(
            "--donor inventory/order must exactly match renderer-config.json"
        )
    if observed_controls != EXPECTED_CONTROLS:
        raise GoldenV2RendererError(
            "--control inventory/order must exactly match renderer-config.json"
        )
    return document


def _load_frozen_renderer(workspace_root: str | Path) -> dict[str, Any]:
    source = _read_bound(
        workspace_root,
        FROZEN_RENDERER_PATH,
        FROZEN_RENDERER_SHA256,
        label="frozen K3-v19 renderer",
    )
    renderer_path = _workspace_path(workspace_root, FROZEN_RENDERER_PATH)
    module_name = "_sstory_frozen_k3_v19_renderer"
    loaded = types.ModuleType(module_name)
    loaded.__file__ = renderer_path
    loaded.__package__ = None
    loaded.__spec__ = None
    loaded.__dict__["__builtins__"] = __builtins__
    sys.modules[module_name] = loaded
    module = loaded.__dict__
    try:
        code = compile(
            source,
            renderer_path,
            "exec",
            dont_inherit=True,
        )
        exec(code, module)
    except Exception as exc:
        raise GoldenV2RendererError(
            f"cannot load frozen K3-v19 renderer: {type(exc).__name__}: {exc}"
        ) from exc
    for name in ("load_replay_inputs", "reconstruct", "png_bytes", "array_sha256"):
        if not callable(module.get(name)):
            raise GoldenV2RendererError(f"frozen renderer is missing callable {name}")
    if (
        module.get("EXPECTED_PNG_SHA256") != EXPECTED_PNG_SHA256
        or module.get("EXPECTED_PIXEL_SHA256") != EXPECTED_PIXEL_SHA256
        or module.get("EXPECTED_PNG_BYTES") != EXPECTED_PNG_BYTES
    ):
        raise GoldenV2RendererError("frozen renderer output authority changed")
    numpy_module = module.get("np")
    if not isinstance(numpy_module, types.ModuleType):
        raise GoldenV2RendererError("frozen renderer did not bind NumPy")
    if "ma" not in numpy_module.__dict__:
        numpy_module.__dict__["ma"] = _PlainArrayMaskShim()
    _load_numpy_fft_without_discovery(numpy_module)
    return module


def _render_payload(workspace_root: str | Path) -> tuple[bytes, dict[str, int]]:
    _read_bound(
        workspace_root,
        REPLAY_CONTRACT_PATH,
        REPLAY_CONTRACT_SHA256,
        label="v19 replay contract",
    )
    module = _load_frozen_renderer(workspace_root)
    try:
        inputs = module["load_replay_inputs"](
            Path(_workspace_path(workspace_root, REPLAY_CONTRACT_PATH))
        )
        result = module["reconstruct"](inputs)
        pixel_sha256 = module["array_sha256"](result.candidate)
        payload = module["png_bytes"](result.candidate)
    except Exception as exc:
        raise GoldenV2RendererError(
            f"frozen K3-v19 replay failed: {type(exc).__name__}: {exc}"
        ) from exc
    if (
        pixel_sha256 != EXPECTED_PIXEL_SHA256
        or len(payload) != EXPECTED_PNG_BYTES
        or _sha256(payload) != EXPECTED_PNG_SHA256
    ):
        raise GoldenV2RendererError("frozen K3-v19 output bytes changed")
    return payload, dict(result.identity)


def _validated_output(workspace_root: str | Path, output: Path) -> str:
    root = _root_identity(workspace_root)
    resolved = os.path.normcase(os.path.abspath(os.fspath(output)))
    try:
        inside = os.path.commonpath((resolved, root)) == root
    except ValueError as exc:
        raise GoldenV2RendererError("--output must stay inside the workspace") from exc
    if not inside:
        raise GoldenV2RendererError("--output must stay inside the workspace")
    declared_inputs = {
        _workspace_path(root, relative)
        for relative in (CONFIG_PATH, *EXPECTED_DONORS, *EXPECTED_CONTROLS)
    }
    if resolved in declared_inputs:
        raise GoldenV2RendererError("--output must not alias a declared input")
    return resolved


def render(
    *,
    config: Path,
    seed: str,
    donors: Sequence[Path],
    controls: Sequence[Path],
    output: Path,
) -> dict[str, Any]:
    """Validate every authority before opening and writing the sole output."""

    workspace_root = _root_identity(os.getcwd())
    validate_invocation(
        workspace_root,
        config=config,
        seed=seed,
        donors=donors,
        controls=controls,
    )
    resolved_output = _validated_output(workspace_root, output)
    payload, identity = _render_payload(workspace_root)
    try:
        with open(resolved_output, "xb") as stream:
            written = stream.write(payload)
            stream.flush()
    except OSError as exc:
        raise GoldenV2RendererError(f"cannot write declared output: {exc}") from exc
    if written != len(payload):
        raise GoldenV2RendererError("declared output write was incomplete")
    return {
        "schema_version": SCHEMA_VERSION,
        "interface": INTERFACE,
        "seed": SEED,
        "output": resolved_output,
        "png_sha256": EXPECTED_PNG_SHA256,
        "pixel_sha256": EXPECTED_PIXEL_SHA256,
        "png_bytes": EXPECTED_PNG_BYTES,
        "size": [1536, 1024],
        "mode": "RGB",
        "identity": identity,
        "passed": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "--config", type=Path, action=_SingleOccurrenceAction, required=True
    )
    parser.add_argument("--seed", action=_SingleOccurrenceAction, required=True)
    parser.add_argument("--donor", type=Path, action="append", required=True)
    parser.add_argument("--control", type=Path, action="append", required=True)
    parser.add_argument(
        "--output", type=Path, action=_SingleOccurrenceAction, required=True
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        receipt = render(
            config=args.config,
            seed=args.seed,
            donors=args.donor,
            controls=args.control,
            output=args.output,
        )
    except GoldenV2RendererError as exc:
        parser.exit(2, f"Golden-v2 K3 renderer failed closed: {exc}\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
