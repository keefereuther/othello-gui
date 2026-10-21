import random
from pathlib import Path

import numpy as np
import pytest

from othello_gui import board as B
from othello_gui.paths import find_wthor
from othello_gui.thor_index import (
    INVERSE,
    SQMAP,
    U64,
    Filters,
    ThorIndex,
    bitboards,
    canonical,
    position_key,
    transform,
)
from othello_gui.wthor import ThorDatabase

WTHOR_DIR = find_wthor()


def _transform_board(board: str, t: int) -> str:
    cells = ["-"] * 64
    for sq, c in enumerate(board):
        cells[int(SQMAP[t, sq])] = c
    return "".join(cells)


def _random_position(seed: int, plies: int) -> B.Position:
    rng = random.Random(seed)
    pos = B.Position()
    for _ in range(plies):
        if pos.is_terminal():
            break
        legal = pos.legal()
        pos = pos.play(rng.choice(legal) if legal else B.PASS)
    return pos


def _key(board: str, player: str) -> int:
    b, w = bitboards(board)
    cb, cw, _ = canonical(np.array([b], dtype=U64), np.array([w], dtype=U64))
    return int(position_key(cb, cw, np.array([0 if player == B.BLACK else 1], dtype=np.uint8))[0])


# ----------------------------------------------------------------- symmetry

def test_square_maps_are_the_eight_board_symmetries():
    maps = {tuple(SQMAP[t, :64]) for t in range(8)}
    assert len(maps) == 8
    for t in range(8):
        m = SQMAP[t, :64]
        assert sorted(m) == list(range(64))
        assert list(SQMAP[INVERSE[t], m]) == list(range(64))
        # a symmetry keeps every pair of squares at the same king distance
        for a in range(0, 64, 7):
            for b in range(64):
                d0 = max(abs(a // 8 - b // 8), abs(a % 8 - b % 8))
                d1 = max(abs(int(m[a]) // 8 - int(m[b]) // 8), abs(int(m[a]) % 8 - int(m[b]) % 8))
                assert d0 == d1


def test_bitboard_transform_matches_square_map():
    pos = _random_position(1, 20)
    b, w = bitboards(pos.board)
    for t in range(8):
        tb, tw = bitboards(_transform_board(pos.board, t))
        assert int(transform(np.array([b], dtype=U64), t)[0]) == tb
        assert int(transform(np.array([w], dtype=U64), t)[0]) == tw


@pytest.mark.parametrize("seed", range(6))
def test_all_transforms_share_one_canonical_key(seed):
    pos = _random_position(seed, 10 + seed * 4)
    keys = {_key(_transform_board(pos.board, t), pos.player) for t in range(8)}
    assert len(keys) == 1
    # side to move is part of the key
    assert _key(pos.board, B.opponent(pos.player)) not in keys


@pytest.mark.parametrize("seed", range(6))
def test_continuations_map_back_onto_the_viewed_board(seed):
    """A move recorded in canonical coordinates on one orientation lands on the
    corresponding legal square of any other orientation."""
    pos = _random_position(seed + 10, 12)
    legal = pos.legal()
    if not legal:
        pytest.skip("no legal move")
    move = legal[0]
    b, w = bitboards(pos.board)
    _, _, t_rec = canonical(np.array([b], dtype=U64), np.array([w], dtype=U64))
    canon_move = int(SQMAP[int(t_rec[0]), move])
    for t in range(8):
        viewed = _transform_board(pos.board, t)
        vb, vw = bitboards(viewed)
        _, _, t_view = canonical(np.array([vb], dtype=U64), np.array([vw], dtype=U64))
        back = int(SQMAP[INVERSE[int(t_view[0])], canon_move])
        expected = int(SQMAP[t, move])
        if back != expected:
            # only allowed when the board has a symmetry that swaps the two squares
            assert any(
                _transform_board(viewed, s) == viewed and int(SQMAP[s, expected]) == back for s in range(1, 8)
            )
            assert back in B.Position(viewed, pos.player).legal()
        else:
            assert back in B.Position(viewed, pos.player).legal()


# ----------------------------------------------------------------- synthetic database

def test_index_roundtrip_and_cache(tmp_path: Path, make_wthor):
    db = make_wthor([("f5d6c3d3c4", 40), ("f5f6e6f4", 20), ("f5d6c5", 32)])
    idx = ThorIndex.load_or_build(db)
    assert (tmp_path / "thor-index.npz").exists()

    start = idx.lookup(B.Position().board, B.BLACK)
    assert (start["games"], start["black_wins"], start["white_wins"], start["draws"]) == (3, 1, 1, 1)

    pos = B.replay(B.Position(), B.parse_transcript("f5d6"))[-1]
    r = idx.lookup(pos.board, pos.player)
    assert r["games"] == 2
    assert sorted(c["name"] for c in r["continuations"]) == ["c3", "c5"]
    assert r["sample"][0]["black"] == "Alice" and r["sample"][0]["tournament"] == "Test Open"

    # the same opening played in another orientation (d3 instead of f5) finds the games
    mirrored = B.replay(B.Position(), B.parse_transcript("d3c5"))[-1]
    r2 = idx.lookup(mirrored.board, mirrored.player)
    assert r2["games"] == 2
    for c in r2["continuations"]:
        assert c["move"] in mirrored.legal()

    # a cached index loads with identical contents
    again = ThorIndex.load_or_build(db)
    assert np.array_equal(again.keys, idx.keys) and np.array_equal(again.nexts, idx.nexts)

    # filters
    assert idx.lookup(B.Position().board, B.BLACK, Filters(min_year=2025))["games"] == 0
    assert idx.lookup(B.Position().board, B.BLACK, Filters(player="ali"))["games"] == 3
    assert idx.lookup(B.Position().board, B.BLACK, Filters(player="zed"))["games"] == 0


def test_game_aligned_follows_the_viewed_orientation(make_wthor):
    db = make_wthor([("f5d6c3d3c4f4", 40)])
    idx = ThorIndex.load_or_build(db)
    viewed = B.replay(B.Position(), B.parse_transcript("d3c5"))[-1]
    moves, ply = idx.game_aligned(0, viewed.board, viewed.player)
    assert ply == 2
    positions = B.replay(B.Position(), moves)
    assert positions[2].board == viewed.board


# ----------------------------------------------------------------- real database

@pytest.mark.skipif(not (WTHOR_DIR / "WTHOR.JOU").exists(), reason="real WTHOR files not present")
def test_real_database_start_position_finds_every_game(tmp_path: Path):
    db = ThorDatabase(WTHOR_DIR)
    idx = ThorIndex.load_or_build(db, cache_dir=tmp_path)
    r = idx.lookup(B.Position().board, B.BLACK)
    assert r["games"] == len(db)
    assert r["black_wins"] + r["draws"] + r["white_wins"] == len(db)
    after_f5 = B.Position().play(B.parse_sq("f5"))
    for c in idx.lookup(after_f5.board, after_f5.player)["continuations"]:
        assert c["move"] in after_f5.legal()
