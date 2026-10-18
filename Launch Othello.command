#!/bin/bash
# Double-click to start the Othello GUI (macOS / Linux).
# First run: installs uv (Python tool runner) if needed, fetches the Edax engine, then opens the app.
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv (https://astral.sh/uv) …"
  curl -LsSf https://astral.sh/uv/install.sh | sh || { echo "Could not install uv."; read -r -p "Press Enter to close."; exit 1; }
  export PATH="$HOME/.local/bin:$PATH"
fi
uv run scripts/setup_edax.py --if-missing || { echo; read -r -p "Engine setup failed (see above). Press Enter to close."; exit 1; }
echo "Starting the Othello GUI. Close this window to stop it."
uv run main.py
