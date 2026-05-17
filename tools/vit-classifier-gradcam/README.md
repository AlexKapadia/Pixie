# ViT Classifier + Grad-CAM

Vision Transformer image classifier (Google ViT-B/16-224) with a Grad-CAM-style attention overlay so the user can see where the model is looking.

## Install

```bash
uv sync
```

Light by default: ships a deterministic fallback so the tool validates without 1GB of model wheels. To enable the real ViT model:

```bash
uv sync --group models
```

The first /run triggers a HuggingFace download into the local cache (~330MB).

## Run standalone

```bash
uv run python main.py --port 8000
```

## Inputs

| Key | Type | Default |
|---|---|---|
| image | image | — |
| top_k | number | 5 |

## Outputs

| Key | Type |
|---|---|
| predictions | kv |
| explanation | image_compare |

## External services / API keys

Hugging Face model hub (only on first run with `--group models`).

## Expected validator result

`overall == "pass"` on `uv run pixie validate vit-classifier-gradcam --json`.
