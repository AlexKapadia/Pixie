"""Validator full-pass budget against the example tool (13s CI, 8s local).

Wave 2 fills the benchmark once the validator can be exercised without
spawning a real subprocess (or accepts a synthetic spawn helper).
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Wave 2: validator perf benchmark")
def test_validator_full_pass_budget() -> None:
    pass
