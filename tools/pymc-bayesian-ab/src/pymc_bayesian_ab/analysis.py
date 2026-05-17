"""Beta-Binomial conjugate analysis (substituted for PyMC).

Closed-form posteriors with Monte Carlo to estimate P(variant > control) and
expected lift. Exact, fast, no PyMC dependency required.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import beta


@dataclass
class AbResult:
    control_alpha: float
    control_beta: float
    variant_alpha: float
    variant_beta: float
    control_mean: float
    variant_mean: float
    p_variant_better: float
    expected_lift: float
    grid: np.ndarray
    control_density: np.ndarray
    variant_density: np.ndarray
    rope_loss: float


def analyse(
    control_conv: int,
    control_total: int,
    variant_conv: int,
    variant_total: int,
    prior_strength: float = 2.0,
    samples: int = 200_000,
    seed: int = 0,
) -> AbResult:
    prior_a = max(1.0 + prior_strength / 2.0, 1.0)
    prior_b = max(1.0 + prior_strength / 2.0, 1.0)

    c_alpha = prior_a + control_conv
    c_beta = prior_b + (control_total - control_conv)
    v_alpha = prior_a + variant_conv
    v_beta = prior_b + (variant_total - variant_conv)

    rng = np.random.default_rng(seed)
    c_samples = rng.beta(c_alpha, c_beta, samples)
    v_samples = rng.beta(v_alpha, v_beta, samples)
    p_better = float(np.mean(v_samples > c_samples))
    expected_lift = float(np.mean((v_samples - c_samples) / np.clip(c_samples, 1e-9, None)))
    # ROPE: probability variant differs from control by < 1% absolute.
    rope_loss = float(np.mean(np.abs(v_samples - c_samples) < 0.01))

    grid_lo = float(min(beta.ppf(0.001, c_alpha, c_beta), beta.ppf(0.001, v_alpha, v_beta)))
    grid_hi = float(max(beta.ppf(0.999, c_alpha, c_beta), beta.ppf(0.999, v_alpha, v_beta)))
    grid = np.linspace(max(0.0, grid_lo), min(1.0, grid_hi), 400)
    c_density = beta.pdf(grid, c_alpha, c_beta)
    v_density = beta.pdf(grid, v_alpha, v_beta)

    return AbResult(
        control_alpha=c_alpha,
        control_beta=c_beta,
        variant_alpha=v_alpha,
        variant_beta=v_beta,
        control_mean=float(c_alpha / (c_alpha + c_beta)),
        variant_mean=float(v_alpha / (v_alpha + v_beta)),
        p_variant_better=p_better,
        expected_lift=expected_lift,
        grid=grid,
        control_density=c_density,
        variant_density=v_density,
        rope_loss=rope_loss,
    )
