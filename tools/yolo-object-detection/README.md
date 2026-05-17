# YOLO Object Detection

Detect objects in an image using YOLOv8. Returns the annotated image with bounding boxes, a table of detections (class, confidence, bbox), and a summary card.

## Install

```bash
uv sync
```

This installs the lightweight default that uses a deterministic stub detector so the tool always validates. To enable real YOLOv8 inference:

```bash
uv sync --group models
uv run python scripts/download-model.py
```

The model weights are written to `./models/`. They are never committed to the repo (only `models/.gitkeep`).

## Run standalone

```bash
uv run python main.py --port 8000
```

## Inputs

| Key | Type | Default |
|---|---|---|
| image | image | — |
| confidence_threshold | slider | 25 |
| model | select | yolov8n |

## Outputs

| Key | Type |
|---|---|
| annotated | image |
| detections | table |
| summary | kv |

## External services / API keys

None.

## Expected validator result

`overall == "pass"` on `uv run pixie validate yolo-object-detection --json`. The reference fixture exercises the stub path so it succeeds regardless of whether the real weights are present.
