"""Mean-variance optimisation using scipy.optimize.minimize as a QP solver."""
from __future__ import annotations

import base64
import io
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize


# Three small synthetic assets used when no file is uploaded — keeps the
# tool runnable end-to-end without an upload.
_DEMO_CSV = (
    "tech,banks,utilities\n"
    "0.012,0.004,0.002\n0.018,-0.002,0.001\n-0.005,0.006,0.003\n"
    "0.022,0.001,-0.001\n-0.015,0.008,0.002\n0.030,-0.010,0.000\n"
    "0.005,0.003,0.004\n-0.020,0.005,0.001\n0.025,0.000,0.002\n"
    "0.008,0.002,0.001\n0.014,-0.004,0.003\n-0.010,0.007,0.000\n"
    "0.018,0.001,0.002\n0.004,0.005,0.004\n-0.012,0.009,0.001\n"
    "0.020,-0.003,0.003\n0.011,0.002,0.002\n-0.008,0.004,0.001\n"
    "0.016,0.000,0.003\n0.009,0.006,0.002\n"
)


def _decode_csv(value: str | None) -> pd.DataFrame:
    if not value:
        return pd.read_csv(io.StringIO(_DEMO_CSV))
    raw: bytes
    if value.startswith("data:"):
        try:
            _, encoded = value.split(",", 1)
            raw = base64.b64decode(encoded)
        except (ValueError, base64.binascii.Error):
            return pd.read_csv(io.StringIO(_DEMO_CSV))
    else:
        try:
            raw = base64.b64decode(value)
        except (ValueError, base64.binascii.Error):
            raw = value.encode("utf-8")
    try:
        return pd.read_csv(io.BytesIO(raw))
    except Exception:
        return pd.read_csv(io.StringIO(_DEMO_CSV))


def _min_variance_target(mean: np.ndarray, cov: np.ndarray, target: float) -> np.ndarray:
    n = len(mean)
    x0 = np.full(n, 1.0 / n)
    bounds = [(0.0, 1.0)] * n
    constraints = [
        {"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)},
        {"type": "eq", "fun": lambda w: float(w @ mean - target)},
    ]
    res = minimize(
        lambda w: float(w @ cov @ w),
        x0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 200, "ftol": 1e-10},
    )
    return res.x


def _min_variance_global(mean: np.ndarray, cov: np.ndarray) -> np.ndarray:
    n = len(mean)
    x0 = np.full(n, 1.0 / n)
    bounds = [(0.0, 1.0)] * n
    constraints = [{"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}]
    res = minimize(
        lambda w: float(w @ cov @ w),
        x0, method="SLSQP", bounds=bounds, constraints=constraints,
        options={"maxiter": 200, "ftol": 1e-10},
    )
    return res.x


def _tangency(mean: np.ndarray, cov: np.ndarray, rf: float) -> np.ndarray:
    """Maximise Sharpe ratio (negative => minimise)."""

    n = len(mean)
    x0 = np.full(n, 1.0 / n)
    bounds = [(0.0, 1.0)] * n
    constraints = [{"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}]

    def negative_sharpe(w: np.ndarray) -> float:
        ret = float(w @ mean - rf)
        vol = float(np.sqrt(w @ cov @ w))
        if vol < 1e-12:
            return 0.0
        return -ret / vol

    res = minimize(
        negative_sharpe, x0, method="SLSQP",
        bounds=bounds, constraints=constraints,
        options={"maxiter": 300, "ftol": 1e-10},
    )
    return res.x


def optimise(returns_csv: str | None, risk_free_rate: float, periods_per_year: int, target_return: float) -> dict[str, Any]:
    df = _decode_csv(returns_csv)
    df = df.dropna(axis=1, how="all").dropna(how="any")
    if df.shape[1] < 2:
        df = pd.read_csv(io.StringIO(_DEMO_CSV))
    assets = list(df.columns)
    mean_period = df.mean().to_numpy()
    cov_period = df.cov().to_numpy()
    mean_annual = mean_period * periods_per_year
    cov_annual = cov_period * periods_per_year
    rf = risk_free_rate / 100.0

    # min-variance global
    w_minvar = _min_variance_global(mean_annual, cov_annual)
    # tangency
    w_tan = _tangency(mean_annual, cov_annual, rf)
    # target
    if target_return > 0:
        try:
            w_target = _min_variance_target(mean_annual, cov_annual, target_return / 100.0)
        except Exception:
            w_target = np.full_like(w_minvar, np.nan)
    else:
        w_target = np.full_like(w_minvar, np.nan)

    # efficient frontier: span 30 target returns
    r_min = float(mean_annual.min())
    r_max = float(mean_annual.max())
    targets = np.linspace(r_min, r_max, 30)
    front_x: list[float] = []
    front_y: list[float] = []
    for t in targets:
        try:
            w = _min_variance_target(mean_annual, cov_annual, float(t))
            vol = float(np.sqrt(w @ cov_annual @ w))
            front_x.append(round(vol * 100, 4))
            front_y.append(round(float(t) * 100, 4))
        except Exception:
            pass

    tan_ret = float(w_tan @ mean_annual)
    tan_vol = float(np.sqrt(w_tan @ cov_annual @ w_tan))
    tan_sharpe = (tan_ret - rf) / tan_vol if tan_vol > 1e-12 else 0.0

    return {
        "efficient_frontier": {
            "series": [
                {
                    "name": "Frontier",
                    "x": front_x,
                    "y": front_y,
                },
                {
                    "name": "Tangency",
                    "x": [round(tan_vol * 100, 4)],
                    "y": [round(tan_ret * 100, 4)],
                },
            ],
            "x_label": "Annual volatility (%)",
            "y_label": "Annual return (%)",
        },
        "tangency_weights": {
            "pairs": {a: round(float(w), 4) for a, w in zip(assets, w_tan, strict=True)},
        },
        "target_weights": {
            "pairs": {
                a: (round(float(w), 4) if not np.isnan(w) else 0.0)
                for a, w in zip(assets, w_target, strict=True)
            },
        },
        "summary": {
            "pairs": {
                "tangency annual return (%)": round(tan_ret * 100, 4),
                "tangency annual vol (%)": round(tan_vol * 100, 4),
                "tangency Sharpe": round(tan_sharpe, 4),
                "assets": len(assets),
                "observations": int(df.shape[0]),
            },
        },
        "weights_table": {
            "columns": [
                {"key": "asset", "label": "Asset", "type": "string"},
                {"key": "min_var", "label": "Min variance", "type": "number"},
                {"key": "tangency", "label": "Tangency", "type": "number"},
                {"key": "target", "label": "At target", "type": "number"},
            ],
            "rows": [
                {
                    "asset": a,
                    "min_var": round(float(w_minvar[i]), 4),
                    "tangency": round(float(w_tan[i]), 4),
                    "target": (round(float(w_target[i]), 4) if not np.isnan(w_target[i]) else 0.0),
                }
                for i, a in enumerate(assets)
            ],
            "downloadable": True,
        },
    }
