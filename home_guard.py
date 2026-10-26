"""Keep the player's character on its starting spot (click-to-move games).

How it works
------------
* Set-up: press F6 (hk_home) to save pictures of your character: the bot freezes the screen in a
  small window; DRAG A BOX AROUND YOUR CHARACTER FROM THE TOP OF THE HEAD TO THE FEET (as tight
  as you can), then press ENTER.  Do it several times in different poses - only the first picture
  sets home if none is set yet; later ones just teach more poses.  Press F5 (hk_home_rearm) to
  toggle the whole home system ON/OFF (character search + return-to-home).  While the bot runs
  it also learns new poses by itself (up to home_max_samples, default 120).  Delete the home/
  folder to start over.
* Every start (Live / Auto play / Preview): the bot looks for the saved pictures, finds the avatar
  and stores the position of its feet as "home" if home is not already set (only while F5 has
  home enabled).
* While running: when nothing else is being clicked and the avatar has stopped walking, or when it
  has been away from home for more than home_force_after_s seconds, and it is farther than
  home_tolerance_px from home, the bot clicks the home spot (the feet).  It never clicks while YOU
  are clicking (Live mode).
* Performance: matching prefers GPU (CUDA, then OpenCL) and runs on a background thread so the
  main ghost-detection loop is not blocked.  Default check interval is 10 seconds.

Camera
------
home_camera_follow = False : the game view does not scroll (small room).  Home is a screen point.
home_camera_follow = True  : the view scrolls with the avatar.  The scene shift against a reference
                             picture of the background is measured (phase correlation) and the click
                             is moved by that shift, so "home" stays a spot in the ROOM.

This module has no game dependency: main.py gives it frames and does the actual clicking.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger("bloop.home")

MIN_TEMPLATE_STD = 6.0  # a flat picture (nothing recognisable) cannot be matched
SHIFT_DEADBAND = 2.0    # scene shifts smaller than this many pixels are treated as 0
FORMAT = 2              # pictures made by the first version (fixed-size box around the mouse) are ignored


def _gray(img: np.ndarray) -> np.ndarray:
    return img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _detect_accel_backend() -> str:
    """Pick the best available accelerator for matchTemplate: cuda > opencl > cpu."""
    # CUDA (opencv built with CUDA + a real device)
    try:
        if hasattr(cv2, "cuda") and int(cv2.cuda.getCudaEnabledDeviceCount()) > 0:
            # TM_CCOEFF_NORMED is supported on recent OpenCV CUDA builds
            return "cuda"
    except Exception:
        pass
    # OpenCL (Intel / AMD / NVIDIA via drivers; works with stock opencv-python on many PCs)
    try:
        if hasattr(cv2, "ocl") and cv2.ocl.haveOpenCL():
            cv2.ocl.setUseOpenCL(True)
            if cv2.ocl.useOpenCL():
                return "opencl"
    except Exception:
        pass
    return "cpu"


class HomeGuard:
    def __init__(self, root: Path, cfg):
        self.cfg = cfg
        self.dir = Path(root) / "home"
        self.index = self.dir / "samples.json"
        self.samples: list = []     # {"file","img"(gray),"fdx","fdy","manual"}: feet position inside each picture
        self._tcache: dict = {}
        self._hint: Optional[Tuple[float, float]] = None  # last place the avatar was found (speeds up searching)
        self._last_scale: Optional[float] = None
        self._last_entry = None
        self._last_auto = 0.0
        self.home: Optional[Tuple[float, float]] = None  # reference-frame coordinates of the feet
        self._ref_bg: Optional[np.ndarray] = None
        self._ref_hann = None
        self._force_arm = False
        self._last_check = 0.0
        self._last_click = 0.0
        self._last_pos: Optional[Tuple[float, float]] = None
        self._away_since: Optional[float] = None
        self._attempts = 0
        self._backoff_until = 0.0
        self._miss = 0
        self._warned_no_template = False
        self._last_lost_log = 0.0
        self.shift = (0.0, 0.0)                           # latest scene shift (frame px)
        self.last_pos: Optional[Tuple[float, float]] = None
        self.last_score = 0.0
        self._seen: Optional[tuple] = None                # (x0, y0, w, h, score, time) of the last recognition
        # F5 toggles this: when False, no character search and no return-home clicks.
        self.enabled = bool(getattr(cfg, "home_enabled", True))

        # GPU / OpenCL backend for template matching (CPU fallback)
        self._backend = _detect_accel_backend()
        self._cuda_failed = False
        self._ocl_failed = False
        log.info("HOME: template matching backend = %s", self._backend)

        # Background worker: home matching never blocks the ghost-detection tick
        self._lock = threading.Lock()
        self._job: Optional[dict] = None          # {"frame", "now", "busy", "hard_busy"}
        self._result_click: Optional[Tuple[int, int]] = None
        self._worker_stop = threading.Event()
        self._worker = threading.Thread(target=self._worker_loop, name="home-guard", daemon=True)
        self._worker.start()

        self.load()

    def close(self) -> None:
        """Stop the background worker (optional; daemon exits with the process)."""
        self._worker_stop.set()
        try:
            self._worker.join(timeout=1.0)
        except Exception:
            pass

    # ------------------------------------------------------------------ files
    @staticmethod
    def _read(path: Path):
        img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
        return None if img is None else _gray(img)

    def load(self) -> bool:
        self.samples = []
        self._tcache.clear()
        ignored = 0
        try:
            if self.index.is_file():
                data = json.loads(self.index.read_text(encoding="utf-8"))
                for e in data.get("samples", []):
                    if int(e.get("format", 1)) < FORMAT:
                        ignored += 1
                        continue
                    img = self._read(self.dir / e["file"])
                    if img is not None:
                        self.samples.append({"file": e["file"], "img": img, "fdx": float(e["feet_dx"]),
                                             "fdy": float(e["feet_dy"]), "manual": bool(e.get("manual", True))})
        except Exception as exc:
            log.warning("HOME: could not load the saved avatar pictures (%s)", exc)
        if ignored:
            log.warning("HOME: %d old avatar picture(s) ignored (they were cut with a fixed-size box and are mostly "
                        "background). Press %s and draw a box around your character instead.",
                        ignored, str(getattr(self.cfg, "hk_home", "f6")).upper())
        if self.samples:
            log.info("HOME: %d avatar picture(s) loaded", len(self.samples))
        return bool(self.samples)

    def has_template(self) -> bool:
        return bool(self.samples)

    def _save_index(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        old = []
        try:                                                           # keep entries of other formats untouched
            if self.index.is_file():
                old = [e for e in json.loads(self.index.read_text(encoding="utf-8")).get("samples", [])
                       if int(e.get("format", 1)) < FORMAT]
        except Exception:
            pass
        self.index.write_text(json.dumps({"samples": old + [
            {"file": e["file"], "feet_dx": e["fdx"], "feet_dy": e["fdy"], "manual": e["manual"], "format": FORMAT}
            for e in self.samples]}), encoding="utf-8")

    def _store(self, crop: np.ndarray, fdx: float, fdy: float, manual: bool) -> bool:
        """Keep one avatar picture (crop) whose feet are at (fdx, fdy) inside it."""
        g = _gray(crop)
        if g.shape[0] < 14 or g.shape[1] < 12 or float(g.std()) < MIN_TEMPLATE_STD:
            return False
        limit = int(getattr(self.cfg, "home_max_samples", 120))
        while len(self.samples) >= limit:                              # make room: drop the oldest automatic one
            old = next((e for e in self.samples if not e["manual"]), None)
            if old is None:
                if not manual:
                    return False
                old = self.samples[0]
            self.samples.remove(old)
            try:
                (self.dir / old["file"]).unlink()
            except Exception:
                pass
        self.dir.mkdir(parents=True, exist_ok=True)
        name = f"avatar_{int(time.time() * 1000)}.png"
        ok, buf = cv2.imencode(".png", crop)
        if not ok:
            return False
        buf.tofile(str(self.dir / name))
        self.samples.append({"file": name, "img": g, "fdx": float(fdx), "fdy": float(fdy), "manual": manual})
        self._tcache.clear()
        self._save_index()
        return True

    # ------------------------------------------------------------------ set-up
    def pick_box(self, frame: np.ndarray) -> Optional[Tuple[float, float, float, float]]:
        """Freeze the frame in a window and let the user drag a box around the character.
        Returns (x, y, w, h) in frame pixels, None when cancelled. Raises RuntimeError without a GUI."""
        h, w = frame.shape[:2]
        sc = min(1.0, 1500.0 / w, 850.0 / h)
        img = cv2.resize(frame, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA) if sc < 1.0 else frame.copy()
        name = "BLOOP: drag a box around your character (head to feet), then ENTER - ESC cancels"
        try:
            cv2.namedWindow(name, cv2.WINDOW_AUTOSIZE)
            try:
                cv2.setWindowProperty(name, cv2.WND_PROP_TOPMOST, 1)
            except Exception:
                pass
            x, y, bw, bh = cv2.selectROI(name, img, False, False)
        except Exception as exc:
            raise RuntimeError(f"no picture window available ({exc})")
        finally:
            try:
                cv2.destroyWindow(name)
                cv2.waitKey(1)
            except Exception:
                pass
        if bw < 8 or bh < 14:
            return None
        return x / sc, y / sc, bw / sc, bh / sc

    def capture_box(self, frame: np.ndarray, box) -> bool:
        """Save the picture inside box=(x, y, w, h). The FIRST picture also sets home at the
        bottom-centre of the box; later pictures never move home (press F5 for that — mouse position)."""
        h, w = frame.shape[:2]
        x0 = int(max(0, round(box[0]))); y0 = int(max(0, round(box[1])))
        x1 = int(min(w, round(box[0] + box[2]))); y1 = int(min(h, round(box[1] + box[3])))
        crop = frame[y0:y1, x0:x1]
        fdx, fdy = (x1 - x0) / 2.0, float(y1 - y0)
        if not self._store(crop, fdx, fdy, manual=True):
            log.warning("HOME: that box is too small or too plain to recognise - draw it tighter around the character.")
            return False
        hk_box = str(getattr(self.cfg, "hk_home", "f6")).upper()
        hk_set = str(getattr(self.cfg, "hk_home_rearm", "f5")).upper()
        if self.home is None:
            self._set_home(frame, (x0 + fdx, y0 + fdy))
            log.info("HOME: picture #%d saved (%dx%d px), home set at (%d,%d). Press %s in other poses to teach "
                     "it more; press %s (hover where you want home) to move home.",
                     len(self.samples), x1 - x0, y1 - y0, x0 + fdx, y0 + fdy, hk_box, hk_set)
        else:
            log.info("HOME: picture #%d saved (%dx%d px). Home stays where it was - hover the spot and "
                     "press %s to move it.", len(self.samples), x1 - x0, y1 - y0, hk_set)
        return True

    def capture_from_point(self, frame: np.ndarray, fx: float, fy: float) -> bool:
        """Fallback without a picture window: a box of home_template_w x home_template_h ending at the mouse."""
        tw = float(getattr(self.cfg, "home_template_w", 60))
        th = float(getattr(self.cfg, "home_template_h", 90))
        return self.capture_box(frame, (fx - tw / 2, fy - th, tw, th))

    def toggle_enabled(self) -> bool:
        """F5: turn the whole home system (search + return-home) on or off. Returns the new state."""
        self.enabled = not self.enabled
        with self._lock:
            self._job = None
            self._result_click = None
        if self.enabled:
            self._last_check = 0.0          # run a check soon after enabling
            self._attempts = 0
            self._backoff_until = 0.0
            self._away_since = None
            if self.home is None:
                self._force_arm = True      # next locate sets home where the character is
            log.info("HOME: ON — character search + return-to-home active")
        else:
            self._force_arm = False
            self._seen = None
            log.info("HOME: OFF — character search and return-to-home paused (press %s to turn back on)",
                     str(getattr(self.cfg, "hk_home_rearm", "f5")).upper())
        return self.enabled

    def request_rearm(self, frame: Optional[np.ndarray] = None,
                      pos: Optional[Tuple[float, float]] = None) -> None:
        """Optional: set home to a frame point, or queue arm-at-avatar if no point given."""
        if not self.samples:
            log.warning("HOME: cannot set home yet - no picture of your character. Press %s and drag a box "
                        "around it first.", str(getattr(self.cfg, "hk_home", "f6")).upper())
            return
        if pos is not None and frame is not None:
            self._set_home(frame, (float(pos[0]), float(pos[1])))
            log.info("HOME: set at (%d,%d)", int(pos[0]), int(pos[1]))
            return
        self.home = None
        self._force_arm = True
        self._attempts = 0
        self._backoff_until = 0.0
        self._away_since = None
        log.info("HOME: home will be re-set to where your character is standing right now")

    def _set_home(self, frame: np.ndarray, pos: Tuple[float, float]) -> None:
        self.home = (float(pos[0]), float(pos[1]))
        self._attempts = 0
        self._backoff_until = 0.0
        self._away_since = None
        self._last_pos = None
        self.shift = (0.0, 0.0)
        self._ref_bg = None
        self._hint = (float(pos[0]), float(pos[1]))
        if getattr(self.cfg, "home_camera_follow", False):
            bg = self._bg(frame, pos)
            self._ref_bg = bg
            self._ref_hann = cv2.createHanningWindow((bg.shape[1], bg.shape[0]), cv2.CV_32F)

    # ------------------------------------------------------------------ vision / GPU match
    def _subset(self, limit: int = 4, rotating: int = 2) -> list:
        """Best recent matchers + a few others in turn — kept small for cheap checks."""
        ranked = sorted(self.samples, key=lambda e: e.get("hit", 0.7 if e["manual"] else 0.5), reverse=True)
        chosen = ranked[:limit]
        rest = ranked[limit:]
        if rest and rotating:
            self._rot = (getattr(self, "_rot", 0) + rotating) % len(rest)
            chosen += [rest[(self._rot + i) % len(rest)] for i in range(min(rotating, len(rest)))]
        return chosen

    def _match_template_gpu(self, g: np.ndarray, t: np.ndarray) -> Optional[Tuple[float, Tuple[int, int]]]:
        """Run matchTemplate on GPU when possible. Returns (max_score, (x, y)) or None on failure."""
        # --- CUDA ---
        if self._backend == "cuda" and not self._cuda_failed:
            try:
                g_gpu = cv2.cuda_GpuMat()
                t_gpu = cv2.cuda_GpuMat()
                g_gpu.upload(g)
                t_gpu.upload(t)
                result_gpu = cv2.cuda.matchTemplate(g_gpu, t_gpu, cv2.TM_CCOEFF_NORMED)
                res = result_gpu.download()
                res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
                _, mx, _, loc = cv2.minMaxLoc(res)
                return float(mx), (int(loc[0]), int(loc[1]))
            except Exception as exc:
                self._cuda_failed = True
                log.warning("HOME: CUDA match failed (%s) — falling back to OpenCL/CPU", exc)
                if self._backend == "cuda":
                    # Prefer OpenCL next if present
                    try:
                        if hasattr(cv2, "ocl") and cv2.ocl.haveOpenCL():
                            cv2.ocl.setUseOpenCL(True)
                            self._backend = "opencl"
                        else:
                            self._backend = "cpu"
                    except Exception:
                        self._backend = "cpu"

        # --- OpenCL via UMat ---
        if self._backend == "opencl" and not self._ocl_failed:
            try:
                g_u = cv2.UMat(g)
                t_u = cv2.UMat(t)
                res_u = cv2.matchTemplate(g_u, t_u, cv2.TM_CCOEFF_NORMED)
                res = res_u.get() if hasattr(res_u, "get") else np.asarray(res_u)
                res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
                _, mx, _, loc = cv2.minMaxLoc(res)
                return float(mx), (int(loc[0]), int(loc[1]))
            except Exception as exc:
                self._ocl_failed = True
                self._backend = "cpu"
                log.warning("HOME: OpenCL match failed (%s) — falling back to CPU", exc)

        # --- CPU ---
        res = cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)
        res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
        _, mx, _, loc = cv2.minMaxLoc(res)
        return float(mx), (int(loc[0]), int(loc[1]))

    def _match(self, g: np.ndarray, ds: float, roi, scales, samples=None):
        """Best match of the saved pictures inside g (optionally only inside roi).
        -> (score, feet_x, feet_y, scale, picture)."""
        ox = oy = 0
        if roi is not None:
            x0, y0, x1, y1 = roi
            g = g[y0:y1, x0:x1]
            ox, oy = x0, y0
        best = None
        for e in (self.samples if samples is None else samples):
            for sc in scales:
                f = float(sc) * ds
                key = (e["file"], round(f, 3))
                t = self._tcache.get(key)
                if t is None:
                    t = cv2.resize(e["img"], None, fx=f, fy=f,
                                   interpolation=cv2.INTER_AREA if f < 1.0 else cv2.INTER_LINEAR)
                    self._tcache[key] = t
                if (t.shape[0] < 8 or t.shape[1] < 8 or t.shape[0] >= g.shape[0]
                        or t.shape[1] >= g.shape[1] or float(t.std()) < 2.0):
                    continue
                hit = self._match_template_gpu(g, t)
                if hit is None:
                    continue
                mx, loc = hit
                if best is None or mx > best[0]:
                    best = (float(mx), (ox + loc[0]) / ds + e["fdx"] * sc, (oy + loc[1]) / ds + e["fdy"] * sc,
                            float(sc), e)
        return best

    def locate(self, frame: np.ndarray, cheap: bool = False) -> Optional[Tuple[float, float, float]]:
        """Find the avatar with the saved pictures. Returns (feet_x, feet_y, score) in frame pixels, or None.

        cheap=True (while ghosts are being clicked): ROI-only, fewer templates, one scale.
        """
        if not self.samples:
            return None
        g = _gray(frame)
        h, w = g.shape[:2]
        max_dim = 480.0 if cheap else 640.0
        ds = min(1.0, max_dim / max(h, w))
        if ds < 1.0:
            g = cv2.resize(g, None, fx=ds, fy=ds, interpolation=cv2.INTER_AREA)
        thr = float(getattr(self.cfg, "home_match_threshold", 0.55))
        all_scales = tuple(getattr(self.cfg, "home_scales", (0.85, 1.0, 1.15)))
        last_sc = self._last_scale or 1.0
        attempts = []
        if self._hint is not None:
            hx, hy = self._hint
            r = (180 if cheap else 260) * ds
            roi = (int(max(0, hx * ds - r)), int(max(0, hy * ds - 1.6 * r)),
                   int(min(g.shape[1], hx * ds + r)), int(min(g.shape[0], hy * ds + r)))
            attempts.append((roi, (last_sc,), self._subset(3, 1 if not cheap else 0)))
        if not cheap:
            attempts.append((None, all_scales, self._subset(4, 2)))
            if len(self.samples) > 6:
                attempts.append((None, (last_sc,), self._subset(12, 0)))
        best = None
        for roi, scales, subset in attempts:
            cand = self._match(g, ds, roi, scales, subset)
            if cand is not None and (best is None or cand[0] > best[0]):
                best = cand
            if best is not None:
                self.last_score = best[0]
                if best[0] >= max(thr, 0.72 if cheap else 0.78):
                    break
        if best is None or best[0] < thr:
            return None
        score, fx, fy, sc, entry = best
        entry["hit"] = 0.7 * entry.get("hit", 0.5) + 0.3 * score
        self._hint = (fx, fy)
        self._last_scale = sc
        self._last_entry = entry
        th_, tw_ = entry["img"].shape[:2]
        self._seen = (fx - entry["fdx"] * sc, fy - entry["fdy"] * sc, tw_ * sc, th_ * sc, score, time.time())
        return fx, fy, score

    def _maybe_learn(self, frame: np.ndarray, fx: float, fy: float, score: float, now: float) -> None:
        """Keep a new picture when the avatar is recognised but in a pose we do not have yet."""
        e = self._last_entry
        if e is None or not getattr(self.cfg, "home_auto_learn", True):
            return
        if now - self._last_auto < float(getattr(self.cfg, "home_auto_interval_s", 4.0)):
            return
        if not (float(getattr(self.cfg, "home_auto_min_score", 0.75)) <= score < 0.96):
            return
        sc = self._last_scale or 1.0
        th, tw = e["img"].shape[:2]
        x0 = int(round(fx - e["fdx"] * sc)); y0 = int(round(fy - e["fdy"] * sc))
        x1 = x0 + int(round(tw * sc)); y1 = y0 + int(round(th * sc))
        fh, fw = frame.shape[:2]
        if x0 < 0 or y0 < 0 or x1 > fw or y1 > fh:
            return
        crop = frame[y0:y1, x0:x1]
        if abs(sc - 1.0) > 0.02:
            crop = cv2.resize(crop, (tw, th), interpolation=cv2.INTER_AREA if sc > 1.0 else cv2.INTER_LINEAR)
        if self._store(crop, e["fdx"], e["fdy"], manual=False):
            self._last_auto = now
            log.info("HOME: learned a new pose automatically (%d pictures, match was %.2f)", len(self.samples), score)

    def _bg(self, frame: np.ndarray, avatar: Optional[Tuple[float, float]]) -> np.ndarray:
        """Small float gray picture of the background with the avatar painted over."""
        g = _gray(frame)
        h, w = g.shape[:2]
        ds = min(1.0, 480.0 / max(h, w))
        small = cv2.resize(g, None, fx=ds, fy=ds, interpolation=cv2.INTER_AREA) if ds < 1.0 else g.copy()
        if avatar is not None and self.samples:
            e = self.samples[0]
            th, tw = e["img"].shape[:2]
            x0 = int((avatar[0] - e["fdx"]) * ds) - 4
            y0 = int((avatar[1] - e["fdy"]) * ds) - 4
            x1 = x0 + int(tw * ds) + 8
            y1 = y0 + int(th * ds) + 8
            small[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = int(small.mean())
        return small.astype(np.float32)

    def scene_shift(self, frame: np.ndarray, avatar: Optional[Tuple[float, float]]
                    ) -> Optional[Tuple[float, float]]:
        """How far the background moved on screen since home was set (frame px), None if unsure."""
        if self._ref_bg is None:
            return (0.0, 0.0)
        cur = self._bg(frame, avatar)
        if cur.shape != self._ref_bg.shape:
            return None
        (dx, dy), response = cv2.phaseCorrelate(self._ref_bg, cur, self._ref_hann)
        if response < float(getattr(self.cfg, "home_shift_min_response", 0.12)):
            return None
        h, w = frame.shape[:2]
        ds = cur.shape[1] / float(w)
        dx, dy = dx / ds, dy / ds
        if math.hypot(dx, dy) < SHIFT_DEADBAND:
            return (0.0, 0.0)
        return (float(dx), float(dy))

    # ------------------------------------------------------------------ background worker
    def _worker_loop(self) -> None:
        while not self._worker_stop.is_set():
            job = None
            with self._lock:
                if self._job is not None:
                    job = self._job
                    self._job = None
            if job is None:
                time.sleep(0.02)
                continue
            try:
                click = self._decide_sync(job["frame"], job["now"], job["busy"], job["hard_busy"])
                if click is not None:
                    with self._lock:
                        self._result_click = click
            except Exception as exc:
                log.warning("HOME worker error: %s", exc)

    # ------------------------------------------------------------------ decision
    def decide(self, frame: np.ndarray, now: float, busy: bool, hard_busy: bool = False) -> Optional[Tuple[int, int]]:
        """Non-blocking: queue a home check on the worker thread; return a pending click if ready.

        busy      = the bot is acting (a ghost click a moment ago, a wave, ...): only a long absence forces a return.
        hard_busy = the human is clicking (Live mode): never click.
        """
        if not self.enabled:
            return None

        # Hand out a completed click from the worker (if any)
        with self._lock:
            pending = self._result_click
            self._result_click = None
        if pending is not None:
            return pending

        if not self.samples:
            if not self._warned_no_template:
                self._warned_no_template = True
                log.warning("HOME: no avatar picture yet. Press %s and drag a box around your character "
                            "(head to feet); do it a few times in different poses. After that every start finds "
                            "the character by itself.", str(getattr(self.cfg, "hk_home", "f6")).upper())
            return None
        if hard_busy and not self._force_arm:
            self._last_pos = None
            return None

        interval = float(getattr(self.cfg, "home_check_interval_s", 10.0))
        if busy and not self._force_arm:
            interval = max(interval, float(getattr(self.cfg, "home_busy_interval_s", 10.0)))
        if now - self._last_check < interval:
            return None
        # Do not queue another job while one is already waiting / running
        with self._lock:
            if self._job is not None:
                return None
            self._last_check = now
            # Copy so the main thread can keep using its frame
            self._job = {
                "frame": frame.copy(),
                "now": now,
                "busy": busy,
                "hard_busy": hard_busy,
            }
        return None

    def _decide_sync(self, frame: np.ndarray, now: float, busy: bool, hard_busy: bool = False
                     ) -> Optional[Tuple[int, int]]:
        """Actual home decision (runs on the background worker / GPU thread)."""
        if hard_busy and not self._force_arm:
            self._last_pos = None
            return None

        found = self.locate(frame, cheap=bool(busy and not self._force_arm))
        if found is None:
            self._miss += 1
            self.last_pos = None
            if self._miss in (6, 60) or now - self._last_lost_log > 30.0:
                self._last_lost_log = now
                log.info("HOME: character not found on screen (best match %.2f < %.2f) - skipping the check. "
                         "Lower home_match_threshold, or add pictures with %s, if this keeps happening.",
                         self.last_score, float(getattr(self.cfg, "home_match_threshold", 0.55)),
                         str(getattr(self.cfg, "hk_home", "f6")).upper())
            return None
        self._miss = 0
        fx, fy, score = found
        self.last_pos = (fx, fy)
        if not busy:
            self._maybe_learn(frame, fx, fy, score, now)

        if self.home is None:                                 # arm at the avatar's current spot
            self._force_arm = False
            self._set_home(frame, (fx, fy))
            log.info("HOME: set at (%d,%d) (match %.2f)", fx, fy, score)
            return None

        follow = bool(getattr(self.cfg, "home_camera_follow", False))
        sx = sy = 0.0
        if follow:
            sh = self.scene_shift(frame, (fx, fy))
            if sh is None:
                return None
            sx, sy = sh
        self.shift = (sx, sy)

        drift = math.hypot((fx - sx) - self.home[0], (fy - sy) - self.home[1])
        if drift <= float(getattr(self.cfg, "home_tolerance_px", 36)):
            self._attempts = 0
            self._away_since = None
            self._last_pos = (fx, fy)
            return None
        if self._away_since is None:
            self._away_since = now
        forced = busy and (now - self._away_since) >= float(getattr(self.cfg, "home_force_after_s", 6.0))
        if busy and not forced:
            self._last_pos = (fx, fy)
            return None
        if not forced:
            if self._last_pos is None:
                self._last_pos = (fx, fy)
                return None
            moved = math.hypot(fx - self._last_pos[0], fy - self._last_pos[1])
            self._last_pos = (fx, fy)
            if moved > float(getattr(self.cfg, "home_stable_px", 4)):
                return None
        if now < self._backoff_until:
            return None
        if now - self._last_click < float(getattr(self.cfg, "home_retry_s", 2.5)):
            return None
        if self._attempts >= int(getattr(self.cfg, "home_max_attempts", 4)):
            self._attempts = 0
            self._backoff_until = now + 15.0
            log.warning("HOME: still %d px from home after %d clicks - pausing return-home for 15 s "
                        "(blocked path? wrong spot?).", drift, int(getattr(self.cfg, "home_max_attempts", 4)))
            return None

        h, w = frame.shape[:2]
        tx = int(round(self.home[0] + sx))
        ty = int(round(self.home[1] + sy))
        if not (8 <= tx < w - 8 and 8 <= ty < h - 8):
            if now - self._last_lost_log > 10.0:
                self._last_lost_log = now
                log.info("HOME: the home spot is off-screen right now (%d,%d); not clicking.", tx, ty)
            return None
        self._attempts += 1
        self._last_click = now
        log.info("HOME: character is %d px from home - clicking the home spot (%d,%d) [attempt %d]%s",
                 drift, tx, ty, self._attempts, " (away for a while)" if forced else "")
        return tx, ty

    # ------------------------------------------------------------------ overlay
    def overlay_boxes(self, now: Optional[float] = None) -> list:
        """Boxes for the on-screen overlay: the home spot and where the bot currently sees your character."""
        if not self.enabled:
            return []
        now = time.time() if now is None else now
        out: List[tuple] = []
        if self.home is not None:
            hx = int(self.home[0] + self.shift[0])
            hy = int(self.home[1] + self.shift[1])
            out.append((hx - 20, hy - 10, 40, 20, "HOME", "#00e5ff", 2))
        if self._seen is not None and now - self._seen[5] < 3.0:
            x, y, w, h, score = self._seen[:5]
            out.append((int(x), int(y), int(w), int(h), f"YOU {score:.2f}", "#ffd400", 2))
        return out

    def overlay_notes(self) -> list:
        if not self.enabled:
            return [("HOME: OFF (press %s to enable search + return-home)"
                     % str(getattr(self.cfg, "hk_home_rearm", "f5")).upper(), "#888888")]
        if not self.samples:
            return [("HOME: no picture of your character yet - press %s and drag a box around it"
                     % str(getattr(self.cfg, "hk_home", "f6")).upper(), "#ffd400")]
        if self.home is None:
            return [("HOME: looking for your character...", "#ffd400")]
        return []
