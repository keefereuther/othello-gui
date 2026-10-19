"""Coach, endgame puzzles and timed play, driven with a scripted fake engine."""

import asyncio
import random
import re
import struct
from pathlib import Path

import pytest

from othello_gui import board as B
from othello_gui.engine import Hint
from othello_gui.session import EDAX, HUMAN, GameSession
from othello_gui.wthor import ThorDatabase


def ggf_position(ggf: str) -> B.Position:
    m = re.search(r"BO\[8 (\S{64}) ([*O])\]", ggf)
    pos = B.Position(B.from_edax(m.group(1)), B.BLACK if m.group(2) == "*" else B.WHITE)
    for mv in re.findall(r"\b[BW]\[([^\]]+)\]", ggf):
        pos = pos.play(B.parse_sq(mv))
    return pos


class FakeEdax:
    """Answers `hint 1` from a table keyed by board string: {board: (move, score)}.
    Unknown boards get (first legal move, 0). `go` plays the table move or the first legal."""

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
        return [Hint(move, score, self.level or 1, [move])]

    async def go(self, progress=None):
        self.calls.append("go")
        move, score = self._answer()
        from othello_gui.engine import EngineMove
        return EngineMove(move, score, 0.0)


async def settle(session: GameSession):
    """Wait for the worker to finish whatever it is doing."""
    for _ in range(200):
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


# ----------------------------------------------------------------- coach

async def test_coach_pauses_on_a_costly_move_and_continues():
    s, e, _ = make_session()
    await s.set_coach(True, 4)
    start = B.Position()
    f5, d3 = B.parse_sq("f5"), B.parse_sq("d3")
    # before the move: best is f5 worth +6; after f5 the opponent's best is -6 (so f5 kept +6);
    # after d3 the opponent is +4 (so d3 was worth -4: a 10-disc loss)
    e.table[start.board] = (f5, 6.0)
    e.table[start.play(f5).board] = (B.parse_sq("d6"), -6.0)
    e.table[start.play(d3).board] = (B.parse_sq("c3"), 4.0)
    s.players = {B.BLACK: HUMAN, B.WHITE: EDAX}

    await s.user_move(d3)
    await settle(s)
    assert s.coach_alert is not None
    assert (s.coach_alert["move"], s.coach_alert["best"], s.coach_alert["loss"]) == ("d3", "f5", 10.0)
    assert len(s.moves) == 1, "Edax must not reply while the coach is waiting"
    assert s.moves[0].loss == 10.0 and s.moves[0].best == f5

    await s.coach_continue()
    await settle(s)
    assert s.coach_alert is None and len(s.moves) == 2, "Edax replies once the player plays on"


async def test_coach_take_back_and_good_move_passes_silently():
    s, e, _ = make_session()
    await s.set_coach(True, 4)
    start = B.Position()
    f5, d3 = B.parse_sq("f5"), B.parse_sq("d3")
    e.table[start.board] = (f5, 6.0)
    e.table[start.play(f5).board] = (B.parse_sq("d6"), -6.0)
    e.table[start.play(d3).board] = (B.parse_sq("c3"), 4.0)

    await s.user_move(d3)
    await settle(s)
    assert s.coach_alert
    await s.undo()
    await settle(s)
    assert s.coach_alert is None and s.moves == []

    await s.user_move(f5)
    await settle(s)
    assert s.coach_alert is None and len(s.moves) == 2  # no pause, Edax replied


async def test_coach_off_never_reviews():
    s, e, _ = make_session()
    await s.user_move(B.parse_sq("d3"))
    await settle(s)
    assert "hint 1" not in e.calls and len(s.moves) == 2


# ----------------------------------------------------------------- puzzles

def _thor_db(tmp_path: Path, transcripts: list[str]) -> ThorDatabase:
    recs = b""
    for text in transcripts:
        moves = [(sq // 8 + 1) * 10 + (sq % 8 + 1) for sq in B.parse_transcript(text)]
        recs += struct.pack("<HHHBB60s", 0, 1, 2, 33, 33, bytes(moves).ljust(60, b"\0"))
    hdr = struct.pack("<BBBBIHHBBBB", 20, 26, 1, 1, len(transcripts), 0, 2024, 8, 0, 24, 0)
    (tmp_path / "WTH_2024.wtb").write_bytes(hdr + recs)
    jou = struct.pack("<BBBBIHHBBBB", 20, 26, 1, 1, 0, 3, 0, 0, 0, 0, 0)
    (tmp_path / "WTHOR.JOU").write_bytes(jou + b"".join(n.ljust(20, b"\0") for n in (b"???", b"Alice", b"Bob")))
    trn = struct.pack("<BBBBIHHBBBB", 20, 26, 1, 1, 0, 1, 0, 0, 0, 0, 0)
    (tmp_path / "WTHOR.TRN").write_bytes(trn + b"Test Open".ljust(26, b"\0"))
    return ThorDatabase(tmp_path)


def _random_full_game(seed: int) -> str:
    rng = random.Random(seed)
    pos, moves = B.Position(), []
    while not pos.is_terminal():
        legal = pos.legal()
        if not legal:
            pos = pos.play(B.PASS)
            continue
        m = rng.choice(legal)
        moves.append(m)
        pos = pos.play(m)
    return B.transcript(moves)


async def test_puzzle_solved_and_missed(tmp_path: Path):
    s, e, _ = make_session()
    s.thor = _thor_db(tmp_path, [_random_full_game(3), _random_full_game(4)])
    s.level = 6

    await s.start_puzzle(12)
    await settle(s)
    pz = s.puzzle
    assert pz["status"] == "ask" and s.start.board.count("-") == 12 and s.moves == []
    assert s.players[s.start.player] == HUMAN and s.players[B.opponent(s.start.player)] == EDAX
    assert s.level == 6 and pz["level"] == 6 and s.opening["puzzle"] and s.opening["empties"] == 12
    best = pz["best_sq"]
    legal = s.start.legal()
    other = next(m for m in legal if m != best)
    # the fake said the start is worth 0 (default); make the best move keep 0 and the other lose 6
    after_best, after_other = s.start.play(best), s.start.play(other)
    e.table[after_best.board] = ((after_best.legal() or [B.PASS])[0], 0.0)
    e.table[after_other.board] = ((after_other.legal() or [B.PASS])[0], 6.0)

    await s.user_move(other)
    await settle(s)
    assert s.puzzle["status"] == "missed" and s.puzzle["loss"] == 6.0 and s.puzzle["played"] == B.sq_name(other)
    assert len(s.moves) >= 2, "Edax plays on after the answer"

    await s.undo()
    await settle(s)
    assert s.puzzle["status"] == "ask" and s.moves == []

    await s.user_move(best)
    await settle(s)
    assert s.puzzle["status"] == "solved" and s.puzzle["loss"] == 0.0


async def test_puzzle_needs_thor():
    s, _, _ = make_session()
    with pytest.raises(ValueError):
        await s.start_puzzle(10)


# ----------------------------------------------------------------- timed play

async def test_timed_play_uses_a_second_engine_and_level_play_the_main_one():
    s, e, _ = make_session()
    created = []

    def factory(exe, threads, book_randomness, move_time=None):
        fe = FakeEdax(exe, threads, book_randomness, move_time)
        created.append(fe)
        return fe

    s.engine_factory = factory
    s.players = {B.BLACK: EDAX, B.WHITE: HUMAN}

    await s.set_move_time(3)
    await settle(s)  # Edax (black) moves right away
    assert len(created) == 1 and created[0].move_time == 3 and created[0].level == 60
    assert "go" in created[0].calls and "go" not in e.calls
    assert len(s.moves) >= 1

    await s.set_move_time(None)
    assert created[0].running is False and s._play_engine is None
    await s.user_move(s.current.legal()[0])
    await settle(s)
    assert "go" in e.calls, "back on the level-based engine"

    with pytest.raises(ValueError):
        await s.set_move_time(10000)
