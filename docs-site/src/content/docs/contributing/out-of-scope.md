---
title: Out of scope
description: What Pixie will never do, and why.
sidebar:
  order: 6
---

Pixie has a deliberately narrow scope. These are the things we will
decline, with the rationale. If you want one of them, Pixie isn't the
right tool — there are good alternatives for most.

## Authentication, user accounts, multi-user

Pixie binds to `127.0.0.1` and trusts the OS user. There is no `users`
table, no session middleware, no role/permission model.

**Why:** the moment Pixie acquires auth, it acquires a security
posture, a deployment story, a recovery path for lost passwords, a
GDPR-shaped audit trail, and 10× the complexity. Pixie's premise is
**personal dashboard, local-first** — auth is a fundamentally different
product.

**Alternative:** if you want a multi-user version of "small tools with
a UI", look at **Streamlit Cloud**, **Gradio Spaces**, or **Modal**.

## Cloud sync, telemetry, remote access

No anonymised metrics. No "phone home". No remote-debug endpoint. No
`0.0.0.0` listener.

**Why:** the value of local-first is that your data — including the
inputs you typed and the outputs you generated — never leaves the
machine. That guarantee is binary; we won't dilute it.

## Docker (for v1)

No Dockerfile in v1. Native install via `uv` only.

**Why:** Pixie is a personal dashboard. Most users will run it on the
same machine they're already developing on. Docker adds another moving
piece (volumes, port mapping, file permissions, host networking
gotchas) without solving a problem the user actually has.

A Docker shipping mode may arrive later for the "I want this on my
homelab" use case, but it's post-v1.

## JavaScript frameworks or a JS build step

No React, no Vue, no Svelte. No webpack, no Vite, no rollup. No npm
package.json in the runtime layer.

**Why:** htmx + Alpine + server-rendered Jinja covers every UI need
Pixie has. A build step adds onboarding friction, a moving piece per
upgrade, and a giant `node_modules`. It would change Pixie from "edit a
file, refresh the page" to a build-tool product, and that's not a
trade we want to make.

The docs site (this site) uses Astro — but the docs site is not the
product.

## Marketplace, registry, "publish" features

No "publish your tool" button. No central index of community tools. No
ratings or stars within Pixie itself.

**Why:** the marketplace shape is high-effort, high-stakes (people will
ship malware), and orthogonal to Pixie's premise. Tool distribution
today is `share-tool` → `.zip` → `import-tool`. If you want
discoverability, GitHub already exists.

## Installing dependencies from the dashboard UI

Dependency installation is a Claude Code skill responsibility, not a
Pixie UI feature. The dashboard never runs `uv sync` in response to a
click.

**Why:** any UI that runs a long blocking command is hostile UX. Worse,
it confuses failure surfaces: did the install fail? Did the validator?
The dashboard? By keeping dependency installation in skills, we get a
clean separation: skills install, Pixie runs.

## Tools that need a GPU (out of scope for the bundled set)

We ship CPU-friendly versions of GPU-favouring tools — `whisper`
(faster-whisper int8), `style-transfer` (numpy fallback), etc. We won't
maintain GPU-only paths in the bundled tools.

**Why:** keeping the project laptop-runnable is more valuable than
maximum throughput. Users who need GPU paths can `uv sync --extra
runtime` to install torch and the tool will use it where it can.

## Tools that hold WebSocket / long-poll connections to external services

The launcher's lifecycle assumes a tool can be SIGTERM'd between
requests. Tools that maintain persistent outbound connections will be
killed when warm-keep expires.

**Why:** the warm-keep model is what makes Pixie cheap. Persistent
connections need a different lifecycle (always-on background process,
externally health-checked) — that's a different product shape.

**Alternative:** for persistent-connection workloads, wrap them in a
small standalone service and have a Pixie tool query that service.

## A plugin system beyond the schema-driven renderer

There is no `pixie.register_input_type("frequency", ...)` API at
runtime. Adding a type means editing source files (see [Adding a new
input/output type](/Pixie/contributing/new-type/)).

**Why:** a runtime plugin system would require versioned hooks,
upgrade contracts, sandboxing, and discovery. The cost is enormous and
the benefit is small — type addition is rare and the four-file change
is trivial.

## Themes beyond the default

We ship a few accent colours (indigo, slate, forest, ember) and
density modes. No user theming, no community themes, no custom CSS
injection.

**Why:** the dashboard is infrastructure, not a marketing surface. The
design language matters; outsourcing it dilutes it. If you want bigger
fonts: density. Different vibe: accent. Anything more is a fork.

## Mobile or tablet layouts

The dashboard targets desktop. The renderer doesn't have responsive
breakpoints for mobile.

**Why:** the use case is "I'm at my workstation and need to run a
small tool." Mobile-friendly responsive design is doable but not free —
form layouts that work on 320px need different decisions than 1440px.
We've chosen one well.

## Native packaging (Tauri, PyInstaller, etc.)

No `.app`, no `.exe`, no `.deb`. Install via `uv sync`.

**Why:** Pixie's audience is developers. They have Python and a
terminal. A native wrapper is more value for end-users than the cost
justifies right now.

## What might land later

Out of scope **for v1** but possibly in scope later:

- A Docker shipping mode (for self-hosters who want one process).
- A "share via link" mode for one-tool-at-a-time hosted demos (with
  explicit opt-in per demo).
- Optional encrypted secrets backup to user-controlled storage.
- A WCAG AA pass on the entire UI (we're already close).
- Tablet layouts.
- A first-class CLI for every Claude Code skill (so non-Claude users get
  the same flows).

If you want any of these and feel strongly, open a discussion issue.
We're not closed to them — they just aren't v1.
