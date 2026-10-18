"""Start the Othello GUI server and open it in the default browser.

    uv run main.py            # http://127.0.0.1:8765
    PORT=9000 uv run main.py  # another port
    EDAX_BIN=/path/to/mEdax uv run main.py
"""

import logging
import os
import threading
import webbrowser

import uvicorn


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(levelname)s %(name)s: %(message)s")
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8765"))
    url = f"http://{host}:{port}/"
    if os.environ.get("NO_BROWSER") != "1":
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    print(f"Othello GUI running at {url}  (Ctrl-C to stop)")
    uvicorn.run("othello_gui.server:app", host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
