---
title: How to contribute
description: PRs welcome — make it work, make it good.
sidebar:
  order: 1
---

Issues and PRs are welcome. There's no checklist of dogma to follow
before contributing — if the change works and makes Pixie (or these
docs) better, it has a good chance of being merged.

## Quick start

1. Fork the repo.
2. Make your change.
3. Open a PR explaining what changed and why.

That's it. Don't pre-discuss small fixes — typos, broken links, dead
code, clearer wording, bug fixes — just send them.

## What gets merged faster

- **It works.** The bug actually went away. The new feature actually
  does what it says. Tests pass if there are tests to run.
- **It's scoped.** One thing per PR. A typo fix and a refactor are two
  PRs.
- **The why is in the description.** A one-sentence "what" plus a
  one-sentence "why" is usually enough. Link an issue if there is one.
- **The diff is honest.** No drive-by reformatting of unrelated files.

## Issue triage

| Label                | Means                                                  |
| -------------------- | ------------------------------------------------------ |
| `bug`                | Reproducible incorrect behaviour.                      |
| `docs`               | Docs are wrong or missing.                             |
| `enhancement`        | Something works but could be better.                   |
| `discussion`         | Open question, no work item.                           |
| `help-wanted`        | Owner could use a hand here.                           |

If you're not sure whether your idea fits, open a `discussion` issue
first — better than building something that won't merge.

## Read next

- [Dev environment](/Pixie/contributing/dev-setup/) — get a working
  dev setup in 5 minutes.
- [Code style](/Pixie/contributing/style/) — light preferences, not
  laws.
- [Adding a new input/output type](/Pixie/contributing/new-type/) —
  the most common contribution to the renderer.
- [Tests](/Pixie/contributing/tests/) — what's covered.
