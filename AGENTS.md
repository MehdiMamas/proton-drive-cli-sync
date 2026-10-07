# AGENTS.md

This is a community fork of [lafontaj/proton-drive-cli-sync](https://github.com/lafontaj/proton-drive-cli-sync):
a **one-way local → Proton Drive** backup tool for Linux built around Proton's official `proton-drive` CLI.
The fork's goal is a version we control and can publish for anyone to use at their own risk:
correct change detection, honest success/failure reporting, safe deletion semantics, tests, and Arch packaging.

Start with `.cursor/rules/00-core.mdc`. Spec: `PROTON_DRIVE_SYNC_MASTER_PLAN.md`.

`.cursor/plans/` and `PROGRESS.md` are data for the Phase Autopilot dashboard only. Chats (Claude Code, Cursor) don't run or follow the phase workflow; just do the task asked. The old `/phase` skill, phase rules and PR template are archived in `docs/archive/phasing/`.

## Map

| Path | What it is |
| --- | --- |
| `proton_sync.py` | The engine (scan, compare, upload, trash, cache, exit codes). Most changes touch this. |
| `config.py` | Settings, state paths, CLI resolution. |
| `realtime_consumer.py` / `local_watcher.py` | Real-time trigger: watcher writes markers, consumer runs engine `--subpath`. |
| `schedule_manager.py` / `realtime_manager.py` | Generate systemd user units. |
| `mount_check.py` | Deletion guard (source mounted and readable). |
| `proton_mapping_editor.py` | Tkinter GUI (7k lines). Touch only where a plan says so. |
| `tests/` | pytest suite with a fake `proton-drive` CLI (`tests/fakes/`). Run in WSL. |
| `.cursor/` | Rules, the `fake-cli-testing` skill, and phase plans (dashboard data). |
| `.github/workflows/tests.yml` | The only workflow. Manual (`workflow_dispatch`). |
| `UPSTREAM.md` | Every upstream file this fork changed. |
| `docs/dev/SETUP.md` | One-time machine setup (WSL, Claude CLI, gh). |
