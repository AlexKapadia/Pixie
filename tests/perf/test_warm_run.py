"""Warm-path /run round-trip budget (100 ms on CI, 50 ms on user laptops).

Wave 2 (Phase 6f perf agent) wires the actual benchmark once the
sample-tool helper can return a kept-warm launcher across rounds.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Wave 2: warm-run benchmark wiring")
def test_warm_run_budget() -> None:
    pass
