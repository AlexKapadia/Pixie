"""VADER sentiment scoring and rolling-window aggregation."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_analyser = SentimentIntensityAnalyzer()


@dataclass
class SentimentSeries:
    timeline: pd.DataFrame  # columns: date, mean_compound (rolling)
    windows: pd.DataFrame   # one row per window day


def _score(text: str) -> float:
    if not isinstance(text, str) or not text.strip():
        return 0.0
    return float(_analyser.polarity_scores(text)["compound"])


def analyse(
    frame: pd.DataFrame,
    date_column: str,
    text_column: str,
    window_days: int,
) -> SentimentSeries:
    if date_column not in frame.columns:
        raise KeyError(f"date column {date_column!r} not in CSV")
    if text_column not in frame.columns:
        raise KeyError(f"text column {text_column!r} not in CSV")

    df = frame[[date_column, text_column]].copy()
    df.columns = ["date", "text"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    df["compound"] = df["text"].apply(_score)

    daily = df.groupby(df["date"].dt.normalize()).agg(
        n_messages=("text", "count"),
        mean_compound=("compound", "mean"),
        share_positive=("compound", lambda s: float((s > 0.05).mean())),
        share_negative=("compound", lambda s: float((s < -0.05).mean())),
    ).reset_index().rename(columns={"date": "window_start"})

    rolled = daily.set_index("window_start").rolling(f"{window_days}D")["mean_compound"].mean().reset_index()
    rolled.columns = ["window_start", "mean_compound"]
    return SentimentSeries(timeline=rolled, windows=daily)
