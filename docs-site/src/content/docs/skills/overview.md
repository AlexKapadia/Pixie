---
title: Skills overview
description: 50+ Claude Code skills that automate every part of the Pixie tool lifecycle.
sidebar:
  order: 1
---

Pixie ships with a library of Claude Code skills that live in
`.claude/skills/`. They load automatically when you open the repo in
Claude Code. Each skill has:

- A YAML frontmatter declaring the skill's `name`, `description`, and
  allowed tools.
- A body of instructions Claude Code follows when the skill fires.

Skills are the **only** sanctioned way to add or modify tools. Pixie's
own dashboard intentionally has no "install tool" button — that
responsibility lives in Claude Code, where the validator can be invoked
end-to-end before any new tool appears.

## How skills get triggered

Claude Code routes user phrases to skills via the description field. The
descriptions are written defensively: every skill says what it does *and*
what it doesn't do, with handoff hints to neighbouring skills. Example:

> `add-tool-from-repo` — Clones a Git repository and wraps its entrypoint
> as a Pixie tool. Use when the user gives a Git URL and asks to add,
> clone, or wrap a repo. **Do NOT use for .zip (import-tool), .py
> (wrap-local-script), .ipynb (add-tool-from-notebook), or prose
> (add-tool-from-description).**

This gives the router (and the user) a clear sense of which skill to
reach for.

## Categories

| Category                           | Skills it includes                                                                             |
| ---------------------------------- | ---------------------------------------------------------------------------------------------- |
| [Add tools](/Pixie/skills/add-tools/)             | from description, from repo, from notebook, from CLI, from OpenAPI, from paper, from Excel, from local script, from Streamlit/Gradio, from zip |
| [Edit & maintain tools](/Pixie/skills/edit-tools/) | update, rename, fork, archive/unarchive, remove, lint, inspect, organise, migrate format, revalidate-all |
| [Data & secrets](/Pixie/skills/data-secrets/)      | set-secret, fetch-dataset-from-url/Kaggle/HuggingFace, import-dataset-from-local                |
| [Runs, outputs & exports](/Pixie/skills/outputs/) | list-outputs, find-output, view-runs, label-run, star-run, export-run, export-run-as-report, export-as-format, bulk-export, copy-output-to, copy-to-clipboard, send-to-folder, register-export-target, open-artefacts-folder, clear-old-outputs, share-tool, import-tool |
| [Workspaces & organisation](/Pixie/skills/workspaces/) | workspace-create, workspace-add-tool, workspace-remove-tool, tag-tool, cite-source        |
| [Diagnostics](/Pixie/skills/diagnostics/)         | debug-tool, pixie-status, pixie-doctor, view-logs, audit-disk-usage, validate-against-reference, list-tools |

A printable cheatsheet of trigger phrases is at
[Cheatsheet](/Pixie/skills/cheatsheet/).

## Core principles every skill obeys

1. **Validator-first.** Every skill that modifies a tool ends with
   `uv run pixie validate <tool_id>` and surfaces the report verbatim.
   A skill **may not claim success** if `overall == "fail"`.
2. **Confirmation gates for destructive ops.** `remove-tool`,
   `rename-tool`, `clear-old-outputs` all require explicit "yes"
   confirmation listing every side effect.
3. **Refuse cleanly.** Skills refuse what they can't do and route the
   user to the right skill. `add-tool-from-repo` refuses .zip files and
   points at `import-tool`.
4. **Never leak secrets.** `set-secret` reads from stdin without echoing,
   `lint-tool` reports hardcoded-secret line numbers only (not the
   value), `share-tool` excludes `.env` from zips, `import-tool` refuses
   zips that contain `.env`.
5. **Two-attempt cap on auto-fix.** `debug-tool` makes at most two
   repair attempts before surfacing the failure and stopping. No
   token-burning loops.
6. **Read-only diagnostics.** `pixie-status`, `pixie-doctor`,
   `inspect-tool`, `lint-tool`, `audit-disk-usage`, `view-runs`,
   `view-logs`, `list-tools`, `list-outputs`, `find-output` all use only
   `Bash`/`Read`/`Glob`/`Grep`.

## Routing accuracy

The skill library is gold-tested against a 130-prompt routing benchmark.
Current pass rate: **97.7%**. The disambiguations the test specifically
exercises:

- `add-tool-from-paper` vs `cite-source` — former creates a NEW tool from
  a paper; latter annotates an EXISTING tool with a citation.
- `debug-tool` vs `update-tool` — former fixes broken validation; latter
  modifies a working tool.
- `rename-tool` vs `fork-tool` — former changes one ID; latter
  duplicates under a new ID.
- `export-run` vs `bulk-export` — former exports ONE run; latter exports
  MULTIPLE.
- `validate-against-reference` vs `debug-tool` — former compares schemas;
  latter repairs failures.

If a prompt is genuinely ambiguous, the skill clarifies before doing any
mutation. None of the skills are silent.

## Tools available to skills

Per Pixie's safety policy, every skill declares its `allowed-tools` in
frontmatter. Only the smallest set required for the job. No skill has
access to:

- Network beyond what `add-tool-from-repo` needs for `git clone` and the
  data-fetch skills for their specific source (Kaggle, HF, URL).
- The `Agent` tool — skills don't spawn other skills programmatically.
- The Pixie dashboard's UI — every action goes through the CLI or the
  HTTP API at `127.0.0.1:7860/api/...`.

## Writing your own skill

The shipped skills are documented templates. If you want to add a
domain-specific skill (e.g. `add-tool-from-my-companys-internal-spec`):

1. Create `.claude/skills/<name>/SKILL.md`.
2. YAML frontmatter:
   ```yaml
   ---
   name: my-skill
   description: One line describing when this fires and when it doesn't.
   allowed-tools: Bash, Read, Write, Edit, Glob, Grep
   ---
   ```
3. Body: numbered steps, refusal templates, validator handoff if
   appropriate.
4. Keep it ≤ 200 lines. Long skills are unreliable.

Read the existing skills in `.claude/skills/` for the patterns.
