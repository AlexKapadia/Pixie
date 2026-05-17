---
title: Tools cookbook
description: The 21 tools that ship with Pixie, what they do, and how they're built.
sidebar:
  order: 1
slug: cookbook
---

Pixie ships with 21 working tools that exercise nearly every input and
output type. They're real (no toy demos) and they double as canonical
references when you're writing your own.

| Category                                  | Tools                                                                              |
| ----------------------------------------- | ---------------------------------------------------------------------------------- |
| [Finance & quant](#finance-and-quant)     | backtest-engine, black-scholes-greeks, markowitz-portfolio, stock-monte-carlo, example-compound-interest |
| [Machine learning](#machine-learning)     | live-mlp-training, style-transfer, vit-classifier-gradcam                          |
| [NLP](#nlp)                               | bertopic-modelling, rag-with-citations, sentiment-over-time                        |
| [Audio](#audio)                           | coqui-tts, demucs-separation, whisper-transcription                                |
| [Science & dynamics](#science-and-dynamics)| cellular-automata, lorenz-ode-solver, n-body-simulator                            |
| [Data & statistics](#data-and-statistics) | image-segmentation, time-series-forecast, yolo-object-detection                    |
| [Agents](#agents)                         | llm-tool-use-agent                                                                 |

## Finance and quant

### example-compound-interest

The canonical reference. Computes compound-interest growth on a
principal with monthly contributions over a horizon. Inputs: principal,
annual rate, years, compounding frequency, monthly contribution,
inflation-adjustment toggle. Outputs: final balance (formatted
currency), growth chart, year-by-year table. **No dependencies beyond
FastAPI / uvicorn**, so it's the lightest possible Pixie tool. Read its
source first if you're new.

### backtest-engine

Long-only moving-average crossover strategy on OHLC data. Takes fast/
slow MA periods, starting cash, and per-side commission in basis points.
Returns an equity curve overlaid against buy-and-hold, per-trade log,
and Sharpe / max drawdown / return metrics. Useful for teaching
backtesting.

### black-scholes-greeks

Closed-form European option pricer. Inputs: spot, strike, days to
expiry, risk-free rate, volatility, call/put. Returns price plus all
five first-order Greeks as `kv` and parametric charts (price vs spot,
price vs days, 2-D heatmap of price across strike × time). Pure
analytical — no approximation.

### markowitz-portfolio

Computes the efficient frontier from a CSV of historical asset returns.
Inputs: returns matrix, risk-free rate, sampling frequency, optional
target return. Outputs: frontier scatter, tangency portfolio weights
(max Sharpe), weights at target return, comparison table. Uses scipy's
constrained minimisation.

### stock-monte-carlo

Geometric Brownian motion simulation. Inputs: spot, drift, volatility,
horizon (trading days), path count, seed. Outputs: VaR / CVaR at 95%,
sample paths with percentile bands, per-day percentile table, terminal
distribution moments. Fully vectorised — all paths in one
`numpy.random.randn` call.

## Machine learning

### live-mlp-training

Trains a small MLP on a CSV dataset with user-configurable hidden
sizes, learning rate, batch size, and epoch count. **Streams loss and
accuracy curves per epoch** — outputs declare `streaming: true`. Ships
with a pure-numpy fallback so it validates without PyTorch; the torch
runtime is an optional dependency group (`uv sync --extra runtime`).

### style-transfer

Classical Gatys-style style transfer. Inputs: content image, style
image, style strength, iteration count, working image size. Streams the
loss curve per iteration. Pure-numpy / PIL fallback returns a smoothed
content image; torch+torchvision optional path runs the real loss.
`concurrent: false` because optimisation isn't thread-safe.

### vit-classifier-gradcam

ViT-B/16-224 classification with a Grad-CAM-style attention saliency
overlay (`image_compare` showing original vs heatmap). Top-K
predictions as `kv`. Model downloaded on first run (~350 MB).
`concurrent: false`.

## NLP

### bertopic-modelling

Topic modelling over a CSV of documents. Primary path: sentence
embeddings + HDBSCAN + UMAP. **Fallback**: TF-IDF + KMeans +
TruncatedSVD when BERTopic isn't available (CI, lightweight
environments). Handles tiny corpora (<8 docs) and dimension mismatches
without crashing. Outputs: topic labels, top words, document scatter
plot, detailed topic table.

### rag-with-citations

Embeds uploaded PDFs/text files, retrieves top-k via TF-IDF cosine,
outputs an extractive markdown answer with citation markers, and
**streams an LLM-synthesised answer** if `ANTHROPIC_API_KEY` is set.
Without the key, returns only the extractive answer.

### sentiment-over-time

VADER sentiment on a dated CSV. Aggregates per-row scores into rolling
windows (configurable days). Outputs: rolling-mean sentiment chart and
per-window summary table. **No model download** — runs fully offline.

## Audio

### coqui-tts

Offline text-to-speech via `pyttsx3` (SAPI on Windows, espeak on Linux,
NSSpeechSynthesizer on macOS). Inputs: text, voice, speech rate. Output:
22 kHz WAV data URL. Runtime typically <5 s. (Folder name kept for
historical reasons; uses `pyttsx3` not Coqui.)

### demucs-separation

Splits stereo/mono audio into vocals / drums / bass / other stems.
**Frequency-band heuristic fallback** when Demucs isn't installed
(centre-channel vs sideband decomposition); swaps in the real model
when it is. `concurrent: false`. Outputs: four WAV data URLs.

### whisper-transcription

CPU-only `faster-whisper` (tiny model, ~75 MB downloaded on first
run). 8 languages with auto-detect. **Streams transcript segments as
they're decoded**. `concurrent: false`. Includes a naive gap-based
speaker diarisation.

## Science and dynamics

### cellular-automata

Conway's Life or Wolfram 1-D rules (30/90/110/184). Inputs: rule, grid
width, generations, seed. Evolved grid rendered to PNG and returned as
data URL. Live-cell count plotted over time.

### lorenz-ode-solver

Integrates the Lorenz equations for given s, ?, ß. Outputs: time
series (x/y/z vs time), phase portrait (x vs z), Poincaré section
(z=27 plane crossings). The phase portrait is the canonical
`chart_scatter` example — `series` of points, not points at top level.

### n-body-simulator

Symplectic leapfrog (velocity Verlet) gravitational N-body. Inputs:
body count (2–20), mass range, step count, step size, seed. Outputs:
final positions, total energy over time, trajectory traces. Softening
prevents close-approach blow-up.

## Data and statistics

### image-segmentation

Foreground/background. **Pure-numpy Otsu threshold fallback** on
luminance; optional `rembg` path for higher-quality neural
segmentation. Outputs: segmented image (RGBA cutout or grayscale mask)
plus a small statistics table.

### time-series-forecast

ARIMA / SARIMA / Holt-Winters / auto-ARIMA. Inputs: CSV (date + value),
horizon, model, seasonality, confidence level. Outputs: history +
forecast + confidence band line chart, forecast table, backtest metrics
(MAE, RMSE, MAPE).

### yolo-object-detection

YOLOv8 (Ultralytics) on an input image. Model downloaded on first
run. Outputs: annotated image with bounding boxes, detection table
(class, confidence, bbox), summary card (top 3 classes).

## Agents

### llm-tool-use-agent

A conversational agent with calculator and sandboxed web-search stubs.
**Routes through Claude 3.5 Haiku if `ANTHROPIC_API_KEY` is set; uses a
deterministic local intent matcher otherwise**, so it always works
offline. Streams the reply token-by-token; tool calls land in a `log`
output.

---

## What you can learn from each

| If you want to learn…                                            | Read this tool                          |
| ---------------------------------------------------------------- | --------------------------------------- |
| The simplest possible Pixie tool                                 | `example-compound-interest`             |
| File upload as input                                             | `backtest-engine`, `image-segmentation` |
| Multiple chart types in one tool                                 | `black-scholes-greeks`                  |
| Streaming text output                                            | `whisper-transcription`, `llm-tool-use-agent` |
| Streaming chart output                                           | `live-mlp-training`, `style-transfer`   |
| Optional dependency groups with a fallback                       | `bertopic-modelling`, `live-mlp-training` |
| Optional API key with an offline fallback                        | `rag-with-citations`, `llm-tool-use-agent` |
| `chart_scatter` with the correct `series` shape                  | `lorenz-ode-solver`                     |
| Image output (PNG data URL)                                      | `cellular-automata`                     |
| Audio output                                                     | `coqui-tts`, `demucs-separation`        |
| `concurrent: false` for thread-unsafe model state                | every ML/NLP/audio tool                 |
| Reference fixtures                                               | most tools have a `reference/` folder    |

If you're stuck while authoring your own tool, the closest cookbook
entry is almost always a copy-pasteable starting point.
