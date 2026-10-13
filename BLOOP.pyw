#!/usr/bin/env python3
"""Double-click GUI launcher for BLOOP; errors are surfaced by gui.py in a dialog/log."""
from pathlib import Path
import runpy
import os
os.chdir(Path(__file__).resolve().parent)
runpy.run_path(str(Path(__file__).resolve().parent / "gui.py"), run_name="__main__")
