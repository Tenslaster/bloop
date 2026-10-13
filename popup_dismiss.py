"""Auto-dismiss the "esprits attrapés" (wave complete) banner.

When the banner template is seen on the game frame, execute a sequence of actions
to try and close it. Highrise usually requires a double-click, but if that fails,
we try dragging it around, right-clicking, and clicking different areas.
Pure script logic: the click is sent through `click_fn`, which the bot wires so
the smart learner never records it.

View restore: the drag gestures also pan the game camera. Just before the first
gesture the module remembers what the scene looked like (ORB features, banner area
excluded). Once the banner is gone it measures how far the scene moved and drags
it back (closed loop, the drag->pan gain and its sign are learned on the fly).
"""
from __future__ import annotations

import logging
from typing import Callable, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger("bot.popup")   # main.py only configures the "bot" logger tree

IDLE, ACTIVE, COOLDOWN, RESTORE = "idle", "active", "cooldown", "restore"


class PopupDismisser:
    def __init__(self, template_path, threshold: float = 0.80, settle_s: float = 0.6,
                 step_frac: float = 0.05, max_attempts: int = 12,
                 giveup_cooldown_s: float = 20.0, check_interval_s: float = 0.25,
                 confirm_hits: int = 2,
                 center_high_frac: float = 0.45,
                 restore_view: bool = True,
                 restore_wait_s: float = 1.0,       # let the banner fade / camera settle before measuring
                 restore_settle_s: float = 0.9,     # wait after each corrective drag before measuring again
                 restore_tol_px: float = 6.0,       # vertical error (frame px) considered "back in place"
                 restore_max_iter: int = 6,
                 restore_mirror_fallback: bool = True,  # if the view cannot be measured: undo the drags by mirroring them
                 restore_max_step_frac: float = 0.45,  # biggest single corrective drag (fraction of window height); keeps steps measurable
                 scales=tuple(round(0.7 * 1.04 ** i, 3) for i in range(26))):
        img = cv2.imdecode(np.fromfile(str(template_path), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(f"cannot read popup template: {template_path}")
        self.template = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        self.threshold = float(threshold)
        self.settle_s = float(settle_s)
        self.step_frac = float(step_frac)
        self.max_attempts = int(max_attempts)
        self.giveup_cooldown_s = float(giveup_cooldown_s)
        self.check_interval_s = float(check_interval_s)
        self.confirm_hits = int(confirm_hits)
        self.center_high_frac = float(center_high_frac)   # NEW: y-fraction for "just above center"
        self.scales = tuple(sorted(set(scales) | {1.0}))
        self._rot = -1
        self._tpl_cache: dict = {}
        self._full_cache: dict = {}
        self.coarse_threshold = max(0.5, self.threshold - 0.18)
        self._best_scale: Optional[float] = None
        self.state = IDLE
        self._hits = 0
        self._misses = 0
        self._attempt = 0
        self._next_click = 0.0
        self._last_check = 0.0
        self._until = 0.0
        self.dismissed = 0
        self._wait_until = 0.0

        # ---- view restore state ----
        self.restore_view = bool(restore_view)
        self.restore_wait_s = float(restore_wait_s)
        self.restore_settle_s = float(restore_settle_s)
        self.restore_tol_px = float(restore_tol_px)
        self.restore_max_iter = int(restore_max_iter)
        self.restore_max_step_frac = float(restore_max_step_frac)
        self.restore_mirror_fallback = bool(restore_mirror_fallback)
        self.restored = 0
        self._drag_log: list = []        # every drag sent while dismissing: (x, y, signed length) in screen px
        self._mirror: list = []          # drags still to undo in mirror mode (last drag first)
        self._mirroring = False
        self._orb = cv2.ORB_create(nfeatures=2000, fastThreshold=8)
        self._bf = cv2.BFMatcher(cv2.NORM_HAMMING)
        self._ref0 = None                # features of the scene before we touched anything
        self._snap = None                # features right before the most recent drag
        self._snap_pending = None        # signed length of the drag whose pan has not been measured yet
        self._cum = [0.0, 0.0]           # tracked scene offset since _ref0 (dx, dy)
        self._lost = False               # tracking broke: only a direct comparison with _ref0 can be trusted
        self._drags_sent = 0
        self._gain = 1.0                 # scene px moved per mouse px dragged (sign is learned; +1 = scene follows the mouse)
        self._gain_known = False
        self._rest_iter = 0
        self._rest_fail = 0
        self._rest_next = 0.0

        # Highrise closes this banner by pressing on it and dragging.
        # We grab DOWN twice (in case the first press is ignored by the game),
        # then grab UP once. "wait_s" delays the first action so the popup
        # animation can finish before we touch it.
        self.action_sequence = [
            {"type": "drag_down", "target": "template", "dist_frac": 0.30,
             "wait_s": 5.0, "desc": "grab banner DOWN (short)"},
            {"type": "drag_down", "target": "template", "dist_frac": 0.45,
             "desc": "grab banner DOWN (long)"},
            # NEW: focus click just above window center before dragging up,
            # so the game registers our press point before the upward drag.
            {"type": "click", "target": "window_center_high",
             "desc": "focus click just above center before drag UP"},
            # drag_up starts at the window center (the drag itself moves the mouse there)
            # and goes up by the same distance as the 2nd drag down (0.45).
            {"type": "drag_up", "target": "window_center", "dist_frac": 0.45,
             "desc": "drag UP from screen center (same distance as 2nd drag down)"},
            {"type": "double_click", "target": "template",
             "desc": "double-click banner (fallback)"},
        ]

    # ---------------------------------------------------------------- detection
    def _tpl(self, sc: float) -> np.ndarray:
        t = self._tpl_cache.get(sc)
        if t is None:
            f = 0.5 * sc
            t = cv2.resize(self.template, None, fx=f, fy=f,
                           interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_CUBIC)
            self._tpl_cache[sc] = t
        return t

    def _full_tpl(self, sc: float) -> np.ndarray:
        t = self._full_cache.get(sc)
        if t is None:
            t = self.template if sc == 1.0 else cv2.resize(
                self.template, None, fx=sc, fy=sc,
                interpolation=cv2.INTER_AREA if sc < 1 else cv2.INTER_CUBIC)
            self._full_cache[sc] = t
        return t

    def find(self, frame: np.ndarray, scales=None) -> Optional[Tuple[float, int, int, int, int]]:
        """Best match (score, x, y, w, h) in frame pixels, or None. Matching runs at half resolution."""
        if frame.ndim == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY if frame.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
        else:
            gray = frame
        small = cv2.resize(gray, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        best = None
        for sc in (scales if scales is not None else [self._best_scale or 1.0]):
            t = self._tpl(sc)
            if t.shape[0] < 6 or t.shape[1] < 6 or t.shape[0] >= small.shape[0] or t.shape[1] >= small.shape[1]:
                continue
            _mn, mx, _l, loc = cv2.minMaxLoc(cv2.matchTemplate(small, t, cv2.TM_CCOEFF_NORMED))
            if mx < self.coarse_threshold:
                continue
            full_t = self._full_tpl(sc)
            x0, y0 = max(0, loc[0] * 2 - 6), max(0, loc[1] * 2 - 6)
            roi = gray[y0:y0 + full_t.shape[0] + 12, x0:x0 + full_t.shape[1] + 12]
            if roi.shape[0] < full_t.shape[0] or roi.shape[1] < full_t.shape[1]:
                continue
            _a, sc_full, _b, l2 = cv2.minMaxLoc(cv2.matchTemplate(roi, full_t, cv2.TM_CCOEFF_NORMED))
            if sc_full >= self.threshold and (best is None or sc_full > best[0]):
                best = (float(sc_full), int(x0 + l2[0]), int(y0 + l2[1]),
                        int(full_t.shape[1]), int(full_t.shape[0]), sc)
        if best is None:
            return None
        self._best_scale = best[5]
        return best[:5]

    def _scales_for_check(self):
        primary = self._best_scale or 1.0
        if self.state != IDLE:
            return [primary]
        self._rot = (self._rot + 1) % len(self.scales)
        extra = self.scales[self._rot]
        return [primary] if extra == primary else [primary, extra]

    # ---------------------------------------------------------------- action coords
    def _get_action_coords(self, rect: dict, found: Optional[Tuple[float, int, int, int, int]], action: dict) -> Tuple[int, int]:
        target = action.get("target", "template")
        if target == "template" and found:
            _score, fx, fy, fw, fh = found
            return int(rect["left"] + fx + fw // 2), int(rect["top"] + fy + fh // 2)
        elif target == "window_center":
            return int(rect["left"] + rect["width"] // 2), int(rect["top"] + rect["height"] // 2)
        elif target == "window_center_high":
            # NEW: same x as center, but a bit higher inside the app window.
            return int(rect["left"] + rect["width"] // 2), int(rect["top"] + rect["height"] * self.center_high_frac)
        elif target == "window_upper":
            return int(rect["left"] + rect["width"] // 2), int(rect["top"] + rect["height"] * 0.25)
        elif target == "window_lower":
            return int(rect["left"] + rect["width"] // 2), int(rect["top"] + rect["height"] * 0.75)
        # fallback
        return int(rect["left"] + rect["width"] // 2), int(rect["top"] + rect["height"] // 2)

    # ---------------------------------------------------------------- view restore
    # Idea: every drag may pan the camera. We snapshot the scene (ORB features, banner area
    # excluded) before each drag and measure the pan right after it. A single big pan can leave
    # almost nothing of the old view to match, but each individual step stays measurable, so the
    # steps are added up ("tracked" offset). Once the view is close to the original again it is
    # also compared directly with the very first snapshot ("direct"), which removes any drift.
    @staticmethod
    def _small_gray(frame: np.ndarray) -> np.ndarray:
        if frame.ndim == 3:
            g = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY if frame.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
        else:
            g = frame
        return cv2.resize(g, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)

    def _features(self, frame: np.ndarray, found=None):
        """ORB features of the frame (half size), ignoring the banner area. None if too few."""
        small = self._small_gray(frame)
        mask = np.full(small.shape, 255, np.uint8)
        if found:
            _s, fx, fy, fw, fh = found
            mx, my = int(fw * 0.25), int(fh * 0.5)         # the banner can be bigger than its template
            x0, y0 = max(0, (fx - mx) // 2), max(0, (fy - my) // 2)
            x1, y1 = min(small.shape[1], (fx + fw + mx) // 2 + 1), min(small.shape[0], (fy + fh + my) // 2 + 1)
            mask[y0:y1, x0:x1] = 0
        kp, des = self._orb.detectAndCompute(small, mask)
        if des is None or len(kp) < 20:
            return None
        return np.float32([k.pt for k in kp]), des

    def _measure_shift(self, ref, frame: np.ndarray, found=None):
        """How far the scene moved between `ref` (from _features) and `frame`, in frame px:
        (dx, dy, votes, other_votes) or None. dy > 0 means the scene now sits LOWER.

        Screen-fixed things (HUD, chat bar) match at zero shift and are counted separately; the
        biggest NON-zero cluster of matches is the camera pan. Moving ghosts / avatars form small,
        incoherent clusters and get outvoted."""
        if ref is None:
            return None
        ref_pts, ref_des = ref
        cur = self._features(frame, found)
        if cur is None:
            return None
        cur_pts, des = cur
        d = []
        for pr in self._bf.knnMatch(ref_des, des, k=2):
            if len(pr) < 2:
                continue
            m, n = pr
            if m.distance < 0.75 * n.distance:
                d.append(2.0 * (cur_pts[m.trainIdx] - ref_pts[m.queryIdx]))   # x2: features were found at half size
        if len(d) < 8:
            return None
        d = np.asarray(d, np.float32)
        norm = np.hypot(d[:, 0], d[:, 1])
        tol = 5.0
        zero_n = int((norm <= tol).sum())
        mov = d[norm > 2 * tol]
        mv_n, mv = 0, np.zeros(2, np.float32)
        if len(mov):
            dist = np.hypot(mov[:, None, 0] - mov[None, :, 0], mov[:, None, 1] - mov[None, :, 1])
            i = int((dist <= tol).sum(axis=1).argmax())
            inl = mov[dist[i] <= tol]
            mv_n, mv = len(inl), inl.mean(axis=0)
        # coherent moved cluster that is not dwarfed by the screen-fixed matches -> the scene moved
        if mv_n >= 8 and mv_n >= 0.2 * zero_n:
            return float(mv[0]), float(mv[1]), mv_n, zero_n
        # "nothing moved" is only believable when the WORLD matches in place (a large share of the
        # remembered features at zero shift); a handful of matches is just the HUD -> view lost
        if zero_n >= max(10, 0.12 * len(ref_pts)):
            return 0.0, 0.0, zero_n, mv_n
        return None

    def _settle_drag(self, frame: np.ndarray, found) -> None:
        """Measure the pan caused by the last drag; add it to the tracked offset and learn the gain."""
        v = self._snap_pending
        self._snap_pending = None
        m = self._measure_shift(self._snap, frame, found)
        if m is None:
            self._lost = True
            log.info("POPUP view: could not measure the pan of the last drag (tracking lost, will compare with the original view)")
            return
        dx, dy, votes, other = m
        self._cum[0] += dx
        self._cum[1] += dy
        log.info("POPUP view: last drag (%+d px) moved the scene dx=%+.0f dy=%+.0f (votes %d)", int(v), dx, dy, votes)
        if abs(v) >= 20:
            g = dy / v
            if 0.15 <= abs(g) <= 6.0:
                self._gain = g if not self._gain_known or self._gain * g < 0 else 0.5 * (self._gain + g)
                self._gain_known = True
                log.info("POPUP view: drag gain %.2f (using %.2f)", g, self._gain)

    def _mirror_step(self, rect: dict, now: float, click_fn) -> bool:
        """Undo the original drags one by one: press where the drag ENDED, drag back the same distance."""
        if not self._mirror:
            log.info("POPUP view restore: mirrored all drags (net %+d px undone)",
                     sum(v for _x, _y, v in self._drag_log))
            self.restored += 1
            self.state, self._hits, self._mirroring = IDLE, 0, False
            return False
        x, y, v = self._mirror.pop(0)
        top, bottom = rect["top"] + 8, rect["top"] + rect["height"] - 8
        y_press = int(min(max(y + v, top), bottom))                    # where the original drag let go (kept inside the window)
        ok = click_fn("drag_up" if v > 0 else "drag_down", x, y_press, dist=abs(int(v)))
        log.info("POPUP view mirror: %s %d px at (%d,%d) %s", "drag up" if v > 0 else "drag down",
                 abs(int(v)), x, y_press, "sent" if ok else "BLOCKED")
        self._rest_next = now + self.restore_settle_s
        return True

    def _restore_step(self, frame: np.ndarray, rect: dict, now: float, click_fn) -> bool:
        """Closed loop: work out how far the scene is from the original, drag it back, repeat."""
        if now < self._rest_next:
            return True
        if self._mirroring:
            return self._mirror_step(rect, now, click_fn)
        if self._snap_pending is not None:
            self._settle_drag(frame, None)
        direct = self._measure_shift(self._ref0, frame)
        if direct is not None:
            dx, dy = direct[0], direct[1]
            self._cum, self._lost, src = [dx, dy], False, "direct"
        elif not self._lost:
            dx, dy = self._cum
            src = "tracked"
        else:
            self._rest_fail += 1
            if self._rest_fail >= 3:
                if self.restore_mirror_fallback and self._drag_log and self._rest_iter == 0:
                    log.warning("POPUP view restore: cannot measure the view, undoing the %d drag(s) by mirroring them "
                                "(same distance, opposite direction, last drag first)", len(self._drag_log))
                    self._mirror, self._mirroring = list(reversed(self._drag_log)), True
                    self._rest_next = now
                    return True
                log.warning("POPUP view restore: cannot work out the view offset; leaving the view as is")
                self.state, self._hits = IDLE, 0
                return False
            self._rest_next = now + 0.5
            return True
        log.info("POPUP view offset: dx=%+.0f dy=%+.0f px (%s)", dx, dy, src)
        if abs(dy) <= self.restore_tol_px:
            self.restored += 1
            log.info("POPUP view restored (vertical error %+.0f px after %d corrective drag(s))", dy, self._rest_iter)
            self.state, self._hits = IDLE, 0
            return False
        if self._rest_iter >= self.restore_max_iter:
            log.warning("POPUP view restore gave up after %d drags (still %+.0f px off)", self._rest_iter, dy)
            self.state, self._hits = IDLE, 0
            return False
        v = -dy / self._gain                                  # mouse px to drag (+ = down)
        cap = self.restore_max_step_frac * rect["height"]     # keep each step small enough to stay measurable
        v = max(-cap, min(cap, v))
        cx = int(rect["left"] + rect["width"] // 2)
        cy = int(rect["top"] + rect["height"] // 2)
        self._snap = self._features(frame)
        if v > 0:
            ok = click_fn("drag_down", cx, int(cy - v / 2), dist=int(v))
        else:
            ok = click_fn("drag_up", cx, int(cy + abs(v) / 2), dist=int(abs(v)))
        log.info("POPUP view restore #%d: drag %s %d px %s", self._rest_iter + 1,
                 "down" if v > 0 else "up", int(abs(v)), "sent" if ok else "BLOCKED")
        self._rest_iter += 1
        if ok:
            self._snap_pending = v if self._snap is not None else None
            self._lost = self._lost or self._snap is None
        self._rest_next = now + self.restore_settle_s
        return True

    # ---------------------------------------------------------------- state machine
    def update(self, frame: np.ndarray, rect: dict, now: float,
               click_fn: Callable[..., bool]) -> bool:
        """Returns True while the popup is being handled (caller should not click ghosts)."""
        if self.state == RESTORE:
            return self._restore_step(frame, rect, now, click_fn)
        if self.state == COOLDOWN:
            if now < self._until:
                return False
            self.state, self._hits = IDLE, 0
        if self.state == IDLE and now - self._last_check < self.check_interval_s:
            return False
        self._last_check = now
        found = self.find(frame, self._scales_for_check())

        if self.state == IDLE:
            self._hits = self._hits + 1 if found else 0
            if self._hits < self.confirm_hits:
                return False
            self.state, self._attempt, self._misses, self._next_click = ACTIVE, 0, 0, now
            self._ref0 = self._snap = self._snap_pending = None
            self._cum, self._lost, self._drags_sent = [0.0, 0.0], False, 0
            self._drag_log, self._mirror, self._mirroring = [], [], False
            # honour a first-action wait before sending anything
            first_wait = float(self.action_sequence[0].get("wait_s", 0.0))
            self._wait_until = now + first_wait
            if first_wait > 0:
                log.info("POPUP 'esprits attrapés' detected (score %.2f): waiting %.1fs before first action",
                         found[0], first_wait)
            else:
                log.info("POPUP 'esprits attrapés' detected (score %.2f): starting dismissal sequence", found[0])

        # ACTIVE
        if not found:
            self._misses += 1
            if self._misses >= 2:
                self.dismissed += 1
                log.info("POPUP dismissed after %d action(s)", self._attempt)
                if self.restore_view and self._drags_sent and self._ref0 is not None:
                    log.info("POPUP gone: moving the view back to where it was")
                    self.state, self._hits = RESTORE, 0
                    self._rest_iter = self._rest_fail = 0
                    self._rest_next = now + self.restore_wait_s
                    return True
                self.state, self._hits = IDLE, 0
                return False
            return True
        self._misses = 0

        # measure the pan caused by the previous drag once the game has settled
        if self._snap_pending is not None and now >= self._next_click:
            self._settle_drag(frame, found)

        # honour any pending wait before sending the next action
        if now < self._wait_until:
            return True
        if now < self._next_click:
            return True

        if self._attempt >= len(self.action_sequence):
            log.warning("POPUP still visible after %d actions; pausing auto-dismiss for %.0fs",
                        self._attempt, self.giveup_cooldown_s)
            self.state, self._until = COOLDOWN, now + self.giveup_cooldown_s
            return False

        action = self.action_sequence[self._attempt]
        x, y = self._get_action_coords(rect, found, action)
        is_drag = action["type"].startswith("drag")
        if self._attempt == 0 or is_drag:
            feats = self._features(frame, found)     # scene exactly as it is before this action
            if self._attempt == 0:
                self._ref0 = feats
                if feats is None:
                    log.warning("POPUP view restore disabled for this popup: too few scene features to remember the view")
            if is_drag:
                self._snap = feats

        # Calculate drag distance in pixels
        dist_px = 0
        if "dist_frac" in action:
            dist_px = int(rect["height"] * action["dist_frac"])

        kwargs = {}
        if "key" in action:
            kwargs["key"] = action["key"]
        if dist_px > 0:
            kwargs["dist"] = dist_px

        ok = click_fn(action["type"], x, y, **kwargs)
        if ok and is_drag:
            self._drags_sent += 1
            signed = dist_px if action["type"] == "drag_down" else -dist_px
            self._drag_log.append((int(x), int(y), int(signed)))
            log.info("POPUP drags sent so far: %d, net %+d px (down is +)", len(self._drag_log),
                     sum(v for _x, _y, v in self._drag_log))
            self._snap_pending = (dist_px if action["type"] == "drag_down" else -dist_px) if self._snap is not None else None
            if self._snap is None:
                self._lost = True
        log.info("POPUP action #%d: %s at (%d,%d) %s",
                 self._attempt + 1, action["desc"], x, y, "sent" if ok else "BLOCKED")
        self._attempt += 1
        self._next_click = now + self.settle_s

        # if the NEXT action has wait_s, schedule it
        next_wait = 0.0
        if self._attempt < len(self.action_sequence):
            next_wait = float(self.action_sequence[self._attempt].get("wait_s", 0.0))
        self._wait_until = now + next_wait
        return True