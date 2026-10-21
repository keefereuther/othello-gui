"""Training: progress and unlocking, the three drill kinds, worked examples and scrimmages."""

import random

import pytest
from fakes import make_session, settle

from othello_gui import board as B
from othello_gui.curriculum import PART1, UNITS
from othello_gui.training import WINDOW, Progress, Trainer, judge_bucket


def _random_game(seed: int) -> str:
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


def _trainer(make_wthor, tmp_path, unlock_all=True):
    s, e, msgs = make_session()
    s.thor = make_wthor([(_random_game(i), 30 + i) for i in range(12)])
    t = Trainer(s, tmp_path / "progress.json", unlock_all=unlock_all)
    t.rng.seed(1)
    s.trainer = t
    return s, e, t


def test_curriculum_shape():
    ids = [u["id"] for u in UNITS]
    assert len(ids) == len(set(ids)) == 14
    assert PART1 == ["rules", "corners", "frontier", "openings", "edges", "endgame", "defense"]
    for u in UNITS:
        assert u["lesson"] and u["ideas"] and u["drill"]["kinds"] and u["scrimmage"]["about"]


def test_unlocking_and_persistence(tmp_path):
    path = tmp_path / "progress.json"
    p = Progress(path)
    assert p.unlocked("rules") and not p.unlocked("corners") and not p.unlocked("parity")
    for _ in range(WINDOW):
        p.record_drill("rules", "squares", 1.0)
    assert p.drills_passed("rules") and not p.passed("rules")
    p.unit("rules")["scrimmages"].append({"passed": True})
    p.save()
    again = Progress(path)
    assert again.passed("rules") and again.unlocked("corners") and not again.unlocked("frontier")
    for uid in PART1:
        again.unit(uid)["scrimmages"].append({"passed": True})
        for _ in range(WINDOW):
            again.record_drill(uid, "move", 1.0)
    assert again.unlocked("parity") and again.unlocked("masters")


def test_judge_buckets():
    assert [judge_bucket(v) for v in (12, 5, 0, -2, -4, -30)] == [0, 1, 2, 2, 3, 4]


async def test_locked_unit_is_refused(make_wthor, tmp_path):
    s, _, t = _trainer(make_wthor, tmp_path, unlock_all=False)
    with pytest.raises(ValueError):
        await t.open_unit("corners")
    await t.open_unit("rules")
    assert s.state()["training"]["unit"] == "rules"


async def test_squares_drill(make_wthor, tmp_path):
    s, _, t = _trainer(make_wthor, tmp_path)
    await t.open_unit("rules")
    await t.next_drill()
    d = t.drill
    assert d["kind"] == "squares" and d["status"] == "ask" and len(t.marks) == 1
    with pytest.raises(ValueError):
        await s.user_move(s.current.legal()[0])  # answer the question, not the board
    await t.answer(d["_answer"])
    assert d["status"] == "answered" and d["credit"] == 1.0
    assert t.progress.drill_rate("rules") == (1, 1.0)
    assert "_answer" not in s.state()["training"]["drill"]


async def test_move_drill_graded_by_engine(make_wthor, tmp_path):
    s, e, t = _trainer(make_wthor, tmp_path)
    await t.open_unit("openings")
    await t.next_drill("move")
    d = t.drill
    assert d["status"] == "ask" and s.moves == [] and t.hides_hints()
    best = d["_best"]
    worst = min(d["_scores"], key=d["_scores"].get)
    await s.user_move(worst)
    await settle(s)
    assert d["status"] == "answered" and d["credit"] == 0.0 and d["loss"] >= 3
    assert t.marks[best] == "good" and t.marks[worst] == "bad" and "Better is" in d["feedback"]
    await t.next_drill("move")
    await s.user_move(t.drill["_best"])
    assert t.drill["credit"] == 1.0
    assert t.progress.drill_rate("openings") == (2, 0.5)


async def test_judge_drill_and_example(make_wthor, tmp_path):
    s, e, t = _trainer(make_wthor, tmp_path)
    await t.open_unit("frontier")
    # the unit filters positions, but the synthetic games may not match: drop the filter here
    spec_filter = t.unit["drill"].pop("filter")
    try:
        await t.next_drill("judge")
        d = t.drill
        assert d["status"] == "ask" and len(d["choices"]) == 5
        await t.answer(d["_answer"])
        assert d["credit"] == 1.0 and "Edax:" in d["feedback"]
        await t.show_example()
        assert t.example["status"] == "ready" and "good" in t.marks.values()
    finally:
        t.unit["drill"]["filter"] = spec_filter


async def test_scrimmage_is_scored_and_settings_restored(make_wthor, tmp_path):
    s, e, t = _trainer(make_wthor, tmp_path)
    s.level, s.hints_enabled = 9, True
    await t.open_unit("corners")
    await t.start_scrimmage()
    human = t.scrim["color"]
    assert s.players[human] == "human" and s.coach_enabled and not s.hints_enabled and s.review_level == 10
    for _ in range(80):
        await settle(s)
        if s.current.is_terminal():
            break
        if s.coach_alert:
            await s.coach_continue()
        elif s.players[s.current.player] == "human":
            await s.user_move(s.current.legal()[-1])
    await settle(s)
    assert s.current.is_terminal()
    assert t.scrim["status"] == "done" and t.review is not None
    assert len(t.progress.unit("corners")["scrimmages"]) == 1
    await t.close()
    assert s.level == 9 and s.hints_enabled and s.review_level is None


async def test_new_game_abandons_a_drill(make_wthor, tmp_path):
    s, _, t = _trainer(make_wthor, tmp_path)
    await t.open_unit("rules")
    await t.next_drill()
    await s.new_game("human", "edax")
    assert t.drill is None and t.mode == "lesson"
