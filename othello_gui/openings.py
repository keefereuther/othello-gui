"""Named Othello openings (Tiger, Rose, Cat, ...).

The table in `data/openings.txt` comes from Chris Welty's GPL othello library.
Each line is a move sequence and a name. A position is named after the last
table entry the game passed through, and positions are compared under the 8
board symmetries, so an opening starting with D3, C4 or E6 is recognised as
well as the F5 form the table is written in.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import board as B
from .thor_index import U64, bitboards, canonical, position_key

DATA = Path(__file__).resolve().parent / "data" / "openings.txt"


@dataclass(frozen=True)
class Opening:
    name: str
    aliases: tuple[str, ...]
    moves: str  # the table's move sequence, e.g. "F5d6C3d3C4"

    @property
    def plies(self) -> int:
        return len(self.moves) // 2


@lru_cache(maxsize=4096)
def _key(board: str, player: str) -> int:
    b, w = bitboards(board)
    cb, cw, _ = canonical(np.array([b], dtype=U64), np.array([w], dtype=U64))
    return int(position_key(cb, cw, np.array([0 if player == B.BLACK else 1], dtype=np.uint8))[0])


class OpeningTable:
    def __init__(self, path: Path = DATA) -> None:
        self.by_key: dict[int, Opening] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            seq, names = parts
            moves = B.parse_transcript(seq)
            pos = B.replay(B.Position(), moves)[-1]  # raises if the table had an illegal line
            labels = [n.strip() for n in names.split(",") if n.strip()]
            self.by_key[_key(pos.board, pos.player)] = Opening(labels[0], tuple(labels[1:]), seq)

    def __len__(self) -> int:
        return len(self.by_key)

    def lookup(self, pos: B.Position) -> Opening | None:
        """The opening whose final position is exactly `pos` (up to symmetry)."""
        if pos.board.count(B.EMPTY) < 60 - 30:  # the table never goes beyond ~25 moves
            return None
        return self.by_key.get(_key(pos.board, pos.player))

    def names_along(self, positions: list[B.Position]) -> list[Opening | None]:
        """For each position, the opening reached there or earlier (None before any)."""
        out: list[Opening | None] = []
        current: Opening | None = None
        for pos in positions:
            hit = self.lookup(pos)
            if hit:
                current = hit
            out.append(current)
        return out


@lru_cache(maxsize=1)
def table() -> OpeningTable:
    return OpeningTable()
