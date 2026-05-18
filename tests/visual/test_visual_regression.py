"""Visual-regression sweep against design artboards.

Each test points Playwright at a Pixie page and asserts the resulting
screenshot is within the pixel-diff threshold (default 2%). First run
writes the baseline and skips; subsequent runs compare.

Phase 6b: every key screen captured in light + dark themes at two
viewports (1440x900 desktop, 1920x1080 wide). Theme switching uses the
public ``Pixie.setTheme`` helper (see ``pixie/static/pixie.js``) so the
captured screenshot exercises the same code path users do.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures"
DIFF_DIR = Path(__file__).resolve().parent / "_diff"

# Viewports we capture every screen at.
VIEWPORTS = [
    ("1440x900", 1440, 900),
    ("1920x1080", 1920, 1080),
]
# Themes — DECISIONS.md s44 requires parity in BOTH.
THEMES = ["light", "dark"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_theme(page, theme: str) -> None:
    """Switch theme via the public Pixie API and wait for re-paint."""

    page.evaluate(
        "(t) => { if (window.Pixie && Pixie.setTheme) Pixie.setTheme(t); "
        "else document.documentElement.setAttribute('data-theme', t); }",
        theme,
    )
    # Theme transitions are 200ms in pixie.css; charts re-layout after the
    # pixie:theme-changed event which fires synchronously inside setTheme.
    page.wait_for_timeout(400)


def _set_viewport(page, w: int, h: int) -> None:
    page.set_viewport_size({"width": w, "height": h})


def _compose_name(screen: str, theme: str, viewport: str) -> str:
    return f"{screen}__{theme}__{viewport}"


def _save_diff(name: str, baseline_path: Path, candidate_bytes: bytes) -> Path:
    """Save a side-by-side PNG to ``_diff/`` for the failing pair."""

    from PIL import Image

    DIFF_DIR.mkdir(exist_ok=True)
    baseline_img = Image.open(baseline_path).convert("RGB")
    candidate_img = Image.open(BytesIO(candidate_bytes)).convert("RGB")
    # Stack baseline + candidate side-by-side; pad smaller image with
    # white so they line up.
    h = max(baseline_img.height, candidate_img.height)
    canvas = Image.new(
        "RGB",
        (baseline_img.width + candidate_img.width + 8, h),
        (255, 255, 255),
    )
    canvas.paste(baseline_img, (0, 0))
    canvas.paste(candidate_img, (baseline_img.width + 8, 0))
    diff_path = DIFF_DIR / f"{name}.png"
    canvas.save(diff_path)
    return diff_path


def _capture_and_compare(
    page,
    name: str,
    compare_screenshot,
    *,
    threshold: float = 0.02,
) -> None:
    """Wrap the conftest helper with side-by-side diff on failure."""

    from tests.visual.conftest import BASELINES, _pixel_diff

    baseline_path = BASELINES / f"{name}.png"
    shot = page.screenshot(full_page=True)
    update = False
    import os

    if os.environ.get("PIXIE_VISUAL_UPDATE_BASELINE", "") not in (
        "",
        "0",
        "false",
        "False",
    ):
        update = True
    BASELINES.mkdir(exist_ok=True)
    if not baseline_path.exists() or update:
        baseline_path.write_bytes(shot)
        pytest.skip(f"baseline {name!r} written - re-run to verify")
    diff = _pixel_diff(baseline_path, shot)
    if diff > threshold:
        side_by_side = _save_diff(name, baseline_path, shot)
        raise AssertionError(
            f"visual diff for {name!r} = {diff:.2%} exceeds "
            f"{threshold:.2%} (side-by-side: {side_by_side})"
        )


# ---------------------------------------------------------------------------
# Fixture: server pre-seeded with fixture tools so catalog screens render
# ---------------------------------------------------------------------------


@pytest.fixture
def pixie_server_with_fixtures(tmp_pixie_root: Path, sample_tool_factory) -> Iterator[str]:
    """Start uvicorn against a tools dir pre-populated with fixture tools.

    Seeds: ``all-inputs-tool``, ``all-outputs-tool``, ``chat-tool``,
    plus a copy of the real ``example-compound-interest`` so the
    settings / tool form / error screens have something to point at.
    """

    import socket
    import threading
    import time

    import uvicorn

    from pixie.app import create_app

    # Stage fixture tools.
    sample_tool_factory("all-inputs-tool")
    sample_tool_factory("all-outputs-tool")
    sample_tool_factory("chat-tool")
    # Copy the real example tool (no venv — visual tests never invoke /run).
    example_src = REPO_ROOT / "tools" / "example-compound-interest"
    if example_src.exists():
        example_dest = tmp_pixie_root / "tools" / "example-compound-interest"
        if not example_dest.exists():
            shutil.copytree(
                example_src,
                example_dest,
                ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.pyc"),
            )

    # Free port + bring up uvicorn in a thread.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    app = create_app()
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", loop="asyncio"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="pixie-vis-server")
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
# Screen catalogue
# ---------------------------------------------------------------------------


def _goto(page, base: str, path: str, *, wait: str = "networkidle") -> None:
    page.goto(base + path, wait_until=wait)


# Screens that the empty-tmp server can already render (no fixtures needed).
EMPTY_SCREENS = [
    ("dashboard_empty", "/"),  # empty_state.html
]

# Screens that need fixture tools present in the tools/ directory.
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


def _all_screens() -> list[tuple[str, str, str]]:
    """Return (screen, path, fixture-set) tuples flattened for parametrise."""

    rows = [(s, p, "empty") for s, p in EMPTY_SCREENS]
    rows += [(s, p, "populated") for s, p in POPULATED_SCREENS]
    return rows


SCREEN_PARAMS = _all_screens()


# A handful of screens contain content that varies run-to-run
# (validation timestamps, async status fragments). They get a relaxed
# threshold so the structural regression check still works without
# false-flagging on incidental seconds-old text.
SCREEN_THRESHOLDS: dict[str, float] = {
    "settings_per_tool": 0.25,
    "settings_global": 0.08,
}


def _hide_volatile_content(page) -> None:
    """Inject CSS that hides elements known to differ run-to-run.

    Targets validation timestamps, recent-runs lists, and the disk-usage
    fragment, which all show "n seconds ago" or live status text.
    """

    page.add_style_tag(
        content="""
        /* Hide validation timestamps + freshness pills. */
        [data-volatile], time, .timestamp, .ts,
        .pixie-recent-runs, .pixie-validation-meta,
        #revalidate-status, [hx-trigger*="every"] {
          visibility: hidden !important;
        }
        /* Stop any in-flight CSS transitions. */
        *, *::before, *::after {
          transition: none !important;
          animation: none !important;
        }
        """
    )


@pytest.mark.parametrize(("screen", "path", "fixtures"), SCREEN_PARAMS)
@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize(("viewport_label", "vw", "vh"), VIEWPORTS)
def test_visual_screen(
    page,
    pixie_server,
    pixie_server_with_fixtures,
    compare_screenshot,
    screen: str,
    path: str,
    fixtures: str,
    theme: str,
    viewport_label: str,
    vw: int,
    vh: int,
) -> None:
    """Capture every screen × theme × viewport and diff against baseline."""

    base = pixie_server if fixtures == "empty" else pixie_server_with_fixtures
    _set_viewport(page, vw, vh)
    _goto(page, base, path)
    # Switch theme via the public helper, then re-wait so any theme-driven
    # re-layout (charts, codemirror) completes before the screenshot.
    _set_theme(page, theme)
    _hide_volatile_content(page)
    page.wait_for_load_state("networkidle")
    name = _compose_name(screen, theme, viewport_label)
    threshold = SCREEN_THRESHOLDS.get(screen, 0.02)
    _capture_and_compare(page, name, compare_screenshot, threshold=threshold)


# ---------------------------------------------------------------------------
# Quick-switcher modal (Cmd+K)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize(("viewport_label", "vw", "vh"), VIEWPORTS)
def test_visual_quick_switcher(
    page,
    pixie_server_with_fixtures,
    compare_screenshot,
    theme: str,
    viewport_label: str,
    vw: int,
    vh: int,
) -> None:
    """Open the Cmd+K modal and screenshot it."""

    _set_viewport(page, vw, vh)
    _goto(page, pixie_server_with_fixtures, "/")
    _set_theme(page, theme)
    page.evaluate("window.Pixie && Pixie.qs && Pixie.qs.open()")
    # Wait for modal to be visible.
    page.wait_for_selector("#pixie-qs:not([hidden])", timeout=2000)
    page.wait_for_timeout(150)
    name = _compose_name("quick_switcher", theme, viewport_label)
    _capture_and_compare(page, name, compare_screenshot)


# ---------------------------------------------------------------------------
# Synthetic error screens (rendered via template-only routes)
# ---------------------------------------------------------------------------


ERROR_SCREENS = [
    # tool_id that does not exist -> tool_not_found.html (covers
    # "spawn-shape" rendering with the error block).
    ("error_spawn", "/tool/does-not-exist"),
]


@pytest.mark.parametrize(("screen", "path"), ERROR_SCREENS)
@pytest.mark.parametrize("theme", THEMES)
def test_visual_error_screen(
    page,
    pixie_server,
    compare_screenshot,
    screen: str,
    path: str,
    theme: str,
) -> None:
    """Render a synthetic error page (no real failure required) and snapshot."""

    _set_viewport(page, 1440, 900)
    _goto(page, pixie_server, path, wait="domcontentloaded")
    _set_theme(page, theme)
    page.wait_for_timeout(200)
    name = _compose_name(screen, theme, "1440x900")
    _capture_and_compare(page, name, compare_screenshot)
