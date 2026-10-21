"""The training module: lessons, drills and themed scrimmages over the curriculum.

A `Trainer` is attached to the `GameSession` (``session.trainer``). It borrows
the session's board for drills and scrimmages and hooks into a few places:

    before_user_move()        refuse board moves while a question is open
    after_user_move(pos, sq)  grade a "find the move" drill
    hides_hints()             no hints while a drill is unanswered
    on_mistake(...)           coach filter during scrimmages (only the unit's concepts pause)
    on_game_over()            score a finished scrimmage
    on_external_game()        the user started something else: drop the activity

Progress is a small JSON file (``progress.json`` in the app folder, git-ignored).
A unit is passed when the last WINDOW drills average at least PASS_RATE and one
scrimmage was finished with no coach pause for the unit's kind of mistake.
"""

from __future__ import annotations

import json
import logging
import random
import struct
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import board as B
from . import concepts as C
from .curriculum import PART1, UNIT_BY_ID, UNITS, watch_tags

if TYPE_CHECKING:
    from .session import GameSession

log = logging.getLogger(__name__)

WINDOW = 10  # drills that count towards mastery
PASS_RATE = 0.8
REVIEW_LEVEL = 10  # level the coach uses to judge scrimmage moves

HUMAN, EDAX = "human", "edax"

JUDGE_BUCKETS = [  # (label, low, high) score for the side to move
    ("Clearly winning (+8 or more)", 8, 99),
    ("Better (+3 to +7)", 3, 7),
    ("About even (−2 to +2)", -2, 2),
    ("Worse (−3 to −7)", -7, -3),
    ("Clearly losing (−8 or less)", -99, -8),
]
SQUARE_CLASSES = ["corner", "X", "C", "A", "B", "interior"]
SQUARE_LABELS = {"corner": "Corner", "X": "X-square", "C": "C-square", "A": "A-square", "B": "B-square",
                 "interior": "Interior"}


# --------------------------------------------------------------------------- position filters

def _reports(pos: B.Position) -> list[C.MoveReport]:
    return [C.analyse_move(pos, m) for m in pos.legal()]


FILTERS = {
    # a corner is available, or some move would give one away
    "corner_choice": lambda p: any(r.takes_corner or r.gives_corner is not None for r in _reports(p)),
    # the candidate moves differ a lot in loudness
    "frontier_spread": lambda p: (lambda nf: max(nf) - min(nf) >= 3)([r.new_frontier for r in _reports(p)]),
    # a non-corner edge move is on offer
    "edge_choice": lambda p: any(m in C.EDGES and m not in C.CORNERS for m in p.legal()),
    # several regions, at least one odd
    "odd_region": lambda p: (lambda rs: len(rs) >= 2 and any(len(r) % 2 for r in rs))(C.regions(p.board)),
    # some move threatens a corner
    "corner_attack": lambda p: any(C.attacks_corner(p, m) for m in p.legal()),
    # a corner or C-square move is on offer
    "c_or_corner": lambda p: any(m in C.CORNERS or m in C.C_SQUARES for m in p.legal()),
}


def judge_bucket(score: float) -> int:
    r = round(score)
    for i, (_, lo, hi) in enumerate(JUDGE_BUCKETS):
        if lo <= r <= hi:
            return i
    return 2


def fmt(v: float) -> str:
    r = round(v)
    return f"+{r}" if r > 0 else f"−{abs(r)}" if r < 0 else "0"


# --------------------------------------------------------------------------- progress

class Progress:
    """Per-unit results, persisted as JSON. `path=None` keeps everything in memory."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.data: dict[str, Any] = {"version": 1, "units": {}}
        if path and path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
                self.data.setdefault("units", {})
            except (OSError, ValueError) as e:
                log.warning("ignoring unreadable progress file %s: %s", path, e)

    def unit(self, uid: str) -> dict[str, Any]:
        u = self.data["units"].setdefault(uid, {})
        u.setdefault("lesson", False)
        u.setdefault("drills", [])
        u.setdefault("scrimmages", [])
        u.setdefault("level_adjust", 0)
        return u

    def save(self) -> None:
        if not self.path:
            return
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as e:
            log.warning("could not save progress to %s: %s", self.path, e)

    def drill_rate(self, uid: str) -> tuple[int, float]:
        recent = self.unit(uid)["drills"][-WINDOW:]
        return len(recent), (sum(d["credit"] for d in recent) / len(recent) if recent else 0.0)

    def drills_passed(self, uid: str) -> bool:
        n, rate = self.drill_rate(uid)
        return n >= WINDOW and rate >= PASS_RATE

    def scrimmage_passed(self, uid: str) -> bool:
        return any(s.get("passed") for s in self.unit(uid)["scrimmages"])

    def passed(self, uid: str) -> bool:
        return self.drills_passed(uid) and self.scrimmage_passed(uid)

    def unlocked(self, uid: str) -> bool:
        unit = UNIT_BY_ID[uid]
        if unit["part"] == 1:
            i = PART1.index(uid)
            return all(self.passed(p) for p in PART1[:i])
        return all(self.passed(p) for p in PART1)

    def record_drill(self, uid: str, kind: str, credit: float) -> None:
        drills = self.unit(uid)["drills"]
        drills.append({"kind": kind, "credit": credit, "t": int(time.time())})
        del drills[:-50]
        self.save()


# --------------------------------------------------------------------------- the trainer

class Trainer:
    def __init__(self, session: GameSession, progress_path: Path | None = None, unlock_all: bool = False) -> None:
        self.s = session
        self.progress = Progress(progress_path)
        self.unlock_all = unlock_all
        self.unit_id: str | None = None
        self.mode: str | None = None  # None | "lesson" | "example" | "drill" | "scrimmage"
        self.drill: dict[str, Any] | None = None
        self.example: dict[str, Any] | None = None
        self.scrim: dict[str, Any] | None = None
        self.review: dict[str, Any] | None = None
        self.marks: dict[int, str] = {}
        self.rng = random.Random()
        self._own = False  # True while the trainer itself changes the session's game
        self._saved: dict[str, Any] | None = None  # the user's settings, restored on leaving
        self._player_games: dict[str, list[int]] = {}

    # ------------------------------------------------------------------ queries

    @property
    def unit(self) -> dict[str, Any]:
        if self.unit_id is None:
            raise ValueError("open a training unit first")
        return UNIT_BY_ID[self.unit_id]

    def is_unlocked(self, uid: str) -> bool:
        return self.unlock_all or self.progress.unlocked(uid)

    def scrim_level(self, uid: str) -> int:
        spec = UNIT_BY_ID[uid]["scrimmage"]
        return max(1, min(20, spec["level"] + self.progress.unit(uid)["level_adjust"]))

    def to_json(self) -> dict[str, Any]:
        units = {}
        for u in UNITS:
            uid = u["id"]
            n, rate = self.progress.drill_rate(uid)
            units[uid] = {
                "lesson": self.progress.unit(uid)["lesson"], "drills": n, "rate": round(rate, 3),
                "drills_passed": self.progress.drills_passed(uid),
                "scrimmages": len(self.progress.unit(uid)["scrimmages"]),
                "scrimmage_passed": self.progress.scrimmage_passed(uid),
                "passed": self.progress.passed(uid), "unlocked": self.is_unlocked(uid),
                "level": self.scrim_level(uid),
            }
        public = lambda d: {k: v for k, v in d.items() if not k.startswith("_")} if d else None  # noqa: E731
        return {
            "unit": self.unit_id, "mode": self.mode, "window": WINDOW, "pass_rate": PASS_RATE,
            "drill": public(self.drill), "example": public(self.example), "scrimmage": public(self.scrim),
            "review": self.review, "marks": [[sq, kind] for sq, kind in self.marks.items()], "units": units,
        }

    # ------------------------------------------------------------------ session hooks

    def before_user_move(self) -> None:
        d = self.drill
        if self.mode != "drill" or not d:
            return
        if d["status"] == "preparing":
            raise ValueError("one moment, the drill is being prepared")
        if d["status"] == "ask" and d["kind"] != "move":
            raise ValueError("answer the question in the Training card")

    def after_user_move(self, pos_before: B.Position, sq: int) -> None:
        d = self.drill
        if self.mode != "drill" or not d or d["kind"] != "move" or d["status"] != "ask":
            return
        if pos_before.board != d["_board"] or pos_before.player != d["_player"]:
            return
        self._grade_move(pos_before, sq)

    def hides_hints(self) -> bool:
        return self.mode == "drill" and bool(self.drill) and self.drill["status"] in ("preparing", "ask")

    def on_mistake(self, pos_before: B.Position, played: int, best: int, loss: float, why: str) -> bool:
        """The coach found a costly human move. Returns whether the game should pause."""
        if self.mode != "scrimmage" or not self.scrim or self.scrim["status"] != "playing":
            return True
        tags = C.analyse_move(pos_before, played).tags
        related = bool(set(tags) & set(watch_tags(self.unit_id or "")))
        self.scrim["mistakes"].append({
            "ply": len(self.s.moves), "move": B.sq_name(played), "best": B.sq_name(best), "loss": loss,
            "tags": tags, "why": why, "related": related,
        })
        if related:
            self.scrim["flagged"] += 1
        return related

    async def on_game_over(self) -> None:
        sc = self.scrim
        if self.mode != "scrimmage" or not sc or sc["status"] != "playing" or self._own:
            return
        uid = self.unit_id
        assert uid is not None
        pos = self.s.current
        diff = pos.disc_diff(sc["color"])
        passed = sc["flagged"] == 0
        prog = self.progress.unit(uid)
        prog["scrimmages"].append({"t": int(time.time()), "color": sc["color"], "level": sc["level"],
                                   "diff": diff, "flagged": sc["flagged"], "passed": passed})
        del prog["scrimmages"][:-30]
        if diff > 0:
            prog["level_adjust"] = min(prog["level_adjust"] + 1, 6)
        elif diff <= -10:
            prog["level_adjust"] = max(prog["level_adjust"] - 1, -4)
        self.progress.save()
        sc["status"] = "done"
        mistakes = sorted(sc["mistakes"], key=lambda m: -m["loss"])
        result = "won" if diff > 0 else "lost" if diff < 0 else "drew"
        verdict = ("Passed: no coach pauses for this unit's kind of mistake."
                   if passed else f"Not passed yet: {sc['flagged']} pause(s) for this unit's kind of mistake.")
        self.review = {"result": result, "diff": diff, "passed": passed, "verdict": verdict, "mistakes": mistakes,
                       "next_level": self.scrim_level(uid)}

    def on_external_game(self) -> None:
        if self._own or self.mode in (None, "lesson"):
            return
        if self.scrim and self.scrim["status"] == "playing":
            self.scrim["status"] = "abandoned"
        self.drill = self.example = None
        self.marks = {}
        self.mode = "lesson"
        self._restore_settings()

    # ------------------------------------------------------------------ navigation

    async def open_unit(self, uid: str) -> None:
        if uid not in UNIT_BY_ID:
            raise ValueError(f"no training unit {uid!r}")
        if not self.is_unlocked(uid):
            raise ValueError("finish the earlier units first")
        self._leave_activity()
        self.unit_id = uid
        self.mode = "lesson"
        await self.s.touch()

    async def close(self) -> None:
        self._leave_activity()
        self.unit_id = None
        self.mode = None
        await self.s.touch()

    async def lesson_done(self) -> None:
        self.progress.unit(self.unit["id"])["lesson"] = True
        self.progress.save()
        await self.s.touch()

    def _leave_activity(self) -> None:
        self.drill = self.example = self.scrim = self.review = None
        self.marks = {}
        self._restore_settings()

    # ------------------------------------------------------------------ settings

    def _save_settings(self) -> None:
        if self._saved is None:
            s = self.s
            self._saved = {"level": s.level, "variety": s.variety, "move_time": s.move_time,
                           "coach": (s.coach_enabled, s.coach_threshold), "hints": s.hints_enabled}

    def _restore_settings(self) -> None:
        s = self.s
        s.review_level = None
        if self._saved is None:
            return
        sv, self._saved = self._saved, None
        s.level, s.variety, s.move_time = sv["level"], sv["variety"], sv["move_time"]
        s.coach_enabled, s.coach_threshold = sv["coach"]
        s.hints_enabled = sv["hints"]

    async def _show(self, pos: B.Position) -> None:
        """Put `pos` on the board for study: both sides human, no coach."""
        s = self.s
        self._save_settings()
        s.coach_enabled = False
        s.review_level = None
        s.hints_enabled = self._saved["hints"] if self._saved else True
        self._own = True
        try:
            s.start, s.moves, s.cursor, s.opening = pos, [], 0, None
            s.players = {B.BLACK: HUMAN, B.WHITE: HUMAN}
            s._reset_game_state()
        finally:
            self._own = False

    # ------------------------------------------------------------------ positions

    def _games_by(self, player: str) -> list[int]:
        if player not in self._player_games:
            thor = self.s.thor
            ids = {i for i, name in enumerate(thor.players) if player in name.lower()} if thor else set()
            out = []
            if thor:
                for gi, (_, rec) in enumerate(thor.records):
                    _, black, white = struct.unpack_from("<HHH", rec)
                    if black in ids or white in ids:
                        out.append(gi)
            self._player_games[player] = out
        return self._player_games[player]

    def _sample(self, spec: dict[str, Any]) -> tuple[B.Position, dict[str, Any]]:
        from .session import _move_between

        thor = self.s.thor
        if thor is None or not len(thor):
            raise ValueError("drills need the Thor database (see the Thor card)")
        lo, hi = spec.get("empties", (10, 50))
        check = FILTERS.get(spec.get("filter") or "")
        player = spec.get("player")
        pool = self._games_by(player) if player else None
        if not pool:
            pool, player = None, None  # player not in this database: fall back to all games
        for _ in range(400):
            gi = self.rng.choice(pool) if pool else self.rng.randrange(len(thor))
            game = thor.game(gi)
            try:
                positions = B.replay(B.Position(), list(game.moves))
            except ValueError:
                continue
            cands = [
                k for k, p in enumerate(positions[:-1])
                if lo <= p.board.count(B.EMPTY) <= hi and not p.must_pass() and len(p.legal()) >= 2
                and (player is None or player in self._master_name(game, p.player).lower())
                and (check is None or check(p))
            ]
            if cands:
                k = self.rng.choice(cands)
                info = {"game": game, "played": _move_between(positions[k], positions[k + 1])}
                return positions[k], info
        raise ValueError("could not find a suitable position for this unit")

    async def _scores(self, pos: B.Position, n: int, level: int) -> list[Any]:
        """Edax's evaluation of the `n` best moves at `pos`, best first."""
        s = self.s
        async with s._engine_lock:
            s.thinking, s.status = True, "preparing the drill"
            await s.broadcast(s.state())
            try:
                if s.engine.level != level:
                    await s.engine.set_level(level)
                await s.engine.set_game(B.ggf(pos, []))
                hints = await s.engine.hint(n, s._progress)
            finally:
                s.thinking, s.status = False, "idle"
        return sorted(hints, key=lambda h: -h.score)

    # ------------------------------------------------------------------ drills

    async def next_drill(self, kind: str | None = None) -> None:
        unit = self.unit
        spec = unit["drill"]
        kinds = spec["kinds"]
        kind = kind or self.rng.choices(list(kinds), weights=list(kinds.values()))[0]
        if kind not in kinds:
            raise ValueError(f"this unit has no {kind} drills")
        self.example = None
        self.review = None
        self.marks = {}
        self.mode = "drill"
        if kind == "squares":
            await self._squares_drill()
            return
        level = spec.get("level", 10)
        drill: dict[str, Any] = {"kind": kind, "status": "preparing", "prompt": "Edax is analysing the position…"}
        self.drill = drill
        for attempt in range(3):
            pos, info = self._sample(spec)
            await self._show(pos)
            drill.update(_board=pos.board, _player=pos.player)
            await self.s.touch()
            n = len(pos.legal()) if kind == "move" else 1
            hints = await self._scores(pos, n, level)
            if self.drill is not drill:
                return  # the user moved on meanwhile
            if not hints:
                continue
            if kind == "move" and attempt < 2 and len(hints) >= 2 and hints[0].score - hints[1].score < 2:
                continue  # no clear answer: find a more instructive position
            break
        else:
            if not hints:
                self.drill = None
                raise ValueError("Edax could not analyse a drill position")
        side = "Black" if pos.player == B.BLACK else "White"
        drill.update(_scores={h.move: h.score for h in hints}, _best=hints[0].move, _game=info,
                     side=side, empties=pos.board.count(B.EMPTY), status="ask")
        if kind == "move":
            drill["prompt"] = f"{side} to move. Click the best move on the board."
            if spec.get("player"):
                drill["prompt"] = f"{side} to move, from a game by {self._master_name(info['game'], pos.player)}. " \
                                  "What would you play?"
        else:
            drill["prompt"] = f"{side} to move. How good is this position for {side.lower()}?"
            drill["choices"] = [label for label, _, _ in JUDGE_BUCKETS]
            drill["_answer"] = judge_bucket(hints[0].score)
        self.s._gen += 1
        await self.s.broadcast(self.s.state())

    @staticmethod
    def _master_name(game: Any, player: str) -> str:
        return game.black if player == B.BLACK else game.white

    async def _squares_drill(self) -> None:
        pool = [sq for sq in range(64) if C.square_class(sq) != "interior"] * 3 + list(range(64))
        sq = self.rng.choice(pool)
        await self._show(B.Position())
        self.marks = {sq: "focus"}
        if self.rng.random() < 0.5:
            cls = C.square_class(sq)
            choices = [SQUARE_LABELS[c] for c in SQUARE_CLASSES]
            self.drill = {"kind": "squares", "status": "ask", "prompt": "What kind of square is the ringed one?",
                          "choices": choices, "_answer": SQUARE_CLASSES.index(cls), "_sq": sq}
        else:
            names = {B.sq_name(sq)}
            while len(names) < 4:
                names.add(B.sq_name(self.rng.randrange(64)))
            choices = sorted(n.upper() for n in names)
            self.drill = {"kind": "squares", "status": "ask", "prompt": "What is the name of the ringed square?",
                          "choices": choices, "_answer": choices.index(B.sq_name(sq).upper()), "_sq": sq}
        await self.s.touch()

    async def answer(self, choice: int) -> None:
        d = self.drill
        if self.mode != "drill" or not d or d["status"] != "ask" or "choices" not in d:
            raise ValueError("there is no question to answer")
        if not 0 <= choice < len(d["choices"]):
            raise ValueError("no such answer")
        right = d["_answer"]
        if d["kind"] == "squares":
            credit = 1.0 if choice == right else 0.0
            sq = d["_sq"]
            d["feedback"] = (f"{B.sq_name(sq).upper()} is a {SQUARE_LABELS[C.square_class(sq)]}."
                             + ("" if credit else f" You answered {d['choices'][choice]}."))
        else:
            credit = 1.0 if choice == right else 0.5 if abs(choice - right) == 1 else 0.0
            d["feedback"] = self._judge_explanation()
        d.update(status="answered", chosen=choice, correct=right, credit=credit)
        self.progress.record_drill(self.unit["id"], d["kind"], credit)
        await self.s.touch()

    def _judge_explanation(self) -> str:
        d = self.drill
        assert d is not None
        pos = B.Position(d["_board"], d["_player"])
        me, opp = pos.player, B.opponent(pos.player)
        score = d["_scores"][d["_best"]]
        side, other = ("Black", "White") if me == B.BLACK else ("White", "Black")
        mob = (len(B.legal_moves(pos.board, me)), len(B.legal_moves(pos.board, opp)))
        fr = (len(C.frontier_discs(pos.board, me)), len(C.frontier_discs(pos.board, opp)))
        discs = (pos.board.count(me), pos.board.count(opp))
        corners = (sum(pos.board[c] == me for c in C.CORNERS), sum(pos.board[c] == opp for c in C.CORNERS))
        text = (f"Edax: {fmt(score)} for {side.lower()}. Moves {side} {mob[0]} / {other} {mob[1]}; "
                f"frontier discs {fr[0]} / {fr[1]}; discs {discs[0]} / {discs[1]}; "
                f"corners {corners[0]} / {corners[1]}.")
        if (score > 2 and discs[0] < discs[1]) or (score < -2 and discs[0] > discs[1]):
            text += " The side with fewer discs is better: mobility and frontier matter more than material."
        elif score > 2 and mob[0] > mob[1]:
            text += f" {side} has more moves, the usual sign of the better position."
        elif score < -2 and mob[0] < mob[1]:
            text += f" {side} has fewer moves, the usual sign of trouble."
        return text

    def _grade_move(self, pos: B.Position, sq: int) -> None:
        d = self.drill
        assert d is not None
        scores, best = d["_scores"], d["_best"]
        worst = min(scores.values())
        score = scores.get(sq, worst - 2)  # Edax ranks every legal move; a missing one is at least this bad
        loss = max(0.0, scores[best] - score)
        credit = 1.0 if loss <= 1 else 0.5 if loss <= 3 else 0.0
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:6]
        text = "Best move!" if loss <= 1 else f"{B.sq_name(sq).upper()} costs {round(loss)} discs."
        text += " " + C.compare(pos, sq, best)
        info = d.get("_game") or {}
        if self.unit.get("drill", {}).get("player") and info.get("played") is not None:
            master = info["played"]
            who = self._master_name(info["game"], pos.player)
            text += f" {who} played {B.sq_name(master).upper()}"
            text += f" ({fmt(scores[master])} by Edax)." if master in scores else "."
        d.update(status="answered", played=B.sq_name(sq), loss=loss, credit=credit, feedback=text,
                 best=B.sq_name(best), ranking=[[B.sq_name(m), round(v)] for m, v in ranked])
        self.marks = {best: "good"}
        if sq != best:
            self.marks[sq] = "bad"
        self.progress.record_drill(self.unit["id"], "move", credit)

    # ------------------------------------------------------------------ worked example

    async def show_example(self) -> None:
        """A position from the unit with Edax's best move and an instructive worse one."""
        unit = self.unit
        spec = unit["drill"]
        if "squares" in spec["kinds"]:
            raise ValueError("this unit's drills explain themselves; start the drills")
        self.drill = None
        self.review = None
        self.mode = "example"
        self.example = {"status": "preparing", "text": "Edax is analysing an example…"}
        ex = self.example
        pos, _ = self._sample(spec)
        await self._show(pos)
        await self.s.touch()
        hints = await self._scores(pos, len(pos.legal()), spec.get("level", 10))
        if self.example is not ex or not hints:
            return
        best = hints[0].move
        watch = set(watch_tags(unit["id"]))
        worse = [h for h in hints[1:] if set(C.analyse_move(pos, h.move).tags) & watch] or hints[1:]
        side = "Black" if pos.player == B.BLACK else "White"
        if worse:
            bad = max(worse, key=lambda h: hints[0].score - h.score)
            text = (f"{side} to move. Best is {B.sq_name(best).upper()} ({fmt(hints[0].score)}); "
                    f"{B.sq_name(bad.move).upper()} would be {fmt(bad.score)}. "
                    + C.compare(pos, bad.move, best, intro="Suppose you played"))
            self.marks = {best: "good", bad.move: "bad"}
        else:
            text = f"{side} to move. Best is {B.sq_name(best).upper()}. " + C.describe(C.analyse_move(pos, best))
            self.marks = {best: "good"}
        ex.update(status="ready", text=text)
        self.s._gen += 1
        await self.s.broadcast(self.s.state())

    # ------------------------------------------------------------------ scrimmage

    async def start_scrimmage(self) -> None:
        unit = self.unit
        uid = unit["id"]
        spec = unit["scrimmage"]
        s = self.s
        n = len(self.progress.unit(uid)["scrimmages"])
        human = B.BLACK if n % 2 == 0 else B.WHITE
        level = self.scrim_level(uid)
        self.drill = self.example = self.review = None
        self.marks = {}
        self.mode = "scrimmage"
        self._save_settings()
        s.variety, s.move_time = spec["variety"], None
        s.coach_enabled, s.coach_threshold = True, spec["threshold"]
        s.hints_enabled = False
        s.review_level = REVIEW_LEVEL
        self.scrim = {"color": human, "level": level, "variety": spec["variety"], "threshold": spec["threshold"],
                      "status": "playing", "flagged": 0, "mistakes": [], "about": spec["about"]}
        opening = None
        if spec.get("opening_plies") and s.thor:
            opening = {"type": "thor", "plies": spec["opening_plies"]}
        players = {B.BLACK: HUMAN if human == B.BLACK else EDAX, B.WHITE: HUMAN if human == B.WHITE else EDAX}
        self._own = True
        try:
            await s.new_game(players[B.BLACK], players[B.WHITE], level, opening)
        finally:
            self._own = False
