---
title: Welcome to Pixie
description: What Pixie is, what it isn't, and who it's for.
sidebar:
  order: 1
---

Pixie is a single local web app that lists every Python tool in your `tools/`
folder and renders a UI for each one from a `tool.json` schema. Tools run as
isolated subprocesses with their own `uv` virtual environments. They spawn on
click, stay warm for a few minutes, then shut down.

You add tools by talking to Claude Code. You don't install anything through
the UI.

## Who Pixie is for

- **The developer with a `~/scripts` folder** full of one-off Python tools
  that never made it onto a website because deploying each one is overkill.
- **The researcher** who has a Jupyter notebook for every paper they've read
  and wants a non-notebook way to re-run them.
- **The hobbyist** who built a thing once, came back six months later, and
  couldn't remember how to run it.
- **The Claude Code user** who wants a place for the small tools an agent
  builds on the fly during a session to actually live.

## What you get

- A dashboard at `http://localhost:7860` that scans `tools/` on startup and
  shows everything it finds.
- A schema-driven renderer that handles **25 input types** (text, slider,
  date range, file, code editor, map polygon, ...) and **39 output types**
  (numbers, tables, every common chart, maps, image, audio, video, LaTeX,
  diff, log, streaming text, ...).
- A subprocess launcher with warm-keep, port allocation, and resource limits.
- A validator that runs **11 checks** end-to-end on every tool before it
  appears in the sidebar.
- SQLite-backed run history (re-run any past input with one click).
- A per-tool secrets UI that writes to the tool's own `.env` and never
  displays values back.
- A bundle of Claude Code skills for adding, editing, debugging, exporting,
  and organising tools.

## What you don't get

- No accounts, no auth, no remote access — Pixie binds to `127.0.0.1` only.
- No cloud, no telemetry, no sync — your data does not leave the machine.
- No marketplace, no registry, no "publish" button — sharing a tool is
  `cp -r tools/your-tool/ ~/somewhere-else/ && uv sync` on the other side.
- No Docker, no Kubernetes, no serverless — Pixie is a single Python process
  that spawns child processes.
- No frontend build step — htmx + Alpine.js + pre-built Tailwind. Editing
  a template means editing a Jinja2 file.

## How this site is organised

- **[Start here](/Pixie/start/install/)** — install, run, see the example
  tool, scaffold your first real tool.
- **[Concepts](/Pixie/concepts/overview/)** — how the runtime, validator, and
  renderer fit together. Read this before contributing.
- **[Build a tool](/Pixie/build/anatomy/)** — the full hand-authoring guide:
  `tool.json`, the HTTP contract, every input and output type, layouts,
  fixtures, streaming.
- **[Claude Code skills](/Pixie/skills/overview/)** — every shipped skill,
  what it does, what it refuses, example trigger phrases.
- **[Tools cookbook](/Pixie/cookbook/)** — the tools that ship with Pixie
  (Lorenz attractor, n-body, sentiment over time, BERTopic, Whisper, ...).
- **[Reference](/Pixie/reference/cli/)** — CLI, HTTP API, database schema,
  configuration.
- **[Contributing](/Pixie/contributing/overview/)** — dev setup, code style,
  how to add a new input/output type, what's out of scope.

If you're just here to use Pixie, the **Start here** section is enough.
