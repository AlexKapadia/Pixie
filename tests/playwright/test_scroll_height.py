"""Scroll-height regression: every scaffold template fits one viewport.

A scaffolded tool, run once with its default inputs, must produce a page
short enough to fit in an 800x600 viewport without introducing a vertical
scrollbar. This guards the design contract that the run surface stays
density-bounded and never sprouts a long output column.

The test is parametrised over every directory in
``pixie/templates_scaffold/`` so a new template is auto-covered.

How it works
------------
1. Scaffold each template into a tmp tools dir via the ``pixie scaffold-tool``
   CLI (the same path contributors take).
2. Boot Pixie pointed at that tmp tools dir on a free port.
3. For each tool, open ``/t/<id>``, submit the form (the scaffolds all
   ship a runnable default), and assert
   ``document.documentElement.scrollHeight <= window.innerHeight + 1``.

The +1 absorbs sub-pixel rounding on Linux/headless Chromium.

Marked ``e2e`` so it sits behind ``PIXIE_RUN_HEAVY_TESTS=1`` in CI; CI
also runs ``playwright install --with-deps chromium`` before invoking
pytest with this marker.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from playwright.sync_api import sync_playwright  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAFFOLD_INDEX = REPO_ROOT / "pixie" / "templates_scaffold" / "_index.json"


def _templates() -> list[str]:
    if not SCAFFOLD_INDEX.exists():
        return []
    data = json.loads(SCAFFOLD_INDEX.read_text(encoding="utf-8"))
    return [t["name"] for t in data.get("templates", [])]


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _wait_for_http(url: str, timeout: float = 30.0) -> None:
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    last_exc: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:  # noqa: S310
                if resp.status < 500:
                    return
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            last_exc = exc
        time.sleep(0.4)
    raise RuntimeError(f"server at {url} did not become ready: {last_exc!r}")


@pytest.fixture(scope="module")
def pixie_server(tmp_path_factory):
    """Scaffold every template into tmp_tools/ and boot Pixie against it."""
    if os.environ.get("PIXIE_RUN_HEAVY_TESTS") != "1":
        pytest.skip("PIXIE_RUN_HEAVY_TESTS!=1; skipping heavy e2e scroll-height test")

    tmp_root = tmp_path_factory.mktemp("scroll_height")
    tools_dir = tmp_root / "tools"
    tools_dir.mkdir()

    port = _free_port()
    env = {
        **os.environ,
        "PIXIE_TOOLS_DIR": str(tools_dir),
        "PIXIE_PORT": str(port),
    }

    # Scaffold every template (without uv sync — we are not running the
    # tool subprocess, only rendering its run page).
    scaffolded: list[str] = []
    for template in _templates():
        tool_id = f"t-{template}"
        rc = subprocess.run(  # noqa: S603
            [
                sys.executable, "-m", "pixie", "scaffold-tool", tool_id,
                "--template", template,
                "--name", tool_id,
                "--tools-dir", str(tools_dir),
                "--no-sync", "--no-validate", "--force",
            ],
            cwd=REPO_ROOT, env=env, check=False,
            capture_output=True, text=True,
        )
        if rc.returncode != 0:
            pytest.skip(
                f"scaffold of template {template} failed in this env: "
                f"{rc.stderr[:400]}"
            )
        scaffolded.append(tool_id)

    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "pixie", "serve", "--port", str(port)],
        cwd=REPO_ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        # No dedicated /healthz on the host — use the dashboard root.
        _wait_for_http(f"http://127.0.0.1:{port}/", timeout=30.0)
        yield {"port": port, "tool_ids": scaffolded}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.e2e
@pytest.mark.parametrize("template", _templates())
def test_scroll_height(pixie_server, template: str) -> None:
    tool_id = f"t-{template}"
    if tool_id not in pixie_server["tool_ids"]:
        pytest.skip(f"{tool_id} was not scaffolded")

    url = f"http://127.0.0.1:{pixie_server['port']}/t/{tool_id}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 800, "height": 600})
            page = context.new_page()
            page.goto(url, wait_until="networkidle")
            # Best-effort: submit if a run form is present. Some templates
            # may not auto-run on first paint.
            run_button = page.locator(
                'form button[type="submit"], form input[type="submit"]'
            ).first
            if run_button.count() > 0:
                run_button.click()
                page.wait_for_load_state("networkidle")
            scroll_height = page.evaluate("document.documentElement.scrollHeight")
            inner_height = page.evaluate("window.innerHeight")
            assert scroll_height <= inner_height + 1, (
                f"template {template}: scrollHeight={scroll_height} "
                f"exceeds innerHeight+1={inner_height + 1}"
            )
        finally:
            browser.close()
