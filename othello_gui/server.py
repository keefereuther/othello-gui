"""FastAPI server: serves the static front end and a WebSocket for the game.

Configuration is read from environment variables:

    EDAX_BIN       path to the Edax executable (default: engine/<platform>/ from setup_edax.py,
                   or ../edax-reversi/bin/mEdax)
    EDAX_THREADS   search threads (default: CPU count - 1)
    EDAX_LEVEL     initial search level (default: 8)
    EDAX_BOOK_RANDOMNESS  let Edax pick slightly worse book moves (default: 0)
    WTHOR_DIR      folder with the WTHOR files (default: wthor/ here, or ../wthor)

Every client message is a JSON object with a ``type`` and is dispatched through
``HANDLERS`` to a GameSession method; see CLAUDE.md for the full protocol.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from . import curriculum
from .engine import Edax, EdaxError
from .paths import find_edax, find_wthor, progress_file, wthor_available
from .session import GameSession
from .thor_index import ThorIndex
from .training import Trainer
from .wthor import ThorDatabase

log = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / "static"


def _env_int(name: str) -> int | None:
    value = os.environ.get(name)
    return int(value) if value else None


class Hub:
    """Connected WebSocket clients plus the single shared game session."""

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.engine = Edax(find_edax(), _env_int("EDAX_THREADS"), _env_int("EDAX_BOOK_RANDOMNESS") or 0)
        thor = None
        wthor_dir = find_wthor()
        if wthor_available(wthor_dir):
            thor = ThorDatabase(wthor_dir)
            log.info("Thor database: %d games from %s", len(thor), wthor_dir)
        else:
            log.warning("Thor database not found at %s: Thor openings and browser are off. "
                        "See README for how to add it.", wthor_dir)
        self.session = GameSession(self.engine, self.broadcast, thor)
        self.session.level = _env_int("EDAX_LEVEL") or 8
        self.session.trainer = Trainer(self.session, progress_file())
        self._thor_task: asyncio.Task | None = None

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def start(self) -> None:
        if self.session.thor is not None:
            self._thor_task = asyncio.create_task(self._load_thor_index())
        try:
            await self.engine.start()
            await self.engine.set_level(self.session.level)
            await self.session.touch()  # compute opening hints before the first client arrives
        except EdaxError as e:
            log.error("cannot start Edax: %s", e)
            self.session.engine_error = f"{e}. Run:  uv run scripts/setup_edax.py"
        except Exception as e:  # pragma: no cover
            log.exception("cannot start Edax")
            self.session.engine_error = repr(e)

    async def _load_thor_index(self) -> None:
        """Load the cached position index, or build it (a few seconds) in a thread,
        reporting progress to the clients while it runs."""
        session = self.session
        loop = asyncio.get_running_loop()
        done = asyncio.Event()

        def progress(fraction: float) -> None:
            session.thor_progress = fraction

        async def report() -> None:
            while not done.is_set():
                await self.broadcast(session.thor_message())
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(done.wait(), 0.5)

        reporter = asyncio.create_task(report())
        try:
            session.thor_index = await loop.run_in_executor(None, ThorIndex.load_or_build, session.thor, progress)
            log.info("Thor index ready: %d positions", len(session.thor_index))
        except Exception as e:  # pragma: no cover - keep the app usable without it
            log.exception("could not build the Thor index")
            session.thor_error = str(e)
        finally:
            done.set()
            await reporter
        await session.thor_lookup()

    async def stop(self) -> None:
        await self.session.close()
        await self.engine.quit()


hub = Hub()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await hub.start()
    try:
        yield
    finally:
        await hub.stop()


app = FastAPI(title="Othello GUI", lifespan=lifespan)


@app.get("/api/curriculum")
async def get_curriculum() -> list[dict[str, Any]]:
    return curriculum.public()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    hub.clients.add(ws)
    session = hub.session
    try:
        await ws.send_json(session.state())
        await ws.send_json(session.hints_message())
        await ws.send_json(session.thor_message())
        while True:
            msg = await ws.receive_json()
            try:
                await handle(session, msg)
            except (ValueError, EdaxError) as e:
                await ws.send_json({"type": "error", "message": str(e)})
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(ws)


# ---------------------------------------------------------------- client messages

Handler = Callable[[GameSession, dict[str, Any]], Awaitable[None]]


async def _in_background(coro: Awaitable[None]) -> None:
    """Run a long job (game analysis) without blocking the WebSocket loop."""
    asyncio.create_task(coro)


def _players(m: dict[str, Any]) -> tuple[str, str]:
    return m.get("black", "human"), m.get("white", "edax")


def _trainer(s: GameSession) -> Trainer:
    if s.trainer is None:
        raise ValueError("training is not available")
    return s.trainer


HANDLERS: dict[str, Handler] = {
    # game
    "new_game": lambda s, m: s.new_game(*_players(m), m.get("level"), m.get("opening")),
    "move": lambda s, m: s.user_move(int(m["sq"])),
    "undo": lambda s, m: s.undo(),
    "goto": lambda s, m: s.goto(int(m["index"])),
    "load_transcript": lambda s, m: s.load_transcript(str(m.get("text", ""))),
    "refresh": lambda s, m: s.touch(),
    # settings
    "set_players": lambda s, m: s.set_players(*_players(m)),
    "set_level": lambda s, m: s.set_level(int(m["level"])),
    "set_variety": lambda s, m: s.set_variety(int(m["discs"])),
    "set_move_time": lambda s, m: s.set_move_time(m.get("seconds")),
    "set_hints": lambda s, m: s.set_hints(bool(m.get("enabled", True)), m.get("count")),
    # coach, puzzles, analysis
    "set_coach": lambda s, m: s.set_coach(bool(m.get("enabled")), m.get("threshold")),
    "coach_continue": lambda s, m: s.coach_continue(),
    "puzzle": lambda s, m: s.start_puzzle(int(m.get("empties", 12))),
    "analyze": lambda s, m: _in_background(s.analyze(m.get("level"))),
    # Thor database
    "thor_lookup": lambda s, m: s.thor_lookup(),
    "thor_filters": lambda s, m: s.set_thor_filters(m.get("min_year"), m.get("player", "")),
    "thor_game": lambda s, m: s.load_thor_game(int(m["index"])),
    # training
    "train_open": lambda s, m: _trainer(s).open_unit(str(m["unit"])),
    "train_close": lambda s, m: _trainer(s).close(),
    "train_lesson_done": lambda s, m: _trainer(s).lesson_done(),
    "train_example": lambda s, m: _trainer(s).show_example(),
    "train_drill": lambda s, m: _trainer(s).next_drill(),
    "train_answer": lambda s, m: _trainer(s).answer(int(m["choice"])),
    "train_scrimmage": lambda s, m: _trainer(s).start_scrimmage(),
}


async def handle(session: GameSession, msg: dict[str, Any]) -> None:
    kind = msg.get("type")
    handler = HANDLERS.get(kind)
    if handler is None:
        raise ValueError(f"unknown message type {kind!r}")
    await handler(session, msg)


# Static files last so that /ws is matched first.
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
