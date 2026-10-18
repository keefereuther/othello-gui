import struct
from pathlib import Path

import pytest

from othello_gui import board as B
from othello_gui.wthor import ThorDatabase, decode_move

WTHOR_DIR = Path(__file__).resolve().parent.parent.parent / "wthor"


def test_decode_move():
    assert B.sq_name(decode_move(56)) == "f5"
    assert B.sq_name(decode_move(11)) == "a1"
    assert B.sq_name(decode_move(88)) == "h8"
    with pytest.raises(ValueError):
        decode_move(9)


def test_synthetic_database(tmp_path: Path):
    header = struct.pack("<BBBBIHHBBBB", 20, 26, 1, 1, 1, 0, 2024, 8, 0, 24, 0)
    moves = bytes([56, 64, 33, 34]) + bytes(56)
    (tmp_path / "WTH_2024.wtb").write_bytes(header + struct.pack("<HHHBB60s", 0, 1, 0, 40, 40, moves))
    (tmp_path / "WTHOR.JOU").write_bytes(struct.pack("<BBBBIHHBBBB", 20, 26, 1, 1, 0, 2, 0, 0, 0, 0, 0) + b"???".ljust(20, b"\0") + b"Tastet Marc".ljust(20, b"\0"))
    (tmp_path / "WTHOR.TRN").write_bytes(struct.pack("<BBBBIHHBBBB", 20, 26, 1, 1, 0, 1, 0, 0, 0, 0, 0) + b"Worlds".ljust(26, b"\0"))
    db = ThorDatabase(tmp_path)
    assert len(db) == 1
    g = db.game(0)
    assert (g.year, g.black, g.white, g.tournament, g.result) == (2024, "Tastet Marc", "???", "Worlds", "40-24")
    assert B.transcript(list(g.moves)) == "F5d6C3d3"
    game, opening = db.random_opening(3)
    assert len(opening) == 3


@pytest.mark.skipif(not (WTHOR_DIR / "WTHOR.JOU").exists(), reason="real WTHOR files not present")
def test_real_database_games_are_legal():
    db = ThorDatabase(WTHOR_DIR)
    assert len(db) > 100000
    for i in range(0, len(db), 2000):
        g = db.game(i)
        B.replay(B.Position(), list(g.moves))  # raises if a game is corrupt
