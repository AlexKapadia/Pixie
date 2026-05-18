"""Fixtures local to the cross-platform smoke suite.

The suite never touches the real OS-specific call surface: every
subprocess / signal / file-system divergent helper is mocked. The
fixtures here only exist to keep the per-test boilerplate small.
"""

from __future__ import annotations

import sys
from typing import Iterator

import pytest


@pytest.fixture
def fake_platform(monkeypatch: pytest.MonkeyPatch) -> Iterator[callable]:
    """Return a ``set(platform)`` callable that monkeypatches ``sys.platform``.

    Usage::

        def test_x(fake_platform):
            fake_platform("win32")
            ...
    """

    def setter(value: str) -> None:
        monkeypatch.setattr(sys, "platform", value, raising=False)

    yield setter
