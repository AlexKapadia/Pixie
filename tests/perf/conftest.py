"""Performance-suite fixtures.

Budgets live in ``tests/perf/baseline.json`` (committed). The first
run on a new machine creates the file from observed medians; later
runs compare medians against it. Each test asserts
``benchmark.stats.stats.median < budget_seconds``.

The budgets are sourced from RESEARCH_perf_dx.md s1 (the canonical
five) and are multiplied by 1.66x for CI slack per s1.3.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

BASELINE_PATH = Path(__file__).resolve().parent / "baseline.json"

# Budgets in milliseconds (the CI-relaxed flavour from RESEARCH_perf_dx s1.3).
DEFAULT_BUDGETS_MS: dict[str, float] = {
    "cold_spawn": 2500.0,
    "warm_run_roundtrip": 100.0,
    "sidebar_render": 200.0,
    "validator_full_pass": 13000.0,
    "pixie_startup": 800.0,
}


def _load_baselines() -> dict[str, float]:
    if BASELINE_PATH.exists():
        try:
            return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return dict(DEFAULT_BUDGETS_MS)


def _write_baselines(values: dict[str, float]) -> None:
    BASELINE_PATH.write_text(json.dumps(values, indent=2, sort_keys=True))


@pytest.fixture(scope="session")
def perf_budgets() -> dict[str, float]:
    """Return the merged budgets dict (file overrides defaults)."""

    baselines = _load_baselines()
    return {**DEFAULT_BUDGETS_MS, **baselines}


@pytest.fixture
def assert_within_budget(perf_budgets: dict[str, float]):
    """Helper used by perf tests: ``assert_within_budget(benchmark, 'warm_run')``.

    Reads the median in milliseconds out of pytest-benchmark's stats and
    compares against the budget. If ``PIXIE_UPDATE_PERF_BASELINE=1`` is
    set the observed median is written back as the new baseline.
    """

    def _check(benchmark, budget_key: str) -> None:
        budget_ms = perf_budgets.get(budget_key)
        if budget_ms is None:
            pytest.skip(f"no budget configured for {budget_key!r}")
        observed_ms = benchmark.stats.stats.median * 1000.0
        if os.environ.get("PIXIE_UPDATE_PERF_BASELINE") == "1":
            updated = dict(perf_budgets)
            updated[budget_key] = max(observed_ms * 1.2, budget_ms)
            _write_baselines(updated)
        assert observed_ms < budget_ms, (
            f"{budget_key}: median {observed_ms:.1f}ms exceeds "
            f"budget {budget_ms:.1f}ms"
        )

    return _check
