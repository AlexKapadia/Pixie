---
title: Validator checks
description: Detailed semantics of each of the 12 validator checks.
sidebar:
  order: 5
---

The validator's 11 mandatory checks plus optional check 12.

## 1. `folder_structure`

**Verifies:** `tool.json`, `pyproject.toml`, and `main.py` exist at
`tools/<id>/`. Files are readable.

**Fails when:** any of those files is missing or unreadable. Stops
further checks if it fails.

## 2. `tool_json_parses`

**Verifies:** `tool.json` is valid JSON and matches the `ToolSchema`
Pydantic model. Required fields (`id`, `name`, `inputs`, `outputs`) are
present. No unknown top-level keys (the model is `extra="forbid"`).

**Common failures:** trailing commas (not valid JSON), using `label`
instead of `description` on a secret, unknown fields.

## 3. `schemas_coherent`

**Verifies:**

- Every input `key` is unique within `inputs`; every output `key`
  unique within `outputs`.
- Every `type` is one of the supported types.
- Type-specific required fields are present (e.g. `select` has
  `options`, `slider` has `min`/`max`, `autocomplete` has `endpoint`).
- Any input's `show_if.key` references another existing input key.

Collects **all** schema problems before failing — you see the full list,
not just the first.

## 4. `pyproject_ok`

**Verifies:** `pyproject.toml` parses and declares `fastapi`,
`uvicorn`, and `python-dotenv` in `[project.dependencies]`.

## 5. `venv_functional`

**Verifies:** `.venv/bin/python --version` (or `Scripts\python.exe` on
Windows) succeeds.

**Note:** The validator does **not** run `uv sync` itself. If the venv
is missing, the report says so and stops. The skill that created or
updated the tool is responsible for running `uv sync`.

## 6. `tool_spawns`

**Verifies:** The tool process starts and `GET /healthz` returns 200
within 30 seconds.

The validator spawns the tool the same way the launcher does:

```bash
cd tools/<id> && .venv/bin/python main.py --port <port>
```

Captures stderr to `spawn_log` for inclusion in the report.

## 7. `schema_matches_disk`

**Verifies:** `GET /schema` from the running tool deep-equals the
parsed `tool.json` on disk. Drift produces a **`warn`** with a diff —
the running tool may not crash, but the renderer and the wire schema
have to agree or you'll get weird inputs.

## 8. `sample_input_run`

**Verifies:** The validator generates sample inputs (see [the
validator concept page](/Pixie/concepts/validator/#how-sample-inputs-are-generated)),
POSTs them to `/run`, and expects a 200 response within
`max_runtime_seconds + 5` from `tool.json`.

Failure modes: 5xx response (exception in tool), 4xx response (input
shape mismatch), timeout.

For tools with `layout: "chat"`, the validator sends a synthetic
`{messages: [{role:"user", content:"Validation probe"}], history: []}`
instead.

## 9. `output_conforms`

**Verifies:** Every declared output `key` is present in the response.
Each value's shape matches its declared type per the
`_OUTPUT_OBJECT_REQUIREMENTS` map (e.g. `chart_line` requires `x` and
`series`; `table` requires `columns` and `rows`).

**Extra keys** are warnings, not failures — the renderer ignores
unknown keys, but you probably meant something.

## 10. `streaming_check`

**Skipped** if no output declares `streaming: true`.

**Verifies:** A `GET /stream?run_id=<id>` connection emits at least one
SSE event within 10 seconds.

The validator doesn't verify event correctness in detail — that's check
12's job if you want it.

## 11. `clean_shutdown`

**Verifies:** SIGTERM to the tool process leads to exit within 5
seconds. If not, SIGKILL is sent and a **warn** is recorded — the tool
runs but cleanup is sloppy.

## 12. `reference_fixtures_match` (optional)

**Skipped** unless `tools/<id>/reference/fixture_*.json` files exist.

**Verifies:** For each fixture file, POSTs the `inputs`, captures the
response, and compares against `expected_outputs` with type-aware
comparators:

- `number` — absolute and relative tolerance (overridable per-key via
  `reference/tolerance.yaml`).
- `text`, `markdown` — exact string match.
- `table`, `kv` — per-row / per-key compare with numeric tolerance.
- `chart_*` — series shape + numeric tolerance on `y` and `points`.
- `image` — size + SHA-256 by default; histogram distance if
  `scikit-image` is installed.
- `audio` — size + SHA-256 by default; spectral distance if `librosa`.
- `file` (PDF) — size + SHA-256 by default; text diff if `pdfplumber`.

Install heavy comparators with:

```bash
uv sync --extra accuracy
```

Without them, binary outputs are compared by SHA-256 only — exact-match
for deterministic tools, useless for stochastic ones. The validator
flags this with a `warn`.

## Overall status

- All `pass`/`skip` → overall `pass`.
- Any `warn` (no fails) → overall `warn` — runnable but worth a look.
- Any `fail` → overall `fail` — tool is blocked.

The sidebar dot reflects `overall`:

- <span class="dot pass"></span> `pass`
- <span class="dot warn"></span> `warn`
- <span class="dot fail"></span> `fail`
- <span class="dot dormant"></span> never validated yet

## The report shape

```python
class ValidationCheck:
    name: str                          # e.g. "schema_matches_disk"
    status: Literal["pass", "fail", "warn", "skip"]
    message: str                       # one line, human-readable
    details: str | None                # multi-line stderr, diffs, traces

class ValidationReport:
    tool_id: str
    tool_path: str
    timestamp: datetime
    overall: Literal["pass", "fail", "warn"]
    checks: list[ValidationCheck]
    sample_inputs: dict | None         # what was POSTed
    sample_output: dict | None         # what came back
    spawn_log: str | None              # captured stderr if any
```

Persisted in the `validation_reports` table. Retrieved by
`uv run pixie validate <id> --json` and the `/api/tools/<id>/validate`
endpoint.
