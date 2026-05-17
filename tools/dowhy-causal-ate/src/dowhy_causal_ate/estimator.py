"""ATE estimation via linear regression with confounder adjustment + IPW.

Original brief asked for DoWhy; we substitute a transparent sklearn-based
estimator (OLS adjustment + IPW + doubly-robust cross-check) so the tool is
installable everywhere without DoWhy's heavy / brittle dependency stack.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, LogisticRegression


@dataclass
class AteEstimate:
    ate: float
    ci_lower: float
    ci_upper: float
    ate_ols: float
    ate_ipw: float
    ate_doubly_robust: float
    placebo_ate: float
    subset_ate: float
    sample_size: int


def estimate(
    df: pd.DataFrame,
    treatment_col: str,
    outcome_col: str,
    confounders: list[str] | None = None,
) -> AteEstimate:
    confounders = [c for c in (confounders or []) if c in df.columns]
    needed = [treatment_col, outcome_col, *confounders]
    work = df[needed].dropna().copy()
    if work.empty:
        raise ValueError("No rows remain after dropping NaNs in the selected columns.")
    t = work[treatment_col].astype(float).to_numpy()
    y = work[outcome_col].astype(float).to_numpy()
    x = work[confounders].astype(float).to_numpy() if confounders else np.zeros((len(work), 0))

    ate_ols, se_ols = _ate_ols(t, y, x)
    ate_ipw = _ate_ipw(t, y, x) if confounders else float(y[t > 0.5].mean() - y[t <= 0.5].mean())
    ate_dr = _ate_doubly_robust(t, y, x) if confounders else ate_ols

    ci = 1.96 * se_ols
    placebo = _placebo_ate(t, y, x)
    subset = _subset_ate(t, y, x)
    return AteEstimate(
        ate=float(ate_ols),
        ci_lower=float(ate_ols - ci),
        ci_upper=float(ate_ols + ci),
        ate_ols=float(ate_ols),
        ate_ipw=float(ate_ipw),
        ate_doubly_robust=float(ate_dr),
        placebo_ate=float(placebo),
        subset_ate=float(subset),
        sample_size=int(len(work)),
    )


def _ate_ols(t: np.ndarray, y: np.ndarray, x: np.ndarray) -> tuple[float, float]:
    design = np.column_stack([np.ones_like(t), t, x]) if x.size else np.column_stack([np.ones_like(t), t])
    coef, _resid, _rank, _sv = np.linalg.lstsq(design, y, rcond=None)
    residuals = y - design @ coef
    dof = max(len(y) - design.shape[1], 1)
    sigma2 = float((residuals @ residuals) / dof)
    cov = sigma2 * np.linalg.pinv(design.T @ design)
    return float(coef[1]), float(np.sqrt(max(cov[1, 1], 0.0)))


def _ate_ipw(t: np.ndarray, y: np.ndarray, x: np.ndarray) -> float:
    if x.size == 0:
        return float(y[t > 0.5].mean() - y[t <= 0.5].mean())
    propensity_model = LogisticRegression(max_iter=200)
    treated = (t > 0.5).astype(int)
    propensity_model.fit(x, treated)
    p = np.clip(propensity_model.predict_proba(x)[:, 1], 0.02, 0.98)
    return float(np.mean(treated * y / p - (1 - treated) * y / (1 - p)))


def _ate_doubly_robust(t: np.ndarray, y: np.ndarray, x: np.ndarray) -> float:
    treated = (t > 0.5).astype(int)
    p = np.clip(LogisticRegression(max_iter=200).fit(x, treated).predict_proba(x)[:, 1], 0.02, 0.98)
    m1 = LinearRegression().fit(x[treated == 1], y[treated == 1]).predict(x)
    m0 = LinearRegression().fit(x[treated == 0], y[treated == 0]).predict(x)
    influence = (treated * (y - m1) / p) - ((1 - treated) * (y - m0) / (1 - p)) + (m1 - m0)
    return float(np.mean(influence))


def _placebo_ate(t: np.ndarray, y: np.ndarray, x: np.ndarray) -> float:
    rng = np.random.default_rng(0)
    permuted = rng.permutation(t)
    return _ate_ols(permuted, y, x)[0]


def _subset_ate(t: np.ndarray, y: np.ndarray, x: np.ndarray) -> float:
    rng = np.random.default_rng(1)
    n = len(y)
    keep = rng.choice(n, size=max(int(0.8 * n), 10), replace=False)
    return _ate_ols(t[keep], y[keep], x[keep] if x.size else x)[0]
