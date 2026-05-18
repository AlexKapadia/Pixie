"""Top-level fixtures and marker wiring for the Pixie test suite.

Test layout (one directory per pytest marker)::

    tests/
      unit/         fast in-process tests
      integration/  multi-module + live-server tests
      visual/       Playwright pixel-diff regression
      format/       exporter round-trip
      perf/         pytest-benchmark budgets
      a11y/         Playwright + axe-core audits
      e2e/          full browser flows against real tools

The heavy markers (``visual``, ``perf``, ``a11y``, ``e2e``) are skipped
by default — set ``PIXIE_RUN_HEAVY_TESTS=1`` in CI (or locally before
the first visual run) to opt in. ``unit`` + ``integration`` always run.

Fixtures provided here are the ones Phase 6a-f tests will rely on:

* ``tmp_pixie_root``    — a scratch repo layout with ``tools/`` and ``pixie.db``
* ``sample_tool_factory`` — copy a ``tests/fixtures/<name>/`` tool into ``tmp_pixie_root``
* ``pixie_app``         — a fresh ``FastAPI`` instance bound to that scratch root
* ``pixie_server``      — same app served on a real localhost port (uvicorn)
* ``httpx_client``      — async client pointed at that server
* ``mock_validator_report`` — synthetic ``ValidationReport`` for UI tests
"""

from __future__ import annotations

import contextlib
import os
import shutil
import socket
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"

HEAVY_MARKERS = {"visual", "perf", "a11y", "e2e"}


# --- marker wiring -----------------------------------------------------------


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Apply per-directory markers and skip heavy markers without opt-in.

    Directory -> marker mapping is positional. A test under ``tests/unit/``
    becomes ``pytest.mark.unit`` automatically; a developer does not need
    to decorate every test by hand.
    """

    rootdir = Path(config.rootpath)
    heavy_enabled = os.environ.get("PIXIE_RUN_HEAVY_TESTS", "") not in (
        "",
        "0",
        "false",
        "False",
    )
    skip_heavy = pytest.mark.skip(
        reason="heavy test - set PIXIE_RUN_HEAVY_TESTS=1 to enable"
    )

    for item in items:
        try:
            rel = Path(item.fspath).resolve().relative_to(rootdir)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) < 2 or parts[0] != "tests":
            continue
        marker_name = parts[1]
        if marker_name in {
            "unit",
            "integration",
            "visual",
            "format",
            "perf",
            "a11y",
            "e2e",
            "cross_platform",
        }:
            item.add_marker(getattr(pytest.mark, marker_name))
        if marker_name in HEAVY_MARKERS and not heavy_enabled:
            item.add_marker(skip_heavy)


# --- scratch repo layout -----------------------------------------------------


@pytest.fixture
def tmp_pixie_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Yield a temp directory laid out as a Pixie repo.

    The ``PIXIE_*`` environment variables are patched so any code that
    calls ``get_settings()`` after the cache is cleared sees this
    scratch root. We clear the cache on entry AND exit.
    """

    (tmp_path / "tools").mkdir()
    (tmp_path / "artefacts").mkdir()
    monkeypatch.setenv("PIXIE_TOOLS_DIR", str(tmp_path / "tools"))
    monkeypatch.setenv("PIXIE_DB_PATH", str(tmp_path / "pixie.db"))
    monkeypatch.setenv("PIXIE_REPO_ROOT", str(tmp_path))
    from pixie.config import get_settings

    get_settings.cache_clear()
    try:
        yield tmp_path
    finally:
        get_settings.cache_clear()


@pytest.fixture
def sample_tool_factory(tmp_pixie_root: Path) -> Callable[..., Path]:
    """Return a factory that drops a fixture tool into ``tmp_pixie_root/tools/``.

    Usage::

        def test_example(sample_tool_factory):
            tool_dir = sample_tool_factory("all-inputs-tool")

    Pass ``with_venv=True`` to copy the example tool's real ``.venv``
    into the new tool so the launcher can spawn it. Calls to
    ``uv sync`` are deliberately NOT made - that is a skill-time
    operation per RULES.md s3. Tests that need a runnable venv must
    either reuse the example tool or stage one explicitly.
    """

    def factory(
        name: str,
        *,
        as_id: str | None = None,
        with_venv: bool = False,
    ) -> Path:
        source = FIXTURE_ROOT / name
        if not source.exists():
            raise FileNotFoundError(f"fixture {name!r} not found at {source}")
        dest_name = as_id or name
        dest = tmp_pixie_root / "tools" / dest_name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(
            source, dest, ignore=shutil.ignore_patterns(".venv", "__pycache__")
        )
        if with_venv:
            example_venv = REPO_ROOT / "tools" / "example-compound-interest" / ".venv"
            if example_venv.exists():
                shutil.copytree(example_venv, dest / ".venv", symlinks=True)
        return dest

    return factory


# --- FastAPI app / live server ----------------------------------------------


@pytest.fixture
async def pixie_app(tmp_pixie_root: Path) -> AsyncIterator:
    """Build a fresh FastAPI app whose state points at ``tmp_pixie_root``.

    The lifespan handler is exercised so ``app.state.launcher``,
    ``app.state.settings``, etc. are populated exactly as in production.
    """

    from pixie.app import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        yield app


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


@pytest.fixture
def pixie_server(tmp_pixie_root: Path) -> Iterator[str]:
    """Start uvicorn on a free loopback port in a background thread.

    Yields the base URL (``http://127.0.0.1:<port>``). The server is
    torn down on fixture exit. Threading (not multiprocessing) is used
    so the scratch ``tmp_pixie_root`` env is inherited.
    """

    import uvicorn

    from pixie.app import create_app

    port = _free_port()
    app = create_app()
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", loop="asyncio"
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True, name="pixie-test-server")
    thread.start()

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if server.started:
            break
        time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=2.0)
        raise RuntimeError("pixie_server failed to start within 10s")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)


@pytest.fixture
async def httpx_client(pixie_server: str) -> AsyncIterator[httpx.AsyncClient]:
    """Async HTTP client pre-pointed at the live Pixie server."""

    async with httpx.AsyncClient(base_url=pixie_server, timeout=10.0) as client:
        yield client


# --- validator report stub ---------------------------------------------------


@pytest.fixture
def mock_validator_report() -> Callable[..., object]:
    """Factory for synthetic ``ValidationReport`` objects.

    The renderer + UI tests want to assert on the *shape* of a report
    without running the full validator. Pass per-check overrides as
    kwargs::

        report = mock_validator_report(overall="warn", folder_structure="warn")
    """

    from pixie.validator import ValidationCheck, ValidationReport

    default_checks = [
        "folder_structure",
        "tool_json_parses",
        "schemas_coherent",
        "pyproject",
        "venv",
        "spawn",
        "schema_endpoint",
        "sample_run",
        "output_shapes",
        "streaming",
        "graceful_shutdown",
    ]

    def factory(
        *,
        tool_id: str = "fixture-tool",
        tool_path: str = "/tmp/fixture-tool",
        overall: str = "pass",
        **check_overrides: str,
    ):
        checks = []
        for name in default_checks:
            status = check_overrides.get(name, "pass")
            checks.append(
                ValidationCheck(
                    name=name,
                    status=status,  # type: ignore[arg-type]
                    message=f"{name} {status}",
                    details=None,
                )
            )
        return ValidationReport(
            tool_id=tool_id,
            tool_path=tool_path,
            timestamp=datetime.now(timezone.utc),
            overall=overall,  # type: ignore[arg-type]
            checks=checks,
            sample_inputs={"foo": "bar"},
            sample_output={"result": 42},
            spawn_log=None,
        )

    return factory


# --- Playwright (shared by visual / a11y / e2e) ------------------------------


def _playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.fixture(scope="session")
def browser():
    """Session-scoped Chromium browser handle (Playwright sync API).

    Skipped if Playwright or its bundled browsers are missing. Run
    ``uv run python tests/playwright_setup.py`` once per machine to
    download Chromium before using visual / a11y / e2e fixtures.
    """

    if not _playwright_available():
        pytest.skip("playwright not installed - uv sync --group dev")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(
                "chromium not installed - "
                "run `uv run python tests/playwright_setup.py` first "
                f"(underlying: {exc})"
            )
        try:
            yield browser
        finally:
            with contextlib.suppress(Exception):
                browser.close()


@pytest.fixture
def page(browser):
    """Function-scoped page (fresh BrowserContext per test for isolation)."""

    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()
    try:
        yield page
    finally:
        with contextlib.suppress(Exception):
            context.close()
