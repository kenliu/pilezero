"""Install the pilezero LaunchAgent on macOS.

Generates net.kenliu.pilezero.plist from live system state (uv path, Homebrew
prefix, incoming_dir from ~/.pilezero/config.toml) and loads it via launchctl.
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

LABEL = "net.kenliu.pilezero"
PLIST_NAME = f"{LABEL}.plist"
LAUNCHAGENTS = Path.home() / "Library" / "LaunchAgents"
CONFIG_DIR = Path.home() / ".pilezero"


def _homebrew_prefix() -> str:
    r = subprocess.run(["brew", "--prefix"], capture_output=True, text=True)
    if r.returncode == 0:
        return r.stdout.strip()
    for p in ("/opt/homebrew", "/usr/local"):
        if Path(p, "bin", "brew").exists():
            return p
    raise RuntimeError("Homebrew not found. Install it first: https://brew.sh")


def _uv_path() -> str:
    p = shutil.which("uv")
    if p:
        return p
    for candidate in (
        Path.home() / ".local" / "bin" / "uv",
        Path("/opt/homebrew/bin/uv"),
        Path("/usr/local/bin/uv"),
    ):
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("uv not found. Install it first: https://docs.astral.sh/uv/")


def _incoming_dir() -> str:
    config = CONFIG_DIR / "config.toml"
    if not config.exists():
        raise RuntimeError(
            f"{config} not found. Copy config.toml from the repo and edit it first."
        )
    with open(config, "rb") as f:
        data = tomllib.load(f)
    raw = data.get("incoming_dir", "")
    if not raw:
        raise RuntimeError(f"incoming_dir not set in {config}")
    return str(Path(raw).expanduser())


def _project_dir() -> str:
    # src/pilezero/install_agent.py → project root is three levels up
    return str(Path(__file__).resolve().parent.parent.parent)


def install_agent(project_dir: str | None = None, dry_run: bool = False) -> int:
    try:
        prefix = _homebrew_prefix()
        uv = _uv_path()
        watch = _incoming_dir()
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if project_dir is None:
        project_dir = _project_dir()

    homebrew_bin = str(Path(prefix) / "bin")
    path_env = f"{homebrew_bin}:/usr/bin:/bin:/usr/sbin:/sbin"

    plist: dict = {
        "Label": LABEL,
        "ProgramArguments": [uv, "run", "python", "-m", "pilezero", "run", "--quiet"],
        "WorkingDirectory": project_dir,
        "EnvironmentVariables": {"PATH": path_env},
        "WatchPaths": [watch],
        "StartInterval": 1800,
        "RunAtLoad": True,
        "StandardOutPath": str(CONFIG_DIR / "launchd.out.log"),
        "StandardErrorPath": str(CONFIG_DIR / "launchd.err.log"),
    }

    dest = LAUNCHAGENTS / PLIST_NAME

    if dry_run:
        print(f"would write: {dest}")
        print(f"  uv:          {uv}")
        print(f"  PATH:        {path_env}")
        print(f"  watch:       {watch}")
        print(f"  working dir: {project_dir}")
        return 0

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LAUNCHAGENTS.mkdir(parents=True, exist_ok=True)

    with open(dest, "wb") as f:
        plistlib.dump(plist, f)

    subprocess.run(["launchctl", "unload", str(dest)], capture_output=True)

    r = subprocess.run(["launchctl", "load", "-w", str(dest)], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"error: launchctl load failed: {r.stderr.strip()}", file=sys.stderr)
        return 1

    print(f"installed: {dest}")
    print(f"loaded:    {LABEL}")
    print(f"watching:  {watch}")
    return 0
