"""Build an Edax opening book from WTHOR tournament games.

    uv run scripts/build_book.py --years 2023-2025 --level 10

Edax learns the book by adding every position of every game (up to `--depth`
plies) and evaluating it at `--level`. Roughly 30 positions per second at
level 10 on an Apple Silicon laptop; a year of games is ~3000 games, so plan
on 10–60 minutes per year depending on level. Lower levels are much faster.

The book is written to a temporary file and moved into place at the end, with
the previous book kept as `book.dat.bak`. Restart the GUI to load it, and set
EDAX_BOOK_RANDOMNESS (or use the Variety option) to make Edax vary its play.
"""

from __future__ import annotations

import argparse
import os
import re
import pty
import select
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EDAX = ROOT.parent / "edax-reversi" / "bin" / "mEdax"
DEFAULT_WTHOR = ROOT.parent / "wthor"


class EdaxText:
    """Drive Edax's text interface through a pseudo-terminal."""

    def __init__(self, exe: Path, args: list[str]) -> None:
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(exe.parent)
            os.execv(str(exe), [str(exe), *args])
        self.buf = b""
        self.wait_prompt(60)

    def read(self, timeout: float) -> bytes:
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return b""
        try:
            return os.read(self.fd, 65536)
        except OSError:
            return b""

    def wait_prompt(self, timeout: float, progress: bool = False) -> str:
        """Collect output until Edax shows its '>' prompt again."""
        start = time.time()
        out = b""
        last_print = 0.0
        while time.time() - start < timeout:
            chunk = self.read(1.0)
            out += chunk
            if progress and chunk and time.time() - last_print > 5:
                tail = chunk.decode(errors="replace").strip().splitlines()
                if tail:
                    print("   ", tail[-1][-90:], flush=True)
                last_print = time.time()
            if out.rstrip().endswith(b">"):
                return out.decode(errors="replace")
        raise TimeoutError("Edax did not return to its prompt")

    def cmd(self, line: str, timeout: float = 600, progress: bool = False) -> str:
        os.write(self.fd, (line + "\n").encode())
        return self.wait_prompt(timeout, progress)

    def close(self) -> None:
        """Quit Edax and wait for it to exit (it saves the book on quit)."""
        try:
            os.write(self.fd, b"quit\n")
        except OSError:
            pass
        for _ in range(600):  # up to 60 s
            try:
                pid, _status = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                return
            if pid:
                return
            self.read(0.1)
        try:
            os.kill(self.pid, 9)
        except OSError:
            pass


def parse_years(spec: str) -> list[int]:
    years: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            years.extend(range(int(a), int(b) + 1))
        else:
            years.append(int(part))
    return years


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", default="2024-2025", help="e.g. 2020-2025 or 1990,2000,2024")
    ap.add_argument("--level", type=int, default=10, help="Edax level used to evaluate book positions")
    ap.add_argument("--depth", type=int, default=24, help="add positions up to this many plies into the game")
    ap.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--edax", type=Path, default=Path(os.environ.get("EDAX_BIN", DEFAULT_EDAX)))
    ap.add_argument("--wthor", type=Path, default=Path(os.environ.get("WTHOR_DIR", DEFAULT_WTHOR)))
    ap.add_argument("--out", type=Path, default=None, help="book file (default: Edax's data/book.dat)")
    ap.add_argument("--merge", action="store_true", help="add to the existing book instead of starting fresh")
    args = ap.parse_args()

    exe = args.edax.resolve()
    out = (args.out or exe.parent / "data" / "book.dat").resolve()
    tmp = out.with_suffix(".building")
    files = [args.wthor / f"WTH_{y}.wtb" for y in parse_years(args.years)]
    missing = [f for f in files if not f.exists()]
    if missing:
        sys.exit(f"missing WTHOR files: {', '.join(str(m) for m in missing)}")

    print(f"Edax {exe}\nbook   {out}\nlevel {args.level}, depth {args.depth} plies, {args.threads} threads")
    if args.merge and out.exists():
        shutil.copy(out, tmp)
    # Edax's in-session commands stop at the first space, so `book save` gets a
    # space-free symlink inside the Edax directory that points at the temp file.
    save_link = exe.parent / "_book_out.dat"
    if save_link.is_symlink() or save_link.exists():
        save_link.unlink()
    save_link.symlink_to(tmp)
    edax = EdaxText(exe, ["-n", str(args.threads), "-l", str(args.level), "-book-file", str(tmp)])
    try:
        if not (args.merge and out.exists()):
            edax.cmd(f"book new {args.level} {args.depth}")
        t0 = time.time()
        for f in files:
            print(f"adding {f.name} …", flush=True)
            # Edax's command parser stops at the first space, so hand it a
            # space-free symlink inside its own directory instead of the real path.
            link = exe.parent / f"_book_src_{f.name}"
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(f.resolve())
            try:
                out_text = edax.cmd(f"book add {link.name}", timeout=24 * 3600, progress=True)
            finally:
                link.unlink()
            m = re.search(r"(\d+) games added to book", out_text)
            added = int(m.group(1)) if m else 0
            if added == 0:
                print("   WARNING: no games were added (Edax output follows)")
                print("   " + out_text.strip().replace("\n", "\n   ")[-800:])
            edax.cmd(f"book save {save_link.name}", timeout=600)  # checkpoint
            print(f"   {added} games added, saved after {time.time() - t0:.0f}s", flush=True)
        print("fixing links and negamaxing the book …", flush=True)
        edax.cmd("book fix", timeout=3600)
        print(edax.cmd("book info").split("\n\n")[0])
        edax.cmd(f"book save {save_link.name}", timeout=600)
    finally:
        edax.close()
        save_link.unlink(missing_ok=True)
    if not tmp.exists():
        sys.exit("the book was not written; check the output above")
    if out.exists():
        shutil.copy(out, out.with_suffix(".dat.bak"))
    shutil.move(tmp, out)
    print(f"done: {out} ({out.stat().st_size / 1e6:.1f} MB). Restart the GUI to use it.")


if __name__ == "__main__":
    main()
