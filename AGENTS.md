# AGENTS.md

This repository is the maintained project. It was forked from [lafontaj/proton-drive-cli-sync](https://github.com/lafontaj/proton-drive-cli-sync) and is not developed by sending pull requests upstream.
It is a Proton Drive sync for Linux built around Proton's official `proton-drive` CLI.
A mapping with `"direction": "twoway"` uploads and downloads. Every other mapping stays upload-only.
The goal is a version we control and can publish for anyone to use at their own risk:
correct change detection, honest success/failure reporting, safe deletion semantics, tests, and Arch packaging.

Start with `PROGRESS.md` (active phase), then `.cursor/rules/00-core.mdc` and the active plan in `.cursor/plans/`.
Phases run with `/phase <N>` (`.cursor/skills/phase/SKILL.md`). Spec: `PROTON_DRIVE_SYNC_MASTER_PLAN.md`.

## Map

| Path | What it is |
| --- | --- |
| `proton_sync.py` | The engine (scan, compare, upload, trash, cache, exit codes). Most phases touch this. |
| `config.py` | Settings, state paths, CLI resolution. |
| `realtime_consumer.py` / `local_watcher.py` | Real-time trigger: watcher writes markers, consumer runs engine `--subpath`. |
| `schedule_manager.py` / `realtime_manager.py` | Generate systemd user units. |
| `mount_check.py` | Deletion guard (source mounted and readable). |
| `proton_mapping_editor.py` | Tkinter GUI (7k lines). Touch only where a plan says so. |
| `tests/` | pytest suite with a fake `proton-drive` CLI (created in phase 1). Run in WSL. |
| `.cursor/` | Rules, plans, the `phase` skill (with the local review script) and the `fake-cli-testing` skill. |
| `.github/workflows/tests.yml` | The only workflow. Manual (`workflow_dispatch`). |
| `UPSTREAM.md` | Every upstream file this fork changed. |
| `docs/dev/SETUP.md` | One-time machine setup (WSL, Claude CLI, gh). |
