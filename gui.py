#!/usr/bin/env python3
"""BLOOP Control Panel v2 - dark desktop control panel for the Highrise Vision Bot.

Tkinter only (no extra GUI dependency). Layout: sidebar navigation, a live dashboard
(metrics, Ectoplaz session tracker, filterable log), searchable settings pages, a
sample-library page (counts, duplicate remover, retrain) and a Discord webhook page.
"""
from __future__ import annotations

import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

import main as botmod

# ------------------------------------------------------------------ palette
BG = "#0a0f1c"
SIDE = "#0d1424"
PANEL = "#111a2e"
PANEL2 = "#16213a"
EDGE = "#26344f"
TEXT = "#e8eefc"
MUTED = "#8fa0bb"
ACCENT = "#54e0c1"
BLUE = "#65a8ff"
ORANGE = "#ffba66"
RED = "#ff6e83"
GREEN = "#76e4a5"
PURPLE = "#b69cff"

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

NAV = (
    ("dashboard", "Overview", "◉", "Run controls, live health, activity and quick links"),
    ("runtime", "Runtime & Speed", "⚙", "Game window, capture, CPU budget and scan cadence"),
    ("detection", "Vision & Detection", "◎", "Matching thresholds, scales and reward watchers"),
    ("learning", "Learning & Safety", "✦", "Smart learning, click policy, cooldowns and popup handling"),
    ("samples", "Model & Samples", "▦", "Training library, sample review, cleanup and retraining"),
    ("webhook", "Rewards & Webhook", "✉", "Ectoplaz tracking and Discord reporting"),
    ("logs", "Diagnostics", "≡", "Logs, image diagnostics and repository import"),
    ("advanced", "Advanced Settings", "⋯", "All remaining engine settings, hotkeys and experimental switches"),
)

DUP_MODES = {"Strict (near-exact only)": 0.8, "Normal": 2.0, "Loose (more aggressive)": 4.0}
LOG_FILTERS = ("All messages", "Hide debug", "Problems only")
ECTO_RE = re.compile(r"ectoplaz \+(\d[\d,]*)")


def redact_webhook_error(text: object, webhook_url: str = "") -> str:
    """Remove Discord webhook credentials from exception/status text before UI/logging."""
    value = str(text)
    if webhook_url:
        value = value.replace(str(webhook_url), "<webhook-redacted>")
    value = re.sub(
        r"https?://(?:canary\.)?discord(?:app)?\.com/api/webhooks/[^\s/?]+/[^\s?]+",
        "https://discord.com/api/webhooks/<redacted>", value, flags=re.IGNORECASE)
    return value[:240]


class VisionGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.project = Path(__file__).resolve().parent
        self.config_path = self.project / "config.json"
        self.control_path = self.project / ".runtime" / "gui_control.json"
        self.proc: subprocess.Popen | None = None
        self.reader_thread: threading.Thread | None = None
        self.lines: queue.Queue = queue.Queue()
        self.last_exit_code: int | None = None
        self.click_count = 0
        self.detect_count = 0
        self.learn_count = 0
        self.reward_count = 0
        self.started_at: float | None = None
        self.pause_requested = False
        self._live_mode_active = False
        self._iconifying_for_live = False
        self._live_start_pending = False
        self.console_lines = 0
        self._user_stop = False          # True only when the user asked to stop
        self._last_command = None        # (command, mode, dry_run) for auto-restart
        self._restart_delay = 2.0
        self._restart_job = None
        self._restarting = False
        # navigation / pages
        self.pages: dict[str, dict] = {}
        self.nav_buttons: dict[str, tk.Button] = {}
        self.current_page: str | None = None
        self._building_page = "dashboard"
        self.field_registry: list[dict] = []
        self._wheel_bindings_installed = False
        # state
        self._dirty = False
        self._loading = True
        self._dedupe_busy = False
        self._ui_queue: queue.Queue = queue.Queue()   # callables posted by worker threads
        # Ectoplaz session tracker (parsed from the bot's log)
        self.ecto_total = 0
        self.ecto_drops = 0
        self.ecto_started: float | None = None
        self._load_config()
        self._build_style()
        self._build_ui()
        for var in self.vars.values():
            var.trace_add("write", self._mark_dirty)
        self._loading = False
        self._bind_shortcuts()
        self._show_page("dashboard")
        self.root.after(100, self._drain_queue)
        self.root.after(100, self._pump_ui)
        self.root.after(500, self._refresh_metrics)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Map>", self._on_gui_restored, add="+")

    # ------------------------------------------------------------------ config
    def _load_config(self):
        self.cfg = botmod.load_config(self.config_path)
        self.vars: dict[str, tk.Variable] = {}
        self.types: dict[str, str] = {}
        for key, value in vars(self.cfg).items():
            if key == "exclusion_zones":
                variable = tk.StringVar(value=json.dumps(value))
                kind = "json"
            elif isinstance(value, bool):
                variable = tk.BooleanVar(value=value)
                kind = "bool"
            elif isinstance(value, (list, tuple)):
                variable = tk.StringVar(value=", ".join(str(x) for x in value))
                kind = "list"
            elif isinstance(value, int):
                variable = tk.StringVar(value=str(value))
                kind = "int"
            elif isinstance(value, float):
                variable = tk.StringVar(value=f"{value:g}")
                kind = "float"
            else:
                variable = tk.StringVar(value=str(value))
                kind = "str"
            self.vars[key] = variable
            self.types[key] = kind
        # Repository belongs to the importer, not Config; create the field before
        # building the UI so opening the GUI never fails with a missing key.
        self.vars["repo_name"] = tk.StringVar(value="Tenslaster/bloop")
        self.types["repo_name"] = "str"
        self.vars["auto_learning"] = tk.BooleanVar(value=not self.cfg.patient_mode)
        self.types["auto_learning"] = "bool"
        self.reported_fps: float | None = None
        self.reported_tick_ms: float | None = None

    def _ui(self, fn):
        """Thread-safe: run fn() on the Tk thread (worker threads must never touch widgets)."""
        self._ui_queue.put(fn)

    def _pump_ui(self):
        for _ in range(100):
            try:
                fn = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception as exc:
                self._append_log(f"[GUI ERROR] {exc}\n", "error")
        self.root.after(80, self._pump_ui)

    def _mark_dirty(self, *_):
        if self._loading:
            return
        self._set_dirty(True)

    def _set_dirty(self, value: bool):
        self._dirty = value
        if hasattr(self, "dirty_lbl"):
            self.dirty_lbl.configure(text="● Unsaved changes · restart to apply" if value else "● All settings saved",
                                     fg=ORANGE if value else MUTED)

    # ------------------------------------------------------------------ style
    def _build_style(self):
        self.root.title("BLOOP · Highrise Control")
        # Fit common laptop displays and Windows DPI scaling; maximize is a convenience,
        # not a requirement for the UI to remain usable.
        self.root.geometry("1180x800")
        self.root.minsize(900, 600)
        try:
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            if sw >= 1180 and sh >= 800:
                self.root.state("zoomed")
            else:
                self.root.geometry(f"{min(1180, sw-40)}x{min(800, sh-80)}+20+20")
        except tk.TclError:
            pass
        self.root.configure(bg=BG)
        self.root.option_add("*TCombobox*Listbox.background", "#0a1222")
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#1a3a50")
        self.root.option_add("*TCombobox*Listbox.selectForeground", ACCENT)
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("TLabelframe", background=PANEL, foreground=TEXT, bordercolor=EDGE)
        style.configure("TLabelframe.Label", background=PANEL, foreground=ACCENT, font=("Segoe UI Semibold", 9))
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=SIDE, foreground=MUTED, padding=(14, 8), font=("Segoe UI Semibold", 9))
        style.map("TNotebook.Tab", background=[("selected", PANEL2), ("active", PANEL)], foreground=[("selected", ACCENT), ("active", TEXT)])
        style.configure("TButton", background=PANEL2, foreground=TEXT, bordercolor=EDGE,
                        lightcolor=PANEL2, darkcolor=PANEL2, focuscolor=ACCENT,
                        padding=(11, 7), font=("Segoe UI Semibold", 9), relief="flat")
        style.map("TButton", background=[("active", "#26395a"), ("disabled", "#1b2538")],
                  foreground=[("disabled", "#5f6f88")])
        style.configure("Accent.TButton", background="#147c75", foreground="#ffffff",
                        bordercolor="#239d90", lightcolor="#147c75", darkcolor="#147c75",
                        padding=(16, 10), font=("Segoe UI Semibold", 10))
        style.map("Accent.TButton", background=[("active", "#16988d"), ("disabled", "#1b2538")])
        style.configure("Live.TButton", background="#8a3349", foreground="#ffffff",
                        bordercolor="#bd4d68", lightcolor="#8a3349", darkcolor="#8a3349",
                        padding=(16, 10), font=("Segoe UI Semibold", 10))
        style.map("Live.TButton", background=[("active", "#a33e59"), ("disabled", "#1b2538")])
        style.configure("Danger.TButton", background="#3b1d2b", foreground="#ffb3c0",
                        bordercolor="#6b2c40", lightcolor="#3b1d2b", darkcolor="#3b1d2b",
                        padding=(14, 10), font=("Segoe UI Semibold", 10))
        style.map("Danger.TButton", background=[("active", "#55273b"), ("disabled", "#1b2538")],
                  foreground=[("disabled", "#5f6f88")])
        style.configure("Save.TButton", background="#1d4ed8", foreground="#ffffff",
                        bordercolor="#3b6cf0", lightcolor="#1d4ed8", darkcolor="#1d4ed8",
                        padding=(14, 10), font=("Segoe UI Semibold", 10))
        style.map("Save.TButton", background=[("active", "#2b61f0")])
        # Compact variants keep the global run controls usable on 900px-wide laptops.
        style.configure("Dock.TButton", background=PANEL2, foreground=TEXT, bordercolor=EDGE,
                        lightcolor=PANEL2, darkcolor=PANEL2, focuscolor=ACCENT,
                        padding=(7, 5), font=("Segoe UI Semibold", 9))
        style.map("Dock.TButton", background=[("active", "#26395a"), ("disabled", "#1b2538")],
                  foreground=[("disabled", "#5f6f88")])
        style.configure("Dock.Accent.TButton", background="#147c75", foreground="#ffffff",
                        bordercolor="#239d90", lightcolor="#147c75", darkcolor="#147c75",
                        padding=(8, 5), font=("Segoe UI Semibold", 9))
        style.map("Dock.Accent.TButton", background=[("active", "#16988d"), ("disabled", "#1b2538")])
        style.configure("Dock.Live.TButton", background="#8a3349", foreground="#ffffff",
                        bordercolor="#bd4d68", lightcolor="#8a3349", darkcolor="#8a3349",
                        padding=(8, 5), font=("Segoe UI Semibold", 9))
        style.map("Dock.Live.TButton", background=[("active", "#a33e59"), ("disabled", "#1b2538")])
        style.configure("Dock.Danger.TButton", background="#3b1d2b", foreground="#ffb3c0",
                        bordercolor="#6b2c40", lightcolor="#3b1d2b", darkcolor="#3b1d2b",
                        padding=(7, 5), font=("Segoe UI Semibold", 9))
        style.map("Dock.Danger.TButton", background=[("active", "#55273b"), ("disabled", "#1b2538")])
        style.configure("Dock.Save.TButton", background="#1d4ed8", foreground="#ffffff",
                        bordercolor="#3b6cf0", lightcolor="#1d4ed8", darkcolor="#1d4ed8",
                        padding=(8, 5), font=("Segoe UI Semibold", 9))
        style.map("Dock.Save.TButton", background=[("active", "#2b61f0")])
        style.configure("TEntry", fieldbackground="#0a1222", foreground=TEXT,
                        bordercolor=EDGE, lightcolor=EDGE, darkcolor=EDGE, insertcolor=TEXT, padding=7)
        style.map("TEntry", bordercolor=[("focus", ACCENT), ("!focus", EDGE)])
        style.configure("TCombobox", fieldbackground="#0a1222", background=PANEL2,
                        foreground=TEXT, arrowcolor=ACCENT, bordercolor=EDGE, padding=6)
        style.map("TCombobox", fieldbackground=[("readonly", "#0a1222")],
                  foreground=[("readonly", TEXT)])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT,
                        font=("Segoe UI", 9), padding=4)
        style.map("TCheckbutton", background=[("active", PANEL)], foreground=[("active", ACCENT)])
        style.configure("Vertical.TScrollbar", background=EDGE, troughcolor=BG, bordercolor=BG,
                        arrowcolor=MUTED, lightcolor=EDGE, darkcolor=EDGE)
        style.configure("Horizontal.TProgressbar", troughcolor="#0a1222", background=ACCENT,
                        bordercolor=EDGE, lightcolor=ACCENT, darkcolor=ACCENT)

    # ------------------------------------------------------------------ layout
    def _build_ui(self):
        self.metric_vars = {k: tk.StringVar(value=v) for k, v in {
            "fps": "—", "detections": "0", "clicks": "0", "learned": "0", "rewards": "0", "uptime": "—",
        }.items()}
        self.ecto_total_var = tk.StringVar(value="0")
        self.ecto_drops_var = tk.StringVar(value="0")
        self.ecto_rate_var = tk.StringVar(value="—")
        self.ecto_last_var = tk.StringVar(value="—")

        shell = tk.Frame(self.root, bg=BG)
        shell.pack(fill="both", expand=True)
        self._build_sidebar(shell)
        main = tk.Frame(shell, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        self._build_topbar(main)
        # A persistent command dock means start / pause / stop are reachable from
        # every page; users never have to navigate back to Overview to control a run.
        self._build_command_dock(main)
        self.page_host = tk.Frame(main, bg=BG)
        self.page_host.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        self._build_dashboard()
        self._build_runtime_page()
        self._build_detection_page()
        self._build_learning_page()
        self._build_samples_page()
        self._build_webhook_page()
        self._build_logs_page()
        self._build_advanced_page()
        self._build_search_popup()
        self._install_tooltips()

    def _build_command_dock(self, parent):
        dock = tk.Frame(parent, bg=SIDE, highlightthickness=1, highlightbackground=EDGE, padx=14, pady=8)
        dock.pack(side="bottom", fill="x", padx=16, pady=(0, 10))
        dock.grid_columnconfigure(0, weight=1)
        left = tk.Frame(dock, bg=SIDE)
        left.grid(row=0, column=0, rowspan=2, sticky="ew", padx=(0, 12))
        self.dock_status = tk.Label(left, text="● READY", bg=SIDE, fg=ACCENT,
                                    font=("Segoe UI Semibold", 10))
        self.dock_status.pack(anchor="w")
        actions = tk.Frame(dock, bg=SIDE)
        actions.grid(row=0, column=1, rowspan=2, sticky="e")
        self.preview_btn = ttk.Button(actions, text="Preview", style="Dock.Accent.TButton",
                                      command=lambda: self._start_bot(dry_run=True))
        self.preview_btn.pack(side="left", padx=(0, 5))
        self.live_btn = ttk.Button(actions, text="▶ Live", style="Dock.Live.TButton",
                                   command=lambda: self._start_bot(dry_run=False))
        self.live_btn.pack(side="left", padx=5)
        self.autoplay_btn = ttk.Button(actions, text="⚡ Auto play", style="Dock.Live.TButton",
                                       command=lambda: self._start_bot(dry_run=False, autoplay=True))
        self.autoplay_btn.pack(side="left", padx=5)
        self.pause_btn = ttk.Button(actions, text="Ⅱ Pause", style="Dock.TButton", command=self._toggle_pause, state="disabled")
        self.pause_btn.pack(side="left", padx=5)
        self.stop_btn = ttk.Button(actions, text="■ Stop", style="Dock.Danger.TButton",
                                   command=self._stop_process, state="disabled")
        self.stop_btn.pack(side="left", padx=5)
        self.teach_btn = ttk.Button(actions, text="✎ Teach", style="Dock.TButton", command=self._open_teach_window)
        self.teach_btn.pack(side="left", padx=5)
        ttk.Button(actions, text="Save", style="Dock.Save.TButton", command=self._save_settings).pack(side="left", padx=(5, 0))
        self.dirty_lbl = tk.Label(dock, text="● All settings saved", bg=SIDE, fg=MUTED,
                                  font=("Segoe UI", 8))
        self.dirty_lbl.grid(row=2, column=0, sticky="w", pady=(5, 0))

    def _build_sidebar(self, shell):
        side = tk.Frame(shell, bg=SIDE, width=218)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        brand = tk.Frame(side, bg=SIDE, padx=22, pady=22)
        brand.pack(fill="x")
        tk.Label(brand, text="BLOOP", fg=ACCENT, bg=SIDE, font=("Segoe UI Black", 22)).pack(anchor="w")
        tk.Label(brand, text="HIGHRISE VISION CONTROL", fg=MUTED, bg=SIDE,
                 font=("Consolas", 8, "bold")).pack(anchor="w")
        nav = tk.Frame(side, bg=SIDE)
        nav.pack(fill="x", pady=(6, 0))
        for index, (key, label, icon, _sub) in enumerate(NAV, 1):
            row = tk.Frame(nav, bg=SIDE)
            row.pack(fill="x")
            bar = tk.Frame(row, bg=SIDE, width=4)
            bar.pack(side="left", fill="y")
            btn = tk.Button(row, text=f"  {icon}   {label}", anchor="w", relief="flat", bd=0,
                            bg=SIDE, fg=MUTED, activebackground=PANEL2, activeforeground=TEXT,
                            font=("Segoe UI Semibold", 9), padx=12, pady=8, cursor="hand2", highlightthickness=0, takefocus=0,
                            command=lambda k=key: self._show_page(k))
            btn.pack(side="left", fill="x", expand=True)
            btn.bind("<Enter>", lambda _e, k=key: self._nav_hover(k, True))
            btn.bind("<Leave>", lambda _e, k=key: self._nav_hover(k, False))
            self.nav_buttons[key] = btn
            btn._bar = bar  # type: ignore[attr-defined]
            self.root.bind_all(f"<Control-Key-{index}>", lambda _e, k=key: self._show_page(k))
        bottom = tk.Frame(side, bg=SIDE, padx=18, pady=14)
        bottom.pack(side="bottom", fill="x")
        tk.Label(bottom, text="CTRL+S  ·  SAVE SETTINGS", bg=SIDE, fg=MUTED,
                 font=("Consolas", 8, "bold")).pack(anchor="w")
        tk.Label(bottom, text="Changes apply on next run", bg=SIDE, fg="#647895",
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(4, 0))

    def _nav_hover(self, key, inside):
        if key == self.current_page:
            return
        self.nav_buttons[key].configure(bg=PANEL if inside else SIDE,
                                        fg=TEXT if inside else MUTED)

    def _build_topbar(self, main):
        top = tk.Frame(main, bg=BG, padx=20, pady=13)
        top.pack(fill="x")
        left = tk.Frame(top, bg=BG)
        left.pack(side="left")
        self.page_title = tk.Label(left, text="", bg=BG, fg=TEXT, font=("Segoe UI Semibold", 18))
        self.page_title.pack(anchor="w")
        self.page_sub = tk.Label(left, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9))
        self.page_sub.pack(anchor="w", pady=(2, 0))
        right = tk.Frame(top, bg=BG)
        right.pack(side="right")
        self.status_pill = tk.Label(right, text="● STANDBY", fg=ACCENT, bg="#12352f",
                                    font=("Consolas", 9, "bold"), padx=12, pady=7)
        self.status_pill.pack(side="right", padx=(14, 0))
        box = tk.Frame(right, bg=PANEL, highlightthickness=1, highlightbackground=EDGE)
        box.pack(side="right")
        tk.Label(box, text="⌕", bg=PANEL, fg=ACCENT, font=("Segoe UI", 12)).pack(side="left", padx=(8, 0))
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(box, textvariable=self.search_var, width=25, bg=PANEL, fg=MUTED,
                                     insertbackground=TEXT, relief="flat", highlightthickness=0, font=("Segoe UI", 10))
        self.search_placeholder = "Search settings…"
        self._search_placeholder_active = True
        self.search_var.set(self.search_placeholder)
        self.search_entry.pack(side="left", padx=6, pady=7)
        self.search_entry.bind("<FocusIn>", self._search_focus_in, add="+")
        self.search_entry.bind("<FocusOut>", self._search_focus_out, add="+")
        tk.Label(box, text="Ctrl+K", bg=PANEL, fg=MUTED, font=("Consolas", 8)).pack(side="left", padx=(0, 8))

    # ----------------------------------------------------------- reusable widgets
    def _fit_label_to_holder(self, holder, label_widget, inset=20, min_width=110, max_width=420):
        """Keep captions/help text inside their responsive settings card/field."""
        def fit(_event=None):
            try:
                width = int(holder.winfo_width()) - int(inset)
                if width > 40:
                    label_widget.configure(wraplength=max(min_width, min(max_width, width)))
            except tk.TclError:
                pass
        holder.bind("<Configure>", fit, add="+")
        self.root.after_idle(fit)

    def _card(self, parent, title, subtitle=None, expand=False, color=ACCENT):
        outer = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=EDGE)
        outer.pack(fill="both" if expand else "x", expand=expand, pady=(0, 10))
        head = tk.Frame(outer, bg=PANEL)
        head.pack(fill="x", padx=14, pady=(10, 0))
        tk.Label(head, text=title.upper(), bg=PANEL, fg=color, font=("Consolas", 9, "bold")).pack(side="left")
        if subtitle:
            sub_label = tk.Label(outer, text=subtitle, bg=PANEL, fg=MUTED, font=("Segoe UI", 8),
                                 wraplength=900, justify="left", anchor="w")
            sub_label.pack(anchor="w", fill="x", padx=16, pady=(4, 0))
            self._fit_label_to_holder(outer, sub_label, inset=32, min_width=180, max_width=900)
        inner = tk.Frame(outer, bg=PANEL)
        inner.pack(fill="both", expand=expand, padx=14, pady=(7, 11))
        return inner, head

    def _tile(self, parent, title, var, color, column, columns, row=0):
        box = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=EDGE, padx=14, pady=10)
        box.grid(row=row, column=column, sticky="nsew", padx=(0 if column == 0 else 7, 0), pady=(0, 7))
        parent.grid_columnconfigure(column, weight=1, uniform="tile")
        tk.Label(box, text=title, bg=PANEL, fg=MUTED, font=("Consolas", 8, "bold")).pack(anchor="w")
        tk.Label(box, textvariable=var, bg=PANEL, fg=color, font=("Segoe UI Semibold", 20)).pack(anchor="w", pady=(3, 0))

    def _make_page(self, key: str, scroll: bool):
        """Create a page frame inside page_host (not shown until selected)."""
        self._building_page = key
        if not scroll:
            frame = tk.Frame(self.page_host, bg=BG)
            self.pages[key] = {"outer": frame, "canvas": None, "content": frame}
            return frame
        outer = tk.Frame(self.page_host, bg=BG)
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0, borderwidth=0, yscrollincrement=24, takefocus=True)
        vertical = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vertical.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        content = tk.Frame(canvas, bg=BG, padx=0, pady=4)
        win_id = canvas.create_window((0, 0), window=content, anchor="nw")

        def update_scrollregion(_event=None):
            def apply_region():
                if not canvas.winfo_exists() or not content.winfo_exists():
                    return
                bbox = canvas.bbox("all")
                canvas.configure(scrollregion=bbox if bbox else (0, 0, 1, 1))
            self.root.after_idle(apply_region)

        def fit_width(event):
            canvas.itemconfigure(win_id, width=max(1, event.width))
            update_scrollregion()

        content.bind("<Configure>", update_scrollregion, add="+")
        canvas.bind("<Configure>", fit_width, add="+")
        canvas.bind("<Enter>", lambda _e: canvas.focus_set(), add="+")
        self.pages[key] = {"outer": outer, "canvas": canvas, "content": content}
        if not self._wheel_bindings_installed:
            self.root.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
            self.root.bind_all("<Button-4>", self._on_mousewheel, add="+")
            self.root.bind_all("<Button-5>", self._on_mousewheel, add="+")
            self.root.bind_all("<Prior>", self._on_scroll_key, add="+")
            self.root.bind_all("<Next>", self._on_scroll_key, add="+")
            self.root.bind_all("<Control-Home>", self._on_scroll_key, add="+")
            self.root.bind_all("<Control-End>", self._on_scroll_key, add="+")
            self._wheel_bindings_installed = True
        content.grid_columnconfigure((0, 1), weight=1)
        return content

    def _group(self, parent, title, row, column=0, columnspan=1, subtitle=None):
        frame = tk.Frame(parent, bg=PANEL, padx=16, pady=12, highlightthickness=1, highlightbackground=EDGE)
        frame.grid(row=row, column=column, columnspan=columnspan, sticky="nsew", padx=(0, 10), pady=(0, 10))
        tk.Label(frame, text=title.upper(), bg=PANEL, fg=ACCENT, font=("Consolas", 9, "bold")).pack(anchor="w")
        if subtitle:
            sub_label = tk.Label(frame, text=subtitle, bg=PANEL, fg=MUTED, font=("Segoe UI", 8),
                                 wraplength=470, justify="left", anchor="w")
            sub_label.pack(anchor="w", fill="x", pady=(4, 6))
            self._fit_label_to_holder(frame, sub_label, inset=36, min_width=150, max_width=650)
        inner = tk.Frame(frame, bg=PANEL)
        inner.pack(fill="both", expand=True, pady=(6, 0))
        inner.grid_columnconfigure((0, 1), weight=1)
        return inner

    def _register(self, label, holder, key=None):
        search_key = key or ""
        if search_key == "auto_learning":
            search_key += " patient_mode exploration mode"
        self.field_registry.append({"label": label, "key": search_key, "page": self._building_page, "holder": holder})

    def _field(self, parent, label, key, row, col=0, width=18, secret=False, help_text=None):
        holder = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=EDGE, padx=4, pady=4)
        holder.grid(row=row, column=col, sticky="ew", padx=3, pady=4)
        holder.grid_columnconfigure(0, weight=1)
        title_label = tk.Label(holder, text=label, bg=PANEL, fg=TEXT, font=("Segoe UI Semibold", 9),
                               wraplength=185, justify="left", anchor="w")
        title_label.grid(row=0, column=0, sticky="ew", padx=2)
        self._fit_label_to_holder(holder, title_label, inset=18, min_width=105, max_width=320)
        var = self.vars[key]
        if key == "capture_method":
            widget = ttk.Combobox(holder, textvariable=var, values=("screen", "printwindow"), state="readonly", width=width)
        elif key in ("console_log_level", "file_log_level"):
            widget = ttk.Combobox(holder, textvariable=var, values=LEVELS, state="readonly", width=width)
        elif key == "exclusion_zones":
            self.exclusion_summary_var = tk.StringVar(value=self._zone_summary())
            widget = ttk.Button(holder, text="Edit rectangles…", command=self._edit_exclusion_zones)
            widget.grid(row=1, column=0, sticky="w", pady=(5, 2), padx=2)
            summary = tk.Label(holder, textvariable=self.exclusion_summary_var, bg=PANEL, fg=MUTED,
                               font=("Segoe UI", 8), anchor="w")
            summary.grid(row=2, column=0, sticky="ew", padx=2, pady=(2, 0))
            self.vars[key].trace_add("write", lambda *_: self._refresh_zone_summary())
            if help_text:
                help_label = tk.Label(holder, text=help_text, bg=PANEL, fg="#8495b2", font=("Segoe UI", 8),
                                      wraplength=180, justify="left", anchor="w")
                help_label.grid(row=3, column=0, sticky="ew", padx=2, pady=(3, 0))
                self._fit_label_to_holder(holder, help_label, inset=18, min_width=105, max_width=320)
            self._register(label, holder, key)
            return widget
        else:
            widget = ttk.Entry(holder, textvariable=var, width=width, show="•" if secret else "")
        widget.grid(row=1, column=0, sticky="ew", pady=(5, 2), padx=2)
        if help_text:
            help_label = tk.Label(holder, text=help_text, bg=PANEL, fg="#8495b2", font=("Segoe UI", 8),
                                  wraplength=180, justify="left", anchor="w")
            help_label.grid(row=2, column=0, sticky="ew", padx=2, pady=(3, 0))
            self._fit_label_to_holder(holder, help_label, inset=18, min_width=105, max_width=320)
        self._register(label, holder, key)
        return widget

    def _check(self, parent, label, key, row, col=0, help_text=None):
        holder = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=EDGE, padx=5, pady=4)
        holder.grid(row=row, column=col, sticky="ew", padx=3, pady=4)
        cb = ttk.Checkbutton(holder, text=label, variable=self.vars[key])
        cb.pack(anchor="w")
        if help_text:
            help_label = tk.Label(holder, text=help_text, bg=PANEL, fg="#8495b2", font=("Segoe UI", 8),
                                  wraplength=180, justify="left", anchor="w")
            help_label.pack(anchor="w", fill="x", padx=4, pady=(2, 0))
            self._fit_label_to_holder(holder, help_label, inset=22, min_width=105, max_width=320)
        self._register(label, holder, key)
        return cb

    def _zone_summary(self):
        try:
            zones = json.loads(str(self.vars["exclusion_zones"].get()) or "[]")
            return f"{len(zones)} exclusion rectangle(s)"
        except Exception:
            return "Invalid JSON — open editor to correct"

    def _refresh_zone_summary(self):
        if hasattr(self, "exclusion_summary_var"):
            self.exclusion_summary_var.set(self._zone_summary())

    def _edit_exclusion_zones(self):
        top = tk.Toplevel(self.root)
        top.title("Edit exclusion zones")
        top.configure(bg=BG)
        top.geometry("560x420")
        top.transient(self.root)
        top.grab_set()
        tk.Label(top, text="Exclusion rectangles", bg=BG, fg=TEXT,
                 font=("Segoe UI Semibold", 14)).pack(anchor="w", padx=16, pady=(14, 3))
        tk.Label(top, text="JSON format: [[x, y, width, height], ...]. Coordinates are relative to the captured game frame.",
                 bg=BG, fg=MUTED, wraplength=520, justify="left").pack(anchor="w", padx=16, pady=(0, 8))
        text = tk.Text(top, bg="#070c17", fg=TEXT, insertbackground=TEXT, relief="flat",
                       font=("Consolas", 10), wrap="none", undo=True)
        text.pack(fill="both", expand=True, padx=16, pady=8)
        text.insert("1.0", str(self.vars["exclusion_zones"].get()))
        buttons = tk.Frame(top, bg=BG)
        buttons.pack(fill="x", padx=16, pady=(0, 14))
        def apply():
            try:
                data = json.loads(text.get("1.0", "end-1c").strip() or "[]")
                if not isinstance(data, list) or any(not isinstance(z, list) or len(z) != 4 for z in data):
                    raise ValueError("Each exclusion zone must contain exactly [x, y, width, height].")
                for zone in data:
                    if any(not isinstance(v, (int, float)) for v in zone) or zone[2] <= 0 or zone[3] <= 0:
                        raise ValueError("Zone coordinates must be numeric and width/height positive.")
                self.vars["exclusion_zones"].set(json.dumps(data))
                top.destroy()
            except Exception as exc:
                messagebox.showerror("Invalid exclusion zones", str(exc), parent=top)
        ttk.Button(buttons, text="Cancel", command=top.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="Apply", style="Accent.TButton", command=apply).pack(side="right")

    def _install_tooltips(self):
        # Lightweight hover help for the main actions. Detailed field explanations are
        # also shown inline on Advanced Settings to avoid forcing users to hover every item.
        tips = {
            getattr(self, "preview_btn", None): "Capture and detect targets without sending any mouse input. Switches to Highrise automatically.",
            getattr(self, "live_btn", None): "Start real input. Verify Preview first.",
            getattr(self, "autoplay_btn", None): "Play with the already-trained model. Real clicks, but nothing is learned or retrained.",
            getattr(self, "pause_btn", None): "Pause or resume the engine. Resume may hide the controller first.",
            getattr(self, "stop_btn", None): "Request a clean shutdown and persistence save; force-stop is a fallback.",
        }
        for widget, text in tips.items():
            if widget is not None:
                widget.bind("<Enter>", lambda _e, w=widget, t=text: self._set_status_hint(t), add="+")
                widget.bind("<Leave>", lambda _e: self._set_status_hint(""), add="+")


    # ------------------------------------------------------------ scrolling helpers
    def _selected_scroll_entry(self):
        entry = self.pages.get(self.current_page or "")
        return entry if entry and entry.get("canvas") is not None else None

    def _pointer_is_over(self, widget, x_root: int, y_root: int) -> bool:
        try:
            if not widget.winfo_viewable():
                return False
            left, top = widget.winfo_rootx(), widget.winfo_rooty()
            return left <= x_root < left + widget.winfo_width() and top <= y_root < top + widget.winfo_height()
        except tk.TclError:
            return False

    def _on_mousewheel(self, event):
        entry = self._selected_scroll_entry()
        if entry is None or not self._pointer_is_over(entry["outer"], event.x_root, event.y_root):
            return None
        canvas = entry["canvas"]
        if getattr(event, "num", None) == 4:
            units = -3
        elif getattr(event, "num", None) == 5:
            units = 3
        else:
            delta = int(getattr(event, "delta", 0))
            if delta == 0:
                return "break"
            units = int(-delta / 120 * 3)
            if units == 0:
                units = -1 if delta > 0 else 1
        canvas.yview_scroll(units, "units")
        return "break"

    def _on_scroll_key(self, event):
        entry = self._selected_scroll_entry()
        if entry is None:
            return None
        focus = self.root.focus_get()
        if isinstance(focus, (tk.Entry, ttk.Entry, tk.Text)):
            return None
        key = getattr(event, "keysym", "")
        if key == "Prior":
            entry["canvas"].yview_scroll(-1, "pages")
        elif key == "Next":
            entry["canvas"].yview_scroll(1, "pages")
        elif key == "Home" and getattr(event, "state", 0) & 0x4:
            entry["canvas"].yview_moveto(0.0)
        elif key == "End" and getattr(event, "state", 0) & 0x4:
            entry["canvas"].yview_moveto(1.0)
        else:
            return None
        return "break"

    # ------------------------------------------------------------ navigation + search
    def _show_page(self, key: str):
        if key not in self.pages or key == self.current_page:
            return
        if self.current_page:
            self.pages[self.current_page]["outer"].pack_forget()
            old = self.nav_buttons[self.current_page]
            old.configure(bg=SIDE, fg=MUTED)
            old._bar.configure(bg=SIDE)  # type: ignore[attr-defined]
        self.current_page = key
        self.pages[key]["outer"].pack(fill="both", expand=True)
        btn = self.nav_buttons[key]
        btn.configure(bg=PANEL2, fg=ACCENT)
        btn._bar.configure(bg=ACCENT)  # type: ignore[attr-defined]
        for nav_key, label, _icon, sub in NAV:
            if nav_key == key:
                self.page_title.configure(text=label)
                self._current_page_sub = sub
                self.page_sub.configure(text=sub)
        if key == "samples":
            self._refresh_samples()

    def _bind_shortcuts(self):
        self.root.bind_all("<Control-s>", lambda _e: (self._save_settings(), "break")[1])
        self.root.bind_all("<Control-k>", lambda _e: (self.search_entry.focus_set(),
                                                      self.search_entry.select_range(0, "end"), "break")[2])

    def _search_focus_in(self, _event=None):
        if self._search_placeholder_active:
            self._search_placeholder_active = False
            self.search_var.set("")
            self.search_entry.configure(fg=TEXT)

    def _search_focus_out(self, _event=None):
        def restore():
            if not self.search_entry.winfo_exists():
                return
            if not self.search_var.get().strip():
                self._search_placeholder_active = True
                self.search_var.set(self.search_placeholder)
                self.search_entry.configure(fg=MUTED)
        self.root.after(150, restore)

    def _build_search_popup(self):
        self.search_list = tk.Listbox(self.root, height=8, width=52, bg="#0a1222", fg=TEXT,
                                      selectbackground="#1a3a50", selectforeground=ACCENT,
                                      activestyle="none", relief="flat", highlightthickness=1,
                                      highlightbackground=ACCENT, font=("Segoe UI", 10))
        self._search_hits: list[dict] = []
        self.search_var.trace_add("write", self._on_search_change)
        self.search_entry.bind("<Down>", lambda _e: self._search_move(1))
        self.search_entry.bind("<Up>", lambda _e: self._search_move(-1))
        self.search_entry.bind("<Return>", lambda _e: self._search_pick())
        self.search_entry.bind("<Escape>", lambda _e: self._search_close(clear=True))
        self.search_entry.bind("<FocusOut>", lambda _e: self.root.after(180, self._search_close))
        self.search_list.bind("<Button-1>", self._search_click)

    def _page_title_of(self, key):
        return next((label for k, label, _i, _s in NAV if k == key), key)

    def _on_search_change(self, *_):
        query = self.search_var.get().strip().lower()
        if not query or (self._search_placeholder_active and query == self.search_placeholder.lower()):
            self._search_close()
            return
        words = query.split()
        hits = []
        for item in self.field_registry:
            hay = f"{item['label']} {item.get('key', '')} {self._page_title_of(item['page'])}".lower()
            if all(w in hay for w in words):
                hits.append(item)
        self._search_hits = hits[:10]
        if not self._search_hits:
            self._search_close()
            return
        self.search_list.delete(0, "end")
        for item in self._search_hits:
            self.search_list.insert("end", f"{item['label']}   ·   {self._page_title_of(item['page'])}")
        self.search_list.selection_clear(0, "end")
        self.search_list.selection_set(0)
        self.root.update_idletasks()
        x = self.search_entry.winfo_rootx() - self.root.winfo_rootx() - 34
        y = self.search_entry.winfo_rooty() - self.root.winfo_rooty() + self.search_entry.winfo_height() + 8
        self.search_list.place(x=max(8, x - 120), y=y)
        self.search_list.lift()

    def _search_move(self, delta):
        if not self._search_hits:
            return "break"
        sel = self.search_list.curselection()
        idx = (sel[0] if sel else 0) + delta
        idx = max(0, min(len(self._search_hits) - 1, idx))
        self.search_list.selection_clear(0, "end")
        self.search_list.selection_set(idx)
        self.search_list.see(idx)
        return "break"

    def _search_pick(self):
        sel = self.search_list.curselection()
        if not self._search_hits:
            return "break"
        item = self._search_hits[sel[0] if sel else 0]
        self._search_close(clear=True)
        self._jump_to(item)
        return "break"

    def _search_click(self, event):
        idx = self.search_list.nearest(event.y)
        if 0 <= idx < len(self._search_hits):
            item = self._search_hits[idx]
            self._search_close(clear=True)
            self._jump_to(item)
        return "break"

    def _search_close(self, clear=False):
        self.search_list.place_forget()
        if clear:
            self.search_var.set("")
            self.root.focus_set()

    def _jump_to(self, item):
        self._show_page(item["page"])
        self.root.update_idletasks()
        entry = self.pages[item["page"]]
        holder = item["holder"]
        canvas = entry.get("canvas")
        if canvas is not None:
            try:
                total = max(1, entry["content"].winfo_height())
                offset = holder.winfo_rooty() - entry["content"].winfo_rooty()
                canvas.yview_moveto(max(0.0, min(1.0, (offset - 90) / total)))
            except tk.TclError:
                pass
        self._flash(holder, 0)

    def _flash(self, holder, step):
        try:
            holder.configure(highlightbackground=ACCENT if step % 2 == 0 else PANEL)
        except tk.TclError:
            return
        if step < 5:
            self.root.after(260, lambda: self._flash(holder, step + 1))
        else:
            holder.configure(highlightbackground=PANEL)

    # ------------------------------------------------------------ dashboard
    def _build_dashboard(self):
        page = self._make_page("dashboard", scroll=True)
        intro, _ = self._card(page, "Welcome to BLOOP", 
                              "Use Preview first. It captures the game and shows what the detector would do without sending mouse input. Start Live only after the boxes align with real ghosts.")
        status_row = tk.Frame(intro, bg=PANEL)
        status_row.pack(fill="x")
        self.dashboard_mode_var = tk.StringVar(value="Idle — no engine process running")
        tk.Label(status_row, textvariable=self.dashboard_mode_var, bg=PANEL, fg=TEXT,
                 font=("Segoe UI Semibold", 12)).pack(side="left", anchor="w")
        ttk.Button(status_row, text="Check game windows", command=self._list_windows).pack(side="right")

        tiles = tk.Frame(page, bg=BG)
        tiles.pack(fill="x", pady=(0, 10))
        metrics = (("LIVE FPS", "fps", BLUE), ("DETECTIONS", "detections", ACCENT),
                   ("INPUT SENT", "clicks", ORANGE), ("AUTO-LEARNED", "learned", GREEN),
                   ("REWARD CONFIRMS", "rewards", RED), ("UPTIME", "uptime", PURPLE))
        for i, (title, key, color) in enumerate(metrics):
            self._tile(tiles, title, self.metric_vars[key], color, i % 3, 3, row=i // 3)

        ecto = tk.Frame(page, bg=BG)
        ecto.pack(fill="x", pady=(0, 10))
        for i, (title, var, color) in enumerate((
                ("ECTOPLAZ THIS SESSION", self.ecto_total_var, GREEN),
                ("REWARD DROPS", self.ecto_drops_var, ACCENT),
                ("ECTOPLAZ / HOUR", self.ecto_rate_var, ORANGE),
                ("LAST GAIN", self.ecto_last_var, BLUE))):
            self._tile(ecto, title, var, color, i, 4)

        tools, _ = self._card(page, "Quick actions", "Common tasks are available here; the main run controls are pinned to the bottom of the window.")
        toolrow = tk.Frame(tools, bg=PANEL)
        toolrow.pack(fill="x")
        ttk.Button(toolrow, text="Open logs", command=lambda: self._open_path(self.project / "logs")).pack(side="left", padx=(0, 7))
        ttk.Button(toolrow, text="Latest detection image", command=lambda: self._open_path(self.project / "diagnostics" / "latest_frame.jpg")).pack(side="left", padx=7)
        ttk.Button(toolrow, text="Ghost training samples", command=lambda: self._open_path(self.project / "smart")).pack(side="left", padx=7)
        ttk.Button(toolrow, text="Advanced settings", command=lambda: self._show_page("advanced")).pack(side="left", padx=7)
        ttk.Button(toolrow, text="Save config backup…", command=self._export_config).pack(side="right")

        card, head = self._card(page, "Activity log", expand=True)
        self.log_filter_var = tk.StringVar(value=LOG_FILTERS[0])
        self.autoscroll_var = tk.BooleanVar(value=True)
        ttk.Button(head, text="Clear", command=self._clear_console).pack(side="right")
        ttk.Button(head, text="Save log…", command=self._save_console).pack(side="right", padx=4)
        ttk.Button(head, text="Copy", command=self._copy_console).pack(side="right")
        ttk.Checkbutton(head, text="Auto-scroll", variable=self.autoscroll_var).pack(side="right", padx=8)
        combo = ttk.Combobox(head, textvariable=self.log_filter_var, values=LOG_FILTERS, state="readonly", width=16)
        combo.pack(side="right", padx=8)
        combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_log_filter())
        wrap = tk.Frame(card, bg="#070c17", highlightthickness=1, highlightbackground=EDGE)
        wrap.pack(fill="both", expand=True)
        self.console = tk.Text(wrap, height=8, bg="#070c17", fg="#b9c8df", insertbackground=TEXT,
                               selectbackground="#20463f", relief="flat", wrap="none",
                               font=("Consolas", 9), padx=10, pady=8, highlightthickness=0, borderwidth=0, state="disabled")
        scrollbar = ttk.Scrollbar(wrap, orient="vertical", command=self.console.yview)
        self.console.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.console.pack(side="left", fill="both", expand=True)
        self.console.tag_configure("error", foreground=RED)
        self.console.tag_configure("warn", foreground=ORANGE)
        self.console.tag_configure("success", foreground=GREEN)
        self.console.tag_configure("debug", foreground="#6f84a8")
        self.console.tag_configure("info", foreground="#b9c8df")

    # ------------------------------------------------------------ settings pages
    def _build_runtime_page(self):
        tab = self._make_page("runtime", scroll=True)
        a = self._group(tab, "Game window", 0, 0, subtitle="The bot locks onto the game by its program name (highrise.exe), so it can never mistake this panel or a browser tab for the game. The title is only used when the program name is empty.")
        self._field(a, "Game program (exe name)", "window_process", 0, 0)
        self._field(a, "Window title (fallback only)", "window_title", 1, 0)
        self._field(a, "Capture method", "capture_method", 2, 0)
        self._field(a, "Monitor index (1 = primary)", "monitor_index", 3, 0)
        self._check(a, "Capture only the client area", "window_client_only", 4, 0)
        self._check(a, "Bring Highrise to the front automatically", "auto_focus_game", 5, 0)
        self._check(a, "Only click where Highrise is on top", "require_game_under_cursor", 6, 0)
        self._field(a, "Re-check game window every (s)", "window_refind_interval_s", 7, 0)
        self._field(a, "Auto-focus retry every (s)", "focus_retry_s", 8, 0)
        self._field(a, "No re-click within (px)", "repeat_click_radius_px", 9, 0)
        ttk.Button(a, text="LIST WINDOWS + PROGRAM NAMES", command=self._list_windows).grid(row=10, column=0, sticky="w", padx=5, pady=7)
        b = self._group(tab, "Performance profile", 0, 1, subtitle="Balanced for an i7-7700 class CPU. Standard pip OpenCV is CPU-based; the 1050 Ti does not automatically accelerate these operations.")
        self._field(b, "OpenCV worker threads", "opencv_threads", 0, 0)
        self._field(b, "Maximum processing dimension", "match_max_dimension", 1, 0)
        self._field(b, "Fast proposals checked / frame", "fast_proposals_per_frame", 2, 0)
        self._field(b, "Minimum fast target side (px)", "fast_min_candidate_side_px", 3, 0)
        self._field(b, "Loop delay seconds", "loop_delay", 4, 0)
        self._field(b, "Periodic save interval seconds", "save_interval_s", 5, 0)
        c = self._group(tab, "Scan scheduler", 1, 0, columnspan=2,
                        subtitle="The whole screen is proposed every captured frame; a rotating shortlist limits CPU while revisiting every candidate across frames. Full multi-scale template matching is a slow recovery pass.")
        self._check(c, "Quick color + shape search every captured frame", "scan_every_frame", 0, 0)
        self._check(c, "Block target clicks when an ok/okay confirmation popup is visible", "skip_click_while_popup", 0, 1)
        self._field(c, "Exact templates checked per frame (higher = more CPU)", "template_targets_per_frame", 1, 0)
        self._field(c, "Reward popup scan interval (frames)", "watcher_interval_frames", 1, 1)
        profiles = self._group(tab, "Performance profiles", 2, 0, columnspan=2,
            subtitle="Profiles change only performance and threshold parameters. They never touch your learned samples/model. Fast searches more aggressively and can increase false positives; always validate in Preview.")
        for i, name in enumerate(("Safe", "Balanced", "Fast")):
            ttk.Button(profiles, text=f"Apply {name}", command=lambda n=name: self._apply_profile(n),
                       style="Accent.TButton" if name == "Balanced" else "TButton").grid(row=0, column=i, sticky="ew", padx=5, pady=4)
            profiles.grid_columnconfigure(i, weight=1)
        ttk.Button(profiles, text="Auto-tune for this PC", command=self._auto_tune).grid(row=1, column=0, columnspan=3, sticky="ew", padx=5, pady=(8, 4))

    def _build_detection_page(self):
        tab = self._make_page("detection", scroll=True)
        a = self._group(tab, "Template matching", 0, 0, subtitle="Lower thresholds improve recall but can increase false clicks. Use Preview and inspect diagnostics when tuning.")
        self._field(a, "Base confidence threshold", "base_threshold", 0, 0)
        self._field(a, "Minimum target side (pixels)", "min_match_side_px", 1, 0)
        self._field(a, "Maximum instances / template", "max_instances", 2, 0)
        self._field(a, "Template proposal peaks per scale", "proposal_peaks_per_scale", 3, 0)
        self._field(a, "Scales (comma-separated multipliers)", "base_scales", 4, 0, width=26)
        self._check(a, "Use grayscale in the fast proposal stage", "grayscale", 5, 0)
        b = self._group(tab, "Confirmation watcher matching", 0, 1, subtitle="Every image inside ok/ is a watcher, never a click target. ok.png and okay.png are handled by name and extension.")
        self._field(b, "Popup confidence threshold", "watcher_threshold", 0, 0)
        self._field(b, "Popup scales (comma-separated)", "watcher_scales", 1, 0, width=26)
        self._field(b, "Reward confirmation window (seconds)", "reward_window_s", 2, 0)
        self._field(b, "Watcher cooldown (seconds)", "watcher_cooldown_s", 3, 0)
        c = self._group(tab, "Advanced thresholds", 1, 0, columnspan=2,
                        subtitle="The bot writes best score vs threshold information in DEBUG logs. DEBUG file logging is kept separately from console verbosity.")
        self._field(c, "Adaptive threshold minimum", "adaptive_threshold_min", 0, 0)
        self._field(c, "Adaptive threshold maximum", "adaptive_threshold_max", 0, 1)
        self._field(c, "Deduplication threshold", "dedup_threshold", 1, 0)
        self._field(c, "Score diagnostic interval seconds", "debug_score_interval_s", 1, 1)

    def _build_learning_page(self):
        tab = self._make_page("learning", scroll=True)
        a = self._group(tab, "Automatic discovery", 0, 0, subtitle="Unknown target crops are only persisted after a real click produces a visual response. Screen change is weak evidence, not a guaranteed reward.")
        self._check(a, "Enable auto-learning / explore plausible unseen ghosts", "auto_learning", 0, 0)
        self._field(a, "Idle delay before exploration (seconds)", "explore_after_idle_s", 1, 0)
        self._field(a, "Exploration click cooldown (seconds)", "explore_cooldown_s", 2, 0)
        self._field(a, "Learn response delay (seconds)", "learn_delay", 3, 0)
        self._field(a, "Blacklist duration (seconds)", "explore_blacklist_s", 4, 0)
        self._field(a, "Exploration grid columns, rows", "explore_grid", 5, 0, width=18)
        b = self._group(tab, "Click rate & safety", 0, 1, subtitle="These caps are applied both to exact matches and exploratory clicks.")
        self._field(b, "Maximum clicks / second", "max_cps", 0, 0)
        self._field(b, "Global cooldown seconds", "global_cooldown", 1, 0)
        self._field(b, "Maximum clicks per frame", "max_clicks_per_frame", 2, 0)
        self._field(b, "Maximum clicks per session (0 = unlimited)", "max_session_clicks", 3, 0)
        self._field(b, "Same-location cooldown seconds", "same_location_cooldown_s", 4, 0)
        d = self._group(tab, "Learn from my clicks (no seeds needed)", 1, 0, columnspan=2,
                        subtitle="Click ghosts yourself while BLOOP watches (use Preview / no input to teach without the bot clicking). It learns the ghost's look from your clicks, including new colours and facings, then clicks moving ghosts for you. Press F8 if a bot click was wrong. Sample tools live on the Samples page.")
        self._check(d, "Watch my clicks and learn what a ghost looks like", "smart_learning", 0, 0)
        self._check(d, "Let the bot click the ghosts it has learned", "smart_clicking", 1, 0)
        self._check(d, "Use the learned detector instead of seeds once trained", "smart_exclusive", 2, 0)
        self._check(d, "Bootstrap with existing seed images", "smart_use_seeds", 3, 0)
        self._check(d, "Pause bot clicks while I am clicking", "smart_yield_to_user", 4, 0)
        self._check(d, "Automatically quarantine samples that look mislabelled", "smart_auto_clean", 5, 0)
        self._field(d, "Confidence needed to click (0.50 - 0.99)", "smart_threshold", 6, 0)
        self._field(d, "Ghosts to learn before it acts", "smart_min_positives", 6, 1)
        self._field(d, "Frames a ghost must stay confirmed", "smart_confirm_frames", 7, 0)
        self._field(d, "Aim-ahead ms (0 = automatic)", "smart_lead_ms", 7, 1)
        self._check(d, "Allow the Teach window to label what the bot sees", "teach_gui", 8, 0)
        ttk.Button(d, text="Open teach window", style="Accent.TButton", command=self._open_teach_window).grid(
            row=8, column=1, sticky="w", padx=3, pady=4)
        p = self._group(tab, "Popup auto-dismiss ('esprits attrapés' banner)", 2, 0, columnspan=2,
                        subtitle="When the banner appears, the handler tries the configured drag-down / drag-up sequence and then a double-click fallback. It blocks ghost clicks while the banner is handled. Test with Preview first; needs the banner template image in the project folder.")
        self._check(p, "Auto-dismiss the 'esprits attrapés' banner", "popup_dismiss", 0, 0)
        self._field(p, "Banner template image", "popup_dismiss_image", 1, 0)
        self._field(p, "Match threshold (0.50 - 0.99)", "popup_dismiss_threshold", 1, 1)
        self._field(p, "Wait between attempts (seconds)", "popup_dismiss_settle_s", 2, 0)
        c = self._group(tab, "Learning validation", 3, 0, columnspan=2, subtitle="Increase response thresholds to make new-form learning more conservative; decrease them if valid target disappearances are consistently missed.")
        self._field(c, "Minimum local visual change", "min_local_change", 0, 0)
        self._field(c, "Minimum global visual change", "min_global_change", 0, 1)
        self._field(c, "Minimum local change when global changes", "min_local_for_global", 1, 0)
        self._field(c, "Session save interval seconds", "save_interval_s", 1, 1)

    def _build_logs_page(self):
        tab = self._make_page("logs", scroll=True)
        a = self._group(tab, "Live logging controls", 0, 0, subtitle="The GUI captures the console stream. File and console levels can be different; by default file logs retain DEBUG while console stays at INFO.")
        self._field(a, "Console verbosity", "console_log_level", 0, 0)
        self._field(a, "File verbosity", "file_log_level", 1, 0)
        self._check(a, "Write log files in logs/", "log_file_enabled", 2, 0)
        self._check(a, "Emit console stream (needed for live GUI logs)", "log_console_enabled", 3, 0)
        self._field(a, "Maximum log file size (MB)", "log_file_max_mb", 4, 0)
        b = self._group(tab, "Frame diagnostics", 0, 1, subtitle="The annotated JPEG shows template scores and boxes; it is rate-limited to at most one image write per second.")
        self._check(b, "Write diagnostics/latest_frame.jpg overlay", "debug_overlay", 0, 0)
        self._field(b, "Score log interval seconds", "debug_score_interval_s", 1, 0)
        actions = tk.Frame(b, bg=PANEL)
        actions.grid(row=2, column=0, sticky="ew", padx=5, pady=10)
        ttk.Button(actions, text="Log folder", command=lambda: self._open_path(self.project / "logs")).pack(side="left", padx=(0, 5))
        ttk.Button(actions, text="Latest frame", command=lambda: self._open_path(self.project / "diagnostics" / "latest_frame.jpg")).pack(side="left", padx=5)
        ttk.Button(actions, text="Toast OCR image", command=lambda: self._open_path(self.project / "diagnostics" / "toast_debug.png")).pack(side="left", padx=5)
        ttk.Button(actions, text="Learned library", command=lambda: self._open_path(self.project / "learned")).pack(side="left", padx=5)
        c = self._group(tab, "Repository image importer", 1, 0, columnspan=2,
                        subtitle="Downloads all images from the repository into the local corpus; ok.png/okay.* go to ok/ and never become targets.")
        self._field(c, "Repository owner/name", "repo_name", 0, 0, width=34)
        self.sync_btn = ttk.Button(c, text="Sync + import repository images", command=self._sync_repo)
        self.sync_btn.grid(row=1, column=0, sticky="w", padx=5, pady=7)
        ttk.Button(c, text="Rebuild crops from cached images", command=self._reimport_corpus).grid(row=1, column=1, sticky="w", padx=5, pady=7)

    # ------------------------------------------------------------ advanced settings
    def _build_advanced_page(self):
        tab = self._make_page("advanced", scroll=True)
        intro_outer = tk.Frame(tab, bg=PANEL, highlightthickness=1, highlightbackground=EDGE, padx=16, pady=12)
        intro_outer.grid(row=0, column=0, columnspan=2, sticky="ew", padx=(0, 10), pady=(0, 12))
        tk.Label(intro_outer, text="ADVANCED SETTINGS", bg=PANEL, fg=PURPLE,
                 font=("Consolas", 9, "bold")).pack(anchor="w")
        intro_sub = tk.Label(intro_outer, text="Every Config field not already on a focused page appears here. Change advanced options only when you understand the trade-off; most changes apply after restarting the engine.",
                             bg=PANEL, fg=MUTED, wraplength=900, justify="left", anchor="w")
        intro_sub.pack(anchor="w", fill="x", pady=(5, 8))
        self._fit_label_to_holder(intro_outer, intro_sub, inset=32, min_width=180, max_width=900)
        intro = tk.Frame(intro_outer, bg=PANEL)
        intro.pack(fill="x")
        actions = tk.Frame(intro, bg=PANEL)
        actions.pack(fill="x")
        ttk.Button(actions, text="Import config…", command=self._import_config).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Export config…", command=self._export_config).pack(side="left", padx=6)
        ttk.Button(actions, text="Restore defaults…", command=self._restore_defaults).pack(side="left", padx=6)
        ttk.Button(actions, text="Validate settings", command=self._validate_settings).pack(side="left", padx=6)

        used = {item.get("key") for item in self.field_registry if item.get("key")}
        config_keys = set(botmod.Config.__dataclass_fields__)
        used_engine = used & config_keys
        missing = [k for k in botmod.Config.__dataclass_fields__ if k not in used_engine and k != "patient_mode"]
        groups = {
            "Hotkeys & exclusions": ["hk_pause", "hk_quit", "hk_zone", "hk_reload", "hk_bad", "exclusion_zones"],
            "Scan cadence & frame stability": ["idle_delay", "multi_delay", "skip_unchanged_frames", "unchanged_rescan_interval_s", "changed_pixel_delta", "changed_pixel_fraction", "template_fallback_interval_frames"],
            "Smart tracking & operator hand-off": ["smart_track_cooldown_s", "smart_yield_s", "smart_penalize_static", "auto_learn_roi"],
            "Training & augmentation": ["smart_aug_pos", "smart_aug_neg", "smart_min_negative_samples", "smart_min_validated_train_rows", "smart_min_validated_precision", "smart_min_validated_recall"],
            "Reward confirmation & recovery": ["smart_ecto_confirm", "smart_ecto_window_s", "smart_ecto_max_gain", "smart_feedback_delay_s", "smart_retry_misses", "smart_retry_max", "smart_auto_threshold", "smart_threshold_floor"],
            "Candidate classification & boss rules": ["seed_similarity_hamming_max", "smart_boss_min_frac", "smart_boss_cooldown_s", "smart_probe", "smart_probe_interval_s"],
            "Webhook reporting": ["webhook_interval_s"],
        }
        help_text = {
            "hk_pause": "Global pause/resume hotkey. Use a key name recognized by the keyboard package.",
            "hk_quit": "Emergency engine quit hotkey. Keep this distinct from GUI shortcuts.",
            "hk_zone": "Hotkey used to define or edit an exclusion zone when zone drawing is supported.",
            "hk_reload": "Reload configuration and target library without relaunching the whole engine.",
            "hk_bad": "Mark the most recent bad click/sample when the engine supports this action.",
            "exclusion_zones": "Rectangles are [x, y, width, height] in captured-frame coordinates. Keep UI/popup regions excluded when appropriate.",
            "idle_delay": "Wait between idle loops. Lower values can increase CPU use when no targets are visible.",
            "multi_delay": "Delay between multiple actions within one frame. Increasing it lowers click bursts.",
            "skip_unchanged_frames": "Skip some repeated work when the scene is unchanged. Disable for maximum scan frequency at higher CPU cost.",
            "unchanged_rescan_interval_s": "Force a rescan after this interval even if the frame appears unchanged.",
            "changed_pixel_delta": "Per-pixel channel difference considered a meaningful change.",
            "changed_pixel_fraction": "Fraction of changed pixels needed to classify a scene as changed.",
            "template_fallback_interval_frames": "How often the slower exhaustive template recovery scan runs. Lower values improve recovery but cost CPU.",
            "smart_track_cooldown_s": "Minimum time before the same tracked object can be clicked again.",
            "smart_yield_s": "How long automation yields after detecting user input.",
            "smart_penalize_static": "Penalize candidates that remain stationary like scenery rather than moving event targets.",
            "auto_learn_roi": "Restrict automatic learning to the configured region of interest when enabled.",
            "smart_aug_pos": "Number of synthetic augmentations generated per positive sample during training.",
            "smart_aug_neg": "Number of synthetic augmentations generated per negative sample during training.",
            "smart_min_negative_samples": "Minimum number of negative examples expected before trusting a newly trained model.",
            "smart_min_validated_train_rows": "Minimum training-row metadata required before a packaged model can be marked ready.",
            "smart_min_validated_precision": "Minimum stored precision threshold. This metadata is not a substitute for an independent benchmark.",
            "smart_min_validated_recall": "Minimum stored recall threshold. This metadata is not a substitute for an independent benchmark.",
            "smart_ecto_confirm": "Use detected Ectoplaz reward to confirm a click when the toast reader is healthy.",
            "smart_ecto_window_s": "Maximum interval after a click in which a reward may be attributed to that click.",
            "smart_ecto_max_gain": "Reject implausibly large OCR reward readings above this amount.",
            "smart_feedback_delay_s": "Delay before evaluating local visual response after a click.",
            "smart_retry_misses": "Allow a limited retry for eligible missed targets.",
            "smart_retry_max": "Maximum retries permitted for one unresolved target.",
            "smart_auto_threshold": "Adjust model threshold based on collected response evidence when enabled.",
            "smart_threshold_floor": "Lowest threshold allowed by automatic threshold adjustment.",
            "seed_similarity_hamming_max": "Maximum perceptual-hash distance for candidates compared with the seed family; lower is stricter.",
            "smart_boss_min_frac": "Minimum candidate-size fraction for special large-target logic.",
            "smart_boss_cooldown_s": "Cooldown used by the special large-target path.",
            "smart_probe": "Enable periodic diagnostic probing. Keep disabled for ordinary production operation unless investigating a specific issue.",
            "smart_probe_interval_s": "Interval between diagnostic probes when probing is enabled.",
            "webhook_interval_s": "Legacy/reporting interval retained for compatibility with the reporter configuration.",
        }
        placed = set()
        row = 1
        group_idx = 0
        for title, keys in groups.items():
            chosen = [key for key in keys if key in missing]
            if not chosen:
                continue
            col = group_idx % 2
            grid_row = row + group_idx // 2
            inner = self._group(tab, title, grid_row, col, subtitle="Advanced controls · save before starting a new run.")
            for i, key in enumerate(chosen):
                label = self._friendly_config_label(key)
                help_msg = help_text.get(key, "Advanced engine setting. Change carefully; use Preview to validate behavior before enabling live input.")
                if self.types.get(key) == "bool":
                    self._check(inner, label, key, i // 2, i % 2, help_text=help_msg)
                else:
                    self._field(inner, label, key, i // 2, i % 2, width=22, secret=(key == "webhook_url"), help_text=help_msg)
                placed.add(key)
            group_idx += 1
        extra = [k for k in missing if k not in placed]
        if extra:
            title = "Additional engine settings"
            col = group_idx % 2
            grid_row = row + group_idx // 2
            inner = self._group(tab, title, grid_row, col, subtitle="New or unclassified Config fields are surfaced here automatically.")
            for i, key in enumerate(extra):
                if self.types.get(key) == "bool":
                    self._check(inner, self._friendly_config_label(key), key, i // 2, i % 2)
                else:
                    self._field(inner, self._friendly_config_label(key), key, i // 2, i % 2, width=22)
            group_idx += 1
        final_row = row + (group_idx + 1) // 2
        coverage = tk.Frame(tab, bg=PANEL, highlightthickness=1, highlightbackground=EDGE, padx=16, pady=12)
        coverage.grid(row=final_row, column=0, columnspan=2, sticky="ew", padx=(0, 10), pady=(0, 10))
        tk.Label(coverage, text="CONFIGURATION COVERAGE", bg=PANEL, fg=PURPLE,
                 font=("Consolas", 9, "bold")).pack(anchor="w")
        tk.Label(coverage, text=f"{len(used_engine)} engine fields are already available on focused pages; {len(missing)} remaining fields are surfaced here. patient_mode is intentionally controlled by the inverse ‘auto-learning’ switch to avoid conflicting duplicate controls.",
                 bg=PANEL, fg=MUTED, wraplength=880, justify="left").pack(anchor="w", pady=(5, 0))
        tab.grid_columnconfigure((0, 1), weight=1, uniform="advanced_cards")

    @staticmethod
    def _friendly_config_label(key: str) -> str:
        labels = {
            "hk_pause": "Pause / resume hotkey", "hk_quit": "Emergency quit hotkey",
            "hk_zone": "Exclusion-zone hotkey", "hk_reload": "Reload config hotkey",
            "hk_bad": "Mark bad sample hotkey", "smart_min_negative_samples": "Minimum negative samples",
            "smart_min_validated_train_rows": "Minimum validated training rows",
            "smart_min_validated_precision": "Minimum stored precision", "smart_min_validated_recall": "Minimum stored recall",
            "smart_ecto_confirm": "Use Ectoplaz reward confirmation", "smart_ecto_window_s": "Reward attribution window (s)",
            "smart_ecto_max_gain": "Maximum plausible Ectoplaz gain", "smart_feedback_delay_s": "Visual feedback delay (s)",
            "smart_retry_misses": "Retry missed targets", "smart_retry_max": "Maximum retry attempts",
            "smart_auto_threshold": "Auto-adjust smart threshold", "smart_threshold_floor": "Minimum auto threshold",
            "smart_boss_min_frac": "Minimum large-target fraction", "smart_boss_cooldown_s": "Large-target cooldown (s)",
            "smart_probe": "Enable diagnostic probe", "smart_probe_interval_s": "Diagnostic probe interval (s)",
            "template_fallback_interval_frames": "Full-template recovery interval (frames)",
            "unchanged_rescan_interval_s": "Unchanged-scene rescan interval (s)",
            "changed_pixel_delta": "Changed-pixel threshold", "changed_pixel_fraction": "Changed-pixel fraction",
            "smart_aug_pos": "Positive augmentations per sample", "smart_aug_neg": "Negative augmentations per sample",
            "seed_similarity_hamming_max": "Maximum seed-family hash distance", "smart_yield_s": "Yield after user input (s)",
            "smart_track_cooldown_s": "Tracked-target cooldown (s)", "auto_learn_roi": "Limit learning to ROI",
        }
        return labels.get(key, key.replace("_", " ").strip().capitalize())

    def _apply_profile(self, profile: str):
        """Apply transparent performance presets; never changes the learned model."""
        presets = {
            "Safe": {"base_threshold": 0.88, "smart_threshold": 0.97, "max_cps": 2.5,
                     "max_clicks_per_frame": 1, "global_cooldown": 0.40,
                     "same_location_cooldown_s": 8.0, "match_max_dimension": 680,
                     "opencv_threads": 2, "fast_proposals_per_frame": 4,
                     "template_targets_per_frame": 1, "template_fallback_interval_frames": 90},
            "Balanced": {"base_threshold": 0.82, "smart_threshold": 0.95, "max_cps": 4.0,
                         "max_clicks_per_frame": 2, "global_cooldown": 0.25,
                         "same_location_cooldown_s": 5.0, "match_max_dimension": 800,
                         "opencv_threads": 4, "fast_proposals_per_frame": 8,
                         "template_targets_per_frame": 1, "template_fallback_interval_frames": 60},
            "Fast": {"base_threshold": 0.78, "smart_threshold": 0.92, "max_cps": 5.0,
                     "max_clicks_per_frame": 3, "global_cooldown": 0.18,
                     "same_location_cooldown_s": 3.0, "match_max_dimension": 960,
                     "opencv_threads": 4, "fast_proposals_per_frame": 10,
                     "template_targets_per_frame": 2, "template_fallback_interval_frames": 45},
        }
        preset = presets[profile]
        for key, value in preset.items():
            if key not in self.vars:
                continue
            if isinstance(value, bool):
                self.vars[key].set(value)
            elif isinstance(value, (tuple, list)):
                self.vars[key].set(", ".join(map(str, value)))
            else:
                self.vars[key].set(str(value))
        self._append_log(f"[GUI] Applied {profile} performance profile. Review and save; changes apply on next run.\n", "success")
        self._set_status(f"{profile.upper()} PROFILE · UNSAVED", ORANGE)

    def _auto_tune(self):
        cpus = os.cpu_count() or 4
        # A deliberately conservative heuristic: OpenCV worker count is capped so
        # it doesn't oversubscribe a quad-core desktop while Python also captures.
        threads = max(1, min(4, (cpus + 1) // 2))
        dimension = 960 if cpus >= 12 else (800 if cpus >= 6 else 680)
        proposals = 10 if cpus >= 8 else (8 if cpus >= 4 else 4)
        for key, value in {"opencv_threads": threads, "match_max_dimension": dimension,
                           "fast_proposals_per_frame": proposals,
                           "template_targets_per_frame": 1,
                           "template_fallback_interval_frames": 60}.items():
            self.vars[key].set(str(value))
        self._append_log(f"[GUI] Auto-tune suggested {threads} OpenCV thread(s), {dimension}px work dimension and {proposals} proposals/frame based on {cpus} logical CPU(s). This is a heuristic, not a hardware benchmark.\n", "success")
        self._set_status("AUTO-TUNE · REVIEW AND SAVE", ORANGE)

    def _validate_settings(self):
        try:
            cfg = self._parsed_config()
            messagebox.showinfo("Settings valid", "Configuration parsed and normalized successfully. No settings were saved yet.\n\nSave settings to persist this configuration.", parent=self.root)
            self._set_status("VALIDATION PASSED", ACCENT)
            return cfg
        except Exception as exc:
            messagebox.showerror("Invalid settings", str(exc), parent=self.root)
            self._set_status("CONFIG ERROR", RED)
            return None

    def _restore_defaults(self):
        if not messagebox.askyesno("Restore defaults", "Replace all form values with the engine's default configuration? This does not delete samples or the model. Unsaved edits will be lost.", parent=self.root):
            return
        cfg = botmod.Config()
        self._loading = True
        for key, value in vars(cfg).items():
            if key not in self.vars:
                continue
            if self.types.get(key) == "list":
                self.vars[key].set(", ".join(map(str, value)))
            elif self.types.get(key) == "bool":
                self.vars[key].set(bool(value))
            elif self.types.get(key) == "json":
                self.vars[key].set(json.dumps(value))
            else:
                self.vars[key].set(str(value))
        self.vars["auto_learning"].set(not cfg.patient_mode)
        self._loading = False
        self._set_dirty(True)
        self._append_log("[GUI] Engine defaults loaded into the form. Save to persist them.\n", "warn")

    def _export_config(self):
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(parent=self.root, title="Export BLOOP configuration",
            defaultextension=".json", initialfile="bloop-config-backup.json",
            filetypes=(("JSON configuration", "*.json"), ("All files", "*.*")))
        if not path:
            return
        try:
            cfg = self._parsed_config()
            botmod.save_config(Path(path), cfg)
            self._append_log(f"[GUI] Configuration exported to {path}\n", "success")
            self._set_status("CONFIG EXPORTED", ACCENT)
        except Exception as exc:
            messagebox.showerror("Config export failed", str(exc), parent=self.root)

    def _import_config(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.root, title="Import BLOOP configuration",
            filetypes=(("JSON configuration", "*.json"), ("All files", "*.*")))
        if not path:
            return
        try:
            cfg = botmod.load_config(Path(path))
            self._loading = True
            for key, value in vars(cfg).items():
                if key not in self.vars:
                    continue
                if self.types.get(key) == "list":
                    self.vars[key].set(", ".join(map(str, value)))
                elif self.types.get(key) == "bool":
                    self.vars[key].set(bool(value))
                elif self.types.get(key) == "json":
                    self.vars[key].set(json.dumps(value))
                else:
                    self.vars[key].set(str(value))
            self.vars["auto_learning"].set(not cfg.patient_mode)
            self._loading = False
            self._set_dirty(True)
            self._append_log(f"[GUI] Imported settings from {path}; review then Save Settings.\n", "success")
        except Exception as exc:
            self._loading = False
            messagebox.showerror("Config import failed", str(exc), parent=self.root)

    # ------------------------------------------------------------ samples page
    def _build_samples_page(self):
        tab = self._make_page("samples", scroll=True)
        a = self._group(tab, "Library", 0, 0, columnspan=2,
                        subtitle="What the smart detector trains on. Quarantined samples are ignored but can be restored in the Sample manager.")
        tiles = tk.Frame(a, bg=PANEL)
        tiles.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self.sample_vars = {k: tk.StringVar(value="—") for k in ("pos", "neg", "quar")}
        for i, (title, key, color) in enumerate((("GHOSTS (POSITIVES)", "pos", GREEN),
                                                 ("NOT GHOSTS (NEGATIVES)", "neg", ORANGE),
                                                 ("QUARANTINED", "quar", RED))):
            self._tile(tiles, title, self.sample_vars[key], color, i, 3)
        ttk.Button(a, text="Refresh counts", command=self._refresh_samples).grid(row=1, column=0, sticky="w", padx=3, pady=4)

        b = self._group(tab, "Remove duplicates", 1, 0,
                        subtitle="Deletes identical or near-identical images so one screenshot saved many times stops dominating training. The copy with the highest weight is kept. You confirm before anything is deleted.")
        tk.Label(b, text="Sensitivity", bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", padx=3)
        self.dup_mode = tk.StringVar(value="Normal")
        ttk.Combobox(b, textvariable=self.dup_mode, values=tuple(DUP_MODES), state="readonly", width=26).grid(
            row=1, column=0, sticky="w", padx=3, pady=(4, 6))
        self.dup_retrain = tk.BooleanVar(value=True)
        ttk.Checkbutton(b, text="Retrain the smart model after removing", variable=self.dup_retrain).grid(
            row=2, column=0, sticky="w", padx=3, pady=2)
        row = tk.Frame(b, bg=PANEL)
        row.grid(row=3, column=0, sticky="w", pady=8)
        self.dup_neg_btn = ttk.Button(row, text="Remove duplicate NEGATIVES", style="Accent.TButton",
                                      command=lambda: self._dedupe("negatives"))
        self.dup_neg_btn.pack(side="left", padx=(3, 6))
        self.dup_pos_btn = ttk.Button(row, text="Remove duplicate GHOSTS", command=lambda: self._dedupe("positives"))
        self.dup_pos_btn.pack(side="left")
        self.dup_prog = ttk.Progressbar(b, mode="determinate", maximum=100)
        self.dup_prog.grid(row=4, column=0, sticky="ew", padx=3, pady=(2, 4))
        self.sample_status = tk.Label(b, text="", bg=PANEL, fg=ACCENT, font=("Segoe UI", 9),
                                      wraplength=420, justify="left")
        self.sample_status.grid(row=5, column=0, sticky="w", padx=3)

        c = self._group(tab, "Review & retrain", 1, 1,
                        subtitle="Browse thumbnails, quarantine or flip mislabelled samples, then retrain. Auto-clean quarantines samples the cross-validated model strongly disagrees with.")
        ttk.Button(c, text="Open teach window (label ghosts live)", style="Accent.TButton",
                   command=self._open_teach_window).grid(row=0, column=0, sticky="w", padx=3, pady=4)
        ttk.Button(c, text="Open sample manager", command=self._open_sample_manager).grid(
            row=1, column=0, sticky="w", padx=3, pady=4)
        ttk.Button(c, text="Auto-clean + retrain now", command=lambda: self._smart_request("clean")).grid(
            row=2, column=0, sticky="w", padx=3, pady=4)
        ttk.Button(c, text="Retrain now", command=lambda: self._smart_request("retrain")).grid(
            row=3, column=0, sticky="w", padx=3, pady=4)
        ttk.Button(c, text="Open samples folder", command=lambda: self._open_path(self.project / "smart")).grid(
            row=4, column=0, sticky="w", padx=3, pady=4)

    @staticmethod
    def _count_pngs(folder: Path) -> int:
        try:
            return sum(1 for _ in folder.glob("*.png"))
        except OSError:
            return 0

    def _refresh_samples(self):
        smart = self.project / "smart"
        quar = self._count_pngs(smart / "quarantine" / "positives") + self._count_pngs(smart / "quarantine" / "negatives")
        self.sample_vars["pos"].set(f"{self._count_pngs(smart / 'positives'):,}")
        self.sample_vars["neg"].set(f"{self._count_pngs(smart / 'negatives'):,}")
        self.sample_vars["quar"].set(f"{quar:,}")

    def _dedupe(self, kind: str):
        if self._dedupe_busy:
            return
        folder = self.project / "smart" / kind
        if not folder.exists() or self._count_pngs(folder) < 2:
            self.sample_status.configure(text=f"Not enough {kind} to compare.", fg=MUTED)
            return
        tol = DUP_MODES.get(self.dup_mode.get(), 2.0)
        self._dedupe_busy = True
        self.dup_neg_btn.configure(state="disabled")
        self.dup_pos_btn.configure(state="disabled")
        self.dup_prog.configure(value=0)
        self.sample_status.configure(text=f"Scanning {kind}…", fg=ACCENT)

        def progress(done, total):
            self._ui(lambda: self.dup_prog.configure(value=100.0 * done / max(1, total)))

        def worker():
            try:
                from sample_manager import find_duplicate_samples
                files, dupes = find_duplicate_samples(folder, tol, progress)
                self._ui(lambda: self._dedupe_scanned(kind, files, dupes))
            except Exception as exc:
                self._ui(lambda: self._dedupe_finish(f"Duplicate scan failed: {exc}", RED))
        threading.Thread(target=worker, daemon=True).start()

    def _dedupe_finish(self, text, color=ACCENT):
        self._dedupe_busy = False
        self.dup_neg_btn.configure(state="normal")
        self.dup_pos_btn.configure(state="normal")
        self.dup_prog.configure(value=0)
        self.sample_status.configure(text=text, fg=color)
        self._refresh_samples()

    def _dedupe_scanned(self, kind, files, dupes):
        if not dupes:
            self._dedupe_finish(f"No duplicates found among {len(files):,} {kind}.")
            return
        if not messagebox.askyesno(
                "Remove duplicates",
                f"Found {len(dupes):,} duplicate(s) among {len(files):,} {kind}.\n"
                f"{len(files) - len(dupes):,} unique images will remain.\n\n"
                "Permanently delete the duplicates?", parent=self.root):
            self._dedupe_finish("Duplicate removal cancelled.", MUTED)
            return
        removed = 0
        for path in dupes:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        self._append_log(f"{time.strftime('%H:%M:%S')} [GUI] Removed {removed} duplicate {kind}.\n", "success")
        self._dedupe_finish(f"Removed {removed:,} duplicate {kind}; {len(files) - removed:,} remain.", GREEN)
        if removed and self.dup_retrain.get():
            self._smart_request("retrain")

    # ------------------------------------------------------------ webhook page
    def _build_webhook_page(self):
        tab = self._make_page("webhook", scroll=True)
        a = self._group(tab, "Discord webhook", 0, 0, columnspan=2,
                        subtitle="Paste a Discord webhook URL (channel settings → Integrations → Webhooks). Each time Highrise shows 'Vous avez obtenu Ectoplaz xN', the bot posts +N and the running session total. Save settings and restart the bot after changing the URL.")
        a.grid_columnconfigure(0, weight=1)
        self.webhook_entry = self._field(a, "Webhook URL", "webhook_url", 0, 0, width=70, secret=True)
        row = tk.Frame(a, bg=PANEL)
        row.grid(row=1, column=0, sticky="w", padx=3, pady=6)
        self.webhook_show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Show URL", variable=self.webhook_show_var,
                        command=self._toggle_webhook_secret).pack(side="left")
        ttk.Button(row, text="Send test message", style="Accent.TButton", command=self._test_webhook).pack(side="left", padx=10)
        ttk.Button(row, text="Clear URL", command=lambda: self.vars["webhook_url"].set("")).pack(side="left")
        self.webhook_state = tk.Label(a, text="", bg=PANEL, fg=MUTED, font=("Segoe UI", 9), wraplength=700, justify="left")
        self.webhook_state.grid(row=2, column=0, sticky="w", padx=3)
        self.vars["webhook_url"].trace_add("write", lambda *_: self._update_webhook_state())
        self._update_webhook_state()

        b = self._group(tab, "This session", 1, 0,
                        subtitle="Totals are counted from the bot's own log, so they keep adding up if the watchdog restarts the bot. They reset when you start a new run.")
        for i, (title, var, color) in enumerate((("ECTOPLAZ", self.ecto_total_var, GREEN),
                                                 ("DROPS", self.ecto_drops_var, ACCENT),
                                                 ("PER HOUR", self.ecto_rate_var, ORANGE))):
            box = tk.Frame(b, bg=PANEL2, padx=12, pady=8)
            box.grid(row=0, column=i, sticky="nsew", padx=3)
            b.grid_columnconfigure(i, weight=1)
            tk.Label(box, text=title, bg=PANEL2, fg=MUTED, font=("Consolas", 8, "bold")).pack(anchor="w")
            tk.Label(box, textvariable=var, bg=PANEL2, fg=color, font=("Segoe UI Semibold", 18)).pack(anchor="w")

        c = self._group(tab, "What gets sent", 1, 1,
                        subtitle="One message per Ectoplaz toast, for example:")
        sample = ("🟢 +55 Ectoplaz\nSession total: 1,234 (23 drops)\nSession time: 1h 02m · ~1,190/h")
        tk.Label(c, text=sample, bg="#0a1222", fg="#c9d6ee", font=("Consolas", 9), justify="left",
                 padx=12, pady=10).grid(row=0, column=0, columnspan=2, sticky="w", padx=3)
        tk.Label(c, text="If the number is not read correctly, check diagnostics/toast_debug.png (Logs & Tools → Toast OCR image).",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 8), wraplength=420, justify="left").grid(
            row=1, column=0, columnspan=2, sticky="w", padx=3, pady=(8, 0))

    def _toggle_webhook_secret(self):
        self.webhook_entry.configure(show="" if self.webhook_show_var.get() else "•")

    def _update_webhook_state(self):
        url = str(self.vars["webhook_url"].get()).strip()
        if not url:
            self.webhook_state.configure(text="Disabled: no URL set, so nothing is sent.", fg=MUTED)
        elif not url.startswith("https://"):
            self.webhook_state.configure(text="This does not look like a Discord webhook URL (should start with https://).", fg=ORANGE)
        else:
            self.webhook_state.configure(text=f"Enabled ({len(url)} characters). Save settings, then restart the bot.", fg=GREEN)

    def _test_webhook(self):
        url = str(self.vars["webhook_url"].get()).strip()
        if not url.startswith("http"):
            messagebox.showerror("Webhook", "Enter a webhook URL first.", parent=self.root)
            return
        self.webhook_state.configure(text="Sending test message…", fg=ACCENT)

        def worker():
            try:
                import requests
                resp = requests.post(url, json={"content": "✅ **BLOOP webhook test**: connection works."}, timeout=10)
                ok = 200 <= resp.status_code < 300
                msg = "Test message delivered." if ok else f"Discord answered HTTP {resp.status_code}."
            except Exception as exc:
                # requests exceptions can embed the full URL; never display/log its token.
                detail = redact_webhook_error(f"{type(exc).__name__}: {exc}", url)
                ok, msg = False, f"Could not reach Discord ({detail})."
            self._ui(lambda: self._webhook_test_done(ok, msg))
        threading.Thread(target=worker, daemon=True).start()

    def _webhook_test_done(self, ok, msg):
        self.webhook_state.configure(text=msg, fg=GREEN if ok else RED)
        self._append_log(f"{time.strftime('%H:%M:%S')} [GUI] Webhook test: {msg}\n", "success" if ok else "error")

    # ------------------------------------------------------------ Ectoplaz tracker
    def _reset_ecto(self):
        self.ecto_total = 0
        self.ecto_drops = 0
        self.ecto_started = time.time()
        self.ecto_total_var.set("0")
        self.ecto_drops_var.set("0")
        self.ecto_rate_var.set("—")
        self.ecto_last_var.set("—")

    def _on_ecto_gain(self, amount: int):
        if self.ecto_started is None:
            self.ecto_started = time.time()
        self.ecto_total += amount
        self.ecto_drops += 1
        self.ecto_total_var.set(f"{self.ecto_total:,}")
        self.ecto_drops_var.set(f"{self.ecto_drops:,}")
        self.ecto_last_var.set(f"+{amount:,}")
        self._update_ecto_rate()

    def _update_ecto_rate(self):
        if self.ecto_started and self.ecto_total:
            elapsed = max(60.0, time.time() - self.ecto_started)
            self.ecto_rate_var.set(f"{int(self.ecto_total * 3600 / elapsed):,}")

    # ------------------------------------------------------------ console helpers
    def _apply_log_filter(self):
        mode = self.log_filter_var.get()
        hide = {"info": False, "success": False, "debug": False, "warn": False, "error": False}
        if mode == LOG_FILTERS[1]:
            hide["debug"] = True
        elif mode == LOG_FILTERS[2]:
            hide.update({"info": True, "success": True, "debug": True})
        for tag, elide in hide.items():
            self.console.tag_configure(tag, elide=elide)

    def _copy_console(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.console.get("1.0", "end-1c"))
        self._append_log("[GUI] Current console text copied to clipboard.\n", "success")
        self._set_status_hint("Log copied to clipboard")
        self.root.after(1800, lambda: self._set_status_hint("")
                        if self.page_sub.cget("text") == "Log copied to clipboard" else None)

    def _save_console(self):
        path = self.project / "logs" / f"gui_console_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.console.get("1.0", "end-1c"), encoding="utf-8")
            self._append_log(f"[GUI] Log saved to {path}\n", "success")
        except OSError as exc:
            messagebox.showerror("Save log", str(exc), parent=self.root)

    def _set_status_hint(self, text):
        """Show transient help in the page subtitle without creating hover-log spam."""
        if not hasattr(self, "page_sub"):
            return
        if text:
            self.page_sub.configure(text=text)
        else:
            self.page_sub.configure(text=getattr(self, "_current_page_sub", ""))

    def _parsed_config(self) -> botmod.Config:
        values = {}
        for key, var in self.vars.items():
            if key == "auto_learning":
                continue
            if key not in botmod.Config.__dataclass_fields__:
                continue
            raw = var.get()
            kind = self.types.get(key, "str")
            if kind == "bool":
                values[key] = bool(raw)
            elif kind == "int":
                values[key] = int(str(raw).strip())
            elif kind == "float":
                values[key] = float(str(raw).strip())
            elif kind == "json":
                value = json.loads(str(raw).strip() or "[]")
                if key == "exclusion_zones":
                    if not isinstance(value, list) or any(not isinstance(z, list) or len(z) != 4 for z in value):
                        raise ValueError("Exclusion zones must be JSON rectangles: [[x, y, width, height], ...]")
                    values[key] = [[int(v) for v in z] for z in value]
                else:
                    values[key] = value
            elif kind == "list":
                parts = [p.strip() for p in str(raw).replace(";", ",").split(",") if p.strip()]
                if key == "explore_grid":
                    values[key] = tuple(int(p) for p in parts)
                    if len(values[key]) != 2:
                        raise ValueError("Exploration grid must contain two integers: columns, rows")
                elif key in ("base_scales", "watcher_scales"):
                    values[key] = [float(p) for p in parts]
                else:
                    values[key] = [int(p) for p in parts]
            else:
                values[key] = str(raw).strip()
        cfg = botmod.Config(**values)
        cfg.patient_mode = not bool(self.vars["auto_learning"].get())
        # Clamp via the same config parser the bot uses at runtime.
        scratch = self.project / ".runtime" / "config_validation.json"
        scratch.parent.mkdir(parents=True, exist_ok=True)
        botmod.save_config(scratch, cfg)
        checked = botmod.load_config(scratch)
        try: scratch.unlink()
        except OSError: pass
        return checked

    def _save_settings(self, quiet=False):
        try:
            cfg = self._parsed_config()
            botmod.save_config(self.config_path, cfg)
            self.cfg = cfg
            # reflect any clamped values back into the interface
            self._loading = True
            for key, value in vars(cfg).items():
                if key not in self.vars: continue
                if self.types.get(key) == "list":
                    self.vars[key].set(", ".join(map(str, value)))
                elif self.types.get(key) == "bool":
                    self.vars[key].set(bool(value))
                elif self.types.get(key) == "json":
                    self.vars[key].set(json.dumps(value))
                else:
                    self.vars[key].set(str(value))
            self._loading = False
            self._set_dirty(False)
            self._append_log(f"{time.strftime('%H:%M:%S')} [GUI] Settings saved to {self.config_path}\n", "success")
            if not quiet: self._set_status("SETTINGS SAVED", ACCENT)
            return True
        except Exception as exc:
            self._loading = False
            if not quiet: messagebox.showerror("Invalid setting", str(exc), parent=self.root)
            self._set_status("CONFIG ERROR", RED)
            self._append_log(f"[GUI ERROR] Could not save configuration: {exc}\n", "error")
            return False

    def _open_sample_manager(self):
        existing = getattr(self, "_sample_manager", None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.lift()
                existing.focus_force()
                return
        except Exception:
            pass
        try:
            from sample_manager import SampleManager
            self._sample_manager = SampleManager(self.root, self.project, self._smart_request)
        except Exception as exc:
            messagebox.showerror("Sample manager", f"Could not open the sample manager:\n{exc}", parent=self.root)

    def _open_teach_window(self):
        existing = getattr(self, "_teach_window", None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.lift()
                existing.focus_force()
                return
        except Exception:
            pass
        try:
            from teach_gui import TeachWindow
            self._teach_window = TeachWindow(
                self.root, self.project, self._smart_request,
                palette=dict(BG=BG, PANEL=PANEL, PANEL2=PANEL2, EDGE=EDGE, TEXT=TEXT, MUTED=MUTED, ACCENT=ACCENT,
                             ORANGE=ORANGE, RED=RED, GREEN=GREEN, BLUE=BLUE))
        except Exception as exc:
            messagebox.showerror("Teach window", f"Could not open the teach window:\n{exc}", parent=self.root)

    def _smart_request(self, action: str):
        """Run one smart job at a time and stream output; never kill cleaning at 900s.
        Bot running -> signal its background worker. Bot stopped -> stream offline CLI output.
        """
        smart_dir = self.project / "smart"
        smart_dir.mkdir(parents=True, exist_ok=True)
        if self.proc is not None and self.proc.poll() is None:
            tmp = smart_dir / "command.tmp"
            tmp.write_text(json.dumps({"action": action}), encoding="utf-8")
            tmp.replace(smart_dir / "command.json")
            self._append_log(f"{time.strftime('%H:%M:%S')} [GUI] Asked the running bot to {action} the smart model.\n", "success")
            return

        # Guard at the GUI level as well as smart_ghost.py's cross-process lock.
        # This avoids launching multiple offline trainers from repeated clicks.
        if getattr(self, "_offline_smart_busy", False):
            self._append_log(f"{time.strftime('%H:%M:%S')} [GUI] Ignored duplicate offline smart request ({action}); a job is already running.\n", "warn")
            return
        self._offline_smart_busy = True
        self._append_log(f"{time.strftime('%H:%M:%S')} [GUI] Bot is not running - running {action} offline...\n", "success")

        def worker():
            cmd = [self._python_executable(), "-u", str(self.project / "smart_ghost.py"),
                   "clean-retrain" if action == "clean" else "retrain", "--root", str(self.project)]
            kwargs = dict(cwd=str(self.project), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace", bufsize=1)
            if os.name == "nt":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = None
            exit_code = None
            try:
                proc = subprocess.Popen(cmd, **kwargs)
                self._offline_smart_process = proc
                self._ui(lambda pid=proc.pid: self._append_log(
                    f"{time.strftime('%H:%M:%S')} [GUI] Offline smart job PID {pid}; streaming output below.\n", "info"))
                if proc.stdout is not None:
                    for raw_line in proc.stdout:
                        line = raw_line.rstrip("\r\n")
                        if line:
                            # Bind the current line in the lambda; UI callbacks execute later.
                            self._ui(lambda line=line: self._append_log(line + "\n", "info"))
                exit_code = proc.wait()
                state = "completed" if exit_code == 0 else f"failed (exit code {exit_code})"
                tag = "success" if exit_code == 0 else "error"
                self._ui(lambda state=state, tag=tag: self._append_log(
                    f"{time.strftime('%H:%M:%S')} [GUI] Offline smart {action} {state}.\n", tag))
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                self._ui(lambda detail=detail: self._append_log(
                    f"{time.strftime('%H:%M:%S')} [GUI ERROR] Offline smart {action} failed: {detail}\n", "error"))
                if proc is not None and proc.poll() is None:
                    try:
                        proc.terminate()
                    except OSError:
                        pass
            finally:
                self._offline_smart_process = None
                def finish_ui():
                    self._offline_smart_busy = False
                self._ui(finish_ui)

        threading.Thread(target=worker, daemon=True, name=f"bloop-offline-smart-{action}").start()

    # BLOOP_SMART_JOB_STREAM_PATCH_V1
    def _python_executable(self):
        # When the GUI is started through pythonw.exe, use its sibling python.exe
        # for child processes so stdout/stderr can be piped into this live log UI.
        executable = Path(sys.executable)
        if os.name == "nt" and executable.name.lower() == "pythonw.exe":
            console_python = executable.with_name("python.exe")
            if console_python.is_file():
                return str(console_python)
        return sys.executable

    def _command_base(self):
        return [self._python_executable(), "-u", str(self.project / "main.py"), "--root", str(self.project)]

    def _list_windows(self):
        try:
            result = subprocess.run(
                self._command_base() + ["--list-windows"], cwd=str(self.project),
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8,
            )
            output = (result.stdout or result.stderr).strip()
            if not output:
                output = "No visible windows returned. Check that pywin32 is installed (py -m pip install pywin32)."
            self._append_log("\n[WINDOW ENUMERATION]\n" + output + "\n", "success" if result.returncode == 0 else "warn")
            messagebox.showinfo("Visible window titles", output[:12000], parent=self.root)
        except Exception as exc:
            messagebox.showerror("Window enumeration failed", str(exc), parent=self.root)

    def _focus_game_window(self):
        """Bring Highrise to front when Live is pressed. Works with window_process=highrise.exe and/or window_title."""
        title = str(self.vars.get("window_title", {}).get() if hasattr(self.vars.get("window_title", ""), "get") else self.vars["window_title"].get()).strip() if "window_title" in self.vars else ""
        proc_name = str(self.vars.get("window_process", {}).get() if hasattr(self.vars.get("window_process", ""), "get") else self.vars["window_process"].get()).strip() if "window_process" in self.vars else ""
        # Fallback: read directly from vars dict safely
        try:
            title = str(self.vars["window_title"].get()).strip()
        except Exception:
            title = title
        try:
            proc_name = str(self.vars["window_process"].get()).strip()
        except Exception:
            proc_name = proc_name
        target_proc = proc_name.lower()
        target_title = title.lower()
        brought = False
        try:
            import win32gui
            import win32con
            import win32process
            def _enum_cb(hwnd, _):
                nonlocal brought
                if brought:
                    return
                if not win32gui.IsWindowVisible(hwnd):
                    return
                # Skip our own GUI
                try:
                    if hwnd == int(self.root.winfo_id()):
                        return
                except Exception:
                    pass
                try:
                    w_text = win32gui.GetWindowText(hwnd) or ""
                except Exception:
                    w_text = ""
                low_text = w_text.lower()
                # 1) Title match (most reliable)
                if target_title and target_title in low_text:
                    try:
                        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                        win32gui.SetForegroundWindow(hwnd)
                        brought = True
                        return
                    except Exception:
                        pass
                # 2) Process match - highrise.exe
                if target_proc:
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        # Try psutil for exact exe name
                        try:
                            import psutil
                            p = psutil.Process(pid)
                            pname = (p.name() or "").lower()
                            if target_proc == pname or target_proc in pname or pname in target_proc:
                                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                                win32gui.SetForegroundWindow(hwnd)
                                brought = True
                                return
                        except Exception:
                            # No psutil: still try to bring window if its title looks like Highrise
                            if "highrise" in low_text:
                                try:
                                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                                    win32gui.SetForegroundWindow(hwnd)
                                    brought = True
                                    return
                                except Exception:
                                    pass
                    except Exception:
                        pass
            win32gui.EnumWindows(_enum_cb, None)
        except ImportError as e:
            self._append_log(f"[GUI] Could not auto-focus (pywin32 missing: {e}). Please install pywin32 and bring Highrise forward manually.\n", "warn")
            return
        except Exception as exc:
            self._append_log(f"[GUI] Auto-focus failed: {exc}\n", "warn")
            return
        if brought:
            self._append_log(f"[GUI] Focused Highrise window ({proc_name or title or 'highrise.exe'}).\n", "success")
        else:
            self._append_log("[GUI] Could not find Highrise window to focus - make sure highrise.exe is running and title/process is set in Runtime & Speed.\n", "warn")

    def _safe_targeting(self) -> bool:
        """True when the bot targets highrise.exe by process: it cannot see or click this panel,
        so the old minimize/pause safety dance is unnecessary and the bot never pauses itself."""
        return bool(str(self.vars["window_process"].get()).strip())

    def _on_gui_restored(self, _event=None):
        if self._safe_targeting():
            return
        # Tk's toplevel bind tag is also present in descendant bindtags, so child
        # Map events can arrive here in batches. Only the actual toplevel restore
        # should trigger safety pause, and it should log/write the control file once.
        if _event is not None and getattr(_event, "widget", self.root) is not self.root:
            return
        if (self._live_mode_active and not self._iconifying_for_live
                and self.proc and self.proc.poll() is None and not self.pause_requested):
            self.pause_requested = True
            try:
                self._write_control(stop=False, paused=True)
                self.pause_btn.configure(text="▶  RESUME")
                self._append_log("[SAFETY] GUI restored during live mode: bot paused. Press RESUME to hide this window and then continue.\n", "warn")
            except Exception as exc:
                self._append_log(f"[SAFETY] Could not write pause control: {exc}\n", "error")

    def _start_bot(self, dry_run: bool, autoplay: bool = False):
        if getattr(self, "_offline_smart_busy", False):
            messagebox.showwarning("Smart training in progress",
                                   "Wait until the offline clean/retrain job finishes before starting the bot.",
                                   parent=self.root)
            return
        if self.proc and self.proc.poll() is None:
            messagebox.showwarning("Already running", "Stop the running process before starting another mode.", parent=self.root)
            return
        if autoplay and not (self.project / "smart" / "model.npz").is_file():
            messagebox.showerror("No trained model", "Auto play needs a trained model (smart/model.npz).\n\n"
                                 "Teach it first with Live / Preview, or use Retrain on the Learning page.", parent=self.root)
            return
        if not dry_run and not messagebox.askyesno(
                "Confirm auto play" if autoplay else "Confirm live input",
                ("BLOOP will click ghosts with the saved model only. It will NOT learn from your clicks or its own, "
                 "and will not retrain.\n\n" if autoplay else
                 "BLOOP will send real mouse clicks to the selected Highrise window.\n\n")
                + "Have you checked Preview and confirmed that detections land on actual ghosts?",
                parent=self.root):
            return
        if not str(self.vars["window_process"].get()).strip() and not str(self.vars["window_title"].get()).strip():
            messagebox.showerror("Missing target", "Enter the game program (highrise.exe) in Runtime & Speed first.", parent=self.root)
            self._show_page("runtime")
            return
        self._user_stop = False
        if self._restart_job is not None:
            try: self.root.after_cancel(self._restart_job)
            except Exception: pass
            self._restart_job = None
        if not self._save_settings(quiet=True): return
        if not dry_run and not bool(self.vars["window_client_only"].get()):
            self.vars["window_client_only"].set(True)
            if not self._save_settings(quiet=True): return
            messagebox.showinfo("Safe capture enforced", "Live mode requires client-area-only capture so the bot cannot target its own GUI or unrelated desktop windows.", parent=self.root)
        self.control_path.parent.mkdir(parents=True, exist_ok=True)
        # Live mode starts PAUSED. The controller is minimized first, then the
        # child is resumed. This closes the race where the bot captured/clicked
        # the controller during the first few hundred milliseconds.
        legacy_hide = (not dry_run) and not self._safe_targeting()
        self.pause_requested = legacy_hide
        self._write_control(stop=False, paused=legacy_hide)
        command = self._command_base() + ["--process", str(self.vars["window_process"].get()).strip(),
                                         "--control-file", str(self.control_path)]
        if str(self.vars["window_title"].get()).strip():
            command += ["--window", str(self.vars["window_title"].get()).strip()]
        if dry_run:
            command.append("--dry-run")
        if autoplay:
            command += ["--autoplay", "--patient"]
        elif bool(self.vars["auto_learning"].get()):
            command.append("--explore")
        else:
            command.append("--patient")
        if bool(self.vars["scan_every_frame"].get()):
            command.append("--scan-every-frame")
        mode = "PREVIEW / NO INPUT" if dry_run else ("LIVE AUTO PLAY (NO TRAINING)" if autoplay else "LIVE CLICKING")
        self._append_log(f"\n[GUI] Starting {mode}: {' '.join(command)}\n", "success" if dry_run else "warn")
        self._append_log("[SAFETY] Capture is restricted to the Highrise window; no monitor-wide live fallback is allowed.\n", "success")
        self._live_mode_active = not dry_run
        self._live_start_pending = legacy_hide
        self._last_command = (command, mode, dry_run)
        self._launch(command, mode)
        if legacy_hide and self.proc is not None:
            self.pause_btn.configure(text="▶  RESUME")
            self._iconifying_for_live = True
            self.root.after(250, self._minimize_for_live)
            # After GUI hides, force Highrise to front so user sees the game immediately
            self.root.after(900, self._focus_game_window)
        elif dry_run and self.proc is not None:
            # Preview sends no input, so the controller does not need to hide or pause;
            # just switch the screen to Highrise so the detection overlay is visible at once.
            self._append_log("[GUI] Preview running. Switching to Highrise; press Stop to end it.\n", "success")
            self.root.after(350, self._focus_game_window)
        elif not dry_run and self.proc is not None:
            self._append_log("[GUI] Live mode running. The bot attaches to highrise.exe by itself, restores it if minimized, and keeps going until you press Stop.\n", "success")
            # Safe targeting (highrise.exe by process) - old code never hid GUI, so game stayed behind.
            # Now we actively bring Highrise forward as soon as Live is pressed.
            self.root.after(350, self._focus_game_window)

    def _minimize_for_live(self):
        """Hide the controller, then resume the new live process after it is hidden."""
        if not (self.proc and self.proc.poll() is None and self._live_mode_active):
            self._iconifying_for_live = False
            self._live_start_pending = False
            return
        self._iconifying_for_live = True
        try:
            self.root.iconify()
        except tk.TclError as exc:
            self._append_log(f"[SAFETY] Could not minimize controller: {exc}; live mode remains paused.\n", "error")
            self.pause_requested = True
            return
        self.root.after(650, self._finish_minimize_and_resume)

    def _finish_minimize_and_resume(self):
        self._iconifying_for_live = False
        if not (self.proc and self.proc.poll() is None and self._live_mode_active):
            self._live_start_pending = False
            return
        # Don't resume if the user explicitly paused or the process is stopping.
        if self.pause_requested and self._live_start_pending:
            self.pause_requested = False
            self._live_start_pending = False
            try:
                self._write_control(stop=False, paused=False)
                self.pause_btn.configure(text="Ⅱ  PAUSE")
                self._append_log("[SAFETY] Controller hidden; live mode resumed. Restore the GUI to pause before interacting.\n", "success")
            except Exception as exc:
                self.pause_requested = True
                self._append_log(f"[SAFETY] Could not resume live process: {exc}\n", "error")

    def _hide_then_resume_live(self):
        """Resume is a two-phase action: hide first, clear pause second."""
        if not (self.proc and self.proc.poll() is None and self._live_mode_active):
            return
        self._iconifying_for_live = True
        try:
            self.root.iconify()
        except tk.TclError as exc:
            self._iconifying_for_live = False
            self._append_log(f"[SAFETY] Resume cancelled because GUI could not be hidden: {exc}\n", "error")
            return
        self.root.after(650, self._finish_manual_resume)

    def _finish_manual_resume(self):
        self._iconifying_for_live = False
        if not (self.proc and self.proc.poll() is None and self._live_mode_active):
            return
        try:
            self._write_control(stop=False, paused=False)
            self.pause_requested = False
            self.pause_btn.configure(text="Ⅱ  PAUSE")
            self._append_log("[GUI] Controller hidden; live process resumed.\n", "success")
        except Exception as exc:
            self.pause_requested = True
            self._append_log(f"[GUI] Resume failed: {exc}\n", "error")

    def _sync_repo(self):
        if self.proc and self.proc.poll() is None:
            messagebox.showwarning("Busy", "Stop the current process before syncing the repository.", parent=self.root)
            return
        if not self._save_settings(quiet=True): return
        repo = str(self.vars.get("repo_name", tk.StringVar(value="Tenslaster/bloop")).get()).strip() or "Tenslaster/bloop"
        command = self._command_base() + ["--sync-repository", repo]
        self._append_log(f"\n[GUI] Syncing {repo}. This is a one-time setup task; it does not run in the frame loop.\n", "success")
        self._launch(command, "REPOSITORY SYNC")

    def _reimport_corpus(self):
        if self.proc and self.proc.poll() is None:
            messagebox.showwarning("Busy", "Stop the current process before importing images.", parent=self.root)
            return
        command = self._command_base() + ["--reimport-corpus", "--force-reimport"]
        self._append_log("\n[GUI] Rebuilding crops from corpus/repository.\n", "success")
        self._launch(command, "IMAGE REIMPORT")

    def _launch(self, command, mode):
        try:
            kwargs = dict(cwd=str(self.project), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
            if os.name == "nt":
                kwargs["creationflags"] = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                                            | getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                kwargs["start_new_session"] = True
            self.proc = subprocess.Popen(command, **kwargs)
        except Exception as exc:
            self.proc = None
            messagebox.showerror("Could not start process", str(exc), parent=self.root)
            self._set_status("LAUNCH FAILED", RED)
            return
        self.started_at = time.time()
        self.last_exit_code = None
        self.reported_fps = None
        self.reported_tick_ms = None
        if not getattr(self, "_restarting", False):
            self.click_count = self.detect_count = self.learn_count = self.reward_count = 0
            for key in ("detections", "clicks", "learned", "rewards"):
                self.metric_vars[key].set("0")
            self._reset_ecto()
        self._restarting = False
        self.metric_vars["fps"].set("STARTING")
        self._set_status(mode, ORANGE if "LIVE" in mode else ACCENT)
        self.pause_btn.configure(state="normal", text="Ⅱ  PAUSE")
        self.stop_btn.configure(state="normal")
        for button in (self.preview_btn, self.live_btn, self.autoplay_btn, self.sync_btn): button.configure(state="disabled")
        self.reader_thread = threading.Thread(target=self._reader, args=(self.proc,), daemon=True)
        self.reader_thread.start()

    def _reader(self, proc):
        try:
            if proc.stdout:
                for line in iter(proc.stdout.readline, ""):
                    self.lines.put(("line", line))
        except Exception as exc:
            self.lines.put(("line", f"[GUI reader error] {exc}\n"))
        code = proc.wait()
        self.lines.put(("exit", code))

    def _write_control(self, stop: bool, paused: bool):
        self.control_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.control_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"stop": stop, "paused": paused}), encoding="utf-8")
        tmp.replace(self.control_path)

    def _toggle_pause(self):
        if not self.proc or self.proc.poll() is not None:
            return
        if not self.pause_requested:
            self.pause_requested = True
            self._write_control(stop=False, paused=True)
            self.pause_btn.configure(text="▶  RESUME")
            self._append_log("[GUI] Pause requested.\n", "warn")
            return
        if self._live_mode_active and not self._safe_targeting():
            # Do not unpause while the controller is still visible over the game.
            # Keep the process paused until iconify has completed.
            self._append_log("[GUI] Resume queued; hiding controller before live input resumes.\n", "warn")
            self._iconifying_for_live = True
            self.root.after(50, self._hide_then_resume_live)
            return
        self.pause_requested = False
        self._write_control(stop=False, paused=False)
        self.pause_btn.configure(text="Ⅱ  PAUSE")
        self._append_log("[GUI] Resume requested.\n", "warn")
        # Bring Highrise to front when resuming (Preview, Live and Auto play)
        self.root.after(100, self._focus_game_window)

    def _stop_process(self):
        self._user_stop = True
        if self._restart_job is not None:
            try: self.root.after_cancel(self._restart_job)
            except Exception: pass
            self._restart_job = None
        if not self.proc or self.proc.poll() is not None: return
        self._write_control(stop=True, paused=False)
        self._set_status("STOP REQUESTED · SAVING", ORANGE)
        self._append_log("[GUI] Stop requested through cooperative control file; bot should save its library/config before exiting.\n", "warn")
        proc = self.proc
        def report(message: str):
            # This worker must never call Tk widgets directly.
            self.lines.put(("line", f"[GUI] {message}\n"))

        def fallback_stop():
            try:
                proc.wait(timeout=6.0)
                return
            except subprocess.TimeoutExpired:
                report("Cooperative stop timed out; sending process-group interrupt.")
            try:
                if os.name == "nt":
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    proc.send_signal(signal.SIGINT)
                proc.wait(timeout=3.0)
                report("Process stopped after interrupt fallback.")
                return
            except Exception as exc:
                report(f"Process-group interrupt did not stop the bot ({exc}); trying terminate().")
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
                report("Process terminated after cooperative stop failed.")
                return
            except Exception as exc:
                report(f"terminate() failed or timed out ({exc}); forcing process kill.")
            try:
                proc.kill()
                proc.wait(timeout=2.0)
                report("Process was force-killed after stop fallbacks failed.")
            except Exception as exc:
                report(f"ERROR: could not force-stop child process ({exc}).")
        threading.Thread(target=fallback_stop, daemon=True).start()

    def _drain_queue(self):
        processed = 0
        while processed < 250:
            try: kind, payload = self.lines.get_nowait()
            except queue.Empty: break
            processed += 1
            if kind == "line":
                self._append_log(payload, self._tag_for(payload))
                self._interpret_line(payload)
            elif kind == "exit":
                self.last_exit_code = payload
                self._append_log(f"[GUI] Process finished with exit code {payload}.\n", "success" if payload == 0 else "error")
                self.proc = None
                self.pause_requested = False
                self._live_mode_active = False
                self._live_start_pending = False
                self._iconifying_for_live = False
                self.pause_btn.configure(state="disabled", text="Ⅱ  PAUSE")
                self.stop_btn.configure(state="disabled")
                for button in (self.preview_btn, self.live_btn, self.autoplay_btn, self.sync_btn): button.configure(state="normal")
                self._set_status("STANDBY" if payload == 0 else "EXITED WITH ERROR", ACCENT if payload == 0 else RED)
                self._maybe_restart(payload)
        self.root.after(80, self._drain_queue)

    def _maybe_restart(self, exit_code):
        """Crash watchdog: if the bot dies without the user asking, start it again."""
        cmd = self._last_command
        if self._user_stop or cmd is None or exit_code == 0:
            self._restart_delay = 2.0
            return
        command, mode, dry_run = cmd
        if dry_run:
            return
        ran_for = time.time() - (self.started_at or time.time())
        if ran_for > 60:
            self._restart_delay = 2.0          # it was stable for a while; reset backoff
        delay = self._restart_delay
        self._restart_delay = min(15.0, self._restart_delay * 2)
        self._append_log(f"[WATCHDOG] Bot exited with code {exit_code}; restarting in {delay:.0f}s.\n", "warn")
        self._set_status("RESTARTING", ORANGE)

        def relaunch():
            self._restart_job = None
            if self._user_stop or (self.proc and self.proc.poll() is None):
                return
            self._write_control(stop=False, paused=False)
            self._restarting = True
            self._launch(command, mode)
        self._restart_job = self.root.after(int(delay * 1000), relaunch)

    @staticmethod
    def _tag_for(line: str):
        low = line.lower()
        if "error" in low or "exception" in low or "failed" in low: return "error"
        if "warning" in low or "no match" in low or "rejected" in low: return "warn"
        if any(x in low for x in ("input sent", "click sent", "auto-learn saved", "confirmed", "detected")): return "success"
        if "debug" in low: return "debug"
        return None

    def _interpret_line(self, line: str):
        low = line.lower()
        eco = ECTO_RE.search(low)
        if eco:
            self._on_ecto_gain(int(eco.group(1).replace(",", "")))
        fps_match = re.search(r"\bfps=([0-9]+(?:\.[0-9]+)?)", low)
        if fps_match:
            try:
                self.reported_fps = float(fps_match.group(1))
            except ValueError:
                pass
        tick_match = re.search(r"\btick_ms=([0-9]+(?:\.[0-9]+)?)", low)
        if tick_match:
            try:
                self.reported_tick_ms = float(tick_match.group(1))
            except ValueError:
                pass

        # Count semantic events, not log-message families that overlap. The
        # engine emits one TARGET DETECTED record per accepted visual detection;
        # INPUT SENT target= is the single low-level dispatch-success event.
        if "target detected source=" in low:
            self.detect_count += 1
        if "input sent target=" in low:
            self.click_count += 1
        if "auto-learn saved" in low:
            self.learn_count += 1
        if "confirmed click=" in low or "reward confirmed" in low:
            self.reward_count += 1

    def _refresh_metrics(self):
        self.metric_vars["detections"].set(str(self.detect_count))
        self.metric_vars["clicks"].set(str(self.click_count))
        self.metric_vars["learned"].set(str(self.learn_count))
        self.metric_vars["rewards"].set(str(self.reward_count))
        running = bool(self.proc and self.proc.poll() is None)
        if running:
            self.metric_vars["fps"].set(f"{self.reported_fps:.1f}" if self.reported_fps is not None else "STARTING")
            if self.started_at:
                secs = int(time.time() - self.started_at)
                self.metric_vars["uptime"].set(f"{secs // 3600}:{secs % 3600 // 60:02d}:{secs % 60:02d}")
        else:
            self.metric_vars["fps"].set("READY")
            self.metric_vars["uptime"].set("—")
        self._update_ecto_rate()
        self.root.after(500, self._refresh_metrics)

    def _append_log(self, text: str, tag: str | None = None):
        self.console.configure(state="normal")
        self.console.insert("end", text, (tag or "info",))
        self.console_lines += text.count("\n") or 1
        if self.console_lines > 2500:
            self.console.delete("1.0", "500.0")
            self.console_lines = 2000
        if self.autoscroll_var.get():
            self.console.see("end")
        self.console.configure(state="disabled")

    def _clear_console(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")
        self.console_lines = 0

    def _set_status(self, text, color):
        bg = "#12352f" if color == ACCENT else ("#3a2b18" if color == ORANGE else ("#3b1d2b" if color == RED else "#152a45"))
        if hasattr(self, "status_pill"):
            self.status_pill.configure(text=f"● {text.upper()}", fg=color, bg=bg)
        if hasattr(self, "dock_status"):
            self.dock_status.configure(text=f"● {text.upper()}", fg=color)
        if hasattr(self, "dashboard_mode_var"):
            self.dashboard_mode_var.set(text.replace("_", " ").capitalize())

    def _open_path(self, path: Path):
        try:
            if not path.exists():
                if path.suffix:
                    messagebox.showinfo("Not created yet", f"{path.name} does not exist yet. Run Preview or Live first so the bot can write it.", parent=self.root)
                    return
                path.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("Could not open path", str(exc), parent=self.root)

    def _on_close(self):
        if self._dirty:
            answer = messagebox.askyesnocancel("Unsaved settings", "You have unsaved changes. Save them before closing?", parent=self.root)
            if answer is None:
                return
            if answer and not self._save_settings():
                return
        if self.proc and self.proc.poll() is None:
            if not messagebox.askyesno("Stop bot?", "A bot process is still running. Request stop/save and close the GUI?", parent=self.root):
                return
            self._stop_process()
            self.root.after(200, self._poll_close)
        else:
            self.root.destroy()

    def _poll_close(self):
        proc = self.proc
        if proc is not None and proc.poll() is None:
            self.root.after(200, self._poll_close)
            return
        self.root.destroy()


def _record_gui_startup_failure(exc: BaseException) -> str:
    import traceback
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    log_path = Path(__file__).resolve().parent / "logs" / "gui_startup.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] GUI startup failure\n{text}\n")
    except Exception:
        pass
    return text


def main():
    root = None
    try:
        root = tk.Tk()
        app = VisionGUI(root)
        root.mainloop()
    except Exception as exc:
        trace = _record_gui_startup_failure(exc)
        # A message box remains visible even when this script was started with
        # pythonw.exe and no console exists. The traceback is also saved to disk.
        try:
            messagebox.showerror(
                "BLOOP GUI could not start",
                f"{type(exc).__name__}: {exc}\n\nFull traceback saved to logs/gui_startup.log.",
                parent=root,
            )
        except Exception:
            pass
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        if sys.stderr is not None:
            print(trace, file=sys.stderr)
        raise


if __name__ == "__main__":
    main()