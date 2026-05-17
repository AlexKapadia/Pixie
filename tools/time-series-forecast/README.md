# Time Series Forecast

Univariate forecast with ARIMA, SARIMA, Holt-Winters (ETS) or an auto-ARIMA grid search. Includes a backtest with MAE / RMSE / MAPE and a confidence band on the forward forecast.

## Install

```bash
uv sync
```

Optionally enable Facebook Prophet support:

```bash
uv sync --group prophet
```

Prophet is intentionally off the default install because its wheel is heavy and brittle on Windows.

## Run standalone

```bash
uv run python main.py --port 8000
```

A 200-point synthetic demo series is used whenever the user does not upload a CSV.

## Inputs

| Key | Type | Default |
|---|---|---|
| series_csv | file (.csv) | demo |
| horizon_days | number | 30 |
| model | select | auto_arima |
| seasonality | select | none |
| confidence | slider (%) | 95 |

## Outputs

| Key | Type |
|---|---|
| forecast_chart | chart_line |
| forecast_table | table |
| metrics | kv |

## External services / API keys

None.

## Expected validator result

`overall == "pass"` on `uv run pixie validate time-series-forecast --json`. Reference fixture forecasts the built-in demo series with auto-ARIMA and asserts the MAE is bounded.
