"""Pixie startup -> ready budget (500 ms user / 800 ms CI).

Measures the in-process portion of startup: lifespan begin (DB init,
discovery, launcher wiring) + first GET ``/`` round-trip. Excludes the
subprocess/uvicorn boot itself, which is dominated by Python module
import time and is measured separately by RESEARCH_perf_dx.md §1.4.

The conceptual budget covers the work Pixie itself does at startup:
``create_app`` → ``lifespan_context`` enter → first 200 on ``/``.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def test_pixie_startup_budget(benchmark, assert_within_budget, tmp_path: Path) -> None:
    """In-process startup (factory + lifespan + first GET /) within budget."""

    import os

    (tmp_path / "tools").mkdir()
    os.environ["PIXIE_TOOLS_DIR"] = str(tmp_path / "tools")
    os.environ["PIXIE_DB_PATH"] = str(tmp_path / "pixie.db")
    os.environ["PIXIE_REPO_ROOT"] = str(tmp_path)
    from pixie.config import get_settings

    def _start_and_first_get() -> None:
        get_settings.cache_clear()
        import uvicorn

        from pixie.app import create_app

        port = _free_port()
        app = create_app()
        config = uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="warning", loop="asyncio"
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                if server.started:
                    break
                time.sleep(0.01)
            else:
                raise AssertionError("uvicorn never started")
            with httpx.Client(timeout=2.0) as client:
                r = client.get(f"http://127.0.0.1:{port}/")
                assert r.status_code in (200, 404)
        finally:
            server.should_exit = True
            thread.join(timeout=3.0)

    benchmark.pedantic(_start_and_first_get, iterations=1, rounds=5, warmup_rounds=1)
    assert_within_budget(benchmark, "pixie_startup")
