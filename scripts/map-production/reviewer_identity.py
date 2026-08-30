#!/usr/bin/env python3
"""Canonical reviewer identities shared by every release gate."""

from __future__ import annotations

import unicodedata


INDEPENDENT_VISION_REVIEW_ROLES = (
    "independent-vision-review-a",
    "independent-vision-review-b",
)


def canonical_reviewer_identity(value: str) -> str:
    """Return the comparison key for a reviewer identity.

    NFKC prevents compatibility-spelling aliases, ``split``/``join`` collapses
    every Unicode whitespace run, and case-folding supplies caseless matching.
    Empty identities are rejected so callers cannot accidentally count them.
    """

    if not isinstance(value, str):
        raise ValueError("reviewer identity must be a string")
    canonical = " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
    if not canonical:
        raise ValueError("reviewer identity must be non-empty")
    return canonical
