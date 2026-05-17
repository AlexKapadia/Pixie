---
title: HTTP API
description: Pixie's own HTTP surface — routes used by the dashboard, htmx fragments, and skills.
sidebar:
  order: 2
---

Pixie exposes a small HTTP API on `127.0.0.1:7860` (configurable). Most
of it is server-rendered HTML for the dashboard, but there's a JSON
surface that Claude Code skills and external integrations use.

## Dashboard / HTML routes

| Method | Path                                      | Returns                                      |
| ------ | ----------------------------------------- | -------------------------------------------- |
| `GET`  | `/`                                       | Dashboard with sidebar + recent runs panel.  |
| `GET`  | `/tool/{tool_id}`                         | Single-tool page (form, output panel, history). |
| `GET`  | `/tool/{tool_id}/runs/{run_id}`           | Past run loaded into inputs + outputs.       |
| `GET`  | `/tool/{tool_id}/settings`                | Per-tool settings (secrets, overrides).      |
| `GET`  | `/settings`                               | Global settings (theme, accent, density).    |
| `GET`  | `/library`                                | Artefact gallery across all tools.           |
| `GET`  | `/empty`                                  | Empty-state screen (when `tools/` is empty). |

## htmx fragment routes

These return HTML fragments swapped into the page by htmx.

| Method | Path                                | Used for                                              |
| ------ | ----------------------------------- | ----------------------------------------------------- |
| `POST` | `/tool/{tool_id}/run`               | Run a tool. Body is form-encoded inputs.              |
| `GET`  | `/tool/{tool_id}/stream`            | SSE proxy to the tool's `/stream`.                    |
| `POST` | `/tool/{tool_id}/cancel`            | Cancel an in-flight run.                              |
| `GET`  | `/tool/{tool_id}/runs`              | Run history dropdown.                                 |
| `GET`  | `/tools-changed`                    | Lightweight "anything changed?" partial (htmx poll).  |
| `GET`  | `/tool/{tool_id}/autocomplete/{ep}` | Proxy to the tool's autocomplete endpoint.            |

## JSON API

Skills and external integrations use these. All return `application/json`.

| Method | Path                                    | Effect                                                       |
| ------ | --------------------------------------- | ------------------------------------------------------------ |
| `GET`  | `/api/tools`                            | List all discovered tools with id, name, status, latest validation summary. |
| `GET`  | `/api/tools/{tool_id}/validate`         | Run the validator on demand, return the full report.         |
| `POST` | `/api/tools/{tool_id}/stop`             | Send SIGTERM to a running tool subprocess.                   |
| `GET`  | `/api/launcher/state`                   | Warm dict snapshot (developer-mode only).                    |
| `GET`  | `/api/healthz`                          | `{"ok": true}` once Pixie is fully booted.                   |
| `GET`  | `/api/artefacts`                        | Paginated artefact list. Query params: `tool`, `mime`, `starred`, `label`, `tag`, `from`, `to`, `page`. |
| `POST` | `/api/artefacts/{id}/star`              | Toggle star on an artefact.                                  |
| `POST` | `/api/artefacts/{id}/label`             | Set the artefact label.                                      |
| `POST` | `/api/artefacts/{id}/delete`            | Soft delete (writes `deleted_at`).                           |
| `GET`  | `/api/runs/{run_id}/export`             | Stream a zip of the run (inputs, outputs, artefacts).        |
| `GET`  | `/api/runs/{run_id}/report`             | Stream a zip with a rendered `report.md` plus assets.        |
| `GET`  | `/api/workspaces`                       | List workspaces.                                             |
| `POST` | `/api/workspaces`                       | Create a workspace. Body: `{name, colour?}`.                 |
| `DELETE` | `/api/workspaces/{id}`                | Delete a workspace (cascades `tool_workspaces`).             |
| `POST` | `/api/workspaces/{id}/tools/{tool_id}`  | Add a tool to a workspace.                                   |
| `DELETE` | `/api/workspaces/{id}/tools/{tool_id}` | Remove a tool from a workspace.                            |

## Headers Pixie sets when calling tools

When forwarding a request to a tool's `/run`, the proxy adds:

| Header                     | Value                                                   |
| -------------------------- | ------------------------------------------------------- |
| `Content-Type`             | `application/json`                                      |
| `X-Pixie-Run-Id`           | the same UUID as the body's `run_id`                    |
| `X-Pixie-Artefacts-Dir`    | absolute path where the tool may write large outputs    |

## What Pixie does NOT expose

- **No auth** — there are no tokens, no sessions, no API keys for
  Pixie's own API. Defence is loopback binding only.
- **No remote-execute endpoint** — every endpoint runs in-process or
  forwards to a tool subprocess.
- **No upload/install endpoint** — tools are added by Claude Code skills
  writing to `tools/` on disk, not via HTTP.
- **No public 0.0.0.0 listener** — `config._host_must_be_loopback`
  enforces 127.0.0.0/8 or ::1 at process boot.

## Example: list tools, then run one

```bash
# List all tools
curl -s http://127.0.0.1:7860/api/tools | jq '.[] | {id, status: .validation.overall}'

# Validate one
curl -s http://127.0.0.1:7860/api/tools/lorenz-ode-solver/validate | jq '.overall'

# Run the tool (via the htmx fragment endpoint — accepts form data)
curl -s -X POST http://127.0.0.1:7860/tool/lorenz-ode-solver/run \
  -d sigma=10 -d rho=28 -d beta=2.667 -d t_end=40 -d steps=8000
```

The last call returns HTML (the rendered output panel). If you want JSON
back from a tool, hit the tool's own port directly — but that port is
dynamic and the launcher owns it; in practice, talk to Pixie.
