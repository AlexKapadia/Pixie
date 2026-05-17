---
title: Data & secrets
description: Setting credentials and importing datasets into a tool's data folder.
sidebar:
  order: 4
---

## set-secret

<span class="skill-pill">non-destructive (writes .env)</span>

**Trigger:** "Set OPENAI_API_KEY for whisper", "Add my Anthropic key to
the RAG tool", "Clear the X secret".

**Steps:**

1. Identify the tool (uses `list-tools` if ambiguous).
2. Identify the secret key.
3. Read the value from stdin **without echoing**.
4. Write `KEY=value` to `tools/<id>/.env` (creates `chmod 600` on
   POSIX).
5. Confirm.

**Never:**
- Logs the value.
- Echoes it back.
- Stores it in `pixie.db` or anywhere outside `tools/<id>/.env`.

After `set-secret`, the tool's settings page in the dashboard shows the
secret as "set" (green pill). To replace it, run `set-secret` again or
use the "Replace" button in the settings UI.

To clear a secret, run with an empty value or use the "Clear" button.

---

## fetch-dataset-from-url

<span class="skill-pill">non-destructive</span>

**Trigger:** any HTTPS URL pointing at a data file, with a request to
"fetch" / "download" / "import" it for a named tool.

Downloads to `tools/<id>/data/` with:

- Safe extraction (refuses paths containing `..`).
- SHA-256 checksum verification (if you provide an expected hash).
- A small note appended to `data/README.md` recording source URL and
  date.

**Doesn't handle** Kaggle (use `fetch-dataset-from-kaggle`) or
HuggingFace (use `fetch-dataset-from-huggingface`) — those need
authenticated API calls.

---

## fetch-dataset-from-kaggle

<span class="skill-pill">non-destructive</span>

**Trigger:** mentions of Kaggle, a dataset slug like `username/dataset`,
or a competition name.

Uses your local Kaggle credentials (typically `~/.kaggle/kaggle.json`)
to download the dataset or competition data into `tools/<id>/data/`.
Refuses Kaggle **notebooks** (those are scripts, not datasets — use
`add-tool-from-notebook`).

---

## fetch-dataset-from-huggingface

<span class="skill-pill">non-destructive</span>

**Trigger:** mentions of HuggingFace, an `org/dataset` slug from the HF
hub.

Uses `huggingface_hub` with your local `HF_TOKEN` (if set) to pull
public or gated datasets into `tools/<id>/data/`. Refuses HF **models**
— those should be loaded by the tool itself via `transformers`, not
copied into the tool folder.

---

## import-dataset-from-local

<span class="skill-pill">non-destructive</span>

**Trigger:** a local filesystem path. "Use `./data/iris.csv` as the
dataset for tool foo".

Copies / symlinks / moves a local file or folder into
`tools/<id>/data/`. Asks before overwriting an existing same-named
file.

---

## How tools find their data

Pixie sets `cwd=tools/<id>/` when spawning a tool, so relative paths
work:

```python
import pandas as pd
import pathlib

DATA_DIR = pathlib.Path(__file__).parent / "data"

iris = pd.read_csv(DATA_DIR / "iris.csv")
```

`data/` is in `.gitignore` by default — large datasets shouldn't live in
your tool's source repo. If you want to ship a small reference fixture,
put it in `reference/` instead (see [Fixtures & reference
validation](/Pixie/build/fixtures/)).
