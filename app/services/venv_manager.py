"""
Manages per-endpoint Python virtual environments.

Layout on disk:
  {VENVS_DIR}/{endpoint_name}/        — isolated venv
  {SCRIPTS_DIR}/{endpoint_name}/script.py
  {SCRIPTS_DIR}/{endpoint_name}/requirements.txt  (optional)
"""

import asyncio
import logging
import sys
from pathlib import Path

from app.config import SCRIPTS_DIR, VENVS_DIR

logger = logging.getLogger(__name__)


def get_script_dir(name: str) -> Path:
    return SCRIPTS_DIR / name


def get_script_path(name: str) -> Path:
    return SCRIPTS_DIR / name / "script.py"


def get_venv_python(name: str) -> Path:
    venv = VENVS_DIR / name
    if sys.platform == "win32":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _pip(name: str) -> Path:
    venv = VENVS_DIR / name
    if sys.platform == "win32":
        return venv / "Scripts" / "pip.exe"
    return venv / "bin" / "pip"


async def _run(args: list[str], timeout: int = 180) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, out.decode(errors="replace")
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "Timed out during venv setup"


async def setup_venv(name: str, has_requirements: bool) -> tuple[bool, str]:
    """Create venv + install requirements. Returns (ok, log_text)."""
    venv_dir = VENVS_DIR / name
    lines: list[str] = []

    lines.append(f"Creating venv at {venv_dir}...")
    code, out = await _run([sys.executable, "-m", "venv", str(venv_dir)])
    lines.append(out)
    if code != 0:
        return False, "\n".join(lines)

    pip = str(_pip(name))
    code, out = await _run([pip, "install", "--quiet", "--upgrade", "pip"])
    lines.append(out)

    if has_requirements:
        req = SCRIPTS_DIR / name / "requirements.txt"
        if req.exists():
            lines.append(f"Installing {req}...")
            code, out = await _run([pip, "install", "--quiet", "-r", str(req)])
            lines.append(out)
            if code != 0:
                return False, "\n".join(lines)

    lines.append("Done.")
    return True, "\n".join(lines)


async def rebuild_venv(name: str, has_requirements: bool) -> tuple[bool, str]:
    import shutil
    venv_dir = VENVS_DIR / name
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
    return await setup_venv(name, has_requirements)


def delete_endpoint_files(name: str) -> None:
    import shutil
    for d in [SCRIPTS_DIR / name, VENVS_DIR / name]:
        if d.exists():
            shutil.rmtree(d)
