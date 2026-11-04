@echo off
rem Starts the GUI with this folder's Python environment, creating it the first time.
rem Double-click it, or run "run.bat" from a terminal in the gui folder.
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo Setting up the Python environment - this only happens once...
    py -m venv .venv || goto :error
    .venv\Scripts\python -m pip install -r requirements.txt || goto :error
)

.venv\Scripts\python main.py || goto :error
exit /b 0

:error
echo.
echo Something went wrong - see the messages above.
pause
exit /b 1
