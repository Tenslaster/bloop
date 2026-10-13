"""Teach the models from the on-screen overlay.

Three ways, all optional (config.json):

1. TEACH MODE  (hotkey hk_teach, default F4; auto-off after overlay_teach_timeout_s of no key)
   Hover a ghost box with the mouse, then press:
       SPACE  it IS a ghost            (positive sample, like a click)
       X      it is NOT a ghost        (negative sample, like F8)
       A      every box shown is a ghost
       1 2 3 4              small ghost: blue / purple / yellow / rainbow
       Q W E R T Y U        boss: blue / cyan / green / light green / red / white / rainbow
       BACKSPACE            undo the last action
   A colour key also counts as "it is a ghost". While the mode is on those keys are swallowed so they do
   not reach the game; the overlay shows a legend while it is on.
   Use it in Preview (the bot does not move your mouse) or with --teach, not while the bot is clicking.

2. COLOUR / KIND CORRECTION  is the colour keys above: the crop is filed in labels/<kind>_<colour>/ exactly
   like label_ghosts.py would, and the running colour model learns it at once (no F10, no restart).

3. AUTO-LEARNING  (overlay_auto_learn): boxes the overlay shows that the model is very sure about, that
   really move, and that nobody clicked, are saved as low-weight positives (tag "ovauto"), rate-limited
   and capped at a small share of all positives. The colour model is never fed automatically: an
   automatic colour label could only repeat the model's own mistakes.

4. TEACH WINDOW (teach_gui.py, opened from the GUI's "Teach" button): the bot writes the latest frame and its
   ghost boxes to <project>/teach/ about 2-3 times a second, ONLY while that window is open. You click a box
   (or drag a rectangle round a ghost the detector missed) and press a button there; the command comes back
   through <project>/teach/cmd/ and is applied to the exact picture you clicked, so it works in Live too and
   needs no hovering and no hotkeys.

AUTO PLAY (--autoplay) learns nothing, so none of this is active there.
Hotkey callbacks only post a command; every change happens on the bot thread inside process().
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import queue
import sys
import time
import types
from collections import OrderedDict, deque
from pathlib import Path
from typing import Callable, Deque, Dict, List, Optional, Tuple

import cv2

log = logging.getLogger("bloop.teacher")

COLOR_KEYS = {
    "1": ("small", "blue"), "2": ("small", "purple"), "3": ("small", "yellow"), "4": ("small", "rainbow"),
    "q": ("boss", "blue"), "w": ("boss", "cyan"), "e": ("boss", "green"), "r": ("boss", "light green"),
    "t": ("boss", "red"), "y": ("boss", "white"), "u": ("boss", "rainbow"),
}

SMALL_COLOURS = ("blue", "purple", "yellow", "rainbow")
BOSS_COLOURS = ("blue", "cyan", "green", "light green", "red", "white", "rainbow")
TEACH_DIR = "teach"
SNAP_RING = 8            # pictures the bot remembers so a click can be applied to the exact frame you saw

HOVER = "#ffffff"
OK = "#76e4a5"
BAD = "#ff6e83"
INFO = "#54e0c1"
WARN = "#ffba66"


def cursor_pos() -> Optional[Tuple[int, int]]:
    """Mouse position in screen pixels (Windows)."""
    if sys.platform != "win32":
        return None
    try:
        class _Pt(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = _Pt()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return int(pt.x), int(pt.y)
    except Exception:
        pass
    return None


class OverlayTeacher:
    def __init__(self, cfg, smart, scene, keyboard_mod=None,
                 cursor_fn: Callable[[], Optional[Tuple[int, int]]] = cursor_pos,
                 has_overlay: bool = True):
        self.cfg = cfg
        self.smart = smart
        self.scene = scene
        self.has_overlay = bool(has_overlay)      # F4 teach mode + auto-learning need the overlay; the teach window does not
        self._kb = keyboard_mod
        self._cursor = cursor_fn
        self._cmds: "queue.Queue[tuple]" = queue.Queue()
        self._handles: List[tuple] = []          # (key, remove-handle)
        self._undo: Deque[list] = deque(maxlen=20)   # each entry: [("sample"|"label", Path), ...]
        self._toasts: Deque[tuple] = deque(maxlen=4)  # (time, text, colour)
        self.active = False
        self._last_key = 0.0
        self._refused_at = 0.0
        # --- teach window bridge (files in <project>/teach/) ---
        try:
            self.dir: Optional[Path] = Path(smart.dir).parent / TEACH_DIR
        except Exception:
            self.dir = None
        self._snaps: "OrderedDict[int, tuple]" = OrderedDict()   # id -> (frame, ghosts, image name)
        self._pinned: Dict[int, tuple] = {}
        self._snap_seq = 0
        self._last_snap = 0.0
        self._last_poll = 0.0
        self._alive_chk = 0.0
        self._alive = False
        self._results: Deque[dict] = deque(maxlen=12)

    # ------------------------------------------------------------------ hotkey side (any thread)
    @property
    def learning_allowed(self) -> bool:
        return self.smart is not None and not getattr(self.smart, "autoplay", False)

    def request_toggle(self) -> None:
        self._cmds.put(("toggle", None, self._cursor(), time.time()))

    def _post(self, name: str, arg=None) -> None:
        self._cmds.put((name, arg, self._cursor(), time.time()))

    # ------------------------------------------------------------------ bot thread
    def process(self, frame, rect: Optional[dict], now: float, items: dict) -> dict:
        """Called once per frame (right before the overlay is pushed, if there is one). Returns the decorated items."""
        try:
            while True:
                try:
                    name, arg, cur, _t = self._cmds.get_nowait()
                except queue.Empty:
                    break
                self._handle(name, arg, cur, frame, rect, now)
            if self.active and now - self._last_key > float(getattr(self.cfg, "overlay_teach_timeout_s", 45.0)):
                self._set_active(False, "teach mode timed out")
            self._bridge(frame)
            if (self.has_overlay and bool(getattr(self.cfg, "overlay_auto_learn", True)) and self.learning_allowed):
                boxes = [(g.x, g.y, g.w, g.h) for g in self.scene.scene.ghosts]
                if boxes:
                    self.smart.overlay_auto_learn(frame, boxes, now)
            self._decorate(rect, now, items)
        except Exception as exc:                   # teaching must never be able to stop the bot
            log.exception("overlay teacher error (continuing): %s", exc)
        return items

    def overlay_lost(self) -> None:
        """The overlay was switched off (self-test failed): F4 mode and auto-learning stop, the teach window keeps working."""
        self.has_overlay = False
        self._set_active(False, None)

    def shutdown(self) -> None:
        self._set_active(False, None)
        self._drop_snapshots(remove_live=True)

    # ------------------------------------------------------------------ teach window bridge
    def _bridge(self, frame) -> None:
        if self.dir is None or frame is None or not bool(getattr(self.cfg, "teach_gui", True)):
            return
        t = time.time()
        if t - self._alive_chk >= 0.5:
            self._alive_chk = t
            try:
                self._alive = (t - (self.dir / "alive").stat().st_mtime) < 4.0
            except OSError:
                self._alive = False
            if not self._alive and (self._snaps or self._pinned):
                self._drop_snapshots(remove_live=True)
        if not self._alive:
            return
        if t - self._last_poll >= 0.1:
            self._last_poll = t
            self._poll_gui(t)
        if t - self._last_snap >= float(getattr(self.cfg, "teach_gui_interval_s", 0.4)):
            self._last_snap = t
            self._export(frame, t)

    def _write_json(self, name: str, data: dict) -> None:
        tmp = self.dir / (name + ".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, self.dir / name)

    def _export(self, frame, t: float) -> None:
        self._snap_seq += 1
        sid = self._snap_seq
        ghosts = [dict(x=int(g.x), y=int(g.y), w=int(g.w), h=int(g.h), kind=str(g.kind),
                       color=str(g.color), conf=round(float(g.conf), 3)) for g in self.scene.scene.ghosts]
        H, W = frame.shape[:2]
        max_w = float(getattr(self.cfg, "teach_gui_max_w", 1280))
        scale = min(1.0, max_w / float(W)) if W else 1.0
        img = frame if scale >= 1.0 else cv2.resize(frame, (max(1, int(W * scale)), max(1, int(H * scale))),
                                                    interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        name = f"snap_{sid}.jpg"
        tmp = self.dir / "snap_tmp.part"
        tmp.write_bytes(buf.tobytes())
        os.replace(tmp, self.dir / name)
        self._snaps[sid] = (frame.copy(), ghosts, name)       # the full-resolution picture stays here, in memory
        while len(self._snaps) > SNAP_RING:
            self._snaps.popitem(last=False)
        self._cleanup_files()
        try:
            pos, neg, trained = len(self.smart.store.pos), len(self.smart.store.neg), bool(self.smart.model.trained)
        except Exception:
            pos, neg, trained = 0, 0, False
        self._write_json("live.json", {
            "id": sid, "t": t, "w": int(W), "h": int(H), "image": name, "ghosts": ghosts,
            "learning": bool(self.learning_allowed), "autoplay": bool(getattr(self.smart, "autoplay", False)),
            "trained": trained, "pos": pos, "neg": neg, "undo": len(self._undo)})

    def _cleanup_files(self) -> None:
        keep = {v[2] for v in self._snaps.values()} | {v[2] for v in self._pinned.values()}
        try:
            for p in self.dir.glob("snap_*.jpg"):
                if p.name not in keep:
                    try:
                        p.unlink()
                    except OSError:
                        pass
        except OSError:
            pass

    def _drop_snapshots(self, remove_live: bool = False) -> None:
        self._snaps.clear()
        self._pinned.clear()
        if self.dir is None:
            return
        self._cleanup_files()
        if remove_live:
            try:
                (self.dir / "live.json").unlink()
            except OSError:
                pass

    def _poll_gui(self, t: float) -> None:
        cdir = self.dir / "cmd"
        try:
            names = sorted(n for n in os.listdir(cdir) if n.endswith(".json"))
        except OSError:
            return
        for n in names:
            p = cdir / n
            c = None
            try:
                c = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
            try:
                p.unlink()
            except OSError:
                pass
            if isinstance(c, dict):
                try:
                    self._gui_command(c, t)
                except Exception as exc:
                    log.exception("teach window command failed: %s", exc)
                    self._result(str(c.get("cid", "")), str(c.get("op", "")), False, "internal error - see the log", BAD)

    def _result(self, cid: str, op: str, ok: bool, msg: str, colour: str = INFO) -> None:
        self._results.append({"cid": cid, "op": op, "ok": bool(ok), "msg": msg})
        if msg:
            self._toast(msg, colour)
        try:
            self._write_json("result.json", {"results": list(self._results), "undo": len(self._undo), "t": time.time()})
        except OSError:
            pass

    def _snap(self, sid: int):
        return self._snaps.get(sid) or self._pinned.get(sid)

    def _gui_command(self, c: dict, t: float) -> None:
        op, cid = str(c.get("op", "")), str(c.get("cid", ""))
        if op == "pin":
            s = self._snap(int(c.get("snap", 0)))
            if s is None:
                self._result(cid, op, False, "that picture is too old - press Resume and try again", WARN)
            else:
                self._pinned[int(c["snap"])] = s
            return
        if op == "unpin":
            self._pinned.clear()
            self._cleanup_files()
            return
        if not self.learning_allowed:
            self._result(cid, op, False, "learning is off (AUTO PLAY or learning disabled) - nothing was saved", WARN)
            return
        if op == "undo":
            self._result(cid, op, *self._do_undo())
            return
        s = self._snap(int(c.get("snap", 0)))
        if s is None:
            self._result(cid, op, False, "that picture is too old - press Resume and try again", WARN)
            return
        frame, ghosts, _name = s
        if op == "all":
            self._result(cid, op, *self._do_all(frame, [(g["x"], g["y"], g["w"], g["h"]) for g in ghosts]))
            return
        if op != "label":
            return
        H, W = frame.shape[:2]
        try:
            x, y, w, h = (int(round(float(v))) for v in c["box"])
        except Exception:
            self._result(cid, op, False, "bad box", BAD)
            return
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(W, x + w), min(H, y + h)
        if x1 - x0 < 6 or y1 - y0 < 6:
            self._result(cid, op, False, "that box is too small", WARN)
            return
        verdict = str(c.get("verdict", ""))
        kind, colour = str(c.get("kind", "")), str(c.get("colour", ""))
        if verdict == "colour" and colour not in (SMALL_COLOURS if kind == "small" else BOSS_COLOURS if kind == "boss" else ()):
            self._result(cid, op, False, f"unknown colour {kind} {colour}", BAD)
            return
        name = {"ghost": "confirm", "not_ghost": "reject", "colour": "color"}.get(verdict)
        if name is None:
            self._result(cid, op, False, "unknown action", BAD)
            return
        entry, text, col, ok = self._teach_box(name, frame, (x0, y0, x1 - x0, y1 - y0), kind, colour, str(c.get("det", "")))
        if entry:
            self._undo.append(entry)
        self._result(cid, op, ok, text, col)

    # ------------------------------------------------------------------ shared teaching actions
    def _teach_box(self, name: str, frame, box: tuple, kind: str = "", colour: str = "", det: str = ""):
        """Apply one verdict to one box of `frame`. Returns (undo entry, message, colour, ok)."""
        entry: list = []
        tail = f" ({det})" if det else ""
        if name == "confirm":
            p = self.smart.overlay_feedback(frame, box, True)
            if p is None:
                return entry, "nothing saved (crop too small or the sample was refused)", WARN, False
            entry.append(("sample", p))
            return entry, f"+ saved: it IS a ghost{tail}", OK, True
        if name == "reject":
            p = self.smart.overlay_feedback(frame, box, False)
            if p is None:
                return entry, "nothing saved (crop too small or the sample was refused)", WARN, False
            entry.append(("sample", p))
            return entry, "x saved: NOT a ghost", BAD, True
        g = types.SimpleNamespace(x=box[0], y=box[1], w=box[2], h=box[3], kind=kind, color=colour)
        lp = self.scene.teach_color(frame, g, kind, colour)
        if lp is None:
            return entry, "could not save that label", BAD, False
        entry.append(("label", lp))
        sp = self.smart.overlay_feedback(frame, box, True)          # labelling a colour = it is a ghost
        if sp is not None:
            entry.append(("sample", sp))
        return entry, f"+ labelled {kind} {colour}", OK, True

    def _do_all(self, frame, boxes: list):
        boxes = list(boxes)[:12]
        if not boxes:
            return False, "no ghost boxes on screen", WARN
        entry = []
        for b in boxes:
            p = self.smart.overlay_feedback(frame, tuple(int(v) for v in b), True, weight_scale=0.7)
            if p is not None:
                entry.append(("sample", p))
        if not entry:
            return False, "nothing saved", WARN
        self._undo.append(entry)
        return True, f"+ saved {len(entry)} boxes as ghosts", OK

    def _do_undo(self):
        if not self._undo:
            return False, "nothing to undo", WARN
        n = 0
        for kind, path in self._undo.pop():
            if kind == "sample":
                n += int(self.smart.overlay_undo(path))
            else:
                n += int(self.scene.colors.remove_label(path))
        return True, f"undone ({n} item{'s' if n != 1 else ''})", INFO

    # ------------------------------------------------------------------ F4 teach mode
    def _toast(self, text: str, colour: str, now: Optional[float] = None) -> None:
        self._toasts.append((now if now is not None else time.time(), text, colour))
        log.info("TEACH: %s", text)

    def _set_active(self, on: bool, why: Optional[str]) -> None:
        if on == self.active:
            return
        if on:
            if not self.has_overlay:
                self._toast("F4 teach mode needs the on-screen overlay - use the Teach window instead", WARN)
                return
            if not self.learning_allowed:
                self._toast("teaching is off in AUTO PLAY (it learns nothing)", WARN)
                return
            if self._kb is None:
                self._toast("teach mode needs the 'keyboard' package (pip install keyboard)", WARN)
                return
            if not self._register_keys():
                self._toast("teach mode: could not capture keys", BAD)
                return
            self.active = True
            self._last_key = time.time()
            self._toast("TEACH MODE ON - hover a ghost, then press a key", INFO)
        else:
            self._unregister_keys()
            self.active = False
            if why:
                self._toast(why, INFO)

    def _register_keys(self) -> bool:
        kb = self._kb
        self._handles = []
        try:
            def bind(key: str, name: str, arg=None):
                h = kb.add_hotkey(key, lambda n=name, a=arg: self._post(n, a), suppress=True)
                self._handles.append((key, h))
            bind("space", "confirm")
            bind("x", "reject")
            bind("a", "all")
            bind("backspace", "undo")
            for key, kc in COLOR_KEYS.items():
                bind(key, "color", kc)
            return True
        except Exception as exc:
            log.warning("teach mode: key capture failed (%s)", exc)
            self._unregister_keys()
            return False

    def _unregister_keys(self) -> None:
        for key, h in self._handles:
            try:
                if callable(h):
                    h()
                else:
                    self._kb.remove_hotkey(key)
            except Exception:
                try:
                    self._kb.remove_hotkey(key)
                except Exception:
                    pass
        self._handles = []

    def _frame_xy(self, cur, rect) -> Optional[Tuple[int, int]]:
        if cur is None or rect is None:
            return None
        return int(cur[0] - rect["left"]), int(cur[1] - rect["top"])

    def _handle(self, name: str, arg, cur, frame, rect, now: float) -> None:
        if name == "toggle":
            self._set_active(not self.active, "teach mode off")
            return
        if not self.active:
            return
        self._last_key = now
        if not self.learning_allowed:
            return
        if name == "undo":
            _ok, text, col = self._do_undo()
            self._toast(text, col, now)
            return
        if name == "all":
            _ok, text, col = self._do_all(frame, [(g.x, g.y, g.w, g.h) for g in self.scene.scene.ghosts])
            self._toast(text, col, now)
            return
        xy = self._frame_xy(cur, rect)
        g = self.scene.ghost_at(*xy) if xy is not None else None
        if g is None:
            self._toast("no ghost box under the mouse", WARN, now)
            return
        kind, colour = arg if name == "color" else ("", "")
        entry, text, col, _ok = self._teach_box(name, frame, (g.x, g.y, g.w, g.h), kind, colour, f"{g.kind} {g.color}")
        if entry:
            self._undo.append(entry)
        self._toast(text, col, now)

    # ------------------------------------------------------------------ what the overlay draws
    def _decorate(self, rect: Optional[dict], now: float, items: dict) -> None:
        notes = list(items.get("notes", []))
        head: List[tuple] = []
        if self.active:
            head.append(("TEACH MODE   [F4] exit   [BACKSPACE] undo", INFO))
            head.append(("SPACE = is a ghost   X = NOT a ghost   A = all shown", "#ffffff"))
            head.append(("small: 1 blue  2 purple  3 yellow  4 rainbow", "#ffffff"))
            head.append(("boss: Q blue W cyan E green R lt-green T red Y white U rainbow", "#ffffff"))
            xy = self._frame_xy(self._cursor(), rect)
            g = self.scene.ghost_at(*xy) if xy is not None else None
            if g is not None:
                items.setdefault("boxes", []).append((g.x - 5, g.y - 5, g.w + 10, g.h + 10, "", HOVER, 2))
                head.append((f"> {g.kind} {g.color} ({g.conf * 100:.0f}%)", HOVER))
            else:
                head.append(("> hover a ghost box", "#8fa0bb"))
        toasts = [(txt, col) for t, txt, col in reversed(self._toasts) if now - t <= 4.0]
        items["notes"] = head + toasts + notes
