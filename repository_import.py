"""Import the user's public Highrise ghost-image repository into the bot's library.

The import is deliberately an explicit, one-shot command; the live frame loop never
performs network I/O.  Every repository image is cached under corpus/repository/.
Files named ok.* or okay.* are routed to ok/ as popup watchers. Other images are
segmented into tight, alpha-masked targets where confidence is sufficient; ambiguous
screenshots stay in corpus/pending/ and are never turned into live click targets.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional

import cv2
import numpy as np

log = logging.getLogger("bot")
DEFAULT_REPOSITORY = "Tenslaster/bloop"
DEFAULT_BRANCH = "main"
IMPORTER_VERSION = 3
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
MAX_REMOTE_IMAGE_BYTES = 24 * 1024 * 1024
USER_AGENT = "Highrise-Vision-Bot-Image-Importer/1.0"


@dataclass
class ImportSummary:
    repository: str
    branch: str
    remote_images: int = 0
    downloaded: int = 0
    up_to_date: int = 0
    watchers: int = 0
    target_crops_added: int = 0
    duplicate_crops: int = 0
    pending_review: int = 0
    unsupported_or_failed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_repo(value: str) -> tuple[str, str]:
    value = value.strip().rstrip("/")
    value = re.sub(r"^https?://github\.com/", "", value, flags=re.IGNORECASE)
    value = value.removesuffix(".git")
    parts = [p for p in value.split("/") if p]
    if len(parts) != 2 or any(p in (".", "..") for p in parts):
        raise ValueError("Repository must be OWNER/REPO or https://github.com/OWNER/REPO")
    return parts[0], parts[1]


def _request_bytes(url: str, timeout: float = 18.0, attempts: int = 3) -> bytes:
    last_error: Optional[BaseException] = None
    for attempt in range(max(1, attempts)):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = response.read(MAX_REMOTE_IMAGE_BYTES + 1)
                if len(data) > MAX_REMOTE_IMAGE_BYTES:
                    raise ValueError(f"Remote file exceeds {MAX_REMOTE_IMAGE_BYTES // (1024 * 1024)} MB limit")
                return data
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.35 * (2 ** attempt))
    if last_error:
        raise RuntimeError(f"Download failed for {url}: {last_error}") from last_error
    raise RuntimeError(f"Download failed for {url}")


def _request_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(req, timeout=18.0) as response:
            data = response.read(8 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", "replace")
        if exc.code == 403 and "rate limit" in detail.lower():
            raise RuntimeError("GitHub API rate limit reached. Wait a while and retry the one-time image sync.") from exc
        raise RuntimeError(f"GitHub API returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Could not reach GitHub API ({exc}). Check the internet connection and retry.") from exc
    if len(data) > 8 * 1024 * 1024:
        raise RuntimeError("GitHub image manifest was unexpectedly large; refusing to parse it.")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("GitHub returned an invalid JSON tree response.") from exc
    if not isinstance(value, dict):
        raise RuntimeError("GitHub returned an unexpected tree response.")
    return value


def _is_watcher(path: str | PurePosixPath) -> bool:
    p = PurePosixPath(str(path))
    return p.stem.casefold() in {"ok", "okay"}


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def _manifest_load(path: Path) -> dict[str, Any]:
    try:
        val = json.loads(path.read_text(encoding="utf-8"))
        return val if isinstance(val, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _image_paths_in_tree(tree: dict[str, Any]) -> list[dict[str, Any]]:
    rows = tree.get("tree")
    if not isinstance(rows, list):
        raise RuntimeError(f"GitHub tree response contained no file list: {tree.get('message', 'unknown response')}")
    if tree.get("truncated"):
        raise RuntimeError("GitHub tree was truncated; refusing to silently skip repository images.")
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("type") != "blob":
            continue
        raw_path = row.get("path")
        if not isinstance(raw_path, str):
            continue
        p = PurePosixPath(raw_path)
        if p.is_absolute() or ".." in p.parts or p.suffix.casefold() not in IMAGE_SUFFIXES:
            continue
        # These two are explicit confirmation watchers, not target images.
        # They may live at the repository root or within a folder.
        out.append({"path": p.as_posix(), "sha": str(row.get("sha", "")),
                    "size": int(row.get("size", 0) or 0)})
    out.sort(key=lambda r: r["path"].casefold())
    return out


def sync_repository_images(root: Path, repository: str = DEFAULT_REPOSITORY,
                           branch: str = DEFAULT_BRANCH, *, force: bool = False,
                           workers: int = 4) -> dict[str, Any]:
    """Download all image files from a public GitHub repository into the project.

    Network work is concurrent but bounded. Exact remote blob SHA values are cached
    so subsequent explicit syncs only download changed/new files. No network calls
    are made by the bot's live loop.
    """
    owner, repo = _safe_repo(repository)
    repo_id = f"{owner}/{repo}"
    root = Path(root).resolve()
    corpus = root / "corpus"
    raw_dir = corpus / "repository"
    ok_dir = root / "ok"
    raw_dir.mkdir(parents=True, exist_ok=True)
    ok_dir.mkdir(parents=True, exist_ok=True)
    state_path = corpus / "repository_sync.json"
    state = _manifest_load(state_path)
    previous = state.get("files", {}) if isinstance(state.get("files", {}), dict) else {}

    tree_url = "https://api.github.com/repos/{}/{}/git/trees/{}?recursive=1".format(
        urllib.parse.quote(owner, safe=""), urllib.parse.quote(repo, safe=""),
        urllib.parse.quote(branch, safe=""))
    tree = _request_json(tree_url)
    if tree.get("message") and "tree" not in tree:
        raise RuntimeError(f"GitHub tree lookup failed: {tree['message']}")
    images = _image_paths_in_tree(tree)
    if not images:
        raise RuntimeError("No supported image files were found in the selected repository tree.")

    summary = ImportSummary(repository=repo_id, branch=branch, remote_images=len(images))
    updates: dict[str, dict[str, Any]] = {}
    work: list[tuple[dict[str, Any], Path, str]] = []
    for item in images:
        source_path = PurePosixPath(item["path"])
        if _is_watcher(source_path):
            # Watchers live flat in ./ok; filenames like okay.jpg remain supported.
            dest = ok_dir / source_path.name
            kind = "watcher"
        else:
            dest = raw_dir.joinpath(*source_path.parts)
            kind = "target_source"
        record = previous.get(item["path"], {}) if isinstance(previous.get(item["path"], {}), dict) else {}
        if (not force and record.get("remote_sha") == item["sha"] and dest.is_file()
                and dest.stat().st_size == item["size"]):
            summary.up_to_date += 1
            if kind == "watcher":
                summary.watchers += 1
            updates[item["path"]] = {"remote_sha": item["sha"], "local_path": dest.relative_to(root).as_posix(),
                                      "sha256": record.get("sha256", ""), "kind": kind}
            continue
        if item["size"] > MAX_REMOTE_IMAGE_BYTES:
            summary.unsupported_or_failed += 1
            log.warning("Skipping remote image bigger than %d MB: %s", MAX_REMOTE_IMAGE_BYTES // (1024 * 1024), item["path"])
            continue
        raw_url = "https://raw.githubusercontent.com/{}/{}/{}/{}".format(
            urllib.parse.quote(owner, safe=""), urllib.parse.quote(repo, safe=""),
            urllib.parse.quote(branch, safe=""),
            urllib.parse.quote(item["path"], safe="/"))
        work.append((item, dest, raw_url))

    def fetch(one: tuple[dict[str, Any], Path, str]):
        item, dest, url = one
        data = _request_bytes(url)
        if not data:
            raise RuntimeError("empty image response")
        if item["size"] and len(data) != item["size"]:
            # Some GitHub proxy responses can be transformed. Image decode below is
            # still the final validation, but a major length mismatch is suspicious.
            if abs(len(data) - item["size"]) > max(32, int(item["size"] * 0.05)):
                raise RuntimeError(f"size mismatch ({len(data)} vs expected {item['size']})")
        # Reject HTML login/error pages mislabeled with an image extension.
        decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
        if decoded is None or decoded.size == 0:
            raise RuntimeError("downloaded bytes did not decode as an image")
        return item, dest, data, decoded

    failed: list[dict[str, str]] = []
    max_workers = max(1, min(int(workers), 8))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch, item): item[0]["path"] for item in work}
        for future in concurrent.futures.as_completed(futures):
            path = futures[future]
            try:
                item, dest, data, _ = future.result()
                _atomic_write(dest, data)
                kind = "watcher" if _is_watcher(item["path"]) else "target_source"
                updates[item["path"]] = {"remote_sha": item["sha"], "local_path": dest.relative_to(root).as_posix(),
                                          "sha256": _sha256(data), "kind": kind}
                summary.downloaded += 1
                if kind == "watcher":
                    summary.watchers += 1
                log.info("Synced image: %s", item["path"])
            except Exception as exc:
                failed.append({"path": path, "error": str(exc)})
                summary.unsupported_or_failed += 1
                log.warning("Could not sync image %s: %s", path, exc)

    # Preserve metadata for files which were skipped due to transient download
    # failure, but make no claim they were successfully synchronized this run.
    for item in images:
        if item["path"] not in updates and item["path"] in previous:
            updates[item["path"]] = previous[item["path"]]
    state_out = {
        "repository": repo_id, "branch": branch, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": updates, "failed": failed,
    }
    _atomic_write(state_path, json.dumps(state_out, indent=2).encode("utf-8"))
    if failed:
        log.warning("Image sync was partial: %d/%d download(s) failed. Re-run --sync-repository to retry.", len(failed), len(work))
    return {"summary": summary.to_dict(), "failed": failed, "state_path": str(state_path)}


def _grabcut_mask(img: np.ndarray) -> Optional[np.ndarray]:
    if img is None or img.size == 0 or img.ndim != 3:
        return None
    h, w = img.shape[:2]
    if min(h, w) < 14:
        return None
    pad = max(2, min(10, int(min(h, w) * 0.04)))
    if w <= 2 * pad or h <= 2 * pad:
        return None
    gc = np.zeros((h, w), np.uint8)
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(img[:, :, :3], gc, (pad, pad, w - 2 * pad, h - 2 * pad), bgd, fgd, 3, cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return None
    binary = np.where((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats((binary > 0).astype(np.uint8), 8)
    if count <= 1:
        return None
    min_area = max(35, int(h * w * 0.035))
    candidates = []
    for idx in range(1, count):
        x, y, cw, ch, area = [int(v) for v in stats[idx]]
        if area < min_area:
            continue
        # Foreground often includes an island of background texture. Prefer a
        # sizeable, centrally located component instead of blindly taking max.
        cx, cy = x + cw / 2, y + ch / 2
        dist = math.hypot((cx - w / 2) / max(1, w / 2), (cy - h / 2) / max(1, h / 2))
        score = math.sqrt(area) * (1.15 - 0.25 * min(1.8, dist))
        candidates.append((score, idx))
    if not candidates:
        return None
    _, idx = max(candidates)
    comp = (labels == idx).astype(np.uint8) * 255
    k = max(3, min(11, int(min(h, w) * 0.035) // 2 * 2 + 1))
    comp = cv2.morphologyEx(comp, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    out = np.zeros_like(comp)
    cv2.drawContours(out, [contour], -1, 255, thickness=cv2.FILLED)
    return out


def _bbox(mask: np.ndarray) -> Optional[tuple[int, int, int, int]]:
    ys, xs = np.where(mask > 0)
    if len(xs) < 1:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)


def _object_rgba(img: np.ndarray, mask: np.ndarray, *, pad_ratio: float = 0.06) -> Optional[np.ndarray]:
    box = _bbox(mask)
    if box is None:
        return None
    x0, y0, x1, y1 = box
    h, w = img.shape[:2]
    obj_w, obj_h = x1 - x0, y1 - y0
    if obj_w < 16 or obj_h < 16:
        return None
    pad = max(3, int(round(min(obj_w, obj_h) * pad_ratio)))
    x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)
    crop = img[y0:y1, x0:x1, :3]
    alpha = mask[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    rgba = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
    rgba[:, :, 3] = np.where(alpha > 0, 255, 0).astype(np.uint8)
    return rgba


def _valid_primary_crop(img: np.ndarray, mask: np.ndarray) -> tuple[bool, str, float]:
    h, w = img.shape[:2]
    box = _bbox(mask)
    if box is None:
        return False, "no foreground mask", 0.0
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    if bw < 16 or bh < 16:
        return False, "foreground is too small", 0.0
    mask_fraction = float(np.count_nonzero(mask)) / max(1, h * w)
    wf, hf = bw / max(1, w), bh / max(1, h)
    bx_area = wf * hf
    # A mask which spans almost the whole large image is generally a gameplay
    # screenshot/scene rather than a tightly cropped ghost. Do not click it as-is.
    if max(h, w) > 360 and wf >= 0.86 and hf >= 0.78:
        return False, "foreground spans nearly the whole scene", 0.12
    if mask_fraction < 0.06 or mask_fraction > 0.92:
        return False, "foreground coverage is implausible", 0.0
    # For small image assets, the user's repository is a positive-labelled corpus;
    # most are tight icon captures. Larger images need a central, reasonably sized
    # object region or they are held for proposal-based extraction/review.
    cx, cy = x0 + bw / 2, y0 + bh / 2
    center_dist = math.hypot((cx - w / 2) / max(1, w / 2), (cy - h / 2) / max(1, h / 2))
    if max(h, w) > 360 and (bx_area < 0.06 or bx_area > 0.88 or center_dist > 0.70):
        return False, "large image did not yield a centered target crop", 0.18
    sat = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2HSV)[:, :, 1]
    target_sat = float(np.mean(sat[mask > 0])) if np.any(mask > 0) else 0.0
    # Score is diagnostic only. Thresholds here determine whether the crop can be
    # safely activated as a target, not whether the target will match live frames.
    score = 0.30 + min(0.25, mask_fraction * 0.35) + min(0.20, bx_area * 0.25)
    score += min(0.15, target_sat / 255 * 0.15) + max(0.0, 0.10 - center_dist * 0.05)
    return True, "masked foreground crop accepted", min(0.99, score)


def _core_boxes(img: np.ndarray, maximum: int = 6) -> list[tuple[float, tuple[int, int, int, int]]]:
    """Find plausible bright/colorful object cores in a full gameplay screenshot."""
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2HSV)
    proposals: list[tuple[float, tuple[int, int, int, int]]] = []
    seen: list[tuple[float, float, float, float]] = []
    # The stricter mask keeps the frame background from becoming one giant blob.
    for sat_min, val_min in ((125, 180), (105, 165), (80, 185)):
        core = ((hsv[:, :, 1] >= sat_min) & (hsv[:, :, 2] >= val_min)).astype(np.uint8) * 255
        core = cv2.morphologyEx(core, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=2)
        count, _, stats, centers = cv2.connectedComponentsWithStats((core > 0).astype(np.uint8), 8)
        for idx in range(1, count):
            x, y, cw, ch, area = [int(v) for v in stats[idx]]
            box_area = cw * ch
            if cw < max(15, int(w * 0.025)) or ch < max(15, int(h * 0.025)):
                continue
            if area < max(40, int(h * w * 0.002)) or box_area > h * w * 0.42:
                continue
            aspect = cw / max(1, ch)
            if not 0.30 <= aspect <= 3.0:
                continue
            # UI controls tend to sit at the extreme edges/corners. A ghost's
            # main glow is usually in the gameplay area and often near center.
            cx, cy = float(centers[idx][0]), float(centers[idx][1])
            d = math.hypot((cx - w / 2) / max(1, w / 2), (cy - h / 2) / max(1, h / 2))
            if (x < 0.04 * w or x + cw > 0.96 * w) and d > 0.95:
                continue
            area_score = math.sqrt(area / max(1.0, h * w))
            score = (area_score * 3.0 + min(0.6, math.log1p(area) / 20.0)
                     + max(0.0, 0.55 - d * 0.45) + min(0.3, (aspect if aspect < 1 else 1 / aspect) * 0.3))
            box = (x, y, x + cw, y + ch)
            # Multi-threshold masks produce nearly identical proposals; keep one.
            if any(
                abs((x + x + cw) / 2 - (a + c) / 2) < max(10, w * 0.05)
                and abs((y + y + ch) / 2 - (b + d0) / 2) < max(10, h * 0.05)
                and abs((cw * ch) - ((c - a) * (d0 - b))) < h * w * 0.06
                for a, b, c, d0 in seen
            ):
                continue
            seen.append((float(x), float(y), float(x + cw), float(y + ch)))
            proposals.append((score, box))
    proposals.sort(key=lambda z: z[0], reverse=True)
    return proposals[:maximum]


def _crop_around_core(img: np.ndarray, core_box: tuple[int, int, int, int], scale: float = 2.0) -> Optional[np.ndarray]:
    h, w = img.shape[:2]
    x0, y0, x1, y1 = core_box
    cw, ch = x1 - x0, y1 - y0
    # Expand around bright facial/core detail to recover the surrounding silhouette.
    rw = min(w, max(cw + 8, int(round(cw * scale))))
    rh = min(h, max(ch + 8, int(round(ch * scale))))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx0 = max(0, min(w - rw, int(round(cx - rw / 2))))
    ry0 = max(0, min(h - rh, int(round(cy - rh / 2))))
    roi = img[ry0:ry0 + rh, rx0:rx0 + rw, :3]
    if roi.size == 0:
        return None
    mask = _grabcut_mask(roi)
    if mask is None:
        return None
    ok, _, _ = _valid_primary_crop(roi, mask)
    if not ok:
        return None
    return _object_rgba(roi, mask)


def _read_bgr(path: Path) -> Optional[np.ndarray]:
    raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if raw is None or raw.size == 0:
        return None
    if raw.ndim == 2:
        return cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
    if raw.shape[2] == 4:
        return raw[:, :, :3]
    return raw[:, :, :3]


def _signature(rgba: np.ndarray) -> tuple[int, np.ndarray, np.ndarray]:
    """Small perceptual signature retaining silhouette and color differences."""
    alpha = rgba[:, :, 3] > 0
    bgr = rgba[:, :, :3].copy()
    if np.any(alpha):
        bg = np.median(bgr[alpha], axis=0).astype(np.uint8)
        bgr[~alpha] = bg
    gray = cv2.cvtColor(cv2.resize(bgr, (9, 8), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    bits = (gray[:, 1:] > gray[:, :-1]).flatten()
    dh = 0
    for bit in bits:
        dh = (dh << 1) | int(bit)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    selected = alpha & (hsv[:, :, 1] >= 35)
    if np.any(selected):
        hist = cv2.calcHist([hsv], [0, 1], selected.astype(np.uint8) * 255, [12, 4], [0, 180, 0, 256])
    else:
        hist = np.zeros((12, 4), np.float32)
    hist = hist.astype(np.float32)
    cv2.normalize(hist, hist, alpha=1.0, norm_type=cv2.NORM_L1)
    mask = cv2.resize(alpha.astype(np.uint8), (48, 48), interpolation=cv2.INTER_NEAREST) > 0
    return dh, hist, mask


def _load_signature_index(seed_dir: Path) -> dict[str, tuple[int, np.ndarray, np.ndarray]]:
    index: dict[str, tuple[int, np.ndarray, np.ndarray]] = {}
    for path in seed_dir.glob("*.png"):
        img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if img is None:
            continue
        if img.ndim == 3 and img.shape[2] == 4:
            rgba = img
        else:
            bgr = img if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            rgba = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
            rgba[:, :, 3] = 255
        index[path.name] = _signature(rgba)
    return index


def _duplicate_target(candidate: np.ndarray,
                      output_index: dict[str, tuple[int, np.ndarray, np.ndarray]]) -> Optional[str]:
    sig_hash, sig_hist, cand_mask = _signature(candidate)
    # A shape-only match is not enough: different ghost colors must stay distinct.
    for name, (h0, hist0, other_mask) in output_index.items():
        distance = (h0 ^ sig_hash).bit_count()
        hist_distance = float(cv2.compareHist(sig_hist, hist0, cv2.HISTCMP_BHATTACHARYYA))
        union = int(np.count_nonzero(cand_mask | other_mask))
        mask_iou = float(np.count_nonzero(cand_mask & other_mask)) / max(1, union)
        if (distance <= 3 and hist_distance <= 0.11) or (mask_iou >= 0.80 and hist_distance <= 0.10):
            return name
    return None


def _save_pending(root: Path, source_rel: str, source_digest: str, image: np.ndarray, reason: str) -> str:
    pending_dir = root / "corpus" / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(source_rel).stem)[:45] or "image"
    out = pending_dir / f"{stem}_{source_digest[:8]}.jpg"
    if not out.exists():
        # Keep the original full image as evidence; it is deliberately NOT a target.
        cv2.imwrite(str(out), image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return out.relative_to(root).as_posix()


def build_target_templates(root: Path, *, force: bool = False) -> dict[str, Any]:
    """Extract/normalize target crops from the locally cached repository images.

    Small images are assumed to be positive-labelled tight target captures. For
    larger screenshots, segmentation must produce a centered, not-nearly-full-frame
    target. If not, the source remains in the corpus/pending gallery and is never a
    live click template. This avoids the dangerous failure mode of matching a whole
    scene as though it were a ghost.
    """
    root = Path(root).resolve()
    raw_dir = root / "corpus" / "repository"
    seed_dir = root / "seeds"
    pending_dir = root / "corpus" / "pending"
    seed_dir.mkdir(parents=True, exist_ok=True)
    if not raw_dir.is_dir():
        return {"sources_seen": 0, "target_crops_added": 0, "duplicate_crops": 0, "pending_review": 0,
                "failed": 0, "message": "No corpus/repository folder yet; run --sync-repository first."}
    import_state_path = root / "corpus" / "repository_import.json"
    import_state = _manifest_load(import_state_path)
    old_records = import_state.get("sources", {}) if isinstance(import_state.get("sources", {}), dict) else {}
    new_records: dict[str, Any] = {}
    signature_index = _load_signature_index(seed_dir)
    summary = {"sources_seen": 0, "unchanged_sources": 0, "target_crops_added": 0,
               "duplicate_crops": 0, "pending_review": 0, "failed": 0,
               "importer_version": IMPORTER_VERSION, "sources": {}}
    source_files = sorted(p for p in raw_dir.rglob("*") if p.is_file() and p.suffix.casefold() in IMAGE_SUFFIXES)
    for source in source_files:
        source_rel = source.relative_to(raw_dir).as_posix()
        if _is_watcher(source.name):
            # Names in this corpus should not generally include watchers; route any
            # that do appear to ./ok anyway as belt-and-suspenders.
            dest = root / "ok" / source.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                try:
                    _atomic_write(dest, source.read_bytes())
                except OSError:
                    summary["failed"] += 1
            continue
        try:
            source_bytes = source.read_bytes()
        except OSError as exc:
            summary["failed"] += 1
            log.warning("Could not read cached source %s: %s", source, exc)
            continue
        digest = _sha256(source_bytes)
        old = old_records.get(source_rel, {}) if isinstance(old_records.get(source_rel, {}), dict) else {}
        if (not force and old.get("sha256") == digest and old.get("importer_version") == IMPORTER_VERSION
                and all((root / rel).is_file() for rel in old.get("outputs", []))):
            new_records[source_rel] = old
            summary["sources_seen"] += 1
            summary["unchanged_sources"] += 1
            continue
        image = cv2.imdecode(np.frombuffer(source_bytes, np.uint8), cv2.IMREAD_UNCHANGED)
        if image is None:
            summary["failed"] += 1
            log.warning("Cached file is not a supported image: %s", source)
            continue
        if image.ndim == 2:
            bgr = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        else:
            bgr = image[:, :, :3]
        h, w = bgr.shape[:2]
        outputs: list[str] = []
        added = duplicates = pending = failed = 0
        candidates: list[tuple[np.ndarray, float, str]] = []

        source_mask = None
        if image.ndim == 3 and image.shape[2] == 4 and np.count_nonzero(image[:, :, 3] < 250) > 16:
            source_mask = np.where(image[:, :, 3] >= 32, 255, 0).astype(np.uint8)
        else:
            source_mask = _grabcut_mask(bgr)
        if source_mask is not None:
            ok, reason, score = _valid_primary_crop(bgr, source_mask)
            if ok and score >= 0.42:
                rgba = _object_rgba(bgr, source_mask)
                if rgba is not None:
                    candidates.append((rgba, score, reason))
        # Big screenshots may have failed the whole-frame mask test. Search bright
        # cores, expand around them, and run GrabCut locally. Only the best candidate
        # is activated; extra/ambiguous scene material stays in the pending corpus.
        if not candidates and max(h, w) > 220:
            for core_score, box in _core_boxes(bgr, maximum=8):
                for expand in (2.0, 2.35, 1.7):
                    rgba = _crop_around_core(bgr, box, scale=expand)
                    if rgba is None:
                        continue
                    # score candidate by seed crop geometry and bright-core centrality
                    bonus = min(0.15, core_score * 0.025)
                    candidates.append((rgba, min(0.95, 0.50 + bonus), f"bright-core crop ({expand:.2f}x)") )
                    break
                if len(candidates) >= 3:
                    break

        # Keep one active template per source image to avoid exploding scan cost
        # from UI icons or multiple people/particles in full-screen screenshots.
        if candidates:
            candidates.sort(key=lambda c: c[1], reverse=True)
            candidate, score, reason = candidates[0]
            duplicate = _duplicate_target(candidate, signature_index)
            if duplicate:
                duplicates += 1
                log.debug("Repository image %s resolves to existing template %s", source_rel, duplicate)
            else:
                slug = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(source_rel).stem)[:42] or "ghost"
                out_name = f"repo_{slug}_{digest[:8]}.png"
                out_path = seed_dir / out_name
                if not cv2.imwrite(str(out_path), candidate):
                    failed += 1
                    log.warning("Could not write generated seed %s", out_path)
                else:
                    outputs.append(out_path.relative_to(root).as_posix())
                    signature_index[out_name] = _signature(candidate)
                    added += 1
                    log.info("Imported target crop %s (%dx%d, confidence %.2f, %s)",
                             out_name, candidate.shape[1], candidate.shape[0], score, reason)
        else:
            rel_pending = _save_pending(root, source_rel, digest, bgr,
                                        "full-scene target could not be isolated with confidence")
            outputs.append(rel_pending)
            pending += 1
            log.warning("Source needs target-crop review, not activated as a click target: %s", source_rel)

        rec = {"sha256": digest, "importer_version": IMPORTER_VERSION, "outputs": outputs,
               "added": added, "duplicates": duplicates, "pending": pending, "failed": failed}
        new_records[source_rel] = rec
        summary["sources_seen"] += 1
        summary["target_crops_added"] += added
        summary["duplicate_crops"] += duplicates
        summary["pending_review"] += pending
        summary["failed"] += failed
        summary["sources"][source_rel] = {"outputs": outputs, "added": added, "duplicates": duplicates,
                                           "pending": pending, "confidence": round(candidates[0][1], 3) if candidates else None}

    summary["sources"] = summary["sources"] if summary["sources"] else {}
    state_out = {"importer_version": IMPORTER_VERSION, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "sources": new_records, "report": {k: v for k, v in summary.items() if k != "sources"}}
    _atomic_write(import_state_path, json.dumps(state_out, indent=2).encode("utf-8"))
    # Human-readable compact report; detailed per-file decisions live in JSON.
    report_path = root / "corpus" / "repository_import_report.json"
    _atomic_write(report_path, json.dumps(summary, indent=2).encode("utf-8"))
    return summary


def sync_and_import_repository(root: Path, repository: str = DEFAULT_REPOSITORY,
                               branch: str = DEFAULT_BRANCH, *, force: bool = False) -> dict[str, Any]:
    """One entry point used by the command-line option; returns both summaries."""
    sync = sync_repository_images(root, repository=repository, branch=branch, force=force)
    imported = build_target_templates(root, force=force)
    return {"sync": sync, "import": imported}
