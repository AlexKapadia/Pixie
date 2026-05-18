"""Streaming SSE proxy coverage.

Wave 2 (Phase 6b integration agent) implements the full streaming
fixture and assertions. The placeholder below pins the test name so
the agent's plan picks it up.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Wave 2: streaming integration coverage")
def test_sse_round_trip_against_streaming_tool() -> None:
    pass
