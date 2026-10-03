# Changelog

## [Unreleased]

### Fixed

- An edit that keeps the same file size is uploaded on the next pass. The upload decision used to stop at "same number of bytes", so a change such as AAAA to BBBB never left the machine unless `--verify-hash` was on and the remote listing included a SHA-1. The last successful folder signature is now a per-file baseline (name, size, modification time). When that baseline does not match, the remote SHA-1 is compared if the listing has one, then the revision's claimed modification time (within 2 seconds). If none of those show the file is unchanged, it is uploaded. After a failed batch, an older remote file of the same size is no longer treated as the file that just uploaded. Existing cache files still load, and their signature format is unchanged. A cache entry from before the envelope format (`{"sig": ...}`) has no baseline, so equal-size files in that folder are checked again once; unchanged folders are still skipped. No settings change and no cache reset is required.

### Added

- `docs/change-detection.md` explains when a file is uploaded again, including the case an edit keeps both the size and the modification time.
- `PROTON_SYNC_SETTINGS`, read when `config.py` and `i18n.py` are imported. When it is set to a non-empty path, that file is the settings file. When it is unset or empty, settings stay at `settings.json` next to the scripts, as before. Existing installs that do not set the variable need no migration. Tests use it so they never write the repository's `settings.json`.
