# Graveyard Sweep — 2026-05-18

Branch: `master-prompt-fixes`. Three commits, all `chore(graveyard):`.
App boots clean (70 routes), unit suite passes (732/733, the 1 failure is
unrelated and pre-existing — see "Pre-existing issues" below).

## Deleted

### Commit `1ae82d3` — 25 unused imports
- `pixie/config.py`: `pydantic.Field`
- `pixie/exporters/__init__.py`: `json`
- `pixie/exporters/maps.py`: `ExporterMissingDependency`
- `pixie/exporters/media.py`: `os`
- `pixie/exporters/table.py`: `ExporterError`
- `pixie/exporters/text.py`: `pathlib.Path`, `ExporterError`, `coerce_path`
- `pixie/routes/_coerce.py`: `DateRangeInput`, `JsonInput`, `MapBboxInput`,
  `MapMultipointInput`, `MapPointInput`, `MapPolygonInput`, `TableInput`,
  `TagsInput`
- `pixie/routes/artefacts.py`: `json`, `fastapi.Body`,
  `fastapi.responses.JSONResponse`
- `pixie/routes/exports.py`: `asyncio`, `pathlib.Path`, `fastapi.Body`
- `pixie/validator.py`: `ReferenceFixture`, `ToleranceConfig`,
  `list_reference_fixtures`

Net: 20 deletions, 0 insertions of substance (one `import` line collapsed).

### Commit `e24480c` — phase-4b stub templates + dead module (19 lines)
- `pixie/templates/chat.html` (6 lines) — `<h1>` stub for the unimplemented
  chat layout. Tools that declare `layout='chat'` instead fall through to
  the placeholder div in `tool.html` and `tool_fragment.html`.
- `pixie/templates/partials/input_form.html` (2 lines) — literal
  `<form></form>` with TODO. Real input form rendering lives in
  `pixie/renderer/inputs.py` which dispatches to
  `partials/inputs/<type>.html` directly.
- `pixie/renderer/layouts.py` (11 lines) — docstring + TODO comment, no
  symbols defined, no importers.

### Commit `0702a18` — phase-6 output stub (2 lines)
- `pixie/templates/partials/output_panel.html` — literal `<section></section>`
  TODO. Real output rendering goes through `pixie/renderer/outputs.py` →
  `partials/outputs/<type>.html`.

### Untracked scratch (working tree only, never committed)
- `_smoke_themes.py` — one-off TestClient probe from a prior session
- `README-stub.md` — superseded by the real `README.md` on this branch

## Kept on purpose (looked dead, isn't)

- **`pixie/templates/partials/inputs/*.html`** — initial orphan scan flagged
  17 of these because nothing greppably references the filenames. They are
  loaded dynamically by `pixie/renderer/inputs.py` via
  `_env.get_template(f"{type_}.html")` where `type_` is whatever
  `InputSpec.type` says. Every committed partial maps to a class in
  `pixie/discovery.py`. All live.
- **`pixie/templates/partials/errors/*.html`** — same pattern. Loaded by
  `pixie/routes/tool.py:_render_error(kind=...)`. All 6 kinds (`run`,
  `schema`, `spawn`, `timeout`, `validation`, `venv`) are reachable —
  `schema` via `tool_parse_error.html`, the others via direct
  `_render_error` calls.
- **`pixie/exporters/*.py` and `pixie/comparators/*.py` submodules** —
  loaded via `pkgutil.iter_modules` (exporters) or explicit `from .X import`
  in `__init__.py` (comparators). Don't grep, walk the registry.
- **`KILL_FILE.md` machinery** in `pixie/validator.py` (`_KILL_FILE_PATH`,
  `_parse_kill_file`, `_check_kill_file_unaddressed`) — looks like a kill
  switch but it's a live validator extension that cross-references
  KILL-NNNN bug entries against failing checks.

## Flagged for human review (not deleted)

### Stale-looking `@pytest.mark.skip` placeholders
All four say "Wave 2: ... coverage" with no date, no ticket:
- `tests/integration/test_cancel.py:12`
- `tests/integration/test_library.py:11`
- `tests/integration/test_secrets_flow.py:12`
- `tests/integration/test_streaming.py:13`

Each file is a single `def test_...(): pass` stub. Either implement Wave 2
or delete the files — leaving them as silently-skipped tests rots.

### Half-finished partial that IS wired in
- `pixie/templates/partials/run_history.html` is literally `<ul></ul>` with
  a phase-7 TODO, but it IS rendered every run via `pixie/routes/tool.py:164`
  (the OOB swap after a successful run). The render emits nothing visible.
  Decide: implement the dropdown, or remove the OOB render call and the
  partial together. I did not touch this because removing the render call
  changes route behaviour.

### In-context TODOs (not dead, just unfinished)
- `pixie/config.py:87` — `# TODO(phase-3a): wire get_settings() into the app
  factory's lifespan` (the settings ARE wired; this comment is stale)
- `pixie/templates/tool.html:12` — `TODO: wire Re-run button` (UI affordance
  noted, not blocking)

### Untracked dev scratch directories (gitignored sibling-pattern dirs that
escape the existing rules; not mine to delete)
- `.design_pkg/pixie/` — design exploration package
- `.theme-test-shots/` — playwright theme-grid screenshots + a small JS
  harness (`theme-test.js`, `theme-test-v2.js`, `diagnose-cutoff.js`,
  `inspect-page.js`, `results.json`, `server*.log`)

Both look like prior-session output. If you don't need them, `rm -rf`. If
you want them gone permanently, add `.design_pkg/` and `.theme-test-shots/`
to `.gitignore`.

### Top-level cruft confirmed safe / already handled
- `Master Prompt.md`, `DESKTOP_APP_PLAN.md`, `pixie.db*`, `artefacts/`,
  `*.log`, `node_modules/`, `.venv/` — all already gitignored. No action.
- `Pixie.mp4`, `Pixie Logo.png`, `docs/`, `LICENCE`, `pyproject.toml`,
  `uv.lock`, `CONTRIBUTING.md` — all real, all tracked, all keep.

## Pre-existing issues surfaced (NOT introduced by this sweep)

- `tests/unit/test_cli.py` errors on collection: `ModuleNotFoundError: typer`.
  `typer` isn't a declared test dep but the CLI uses it. Either add it to
  dev deps or guard the import.
- `tests/unit/test_validator_extended.py::test_check_pyproject_picks_up_dependencies`
  fails because `_check_pyproject` now requires `pydantic` in tool deps but
  the test fixture only declares `fastapi`, `uvicorn`, `python-dotenv`. The
  validator changed; the test didn't.

## Net result

- 4 source files deleted
- 25 unused imports removed
- 0 behaviour changes
- 0 test regressions introduced
- 1 stub partial (`run_history.html`) and 4 skipped integration tests flagged
  for follow-up
