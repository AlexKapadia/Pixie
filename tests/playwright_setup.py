"""One-time Playwright browser-download helper.

Run ``uv run python tests/playwright_setup.py`` once per machine before
running the ``visual`` / ``a11y`` / ``e2e`` test markers. The script
downloads the Chromium binary that Playwright drives. It is idempotent
- subsequent runs verify the install and exit quickly.

CI must run this as a step before ``PIXIE_RUN_HEAVY_TESTS=1 uv run pytest``.
"""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
    print("running:", " ".join(cmd))
    result = subprocess.run(cmd, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
