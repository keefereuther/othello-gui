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
- Undo, transcript paste/copy, Save/Open `.ggf` game files.
- Keyboard: ↓ / ↑ cycle through legal moves clockwise / counter-clockwise, ⏎ plays,
  ← → step through the game, Home / End, H toggles hints.
- Light and dark themes (header toggle; follows the OS by default).

## The Thor database (optional, recommended)

The Thor browser and Thor openings use the WTHOR game files published free of charge
by the Fédération Française d'Othello for personal use. They are not included here;
download them yourself:

1. Go to https://www.ffothello.org/informatique/la-base-wthor/
2. Download `WTHOR.JOU` (players), `WTHOR.TRN` (tournaments) and the yearly game files
   `WTH_1977.wtb` … `WTH_2025.wtb` (the yearly zip bundles contain the same files).
3. Put them all in a folder named `wthor` inside this app folder (next to `main.py`),
   or anywhere and set `WTHOR_DIR=/path/to/folder`.
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

## How it works

```
browser (othello_gui/static: index.html, app.js, tokens.css, style.css, motion.css)
   │  WebSocket /ws : JSON messages
   ▼
othello_gui/server.py      FastAPI app, one game session shared by connected pages
othello_gui/session.py     game state, review cursor, analysis, the worker that asks Edax
othello_gui/engine.py      asyncio driver for `edax -nboard` (NBoard text protocol)
othello_gui/board.py       Othello rules, notation, GGF (pure Python, tested)
othello_gui/wthor.py       WTHOR file reader
othello_gui/thor_index.py  position index over all games (numpy bitboards, 8 symmetries)
othello_gui/openings.py    named openings
```

The server owns all state and broadcasts a full `state` message after every change;
the page re-renders. The NBoard protocol has no "stop" command, so a running search
is never cancelled; stale results are discarded via a generation counter. Edax is a
separate process talking plain text over pipes.

Positions in the Thor index are normalised over the 8 board symmetries, so mirrored
games and transpositions are found; the index covers positions up to move 40. Results
come from black's final disc count. The browser only queries while its card is visible.

Tests: `uv run pytest` (rules incl. perft counts, WTHOR parsing, index symmetry, openings).

## Look and feel

The interface follows a "paper and tile" style system: warm paper surfaces, flat
cards with a solid bottom edge, a dark teal board, short springy motion that never
blocks input. All colours, sizes and timings are tokens in `static/tokens.css`; change
the palette there and nowhere else. Discs animate only for live moves; stepping
through history is instant. Hovering a legal square or a table row previews the flips.

## Customising

- Colours, sizes and fonts: `static/tokens.css`.
- Board look: `.board` / `.square` / `.disc` rules in `static/style.css`.
- New server-side actions: a branch in `handle()` in `server.py` plus a method on
  `GameSession`. Anything Edax can do in its text interface can be exposed by adding a
  method to `engine.py`.

## Licence and credits

This project is released under the GNU GPL v3 (see `LICENSE`).

- [Edax](https://github.com/abulmo/edax-reversi) by Richard Delorme and Toshihiko
  Okuhara, GPL-3.0, does all the thinking. The Apple Silicon build in `engine/` was
  made from the upstream source plus two small macOS fixes (`engine/README.md` has the
  exact commit, the patch and build steps, which together are the corresponding source).
- The layout and feature set follow [NBoard](https://github.com/weltyc/nboard) by
  Chris Welty (GPL-3.0). No NBoard code is used. The opening names table
  (`othello_gui/data/openings.txt`) is from his othello library, GPL-3.0.
- The WTHOR game database is published by the Fédération Française d'Othello for
  personal use; download it from https://www.ffothello.org rather than redistributing it.
- Python dependencies: FastAPI (MIT), Uvicorn and Starlette (BSD-3-Clause),
  NumPy (BSD-3-Clause), py7zr (LGPL-2.1).
- Rubik typeface by the Rubik Project Authors, SIL Open Font License 1.1
  (`static/fonts/OFL.txt`).
