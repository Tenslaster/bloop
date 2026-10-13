# BLOOP — Highrise Ghost Vision Bot

> Complete operator, developer, configuration, diagnostics, and release manual for the BLOOP Highrise ghost/effect detection project.
>
> This document is intentionally longer than a typical README because it includes a detailed configuration reference, a source-symbol index, troubleshooting playbooks, operational scenarios, and a validation catalog. Start with **Quick start**, **Runtime architecture**, and **Troubleshooting**.

## Table of contents

- [Project and repository status](#project-and-repository-status)
- [What BLOOP does](#what-bloop-does)
- [Important limits and safety](#important-limits-and-safety)
- [Project layout](#project-layout)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [First-run checklist](#first-run-checklist)
- [Using the GUI](#using-the-gui)
- [GUI operator guide](GUI_GUIDE.md)
- [Command-line interface](#command-line-interface)
- [Runtime architecture](#runtime-architecture)
- [Window discovery and capture](#window-discovery-and-capture)
- [Image detection and matching](#image-detection-and-matching)
- [Target and watcher images](#target-and-watcher-images)
- [Exploration and feedback](#exploration-and-feedback)
- [Click safety](#click-safety)
- [Performance tuning](#performance-tuning)
- [Configuration guide](#configuration-guide)
- [Logs and diagnostics](#logs-and-diagnostics)
- [Repository importer](#repository-importer)
- [Optional smart-learning and reporting modules](#optional-smart-learning-and-reporting-modules)
- [Customer executable packaging](#customer-executable-packaging)
- [Tests and quality assurance](#tests-and-quality-assurance)
- [Security and privacy](#security-and-privacy)
- [Troubleshooting](#troubleshooting)
- [Operational playbooks](#operational-playbooks)
- [Developer workflow](#developer-workflow)
- [Exhaustive configuration reference](#exhaustive-configuration-reference)
- [Source symbol index](#source-symbol-index)
- [Troubleshooting atlas](#troubleshooting-atlas-observable-symptom-to-evidence-driven-fix)
- [Validation catalog](#validation-catalog-and-test-design)
- [File-by-file checklist](#file-by-file-checklist)
- [Glossary](#glossary)
- [FAQ](#faq)
- [Release checklist](#release-checklist)

---

## Project and repository status

BLOOP is a Windows-oriented computer-vision automation project for recognizing ghost/effect sprites in the Highrise client. The runtime captures a game window, proposes regions likely to contain a target, verifies them against available templates, applies safety checks, optionally sends mouse input, and records evidence for later decisions.

Repository link: <https://github.com/Tenslaster/bloop>.

**Repository inspection note (2026-10-11):** the public GitHub root view showed image assets and a README, but did not show the Python runtime, GUI, dependency manifest, or executable build scripts in the visible root file listing. This manual also documents the source modules supplied alongside this work. A fresh clone cannot run the full application unless the source and required data files are committed to that repository or distributed separately. Verify the current branch and repository tree before publishing this README as a promise of a runnable checkout.

### Scope and source-of-truth rule

This manual uses the latest integrated source snapshot supplied for this task as its reference: the engine snapshot (`main(9).py`, normalized here as `main.py`) wires `SmartGhost` and `WebhookReporter` when available, conditionally wires `PopupDismisser`, and exposes the supervised-learning CLI. The corresponding GUI snapshot (`gui(1).py`, normalized here as `gui.py`) includes the learning, sample-management, popup and webhook pages. These numbered names are upload names, not recommended project filenames. Put the matching source files beside one another under the canonical names shown in the layout before using the commands. Earlier or reduced engine snapshots in the same project may lack these capabilities; a companion file is active only if the running entry point imports, constructs and calls it.

The behavior of a particular release is determined by its source revision, configuration schema, data files, and build recipe. If the implementation and this README disagree, inspect the implementation and update the documentation before shipping.

For the detailed command and configuration sections below, the reference implementation is the newest integrated source snapshot supplied for this task. It is normalized to the conventional filenames `main.py` and `gui.py` for documentation. The public GitHub listing was asset-only at inspection time, so commit the matching Python modules, model/dependency manifest and build files if you want a fresh clone to be runnable.

### Compatibility policy

- The examples are based on the source bundle inspected on 2026-10-11.
- Confirm CLI flags against the actual `main.py` and the actual compiled binary.
- An existing EXE does not update when a neighboring `.py` file is edited.
- Keep a versioned copy of configuration defaults for each release.
- Test optional dependencies both present and absent.
- Do not state that an executable passed Windows testing unless it was actually run on Windows.

## What BLOOP does

Depending on which modules are wired into the selected runtime, BLOOP can:

1. locate a candidate Highrise window and calculate its rectangle;
2. capture the client area or a configured region;
3. prepare resized frame representations and masks;
4. propose visual regions that may contain a ghost/effect;
5. compare those candidates against image templates at supported scales;
6. merge overlapping detections and limit instance count;
7. block unsafe actions using cooldowns, budgets, exclusion zones, popup watchers, and window checks;
8. run in dry-run mode or dispatch mouse/keyboard input;
9. queue post-action feedback checks instead of waiting synchronously in the frame loop;
10. persist learned target images and evidence metadata;
11. import image collections from a public repository;
12. optionally train/score samples through the separate smart learner;
13. optionally detect reward toasts and send user-configured webhook reports;
14. emit logs and timing metrics for diagnosing misses, false positives, and stalls.

The base matcher is computer vision, not guaranteed semantic understanding. A high similarity score is evidence that two regions resemble each other under a chosen metric. It is not a calibrated probability that a region is a ghost.

## Important limits and safety

- **Dry run does not mean live input.** `--dry-run` should log prospective actions and must not invoke the real input driver.
- **Input dispatch is not game confirmation.** A successful `pydirectinput` call does not prove that Highrise accepted a catch.
- **Pixel change is weak feedback.** Ambient animation, avatar movement, and unrelated UI changes can occur after a click. A healthy, correctly associated reward watcher is stronger evidence.
- **A seed does not encode motion.** Templates encode appearance; searching each frame or tracking candidates handles movement.
- **Whole-room screenshots are not safe target templates.** They contain unrelated objects and may match arbitrary scenery. Treat them as source material until an actual sprite has been isolated.
- **Color alone is insufficient.** Outfits, lights, decorations, and ghosts may share colors. Use shape/edge evidence and negative-frame tests.
- **Customer read-only behavior must be enforced in the engine.** Hiding a training button is not enough if the runtime can still write model/sample files.
- **Fail closed on a bad capture.** If the game window or frame cannot be verified, skip the action and explain why. Do not fall back to blind desktop-wide clicks.
- **Global hotkeys may be restricted by OS permissions.** Keep a GUI Stop button and/or Ctrl+C fallback.
- **Model and sample compatibility matters.** A model archive must match the feature preprocessing and architecture used by the selected code.
- **Do not publish webhook secrets.** Use a private user setting or environment variable where supported. A live-looking Discord webhook URL appeared in development configuration; if it was active, rotate it. This README does not repeat it.

## Project layout

A full source distribution should resemble the following. Some items are optional and may be absent from an image-only repository checkout.

```text
bloop/
├── README.md
├── main.py                         # capture, vision pipeline, safety, persistence and CLI
├── gui.py                          # developer Tkinter GUI, if included
├── BLOOP.pyw                       # no-console GUI launcher, if included
├── launch_gui.bat                  # visible-console launcher, if included
├── config.json                     # secret-free runtime defaults
├── repository_import.py            # source image sync and crop generator
├── smart_ghost.py                  # optional supervised model and tracker
├── sample_manager.py               # optional sample review UI
├── popup_dismiss.py                # optional completion-popup helper
├── webhook_reporter.py             # optional reward-toast OCR and webhook reporter
├── smart/model.npz                # optional learned classifier weights for SmartGhost
├── VagueComplete.png               # optional popup reference image
├── requirements.txt                # runtime dependencies
├── requirements-build.txt          # packaging dependencies
├── seeds/                          # known ghost/effect images
├── learned/                        # persistent learned target images and metadata
├── ok/                             # confirmation watcher references, never click targets
├── corpus/repository/               # downloaded image source corpus
├── corpus/pending/                  # unresolved scenes/crops awaiting review
├── smart/positives/                 # optional positive samples
├── smart/negatives/                 # optional negative samples
├── smart/quarantine/                # optional samples under review
├── diagnostics/                     # overlays and diagnostic images
├── logs/                            # rotating bot logs and GUI startup traces
├── .runtime/                        # cooperative GUI control file
├── tests/                            # unit, fixture, GUI and mocked integration tests
└── dist/                             # built executable output; do not commit blindly
```

### File responsibility matrix

| File or folder | Responsibility | Important boundary |
|---|---|---|
| `main.py` | Integrated engine, config, capture, detection, safety, smart integration, click dispatch, CLI | Optional imports can fail; verify startup capability logs |
| `gui.py` | Tkinter control panel and engine process management | CPU-heavy vision should run in the engine process, not the Tk callback |
| `BLOOP.pyw` | Starts the GUI without an extra console | Does not bundle Python or compile the project |
| `launch_gui.bat` | Visible-console startup and diagnostics | A launcher is not a substitute for the engine |
| `repository_import.py` | Syncs source image assets, derives crops, records manifest/report | Every source image is not necessarily a valid target |
| `smart_ghost.py` | Click-supervised data, features, model training/inference and motion tracking | Loaded by the integrated snapshot when available and enabled in config |
| `sample_manager.py` | Optional positive/negative/quarantine review | Review does not guarantee a valid model without training/validation |
| `popup_dismiss.py` | Optional popup detection/action sequence | Popup actions are separate from ghost actions |
| `webhook_reporter.py` | Toast OCR, gain events and HTTP delivery | Reporter initialization depends on configured webhook URL and module availability; OCR needs Tesseract |
| `config.json` | Runtime settings | Must not contain credentials in a public repo |
| `smart/model.npz` | Optional trained model arrays used by `SmartGhost` | Must match the feature/model schema; back up before replacement |
| `seeds/` | Known target references | Avoid full-room screenshots as templates |
| `learned/` | Persisted learned target evidence | Back up PNGs and metadata together |
| `ok/` | Confirmation watcher images | Watchers identify state; they are not click targets |
| `corpus/pending/` | Source material that could not be safely cropped | Review manually rather than auto-clicking it |

## Prerequisites

### Operating system

The live window-capture and input workflow is intended primarily for Windows. Pure image-processing helpers can be tested on other platforms, but a Linux sandbox cannot establish real Windows window handles, client-area capture correctness, keyboard hooks, or game-side input acceptance.

### Python

Use a supported CPython release compatible with the actual dependency manifest. The supplied source uses modern type syntax; Python 3.10+ is a practical baseline, but verify the exact release required by your build recipe.

```powershell
py --version
py -0p
python --version
```

Use one interpreter for install, tests, GUI and packaging. A package installed into one Python environment may be missing from another.

### Core and optional dependencies

The base engine imports NumPy and OpenCV. Optional capture/input paths use `mss`, `pydirectinput`, `keyboard`, `pywin32`, and `pynput`. The OCR/webhook companion may use `requests`, `pytesseract`, and a separately installed Tesseract executable.

Prefer the exact manifest when available:

```powershell
py -m pip install -r requirements.txt
```

Only run that command when the checked-out release actually includes `requirements.txt`. The public repository view inspected for this guide did not show that manifest or the runtime modules. If you are preparing a source checkout from the supplied scripts and there is no manifest, use the explicit install commands below and maintain a real requirements file for your release.

For a minimal base environment, the imports suggest these likely runtime packages:

```powershell
py -m pip install numpy opencv-python mss pydirectinput keyboard pywin32 pynput
```

Optional OCR/reporting may also need:

```powershell
py -m pip install requests pytesseract
```

`pytesseract` is a Python wrapper. It does not install the separate Tesseract binary. Verify the OCR installation with `tesseract --version` or configure the supported path in the environment.

### GPU note

Ordinary calls such as `cv2.matchTemplate` run on the CPU in the standard OpenCV build. A GTX 1050 Ti does not automatically accelerate them. Tune the working frame dimensions, number of target scales, candidate budget, cache reuse and blocking operations before assuming GPU acceleration is needed.

## Quick start

### 1. Obtain the complete project

```powershell
git clone https://github.com/Tenslaster/bloop.git
cd bloop
```

This only produces a runnable checkout if the repository contains the source modules and dependency/data files. If the repo is currently image-only, use the complete source package separately or commit the source code first.

### 2. Create an isolated environment

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

If the release includes a dependency manifest, install it with:

```powershell
python -m pip install -r requirements.txt
```

If it does not, install dependencies according to the selected source modules as described above. Do not assume an image-only checkout contains executable code.

If activation is blocked by PowerShell policy, call the environment interpreter directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. Configure the project root and window

Keep `config.json` beside `main.py`, or pass `--root` to the directory containing configuration and data folders. The integrated source snapshot documented here supports `--process highrise.exe`; process matching is preferred to a broad title substring when configured. Always run `python main.py --help` against the exact source or executable you will launch: a frozen EXE may have been built from an older parser and reject options that exist in a newer `.py` file.

### 4. Preview without clicks

```powershell
py main.py --root . --process highrise.exe --dry-run --scan-every-frame
```

If the target process name is unknown, use `--list-windows` and the source's process/title logging to identify the correct selector. Keep Highrise open and visible. Confirm the frame, detection boxes, target names, coordinates and scores. Dry-run should never call the live input driver.

### 5. Live mode after preview is correct

```powershell
py main.py --root . --process highrise.exe --patient
```

This enables live input for known target logic, subject to the configured safety gates. Use `--explore` only after known-target detection and negative-frame behavior have been validated. Do not enable exploration to work around a broken capture path. If you need to build the learner first, run the teacher-mode command below instead of autonomous clicking.

### 6. Stop and review

Use the configured engine quit hotkey (the integrated source default is F12) or Ctrl+C from the terminal. The separate client GUI may use its own F12 action to toggle start/stop; do not assume the client and engine bind the same key in every build. Confirm a clean stop/save message and inspect the newest file under `logs/` before making threshold changes.

## First-run checklist

- [ ] Complete source files and their dependencies are present.
- [ ] `config.json` parses and has the expected schema.
- [ ] The correct Python interpreter has OpenCV and NumPy installed.
- [ ] Highrise is open and its title matches `window_title`.
- [ ] Capture produces a non-empty, current frame.
- [ ] FPS/tick telemetry advances.
- [ ] Diagnostic overlay coordinates align with the original frame.
- [ ] Target images are tightly cropped sprites rather than entire rooms.
- [ ] `ok/` contains only confirmation/watch references.
- [ ] Preview detects ghosts and rejects ordinary room details.
- [ ] Exclusion zones protect menus, chat and non-target UI.
- [ ] Click caps/cooldowns remain conservative during tuning.
- [ ] No repeated `CAPTURE WAIT` messages remain unexplained.
- [ ] Live input is enabled only after dry-run verification.
- [ ] `learned/`, model data and config have backups.
- [ ] No webhook secret is included in public files.

## Using the GUI

The developer GUI is a dark Tkinter control surface around a separate engine process. The refreshed layout has eight pages and a persistent bottom command dock so Preview, Start Live, Pause/Resume, Stop & Save, and Save remain accessible without leaving the current page. A global searchable settings index (Ctrl+K) can jump to a field by label or config key. See [`GUI_GUIDE.md`](GUI_GUIDE.md) for the operator guide and profile trade-offs.

The GUI should remain responsive while vision runs in the child process; worker-thread output should be marshalled back onto Tk's event loop. The focused pages cover common tasks, while Advanced Settings exposes every remaining engine setting; `patient_mode` is represented by the inverse `auto_learning` control to avoid contradictory duplicate options.

### Launch

No-console GUI launch when `BLOOP.pyw` exists:

```powershell
pyw BLOOP.pyw
```

Visible-console diagnostic launch:

```powershell
py -3 gui.py
```

A supplied batch launcher may also be used for visible startup diagnostics. Keep it simple and verify which Python interpreter it selects.

### Controls

The bottom command dock is pinned across all pages:

- **Preview:** detects and logs without real mouse/keyboard input.
- **Start Live:** asks for confirmation, then starts the process that can dispatch real input after safety checks.
- **Pause / Resume:** pauses actions without deleting state. When the controller has to be hidden for safety, it is hidden before the engine resumes.
- **Stop & Save:** requests a cooperative stop so files can be saved; fallback termination is used only if the stop request times out.
- **Save:** validates and writes the current config. Unsaved edits are clearly marked; most settings apply when the engine is next started.

The sidebar has eight pages: Overview, Runtime & Speed, Vision & Detection, Learning & Safety, Model & Samples, Rewards & Webhook, Diagnostics, and Advanced Settings. The advanced page exposes all remaining `main.Config` fields, including hotkeys and exclusion zones. Import/Export Config, Restore Defaults, Validate Settings, Safe/Balanced/Fast profiles, and CPU-count-based Auto-tune are available. Profiles edit the form only; they do not auto-save or train the model.

### Scrolling and screen scaling

Every page, including Overview and Advanced Settings, is vertically scrollable. The Canvas scroll region follows content size changes; mouse-wheel routing operates over the active page, and Page Up/Page Down plus Ctrl+Home/Ctrl+End provide keyboard access. The footer command dock stays visible. The intended minimum window size is 900×600, and captions dynamically wrap within responsive settings fields. Test Windows scaling at 100%, 125% and 150%.

### Do not click the GUI

The GUI must not be mistaken for Highrise capture. Live mode should hide/minimize the controller, pause when the controller is restored, and hide the controller before resuming. The engine must separately revalidate the selected game window and proposed click point. UI-only protections are not sufficient.

## Command-line interface

The current inspected `main.py` parser supports the following options. A compiled executable may differ if it was built from another revision; compare its `--help` output before relying on these options.

| Option | Meaning | Notes |
|---|---|---|
| `--window`, `-w` | Window-title substring | Used when a process name is not configured or selected, depending on window discovery rules |
| `--process` | Executable/process name, e.g. `highrise.exe` | Overrides the configured process selector in the integrated source snapshot |
| `--teach` | Teacher mode | Bot sends no input while collecting human-click examples if smart learning is wired and available |
| `--no-smart` | Disable click-supervised smart learning | Falls back to non-smart logic available in that build |
| `--root` | Project data/config root | Defaults to the current directory |
| `--debug` | Debug logging mode | More detailed diagnostic output |
| `--log-level` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` | Common console/file override |
| `--dry-run` | No real input | Use before live mode |
| `--explore` | Enable exploration | Overrides patient mode when supported |
| `--patient` | Disable exploratory clicks | Known templates may still run live |
| `--no-explore` | Disable unseen-target exploration | Exploration off |
| `--scan-every-frame` | Fast proposal pass on each captured frame | More CPU work is possible |
| `--full-template-every-frame` | Raise exact-template budget | Diagnostic and CPU-heavy, still bounded in current source |
| `--control-file` | GUI cooperative control JSON | Use a unique path for each independent instance |
| `--reset-learned` | Delete learned target data | Destructive; back up first |
| `--max-cps` | Override click-rate budget | Still bounded by validation |
| `--list-windows` | List visible window titles | Does not start detection |
| `--sync-repository [OWNER/REPO]` | Download/import repository images | One-shot task, not live frame loop |
| `--force-reimport` | Force crop regeneration | Pair with sync or local corpus reimport |
| `--reimport-corpus` | Rebuild crops from local repository corpus | Does not require a network call |

### Common commands

List visible windows:

```powershell
py main.py --list-windows
```

Preview only known templates:

```powershell
py main.py --root . --window Highrise --dry-run --patient
```

Preview with the fast scan every frame:

```powershell
py main.py --root . --window Highrise --dry-run --scan-every-frame
```

Live mode with known targets only:

```powershell
py main.py --root . --window Highrise --patient
```

Live mode with exploration enabled after preview validation:

```powershell
py main.py --root . --process highrise.exe --explore
```

Human-supervised teaching mode (no bot-generated mouse input):

```powershell
py main.py --root . --process highrise.exe --teach
```

In the integrated source snapshot, `--teach` disables smart autonomous clicking and sets the engine's dry-run behavior while the smart module listens for the user's own clicks. It is not equivalent to running with no capture: the game still needs to be selected and a valid frame must be available. Verify startup logs say the smart learner and click hook are available before assuming samples are being collected.

Disable the smart learner explicitly:

```powershell
py main.py --root . --process highrise.exe --no-smart --dry-run
```

Sync the public reference-image collection:

```powershell
py main.py --root . --sync-repository Tenslaster/bloop
```

Reprocess the local image corpus:

```powershell
py main.py --root . --reimport-corpus --force-reimport
```

Use destructive reset flags only after making a backup of `learned/` and related metadata.

## Runtime architecture

The core runtime is a recurring frame loop. Capture and processing are mostly synchronous in the base engine, so a slow matcher can dominate frame time. `loop_delay` is a pacing floor, not a guarantee that the process can reach a target FPS when each iteration takes longer than the requested interval.

### Pipeline stages

1. Parse arguments and load the config.
2. Configure logging and OpenCV thread count.
3. Discover the game window.
4. Load target templates and watcher images.
5. Capture a current frame.
6. Prepare scaled/gray/edge/color representations.
7. Generate fast candidate boxes.
8. Match candidate crops against known targets.
9. Run a bounded rotating fallback through exact templates.
10. Merge overlapping detections and cap accepted instances.
11. Check popup/reward watchers.
12. Apply budgets, per-target cooldowns, spatial guard, exclusions and window checks.
13. Log the decision and either perform a dry run or dispatch input.
14. Queue delayed feedback checks.
15. Save state periodically and emit timing telemetry.

### Why there are multiple detectors

A fast proposal path can react quickly but may miss unusual colors or shapes. Exact template matching recovers some difficult cases but becomes expensive when the library grows. A rotating per-frame template budget spreads this cost out. All paths must call the same click guards; otherwise one object can be clicked once per template or once per detector type.

### Threading rules

- Keep network sync outside the live frame loop.
- Keep OCR and HTTP request work off the frame thread.
- Avoid waiting synchronously for post-click feedback.
- Never mutate Tk widgets directly from an engine-reader worker thread.
- Poll stop/pause controls between bounded units of work.
- Keep worker shutdown bounded and observable.

## Window discovery and capture

### Title selection

The current base engine selects a window by a title substring. Use a substring distinctive enough not to match the controller, another application, or a browser tab. Some customer builds may include process-name selection; do not assume it exists in every source version.

### Client-area capture

`window_client_only=true` is intended to capture the Highrise client area rather than window borders/desktop chrome. This reduces non-game pixels in the vision pipeline, but correctness depends on client rectangle and DPI coordinate handling. Screen capture and PrintWindow can behave differently with hardware-accelerated content, minimization and occlusion.

### When capture fails

- Restore Highrise if minimized.
- Verify the configured title.
- Check the logged rectangle and frame shape.
- Check `mss` and `pywin32` availability on Windows.
- Check display scaling/DPI awareness.
- Check whether another window is foreground if the engine requires foreground capture.
- Save a diagnostic frame from the same capture path the engine uses.
- Do not use stale pixels to send new clicks.

## Image detection and matching

### Template matching

The engine prepares target images, compares them at allowed scales and accepts matches above a target threshold. Grayscale correlation can tolerate some palette variation but can confuse similar silhouettes. Mask and edge validation may improve distinction when enabled by the selected code path.

### Scale selection

A scale factor multiplies the reference width and height. A 50-pixel template at 0.7 scale is around 35 pixels wide; at 1.25 it is around 63 pixels wide. Too few scales miss actual sizes; too many scales increase CPU work. Base scales should cover real in-game dimensions rather than every possible fractional step.

### Scores are not probabilities

A score of 0.95 is a similarity value, not a 95% probability. UI textures, glowing clothes, room decorations and other sprites can accidentally score highly. Tune thresholds using several labeled positive and negative images, not only the best-looking example.

### Proposal versus verification

A proposal is a region worth examining, not a confirmed ghost. Color, hue, contrast, foreground segmentation and edges can suggest locations, but every candidate should pass a template/shape verification stage before it is allowed to click.

### Non-maximum suppression

NMS removes boxes whose overlap with a higher-scoring box is too high. This limits duplicate work around one sprite. Overly strict NMS can merge close ghosts; overly loose NMS can return several boxes for one ghost. Test both single- and multi-instance frames.

### Coordinate transforms

When matching at a reduced resolution, every box must be mapped back to the original frame exactly once. The window origin then maps frame coordinates to absolute screen coordinates. A transform error can create believable scores and completely wrong clicks. Diagnostic boxes must agree with mouse coordinates on the actual display.

## Target and watcher images

### `seeds/`

Known reference images. A strong seed is a tight crop of one whole sprite with little unrelated scenery. Keep color/facing variants separate when they materially differ. Keep source provenance if a crop came from a larger screenshot.

### `learned/`

Persistent targets created by the active learning path. Images and their metadata should be backed up together. A PNG without its corresponding threshold/evidence metadata may behave differently after restart.

### `ok/`

Confirmation watcher templates, including the provided `ok.png` and `okay.jpg` naming convention. Watchers identify a popup/confirmation state and must never enter the click-target bank. A watcher match is not itself a ghost click.

### `corpus/repository/` and `corpus/pending/`

The repository corpus retains downloaded source assets and makes import repeatable. The pending folder retains scenes/crops that cannot safely be activated automatically. Review pending scenes manually, then crop the exact ghost into a target reference. Never use an entire room screenshot as a live template.

### Good target crop checklist

- The intended ghost is the primary object in the crop.
- The complete silhouette is visible.
- Margins are modest and consistent.
- Face/glow evidence is preserved.
- Compression noise is not the main structure.
- UI icons and watcher popups are excluded from the target bank.
- Negative-scene fixtures verify that the crop does not match ordinary scenery.
- Different colors/facings are represented when necessary.

## Exploration and feedback

Exploration attempts to find plausible unseen forms after known templates fail. That path is riskier because it must judge candidates without an exact reference. It should not be used as a substitute for working capture, well-cropped known seeds or verified target matching.

### Delayed feedback

After an action, the engine can save the clicked point/crop and compare a later frame. Local disappearance may be useful weak evidence, but unrelated room animation is not proof of a catch. Explicit reward watcher/OCR evidence is stronger when the observer is healthy and correctly wired to the runtime.

### Retry backoff and quarantine

Repeated unconfirmed attempts should be spaced farther apart. A target that repeatedly fails can be temporarily quarantined without deleting its file. If a valid target is punished because the watcher is broken, repair the observer before weakening quarantine rules.

### Supervised click learning

The integrated source snapshot imports and constructs `SmartGhost` when the module is available and `smart_learning` is enabled. It supports collecting human-click samples, positive/negative sample storage, augmentation, model training/scoring and moving-candidate tracking. The `--teach` option sets `smart_clicking` off and forces dry-run input behavior while the listener collects samples. The feature still depends on compatible versions of `main.py` and `smart_ghost.py`, a working global mouse hook (`pynput`), correct game capture, enough labeled examples and model readiness. If import fails, the main engine can log that smart learning is unavailable and fall back or disable that path according to its code; always confirm the startup capability log rather than infer activity from a filename alone.

Human clicks provide useful labels, but the crop can contain background/avatar content, and the click does not define the exact target box. Use sample review and negative examples. Avoid training on bot-generated clicks unless the event origin is explicitly distinguished.

## Click safety

The source configuration includes click-rate, per-frame and session limits, target/location cooldowns, shared spatial memory, absent-frame rearming, no-response quarantine, retry backoff and exclusion rectangles. Those mechanisms limit dangerous repetition but do not guarantee semantic correctness.

### Fail closed

If capture, coordinate mapping, foreground validation, input dependency, watcher state or a required safety check fails, skip the action and log the reason. Never loosen all safety checks just to get a click.

### Exclusion zones

An exclusion rectangle is `[x, y, width, height]` in the coordinate space used by the current source (documented as window-relative in the config). Coordinates cannot be blindly reused across monitor arrangements, display scale or window sizes. Protect navigation bars, chat, persistent icons and other unsafe regions.

### Repeat-click guard

A shared spatial guard is important because fast matching, template fallback and exploration may give the same object different names. The guard should be global across those routes. It can require a minimum cooldown plus multiple absence observations before rearming. It should suppress repeats of one persistent sprite while still allowing nearby, independently verified targets.

## Performance tuning

### Measure before optimizing

Use `fps`, tick duration, proposal time, fast-match time, exact-template time, candidate count and target count. Fix the dominant stage first. A shorter `loop_delay` cannot overcome a 200 ms matching operation.

### Common cost drivers

- `match_max_dimension`: larger frames retain detail but cost more CPU.
- `base_scales`: each scale adds matcher work.
- `fast_proposals_per_frame`: more candidates can improve recall but add verification cost.
- `proposal_peaks_per_scale`: more maxima cause more candidate work.
- `template_targets_per_frame`: higher library coverage per frame can increase tick latency.
- frequent watcher checks add matching cost.
- debug overlays add drawing and image-write I/O.
- excessive DEBUG output can become an I/O bottleneck.

### Starting profiles

| Profile | Working dimension | Proposals per frame | Exact templates per frame | Use |
|---|---:|---:|---:|---|
| Diagnose | 1024 | 8 | 1 | Find misses and false positives |
| Balanced | 800–1024 | 8 | 1 | General tuning baseline |
| Low CPU | 640–800 | 4–6 | 1 | Reduce machine load |
| Coverage-biased | 1024–1280 | 12–16 | 2–4 | Crowded scenes, benchmark carefully |
| Exact scan experiment | 800–1024 | 8 | 8 | Short diagnostic only |

These are starting points, not measured guarantees. Verify precision and recall at the real game resolution after any performance change.

## Configuration guide

The `Config` dataclass is the schema source for the inspected base engine. Unknown JSON keys are discarded by `load_config()`. Some fields are normalized or clamped at load time, meaning the value saved in JSON might not be the effective runtime value.

### Safe config editing

1. Stop the engine and back up `config.json`.
2. Use valid JSON with double-quoted keys and strings.
3. Keep boolean values unquoted.
4. Keep scale values numeric arrays.
5. Keep exclusion zones as `[x, y, width, height]` lists.
6. Change one setting per experiment.
7. Restart the engine unless the active build documents a hot-reload path.
8. Confirm the effective value in startup logs.
9. Preserve the old config so you can roll back.
10. Never put live webhook tokens into a public config file.

## Logs and diagnostics

Logs should let an operator distinguish: window not found; capture failed; no candidates; candidates found but no match; target matched but safety blocked it; dry-run would click; input driver called; input failed; watcher appeared; feedback was queued; evidence was confirmed or ambiguous; state saved.

`INPUT SENT` only proves that the input driver call returned. It does not prove that the game registered a catch. If `CAPTURE READY` is followed by zero FPS, investigate frame acquisition before changing detection thresholds.

### Logging practices

- Use INFO console level during normal operation.
- Keep DEBUG in rotating files while debugging.
- Rate-limit repeated candidate diagnostics.
- Disable overlay file writes outside diagnosis if they affect latency.
- Keep secrets out of logs.
- Submit only sanitized log excerpts.

## Repository importer

The optional importer downloads images from a public repository, tracks source hashes/manifests, routes watcher images, proposes target crops and records ambiguous scenes for review. Run it as a one-shot setup/update task, not inside the real-time frame loop.

Sync the current public collection:

```powershell
py main.py --root . --sync-repository Tenslaster/bloop
```

Force crop regeneration:

```powershell
py main.py --root . --sync-repository Tenslaster/bloop --force-reimport
```

Rebuild crops from cached assets without network:

```powershell
py main.py --root . --reimport-corpus --force-reimport
```

Interpret the report carefully: source images seen, downloaded files, unchanged files, watcher files, new crops, duplicate crops, pending scenes, and failures are separate counts. One repository image does not equal one valid click target.

## Optional smart-learning and reporting modules

### `smart_ghost.py`

The companion learner has a foreground-mask function, image features, augmentations, an MLP, motion proposals, tracks, a sample store and a higher-level `SmartGhost` component. Its intended training source is labeled positive/negative examples. Feature logic tries to reduce reliance on absolute hue so a sprite family can generalize across color variants. Augmentation is not a guarantee of recognizing every arbitrary pose.

### `sample_manager.py`

A review UI for positive, negative and quarantine samples. It helps inspect questionable labels and near-duplicates. A cleaner's score is not ground truth; preserve originals and make destructive operations reversible.

### `popup_dismiss.py`

A separate helper for matching a completion banner and performing its configured action sequence. Popup coordinates are not ghost coordinates. Validate the matched crop and the action sequence against current UI behavior before enabling it live.

### `webhook_reporter.py`

An optional companion that parses a reward toast such as an Ectoplaz gain, notifies listeners and sends user-configured HTTP reports in a background worker. OCR requires the external Tesseract binary. If the OCR observer is unhealthy, absence of an OCR event must not count as proof of no reward.

### Integration checklist

- [ ] Entry point imports the module.
- [ ] Runtime constructs and starts the module.
- [ ] Stop/shutdown calls are wired.
- [ ] Callbacks are thread-safe.
- [ ] Missing optional dependencies are handled clearly.
- [ ] Settings exist in the active config schema.
- [ ] The feature is tested in the exact build intended for distribution.
- [ ] README claims match the feature wiring.

## Customer executable packaging

A simplified customer GUI can launch a frozen engine. Developer tools should be hidden from customers, but important guarantees—such as read-only model use—must be enforced by the engine itself.

### Source and EXE are different artifacts

Editing `main.py` does not update an existing executable. Rebuild the EXE from the intended source after changes. Compare `--help` output and make sure client arguments exactly match the frozen engine parser.

A generic PyInstaller example is:

```powershell
py -m pip install pyinstaller
py -m PyInstaller --clean --noconfirm --onefile --windowed --name BLOOP-Client customer_app.py
```

Use the project's exact build script when available. Dynamic imports may need hidden-import options; models, config and image assets may need to be copied as external data. A build in Linux does not produce a verified Windows result.

### Customer EXE checklist

1. Build in a clean environment.
2. Stage into a fresh release directory.
3. Validate root-relative file paths.
4. Confirm `--engine` routing.
5. Confirm every launcher argument is supported by the parser.
6. Test Start/Stop/Pause/Resume.
7. Test F12/F9 in the actual packaged build.
8. Test popup blocking and rewards when wired.
9. Hash the model before/after to verify read-only inference.
10. Confirm Preview sends no real input.
11. Test on Windows without developer-only Python packages.
12. Review normal and forced-stop logs.

### Unknown `--process` error

If the binary reports `unrecognized arguments: --process highrise.exe`, the launcher and compiled engine came from inconsistent revisions. Rebuild the EXE from a source parser that supports the flag, or remove the argument if `config.json` already handles window selection. Changing a Python file beside an old EXE has no effect on the EXE itself.

## Tests and quality assurance

Use several layers of testing: pure helper tests, image fixtures, mocked Windows/input tests, GUI tests, and a real Windows smoke test. No single layer proves everything.

### Unit-test areas

- config defaults/clamps;
- scales and hashes;
- candidate clipping and overlap/NMS;
- local/global image difference;
- metadata serialization and reload;
- retry backoff/quarantine timing;
- spatial guard rearming;
- watcher cooldown and event deduplication;
- CLI argument behavior;
- filesystem error handling.

### Image fixture areas

- find a known target at its actual position;
- detect the target at several sizes;
- handle plausible hue/facing changes;
- reject an unrelated room screenshot;
- reject UI icons and watcher images as click targets;
- isolate one target from a full-room screenshot;
- detect multiple separated target instances;
- keep diagnostic overlays aligned after resizing.

### Mocked integration areas

- dry-run never calls the input driver;
- missing window blocks input;
- invalid client rectangle blocks input;
- foreground changes cancel stale actions;
- shared location guard suppresses repeat clicks across detection paths;
- GUI stop writes cooperative control and engine exits;
- GUI restore pauses the engine before user interaction;
- customer read-only mode never writes its model/samples.

### Real Windows smoke test

A Linux sandbox cannot prove the actual Highrise rendering path, Windows window handles, keyboard hooks or game-side click acceptance. After automated checks pass, test the real Windows build in Preview, inspect boxes, then test a very small live session while watching logs.

## Security and privacy

### Webhook credentials

A Discord webhook URL is a credential. Do not commit it in JSON, source, screenshots, README or issue reports. Use a private local setting/environment variable when supported. A live-looking webhook URL appeared in development configuration; if that URL was active, rotate/delete it in Discord and create a new one. Its value is intentionally omitted here.

### Model and user data

- Back up model and sample folders before training or cleanup.
- Check whether click-collected samples may include usernames/messages before enabling learning.
- Avoid uploading screenshots that expose private UI content.
- Keep customer telemetry local unless the user explicitly opts into reporting.
- Use HTTPS webhook endpoints and do not log the full URL.
- Treat downloaded images as untrusted inputs; validate size and decoder results.
- Use atomic writes for config and persistent metadata.
- Prefer safe NumPy model loading such as `allow_pickle=False` where compatible.
- Keep build outputs and temporary folders out of source control.

## Troubleshooting

Debug from the earliest failed stage instead of changing several thresholds at once:

1. Does the process start?
2. Is the intended Highrise window found?
3. Is a fresh, non-empty frame captured?
4. Are FPS/tick counters progressing?
5. Does proposal count become nonzero?
6. Does template verification accept a candidate?
7. Does the click guard permit it?
8. Does the input API return successfully?
9. Does a watcher or local disappearance provide feedback?
10. Does the expected state persist after restart?

Lowering a threshold cannot fix an empty screenshot. Changing the input driver cannot fix a proposal stage that returns zero candidates.

### First diagnostic report

Collect the Python version, OS and display scaling, project root, exact command/GUI mode, capture and threshold config, first 50 startup log lines, a 20–40 second performance excerpt, a sanitized overlay, and an explanation of whether Preview and Live agree. Report `TARGET DETECTED`, `INPUT ATTEMPT`, `INPUT SENT`, watcher and reward events separately. Never include webhook URLs or account credentials.

## Operational playbooks

### New PC setup

1. Extract to a permanent local directory.
2. Avoid running from a temporary transfer folder.
3. Install Python and dependencies.
4. Check the config and project root.
5. Verify Highrise window discovery.
6. Sync/import the image corpus if needed.
7. Confirm watcher routing for `ok.png`/`okay.jpg`.
8. Review full-scene items in `corpus/pending/`.
9. Run `--list-windows`.
10. Launch Preview.
11. Confirm current frames and aligned overlays.
12. Inspect false positives.
13. Enable Live only after the previous checks pass.
14. Test Stop & Save before leaving a long session unattended.

### A known ghost is missed

1. Save a preview frame and target crop.
2. Verify the target is in `seeds/` or `learned/`.
3. Check startup target count.
4. Compare target/native sprite dimensions.
5. Review the scale list.
6. Compare match score with target threshold.
7. Determine whether the proposal stage saw the ghost.
8. If there was no proposal, inspect candidate/color/shape logic.
9. If there was a proposal, inspect the verification score/mask.
10. Add a cropped reference only if the visual form is genuinely new.
11. Add a negative image of the confusing scene.
12. Adjust one parameter and rerun positive and negative fixtures.

### False positives click

1. Stop Live.
2. Preserve log and overlay.
3. Record target name and score.
4. Inspect the target's original file and dimensions.
5. Check whether a room screenshot is being used as a template.
6. Check target/watcher folder separation.
7. Inspect candidate size, aspect ratio and crop mask.
8. Check threshold and scales.
9. Add a negative fixture where appropriate.
10. Add an exclusion only for known UI, not as a substitute for classification.
11. Verify every click path uses the shared safety guard.
12. Resume only after negatives pass.

### No clicks are sent

1. Confirm frame capture works.
2. Confirm targets loaded.
3. Check candidate count.
4. Check target scores and threshold.
5. Check popup watcher state.
6. Check click rate/session caps.
7. Check global/per-target/location cooldowns.
8. Check quarantine status.
9. Check exclusion zones.
10. Check pause/control-file state.
11. Check input dependency errors.
12. Confirm Preview/Live mode is correct.
13. Distinguish input dispatch from game acceptance.

### FPS collapses

1. Read tick duration.
2. Compare capture/proposal/template/watcher timing.
3. Lower working resolution one step.
4. Keep exact-template budget low.
5. Use a realistic scale list.
6. Reduce proposal peaks if candidate count is excessive.
7. Disable debug overlays temporarily.
8. Reduce console DEBUG spam.
9. Compare unchanged-frame shortcut with full scans.
10. Benchmark OpenCV threads empirically.
11. Ensure network and OCR work are asynchronous.
12. Benchmark using the real target library size.
13. Compare both average and worst-case tick time.
14. Preserve target recall and false-positive checks.

## Developer workflow

Before editing code, identify the actual source revision used by the GUI/EXE, reproduce the failure, and locate the responsible layer. Preserve config compatibility. Make coordinate systems explicit. Keep optional dependencies optional when feasible. Avoid network/OCR inside the frame loop. Marshal Tk updates to the Tk main thread. Add a regression for the exact failure before changing thresholds.

### Pull-request checklist

- [ ] Code compiles and imports.
- [ ] New config fields have defaults and validation.
- [ ] CLI and README agree.
- [ ] GUI fields are saved/loaded correctly.
- [ ] Positive and negative image fixtures exist.
- [ ] Preview still sends no live input.
- [ ] Every click route uses shared safety.
- [ ] Coordinate transforms are tested.
- [ ] State migration is backward-compatible or documented.
- [ ] Logs contain useful reasons without secrets.
- [ ] Stop/close is bounded and recoverable.
- [ ] Dependencies/data are included in the build.
- [ ] Customer model read-only behavior is tested if promised.
- [ ] Final package is extracted and tested fresh.

## Release checklist

1. Freeze source commit.
2. Confirm all source files are in the repository.
3. Scan for secrets before commit.
4. Run syntax/compile checks.
5. Run pure unit tests.
6. Run image fixture tests.
7. Run mocked input/safety tests.
8. Run GUI launch and scrolling tests.
9. Run end-to-end dry run.
10. Test on real Windows.
11. Verify the CLI help matches this README.
12. Verify all documented configuration fields.
13. Build the executable from the frozen source.
14. Test the executable on a clean Windows setup.
15. Check external model/image paths.
16. Keep stale EXEs out of the release archive.
17. Record change summary and release hash.
18. Update this README when behavior changes.
19. Do not claim native Windows validation unless performed.

## Customer vs developer builds

- **Developer build:** includes source diagnostics, tuning, sample review and controlled experiments.
- **Customer build:** offers simple start/stop/pause controls and customer-specific webhook settings where supported.
- **Model artifact:** numeric weights used by a compatible learner; not the same as a seed image library.
- **Seed library:** known reference images used by template logic.
- **Watcher library:** popup/confirmation references, not ghost classes.
- **Read-only inference:** must be enforced in the engine, not only by hiding UI controls.

## File-by-file checklist

This checklist is for assembling a coherent working tree from the source modules described by this manual. The public repository listing observed during authoring showed image assets and a README, but not all runtime files. Check the actual branch before using this as a claim about repository contents.

### Required to run the integrated source engine

- [ ] `main.py` is the intended integrated source version and its `--help` output matches the commands in this README.
- [ ] `config.json` exists beside the engine or under the path selected by `--root`.
- [ ] `repository_import.py` is present when repository syncing or corpus reimport is required.
- [ ] `smart_ghost.py` is present when click-supervised learning is enabled.
- [ ] `popup_dismiss.py` is present when completion-popup dismissal is enabled.
- [ ] `webhook_reporter.py` is present when OCR/reward reporting is enabled.
- [ ] `VagueComplete.png` exists at the configured popup-template path if popup dismissal is enabled.
- [ ] `ok/` contains confirmation images, not target seeds.
- [ ] `seeds/` contains tight target crops when template bootstrap is enabled.
- [ ] `smart/` is writable during developer training and backed up before retraining.
- [ ] `learned/` is writable when the selected base engine persists learned target data.
- [ ] `logs/` is writable so diagnosis survives a GUI crash.
- [ ] `requirements.txt` accurately lists runtime dependencies, if that file is shipped.
- [ ] `requirements-build.txt` accurately lists build tooling, if the project distributes the build recipe.

### Required for the desktop GUI

- [ ] `gui.py` belongs to the same project version as `main.py`.
- [ ] `BLOOP.pyw` points at the intended GUI file and sets the project working directory predictably.
- [ ] `launch_gui.bat`, if present, visibly reports startup problems and does not swallow errors.
- [ ] A dependency-check path reports missing packages instead of merely closing the window.
- [ ] Worker-thread log messages are sent to Tk through a queue or equivalent thread-safe mechanism.
- [ ] The GUI uses the same config path as the child engine.
- [ ] Pause/stop commands use the correct control-file path.
- [ ] Closing the GUI cannot leave an unnoticed orphaned child process.
- [ ] Scrolling works at laptop resolutions and common Windows display scaling settings.
- [ ] F12/F9 meanings are shown accurately for the chosen dev/client build.

### Required for customer packaging

- [ ] The customer GUI does not show developer-only training controls unless deliberately intended.
- [ ] Read-only inference is enforced in engine logic, not only in the GUI.
- [ ] The shipped model and its version/feature metadata are included at the path the code loads.
- [ ] Webhook configuration is blank in the public/default distribution.
- [ ] Required popup/watch templates are copied into the release folder.
- [ ] Dynamic imports are included by the packaging recipe when needed.
- [ ] The exact CLI flags emitted by the GUI are accepted by the frozen binary.
- [ ] The frozen artifact has a build revision/hash available for support.
- [ ] A fresh Windows machine smoke test has been completed before claiming release readiness.
- [ ] The delivered artifact has been checked for secrets, temporary data and developer-specific absolute paths.

### Pre-publication checklist

- [ ] No credentials, webhook URLs, tokens or private logs are included.
- [ ] Public images are reviewed for private chat/identity/location information.
- [ ] Asset filenames and labels describe their roles accurately.
- [ ] Watcher images are documented and routed separately.
- [ ] Full-room screenshots are not automatically treated as tight target crops.
- [ ] Source licenses and redistribution rights are checked for every dependency and asset.
- [ ] README examples are compatible with the committed source revision.
- [ ] The source and executable are not described as interchangeable artifacts.
- [ ] The README's test claims state the actual environment and scope.
- [ ] The public repository contains everything a fresh clone is promised to run.

## Glossary

**Adaptive threshold** — A score threshold changed within configured bounds based on runtime evidence. It is not automatically a calibrated probability.

**Augmentation** — A transformation of a labeled training crop, such as a realistic hue, scale, brightness, flip or rotation variant.

**Candidate / proposal** — An image region produced by a cheap search stage that still needs verification.

**Client area** — The drawable portion of a Windows app window, excluding its title bar and border.

**Click dispatch** — A call to the input library requesting a mouse click. Dispatch is not the same as the game accepting the interaction.

**Click guard** — The final collection of rate limits, cooldowns, exclusion rectangles, window checks, pause checks and other rules that can reject an action.

**Confidence score** — A numeric value emitted by a detector. Its meaning depends on the score function and must not be called probability without calibration.

**Corpus** — The collection of source images downloaded or supplied for later crop/import/review.

**Dry run / Preview** — A mode that can capture and detect but must not send real click input.

**Exclusion zone** — A rectangular area where the engine is forbidden to click.

**False negative** — A real target that the system fails to detect or accept.

**False positive** — A non-target such as scenery, avatar accessory, popup or UI icon that the system incorrectly accepts as a ghost.

**Foreground window** — The window currently receiving keyboard focus or otherwise considered frontmost by the relevant Windows API.

**Frame** — A single captured image of the game client.

**Frame loop** — The recurring capture, image-processing, decision and optional action cycle.

**Hard negative** — A labeled non-target that looks similar to targets, for example a neon decoration with the same hue as a ghost.

**Held-out set** — Data reserved for evaluation and not used during training or threshold selection.

**HOG** — Histogram of Oriented Gradients, a feature descriptor that summarizes local edge orientations.

**IoU** — Intersection over Union, a measure of overlap between two rectangles or masks.

**Library** — The loaded collection of templates and metadata that the matcher can search.

**Mask** — A pixel map identifying a candidate foreground/silhouette region.

**Model artifact** — Serialized learned parameters, for example the compatible `smart/model.npz` file.

**NMS** — Non-Maximum Suppression, a method for discarding overlapping duplicate detections after ranking candidates.

**OCR** — Optical Character Recognition, used by an optional toast reader to interpret text in an image.

**Positive sample** — A training example labeled as containing a ghost.

**Negative sample** — A training example labeled as not containing a ghost.

**Quarantine** — A reversible holding area for samples or target templates excluded from active use pending review.

**Reward watcher** — A visual reference that signals a popup/confirmation/reward state. Watchers are not click targets.

**Seed** — An initial target image used to bootstrap template matching or, if supported, seed the smart learner.

**Session limit** — A maximum number of actions allowed during one bot process run.

**Smart-exclusive mode** — A policy that prefers or relies on the learned model instead of ordinary seed/exploration logic, subject to the implementation.

**Template matching** — A computer-vision operation comparing an image region against a reference at one or more scales.

**Teacher mode** — A mode in which the bot sends no autonomous input while the user's own clicks are observed as training labels, if the hook and smart learner are available.

**Track** — A candidate identity associated across multiple frames to estimate stability/motion and prevent duplicate actions.

**Watcher cooldown** — A period that prevents the same persistent visual banner from emitting the same event repeatedly.

**Webhook** — A secret endpoint URL that accepts HTTP messages. Treat it as a credential.

## FAQ

### Does the base engine use my NVIDIA GPU?

Not automatically. The inspected base implementation uses CPU OpenCV operations unless an explicit GPU path is installed and called.

### Is a score of 0.99 a 99% probability?

No. It is a similarity score. Probability calibration requires labeled positive/negative data and held-out evaluation.

### Why is a target detected but not clicked?

Cooldowns, budgets, exclusion zones, popup watchers, pause state, foreground checks or missing input dependencies may block it. Look at the log immediately after the detection event.

### Why does `--process` fail in an older EXE?

The binary may have been built from a parser that lacks the argument. Rebuild the executable or remove that flag from the launcher when config handles selection.

### Can all source screenshots be seeds?

No. A screenshot includes unrelated scene objects. Crop the ghost into its own target image.

### Are `ok.png` and `okay.jpg` click targets?

No. They are watcher references when routed to `ok/`.

### Can the project learn from human clicks?

Only if the current engine wires in the optional click-supervision module. A file sitting beside `main.py` does not guarantee that feature is running.

### Does any screen change prove a reward?

No. Unrelated animation creates false evidence. Use a healthy, associated watcher/OCR event when available.

### Why is preview mandatory?

It exposes capture/detection/coordinate mistakes without sending mouse input.

### Should I delete a repeatedly failing learned target?

Inspect its crop and negative matches first. Prefer reversible quarantine and backup before deletion.

### How do I reset learning safely?

Stop the engine, back up `learned/` and smart sample/model directories, then use the explicit reset/review workflow and verify the intended folders.

### Why does the UI freeze during import?

Image downloads and segmentation should run outside the real-time detector loop, preferably in a worker or one-shot setup command.

---

## Exhaustive configuration reference

This section is generated from the integrated `Config` dataclass in the latest supplied engine snapshot. The exact default expressions below are source-derived from that snapshot. Explanations describe expected tuning intent; local JSON may override defaults, so inspect the configuration distributed with your exact source/EXE build.

### 01. `window_title`

**Category:** Window discovery  
**Declared type:** `str` (`string`)  
**Dataclass default:** `''`

**Purpose**  
Title substring used when looking for the game window. Keep blank only when the selected release provides a separate, reliable window selector.

**Operational caution**  
A title that is too broad may match unrelated windows. A title that is too narrow may fail after a game update changes the caption.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `window_title` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `window_title` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `window_title` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `window_title` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `window_title`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 02. `window_process`

**Category:** Window discovery  
**Declared type:** `str` (`string`)  
**Dataclass default:** `'highrise.exe'`

**Purpose**  
Executable/process name used to select Highrise, rather than relying on a broad caption substring.

**Operational caution**  
Use the actual process executable name shown by Task Manager; wrong values can make the game invisible to discovery.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `window_process` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `window_process` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `window_process` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `window_process` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `window_process`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 03. `auto_focus_game`

**Category:** Window discovery  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `True`

**Purpose**  
Whether the runtime tries to foreground the selected game window.

**Operational caution**  
If another app needs focus, disable or pause the bot instead of fighting focus changes.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `auto_focus_game` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `auto_focus_game` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `auto_focus_game` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `auto_focus_game` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `auto_focus_game`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 04. `focus_retry_s`

**Category:** Window discovery  
**Declared type:** `float` (`number`)  
**Dataclass default:** `1.0`

**Purpose**  
Delay before another focus attempt.

**Operational caution**  
Very short retries can steal focus repeatedly; avoid tight loops.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `focus_retry_s` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `focus_retry_s` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `focus_retry_s` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `focus_retry_s` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `focus_retry_s`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 05. `window_refind_interval_s`

**Category:** Window discovery  
**Declared type:** `float` (`number`)  
**Dataclass default:** `3.0`

**Purpose**  
How often to re-enumerate/reacquire the selected window.

**Operational caution**  
Short intervals recover faster after window recreation but add repeated enumeration.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `window_refind_interval_s` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `window_refind_interval_s` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `window_refind_interval_s` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `window_refind_interval_s` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `window_refind_interval_s`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 06. `require_game_under_cursor`

**Category:** Input safety  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `True`

**Purpose**  
Requires the intended game window to be under the actual click point before dispatch.

**Operational caution**  
Keep enabled during normal operation; it deliberately blocks clicks covered by other windows.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `require_game_under_cursor` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `require_game_under_cursor` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `require_game_under_cursor` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `require_game_under_cursor` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `require_game_under_cursor`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 07. `repeat_click_radius_px`

**Category:** Input safety  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `28`

**Purpose**  
Screen-space radius used to treat a nearby action as a repeated location.

**Operational caution**  
Larger radius is safer for jitter but could suppress two distinct nearby ghosts.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `repeat_click_radius_px` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `repeat_click_radius_px` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `repeat_click_radius_px` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `repeat_click_radius_px` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `repeat_click_radius_px`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 08. `window_client_only`

**Category:** Capture geometry  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `True`

**Purpose**  
Restricts capture to the client area rather than including the title bar and borders.

**Operational caution**  
Changing this changes the coordinate origin and can invalidate click offsets; recheck the overlay after any change.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `window_client_only` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `window_client_only` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `window_client_only` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `window_client_only` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `window_client_only`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 09. `capture_method`

**Category:** Capture backend  
**Declared type:** `str` (`string`)  
**Dataclass default:** `'screen'`

**Purpose**  
Selects the implementation used to capture the target window or screen.

**Operational caution**  
A backend may be unsupported by a given Windows compositor/game mode; verify that fresh frames are produced.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `capture_method` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `capture_method` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `capture_method` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `capture_method` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `capture_method`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 10. `monitor_index`

**Category:** Capture geometry  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `1`

**Purpose**  
Selects the monitor used by backends that capture a monitor rather than a client rectangle.

**Operational caution**  
Monitor numbering is backend-dependent. Test the actual captured image rather than guessing the index.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `monitor_index` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `monitor_index` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `monitor_index` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `monitor_index` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `monitor_index`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 11. `webhook_url`

**Category:** Webhook reporting  
**Declared type:** `str` (`string`)  
**Dataclass default:** `''`

**Purpose**  
Discord webhook endpoint used by the reporting module when configured.

**Operational caution**  
Secret: never commit a live URL, never paste it into logs, and rotate it if exposed.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `webhook_url` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `webhook_url` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `webhook_url` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `webhook_url` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `webhook_url`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 12. `webhook_interval_s`

**Category:** Webhook reporting  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `300`

**Purpose**  
Reporter interval argument retained by the reporter interface.

**Operational caution**  
Check the reporter implementation for whether this value controls current behavior; the constructor may retain it for compatibility.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `webhook_interval_s` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `webhook_interval_s` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `webhook_interval_s` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `webhook_interval_s` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `webhook_interval_s`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 13. `console_log_level`

**Category:** Diagnostics  
**Declared type:** `str` (`string`)  
**Dataclass default:** `'INFO'`

**Purpose**  
Minimum severity printed to the console.

**Operational caution**  
DEBUG can be noisy; INFO is a useful normal-operation setting, while WARNING is useful for quiet unattended runs.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `console_log_level` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `console_log_level` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `console_log_level` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `console_log_level` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `console_log_level`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 14. `file_log_level`

**Category:** Diagnostics  
**Declared type:** `str` (`string`)  
**Dataclass default:** `'DEBUG'`

**Purpose**  
Minimum severity written to the rotating log file.

**Operational caution**  
Keeping DEBUG in the file while console stays at INFO usually preserves evidence without flooding the terminal.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `file_log_level` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `file_log_level` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `file_log_level` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `file_log_level` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `file_log_level`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 15. `log_console_enabled`

**Category:** Diagnostics  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `True`

**Purpose**  
Enables or disables console logging.

**Operational caution**  
Turn this off only if another log channel is confirmed; otherwise startup and capture failures may be harder to see.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `log_console_enabled` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `log_console_enabled` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `log_console_enabled` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `log_console_enabled` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `log_console_enabled`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 16. `log_file_enabled`

**Category:** Diagnostics  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `True`

**Purpose**  
Enables or disables persistent file logging.

**Operational caution**  
Disabling this removes the most useful forensic record for intermittent failures.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `log_file_enabled` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `log_file_enabled` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `log_file_enabled` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `log_file_enabled` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `log_file_enabled`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 17. `log_file_max_mb`

**Category:** Diagnostics  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `12`

**Purpose**  
Maximum approximate size for a log file before rotation.

**Operational caution**  
Too small loses history quickly; too large uses more disk. Rotated files are not an unlimited archive.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `log_file_max_mb` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `log_file_max_mb` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `log_file_max_mb` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `log_file_max_mb` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `log_file_max_mb`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 18. `base_threshold`

**Category:** Template matching  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.78`

**Purpose**  
Minimum similarity score used by the base template matcher. It is a score threshold, not a calibrated probability.

**Operational caution**  
Higher values reduce weak matches but can miss sprites with glow, scale changes or animation; lower values increase false positives.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `base_threshold` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `base_threshold` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `base_threshold` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `base_threshold` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `base_threshold`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 19. `base_scales`

**Category:** Template matching  
**Declared type:** `List[float]` (`sequence`)  
**Dataclass default:** `field(default_factory=lambda: [0.7, 0.95, 1.25])`

**Purpose**  
Scale multipliers tried for reference images.

**Operational caution**  
A larger scale list expands coverage and CPU cost. Include sizes representative of the real game UI, not every imaginable scale.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `base_scales` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `base_scales` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `base_scales` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `base_scales` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `base_scales`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 20. `grayscale`

**Category:** Template matching  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `True`

**Purpose**  
Controls grayscale preprocessing where applicable.

**Operational caution**  
Grayscale can be robust to color shifts but loses color discrimination between similarly shaped decorations.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `grayscale` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `grayscale` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `grayscale` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `grayscale` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `grayscale`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 21. `max_instances`

**Category:** Template matching  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `12`

**Purpose**  
Upper bound on detections returned for a matching operation.

**Operational caution**  
A larger limit allows more simultaneous ghosts but can increase duplicate proposals and input work.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `max_instances` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `max_instances` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `max_instances` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `max_instances` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `max_instances`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 22. `min_match_side_px`

**Category:** Template matching  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `12`

**Purpose**  
Minimum width/height for exact template matching candidates.

**Operational caution**  
Lower values cover tiny sprites but are susceptible to texture noise; raise only after inspecting missed-small-target diagnostics.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `min_match_side_px` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `min_match_side_px` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `min_match_side_px` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `min_match_side_px` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `min_match_side_px`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 23. `loop_delay`

**Category:** Timing  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.008`

**Purpose**  
Short delay used in the main loop when work is available.

**Operational caution**  
A tiny delay does not guarantee high FPS; capture and matching time dominate. Avoid zero-delay busy loops.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `loop_delay` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `loop_delay` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `loop_delay` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `loop_delay` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `loop_delay`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 24. `idle_delay`

**Category:** Timing  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.3`

**Purpose**  
Delay used while the loop has no immediate action.

**Operational caution**  
Lowering this increases polling while idle but cannot make slow matching operations faster.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `idle_delay` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `idle_delay` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `idle_delay` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `idle_delay` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `idle_delay`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 25. `multi_delay`

**Category:** Timing  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.05`

**Purpose**  
Delay between sequential actions when a frame has multiple candidates.

**Operational caution**  
Too short can produce dense input bursts; too long can allow moving targets to leave their positions.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `multi_delay` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `multi_delay` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `multi_delay` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `multi_delay` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `multi_delay`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 26. `learn_delay`

**Category:** Timing and learning  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.25`

**Purpose**  
Delay around learning/feedback operations.

**Operational caution**  
Do not reduce this simply to chase FPS unless feedback scheduling is verified nonblocking.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `learn_delay` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `learn_delay` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `learn_delay` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `learn_delay` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `learn_delay`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 27. `explore_after_idle_s`

**Category:** Exploration  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.75`

**Purpose**  
Idle interval before exploratory candidate search can run.

**Operational caution**  
Lower values trigger exploration sooner; if the detector is already finding known ghosts, premature exploration may add risky noise.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `explore_after_idle_s` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `explore_after_idle_s` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `explore_after_idle_s` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `explore_after_idle_s` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `explore_after_idle_s`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 28. `explore_cooldown_s`

**Category:** Exploration  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.12`

**Purpose**  
Minimum wait between exploration attempts.

**Operational caution**  
Short cooldowns can repeatedly probe the same uncertain scene before feedback arrives.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `explore_cooldown_s` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `explore_cooldown_s` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `explore_cooldown_s` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `explore_cooldown_s` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `explore_cooldown_s`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 29. `explore_blacklist_s`

**Category:** Exploration  
**Declared type:** `float` (`number`)  
**Dataclass default:** `90.0`

**Purpose**  
Time that a rejected exploration location remains blacklisted.

**Operational caution**  
Longer values reduce repeat false trials; shorter values are useful only when candidates genuinely move or scenes change quickly.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `explore_blacklist_s` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `explore_blacklist_s` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `explore_blacklist_s` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `explore_blacklist_s` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `explore_blacklist_s`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 30. `explore_grid`

**Category:** Exploration  
**Declared type:** `Tuple[int, int]` (`sequence`)  
**Dataclass default:** `(24, 18)`

**Purpose**  
Grid resolution used by parts of the candidate exploration logic.

**Operational caution**  
Finer grids offer more precise candidate cells but increase the number of checks and do not substitute for a good object detector.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `explore_grid` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `explore_grid` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `explore_grid` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `explore_grid` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `explore_grid`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 31. `min_local_change`

**Category:** Exploration and feedback  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.1`

**Purpose**  
Minimum normalized local pixel difference for a local-change event.

**Operational caution**  
Lower thresholds react to subtle effects but can mistake glow flicker and animation for a click response.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `min_local_change` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `min_local_change` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `min_local_change` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `min_local_change` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `min_local_change`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 32. `min_global_change`

**Category:** Exploration and feedback  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.15`

**Purpose**  
Minimum whole-frame difference used by global response checks.

**Operational caution**  
Global changes are weak evidence because avatars, particles and camera effects can change independently.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `min_global_change` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `min_global_change` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `min_global_change` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `min_global_change` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `min_global_change`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 33. `min_local_for_global`

**Category:** Exploration and feedback  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.04`

**Purpose**  
Minimum local signal required before a global-change result contributes.

**Operational caution**  
The local gate reduces false evidence from unrelated full-screen animation.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `min_local_for_global` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `min_local_for_global` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `min_local_for_global` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `min_local_for_global` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `min_local_for_global`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 34. `seed_similarity_hamming_max`

**Category:** Exploration  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `22`

**Purpose**  
Maximum perceptual-hash Hamming distance used by seed-family similarity checks.

**Operational caution**  
A larger distance admits more diverse forms but risks admitting unrelated scenery; evaluate with hard negatives.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `seed_similarity_hamming_max` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `seed_similarity_hamming_max` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `seed_similarity_hamming_max` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `seed_similarity_hamming_max` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `seed_similarity_hamming_max`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 35. `max_cps`

**Category:** Input safety  
**Declared type:** `float` (`number`)  
**Dataclass default:** `6.0`

**Purpose**  
Maximum clicks per second.

**Operational caution**  
This caps dispatch frequency; it cannot guarantee game-side registration or target correctness.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `max_cps` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `max_cps` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `max_cps` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `max_cps` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `max_cps`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 36. `max_session_clicks`

**Category:** Input safety  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `0`

**Purpose**  
Hard click count limit for one process session; zero may represent unlimited depending on the click guard implementation.

**Operational caution**  
Keep a finite limit while testing a new template/model. Verify the exact zero semantics in the installed source.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `max_session_clicks` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `max_session_clicks` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `max_session_clicks` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `max_session_clicks` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `max_session_clicks`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 37. `global_cooldown`

**Category:** Input safety  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.25`

**Purpose**  
Minimum delay between input events globally.

**Operational caution**  
This protects the client from click bursts even when different targets are detected.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `global_cooldown` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `global_cooldown` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `global_cooldown` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `global_cooldown` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `global_cooldown`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 38. `max_clicks_per_frame`

**Category:** Input safety  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `12`

**Purpose**  
Maximum click actions permitted from one frame.

**Operational caution**  
Lower values limit cascades from noisy frames; start conservatively.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `max_clicks_per_frame` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `max_clicks_per_frame` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `max_clicks_per_frame` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `max_clicks_per_frame` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `max_clicks_per_frame`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 39. `same_location_cooldown_s`

**Category:** Input safety  
**Declared type:** `float` (`number`)  
**Dataclass default:** `5.0`

**Purpose**  
Minimum cooldown for repeated clicks at the same approximate location.

**Operational caution**  
This is part of spatial suppression; movement may shift a sprite, so other identity checks are also needed.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `same_location_cooldown_s` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `same_location_cooldown_s` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `same_location_cooldown_s` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `same_location_cooldown_s` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `same_location_cooldown_s`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 40. `dedup_threshold`

**Category:** Library management  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.92`

**Purpose**  
Similarity threshold used to decide when two references are duplicates.

**Operational caution**  
More permissive deduplication saves CPU but can merge distinct ghost colors/shapes; inspect near-duplicate examples before changing.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `dedup_threshold` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `dedup_threshold` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `dedup_threshold` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `dedup_threshold` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `dedup_threshold`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 41. `auto_learn_roi`

**Category:** Learning scope  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `False`

**Purpose**  
Restricts or enables a configured learning region of interest.

**Operational caution**  
A region can reduce false discoveries but may miss ghosts that spawn elsewhere.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `auto_learn_roi` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `auto_learn_roi` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `auto_learn_roi` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `auto_learn_roi` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `auto_learn_roi`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 42. `save_interval_s`

**Category:** Persistence  
**Declared type:** `float` (`number`)  
**Dataclass default:** `15.0`

**Purpose**  
Periodic save cadence for the engine state/configuration where supported.

**Operational caution**  
Frequent saves reduce loss after a crash but increase disk I/O and may interact with external edits.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `save_interval_s` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `save_interval_s` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `save_interval_s` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `save_interval_s` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `save_interval_s`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 43. `match_max_dimension`

**Category:** Performance  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `1024`

**Purpose**  
Largest dimension used by the downscaled matching frame.

**Operational caution**  
Lower values reduce CPU time but remove small details; higher values preserve more evidence but cost more.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `match_max_dimension` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `match_max_dimension` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `match_max_dimension` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `match_max_dimension` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `match_max_dimension`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 44. `skip_unchanged_frames`

**Category:** Performance  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `False`

**Purpose**  
Skips some expensive work when the captured frame appears unchanged.

**Operational caution**  
Moving targets require a reliable change detector and periodic full checks to avoid starvation.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `skip_unchanged_frames` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `skip_unchanged_frames` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `skip_unchanged_frames` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `skip_unchanged_frames` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `skip_unchanged_frames`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 45. `scan_every_frame`

**Category:** Performance  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `True`

**Purpose**  
Runs the fast candidate proposal pass on every usable captured frame.

**Operational caution**  
Turning this off trades lower CPU for slower detection of short-lived moving sprites.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `scan_every_frame` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `scan_every_frame` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `scan_every_frame` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `scan_every_frame` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `scan_every_frame`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 46. `opencv_threads`

**Category:** Performance  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `4`

**Purpose**  
CPU worker-thread count for OpenCV operations.

**Operational caution**  
More threads can help or hurt based on resolution and contention; benchmark with the actual machine.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `opencv_threads` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `opencv_threads` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `opencv_threads` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `opencv_threads` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `opencv_threads`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 47. `proposal_peaks_per_scale`

**Category:** Performance and recall  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `2`

**Purpose**  
Number of local response peaks retained per template scale.

**Operational caution**  
More peaks can discover multiple instances but increase duplicate suppression and verification work.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `proposal_peaks_per_scale` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `proposal_peaks_per_scale` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `proposal_peaks_per_scale` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `proposal_peaks_per_scale` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `proposal_peaks_per_scale`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 48. `fast_proposals_per_frame`

**Category:** Performance and recall  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `8`

**Purpose**  
Candidate budget for the fast proposal matcher per frame.

**Operational caution**  
Increasing it may improve recall in busy scenes but can lower FPS and admit more weak candidates.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `fast_proposals_per_frame` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `fast_proposals_per_frame` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `fast_proposals_per_frame` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `fast_proposals_per_frame` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `fast_proposals_per_frame`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 49. `fast_min_candidate_side_px`

**Category:** Candidate geometry  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `24`

**Purpose**  
Minimum size for a fast-path candidate.

**Operational caution**  
Lower it carefully to catch tiny sprites; room particles and UI decorations may create many small components.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `fast_min_candidate_side_px` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `fast_min_candidate_side_px` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `fast_min_candidate_side_px` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `fast_min_candidate_side_px` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `fast_min_candidate_side_px`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 50. `template_targets_per_frame`

**Category:** Performance and recall  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `1`

**Purpose**  
Number of templates processed in the rotating exact-match budget per frame.

**Operational caution**  
Higher values improve library revisit latency at a predictable CPU cost; setting this to the full library may cause slow frames.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `template_targets_per_frame` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `template_targets_per_frame` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `template_targets_per_frame` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `template_targets_per_frame` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `template_targets_per_frame`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 51. `template_fallback_interval_frames`

**Category:** Legacy scheduling  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `60`

**Purpose**  
Compatibility setting retained for older configurations; the rotating budget may supersede it in current code.

**Operational caution**  
Verify active scheduling messages before tuning this legacy value.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `template_fallback_interval_frames` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `template_fallback_interval_frames` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `template_fallback_interval_frames` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `template_fallback_interval_frames` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `template_fallback_interval_frames`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 52. `watcher_interval_frames`

**Category:** Reward watchers  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `2`

**Purpose**  
How often popup/confirmation watcher matching runs relative to frame iteration.

**Operational caution**  
Frequent checks reduce response latency but consume CPU; too infrequent checks can miss brief banners.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `watcher_interval_frames` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `watcher_interval_frames` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `watcher_interval_frames` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `watcher_interval_frames` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `watcher_interval_frames`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 53. `debug_overlay`

**Category:** Diagnostics  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `False`

**Purpose**  
Writes or enables annotated frames that show candidate boxes and scores where supported.

**Operational caution**  
Use overlays to verify geometry; disable during normal operation if image writing adds load.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `debug_overlay` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `debug_overlay` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `debug_overlay` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `debug_overlay` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `debug_overlay`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 54. `debug_score_interval_s`

**Category:** Diagnostics  
**Declared type:** `float` (`number`)  
**Dataclass default:** `2.5`

**Purpose**  
Minimum interval between repetitive score diagnostics.

**Operational caution**  
A longer interval reduces log spam while retaining periodic evidence.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `debug_score_interval_s` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `debug_score_interval_s` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `debug_score_interval_s` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `debug_score_interval_s` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `debug_score_interval_s`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 55. `unchanged_rescan_interval_s`

**Category:** Performance  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.75`

**Purpose**  
Maximum wait between rescans when frames appear unchanged.

**Operational caution**  
A short interval protects against missed subtle motion; a long interval can delay a low-contrast target.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `unchanged_rescan_interval_s` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `unchanged_rescan_interval_s` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `unchanged_rescan_interval_s` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `unchanged_rescan_interval_s` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `unchanged_rescan_interval_s`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 56. `changed_pixel_delta`

**Category:** Frame change detection  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `12`

**Purpose**  
Per-pixel intensity delta treated as a changed pixel.

**Operational caution**  
Lower values react to tiny changes but are noisy in animated/glowing scenes.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `changed_pixel_delta` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `changed_pixel_delta` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `changed_pixel_delta` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `changed_pixel_delta` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `changed_pixel_delta`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 57. `changed_pixel_fraction`

**Category:** Frame change detection  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.00035`

**Purpose**  
Fraction of pixels that must change to classify a frame as changed.

**Operational caution**  
Use together with delta; either threshold alone can be misleading.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `changed_pixel_fraction` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `changed_pixel_fraction` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `changed_pixel_fraction` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `changed_pixel_fraction` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `changed_pixel_fraction`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 58. `patient_mode`

**Category:** Behavior mode  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `False`

**Purpose**  
Disables exploratory clicking and limits actions to known target logic.

**Operational caution**  
Patient mode is recommended when calibrating the library or investigating false positives.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `patient_mode` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `patient_mode` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `patient_mode` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `patient_mode` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `patient_mode`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 59. `reward_window_s`

**Category:** Reward feedback  
**Declared type:** `float` (`number`)  
**Dataclass default:** `2.5`

**Purpose**  
Window in which a reward watcher response can be associated with a click.

**Operational caution**  
Too short misses delayed rewards; too long can assign an unrelated later reward to an earlier click.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `reward_window_s` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `reward_window_s` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `reward_window_s` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `reward_window_s` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `reward_window_s`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 60. `watcher_cooldown_s`

**Category:** Reward watchers  
**Declared type:** `float` (`number`)  
**Dataclass default:** `2.5`

**Purpose**  
Cooldown used to prevent a persistent watcher image from firing repeatedly.

**Operational caution**  
Long enough cooldown prevents duplicate event handling; too long may suppress distinct consecutive events.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `watcher_cooldown_s` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `watcher_cooldown_s` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `watcher_cooldown_s` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `watcher_cooldown_s` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `watcher_cooldown_s`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 61. `watcher_threshold`

**Category:** Reward watchers  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.82`

**Purpose**  
Minimum watcher template similarity.

**Operational caution**  
Raise it for noisy background matches; lower only if the real banner is consistently missed and false positives remain controlled.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `watcher_threshold` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `watcher_threshold` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `watcher_threshold` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `watcher_threshold` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `watcher_threshold`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 62. `watcher_scales`

**Category:** Reward watchers  
**Declared type:** `List[float]` (`sequence`)  
**Dataclass default:** `field(default_factory=lambda: [0.75, 0.85, 0.95, 1.05, 1.15, 1.3])`

**Purpose**  
Scale multipliers tried for watcher images.

**Operational caution**  
Include expected UI scales while keeping the list compact.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `watcher_scales` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `watcher_scales` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `watcher_scales` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `watcher_scales` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `watcher_scales`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 63. `skip_click_while_popup`

**Category:** Input safety and overlays  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `True`

**Purpose**  
Blocks ordinary target clicking while the configured watcher/popup is detected.

**Operational caution**  
Keep enabled unless a verified workflow intentionally allows clicking behind overlays.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `skip_click_while_popup` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `skip_click_while_popup` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `skip_click_while_popup` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `skip_click_while_popup` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `skip_click_while_popup`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 64. `adaptive_threshold_min`

**Category:** Adaptive matching  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.65`

**Purpose**  
Lower bound for threshold adjustment.

**Operational caution**  
The floor prevents adaptation from making scores too permissive.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `adaptive_threshold_min` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `adaptive_threshold_min` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `adaptive_threshold_min` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `adaptive_threshold_min` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `adaptive_threshold_min`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 65. `adaptive_threshold_max`

**Category:** Adaptive matching  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.94`

**Purpose**  
Upper bound for threshold adjustment.

**Operational caution**  
The ceiling prevents adaptation from permanently rejecting every target.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `adaptive_threshold_max` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `adaptive_threshold_max` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `adaptive_threshold_max` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `adaptive_threshold_max` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `adaptive_threshold_max`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 66. `smart_learning`

**Category:** Smart-learning model  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `True`

**Purpose**  
Enables teacher-click sample collection and the smart learner when that module is available.

**Operational caution**  
Training labels can be noisy; start in teach/preview mode and review samples before relying on autonomous clicks.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_learning` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_learning` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_learning` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_learning` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_learning`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 67. `smart_clicking`

**Category:** Smart-learning model  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `True`

**Purpose**  
Allows the trained smart detector to participate in autonomous click decisions.

**Operational caution**  
Disable this to make learning/teaching-only sessions; only enable after representative training and negative evaluation.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_clicking` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_clicking` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_clicking` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_clicking` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_clicking`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 68. `smart_exclusive`

**Category:** Smart-learning model  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `True`

**Purpose**  
Prefers or requires the smart learner rather than ordinary seed matching, per implementation.

**Operational caution**  
If the model is not ready, exclusive mode may reduce detections; verify readiness logs before enabling.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_exclusive` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_exclusive` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_exclusive` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_exclusive` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_exclusive`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 69. `smart_use_seeds`

**Category:** Smart-learning model  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `True`

**Purpose**  
Allows seed templates to bootstrap or supplement the smart-learning pipeline.

**Operational caution**  
Seeds are helpful starting references but full-room screenshots must not be treated as tight target crops.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_use_seeds` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_use_seeds` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_use_seeds` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_use_seeds` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_use_seeds`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 70. `smart_threshold`

**Category:** Smart-learning model  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.8`

**Purpose**  
Minimum confidence score for smart detector acceptance.

**Operational caution**  
Treat as a score until calibration data establishes a probability interpretation.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_threshold` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_threshold` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_threshold` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_threshold` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_threshold`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 71. `smart_min_positives`

**Category:** Smart-learning model  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `12`

**Purpose**  
Minimum number of positive samples required before autonomous model use.

**Operational caution**  
Diversity matters as well as count; many duplicate crops are not a strong dataset.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_min_positives` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_min_positives` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_min_positives` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_min_positives` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_min_positives`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 72. `smart_confirm_frames`

**Category:** Smart-learning model  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `2`

**Purpose**  
Number of frame confirmations used before a candidate is treated as stable.

**Operational caution**  
More frames suppress one-frame noise but can miss fast or short-lived targets.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_confirm_frames` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_confirm_frames` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_confirm_frames` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_confirm_frames` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_confirm_frames`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 73. `smart_track_cooldown_s`

**Category:** Smart-learning tracking  
**Declared type:** `float` (`number`)  
**Dataclass default:** `1.5`

**Purpose**  
Per-track delay before it can be acted on again.

**Operational caution**  
A track cooldown should accompany object identity and disappearance logic.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_track_cooldown_s` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_track_cooldown_s` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_track_cooldown_s` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_track_cooldown_s` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_track_cooldown_s`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 74. `smart_lead_ms`

**Category:** Smart-learning tracking  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.0`

**Purpose**  
Motion lead time for predicted clicking, with special automatic behavior at zero where implemented.

**Operational caution**  
Start at zero; prediction can overshoot if velocity estimates are noisy.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_lead_ms` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_lead_ms` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_lead_ms` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_lead_ms` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_lead_ms`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 75. `smart_yield_to_user`

**Category:** Smart-learning control  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `True`

**Purpose**  
Makes automatic input yield when the user is actively interacting.

**Operational caution**  
Keep on for human-supervised sessions so manual clicks and bot clicks do not compete.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_yield_to_user` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_yield_to_user` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_yield_to_user` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_yield_to_user` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_yield_to_user`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 76. `smart_yield_s`

**Category:** Smart-learning control  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.8`

**Purpose**  
Duration for which the bot yields after user input.

**Operational caution**  
Longer yield improves manual control but reduces autonomous duty cycle.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_yield_s` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_yield_s` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_yield_s` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_yield_s` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_yield_s`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 77. `smart_penalize_static`

**Category:** Smart-learning model  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `True`

**Purpose**  
Enables a penalty/negative evidence for candidates that remain static under the learner’s criteria.

**Operational caution**  
A target may stay still while glowing; inspect the label rule before using staticness as a negative.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_penalize_static` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_penalize_static` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_penalize_static` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_penalize_static` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_penalize_static`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 78. `smart_feedback_delay_s`

**Category:** Smart-learning feedback  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.35`

**Purpose**  
Delay between action/candidate and visual response evaluation.

**Operational caution**  
Too short can observe animation before completion; too long can associate unrelated changes.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_feedback_delay_s` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_feedback_delay_s` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_feedback_delay_s` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_feedback_delay_s` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_feedback_delay_s`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 79. `smart_aug_pos`

**Category:** Smart-learning training  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `8`

**Purpose**  
Number/amount of positive augmentation operations configured for training.

**Operational caution**  
Augmentation should represent real hue, scale, orientation and brightness differences, not create impossible sprites.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_aug_pos` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_aug_pos` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_aug_pos` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_aug_pos` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_aug_pos`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 80. `smart_aug_neg`

**Category:** Smart-learning training  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `2`

**Purpose**  
Number/amount of negative augmentation operations configured for training.

**Operational caution**  
Negative examples should remain realistic and should not erase the distinction between target and background.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_aug_neg` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_aug_neg` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_aug_neg` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_aug_neg` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_aug_neg`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 81. `popup_dismiss`

**Category:** Popup handling  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `True`

**Purpose**  
Enables the optional completion-banner dismiss state machine when wired by the engine.

**Operational caution**  
Test with dry/mock actions first; popup handling is separate from ghost-click matching.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `popup_dismiss` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `popup_dismiss` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `popup_dismiss` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `popup_dismiss` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `popup_dismiss`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 82. `popup_dismiss_image`

**Category:** Popup handling  
**Declared type:** `str` (`string`)  
**Dataclass default:** `'VagueComplete.png'`

**Purpose**  
Path to the template image used to recognize the completion popup.

**Operational caution**  
The image must exist under the expected root and reflect the current UI language/theme.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `popup_dismiss_image` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `popup_dismiss_image` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `popup_dismiss_image` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `popup_dismiss_image` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `popup_dismiss_image`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 83. `popup_dismiss_threshold`

**Category:** Popup handling  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.8`

**Purpose**  
Similarity score required before the popup handler begins its sequence.

**Operational caution**  
Too low risks actions on unrelated scenes; too high may fail after UI scaling changes.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `popup_dismiss_threshold` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `popup_dismiss_threshold` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `popup_dismiss_threshold` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `popup_dismiss_threshold` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `popup_dismiss_threshold`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 84. `popup_dismiss_settle_s`

**Category:** Popup handling  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.9`

**Purpose**  
Delay intended to let the popup settle before an action.

**Operational caution**  
Too short can act during animation; too long delays dismissing a genuine blocker.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `popup_dismiss_settle_s` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `popup_dismiss_settle_s` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `popup_dismiss_settle_s` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `popup_dismiss_settle_s` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `popup_dismiss_settle_s`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 85. `smart_auto_clean`

**Category:** Smart-learning data quality  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `True`

**Purpose**  
Enables automated sample review/cleaning logic when present.

**Operational caution**  
Cleaning can mislabel hard examples; retain backups and review quarantine before deleting anything.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_auto_clean` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_auto_clean` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_auto_clean` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_auto_clean` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_auto_clean`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 86. `smart_ecto_confirm`

**Category:** Reward verification  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `True`

**Purpose**  
Enables Ectoplaz/reward-toast confirmation in the smart feedback path.

**Operational caution**  
This is useful only when OCR and the watcher are healthy; no OCR event is not proof of no reward.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_ecto_confirm` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_ecto_confirm` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_ecto_confirm` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_ecto_confirm` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_ecto_confirm`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 87. `smart_ecto_window_s`

**Category:** Reward verification  
**Declared type:** `float` (`number`)  
**Dataclass default:** `3.0`

**Purpose**  
Time window used to associate Ectoplaz confirmation with a recent action.

**Operational caution**  
Too long can associate unrelated rewards; too short misses delayed UI feedback.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_ecto_window_s` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_ecto_window_s` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_ecto_window_s` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_ecto_window_s` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_ecto_window_s`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 88. `smart_ecto_max_gain`

**Category:** Reward verification  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `500`

**Purpose**  
Plausibility ceiling for a parsed gain amount.

**Operational caution**  
Set high enough for legitimate game rewards but low enough to reject OCR garbage.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_ecto_max_gain` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_ecto_max_gain` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_ecto_max_gain` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_ecto_max_gain` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_ecto_max_gain`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 89. `smart_retry_misses`

**Category:** Smart-learning retry  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `True`

**Purpose**  
Enables retry behavior for eligible missed targets.

**Operational caution**  
Retry must still pass shared spatial, global-rate, foreground and popup guards.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_retry_misses` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_retry_misses` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_retry_misses` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_retry_misses` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_retry_misses`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 90. `smart_retry_max`

**Category:** Smart-learning retry  
**Declared type:** `int` (`integer`)  
**Dataclass default:** `2`

**Purpose**  
Maximum retry attempts or retry budget used by the smart engine.

**Operational caution**  
More retries can recover aim misses but can repeat clicks on false positives.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_retry_max` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_retry_max` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_retry_max` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_retry_max` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_retry_max`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 91. `smart_auto_threshold`

**Category:** Smart-learning model  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `True`

**Purpose**  
Allows the smart learner to adapt threshold based on its evidence.

**Operational caution**  
Keep floor/ceiling bounded and evaluate against fixed positive and negative frames.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_auto_threshold` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_auto_threshold` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_auto_threshold` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_auto_threshold` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_auto_threshold`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 92. `smart_threshold_floor`

**Category:** Smart-learning model  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.88`

**Purpose**  
Minimum threshold for smart-threshold adaptation.

**Operational caution**  
A floor limits how permissive automatic adjustment can become.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_threshold_floor` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_threshold_floor` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_threshold_floor` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_threshold_floor` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_threshold_floor`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 93. `smart_boss_min_frac`

**Category:** Smart-learning candidate geometry  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.14`

**Purpose**  
Minimum candidate size fraction for the special larger/boss-like target path.

**Operational caution**  
Confirm the meaning in current source and do not apply it to ordinary small ghosts without tests.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_boss_min_frac` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_boss_min_frac` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_boss_min_frac` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_boss_min_frac` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_boss_min_frac`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 94. `smart_boss_cooldown_s`

**Category:** Smart-learning candidate geometry  
**Declared type:** `float` (`number`)  
**Dataclass default:** `0.4`

**Purpose**  
Cooldown for the special larger/boss-like detection path.

**Operational caution**  
Longer cooldown limits repeated clicks on a persistent effect.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_boss_cooldown_s` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_boss_cooldown_s` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_boss_cooldown_s` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_boss_cooldown_s` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_boss_cooldown_s`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 95. `smart_probe`

**Category:** Smart-learning diagnostics  
**Declared type:** `bool` (`boolean`)  
**Dataclass default:** `False`

**Purpose**  
Enables a periodic probe/diagnostic path in compatible code.

**Operational caution**  
Probe actions can affect live state; keep disabled unless you know exactly what it does.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_probe` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_probe` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_probe` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_probe` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_probe`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 96. `smart_probe_interval_s`

**Category:** Smart-learning diagnostics  
**Declared type:** `float` (`number`)  
**Dataclass default:** `30.0`

**Purpose**  
Interval between smart probing operations.

**Operational caution**  
A smaller interval increases overhead and may interact with action cooldowns.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `smart_probe_interval_s` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `smart_probe_interval_s` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `smart_probe_interval_s` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `smart_probe_interval_s` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `smart_probe_interval_s`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 97. `hk_pause`

**Category:** Keyboard controls  
**Declared type:** `str` (`string`)  
**Dataclass default:** `'f9'`

**Purpose**  
Global hotkey that toggles pause.

**Operational caution**  
Avoid collisions with game controls and test whether the keyboard package can register global shortcuts.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `hk_pause` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `hk_pause` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `hk_pause` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `hk_pause` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `hk_pause`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 98. `hk_quit`

**Category:** Keyboard controls  
**Declared type:** `str` (`string`)  
**Dataclass default:** `'f12'`

**Purpose**  
Global hotkey that requests engine shutdown.

**Operational caution**  
Keep an emergency stop independent of the GUI; avoid assigning this to a common in-game key.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `hk_quit` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `hk_quit` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `hk_quit` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `hk_quit` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `hk_quit`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 99. `hk_zone`

**Category:** Keyboard controls  
**Declared type:** `str` (`string`)  
**Dataclass default:** `'f7'`

**Purpose**  
Global hotkey used for exclusion-zone interaction.

**Operational caution**  
Test region coordinates in preview and save a backup before editing zones.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `hk_zone` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `hk_zone` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `hk_zone` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `hk_zone` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `hk_zone`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 100. `hk_reload`

**Category:** Keyboard controls  
**Declared type:** `str` (`string`)  
**Dataclass default:** `'f10'`

**Purpose**  
Global hotkey that reloads the target/watcher library.

**Operational caution**  
Reload after changing image files; avoid writing the library while it is being scanned.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `hk_reload` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `hk_reload` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `hk_reload` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `hk_reload` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `hk_reload`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 101. `hk_bad`

**Category:** Keyboard controls  
**Declared type:** `str` (`string`)  
**Dataclass default:** `'f8'`

**Purpose**  
Global hotkey for marking the most recent bot action/sample as bad, where supported.

**Operational caution**  
Verify behavior in the exact engine build and ensure it does not collide with a game binding.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `hk_bad` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `hk_bad` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `hk_bad` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `hk_bad` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `hk_bad`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

### 102. `exclusion_zones`

**Category:** Input safety  
**Declared type:** `List[List[int]]` (`sequence`)  
**Dataclass default:** `field(default_factory=list)`

**Purpose**  
Window-relative rectangles [x, y, width, height] where clicking is prohibited.

**Operational caution**  
Use zones to protect menus and overlays; re-evaluate them after changing window size or DPI.

**Tuning procedure**
1. Stop the engine before editing the file unless the running version explicitly supports safe live reload for this setting.
2. Copy `config.json` to a timestamped backup.
3. Change only `exclusion_zones` for the first experiment.
4. Run Preview and capture enough evidence to compare the result with the previous setting.
5. Compare detection count, accepted matches, click blocks, FPS, tick time, and confirmation signals.
6. Keep the change only if the target precision and responsiveness both improve.

**How to interpret results**  
If changing `exclusion_zones` increases detections but the boxes land on decorations, it improved recall without preserving precision.
If `exclusion_zones` reduces CPU but delays moving-target discovery, it traded responsiveness for workload.
If the log no longer explains why an action was blocked, raise diagnostic verbosity temporarily instead of blindly loosening safety settings.

**Example change**  
Edit the JSON value while preserving its expected JSON type. Use `true`/`false` for booleans, numbers without quotes for numeric values, and arrays for scale lists or rectangles.

**Rollback**  
Restore the saved value for `exclusion_zones` if the new behavior is worse. Do not delete `learned/`, `smart/`, or imported image data as a first-line response to a tuning regression.

**Interaction with other fields**  
Many settings are coupled: thresholds interact with preprocessing, frame dimensions interact with minimum candidate size, and click speed interacts with cooldowns and response latency.
For `exclusion_zones`, change one variable at a time and record the old and new values in the experiment notes.

**Do not infer success from one event**  
A successful Python input call only means the input library accepted the event; it does not prove the game selected the ghost or granted a reward.

---

## Command-line argument reference

The options in this section are taken from the inspected `main.py` parser. Confirm with `python main.py --help` after updating source; a frozen executable can have a different argument list if it was built earlier.

### CLI option 01: `--window` / `-w`

**Source help:** Window title substring (only used when no process name is set)

**What to do with it**  
Use this option only for the purpose described by its parser help: Window title substring (only used when no process name is set)

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

### CLI option 02: `--process`

**Source help:** Executable to target, e.g. highrise.exe (default from config)

**What to do with it**  
Use this option only for the purpose described by its parser help: Executable to target, e.g. highrise.exe (default from config)

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

### CLI option 03: `--root`

**Source help:** Project root (holds seeds/, learned/)

**What to do with it**  
Use this option only for the purpose described by its parser help: Project root (holds seeds/, learned/)

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

### CLI option 04: `--debug`

**Source help:** No help text is supplied by the parser.

**What to do with it**  
Use this option only for the purpose described by its parser help: inspect the implementation before relying on it.

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

### CLI option 05: `--log-level`

**Source help:** Console and file verbosity

**What to do with it**  
Use this option only for the purpose described by its parser help: Console and file verbosity

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

### CLI option 06: `--dry-run`

**Source help:** Detect and log targets without sending input

**What to do with it**  
Use this option only for the purpose described by its parser help: Detect and log targets without sending input

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

### CLI option 07: `--explore`

**Source help:** Enable cautious exploration (enabled by default; useful to override patient_mode in config)

**What to do with it**  
Use this option only for the purpose described by its parser help: Enable cautious exploration (enabled by default; useful to override patient_mode in config)

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

### CLI option 08: `--patient`

**Source help:** Disable exploratory clicking; only click imported/learned templates

**What to do with it**  
Use this option only for the purpose described by its parser help: Disable exploratory clicking; only click imported/learned templates

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

### CLI option 09: `--no-explore`

**Source help:** Disable unseen-ghost exploration

**What to do with it**  
Use this option only for the purpose described by its parser help: Disable unseen-ghost exploration

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

### CLI option 10: `--teach`

**Source help:** Teach mode: the bot sends NO input; it only watches your clicks and learns what a ghost is

**What to do with it**  
Use this option only for the purpose described by its parser help: Teach mode: the bot sends NO input; it only watches your clicks and learns what a ghost is

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

### CLI option 11: `--no-smart`

**Source help:** Disable learn-from-my-clicks

**What to do with it**  
Use this option only for the purpose described by its parser help: Disable learn-from-my-clicks

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

### CLI option 12: `--scan-every-frame`

**Source help:** Run the fast color/shape candidate scan on every captured frame

**What to do with it**  
Use this option only for the purpose described by its parser help: Run the fast color/shape candidate scan on every captured frame

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

### CLI option 13: `--full-template-every-frame`

**Source help:** Raise exact template budget to 8 targets/frame (CPU-heavy, but still bounded)

**What to do with it**  
Use this option only for the purpose described by its parser help: Raise exact template budget to 8 targets/frame (CPU-heavy, but still bounded)

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

### CLI option 14: `--control-file`

**Source help:** Optional JSON file for GUI pause/stop controls

**What to do with it**  
Use this option only for the purpose described by its parser help: Optional JSON file for GUI pause/stop controls

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

### CLI option 15: `--reset-learned`

**Source help:** No help text is supplied by the parser.

**What to do with it**  
Use this option only for the purpose described by its parser help: inspect the implementation before relying on it.

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

### CLI option 16: `--max-cps`

**Source help:** No help text is supplied by the parser.

**What to do with it**  
Use this option only for the purpose described by its parser help: inspect the implementation before relying on it.

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

### CLI option 17: `--list-windows`

**Source help:** No help text is supplied by the parser.

**What to do with it**  
Use this option only for the purpose described by its parser help: inspect the implementation before relying on it.

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

### CLI option 18: `--sync-repository`

**Source help:** one-time download and import of all repository images (default: Tenslaster/bloop); no game window needed

**What to do with it**  
Use this option only for the purpose described by its parser help: one-time download and import of all repository images (default: Tenslaster/bloop); no game window needed

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

### CLI option 19: `--force-reimport`

**Source help:** re-run image cropping for cached repository images; use with --sync-repository or --reimport-corpus

**What to do with it**  
Use this option only for the purpose described by its parser help: re-run image cropping for cached repository images; use with --sync-repository or --reimport-corpus

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

### CLI option 20: `--reimport-corpus`

**Source help:** rebuild target crops from corpus/repository without using the network

**What to do with it**  
Use this option only for the purpose described by its parser help: rebuild target crops from corpus/repository without using the network

**Before using it**
1. Confirm the option appears in the output of `python main.py --help`.
2. Run it first with `--dry-run` if it could alter runtime behavior.
3. Keep project-relative paths rooted at the folder containing the intended config and image libraries.
4. Preserve the complete console output if the command exits nonzero.

**Common failure**  
A command rejected as an unrecognized argument usually means that the command and executable came from different source versions. Rebuild the executable or remove the unsupported flag; do not assume a `.py` edit changes an already-built `.exe`.

---

## Source symbol index

The symbol index below is built from the local source files made available for documentation. A listed companion module is not automatically active at runtime: confirm imports/instantiation in the `main.py` version you actually launch. Private symbols are included because they are useful when debugging source, but should not be treated as stable public API.

### `main.py`

Source file: `main(9).py`.

**`enable_dpi_awareness`** — lines 91–100; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`setup_logging`** — lines 103–140; kind: `FunctionDef`.

Configure separate console/file verbosity; DEBUG can be kept in file only.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Config`** — lines 147–303; kind: `ClassDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`load_config`** — lines 306–368; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`save_config`** — lines 371–380; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`exe_name`** — lines 406–409; kind: `FunctionDef`.

'C:\Games\Highrise.EXE' -> 'highrise.exe'.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_pid_of_window`** — lines 412–415; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_process_basename`** — lines 418–430; kind: `FunctionDef`.

Lower-case executable name of a process id ('' if it cannot be read).

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_enum_top_windows`** — lines 433–458; kind: `FunctionDef`.

All visible top-level windows with owner pid and executable name.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_window_at_point`** — lines 461–467; kind: `FunctionDef`.

(top-level hwnd, pid) of whatever window is visible at screen point x,y.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WindowCapture`** — lines 470–655; kind: `ClassDef`.

Finds and tracks the game window.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WindowCapture.__init__`** — lines 478–484; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WindowCapture.targeting`** — lines 487–488; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WindowCapture.label`** — lines 491–492; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WindowCapture.find`** — lines 494–533; kind: `FunctionDef`.

Pick the best visible window of the target (un-minimized, then largest).

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WindowCapture.is_alive`** — lines 535–543; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WindowCapture.is_minimized`** — lines 545–549; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WindowCapture._foreground_is_game`** — lines 551–561; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WindowCapture.is_foreground`** — lines 563–576; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WindowCapture.owns_point`** — lines 578–584; kind: `FunctionDef`.

True when a window of the game is what is visible at screen point x,y.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WindowCapture.visible_fraction`** — lines 586–595; kind: `FunctionDef`.

Share of a 3x3 grid of sample points inside rect that show the game.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WindowCapture.usable_for_screen_capture`** — lines 597–604; kind: `FunctionDef`.

Screen capture reads desktop pixels; accept it only when the game is what is shown.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WindowCapture.get_rect`** — lines 606–627; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WindowCapture.focus`** — lines 629–655; kind: `FunctionDef`.

Restore (if minimized) and raise the game window. Cheap when already in front.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`capture_region_screen`** — lines 661–664; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`capture_window_printwindow`** — lines 667–683; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_prep`** — lines 689–690; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_resize`** — lines 693–698; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`prepare_match_frame`** — lines 701–732; kind: `FunctionDef`.

Prepare frame features once and share them across all target templates.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_dominant_hue_mask`** — lines 735–750; kind: `FunctionDef`.

Pixels belonging to the dominant saturated foreground color family.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_masked_similarity`** — lines 753–841; kind: `FunctionDef`.

Verify a sprite using foreground texture, color family, and silhouette.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_cached_masked_template_features`** — lines 853–890; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`clear_template_feature_cache`** — lines 893–897; kind: `FunctionDef`.

Clear transformed template cache (also useful for deterministic tests).

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`find_all_matches`** — lines 900–1133; kind: `FunctionDef`.

Return scored, non-overlapping template detections.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`region_diff`** — lines 1136–1149; kind: `FunctionDef`.

Local pixel change around (cx, cy), normalized to [0,1].

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`global_diff`** — lines 1152–1157; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`extract_foreground_mask`** — lines 1160–1201; kind: `FunctionDef`.

Estimate an object silhouette for a tightly-cropped exploration proposal.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`quick_hue_mask`** — lines 1204–1273; kind: `FunctionDef`.

Fast HSV/connected-component mask for real-time candidate verification.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_mask_contour`** — lines 1276–1284; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`dhash`** — lines 1287–1294; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`hamming`** — lines 1297–1298; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`dominant_hue_value`** — lines 1301–1318; kind: `FunctionDef`.

Return the dominant saturated hue (OpenCV 0..179), ignoring transparent/background pixels.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`hue_distance`** — lines 1321–1325; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SaliencyDetector`** — lines 1331–1426; kind: `ClassDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SaliencyDetector.__init__`** — lines 1332–1338; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SaliencyDetector.candidates`** — lines 1340–1426; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Target`** — lines 1433–1591; kind: `ClassDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Target.load`** — lines 1473–1572; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Target.serialize`** — lines 1574–1591; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Watcher`** — lines 1595–1634; kind: `ClassDef`.

A visual confirmation image from ./ok. Watchers are never clicked.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Watcher.load`** — lines 1613–1634; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`adaptive_scales`** — lines 1637–1662; kind: `FunctionDef`.

A compact scale pyramid tuned for sprites rather than general photographs.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Library`** — lines 1665–1796; kind: `ClassDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Library.__init__`** — lines 1666–1679; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Library.load`** — lines 1682–1739; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Library.save`** — lines 1742–1753; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Library.add_learned`** — lines 1756–1784; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Library.seed_profile`** — lines 1787–1796; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Safety`** — lines 1802–1829; kind: `ClassDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Safety.__init__`** — lines 1803–1807; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Safety.add_exclusion`** — lines 1809–1811; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Safety.in_exclusion`** — lines 1813–1817; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Safety.can_click`** — lines 1819–1825; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Safety.note_click`** — lines 1827–1829; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot`** — lines 1835–3671; kind: `ClassDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot.__init__`** — lines 1836–1952; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._load_watchers`** — lines 1955–1978; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._check_watchers`** — lines 1980–2031; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._calibrate_threshold`** — lines 2033–2055; kind: `FunctionDef`.

Tune only when reward-confirmed and unconfirmed scores are available.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._calibrate_response_threshold`** — lines 2057–2083; kind: `FunctionDef`.

Raise a target's threshold only when persistent click-response evidence separates.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._apply_rewards`** — lines 2086–2111; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._sweep_unconfirmed`** — lines 2113–2130; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot.stop`** — lines 2133–2133; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot.toggle_pause`** — lines 2134–2136; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot.request_reload`** — lines 2137–2137; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot.request_zone`** — lines 2138–2138; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._auto_focus`** — lines 2141–2149; kind: `FunctionDef`.

Bring Highrise back by itself (rate-limited) instead of stalling until a human does.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._capture`** — lines 2151–2198; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot.run`** — lines 2201–2291; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._persist`** — lines 2293–2312; kind: `FunctionDef`.

Save learned targets; rewrite config.json only if the bot itself changed it

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._tick`** — lines 2314–2469; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._emit_performance`** — lines 2471–2486; kind: `FunctionDef`.

Rate-limited runtime telemetry consumed by both logs and the GUI.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._local_masked_template_score`** — lines 2488–2532; kind: `FunctionDef`.

Check a few sizes around a proposed box with an alpha/foreground mask.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._match_fast_candidates`** — lines 2534–2770; kind: `FunctionDef`.

Match the current frame's compact proposals against target shape + hue.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._candidate_boxes`** — lines 2772–2802; kind: `FunctionDef`.

Fast per-frame proposal pass: known color families + unseen neon forms.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._color_component_candidates`** — lines 2804–2913; kind: `FunctionDef`.

Segment compact neon components by learned and quantized HSV hue.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._poll_control_file`** — lines 2915–2934; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._process_pending_discoveries`** — lines 2936–2968; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._update_pending_feedback`** — lines 2970–3000; kind: `FunctionDef`.

Persist weak screen-change evidence without pretending it proves a reward.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._match_and_click`** — lines 3003–3165; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._write_debug_overlay`** — lines 3167–3204; kind: `FunctionDef`.

Write a rate-limited annotated frame useful for diagnosing missed clicks.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._maybe_tune`** — lines 3206–3225; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._looks_like_unseen_ghost_form`** — lines 3228–3306; kind: `FunctionDef`.

Conservative fallback for a genuinely new color/shape not in the seed bank.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._candidate_matches_seed_family`** — lines 3308–3366; kind: `FunctionDef`.

Return a foreground mask only when the candidate resembles a seed silhouette.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._explore_once`** — lines 3368–3448; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._smart_feed`** — lines 3452–3460; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._smart_click`** — lines 3462–3491; kind: `FunctionDef`.

Click the best learned ghost. Returns True when a ghost was identified.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._do_click`** — lines 3493–3547; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._script_click`** — lines 3549–3623; kind: `FunctionDef`.

Scripted input used to dismiss popups. Never recorded by the smart learner,

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._draw_zone`** — lines 3626–3662; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`AutonomousBot._do_reload`** — lines 3665–3671; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`list_windows`** — lines 3677–3686; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`main`** — lines 3689–3844; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

### `gui.py`

Source file: `gui(1).py`.

**`VisionGUI`** — lines 57–1601; kind: `ClassDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI.__init__`** — lines 58–110; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._load_config`** — lines 113–145; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._ui`** — lines 147–149; kind: `FunctionDef`.

Thread-safe: run fn() on the Tk thread (worker threads must never touch widgets).

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._pump_ui`** — lines 151–161; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._mark_dirty`** — lines 163–166; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._set_dirty`** — lines 168–172; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._build_style`** — lines 175–229; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._build_ui`** — lines 232–257; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._build_sidebar`** — lines 259–291; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._nav_hover`** — lines 293–297; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._build_topbar`** — lines 299–320; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._card`** — lines 323–334; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._tile`** — lines 336–341; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._make_page`** — lines 343–387; kind: `FunctionDef`.

Create a page frame inside page_host (not shown until selected).

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._group`** — lines 389–399; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._register`** — lines 401–402; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._field`** — lines 404–418; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._check`** — lines 420–426; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._selected_scroll_entry`** — lines 429–431; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._pointer_is_over`** — lines 433–440; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._on_mousewheel`** — lines 442–459; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._on_scroll_key`** — lines 461–479; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._show_page`** — lines 482–500; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._bind_shortcuts`** — lines 502–505; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._build_search_popup`** — lines 507–519; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._page_title_of`** — lines 521–522; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._on_search_change`** — lines 524–548; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._search_move`** — lines 550–559; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._search_pick`** — lines 561–568; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._search_click`** — lines 570–576; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._search_close`** — lines 578–582; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._jump_to`** — lines 584–597; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._flash`** — lines 599–607; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._build_dashboard`** — lines 610–668; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._build_runtime_page`** — lines 671–697; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._build_detection_page`** — lines 699–718; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._build_learning_page`** — lines 720–757; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._build_logs_page`** — lines 759–781; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._build_samples_page`** — lines 784–828; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._count_pngs`** — lines 831–835; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._refresh_samples`** — lines 837–842; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._dedupe`** — lines 844–868; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._dedupe_finish`** — lines 870–876; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._dedupe_scanned`** — lines 878–899; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._build_webhook_page`** — lines 902–938; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._toggle_webhook_secret`** — lines 940–941; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._update_webhook_state`** — lines 943–950; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._test_webhook`** — lines 952–968; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._webhook_test_done`** — lines 970–972; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._reset_ecto`** — lines 975–982; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._on_ecto_gain`** — lines 984–992; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._update_ecto_rate`** — lines 994–997; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._apply_log_filter`** — lines 1000–1008; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._copy_console`** — lines 1010–1013; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._save_console`** — lines 1015–1022; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._set_status_hint`** — lines 1024–1025; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._parsed_config`** — lines 1027–1071; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._save_settings`** — lines 1073–1100; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._open_sample_manager`** — lines 1102–1115; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._smart_request`** — lines 1117–1143; kind: `FunctionDef`.

Ask the smart detector to retrain ('retrain') or clean + retrain ('clean').

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._python_executable`** — lines 1145–1153; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._command_base`** — lines 1155–1156; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._list_windows`** — lines 1158–1170; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._safe_targeting`** — lines 1172–1175; kind: `FunctionDef`.

True when the bot targets highrise.exe by process: it cannot see or click this panel,

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._on_gui_restored`** — lines 1177–1193; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._start_bot`** — lines 1195–1244; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._minimize_for_live`** — lines 1246–1259; kind: `FunctionDef`.

Hide the controller, then resume the new live process after it is hidden.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._finish_minimize_and_resume`** — lines 1261–1276; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._hide_then_resume_live`** — lines 1278–1289; kind: `FunctionDef`.

Resume is a two-phase action: hide first, clear pause second.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._finish_manual_resume`** — lines 1291–1302; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._sync_repo`** — lines 1304–1312; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._reimport_corpus`** — lines 1314–1320; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._launch`** — lines 1322–1353; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._reader`** — lines 1355–1363; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._write_control`** — lines 1365–1369; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._toggle_pause`** — lines 1371–1390; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._stop_process`** — lines 1392–1436; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._drain_queue`** — lines 1438–1460; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._maybe_restart`** — lines 1462–1486; kind: `FunctionDef`.

Crash watchdog: if the bot dies without the user asking, start it again.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._tag_for`** — lines 1489–1495; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._interpret_line`** — lines 1497–1525; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._refresh_metrics`** — lines 1527–1542; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._append_log`** — lines 1544–1553; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._clear_console`** — lines 1555–1559; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._set_status`** — lines 1561–1563; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._open_path`** — lines 1565–1579; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._on_close`** — lines 1581–1594; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`VisionGUI._poll_close`** — lines 1596–1601; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_record_gui_startup_failure`** — lines 1604–1614; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`main`** — lines 1617–1642; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

### `smart_ghost.py`

Source file: `smart_ghost.py`.

**`_iou`** — lines 64–69; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_nms`** — lines 72–80; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_clip_box`** — lines 83–89; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`fast_mask`** — lines 92–136; kind: `FunctionDef`.

Cheap, deterministic foreground mask used for BOTH training and inference.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`features`** — lines 139–214; kind: `FunctionDef`.

Hue-invariant feature vector for one candidate crop.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`augment`** — lines 220–245; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`MLP`** — lines 251–363; kind: `ClassDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`MLP.__init__`** — lines 252–257; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`MLP.trained`** — lines 260–261; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`MLP.predict`** — lines 263–269; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`MLP.fit`** — lines 271–346; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`MLP.save`** — lines 348–352; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`MLP.load`** — lines 354–363; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`MotionProposer`** — lines 369–428; kind: `ClassDef`.

Moving-object proposals from a slowly adapting background model.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`MotionProposer.__init__`** — lines 377–382; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`MotionProposer.reset`** — lines 384–386; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`MotionProposer.propose`** — lines 388–428; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Track`** — lines 435–459; kind: `ClassDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Track.center`** — lines 454–455; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Track.speed`** — lines 458–459; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Tracker`** — lines 462–504; kind: `ClassDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Tracker.__init__`** — lines 463–465; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Tracker.update`** — lines 467–504; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleStore`** — lines 510–611; kind: `ClassDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleStore.__init__`** — lines 511–521; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleStore._scan`** — lines 523–533; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleStore.add`** — lines 535–553; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleStore.snapshot`** — lines 555–557; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleStore.quar_dir`** — lines 561–562; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleStore.rescan`** — lines 564–567; kind: `FunctionDef`.

Re-read the folders (files may have been moved/deleted by the GUI).

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleStore.tag_of`** — lines 570–572; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleStore.quarantine`** — lines 574–588; kind: `FunctionDef`.

Move a sample out of the training set, reversibly.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleStore.restore`** — lines 590–599; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleStore.flip`** — lines 601–611; kind: `FunctionDef`.

Move a sample to the opposite class (it was labelled the wrong way round).

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_read_bgr`** — lines 614–620; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`Pick`** — lines 627–635; kind: `ClassDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_Pending`** — lines 639–655; kind: `ClassDef`.

One bot click waiting for its verdict (visual check at `due`, ecto check until deadline).

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost`** — lines 658–1616; kind: `ClassDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.__init__`** — lines 659–713; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.start_listener`** — lines 716–732; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.stop`** — lines 734–740; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.note_bot_click`** — lines 743–746; kind: `FunctionDef`.

Called right BEFORE the bot sends a click so the listener can ignore it.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.on_user_click`** — lines 748–754; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.mark_bad`** — lines 756–767; kind: `FunctionDef`.

Hotkey: the bot's most recent smart click was wrong -> teach a negative.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.on_frame`** — lines 770–803; kind: `FunctionDef`.

Feed every captured frame. Cheap: bookkeeping + proposals + tracking.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._frame_before`** — lines 806–813; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._segment_click`** — lines 815–856; kind: `FunctionDef`.

Return (box, quality) of the object under the click.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._process_clicks`** — lines 858–905; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._excluded`** — lines 907–911; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._track_at`** — lines 913–922; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._crop`** — lines 925–933; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._recently_clicked_near`** — lines 936–940; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._mine_negatives`** — lines 942–976; kind: `FunctionDef`.

Things that never move or react are not ghosts: free negative labels.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.ready`** — lines 979–981; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._score_tracks`** — lines 983–1000; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.pick_target`** — lines 1002–1049; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.threshold`** — lines 1051–1056; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._probe_candidate`** — lines 1058–1077; kind: `FunctionDef`.

Active learning: occasionally click a moving, near-threshold candidate and let the ecto

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.note_smart_click`** — lines 1079–1094; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.is_boss`** — lines 1097–1100; kind: `FunctionDef`.

Big targets (bosses) take many clicks and stay on screen until the last one.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.in_wave`** — lines 1103–1104; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._note_click_rate`** — lines 1106–1117; kind: `FunctionDef`.

Many bot clicks with no per-click toast = a wave or boss: the reward only comes at the end.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.ecto_window`** — lines 1120–1125; kind: `FunctionDef`.

How long after a click a gain may still be credited to it (learned from real latencies).

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.on_ecto_gain`** — lines 1127–1132; kind: `FunctionDef`.

Webhook thread -> queue; credited to a click on the next frame (keeps all state single-threaded).

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._process_ecto`** — lines 1134–1187; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._log_gain`** — lines 1189–1197; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.hit_rate`** — lines 1199–1200; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._adapt_threshold`** — lines 1202–1209; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.stats_line`** — lines 1211–1217; kind: `FunctionDef`.

One line for the Discord post.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._visual_verdict`** — lines 1220–1235; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._process_pending`** — lines 1237–1265; kind: `FunctionDef`.

Visual verdict at `due`; final label once the ecto window has closed (or a gain confirmed it).

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._retry_after`** — lines 1267–1270; kind: `FunctionDef`.

Seconds after a click before 'still alive, no gain' counts as an aim miss (toast latency + margin).

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._maybe_retry`** — lines 1272–1283; kind: `FunctionDef`.

Ghost still alive and moving after our click = aim miss: free the track for a quick re-click.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._finalize`** — lines 1285–1321; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.seed_from_images`** — lines 1324–1336; kind: `FunctionDef`.

Optional bootstrap from existing seed crops so the first session is not empty.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._maybe_train`** — lines 1338–1353; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.train_now`** — lines 1355–1357; kind: `FunctionDef`.

Synchronous training (also used by the test-suite).

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._train_worker`** — lines 1359–1376; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._sample_feats`** — lines 1378–1397; kind: `FunctionDef`.

Features of the original crop + n_aug augmented copies (cached; deterministic per file).

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._train_h`** — lines 1399–1400; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._build_dataset`** — lines 1402–1420; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._train`** — lines 1422–1442; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._clean_pass`** — lines 1452–1532; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.auto_clean`** — lines 1534–1549; kind: `FunctionDef`.

Iterative cleaning: removing the clearest mislabels makes the next pass sharper.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._write_status`** — lines 1552–1561; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._poll_commands`** — lines 1563–1581; kind: `FunctionDef`.

The GUI drops smart/command.json ({"action": "retrain" | "clean"}); run it in the background.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost._command_worker`** — lines 1583–1599; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.status`** — lines 1602–1608; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SmartGhost.debug_boxes`** — lines 1610–1616; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

### `repository_import.py`

Source file: `repository_import.py`.

**`ImportSummary`** — lines 39–52; kind: `ClassDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`ImportSummary.to_dict`** — lines 51–52; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_sha256`** — lines 55–56; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_safe_repo`** — lines 59–66; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_request_bytes`** — lines 69–85; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_request_json`** — lines 88–112; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_is_watcher`** — lines 115–117; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_atomic_write`** — lines 120–127; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_manifest_load`** — lines 130–135; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_image_paths_in_tree`** — lines 138–159; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`sync_repository_images`** — lines 162–273; kind: `FunctionDef`.

Download all image files from a public GitHub repository into the project.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_grabcut_mask`** — lines 276–320; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_bbox`** — lines 323–327; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_object_rgba`** — lines 330–347; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_valid_primary_crop`** — lines 350–381; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_core_boxes`** — lines 384–427; kind: `FunctionDef`.

Find plausible bright/colorful object cores in a full gameplay screenshot.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_crop_around_core`** — lines 430–449; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_read_bgr`** — lines 452–460; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_signature`** — lines 463–484; kind: `FunctionDef`.

Small perceptual signature retaining silhouette and color differences.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_load_signature_index`** — lines 487–500; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_duplicate_target`** — lines 503–514; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_save_pending`** — lines 517–525; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`build_target_templates`** — lines 528–669; kind: `FunctionDef`.

Extract/normalize target crops from the locally cached repository images.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`sync_and_import_repository`** — lines 672–677; kind: `FunctionDef`.

One entry point used by the command-line option; returns both summaries.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

### `popup_dismiss.py`

Source file: `popup_dismiss.py`.

**`PopupDismisser`** — lines 23–217; kind: `ClassDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`PopupDismisser.__init__`** — lines 24–69; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`PopupDismisser._tpl`** — lines 72–79; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`PopupDismisser._full_tpl`** — lines 81–88; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`PopupDismisser.find`** — lines 90–117; kind: `FunctionDef`.

Best match (score, x, y, w, h) in frame pixels, or None. Matching runs at half resolution.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`PopupDismisser._scales_for_check`** — lines 119–125; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`PopupDismisser._get_action_coords`** — lines 128–140; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`PopupDismisser.update`** — lines 143–217; kind: `FunctionDef`.

Returns True while the popup is being handled (caller should not click ghosts).

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

### `webhook_reporter.py`

Source file: `webhook_reporter.py`.

**`_find_tesseract`** — lines 49–57; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`parse_amount`** — lines 93–105; kind: `FunctionDef`.

'Vous avez obtenu Ectoplaz xS5' -> 55. None if no plausible amount.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WebhookReporter`** — lines 108–355; kind: `ClassDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WebhookReporter.__init__`** — lines 109–149; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WebhookReporter.add_gain_listener`** — lines 152–154; kind: `FunctionDef`.

fn(amount:int, t_seen:float), called from the OCR thread on every confirmed gain.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WebhookReporter.set_stats_provider`** — lines 156–157; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WebhookReporter.feed_alive`** — lines 159–161; kind: `FunctionDef`.

True only while OCR really works, so 'no gain' is meaningful evidence.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WebhookReporter.check_and_report`** — lines 163–179; kind: `FunctionDef`.

Called every frame by main.py: a slice copy + queue put at most every TOAST_POLL_S.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WebhookReporter._ocr_loop`** — lines 182–191; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WebhookReporter._ocr_once`** — lines 193–196; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WebhookReporter._read_toast`** — lines 198–237; kind: `FunctionDef`.

Returns (visible, value). visible = toast-like bright text present; value = amount or None.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WebhookReporter._save_debug`** — lines 239–250; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WebhookReporter._health`** — lines 252–259; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WebhookReporter._update_toast_state`** — lines 262–298; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WebhookReporter._session_line`** — lines 301–306; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WebhookReporter._send_loop`** — lines 308–329; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`WebhookReporter._post`** — lines 331–355; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

### `sample_manager.py`

Source file: `sample_manager.py`.

**`_tag_of`** — lines 48–50; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`_weight_of`** — lines 53–57; kind: `FunctionDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`find_duplicate_samples`** — lines 60–93; kind: `FunctionDef`.

Return (all_files, duplicates) for the PNGs in `folder`.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager`** — lines 96–458; kind: `ClassDef`.

No docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager.__init__`** — lines 97–123; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._build`** — lines 126–179; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._wheel`** — lines 181–185; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._on_wheel`** — lines 187–188; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._load_scores`** — lines 191–198; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._suspicion`** — lines 200–207; kind: `FunctionDef`.

0..1, higher = more likely mislabelled (unknown -> 0).

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._list_view`** — lines 209–226; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._thumb`** — lines 230–252; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager.refresh`** — lines 254–296; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._reset_page`** — lines 298–300; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._turn`** — lines 302–305; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._toggle`** — lines 308–311; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._select_all`** — lines 313–317; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._select_suspicious`** — lines 319–324; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._chosen`** — lines 326–327; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._count_status`** — lines 329–330; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._move`** — lines 333–347; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._quarantine`** — lines 349–355; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._restore`** — lines 357–363; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._flip`** — lines 365–371; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._delete`** — lines 373–390; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._remove_duplicates`** — lines 392–437; kind: `FunctionDef`.

Delete identical / near-identical images in the folder of the current view

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._ask`** — lines 439–443; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._open_folder`** — lines 445–450; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

**`SampleManager._close`** — lines 452–458; kind: `FunctionDef`.

No method docstring supplied.

- **Debugging use:** search for the symbol in the matching source file before changing it.
- **Compatibility:** private names may change between releases; tests should target observable behavior as well as implementation details.
- **Concurrency note:** when the symbol accesses queues, locks, callbacks or Tk widgets, keep the owning thread rules intact.
- **Failure evidence:** record the stack trace and the surrounding log messages before editing exception handling.

## Troubleshooting atlas: observable symptom to evidence-driven fix

Each card is a decision aid, not a promise that the underlying platform will behave identically on every PC. Start with logs and saved images; avoid changing multiple safety parameters at once.

**Troubleshooting case 001 — No window matched.**

- **Likely causes:** Window title, process selection, stale HWND, or permissions do not match the visible game.

- **Evidence-driven checks:** Confirm Highrise is open, inspect `--list-windows`, check `window_title`, and relaunch Preview.

- **Safety / recovery:** Do not loosen matching to any visible window; that can select the controller or a browser.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 002 — Frame capture returns empty.**

- **Likely causes:** The target is minimized, covered, captured through an unsupported backend, or capture dependencies failed.

- **Evidence-driven checks:** Read the exact `CAPTURE WAIT` reason, restore/focus Highrise, and verify the capture rectangle.

- **Safety / recovery:** No frame means there must be no click. Never convert capture failure into a fallback arbitrary click.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 003 — Preview sees UI instead of game.**

- **Likely causes:** The selected HWND or capture bounds include another window or wrong client origin.

- **Evidence-driven checks:** Compare a saved raw frame against the actual client area and verify window/client geometry.

- **Safety / recovery:** Keep live mode disabled until preview aligns with the game.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 004 — Bot clicks the same point.**

- **Likely causes:** Cooldown is local-only, tracking identity changes, or template matches the same scene patch repeatedly.

- **Evidence-driven checks:** Check shared spatial guard logs, template identities, disappearance evidence and repeated-click records.

- **Safety / recovery:** Do not just reduce cooldown; fix duplicate identity and false template sources first.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 005 — Bot never clicks in preview.**

- **Likely causes:** Expected: dry-run mode dispatches no real mouse input.

- **Evidence-driven checks:** Look for `DRY RUN` detections and candidate coordinates; switch to live only after verification.

- **Safety / recovery:** Do not diagnose dry-run no-clicks as an input failure without reading the mode.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 006 — Bot detects but live count stays zero.**

- **Likely causes:** The action may be blocked by cooldown, excluded zone, popup, foreground guard, click budget or missing driver.

- **Evidence-driven checks:** Read the next log message after `TARGET DETECTED` and identify the explicit guard.

- **Safety / recovery:** Do not bypass the guard until the reason and target coordinates are understood.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 007 — Clicks are sent but no reward.**

- **Likely causes:** Input could land outside the ghost, ghost animation may move, click could be late, or reward confirmation may be unhealthy.

- **Evidence-driven checks:** Check screen coordinates, local disappearance, watcher/OCR health and capture latency.

- **Safety / recovery:** An `INPUT SENT` event is not proof of a successful catch.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 008 — Very low FPS.**

- **Likely causes:** Frame size, too many candidate proposals, excessive exact templates, or debug image I/O dominate.

- **Evidence-driven checks:** Compare `tick_ms`, proposal time, template time, frame dimensions and candidate counts.

- **Safety / recovery:** Change one budget at a time and compare identical scenes.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 009 — One long stall every N frames.**

- **Likely causes:** Periodic exhaustive scan, library reload, model retraining, disk save or image import may run synchronously.

- **Evidence-driven checks:** Correlate the stall timestamp with PERF and reload/save/import messages.

- **Safety / recovery:** Network sync and retraining should not run in the live frame loop.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 010 — CPU high with low FPS.**

- **Likely causes:** The loop may continuously process unchanged 1080p frames or oversubscribe OpenCV threads.

- **Evidence-driven checks:** Benchmark capture-only, proposal-only and matching-only stages separately.

- **Safety / recovery:** The presence of an NVIDIA GPU does not mean CPU OpenCV code uses it.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 011 — Tiny ghosts missed.**

- **Likely causes:** Candidate minimum size and frame downscale erase small sprite details.

- **Evidence-driven checks:** Save a frame, inspect pixel dimensions, and test lower candidate floor in dry-run.

- **Safety / recovery:** A lower floor can increase small false positives; check negative scenes too.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 012 — Large effects selected instead of ghosts.**

- **Likely causes:** A bright spell/glow component dominates the proposal mask.

- **Evidence-driven checks:** Inspect segmentation masks, box aspect ratio, seed silhouette similarity and score margin.

- **Safety / recovery:** Do not interpret “bright” as “ghost”.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 013 — Different color ghosts missed.**

- **Likely causes:** The feature path may be too color-specific or references are insufficient.

- **Evidence-driven checks:** Add diverse positive examples, test hue shifts, and compare silhouette/texture scores.

- **Safety / recovery:** Use human-labeled examples and held-out frames rather than guessing a threshold.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 014 — Facing direction causes misses.**

- **Likely causes:** Mirror/rotation augmentation may be absent or weak.

- **Evidence-driven checks:** Test mirrored crops and different orientations; verify the model version includes those augmentations.

- **Safety / recovery:** Augmentation should not distort important facial geometry beyond realistic variants.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 015 — Ghost moves between detections.**

- **Likely causes:** Frame rate is too low or candidate tracker has no stable association across frames.

- **Evidence-driven checks:** Measure object displacement per frame and inspect track IDs/confidence.

- **Safety / recovery:** Do not reuse a stale screen coordinate for a moving target without track validation.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 016 — Target jitter causes rapid clicks.**

- **Likely causes:** Location dedup uses only exact or small-radius points and boxes jitter.

- **Evidence-driven checks:** Compare boxes across frames and increase identity-aware suppression only after testing.

- **Safety / recovery:** Do not increase click speed to compensate for unstable localization.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 017 — Same target has many template names.**

- **Likely causes:** Duplicate library assets differ slightly in crop, edge or transparency.

- **Evidence-driven checks:** Run the sample duplicate report and inspect clustered thumbnails.

- **Safety / recovery:** Back up before deduplication; similar colors can still be different classes.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 018 — Full screenshot gets clicked.**

- **Likely causes:** Screenshot asset entered target directory without cropping.

- **Evidence-driven checks:** Inspect target manifest and source filenames; move scene references to pending review.

- **Safety / recovery:** Never use a whole room screenshot as a click template.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 019 — Watcher image gets clicked.**

- **Likely causes:** Watcher folder routing failed or target and watcher directories overlap.

- **Evidence-driven checks:** Check library load summary and confirm watcher file paths.

- **Safety / recovery:** Watchers signal popup/reward state; they are not targets.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 020 — Popup persists forever.**

- **Likely causes:** Template differs by scale/theme, screenshot is stale, or state machine cannot confirm dismissal.

- **Evidence-driven checks:** Compare the popup template with a fresh frame and inspect each transition log.

- **Safety / recovery:** Do not let popup recovery drag or click arbitrary parts of the screen.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 021 — Popup handler blocks ghost clicks.**

- **Likely causes:** The watcher false-matches background or has too loose threshold.

- **Evidence-driven checks:** Review watcher confidence and confirm the popup is visually present.

- **Safety / recovery:** Tighten the watcher based on real positive/negative frames.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 022 — Reward toast counted twice.**

- **Likely causes:** OCR state machine rearmed while the same toast remained visible.

- **Evidence-driven checks:** Inspect event timestamps and absence polls; dedupe same toast episode.

- **Safety / recovery:** Do not count multiple OCR reads as separate rewards.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 023 — Reward toast not read.**

- **Likely causes:** Tesseract missing, crop region wrong, toast language differs, or OCR is slow.

- **Evidence-driven checks:** Check startup OCR health, save the ROI image and run OCR manually.

- **Safety / recovery:** If OCR is unhealthy, no-read must not be interpreted as a negative reward.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 024 — Webhook fails.**

- **Likely causes:** URL is invalid, endpoint returns an error, rate limit occurs, or network is unavailable.

- **Evidence-driven checks:** Check response code, sanitized error, retries and request timeout.

- **Safety / recovery:** Never log the complete webhook URL or token.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 025 — Webhook secret leaked.**

- **Likely causes:** URL is present in committed config, logs, or screenshots.

- **Evidence-driven checks:** Rotate the webhook immediately and remove it from history where appropriate.

- **Safety / recovery:** Treat a webhook URL as a credential, not as ordinary configuration.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 026 — GUI immediately closes.**

- **Likely causes:** Python dependency or Tk initialization failed and no console was visible.

- **Evidence-driven checks:** Open startup log; run `python gui.py` from a terminal.

- **Safety / recovery:** Do not repeatedly double-click without reading the traceback.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 027 — GUI cannot scroll.**

- **Likely causes:** Content scroll region is not updated, mouse wheel routed to wrong page, or stale GUI file runs.

- **Evidence-driven checks:** Use page buttons and scrollbar; verify the path of the running `gui.py`.

- **Safety / recovery:** Extract a clean release folder to avoid mixing versions.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 028 — GUI starts but buttons do nothing.**

- **Likely causes:** Child process never launched, callback raised, or UI worker error is queued.

- **Evidence-driven checks:** Inspect GUI log and process status; run child command manually with `--help`.

- **Safety / recovery:** Do not hide callback exceptions.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 029 — Stop button takes too long.**

- **Likely causes:** Child is busy inside a long blocking OpenCV call or ignores control file.

- **Evidence-driven checks:** Inspect shutdown timeout and process-group escalation log.

- **Safety / recovery:** Avoid kill-only shutdown if state must be saved.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 030 — F12 conflicts with hotkey.**

- **Likely causes:** Global key may be registered by both GUI and engine or OS/game.

- **Evidence-driven checks:** Keep client toggle and engine emergency quit distinct.

- **Safety / recovery:** Verify which process owns each hotkey in the specific build.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 031 — F9 pauses unexpectedly.**

- **Likely causes:** Focus/restore safety events or another process own the key.

- **Evidence-driven checks:** Check safety event timestamps and hotkey configuration.

- **Safety / recovery:** A pause should be visible in status and logs.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 032 — Exclusion zone misplaced.**

- **Likely causes:** Window size/DPI/client origin changed after drawing.

- **Evidence-driven checks:** Redraw zones in the current client area and test with overlay.

- **Safety / recovery:** Exclusion rectangles are usually relative to the game client, not the desktop.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 033 — Zone feature unavailable.**

- **Likely causes:** Optional pynput or keyboard dependency missing or permissions blocked global input.

- **Evidence-driven checks:** Check startup dependencies and use the in-GUI zone controls if available.

- **Safety / recovery:** Do not assume all hotkeys registered just because the process started.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 034 — Config JSON is invalid.**

- **Likely causes:** Trailing comma, wrong quote, wrong type, or manual partial edit.

- **Evidence-driven checks:** Validate JSON syntax; restore last known-good backup and save through GUI.

- **Safety / recovery:** Preserve booleans as booleans, not strings.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 035 — Setting appears ignored.**

- **Likely causes:** Running process loaded config at startup; the GUI saved to another folder; CLI override wins.

- **Evidence-driven checks:** Check the exact `--root`, active config path and startup log settings.

- **Safety / recovery:** A source edit does not modify a frozen EXE.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 036 — Executable rejects an argument.**

- **Likely causes:** EXE parser was built from an older source tree.

- **Evidence-driven checks:** Run `BLOOP-Client.exe --help`, compare with current main.py, rebuild.

- **Safety / recovery:** Do not assume the deployed binary contains current source.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 037 — PyInstaller missing hidden module.**

- **Likely causes:** Import is dynamic or optional and dependency was not collected.

- **Evidence-driven checks:** Add `--hidden-import` or PyInstaller spec hook and build in a clean venv.

- **Safety / recovery:** Test the EXE on a clean Windows account/folder.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 038 — EXE blocked by antivirus.**

- **Likely causes:** Packaged executable heuristic or untrusted unsigned build.

- **Evidence-driven checks:** Scan the artifact, verify source and hash, and build using a clean toolchain.

- **Safety / recovery:** Never tell customers to disable all antivirus protections indiscriminately.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 039 — EXE cannot find model.**

- **Likely causes:** The path differs between source run, one-file extraction and installed folder.

- **Evidence-driven checks:** Log resolved `ROOT`, model path, file existence and hash.

- **Safety / recovery:** Ship model as data or resolve relative to the application data directory explicitly.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 040 — Customer retrains model by accident.**

- **Likely causes:** Developer training path is still enabled in client mode.

- **Evidence-driven checks:** Enforce read-only at engine level and test against write attempts.

- **Safety / recovery:** Hiding a training button is not a security boundary.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 041 — Model changes after customer session.**

- **Likely causes:** Training or cleanup writes model files despite inference-only intention.

- **Evidence-driven checks:** Hash model before and after a session and test all code paths.

- **Safety / recovery:** Read-only claims require filesystem/logic checks.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 042 — Training accuracy looks perfect.**

- **Likely causes:** Train/test leakage or near-duplicate crops appear on both splits.

- **Evidence-driven checks:** Split by session/identity/time, run dedup and cross-validation.

- **Safety / recovery:** A high score on duplicates does not prove generalization.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 043 — Generalization fails on new room.**

- **Likely causes:** Training examples capture background, UI scale or one room palette.

- **Evidence-driven checks:** Add diverse click positives and hard negatives; evaluate held-out rooms.

- **Safety / recovery:** The learned object should not encode fixed screen location.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 044 — False positives rise after learning.**

- **Likely causes:** Labels are noisy or successful clicks were assumed from arbitrary screen changes.

- **Evidence-driven checks:** Review positives/negatives/quarantine samples and watcher health.

- **Safety / recovery:** Do not automatically promote every clicked crop to a positive class.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 045 — False negatives rise after augmentation.**

- **Likely causes:** Flips/rotations or color transforms make unnatural samples dominate.

- **Evidence-driven checks:** Reduce augmentation, compare unaugmented samples and evaluate orientation buckets.

- **Safety / recovery:** Realistic augmentation should reflect in-game variants.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 046 — No teacher-click samples collected.**

- **Likely causes:** Mouse hook unavailable, game capture frame buffer empty, or click was outside client rectangle.

- **Evidence-driven checks:** Check listener availability and log each filtering reason.

- **Safety / recovery:** Teacher mode must not collect clicks on the GUI or desktop.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 047 — Teacher mode trains on a misclick.**

- **Likely causes:** Coordinate mapping is offset or pre-click ring buffer is stale.

- **Evidence-driven checks:** Log click timestamp/frame timestamp and draw the crop box before saving.

- **Safety / recovery:** Require a human review/undo path for mislabeled samples.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 048 — Learning does not persist.**

- **Likely causes:** Path points to temporary folder, save failed or process terminated mid-write.

- **Evidence-driven checks:** Check file timestamps, logs and permissions; use atomic file replacement.

- **Safety / recovery:** Back up before manual model surgery.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 049 — Library reload misses added files.**

- **Likely causes:** New files are in the wrong directory or supported extensions differ.

- **Evidence-driven checks:** Review load summary, extension support and issue explicit reload.

- **Safety / recovery:** Do not add reward watcher to `seeds/`.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 050 — Repository import repeats work.**

- **Likely causes:** Cache key does not match source hash/version or force option set.

- **Evidence-driven checks:** Check import report and cached manifest.

- **Safety / recovery:** A forced reimport can alter crops; preserve a copy first.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 051 — Repository sync fails.**

- **Likely causes:** Network rate limit, renamed repository asset or transient connection.

- **Evidence-driven checks:** Retry sync separately from live mode and inspect failures in the report.

- **Safety / recovery:** Keep network work out of the frame loop.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 052 — Image decoder fails on Unicode path.**

- **Likely causes:** A code path uses an API that cannot open non-ASCII path characters.

- **Evidence-driven checks:** Prefer `np.fromfile` plus `cv2.imdecode` on Windows or verify the decoder.

- **Safety / recovery:** Test a path with accented characters and spaces.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 053 — Memory slowly grows.**

- **Likely causes:** Frame/history queues are unbounded, images are retained by caches, or log widget never trims.

- **Evidence-driven checks:** Track RSS and queue/cache sizes during an extended session.

- **Safety / recovery:** Use bounded queues and bounded LRU caches.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 054 — Disk fills up with diagnostics.**

- **Likely causes:** Every frame or candidate is written to disk.

- **Evidence-driven checks:** Disable continuous overlay writes or set a sampling interval.

- **Safety / recovery:** Keep only a bounded ring of recent diagnostic images.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 055 — Save causes stutter.**

- **Likely causes:** Large library/model serialization blocks the frame loop.

- **Evidence-driven checks:** Measure save duration and move serialization off-thread with snapshots.

- **Safety / recovery:** Atomic writes and locking are more important than a fast but corrupt save.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 056 — Multiple bot instances run.**

- **Likely causes:** Previous run survived closing GUI or a second copy launched.

- **Evidence-driven checks:** Inspect process list, project lock and active control file.

- **Safety / recovery:** Refuse to start a second instance by default.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 057 — Control file ignored.**

- **Likely causes:** Wrong path, stale command, permissions, or polling does not run.

- **Evidence-driven checks:** Log absolute control-file path and last modification time.

- **Safety / recovery:** Use atomic JSON writes and validate allowed commands.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 058 — Pause state desynchronized.**

- **Likely causes:** GUI and engine control protocol disagree.

- **Evidence-driven checks:** Read engine state logs and use a single source of truth for state transitions.

- **Safety / recovery:** On uncertainty, fail paused.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 059 — Game foreground guard blocks valid clicks.**

- **Likely causes:** Game window is not foreground or overlays the exact click point.

- **Evidence-driven checks:** Focus game and verify the GUI is minimized/hidden; inspect HWND and cursor point.

- **Safety / recovery:** Do not disable the guard to make detections appear productive.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 060 — Capture guard sees BLOOP instead of game.**

- **Likely causes:** Window title query is too broad or process filter missing.

- **Evidence-driven checks:** Use executable/process selection and log all candidate HWNDs.

- **Safety / recovery:** Never use title substring alone where a process check is available.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 061 — Resolution changed mid-session.**

- **Likely causes:** Window resized and saved client rectangle/coordinates are stale.

- **Evidence-driven checks:** Detect size changes and rebuild capture region; invalidate stale tracks.

- **Safety / recovery:** Coordinates must be recomputed from the current frame, not old desktop pixels.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 062 — DPI scaling causes offset.**

- **Likely causes:** DPI awareness not set consistently across GUI and engine.

- **Evidence-driven checks:** Log DPI mode and compare detected frame coordinates with desktop coordinates.

- **Safety / recovery:** Set DPI awareness before creating windows or querying geometry.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 063 — Click near window edge is rejected.**

- **Likely causes:** Target center/offset lies outside valid client area.

- **Evidence-driven checks:** Clamp target centers and validate bounds before dispatch.

- **Safety / recovery:** Never silently clamp a bad large box into a random safe-looking point.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 064 — Multiple ghosts overlapping.**

- **Likely causes:** NMS removes adjacent objects or one large mask spans two ghosts.

- **Evidence-driven checks:** Adjust IoU threshold and inspect both candidate proposals and final detections.

- **Safety / recovery:** Test crowded-scene recall separately from single-object recall.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 065 — Repeated detection after reward.**

- **Likely causes:** Old object template remains in scene background or cooldown rearm is too permissive.

- **Evidence-driven checks:** Require disappearance/motion evidence and associate watcher events with the click window.

- **Safety / recovery:** Do not use global toast occurrence to clear every spatial guard.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 066 — Adaptive threshold drifts down.**

- **Likely causes:** Feedback labels are noisy or response metric mistakes room animation for success.

- **Evidence-driven checks:** Review score history and clamp min/max; validate on fixed labeled set.

- **Safety / recovery:** Learning threshold should not self-reinforce unchecked false positives.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 067 — Threshold too high after misses.**

- **Likely causes:** Adaptive code may only raise threshold or failed examples dominate.

- **Evidence-driven checks:** Review per-class positive score distributions and retain a manual floor/ceiling.

- **Safety / recovery:** Separate recognition confidence from response confidence.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 068 — Template exact match is slow.**

- **Likely causes:** Too many scales, large templates, or full-size matching on 1080p each pass.

- **Evidence-driven checks:** Use downscaled frame, bounded rotated template budget and cache reusable features.

- **Safety / recovery:** Measure each stage; do not assume CUDA or more threads solve Python orchestration.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 069 — Fast proposals consume too much CPU.**

- **Likely causes:** Too many contours, color masks, or verifier calls.

- **Evidence-driven checks:** Reduce candidate budget and use shortlist ranking before expensive verification.

- **Safety / recovery:** Monitor recall using labeled fixtures when reducing budget.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 070 — Tracker loses fast ghost.**

- **Likely causes:** Large per-frame displacement exceeds matching gate or no motion model used.

- **Evidence-driven checks:** Measure velocity/displacement and adjust tracker association using multiple consecutive frames.

- **Safety / recovery:** Prediction is helpful only when uncertainty is represented.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 071 — Prediction clicks behind moving sprite.**

- **Likely causes:** Motion lead is excessive or track velocity is noisy.

- **Evidence-driven checks:** Set lead to zero, validate track continuity, then test small lead values.

- **Safety / recovery:** Always cap prediction distance and reject stale tracks.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 072 — Model inference blocks frame loop.**

- **Likely causes:** Training, model loading or high-cost feature extraction happens inline.

- **Evidence-driven checks:** Profile `features`, model prediction, training and I/O independently.

- **Safety / recovery:** Training should use a worker; inference should use a bounded feature batch.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 073 — Optional module silently inactive.**

- **Likely causes:** Import exception was caught and feature fell back to classic matching.

- **Evidence-driven checks:** Read startup capability report and log exact import failure.

- **Safety / recovery:** Optional imports must be visible, not silently treated as full capability.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 074 — OCR package installed but no OCR.**

- **Likely causes:** Tesseract executable itself is not installed or located.

- **Evidence-driven checks:** Run `tesseract --version`, configure executable path, inspect startup OCR report.

- **Safety / recovery:** The Python wrapper is not the OCR engine.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 075 — Report counters reset unexpectedly.**

- **Likely causes:** GUI process restarted or session counters are intentionally in-memory.

- **Evidence-driven checks:** Distinguish per-process counters from persisted totals.

- **Safety / recovery:** Persist a session ID and timestamp when long-term analytics are needed.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 076 — Debug log lacks click reason.**

- **Likely causes:** A guard returns false without a structured reason code.

- **Evidence-driven checks:** Add named block reasons and counters to every gate.

- **Safety / recovery:** Avoid unstructured noisy logs; reason codes make diagnosis actionable.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 077 — Customer asks for more settings.**

- **Likely causes:** Customer UI is intentionally restricted.

- **Evidence-driven checks:** Expose only customer-safe toggles and diagnostics; keep advanced calibration in developer build.

- **Safety / recovery:** Do not ship training/admin features accidentally just to satisfy a UI request.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 078 — New model is incompatible.**

- **Likely causes:** Feature schema/model dimensions changed between versions.

- **Evidence-driven checks:** Store model version, feature version, dimensions and checksum in metadata.

- **Safety / recovery:** Reject incompatible models with clear errors rather than guessing.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 079 — Checkpoint partially written.**

- **Likely causes:** Crash during direct overwrite leaves a corrupt model or config.

- **Evidence-driven checks:** Write to a temporary file, fsync where needed, and atomically replace.

- **Safety / recovery:** Retain the previous known-good backup until validation passes.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 080 — Source and executable differ.**

- **Likely causes:** The EXE is stale, compiled from another folder or another git commit.

- **Evidence-driven checks:** Log build revision/hash and compare to source commit.

- **Safety / recovery:** A source edit never mutates bytes embedded in an existing EXE.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 081 — Need reproduce a bug.**

- **Likely causes:** Only a screenshot or anecdotal report is available.

- **Evidence-driven checks:** Record frame, timestamp, config snapshot, model hash, log, target box and block reason.

- **Safety / recovery:** Redact credentials and private messages from repro bundles.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 082 — Need report a false positive.**

- **Likely causes:** The object is incorrectly labeled as target.

- **Evidence-driven checks:** Save the crop and wider context; add to hard-negative review, do not immediately delete model.

- **Safety / recovery:** Ensure both cropped target and context image are available to maintainers.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 083 — Need report a missed ghost.**

- **Likely causes:** No detection box appears over the target.

- **Evidence-driven checks:** Save raw frame, scale, target size, template/model version and candidate-stage telemetry.

- **Safety / recovery:** Distinguish no proposal from proposal rejected at verification.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 084 — Need improve throughput.**

- **Likely causes:** FPS alone hides detector latency and time spent waiting.

- **Evidence-driven checks:** Report capture ms, proposal ms, template ms, model ms, input ms, and queue age.

- **Safety / recovery:** Use percentile latency over a sustained interval, not one best frame.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 085 — Need safely share logs.**

- **Likely causes:** Logs may contain webhook URL, local username, paths or private game content.

- **Evidence-driven checks:** Redact secrets and personal paths while preserving timestamps/reason codes.

- **Safety / recovery:** Rotate credentials if a real secret was ever committed or shared.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 086 — Config migration needed.**

- **Likely causes:** New version adds/renames fields or changes semantics.

- **Evidence-driven checks:** Version configs and migrate recognized fields while preserving a backup.

- **Safety / recovery:** Unknown-field dropping should be logged so a setting is not silently lost.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 087 — Game update breaks matching.**

- **Likely causes:** Sprite renderer, glow, scaling or window backend changed.

- **Evidence-driven checks:** Capture a fresh labeled test set and rerun feature/threshold evaluation.

- **Safety / recovery:** Avoid lowering the threshold globally before identifying the changed feature.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 088 — Popup animation creates clicks.**

- **Likely causes:** Watcher only detects one frame late or gets disabled by cooldown.

- **Evidence-driven checks:** Require repeated watcher hits and gate ordinary input while popup evidence is recent.

- **Safety / recovery:** Popup actions should have a separate state machine from ghost clicks.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 089 — Click counter differs from game rewards.**

- **Likely causes:** Input dispatch metric is not reward confirmation.

- **Evidence-driven checks:** Compare click attempts, input sent, watcher rewards and OCR increments separately.

- **Safety / recovery:** Never interpret these counters as interchangeable.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 090 — Import report says pending.**

- **Likely causes:** Importer preserved an ambiguous whole-room image.

- **Evidence-driven checks:** Open `corpus/pending/`, crop the actual ghost manually and import as a tight template.

- **Safety / recovery:** Pending means not active, not necessarily a failed download.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 091 — Import creates duplicate seed files.**

- **Likely causes:** Crop variations are below duplicate threshold.

- **Evidence-driven checks:** Review crop montage and dedup report; retain color/facing diversity where useful.

- **Safety / recovery:** Do not collapse distinct ghost forms solely because color thumbnails look close.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 092 — Bot targets avatar/name labels.**

- **Likely causes:** Proposal logic mistakes glowing accessory, username or UI badges for a sprite.

- **Evidence-driven checks:** Add hard negatives and increase geometric/shape verification; inspect the candidate crop.

- **Safety / recovery:** Do not make a target click based on hue alone.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 093 — App crashes while closing.**

- **Likely causes:** Background worker accesses destroyed Tk widget or process is still active.

- **Evidence-driven checks:** Stop worker, join reader, drain queues safely, then destroy root.

- **Safety / recovery:** Tk widgets must be updated from the Tk main thread.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 094 — Save settings overwrites another version.**

- **Likely causes:** Two GUIs write the same config concurrently.

- **Evidence-driven checks:** Use a single-instance lock or compare config modification time before saving.

- **Safety / recovery:** Warn on external changes; do not silently discard newer settings.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 095 — Repository branch changed.**

- **Likely causes:** Default branch or path changed since docs were written.

- **Evidence-driven checks:** Check current branch and GitHub file list; update repo URL/asset manifest.

- **Safety / recovery:** Do not assume old image count remains accurate.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 096 — Screen captured black.**

- **Likely causes:** GPU/compositor capture API may not expose a hardware-rendered window.

- **Evidence-driven checks:** Try supported capture method, disable minimized capture, and compare to desktop screenshot.

- **Safety / recovery:** A black frame must never be interpreted as an empty target field and clicked.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 097 — No click reaches game but driver says sent.**

- **Likely causes:** Game may ignore synthetic input, require focus, or have input injection restrictions.

- **Evidence-driven checks:** Use a visible harmless test and verify cursor/click behavior in game.

- **Safety / recovery:** Input API return is not proof of game-side acceptance.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 098 — Clicks overshoot due to scaling.**

- **Likely causes:** Detection was performed on scaled frame but coordinates restored incorrectly.

- **Evidence-driven checks:** Test a calibration target at known coordinates and inspect original-frame overlay.

- **Safety / recovery:** Keep coordinate transforms in one place and unit-test every scale factor.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 099 — Multiple displays mismatch.**

- **Likely causes:** Window coordinates are virtual-desktop based but capture uses monitor-local origin.

- **Evidence-driven checks:** Log monitor origin, HWND rectangle, client rectangle, and coordinate conversion.

- **Safety / recovery:** Test with a window on each monitor configuration.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 100 — Learning starts with few positives.**

- **Likely causes:** The model lacks representative examples and should not click aggressively.

- **Evidence-driven checks:** Collect diverse teacher positives and hard negatives before enabling smart-exclusive behavior.

- **Safety / recovery:** A pretrained weight file needs its matching feature definition and model metadata.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 101 — Learning accepts background patch.**

- **Likely causes:** Crop centered on click does not isolate the clicked object.

- **Evidence-driven checks:** Review mask overlays, foreground ratio, center offset and patch dimensions.

- **Safety / recovery:** Human click labels identify a point, not a perfect bounding box; use uncertainty handling.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 102 — Negative sample set is polluted.**

- **Likely causes:** Every missed click or no-reward event may be mislabeled as a negative.

- **Evidence-driven checks:** Require clear persistent non-target evidence or human review before negative promotion.

- **Safety / recovery:** No reward can be caused by aim, timing, network or OCR failure.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 103 — Training is unstable.**

- **Likely causes:** Class imbalance, too few examples, repeated duplicates or mismatched feature versions.

- **Evidence-driven checks:** Inspect class counts, calibration split, loss/metrics and sample weights.

- **Safety / recovery:** Do not evaluate on augmented copies of the training examples.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 104 — Webhook interval seems ignored.**

- **Likely causes:** A configured interval may be legacy or intentionally unused by a version.

- **Evidence-driven checks:** Inspect actual event scheduling in the reporter source.

- **Safety / recovery:** Document current behavior, not only a configuration field name.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 105 — One image extension is skipped.**

- **Likely causes:** Importer allowlist may not include SVG/WEBP/GIF or uppercase extension.

- **Evidence-driven checks:** Check importer supported list and import report.

- **Safety / recovery:** Unsupported images should produce visible report entries.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 106 — Need update without deleting model.**

- **Likely causes:** New source files need to replace code but learned data should persist.

- **Evidence-driven checks:** Back up data directories and replace only program/source files; run migration if needed.

- **Safety / recovery:** Never overwrite learned model without explicit backup/consent.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 107 — Customer build shows developer controls.**

- **Likely causes:** Wrong GUI/entry point got packaged or cached old EXE is launched.

- **Evidence-driven checks:** Log executable path and build ID; inspect dist package contents.

- **Safety / recovery:** A customer interface is not a permission boundary unless engine mode enforces it.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 108 — Customer has wrong webhook.**

- **Likely causes:** Webhook config persisted from developer environment.

- **Evidence-driven checks:** Ship empty default and ask customer to set their own secret.

- **Safety / recovery:** Do not commit personal endpoint values.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 109 — Stop still leaves a process.**

- **Likely causes:** Child spawned its own worker/subprocess or shutdown command not relayed.

- **Evidence-driven checks:** Enumerate child process tree and ensure stop protocol propagates.

- **Safety / recovery:** A GUI close must not imply engine stopped until exit is confirmed.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 110 — F12 does nothing in EXE.**

- **Likely causes:** Global keyboard hook missing or key registered by another process.

- **Evidence-driven checks:** Check startup log and dependency packaging; test button as fallback.

- **Safety / recovery:** The GUI button and hotkey should call the same state transition.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 111 — F11 does nothing.**

- **Likely causes:** Emergency hotkey not wired or engine has a different quit hotkey.

- **Evidence-driven checks:** Inspect exact `hk_quit` and client global hotkey map.

- **Safety / recovery:** Document distinct client-toggle and engine-quit keys clearly.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 112 — No windows listed.**

- **Likely causes:** pywin32 missing, not on Windows, or process lacks GUI desktop access.

- **Evidence-driven checks:** Check import/dependency health and run under the same interactive user session.

- **Safety / recovery:** Windows window enumeration cannot be validated in a Linux container.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 113 — Model npz loads with error.**

- **Likely causes:** File is damaged, compressed arrays differ, or dtype/dimension incompatible.

- **Evidence-driven checks:** Check archive integrity, expected keys/shapes and model metadata.

- **Safety / recovery:** Do not silently replace a corrupt model with randomly initialized weights.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 114 — Model makes no confident predictions.**

- **Likely causes:** No preprocessing parity or model weights do not match feature extractor.

- **Evidence-driven checks:** Compare feature dimension, normalization, model version and training pipeline.

- **Safety / recovery:** Inference feature code must match the code that generated training data.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 115 — Track clicks while paused.**

- **Likely causes:** Pause flag is not checked on one action path.

- **Evidence-driven checks:** Add pause gate at the centralized action dispatcher, not only loop top.

- **Safety / recovery:** Every click path must pass the same final input guard.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 116 — Action runs in dry run.**

- **Likely causes:** A special popup action bypasses dry-run guard.

- **Evidence-driven checks:** Centralize dry-run enforcement below every action producer.

- **Safety / recovery:** Dry run must be an invariant across target, exploration and popup handlers.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 117 — Learning checks stall FPS.**

- **Likely causes:** Response monitor performs blocking capture/sleep inside click handler.

- **Evidence-driven checks:** Queue delayed feedback and poll it on later frames or worker jobs.

- **Safety / recovery:** Do not put fixed sleep loops in latency-sensitive detection path.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 118 — Too many candidate boxes.**

- **Likely causes:** NMS/IoU threshold too strict or proposal rank emits multiple overlapping scales.

- **Evidence-driven checks:** Visualize pre-NMS and post-NMS candidates and tune their separate thresholds.

- **Safety / recovery:** Do not remove true adjacent ghosts as duplicates.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 119 — No candidate boxes at all.**

- **Likely causes:** Color mask assumptions fail on lighting change or proposal stage rejects size.

- **Evidence-driven checks:** Save mask intermediates and use exact templates in preview to isolate the failing stage.

- **Safety / recovery:** Differentiate capture success from proposal success.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 120 — Large green effect not learned.**

- **Likely causes:** Glow and facial details connect into one component or shape test is too restrictive.

- **Evidence-driven checks:** Review segmentation, use multiple masks and validate body/facial contrast independently.

- **Safety / recovery:** Do not fix this by accepting every bright blob.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 121 — Blue ghost missed on green room.**

- **Likely causes:** Color-invariant feature or template mask overfits the background.

- **Evidence-driven checks:** Use tight crop, masks and hard negatives from the same room palette.

- **Safety / recovery:** Keep background context limited during model training.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 122 — Rotated or mirrored target missed.**

- **Likely causes:** No variant augmentation or exact template bank only supports one facing.

- **Evidence-driven checks:** Capture examples for alternate facing and validate augmentation transformations.

- **Safety / recovery:** Mirror support should be tested independently of color robustness.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 123 — Motion creates ghost trail proposals.**

- **Likely causes:** Temporal difference highlights afterimages and particles.

- **Evidence-driven checks:** Associate detections across consecutive frames and require stable object-like shape.

- **Safety / recovery:** A motion mask alone is not a semantic classifier.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 124 — FPS changes with debug overlay.**

- **Likely causes:** JPEG/PNG writes or drawing large images dominate loop.

- **Evidence-driven checks:** Measure diagnostic write time and sample overlays at a slower interval.

- **Safety / recovery:** Keep debug artifacts bounded.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 125 — System runs hot with OpenCV threads.**

- **Likely causes:** OpenCV and Python workers compete for cores.

- **Evidence-driven checks:** Benchmark thread count 1, 2, 4 on the target PC.

- **Safety / recovery:** Best thread count is workload-specific.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 126 — Windows Defender warns on EXE.**

- **Likely causes:** Unsigned PyInstaller artifact may be heuristically suspicious.

- **Evidence-driven checks:** Build reproducibly, scan file, verify hash and consider signing.

- **Safety / recovery:** Never disguise the binary or tell users to bypass warnings without investigation.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 127 — Portable folder path has spaces.**

- **Likely causes:** Quoted arguments are missing in subprocess command.

- **Evidence-driven checks:** Pass argument list rather than a joined command string; test a path with spaces.

- **Safety / recovery:** The supplied Send Anywhere path is a useful regression case.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 128 — Portable folder path has accents.**

- **Likely causes:** Unicode path used with unsupported native call.

- **Evidence-driven checks:** Run smoke test from a folder containing non-ASCII characters.

- **Safety / recovery:** All path I/O should use Unicode-safe APIs.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 129 — Model file is too big to ship.**

- **Likely causes:** Training artifacts include raw images or replay buffers.

- **Evidence-driven checks:** Separate compact inference weights from datasets and optimizer state.

- **Safety / recovery:** Keep customer package lean but preserve needed metadata.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 130 — README examples do not match EXE.**

- **Likely causes:** Documentation refers to source flags unavailable in binary.

- **Evidence-driven checks:** Generate `--help` snapshot from the release artifact and compare docs.

- **Safety / recovery:** Rebuild the EXE after argument changes.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 131 — Need verify release contents.**

- **Likely causes:** ZIP may omit companion modules, seeds or watcher assets.

- **Evidence-driven checks:** List ZIP entries and compare with an explicit packaging manifest.

- **Safety / recovery:** Fail release build if a required path is missing.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

**Troubleshooting case 132 — Need rollback a release.**

- **Likely causes:** New version breaks capture or model loading.

- **Evidence-driven checks:** Keep old ZIP and configuration/model backup with hashes.

- **Safety / recovery:** Never overwrite the only working binary before validation.

- **Record:** timestamp, active version, absolute project root, config backup name, frame dimensions, FPS/tick time, candidate count, score, coordinates, and the exact block reason.
- **Exit condition:** only resume live clicking when the issue has a specific explanation and Preview no longer reproduces it.
- **Avoid:** making a broad threshold/cooldown change before confirming which stage failed.

## Validation catalog and test design

This is a recommended release test plan. It describes what the project should validate; it does not state that all tests are present or have passed unless the release’s separate report says so. For each build, record command, OS, Python version, result, elapsed time, and relevant artifact hash.

**Validation 001 — Config parse.**

- **Positive / expected path:** Valid JSON loads into typed fields.

- **Negative / regression path:** Malformed JSON produces a clear error and does not overwrite the prior file.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 002 — Unknown config field.**

- **Positive / expected path:** Unknown keys are ignored according to the implementation.

- **Negative / regression path:** Migration tool should report ignored keys rather than silently implying support.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 003 — CLI help.**

- **Positive / expected path:** Every parser argument appears in --help.

- **Negative / regression path:** Frozen EXE argument list is separately tested after every build.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 004 — Window title.**

- **Positive / expected path:** Known title selects intended window in a mocked enumerator.

- **Negative / regression path:** Generic substring cannot match BLOOP Control Panel.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 005 — Process filter.**

- **Positive / expected path:** Executable match prefers Highrise process.

- **Negative / regression path:** Missing process metadata fails safe rather than selecting unrelated app.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 006 — Minimized window.**

- **Positive / expected path:** Capture state reports minimized/invalid surface.

- **Negative / regression path:** No click is attempted without a usable frame.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 007 — Foreground guard.**

- **Positive / expected path:** Game foreground is accepted.

- **Negative / regression path:** Other foreground app blocks capture/click as configured.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 008 — Client rectangle.**

- **Positive / expected path:** Client origin and size are recorded.

- **Negative / regression path:** Title bar and borders are not mistakenly included in target coordinates.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 009 — DPI transform.**

- **Positive / expected path:** Known point maps through scale conversion.

- **Negative / regression path:** DPI changes do not double-scale overlay coordinates.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 010 — Monitor origin.**

- **Positive / expected path:** Capture on primary monitor maps correctly.

- **Negative / regression path:** Secondary display negative/positive coordinates are handled explicitly.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 011 — Blank frame.**

- **Positive / expected path:** No targets returned from blank capture.

- **Negative / regression path:** No fallback point is clicked.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 012 — Static frame.**

- **Positive / expected path:** Unchanged-frame optimization still periodically rescans.

- **Negative / regression path:** Small changes below delta are not starved indefinitely.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 013 — Color shift.**

- **Positive / expected path:** Target remains discoverable across expected hue changes.

- **Negative / regression path:** Decorations sharing that hue remain rejected by shape/texture checks.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 014 — Brightness shift.**

- **Positive / expected path:** Matching tolerates expected glow changes.

- **Negative / regression path:** Very dim frames do not cause unconstrained threshold adaptation.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 015 — Scale sweep.**

- **Positive / expected path:** Targets are found at trained scale sizes.

- **Negative / regression path:** Very small sizes do not flood the detector with particles.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 016 — Facing variants.**

- **Positive / expected path:** Mirrored examples are scored consistently if augmentation is enabled.

- **Negative / regression path:** No unsupported orientation-invariance claim is made without results.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 017 — Translation invariance.**

- **Positive / expected path:** Same sprite at multiple frame locations is found.

- **Negative / regression path:** Click logic does not hard-code sample coordinates.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 018 — Moving target.**

- **Positive / expected path:** Tracker associates consecutive boxes in synthetic motion.

- **Negative / regression path:** Stale position cannot be clicked after track is lost.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 019 — Multiple targets.**

- **Positive / expected path:** Two separated instances produce separate boxes.

- **Negative / regression path:** NMS does not merge different instances too aggressively.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 020 — Overlapping targets.**

- **Positive / expected path:** Nearby candidates are reviewed with overlap-aware test.

- **Negative / regression path:** Suppression behavior is explicit and measured.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 021 — Known template.**

- **Positive / expected path:** Strong positive template matches.

- **Negative / regression path:** Negative fixture must not trigger the same threshold.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 022 — Scene screenshot.**

- **Positive / expected path:** A room screenshot cannot become one huge target.

- **Negative / regression path:** Only reviewed crop becomes active template.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 023 — Watcher separation.**

- **Positive / expected path:** Watcher is detected in its watcher bank.

- **Negative / regression path:** Watcher path can never call target click dispatcher.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 024 — Empty library.**

- **Positive / expected path:** Startup status reports zero targets.

- **Negative / regression path:** Live operation is disabled or clearly reports that there are no valid targets.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 025 — Unreadable asset.**

- **Positive / expected path:** Decoder failure is logged with path.

- **Negative / regression path:** One bad image does not crash whole library load.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 026 — Unicode file path.**

- **Positive / expected path:** Image decodes from Unicode path.

- **Negative / regression path:** No ANSI-only file API assumptions.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 027 — Corrupt image.**

- **Positive / expected path:** Importer reports a failed asset.

- **Negative / regression path:** Corrupt file is not saved as valid template.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 028 — Duplicate images.**

- **Positive / expected path:** Near duplicates are grouped for review.

- **Negative / regression path:** Different color variants are not merged without evidence.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 029 — Template cache.**

- **Positive / expected path:** Repeated matching reuses immutable transformed features.

- **Negative / regression path:** Cache stays bounded and invalidates when source identity changes.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 030 — Mask cache.**

- **Positive / expected path:** Repeated mask calculation is reused where designed.

- **Negative / regression path:** Mutating input array cannot poison cached results.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 031 — Proposal budget.**

- **Positive / expected path:** Candidate count respects configured cap.

- **Negative / regression path:** Increasing cap has visible bounded CPU impact.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 032 — Template rotation.**

- **Positive / expected path:** Budget advances around target bank.

- **Negative / regression path:** One target does not monopolize all exact scans.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 033 — Template fallback.**

- **Positive / expected path:** Recovery scan catches misses not handled by fast path.

- **Negative / regression path:** It does not block loop for many seconds.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 034 — Match threshold.**

- **Positive / expected path:** Threshold boundary is tested precisely.

- **Negative / regression path:** Score never described as probability without calibration.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 035 — Candidate size floor.**

- **Positive / expected path:** Under-floor candidate rejected.

- **Negative / regression path:** Legitimate small-target recall documented.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 036 — False positive room.**

- **Positive / expected path:** Busy room fixture has an acceptance criterion.

- **Negative / regression path:** Any accepted negative is investigated, not hidden by average accuracy.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 037 — False negative ghost.**

- **Positive / expected path:** Each labeled positive has recall measurement.

- **Negative / regression path:** Miss stage is identified: capture, proposal, verification or action gate.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 038 — Spatial cooldown.**

- **Positive / expected path:** First candidate may pass.

- **Negative / regression path:** Same location from different target ID remains blocked inside cooldown.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 039 — Spatial rearm.**

- **Positive / expected path:** Target disappearance count reaches threshold.

- **Negative / regression path:** Ambiguous frame and animation flicker do not clear guard immediately.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 040 — Target cooldown.**

- **Positive / expected path:** Same template identity has its own retry budget.

- **Negative / regression path:** Fast path cannot bypass target cooldown.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 041 — Global CPS.**

- **Positive / expected path:** Input dispatch count obeys the rate cap.

- **Negative / regression path:** Blocked/failed inputs do not increment sent-click count.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 042 — Session click cap.**

- **Positive / expected path:** No action after finite maximum reached.

- **Negative / regression path:** Reset semantics are documented.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 043 — Per-frame cap.**

- **Positive / expected path:** Crowded frame remains within action budget.

- **Negative / regression path:** One detection pass cannot create an unbounded click burst.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 044 — Exclusion zone.**

- **Positive / expected path:** Point inside zone is blocked.

- **Negative / regression path:** Point outside zone follows normal gates.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 045 — Popup visible.**

- **Positive / expected path:** Watcher causes ordinary clicks to be skipped.

- **Negative / regression path:** Popup action is isolated from ghost click path.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 046 — Popup absent.**

- **Positive / expected path:** Popup state returns to idle.

- **Negative / regression path:** Stale watcher event does not block forever.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 047 — Dry-run invariant.**

- **Positive / expected path:** Every action pathway logs would-click.

- **Negative / regression path:** No mouse event is sent, including exploration and popup actions.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 048 — Input driver missing.**

- **Positive / expected path:** Startup reports missing driver.

- **Negative / regression path:** No “sent” log is emitted for unavailable library.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 049 — Input exception.**

- **Positive / expected path:** Exception recorded and click not counted as sent.

- **Negative / regression path:** Loop continues only if error is safely recoverable.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 050 — Coordinate center.**

- **Positive / expected path:** Box center maps to expected desktop point.

- **Negative / regression path:** Client offset added exactly once.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 051 — Coordinate clipping.**

- **Positive / expected path:** Off-screen/invalid point is rejected.

- **Negative / regression path:** No silent click at clipped unrelated coordinate.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 052 — Control file pause.**

- **Positive / expected path:** PAUSE prevents every input pathway.

- **Negative / regression path:** Fast, fallback, exploration, popup all check shared gate.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 053 — Control file resume.**

- **Positive / expected path:** RUNNING resumes only when game focus rules pass.

- **Negative / regression path:** GUI visible state cannot bypass pause safety.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 054 — Control file stop.**

- **Positive / expected path:** Stop is polled and state saved.

- **Negative / regression path:** Child exits within bounded timeout or escalation is logged.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 055 — Hotkey pause.**

- **Positive / expected path:** Pause callback is invoked once.

- **Negative / regression path:** Duplicate OS key events do not flood safety log.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 056 — Hotkey quit.**

- **Positive / expected path:** Quit stops bot.

- **Negative / regression path:** Client F12 toggle and engine emergency key remain documented per build.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 057 — Hotkey unavailable.**

- **Positive / expected path:** Missing keyboard dependency degrades visibly.

- **Negative / regression path:** Ctrl+C and GUI stop remain usable.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 058 — Atomic config save.**

- **Positive / expected path:** Temporary file replaces config atomically.

- **Negative / regression path:** Crash during save does not destroy last good config.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 059 — Model round trip.**

- **Positive / expected path:** Weights load and predict after serialization.

- **Negative / regression path:** Feature dimension/version mismatch is rejected.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 060 — Read-only inference.**

- **Positive / expected path:** Customer mode predicts without updates.

- **Negative / regression path:** Model checksum unchanged after a session.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 061 — Training mode.**

- **Positive / expected path:** Explicit opt-in collects training samples.

- **Negative / regression path:** Customer build cannot enable training by editing a config flag.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 062 — Teacher click capture.**

- **Positive / expected path:** Human click is associated with a recent frame.

- **Negative / regression path:** Click on GUI/outside game is filtered.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 063 — Teacher crop.**

- **Positive / expected path:** Crop centers around manually clicked location.

- **Negative / regression path:** Large amount of background triggers review/uncertainty.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 064 — Positive labeling.**

- **Positive / expected path:** Human-selected target is stored as positive.

- **Negative / regression path:** It is not considered a guaranteed catch without reward evidence.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 065 — Negative labeling.**

- **Positive / expected path:** Unambiguous rejected sample is stored as negative.

- **Negative / regression path:** A missed reward alone cannot blindly label the target non-ghost.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 066 — Sample quarantine.**

- **Positive / expected path:** Low-confidence samples remain excluded from training.

- **Negative / regression path:** Review/restore workflow is reversible.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 067 — Augmentation sanity.**

- **Positive / expected path:** Hue/scale/flip outputs remain plausible.

- **Negative / regression path:** Augment does not place target label on unrelated pixels.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 068 — Train/validation split.**

- **Positive / expected path:** Split has no exact duplicate leakage.

- **Negative / regression path:** Performance reports include class counts and split strategy.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 069 — Calibration.**

- **Positive / expected path:** Threshold chosen from held-out scores.

- **Negative / regression path:** No arbitrary 0.95 value described as 95% probability.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 070 — Negative hard set.**

- **Positive / expected path:** UI icons and room decorations included.

- **Negative / regression path:** False-positive rate reported by scene category.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 071 — Watcher timing.**

- **Positive / expected path:** Reward event associates with valid time window.

- **Negative / regression path:** Unrelated later watcher event is not attached to old click.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 072 — Watcher dedupe.**

- **Positive / expected path:** Same persistent toast fires once.

- **Negative / regression path:** Rearm requires observed absence.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 073 — OCR missing.**

- **Positive / expected path:** Startup health reports OCR unavailable.

- **Negative / regression path:** No OCR read is not treated as no reward.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 074 — OCR corrupt text.**

- **Positive / expected path:** Parser rejects impossible counts.

- **Negative / regression path:** No counter jump from unrecognized noise.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 075 — Webhook URL absent.**

- **Positive / expected path:** Rewards tracked locally if reporter supports it.

- **Negative / regression path:** No network post is attempted with empty URL.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 076 — Webhook URL secret.**

- **Positive / expected path:** Config/log sanitizer redacts it.

- **Negative / regression path:** No credential appears in example config or test output.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 077 — Network unavailable.**

- **Positive / expected path:** HTTP retry is bounded and asynchronous.

- **Negative / regression path:** No network wait blocks vision loop.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 078 — GUI startup.**

- **Positive / expected path:** Root window creates and mainloop runs.

- **Negative / regression path:** Traceback is saved if startup fails.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 079 — GUI scrolling.**

- **Positive / expected path:** Every page can reach bottom and return top.

- **Negative / regression path:** Wheel events over widgets reach intended page.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 080 — GUI thread safety.**

- **Positive / expected path:** Background reader posts through queue.

- **Negative / regression path:** Worker never mutates Tk widgets directly.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 081 — GUI close running.**

- **Positive / expected path:** User gets stop/save choice.

- **Negative / regression path:** Window does not claim closed while unmanaged engine remains active.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 082 — GUI duplicate instance.**

- **Positive / expected path:** Second copy is detected or prevented.

- **Negative / regression path:** Old process is not accidentally ignored.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 083 — GUI log cap.**

- **Positive / expected path:** Text widget lines remain bounded.

- **Negative / regression path:** Latest logs remain inspectable without memory growth.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 084 — GUI settings dirty.**

- **Positive / expected path:** Unsaved changes are indicated.

- **Negative / regression path:** Close offers save/discard/cancel.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 085 — GUI config backup.**

- **Positive / expected path:** Prior copies retained to configured count.

- **Negative / regression path:** Restore procedure tested.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 086 — Importer happy path.**

- **Positive / expected path:** Supported image fetched and stored.

- **Negative / regression path:** Manifest/hash marks it up-to-date on later sync.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 087 — Importer HTTP failure.**

- **Positive / expected path:** Failed URL captured in report.

- **Negative / regression path:** Partial import does not falsely report complete success.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 088 — Importer pending scene.**

- **Positive / expected path:** Full screenshot preserved for review.

- **Negative / regression path:** It is not activated as click template.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 089 — Importer watcher routing.**

- **Positive / expected path:** ok/okay files go to watcher directory.

- **Negative / regression path:** Filename extension case does not change role.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 090 — Importer reimport.**

- **Positive / expected path:** Cached corpus rebuild avoids network.

- **Negative / regression path:** Existing manual crops are not unexpectedly deleted.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 091 — Model package.**

- **Positive / expected path:** Weights/model metadata copied into distribution.

- **Negative / regression path:** Customer starts from a clean directory and can load it.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 092 — PyInstaller dependency.**

- **Positive / expected path:** Frozen app can import every required module.

- **Negative / regression path:** Dynamic import included through spec/hidden-import where required.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 093 — PyInstaller data.**

- **Positive / expected path:** Popup image/config/model exist in release.

- **Negative / regression path:** Paths resolve from chosen app root, not build machine CWD.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 094 — Clean PC install.**

- **Positive / expected path:** App starts with only documented prerequisites.

- **Negative / regression path:** No hidden developer path/dependency is assumed.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 095 — Space in path.**

- **Positive / expected path:** Child command uses argument list.

- **Negative / regression path:** Path containing spaces runs without splitting flags.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 096 — Unicode path.**

- **Positive / expected path:** Config/model loads in non-ASCII path.

- **Negative / regression path:** File-system operations keep Unicode filenames.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 097 — Stale EXE.**

- **Positive / expected path:** Version/build hash printed.

- **Negative / regression path:** Command options align with included source. 

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 098 — Archive integrity.**

- **Positive / expected path:** All package entries readable.

- **Negative / regression path:** Required files checked against manifest.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 099 — Long run stability.**

- **Positive / expected path:** Multi-hour soak monitors memory, CPU, logs.

- **Negative / regression path:** No duplicate process, click bursts or queue growth.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 100 — Release rollback.**

- **Positive / expected path:** Previous EXE/config/model retained.

- **Negative / regression path:** Rollback does not mix old code with new model schema.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 101 — README command audit.**

- **Positive / expected path:** Commands execute or are labeled illustrative.

- **Negative / regression path:** README names match current files and CLI parser.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

**Validation 102 — Security audit.**

- **Positive / expected path:** Secrets and personal paths checked.

- **Negative / regression path:** Webhook rotation and clean customer config confirmed.

- **Required evidence:** test output, assertion name, run identifier, and a short explanation of what would constitute a failure.
- **Pass criteria:** both expected behavior and failure-safe behavior are demonstrated; a single happy-path test is insufficient.
- **Release note:** record whether this check was run on Linux, Windows, a virtual display, mocked input, or the real game client.

- **When it fails:** preserve the failing fixture and config snapshot before changing thresholds; add the reproduction to the automated suite.

## Operational playbooks

Use these runbooks as ordered checklists. Mark completion in your release notes so repeatable work does not depend on memory.

### Playbook 01 — First installation

Extract source into a permanent user-owned folder; create venv; install requirements; run `--help`; open GUI; inspect config path; launch preview; verify capture; only then consider live mode.

**Checklist**

- [ ] Confirm the version and project root.
- [ ] Back up the current configuration and any learned artifacts that will be touched.
- [ ] Make one controlled change at a time.
- [ ] Capture before/after metrics and save representative diagnostics.
- [ ] Run the negative case as well as the happy path.
- [ ] Stop immediately if capture geometry or click coordinates are uncertain.
- [ ] Record the outcome and exact rollback step.

**Completion criteria**  
The workflow completes without unexplained warnings, safety gates remain active, and the recorded evidence matches the intended change.

### Playbook 02 — First live session

Set conservative CPS and finite click budget; check window selection; hide controller before resume; keep reward watcher healthy; watch detection and input counters separately; stop if boxes drift.

**Checklist**

- [ ] Confirm the version and project root.
- [ ] Back up the current configuration and any learned artifacts that will be touched.
- [ ] Make one controlled change at a time.
- [ ] Capture before/after metrics and save representative diagnostics.
- [ ] Run the negative case as well as the happy path.
- [ ] Stop immediately if capture geometry or click coordinates are uncertain.
- [ ] Record the outcome and exact rollback step.

**Completion criteria**  
The workflow completes without unexplained warnings, safety gates remain active, and the recorded evidence matches the intended change.

### Playbook 03 — Calibrate new resolution

Save baseline config; capture a frame; log client rectangle; test scaling/crop mapping; adjust max dimension and minimum candidate sizes; verify overlay on corners and center; retest multiple monitors.

**Checklist**

- [ ] Confirm the version and project root.
- [ ] Back up the current configuration and any learned artifacts that will be touched.
- [ ] Make one controlled change at a time.
- [ ] Capture before/after metrics and save representative diagnostics.
- [ ] Run the negative case as well as the happy path.
- [ ] Stop immediately if capture geometry or click coordinates are uncertain.
- [ ] Record the outcome and exact rollback step.

**Completion criteria**  
The workflow completes without unexplained warnings, safety gates remain active, and the recorded evidence matches the intended change.

### Playbook 04 — Add a new ghost image

Place a tight crop in the documented target source folder; keep watcher images separate; give it a descriptive filename; run import/duplicate check; inspect its mask; validate against hard-negative room images; reload library.

**Checklist**

- [ ] Confirm the version and project root.
- [ ] Back up the current configuration and any learned artifacts that will be touched.
- [ ] Make one controlled change at a time.
- [ ] Capture before/after metrics and save representative diagnostics.
- [ ] Run the negative case as well as the happy path.
- [ ] Stop immediately if capture geometry or click coordinates are uncertain.
- [ ] Record the outcome and exact rollback step.

**Completion criteria**  
The workflow completes without unexplained warnings, safety gates remain active, and the recorded evidence matches the intended change.

### Playbook 05 — Investigate false positives

Save the clicked crop and full frame; identify which detection path produced it; note template identity and score; add negative sample; isolate same-color background; adjust segmentation/matching only after regression test.

**Checklist**

- [ ] Confirm the version and project root.
- [ ] Back up the current configuration and any learned artifacts that will be touched.
- [ ] Make one controlled change at a time.
- [ ] Capture before/after metrics and save representative diagnostics.
- [ ] Run the negative case as well as the happy path.
- [ ] Stop immediately if capture geometry or click coordinates are uncertain.
- [ ] Record the outcome and exact rollback step.

**Completion criteria**  
The workflow completes without unexplained warnings, safety gates remain active, and the recorded evidence matches the intended change.

### Playbook 06 — Investigate false negatives

Save frame with target location; track whether capture had object; inspect proposal count; check candidate box; verify exact matcher coverage; test scale/hue/facing; add a labeled fixture for that specific missed case.

**Checklist**

- [ ] Confirm the version and project root.
- [ ] Back up the current configuration and any learned artifacts that will be touched.
- [ ] Make one controlled change at a time.
- [ ] Capture before/after metrics and save representative diagnostics.
- [ ] Run the negative case as well as the happy path.
- [ ] Stop immediately if capture geometry or click coordinates are uncertain.
- [ ] Record the outcome and exact rollback step.

**Completion criteria**  
The workflow completes without unexplained warnings, safety gates remain active, and the recorded evidence matches the intended change.

### Playbook 07 — Recover after a crash

Do not relaunch repeatedly; inspect for leftover child process; preserve logs; confirm whether model/config was written; back up data; validate archive integrity; restart Preview and check counters.

**Checklist**

- [ ] Confirm the version and project root.
- [ ] Back up the current configuration and any learned artifacts that will be touched.
- [ ] Make one controlled change at a time.
- [ ] Capture before/after metrics and save representative diagnostics.
- [ ] Run the negative case as well as the happy path.
- [ ] Stop immediately if capture geometry or click coordinates are uncertain.
- [ ] Record the outcome and exact rollback step.

**Completion criteria**  
The workflow completes without unexplained warnings, safety gates remain active, and the recorded evidence matches the intended change.

### Playbook 08 — Upgrade source without losing training

Stop all instances; copy data folders and config; record source revision; replace code as a unit; read migration notes; verify model/feature compatibility; run offline checks; compare model hash before/after.

**Checklist**

- [ ] Confirm the version and project root.
- [ ] Back up the current configuration and any learned artifacts that will be touched.
- [ ] Make one controlled change at a time.
- [ ] Capture before/after metrics and save representative diagnostics.
- [ ] Run the negative case as well as the happy path.
- [ ] Stop immediately if capture geometry or click coordinates are uncertain.
- [ ] Record the outcome and exact rollback step.

**Completion criteria**  
The workflow completes without unexplained warnings, safety gates remain active, and the recorded evidence matches the intended change.

### Playbook 09 — Build customer package

Use clean virtual environment; install build requirements; run build script; inspect spec and data files; check secret redaction; start packaged client on clean Windows profile; test hotkeys, popup and stop.

**Checklist**

- [ ] Confirm the version and project root.
- [ ] Back up the current configuration and any learned artifacts that will be touched.
- [ ] Make one controlled change at a time.
- [ ] Capture before/after metrics and save representative diagnostics.
- [ ] Run the negative case as well as the happy path.
- [ ] Stop immediately if capture geometry or click coordinates are uncertain.
- [ ] Record the outcome and exact rollback step.

**Completion criteria**  
The workflow completes without unexplained warnings, safety gates remain active, and the recorded evidence matches the intended change.

### Playbook 10 — Rotate exposed webhook

Revoke old webhook in provider UI; create replacement; update local secret storage; search repo/logs for the old token without copying it into output; clean git history as needed; verify sanitized logs.

**Checklist**

- [ ] Confirm the version and project root.
- [ ] Back up the current configuration and any learned artifacts that will be touched.
- [ ] Make one controlled change at a time.
- [ ] Capture before/after metrics and save representative diagnostics.
- [ ] Run the negative case as well as the happy path.
- [ ] Stop immediately if capture geometry or click coordinates are uncertain.
- [ ] Record the outcome and exact rollback step.

**Completion criteria**  
The workflow completes without unexplained warnings, safety gates remain active, and the recorded evidence matches the intended change.

### Playbook 11 — Tune frame rate

Measure capture, proposal, matching, learning and output independently; keep same room/size; vary one setting per run; collect p50/p95 tick ms; evaluate recall and false-positive rate; retain a named baseline.

**Checklist**

- [ ] Confirm the version and project root.
- [ ] Back up the current configuration and any learned artifacts that will be touched.
- [ ] Make one controlled change at a time.
- [ ] Capture before/after metrics and save representative diagnostics.
- [ ] Run the negative case as well as the happy path.
- [ ] Stop immediately if capture geometry or click coordinates are uncertain.
- [ ] Record the outcome and exact rollback step.

**Completion criteria**  
The workflow completes without unexplained warnings, safety gates remain active, and the recorded evidence matches the intended change.

### Playbook 12 — Review model quality

Group samples by source/session; check positives, negatives and quarantine; remove duplicates conservatively; split by scene/session; train offline; evaluate held-out positive recall and negative false-positive rate; promote only after checks.

**Checklist**

- [ ] Confirm the version and project root.
- [ ] Back up the current configuration and any learned artifacts that will be touched.
- [ ] Make one controlled change at a time.
- [ ] Capture before/after metrics and save representative diagnostics.
- [ ] Run the negative case as well as the happy path.
- [ ] Stop immediately if capture geometry or click coordinates are uncertain.
- [ ] Record the outcome and exact rollback step.

**Completion criteria**  
The workflow completes without unexplained warnings, safety gates remain active, and the recorded evidence matches the intended change.

### Playbook 13 — Troubleshoot webhook reporting

Validate URL locally without printing it; verify OCR executable; save toast ROI; test parser with sanitized strings; inspect HTTP response status; ensure reporter thread cannot block game loop.

**Checklist**

- [ ] Confirm the version and project root.
- [ ] Back up the current configuration and any learned artifacts that will be touched.
- [ ] Make one controlled change at a time.
- [ ] Capture before/after metrics and save representative diagnostics.
- [ ] Run the negative case as well as the happy path.
- [ ] Stop immediately if capture geometry or click coordinates are uncertain.
- [ ] Record the outcome and exact rollback step.

**Completion criteria**  
The workflow completes without unexplained warnings, safety gates remain active, and the recorded evidence matches the intended change.

### Playbook 14 — Troubleshoot popup handling

Capture popup in several animation phases; compare template score; check cooldown/state; confirm action coordinates relative to client area; test each action in dry/mock mode; retain an emergency shutdown path.

**Checklist**

- [ ] Confirm the version and project root.
- [ ] Back up the current configuration and any learned artifacts that will be touched.
- [ ] Make one controlled change at a time.
- [ ] Capture before/after metrics and save representative diagnostics.
- [ ] Run the negative case as well as the happy path.
- [ ] Stop immediately if capture geometry or click coordinates are uncertain.
- [ ] Record the outcome and exact rollback step.

**Completion criteria**  
The workflow completes without unexplained warnings, safety gates remain active, and the recorded evidence matches the intended change.

### Playbook 15 — Prepare a support bundle

Copy sanitized logs, config without secrets, model hash (not necessarily model itself), version, screenshots, dimensions and concise reproduction; remove usernames, webhook URLs, chats and unrelated desktop content.

**Checklist**

- [ ] Confirm the version and project root.
- [ ] Back up the current configuration and any learned artifacts that will be touched.
- [ ] Make one controlled change at a time.
- [ ] Capture before/after metrics and save representative diagnostics.
- [ ] Run the negative case as well as the happy path.
- [ ] Stop immediately if capture geometry or click coordinates are uncertain.
- [ ] Record the outcome and exact rollback step.

**Completion criteria**  
The workflow completes without unexplained warnings, safety gates remain active, and the recorded evidence matches the intended change.

## State and data lifecycle reference

### Runtime state

- **Captured frame:** the current screenshot/crop and its width, height, capture timestamp and coordinate origin.
- **Proposal:** an image region that could contain a target. A proposal is not yet a detection.
- **Detection:** a proposal that passed the active template/model verifier.
- **Click attempt:** an action selected by policy after click budgets and safety gates.
- **Input sent:** the underlying input library accepted an event call; game success remains unproven.
- **Response evidence:** local disappearance, watcher change or OCR-reported reward associated with a time window.
- **Learned positive/negative:** training labels with their source and review state; these must be separated from mere click history.
- **Quarantined sample:** evidence retained but excluded from active inference/training until reviewed.

### Why each state needs its own counter

Counting proposals as detections exaggerates performance. Counting detections as clicks ignores safety gates. Counting input calls as rewards confuses OS delivery with game acceptance. Counting any image change as a reward confuses animation with success. Use separate counters and event names across every release.

### Recommended event schema

Each critical event should carry a timestamp, session ID, state, reason code, target/model ID when applicable, score, threshold, frame coordinate, screen coordinate, and code path (`fast`, `template`, `exploration`, `popup`, `manual-teach`). Credentials and full webhook URL must never appear.

### Persistence contracts

- Configuration stores operator preferences and tuning values.
- Seed images are maintained references; their original bytes should not be mutated as part of matching.
- Learned crops/weights represent training output and require backups and compatible feature metadata.
- Watcher images express state/reward patterns and must not enter the positive ghost class.
- Diagnostics are temporary evidence and should use a bounded retention policy.
- Import manifests connect remote assets to local files and need source URL/hash/version information.

## Source-derived behavior vs optional integrations

The inspected project has multiple snapshots/variants in the conversation. The presence of `smart_ghost.py`, `popup_dismiss.py`, or `webhook_reporter.py` beside an engine does not prove the specific engine imports or instantiates it. At startup, use capability logs and inspect imports in the launched `main.py`. Customer builds may intentionally disable training and exploration even where developer builds offer them.

### Verify what is active

1. Inspect the exact file path in the GUI log or process command line.
2. Run the source parser’s `--help` and compare it with the running EXE usage text.
3. Check startup logs for optional module health.
4. Verify the expected directories, watcher counts and model path are logged.
5. Confirm a customer session does not change the model checksum.
6. Inspect the build manifest to know which external data files are required.

## Documentation maintenance

### Updating after a code change

1. Change source and tests first.
2. Update the CLI section from the actual parser.
3. Update the configuration defaults from the dataclass and sample JSON.
4. Remove descriptions for deleted options and add migration notes for changed semantics.
5. Run documented examples in a clean working directory.
6. Rebuild all supported release artifacts.
7. Verify headings, code fences, relative links and line count.
8. Review the README for secrets, user paths, unsupported performance claims and stale version numbers.
9. Record which checks actually passed and on what environment.

### Suggested pull-request template

- [ ] Source and tests updated.
- [ ] CLI help compared with docs.
- [ ] Config schema/defaults compared with docs.
- [ ] Example paths tested with spaces and Unicode.
- [ ] No credentials or personal data committed.
- [ ] Windows-specific validation is clearly distinguished from mocked/Linux validation.
- [ ] Model/version compatibility verified.
- [ ] All release files are present.
- [ ] README line count and links checked.

## Final accuracy statement

This README is a documentation artifact based on the inspected local source files and the public repository listing on the documentation date. Repository contents and project snapshots can change. Treat code, CLI help, runtime logs and the release manifest as authoritative for the exact version in use. If a feature described here is not imported by the version you run, it is not active in that build; wire it in and test it before claiming support.

---

# Engineering hardening addendum (2026-10-11)

This addendum describes the hardening patches included with the reviewed source bundle.
The root README remains intentionally extensive; this short section supersedes older counts
where the source schema changed after the original generated reference was written.

## Current configuration schema additions

The current inspected `Config` dataclass has 106 fields. The detailed legacy reference
above documents the earlier 102-field schema; the four fields below were added afterward.
The actual `main.py` dataclass and current `config.json` remain the runtime authority.

### `smart_min_negative_samples`

Minimum local negative examples required before an *unvalidated, locally trained* model
can be treated as ready. This prevents a model trained only on examples labelled as ghosts
from being used as if it had learned the difference between ghosts and background objects.
The current default is 8, and config loading clamps it to a supported range.

### `smart_min_validated_train_rows`

Minimum reported training-row count required for a packaged pre-trained model to qualify
for inference when its original source samples are not present on the client machine. The
current default is 100. This is a practical readiness gate, not cryptographic proof that
metrics are authentic or that a model generalizes to a new room.

### `smart_min_validated_precision`

Minimum saved holdout precision accepted by the model-readiness gate. The current default
is 0.85. Precision estimates how many predicted ghost targets were true positives on the
reported validation set. It does not promise the same precision in a different room or
under a different display scale.

### `smart_min_validated_recall`

Minimum saved holdout recall accepted by the model-readiness gate. The current default is
0.85. Recall estimates the portion of labelled ghosts found by the model on the reported
validation set. Higher recall can increase detections but must be balanced against false
positives.

## Security and default-profile notes

The review package intentionally sets `webhook_url` to an empty string. Configure a webhook
through the GUI or `BLOOP_WEBHOOK_URL` in the local environment. A webhook token previously
included in a supplied configuration should be considered exposed and rotated before further
use. Never commit an actual Discord webhook to Git.

The reviewed sample `config.json` also uses a 5,000-click session cap and at most four clicks
per frame. These are safer starting defaults for a newly extracted copy. Adjust them only
after preview and live tests show that targets are correctly localized. The bot's click rate,
per-frame budget and session cap are distinct controls: each constrains a different failure
mode.

## Hardening changes in this bundle

- Model NPZ archives are loaded defensively and are not partially applied to an active model
  if dimensions or numeric values fail validation.
- Model writes use a temporary file and atomic replacement, creating parent directories as
  needed. A failed save is logged instead of silently pretending that persistence succeeded.
- Feature preprocessing uses a bounded LRU cache whose identity incorporates file path,
  file modification time, file size, augmentation parameters and reference height.
- Model training input is checked for shape consistency, finite values, valid labels and
  usable class balance before fitting.
- Class/group splitting avoids needlessly placing the only positive source group exclusively
  in the validation fold when there is not enough class diversity to do that safely.
- A validated pre-trained model can be used without distributing private raw sample images,
  but locally trained models still need both positive and negative data before readiness.
- Discord webhook URLs and token-shaped path fragments are redacted from known HTTP error
  logging paths and the GUI's webhook-test error output.
- Environment-provided webhook configuration takes precedence over the file setting.
- OCR reward tracking can initialize even when Discord posting is disabled, when that feature
  is enabled and the OCR runtime is available.
- The template pipeline avoids preparing expensive exact-match frame representations when
  a ready exclusive smart detector owns target selection.
- Regression tests exercise model corruption, round-trip persistence, feature-cache isolation,
  moving-track continuity, OCR count parsing, template coordinate accuracy and secret redaction.

## What these changes do not prove

A unit test proves only the property it actually exercises. Synthetic sprites and a virtual
Tk screen do not constitute a representative Highrise benchmark. The saved values in a model
archive are metadata, not an independent reproducible evaluation unless its held-out labels
and evaluation procedure are also available. Windows capture, overlay coordinates, foreground
window checks, actual mouse delivery, popup dismissal and OCR still require a controlled test
on a Windows PC with Highrise open. Refer to `ENGINEERING_REVIEW.md` and `TEST_REPORT.md` for
the tested scope and known limitations.


## Windows contributor quick-start (review pack)

On Windows, use Python 3.11 for the closest match to the tested project assumptions. Double-click
`setup_dev.bat` to create a project-local `.venv` and install the dependency ranges, then run
`run_tests.bat` before editing. `launch_gui.bat` opens the developer panel with a visible console
for diagnosing startup problems. If a test fails, preserve the complete output and attach the
latest log rather than resetting learned data. The scripts never delete seeds, model weights or
training samples.

The sample configuration shipped with this review pack is intentionally safer than the older
configuration: no Discord webhook is embedded, the session click cap is finite, and the maximum
per-frame click count is reduced. To merge the code into an existing installation, back up the
whole project and copy source files deliberately; retain your local `seeds/`, `learned/`, `ok/`,
`smart/positives/`, `smart/negatives/`, `smart/quarantine/`, and `corpus/` data unless you intend
to replace them.
