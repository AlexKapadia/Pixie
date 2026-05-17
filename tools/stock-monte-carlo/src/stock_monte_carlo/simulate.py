"""GBM Monte Carlo simulation logic. Pure numpy, vectorised across paths."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class SimulationInputs:
    spot_price: float
    drift: float
    volatility: float
    days: int
    paths: int
    seed: int


def simulate(inputs: SimulationInputs) -> dict[str, Any]:
    """Run a GBM simulation and return Pixie-shaped output dict."""

    rng = np.random.default_rng(inputs.seed if inputs.seed > 0 else None)
    dt = 1.0 / TRADING_DAYS_PER_YEAR
    mu = inputs.drift / 100.0
    sigma = inputs.volatility / 100.0
    n_days = int(inputs.days)
    n_paths = int(inputs.paths)

    # log-return increments: shape (n_days, n_paths)
    shocks = rng.standard_normal((n_days, n_paths))
    drift_term = (mu - 0.5 * sigma * sigma) * dt
    diffusion_term = sigma * np.sqrt(dt) * shocks
    log_increments = drift_term + diffusion_term
    log_paths = np.cumsum(log_increments, axis=0)
    # prepend starting day-zero log(spot)
    log0 = np.log(inputs.spot_price)
    log_prices_full = np.vstack([np.full((1, n_paths), log0), log0 + log_paths])
    prices = np.exp(log_prices_full)

    # per-day percentiles
    p05 = np.percentile(prices, 5, axis=1)
    p50 = np.percentile(prices, 50, axis=1)
    p95 = np.percentile(prices, 95, axis=1)
    mean = prices.mean(axis=1)

    # sample paths — show up to 10 individual paths
    sample_count = min(10, n_paths)
    sample_indices = np.linspace(0, n_paths - 1, sample_count, dtype=int)
    sample_series = [
        {"name": f"Path {i + 1}", "y": [round(float(v), 4) for v in prices[:, idx]]}
        for i, idx in enumerate(sample_indices)
    ]
    band_series = [
        {"name": "Median", "y": [round(float(v), 4) for v in p50]},
        {"name": "5th pct", "y": [round(float(v), 4) for v in p05]},
        {"name": "95th pct", "y": [round(float(v), 4) for v in p95]},
    ]

    # VaR / CVaR on terminal P&L vs spot
    terminal = prices[-1]
    pnl = terminal - inputs.spot_price
    var_95 = float(-np.percentile(pnl, 5))
    cvar_95 = float(-pnl[pnl <= np.percentile(pnl, 5)].mean())

    # moments of terminal distribution
    moments = {
        "pairs": {
            "mean": round(float(terminal.mean()), 4),
            "std": round(float(terminal.std(ddof=1)), 4),
            "min": round(float(terminal.min()), 4),
            "max": round(float(terminal.max()), 4),
            "skew": round(float(_skew(terminal)), 4),
            "kurtosis": round(float(_kurtosis(terminal)), 4),
        },
    }

    # daily stats table — downsample if very long
    step = max(1, (n_days + 1) // 60)
    indices = list(range(0, n_days + 1, step))
    rows = [
        {
            "day": int(i),
            "p05": round(float(p05[i]), 4),
            "p50": round(float(p50[i]), 4),
            "p95": round(float(p95[i]), 4),
            "mean": round(float(mean[i]), 4),
        }
        for i in indices
    ]

    x_axis = list(range(n_days + 1))
    return {
        "var_95": round(var_95, 2),
        "cvar_95": round(cvar_95, 2),
        "price_paths": {
            "x": x_axis,
            "series": sample_series + band_series,
            "x_label": "Trading day",
            "y_label": "Price (£)",
        },
        "daily_stats": {
            "columns": [
                {"key": "day", "label": "Day", "type": "number"},
                {"key": "p05", "label": "5th pct", "type": "number"},
                {"key": "p50", "label": "Median", "type": "number"},
                {"key": "p95", "label": "95th pct", "type": "number"},
                {"key": "mean", "label": "Mean", "type": "number"},
            ],
            "rows": rows,
            "downloadable": True,
        },
        "moments": moments,
    }


def _skew(arr: np.ndarray) -> float:
    centred = arr - arr.mean()
    m3 = (centred ** 3).mean()
    m2 = (centred ** 2).mean()
    return m3 / (m2 ** 1.5) if m2 > 0 else 0.0


def _kurtosis(arr: np.ndarray) -> float:
    centred = arr - arr.mean()
    m4 = (centred ** 4).mean()
    m2 = (centred ** 2).mean()
    return m4 / (m2 ** 2) - 3.0 if m2 > 0 else 0.0
