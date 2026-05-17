# Live MLP Training

Trains a small multilayer perceptron on a CSV with the loss and accuracy curves streaming live to the UI via Server-Sent Events. Runs without PyTorch (pure numpy implementation) so it stays cheap to install and always validates; declare and `uv sync --group runtime` to enable the torch path.

## Install

```bash
uv sync
```

Add the torch runtime if you want a heavier model later:

```bash
uv sync --group runtime
```

## Run standalone

```bash
uv run python main.py --port 8000
```

The default 600-row XOR-ish synthetic dataset kicks in whenever a CSV is not uploaded.

## Inputs

| Key | Type | Default |
|---|---|---|
| dataset_csv | file (.csv) | demo |
| target_column | text | target |
| hidden_sizes | text | 32,16 |
| epochs | number | 20 |
| learning_rate | slider | 0.01 |
| batch_size | number | 32 |
| seed | number | 42 |

## Outputs

| Key | Type | Streaming |
|---|---|---|
| loss_curve | chart_line | yes |
| accuracy_curve | chart_line | yes |
| final_metrics | kv | no |
| epoch_summary | table | no |

`concurrent: false` — training is serialised per tool instance.

## External services / API keys

None.

## Expected validator result

`overall == "pass"` on `uv run pixie validate live-mlp-training --json`, including streaming_check.
