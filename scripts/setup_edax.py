"""Fetch the Edax engine and its evaluation weights for this computer.

    uv run scripts/setup_edax.py              # set up engine/<platform>/
    uv run scripts/setup_edax.py --if-missing # do nothing if an engine is already usable
    uv run scripts/setup_edax.py --arch v3    # Linux/Windows: faster build for CPUs with AVX2

What it does, per platform:
  macOS, Apple Silicon   uses the ready-made build shipped in engine/darwin-arm64/
                         (Edax 4.7 with two small macOS fixes, see engine/README.md)
  macOS, Intel           builds Edax from source (needs Xcode command line tools: xcode-select --install)
  Linux x86-64           downloads the official Edax 4.7 Linux release
  Windows x86-64         downloads the official Edax 4.7 Windows release

Then it downloads the evaluation weights (eval.dat, 14 MB) from the Edax
repository and makes sure an opening book exists. Everything lands in
engine/<platform>/, which git ignores. Re-run with --force to refetch.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = ROOT / "engine"
EDAX_REPO = "https://github.com/abulmo/edax-reversi"
EDAX_TAG = "v4.7"
EVAL_URL = f"https://raw.githubusercontent.com/abulmo/edax-reversi/{EDAX_TAG}/bin/data/eval.dat"
EVAL_SIZE = 13_952_436
RELEASE = f"{EDAX_REPO}/releases/download/{EDAX_TAG}"
ARCHIVES = {"linux-x86_64": f"{RELEASE}/edax-4.7-linux.7z", "windows-x86_64": f"{RELEASE}/edax-4.7-windows.7z"}
BOOK_URLS: list[str] = []  # optional ready-made opening books (release assets); empty = make a minimal one
SIBLING_EDAX = ROOT.parent / "edax-reversi" / "bin"  # developer layout: Edax checkout next to this repo


def platform_tag() -> str:
    system = {"darwin": "darwin", "linux": "linux", "win32": "windows"}.get(sys.platform, sys.platform)
    machine = platform.machine().lower()
    machine = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64", "amd64": "x86_64"}.get(machine, machine)
    return f"{system}-{machine}"


def exe_name(tag: str) -> str:
    return "edax.exe" if tag.startswith("windows") else "mEdax" if tag.startswith("darwin") else "edax"


def say(msg: str) -> None:
    print(msg, flush=True)


def download(url: str, dest: Path, label: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    say(f"  downloading {label} …")
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 16):
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r    {done / 1e6:5.1f} / {total / 1e6:.1f} MB", end="", flush=True)
    print()
    tmp.replace(dest)


def cpu_level(requested: str | None) -> str:
    """Which x86-64 build to use: plain, v2 (SSE4.2/POPCNT, ~2009+) or v3 (AVX2, ~2014+)."""
    if requested:
        return requested
    flags = ""
    try:
        if sys.platform.startswith("linux"):
            flags = Path("/proc/cpuinfo").read_text().lower()
        elif sys.platform == "darwin":
            flags = subprocess.run(["sysctl", "-n", "machdep.cpu.features", "machdep.cpu.leaf7_features"], capture_output=True, text=True).stdout.lower()
    except Exception:
        pass
    if "avx2" in flags:
        return "v3"
    if "popcnt" in flags or "sse4_2" in flags or "sse4.2" in flags or not flags:
        return "v2"
    return "plain"


def extract_release(archive_url: str, dest_exe: Path, level: str) -> None:
    import py7zr  # pure-Python 7z reader (dependency of this project)

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "edax.7z"
        download(archive_url, archive, "Edax 4.7 release")
        with py7zr.SevenZipFile(archive, "r") as z:
            names = z.getnames()
            z.extractall(tmp)
        want = {"v3": "-v3", "v2": "-v2", "plain": ""}[level]
        pick = None
        for n in names:
            base = Path(n).name
            stem = base[:-4] if base.endswith(".exe") else base
            if (want and stem.endswith(want)) or (not want and stem.endswith("x86-64")):
                pick = Path(tmp) / n
        if pick is None:
            raise SystemExit(f"no matching executable in the release archive (found {names})")
        dest_exe.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(pick, dest_exe)
        dest_exe.chmod(0o755)
        say(f"  installed {pick.name} as {dest_exe.name} ({level} build)")


def build_from_source(dest_exe: Path, tag: str) -> None:
    for tool in ("git", "make", "clang"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} is required to build Edax on this platform. On macOS run: xcode-select --install")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "edax-reversi"
        say("  cloning Edax source …")
        subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--branch", EDAX_TAG, EDAX_REPO, str(src)], check=True)
        patch = ENGINE_DIR / "edax-macos-fixes.patch"
        if patch.exists():
            subprocess.run(["git", "-C", str(src), "apply", str(patch)], check=True)
        arch = "armv8.5-a" if tag.endswith("arm64") else "x86-64-v2"
        os_name = "osx" if tag.startswith("darwin") else "linux"
        say(f"  compiling Edax ({arch}) … this takes a minute")
        subprocess.run(["make", "build", f"ARCH={arch}", f"OS={os_name}", "CC=clang"], cwd=src / "src", check=True,
                       stdout=subprocess.DEVNULL)
        built = next((src / "bin").glob("*Edax*"))
        dest_exe.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(built, dest_exe)
        dest_exe.chmod(0o755)
        say(f"  built {dest_exe}")


def ensure_book(exe: Path, data: Path) -> None:
    """Edax needs data/book.dat; without one it builds a book from scratch at level 24
    on first start, which looks like a hang. Copy a local book if one exists, otherwise
    download one, otherwise create a minimal book at level 1 (instant)."""
    book = data / "book.dat"
    if book.exists():
        return
    sibling = SIBLING_EDAX / "data" / "book.dat"
    if sibling.exists() and sibling.stat().st_size > 1000:
        shutil.copy(sibling, book)
        say(f"  copied opening book from {sibling} ({book.stat().st_size / 1e6:.1f} MB)")
        return
    for url in BOOK_URLS:
        try:
            download(url, book, "opening book")
            return
        except Exception as e:  # pragma: no cover - network
            say(f"  could not download {url}: {e}")
    say("  creating a minimal opening book …")
    try:
        subprocess.run([str(exe), "-l", "1", "-q", "-book-file", str(book)], input=b"quit\n", cwd=exe.parent,
                       timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        pass
    if not book.exists():
        say("  warning: could not create a book; the first start will be slow once")


def usable(exe: Path) -> bool:
    return exe.exists() and (exe.parent / "data" / "eval.dat").exists()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--if-missing", action="store_true", help="exit immediately if an engine is already usable")
    ap.add_argument("--force", action="store_true", help="refetch even if files exist")
    ap.add_argument("--arch", choices=["plain", "v2", "v3"], help="x86-64 build level for Linux/Windows downloads")
    ap.add_argument("--platform", dest="tag", default=platform_tag(), help=argparse.SUPPRESS)
    ap.add_argument("--dest", type=Path, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()

    tag = args.tag
    dest = args.dest or ENGINE_DIR / tag
    exe = dest / exe_name(tag)
    data = dest / "data"

    if args.if_missing and not args.force:
        if usable(exe) or usable(SIBLING_EDAX / "mEdax") or os.environ.get("EDAX_BIN"):
            return

    say(f"Setting up Edax for {tag} in {dest}")
    data.mkdir(parents=True, exist_ok=True)

    if args.force or not exe.exists():
        if tag in ARCHIVES:
            extract_release(ARCHIVES[tag], exe, cpu_level(args.arch))
        elif tag == "darwin-arm64" and (ENGINE_DIR / "darwin-arm64" / "mEdax").exists() and exe != ENGINE_DIR / "darwin-arm64" / "mEdax":
            shutil.copy(ENGINE_DIR / "darwin-arm64" / "mEdax", exe)
            exe.chmod(0o755)
        elif tag == "darwin-arm64" and exe.exists():
            pass
        elif tag.startswith(("darwin", "linux")):
            build_from_source(exe, tag)
        else:
            raise SystemExit(f"no automatic setup for {tag}; build Edax yourself ({EDAX_REPO}) and set EDAX_BIN")
    else:
        say(f"  engine present: {exe}")

    eval_file = data / "eval.dat"
    if args.force or not eval_file.exists() or eval_file.stat().st_size != EVAL_SIZE:
        sibling_eval = SIBLING_EDAX / "data" / "eval.dat"
        if sibling_eval.exists() and sibling_eval.stat().st_size == EVAL_SIZE:
            shutil.copy(sibling_eval, eval_file)
            say("  copied evaluation weights from the Edax checkout next to this folder")
        else:
            download(EVAL_URL, eval_file, "evaluation weights (14 MB)")
        if eval_file.stat().st_size != EVAL_SIZE:
            raise SystemExit("eval.dat has an unexpected size; download again with --force")
    else:
        say("  evaluation weights present")

    ensure_book(exe, data)
    say(f"Done. Engine: {exe}\nStart the app with:  uv run main.py")


if __name__ == "__main__":
    main()
