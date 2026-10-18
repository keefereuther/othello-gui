from othello_gui import board as B


def count_games(pos: B.Position, depth: int) -> int:
    """Number of distinct game paths of `depth` plies (passes count as plies)."""
    if depth == 0 or pos.is_terminal():
        return 1
    moves = pos.legal() or [B.PASS]
    return sum(count_games(pos.play(m), depth - 1) for m in moves)


def test_start_position():
    pos = B.Position()
    assert B.counts(pos.board) == (2, 2, 60)
    assert sorted(B.sq_name(s) for s in pos.legal()) == ["c4", "d3", "e6", "f5"]


def test_perft_matches_known_values():
    # Well-known Othello perft numbers
    expected = {1: 4, 2: 12, 3: 56, 4: 244, 5: 1396, 6: 8200}
    for depth, n in expected.items():
        assert count_games(B.Position(), depth) == n


def test_names_roundtrip():
    for sq in range(64):
        assert B.parse_sq(B.sq_name(sq)) == sq
    assert B.parse_sq("PA") == B.PASS


def test_replay_and_transcript():
    moves = B.parse_transcript("F5d6C3d3C4")
    positions = B.replay(B.Position(), moves)
    assert len(positions) == 6
    assert B.transcript(moves) == "F5d6C3d3C4"


def test_ggf_header():
    g = B.ggf(B.Position(), [B.parse_sq("f5"), B.parse_sq("d6")])
    assert "BO[8 ---------------------------O*------*O--------------------------- *]" in g
    assert g.endswith("B[f5]W[d6];)")


def _pass_position() -> B.Position:
    """White at h2 hemmed in by black on h1, g1 and a2..g2: white has no move,
    black can play h3 (h1 black, h2 white, h3 empty)."""
    cells = ["-"] * 64
    for sq in [7, 6, *range(8, 15)]:
        cells[sq] = B.BLACK
    cells[15] = B.WHITE
    return B.Position("".join(cells), B.WHITE)


def test_forced_pass_is_inserted():
    pos = _pass_position()
    assert pos.must_pass() and not pos.is_terminal()
    positions = B.replay(pos, [B.parse_sq("h3")])
    assert len(positions) == 3  # start, after pass, after h3
    assert positions[1].player == B.BLACK
    assert positions[2].board[B.parse_sq("h3")] == B.BLACK
    assert positions[2].board[15] == B.BLACK  # h2 was flipped


def test_ggf_writes_passes():
    pos = _pass_position()
    g = B.ggf(pos, [B.PASS, B.parse_sq("h3")])
    assert g.endswith("W[pa]B[h3];)")
    assert " O]" in g  # white to move in the header
