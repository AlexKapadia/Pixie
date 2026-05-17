# Black–Scholes Greeks

European option pricer using the closed-form Black-Scholes formula. Returns the price, all five first-order Greeks (delta, gamma, theta, vega, rho), price-vs-spot, price-vs-days, and a price heatmap across strike × time.

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
| spot | number (£) | 100 |
| strike | number (£) | 100 |
| days_to_expiry | number | 30 |
| rate | slider (%) | 4 |
| volatility | slider (%) | 20 |
| option_type | select | call |

## Outputs

| Key | Type |
|---|---|
| price | number (currency) |
| greeks | kv |
| price_vs_spot | chart_line |
| price_vs_days | chart_line |
| heatmap | chart_heatmap |

## External services / API keys

None.

## Expected validator result

`overall == "pass"` on `uv run pixie validate black-scholes-greeks --json`.
