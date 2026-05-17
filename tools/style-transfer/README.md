# Neural Style Transfer

Classic Gatys-style neural style transfer: paint a content image with the texture and palette of a style image. The optimisation loss streams to the UI in real time so the user can watch convergence.

## Install

```bash
uv sync
```

Light by default: ships a histogram-matching fallback that produces a plausible stylised result without 1GB of torch wheels. To enable the real VGG19-based algorithm:

```bash
uv sync --group runtime
```

## Run standalone

```bash
uv run python main.py --port 8000
```

Without uploaded images, the tool falls back to two solid-colour pads so the wiring exercises end-to-end.

## Inputs

| Key | Type | Default |
|---|---|---|
| content_image | image | sand pad |
| style_image | image | navy pad |
| strength | slider (%) | 60 |
| iterations | number | 100 |
| image_size | select | 128 |

## Outputs

| Key | Type | Streaming |
|---|---|---|
| styled | image | no |
| loss_curve | chart_line | yes |
| summary | kv | no |

`concurrent: false` — the optimisation is serialised per tool instance.

## External services / API keys

VGG19 weights are downloaded from `torch.hub` on first run with `--group runtime`.

## Expected validator result

`overall == "pass"` on `uv run pixie validate style-transfer --json`, including streaming_check. The reference fixture uses the fallback path so it runs in seconds.
