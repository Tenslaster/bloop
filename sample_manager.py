#!/usr/bin/env python3
"""Sample manager: review, clean and relabel what BLOOP's smart detector has learned.

Opened from the Learning tab. Works directly on smart/positives, smart/negatives and
smart/quarantine, so it is safe to use while the bot is stopped or running.

What it does for you
--------------------
* Shows every sample as a thumbnail, most suspicious first. Suspicion comes from the
  cross-validated scores the auto-cleaner writes to smart/review.json: a "ghost" the model
  is sure is NOT a ghost (or the other way round) is probably a mislabel.
* A banner tells you how many samples look mislabelled and takes you straight to them.
* Click, shift-click (range) or drag across thumbnails to select. Selection survives paging.
* Quarantine / restore / flip are all UNDOABLE (Ctrl+Z). Restored and flipped samples are
  also marked "kept" (smart/keep.json) so the auto-cleaner never removes them again.
* Restore is a split button. The main part puts the selection back where it came from; the arrow
  opens every option: restore as ghost / as not-ghost, restore + label in one step, restore without
  protection, and whole-group restores (all auto-cleaned, all manual, everything shown). Large or
  group restores show a preview and ask first. Right-click works in the Quarantine tab too.
* The inspector (right) explains WHY a sample is flagged, or why auto-clean quarantined it.
* Retrain / auto-clean requests report back when the bot has finished.
* Edit individual or bulk training weights (including quarantined samples); filename-linked
  labels, keep markers and review scores follow renamed files, and Ctrl+Z undoes weight edits.
* Export copies of selected PNGs to any folder, including from Quarantine; source files remain untouched.

Labelling (ghost kind + colour for the wave/boss detector): select ghosts, then use the Label
menu, right-click, or keys 1-4 (small: blue, purple, yellow, rainbow) and Alt+1..7 (boss: blue,
cyan, green, light green, red, white, rainbow); 0 clears. Saved to smart/ghost_labels.json; the
bot picks the labels up by itself.

Auto-label ghosts: once your own labels are good enough, "Auto-label ghosts" (footer) labels the rest of the
Ghosts tab for you (smart/ghost_labels_auto.json; shown as lowercase s/b). The bot also does this on its own
(config: ghost_auto_label). Your labels always win; Ctrl+Z undoes it.

Keyboard: click/drag select - Shift+click range - Ctrl+A page - Esc clear - Del quarantine -
R restore - G / N restore as ghost / not ghost - F flip - Ctrl+Z undo - PgUp/PgDn page - F5 refresh - Ctrl+wheel thumbnail size.
"""
from __future__ import annotations

import base64
import json
import os
import queue
import threading
import time
import tkinter as tk
from collections import Counter, OrderedDict
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox
import shutil
import re
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

import cv2
import numpy as np

# ---------------------------------------------------------------- palette
BG = "#0b1020"
PANEL = "#111a2e"
CARD = "#16223a"
HOVER = "#1e2e4d"
EDGE = "#26344f"
TEXT = "#e8eefc"
MUTED = "#91a2bd"
ACCENT = "#54e0c1"
ACCENT_DK = "#06201b"
RED = "#ff6e83"
GREEN = "#76e4a5"
ORANGE = "#ffba66"
BLUE = "#8ab4ff"
PURPLE = "#c9a7ff"
UI = ("Segoe UI", 9)
UI_B = ("Segoe UI", 9, "bold")
UI_S = ("Segoe UI", 8)
MONO = ("Consolas", 8)

DUP_SIZE = 16     # images are compared as 16x16 colour thumbnails
DUP_TOL = 2.0     # max mean abs pixel difference (0-255) to count as "the same" image

PAGE = 120
PAD = 8
CAP = 16
THUMB_MIN, THUMB_MAX, THUMB_DEFAULT = 56, 144, 88
SUSPECT = 0.70    # suspicion at/above which a sample is "likely mislabelled"
VERY_SUSPECT = 0.90

BULK_CONFIRM = 50   # restoring at least this many samples at once asks for confirmation first
DEST_TEXT = {"pos": "Ghosts", "neg": "Not ghosts"}

VIEWS = (("pos", "Ghosts"), ("neg", "Not ghosts"), ("quar", "Quarantine"))
SORTS = (("suspicious", "Most suspicious"), ("newest", "Newest"), ("oldest", "Oldest"), ("weight", "Highest weight"))

# Ghost labels: key = "<kind>_<colour>" (colour uses '-' instead of a space). Points are for small ghosts.
GHOST_LABELS = (
    ("small_blue", "Small - blue (+5)"), ("small_purple", "Small - purple (+15)"),
    ("small_yellow", "Small - yellow (+55)"), ("small_rainbow", "Small - rainbow (+100)"),
    ("boss_blue", "Boss - blue"), ("boss_cyan", "Boss - cyan"), ("boss_green", "Boss - green"),
    ("boss_light-green", "Boss - light green"), ("boss_red", "Boss - red"),
    ("boss_white", "Boss - white"), ("boss_rainbow", "Boss - rainbow"),
)
LABEL_TEXT = dict(GHOST_LABELS)
LABEL_COLORS = {"blue": "#4aa3ff", "purple": "#c36bff", "yellow": "#ffe14d", "rainbow": "#ff6ad5",
                "cyan": "#4ff0ff", "green": "#3cc860", "light-green": "#9bff9b", "red": "#ff4d4d",
                "white": "#f2f2f2"}
NO_LABEL = "__none__"
AUTO_ONLY = "__auto__"     # label-filter value: only the labels the auto-labeller made


def label_color(key: str) -> str:
    return LABEL_COLORS.get(key.partition("_")[2], MUTED)


TAG_INFO = {
    "user":    (ACCENT, "You clicked it. Strongest hand-made label."),
    "ecto":    (GREEN, "Bot clicked it and the Ectoplaz toast confirmed a real catch."),
    "react":   (BLUE, "Bot clicked it and it vanished (weak positive; no gain was seen)."),
    "seed":    (PURPLE, "Imported from your seeds folder."),
    "static":  (ORANGE, "Sat still for seconds, so it was mined as scenery."),
    "ignored": (MUTED, "Looked like a candidate but nothing ever happened to it."),
    "noreact": ("#ff9f7a", "Bot clicked it, nothing reacted and no gain came: not a ghost."),
    "bad":     (RED, "You pressed F8 on a wrong bot click. Protected from auto-clean."),
}


# ================================================================== pure helpers
def _tag_of(path: Path) -> str:
    parts = path.stem.split("_")
    return parts[1] if len(parts) >= 3 else ""


def _weight_of(path: Path) -> float:
    """Read the training weight encoded by SampleStore in the filename."""
    match = re.search(r"_w([0-9]+(?:\.[0-9]+)?|\.[0-9]+)$", path.stem, re.IGNORECASE)
    if not match:
        return 1.0
    try:
        value = float(match.group(1))
        return value if np.isfinite(value) and value > 0 else 1.0
    except (TypeError, ValueError):
        return 1.0


def _stamp_of(path: Path) -> float:
    try:
        v = int(path.stem.split("_")[0]) / 1000.0
        return v if v > 1e9 else 0.0
    except (ValueError, IndexError):
        return 0.0


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _ago(seconds: float) -> str:
    if seconds < 90:
        return "just now"
    m = seconds / 60
    if m < 90:
        return f"{int(m)} min ago"
    h = m / 60
    if h < 36:
        return f"{int(h)} h ago"
    return f"{int(h / 24)} d ago"


def find_duplicate_samples(folder: Path, tol: float = DUP_TOL, progress=None):
    """Return (all_files, duplicates) for the PNGs in `folder`.

    Images are compared as DUP_SIZE x DUP_SIZE colour thumbnails; two images whose mean
    absolute pixel difference is <= tol count as the same. The highest-weight copy is kept
    (first in the sort order), later ones are reported as duplicates. Nothing is deleted.
    `progress(done, total)` is called now and then (safe to call from a worker thread)."""
    files = sorted(Path(folder).glob("*.png"), key=lambda p: (-_weight_of(p), p.name))
    kept_vecs: List[np.ndarray] = []
    kept_keys: List[int] = []
    dupes: List[Path] = []
    total = len(files)
    for n, p in enumerate(files, 1):
        if progress and (n % 100 == 0 or n == total):
            progress(n, total)
        try:
            img = cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            vec = cv2.resize(img, (DUP_SIZE, DUP_SIZE), interpolation=cv2.INTER_AREA).astype(np.float32).ravel()
        except Exception:
            continue
        key = int(vec.mean() // 4)
        is_dup = False
        idx = [i for i, k in enumerate(kept_keys) if abs(k - key) <= 1]
        if idx:
            mat = np.stack([kept_vecs[i] for i in idx])
            is_dup = float(np.abs(mat - vec).mean(axis=1).min()) <= tol
        if is_dup:
            dupes.append(p)
        else:
            kept_vecs.append(vec)
            kept_keys.append(key)
    return files, dupes


def read_sample_image(path: Path) -> Optional[Tuple[np.ndarray, Tuple[int, int]]]:
    """BGR uint8 image (transparent areas flattened onto dark grey) and its original (w, h)."""
    try:
        img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_UNCHANGED)
        if img is None:
            return None
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        if img.shape[2] == 4:
            a = img[:, :, 3:4].astype(np.float32) / 255.0
            img = (img[:, :, :3] * a + 40 * (1 - a)).astype(np.uint8)
        h, w = img.shape[:2]
        return img, (w, h)
    except Exception:
        return None


def fit_square(img: np.ndarray, size: int, bg: int = 24) -> np.ndarray:
    """Scale to fit inside a size x size square (crisp when enlarging), centred on a dark tile."""
    h, w = img.shape[:2]
    sc = size / float(max(h, w))
    interp = cv2.INTER_NEAREST if sc >= 2 else (cv2.INTER_CUBIC if sc > 1 else cv2.INTER_AREA)
    img = cv2.resize(img, (max(1, int(w * sc)), max(1, int(h * sc))), interpolation=interp)
    tile = np.full((size, size, 3), bg, np.uint8)
    y0, x0 = (size - img.shape[0]) // 2, (size - img.shape[1]) // 2
    tile[y0:y0 + img.shape[0], x0:x0 + img.shape[1]] = img
    return tile


# ================================================================== data layer (no Tk)
@dataclass
class Sample:
    path: Path
    positive: bool
    quarantined: bool
    tag: str
    weight: float
    stamp: float
    suspicion: float = 0.0
    score: Optional[float] = None      # cross-validated P(ghost); None = never scored
    kept: bool = False
    ghost_label: str = ""            # e.g. "small_yellow" / "boss_light-green"; "" = not labelled
    auto: bool = False               # ghost_label came from the auto-labeller, not from you

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def label(self) -> str:
        return "Ghost" if self.positive else "Not a ghost"

    @property
    def age_s(self) -> Optional[float]:
        return max(0.0, time.time() - self.stamp) if self.stamp else None


class SampleLibrary:
    """Everything the manager knows about the samples on disk. No UI code in here."""

    def __init__(self, smart: Path):
        self.smart = Path(smart)
        self.pos_dir = self.smart / "positives"
        self.neg_dir = self.smart / "negatives"
        self.quar_dir = self.smart / "quarantine"
        for d in (self.pos_dir, self.neg_dir, self.quar_dir / "positives", self.quar_dir / "negatives"):
            d.mkdir(parents=True, exist_ok=True)
        self.keep_path = self.smart / "keep.json"
        self.labels_path = self.smart / "ghost_labels.json"
        self.auto_path = self.smart / "ghost_labels_auto.json"
        self.labels: Dict[str, str] = {}
        self.auto_labels: Dict[str, str] = {}      # made by the auto-labeller; yours (self.labels) always win
        self.no_auto: Set[str] = set()             # you cleared these on purpose: never auto-label them again
        self.samples: List[Sample] = []
        self.keep: Set[str] = set()
        self.reasons: Dict[str, dict] = {}
        self.review_time: Optional[float] = None
        self.accuracy: Optional[float] = None
        self.scan()

    # ------------------------------------------------------------ scanning
    def scan(self) -> None:
        review = _read_json(self.smart / "review.json") or {}
        scores = {"pos": review.get("pos", {}) or {}, "neg": review.get("neg", {}) or {}}
        self.review_time = review.get("time") if isinstance(review.get("time"), (int, float)) else None
        self.accuracy = review.get("oof_accuracy") if isinstance(review.get("oof_accuracy"), (int, float)) else None
        keep = _read_json(self.keep_path)
        self.keep = set(keep) if isinstance(keep, list) else set()
        self._load_reasons()
        self._reload_labels()
        out: List[Sample] = []
        for folder, positive, quarantined in ((self.pos_dir, True, False), (self.neg_dir, False, False),
                                              (self.quar_dir / "positives", True, True),
                                              (self.quar_dir / "negatives", False, True)):
            for p in folder.glob("*.png"):
                mine = self.labels.get(p.name, "")
                auto = "" if (mine or p.name in self.no_auto) else self.auto_labels.get(p.name, "")
                s = Sample(p, positive, quarantined, _tag_of(p), _weight_of(p), _stamp_of(p), kept=p.name in self.keep,
                           ghost_label=mine or auto, auto=bool(auto))
                if not quarantined:
                    v = scores["pos" if positive else "neg"].get(p.name)
                    if isinstance(v, (int, float)):
                        s.score = float(v)
                        s.suspicion = float(1.0 - v) if positive else float(v)
                out.append(s)
        self.samples = out

    def _reload_labels(self) -> None:
        """Re-read both label files. The bot / auto-labeller writes ghost_labels_auto.json on its own,
        so every edit starts from what is on disk now, not from what was loaded at the last scan
        (otherwise saving one label would silently wipe auto-labels written in the meantime)."""
        lab = _read_json(self.labels_path)
        self.labels = {k: v for k, v in lab.items() if isinstance(k, str) and v in LABEL_TEXT} if isinstance(lab, dict) else {}
        self.no_auto = {k for k, v in lab.items() if isinstance(k, str) and v == ""} if isinstance(lab, dict) else set()
        aut = _read_json(self.auto_path)
        self.auto_labels = {k: v for k, v in aut.items() if isinstance(k, str) and v in LABEL_TEXT} if isinstance(aut, dict) else {}

    def _load_reasons(self) -> None:
        self.reasons = {}
        try:
            lines = (self.smart / "clean_log.jsonl").read_text(encoding="utf-8").splitlines()[-2000:]
        except OSError:
            return
        for ln in lines:
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            for r in rec.get("removed", []) or []:
                if isinstance(r, dict) and "file" in r:
                    self.reasons[r["file"]] = {**r, "time": rec.get("time"), "accuracy": rec.get("accuracy")}

    def signature(self) -> tuple:
        """Cheap fingerprint to notice that the bot/GUI changed something on disk."""
        sig = []
        for d in (self.pos_dir, self.neg_dir, self.quar_dir / "positives", self.quar_dir / "negatives"):
            try:
                sig.append(d.stat().st_mtime_ns)
            except OSError:
                sig.append(0)
        for f in ("review.json", "status.json", "ghost_labels_auto.json"):
            try:
                sig.append((self.smart / f).stat().st_mtime_ns)
            except OSError:
                sig.append(0)
        return tuple(sig)

    def status(self) -> dict:
        d = _read_json(self.smart / "status.json")
        return d if isinstance(d, dict) else {}

    # ------------------------------------------------------------ queries
    def counts(self) -> Dict[str, int]:
        c = {"pos": 0, "neg": 0, "quar": 0}
        for s in self.samples:
            c["quar" if s.quarantined else ("pos" if s.positive else "neg")] += 1
        return c

    def in_view(self, view: str) -> List[Sample]:
        if view == "quar":
            return [s for s in self.samples if s.quarantined]
        want = view == "pos"
        return [s for s in self.samples if not s.quarantined and s.positive == want]

    def tags(self, view: str) -> Counter:
        return Counter(s.tag or "?" for s in self.in_view(view))

    def query(self, view: str, sort: str, tag: Optional[str] = None, only_suspicious: bool = False,
              threshold: float = SUSPECT, label: Optional[str] = None,
              reason: Optional[str] = None) -> List[Sample]:
        items = self.in_view(view)
        if view == "quar" and reason:
            items = self.quarantined(reason, items)
        if label == NO_LABEL:
            items = [s for s in items if not s.ghost_label]
        elif label == AUTO_ONLY:
            items = [s for s in items if s.auto]
        elif label:
            items = [s for s in items if s.ghost_label == label]
        if tag:
            items = [s for s in items if (s.tag or "?") == tag]
        if only_suspicious:
            items = [s for s in items if s.suspicion >= threshold and not s.kept]
        if sort == "suspicious":
            items.sort(key=lambda s: (-(0.0 if s.kept else s.suspicion), -s.stamp, s.name))
        elif sort == "newest":
            items.sort(key=lambda s: (-s.stamp, s.name))
        elif sort == "oldest":
            items.sort(key=lambda s: (s.stamp, s.name))
        else:
            items.sort(key=lambda s: (-s.weight, s.name))
        return items

    def quarantined(self, reason: Optional[str] = None, pool: Optional[Sequence[Sample]] = None) -> List[Sample]:
        """Quarantined samples. reason: 'auto' = auto-clean put it there, 'manual' = anything else, None = all."""
        items = [s for s in (self.samples if pool is None else pool) if s.quarantined]
        if reason == "auto":
            return [s for s in items if s.name in self.reasons]
        if reason == "manual":
            return [s for s in items if s.name not in self.reasons]
        return items

    def suspects(self, threshold: float = SUSPECT) -> List[Sample]:
        return [s for s in self.samples if not s.quarantined and not s.kept and s.suspicion >= threshold]

    # ------------------------------------------------------------ mutations (all reversible except delete)
    def move(self, samples: Sequence[Sample], action: str, target: str = "original",
             protect: bool = True) -> Tuple[List[Tuple[Path, Path]], List[str], int]:
        """action: quarantine | restore | flip.

        For 'restore', `target` is 'original' (back where it came from), 'pos' or 'neg', and `protect`
        says whether the sample is also marked 'kept' so auto-clean leaves it alone (flip always protects).
        A sample is never overwritten: if the destination already has a file of that name it is skipped.
        Returns (moves, names newly marked 'kept', number skipped)."""
        moves: List[Tuple[Path, Path]] = []
        kept_new: List[str] = []
        skipped = 0
        for s in samples:
            if action == "quarantine" and not s.quarantined:
                dst = self.quar_dir / ("positives" if s.positive else "negatives") / s.name
            elif action == "restore" and s.quarantined:
                to_pos = s.positive if target == "original" else target == "pos"
                dst = (self.pos_dir if to_pos else self.neg_dir) / s.name
            elif action == "flip" and not s.quarantined:
                dst = (self.neg_dir if s.positive else self.pos_dir) / s.name
            else:
                continue
            if dst.exists():
                skipped += 1
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.replace(s.path, dst)
            except OSError:
                continue
            moves.append((s.path, dst))
            if (action == "flip" or (action == "restore" and protect)) and s.name not in self.keep:
                kept_new.append(s.name)
        if kept_new:
            self.keep.update(kept_new)
            self._save_keep()
        return moves, kept_new, skipped

    def undo(self, moves: Sequence[Tuple[Path, Path]], kept_new: Sequence[str]) -> int:
        n = 0
        for src, dst in reversed(list(moves)):
            try:
                os.replace(dst, src)
                n += 1
            except OSError:
                pass
        if kept_new:
            self.keep.difference_update(kept_new)
            self._save_keep()
        return n

    def delete(self, samples: Sequence[Sample]) -> int:
        n = 0
        for s in samples:
            try:
                s.path.unlink()
                n += 1
            except OSError:
                pass
        return n

    def _save_keep(self) -> None:
        # Same file/format the bot's SampleStore uses, so auto-clean honours the user's decisions.
        try:
            tmp = self.keep_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(sorted(self.keep)), encoding="utf-8")
            os.replace(tmp, self.keep_path)
        except OSError:
            pass

    @staticmethod
    def _write_json_atomic(path: Path, data) -> bool:
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
            os.replace(tmp, path)
            return True
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def _migrate_filename_references(self, names: Dict[str, str]) -> None:
        """Keep sidecar metadata attached to a sample when its weight changes its filename."""
        if not names:
            return
        # A manual protection marker must follow the renamed file.
        keep_data = _read_json(self.keep_path)
        if isinstance(keep_data, list):
            migrated = {names.get(str(name), str(name)) for name in keep_data}
            self._write_json_atomic(self.keep_path, sorted(migrated))

        # Manual/automatic ghost labels and explicit 'do not auto-label' markers use filenames as keys.
        for path in (self.labels_path, self.auto_path):
            data = _read_json(path)
            if isinstance(data, dict):
                changed = False
                for old, new in names.items():
                    if old in data:
                        value = data.pop(old)
                        data.setdefault(new, value)
                        changed = True
                if changed:
                    self._write_json_atomic(path, data)

        # The cross-validation scores are keyed by filename too.
        review_path = self.smart / "review.json"
        review = _read_json(review_path)
        if isinstance(review, dict):
            changed = False
            for group in ("pos", "neg"):
                values = review.get(group)
                if not isinstance(values, dict):
                    continue
                for old, new in names.items():
                    if old in values:
                        value = values.pop(old)
                        values.setdefault(new, value)
                        changed = True
            if changed:
                self._write_json_atomic(review_path, review)

        # Preserve auto-clean explanations for renamed quarantined samples.
        log_path = self.smart / "clean_log.jsonl"
        try:
            original = log_path.read_text(encoding="utf-8")
        except OSError:
            original = ""
        if original:
            changed_lines = []
            changed = False
            for line in original.splitlines():
                try:
                    record = json.loads(line)
                    for item in record.get("removed", []) or []:
                        if isinstance(item, dict) and item.get("file") in names:
                            item["file"] = names[item["file"]]
                            changed = True
                    changed_lines.append(json.dumps(record, ensure_ascii=False))
                except (ValueError, TypeError):
                    changed_lines.append(line)
            if changed:
                tmp = log_path.with_suffix(log_path.suffix + ".tmp")
                try:
                    tmp.write_text("\n".join(changed_lines) + "\n", encoding="utf-8")
                    os.replace(tmp, log_path)
                except OSError:
                    try:
                        tmp.unlink(missing_ok=True)
                    except OSError:
                        pass

    def set_weights(self, samples: Sequence[Sample], values: Dict[Path, float]) -> Tuple[List[Tuple[Path, Path]], int]:
        """Set sample weights by renaming PNGs in the filename format consumed by SampleStore.

        Allowed weights are deliberately bounded to avoid accidentally dominating the loss.
        Metadata keyed by sample filename is migrated with each successful rename.
        Returns (successful renames, skipped count).
        """
        moves: List[Tuple[Path, Path]] = []
        skipped = 0
        names: Dict[str, str] = {}
        for sample in samples:
            src = sample.path
            try:
                weight = float(values[src])
            except (KeyError, TypeError, ValueError):
                skipped += 1
                continue
            if not np.isfinite(weight) or not 0.05 <= weight <= 20.0 or not src.is_file():
                skipped += 1
                continue
            stem = re.sub(r"_w(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)$", "", src.stem, flags=re.IGNORECASE)
            dst = src.with_name(f"{stem}_w{weight:.2f}{src.suffix.lower()}")
            if dst == src:
                continue
            if dst.exists():
                skipped += 1
                continue
            try:
                os.replace(src, dst)
            except OSError:
                skipped += 1
                continue
            moves.append((src, dst))
            names[src.name] = dst.name
        self._migrate_filename_references(names)
        return moves, skipped

    def undo_weight_moves(self, moves: Sequence[Tuple[Path, Path]]) -> Tuple[int, int]:
        """Undo weight-renames without overwriting files created since the original edit."""
        names: Dict[str, str] = {}
        restored = skipped = 0
        for src, dst in reversed(list(moves)):
            if not dst.exists():
                skipped += 1
                continue
            if src.exists():
                skipped += 1
                continue
            try:
                os.replace(dst, src)
            except OSError:
                skipped += 1
                continue
            names[dst.name] = src.name
            restored += 1
        self._migrate_filename_references(names)
        return restored, skipped

    # ------------------------------------------------------------ ghost labels
    def label_counts(self, view: str) -> Counter:
        return Counter(s.ghost_label or NO_LABEL for s in self.in_view(view))

    def set_labels(self, samples: Sequence[Sample], key: Optional[str]) -> Dict[str, tuple]:
        """Give `samples` the label `key` (None clears it). Your decision always beats an auto-label, and
        clearing a label also stops the auto-labeller from putting one back. Returns the previous state for undo."""
        self._reload_labels()
        prev: Dict[str, tuple] = {}
        for s in samples:
            prev[s.name] = (self.labels.get(s.name), self.auto_labels.get(s.name), s.name in self.no_auto)
            self.auto_labels.pop(s.name, None)
            if key:
                self.labels[s.name] = key
                self.no_auto.discard(s.name)
            else:
                self.labels.pop(s.name, None)
                self.no_auto.add(s.name)
        self._save_labels()
        self._save_auto()
        return prev

    def restore_labels(self, prev: Dict[str, tuple]) -> int:
        self._reload_labels()
        for name, (mine, auto, no_auto) in prev.items():
            for table, old in ((self.labels, mine), (self.auto_labels, auto)):
                if old:
                    table[name] = old
                else:
                    table.pop(name, None)
            (self.no_auto.add if no_auto else self.no_auto.discard)(name)
        self._save_labels()
        self._save_auto()
        return len(prev)

    def clear_auto_labels(self) -> Dict[str, str]:
        """Remove every auto-label (yours stay). Returns what was removed, for undo."""
        self._reload_labels()
        removed = dict(self.auto_labels)
        self.auto_labels.clear()
        self._save_auto()
        return removed

    def restore_auto(self, removed: Dict[str, str]) -> int:
        self._reload_labels()
        for name, key in removed.items():
            if name not in self.labels:
                self.auto_labels[name] = key
        self._save_auto()
        return len(removed)

    def undo_auto_run(self, diff: Dict[str, Optional[str]]) -> int:
        """Undo one "Auto-label ghosts" run. `diff` maps file name -> the auto-label it had BEFORE the run
        (None = none). Only those files are touched; labels you made yourself are never changed."""
        self._reload_labels()
        n = 0
        for name, old in diff.items():
            if old:
                self.auto_labels[name] = old
            else:
                self.auto_labels.pop(name, None)
            n += 1
        self._save_auto()
        return n

    def _save_auto(self) -> None:
        try:
            tmp = self.auto_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.auto_labels, indent=0, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self.auto_path)
        except OSError:
            pass

    def _save_labels(self) -> None:
        # drop labels of files that no longer exist anywhere, then write atomically
        try:
            alive = {s.name for s in self.samples}
            for k in [k for k in list(self.labels) + list(self.no_auto) if k not in alive and not any(
                    (d / k).exists() for d in (self.pos_dir, self.neg_dir,
                                               self.quar_dir / "positives", self.quar_dir / "negatives"))]:
                self.labels.pop(k, None)
                self.no_auto.discard(k)
            tmp = self.labels_path.with_suffix(".tmp")
            data = dict(self.labels)
            data.update({k: "" for k in self.no_auto if k not in data})
            tmp.write_text(json.dumps(data, indent=0, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self.labels_path)
        except OSError:
            pass

    # ------------------------------------------------------------ explanations
    def explain(self, s: Sample) -> Tuple[str, str]:
        """(headline, detail) shown in the inspector. Colour is chosen by the caller."""
        if s.quarantined:
            r = self.reasons.get(s.name)
            if r:
                when = _ago(time.time() - float(r["time"])) if r.get("time") else "earlier"
                return ("Auto-clean quarantined this",
                        f"{when}. Cross-validated model said P(ghost) = {float(r.get('oof', 0)) * 100:.0f}%"
                        f" and {float(r.get('knn', 0)) * 100:.0f}% of its nearest neighbours carried the opposite label."
                        " Restore it if the label was right - it will then be protected from auto-clean.")
            return ("Quarantined", "Not used for training. Restore it to put it back (it is then protected from auto-clean).")
        if s.kept:
            return ("Protected by you", "You restored or relabelled this sample, so auto-clean will never remove it.")
        if s.score is None:
            return ("Not scored yet", "Run \"Auto-clean + retrain\" to get a cross-validated opinion on this sample.")
        pct = s.score * 100
        if s.positive and s.suspicion >= SUSPECT:
            return ("Probably NOT a ghost", f"Labelled ghost, but the model gives it only {pct:.0f}% ghost. "
                    "Likely a stray click or scenery - quarantine it if the picture is not a ghost.")
        if not s.positive and s.suspicion >= SUSPECT:
            return ("Probably a ghost", f"Labelled not-ghost, but the model gives it {pct:.0f}% ghost. "
                    "Flip it if the picture is a ghost.")
        if s.suspicion >= 0.4:
            return ("Uncertain", f"Model P(ghost) = {pct:.0f}%. Worth a look, not clearly wrong.")
        return ("Looks right", f"Model P(ghost) = {pct:.0f}% agrees with the label.")


# ================================================================== small widgets
class Tip:
    def __init__(self, widget, text: str):
        self.w, self.text, self.job, self.top = widget, text, None, None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _enter(self, _e=None):
        self._hide()
        self.job = self.w.after(550, self._show)

    def _show(self):
        try:
            self.top = tk.Toplevel(self.w)
            self.top.wm_overrideredirect(True)
            self.top.wm_geometry(f"+{self.w.winfo_rootx() + 8}+{self.w.winfo_rooty() + self.w.winfo_height() + 6}")
            tk.Label(self.top, text=self.text, bg=CARD, fg=TEXT, font=UI_S, padx=8, pady=4, justify="left",
                     wraplength=280, highlightthickness=1, highlightbackground=EDGE).pack()
        except Exception:
            self.top = None

    def _hide(self, _e=None):
        if self.job:
            try:
                self.w.after_cancel(self.job)
            except Exception:
                pass
            self.job = None
        if self.top is not None:
            try:
                self.top.destroy()
            except Exception:
                pass
            self.top = None


class Btn(tk.Label):
    """Flat button with hover, disabled state and variants (primary / danger / ghost)."""
    KINDS = {"primary": (ACCENT, ACCENT_DK, "#7df0d6"), "danger": ("#3a1c2a", RED, "#4d2336"),
             "ghost": (CARD, TEXT, HOVER), "quiet": (BG, MUTED, CARD)}

    def __init__(self, master, text: str, command: Callable[[], None], kind: str = "ghost", tip: str = ""):
        bg, fg, hov = self.KINDS[kind]
        super().__init__(master, text=text, bg=bg, fg=fg, font=UI_B if kind == "primary" else UI,
                         padx=12, pady=6, cursor="hand2")
        self._bg, self._fg, self._hov, self._cmd, self._on = bg, fg, hov, command, True
        self.bind("<Enter>", lambda e: self._on and self.configure(bg=self._hov))
        self.bind("<Leave>", lambda e: self.configure(bg=self._bg if self._on else CARD if self._bg != BG else BG))
        self.bind("<ButtonRelease-1>", self._click)
        if tip:
            Tip(self, tip)

    def _click(self, _e):
        if self._on:
            self._cmd()

    def enable(self, on: bool):
        self._on = on
        off_bg = BG if self._bg == BG else CARD
        self.configure(fg=self._fg if on else "#4a5a78", cursor="hand2" if on else "arrow",
                       bg=self._bg if on else off_bg)


class SplitBtn(tk.Frame):
    """A button with a main action and an arrow that opens a menu of variants.
    `build_menu()` is called each time the arrow is pressed, so the menu can show live counts."""

    def __init__(self, master, text: str, command: Callable[[], None], build_menu: Callable[[], tk.Menu],
                 kind: str = "primary", tip: str = ""):
        super().__init__(master, bg=BG)
        self._build_menu = build_menu
        self.main = Btn(self, text, command, kind, tip)
        self.main.pack(side="left")
        self.arrow = Btn(self, "\u25be", self.open_menu, kind, "More restore options")
        self.arrow.configure(padx=8)
        self.arrow.pack(side="left", padx=(1, 0))

    def open_menu(self):
        menu = self._build_menu()
        try:
            menu.tk_popup(self.winfo_rootx(), self.winfo_rooty() + self.winfo_height() + 2)
        finally:
            menu.grab_release()

    def enable(self, on: bool, menu_on: bool = True):
        self.main.enable(on)
        self.arrow.enable(menu_on)


class Dropdown(tk.Menubutton):
    """Select-one dropdown: options are (key, text) pairs."""

    def __init__(self, master, label: str, options: Sequence[Tuple[object, str]], on_select: Callable[[object], None],
                 value=None):
        super().__init__(master, bg=CARD, fg=TEXT, activebackground=HOVER, activeforeground=TEXT, relief="flat",
                         bd=0, padx=10, pady=5, font=UI, cursor="hand2", indicatoron=False,
                         highlightthickness=1, highlightbackground=EDGE)
        self.label, self.on_select, self.value, self.options = label, on_select, value, list(options)
        self._menu = tk.Menu(self, tearoff=0, bg=CARD, fg=TEXT, activebackground=ACCENT, activeforeground=ACCENT_DK,
                             bd=0, relief="flat", font=UI)
        self.configure(menu=self._menu)
        self.set_options(options, value)

    def set_options(self, options: Sequence[Tuple[object, str]], value=None):
        self.options = list(options)
        self._menu.delete(0, "end")
        for key, text in self.options:
            self._menu.add_command(label=text, command=lambda k=key: self._pick(k))
        keys = [k for k, _ in self.options]
        self.value = value if value in keys else (keys[0] if keys else None)
        self._text()

    def _text(self):
        t = next((t for k, t in self.options if k == self.value), "")
        self.configure(text=f"{self.label}: {t}  \u25be")

    def _pick(self, key):
        self.value = key
        self._text()
        self.on_select(key)

    def set(self, key):
        self.value = key
        self._text()


class MenuBtn(tk.Menubutton):
    """Button that opens a menu of commands. items: (text, command) or None for a separator."""

    def __init__(self, master, text: str, items: Sequence[Optional[Tuple[str, Callable[[], None]]]]):
        super().__init__(master, text=text + "  \u25be", bg=CARD, fg=TEXT, activebackground=HOVER,
                         activeforeground=TEXT, relief="flat", bd=0, padx=12, pady=6, font=UI, cursor="hand2",
                         indicatoron=False)
        m = tk.Menu(self, tearoff=0, bg=CARD, fg=TEXT, activebackground=ACCENT, activeforeground=ACCENT_DK,
                    bd=0, relief="flat", font=UI)
        for it in items:
            if it is None:
                m.add_separator()
            else:
                m.add_command(label=it[0], command=it[1])
        self.configure(menu=m)


class Chip(tk.Frame):
    def __init__(self, master, caption: str):
        super().__init__(master, bg=CARD, highlightthickness=1, highlightbackground=EDGE)
        self.val = tk.Label(self, text="-", bg=CARD, fg=TEXT, font=("Segoe UI", 13, "bold"), padx=12)
        self.val.pack(anchor="w", pady=(4, 0))
        tk.Label(self, text=caption, bg=CARD, fg=MUTED, font=UI_S, padx=12).pack(anchor="w", pady=(0, 5))

    def set(self, text: str, color: str = TEXT):
        self.val.configure(text=text, fg=color)


# ================================================================== the window
class SampleManager(tk.Toplevel):
    def __init__(self, master, project: Path, request: Callable[[str], None]):
        super().__init__(master)
        self.title("BLOOP - Sample manager")
        self.configure(bg=BG)
        self.geometry("1220x780")
        self.minsize(940, 580)
        self.lib = SampleLibrary(Path(project) / "smart")
        self.request = request
        self.changed = False
        # view state
        self.view = "pos"
        self.sort = "suspicious"
        self.tag: Optional[str] = None
        self.label_filter: Optional[str] = None
        self.only_susp = False
        self.reason: Optional[str] = None          # quarantine filter: None | 'auto' | 'manual'
        self.thumb = THUMB_DEFAULT
        self.page = 0
        self.items: List[Sample] = []
        self.selected: Set[Path] = set()
        self.cols = 1
        # internals
        self._cache: "OrderedDict[tuple, tk.PhotoImage]" = OrderedDict()
        self._cell_ids: Dict[int, dict] = {}
        self._page_items: List[Sample] = []
        self._render_token = 0
        self._anchor: Optional[int] = None
        self._paint: Optional[bool] = None
        self._paint_last: Optional[int] = None
        self._undo: List[Tuple[str, list, list]] = []
        self._bgq: "queue.Queue" = queue.Queue()
        self._busy = False
        self._await: Optional[Tuple[str, float]] = None
        self._sig = self.lib.signature()
        self._warned_disk = False
        self._toast_job = None
        self._resize_job = None
        self._last_w = 0
        self._insp_photo = None
        self._tick_job = None
        self._banner_on = False
        self._reason_on = False
        self._rmenu: Optional[tk.Menu] = None
        self._n_quar = 0
        self._insp_for: Optional[Path] = None
        self._build()
        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.refresh()
        self._tick_job = self.after(1500, self._tick)
        self.after(60, self._poll_bg)

    # ------------------------------------------------------------ layout
    def _build(self):
        # header: title + stat chips
        head = self.head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(head, text="Sample manager", bg=BG, fg=TEXT, font=("Segoe UI", 15, "bold")).pack(side="left")
        tk.Label(head, text="what BLOOP has learned - review, fix, retrain", bg=BG, fg=MUTED, font=UI).pack(
            side="left", padx=12, pady=(6, 0))
        chips = tk.Frame(head, bg=BG)
        chips.pack(side="right")
        self.chip_pos, self.chip_neg, self.chip_quar = Chip(chips, "ghosts"), Chip(chips, "not ghosts"), Chip(chips, "quarantined")
        self.chip_acc = Chip(chips, "cross-val accuracy")
        self.chip_model = Chip(chips, "model precision / recall")
        for c in (self.chip_pos, self.chip_neg, self.chip_quar, self.chip_acc, self.chip_model):
            c.pack(side="left", padx=3)

        # smart banner (shown only when something looks mislabelled)
        self.banner = tk.Frame(self, bg="#3a2a14", highlightthickness=1, highlightbackground="#6a4a1c")
        self.banner_lbl = tk.Label(self.banner, text="", bg="#3a2a14", fg=ORANGE, font=UI_B, anchor="w")
        self.banner_lbl.pack(side="left", padx=12, pady=7)
        Btn(self.banner, "Review them", self._review_suspects, "primary").pack(side="right", padx=8, pady=4)

        # toolbar: views, filters, paging
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=14, pady=(8, 6))
        self.tabs: Dict[str, tk.Label] = {}
        seg = tk.Frame(bar, bg=EDGE, padx=1, pady=1)
        seg.pack(side="left")
        for key, text in VIEWS:
            lb = tk.Label(seg, text=text, bg=CARD, fg=MUTED, font=UI_B, padx=14, pady=6, cursor="hand2")
            lb.pack(side="left")
            lb.bind("<Button-1>", lambda e, k=key: self._set_view(k))
            self.tabs[key] = lb
        self.dd_sort = Dropdown(bar, "Sort", SORTS, self._set_sort, self.sort)
        self.dd_sort.pack(side="left", padx=(10, 4))
        self.dd_tag = Dropdown(bar, "Source", [(None, "All")], self._set_tag, None)
        self.dd_tag.pack(side="left", padx=4)
        self.dd_label = Dropdown(bar, "Label", [(None, "All")], self._set_label_filter, None)
        self.dd_label.pack(side="left", padx=4)
        self.dd_reason = Dropdown(bar, "Reason", [(None, "All")], self._set_reason, None)     # shown in Quarantine only
        self.btn_susp = Btn(bar, "Suspicious only", self._toggle_susp, "ghost",
                            tip="Show only samples the model thinks are mislabelled (>= 70%).")
        self.btn_susp.pack(side="left", padx=4)
        nav = tk.Frame(bar, bg=BG)
        nav.pack(side="right")
        self.size_var = tk.IntVar(value=self.thumb)
        sz = tk.Scale(nav, from_=THUMB_MIN, to=THUMB_MAX, resolution=8, orient="horizontal", length=96, showvalue=False,
                      variable=self.size_var, bg=BG, fg=TEXT, troughcolor=CARD, highlightthickness=0, bd=0,
                      activebackground=ACCENT, sliderrelief="flat", command=self._on_size)
        sz.pack(side="left", padx=(0, 12))
        Tip(sz, "Thumbnail size (Ctrl + mouse wheel also works)")
        Btn(nav, "\u2039", lambda: self._turn(-1), "ghost").pack(side="left")
        self.page_lbl = tk.Label(nav, text="1 / 1", bg=BG, fg=TEXT, font=UI_B, width=9)
        self.page_lbl.pack(side="left")
        Btn(nav, "\u203a", lambda: self._turn(1), "ghost").pack(side="left")

        # body: grid + inspector
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=14, pady=4)
        self.insp = tk.Frame(body, bg=PANEL, width=268, highlightthickness=1, highlightbackground=EDGE)
        self.insp.pack(side="right", fill="y", padx=(10, 0))
        self.insp.pack_propagate(False)
        self._build_inspector()
        gridbox = tk.Frame(body, bg=PANEL, highlightthickness=1, highlightbackground=EDGE)
        gridbox.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(gridbox, bg=PANEL, highlightthickness=0)
        sb = tk.Scrollbar(gridbox, orient="vertical", command=self.canvas.yview, bg=CARD, troughcolor=PANEL,
                          activebackground=HOVER, bd=0, highlightthickness=0)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_hover)
        self.canvas.bind("<Leave>", lambda e: self._show_inspector(None))
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-3>", self._on_context)
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))

        # action bar
        act = tk.Frame(self, bg=BG)
        act.pack(fill="x", padx=14, pady=(6, 4))
        self.sel_menu = MenuBtn(act, "Select", [
            ("This page          Ctrl+A", lambda: self._select_page(True)),
            ("Everything in this view", self._select_all_items),
            ("Suspicious (\u2265 70%)", lambda: self._select_susp(SUSPECT)),
            ("Very suspicious (\u2265 90%)", lambda: self._select_susp(VERY_SUSPECT)),
            ("Invert this page", self._invert_page),
            None,
            ("Clear selection      Esc", self._clear_selection)])
        self.sel_menu.pack(side="left", padx=(0, 8))
        self.sel_lbl = tk.Label(act, text="Nothing selected", bg=BG, fg=MUTED, font=UI, width=24, anchor="w")
        self.sel_lbl.pack(side="left")
        self.btn_quar = Btn(act, "Quarantine", self._quarantine, "primary", "Move out of training (undoable).  Del")
        self.btn_restore = SplitBtn(act, "Restore", self._restore, self._restore_menu, "primary",
                                    "Put the selection back where it came from and protect it from auto-clean.  R\n"
                                    "Use the arrow for more: as ghost / not ghost, with a label, or a whole group.")
        self.btn_flip = Btn(act, "Flip label", self._flip, "ghost", "Ghost \u2194 not ghost. Protected from auto-clean.  F")
        self.btn_weight = Btn(act, "Weight…", self._edit_weights, "ghost",
                              "Edit the training weight of selected images, individually or as a bulk multiplier.")
        self.btn_del = Btn(act, "Delete\u2026", self._delete, "danger", "Permanent. Quarantine is the reversible option.")
        self.btn_undo = Btn(act, "Undo", self._undo_last, "quiet", "Ctrl+Z")
        self.lab_menu = MenuBtn(act, "Label", self._label_menu_items())
        self.ctx = tk.Menu(self, tearoff=0, bg=CARD, fg=TEXT, activebackground=ACCENT, activeforeground=ACCENT_DK,
                           bd=0, relief="flat", font=UI)
        for it in self._label_menu_items():
            if it is None:
                self.ctx.add_separator()
            else:
                self.ctx.add_command(label=it[0], command=it[1])
        self.btn_del.pack(side="left", padx=3)
        self.btn_weight.pack(side="left", padx=3, before=self.btn_del)
        self.lab_menu.pack(side="left", padx=(12, 3), before=self.btn_weight)
        Tip(self.lab_menu, "Say what kind of ghost this is (small / boss + colour). Keys: 1-4 small, Alt+1..7 boss, 0 clears.")
        self.btn_undo.pack(side="left", padx=(12, 3))     # quarantine/flip/restore are packed by _update_actions

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", padx=14, pady=(2, 12))
        Btn(foot, "Auto-clean + retrain", lambda: self._ask("clean"), "ghost",
            "Cross-validate, quarantine labels that the model AND nearest neighbours reject, then retrain.").pack(side="left", padx=(0, 3))
        Btn(foot, "Retrain", lambda: self._ask("retrain"), "ghost").pack(side="left", padx=3)
        Btn(foot, "Auto-label ghosts", self._auto_label, "primary",
            "Label the unlabelled ghost samples for you - only the ones the model is sure about, once your own labels are good enough. "
            "The bot does this by itself too.").pack(side="left", padx=3)
        Btn(foot, "Clear auto-labels", self._clear_auto, "quiet",
            "Remove every automatic label (yours stay). Undoable.").pack(side="left", padx=3)
        Btn(foot, "Remove duplicates", self._remove_duplicates, "ghost",
            "Delete near-identical copies in this view's folder (keeps the highest weight).").pack(side="left", padx=3)
        Btn(foot, "Export selected…", self._export_selected, "quiet",
            "Save copies of selected PNGs to another folder; originals stay in their current folder, including quarantine.").pack(side="left", padx=3)
        Btn(foot, "Refresh", self.refresh, "quiet", "F5").pack(side="left", padx=3)
        Btn(foot, "Open folder", self._open_folder, "quiet").pack(side="left", padx=3)
        self.status = tk.Label(foot, text="", bg=BG, fg=ACCENT, font=UI, anchor="e")
        self.status.pack(side="right", fill="x", expand=True)

    def _build_inspector(self):
        tk.Label(self.insp, text="INSPECTOR", bg=PANEL, fg=MUTED, font=UI_S).pack(anchor="w", padx=12, pady=(10, 4))
        self.insp_img = tk.Label(self.insp, bg="#181818", width=232, height=232)
        self.insp_img.pack(padx=12)
        self.insp_title = tk.Label(self.insp, text="Hover a sample", bg=PANEL, fg=TEXT, font=("Segoe UI", 11, "bold"),
                                   anchor="w", wraplength=240, justify="left")
        self.insp_title.pack(fill="x", padx=12, pady=(10, 0))
        self.meter = tk.Canvas(self.insp, width=240, height=8, bg=EDGE, highlightthickness=0)
        self.meter.pack(padx=12, pady=(6, 2))
        self.insp_verdict = tk.Label(self.insp, text="", bg=PANEL, fg=MUTED, font=UI, anchor="w", wraplength=240,
                                     justify="left")
        self.insp_verdict.pack(fill="x", padx=12, pady=(4, 6))
        self.insp_meta = tk.Label(self.insp, text="", bg=PANEL, fg=MUTED, font=MONO, anchor="w", justify="left")
        self.insp_meta.pack(fill="x", padx=12)
        self.insp_tag = tk.Label(self.insp, text="", bg=PANEL, fg=MUTED, font=UI_S, anchor="w", wraplength=240,
                                 justify="left")
        self.insp_tag.pack(fill="x", padx=12, pady=(6, 0))
        self.insp_lab = tk.Label(self.insp, text="", bg=PANEL, fg=MUTED, font=UI_B, anchor="w", wraplength=240,
                                 justify="left")
        self.insp_lab.pack(fill="x", padx=12, pady=(8, 0))

    def _bind_keys(self):
        def guard(fn):
            return lambda e: fn() if not isinstance(e.widget, tk.Entry) else None
        self.bind("<Control-a>", guard(lambda: self._select_page(True)))
        self.bind("<Escape>", guard(self._clear_selection))
        self.bind("<Delete>", guard(self._delete_key))
        self.bind("<Key-r>", guard(self._restore))
        self.bind("<Key-g>", guard(lambda: self._restore_as("pos")))
        self.bind("<Key-n>", guard(lambda: self._restore_as("neg")))
        self.bind("<Key-f>", guard(self._flip))
        self.bind("<Control-z>", guard(self._undo_last))
        self.bind("<Prior>", guard(lambda: self._turn(-1)))
        self.bind("<Next>", guard(lambda: self._turn(1)))
        self.bind("<F5>", guard(self.refresh))
        for i, (key, _t) in enumerate(GHOST_LABELS):
            if key.startswith("small_"):
                n = i + 1
                self.bind(f"<Key-{n}>", guard(lambda k=key: self._label(k)))
                self.bind(f"<KP_{n}>", guard(lambda k=key: self._label(k)))
            else:
                n = i - 3
                self.bind(f"<Alt-Key-{n}>", guard(lambda k=key: self._label(k)))
        self.bind("<Key-0>", guard(lambda: self._label(None)))
        self.bind("<KP_0>", guard(lambda: self._label(None)))

    # ------------------------------------------------------------ toast
    def toast(self, msg: str, kind: str = "ok", ms: int = 6500):
        color = {"ok": ACCENT, "warn": ORANGE, "err": RED, "info": MUTED}.get(kind, ACCENT)
        self.status.configure(text=msg, fg=color)
        if self._toast_job:
            try:
                self.after_cancel(self._toast_job)
            except Exception:
                pass
        self._toast_job = self.after(ms, lambda: self.status.configure(text=""))

    # ------------------------------------------------------------ data refresh
    def refresh(self):
        self.lib.scan()
        self._sig = self.lib.signature()
        self._warned_disk = False
        self._rebuild()

    def _rebuild(self, keep_scroll: bool = False):
        counts = self.lib.counts()
        tag_counts = self.lib.tags(self.view)
        if self.tag and self.tag not in tag_counts:
            self.tag = None
        self.dd_tag.set_options([(None, "All")] + [(t, f"{t} ({n})") for t, n in sorted(tag_counts.items())], self.tag)
        lcounts = self.lib.label_counts(self.view)
        lopts = [(None, "All"), (NO_LABEL, f"Not labelled ({lcounts.get(NO_LABEL, 0)})")]
        n_auto = sum(1 for s in self.lib.in_view(self.view) if s.auto)
        if n_auto:
            lopts.append((AUTO_ONLY, f"Auto-labelled ({n_auto})"))
        lopts += [(k, f"{t} ({lcounts[k]})") for k, t in GHOST_LABELS if lcounts.get(k)]
        if self.label_filter not in [k for k, _ in lopts]:
            self.label_filter = None
        self.dd_label.set_options(lopts, self.label_filter)
        if self.view == "quar":
            quar = self.lib.quarantined()
            n_auto = sum(1 for s in quar if s.name in self.lib.reasons)
            ropts = [(None, f"All ({len(quar)})"), ("auto", f"Auto-clean ({n_auto})"),
                     ("manual", f"By you / older ({len(quar) - n_auto})")]
            if self.reason not in [k for k, _ in ropts]:
                self.reason = None
            self.dd_reason.set_options(ropts, self.reason)
            if not self._reason_on:
                self.dd_reason.pack(side="left", padx=4, after=self.dd_label)
                self._reason_on = True
        elif self._reason_on:
            self.dd_reason.pack_forget()
            self._reason_on = False
        self._n_quar = counts["quar"]
        self.items = self.lib.query(self.view, self.sort, self.tag, self.only_susp, label=self.label_filter,
                                    reason=self.reason if self.view == "quar" else None)
        live = {s.path for s in self.items}
        self.selected &= live
        pages = max(1, (len(self.items) + PAGE - 1) // PAGE)
        self.page = max(0, min(self.page, pages - 1))
        self.page_lbl.configure(text=f"{self.page + 1} / {pages}")
        for key, text in VIEWS:
            on = key == self.view
            self.tabs[key].configure(text=f"{text}  {counts[key]}", bg=ACCENT if on else CARD,
                                     fg=ACCENT_DK if on else MUTED)
        self.chip_pos.set(str(counts["pos"]), GREEN)
        self.chip_neg.set(str(counts["neg"]), TEXT)
        self.chip_quar.set(str(counts["quar"]), ORANGE if counts["quar"] else MUTED)
        acc = self.lib.accuracy
        self.chip_acc.set(f"{acc * 100:.0f}%" if acc is not None else "-", GREEN if (acc or 0) >= 0.9 else (ORANGE if acc else MUTED))
        m = self.lib.status().get("metrics", {}) or {}
        if "val_precision" in m:
            self.chip_model.set(f"{m['val_precision'] * 100:.0f}% / {m.get('val_recall', 0) * 100:.0f}%", TEXT)
        else:
            self.chip_model.set("-", MUTED)
        self.btn_susp.configure(bg=ORANGE if self.only_susp else CARD, fg=ACCENT_DK if self.only_susp else TEXT)
        self.btn_susp._bg = ORANGE if self.only_susp else CARD
        self._insp_for = None
        self._update_banner()
        self._render(keep_scroll)
        self._update_actions()

    def _update_banner(self):
        sus = self.lib.suspects()
        if sus and self.view != "quar" and not self.only_susp:
            n_pos = sum(1 for s in sus if s.positive)
            n_neg = len(sus) - n_pos
            parts = []
            if n_pos:
                parts.append(f"{n_pos} \"ghost\" sample(s) that look like scenery")
            if n_neg:
                parts.append(f"{n_neg} \"not ghost\" sample(s) that look like ghosts")
            self.banner_lbl.configure(text="\u26a0  " + " and ".join(parts) + " - probably mislabelled")
            if not self._banner_on:
                self.banner.pack(fill="x", padx=14, pady=(2, 0), after=self.head)
                self._banner_on = True
        elif self._banner_on:
            self.banner.pack_forget()
            self._banner_on = False

    # ------------------------------------------------------------ view controls
    def _set_view(self, key: str):
        if key == self.view:
            return
        self.view, self.page, self.tag, self.only_susp, self.label_filter = key, 0, None, False, None
        self.reason = None
        self.selected.clear()
        self._rebuild()

    def _set_sort(self, key):
        self.sort, self.page = key, 0
        self._rebuild()

    def _set_tag(self, key):
        self.tag, self.page = key, 0
        self._rebuild()

    def _set_label_filter(self, key):
        self.label_filter, self.page = key, 0
        self._rebuild()

    def _set_reason(self, key):
        self.reason, self.page = key, 0
        self._rebuild()

    def _toggle_susp(self):
        self.only_susp, self.page = not self.only_susp, 0
        if self.only_susp:
            self.sort = "suspicious"
            self.dd_sort.set("suspicious")
        self._rebuild()

    def _review_suspects(self):
        sus = self.lib.suspects()
        if not sus:
            return
        view = "pos" if sum(1 for s in sus if s.positive) >= len(sus) / 2 else "neg"
        self.view, self.page, self.tag, self.only_susp, self.sort = view, 0, None, True, "suspicious"
        self.dd_sort.set("suspicious")
        self.selected.clear()
        self._rebuild()
        self.toast("Showing only suspicious samples - select the wrong ones, then Quarantine (or Flip).", "info", 9000)

    def _turn(self, d: int):
        pages = max(1, (len(self.items) + PAGE - 1) // PAGE)
        new = max(0, min(pages - 1, self.page + d))
        if new != self.page:
            self.page = new
            self._rebuild()

    # ------------------------------------------------------------ thumbnails & rendering
    def _photo(self, s: Sample, size: int) -> Optional[tk.PhotoImage]:
        key = (s.name, size)
        hit = self._cache.get(key)
        if hit is not None:
            self._cache.move_to_end(key)
            return hit
        got = read_sample_image(s.path)
        if got is None:
            return None
        ok, buf = cv2.imencode(".png", fit_square(got[0], size))
        if not ok:
            return None
        photo = tk.PhotoImage(data=base64.b64encode(buf.tobytes()).decode("ascii"))
        self._cache[key] = photo
        while len(self._cache) > 900:
            self._cache.popitem(last=False)
        return photo

    def _geom(self):
        w = max(self.canvas.winfo_width(), 240)
        self.cols = max(1, (w - PAD) // (self.thumb + PAD))

    def _xy(self, idx: int) -> Tuple[int, int]:
        return PAD + (idx % self.cols) * (self.thumb + PAD), PAD + (idx // self.cols) * (self.thumb + PAD + CAP)

    def _render(self, keep_scroll: bool = False):
        frac = self.canvas.yview()[0] if keep_scroll else 0.0
        self._render_token += 1
        self.canvas.delete("all")
        self._cell_ids = {}
        self._geom()
        self._page_items = self.items[self.page * PAGE:(self.page + 1) * PAGE]
        if not self._page_items:
            msg = {"quar": "Nothing in quarantine.", "pos": "No ghost samples here.", "neg": "No not-ghost samples here."}[self.view]
            if self.only_susp or self.tag:
                msg += "\nNo samples match the current filter."
            self.canvas.create_text(max(self.canvas.winfo_width(), 240) // 2, 90, text=msg, fill=MUTED, font=UI,
                                    justify="center")
            self.canvas.configure(scrollregion=(0, 0, 1, 1))
            return
        self._draw_chunk(0, self._render_token, frac)

    def _draw_chunk(self, start: int, token: int, frac: float):
        if token != self._render_token:
            return
        end = min(len(self._page_items), start + 36)
        for idx in range(start, end):
            self._draw_cell(idx)
        rows = (len(self._page_items) + self.cols - 1) // self.cols
        self.canvas.configure(scrollregion=(0, 0, self.cols * (self.thumb + PAD) + PAD,
                                            PAD + rows * (self.thumb + PAD + CAP)))
        if end < len(self._page_items):
            self.after(1, lambda: self._draw_chunk(end, token, frac))
        elif frac:
            self.canvas.yview_moveto(frac)

    def _draw_cell(self, idx: int):
        s = self._page_items[idx]
        x, y = self._xy(idx)
        t = self.thumb
        c = self.canvas
        card = c.create_rectangle(x - 3, y - 3, x + t + 3, y + t + CAP, fill=CARD, outline=CARD, width=2)
        photo = self._photo(s, t)
        if photo is not None:
            c.create_image(x, y, image=photo, anchor="nw")
        else:
            c.create_text(x + t // 2, y + t // 2, text="unreadable", fill=RED, font=UI_S)
        if s.suspicion > 0.05 and not s.kept:
            col = RED if s.suspicion >= SUSPECT else (ORANGE if s.suspicion >= 0.4 else MUTED)
            c.create_rectangle(x, y + t - 4, x + max(3, int(t * s.suspicion)), y + t, fill=col, outline="")
        tag_col = TAG_INFO.get(s.tag, (MUTED, ""))[0]
        c.create_text(x + t // 2, y + t + CAP // 2 + 1, text=f"{s.tag or '?'}  w{s.weight:.1f}" + ("  \u2713" if s.kept else ""),
                      fill=tag_col, font=MONO)
        if s.ghost_label:
            lc = label_color(s.ghost_label)
            c.create_rectangle(x, y, x + 15, y + 15, fill=lc, outline="#ffffff" if s.auto else "#000000")
            letter = "B" if s.ghost_label.startswith("boss") else "S"
            c.create_text(x + 8, y + 8, text=letter.lower() if s.auto else letter,
                          fill="#000000", font=("Segoe UI", 8, "bold"))
        badge = c.create_oval(x + t - 18, y + 4, x + t - 4, y + 18, fill=ACCENT, outline=ACCENT_DK, state="hidden")
        tick = c.create_text(x + t - 11, y + 11, text="\u2713", fill=ACCENT_DK, font=("Segoe UI", 8, "bold"), state="hidden")
        self._cell_ids[idx] = {"card": card, "badge": badge, "tick": tick}
        self._paint_cell(idx)

    def _paint_cell(self, idx: int):
        ids = self._cell_ids.get(idx)
        if not ids:
            return
        on = self._page_items[idx].path in self.selected
        self.canvas.itemconfigure(ids["card"], outline=ACCENT if on else CARD, fill=HOVER if on else CARD)
        st = "normal" if on else "hidden"
        self.canvas.itemconfigure(ids["badge"], state=st)
        self.canvas.itemconfigure(ids["tick"], state=st)

    def _on_resize(self, e):
        if abs(e.width - self._last_w) < (self.thumb + PAD) // 2:
            return
        self._last_w = e.width
        if self._resize_job:
            try:
                self.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.after(90, lambda: self._render(True))

    def _on_size(self, v):
        new = int(float(v))
        if new == self.thumb:
            return
        self.thumb = new
        if self._resize_job:
            try:
                self.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.after(120, lambda: self._render(True))

    def _on_wheel(self, e):
        if e.state & 0x4:      # Ctrl + wheel = zoom
            self.size_var.set(max(THUMB_MIN, min(THUMB_MAX, self.thumb + (8 if e.delta > 0 else -8))))
            self._on_size(self.size_var.get())
        else:
            self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")

    # ------------------------------------------------------------ mouse interaction
    def _idx_at(self, ex: int, ey: int) -> Optional[int]:
        x, y = self.canvas.canvasx(ex), self.canvas.canvasy(ey)
        col = int((x - PAD // 2) // (self.thumb + PAD))
        row = int((y - PAD // 2) // (self.thumb + PAD + CAP))
        if col < 0 or row < 0 or col >= self.cols:
            return None
        idx = row * self.cols + col
        return idx if idx < len(self._page_items) else None

    def _set_range(self, a: int, b: int, on: bool):
        lo, hi = min(a, b), max(a, b)
        for i in range(lo, hi + 1):
            p = self._page_items[i].path
            if on:
                self.selected.add(p)
            else:
                self.selected.discard(p)
            self._paint_cell(i)

    def _on_press(self, e):
        self.canvas.focus_set()
        idx = self._idx_at(e.x, e.y)
        if idx is None:
            return
        if (e.state & 0x1) and self._anchor is not None and self._anchor < len(self._page_items):
            self._set_range(self._anchor, idx, True)
            self._paint = None
        else:
            self._paint = self._page_items[idx].path not in self.selected
            self._set_range(idx, idx, self._paint)
            self._anchor = idx
            self._paint_last = idx
        self._update_actions()

    def _on_drag(self, e):
        if self._paint is None:
            return
        idx = self._idx_at(e.x, e.y)
        if idx is None or idx == self._paint_last:
            return
        self._set_range(self._paint_last if self._paint_last is not None else idx, idx, self._paint)
        self._paint_last = idx
        self._update_actions()

    def _on_release(self, _e):
        self._paint = None

    def _on_hover(self, e):
        idx = self._idx_at(e.x, e.y)
        self._show_inspector(self._page_items[idx] if idx is not None else None)

    # ------------------------------------------------------------ inspector
    def _show_inspector(self, s: Optional[Sample]):
        key = s.path if s is not None else None
        if key == self._insp_for:
            return                                  # same sample: don't re-read the image on every mouse move
        self._insp_for = key
        if s is None:
            self.insp_img.configure(image="")
            self._insp_photo = None
            self.insp_title.configure(text="Hover a sample", fg=MUTED)
            self.meter.delete("all")
            self.insp_verdict.configure(text="Hover a thumbnail to see what it is and why it may be mislabelled.\n\n"
                                             "Click or drag to select. Shift+click selects a range.")
            self.insp_meta.configure(text="")
            self.insp_tag.configure(text="")
            self.insp_lab.configure(text="")
            return
        got = read_sample_image(s.path)
        if got is not None:
            ok, buf = cv2.imencode(".png", fit_square(got[0], 232))
            if ok:
                self._insp_photo = tk.PhotoImage(data=base64.b64encode(buf.tobytes()).decode("ascii"))
                self.insp_img.configure(image=self._insp_photo)
        head, detail = self.lib.explain(s)
        col = RED if (s.suspicion >= SUSPECT and not s.kept and not s.quarantined) else (
            ORANGE if (s.suspicion >= 0.4 or s.quarantined) and not s.kept else GREEN)
        self.insp_title.configure(text=f"{s.label}  \u00b7  {head}", fg=col)
        self.meter.delete("all")
        if s.score is not None and not s.quarantined:
            self.meter.create_rectangle(0, 0, int(240 * s.suspicion), 8, fill=col, outline="")
        self.insp_verdict.configure(text=detail)
        w = h = "?"
        got_size = got[1] if got else None
        if got_size:
            w, h = got_size
        age = _ago(s.age_s) if s.age_s is not None else "unknown"
        self.insp_meta.configure(text=f"size    {w}x{h}\nweight  {s.weight:.2f}\nadded   {age}\n"
                                      f"state   {'quarantined' if s.quarantined else ('protected' if s.kept else 'active')}")
        tcol, thelp = TAG_INFO.get(s.tag, (MUTED, "Unknown source."))
        self.insp_tag.configure(text=f"\u25cf {s.tag or '?'}: {thelp}", fg=tcol)
        if s.ghost_label:
            self.insp_lab.configure(text=f"Label: {LABEL_TEXT[s.ghost_label]}"
                                         + ("\n(automatic - select it and press a label key to overrule)" if s.auto else ""),
                                    fg=label_color(s.ghost_label))
        elif s.positive and not s.quarantined:
            self.insp_lab.configure(text="Not labelled yet  (1-4 small, Alt+1..7 boss)", fg=MUTED)
        elif s.quarantined:
            self.insp_lab.configure(text=f"R restores it to: {DEST_TEXT['pos' if s.positive else 'neg']}\n"
                                         "G / N restore it as ghost / not ghost.", fg=MUTED)
        else:
            self.insp_lab.configure(text="")

    # ------------------------------------------------------------ selection helpers
    def _select_page(self, on: bool):
        for p in (s.path for s in self._page_items):
            (self.selected.add if on else self.selected.discard)(p)
        for i in self._cell_ids:
            self._paint_cell(i)
        self._update_actions()

    def _select_all_items(self):
        self.selected = {s.path for s in self.items}
        for i in self._cell_ids:
            self._paint_cell(i)
        self._update_actions()

    def _select_susp(self, thr: float):
        self.selected = {s.path for s in self.items if s.suspicion >= thr and not s.kept}
        for i in self._cell_ids:
            self._paint_cell(i)
        self._update_actions()
        if not self.selected:
            self.toast("No samples at that suspicion level.", "info")

    def _invert_page(self):
        for s in self._page_items:
            if s.path in self.selected:
                self.selected.discard(s.path)
            else:
                self.selected.add(s.path)
        for i in self._cell_ids:
            self._paint_cell(i)
        self._update_actions()

    def _clear_selection(self):
        self.selected.clear()
        for i in self._cell_ids:
            self._paint_cell(i)
        self._update_actions()

    def _chosen(self) -> List[Sample]:
        return [s for s in self.items if s.path in self.selected]

    def _update_actions(self):
        n = len(self.selected)
        quar_view = self.view == "quar"
        on_page = sum(1 for s in self._page_items if s.path in self.selected)
        if n == 0:
            self.sel_lbl.configure(text="Nothing selected", fg=MUTED)
        else:
            extra = f"  ({n - on_page} on other pages)" if n > on_page else ""
            self.sel_lbl.configure(text=f"{n} selected{extra}", fg=ACCENT)
        self.btn_quar.enable(n > 0 and not quar_view)
        self.btn_flip.enable(n > 0 and not quar_view)
        self.btn_restore.enable(n > 0 and quar_view, menu_on=self._n_quar > 0)
        self.btn_del.enable(n > 0)
        self.btn_weight.enable(n > 0)
        self.lab_menu.configure(state="normal" if (n > 0 and self.view == "pos") else "disabled")
        for b in (self.btn_quar, self.btn_flip, self.btn_restore):
            b.pack_forget()
        for b in ((self.btn_restore,) if quar_view else (self.btn_quar, self.btn_flip)):
            b.pack(side="left", padx=3, before=self.lab_menu)
        self.btn_undo.enable(bool(self._undo))
        self.btn_undo.configure(text=f"Undo ({len(self._undo)})" if self._undo else "Undo")

    # ------------------------------------------------------------ actions
    def _apply(self, action: str, verb: str):
        chosen = self._chosen()
        if not chosen:
            return
        moves, kept_new, skipped = self.lib.move(chosen, action)
        if not moves:
            self.toast("Nothing was moved (same file name already at the destination, or files changed on disk). Press F5.",
                       "warn", 9000)
            self.refresh()
            return
        self._undo.append((action, moves, kept_new))
        del self._undo[:-30]
        self.changed = True
        self._commit()
        extra = " They are now protected from auto-clean." if action == "flip" else ""
        if skipped:
            extra += f" {skipped} skipped (same file name already at the destination)."
        self.toast(f"{len(moves)} {verb}.{extra}  Ctrl+Z to undo.", "warn" if skipped else "ok")

    def _commit(self):
        """After a change on disk: drop the selection, rescan and redraw (scroll position kept)."""
        self.selected.clear()
        self.lib.scan()
        self._sig = self.lib.signature()
        self._rebuild(keep_scroll=True)

    def _label_menu_items(self):
        items = [(t, (lambda k=k: self._label(k))) for k, t in GHOST_LABELS[:4]]
        items.append(None)
        items += [(t, (lambda k=k: self._label(k))) for k, t in GHOST_LABELS[4:]]
        items += [None, ("Clear label       0", lambda: self._label(None))]
        return items

    def _label(self, key: Optional[str]):
        if self.view != "pos":
            self.toast("Labels are for ghost samples: open the Ghosts tab.", "warn")
            return
        chosen = self._chosen()
        if not chosen:
            self.toast("Select some ghost thumbnails first, then pick a label.", "info")
            return
        prev = self.lib.set_labels(chosen, key)
        self._undo.append(("label", [prev], []))
        del self._undo[:-30]
        self.selected.clear()
        self.lib.scan()
        self._sig = self.lib.signature()
        self._rebuild(keep_scroll=True)
        what = LABEL_TEXT[key] if key else "no label"
        self.toast(f"{len(chosen)} sample(s) labelled: {what}.  The bot picks it up on its own.  Ctrl+Z to undo.")

    def _auto_label(self):
        project = self.lib.smart.parent
        self.toast("Auto-labelling ghosts...", "info", 60000)

        def job(progress):
            from ghost_classifier import ColorClassifier     # needs ghost_classifier.py next to this file
            cc = ColorClassifier(project)
            st = cc.auto_status()
            if not st["ready"]:
                return {"not_ready": True, "status": st}
            res = cc.auto_label_positives(progress=progress)
            res["status"] = st
            return res

        def done(res):
            if isinstance(res, Exception):
                self.toast(f"Auto-label failed: {res}", "err", 12000)
                return
            st = res["status"]
            if res.get("not_ready"):
                self.toast(f"Not enough to go on yet: {st['reason']}.", "warn", 15000)
                return
            before = dict(self.lib.auto_labels)              # state before this run (memory = last scan)
            self.refresh()
            after = dict(self.lib.auto_labels)
            diff = {k: before.get(k) for k, v in after.items() if before.get(k) != v}
            if diff:
                self._undo.append(("auto-label", [diff], []))
                del self._undo[:-30]
                self._update_actions()                       # refresh the Undo button
            n, left = res["labelled"], res["left"]
            msg = f"Auto-labelled {n} ghost sample(s) (model matches {st['accuracy'] * 100:.0f}% of your own labels)."
            if left:
                msg += f" {left} not sure enough - label those by hand."
            if st.get("weak"):
                msg += " Needs more of your labels: " + ", ".join(st["weak"][:4]) + "."
            if n:
                msg += "  Filter: Label > Auto-labelled.  Ctrl+Z to undo."
            self.toast(msg, "ok" if n else "info", 15000)

        self._run_bg(job, done)

    def _clear_auto(self):
        removed = self.lib.clear_auto_labels()
        if not removed:
            self.toast("There are no automatic labels to remove.", "info")
            return
        self._undo.append(("autoclear", [removed], []))
        del self._undo[:-30]
        self.selected.clear()
        self.lib.scan()
        self._sig = self.lib.signature()
        self._rebuild(keep_scroll=True)
        self.toast(f"{len(removed)} automatic label(s) removed. Your own labels are untouched.  Ctrl+Z to undo.")

    def _on_context(self, e):
        idx = self._idx_at(e.x, e.y)
        if idx is not None and self._page_items[idx].path not in self.selected:
            self.selected = {self._page_items[idx].path}
            for i in self._cell_ids:
                self._paint_cell(i)
            self._update_actions()
        if not self.selected and self.view != "quar":
            return
        if self.view == "pos":
            menu = self.ctx
        elif self.view == "quar":
            menu = self._restore_menu()
        else:
            return
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    def _quarantine(self):
        if self.view != "quar":
            self._apply("quarantine", "moved to quarantine")

    # ---- restore: one engine (_do_restore), several entry points (button, menu, keys, right-click)
    def _mk_menu(self, parent=None) -> tk.Menu:
        return tk.Menu(parent or self, tearoff=0, bg=CARD, fg=TEXT, activebackground=ACCENT, activeforeground=ACCENT_DK,
                       disabledforeground="#5b6b88", bd=0, relief="flat", font=UI)

    def _restore_menu(self) -> tk.Menu:
        """Menu with every way to restore. Built fresh each time so the counts are current."""
        if self._rmenu is not None:
            try:
                self._rmenu.destroy()
            except Exception:
                pass
        m = self._rmenu = self._mk_menu()
        n = len(self._chosen()) if self.view == "quar" else 0
        n_auto = len(self.lib.quarantined("auto"))
        n_manual = len(self.lib.quarantined("manual"))
        on = lambda ok: "normal" if ok else "disabled"      # noqa: E731

        m.add_command(label=f"SELECTION  \u00b7  {n} sample(s)" if n else "SELECTION  \u00b7  nothing selected", state="disabled")
        m.add_command(label="Restore to original list        R", state=on(n),
                      command=lambda: self._restore_selected("original"))
        m.add_command(label="Restore as Ghost        G", state=on(n), command=lambda: self._restore_selected("pos"))
        m.add_command(label="Restore as Not a ghost        N", state=on(n), command=lambda: self._restore_selected("neg"))
        sub = self._mk_menu(m)
        for key, text in GHOST_LABELS:
            sub.add_command(label=text, command=lambda k=key: self._restore_selected("pos", True, k))
        m.add_cascade(label="Restore as Ghost + label", menu=sub, state=on(n))
        m.add_command(label="Restore, but let auto-clean judge it again", state=on(n),
                      command=lambda: self._restore_selected("original", protect=False))
        m.add_separator()
        m.add_command(label="WHOLE QUARANTINE  (asks first)", state="disabled")
        m.add_command(label=f"Restore everything auto-clean removed  ({n_auto})", state=on(n_auto),
                      command=lambda: self._restore_scope("auto"))
        m.add_command(label=f"Restore everything removed by you / older  ({n_manual})", state=on(n_manual),
                      command=lambda: self._restore_scope("manual"))
        m.add_command(label=f"Restore everything shown here  ({len(self.items)})", state=on(self.items),
                      command=lambda: self._restore_scope("view"))
        return m

    def _restore(self):
        self._restore_selected("original")

    def _restore_as(self, target: str):
        self._restore_selected(target)

    def _restore_selected(self, target: str = "original", protect: bool = True, label: Optional[str] = None):
        if self.view != "quar":
            return
        chosen = self._chosen()
        if not chosen:
            self.toast("Select quarantined samples first - or open the \u25be next to Restore to restore a whole group.", "info", 8000)
            return
        self._do_restore(chosen, target, protect, label)

    def _restore_scope(self, kind: str):
        samples = list(self.items) if kind == "view" else self.lib.quarantined(kind)
        self._do_restore(samples, confirm=True)

    def _do_restore(self, samples: Sequence[Sample], target: str = "original", protect: bool = True,
                    label: Optional[str] = None, confirm: bool = False):
        """target: original | pos | neg.  protect: also mark 'kept' so auto-clean leaves them alone.
        label: ghost label to give the samples that end up in Ghosts (done as ONE undo step)."""
        samples = [s for s in samples if s.quarantined]
        if not samples:
            self.toast("Nothing to restore.", "info")
            return
        plan = Counter("pos" if (s.positive if target == "original" else target == "pos") else "neg" for s in samples)
        if confirm or len(samples) >= BULK_CONFIRM:
            lines = [f"Restore {len(samples)} sample(s)?", ""]
            lines += [f"    {plan[k]}  \u2192  {DEST_TEXT[k]}" for k in ("pos", "neg") if plan[k]]
            if label and plan["pos"]:
                lines.append(f"\nGhosts get the label: {LABEL_TEXT[label]}")
            lines.append("\nProtected from auto-clean: " + ("yes" if protect else "no - auto-clean may quarantine them again"))
            lines.append("You can undo this with Ctrl+Z.")
            if not messagebox.askyesno("Restore samples", "\n".join(lines), parent=self):
                return
        moves, kept_new, skipped = self.lib.move(samples, "restore", target, protect)
        if not moves:
            self.toast("Nothing was restored (same file name already at the destination, or files changed on disk). Press F5.",
                       "warn", 9000)
            self.refresh()
            return
        prev = None
        if label:
            in_ghosts = {dst.name for _src, dst in moves if dst.parent == self.lib.pos_dir}
            to_label = [s for s in samples if s.name in in_ghosts]
            if to_label:
                prev = self.lib.set_labels(to_label, label)
        if prev is not None:
            self._undo.append(("restore + label", [moves, kept_new, prev], []))
        else:
            self._undo.append(("restore", moves, kept_new))
        del self._undo[:-30]
        self.changed = True
        self._commit()
        done = Counter("pos" if dst.parent == self.lib.pos_dir else "neg" for _src, dst in moves)
        where = ", ".join(f"{done[k]} \u2192 {DEST_TEXT[k]}" for k in ("pos", "neg") if done[k])
        msg = f"Restored {len(moves)} ({where})."
        if prev is not None:
            msg += f" Labelled {LABEL_TEXT[label]}."
        msg += " Protected from auto-clean." if protect else " Not protected: auto-clean may judge them again."
        if skipped:
            msg += f" {skipped} skipped (same file name already at the destination)."
        self.toast(msg + "  Ctrl+Z to undo.", "warn" if skipped else "ok", 9000)

    def _flip(self):
        if self.view != "quar":
            self._apply("flip", "relabelled")

    def _delete_key(self):
        (self._delete if self.view == "quar" else self._quarantine)()

    def _undo_last(self):
        if not self._undo:
            return
        action, moves, kept_new = self._undo.pop()
        if action == "label":
            n = self.lib.restore_labels(moves[0])
        elif action == "autoclear":
            n = self.lib.restore_auto(moves[0])
        elif action == "auto-label":
            n = self.lib.undo_auto_run(moves[0])
        elif action == "restore + label":
            done, kept, prev = moves
            n = self.lib.undo(done, kept)
            self.lib.restore_labels(prev)
            self.changed = True
        elif action == "weights":
            n, skipped = self.lib.undo_weight_moves(moves)
            self.changed = True
        else:
            n = self.lib.undo(moves, kept_new)
            self.changed = True
        self.selected.clear()
        self.lib.scan()
        self._sig = self.lib.signature()
        self._rebuild(keep_scroll=True)
        undo_msg = f"Undid {action}: {n} sample(s) put back."
        if action == "weights" and skipped:
            undo_msg += f" {skipped} skipped to avoid overwriting a file."
        self.toast(undo_msg, "info")

    def _edit_weights(self):
        chosen = self._chosen()
        if not chosen:
            self.toast("Select one or more sample images first.", "info")
            return
        win = tk.Toplevel(self)
        win.title("Edit sample weights")
        win.configure(bg=BG)
        win.transient(self)
        win.resizable(False, False)
        win.grab_set()
        tk.Label(win, text=f"Training weight · {len(chosen)} selected image(s)", bg=BG, fg=TEXT,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=16, pady=(14, 4))
        tk.Label(win, text="Weights are saved into the PNG filenames and used on the next training run.\n"
                           "Allowed range: 0.05–20.00. Higher values make a sample count more.",
                 bg=BG, fg=MUTED, justify="left", wraplength=420).pack(anchor="w", padx=16, pady=(0, 10))
        mode = tk.StringVar(value="set")
        initial = f"{chosen[0].weight:.2f}" if len(chosen) == 1 else "1.00"
        value = tk.StringVar(value=initial)
        tk.Radiobutton(win, text="Set every selected image to the same weight", variable=mode, value="set",
                       bg=BG, fg=TEXT, selectcolor=PANEL, activebackground=BG, activeforeground=TEXT).pack(anchor="w", padx=16)
        tk.Radiobutton(win, text="Multiply each current weight by this factor", variable=mode, value="multiply",
                       bg=BG, fg=TEXT, selectcolor=PANEL, activebackground=BG, activeforeground=TEXT).pack(anchor="w", padx=16, pady=(2, 4))
        entry_row = tk.Frame(win, bg=BG)
        entry_row.pack(fill="x", padx=16, pady=4)
        tk.Label(entry_row, text="Weight / multiplier", bg=BG, fg=MUTED).pack(side="left")
        entry = tk.Entry(entry_row, textvariable=value, width=12, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                         relief="flat", font=UI_B)
        entry.pack(side="right", ipady=5)
        tk.Label(win, text="Examples: 1.50 sets all to 1.50; multiplier 1.25 raises each by 25%.",
                 bg=BG, fg=MUTED, font=UI_S).pack(anchor="w", padx=16, pady=(2, 10))
        actions = tk.Frame(win, bg=BG)
        actions.pack(fill="x", padx=16, pady=(0, 14))

        def save():
            try:
                amount = float(value.get().strip())
            except ValueError:
                messagebox.showerror("Invalid weight", "Enter a valid number.", parent=win)
                return
            if not np.isfinite(amount) or amount <= 0:
                messagebox.showerror("Invalid weight", "The value must be greater than zero.", parent=win)
                return
            if mode.get() == "set":
                values = {sample.path: amount for sample in chosen}
            else:
                values = {sample.path: sample.weight * amount for sample in chosen}
            bad = [v for v in values.values() if not 0.05 <= v <= 20.0]
            if bad:
                messagebox.showerror("Weight outside allowed range",
                                     "Every resulting weight must be between 0.05 and 20.00.\n"
                                     "Use a smaller multiplier or set a different value.", parent=win)
                return
            moves, skipped = self.lib.set_weights(chosen, values)
            win.destroy()
            if not moves:
                self.toast("No weights changed (same weight, filename conflict, or file access error).", "warn", 9000)
                self.refresh()
                return
            self._undo.append(("weights", moves, []))
            del self._undo[:-30]
            self.changed = True
            self._commit()
            message = f"Updated {len(moves)} sample weight(s). Retrain to apply them to the model. Ctrl+Z undoes this edit."
            if skipped:
                message += f" {skipped} skipped."
            self.toast(message, "warn" if skipped else "ok", 10000)

        Btn(actions, "Cancel", win.destroy, "quiet").pack(side="right", padx=(6, 0))
        Btn(actions, "Apply weights", save, "primary").pack(side="right")
        entry.focus_set()
        entry.selection_range(0, tk.END)
        win.bind("<Return>", lambda _e: save())
        win.bind("<Escape>", lambda _e: win.destroy())

    def _export_selected(self):
        chosen = self._chosen()
        if not chosen:
            self.toast("Select one or more images first. Selection can include samples across pages.", "info")
            return
        destination = filedialog.askdirectory(parent=self, title="Export copies of selected sample images",
                                              initialdir=str(self.lib.smart))
        if not destination:
            return
        target_dir = Path(destination)
        self.toast(f"Exporting {len(chosen)} image(s)…", "info", 60000)

        def job(progress):
            copied = failed = 0
            for i, sample in enumerate(chosen, 1):
                source = sample.path
                try:
                    if not source.is_file():
                        failed += 1
                        continue
                    target = target_dir / source.name
                    suffix = 1
                    while target.exists():
                        target = target_dir / f"{source.stem}_{suffix}{source.suffix}"
                        suffix += 1
                    shutil.copy2(source, target)
                    copied += 1
                except OSError:
                    failed += 1
                if i % 25 == 0 or i == len(chosen):
                    progress(f"Exported {i}/{len(chosen)} selected image(s)…")
            return {"copied": copied, "failed": failed, "directory": str(target_dir)}

        def done(result):
            if isinstance(result, Exception):
                self.toast(f"Export failed: {result}", "err", 12000)
                return
            copied, failed = result["copied"], result["failed"]
            msg = f"Saved {copied} image copy/copies to {result['directory']}. Originals were not moved."
            if failed:
                msg += f" {failed} image(s) could not be copied."
            self.toast(msg, "warn" if failed else "ok", 12000)

        self._run_bg(job, done)

    def _delete(self):
        chosen = self._chosen()
        if not chosen:
            return
        if not messagebox.askyesno("Delete permanently", f"Permanently delete {len(chosen)} sample(s)?\n"
                                   "This cannot be undone. (Quarantine is the reversible option.)", parent=self):
            return
        n = self.lib.delete(chosen)
        self._undo.clear()                 # earlier moves may refer to deleted files
        if n:
            self.changed = True
        self.selected.clear()
        self.refresh()
        self.toast(f"{n} deleted permanently.", "warn")

    # ------------------------------------------------------------ background work
    def _run_bg(self, fn: Callable[[Callable[[str], None]], object], done: Callable[[object], None]):
        if self._busy:
            self.toast("Another job is still running.", "warn")
            return
        self._busy = True

        def work():
            try:
                res = fn(lambda m: self._bgq.put(("progress", m)))
            except Exception as exc:                       # surfaced to the user, never swallowed
                res = exc
            self._bgq.put(("done", (done, res)))
        threading.Thread(target=work, daemon=True, name="sample-manager-job").start()

    def _poll_bg(self):
        try:
            while True:
                kind, payload = self._bgq.get_nowait()
                if kind == "progress":
                    self.toast(payload, "info", 4000)
                else:
                    self._busy = False
                    done, res = payload
                    done(res)
        except queue.Empty:
            pass
        try:
            if self.winfo_exists():
                self.after(80, self._poll_bg)
        except Exception:
            pass

    def _remove_duplicates(self):
        if self.view == "quar":
            self.toast("Switch to Ghosts or Not ghosts first.", "warn")
            return
        folder = self.lib.pos_dir if self.view == "pos" else self.lib.neg_dir
        label = "ghost" if self.view == "pos" else "not-ghost"
        if len(list(folder.glob("*.png"))) < 2:
            self.toast("Nothing to compare.", "info")
            return
        self.toast(f"Scanning {label} samples for duplicates...", "info", 60000)

        def job(progress):
            return find_duplicate_samples(folder, DUP_TOL, lambda d, t: progress(f"Scanning {d}/{t}..."))

        def done(res):
            if isinstance(res, Exception):
                self.toast(f"Duplicate scan failed: {res}", "err")
                return
            files, dupes = res
            if not dupes:
                self.toast(f"No duplicates among {len(files)} {label} samples.", "ok")
                return
            if not messagebox.askyesno("Remove duplicates", f"Found {len(dupes)} duplicate(s) among {len(files)} "
                                       f"{label} samples.\n{len(files) - len(dupes)} unique images will remain.\n\n"
                                       "Permanently delete the duplicates?", parent=self):
                self.toast("Duplicate removal cancelled.", "info")
                return
            removed = 0
            for p in dupes:
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
            if removed:
                self.changed = True
            self._undo.clear()
            self.refresh()
            self.toast(f"{removed} duplicate sample(s) removed.", "ok")

        self._run_bg(job, done)

    def _ask(self, action: str):
        if self._await:
            self.toast("A clean/retrain job is already pending. Wait for it to finish before requesting another.",
                       "warn", 8000)
            return
        if self._busy:
            self.toast("Wait for the current sample-manager task to finish first.", "warn")
            return
        requested_at = time.time()
        try:
            self.request(action)
        except Exception as exc:
            self.toast(f"Could not send the request: {exc}", "err")
            return
        self.changed = False
        self._await = (action, requested_at)
        self.toast("Requested " + ("auto-clean + retrain" if action == "clean" else "retrain")
                   + ". Duplicate requests are blocked while this job is pending.", "info", 120000)

    def _check_await(self):
        if not self._await:
            return
        action, t0 = self._await
        now = time.time()
        maintenance_path = self.lib.smart / "maintenance.json"
        job = _read_json(maintenance_path)
        # The offline CLI writes an explicit lifecycle marker. Prefer it over status.json,
        # which can change between cleaning passes and otherwise looks like completion.
        if isinstance(job, dict):
            try:
                started_at = float(job.get("started_at", 0) or 0)
            except (TypeError, ValueError):
                started_at = 0.0
            job_action = str(job.get("action", ""))
            expected = {"clean": {"clean", "clean-retrain"},
                        "retrain": {"retrain", "clean-retrain"}}.get(action, {action})
            if started_at >= t0 and job_action in expected:
                state = str(job.get("state", ""))
                if state == "running":
                    # A long-running job is alive; do not interpret its quiet periods as success.
                    if now - t0 > 1800:
                        self._await = None
                        self.toast("The offline job has not finished after 30 minutes. Check the latest console/log output; "
                                   "the job may still be active, so no new job was launched automatically.", "warn", 18000)
                    return
                if state in {"done", "error"}:
                    self._await = None
                    self.refresh()
                    if state == "error":
                        detail = str(job.get("error", "Unknown error"))
                        self.toast(f"Offline {action} failed: {detail}", "err", 18000)
                    else:
                        m = self.lib.status().get("metrics", {}) or {}
                        msg = "Done."
                        if "val_precision" in m:
                            msg = (f"Done - model precision {m['val_precision'] * 100:.0f}% / recall "
                                   f"{m.get('val_recall', 0) * 100:.0f}% on held-out samples.")
                        self.toast("\u2714 " + msg, "ok", 12000)
                    return
        # Live-bot commands do not run the offline CLI. In that case wait for a fresh,
        # stable status write, but use a much more generous deadline than the old 150 seconds.
        st_time = float(self.lib.status().get("time", 0) or 0)
        if st_time > t0 and now - st_time > 4.0:
            self._await = None
            self.refresh()
            m = self.lib.status().get("metrics", {}) or {}
            msg = "Done."
            if "val_precision" in m:
                msg = (f"Done - model precision {m['val_precision'] * 100:.0f}% / recall "
                       f"{m.get('val_recall', 0) * 100:.0f}% on held-out samples.")
            self.toast("\u2714 " + msg, "ok", 12000)
        elif now - t0 > 1800:
            self._await = None
            self.toast("No completion signal after 30 minutes. Check the bot console/logs before trying again; "
                       "a running offline job is not automatically started twice.", "warn", 18000)

    def _open_folder(self):
        try:
            if os.name == "nt":
                os.startfile(str(self.lib.smart))        # type: ignore[attr-defined]
            else:
                self.toast(str(self.lib.smart), "info", 12000)
        except Exception as exc:
            self.toast(f"Could not open the folder: {exc}", "err")

    # ------------------------------------------------------------ housekeeping
    def _tick(self):
        try:
            if not self.winfo_exists():
                return
            sig = self.lib.signature()
            if sig != self._sig and not self._busy:
                if self.selected:
                    if not self._warned_disk:
                        self._warned_disk = True
                        self.toast("Samples changed on disk. Press F5 to refresh (your selection is kept until then).", "info", 8000)
                else:
                    self.refresh()
            self._check_await()
            self._tick_job = self.after(2000, self._tick)
        except Exception:
            pass

    def _close(self):
        if self._tick_job:
            try:
                self.after_cancel(self._tick_job)
            except Exception:
                pass
        if self.changed and not self._await:
            try:
                self.request("retrain")
            except Exception:
                pass
        self.destroy()
