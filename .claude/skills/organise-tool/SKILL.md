---
name: organise-tool
description: Restructures one Pixie tool's internal Python files into the src/ layout, adding tests/, notebooks/, CHANGELOG skeletons, then re-validates. Use when the user asks to organise, tidy, refactor, restructure, or clean up a tool's files or layout. Do NOT use to change inputs (update-tool), rename (rename-tool), or fix broken (debug-tool).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Organise a Pixie tool's internal layout

You are restructuring ONE tool's on-disk Python layout to match Pixie's recommended `src/` shape. You move loose `.py` files into `src/<package>/`, add `tests/`, `notebooks/`, and `CHANGELOG.md` skeletons where missing, fix the entrypoint's imports to match the new package path, and update `pyproject.toml` for the src-layout build. You do NOT change the tool's inputs, outputs, behaviour, or dependencies — that is `update-tool`'s job.

## Routing check (do this first)

- If the user wants to change a tool's behaviour, inputs, outputs, or dependencies, switch to `update-tool` instead.
- If the user wants to rename the tool itself, switch to `rename-tool` instead.
- If the tool is broken, failing, or crashing, switch to `debug-tool` instead.
- If the user says "every tool" or "all tools", refuse — this skill operates on one tool at a time.
- If the tool has fewer than 2 `.py` files loose at the tool root (i.e. only `main.py`), there is nothing to organise. Surface the refusal block and stop.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Read before you act

- `tools/example-compound-interest/tool.json`
- `tools/example-compound-interest/main.py`
- `tools/example-compound-interest/pyproject.toml`

These are the canonical Pixie tool shape. Match them.

## Steps

### 1. Identify the tool and inspect its layout

If the user did not name a tool, `Glob` `tools/*/tool.json` and ask which one. Then enumerate the tool's current layout:

```bash
ls tools/<tool_id>
```

`Glob` `tools/<tool_id>/*.py` to count loose Python files at the tool root. If there are fewer than two, surface the refusal block at the bottom and stop.

`Read` `tools/<tool_id>/tool.json`, `tools/<tool_id>/main.py`, and `tools/<tool_id>/pyproject.toml`. Note the tool `id`, the entrypoint module name, and any existing `[tool.setuptools]` or `[tool.hatch.build]` configuration.

### 2. Propose the new layout

Print the proposed layout as a tree. The target shape is:

```
tools/<tool_id>/
  tool.json
  pyproject.toml
  README.md
  CHANGELOG.md
  main.py
  src/<package>/
    __init__.py
    <moved_module_1>.py
    <moved_module_2>.py
  tests/
    test_smoke.py
  notebooks/
    .gitkeep
```

`<package>` is the tool `id` converted from kebab-case to snake_case (e.g. `geocoder-uk` → `geocoder_uk`).

Ask the user to confirm the proposed move list before touching anything. List each source file and its destination path on a separate line. Wait for an explicit "yes".

### 3. Move each loose `.py` file

For each loose `.py` other than `main.py`, ask before moving:

> "Move `tools/<tool_id>/<file>.py` to `tools/<tool_id>/src/<package>/<file>.py`? (yes/no/skip)"

Skip the file on anything other than "yes". For files moved, use `Bash`:

```bash
mkdir -p tools/<tool_id>/src/<package>
git mv tools/<tool_id>/<file>.py tools/<tool_id>/src/<package>/<file>.py 2>/dev/null || mv tools/<tool_id>/<file>.py tools/<tool_id>/src/<package>/<file>.py
```

Prefer `git mv` so history is preserved if the tool is under git. Fall back to `mv` if not.

### 4. Create `src/<package>/__init__.py`

Empty file, one comment line:

```python
# Package root for the <tool_id> Pixie tool.
```

Use `Write`.

### 5. Fix imports in `main.py`

`Read` `main.py` again. For every moved module, find the old top-level import (`from <module> import ...` or `import <module>`) and rewrite it to `from <package>.<module> import ...` or `from <package> import <module>`. Use `Edit` for each rewrite. Show the user the before/after for each import before confirming.

If `main.py` uses a relative import like `from .helpers import x`, leave it alone — relative imports inside `main.py` are a different problem and out of this skill's scope.

### 6. Update `pyproject.toml` for src-layout

`Read` `pyproject.toml`. If it uses `[tool.setuptools.packages.find]`, ensure `where = ["src"]` is set. If it uses hatch, ensure `[tool.hatch.build.targets.wheel]` includes `packages = ["src/<package>"]`. If neither build backend block exists, add the minimal setuptools block:

```toml
[tool.setuptools.packages.find]
where = ["src"]
```

Use `Edit` to apply the change. Do NOT add new runtime dependencies.

### 7. Add `tests/test_smoke.py` if missing

If `tools/<tool_id>/tests/` does not exist or is empty, create a smoke test that imports the package and asserts the FastAPI app has the four required routes (`/schema`, `/healthz`, `/run`, plus one of `/stream` or `/cancel` if declared in `tool.json`).

The smoke test must not start `uvicorn` — it imports `app` from `main.py` and inspects `app.routes`.

### 8. Add `notebooks/.gitkeep` if missing

Empty file. Lets the user drop exploratory `.ipynb` files into a stable location without polluting the tool root.

### 9. Add `CHANGELOG.md` skeleton if missing

Use British English. Sentence case. Format:

```markdown
# Changelog

All notable changes to this tool are recorded here. Format follows Keep a Changelog.

## [Unreleased]

### Changed
- Restructured internal layout to src/<package>/.
```

### 10. Validator handoff (mandatory final step)

From the repo root:

```bash
uv run pixie validate <tool_id> --json
```

Parse the JSON. Branch on `overall`:

- `"pass"` — report success in one line. Surface any `warn` checks verbatim.
- `"warn"` — report success and list every check where `status == "warn"` verbatim, with `name`, `message`, and `details`.
- `"fail"` — DO NOT claim success. Output the entire JSON report verbatim in a fenced `json` block, then explain in plain language which checks failed and what the `message` and `details` mean. The most likely cause is an import that the rewrite missed. Offer to revert the move with `git checkout tools/<tool_id>/` if the tool is under git, then end with: "Would you like me to hand this off to the `debug-tool` skill?" Stop.

Hard stop after two consecutive failed runs. Surface both reports and stop iterating.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
There is nothing to organise here. `tools/<tool_id>/` has fewer than two loose `.py`
files at the tool root, so the recommended src/<package>/ layout would not change
anything meaningful. If you want to change the tool's behaviour, inputs, or outputs,
the right skill is `update-tool`.
```

## Do NOT

- Do NOT change the tool's `tool.json` inputs, outputs, secrets, or behaviour.
- Do NOT add or remove runtime dependencies in `pyproject.toml`.
- Do NOT rename the tool id or folder — that is `rename-tool`.
- Do NOT touch the `.venv/` or `data/` folder.
- Do NOT operate on more than one tool per invocation.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
