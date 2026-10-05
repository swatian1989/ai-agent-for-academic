@echo off
REM Double-click to open "AI Agent for Academic" in your browser (Windows). Close this window to stop.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First-time setup: installing the app, once only...
  powershell -ExecutionPolicy Bypass -File setup_venv.ps1
)
.venv\Scripts\python.exe -m streamlit run app.py
