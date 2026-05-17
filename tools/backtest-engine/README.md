# Backtest Engine

Long-only moving-average crossover backtest with per-trade log, equity curve vs buy-and-hold, and headline risk metrics (Sharpe, max drawdown, total return).

## Install

```bash
uv sync
```

## Run standalone

```bash
uv run python main.py --port 8000
```

## Inputs

| Key | Type | Default |
|---|---|---|
| ohlc_csv | file (.csv) | demo |
| fast_ma | number | 20 |
| slow_ma | number | 50 |
| initial_cash | number (£) | 100000 |
| commission_bps | slider | 5 |

CSV columns expected (case-insensitive): `date`, `open`, `high`, `low`, `close`. Only `date` and `close` are required.

## Outputs

| Key | Type |
|---|---|
| equity_chart | chart_line |
| trades_table | table |
| metrics | kv |

## External services / API keys

None.

## Expected validator result

`overall == "pass"` on `uv run pixie validate backtest-engine --json`.
