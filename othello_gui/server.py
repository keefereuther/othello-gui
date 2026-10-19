"""FastAPI server: serves the static front end and a WebSocket for the game.

Configuration is read from environment variables:

    EDAX_BIN       path to the Edax executable (default: engine/<platform>/ from setup_edax.py,
                   or ../edax-reversi/bin/mEdax)
    EDAX_THREADS   search threads (default: CPU count - 1)
    EDAX_LEVEL     initial search level (default: 8)
    EDAX_BOOK_RANDOMNESS  let Edax pick slightly worse book moves (default: 0)
    WTHOR_DIR      folder with the WTHOR files (default: wthor/ here, or ../wthor)
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .engine import Edax, EdaxError
from .session import GameSession
from .thor_index import ThorIndex
from .wthor import ThorDatabase

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
APP = ROOT.parent  # the repository folder


def _env_int(name: str) -> int | None:
    value = os.environ.get(name)
    return int(value) if value else None


def _platform_tag() -> str:
    import platform
    import sys

    system = {"darwin": "darwin", "linux": "linux", "win32": "windows"}.get(sys.platform, sys.platform)
    machine = platform.machine().lower()
    machine = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64", "amd64": "x86_64"}.get(machine, machine)
    return f"{system}-{machine}"


def find_edax() -> Path:
    """EDAX_BIN, else engine/<platform>/ (set up by scripts/setup_edax.py), else a
    developer checkout of Edax next to this repository."""
    if os.environ.get("EDAX_BIN"):
        return Path(os.environ["EDAX_BIN"]).expanduser()
    tag = _platform_tag()
    name = "edax.exe" if tag.startswith("windows") else "mEdax" if tag.startswith("darwin") else "edax"
    candidates = [APP / "engine" / tag / name, APP.parent / "edax-reversi" / "bin" / "mEdax"]
    for c in candidates:
        if c.exists() and (c.parent / "data" / "eval.dat").exists():
            return c
    return candidates[0]


def find_wthor() -> Path:
    """WTHOR_DIR, else wthor/ inside this repository, else next to it."""
    if os.environ.get("WTHOR_DIR"):
        return Path(os.environ["WTHOR_DIR"]).expanduser()
    for c in (APP / "wthor", APP.parent / "wthor"):
        if (c / "WTHOR.JOU").exists():
            return c
    return APP / "wthor"


class Hub:
    """Connected WebSocket clients plus the single shared game session."""

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.engine = Edax(find_edax(), _env_int("EDAX_THREADS"), _env_int("EDAX_BOOK_RANDOMNESS") or 0)
        thor = None
        wthor_dir = find_wthor()
        if (wthor_dir / "WTHOR.JOU").exists():
            thor = ThorDatabase(wthor_dir)
            log.info("Thor database: %d games from %s", len(thor), wthor_dir)
        else:
            log.warning("Thor database not found at %s: Thor openings and browser are off. "
                        "See README for how to add it.", wthor_dir)
        self.session = GameSession(self.engine, self.broadcast, thor)
        self.session.level = _env_int("EDAX_LEVEL") or 8

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
                try:
                    await asyncio.wait_for(done.wait(), 0.5)
                except asyncio.TimeoutError:
                    pass

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


async def handle(session: GameSession, msg: dict[str, Any]) -> None:
    kind = msg.get("type")
    if kind == "new_game":
        await session.new_game(msg.get("black", "human"), msg.get("white", "edax"), msg.get("level"), msg.get("opening"))
    elif kind == "move":
        await session.user_move(int(msg["sq"]))
    elif kind == "undo":
        await session.undo()
    elif kind == "goto":
        await session.goto(int(msg["index"]))
    elif kind == "set_level":
        await session.set_level(int(msg["level"]))
    elif kind == "set_variety":
        await session.set_variety(int(msg["discs"]))
    elif kind == "set_move_time":
        await session.set_move_time(msg.get("seconds"))
    elif kind == "set_coach":
        await session.set_coach(bool(msg.get("enabled")), msg.get("threshold"))
    elif kind == "coach_continue":
        await session.coach_continue()
    elif kind == "puzzle":
        await session.start_puzzle(int(msg.get("empties", 12)))
    elif kind == "set_players":
        await session.set_players(msg.get("black", "human"), msg.get("white", "edax"))
    elif kind == "set_hints":
        await session.set_hints(bool(msg.get("enabled", True)), msg.get("count"))
    elif kind == "load_transcript":
        await session.load_transcript(str(msg.get("text", "")))
    elif kind == "analyze":
        asyncio.create_task(session.analyze(msg.get("level")))
    elif kind == "thor_lookup":
        await session.thor_lookup()
    elif kind == "thor_filters":
        await session.set_thor_filters(msg.get("min_year"), msg.get("player", ""))
    elif kind == "thor_game":
        await session.load_thor_game(int(msg["index"]))
    elif kind == "refresh":
        await session.touch()
    else:
        raise ValueError(f"unknown message type {kind!r}")


# Static files last so that /ws is matched first.
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
