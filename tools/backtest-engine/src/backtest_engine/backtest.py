"""MA-crossover backtest logic."""
from __future__ import annotations

import base64
import io
from typing import Any

import numpy as np
import pandas as pd


def _demo_dataset() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    n = 500
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    log_returns = rng.normal(0.0005, 0.015, n)
    close = 100 * np.exp(np.cumsum(log_returns))
    high = close * (1 + rng.uniform(0, 0.01, n))
    low = close * (1 - rng.uniform(0, 0.01, n))
    open_ = close * (1 + rng.normal(0, 0.003, n))
    return pd.DataFrame({"date": dates, "open": open_, "high": high, "low": low, "close": close})


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
    df.columns = [c.lower() for c in df.columns]
    if not {"date", "close"}.issubset(df.columns):
        return _demo_dataset()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    return df


def _max_drawdown(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    return float(dd.min())


def _annualised_sharpe(returns: np.ndarray) -> float:
    if returns.size < 2:
        return 0.0
    mu = returns.mean()
    sigma = returns.std(ddof=1)
    if sigma < 1e-12:
        return 0.0
    return float(mu / sigma * np.sqrt(252))


def backtest(ohlc_csv: str | None, fast_ma: int, slow_ma: int, initial_cash: float, commission_bps: float) -> dict[str, Any]:
    df = _decode_csv(ohlc_csv)
    if fast_ma >= slow_ma:
        fast_ma, slow_ma = min(fast_ma, slow_ma), max(fast_ma, slow_ma)
        if fast_ma == slow_ma:
            fast_ma = max(2, slow_ma - 1)

    close = df["close"].to_numpy(dtype=float)
    fast = pd.Series(close).rolling(fast_ma, min_periods=fast_ma).mean().to_numpy()
    slow = pd.Series(close).rolling(slow_ma, min_periods=slow_ma).mean().to_numpy()
    signal = np.where(fast > slow, 1, 0)
    signal[: slow_ma] = 0

    # Trade detection — long-only, all-in
    position = 0
    cash = float(initial_cash)
    shares = 0.0
    equity = np.full(len(close), cash, dtype=float)
    trades: list[dict[str, Any]] = []
    entry_price = 0.0
    entry_date = ""
    commission_rate = commission_bps / 10000.0
    dates = df["date"].dt.strftime("%Y-%m-%d").tolist()

    for i in range(len(close)):
        price = float(close[i])
        if position == 0 and signal[i] == 1:
            shares = cash / price * (1 - commission_rate)
            cash = 0.0
            position = 1
            entry_price = price
            entry_date = dates[i]
        elif position == 1 and signal[i] == 0:
            gross = shares * price
            cash = gross * (1 - commission_rate)
            pnl = cash - initial_cash if not trades else cash - (initial_cash + sum(t["pnl"] for t in trades))
            trades.append({
                "entry_date": entry_date,
                "exit_date": dates[i],
                "entry_price": round(entry_price, 4),
                "exit_price": round(price, 4),
                "pnl": round(float(pnl), 2),
                "return_pct": round((price / entry_price - 1.0) * 100.0, 4),
            })
            shares = 0.0
            position = 0
        equity[i] = cash + shares * price

    # buy-and-hold equity
    bh_shares = initial_cash / close[0]
    bh_equity = bh_shares * close

    # metrics
    returns = np.diff(equity) / equity[:-1]
    sharpe = _annualised_sharpe(returns)
    max_dd = _max_drawdown(equity) * 100.0
    total_return = (equity[-1] / initial_cash - 1.0) * 100.0
    bh_return = (bh_equity[-1] / initial_cash - 1.0) * 100.0
    winning = sum(1 for t in trades if t["pnl"] > 0)

    # downsample equity if very long
    step = max(1, len(close) // 250)
    sample_idx = list(range(0, len(close), step))
    chart_x = [dates[i] for i in sample_idx]
    strat_y = [round(float(equity[i]), 2) for i in sample_idx]
    bh_y = [round(float(bh_equity[i]), 2) for i in sample_idx]

    return {
        "equity_chart": {
            "x": chart_x,
            "series": [
                {"name": "Strategy", "y": strat_y},
                {"name": "Buy-and-hold", "y": bh_y},
            ],
            "x_label": "Date",
            "y_label": "Equity (£)",
        },
        "trades_table": {
            "columns": [
                {"key": "entry_date", "label": "Entry date", "type": "string"},
                {"key": "exit_date", "label": "Exit date", "type": "string"},
                {"key": "entry_price", "label": "Entry", "type": "number"},
                {"key": "exit_price", "label": "Exit", "type": "number"},
                {"key": "pnl", "label": "P&L (£)", "type": "number"},
                {"key": "return_pct", "label": "Return (%)", "type": "number"},
            ],
            "rows": trades,
            "downloadable": True,
        },
        "metrics": {
            "pairs": {
                "fast MA": int(fast_ma),
                "slow MA": int(slow_ma),
                "bars": int(len(close)),
                "trades": int(len(trades)),
                "winning trades": int(winning),
                "total return (%)": round(float(total_return), 4),
                "buy-and-hold return (%)": round(float(bh_return), 4),
                "max drawdown (%)": round(float(max_dd), 4),
                "annualised Sharpe": round(float(sharpe), 4),
                "final equity (£)": round(float(equity[-1]), 2),
            },
        },
    }
