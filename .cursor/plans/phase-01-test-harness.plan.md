---
name: "Proton Drive Sync Phase 1 – Test harness with a fake Proton CLI"
overview: "Phase 1 of 6. Test harness with a fake Proton CLI. Scope is limited to this phase; finish when the gate passes, record evidence in PROGRESS.md and stop. Gate: `wsl -- bash scripts/test.sh` exits 0 with 0 failed, 0 xpassed and exactly 7 xfailed, and `git diff origin/main -- proton_sync.py` is empty."
todos:
  - id: p01-0-preflight
    content: "Preflight: read PROGRESS.md, confirm the active phase is 1; read PROTON_DRIVE_SYNC_MASTER_PLAN.md §4, §8, Appendix A"
    status: completed
  - id: p01-0b-wsl
    content: "Finish WSL setup on this PC (section 'WSL setup after the restart'): Ubuntu on WSL2, non-root default user, python3/venv/pip/gettext; record the distro in PROGRESS.md"
    status: completed
    dependencies: [p01-0-preflight]
  - id: p01-1-task
    content: "PROTON_SYNC_SETTINGS env override in config.py and i18n.py (task 1)"
    status: completed
    dependencies: [p01-0b-wsl]
  - id: p01-2-task
    content: "scripts/test.sh, requirements-dev.txt, pytest.ini, .gitignore (tasks 2-3)"
    status: completed
    dependencies: [p01-1-task]
  - id: p01-3-task
    content: "Fake CLI and fixtures per .cursor/skills/fake-cli-testing (task 4)"
    status: completed
    dependencies: [p01-2-task]
  - id: p01-4-task
    content: "Fake CLI self-tests (task 5)"
    status: completed
    dependencies: [p01-3-task]
  - id: p01-5-task
    content: "Characterization tests of current behavior (task 6)"
    status: completed
    dependencies: [p01-4-task]
  - id: p01-6-task
    content: "Strict-xfail known-bug tests (task 7)"
    status: completed
    dependencies: [p01-5-task]
  - id: p01-7-task
    content: "docs/dev/TESTING.md (task 8)"
    status: completed
    dependencies: [p01-6-task]
  - id: p01-8-gate
    content: "Verify gate: `wsl -- bash scripts/test.sh` exits 0 with 0 failed, 0 xpassed and exactly 7 xfailed, and `git diff origin/main -- proton_sync.py` is empty"
    status: completed
    dependencies: [p01-7-task]
  - id: p01-9-handoff
    content: "Record gate evidence in PROGRESS.md, mark Phase 1 complete there, open the PR and run the review loop, then hand off with `next-phase.sh` (new headless session) and stop"
    status: completed
    dependencies: [p01-8-gate]
---

# Phase 1 – Test harness with a fake Proton CLI

> Part of the Proton Drive Sync roadmap: [`00-roadmap.plan.md`](00-roadmap.plan.md). Spec: `PROTON_DRIVE_SYNC_MASTER_PLAN.md` §4, §8, Appendix A. Rules in `.cursor/rules/` are binding, especially `05-phase-discipline.mdc` and `10-engine-safety.mdc`.

**Phase 1 of 6.** Previous: none. Next: Phase 2 – Detect equal-size edits.
Branch `phase-01-test-harness`. Commit subject: `test(phase-01): add fake proton-drive CLI and engine regression suite`.
Line numbers below refer to upstream commit `5a852e2`. Earlier phases shift them, so locate code by function name.

## Depends on
- **Needs:** the phasing setup merged into `main`. Check: `gh pr view 1 --json state -q .state` prints `MERGED`. **Met** (2026-10-03, merge `f9f186e`).
- **Needs:** WSL with Ubuntu ready on the machine that runs the gate. Check: the last step of "WSL setup after the restart" below. **Not met yet; this phase does it as its first task** (only stop if a step says to ask the user).

## WSL setup after the restart

State on 2026-10-03 (Windows 11 PC, AMD Ryzen 9 7900X): `wsl --install -d Ubuntu --no-launch` was run elevated; virtualization is enabled in firmware; Windows needed a **restart** to finish enabling the Virtual Machine Platform. The user will restart and then paste `/phase 1`. Do these steps in PowerShell, in order. Each is safe to repeat; skip a step whose check already passes.

1. **WSL works.** `wsl --status`. If it still says virtualization or the Virtual Machine Platform is not enabled, **stop** and tell the user: "Restart Windows first (WSL setup is pending a reboot), then paste `/phase 1` again."
2. **Ubuntu is registered.** `wsl -l -v` (output is UTF-16; read it as text). If no `Ubuntu` row: `wsl --install -d Ubuntu --no-launch`. If that needs admin rights, ask the user to approve the prompt (or run it in an admin PowerShell), then re-check. Then `wsl --set-default Ubuntu`. The row must show `VERSION 2`; if not, `wsl --set-version Ubuntu 2`.
3. **A non-root default user exists** (tests must not run as root, or permission-based tests lie). Check: `wsl -d Ubuntu -- id -un` prints something other than `root`. If it prints `root` or the first launch asks for a username, create the user without prompts:
   ```powershell
   wsl -d Ubuntu -u root -- bash -c "id -u mehdi >/dev/null 2>&1 || useradd -m -s /bin/bash -G sudo mehdi; printf '[user]\ndefault=mehdi\n' >> /etc/wsl.conf"
   wsl --terminate Ubuntu
   ```
   (Only append to `/etc/wsl.conf` if it has no `[user]` section yet. The user has no password; it is not needed because packages are installed with `-u root`. The user can set one later with `wsl -u root -- passwd mehdi`.)
4. **Packages.** `wsl -d Ubuntu -u root -- bash -c "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip gettext"`.
5. **Check (this is the Needs check).** All must succeed:
   ```powershell
   wsl -- id -un                                   # not root
   wsl -- python3 -c "import venv, fcntl; print('ok')"
   wsl -- msgfmt --version
   wsl -- grep PRETTY_NAME /etc/os-release         # record this
   ```
   Record the result in `PROGRESS.md` → Notes / decisions as `YYYY-MM-DD: WSL ready: <PRETTY_NAME>, WSL2, user <name>`. This is part of the phase 1 commit (no separate push).

If any step fails in a way not covered here, stop and report the exact command and output to the user. Do not work around it by running tests with Windows Python (that is not gate evidence).

## Before you start
- `PROGRESS.md` must say the active phase is **1**.
- Read the cited spec sections in full.
- Look at the code that already exists. Build on it instead of re-creating it. If the code differs from this plan, follow the code and note the difference in `PROGRESS.md`.

## Goal

Make the engine testable without a Proton account. That means a fake `proton-drive` executable, hermetic pytest
fixtures, a WSL test runner, and a regression suite that pins down current behavior. Known bugs get **strict xfail**
tests that later phases must flip. No behavior change for users, except one tiny test seam (`PROTON_SYNC_SETTINGS`).

## Scope (do these, nothing else)

### Files

- New: `tests/**`, `scripts/test.sh`, `requirements-dev.txt`, `pytest.ini`, `docs/dev/TESTING.md`
- Edit: `config.py` and `i18n.py` (settings-path env override only), `.gitignore` (add `.venv-wsl/`, `.pytest_cache/`)
- Nothing else. Do **not** modify `proton_sync.py` in this phase. If a test seam seems necessary there, find another
  way (env vars, subprocess, fake CLI). If truly impossible, record it in `PROGRESS.md` under Notes / decisions and keep it to a few lines.

### Tasks

1. **Settings test seam.** In `config.py` (`_SETTINGS_PATH`) and `i18n.py` (`SETTINGS_PATH`): if env
   `PROTON_SYNC_SETTINGS` is set and non-empty, use that path; otherwise the current `APP_DIR/settings.json`.
   Evaluate it at import time like today. French comment explaining it exists for tests and packaging (phase 5 builds on it).
2. **Runner.** `scripts/test.sh` (bash, `set -euo pipefail`):
   - refuse to run unless `uname -s` is Linux (print: "run via: wsl -- bash scripts/test.sh");
   - `cd` to repo root; create `.venv-wsl` with `python3 -m venv` if missing; `pip install -q -r requirements-dev.txt`
     only when `requirements-dev.txt` is newer than a stamp file;
   - `exec .venv-wsl/bin/python -m pytest "$@"`.
   - Must work when the repo lives on the Windows filesystem (`/mnt/c/...`). Keep the venv inside the repo dir (gitignored).
3. **Config.** `requirements-dev.txt`: `pytest>=8,<9`. `pytest.ini`: `testpaths = tests`, `addopts = -q -m "not slow" -p no:cacheprovider`,
   register marker `slow`, `xfail_strict = true`. (Root-level `test_glyphes.py` must NOT be collected.)
4. **Fake CLI and fixtures.** Implement exactly the contract in `.cursor/skills/fake-cli-testing/SKILL.md`
   (`tests/fakes/fake_proton_drive.py`, `tests/fakes/remote_state.py`, `tests/conftest.py` with `_isolate`, `fake_drive`,
   `local_tree`, `write_mappings`, `engine`). The `engine` fixture runs `proton_sync.py` as a subprocess with env:
   `HOME`, `XDG_*`, `PROTON_SYNC_SETTINGS` (tmp settings file, contents `{"language": "en"}`), `PROTON_DRIVE_CLI`,
   `FAKE_PROTON_STATE`, `LANG=C.UTF-8`. The fake must be executable (`chmod 0o755` in the fixture) with a
   `#!/usr/bin/env python3` shebang.
5. **Fake CLI self-tests** `tests/test_fake_cli.py`: list JSON shape (wrapped `{"ok","value"}` fields as the engine's `_unwrap` expects),
   upload from cwd with names, glob-escaped names (`a[[]b.txt` → `a[b.txt`), replace semantics, trash hides from list,
   per-file fault produces partial batch failure (stdout per-file line, stderr counter, exit 1, other files stored),
   `--version` text parsed by `proton_sync.cli_version()` regex `cli-drive@(\d+\.\d+\.\d+)`, unknown command exits 2.
6. **Characterization tests** (must PASS on current code) in `tests/test_engine_baseline.py`:
   - `test_first_pass_uploads_tree_under_basename`: source `.../Docs` with nested files → remote `/my-files/Backups/Docs/...` (briefing §3 mapping semantics).
   - `test_second_pass_unchanged_makes_no_uploads_or_listings`: after pass 1, pass 2 makes zero `upload` calls and zero `filesystem list` calls for cached dirs (the auth/account probes on `/` and `/my-files` are allowed; assert on the specific dir paths).
   - `test_size_change_is_uploaded`
   - `test_excluded_names_and_patterns_not_uploaded` (global and per-mapping exclusions).
   - `test_listing_failure_skips_folder_without_upload_or_trash` (fault on `list` of one dir).
   - `test_delete_requires_flag_and_allow_delete`: orphan trashed only with `--delete` AND `allow_delete: true` (`source_kind: "local"`).
   - `test_exit_2_when_auth_probe_fails` (fault `auth`; ~2.5 s because of `check_auth_settled`, acceptable).
   - `test_exit_1_when_lock_held` (hold `fcntl.flock` on the isolated lock file during the run).
   - `test_exit_4_on_account_change` (pre-seed the cache file with `{"__meta__": {"account": "other@example.com"}}` at the isolated cache path).
   - `test_subpath_cold_exits_3` (no prior full pass → `--subpath <dir> --mapping-source <src>` → exit 3, `[subpath-cold-root]` or `[subpath-cold]` tag).
   - `test_symlink_to_file_uploaded_symlinked_dir_not_followed` (characterizes briefing §4 symlink note).
   - `test_partial_batch_failure_retries_individually_and_logs_failure` (one faulty file: others land remotely, `[upload-failed]` printed).
7. **Known-bug tests**, each `@pytest.mark.xfail(strict=True, reason="<phase-N>: <short>")`, in `tests/test_known_bugs.py`:
   - `test_equal_size_edit_is_uploaded`: AAAA→BBBB with newer mtime; expect remote content BBBB. (phase-02)
   - `test_equal_size_edit_detected_by_comparator`: in-process port of briefing Appendix A; assert the default comparator requests upload. (phase-02)
   - `test_batch_recovery_not_fooled_by_old_equal_size_remote`: remote has old same-size content, batch fails for that file → expect it retried and ends BBBB or reported failed (not silently "already uploaded"). (phase-02)
   - `test_upload_failure_exits_nonzero`: a persistently failing file → expect exit code 5. (phase-03)
   - `test_subpath_upload_failure_exits_nonzero`: same through `--subpath` after a full pass made the tree warm → expect 5. (phase-03)
   - `test_exclusion_added_later_keeps_remote_copy`: file uploaded, then excluded, then `--delete` pass with `allow_delete` → expect remote copy NOT trashed. (phase-04)
   - `test_headless_run_does_not_rename_extensions_on_modern_cli`: `IMG.JPG` locally, no `rename_ext_enabled` key in settings, fake CLI 0.8.0 → expect local name unchanged. (phase-05)
   Each must currently fail for the stated reason (strict xfail enforces that it does not pass by accident).
8. **Docs.** `docs/dev/TESTING.md`: how to run (WSL), the fake CLI's capabilities and fault injection, how to write an engine test, the xfail convention ("a phase that fixes a bug removes the xfail marker").

### Required tests

Each must assert the behavior and fail on the code before this phase (say how you checked in the PR).

All tests listed in tasks 5–7 (names may differ slightly if clearer; keep one test per bullet).

### Acceptance criteria

- **AC-1** `wsl -- bash scripts/test.sh` passes from a clean clone on Ubuntu WSL (first run creates the venv). Summary shows passes plus exactly the 7 xfails above, 0 failures, 0 xpass.
- **AC-2** The suite never touches the real home: running it with a sentinel `~/.proton-drive-sync` absent leaves it absent (assert in a session-finish hook or a dedicated test), and no `settings.json` appears in the repo root.
- **AC-3** No network, no real CLI: if `PROTON_DRIVE_CLI` is unset inside a test, the engine fixture fails loudly rather than finding a real binary.
- **AC-4** `proton_sync.py` is unchanged (`git diff main -- proton_sync.py` empty).
- **AC-5** Without `PROTON_SYNC_SETTINGS`, `config._SETTINGS_PATH` and `i18n.SETTINGS_PATH` equal their previous values (unit test).
- **AC-6** Total runtime < 60 s in WSL.
- **AC-7** Every `xfail` has `strict=True` and a reason naming the phase that will fix it.

## Out of scope (do NOT start these, even partially)
- Phase 2 – Detect equal-size edits → `phase-02-equal-size-edits.plan.md`
- Everything in later phases (see `00-roadmap.plan.md`)
- Any engine fix, even if trivial. Note discovered bugs under Deferred in `PROGRESS.md`, tagged with the phase that should own them. If one is serious, add another strict xfail.

Do not create files, services, stubs, settings or UI that belong to a later phase. If something here seems to need later-phase work, write the smallest thing that unblocks this phase, then add a note under "Deferred" in `PROGRESS.md`.

## Gate
**`wsl -- bash scripts/test.sh` exits 0 with 0 failed, 0 xpassed and exactly 7 xfailed, and `git diff origin/main -- proton_sync.py` is empty.**

Prove it: run the command, and paste the command and its result (exit code, the pytest summary line) into Phase 1's row in `PROGRESS.md`. Name the OS that ran it (e.g. `Ubuntu 24.04 on WSL2, Windows 11`, from `wsl -- grep PRETTY_NAME /etc/os-release`). Anything not run (real Proton account, real systemd, Arch) is written as not run, with who runs it.

## When the gate passes
1. Mark every todo in this file `completed`.
2. In `PROGRESS.md`: mark Phase 1 done with the date and evidence, and set the active phase to **2**.
3. Commit with a conventional message scoped `phase-01`, push branch `phase-01-test-harness`, open the PR, and run the review loop in `.cursor/skills/phase/SKILL.md`.
4. **Hand off** after the merge: run `bash .cursor/skills/phase/next-phase.sh`, report the PR URL and its `NEXT:` line, and stop. Never start the next phase in the same chat.

## Manual test (for the human)

```powershell
wsl -- bash scripts/test.sh            # expect: N passed, 7 xfailed
wsl -- bash scripts/test.sh -k baseline -vv
```
