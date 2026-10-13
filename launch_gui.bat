@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist "logs" mkdir "logs"

rem Prefer a project virtual environment so the GUI and its child bot use the same packages.
set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist "venv\Scripts\python.exe" set "PYTHON_EXE=%CD%\venv\Scripts\python.exe"

rem Ask the Python launcher for the exact interpreter rather than launching an
rem arbitrary pythonw.exe from PATH (which may belong to a different install).
if not defined PYTHON_EXE (
  for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_EXE=%%P"
)
if not defined PYTHON_EXE (
  for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_EXE=%%P"
)
if not defined PYTHON_EXE (
  echo [BLOOP] Python 3 was not found. Install Python 3.10+ and enable the Python launcher.
  echo See README.md for setup instructions.
  pause
  exit /b 1
)

echo [BLOOP] Using interpreter: "%PYTHON_EXE%"
echo [BLOOP] Checking Tkinter, NumPy and OpenCV...
"%PYTHON_EXE%" -c "import tkinter, numpy, cv2; print('Python GUI dependencies OK')"
if errorlevel 1 (
  echo.
  echo [BLOOP] Startup preflight failed. Install dependencies with:
  echo   "%PYTHON_EXE%" -m pip install -r requirements.txt
  echo The traceback above is intentional; this launcher does not hide startup errors.
  pause
  exit /b 1
)

echo [BLOOP] Launching GUI. Keep this window open to see startup/runtime errors.
"%PYTHON_EXE%" -u gui.py
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo [BLOOP] GUI exited with code %EXIT_CODE%. Check logs\gui_startup.log and logs\.
  pause
  exit /b %EXIT_CODE%
)
exit /b 0
