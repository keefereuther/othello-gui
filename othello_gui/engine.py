"""Asyncio driver for the Edax engine speaking Chris Welty's NBoard protocol.

Edax is started as ``mEdax -nboard -n <threads>`` with its working directory set
to the folder that holds ``data/eval.dat`` and ``data/book.dat``.  The protocol
is plain text over stdin/stdout.  Commands we use::

    nboard 1                 handshake
    set depth N              search level (Edax "level")
    set game <GGF>           set the whole game; Edax replays it
    hint N                   evaluate the N best moves at the current position
    go                       let Edax choose and play a move
    ping K  ->  pong K       synchronisation

Replies we parse::

    set myname EdaxN
    status Edax is thinking | status Edax is waiting
    nodestats <nodes> <seconds>
    search <pv> <score> 0 <depth>       one hint from search
    book <pv> <score> <games> <level>   one hint from the opening book
    === <move> <score> <seconds>        the move chosen by `go`

Scores are disc differences from the point of view of the player to move.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from .board import parse_sq

log = logging.getLogger(__name__)

_PV_RE = re.compile(r"[a-hA-H][1-8]|[pP][aA]")


class EdaxError(RuntimeError):
    pass


@dataclass
class Hint:
    move: int
    score: float
    depth: int
    pv: list[int] = field(default_factory=list)
    book: bool = False
    book_games: int = 0


@dataclass
class EngineMove:
    move: int
    score: float
    seconds: float


ProgressCallback = Callable[[int, float], Awaitable[None]]


def _parse_pv(text: str) -> list[int]:
    return [parse_sq(m) for m in _PV_RE.findall(text)]


class Edax:
    """One Edax process. All commands are serialised through a lock, so callers
    may share an instance freely; a command never sees another command's output.
    """

    def __init__(self, exe: Path | str, threads: int | None = None, book_randomness: int = 0) -> None:
        self.exe = Path(exe).expanduser().resolve()
        self.cwd = self.exe.parent
        self.threads = threads or max(1, (os.cpu_count() or 2) - 1)
        self.book_randomness = max(0, int(book_randomness))
        self.level: int | None = None
        self.name = "Edax"
        self.proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._ping_id = 0
        self._stderr: list[str] = []
        self._stderr_task: asyncio.Task | None = None

    # ------------------------------------------------------------------ lifecycle

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self) -> None:
        if not self.exe.exists():
            raise EdaxError(f"Edax executable not found at {self.exe}")
        if not (self.cwd / "data" / "eval.dat").exists():
            raise EdaxError(f"eval.dat not found in {self.cwd / 'data'}")
        await self._ensure_book()
        args = [str(self.exe), "-nboard", "-n", str(self.threads)]
        if self.book_randomness:
            args += ["-book-randomness", str(self.book_randomness)]
        self.proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(self.cwd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        async with self._lock:
            await self._write("nboard 1")
            await self._ping()
        log.info("Edax started (pid %s, %d threads) from %s", self.proc.pid, self.threads, self.exe)

    async def _ensure_book(self) -> None:
        """Without data/book.dat Edax builds a book at level 24 on start, which looks
        like a hang. Create a minimal book at level 1 instead (well under a second)."""
        book = self.cwd / "data" / "book.dat"
        if book.exists():
            return
        log.info("no opening book found; creating a minimal one at %s", book)
        proc = await asyncio.create_subprocess_exec(
            str(self.exe), "-l", "1", "-q", cwd=str(self.cwd),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.communicate(b"quit\n"), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
        if not book.exists():
            log.warning("could not create %s; the first start may be slow", book)

    async def quit(self) -> None:
        if not self.running:
            return
        try:
            await self._write("quit")
            await asyncio.wait_for(self.proc.wait(), timeout=3)
        except Exception:
            self.proc.kill()
        if self._stderr_task:
            self._stderr_task.cancel()

    # ------------------------------------------------------------------ commands

    async def set_level(self, level: int) -> None:
        level = max(1, min(60, int(level)))
        async with self._lock:
            await self._write(f"set depth {level}")
            await self._ping()
        self.level = level

    async def set_game(self, ggf: str) -> None:
        async with self._lock:
            n_err = len(self._stderr)
            await self._write(f"set game {ggf}")
            await self._ping()
            # stderr is a separate pipe; give the reader a moment to catch up
            await asyncio.sleep(0.02)
            new_errors = [l for l in self._stderr[n_err:] if l.startswith("Error")]
            if new_errors:
                raise EdaxError(new_errors[-1])

    async def hint(self, n: int, progress: ProgressCallback | None = None) -> list[Hint]:
        """Ask for the `n` best moves. Book moves (if any) come first."""
        async with self._lock:
            await self._write(f"hint {max(1, n)}")
            hints: list[Hint] = []
            while True:
                line = await self._readline()
                parts = line.split()
                if not parts:
                    continue
                if parts[0] == "status" and "waiting" in line:
                    break
                if parts[0] == "search" and len(parts) >= 5:
                    pv = _parse_pv(parts[1])
                    if pv:
                        hints.append(Hint(pv[0], float(parts[2]), int(parts[4]), pv))
                elif parts[0] == "book" and len(parts) >= 5:
                    pv = _parse_pv(parts[1])
                    if pv:
                        hints.append(Hint(pv[0], float(parts[2]), int(parts[4]), pv, True, int(parts[3])))
                elif parts[0] == "nodestats" and progress and len(parts) >= 3:
                    await progress(int(parts[1]), float(parts[2]))
            return hints

    async def go(self, progress: ProgressCallback | None = None) -> EngineMove:
        """Let Edax play a move at the current position."""
        async with self._lock:
            await self._write("go")
            result: EngineMove | None = None
            while True:
                line = await self._readline()
                parts = line.split()
                if not parts:
                    continue
                if parts[0] == "status" and "waiting" in line:
                    break
                if parts[0] == "===" and len(parts) >= 4:
                    result = EngineMove(parse_sq(parts[1]), float(parts[2]), float(parts[3]))
                elif parts[0] == "nodestats" and progress and len(parts) >= 3:
                    await progress(int(parts[1]), float(parts[2]))
            if result is None:
                raise EdaxError("Edax did not return a move")
            return result

    # ------------------------------------------------------------------ plumbing

    async def _write(self, line: str) -> None:
        if not self.running:
            raise EdaxError("Edax is not running")
        assert self.proc and self.proc.stdin
        log.debug("-> %s", line)
        self.proc.stdin.write((line + "\n").encode())
        await self.proc.stdin.drain()

    async def _readline(self, timeout: float | None = None) -> str:
        assert self.proc and self.proc.stdout
        raw = await asyncio.wait_for(self.proc.stdout.readline(), timeout)
        if not raw:
            raise EdaxError("Edax exited unexpectedly")
        line = raw.decode(errors="replace").rstrip("\r\n")
        log.debug("<- %s", line)
        return line

    async def _ping(self) -> None:
        """Must be called with the lock held. Discards unrelated output
        (e.g. 'set myname ...') until the matching pong arrives."""
        self._ping_id += 1
        token = str(self._ping_id)
        await self._write(f"ping {token}")
        while True:
            line = await self._readline(timeout=60)
            if line == f"pong {token}":
                return
            if line.startswith("set myname "):
                self.name = line.split(" ", 2)[2]

    async def _drain_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        async for raw in self.proc.stderr:
            line = raw.decode(errors="replace").rstrip()
            self._stderr.append(line)
            if len(self._stderr) > 200:
                del self._stderr[:100]
            log.warning("edax: %s", line)
