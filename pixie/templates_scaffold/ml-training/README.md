# {{TOOL_NAME}}

*{{DESCRIPTION}}*

## What it does

Trains a model on an uploaded CSV. Streams per-epoch loss values via SSE
so the line chart in Pixie updates live. Marked `concurrent: false` so
two trainings never fight over the same resources.

## Install

```sh
cd tools/{{TOOL_ID}}
uv sync
```

To install the real training runtime (PyTorch), enable the optional
dependency group:

```sh
uv sync --group runtime
```

## Run standalone

```sh
uv run python main.py --port 8001
```

## Streaming contract

* `POST /run` returns `{run_id, loss_curve, summary}` with empty series.
  The renderer immediately switches to streaming mode for the
  `loss_curve` output (declared `streaming: true` in `tool.json`).
* `GET /stream?run_id=<id>` emits one SSE per epoch:
  `{"epoch": N, "loss": x, "val_loss": y, "done": false}`. The final
  event has `"done": true`.
* `POST /cancel?run_id=<id>` stops the run.

## Inputs

| Key | Type | Description |
|---|---|---|
| `dataset` | file | CSV with features and one target column. |
| `epochs` | slider | Number of training epochs (1-100). |
| `learning_rate` | slider | Optimiser step size. |

## Outputs

| Key | Type | Description |
|---|---|---|
| `loss_curve` | chart_line (streaming) | Train + validation loss per epoch. |
| `summary` | table | Per-epoch numeric summary. |

## External services / API keys

None.
