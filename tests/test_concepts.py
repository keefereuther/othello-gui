from othello_gui import board as B
from othello_gui.concepts import analyse_move, compare, describe, frontier_discs, regions, square_class


def _pos(seq: str) -> B.Position:
    return B.replay(B.Position(), B.parse_transcript(seq))[-1]


def test_square_classes():
    assert square_class(B.parse_sq("a1")) == "corner"
    assert square_class(B.parse_sq("b2")) == "X"
    assert square_class(B.parse_sq("b1")) == "C"
    assert square_class(B.parse_sq("c1")) == "A"
    assert square_class(B.parse_sq("d1")) == "B"
    assert square_class(B.parse_sq("d4")) == "interior"


def test_frontier_and_regions():
    start = B.Position()
    assert frontier_discs(start.board, B.BLACK) == {B.parse_sq("e4"), B.parse_sq("d5")}
    assert len(regions(start.board)) == 1 and len(regions(start.board)[0]) == 60
    # a lone empty corner is its own region
    board = "O" * 64
    board = "-" + board[1:62] + "-" + board[63:]
    assert sorted(len(r) for r in regions(board)) == [1, 1]


def test_x_square_report_and_text():
    # Black has a wall; b2 for black (an X-square) is flagged
    pos = _pos("f5d6c3d3c4f4c5b3c2e3d2c6b4a3a4a5")
    xs = [m for m in pos.legal() if square_class(m) == "X"]
    if xs:
        r = analyse_move(pos, xs[0])
        assert "x-square" in r.tags
        assert "X-square" in describe(r)
    first = analyse_move(B.Position(), B.parse_sq("f5"))
    assert first.flipped == 1 and first.new_frontier == 2 and "loud" not in first.tags
    # Diagram 3-19: c5 for Black creates no new frontier discs
    board = list("-" * 64)
    for sq, v in {"c1": "X", "d1": "X", "f1": "O", "a2": "O", "b2": "O", "c2": "X", "d2": "O", "e2": "O",
                  "b3": "O", "c3": "X", "d3": "O", "e3": "O", "f3": "O", "g3": "X", "b4": "O", "c4": "O",
                  "d4": "X", "e4": "O", "b5": "O", "c5": "-", "d5": "O", "e5": "O", "b6": "O", "c6": "O",
                  "d6": "O", "e6": "O", "f6": "O"}.items():
        board[B.parse_sq(sq)] = v
    pos = B.Position("".join(board), B.BLACK)
    if B.parse_sq("c5") in pos.legal():
        r = analyse_move(pos, B.parse_sq("c5"))
        assert r.quiet and "quiet" in r.tags


def test_compare_mentions_both_moves():
    pos = B.Position()
    text = compare(pos, B.parse_sq("f5"), B.parse_sq("d3"))
    assert text.startswith("You played F5") and "Better is D3" in text
    assert compare(pos, B.parse_sq("f5"), B.parse_sq("f5"))
