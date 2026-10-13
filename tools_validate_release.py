#!/usr/bin/env python3
"""Minimal reproducible checks before sharing a BLOOP source bundle."""
from __future__ import annotations
import compileall, json, subprocess, sys, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIRED = [
    "main.py", "gui.py", "smart_ghost.py", "popup_dismiss.py",
    "webhook_reporter.py", "repository_import.py", "sample_manager.py",
    "BLOOP.pyw", "config.json", "requirements.txt", "smart/model.npz",
    "tests/test_engine_hardening.py", "ENGINEERING_REVIEW.md", "TEST_REPORT.md",
    "README.md", "run_tests.bat", "setup_dev.bat", "tools_validate_release.py",
]
missing = [name for name in REQUIRED if not (ROOT / name).is_file()]
if missing:
    raise SystemExit("MISSING: " + ", ".join(missing))
sys.path.insert(0, str(ROOT))
import main
raw = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
known = set(main.Config.__dataclass_fields__)
if set(raw) != known:
    raise SystemExit(f"Config schema mismatch: missing={sorted(known-set(raw))}, unknown={sorted(set(raw)-known)}")
if raw.get("webhook_url"):
    raise SystemExit("Release config must not contain a webhook URL")
if raw.get("max_session_clicks", 0) <= 0:
    raise SystemExit("Release sample config should have a finite session click cap")
if not compileall.compile_dir(str(ROOT), quiet=1, rx=re.compile(r"(^|[/\\])(build|dist|.venv|.pytest_cache)([/\\]|$)")):
    raise SystemExit("Compile check failed")
help_result = subprocess.run([sys.executable, str(ROOT / "main.py"), "--help"], cwd=ROOT,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
if help_result.returncode != 0 or "--process" not in help_result.stdout:
    raise SystemExit("CLI smoke test failed")
print(f"PASS: {len(REQUIRED)} required artifacts")
print(f"PASS: config schema ({len(known)} fields), webhook blank, bounded click cap")
print("PASS: compileall and CLI --help")
