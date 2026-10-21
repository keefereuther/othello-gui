"""Reader for the WTHOR tournament game database (Fédération Française d'Othello).

Files:
    WTHOR.JOU      players:     16-byte header, then 20-byte names
    WTHOR.TRN      tournaments: 16-byte header, then 26-byte names
    WTH_YYYY.wtb   games:       16-byte header, then 68-byte game records

Header (little endian): century, year, month, day (1 byte each), number of
games (uint32), number of records (uint16), game year (uint16), board size,
game type, depth of the theoretical score, reserved (1 byte each).

Game record: tournament id (uint16), black id (uint16), white id (uint16),
black's final disc count (uint8), theoretical score (uint8), then 60 move
bytes. A move byte is 10 * row + column, both 1-based, so f5 is 56; a zero
byte ends the move list. Passes are not recorded.

The files are free to download for personal use from https://www.ffothello.org
but are not freely redistributable, so this module reads them from a folder
rather than bundling them.
"""

from __future__ import annotations

import random
import struct
from dataclasses import dataclass
from pathlib import Path

from . import board as B

HEADER = struct.Struct("<BBBBIHHBBBB")
GAME = struct.Struct("<HHHBB60s")
RECORD_SIZE = 68


@dataclass(frozen=True)
class ThorGame:
    year: int
    tournament: str
    black: str
    white: str
    black_discs: int
    theoretical: int
    moves: tuple[int, ...]  # square indices, passes omitted

    @property
    def result(self) -> str:
        return f"{self.black_discs}-{64 - self.black_discs}"


def decode_move(byte: int) -> int:
    row, col = divmod(byte, 10)
    if not (1 <= row <= 8 and 1 <= col <= 8):
        raise ValueError(f"bad WTHOR move byte {byte}")
    return (row - 1) * 8 + (col - 1)


def _read_names(path: Path, width: int) -> list[str]:
    data = path.read_bytes()
    names = []
    for off in range(16, len(data) - width + 1, width):
        names.append(data[off : off + width].split(b"\0", 1)[0].decode("latin-1").strip())
    return names


class ThorDatabase:
    """All games from a WTHOR folder, kept as raw records and decoded on demand."""

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)
        self.players = _read_names(self.directory / "WTHOR.JOU", 20)
        self.tournaments = _read_names(self.directory / "WTHOR.TRN", 26)
        self.records: list[tuple[int, bytes]] = []  # (year, 68-byte record)
        for path in sorted(self.directory.glob("WTH_*.wtb")):
            data = path.read_bytes()
            if len(data) < 16:
                continue
            year = HEADER.unpack_from(data)[6]
            for off in range(16, len(data) - RECORD_SIZE + 1, RECORD_SIZE):
                self.records.append((year, data[off : off + RECORD_SIZE]))

    def __len__(self) -> int:
        return len(self.records)

    @property
    def years(self) -> tuple[int, int]:
        ys = [y for y, _ in self.records]
        return (min(ys), max(ys)) if ys else (0, 0)

    def game(self, index: int) -> ThorGame:
        year, rec = self.records[index]
        tourn, black, white, discs, theo, raw = GAME.unpack(rec)
        moves = []
        for b in raw:
            if b == 0:
                break
            moves.append(decode_move(b))
        return ThorGame(
            year,
            self._name(self.tournaments, tourn),
            self._name(self.players, black),
            self._name(self.players, white),
            discs,
            theo,
            tuple(moves),
        )

    def random_game(self, rng: random.Random | None = None, min_year: int | None = None) -> ThorGame:
        rng = rng or random
        candidates = range(len(self.records))
        if min_year:
            candidates = [i for i, (y, _) in enumerate(self.records) if y >= min_year]
            if not candidates:
                candidates = range(len(self.records))
        return self.game(rng.choice(candidates))

    def random_opening(
        self, plies: int, rng: random.Random | None = None, min_year: int | None = None
    ) -> tuple[ThorGame, list[int]]:
        """A random game and its first `plies` moves, verified legal."""
        for _ in range(50):
            game = self.random_game(rng, min_year)
            moves = list(game.moves[:plies])
            try:
                B.replay(B.Position(), moves)
            except ValueError:
                continue
            if len(moves) == plies:
                return game, moves
        raise ValueError("could not find a usable opening in the Thor database")

    @staticmethod
    def _name(table: list[str], idx: int) -> str:
        return table[idx] if 0 <= idx < len(table) else f"#{idx}"
