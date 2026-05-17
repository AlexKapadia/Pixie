# Pixie — master build instructions for Claude Code

This file is the operating manual for building Pixie. Read it in full before doing anything. If a later instruction in a chat session conflicts with this file, this file wins unless the user explicitly says otherwise.

## What Pixie is

Pixie is a local-first personal dashboard for running small Python tools and models from one place. It runs entirely on the user's own machine. Each tool lives in its own folder with its own isolated virtual environment, exposes an HTTP contract, and is rendered in the dashboard via a schema-driven UI.

Pixie itself is a single web application that the user runs on localhost. The dashboard reads the `tools/` folder on startup, lists every tool it finds in a sidebar, and spawns a tool as a subprocess when the user clicks it. Tools that are not in use stay dormant on disk.

## What Pixie is not

Pixie is not hosted, not a SaaS, not a marketplace, not a deployment platform. It does not authenticate users. It does not have remote access. It does not synchronise to the cloud. It is not a generic app platform — it is for small tools and models with simple input/output contracts.

Pixie does not ingest, install, or modify tools from inside its own UI. Adding tools is done externally in Claude Code using the skills shipped in this repo. From Pixie's perspective, tools simply appear on disk in the `tools/` folder and it renders whatever is there.

## Tech stack

- Language: Python 3.12+
- Package manager: `uv` (https://docs.astral.sh/uv)
- Web framework: FastAPI with `uvicorn` as the ASGI server
- Templating: Jinja2
- Frontend: server-rendered HTML + htmx + Alpine.js for small client-side state + Tailwind CSS (loaded as a single pre-built CSS file, no build step)
- Charts: Plotly.js loaded from CDN for charts. Leaflet.js loaded from CDN for maps.
- Code editor input: CodeMirror 6 loaded from CDN, used only when a tool declares a code-type input
- Storage: SQLite via the standard library `sqlite3` module for Pixie's own state (recent runs, settings, last-used inputs per tool)
- Process management: standard library `subprocess` and `asyncio`
- Tool wrappers: FastAPI + `uvicorn` (each tool is its own tiny FastAPI app)
- Tests: `pytest`

Do not introduce other frontend frameworks (React, Vue, Svelte). Do not introduce a JavaScript build step. Do not introduce Docker for v1 (it may come later but is not part of this build).

## Repository layout

Build the repo with this exact structure:

```
pixie/
├── CLAUDE.md                      # this file
├── README.md                      # user-facing installation and usage
├── LICENCE                        # MIT
├── pyproject.toml                 # uv project config for Pixie itself
├── uv.lock
├── .gitignore                     # ignores tools/*/.venv, tools/*/data, pixie.db, .env
├── pixie/                         # the Pixie runtime package
│   ├── __init__.py
│   ├── __main__.py                # entrypoint: `python -m pixie` or `pixie` CLI
│   ├── app.py                     # FastAPI app factory
│   ├── config.py                  # settings, paths, defaults
│   ├── db.py                      # SQLite schema + helpers
│   ├── discovery.py               # scans tools/ folder, parses tool.json
│   ├── launcher.py                # subprocess management, port allocation, lifecycle
│   ├── validator.py               # end-to-end tool validation (used by skills + runtime)
│   ├── proxy.py                   # proxies /schema and /run from tool subprocesses
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── dashboard.py           # main UI routes (sidebar, tool view)
│   │   ├── tool.py                # per-tool routes (run, settings, secrets)
│   │   ├── settings.py            # global settings routes
│   │   └── api.py                 # JSON endpoints for htmx fragments
│   ├── renderer/
│   │   ├── __init__.py
│   │   ├── inputs.py              # renders each input type to HTML
│   │   ├── outputs.py             # renders each output type to HTML
│   │   └── layouts.py             # form, chat, and split layouts
│   ├── secrets.py                 # per-tool .env handling
│   ├── templates/                 # Jinja2 templates
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── tool.html
│   │   ├── chat.html
│   │   ├── settings.html
│   │   ├── empty_state.html
│   │   ├── partials/
│   │   │   ├── sidebar.html
│   │   │   ├── input_form.html
│   │   │   ├── output_panel.html
│   │   │   ├── run_history.html
│   │   │   ├── error.html
│   │   │   └── inputs/            # one partial per input type
│   │   │   └── outputs/           # one partial per output type
│   └── static/
│       ├── pixie.css              # pre-built Tailwind output
│       ├── pixie.js               # small Alpine helpers, chart init, code editor init
│       ├── pixie-logo.png         # the Pixie logo (pixel-art moth/pixie, black on white)
│       └── vendor/                # htmx, alpine, plotly, leaflet, codemirror (or CDN refs)
├── tools/                         # user's installed tools (gitignored except example/)
│   └── example-compound-interest/ # one ships in the repo as a worked example
│       ├── tool.json
│       ├── pyproject.toml
│       ├── main.py
│       └── README.md
├── docs/                          # README assets and any extended documentation
│   ├── demo.gif                   # demo animation embedded in README (placeholder at v1)
│   └── example-tool-screenshot.png # screenshot of example tool in dashboard
├── .claude/
│   └── skills/                    # Claude Code skills shipped with Pixie
│       ├── add-tool-from-repo/
│       │   └── SKILL.md
│       ├── add-tool-from-description/
│       │   └── SKILL.md
│       ├── debug-tool/
│       │   └── SKILL.md
│       ├── update-tool/
│       │   └── SKILL.md
│       └── remove-tool/
│           └── SKILL.md
└── tests/
    ├── test_discovery.py
    ├── test_launcher.py
    ├── test_validator.py
    ├── test_renderer.py
    └── test_example_tool.py
```

## The tool format (the load-bearing contract)

Every tool is a folder under `tools/` containing at minimum:

1. `tool.json` — metadata and schema
2. `pyproject.toml` — dependencies declared for `uv`
3. `main.py` — the FastAPI app that exposes the tool's HTTP endpoints
4. `.venv/` — created by `uv` at install time, never committed
5. `README.md` — optional, human-readable description
6. `data/` — optional, the tool's own persistent state. Pixie does not touch this.
7. `.env` — optional, the tool's own secrets and API keys. Pixie reads and writes this through its secrets UI but never displays values back.

### tool.json schema

```json
{
  "id": "compound-interest",
  "name": "Compound Interest",
  "description": "Calculate compound interest with monthly contributions.",
  "version": "0.1.0",
  "category": "finance",
  "icon": "calculator",
  "layout": "form",
  "warm_keep_seconds": 300,
  "max_memory_mb": 512,
  "max_runtime_seconds": 60,
  "secrets": [
    {"key": "OPENAI_API_KEY", "description": "Used for the explanation feature", "required": false}
  ],
  "inputs": [ /* see input types below */ ],
  "outputs": [ /* see output types below */ ]
}
```

Required fields: `id`, `name`, `inputs`, `outputs`. Everything else is optional with sensible defaults.

`layout` is one of `"form"` (default — inputs on left, outputs on right), `"chat"` (conversational UI with message history), or `"split"` (inputs and outputs interleaved in a single column for tools that need to show several outputs).

### HTTP contract

Every tool's `main.py` exposes a FastAPI app bound to `127.0.0.1` (never `0.0.0.0`) on a port chosen by Pixie at spawn time. The app exposes:

- `GET /schema` → returns the `tool.json` content as JSON. Pixie calls this once on first spawn to verify the schema matches what's on disk.
- `GET /healthz` → returns `{"ok": true}` once the app is ready. Pixie polls this after spawning until it returns 200 or a timeout elapses.
- `POST /run` → takes a JSON body matching the input schema, returns a JSON body matching the output schema. Synchronous.
- `GET /stream?run_id=<id>` (optional) → Server-Sent Events stream for tools that produce output incrementally. Used when an input has `streaming: true` set on any output.
- `POST /cancel?run_id=<id>` (optional) → cancels an in-flight run.

The tool is responsible for nothing else. No auth, no CORS handling, no logging configuration. Pixie talks to it over localhost only.

### Input types

The Pixie renderer must handle every type below. Each input is a JSON object in the `inputs` array of `tool.json`. Required fields: `key`, `type`, `label`. Optional common fields: `description`, `default`, `required` (default true), `group`, `show_if` (conditional visibility — an object like `{"key": "mode", "equals": "advanced"}`).

| Type | Type-specific fields |
|---|---|
| `text` | `placeholder`, `max_length` |
| `textarea` | `placeholder`, `max_length`, `monospace` (bool) |
| `number` | `min`, `max`, `step`, `unit` |
| `slider` | `min`, `max`, `step`, `range` (bool — if true, value is `[low, high]`) |
| `select` | `options: [{value, label}]`, `searchable` (bool) |
| `multiselect` | `options: [{value, label}]` |
| `checkbox` | — |
| `toggle` | — |
| `radio` | `options: [{value, label}]` |
| `date` | `min`, `max` |
| `time` | — |
| `datetime` | — |
| `date_range` | — |
| `file` | `accept` (MIME types or extensions), `max_size_mb`, `multiple` (bool) |
| `image` | `max_size_mb`, `multiple` |
| `audio` | `max_size_mb` |
| `colour` | — |
| `json` | `schema` (optional JSON schema for validation) |
| `code` | `language` (python, sql, js, etc.) |
| `markdown` | — |
| `tags` | `suggestions: [string]` |
| `autocomplete` | `endpoint` (a tool-internal URL like `/autocomplete/cities` that Pixie proxies to) |
| `table` | `columns: [{key, label, type}]`, `min_rows`, `max_rows` |
| `map_point` | `default_center: [lat, lng]`, `default_zoom` |
| `map_bbox` | `default_center`, `default_zoom` |
| `map_polygon` | `default_center`, `default_zoom` |
| `map_multipoint` | `default_center`, `default_zoom` |
| `hidden` | — (computed defaults the tool needs but the user doesn't edit) |

### Output types

Each output is a JSON object in the `outputs` array. Required fields: `key`, `type`, `label`. Optional common fields: `description`, `caption`, `unit`, `streaming` (bool — if any output is streaming, Pixie uses the `/stream` endpoint).

| Type | Type-specific fields in the output value |
|---|---|
| `text` | `value: string` |
| `markdown` | `value: string` |
| `number` | `value: number`, `format: "currency" \| "percent" \| "scientific" \| "decimal"`, `precision: number` |
| `boolean` | `value: bool`, `true_label`, `false_label` |
| `table` | `columns: [{key, label, type}]`, `rows: [object]`, `downloadable: bool` |
| `kv` | `pairs: [{key, value}]` |
| `chart_line` | `x: [number]`, `series: [{name, y: [number]}]`, `x_label`, `y_label`, `log_x`, `log_y` |
| `chart_bar` | `x: [string]`, `series: [{name, y: [number]}]` |
| `chart_scatter` | `series: [{name, points: [{x, y, label?}]}]` |
| `chart_area` | same as line |
| `chart_pie` | `slices: [{label, value}]` |
| `chart_histogram` | `values: [number]`, `bins: number` |
| `chart_boxplot` | `series: [{name, values: [number]}]` |
| `chart_heatmap` | `x_labels`, `y_labels`, `z: [[number]]` |
| `chart_candlestick` | `points: [{t, open, high, low, close}]` |
| `chart_radar` | `axes: [string]`, `series: [{name, values: [number]}]` |
| `chart_sankey` | `nodes: [{id, label}]`, `links: [{source, target, value}]` |
| `chart_treemap` | `nodes: [{id, label, value, parent?}]` |
| `chart_network` | `nodes: [{id, label}]`, `edges: [{source, target, label?}]` |
| `map_points` | `points: [{lat, lng, label?, colour?}]`, `default_center`, `default_zoom` |
| `map_heatmap` | `points: [{lat, lng, weight?}]` |
| `map_choropleth` | `geojson: object`, `values: {feature_id: number}` |
| `map_polygons` | `polygons: [{coords: [[lat, lng]], colour?, label?}]` |
| `map_route` | `points: [{lat, lng}]` |
| `image` | `value: data_url or url`, `alt?` |
| `image_grid` | `images: [{value, label?}]` |
| `image_compare` | `before: data_url`, `after: data_url` |
| `audio` | `value: data_url or url` |
| `video` | `value: data_url or url` |
| `latex` | `value: string` |
| `code` | `value: string`, `language: string` |
| `diff` | `before: string`, `after: string` |
| `tree` | `root: {label, children: []}` |
| `timeline` | `events: [{t, label, description?}]` |
| `gantt` | `tasks: [{name, start, end, dependencies?}]` |
| `progress` | `value: 0..1 or null for indeterminate`, `label?` |
| `log` | `lines: [{level, message, t}]` |
| `stream_text` | `value: string` (appended over SSE) |
| `file` | `filename: string`, `data: base64 or url`, `mime_type` |

A tool may return multiple outputs at once. If a tool returns more than one output, the renderer arranges them as stacked panels by default. The tool can request a different arrangement via the layout field on each output: `panel`, `tab`, or `inline`.

## How tools are run (the runtime model)

This is the most important part of the architecture. Read carefully.

### Process model

Pixie itself runs as a single long-lived FastAPI process listening on a fixed port (default `7860`, configurable). Tools are never imported into this process. Every tool runs as a child subprocess, started on demand, killed when no longer needed.

When the user clicks a tool in the sidebar, the launcher does the following:

1. Check if this tool is already running (registered in the launcher's in-memory state). If yes, return its port.
2. If no, pick a free port by binding to `127.0.0.1:0`, reading the assigned port, then releasing.
3. Spawn the tool: `cd tools/<tool_id> && .venv/bin/python main.py --port <port>`.
4. Poll `http://127.0.0.1:<port>/healthz` every 100ms up to a 30-second timeout.
5. Once healthy, fetch `/schema` and validate it matches the on-disk `tool.json` (warn but don't fail on mismatch).
6. Register the running tool with its port and last-used timestamp.
7. Return the port to the route handler.

### Communication

The dashboard's `POST /tool/<id>/run` route receives the user's form submission, transforms it into the JSON shape declared by the tool's input schema, and forwards it to `http://127.0.0.1:<tool_port>/run`. The response is then rendered using the output schema and returned as an htmx partial that swaps into the output panel.

For streaming tools, the dashboard opens an SSE connection to the tool's `/stream` endpoint and relays events to the browser via its own SSE endpoint at `/tool/<id>/stream`. Each event is a JSON object `{output_key, value, done}` that the browser uses to update the relevant output panel via htmx's SSE extension.

### Warm-keep policy

Tools that have been used recently stay running for `warm_keep_seconds` (per-tool, default 300) so that subsequent uses are instant. After that timeout passes with no activity, the launcher sends SIGTERM, waits up to 5 seconds, then SIGKILL if necessary. A global cap (default 5 concurrent warm tools) prevents memory exhaustion — when the cap is reached and a new tool needs to start, the least-recently-used warm tool is shut down first.

### Resource limits

On POSIX systems, the launcher uses `resource.setrlimit` to enforce `max_memory_mb` and `max_runtime_seconds` from `tool.json` as soft limits on the child process. On Windows, only the runtime limit is enforced via a watchdog timer (memory limits are not portable). Limits exceeded result in the process being killed and an error rendered to the user.

### Port management

The launcher maintains a dict of `{tool_id: (process, port, last_used)}`. Ports are assigned by the OS at bind time and never reused within a single Pixie session. When a tool is shut down, its port is released; when it's restarted, a new port is chosen.

### Failure handling

If a tool fails to start (non-zero exit during startup, `/healthz` never returns 200, schema fetch fails), the dashboard renders a clear error with the tool's stderr captured and made viewable. The tool is then marked failed in the launcher state, and subsequent clicks re-attempt the spawn (failures are not sticky — the user may have fixed something on disk between clicks).

If a tool crashes mid-run, the user sees an error in the output panel with the option to view the stderr log. The launcher de-registers the dead process and a fresh subprocess is spawned on the next click.

## The validator (mandatory end-to-end check)

Every tool must pass a deterministic validation pass before it is considered usable. The validator is the single source of truth for "is this tool well-formed and working." It is invoked by every skill that creates or modifies a tool, and by Pixie itself at discovery time.

Build it as `pixie/validator.py`, exposed three ways:

1. As a Python function `validate_tool(tool_path: Path) -> ValidationReport` that the runtime calls directly.
2. As a CLI command: `uv run pixie validate <tool_id>` for manual debugging.
3. As an HTTP endpoint at `GET /api/tools/<id>/validate` that returns the latest report as JSON.

### What the validator checks

The validator runs every check in order and stops at the first failure (except for the schema checks, which collect all problems and report them together). It does not modify the tool in any way — read-only inspection plus a controlled spawn.

1. **Folder structure.** `tool.json`, `pyproject.toml`, and `main.py` exist. Nothing in the folder has obviously wrong permissions.
2. **`tool.json` parses.** Valid JSON, parses against the Pydantic model for the tool schema. Required fields present. No unknown top-level keys.
3. **Input and output schemas are coherent.** Every `key` is unique within its list. Every type is one Pixie supports. Type-specific required fields are present (e.g. `select` has `options`, `slider` has `min`/`max`). Conditional `show_if` references existing input keys.
4. **`pyproject.toml` parses.** Lists `fastapi`, `uvicorn`, and `python-dotenv` at minimum. No dependencies on packages outside PyPI without explicit allowlisting.
5. **`.venv` exists and is functional.** Run `.venv/bin/python --version` and confirm it succeeds. If `.venv` is missing, the validator does not run `uv sync` itself — it reports the failure and returns. (Skills run `uv sync`, not the validator.)
6. **Tool spawns.** Spawn the tool the same way the launcher does, on a port the validator allocates. Wait up to 30 seconds for `/healthz` to return 200.
7. **`/schema` matches `tool.json`.** Fetch `/schema` from the running tool and compare to the parsed `tool.json` on disk. Any drift is a failure — the wrapper code and the declared schema must agree. The validator reports which fields differ.
8. **Sample-input run succeeds.** The validator generates a single set of sample inputs from the declared schema (defaults where given; otherwise type-appropriate values: empty string for `text`, 0 for `number`, mid-range for `slider`, first option for `select`, `false` for `toggle`, a 1x1 transparent PNG for `image`, and so on). It calls `/run` with these inputs and expects a 200 response within `max_runtime_seconds` from `tool.json`.
9. **Output conforms to schema.** Every declared output key is present in the response. Every value matches its declared type. No extra keys (warn, don't fail). For typed outputs like `chart_line`, the value shape matches what the renderer expects (right keys, right list shapes).
10. **Streaming check (if applicable).** If any output declares `streaming: true`, the validator opens an SSE connection to `/stream?run_id=<id>` and confirms at least one event is received within 10 seconds.
11. **Clean shutdown.** The validator sends SIGTERM and confirms the process exits within 5 seconds. If not, it sends SIGKILL and records the slow shutdown as a warning.

### ValidationReport shape

```python
class ValidationCheck(BaseModel):
    name: str                      # e.g. "schema_matches_disk"
    status: Literal["pass", "fail", "warn", "skip"]
    message: str                   # human-readable, one line
    details: str | None = None     # multi-line, for stderr/diffs/stack traces

class ValidationReport(BaseModel):
    tool_id: str
    tool_path: str
    timestamp: datetime
    overall: Literal["pass", "fail", "warn"]
    checks: list[ValidationCheck]
    sample_inputs: dict | None = None       # what the validator sent
    sample_output: dict | None = None       # what came back
    spawn_log: str | None = None            # captured stderr if anything was emitted
```

A tool with any `fail` check has overall `fail`. A tool with only `warn` and `pass` has overall `warn`. All `pass` means `pass`.

### How the validator is used

**At discovery time:** When Pixie scans `tools/` on startup, every tool is checked against the validator's report. If no report exists, the validator runs once and caches the result in SQLite. Tools with `fail` reports appear in the sidebar but are visually marked (red dot, "validation failed" badge) and clicking them shows the report instead of trying to spawn the tool. Tools with `warn` reports work normally but show a yellow indicator.

**At skill invocation:** Every skill that creates or modifies a tool ends with a call to the validator. The skill must surface the report to the user verbatim before claiming success. A skill must not report "tool added successfully" if the validation report has overall `fail` — it must report the failure and offer to debug.

**Manually:** The user can run `uv run pixie validate <tool_id>` at any time to re-check a tool. The dashboard also shows a "Re-validate" button on each tool's settings page.

### Validation report storage

Reports are persisted in a `validation_reports` table:

```sql
CREATE TABLE validation_reports (
    tool_id TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    overall TEXT NOT NULL,
    report_json TEXT NOT NULL,
    PRIMARY KEY (tool_id, timestamp)
);

CREATE INDEX idx_validation_latest ON validation_reports(tool_id, timestamp DESC);
```

Only the latest report per tool is shown in the UI; older reports are kept for 30 days for debugging history then pruned.

### What the validator does not do

- It does not run user-specified test cases. If a tool author wants richer testing, they add their own `pytest` files inside the tool folder — but this is out of scope for the validator's responsibility.
- It does not test correctness of the tool's logic. Sample inputs check that the contract is honoured, not that the answer is right.
- It does not retry on transient failures. A flaky tool is a broken tool.
- It does not modify the tool. If a check fails, the report explains what's wrong; fixing it is the skill's or user's job.

## Per-tool environment setup

Tools manage their own virtual environments via `uv`. When a tool folder appears that lacks a `.venv/`, Pixie does not automatically install dependencies. The Claude Code skill responsible for adding tools is required to run `uv sync` in the tool folder during integration. Pixie verifies `.venv/` exists before attempting to spawn a tool and surfaces a clear error if it doesn't, telling the user to run the integration skill again.

The reason for this division: Pixie should not run `uv` commands in response to UI actions. That would make the UI block on dependency resolution and creates a confusing failure surface. Dependency setup is a Claude Code job; running is a Pixie job.

## Secrets and API keys

Tools may require API keys, model paths, or other secrets. The schema declares them in `tool.json` under `secrets`. Pixie provides a per-tool settings page where the user can set values, which are written to the tool's `.env` file. The tool's `main.py` reads from `.env` via `python-dotenv` (the skill should add this to every tool by default).

Rules for the secrets UI:

- Input fields are always masked (`type="password"` in HTML).
- Once saved, values are never displayed back to the user. The UI shows a status indicator (`set` or `not set`) and a "Replace" button that opens an empty input.
- Secrets are stored only in the tool's own `.env`. Pixie does not copy them to its own SQLite or to any central store.
- The `.env` files are listed in `.gitignore` and never written to logs.

## Pixie's own SQLite schema

Pixie maintains a `pixie.db` file in the repo root with the following tables:

```sql
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE runs (
    id TEXT PRIMARY KEY,            -- UUID
    tool_id TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    inputs_json TEXT NOT NULL,
    outputs_json TEXT,
    error_text TEXT,
    status TEXT NOT NULL             -- "running", "ok", "error", "cancelled"
);

CREATE INDEX idx_runs_tool ON runs(tool_id, started_at DESC);

CREATE TABLE tool_state (
    tool_id TEXT PRIMARY KEY,
    last_inputs_json TEXT,           -- pre-fill inputs from the most recent run
    favourited BOOLEAN DEFAULT 0,
    sort_order INTEGER
);

-- See the validator section for the validation_reports table.
```

Run history is persistent and shown in a strip on each tool page (the user can click an old run to load its inputs and outputs). The dashboard never stores tool outputs containing files larger than 1MB — those are dropped from history and only the run record is kept.

## UI conventions

### Layout

- Fixed left sidebar (default 240px wide, collapsible). Lists every tool found in `tools/` grouped by category (`category` field in `tool.json`). Active tool is visually distinct. Each entry shows the tool name and a small dot indicator: green = running, grey = dormant, red = failed. The sidebar header shows the Pixie logo (`/static/pixie-logo.png`) at small size (around 32px) next to the word "Pixie" — this is the only place the logo appears in the dashboard chrome. Use the same logo as the browser favicon (referenced from `templates/base.html` as both `<link rel="icon">` for the favicon and an `<img>` in the sidebar header).
- Header strip across the top of the main area: tool name, description, settings cog, run history dropdown, and a "running" / "dormant" status pill.
- Main area is split based on `layout` field: form layout shows inputs on the left (one-third) and outputs on the right (two-thirds); chat layout shows a single full-width column with messages and a sticky input at the bottom; split layout shows inputs and outputs in a single vertical column.
- Footer strip: small text showing Pixie version, port, and a link to docs.

### Visual language

Neutral and restrained. The dashboard is infrastructure, not a marketing surface. Use Tailwind's default neutral palette (`stone` for backgrounds and text, `blue` for primary actions, `red` for errors, `amber` for warnings, `emerald` for success). System font stack (`font-sans` from Tailwind). Sentence-case for all UI text. No emoji in the UI itself.

Density should be moderate — comfortable, not cramped, but not luxuriously spaced either. Think of well-designed admin tooling like Linear's settings pages or the cleaner parts of GitHub's UI.

### Interaction patterns

- Sidebar tool clicks: `hx-get="/tool/<id>"` swaps the main content area. The URL updates via `hx-push-url="true"` so deep links work.
- Run button: `hx-post="/tool/<id>/run"` with form data, swaps the output panel. Disabled and shows a spinner while in flight.
- Streaming runs: an SSE connection opens after the initial POST returns the run ID; events update the output panel in place.
- Settings: a separate route per tool at `/tool/<id>/settings`.
- Recent runs: a dropdown in the header. Clicking a recent run does `hx-get="/tool/<id>/runs/<run_id>"` which swaps both inputs and outputs to that historical state.
- Failure states: rendered inline in the output panel with a `details/summary` for stderr.

### Schema-driven rendering rules

The renderer iterates over `inputs` and `outputs` from `tool.json` and dispatches to per-type partial templates. Each input type has its own partial in `pixie/templates/partials/inputs/<type>.html`; each output type the equivalent in `outputs/<type>.html`. Adding a new input or output type means adding a new partial and a small entry in `renderer/inputs.py` or `outputs.py` — nothing else changes.

Conditional visibility (`show_if` on inputs) is handled client-side with Alpine.js using `x-show`. The renderer emits the appropriate Alpine bindings; no server round-trip needed when toggling.

## The example tool that ships with the repo

Build `tools/example-compound-interest/` as a complete working tool that demonstrates the format. Its `tool.json` should exercise at least: a number input with min/max/step/unit, a slider, a select, a toggle, and outputs of type `number` (currency formatted), `chart_line` (growth over time), and `table` (year-by-year breakdown). Its `main.py` should be ~40 lines of FastAPI doing the actual calculation. Its `pyproject.toml` should list only `fastapi`, `uvicorn`, and `python-dotenv` as dependencies.

This tool serves three purposes: a sanity check that Pixie works, an end-to-end example of the format for users, and a reference for the Claude Code skills to point at.

## The Claude Code skills shipped in the repo

Five skills live in `.claude/skills/`. Each is a folder with a `SKILL.md` containing YAML frontmatter and instructions. The skills are loaded automatically by Claude Code when the user opens the repo. They are the only way tools get into Pixie.

### add-tool-from-repo

YAML frontmatter:
```yaml
---
name: add-tool-from-repo
description: Clones a GitHub repository and integrates it as a Pixie tool. Use when the user asks to add, install, integrate, or import a tool from a Git URL or repository.
---
```

The skill body must:

1. Take the repo URL from the user's request. Clone it to a temporary directory.
2. Read the repo's README and main code files to understand what it does, what its entrypoint is, what dependencies it uses, and what its inputs and outputs are.
3. Decide whether the repo can be cleanly integrated. Refuse and explain if any of these are true: the repo requires a GPU not present, requires a database server, is a full web application (not a tool), requires Docker, requires system packages outside a known allowlist (the allowlist is roughly: nothing — only Python packages allowed in v1).
4. If proceeding, create a new folder under `tools/` with a kebab-case ID derived from the repo name.
5. Write a `tool.json` with inputs and outputs inferred from the repo's entrypoint signature and behaviour. When in doubt, ask the user to confirm input and output types before writing.
6. Write a `pyproject.toml` listing the dependencies needed.
7. Write a `main.py` that wraps the repo's entrypoint in a FastAPI app exposing `/schema`, `/healthz`, `/run`, and (if appropriate) `/stream`.
8. Run `uv sync` in the tool folder to build the `.venv`.
9. Run the validator: `uv run pixie validate <tool_id>`. Parse the JSON report.
10. If the validator's overall status is `pass`, report success and tell the user to refresh their Pixie dashboard. Surface any `warn` checks. If overall is `fail`, surface the full report verbatim, explain what failed in plain language, and offer to debug (handing off to the `debug-tool` skill). Never report success if the validator failed.

Hard rules for this skill:
- Never invent dependencies. Only use what the repo declares or what's clearly imported.
- Never modify the cloned repo's source. Wrap it from the outside.
- Always pin Python version to 3.12 unless the repo's setup metadata declares otherwise.
- Never write secrets or API keys into `main.py`. If the tool needs them, declare them in `tool.json` under `secrets` and load via `os.environ`.
- If the entrypoint is ambiguous, ask the user which function to wrap before writing anything.

### add-tool-from-description

YAML frontmatter:
```yaml
---
name: add-tool-from-description
description: Generates a new Pixie tool from a natural-language description. Use when the user asks to make, build, create, or generate a tool to do something specific.
---
```

The skill body must:

1. Read the description carefully. Ask clarifying questions if any of these are ambiguous: what the inputs are and their types, what the outputs are and their types, whether the tool is conversational or form-based, whether it needs external APIs.
2. Pick a kebab-case ID and a human-readable name.
3. Create the folder under `tools/`.
4. Write `tool.json` with the full input and output schemas.
5. Write `pyproject.toml` with minimal dependencies (default to `fastapi`, `uvicorn`, `python-dotenv` plus whatever the tool's logic genuinely requires).
6. Write `main.py` implementing the tool's logic and the HTTP contract.
7. Run `uv sync` in the tool folder, then run the validator: `uv run pixie validate <tool_id>`. Surface the full report. Do not claim success on a fail.
8. Report success and any caveats.

The body of this skill should include short code templates for the three common cases: a pure-function tool, a stateful tool, and an LLM-wrapping tool. Use the example tool in the repo as a canonical reference.

### debug-tool

YAML frontmatter:
```yaml
---
name: debug-tool
description: Diagnoses and fixes a Pixie tool that is failing to start, crashing during runs, or returning unexpected results. Use when the user reports a broken or misbehaving tool.
---
```

The skill body must:

1. Ask which tool is failing if not specified.
2. Run the validator first: `uv run pixie validate <tool_id>`. The report is the primary diagnostic input — read it before reading the code. Most failures will be specifically located by the validator.
3. Read the tool's `main.py`, `tool.json`, and `pyproject.toml` to understand the context for whatever the validator flagged.
4. Diagnose: missing dependency, schema mismatch between code and `tool.json`, port conflict, syntax error, runtime exception during `/run`, output type mismatch.
5. Propose a fix and apply it, but only after explaining what's being changed.
6. Re-run the validator and confirm it now passes. Surface the new report.
7. If the fix doesn't work, report what was tried and what's still broken; do not silently keep iterating beyond two attempts.

### update-tool

YAML frontmatter:
```yaml
---
name: update-tool
description: Modifies an existing Pixie tool's inputs, outputs, behaviour, or dependencies. Use when the user asks to change, edit, update, or improve an existing tool.
---
```

The skill body must:

1. Ask which tool and what changes if ambiguous.
2. Read current state.
3. Make the requested changes to `tool.json`, `main.py`, and `pyproject.toml` as needed.
4. If dependencies changed, run `uv sync`.
5. Run the validator: `uv run pixie validate <tool_id>`. Surface the report.
6. Report success or failure.

### remove-tool

YAML frontmatter:
```yaml
---
name: remove-tool
description: Permanently removes a Pixie tool, including its code, virtual environment, and data. Use when the user asks to delete, uninstall, or remove a tool.
---
```

The skill body must:

1. Confirm with the user before deleting (this is destructive).
2. Stop the tool if currently running (best effort via the Pixie API at `/api/tools/<id>/stop`).
3. Delete the tool folder including `.venv` and `data`.
4. Confirm completion.

## Commands the user will run

These need to work from the repo root. Document them in the README.

```bash
# First-time setup
uv sync

# Run Pixie
uv run pixie                  # or `python -m pixie`

# Run tests
uv run pytest

# Open the dashboard
# (browser to http://localhost:7860)
```

A `pixie` console script entry point should be declared in `pyproject.toml` pointing to `pixie.__main__:main`.

## Build order

Build the project in this order. Do not skip steps. Each step should leave the repo in a runnable state.

1. **Scaffold and runtime skeleton.** Create the repo structure, `pyproject.toml` with all top-level dependencies, an empty FastAPI app that returns "Pixie is running" at `/`, and a `pixie` console script. Verify `uv run pixie` starts a server on port 7860.

2. **Discovery and the example tool.** Build `pixie/discovery.py` that scans `tools/` and parses each `tool.json`. Build `tools/example-compound-interest/` as a complete working tool (its own `pyproject.toml`, `main.py`, `tool.json`). Run `uv sync` in the example tool folder so its `.venv` exists. Add a `/api/tools` endpoint returning the list.

3. **Launcher.** Build `pixie/launcher.py` with subprocess spawn, port allocation, healthz polling, warm-keep policy, and shutdown. Cover it with `tests/test_launcher.py` using the example tool as a fixture.

4. **Proxy.** Build `pixie/proxy.py` that, given a tool ID, ensures the tool is running and forwards a JSON body to its `/run`. Returns the JSON response.

5. **Validator.** Build `pixie/validator.py` per the validator section. Expose the CLI command `uv run pixie validate <tool_id>`. Cover with `tests/test_validator.py` using the example tool as a fixture (passing case) and a deliberately broken copy as a fixture (failing case). At this point the example tool should pass validation end-to-end before any UI exists.

6. **Base templates and sidebar.** Build `templates/base.html`, the global CSS, and `templates/partials/sidebar.html`. Render the dashboard route at `/` showing the sidebar populated from discovery. Show validation status indicators (green/yellow/red dot) on each sidebar entry. Clicking a tool should swap the main area to a placeholder.

7. **Renderer — inputs.** Build `pixie/renderer/inputs.py` and the per-type partials under `templates/partials/inputs/`. Start with `text`, `number`, `select`, `checkbox`. Verify the example tool's input form renders. Then add the rest of the input types incrementally, testing each one.

8. **Run flow.** Wire up the run button: form POST to `/tool/<id>/run`, transform form data to JSON matching the schema, call the proxy, return rendered output. At this point the example tool should be fully usable end-to-end.

9. **Renderer — outputs.** Build `pixie/renderer/outputs.py` and the per-type partials under `templates/partials/outputs/`. Start with `text`, `number`, `table`, `chart_line`. Then add the rest. The example tool exercises three output types; verify they render correctly.

10. **Run history and SQLite.** Build `pixie/db.py` with the schema above (including the `validation_reports` table). Persist every run. Add the run history dropdown in the tool view header.

11. **Streaming outputs.** Add SSE support to the launcher (`/stream` proxy), the renderer, and the browser side via the htmx SSE extension. Update the validator to exercise streaming when a tool declares it.

12. **Settings — per-tool.** Build `routes/settings.py` and a settings page per tool: secrets management (masked inputs, write to tool `.env`), resource limit overrides, a "Re-validate" button that runs the validator on demand and shows the report, and a "View source" link that opens the tool's folder in the OS file browser.

13. **Settings — global.** Pixie-wide settings: port, warm-keep cap, default warm-keep seconds, developer mode toggle (shows ports/PIDs in the UI).

14. **Empty state.** Build the empty-state screen shown when `tools/` is empty (except possibly the example), pointing the user to Claude Code with the installation instructions for the skills.

15. **Error states.** Polish every failure mode: tool fails to start, missing `.venv`, schema mismatch, run error, timeout, validation failure. Each should render a clear actionable message. Failed validation should show the full report inline.

16. **Skills.** Write the five SKILL.md files under `.claude/skills/`. Each should follow the structure described above and include short worked examples. Every skill that creates or modifies a tool must end with a validator invocation and surface the report.

17. **README.** Build the README per the dedicated README section above. This is not a routine documentation step — it's a product-quality artefact. Include the logo, both tables (inputs/outputs and skills), the quick-start block, the FAQ, and placeholder paths for the demo GIF and example screenshot. Write in the deliberate voice specified, not the default Claude-doc voice.

18. **Tests.** Fill in `tests/` to cover discovery, launcher, validator, renderer for each type, and an end-to-end test that runs the example tool through the full stack.

## Coding conventions

- Type-annotate all function signatures.
- Use `pathlib.Path` everywhere, not raw strings.
- Use `pydantic` models for `tool.json` parsing and for the run request/response shapes.
- Use `asyncio` and `httpx.AsyncClient` for talking to tool subprocesses.
- Keep functions short. If a function exceeds 40 lines, look for a refactor.
- Comments explain why, not what. Most code should not need comments.
- No abbreviations in identifiers. `tool_id` not `tid`, `subprocess` not `proc`.
- All user-facing strings go through templates, not Python string literals.

## Things to refuse

If asked to do any of these, decline and explain why:

- Add authentication, user accounts, or any multi-user concept. Pixie is single-user local-only.
- Add cloud sync, telemetry, or external reporting.
- Bind the dashboard or any tool to `0.0.0.0` or any non-loopback interface.
- Support running tools as containers, on remote hosts, or in serverless platforms. Out of scope for v1.
- Add a marketplace, a registry, or any concept of "publishing" tools.
- Add JavaScript frameworks (React, Vue, Svelte) or a Node-based build step.
- Add complex agent behaviour inside Pixie itself. Pixie is a renderer and a subprocess manager. Agentic behaviour lives in Claude Code via the skills.
- Install dependencies in response to UI actions. Dependency installation is a skill responsibility.

## The README

The README is the project's storefront. Most people who land on the repo will spend less than 30 seconds deciding whether to star, try, or close. Treat it as a product surface, not as project documentation. Project documentation lives in `docs/` if it ever exists; the README sells.

Do not write a default-Claude-style README. The default style — long-winded prose, generic headings, no images, no personality, paragraph-heavy "Features" sections — is recognisable and signals an AI-generated project. People discount these heavily. Write the README in a deliberate voice: short sentences, confident, visual, scannable. Reference well-regarded OSS READMEs like Cal.com, Posthog, Plausible, Coolify, Excalidraw, and Tailscale for tone. The bar is "would a developer stop scrolling and try this."

### Structure (in this order)

1. **Hero block.** The Pixie logo (`static/pixie-logo.png`, displayed at around 120-160px) centred at the top of the README. Underneath, the project name as an H1, then a one-line tagline in italics: *"A local-first dashboard for your personal tools and models. Add tools by talking to Claude Code."* No more. The tagline is the whole pitch.

2. **Badges row.** Single line, centred. Include: licence (MIT), Python version (3.12+), build status (GitHub Actions when added), star count badge (shields.io), and a "Built for Claude Code" badge if a reasonable one exists or can be made. Six badges maximum. Use shields.io with the `flat` or `for-the-badge` style consistently.

3. **Demo block.** A single animated GIF or short MP4 showing the core flow: open Claude Code, type "add a Pixie tool that does X," watch the tool appear in the dashboard, click it, run it, see the output. The GIF should be under 10 seconds and under 5MB. If a GIF doesn't exist yet, leave a clearly-marked placeholder noting "demo gif goes here" so it doesn't get forgotten. Visual demos convert visitors to stars at roughly 10x the rate of any amount of prose; this is the single most important element of the README.

4. **Why Pixie.** Three or four sentences, no headings. Not a feature list. State the problem (developers build small tools and have nowhere to put them, deploying each one to its own URL is overkill, Streamlit Cloud and similar require either internet hosting or per-tool repos) and the answer (one local dashboard, isolated tools, Claude Code does the integration). Conversational, not corporate.

5. **Quick start.** Code block, three commands maximum:
```bash
git clone https://github.com/<user>/pixie
cd pixie
uv sync && uv run pixie
```
Then a line: "Open http://localhost:7860 and you'll see the example tool already loaded."

6. **Adding tools.** Three subsections — each a single paragraph and a code example — for the three ways to add tools:
   - **From a description** ("In Claude Code, type: *Add a Pixie tool that converts currencies using the Frankfurter API*")
   - **From a GitHub repo** ("In Claude Code, type: *Add github.com/example/calc as a Pixie tool*")
   - **By hand** (one-paragraph pointer to the tool format spec and the example tool)

7. **What tools can do (the input/output table).** A two-column table listing every supported input type on the left and every supported output type on the right, with one-line descriptions. This is the section that sells Pixie to the "what could I build with this" reader. Format as a proper markdown table, not as bullet lists. Roughly:

   | Inputs | Outputs |
   |---|---|
   | text, textarea, number, slider | text, markdown, number, boolean |
   | select, multiselect, checkbox, toggle, radio | table, kv |
   | date, time, datetime, date_range | chart (line, bar, scatter, area, pie, histogram, boxplot, heatmap, candlestick, radar, sankey, treemap, network) |
   | file, image, audio | map (points, heatmap, choropleth, polygons, route) |
   | colour, json, code, markdown, tags | image, image_grid, image_compare |
   | autocomplete, table | audio, video, latex, code, diff |
   | map (point, bbox, polygon, multipoint) | tree, timeline, gantt, progress, log |
   | hidden | stream_text, file |

   Right beneath this table, a one-line note: "Tools can mix any combination. The dashboard renders the right UI from the schema." This table is genuinely impressive when seen on first scroll and does more selling than any amount of prose.

8. **A concrete example tool.** Show the `tool.json` for the example compound-interest tool in a fenced code block, alongside a screenshot of how it renders. This makes the abstract "schema-driven UI" concept tangible.

9. **How it works (architecture).** Five-bullet summary, no diagrams unless one can be done in plain ASCII or as a small SVG. Mention the local-first runtime, the per-tool isolated venv, the schema-driven renderer, the Claude Skills integration, and the validator. Each bullet one sentence.

10. **Adding tools via Claude Code (skills section).** A small table listing the five skills and what each does:

    | Skill | What it does |
    |---|---|
    | `add-tool-from-repo` | Clones a GitHub repo and wraps it as a Pixie tool |
    | `add-tool-from-description` | Generates a tool from a natural-language description |
    | `debug-tool` | Diagnoses and fixes a broken tool |
    | `update-tool` | Modifies an existing tool's inputs, outputs, or behaviour |
    | `remove-tool` | Cleanly uninstalls a tool |

    Then a one-line note: "Skills live in `.claude/skills/` and load automatically when you open the repo in Claude Code."

11. **Configuration table.** A compact table of all the environment variables and CLI flags Pixie itself supports, with defaults. Columns: name, description, default. Keep it under 10 rows. This is the "I want to tinker" reader's section.

12. **FAQ.** Five questions maximum. Each question and answer one or two sentences. Cover: *Is my data sent anywhere? (No — everything is local.) Do I need a Claude subscription? (You need Claude Code to add tools via skills, but you can hand-write tools without one.) What if a tool breaks? (Use the `debug-tool` skill or run `uv run pixie validate`.) Can I share tools with others? (Yes — copy the tool folder, they run `uv sync` in it.) Why isn't this hosted? (Because it doesn't need to be, and your tools may touch local files or credentials.)*

13. **Contributing.** One paragraph pointing to `CONTRIBUTING.md` (which can be a stub at v1) and saying issues and PRs are welcome.

14. **Licence.** One line: "MIT. See LICENCE."

### Style rules for the README

- British or American English consistently — pick one and stick to it (the rest of the project uses British English per the user's preference, so the README uses British English too).
- No emoji in headings. One emoji per section maximum, and only where it does real work (a 🚧 next to a "Work in Progress" banner is fine; emoji-decorated H2s are not). Default to none.
- No "Why I built this" autobiographical sections. People don't care.
- No "✨ Features ✨" sections with sparkles or marketing voice. The product is the marketing.
- No phrases like "delightful," "seamless," "powerful," "robust," "leverages," "empowers." These are the default-Claude tells. Use concrete language: "renders charts," "spawns each tool in its own venv," "the validator runs every check before the tool appears in the sidebar."
- No paragraphs longer than four lines. Break them up. Most readers scan, not read.
- Use real screenshots and the actual logo. Placeholder images undermine credibility on first impression.
- Code blocks are language-tagged. Bash blocks use `bash`, JSON blocks use `json`, Python blocks use `python`.
- Tables over bullet lists whenever the data is comparable across rows. This is a project that benefits from tables — input/output types, skills, configuration — use them prominently. The two main tables (inputs/outputs and skills) should be visible on first scroll.

### Assets the README needs

- `static/pixie-logo.png` — the logo, used in the hero block.
- `docs/demo.gif` — the demo animation (placeholder at v1, replaced before any public launch).
- `docs/example-tool-screenshot.png` — a clean screenshot of the example compound-interest tool running in the dashboard.

Create these as actual files when building the README, even if some start as placeholders, so the README's image links work locally on clone.

## What "done" looks like for v1

The user can:

1. Clone the repo, run `uv sync`, run `uv run pixie`, and open localhost:7860 in a browser.
2. See the example tool in the sidebar with a green validation indicator and use it end-to-end — adjust inputs, click run, see numerical, chart, and table outputs.
3. Open Claude Code in the repo, type "add a Pixie tool that converts currencies using the Frankfurter API," and have a new tool appear in their sidebar after the validator confirms it works. The skill must report the validation result, not just "done."
4. Open Claude Code, type "add github.com/some/calculator as a Pixie tool," and have it integrated and validated (assuming the repo is compatible).
5. Configure API keys for a tool via the settings page.
6. See run history and re-run past inputs.
7. Have tools shut down automatically when not in use, and restart on demand.
8. Run `uv run pixie validate <tool_id>` manually and see a structured report.
9. See clearly broken tools (failed validation) in the sidebar with red indicators, click them, and see the validation report instead of a confusing crash.

If all nine work end-to-end without manual intervention beyond the user prompts in Claude Code, v1 is done.

## Open questions to flag, not solve

These are deliberately out of scope for v1. If the user asks about them, acknowledge them and defer:

- Sharing tools between machines (manual `git clone` of a tool folder works fine for now).
- Tools that need a GPU.
- Tools that maintain server-side connections (WebSockets to external services, long-poll integrations).
- A plugin system beyond the schema-driven renderer.
- Themes beyond the default.
- Mobile or tablet layouts.
- Native packaging (Tauri, PyInstaller, etc.).

## Final reminders

Build incrementally. Run the example tool end-to-end as early as possible — by step 7 you should have a usable system. Resist the urge to scope-creep. The renderer is where the project lives or dies; the rest is plumbing. Test the schema-driven UI against every input and output type before declaring the renderer done.

When in doubt about a design decision, choose the simpler, more boring option. Pixie is infrastructure for personal tools. It should feel quiet and reliable, not clever.