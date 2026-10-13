"""On-screen labels drawn over the Highrise window.

A borderless, click-through, always-on-top window that exactly covers the game and
draws the ghost boxes, their labels and the BIG WAVE / BOSS banner.

Two things keep it from disturbing the bot:
  * it is click-through (WS_EX_TRANSPARENT): mouse clicks go to the game;
  * it is excluded from screen capture (SetWindowDisplayAffinity, Windows 10 2004+),
    so the bot's own screenshots never contain the labels. main.py proves this at
    start-up with a test patch and turns the overlay off if the patch is visible.

The window is hidden whenever there is nothing fresh to show.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("bloop.overlay")

KEY = "#010101"                 # colour-key: drawn as "see-through"
OVERLAY_HWNDS: set = set()      # main.py ignores these when asking "which window is at this point?"


class GhostOverlay:
    def __init__(self, stale_s: float = 0.8):
        self.stale_s = float(stale_s)
        self._lock = threading.Lock()
        self._state: Optional[tuple] = None        # (seq, rect, items, time)
        self._seq = 0
        self._test: Optional[dict] = None
        self._stop = False
        self._ready = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.ok = False
        self.capture_excluded = False

    # ------------------------------------------------------------ api (bot thread)
    def start(self) -> bool:
        if sys.platform != "win32":
            return False
        self._thread = threading.Thread(target=self._run, name="ghost-overlay", daemon=True)
        self._thread.start()
        self._ready.wait(4.0)
        return self.ok

    def push(self, rect: dict, items: dict) -> None:
        with self._lock:
            self._seq += 1
            self._state = (self._seq, dict(rect), items, time.time())

    def show_test(self, rect: Optional[dict]) -> None:
        """Show (rect) or hide (None) a solid magenta patch used to verify capture exclusion."""
        self._test = dict(rect) if rect else None

    def stop(self) -> None:
        self._stop = True

    # ------------------------------------------------------------ overlay thread
    def _run(self) -> None:
        try:
            import tkinter as tk
        except Exception as exc:
            log.warning("overlay off: tkinter unavailable (%s)", exc)
            self._ready.set()
            return
        try:
            u = ctypes.WinDLL("user32", use_last_error=True)      # private copy: leaves main.py's prototypes alone
            u.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            u.GetAncestor.restype = ctypes.c_void_p
            u.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            u.SetWindowDisplayAffinity.restype = ctypes.c_int
            u.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
            u.GetWindowLongW.restype = ctypes.c_long
            u.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]

            root = tk.Tk()
            root.overrideredirect(True)
            root.configure(bg=KEY)
            root.attributes("-topmost", True)
            root.attributes("-transparentcolor", KEY)
            root.geometry("80x40+0+0")
            canvas = tk.Canvas(root, bg=KEY, highlightthickness=0, bd=0)
            canvas.pack(fill="both", expand=True)
            root.update()
            wid = root.winfo_id()
            hwnd = u.GetAncestor(wid, 2) or wid                      # GA_ROOT
            ex = u.GetWindowLongW(hwnd, -20)
            # layered + click-through + no taskbar button + never takes focus
            u.SetWindowLongW(hwnd, -20, ex | 0x00080000 | 0x00000020 | 0x00000080 | 0x08000000)
            self.capture_excluded = bool(u.SetWindowDisplayAffinity(hwnd, 0x11))   # WDA_EXCLUDEFROMCAPTURE
            OVERLAY_HWNDS.add(int(hwnd))
            root.withdraw()
            self.ok = True
        except Exception as exc:
            log.warning("overlay off: could not create the window (%s)", exc)
            self._ready.set()
            return
        self._ready.set()

        shown = False
        last_seq = -1
        geom: Optional[tuple] = None

        def outlined(x, y, text, color, anchor, size=11, bold=True):
            font = ("Segoe UI", size, "bold" if bold else "normal")
            for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                canvas.create_text(x + dx, y + dy, text=text, fill="#000000", anchor=anchor, font=font)
            canvas.create_text(x, y, text=text, fill=color, anchor=anchor, font=font)

        def place(rect: dict) -> None:
            nonlocal geom, shown
            g = (int(rect["left"]), int(rect["top"]), int(rect["width"]), int(rect["height"]))
            if g != geom:
                root.geometry(f"{g[2]}x{g[3]}+{g[0]}+{g[1]}")
                geom = g
            if not shown:
                root.deiconify()
                root.attributes("-topmost", True)
                shown = True

        def hide() -> None:
            nonlocal shown, last_seq
            if shown:
                canvas.delete("all")
                root.withdraw()
                shown = False
                last_seq = -1

        def pump() -> None:
            nonlocal last_seq
            if self._stop:
                try:
                    OVERLAY_HWNDS.discard(int(hwnd))
                    root.destroy()
                except Exception:
                    pass
                return
            try:
                test = self._test
                with self._lock:
                    st = self._state
                if test is not None:
                    place(test)
                    if last_seq != -2:
                        canvas.delete("all")
                        canvas.create_rectangle(2, 2, 62, 62, fill="#ff00ff", outline="#ff00ff")
                        last_seq = -2
                elif st is None or time.time() - st[3] > self.stale_s:
                    hide()
                elif st[0] != last_seq:
                    seq, rect, items, _t = st
                    place(rect)
                    canvas.delete("all")
                    for (x, y, w, h, text, color, thick) in items.get("boxes", []):
                        canvas.create_rectangle(x + 1, y + 1, x + w + 1, y + h + 1, outline="#000000", width=thick + 2)
                        canvas.create_rectangle(x, y, x + w, y + h, outline=color, width=thick)
                        if y > 22:
                            outlined(x + 2, y - 3, text, color, "sw")
                        else:
                            outlined(x + 2, y + h + 3, text, color, "nw")
                    banner = items.get("banner")
                    ytxt = 8
                    if banner:
                        text, color = banner
                        cx = int(rect["width"]) // 2
                        canvas.create_rectangle(cx - 260, 4, cx + 260, 44, fill=color, outline="#000000", width=2)
                        canvas.create_text(cx, 24, text=text, fill="#ffffff", font=("Segoe UI", 16, "bold"))
                        ytxt = 52
                    for text, color in items.get("notes", []):
                        outlined(10, ytxt, text, color, "nw", size=12)
                        ytxt += 22
                    last_seq = seq
            except Exception as exc:
                log.debug("overlay draw error: %s", exc)
            root.after(40, pump)

        root.after(40, pump)
        try:
            root.mainloop()
        except Exception:
            pass
