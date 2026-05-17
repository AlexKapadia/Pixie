"""Closed-form Black-Scholes pricing + first-order Greeks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.stats import norm


@dataclass(frozen=True)
class OptionInputs:
    spot: float
    strike: float
    days_to_expiry: int
    rate: float
    volatility: float
    option_type: str  # "call" or "put"


def _d1_d2(spot: float, strike: float, t: float, r: float, sigma: float) -> tuple[float, float]:
    if t <= 0 or sigma <= 0:
        # degenerate, return inf-like values that the caller handles
        return float("nan"), float("nan")
    d1 = (np.log(spot / strike) + (r + 0.5 * sigma * sigma) * t) / (sigma * np.sqrt(t))
    d2 = d1 - sigma * np.sqrt(t)
    return d1, d2


def price(option: OptionInputs) -> float:
    """European option price."""

    t = option.days_to_expiry / 365.0
    r = option.rate / 100.0
    sigma = option.volatility / 100.0
    if t <= 0:
        # immediately expiring
        if option.option_type == "call":
            return max(option.spot - option.strike, 0.0)
        return max(option.strike - option.spot, 0.0)
    d1, d2 = _d1_d2(option.spot, option.strike, t, r, sigma)
    if option.option_type == "call":
        return float(option.spot * norm.cdf(d1) - option.strike * np.exp(-r * t) * norm.cdf(d2))
    return float(option.strike * np.exp(-r * t) * norm.cdf(-d2) - option.spot * norm.cdf(-d1))


def greeks(option: OptionInputs) -> dict[str, float]:
    t = option.days_to_expiry / 365.0
    r = option.rate / 100.0
    sigma = option.volatility / 100.0
    if t <= 0 or sigma <= 0:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    d1, d2 = _d1_d2(option.spot, option.strike, t, r, sigma)
    pdf_d1 = norm.pdf(d1)
    sqrt_t = np.sqrt(t)
    gamma_val = pdf_d1 / (option.spot * sigma * sqrt_t)
    vega_val = option.spot * pdf_d1 * sqrt_t / 100.0
    if option.option_type == "call":
        delta_val = norm.cdf(d1)
        theta_val = (
            -(option.spot * pdf_d1 * sigma) / (2 * sqrt_t)
            - r * option.strike * np.exp(-r * t) * norm.cdf(d2)
        ) / 365.0
        rho_val = option.strike * t * np.exp(-r * t) * norm.cdf(d2) / 100.0
    else:
        delta_val = norm.cdf(d1) - 1.0
        theta_val = (
            -(option.spot * pdf_d1 * sigma) / (2 * sqrt_t)
            + r * option.strike * np.exp(-r * t) * norm.cdf(-d2)
        ) / 365.0
        rho_val = -option.strike * t * np.exp(-r * t) * norm.cdf(-d2) / 100.0
    return {
        "delta": float(delta_val),
        "gamma": float(gamma_val),
        "theta": float(theta_val),
        "vega": float(vega_val),
        "rho": float(rho_val),
    }


def build_response(option: OptionInputs) -> dict[str, Any]:
    p = price(option)
    g = greeks(option)

    # price vs spot
    spot_range = np.linspace(max(0.5, option.spot * 0.5), option.spot * 1.5, 41)
    price_spot = [price(OptionInputs(**{**option.__dict__, "spot": float(s)})) for s in spot_range]

    # price vs days
    days_range = np.linspace(1, max(2, option.days_to_expiry * 2), 41).astype(int)
    price_days = [price(OptionInputs(**{**option.__dict__, "days_to_expiry": int(d)})) for d in days_range]

    # heatmap
    strikes = np.linspace(option.spot * 0.6, option.spot * 1.4, 25)
    times = np.linspace(7, max(30, option.days_to_expiry * 1.5), 25).astype(int)
    matrix = []
    for d in times:
        row = []
        for k in strikes:
            row.append(round(price(OptionInputs(**{**option.__dict__, "strike": float(k), "days_to_expiry": int(d)})), 4))
        matrix.append(row)

    return {
        "price": round(p, 4),
        "greeks": {
            "pairs": {
                "delta": round(g["delta"], 6),
                "gamma": round(g["gamma"], 6),
                "theta (per day)": round(g["theta"], 6),
                "vega (per 1% vol)": round(g["vega"], 6),
                "rho (per 1% rate)": round(g["rho"], 6),
            },
        },
        "price_vs_spot": {
            "x": [round(float(s), 2) for s in spot_range],
            "series": [{"name": f"{option.option_type.title()} price", "y": [round(v, 4) for v in price_spot]}],
            "x_label": "Spot (£)",
            "y_label": "Price (£)",
        },
        "price_vs_days": {
            "x": [int(d) for d in days_range],
            "series": [{"name": f"{option.option_type.title()} price", "y": [round(v, 4) for v in price_days]}],
            "x_label": "Days to expiry",
            "y_label": "Price (£)",
        },
        "heatmap": {
            "x": [round(float(k), 2) for k in strikes],
            "y": [int(d) for d in times],
            "z": matrix,
            "x_label": "Strike (£)",
            "y_label": "Days to expiry",
        },
    }
