"""Format round-trip tests (Wave 2 placeholder).

For every (output_type, format) pair in DECISIONS s31's matrix, the
exporter must produce a non-empty file with the right mime and a
deterministic provenance footer.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Wave 2: pixie.exporters round-trip suite")
def test_format_round_trip_placeholder() -> None:
    pass
