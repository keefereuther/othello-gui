"""Position index over the WTHOR database.

Every game is replayed (all games at once, vectorised with numpy bitboards)
and every position up to `MAX_PLY` moves is recorded as

    key   uint64  hash of the *canonical* position (see below) + side to move
    game  uint32  game index in the ThorDatabase
    next  uint8   the move played from that position, in canonical
                  coordinates (255 = the game ended / no move recorded)

sorted by key, so a lookup is two binary searches.

Symmetry: Othello positions come in families of up to 8 equivalent boards
(4 rotations x reflection). A position is normalised by applying all 8
transforms and keeping the lexicographically smallest (black, white)
bitboard pair; the transform used is remembered so the continuation moves of
other games can be mapped back onto the board the user is looking at.
WTHOR stores every game starting with F5, so without this a game opened with
D3, C4 or E6 would find nothing.

Bitboards use the GUI's square numbering: a1 = bit 0, h1 = bit 7, a2 = bit 8 ...

The index is cached next to the WTHOR files (`thor-index.npz`) and rebuilt
automatically when the files change. Building it takes a few seconds.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from . import board as B
from .wthor import RECORD_SIZE, ThorDatabase

log = logging.getLogger(__name__)

MAX_PLY = 40          # positions after 0..MAX_PLY moves are indexed
NO_MOVE = 255
CACHE_NAME = "thor-index.npz"
CACHE_VERSION = 1

U64 = np.uint64
_FILE_A = U64(0x0101010101010101)
_FILE_H = U64(0x8080808080808080)
_NOT_A = ~_FILE_A
_NOT_H = ~_FILE_H

# (shift amount, shift left?, mask applied after the shift)
_DIRS = (
    (1, True, _NOT_A), (1, False, _NOT_H),     # east, west
    (8, True, None), (8, False, None),         # north (up the ranks), south
    (9, True, _NOT_A), (7, True, _NOT_H),      # +1 rank +1 file, +1 rank -1 file
    (7, False, _NOT_A), (9, False, _NOT_H),    # -1 rank +1 file, -1 rank -1 file
)


# --------------------------------------------------------------------------- bit tricks

def _shift(x: np.ndarray, n: int, left: bool, mask) -> np.ndarray:
    y = np.left_shift(x, U64(n)) if left else np.right_shift(x, U64(n))
    return y if mask is None else y & mask


def _flips(move_bit: np.ndarray, player: np.ndarray, opp: np.ndarray) -> np.ndarray:
    """Discs flipped when `player` plays the single-bit `move_bit` (vectorised)."""
    flips = np.zeros_like(player)
    for n, left, mask in _DIRS:
        x = _shift(move_bit, n, left, mask) & opp
        for _ in range(5):
            x |= _shift(x, n, left, mask) & opp
        bounded = (_shift(x, n, left, mask) & player) != 0
        flips |= np.where(bounded, x, U64(0))
    return flips


def _mirror_h(x: np.ndarray) -> np.ndarray:
    """Reverse the files (a<->h) by reversing the bits of every byte."""
    k1, k2, k4 = U64(0x5555555555555555), U64(0x3333333333333333), U64(0x0F0F0F0F0F0F0F0F)
    x = ((x >> U64(1)) & k1) | ((x & k1) << U64(1))
    x = ((x >> U64(2)) & k2) | ((x & k2) << U64(2))
    return ((x >> U64(4)) & k4) | ((x & k4) << U64(4))


def _flip_v(x: np.ndarray) -> np.ndarray:
    """Reverse the ranks (1<->8): one rank per byte."""
    return x.byteswap()


def _transpose(x: np.ndarray) -> np.ndarray:
    """Reflect in the a1-h8 diagonal."""
    k1, k2, k4 = U64(0x5500550055005500), U64(0x3333000033330000), U64(0x0F0F0F0F00000000)
    t = k4 & (x ^ (x << U64(28)))
    x = x ^ t ^ (t >> U64(28))
    t = k2 & (x ^ (x << U64(14)))
    x = x ^ t ^ (t >> U64(14))
    t = k1 & (x ^ (x << U64(7)))
    return x ^ t ^ (t >> U64(7))


def transform(x: np.ndarray, t: int) -> np.ndarray:
    """Apply symmetry t (0..7): bit0 = mirror files, bit1 = flip ranks, bit2 = transpose."""
    if t & 1:
        x = _mirror_h(x)
    if t & 2:
        x = _flip_v(x)
    if t & 4:
        x = _transpose(x)
    return x


def _square_maps() -> tuple[np.ndarray, np.ndarray]:
    """SQMAP[t, sq] = square that sq goes to under t (256 wide so NO_MOVE maps to itself);
    INVERSE[t] = the transform undoing t."""
    bits = np.array([1 << s for s in range(64)], dtype=U64)
    sqmap = np.full((8, 256), NO_MOVE, dtype=np.uint8)
    for t in range(8):
        sqmap[t, :64] = [int(v).bit_length() - 1 for v in transform(bits, t)]
    inverse = np.zeros(8, dtype=np.uint8)
    for t in range(8):
        for u in range(8):
            if np.array_equal(sqmap[u, sqmap[t, :64]], np.arange(64)):
                inverse[t] = u
    return sqmap, inverse


SQMAP, INVERSE = _square_maps()


def canonical(black: np.ndarray, white: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Smallest (black, white) pair over the 8 symmetries, plus the transform giving it."""
    best_b, best_w = black.copy(), white.copy()
    best_t = np.zeros(black.shape, dtype=np.uint8)
    for t in range(1, 8):
        tb, tw = transform(black, t), transform(white, t)
        better = (tb < best_b) | ((tb == best_b) & (tw < best_w))
        best_b = np.where(better, tb, best_b)
        best_w = np.where(better, tw, best_w)
        best_t = np.where(better, np.uint8(t), best_t)
    return best_b, best_w, best_t


def _mix(x: np.ndarray) -> np.ndarray:
    """splitmix64 finaliser (wrapping uint64 arithmetic)."""
    with np.errstate(over="ignore"):
        x = (x ^ (x >> U64(30))) * U64(0xBF58476D1CE4E5B9)
        x = (x ^ (x >> U64(27))) * U64(0x94D049BB133111EB)
        return x ^ (x >> U64(31))


def position_key(black: np.ndarray, white: np.ndarray, stm: np.ndarray) -> np.ndarray:
    """64-bit hash of an already-canonical position and the side to move (0 black, 1 white)."""
    with np.errstate(over="ignore"):
        return _mix(black ^ _mix(white ^ (stm.astype(U64) * U64(0x9E3779B97F4A7C15))))


def bitboards(board: str) -> tuple[int, int]:
    """GUI board string -> (black, white) Python ints."""
    black = white = 0
    for sq, c in enumerate(board):
        if c == B.BLACK:
            black |= 1 << sq
        elif c == B.WHITE:
            white |= 1 << sq
    return black, white


# --------------------------------------------------------------------------- the index

@dataclass
class Filters:
    min_year: int | None = None
    player: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"min_year": self.min_year, "player": self.player}


class ThorIndex:
    def __init__(self, db: ThorDatabase, keys: np.ndarray, games: np.ndarray, nexts: np.ndarray) -> None:
        self.db = db
        self.keys, self.games, self.nexts = keys, games, nexts
        header = _header_matrix(db)
        self.years = np.array([y for y, _ in db.records], dtype=np.uint16)
        self.tournament = header[:, 0].astype(np.uint16) | (header[:, 1].astype(np.uint16) << 8)
        self.black_id = header[:, 2].astype(np.uint16) | (header[:, 3].astype(np.uint16) << 8)
        self.white_id = header[:, 4].astype(np.uint16) | (header[:, 5].astype(np.uint16) << 8)
        self.black_discs = header[:, 6].astype(np.int16)
        self._player_cache: tuple[str, np.ndarray] | None = None

    def __len__(self) -> int:
        return len(self.keys)

    # ---------------------------------------------------------------- build / cache

    @classmethod
    def load_or_build(
        cls, db: ThorDatabase, progress: Callable[[float], None] | None = None, cache_dir: Path | None = None
    ) -> ThorIndex:
        cache = (cache_dir or db.directory) / CACHE_NAME
        signature = _signature(db.directory)
        if cache.exists():
            try:
                with np.load(cache, allow_pickle=False) as z:
                    if str(z["signature"]) == signature and len(z["keys"]) == len(z["games"]):
                        log.info("Thor index loaded from cache (%d positions)", len(z["keys"]))
                        return cls(db, z["keys"], z["games"], z["nexts"])
            except Exception as e:  # corrupt or old cache: rebuild
                log.warning("ignoring Thor index cache: %s", e)
        idx = cls.build(db, progress)
        try:
            tmp = cache.with_suffix(".tmp.npz")
            np.savez(tmp, keys=idx.keys, games=idx.games, nexts=idx.nexts, signature=np.array(signature))
            tmp.replace(cache)
        except OSError as e:
            log.warning("could not write Thor index cache %s: %s", cache, e)
        return idx

    @classmethod
    def build(cls, db: ThorDatabase, progress: Callable[[float], None] | None = None) -> ThorIndex:
        t0 = time.time()
        n = len(db)
        header = _header_matrix(db)
        raw = header[:, 8:68].astype(np.int16)
        row, col = raw // 10 - 1, raw % 10 - 1
        valid = (raw > 0) & (row >= 0) & (row < 8) & (col >= 0) & (col < 8)
        moves = np.where(valid, row * 8 + col, NO_MOVE).astype(np.uint8)
        # a zero byte ends the game; anything after an invalid byte is ignored too
        moves = np.where(np.cumprod(valid, axis=1).astype(bool), moves, np.uint8(NO_MOVE))

        black = np.full(n, U64((1 << 28) | (1 << 35)))
        white = np.full(n, U64((1 << 27) | (1 << 36)))
        stm = np.zeros(n, dtype=np.uint8)          # 0 = black to move
        alive = np.ones(n, dtype=bool)
        keys, games, nexts = [], [], []

        for ply in range(MAX_PLY + 1):
            idx = np.nonzero(alive)[0]
            if not len(idx):
                break
            b, w, s = black[idx], white[idx], stm[idx]
            nxt = moves[idx, ply] if ply < 60 else np.full(len(idx), NO_MOVE, dtype=np.uint8)
            has_move = nxt != NO_MOVE
            bit = np.left_shift(U64(1), np.where(has_move, nxt, 0).astype(U64))
            empty = (bit & (b | w)) == 0

            # Resolve passes (WTHOR omits them): if the nominal mover cannot play
            # the recorded move, the other side must be the one moving.
            mover, opp = np.where(s == 0, b, w), np.where(s == 0, w, b)
            f = _flips(bit, mover, opp)
            swap = has_move & empty & (f == 0)
            f2 = _flips(bit, opp, mover)
            s = np.where(swap & (f2 != 0), 1 - s, s).astype(np.uint8)
            f = np.where(swap, f2, f)
            legal = has_move & empty & (f != 0)

            cb, cw, ct = canonical(b, w)
            keys.append(position_key(cb, cw, s))
            games.append(idx.astype(np.uint32))
            nexts.append(np.where(legal, SQMAP[ct, nxt], np.uint8(NO_MOVE)).astype(np.uint8))

            # play the move
            mover, opp = np.where(s == 0, b, w), np.where(s == 0, w, b)
            mover = np.where(legal, mover | f | bit, mover)
            opp = np.where(legal, opp & ~f, opp)
            black[idx] = np.where(s == 0, mover, opp)
            white[idx] = np.where(s == 0, opp, mover)
            stm[idx] = 1 - s
            alive[idx] = legal
            if progress:
                progress(0.95 * (ply + 1) / (MAX_PLY + 1))

        k = np.concatenate(keys)
        order = np.argsort(k, kind="stable")
        idx_obj = cls(db, k[order], np.concatenate(games)[order], np.concatenate(nexts)[order])
        if progress:
            progress(1.0)
        log.info("Thor index built: %d positions from %d games in %.1fs", len(k), n, time.time() - t0)
        return idx_obj

    # ---------------------------------------------------------------- queries

    def locate(self, board: str, player: str) -> tuple[int, int, int, int, int]:
        """(lo, hi, transform, black, white) for a position given as a GUI board string."""
        bb, ww = bitboards(board)
        b, w = np.array([bb], dtype=U64), np.array([ww], dtype=U64)
        cb, cw, ct = canonical(b, w)
        key = position_key(cb, cw, np.array([0 if player == B.BLACK else 1], dtype=np.uint8))[0]
        lo = int(np.searchsorted(self.keys, key, "left"))
        hi = int(np.searchsorted(self.keys, key, "right"))
        return lo, hi, int(ct[0]), bb, ww

    def _player_mask(self, text: str) -> np.ndarray:
        text = text.strip().lower()
        if self._player_cache and self._player_cache[0] == text:
            return self._player_cache[1]
        size = max(len(self.db.players), int(self.black_id.max()) + 1, int(self.white_id.max()) + 1)
        mask = np.zeros(size, dtype=bool)
        for i, name in enumerate(self.db.players):
            if text in name.lower():
                mask[i] = True
        self._player_cache = (text, mask)
        return mask

    def lookup(self, board: str, player: str, filters: Filters | None = None, sample: int = 50) -> dict[str, Any]:
        filters = filters or Filters()
        lo, hi, t, bb, ww = self.locate(board, player)
        g = self.games[lo:hi]
        nx = self.nexts[lo:hi]
        keep = np.ones(len(g), dtype=bool)
        if filters.min_year:
            keep &= self.years[g] >= filters.min_year
        if filters.player.strip():
            pm = self._player_mask(filters.player)
            keep &= pm[self.black_id[g]] | pm[self.white_id[g]]
        g, nx = g[keep], nx[keep]

        discs = self.black_discs[g]
        black_win, draw = discs > 32, discs == 32
        out: dict[str, Any] = {
            "games": int(len(g)),
            "black_wins": int(black_win.sum()),
            "draws": int(draw.sum()),
            "white_wins": int((discs < 32).sum()),
            "continuations": self._continuations(nx, black_win, draw, t, bb, ww),
            "sample": [],
        }
        if len(g):
            order = np.lexsort((g, self.years[g]))[::-1][:sample]
            for i in g[order]:
                gi = int(i)
                out["sample"].append({
                    "index": gi,
                    "year": int(self.years[gi]),
                    "tournament": self.db._name(self.db.tournaments, int(self.tournament[gi])),
                    "black": self.db._name(self.db.players, int(self.black_id[gi])),
                    "white": self.db._name(self.db.players, int(self.white_id[gi])),
                    "result": f"{int(self.black_discs[gi])}-{64 - int(self.black_discs[gi])}",
                })
        return out

    def _continuations(self, nx, black_win, draw, t, bb, ww) -> list[dict[str, Any]]:
        has = nx != NO_MOVE
        if not has.any():
            return []
        actual = SQMAP[INVERSE[t], nx[has]].astype(np.int64)
        bw, dr = black_win[has], draw[has]
        # On a symmetric board, equivalent moves are one move: merge each orbit.
        b, w = np.array([bb], dtype=U64), np.array([ww], dtype=U64)
        stab = [s for s in range(8) if transform(b, s)[0] == b[0] and transform(w, s)[0] == w[0]]
        rep = actual.copy()
        for s in stab[1:]:
            rep = np.minimum(rep, SQMAP[s, actual].astype(np.int64))
        result = []
        for r in np.unique(rep):
            sel = rep == r
            squares, counts = np.unique(actual[sel], return_counts=True)
            sq = int(squares[np.argmax(counts)])
            n, wins, draws = int(sel.sum()), int(bw[sel].sum()), int(dr[sel].sum())
            result.append({
                "move": sq,
                "name": B.sq_name(sq),
                "games": n,
                "black_win_pct": round(100.0 * wins / n, 1),
                "draws": draws,
                "black_wins": wins,
                "white_wins": n - wins - draws,
            })
        result.sort(key=lambda c: -c["games"])
        return result

    def game_aligned(self, index: int, board: str, player: str) -> tuple[list[int], int | None]:
        """The moves of game `index`, transformed so that it passes through the given
        position on the same orientation, plus the ply where it does (None if it
        never does). Falls back to the game as recorded."""
        moves = list(self.db.game(index).moves)
        target_b, target_w = bitboards(board)
        try:
            positions = B.replay(B.Position(), moves)
        except ValueError:
            return moves, None
        start = np.array([bitboards(B.START_BOARD)[0]], dtype=U64), np.array([bitboards(B.START_BOARD)[1]], dtype=U64)
        tb, tw = np.array([target_b], dtype=U64), np.array([target_w], dtype=U64)
        for ply, pos in enumerate(positions):
            if pos.player != player or pos.board.count("-") != board.count("-"):
                continue
            gb, gw = bitboards(pos.board)
            gbv, gwv = np.array([gb], dtype=U64), np.array([gw], dtype=U64)
            candidates = [u for u in range(8) if transform(gbv, u)[0] == tb[0] and transform(gwv, u)[0] == tw[0]]
            if not candidates:
                continue
            # prefer a symmetry that keeps the standard start position, so the
            # transformed game is still a legal game from the start
            for u in candidates:
                if transform(start[0], u)[0] == start[0][0] and transform(start[1], u)[0] == start[1][0]:
                    return [int(SQMAP[u, m]) for m in moves], ply
            return moves, None
        return moves, None


def _header_matrix(db: ThorDatabase) -> np.ndarray:
    return np.frombuffer(b"".join(rec for _, rec in db.records), dtype=np.uint8).reshape(-1, RECORD_SIZE)


def _signature(directory: Path) -> str:
    files = sorted(directory.glob("WTH_*.wtb")) + [directory / "WTHOR.JOU", directory / "WTHOR.TRN"]
    parts = [(f.name, f.stat().st_size, f.stat().st_mtime_ns) for f in files if f.exists()]
    return json.dumps({"version": CACHE_VERSION, "max_ply": MAX_PLY, "files": parts})
