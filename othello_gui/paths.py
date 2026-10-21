"""Where things live: the repository root, the Edax executable and the WTHOR files.

One place for "the engine folder" and "the Thor folder", shared by the server,
the scripts and the tests. Only the standard library is imported here, so the
setup script can use it before any dependency is installed.

Lookup order:

    Edax    $EDAX_BIN, else engine/<platform>/ (filled by scripts/setup_edax.py),
            else a developer checkout at ../edax-reversi/bin
    WTHOR   $WTHOR_DIR, else wthor/ in this repository, else ../wthor
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # the repository folder
ENGINE_DIR = ROOT / "engine"
SIBLING_EDAX = ROOT.parent / "edax-reversi" / "bin"  # developer layout: Edax checkout next to this repo
SIBLING_WTHOR = ROOT.parent / "wthor"


def platform_tag() -> str:
    """'darwin-arm64', 'linux-x86_64', 'windows-x86_64', ... (the engine/ subfolder name)."""
    system = {"darwin": "darwin", "linux": "linux", "win32": "windows"}.get(sys.platform, sys.platform)
    machine = platform.machine().lower()
    machine = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64", "amd64": "x86_64"}.get(machine, machine)
    return f"{system}-{machine}"


def exe_name(tag: str) -> str:
    """Edax's executable name on a platform (Edax names its macOS build mEdax)."""
    return "edax.exe" if tag.startswith("windows") else "mEdax" if tag.startswith("darwin") else "edax"


def engine_usable(exe: Path) -> bool:
    """An executable whose folder also holds the evaluation weights."""
    return exe.exists() and (exe.parent / "data" / "eval.dat").exists()


def find_edax() -> Path:
    """The Edax executable to run. If none is usable, the engine/<platform>/ path is
    returned anyway so that error messages point at where setup_edax.py would put it."""
    if os.environ.get("EDAX_BIN"):
        return Path(os.environ["EDAX_BIN"]).expanduser()
    tag = platform_tag()
    candidates = [ENGINE_DIR / tag / exe_name(tag), SIBLING_EDAX / "mEdax"]
    for c in candidates:
        if engine_usable(c):
            return c
    return candidates[0]


def find_wthor() -> Path:
    """The folder with WTHOR.JOU, WTHOR.TRN and WTH_*.wtb (may not exist)."""
    if os.environ.get("WTHOR_DIR"):
        return Path(os.environ["WTHOR_DIR"]).expanduser()
    for c in (ROOT / "wthor", SIBLING_WTHOR):
        if (c / "WTHOR.JOU").exists():
            return c
    return ROOT / "wthor"


def progress_file() -> Path:
    """Training progress (lessons, drill results, scrimmages): $OTHELLO_PROGRESS or progress.json here."""
    if os.environ.get("OTHELLO_PROGRESS"):
        return Path(os.environ["OTHELLO_PROGRESS"]).expanduser()
    return ROOT / "progress.json"


def wthor_available(directory: Path | None = None) -> bool:
    return ((directory or find_wthor()) / "WTHOR.JOU").exists()
