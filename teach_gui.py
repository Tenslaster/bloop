"""Teach window: label ghosts with the mouse instead of hovering + hotkeys.

How it works
------------
While this window is open it touches <project>/teach/alive once a second. The running bot (Preview or Live)
sees that and starts writing its latest frame + ghost boxes to <project>/teach/ a few times a second
(overlay_teacher.py). You click a box here (or drag a rectangle round a ghost the detector missed), press a
button, and a small command file goes back to the bot, which applies it to the *exact picture you clicked* -
so it does not matter that the ghost has since moved, or that the bot is clicking in Live.

Nothing is written, and the bot does no extra work, when this window is closed.

TeachSession  = all file / state logic (no tkinter, unit-testable)
TeachWindow   = the tkinter window on top of it
"""
from __future__ import annotations

import base64
import json
import os
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np

SMALL_COLOURS = ("blue", "purple", "yellow", "rainbow")
BOSS_COLOURS = ("blue", "cyan", "green", "light green", "red", "white", "rainbow")
SMALL_KEYS = dict(zip("1234", SMALL_COLOURS))
BOSS_KEYS = dict(zip("qwertyu", BOSS_COLOURS))

COLOUR_HEX = {"blue": "#2878ff", "cyan": "#00ffff", "green": "#3cc83c", "light green": "#a0ff8c",
              "red": "#ff3232", "white": "#f0f0f0", "yellow": "#ffe600", "purple": "#c850dc",
              "rainbow": "#ff00ff"}

Key = Union[int, Tuple[str, int]]          # index into the picture's ghost list, or ("u", n) for a box you drew


# =====================================================================================================
class TeachSession:
    """Everything except the pixels-on-screen part."""

    STALE_S = 3.0

    def __init__(self, project: Path):
        self.dir = Path(project) / "teach"
        self.cmd_dir = self.dir / "cmd"
        self.cmd_dir.mkdir(parents=True, exist_ok=True)
        self.meta: Optional[dict] = None          # newest live.json
        self.view: Optional[dict] = None          # the picture being shown (live.json of that moment)
        self.image: Optional[np.ndarray] = None   # BGR picture as written by the bot (may be downscaled)
        self.frozen = False
        self.user_boxes: List[Tuple[int, int, int, int]] = []
        self.done: Dict[Key, str] = {}
        self.selected: Optional[Key] = None
        self._done_stack: List[Tuple[int, Key]] = []
        self._seq = 0
        self._pending: Dict[str, tuple] = {}
        self._seen: set = set()
        self._result_mtime = 0.0
        self._beat = 0.0
        self.undo_depth = 0
        self.heartbeat(force=True)

    # ---------------------------------------------------------------- bot link
    def heartbeat(self, force: bool = False) -> None:
        t = time.time()
        if force or t - self._beat >= 1.0:
            self._beat = t
            try:
                (self.dir / "alive").write_text(str(t), encoding="utf-8")
            except OSError:
                pass

    def close(self) -> None:
        try:
            if self.frozen:
                self._send({"op": "unpin"})
            (self.dir / "alive").unlink()
        except OSError:
            pass

    def _send(self, payload: dict) -> str:
        self._seq += 1
        cid = f"{time.time_ns()}-{self._seq}"
        payload = dict(payload, cid=cid)
        name = f"{time.time_ns():020d}_{self._seq:04d}"
        tmp = self.cmd_dir / (name + ".part")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self.cmd_dir / (name + ".json"))
        return cid

    # ---------------------------------------------------------------- reading what the bot wrote
    def poll(self) -> bool:
        """Read live.json; load a new picture unless frozen. True when the shown picture changed."""
        try:
            meta = json.loads((self.dir / "live.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        self.meta = meta
        self.undo_depth = int(meta.get("undo", self.undo_depth))
        if self.frozen or (self.view is not None and meta.get("id") == self.view.get("id")):
            return False
        try:
            raw = np.frombuffer((self.dir / meta["image"]).read_bytes(), dtype=np.uint8)
            img = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        except (OSError, KeyError):
            return False
        if img is None:
            return False
        self.view, self.image = meta, img
        self.user_boxes, self.done, self.selected, self._done_stack = [], {}, None, []
        return True

    def age(self) -> Optional[float]:
        if not self.meta:
            return None
        return time.time() - float(self.meta.get("t", 0))

    def health(self) -> Tuple[str, str]:
        """(text, level) with level in ok / warn / bad / info."""
        a = self.age()
        if self.meta is None:
            return "Waiting for the bot... start Preview or Live (it must be running and not paused).", "warn"
        if a is not None and a > self.STALE_S:
            return "No fresh frames: the bot is stopped, paused (F9) or cannot see the game window.", "warn"
        if not self.meta.get("learning", True):
            return "Learning is OFF (AUTO PLAY or learning disabled): nothing you do here will be saved.", "bad"
        n = len(self.view.get("ghosts", [])) if self.view else 0
        if self.frozen:
            return f"Frozen picture, {n} detected box{'es' if n != 1 else ''}. Label as many as you like, then Resume.", "info"
        return f"Live, {n} detected box{'es' if n != 1 else ''}. Click one (or drag round a ghost) to freeze the picture.", "ok"

    @property
    def ghosts(self) -> List[dict]:
        return list(self.view.get("ghosts", [])) if self.view else []

    @property
    def frame_size(self) -> Tuple[int, int]:
        return (int(self.view["w"]), int(self.view["h"])) if self.view else (0, 0)

    @property
    def counts(self) -> Tuple[int, int]:
        m = self.meta or {}
        return int(m.get("pos", 0)), int(m.get("neg", 0))

    # ---------------------------------------------------------------- boxes
    def box_of(self, key: Key) -> Optional[Tuple[int, int, int, int]]:
        if isinstance(key, tuple):
            return self.user_boxes[key[1]] if 0 <= key[1] < len(self.user_boxes) else None
        gs = self.ghosts
        if 0 <= key < len(gs):
            g = gs[key]
            return int(g["x"]), int(g["y"]), int(g["w"]), int(g["h"])
        return None

    def keys(self) -> List[Key]:
        return [i for i in range(len(self.ghosts))] + [("u", i) for i in range(len(self.user_boxes))]

    def hit(self, fx: float, fy: float) -> Optional[Key]:
        """The box under a point (frame pixels); the smallest one wins so a ghost inside a big box is reachable."""
        best, best_area = None, 1e18
        for key in reversed(self.keys()):
            b = self.box_of(key)
            if b is None:
                continue
            x, y, w, h = b
            m = 0.12 * max(w, h)
            if x - m <= fx <= x + w + m and y - m <= fy <= y + h + m:
                area = w * h
                if area < best_area:
                    best, best_area = key, area
        return best

    def next_key(self, after: Optional[Key] = None) -> Optional[Key]:
        """Next box that has no verdict yet (so labelling a screenful is click, click, click)."""
        ks = self.keys()
        if not ks:
            return None
        start = ks.index(after) + 1 if after in ks else 0
        for k in ks[start:] + ks[:start]:
            if k not in self.done and k != after:
                return k
        return None

    def add_user_box(self, x: float, y: float, w: float, h: float) -> Optional[Key]:
        fw, fh = self.frame_size
        x0, y0 = max(0, int(round(x))), max(0, int(round(y)))
        x1, y1 = min(fw, int(round(x + w))), min(fh, int(round(y + h)))
        if x1 - x0 < 8 or y1 - y0 < 8:
            return None
        self.user_boxes.append((x0, y0, x1 - x0, y1 - y0))
        return ("u", len(self.user_boxes) - 1)

    # ---------------------------------------------------------------- freeze / resume
    def freeze(self) -> None:
        if self.frozen or self.view is None:
            return
        self.frozen = True
        self._send({"op": "pin", "snap": int(self.view["id"])})

    def resume(self) -> None:
        if not self.frozen:
            return
        self.frozen = False
        self._send({"op": "unpin"})
        self.view = None            # forces the next poll() to load the newest picture
        self.image = None
        self.user_boxes, self.done, self.selected, self._done_stack = [], {}, None, []

    # ---------------------------------------------------------------- teaching commands
    def label(self, key: Key, verdict: str, kind: str = "", colour: str = "") -> bool:
        """verdict: 'ghost' | 'not_ghost' | 'colour' (colour implies 'it is a ghost')."""
        b = self.box_of(key)
        if b is None or self.view is None:
            return False
        det = ""
        if isinstance(key, int):
            g = self.ghosts[key]
            det = f"{g['kind']} {g['color']}"
        cid = self._send({"op": "label", "snap": int(self.view["id"]), "box": list(b), "verdict": verdict,
                          "kind": kind, "colour": colour, "det": det})
        self._pending[cid] = ("label", key, int(self.view["id"]))
        tag = {"ghost": "ghost", "not_ghost": "not", "colour": f"{kind} {colour}"}[verdict]
        self.done[key] = tag
        self._done_stack.append((int(self.view["id"]), key))
        return True

    def label_all(self) -> bool:
        if self.view is None or not self.ghosts:
            return False
        cid = self._send({"op": "all", "snap": int(self.view["id"])})
        self._pending[cid] = ("all", None, int(self.view["id"]))
        for k in range(len(self.ghosts)):
            if k not in self.done:
                self.done[k] = "ghost"
                self._done_stack.append((int(self.view["id"]), k))
        return True

    def undo(self) -> None:
        cid = self._send({"op": "undo"})
        self._pending[cid] = ("undo", None, 0)

    def poll_results(self) -> List[Tuple[bool, str]]:
        """Answers from the bot to commands sent from this window: [(ok, message)]."""
        p = self.dir / "result.json"
        try:
            mt = p.stat().st_mtime
            if mt == self._result_mtime:
                return []
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        self._result_mtime = mt
        out: List[Tuple[bool, str]] = []
        for r in data.get("results", []):
            cid = r.get("cid")
            if cid in self._seen or cid not in self._pending:
                continue
            self._seen.add(cid)
            op, key, snap = self._pending.pop(cid)
            ok = bool(r.get("ok"))
            if not ok and op == "label" and self.view and snap == int(self.view["id"]):
                self.done.pop(key, None)                       # the bot refused: show the box as unlabelled again
            if ok and op == "undo" and self._done_stack:
                s, k = self._done_stack.pop()
                if self.view and s == int(self.view["id"]):
                    self.done.pop(k, None)
            if r.get("msg"):
                out.append((ok, str(r["msg"])))
        return out


# =====================================================================================================
class TeachWindow(tk.Toplevel):
    PAL = dict(BG="#0a0f1c", PANEL="#111a2e", PANEL2="#16213a", EDGE="#26344f", TEXT="#e8eefc", MUTED="#8fa0bb",
               ACCENT="#54e0c1", ORANGE="#ffba66", RED="#ff6e83", GREEN="#76e4a5", BLUE="#65a8ff")

    def __init__(self, root: tk.Misc, project: Path, smart_request: Optional[Callable[[str], None]] = None,
                 palette: Optional[dict] = None):
        super().__init__(root)
        if palette:
            self.PAL = {**self.PAL, **palette}
        P = self.PAL
        self.project = Path(project)
        self._smart_request = smart_request
        self.session = TeachSession(self.project)
        self.title("BLOOP - Teach the ghost detector")
        self.configure(bg=P["BG"])
        self.geometry("1240x760")
        self.minsize(960, 600)
        self._photo = None
        self._photo_key = None
        self._geom = (1.0, 0, 0)
        self._p0: Optional[Tuple[int, int]] = None
        self._drag_item = None
        self._dragging = False
        self._toast_until = 0.0
        self._job = None
        self._build()
        self.bind("<Key>", self._on_key)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._tick()

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        P = self.PAL
        top = tk.Frame(self, bg=P["BG"], padx=14, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="Teach the ghost detector", bg=P["BG"], fg=P["TEXT"],
                 font=("Segoe UI Semibold", 16)).pack(side="left")
        self.top_btn = ttk.Button(top, text="Resume live (P)", command=self._toggle_freeze)
        self.top_btn.pack(side="right")
        self.ontop = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Keep on top", variable=self.ontop,
                        command=lambda: self.attributes("-topmost", bool(self.ontop.get()))).pack(side="right", padx=12)
        self.status = tk.Label(self, text="", bg=P["PANEL"], fg=P["ACCENT"], anchor="w", padx=14, pady=7,
                               font=("Segoe UI", 10))
        self.status.pack(fill="x", padx=14)

        body = tk.Frame(self, bg=P["BG"])
        body.pack(fill="both", expand=True, padx=14, pady=10)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        wrap = tk.Frame(body, bg=P["EDGE"], padx=1, pady=1)
        wrap.grid(row=0, column=0, sticky="nsew")
        self.canvas = tk.Canvas(wrap, bg="#05080f", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)

        side = tk.Frame(body, bg=P["PANEL"], highlightthickness=1, highlightbackground=P["EDGE"], padx=14, pady=12, width=330)
        side.grid(row=0, column=1, sticky="ns", padx=(12, 0))
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        side.grid_columnconfigure(1, weight=1)

        def head(text, row):
            tk.Label(side, text=text, bg=P["PANEL"], fg=P["MUTED"], font=("Consolas", 8, "bold")).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(10, 3))

        head("1  PICK A BOX", 0)
        self.sel_lbl = tk.Label(side, text="Click a box on the picture.\nMissed a ghost? Drag a rectangle round it.",
                                bg=P["PANEL"], fg=P["TEXT"], justify="left", anchor="w", wraplength=290,
                                font=("Segoe UI", 10))
        self.sel_lbl.grid(row=1, column=0, columnspan=2, sticky="ew")

        head("2  WHAT IS IT?", 2)
        self._btn(side, "✔  It IS a ghost   [Space]", P["GREEN"], lambda: self._act("ghost")).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=2)
        self._btn(side, "✖  NOT a ghost   [X]", P["RED"], lambda: self._act("not_ghost")).grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=2)

        head("OR GIVE IT A COLOUR (it is a ghost)", 5)
        tk.Label(side, text="Small ghost", bg=P["PANEL"], fg=P["TEXT"], font=("Segoe UI", 9)).grid(
            row=6, column=0, columnspan=2, sticky="w")
        r = 7
        for i, (key, colour) in enumerate(SMALL_KEYS.items()):
            self._chip(side, f"{key}  {colour}", colour, lambda c=colour: self._act("colour", "small", c)).grid(
                row=r + i // 2, column=i % 2, sticky="ew", padx=1, pady=1)
        r += 2
        tk.Label(side, text="Boss", bg=P["PANEL"], fg=P["TEXT"], font=("Segoe UI", 9)).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(6, 0))
        r += 1
        for i, (key, colour) in enumerate(BOSS_KEYS.items()):
            self._chip(side, f"{key.upper()}  {colour}", colour, lambda c=colour: self._act("colour", "boss", c)).grid(
                row=r + i // 2, column=i % 2, sticky="ew", padx=1, pady=1)
        r += 4
        head("MORE", r)
        r += 1
        ttk.Button(side, text="All detected boxes are ghosts", command=self._all).grid(
            row=r, column=0, columnspan=2, sticky="ew", pady=2)
        r += 1
        self.undo_btn = ttk.Button(side, text="Undo last  [Ctrl+Z]", command=self.session.undo)
        self.undo_btn.grid(row=r, column=0, sticky="ew", pady=2, padx=(0, 2))
        if self._smart_request is not None:
            ttk.Button(side, text="Retrain now", command=lambda: self._smart_request("retrain")).grid(
                row=r, column=1, sticky="ew", pady=2, padx=(2, 0))
        r += 1
        self.count_lbl = tk.Label(side, text="", bg=P["PANEL"], fg=P["MUTED"], anchor="w", font=("Segoe UI", 9))
        self.count_lbl.grid(row=r, column=0, columnspan=2, sticky="w", pady=(8, 0))
        r += 1
        self.toast_lbl = tk.Label(side, text="", bg=P["PANEL"], fg=P["ACCENT"], anchor="w", justify="left",
                                  wraplength=290, font=("Segoe UI", 10, "bold"))
        self.toast_lbl.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        tk.Label(self, text="Keys while this window is focused:  Space = ghost   X = not a ghost   Tab = next box   "
                            "1-4 small colours   Q W E R T Y U boss colours   Ctrl+Z undo   P freeze / resume",
                 bg=P["BG"], fg=P["MUTED"], font=("Segoe UI", 8)).pack(fill="x", padx=14, pady=(0, 8))

    def _btn(self, parent, text, colour, cmd):
        return tk.Button(parent, text=text, command=cmd, bg=colour, fg="#07101c", activebackground=colour,
                         relief="flat", bd=0, font=("Segoe UI Semibold", 11), pady=8, cursor="hand2")

    def _chip(self, parent, text, colour, cmd):
        bg = COLOUR_HEX.get(colour, "#888888")
        r, g, b = (int(bg[i:i + 2], 16) for i in (1, 3, 5))
        fg = "#07101c" if (0.299 * r + 0.587 * g + 0.114 * b) > 140 else "#ffffff"
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg, activebackground=bg, relief="flat", bd=0,
                         font=("Segoe UI", 9, "bold"), pady=5, cursor="hand2")

    # ------------------------------------------------------------------ periodic work
    def _tick(self) -> None:
        try:
            s = self.session
            s.heartbeat()
            changed = s.poll()
            for ok, msg in s.poll_results():
                self._toast(msg, ok)
            if changed:
                self._redraw()
            self._refresh_labels()
        except Exception as exc:                     # never let the window loop die
            self._toast(f"window error: {exc}", False)
        self._job = self.after(250, self._tick)

    def _refresh_labels(self) -> None:
        P = self.PAL
        text, level = self.session.health()
        self.status.config(text="● " + text,
                           fg={"ok": P["GREEN"], "info": P["BLUE"], "warn": P["ORANGE"], "bad": P["RED"]}[level])
        self.top_btn.config(text="Resume live (P)" if self.session.frozen else "Freeze picture (P)")
        pos, neg = self.session.counts
        self.count_lbl.config(text=f"In the library: {pos} ghosts · {neg} not-ghosts")
        key = self.session.selected
        b = self.session.box_of(key) if key is not None else None
        if b is None:
            self.sel_lbl.config(text="Click a box on the picture.\nMissed a ghost? Drag a rectangle round it.")
        elif isinstance(key, int):
            g = self.session.ghosts[key]
            self.sel_lbl.config(text=f"Selected: detected {g['kind']} {g['color']} ({g['conf'] * 100:.0f}%)")
        else:
            self.sel_lbl.config(text=f"Selected: your own box ({b[2]}x{b[3]})")
        if self._toast_until and time.time() > self._toast_until:
            self.toast_lbl.config(text="")
            self._toast_until = 0.0

    def _toast(self, text: str, ok: bool = True) -> None:
        self.toast_lbl.config(text=text, fg=self.PAL["GREEN"] if ok else self.PAL["ORANGE"])
        self._toast_until = time.time() + 6.0

    # ------------------------------------------------------------------ drawing
    def _redraw(self) -> None:
        c, s = self.canvas, self.session
        c.delete("all")
        cw, ch = max(1, c.winfo_width()), max(1, c.winfo_height())
        if s.image is None or s.view is None:
            c.create_text(cw // 2, ch // 2, fill=self.PAL["MUTED"], font=("Segoe UI", 12), justify="center",
                          text="No picture yet.\n\nStart Preview or Live, open the game, and the bot's view appears here.")
            return
        fw, fh = s.frame_size
        scale = min(cw / fw, ch / fh)
        dw, dh = max(1, int(fw * scale)), max(1, int(fh * scale))
        ox, oy = (cw - dw) // 2, (ch - dh) // 2
        self._geom = (scale, ox, oy)
        key = (s.view["id"], dw, dh)
        if key != self._photo_key:
            img = cv2.resize(s.image, (dw, dh), interpolation=cv2.INTER_AREA)
            ok, png = cv2.imencode(".png", img)
            if ok:
                self._photo = tk.PhotoImage(data=base64.b64encode(png.tobytes()).decode("ascii"))
                self._photo_key = key
        if self._photo is not None:
            c.create_image(ox, oy, anchor="nw", image=self._photo)
        for k in s.keys():
            b = s.box_of(k)
            if b is None:
                continue
            x, y, w, h = b
            x0, y0, x1, y1 = ox + x * scale, oy + y * scale, ox + (x + w) * scale, oy + (y + h) * scale
            if isinstance(k, int):
                g = s.ghosts[k]
                colour, label = COLOUR_HEX.get(g["color"], "#ffffff"), f"{g['kind']} {g['color']} {g['conf'] * 100:.0f}%"
                dash = None
            else:
                colour, label, dash = "#ffba66", "your box", (5, 3)
            verdict = s.done.get(k)
            if verdict:
                good = verdict != "not"
                mark_col = self.PAL["GREEN"] if good else self.PAL["RED"]
                label = ("✔ " if good else "✖ ") + (verdict if verdict not in ("ghost", "not") else label)
                c.create_rectangle(x0, y0, x1, y1, outline=mark_col, width=2, dash=(2, 3))
            else:
                c.create_rectangle(x0 - 1, y0 - 1, x1 + 1, y1 + 1, outline="#000000", width=4)
                c.create_rectangle(x0, y0, x1, y1, outline=colour, width=3 if k != s.selected else 4, dash=dash)
            if k == s.selected:
                c.create_rectangle(x0 - 5, y0 - 5, x1 + 5, y1 + 5, outline="#ffffff", width=2)
            ty, anchor = (y0 - 4, "sw") if y0 > 22 else (y1 + 4, "nw")
            for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                c.create_text(x0 + dx, ty + dy, text=label, fill="#000000", anchor=anchor, font=("Segoe UI", 9, "bold"))
            c.create_text(x0, ty, text=label, fill=colour if not verdict else mark_col, anchor=anchor,
                          font=("Segoe UI", 9, "bold"))

    def _to_frame(self, x: float, y: float) -> Tuple[float, float]:
        scale, ox, oy = self._geom
        return (x - ox) / scale, (y - oy) / scale

    # ------------------------------------------------------------------ mouse
    def _press(self, e) -> None:
        self.canvas.focus_set()
        self._p0 = (e.x, e.y)
        self._dragging = False

    def _motion(self, e) -> None:
        if self._p0 is None or self.session.image is None:
            return
        if not self._dragging and (abs(e.x - self._p0[0]) > 6 or abs(e.y - self._p0[1]) > 6):
            self._dragging = True
            self._drag_item = self.canvas.create_rectangle(*self._p0, e.x, e.y, outline="#ffba66", width=2, dash=(5, 3))
        if self._dragging and self._drag_item is not None:
            self.canvas.coords(self._drag_item, self._p0[0], self._p0[1], e.x, e.y)

    def _release(self, e) -> None:
        p0, self._p0 = self._p0, None
        if p0 is None or self.session.image is None:
            return
        s = self.session
        if self._dragging:
            self._dragging = False
            if self._drag_item is not None:
                self.canvas.delete(self._drag_item)
                self._drag_item = None
            ax, ay = self._to_frame(min(p0[0], e.x), min(p0[1], e.y))
            bx, by = self._to_frame(max(p0[0], e.x), max(p0[1], e.y))
            s.freeze()
            key = s.add_user_box(ax, ay, bx - ax, by - ay)
            if key is None:
                self._toast("that rectangle is too small", False)
            else:
                s.selected = key
        else:
            key = s.hit(*self._to_frame(e.x, e.y))
            if key is not None:
                s.freeze()
                s.selected = key
            else:
                s.selected = None
        self._redraw()
        self._refresh_labels()

    # ------------------------------------------------------------------ actions
    def _toggle_freeze(self) -> None:
        if self.session.frozen:
            self.session.resume()
        else:
            self.session.freeze()
        self._redraw()
        self._refresh_labels()

    def _act(self, verdict: str, kind: str = "", colour: str = "") -> None:
        s = self.session
        if s.selected is None:
            self._toast("Click a box first (or drag a rectangle round the ghost).", False)
            return
        if not s.frozen:
            s.freeze()
        if s.label(s.selected, verdict, kind, colour):
            s.selected = s.next_key(s.selected)
            self._toast("sent...", True)
        self._redraw()
        self._refresh_labels()

    def _all(self) -> None:
        s = self.session
        if not s.frozen:
            s.freeze()
        if not s.label_all():
            self._toast("There are no detected boxes to confirm.", False)
        self._redraw()

    def _on_key(self, e) -> None:
        if e.state & 0x4 and e.keysym.lower() == "z":          # Ctrl+Z
            self.session.undo()
            return
        if e.state & 0x4 or e.state & 0x20000:                  # other Ctrl / Alt combos
            return
        k = (e.keysym or "").lower()
        ch = (e.char or "").lower()
        if k in ("space", "return"):
            self._act("ghost")
        elif ch == "x" or k == "delete":
            self._act("not_ghost")
        elif ch == "p":
            self._toggle_freeze()
        elif k in ("tab", "right"):
            self.session.selected = self.session.next_key(self.session.selected) if self.session.selected is not None \
                else (self.session.keys() or [None])[0]
            self._redraw()
        elif ch in SMALL_KEYS:
            self._act("colour", "small", SMALL_KEYS[ch])
        elif ch in BOSS_KEYS:
            self._act("colour", "boss", BOSS_KEYS[ch])

    def _on_close(self) -> None:
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        self.session.close()
        self.destroy()
