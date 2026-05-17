# {{TOOL_NAME}}

*{{DESCRIPTION}}*

## What it does

Generates a series under one of three growth shapes (linear, quadratic,
exponential), returns the peak value, a line chart, and a step-by-step
breakdown table.

## Install

```sh
cd tools/{{TOOL_ID}}
uv sync
```

## Run standalone

```sh
uv run python main.py --port 8001
```

## Inputs

| Key | Type | Description |
|---|---|---|
| `scale` | number | Linear multiplier applied to the sample series. |
| `intensity` | slider | How aggressively the values grow. |
| `shape` | select | Curve family (linear, quadratic, exponential). |

## Outputs

| Key | Type | Description |
|---|---|---|
| `peak_value` | number | Maximum value in the series. |
| `growth_chart` | chart_line | The series rendered as a line chart. |
| `breakdown` | table | Step-by-step values. |

## External services / API keys

None.
