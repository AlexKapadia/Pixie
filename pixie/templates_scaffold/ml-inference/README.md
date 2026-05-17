# {{TOOL_NAME}}

*{{DESCRIPTION}}*

## What it does

Loads an image classifier from `models/`, runs inference, returns the
top-K predictions as key-value pairs. Ships with a deterministic stub
classifier so the tool validates and runs end-to-end before you wire up
real weights.

## Install

```sh
cd tools/{{TOOL_ID}}
uv sync
```

## Download the model

```sh
uv run python scripts/download-model.py
```

This pulls a small ONNX file to `models/classifier.onnx`. Swap the URL
in `scripts/download-model.py` and the loader in `src/{{PACKAGE}}/model.py`
for your own model.

To install the heavier inference runtime (PyTorch), enable the optional
dependency group:

```sh
uv sync --group models
```

## Run standalone

```sh
uv run python main.py --port 8001
```

## Inputs

| Key | Type | Description |
|---|---|---|
| `image` | image | The image to classify. |
| `top_k` | slider | Number of predictions to return. |

## Outputs

| Key | Type | Description |
|---|---|---|
| `predictions` | kv | Top-K predictions as `class -> score`. |

## External services / API keys

None. The model lives on disk under `models/`.
