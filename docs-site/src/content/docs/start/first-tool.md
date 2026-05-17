---
title: Add your first tool
description: Use Claude Code to scaffold, validate, and ship a new tool in one sentence.
sidebar:
  order: 4
---

import { Tabs, TabItem, Aside } from "@astrojs/starlight/components";

The intended workflow for adding tools is: **say what you want in Claude
Code, and refresh the dashboard a minute later**. Pixie ships with five
skills (and many more in the wider library) that handle the scaffolding,
dependency install, and validation for you.

## From a natural-language description

Open the Pixie repo in Claude Code, then type:

```text
Add a Pixie tool that converts currencies using the Frankfurter API
```

This triggers the [`add-tool-from-description`](/Pixie/skills/add-tools/#add-tool-from-description)
skill, which:

1. Asks you any clarifying questions (what's the input — amount + currency
   codes? Should there be a target-currency picker? Does it need historic
   rates?).
2. Picks a kebab-case `id` like `currency-converter` and a human-readable
   name `Currency Converter`.
3. Writes `tools/currency-converter/tool.json` with the inputs and outputs.
4. Writes `tools/currency-converter/pyproject.toml` with `httpx` (for the
   API call) added to the default dependencies.
5. Writes `tools/currency-converter/main.py` — a FastAPI app honouring
   `/schema`, `/healthz`, and `/run`.
6. Runs `uv sync` inside the tool folder to build its `.venv`.
7. Runs `uv run pixie validate currency-converter`.
8. Surfaces the validation report verbatim. **If overall is `fail`, the skill
   reports failure** — it doesn't pretend success.

Refresh the dashboard, and `Currency Converter` appears in the sidebar.

## From a GitHub repository

Find a repo that does something useful (a CLI calculator, a model wrapper,
a data tool). In Claude Code, type:

```text
Add github.com/example/some-calculator as a Pixie tool
```

This triggers [`add-tool-from-repo`](/Pixie/skills/add-tools/#add-tool-from-repo),
which clones the repo, reads its README and entrypoint, decides whether it
can be cleanly wrapped (refusing if it needs a GPU, a database server, Docker,
or system packages outside the allowlist), then scaffolds a new tool folder
that imports or invokes the repo's entrypoint via FastAPI.

The skill refuses cleanly when a repo isn't a good fit. Read the refusal —
it usually tells you what's needed (e.g. "this repo expects a GPU, but I
can wrap a CPU fallback if one exists").

## From other artefacts

Pixie's wider skill library can wrap:

- **A local Python script** → [`wrap-local-script`](/Pixie/skills/add-tools/#wrap-local-script)
- **A Jupyter notebook** → [`add-tool-from-notebook`](/Pixie/skills/add-tools/#add-tool-from-notebook)
- **A CLI binary** like `ffmpeg` or `yt-dlp` → [`add-tool-from-cli-command`](/Pixie/skills/add-tools/#add-tool-from-cli-command)
- **An OpenAPI spec** → [`add-tool-from-openapi-spec`](/Pixie/skills/add-tools/#add-tool-from-openapi-spec)
- **A Streamlit or Gradio app** → [`convert-streamlit-app`](/Pixie/skills/add-tools/#convert-streamlit-app) / [`convert-gradio-app`](/Pixie/skills/add-tools/#convert-gradio-app)
- **An Excel workbook with formulas** → [`add-tool-from-excel-model`](/Pixie/skills/add-tools/#add-tool-from-excel-model)
- **An academic paper PDF or arXiv link** → [`add-tool-from-paper`](/Pixie/skills/add-tools/#add-tool-from-paper)

Each skill is opinionated about what it accepts and what it refuses. See the
[Skills reference](/Pixie/skills/overview/) for triggers and acceptance
rules.

<Aside type="tip" title="Don't have Claude Code?">
You can still hand-write tools — the [Tool authoring guide](/Pixie/build/anatomy/)
walks through the format file by file. Claude Code just removes the tedium.
</Aside>

## When something goes wrong

If the validator fails, the skill won't claim success. The right move is:

```text
Debug the currency-converter tool
```

This triggers [`debug-tool`](/Pixie/skills/diagnostics/#debug-tool), which
re-runs the validator, reads the failing check's `details`, opens
`main.py` / `tool.json` / `pyproject.toml`, proposes a fix, applies it, and
re-validates. It stops after two attempts so you don't waste tokens on a
fundamentally broken concept.

See [Troubleshooting](/Pixie/help/troubleshooting/) for the most common
failure modes (missing dependency, schema drift, wrong output shape).

## What's next

You've installed Pixie, used the example tool, and added a real one. The
fastest way to go deeper is:

- [How Pixie works →](/Pixie/concepts/overview/)
- [Hand-write a tool from scratch →](/Pixie/build/anatomy/)
- [Browse the cookbook for inspiration →](/Pixie/cookbook/)
