---
title: Use the example tool
description: Walk through the compound-interest tool that ships with Pixie.
sidebar:
  order: 3
---

Pixie ships with one fully-working example tool at
`tools/example-compound-interest/`. It exists so that on first run you have
something to click, and so that the format documentation has a concrete
reference to point at.

## Click the tool

In the sidebar under **Finance**, click **Compound interest**. The launcher
will:

1. Notice the tool isn't warm.
2. Bind to `127.0.0.1:0` to pick a free port, release the binding.
3. Run `tools/example-compound-interest/.venv/bin/python main.py --port <port>`.
4. Poll `http://127.0.0.1:<port>/healthz` until it returns `{"ok": true}`.
5. Fetch `/schema` and compare it to the on-disk `tool.json`.
6. Register the running tool in the launcher's in-memory state.
7. Render the form on the left and the empty output panel on the right.

You should see the status pill flip from **dormant** to **running** in
~200–500 ms on the first click. Subsequent clicks within `warm_keep_seconds`
(default 300) are instant.

## Run a calculation

Enter:

- **Principal:** `10000`
- **Monthly contribution:** `200`
- **Years:** `20`
- **Annual rate (%):** `7`
- **Compounding:** `Monthly`

Click **Run**. The right panel updates with:

- **Final balance** — a `number` output with `format: "currency"`, precision 2.
- **Growth over time** — a `chart_line` showing principal, contributions, and
  interest accumulated by year.
- **Year-by-year breakdown** — a `table` listing each year's contributions,
  interest, and end balance.

The same data also lands in `pixie.db` as a row in `runs` with the inputs and
the (truncated) outputs. Hit the run-history dropdown in the header to
reload any past run with one click.

## Look under the hood

The whole tool is four small files:

```text
tools/example-compound-interest/
├── tool.json        # schema: inputs, outputs, layout, metadata
├── pyproject.toml   # deps: fastapi, uvicorn, python-dotenv
├── main.py          # ~40 lines of FastAPI doing the calculation
└── README.md        # how to run the tool standalone for debugging
```

Open `tool.json` to see the schema, then open `main.py` to see how it gets
wired to FastAPI. Then read [Tool anatomy](/Pixie/build/anatomy/) — that
page walks through every line.

## Validate it manually

You can re-run the validator on any tool from the command line:

```bash
uv run pixie validate example-compound-interest
```

You'll get a structured report with 11 checks (folder structure, schema
parsing, sample-input run, output conformance, clean shutdown, ...). All
green means the tool is fit to ship.

See [The validator](/Pixie/concepts/validator/) for what each check does and
[Validator checks reference](/Pixie/reference/validator-checks/) for the
exact behaviour of each.

## Stop the tool

Walk away. After `warm_keep_seconds` of inactivity (300 by default), the
launcher sends SIGTERM, waits up to 5 seconds, then SIGKILL if needed. The
tool's port is released. Memory usage drops back to roughly Pixie's own
baseline.

## Next

Now that you've run a working tool end-to-end, the fun starts —
[add your first real tool via Claude Code →](/Pixie/start/first-tool/)
