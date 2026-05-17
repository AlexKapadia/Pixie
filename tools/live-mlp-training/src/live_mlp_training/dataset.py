"""Dataset loader. Falls back to a synthetic 2-class problem when no
CSV is supplied so the streaming wiring can be exercised cleanly."""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import Tuple

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Dataset:
    features_train: np.ndarray
    labels_train: np.ndarray
    features_val: np.ndarray
    labels_val: np.ndarray
    n_classes: int
    n_features: int


def _demo_dataset(seed: int) -> Tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    n = 600
    x = rng.normal(0, 1, (n, 4))
    # non-linear-ish label: ((x0+x1) > 0) XOR (x2 > 0)
    y = ((x[:, 0] + x[:, 1] > 0) ^ (x[:, 2] > 0)).astype(np.int64)
    return x.astype(np.float32), y


def _decode_csv(value: str | None) -> bytes | None:
    if not value:
        return None
    if value.startswith("data:"):
        try:
            _, encoded = value.split(",", 1)
            return base64.b64decode(encoded)
        except (ValueError, base64.binascii.Error):
            return None
    try:
        return base64.b64decode(value)
    except (ValueError, base64.binascii.Error):
        return value.encode("utf-8")


def load(value: str | None, target_column: str, seed: int, val_fraction: float = 0.2) -> Dataset:
    rng = np.random.default_rng(seed)
    raw = _decode_csv(value)
    if raw is None:
        x, y = _demo_dataset(seed)
    else:
        try:
            df = pd.read_csv(io.BytesIO(raw))
        except Exception:
            x, y = _demo_dataset(seed)
        else:
            target = target_column if target_column in df.columns else df.columns[-1]
            y_series = df[target]
            features_df = df.drop(columns=[target])
            features_df = features_df.select_dtypes(include=[np.number]).dropna(axis=1, how="all")
            features_df = features_df.fillna(features_df.mean(numeric_only=True))
            if features_df.shape[1] == 0:
                x, y = _demo_dataset(seed)
            else:
                x = features_df.to_numpy(dtype=np.float32)
                # encode labels to ints
                _, y = np.unique(y_series.to_numpy(), return_inverse=True)
                y = y.astype(np.int64)

    # shuffle + split
    indices = np.arange(len(x))
    rng.shuffle(indices)
    x = x[indices]
    y = y[indices]
    cut = int(len(x) * (1 - val_fraction))
    x_train, x_val = x[:cut], x[cut:]
    y_train, y_val = y[:cut], y[cut:]
    # standardise on train stats
    mean = x_train.mean(axis=0, keepdims=True)
    std = x_train.std(axis=0, keepdims=True) + 1e-6
    x_train = ((x_train - mean) / std).astype(np.float32)
    x_val = ((x_val - mean) / std).astype(np.float32)
    return Dataset(
        features_train=x_train,
        labels_train=y_train,
        features_val=x_val,
        labels_val=y_val,
        n_classes=int(max(2, len(np.unique(y)))),
        n_features=x.shape[1],
    )
