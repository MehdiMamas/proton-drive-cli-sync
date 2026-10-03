---
name: "Proton Drive Sync Phase 6 – Arch packaging, safe units, diagnostics, public release"
overview: "Phase 6 of 6. Arch packaging, safe units, diagnostics, public release. Scope is limited to this phase; finish when the gate passes, record evidence in PROGRESS.md and stop. Gate: `wsl -- bash scripts/test.sh` exits 0 with 0 failed, and `wsl -- bash -n packaging/arch/PKGBUILD` exits 0. makepkg, namcap and a real Arch install are recorded as NOT run (human task)."
todos:
  - id: p06-0-preflight
    content: "Preflight: read PROGRESS.md, confirm the active phase is 6 and the Phase 5 gate is recorded with command output; read PROTON_DRIVE_SYNC_MASTER_PLAN.md §5, §8, §9"
    status: completed
  - id: p06-1-task
    content: "Launcher/path helper, systemd_quote, unit generation and backward-compatible parsers (task 1)"
    status: completed
    dependencies: [p06-0-preflight]
  - id: p06-2-task
    content: "doctor.py with --redact (task 2)"
    status: completed
    dependencies: [p06-1-task]
  - id: p06-3-task
    content: "packaging/arch/: PKGBUILD, .install, launchers, desktop file (task 3)"
    status: completed
    dependencies: [p06-2-task]
  - id: p06-4-task
    content: "README, LICENSE, VERSION, CHANGELOG, RELEASING, SECURITY (task 4)"
    status: completed
    dependencies: [p06-3-task]
  - id: p06-5-task
    content: "Suite runs under makepkg check() assumptions (task 5)"
    status: completed
    dependencies: [p06-4-task]
  - id: p06-8-gate
    content: "Verify gate: `wsl -- bash scripts/test.sh` exits 0 with 0 failed, and `wsl -- bash -n packaging/arch/PKGBUILD` exits 0. makepkg, namcap and a real Arch install are recorded as NOT run (human task)"
    status: completed
    dependencies: [p06-5-task]
  - id: p06-9-handoff
    content: "Record gate evidence in PROGRESS.md, mark Phase 6 complete there, open the PR and run the review loop, then hand off with `next-phase.sh` (new headless session) and stop"
    status: completed
    dependencies: [p06-8-gate]
---

# Phase 6 – Arch packaging, safe units, diagnostics, public release

> Part of the Proton Drive Sync roadmap: [`00-roadmap.plan.md`](00-roadmap.plan.md). Spec: `PROTON_DRIVE_SYNC_MASTER_PLAN.md` §5, §8, §9. Rules in `.cursor/rules/` are binding, especially `05-phase-discipline.mdc` and `10-engine-safety.mdc`.

**Phase 6 of 6.** Previous: Phase 5 – Headless defaults and file locations. Next: none (last planned phase).
Branch `phase-06-arch-packaging-release`. Commit subject: `feat(phase-06): Arch PKGBUILD, escaped systemd units, doctor, public README`. Depends on: phase 5.
Line numbers below refer to upstream commit `5a852e2`. Earlier phases shift them, so locate code by function name.

## Before you start
- `PROGRESS.md` must say the active phase is **6**. The Phase 5 gate must be recorded with command output. If it is not, stop and tell the user.
- Read the cited spec sections in full.
- Look at the code that already exists. Build on it instead of re-creating it. If the code differs from this plan, follow the code and note the difference in `PROGRESS.md`.

## Goal

Someone on Arch can build and install the fork with `makepkg -si`, set up the nightly timer, and get a clear diagnosis
when something is wrong. The repo presents itself honestly as a community fork, used at your own risk.

## Design

### Install layout (package)
- Program files: `/usr/lib/proton-drive-cli-sync/` (all `.py`, `locale/`, icons). Nothing writable there.
- Launchers in `/usr/bin/` (small `sh` wrappers that `exec python3 /usr/lib/proton-drive-cli-sync/<script> "$@"`):
  `proton-drive-sync` (engine), `proton-drive-sync-gui` (mapping editor), `proton-drive-sync-doctor` (new).
- Desktop entry `/usr/share/applications/proton-drive-sync.desktop`, icon under `/usr/share/icons/hicolor/…/apps/`.
- License `/usr/share/licenses/<pkgname>/LICENSE`, docs `/usr/share/doc/<pkgname>/`.
- User data stays in `~/.config/proton-drive-sync/` (phase 5) and `~/.proton-drive-sync/`.

### PKGBUILD (`packaging/arch/PKGBUILD`, VCS package)
- Name: check the AUR for conflicts first (`https://aur.archlinux.org/rpc/v5/search/proton-drive?by=name`). Pick a
  non-conflicting `-git` name (proposal: `proton-drive-cli-sync-git`; if taken, `proton-drive-cli-sync-fork-git`). Record it in `PROGRESS.md` under Notes / decisions.
- `source=("git+https://github.com/<owner>/proton-drive-cli-sync.git")`, `pkgver()` from `git describe --long --tags` with fallback to `r<count>.<shortsha>`.
- `depends=(python tk python-pyinotify)`. `optdepends`: tray (`python-gobject`, `xapp`, check `tray_indicator.py`
  imports), `libsecret`/`gnome-keyring` or `pass` (CLI credential storage, briefing §2), and the Proton CLI itself:
  check the AUR for a `proton-drive` CLI package; if one exists, name it; otherwise document the manual download from
  `https://proton.me/download/drive/cli/index.html` in the post-install message.
- `checkdepends=(python-pytest)`, `check()` runs the suite (it must pass in a clean chroot: no network, no home writes).
- `package()` installs exactly the layout above. `namcap`-clean as far as can be checked without Arch (document how the human runs `namcap`).
- `.install` file printing post-install steps (CLI install, first GUI run or mappings file, timer enable, `loginctl enable-linger` note: lingering does not unlock a keyring, briefing §5).
- Keep `packaging/arch/.SRCINFO` generation instructions (human runs `makepkg --printsrcinfo > .SRCINFO` on Arch).

### systemd unit generation (`schedule_manager.py`, `realtime_manager.py`)
- Engine/consumer path resolution: if running from `/usr/lib/proton-drive-cli-sync`, `ExecStart` uses `/usr/bin/proton-drive-sync`
  (stable across upgrades); otherwise the current `python3 <APP_DIR>/proton_sync.py`. One helper, used by both managers.
- **Escaping:** a helper `systemd_quote(arg)` implementing systemd's `ExecStart` rules: wrap in double quotes when needed,
  escape `\` and `"`, and `%` → `%%` (specifier). Apply it to every path and argument in `ExecStart=` and the value in `Environment=`.
- Parsers that read units back (`read_service_mappings_path`, `read_service_delete`, the consumer's `ExecStart` regex ~L758)
  must handle quoted paths with spaces and still read units generated by older versions.
- Keep phase 3's `RestartPreventExitStatus=5`.

### Doctor (`doctor.py` + launcher)
Read-only report of the briefing §5 inventory, safe to paste into an issue:
- CLI path resolution chain and `proton-drive --version`; engine/fork version and git commit if a checkout.
- `systemctl --user cat/list-timers/show -p Result -p ExecMainStatus` for the sync service/timer and real-time units; linger status.
- `last-run.json` and `health.json` summaries; last 50 journal lines of the service.
- Effective settings (rename-ext decision and why, thresholds) and, per mapping: type, `allow_delete`, `delete_mode`, `excluded_remote`, `source_kind`, `conflict_mode`, exclusion counts.
- Session facts relevant to unattended auth: `DBUS_SESSION_BUS_ADDRESS` set?, Secret Service reachable? (`busctl --user status org.freedesktop.secrets` or equivalent, best-effort), `PROTON_DRIVE_CREDENTIALS_STORE`.
- `--redact` (recommend it in the output header): replaces home paths with `~`, other absolute paths with `<path#n>`, emails with `<account>`.
- Every external command has a timeout, and failures are reported, never fatal. Exit 0 always (it's a report).

### Public-facing repo
- `README.md` top section (English, before the existing content): what this fork is, the one-way model in one paragraph,
  **disclaimer** ("community software, not affiliated with or endorsed by Proton AG; use at your own risk; test with a throwaway folder first; keep independent backups"),
  install (AUR/makepkg and manual), quick start, link to `CHANGELOG.md`, `docs/change-detection.md`, credits to the upstream author and project.
  Keep the upstream README content below, unchanged except obvious path fixes.
- `LICENSE`: keep the original copyright line, add a line for fork contributors. MIT stays.
- `VERSION` file with `2.0.0` and CHANGELOG `## [2.0.0] - <date>` collecting phases 2–6. Tag creation is done by the human after merge.
- `docs/RELEASING.md`: tag → build in clean Arch (container or `extra-x86_64-build`) → `namcap` → update AUR repo (`.SRCINFO`) → announce. Human-only steps clearly marked.
- `SECURITY.md`: how to report issues; never post un-redacted doctor output publicly.

## Scope (do these, nothing else)

### Tasks

1. Path/launcher helper + unit generation changes + `systemd_quote` + backward-compatible parsers.
2. `doctor.py` + redaction.
3. `packaging/arch/` (PKGBUILD, `.install`, launchers, desktop file).
4. README/LICENSE/VERSION/CHANGELOG/RELEASING/SECURITY.
5. Ensure the test suite passes inside `check()` assumptions (no writes outside tmp, no network, no display needed: GUI not imported by tests).

### Required tests

Each must assert the behavior and fail on the code before this phase (say how you checked in the PR).

- `test_systemd_quote_spaces_quotes_percent_backslash` (table-driven)
- `test_service_unit_with_space_in_mappings_path_roundtrips` (generate → parse back the same path)
- `test_legacy_unquoted_unit_still_parsed`
- `test_packaged_install_uses_usr_bin_launcher` (simulate APP_DIR under a fake `/usr/lib/proton-drive-cli-sync` via monkeypatch)
- `test_consumer_unit_generation_escaped` (realtime_manager)
- `test_doctor_redact_removes_emails_and_paths` (seed settings/mappings/last-run with an email and paths, run doctor with `--redact`, assert none appear)
- `test_doctor_survives_missing_systemctl_and_cli` (PATH without them → still exit 0 with "not available" lines)
- `test_pkgbuild_syntax` (`bash -n packaging/arch/PKGBUILD`; and every file referenced in `package()` exists in the repo)
- `test_launchers_exec_correct_scripts` (parse the wrapper files)

### Acceptance criteria

- **AC-1** `makepkg` layout matches the design. The PKGBUILD passes `bash -n`. `check()` runs the suite. Documented `namcap` step.
- **AC-2** Units generated for paths containing spaces, quotes or `%` start correctly (verified by round-trip tests and by `systemd-analyze verify` instructions in RELEASING.md for the human).
- **AC-3** Units from older versions are still read correctly by the GUI/managers.
- **AC-4** `proton-drive-sync-doctor --redact` prints the full §5 inventory with no emails or absolute personal paths.
- **AC-5** README starts with the fork notice + disclaimer + credits. LICENSE keeps the upstream copyright. CHANGELOG has 2.0.0.
- **AC-6** No workflow triggers added. No AUR push, no tag push (human-only).
- **AC-7** Full suite green.

## Out of scope (do NOT start these, even partially)
- Everything listed under "Not planned yet" in `00-roadmap.plan.md`
- Publishing to the AUR, creating tags/releases, a Flatpak, a new GUI, two-way sync.

Do not create files, services, stubs, settings or UI that belong to a later phase. If something here seems to need later-phase work, write the smallest thing that unblocks this phase, then add a note under "Deferred" in `PROGRESS.md`.

## Gate
**`wsl -- bash scripts/test.sh` exits 0 with 0 failed, and `wsl -- bash -n packaging/arch/PKGBUILD` exits 0. makepkg, namcap and a real Arch install are recorded as NOT run (human task).**

Prove it: run the command, and paste the command and its result (exit code, the pytest summary line) into Phase 6's row in `PROGRESS.md`. Name the OS that ran it (e.g. `Ubuntu 24.04 on WSL2, Windows 11`, from `wsl -- grep PRETTY_NAME /etc/os-release`). Anything not run (real Proton account, real systemd, Arch) is written as not run, with who runs it.

## When the gate passes
1. Mark every todo in this file `completed`.
2. In `PROGRESS.md`: mark Phase 6 done with the date and evidence, and set the active phase to **none (all planned phases done)**.
3. Commit with a conventional message scoped `phase-06`, push branch `phase-06-arch-packaging-release`, open the PR, and run the review loop in `.cursor/skills/phase/SKILL.md`.
4. **Hand off** after the merge: run `bash .cursor/skills/phase/next-phase.sh`, report the PR URL and its `NEXT:` line, and stop. Never start the next phase in the same chat.

## Manual test (for the human, on Arch)

```bash
cd packaging/arch && makepkg -si
proton-drive-sync-doctor --redact | less
proton-drive-sync-gui        # create a mapping to a test folder, schedule it
systemctl --user cat proton-sync.service   # ExecStart uses /usr/bin/proton-drive-sync, paths quoted
systemctl --user start proton-sync.service && journalctl --user -u proton-sync.service -n 30
```
