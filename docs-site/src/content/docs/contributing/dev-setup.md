---
title: Dev environment
description: Get a working dev environment in 5 minutes.
sidebar:
  order: 2
---

import { Tabs, TabItem, Steps } from "@astrojs/starlight/components";

<Steps>

1. **Clone and install dev deps.**

   ```bash
   git clone https://github.com/AlexKapadia/Pixie.git
   cd pixie
   uv sync --extra dev
   ```

   `--extra dev` pulls in `pytest`, `pytest-asyncio`, `pytest-benchmark`,
   `playwright`, `pillow`, and `ruff`.

2. **Install the example tool's venv.** Pixie's tests use the
   example-compound-interest tool as a fixture; it needs its own venv.

   ```bash
   cd tools/example-compound-interest
   uv sync
   cd ../..
   ```

3. **Run Pixie in dev mode.** Hot reload on Python file changes.

   ```bash
   uv run pixie dev --no-browser
   ```

   Visit <http://localhost:7860>.

4. **Run the tests.**

   ```bash
   uv run pytest                     # unit + integration
   PIXIE_RUN_HEAVY_TESTS=1 uv run pytest -m perf     # benchmarks
   PIXIE_RUN_HEAVY_TESTS=1 uv run pytest -m visual   # Playwright pixel-diff
   PIXIE_RUN_HEAVY_TESTS=1 uv run pytest -m a11y     # axe accessibility
   PIXIE_RUN_HEAVY_TESTS=1 uv run pytest -m e2e      # full browser flows
   ```

   Heavy markers are off by default so a fresh clone runs fast.

5. **Lint and format.**

   ```bash
   uv run ruff format .
   uv run ruff check .
   ```

</Steps>

## Recommended editor setup

- **VS Code** with the Python and Ruff extensions. The repo doesn't
  ship a `settings.json` because preferences vary, but `format on save`
  with Ruff is the team default.
- **Type checking.** `pyright` runs in CI; no strict-mode obligation
  in editors, but cleaning up type errors as you go is the path of
  least resistance.

## Working on the frontend

Pixie has **no JS build step**. To work on the UI:

1. Edit `pixie/templates/**/*.html` for Jinja partials.
2. Edit `pixie/static/pixie.css` for styles.
3. Edit `pixie/static/pixie.js` or `pixie-inputs.js` for JS helpers.
4. Refresh the browser — that's it.

Static assets aren't fingerprinted in dev mode, so a hard refresh
(`Ctrl+Shift+R` / `Cmd+Shift+R`) clears the browser cache if you don't
see changes.

## Common dev tasks

### Add a new tool while developing

Use the skill library in Claude Code as normal. If you're testing the
skill itself, run it against a throwaway test repo first.

### Re-validate every tool after a runtime change

```bash
for d in tools/*/; do
  uv run pixie validate "$(basename "$d")" --summary
done
```

### Drop the database

```bash
rm pixie.db pixie.db-wal pixie.db-shm
uv run pixie  # init_db() rebuilds the schema on next boot
```

### Wipe artefacts

```bash
rm -rf artefacts/
```

Existing runs in `pixie.db` will have their artefact links dangle —
either drop the DB too, or just live with it.

### Inspect what's warm

```bash
curl -s http://127.0.0.1:7860/api/launcher/state | jq
```

Developer mode only. Toggle it in `.env`:

```bash
echo "PIXIE_DEVELOPER_MODE=true" >> .env
```

## CI

GitHub Actions runs (on every push):

- `ruff format --check`
- `ruff check`
- `uv run pytest -m "not (perf or visual or a11y or e2e)"`
- A subset of tools' validators

The heavy markers run on a nightly schedule, not per-PR.
