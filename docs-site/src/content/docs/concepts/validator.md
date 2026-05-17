---
title: The validator
description: 11 deterministic checks that gate every tool, plus an opt-in 12th for reference fixtures.
sidebar:
  order: 3
---

The validator is the **single source of truth** for "is this tool well-formed
and working." It's read-only — it never modifies the tool, only inspects.

You invoke it three ways:

- **Python:** `validator.validate_tool(tool_path) -> ValidationReport`
- **CLI:** `uv run pixie validate <tool_id>`
- **HTTP:** `GET /api/tools/<id>/validate`

All three return the same `ValidationReport` shape.

## The 11 checks

The validator runs checks in order. Schema checks (1–4) collect all
problems before stopping. Spawn checks (6–11) stop at the first failure
because later checks depend on earlier ones (you can't validate `/schema`
output if the process didn't start).

| #  | Check                   | What it verifies                                                              |
| -- | ----------------------- | ----------------------------------------------------------------------------- |
| 1  | folder_structure        | `tool.json`, `pyproject.toml`, `main.py` exist; no weird permissions.         |
| 2  | tool_json_parses        | Valid JSON; matches the Pydantic `ToolManifest` model; no unknown top fields. |
| 3  | schemas_coherent        | Unique keys; valid types; type-specific required fields; `show_if` resolves.  |
| 4  | pyproject_parses        | Parses; declares `fastapi`, `uvicorn`, `python-dotenv` at minimum.            |
| 5  | venv_functional         | `.venv/` exists; `python --version` succeeds. (Validator never runs uv sync.) |
| 6  | tool_spawns             | Process starts; `/healthz` returns 200 within 30 s.                           |
| 7  | schema_matches_disk     | `/schema` response equals parsed `tool.json` (drift fails).                   |
| 8  | sample_input_run        | Sample inputs from defaults; `/run` returns 200 within `max_runtime_seconds`. |
| 9  | output_conforms         | Every declared output key present; value shape matches type; no extra keys.  |
| 10 | streaming_check         | If any output `streaming: true`, `/stream` emits ≥1 event within 10 s.        |
| 11 | clean_shutdown          | SIGTERM → exit within 5 s, else SIGKILL (recorded as warn).                   |
| 12 | reference_fixtures      | Opt-in. Reference outputs compared with type-aware comparators.               |

## How sample inputs are generated

For check 8, the validator builds a single set of sample inputs from the
declared schema. The rules:

- `default` field present → use it.
- Otherwise:
  - `text`, `textarea` → empty string `""`
  - `number`, `slider` (non-range) → `(min + max) / 2`, or `0` if no min/max
  - `slider` with `range: true` → `[min, max]`
  - `select`, `radio` → first option's `value`
  - `multiselect` → empty list `[]`
  - `checkbox`, `toggle` → `false`
  - `date` → today
  - `time` → `"00:00"`
  - `datetime` → now
  - `date_range` → `[today, today]`
  - `file`, `image`, `audio` → a 1x1 transparent PNG / 1-second silent WAV
    encoded as a data URL
  - `colour` → `"#000000"`
  - `json` → `{}`
  - `code` → `""` (empty source)
  - `markdown` → `""`
  - `tags` → `[]`
  - `table` → empty list `[]`
  - `map_point` → centre coords if declared; else `(0, 0)`
  - `map_bbox` → small box around centre
  - `map_polygon`, `map_multipoint` → empty lists
  - `hidden` → `default` (must be present, otherwise check 3 already failed)

Inputs marked `required: false` with no default are **omitted** from the
sample body — the validator tests the most-zero-effort happy path.

## Output conformance

Check 9 walks the response against an internal `_OUTPUT_OBJECT_REQUIREMENTS`
map that knows the required shape per output type. For example:

| Output type      | Required keys in value                                          |
| ---------------- | --------------------------------------------------------------- |
| `number`         | `value: number` (optional `format`, `precision`, `unit`)        |
| `table`          | `columns: list`, `rows: list`                                   |
| `chart_line`     | `x: list[number]`, `series: list[{name, y: list[number]}]`      |
| `chart_scatter`  | `series: list[{name, points: list[{x, y, label?}]}]`            |
| `map_points`     | `points: list[{lat, lng, label?, colour?}]`                     |
| `image`          | `value: str` (data URL or http(s) URL)                          |
| `log`            | `lines: list[{level, message, t}]`                              |
| `file`           | `filename: str`, `data: str`, `mime_type: str`                  |

Missing required keys → `fail`. Extra keys → `warn` (your output schema may
have drifted; the renderer ignores them but it's worth knowing).

## The report shape

```python
class ValidationCheck(BaseModel):
    name: str                          # e.g. "schema_matches_disk"
    status: Literal["pass", "fail", "warn", "skip"]
    message: str                       # one line, human-readable
    details: str | None = None         # multi-line stderr, diffs, traces

class ValidationReport(BaseModel):
    tool_id: str
    tool_path: str
    timestamp: datetime
    overall: Literal["pass", "fail", "warn"]
    checks: list[ValidationCheck]
    sample_inputs: dict | None = None
    sample_output: dict | None = None
    spawn_log: str | None = None
```

The `overall` is computed:

- Any `fail` → overall `fail`
- Any `warn` (no fails) → overall `warn`
- All `pass`/`skip` → overall `pass`

## How the dashboard uses it

Discovery consults the cached latest report from the `validation_reports`
table:

- <span class="dot pass"></span> **`pass`** — sidebar entry is green, click
  spawns the tool normally.
- <span class="dot warn"></span> **`warn`** — sidebar entry is yellow, click
  still spawns; the warnings are shown in a "details" disclosure.
- <span class="dot fail"></span> **`fail`** — sidebar entry is red, click
  shows the **report**, not the tool's UI. There's a "Re-validate" button.

The settings page for each tool has a "Re-validate" button that runs the
validator on demand and shows the new report.

## When skills must surface the report

Every skill that creates or modifies a tool ends with a validator call.
The skill **must not claim success** if `overall == "fail"`. Specifically:

- `add-tool-from-description`, `add-tool-from-repo`, `wrap-local-script`,
  `add-tool-from-notebook`, `convert-streamlit-app`, `convert-gradio-app`,
  `add-tool-from-cli-command`, `add-tool-from-openapi-spec`,
  `add-tool-from-excel-model`, `add-tool-from-paper`,
  `implement-model-from-spec` — all end with a validator call and surface
  the full report.
- `update-tool`, `debug-tool`, `migrate-tool-format`, `organise-tool`,
  `fork-tool`, `rename-tool` — re-run the validator after their change.

Read more: [Skills overview](/Pixie/skills/overview/).

## What the validator does not do

- It does not run user-specified tests. Bring your own `pytest` files
  inside the tool folder — the validator ignores them. (Out of scope for
  the validator's responsibility.)
- It does not test correctness of logic. Check 8 verifies the **contract**
  is honoured, not that the answer is right. Use reference fixtures
  (check 12) for that.
- It does not retry on transient failures. A flaky tool is a broken tool.
- It does not modify the tool. If a check fails, the report explains
  what's wrong; the skill (or you) does the fix.

## Reading the report

In the terminal, `uv run pixie validate <id>` gives you a rich table with
coloured status icons and one-line messages. For machine consumption,
`--json` returns the full structured report.

`--summary` keeps only the non-`pass` rows, which is the right default in
agent contexts where every token matters.

```bash
uv run pixie validate lorenz-ode-solver --summary
uv run pixie validate lorenz-ode-solver --json | jq '.checks[]'
uv run pixie validate lorenz-ode-solver --reference-only      # only check 12
```

See [Validator checks reference](/Pixie/reference/validator-checks/) for
the exhaustive table.
