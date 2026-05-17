"""Time-series forecasting using statsmodels."""
from __future__ import annotations

import base64
import io
import warnings
from typing import Any

import numpy as np
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX

warnings.filterwarnings("ignore")


# A small built-in dataset (synthetic with trend + weekly seasonality) so
# the tool always has something to forecast even before a file is uploaded.
def _demo_dataset() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=200, freq="D")
    rng = np.random.default_rng(0)
    trend = np.linspace(100, 140, 200)
    weekly = 6 * np.sin(2 * np.pi * np.arange(200) / 7)
    noise = rng.normal(0, 2.0, 200)
    values = trend + weekly + noise
    return pd.DataFrame({"date": dates, "value": values})


def _decode_csv(value: str | None) -> pd.DataFrame:
    if not value:
        return _demo_dataset()
    raw: bytes
    if value.startswith("data:"):
        try:
            _, encoded = value.split(",", 1)
            raw = base64.b64decode(encoded)
        except (ValueError, base64.binascii.Error):
            return _demo_dataset()
    else:
        try:
            raw = base64.b64decode(value)
        except (ValueError, base64.binascii.Error):
            raw = value.encode("utf-8")
    try:
        df = pd.read_csv(io.BytesIO(raw))
    except Exception:
        return _demo_dataset()
    cols = [c.lower() for c in df.columns]
    df.columns = cols
    if "date" not in cols or "value" not in cols:
        return _demo_dataset()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)
    return df[["date", "value"]]


def _seasonal_period(name: str) -> int:
    return {"weekly": 7, "monthly": 12, "yearly": 12}.get(name, 0)


def _fit_arima(values: np.ndarray) -> Any:
    return ARIMA(values, order=(1, 1, 1)).fit()


def _fit_sarima(values: np.ndarray, period: int) -> Any:
    s = max(2, period or 7)
    return SARIMAX(
        values, order=(1, 1, 1), seasonal_order=(1, 1, 1, s),
        enforce_stationarity=False, enforce_invertibility=False,
    ).fit(disp=False)


def _fit_ets(values: np.ndarray, period: int) -> Any:
    seasonal = "add" if period >= 2 else None
    return ExponentialSmoothing(
        values, trend="add", seasonal=seasonal,
        seasonal_periods=period if period >= 2 else None,
    ).fit()


def _auto_arima(values: np.ndarray) -> Any:
    best_aic = float("inf")
    best = None
    for p in (0, 1, 2):
        for q in (0, 1, 2):
            try:
                fit = ARIMA(values, order=(p, 1, q)).fit()
                if fit.aic < best_aic:
                    best_aic = fit.aic
                    best = fit
            except Exception:
                continue
    if best is None:
        return _fit_arima(values)
    return best


def _fit(values: np.ndarray, model: str, period: int) -> Any:
    if model == "arima":
        return _fit_arima(values)
    if model == "sarima":
        return _fit_sarima(values, period)
    if model == "ets":
        return _fit_ets(values, period)
    return _auto_arima(values)


def _forecast_with_band(fit: Any, horizon: int, confidence: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    alpha = 1.0 - confidence / 100.0
    try:
        res = fit.get_forecast(steps=horizon)
        mean = np.asarray(res.predicted_mean)
        ci = np.asarray(res.conf_int(alpha=alpha))
        lower = ci[:, 0]
        upper = ci[:, 1]
    except Exception:
        mean = np.asarray(fit.forecast(steps=horizon))
        # crude band from in-sample residual std
        try:
            sigma = float(np.std(np.asarray(fit.resid)))
        except Exception:
            sigma = 1.0
        z = 1.96 if confidence >= 95 else 1.645
        lower = mean - z * sigma
        upper = mean + z * sigma
    return mean, lower, upper


def _backtest(values: np.ndarray, model: str, period: int) -> dict[str, float]:
    if len(values) < 30:
        return {"mae": 0.0, "rmse": 0.0, "mape": 0.0}
    split = int(len(values) * 0.8)
    train = values[:split]
    test = values[split:]
    try:
        fit = _fit(train, model, period)
        pred = np.asarray(fit.forecast(steps=len(test)))
        err = pred - test
        mae = float(np.mean(np.abs(err)))
        rmse = float(np.sqrt(np.mean(err ** 2)))
        denom = np.where(np.abs(test) < 1e-9, 1.0, np.abs(test))
        mape = float(np.mean(np.abs(err) / denom) * 100.0)
        return {"mae": round(mae, 4), "rmse": round(rmse, 4), "mape": round(mape, 4)}
    except Exception:
        return {"mae": 0.0, "rmse": 0.0, "mape": 0.0}


def forecast(series_csv: str | None, horizon_days: int, model: str, seasonality: str, confidence: float) -> dict[str, Any]:
    df = _decode_csv(series_csv)
    values = df["value"].to_numpy(dtype=float)
    dates = df["date"]
    period = _seasonal_period(seasonality)

    fit = _fit(values, model, period)
    mean, lower, upper = _forecast_with_band(fit, horizon_days, confidence)

    last_date = pd.Timestamp(dates.iloc[-1])
    future_dates = pd.date_range(last_date + pd.Timedelta(days=1), periods=horizon_days, freq="D")

    # show last 90 history points to keep payload modest
    hist_tail = 90
    hist_x = [d.strftime("%Y-%m-%d") for d in dates.iloc[-hist_tail:]]
    hist_y = [round(float(v), 4) for v in values[-hist_tail:]]
    future_x = [d.strftime("%Y-%m-%d") for d in future_dates]

    chart_x = hist_x + future_x
    history_padded = hist_y + [None] * len(future_x)
    forecast_padded = [None] * len(hist_x) + [round(float(v), 4) for v in mean]
    lower_padded = [None] * len(hist_x) + [round(float(v), 4) for v in lower]
    upper_padded = [None] * len(hist_x) + [round(float(v), 4) for v in upper]

    metrics = _backtest(values, model, period)
    return {
        "forecast_chart": {
            "x": chart_x,
            "series": [
                {"name": "History", "y": history_padded},
                {"name": "Forecast", "y": forecast_padded},
                {"name": "Lower", "y": lower_padded},
                {"name": "Upper", "y": upper_padded},
            ],
            "x_label": "Date",
            "y_label": "Value",
        },
        "forecast_table": {
            "columns": [
                {"key": "date", "label": "Date", "type": "string"},
                {"key": "forecast", "label": "Forecast", "type": "number"},
                {"key": "lower", "label": "Lower", "type": "number"},
                {"key": "upper", "label": "Upper", "type": "number"},
            ],
            "rows": [
                {
                    "date": d,
                    "forecast": round(float(m), 4),
                    "lower": round(float(lo), 4),
                    "upper": round(float(up), 4),
                }
                for d, m, lo, up in zip(future_x, mean, lower, upper, strict=True)
            ],
            "downloadable": True,
        },
        "metrics": {
            "pairs": {
                "model": model,
                "MAE": metrics["mae"],
                "RMSE": metrics["rmse"],
                "MAPE (%)": metrics["mape"],
                "history points": int(len(values)),
                "forecast horizon": int(horizon_days),
            },
        },
    }
