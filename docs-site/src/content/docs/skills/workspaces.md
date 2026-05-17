---
title: Workspaces & organisation
description: Group tools into named workspaces, tag them, and attach citations.
sidebar:
  order: 6
---

Sidebar grouping and tool-level metadata. None of these affect what a
tool does — they're for keeping a growing library organised.

## workspace-create

<span class="skill-pill">non-destructive</span>

**Trigger:** "Create a 'finance' workspace", "Make a new sidebar group
for ML tools".

Adds a row to the `workspaces` table. Each workspace is a named,
collapsible group in the sidebar with optional colour and sort order.

## workspace-add-tool

<span class="skill-pill">non-destructive</span>

**Trigger:** "Add lorenz-ode-solver to the science workspace", "Move
bertopic into the NLP group".

Adds a row to `tool_workspaces` (the many-to-many join). A tool can be
in multiple workspaces.

## workspace-remove-tool

<span class="skill-pill">non-destructive</span>

**Trigger:** "Remove foo from the science workspace", "Take bar out of
the data group".

Removes the join row. The tool itself is untouched.

## tag-tool

<span class="skill-pill">non-destructive</span>

**Trigger:** "Tag foo as 'nlp'", "Mark bar as production", "Add
'experimental' to baz".

Adds or removes a kebab-case keyword in the tool's `tool.json` `tags`
array (and indexes it in `tool_tags` for fast reverse lookup). Tags
appear as filter pills in the sidebar.

## cite-source

<span class="skill-pill">non-destructive</span>

**Trigger:** "Cite the Demucs paper in demucs-separation", "Attribute
this tool to its source repo", "Record the DOI for foo".

Records a citation, attribution, or source provenance (paper, Excel
checksum, DOI, repo commit) on an **existing** Pixie tool. Modifies
`tool.json` to add a `citations: [...]` array (and a small
`CITATION.cff` if you ask for one).

**Routes elsewhere:**
- "Implement this paper as a NEW tool" ? `add-tool-from-paper`.
- "Change behaviour" ? `update-tool`.
- "Just add a keyword" ? `tag-tool`.

---

## Why workspaces, why tags

- **Workspaces** are about **organising what you see**. A workspace is a
  named sidebar group with display order and colour. One tool, many
  workspaces.
- **Tags** are about **filtering and searching**. A tag is metadata you
  attach to a tool to find it later — `nlp`, `slow`, `costs-money`,
  `production`, whatever. Pixie's sidebar has a filter strip that lets
  you click a tag and narrow the visible tools.
- **Categories** (in `tool.json` itself) are coarse default groupings
  before workspaces. They're the "out of the box" placement.

Use all three. They don't conflict.
