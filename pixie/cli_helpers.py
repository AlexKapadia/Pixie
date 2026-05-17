"""Helpers shared by the CLI and HTTP layers.

Currently exposes:

* :func:`open_in_os` — reveal a path in the host file browser. Used by
  ``pixie open`` and by the per-tool "open folder" endpoint in
  :mod:`pixie.routes.settings` (single implementation, one behaviour).
* :func:`scaffold` — render a template tree from
  ``pixie/templates_scaffold/<name>/`` into ``tools/<tool_id>/`` with
  placeholder substitution in both file paths and contents.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATES_ROOT = PACKAGE_ROOT / "templates_scaffold"

_VALID_TOOL_ID = re.compile(r"^[a-z][a-z0-9-]*$")


class ScaffoldError(RuntimeError):
    """Raised when scaffold() cannot satisfy the request."""


def open_in_os(path: Path) -> None:
    """Reveal ``path`` in the host platform's default file browser.

    Windows uses ``os.startfile`` (which honours the user's file-manager
    association). macOS uses ``open``, Linux uses ``xdg-open``. The call
    is non-blocking on POSIX (we don't wait for the file manager to
    return) and propagates :class:`OSError` on failure so the caller can
    decide how to surface the failure.
    """

    target = str(path)
    if sys.platform == "win32":
        import os as _os  # local import: only Windows path needs it
        _os.startfile(target)  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        opener = shutil.which("open") or "/usr/bin/open"
        subprocess.Popen(
            [opener, target],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    opener = shutil.which("xdg-open") or "/usr/bin/xdg-open"
    subprocess.Popen(
        [opener, target],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def snake_case(tool_id: str) -> str:
    """Convert ``my-cool-tool`` to ``my_cool_tool`` for Python package use."""

    return tool_id.replace("-", "_")


def list_templates() -> list[dict[str, str]]:
    """Return the catalogue of scaffold templates from ``_index.json``."""

    import json

    index_path = TEMPLATES_ROOT / "_index.json"
    if not index_path.is_file():
        return []
    data = json.loads(index_path.read_text(encoding="utf-8"))
    return list(data.get("templates", []))


def _walk_template(template_root: Path) -> Iterable[Path]:
    """Yield every file under ``template_root`` (skips dot-folders we use as control)."""

    for path in sorted(template_root.rglob("*")):
        if path.is_file():
            yield path


def _substitute(content: str, context: dict[str, str]) -> str:
    for key, value in context.items():
        content = content.replace("{{" + key + "}}", value)
    return content


def _gitkeep_to_real(path: Path) -> Path:
    # We ship ``.gitkeep_`` (no leading dot) inside templates so they
    # survive packaging and globbing; rename on render.
    if path.name == "_gitkeep":
        return path.parent / ".gitkeep"
    return path


def scaffold(
    tool_id: str,
    template_name: str,
    target_root: Path,
    *,
    name: str | None = None,
    description: str | None = None,
    force: bool = False,
) -> Path:
    """Render a template tree into ``<target_root>/<tool_id>/``.

    Returns the resolved tool directory. Raises :class:`ScaffoldError`
    on validation or filesystem trouble (parent exists, unknown
    template, malformed tool id).
    """

    if not _VALID_TOOL_ID.match(tool_id):
        raise ScaffoldError(
            f"invalid tool id {tool_id!r}: must match {_VALID_TOOL_ID.pattern}"
        )

    template_dir = TEMPLATES_ROOT / template_name
    if not template_dir.is_dir():
        raise ScaffoldError(
            f"unknown template {template_name!r} (looked under {TEMPLATES_ROOT})"
        )

    destination = (target_root / tool_id).resolve()
    if destination.exists():
        if not force:
            raise ScaffoldError(
                f"refusing to overwrite existing folder: {destination}"
            )
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=False)

    package_name = snake_case(tool_id)
    display_name = name or tool_id.replace("-", " ").title()
    descr = description or f"{display_name} — a Pixie tool."

    context = {
        "TOOL_ID": tool_id,
        "TOOL_NAME": display_name,
        "DESCRIPTION": descr,
        "PACKAGE": package_name,
    }

    for source in _walk_template(template_dir):
        relative = source.relative_to(template_dir)
        # Substitute placeholders in path segments.
        rendered_parts = [_substitute(part, context) for part in relative.parts]
        rendered_rel = Path(*rendered_parts)
        rendered_rel = _gitkeep_to_real(rendered_rel)

        out_path = destination / rendered_rel
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Text files get placeholder substitution; everything else is copied
        # verbatim (we don't ship binaries in the templates today, but the
        # branch keeps the door open).
        try:
            text = source.read_text(encoding="utf-8")
            out_path.write_text(_substitute(text, context), encoding="utf-8")
        except UnicodeDecodeError:
            shutil.copyfile(source, out_path)

    return destination
