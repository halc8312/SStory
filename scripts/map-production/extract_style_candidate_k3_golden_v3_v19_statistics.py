#!/usr/bin/env python3
"""Extract a sealed, phase-free statistics firewall from the frozen v19 replay.

The default operation is ``--check``.  It verifies the byte-frozen renderer,
replay contract, transitive hash claims, and the closed output schema using only
the Python standard library.  It neither imports the renderer nor imports a
pixel/FFT package.

Only an explicit ``--extract`` imports and runs v19.  Extraction uses the
replayed final RGB solely for the three OpenCV-encoded Lab channel medians.  Its
distribution and spectrum measurements use ``BuildResult.contour_field``.
No pixels, coordinates, crops, phases, colours, prompts, material references,
or arbitrary metadata can enter the exact-key output schema.

Numerical contract (part of SCHEMA_ID):

* Every numeric result is a JSON integer holding signed 32-bit Q16.16.  Values
  are multiplied by 65536 and rounded to nearest, ties to even.  Overflow and
  non-finite inputs fail closed.
* A body's contour quantiles are Hyndman/Fan type 7 at the 17 fixed positions
  k/16 for k=0..16.  Samples are sorted ascending; h=(n-1)p; adjacent order
  statistics are linearly interpolated.  Equal samples remain equal, so ties
  require no rank-dependent tie break.  Lab channel medians use the same rule
  at p=1/2 independently for OpenCV's uint8 [L,a,b] channels.
* A spectrum starts at the tight axis-aligned support bounding box.  Eight zero
  samples are added on all four sides.  A separable symmetric Hann window
  w[i]=0.5-0.5*cos(2*pi*i/(n-1)) is evaluated on that padded shape.  The DC
  level is the support/Hann-weighted arithmetic mean; it is subtracted before
  multiplying by the support and window.  Pixels outside support are zero.  An
  exactly constant support is defined to have sixteen zero power bins (this
  check precedes floating-point mean/window evaluation).
* numpy.fft.rfft2 is applied without further padding or scaling.  One-sided
  columns have Hermitian weights 2, except DC and (for even widths) Nyquist,
  which have weight 1.  The DC coefficient [0,0] is set to zero.  For padded
  dimensions h,w, each remaining coefficient is assigned to
      min(15, floor(16*hypot(fftfreq(h), rfftfreq(w))/sqrt(0.5^2+0.5^2))).
  Bin sums are divided by total non-DC weighted power before Q16.16
  quantization.  A zero-power body has sixteen zero bins.
* Canonical JSON is UTF-8, ASCII-escaped, recursively key-sorted, uses comma and
  colon separators without spaces, forbids NaN/Infinity, and ends in one LF.
  The output is created with O_EXCL and is never overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping, Sequence


SCHEMA_ID = "sstory.k3.golden-v3.v19-contour-statistics.v1"
RECORD_ID = "k3-golden-v3-v19-contour-field-bodies-32-224"

V19_RENDERER_RELATIVE_PATH = Path(
    "scripts/map-production/build_style_candidate_k3_sparse_ridgeline_v19.py"
)
V19_REPLAY_CONTRACT_RELATIVE_PATH = Path(
    "world/map-production/controls/style-candidate-k-v3-golden-v2/"
    "v19-replay-contract.json"
)
EXPECTED_V19_RENDERER_SHA256 = (
    "92100794ff519fb77c7bca89af74897dcc422c9bb341582d31355d6b98cd229a"
)
EXPECTED_V19_REPLAY_CONTRACT_SHA256 = (
    "c8a4c4f2bb50905f0904cef050218d3fdafcafc7d11172a92db613774e02b0b6"
)
EXPECTED_V19_TRANSITIVE_INPUTS_SHA256 = (
    "50aa6962fcc59c7ffb229ad5a510f0151d7a9d2500deebad2953daec27b6390e"
)
EXPECTED_V19_FINAL_PIXEL_ARRAY_SHA256 = (
    "f613b6579c637b6f93f12b7ffd332fd79e0b1cba1f5f992b578bf74adcedd1c3"
)
EXPECTED_V19_CONTOUR_FIELD_ARRAY_SHA256 = (
    "a9b27c4a0cc6bf3a80702794853d5053d024e22b16088597fa4b32fd06e8b022"
)

BODY_CONTROL_VALUES = (32, 64, 96, 128, 160, 192, 224)
EXPECTED_SUPPORT_SHA256 = {
    32: "22411dccde51d280322d6357bf3bfd7103c83316df75d5e153c4d4628e573d94",
    64: "f528cfa39a95ea1f49c9cefaa35848f7ce7bb9b0939eab325501aabfd04f2f0e",
    96: "5c7219a4a67dd2be266011791b7ff04e2c19e996088ebd39c61760ab0e9240c9",
    128: "b3ff40a24077abb168a1490a1b23b8841d024243ec201a3833799bc8c7d38d81",
    160: "b28ce325cc9a0abffafa3c4d4cf94bb85b468973fbef972cc2f082148f657ccd",
    192: "6e2dcb974dfb2596c861916719c637df70b5a16095527abcaa9dba4f377f545a",
    224: "df6ef1892510bf62dc55d46fbe25b365e16d9ec194284245341ebcc712ea0bc9",
}

Q_TOTAL_BITS = 32
Q_FRACTION_BITS = 16
Q_SCALE = 1 << Q_FRACTION_BITS
Q_MIN = -(1 << (Q_TOTAL_BITS - 1))
Q_MAX = (1 << (Q_TOTAL_BITS - 1)) - 1
SPATIAL_PADDING_PIXELS = 8
RADIAL_POWER_LENGTH = 16
QUANTILE_DENOMINATOR = 16
QUANTILE_NUMERATORS = tuple(range(QUANTILE_DENOMINATOR + 1))
QUANTILE_LENGTH = len(QUANTILE_NUMERATORS)
NYQUIST_RADIUS = math.sqrt(0.5**2 + 0.5**2)

TOP_LEVEL_KEYS = frozenset(
    {"schema_id", "record_id", "source_hashes", "body_statistics"}
)
SOURCE_HASH_KEY_ORDER = (
    "v19_contour_field_array_sha256",
    "v19_final_pixel_array_sha256",
    "v19_renderer_sha256",
    "v19_replay_contract_sha256",
    "v19_statistics_extractor_sha256",
    "v19_transitive_inputs_sha256",
)
SOURCE_HASH_KEYS = frozenset(SOURCE_HASH_KEY_ORDER)
BODY_STATISTIC_KEYS = frozenset(
    {"support_sha256", "median_lab_q16", "radial_power_q16", "quantiles_q16"}
)
FROZEN_SOURCE_HASHES = {
    "v19_renderer_sha256": EXPECTED_V19_RENDERER_SHA256,
    "v19_replay_contract_sha256": EXPECTED_V19_REPLAY_CONTRACT_SHA256,
    "v19_transitive_inputs_sha256": EXPECTED_V19_TRANSITIVE_INPUTS_SHA256,
    "v19_final_pixel_array_sha256": EXPECTED_V19_FINAL_PIXEL_ARRAY_SHA256,
    "v19_contour_field_array_sha256": EXPECTED_V19_CONTOUR_FIELD_ARRAY_SHA256,
}

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
V19_INTERFACE = "sstory-k3-sparse-ridgeline-v19-replay-v2"
V19_SCHEMA_VERSION = "1.0.0"
CONTRACT_DIRECT_INPUT_KEYS = (
    "base_v18",
    "generated_layout_control",
    "canonical_body_control",
    "control_atlas_metadata",
    "imagegen_prompt",
    "generation_receipt",
)
CONTRACT_AUTHORITY_ROLES = frozenset(
    {
        "canonical-k3-spec",
        "v55-root-vision-review",
        "v55-robust-recipe-verification",
        "v52-control-atlas",
        "v55-copperplate-material-reference",
        "v55-palette-parchment-reference",
    }
)
CONTRACT_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "interface", *CONTRACT_DIRECT_INPUT_KEYS, "authorities"}
)


class StatisticsFirewallError(RuntimeError):
    """Raised before a statistics authority is created."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_without_lf(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise StatisticsFirewallError(f"value is not canonical JSON: {exc}") from exc
    return rendered.encode("utf-8")


def _reject_duplicate_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StatisticsFirewallError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _load_json_object(payload: bytes, label: str) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise StatisticsFirewallError(f"{label} contains forbidden constant {value!r}")

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_object_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise StatisticsFirewallError(f"{label} is not strict UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise StatisticsFirewallError(f"{label} must contain exactly one JSON object")
    return value


def _read_frozen_file(path: Path, expected_sha256: str, label: str) -> bytes:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise StatisticsFirewallError(f"{label} must be a regular non-symlink file: {path}")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise StatisticsFirewallError(f"cannot read {label}: {exc}") from exc
    actual = _sha256_bytes(payload)
    if actual != expected_sha256:
        raise StatisticsFirewallError(
            f"{label} SHA-256 changed: {actual}/{expected_sha256}"
        )
    return payload


def statistics_extractor_sha256() -> str:
    """Hash the final extractor bytes; this value is deliberately not hardcoded."""

    path = Path(__file__)
    if path.is_symlink() or not path.is_file():
        raise StatisticsFirewallError(
            f"statistics extractor must be a regular non-symlink file: {path}"
        )
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise StatisticsFirewallError(f"cannot read statistics extractor: {exc}") from exc
    return _sha256_bytes(payload)


def expected_source_hashes() -> dict[str, str]:
    """Return the exact source map, including the live final extractor hash."""

    values = {
        **FROZEN_SOURCE_HASHES,
        "v19_statistics_extractor_sha256": statistics_extractor_sha256(),
    }
    if set(values) != SOURCE_HASH_KEYS:
        raise StatisticsFirewallError("source hash schema changed")
    return {key: values[key] for key in SOURCE_HASH_KEY_ORDER}


def _require_exact_keys(value: Any, keys: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        observed = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise StatisticsFirewallError(
            f"{label} keys must be exactly {sorted(keys)}; observed={observed}"
        )
    return value


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise StatisticsFirewallError(f"{label} must be one lowercase SHA-256")
    return value


def _validate_contract_record(value: Any, label: str) -> dict[str, str]:
    record = _require_exact_keys(value, frozenset({"path", "sha256"}), label)
    if not isinstance(record["path"], str) or not record["path"]:
        raise StatisticsFirewallError(f"{label}.path must be a non-empty string")
    _require_sha256(record["sha256"], f"{label}.sha256")
    return record


def _transitive_inputs_sha256(contract: Mapping[str, Any]) -> str:
    """Validate the frozen contract shape and hash only its named byte claims."""

    record = _require_exact_keys(contract, CONTRACT_TOP_LEVEL_KEYS, "v19 contract")
    if record["schema_version"] != V19_SCHEMA_VERSION:
        raise StatisticsFirewallError("v19 contract schema_version changed")
    if record["interface"] != V19_INTERFACE:
        raise StatisticsFirewallError("v19 contract interface changed")

    direct: dict[str, str] = {}
    for name in CONTRACT_DIRECT_INPUT_KEYS:
        binding = _validate_contract_record(record[name], f"v19 contract.{name}")
        direct[name] = binding["sha256"]

    authorities = record["authorities"]
    if not isinstance(authorities, list) or len(authorities) != len(
        CONTRACT_AUTHORITY_ROLES
    ):
        raise StatisticsFirewallError("v19 contract authority count changed")
    authority_hashes: dict[str, str] = {}
    for index, value in enumerate(authorities):
        authority = _require_exact_keys(
            value,
            frozenset({"role", "path", "sha256"}),
            f"v19 contract.authorities[{index}]",
        )
        role = authority["role"]
        if not isinstance(role, str) or role not in CONTRACT_AUTHORITY_ROLES:
            raise StatisticsFirewallError(
                f"v19 contract.authorities[{index}].role is not frozen"
            )
        if role in authority_hashes:
            raise StatisticsFirewallError(f"duplicate v19 authority role: {role}")
        if not isinstance(authority["path"], str) or not authority["path"]:
            raise StatisticsFirewallError(
                f"v19 contract.authorities[{index}].path must be non-empty"
            )
        authority_hashes[role] = _require_sha256(
            authority["sha256"], f"v19 contract.authorities[{index}].sha256"
        )
    if set(authority_hashes) != CONTRACT_AUTHORITY_ROLES:
        raise StatisticsFirewallError("v19 contract authority roles changed")
    closed_claims = {"inputs": direct, "authorities": authority_hashes}
    return _sha256_bytes(_canonical_json_without_lf(closed_claims))


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def validate_schema_definition() -> None:
    if BODY_CONTROL_VALUES != (32, 64, 96, 128, 160, 192, 224):
        raise StatisticsFirewallError("body-control domain changed")
    if 255 in BODY_CONTROL_VALUES or set(EXPECTED_SUPPORT_SHA256) != set(
        BODY_CONTROL_VALUES
    ):
        raise StatisticsFirewallError("body-255 or an unbound support entered schema")
    if (
        Q_TOTAL_BITS != 32
        or Q_FRACTION_BITS != 16
        or Q_SCALE != 65_536
        or Q_MIN != -2_147_483_648
        or Q_MAX != 2_147_483_647
    ):
        raise StatisticsFirewallError("signed Q16.16 contract changed")
    if SPATIAL_PADDING_PIXELS != 8 or RADIAL_POWER_LENGTH != 16:
        raise StatisticsFirewallError("spatial/radial contract changed")
    if QUANTILE_DENOMINATOR != 16 or QUANTILE_NUMERATORS != tuple(range(17)):
        raise StatisticsFirewallError("quantile positions changed")
    if QUANTILE_LENGTH != 17:
        raise StatisticsFirewallError("quantile vector length changed")
    if TOP_LEVEL_KEYS != frozenset(
        {"schema_id", "record_id", "source_hashes", "body_statistics"}
    ):
        raise StatisticsFirewallError("top-level schema is not closed")
    if BODY_STATISTIC_KEYS != frozenset(
        {"support_sha256", "median_lab_q16", "radial_power_q16", "quantiles_q16"}
    ):
        raise StatisticsFirewallError("body statistics schema is not closed")
    if set(FROZEN_SOURCE_HASHES) != SOURCE_HASH_KEYS - {
        "v19_statistics_extractor_sha256"
    }:
        raise StatisticsFirewallError("source hash schema changed")
    for label, digest in {
        **expected_source_hashes(),
        **{f"support-{body}": digest for body, digest in EXPECTED_SUPPORT_SHA256.items()},
    }.items():
        _require_sha256(digest, label)


def check_sources(
    repo_root: Path | None = None,
    replay_contract_path: Path | None = None,
) -> dict[str, str]:
    """Check byte-closed text sources without importing or running v19."""

    validate_schema_definition()
    root = repository_root() if repo_root is None else Path(repo_root).resolve()
    renderer_path = root / V19_RENDERER_RELATIVE_PATH
    contract_path = (
        root / V19_REPLAY_CONTRACT_RELATIVE_PATH
        if replay_contract_path is None
        else Path(replay_contract_path)
    )
    renderer_payload = _read_frozen_file(
        renderer_path, EXPECTED_V19_RENDERER_SHA256, "v19 renderer"
    )
    if EXPECTED_V19_CONTOUR_FIELD_ARRAY_SHA256.encode("ascii") not in renderer_payload:
        raise StatisticsFirewallError(
            "v19 renderer no longer contains the committed contour_field array hash"
        )
    if EXPECTED_V19_FINAL_PIXEL_ARRAY_SHA256.encode("ascii") not in renderer_payload:
        raise StatisticsFirewallError(
            "v19 renderer no longer contains the committed final pixel-array hash"
        )
    contract_payload = _read_frozen_file(
        contract_path,
        EXPECTED_V19_REPLAY_CONTRACT_SHA256,
        "v19 replay contract",
    )
    contract = _load_json_object(contract_payload, "v19 replay contract")
    transitive = _transitive_inputs_sha256(contract)
    if transitive != EXPECTED_V19_TRANSITIVE_INPUTS_SHA256:
        raise StatisticsFirewallError(
            "v19 transitive input claims changed: "
            f"{transitive}/{EXPECTED_V19_TRANSITIVE_INPUTS_SHA256}"
        )
    return expected_source_hashes()


def _require_q16(value: Any, label: str, *, nonnegative: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StatisticsFirewallError(f"{label} must be a JSON integer")
    if value < Q_MIN or value > Q_MAX:
        raise StatisticsFirewallError(f"{label} is outside signed Q16.16 range")
    if nonnegative and value < 0:
        raise StatisticsFirewallError(f"{label} must be nonnegative Q16.16")
    return value


def _require_q16_vector(
    value: Any,
    length: int,
    label: str,
    *,
    nonnegative: bool = False,
) -> list[int]:
    if not isinstance(value, list) or len(value) != length:
        raise StatisticsFirewallError(f"{label} must have exactly {length} entries")
    return [
        _require_q16(item, f"{label}[{index}]", nonnegative=nonnegative)
        for index, item in enumerate(value)
    ]


def validate_statistics_record(value: Any) -> dict[str, Any]:
    """Validate the exact sealed schema; unknown keys and bool-as-int fail."""

    record = _require_exact_keys(value, TOP_LEVEL_KEYS, "statistics record")
    if record["schema_id"] != SCHEMA_ID:
        raise StatisticsFirewallError("statistics schema_id changed")
    if record["record_id"] != RECORD_ID:
        raise StatisticsFirewallError("statistics record_id changed")

    source_hashes = _require_exact_keys(
        record["source_hashes"], SOURCE_HASH_KEYS, "statistics source_hashes"
    )
    for key, expected in expected_source_hashes().items():
        actual = _require_sha256(source_hashes[key], f"source_hashes.{key}")
        if actual != expected:
            raise StatisticsFirewallError(
                f"source_hashes.{key} changed: {actual}/{expected}"
            )

    body_statistics = _require_exact_keys(
        record["body_statistics"],
        frozenset(str(value) for value in BODY_CONTROL_VALUES),
        "statistics body_statistics",
    )
    for control_value in BODY_CONTROL_VALUES:
        label = f"body_statistics.{control_value}"
        body = _require_exact_keys(
            body_statistics[str(control_value)], BODY_STATISTIC_KEYS, label
        )
        support = _require_sha256(body["support_sha256"], f"{label}.support_sha256")
        if support != EXPECTED_SUPPORT_SHA256[control_value]:
            raise StatisticsFirewallError(f"{label}.support_sha256 changed")
        lab = _require_q16_vector(body["median_lab_q16"], 3, f"{label}.median_lab_q16")
        if any(channel < 0 or channel > 255 * Q_SCALE for channel in lab):
            raise StatisticsFirewallError(f"{label}.median_lab_q16 is outside uint8 Lab")
        radial = _require_q16_vector(
            body["radial_power_q16"],
            RADIAL_POWER_LENGTH,
            f"{label}.radial_power_q16",
            nonnegative=True,
        )
        if any(item > Q_SCALE for item in radial):
            raise StatisticsFirewallError(f"{label}.radial_power_q16 exceeds unity")
        radial_sum = sum(radial)
        if radial_sum != 0 and abs(radial_sum - Q_SCALE) > RADIAL_POWER_LENGTH // 2:
            raise StatisticsFirewallError(
                f"{label}.radial_power_q16 is neither zero nor normalized"
            )
        quantiles = _require_q16_vector(
            body["quantiles_q16"], QUANTILE_LENGTH, f"{label}.quantiles_q16"
        )
        if quantiles != sorted(quantiles):
            raise StatisticsFirewallError(f"{label}.quantiles_q16 is not monotone")
    return record


def canonical_statistics_json(value: Any) -> bytes:
    record = validate_statistics_record(value)
    return _canonical_json_without_lf(record) + b"\n"


def load_canonical_statistics(path: Path) -> dict[str, Any]:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise StatisticsFirewallError("statistics authority must be a regular file")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise StatisticsFirewallError(f"cannot read statistics authority: {exc}") from exc
    value = _load_json_object(payload, "statistics authority")
    canonical = canonical_statistics_json(value)
    if payload != canonical:
        raise StatisticsFirewallError("statistics authority is not canonical JSON")
    return value


def _quantize_q16(value: float, label: str) -> int:
    numeric = float(value)
    if not math.isfinite(numeric):
        raise StatisticsFirewallError(f"{label} is non-finite")
    quantized = int(round(numeric * Q_SCALE))
    if quantized < Q_MIN or quantized > Q_MAX:
        raise StatisticsFirewallError(f"{label} overflows signed Q16.16")
    return quantized


def _type7_quantile(sorted_values: Any, numerator: int, denominator: int) -> float:
    size = int(sorted_values.size)
    if size <= 0:
        raise StatisticsFirewallError("cannot measure an empty support")
    if denominator <= 0 or numerator < 0 or numerator > denominator:
        raise StatisticsFirewallError("invalid fixed quantile position")
    scaled_rank = (size - 1) * numerator
    lower = scaled_rank // denominator
    remainder = scaled_rank % denominator
    lower_value = float(sorted_values[lower])
    if remainder == 0:
        return lower_value
    upper_value = float(sorted_values[lower + 1])
    return (
        lower_value * (denominator - remainder) + upper_value * remainder
    ) / denominator


def _symmetric_hann(length: int, np: ModuleType) -> Any:
    if length < 2:
        raise StatisticsFirewallError("padded Hann dimension must be at least two")
    positions = np.arange(length, dtype=np.float64)
    return 0.5 - 0.5 * np.cos((2.0 * np.pi * positions) / float(length - 1))


def _radial_power_q16(contour_field: Any, support: Any, np: ModuleType) -> list[int]:
    rows, columns = np.nonzero(support)
    if int(rows.size) == 0:
        raise StatisticsFirewallError("cannot measure an empty support")
    y0, y1 = int(rows.min()), int(rows.max()) + 1
    x0, x1 = int(columns.min()), int(columns.max()) + 1
    field_crop = np.asarray(contour_field[y0:y1, x0:x1], dtype=np.float64)
    support_crop = np.asarray(support[y0:y1, x0:x1], dtype=np.bool_)
    support_values = field_crop[support_crop]
    if bool(np.all(support_values == support_values[0])):
        return [0] * RADIAL_POWER_LENGTH
    crop_height, crop_width = support_crop.shape
    padded_height = crop_height + 2 * SPATIAL_PADDING_PIXELS
    padded_width = crop_width + 2 * SPATIAL_PADDING_PIXELS

    field_padded = np.zeros((padded_height, padded_width), dtype=np.float64)
    support_padded = np.zeros((padded_height, padded_width), dtype=np.bool_)
    inset = (
        slice(SPATIAL_PADDING_PIXELS, SPATIAL_PADDING_PIXELS + crop_height),
        slice(SPATIAL_PADDING_PIXELS, SPATIAL_PADDING_PIXELS + crop_width),
    )
    field_padded[inset] = field_crop
    support_padded[inset] = support_crop

    window_y = _symmetric_hann(padded_height, np)
    window_x = _symmetric_hann(padded_width, np)
    window = window_y[:, None] * window_x[None, :]
    support_window = window[support_padded]
    weight_total = math.fsum(float(value) for value in support_window)
    if not math.isfinite(weight_total) or weight_total <= 0.0:
        raise StatisticsFirewallError("support has zero or non-finite Hann weight")
    weighted_values = field_padded[support_padded] * support_window
    weighted_total = math.fsum(float(value) for value in weighted_values)
    dc_level = weighted_total / weight_total

    signal = np.zeros_like(field_padded)
    signal[support_padded] = (
        field_padded[support_padded] - dc_level
    ) * support_window
    spectrum = np.fft.rfft2(signal)
    power = np.square(spectrum.real) + np.square(spectrum.imag)

    hermitian = np.full(power.shape[1], 2.0, dtype=np.float64)
    hermitian[0] = 1.0
    if padded_width % 2 == 0:
        hermitian[-1] = 1.0
    power *= hermitian[None, :]
    power[0, 0] = 0.0

    fy = np.fft.fftfreq(padded_height)[:, None]
    fx = np.fft.rfftfreq(padded_width)[None, :]
    radius = np.hypot(fy, fx)
    radial_index = np.floor(
        RADIAL_POWER_LENGTH * radius / NYQUIST_RADIUS
    ).astype(np.int64)
    radial_index = np.minimum(radial_index, RADIAL_POWER_LENGTH - 1)
    bin_power = np.bincount(
        radial_index.reshape(-1),
        weights=power.reshape(-1),
        minlength=RADIAL_POWER_LENGTH,
    )[:RADIAL_POWER_LENGTH]
    total_power = math.fsum(float(value) for value in bin_power)
    if not math.isfinite(total_power) or total_power < 0.0:
        raise StatisticsFirewallError("radial power is non-finite or negative")
    if total_power == 0.0:
        return [0] * RADIAL_POWER_LENGTH
    return [
        _quantize_q16(float(value) / total_power, f"radial bin {index}")
        for index, value in enumerate(bin_power)
    ]


def _measure_body(
    contour_field: Any,
    lab_image: Any,
    support: Any,
    np: ModuleType,
) -> dict[str, Any]:
    if contour_field.ndim != 2 or support.ndim != 2:
        raise StatisticsFirewallError("contour_field and support must be 2-D")
    if lab_image.ndim != 3 or lab_image.shape[2] != 3:
        raise StatisticsFirewallError("Lab source must have exactly three channels")
    if contour_field.shape != support.shape or lab_image.shape[:2] != support.shape:
        raise StatisticsFirewallError("statistics source shapes do not match")
    sample_count = int(np.count_nonzero(support))
    if sample_count == 0:
        raise StatisticsFirewallError("cannot measure an empty support")

    field_samples = np.sort(
        np.asarray(contour_field[support], dtype=np.float64), kind="mergesort"
    )
    quantiles = [
        _quantize_q16(
            _type7_quantile(field_samples, numerator, QUANTILE_DENOMINATOR),
            f"contour quantile {numerator}/{QUANTILE_DENOMINATOR}",
        )
        for numerator in QUANTILE_NUMERATORS
    ]
    lab_medians: list[int] = []
    for channel in range(3):
        samples = np.sort(
            np.asarray(lab_image[..., channel][support], dtype=np.float64),
            kind="mergesort",
        )
        lab_medians.append(
            _quantize_q16(
                _type7_quantile(samples, 1, 2), f"Lab channel {channel} median"
            )
        )
    return {
        "median_lab_q16": lab_medians,
        "radial_power_q16": _radial_power_q16(contour_field, support, np),
        "quantiles_q16": quantiles,
    }


def _array_sha256(values: Any, np: ModuleType) -> str:
    return _sha256_bytes(np.ascontiguousarray(values).tobytes())


def measure_replay_arrays(
    contour_field: Any,
    final_rgb: Any,
    canonical_body_control: Any,
    cv2: ModuleType,
    np: ModuleType,
) -> dict[str, dict[str, Any]]:
    """Measure only the frozen v19 arrays; this function performs no I/O."""

    if not isinstance(contour_field, np.ndarray) or contour_field.dtype != np.float32:
        raise StatisticsFirewallError("v19 contour_field must be one float32 ndarray")
    if contour_field.ndim != 2:
        raise StatisticsFirewallError("v19 contour_field must be 2-D")
    if (
        not isinstance(final_rgb, np.ndarray)
        or final_rgb.dtype != np.uint8
        or final_rgb.ndim != 3
        or final_rgb.shape[2] != 3
    ):
        raise StatisticsFirewallError("v19 final replay must be one uint8 RGB ndarray")
    if (
        not isinstance(canonical_body_control, np.ndarray)
        or canonical_body_control.dtype != np.uint8
        or canonical_body_control.ndim != 2
    ):
        raise StatisticsFirewallError("canonical body control must be one uint8 plane")
    if final_rgb.shape[:2] != contour_field.shape or canonical_body_control.shape != (
        contour_field.shape
    ):
        raise StatisticsFirewallError("frozen replay array dimensions disagree")
    if _array_sha256(contour_field, np) != EXPECTED_V19_CONTOUR_FIELD_ARRAY_SHA256:
        raise StatisticsFirewallError("v19 contour_field array hash changed")
    if _array_sha256(final_rgb, np) != EXPECTED_V19_FINAL_PIXEL_ARRAY_SHA256:
        raise StatisticsFirewallError("v19 final pixel-array hash changed")

    lab_image = cv2.cvtColor(final_rgb, cv2.COLOR_RGB2LAB)
    if not isinstance(lab_image, np.ndarray) or lab_image.dtype != np.uint8:
        raise StatisticsFirewallError("OpenCV RGB-to-Lab conversion contract changed")
    bodies: dict[str, dict[str, Any]] = {}
    for control_value in BODY_CONTROL_VALUES:
        support = canonical_body_control == control_value
        support_digest = _array_sha256(support.astype(np.uint8), np)
        if support_digest != EXPECTED_SUPPORT_SHA256[control_value]:
            raise StatisticsFirewallError(
                f"body-control {control_value} support hash changed"
            )
        measured = _measure_body(contour_field, lab_image, support, np)
        bodies[str(control_value)] = {
            "support_sha256": support_digest,
            **measured,
        }
    return bodies


def assemble_statistics_record(
    source_hashes: Mapping[str, str],
    body_statistics: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    record = {
        "schema_id": SCHEMA_ID,
        "record_id": RECORD_ID,
        "source_hashes": dict(source_hashes),
        "body_statistics": {
            str(control_value): dict(body_statistics[str(control_value)])
            for control_value in BODY_CONTROL_VALUES
        },
    }
    return validate_statistics_record(record)


def _load_v19_renderer(renderer_path: Path) -> tuple[str, ModuleType]:
    module_name = "_sstory_golden_v3_v19_statistics_replay"
    if module_name in sys.modules:
        raise StatisticsFirewallError("private v19 replay module name is already occupied")
    spec = importlib.util.spec_from_file_location(module_name, renderer_path)
    if spec is None or spec.loader is None:
        raise StatisticsFirewallError("cannot construct the frozen v19 module spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module_name, module


def _verify_loaded_v19(module: ModuleType) -> None:
    required = {
        "INTERFACE": V19_INTERFACE,
        "SCHEMA_VERSION": V19_SCHEMA_VERSION,
        "EXPECTED_PIXEL_SHA256": EXPECTED_V19_FINAL_PIXEL_ARRAY_SHA256,
    }
    for name, expected in required.items():
        if getattr(module, name, None) != expected:
            raise StatisticsFirewallError(f"loaded v19 {name} changed")
    expected_intermediate = getattr(module, "EXPECTED_INTERMEDIATE_SHA256", None)
    if (
        not isinstance(expected_intermediate, dict)
        or expected_intermediate.get("field")
        != EXPECTED_V19_CONTOUR_FIELD_ARRAY_SHA256
    ):
        raise StatisticsFirewallError("loaded v19 field authority changed")
    if tuple(getattr(module, "BODY_VALUES", ())) != (*BODY_CONTROL_VALUES, 255):
        raise StatisticsFirewallError("loaded v19 body-control authority changed")
    if tuple(getattr(module, "EXPECTED_BODY_SHA256", ()))[:7] != tuple(
        EXPECTED_SUPPORT_SHA256[value] for value in BODY_CONTROL_VALUES
    ):
        raise StatisticsFirewallError("loaded v19 body support authority changed")
    for callable_name in ("load_replay_inputs", "reconstruct", "array_sha256"):
        if not callable(getattr(module, callable_name, None)):
            raise StatisticsFirewallError(f"loaded v19 lacks {callable_name}")


def _exclusive_create(path: Path, payload: bytes) -> None:
    destination = Path(path)
    parent = destination.parent
    if parent.is_symlink() or not parent.is_dir():
        raise StatisticsFirewallError(
            f"output parent must be an existing regular directory: {parent}"
        )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        descriptor = os.open(destination, flags, 0o644)
    except FileExistsError as exc:
        raise StatisticsFirewallError(
            f"refusing to overwrite statistics authority: {destination}"
        ) from exc
    except OSError as exc:
        raise StatisticsFirewallError(
            f"cannot exclusively create statistics authority: {exc}"
        ) from exc
    completed = False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        completed = True
    finally:
        if not completed:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass


def extract(
    replay_contract_path: Path,
    output_path: Path,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Run the frozen replay once and exclusively create its statistics JSON."""

    root = repository_root() if repo_root is None else Path(repo_root).resolve()
    contract_path = Path(replay_contract_path)
    output = Path(output_path)
    source_hashes = check_sources(root, contract_path)
    renderer_path = root / V19_RENDERER_RELATIVE_PATH
    resolved_output = output.resolve(strict=False)
    if resolved_output in {
        renderer_path.resolve(strict=True),
        contract_path.resolve(strict=True),
    }:
        raise StatisticsFirewallError("statistics output cannot replace a frozen source")

    module_name, v19 = _load_v19_renderer(renderer_path)
    try:
        _verify_loaded_v19(v19)
        inputs = v19.load_replay_inputs(contract_path)
        result = v19.reconstruct(inputs)
        np = v19.np
        if v19.array_sha256(result.contour_field) != (
            EXPECTED_V19_CONTOUR_FIELD_ARRAY_SHA256
        ):
            raise StatisticsFirewallError("replayed contour_field hash changed")
        if v19.array_sha256(result.candidate) != EXPECTED_V19_FINAL_PIXEL_ARRAY_SHA256:
            raise StatisticsFirewallError("replayed final pixel-array hash changed")
        bodies = measure_replay_arrays(
            result.contour_field,
            result.candidate,
            inputs.canonical_body_control,
            v19.cv2,
            np,
        )
        record = assemble_statistics_record(source_hashes, bodies)
        payload = canonical_statistics_json(record)
        _exclusive_create(output, payload)
        return record
    except StatisticsFirewallError:
        raise
    except Exception as exc:
        raise StatisticsFirewallError(f"frozen v19 extraction failed: {exc}") from exc
    finally:
        sys.modules.pop(module_name, None)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="validate frozen sources and schema without importing/running v19 (default)",
    )
    mode.add_argument(
        "--extract",
        action="store_true",
        help="explicitly run v19 and exclusively create the statistics authority",
    )
    parser.add_argument(
        "--replay-contract",
        type=Path,
        help="exact byte-frozen v19 replay contract (the tracked contract is default)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="new canonical JSON path; required with --extract and never overwritten",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    root = repository_root()
    contract = (
        root / V19_REPLAY_CONTRACT_RELATIVE_PATH
        if args.replay_contract is None
        else args.replay_contract
    )
    try:
        if args.extract:
            if args.output is None:
                parser.error("--extract requires --output")
            extract(contract, args.output, root)
            return 0
        if args.output is not None:
            parser.error("--output is valid only with explicit --extract")
        check_sources(root, contract)
        return 0
    except StatisticsFirewallError as exc:
        parser.exit(2, f"v19 statistics firewall failed closed: {exc}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
