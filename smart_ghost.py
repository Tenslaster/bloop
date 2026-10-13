#!/usr/bin/env python3
"""
smart_ghost.py - learn what a ghost is from the player's own clicks.

How it works
------------
1. WATCH   A global mouse listener records every left click. A short ring buffer
           of recent frames lets us look back to the frame the player was looking
           at just before the click, so moving ghosts are cropped where they
           actually were.
2. LEARN   The object under each click becomes a positive sample (saved as an
           RGBA PNG in smart/positives/). Things that sit still for seconds, or
           that the bot clicked without any reaction, become negatives.
3. TRAIN   Colour-invariant features (shape, texture, glow, size) feed a tiny
           NumPy neural net. Samples are augmented with hue shifts, flips (ghost
           facing), scale, rotation and brightness, so a ghost colour or facing
           the player never clicked is still recognised.
5. CONFIRM The webhook reporter reads the "Vous avez obtenu Ectoplaz xN" toast. A gain that
           lines up with a bot click proves it was a real catch -> strongest positive label,
           hit-rate tracking, adaptive threshold, fast retry of aim misses (see on_ecto_gain).
4. ACT     Class-agnostic proposals (motion against a background model, plus the
           host bot's colour/edge proposals) are tracked frame to frame, scored by
           the model, and the best track is clicked at a motion-predicted spot.

Everything is pure NumPy + OpenCV. No GPU, torch or scikit-learn needed.
"""
from __future__ import annotations

import json
import logging
import errno
import os
import random
import shutil
import threading
import time
import warnings
import zlib
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

try:
    from pynput import mouse as _pmouse
    HAS_PYNPUT = True
except Exception:  # headless / not installed
    _pmouse = None
    HAS_PYNPUT = False

log = logging.getLogger("bot.smart")

Box = Tuple[int, int, int, int]          # x, y, w, h  (frame coordinates)

FEAT_SIZE = 32
_HOG = cv2.HOGDescriptor((FEAT_SIZE, FEAT_SIZE), (16, 16), (8, 8), (8, 8), 9)


# ============================================================
# Small helpers
# ============================================================
def _read_json(path: Path):
    """Read a JSON file defensively; malformed/stale state is treated as absent."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def _iou(a: Box, b: Box) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    inter = max(0, min(ax + aw, bx + bw) - max(ax, bx)) * max(0, min(ay + ah, by + bh) - max(ay, by))
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _nms(items: List[Tuple[float, Box]], iou_thr: float = 0.45, limit: int = 60) -> List[Tuple[float, Box]]:
    items = sorted(items, key=lambda t: t[0], reverse=True)
    kept: List[Tuple[float, Box]] = []
    for s, b in items:
        if all(_iou(b, k[1]) < iou_thr for k in kept):
            kept.append((s, b))
            if len(kept) >= limit:
                break
    return kept


def _clip_box(b: Box, W: int, H: int) -> Optional[Box]:
    x, y, w, h = b
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return (x0, y0, x1 - x0, y1 - y0)


def fast_mask(crop: np.ndarray) -> np.ndarray:
    """Cheap, deterministic foreground mask used for BOTH training and inference.

    Foreground = pixels that differ from the crop's border colour (median of the
    outer ring) in LAB space, largest blob, holes filled. Using one function in
    both places keeps train/test features consistent.
    """
    h, w = crop.shape[:2]
    if h < 6 or w < 6:
        return np.full((h, w), 255, np.uint8)
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).astype(np.float32)
    ring = max(1, min(h, w) // 8)
    border = np.concatenate([
        lab[:ring].reshape(-1, 3), lab[-ring:].reshape(-1, 3),
        lab[:, :ring].reshape(-1, 3), lab[:, -ring:].reshape(-1, 3)])
    ref = np.median(border, axis=0)
    dist = np.sqrt(((lab - ref) ** 2).sum(axis=2))
    spread = float(np.median(np.sqrt(((border - ref) ** 2).sum(axis=1)))) + 1e-3
    thr = max(16.0, min(60.0, 2.5 * spread + 10.0))
    m = (dist > thr).astype(np.uint8) * 255
    k = max(3, (min(h, w) // 12) | 1)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats((m > 0).astype(np.uint8), 8)
    if n <= 1:
        return np.full((h, w), 255, np.uint8)
    # prefer the component closest to the centre among the larger ones
    best, best_score = 1, -1.0
    cy, cx = h / 2.0, w / 2.0
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < 0.03 * h * w:
            continue
        ccx = stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH] / 2.0
        ccy = stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] / 2.0
        d = np.hypot(ccx - cx, ccy - cy) / max(h, w)
        score = area / float(h * w) - 0.8 * d
        if score > best_score:
            best, best_score = i, score
    comp = (labels == best).astype(np.uint8) * 255
    contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return np.full((h, w), 255, np.uint8)
    filled = np.zeros_like(comp)
    cv2.drawContours(filled, [max(contours, key=cv2.contourArea)], -1, 255, cv2.FILLED)
    return filled


def features(crop_bgr: np.ndarray, frame_h: int) -> np.ndarray:
    """Hue-invariant feature vector for one candidate crop.

    Deliberately NO absolute hue: colour changes between ghost variants, so the
    model must key on shape, glow, saturation, texture and size instead.
    """
    h, w = crop_bgr.shape[:2]
    small = cv2.resize(crop_bgr, (FEAT_SIZE, FEAT_SIZE), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    hog = _HOG.compute(gray).reshape(-1).astype(np.float32)

    mask_full = fast_mask(crop_bgr)
    mask = cv2.resize(mask_full, (FEAT_SIZE, FEAT_SIZE), interpolation=cv2.INTER_NEAREST) > 0
    area = float(mask.sum())
    frac = area / (FEAT_SIZE * FEAT_SIZE)

    # --- shape ---
    mu = cv2.moments(mask.astype(np.uint8), binaryImage=True)
    hu = cv2.HuMoments(mu).reshape(-1)
    hu = -np.sign(hu) * np.log10(np.abs(hu) + 1e-12)
    hu = np.clip(hu, -2, 20) / 10.0
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    solidity = circ = 0.0
    if contours:
        c = max(contours, key=cv2.contourArea)
        ca = cv2.contourArea(c)
        hull = cv2.convexHull(c)
        ha = cv2.contourArea(hull)
        per = cv2.arcLength(c, True)
        solidity = ca / ha if ha > 0 else 0.0
        circ = 4 * np.pi * ca / (per * per) if per > 0 else 0.0
    # vertical / horizontal mass distribution: ghosts are top-heavy blobs with wavy hem
    ys, xs = np.nonzero(mask)
    if len(ys) > 4:
        cyn, cxn = ys.mean() / FEAT_SIZE, xs.mean() / FEAT_SIZE
        syn, sxn = ys.std() / FEAT_SIZE, xs.std() / FEAT_SIZE
    else:
        cyn = cxn = 0.5
        syn = sxn = 0.0
    shape = np.array([frac, solidity, circ, cyn, cxn, syn, sxn, w / max(1.0, h)], np.float32)

    # --- colour statistics (hue-free) ---
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    S = hsv[:, :, 1].astype(np.float32) / 255.0
    V = hsv[:, :, 2].astype(np.float32) / 255.0
    inside = mask if area >= 8 else np.ones_like(mask, bool)
    outside = ~inside if (~inside).sum() >= 8 else inside
    s_in, v_in = S[inside], V[inside]
    s_out, v_out = S[outside], V[outside]
    hue = hsv[:, :, 0][inside & (hsv[:, :, 1] > 60)]
    if hue.size >= 8:
        hist = np.bincount(hue, minlength=180).astype(np.float32)
        hist = sum(np.roll(hist, k) for k in range(-3, 4))
        hist /= hist.sum() + 1e-6
        peak = float(hist.max())
        ent = float(-(hist[hist > 0] * np.log(hist[hist > 0])).sum() / np.log(180))
    else:
        peak, ent = 0.0, 1.0
    # radial glow profile: centre vs rim brightness inside the mask
    yy, xx = np.mgrid[0:FEAT_SIZE, 0:FEAT_SIZE]
    rr = np.hypot(yy - FEAT_SIZE / 2.0, xx - FEAT_SIZE / 2.0) / (FEAT_SIZE / 2.0)
    core = inside & (rr < 0.45)
    rim = inside & (rr >= 0.45)
    glow = (V[core].mean() - V[rim].mean()) if core.any() and rim.any() else 0.0
    edges = cv2.Canny(gray, 40, 120)
    edge_den = float((edges > 0)[inside].mean()) if inside.any() else 0.0
    lap = float(cv2.Laplacian(gray, cv2.CV_32F).var()) / 2000.0
    color = np.array([
        s_in.mean(), s_in.std(), v_in.mean(), v_in.std(),
        s_out.mean(), v_out.mean(),
        s_in.mean() - s_out.mean(), v_in.mean() - v_out.mean(),
        float((v_in > 0.8).mean()), peak, ent, glow, edge_den, min(lap, 3.0),
    ], np.float32)

    size = np.array([np.log(max(4, h) / max(1.0, frame_h)), np.log(max(4, w) / max(1.0, frame_h))], np.float32)
    return np.concatenate([hog, shape, hu.astype(np.float32), color, size]).astype(np.float32)


# ============================================================
# Augmentation: this is what generalises to new colours / facings
# ============================================================
def augment(crop: np.ndarray, rng: random.Random) -> np.ndarray:
    out = crop.copy()
    if rng.random() < 0.5:
        out = out[:, ::-1]                                  # facing left <-> right
    if rng.random() < 0.75:                                 # new colour variant
        hsv = cv2.cvtColor(np.ascontiguousarray(out), cv2.COLOR_BGR2HSV)
        shift = rng.randint(0, 179)
        hsv[:, :, 0] = (hsv[:, :, 0].astype(np.int32) + shift) % 180
        out = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    out = np.ascontiguousarray(out)
    h, w = out.shape[:2]
    if rng.random() < 0.6:                                  # scale + small rotation
        ang = rng.uniform(-12, 12)
        sc = rng.uniform(0.85, 1.2)
        M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, sc)
        out = cv2.warpAffine(out, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
    if rng.random() < 0.5:                                  # brightness / contrast
        a, b = rng.uniform(0.8, 1.25), rng.uniform(-18, 18)
        out = cv2.convertScaleAbs(out, alpha=a, beta=b)
    if rng.random() < 0.3:
        out = cv2.GaussianBlur(out, (3, 3), 0)
    if rng.random() < 0.5:                                  # loose / tight framing
        mx, my = int(w * rng.uniform(0, 0.08)), int(h * rng.uniform(0, 0.08))
        if w - 2 * mx > 6 and h - 2 * my > 6:
            out = out[my:h - my, mx:w - mx]
    return out


# ============================================================
# Tiny MLP (NumPy). Online-friendly, no external ML deps.
# ============================================================
class MLP:
    def __init__(self):
        self.mu: Optional[np.ndarray] = None
        self.sd: Optional[np.ndarray] = None
        self.W1 = self.b1 = self.W2 = self.b2 = None
        self.metrics: Dict[str, float] = {}
        self.ref_h: Optional[int] = None      # frame height the size features were normalised with

    @property
    def trained(self) -> bool:
        return self.W1 is not None

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict probabilities after validating shape and numeric health.

        Invalid feature arrays are rejected loudly instead of silently poisoning
        track scores with NaNs. An untrained model deliberately scores zero.
        """
        X = np.asarray(X, dtype=np.float32)
        if X.ndim != 2:
            raise ValueError(f"expected a 2-D feature matrix, got shape={X.shape}")
        if not self.trained:
            return np.zeros(X.shape[0], dtype=np.float32)
        if self.mu is None or X.shape[1] != self.mu.shape[0]:
            raise ValueError(f"feature width mismatch: got {X.shape[1]}, expected {None if self.mu is None else self.mu.shape[0]}")
        if not np.isfinite(X).all():
            raise ValueError("feature matrix contains NaN or infinity")
        Z = (X - self.mu) / self.sd
        H = np.maximum(0.0, Z @ self.W1 + self.b1)
        o = (H @ self.W2 + self.b2).reshape(-1)
        return (1.0 / (1.0 + np.exp(-np.clip(o, -30, 30)))).astype(np.float32)

    def fit(self, X: np.ndarray, y: np.ndarray, w: np.ndarray, groups: np.ndarray,
            epochs: int = 120, hidden: int = 64, l2: float = 3e-3, seed: int = 0) -> Dict[str, float]:
        X = np.asarray(X, dtype=np.float32)
        y = np.asarray(y, dtype=np.float32).reshape(-1)
        w = np.asarray(w, dtype=np.float32).reshape(-1)
        groups = np.asarray(groups).reshape(-1)
        if X.ndim != 2 or X.shape[0] < 4 or X.shape[1] < 1:
            raise ValueError(f"training features must be a non-empty 2-D matrix, got {X.shape}")
        if not (len(y) == len(w) == len(groups) == X.shape[0]):
            raise ValueError("training features, labels, weights, and groups must have equal lengths")
        if not np.isfinite(X).all() or not np.isfinite(y).all() or not np.isfinite(w).all():
            raise ValueError("training data contains NaN or infinity")
        if np.any(w <= 0) or not np.isin(y, [0.0, 1.0]).all():
            raise ValueError("sample weights must be positive and labels must be 0 or 1")
        if not np.any(y > 0.5) or not np.any(y <= 0.5):
            raise ValueError("training requires both positive and negative samples")
        if int(epochs) < 1 or int(hidden) < 1:
            raise ValueError("epochs and hidden width must be positive")
        rng = np.random.default_rng(seed)
        # hold out whole source samples (not augmented siblings) to measure honestly
        uniq = np.unique(groups)
        # Split by source group and stratify by class. The old unstratified random
        # split could place the only positive source in validation, leaving the
        # optimizer with no positive training examples while still reporting a model.
        val_groups = set()
        group_label = {}
        for group_id in uniq.tolist():
            ids = np.flatnonzero(groups == group_id)
            group_label[group_id] = float(y[ids[0]])
        pos_groups = np.asarray([g for g in uniq if group_label[g] > 0.5])
        neg_groups = np.asarray([g for g in uniq if group_label[g] <= 0.5])
        if len(uniq) >= 20 and len(pos_groups) >= 2 and len(neg_groups) >= 2:
            for class_groups in (pos_groups, neg_groups):
                class_groups = class_groups.copy()
                rng.shuffle(class_groups)
                n_class_val = min(len(class_groups) - 1, max(1, int(round(0.15 * len(class_groups)))))
                val_groups.update(class_groups[:n_class_val].tolist())
        is_val = np.array([g in val_groups for g in groups])
        n_val = int(is_val.sum())
        tr, va = ~is_val, is_val
        mu = X[tr].mean(axis=0)
        sd = X[tr].std(axis=0) + 1e-3
        Z = (X - mu) / sd
        d = Z.shape[1]
        W1 = rng.normal(0, np.sqrt(2.0 / d), (d, hidden)).astype(np.float32)
        b1 = np.zeros(hidden, np.float32)
        W2 = rng.normal(0, np.sqrt(1.0 / hidden), (hidden, 1)).astype(np.float32)
        b2 = np.zeros(1, np.float32)
        params = [W1, b1, W2, b2]
        m = [np.zeros_like(p) for p in params]
        v = [np.zeros_like(p) for p in params]
        pos_w = w[tr & (y > 0.5)].sum() + 1e-6
        neg_w = w[tr & (y <= 0.5)].sum() + 1e-6
        class_scale = np.where(y > 0.5, 0.5 / pos_w, 0.5 / neg_w).astype(np.float32)  # balanced classes
        sw = (w * class_scale).astype(np.float32)
        sw = sw / (sw[tr].mean() + 1e-9)
        idx_tr = np.nonzero(tr)[0]
        best = None
        best_loss = 1e9
        t = 0
        bs = 128
        lr = 3e-3
        for ep in range(epochs):
            rng.shuffle(idx_tr)
            for s in range(0, len(idx_tr), bs):
                bi = idx_tr[s:s + bs]
                zb = Z[bi]
                # light feature dropout noise for robustness with few samples
                zb = zb * (rng.random(zb.shape) > 0.1).astype(np.float32)
                H = np.maximum(0.0, zb @ params[0] + params[1])
                o = (H @ params[2] + params[3]).reshape(-1)
                p = 1.0 / (1.0 + np.exp(-np.clip(o, -30, 30)))
                g = ((p - y[bi]) * sw[bi]).reshape(-1, 1) / len(bi)
                gW2 = H.T @ g + l2 * params[2]
                gb2 = g.sum(axis=0)
                gH = (g @ params[2].T) * (H > 0)
                gW1 = zb.T @ gH + l2 * params[0]
                gb1 = gH.sum(axis=0)
                t += 1
                for i, gr in enumerate((gW1, gb1, gW2, gb2)):
                    m[i] = 0.9 * m[i] + 0.1 * gr
                    v[i] = 0.999 * v[i] + 0.001 * gr * gr
                    params[i] -= lr * (m[i] / (1 - 0.9 ** t)) / (np.sqrt(v[i] / (1 - 0.999 ** t)) + 1e-8)
            if n_val and (ep % 5 == 4 or ep == epochs - 1):
                H = np.maximum(0.0, Z[va] @ params[0] + params[1])
                o = (H @ params[2] + params[3]).reshape(-1)
                p = 1.0 / (1.0 + np.exp(-np.clip(o, -30, 30)))
                loss = float(-(sw[va] * (y[va] * np.log(p + 1e-7) + (1 - y[va]) * np.log(1 - p + 1e-7))).mean())
                if loss < best_loss:
                    best_loss = loss
                    best = [q.copy() for q in params]
        if best is not None:
            params = best
        self.mu, self.sd = mu.astype(np.float32), sd.astype(np.float32)
        self.W1, self.b1, self.W2, self.b2 = params
        metrics: Dict[str, float] = {"n_train": int(tr.sum()), "n_val": int(va.sum())}
        if n_val:
            p = self.predict(X[va])
            yy = y[va] > 0.5
            tp = float(((p >= 0.5) & yy).sum())
            fp = float(((p >= 0.5) & ~yy).sum())
            fn = float(((p < 0.5) & yy).sum())
            metrics["val_precision"] = tp / (tp + fp) if tp + fp else 0.0
            metrics["val_recall"] = tp / (tp + fn) if tp + fn else 0.0
        self.metrics = metrics
        return metrics

    def save(self, path: Path) -> None:
        """Persist a complete model atomically; never replace a good model with a partial file."""
        if not self.trained or any(v is None for v in (self.mu, self.sd, self.W1, self.b1, self.W2, self.b2)):
            raise ValueError("cannot save an untrained or incomplete model")
        self._validate_arrays(self.mu, self.sd, self.W1, self.b1, self.W2, self.b2)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.stem + ".tmp.npz")
        try:
            with tmp.open("wb") as handle:
                np.savez_compressed(handle, mu=self.mu, sd=self.sd, W1=self.W1, b1=self.b1,
                                    W2=self.W2, b2=self.b2,
                                    metrics=json.dumps(self.metrics, allow_nan=False),
                                    ref_h=np.int32(self.ref_h or 0))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _validate_arrays(mu, sd, W1, b1, W2, b2) -> None:
        arrays = [np.asarray(v) for v in (mu, sd, W1, b1, W2, b2)]
        if any(a.dtype.kind not in "fiu" or not np.isfinite(a).all() for a in arrays):
            raise ValueError("model arrays must be finite numeric arrays")
        mu, sd, W1, b1, W2, b2 = arrays
        if mu.ndim != 1 or sd.shape != mu.shape or W1.ndim != 2:
            raise ValueError("inconsistent model input/normalization dimensions")
        if W1.shape[0] != mu.size or b1.shape != (W1.shape[1],):
            raise ValueError("inconsistent first-layer dimensions")
        if W2.shape != (W1.shape[1], 1) or b2.shape not in ((1,), ()):
            raise ValueError("inconsistent output-layer dimensions")
        if mu.size == 0 or W1.shape[1] == 0 or np.any(sd <= 0):
            raise ValueError("model dimensions and normalization scales must be positive")

    def load(self, path: Path) -> bool:
        """Load and validate into temporaries; a corrupt model never half-mutates this object."""
        path = Path(path)
        if not path.is_file():
            return False
        try:
            with np.load(path, allow_pickle=False) as z:
                required = {"mu", "sd", "W1", "b1", "W2", "b2", "metrics"}
                if not required.issubset(set(z.files)):
                    raise ValueError("missing model arrays: " + ", ".join(sorted(required - set(z.files))))
                mu, sd, W1, b1, W2, b2 = (np.asarray(z[k], dtype=np.float32).copy()
                                           for k in ("mu", "sd", "W1", "b1", "W2", "b2"))
                raw_metrics = z["metrics"]
                metrics = json.loads(str(raw_metrics.item() if raw_metrics.shape == () else raw_metrics))
                ref_h = int(z["ref_h"].item()) if "ref_h" in z.files else 0
            self._validate_arrays(mu, sd, W1, b1, W2, b2)
            if not isinstance(metrics, dict):
                raise ValueError("model metrics must be a JSON object")
            if ref_h < 0:
                raise ValueError("model reference frame height cannot be negative")
            self.mu, self.sd, self.W1, self.b1, self.W2, self.b2 = mu, sd, W1, b1, W2, b2
            self.metrics = metrics
            self.ref_h = ref_h or None
            return True
        except Exception as exc:
            log.warning("SMART: refusing invalid model %s: %s", path.name, exc)
            return False


# ============================================================
# Proposals: class-agnostic, so unseen colours/shapes still get looked at
# ============================================================
class MotionProposer:
    """Moving-object proposals from a slowly adapting background model.

    Ghosts drift across a mostly static room, so |frame - background| isolates
    them at their *current* position (frame differencing would give a double
    blob). A camera pan trips the global-change guard and resets the model.
    """

    def __init__(self, work_width: int = 480):
        self.work_width = work_width
        self.bg: Optional[np.ndarray] = None
        self.prev_small: Optional[np.ndarray] = None
        self.scale = 1.0
        self.global_change = 0.0

    def reset(self) -> None:
        self.bg = None
        self.prev_small = None

    def propose(self, frame: np.ndarray) -> List[Tuple[float, Box]]:
        H, W = frame.shape[:2]
        sc = min(1.0, self.work_width / float(W))
        small = cv2.resize(frame, (max(8, int(W * sc)), max(8, int(H * sc))), interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (3, 3), 0)
        if self.bg is None or self.bg.shape != small.shape:
            self.bg = small.astype(np.float32)
            self.prev_small = small
            return []

        def chmax(a: np.ndarray, b: np.ndarray) -> np.ndarray:
            d = cv2.absdiff(a, b)
            return cv2.max(cv2.max(d[:, :, 0], d[:, :, 1]), d[:, :, 2])

        diff_bg = chmax(small, self.bg.astype(np.uint8))
        diff_prev = chmax(small, self.prev_small)
        self.prev_small = small
        changed = float(np.count_nonzero(diff_bg > 30)) / diff_bg.size
        self.global_change = changed
        if changed > 0.30:           # camera moved / scene cut: relearn background
            self.bg = small.astype(np.float32)
            return []
        fg_u8 = ((diff_bg > 26) & (diff_prev > 4)).astype(np.uint8) * 255   # differs from room AND still changing
        # slow background update: fast where nothing moves, almost frozen under blobs
        inv = cv2.bitwise_not(fg_u8)
        cv2.accumulateWeighted(small, self.bg, 0.04, inv)
        cv2.accumulateWeighted(small, self.bg, 0.004, fg_u8)
        k = max(3, int(round(small.shape[1] * 0.012)) | 1)
        fg_u8 = cv2.morphologyEx(fg_u8, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        fg_u8 = cv2.morphologyEx(fg_u8, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k * 2 + 1, k * 2 + 1)))
        n, labels, stats, _ = cv2.connectedComponentsWithStats(fg_u8, 8)
        min_area = max(30, int(0.00035 * small.shape[0] * small.shape[1]))
        out = []
        back = 1.0 / sc
        for i in range(1, n):
            x, y, w, h, a = [int(v) for v in stats[i]]
            if a < min_area or w * h > 0.35 * small.shape[0] * small.shape[1]:
                continue
            out.append((0.5 + min(0.5, a / float(w * h) * 0.5),
                        (int(x * back), int(y * back), int(w * back), int(h * back))))
        return out


# ============================================================
# Tracking
# ============================================================
@dataclass
class Track:
    tid: int
    box: Box
    t_first: float
    t_last: float
    vx: float = 0.0
    vy: float = 0.0
    hits: int = 1
    p: float = 0.0
    p_n: int = 0
    last_scored: float = 0.0
    last_feat_crop: Optional[np.ndarray] = None
    clicked_at: float = 0.0
    origin: Tuple[float, float] = (0.0, 0.0)
    neg_logged: int = 0
    pos_logged: bool = False
    retries: int = 0
    auto_logged: bool = False          # the overlay auto-learner already took a sample from this track

    @property
    def center(self) -> Tuple[float, float]:
        return self.box[0] + self.box[2] / 2.0, self.box[1] + self.box[3] / 2.0

    @property
    def speed(self) -> float:
        return float(np.hypot(self.vx, self.vy))


class Tracker:
    def __init__(self):
        self.tracks: Dict[int, Track] = {}
        self._next = 1

    def update(self, boxes: List[Box], now: float, frame_h: int) -> List[Track]:
        unmatched = list(range(len(boxes)))
        used = set()
        for tid, tr in sorted(self.tracks.items(), key=lambda kv: -kv[1].hits):
            dt = max(1e-3, now - tr.t_last)
            px = tr.center[0] + tr.vx * dt
            py = tr.center[1] + tr.vy * dt
            best, best_d = None, 1e9
            gate = max(0.035 * frame_h, 0.9 * max(tr.box[2], tr.box[3])) + tr.speed * dt * 0.5
            for i in unmatched:
                if i in used:
                    continue
                bx, by, bw, bh = boxes[i]
                d = float(np.hypot(bx + bw / 2.0 - px, by + bh / 2.0 - py))
                if d < gate and d < best_d:
                    best, best_d = i, d
            if best is not None:
                used.add(best)
                bx, by, bw, bh = boxes[best]
                ncx, ncy = bx + bw / 2.0, by + bh / 2.0
                ocx, ocy = tr.center
                ivx, ivy = (ncx - ocx) / dt, (ncy - ocy) / dt
                a = 0.5
                tr.vx = (1 - a) * tr.vx + a * ivx
                tr.vy = (1 - a) * tr.vy + a * ivy
                tr.box = (bx, by, bw, bh)
                tr.t_last = now
                tr.hits += 1
        for i, b in enumerate(boxes):
            if i in used:
                continue
            tr = Track(self._next, b, now, now)
            tr.origin = tr.center
            self.tracks[self._next] = tr
            self._next += 1
        for tid in [t for t, tr in self.tracks.items() if now - tr.t_last > 0.4]:
            self.tracks.pop(tid)
        return [tr for tr in self.tracks.values() if tr.t_last == now]


# ============================================================
# Sample store
# ============================================================
class SampleStore:
    def __init__(self, root: Path, max_neg: int = 5000, max_pos: int = 3000):
        self.dir = root
        self.pos_dir = root / "positives"
        self.neg_dir = root / "negatives"
        self.pos_dir.mkdir(parents=True, exist_ok=True)
        self.neg_dir.mkdir(parents=True, exist_ok=True)
        self.max_neg, self.max_pos = max_neg, max_pos
        self.pos: List[Tuple[Path, float]] = []
        self.neg: List[Tuple[Path, float]] = []
        self.lock = threading.Lock()
        self._scan()

    def _scan(self) -> None:
        def load_dir(d: Path):
            out = []
            for p in sorted(d.glob("*.png")):
                try:
                    wt = float(p.stem.split("_w")[-1]) if "_w" in p.stem else 1.0
                except ValueError:
                    wt = 1.0
                out.append((p, wt))
            return out
        self.pos, self.neg = load_dir(self.pos_dir), load_dir(self.neg_dir)

    def add(self, crop: np.ndarray, positive: bool, weight: float, tag: str) -> Optional[Path]:
        d = self.pos_dir if positive else self.neg_dir
        stamp = int(time.time() * 1000)
        name = f"{stamp}_{tag}_w{weight:.2f}.png"
        path = d / name
        while path.exists():                     # two samples in the same millisecond must not overwrite each other
            stamp += 1
            path = d / f"{stamp}_{tag}_w{weight:.2f}.png"
        if cv2.imwrite(str(path), crop):
            with self.lock:
                lst = self.pos if positive else self.neg
                lst.append((path, weight))
                cap = self.max_pos if positive else self.max_neg
                while len(lst) > cap:
                    old, _ = lst.pop(0)
                    try:
                        old.unlink()
                    except OSError:
                        pass
            return path
        return None

    def discard(self, path: Path) -> bool:
        """Delete a sample outright (used to undo an overlay action the same minute)."""
        path = Path(path)
        with self.lock:
            self.pos = [(q, w) for q, w in self.pos if q != path]
            self.neg = [(q, w) for q, w in self.neg if q != path]
        try:
            path.unlink()
            return True
        except OSError:
            return False

    def snapshot(self):
        with self.lock:
            return list(self.pos), list(self.neg)

    # ---- curation (used by the auto-cleaner and the GUI sample manager) ----
    @property
    def quar_dir(self) -> Path:
        return self.dir / "quarantine"

    def rescan(self) -> None:
        """Re-read the folders (files may have been moved/deleted by the GUI)."""
        with self.lock:
            self._scan()

    @staticmethod
    def tag_of(path: Path) -> str:
        parts = path.stem.split("_")
        return parts[1] if len(parts) >= 3 else ""

    def quarantine(self, path: Path) -> bool:
        """Move a sample out of the training set, reversibly."""
        path = Path(path)
        label = "positives" if path.parent.name == "positives" else "negatives"
        dst_dir = self.quar_dir / label
        dst_dir.mkdir(parents=True, exist_ok=True)
        try:
            if path.exists():
                os.replace(path, dst_dir / path.name)
        except OSError:
            return False
        with self.lock:
            self.pos = [(q, w) for q, w in self.pos if q != path]
            self.neg = [(q, w) for q, w in self.neg if q != path]
        return True

    def restore(self, path: Path) -> bool:
        path = Path(path)
        label = "positives" if path.parent.name == "positives" else "negatives"
        dst = (self.pos_dir if label == "positives" else self.neg_dir) / path.name
        try:
            os.replace(path, dst)
        except OSError:
            return False
        self.rescan()
        return True

    def flip(self, path: Path) -> bool:
        """Move a sample to the opposite class (it was labelled the wrong way round)."""
        path = Path(path)
        to_pos = path.parent.name == "negatives"
        dst = (self.pos_dir if to_pos else self.neg_dir) / path.name
        try:
            os.replace(path, dst)
        except OSError:
            return False
        self.rescan()
        return True


def _read_bgr(path: Path) -> Optional[np.ndarray]:
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return np.ascontiguousarray(img[:, :, :3])


# ============================================================
# Main class
# ============================================================
@dataclass
class Pick:
    tid: int
    frame_x: int
    frame_y: int
    screen_x: int
    screen_y: int
    p: float
    box: Box
    probe: bool = False


@dataclass
class _Pending:
    """One bot click waiting for its verdict (visual check at `due`, ecto check until deadline)."""
    tid: int
    due: float
    box: Box
    crop: np.ndarray
    center0: Tuple[float, float]
    p: float
    t_click: float = 0.0
    probe: bool = False
    verdict: Optional[str] = None      # None until `due`; then static | gone | moving | unknown
    confirmed: bool = False            # an ecto gain was attributed to this click
    ambiguous: bool = False            # several clicks were in the window when the gain arrived
    vetoed: bool = False               # player pressed F8 on it
    retry_pending: bool = False
    amount: int = 0
    latency: float = 0.0


class SmartGhost:
    def __init__(self, root: Path, cfg, ref_frame_h: int = 720):
        self.cfg = cfg
        # Auto play: use the saved model as-is. Nothing is learned, saved, relabelled or retrained.
        self.autoplay = bool(getattr(cfg, "smart_autoplay", False))
        self.dir = Path(root) / "smart"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.store = SampleStore(self.dir)
        self.model = MLP()
        self.model_path = self.dir / "model.npz"
        if self.model.load(self.model_path):
            log.info("SMART: loaded model %s", self.model.metrics)
        self.motion = MotionProposer()
        self.tracker = Tracker()
        self.ring: deque = deque(maxlen=14)           # (t, frame, rect)
        self._clicks: deque = deque(maxlen=64)        # raw user clicks awaiting processing
        self._bot_clicks: deque = deque(maxlen=64)    # (t, x, y) clicks the bot itself sent
        self._lock = threading.Lock()
        self._listener = None
        self._await: List[_Pending] = []              # bot clicks awaiting visual + ecto verdict
        self._gains: deque = deque(maxlen=64)         # (t_seen, amount) from the webhook thread
        self._used_user: set = set()                  # user clicks already credited with a gain
        self._hits: deque = deque(maxlen=30)          # 1 = ecto-confirmed, 0 = classification failure
        self._lat: deque = deque(maxlen=60)           # click -> toast latencies (s)
        self._thr_adj = 0.0
        self._last_probe = 0.0
        self.feed_alive = lambda: False               # main.py wires this to reporter.feed_alive
        self.ecto_log = self.dir / "ecto_log.jsonl"
        self._wave_until = 0.0                        # wave/boss mode: reward comes once at the END, not per click
        self._wave_clicks = 0
        self._wave_gone = 0
        self._click_times: deque = deque(maxlen=12)
        self._last_confirm_t = 0.0
        self._recent_user_clicks: deque = deque(maxlen=50)   # (t, fx, fy)
        self._last_smart: Optional[_Pending] = None
        self._last_props: List[Tuple[float, Box]] = []
        self._latency = 0.06
        self._train_lock = threading.Lock()
        self._training = False
        self._since_train_pos = 0
        self._since_train_neg = 0
        self._last_train = 0.0
        self._last_neg_scan = 0.0
        self.popup = False
        self.frame_h = ref_frame_h
        self.last_tracks: List[Track] = []
        self.stats = {"user_clicks": 0, "pos_added": 0, "neg_added": 0, "smart_clicks": 0,
                      "trained": 0, "ignored_clicks": 0}
        self._rng = random.Random(7)
        # LRU is bounded by bytes, not entry count. Feature vectors are small, but
        # 60,000 augmented entries can still consume hundreds of MiB.
        self._fcache: OrderedDict[Tuple[str, int, int, float, int, int], List[Optional[np.ndarray]]] = OrderedDict()
        self._fcache_bytes = 0
        self._fcache_limit_bytes = 64 * 1024 * 1024
        self._last_clean_total = 0
        self._last_cmd_poll = 0.0
        self.cmd_path = self.dir / "command.json"
        self.status_path = self.dir / "status.json"
        self.review_path = self.dir / "review.json"
        self.stats["auto_removed"] = 0
        self.stats.update({"ov_confirm": 0, "ov_reject": 0, "ov_auto": 0})
        self._last_ov_auto = 0.0
        self.stats.update({"ecto_gains": 0, "ecto_bot": 0, "ecto_user": 0, "ecto_unattributed": 0,
                           "ecto_positives": 0, "aim_misses": 0, "retries": 0, "probes": 0, "ecto_amount": 0})

    # ---------------- lifecycle ----------------
    def start_listener(self) -> bool:
        if self.autoplay:
            log.info("SMART: AUTO PLAY - not watching your clicks, nothing will be learned.")
            return False
        if not HAS_PYNPUT:
            log.warning("SMART: pynput missing, cannot learn from your clicks. pip install pynput")
            return False
        if self._listener is not None:
            return True

        def on_click(x, y, button, pressed, *_):
            if pressed and button == _pmouse.Button.left:
                self.on_user_click(int(x), int(y), time.time())
            return True

        self._listener = _pmouse.Listener(on_click=on_click)
        self._listener.daemon = True
        self._listener.start()
        log.info("SMART: watching your clicks (left button). Click ghosts normally and it learns.")
        return True

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    # ---------------- inputs ----------------
    def note_bot_click(self, x: int, y: int) -> None:
        """Called right BEFORE the bot sends a click so the listener can ignore it."""
        with self._lock:
            self._bot_clicks.append((time.time(), int(x), int(y)))

    def on_user_click(self, sx: int, sy: int, t: float) -> None:
        if self.autoplay:
            return
        with self._lock:
            for bt, bx, by in self._bot_clicks:
                if abs(t - bt) < 0.25 and abs(sx - bx) <= 4 and abs(sy - by) <= 4:
                    return                                   # that was the bot, not the player
            self._clicks.append((t, int(sx), int(sy)))
        self.stats["user_clicks"] += 1

    # ---------------- learning from the on-screen overlay ----------------
    def _track_for_box(self, box: Box, min_iou: float = 0.3) -> Optional[Track]:
        best, bi = None, min_iou
        for tr in self.last_tracks:
            v = _iou(tr.box, box)
            if v >= bi:
                best, bi = tr, v
        return best

    def overlay_feedback(self, frame: np.ndarray, box: Box, positive: bool,
                         weight_scale: float = 1.0) -> Optional[Path]:
        """You told the overlay "this box IS / is NOT a ghost". Saved like a click (positive) or like F8 (negative).
        Returns the saved sample path (for undo), or None when nothing was learned."""
        if self.autoplay:
            return None                                   # AUTO PLAY never learns
        crop = self._crop(frame, tuple(int(v) for v in box), pad=0.10)
        if crop is None:
            return None
        H = frame.shape[0]
        weight = (1.2 if positive else 1.5) * float(weight_scale)
        if self.model.trained:
            p = float(self.model.predict(features(crop, self.model.ref_h or H)[None, :])[0])
            if (positive and p < 0.5) or (not positive and p > 0.5):
                weight *= 1.5                             # the model was wrong here: learn harder
        path = self.store.add(crop, positive, weight, "ovconf" if positive else "ovrej")
        if path is None:
            return None
        tr = self._track_for_box(tuple(int(v) for v in box))
        if positive:
            if tr is not None:
                tr.pos_logged = True
            self.stats["ov_confirm"] += 1
            self.stats["pos_added"] += 1
            self._since_train_pos += 1
        else:
            if tr is not None:
                tr.neg_logged = max(tr.neg_logged, 2)     # stop the scenery miner re-adding it
            self.stats["ov_reject"] += 1
            self.stats["neg_added"] += 1
            self._since_train_neg += 3                    # same push as F8
        log.info("SMART: overlay %s: %s sample saved box=%dx%d weight=%.2f total_pos=%d total_neg=%d",
                 "confirmed" if positive else "rejected", "positive" if positive else "negative",
                 int(box[2]), int(box[3]), weight, len(self.store.pos), len(self.store.neg))
        return path

    def overlay_undo(self, path: Path) -> bool:
        """Take back one overlay_feedback() sample."""
        was_pos = Path(path).parent.name == "positives"
        if not self.store.discard(path):
            return False
        key = "ov_confirm" if was_pos else "ov_reject"
        self.stats[key] = max(0, self.stats[key] - 1)
        return True

    def overlay_auto_learn(self, frame: np.ndarray, boxes: List[Box], now: float) -> int:
        """Learn from boxes the overlay is SHOWING, with no input from you - but only the safest ones:
        the model is very sure (p high for several frames), the box really moves (scenery is not a ghost),
        nobody clicked it, and the share of such self-labelled samples stays small. They are saved with the
        'ovauto' tag at low weight, so auto-clean drops them first and the Sample manager can filter them.
        Never active in AUTO PLAY. Returns the number of samples added (0 or 1 per call)."""
        cfg = self.cfg
        if self.autoplay or not bool(getattr(cfg, "overlay_auto_learn", True)):
            return 0
        if self.popup or not self.model.trained or not self.ready():
            return 0
        if now - self._last_ov_auto < float(getattr(cfg, "overlay_auto_interval_s", 2.0)):
            return 0
        if self.stats["ov_auto"] >= int(getattr(cfg, "overlay_auto_max_session", 60)):
            return 0
        pos, _neg = self.store.snapshot()
        n_auto = sum(1 for q, _w in pos if SampleStore.tag_of(q) == "ovauto")
        if (n_auto + 1) > float(getattr(cfg, "overlay_auto_max_share", 0.25)) * (len(pos) + 1):
            return 0
        H = frame.shape[0]
        min_p = float(getattr(cfg, "overlay_auto_min_p", 0.93))
        awaiting = {pd.tid for pd in self._await}
        best, best_p = None, 0.0
        for b in boxes:
            tr = self._track_for_box(tuple(int(v) for v in b[:4]))
            if tr is None or tr.auto_logged or tr.pos_logged or tr.neg_logged or tr.clicked_at:
                continue
            if tr.tid in awaiting:
                continue                                  # a bot click on it is still being judged
            if tr.p_n < 3 or tr.p < min_p or tr.hits < 8 or now - tr.t_first < 0.8:
                continue
            if tr.speed < 0.01 * H:
                continue                                  # sits still: scenery, not a ghost
            cx, cy = tr.center
            if self._excluded(int(cx), int(cy)):
                continue
            if tr.p > best_p:
                best, best_p = tr, tr.p
        if best is None:
            return 0
        crop = self._crop(frame, best.box, pad=0.10)
        if crop is None:
            return 0
        weight = float(getattr(cfg, "overlay_auto_weight", 0.35))
        if self.store.add(crop, True, weight, "ovauto") is None:
            return 0
        best.auto_logged = True
        best.pos_logged = True
        self._last_ov_auto = now
        self.stats["ov_auto"] += 1
        self.stats["pos_added"] += 1                      # counted, but it does not trigger a retrain by itself
        log.info("SMART: overlay auto-learned a ghost p=%.2f box=%dx%d weight=%.2f (auto samples %d/%d positives)",
                 best.p, best.box[2], best.box[3], weight, n_auto + 1, len(pos) + 1)
        return 1

    def mark_bad(self) -> None:
        """Hotkey: the bot's most recent smart click was wrong -> teach a negative."""
        if self.autoplay:
            log.info("SMART: AUTO PLAY - bad-click marking is ignored (no training).")
            return
        p = self._last_smart
        if p is None:
            log.info("SMART: nothing to mark as bad yet.")
            return
        p.vetoed = True                                  # never let a later ecto flip this to a positive
        self.store.add(p.crop, False, 1.5, "bad")
        self.stats["neg_added"] += 1
        self._since_train_neg += 3
        self._last_smart = None
        log.info("SMART: marked last smart click as NOT a ghost (negative, weight 1.5)")

    # ---------------- per frame ----------------
    def on_frame(self, frame: np.ndarray, rect: Dict[str, int], now: float,
                 extra_boxes: Optional[List[Tuple[float, int, int, int, int]]] = None,
                 popup: bool = False) -> None:
        """Feed every captured frame. Cheap: bookkeeping + proposals + tracking."""
        self.popup = popup
        if popup and self._wave_clicks:                # the end-of-wave banner: the reward toast follows
            self._wave_until = max(self._wave_until, now + 20.0)
        self.frame_h = frame.shape[0]
        self.ring.append((now, frame, dict(rect)))
        props = self.motion.propose(frame)
        H, W = frame.shape[:2]
        cand = list(props)
        for item in (extra_boxes or []):
            s, x, y, w, h = item
            cand.append((float(min(1.0, s)) * 0.8, (int(x), int(y), int(w), int(h))))
        min_side = max(14, int(0.028 * H))
        max_side = int(0.45 * H)
        filt = []
        for s, b in cand:
            cb = _clip_box(b, W, H)
            if cb is None:
                continue
            if cb[2] < min_side or cb[3] < min_side or cb[2] > max_side or cb[3] > max_side:
                continue
            filt.append((s, cb))
        kept = _nms(filt, 0.4, 50)
        self._last_props = kept
        self.last_tracks = self.tracker.update([b for _, b in kept], now, H)
        if self.autoplay:
            # Keep click bookkeeping + aim-miss retries working, but learn nothing.
            with self._lock:
                self._clicks.clear()
            self._process_ecto(now)
            self._process_pending(frame, now)
            self._poll_commands(now)
            return
        self._process_clicks(now)
        self._process_ecto(now)
        self._process_pending(frame, now)
        self._mine_negatives(frame, now)
        self._maybe_train(now)
        self._poll_commands(now)

    # ---------------- click -> positive sample ----------------
    def _frame_before(self, t_click: float, lookback: float = 0.04):
        target = t_click - lookback
        best, best_dt = None, 1e9
        for item in self.ring:
            dt = abs(item[0] - target)
            if item[0] <= t_click and dt < best_dt:
                best, best_dt = item, dt
        return best

    def _segment_click(self, frame: np.ndarray, fx: int, fy: int) -> Optional[Tuple[Box, float]]:
        """Return (box, quality) of the object under the click."""
        H, W = frame.shape[:2]
        # 1) a proposal (motion/edge/colour) that contains the click, smallest sane one
        best = None
        for s, b in self._last_props:
            x, y, w, h = b
            m = 0.12 * max(w, h)
            if x - m <= fx <= x + w + m and y - m <= fy <= y + h + m:
                cx, cy = x + w / 2.0, y + h / 2.0
                score = np.hypot(fx - cx, fy - cy) / max(w, h) + 0.002 * (w * h) ** 0.5
                if best is None or score < best[0]:
                    best = (score, b)
        if best is not None:
            return best[1], 1.0
        # 2) GrabCut seeded at the click
        R = int(max(40, 0.09 * H))
        x0, y0 = max(0, fx - R), max(0, fy - R)
        x1, y1 = min(W, fx + R), min(H, fy + R)
        win = frame[y0:y1, x0:x1]
        if win.shape[0] < 30 or win.shape[1] < 30:
            return None
        gm = np.full(win.shape[:2], cv2.GC_PR_BGD, np.uint8)
        cx, cy = fx - x0, fy - y0
        cv2.circle(gm, (cx, cy), int(R * 0.45), cv2.GC_PR_FGD, -1)
        cv2.circle(gm, (cx, cy), max(3, int(R * 0.08)), cv2.GC_FGD, -1)
        gm[0, :] = gm[-1, :] = gm[:, 0] = gm[:, -1] = cv2.GC_BGD
        try:
            bgd = np.zeros((1, 65), np.float64)
            fgd = np.zeros((1, 65), np.float64)
            cv2.grabCut(win, gm, None, bgd, fgd, 3, cv2.GC_INIT_WITH_MASK)
        except cv2.error:
            return None
        fgm = ((gm == cv2.GC_FGD) | (gm == cv2.GC_PR_FGD)).astype(np.uint8)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(fgm, 8)
        lbl = labels[min(cy, labels.shape[0] - 1), min(cx, labels.shape[1] - 1)]
        if lbl == 0:
            return None
        x, y, w, h, a = [int(v) for v in stats[lbl]]
        if a < 0.04 * win.shape[0] * win.shape[1] or a > 0.75 * win.shape[0] * win.shape[1]:
            return None
        return (x0 + x, y0 + y, w, h), 0.7

    def _process_clicks(self, now: float) -> None:
        while True:
            with self._lock:
                if not self._clicks:
                    return
                t, sx, sy = self._clicks.popleft()
            if self.popup:
                self.stats["ignored_clicks"] += 1
                continue
            entry = self._frame_before(t)
            if entry is None:
                self.stats["ignored_clicks"] += 1
                continue
            ft, frame, rect = entry
            fx, fy = sx - rect["left"], sy - rect["top"]
            H, W = frame.shape[:2]
            if not (0 <= fx < W and 0 <= fy < H):
                self.stats["ignored_clicks"] += 1
                continue
            if self._excluded(fx, fy):
                self.stats["ignored_clicks"] += 1
                continue
            self._recent_user_clicks.append((t, fx, fy))
            seg = self._segment_click(frame, fx, fy)
            if seg is None:
                self.stats["ignored_clicks"] += 1
                log.debug("SMART: click at (%d,%d) had no recognisable object; ignored", fx, fy)
                continue
            box, quality = seg
            crop = self._crop(frame, box, pad=0.10)
            if crop is None:
                continue
            # weight: a click on something we did not expect is more valuable
            tr = self._track_at(fx, fy)
            moving = tr is not None and tr.speed > 0.01 * H
            weight = 1.0 * quality * (1.0 if moving else 0.6)
            if self.model.trained:
                p = float(self.model.predict(features(crop, self.model.ref_h or H)[None, :])[0])
                if p < 0.5:
                    weight *= 1.5        # model missed this ghost: learn harder from it
            if tr is not None:
                tr.pos_logged = True
                tr.clicked_at = t
            self.store.add(crop, True, weight, "user")
            self.stats["pos_added"] += 1
            self._since_train_pos += 1
            log.info("SMART: learned ghost from your click at (%d,%d) box=%dx%d weight=%.2f total_pos=%d",
                     fx, fy, box[2], box[3], weight, len(self.store.pos))

    def _excluded(self, fx: int, fy: int) -> bool:
        for ex, ey, ew, eh in (getattr(self.cfg, "exclusion_zones", None) or []):
            if ex <= fx <= ex + ew and ey <= fy <= ey + eh:
                return True
        return False

    def _track_at(self, fx: int, fy: int) -> Optional[Track]:
        best, bd = None, 1e9
        for tr in self.last_tracks:
            x, y, w, h = tr.box
            m = 0.15 * max(w, h)
            if x - m <= fx <= x + w + m and y - m <= fy <= y + h + m:
                d = np.hypot(fx - (x + w / 2.0), fy - (y + h / 2.0))
                if d < bd:
                    best, bd = tr, d
        return best

    @staticmethod
    def _crop(frame: np.ndarray, box: Box, pad: float = 0.1) -> Optional[np.ndarray]:
        H, W = frame.shape[:2]
        x, y, w, h = box
        px, py = int(w * pad), int(h * pad)
        x0, y0 = max(0, x - px), max(0, y - py)
        x1, y1 = min(W, x + w + px), min(H, y + h + py)
        if x1 - x0 < 8 or y1 - y0 < 8:
            return None
        return frame[y0:y1, x0:x1].copy()

    # ---------------- negatives ----------------
    def _recently_clicked_near(self, fx: float, fy: float, now: float, radius: float, window: float = 1.5) -> bool:
        for t, cx, cy in self._recent_user_clicks:
            if abs(now - t) <= window and np.hypot(cx - fx, cy - fy) <= radius:
                return True
        return False

    def _mine_negatives(self, frame: np.ndarray, now: float) -> None:
        """Things that never move or react are not ghosts: free negative labels."""
        if now - self._last_neg_scan < 0.5:
            return
        self._last_neg_scan = now
        H = frame.shape[0]
        added = 0
        engaged = bool(self._recent_user_clicks) and now - self._recent_user_clicks[-1][0] < 3.0
        for tr in self.last_tracks:
            if added >= 2 or tr.neg_logged >= 2 or tr.pos_logged:
                continue
            age = now - tr.t_first
            cx, cy = tr.center
            drift = float(np.hypot(cx - tr.origin[0], cy - tr.origin[1]))
            static = age >= 5.0 and drift < 0.02 * H and tr.speed < 0.01 * H
            lingering = engaged and age >= 2.5 and not static
            if not (static or lingering):
                continue
            if self.is_boss(tr.box) and self.model.trained and tr.p_n and tr.p >= 0.8:
                continue                      # probably a boss waiting for more clicks, not scenery
            if self._recently_clicked_near(cx, cy, now, 0.08 * H, window=30.0 if static else 4.0):
                continue
            if lingering and self.model.trained and tr.p_n and tr.p >= 0.4:
                continue          # we believe this is a ghost the player just did not get to
            crop = self._crop(frame, tr.box, 0.10)
            if crop is None:
                continue
            # static scenery is a firm negative; a lingering mover that an engaged player
            # ignored is a softer one (the player may simply have missed a ghost)
            self.store.add(crop, False, 1.0 if static else 0.4, "static" if static else "ignored")
            tr.neg_logged += 1
            tr.t_first = now                     # re-arm: next sample only after another stretch
            self.stats["neg_added"] += 1
            self._since_train_neg += 1
            added += 1

    # ---------------- inference ----------------
    def ready(self) -> bool:
        """Whether it is safe to use a model for autonomous inference.

        A validated, pre-trained model is usable even when its original training
        corpus is intentionally not shipped (e.g. a customer install). For models
        without meaningful holdout metrics, require enough local positive AND
        negative samples; a positive-only model is never considered ready.
        """
        if not self.model.trained:
            return False
        metrics = self.model.metrics if isinstance(self.model.metrics, dict) else {}
        n_train = int(metrics.get("n_train", 0) or 0)
        n_val = int(metrics.get("n_val", 0) or 0)
        precision = metrics.get("val_precision")
        recall = metrics.get("val_recall")
        try:
            precision, recall = float(precision), float(recall)
        except (TypeError, ValueError):
            precision = recall = float("nan")
        min_rows = int(getattr(self.cfg, "smart_min_validated_train_rows", 100))
        min_precision = float(getattr(self.cfg, "smart_min_validated_precision", 0.85))
        min_recall = float(getattr(self.cfg, "smart_min_validated_recall", 0.85))
        # Saved metrics may originate from a previous run, so also check their range.
        if (n_train >= min_rows and n_val >= 20 and np.isfinite(precision) and np.isfinite(recall)
                and min_precision <= precision <= 1.0 and min_recall <= recall <= 1.0):
            return True
        need_pos = int(getattr(self.cfg, "smart_min_positives", 12))
        need_neg = int(getattr(self.cfg, "smart_min_negative_samples", 8))
        return len(self.store.pos) >= need_pos and len(self.store.neg) >= need_neg

    def _score_tracks(self, frame: np.ndarray, now: float) -> None:
        H = frame.shape[0]
        crops, idx = [], []
        for tr in self.last_tracks:
            if now - tr.last_scored < 0.12 and tr.p_n > 0:
                continue
            crop = self._crop(frame, tr.box, 0.10)
            if crop is None:
                continue
            crops.append(features(crop, self.model.ref_h or H))
            idx.append(tr)
        if not crops:
            return
        P = self.model.predict(np.stack(crops))
        for tr, p in zip(idx, P):
            tr.p = float(p) if tr.p_n == 0 else 0.5 * tr.p + 0.5 * float(p)
            tr.p_n += 1
            tr.last_scored = now

    def pick_target(self, frame: np.ndarray, rect: Dict[str, int], now: float) -> Optional[Pick]:
        if not self.ready():
            return None
        self._score_tracks(frame, now)
        thr = self.threshold()
        confirm = int(getattr(self.cfg, "smart_confirm_frames", 2))
        cooldown = float(getattr(self.cfg, "smart_track_cooldown_s", 1.5))
        H, W = frame.shape[:2]
        # yield to the human: do not fight a live mouse
        if getattr(self.cfg, "smart_yield_to_user", True) and self._recent_user_clicks:
            if now - self._recent_user_clicks[-1][0] < float(getattr(self.cfg, "smart_yield_s", 0.8)):
                return None
        best: Optional[Tuple[float, Track]] = None
        for tr in self.last_tracks:
            boss = self.is_boss(tr.box)
            cd = float(getattr(self.cfg, "smart_boss_cooldown_s", 0.4)) if boss else cooldown
            if tr.p_n < confirm or tr.p < thr or now - tr.clicked_at < cd:
                continue
            cx, cy = tr.center
            if self._excluded(int(cx), int(cy)):
                continue
            # a ghost that has sat dead still for seconds is far more likely scenery
            age = now - tr.t_first
            p_eff = tr.p
            if (age > 2.5 and tr.speed < 0.004 * H and not boss
                    and getattr(self.cfg, "smart_penalize_static", True)):
                p_eff *= 0.7
            if p_eff < thr:
                continue
            if best is None or p_eff > best[0]:
                best = (p_eff, tr)
        probe = False
        if best is None:
            best = self._probe_candidate(now, thr, confirm, cooldown, H)
            if best is None:
                return None
            probe = True
        p_eff, tr = best
        cx, cy = tr.center
        lead = float(getattr(self.cfg, "smart_lead_ms", 0.0)) / 1000.0 or self._latency
        dx, dy = tr.vx * lead, tr.vy * lead
        cap = 0.6 * max(tr.box[2], tr.box[3])
        n = float(np.hypot(dx, dy))
        if n > cap:
            dx, dy = dx * cap / n, dy * cap / n
        fx = int(round(min(max(cx + dx, 0), W - 1)))
        fy = int(round(min(max(cy + dy, 0), H - 1)))
        return Pick(tr.tid, fx, fy, rect["left"] + fx, rect["top"] + fy, float(p_eff), tr.box, probe)

    def threshold(self) -> float:
        base = float(getattr(self.cfg, "smart_threshold", 0.80))
        if not bool(getattr(self.cfg, "smart_auto_threshold", True)):
            return base
        floor = float(getattr(self.cfg, "smart_threshold_floor", 0.88))
        return float(min(0.99, max(min(floor, base), base + self._thr_adj)))

    def _probe_candidate(self, now: float, thr: float, confirm: int, cooldown: float, H: int):
        """Active learning: occasionally click a moving, near-threshold candidate and let the ecto
        toast say whether it was a ghost. Off by default (a wrong click can hit an avatar)."""
        if not bool(getattr(self.cfg, "smart_probe", False)) or not self.feed_alive():
            return None
        if now - self._last_probe < float(getattr(self.cfg, "smart_probe_interval_s", 30.0)):
            return None
        lo = thr - 0.15
        best = None
        for tr in self.last_tracks:
            if tr.p_n < confirm or not (lo <= tr.p < thr) or now - tr.clicked_at < cooldown:
                continue
            if tr.speed < 0.01 * H or self._excluded(int(tr.center[0]), int(tr.center[1])):
                continue
            if best is None or tr.p > best[0]:
                best = (tr.p, tr)
        if best is not None:
            self._last_probe = now
            self.stats["probes"] += 1
        return best

    def note_smart_click(self, pick: Pick, frame: np.ndarray, now: float) -> None:
        tr = self.tracker.tracks.get(pick.tid)
        if tr is not None:
            tr.clicked_at = now
        crop = self._crop(frame, pick.box, 0.10)
        if crop is None:
            return
        pend = _Pending(pick.tid, now + float(getattr(self.cfg, "smart_feedback_delay_s", 0.35)),
                        pick.box, crop, (pick.box[0] + pick.box[2] / 2.0, pick.box[1] + pick.box[3] / 2.0),
                        pick.p, t_click=now, probe=pick.probe)
        self._note_click_rate(now)
        self._await.append(pend)
        if len(self._await) > 40:
            self._await.pop(0)
        self._last_smart = pend
        self.stats["smart_clicks"] += 1

    # ---------------- bosses ----------------
    def is_boss(self, box: Box) -> bool:
        """Big targets (bosses) take many clicks and stay on screen until the last one."""
        frac = float(getattr(self.cfg, "smart_boss_min_frac", 0.14))
        return max(box[2], box[3]) >= frac * max(1, self.frame_h)

    # ---------------- wave / boss mode ----------------
    def in_wave(self, now: float) -> bool:
        return now < self._wave_until

    def _note_click_rate(self, now: float) -> None:
        """Many bot clicks with no per-click toast = a wave or boss: the reward only comes at the end."""
        self._click_times.append(now)
        recent = [t for t in self._click_times if now - t <= 8.0]
        if self.in_wave(now):
            self._wave_clicks += 1
            self._wave_until = now + 20.0
        elif len(recent) >= 5 and self._last_confirm_t < recent[0]:
            self._wave_clicks = len(recent)
            self._wave_until = now + 20.0
            log.info("SMART: wave/boss mode ON (%d clicks, no per-click toasts): per-click ecto labelling paused "
                     "until the end-of-wave reward", len(recent))

    # ---------------- ecto confirmation ----------------
    def ecto_window(self) -> float:
        """How long after a click a gain may still be credited to it (learned from real latencies)."""
        base = float(getattr(self.cfg, "smart_ecto_window_s", 3.0))
        if len(self._lat) >= 8:
            return float(min(8.0, max(1.5, 1.6 * float(np.percentile(self._lat, 90)) + 0.5)))
        return base

    def on_ecto_gain(self, amount: int, t_seen: float) -> None:
        """Webhook thread -> queue; credited to a click on the next frame (keeps all state single-threaded)."""
        if not bool(getattr(self.cfg, "smart_ecto_confirm", True)):
            return
        with self._lock:
            self._gains.append((float(t_seen), int(amount)))

    def _process_ecto(self, now: float) -> None:
        win = self.ecto_window()
        lat_med = float(np.median(self._lat)) if len(self._lat) >= 5 else None
        cap = int(getattr(self.cfg, "smart_ecto_max_gain", 500))
        while True:
            with self._lock:
                if not self._gains:
                    break
                t_seen, amount = self._gains.popleft()
            self.stats["ecto_gains"] += 1
            self.stats["ecto_amount"] += amount
            if self.in_wave(t_seen) or (self._wave_clicks and t_seen - (self._click_times[-1] if self._click_times else 0) < 20.0
                                         and self._wave_until > 0):
                log.info("SMART: WAVE REWARD +%d after %d bot clicks (%d vanished) = %.1f per click",
                         amount, self._wave_clicks, self._wave_gone, amount / max(1, self._wave_clicks))
                self._log_gain(t_seen, amount, "wave_reward", 0.0, None)
                self.stats["wave_rewards"] = self.stats.get("wave_rewards", 0) + 1
                self._wave_until, self._wave_clicks, self._wave_gone = 0.0, 0, 0
                continue
            if amount > cap:                                  # bonus / daily reward, not a catch
                self._log_gain(t_seen, amount, "ignored_big", 0.0, None)
                continue
            cands = []                                        # (latency, kind, obj)
            for pd in self._await:
                lat = t_seen - pd.t_click
                if not pd.confirmed and not pd.vetoed and -0.05 <= lat <= win:
                    cands.append((max(0.0, lat), "bot", pd))
            for (tu, fx, fy) in self._recent_user_clicks:
                lat = t_seen - tu
                if tu not in self._used_user and -0.05 <= lat <= win:
                    cands.append((max(0.0, lat), "user", tu))
            if not cands:
                self.stats["ecto_unattributed"] += 1
                self._log_gain(t_seen, amount, "unattributed", 0.0, None)
                continue
            if lat_med is not None:
                cands.sort(key=lambda c: abs(c[0] - lat_med))
            else:
                cands.sort(key=lambda c: c[0], reverse=True)  # earliest click first until latency is known
            lat, kind, obj = cands[0]
            if kind == "bot":
                obj.confirmed, obj.amount, obj.latency = True, amount, lat
                obj.ambiguous = len(cands) > 1
                self._lat.append(lat)
                self._last_confirm_t = obj.t_click
                self.stats["ecto_bot"] += 1
                self._log_gain(t_seen, amount, "bot" + ("?" if obj.ambiguous else ""), lat, obj)
            else:
                self._used_user.add(obj)
                if len(self._used_user) > 200:
                    self._used_user = set(sorted(self._used_user)[-100:])
                self._lat.append(lat)
                self.stats["ecto_user"] += 1
                self._log_gain(t_seen, amount, "user", lat, None)

    def _log_gain(self, t: float, amount: int, kind: str, lat: float, pd: Optional[_Pending]) -> None:
        try:
            rec = {"t": round(t, 3), "amount": amount, "kind": kind, "lat": round(lat, 3)}
            if pd is not None:
                rec.update(p=round(pd.p, 3), w=pd.box[2], h=pd.box[3], probe=pd.probe)
            with open(self.ecto_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError:
            pass

    def hit_rate(self) -> Optional[float]:
        return (sum(self._hits) / len(self._hits)) if len(self._hits) >= 8 else None

    def _adapt_threshold(self) -> None:
        if not bool(getattr(self.cfg, "smart_auto_threshold", True)) or len(self._hits) < 20:
            return
        r = sum(self._hits) / len(self._hits)
        if r < 0.35:
            self._thr_adj = min(0.04, self._thr_adj + 0.004)
        elif r > 0.75:
            self._thr_adj = max(-0.07, self._thr_adj - 0.004)

    def stats_line(self) -> str:
        """One line for the Discord post."""
        r = self.hit_rate()
        if r is None:
            return ""
        return (f"Bot accuracy: **{r * 100:.0f}%** of the last {len(self._hits)} judged clicks "
                f"(threshold {self.threshold():.3f})\n")

    # ---------------- per-click verdict ----------------
    def _visual_verdict(self, pend: _Pending, frame: np.ndarray, now: float) -> str:
        H, W = frame.shape[:2]
        tr = self.tracker.tracks.get(pend.tid)
        if tr is not None and now - tr.t_last < 0.25:
            moved = float(np.hypot(tr.center[0] - pend.center0[0], tr.center[1] - pend.center0[1]))
            return "static" if (tr.speed < 0.01 * H and moved < 0.015 * H) else "moving"
        x, y, w, h = pend.box
        x0, y0 = max(0, x - w // 2), max(0, y - h // 2)
        x1, y1 = min(W, x + w + w // 2), min(H, y + h + h // 2)
        if x1 - x0 > 8 and y1 - y0 > 8:
            region, tpl = frame[y0:y1, x0:x1], pend.crop
            if region.shape[0] > tpl.shape[0] and region.shape[1] > tpl.shape[1]:
                res = cv2.matchTemplate(region, tpl, cv2.TM_CCOEFF_NORMED)
                return "gone" if float(res.max()) < 0.6 else "unknown"
            return "gone"
        return "unknown"

    def _process_pending(self, frame: np.ndarray, now: float) -> None:
        """Visual verdict at `due`; final label once the ecto window has closed (or a gain confirmed it)."""
        if not self._await:
            return
        win = self.ecto_window()
        feed_ok = bool(self.feed_alive())
        use_ecto = feed_ok and bool(getattr(self.cfg, "smart_ecto_confirm", True)) and not self.in_wave(now)
        keep: List[_Pending] = []
        for pd in self._await:
            if pd.verdict is None and now >= pd.due:
                pd.verdict = self._visual_verdict(pd, frame, now)
                if pd.verdict == "moving" and not pd.confirmed:
                    if use_ecto:
                        pd.retry_pending = True          # wait out the toast latency before calling it a miss
                    else:
                        self._maybe_retry(pd)
            if pd.retry_pending and now >= pd.t_click + self._retry_after():
                pd.retry_pending = False
                if not pd.confirmed and not pd.vetoed:
                    self._maybe_retry(pd)
            if pd.verdict is None:
                keep.append(pd)
                continue
            # With a live ecto feed wait for the window to close; without it fall back to visual-only now.
            if use_ecto and not pd.confirmed and now < pd.t_click + win:
                keep.append(pd)
                continue
            self._finalize(pd, use_ecto)
        self._await = keep

    def _retry_after(self) -> float:
        """Seconds after a click before 'still alive, no gain' counts as an aim miss (toast latency + margin)."""
        med = float(np.median(self._lat)) if len(self._lat) >= 5 else 0.6
        return max(0.5, 1.5 * med + 0.15)

    def _maybe_retry(self, pd: _Pending) -> None:
        """Ghost still alive and moving after our click = aim miss: free the track for a quick re-click."""
        if not bool(getattr(self.cfg, "smart_retry_misses", True)):
            return
        tr = self.tracker.tracks.get(pd.tid)
        if tr is None:
            return
        if tr.retries >= int(getattr(self.cfg, "smart_retry_max", 2)) and not self.is_boss(pd.box):
            return
        tr.retries += 1
        tr.clicked_at = 0.0
        self.stats["retries"] += 1

    def _finalize(self, pd: _Pending, use_ecto: bool) -> None:
        if self.autoplay or pd.vetoed:
            return                                        # auto play never writes samples or adapts the threshold
        if pd.confirmed:
            # Ground truth: a real catch. Ambiguous attribution (several clicks in the window) counts less.
            w = 1.5 if pd.probe else (0.8 if pd.ambiguous else 1.2)
            self.store.add(pd.crop, True, w, "ecto")
            self.stats["pos_added"] += 1
            self.stats["ecto_positives"] += 1
            self._since_train_pos += 1
            self._hits.append(1)
            self._adapt_threshold()
            log.info("SMART: ECTO CONFIRMED +%d (%.2fs after click, p=%.2f%s%s): saved as strong positive",
                     pd.amount, pd.latency, pd.p, " PROBE" if pd.probe else "", " ambiguous" if pd.ambiguous else "")
            return
        v = pd.verdict
        if v == "static" and self.is_boss(pd.box):
            return                                        # a boss that survives a click is normal: no label
        if v == "static":
            self.store.add(pd.crop, False, 1.0 if pd.probe else 0.8, "noreact")
            self.stats["neg_added"] += 1
            self._since_train_neg += 1
            if use_ecto:
                self._hits.append(0)
                self._adapt_threshold()
            log.info("SMART: click on a static object, no ecto: learned as NOT a ghost%s", " (probe)" if pd.probe else "")
        elif v == "gone" and pd.p >= 0.85 and not pd.probe:
            self._wave_gone += 1
            # vanished but no gain seen: weak positive (could be OCR miss or someone else's catch)
            self.store.add(pd.crop, True, 0.3 if use_ecto else 0.5, "react")
            self.stats["pos_added"] += 1
            self._since_train_pos += 1
            if use_ecto:
                self._hits.append(0)
                self._adapt_threshold()
        elif v == "moving":
            self.stats["aim_misses"] += 1                 # survived and still moves: aim problem, no label

    # ---------------- training ----------------
    def seed_from_images(self, images: List[Tuple[np.ndarray, Optional[np.ndarray]]], weight: float = 0.6) -> int:
        """Optional bootstrap from existing seed crops so the first session is not empty."""
        if self.autoplay or self.store.pos:
            return 0
        n = 0
        for img, mask in images:
            if img is None or min(img.shape[:2]) < 10:
                continue
            self.store.add(img, True, weight, "seed")
            n += 1
        if n:
            self._since_train_pos += n
        return n

    def _maybe_train(self, now: float) -> None:
        if self._training:
            return
        enough_pos = len(self.store.pos) >= max(5, int(getattr(self.cfg, "smart_min_positives", 12)) // 2)
        enough_neg = len(self.store.neg) >= 8
        if not (enough_pos and enough_neg):
            return
        due = (self._since_train_pos >= 3 or self._since_train_neg >= 20
               or (not self.model.trained)) and now - self._last_train >= 6.0
        if not due:
            return
        self._training = True
        self._last_train = now
        self._since_train_pos = 0
        self._since_train_neg = 0
        threading.Thread(target=self._train_worker, daemon=True, name="smart-train").start()

    def train_now(self, aug_pos: int = 8, aug_neg: int = 2) -> Dict[str, float]:
        """Synchronous training (also used by the test-suite)."""
        return self._train(aug_pos, aug_neg)

    def _train_worker(self) -> None:
        lock = _acquire_maintenance_lock(self.dir.parent, "auto-train")
        if lock is None:
            log.info("SMART: skipped automatic training because another maintenance job is already running")
            self._training = False
            return
        try:
            ap = int(getattr(self.cfg, "smart_aug_pos", 8))
            an = int(getattr(self.cfg, "smart_aug_neg", 2))
            m = self._train(ap, an)
            log.info("SMART: model retrained %s", {k: round(v, 3) if isinstance(v, float) else v for k, v in m.items()})
            if bool(getattr(self.cfg, "smart_auto_clean", True)):
                total = len(self.store.pos) + len(self.store.neg)
                if total - self._last_clean_total >= 40:
                    c = self.auto_clean(ap, an)
                    if c.get("removed", 0) > 0:
                        m = self._train(ap, an)
                        log.info("SMART: retrained after cleaning %s",
                                 {k: round(v, 3) if isinstance(v, float) else v for k, v in m.items()})
        except Exception as exc:
            log.exception("SMART: training failed: %s", exc)
        finally:
            _release_maintenance_lock(lock)
            self._training = False

    def _sample_feats(self, path: Path, wt: float, n_aug: int, ref_h: int) -> List[Optional[np.ndarray]]:
        """Features of a source sample and deterministic augmentations, cached by file identity."""
        path = Path(path)
        try:
            st = path.stat()
            key = (str(path.resolve()), int(st.st_mtime_ns), int(st.st_size), float(wt), int(ref_h), int(n_aug))
        except OSError:
            key = (str(path.absolute()), -1, -1, float(wt), int(ref_h), int(n_aug))
        hit = self._fcache.get(key)
        if hit is not None:
            self._fcache.move_to_end(key)
            return hit
        img = _read_bgr(path)
        out: List[Optional[np.ndarray]] = []
        if img is not None and min(img.shape[:2]) >= 8:
            # Stable across machines and independent of Python's randomized hash seed.
            rng = random.Random(zlib.crc32((key[0] + str(key[1])).encode("utf-8")))
            for k in range(max(0, int(n_aug)) + 1):
                v_img = img if k == 0 else augment(img, rng)
                try:
                    feat = np.asarray(features(v_img, ref_h), dtype=np.float32)
                    out.append(feat if np.isfinite(feat).all() else None)
                except Exception:
                    out.append(None)       # keeps index k aligned with its sample weight
        self._fcache[key] = out
        size = sum(int(x.nbytes) for x in out if isinstance(x, np.ndarray))
        self._fcache_bytes += size
        while self._fcache and (self._fcache_bytes > self._fcache_limit_bytes or len(self._fcache) > 20000):
            _old_key, old = self._fcache.popitem(last=False)
            self._fcache_bytes -= sum(int(x.nbytes) for x in old if isinstance(x, np.ndarray))
        return out

    def _train_h(self) -> int:
        return int(max(480, self.frame_h))

    def _build_dataset(self, pos, neg, aug_pos: int, aug_neg: int, ref_h: Optional[int] = None):
        ref_h = int(ref_h or self._train_h())
        X, y, w, g, src = [], [], [], [], []
        gid = 0
        for label, items, n_aug in ((1.0, pos, aug_pos), (0.0, neg, aug_neg)):
            for path, wt in items:
                feats = self._sample_feats(path, wt, n_aug, ref_h)
                if not feats or feats[0] is None:
                    continue
                for k, f in enumerate(feats):
                    if f is None:
                        continue
                    X.append(f)
                    y.append(label)
                    w.append(wt * (1.0 if k == 0 else 0.7))
                    g.append(gid)
                    src.append((path, k))
                gid += 1
        return X, y, w, g, src

    def _train(self, aug_pos: int, aug_neg: int) -> Dict[str, float]:
        pos, neg = self.store.snapshot()
        ref_h = self._train_h()
        X, y, w, g, _src = self._build_dataset(pos, neg, aug_pos, aug_neg, ref_h)
        if not X or sum(1 for v in y if v > 0.5) < 3 or sum(1 for v in y if v <= 0.5) < 3:
            return {"skipped": 1}
        Xa = np.stack(X).astype(np.float32)
        ya = np.array(y, np.float32)
        wa = np.array(w, np.float32)
        ga = np.array(g)
        new = MLP()
        m = new.fit(Xa, ya, wa, ga)
        new.ref_h = ref_h
        # Keep the newly trained model active, but report persistence failures. Silent
        # failure made users believe learning would survive restart when it would not.
        self.model = new
        try:
            new.save(self.model_path)
        except Exception as exc:
            log.exception("SMART: model trained in memory but could not be saved to %s: %s", self.model_path, exc)
        self.stats["trained"] += 1
        self._write_status()
        return m

    # ---------------- automatic curation ----------------
    # A positive the cross-validated model is sure is NOT a ghost (or a negative it is sure IS
    # one) is probably a mislabel: a stray click, a ghost mined as scenery, ... Such samples are
    # moved to smart/quarantine/ (reversible), never deleted. Explicit F8 negatives are protected.
    _POS_THR = {"user": 0.03, "react": 0.15, "seed": 0.10, "ecto": 0.0,
                "ovconf": 0.03,      # you confirmed it on the overlay: trusted like a click
                "ovauto": 0.30}      # the model's own overlay guess: first to go when cross-validation doubts it
    _NEG_THR = {"static": 0.97, "ignored": 0.90, "noreact": 0.92}
    _PROTECTED_NEG = {"bad", "ovrej"}      # explicit "not a ghost" verdicts are never auto-removed

    def _clean_pass(self, aug_pos: int = 8, aug_neg: int = 2, folds: int = 5,
                    max_frac: float = 0.08, force: bool = False, repeats: int = 2) -> Dict[str, float]:
        pos, neg = self.store.snapshot()
        if len(pos) < 30 or len(neg) < 40:
            return {"skipped": 1, "reason": "not enough samples", "removed": 0}

        # Cross-validation is only used to rank questionable labels, not to build the final
        # production model. Running five folds twice over 200k+ augmented rows made offline
        # cleaning take longer than the GUI's 900-second process timeout. Use a bounded,
        # conservative triage pass for large libraries; _train() below still uses full configured
        # augmentation for the saved model.
        total_samples = len(pos) + len(neg)
        cv_aug_pos, cv_aug_neg = max(0, int(aug_pos)), max(0, int(aug_neg))
        # Include augmentation in the work estimate: a few thousand originals can expand to
        # 25k-35k feature rows (matching the n_train/n_val sizes printed by MLP.fit).
        expanded_rows = len(pos) * (cv_aug_pos + 1) + len(neg) * (cv_aug_neg + 1)
        cv_epochs = 50
        if total_samples >= 25000 or expanded_rows >= 25000:
            folds, repeats, cv_aug_pos, cv_aug_neg, cv_epochs = min(folds, 3), 1, 0, 0, 18
            log.info("SMART: large clean workload (%d originals, about %d augmented rows): bounded pass (3-fold, 1 repeat, no CV augmentation, 18 epochs); full augmentation remains enabled for final retrain", total_samples, expanded_rows)
        elif total_samples >= 7000 or expanded_rows >= 12000:
            folds, repeats, cv_aug_pos, cv_aug_neg, cv_epochs = min(folds, 3), 1, min(cv_aug_pos, 1), min(cv_aug_neg, 1), 25
            log.info("SMART: medium/large clean workload (%d originals, about %d augmented rows): faster pass (3-fold, 1 repeat, capped augmentation, 25 epochs)", total_samples, expanded_rows)

        X, y, w, g, src = self._build_dataset(pos, neg, cv_aug_pos, cv_aug_neg)
        if not X:
            return {"skipped": 1, "reason": "no usable sample features", "removed": 0}
        Xa = np.stack(X).astype(np.float32)
        ya = np.array(y, np.float32)
        wa = np.array(w, np.float32)
        ga = np.array(g)
        is_orig = np.array([k == 0 for _, k in src])
        uniq = np.unique(ga)
        oofs = []
        for rep_i in range(max(1, repeats)):
            rng = np.random.default_rng(99 + rep_i)
            fold_of: Dict[int, int] = {}
            for lab in (1.0, 0.0):          # stratified fold assignment per source sample
                ids = [u for u in uniq if ya[np.nonzero(ga == u)[0][0]] == lab]
                rng.shuffle(ids)
                for i, u in enumerate(ids):
                    fold_of[int(u)] = i % folds
            folds_arr = np.array([fold_of[int(v)] for v in ga])
            o = np.full(len(Xa), np.nan, np.float32)
            for f in range(folds):
                te = folds_arr == f
                tr = ~te
                if (ya[tr] > 0.5).sum() < 3 or (ya[tr] <= 0.5).sum() < 3:
                    continue
                m = MLP()
                m.fit(Xa[tr], ya[tr], wa[tr], ga[tr], epochs=cv_epochs, seed=f + 10 * rep_i)
                sel = te & is_orig
                o[sel] = m.predict(Xa[sel])
            oofs.append(o)
        stack = np.stack(oofs)
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            oof = np.nanmean(stack, axis=0)         # for reporting / accuracy
            oof_hi = np.nanmax(stack, axis=0)       # a positive is suspicious only if EVERY pass says no
            oof_lo = np.nanmin(stack, axis=0)       # a negative is suspicious only if EVERY pass says yes
        ok = is_orig & ~np.isnan(oof)
        if ok.sum() < 20:
            return {"skipped": 1, "reason": "no usable folds", "removed": 0}
        acc = float((((oof[ok] >= 0.5) == (ya[ok] > 0.5))).mean())
        scores: Dict[str, Dict[str, float]] = {"pos": {}, "neg": {}}
        cand_pos, cand_neg = [], []
        for i in np.nonzero(ok)[0]:
            path = src[i][0]
            p = float(oof[i])
            if ya[i] > 0.5:
                scores["pos"][path.name] = round(p, 4)
                if float(oof_hi[i]) < self._POS_THR.get(SampleStore.tag_of(path), 0.10):
                    cand_pos.append((p, path))
            else:
                scores["neg"][path.name] = round(p, 4)
                tag = SampleStore.tag_of(path)
                if tag in self._PROTECTED_NEG:
                    continue
                if float(oof_lo[i]) > self._NEG_THR.get(tag, 0.92):
                    cand_neg.append((-p, path))
        try:
            tmp = self.review_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"time": time.time(), "oof_accuracy": acc, **scores}), encoding="utf-8")
            os.replace(tmp, self.review_path)
        except OSError:
            pass
        self._last_clean_total = len(pos) + len(neg)
        if acc < 0.75 and not force:
            log.info("SMART: auto-clean skipped, cross-validated accuracy only %.2f (labels too inconsistent to judge)", acc)
            return {"skipped": 1, "reason": "low accuracy", "oof_accuracy": acc, "removed": 0}
        cand_pos.sort(key=lambda t: t[0])
        cand_neg.sort(key=lambda t: t[0])
        cand_pos = cand_pos[:max(1, int(max_frac * len(pos)))]
        cand_neg = cand_neg[:max(1, int(max_frac * len(neg)))]
        rp = sum(1 for _, pth in cand_pos if self.store.quarantine(pth))
        rn = sum(1 for _, pth in cand_neg if self.store.quarantine(pth))
        self.stats["auto_removed"] += rp + rn
        if rp + rn:
            log.info("SMART: auto-clean quarantined %d suspicious positives and %d suspicious negatives "
                     "(cv accuracy %.2f). Restore them from the Sample manager if any was right.", rp, rn, acc)
        self._write_status()
        return {"removed": rp + rn, "removed_pos": rp, "removed_neg": rn, "oof_accuracy": acc}

    def auto_clean(self, aug_pos: int = 8, aug_neg: int = 2, force: bool = False,
                   rounds: int = 3) -> Dict[str, float]:
        """Iterative cleaning, automatically bounded for large sample libraries."""
        pos, neg = self.store.snapshot()
        total_samples = len(pos) + len(neg)
        expanded_rows = len(pos) * (max(0, int(aug_pos)) + 1) + len(neg) * (max(0, int(aug_neg)) + 1)
        effective_rounds = max(1, int(rounds))
        if total_samples >= 10000 or expanded_rows >= 20000:
            # A single conservative pass is safer and much faster on large corpora. The user
            # can inspect/restore quarantined images and retrain again after reviewing them.
            effective_rounds = 1
        total = {"removed": 0, "removed_pos": 0, "removed_neg": 0}
        last: Dict[str, float] = {}
        for _ in range(effective_rounds):
            last = self._clean_pass(aug_pos, aug_neg, force=force)
            if last.get("skipped"):
                break
            for k in ("removed", "removed_pos", "removed_neg"):
                total[k] += int(last.get(k, 0))
            if not last.get("removed"):
                break
        out = dict(last)
        out.update(total)
        return out

    # ---------------- GUI <-> bot commands & status ----------------
    def _write_status(self) -> None:
        try:
            tmp = self.status_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"time": time.time(), "positives": len(self.store.pos),
                                       "negatives": len(self.store.neg), "metrics": self.model.metrics,
                                       "auto_removed": self.stats.get("auto_removed", 0),
                                       "frame_h": int(self.frame_h)}), encoding="utf-8")
            os.replace(tmp, self.status_path)
        except OSError:
            pass

    def _poll_commands(self, now: float) -> None:
        """The GUI drops smart/command.json ({"action": "retrain" | "clean"}); run it in the background."""
        if now - self._last_cmd_poll < 2.0 or self._training:
            return
        self._last_cmd_poll = now
        if not self.cmd_path.exists():
            return
        try:
            cmd = json.loads(self.cmd_path.read_text(encoding="utf-8"))
            self.cmd_path.unlink()
        except Exception:
            try:
                self.cmd_path.unlink()
            except OSError:
                pass
            return
        self._training = True
        threading.Thread(target=self._command_worker, args=(str(cmd.get("action", "retrain")),),
                         daemon=True, name="smart-cmd").start()

    def _command_worker(self, action: str) -> None:
        lock = _acquire_maintenance_lock(self.dir.parent, action)
        if lock is None:
            log.warning("SMART: ignored requested %s because another maintenance/training job is already running", action)
            self._training = False
            return
        started_at = float(lock["started_at"])
        try:
            _write_maintenance(self.dir.parent, action, "running", started_at, stage="initializing")
            self.store.rescan()
            ap = int(getattr(self.cfg, "smart_aug_pos", 8))
            an = int(getattr(self.cfg, "smart_aug_neg", 2))
            if action == "clean":
                _write_maintenance(self.dir.parent, action, "running", started_at, stage="cleaning")
                c = self.auto_clean(ap, an, force=False)
                log.info("SMART: manual auto-clean %s", c)
            _write_maintenance(self.dir.parent, action, "running", started_at, stage="retraining")
            m = self._train(ap, an)
            if m.get("skipped"):
                raise RuntimeError("Retrain skipped: not enough usable positive/negative training features.")
            self._last_train = time.time()
            self._since_train_pos = self._since_train_neg = 0
            log.info("SMART: model retrained on request %s",
                     {k: round(v, 3) if isinstance(v, float) else v for k, v in m.items()})
            _write_maintenance(self.dir.parent, action, "done", started_at,
                               stage="complete", finished_at=time.time())
        except Exception as exc:
            _write_maintenance(self.dir.parent, action, "error", started_at, stage="failed",
                               finished_at=time.time(), error=f"{type(exc).__name__}: {exc}")
            log.exception("SMART: command failed: %s", exc)
        finally:
            _release_maintenance_lock(lock)
            self._training = False

    # ---------------- reporting ----------------
    def status(self) -> Dict[str, object]:
        return {
            "positives": len(self.store.pos), "negatives": len(self.store.neg),
            "model": self.model.trained, "ready": self.ready(),
            "metrics": self.model.metrics, **self.stats,
            "hit_rate": self.hit_rate(), "threshold": self.threshold(),
        }

    def debug_boxes(self) -> List[Tuple[int, int, int, int, str]]:
        out = []
        for tr in self.last_tracks:
            if tr.p_n:
                x, y, w, h = tr.box
                out.append((x, y, w, h, f"smart#{tr.tid} p={tr.p:.2f} v={tr.speed:.0f}"))
        return out


def _write_maintenance(root: Path, action: str, state: str, started_at: float,
                       **extra) -> None:
    """Atomically publish offline maintenance state for the GUI to poll."""
    path = Path(root) / "smart" / "maintenance.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"action": str(action), "state": str(state), "started_at": float(started_at),
               "updated_at": time.time(), "pid": os.getpid()}
    payload.update(extra)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("SMART: could not write maintenance status to %s: %s", path, exc)


def _pid_is_running(pid: int) -> bool:
    """Best-effort cross-platform check used only to recover stale maintenance locks."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
    except OSError as exc:
        if exc.errno == errno.ESRCH or getattr(exc, "winerror", None) in (87, 1168):
            return False
        # Access-denied/unknown OS errors should fail closed: do not start a second trainer.
        return True


def _acquire_maintenance_lock(root: Path, action: str):
    """Acquire one project-wide lock so two offline/live maintenance jobs cannot overlap."""
    lock_path = Path(root) / "smart" / "maintenance.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = time.time()
    payload = {"pid": os.getpid(), "action": str(action), "started_at": started_at}
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for _attempt in range(2):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            existing = _read_json(lock_path)
            if isinstance(existing, dict):
                try:
                    owner_pid = int(existing.get("pid", 0) or 0)
                except (TypeError, ValueError):
                    owner_pid = 0
                if _pid_is_running(owner_pid):
                    return None
            else:
                # Another process may have just created the lock but not written its payload yet.
                try:
                    if time.time() - lock_path.stat().st_mtime < 5.0:
                        return None
                except OSError:
                    continue
            try:
                lock_path.unlink()
            except OSError:
                return None
            continue
        except OSError as exc:
            log.warning("SMART: cannot acquire maintenance lock %s: %s", lock_path, exc)
            return None
        else:
            try:
                os.write(fd, encoded)
                os.fsync(fd)
            finally:
                os.close(fd)
            return {"path": lock_path, "pid": payload["pid"], "started_at": started_at,
                    "action": str(action)}
    return None


def _release_maintenance_lock(lock) -> None:
    if not lock:
        return
    path = Path(lock["path"])
    try:
        existing = _read_json(path)
        if isinstance(existing, dict) and int(existing.get("pid", 0) or 0) == int(lock["pid"]):
            if abs(float(existing.get("started_at", 0) or 0) - float(lock["started_at"])) < 0.01:
                path.unlink(missing_ok=True)
    except (OSError, TypeError, ValueError):
        pass


# ============================================================
# Offline CLI (used by the GUI when the bot is not running)
#   python smart_ghost.py clean-retrain|retrain|clean [--root <project folder>]
# ============================================================
if __name__ == "__main__":
    import argparse
    import sys
    from types import SimpleNamespace

    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["clean-retrain", "retrain", "clean", "stats"])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent))
    ap.add_argument("--aug-pos", type=int, default=8)
    ap.add_argument("--aug-neg", type=int, default=2)
    a = ap.parse_args()
    root = Path(a.root).resolve()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    if a.action == "stats":
        _h = 720
        try:
            _h = int(json.loads((root / "smart" / "status.json").read_text(encoding="utf-8")).get("frame_h", 0)) or 720
        except Exception:
            pass
        sgh = SmartGhost(root, SimpleNamespace(), ref_frame_h=_h)
        print(json.dumps(sgh.status(), default=str))
        sys.exit(0)

    lock = _acquire_maintenance_lock(root, a.action)
    if lock is None:
        print("SMART maintenance is already running for this project; refusing to start a duplicate clean/retrain.",
              file=sys.stderr, flush=True)
        sys.exit(2)
    started_at = float(lock["started_at"])
    _write_maintenance(root, a.action, "running", started_at, stage="initializing")
    try:
        _h = 720
        try:
            _h = int(json.loads((root / "smart" / "status.json").read_text(encoding="utf-8")).get("frame_h", 0)) or 720
        except Exception:
            pass
        sgh = SmartGhost(root, SimpleNamespace(), ref_frame_h=_h)
        if sgh.model.ref_h:
            sgh.frame_h = sgh.model.ref_h        # keep size features identical to the live model
        if a.action in ("clean", "clean-retrain"):
            _write_maintenance(root, a.action, "running", started_at, stage="cleaning")
            print("clean:", sgh.auto_clean(a.aug_pos, a.aug_neg), flush=True)
        if a.action in ("retrain", "clean-retrain"):
            _write_maintenance(root, a.action, "running", started_at, stage="retraining")
            m = sgh._train(a.aug_pos, a.aug_neg)
            print("retrained:", {k: round(v, 3) if isinstance(v, float) else v for k, v in m.items()}, flush=True)
            if m.get("skipped"):
                raise RuntimeError("Retrain skipped: not enough usable positive/negative training features.")
        _write_maintenance(root, a.action, "done", started_at, stage="complete", finished_at=time.time())
    except Exception as exc:
        _write_maintenance(root, a.action, "error", started_at, stage="failed",
                            finished_at=time.time(), error=f"{type(exc).__name__}: {exc}")
        log.exception("SMART: offline %s failed", a.action)
        sys.exit(1)
    finally:
        _release_maintenance_lock(lock)
