"""Canonical JSON serialization for evidence records.

The same logical record must always produce the same bytes, whatever the key order or
whitespace of the original log line, so its keccak256 digest is stable.

Canonical form
--------------
* object keys sorted (Python ``sort_keys``: Unicode code-point order)
* no insignificant whitespace (separators ``,`` and ``:``)
* UTF-8 output; non-ASCII characters are emitted literally (no ``\\uXXXX`` escapes)
* NaN / Infinity are rejected (they are not JSON)
* duplicate object keys are rejected on input (different parsers would disagree on them)

Canonicalization operates on the *parsed* value: number spellings that parse to the same
Python value (``1.10`` and ``1.1``) canonicalize identically, while ``1`` (int) and ``1.0``
(float) do not. This is not RFC 8785 (JCS); it is stable for this codebase's Python
implementation. The raw log files are additionally fingerprinted in ``session_index.json``.
"""

from __future__ import annotations

import json
from typing import Any, List, Tuple, Union


class CanonicalizationError(ValueError):
    """A value cannot be canonicalized (invalid or ambiguous JSON)."""


def _reject_duplicates(pairs: List[Tuple[str, Any]]) -> dict:
    obj: dict = {}
    for key, value in pairs:
        if key in obj:
            raise CanonicalizationError(f"duplicate JSON object key: {key!r}")
        obj[key] = value
    return obj


def _reject_constant(name: str) -> Any:
    raise CanonicalizationError(f"non-finite number not allowed in evidence JSON: {name}")


def parse_json_strict(text: Union[str, bytes]) -> Any:
    """Parse JSON, rejecting duplicate keys and NaN/Infinity."""
    if isinstance(text, (bytes, bytearray)):
        try:
            text = bytes(text).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CanonicalizationError(f"JSON text is not valid UTF-8: {exc}") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise CanonicalizationError(f"invalid JSON: {exc}") from exc


def canonical_json(obj: Any) -> str:
    """Return the canonical JSON text of ``obj``."""
    try:
        return json.dumps(
            obj,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        # ValueError: out-of-range float (e.g. 1e400 parsed to inf); TypeError: non-JSON type.
        raise CanonicalizationError(f"value cannot be canonicalized: {exc}") from exc


def canonical_bytes(obj: Any) -> bytes:
    """Return the canonical UTF-8 bytes of ``obj``; these are the bytes that get hashed."""
    text = canonical_json(obj)
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonicalizationError(
            f"string contains characters that cannot be encoded as UTF-8 (unpaired surrogate?): {exc}"
        ) from exc


def canonicalize_text(text: Union[str, bytes]) -> bytes:
    """Parse JSON text strictly and return its canonical bytes."""
    return canonical_bytes(parse_json_strict(text))
