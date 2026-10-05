# Creates the virtual environment and installs all dependencies (Windows PowerShell).
#   PS> .\setup_venv.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env - add your ANTHROPIC_API_KEY (or use Settings in the app)" }
Write-Host "Done. Start the app with:  .\.venv\Scripts\python.exe -m streamlit run app.py"
