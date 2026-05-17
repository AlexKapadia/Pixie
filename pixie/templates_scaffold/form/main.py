"""{{TOOL_NAME}} — thin Pixie entrypoint. Binds 127.0.0.1 only.

The real logic lives in ``src/{{PACKAGE}}/``. This file only wires the
FastAPI app and the uvicorn server.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from {{PACKAGE}}.handlers import build_app  # noqa: E402

app = build_app()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
