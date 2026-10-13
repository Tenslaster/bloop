"""BLOOP Teach window: reliable, confidence-aware annotation for live ghost frames.

The bot owns detection and learning.  This module is a client of the existing
``overlay_teacher.py`` file bridge: it never writes training samples itself and
never calls the bot's model from the Tk event loop.

Public compatibility API:
    TeachSession(project: Path)
    TeachWindow(root, project, smart_request=None, palette=None)

Safety / reliability properties:
* a label is shown as confirmed only after the bot acknowledges it;
* frame IDs and original-frame coordinates are retained for exact-frame labels;
* file commands are atomically published and malformed metadata is ignored;
* the UI warns on stale frames and refuses to submit labels when learning is off;
* all polling and drawing remains on Tk's main thread; this module starts no threads.
"""
from __future__ import annotations

import base64
import json
import math
import os
import time
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import ttk
from typing import Callable, Deque, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np

SMALL_COLOURS = ("blue", "purple", "yellow", "rainbow")
BOSS_COLOURS = ("blue", "cyan", "green", "light green", "red", "white", "rainbow")
SMALL_KEYS = dict(zip("1234", SMALL_COLOURS))
BOSS_KEYS = dict(zip("qwertyu", BOSS_COLOURS))
COLOUR_HEX = {
    "blue": "#2878ff", "cyan": "#00d7e8", "green": "#3cc83c",
    "light green": "#a0ff8c", "red": "#ff3232", "white": "#f0f0f0",
    "yellow": "#ffe600", "purple": "#c850dc", "rainbow": "#ff00ff",
}

Key = Union[int, Tuple[str, int]]  # detector index or ("u", user-box index)
VALID_VERDICTS = {"ghost", "not_ghost", "colour"}
ALL_BATCH_LIMIT = 12  # Matches OverlayTeacher._do_all; don't misrepresent boxes past the bot's cap.


def _safe_int(value: object, default: int = 0) -> int:
    try:
        n = int(value)
        return n if n >= 0 else default
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError, OverflowError):
        return default


# ============================================================================
class TeachSession:
    """File protocol, frame state, selection and acknowledgement bookkeeping."""

    STALE_S = 3.0
    COMMAND_TIMEOUT_S = 12.0
    SEEN_RESULT_LIMIT = 512

    def __init__(self, project: Path):
        self.project = Path(project)
        self.dir = self.project / "teach"
        self.cmd_dir = self.dir / "cmd"
        self.cmd_dir.mkdir(parents=True, exist_ok=True)
        self.meta: Optional[dict] = None          # newest valid live.json
        self.view: Optional[dict] = None          # frozen/current frame metadata
        self.image: Optional[np.ndarray] = None   # decoded preview image (may be downscaled)
        self.frozen = False
        self.user_boxes: List[Tuple[int, int, int, int]] = []
        self.done: Dict[Key, str] = {}             # acknowledged labels only
        self.pending_labels: Dict[Key, str] = {}
        self.selected: Optional[Key] = None
        self._done_stack: List[Tuple[int, List[Key]]] = []  # one entry per acknowledged command
        self._seq = 0
        self._pending: Dict[str, dict] = {}
        self._seen_order: Deque[str] = deque()
        self._seen: set[str] = set()
        self._result_mtime_ns = -1
        self._beat = 0.0
        self.undo_depth = 0
        self.last_io_error: str = ""
        self.heartbeat(force=True)

    # ---------------------------------------------------------------- bot link
    def heartbeat(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._beat < 1.0:
            return
        self._beat = now
        target = self.dir / "alive"
        tmp = self.dir / "alive.tmp"
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp.write_text(f"{time.time():.6f}", encoding="utf-8")
            os.replace(tmp, target)
            self.last_io_error = ""
        except OSError as exc:
            self.last_io_error = f"could not refresh bot heartbeat: {exc}"
            try:
                tmp.unlink()
            except OSError:
                pass

    def close(self) -> None:
        # Removing the heartbeat is the protocol's close signal. The bot clears
        # its pinned snapshots after its next heartbeat check; publishing an
        # unpin command immediately before close would leave a stale command file.
        try:
            (self.dir / "alive").unlink()
        except OSError:
            pass
        try:
            (self.dir / "alive.tmp").unlink()
        except OSError:
            pass

    def _send(self, payload: dict, *, track: Optional[dict] = None) -> Optional[str]:
        """Atomically publish one command; return its correlation ID or None."""
        self._seq += 1
        now_ns = time.time_ns()
        cid = f"{now_ns}-{self._seq}"
        name = f"{now_ns:020d}_{self._seq:04d}"
        tmp = self.cmd_dir / (name + ".part")
        dest = self.cmd_dir / (name + ".json")
        try:
            payload = dict(payload, cid=cid)
            tmp.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            os.replace(tmp, dest)
        except (OSError, TypeError, ValueError) as exc:
            self.last_io_error = f"could not send command: {exc}"
            try:
                tmp.unlink()
            except OSError:
                pass
            return None
        if track is not None:
            pending = dict(track)
            pending["issued_at"] = time.monotonic()
            self._pending[cid] = pending
        self.last_io_error = ""
        return cid

    # ---------------------------------------------------------------- live frames
    @staticmethod
    def _valid_meta(meta: object) -> bool:
        if not isinstance(meta, dict):
            return False
        sid = meta.get("id")
        name = meta.get("image")
        w, h = _safe_int(meta.get("w")), _safe_int(meta.get("h"))
        if isinstance(sid, bool) or not isinstance(sid, (int, float)) or not math.isfinite(float(sid)) or sid < 1:
            return False
        if w < 1 or h < 1 or w > 20000 or h > 20000:
            return False
        if not isinstance(name, str) or not name.startswith("snap_") or Path(name).name != name:
            return False
        if not name.lower().endswith((".jpg", ".jpeg", ".png")):
            return False
        ghosts = meta.get("ghosts", [])
        if not isinstance(ghosts, list):
            return False
        return True

    def poll(self) -> bool:
        """Load a new complete snapshot. True only when the shown picture changes."""
        try:
            meta = json.loads((self.dir / "live.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return False
        if not self._valid_meta(meta):
            return False
        self.meta = meta
        self.undo_depth = _safe_int(meta.get("undo"), self.undo_depth)
        if self.frozen or (self.view is not None and meta.get("id") == self.view.get("id")):
            return False
        try:
            raw = np.frombuffer((self.dir / meta["image"]).read_bytes(), dtype=np.uint8)
            img = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        except (OSError, KeyError, ValueError, cv2.error):
            return False
        if img is None or img.size == 0:
            return False
        self.view, self.image = meta, img
        self.user_boxes, self.done, self.pending_labels = [], {}, {}
        self.selected, self._done_stack = None, []
        return True

    def age(self) -> Optional[float]:
        if not self.meta:
            return None
        stamp = _safe_float(self.meta.get("t"), -1.0)
        if stamp < 0:
            return None
        return max(0.0, time.time() - stamp)

    @property
    def learning_allowed(self) -> bool:
        return bool(self.meta and self.meta.get("learning", False) and not self.meta.get("autoplay", False))

    def health(self) -> Tuple[str, str]:
        """Return status copy and a severity: ok / warn / bad / info."""
        if self.last_io_error:
            return self.last_io_error, "bad"
        if self.meta is None:
            return "Waiting for the bot. Start Preview or Live and keep the game unpaused.", "warn"
        age = self.age()
        if age is None or age > self.STALE_S:
            return "No fresh frames: the bot may be stopped, paused (F9), or unable to see the game window.", "warn"
        if not self.learning_allowed:
            return "Learning is OFF (AUTO PLAY or learning disabled). Labels cannot be saved.", "bad"
        n = len(self.view.get("ghosts", [])) if self.view else 0
        if self.frozen:
            return f"Frozen snapshot · {n} detected box(es). Label carefully, then resume live.", "info"
        return f"Live · {n} detected box(es). Click a box to freeze this exact frame.", "ok"

    @property
    def ghosts(self) -> List[dict]:
        if not self.view:
            return []
        out = []
        for item in self.view.get("ghosts", []):
            if not isinstance(item, dict):
                continue
            x, y, w, h = (_safe_int(item.get(k), -1) for k in ("x", "y", "w", "h"))
            if x < 0 or y < 0 or w < 1 or h < 1:
                continue
            fw, fh = self.frame_size
            if x >= fw or y >= fh or x + w > fw + 2 or y + h > fh + 2:
                continue
            out.append(item)
        return out

    @property
    def frame_size(self) -> Tuple[int, int]:
        if not self.view:
            return (0, 0)
        return (_safe_int(self.view.get("w")), _safe_int(self.view.get("h")))

    @property
    def counts(self) -> Tuple[int, int]:
        meta = self.meta or {}
        return _safe_int(meta.get("pos")), _safe_int(meta.get("neg"))

    # ---------------------------------------------------------------- boxes + review queue
    def box_of(self, key: Key) -> Optional[Tuple[int, int, int, int]]:
        if isinstance(key, tuple):
            idx = key[1]
            return self.user_boxes[idx] if key[0] == "u" and 0 <= idx < len(self.user_boxes) else None
        ghosts = self.ghosts
        if isinstance(key, int) and 0 <= key < len(ghosts):
            g = ghosts[key]
            return (_safe_int(g.get("x")), _safe_int(g.get("y")),
                    _safe_int(g.get("w")), _safe_int(g.get("h")))
        return None

    def keys(self) -> List[Key]:
        return list(range(len(self.ghosts))) + [("u", i) for i in range(len(self.user_boxes))]

    def confidence(self, key: Key) -> Optional[float]:
        if not isinstance(key, int) or not (0 <= key < len(self.ghosts)):
            return None
        return max(0.0, min(1.0, _safe_float(self.ghosts[key].get("conf"), 0.0)))

    def review_keys(self, sort_order: str = "Lowest confidence", filter_mode: str = "Unlabeled") -> List[Key]:
        keys = self.keys()
        if filter_mode == "Unlabeled":
            keys = [k for k in keys if k not in self.done and k not in self.pending_labels]
        elif filter_mode == "Labeled":
            keys = [k for k in keys if k in self.done]
        elif filter_mode == "Low confidence":
            keys = [k for k in keys if isinstance(k, int) and (self.confidence(k) or 0.0) < 0.70]
        if sort_order == "Lowest confidence":
            keys.sort(key=lambda k: (self.confidence(k) if self.confidence(k) is not None else 2.0,
                                     -(self.box_of(k) or (0, 0, 0, 0))[2] * (self.box_of(k) or (0, 0, 0, 0))[3]))
        elif sort_order == "Largest first":
            keys.sort(key=lambda k: -((self.box_of(k) or (0, 0, 0, 0))[2] * (self.box_of(k) or (0, 0, 0, 0))[3]))
        elif sort_order == "Smallest first":
            keys.sort(key=lambda k: (self.box_of(k) or (0, 0, 0, 0))[2] * (self.box_of(k) or (0, 0, 0, 0))[3])
        # On-screen order keeps the detector's natural list ordering.
        return keys

    def hit(self, fx: float, fy: float) -> Optional[Key]:
        """Return the smallest box under a frame-space point, so nested boxes remain reachable."""
        best: Optional[Key] = None
        best_area = math.inf
        for key in reversed(self.keys()):
            box = self.box_of(key)
            if box is None:
                continue
            x, y, w, h = box
            margin = 0.12 * max(w, h)
            if x - margin <= fx <= x + w + margin and y - margin <= fy <= y + h + margin:
                area = w * h
                if area < best_area:
                    best, best_area = key, area
        return best

    def next_key(self, after: Optional[Key] = None, direction: int = 1,
                 sort_order: str = "Lowest confidence", filter_mode: str = "Unlabeled") -> Optional[Key]:
        keys = self.review_keys(sort_order, filter_mode)
        if not keys:
            return None
        if after not in keys:
            return keys[0] if direction >= 0 else keys[-1]
        start = keys.index(after)
        return keys[(start + (1 if direction >= 0 else -1)) % len(keys)]

    def add_user_box(self, x: float, y: float, w: float, h: float) -> Optional[Key]:
        fw, fh = self.frame_size
        if fw < 1 or fh < 1 or not all(math.isfinite(v) for v in (x, y, w, h)):
            return None
        x0, y0 = max(0, min(fw, int(round(x)))), max(0, min(fh, int(round(y))))
        x1, y1 = max(0, min(fw, int(round(x + w)))), max(0, min(fh, int(round(y + h))))
        if x1 - x0 < 8 or y1 - y0 < 8:
            return None
        self.user_boxes.append((x0, y0, x1 - x0, y1 - y0))
        return ("u", len(self.user_boxes) - 1)

    # ---------------------------------------------------------------- freeze / resume
    def freeze(self) -> bool:
        if self.frozen or self.view is None:
            return self.frozen
        snap = _safe_int(self.view.get("id"))
        # OverlayTeacher acknowledges only a failed pin; a successful pin is silent.
        # Do not track it as a request that must receive a result.json acknowledgement.
        cid = self._send({"op": "pin", "snap": snap})
        if cid is None:
            return False
        self.frozen = True
        return True

    def resume(self) -> None:
        if not self.frozen:
            return
        self._send({"op": "unpin"})
        self.frozen = False
        self.view, self.image = None, None  # force next poll to load the newest frame
        self.user_boxes, self.done, self.pending_labels = [], {}, {}
        self.selected, self._done_stack = None, []

    # ---------------------------------------------------------------- commands
    def label(self, key: Key, verdict: str, kind: str = "", colour: str = "") -> bool:
        if verdict not in VALID_VERDICTS or self.view is None or self.box_of(key) is None:
            return False
        frame_age = self.age()
        if not self.learning_allowed or frame_age is None or frame_age > self.STALE_S:
            return False
        if key in self.pending_labels or key in self.done:
            return False
        if verdict == "colour":
            allowed = SMALL_COLOURS if kind == "small" else BOSS_COLOURS if kind == "boss" else ()
            if colour not in allowed:
                return False
        if not self.frozen and not self.freeze():
            return False
        box = self.box_of(key)
        if box is None:
            return False
        det = ""
        if isinstance(key, int):
            g = self.ghosts[key]
            det = f"{g.get('kind', '')} {g.get('color', '')}".strip()
        cid = self._send({"op": "label", "snap": _safe_int(self.view.get("id")), "box": list(box),
                          "verdict": verdict, "kind": kind, "colour": colour, "det": det},
                         track={"op": "label", "key": key, "snap": _safe_int(self.view.get("id")),
                                "tag": {"ghost": "ghost", "not_ghost": "not", "colour": f"{kind} {colour}"}[verdict],
                                "keys": [key]})
        if cid is None:
            return False
        self.pending_labels[key] = {"ghost": "ghost", "not_ghost": "not", "colour": f"{kind} {colour}"}[verdict]
        return True

    def label_all(self) -> bool:
        frame_age = self.age()
        if self.view is None or not self.ghosts or not self.learning_allowed or frame_age is None or frame_age > self.STALE_S:
            return False
        if not self.frozen and not self.freeze():
            return False
        keys = list(range(min(len(self.ghosts), ALL_BATCH_LIMIT)))
        cid = self._send({"op": "all", "snap": _safe_int(self.view.get("id"))},
                         track={"op": "all", "snap": _safe_int(self.view.get("id")),
                                "keys": keys, "overflow": len(self.ghosts) > ALL_BATCH_LIMIT})
        if cid is None:
            return False
        for key in keys:
            self.pending_labels[key] = "ghost"
        return True

    def undo(self) -> bool:
        return self._send({"op": "undo"}, track={"op": "undo", "snap": _safe_int(self.view.get("id")) if self.view else 0,
                                                  "keys": []}) is not None

    def poll_results(self) -> List[Tuple[bool, str]]:
        """Consume result acknowledgements and expose user-readable feedback."""
        path = self.dir / "result.json"
        try:
            stat = path.stat()
            if stat.st_mtime_ns == self._result_mtime_ns:
                return self._expire_pending()
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return self._expire_pending()
        self._result_mtime_ns = stat.st_mtime_ns
        if not isinstance(data, dict):
            return self._expire_pending()
        self.undo_depth = _safe_int(data.get("undo"), self.undo_depth)
        results = data.get("results", [])
        out: List[Tuple[bool, str]] = []
        if isinstance(results, list):
            for result in results:
                if not isinstance(result, dict):
                    continue
                cid = str(result.get("cid", ""))
                if not cid or cid in self._seen or cid not in self._pending:
                    continue
                self._remember_seen(cid)
                pending = self._pending.pop(cid)
                op = pending.get("op")
                ok = bool(result.get("ok"))
                snap = _safe_int(pending.get("snap"))
                keys = list(pending.get("keys", []))
                visible_frame = self.view is not None and _safe_int(self.view.get("id")) == snap
                for key in keys:
                    self.pending_labels.pop(key, None)
                if ok and op in ("label", "all") and visible_frame:
                    tag = str(pending.get("tag", "ghost"))
                    for key in keys:
                        if self.box_of(key) is not None:
                            self.done[key] = tag
                    if keys:
                        self._done_stack.append((snap, keys))
                elif op == "undo" and ok:
                    if self._done_stack and self._done_stack[-1][0] == snap:
                        _s, undone_keys = self._done_stack.pop()
                        if visible_frame:
                            for key in undone_keys:
                                self.done.pop(key, None)
                msg = str(result.get("msg", "")).strip()
                if op == "all" and pending.get("overflow") and ok:
                    msg = (msg + " · only the first 12 detected boxes are marked here (bot batch cap). ").strip()
                if msg:
                    out.append((ok, msg))
        out.extend(self._expire_pending())
        return out

    def _remember_seen(self, cid: str) -> None:
        self._seen.add(cid)
        self._seen_order.append(cid)
        if len(self._seen_order) > self.SEEN_RESULT_LIMIT:
            old = self._seen_order.popleft()
            self._seen.discard(old)

    def _expire_pending(self) -> List[Tuple[bool, str]]:
        now = time.monotonic()
        out = []
        expired = [cid for cid, item in self._pending.items()
                   if now - _safe_float(item.get("issued_at"), now) > self.COMMAND_TIMEOUT_S]
        for cid in expired:
            item = self._pending.pop(cid)
            for key in item.get("keys", []):
                self.pending_labels.pop(key, None)
            out.append((False, f"Bot acknowledgement timed out for {item.get('op', 'command')}; no success was confirmed."))
        return out


# ============================================================================
class TeachWindow(tk.Toplevel):
    """Dark, keyboard-friendly live annotation window."""

    PAL = dict(BG="#0a0f1c", PANEL="#111a2e", PANEL2="#16213a", EDGE="#26344f", TEXT="#e8eefc",
               MUTED="#8fa0bb", ACCENT="#54e0c1", ORANGE="#ffba66", RED="#ff6e83", GREEN="#76e4a5", BLUE="#65a8ff")
    SORT_OPTIONS = ("Lowest confidence", "Largest first", "Smallest first", "On-screen order")
    FILTER_OPTIONS = ("Unlabeled", "All", "Low confidence", "Labeled")

    def __init__(self, root: tk.Misc, project: Path, smart_request: Optional[Callable[[str], None]] = None,
                 palette: Optional[dict] = None):
        super().__init__(root)
        if palette:
            self.PAL = {**self.PAL, **palette}
        self.project = Path(project)
        self._smart_request = smart_request
        self.session = TeachSession(self.project)
        self.title("BLOOP · Smart Teach")
        self.configure(bg=self.PAL["BG"])
        self.geometry("1420x850")
        self.minsize(1020, 650)
        self._photo = None
        self._photo_key = None
        self._geom = (1.0, 0, 0)  # display pixels per native frame pixel, x offset, y offset
        self._fit_scale = 1.0
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._p0: Optional[Tuple[int, int]] = None
        self._pan_start: Optional[Tuple[int, int, float, float]] = None
        self._drag_item = None
        self._dragging = False
        self._panning = False
        self._toast_until = 0.0
        self._job = None
        self._closing = False
        self.sort_var = tk.StringVar(value="Lowest confidence")
        self.filter_var = tk.StringVar(value="Unlabeled")
        self._build()
        self.bind("<Key>", self._on_key)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._tick()

    # ---------------------------------------------------------------- layout
    def _build(self) -> None:
        P = self.PAL
        top = tk.Frame(self, bg=P["BG"], padx=14, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="BLOOP  /  SMART TEACH", bg=P["BG"], fg=P["TEXT"],
                 font=("Segoe UI Semibold", 16)).pack(side="left")
        self.top_btn = ttk.Button(top, text="Freeze picture (P)", command=self._toggle_freeze)
        self.top_btn.pack(side="right")
        self.ontop = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Keep on top", variable=self.ontop,
                        command=lambda: self.attributes("-topmost", bool(self.ontop.get()))).pack(side="right", padx=12)
        self.status = tk.Label(self, text="", bg=P["PANEL"], fg=P["ACCENT"], anchor="w", padx=14, pady=7,
                               font=("Segoe UI", 10))
        self.status.pack(fill="x", padx=14)

        stats = tk.Frame(self, bg=P["BG"], padx=14, pady=(7, 0))
        stats.pack(fill="x")
        self.stat_vars = {k: tk.StringVar(value="—") for k in ("frame", "age", "boxes", "labels", "library", "zoom")}
        for col, (key, label) in enumerate((("frame", "SNAPSHOT"), ("age", "LIVE AGE"), ("boxes", "DETECTED"),
                                            ("labels", "REVIEWED"), ("library", "LIBRARY"), ("zoom", "ZOOM"))):
            tile = tk.Frame(stats, bg=P["PANEL"], padx=10, pady=6, highlightthickness=1, highlightbackground=P["EDGE"])
            tile.pack(side="left", fill="x", expand=True, padx=(0, 6))
            tk.Label(tile, text=label, bg=P["PANEL"], fg=P["MUTED"], font=("Consolas", 8, "bold")).pack(anchor="w")
            tk.Label(tile, textvariable=self.stat_vars[key], bg=P["PANEL"], fg=P["TEXT"],
                     font=("Segoe UI Semibold", 10)).pack(anchor="w", pady=(2, 0))

        body = tk.Frame(self, bg=P["BG"])
        body.pack(fill="both", expand=True, padx=14, pady=10)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        toolbar = tk.Frame(body, bg=P["PANEL"], padx=8, pady=7)
        toolbar.grid(row=0, column=0, sticky="ew")
        tk.Label(toolbar, text="Review", bg=P["PANEL"], fg=P["MUTED"], font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        self.sort_combo = ttk.Combobox(toolbar, state="readonly", width=20, values=self.SORT_OPTIONS, textvariable=self.sort_var)
        self.sort_combo.pack(side="left", padx=(0, 8))
        self.sort_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_labels())
        self.filter_combo = ttk.Combobox(toolbar, state="readonly", width=14, values=self.FILTER_OPTIONS, textvariable=self.filter_var)
        self.filter_combo.pack(side="left", padx=(0, 10))
        self.filter_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_labels())
        ttk.Button(toolbar, text="← Previous", command=lambda: self._navigate(-1)).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Next →", command=lambda: self._navigate(1)).pack(side="left", padx=2)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="−", width=3, command=lambda: self._set_zoom(self.zoom / 1.2)).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Fit", command=self._fit_image).pack(side="left", padx=2)
        ttk.Button(toolbar, text="+", width=3, command=lambda: self._set_zoom(self.zoom * 1.2)).pack(side="left", padx=2)
        tk.Label(toolbar, text="Wheel: zoom · Shift+drag: pan · drag: draw missed ghost", bg=P["PANEL"], fg=P["MUTED"],
                 font=("Segoe UI", 8)).pack(side="right", padx=4)

        wrap = tk.Frame(body, bg=P["EDGE"], padx=1, pady=1)
        wrap.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.canvas = tk.Canvas(wrap, bg="#05080f", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<ButtonPress-2>", self._pan_press)
        self.canvas.bind("<B2-Motion>", self._pan_motion)
        self.canvas.bind("<ButtonRelease-2>", self._pan_release)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda e: self._wheel_steps(e, 1))
        self.canvas.bind("<Button-5>", lambda e: self._wheel_steps(e, -1))

        side = tk.Frame(body, bg=P["PANEL"], highlightthickness=1, highlightbackground=P["EDGE"], padx=13, pady=12, width=326)
        side.grid(row=0, column=1, rowspan=2, sticky="ns", padx=(12, 0))
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        side.grid_columnconfigure(1, weight=1)

        def head(text, row):
            tk.Label(side, text=text, bg=P["PANEL"], fg=P["MUTED"], font=("Consolas", 8, "bold")).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(10, 3))

        head("SELECTED OBJECT", 0)
        self.sel_lbl = tk.Label(side, text="Click a detected box or draw a rectangle around a missed ghost.",
                                bg=P["PANEL"], fg=P["TEXT"], justify="left", anchor="w", wraplength=285,
                                font=("Segoe UI", 10))
        self.sel_lbl.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.sel_detail = tk.Label(side, text="", bg=P["PANEL"], fg=P["MUTED"], justify="left", anchor="w",
                                   wraplength=285, font=("Consolas", 8))
        self.sel_detail.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(5, 0))

        head("1 · GHOST OR NOT?", 3)
        self.action_buttons = []
        self.action_buttons.append(self._btn(side, "✔  IS a ghost   [Space]", P["GREEN"], lambda: self._act("ghost")))
        self.action_buttons[-1].grid(row=4, column=0, columnspan=2, sticky="ew", pady=2)
        self.action_buttons.append(self._btn(side, "✖  NOT a ghost   [X]", P["RED"], lambda: self._act("not_ghost")))
        self.action_buttons[-1].grid(row=5, column=0, columnspan=2, sticky="ew", pady=2)

        head("2 · EXACT CLASS (ALSO A POSITIVE)", 6)
        tk.Label(side, text="Small ghost", bg=P["PANEL"], fg=P["TEXT"], font=("Segoe UI", 9)).grid(
            row=7, column=0, columnspan=2, sticky="w")
        row = 8
        for i, (key, colour) in enumerate(SMALL_KEYS.items()):
            b = self._chip(side, f"{key}  {colour}", colour, lambda c=colour: self._act("colour", "small", c))
            b.grid(row=row + i // 2, column=i % 2, sticky="ew", padx=1, pady=1)
            self.action_buttons.append(b)
        row += 2
        tk.Label(side, text="Boss", bg=P["PANEL"], fg=P["TEXT"], font=("Segoe UI", 9)).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
        row += 1
        for i, (key, colour) in enumerate(BOSS_KEYS.items()):
            b = self._chip(side, f"{key.upper()}  {colour}", colour, lambda c=colour: self._act("colour", "boss", c))
            b.grid(row=row + i // 2, column=i % 2, sticky="ew", padx=1, pady=1)
            self.action_buttons.append(b)
        row += 4
        head("TOOLS", row)
        row += 1
        self.all_btn = ttk.Button(side, text="All detected boxes are ghosts", command=self._all)
        self.all_btn.grid(row=row, column=0, columnspan=2, sticky="ew", pady=2)
        row += 1
        self.undo_btn = ttk.Button(side, text="Undo last  [Ctrl+Z]", command=self.session.undo)
        self.undo_btn.grid(row=row, column=0, sticky="ew", pady=2, padx=(0, 2))
        if self._smart_request is not None:
            ttk.Button(side, text="Retrain now", command=lambda: self._smart_request("retrain")).grid(
                row=row, column=1, sticky="ew", pady=2, padx=(2, 0))
        row += 1
        self.toast_lbl = tk.Label(side, text="", bg=P["PANEL"], fg=P["ACCENT"], anchor="w", justify="left",
                                  wraplength=285, font=("Segoe UI", 9, "bold"))
        self.toast_lbl.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(9, 0))

        tk.Label(self, text="Space = ghost · X = not a ghost · Tab/→ = next · ← = previous · 1–4 = small colour · "
                            "Q W E R T Y U = boss colour · Ctrl+Z = undo · P = freeze/resume · +/− = zoom · 0 = fit",
                 bg=P["BG"], fg=P["MUTED"], font=("Segoe UI", 8)).pack(fill="x", padx=14, pady=(0, 8))

    def _btn(self, parent, text, colour, cmd):
        return tk.Button(parent, text=text, command=cmd, bg=colour, fg="#07101c", activebackground=colour,
                         relief="flat", bd=0, font=("Segoe UI Semibold", 10), pady=7, cursor="hand2")

    def _chip(self, parent, text, colour, cmd):
        bg = COLOUR_HEX.get(colour, "#888888")
        r, g, b = (int(bg[i:i + 2], 16) for i in (1, 3, 5))
        fg = "#07101c" if (0.299 * r + 0.587 * g + 0.114 * b) > 140 else "#ffffff"
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg, activebackground=bg, relief="flat", bd=0,
                         font=("Segoe UI", 9, "bold"), pady=4, cursor="hand2")

    # ---------------------------------------------------------------- periodic work
    def _tick(self) -> None:
        if self._closing:
            return
        try:
            s = self.session
            s.heartbeat()
            changed = s.poll()
            results = s.poll_results()
            for ok, msg in results:
                self._toast(msg, ok)
            if changed or results:
                self._redraw()
            self._refresh_labels()
        except Exception as exc:  # UI faults must not silently kill polling
            self._toast(f"Teach window recovered from an error: {exc}", False)
        self._job = self.after(250, self._tick)

    def _refresh_labels(self) -> None:
        P = self.PAL
        text, level = self.session.health()
        self.status.config(text="● " + text,
                           fg={"ok": P["GREEN"], "info": P["BLUE"], "warn": P["ORANGE"], "bad": P["RED"]}.get(level, P["MUTED"]))
        self.top_btn.config(text="Resume live (P)" if self.session.frozen else "Freeze picture (P)")
        frame_id = self.session.view.get("id", "—") if self.session.view else "—"
        age = self.session.age()
        ghosts = self.session.ghosts
        reviewed = sum(1 for k in self.session.done if isinstance(k, int))
        self.stat_vars["frame"].set(str(frame_id))
        self.stat_vars["age"].set(f"{age:.1f}s" if age is not None else "waiting")
        self.stat_vars["boxes"].set(f"{len(ghosts)} detected")
        self.stat_vars["labels"].set(f"{reviewed}/{len(ghosts)} confirmed")
        pos, neg = self.session.counts
        self.stat_vars["library"].set(f"+{pos:,} / −{neg:,}")
        self.stat_vars["zoom"].set(f"{int(round(self.zoom * 100))}%")
        key = self.session.selected
        box = self.session.box_of(key) if key is not None else None
        if box is None:
            self.sel_lbl.config(text="Click a detected box or draw a rectangle around a missed ghost.")
            self.sel_detail.config(text="")
        elif isinstance(key, int) and key < len(self.session.ghosts):
            ghost = self.session.ghosts[key]
            conf = max(0.0, min(1.0, _safe_float(ghost.get("conf"))))
            self.sel_lbl.config(text=f"Detected: {ghost.get('kind', 'unknown')} {ghost.get('color', 'unknown')} · {conf:.0%}")
            self.sel_detail.config(text=f"Box: x={box[0]} y={box[1]}  w={box[2]} h={box[3]}\n"
                                        f"Status: {self.session.done.get(key, self.session.pending_labels.get(key, 'unlabeled'))}")
        else:
            self.sel_lbl.config(text=f"Manual box · {box[2]}×{box[3]} pixels")
            self.sel_detail.config(text=f"Box: x={box[0]} y={box[1]}  w={box[2]} h={box[3]}\nStatus: "
                                        f"{self.session.done.get(key, self.session.pending_labels.get(key, 'unlabeled'))}")
        selected_ready = key is not None and box is not None and key not in self.session.done and key not in self.session.pending_labels
        can_save = self.session.learning_allowed and self.session.age() is not None and self.session.age() <= TeachSession.STALE_S
        for button in self.action_buttons:
            button.configure(state="normal" if selected_ready and can_save else "disabled")
        self.all_btn.configure(state="normal" if can_save and bool(ghosts) and not any(isinstance(k, int) for k in self.session.pending_labels) else "disabled")
        self.undo_btn.configure(state="normal" if self.session.undo_depth > 0 or self.session._done_stack else "disabled")
        if self._toast_until and time.time() > self._toast_until:
            self.toast_lbl.config(text="")
            self._toast_until = 0.0

    def _toast(self, text: str, ok: bool = True) -> None:
        self.toast_lbl.config(text=str(text), fg=self.PAL["GREEN"] if ok else self.PAL["ORANGE"])
        self._toast_until = time.time() + 7.0

    # ---------------------------------------------------------------- drawing
    def _redraw(self) -> None:
        canvas, session = self.canvas, self.session
        canvas.delete("all")
        cw, ch = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
        if session.image is None or session.view is None:
            canvas.create_text(cw // 2, ch // 2, fill=self.PAL["MUTED"], font=("Segoe UI", 12), justify="center",
                               text="Waiting for a bot snapshot\n\nStart Preview or Live, open the Highrise game,\nand leave the bot unpaused.")
            self._geom = (1.0, 0, 0)
            self._photo_key = None
            return
        fw, fh = session.frame_size
        if fw < 1 or fh < 1:
            return
        self._fit_scale = max(0.0001, min(cw / fw, ch / fh))
        scale = self._fit_scale * self.zoom
        dw, dh = max(1, int(round(fw * scale))), max(1, int(round(fh * scale)))
        self._clamp_pan(cw, ch, dw, dh)
        ox = int((cw - dw) / 2 + self.pan_x)
        oy = int((ch - dh) / 2 + self.pan_y)
        self._geom = (scale, ox, oy)
        photo_key = (session.view.get("id"), dw, dh)
        if photo_key != self._photo_key:
            try:
                img = cv2.resize(session.image, (dw, dh), interpolation=cv2.INTER_AREA if scale <= 1 else cv2.INTER_LINEAR)
                ok, png = cv2.imencode(".png", img)
                if ok:
                    self._photo = tk.PhotoImage(data=base64.b64encode(png.tobytes()).decode("ascii"))
                    self._photo_key = photo_key
            except (cv2.error, tk.TclError, MemoryError) as exc:
                self._toast(f"Could not render snapshot: {exc}", False)
                return
        if self._photo is not None:
            canvas.create_image(ox, oy, anchor="nw", image=self._photo)
        # Draw a low-cost review overlay; class colour communicates the classifier's label,
        # while confidence affects stroke style so uncertain detections are easier to spot.
        for key in session.keys():
            box = session.box_of(key)
            if box is None:
                continue
            x, y, w, h = box
            x0, y0, x1, y1 = ox + x * scale, oy + y * scale, ox + (x + w) * scale, oy + (y + h) * scale
            if isinstance(key, int):
                ghost = session.ghosts[key]
                conf = max(0.0, min(1.0, _safe_float(ghost.get("conf"))))
                class_colour = COLOUR_HEX.get(str(ghost.get("color", "")).lower(), "#ffffff")
                confidence_colour = self.PAL["RED"] if conf < 0.60 else self.PAL["ORANGE"] if conf < 0.80 else self.PAL["GREEN"]
                label = f"{ghost.get('kind', '?')} {ghost.get('color', '?')}  {conf:.0%}"
                dash = (4, 3) if conf < 0.70 else None
                outline = confidence_colour if conf < 0.80 else class_colour
            else:
                class_colour, outline, label, dash = "#ffba66", "#ffba66", "manual box", (5, 3)
            if key in session.pending_labels:
                outline, label = self.PAL["BLUE"], "… saving label"
            verdict = session.done.get(key)
            if verdict:
                outline = self.PAL["RED"] if verdict == "not" else self.PAL["GREEN"]
                label = ("✖ " if verdict == "not" else "✔ ") + (verdict if verdict not in ("ghost", "not") else label)
                dash = (2, 3)
            canvas.create_rectangle(x0 - 1, y0 - 1, x1 + 1, y1 + 1, outline="#000000", width=4)
            canvas.create_rectangle(x0, y0, x1, y1, outline=outline, width=4 if key == session.selected else 2,
                                    dash=dash if dash else "")
            if key == session.selected:
                canvas.create_rectangle(x0 - 5, y0 - 5, x1 + 5, y1 + 5, outline="#ffffff", width=2)
            ty, anchor = (y0 - 4, "sw") if y0 > 24 else (y1 + 4, "nw")
            # Dark text halo keeps labels readable over both bright and dark scenes.
            for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                canvas.create_text(x0 + dx, ty + dy, text=label, fill="#000000", anchor=anchor, font=("Segoe UI", 9, "bold"))
            canvas.create_text(x0, ty, text=label, fill=outline, anchor=anchor, font=("Segoe UI", 9, "bold"))

    def _clamp_pan(self, cw: int, ch: int, dw: int, dh: int) -> None:
        if dw <= cw:
            self.pan_x = 0.0
        else:
            self.pan_x = min(0.0, max(float(cw - dw), self.pan_x))
        if dh <= ch:
            self.pan_y = 0.0
        else:
            self.pan_y = min(0.0, max(float(ch - dh), self.pan_y))

    def _to_frame(self, x: float, y: float) -> Tuple[float, float]:
        scale, ox, oy = self._geom
        if scale <= 0:
            return -1.0, -1.0
        return (x - ox) / scale, (y - oy) / scale

    # ---------------------------------------------------------------- mouse + zoom
    def _press(self, event) -> None:
        self.canvas.focus_set()
        if event.state & 0x0001:  # Shift+left drag pans; plain drag annotates missed objects.
            self._pan_start = (event.x, event.y, self.pan_x, self.pan_y)
            self._panning = True
            self._p0 = None
            return
        self._p0 = (event.x, event.y)
        self._dragging = False

    def _motion(self, event) -> None:
        if self._panning and self._pan_start is not None:
            self.pan_x = self._pan_start[2] + event.x - self._pan_start[0]
            self.pan_y = self._pan_start[3] + event.y - self._pan_start[1]
            self._redraw()
            return
        if self._p0 is None or self.session.image is None:
            return
        if not self._dragging and (abs(event.x - self._p0[0]) > 6 or abs(event.y - self._p0[1]) > 6):
            self._dragging = True
            self._drag_item = self.canvas.create_rectangle(*self._p0, event.x, event.y,
                                                           outline=self.PAL["ORANGE"], width=2, dash=(5, 3))
        if self._dragging and self._drag_item is not None:
            self.canvas.coords(self._drag_item, self._p0[0], self._p0[1], event.x, event.y)

    def _release(self, event) -> None:
        if self._panning:
            self._panning, self._pan_start = False, None
            self._redraw()
            return
        point0, self._p0 = self._p0, None
        if point0 is None or self.session.image is None:
            return
        session = self.session
        if self._dragging:
            self._dragging = False
            if self._drag_item is not None:
                self.canvas.delete(self._drag_item)
                self._drag_item = None
            ax, ay = self._to_frame(min(point0[0], event.x), min(point0[1], event.y))
            bx, by = self._to_frame(max(point0[0], event.x), max(point0[1], event.y))
            if not session.frozen and not session.freeze():
                self._toast("Could not freeze this snapshot; try again.", False)
                return
            key = session.add_user_box(ax, ay, bx - ax, by - ay)
            if key is None:
                self._toast("That rectangle is too small; draw at least 8×8 frame pixels.", False)
            else:
                session.selected = key
        else:
            key = session.hit(*self._to_frame(event.x, event.y))
            if key is not None:
                if not session.frozen and not session.freeze():
                    self._toast("Could not freeze this snapshot; try again.", False)
                    return
                session.selected = key
            else:
                session.selected = None
        self._redraw()
        self._refresh_labels()

    def _pan_press(self, event) -> None:
        self.canvas.focus_set()
        self._pan_start = (event.x, event.y, self.pan_x, self.pan_y)
        self._panning = True

    def _pan_motion(self, event) -> None:
        self._motion(event)

    def _pan_release(self, _event) -> None:
        self._panning, self._pan_start = False, None
        self._redraw()

    def _wheel(self, event) -> None:
        delta = getattr(event, "delta", 0)
        steps = 1 if delta > 0 else -1 if delta < 0 else 0
        self._wheel_steps(event, steps)

    def _wheel_steps(self, event, steps: int) -> None:
        if not steps:
            return
        fx, fy = self._to_frame(event.x, event.y)
        old_scale, _ox, _oy = self._geom
        if old_scale <= 0:
            return
        new_zoom = max(1.0, min(4.0, self.zoom * (1.15 ** steps)))
        if abs(new_zoom - self.zoom) < 1e-6:
            return
        self.zoom = new_zoom
        self.update_idletasks()
        cw, ch = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        fw, fh = self.session.frame_size
        if fw and fh:
            new_scale = min(cw / fw, ch / fh) * self.zoom
            dw, dh = fw * new_scale, fh * new_scale
            self.pan_x = event.x - fx * new_scale - (cw - dw) / 2
            self.pan_y = event.y - fy * new_scale - (ch - dh) / 2
        self._redraw()

    def _set_zoom(self, zoom: float) -> None:
        self.zoom = max(1.0, min(4.0, float(zoom)))
        if self.zoom == 1.0:
            self.pan_x = self.pan_y = 0.0
        self._redraw()
        self._refresh_labels()

    def _fit_image(self) -> None:
        self.zoom = 1.0
        self.pan_x = self.pan_y = 0.0
        self._redraw()
        self._refresh_labels()

    # ---------------------------------------------------------------- actions + keyboard
    def _toggle_freeze(self) -> None:
        if self.session.frozen:
            self.session.resume()
            self._fit_image()
        elif not self.session.freeze():
            self._toast("No snapshot to freeze yet.", False)
        self._redraw()
        self._refresh_labels()

    def _navigate(self, direction: int) -> None:
        key = self.session.next_key(self.session.selected, direction=direction,
                                    sort_order=self.sort_var.get(), filter_mode=self.filter_var.get())
        if key is None:
            self._toast("No boxes match this review filter.", False)
            return
        self.session.selected = key
        self._redraw()
        self._refresh_labels()

    def _act(self, verdict: str, kind: str = "", colour: str = "") -> None:
        session = self.session
        key = session.selected
        if key is None:
            self._toast("Select a box first (or drag a rectangle around a missed ghost).", False)
            return
        if not session.learning_allowed or session.age() is None or session.age() > TeachSession.STALE_S:
            self._toast("Learning is disabled or the latest bot frame is stale; nothing was sent.", False)
            return
        if session.label(key, verdict, kind, colour):
            session.selected = session.next_key(key, sort_order=self.sort_var.get(), filter_mode=self.filter_var.get())
            self._toast("Waiting for the bot to confirm the label…", True)
        else:
            self._toast("Label was not sent. Check that the snapshot is current and learning is enabled.", False)
        self._redraw()
        self._refresh_labels()

    def _all(self) -> None:
        if not self.session.learning_allowed:
            self._toast("Learning is disabled; nothing was sent.", False)
            return
        if not self.session.frozen and not self.session.freeze():
            self._toast("No snapshot to freeze yet.", False)
            return
        total = len(self.session.ghosts)
        if not self.session.label_all():
            self._toast("There are no detected boxes, the frame is stale, or a command failed.", False)
        else:
            self._toast(f"Batch label sent for up to {min(total, ALL_BATCH_LIMIT)} detected boxes…", True)
        self._redraw()
        self._refresh_labels()

    def _on_key(self, event):
        focus = self.focus_get()
        if isinstance(focus, (tk.Entry, ttk.Entry, tk.Text, ttk.Combobox)):
            return None
        key = (getattr(event, "keysym", "") or "").lower()
        char = (getattr(event, "char", "") or "").lower()
        if event.state & 0x4 and key == "z":
            if not self.session.undo():
                self._toast("Could not send undo.", False)
            return "break"
        if event.state & (0x4 | 0x20000):
            return None
        if key in ("space", "return"):
            self._act("ghost")
        elif char == "x" or key == "delete":
            self._act("not_ghost")
        elif char == "p":
            self._toggle_freeze()
        elif key in ("tab", "right"):
            self._navigate(1)
        elif key == "left" or (key in ("tab", "iso_left_tab") and bool(event.state & 0x0001)):
            self._navigate(-1)
        elif char in SMALL_KEYS:
            self._act("colour", "small", SMALL_KEYS[char])
        elif char in BOSS_KEYS:
            self._act("colour", "boss", BOSS_KEYS[char])
        elif char in ("+", "=") or key in ("plus", "equal"):
            self._set_zoom(self.zoom * 1.2)
        elif char == "-" or key == "minus":
            self._set_zoom(self.zoom / 1.2)
        elif char == "0":
            self._fit_image()
        else:
            return None
        return "break"

    def _on_close(self) -> None:
        self._closing = True
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except (tk.TclError, ValueError):
                pass
        self.session.close()
        try:
            self.destroy()
        except tk.TclError:
            pass
