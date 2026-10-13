"""Ectoplaz toast reader + Discord reporter (v3).

Reads the "Vous avez obtenu Ectoplaz xN" toast (bottom-left of the game window) and
  1. tells listeners (the smart learner) about every gain, with the time the toast FIRST appeared;
  2. posts it to Discord from a background queue (bursts merged, failed posts retried).

Fixes vs the previous version
  * DOUBLE COUNTING: one OCR misread in the middle of a toast re-armed the counter, so the same
    toast was counted twice. Re-arming now needs the toast to really be gone (several polls).
  * A failed read was cached forever for an unchanged toast -> a gain could be missed. Only good
    reads are cached; failures are retried (throttled).
  * OCR digit confusions (S/5, O/0, l/1, B/8, Z/2) are repaired; a second pass with other
    thresholds runs only when the first read fails.
  * Missing/misplaced Tesseract: auto-detected, checked once at start, ONE clear error instead of
    an error spam every poll; feed_alive() is False when OCR is broken, so the learner never
    treats "no gain" as evidence while the reader is blind.
  * Discord posts are retried (3x with backoff) instead of silently lost; the timestamp is the
    first gain of a merged burst; the webhook URL can come from the BLOOP_WEBHOOK_URL env var.
  * Health line every 60 s (reads / cache hits / failures) + raw crop saved on failures.
"""
import logging
import os
import queue
import re
import shutil
import threading
import time
from pathlib import Path

import cv2
import numpy as np

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

log = logging.getLogger("bot.webhook")

# --------------------------------------------------------------------------- Tesseract
try:
    import pytesseract
    _HAVE_PYT = True
except ImportError:
    pytesseract = None
    _HAVE_PYT = False


def _find_tesseract():
    cands = [os.environ.get("TESSERACT_CMD"), shutil.which("tesseract"),
             r"C:\Program Files\Tesseract-OCR\tesseract.exe",
             r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
             os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe")]
    for c in cands:
        if c and Path(c).is_file():
            return c
    return None


HAS_OCR = False
if _HAVE_PYT:
    _exe = _find_tesseract()
    if _exe:
        pytesseract.pytesseract.tesseract_cmd = _exe
        try:
            pytesseract.get_tesseract_version()
            HAS_OCR = True
        except Exception as _e:  # pragma: no cover
            log.error("Tesseract found at %s but unusable: %s", _exe, _e)
    else:
        log.error("Tesseract OCR not found. Install https://github.com/UB-Mannheim/tesseract/wiki "
                  "(or set TESSERACT_CMD). Ecto confirmation + Discord reporting are DISABLED.")
else:
    log.error("pytesseract missing: pip install pytesseract requests. "
              "Ecto confirmation + Discord reporting are DISABLED.")

# --------------------------------------------------------------------------- tuning
TOAST_ROI = (0.07, 0.79, 0.22, 0.92)    # x1, y1, x2, y2 as fractions of the game frame
TOAST_POLL_S = 0.20
TOAST_CONFIRM_HITS = 2                  # identical reads in a row before a gain counts
ABSENT_POLLS_TO_REARM = 2               # polls with NO bright text = toast gone
UNREAD_POLLS_TO_REARM = 3               # polls with text but unreadable = treat as gone (scene glare)
RETRY_FAILED_READ_S = 0.6               # re-OCR an unchanged-but-unreadable crop at most this often
TEXT_THRS = (150, 125, 175)             # first is the default; the others are fallback passes
MIN_TEXT_PIX = 25
MAX_GAIN = 100000

_DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "S": "5", "s": "5", "l": "1", "I": "1",
                            "|": "1", "B": "8", "Z": "2", "z": "2"})
TOAST_RE = re.compile(r"(?:ecto|plaz)\w*\s*[xX×*]\s*([0-9OoSslI|BZz]{1,6})", re.IGNORECASE)


def parse_amount(text, max_gain=MAX_GAIN):
    """'Vous avez obtenu Ectoplaz xS5' -> 55. None if no plausible amount."""
    m = TOAST_RE.search(text.replace("\n", " "))
    if not m:
        return None
    raw = m.group(1)
    if not any(c.isdigit() for c in raw):
        return None                                   # 'xs' alone is noise, not a number
    try:
        v = int(raw.translate(_DIGIT_FIX))
    except ValueError:
        return None
    return v if 0 < v <= max_gain else None


class WebhookReporter:
    def __init__(self, url, interval_s=300, max_plausible_gain=MAX_GAIN):
        self.url = os.environ.get("BLOOP_WEBHOOK_URL") or url
        self.interval_s = interval_s                  # unused; keeps main.py's call signature
        self.max_gain = int(max_plausible_gain)
        self.session_start = time.time()
        self.session_total = 0
        self.session_drops = 0
        self._lock = threading.Lock()
        self._listeners = []                          # fn(amount, t_seen)
        self._stats_provider = None

        # toast state machine
        self._cand = None
        self._cand_hits = 0
        self._cand_t = 0.0
        self._armed = True
        self._counted_value = None
        self._absent = 0
        self._unread = 0

        # OCR worker
        self._roi_q = queue.Queue(maxsize=1)
        self._last_poll = 0.0
        self._last_mask = None
        self._last_read = None                        # only ever a GOOD reading
        self._last_fail_t = 0.0
        self._last_dbg = 0.0
        self._ocr_err_t = 0.0
        self.toast_visible = False
        self.last_ocr_time = 0.0                      # last time the reader processed a poll successfully
        self.last_gain_time = 0.0
        self.counters = {"polls": 0, "ocr": 0, "cached": 0, "empty": 0, "fail": 0, "gains": 0, "posts_failed": 0}
        self._last_health = time.time()

        self._out_q = queue.Queue()
        self._http = requests.Session() if requests else None
        if HAS_OCR:
            threading.Thread(target=self._ocr_loop, daemon=True, name="toast-ocr").start()
            threading.Thread(target=self._send_loop, daemon=True, name="discord-send").start()
        if not self.url:
            log.warning("No webhook URL set: gains are tracked but nothing is posted to Discord.")

    # ------------------------------------------------------------------ public API
    def add_gain_listener(self, fn):
        """fn(amount:int, t_seen:float), called from the OCR thread on every confirmed gain."""
        self._listeners.append(fn)

    def set_stats_provider(self, fn):
        self._stats_provider = fn

    def feed_alive(self, max_age=3.0):
        """True only while OCR really works, so 'no gain' is meaningful evidence."""
        return HAS_OCR and (time.time() - self.last_ocr_time) < max_age

    def check_and_report(self, frame):
        """Called every frame by main.py: a slice copy + queue put at most every TOAST_POLL_S."""
        if not HAS_OCR:
            return
        now = time.time()
        if now - self._last_poll < TOAST_POLL_S:
            return
        self._last_poll = now
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = TOAST_ROI
        roi = frame[int(h * y1):int(h * y2), int(w * x1):int(w * x2)]
        if roi.size == 0:
            return
        try:
            self._roi_q.put_nowait((now, roi.copy()))
        except queue.Full:
            pass                                      # OCR busy: the newest crop wins next time

    # ------------------------------------------------------------------ OCR worker
    def _ocr_loop(self):
        while True:
            t, roi = self._roi_q.get()
            try:
                visible, value = self._read_toast(roi)
                self.counters["polls"] += 1
                self._update_toast_state(value, visible, t)
                self._health()
            except Exception as e:
                log.error("Toast processing error: %s", e)

    def _ocr_once(self, gray, thr):
        up = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        _, img = cv2.threshold(up, thr, 255, cv2.THRESH_BINARY_INV)
        return parse_amount(pytesseract.image_to_string(img, config="--psm 6"), self.max_gain), img

    def _read_toast(self, roi):
        """Returns (visible, value). visible = toast-like bright text present; value = amount or None."""
        gray = cv2.cvtColor(roi, cv2.COLOR_BGRA2GRAY if roi.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
        bright = gray > TEXT_THRS[0]
        self.last_ocr_time = time.time()
        if int(np.count_nonzero(bright)) < MIN_TEXT_PIX:       # nothing toast-like: skip OCR entirely
            self.toast_visible = False
            self._last_mask, self._last_read = None, None
            self.counters["empty"] += 1
            return False, None
        self.toast_visible = True
        small = cv2.resize(bright.astype(np.uint8) * 255, (48, 20), interpolation=cv2.INTER_AREA)
        same = self._last_mask is not None and float(np.mean(cv2.absdiff(small, self._last_mask))) < 4.0
        now = time.time()
        if same and self._last_read is not None:               # same toast, already read: reuse (cheap)
            self.counters["cached"] += 1
            return True, self._last_read
        if same and now - self._last_fail_t < RETRY_FAILED_READ_S:
            self.counters["cached"] += 1
            return True, None                                  # unreadable crop: don't hammer Tesseract
        self._last_mask = small
        value, last_img = None, None
        try:
            for thr in TEXT_THRS:                              # fallback thresholds only run on failure
                value, last_img = self._ocr_once(gray, thr)
                if value is not None:
                    break
        except Exception as e:                                 # Tesseract itself broke
            self.last_ocr_time = 0.0                           # => feed_alive() goes False
            if now - self._ocr_err_t > 30.0:
                self._ocr_err_t = now
                log.error("Tesseract failed (%s). Ecto confirmation paused until it works again.", e)
            return True, None
        self.counters["ocr"] += 1
        if value is None:
            self.counters["fail"] += 1
            self._last_fail_t = now
            self._save_debug(roi, last_img)
        self._last_read = value
        return True, value

    def _save_debug(self, roi, thresh):
        if time.time() - self._last_dbg < 10.0:
            return
        self._last_dbg = time.time()
        try:
            d = Path(__file__).resolve().parent / "diagnostics"
            d.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(d / "toast_fail_raw.png"), roi)
            if thresh is not None:
                cv2.imwrite(str(d / "toast_debug.png"), thresh)
        except Exception:
            pass

    def _health(self):
        now = time.time()
        if now - self._last_health < 60.0:
            return
        self._last_health = now
        c = self.counters
        log.info("toast-reader: polls=%d ocr=%d cached=%d empty=%d unreadable=%d gains=%d post_failures=%d",
                 c["polls"], c["ocr"], c["cached"], c["empty"], c["fail"], c["gains"], c["posts_failed"])

    # ------------------------------------------------------------------ toast state machine
    def _update_toast_state(self, amount, visible, t_poll):
        if not visible:
            self._absent += 1
            if self._absent >= ABSENT_POLLS_TO_REARM:
                self._cand, self._cand_hits, self._armed, self._unread = None, 0, True, 0
            return
        self._absent = 0
        if amount is None:
            # Text on screen but unreadable. One or two misreads must NOT re-arm (that double-counted
            # a toast); only a sustained unreadable stretch means the toast is really gone.
            self._unread += 1
            if self._unread >= UNREAD_POLLS_TO_REARM:
                self._cand, self._cand_hits, self._armed = None, 0, True
            return
        self._unread = 0
        if amount == self._cand:
            self._cand_hits += 1
        else:
            self._cand, self._cand_hits, self._cand_t = amount, 1, t_poll
        if self._cand_hits < TOAST_CONFIRM_HITS:
            return
        if not self._armed and amount == self._counted_value:
            return                                              # same toast, still on screen
        self._armed = False
        self._counted_value = amount
        with self._lock:
            self.session_total += amount
            self.session_drops += 1
        self.counters["gains"] += 1
        self.last_gain_time = time.time()
        log.info("Ectoplaz +%d (session total %d)", amount, self.session_total)
        for fn in self._listeners:
            try:
                fn(amount, self._cand_t)                        # FIRST sighting time
            except Exception as e:
                log.error("gain listener failed: %s", e)
        self._out_q.put((amount, self._cand_t))

    # ------------------------------------------------------------------ Discord
    def _session_line(self):
        elapsed = max(1, int(time.time() - self.session_start))
        h, rem = divmod(elapsed, 3600)
        rate = f" · ~{int(self.session_total * 3600 / elapsed):,}/h" if elapsed >= 300 else ""   # no silly rate in the first 5 min
        return (f"Session total: **{self.session_total:,}** ({self.session_drops} drops)\n"
                f"Session time: {h}h {rem // 60:02d}m{rate}")

    def _send_loop(self):
        while True:
            amount, t0 = self._out_q.get()
            n = 1
            time.sleep(0.4)                                     # grace: a burst becomes one post
            try:
                while True:
                    a, _ = self._out_q.get_nowait()
                    amount += a
                    n += 1
            except queue.Empty:
                pass
            extra = ""
            if self._stats_provider:
                try:
                    extra = self._stats_provider() or ""
                except Exception:
                    extra = ""
            head = f"🟢 **+{amount:,} Ectoplaz**" + (f" ({n} catches)" if n > 1 else "")
            ok = self._post(f"{head}\n{self._session_line()}\n{extra}Time: <t:{int(t0)}:R>")
            if not ok:
                self.counters["posts_failed"] += 1

    def _post(self, content, attempts=3):
        if not (self._http and self.url):
            return False
        for i in range(attempts):
            try:
                r = self._http.post(self.url, json={"content": content}, timeout=10)
                if r.status_code == 429:
                    try:
                        wait = float(r.json().get("retry_after", 1))
                    except Exception:
                        wait = 1.0
                    time.sleep(min(10.0, wait) + 0.1)
                    continue
                if r.status_code in (401, 403, 404):
                    log.error("Discord webhook rejected (HTTP %d): the URL is wrong or was deleted. "
                              "Posts are skipped until you fix webhook_url.", r.status_code)
                    self.url = ""                               # stop hammering a dead webhook
                    return False
                if r.status_code < 300:
                    return True
                log.warning("Discord HTTP %d (attempt %d/%d)", r.status_code, i + 1, attempts)
            except Exception as e:
                # HTTP libraries may include a request URL in exception text. Never
                # emit a Discord webhook token to the rotating logs.
                detail = str(e)
                if self.url:
                    detail = detail.replace(self.url, "<webhook-redacted>")
                detail = re.sub(
                    r"https?://(?:canary\.)?discord(?:app)?\.com/api/webhooks/[^\s/?]+/[^\s?]+",
                    "https://discord.com/api/webhooks/<redacted>", detail, flags=re.IGNORECASE)
                log.warning("Discord post failed (attempt %d/%d): %s", i + 1, attempts, detail[:240])
            time.sleep(1.0 * (i + 1))
        return False
