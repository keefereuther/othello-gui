"""Shared test helpers.

`make_wthor` writes a tiny synthetic WTHOR database (the real files are not
redistributable) and returns it as a ThorDatabase. Players are 0 '???',
1 'Alice', 2 'Bob'; the only tournament is 'Test Open' in 2024.
"""

import struct
from collections.abc import Callable
from pathlib import Path

import pytest

from othello_gui import board as B
from othello_gui.wthor import ThorDatabase

_HEADER = "<BBBBIHHBBBB"


def write_wthor(directory: Path, games: list[tuple[str, int]]) -> ThorDatabase:
    """games: (transcript, black's final disc count)."""
    recs = b""
    for text, discs in games:
        moves = [(sq // 8 + 1) * 10 + (sq % 8 + 1) for sq in B.parse_transcript(text)]
        recs += struct.pack("<HHHBB60s", 0, 1, 2, discs, discs, bytes(moves).ljust(60, b"\0"))
    games_header = struct.pack(_HEADER, 20, 26, 1, 1, len(games), 0, 2024, 8, 0, 24, 0)
    (directory / "WTH_2024.wtb").write_bytes(games_header + recs)
    names = b"".join(n.ljust(20, b"\0") for n in (b"???", b"Alice", b"Bob"))
    (directory / "WTHOR.JOU").write_bytes(struct.pack(_HEADER, 20, 26, 1, 1, 0, 3, 0, 0, 0, 0, 0) + names)
    tournaments = b"Test Open".ljust(26, b"\0")
    (directory / "WTHOR.TRN").write_bytes(struct.pack(_HEADER, 20, 26, 1, 1, 0, 1, 0, 0, 0, 0, 0) + tournaments)
    return ThorDatabase(directory)


@pytest.fixture
def make_wthor(tmp_path: Path) -> Callable[[list[tuple[str, int]]], ThorDatabase]:
    return lambda games: write_wthor(tmp_path, games)
