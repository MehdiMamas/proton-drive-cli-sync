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
| `INSTALLATION-systemd.md` | 3 | Exit-code table and the `--refresh-units` step for units already installed |
