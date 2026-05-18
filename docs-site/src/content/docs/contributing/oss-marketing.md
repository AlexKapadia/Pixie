---
title: OSS marketing playbook
description: A practical plan to grow Pixie with proof-first, audience-specific messaging.
sidebar:
  order: 2
---

Use this page as the default operating plan for marketing Pixie as open source.

## 1) Positioning (single sentence, everywhere)

Use this exact sentence in README intros, docs hero copy, launch posts, and
demo intros:

> **Pixie turns any Python script/notebook/repo into a local UI tool with no cloud and no frontend work.**

## 2) Proof-first funnel

Prioritise evidence over claims. Every campaign should include:

- **Short demo clips (30–90s):**
  - raw script/notebook/repo starting point
  - one command/prompt to wrap it
  - final local UI run in Pixie
- **One-click examples:** direct links to runnable examples in docs and repo.
- **Before/after stories:** show `raw script` -> `usable local app` with clear
  screenshots and time-to-result.

## 3) Audience-specific messaging

Ship dedicated messaging blocks and examples for three audiences:

### AI builders using Claude Code skills

- Lead with skill coverage: description, repo, notebook, Streamlit/Gradio, CLI,
  OpenAPI, Excel, papers.
- CTA: "Describe a tool in one sentence and validate it end-to-end."

### Data scientists with notebooks/Excel models

- Lead with conversion of existing assets without rewriting frontend.
- CTA: "Turn notebooks and `.xlsx` models into reusable local apps."

### Engineers wrapping internal utilities

- Lead with local-only deployment, no SaaS, no telemetry, contract validation.
- CTA: "Wrap internal scripts into dependable team-facing UIs."

## 4) Weekly high-intent content cadence

Publish one case study per week and rotate source formats:

- GitHub repo -> Pixie tool
- Notebook -> Pixie tool
- Streamlit app -> Pixie tool
- OpenAPI spec -> Pixie tool
- Excel model -> Pixie tool
- Paper/arXiv -> Pixie tool

Each case study should include:

- search-friendly title ("Convert X to a local UI tool")
- short social clip cut-down
- minimal reproducible steps
- link to source and final tool output

## 5) Launch loops in OSS channels

Run repeatable launch cycles around each major case study/release:

- GitHub Discussions + linked issues for feedback and follow-up tasks
- Hacker News "Show HN" launches for notable milestones
- Reddit posts in relevant Python/data/ML communities
- X and LinkedIn build-in-public threads
- Python/Data newsletter submissions

Track channel-specific outcomes and double down on channels with the highest
docs-to-install conversion.

## 6) Contribution-led growth

Use contributions as a growth surface, not just maintenance:

- keep `good first issue` and `docs` issues well-scoped and continuously filled
- run contributor spotlights (monthly post with merged PR highlights)
- host a monthly community demo thread in GitHub Discussions

## 7) Trust signals

Publish and keep current:

- benchmark page for startup/runtime/validation timings
- validator reliability stats (pass/fail rates by check)
- comparison matrix vs Streamlit, Gradio, and manual FastAPI
- explicit privacy stance: local-only, no cloud sync, no telemetry

## 8) Monthly growth review

Review these metrics monthly:

- GitHub stars
- install starts
- docs -> install conversion
- first-tool completion rate
- 30-day retention

Keep a simple monthly changelog of what was tried, what moved metrics, and what
to stop/start/continue next month.
