---
title: Tests
description: What the test suite covers, how it's organised, and how to add tests.
sidebar:
  order: 5
---

The test suite lives at `tests/`. Run everything with `uv run pytest`.

## Layout

```text
tests/
+-- conftest.py                  # shared fixtures
+-- unit/                        # fast, no subprocesses
+-- integration/                 # live FastAPI server + httpx
+-- visual/                      # Playwright pixel-diff (heavy)
+-- perf/                        # pytest-benchmark (heavy)
+-- a11y/                        # axe-core via Playwright (heavy)
+-- e2e/                         # full browser flows (heavy)
+-- format/                      # exporter round-trip
+-- fixtures/                    # test tools (reference-tool, broken-tool, etc.)
```

## What's covered

### Unit (`tests/unit/`)

| Test file                  | What it covers                                                                |
| -------------------------- | ----------------------------------------------------------------------------- |
| `test_discovery.py`        | Tool schema parsing, validation errors, optional fields, error recovery.      |
| `test_validator.py`        | Sample input generation, output-shape checking, report summarisation.         |
| `test_db.py`               | Schema init, WAL pragmas, CRUD round-trips on all 9 tables.                   |
| `test_launcher.py`         | Free-port allocation, env scrubbing, warm-keep bookkeeping (no real spawn).   |
| `test_artefacts.py`        | `safe_join` traversal refusal, sha256 hashing, mime inference, soft-delete.   |
| `test_workspaces.py`       | Workspace CRUD + tool assignment + cascade delete.                            |
| `test_secrets.py`          | `.env` round-trip, masking filter behaviour, atomic writes.                   |
| `test_renderer_inputs.py`  | Every input partial renders without errors against a fixture spec.            |
| `test_renderer_outputs.py` | Every output partial renders given valid value shapes.                        |
| `test_reference_validator.py` | Check 12 with scikit-image / librosa / pdfplumber comparators.             |
| `test_exporters.py`        | Round-trips for CSV, Excel, Parquet, PDF.                                     |
| `test_comparators.py`      | Numeric tolerance, structured diff, SHA-256 short-circuit.                    |
| `test_proxy.py`            | Routing, header injection, run-id flow.                                       |

### Integration (`tests/integration/`)

| Test file                  | What it covers                                                                |
| -------------------------- | ----------------------------------------------------------------------------- |
| `test_run_flow.py`         | Boot server, `GET /api/tools`, `POST /tool/<id>/run` against staged example.  |
| `test_streaming.py`        | SSE round-trip from a streaming tool.                                         |
| `test_cancel.py`           | Cancel flow via the proxy.                                                    |
| `test_settings.py`         | Settings API + env-var overrides.                                             |
| `test_secrets_flow.py`     | Secrets injection into subprocess environment.                                |
| `test_library.py`          | Artefact gallery listing and filters.                                         |
| `test_reference_check.py`  | Full reference fixture validation against real tools.                         |
| `test_tools_grid.py`       | Discovery across multiple tools, sorting, filtering.                          |
| `test_workspaces.py`       | Workspace endpoints, membership ops.                                          |

### Heavy markers

Skipped by default. Enable with `PIXIE_RUN_HEAVY_TESTS=1`:

| Marker     | Cost  | What it does                                                          |
| ---------- | ----- | --------------------------------------------------------------------- |
| `visual`   | ~30s  | Playwright launches Chromium, screenshots key pages, pixel-diffs.     |
| `perf`     | ~60s  | `pytest-benchmark` budgets cold-start, warm run, sidebar render.      |
| `a11y`     | ~30s  | axe-core audits each page for WCAG violations.                        |
| `e2e`      | ~90s  | Full browser flows against the staged example tool.                   |

## Fixtures (`tests/conftest.py`)

| Fixture                | Type     | Purpose                                                              |
| ---------------------- | -------- | -------------------------------------------------------------------- |
| `tmp_pixie_root`       | session  | Scratch repo layout with `tools/` and a fresh `pixie.db`.            |
| `sample_tool_factory`  | function | Copies a tool from `tests/fixtures/<name>/` into `tmp_pixie_root`.   |
| `staged_example_tool`  | function | The `example-compound-interest` tool with its venv pre-built.        |
| `pixie_app`            | function | A fresh FastAPI app instance bound to the temp root.                 |
| `pixie_server`         | function | The above served on a real localhost port via uvicorn.               |
| `httpx_client`         | function | `httpx.AsyncClient` pointed at the server.                           |
| `mock_validator_report`| function | Synthetic `ValidationReport` for UI tests.                           |
| `db_path`              | function | Initialised `pixie.db` at tmp_path (workspace tests).                |

## Adding tests

### A new unit test for a function

Add a file under `tests/unit/test_<topic>.py`:

```python
import pytest
from pixie.validator import _sample_for_input
from pixie.discovery import TextInput

@pytest.mark.parametrize("default,expected", [
    (None, ""),
    ("hello", "hello"),
])
def test_text_input_sample(default, expected):
    spec = TextInput(type="text", key="x", label="X", default=default, required=True)
    assert _sample_for_input(spec) == expected
```

### A new integration test against a tool

```python
async def test_my_tool_runs(staged_example_tool, httpx_client):
    response = await httpx_client.post(
        "/tool/example-compound-interest/run",
        data={"principal": 1000, "annual_rate": 5, "years": 10}
    )
    assert response.status_code == 200
```

### A new fixture tool

Put it under `tests/fixtures/<name>/`. Minimal:

```text
tests/fixtures/my-fixture/
+-- tool.json
+-- pyproject.toml
+-- main.py
```

Then in your test:

```python
def test_my_fixture(sample_tool_factory):
    tool_path = sample_tool_factory("my-fixture")
    ...
```

`sample_tool_factory` returns the path of the copied tool; the venv is
NOT created (your test should not need one).

## CI

GitHub Actions runs:

- `uv run pytest -m "not (perf or visual or a11y or e2e)"` per push.
- Heavy markers nightly.
- `ruff format --check` and `ruff check`.
- The validator over a curated subset of tools.

Failures block merge.
