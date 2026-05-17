# Stock Monte Carlo

Geometric Brownian motion simulation of a single underlying. Produces percentile bands, VaR/CVaR at 95% and the terminal distribution moments.

## Install

```bash
uv sync
```

## Run standalone

```bash
uv run python main.py --port 8000
```

`curl http://127.0.0.1:8000/healthz` should return `{"ok":true}`.

## Inputs

| Key | Type | Default |
|---|---|---|
| spot_price | number (£) | 100 |
| drift | slider (%) | 8 |
| volatility | slider (%) | 25 |
| days | number | 252 |
| paths | number | 5000 |
| seed | number | 42 |

## Outputs

| Key | Type |
|---|---|
| var_95 | number (currency) |
| cvar_95 | number (currency) |
| price_paths | chart_line (paths + median + 5/95 bands) |
| daily_stats | table |
| moments | kv |

## External services / API keys

None.

## Expected validator result

`overall == "pass"` on `uv run pixie validate stock-monte-carlo --json`. Reference fixture uses seed 42 with generous tolerance because Monte Carlo output still depends on the numpy BitGenerator version.
