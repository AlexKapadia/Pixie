"""Survival analysis using lifelines."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from lifelines import CoxPHFitter, KaplanMeierFitter


@dataclass
class StratumCurve:
    label: str
    timeline: list[float]
    survival: list[float]
    median: float | None
    size: int
    events: int


def kaplan_meier(
    df: pd.DataFrame,
    time_col: str,
    event_col: str,
    strata_col: str | None = None,
) -> list[StratumCurve]:
    work = df[[time_col, event_col] + ([strata_col] if strata_col else [])].dropna().copy()
    if strata_col and strata_col in work.columns:
        groups = list(work.groupby(strata_col, sort=True))
    else:
        groups = [("all", work)]

    out: list[StratumCurve] = []
    fitter = KaplanMeierFitter()
    for label, group in groups:
        if group.empty:
            continue
        fitter.fit(group[time_col].astype(float), group[event_col].astype(float), label=str(label))
        surv = fitter.survival_function_
        timeline = surv.index.tolist()
        values = surv.iloc[:, 0].tolist()
        median = fitter.median_survival_time_
        if isinstance(median, float) and (np.isnan(median) or np.isinf(median)):
            median = None
        out.append(StratumCurve(
            label=str(label),
            timeline=[float(t) for t in timeline],
            survival=[float(v) for v in values],
            median=float(median) if median is not None else None,
            size=int(len(group)),
            events=int(group[event_col].sum()),
        ))
    return out


def cox_hazards(
    df: pd.DataFrame,
    time_col: str,
    event_col: str,
    covariates: list[str],
) -> dict[str, Any]:
    if not covariates:
        return {}
    cols = [time_col, event_col, *covariates]
    work = df[cols].dropna().copy()
    if work.empty or len(covariates) == 0:
        return {}
    fitter = CoxPHFitter(penalizer=0.001)
    fitter.fit(work, duration_col=time_col, event_col=event_col)
    summary = fitter.summary
    out: dict[str, Any] = {}
    for name, row in summary.iterrows():
        out[str(name)] = {
            "hr": round(float(row["exp(coef)"]), 4),
            "hr_lower_95": round(float(row["exp(coef) lower 95%"]), 4),
            "hr_upper_95": round(float(row["exp(coef) upper 95%"]), 4),
            "p_value": round(float(row["p"]), 5),
        }
    return out
