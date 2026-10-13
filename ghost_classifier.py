"""Ghost kind / colour classification, wave detection and on-screen labels.

Rules (from the game):
  * SMALL ghosts are the normal ghosts. Colours and points: blue 5, purple 15,
    yellow 55, rainbow 100.
  * BOSSES are the big ones. Colours: blue, cyan, green, light green, red,
    white, rainbow.
  * A BIG WAVE = lots of small ghosts on screen at once. The bot must click ALL
    of them. The reward only arrives at the end, when the "esprits attrapes"
    popup shows, so there is no per-click confirmation during a wave.

Colours are decided in two steps:
  1. built-in HSV rules (works out of the box, tunable in ghost_colors.json);
  2. a nearest-neighbour model trained from crops you label with
     label_ghosts.py (labels/<kind>_<colour>/*.png). Labels win over the rules
     once there are enough of them.

Pure logic: no clicking happens here. main.py decides what to do with the result.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

log = logging.getLogger("bloop.ghosts")

SMALL, BOSS = "small", "boss"
SMALL_COLORS = ("blue", "purple", "yellow", "rainbow")
BOSS_COLORS = ("blue", "cyan", "green", "light green", "red", "white", "rainbow")
SMALL_POINTS = {"blue": 5, "purple": 15, "yellow": 55, "rainbow": 100}

# OpenCV hue is 0..179. Starting guesses; override them in ghost_colors.json
# ({"hue_ranges": {"cyan": [85, 100], ...}}) after looking at your labelled crops.
DEFAULT_HUES: Dict[str, Tuple[int, int]] = {
    "red": (0, 8),          # also wraps: 170..179
    "yellow": (18, 36),
    "light green": (37, 55),
    "green": (56, 80),
    "cyan": (81, 98),
    "blue": (99, 125),
    "purple": (126, 169),
}


@dataclass
class Ghost:
    x: int
    y: int
    w: int
    h: int
    kind: str                  # "small" | "boss"
    color: str
    conf: float = 1.0
    points: int = 0            # only meaningful for small ghosts

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2

    @property
    def label(self) -> str:
        pct = f"{self.conf * 100:.0f}%"
        if self.kind == BOSS:
            return f"BOSS {self.color}  {pct}"
        return f"ghost {self.color} +{self.points}  {pct}"


@dataclass
class Scene:
    ghosts: List[Ghost] = field(default_factory=list)
    wave: bool = False
    wave_size: int = 0

    @property
    def smalls(self) -> List[Ghost]:
        return [g for g in self.ghosts if g.kind == SMALL]

    @property
    def bosses(self) -> List[Ghost]:
        return [g for g in self.ghosts if g.kind == BOSS]


# --------------------------------------------------------------------------
# colour features
# --------------------------------------------------------------------------
def color_features(crop_bgr: np.ndarray) -> Optional[np.ndarray]:
    """Rotation-free colour descriptor: 18-bin hue histogram of saturated pixels
    + [white share, dark share, hue spread, mean S, mean V]. None if crop is empty."""
    if crop_bgr is None or crop_bgr.size == 0:
        return None
    small = cv2.resize(crop_bgr, (32, 32), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.float32)
    h, s, v = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    bright = v > 90                                   # ignore dark outlines / shadows
    sat = bright & (s > 70)
    white = bright & (s < 45) & (v > 190)
    n_b = max(1, int(bright.sum()))
    hist = np.zeros(18, np.float32)
    if sat.any():
        hist, _ = np.histogram(h[sat], bins=18, range=(0, 180))
        hist = hist.astype(np.float32) / max(1, sat.sum())
    # circular spread: fraction of hue bins holding >= 6% of the coloured pixels
    spread = float((hist >= 0.06).sum()) / 18.0
    feats = np.concatenate([hist, [white.sum() / n_b, 1.0 - n_b / len(v), spread,
                                   float(s[bright].mean()) / 255.0 if bright.any() else 0.0,
                                   float(v[bright].mean()) / 255.0 if bright.any() else 0.0]])
    return feats.astype(np.float32)


class ColorClassifier:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.hues = dict(DEFAULT_HUES)
        self.rainbow_spread = 0.40      # >= this share of hue bins used -> rainbow
        self.white_share = 0.55         # >= this share of near-white pixels -> white
        self._X: Optional[np.ndarray] = None
        self._y: List[Tuple[str, str]] = []
        self._meta: List[Tuple[float, Optional[float]]] = []   # per label: (timestamp s or 0, size fraction or None)
        self.boss_min_frac = 0.14       # default small/boss size split (GhostScene keeps it in sync)
        self.min_labels = 6             # per (kind) before the model overrides rules
        self._labels_mtime = 0.0
        self._last_label_check = 0.0
        self.reload()

    # ----- config + labels -----
    def reload(self) -> None:
        cfg = self.root / "ghost_colors.json"
        if cfg.exists():
            try:
                raw = json.loads(cfg.read_text(encoding="utf-8"))
                for name, rng in (raw.get("hue_ranges") or {}).items():
                    self.hues[name] = (int(rng[0]), int(rng[1]))
                self.rainbow_spread = float(raw.get("rainbow_spread", self.rainbow_spread))
                self.white_share = float(raw.get("white_share", self.white_share))
            except Exception as exc:
                log.warning("ghost_colors.json ignored: %s", exc)
        feats, labels, meta = [], [], []
        frame_h = self._frame_h()
        base = self.root / "labels"
        if base.exists():
            for d in sorted(p for p in base.iterdir() if p.is_dir()):
                kind, _, color = d.name.partition("_")
                color = color.replace("-", " ")
                if kind not in (SMALL, BOSS) or not color:
                    continue
                for f in list(d.glob("*.png")) + list(d.glob("*.jpg")):
                    img = cv2.imdecode(np.fromfile(str(f), np.uint8), cv2.IMREAD_COLOR)
                    ft = color_features(img)
                    if ft is not None:
                        feats.append(ft)
                        labels.append((kind, color))
                        meta.append((0.0, None))
        # labels made in the Sample manager (smart/ghost_labels.json -> crops in smart/positives|negatives)
        lab_file = self.root / "smart" / "ghost_labels.json"
        try:
            self._labels_mtime = lab_file.stat().st_mtime
            sm_labels = json.loads(lab_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            sm_labels = {}
        if isinstance(sm_labels, dict):
            for name, key in sm_labels.items():
                kind, _, color = str(key).partition("_")
                color = color.replace("-", " ")
                if kind not in (SMALL, BOSS) or not color:
                    continue
                for d in ("positives", "negatives"):
                    f = self.root / "smart" / d / name
                    if f.exists():
                        img = cv2.imdecode(np.fromfile(str(f), np.uint8), cv2.IMREAD_COLOR)
                        ft = color_features(img)
                        if ft is not None:
                            feats.append(ft)
                            labels.append((kind, color))
                            meta.append((self._stamp_of(name), self._size_frac(img, frame_h)))
                        break
        self._X = np.stack(feats) if feats else None
        self._y = labels
        self._meta = meta
        if labels:
            log.info("GHOST labels loaded: %d crop(s)", len(labels))

    def maybe_reload(self, now: float, every_s: float = 5.0) -> None:
        """Pick up labels saved from the Sample manager without a restart / F10."""
        if now - self._last_label_check < every_s:
            return
        self._last_label_check = now
        try:
            m = (self.root / "smart" / "ghost_labels.json").stat().st_mtime
        except OSError:
            return
        if m != self._labels_mtime:
            self.reload()

    def label_counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for kind, color in self._y:
            out[f"{kind}_{color}"] = out.get(f"{kind}_{color}", 0) + 1
        return out

    # ----- rules -----
    def rule_color(self, feats: np.ndarray, kind: str) -> Tuple[str, float]:
        hist, white, _dark, spread, mean_s, _mean_v = feats[:18], feats[18], feats[19], feats[20], feats[21], feats[22]
        allowed = SMALL_COLORS if kind == SMALL else BOSS_COLORS
        if spread >= self.rainbow_spread and "rainbow" in allowed:
            return "rainbow", min(1.0, spread / max(self.rainbow_spread, 1e-6) * 0.7)
        if white >= self.white_share and "white" in allowed and hist.sum() < 0.5:
            return "white", float(min(1.0, white))
        # circular hue vote
        votes: Dict[str, float] = {}
        for b in range(18):
            if hist[b] <= 0:
                continue
            hue = b * 10 + 5
            name = self._hue_name(hue)
            votes[name] = votes.get(name, 0.0) + float(hist[b])
        if not votes:
            return ("white" if "white" in allowed else allowed[0]), 0.3
        # map to the colours this kind can actually have
        mapped: Dict[str, float] = {}
        for name, v in votes.items():
            mapped[self._to_allowed(name, kind)] = mapped.get(self._to_allowed(name, kind), 0.0) + v
        best = max(mapped, key=mapped.get)
        return best, float(mapped[best] / max(1e-6, sum(mapped.values())))

    def _hue_name(self, hue: float) -> str:
        for name, (lo, hi) in self.hues.items():
            if lo <= hue <= hi:
                return name
        if hue >= 170 or hue <= 8:
            return "red"
        return "purple"

    @staticmethod
    def _to_allowed(name: str, kind: str) -> str:
        if kind == SMALL:
            # small ghosts only come in blue / purple / yellow / rainbow
            return {"red": "purple", "cyan": "blue", "green": "yellow", "light green": "yellow"}.get(name, name)
        return name

    # ----- auto-labelling (used by the Sample manager's "Auto-label ghosts" button) -----
    # The model is the same nearest-neighbour colour model the bot uses, trained ONLY on labels you made
    # yourself (labels/ folders + smart/ghost_labels.json). Automatic labels are never fed back into it,
    # so a wrong guess can not teach the model to repeat itself.
    AUTO_MIN_LABELS = 20        # your own labels needed before auto-labelling is offered
    AUTO_MIN_CLASS = 5          # labels a colour needs to count as "known"
    AUTO_MIN_ACCURACY = 0.85    # leave-one-out agreement with your labels
    AUTO_MIN_CONF = 0.75        # vote share needed to label a crop
    CROP_PAD = 0.10             # smart_ghost saves every crop with 10 % padding on each side

    def _frame_h(self) -> int:
        try:
            v = int(json.loads((self.root / "smart" / "status.json").read_text(encoding="utf-8")).get("frame_h", 0))
            if v > 0:
                return v
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return 720

    @staticmethod
    def _stamp_of(name: str) -> float:
        try:
            v = int(Path(name).stem.split("_")[0]) / 1000.0
            return v if v > 1e9 else 0.0
        except (ValueError, IndexError):
            return 0.0

    @classmethod
    def _size_frac(cls, img: np.ndarray, frame_h: int) -> float:
        """Biggest side of the ghost (crop minus its padding) as a fraction of the frame height.
        Same definition as SmartGhost.is_boss (max of width and height)."""
        return float(max(img.shape[0], img.shape[1])) / (1.0 + 2.0 * cls.CROP_PAD) / max(1, frame_h)

    def _kind_threshold(self) -> float:
        """Small/boss split. Taken from the sizes of your own labels when both kinds are labelled and
        separable; otherwise the default boss_min_frac."""
        sm = [f for (k, _c), (_t, f) in zip(self._y, self._meta) if k == SMALL and f]
        bs = [f for (k, _c), (_t, f) in zip(self._y, self._meta) if k == BOSS and f]
        if len(sm) >= 3 and len(bs) >= 3:
            hi_small, lo_boss = float(np.percentile(sm, 95)), float(np.percentile(bs, 5))   # percentiles: one slip is tolerated
            if hi_small < lo_boss:
                return (hi_small + lo_boss) / 2.0
        return self.boss_min_frac

    def _knn(self, feats: np.ndarray, kind: str) -> Optional[Tuple[str, float, float]]:
        """(colour, vote share, distance to the nearest labelled crop) or None if the kind has too few labels."""
        if self._X is None:
            return None
        idx = [i for i, (k, _c) in enumerate(self._y) if k == kind]
        if len(idx) < self.min_labels:
            return None
        d = np.linalg.norm(self._X[idx] - feats[None, :], axis=1)
        order = np.argsort(d)[:5]
        votes: Dict[str, float] = {}
        for j in order:
            col = self._y[idx[j]][1]
            votes[col] = votes.get(col, 0.0) + 1.0 / (0.05 + float(d[j]))
        best = max(votes, key=votes.get)
        return best, float(votes[best] / max(1e-6, sum(votes.values()))), float(d[order[0]])

    def _leave_one_out(self) -> Dict[str, object]:
        """How well the model predicts each of YOUR labels from all the others.
        Crops saved within 2 s of each other are usually the same ghost, so a label is never judged by
        its own twins (that would make the score look far better than it is)."""
        out: Dict[str, object] = {"n": 0, "correct": 0, "nn": {}}
        if self._X is None:
            return out
        for kind in (SMALL, BOSS):
            idx = [i for i, (k, _c) in enumerate(self._y) if k == kind]
            if len(idx) < self.min_labels:
                continue
            A = self._X[idx].astype(np.float64)
            sq = (A ** 2).sum(axis=1)
            D = np.sqrt(np.maximum(sq[:, None] + sq[None, :] - 2.0 * A @ A.T, 0.0))
            t = np.array([self._meta[i][0] for i in idx])
            twin = (np.abs(t[:, None] - t[None, :]) <= 2.0) & (t[:, None] > 0) & (t[None, :] > 0)
            np.fill_diagonal(twin, True)
            D[twin] = np.inf
            nn: List[float] = []
            for a, i in enumerate(idx):
                order = [j for j in np.argsort(D[a])[:5] if np.isfinite(D[a][j])]
                if not order:
                    continue
                votes: Dict[str, float] = {}
                for j in order:
                    col = self._y[idx[j]][1]
                    votes[col] = votes.get(col, 0.0) + 1.0 / (0.05 + float(D[a][j]))
                out["n"] += 1
                out["correct"] += int(max(votes, key=votes.get) == self._y[i][1])
                nn.append(float(D[a][order[0]]))
            if nn:
                out["nn"][kind] = float(np.median(nn))
        return out

    def auto_status(self) -> Dict[str, object]:
        """Can the auto-labeller be trusted yet?  Keys: ready, reason, accuracy (0..1), labels, weak, classes."""
        self.reload()
        counts = self.label_counts()
        n = len(self._y)
        weak = [f"{k} ({c})" for k, c in sorted(counts.items(), key=lambda kv: kv[1]) if c < self.AUTO_MIN_CLASS]
        weak += [f"small_{c} (0)" for c in SMALL_COLORS if f"small_{c}" not in counts]
        st: Dict[str, object] = {"ready": False, "reason": "", "accuracy": 0.0, "labels": n,
                                 "classes": counts, "weak": weak, "judged": 0}
        if n < self.AUTO_MIN_LABELS:
            st["reason"] = f"only {n} of your own labels so far (at least {self.AUTO_MIN_LABELS} needed)"
            return st
        strong = [k for k, c in counts.items() if c >= self.AUTO_MIN_CLASS]
        if len(strong) < 2:
            st["reason"] = f"label at least 2 kinds/colours with {self.AUTO_MIN_CLASS}+ examples each (have {len(strong)})"
            return st
        loo = self._leave_one_out()
        st["judged"] = int(loo["n"])
        if loo["n"] < self.AUTO_MIN_LABELS:
            st["reason"] = (f"only {loo['n']} of your labels can be checked "
                            f"(a kind needs {self.min_labels}+ labels, and crops from the same moment count once)")
            return st
        acc = loo["correct"] / float(loo["n"])
        st["accuracy"] = float(acc)
        self._auto_nn = dict(loo["nn"])
        if acc < self.AUTO_MIN_ACCURACY:
            st["reason"] = (f"the model only agrees with {acc * 100:.0f}% of your labels "
                            f"(needs {self.AUTO_MIN_ACCURACY * 100:.0f}%); check for mislabelled samples or add more")
            return st
        st["ready"] = True
        return st

    def auto_label_positives(self, progress=None, min_conf: Optional[float] = None) -> Dict[str, object]:
        """Label the ghosts you have NOT labelled yourself. Writes smart/ghost_labels_auto.json
        ({sample file: "<kind>_<colour>"}). Skips samples you labelled or cleared on purpose. A crop is
        only labelled when the model is confident AND it looks like labelled ghosts (not an odd one out);
        the rest stay unlabelled for you. Returns {"labelled", "left", "total", ...}."""
        say = progress if callable(progress) else (lambda _m: None)
        st = self.auto_status()
        if not st["ready"]:
            return {"labelled": 0, "left": 0, "total": 0, "not_ready": True, "reason": st["reason"], "status": st}
        min_conf = self.AUTO_MIN_CONF if min_conf is None else float(min_conf)
        smart = self.root / "smart"
        pos_dir = smart / "positives"
        try:
            manual = json.loads((smart / "ghost_labels.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manual = {}
        if not isinstance(manual, dict):
            manual = {}
        try:
            old = json.loads((smart / "ghost_labels_auto.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = {}
        if not isinstance(old, dict):
            old = {}
        files = sorted(pos_dir.glob("*.png")) if pos_dir.exists() else []
        cands = [f for f in files if f.name not in manual]          # your label (or your "no label") always wins
        frame_h, thr_kind = self._frame_h(), self._kind_threshold()
        nn = getattr(self, "_auto_nn", {})
        new: Dict[str, str] = {}
        kinds = {SMALL: 0, BOSS: 0}
        for i, f in enumerate(cands):
            if i % 150 == 0:
                say(f"Auto-labelling ghosts... {i}/{len(cands)}")
            img = cv2.imdecode(np.fromfile(str(f), np.uint8), cv2.IMREAD_COLOR)
            ft = color_features(img)
            if ft is None:
                continue
            kind = BOSS if self._size_frac(img, frame_h) >= thr_kind else SMALL
            r = self._knn(ft, kind)
            if r is None:
                continue                                              # no labels of this kind to learn from
            colour, conf, dmin = r
            allowed = SMALL_COLORS if kind == SMALL else BOSS_COLORS
            if colour not in allowed or conf < min_conf:
                continue
            if kind in nn and dmin > 3.0 * nn[kind] + 0.05:
                continue                                              # nothing like what you labelled: not sure
            new[f.name] = f"{kind}_{colour.replace(' ', '-')}"
            kinds[kind] += 1
        # keep earlier auto-labels of samples that are not in positives/ (e.g. still on disk elsewhere)
        keep_dirs = [smart / "negatives", smart / "quarantine" / "positives", smart / "quarantine" / "negatives"]
        cand_names = {f.name for f in cands}
        for name, key in old.items():
            if name not in new and name not in cand_names and name not in manual and isinstance(key, str) \
                    and any((d / name).exists() for d in keep_dirs):
                new[name] = key
        tmp = smart / "ghost_labels_auto.tmp"
        smart.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(new, indent=0, sort_keys=True), encoding="utf-8")
        os.replace(tmp, smart / "ghost_labels_auto.json")
        labelled = sum(1 for f in cands if f.name in new)
        log.info("GHOST auto-label: %d labelled, %d left for you (of %d unlabelled ghosts); accuracy vs your labels %.0f%%",
                 labelled, len(cands) - labelled, len(cands), float(st["accuracy"]) * 100)
        return {"labelled": labelled, "left": len(cands) - labelled, "total": len(cands),
                "small": kinds[SMALL], "boss": kinds[BOSS], "kind_threshold": thr_kind, "status": st}

    # ----- model -----
    def model_color(self, feats: np.ndarray, kind: str) -> Optional[Tuple[str, float]]:
        if self._X is None:
            return None
        idx = [i for i, (k, _c) in enumerate(self._y) if k == kind]
        if len(idx) < self.min_labels:
            return None
        d = np.linalg.norm(self._X[idx] - feats[None, :], axis=1)
        order = np.argsort(d)[:5]
        votes: Dict[str, float] = {}
        for j in order:
            col = self._y[idx[j]][1]
            votes[col] = votes.get(col, 0.0) + 1.0 / (0.05 + float(d[j]))
        best = max(votes, key=votes.get)
        conf = votes[best] / max(1e-6, sum(votes.values()))
        return best, float(conf)

    def classify(self, crop_bgr: np.ndarray, kind: str) -> Tuple[str, float]:
        feats = color_features(crop_bgr)
        if feats is None:
            return ("blue", 0.0)
        m = self.model_color(feats, kind)
        if m is not None and m[1] >= 0.55:
            return m
        return self.rule_color(feats, kind)


# --------------------------------------------------------------------------
# kind (size) + wave detection
# --------------------------------------------------------------------------
class GhostScene:
    """Turns raw boxes into labelled ghosts and tracks wave state."""

    def __init__(self, root: Path, boss_min_frac: float = 0.14, wave_min_ghosts: int = 6,
                 wave_confirm_frames: int = 2, wave_end_quiet_s: float = 2.5,
                 min_frac: float = 0.02):
        self.colors = ColorClassifier(root)
        self.colors.boss_min_frac = float(boss_min_frac)
        self.boss_min_frac = float(boss_min_frac)    # box height / frame height
        self.min_frac = float(min_frac)              # smaller than this = noise
        self.wave_min_ghosts = int(wave_min_ghosts)
        self.wave_confirm_frames = int(wave_confirm_frames)
        self.wave_end_quiet_s = float(wave_end_quiet_s)
        self.scene = Scene()
        self._wave_hits = 0
        self.wave_active = False
        self._wave_last_seen = 0.0
        self.wave_started_at = 0.0
        self.wave_peak = 0
        self.wave_points_est = 0           # sum of the points of every small ghost *seen* (first sighting)
        self.waves_done = 0
        self.session = {"small": 0, "boss": 0, "waves": 0}
        self._events: List[Tuple[float, str, Tuple[int, int, int]]] = []   # (time, text, bgr)
        self._seen_boss = 0.0
        self._seen_small = 0.0
        self._wave_ids: List[Tuple[int, int, int]] = []                  # coarse positions for first-sighting counts
        self.calibrate_size()

    # ----- main entry -----
    def update(self, frame: np.ndarray, boxes: Sequence[Tuple[int, int, int, int]], now: float) -> Scene:
        self.colors.maybe_reload(now)
        fh = max(1, frame.shape[0])
        ghosts: List[Ghost] = []
        for (x, y, w, h) in boxes:
            frac = h / fh
            if frac < self.min_frac:
                continue
            kind = BOSS if frac >= self.boss_min_frac else SMALL
            x0, y0 = max(0, int(x)), max(0, int(y))
            crop = frame[y0:y0 + int(h), x0:x0 + int(w)]
            color, conf = self.colors.classify(crop, kind)
            g = Ghost(x0, y0, int(w), int(h), kind, color, conf,
                      SMALL_POINTS.get(color, 0) if kind == SMALL else 0)
            ghosts.append(g)
        self.scene = Scene(ghosts)
        self._update_wave(now)
        self._announce(now)
        return self.scene

    def _update_wave(self, now: float) -> None:
        n = len(self.scene.smalls)
        if n >= self.wave_min_ghosts:
            self._wave_hits += 1
            self._wave_last_seen = now
        else:
            self._wave_hits = 0
        if not self.wave_active and self._wave_hits >= self.wave_confirm_frames:
            self.wave_active = True
            self.wave_started_at = now
            self.wave_peak = n
            self.wave_points_est = 0
            self._wave_ids = []
            self.session["waves"] += 1
            self._push(now, f"BIG WAVE! {n} ghosts - clicking them all", (0, 140, 255))
            log.info("BIG WAVE detected: %d small ghosts on screen", n)
        if self.wave_active:
            self.wave_peak = max(self.wave_peak, n)
            self.scene.wave, self.scene.wave_size = True, n
            for g in self.scene.smalls:       # estimate: count each ghost the first time we see it
                key = (g.cx // 40, g.cy // 40, hash(g.color) % 7)
                if key not in self._wave_ids:
                    self._wave_ids.append(key)
                    self.wave_points_est += g.points
            if n == 0 and now - self._wave_last_seen >= self.wave_end_quiet_s:
                self.end_wave(now, reason="no ghosts left")

    def end_wave(self, now: float, reason: str = "") -> None:
        if not self.wave_active:
            return
        self.wave_active = False
        self.waves_done += 1
        self._push(now, f"Wave over: peak {self.wave_peak} ghosts ({reason})", (0, 200, 255))
        log.info("WAVE ended (%s): peak=%d, rough value seen=%d pts (real reward comes with the popup)",
                 reason, self.wave_peak, self.wave_points_est)

    def _announce(self, now: float) -> None:
        if self.scene.bosses and now - self._seen_boss > 3.0:
            b = self.scene.bosses[0]
            self._push(now, f"BOSS spotted: {b.color}", (60, 60, 255))
            log.info("BOSS detected: %s at (%d,%d) %dx%d", b.color, b.cx, b.cy, b.w, b.h)
            self.session["boss"] += 1
        if self.scene.bosses:
            self._seen_boss = now
        if self.scene.smalls and not self.wave_active and now - self._seen_small > 3.0:
            g = self.scene.smalls[0]
            self._push(now, f"Ghost: {g.color} (+{g.points})", (255, 200, 80))
            log.info("GHOST detected: %s (+%d) at (%d,%d)", g.color, g.points, g.cx, g.cy)
            self.session["small"] += 1
        if self.scene.smalls:
            self._seen_small = now

    def _push(self, now: float, text: str, bgr: Tuple[int, int, int]) -> None:
        self._events.append((now, text, bgr))
        self._events = self._events[-6:]

    # ----- labelling support -----
    def collect_unlabeled(self, frame: np.ndarray, now: float, every_s: float = 1.5, max_files: int = 400) -> None:
        """Save a crop of one on-screen ghost now and then into labels/unlabeled/ so
        label_ghosts.py can ask you what it is. The file name starts with the
        box-height / frame-height fraction (used to calibrate small-vs-boss)."""
        if now - getattr(self, "_last_collect", 0.0) < every_s or not self.scene.ghosts:
            return
        folder = self.colors.root / "labels" / "unlabeled"
        folder.mkdir(parents=True, exist_ok=True)
        if len(list(folder.glob("*.png"))) >= max_files:
            return
        self._last_collect = now
        # prefer a kind we have fewer examples of
        g = sorted(self.scene.ghosts, key=lambda q: q.kind == BOSS, reverse=True)[0] if self.scene.bosses \
            else self.scene.ghosts[int(now * 10) % len(self.scene.ghosts)]
        pad = int(0.15 * max(g.w, g.h))
        crop = frame[max(0, g.y - pad):g.y + g.h + pad, max(0, g.x - pad):g.x + g.w + pad]
        if crop.size == 0:
            return
        frac = g.h / max(1, frame.shape[0])
        name = f"{frac:.3f}_{g.kind}-{g.color.replace(' ', '-')}_{int(now * 1000)}.png"
        cv2.imwrite(str(folder / name), crop)

    def calibrate_size(self) -> None:
        """Set boss_min_frac between your biggest labelled small ghost and your
        smallest labelled boss (needs >= 3 of each)."""
        base = self.colors.root / "labels"
        smalls, bosses = [], []
        if base.exists():
            for d in base.iterdir():
                if not d.is_dir() or d.name == "unlabeled":
                    continue
                kind = d.name.split("_")[0]
                for f in d.glob("*.png"):
                    try:
                        frac = float(f.name.split("_")[0])
                    except ValueError:
                        continue
                    (smalls if kind == SMALL else bosses if kind == BOSS else []).append(frac)
        if len(smalls) >= 3 and len(bosses) >= 3 and max(smalls) < min(bosses):
            self.boss_min_frac = (max(smalls) + min(bosses)) / 2.0
            self.colors.boss_min_frac = self.boss_min_frac
            log.info("GHOST size calibrated from labels: boss if height >= %.3f of frame (small max %.3f, boss min %.3f)",
                     self.boss_min_frac, max(smalls), min(bosses))

    # ----- wave click order -----
    def wave_click_order(self, start: Optional[Tuple[int, int]] = None) -> List[Ghost]:
        """Small ghosts ordered as a short path (nearest neighbour) so the cursor
        does not jump across the screen between clicks."""
        todo = list(self.scene.smalls)
        if not todo:
            return []
        cur = start or (todo[0].cx, todo[0].cy)
        out: List[Ghost] = []
        while todo:
            nxt = min(todo, key=lambda g: (g.cx - cur[0]) ** 2 + (g.cy - cur[1]) ** 2)
            todo.remove(nxt)
            out.append(nxt)
            cur = (nxt.cx, nxt.cy)
        return out

    # ----- on-screen overlay data -----
    @staticmethod
    def _hex(bgr: Tuple[int, int, int]) -> str:
        b, g, r = bgr
        h = "#%02x%02x%02x" % (r, g, b)
        return "#020202" if h == "#010101" else h

    def overlay_items(self, now: float) -> dict:
        boxes = []
        for g in self.scene.ghosts:
            col = self._hex(self._BOX_BGR.get(g.color, (255, 255, 255)))
            boxes.append((g.x, g.y, g.w, g.h, g.label, col, 4 if g.kind == BOSS else 3))
        banner = None
        if self.wave_active:
            banner = (f"BIG WAVE  {len(self.scene.smalls)} ghosts", "#d96a00")
        elif self.scene.bosses:
            banner = (f"BOSS  {self.scene.bosses[0].color}", "#b02020")
        notes = [(text, self._hex(col)) for t, text, col in reversed(self._events) if now - t <= 6.0]
        return {"boxes": boxes, "banner": banner, "notes": notes}

    # ----- drawing -----
    _BOX_BGR = {"blue": (255, 120, 40), "cyan": (255, 255, 0), "green": (60, 200, 60),
                "light green": (140, 255, 160), "red": (50, 50, 255), "white": (240, 240, 240),
                "yellow": (0, 230, 255), "purple": (220, 80, 200), "rainbow": (255, 0, 255)}

    def draw(self, frame: np.ndarray, clicks_this_wave: int = 0) -> np.ndarray:
        view = frame.copy()
        for g in self.scene.ghosts:
            col = self._BOX_BGR.get(g.color, (255, 255, 255))
            th = 3 if g.kind == BOSS else 2
            cv2.rectangle(view, (g.x, g.y), (g.x + g.w, g.y + g.h), col, th)
            txt = g.label
            (tw, tht), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            ty = max(tht + 4, g.y - 4)
            cv2.rectangle(view, (g.x, ty - tht - 3), (g.x + tw + 4, ty + 3), (0, 0, 0), -1)
            cv2.putText(view, txt, (g.x + 2, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)
        # banner
        now = time.time()
        y = 28
        if self.wave_active:
            banner = f"BIG WAVE  {len(self.scene.smalls)} ghosts on screen  (peak {self.wave_peak})  clicked {clicks_this_wave}"
            cv2.rectangle(view, (0, 0), (view.shape[1], 40), (0, 90, 220), -1)
            cv2.putText(view, banner, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
            y = 66
        elif self.scene.bosses:
            cv2.rectangle(view, (0, 0), (view.shape[1], 40), (40, 40, 200), -1)
            cv2.putText(view, f"BOSS: {self.scene.bosses[0].color}", (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
            y = 66
        for t, text, col in reversed(self._events):
            if now - t > 6.0:
                continue
            cv2.putText(view, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2, cv2.LINE_AA)
            y += 24
        s = self.session
        cv2.putText(view, f"seen: ghosts {s['small']}  bosses {s['boss']}  waves {s['waves']}",
                    (10, view.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)
        return view
