<div align="center">

<img src="./Pixie%20Logo.png" alt="Pixie" width="220" />

### A local dashboard for every Python tool you've ever written.

[Docs](https://alexkapadia.github.io/Pixie/) · [Install](https://alexkapadia.github.io/Pixie/start/install/) · [Cookbook](https://alexkapadia.github.io/Pixie/cookbook/) · [Skills](https://alexkapadia.github.io/Pixie/skills/overview/)

</div>

<br />

<div align="center">

https://github.com/AlexKapadia/Pixie/raw/main/Pixie.mp4

</div>

<br />

## What it is

Pixie is one local web app. Point it at a `tools/` folder and it scans, validates, and serves every tool in there with a real UI: forms, charts, maps, tables, audio, video, the lot. Each tool runs in its own `uv` virtualenv as a subprocess that spins up on click and shuts down when idle.

You don't add tools through the dashboard. You add them by talking to Claude Code, and you bring whatever you've already got:

* a description in plain English (`add-tool-from-description`)
* a GitHub repo (`add-tool-from-repo`)
* a Python script on disk (`wrap-local-script`)
* a Jupyter notebook (`add-tool-from-notebook`)
* a Streamlit or Gradio app (`convert-streamlit-app`, `convert-gradio-app`)
* a CLI binary like `ffmpeg`, `yt-dlp`, `pandoc` (`add-tool-from-cli-command`)
* an OpenAPI / Swagger spec (`add-tool-from-openapi-spec`)
* **an Excel `.xlsx` model**, formulas and all (`add-tool-from-excel-model`)
* **an academic paper PDF or arXiv link** (`add-tool-from-paper`, which also generates reference fixtures from the paper's reported numbers)
* a detailed model spec when there's no paper or code (`implement-model-from-spec`)

Each skill writes the schema, the FastAPI handler, the dependencies, runs the validator end-to-end, and only claims success if every check passes. Refresh the page and the tool shows up with a green dot.

Everything stays on `127.0.0.1`. No accounts. No telemetry. No cloud sync. Your `.env` files stay in your tool folders.

## Install

```bash
git clone https://github.com/AlexKapadia/Pixie
cd Pixie
uv sync
uv run pixie
```

Open `http://127.0.0.1:7860`. Done.

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). Works on macOS, Linux, and Windows.

## Add your first tool

In Claude Code, inside the Pixie repo, say whichever fits what you've got:

```
Add a Pixie tool that fetches a stock ticker and runs a Monte Carlo on it.
```
```
Add a Pixie tool from https://github.com/some-org/cool-model
```
```
Wrap my Excel model at ./quant/black_litterman.xlsx as a Pixie tool.
```
```
Implement this paper as a Pixie tool: https://arxiv.org/abs/2310.06770
```
```
Add a Pixie tool from this notebook: ./experiments/forecasting.ipynb
```

Claude picks an id, writes `tool.json`, writes `main.py`, runs `uv sync`, spawns the subprocess, POSTs sample input, checks the response conforms to the declared output schema, then reports back. If anything fails, the tool does not appear in the sidebar.

Full walkthrough: [start/first-tool](https://alexkapadia.github.io/Pixie/start/first-tool/).

## What ships in the box

Thirty-one tools, all validated, all reproducible:

| Domain | Tools |
| --- | --- |
| Quant & finance | black-scholes-greeks, markowitz-portfolio, stock-monte-carlo, backtest-engine |
| Time series | time-series-forecast, sentiment-over-time, anomaly-detection-isolation-forest |
| ML training | live-mlp-training, vit-classifier-gradcam, yolo-object-detection, image-segmentation, style-transfer |
| NLP & audio | bertopic-modelling, whisper-transcription, coqui-tts, demucs-separation, rag-with-citations, llm-tool-use-agent |
| Causal & stats | dowhy-causal-ate, pymc-bayesian-ab, kaplan-meier-cox |
| Simulation | lorenz-ode-solver, n-body-simulator, lotka-volterra-simulator, cellular-automata |
| Geospatial & graph | geospatial-kde-heatmap, open-meteo-forecast, graph-algorithms-playground, tsp-route-optimizer |
| Physics | qiskit-quantum-simulator |
| Examples | example-compound-interest |

Each is a folder under `tools/`. Each has a `tool.json`, a `pyproject.toml`, a `main.py`, sample fixtures, and reference outputs the validator diffs against on every change.

## How a tool is shaped

`tool.json` declares inputs, outputs, layout, and secrets. Pixie renders the entire UI from the schema, no per-tool frontend code.

```json
{
  "id": "currency-converter",
  "name": "Currency Converter",
  "inputs": [
    { "id": "from",   "type": "select", "options": ["USD", "EUR", "GBP"] },
    { "id": "to",     "type": "select", "options": ["USD", "EUR", "GBP"] },
    { "id": "amount", "type": "number", "min": 0 }
  ],
  "outputs": [
    { "id": "converted", "type": "number", "format": "currency" }
  ]
}
```

You get, free, 28 input widgets and 30-odd output renderers: text, markdown, sliders, file drops, maps (points, heatmap, choropleth, polygons, route), charts (line, bar, scatter, area, pie, histogram, boxplot, heatmap, candlestick, radar, sankey, treemap, network), tables, audio, video, LaTeX, code, diffs, gantt, timelines, streaming text.

Full reference: [Input types](https://alexkapadia.github.io/Pixie/build/inputs/) and [Output types](https://alexkapadia.github.io/Pixie/build/outputs/).

## Skills

Pixie ships about fifty Claude Code skills covering the whole lifecycle:

* **Build new tools.** `add-tool-from-description`, `add-tool-from-repo`, `add-tool-from-paper`, `add-tool-from-notebook`, `add-tool-from-openapi-spec`, `add-tool-from-excel-model`, `add-tool-from-cli-command`, `convert-streamlit-app`, `convert-gradio-app`, `wrap-local-script`, `implement-model-from-spec`.
* **Maintain existing tools.** `update-tool`, `rename-tool`, `fork-tool`, `tag-tool`, `migrate-tool-format`, `organise-tool`, `lint-tool`, `set-secret`, `cite-source`.
* **Diagnose.** `debug-tool`, `pixie-doctor`, `pixie-status`, `revalidate-all`, `validate-against-reference`, `view-logs`, `view-runs`, `inspect-tool`, `list-tools`.
* **Data and outputs.** `fetch-dataset-from-url`, `fetch-dataset-from-kaggle`, `fetch-dataset-from-huggingface`, `import-dataset-from-local`, `list-outputs`, `find-output`, `export-as-format`, `export-run`, `export-run-as-report`, `bulk-export`, `copy-to-clipboard`, `copy-output-to`, `send-to-folder`, `register-export-target`, `star-run`, `label-run`.
* **House-keeping.** `archive-tool`, `unarchive-tool`, `remove-tool`, `audit-disk-usage`, `clear-old-outputs`, `share-tool`, `import-tool`, `workspace-create`, `workspace-add-tool`, `workspace-remove-tool`, `open-artefacts-folder`.

Each one has a narrow trigger, runs the validator if it touches a tool, and refuses politely when given the wrong shape of input.

## The validator

Every tool passes a deterministic check sequence before it appears in the sidebar:

1. Folder structure is sane.
2. `tool.json` parses against the schema.
3. `pyproject.toml` is valid.
4. `.venv` builds cleanly.
5. Subprocess starts on the assigned port.
6. `/healthz` returns 200.
7. `/schema` matches `tool.json`.
8. `/run` accepts sample input and returns inside the timeout.
9. Output shape matches the declared outputs.
10. Subprocess shuts down cleanly when idle.
11. Reference fixtures diff inside tolerance.

Failures don't ship. There is no "mostly works" tier.

## What it isn't

Pixie is not a SaaS, not a marketplace, not a deployment platform. It does not authenticate users. It does not push tools to a server. It will not, ever, ingest a tool from inside its own UI: that path goes through Claude Code on your machine, where you can see what is being written before it is written.

It is also not a generic app platform. It is for small tools and models with a clean input/output contract. If you need session state, multi-user auth, or long-lived background jobs, build them somewhere else.

## Tests

The Pixie test suite (unit, integration, format, perf, visual regression, accessibility, e2e Playwright matrix) lives in a separate repo: [AlexKapadia/Pixie-tests](https://github.com/AlexKapadia/Pixie-tests). Keeps this repo focused on the runtime and the tool library.

## Status

Active, single-author project, MIT licensed. Issues and PRs welcome at [github.com/AlexKapadia/Pixie/issues](https://github.com/AlexKapadia/Pixie/issues). Read [Contributing](https://alexkapadia.github.io/Pixie/contributing/overview/) before opening a PR, but the short version is: if it works and the validator passes, it's probably in.

## Licence

[MIT](./LICENCE).
