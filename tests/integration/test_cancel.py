"""Soft + hard cancel coverage.

DECISIONS s5: soft ``/cancel`` first, then hard kill after a 5s grace.
Wave 2 (Phase 6b integration agent) implements the assertions.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Wave 2: cancel integration coverage")
def test_soft_cancel_then_hard_kill() -> None:
    pass
