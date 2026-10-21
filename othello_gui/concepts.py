"""Describe a move in the vocabulary of Brian Rose's "Othello: A Minute to Learn...".

The training module uses this to explain *why* a move was good or bad in terms a
student is learning (quiet / loud, X-square, C-square, frontier discs, walls,
corner access, parity), and to tag a scrimmage mistake with the concept it
belongs to. Everything here is pure Python over the 64-character board strings
of :mod:`othello_gui.board`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import board as B

CORNERS = frozenset({0, 7, 56, 63})
X_SQUARES = frozenset({9, 14, 49, 54})
C_SQUARES = frozenset({1, 8, 6, 15, 48, 57, 55, 62})
A_SQUARES = frozenset({2, 5, 16, 40, 23, 47, 58, 61})
B_SQUARES = frozenset({3, 4, 24, 32, 31, 39, 59, 60})
EDGES = frozenset(sq for sq in range(64) if sq // 8 in (0, 7) or sq % 8 in (0, 7))

# corner -> the X-square and the two C-squares next to it
_CORNER_NEIGHBOURS = {0: (9, 1, 8), 7: (14, 6, 15), 56: (49, 48, 57), 63: (54, 55, 62)}


def square_class(sq: int) -> str:
    """'corner', 'X', 'C', 'A', 'B' (edge squares) or 'interior'."""
    if sq in CORNERS:
        return "corner"
    if sq in X_SQUARES:
        return "X"
    if sq in C_SQUARES:
        return "C"
    if sq in A_SQUARES:
        return "A"
    if sq in B_SQUARES:
        return "B"
    return "interior"


def _neighbours(sq: int) -> list[int]:
    r, c = divmod(sq, 8)
    out = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if (dr or dc) and 0 <= r + dr < 8 and 0 <= c + dc < 8:
                out.append((r + dr) * 8 + c + dc)
    return out


def frontier_discs(board: str, player: str) -> set[int]:
    """Discs of `player` that touch at least one empty square (edge discs are
    excluded, following the book's convention)."""
    out = set()
    for sq, v in enumerate(board):
        if v == player and sq not in EDGES and any(board[n] == B.EMPTY for n in _neighbours(sq)):
            out.add(sq)
    return out


def regions(board: str) -> list[list[int]]:
    """Connected groups of empty squares (8-neighbourhood), for parity."""
    seen: set[int] = set()
    out = []
    for start in range(64):
        if board[start] != B.EMPTY or start in seen:
            continue
        group, stack = [], [start]
        seen.add(start)
        while stack:
            sq = stack.pop()
            group.append(sq)
            for n in _neighbours(sq):
                if board[n] == B.EMPTY and n not in seen:
                    seen.add(n)
                    stack.append(n)
        out.append(sorted(group))
    return out


@dataclass
class MoveReport:
    sq: int
    player: str
    square_class: str
    flipped: int
    frontier_before: int  # mover's frontier discs before the move
    frontier_after: int  # ... and after it
    opp_moves_before: int  # opponent's mobility before and after
    opp_moves_after: int
    gives_corner: int | None  # corner the opponent can now take, if any (and could not before)
    takes_corner: bool
    tags: list[str] = field(default_factory=list)  # concept tags, e.g. "x-square", "loud"

    @property
    def new_frontier(self) -> int:
        return self.frontier_after - self.frontier_before

    @property
    def quiet(self) -> bool:
        return self.new_frontier <= 1


def attacks_corner(pos: B.Position, sq: int) -> bool:
    """After `sq`, could the mover take a corner next turn that it could not take before?"""
    me = pos.player
    after = pos.play(sq)
    before = set(B.legal_moves(pos.board, me)) & CORNERS
    now = set(B.legal_moves(after.board, me)) & CORNERS
    return bool(now - before - {sq})


def analyse_move(pos: B.Position, sq: int) -> MoveReport:
    """What a move does, in concept terms. `sq` must be legal for `pos`."""
    me, opp = pos.player, B.opponent(pos.player)
    after = pos.play(sq)
    flipped = B.flips(pos.board, sq, me)
    fb, fa = frontier_discs(pos.board, me), frontier_discs(after.board, me)
    opp_before = set(B.legal_moves(pos.board, opp))
    opp_after = set(B.legal_moves(after.board, opp))
    given = sorted((opp_after - opp_before) & CORNERS)
    report = MoveReport(
        sq=sq, player=me, square_class=square_class(sq), flipped=len(flipped),
        frontier_before=len(fb), frontier_after=len(fa),
        opp_moves_before=len(opp_before), opp_moves_after=len(opp_after),
        gives_corner=given[0] if given else None, takes_corner=sq in CORNERS,
    )
    tags = report.tags
    if report.takes_corner:
        tags.append("corner")
    if report.square_class == "X":
        tags.append("x-square")
    if report.square_class == "C":
        tags.append("c-square")
    if report.gives_corner is not None:
        tags.append("gives-corner")
    if not report.takes_corner and attacks_corner(pos, sq):
        tags.append("corner-attack")
    if sq in EDGES and not report.takes_corner:
        tags.append("edge")
    if report.new_frontier >= 4 or len(flipped) >= 6:
        tags.append("loud")
    elif report.new_frontier <= 0 and len(flipped) <= 2:
        tags.append("quiet")
    empties = pos.board.count(B.EMPTY)
    if empties <= 16:
        tags.append("endgame")
        region = next((r for r in regions(pos.board) if sq in r), [])
        if len(region) % 2 == 0:
            tags.append("even-region")
        else:
            tags.append("odd-region")
    if report.opp_moves_after > report.opp_moves_before + 2:
        tags.append("opens-options")
    return report


def describe(report: MoveReport) -> str:
    """One or two sentences a student can learn from."""
    name = B.sq_name(report.sq).upper()
    parts: list[str] = []
    if report.takes_corner:
        parts.append(f"{name} takes a corner: it can never be flipped and anchors stable discs.")
    elif report.square_class == "X":
        parts.append(f"{name} is an X-square, diagonally next to a corner; "
                     "it usually hands the corner to the opponent.")
    elif report.square_class == "C":
        parts.append(f"{name} is a C-square next to a corner, risky unless the edge is already yours.")
    if report.gives_corner is not None and not report.takes_corner:
        parts.append(f"It gives the opponent access to the {B.sq_name(report.gives_corner).upper()} corner.")
    nf = report.new_frontier
    flipped = _count(report.flipped, "disc")
    if nf >= 4:
        parts.append(f"It is loud: {flipped} flipped and {nf} new frontier discs for you to defend.")
    elif nf <= 0:
        parts.append(f"It is quiet: {flipped} flipped and no new frontier discs.")
    else:
        parts.append(f"It flips {flipped} and adds {_count(nf, 'frontier disc')}.")
    before, after = report.opp_moves_before, report.opp_moves_after
    if after > before + 2:
        parts.append(f"The opponent's options grow from {before} to {after} moves.")
    elif after + 2 < before:
        parts.append(f"The opponent's options shrink from {before} to {after} moves.")
    else:
        parts.append(f"The opponent keeps about the same options ({before} → {after} moves).")
    if "odd-region" in report.tags:
        parts.append("It is the first move into an odd region, which is usually right (parity).")
    elif "even-region" in report.tags:
        parts.append("It opens an even region, so the opponent will probably get the last move there.")
    return " ".join(parts)


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def compare(pos: B.Position, played: int, best: int, intro: str = "You played") -> str:
    """Explain a mistake: what the played move did versus what the best move does."""
    if played == best:
        return describe(analyse_move(pos, best))
    p, b = analyse_move(pos, played), analyse_move(pos, best)
    return f"{intro} {B.sq_name(played).upper()}. {describe(p)} Better is {B.sq_name(best).upper()}: {describe(b)}"


# Which concept tags belong to which curriculum unit (used to filter coach alerts
# during a themed scrimmage and to tag mistakes in the post-game review).
UNIT_CONCEPTS: dict[str, tuple[str, ...]] = {
    "corners": ("corner", "x-square", "c-square", "gives-corner"),
    "frontier": ("loud", "quiet", "opens-options"),
    "openings": ("loud", "quiet", "opens-options"),
    "edges": ("edge", "c-square", "gives-corner"),
    "endgame": ("endgame", "corner", "gives-corner"),
    "defense": ("opens-options", "quiet", "loud"),
    "parity": ("even-region", "odd-region", "endgame"),
    "tesuji1": ("corner", "gives-corner", "corner-attack", "x-square"),
    "tesuji2": ("corner", "gives-corner", "c-square", "corner-attack"),
    "book": ("loud", "quiet", "opens-options"),
    "masters": ("loud", "opens-options", "gives-corner", "x-square"),
    "midgame": ("loud", "quiet", "opens-options", "edge"),
    "counting": ("endgame", "even-region", "odd-region"),
    "rules": (),
}
