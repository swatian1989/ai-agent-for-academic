#!/usr/bin/env bash
# Creates the virtual environment and installs all dependencies (macOS / Linux).
#   $ bash setup_venv.sh
set -e
cd "$(dirname "$0")"
PY=python3
command -v python3 >/dev/null 2>&1 || { echo "Python 3 is not installed: https://www.python.org/downloads/"; exit 1; }
$PY -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
[ -f .env ] || { cp .env.example .env; chmod 600 .env; echo "Created .env - add your ANTHROPIC_API_KEY (or use Settings in the app)"; }
echo "Done. Start the app with:  .venv/bin/python -m streamlit run app.py"
