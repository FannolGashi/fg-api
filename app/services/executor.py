"""
Isolated script execution.

Each endpoint gets its own asyncio.Semaphore to cap concurrency.
Scripts run in their dedicated venv with a minimal, clean environment.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

from app.config import settings
from app.models import Endpoint
from app.services.venv_manager import get_script_dir, get_script_path, get_venv_python

logger = logging.getLogger(__name__)

_semaphores: dict[int, asyncio.Semaphore] = {}

# Minimal env passed to every subprocess — no leaked secrets
_BASE_ENV = {k: v for k, v in os.environ.items() if k in {
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "TZ",
}}


def invalidate_semaphore(endpoint_id: int) -> None:
    _semaphores.pop(endpoint_id, None)


@dataclass
class ExecutionResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    duration_ms: int = 0
    timed_out: bool = False
    error: Optional[str] = None


async def execute(endpoint: Endpoint) -> ExecutionResult:
    if endpoint.id not in _semaphores:
        _semaphores[endpoint.id] = asyncio.Semaphore(endpoint.max_concurrent)
    sem = _semaphores[endpoint.id]

    # Reject immediately if all slots are taken
    if sem._value == 0:  # type: ignore[attr-defined]
        return ExecutionResult(
            exit_code=-1,
            error=f"Too many concurrent executions (limit={endpoint.max_concurrent})",
        )

    await sem.acquire()
    try:
        return await _run(endpoint)
    finally:
        sem.release()


async def _run(endpoint: Endpoint) -> ExecutionResult:
    script_path = get_script_path(endpoint.name)
    script_dir  = get_script_dir(endpoint.name)
    python      = get_venv_python(endpoint.name)

    if not script_path.exists():
        return ExecutionResult(exit_code=1, error="script.py not found")
    if not python.exists():
        return ExecutionResult(exit_code=1, error="Venv not ready")

    env = {**_BASE_ENV, "PYTHONUNBUFFERED": "1"}
    t0 = time.monotonic()

    try:
        proc = await asyncio.create_subprocess_exec(
            str(python), str(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(script_dir),
            env=env,
        )
        try:
            raw_out, raw_err = await asyncio.wait_for(
                proc.communicate(), timeout=endpoint.timeout
            )
            ms = int((time.monotonic() - t0) * 1000)
            stdout = raw_out[: settings.max_output_bytes].decode(errors="replace")
            stderr = raw_err[: settings.max_output_bytes].decode(errors="replace")
            logger.info("endpoint=%s exit=%s %dms", endpoint.name, proc.returncode, ms)
            return ExecutionResult(stdout=stdout, stderr=stderr,
                                   exit_code=proc.returncode or 0, duration_ms=ms)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            ms = int((time.monotonic() - t0) * 1000)
            logger.warning("endpoint=%s timed out after %ds", endpoint.name, endpoint.timeout)
            return ExecutionResult(
                stderr=f"Timed out after {endpoint.timeout}s",
                exit_code=-1, duration_ms=ms, timed_out=True,
            )
    except Exception as exc:
        logger.exception("endpoint=%s error: %s", endpoint.name, exc)
        return ExecutionResult(exit_code=1, error=str(exc))
