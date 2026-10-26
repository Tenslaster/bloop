@echo off
setlocal EnableExtensions
cd /d "%~dp0"
where py >NUL 2>NUL
if errorlevel 1 (
  echo [BLOOP] Python Launcher not found. Install Python 3.11 or 3.12 with the launcher enabled.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" py -3.11 -m venv .venv
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail
echo [BLOOP] Development environment ready. Run run_tests.bat, then launch_gui.bat.
pause
exit /b 0
:fail
echo [BLOOP] Setup failed. Ensure Python 3.11 is installed, then retry.
pause
exit /b 1
