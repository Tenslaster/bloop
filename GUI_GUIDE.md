# BLOOP Control Panel — Operator Guide

This guide describes the refreshed dark-themed developer GUI in `gui.py`.

## Design goals

- Keep the main operation buttons visible on every page.
- Make settings easier to find by separating focused pages from uncommon advanced options.
- Preserve access to every `main.Config` setting without crowding the first screen.
- Keep input-sensitive actions explicit and require a confirmation before live input starts.
- Keep the interface responsive while engine output is read by a background thread.
- Make long pages usable on smaller windows through the existing Canvas scrollbar, mouse wheel, Page Up/Page Down and Ctrl+Home/Ctrl+End navigation.

## Main layout

The application uses a dark navy background, high-contrast labels, green/cyan accents for normal activity, amber for warnings/unsaved state, red for live-input/danger controls, and a blue Save action. The layout has three persistent areas:

1. **Sidebar** — navigates between the eight pages. Ctrl+1 through Ctrl+8 selects the corresponding page.
2. **Page header** — shows the current page title and help text. Ctrl+K focuses the settings search.
3. **Command dock** — Preview, Start Live, Pause/Resume, Stop & Save and Save remain visible when changing pages. The status and saved/unsaved indicator stay in the dock.

The application starts maximized on larger displays, but uses a smaller resizable window on compact displays. The minimum intended window size is 900×600. Every page, including Overview and Advanced Settings, is scrollable.

## Page guide

### 1. Overview

Use this as the primary operating page. It contains the current engine state, FPS, detections, dispatched input count, auto-learning count, reward confirmations, uptime, Ectoplaz totals and quick links to logs, the latest detection overlay, the smart sample folder, Advanced Settings and configuration export.

Start with **Preview**. It must not dispatch real mouse input. Verify that the candidate boxes land on real ghosts before starting live input. Overview's Activity Log can be filtered, copied, cleared or saved.

### 2. Runtime & Speed

Contains the game-process selector, fallback title, capture method, client-area capture, focus/re-find behavior, click-under-game guard, OpenCV thread count, processing dimension, candidate budget, scan scheduling and recovery scan cadence.

Performance profiles:

- **Safe** raises thresholds, limits clicking and lowers processing load. It may miss more targets.
- **Balanced** uses moderate defaults for a desktop-class CPU.
- **Fast** increases work per frame and relaxes some thresholds. It may increase CPU usage and false positives.
- **Auto-tune for this PC** uses logical CPU count to suggest a starting point. It is a heuristic, not a benchmark of the actual game loop.

Applying a profile only edits the form. It does not save automatically, change the learned model or restart a running engine. Review and Save; then restart the bot to apply it.

### 3. Vision & Detection

Contains template confidence, minimum target size, target-instance limit, template scales, gray-scale proposal options, confirmation watcher threshold/scales, watcher cooldowns, reward-attribution window, adaptive threshold bounds, deduplication and score diagnostics.

Lower thresholds generally accept more candidates but can create more false positives. Higher thresholds generally reduce false clicks but may miss small, dim, rotated or differently colored ghosts. Change one parameter at a time and use Preview to evaluate it.

### 4. Learning & Safety

Contains exploration, response delay, blacklist, click-rate/session limits, same-location cooldowns, smart click-teaching, learned-model use, seed bootstrap, user-input yielding, sample auto-cleaning, classifier threshold, confirmation-frame count, aim lead and the `VagueComplete.png` popup handler.

Do not treat a click dispatch as proof that the game accepted a target. The engine has visual-response and watcher/reward evidence paths, but neither is a perfect oracle. If results look suspicious, pause or stop the engine and inspect the image overlay and log.

### 5. Model & Samples

Displays positive samples, negative samples and quarantined counts. It offers duplicate scans, the Sample Manager, auto-clean, retraining and folder access. Duplicate removal asks for confirmation because it deletes files. Back up the `smart/` folder before any manual corpus cleanup or retraining.

### 6. Rewards & Webhook

Configure a Discord webhook and inspect Ectoplaz totals, drop count, estimated per-hour rate and last gain. The webhook URL is masked by default. Reveal it only when required, clear it to disable posting, and use the test button to check delivery. The test message is an external action.

Never ship a personal webhook URL in a public ZIP or executable. Use an environment variable or a per-customer configuration. Rotate any webhook secret that has been posted in public or uploaded into a shared debugging channel.

### 7. Diagnostics

Controls separate console and file verbosity, log-file size, overlay output and score-log cadence. Quick links open the log folder, latest detection frame, toast OCR debug image and learned target folder. Repository importer tools download sources once; the live frame loop should not require network activity.

Use DEBUG file logs for diagnosis and INFO console logs for ordinary operation to avoid drowning important events. Hover hints update the page subtitle and do not create log lines.

### 8. Advanced Settings

Every `main.Config` field not already shown on a focused page is placed in grouped advanced sections. This page includes hotkeys, exclusion-zone JSON, scan cadence, unchanged-frame detection, training augmentation, model readiness metadata thresholds, Ectoplaz confirmation, retry behavior, candidate classification, large-target rules, diagnostic probing and the legacy webhook reporting interval.

`patient_mode` is not displayed as a second independent checkbox because it is the inverse representation of the focused page's **Enable auto-learning / explore** setting. Having both exposed independently would allow contradictory values. Search for “patient mode” to jump to that control.

Advanced Settings also offers:

- **Import config** — loads a JSON configuration into the form; it does not immediately save over your active config.
- **Export config** — saves the current parsed form values to a separate JSON file.
- **Restore defaults** — loads `main.Config()` defaults into the form after confirmation. It does not delete model/sample data.
- **Validate settings** — parses and normalizes the current values without persisting them.

For exclusion zones, use **Edit rectangles…** rather than editing a long JSON list in a small entry. Each zone has the form `[x, y, width, height]` relative to captured-frame coordinates.

## Search and keyboard shortcuts

- **Ctrl+K** — focus global settings search.
- Enter a user-facing label or internal config key such as `base_threshold`, `max_cps`, `window_process`, `smart_ecto_confirm` or `hk_pause`.
- **Up / Down / Enter / Escape** — navigate the settings search results.
- **Ctrl+S** — save settings.
- **Ctrl+1 … Ctrl+8** — navigate pages in sidebar order.
- **Page Up / Page Down** — scroll the active page; Ctrl+Home and Ctrl+End go to its top and bottom.
- **F9** and **F12** are engine hotkeys configured by `hk_pause` and `hk_quit`; their exact behavior is owned by the engine, not the Tk window.

## Start, pause, resume and stop

1. Save settings and start Preview.
2. Confirm the log has a valid capture, nonzero frame rate, and detections centered on real ghost targets.
3. Select Start Live. The GUI asks for explicit confirmation because real mouse input will be sent.
4. Use Pause/Resume when you need to interrupt automation. The GUI is protected from being selected as the game window; the engine also validates the target process/window and click point.
5. Use Stop & Save for a cooperative stop. The GUI attempts fallback termination only if the cooperative request times out.

A setting edit is marked **Unsaved changes · restart to apply**. Saving updates the file; most runtime settings do not alter an already-running process. Stop and restart to reliably apply changes unless a specific setting is documented as hot-reloadable.

## Window scaling and clipping

The layout dynamically wraps descriptive captions to fit their settings cards. The active page scrolls vertically when it exceeds the viewport. On Windows, test 100%, 125% and 150% display scaling if a platform-specific font or theme changes the measured widget sizes. If a control appears inaccessible, first resize/maximize the window, verify the correct page, and use the scrollbar or keyboard navigation.

## Troubleshooting

### GUI opens but the engine never starts

Check the log panel, interpreter path, installed requirements and `logs/gui_startup.log`. Confirm the source modules are beside `gui.py`. An older compiled EXE does not inherit fixes made in Python source files.

### Live mode reports no capture

Restore Highrise, confirm the executable is correct (usually `highrise.exe`), check the capture dependencies and inspect the foreground-window guard message. Do not remove the foreground safety guard to conceal capture errors.

### There are detections but no clicks

Review whether Preview/dry-run is active, whether the engine is paused, whether a popup watcher is blocking clicks, whether click limits are reached, and whether the foreground/window/point guards rejected dispatch. A detection is not the same as a permitted input.

### It clicks the same target repeatedly

Stop live mode and inspect the image overlay. Check the target source/template name, the location cooldown and the model's response evidence. Do not lower thresholds or raise click-rate limits before confirming that the detected boxes correspond to the ghost sprites.

### Applying a profile appears to do nothing

Profiles edit the form and mark it unsaved. Click Save, then stop and start the engine. The actual processing time also depends on capture resolution, overlays, scene complexity, and other running applications.

### Settings fail to save

Use Validate Settings first. The editor reports parsing/normalization errors. List fields use comma-separated values, except exclusion zones, which use the JSON editor. Export the current configuration to a separate file before trying Restore Defaults.

## GUI verification limits

The layout is smoke-tested under Xvfb at a regular size and at a 900×600 viewport. This proves the Tk widgets can initialize, the pages can be reached, the advanced settings page has a scroll range, the command dock remains visible, and all config fields are represented. It does not substitute for testing Windows DPI scaling, mouse driver behavior or live Highrise capture on the deployment PC.
