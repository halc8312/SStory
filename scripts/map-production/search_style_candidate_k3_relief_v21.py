#!/usr/bin/env python3
"""Finite authoring search for v21 relief salts and body-noise frames.

This never emits a candidate. It evaluates a fixed, ordered candidate set and
prints the first diagnostics-clean choice for every frozen body. The printed
JSON is intended to be reviewed and frozen as a control before replay.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

import render_style_candidate_k3_overhead_relief_v21 as renderer


SCHEMA_VERSION = "1.0.0"
INTERFACE = "sstory-k3-v21-relief-finite-search-v1"
SALT_OFFSETS = (0, 37, 79, 131, 197, 269, 353, 449, 557, 677, 809, 953)
BASE_SALTS = (101, 211, 307, 401, 503, 601, 701, 809)
FRAME_CATALOG = (
    ("frame-00", [0.974370064785, 0.224951054344], [-0.224951054344, 0.974370064785], 1.0),
    ("frame-01", [0.857167300702, -0.51503807491], [0.51503807491, 0.857167300702], 1.08),
    ("frame-02", [0.681998360062, 0.731353701619], [-0.731353701619, 0.681998360062], 0.94),
    ("frame-03", [0.978147600734, -0.207911690818], [0.207911690818, 0.978147600734], 1.12),
    ("frame-04", [0.874619707139, 0.484809620246], [-0.484809620246, 0.874619707139], 0.97),
    ("frame-05", [0.731353701619, -0.681998360062], [0.681998360062, 0.731353701619], 1.06),
    ("frame-06", [0.994521895368, 0.104528463268], [-0.104528463268, 0.994521895368], 0.91),
    ("frame-07", [0.529919264233, 0.848048096156], [-0.848048096156, 0.529919264233], 1.1),
)
CRITERIA = {
    "closed_crater_count_max": 0,
    "partial_dark_arc_count_max": 0,
    "near_vertical_residual_count_max": 0,
    "near_vertical_severe_count_max": 0,
    "relief_orientation_coherence_max": 0.4,
    "maximum_relative_jacobian_norm_max": 0.35,
    "minimum_mapping_determinant_min": 0.5,
    "maximum_mapping_determinant_max": 1.75,
}


def _passes(volume: dict[str, Any]) -> bool:
    topology = volume["topology"]
    warp = volume["domain_warp"]
    return (
        topology["closed_crater_count"]
        <= CRITERIA["closed_crater_count_max"]
        and topology["partial_dark_arc_count"]
        <= CRITERIA["partial_dark_arc_count_max"]
        and topology["near_vertical_residual_count"]
        <= CRITERIA["near_vertical_residual_count_max"]
        and topology["near_vertical_severe_count"]
        <= CRITERIA["near_vertical_severe_count_max"]
        and topology["relief_orientation_coherence"]
        <= CRITERIA["relief_orientation_coherence_max"]
        and warp["maximum_relative_jacobian_norm"]
        <= CRITERIA["maximum_relative_jacobian_norm_max"]
        and warp["minimum_mapping_determinant"]
        >= CRITERIA["minimum_mapping_determinant_min"]
        and warp["maximum_mapping_determinant"]
        <= CRITERIA["maximum_mapping_determinant_max"]
    )


def main() -> int:
    inputs = renderer.load_replay_inputs(
        Path(renderer.REPLAY_CONTRACT_PATH),
        expected_contract_sha256=renderer.REPLAY_CONTRACT_SHA256,
    )
    renderer._validate_marks(inputs.marks)
    body_masks, _, _ = renderer._decode_components(inputs.v20_body_control)
    systems = inputs.marks["systems"]
    styles = inputs.marks["styles"]
    frame_catalog = [
        {
            "frame_id": frame_id,
            "noise_major_xy": major,
            "noise_minor_xy": minor,
            "noise_aspect": aspect,
        }
        for frame_id, major, minor, aspect in FRAME_CATALOG
    ]
    lab = np.zeros(renderer.SHAPE, dtype=np.float32)
    body_results: list[dict[str, Any]] = []
    for body_index, (source_system, body) in enumerate(
        zip(systems, body_masks, strict=True)
    ):
        base_salt = BASE_SALTS[body_index]
        frame_order = tuple(
            (body_index + offset) % len(frame_catalog)
            for offset in range(len(frame_catalog))
        )
        evaluated: list[dict[str, Any]] = []
        selected: dict[str, Any] | None = None
        for salt_offset_index, salt_offset in enumerate(SALT_OFFSETS):
            salt = base_salt + salt_offset
            for frame_order_index, frame_index in enumerate(frame_order):
                frame = frame_catalog[frame_index]
                system = copy.deepcopy(source_system)
                system["noise_salt"] = salt
                system["noise_major_xy"] = frame["noise_major_xy"]
                system["noise_minor_xy"] = frame["noise_minor_xy"]
                system["noise_aspect"] = frame["noise_aspect"]
                volume = dict(
                    renderer._apply_volume_relief(lab, body, system, styles)
                )
                lab[body] = 0.0
                record = {
                    "salt_offset_index": salt_offset_index,
                    "salt_offset": salt_offset,
                    "salt": salt,
                    "frame_order_index": frame_order_index,
                    "frame_id": frame["frame_id"],
                    "topology": volume["topology"],
                    "domain_warp": volume["domain_warp"],
                    "relief_minimum_l": volume["relief_minimum_l"],
                    "relief_maximum_l": volume["relief_maximum_l"],
                }
                record["passes"] = _passes(volume)
                evaluated.append(record)
                if record["passes"]:
                    selected = record
                    break
            if selected is not None:
                break
        if selected is None:
            raise renderer.V20ReplayError(
                f"finite v21 search exhausted for {source_system['body_id']}"
            )
        body_results.append(
            {
                "body_id": source_system["body_id"],
                "base_salt": base_salt,
                "frame_order": [frame_catalog[index]["frame_id"] for index in frame_order],
                "evaluated": evaluated,
                "selected": {
                    "salt": selected["salt"],
                    "frame_id": selected["frame_id"],
                    "noise_major_xy": frame_catalog[
                        int(selected["frame_id"].split("-")[1])
                    ]["noise_major_xy"],
                    "noise_minor_xy": frame_catalog[
                        int(selected["frame_id"].split("-")[1])
                    ]["noise_minor_xy"],
                    "noise_aspect": frame_catalog[
                        int(selected["frame_id"].split("-")[1])
                    ]["noise_aspect"],
                },
            }
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "interface": INTERFACE,
        "selection_rule": "first passing candidate in salt_offset then cyclic frame order",
        "base_salts": list(BASE_SALTS),
        "salt_offsets": list(SALT_OFFSETS),
        "criteria": CRITERIA,
        "frame_catalog": frame_catalog,
        "bodies": body_results,
    }
    print(json.dumps(payload, sort_keys=True, indent=2, separators=(",", ": ")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
