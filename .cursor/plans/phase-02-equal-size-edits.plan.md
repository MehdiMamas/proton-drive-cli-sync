---
name: "Proton Drive Sync Phase 2 – Detect equal-size edits"
overview: "Phase 2 of 6. Detect equal-size edits. Scope is limited to this phase; finish when the gate passes, record evidence in PROGRESS.md and stop. Gate: `wsl -- bash scripts/test.sh` exits 0 with 0 failed, 0 xpassed and exactly 4 xfailed (owned by phases 3-5)."
todos:
  - id: p02-0-preflight
    content: "Preflight: read PROGRESS.md, confirm the active phase is 2 and the Phase 1 gate is recorded with command output; read PROTON_DRIVE_SYNC_MASTER_PLAN.md §4, Appendix A"
    status: pending
  - id: p02-1-task
    content: "Investigate the CLI's claimedModificationTime at the pinned SDK commit, record it, align the fake (task 1)"
    status: pending
    dependencies: [p02-0-preflight]
  - id: p02-2-task
    content: "Cache.file_baseline() (task 2)"
    status: pending
    dependencies: [p02-1-task]
  - id: p02-3-task
    content: "upload_decision() + needs_upload wrapper + sync_folder wiring (task 3)"
    status: pending
    dependencies: [p02-2-task]
  - id: p02-4-task
    content: "Batch recovery fix in upload_batch (task 4)"
    status: pending
    dependencies: [p02-3-task]
  - id: p02-5-task
    content: "sync_file uses the new comparator (task 5)"
    status: pending
    dependencies: [p02-4-task]
  - id: p02-6-task
    content: "Remove the three phase-02 xfail markers (task 6)"
    status: pending
    dependencies: [p02-5-task]
  - id: p02-7-task
    content: "CHANGELOG.md + docs/change-detection.md (task 7)"
    status: pending
    dependencies: [p02-6-task]
  - id: p02-8-gate
    content: "Verify gate: `wsl -- bash scripts/test.sh` exits 0 with 0 failed, 0 xpassed and exactly 4 xfailed (owned by phases 3-5)"
    status: pending
    dependencies: [p02-7-task]
  - id: p02-9-handoff
    content: "Record gate evidence in PROGRESS.md, mark Phase 2 complete there, open the PR and run the review loop, then STOP and wait for the user"
    status: pending
    dependencies: [p02-8-gate]
---

# Phase 2 – Detect equal-size edits

> Part of the Proton Drive Sync roadmap: [`00-roadmap.plan.md`](00-roadmap.plan.md). Spec: `PROTON_DRIVE_SYNC_MASTER_PLAN.md` §4, Appendix A. Rules in `.cursor/rules/` are binding, especially `05-phase-discipline.mdc` and `10-engine-safety.mdc`.

**Phase 2 of 6.** Previous: Phase 1 – Test harness with a fake Proton CLI. Next: Phase 3 – Honest run results.
Branch `phase-02-equal-size-edits`. Commit subject: `fix(phase-02): stop skipping edits that keep the file size`. Depends on: phase 1.
Line numbers below refer to upstream commit `5a852e2`. Earlier phases shift them, so locate code by function name.

## Before you start
- `PROGRESS.md` must say the active phase is **2**. The Phase 1 gate must be recorded with command output. If it is not, stop and tell the user.
- Read the cited spec sections in full.
- Look at the code that already exists. Build on it instead of re-creating it. If the code differs from this plan, follow the code and note the difference in `PROGRESS.md`.

## Problem

`needs_upload()` (`proton_sync.py` ~L1316) decides from existence and byte count only. A file edited in place with the
same size (AAAA→BBBB) is never uploaded, unless `--verify-hash` is on **and** the remote listing carries a SHA-1.
The directory signature does notice the change, so the folder IS inspected. The comparator just answers "no".
The same comparator is used in `upload_batch()` (~L1458) after a failed batch to decide what "already made it",
so an old same-size remote file can be taken for a successful replacement. `sync_file()` (~L2159) has the same gap.

## Design (follow it; deviations need a recorded reason)

Use the **cached directory signature as a per-file baseline** of the last fully successful pass. The cache entry's
`sig.files` already stores `[name, size, mtime]` for each direct file, written only when the folder pass had no failure.
That gives a cheap "has this file changed since we last confirmed it?" signal without changing the cache format.

Decision order for a regular file (new function, e.g. `upload_decision(local_path, remote_info, baseline=None, verify_hash=False) -> (bool, reason)`):

| # | Condition | Upload? | reason |
| --- | --- | --- | --- |
| 1 | `remote_info is None` | yes | `new` |
| 2 | local stat fails | yes | `local-unreadable` (current behavior; the upload will report the real error) |
| 3 | remote size unknown | yes | `remote-size-unknown` |
| 4 | sizes differ | yes | `size-changed` |
| 5 | `verify_hash` and remote sha1 present | iff hashes differ | `hash-differs` / `hash-equal` |
| 6 | baseline has this name with equal `(size, mtime)` to the local stat | no | `unchanged-since-last-success` |
| 7 | remote sha1 present | iff local sha1 differs | `hash-differs` / `hash-equal` |
| 8 | remote mtime usable (see Task 1) and equals local mtime within 2 s | no | `mtime-equal` |
| 9 | otherwise | **yes** | `equal-size-unverifiable` (conservative) |

- `baseline` is `None` when there is no cache entry, the entry is legacy/bare, or `--ignore-cache` is set
  (`--ignore-cache` means "re-verify", so the baseline is not trusted).
- Hashing (rows 5, 7) happens only for equal-size files whose baseline is missing or different, so unchanged trees
  are never re-read. Cache-skipped folders never reach the comparator at all.
- Keep `needs_upload(local_path, remote_info, verbose=False, verify_hash=False)` as a thin wrapper with the same signature
  (GUI and other modules may import it: `rg -n "needs_upload" --type py`) that calls the new function with `baseline=None`.
  Note: that means the wrapper is now conservative (row 9) when no baseline/digest exists. Check every caller and make sure that is intended.
- Verbose mode prints the reason for each upload decision of an equal-size file (translated message, reason code untranslated).

### Batch recovery (`upload_batch`)

After a failed batch, a file counts as "already uploaded by the batch" only if the re-listed remote entry has
**a sha1 equal to the local sha1**, or (no sha1) **size equal AND row 8's mtime check passes**. Otherwise retry it
individually as today. Never use the pre-batch baseline here.

### Cache format

**Do not change `_local_signature()`'s output** (that would invalidate every user's cache and force a full re-listing).
Add a read helper on `Cache`, e.g. `file_baseline(local_dir) -> dict[name, (size, mtime)] | None`, that tolerates legacy
bare-signature entries and missing `files`.

## Scope (do these, nothing else)

### Tasks

1. **Investigate remote mtime.** At pinned SDK commit `28ac9cdc258737375692d1751dd9c7edcfb96708`, read
   `cli/src/commands/fileSystem/` (upload path) in `ProtonDriveApps/sdk` (use `gh api repos/ProtonDriveApps/sdk/contents/<path>?ref=<sha>`)
   and determine: does `filesystem upload` send the local file's modification time as the revision's
   `claimedModificationTime`? In what unit/format does `filesystem list -j` return it (seconds, ms, ISO string)?
   Record the answer with source links in `PROGRESS.md` under Notes / decisions and in a French comment above `_extract_remote_meta`.
   - If yes: normalize remote mtime to float seconds in `_extract_remote_meta` (robust to the formats found) and use row 8.
   - If no / unclear: drop row 8 (rows 7 → 9) and say so.
   - Update the fake CLI to mirror the finding (store and report mtime the same way), with a comment.
2. Add `Cache.file_baseline()`; unit-test legacy entries, missing entries, `__meta__`.
3. Implement `upload_decision()` + `needs_upload()` wrapper per the table. Pass the baseline from `sync_folder()` (both
   the normal path and anything else that calls the comparator). Respect `ignore_cache`.
4. Fix batch recovery in `upload_batch()` as specified.
5. `sync_file()` uses `upload_decision()` with `baseline=None`.
6. Remove the xfail markers from `test_equal_size_edit_is_uploaded`, `test_equal_size_edit_detected_by_comparator`,
   `test_batch_recovery_not_fooled_by_old_equal_size_remote` (move them to a proper test module if cleaner).
7. Docs: create `CHANGELOG.md` (Keep a Changelog format, `## [Unreleased]`) with a "Fixed" entry. Create
   `docs/change-detection.md` explaining exactly when a file is re-uploaded (the table above in user language), the
   known limitation (an edit that preserves both size and mtime, e.g. `cp -p`/`rsync -t` of different content, is only
   caught by `--ignore-cache` or `--verify-hash`), and the cost model (hashing only equal-size changed candidates).

### Required tests

Each must assert the behavior and fail on the code before this phase (say how you checked in the PR).

- `test_equal_size_edit_is_uploaded` (e2e, flipped from xfail)
- `test_equal_size_edit_detected_by_comparator` (flipped; adapt to call `needs_upload` per Appendix A expecting `True`)
- `test_batch_recovery_not_fooled_by_old_equal_size_remote` (flipped)
- `test_unchanged_files_are_not_hashed`: second pass over a folder whose signature changed only because a **sibling** changed → `_local_sha1` is not called for the unchanged files (in-process, count calls via monkeypatch of `_local_sha1`).
- `test_equal_size_edit_without_remote_digest_is_uploaded` (fake omits `claimedDigests`; baseline differs → upload)
- `test_equal_size_unchanged_without_remote_digest_is_skipped` (baseline matches → no upload)
- `test_existing_identical_remote_not_reuploaded_without_cache` (fresh cache, remote already has identical content with digest → no upload; pins the "reinstall" scenario)
- `test_ignore_cache_rechecks_preserved_mtime_edit` (content changed, size and mtime restored with `os.utime` → normal pass skips (documented limitation), `--ignore-cache` pass uploads)
- `test_sync_file_mapping_equal_size_edit` (`type: "file"` mapping)
- `test_signature_format_unchanged` (golden: `_local_signature` output for a fixed tree equals a literal dict, guarding cache compatibility)
- `test_file_baseline_legacy_entry` (bare-signature legacy entry and entry without `files` → `None`/empty, no crash)
- If row 8 is implemented: `test_remote_mtime_normalization` covering every format found in Task 1.

### Acceptance criteria

- **AC-1** An in-place equal-size edit with a newer mtime is uploaded on the next normal pass, with and without remote digests.
- **AC-2** An unchanged file in an inspected folder is neither hashed nor uploaded when a baseline exists.
- **AC-3** Batch-failure recovery never treats an old equal-size remote file as freshly uploaded.
- **AC-4** Cache files written by the previous version still load, and unchanged folders are still skipped without a remote listing (no forced re-scan).
- **AC-5** `needs_upload` keeps its signature. All callers reviewed and listed in the PR.
- **AC-6** Task 1's finding is documented with source links. The fake CLI matches it.
- **AC-7** `CHANGELOG.md` and `docs/change-detection.md` exist and match the implemented behavior.
- **AC-8** Full suite green in WSL. Remaining xfails are exactly the phase-03/04/05 ones.

## Out of scope (do NOT start these, even partially)
- Phase 3 – Honest run results → `phase-03-run-results.plan.md`
- Everything in later phases (see `00-roadmap.plan.md`)
- Exit codes / run results (phase 3). Changing the signature/cache format. Two-way anything.

Do not create files, services, stubs, settings or UI that belong to a later phase. If something here seems to need later-phase work, write the smallest thing that unblocks this phase, then add a note under "Deferred" in `PROGRESS.md`.

## Gate
**`wsl -- bash scripts/test.sh` exits 0 with 0 failed, 0 xpassed and exactly 4 xfailed (owned by phases 3-5).**

Prove it: run the command, and paste the command and its result (exit code, the pytest summary line) into Phase 2's row in `PROGRESS.md`. Name the OS that ran it (e.g. `Ubuntu 24.04 on WSL2, Windows 11`, from `wsl -- grep PRETTY_NAME /etc/os-release`). Anything not run (real Proton account, real systemd, Arch) is written as not run, with who runs it.

## When the gate passes
1. Mark every todo in this file `completed`.
2. In `PROGRESS.md`: mark Phase 2 done with the date and evidence, and set the active phase to **3**.
3. Commit with a conventional message scoped `phase-02`, push branch `phase-02-equal-size-edits`, open the PR, and run the review loop in `.cursor/skills/phase/SKILL.md`.
4. **Stop** after the merge. Report the PR URL. Do not start the next phase.

## Manual test (for the human, needs a real account, optional)

Use a throwaway mapping to a test folder: run once, then `printf BBBB > file` over an `AAAA` file, run again with `-v`,
and confirm the log shows the upload with reason `hash-differs` (or `equal-size-unverifiable`), and the web UI shows the new content.
