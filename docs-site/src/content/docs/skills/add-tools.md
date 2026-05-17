---
title: Add tools
description: Every skill that creates a new tool — from description, repo, notebook, CLI, spec, paper, or zip.
sidebar:
  order: 2
---

The Pixie skill library has ten ways to create a new tool. Pick the one
whose **source artefact** matches what you have.

## Quick chooser

| You have…                                 | Use this skill                                                  |
| ----------------------------------------- | --------------------------------------------------------------- |
| A natural-language description, no code   | [`add-tool-from-description`](#add-tool-from-description)        |
| A Git URL                                 | [`add-tool-from-repo`](#add-tool-from-repo)                      |
| A local `.py` file                        | [`wrap-local-script`](#wrap-local-script)                        |
| A Jupyter `.ipynb`                        | [`add-tool-from-notebook`](#add-tool-from-notebook)              |
| A CLI binary (`ffmpeg`, `yt-dlp`, …)      | [`add-tool-from-cli-command`](#add-tool-from-cli-command)        |
| An OpenAPI / Swagger spec                 | [`add-tool-from-openapi-spec`](#add-tool-from-openapi-spec)      |
| A Streamlit `.py` app                     | [`convert-streamlit-app`](#convert-streamlit-app)                |
| A Gradio `.py` app                        | [`convert-gradio-app`](#convert-gradio-app)                      |
| An Excel `.xlsx` model                    | [`add-tool-from-excel-model`](#add-tool-from-excel-model)        |
| A research paper PDF or arXiv link        | [`add-tool-from-paper`](#add-tool-from-paper)                    |
| A `.zip` someone packaged via `share-tool`| [`import-tool`](#import-tool)                                    |
| A detailed model spec (architecture etc.) | [`implement-model-from-spec`](#implement-model-from-spec)        |

Every skill ends with `uv run pixie validate <tool_id>` and refuses to
claim success on a `fail`.

---

## add-tool-from-description

<span class="skill-pill">non-destructive</span>

**Trigger:** "Add a Pixie tool that …", "Make me a tool that …",
"Generate a tool to …" — with no artefact attached.

**Steps:**

1. Ask up to 3 clarifying questions (inputs? outputs? stateful or
   functional? needs external APIs?).
2. Pick template — pure function / stateful / LLM-wrapping (see
   [patterns](/Pixie/build/patterns/)).
3. Pick a kebab-case `id` and human-readable name.
4. Write `tools/<id>/tool.json`, `pyproject.toml`, `main.py`,
   `README.md`.
5. `uv sync` inside the tool folder.
6. `uv run pixie validate <id> --json`.
7. Surface the full report.

**Refuses to:** scaffold tools that require a GPU, Docker, a database
server, or system packages outside the allowlist (currently empty —
Python-only).

**Example trigger:**
```text
Add a Pixie tool that converts between metric and imperial units
```

---

## add-tool-from-repo

<span class="skill-pill">non-destructive</span>

**Trigger:** a Git URL (`github.com/…`, `gitlab.com/…`, `*.git`,
`git@…`). "Add github.com/x/y as a Pixie tool", "Wrap this repo".

**Steps:**

1. Parse URL. Refuse non-Git inputs (route to alternates).
2. `git clone --depth=1` to a temp dir.
3. Read README, main code files, `pyproject.toml`/`requirements.txt` to
   understand the entrypoint and dependencies.
4. Decide whether the repo can be cleanly wrapped. Refuse if it needs a
   GPU not present, a database server, Docker, system packages outside
   allowlist, or it's a full SPA rather than a tool.
5. Create `tools/<id>/` with kebab-case id derived from repo name.
6. Write `tool.json` (inputs/outputs inferred), `pyproject.toml`
   (declared deps + fastapi/uvicorn/python-dotenv), `main.py` (FastAPI
   wrapper around the repo's entrypoint).
7. `uv sync`.
8. `uv run pixie validate <id>`. Surface report verbatim.

**Hard rules:**
- Never invent dependencies. Use only what the repo declares or imports.
- Never modify cloned source. Wrap from outside.
- Pin Python 3.12 unless the repo's metadata says otherwise.
- If the entrypoint is ambiguous, ask before writing.

**Example trigger:**
```text
Add github.com/foo/bar as a Pixie tool
```

---

## wrap-local-script

<span class="skill-pill">non-destructive</span>

**Trigger:** a local `.py` file path. "Wrap `./scripts/foo.py` as a
Pixie tool".

Refuses `.py` files that import `streamlit` or `gradio` (routes to
`convert-streamlit-app` / `convert-gradio-app`).

---

## add-tool-from-notebook

<span class="skill-pill">non-destructive</span>

**Trigger:** an `.ipynb` path. "Convert this notebook to a Pixie tool".

Extracts the meaningful "input cells" and "output cells" by inspecting
the notebook, generates `tool.json` and `main.py` that re-runs the
relevant pipeline, then validates.

---

## add-tool-from-cli-command

<span class="skill-pill">non-destructive</span>

**Trigger:** a CLI binary name (`ffmpeg`, `pandoc`, `yt-dlp`,
`imagemagick`, `curl`). "Wrap `ffmpeg` as a Pixie tool".

Generates `tool.json` from the binary's flags (via `--help` parsing) and
a `subprocess`-based `main.py`. Refuses Python scripts (use
`wrap-local-script`) and full repos (use `add-tool-from-repo`).

---

## add-tool-from-openapi-spec

<span class="skill-pill">non-destructive</span>

**Trigger:** mentions of "OpenAPI", "Swagger", `openapi.yaml`,
`openapi.json`. "Wrap this API spec".

Reads the spec, picks one endpoint (asks if multiple), generates inputs
from the endpoint's parameters and outputs from the response schema,
writes an `httpx`-based `main.py`.

---

## convert-streamlit-app

<span class="skill-pill">non-destructive</span>

**Trigger:** mentions of Streamlit, `streamlit run`, or a `.py` that
imports `streamlit`. "Port this Streamlit app to Pixie".

Maps `st.*` widgets to `tool.json` inputs and `st.*` outputs to partials.
Single-form apps only — refuses multi-page or stateful apps.

## convert-gradio-app

<span class="skill-pill">non-destructive</span>

**Trigger:** mentions of Gradio, `gr.Interface`, `gr.Blocks`, or a `.py`
importing `gradio`.

Same idea as Streamlit conversion but for `gr.Interface` / `gr.Blocks`
mappings.

---

## add-tool-from-excel-model

<span class="skill-pill">non-destructive</span>

**Trigger:** a `.xlsx` workbook. "Wrap this Excel model".

Parses the formula DAG with `openpyxl`, generates Python that
reproduces every cell. Refuses `.xlsm`/`.xlsb`/`.xls` (different
binary formats) and `.csv` (route to `fetch-dataset-from-url` or
`import-dataset-from-local`).

---

## add-tool-from-paper

<span class="skill-pill">non-destructive</span>

**Trigger:** a paper PDF, arXiv link, or DOI. "Implement this paper as
a Pixie tool".

Reads the paper, implements the method as a new tool, and **generates
reference fixtures from the paper's reported numbers** — so check 12 is
useful from day one.

Refuses to cite without creating (`cite-source` does that). Refuses code
(use `add-tool-from-repo`).

---

## implement-model-from-spec

<span class="skill-pill">non-destructive</span>

**Trigger:** a detailed ML model spec (architecture, training setup,
hyperparameters, expected metric). "Build a tool that implements this
model".

For when you have a spec but no code, no paper, and no repo — i.e. you
know what you want, you just need it built.

---

## import-tool

<span class="skill-pill">non-destructive</span>

**Trigger:** a `.zip` someone packaged via `share-tool`. "Install this
zipped tool".

**Refuses zips that contain:**
- `.venv/` (platform-specific bloat).
- `.env` (secrets must be set out-of-band via `set-secret`).
- Native binaries.
- `../` in any path (traversal).
- Multiple top-level directories.

**Routes elsewhere if:**
- The zip is a `.git` archive → `add-tool-from-repo`.
- The zip is a notebook → `add-tool-from-notebook`.
- The zip is a single `.py` → `wrap-local-script`.

**Steps:**

1. Extract to a temp dir; validate security constraints.
2. Refuse if a tool with this id already exists (offer `remove-tool` or
   `rename-tool`).
3. Move to `tools/<id>/`.
4. `uv sync`.
5. `uv run pixie validate <id> --json`. Surface report.

---

## After it lands

Every "add" skill leaves you with:

- A new folder under `tools/<id>/`.
- An installed `.venv/`.
- A `validation_reports` row in `pixie.db`.

Refresh the dashboard and the tool appears in the sidebar.

If validation failed, the skill says so and offers
[`debug-tool`](/Pixie/skills/diagnostics/#debug-tool). Run it. The first
attempt usually fixes obvious issues (missing dep, wrong output shape).
