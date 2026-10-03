# Proton Drive Sync build progress

Read this file **before** any work. It is the single source of truth for which phase is active. Rules: `.cursor/rules/05-phase-discipline.mdc`. Roadmap: `.cursor/plans/00-roadmap.plan.md`.

**Active phase:** 6 – Arch packaging and release (not started) → `.cursor/plans/phase-06-arch-packaging-release.plan.md`
**Next:** none (phase 6 is the last planned phase)

| Phase | Plan | Status | Gate evidence | Date |
|---|---|---|---|---|
| 1 | `phase-01-test-harness.plan.md` | completed | `wsl -- bash scripts/test.sh` exit 0: `28 passed, 7 xfailed in 12.70s` (0 failed, 0 xpassed). `git diff origin/main -- proton_sync.py` empty. Ubuntu 26.04.1 LTS on WSL2, Windows 11. Not run: real Proton account, real systemd, Arch (human, after phase 6). | 2026-10-03 |
| 2 | `phase-02-equal-size-edits.plan.md` | completed | `wsl -- bash scripts/test.sh -ra --tb=line` exit 0: `40 passed, 4 xfailed in 14.91s` (0 failed, 0 xpassed). The 4 xfailed are phase 3 (upload and subpath exit codes), phase 4 (exclusion plus delete), and phase 5 (headless extension rename). Ubuntu 26.04.1 LTS on WSL2, Windows 11. Not run: real Proton account, real systemd, Arch (human, after phase 6). | 2026-10-03 |
| 3 | `phase-03-run-results.plan.md` | completed | `wsl -- bash scripts/test.sh` exit 0: `63 passed, 2 xfailed in 23.67s` (0 failed, 0 xpassed). The 2 xfailed are phase 4 (exclusion plus delete) and phase 5 (headless extension rename). Ubuntu 26.04.1 LTS on WSL2, Windows 11. Not run: real Proton account, real systemd, Arch (human, after phase 6). | 2026-10-03 |
| 4 | `phase-04-deletion-safety.plan.md` | completed | `wsl -- bash scripts/test.sh` exit 0: `76 passed, 1 xfailed in 31.30s` (0 failed, 0 xpassed). The 1 xfailed is phase 5 (headless extension rename). Ubuntu 26.04.1 LTS on WSL2, Windows 11. Not run: real Proton account, real systemd, Arch (human, after phase 6). | 2026-10-03 |
| 5 | `phase-05-headless-defaults-and-paths.plan.md` | completed | `wsl -- bash scripts/test.sh -ra --tb=line` exit 0: `91 passed in 32.37s` (0 failed, 0 xfailed). Ubuntu 26.04.1 LTS on WSL2, Windows 11. Not run: real Proton account, real systemd, Arch (human, after phase 6). | 2026-10-03 |
| 6 | `phase-06-arch-packaging-release.plan.md` | not started | | |

## Handoff (2026-10-03)

**Where we are**
- Fork of `lafontaj/proton-drive-cli-sync` at `5a852e2`. The phasing setup is merged into `main` (PR #1, `f9f186e`).
- No CI on pull requests. `.github/workflows/tests.yml` is manual (`workflow_dispatch`) only. Reviews run locally via `.cursor/skills/phase/review.sh`.
- Phase 5 is done on this branch: a headless run does not rename extensions on CLI ≥ 0.5.0 unless settings say so, settings live under `~/.config/proton-drive-sync/`, and `proton-drive` is found on `PATH`. No xfails remain.
- WSL is ready on this PC (see Notes). The gate ran there.

**Who does what**
- Cursor: code changes, using `/phase <N>` or `/phase <N> resume`.
- Claude Code: orchestration. Checks PR and review state, decides the next step, and updates this file and the plans.
- User: approves pushes, posts anything public, and can stop the automatic hand-off with `PHASE_AUTOCHAIN=0` (after each merge `next-phase.sh` starts the next phase in a new headless Cursor CLI session; log in `.git/phase-runs/`).

**Prompt to give Cursor**
```
/phase 6

Arch packaging and release from .cursor/plans/phase-06-arch-packaging-release.plan.md. The phase 5 gate is recorded in this file. Do not start work past phase 6.
```

## Deferred
- [Not planned] SDK/event experiment, two-way prototype, desktop status UI (see roadmap "Not planned yet"). Noticed while planning, 2026-10-03.
- [Human, after phase 6] Publish to the AUR, tag `v2.0.0`, run `makepkg`/`namcap` on Arch. Noticed while planning, 2026-10-03.
- [Human, any time] Run the read-only inventory from spec §5 on Nizar's machine (after phase 6: `proton-drive-sync-doctor --redact`) to learn whether deletion, rename-ext or equal-size edits affect his setup. Noticed while planning, 2026-10-03.

## Notes / decisions
- 2026-10-03: Phase 5 GUI migration. `_maybe_disable_rename_ext` still writes settings, once: if `effective_rename_ext` is off and the stored value is on, it sets `rename_ext_enabled` false and `rename_ext_auto_disabled` true, then shows the existing dialog. If the stored value is already off, it only sets the flag and does not show the dialog. If the helper says the workaround stays (old CLI), it writes nothing. The engine never writes these keys. A missing key uses `DEFAULTS["rename_ext_enabled"]` (true) only for that stored-value check; the headless decision does not.
- 2026-10-03: `~/.proton_sync` leftovers that stay. Runtime paths now use `~/.proton-drive-sync`. The only `expanduser("~/.proton_sync…")` calls are `config.py`'s `_LEGACY_CACHE_DIR`, `_LEGACY_BASE_DIR`, and `_LEGACY_LOCK_FILE`. Comments that name the old paths stay because they describe that migration (`config.py`, `local_watcher.py`, `realtime_consumer.py`, `realtime_manager.py`). README and README_fr migration paragraphs name the same legacy locations. The phase 5 plan text and `PROTON_DRIVE_SYNC_MASTER_PLAN.md` still describe the pre-change snapshot. The phase 3 note below that names `~/.proton_sync/last-run.json` as the no-config fallback is superseded: that fallback is `~/.proton-drive-sync/last-run.json`. No `-dev` or leading-dot sibling of `~/.config/proton-drive-sync/settings.json` or `cli-version.json`.
- 2026-10-03: Phase 4 mount re-check. `detect_source_kind` reads `/proc/mounts`, so a positive verdict is reused for 5 seconds (`_MOUNT_RECHECK_TTL`). A refusal is never cached. The latch (`mount_lost` on the mapping's delete options) still stops every later folder in that pass after the first failure.
- 2026-10-03: Phase 4 exclusion fingerprint. The signature still includes the exclusion fingerprint, so a change still forces one listing. Under the default `excluded_remote: "keep"` that listing does not trash excluded names. `"prune"` is the old cleanup.
- 2026-10-03: Phase 3 review round 1. Exit 5 still records `[unreadable]` paths on the consumer (`clear_unreadable` then `note_unreadable`) so the tray can name them before the next full pass. `[run-result]` is printed after the last-run write so a write error is not the last line. `00-core` and this file keep the existing hand-off: `next-phase.sh` starts the next session.
- 2026-10-03: Phase 3 code 2 (auth). `run_once` already refuses to launch when `keyring_ready` is false, so a locked keyring never reaches the engine. If the engine still exits 2, `process_ready` keeps the previous path: markers restored, no exponential backoff. Backoff applies to exit 1, 5 and any other non-success code. Exits 3 and 4 keep the cold mechanism.
- 2026-10-03: Phase 3 trash counters. `items_trashed` and `trash_failed` are incremented in `remote_trash`, which `delete_orphans` and `_wipe_mapping_remote` both call. A failed wipe is therefore a pass failure even though `main` ignores the wipe's return value. Dry-run returns before those counters.
- 2026-10-03: `last-run.json` is a new file, not a renamed path. Writer: `proton_sync._write_last_run` (tmp + `os.replace`). Path constant: `config.LAST_RUN_FILE`, with the no-config fallback `~/.proton_sync/last-run.json`. No other runtime reader. The GUI does not display it (out of scope). Phase 6's doctor plan is the later reader. No `-dev` or leading-dot sibling of this path. Hits that stay: tests, `CHANGELOG.md`, `INSTALLATION-systemd.md`, and the phase 6 plan text.
- 2026-10-03: Phase 2 review round 1. Edits that the old comparator skipped are already stored as synced in the cache, and a baseline can also match a file that was edited while excluded. This phase documents both: one `--ignore-cache` pass after upgrading, and one after removing an exclusion. The engine does not do that pass by itself. Automatic repair and invalidating baselines when the exclusion fingerprint changes stay a user decision (review follow-up, not this phase).
- 2026-10-03: Phase 2 remote mtime. At SDK `28ac9cdc258737375692d1751dd9c7edcfb96708`, `filesystem upload` sends the local file's modification time: `cli/src/commands/fileSystem/commandFileSystemUpload.ts` sets `modificationTime` from `Bun.file().lastModified` (milliseconds) via `new Date(...)` when it is non-zero (https://github.com/ProtonDriveApps/sdk/blob/28ac9cdc258737375692d1751dd9c7edcfb96708/cli/src/commands/fileSystem/commandFileSystemUpload.ts#L331). That Date is stored as ISO-8601 UTC (`Date.toISOString`) in extended attributes (https://github.com/ProtonDriveApps/sdk/blob/28ac9cdc258737375692d1751dd9c7edcfb96708/client/js/src/internal/nodes/extendedAttributes.ts#L65). `filesystem list -j` serializes the revision Date, so `claimedModificationTime` is a string like `2016-02-29T21:42:04.000Z` (https://github.com/ProtonDriveApps/sdk/blob/28ac9cdc258737375692d1751dd9c7edcfb96708/client/js/src/transformers.ts#L168 and `client/js/src/interface/nodes.ts`). The top-level `modificationTime` is the server clock and is not used for the upload decision. Row 8 is implemented: normalized claimed time within 2 seconds of the local mtime means unchanged. The fake stores POSIX seconds and emits that ISO string. `needs_upload` callers: `upload_batch` recovery (baseline forced to None), `sync_folder` (`upload_decision` plus `Cache.file_baseline`, skipped when `--ignore-cache`), `sync_file` (`upload_decision` with baseline None). No other Python caller.
- 2026-10-03: `CHANGELOG.md` already existed from phase 1 (`## [Unreleased]`). Phase 2 added a Fixed entry there instead of creating the file. The plan's "create CHANGELOG.md" step was already done.
- 2026-10-03: `CHANGELOG.md` was added and `UPSTREAM.md` was edited even though the phase 1 plan's Files list says "Nothing else". `00-core` requires a changelog entry for the settings-path behavior, and it requires every touched upstream file in `UPSTREAM.md`. The changelog heading is `## [Unreleased]` so phase 2 can add a Fixed entry without reformatting.
- 2026-10-03: WSL ready: Ubuntu 26.04.1 LTS, WSL2, user mehdi. `wsl -- id -un` prints `mehdi`; `python3 -c "import venv, fcntl"` prints `ok`; `msgfmt` is GNU gettext-tools 0.23.2.
- 2026-10-03: `PROTON_SYNC_SETTINGS` is a new override, not a renamed path. When it is unset or empty, `config._SETTINGS_PATH` and `i18n.SETTINGS_PATH` stay `APP_DIR/settings.json`. Those two modules are the only readers and writers of the file. Other `settings.json` hits are comments, `.gitignore`, `settings.example.json`, and docs. This repo has no `-dev` or leading-dot sibling of the settings path.
- 2026-10-03: Forked at upstream `5a852e218d353209a3b39cabdb4b810d0f254177`, the commit the spec reviewed. Upstream remote is `upstream`.
- 2026-10-03: Review budget for this project is **2 rounds per PR** (round 1 full, round 2 verify). Set by the user for cost reasons; enforced by `PHASE_REVIEW_MAX_ROUNDS` in `.cursor/skills/phase/review.sh`. After round 2, Cursor fixes what is listed, pushes once, and stops without merging if the verdict was not Ready to merge.
- 2026-10-03: Tests run in WSL (`wsl -- bash scripts/test.sh`) because the engine needs `fcntl`, `/proc` and systemd. Windows Python results do not count as gate evidence.
- 2026-10-03: The spec is the engineering briefing, renamed `PROTON_DRIVE_SYNC_MASTER_PLAN.md` with headings turned into `# N.`. The surname of the user it was written for was removed from the public copy.
- 2026-10-03: Upstream files edited by this fork are listed in `UPSTREAM.md` so fixes can be offered back to upstream later.
