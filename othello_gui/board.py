"""Othello rules and notation.

The board is a 64-character string indexed a1=0, b1=1, ... h1=7, a2=8, ... h8=63.
Squares hold BLACK ("X"), WHITE ("O") or EMPTY ("-").  Edax uses "*" for black,
so :func:`to_edax` / :func:`from_edax` convert when talking to the engine.

Everything here is pure Python with no dependencies, so it is easy to test and
easy to reuse from a different front end.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

BLACK = "X"
WHITE = "O"
EMPTY = "-"
PASS = -1  # pseudo-square used for a pass

COLS = "abcdefgh"
START_BOARD = "-" * 27 + "OX" + "-" * 6 + "XO" + "-" * 27

# (row delta, column delta) for the eight directions
_DIRS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))

_MOVE_RE = re.compile(r"[a-hA-H][1-8]|[pP][aA](?:[sS]{2})?")


def opponent(player: str) -> str:
    return WHITE if player == BLACK else BLACK


def sq_name(sq: int) -> str:
    """Square index to algebraic name, e.g. 37 -> 'f5'. A pass is 'pa'."""
    if sq == PASS:
        return "pa"
    return f"{COLS[sq % 8]}{sq // 8 + 1}"


def parse_sq(name: str) -> int:
    """Algebraic name to square index. Accepts 'F5', 'f5', 'pa', 'pass'."""
    name = name.strip().lower()
    if name in ("pa", "pass", "ps", "--"):
        return PASS
    if len(name) != 2 or name[0] not in COLS or name[1] not in "12345678":
        raise ValueError(f"bad square name {name!r}")
    return (int(name[1]) - 1) * 8 + COLS.index(name[0])


def parse_transcript(text: str) -> list[int]:
    """Extract moves from text such as 'F5d6C3d3C4' or 'f5 d6 c3 ...'.

    Passes written as 'pa' or 'pass' are returned as PASS; passes that are
    simply omitted are inserted later by :func:`replay`.
    """
    return [parse_sq(m) for m in _MOVE_RE.findall(text)]


def flips(board: str, sq: int, player: str) -> list[int]:
    """Squares flipped if `player` plays `sq`; empty list means illegal."""
    if sq == PASS or board[sq] != EMPTY:
        return []
    opp = opponent(player)
    r0, c0 = divmod(sq, 8)
    flipped: list[int] = []
    for dr, dc in _DIRS:
        r, c = r0 + dr, c0 + dc
        line: list[int] = []
        while 0 <= r < 8 and 0 <= c < 8 and board[r * 8 + c] == opp:
            line.append(r * 8 + c)
            r += dr
            c += dc
        if line and 0 <= r < 8 and 0 <= c < 8 and board[r * 8 + c] == player:
            flipped.extend(line)
    return flipped


def legal_moves(board: str, player: str) -> list[int]:
    return [sq for sq in range(64) if board[sq] == EMPTY and flips(board, sq, player)]


def apply_move(board: str, sq: int, player: str) -> str:
    f = flips(board, sq, player)
    if not f:
        raise ValueError(f"illegal move {sq_name(sq)} for {player}")
    cells = list(board)
    for x in f:
        cells[x] = player
    cells[sq] = player
    return "".join(cells)


def counts(board: str) -> tuple[int, int, int]:
    """(black, white, empty) disc counts."""
    return board.count(BLACK), board.count(WHITE), board.count(EMPTY)


def to_edax(board: str) -> str:
    return board.replace(BLACK, "*")


def from_edax(board: str) -> str:
    return board.replace("*", BLACK)


@dataclass(frozen=True)
class Position:
    """An immutable board plus the player to move."""

    board: str = START_BOARD
    player: str = BLACK

    def legal(self) -> list[int]:
        return legal_moves(self.board, self.player)

    def must_pass(self) -> bool:
        """True when the player to move has no move but the opponent has."""
        return not self.legal() and bool(legal_moves(self.board, opponent(self.player)))

    def is_terminal(self) -> bool:
        return not self.legal() and not legal_moves(self.board, opponent(self.player))

    def play(self, sq: int) -> "Position":
        if sq == PASS:
            if self.legal():
                raise ValueError("cannot pass when a legal move exists")
            return Position(self.board, opponent(self.player))
        return Position(apply_move(self.board, sq, self.player), opponent(self.player))

    def disc_diff(self, perspective: str) -> int:
        """Final-score style disc difference, with empties given to the winner
        (the convention Edax uses for finished games)."""
        b, w, e = counts(self.board)
        if b > w:
            b += e
        elif w > b:
            w += e
        diff = b - w
        return diff if perspective == BLACK else -diff


def replay(start: Position, moves: list[int]) -> list[Position]:
    """Replay `moves` from `start`, inserting forced passes that the transcript
    omitted. Returns the list of positions, one more than the number of moves
    actually applied (passes included). Raises ValueError on an illegal move."""
    positions = [start]
    pos = start
    for sq in moves:
        if sq != PASS and pos.must_pass():
            pos = pos.play(PASS)
            positions.append(pos)
        pos = pos.play(sq)
        positions.append(pos)
    return positions


def ggf(start: Position, moves: list[int], black: str = "?", white: str = "?") -> str:
    """Generic Game Format string as Edax's NBoard mode expects it in `set game`."""
    tags = []
    pos = start
    for sq in moves:
        colour = "B" if pos.player == BLACK else "W"
        tags.append(f"{colour}[{sq_name(sq)}]")
        pos = pos.play(sq)
    to_move = "*" if start.player == BLACK else "O"
    return (
        f"(;GM[Othello]PC[othello-gui]PB[{black}]PW[{white}]RE[?]TI[0//0]TY[8]"
        f"BO[8 {to_edax(start.board)} {to_move}]{''.join(tags)};)"
    )


def transcript(moves: list[int]) -> str:
    """Compact transcript, e.g. 'F5d6C3d3C4'. Black moves upper case."""
    out = []
    for i, sq in enumerate(moves):
        name = sq_name(sq)
        out.append(name.upper() if i % 2 == 0 else name)
    return "".join(out)
