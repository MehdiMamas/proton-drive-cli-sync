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
