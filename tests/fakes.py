"""A scripted stand-in for Edax, shared by the session and training tests."""

import asyncio
import re

from othello_gui import board as B
from othello_gui.engine import EngineMove, Hint
from othello_gui.session import GameSession


def ggf_position(ggf: str) -> B.Position:
    m = re.search(r"BO\[8 (\S{64}) ([*O])\]", ggf)
    pos = B.Position(B.from_edax(m.group(1)), B.BLACK if m.group(2) == "*" else B.WHITE)
    for mv in re.findall(r"\b[BW]\[([^\]]+)\]", ggf):
        pos = pos.play(B.parse_sq(mv))
    return pos


class FakeEdax:
    """Answers from a table keyed by board string: {board: (move, score)}.
    Unknown boards get (first legal move, 0). `hint n` returns the table move first,
    then the other legal moves, each 3 discs worse than the one before.
    `go` plays the table move or the first legal."""

    def __init__(self, exe="fake", threads=1, book_randomness=0, move_time=None):
        self.exe, self.threads, self.book_randomness, self.move_time = exe, threads, book_randomness, move_time
        self.name, self.level, self.running = "Fake", None, False
        self.table: dict[str, tuple[int, float]] = {}
        self.pos = B.Position()
        self.calls: list[str] = []

    async def start(self):
        self.running = True

    async def quit(self):
        self.running = False

    async def set_level(self, level):
        self.level = level

    async def set_game(self, ggf):
        self.pos = ggf_position(ggf)
        self.calls.append("set_game")

    def _answer(self):
        if self.pos.board in self.table:
            return self.table[self.pos.board]
        legal = self.pos.legal()
        return (legal[0] if legal else B.PASS), 0.0

    async def hint(self, n, progress=None):
        self.calls.append(f"hint {n}")
        move, score = self._answer()
        others = [m for m in self.pos.legal() if m != move]
        out = [Hint(move, score, self.level or 1, [move])]
        out += [Hint(m, score - 3 * (k + 1), self.level or 1, [m]) for k, m in enumerate(others)]
        return out[: max(1, n)]

    async def go(self, progress=None):
        self.calls.append("go")
        move, score = self._answer()
        return EngineMove(move, score, 0.0)


async def settle(session: GameSession):
    """Wait for the worker to finish whatever it is doing."""
    for _ in range(400):
        await asyncio.sleep(0.005)
        if session._worker is None or session._worker.done():
            return
    raise TimeoutError("worker did not settle")


def make_session(engine=None):
    engine = engine or FakeEdax()
    engine.running = True
    messages = []

    async def broadcast(msg):
        messages.append(msg)

    s = GameSession(engine, broadcast)
    s.hints_enabled = False
    return s, engine, messages
