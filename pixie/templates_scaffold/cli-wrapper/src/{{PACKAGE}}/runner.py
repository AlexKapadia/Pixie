"""Subprocess wrapper for {{TOOL_NAME}}.

The default example wraps ``ffmpeg`` — change ``CLI_NAME`` and the
``build_command`` body to wrap a different binary (tesseract,
imagemagick, pandoc, yt-dlp, etc.). Everything else (timeout, output
capture, missing-binary detection) is generic.
"""
from __future__ import annotations

import logging
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("{{PACKAGE}}.runner")

# Change this to the CLI binary your tool wraps.
CLI_NAME = "ffmpeg"
DEFAULT_TIMEOUT_SECONDS = 60


class CliMissingError(RuntimeError):
    """Raised when the wrapped binary isn't on PATH."""


class CliFailedError(RuntimeError):
    """Raised when the wrapped binary exited non-zero."""


@dataclass(frozen=True)
class CliResult:
    returncode: int
    stdout: str
    stderr: str
    output_path: Path


def find_cli() -> str | None:
    return shutil.which(CLI_NAME)


def build_command(source: Path, output: Path, extra_args: str) -> list[str]:
    """Return the argv list for the wrapped CLI.

    The default builds a minimal ffmpeg invocation that simply copies
    the input to the output (so the wrapper validates without needing
    real input). Replace this with the real invocation for your binary.
    """

    base = [CLI_NAME, "-y", "-i", str(source)]
    if extra_args.strip():
        base.extend(shlex.split(extra_args))
    base.append(str(output))
    return base


def invoke(
    source: Path,
    output: Path,
    extra_args: str = "",
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> CliResult:
    binary = find_cli()
    if binary is None:
        raise CliMissingError(
            f"{CLI_NAME} not found on PATH. Install it first, then re-run."
        )

    command = build_command(source, output, extra_args)
    logger.info("running %s", " ".join(command))
    try:
        completed = subprocess.run(  # noqa: S603 — argv is a known list
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CliFailedError(f"{CLI_NAME} timed out after {timeout}s") from exc

    if completed.returncode != 0:
        raise CliFailedError(
            f"{CLI_NAME} exited {completed.returncode}: "
            f"{completed.stderr.strip()[:500]}"
        )
    return CliResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        output_path=output,
    )
