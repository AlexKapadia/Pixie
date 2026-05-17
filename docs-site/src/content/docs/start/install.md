---
title: Install & first run
description: Clone, install dependencies, and open the dashboard.
sidebar:
  order: 2
---

import { Tabs, TabItem, Steps } from "@astrojs/starlight/components";

You need Python 3.12+ and [`uv`](https://docs.astral.sh/uv). That's it.

## Prerequisites

<Tabs>
<TabItem label="macOS / Linux">

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Verify
uv --version
python3 --version  # 3.12 or newer
```

</TabItem>
<TabItem label="Windows (PowerShell)">

```powershell
# Install uv
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Verify
uv --version
python --version  # 3.12 or newer
```

</TabItem>
</Tabs>

If `python` is older than 3.12, `uv` can install a managed 3.12 for you:

```bash
uv python install 3.12
```

## Install Pixie

<Steps>

1. **Clone the repo.**

   ```bash
   git clone https://github.com/alexanderkapadia/pixie.git
   cd pixie
   ```

2. **Install dependencies.** `uv sync` reads `pyproject.toml` and creates
   `.venv/` in the repo root with everything Pixie needs.

   ```bash
   uv sync
   ```

3. **Run Pixie.**

   ```bash
   uv run pixie
   ```

   You should see something like:

   ```text
   Pixie listening on http://127.0.0.1:7860
   Discovered 12 tools in ./tools
   ```

4. **Open the dashboard.** Browse to <http://localhost:7860>. The example
   tool (compound-interest) is already in the sidebar with a green dot.

</Steps>

## What you should see on first run

- A left sidebar listing every tool under `tools/`, grouped by category, with
  a coloured dot next to each name:
  - <span class="dot pass"></span> **Green** — validator passed, ready to run.
  - <span class="dot warn"></span> **Yellow** — validator warned (e.g. slow shutdown), still runnable.
  - <span class="dot fail"></span> **Red** — validator failed, clicking shows the report instead of spawning.
  - <span class="dot dormant"></span> **Grey** — never spawned, not yet warm.
- A header showing the active tool's name, description, and a "running" /
  "dormant" pill.
- A main area split by the tool's declared layout (form, chat, or split).

If the sidebar is empty, see [Troubleshooting → empty sidebar](/Pixie/help/troubleshooting/#empty-sidebar).

## Next

- [Run the example compound-interest tool →](/Pixie/start/example-tool/)
- [Add your first real tool via Claude Code →](/Pixie/start/first-tool/)
