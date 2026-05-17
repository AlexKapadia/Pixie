"""Pixie error hierarchy.

Every custom exception raised by Pixie modules inherits from
``PixieError`` so route handlers can surface them via the standard
error envelope (``{"error": {"code": ..., "message": ..., "hint": ...}}``)
without leaking arbitrary stack traces.
"""

from __future__ import annotations


class PixieError(Exception):
    """Base class for every Pixie-raised exception."""

    code: str = "pixie_error"
    hint: str | None = None

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        if hint is not None:
            self.hint = hint
