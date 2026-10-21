from types import SimpleNamespace

from othello_gui import board as B
from othello_gui.openings import DATA, table
from othello_gui.session import GameSession


def _positions(seq: str) -> list[B.Position]:
    return B.replay(B.Position(), B.parse_transcript(seq))


def test_every_table_line_is_a_legal_game():
    lines = [line for line in DATA.read_text().splitlines() if line.strip() and not line.startswith("//")]
    for line in lines:
        B.replay(B.Position(), B.parse_transcript(line.split()[0]))  # raises on an illegal line
    assert len(table()) >= 80


def test_named_positions_and_symmetry():
    t = table()
    assert t.lookup(_positions("f5d6")[-1]).name == "Perpendicular"
    tiger = t.lookup(_positions("f5d6c3d3c4")[-1])
    assert tiger.name == "Tiger"
    # the same opening started with each of the other three first moves
    for seq in ("d3c5f6f5e6", "c4e3f6e6f5", "e6f4c3c4d3"):
        assert t.lookup(_positions(seq)[-1]).name == "Tiger"
    aubrey = t.lookup(_positions("f5d6c3d3c4b3")[-1])
    assert aubrey.name == "Aubrey" and "Tanaka" in aubrey.aliases


def test_names_along_carries_the_last_named_opening():
    names = table().names_along(_positions("f5d6c3d3c4f4c5b3c2e6"))
    assert names[0] is None
    assert names[2].name == "Perpendicular"
    assert names[5].name == "Tiger"
    assert names[-1].name == "Tamenori"


def test_session_reports_opening_and_distance(tmp_path):
    engine = SimpleNamespace(running=False, name="Edax", threads=1, error=None)

    async def broadcast(_):
        pass

    s = GameSession(engine, broadcast)
    s._set_moves(B.Position(), B.parse_transcript("f5d6c3d3c4g6"))  # Tiger, then an unnamed reply
    st = s.state()
    assert st["opening_name"]["name"] == "Tiger" and st["opening_name"]["since"] == 1
    assert [m["opening"] for m in st["moves"]][:5] == [None, "Perpendicular", None, None, "Tiger"]
    s.cursor = 2
    assert s.state()["opening_name"] == {"name": "Perpendicular", "aliases": [], "moves": "F5d6", "since": 0}
    s.cursor = 0
    assert s.state()["opening_name"] is None
