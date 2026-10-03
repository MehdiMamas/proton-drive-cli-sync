---
name: "Proton Drive Sync Phase 4 – Deletion and exclusion safety"
overview: "Phase 4 of 6. Deletion and exclusion safety. Scope is limited to this phase; finish when the gate passes, record evidence in PROGRESS.md and stop. Gate: `wsl -- bash scripts/test.sh` exits 0 with 0 failed, 0 xpassed and exactly 1 xfailed (owned by phase 5)."
todos:
  - id: p04-0-preflight
    content: "Preflight: read PROGRESS.md, confirm the active phase is 4 and the Phase 3 gate is recorded with command output; read PROTON_DRIVE_SYNC_MASTER_PLAN.md §4, §5, §9"
    status: completed
  - id: p04-1-task
    content: "excluded_remote mapping key, default keep (task 1)"
    status: completed
    dependencies: [p04-0-preflight]
  - id: p04-2-task
    content: "Mass-deletion guard, overrides, --allow-mass-delete (task 2)"
    status: completed
    dependencies: [p04-1-task]
  - id: p04-3-task
    content: "Per-folder mount re-check with latch (task 3)"
    status: completed
    dependencies: [p04-2-task]
  - id: p04-4-task
    content: "GUI preserves unknown mapping keys (task 4)"
    status: completed
    dependencies: [p04-3-task]
  - id: p04-5-task
    content: "Help text, example mappings, README, CHANGELOG (task 5)"
    status: completed
    dependencies: [p04-4-task]
  - id: p04-6-task
    content: "Remove the phase-04 xfail marker (task 6)"
    status: completed
    dependencies: [p04-5-task]
  - id: p04-8-gate
    content: "Verify gate: `wsl -- bash scripts/test.sh` exits 0 with 0 failed, 0 xpassed and exactly 1 xfailed (owned by phase 5)"
    status: completed
    dependencies: [p04-6-task]
  - id: p04-9-handoff
    content: "Record gate evidence in PROGRESS.md, mark Phase 4 complete there, open the PR and run the review loop, then hand off with `next-phase.sh` (new headless session) and stop"
    status: completed
    dependencies: [p04-8-gate]
---

# Phase 4 – Deletion and exclusion safety

> Part of the Proton Drive Sync roadmap: [`00-roadmap.plan.md`](00-roadmap.plan.md). Spec: `PROTON_DRIVE_SYNC_MASTER_PLAN.md` §4, §5, §9. Rules in `.cursor/rules/` are binding, especially `05-phase-discipline.mdc` and `10-engine-safety.mdc`.

**Phase 4 of 6.** Previous: Phase 3 – Honest run results. Next: Phase 5 – Headless defaults and file locations.
Branch `phase-04-deletion-safety`. Commit subject: `fix(phase-04): keep excluded remote items, guard mass deletions, re-check mounts`. Depends on: phase 3.
Line numbers below refer to upstream commit `5a852e2`. Earlier phases shift them, so locate code by function name.

## Before you start
- `PROGRESS.md` must say the active phase is **4**. The Phase 3 gate must be recorded with command output. If it is not, stop and tell the user.
- Read the cited spec sections in full.
- Look at the code that already exists. Build on it instead of re-creating it. If the code differs from this plan, follow the code and note the difference in `PROGRESS.md`.

## Problem

1. With deletion enabled, `sync_folder()` builds `local_names` from **non-excluded** local entries and `delete_orphans()`
   trashes every remote name not in that set. Adding an exclusion therefore trashes the already-uploaded remote copy on
   the next full `--delete` pass (the exclusion fingerprint in the signature is designed to trigger exactly that).
   Users expect "exclude" to mean "stop syncing it", not "delete my backup of it".
2. The mount guard runs once per mapping (`sync_folder_guarded`) / subpath. A NAS that drops mid-pass, or a source that
   is emptied by accident, can still make whole folders look like orphans.
3. Stale text: `--subpath` help calls it purely additive (it isn't); `mappings.example.json` and docs still show
   `"delete_mode": "permanent"` as if it deleted permanently (`remote_trash` always trashes since CLI 0.8.0).

## Design

### Excluded remote items: `excluded_remote` mapping key
- Values: `"keep"` (**new default**) or `"prune"` (old behavior). Unknown values → treat as `"keep"` and print a one-line warning.
- In `delete_orphans()` (or just before calling it), a remote child whose name matches the mapping's effective exclusions
  is **never** trashed under `keep`. Verbose: `kept (excluded): <path>`.
- Under `keep`, the exclusion fingerprint must no longer force a reconciliation pass just to prune. Keep the fingerprint
  in the signature as is (format compatibility). The extra pass is harmless, just a listing.
- Applies identically to full passes, `--reset-source` rebuilds, and `--subpath`.

### Mass-deletion guard
- Per folder, before trashing: let `n_orphans` = items about to be trashed, `n_remote` = remote children in that folder.
  If `n_orphans >= max_delete_min` **and** `n_orphans / n_remote > max_delete_ratio`, refuse **all** deletions in that
  folder for this pass, print `[delete-guard] ` + translated message naming the folder and counts, increment a new
  RunStats counter `deletions_refused` (counts as a failure → exit 5), and do NOT mark the folder `delete_synced`.
- Defaults: `max_delete_min = 20`, `max_delete_ratio = 0.5`. Configurable globally in `settings.json` via `config.py`
  (`DEFAULTS` + typed getters) and overridable per mapping (`max_delete_min`, `max_delete_ratio` keys).
- New engine flag `--allow-mass-delete` disables the guard for one run (for deliberate cleanups). The GUI does not pass it.
- Dry-run: report what the guard would do. Never trash in dry-run (unchanged).

### Mount re-check right before deleting
- Re-run the mapping's mount guard (`_delete_guard_ok(source, source_kind)`) immediately before each folder's
  deletions. Pass what's needed down to `sync_folder` (e.g. a `delete_guard` callable parameter defaulting to `None` = no
  re-check, so other callers are unaffected). If it fails: skip deletions for that folder and all later folders of this
  mapping in this pass (latch), message once, count as failure, uploads continue.
- Cost: `mount_check.detect_source_kind` reads `/proc/mounts`. If that is too heavy per folder, cache the result for ≤ 5 s;
  document the choice in `PROGRESS.md` under Notes / decisions.

### GUI must preserve new keys
Verify how `proton_mapping_editor.py` loads and saves mappings. If it rebuilds mapping dicts from widget fields, make
sure unknown keys (`excluded_remote`, `max_delete_*`, and any other key it does not edit) survive a load→save round trip.
Add a non-GUI unit test for the save/serialize helper if it can be imported without a display; otherwise extract the
smallest pure helper needed and test that. **No new GUI widgets in this phase.**

### Docs and text
- Engine `--help` for `--subpath` / `--delete`: describe actual behavior (deletion gates).
- `mappings.example.json`: replace `"permanent"` example with `"trash"`, add `"excluded_remote": "keep"` to the deleting mappings.
- README (EN; FR only the matching paragraphs if straightforward): exclusion semantics, mass-delete guard, "permanent = trash".
- `CHANGELOG.md`: **Changed (safety):** excluded items' remote copies are now kept by default; set `"excluded_remote": "prune"` for the old behavior. **Added:** mass-deletion guard, `--allow-mass-delete`.

## Scope (do these, nothing else)

### Tasks

1. `excluded_remote` handling + warning for unknown values.
2. Mass-deletion guard + settings/mapping overrides + `--allow-mass-delete` + RunStats counter.
3. Per-folder mount re-check with latch.
4. GUI key-preservation verification/fix + test.
5. Docs/help/example/CHANGELOG updates.
6. Flip xfail `test_exclusion_added_later_keeps_remote_copy`.

### Required tests

Each must assert the behavior and fail on the code before this phase (say how you checked in the PR).

- `test_exclusion_added_later_keeps_remote_copy` (flipped)
- `test_excluded_remote_prune_restores_old_behavior`
- `test_remote_only_item_still_trashed_in_mirror_mode` (non-excluded orphan is trashed: mirror semantics intact)
- `test_mass_delete_guard_refuses_and_exits_5` (e.g. 30 remote files, local folder emptied → nothing trashed, `[delete-guard]`, exit 5, folder not `delete_synced`)
- `test_mass_delete_guard_below_threshold_allows` (e.g. 3 of 30)
- `test_allow_mass_delete_flag_overrides_guard`
- `test_per_mapping_threshold_override`
- `test_mount_lost_mid_pass_stops_deletions` (in-process `sync_folder` with a guard callable that flips to failure after the first folder → later folders trash nothing, uploads still happen)
- `test_subpath_respects_excluded_remote`
- `test_listing_failure_never_deletes` (exists in baseline? keep green)
- `test_mappings_roundtrip_preserves_unknown_keys` (GUI save helper)
- `test_unknown_excluded_remote_value_defaults_to_keep`

### Acceptance criteria

- **AC-1** By default, no remote item whose name matches an active exclusion is ever trashed, in any pass type.
- **AC-2** `excluded_remote: "prune"` reproduces the previous behavior exactly (test proves it).
- **AC-3** A pass that would trash more than the thresholds in one folder trashes nothing there, exits 5, and says why with `[delete-guard]`.
- **AC-4** Losing the mount mid-pass prevents any further deletion in that mapping for the rest of the pass.
- **AC-5** All three original deletion gates are unchanged (baseline tests green).
- **AC-6** GUI load/save keeps unknown mapping keys.
- **AC-7** Help text, example mappings, README and CHANGELOG match behavior. No doc still claims permanent deletion happens.
- **AC-8** Full suite green. The only remaining xfail is the phase-05 one.

## Out of scope (do NOT start these, even partially)
- Phase 5 – Headless defaults and file locations → `phase-05-headless-defaults-and-paths.plan.md`
- Everything in later phases (see `00-roadmap.plan.md`)
- New GUI controls for these settings (later). Permanent deletion. Changing upload semantics.

Do not create files, services, stubs, settings or UI that belong to a later phase. If something here seems to need later-phase work, write the smallest thing that unblocks this phase, then add a note under "Deferred" in `PROGRESS.md`.

## Gate
**`wsl -- bash scripts/test.sh` exits 0 with 0 failed, 0 xpassed and exactly 1 xfailed (owned by phase 5).**

Prove it: run the command, and paste the command and its result (exit code, the pytest summary line) into Phase 4's row in `PROGRESS.md`. Name the OS that ran it (e.g. `Ubuntu 24.04 on WSL2, Windows 11`, from `wsl -- grep PRETTY_NAME /etc/os-release`). Anything not run (real Proton account, real systemd, Arch) is written as not run, with who runs it.

## When the gate passes
1. Mark every todo in this file `completed`.
2. In `PROGRESS.md`: mark Phase 4 done with the date and evidence, and set the active phase to **5**.
3. Commit with a conventional message scoped `phase-04`, push branch `phase-04-deletion-safety`, open the PR, and run the review loop in `.cursor/skills/phase/SKILL.md`.
4. **Hand off** after the merge: run `bash .cursor/skills/phase/next-phase.sh`, report the PR URL and its `NEXT:` line, and stop. Never start the next phase in the same chat.

## Manual test (for the human, real account, test folder only)

Mapping with `allow_delete: true` to a throwaway remote folder. Upload `keep.log`, then add `*.log` to the mapping's
exclusion patterns, run with `--delete -v`: expect `kept (excluded)` and the file still in Drive. Then move 25 files
out of the local folder and run with `--delete`: expect `[delete-guard]`, nothing trashed, exit 5.
