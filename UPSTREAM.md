# Upstream

- Upstream: https://github.com/lafontaj/proton-drive-cli-sync (remote `upstream`)
- Forked at: `5a852e218d353209a3b39cabdb4b810d0f254177` (2 October 2026), the commit `PROTON_DRIVE_SYNC_MASTER_PLAN.md` reviewed
- License: MIT (upstream copyright kept)

Every upstream file this fork changes is listed here, so changes can be reviewed against upstream and offered back as
separate pull requests. New files added by the fork are not listed.

| File | Phase | Why |
|---|---|---|
| `config.py` | 1 | `PROTON_SYNC_SETTINGS` selects the settings file at import, so tests and phase 5 packaging can leave `APP_DIR/settings.json` untouched |
| `i18n.py` | 1 | Same override. `config.py` reads and writes settings through `i18n` when that module is present, so both paths have to follow the variable |
| `proton_sync.py` | 2 | Equal-size edits were skipped. `upload_decision` uses the cached folder signature as a per-file baseline, then the remote SHA-1, then `claimedModificationTime` |
| `config.py` | 3 | `LAST_RUN_FILE` (`last-run.json` in the data directory) so the engine, and later readers, share one path |
| `proton_sync.py` | 3 | A pass with upload, listing, trash, unreadable-folder or missing-source failures exited 0. It now exits 5 and writes `[run-result]` plus `last-run.json` |
| `realtime_consumer.py` | 3 | Exit 0 was the only signal that markers could be deleted, so a partial failure was acknowledged. Exit 5 keeps markers and backs off |
| `schedule_manager.py` | 3 | A partial failure must show as a failed unit without a restart storm (`RestartPreventExitStatus=5`, `--refresh-units`) |
| `proton_mapping_editor.py` | 3 | Exit 5 was shown like any other non-zero code. The GUI now treats it as finished with failures |
| `proton_sync.py` | 4 | Exclusions trashed already-uploaded remote copies and nothing limited a mass deletion. Adds `excluded_remote`, the `[delete-guard]` mass-deletion guard, `--allow-mass-delete`, and a mount re-check per folder |
| `config.py` | 4 | `max_delete_min` and `max_delete_ratio` settings with typed getters |
| `realtime_consumer.py` | 4 | Names `deletions_refused` in the failure summary of a kept marker |
| `proton_mapping_editor.py` | 4 | Editing a mapping dropped keys the dialog does not know; they are carried over now |
| `README.md`, `README_fr.md`, `mappings.example.json` | 4 | Exclusion semantics, mass-deletion guard, `"permanent"` example replaced by `"trash"` |
| `config.py` | 5 | Headless extension default (`effective_rename_ext`) and CLI lookup on `PATH` after the bundled binary |
| `i18n.py` | 5 | Settings path follows `paths.settings_path()` (XDG, with a one-time copy from the legacy file) |
| `proton_sync.py` | 5 | Engine uses `effective_rename_ext`; CLI version cache lives in the data directory |
| `proton_mapping_editor.py` | 5 | One-time extension notice uses the same decision as the engine |
| `local_watcher.py`, `realtime_consumer.py`, `realtime_manager.py` | 5 | No-config fallbacks use `~/.proton-drive-sync` instead of the legacy split paths |
| `README.md`, `README_fr.md` | 5 | Current paths, settings location, CLI search order, and `paths.py` in the NAS file list |
| `INSTALLATION-realtime.md`, `INSTALLATION-realtime_fr.md` | 5 | NAS file list includes `paths.py`; queue, realtime.conf and settings paths |
| `INSTALLATION-systemd.md`, `INSTALLATION-systemd_fr.md` | 5 | Lock path is `~/.proton-drive-sync/proton_sync.lock` |
| `Temporary-files-exclusions.md`, `Temporary-files-exclusions_fr.md` | 5 | Extension rename is no longer the default on CLI ≥ 0.5.0; log path updated |
| `INSTALLATION-systemd.md` | 3 | Exit-code table and the `--refresh-units` step for units already installed |
| `schedule_manager.py`, `realtime_manager.py` | 6 | Unit text quotes and escapes paths (`unitexec.py`), packaged installs use `/usr/bin/proton-drive-sync`, readers accept quoted and legacy lines |
| `proton_mapping_editor.py` | 6 | GUI run logs and file dialogs no longer use a read-only packaged `APP_DIR` |
| `config.py` | 6 | `RUN_LOG_DIR` is `~/.proton-drive-sync/logs` |
| `README.md`, `README_fr.md` | 6 | File list names `unitexec.py` and `doctor.py`; run logs are under the data directory |
| `README.md`, `LICENSE`, `CHANGELOG.md` | 6 | Fork notice and disclaimer on top, fork contributors line, 2.0.0 section |
| `tray_indicator.py` | UI | The status icon opens `python -m ui` instead of the Tk editor |
