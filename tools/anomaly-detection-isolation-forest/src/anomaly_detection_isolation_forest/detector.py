"""Isolation-forest anomaly detection on a univariate time series.

We enrich the raw value with two engineered features (rolling z-score and
first-difference) so the forest sees both magnitude and local shape changes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


@dataclass
class DetectionResult:
    values: np.ndarray
    timestamps: np.ndarray
    scores: np.ndarray
    anomalies: np.ndarray  # bool mask


def detect(
    df: pd.DataFrame,
    value_col: str,
    timestamp_col: str | None,
    contamination: float = 0.05,
    seed: int = 0,
) -> DetectionResult:
    if value_col not in df.columns:
        raise ValueError(f"value column {value_col!r} not in CSV")
    work = df.copy()
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce")
    work = work.dropna(subset=[value_col]).reset_index(drop=True)
    if work.empty:
        raise ValueError("No usable rows after coercing the value column.")

    values = work[value_col].to_numpy(dtype=float)
    if timestamp_col and timestamp_col in work.columns:
        timestamps = work[timestamp_col].astype(str).to_numpy()
    else:
        timestamps = np.array([str(i) for i in range(len(values))])

    window = max(min(20, len(values) // 10), 3)
    rolling = pd.Series(values).rolling(window=window, min_periods=1)
    z = (values - rolling.mean().to_numpy()) / np.maximum(rolling.std().fillna(1.0).to_numpy(), 1e-6)
    diff = np.diff(values, prepend=values[0])
    features = np.column_stack([values, z, diff])

    contamination = float(min(max(contamination, 1e-4), 0.5))
    model = IsolationForest(
        n_estimators=150,
        contamination=contamination,
        random_state=seed,
    )
    model.fit(features)
    predictions = model.predict(features)
    scores = -model.score_samples(features)
    anomalies = predictions == -1
    return DetectionResult(
        values=values, timestamps=timestamps,
        scores=scores, anomalies=anomalies,
    )
