"""Coach, endgame puzzles and timed play, driven with a scripted fake engine."""

import random

import pytest
from fakes import FakeEdax, make_session, settle

from othello_gui import board as B
from othello_gui.session import EDAX, HUMAN

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


async def test_puzzle_solved_and_missed(make_wthor):
    s, e, _ = make_session()
    s.thor = make_wthor([(_random_full_game(3), 33), (_random_full_game(4), 33)])
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
