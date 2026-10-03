---
name: "Proton Drive Sync Phase 3 – Honest run results"
overview: "Phase 3 of 6. Honest run results. Scope is limited to this phase; finish when the gate passes, record evidence in PROGRESS.md and stop. Gate: `wsl -- bash scripts/test.sh` exits 0 with 0 failed, 0 xpassed and exactly 2 xfailed (owned by phases 4-5)."
todos:
  - id: p03-0-preflight
    content: "Preflight: read PROGRESS.md, confirm the active phase is 3 and the Phase 2 gate is recorded with command output; read PROTON_DRIVE_SYNC_MASTER_PLAN.md §4, §5, §9"
    status: pending
  - id: p03-1-task
    content: "RunStats accumulator and increments (task 1)"
    status: pending
    dependencies: [p03-0-preflight]
  - id: p03-2-task
    content: "Exit code 5 plumbing incl. sync_subpath and sync_file (task 2)"
    status: pending
    dependencies: [p03-1-task]
  - id: p03-3-task
    content: "[run-result] line and last-run.json (task 3)"
    status: pending
    dependencies: [p03-2-task]
  - id: p03-4-task
    content: "Consumer exit-5 branch and failure backoff (task 4)"
    status: pending
    dependencies: [p03-3-task]
  - id: p03-5-task
    content: "Unit text, result labels, refresh_units + --refresh-units (task 5)"
    status: pending
    dependencies: [p03-4-task]
  - id: p03-6-task
    content: "GUI handles exit 5 (task 6)"
    status: pending
    dependencies: [p03-5-task]
  - id: p03-7-task
    content: "Remove the phase-03 xfail markers (task 7)"
    status: pending
    dependencies: [p03-6-task]
  - id: p03-8-task
    content: "Exit-code table in 00-core.mdc, INSTALLATION-systemd.md, CHANGELOG (task 8)"
    status: pending
    dependencies: [p03-7-task]
  - id: p03-8-gate
    content: "Verify gate: `wsl -- bash scripts/test.sh` exits 0 with 0 failed, 0 xpassed and exactly 2 xfailed (owned by phases 4-5)"
    status: pending
    dependencies: [p03-8-task]
  - id: p03-9-handoff
    content: "Record gate evidence in PROGRESS.md, mark Phase 3 complete there, open the PR and run the review loop, then STOP and wait for the user"
    status: pending
    dependencies: [p03-8-gate]
---

# Phase 3 – Honest run results

> Part of the Proton Drive Sync roadmap: [`00-roadmap.plan.md`](00-roadmap.plan.md). Spec: `PROTON_DRIVE_SYNC_MASTER_PLAN.md` §4, §5, §9. Rules in `.cursor/rules/` are binding, especially `05-phase-discipline.mdc` and `10-engine-safety.mdc`.

**Phase 3 of 6.** Previous: Phase 2 – Detect equal-size edits. Next: Phase 4 – Deletion and exclusion safety.
Branch `phase-03-run-results`. Commit subject: `fix(phase-03): report partial failures and stop acknowledging unfinished work`. Depends on: phase 2.
Line numbers below refer to upstream commit `5a852e2`. Earlier phases shift them, so locate code by function name.

## Before you start
- `PROGRESS.md` must say the active phase is **3**. The Phase 2 gate must be recorded with command output. If it is not, stop and tell the user.
- Read the cited spec sections in full.
- Look at the code that already exists. Build on it instead of re-creating it. If the code differs from this plan, follow the code and note the difference in `PROGRESS.md`.

## Problem

Failed uploads, failed listings, unreadable folders, missing sources, failed trashes and stall-skips leave a folder
incomplete, but `main()` still exits **0**. In `--subpath` mode `sync_subpath()` discards `sync_folder()`'s completion
boolean, so the real-time consumer (`realtime_consumer.process_ready`, `code == 0` branch) **deletes the markers** for
work that did not reach Drive. systemd shows the nightly run green. Nobody can tell "process finished" from "everything is backed up".

## Design

### Run statistics
A module-level accumulator in `proton_sync.py` (same pattern as `_UNREADABLE`), e.g. `class RunStats` with a
`reset()` and a `to_dict()`. Counters (all ints):

`files_uploaded`, `files_failed`, `files_vanished`, `folders_listing_failed`, `folders_unreadable`,
`folders_permission_denied`, `folders_stall_skipped`, `items_trashed`, `trash_failed`, `sources_missing`,
`mappings_total`, `mappings_complete`.

Increment at the existing decision points (`upload_batch` success/recovered/failures/vanished, `get_remote_listing` failure
branches in `sync_folder`/`sync_file`, `_note_unreadable`, `ensure_remote_path` permission refusal, stall give-up,
`delete_orphans`, the "Source not found" branch in `main`). Dry-run counts "would upload" as uploaded? **No.** Keep
`files_uploaded` = real uploads only. Add `files_would_upload` for dry-run.

`has_failures` ⇔ any of `files_failed`, `folders_listing_failed`, `folders_unreadable`, `folders_permission_denied`,
`folders_stall_skipped`, `trash_failed`, `sources_missing` > 0.

### Exit codes (extend the contract in `.cursor/rules/00-core.mdc`)
- **5 = pass ran to the end but with failures** (`has_failures`). Applies to full passes, `--only-source`, `--reset-source`,
  file mappings, and `--subpath` (when not cold). Dry-run uses the same rule.
- 0/1/2/3/4 unchanged in meaning. Code 3 (cold) still wins over 5 for `--subpath` (nothing was attempted).
- `sync_subpath()` must return the completion result (e.g. `"cold"`, `"failed"`, `"ok"`, or `None` for its existing early
  returns, mapped deliberately: "subpath not found" and "excluded" are not failures; "remote parent unresolvable" is).

### Outputs
- Last line before exit, always (also on 0): `[run-result] {"exit": 5, "mode": "full|subpath|only-source|reset", ...counters}`
  as single-line JSON, untranslated, plus a translated human summary line just before it.
- Keep printing `Done.` at the end of a completed loop (exit 0 or 5). The scheduler's journal parser relies on it.
- `last-run.json` in `config.DATA_DIR` (new constant `LAST_RUN_FILE` in `config.py` with fallback in the engine's
  no-config branch), written atomically (tmp + `os.replace`) for: exit 0, 5, 2 (auth), 4 (account). Not for 1 (another run
  owns the state) and not for dry-run. Fields: `started_at`, `finished_at` (ISO 8601 with offset), `exit`, `mode`,
  `counters`, `engine_version` (`__version__`), `cli_version`. A subpath run must not erase information about the last
  full pass: store `last_full` and `last_subpath` as separate top-level keys, updating only the relevant one.

### Real-time consumer (`realtime_consumer.py`)
- `process_ready`: explicit `code == 5` branch: restore markers (`_restore_markers`), do not `state.clear_cold`, log
  "partial failure, markers kept" with the counters parsed from the `[run-result]` line if present.
- **Failure backoff** for every non-success, non-cold, non-account code (1, 2?, 5, others): per `target_dir`, wait
  60 s, 120 s, 240 s … capped at 1800 s before the engine is relaunched for that target. Reset on success. Implement in
  `DebounceState` next to the cold mechanism (`is_cold_recent`/`mark_cold`) without changing cold semantics.
  Check how code 2 (auth) is handled today: the consumer has a keyring readiness probe (`keyring_ready`). Do not regress it; if
  auth already has its own gating, leave code 2 on its current path and say so in `PROGRESS.md` under Notes / decisions.
- Never call `_cleanup(markers)` unless `code == 0`.

### systemd (`schedule_manager.py`)
- `build_service_text`: keep `SuccessExitStatus=0 2 4`, add `RestartPreventExitStatus=5` with a French comment: a
  partial failure is visible as a failed unit but must not trigger 6 restarts/hour (the next timer or real-time cycle retries).
- `_parse_result`/`_result_label`: code 5 → label "⚠ completed with failures (code 5)" (translated), `ok=False`.
- Existing installs keep old unit files. Add `refresh_units()` that rewrites service+timer from their current values
  (`read_service_mappings_path`, `read_timer_calendar`, `read_service_delete`) via `install_or_update`, and a CLI entry
  `python3 schedule_manager.py --refresh-units` (add `if __name__ == "__main__":` if absent). Document in CHANGELOG.

### GUI (`proton_mapping_editor.py`): minimal
Where the engine's exit code is interpreted (search `returncode`, `code == 0`, around L4787, L5290, L5964 at 5a852e2),
treat 5 as "finished with failures": a warning, not a crash and not a success. No other GUI changes.

## Scope (do these, nothing else)

### Tasks

1. RunStats + increments + `has_failures`.
2. Exit code 5 plumbing in `main()` for every pass type; `sync_subpath` return values; `sync_file` returns its result.
3. `[run-result]` line + summary + `last-run.json` (+ `config.LAST_RUN_FILE`).
4. Consumer: code-5 branch, failure backoff, logging.
5. Scheduler: unit text, result parsing/labels, `refresh_units` + CLI.
6. GUI exit-code handling for 5.
7. Flip xfails `test_upload_failure_exits_nonzero`, `test_subpath_upload_failure_exits_nonzero`.
8. Update `.cursor/rules/00-core.mdc` exit-code table (this file IS in scope for this phase), `INSTALLATION-systemd.md`
   (exit codes section, refresh command), `CHANGELOG.md`.

### Required tests

Each must assert the behavior and fail on the code before this phase (say how you checked in the PR).

- `test_upload_failure_exits_nonzero` (flipped) and `test_subpath_upload_failure_exits_nonzero` (flipped)
- `test_clean_pass_exits_0_with_run_result_line` (parse the JSON, counters correct)
- `test_listing_failure_exits_5`, `test_unreadable_folder_exits_5` (chmod 000 a subdir; skip if running as root), `test_missing_source_exits_5`, `test_trash_failure_exits_5`
- `test_subpath_cold_still_exits_3`
- `test_last_run_json_written_atomically_and_keeps_last_full_on_subpath` (full pass then subpath pass → both keys present, correct exits)
- `test_last_run_not_written_on_dry_run_or_lock_contention`
- `test_consumer_keeps_markers_on_exit_5` and `test_consumer_acks_markers_on_exit_0` (runner injection)
- `test_consumer_backoff_grows_and_resets` (fake monotonic clock; runner call count across cycles)
- `test_service_unit_prevents_restart_on_5` (generated text contains `RestartPreventExitStatus=5` and `SuccessExitStatus=0 2 4`)
- `test_parse_result_labels_code_5`
- `test_refresh_units_preserves_settings` (write old-style unit files into an isolated `~/.config/systemd/user`, run `refresh_units` with `systemctl` calls stubbed, assert mappings path/calendar/delete preserved and new line present)

### Acceptance criteria

- **AC-1** No path exists where an upload/listing/trash failure, an unreadable folder or a missing source results in exit 0.
- **AC-2** The consumer acknowledges markers only on exit 0, and relaunches a persistently failing target no more than the backoff allows.
- **AC-3** A persistent partial failure under systemd produces a failed unit without automatic restarts.
- **AC-4** `[run-result]` JSON and `last-run.json` exist with the documented fields. A subpath run never erases `last_full`.
- **AC-5** Exit codes 1–4 behave exactly as before (existing baseline tests untouched and green).
- **AC-6** Exit-code table updated in the rule file, INSTALLATION-systemd.md and CHANGELOG (with the `--refresh-units` migration step).
- **AC-7** Full suite green. Remaining xfails are exactly the phase-04/05 ones.

## Out of scope (do NOT start these, even partially)
- Phase 4 – Deletion and exclusion safety → `phase-04-deletion-safety.plan.md`
- Everything in later phases (see `00-roadmap.plan.md`)
- Deletion policy (phase 4). Notifications/tray changes. Rewriting the GUI's log parsing beyond exit code 5.

Do not create files, services, stubs, settings or UI that belong to a later phase. If something here seems to need later-phase work, write the smallest thing that unblocks this phase, then add a note under "Deferred" in `PROGRESS.md`.

## Gate
**`wsl -- bash scripts/test.sh` exits 0 with 0 failed, 0 xpassed and exactly 2 xfailed (owned by phases 4-5).**

Prove it: run the command, and paste the command and its result (exit code, the pytest summary line) into Phase 3's row in `PROGRESS.md`. Name the OS that ran it (e.g. `Ubuntu 24.04 on WSL2, Windows 11`, from `wsl -- grep PRETTY_NAME /etc/os-release`). Anything not run (real Proton account, real systemd, Arch) is written as not run, with who runs it.

## When the gate passes
1. Mark every todo in this file `completed`.
2. In `PROGRESS.md`: mark Phase 3 done with the date and evidence, and set the active phase to **4**.
3. Commit with a conventional message scoped `phase-03`, push branch `phase-03-run-results`, open the PR, and run the review loop in `.cursor/skills/phase/SKILL.md`.
4. **Stop** after the merge. Report the PR URL. Do not start the next phase.

## Manual test (for the human)

On the Linux machine after merge: `python3 schedule_manager.py --refresh-units`, then `systemctl --user cat proton-sync.service`
shows `RestartPreventExitStatus=5`. Make one source file unreadable (`chmod 000 file`), run the service
(`systemctl --user start proton-sync.service`), and check `systemctl --user status` shows it failed with status 5 and no
restart, and `~/.proton-drive-sync/last-run.json` lists `files_failed: 1`. Restore permissions afterwards.
