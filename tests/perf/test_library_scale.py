"""Library page render at N=200 artefacts (≤ 1 s).

Pre-populates the SQLite DB with 200 artefact rows (and the runs they
belong to), then hits ``GET /library`` against a live server and
asserts the wall-clock is under the budget.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import Iterator

import httpx
import pytest

from pixie import db as pixie_db


def _seed_artefacts(db_path: Path, count: int) -> None:
    pixie_db.init_db(db_path)
    # Insert N runs first, then N artefact rows each pointing at one.
    import sqlite3

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        for i in range(count):
            run_id = f"perf-run-{i:04d}"
            conn.execute(
                "INSERT INTO runs(id, tool_id, started_at, inputs_json, status) "
                "VALUES(?, ?, ?, ?, 'ok')",
                (run_id, "compound-interest", "2026-05-01T00:00:00Z", "{}"),
            )
            conn.execute(
                "INSERT INTO artefacts(run_id, tool_id, output_key, rel_path, "
                "filename, mime, size_bytes, sha256, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id, "compound-interest", "chart",
                    f"compound-interest/{run_id}/chart.png",
                    f"chart-{i:04d}.png", "image/png",
                    12345, f"sha-{i:04d}", "2026-05-01T00:00:00Z",
                ),
            )
        conn.commit()


@pytest.fixture
def server_with_200_artefacts(tmp_pixie_root: Path) -> Iterator[str]:
    import uvicorn

    from pixie.app import create_app

    _seed_artefacts(tmp_pixie_root / "pixie.db", count=200)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    app = create_app()
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", loop="asyncio"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="pixie-libscale")
    thread.start()

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if server.started:
            break
        time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=2.0)
        raise RuntimeError("server_with_200_artefacts failed to start")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)


def test_library_render_at_200_artefacts_under_1s(server_with_200_artefacts: str) -> None:
    """``GET /library`` returns within 1 s with N=200 artefacts staged."""

    # One warm-up to amortise template parse + cold imports.
    with httpx.Client(timeout=10.0) as client:
        client.get(server_with_200_artefacts + "/library")
        elapsed = []
        for _ in range(5):
            t0 = time.perf_counter()
            r = client.get(server_with_200_artefacts + "/library")
            elapsed.append(time.perf_counter() - t0)
            assert r.status_code == 200, f"unexpected {r.status_code}"

    median = sorted(elapsed)[len(elapsed) // 2]
    assert median < 1.0, (
        f"GET /library median {median:.3f}s exceeds 1.0s budget "
        f"(samples: {[f'{e:.3f}' for e in elapsed]})"
    )
