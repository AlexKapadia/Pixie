"""Tool subprocess launcher.

Owns the lifecycle of every tool child process: free-port allocation
(bind ``127.0.0.1:0``), spawn via ``asyncio.create_subprocess_exec``
against the tool's own ``.venv`` interpreter, health polling against
``/healthz``, warm-keep with a global LRU cap, and graceful shutdown
(``SIGTERM`` -> wait 5s -> ``SIGKILL`` on POSIX; ``CTRL_BREAK_EVENT``
or ``terminate()`` then ``kill()`` on Windows).

Tools are never imported into the Pixie process. The launcher is the
only module that touches ``subprocess`` or ``asyncio.subprocess``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from collections import deque
from contextlib import closing, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values

from pixie.config import Settings
from pixie.discovery import DiscoveredTool, ToolSchema

logger = logging.getLogger("pixie.launcher")

HEALTHZ_INTERVAL_S = 0.1
HEALTHZ_TIMEOUT_S = 30.0
SWEEPER_INTERVAL_S = 10.0
STDERR_RING_BYTES = 64 * 1024

ALLOWED_PARENT_ENV = (
    "PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP",
    "LANG", "LC_ALL", "LC_CTYPE", "PYTHONHOME",
)


class LauncherError(RuntimeError):
    """Base for launcher failures (spawn timeout, schema fetch failure, etc.)."""


class ToolSpawnTimeout(LauncherError):
    pass


class StderrRing:
    """Bounded byte buffer holding the last ``max_bytes`` of child stderr."""

    def __init__(self, max_bytes: int = STDERR_RING_BYTES) -> None:
        self._chunks: deque[bytes] = deque()
        self._total = 0
        self._max = max_bytes

    def feed(self, chunk: bytes) -> None:
        self._chunks.append(chunk)
        self._total += len(chunk)
        while self._total > self._max and self._chunks:
            dropped = self._chunks.popleft()
            self._total -= len(dropped)

    def snapshot(self) -> str:
        return b"".join(self._chunks).decode("utf-8", "replace")


@dataclass
class RunningTool:
    tool_id: str
    process: asyncio.subprocess.Process
    port: int
    started_at: float
    last_used: float
    stderr_ring: StderrRing = field(default_factory=StderrRing)
    stderr_task: asyncio.Task[None] | None = None
    # Run IDs we've POSTed to /run that haven't yet returned. Used by the
    # cancel handler to know when a soft /cancel has actually drained.
    in_flight_runs: set[str] = field(default_factory=set)


def _free_port() -> int:
    """Ask the kernel for a free loopback port. Spawn immediately after."""

    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _venv_python(tool_path: Path) -> Path:
    if sys.platform == "win32":
        return tool_path / ".venv" / "Scripts" / "python.exe"
    return tool_path / ".venv" / "bin" / "python"


def _build_child_env(
    tool_path: Path,
    *,
    run_id: str | None = None,
    artefacts_dir: Path | None = None,
    pyc_cache_dir: Path | None = None,
) -> dict[str, str]:
    base = {k: v for k, v in os.environ.items() if k in ALLOWED_PARENT_ENV}
    env_path = tool_path / ".env"
    if env_path.exists():
        for key, value in dotenv_values(env_path).items():
            if value is not None:
                base[key] = value
    base["PYTHONUNBUFFERED"] = "1"
    if pyc_cache_dir is not None:
        base["PYTHONPYCACHEPREFIX"] = str(pyc_cache_dir)
    else:
        base["PYTHONDONTWRITEBYTECODE"] = "1"
    if run_id is not None:
        base["PIXIE_RUN_ID"] = run_id
    if artefacts_dir is not None:
        base["PIXIE_RUN_ARTEFACTS_DIR"] = str(artefacts_dir)
    return base


def _posix_preexec(max_memory_mb: int, max_runtime_seconds: int):
    """Returned closure runs in the child between fork() and exec()."""

    import resource

    def apply() -> None:
        if max_memory_mb:
            cap = max_memory_mb * 1024 * 1024
            with suppress(ValueError, OSError):
                resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
        if max_runtime_seconds:
            with suppress(ValueError, OSError):
                resource.setrlimit(
                    resource.RLIMIT_CPU,
                    (max_runtime_seconds, max_runtime_seconds + 5),
                )
        os.setsid()

    return apply


def _popen_kwargs(schema: ToolSchema) -> dict[str, Any]:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {
        "preexec_fn": _posix_preexec(schema.max_memory_mb, schema.max_runtime_seconds),
        "start_new_session": True,
    }


async def _pump_stderr(process: asyncio.subprocess.Process, ring: StderrRing) -> None:
    assert process.stderr is not None
    while True:
        chunk = await process.stderr.read(4096)
        if not chunk:
            return
        ring.feed(chunk)


def _send_graceful(process: asyncio.subprocess.Process) -> None:
    if sys.platform == "win32":
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
        except (OSError, ValueError):
            process.terminate()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            process.terminate()


def _send_hard(process: asyncio.subprocess.Process) -> None:
    if sys.platform == "win32":
        process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()


class Launcher:
    """Spawns, tracks, and reaps tool subprocesses."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.client = client
        self.processes: dict[str, RunningTool] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        # Per-tool serialisation locks for tools with `concurrent: false`.
        # Lazily allocated on first run; never freed (cheap, single-user app).
        self.concurrent_locks: dict[str, asyncio.Lock] = {}
        self.sweeper_task: asyncio.Task[None] | None = None
        # Tools the user has pinned warm — immune to LRU eviction.
        self.pinned_warm: set[str] = set()
        # In-flight prewarm tasks (fire-and-forget). Stored so they don't
        # get GC'd while pending.
        self._prewarm_tasks: set[asyncio.Task[Any]] = set()

    def set_pinned_warm(self, tool_id: str, on: bool) -> None:
        """Mark a tool as eviction-immune (or release that hold).

        Persists nothing here — the database row is the source of truth;
        this is the in-memory cache the eviction loop consults.
        """

        if on:
            self.pinned_warm.add(tool_id)
        else:
            self.pinned_warm.discard(tool_id)

    def prewarm(self, tool: DiscoveredTool) -> None:
        """Schedule a fire-and-forget spawn for hover-prewarm.

        Bails immediately if the tool is already warm or the warm pool
        is full (we never evict on hover, only on click).
        """

        if tool.schema is None:
            return
        if self.is_running(tool.tool_id):
            self.touch(tool.tool_id)
            return
        if len(self.processes) >= self.settings.warm_keep_max:
            return

        async def _run() -> None:
            try:
                await self.ensure_running(tool)
            except Exception as exc:  # noqa: BLE001 — hover errors stay silent
                logger.info("prewarm failed for %s: %s", tool.tool_id, exc)

        task = asyncio.create_task(_run(), name=f"pixie-prewarm-{tool.tool_id}")
        self._prewarm_tasks.add(task)
        task.add_done_callback(self._prewarm_tasks.discard)

    def get_concurrent_lock(self, tool_id: str) -> asyncio.Lock:
        """Lock used to serialise /run calls for tools that opt out of concurrency."""

        lock = self.concurrent_locks.get(tool_id)
        if lock is None:
            lock = asyncio.Lock()
            self.concurrent_locks[tool_id] = lock
        return lock

    # --- public lifecycle ---------------------------------------------------

    def start_sweeper(self) -> asyncio.Task[None]:
        self.sweeper_task = asyncio.create_task(self._sweeper(), name="pixie-sweeper")
        return self.sweeper_task

    def touch(self, tool_id: str) -> None:
        running = self.processes.get(tool_id)
        if running:
            running.last_used = time.monotonic()

    def is_running(self, tool_id: str) -> bool:
        running = self.processes.get(tool_id)
        return bool(running and running.process.returncode is None)

    def list_running(self) -> list[RunningTool]:
        return [r for r in self.processes.values() if r.process.returncode is None]

    async def ensure_running(self, tool: DiscoveredTool) -> int:
        """Return the port of a healthy subprocess for ``tool``, spawning if needed.

        Holds a per-tool lock for the spawn-or-reuse decision. The check-
        inside-lock pattern is essential: two concurrent callers must
        observe one another's spawn instead of racing to spawn twice.
        """

        if tool.schema is None:
            raise LauncherError(f"tool {tool.tool_id!r} has no valid schema")
        lock = self.locks.setdefault(tool.tool_id, asyncio.Lock())
        async with lock:
            existing = self.processes.get(tool.tool_id)
            if existing and existing.process.returncode is None:
                existing.last_used = time.monotonic()
                return existing.port
            if existing:
                # Stale entry from a dead process — drop and re-spawn.
                self.processes.pop(tool.tool_id, None)
            running = await self._spawn(tool)
            self.processes[tool.tool_id] = running
            await self._enforce_warm_cap()
            return running.port

    async def stop(self, tool_id: str, grace: float = 5.0) -> None:
        running = self.processes.pop(tool_id, None)
        if not running:
            return
        await self._terminate(running, grace)

    async def stop_all(self) -> None:
        if not self.processes:
            return
        items = list(self.processes.items())
        self.processes.clear()
        await asyncio.gather(
            *(self._terminate(r, 5.0) for _, r in items),
            return_exceptions=True,
        )
        if self.sweeper_task and not self.sweeper_task.done():
            self.sweeper_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.sweeper_task

    # --- internal helpers ---------------------------------------------------

    async def _spawn(self, tool: DiscoveredTool) -> RunningTool:
        schema = tool.schema
        assert schema is not None
        # Cache the schema so the memory-budget calculation can read
        # max_memory_mb without re-discovering on every eviction tick.
        if not hasattr(self, "_schema_cache"):
            self._schema_cache: dict[str, ToolSchema] = {}
        self._schema_cache[tool.tool_id] = schema
        python = _venv_python(tool.path)
        if not python.exists():
            raise LauncherError(
                f"missing venv for {tool.tool_id!r}: expected {python} (run `uv sync`)"
            )
        port = _free_port()
        artefacts_root = getattr(self.settings, "artefacts_root", None)
        # Pyc cache prefix (RESEARCH_perf_dx s1 + DECISIONS item 3).
        pyc_cache = None
        if artefacts_root is not None:
            pyc_cache = artefacts_root.parent / ".cache" / "pyc" / tool.tool_id
        env = _build_child_env(tool.path, pyc_cache_dir=pyc_cache)
        if artefacts_root is not None:
            env["PIXIE_ARTEFACTS_ROOT"] = str(artefacts_root)
            env["PIXIE_TOOL_ID"] = tool.tool_id
        logger.info("spawning tool %s on port %d", tool.tool_id, port)
        process = await asyncio.create_subprocess_exec(
            str(python), "main.py", "--port", str(port),
            cwd=str(tool.path),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **_popen_kwargs(schema),
        )
        now = time.monotonic()
        running = RunningTool(
            tool_id=tool.tool_id, process=process, port=port,
            started_at=now, last_used=now,
        )
        running.stderr_task = asyncio.create_task(
            _pump_stderr(process, running.stderr_ring),
            name=f"pixie-stderr-{tool.tool_id}",
        )
        try:
            await self._wait_healthy(running)
            await self._fetch_and_check_schema(running, schema)
        except Exception:
            await self._terminate(running, grace=2.0)
            raise
        return running

    async def _wait_healthy(self, running: RunningTool) -> None:
        deadline = asyncio.get_running_loop().time() + HEALTHZ_TIMEOUT_S
        url = f"http://127.0.0.1:{running.port}/healthz"
        while True:
            if running.process.returncode is not None:
                stderr_tail = running.stderr_ring.snapshot()
                raise LauncherError(
                    f"{running.tool_id}: process exited with code "
                    f"{running.process.returncode} during startup\n"
                    f"--- stderr ---\n{stderr_tail}"
                )
            try:
                response = await self.client.get(url, timeout=1.0)
                if response.status_code == 200:
                    return
            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError,
                    httpx.ConnectTimeout, httpx.ReadTimeout):
                pass
            if asyncio.get_running_loop().time() > deadline:
                raise ToolSpawnTimeout(
                    f"{running.tool_id}: /healthz did not return 200 within "
                    f"{HEALTHZ_TIMEOUT_S}s"
                )
            await asyncio.sleep(HEALTHZ_INTERVAL_S)

    async def _fetch_and_check_schema(
        self, running: RunningTool, disk_schema: ToolSchema
    ) -> None:
        url = f"http://127.0.0.1:{running.port}/schema"
        try:
            response = await self.client.get(url, timeout=5.0)
            response.raise_for_status()
            live = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            logger.warning("schema fetch failed for %s: %s", running.tool_id, exc)
            return
        disk = disk_schema.model_dump(mode="json", exclude_none=False)
        if live.get("id") != disk.get("id"):
            logger.warning(
                "schema drift on %s: id %r vs %r",
                running.tool_id, disk.get("id"), live.get("id"),
            )

    async def _terminate(self, running: RunningTool, grace: float) -> None:
        if running.process.returncode is None:
            _send_graceful(running.process)
            try:
                await asyncio.wait_for(running.process.wait(), timeout=grace)
            except asyncio.TimeoutError:
                _send_hard(running.process)
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(running.process.wait(), timeout=2.0)
        if running.stderr_task and not running.stderr_task.done():
            running.stderr_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await running.stderr_task
        logger.info("stopped tool %s (exit=%s)", running.tool_id, running.process.returncode)

    def _system_ram_mb(self) -> int | None:
        """Return total system RAM in MB, or None if psutil is unavailable."""

        try:
            import psutil  # type: ignore
        except ImportError:
            return None
        try:
            return int(psutil.virtual_memory().total / (1024 * 1024))
        except Exception:  # noqa: BLE001
            return None

    def _memory_budget_mb(self) -> int | None:
        """Total RAM the warm pool may collectively claim (40% of system)."""

        ram = self._system_ram_mb()
        if ram is None:
            return None
        return int(ram * 0.4)

    async def _enforce_warm_cap(self) -> None:
        """Evict LRU tools until both the slot cap AND memory budget hold.

        Pinned-warm tools are immune. Within the eligible pool, eviction
        prefers tools with the highest declared ``max_memory_mb`` (cost-
        weighted LRU), tie-broken by oldest ``last_used``.
        """

        cap = self.settings.warm_keep_max

        def evictable() -> list[RunningTool]:
            return [
                r for r in self.processes.values()
                if r.tool_id not in self.pinned_warm
            ]

        # Phase 1: slot cap.
        while len(self.processes) > cap and evictable():
            ordered = sorted(evictable(), key=lambda r: r.last_used)
            victim = ordered[0]
            self.processes.pop(victim.tool_id, None)
            logger.info("evicting %s for LRU cap", victim.tool_id)
            await self._terminate(victim, grace=3.0)

        # Phase 2: memory budget. Skip if psutil unavailable or no hints.
        budget_mb = self._memory_budget_mb()
        if budget_mb is None:
            return
        schemas = getattr(self, "_schema_cache", {})

        def estimated_mb(running: RunningTool) -> int:
            schema = schemas.get(running.tool_id)
            if schema is not None and schema.max_memory_mb:
                return schema.max_memory_mb
            return 512  # default budget hint per RESEARCH_scale s6.3

        total = sum(estimated_mb(r) for r in self.processes.values())
        while total > budget_mb and evictable():
            # Cost-weighted: prefer evicting the heaviest LRU tool.
            ordered = sorted(
                evictable(),
                key=lambda r: (-estimated_mb(r), r.last_used),
            )
            victim = ordered[0]
            self.processes.pop(victim.tool_id, None)
            logger.info(
                "evicting %s for memory budget (%d MB > %d MB)",
                victim.tool_id, total, budget_mb,
            )
            await self._terminate(victim, grace=3.0)
            total = sum(estimated_mb(r) for r in self.processes.values())

    async def _sweeper(self) -> None:
        try:
            while True:
                await asyncio.sleep(SWEEPER_INTERVAL_S)
                try:
                    await self._sweep_once()
                except Exception as exc:  # never let the sweeper die
                    logger.exception("sweeper iteration failed: %s", exc)
        except asyncio.CancelledError:
            return

    async def _sweep_once(self) -> None:
        now = time.monotonic()
        # Snapshot to allow safe mutation.
        idle: list[RunningTool] = []
        for running in list(self.processes.values()):
            # Per-tool warm_keep isn't stored on RunningTool; consult settings
            # default. Real per-tool value is enforced via schema when needed.
            keep = self.settings.warm_keep_seconds
            if running.process.returncode is not None:
                idle.append(running)
            elif now - running.last_used > keep:
                idle.append(running)
        for running in idle:
            self.processes.pop(running.tool_id, None)
            logger.info("warm-keep expired for %s", running.tool_id)
            await self._terminate(running, grace=3.0)
        await self._enforce_warm_cap()
