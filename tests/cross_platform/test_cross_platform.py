"""Cross-platform smoke tests -- Phase 6f.

The Pixie source tree branches on ``sys.platform`` (and occasionally
``os.name``) in a handful of well-defined places: the launcher's
``Popen`` kwargs, the venv interpreter path, the graceful / hard
signal sender, the secrets ``.env`` permission tightening, the
artefacts directory ``chmod 0o700``, and the ``open_in_os`` reveal
helper. This module parametrises each of those over POSIX and
Windows and asserts the right branch is taken, mocking every actual
OS-level call so the suite is safe to run anywhere.

The tests do not exercise the runtime behaviour (that is what the
unit + integration suites do on the host machine); they exist to
catch regressions that only show up on the other OS.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from pixie import artefacts, cli_helpers, launcher, secrets
from pixie.config import Settings
from pixie.discovery import ToolSchema


def _make_registry(root: Path) -> artefacts.ArtefactRegistry:
    """Build an ArtefactRegistry pointed at ``root``.

    The real constructor takes a Settings instance because it needs
    ``settings.artefacts_root``; we wire one with the test-temp root.
    """

    settings = Settings(artefacts_root=root)
    return artefacts.ArtefactRegistry(settings)


# --- helpers ---------------------------------------------------------------


def _make_schema(**overrides) -> ToolSchema:
    """Build a minimal ToolSchema for launcher helpers under test."""

    base: dict[str, object] = {
        "id": "fixture-tool",
        "name": "Fixture",
        "description": "fixture",
        "version": "0.1.0",
        "entrypoint": "main:app",
        "inputs": [],
        "outputs": [],
        "max_memory_mb": 256,
        "max_runtime_seconds": 30,
    }
    base.update(overrides)
    return ToolSchema.model_validate(base)


# --- launcher: _popen_kwargs -----------------------------------------------


def test_popen_kwargs_on_windows_uses_create_new_process_group(fake_platform):
    fake_platform("win32")
    schema = _make_schema()
    kwargs = launcher._popen_kwargs(schema)
    assert kwargs == {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}


def _fake_resource_module() -> mock.MagicMock:
    """Build a stand-in for the POSIX-only ``resource`` module.

    Windows does not ship this module; ``_posix_preexec`` imports it
    lazily, so a sys.modules injection is all that's needed.
    """

    fake = mock.MagicMock()
    fake.RLIMIT_AS = 9
    fake.RLIMIT_CPU = 0
    return fake


def test_popen_kwargs_on_posix_uses_preexec_and_session(fake_platform):
    fake_platform("linux")
    schema = _make_schema()
    with mock.patch.dict(sys.modules, {"resource": _fake_resource_module()}):
        kwargs = launcher._popen_kwargs(schema)
    assert "creationflags" not in kwargs
    assert callable(kwargs["preexec_fn"])
    assert kwargs["start_new_session"] is True


def test_popen_kwargs_on_darwin_uses_preexec_branch(fake_platform):
    fake_platform("darwin")
    schema = _make_schema()
    with mock.patch.dict(sys.modules, {"resource": _fake_resource_module()}):
        kwargs = launcher._popen_kwargs(schema)
    assert "creationflags" not in kwargs
    assert kwargs["start_new_session"] is True


# --- launcher: _venv_python ------------------------------------------------


def test_venv_python_on_windows_points_at_scripts_dir(
    tmp_path: Path, fake_platform,
):
    fake_platform("win32")
    path = launcher._venv_python(tmp_path)
    assert path == tmp_path / ".venv" / "Scripts" / "python.exe"


def test_venv_python_on_posix_points_at_bin_dir(
    tmp_path: Path, fake_platform,
):
    fake_platform("linux")
    path = launcher._venv_python(tmp_path)
    assert path == tmp_path / ".venv" / "bin" / "python"


def test_venv_python_on_darwin_points_at_bin_dir(
    tmp_path: Path, fake_platform,
):
    fake_platform("darwin")
    path = launcher._venv_python(tmp_path)
    assert path.parts[-2:] == ("bin", "python")


# --- launcher: graceful / hard signal sender -------------------------------


def test_send_graceful_on_windows_uses_ctrl_break(fake_platform):
    fake_platform("win32")
    process = mock.MagicMock()
    launcher._send_graceful(process)
    process.send_signal.assert_called_once_with(signal.CTRL_BREAK_EVENT)
    process.terminate.assert_not_called()


def test_send_graceful_on_windows_falls_back_to_terminate(fake_platform):
    fake_platform("win32")
    process = mock.MagicMock()
    process.send_signal.side_effect = OSError("denied")
    launcher._send_graceful(process)
    process.terminate.assert_called_once()


def test_send_graceful_on_posix_uses_sigterm_via_killpg(fake_platform):
    fake_platform("linux")
    process = mock.MagicMock()
    process.pid = 4242
    with mock.patch("pixie.launcher.os.killpg", create=True) as killpg:
        launcher._send_graceful(process)
    killpg.assert_called_once_with(4242, signal.SIGTERM)
    process.terminate.assert_not_called()


def test_send_graceful_on_posix_falls_back_to_terminate(fake_platform):
    fake_platform("linux")
    process = mock.MagicMock()
    process.pid = 99
    with mock.patch(
        "pixie.launcher.os.killpg", create=True, side_effect=ProcessLookupError,
    ):
        launcher._send_graceful(process)
    process.terminate.assert_called_once()


def test_send_hard_on_windows_uses_kill(fake_platform):
    fake_platform("win32")
    process = mock.MagicMock()
    launcher._send_hard(process)
    process.kill.assert_called_once()


def test_send_hard_on_posix_uses_sigkill_via_killpg(fake_platform):
    fake_platform("linux")
    process = mock.MagicMock()
    process.pid = 11
    # signal.SIGKILL does not exist on Windows; inject it.
    fake_sigkill = 9
    with mock.patch("pixie.launcher.signal.SIGKILL", fake_sigkill, create=True), \
         mock.patch("pixie.launcher.os.killpg", create=True) as killpg:
        launcher._send_hard(process)
    killpg.assert_called_once_with(11, fake_sigkill)


def test_send_hard_on_posix_falls_back_to_kill(fake_platform):
    fake_platform("linux")
    process = mock.MagicMock()
    process.pid = 13
    with mock.patch("pixie.launcher.signal.SIGKILL", 9, create=True), \
         mock.patch(
             "pixie.launcher.os.killpg", create=True,
             side_effect=ProcessLookupError,
         ):
        launcher._send_hard(process)
    process.kill.assert_called_once()


# --- launcher: ALLOWED_PARENT_ENV is a stable contract ---------------------


@pytest.mark.parametrize(
    "key",
    ["PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "TEMP", "TMP",
     "APPDATA", "LOCALAPPDATA", "LANG", "PYTHONHOME"],
)
def test_launcher_allowed_parent_env_contains(key: str) -> None:
    assert key in launcher.ALLOWED_PARENT_ENV


# --- secrets: restrict_permissions -----------------------------------------


def test_restrict_permissions_on_windows_is_a_noop(
    tmp_path: Path, fake_platform,
):
    fake_platform("win32")
    target = tmp_path / ".env"
    target.write_text("X=1", encoding="utf-8")
    with mock.patch("pixie.secrets.os.chmod") as chmod:
        secrets._restrict_permissions(target)
    chmod.assert_not_called()


def test_restrict_permissions_on_posix_chmods_600(
    tmp_path: Path, fake_platform,
):
    fake_platform("linux")
    target = tmp_path / ".env"
    target.write_text("X=1", encoding="utf-8")
    with mock.patch("pixie.secrets.os.chmod") as chmod:
        secrets._restrict_permissions(target)
    chmod.assert_called_once_with(target, 0o600)


def test_restrict_permissions_on_posix_swallows_perm_error(
    tmp_path: Path, fake_platform,
):
    fake_platform("linux")
    target = tmp_path / ".env"
    target.write_text("X=1", encoding="utf-8")
    with mock.patch(
        "pixie.secrets.os.chmod", side_effect=PermissionError("denied")
    ):
        secrets._restrict_permissions(target)  # must not raise


def test_secrets_atomic_write_uses_os_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    target = tmp_path / ".env"
    with mock.patch(
        "pixie.secrets.os.replace", wraps=os.replace,
    ) as replace_spy:
        secrets._atomic_write(target, 'KEY="value"\n')
    replace_spy.assert_called_once()
    # And the data is on disk.
    assert target.exists() and "KEY" in target.read_text(encoding="utf-8")


# --- artefacts: ensure run_dir chmod 0o700 on POSIX, no-op on Windows ------


def test_artefacts_ensure_run_dir_chmods_on_posix(
    tmp_path: Path, fake_platform,
):
    fake_platform("linux")
    registry = _make_registry(tmp_path / "artefacts")
    with mock.patch("pathlib.Path.chmod", autospec=True) as chmod_spy:
        registry.get_run_dir("fixture-tool", "abc123", day="2026-01-01")
    # Exactly one chmod(0o700) for the run dir on POSIX.
    chmod_calls = [c for c in chmod_spy.call_args_list if c.args[1] == 0o700]
    assert chmod_calls, "expected at least one chmod(0o700) on POSIX"


def test_artefacts_ensure_run_dir_skips_chmod_on_windows(
    tmp_path: Path, fake_platform,
):
    fake_platform("win32")
    registry = _make_registry(tmp_path / "artefacts")
    with mock.patch("pathlib.Path.chmod", autospec=True) as chmod_spy:
        registry.get_run_dir("fixture-tool", "abc123", day="2026-01-01")
    chmod_calls = [c for c in chmod_spy.call_args_list if c.args[1] == 0o700]
    assert chmod_calls == []


# --- artefacts: forward-slash relative paths in URLs -----------------------


def test_artefacts_relative_path_uses_forward_slashes(
    tmp_path: Path,
):
    """``rel(...)`` must always produce a URL-safe forward-slash path.

    On Windows the raw resolve would emit backslashes, which would
    break the static/href contract.
    """

    root = tmp_path / "artefacts"
    root.mkdir()
    nested = root / "tool" / "day" / "run" / "file.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("x", encoding="utf-8")
    registry = _make_registry(root)
    rel = registry.rel(nested)
    assert "\\" not in rel
    assert rel.endswith("file.txt")


# --- cli_helpers.open_in_os: per-platform reveal ---------------------------


def test_open_in_os_on_windows_calls_startfile(
    tmp_path: Path, fake_platform,
):
    fake_platform("win32")
    target = tmp_path / "thing"
    target.mkdir()

    fake_os = mock.MagicMock()
    with mock.patch.dict(sys.modules, {"os": fake_os}):
        # Re-import isn't needed -- the helper does a local import of os.
        cli_helpers.open_in_os(target)
    fake_os.startfile.assert_called_once_with(str(target))


def test_open_in_os_on_macos_uses_open(
    tmp_path: Path, fake_platform,
):
    fake_platform("darwin")
    target = tmp_path / "thing"
    target.mkdir()
    with mock.patch("pixie.cli_helpers.subprocess.Popen") as popen, \
         mock.patch("pixie.cli_helpers.shutil.which", return_value="/usr/bin/open"):
        cli_helpers.open_in_os(target)
    args, kwargs = popen.call_args
    assert args[0][0] == "/usr/bin/open"
    assert args[0][1] == str(target)


def test_open_in_os_on_linux_uses_xdg_open(
    tmp_path: Path, fake_platform,
):
    fake_platform("linux")
    target = tmp_path / "thing"
    target.mkdir()
    with mock.patch("pixie.cli_helpers.subprocess.Popen") as popen, \
         mock.patch(
             "pixie.cli_helpers.shutil.which", return_value="/usr/bin/xdg-open",
         ):
        cli_helpers.open_in_os(target)
    args, _ = popen.call_args
    assert args[0][0] == "/usr/bin/xdg-open"
    assert args[0][1] == str(target)


def test_open_in_os_linux_falls_back_to_default_path_when_which_returns_none(
    tmp_path: Path, fake_platform,
):
    fake_platform("linux")
    target = tmp_path / "x"
    target.mkdir()
    with mock.patch("pixie.cli_helpers.subprocess.Popen") as popen, \
         mock.patch("pixie.cli_helpers.shutil.which", return_value=None):
        cli_helpers.open_in_os(target)
    assert popen.call_args.args[0][0] == "/usr/bin/xdg-open"


# --- atomic file replace: os.replace must work on both platforms -----------


def test_os_replace_works_for_partial_pattern(tmp_path: Path):
    """The launcher / secrets / artefacts modules rely on ``os.replace``
    being atomic on both POSIX and Windows. Confirm the call signature
    doesn't blow up across either platform branch.
    """

    src = tmp_path / "file.partial"
    dst = tmp_path / "file"
    src.write_text("payload", encoding="utf-8")
    os.replace(src, dst)
    assert dst.read_text(encoding="utf-8") == "payload"
    assert not src.exists()


# --- url-vs-fs path separator policy ---------------------------------------


def test_artefact_url_pattern_never_contains_backslash(tmp_path: Path):
    """Even when ``Path`` on Windows yields backslashes, the artefact
    relative key the renderer hands to templates must be POSIX-style.
    """

    root = tmp_path / "artefacts"
    root.mkdir()
    deep = root / "t" / "d" / "r" / "x.png"
    deep.parent.mkdir(parents=True)
    deep.write_text("x", encoding="utf-8")
    registry = _make_registry(root)
    assert "/" in registry.rel(deep)
    assert "\\" not in registry.rel(deep)


# --- db: sqlite path separator policy --------------------------------------


def test_db_path_string_form_works_with_both_separators(tmp_path: Path):
    """Sanity: passing a Path to sqlite3.connect works without manual
    separator translation.
    """

    import sqlite3
    p = tmp_path / "x" / "y" / "pixie.db"
    p.parent.mkdir(parents=True)
    con = sqlite3.connect(str(p))
    try:
        con.execute("CREATE TABLE t (x INT)")
        con.commit()
    finally:
        con.close()
    assert p.exists()


# --- launcher posix preexec covers setsid + rlimit branches ----------------


def test_posix_preexec_closure_is_callable_when_resource_present():
    # Inject a fake ``resource`` so the test runs on Windows too.
    with mock.patch.dict(sys.modules, {"resource": _fake_resource_module()}):
        closure = launcher._posix_preexec(64, 1)
    # We do NOT call the closure (would alter the host's rlimit / setsid
    # the current process). Existence + callability is enough.
    assert callable(closure)


def test_posix_preexec_zero_caps_still_returns_closure():
    with mock.patch.dict(sys.modules, {"resource": _fake_resource_module()}):
        closure = launcher._posix_preexec(0, 0)
    assert callable(closure)


# --- secrets serialiser is platform-independent ----------------------------


def test_secrets_serialise_round_trip_independent_of_platform(tmp_path: Path):
    """``_serialise`` + ``read_env`` round-trip on both POSIX/Windows
    because we always write with ``newline="\\n"``.
    """

    target = tmp_path / ".env"
    payload = secrets._serialise({"FOO": 'a"b\\c', "BAR": "baz"})
    target.write_text(payload, encoding="utf-8")
    rehydrated = secrets.read_env(tmp_path)
    assert rehydrated["FOO"] == 'a"b\\c'
    assert rehydrated["BAR"] == "baz"


# --- artefact registry's reserved-dir guard ---------------------------------


@pytest.mark.parametrize("reserved", ["_thumbs", "_quarantine", "_exports"])
def test_artefacts_reserved_tool_id_prefix_refused_on_all_platforms(
    tmp_path: Path, reserved: str,
):
    registry = _make_registry(tmp_path / "artefacts")
    with pytest.raises(artefacts.ArtefactPathError):
        registry.get_run_dir(reserved, "run-1", day="2026-01-01")
