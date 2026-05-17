---
title: How Pixie works
description: The five things you need to understand to use, build, or contribute to Pixie.
sidebar:
  order: 1
---

Pixie is small enough that you can hold the whole architecture in your head.
There are five moving parts. Once you've read this page you'll understand
roughly half the codebase.

## 1. The dashboard is one Python process

Pixie itself is a single FastAPI app run by `uvicorn`, listening on
`127.0.0.1:7860`. It serves the sidebar, the tool pages, the settings UI,
and a handful of htmx-friendly endpoints. **It never imports tool code.**

When you run `uv run pixie`, you get exactly one Python process — plus
whatever child processes the launcher has spawned to serve warm tools.

## 2. Tools are isolated subprocesses

Every tool under `tools/<id>/` has:

- Its own `pyproject.toml` declaring exact dependencies.
- Its own `.venv/` built by `uv sync`.
- A `main.py` that runs FastAPI on `127.0.0.1:<port>` where the port is
  passed in at spawn time.

When you click a tool in the sidebar, the launcher:

1. Picks a free port by binding to `127.0.0.1:0` and reading the assignment.
2. Spawns `<tool>/.venv/bin/python main.py --port <port>`.
3. Polls `GET /healthz` until it returns `{"ok": true}` (up to 30 s).
4. Fetches `GET /schema` and compares it to the on-disk `tool.json` (drift
   logs a warning).
5. Registers the running tool in an in-memory dict.

The tool then stays warm for `warm_keep_seconds` (default 300). A global
cap (`warm_keep_max`, default 5) keeps memory bounded — when full, the
least-recently-used warm tool is shut down to make room.

Why subprocesses? Because tools have wildly different dependencies. A
`whisper-transcription` tool brings PyTorch and `numpy`. A `lorenz-ode-solver`
brings `scipy` and `matplotlib`. A `compound-interest` tool brings nothing
beyond `fastapi`. Sharing one Python process means dependency-hell within a
day. Isolated venvs make it impossible.

## 3. The contract is `tool.json`

A `tool.json` declares **inputs** (what the user fills in), **outputs** (what
the tool returns), **layout** (form, chat, or split), **secrets** (API keys
the tool needs), and metadata (id, name, category, icon, resource limits).

Pixie's renderer reads this file and emits the appropriate HTML — a `select`
input becomes a `<select>`, a `slider` becomes a Tailwind-styled range
control, a `chart_line` output becomes a Plotly chart, a `map_points` output
becomes a Leaflet map.

The tool's `main.py` reads the same `tool.json` shape on the wire: `POST
/run` accepts a body matching the `inputs` schema and returns a body
matching the `outputs` schema. There is no other contract.

## 4. The validator is the gatekeeper

Before a tool appears in the sidebar with a green dot, it must pass **11
deterministic checks**:

1. Folder structure (`tool.json`, `pyproject.toml`, `main.py` exist).
2. `tool.json` parses against the Pydantic model.
3. Input/output schemas are coherent (unique keys, valid types, conditional
   `show_if` references resolve).
4. `pyproject.toml` parses and declares the required dependencies.
5. `.venv/` exists and `python --version` succeeds.
6. The tool spawns and `/healthz` returns 200 within 30 s.
7. `/schema` matches `tool.json` on disk.
8. A sample-input run via `/run` completes within `max_runtime_seconds`.
9. The response conforms to the output schema (right keys, right shapes).
10. If any output is `streaming: true`, the `/stream` endpoint emits at least
    one event within 10 s.
11. Clean shutdown — SIGTERM → exit within 5 s, otherwise SIGKILL and a
    warning.

The validator is invoked at:

- **Discovery time** — when Pixie scans `tools/` on startup, every tool's
  last cached report is consulted. Tools without a report are validated
  once and the result is cached in SQLite.
- **Skill invocation** — every skill that creates or modifies a tool ends
  with a validator call. The skill must surface the report verbatim. **It
  may not claim success on a `fail` report.**
- **On demand** — `uv run pixie validate <id>` from the CLI, or the
  "Re-validate" button on a tool's settings page.

There's a 12th opt-in check for tools that ship **reference fixtures** —
deterministic expected outputs that the validator compares against using
type-aware comparators (image histograms, audio spectral distance, PDF text
diff, …). See [Fixtures & reference validation](/Pixie/build/fixtures/).

## 5. Everything else is persistence

A SQLite file at `pixie.db` stores:

- `settings` — UI prefs (theme, density, accent).
- `runs` — every tool invocation (inputs, outputs, status, error_text).
- `tool_state` — last-used inputs per tool, favourites, sort order,
  pinned/archived flags, run counters.
- `validation_reports` — the latest report per tool plus 30 days of history.
- `artefacts` — large outputs spilled to disk under `artefacts/`, with
  SHA-256 + MIME + soft-delete.
- `workspaces` / `tool_workspaces` / `tool_tags` — sidebar grouping and
  filtering.
- `validate_jobs` — progress of batch validation runs.

WAL mode, 5-second busy timeout, foreign keys on. Schema is idempotent —
re-running `init_db` against an existing DB is a no-op. Column migrations
are applied via `ALTER TABLE` with "duplicate column" errors swallowed.

## How the pieces fit

```
┌──────────────────────────────────────────────────────────────────┐
│                       Browser (htmx + Alpine)                    │
│  GET / → sidebar; POST /tool/<id>/run → output panel swap         │
└──────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                Pixie  (FastAPI on 127.0.0.1:7860)                │
│                                                                  │
│  routes/dashboard.py   ── renders sidebar from discovery         │
│  routes/tool.py        ── per-tool views, run, history, settings │
│  routes/api.py         ── JSON for htmx fragments                │
│                                                                  │
│  discovery.py          ── scans tools/, parses tool.json         │
│  validator.py          ── 11-check pass before sidebar shows tool│
│  launcher.py           ── spawns / warm-keeps / kills subprocs   │
│  proxy.py              ── forwards /run + /stream to tool port   │
│  renderer/inputs.py    ── tool.json input → HTML partial         │
│  renderer/outputs.py   ── tool.json output → HTML partial        │
│  db.py                 ── SQLite (runs, state, reports, ...)     │
└──────────────────────────────────────────────────────────────────┘
                                │ httpx
                ┌───────────────┼───────────────┐
                ▼               ▼               ▼
        ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
        │ tools/a/    │ │ tools/b/    │ │ tools/c/    │
        │ .venv/      │ │ .venv/      │ │ .venv/      │
        │ main.py     │ │ main.py     │ │ main.py     │
        │ port 51234  │ │ port 51235  │ │ port 51236  │
        │ FastAPI app │ │ FastAPI app │ │ FastAPI app │
        └─────────────┘ └─────────────┘ └─────────────┘
```

## Read next

- [Runtime & subprocesses](/Pixie/concepts/runtime/) — port allocation,
  warm-keep policy, resource limits, lifecycle.
- [The validator](/Pixie/concepts/validator/) — what each check does and how
  to read the report.
- [Schema-driven UI](/Pixie/concepts/renderer/) — how `tool.json` becomes
  HTML, the partial dispatch, how to add a new type.
- [Storage & runs](/Pixie/concepts/storage/) — the SQLite schema, artefact
  spill, retention sweeper.
- [Secrets](/Pixie/concepts/secrets/) — per-tool `.env` files, the masked
  UI, redaction.
