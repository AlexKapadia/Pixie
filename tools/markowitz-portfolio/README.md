# Markowitz Portfolio

Mean-variance efficient frontier and tangency portfolio from a CSV of historical asset returns.

## Install

```bash
uv sync
```

## Run standalone

```bash
uv run python main.py --port 8000
```

When no CSV is uploaded the tool falls back to a small built-in three-asset demo set so the front-end always renders.

## Inputs

| Key | Type | Default |
|---|---|---|
| returns_csv | file (.csv) | — |
| risk_free_rate | slider (%) | 4 |
| periods_per_year | select | 252 |
| target_return | slider (%) | 0 |

## Outputs

| Key | Type |
|---|---|
| efficient_frontier | chart_scatter |
| tangency_weights | kv |
| target_weights | kv |
| summary | kv |
| weights_table | table |

## External services / API keys

None.

## Expected validator result

`overall == "pass"` on `uv run pixie validate markowitz-portfolio --json`.
