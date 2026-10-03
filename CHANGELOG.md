# Changelog

## Unreleased

### Added

- `PROTON_SYNC_SETTINGS`, read when `config.py` and `i18n.py` are imported. When it is set to a non-empty path, that file is the settings file. When it is unset or empty, settings stay at `settings.json` next to the scripts, as before. Existing installs that do not set the variable need no migration. Tests use it so they never write the repository's `settings.json`.
