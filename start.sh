#!/bin/bash
# One command for everything: ./start.sh
# Gets the Vexo kit if it is missing, then opens the Wrist Agent control panel.
cd "$(dirname "$0")" || exit 1
command -v python3 >/dev/null || { echo "Python 3 is needed: https://www.python.org/downloads/"; exit 1; }
if [ ! -d vexo-open-kit ]; then
  echo "Getting the Vexo Open kit..."
  git clone -q https://github.com/VexoAI-Org/vexo-open-kit.git || exit 1
fi
exec python3 wrist-agent/server.py
