@echo off
rem Double-click to start the Othello GUI (Windows).
rem First run: installs uv if needed, fetches the Edax engine, then opens the app.
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
  echo Installing uv ^(https://astral.sh/uv^) ...
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)
uv run scripts\setup_edax.py --if-missing || (echo Engine setup failed. & pause & exit /b 1)
echo Starting the Othello GUI. Close this window to stop it.
uv run main.py
pause
