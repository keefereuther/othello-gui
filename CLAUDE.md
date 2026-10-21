# Othello GUI: developer map

A browser front end for the Edax Othello engine. Python 3.12+ / FastAPI server
that owns one shared game session, a vanilla HTML/JS client, no build step.
README.md has the user-facing picture; this file is the map for making changes.

## Commands

```sh
uv run main.py              # start at http://127.0.0.1:8765 (NO_BROWSER=1: no tab; LOG_LEVEL=DEBUG: every Edax line)
uv run pytest -q            # ~3 s, no Edax needed; real-WTHOR tests skip when the files are absent
uv run ruff check .         # lint (CI runs both on every push)
uv run scripts/setup_edax.py     # fetch the engine for this platform into engine/<platform>/
uv run scripts/build_book.py     # build an opening book from WTHOR games (macOS/Linux only, uses a pty)
```

## Layout

| Path | Role |
| --- | --- |
| `othello_gui/board.py` | Rules and notation. Pure Python, no deps. Board = 64-char string, a1 = 0, `X` black, `O` white, `-` empty; `PASS = -1`. Edax writes black as `*` (`to_edax` / `from_edax`). |
| `othello_gui/engine.py` | `Edax`: one engine process speaking the NBoard text protocol over pipes. Commands are serialised by a lock. |
| `othello_gui/session.py` | `GameSession`: the game, the review cursor, players, hints, analysis, coach, puzzles, Thor filters, and the worker that asks Edax for things. |
| `othello_gui/server.py` | FastAPI app. `Hub` holds the clients and the session; `HANDLERS` maps message types to session methods. |
| `othello_gui/paths.py` | Where the engine and the WTHOR files are looked for. Stdlib only; scripts import it too. |
| `othello_gui/wthor.py` | WTHOR file reader (`ThorDatabase`). |
| `othello_gui/thor_index.py` | Position index over all games: numpy bitboards, 8 symmetries, cached as `thor-index.npz` next to the files. |
| `othello_gui/openings.py` | Named openings from `data/openings.txt`, matched under symmetry. |
| `othello_gui/concepts.py` | Describes a move in the book's vocabulary (square classes, frontier, quiet/loud, corner gifts and attacks, parity regions); `UNIT_CONCEPTS` maps units to the tags their coach watches. Pure Python. |
| `othello_gui/curriculum.py` | The 14 training units (Rose's book): lesson text, drill spec, scrimmage spec. Data only. |
| `othello_gui/training.py` | `Trainer`: progress file, unlocking, drill sampling and grading, worked examples, themed scrimmages. |
| `othello_gui/static/` | The client: `index.html`, `app.js` (everything but training), `training.js` (the Training card), `tokens.css` (all design tokens), `style.css`, `motion.css`. |
| `scripts/` | `setup_edax.py` (engine fetch/build per platform), `build_book.py`. Both add the repo root to `sys.path`. |
| `tests/` | pytest + pytest-asyncio (`asyncio_mode = auto`). `conftest.py` has the `make_wthor` fixture (synthetic databases); `fakes.py` has `FakeEdax`, `make_session`, `settle` (import with `from fakes import …`). |
| `engine/` | Git-ignored except `README.md`, the macOS patch and the committed Apple Silicon build. |

## How state flows

- The server owns all state. Any change goes through a `GameSession` method that
  mutates fields and ends with `await self.touch()`. `touch()` bumps `_gen`,
  broadcasts a full `state` message, and starts the worker if it is not running.
- The worker (`_work`) loops: review the human's last move (coach / puzzle) →
  engine move → hints → exit. Each step records `gen = self._gen`, talks to Edax
  under `_engine_lock`, and throws the result away if `_gen` changed meanwhile.
  The NBoard protocol has no stop command, so a running search is never cancelled.
- Hints carry the `cursor` they were computed for; the client shows them only
  when it matches `state.cursor`.
- The client re-renders everything from each `state` message. The board DOM is
  diffed, not rebuilt, so a live move at the tip animates (`liveMove()` in app.js).
- Timed play (`move_time`) uses a second Edax process started with `-move-time`,
  because under a time limit `hint` returns one move only. Hints and analysis stay
  on the level-based engine.
- Scores from Edax are disc differences for the side to move. `MoveRecord.eval_black`
  flips them to black's view; the eval graph and move list use that.

## Training

- `session.trainer` is a `Trainer` (set by the server; `None` in most tests). The
  session calls a few hooks: `before_user_move` / `after_user_move` (grade a move
  drill), `hides_hints`, `on_mistake` (decides whether the coach pauses: only for
  the unit's concept tags during a scrimmage), `on_game_over`, and
  `on_external_game` (the user started a game, puzzle, transcript or Thor game:
  drop the drill). The trainer sets `_own` while it changes the game itself.
- Drills borrow the board: `_show(pos)` puts a Thor position up with both sides
  human. Edax grades with `hint n` for all legal moves at the unit's drill level,
  under `_engine_lock`. `judge` drills use `hint 1`; `squares` drills need no engine.
- The trainer saves the user's level, variety, move time, coach and hints when an
  activity starts and restores them on leaving. Scrimmages set
  `session.review_level` so the coach judges moves at level 10 whatever Edax plays at.
- Progress lives in `progress.json` (git-ignored; `OTHELLO_PROGRESS` overrides).
  Passing a unit: last `WINDOW` drills average ≥ `PASS_RATE`, plus one finished
  scrimmage with no coach pause. Part I unlocks in order; Part II after Part I.
- Adding a unit: an entry in `curriculum.UNITS`, its tags in
  `concepts.UNIT_CONCEPTS`, and a filter in `training.FILTERS` if drills need one.

## WebSocket protocol (`/ws`, JSON objects)

Client → server (`HANDLERS` in server.py; invalid input raises `ValueError`, sent back as `error`):

| type | fields | effect |
| --- | --- | --- |
| `new_game` | `black`, `white` (`human`/`edax`), `level?`, `opening?` `{type:"thor", plies, min_year?}` | start a game |
| `move` | `sq` 0–63 | play at the cursor; truncates the future when reviewing |
| `undo` | | take back until a human is to move |
| `goto` | `index` | move the review cursor |
| `load_transcript` | `text` (`F5d6C3…` or a GGF record) | load for review, both players human |
| `set_players` | `black`, `white` | |
| `set_level` | `level` 1–60 | also re-hints |
| `set_variety` | `discs` 0–16 | Edax picks randomly within this of the best |
| `set_move_time` | `seconds` or null | |
| `set_hints` | `enabled`, `count?` | |
| `set_coach` | `enabled`, `threshold?` | |
| `coach_continue` | | accept the flagged move |
| `puzzle` | `empties` 6–20 | endgame puzzle from a Thor game |
| `analyze` | `level?` | runs as a background task |
| `thor_lookup` | | resend Thor statistics for the current position |
| `thor_filters` | `min_year?`, `player?` | |
| `thor_game` | `index` | load a tournament game for review |
| `refresh` | | resend state |
| `train_open` | `unit` | open an unlocked unit (lesson view) |
| `train_close` | | back to the unit list; restores the user's settings |
| `train_lesson_done` | | mark the lesson read |
| `train_example` | | worked example: a unit position with the best move and an instructive worse one marked |
| `train_drill` | | next drill (kind drawn from the unit's weights) |
| `train_answer` | `choice` | answer a multiple-choice drill (`move` drills are answered with `move`) |
| `train_scrimmage` | | themed game against Edax at the unit's calibrated level |

`GET /api/curriculum` returns the static unit list and lesson text; `state.training`
carries everything that changes (progress per unit, drill, example, scrimmage, review, board marks).

Server → client:

| type | content |
| --- | --- |
| `state` | full snapshot, see `GameSession.state()`: board, legal moves, moves (with evals, losses, flips, opening names), cursor, players, settings, coach/puzzle state (the coach alert carries a `why` explanation), engine status, `training` |
| `hints` | `{cursor, hints: [{sq, name, score, depth, pv, book, book_games}]}` |
| `thor` | `{available, ready, progress?, error?, filters, games, black_wins, draws, white_wins, continuations, sample}` |
| `error` | `{message}` |

## Adding a feature

1. `session.py`: add a method on `GameSession` that validates input, mutates
   state, and ends with `await self.touch()`. Put new fields in `state()` if the
   client needs them. If Edax is involved, follow the `_engine_hints` pattern
   (capture `gen`, lock, check `gen`, store, broadcast).
2. `server.py`: one line in `HANDLERS`.
3. `app.js`: render from `state` in a `render*()` function called from `render()`;
   wire controls near the other `$("…").onclick` lines; send `{type: …}`.
4. `index.html` / `style.css` for markup and components. Colours, sizes and
   timings only in `tokens.css`.
5. Tests: drive the flow with `FakeEdax` from `tests/fakes.py` (answers from a
   board → (move, score) table; `hint n` ranks the other legal moves 3 discs apart)
   and `settle()`. See `test_modes.py` and `test_training.py`.

## Gotchas

- Edax needs `data/book.dat` next to `data/eval.dat`; without one it builds a
  book at level 24 on start, which looks like a hang. `Edax._ensure_book` and
  `setup_edax.py` both create a minimal one.
- `set game` errors arrive on Edax's stderr, asynchronously; `Edax.set_game`
  waits briefly and raises `EdaxError` if a new `Error` line appeared.
- Edax's in-session commands stop at the first space, so `build_book.py` hands
  it space-free symlinks inside the engine folder.
- WTHOR files are free for personal use but not redistributable: never commit
  them. The index cache and its signature live next to them.
- The Thor index stores continuation moves in canonical (symmetry-normalised)
  coordinates; `SQMAP` / `INVERSE` map them back to the board on screen.
- Only `engine/darwin-arm64/mEdax` is committed, with its GPL notes in
  `engine/README.md`; keep that file accurate if the build changes.
- Windows is supported by the code but untested; `build_book.py` is Unix only.

## Conventions

- Ruff (`pyproject.toml`): line length 120, rules E/F/W/I/UP/B/SIM. Keep it clean.
- Messages are plain dicts; coerce with `int()` / `bool()` at the boundary and
  raise `ValueError` with a message the user can read.
- Rules logic goes in `board.py` with a test; nothing there may import numpy.
- JS: no framework, `$()` for elements, `esc()` for any user-sourced text put
  into `innerHTML`, state read from the last `state` message only.
