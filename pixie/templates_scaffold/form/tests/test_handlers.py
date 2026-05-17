"""Round-trip test for {{TOOL_NAME}}'s /run endpoint."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from {{PACKAGE}}.handlers import build_app


def test_run_round_trip() -> None:
    client = TestClient(build_app())
    response = client.post(
        "/run",
        json={
            "run_id": "test",
            "inputs": {"scale": 200, "intensity": 2.0, "shape": "exponential"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "peak_value" in body
    assert "growth_chart" in body
    assert body["growth_chart"]["series"]
    assert "breakdown" in body
    assert len(body["breakdown"]["rows"]) > 0
