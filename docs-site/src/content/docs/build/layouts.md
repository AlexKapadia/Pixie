---
title: Layouts
description: Form, chat, and split — what changes between them.
sidebar:
  order: 6
---

The `layout` field in `tool.json` chooses one of three page templates.
All three render the same input and output partials; only the surrounding
structure differs.

## `form` (default)

Two-column page. Inputs on the left (~⅓ width), outputs on the right
(~⅔ width). The run button sits at the bottom of the input column.

```json
{ "layout": "form", ... }
```

Use this for **most tools**. Calculators, analyzers, transformers — if
the user enters a few values and gets back a result, this is the layout.

## `chat`

Single full-width column. Messages display as a conversation, sticky
input at the bottom. The validator treats this layout specially: it
sends a synthetic `{messages: [{role: "user", content: "Validation
probe"}], history: []}` payload instead of walking declared inputs.

```json
{
  "layout": "chat",
  "inputs": [
    {"key": "messages", "type": "json", "label": "Conversation"},
    {"key": "history",  "type": "json", "label": "History", "required": false, "default": []}
  ],
  "outputs": [
    {"key": "reply", "type": "stream_text", "label": "Reply", "streaming": true}
  ]
}
```

Use for **conversational tools** — chat agents, code assistants, Q&A
loops. The renderer skeleton for `chat` is currently minimal; rich chat
UI is on the roadmap (Phase 4d).

## `split`

Single-column vertical stack with inputs and outputs interleaved. The
"Run" button is sticky at the top of the page.

```json
{ "layout": "split", ... }
```

Use when you have **several outputs that the user wants to compare side
by side** (e.g. an image-processing tool that returns input, output, and
diff stacked vertically). Also useful for tools whose inputs and outputs
are best described together (e.g. show me this dataset, then run this
on it, then show the result).

## How layouts affect validation

The only layout-specific behaviour in the validator is the `chat`
override: instead of generating sample inputs from the declared schema,
it sends `{"messages": [...], "history": []}`. Tools declaring `layout:
"chat"` must accept this shape or check 8 will fail.

For `form` and `split`, the validator walks the declared inputs normally.

## Output `layout` field

Beyond the top-level `layout`, each **output** has its own `layout` field
(`panel`, `tab`, or `inline`). This controls grouping within the output
panel — see [Output types → Layout grouping](/Pixie/build/outputs/#layout-grouping).

## Choosing

| If your tool…                                                          | Use      |
| ---------------------------------------------------------------------- | -------- |
| Computes a result from inputs (calculator, model, analyzer)            | `form`   |
| Has a conversation                                                     | `chat`   |
| Shows inputs and several outputs vertically (e.g. image processing)    | `split`  |

If unsure, start with `form`. Most tools never need anything else.
