# Image Segmentation

Foreground / background segmentation. Returns the cut-out image (transparent background) or the binary mask, plus a small per-region pixel-count table.

## Install

```bash
uv sync
```

Light by default with an Otsu-threshold fallback so the tool validates without heavy ONNX wheels. To enable the real `rembg` U2Net / Silueta models:

```bash
uv sync --group models
```

The first /run with the real backend triggers a one-off model download into the local cache.

## Run standalone

```bash
uv run python main.py --port 8000
```

## Inputs

| Key | Type | Default |
|---|---|---|
| image | image | demo disc |
| model | select | u2net |
| output_format | select | cutout |

## Outputs

| Key | Type |
|---|---|
| segmented | image |
| mask | image |
| stats | table |

## External services / API keys

None at install time. `rembg` will fetch model weights on first run.

## Expected validator result

`overall == "pass"` on `uv run pixie validate image-segmentation --json`.
