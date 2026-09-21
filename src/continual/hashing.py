"""Deterministic content hashing — the basis of episode identity."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> bytes:
    """Deterministic JSON bytes: sorted keys, no whitespace, UTF-8."""
    # sort_keys makes dict ordering irrelevant; lists stay ordered because span
    # order within an episode is meaningful. separators drops incidental
    # whitespace. ensure_ascii=False + explicit UTF-8 keeps non-ASCII stable
    # across platforms.
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def content_hash(obj: Any) -> str:
    """SHA-256 of the canonical serialization, as lowercase hex."""
    return hashlib.sha256(canonical_json(obj)).hexdigest()
