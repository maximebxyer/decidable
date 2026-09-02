"""Content hashing, in one place so every digest in the project means the same thing."""

from __future__ import annotations

import hashlib


def digest(text: str) -> str:
    """The sha256 of some text, as hex.

    Used for artifact digests in a report and for the parts of a verifier's
    fingerprint that are too big to spell out.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
