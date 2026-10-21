# Othello GUI

Play and study Othello in your browser with the [Edax](https://github.com/abulmo/edax-reversi)
engine, one of the strongest Othello programs in existence. Hints with evaluations on the
board, game analysis, an evaluation graph, named openings, and a browser for the
Thor database of 137,000 tournament games. Runs on your own computer; nothing is
sent anywhere.

## Quick start

You need [uv](https://docs.astral.sh/uv/), a small tool that installs Python and the
app's dependencies for you.

**macOS / Linux**

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh        # once, if you don't have uv
git clone https://github.com/keefereuther/othello-gui.git
cd othello-gui
uv run scripts/setup_edax.py                            # fetches the engine for your computer
uv run main.py                                          # opens http://127.0.0.1:8765/
```

Or just double-click **Launch Othello.command** in the folder: it does all of the
above the first time, then starts the app. Close its window to stop the app.

**Windows**

Double-click **launch.bat**, or run the same commands in PowerShell with
`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
to install uv. Windows is supported by the code but has not been tested yet; please
report problems.

**What the engine setup does.** Apple Silicon Macs use the ready-made Edax build
shipped in `engine/darwin-arm64/` (see `engine/README.md`). Linux and Windows get the
official Edax 4.7 release; Intel Macs compile Edax from source (install the Xcode
command line tools first: `xcode-select --install`). All platforms download the
14 MB evaluation weights from the Edax repository. The first start also creates a
minimal opening book; see below for a real one.

## Features

- Play against Edax as black or white at any level, watch Edax vs Edax, or play
  human vs human. Levels 1–5 are casual, 6–9 strong club, 10–14 master, 15+ superhuman.
- Hints: the best N moves with evaluations drawn on the board, best move highlighted,
  book moves marked. Toggle with **H**.
- Move list with evaluations; click any move to review that position. The header
  names the opening (Tiger, Rose, Cat, … 86 named lines, recognised in any orientation).
- Evaluation graph, and **Analyze game** to re-evaluate every position and mark
  the discs each mistake cost.
- Thor database browser: for the position on the board, how many tournament games
  reached it, how they ended, what was played next (click to play it), and the latest
  games (click to load one). Filters by year and player.
- Random openings from real tournament games; **Variety** so Edax doesn't always
  play the same move.
- **Edax thinks by** a fixed level or a time per move (1–30 s). Hints and analysis
  always use the level; timed play runs on a second Edax process.
- **Coach**: after each of your moves Edax checks it; if it cost at least the chosen
  number of discs, the game pauses with the loss and the better move. Take back or play on.
- **Endgame puzzles**: a real tournament game cut at 8–20 empties, solved exactly by
  Edax. Find the best move; you're told the exact value, and can play the ending out
  against perfect defence, undo to retry, or take the next puzzle.
- Undo, transcript paste/copy, Save/Open `.ggf` game files.
- Keyboard: ↓ / ↑ cycle through legal moves clockwise / counter-clockwise, ⏎ plays,
  ← → step through the game, Home / End, H toggles hints.
- Light and dark themes (header toggle; follows the OS by default).
- Every sidebar panel folds away: click its title. The app remembers which ones you closed.
- **Training**: a 14-unit course from beginner to advanced (see below).

## Training

The Training panel is a course built on Brian Rose's *Othello: A Minute to Learn…
A Lifetime to Master*. Part I (rules, corners, frontier discs, openings, edges, basic
endgame, defense) unlocks one unit at a time; Part II (parity, corner-attack tesuji,
swindles, opening books, midgame shape, endgame counting, master games) opens once
Part I is done and can be taken in any order.

Each unit has three steps:

1. **Lesson**: a short summary of the chapter, key ideas, and questions to ask yourself.
   *Show an example* puts a real tournament position on the board with Edax's best move
   and an instructive worse one marked and explained.
2. **Drills**, graded by Edax: *find the move* (positions chosen to exercise the unit's
   idea), *judge the position* (who is better, and by how much, explained through
   mobility, frontier discs and corners), and square-naming for unit 1. Unit 14 uses
   positions from Hideshi Tamenori's games and shows what he played. Pass: 80% over
   the last 10 drills.
3. **Scrimmage**: a full game against Edax at a level that rises when you win. The
   coach pauses only for the unit's kind of mistake and explains it; the review lists
   every costly move. Pass: finish a game without a pause.

Drills need the Thor database. Progress is saved in `progress.json` in the app folder
(set `OTHELLO_PROGRESS` to keep it elsewhere). The book itself is not included.

## The Thor database (optional, recommended)

The Thor browser and Thor openings use the WTHOR game files published free of charge
by the Fédération Française d'Othello for personal use. They are not included here;
download them yourself:

1. Go to https://www.ffothello.org/informatique/la-base-wthor/
2. Download `WTHOR.JOU` (players), `WTHOR.TRN` (tournaments) and the yearly game files
   `WTH_1977.wtb` … `WTH_2025.wtb` (the yearly zip bundles contain the same files).
3. Put them all in a folder named `wthor` inside this app folder (next to `main.py`)
   or next to it, or anywhere and set `WTHOR_DIR=/path/to/folder`.
4. Restart the app. The first start builds a position index (a few seconds, cached as
   `wthor/thor-index.npz`, about 70 MB).

## A real opening book (optional)

Edax plays openings instantly and with variety when it has an opening book. The
setup downloads a 12 MB book built from the 2010–2025 Thor games at level 10 (or
falls back to a minimal one). To build your own, which takes about 45 minutes per
year of games at level 10:

```sh
uv run scripts/build_book.py --years 2024-2025 --level 10        # a good start
uv run scripts/build_book.py --years 2010-2023 --level 10 --merge # add more later
```

Restart the app afterwards. Hints then show "book" moves with the number of games
that reached the position. Keep the laptop plugged in; the build pauses if the
battery dies and resumes when power returns.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `EDAX_BIN` | `engine/<platform>/…` | Edax executable; its folder must contain `data/eval.dat` |
| `EDAX_THREADS` | CPU count − 1 | Search threads |
| `EDAX_LEVEL` | `8` | Initial search level |
| `EDAX_BOOK_RANDOMNESS` | `0` | Let Edax play slightly worse book moves (Variety in the GUI does the same) |
| `WTHOR_DIR` | `wthor/` | Folder with the WTHOR files |
| `PORT` | `8765` | HTTP port |
| `NO_BROWSER` | unset | `1` to not open the browser |
| `LOG_LEVEL` | `INFO` | `DEBUG` logs every line exchanged with Edax |
| `OTHELLO_PROGRESS` | `progress.json` | Where training progress is saved |

## How it works

```
browser (othello_gui/static: index.html, app.js, tokens.css, style.css, motion.css)
   │  WebSocket /ws : JSON messages
   ▼
othello_gui/server.py      FastAPI app, one game session shared by connected pages,
                           HANDLERS table mapping message types to session methods
othello_gui/session.py     game state, review cursor, analysis, the worker that asks Edax
othello_gui/engine.py      asyncio driver for `edax -nboard` (NBoard text protocol)
othello_gui/board.py       Othello rules, notation, GGF (pure Python, tested)
othello_gui/paths.py       where the engine and the WTHOR files are looked for
othello_gui/wthor.py       WTHOR file reader
othello_gui/thor_index.py  position index over all games (numpy bitboards, 8 symmetries)
othello_gui/openings.py    named openings
othello_gui/concepts.py    explains a move in the book's terms (frontier, X/C-squares, parity …)
othello_gui/curriculum.py  the 14 training units: lessons, drill and scrimmage specs
othello_gui/training.py    progress, drills graded by Edax, themed scrimmages
```

The server owns all state and broadcasts a full `state` message after every change;
the page re-renders. The NBoard protocol has no "stop" command, so a running search
is never cancelled; stale results are discarded via a generation counter. Edax is a
separate process talking plain text over pipes.

Positions in the Thor index are normalised over the 8 board symmetries, so mirrored
games and transpositions are found; the index covers positions up to move 40. Results
come from black's final disc count. The browser only queries while its card is visible.

Coach and puzzle checks compare the best score before your move with the value of the
position after it, both at the current level (the puzzle level is at least half the
number of empties, which makes Edax's answer exact). A time per move uses a second
Edax process started with `-move-time`, because under a time limit Edax returns only
one hint, so hints and analysis stay on the level-based engine.

## Look and feel

The interface follows a "paper and tile" style system: warm paper surfaces, flat
cards with a solid bottom edge, a dark teal board, short springy motion that never
blocks input. All colours, sizes and timings are tokens in `static/tokens.css`; change
the palette there and nowhere else. Discs animate only for live moves; stepping
through history is instant. Hovering a legal square or a table row previews the flips.

## Customising

- Colours, sizes and fonts: `static/tokens.css`.
- Board look: `.board` / `.square` / `.disc` rules in `static/style.css`.
- New server-side actions: a method on `GameSession` plus one line in `HANDLERS` in
  `server.py`. Anything Edax can do in its text interface can be exposed by adding a
  method to `engine.py`.

## Development

```sh
uv sync                 # Python, dependencies and the dev tools (pytest, ruff)
uv run pytest -q        # about 3 s; no Edax needed, a scripted fake engine stands in
uv run ruff check .     # lint; CI (.github/workflows/ci.yml) runs both on every push
uv run -m othello_gui   # the same as `uv run main.py`
```

The tests cover the rules (including perft counts), WTHOR parsing, index symmetry,
openings, and the coach / puzzle / timed-play flows. Tests that need the real WTHOR
files skip when they are absent.

`CLAUDE.md` is the developer map: module layout, the WebSocket protocol, how state
flows, a checklist for adding a feature, and the gotchas. It is written for coding
agents but is the right starting point for people too.

## Licence and credits

This project is released under the GNU GPL v3 (see `LICENSE`).

- [Edax](https://github.com/abulmo/edax-reversi) by Richard Delorme and Toshihiko
  Okuhara, GPL-3.0, does all the thinking. The Apple Silicon build in `engine/` was
  made from the upstream source plus two small macOS fixes (`engine/README.md` has the
  exact commit, the patch and build steps, which together are the corresponding source).
- The layout and feature set follow [NBoard](https://github.com/weltyc/nboard) by
  Chris Welty (GPL-3.0). No NBoard code is used. The opening names table
  (`othello_gui/data/openings.txt`) is from his othello library, GPL-3.0.
- The Training lessons summarise ideas from Brian Rose, *Othello: A Minute to Learn… A Lifetime
  to Master* (2005), in our own words, with page references. No text or diagrams from the book
  are included; read the book itself for the full explanations and exercises.
- The WTHOR game database is published by the Fédération Française d'Othello for
  personal use; download it from https://www.ffothello.org rather than redistributing it.
- Python dependencies: FastAPI (MIT), Uvicorn and Starlette (BSD-3-Clause),
  NumPy (BSD-3-Clause), py7zr (LGPL-2.1).
- Rubik typeface by the Rubik Project Authors, SIL Open Font License 1.1
  (`static/fonts/OFL.txt`).
