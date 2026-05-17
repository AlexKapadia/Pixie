---
title: CLI
description: Every pixie subcommand with flags and examples.
sidebar:
  order: 1
---

Pixie's CLI is built with `typer` and lives in `pixie/__main__.py`. The
console-script entry `pixie` is declared in `pyproject.toml` and points
at `pixie.__main__:main`.

## pixie serve

The default. Boot the FastAPI app on `127.0.0.1:<port>`.

```bash
uv run pixie serve [--port PORT]
```

| Flag           | Default                  | Notes                                 |
| -------------- | ------------------------ | ------------------------------------- |
| `--port`, `-p` | `7860` or `$PIXIE_PORT`  | TCP port. Must be unbound on loopback.|

Equivalent to just `uv run pixie`.

## pixie dev

Developer mode — watch files for changes, hot-reload on Python edits,
debug logging, `PIXIE_DEVELOPER_MODE=1`, hover-prewarm enabled.

```bash
uv run pixie dev [--port PORT] [--no-browser]
```

| Flag           | Default | Notes                                                  |
| -------------- | ------- | ------------------------------------------------------ |
| `--port`, `-p` | `7860`  | TCP port.                                              |
| `--no-browser` | `false` | Don't open the dashboard in your browser on boot.      |

## pixie validate

Run the 11-check validator on one tool (plus optional check 12 if a
`reference/` folder is present).

```bash
uv run pixie validate <tool_id> [flags]
```

| Flag                | Default | Effect                                                                  |
| ------------------- | ------- | ----------------------------------------------------------------------- |
| `--tools-dir`       | `tools` | Override where to look for the tool.                                    |
| `--json`            | off     | Emit the full report as JSON on stdout. Use in scripts / CI.            |
| `--summary`         | off     | Print only non-pass checks (token-efficient for agents).                |
| `--no-save`         | off     | Don't persist the report to `validation_reports`.                       |
| `--export-check`    | off     | Also run check 12 even without `--reference-only`.                      |
| `--reference-only`  | off     | Skip checks 1–11. Run only check 12 against reference fixtures.         |
| `--fixture FILE`    | none    | Run only the named fixture file.                                        |
| `--tag TAG`         | none    | Run only fixtures with this tag (in their JSON).                        |
| `--update-fixtures` | off     | Run the tool with sample inputs and overwrite reference fixtures.       |
| `--yes`             | off     | Required to confirm `--update-fixtures` (destructive).                  |

Exit code: 0 on `pass` or `warn`, 1 on `fail`.

```bash
uv run pixie validate lorenz-ode-solver
uv run pixie validate lorenz-ode-solver --summary
uv run pixie validate lorenz-ode-solver --json | jq '.checks[]'
uv run pixie validate lorenz-ode-solver --reference-only
uv run pixie validate lorenz-ode-solver --update-fixtures --yes
```

## pixie tail

Stream a warm tool's stderr ring buffer (default 64 KiB), or list its
recent artefacts.

```bash
uv run pixie tail <tool_id> [--lines N] [--artefacts] [--port PORT]
```

| Flag             | Default | Effect                                          |
| ---------------- | ------- | ----------------------------------------------- |
| `--lines`, `-n`  | `50`    | Last N lines from the ring buffer.              |
| `--artefacts`    | off     | List recent artefacts instead of stderr.        |
| `--port`, `-p`   | `7860`  | Connect to Pixie on this port.                  |

## pixie open

Open a tool's folder in the OS file browser.

```bash
uv run pixie open <tool_id>
```

Windows: Explorer. macOS: Finder. Linux: `xdg-open`.

## pixie sweep

Run the retention sweeper. Reports / prunes runs and artefacts older
than `--older-than`, sparing starred and labelled ones.

```bash
uv run pixie sweep [--dry-run | --apply] [--older-than SPEC] [--tool ID]
```

| Flag             | Default      | Effect                                                          |
| ---------------- | ------------ | --------------------------------------------------------------- |
| `--dry-run`      | **on**       | Report what would be deleted; commit nothing.                   |
| `--apply`        | off          | Actually delete.                                                |
| `--older-than`   | `30d`        | Duration spec. Accepts `d`, `h`, `m` suffixes (e.g. `7d`, `24h`).|
| `--tool`         | all          | Limit to one tool.                                              |

Always start with `--dry-run`. Once happy with what you see, add
`--apply`.

## pixie artefacts

List a tool's artefacts (Wave 2).

```bash
uv run pixie artefacts <tool_id>
```

## pixie scaffold-tool

Generate a starter tool from a template under
`pixie/templates_scaffold/<name>/`.

```bash
uv run pixie scaffold-tool <tool_id>
```

Usually you'll want a Claude Code skill (e.g. `add-tool-from-description`)
instead — `scaffold-tool` is the lowest-level option.

## Common patterns

### CI: validate every tool

```bash
for d in tools/*/; do
  id=$(basename "$d")
  uv run pixie validate "$id" --summary || exit 1
done
```

### Get a JSON report and assert overall == pass

```bash
status=$(uv run pixie validate compound-interest --json | jq -r '.overall')
if [ "$status" != "pass" ]; then
  echo "Validation failed"; exit 1
fi
```

### Tail logs while running

```bash
# In one terminal
uv run pixie

# In another
uv run pixie tail whisper-transcription --lines 200
```
