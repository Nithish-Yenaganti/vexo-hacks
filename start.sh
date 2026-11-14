#!/bin/bash
# One command for everything:
#   ./start.sh                 run Wrist Agent (menu-bar dot + floating pill); Ctrl+C quits
#   ./start.sh --background    same, detached; logs in ~/Library/Logs/WristAgent.log
#   ./start.sh --setup-only    only get the kit and the libraries
# The first run gets the Vexo kit and the libraries it needs.
cd "$(dirname "$0")" || exit 1
command -v python3 >/dev/null || { echo "Python 3 is needed: https://www.python.org/downloads/"; exit 1; }
if [ ! -d vexo-open-kit ]; then
  echo "Getting the Vexo Open kit..."
  git clone -q https://github.com/VexoAI-Org/vexo-open-kit.git || exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "Making the project's Python environment (.venv)..."
  python3 -m venv .venv || exit 1
fi
if ! .venv/bin/python -c "import bleak, serial, pyautogui, AppKit, ApplicationServices, sounddevice, websockets" 2>/dev/null; then
  echo "Installing libraries (bleak: Bluetooth, pyserial: USB, pyautogui: computer control, pyobjc: menu bar)..."
  .venv/bin/python -m pip install -q --disable-pip-version-check bleak pyserial pyautogui pyobjc-framework-Cocoa pyobjc-framework-ApplicationServices sounddevice websockets || exit 1
fi
case "$1" in
  --setup-only) exit 0 ;;
  --background)
    mkdir -p "$HOME/Library/Logs"
    nohup .venv/bin/python wrist-agent/app.py >> "$HOME/Library/Logs/WristAgent.log" 2>&1 &
    echo $! > "$HOME/.wrist-agent.pid"
    echo "Wrist Agent started: look for the dot in the menu bar." ;;
  *) exec .venv/bin/python wrist-agent/app.py ;;
esac
