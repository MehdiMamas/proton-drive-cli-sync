# Changelog

## [Unreleased]

### Changed

- The mapping dialog explains each deletion choice under the control: whether a local delete is sent to Proton, that removed files go to the Proton trash, and whether the folder is on a network drive or an internal disk. The trash choice and the disk choice are separate. Picking the disk no longer clears the trash selection on screen. Migration: none.
- The project is presented as two-way sync maintained in this repository. It was forked from lafontaj/proton-drive-cli-sync and is not sent upstream as a pull request. A new mapping defaults to two-way. A mapping that was already saved without `"direction": "twoway"` stays upload-only until you change it. Migration: none for existing mappings.

## [2.2.0] - 2026-10-05

Trial build for a real Proton account. Existing mappings stay upload-only until `"direction": "twoway"` is set. Checked with the fake CLI (`165 passed`), not against Proton.

### Added

- A mapping can opt in with `"direction": "twoway"`. Mappings without that key stay upload-only. A two-way pass lists the remote folder even when the local fingerprint is unchanged, uploads a local-only edit, downloads a remote-only edit into a temporary file and replaces the local file only after that download exits 0, and writes a ` (proton conflict)` copy when both sides changed. Nothing is deleted on a conflict. A local file whose remote copy disappeared is moved into `holding/` under the data directory. A failed listing does not update the sync database for that folder and the pass exits 5. Migration: no change unless you add the key.
- Remote changes on a two-way mapping are picked up by the existing real-time consumer, every `poll_minutes` (default 5), by running the same engine pass. There is no separate daemon and no per-second remote sync. The nightly timer is still that same pass. Migration: none.
- The Qt mapping dialog can set direction to upload or two-way. Two-way keeps both copies when both sides change, and the shared-folder deletion warning is the same confirmation the engine already requires. The sidebar stays "Unofficial one-way backup" until a mapping is two-way. The Tk editor does not offer the control; saving there keeps the key. Migration: none until you choose two-way.
- `cloudproviders.py` exports sync-database status on the session bus for Nautilus and Nemo (`org.freedesktop.CloudProviders` account status, plus `GetFileStatus`). It does not call the Proton CLI and does not change files. Nautilus shows one status per mapping folder, not an emblem on each file. The registration file `packaging/proton-drive-sync-cloud.desktop` is not installed by the package. Migration: none; nothing starts the service for you.

## [2.1.0] - 2026-10-05

### Added

- PySide6 window (`python -m ui`): sidebar, mappings, schedule, real-time and configuration, in separate cards, with the previous toolbar icons on the sidebar and the mapping actions. Dropdowns use a chevron and a padded menu. It is unofficial one-way backup, not a Drive file browser. The tray icon and the Arch launcher `proton-drive-sync-gui` open this window. `python3 proton_mapping_editor.py` still opens the previous Tk editor. Headless sync does not import Qt. Migration: install PySide6 (`pyside6` on Arch, already a package dependency).

### Fixed

- A pass no longer asks Proton whether every ancestor of a folder exists when this pass has already seen, created, or listed that folder. The next full pass makes fewer CLI calls. No settings change is required. A failed direct listing is not treated as an empty folder: the engine falls back to the level-by-level check, then lists again. A listing that still fails skips that folder and exits 5, as before.

## [2.0.0] - 2026-10-03

Collects phases 2 to 6 of the fork: change detection, honest exit codes, deletion safety, headless defaults, Arch packaging. Tag creation is a human step after merge.

### Added

- Mass-deletion guard: in one remote folder, a pass that would trash at least 20 items and more than half of the folder's remote children trashes nothing there, prints `[delete-guard]`, counts `deletions_refused` in `[run-result]` and exits 5. Thresholds: `max_delete_min` and `max_delete_ratio` in `settings.json`, overridable per mapping. `--allow-mass-delete` turns the guard off for one run.
- The mount guard is re-checked before each folder's deletions. If it fails mid-pass, deletions stop for the rest of that mapping (uploads continue) and the pass exits 5.
- Arch packaging in `packaging/arch/` (`proton-drive-cli-sync-git`): program files in `/usr/lib/proton-drive-cli-sync/`, launchers `proton-drive-sync`, `proton-drive-sync-gui` and `proton-drive-sync-doctor` in `/usr/bin/`, desktop entry and icon. Nothing writable is installed.
- `proton-drive-sync-doctor [--redact]` (`doctor.py`): read-only report of CLI resolution and version, systemd units and last results, `last-run.json` and `health.json`, effective settings, per-mapping safety options and session facts for unattended auth. It does not import `config` or `schedule_manager`, so it does not rename `~/.proton_sync` or copy settings. `--redact` hides e-mails and personal paths, including paths that contain spaces. It always exits 0.
- `VERSION` (2.0.0), `SECURITY.md`, `docs/RELEASING.md`, and a fork notice and disclaimer at the top of `README.md`.
- The engine prints a `[run-result]` JSON line as the last line of a pass (including a clean exit 0), and a translated summary line just before it. `Done.` is still printed when the loop finishes (exit 0 or 5). `last-run.json` in the data directory records `last_full` and `last_subpath` separately, so a subpath run does not erase the last full pass. It is written for exits 0, 2, 4 and 5, not for lock contention (exit 1) and not for a dry-run.
- `python3 schedule_manager.py --refresh-units` rewrites the user service and timer from the mappings path, calendar and `--delete` flag already installed, and adds `RestartPreventExitStatus=5`.
- `docs/change-detection.md` explains when a file is uploaded again, including the case an edit keeps both the size and the modification time.
- `PROTON_SYNC_SETTINGS`, read whenever settings are loaded. When it is set to a non-empty path, that file is the settings file. When it is unset or empty, the XDG path above is used. Tests set it so they never write the repository's `settings.json`.
- GUI run logs (`sync-*.log` from Run, Prime and Reset) are written under `~/.proton-drive-sync/logs/`, so a packaged install can start a sync from the GUI.

### Changed

- A headless run no longer renames local extensions when the CLI is 0.5.0 or newer, unless settings say so. `rename_ext_enabled: false` stays off. `rename_ext_enabled: true` together with `rename_ext_auto_disabled: true` stays on (that is the GUI's "I turned it back on" flag). A missing key, or `true` without that flag, follows the CLI: off from 0.5.0, on for an older or unknown CLI. `--no-rename-ext` still forces off for one run. The engine does not write these keys. Opening the GUI still performs the one-time notice and records the flag.
- Settings now live at `$XDG_CONFIG_HOME/proton-drive-sync/settings.json` (`~/.config/proton-drive-sync/settings.json` when `XDG_CONFIG_HOME` is unset). `PROTON_SYNC_SETTINGS` still wins when it is set. If only the old file next to the scripts exists, it is copied once to the new path (mode 0600) and left in place. If that directory cannot be created, the old file is read and a line is printed on stderr. A fresh install creates the new path on the first write.
- `proton-drive` is resolved in this order: `PROTON_DRIVE_CLI`, the `proton_cli_path` setting, `proton-drive` next to the scripts when that file is executable, then `proton-drive` on `PATH`. The CLI version cache is `cli-version.json` inside `~/.proton-drive-sync/`.
- Remote copies of excluded items are now kept by default. Before, adding an exclusion and running with `--delete` sent the already-uploaded copy to the Proton trash. The new mapping key `excluded_remote` is `"keep"` (default) or `"prune"`. Migration: nothing to do to get the safer behavior; set `"excluded_remote": "prune"` on a mapping to get the old behavior back. Unknown values act as `"keep"` and print a warning. The mapping editor now keeps keys it does not edit (`excluded_remote`, `max_delete_*`) when you edit a mapping.
- `mappings.example.json` no longer shows `"delete_mode": "permanent"`; the CLI only trashes, so the example uses `"trash"`. `--subpath` help no longer calls it purely additive.
- Generated systemd units quote and escape paths. In `ExecStart=` arguments, spaces, quotes and backslashes are quoted, `%` becomes `%%` and `$` becomes `$$`. `Environment=` doubles `%` and escapes `\` and `"`, and does not change `$` (systemd does not expand `$` there). A packaged install writes `ExecStart=/usr/bin/proton-drive-sync ...` so units survive upgrades. The readers (`read_service_mappings_path`, `read_service_delete`, `read_units_mappings_path`) accept both the new form and units written by older versions. Migration: nothing required; run `python3 schedule_manager.py --refresh-units` (or save in the GUI) once to rewrite old units.

### Fixed

- A pass that finished with failed uploads, a failed remote listing, an unreadable folder, a missing source, a failed trash, or a folder skipped after repeated stalls used to exit 0. systemd and the real-time consumer treated that as success, and the consumer deleted the markers for work that never reached Drive. The pass now exits 5. Exit codes 0–4 are unchanged. Code 3 (a cold `--subpath`, nothing attempted) still wins over 5. Dry-run uses the same rule and does not write `last-run.json`. Existing systemd units do not contain `RestartPreventExitStatus=5` until they are rewritten: run `python3 schedule_manager.py --refresh-units` once per user so a partial failure shows as a failed unit and is not restarted six times an hour. The next timer or the real-time cycle retries it. The real-time consumer now waits 60 seconds, then 120 seconds, doubling up to 30 minutes, before relaunching a target that exited 1, 5, or another non-success code. A later success resets that wait. Exit 2 is unchanged and does not use this wait. The GUI shows "finished with failures (code 5)" for that exit, as a warning rather than a crash or a success.
- An edit that keeps the same file size is uploaded on the next pass. The upload decision used to stop at "same number of bytes", so a change such as AAAA to BBBB never left the machine unless `--verify-hash` was on and the remote listing included a SHA-1. The last successful folder signature is now a per-file baseline (name, size, modification time). When that baseline does not match, the remote SHA-1 is compared if the listing has one, then the revision's claimed modification time (within 2 seconds). If none of those show the file is unchanged, it is uploaded. After a failed batch, an older remote file of the same size is no longer treated as the file that just uploaded. Existing cache files still load, and their signature format is unchanged. A cache entry from before the envelope format (`{"sig": ...}`) has no baseline, so equal-size files in that folder are checked again once; unchanged folders are still skipped. No settings change is required. A cache reset is not required for the new code to run, but it is not enough on its own: an earlier version already recorded equal-size edits as synced, because it wrote the folder signature after skipping those files. After upgrading, run one pass with `--ignore-cache` so every folder is listed and those files are compared with Drive (remote SHA-1, or the claimed modification time). Without that pass, Drive can keep the old bytes and a normal run will not look again.
