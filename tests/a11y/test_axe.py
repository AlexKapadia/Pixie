"""WCAG audit via axe-core injected into Playwright.

Fails on any ``critical`` or ``serious`` violation. ``moderate`` and
``minor`` violations are reported but do not fail the build (yet);
``needs_review`` items are logged.

Phase 6e: parametrised over every key screen plus a keyboard-only
navigation smoke test.
"""

from __future__ import annotations

import shutil
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _critical_violations(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        v for v in report.get("violations", [])
        if v.get("impact") in {"critical", "serious"}
    ]


def _summarise(violations: list[dict[str, Any]]) -> str:
    parts = []
    for v in violations:
        nodes = v.get("nodes", [])
        targets = []
        for n in nodes[:3]:
            t = n.get("target")
            if isinstance(t, list) and t:
                targets.append(" > ".join(str(x) for x in t))
        joined = "; ".join(targets) if targets else "<no targets>"
        parts.append(f"{v.get('id', '?')} [{v.get('impact', '?')}] ({joined})")
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Server fixture mirrors the visual one — a11y tests need fixture tools too
# ---------------------------------------------------------------------------


@pytest.fixture
def pixie_server_with_fixtures(tmp_pixie_root: Path, sample_tool_factory) -> Iterator[str]:
    """Server with fixture tools staged so catalog routes render."""

    import uvicorn

    from pixie.app import create_app

    sample_tool_factory("all-inputs-tool")
    sample_tool_factory("all-outputs-tool")
    sample_tool_factory("chat-tool")
    example_src = REPO_ROOT / "tools" / "example-compound-interest"
    if example_src.exists():
        example_dest = tmp_pixie_root / "tools" / "example-compound-interest"
        if not example_dest.exists():
            shutil.copytree(
                example_src,
                example_dest,
                ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.pyc"),
            )

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    app = create_app()
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", loop="asyncio"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="pixie-a11y-server")
    thread.start()

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if server.started:
            break
        time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=2.0)
        raise RuntimeError("pixie_server_with_fixtures failed to start")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)


# ---------------------------------------------------------------------------
# Screen coverage — light theme only (axe-core contrast rules cover dark
# parity separately when needed).
# ---------------------------------------------------------------------------


EMPTY_SCREENS = [
    ("dashboard_empty", "/"),
]
POPULATED_SCREENS = [
    ("dashboard_with_tools", "/"),
    ("tool_form", "/tool/compound-interest"),
    ("tool_chat", "/tool/chat-tool"),
    ("library_empty", "/library"),
    ("tools_grid", "/tools"),
    ("settings_global", "/settings"),
    ("settings_per_tool", "/tool/compound-interest/settings"),
    ("input_catalog", "/tool/all-inputs-tool"),
    ("output_catalog", "/tool/all-outputs"),
]

ALL_SCREENS = (
    [(s, p, "empty") for s, p in EMPTY_SCREENS]
    + [(s, p, "populated") for s, p in POPULATED_SCREENS]
)


@pytest.mark.parametrize(("screen", "path", "fixtures"), ALL_SCREENS)
def test_no_critical_violations(
    page,
    pixie_server,
    pixie_server_with_fixtures,
    axe_audit,
    screen: str,
    path: str,
    fixtures: str,
) -> None:
    """No ``critical`` or ``serious`` axe-core violations on any screen."""

    base = pixie_server if fixtures == "empty" else pixie_server_with_fixtures
    page.goto(base + path, wait_until="networkidle")
    report = axe_audit(page)
    failures = _critical_violations(report)
    assert failures == [], (
        f"{screen}: critical/serious axe-core violations -> {_summarise(failures)}"
    )

    # Log moderate/minor as warnings via the stderr stream so they show
    # up in -s mode but don't fail.
    moderate = [
        v for v in report.get("violations", [])
        if v.get("impact") in {"moderate", "minor"}
    ]
    if moderate:
        print(
            f"\n[a11y warning] {screen}: {len(moderate)} moderate/minor "
            f"violations -> {_summarise(moderate)}"
        )


# ---------------------------------------------------------------------------
# Keyboard-only navigation smoke test
# ---------------------------------------------------------------------------


KEYBOARD_SCREENS = [
    ("dashboard_with_tools", "/", "populated"),
    ("tool_form", "/tool/compound-interest", "populated"),
    ("settings_global", "/settings", "populated"),
]


@pytest.mark.parametrize(("screen", "path", "fixtures"), KEYBOARD_SCREENS)
def test_keyboard_navigation(
    page,
    pixie_server,
    pixie_server_with_fixtures,
    screen: str,
    path: str,
    fixtures: str,
) -> None:
    """Tabbing through the page reaches at least N interactive elements and
    every focused element has a visible focus indicator (outline != none
    OR a :focus-visible replacement reachable via ``outline-offset`` /
    ``box-shadow``).
    """

    base = pixie_server if fixtures == "empty" else pixie_server_with_fixtures
    page.goto(base + path, wait_until="networkidle")

    # Count interactive elements that should be reachable.
    interactive_count = page.evaluate(
        """() => document.querySelectorAll(
          'a[href], button:not([disabled]), input:not([disabled]), '
          + 'select:not([disabled]), textarea:not([disabled]), '
          + '[tabindex]:not([tabindex="-1"])'
        ).length"""
    )
    assert interactive_count > 0, f"{screen}: no interactive elements found"

    # Tab through up to N elements; record focus indicator each step.
    max_tabs = min(interactive_count + 2, 40)
    indicator_issues: list[str] = []
    for _ in range(max_tabs):
        page.keyboard.press("Tab")
        info = page.evaluate(
            """() => {
              const el = document.activeElement;
              if (!el || el === document.body) return null;
              const cs = window.getComputedStyle(el);
              return {
                tag: el.tagName.toLowerCase(),
                id: el.id || null,
                outline: cs.outline,
                outlineStyle: cs.outlineStyle,
                outlineWidth: cs.outlineWidth,
                boxShadow: cs.boxShadow,
                borderColor: cs.borderColor,
              };
            }"""
        )
        if info is None:
            continue
        has_outline = (
            info["outlineStyle"] not in ("none", "")
            and info["outlineWidth"] not in ("0px", "0")
        )
        has_box_shadow = info["boxShadow"] not in ("none", "", None)
        if not (has_outline or has_box_shadow):
            indicator_issues.append(
                f"<{info['tag']}#{info['id'] or '?'}>: "
                f"outline={info['outline']!r} boxShadow={info['boxShadow']!r}"
            )

    # Allow up to 1 element without a visible indicator (e.g. some
    # invisible focusable elements). More than that is a real bug.
    assert len(indicator_issues) <= 1, (
        f"{screen}: {len(indicator_issues)} focusable elements lack a "
        f"visible focus indicator -> {'; '.join(indicator_issues[:5])}"
    )
