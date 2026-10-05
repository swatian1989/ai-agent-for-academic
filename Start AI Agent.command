#!/bin/bash
# Double-click this file to open "AI Agent for Academic" in your web browser.
# Keep this window open while you work; close it (or press Ctrl+C) to stop the app.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "First-time setup: installing the app (this takes a few minutes, once only)..."
  bash setup_venv.sh || { echo "Setup failed - see the messages above."; read -n 1 -s -r -p "Press any key to close"; exit 1; }
fi
echo ""
echo "  AI Agent for Academic is starting - your browser will open in a moment."
echo "  If it does not, open:  http://localhost:8501"
echo "  Keep this window open while you work. Close it to stop the app."
echo ""
.venv/bin/python -m streamlit run app.py --server.headless false
