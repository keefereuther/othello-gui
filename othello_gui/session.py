"""Game session: the state behind the GUI and the logic that drives Edax.

A session holds one game (start position + moves), a cursor into that game
for reviewing, who plays each colour, and the analysis results.  Whenever the
state changes, :meth:`GameSession.touch` bumps a generation counter and makes
sure a single worker task is running.  The worker looks at the current state,
asks Edax for whatever is needed (an engine move, or hints for the human), and
applies the answer only if the state has not changed in the meantime.

The NBoard protocol has no "stop" command, so we never cancel a running
search; we just ignore its result when it is stale.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from . import board as B
from . import concepts, openings
from .engine import Edax, EdaxError, Hint
from .thor_index import Filters, ThorIndex
from .wthor import ThorDatabase

log = logging.getLogger(__name__)

Broadcast = Callable[[dict[str, Any]], Awaitable[None]]

HUMAN = "human"
EDAX = "edax"


@dataclass
class MoveRecord:
    sq: int
    player: str
    position: B.Position  # position *after* the move
    eval_black: float | None = None  # evaluation after the move, black's view
    eval_source: str | None = None  # "engine" (from go) or "analysis"
    loss: float | None = None  # discs lost compared with the best move
    best: int | None = None  # best move at the position before this move
    flips: list[int] = field(default_factory=list)  # squares turned over by this move
    reviewed: bool = False  # the coach / puzzle has evaluated this move

    def to_json(self) -> dict[str, Any]:
        return {
            "sq": self.sq,
            "name": B.sq_name(self.sq),
            "player": self.player,
            "eval": self.eval_black,
            "eval_source": self.eval_source,
            "loss": self.loss,
            "best": B.sq_name(self.best) if self.best is not None else None,
            "flips": self.flips,
        }


@dataclass
class Analysis:
    running: bool = False
    done: int = 0
    total: int = 0
    level: int = 0


class GameSession:
    def __init__(self, engine: Edax, broadcast: Broadcast, thor: ThorDatabase | None = None) -> None:
        self.engine = engine
        self.broadcast = broadcast
        self.thor = thor
        self.thor_index: ThorIndex | None = None  # set by the server once built/loaded
        self.thor_progress = 0.0
        self.thor_error: str | None = None
        self.thor_filters = Filters()
        self.opening: dict[str, Any] | None = None  # info about a Thor opening / game in use
        self.start = B.Position()
        self.moves: list[MoveRecord] = []
        self.cursor = 0  # number of moves currently displayed
        self.players = {B.BLACK: HUMAN, B.WHITE: EDAX}
        self.level = 8
        self.variety = 0  # discs: engine picks randomly among moves within this of the best (0 = always best)
        self.move_time: float | None = None  # seconds per Edax move; None = play to the fixed level
        self._play_engine: Edax | None = None  # second Edax with a time limit (hints/analysis stay on `engine`)
        self.engine_factory: Callable[..., Edax] = Edax
        self.coach_enabled = False
        self.coach_threshold = 4  # discs lost that make the coach pause the game
        self.coach_alert: dict[str, Any] | None = None  # set while the coach is waiting for you
        self.review_level: int | None = None  # level the coach judges moves at (None: the play level)
        self.trainer: Any = None  # training.Trainer, attached by the server
        self.puzzle: dict[str, Any] | None = None  # endgame puzzle in progress
        self.hints_enabled = True
        self.hint_count = 4
        self.hints: list[Hint] = []
        self.hints_cursor: int | None = None  # cursor the hints belong to
        self.analysis = Analysis()
        self.best_scores: dict[int, tuple[int, float]] = {}  # position idx -> (move, score)
        self.thinking = False
        self.status = "idle"
        self.nodes = 0
        self.engine_error: str | None = None
        self._gen = 0
        self._hints_gen = -1
        self._worker: asyncio.Task | None = None
        self._engine_lock = asyncio.Lock()  # set_game + hint/go must be atomic

    # ------------------------------------------------------------------ queries

    def positions(self) -> list[B.Position]:
        return [self.start] + [m.position for m in self.moves]

    @property
    def current(self) -> B.Position:
        return self.start if self.cursor == 0 else self.moves[self.cursor - 1].position

    @property
    def at_tip(self) -> bool:
        return self.cursor == len(self.moves)

    def state(self) -> dict[str, Any]:
        pos = self.current
        black, white, empty = B.counts(pos.board)
        return {
            "type": "state",
            "board": pos.board,
            "to_move": pos.player,
            "legal": pos.legal(),
            "moves": self._moves_json(),
            "opening_name": self._opening_at_cursor(),
            "cursor": self.cursor,
            "players": self.players,
            "level": self.level,
            "variety": self.variety,
            "move_time": self.move_time,
            "coach": {"enabled": self.coach_enabled, "threshold": self.coach_threshold},
            "coach_alert": self.coach_alert,
            "puzzle": self.puzzle,
            "game_over": self.moves[-1].position.is_terminal() if self.moves else pos.is_terminal(),
            "black": black,
            "white": white,
            "empty": empty,
            "hints_enabled": self.hints_enabled,
            "hint_count": self.hint_count,
            "thinking": self.thinking,
            "status": self.status,
            "nodes": self.nodes,
            "engine": {
                "name": self.engine.name,
                "running": self.engine.running,
                "error": self.engine_error,
                "threads": self.engine.threads,
            },
            "analysis": asdict(self.analysis),
            "opening": self.opening,
            "thor_games": len(self.thor) if self.thor else 0,
            "training": self.trainer.to_json() if self.trainer else None,
            "transcript": B.transcript([m.sq for m in self.moves]),
        }

    def _moves_json(self) -> list[dict[str, Any]]:
        """Moves for the client, each tagged with the named opening it completes (if any)."""
        out = [m.to_json() for m in self.moves]
        try:
            table = openings.table()
        except Exception:  # missing/corrupt table: names are optional
            return out
        for rec, js in zip(self.moves, out, strict=True):
            hit = table.lookup(rec.position) if rec.sq != B.PASS else None
            js["opening"] = hit.name if hit else None
        return out

    def _opening_at_cursor(self) -> dict[str, Any] | None:
        """The named opening the game has passed through up to the cursor, and how
        many moves ago it was left (0 = the board is exactly that opening)."""
        if self.start != B.Position():
            return None
        try:
            table = openings.table()
        except Exception:
            return None
        positions = self.positions()[: self.cursor + 1]
        for i in range(len(positions) - 1, 0, -1):
            hit = table.lookup(positions[i])
            if hit:
                return {
                    "name": hit.name, "aliases": list(hit.aliases), "moves": hit.moves, "since": len(positions) - 1 - i,
                }
        return None

    def hints_message(self) -> dict[str, Any]:
        return {
            "type": "hints",
            "cursor": self.hints_cursor,
            "hints": [
                {
                    "sq": h.move,
                    "name": B.sq_name(h.move),
                    "score": h.score,
                    "depth": h.depth,
                    "pv": [B.sq_name(s) for s in h.pv],
                    "book": h.book,
                    "book_games": h.book_games,
                }
                for h in self.hints
            ],
        }

    # ------------------------------------------------------------------ mutations

    async def new_game(
        self, black: str, white: str, level: int | None = None, opening: dict[str, Any] | None = None
    ) -> None:
        """Start a game. `opening` may be {"type": "thor", "plies": 8, "min_year": 2000}
        to begin from the first moves of a random tournament game."""
        self._training_reset()
        moves: list[int] = []
        self.opening = None
        if opening and opening.get("type") == "thor" and int(opening.get("plies", 0)) > 0:
            if not self.thor:
                raise ValueError("Thor database not loaded (set WTHOR_DIR to the folder with the WTH_*.wtb files)")
            plies = max(1, min(40, int(opening["plies"])))
            game, moves = self.thor.random_opening(plies, min_year=opening.get("min_year"))
            self.opening = {
                "black": game.black, "white": game.white, "tournament": game.tournament,
                "year": game.year, "result": game.result, "plies": plies,
            }
        self._set_moves(B.Position(), moves)
        self.players = {B.BLACK: black, B.WHITE: white}
        if level:
            self.level = int(level)
        self._reset_game_state()
        await self.touch()

    def _set_moves(self, start: B.Position, moves: list[int]) -> None:
        """Replace the game with `moves` played from `start` (forced passes added)."""
        positions = B.replay(start, moves)  # raises on illegal moves
        self.start = positions[0]
        self.moves = []
        pos = self.start
        for nxt in positions[1:]:
            sq = _move_between(pos, nxt)
            flips = B.flips(pos.board, sq, pos.player) if sq != B.PASS else []
            self.moves.append(MoveRecord(sq, pos.player, nxt, flips=flips))
            pos = nxt
        self.cursor = len(self.moves)

    async def user_move(self, sq: int) -> None:
        pos = self.current
        if sq not in pos.legal():
            raise ValueError(f"{B.sq_name(sq)} is not a legal move")
        if self.puzzle and self.puzzle["status"] == "solving":
            raise ValueError("one moment, Edax is still solving the puzzle")
        if self.trainer:
            self.trainer.before_user_move()
        self.coach_alert = None
        if not self.at_tip:
            # playing a new move while reviewing truncates the future
            del self.moves[self.cursor :]
            self.best_scores = {k: v for k, v in self.best_scores.items() if k <= self.cursor}
        self._append(sq)
        if self.trainer:
            self.trainer.after_user_move(pos, sq)
        await self.touch()

    async def undo(self) -> None:
        """Take back moves until a human is to move again (at least one)."""
        if not self.moves:
            return
        self.moves.pop()
        while self.moves and (
            self.moves[-1].sq == B.PASS or self.players[self.moves[-1].position.player] != HUMAN
        ):
            self.moves.pop()
        self.cursor = len(self.moves)
        self.best_scores = {k: v for k, v in self.best_scores.items() if k <= self.cursor}
        self.coach_alert = None
        if self.puzzle and self.cursor == 0 and self.puzzle["status"] in ("solved", "missed"):
            self.puzzle.update(status="ask", played=None, played_score=None, loss=None)
        await self.touch()

    async def goto(self, index: int) -> None:
        self.cursor = max(0, min(len(self.moves), int(index)))
        await self.touch()

    async def set_level(self, level: int) -> None:
        self.level = max(1, min(60, int(level)))
        self._hints_gen = -1  # re-hint at the new level
        await self.touch()

    async def set_variety(self, discs: int) -> None:
        self.variety = max(0, min(16, int(discs)))
        await self.touch()

    async def set_move_time(self, seconds: Any) -> None:
        """Let Edax think for a fixed time per move instead of to a fixed level.
        Hints and analysis keep using the level."""
        value = float(seconds) if seconds not in (None, "", 0, "0") else None
        if value is not None and not 0.1 <= value <= 600:
            raise ValueError("time per move must be between 0.1 and 600 seconds")
        self.move_time = value
        if value is None and self._play_engine is not None:
            engine, self._play_engine = self._play_engine, None
            await engine.quit()
        await self.touch()

    async def set_coach(self, enabled: bool, threshold: Any = None) -> None:
        self.coach_enabled = bool(enabled)
        if threshold:
            self.coach_threshold = max(1, min(32, int(threshold)))
        if not self.coach_enabled:
            self.coach_alert = None
        await self.touch()

    async def coach_continue(self) -> None:
        """Accept the move the coach flagged and let the game go on."""
        self.coach_alert = None
        await self.touch()

    async def start_puzzle(self, empties: int = 12) -> None:
        """Cut a random tournament game at `empties` empty squares, let Edax solve it
        exactly, and ask the player for the best move."""
        self._training_reset()
        if not self.thor:
            raise ValueError("endgame puzzles need the Thor database (see the Thor card)")
        empties = max(6, min(20, int(empties)))
        rng = random.Random()
        pos: B.Position | None = None
        for _ in range(500):
            game = self.thor.random_game(rng)
            try:
                positions = B.replay(B.Position(), list(game.moves))
            except ValueError:
                continue
            for p in positions:
                if (
                    p.board.count(B.EMPTY) == empties
                    and not p.is_terminal()
                    and not p.must_pass()
                    and len(p.legal()) >= 2
                ):
                    pos = p
                    break
            if pos is not None:
                break
        if pos is None:
            raise ValueError("could not find a suitable puzzle position")
        self.start = pos
        self.moves = []
        self.cursor = 0
        self.players = {pos.player: HUMAN, B.opponent(pos.player): EDAX}
        self.level = max(self.level, (empties + 1) // 2)  # enough for an exact solve
        self._reset_game_state()
        self.opening = {
            "black": game.black, "white": game.white, "tournament": game.tournament, "year": game.year,
            "result": game.result, "plies": len(game.moves), "puzzle": True, "empties": empties,
        }
        self.puzzle = {
            "empties": empties, "to_move": pos.player, "status": "solving", "level": self.level,
            "best": None, "best_sq": None, "best_score": None, "played": None, "played_score": None, "loss": None,
        }
        await self.touch()  # show the position while Edax solves it
        gen = self._gen
        async with self._engine_lock:
            if self._gen != gen:
                return
            self.thinking = True
            self.status = "solving the puzzle"
            await self.broadcast(self.state())
            await self._sync_level()
            best = await self._best_at(0)
        self.thinking = False
        self.status = "idle"
        if self._gen != gen or not self.puzzle:
            return
        if best is None:
            self.puzzle = None
            raise EdaxError("Edax could not solve the puzzle")
        self.best_scores[0] = best
        self.puzzle.update(status="ask", best=B.sq_name(best[0]), best_sq=best[0], best_score=best[1])
        await self.touch()

    async def close(self) -> None:
        if self._play_engine is not None:
            await self._play_engine.quit()
            self._play_engine = None

    async def set_players(self, black: str, white: str) -> None:
        self.players = {B.BLACK: black, B.WHITE: white}
        await self.touch()

    async def set_hints(self, enabled: bool, count: int | None = None) -> None:
        self.hints_enabled = bool(enabled)
        if count:
            self.hint_count = max(1, min(32, int(count)))
        self._hints_gen = -1
        if not self.hints_enabled:
            self._clear_hints()
            await self.broadcast(self.hints_message())
        await self.touch()

    async def load_transcript(self, text: str) -> None:
        """Load a game from a move list (F5d6C3...) or a GGF string."""
        self._training_reset()
        moves = B.parse_transcript(_strip_ggf(text))
        if not moves:
            raise ValueError("no moves found in the transcript")
        self._set_moves(B.Position(), moves)
        self.opening = None
        self.players = {B.BLACK: HUMAN, B.WHITE: HUMAN}  # review mode: nobody auto-plays
        self._reset_game_state()
        await self.touch()

    # ------------------------------------------------------------------ Thor database

    def thor_message(self) -> dict[str, Any]:
        """Statistics from the Thor database for the position on the board."""
        msg: dict[str, Any] = {"type": "thor", "cursor": self.cursor, "filters": self.thor_filters.to_json()}
        if self.thor is None:
            return {**msg, "ready": False, "available": False, "error": "Thor database not found"}
        if self.thor_index is None:
            progress = round(self.thor_progress, 3)
            return {**msg, "ready": False, "available": True, "progress": progress, "error": self.thor_error}
        pos = self.current
        result = self.thor_index.lookup(pos.board, pos.player, self.thor_filters)
        return {**msg, "ready": True, "available": True, "board": pos.board, "to_move": pos.player, **result}

    async def thor_lookup(self) -> None:
        await self.broadcast(self.thor_message())

    async def set_thor_filters(self, min_year: Any = None, player: Any = "") -> None:
        year = int(min_year) if min_year not in (None, "", 0, "0") else None
        if year is not None and not 1900 <= year <= 2100:
            raise ValueError("minimum year must be between 1900 and 2100")
        self.thor_filters = Filters(min_year=year, player=str(player or "")[:40])
        await self.thor_lookup()

    async def load_thor_game(self, index: int) -> None:
        """Load a tournament game for review. If it passes through the position on the
        board, it is shown in the same orientation with the cursor on that position."""
        self._training_reset()
        if self.thor is None or self.thor_index is None:
            raise ValueError("the Thor database is not ready yet")
        index = int(index)
        if not 0 <= index < len(self.thor):
            raise ValueError("no such Thor game")
        game = self.thor.game(index)
        pos = self.current
        moves, ply = self.thor_index.game_aligned(index, pos.board, pos.player)
        self._set_moves(B.Position(), moves)  # raises ValueError on a corrupt game
        if ply is not None:
            self.cursor = ply
        self.opening = {
            "black": game.black, "white": game.white, "tournament": game.tournament,
            "year": game.year, "result": game.result, "plies": len(moves), "full": True, "index": index,
        }
        self.players = {B.BLACK: HUMAN, B.WHITE: HUMAN}  # review mode: nobody auto-plays
        self._reset_game_state()
        await self.touch()
        await self.thor_lookup()

    # ------------------------------------------------------------------ analysis

    async def analyze(self, level: int | None = None) -> None:
        """Evaluate every position of the game with `hint 1` and fill in the
        per-move evaluations and disc losses."""
        if self.analysis.running:
            return
        level = int(level or self.level)
        positions = self.positions()
        todo = [i for i, p in enumerate(positions) if not p.is_terminal() and not p.must_pass()]
        self.analysis = Analysis(running=True, done=0, total=len(todo), level=level)
        await self.broadcast(self.state())
        gen = self._gen
        try:
            async with self._engine_lock:
                await self.engine.set_level(level)
                for i in todo:
                    if self._gen != gen:
                        break  # game changed under us; stop quietly
                    best = await self._best_at(i)
                    if best is not None:
                        self.best_scores[i] = best
                    self.analysis.done += 1
                    self._apply_analysis()
                    await self.broadcast(self.state())
                await self.engine.set_level(self.level)
        except EdaxError as e:
            self.engine_error = str(e)
        finally:
            self.analysis.running = False
            self._apply_analysis()
            await self.broadcast(self.state())

    def _apply_analysis(self) -> None:
        """Derive eval/loss for each move from the best scores of positions."""
        positions = self.positions()
        for i, rec in enumerate(self.moves):
            if rec.sq == B.PASS:
                continue
            after = self._value_for(i + 1, rec.player, positions)
            if after is not None:
                rec.eval_black = (after if rec.player == B.BLACK else -after) + 0.0  # no -0.0
                rec.eval_source = "analysis"
            if i in self.best_scores and after is not None:
                best_move, best_score = self.best_scores[i]
                rec.best = best_move
                rec.loss = max(0.0, best_score - after)

    def _value_for(self, idx: int, perspective: str, positions: list[B.Position]) -> float | None:
        """Value of position `idx` for `perspective`, skipping forced passes."""
        while idx < len(positions) and positions[idx].must_pass():
            idx += 1
        if idx >= len(positions):
            return None
        pos = positions[idx]
        if pos.is_terminal():
            return float(pos.disc_diff(perspective))
        if idx not in self.best_scores:
            return None
        score = self.best_scores[idx][1]
        return score if pos.player == perspective else -score

    # ------------------------------------------------------------------ worker

    async def touch(self) -> None:
        """State changed: notify clients and (re)start the worker."""
        self._gen += 1
        await self._check_game_over()
        await self.broadcast(self.state())
        if self.hints_cursor is not None and self.hints_cursor != self.cursor:
            self._clear_hints()
            await self.broadcast(self.hints_message())
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._work())

    def _last_real_move(self) -> int:
        """Index of the last move that is not a forced pass, or -1."""
        i = len(self.moves) - 1
        while i >= 0 and self.moves[i].sq == B.PASS:
            i -= 1
        return i

    def _needs_review(self) -> bool:
        """Should the coach / puzzle evaluate the move the human just made?"""
        if not self.at_tip or self.analysis.running:
            return False
        i = self._last_real_move()
        if i < 0:
            return False
        rec = self.moves[i]
        if rec.reviewed or self.players[rec.player] != HUMAN:
            return False
        if self.puzzle and self.puzzle["status"] == "ask":
            return True
        return self.coach_enabled

    def _needs_engine_move(self) -> bool:
        pos = self.current
        return (
            self.at_tip
            and not pos.is_terminal()
            and self.players[pos.player] == EDAX
            and not self.analysis.running
            and self.coach_alert is None
            and not self._needs_review()
        )

    def _needs_hints(self) -> bool:
        pos = self.current
        return (
            self.hints_enabled
            and not pos.is_terminal()
            and not pos.must_pass()
            and self._hints_gen != self._gen
            and not self.analysis.running
            and not (self.puzzle and self.puzzle["status"] in ("solving", "ask") and self.at_tip)
            and not (self.trainer and self.trainer.hides_hints())
            and (self.players[pos.player] == HUMAN or not self.at_tip)
        )

    async def _work(self) -> None:
        try:
            while self.engine.running:
                gen = self._gen
                if self._needs_review():
                    await self._review_move(gen)
                elif self._needs_engine_move():
                    await self._engine_move(gen)
                elif self._needs_hints():
                    await self._engine_hints(gen)
                else:
                    return
        except EdaxError as e:
            log.error("engine error: %s", e)
            self.engine_error = str(e)
            self.thinking = False
            self.status = "engine error"
            await self.broadcast(self.state())
        except Exception:  # pragma: no cover - keep the server alive
            log.exception("worker failed")
            self.thinking = False

    async def _progress(self, nodes: int, seconds: float) -> None:
        self.nodes = nodes

    async def _engine_for_play(self) -> Edax:
        """The engine that plays Edax's moves: a second, time-limited Edax when a
        time per move is set, otherwise the main (level-based) engine."""
        if not self.move_time:
            return self.engine
        pe = self._play_engine
        if pe is None or not pe.running or pe.move_time != self.move_time:
            if pe is not None:
                await pe.quit()
            pe = self.engine_factory(
                self.engine.exe, self.engine.threads, self.engine.book_randomness, move_time=self.move_time
            )
            await pe.start()
            await pe.set_level(60)  # the clock, not the level, ends the search
            self._play_engine = pe
        return pe

    async def _review_move(self, gen: int) -> None:
        """Coach / puzzle: evaluate the human's last move by comparing the best score
        before it with the value of the position after it (both at the current level)."""
        i = self._last_real_move()
        rec = self.moves[i]
        positions = self.positions()
        j = i + 1
        while j < len(positions) and positions[j].must_pass():
            j += 1
        async with self._engine_lock:
            if self._gen != gen:
                return
            self.thinking = True
            self.status = "checking your move"
            await self.broadcast(self.state())
            if self.review_level:
                if self.engine.level != self.review_level:
                    await self.engine.set_level(self.review_level)
            else:
                await self._sync_level()
            if i not in self.best_scores and (best := await self._best_at(i)) is not None:
                self.best_scores[i] = best
            if (
                j < len(positions)
                and not positions[j].is_terminal()
                and j not in self.best_scores
                and (best := await self._best_at(j)) is not None
            ):
                self.best_scores[j] = best
        self.thinking = False
        self.status = "idle"
        if self._gen != gen:
            return
        rec.reviewed = True
        self._apply_analysis()
        best = self.best_scores.get(i)
        if best is not None:
            best_move, best_score = best
            loss = rec.loss if rec.loss is not None else 0.0
            played_score = best_score - loss
            if self.puzzle and self.puzzle["status"] == "ask":
                self.puzzle.update(
                    status="solved" if loss < 0.5 else "missed", played=B.sq_name(rec.sq), played_sq=rec.sq,
                    played_score=played_score, loss=loss,
                )
            elif self.coach_enabled and loss >= self.coach_threshold and best_move != rec.sq:
                before = positions[i]
                why = concepts.compare(before, rec.sq, best_move)
                pause = self.trainer.on_mistake(before, rec.sq, best_move, loss, why) if self.trainer else True
                if pause:
                    self.coach_alert = {
                        "cursor": len(self.moves), "move": B.sq_name(rec.sq), "move_sq": rec.sq,
                        "best": B.sq_name(best_move), "best_sq": best_move, "loss": loss,
                        "best_score": best_score, "played_score": played_score, "why": why,
                    }
        self._gen += 1
        await self.broadcast(self.state())

    async def _engine_move(self, gen: int) -> None:
        cursor = self.cursor
        async with self._engine_lock:
            if self._gen != gen:
                return
            varied = self.variety > 0 and not self.puzzle
            engine = self.engine if varied else await self._engine_for_play()
            self.thinking = True
            self.status = f"{engine.name} is thinking" + (f" ({engine.move_time:g} s)" if engine.move_time else "")
            await self.broadcast(self.state())
            if engine is self.engine:
                await self._sync_level()
            await engine.set_game(self._ggf_upto(cursor))
            if varied:
                move, score = await self._varied_move()
            else:
                result = await engine.go(self._progress)
                move, score = result.move, result.score
        self.thinking = False
        self.status = "idle"
        if self._gen != gen:
            return  # the user changed something while Edax was thinking
        pos = self.current
        if move not in pos.legal():
            raise EdaxError(f"Edax returned illegal move {B.sq_name(move)}")
        rec = self._append(move)
        rec.eval_black = (score if rec.player == B.BLACK else -score) + 0.0  # no -0.0
        rec.eval_source = "engine"
        self._gen += 1
        await self._check_game_over()
        await self.broadcast(self.state())

    async def _varied_move(self) -> tuple[int, float]:
        """Evaluate several moves and pick one at random among those within
        `variety` discs of the best. Gives Edax some unpredictability; the
        engine is otherwise fully deterministic at a fixed level."""
        n = min(len(self.current.legal()), 6)
        hints = await self.engine.hint(n, self._progress)
        if not hints:
            raise EdaxError("Edax returned no moves")
        best = max(h.score for h in hints)
        candidates = [h for h in hints if h.score >= best - self.variety]
        pick = random.choice(candidates)
        return pick.move, pick.score

    async def _engine_hints(self, gen: int) -> None:
        cursor = self.cursor
        n = self.hint_count
        async with self._engine_lock:
            if self._gen != gen:
                return
            self.thinking = True
            self.status = "computing hints"
            await self.broadcast(self.state())
            await self._sync_level()
            await self.engine.set_game(self._ggf_upto(cursor))
            hints = await self.engine.hint(n, self._progress)
        self.thinking = False
        self.status = "idle"
        if self._gen != gen:
            return
        self._hints_gen = gen
        self.hints = hints
        self.hints_cursor = cursor
        # remember the best score for the eval graph / analysis
        if hints:
            self.best_scores[cursor] = (hints[0].move, hints[0].score)
            self._apply_analysis()
        await self.broadcast(self.hints_message())
        await self.broadcast(self.state())

    # ------------------------------------------------------------------ helpers

    def _append(self, sq: int) -> MoveRecord:
        """Append a move at the tip, then any forced passes. Returns the move's record."""
        pos = self.current
        nxt = pos.play(sq)
        rec = MoveRecord(sq, pos.player, nxt, flips=B.flips(pos.board, sq, pos.player))
        self.moves.append(rec)
        while nxt.must_pass():
            after = nxt.play(B.PASS)
            self.moves.append(MoveRecord(B.PASS, nxt.player, after))
            nxt = after
        self.cursor = len(self.moves)
        return rec

    def _training_reset(self) -> None:
        """The user started something else: let the trainer drop its drill or scrimmage."""
        if self.trainer:
            self.trainer.on_external_game()

    async def _check_game_over(self) -> None:
        if self.trainer and self.moves and self.at_tip and self.current.is_terminal():
            await self.trainer.on_game_over()

    def _clear_hints(self) -> None:
        self.hints = []
        self.hints_cursor = None

    def _reset_game_state(self) -> None:
        """Forget everything derived from the previous game (evaluations, analysis,
        coach / puzzle state, hints). Call after replacing `start` / `moves`."""
        self.best_scores = {}
        self.analysis = Analysis()
        self.coach_alert = None
        self.puzzle = None
        self._clear_hints()

    def _ggf_upto(self, n: int) -> str:
        """The game as Edax's `set game` wants it, truncated to the first `n` moves."""
        return B.ggf(self.start, [m.sq for m in self.moves[:n]])

    async def _sync_level(self) -> None:
        """Make sure the main engine searches at the session's level."""
        if self.engine.level != self.level:
            await self.engine.set_level(self.level)

    async def _best_at(self, n: int) -> tuple[int, float] | None:
        """Edax's best move and score after the first `n` moves (None if it has no move).
        Must be called with `_engine_lock` held; the caller stores the result once it
        has checked that the game did not change meanwhile."""
        await self.engine.set_game(self._ggf_upto(n))
        hints = await self.engine.hint(1, self._progress)
        return (hints[0].move, hints[0].score) if hints else None


def _move_between(a: B.Position, b: B.Position) -> int:
    if a.board == b.board:
        return B.PASS
    for sq in range(64):
        if a.board[sq] == B.EMPTY and b.board[sq] != B.EMPTY:
            return sq
    raise ValueError("positions are not one move apart")


def _strip_ggf(text: str) -> str:
    """If `text` is a GGF record, keep only its move tags so that the board
    header (which also contains letters and digits) is not mistaken for moves."""
    if "(;" in text and "]" in text:
        return " ".join(re.findall(r"\b[BW]\[([^\]]+)\]", text))
    return text
