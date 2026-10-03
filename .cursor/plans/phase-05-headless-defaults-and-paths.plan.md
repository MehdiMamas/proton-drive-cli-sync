---
name: "Proton Drive Sync Phase 5 – Headless defaults and file locations"
overview: "Phase 5 of 6. Headless defaults and file locations. Scope is limited to this phase; finish when the gate passes, record evidence in PROGRESS.md and stop. Gate: `wsl -- bash scripts/test.sh` exits 0 with 0 failed and 0 xfailed."
todos:
  - id: p05-0-preflight
    content: "Preflight: read PROGRESS.md, confirm the active phase is 5 and the Phase 4 gate is recorded with command output; read PROTON_DRIVE_SYNC_MASTER_PLAN.md §3, §4, §8"
    status: pending
  - id: p05-1-task
    content: "config.effective_rename_ext shared by engine and GUI (task 1)"
    status: pending
    dependencies: [p05-0-preflight]
  - id: p05-2-task
    content: "paths.py, settings migration, config/i18n switch (task 2)"
    status: pending
    dependencies: [p05-1-task]
  - id: p05-3-task
    content: "CLI version cache path, CLI discovery order, path mentions (task 3)"
    status: pending
    dependencies: [p05-2-task]
  - id: p05-4-task
    content: "Symlink documentation (task 4)"
    status: pending
    dependencies: [p05-3-task]
  - id: p05-5-task
    content: "Remove the last xfail marker (task 5)"
    status: pending
    dependencies: [p05-4-task]
  - id: p05-6-task
    content: "CHANGELOG (task 6)"
    status: pending
    dependencies: [p05-5-task]
  - id: p05-8-gate
    content: "Verify gate: `wsl -- bash scripts/test.sh` exits 0 with 0 failed and 0 xfailed"
    status: pending
    dependencies: [p05-6-task]
  - id: p05-9-handoff
    content: "Record gate evidence in PROGRESS.md, mark Phase 5 complete there, open the PR and run the review loop, then hand off with `next-phase.sh` (new headless session) and stop"
    status: pending
    dependencies: [p05-8-gate]
---

# Phase 5 – Headless defaults and file locations

> Part of the Proton Drive Sync roadmap: [`00-roadmap.plan.md`](00-roadmap.plan.md). Spec: `PROTON_DRIVE_SYNC_MASTER_PLAN.md` §3, §4, §8. Rules in `.cursor/rules/` are binding, especially `05-phase-discipline.mdc` and `10-engine-safety.mdc`.

**Phase 5 of 6.** Previous: Phase 4 – Deletion and exclusion safety. Next: Phase 6 – Arch packaging, safe units, diagnostics, public release.
Branch `phase-05-headless-defaults-and-paths`. Commit subject: `fix(phase-05): same defaults headless and in the GUI; settings under ~/.config`. Depends on: phase 4.
Line numbers below refer to upstream commit `5a852e2`. Earlier phases shift them, so locate code by function name.

## Before you start
- `PROGRESS.md` must say the active phase is **5**. The Phase 4 gate must be recorded with command output. If it is not, stop and tell the user.
- Read the cited spec sections in full.
- Look at the code that already exists. Build on it instead of re-creating it. If the code differs from this plan, follow the code and note the difference in `PROGRESS.md`.

## Problems

1. **Extension renaming headless.** `config.DEFAULTS["rename_ext_enabled"] = True`. Only the GUI
   (`proton_mapping_editor._maybe_disable_rename_ext`, ~L1363) turns it off once for CLI ≥ 0.5.0. A machine that only runs
   the systemd timer (never opened the GUI) keeps **renaming the user's local files** (`IMG.JPG` → `IMG.jpg`) for a
   workaround that is obsolete.
2. **Settings live beside the scripts** (`APP_DIR/settings.json` in `config.py` and `i18n.py`). That breaks a packaged,
   read-only install (`/usr/lib/...`) and mixes user data with program files.
3. **Leftover legacy paths:** `CLI_VERSION_CACHE = ~/.proton_sync/cli-version.json` in `proton_sync.py`, docstrings and
   README sections mentioning `~/.proton_sync_cache/` etc. (`config.DATA_DIR = ~/.proton-drive-sync` is the real one).
4. **CLI discovery:** without env/setting, the default is `APP_DIR/proton-drive`. A packaged install needs `PATH` lookup.
5. **Symlink behavior** is implemented but undocumented (file symlinks uploaded as their target's content; directory symlinks not followed).

## Design

### Effective rename-ext default (single source of truth)
`config.effective_rename_ext(cli_supports_fix)` where `cli_supports_fix` is a zero-arg callable (the engine passes
`cli_supports_shared_delete`, the ≥ 0.5.0 check the GUI already uses):
- `rename_ext_enabled` explicitly `False` in `settings.json` → off.
- `rename_ext_enabled` explicitly `True` **and** `rename_ext_auto_disabled` is `True` → on (the user re-enabled it after the GUI's one-time migration; that is a deliberate choice).
- Otherwise (key absent, or `True` without the migration flag, which may just be an old default the GUI wrote) → `False` if
  `cli_supports_fix()` is True, else `True` (old CLI still needs the workaround; unknown version → True, as today).
- The engine never writes these settings (read-only decision). Verify by reading the GUI how it writes them and adjust
  this rule if the GUI stores defaults differently; record what you found in `PROGRESS.md` under Notes / decisions.
- `--no-rename-ext` still forces off for one run.
The engine's computation of `effective_rename_ext` in `main()` uses it. The GUI's `_maybe_disable_rename_ext` keeps
its one-time notice but must not contradict the helper (refactor to share the decision; keep the dialog).

### Settings location
New small module `paths.py` (no imports from `config`/`i18n`, to avoid cycles) with `settings_path()`:
1. `PROTON_SYNC_SETTINGS` env (phase 1 seam) if set;
2. else `$XDG_CONFIG_HOME/proton-drive-sync/settings.json` (default `~/.config/...`) **if it exists**;
3. else, if legacy `APP_DIR/settings.json` exists → **migrate**: copy it atomically to the XDG path (create dirs, mode 0600),
   leave the legacy file in place, print one line (stderr, translated) once. Use the XDG path from then on;
4. else the XDG path (created on first write).
`config.py` and `i18n.py` both use `paths.settings_path()`. If a process cannot write the XDG dir, fall back to reading
the legacy file and say so. Never crash at import.

### Paths cleanup
- `CLI_VERSION_CACHE` → `os.path.join(config.DATA_DIR, "cli-version.json")` (keep the no-config fallback branch consistent).
- Update the engine module docstring and README path mentions to `~/.proton-drive-sync/` and `~/.config/proton-drive-sync/settings.json`.
- `config.resolve_proton_cli()`: env → setting → `APP_DIR/proton-drive` **if usable** → `shutil.which("proton-drive")` →
  `APP_DIR/proton-drive` (returned for the error message as today). Same order documented in the docstring and README.

### Symlinks: document, don't change
Add a "Symbolic links" section to `docs/change-detection.md`: file symlinks are uploaded as the target's content (target
may be outside the mapping), directory symlinks are skipped, broken links are ignored. Tests pin it.

## Scope (do these, nothing else)

### Tasks

1. `config.effective_rename_ext` + engine use + GUI refactor (no dialog text change).
2. `paths.py` + migration + `config.py`/`i18n.py` switch.
3. CLI version cache path, CLI discovery order, docstring/README path fixes.
4. Symlink docs.
5. Flip xfail `test_headless_run_does_not_rename_extensions_on_modern_cli`.
6. CHANGELOG: **Changed:** headless runs no longer rename extensions with CLI ≥ 0.5.0 unless enabled; settings moved (auto-migrated); CLI found on PATH.

### Required tests

Each must assert the behavior and fail on the code before this phase (say how you checked in the PR).

- `test_headless_run_does_not_rename_extensions_on_modern_cli` (flipped)
- `test_explicit_rename_ext_true_after_migration_is_honored_headless` (`enabled: true`, `auto_disabled: true`)
- `test_rename_ext_true_without_migration_flag_uses_version_default`
- `test_explicit_rename_ext_false_is_honored_on_old_cli`
- `test_old_cli_keeps_rename_ext_default_on` (fake `--version` 0.4.0)
- `test_settings_env_override_wins`
- `test_settings_migrated_from_legacy_once` (legacy file copied, content identical, legacy untouched, mode 0600, second import does not re-copy or re-print)
- `test_settings_xdg_preferred_when_both_exist`
- `test_unwritable_xdg_falls_back_to_legacy_read` (chmod the parent; skip if root)
- `test_i18n_and_config_agree_on_settings_path`
- `test_cli_version_cache_under_data_dir`
- `test_cli_found_on_path_when_no_setting` (fake on a tmp PATH dir, no env/setting, `APP_DIR/proton-drive` absent)
- `test_symlink_semantics_documented` (file symlink uploaded, dir symlink skipped, broken link ignored; may reuse the phase-01 characterization)

### Acceptance criteria

- **AC-1** With no explicit setting and CLI ≥ 0.5.0, neither the timer path nor the GUI path renames local files.
- **AC-2** Explicit user settings always win. Old CLI keeps the workaround on by default.
- **AC-3** Fresh installs write settings only under `~/.config/proton-drive-sync/`. Existing installs are migrated without losing any key, and the old file is left untouched.
- **AC-4** No runtime code references `~/.proton_sync` paths except `config.py`'s explicit legacy-migration constants.
- **AC-5** `proton-drive` is found on `PATH` when nothing else is configured.
- **AC-6** CHANGELOG and docs updated. Symlink behavior documented.
- **AC-7** Full suite green, **zero** xfails left.

## Out of scope (do NOT start these, even partially)
- Phase 6 – Arch packaging, safe units, diagnostics, public release → `phase-06-arch-packaging-release.plan.md`
- Everything in later phases (see `00-roadmap.plan.md`)
- Packaging, systemd unit paths (phase 6). New settings UI.

Do not create files, services, stubs, settings or UI that belong to a later phase. If something here seems to need later-phase work, write the smallest thing that unblocks this phase, then add a note under "Deferred" in `PROGRESS.md`.

## Gate
**`wsl -- bash scripts/test.sh` exits 0 with 0 failed and 0 xfailed.**

Prove it: run the command, and paste the command and its result (exit code, the pytest summary line) into Phase 5's row in `PROGRESS.md`. Name the OS that ran it (e.g. `Ubuntu 24.04 on WSL2, Windows 11`, from `wsl -- grep PRETTY_NAME /etc/os-release`). Anything not run (real Proton account, real systemd, Arch) is written as not run, with who runs it.

## When the gate passes
1. Mark every todo in this file `completed`.
2. In `PROGRESS.md`: mark Phase 5 done with the date and evidence, and set the active phase to **6**.
3. Commit with a conventional message scoped `phase-05`, push branch `phase-05-headless-defaults-and-paths`, open the PR, and run the review loop in `.cursor/skills/phase/SKILL.md`.
4. **Hand off** after the merge: run `bash .cursor/skills/phase/next-phase.sh`, report the PR URL and its `NEXT:` line, and stop. Never start the next phase in the same chat.

## Manual test (for the human)

On the Linux machine: `ls ~/.config/proton-drive-sync/settings.json` after first run (migrated). Put `TEST.JPG` in a
mapped folder, run the timer service, confirm the local name is unchanged.
