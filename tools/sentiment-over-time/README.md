# Sentiment Over Time

Score per-row sentiment with VADER and aggregate by day with a rolling-mean window.

## Install
```
cd tools/sentiment-over-time
uv sync
```

## Test
```
uv run pixie validate sentiment-over-time --summary
```
