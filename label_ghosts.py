"""Label ghost crops: python label_ghosts.py [--root .]

The bot saves crops of what it sees to labels/unlabeled/. This tool shows them
one by one with the bot's guess in the title; press a key to file each one under
labels/<kind>_<colour>/ (the bot reloads these on F10 or at restart).

  SMALL ghosts            BOSS ghosts
  1 blue    (+5)          q blue     w cyan      e green    r light green
  2 purple  (+15)         t red      y white     u rainbow
  3 yellow  (+55)
  4 rainbow (+100)
  SPACE accept the guess   x not a ghost (delete)   s skip   ESC quit
"""
from __future__ import annotations
import argparse, shutil
from pathlib import Path
import cv2, numpy as np

KEYS = {
    ord("1"): ("small", "blue"), ord("2"): ("small", "purple"),
    ord("3"): ("small", "yellow"), ord("4"): ("small", "rainbow"),
    ord("q"): ("boss", "blue"), ord("w"): ("boss", "cyan"), ord("e"): ("boss", "green"),
    ord("r"): ("boss", "light-green"), ord("t"): ("boss", "red"),
    ord("y"): ("boss", "white"), ord("u"): ("boss", "rainbow"),
}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--root", default=".")
    root = Path(ap.parse_args().root).resolve()
    src = root / "labels" / "unlabeled"
    files = sorted(src.glob("*.png")) if src.exists() else []
    if not files:
        print("Nothing to label yet: run the bot while ghosts are on screen (labeling_collect=true)."); return
    done = 0
    for f in files:
        img = cv2.imdecode(np.fromfile(str(f), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        parts = f.stem.split("_")                    # frac _ kind-colour _ timestamp
        guess = parts[1] if len(parts) > 2 else ""
        gk, _, gc = guess.partition("-")
        view = cv2.resize(img, None, fx=max(1.0, 220 / max(img.shape[:2])), fy=max(1.0, 220 / max(img.shape[:2])),
                          interpolation=cv2.INTER_CUBIC)
        title = f"[{done+1}/{len(files)}] guess: {gk} {gc}  | 1-4 small, q-u boss, SPACE=accept, x=not ghost, s=skip"
        cv2.imshow("label_ghosts", view); cv2.setWindowTitle("label_ghosts", title)
        k = cv2.waitKey(0) & 0xFF
        if k == 27:
            break
        if k == ord("s"):
            continue
        if k == ord("x"):
            f.unlink(); done += 1; continue
        choice = (gk, gc) if k == 32 and gk in ("small", "boss") else KEYS.get(k)
        if not choice:
            continue
        dest = root / "labels" / f"{choice[0]}_{choice[1].replace(' ', '-')}"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), str(dest / f.name)); done += 1
    cv2.destroyAllWindows()
    print(f"Labelled {done} crop(s). Press F10 in the bot (or restart) to load them.")

if __name__ == "__main__":
    main()
