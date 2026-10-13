#!/usr/bin/env python3
"""
Highrise Vision Bot — multi-instance sprite matching with persistent evidence.
Bootstraps from ./seeds/ and enables response-gated exploration by default; --patient disables exploratory clicks.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import sys
import threading
import time
from collections import OrderedDict, defaultdict, deque
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

try:
    from smart_ghost import SmartGhost
except ImportError:  # click-learning is optional; the seed-based bot still works without it
    SmartGhost = None

try:
    from ghost_classifier import GhostScene
except ImportError:
    GhostScene = None
try:
    from ghost_overlay import GhostOverlay, OVERLAY_HWNDS
except ImportError:
    GhostOverlay, OVERLAY_HWNDS = None, set()
try:
    from overlay_teacher import OverlayTeacher
except ImportError:      # teaching from the overlay is optional
    OverlayTeacher = None

# ADD THIS:
try:
    from webhook_reporter import WebhookReporter
except ImportError:
    WebhookReporter = None

try:
    from repository_import import (
        DEFAULT_REPOSITORY,
        sync_and_import_repository,
        build_target_templates,
    )
except ImportError:  # allows the vision helpers to remain importable for minimal tests
    DEFAULT_REPOSITORY = "Tenslaster/bloop"
    sync_and_import_repository = None
    build_target_templates = None

# Keep the vision core importable on Linux/macOS for testing. Windows-only input
# and capture dependencies are checked at launch rather than crashing on import.
try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    keyboard = None
    HAS_KEYBOARD = False

try:
    import mss
    HAS_MSS = True
except ImportError:
    mss = None
    HAS_MSS = False

try:
    import pydirectinput
    HAS_DIRECT_INPUT = True
except ImportError:
    pydirectinput = None
    HAS_DIRECT_INPUT = False

try:
    import win32gui, win32con, win32ui
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

try:
    from pynput import mouse as pmouse
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False


# ============================================================
# Infra
# ============================================================
log = logging.getLogger("bot")


def enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def setup_logging(log_dir: str = "logs", debug: bool = False, level: Optional[str] = None,
                  console_level: Optional[str] = None, file_level: Optional[str] = None,
                  file_enabled: bool = True, console_enabled: bool = True,
                  file_max_mb: int = 12) -> None:
    """Configure separate console/file verbosity; DEBUG can be kept in file only."""
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, f"bot_{time.strftime('%Y%m%d_%H%M%S')}.log")
    logger = logging.getLogger("bot")
    override = level.upper() if level else None
    default_level = "DEBUG" if debug else "INFO"
    c_level = (override or console_level or default_level).upper()
    f_level = (override or file_level or ("DEBUG" if not debug else default_level)).upper()
    allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if c_level not in allowed: c_level = "INFO"
    if f_level not in allowed: f_level = "DEBUG"
    active_levels = [getattr(logging, x) for x, enabled in ((c_level, console_enabled), (f_level, file_enabled)) if enabled]
    logger.setLevel(min(active_levels) if active_levels else logging.CRITICAL + 1)
    for old_handler in list(logger.handlers):
        try:
            old_handler.flush()
            old_handler.close()
        except Exception:
            pass
        logger.removeHandler(old_handler)

    formatter_file = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    formatter_console = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    if file_enabled:
        max_bytes = max(1, min(int(file_max_mb), 200)) * 1024 * 1024
        fh = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=2, encoding="utf-8")
        fh.setLevel(getattr(logging, f_level))
        fh.setFormatter(formatter_file)
        logger.addHandler(fh)
    if console_enabled:
        ch = logging.StreamHandler()
        ch.setLevel(getattr(logging, c_level))
        ch.setFormatter(formatter_console)
        logger.addHandler(ch)


# ============================================================
# Config
# ============================================================
@dataclass
class Config:
    window_title: str = ""
    # Target the game by executable name. This is the primary way the bot finds
    # Highrise: it can never match the BLOOP GUI, a browser tab or a folder that
    # merely has "Highrise" in its title. window_title is only used when this is empty.
    window_process: str = "highrise.exe"
    # Bring Highrise back (restore from minimized / raise above other windows)
    # automatically instead of waiting for the user to do it.
    auto_focus_game: bool = True
    focus_retry_s: float = 1.0
    window_refind_interval_s: float = 3.0
    # Refuse to click at a point unless a Highrise window is what is on top there.
    require_game_under_cursor: bool = True
    # Shared across every click path: no second click within this radius
    # (screen pixels) of an earlier click until same_location_cooldown_s passes.
    repeat_click_radius_px: int = 28
    window_client_only: bool = True
    capture_method: str = "screen"     # screen | printwindow
    monitor_index: int = 1
    
    # ADD THESE TWO LINES:
    webhook_url: str = ""
    webhook_interval_s: int = 300

    # logging; file logging defaults to DEBUG while console stays readable
    console_log_level: str = "INFO"
    file_log_level: str = "DEBUG"
    log_console_enabled: bool = True
    log_file_enabled: bool = True
    log_file_max_mb: int = 12

    # matching
    base_threshold: float = 0.78
    # Wider scale coverage matters because Highrise sprites vary with UI scale.
    base_scales: List[float] = field(default_factory=lambda: [0.70, 0.95, 1.25])
    grayscale: bool = True
    max_instances: int = 12
    # Pixel floor for exhaustive template matching. The fast proposal path has
    # its own minimum side setting, used to keep noisy tiny decorations out.
    min_match_side_px: int = 12

    # timing
    loop_delay: float = 0.008
    idle_delay: float = 0.30
    multi_delay: float = 0.05
    learn_delay: float = 0.25

    # exploration
    explore_after_idle_s: float = 0.75
    explore_cooldown_s: float = 0.12
    explore_blacklist_s: float = 90.0
    explore_grid: Tuple[int, int] = (24, 18)
    min_local_change: float = 0.10
    min_global_change: float = 0.15
    min_local_for_global: float = 0.04
    # Exploration is restricted to candidates visually similar to known seed images.
    seed_similarity_hamming_max: int = 22

    # safety
    max_cps: float = 6.0
    max_session_clicks: int = 0   # 0 = unlimited; the bot never stops itself
    global_cooldown: float = 0.25
    max_clicks_per_frame: int = 12
    same_location_cooldown_s: float = 5.0

    # dedup
    dedup_threshold: float = 0.92
    auto_learn_roi: bool = False  # off by default: targets may appear anywhere on screen

    # persistence
    save_interval_s: float = 15.0
    # Downscale larger frames once before detection to control latency.
    match_max_dimension: int = 1024
    # Poll cheaply for frame changes and avoid a full template sweep on identical
    # static frames. The periodic rescan protects against sub-threshold changes.
    skip_unchanged_frames: bool = False
    # Fast color/shape candidate search runs on every captured frame by default.
    # Exact multi-scale template convolution is independently throttled below.
    scan_every_frame: bool = True
    # OpenCV threading is CPU-side even on machines with an NVIDIA GPU.
    opencv_threads: int = 4
    proposal_peaks_per_scale: int = 2
    fast_proposals_per_frame: int = 8
    fast_min_candidate_side_px: int = 24
    # Exhaustive template recovery is spread over frames: checking the whole
    # library at once caused multi-second stalls with 60+ imported targets.
    # One target per frame keeps latency bounded; every target is revisited in a
    # rotating cycle. Increase for faster library coverage at higher CPU cost.
    template_targets_per_frame: int = 1
    # Legacy setting retained for older config files; the rotating budget above
    # supersedes frame-interval full-library sweeps.
    template_fallback_interval_frames: int = 60
    watcher_interval_frames: int = 2
    debug_overlay: bool = False
    debug_score_interval_s: float = 2.5
    unchanged_rescan_interval_s: float = 0.75
    changed_pixel_delta: int = 12
    changed_pixel_fraction: float = 0.00035

    # Reward watchers in ./ok are confirmation signals; they are never clicked.
    # Explore visually plausible unseen ghost forms when no known target is found.
    # Use --patient to disable exploratory clicking explicitly.
    patient_mode: bool = False
    reward_window_s: float = 2.5
    watcher_cooldown_s: float = 2.5
    watcher_threshold: float = 0.82
    watcher_scales: List[float] = field(default_factory=lambda: [0.75, 0.85, 0.95, 1.05, 1.15, 1.3])
    skip_click_while_popup: bool = True
    adaptive_threshold_min: float = 0.65
    adaptive_threshold_max: float = 0.94

    # learn-from-my-clicks (smart_ghost.py)
    # smart_learning : watch the player's left clicks and learn what a ghost is.
    # smart_clicking : once trained, click ghosts by itself (off = teach-only).
    # smart_exclusive: once trained, the learned detector replaces seed/exploration clicking.
    smart_learning: bool = True
    smart_clicking: bool = True
    smart_autoplay: bool = False          # runtime only (--autoplay): play with the saved model, learn nothing
    smart_exclusive: bool = True
    smart_use_seeds: bool = True          # bootstrap the first session with existing seed crops
    smart_threshold: float = 0.80         # model confidence needed to click
    smart_min_positives: int = 12         # positive examples needed for an unvalidated local model
    smart_min_negative_samples: int = 8    # negative examples paired with locally trained model
    smart_min_validated_train_rows: int = 100
    smart_min_validated_precision: float = 0.85
    smart_min_validated_recall: float = 0.85
    smart_confirm_frames: int = 2         # frames a candidate must stay above threshold
    smart_track_cooldown_s: float = 1.5   # never re-click the same moving ghost sooner than this
    smart_lead_ms: float = 0.0            # aim-ahead for moving ghosts; 0 = measure automatically
    smart_yield_to_user: bool = True      # pause bot clicks while the player is clicking
    smart_yield_s: float = 0.8
    smart_penalize_static: bool = True    # distrust things that never move
    smart_feedback_delay_s: float = 0.35
    smart_aug_pos: int = 8                # augmented copies per learned ghost (colour/flip/scale)
    smart_aug_neg: int = 2
    popup_dismiss: bool = True                    # auto-click away the 'esprits attrapés' banner
    popup_dismiss_image: str = "VagueComplete.png"
    popup_dismiss_threshold: float = 0.80
    popup_dismiss_settle_s: float = 0.9
    smart_auto_clean: bool = True         # quarantine samples the cross-validated model says are mislabelled
    # Ecto confirmation: the webhook toast reader tells the learner which bot clicks really caught a ghost.
    smart_ecto_confirm: bool = True       # use gains as ground truth (strong positives, hit-rate, retries)
    smart_ecto_window_s: float = 3.0      # max click->toast delay before learning it; then adapts to measured latency
    smart_ecto_max_gain: int = 500        # a toast bigger than this is a bonus/daily reward, not a catch
    smart_retry_misses: bool = True       # ghost survived the click and still moves -> re-click it fast
    smart_retry_max: int = 2
    smart_auto_threshold: bool = True     # nudge smart_threshold from the measured hit rate
    smart_threshold_floor: float = 0.88   # auto-threshold never goes below this
    smart_boss_min_frac: float = 0.14     # targets at least this fraction of the frame height count as bosses
    smart_boss_cooldown_s: float = 0.4    # bosses take many clicks: re-click this fast
    smart_probe: bool = False             # click near-threshold movers now and then to get ecto ground truth
    smart_probe_interval_s: float = 30.0

    # ghost kinds / big waves (ghost_classifier.py)
    ghost_scene: bool = True              # label ghosts (small / boss + colour) and detect big waves
    wave_min_ghosts: int = 6              # this many small ghosts on screen at once = big wave
    wave_click_all: bool = True           # during a wave, click every small ghost on screen
    wave_max_cps: float = 14.0            # click-rate cap while a wave is running (normal cap is max_cps)
    wave_clicks_per_tick: int = 4         # clicks sent per frame during a wave
    wave_reclick_s: float = 0.9           # do not click the same spot again sooner than this
    wave_conf_delta: float = 0.25         # boxes up to this far BELOW smart_threshold still count toward a wave (was a fixed 0.15)
    wave_dedup_iou: float = 0.70          # merge two boxes only above this overlap (was 0.5: packed ghosts got merged into one)
    ghost_overlay: bool = True            # draw boxes + labels + banner directly over the game (click-through, invisible to the bot)
    ghost_preview: bool = False           # separate cv2 window instead (only used when the overlay is off)
    ghost_preview_force: bool = False     # show it even when it would overlap the game (the bot may then see it!)
    ghost_preview_width: int = 960
    labeling_collect: bool = True         # save crops to labels/unlabeled/ for label_ghosts.py
    # learn from the on-screen overlay (see overlay_teacher.py). Never active in AUTO PLAY.
    teach_gui: bool = True                # the GUI's Teach window: click a box in a live picture and label it
    teach_gui_interval_s: float = 0.4     # ... how often the bot hands it a new picture (only while it is open)
    teach_gui_max_w: int = 1280           # ... pictures are downscaled to this width for display (training uses full size)
    overlay_teach: bool = False           # OLD F4 teach mode (hover a box + keys); the Teach window replaces it
    overlay_teach_timeout_s: float = 45.0 # teach mode switches itself off after this long without a key
    overlay_auto_learn: bool = True       # save boxes the model is very sure about as low-weight positives
    overlay_auto_min_p: float = 0.93      # ... only when its probability is at least this
    overlay_auto_interval_s: float = 2.0  # ... at most one sample per this many seconds
    overlay_auto_max_session: int = 60    # ... and at most this many per run
    overlay_auto_max_share: float = 0.25  # ... and never more than this share of all positives
    overlay_auto_weight: float = 0.35     # training weight of such a sample (a click is ~1.0)

    # hotkeys
    hk_pause: str = "f9"
    hk_quit: str = "f12"
    hk_zone: str = "f7"
    hk_reload: str = "f10"
    hk_bad: str = "f8"      # tell the smart detector its last click was NOT a ghost
    hk_teach: str = "f4"    # toggle overlay teach mode (hover a ghost box + SPACE / X / colour keys)

    # exclusions (window-relative [x,y,w,h])
    exclusion_zones: List[List[int]] = field(default_factory=list)


def smart_exclusive_active(cfg, smart) -> bool:
    """Whether the ready learned detector owns target selection this frame."""
    return bool(smart is not None and getattr(cfg, "smart_clicking", False)
                and getattr(cfg, "smart_exclusive", False) and smart.ready())


def effective_webhook_url(config_url: Optional[str], environ=None) -> str:
    """Resolve webhook credentials without logging or persisting the environment value."""
    source = os.environ if environ is None else environ
    return str(source.get("BLOOP_WEBHOOK_URL", "") or "").strip() or str(config_url or "").strip()


def should_start_reporter(config_url: Optional[str], smart_ecto_confirm: bool,
                          reporter_available: bool = True, environ=None) -> Tuple[bool, str]:
    """Return (start_reporter, effective_url).

    OCR confirmation is useful even when Discord posting is disabled; an environment
    variable must work even when config.json's webhook_url is blank.
    """
    url = effective_webhook_url(config_url, environ=environ)
    return bool(reporter_available and (url or smart_ecto_confirm)), url


def load_config(path: Path) -> Config:
    if not path.is_file():
        return Config()
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    fields_ = {f.name for f in Config.__dataclass_fields__.values()}
    clean = {k: v for k, v in raw.items() if k in fields_}
    if "explore_grid" in clean:
        clean["explore_grid"] = tuple(clean["explore_grid"])
    cfg = Config(**clean)
    # Fail fast on invalid or hazardous values rather than accepting an
    # effectively unbounded click budget from a stale config file.
    cfg.max_cps = max(0.0, min(float(cfg.max_cps), 20.0))
    cfg.max_session_clicks = max(0, min(int(cfg.max_session_clicks), 10_000_000))
    cfg.window_process = exe_name(cfg.window_process)
    cfg.window_title = str(cfg.window_title or "").strip()
    cfg.focus_retry_s = max(0.2, min(float(cfg.focus_retry_s), 30.0))
    cfg.window_refind_interval_s = max(0.5, min(float(cfg.window_refind_interval_s), 60.0))
    cfg.repeat_click_radius_px = max(0, min(int(cfg.repeat_click_radius_px), 200))
    cfg.max_instances = max(1, min(int(cfg.max_instances), 40))
    cfg.min_match_side_px = max(8, min(int(cfg.min_match_side_px), 96))
    cfg.max_clicks_per_frame = max(1, min(int(cfg.max_clicks_per_frame), 40))
    cfg.loop_delay = max(0.001, min(float(cfg.loop_delay), 1.0))
    cfg.idle_delay = max(cfg.loop_delay, min(float(cfg.idle_delay), 3.0))
    cfg.global_cooldown = max(0.0, min(float(cfg.global_cooldown), 5.0))
    cfg.same_location_cooldown_s = max(0.5, min(float(cfg.same_location_cooldown_s), 120.0))
    cfg.base_scales = sorted({max(0.35, min(float(s), 2.5)) for s in cfg.base_scales}) or [1.0]
    cfg.watcher_scales = sorted({max(0.35, min(float(s), 2.5)) for s in cfg.watcher_scales}) or [1.0]
    cfg.base_threshold = max(0.45, min(float(cfg.base_threshold), 0.99))
    cfg.watcher_threshold = max(0.45, min(float(cfg.watcher_threshold), 0.99))
    cfg.match_max_dimension = max(480, min(int(cfg.match_max_dimension), 2560))
    cfg.opencv_threads = max(1, min(int(cfg.opencv_threads), 16))
    cfg.proposal_peaks_per_scale = max(1, min(int(cfg.proposal_peaks_per_scale), 12))
    cfg.fast_proposals_per_frame = max(4, min(int(cfg.fast_proposals_per_frame), 48))
    cfg.template_targets_per_frame = max(1, min(int(cfg.template_targets_per_frame), 8))
    cfg.fast_min_candidate_side_px = max(12, min(int(cfg.fast_min_candidate_side_px), 128))
    cfg.template_fallback_interval_frames = max(1, min(int(cfg.template_fallback_interval_frames), 60))
    cfg.watcher_interval_frames = max(1, min(int(cfg.watcher_interval_frames), 10))
    cfg.debug_score_interval_s = max(0.5, min(float(cfg.debug_score_interval_s), 30.0))
    cfg.unchanged_rescan_interval_s = max(0.15, min(float(cfg.unchanged_rescan_interval_s), 5.0))
    cfg.changed_pixel_delta = max(1, min(int(cfg.changed_pixel_delta), 64))
    cfg.changed_pixel_fraction = max(0.00005, min(float(cfg.changed_pixel_fraction), 0.10))
    cfg.smart_threshold = max(0.5, min(float(cfg.smart_threshold), 0.99))
    cfg.smart_min_positives = max(5, min(int(cfg.smart_min_positives), 500))
    cfg.smart_min_negative_samples = max(3, min(int(cfg.smart_min_negative_samples), 1000))
    cfg.smart_min_validated_train_rows = max(50, min(int(cfg.smart_min_validated_train_rows), 10_000_000))
    cfg.smart_min_validated_precision = max(0.50, min(float(cfg.smart_min_validated_precision), 0.99))
    cfg.smart_min_validated_recall = max(0.50, min(float(cfg.smart_min_validated_recall), 0.99))
    cfg.smart_confirm_frames = max(1, min(int(cfg.smart_confirm_frames), 10))
    cfg.smart_track_cooldown_s = max(0.3, min(float(cfg.smart_track_cooldown_s), 30.0))
    cfg.smart_lead_ms = max(0.0, min(float(cfg.smart_lead_ms), 300.0))
    cfg.smart_yield_s = max(0.0, min(float(cfg.smart_yield_s), 10.0))
    cfg.smart_feedback_delay_s = max(0.1, min(float(cfg.smart_feedback_delay_s), 3.0))
    cfg.smart_ecto_window_s = max(1.0, min(float(cfg.smart_ecto_window_s), 10.0))
    cfg.smart_ecto_max_gain = max(1, int(cfg.smart_ecto_max_gain))
    cfg.smart_retry_max = max(0, min(int(cfg.smart_retry_max), 5))
    cfg.smart_threshold_floor = max(0.5, min(float(cfg.smart_threshold_floor), 0.99))
    cfg.smart_probe_interval_s = max(5.0, min(float(cfg.smart_probe_interval_s), 600.0))
    cfg.smart_aug_pos = max(0, min(int(cfg.smart_aug_pos), 24))
    cfg.smart_aug_neg = max(0, min(int(cfg.smart_aug_neg), 8))
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    cfg.console_log_level = str(cfg.console_log_level).upper()
    cfg.file_log_level = str(cfg.file_log_level).upper()
    if cfg.console_log_level not in valid_levels: cfg.console_log_level = "INFO"
    if cfg.file_log_level not in valid_levels: cfg.file_log_level = "DEBUG"
    cfg.log_file_max_mb = max(1, min(int(cfg.log_file_max_mb), 200))
    return cfg


def save_config(path: Path, cfg: Config) -> None:
    d = asdict(cfg)
    d["explore_grid"] = list(d["explore_grid"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


# ============================================================
# Window capture
# ============================================================
# --- low-level helpers (module level so tests can replace them) ---------------
if sys.platform == "win32":
    from ctypes import wintypes as _wt
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _user32.WindowFromPoint.argtypes = [_wt.POINT]
    _user32.WindowFromPoint.restype = _wt.HWND
    _user32.GetAncestor.argtypes = [_wt.HWND, _wt.UINT]
    _user32.GetAncestor.restype = _wt.HWND
    _user32.GetTopWindow.argtypes = [_wt.HWND]
    _user32.GetTopWindow.restype = _wt.HWND
    _user32.GetWindow.argtypes = [_wt.HWND, _wt.UINT]
    _user32.GetWindow.restype = _wt.HWND
    _user32.IsWindowVisible.argtypes = [_wt.HWND]
    _user32.IsIconic.argtypes = [_wt.HWND]
    _user32.GetWindowRect.argtypes = [_wt.HWND, ctypes.POINTER(_wt.RECT)]
    _user32.GetWindowLongW.argtypes = [_wt.HWND, ctypes.c_int]
    _user32.GetWindowThreadProcessId.argtypes = [_wt.HWND, ctypes.POINTER(_wt.DWORD)]
    _user32.GetWindowThreadProcessId.restype = _wt.DWORD
    _kernel32.OpenProcess.argtypes = [_wt.DWORD, _wt.BOOL, _wt.DWORD]
    _kernel32.OpenProcess.restype = _wt.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = [_wt.HANDLE, _wt.DWORD, _wt.LPWSTR, ctypes.POINTER(_wt.DWORD)]
    _kernel32.QueryFullProcessImageNameW.restype = _wt.BOOL
    _kernel32.CloseHandle.argtypes = [_wt.HANDLE]
else:  # pragma: no cover - Windows only
    _user32 = _kernel32 = None


def exe_name(value) -> str:
    """'C:\\Games\\Highrise.EXE' -> 'highrise.exe'."""
    text = str(value or "").strip().replace("\\", "/")
    return text.rsplit("/", 1)[-1].strip().lower()


def _pid_of_window(hwnd: int) -> int:
    pid = _wt.DWORD(0)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _process_basename(pid: int) -> str:
    """Lower-case executable name of a process id ('' if it cannot be read)."""
    handle = _kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = _wt.DWORD(1024)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
    finally:
        _kernel32.CloseHandle(handle)
    return ""


def _enum_top_windows() -> List[dict]:
    """All visible top-level windows with owner pid and executable name."""
    out: List[dict] = []
    names: Dict[int, str] = {}

    def cb(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            pid = _pid_of_window(hwnd)
            if pid not in names:
                names[pid] = _process_basename(pid)
            try:
                l, t, r, b = win32gui.GetClientRect(hwnd)
                area = max(0, r - l) * max(0, b - t)
            except Exception:
                area = 0
            out.append({"hwnd": hwnd, "title": win32gui.GetWindowText(hwnd) or "",
                        "pid": pid, "proc": names[pid],
                        "iconic": bool(win32gui.IsIconic(hwnd)), "area": area})
        except Exception:
            pass
        return True

    win32gui.EnumWindows(cb, None)
    return out


def _window_at_point(x: int, y: int, game_pid: int = 0, game_hwnd: int = 0):
    hwnd = _user32.WindowFromPoint(_wt.POINT(int(x), int(y)))
    if not hwnd:
        return 0, 0
    root = _user32.GetAncestor(hwnd, 2) or hwnd
    if int(root) not in OVERLAY_HWNDS:
        return int(root), _pid_of_window(root)

    # The overlay is on top: walk down the Z-order and require a match.
    h = _user32.GetTopWindow(None)
    rc = _wt.RECT()
    while h:
        h_i = int(h)
        if h_i not in OVERLAY_HWNDS and _user32.IsWindowVisible(h) and not _user32.IsIconic(h):
            _user32.GetWindowRect(h, ctypes.byref(rc))
            if rc.left <= x < rc.right and rc.top <= y < rc.bottom \
               and not (_user32.GetWindowLongW(h, -20) & 0x20):
                pid = _pid_of_window(h)
                # Only accept the window we actually care about.
                if (game_hwnd and _user32.GetAncestor(h, 2) == game_hwnd) \
                   or (game_pid and pid == game_pid):
                    return h_i, pid
        h = _user32.GetWindow(h, 2)
    return 0, 0

class WindowCapture:
    """Finds and tracks the game window.

    Targeting is by executable name (default highrise.exe), not by title, so the
    bot can never lock onto its own GUI. The window is re-resolved periodically,
    which makes the bot survive the game being closed and reopened.
    """

    def __init__(self, title: str = "", client_only: bool = True, process_name: str = ""):
        self.title = title
        self.process_name = exe_name(process_name)
        self.client_only = client_only
        self.hwnd: Optional[int] = None
        self.pid: int = 0
        self.last_status = "window search has not run"

    @property
    def targeting(self) -> bool:
        return bool(self.process_name or self.title)

    @property
    def label(self) -> str:
        return self.process_name or repr(self.title)

    def find(self) -> bool:
        """Pick the best visible window of the target (un-minimized, then largest)."""
        if not HAS_WIN32 or not self.targeting:
            self.hwnd, self.pid = None, 0
            self.last_status = "window capture requires pywin32 and a process name or title"
            return False
        needle = (self.title or "").lower()
        own = {os.getpid(), os.getppid()}   # the bot and the GUI that launched it
        try:
            windows = _enum_top_windows()
        except Exception as exc:
            self.hwnd, self.pid = None, 0
            self.last_status = f"window enumeration failed: {exc}"
            return False
        found = []
        for w in windows:
            if w["pid"] in own or "bloop" in w["title"].lower():
                continue
            if self.process_name:
                if w["proc"] != self.process_name:
                    continue
            elif needle not in w["title"].lower():
                continue
            if w["area"] <= 0 and not w["iconic"]:
                continue   # invisible helper window of the same process
            found.append(w)
        if not found:
            self.hwnd, self.pid = None, 0
            self.last_status = f"{self.label} is not running or has no visible window yet; waiting for it"
            return False
        def rank(w):
            real = w["area"] >= 160 * 120
            tier = 2 if (real and not w["iconic"]) else (1 if w["iconic"] else 0)
            return (tier, w["area"])
        found.sort(key=rank, reverse=True)
        best = found[0]
        self.hwnd, self.pid = best["hwnd"], best["pid"]
        self.last_status = (f"matched {best['title']!r} ({best['proc'] or 'unknown exe'})"
                            + (" (minimized)" if best["iconic"] else ""))
        return True

    def is_alive(self) -> bool:
        if self.hwnd is None or not HAS_WIN32 or not win32gui.IsWindow(self.hwnd):
            return False
        if self.pid:
            try:
                return _pid_of_window(self.hwnd) == self.pid   # guards against handle reuse
            except Exception:
                return False
        return True

    def is_minimized(self) -> bool:
        try:
            return bool(self.hwnd and win32gui.IsIconic(self.hwnd))
        except Exception:
            return False

    def _foreground_is_game(self) -> bool:
        try:
            fg = win32gui.GetForegroundWindow()
            if not fg:
                return False
            if fg == self.hwnd:
                return True
            root = win32gui.GetAncestor(fg, 2)
            return root == self.hwnd or bool(self.pid and _pid_of_window(root or fg) == self.pid)
        except Exception:
            return False

    def is_foreground(self) -> bool:
        if not self.is_alive():
            self.last_status = "matched window handle is no longer valid"
            return False
        if self._foreground_is_game():
            return True
        try:
            fg = win32gui.GetForegroundWindow()
            fg = win32gui.GetAncestor(fg, 2) or fg
            name = win32gui.GetWindowText(fg) or "another application"
        except Exception:
            name = "another application"
        self.last_status = f"{self.label} is not in front (foreground is {name!r})"
        return False

    def owns_point(self, x: int, y: int) -> bool:
        try:
            root, pid = _window_at_point(x, y, game_pid=self.pid, game_hwnd=self.hwnd)
        except Exception:
            return False
        return bool(root) and (root == self.hwnd or (bool(self.pid) and pid == self.pid))

    def visible_fraction(self, rect: Dict[str, int]) -> float:
        """Share of a 3x3 grid of sample points inside rect that show the game."""
        hits = total = 0
        for fx in (0.15, 0.5, 0.85):
            for fy in (0.15, 0.5, 0.85):
                total += 1
                if self.owns_point(rect["left"] + int(rect["width"] * fx),
                                   rect["top"] + int(rect["height"] * fy)):
                    hits += 1
        return hits / max(1, total)

    def usable_for_screen_capture(self, rect: Dict[str, int]) -> bool:
        """Screen capture reads desktop pixels; accept it only when the game is what is shown."""
        if self._foreground_is_game():
            return True
        if self.visible_fraction(rect) >= 0.6:
            return True
        self.is_foreground()   # sets a descriptive last_status
        return False

    def get_rect(self) -> Optional[Dict[str, int]]:
        if not self.is_alive():
            self.last_status = "matched window handle is no longer valid"
            return None
        try:
            if win32gui.IsIconic(self.hwnd):
                self.last_status = f"{self.label} is minimized"
                return None
            if self.client_only:
                l, t, r, b = win32gui.GetClientRect(self.hwnd)
                l, t = win32gui.ClientToScreen(self.hwnd, (l, t))
                r, b = win32gui.ClientToScreen(self.hwnd, (r, b))
            else:
                l, t, r, b = win32gui.GetWindowRect(self.hwnd)
        except Exception as exc:
            self.last_status = f"could not read target window rectangle: {exc}"
            return None
        if r - l <= 0 or b - t <= 0:
            self.last_status = f"target window has an empty client rectangle ({r-l}x{b-t})"
            return None
        self.last_status = "target window rectangle ready"
        return {"left": l, "top": t, "width": r - l, "height": b - t}

    def focus(self) -> bool:
        """Restore (if minimized) and raise the game window. Cheap when already in front."""
        if not self.is_alive():
            return False
        try:
            if win32gui.IsIconic(self.hwnd):
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
            if self._foreground_is_game():
                return True
            fg = win32gui.GetForegroundWindow()
            cur_tid = _kernel32.GetCurrentThreadId()
            fg_tid = _user32.GetWindowThreadProcessId(fg, None) if fg else 0
            attached = bool(fg_tid and fg_tid != cur_tid and _user32.AttachThreadInput(cur_tid, fg_tid, True))
            try:
                win32gui.BringWindowToTop(self.hwnd)
                win32gui.SetForegroundWindow(self.hwnd)
            finally:
                if attached:
                    _user32.AttachThreadInput(cur_tid, fg_tid, False)
        except Exception:
            try:
                ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)   # Alt unlocks SetForegroundWindow
                ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
                win32gui.SetForegroundWindow(self.hwnd)
            except Exception:
                pass
        return self._foreground_is_game()


# ============================================================
# Screen capture
# ============================================================
def capture_region_screen(sct, rect: Dict[str, int]) -> np.ndarray:
    shot = sct.grab(rect)
    frame = np.asarray(shot)
    return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)


def capture_window_printwindow(hwnd: int, rect: Dict[str, int]) -> np.ndarray:
    w, h = rect["width"], rect["height"]
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc_dc, w, h)
    save_dc.SelectObject(bmp)
    ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)
    info = bmp.GetInfo()
    bits = bmp.GetBitmapBits(True)
    img = np.frombuffer(bits, dtype=np.uint8).reshape((info["bmHeight"], info["bmWidth"], 4))
    win32gui.DeleteObject(bmp.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


# ============================================================
# Matching
# ============================================================
def _prep(frame, gray):
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if gray else frame


def _resize(t, scale):
    if scale == 1.0:
        return t
    return cv2.resize(t, (max(1, int(t.shape[1] * scale)),
                          max(1, int(t.shape[0] * scale))),
                      interpolation=cv2.INTER_AREA)


def prepare_match_frame(frame: np.ndarray, max_dimension: int = 800) -> dict:
    """Prepare frame features once and share them across all target templates."""
    if frame is None or frame.size == 0:
        raise ValueError("cannot prepare an empty frame")
    if frame.ndim == 2:
        gray = frame
        color = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    else:
        color = frame
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    scale = min(1.0, float(max_dimension) / max(w, h))
    if scale < 0.999:
        size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
        proc_gray = cv2.resize(gray, size, interpolation=cv2.INTER_AREA)
        proc_color = cv2.resize(color, size, interpolation=cv2.INTER_AREA)
    else:
        proc_gray, proc_color = gray, color
    # Edge features are computed at processing resolution. Resizing a full-res
    # edge map made aliases and costs more CPU than recomputing on the small map.
    if scale >= 0.999:
        proc_edges = cv2.Canny(cv2.GaussianBlur(proc_gray, (3, 3), 0), 40, 120)
        edges = proc_edges
    else:
        proc_edges = cv2.Canny(cv2.GaussianBlur(proc_gray, (3, 3), 0), 40, 120)
        # Full-resolution edges are required only for user-defined ROIs, but
        # preserving them keeps ROI matching consistent and is still one pass.
        edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 40, 120)
    proc_hsv = cv2.cvtColor(proc_color, cv2.COLOR_BGR2HSV)
    return {"gray": gray, "color": color, "edges": edges, "scale": scale,
            "proc_gray": proc_gray, "proc_color": proc_color, "proc_edges": proc_edges,
            "proc_hsv": proc_hsv}


def _dominant_hue_mask(hsv: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Pixels belonging to the dominant saturated foreground color family."""
    valid = mask > 0
    target_sat = valid & (hsv[:, :, 1] >= 45) & (hsv[:, :, 2] >= 35)
    if int(target_sat.sum()) < max(12, int(valid.sum() * 0.03)):
        return target_sat
    hue = hsv[:, :, 0].astype(np.int16)
    weights = hsv[:, :, 1].astype(np.float32)
    hist = np.bincount(hue[target_sat], weights=weights[target_sat], minlength=180)
    smooth = np.zeros_like(hist)
    for shift in range(-9, 10):
        smooth += np.roll(hist, shift)
    dominant = int(np.argmax(smooth))
    delta = np.abs(hue - dominant)
    delta = np.minimum(delta, 180 - delta)
    return target_sat & (delta <= 20)


def _masked_similarity(screen_gray: np.ndarray, screen_edges: np.ndarray,
                       template_gray: np.ndarray, template_edges: np.ndarray,
                       mask: np.ndarray, screen_color: Optional[np.ndarray] = None,
                       template_color: Optional[np.ndarray] = None,
                       screen_hsv: Optional[np.ndarray] = None,
                       template_hsv: Optional[np.ndarray] = None,
                       template_color_mask: Optional[np.ndarray] = None) -> float:
    """Verify a sprite using foreground texture, color family, and silhouette.

    The seed screenshots can contain scene texture inside translucent glow.
    Hue selection focuses on the seed's dominant saturated color and a small
    halo around it, preventing background pixels baked into a crop from dominating
    verification when the same sprite appears over a different room.
    """
    valid = mask > 0
    if not np.any(valid):
        return -1.0

    compare_mask = valid
    hue_score = 0.5
    shsv = thsv = None
    if (screen_color is not None and template_color is not None
            and screen_color.ndim == 3 and template_color.ndim == 3
            and screen_color.shape[:2] == mask.shape and template_color.shape[:2] == mask.shape):
        try:
            shsv = screen_hsv if screen_hsv is not None else cv2.cvtColor(screen_color, cv2.COLOR_BGR2HSV)
            thsv = template_hsv if template_hsv is not None else cv2.cvtColor(template_color, cv2.COLOR_BGR2HSV)
            hue = thsv[:, :, 0].astype(np.int16)
            target_color = (template_color_mask if template_color_mask is not None
                            and template_color_mask.shape == mask.shape
                            else _dominant_hue_mask(thsv, mask))
            if int(target_color.sum()) >= max(12, int(valid.sum() * 0.03)):
                # Keep the main body hue, not unrelated scenery baked into the crop.
                k = max(3, min(11, (int(round(min(mask.shape) * 0.06)) | 1)))
                color_neighborhood = cv2.dilate(target_color.astype(np.uint8),
                    cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
                neutral_details = (valid & (thsv[:, :, 1] < 45) &
                                   (thsv[:, :, 2] >= 135) & color_neighborhood)
                refined = target_color | neutral_details
                if int(refined.sum()) >= max(12, int(valid.sum() * 0.06)):
                    compare_mask = refined
                hue_valid = (target_color & (shsv[:, :, 1] >= 30))
                if int(hue_valid.sum()) >= max(12, int(target_color.sum() * 0.10)):
                    delta = np.abs(shsv[:, :, 0].astype(np.int16) - hue.astype(np.int16))
                    delta = np.minimum(delta, 180 - delta).astype(np.float32)
                    hue_score = float(np.mean(0.5 + 0.5 * np.cos(
                        delta[hue_valid] * (2.0 * np.pi / 180.0))))
                    hue_score = max(0.0, min(1.0, hue_score))
        except cv2.error:
            shsv = thsv = None
            compare_mask = valid
            hue_score = 0.5

    s = screen_gray[compare_mask].astype(np.float32)
    t = template_gray[compare_mask].astype(np.float32)
    s -= float(s.mean())
    t -= float(t.mean())
    denom = float(np.linalg.norm(s) * np.linalg.norm(t))
    gray_corr = float(np.dot(s, t) / denom) if denom > 1e-6 else -1.0
    gray_score = max(0.0, min(1.0, (gray_corr + 1.0) * 0.5))

    channel_score = gray_score
    if screen_color is not None and template_color is not None:
        channels = []
        for channel in range(3):
            sc = screen_color[:, :, channel][compare_mask].astype(np.float32)
            tc = template_color[:, :, channel][compare_mask].astype(np.float32)
            sc -= float(sc.mean())
            tc -= float(tc.mean())
            d = float(np.linalg.norm(sc) * np.linalg.norm(tc))
            corr = float(np.dot(sc, tc) / d) if d > 1e-6 else -1.0
            channels.append(max(0.0, min(1.0, (corr + 1.0) * 0.5)))
        channel_score = float(np.mean(channels))

    # Silhouette and tolerant edge alignment remain measured on the complete mask.
    te = (template_edges > 0) & valid
    se = (screen_edges > 0) & valid
    nt, ns = int(te.sum()), int(se.sum())
    if nt == 0 or ns == 0:
        edge_score = 0.0
    else:
        kernel = np.ones((3, 3), dtype=np.uint8)
        te_d = cv2.dilate(te.astype(np.uint8), kernel) > 0
        se_d = cv2.dilate(se.astype(np.uint8), kernel) > 0
        recall = float(np.count_nonzero(te & se_d)) / nt
        precision = float(np.count_nonzero(se & te_d)) / ns
        edge_score = 2.0 * precision * recall / (precision + recall + 1e-6)
    return max(0.0, min(1.0,
        0.25 * gray_score + 0.20 * channel_score + 0.35 * hue_score + 0.20 * edge_score))


# Cache target-side transforms between frames. The expensive work in the masked
# verifier (resizing, HSV conversion, hue-family extraction and edge generation)
# depends on the template and scale, not the live frame. A byte-bounded LRU keeps
# repeated ticks fast without allowing large templates to grow RAM without limit.
_TEMPLATE_FEATURE_CACHE = OrderedDict()
_TEMPLATE_FEATURE_CACHE_BYTES = 0
_TEMPLATE_FEATURE_CACHE_LIMIT = 64 * 1024 * 1024


def _cached_masked_template_features(template_gray: np.ndarray,
                                     template_color_source: np.ndarray,
                                     base_mask: np.ndarray,
                                     template_edges: np.ndarray,
                                     tw: int, th: int, interp: int,
                                     cache_identity: Optional[np.ndarray] = None):
    global _TEMPLATE_FEATURE_CACHE_BYTES
    identity = cache_identity if cache_identity is not None else base_mask
    key = (id(template_gray), id(template_color_source), id(identity),
           id(template_edges), int(tw), int(th), int(interp))
    cached = _TEMPLATE_FEATURE_CACHE.pop(key, None)
    if cached is not None:
        _TEMPLATE_FEATURE_CACHE[key] = cached
        return cached[1]

    coarse_base = template_gray.copy()
    coarse_base[base_mask == 0] = int(np.median(template_gray[base_mask > 0]))
    coarse_t = cv2.resize(coarse_base, (tw, th), interpolation=interp)
    scaled_mask = cv2.resize(base_mask, (tw, th), interpolation=cv2.INTER_NEAREST)
    scaled_mask = np.where(scaled_mask > 0, 255, 0).astype(np.uint8)
    scaled_color = cv2.resize(template_color_source, (tw, th), interpolation=interp)
    scaled_hsv = cv2.cvtColor(scaled_color, cv2.COLOR_BGR2HSV)
    target_color_mask = _dominant_hue_mask(scaled_hsv, scaled_mask)
    scaled_edges = cv2.resize(template_edges, (tw, th), interpolation=cv2.INTER_NEAREST)
    features = (coarse_t, scaled_mask, scaled_color, scaled_hsv,
                target_color_mask, scaled_edges)
    size_bytes = sum(int(a.nbytes) for a in features)
    # Keep references to the source arrays in the entry. That prevents Python
    # object-id reuse from making a later template collide with a stale key.
    entry = ((template_gray, template_color_source, identity, base_mask, template_edges),
             features, size_bytes)
    while _TEMPLATE_FEATURE_CACHE and _TEMPLATE_FEATURE_CACHE_BYTES + size_bytes > _TEMPLATE_FEATURE_CACHE_LIMIT:
        _, old = _TEMPLATE_FEATURE_CACHE.popitem(last=False)
        _TEMPLATE_FEATURE_CACHE_BYTES -= old[2]
    if size_bytes <= _TEMPLATE_FEATURE_CACHE_LIMIT:
        _TEMPLATE_FEATURE_CACHE[key] = entry
        _TEMPLATE_FEATURE_CACHE_BYTES += size_bytes
    return features


def clear_template_feature_cache() -> None:
    """Clear transformed template cache (also useful for deterministic tests)."""
    global _TEMPLATE_FEATURE_CACHE_BYTES
    _TEMPLATE_FEATURE_CACHE.clear()
    _TEMPLATE_FEATURE_CACHE_BYTES = 0


def find_all_matches(screen, template, scales, threshold, gray,
                     max_matches=0, nms_factor=0.5, max_peaks=400,
                     mask=None, precomputed_gray=None, precomputed_edges=None,
                     template_edges=None, template_color=None,
                     precomputed_proc_gray=None, precomputed_proc_color=None,
                     precomputed_proc_edges=None, process_scale_override=None,
                     precomputed_proc_hsv=None, min_match_side_px=0,
                     diagnostics=None, proposal_peaks_per_scale=3):
    """Return scored, non-overlapping template detections.

    Alpha-masked sprite matching uses a fast whole-frame grayscale proposal pass,
    followed by precise foreground/edge verification only at the best candidate
    peaks. This avoids OpenCV's expensive masked full-frame correlation path.
    Ordinary (non-masked) templates use normalized correlation directly.

    Result tuples are (score, center_x, center_y, width, height, scale), in the
    original frame's coordinate system.
    """
    if screen is None or template is None or screen.size == 0 or template.size == 0:
        return []
    if len(template.shape) not in (2, 3):
        return []
    full_h, full_w = screen.shape[:2]
    process_scale = (float(process_scale_override) if process_scale_override is not None
                     else min(1.0, 800.0 / max(full_w, full_h)))
    screen_gray = precomputed_gray
    if screen_gray is None:
        screen_gray = screen if screen.ndim == 2 else cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    if screen.ndim == 2:
        screen_color = cv2.cvtColor(screen, cv2.COLOR_GRAY2BGR)
    else:
        screen_color = screen
    screen_edges = precomputed_edges
    if screen_edges is None:
        screen_edges = cv2.Canny(cv2.GaussianBlur(screen_gray, (3, 3), 0), 40, 120)

    if precomputed_proc_gray is not None:
        proc_gray = precomputed_proc_gray
        proc_color = precomputed_proc_color if precomputed_proc_color is not None else (
            cv2.cvtColor(proc_gray, cv2.COLOR_GRAY2BGR) if screen.ndim == 2 else
            cv2.resize(screen_color, (proc_gray.shape[1], proc_gray.shape[0]), interpolation=cv2.INTER_AREA))
        proc_edges = precomputed_proc_edges if precomputed_proc_edges is not None else cv2.resize(
            screen_edges, (proc_gray.shape[1], proc_gray.shape[0]), interpolation=cv2.INTER_NEAREST)
    elif process_scale < 0.999:
        size = (max(1, int(round(full_w * process_scale))),
                max(1, int(round(full_h * process_scale))))
        proc_gray = cv2.resize(screen_gray, size, interpolation=cv2.INTER_AREA)
        proc_color = cv2.resize(screen_color, (proc_gray.shape[1], proc_gray.shape[0]), interpolation=cv2.INTER_AREA)
        proc_edges = cv2.resize(screen_edges, (proc_gray.shape[1], proc_gray.shape[0]), interpolation=cv2.INTER_NEAREST)
    else:
        proc_gray, proc_color, proc_edges = screen_gray, screen_color, screen_edges
    use_mask = mask is not None and mask.size > 0 and np.count_nonzero(mask) >= 16
    proc_hsv = precomputed_proc_hsv
    if use_mask and proc_hsv is None:
        proc_hsv = cv2.cvtColor(proc_color, cv2.COLOR_BGR2HSV)
    if len(template.shape) == 3:
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        template_color_source = template
    else:
        template_gray = template
        template_color_source = template_color
        if template_color_source is None:
            template_color_source = cv2.cvtColor(template_gray, cv2.COLOR_GRAY2BGR)
    if float(template_gray.std()) < 1e-3:
        return []

    # Make sure the template edge map only contains foreground structure.
    if use_mask:
        base_mask = np.where(mask > 0, 255, 0).astype(np.uint8)
        if template_edges is None:
            cleaned = template_gray.copy()
            cleaned[base_mask == 0] = int(np.median(template_gray[base_mask > 0]))
            template_edges = cv2.Canny(cv2.GaussianBlur(cleaned, (3, 3), 0), 40, 120)
            contours, _ = cv2.findContours(base_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                cv2.drawContours(template_edges, [max(contours, key=cv2.contourArea)], -1, 255, 1)
    else:
        base_mask = None
        template_edges = None
        coarse_base = template_gray if gray else template_color

    raw = []
    # A small number of top peaks per scale is enough because the detector is
    # run on every tick and candidate points are re-suppressed across scales.
    template_side = max(template.shape[:2])
    # The final NMS returns at most max_matches. Verifying dozens of weak peaks
    # per scale dominated CPU time on empty rooms; keep a modest recall reserve.
    proposal_count = max(1, min(12, int(proposal_peaks_per_scale)))
    for scale in scales:
        try:
            scale = float(scale)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(scale) or scale <= 0:
            continue
        effective_scale = scale * process_scale
        tw = max(1, int(round(template.shape[1] * effective_scale)))
        th = max(1, int(round(template.shape[0] * effective_scale)))
        # The relevant size is the actual template pixels in the matching frame,
        # not its size before frame downscaling.
        if use_mask and min_match_side_px > 0 and min(tw, th) < min_match_side_px:
            continue
        if th > proc_gray.shape[0] or tw > proc_gray.shape[1] or th < 8 or tw < 8:
            continue
        interp = cv2.INTER_AREA if effective_scale < 1 else cv2.INTER_LINEAR

        if use_mask:
            (coarse_t, scaled_mask, scaled_color, scaled_hsv,
             target_color_mask, scaled_edges) = _cached_masked_template_features(
                 template_gray, template_color_source, base_mask, template_edges,
                 tw, th, interp, cache_identity=mask)
            if float(coarse_t.std()) < 1e-3:
                continue
            try:
                # Fast grayscale proposal map; the following prefilter+masked
                # verifier reject lookalikes. The map is never trusted to click.
                response = cv2.matchTemplate(proc_gray, coarse_t, cv2.TM_CCOEFF_NORMED)
            except cv2.error:
                continue
            response = np.nan_to_num(response, nan=-1.0, posinf=-1.0, neginf=-1.0)
            # One grayscale proposal map per scale is substantially faster than
            # running a second full-frame edge correlation. Alpha masking and the
            # detailed color/edge verifier below still decide which peaks may click.
            combined = np.maximum(response, 0.0).astype(np.float32, copy=False)
            if diagnostics is not None and combined.size:
                cy, cx = np.unravel_index(int(np.argmax(combined)), combined.shape)
                peak = float(combined[cy, cx])
                if peak > diagnostics.get("coarse_score", -1.0):
                    diagnostics.update(coarse_score=peak,
                                       coarse_xy=(int(round((cx + tw / 2) / process_scale)),
                                                  int(round((cy + th / 2) / process_scale))))
            kernel = np.ones((5, 5), np.uint8)
            peaks = cv2.dilate(combined, kernel)
            py, px = np.where((combined >= 0.10) & (combined >= peaks - 1e-6))
            if len(py) == 0:
                continue
            vals = combined[py, px]
            keep_n = min(proposal_count, len(vals))
            if len(vals) > keep_n:
                ix = np.argpartition(vals, -keep_n)[-keep_n:]
                py, px, vals = py[ix], px[ix], vals[ix]
            order = np.argsort(-vals)
            for index in order:
                x, y = int(px[index]), int(py[index])
                patch = proc_gray[y:y + th, x:x + tw]
                patch_edges = proc_edges[y:y + th, x:x + tw]
                patch_color = proc_color[y:y + th, x:x + tw]
                patch_hsv = proc_hsv[y:y + th, x:x + tw]
                if patch.shape != (th, tw) or scaled_mask.shape != (th, tw):
                    continue
                # Reject obvious color-family mismatches before the costlier
                # per-pixel detail + edge verification.
                color_pixels = target_color_mask
                if int(color_pixels.sum()) >= 12:
                    screen_hue = patch_hsv[:, :, 0].astype(np.int16)
                    expected_hue = scaled_hsv[:, :, 0].astype(np.int16)
                    hue_delta = np.abs(screen_hue - expected_hue)
                    hue_delta = np.minimum(hue_delta, 180 - hue_delta)
                    hue_agree = ((patch_hsv[:, :, 1] >= 30) & (hue_delta <= 28))
                    if float(hue_agree[color_pixels].mean()) < 0.22:
                        continue
                score = _masked_similarity(patch, patch_edges, coarse_t, scaled_edges,
                                            scaled_mask, patch_color, scaled_color,
                                            patch_hsv, scaled_hsv,
                                            template_color_mask=target_color_mask)
                if diagnostics is not None and score > diagnostics.get("best_score", -1.0):
                    diagnostics.update(best_score=float(score), best_scale=float(scale),
                                       best_xy=(int(round((x + tw / 2) / process_scale)),
                                                int(round((y + th / 2) / process_scale))))
                if score >= threshold:
                    raw.append((float(score), int(round((x + tw / 2) / process_scale)),
                                int(round((y + th / 2) / process_scale)),
                                int(round(tw / process_scale)), int(round(th / process_scale)), scale))
        else:
            if len(template.shape) == 3 and not gray:
                proc_screen = proc_color
                t = cv2.resize(template_color_source, (tw, th), interpolation=interp)
            else:
                proc_screen = proc_gray
                t = cv2.resize(template_gray, (tw, th), interpolation=interp)
            if float(t.std()) < 1e-3:
                continue
            try:
                response = cv2.matchTemplate(proc_screen, t, cv2.TM_CCOEFF_NORMED)
            except cv2.error:
                continue
            response = np.nan_to_num(response, nan=-1.0, posinf=-1.0, neginf=-1.0)
            if diagnostics is not None and response.size:
                iy, ix = np.unravel_index(int(np.argmax(response)), response.shape)
                if float(response[iy, ix]) > diagnostics.get("best_score", -1.0):
                    diagnostics.update(best_score=float(response[iy, ix]), best_scale=float(scale),
                                       best_xy=(int(round((ix + tw / 2) / process_scale)),
                                                int(round((iy + th / 2) / process_scale))))
            peaks = cv2.dilate(response.astype(np.float32), np.ones((5, 5), np.uint8))
            py, px = np.where((response >= threshold) & (response >= peaks - 1e-6))
            if len(py) == 0:
                continue
            vals = response[py, px]
            if len(vals) > max_peaks:
                ix = np.argpartition(vals, -max_peaks)[-max_peaks:]
                py, px, vals = py[ix], px[ix], vals[ix]
            order = np.argsort(-vals)
            for index in order:
                x, y = int(px[index]), int(py[index])
                raw.append((float(vals[index]), int(round((x + tw / 2) / process_scale)),
                            int(round((y + th / 2) / process_scale)),
                            int(round(tw / process_scale)), int(round(th / process_scale)), scale))

    if not raw:
        return []
    raw.sort(key=lambda item: item[0], reverse=True)
    kept = []
    for match in raw:
        _, cx, cy, w, h, _ = match
        x0, y0 = cx - w / 2, cy - h / 2
        x1, y1 = cx + w / 2, cy + h / 2
        suppressed = False
        for other in kept:
            _, ox, oy, ow, oh, _ = other
            ox0, oy0, ox1, oy1 = ox - ow / 2, oy - oh / 2, ox + ow / 2, oy + oh / 2
            iw = max(0.0, min(x1, ox1) - max(x0, ox0))
            ih = max(0.0, min(y1, oy1) - max(y0, oy0))
            inter = iw * ih
            union = w * h + ow * oh - inter
            iou = inter / union if union > 0 else 0.0
            center_dist = ((cx - ox) ** 2 + (cy - oy) ** 2) ** 0.5
            if iou >= 0.20 or center_dist < min(w, h, ow, oh) * nms_factor:
                suppressed = True
                break
        if not suppressed:
            kept.append(match)
            if max_matches > 0 and len(kept) >= max_matches:
                break
    return kept


def region_diff(before, after, cx, cy, radius=140) -> float:
    """Local pixel change around (cx, cy), normalized to [0,1]."""
    if before is None or after is None or before.size == 0 or after.size == 0:
        return 0.0
    h, w = before.shape[:2]
    if after.shape[:2] != (h, w):
        return 1.0
    x0, x1 = max(0, cx - radius), min(w, cx + radius)
    y0, y1 = max(0, cy - radius), min(h, cy + radius)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    b = cv2.cvtColor(cv2.resize(before[y0:y1, x0:x1], (64, 64)), cv2.COLOR_BGR2GRAY)
    a = cv2.cvtColor(cv2.resize(after[y0:y1, x0:x1], (64, 64)), cv2.COLOR_BGR2GRAY)
    return float(cv2.absdiff(b, a).mean()) / 255.0


def global_diff(before, after) -> float:
    if before is None or after is None or before.shape[:2] != after.shape[:2]:
        return 1.0
    b = cv2.cvtColor(cv2.resize(before, (160, 90)), cv2.COLOR_BGR2GRAY)
    a = cv2.cvtColor(cv2.resize(after, (160, 90)), cv2.COLOR_BGR2GRAY)
    return float(cv2.absdiff(b, a).mean()) / 255.0


def extract_foreground_mask(image: np.ndarray) -> Optional[np.ndarray]:
    """Estimate an object silhouette for a tightly-cropped exploration proposal.

    This is intentionally conservative. A mask is returned only when GrabCut
    produces a non-trivial foreground component; it is used for family-shape
    filtering and alpha-masked learning, not as semantic ground truth.
    """
    if image is None or image.size == 0 or image.ndim != 3:
        return None
    h, w = image.shape[:2]
    if min(h, w) < 14:
        return None
    pad = max(2, min(8, int(min(h, w) * 0.04)))
    if w <= 2 * pad or h <= 2 * pad:
        return None
    gc = np.zeros((h, w), dtype=np.uint8)
    bgd = np.zeros((1, 65), dtype=np.float64)
    fgd = np.zeros((1, 65), dtype=np.float64)
    try:
        cv2.grabCut(image, gc, (pad, pad, w - 2 * pad, h - 2 * pad),
                    bgd, fgd, 3, cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return None
    binary = np.where((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats((binary > 0).astype(np.uint8), 8)
    if n <= 1:
        return None
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    area = int(stats[idx, cv2.CC_STAT_AREA])
    if area < max(40, int(h * w * 0.04)) or area > int(h * w * 0.98):
        return None
    comp = (labels == idx).astype(np.uint8) * 255
    k = max(3, int(min(h, w) * 0.04) // 2 * 2 + 1)
    comp = cv2.morphologyEx(comp, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    filled = np.zeros_like(comp)
    cv2.drawContours(filled, [contour], -1, 255, thickness=cv2.FILLED)
    return filled


def quick_hue_mask(image: np.ndarray, expected_hue: Optional[float] = None, hsv: Optional[np.ndarray] = None) -> Tuple[Optional[np.ndarray], Optional[float]]:
    """Fast HSV/connected-component mask for real-time candidate verification.

    When matching a known seed, callers supply its hue so a similarly colored
    background cannot dictate the crop's dominant color (common for yellow
    ghosts on earthy rooms). For discovery, dominant saturated hue is used.
    No GrabCut/graph cuts are performed on the per-frame hot path.
    """
    if image is None or image.size == 0 or image.ndim != 3 or min(image.shape[:2]) < 10:
        return None, None
    bgr = image[:, :, :3] if image.shape[2] >= 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    hsv = hsv if hsv is not None else cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hue, sat, val = cv2.split(hsv)
    h, w = hue.shape
    total = max(1, h * w)
    if expected_hue is None:
        colored = (sat >= 42) & (val >= 32)
        if int(colored.sum()) < max(12, int(total * 0.018)):
            return None, None
        hist = np.bincount(hue[colored], weights=sat[colored].astype(np.float32), minlength=180).astype(np.float32)
        smooth = np.zeros_like(hist)
        for shift in range(-5, 6):
            smooth += np.roll(hist, shift)
        expected_hue = float(np.argmax(smooth))
        tolerance, sat_floor = 10.0, 32
    else:
        # Known-seed matching uses a narrow, bright neon band. Broad masks made
        # yellow sprites merge into warm room scenery and blue sprites into UI.
        tolerance, sat_floor = 8.0, 42
    delta = np.abs(hue.astype(np.float32) - float(expected_hue))
    delta = np.minimum(delta, 180.0 - delta)
    band = (delta <= tolerance) & (sat >= sat_floor) & (val >= 28)
    binary = band.astype(np.uint8) * 255
    kernel_size = 3 if min(h, w) < 50 else 5
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
    n, labels, stats, centroids = cv2.connectedComponentsWithStats((binary > 0).astype(np.uint8), 8)
    if n <= 1:
        return None, float(expected_hue)
    min_area = max(12, int(total * 0.008 if expected_hue is not None else 0.018))
    options = []
    center_x, center_y = w * 0.5, h * 0.5
    for idx in range(1, n):
        x, y, cw, ch, area = [int(v) for v in stats[idx]]
        if area < min_area or area > int(total * 0.97):
            continue
        cx, cy = centroids[idx]
        center_dist = (((cx-center_x)/max(1,w))**2 + ((cy-center_y)/max(1,h))**2) ** 0.5
        edges = int(x <= 0) + int(y <= 0) + int(x + cw >= w) + int(y + ch >= h)
        # Prefer a sizable component near the proposal center; room/background
        # regions frequently touch several crop edges and are down-ranked.
        score = np.log1p(area) - 3.2 * center_dist - 0.70 * max(0, edges - 1)
        options.append((float(score), idx))
    if not options:
        return None, float(expected_hue)
    _, idx = max(options)
    component = (labels == idx).astype(np.uint8) * 255
    contours, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, float(expected_hue)
    filled = np.zeros_like(component)
    cv2.drawContours(filled, [max(contours, key=cv2.contourArea)], -1, 255, cv2.FILLED)
    selected = (filled > 0) & (sat >= sat_floor) & (val >= 28)
    if int(selected.sum()) >= 8:
        vals = hue[selected]
        hist = np.bincount(vals, weights=sat[selected].astype(np.float32), minlength=180)
        actual_hue = float(np.argmax(hist))
    else:
        actual_hue = float(expected_hue)
    return filled, actual_hue


def _mask_contour(mask: Optional[np.ndarray]):
    if mask is None or mask.size == 0:
        return None
    contours, _ = cv2.findContours((mask > 0).astype(np.uint8) * 255,
                                   cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    return contour if cv2.contourArea(contour) >= 25 else None


def dhash(img: np.ndarray, size: int = 8) -> int:
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (size + 1, size))
    diff = g[:, 1:] > g[:, :-1]
    out = 0
    for bit in diff.flatten():
        out = (out << 1) | int(bit)
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def dominant_hue_value(img: np.ndarray, mask: Optional[np.ndarray] = None) -> Optional[float]:
    """Return the dominant saturated hue (OpenCV 0..179), ignoring transparent/background pixels."""
    if img is None or img.size == 0:
        return None
    bgr = img[:, :, :3] if img.ndim == 3 and img.shape[2] >= 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    valid = (hsv[:, :, 1] >= 45) & (hsv[:, :, 2] >= 35)
    if mask is not None and mask.shape[:2] == valid.shape:
        valid &= mask > 0
    if int(valid.sum()) < 12:
        return None
    hues = hsv[:, :, 0][valid]
    weights = hsv[:, :, 1][valid].astype(np.float32)
    hist = np.bincount(hues, weights=weights, minlength=180).astype(np.float32)
    smooth = np.zeros_like(hist)
    for shift in range(-8, 9):
        smooth += np.roll(hist, shift)
    return float(np.argmax(smooth))


def hue_distance(a: Optional[float], b: Optional[float]) -> float:
    if a is None or b is None:
        return 0.0
    delta = abs(float(a) - float(b))
    return min(delta, 180.0 - delta)


# ============================================================
# Saliency (candidate proposal)
# ============================================================
class SaliencyDetector:
    def __init__(self, min_w: int, max_w: int, min_h: int, max_h: int,
                 aspect_lo: float = 0.35, aspect_hi: float = 3.0,
                 max_dimension: int = 960):
        self.min_w, self.max_w = min_w, max_w
        self.min_h, self.max_h = min_h, max_h
        self.aspect_lo, self.aspect_hi = aspect_lo, aspect_hi
        self.max_dimension = max(480, int(max_dimension))

    def candidates(self, frame: np.ndarray) -> List[Tuple[float, int, int, int, int]]:
        original_h, original_w = frame.shape[:2]
        process_scale = min(1.0, self.max_dimension / max(original_w, original_h))
        if process_scale < 0.999:
            work = cv2.resize(frame, (max(1, int(round(original_w * process_scale))),
                                      max(1, int(round(original_h * process_scale)))),
                              interpolation=cv2.INTER_AREA)
        else:
            work = frame
        frame_h, frame_w = work.shape[:2]
        gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 40, 130)
        edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=1)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE,
                                 np.ones((15, 15), np.uint8))
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        out = []
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            if not (self.min_w <= w <= self.max_w and self.min_h <= h <= self.max_h):
                continue
            ar = w / max(1, h)
            if not (self.aspect_lo <= ar <= self.aspect_hi):
                continue
            mask = np.zeros_like(edges)
            cv2.drawContours(mask, [c], -1, 255, -1)
            m = mask > 0
            if m.sum() < 50:
                continue
            density = float((edges > 0)[m].mean())
            fill = float(m.sum()) / max(1, w * h)
            score = density * (0.5 + 0.5 * fill)
            out.append((score, x, y, w, h))

        # Edge contours alone missed luminous ghosts in the user-provided room
        # frame (the edge union had no candidate at all). Add neon-color connected
        # components as a second proposal channel. This is only a proposer: every
        # exploration candidate must still pass the foreground/ghost-shape gate.
        hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
        sat, val = hsv[:, :, 1], hsv[:, :, 2]
        neon = ((sat >= 105) & (val >= 65)).astype(np.uint8) * 255
        close_size = max(3, min(11, (int(min(frame_h, frame_w) * 0.012) | 1)))
        neon = cv2.morphologyEx(neon, cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_size, close_size)))
        neon = cv2.dilate(neon, np.ones((3, 3), np.uint8), iterations=1)
        count, labels, stats, _ = cv2.connectedComponentsWithStats((neon > 0).astype(np.uint8), 8)
        max_w = min(frame_w - 1, max(self.max_w, int(frame_w * 0.92)))
        max_h = min(frame_h - 1, max(self.max_h, int(frame_h * 0.92)))
        for idx in range(1, count):
            x, y, bw, bh, area = [int(v) for v in stats[idx]]
            if not (max(18, self.min_w // 2) <= bw <= max_w and
                    max(18, self.min_h // 2) <= bh <= max_h and area >= max(60, int(frame_h * frame_w * 0.002))):
                continue
            ar = bw / max(1, bh)
            if not (0.35 <= ar <= 3.0) or (bw * bh) >= (frame_w * frame_h * 0.985):
                continue
            component = labels[y:y + bh, x:x + bw] == idx
            fill = float(area) / max(1, bw * bh)
            mean_sat = float(sat[y:y + bh, x:x + bw][component].mean()) / 255.0
            # Prioritize coherent luminous regions but don't make this score a
            # click confidence; contour and response validation still follow.
            score = 0.55 + min(0.25, fill * 0.25) + min(0.20, mean_sat * 0.20)
            out.append((score, x, y, bw, bh))

        # Remove duplicate edge/neon proposals with high rectangle overlap.
        out.sort(reverse=True)
        kept = []
        for candidate in out:
            _, x, y, bw, bh = candidate
            overlap = False
            for _, px, py, pw, ph in kept:
                inter = max(0, min(x + bw, px + pw) - max(x, px)) * max(0, min(y + bh, py + ph) - max(y, py))
                union = bw * bh + pw * ph - inter
                if union > 0 and inter / union >= 0.55:
                    overlap = True
                    break
            if not overlap:
                kept.append(candidate)
            if len(kept) >= 60:
                break
        if process_scale < 0.999:
            inv = 1.0 / process_scale
            return [(score, int(round(x * inv)), int(round(y * inv)),
                     int(round(bw * inv)), int(round(bh * inv)))
                    for score, x, y, bw, bh in kept]
        return kept


# ============================================================
# Library (persistent known + learned templates)
# ============================================================
@dataclass
class Target:
    name: str
    image_path: str
    source: str = "learned"           # "seed" | "learned"
    threshold: float = 0.78
    scales: List[float] = field(default_factory=lambda: [0.75, 0.9, 1.0, 1.15, 1.3])
    region: Optional[List[int]] = None
    priority: int = 10
    cooldown: float = 0.5
    action: str = "click"             # click | double_click | key
    key: Optional[str] = None
    grayscale: bool = True
    # Persistent evidence; these are updated conservatively across sessions.
    evidence_clicks: int = 0
    evidence_responses: int = 0
    evidence_no_change: int = 0
    total_hits: int = 0
    total_misses: int = 0
    total_rewards: int = 0
    confirmed_scores: List[float] = field(default_factory=list)
    negative_scores: List[float] = field(default_factory=list)
    # Weak post-click evidence, distinct from explicit reward-popup confirmation.
    response_scores: List[float] = field(default_factory=list)
    no_response_scores: List[float] = field(default_factory=list)
    # runtime (not serialized)
    _template: Optional[np.ndarray] = None
    _template_color: Optional[np.ndarray] = None
    _mask: Optional[np.ndarray] = None
    _edge_template: Optional[np.ndarray] = None
    _scale_compensation: float = 1.0
    _threshold_floor: float = 0.0
    _hash: int = 0
    _dominant_hue: Optional[float] = None
    _color_median_hue: Optional[float] = None
    _shape_contour: Optional[np.ndarray] = None
    _last_action: float = 0.0
    _clicks: List[Tuple[int, int]] = field(default_factory=list)
    _recent_locations: List[Tuple[int, int, float]] = field(default_factory=list)
    _dirty: bool = False

    def load(self, base: Path):
        p = Path(self.image_path)
        if not p.is_absolute():
            p = base / p
        raw = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
        if raw is None:
            return False
        self._mask = None
        if raw.ndim == 3 and raw.shape[2] == 4:
            img, alpha = raw[:, :, :3], raw[:, :, 3]
            # Treat non-opaque alpha as a foreground mask, but tolerate PNGs
            # whose alpha channel is present yet entirely opaque.
            if np.count_nonzero(alpha < 250) >= 16 and np.count_nonzero(alpha > 0) >= 16:
                self._mask = np.where(alpha >= 32, 255, 0).astype(np.uint8)
        elif raw.ndim == 2:
            img = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
        else:
            img = raw
        max_side = max(img.shape[:2])
        # Similar silhouette sprites need stricter thresholds to prevent cross-
        # family clicks. Large detailed images naturally score a little lower.
        self._threshold_floor = 0.0
        # The score floor is assigned after the masked edge map is available;
        # compact icons with dense internal detail need a stricter threshold than
        # a simpler low-frequency silhouette.
        # Do not shrink normal seed screenshots: the configured scale list is
        # relative to the seed's native dimensions. Shrinking a 240px ghost to
        # 96px without compensating scale made it impossible to detect at 1:1.
        # Only very large accidental crops are normalized, with scale compensation.
        max_native_side = 480 if self.source == "seed" else 600
        preferred_side = 320 if self.source == "seed" else 400
        self._scale_compensation = 1.0
        if max_side > max_native_side:
            ratio = preferred_side / float(max_side)
            self._scale_compensation = 1.0 / ratio
            new_size = (max(8, int(round(img.shape[1] * ratio))),
                        max(8, int(round(img.shape[0] * ratio))))
            img = cv2.resize(img, new_size, interpolation=cv2.INTER_AREA)
            if self._mask is not None:
                self._mask = cv2.resize(self._mask, new_size, interpolation=cv2.INTER_NEAREST)
        # Retain original BGR pixels for masked verification; grayscale-only
        # matching loses the yellow/blue/purple differences between ghost families.
        self._template_color = img.copy()
        self._template = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if self.grayscale else img
        self._hash = dhash(img)
        self._dominant_hue = dominant_hue_value(img, self._mask)
        # A narrow histogram peak is a better segmentation hue than the smoothed
        # perceptual hue used for deduplication; broad smoothing joined yellow
        # ghosts to orange scenery in busy rooms.
        hue_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        hue_valid = (hue_hsv[:, :, 1] >= 70) & (hue_hsv[:, :, 2] >= 60)
        if self._mask is not None and self._mask.shape[:2] == hue_valid.shape:
            hue_valid &= self._mask > 0
        hues = hue_hsv[:, :, 0][hue_valid]
        if hues.size >= 12:
            hue_hist = np.bincount(hues, minlength=180).astype(np.float32)
            hue_smooth = sum(np.roll(hue_hist, shift) for shift in range(-2, 3))
            self._color_median_hue = float(np.argmax(hue_smooth))
        else:
            self._color_median_hue = self._dominant_hue
        if self._mask is not None and self._mask.shape[:2] != self._template.shape[:2]:
            self._mask = cv2.resize(self._mask, (self._template.shape[1], self._template.shape[0]),
                                    interpolation=cv2.INTER_NEAREST)
        gray_template = self._template if self._template.ndim == 2 else cv2.cvtColor(self._template, cv2.COLOR_BGR2GRAY)
        if self._mask is not None:
            mask_binary = np.where(self._mask > 0, 255, 0).astype(np.uint8)
            clean = gray_template.copy()
            clean[mask_binary == 0] = int(np.median(gray_template[mask_binary > 0]))
            self._edge_template = cv2.Canny(cv2.GaussianBlur(clean, (3, 3), 0), 40, 120)
            contours, _ = cv2.findContours(mask_binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                cv2.drawContours(self._edge_template, [max(contours, key=cv2.contourArea)], -1, 255, 1)
        else:
            self._edge_template = None
        # Cache this immutable shape feature: exploration may compare dozens of
        # proposals against every target on every frame.
        self._shape_contour = _mask_contour(self._mask)
        if self.source == "seed" and self._mask is not None:
            valid_area = max(1, int(np.count_nonzero(self._mask)))
            edge_density = float(np.count_nonzero(self._edge_template)) / valid_area
            # Dense-detail sprites require a stricter threshold, except where
            # the masked crop includes a little more scene texture (e.g. the
            # cyan rune effect). Its hue coverage provides a reproducible signal
            # for a slight relaxation; the unrelated-room fixture stays below
            # this floor, while resized/composited cyan instances remain visible.
            color_hsv = cv2.cvtColor(self._template_color, cv2.COLOR_BGR2HSV)
            color_fraction = float(np.count_nonzero(_dominant_hue_mask(color_hsv, self._mask))) / valid_area
            if max_side <= 130 and edge_density >= 0.235:
                self._threshold_floor = 0.83 if color_fraction >= 0.995 else 0.81
            elif max_side <= 130 and edge_density >= 0.14:
                self._threshold_floor = 0.80
            else:
                self._threshold_floor = 0.79
            self.threshold = max(float(self.threshold), self._threshold_floor)
        # Clamp old/corrupt histories when loading a long-running library.
        self.confirmed_scores = [float(v) for v in self.confirmed_scores[-100:] if np.isfinite(v)]
        self.negative_scores = [float(v) for v in self.negative_scores[-100:] if np.isfinite(v)]
        self.response_scores = [float(v) for v in self.response_scores[-100:] if np.isfinite(v)]
        self.no_response_scores = [float(v) for v in self.no_response_scores[-100:] if np.isfinite(v)]
        return True

    def serialize(self) -> dict:
        return {
            "name": self.name, "image_path": self.image_path,
            "source": self.source, "threshold": round(self.threshold, 3),
            "scales": self.scales, "region": self.region,
            "priority": self.priority, "cooldown": self.cooldown,
            "action": self.action, "key": self.key, "grayscale": self.grayscale,
            "evidence_clicks": self.evidence_clicks,
            "evidence_responses": self.evidence_responses,
            "evidence_no_change": self.evidence_no_change,
            "total_hits": self.total_hits,
            "total_misses": self.total_misses,
            "total_rewards": self.total_rewards,
            "confirmed_scores": self.confirmed_scores[-100:],
            "negative_scores": self.negative_scores[-100:],
            "response_scores": self.response_scores[-100:],
            "no_response_scores": self.no_response_scores[-100:],
        }


@dataclass
class Watcher:
    """A visual confirmation image from ./ok. Watchers are never clicked."""
    name: str
    image_path: str
    threshold: float = 0.82
    scales: List[float] = field(default_factory=lambda: [0.75, 0.85, 0.95, 1.05, 1.15, 1.3])
    cooldown: float = 2.5
    region: Optional[List[int]] = None
    grayscale: bool = True
    _template: Optional[np.ndarray] = None
    _template_color: Optional[np.ndarray] = None
    _mask: Optional[np.ndarray] = None
    _last_fired: float = 0.0
    _armed: bool = True
    _count: int = 0
    _visible: bool = False
    _last_score: float = 0.0

    def load(self, base: Path) -> bool:
        p = Path(self.image_path)
        if not p.is_absolute():
            p = base / p
        raw = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
        if raw is None:
            return False
        if raw.ndim == 3 and raw.shape[2] == 4:
            img, alpha = raw[:, :, :3], raw[:, :, 3]
            if np.count_nonzero(alpha < 250) >= 16:
                self._mask = np.where(alpha >= 32, 255, 0).astype(np.uint8)
            else:
                self._mask = None
        elif raw.ndim == 2:
            img = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
            self._mask = None
        else:
            img = raw
            self._mask = None
        self._template_color = img.copy()
        self._template = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if self.grayscale else img
        return True


def adaptive_scales(template_shape: Tuple[int, int], base_scales: List[float]) -> List[float]:
    """A compact scale pyramid tuned for sprites rather than general photographs.

    Six probes cover small renderings of big source crops and enlarged tiny icons.
    The old 7–10 probes per seed were expensive and still could miss ghosts smaller
    than the 36px native-template gate. Runtime matching now permits compact targets.
    """
    h, w = int(round(float(template_shape[0]))), int(round(float(template_shape[1])))
    side = max(h, w)
    if side <= 75:
        profile = [0.55, 0.75, 0.95, 1.25, 1.65, 2.10]
    elif side <= 130:
        profile = [0.35, 0.50, 0.70, 0.95, 1.30, 1.80]
    elif side <= 200:
        profile = [0.25, 0.38, 0.55, 0.78, 1.10, 1.55]
    else:
        profile = [0.16, 0.24, 0.34, 0.48, 0.68, 0.95, 1.35]
    values = list(profile)
    for value in list(base_scales or []):
        try:
            f = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(f) and 0.12 <= f <= 2.5 and all(abs(f - x) > 0.16 for x in profile):
            values.append(round(f, 3))
    return sorted(set(values))


class Library:
    def __init__(self, root: Path, cfg: Optional[Config] = None):
        self.root = root
        self.cfg = cfg or Config()
        self.seeds_dir = root / "seeds"
        self.ok_dir = root / "ok"
        self.learned_dir = root / "learned"
        self.templates_dir = self.learned_dir / "templates"
        self.index_file = self.learned_dir / "library.json"
        self.seeds_dir.mkdir(parents=True, exist_ok=True)
        self.ok_dir.mkdir(parents=True, exist_ok=True)
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.targets: Dict[str, Target] = {}
        self.blacklist: Dict[str, float] = {}    # "gx,gy" → expiry_ts
        self.visited: Dict[str, float] = {}      # "gx,gy" → last_visit_ts

    # -------- load --------
    def load(self):
        self.targets.clear()
        # learned metadata first
        if self.index_file.is_file():
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for t in data.get("targets", []):
                    obj = Target(**{k: v for k, v in t.items()
                                    if k in Target.__dataclass_fields__})
                    self.targets[obj.name] = obj
                self.blacklist = data.get("blacklist", {})
                self.visited = data.get("visited", {})
            except Exception as e:
                log.warning(f"Could not read library: {e}")

        # Seed pixels always come from ./seeds. Keep learned thresholds/evidence
        # from library.json, but refresh paths if the project folder was moved.
        for p in sorted(self.seeds_dir.glob("*")):
            if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp"):
                continue
            name = f"seed_{p.stem}"
            rel = p.relative_to(self.root).as_posix()
            if name in self.targets:
                self.targets[name].image_path = rel
                self.targets[name].source = "seed"
            else:
                # Alpha-masked sprites are easier to match across different
                # scene backgrounds; their thresholds use a separate score map.
                raw_seed = cv2.imread(str(p), cv2.IMREAD_UNCHANGED) if p.suffix.lower() == ".png" else None
                has_alpha = raw_seed is not None and raw_seed.ndim == 3 and raw_seed.shape[2] == 4
                self.targets[name] = Target(
                    name=name, image_path=rel, source="seed",
                    priority=20, cooldown=0.6,
                    threshold=max(0.65, self.cfg.base_threshold - (0.04 if has_alpha else 0.0)),
                    scales=list(self.cfg.base_scales))

        # load pixels
        loaded = []
        for t in list(self.targets.values()):
            if not t.load(self.root):
                log.warning(f"Missing image for '{t.name}': {t.image_path}")
                self.targets.pop(t.name, None)
            else:
                # A previously persisted conservative threshold (e.g. 0.89 from
                # an older build) must not permanently block first detections. Keep
                # response/reward-calibrated values, but reset unproven seed scores
                # to the current configured baseline and freshly computed floor.
                if t.source == "seed":
                    if t.total_rewards < 3 and not t.confirmed_scores:
                        t.threshold = max(float(self.cfg.base_threshold), float(t._threshold_floor))
                    h, w = t._template.shape[:2]
                    t.scales = adaptive_scales((h * t._scale_compensation, w * t._scale_compensation),
                                               self.cfg.base_scales)
                loaded.append(t)
        log.info(f"Library loaded: {len(loaded)} targets "
                 f"({sum(1 for t in loaded if t.source=='seed')} seeds, "
                 f"{sum(1 for t in loaded if t.source=='learned')} learned)")

    # -------- save --------
    def save(self):
        data = {
            "targets": [t.serialize() for t in self.targets.values()],
            "blacklist": self.blacklist,
            "visited": self.visited,
        }
        tmp = self.index_file.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(self.index_file)

    # -------- add learned --------
    def add_learned(self, crop: np.ndarray, threshold: float,
                    scales: List[float], mask: Optional[np.ndarray] = None) -> Optional[Target]:
        # Deduplicate by shape/texture AND color family. Grayscale dHash alone
        # collapses same-shape blue/cyan/purple variants, preventing color learning.
        h = dhash(crop)
        new_hue = dominant_hue_value(crop, mask)
        for t in self.targets.values():
            if t._hash and hamming(h, t._hash) <= 4:
                if hue_distance(new_hue, t._dominant_hue) <= 14.0:
                    log.debug("New template resembles '%s' in shape and hue; skipped", t.name)
                    return None
                log.info("Keeping a same-shape target with a new color family (%.0f vs %.0f hue)",
                         new_hue if new_hue is not None else -1,
                         t._dominant_hue if t._dominant_hue is not None else -1)
        name = f"learned_{time.strftime('%Y%m%d_%H%M%S')}_{hashlib.md5(str(time.time()).encode()).hexdigest()[:4]}"
        path = self.templates_dir / f"{name}.png"
        if mask is not None and mask.shape[:2] == crop.shape[:2]:
            rgba = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
            rgba[:, :, 3] = np.where(mask > 0, 255, 0).astype(np.uint8)
            cv2.imwrite(str(path), rgba)
        else:
            cv2.imwrite(str(path), crop)
        t = Target(
            name=name, image_path=path.relative_to(self.root).as_posix(), source="learned",
            threshold=threshold, scales=scales, priority=15, cooldown=0.6)
        if not t.load(self.root):
            return None
        self.targets[name] = t
        return t

    # -------- seed profile --------
    def seed_profile(self) -> Tuple[int, int, int, int]:
        ws, hs = [], []
        for t in self.targets.values():
            if t.source == "seed" and t._template is not None:
                hs_, ws_ = t._template.shape[:2]
                ws.append(ws_); hs.append(hs_)
        if not ws:
            return 30, 220, 20, 140
        return (max(20, int(min(ws) * 0.6)), int(max(ws) * 1.6),
                max(15, int(min(hs) * 0.6)), int(max(hs) * 1.6))


# ============================================================
# Safety
# ============================================================
class Safety:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.exclusions: List[List[int]] = [list(z) for z in cfg.exclusion_zones]
        self._click_times: deque = deque(maxlen=120)
        self.session_clicks = 0
        self.boost_cps = 0.0          # raised during a big wave

    def add_exclusion(self, x, y, w, h):
        self.exclusions.append([int(x), int(y), int(w), int(h)])
        self.cfg.exclusion_zones = [list(z) for z in self.exclusions]

    def in_exclusion(self, x, y) -> bool:
        for ex, ey, ew, eh in self.exclusions:
            if ex <= x <= ex + ew and ey <= y <= ey + eh:
                return True
        return False

    def can_click(self) -> bool:
        if self.cfg.max_session_clicks > 0 and self.session_clicks >= self.cfg.max_session_clicks:
            return False
        now = time.time()
        while self._click_times and now - self._click_times[0] > 1.0:
            self._click_times.popleft()
        return len(self._click_times) < max(self.cfg.max_cps, self.boost_cps)

    def note_click(self):
        self._click_times.append(time.time())
        self.session_clicks += 1


# ============================================================
# The bot
# ============================================================
class AutonomousBot:
    def __init__(self, cfg: Config, root: Path, dry_run: bool = False):
        cv2.setUseOptimized(True)
        cv2.setNumThreads(max(1, int(cfg.opencv_threads)))
        self.cfg = cfg
        self.root = root
        self.dry_run = bool(dry_run)
        self.sct = mss.mss() if HAS_MSS else None
        self.window = WindowCapture(cfg.window_title, cfg.window_client_only, cfg.window_process)
        # OCR/Ectoplaz confirmation is useful to the learner even when Discord posting
        # is disabled. The reporter owns a background OCR worker; its sender is a no-op
        # when no webhook is configured. Environment configuration takes precedence.
        self.reporter = None
        reporter_enabled, effective_webhook = should_start_reporter(
            self.cfg.webhook_url, bool(self.cfg.smart_ecto_confirm), WebhookReporter is not None)
        if reporter_enabled:
            try:
                self.reporter = WebhookReporter(effective_webhook, self.cfg.webhook_interval_s,
                                                max_plausible_gain=self.cfg.smart_ecto_max_gain)
                if effective_webhook:
                    log.info("Discord/Ectoplaz reporter initialized; webhook URL kept out of logs.")
                else:
                    log.info("Ectoplaz OCR confirmation enabled; Discord posting is disabled until a webhook is configured.")
            except Exception as e:
                log.error("Failed to initialize Ectoplaz/webhook reporter: %s", type(e).__name__)
        self._last_refind = 0.0
        self._last_focus_try = 0.0
        self._last_focus_log = 0.0
        self._last_cover_log = 0.0
        self._last_click_points: deque = deque(maxlen=64)
        self._last_saved_zones = [list(z) for z in cfg.exclusion_zones]
        self._consecutive_errors = 0
        self.library = Library(root, cfg)
        self.library.load()
        self.safety = Safety(cfg)

        mn, mx, _, _ = self.library.seed_profile()
        self.saliency = SaliencyDetector(*self.library.seed_profile(),
                                         max_dimension=min(800, cfg.match_max_dimension))
        log.info(f"Candidate size profile: {mn}..{mx}px wide")

        self.watchers: List[Watcher] = []
        self._load_watchers()
        self._any_popup_visible = False
        self.recent_clicks: deque = deque(maxlen=200)
        self.reward_stats = {"confirmed": 0, "unconfirmed": 0, "fires": 0}

        self.running = True
        self.paused = False
        self._stop = False
        self._reload = False
        self._zone_request = False

        self.last_match_time = time.time()
        self.last_explore_time = 0.0
        self.last_save = time.time()
        self.last_global_click = 0.0
        self.frames_seen = 0
        self.fps = 0.0
        self._fps_t = time.time()
        self._pending_feedback: deque = deque(maxlen=100)
        self._pending_discoveries: deque = deque(maxlen=12)
        self._last_stat_log = time.time()
        self._last_scan_thumbnail: Optional[np.ndarray] = None
        self._last_target_scan = 0.0
        self._last_proposal_scan = 0.0
        self._total_frames = 0
        self.control_file: Optional[Path] = None
        self._control_mtime_ns = -1
        self._control_state = {"stop": False, "paused": False}
        self._last_proposal_ms = 0.0
        self._last_template_ms = 0.0
        self._last_fast_match_ms = 0.0
        self._candidate_count = 0
        self._debug_proposals: List[Tuple[int, int, int, int, str]] = []
        self._last_perf_log = time.time()
        self._last_capture_warning = 0.0
        self._last_popup_block_log = 0.0
        self._last_proposal_diag = 0.0
        self._last_explore_gate_log = 0.0
        self._last_explore_diag = 0.0
        self._last_target_diag: Dict[str, float] = {}
        self._last_debug_write = 0.0
        self._debug_boxes: List[Tuple[int, int, int, int, str]] = []
        self._best_target_diagnostics: List[Tuple[str, float, float, int, int]] = []

        # Learn-from-my-clicks detector. Works in dry-run too: "Preview" then acts as a
        # pure teaching mode (the bot sends no input, it only watches the player).
        self.smart = None
        self._smart_boxes: List[Tuple[int, int, int, int, str]] = []
        self._last_smart_err = 0.0
        if cfg.smart_learning and SmartGhost is not None:
            try:
                self.smart = SmartGhost(root, cfg)
                if cfg.smart_use_seeds:
                    seeds = [(t._template_color, t._mask) for t in self.library.targets.values()
                             if t.source == "seed" and t._template_color is not None]
                    added = self.smart.seed_from_images(seeds)
                    if added:
                        log.info("SMART: bootstrapped with %d existing seed crop(s)", added)
                self.smart.start_listener()
            except Exception as exc:
                log.exception("SMART disabled, could not start: %s", exc)
                self.smart = None
        # Webhook toast reader -> smart learner: every Ectoplaz gain confirms (or fails to confirm) a click.
        if self.smart is not None and self.reporter is not None and cfg.smart_ecto_confirm:
            self.reporter.add_gain_listener(self.smart.on_ecto_gain)
            self.reporter.set_stats_provider(self.smart.stats_line)
            self.smart.feed_alive = self.reporter.feed_alive
            log.info("SMART: Ectoplaz toast confirmation linked (gains label bot clicks as real catches).")
        elif cfg.smart_learning:
            log.warning("smart_ghost.py not found next to main.py; click-learning disabled.")

        self.ghost_scene = None
        self._wave_clicks = 0
        self._wave_recent: deque = deque(maxlen=200)
        self._last_wave_pos: Optional[Tuple[int, int]] = None
        self._preview_ok = bool(cfg.ghost_preview)
        self.overlay = None
        self.teacher = None
        self._overlay_checked = False
        self._recent_picks: deque = deque(maxlen=24)     # (time, (x, y, w, h), p) of boxes the learner chose
        self._last_ghost_diag = 0.0
        self._ghost_raw_n = 0
        if cfg.ghost_scene and cfg.ghost_overlay and GhostOverlay is not None and sys.platform == "win32":
            try:
                ov = GhostOverlay()
                if ov.start():
                    self.overlay = ov
                    log.info("GHOSTS: on-screen labels ready (click-through; capture exclusion %s)",
                             "on" if ov.capture_excluded else "NOT available - will be tested")
                else:
                    log.warning("GHOSTS: on-screen overlay could not start; see ghost_preview instead.")
            except Exception as exc:
                log.warning("GHOSTS: on-screen overlay disabled: %s", exc)
        self._preview_placed = False
        self._last_preview = 0.0
        if cfg.ghost_scene and GhostScene is not None:
            try:
                self.ghost_scene = GhostScene(root, boss_min_frac=cfg.smart_boss_min_frac,
                                              wave_min_ghosts=cfg.wave_min_ghosts)
                log.info("GHOSTS: kind/colour labels + wave detection ON (wave = %d+ small ghosts)", cfg.wave_min_ghosts)
            except Exception as exc:
                log.warning("ghost labels disabled: %s", exc)
        elif cfg.ghost_scene:
            log.warning("ghost_classifier.py not found next to main.py; labels/waves disabled.")
        if (OverlayTeacher is not None and self.ghost_scene is not None
                and self.smart is not None and not cfg.smart_autoplay
                and (cfg.teach_gui or (self.overlay is not None and (cfg.overlay_teach or cfg.overlay_auto_learn)))):
            try:
                self.teacher = OverlayTeacher(cfg, self.smart, self.ghost_scene,
                                              keyboard if HAS_KEYBOARD else None,
                                              has_overlay=self.overlay is not None)
                log.info("GHOSTS: teaching ON (Teach window %s, F4 mode %s, overlay auto-learn %s)",
                         "available" if cfg.teach_gui else "off",
                         f"{cfg.hk_teach.upper()}" if (cfg.overlay_teach and self.overlay is not None) else "off",
                         "on" if (cfg.overlay_auto_learn and self.overlay is not None) else "off")
            except Exception as exc:
                log.warning("overlay teaching disabled: %s", exc)

        self.dismisser = None
        if getattr(cfg, "popup_dismiss", False):
            try:
                from popup_dismiss import PopupDismisser
                img = root / cfg.popup_dismiss_image
                if img.exists():
                    self.dismisser = PopupDismisser(img, threshold=cfg.popup_dismiss_threshold,
                                                    settle_s=cfg.popup_dismiss_settle_s)
                    log.info("POPUP auto-dismiss ready (%s)", img.name)
                else:
                    log.warning("POPUP auto-dismiss off: %s not found next to main.py", img.name)
            except Exception as exc:
                log.warning("POPUP auto-dismiss disabled: %s", exc)

    # ---------- reward watchers ----------
    def _load_watchers(self) -> None:
        self.watchers.clear()
        ok_dir = self.root / "ok"
        ok_dir.mkdir(parents=True, exist_ok=True)
        for p in sorted(ok_dir.iterdir()):
            if not p.is_file() or p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"):
                continue
            watcher = Watcher(
                name=p.stem,
                image_path=p.relative_to(self.root).as_posix(),
                threshold=self.cfg.watcher_threshold,
                scales=list(self.cfg.watcher_scales),
                cooldown=self.cfg.watcher_cooldown_s,
            )
            if watcher.load(self.root):
                self.watchers.append(watcher)
                log.info("watcher loaded: %s (%sx%s)", watcher.name,
                         watcher._template.shape[1], watcher._template.shape[0])
            else:
                log.warning("watcher image could not be loaded: %s", p)
        if self.watchers:
            log.info("%d reward watcher(s) loaded from ./ok/.", len(self.watchers))
        else:
            log.warning("No reward watchers in ./ok/; clicks cannot be confirmed by popup evidence yet.")

    def _check_watchers(self, frame: np.ndarray, rect: Dict[str, int], now: float, prepared=None):
        fired = []
        any_visible = False
        if not self.watchers:
            self._any_popup_visible = False
            return fired
        if prepared is None:
            prepared = prepare_match_frame(frame, self.cfg.match_max_dimension)
        gray, edges = prepared["gray"], prepared["edges"]
        for watcher in self.watchers:
            if watcher._template is None:
                continue
            roi = frame
            rx = ry = 0
            roi_gray, roi_edges = gray, edges
            if watcher.region and len(watcher.region) == 4:
                rx, ry, rw, rh = watcher.region
                rx, ry = max(0, int(rx)), max(0, int(ry))
                roi = frame[ry:ry + int(rh), rx:rx + int(rw)]
                roi_gray = gray[ry:ry + int(rh), rx:rx + int(rw)]
                roi_edges = edges[ry:ry + int(rh), rx:rx + int(rw)]
                if roi.size == 0:
                    watcher._visible = False
                    watcher._armed = True
                    continue
            matches = find_all_matches(
                roi, watcher._template, watcher.scales, watcher.threshold,
                watcher.grayscale, max_matches=1, mask=watcher._mask,
                precomputed_gray=roi_gray, precomputed_edges=roi_edges,
                template_color=watcher._template_color,
                precomputed_proc_gray=(prepared["proc_gray"] if not watcher.region else None),
                precomputed_proc_color=(prepared["proc_color"] if not watcher.region else None),
                precomputed_proc_edges=(prepared["proc_edges"] if not watcher.region else None),
                process_scale_override=(prepared["scale"] if not watcher.region else None),
                precomputed_proc_hsv=(prepared["proc_hsv"] if not watcher.region else None))
            if matches:
                any_visible = True
                watcher._visible = True
                watcher._last_score = float(matches[0][0])
                if watcher._armed and now - watcher._last_fired >= watcher.cooldown:
                    watcher._armed = False
                    watcher._last_fired = now
                    watcher._count += 1
                    self.reward_stats["fires"] += 1
                    log.info("WATCHER '%s' fired (#%d), score=%.3f",
                             watcher.name, watcher._count, watcher._last_score)
                    fired.append(watcher)
            else:
                watcher._visible = False
                watcher._armed = True
        self._any_popup_visible = any_visible
        return fired

    def _calibrate_threshold(self, target: Target) -> bool:
        """Tune only when reward-confirmed and unconfirmed scores are available."""
        pos = np.asarray(target.confirmed_scores[-100:], dtype=np.float32)
        neg = np.asarray(target.negative_scores[-100:], dtype=np.float32)
        if len(pos) < 3 or len(neg) < 3:
            return False
        positive_floor = float(np.percentile(pos, 10))
        negative_ceiling = float(np.percentile(neg, 90))
        if positive_floor <= negative_ceiling + 0.015:
            # Distributions overlap: don't invent a separating threshold.
            return False
        proposed = (positive_floor + negative_ceiling) / 2.0
        lower_bound = max(self.cfg.adaptive_threshold_min, target._threshold_floor)
        proposed = max(lower_bound, min(self.cfg.adaptive_threshold_max, proposed))
        proposed = max(target.threshold - 0.03, min(target.threshold + 0.03, proposed))
        if abs(proposed - target.threshold) < 0.005:
            return False
        old = target.threshold
        target.threshold = float(proposed)
        target._dirty = True
        log.info("[%s] reward-calibrated threshold %.3f -> %.3f (n+%d / n-%d)",
                 target.name, old, target.threshold, len(pos), len(neg))
        return True

    def _calibrate_response_threshold(self, target: Target) -> bool:
        """Raise a target's threshold only when persistent click-response evidence separates.

        Pixel change is weaker than a reward popup, so this path requires at least
        five observations in each class, a clear percentile gap, a strict seed-derived
        floor, and a maximum 0.01 adjustment per update. It never lowers a threshold.
        """
        pos = np.asarray(target.response_scores[-100:], dtype=np.float32)
        neg = np.asarray(target.no_response_scores[-100:], dtype=np.float32)
        if len(pos) < 5 or len(neg) < 5:
            return False
        positive_floor = float(np.percentile(pos, 20))
        no_response_ceiling = float(np.percentile(neg, 80))
        if positive_floor <= no_response_ceiling + 0.02:
            return False
        proposed = (positive_floor + no_response_ceiling) / 2.0
        lower_bound = max(self.cfg.adaptive_threshold_min, target._threshold_floor)
        proposed = max(lower_bound, min(self.cfg.adaptive_threshold_max, proposed))
        proposed = max(target.threshold, min(target.threshold + 0.01, proposed))
        if proposed - target.threshold < 0.005:
            return False
        old = target.threshold
        target.threshold = float(proposed)
        target._dirty = True
        log.info("[%s] response-calibrated threshold %.3f -> %.3f (n-response=%d / n-no-response=%d)",
                 target.name, old, target.threshold, len(pos), len(neg))
        return True


    def _apply_rewards(self, fired: List[Watcher], now: float) -> None:
        if not fired:
            return
        # One visible popup event can be matched by multiple near-duplicate
        # watcher templates. Count the event once to avoid double-crediting.
        fired.sort(key=lambda w: w._last_score, reverse=True)
        watcher = fired[0]
        eligible = [c for c in reversed(self.recent_clicks)
                    if not c["confirmed"] and 0 <= now - c["ts"] <= self.cfg.reward_window_s]
        if not eligible:
            log.info("watcher '%s' fired with no recent click to confirm.", watcher.name)
            return
        record = eligible[0]
        record["confirmed"] = True
        target = self.library.targets.get(record["target"])
        if target is None:
            return
        target.total_rewards += 1
        target.confirmed_scores.append(float(record["score"]))
        target.confirmed_scores = target.confirmed_scores[-100:]
        target.priority = min(100, target.priority + 1)
        self.reward_stats["confirmed"] += 1
        log.info("CONFIRMED click=%s score=%.3f watcher=%s rewards=%d",
                 target.name, record["score"], watcher.name, target.total_rewards)
        self._calibrate_threshold(target)
        self.library.save()  # persistence at the point of confirmed learning

    def _sweep_unconfirmed(self, now: float) -> None:
        if not self.watchers:
            return
        for record in list(self.recent_clicks):
            if record["confirmed"]:
                continue
            if now - record["ts"] < self.cfg.reward_window_s:
                break  # deque is chronological
            record["confirmed"] = True
            self.reward_stats["unconfirmed"] += 1
            target = self.library.targets.get(record["target"])
            if target is None:
                continue
            target.total_misses += 1
            target.negative_scores.append(float(record["score"]))
            target.negative_scores = target.negative_scores[-100:]
            target._dirty = True
            self._calibrate_threshold(target)

    # ---------- control ----------
    def stop(self): self._stop = True
    def toggle_pause(self):
        self.paused = not self.paused
        log.info(f"{'PAUSED' if self.paused else 'RUNNING'}")
    def request_reload(self): self._reload = True
    def request_zone(self): self._zone_request = True

    # ---------- capture ----------
    def _auto_focus(self, now: float, why: str) -> None:
        """Bring Highrise back by itself (rate-limited) instead of stalling until a human does."""
        if not self.cfg.auto_focus_game or now - self._last_focus_try < self.cfg.focus_retry_s:
            return
        self._last_focus_try = now
        ok = self.window.focus()
        if now - self._last_focus_log >= 5.0 or ok:
            log.info("AUTO-FOCUS: %s -> %s", why, "Highrise is in front" if ok else "Windows refused; will retry")
            self._last_focus_log = now

    def _capture(self):
        if self.sct is None:
            raise RuntimeError("mss is required for capture. Install dependencies with: pip install mss")
        win = self.window
        if win.targeting and HAS_WIN32:
            now = time.time()
            if (not win.is_alive()) or now - self._last_refind >= self.cfg.window_refind_interval_s:
                self._last_refind = now
                previous = win.hwnd
                if not win.find():
                    return None, None
                if win.hwnd != previous:
                    log.info("TARGET WINDOW %s hwnd=%s pid=%s", win.last_status, win.hwnd, win.pid)
            rect = win.get_rect()
            if rect is None:
                if win.is_minimized():
                    self._auto_focus(now, "Highrise is minimized")
                return None, None
            if self.cfg.capture_method != "printwindow" and not win.usable_for_screen_capture(rect):
                self._auto_focus(now, "Highrise is covered by another window")
                return None, None
            previous_rect = getattr(self, "_last_capture_rect", None)
            current = (rect["left"], rect["top"], rect["width"], rect["height"])
            if previous_rect != current:
                log.info("CAPTURE WINDOW rect=left:%d top:%d width:%d height:%d client_only=%s",
                         rect["left"], rect["top"], rect["width"], rect["height"], win.client_only)
                self._last_capture_rect = current
            if self.cfg.capture_method == "printwindow":
                try:
                    return rect, capture_window_printwindow(win.hwnd, rect)
                except Exception as exc:
                    log.debug("PrintWindow capture failed; falling back to screen capture: %s", exc)
            return rect, capture_region_screen(self.sct, rect)

        if win.targeting and not HAS_WIN32 and sys.platform == "win32":
            # Fail closed on Windows: monitor-wide capture can include the bot's
            # own GUI or unrelated windows.
            raise RuntimeError(
                "Safe window-only capture unavailable: pywin32 is missing. "
                "Run: py -m pip install pywin32"
            )
        monitors = self.sct.monitors
        index = int(self.cfg.monitor_index)
        if not 0 <= index < len(monitors):
            index = 1 if len(monitors) > 1 else 0
        m = monitors[index]
        rect = {"left": m["left"], "top": m["top"], "width": m["width"], "height": m["height"]}
        return rect, capture_region_screen(self.sct, rect)

    # ---------- main loop ----------
    def run(self):
        if self.sct is None:
            raise RuntimeError("Screen capture dependency missing. Install requirements.txt first.")
        cv2.setUseOptimized(True)
        cv2.setNumThreads(int(self.cfg.opencv_threads))
        log.info("Vision runtime: OpenCV threads=%d, max scan dimension=%d, fast scan every frame=%s, rotating template budget=%d/frame, proposal peaks/scale=%d",
                 self.cfg.opencv_threads, self.cfg.match_max_dimension, self.cfg.scan_every_frame,
                 self.cfg.template_targets_per_frame, self.cfg.proposal_peaks_per_scale)
        log.info("Runtime dependencies: Windows=%s MSS=%s pywin32=%s pydirectinput=%s keyboard=%s; OpenCV CUDA available=%s",
                 sys.platform == "win32", HAS_MSS, HAS_WIN32, HAS_DIRECT_INPUT, HAS_KEYBOARD,
                 bool(hasattr(cv2, "cuda") and cv2.cuda.getCudaEnabledDeviceCount() > 0))
        log.info("Library readiness: targets=%d seeds=%d learned=%d watchers=%d; auto_learning=%s",
                 len(self.library.targets), sum(t.source == "seed" for t in self.library.targets.values()),
                 sum(t.source != "seed" for t in self.library.targets.values()), len(self.watchers),
                 not self.cfg.patient_mode)
        if not self.dry_run and not HAS_DIRECT_INPUT:
            raise RuntimeError("pydirectinput is required for live clicks. Install requirements.txt.")
        if self.window.targeting:
            if not HAS_WIN32:
                log.warning("pywin32 missing — window capture will fail closed; run: py -m pip install pywin32")
            elif not self.window.find():
                log.warning("%s — the bot keeps running and will attach the moment the game appears.", self.window.last_status)
            else:
                initial_rect = self.window.get_rect()
                if initial_rect is None:
                    log.warning("CAPTURE NOT READY: %s (will auto-recover)", self.window.last_status)
                else:
                    log.info("CAPTURE READY: %s hwnd=%s pid=%s client=%dx%d",
                             self.window.last_status, self.window.hwnd, self.window.pid,
                             initial_rect["width"], initial_rect["height"])

        mode = "AUTO PLAY (NO TRAINING)" if self.cfg.smart_autoplay else ("PATIENT" if self.cfg.patient_mode else "AUTO-LEARN")
        log.info("Running in %s mode. F9 pause, F7 exclusions, F10 reload, F12 quit.", mode)
        log.info("Input mode: %s", "DRY RUN (NO CLICKS SENT)" if self.dry_run else "LIVE INPUT ENABLED")
        if self.smart is not None and self.cfg.smart_autoplay:
            st = self.smart.status()
            log.info("SMART AUTO PLAY: using the saved model (%d positives / %d negatives on disk). Learning is OFF.",
                     st["positives"], st["negatives"])
        elif self.smart is not None:
            st = self.smart.status()
            log.info("SMART click-learning ON: %d learned ghosts, %d negatives, model=%s. Click ghosts yourself "
                     "to teach it; it starts acting at %d learned ghosts%s. F8 = 'that last bot click was wrong'.",
                     st["positives"], st["negatives"], "trained" if st["model"] else "not trained yet",
                     self.cfg.smart_min_positives, "" if self.cfg.smart_clicking else " (clicking disabled: teach-only)")
        if self.dry_run:
            log.warning("DRY RUN: detections will be logged; no input events will be sent.")
        if not self.library.targets:
            log.warning("No seed/learned targets found. Add tightly-cropped images to ./seeds/.")

        while not self._stop:
            self._poll_control_file()
            if self._zone_request:
                self._zone_request = False
                self._draw_zone()
                continue
            if self._reload:
                self._reload = False
                self._do_reload()
                continue
            if self.paused:
                time.sleep(0.1)
                continue
            try:
                self._tick()
                self._consecutive_errors = 0
            except Exception as exc:
                # Never let one bad frame end the session; back off if it keeps failing.
                self._consecutive_errors += 1
                if self._consecutive_errors <= 3 or self._consecutive_errors % 50 == 0:
                    log.exception("tick error #%d (continuing): %s", self._consecutive_errors, exc)
                time.sleep(min(2.0, 0.25 * self._consecutive_errors))
            now = time.time()
            if now - self.last_save >= self.cfg.save_interval_s:
                self._persist()
                self.last_save = now
            if now - self._last_stat_log >= 30.0:
                log.info("stats: confirmed=%d unconfirmed=%d watcher_fires=%d fps=%.1f clicks=%d",
                         self.reward_stats["confirmed"], self.reward_stats["unconfirmed"],
                         self.reward_stats["fires"], self.fps, self.safety.session_clicks)
                self._last_stat_log = now
                if self.smart is not None:
                    st = self.smart.status()
                    log.info("smart: learned=%d negatives=%d ready=%s your_clicks=%d bot_clicks=%d metrics=%s",
                             st["positives"], st["negatives"], st["ready"], st["user_clicks"],
                             st["smart_clicks"], st["metrics"])
                    hr = st.get("hit_rate")
                    log.info("ecto: gains=%d (bot=%d you=%d unmatched=%d) strong_pos=%d aim_misses=%d retries=%d "
                             "hit_rate=%s thr=%.3f", st["ecto_gains"], st["ecto_bot"], st["ecto_user"],
                             st["ecto_unattributed"], st["ecto_positives"], st["aim_misses"], st["retries"],
                             "n/a" if hr is None else f"{hr:.0%}", st["threshold"])

        self._persist()
        if self.smart is not None:
            self.smart.stop()
        if self.teacher is not None:
            self.teacher.shutdown()
        if self.overlay is not None:
            self.overlay.stop()
        log.info("Saved and stopped.")

    def _persist(self) -> None:
        """Save learned targets; rewrite config.json only if the bot itself changed it
        (new exclusion zone). Rewriting it blindly would wipe settings saved in the GUI."""
        try:
            self.library.save()
        except Exception as exc:
            log.warning("library save failed (will retry): %s", exc)
        try:
            zones = [list(z) for z in self.safety.exclusions]
            if zones != self._last_saved_zones:
                path = self.root / "config.json"
                try:
                    disk = load_config(path)
                except Exception:
                    disk = self.cfg
                disk.exclusion_zones = zones
                save_config(path, disk)
                self._last_saved_zones = zones
        except Exception as exc:
            log.warning("config save failed (will retry): %s", exc)

    def _tick(self):
        tick_started = time.perf_counter()
        rect, frame = self._capture()
        if frame is None or rect is None:
            now = time.time()
            last_warn = getattr(self, "_last_capture_warning", 0.0)
            if now - last_warn >= 3.0:
                title = getattr(getattr(self, "window", None), "title", self.cfg.window_title)
                reason = getattr(getattr(self, "window", None), "last_status", "capture returned no frame")
                log.warning("CAPTURE WAIT: %s. The bot keeps running, restores Highrise automatically and clicks only on a verified game frame.", reason)
                self._last_capture_warning = now
            time.sleep(0.08)
            self._emit_performance(now, tick_started)
            return

        self._last_capture_warning = 0.0
        self.frames_seen += 1
        self._total_frames += 1
        now = time.time()
        if now - self._fps_t >= 1.0:
            self.fps = self.frames_seen / max(1e-6, now - self._fps_t)
            self.frames_seen = 0
            self._fps_t = now

        # The color/shape proposal pass runs each frame. Exact full-screen matching
        # is split into a rotating target batch so 60+ templates never block one
        # tick for multiple seconds. The cursor advances every captured frame; a
        # no-candidate frame checks the next one or few templates as a recovery path.
        target_values = list(self.library.targets.values())
        target_count = len(target_values)
        template_budget = max(1, min(8, int(getattr(self.cfg, "template_targets_per_frame", 1))))
        template_batch = []
        if target_values:
            cursor = int(getattr(self, "_template_scan_cursor", 0)) % len(target_values)
            for offset in range(min(template_budget, len(target_values))):
                template_batch.append(target_values[(cursor + offset) % len(target_values)])
            self._template_scan_cursor = (cursor + len(template_batch)) % len(target_values)
        template_cycle_frames = max(1, int(np.ceil(target_count / max(1, template_budget))))
        # Once the learned model is ready and exclusive, exact template matching
        # is not used for click decisions. Avoid preparing full-size gray/edge maps
        # for work that will be thrown away; this can save a material amount of CPU.
        smart_owns_selection = smart_exclusive_active(self.cfg, self.smart)
        should_scan_templates = bool(template_batch) and not smart_owns_selection
        if self.cfg.scan_every_frame:
            should_scan_proposals = True
        else:
            thumb = cv2.resize(frame, (80, 45), interpolation=cv2.INTER_AREA)
            changed = (self._last_scan_thumbnail is None or
                       cv2.absdiff(thumb, self._last_scan_thumbnail).mean() >= 1.0)
            timed = now - self._last_proposal_scan >= self.cfg.unchanged_rescan_interval_s
            should_scan_proposals = bool(changed or timed)
            if should_scan_proposals:
                self._last_scan_thumbnail = thumb
        should_scan_watchers = (
            self._total_frames == 1 or self._total_frames % self.cfg.watcher_interval_frames == 0
            or self._any_popup_visible
        )
        prepared = None
        if should_scan_templates or should_scan_watchers:
            prepared = prepare_match_frame(frame, self.cfg.match_max_dimension)
        if should_scan_watchers:
            fired = self._check_watchers(frame, rect, now, prepared=prepared)
            if fired:
                self._apply_rewards(fired, now)
        self._sweep_unconfirmed(now)
        self._update_pending_feedback(frame, now)
        self._process_pending_discoveries(frame, now)

        if self.dismisser is not None and self.dismisser.update(frame, rect, now, self._script_click):
            if self.ghost_scene is not None and self.ghost_scene.wave_active:
                self.ghost_scene.end_wave(now, reason="popup: reward received")
                self._wave_clicks = 0
            self._smart_feed(frame, rect, now, None, popup=True)    # nothing is learned from this frame
            self._emit_performance(now, tick_started)
            self._write_debug_overlay(frame)
            time.sleep(max(self.cfg.loop_delay, 0.005))
            return

        if self.cfg.skip_click_while_popup and self._any_popup_visible:
            last_popup_log = getattr(self, "_last_popup_block_log", 0.0)
            if now - last_popup_log >= 2.0:
                visible = [w.name for w in self.watchers if getattr(w, "_visible", False)]
                log.warning("CLICK BLOCKED: confirmation watcher visible (%s); disable popup blocking only if this is a false positive.", ", ".join(visible) or "watcher")
                self._last_popup_block_log = now
            self._smart_feed(frame, rect, now, None, popup=True)
            self._emit_performance(now, tick_started)
            self._write_debug_overlay(frame)
            time.sleep(max(self.cfg.loop_delay, 0.005))
            return

        proposal_boxes = []
        self._debug_proposals = []
        if should_scan_proposals:
            t0 = time.perf_counter()
            proposal_boxes = self._candidate_boxes(frame)
            self._last_proposal_scan = now
            self._last_proposal_ms = (time.perf_counter() - t0) * 1000.0
            self._candidate_count = len(proposal_boxes)
            self._debug_proposals = [
                (int(x), int(y), int(w), int(h), f"candidate {score:.2f}")
                for score, x, y, w, h in proposal_boxes[:15]
            ]
            if now - getattr(self, "_last_proposal_diag", 0.0) >= max(0.5, self.cfg.debug_score_interval_s):
                top = "; ".join(f"{int(x)},{int(y)} {int(w)}x{int(h)} s={score:.2f}"
                                 for score, x, y, w, h in proposal_boxes[:8])
                log.debug("PROPOSALS count=%d elapsed_ms=%.1f top=[%s]", len(proposal_boxes),
                          self._last_proposal_ms, top or "none")
                self._last_proposal_diag = now
        else:
            self._candidate_count = 0

        action = False
        self._last_template_ms = 0.0
        # Learned detector: feeds every frame (so it can learn from the player's clicks) and,
        # once trained, picks ghosts itself. When exclusive it replaces the seed paths below.
        smart_took_over = False
        self._smart_feed(frame, rect, now, proposal_boxes, popup=False)
        wave_took_over = False
        scene = self._update_ghost_scene(frame, now, rect)
        if scene is not None and scene.wave and self.cfg.wave_click_all:
            self.safety.boost_cps = float(self.cfg.wave_max_cps)
            action = self._wave_click(rect, now)
            wave_took_over = bool(action)     # no small ghost left (e.g. only a boss): normal clicking continues
        else:
            self.safety.boost_cps = 0.0
        if wave_took_over:
            smart_took_over = True      # nothing else clicks while the wave is being cleared
        elif (self.smart is not None and self.cfg.smart_clicking and self.smart.ready()):
            smart_took_over = bool(self.cfg.smart_exclusive)
            action = self._smart_click(frame, rect, now)
        if proposal_boxes and not smart_took_over:
            t0 = time.perf_counter()
            action = self._match_fast_candidates(frame, rect, now, proposal_boxes)
            self._last_fast_match_ms = (time.perf_counter() - t0) * 1000.0
        else:
            self._last_fast_match_ms = 0.0

        # Full-frame correlation is now bounded to a rotating subset of templates.
        # It runs only when the fast path did not act; the cursor still advances on
        # every valid frame so the whole library is visited regularly without a
        # five-second hitch from matching every template at once.
        if not action and should_scan_templates and not smart_took_over:
            self._last_target_scan = now
            t0 = time.perf_counter()
            action = self._match_and_click(frame, rect, now, prepared=prepared, targets=template_batch)
            self._last_template_ms = (time.perf_counter() - t0) * 1000.0

        # Explore only after a quiet interval without a known exact match. The
        # exploration itself never sleeps for the learning delay; feedback is
        # checked asynchronously in later frames.
        last_exact = getattr(self, "_last_exact_match_time", getattr(self, "last_match_time", now))
        quiet_for = now - last_exact
        if (not action and not smart_took_over and not self.cfg.patient_mode and should_scan_proposals
                and quiet_for > self.cfg.explore_after_idle_s
                and now - self.last_explore_time >= self.cfg.explore_cooldown_s):
            self.last_explore_time = now
            action = self._explore_once(frame, rect, candidates=proposal_boxes)
        elif (not action and not smart_took_over and not self.cfg.patient_mode and should_scan_proposals
              and now - getattr(self, "_last_explore_gate_log", 0.0) >= 3.0):
            log.debug("EXPLORATION WAIT: known-target quiet timer %.2fs / %.2fs; proposals=%d",
                      quiet_for, self.cfg.explore_after_idle_s, len(proposal_boxes))
            self._last_explore_gate_log = now

               # Refresh the annotated frame after proposal/exploration processing so
        # it visualizes the same candidates and click decision shown in the log.
        self._write_debug_overlay(frame)
        
        # Report Ectoplaz total to Discord every N seconds
        if self.reporter is not None:
            self.reporter.check_and_report(frame)
        
        self._emit_performance(now, tick_started, template_cycle_frames)
        time.sleep(max(0.0, self.cfg.loop_delay))

    def _emit_performance(self, now: float, tick_started: float, template_interval: int | None = None) -> None:
        """Rate-limited runtime telemetry consumed by both logs and the GUI."""
        last = getattr(self, "_last_perf_log", 0.0)
        if now - last < 2.0:
            return
        self._last_perf_log = now
        elapsed_ms = max(0.0, (time.perf_counter() - tick_started) * 1000.0)
        interval = template_interval or max(1, int(getattr(self.cfg, "template_targets_per_frame", 1)))
        log.info("PERF fps=%.1f tick_ms=%.1f proposal_ms=%.1f fast_match_ms=%.1f template_ms=%.1f candidates=%d targets=%d template_cycle_frames=%d clicks=%d",
                 float(getattr(self, "fps", 0.0)), elapsed_ms,
                 float(getattr(self, "_last_proposal_ms", 0.0)),
                 float(getattr(self, "_last_fast_match_ms", 0.0)),
                 float(getattr(self, "_last_template_ms", 0.0)),
                 int(getattr(self, "_candidate_count", 0)),
                 len(getattr(getattr(self, "library", None), "targets", {})), interval,
                 int(getattr(getattr(self, "safety", None), "session_clicks", 0)))

    def _local_masked_template_score(self, frame: np.ndarray, x: int, y: int, w: int, h: int,
                                     target: Target) -> float:
        """Check a few sizes around a proposed box with an alpha/foreground mask.

        This tiny local search is a fallback when outline segmentation is confused
        by same-colored scenery. It never searches the whole screen and therefore
        avoids the expensive full-frame multiscale correlation pass.
        """
        template = getattr(target, "_template_color", None)
        mask0 = getattr(target, "_mask", None)
        if template is None or mask0 is None or min(w, h) < 12:
            return 0.0
        th, tw = template.shape[:2]
        if min(th, tw) < 8:
            return 0.0
        center_x, center_y = x + w / 2.0, y + h / 2.0
        fit_scale = min(w / max(1, tw), h / max(1, th))
        best = 0.0
        # Small scale neighborhood handles glow/bounding-box padding without
        # turning one proposal into an expensive open-ended search.
        for factor in (1.0, 0.92, 1.08):
            rw = max(12, int(round(tw * fit_scale * factor)))
            rh = max(12, int(round(th * fit_scale * factor)))
            if rw > frame.shape[1] or rh > frame.shape[0]:
                continue
            left = int(round(center_x - rw / 2.0))
            top = int(round(center_y - rh / 2.0))
            left = min(max(0, left), frame.shape[1] - rw)
            top = min(max(0, top), frame.shape[0] - rh)
            roi = frame[top:top + rh, left:left + rw]
            resized = cv2.resize(template, (rw, rh), interpolation=cv2.INTER_AREA if fit_scale * factor < 1 else cv2.INTER_LINEAR)
            mask = cv2.resize(mask0, (rw, rh), interpolation=cv2.INTER_NEAREST)
            if mask.ndim == 3:
                mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
            mask = np.where(mask > 0, 255, 0).astype(np.uint8)
            try:
                result = cv2.matchTemplate(roi, resized, cv2.TM_CCORR_NORMED, mask=mask)
                score = float(result.max()) if result.size else 0.0
            except cv2.error:
                continue
            if np.isfinite(score):
                best = max(best, score)
                if best >= 0.93:
                    break
        return best

    def _match_fast_candidates(self, frame: np.ndarray, rect: Dict[str, int], now: float,
                               proposals: List[Tuple[float, int, int, int, int]]) -> bool:
        """Match the current frame's compact proposals against target shape + hue.

        This is the primary low-latency click path. Unlike full-screen multi-scale
        cross-correlation, it verifies a few small candidate crops and can run on
        every frame. The expensive exhaustive matcher is only a recovery pass.
        Returns True when a known target was positively identified, even if a
        cooldown suppresses the physical click; that prevents a needless full scan.
        """
        if frame is None or not proposals or not self.library.targets:
            return False

        ranked = []
        saw_known_target = False
        original_frame = frame
        original_h, original_w = frame.shape[:2]
        process_dimension = max(480, min(800, int(getattr(self.cfg, "match_max_dimension", 800))))
        process_scale = min(1.0, process_dimension / max(original_w, original_h))
        scan_frame = frame if process_scale >= 0.999 else cv2.resize(
            frame, (max(1, int(round(original_w * process_scale))),
                    max(1, int(round(original_h * process_scale)))),
            interpolation=cv2.INTER_AREA)
        # Group templates by near-identical hue once per frame. Bloop imports can
        # contain dozens of files, often several variants per color; one mask per
        # hue family is far cheaper than one mask per image/template.
        hue_groups: List[Tuple[float, List[Target]]] = []
        target_values = []
        for target in self.library.targets.values():
            if target._template is None or getattr(target, "_shape_contour", None) is None:
                continue
            seed_hue = getattr(target, "_color_median_hue", None)
            if seed_hue is None:
                seed_hue = getattr(target, "_dominant_hue", None)
            if seed_hue is None or not np.isfinite(seed_hue):
                continue
            target_values.append((float(seed_hue) % 180.0, target))
        target_values.sort(key=lambda item: item[0])
        for seed_hue, target in target_values:
            group = next((g for g in hue_groups if hue_distance(g[0], seed_hue) <= 2.5), None)
            if group is None:
                hue_groups.append((seed_hue, [target]))
            else:
                group[1].append(target)

        max_template_side = max((max(t._template.shape[:2]) for _, t in target_values), default=268)
        known_max_side = max(280, min(360, int(max_template_side * 1.3)))
        min_side = max(int(self.cfg.min_match_side_px), int(getattr(self.cfg, "fast_min_candidate_side_px", 24)))
        eligible = [(score, x, y, w, h) for score, x, y, w, h in proposals[:80]
                    if min(w, h) >= min_side and max(w, h) <= known_max_side]
        # Bounded rotating shortlist keeps the per-frame CPU budget predictable,
        # while every proposal is revisited over successive captured frames.
        budget = max(4, int(getattr(self.cfg, "fast_proposals_per_frame", 8)))
        if len(eligible) > budget:
            cursor = int(getattr(self, "_fast_proposal_cursor", 0)) % len(eligible)
            batch = eligible[cursor:cursor + budget]
            if len(batch) < budget:
                batch.extend(eligible[:budget - len(batch)])
            self._fast_proposal_cursor = (cursor + budget) % len(eligible)
        else:
            batch = eligible
            self._fast_proposal_cursor = 0
        for saliency_score, orig_x, orig_y, orig_w, orig_h in batch:
            x = int(round(orig_x * process_scale))
            y = int(round(orig_y * process_scale))
            w = max(1, int(round(orig_w * process_scale)))
            h = max(1, int(round(orig_h * process_scale)))
            if min(w, h) < 12:
                continue
            pad = max(3, int(round(min(w, h) * 0.08)))
            x0, y0 = max(0, x - pad), max(0, y - pad)
            x1, y1 = min(scan_frame.shape[1], x + w + pad), min(scan_frame.shape[0], y + h + pad)
            crop = scan_frame[y0:y1, x0:x1]
            if crop.size == 0 or min(crop.shape[:2]) < 16:
                continue
            crop_aspect = crop.shape[1] / max(1, crop.shape[0])
            crop_hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            crop_hue, crop_sat, crop_val = cv2.split(crop_hsv)
            crop_area = crop.shape[0] * crop.shape[1]
            colored = (crop_sat >= 32) & (crop_val >= 40)
            hue_hist = np.bincount(crop_hue[colored], minlength=180).astype(np.float32)
            hue_support = np.zeros_like(hue_hist)
            for shift in range(-8, 9):
                hue_support += np.roll(hue_hist, shift)
            viable_groups = []
            for group_hue, group_targets in hue_groups:
                support = float(hue_support[int(round(group_hue)) % 180])
                if support >= max(24.0, crop_area * 0.025):
                    viable_groups.append((support, group_hue, group_targets))
            # Most candidates have one salient hue. Three hue groups are enough
            # to handle a body + glow/face while keeping large-corpus frame cost low.
            viable_groups.sort(key=lambda item: item[0], reverse=True)
            decisive = False
            for _support, group_hue, group_targets in viable_groups[:3]:
                candidate_mask, candidate_hue = quick_hue_mask(crop, expected_hue=group_hue, hsv=crop_hsv)
                contour = _mask_contour(candidate_mask)
                if contour is None or candidate_hue is None:
                    continue
                for target in group_targets:
                    seed_hue = getattr(target, "_color_median_hue", None)
                    if seed_hue is None:
                        seed_hue = getattr(target, "_dominant_hue", None)
                    target_contour = getattr(target, "_shape_contour", None)
                    if seed_hue is None or target_contour is None:
                        continue
                    hue_delta = hue_distance(candidate_hue, seed_hue)
                    if hue_delta > 8.0:
                        continue
                    target_h, target_w = target._template.shape[:2]
                    aspect_ratio = (target_w / max(1, target_h)) / max(1e-6, crop_aspect)
                    if not 0.68 <= aspect_ratio <= 1.48:
                        continue
                    try:
                        shape_distance = float(cv2.matchShapes(
                            target_contour, contour, cv2.CONTOURS_MATCH_I1, 0.0))
                    except cv2.error:
                        continue
                    uncertain = (not np.isfinite(shape_distance) or shape_distance > 0.05 or hue_delta > 4.0)
                    if uncertain:
                        # A permissive shape-only gate can mistake blue clothing or
                        # scenery for a cyan ghost. The local fallback is specifically
                        # for near-proportional sprites; odd aspect ratios still get
                        # the exhaustive template recovery pass rather than a risky click.
                        if not 0.82 <= aspect_ratio <= 1.16:
                            continue
                        # Cache whether the target itself has the ghost-face signature.
                        # For these templates, require the candidate crop to retain
                        # that feature too; clothing with a similar hue/outline is not
                        # enough. Non-face templates keep the local-template fallback.
                        face_signature = getattr(target, "_face_signature", None)
                        if face_signature is None:
                            face_signature = self._looks_like_unseen_ghost_form(
                                target._template_color, target._mask)
                            target._face_signature = bool(face_signature)
                        if face_signature and not self._looks_like_unseen_ghost_form(crop, candidate_mask):
                            continue
                        template_score = self._local_masked_template_score(scan_frame, x, y, w, h, target)
                        # Require close masked pixel agreement if outline/color isn't
                        # decisive. This rejects same-hue UI decorations and scenery.
                        if template_score < 0.96:
                            continue
                        similarity = float(0.78 + min(0.20, (template_score - 0.78) * 0.90))
                    else:
                        similarity = float(1.0 - 0.80 * shape_distance - 0.005 * hue_delta)
                    if similarity < max(0.86, float(target.threshold) - 0.02):
                        continue
                    saw_known_target = True
                    ranked.append((similarity + min(2.0, max(0.0, saliency_score)) * 0.002,
                                   similarity, target, int(orig_x), int(orig_y), int(orig_w), int(orig_h),
                                   hue_delta, shape_distance))
                    if similarity >= 0.94:
                        decisive = True
                        break
                if decisive:
                    break
            if decisive:
                # The fast path dispatches only one click/frame. Use the newly
                # captured frame next iteration rather than verifying stale boxes.
                break

        if not ranked:
            return False
        ranked.sort(key=lambda r: (r[0], r[1], r[2].priority), reverse=True)
        recent_now = now
        chosen = None
        for item in ranked:
            _rank, similarity, target, x, y, w, h, hue_delta, shape_distance = item
            cx, cy = x + w // 2, y + h // 2
            if self.safety.in_exclusion(cx, cy):
                continue
            target._recent_locations = [p for p in target._recent_locations
                                        if recent_now - p[2] < self.cfg.same_location_cooldown_s]
            suppress_radius = max(8.0, min(w, h) * 0.42)
            if any((cx - px) ** 2 + (cy - py) ** 2 < suppress_radius ** 2
                   for px, py, _ts in target._recent_locations):
                continue
            chosen = (similarity, target, x, y, w, h, cx, cy, hue_delta, shape_distance)
            break

        if chosen is None:
            log.debug("FAST MATCH: known ghost target(s) detected but all candidate locations are in cooldown")
            return saw_known_target

        similarity, target, x, y, w, h, cx, cy, hue_delta, shape_distance = chosen
        # Ranked box coordinates are back in the original captured-frame space;
        # do not divide by process_scale a second time (that shifted diagnostic
        # rectangles off-screen on 1080p+ captures).
        self._debug_boxes.append((int(x), int(y), int(w), int(h),
                                  f"FAST {target.name} {similarity:.2f}/{target.threshold:.2f}"))
        log.info("TARGET DETECTED source=fast target=%s screen=(%d,%d) score=%.3f threshold=%.3f",
                 target.name, rect["left"] + cx, rect["top"] + cy, similarity, target.threshold)
        log.debug("FAST MATCH target=%s score=%.3f hue_delta=%.1f shape_distance=%.3f frame=(%d,%d) size=%dx%d",
                  target.name, similarity, hue_delta, shape_distance, cx, cy, w, h)

        if now - self.last_global_click < self.cfg.global_cooldown:
            log.debug("CLICK THROTTLED: fast target=%s remaining=%.3fs", target.name,
                      self.cfg.global_cooldown - (now - self.last_global_click))
            self._write_debug_overlay(frame)
            return True
        abs_x, abs_y = rect["left"] + cx, rect["top"] + cy
        if not self._do_click(target, abs_x, abs_y, score=similarity, enforce_global=False):
            # The target was still positively seen; don't waste a 0.5s template
            # sweep on an input or rate-limit problem.
            return True

        clicked_at = time.time()
        self.last_global_click = clicked_at
        target._recent_locations.append((cx, cy, clicked_at))
        target._recent_locations = target._recent_locations[-100:]
        if self.dry_run:
            log.info("DRY RUN DETECTED FAST %s screen=(%d,%d) frame=(%d,%d) score=%.3f hue_delta=%.1f shape_distance=%.3f",
                     target.name, abs_x, abs_y, cx, cy, similarity, hue_delta, shape_distance)
            self._write_debug_overlay(frame)
            return True

        self.safety.note_click()
        target._last_action = clicked_at
        target.total_hits += 1
        target.evidence_clicks += 1
        target._clicks.append((cx, cy))
        target._clicks = target._clicks[-200:]
        target._dirty = True
        if not hasattr(self, "recent_clicks") or self.recent_clicks is None:
            self.recent_clicks = deque(maxlen=200)
        self.recent_clicks.append({"target": target.name, "score": float(similarity),
                                   "ts": clicked_at, "confirmed": False})
        if not hasattr(self, "_pending_feedback") or self._pending_feedback is None:
            self._pending_feedback = deque(maxlen=100)
        self._pending_feedback.append({
            "name": target.name, "score": float(similarity), "before": frame.copy(),
            "x": cx, "y": cy, "due": clicked_at + max(0.05, self.cfg.learn_delay),
        })
        self._maybe_tune(target, rect)
        log.info("CLICK SENT FAST %s screen=(%d,%d) frame=(%d,%d) score=%.3f threshold=%.3f hits=%d",
                 target.name, abs_x, abs_y, cx, cy, similarity, target.threshold, target.total_hits)
        self._write_debug_overlay(frame)
        return True

    def _candidate_boxes(self, frame: np.ndarray) -> List[Tuple[float, int, int, int, int]]:
        """Fast per-frame proposal pass: known color families + unseen neon forms."""
        color_candidates = self._color_component_candidates(frame)
        generic_candidates = self.saliency.candidates(frame)
        combined = list(color_candidates)
        # Keep a handful of the edge/neon-agnostic proposals for newly appearing
        # shapes such as the large green effect, even if its hue is not yet learned.
        for score, x, y, w, h in generic_candidates:
            box_area = max(1, w * h)
            frame_area = max(1, frame.shape[0] * frame.shape[1])
            frac = box_area / frame_area
            # Generic contours tend to score below color components; lift plausible
            # mid/large forms slightly without allowing a full-screen rectangle to win.
            adjusted = float(score) + (0.30 if 0.003 <= frac <= 0.88 else 0.08)
            combined.append((adjusted, x, y, w, h))
        combined.sort(reverse=True)
        kept = []
        for candidate in combined:
            _, x, y, w, h = candidate
            duplicate = False
            for _, px, py, pw, ph in kept:
                inter = max(0, min(x + w, px + pw) - max(x, px)) * max(0, min(y + h, py + ph) - max(y, py))
                union = w * h + pw * ph - inter
                if union > 0 and inter / union >= 0.50:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(candidate)
            if len(kept) >= 60:
                break
        return kept

    def _color_component_candidates(self, frame: np.ndarray) -> List[Tuple[float, int, int, int, int]]:
        """Segment compact neon components by learned and quantized HSV hue.

        This avoids the global template correlation map being dominated by high
        correlations from scenery. It is intentionally a proposal stage only;
        every candidate still has to pass silhouette/ghost-shape validation.
        """
        if frame is None or frame.size == 0:
            return []
        max_dim = min(800, max(480, int(self.cfg.match_max_dimension)))
        fh, fw = frame.shape[:2]
        scale = min(1.0, max_dim / max(fh, fw))
        work = frame if scale >= 0.999 else cv2.resize(
            frame, (max(1, int(round(fw * scale))), max(1, int(round(fh * scale)))),
            interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
        hue, sat, val = cv2.split(hsv)
        h, w = hue.shape[:2]
        target_hues = []
        for target in self.library.targets.values():
            th = getattr(target, "_color_median_hue", None)
            if th is None:
                th = getattr(target, "_dominant_hue", None)
            if th is not None and np.isfinite(th):
                target_hues.append(float(th) % 180.0)
        # Build hue proposals from this frame's actual saturated-color histogram,
        # not a fixed sweep of every 12 degrees. This cuts full-frame masks on
        # 1050 Ti / i7-class systems while still discovering unseen neon colors.
        target_centers: List[float] = []
        for item in sorted(target_hues):
            if not any(hue_distance(item, prior) <= 3.5 for prior in target_centers):
                target_centers.append(item)
        hue_i16 = hue.astype(np.int16)
        eligible_pixels = (sat >= 75) & (val >= 65)
        hist = np.bincount(hue[eligible_pixels], weights=sat[eligible_pixels].astype(np.float32), minlength=180).astype(np.float32)
        smooth = np.zeros_like(hist)
        for shift in range(-4, 5):
            smooth += np.roll(hist, shift)
        # Always retain known hue families. Picking just histogram peaks can
        # suppress a blue target when a nearby cyan room hue wins the peak; both
        # must be proposed. Use only a handful of additional peaks for new colors.
        centers: List[Tuple[float, bool]] = [(c, True) for c in target_centers[:20]]
        suppressed = np.zeros(180, dtype=bool)
        for _ in range(8):
            peak_values = smooth.copy()
            peak_values[suppressed] = 0
            peak = int(np.argmax(peak_values))
            if float(peak_values[peak]) <= 0:
                break
            nearest = min(target_centers, key=lambda known: hue_distance(float(peak), known), default=None)
            if (nearest is None or hue_distance(float(peak), nearest) > 8.0) and not any(
                    hue_distance(float(peak), existing) <= 8.0 for existing, _known in centers):
                centers.append((float(peak), False))
            for offset in range(-7, 8):
                suppressed[(peak + offset) % 180] = True
        centers = centers[:26]
        frame_area = max(1, h * w)
        min_area = max(22, int(frame_area * 0.000025))
        close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        out: List[Tuple[float, int, int, int, int]] = []
        for center, known_hue in centers:
            dh = np.abs(hue_i16 - int(round(center)))
            dh = np.minimum(dh, 180 - dh)
            hue_tolerance = 6 if known_hue else 8
            sat_floor, value_floor = (90, 90) if known_hue else (85, 80)
            mask = ((dh <= hue_tolerance) & (sat >= sat_floor) & (val >= value_floor)).astype(np.uint8) * 255
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel)
            # findContours is materially cheaper than connectedComponentsWithStats
            # for these sparse neon masks, especially on 1080p desktop captures.
            # The close operation above already joins nearby glow fragments.
            contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            local = []
            for contour in contours:
                x, y, bw, bh = [int(v) for v in cv2.boundingRect(contour)]
                area = int(cv2.contourArea(contour))
                if area < min_area or bw < 17 or bh < 17:
                    continue
                box_area = max(1, bw * bh)
                frac = box_area / frame_area
                fill = area / box_area
                aspect = bw / max(1, bh)
                if frac > 0.16 or fill < 0.12 or not 0.36 <= aspect <= 2.7:
                    continue
                # Reject clipped components that span an edge and look like scenery.
                if (x <= 1 or y <= 1 or x + bw >= w - 1 or y + bh >= h - 1) and frac > 0.025:
                    continue
                priority = 1.22 if known_hue else 1.08
                score = priority + min(0.14, fill * 0.14) - min(0.08, frac * 0.5)
                inv = 1.0 / scale
                local.append((score, int(round(x * inv)), int(round(y * inv)),
                              int(round(bw * inv)), int(round(bh * inv)), area))
            # Limit per hue to keep common blue scenery from flooding the shortlist.
            local.sort(key=lambda item: (item[0], item[5]), reverse=True)
            out.extend([(score, x, y, bw, bh) for score, x, y, bw, bh, _ in local[:5]])
        out.sort(reverse=True)
        kept: List[Tuple[float, int, int, int, int]] = []
        for cand in out:
            _, x, y, bw, bh = cand
            duplicate = False
            for _, px, py, pw, ph in kept:
                inter = max(0, min(x + bw, px + pw) - max(x, px)) * max(0, min(y + bh, py + ph) - max(y, py))
                union = bw * bh + pw * ph - inter
                if union and inter / union >= 0.55:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(cand)
            if len(kept) >= 36:
                break
        return kept

    def _poll_control_file(self) -> None:
        path = getattr(self, "control_file", None)
        if path is None:
            return
        try:
            stat = path.stat()
            if stat.st_mtime_ns == self._control_mtime_ns:
                return
            state = json.loads(path.read_text(encoding="utf-8"))
            self._control_mtime_ns = stat.st_mtime_ns
            if bool(state.get("stop", False)):
                self.stop()
            wanted_pause = bool(state.get("paused", False))
            if wanted_pause != self.paused:
                self.paused = wanted_pause
                log.info("GUI control: %s", "PAUSED" if self.paused else "RUNNING")
        except FileNotFoundError:
            return
        except Exception as exc:
            log.debug("Control file read issue: %s", exc)

    def _process_pending_discoveries(self, frame: np.ndarray, now: float) -> None:
        if not getattr(self, "_pending_discoveries", None):
            return
        count = len(self._pending_discoveries)
        for _ in range(count):
            item = self._pending_discoveries.popleft()
            if now < item["due"]:
                self._pending_discoveries.append(item)
                continue
            if frame.shape[:2] != item["before"].shape[:2]:
                self.library.blacklist[item["key"]] = now + self.cfg.explore_blacklist_s
                continue
            local_change = region_diff(item["before"], frame, item["cx"], item["cy"])
            global_change = global_diff(item["before"], frame)
            useful = (local_change >= self.cfg.min_local_change and
                      (global_change >= self.cfg.min_global_change or
                       local_change >= self.cfg.min_local_change * 1.6))
            log.debug("AUTO-LEARN feedback key=%s local=%.3f global=%.3f accepted=%s",
                      item["key"], local_change, global_change, useful)
            if useful:
                target = self.library.add_learned(
                    item["crop"], max(0.66, self.cfg.base_threshold - 0.06),
                    list(self.cfg.base_scales), mask=item["mask"])
                if target is not None:
                    log.info("AUTO-LEARN saved '%s' size=%dx%d local=%.3f global=%.3f",
                             target.name, item["crop"].shape[1], item["crop"].shape[0],
                             local_change, global_change)
                    self.library.save()
                else:
                    log.debug("AUTO-LEARN response seen, but candidate was an existing color/shape duplicate")
            else:
                self.library.blacklist[item["key"]] = now + self.cfg.explore_blacklist_s
                log.debug("AUTO-LEARN candidate rejected without click response (key=%s)", item["key"])

    def _update_pending_feedback(self, frame: np.ndarray, now: float) -> None:
        """Persist weak screen-change evidence without pretending it proves a reward."""
        if not self._pending_feedback:
            return
        count = len(self._pending_feedback)
        for _ in range(count):
            pending = self._pending_feedback.popleft()
            if now < pending["due"]:
                self._pending_feedback.append(pending)
                continue
            target = self.library.targets.get(pending["name"])
            if target is None:
                continue
            ld = region_diff(pending["before"], frame, pending["x"], pending["y"])
            gd = global_diff(pending["before"], frame)
            changed = (ld >= self.cfg.min_local_change or
                       (gd >= self.cfg.min_global_change and ld >= self.cfg.min_local_for_global))
            observed_score = float(pending.get("score", 0.0))
            if changed:
                target.evidence_responses += 1
                target.evidence_no_change = 0
                target.response_scores.append(observed_score)
                target.response_scores = target.response_scores[-100:]
            else:
                target.evidence_no_change += 1
                target.no_response_scores.append(observed_score)
                target.no_response_scores = target.no_response_scores[-100:]
            target._dirty = True
            self._calibrate_response_threshold(target)
            log.debug("[%s] post-click evidence: local=%.3f global=%.3f changed=%s score=%.3f",
                      target.name, ld, gd, changed, observed_score)

    # ---------- exploit: multi-target, multi-instance matching ----------
    def _match_and_click(self, frame, rect, now, prepared=None, targets=None) -> bool:
        if not self.library.targets:
            return False
        if prepared is None:
            prepared = prepare_match_frame(frame, self.cfg.match_max_dimension)
        scan_targets = list(targets) if targets is not None else list(self.library.targets.values())
        if not scan_targets:
            return False
        self._debug_boxes = []
        self._best_target_diagnostics = []
        screen_gray, screen_edges = prepared["gray"], prepared["edges"]
        # candidate: (margin-over-threshold, raw score, target, local x/y, w/h, absolute x/y)
        candidates = []
        for target in scan_targets:
            if target._template is None:
                continue
            if now - target._last_action < max(0.0, float(target.cooldown)):
                continue
            roi = frame
            roi_gray = screen_gray
            roi_edges = screen_edges
            rx = ry = 0
            if target.region and len(target.region) == 4:
                rx, ry, rw, rh = [int(v) for v in target.region]
                rx, ry = max(0, rx), max(0, ry)
                x1, y1 = min(frame.shape[1], rx + max(0, rw)), min(frame.shape[0], ry + max(0, rh))
                roi = frame[ry:y1, rx:x1]
                roi_gray = screen_gray[ry:y1, rx:x1]
                roi_edges = screen_edges[ry:y1, rx:x1]
                if roi.size == 0:
                    continue
            diag = {"best_score": -1.0}
            matches = find_all_matches(
                roi, target._template,
                [scale * target._scale_compensation for scale in target.scales],
                target.threshold, target.grayscale,
                max_matches=self.cfg.max_instances, mask=target._mask,
                precomputed_gray=roi_gray, precomputed_edges=roi_edges,
                template_edges=target._edge_template,
                template_color=target._template_color,
                precomputed_proc_gray=(prepared["proc_gray"] if not target.region else None),
                precomputed_proc_color=(prepared["proc_color"] if not target.region else None),
                precomputed_proc_edges=(prepared["proc_edges"] if not target.region else None),
                process_scale_override=(prepared["scale"] if not target.region else None),
                precomputed_proc_hsv=(prepared["proc_hsv"] if not target.region else None),
                min_match_side_px=self.cfg.min_match_side_px,
                diagnostics=diag,
                proposal_peaks_per_scale=self.cfg.proposal_peaks_per_scale)
            best_xy = diag.get("best_xy", (0, 0))
            diag_x, diag_y = int(best_xy[0]) + rx, int(best_xy[1]) + ry
            self._best_target_diagnostics.append((target.name, float(diag.get("best_score", -1.0)),
                                                  float(target.threshold), diag_x, diag_y))
            if not matches and log.isEnabledFor(logging.DEBUG):
                last = getattr(self, "_last_target_diag", {})
                if time.time() - last.get(target.name, 0.0) >= self.cfg.debug_score_interval_s:
                    coarse = diag.get("coarse_score", -1.0)
                    log.debug("NO MATCH target=%s best_verified=%.3f coarse_peak=%.3f threshold=%.3f scales=%d min_px=%d",
                              target.name, float(diag.get("best_score", -1.0)), float(coarse),
                              target.threshold, len(target.scales), self.cfg.min_match_side_px)
                    last[target.name] = time.time()
                    self._last_target_diag = last
            for match in matches:
                score, mx, my, mw, mh, scale = match
                lx, ly = rx + mx, ry + my
                self._debug_boxes.append((int(lx), int(ly), int(mw), int(mh),
                                          f"{target.name} {score:.2f}/{target.threshold:.2f}"))
                if self.safety.in_exclusion(lx, ly):
                    continue
                # Avoid clicking the exact same still-visible sprite every frame.
                target._recent_locations = [p for p in target._recent_locations
                                            if now - p[2] < self.cfg.same_location_cooldown_s]
                suppress_radius = max(8.0, min(mw, mh) * 0.42)
                if any((lx - px) ** 2 + (ly - py) ** 2 < suppress_radius ** 2
                       for px, py, ts in target._recent_locations):
                    continue
                confidence = float(score) - float(target.threshold)
                candidates.append((confidence, float(score), target, lx, ly, mw, mh,
                                   rect["left"] + lx, rect["top"] + ly))

        if not candidates:
            if log.isEnabledFor(logging.DEBUG) and self._best_target_diagnostics:
                top = sorted(self._best_target_diagnostics, key=lambda x: x[1], reverse=True)[:3]
                log.debug("FRAME NO CLICK: best targets=%s (thresholds included in target-level diagnostics)",
                          ", ".join(f"{n}={score:.3f}/{threshold:.3f}" for n, score, threshold, _, _ in top))
            self._write_debug_overlay(frame)
            return False
        candidates.sort(key=lambda c: (c[0], c[2].priority, c[1]), reverse=True)

        # Two different templates can match the same sprite. Keep the strongest
        # detection in an overlapping region to avoid duplicate click events.
        deduped = []
        for candidate in candidates:
            _, _, target, x, y, w, h, _, _ = candidate
            overlap = False
            for prior in deduped:
                _, _, _, px, py, pw, ph, _, _ = prior
                iw = max(0.0, min(x + w / 2, px + pw / 2) - max(x - w / 2, px - pw / 2))
                ih = max(0.0, min(y + h / 2, py + ph / 2) - max(y - h / 2, py - ph / 2))
                inter = iw * ih
                union = w * h + pw * ph - inter
                iou = inter / union if union > 0 else 0.0
                if iou >= 0.35:
                    overlap = True
                    break
            if not overlap:
                deduped.append(candidate)

        # Visual detections and mouse dispatch are distinct events for GUI
        # telemetry. Log the deduplicated, threshold-passing proposals before a
        # cooldown can prevent input from being dispatched.
        for _, score, target, lx, ly, mw, mh, abs_x, abs_y in deduped[:self.cfg.max_clicks_per_frame]:
            log.info("TARGET DETECTED source=template target=%s screen=(%d,%d) score=%.3f threshold=%.3f",
                     target.name, abs_x, abs_y, score, target.threshold)

        # A global cooldown gates the start of a burst. Inside the burst, the
        # per-second Safety limiter governs each individual click, so multi-match
        # mode really can click several detections instead of silently only one.
        if time.time() - self.last_global_click < self.cfg.global_cooldown:
            return False
        acted = 0
        preview_frame = frame.copy()
        for _, score, target, lx, ly, mw, mh, abs_x, abs_y in deduped:
            if acted >= self.cfg.max_clicks_per_frame or not self.safety.can_click():
                break
            if not self._do_click(target, abs_x, abs_y, score=score, enforce_global=False):
                continue
            acted += 1
            now_click = time.time()
            self.last_global_click = now_click
            target._recent_locations.append((lx, ly, now_click))
            target._recent_locations = target._recent_locations[-100:]
            if self.dry_run:
                log.info("DRY RUN DETECTED %s screen=(%d,%d) frame=(%d,%d) score=%.3f threshold=%.3f",
                         target.name, abs_x, abs_y, lx, ly, score, target.threshold)
                continue

            self.safety.note_click()
            target._last_action = now_click
            target.total_hits += 1
            target.evidence_clicks += 1
            target._clicks.append((lx, ly))
            if len(target._clicks) > 200:
                target._clicks = target._clicks[-200:]
            target._dirty = True
            self.recent_clicks.append({
                "target": target.name, "score": float(score), "ts": now_click,
                "confirmed": False,
            })
            self._pending_feedback.append({
                "name": target.name, "score": float(score), "before": preview_frame,
                "x": lx, "y": ly,
                "due": now_click + max(0.05, self.cfg.learn_delay),
            })
            self._maybe_tune(target, rect)
            log.info("CLICK SENT %s screen=(%d,%d) frame=(%d,%d) score=%.3f threshold=%.3f hits=%d",
                     target.name, abs_x, abs_y, lx, ly, score, target.threshold, target.total_hits)
            if self.cfg.multi_delay > 0:
                time.sleep(self.cfg.multi_delay)
        self._write_debug_overlay(frame)
        if acted:
            self.last_match_time = time.time()
            self._last_exact_match_time = self.last_match_time
        return acted > 0

    def _write_debug_overlay(self, frame: np.ndarray) -> None:
        """Write a rate-limited annotated frame useful for diagnosing missed clicks."""
        self._ghost_preview(frame)
        if not getattr(self.cfg, "debug_overlay", False):
            return
        now = time.time()
        if now - getattr(self, "_last_debug_write", 0.0) < 1.0:
            return
        self._last_debug_write = now
        view = frame.copy()
        for x, y, w, h, label in getattr(self, "_debug_boxes", []):
            cv2.rectangle(view, (x, y), (x + w, y + h), (65, 220, 150), 2)
            cv2.putText(view, label[:48], (x, max(16, y - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (65, 220, 150), 1, cv2.LINE_AA)
        for x, y, w, h, label in getattr(self, "_debug_proposals", []):
            cv2.rectangle(view, (x, y), (x + w, y + h), (80, 170, 255), 1)
            cv2.putText(view, label[:48], (x, min(view.shape[0] - 3, y + 14)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (80, 170, 255), 1, cv2.LINE_AA)
        for x, y, w, h, label in getattr(self, "_smart_boxes", []):
            cv2.rectangle(view, (x, y), (x + w, y + h), (255, 120, 255), 2)
            cv2.putText(view, label[:40], (x, max(16, y - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 120, 255), 1, cv2.LINE_AA)
        ranked = sorted(getattr(self, "_best_target_diagnostics", []),
                        key=lambda x: x[1], reverse=True)[:10]
        y_text = 20
        for name, score, threshold, x, y in ranked:
            good = score >= threshold
            color = (65, 220, 150) if good else (50, 180, 255)
            if score >= 0:
                cv2.circle(view, (max(0, min(view.shape[1]-1, x)), max(0, min(view.shape[0]-1, y))), 5, color, 2)
            cv2.putText(view, f"{name[:22]} {score:.3f}/{threshold:.3f}",
                        (8, y_text), cv2.FONT_HERSHEY_SIMPLEX, 0.44, color, 1, cv2.LINE_AA)
            y_text += 18
        folder = self.root / "diagnostics"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "latest_frame.jpg"
        ok = cv2.imwrite(str(path), view, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if ok:
            log.debug("DEBUG FRAME written: %s", path)

    def _maybe_tune(self, t: Target, rect):
        # Auto-ROI can suppress legitimate targets outside an early cluster.
        # Keep global matching as the default; only enable narrowing explicitly.
        if not self.cfg.auto_learn_roi:
            return
        if len(t._clicks) >= 15:
            xs = [p[0] for p in t._clicks]; ys = [p[1] for p in t._clicks]
            x0, x1 = min(xs), max(xs); y0, y1 = min(ys), max(ys)
            pad_x = int((x1 - x0) * 0.35) + 50
            pad_y = int((y1 - y0) * 0.35) + 50
            nx0, ny0 = max(0, x0 - pad_x), max(0, y0 - pad_y)
            nw, nh = (x1 - x0) + 2 * pad_x, (y1 - y0) + 2 * pad_y
            # only if it's a meaningful shrink
            if rect["width"] > 0 and nw * nh < 0.6 * rect["width"] * rect["height"]:
                if (t.region is None
                    or abs(nw - t.region[2]) > 40
                    or abs(nh - t.region[3]) > 40):
                    t.region = [nx0, ny0, nw, nh]
                    t._dirty = True
                    log.info(f"[{t.name}] ROI → {t.region}")

    # ---------- explore (idle-only, response-gated) ----------
    def _looks_like_unseen_ghost_form(self, crop: np.ndarray, mask: np.ndarray) -> bool:
        """Conservative fallback for a genuinely new color/shape not in the seed bank.

        This runs only during opt-in exploration. Requiring a compact foreground,
        neon/high-saturation pixels, and multiple bright face-like features is much
        stricter than accepting any visually interesting contour.
        """
        if crop is None or crop.size == 0 or mask is None or mask.shape[:2] != crop.shape[:2]:
            return False
        h, w = crop.shape[:2]
        if min(h, w) < 24 or not 0.42 <= (w / max(1, h)) <= 1.9:
            return False
        valid = mask > 0
        valid_count = int(np.count_nonzero(valid))
        coverage = valid_count / max(1, h * w)
        if not 0.12 <= coverage <= 0.94:
            return False
        contours, _ = cv2.findContours((valid.astype(np.uint8) * 255), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return False
        contour = max(contours, key=cv2.contourArea)
        area = float(cv2.contourArea(contour))
        hull = cv2.convexHull(contour)
        hull_area = float(cv2.contourArea(hull))
        solidity = area / max(1.0, hull_area)
        if not 0.42 <= solidity <= 0.995:
            return False
        hsv = cv2.cvtColor(crop[:, :, :3], cv2.COLOR_BGR2HSV)
        sat = hsv[:, :, 1]
        val = hsv[:, :, 2]
        sat_fraction = float(np.mean(sat[valid] >= 95))
        glow_fraction = float(np.mean((val[valid] >= 190) & (sat[valid] >= 40)))
        if sat_fraction < 0.22 or glow_fraction < 0.025:
            return False

        # Separate facial glow from the body by relative saturation. A bright
        # neon body can itself have high V; thresholding brightness alone made the
        # entire silhouette one component and rejected real unseen variants.
        # Eye/mouth glows are commonly lighter and less saturated than the shell.
        body_sat_median = float(np.median(sat[valid]))
        body_value_p72 = float(np.percentile(val[valid], 72))
        feature_value_floor = max(205.0, body_value_p72)
        lower_sat_ceiling = max(70.0, body_sat_median * 0.72)
        features = ((val >= feature_value_floor) & (sat <= lower_sat_ceiling) & valid).astype(np.uint8) * 255
        features = cv2.morphologyEx(features, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        count, labels, stats, centroids = cv2.connectedComponentsWithStats((features > 0).astype(np.uint8), 8)
        face_like = []
        for idx in range(1, count):
            fx, fy, fw, fh, fa = [int(v) for v in stats[idx]]
            if fa < max(3, int(h * w * 0.001)) or fa > int(valid_count * 0.22):
                continue
            cx, cy = centroids[idx]
            if 0.12 * w <= cx <= 0.88 * w and 0.10 * h <= cy <= 0.78 * h:
                face_like.append((float(cx), float(cy), fa))
        if len(face_like) >= 2:
            xs = [p[0] for p in face_like]
            if (max(xs) - min(xs)) >= 0.12 * w:
                return True

        # Some Highrise effects have saturated neon-green eyes sitting above a
        # single connected yellow/white mouth-glow. Treat the two spatially
        # separated upper highlights plus a bright lower-face patch as a face;
        # requiring all of this avoids accepting ordinary neon scenery.
        eye_floor = max(170.0, float(np.percentile(val[valid], 58)))
        eyes = ((val >= eye_floor) & (sat >= 80) & valid).astype(np.uint8) * 255
        eyes = cv2.morphologyEx(eyes, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n_eye, eye_labels, eye_stats, eye_centroids = cv2.connectedComponentsWithStats((eyes > 0).astype(np.uint8), 8)
        eye_points = []
        for idx in range(1, n_eye):
            ex, ey, ew, eh, ea = [int(v) for v in eye_stats[idx]]
            ecx, ecy = eye_centroids[idx]
            if ea < max(5, int(h * w * 0.0008)) or ea > int(valid_count * 0.12):
                continue
            if 0.12 * w <= ecx <= 0.88 * w and 0.10 * h <= ecy <= 0.62 * h:
                eye_points.append((float(ecx), float(ecy), ea))
        separated_eyes = (len(eye_points) >= 2 and
                          (max(p[0] for p in eye_points) - min(p[0] for p in eye_points)) >= 0.12 * w)
        lower_face = any(0.25 * h <= cy <= 0.78 * h for _cx, cy, _area in face_like)
        return bool(separated_eyes and lower_face)

    def _candidate_matches_seed_family(self, crop: np.ndarray) -> Optional[np.ndarray]:
        """Return a foreground mask only when the candidate resembles a seed silhouette.

        dHash-only filtering is not reliable here: scenery dominates small crops,
        and unrelated images can have similar perceptual hashes. The proposal
        must have a contour close to a seed's contour before it can be trial-clicked.
        """
        # This function is called repeatedly while scanning candidate proposals;
        # keep it strictly CPU-light and do not call GrabCut in the frame loop.
        candidate_mask, _candidate_hue = quick_hue_mask(crop)
        candidate_contour = _mask_contour(candidate_mask)
        if candidate_mask is None or candidate_contour is None:
            return None
        h, w = crop.shape[:2]
        aspect = w / max(1, h)
        if not 0.45 <= aspect <= 1.9:
            return None
        best_distance = float("inf")
        for target in self.library.targets.values():
            if target.source != "seed" or target._template is None:
                continue
            seed_contour = getattr(target, "_shape_contour", None)
            if seed_contour is None:
                seed_mask = target._mask
                if seed_mask is None:
                    base = target._template
                    base_bgr = cv2.cvtColor(base, cv2.COLOR_GRAY2BGR) if base.ndim == 2 else base
                    seed_mask, _ = quick_hue_mask(base_bgr)
                seed_contour = _mask_contour(seed_mask)
            if seed_contour is None:
                continue
            sh, sw = target._template.shape[:2]
            ratio = (sw / max(1, sh)) / aspect
            if not 0.55 <= ratio <= 1.8:
                continue
            try:
                distance = float(cv2.matchShapes(seed_contour, candidate_contour,
                                                 cv2.CONTOURS_MATCH_I1, 0.0))
            except cv2.error:
                continue
            best_distance = min(best_distance, distance)
        # A candidate that resembles a known seed silhouette belongs to the
        # seed family; it must not also pass the much stricter unseen-form face
        # heuristic. This independent gate is important for unusual palettes.
        if best_distance <= 0.11:
            return candidate_mask

        # Genuinely new silhouettes use the stricter neon/face heuristic. This
        # path is intentionally logged at DEBUG and rate-limited so a busy scene
        # cannot flood the console or file log while exploration is enabled.
        if self._looks_like_unseen_ghost_form(crop, candidate_mask):
            now = time.monotonic()
            last = getattr(self, "_last_unseen_form_log", 0.0)
            interval = max(1.0, float(getattr(self.cfg, "debug_score_interval_s", 2.0)))
            if now - last >= interval:
                log.debug("Exploration: visually plausible unseen ghost form; waiting for response evidence")
                self._last_unseen_form_log = now
            return candidate_mask
        return None

    def _explore_once(self, frame, rect, candidates=None) -> bool:
        if self.cfg.patient_mode:
            return False
        if candidates is None:
            candidates = self._candidate_boxes(frame)
        if not candidates:
            return False
        now = time.time()
        gw, gh = self.cfg.explore_grid
        cw = max(1, rect["width"] // max(1, gw))
        ch = max(1, rect["height"] // max(1, gh))
        chosen = None
        examined = 0
        validated = 0
        # Candidates are hue-segmented first, with contour proposals retained for
        # unknown hues/shapes. Try a bounded shortlist on each frame.
        for saliency_score, x, y, w, h in candidates[:40]:
            examined += 1
            cx, cy = x + w // 2, y + h // 2
            if self.safety.in_exclusion(cx, cy):
                continue
            key = f"{cx // cw},{cy // ch}"
            if self.library.blacklist.get(key, 0) > now:
                continue
            if now - self.library.visited.get(key, 0) < 5.0:
                continue
            pad = 5
            x0, y0 = max(0, x - pad), max(0, y - pad)
            x1 = min(frame.shape[1], x + w + pad)
            y1 = min(frame.shape[0], y + h + pad)
            proposal = frame[y0:y1, x0:x1]
            family_mask = self._candidate_matches_seed_family(proposal)
            if family_mask is None:
                continue
            validated += 1
            chosen = (saliency_score, x, y, w, h, cx, cy, key, x0, y0, x1, y1, family_mask)
            break
        if chosen is None:
            last_diag = getattr(self, "_last_explore_diag", 0.0)
            if now - last_diag >= max(0.5, self.cfg.debug_score_interval_s):
                log.debug("EXPLORATION NO CLICK: proposals=%d examined=%d ghost_validations=%d; no input was attempted",
                          len(candidates), examined, validated)
                self._last_explore_diag = now
            return False

        saliency_score, x, y, w, h, cx, cy, key, x0, y0, x1, y1, family_mask = chosen
        log.info("TARGET DETECTED source=exploration target=exploration-proposal screen=(%d,%d) score=%.3f size=%dx%d",
                 rect["left"] + cx, rect["top"] + cy, saliency_score, w, h)
        if not self.safety.can_click():
            log.warning("CLICK BLOCKED: safety rate/session limiter active (session=%d/%d, max_cps=%.1f)",
                        self.safety.session_clicks, self.cfg.max_session_clicks, self.cfg.max_cps)
            return False
        if now - self.last_global_click < self.cfg.global_cooldown:
            log.debug("CLICK DEFERRED: global cooldown %.3fs remaining",
                      self.cfg.global_cooldown - (now - self.last_global_click))
            return False
        abs_x, abs_y = rect["left"] + cx, rect["top"] + cy
        log.debug("EXPLORATION CANDIDATE VALIDATED screen=(%d,%d) size=%dx%d score=%.3f cell=%s",
                  rect["left"] + cx, rect["top"] + cy, w, h, saliency_score, key)
        proposal_target = Target(name="exploration-proposal", image_path="", source="learned")
        if not self._do_click(proposal_target, abs_x, abs_y, score=saliency_score, enforce_global=False):
            return False
        if self.dry_run:
            self.library.visited[key] = now
            log.info("DRY RUN CANDIDATE ACCEPTED screen=(%d,%d) size=%dx%d score=%.3f; no click/learning emitted",
                     abs_x, abs_y, w, h, saliency_score)
            return True

        # Do not sleep/capture inside exploration. Queue a bounded piece of
        # evidence and evaluate it asynchronously during subsequent frame ticks,
        # otherwise each candidate would stall the loop for learn_delay seconds.
        self.safety.note_click()
        self.library.visited[key] = now
        self._pending_discoveries.append({
            "before": frame.copy(), "crop": frame[y0:y1, x0:x1].copy(),
            "mask": family_mask.copy(), "cx": cx, "cy": cy, "key": key,
            "due": now + max(0.05, self.cfg.learn_delay),
        })
        log.info("EXPLORATION INPUT SENT screen=(%d,%d) size=%dx%d score=%.3f; learning check queued",
                 abs_x, abs_y, w, h, saliency_score)
        return True

    # ---------- action ----------
    # ---------- learned detector ----------
    # ---------- ghost kinds / waves ----------
    _P_IN_LABEL = re.compile(r"(?<![\d.])(0?\.\d+|1\.0+)(?!\d)")

    def _ghost_boxes(self) -> List[Tuple[int, int, int, int]]:
        """Current ghost boxes (frame pixels): the learned detector when it is ready,
        otherwise the template matches of this frame."""
        raw = []
        if self.smart is not None:
            try:
                if self.smart.ready():
                    raw = list(self.smart.debug_boxes())
            except Exception:
                raw = []
        if not raw:
            raw = list(self._debug_boxes)
        floor = float(self.cfg.smart_threshold) - float(self.cfg.wave_conf_delta)
        dedup_iou = float(self.cfg.wave_dedup_iou)
        self._ghost_drop_low = 0
        self._ghost_drop_dup = 0
        out: List[Tuple[int, int, int, int]] = []
        now_t = time.time()
        raw = list(raw) + [(b[0], b[1], b[2], b[3]) for t, b, _p in self._recent_picks if now_t - t < 0.8]
        self._ghost_raw_n = len(raw)
        for item in raw:
            try:
                x, y, w, h = int(item[0]), int(item[1]), int(item[2]), int(item[3])
            except Exception:
                continue
            if w <= 0 or h <= 0:
                continue
            m = self._P_IN_LABEL.search(str(item[4])) if len(item) > 4 else None
            if m and float(m.group(1)) < floor:
                self._ghost_drop_low += 1
                continue                              # low-confidence candidate, not a ghost
            dup = False
            for px, py, pw, ph in out:
                inter = max(0, min(x + w, px + pw) - max(x, px)) * max(0, min(y + h, py + ph) - max(y, py))
                if inter / float(w * h + pw * ph - inter) >= dedup_iou:
                    dup = True
                    break
            if dup:
                self._ghost_drop_dup += 1
            else:
                out.append((x, y, w, h))
        return out

    def _update_ghost_scene(self, frame, now, rect=None):
        gs = self.ghost_scene
        if gs is None:
            return None
        try:
            was_wave = gs.wave_active
            scene = gs.update(frame, self._ghost_boxes(), now)
            if gs.wave_active and not was_wave:
                self._wave_clicks = 0
                self._wave_recent.clear()
            if self.cfg.labeling_collect:
                gs.collect_unlabeled(frame, now)
            if now - self._last_ghost_diag >= 10.0:
                self._last_ghost_diag = now
                log.info("GHOSTS: raw boxes=%d (dropped: %d low-confidence, %d duplicate), small=%d, boss=%d, wave=%s, overlay=%s",
                         self._ghost_raw_n, getattr(self, "_ghost_drop_low", 0), getattr(self, "_ghost_drop_dup", 0),
                         len(scene.smalls), len(scene.bosses), gs.wave_active,
                         "on" if self.overlay is not None else "off")
            if self.overlay is not None and rect is not None:
                if not self._overlay_checked:
                    self._overlay_checked = True
                    if not self._overlay_selftest(rect):
                        log.warning("GHOSTS: the overlay would be visible to the bot's screenshots (Windows too old for "
                                    "capture exclusion?) - overlay turned OFF so the bot never reads its own labels.")
                        self.overlay.stop()
                        self.overlay = None
                        if self.teacher is not None:
                            self.teacher.overlay_lost()      # F4 mode + overlay auto-learning stop; the Teach window stays
                        return scene
                    log.info("GHOSTS: overlay self-test passed (labels are invisible to the bot).")
                items = gs.overlay_items(now)
                if self.teacher is not None:
                    items = self.teacher.process(frame, rect, now, items)
                self.overlay.push(rect, items)
            elif self.teacher is not None:       # no overlay (or no window rect): the Teach window still works
                self.teacher.process(frame, rect, now, {})
            return scene
        except Exception as exc:       # labels must never be able to stop the bot
            if now - self._last_smart_err > 5.0:
                log.exception("GHOST scene error (continuing): %s", exc)
                self._last_smart_err = now
            return None

    def _overlay_selftest(self, rect) -> bool:
        """True when a bright test patch drawn by the overlay does NOT show up in a screenshot."""
        if self.cfg.capture_method == "printwindow" or self.sct is None:
            return True
        try:
            self.overlay.show_test(rect)
            time.sleep(0.45)
            shot = np.array(self.sct.grab({"left": int(rect["left"]) + 4, "top": int(rect["top"]) + 4,
                                           "width": 40, "height": 40}))
            self.overlay.show_test(None)
            time.sleep(0.1)
            b, g, r = (float(shot[..., i].mean()) for i in range(3))
            return not (r > 200 and b > 200 and g < 70)
        except Exception as exc:
            log.warning("overlay self-test failed (%s); overlay stays off", exc)
            try:
                self.overlay.show_test(None)
            except Exception:
                pass
            return False

    def _wave_click(self, rect, now) -> bool:
        """Click every small ghost on screen (nearest-neighbour order). No reward is
        visible per click during a wave, so nothing here is reported to the learner."""
        gs = self.ghost_scene
        order = gs.wave_click_order(self._last_wave_pos)
        if not order:
            return False
        sent = 0
        for g in order:
            if sent >= max(1, int(self.cfg.wave_clicks_per_tick)):
                break
            sx, sy = int(rect["left"] + g.cx), int(rect["top"] + g.cy)
            rad = max(20, int(0.6 * max(g.w, g.h)))
            if any(now - t < self.cfg.wave_reclick_s and abs(px - sx) <= rad and abs(py - sy) <= rad
                   for px, py, t in self._wave_recent):
                continue
            if self.safety.in_exclusion(g.cx, g.cy):
                continue
            target = Target(name="wave-ghost", image_path="", source="learned")
            if not self._do_click(target, sx, sy, score=g.conf, enforce_global=False, track_based=True):
                break                                   # rate cap / window not on top: try next frame
            self.safety.note_click()
            self._wave_recent.append((sx, sy, now))
            self._last_wave_pos = (g.cx, g.cy)
            self._wave_clicks += 1
            sent += 1
            self.last_global_click = time.time()
            time.sleep(0.012)
        return True

    def _ghost_preview(self, frame) -> None:
        """Live view with labels + banner. Shown only where the bot cannot see it."""
        gs = self.ghost_scene
        if gs is None or not self._preview_ok or self.overlay is not None:
            return
        now = time.time()
        if now - self._last_preview < 1.0 / 15.0:
            return
        self._last_preview = now
        try:
            if not self._preview_placed:
                if not self._place_preview(frame):
                    return
            view = gs.draw(frame, self._wave_clicks)
            wmax = int(self.cfg.ghost_preview_width)
            if view.shape[1] > wmax:
                f = wmax / view.shape[1]
                view = cv2.resize(view, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
            cv2.imshow("BLOOP ghosts", view)
            cv2.waitKey(1)
        except Exception as exc:
            log.warning("ghost preview disabled: %s", exc)
            self._preview_ok = False

    def _place_preview(self, frame) -> bool:
        """Put the preview window outside the game rectangle. If it would overlap the
        game, screen capture would see the labels as ghosts, so it is not shown."""
        safe = self.cfg.capture_method == "printwindow" or self.cfg.ghost_preview_force
        rect = self.window.get_rect() if self.window.targeting else None
        pw = min(int(self.cfg.ghost_preview_width), frame.shape[1])
        ph = int(frame.shape[0] * pw / max(1, frame.shape[1]))
        x = y = 0
        if rect is not None and sys.platform == "win32":
            u = ctypes.windll.user32
            vx, vy, vw, vh = u.GetSystemMetrics(76), u.GetSystemMetrics(77), u.GetSystemMetrics(78), u.GetSystemMetrics(79)
            r0, r1, t0, t1 = rect["left"], rect["left"] + rect["width"], rect["top"], rect["top"] + rect["height"]
            spots = [(r1 + 8, t0, vx + vw - (r1 + 8)),           # right of the game
                     (vx, t0, r0 - 8 - vx)]                       # left of the game
            for sx, sy, room in spots:
                if room >= 320:
                    pw = min(pw, room)
                    ph = int(frame.shape[0] * pw / max(1, frame.shape[1]))
                    x, y, safe = (sx if sx != vx else max(vx, r0 - 8 - pw)), sy, True
                    break
        if not safe:
            log.warning("GHOST preview window hidden: it would overlap Highrise and the bot would read its own "
                        "labels. Use a second monitor / smaller game window, or set ghost_preview_force=true. "
                        "Labels still appear in the log.")
            self._preview_ok = False
            return False
        cv2.namedWindow("BLOOP ghosts", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("BLOOP ghosts", int(pw), int(ph))
        cv2.moveWindow("BLOOP ghosts", int(x), int(y))
        self._preview_placed = True
        return True

    def _smart_feed(self, frame, rect, now, boxes, popup: bool = False) -> None:
        if self.smart is None:
            return
        try:
            self.smart.on_frame(frame, rect, now, boxes, popup=popup)
        except Exception as exc:     # learning must never be able to stop the bot
            if now - self._last_smart_err > 5.0:
                log.exception("SMART frame processing error (continuing): %s", exc)
                self._last_smart_err = now

    def _smart_click(self, frame, rect, now) -> bool:
        """Click the best learned ghost. Returns True when a ghost was identified."""
        try:
            pick = self.smart.pick_target(frame, rect, now)
        except Exception as exc:
            if now - self._last_smart_err > 5.0:
                log.exception("SMART pick error (continuing): %s", exc)
                self._last_smart_err = now
            return False
        self._smart_boxes = self.smart.debug_boxes()[:20]
        if pick is None:
            return False
        try:                                    # remember what the learner chose so it can be labelled / drawn
            bx, by, bw, bh = (int(v) for v in pick.box[:4])
            fx, fy = int(pick.frame_x), int(pick.frame_y)
            inside_tl = bx <= fx <= bx + bw and by <= fy <= by + bh
            inside_c = bx - bw // 2 <= fx <= bx + bw // 2 and by - bh // 2 <= fy <= by + bh // 2
            if not inside_tl and inside_c:      # box given as centre + size
                bx, by = bx - bw // 2, by - bh // 2
            self._recent_picks.append((now, (bx, by, bw, bh), float(pick.p)))
        except Exception:
            pass
        if now - self.last_global_click < self.cfg.global_cooldown:
            return True
        target = Target(name="smart-ghost", image_path="", source="learned")
        if not self._do_click(target, pick.screen_x, pick.screen_y, score=pick.p,
                              enforce_global=False, track_based=True):   # tracked mover: short same-spot lockout so aim-miss retries work
            return True
        clicked_at = time.time()
        self.last_global_click = clicked_at
        if self.dry_run:
            log.info("DRY RUN SMART would click ghost #%d at frame=(%d,%d) p=%.2f",
                     pick.tid, pick.frame_x, pick.frame_y, pick.p)
            return True
        self.safety.note_click()
        self.smart.note_smart_click(pick, frame, clicked_at)
        log.info("SMART CLICK ghost #%d screen=(%d,%d) frame=(%d,%d) p=%.2f box=%dx%d",
                 pick.tid, pick.screen_x, pick.screen_y, pick.frame_x, pick.frame_y,
                 pick.p, pick.box[2], pick.box[3])
        return True

    def _do_click(self, target: Target, x: int, y: int, score: float = 0.0,
                  enforce_global: bool = True, track_based: bool = False) -> bool:
        if not self.safety.can_click():
            return False
        if enforce_global and time.time() - self.last_global_click < self.cfg.global_cooldown:
            return False
        radius = int(self.cfg.repeat_click_radius_px)
        if radius > 0:
            stamp = time.time()
            for px, py, pt in self._last_click_points:
                # Tracked (moving) ghosts are de-duplicated by track id, so the long
                # same-spot lockout is shortened for them.
                cool = min(0.6, self.cfg.same_location_cooldown_s) if track_based else self.cfg.same_location_cooldown_s
                if stamp - pt < cool and abs(px - x) <= radius and abs(py - y) <= radius:
                    return False   # same spot as a very recent click, whichever detector found it
        if self.dry_run:
            log.info("DRY RUN WOULD CLICK %s screen=(%d,%d) score=%.3f",
                     target.name, x, y, score)
            return True
        if not HAS_DIRECT_INPUT or pydirectinput is None:
            log.error("pydirectinput missing; refusing to send input.")
            return False
        if self.window.hwnd:
            self.window.focus()
            if self.cfg.require_game_under_cursor and not self.window.owns_point(int(x), int(y)):
                time.sleep(0.05)
                if not self.window.owns_point(int(x), int(y)):
                    if time.time() - self._last_cover_log >= 3.0:
                        log.warning("CLICK BLOCKED: another window is on top of (%d,%d); not clicking outside Highrise.", x, y)
                        self._last_cover_log = time.time()
                    return False
        if getattr(self, "smart", None) is not None:
            self.smart.note_bot_click(int(x), int(y))   # so the learner ignores the bot's own click
        log.info("INPUT ATTEMPT target=%s screen=(%d,%d) action=%s score=%.3f",
                 target.name, x, y, target.action, score)
        try:
            if target.action == "key":
                if not target.key:
                    log.warning("target '%s' has action=key without a key name; skip", target.name)
                    return False
                pydirectinput.press(target.key)
            elif target.action == "double_click":
                pydirectinput.moveTo(int(x), int(y))
                pydirectinput.doubleClick()
            else:
                pydirectinput.moveTo(int(x), int(y))
                pydirectinput.click()
        except Exception as exc:
            log.error("input action failed on %s: %s", target.name, exc)
            return False
        self.last_global_click = time.time()
        self._last_click_points.append((int(x), int(y), self.last_global_click))
        log.info("INPUT SENT target=%s screen=(%d,%d) via=pydirectinput; game acceptance is not observable here",
                 target.name, x, y)
        return True

    def _script_click(self, action: str, x: int, y: int, **kwargs) -> bool:
        """Scripted input used to dismiss popups. Never recorded by the smart learner,
        never added to targets or reward bookkeeping.

        Supports:
          - drag_down : press at (x,y), move mouse down, release
          - drag_up   : press at (x,y), move mouse up, release
          - double_click, right_click, key: (kept for compatibility)
        """
        if not self.safety.can_click():
            return False
        if self.dry_run:
            log.info("DRY RUN WOULD EXECUTE POPUP ACTION: %s at (%d,%d) with %s", action, x, y, kwargs)
            return True
        if not HAS_DIRECT_INPUT or pydirectinput is None:
            return False
        if self.window.hwnd:
            self.window.focus()
            if self.cfg.require_game_under_cursor and not self.window.owns_point(int(x), int(y)):
                time.sleep(0.05)
                if not self.window.owns_point(int(x), int(y)):
                    return False
        if getattr(self, "smart", None) is not None:
            self.smart.note_bot_click(int(x), int(y))    # the learner ignores this click

        # -------- helper: smooth press-and-move gesture --------
        def _drag(dx_sign: int, dist: int) -> None:
            """Press at (x,y), move vertically by dist*dx_sign, release."""
            pydirectinput.moveTo(int(x), int(y))
            time.sleep(0.05)
            pydirectinput.mouseDown()
            time.sleep(0.08)
            steps = 10
            for i in range(1, steps + 1):
                cy = int(y + (dx_sign * dist * i / steps))
                pydirectinput.moveTo(int(x), cy)
                time.sleep(0.02)
            time.sleep(0.08)
            pydirectinput.mouseUp()

        try:
            if action == "key":
                pydirectinput.press(kwargs.get("key", "esc"))
            elif action == "double_click":
                pydirectinput.moveTo(int(x), int(y))
                pydirectinput.doubleClick()
            elif action == "right_click":
                pydirectinput.moveTo(int(x), int(y))
                pydirectinput.rightClick()
            elif action == "drag_down":
                dist = int(kwargs.get("dist", 150))
                if not hasattr(pydirectinput, "mouseDown") or not hasattr(pydirectinput, "mouseUp"):
                    # Fallback: simple click if drag not supported
                    pydirectinput.moveTo(int(x), int(y))
                    pydirectinput.doubleClick()
                else:
                    _drag(+1, dist)   # +1 = downward
            elif action == "drag_up":
                dist = int(kwargs.get("dist", 150))
                if not hasattr(pydirectinput, "mouseDown") or not hasattr(pydirectinput, "mouseUp"):
                    pydirectinput.moveTo(int(x), int(y))
                    pydirectinput.doubleClick()
                else:
                    _drag(-1, dist)   # -1 = upward
            else:
                log.warning("Unknown popup action: %s", action)
                return False
        except Exception as exc:
            log.error("popup action '%s' failed: %s", action, exc)
            return False

        self.safety.note_click()
        self.last_global_click = time.time()
        log.info("POPUP action '%s' sent at (%d,%d) with %s", action, x, y, kwargs)
        return True
    
    # ---------- zone drawing ----------
    def _draw_zone(self):
        if not HAS_PYNPUT:
            log.warning("pynput missing — cannot draw zones.")
            return
        was_paused = self.paused
        self.paused = True
        time.sleep(0.1)
        log.info("Draw a rectangle to add an EXCLUSION zone (right-click cancel).")
        start = [None]; end = [None]

        def on_click(x, y, button, pressed):
            if button == pmouse.Button.right and pressed: return False
            if button != pmouse.Button.left: return True
            if pressed: start[0] = (int(x), int(y))
            else:
                if start[0] is not None:
                    end[0] = (int(x), int(y)); return False
            return True

        with pmouse.Listener(on_click=on_click) as listener:
            listener.join()

        if start[0] and end[0]:
            x0, y0 = start[0]; x1, y1 = end[0]
            _, frame = self._capture()
            if frame is not None:
                # translate to window-relative
                # find window rect again
                rect, _ = self._capture()
                if rect:
                    lx = min(x0, x1) - rect["left"]
                    ly = min(y0, y1) - rect["top"]
                    w = abs(x1 - x0); h = abs(y1 - y0)
                    if w > 8 and h > 8:
                        self.safety.add_exclusion(lx, ly, w, h)
                        log.info(f"Exclusion added: {[lx, ly, w, h]}")
        self.paused = was_paused

    # ---------- reload ----------
    def _do_reload(self):
        log.info("Reloading targets and watchers…")
        self.library.load()
        self._load_watchers()
        if self.ghost_scene is not None:
            self.ghost_scene.colors.reload()
            self.ghost_scene.calibrate_size()
        mn, mx, _, _ = self.library.seed_profile()
        self.saliency = SaliencyDetector(*self.library.seed_profile(),
                                         max_dimension=min(800, self.cfg.match_max_dimension))


# ============================================================
# CLI
# ============================================================
def list_windows():
    if not HAS_WIN32:
        print("pywin32 not installed.")
        return
    rows = set()
    for w in _enum_top_windows():
        if w["title"].strip():
            rows.add(f"{w['proc'] or '?':<24} {w['title']}")
    for row in sorted(rows):
        print(row)


def main():
    p = argparse.ArgumentParser(description="Highrise Vision Bot — multi-match + persistent reward learning")
    p.add_argument("--window", "-w", default=None, help="Window title substring (only used when no process name is set)")
    p.add_argument("--process", default=None, help="Executable to target, e.g. highrise.exe (default from config)")
    p.add_argument("--root", default=".", help="Project root (holds seeds/, learned/)")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default=None, help="Console and file verbosity")
    p.add_argument("--dry-run", action="store_true",
                   help="Detect and log targets without sending input")
    p.add_argument("--explore", action="store_true",
                   help="Enable cautious exploration (enabled by default; useful to override patient_mode in config)")
    p.add_argument("--patient", action="store_true",
                   help="Disable exploratory clicking; only click imported/learned templates")
    p.add_argument("--no-explore", action="store_true", help="Disable unseen-ghost exploration")
    p.add_argument("--teach", action="store_true",
                   help="Teach mode: the bot sends NO input; it only watches your clicks and learns what a ghost is")
    p.add_argument("--no-smart", action="store_true", help="Disable learn-from-my-clicks")
    p.add_argument("--autoplay", action="store_true",
                   help="Auto play: click with the already-trained smart model only; no learning, labelling or retraining")
    p.add_argument("--scan-every-frame", action="store_true", help="Run the fast color/shape candidate scan on every captured frame")
    p.add_argument("--full-template-every-frame", action="store_true", help="Raise exact template budget to 8 targets/frame (CPU-heavy, but still bounded)")
    p.add_argument("--control-file", default=None, help="Optional JSON file for GUI pause/stop controls")
    p.add_argument("--reset-learned", action="store_true")
    p.add_argument("--max-cps", type=float, default=None)
    p.add_argument("--list-windows", action="store_true")
    p.add_argument("--sync-repository", nargs="?", const=DEFAULT_REPOSITORY, default=None,
                   metavar="OWNER/REPO",
                   help="one-time download and import of all repository images (default: Tenslaster/bloop); no game window needed")
    p.add_argument("--force-reimport", action="store_true",
                   help="re-run image cropping for cached repository images; use with --sync-repository or --reimport-corpus")
    p.add_argument("--reimport-corpus", action="store_true",
                   help="rebuild target crops from corpus/repository without using the network")
    args = p.parse_args()

    if args.list_windows:
        list_windows(); return

    enable_dpi_awareness()
    root = Path(args.root).resolve()
    log_preferences = {}
    try:
        raw_cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
        if isinstance(raw_cfg, dict):
            log_preferences = raw_cfg
    except Exception:
        pass
    setup_logging(
        str(root / "logs"), debug=args.debug, level=args.log_level,
        console_level=log_preferences.get("console_log_level"),
        file_level=log_preferences.get("file_log_level"),
        file_enabled=bool(log_preferences.get("log_file_enabled", True)),
        console_enabled=bool(log_preferences.get("log_console_enabled", True)),
        file_max_mb=log_preferences.get("log_file_max_mb", 12))

    # Repository sync is an explicit one-shot command, never part of the live
    # frame loop; a network timeout therefore cannot stall gameplay detection.
    if args.sync_repository is not None:
        if sync_and_import_repository is None:
            log.error("Repository importer module is missing; keep repository_import.py beside main.py.")
            sys.exit(2)
        try:
            result = sync_and_import_repository(
                root, repository=args.sync_repository, force=args.force_reimport)
            sync_summary = result.get("sync", {}).get("summary", {})
            imp_summary = result.get("import", {})
            log.info("Repository sync: %(remote_images)s image(s) found, %(downloaded)s downloaded, %(up_to_date)s unchanged, %(watchers)s watcher(s), %(unsupported_or_failed)s failure(s)",
                     sync_summary)
            log.info("Image import: %(sources_seen)s source(s) processed, %(target_crops_added)s new target crop(s), %(duplicate_crops)s duplicate(s), %(pending_review)s pending scene(s), %(failed)s failure(s)",
                     imp_summary)
            if result.get("sync", {}).get("failed"):
                log.warning("Some downloads failed. Re-run --sync-repository later to retry.")
            if imp_summary.get("pending_review", 0):
                log.warning("Some full-scene images were preserved under corpus/pending and NOT activated as click targets. See corpus/repository_import_report.json.")
        except Exception as exc:
            log.error("Repository image sync/import failed: %s", exc)
            log.error("No images were clicked. Check the connection and retry --sync-repository.")
            sys.exit(2)
        return

    if args.reimport_corpus:
        if build_target_templates is None:
            log.error("Repository importer module is missing; keep repository_import.py beside main.py.")
            sys.exit(2)
        try:
            summary = build_target_templates(root, force=args.force_reimport)
            log.info("Cached corpus processed: %(target_crops_added)s new crops, %(duplicate_crops)s duplicates, %(pending_review)s pending scene(s)", summary)
            return
        except Exception as exc:
            log.error("Could not re-import cached repository images: %s", exc)
            sys.exit(2)

    if args.force_reimport:
        p.error("--force-reimport must be paired with --sync-repository or --reimport-corpus")

    if HAS_DIRECT_INPUT and pydirectinput is not None:
        pydirectinput.PAUSE = 0.01

    if args.reset_learned:
        import shutil
        learned = root / "learned"
        if learned.exists(): shutil.rmtree(learned)
        log.info("learned/ wiped.")

    cfg = load_config(root / "config.json")
    if args.window:
        cfg.window_title = args.window
    if args.process is not None:
        cfg.window_process = exe_name(args.process)
    if args.max_cps is not None:
        cfg.max_cps = max(0.0, min(float(args.max_cps), 20.0))

    if args.explore:
        cfg.patient_mode = False
    if args.patient or args.no_explore:
        cfg.patient_mode = True
    if args.scan_every_frame:
        cfg.scan_every_frame = True
        cfg.skip_unchanged_frames = False
    if args.full_template_every_frame:
        # This troubleshooting flag raises the per-frame exact-match budget to
        # the maximum supported value; it no longer runs every template in one
        # huge blocking call.
        cfg.template_targets_per_frame = 8

    if not cfg.window_title and not cfg.window_process:
        log.error("No target. Set window_process (e.g. highrise.exe) in config.json or pass --process.")
        sys.exit(1)

    if args.no_smart:
        cfg.smart_learning = False
    if args.teach:
        cfg.smart_clicking = False
    if args.autoplay:
        cfg.smart_learning = True        # the smart detector must load (it just never learns)
        cfg.smart_autoplay = True
        cfg.smart_clicking = True
        cfg.smart_exclusive = True       # only the model clicks: no seed / explore fallback
        cfg.patient_mode = True
    bot = AutonomousBot(cfg, root, dry_run=args.dry_run or args.teach)
    if args.autoplay and (bot.smart is None or not bot.smart.ready()):
        log.error("AUTO PLAY needs a trained model in smart/ (model.npz). Run Live or Preview with learning first, "
                  "or use Retrain on the Learning page, then try Auto play again.")
        sys.exit(0)                      # exit 0 so the GUI crash watchdog does not restart-loop
    if args.control_file:
        bot.control_file = Path(args.control_file).resolve()
        bot.control_file.parent.mkdir(parents=True, exist_ok=True)
        bot._poll_control_file()

    # Hotkeys are useful but optional. Ctrl+C remains available even when the
    # keyboard package is unavailable or Windows accessibility blocks it.
    if HAS_KEYBOARD and keyboard is not None:
        try:
            keyboard.add_hotkey(cfg.hk_pause, bot.toggle_pause)
            keyboard.add_hotkey(cfg.hk_quit, bot.stop)
            keyboard.add_hotkey(cfg.hk_zone, bot.request_zone)
            keyboard.add_hotkey(cfg.hk_reload, bot.request_reload)
            if bot.smart is not None:
                keyboard.add_hotkey(cfg.hk_bad, bot.smart.mark_bad)
            f4 = bot.teacher is not None and cfg.overlay_teach and bot.teacher.has_overlay
            if f4:
                keyboard.add_hotkey(cfg.hk_teach, bot.teacher.request_toggle)
            log.info("Hotkeys registered (F9 pause, F7 exclusion, F10 reload, F8 bad-click, F12 quit%s).",
                     f", {cfg.hk_teach.upper()} teach mode" if f4 else "")
        except Exception as exc:
            log.warning("Could not register global hotkeys (%s); use Ctrl+C to quit.", exc)
    else:
        log.warning("keyboard package unavailable; global hotkeys disabled. Ctrl+C still works.")

    try:
        bot.run()
    except KeyboardInterrupt:
        bot.stop()


if __name__ == "__main__":
    main()