---
name: "Proton Drive Sync – Roadmap (index only, do not Build)"
overview: "Index for the proton-drive-cli-sync fork. It explains the architecture and the order of the numbered phase plans. It contains no implementation work. Each todo is completed by finishing the matching phase-NN-*.plan.md and passing its gate. Do not press Build on this file; open the active phase plan instead."
todos:
  - id: phase-01-test-harness
    content: "1 – Test harness with a fake Proton CLI → complete phase-01-test-harness.plan.md"
    status: pending
  - id: phase-02-equal-size-edits
    content: "2 – Detect equal-size edits → complete phase-02-equal-size-edits.plan.md"
    status: pending
    dependencies: [phase-01-test-harness]
  - id: phase-03-run-results
    content: "3 – Honest run results → complete phase-03-run-results.plan.md"
    status: pending
    dependencies: [phase-02-equal-size-edits]
  - id: phase-04-deletion-safety
    content: "4 – Deletion and exclusion safety → complete phase-04-deletion-safety.plan.md"
    status: pending
    dependencies: [phase-03-run-results]
  - id: phase-05-headless-defaults-and-paths
    content: "5 – Headless defaults and file locations → complete phase-05-headless-defaults-and-paths.plan.md"
    status: pending
    dependencies: [phase-04-deletion-safety]
  - id: phase-06-arch-packaging-release
    content: "6 – Arch packaging, safe units, diagnostics, public release → complete phase-06-arch-packaging-release.plan.md"
    status: pending
    dependencies: [phase-05-headless-defaults-and-paths]
---

# Proton Drive Sync roadmap

This repo is a community fork of `lafontaj/proton-drive-cli-sync` (forked at `5a852e2`): a **one-way local → Proton Drive**
backup tool for Linux around Proton's official `proton-drive` CLI. The goal is a version we control and can publish for
anyone to use at their own risk. The spec is `PROTON_DRIVE_SYNC_MASTER_PLAN.md` (the engineering briefing). Plans cite it as §N.

## Architecture

```
systemd timer ─┐                                   ┌─> proton-drive CLI (official, SDK-backed) ─> Proton Drive
GUI (Tkinter) ─┼─> proton_sync.py (engine) ────────┤
local_watcher ─> queue markers ─> realtime_consumer ┘   cache / health / last-run under ~/.proton-drive-sync/
```

- `proton_sync.py` decides what to upload/trash. It is the only module that calls the CLI for transfers.
- `config.py` owns settings and state paths. `schedule_manager.py` / `realtime_manager.py` generate systemd user units.
- The real-time consumer reacts to the engine's **exit codes and stable output tags**. Those are an API (see `00-core.mdc`).
- Tests drive the real engine against a **fake CLI executable** (phase 1), never a real account.

## Phases

| # | Phase | Gate (one line) |
|---|---|---|
| 1 | Test harness with a fake Proton CLI | WSL suite green, 7 strict xfails documenting known bugs, engine untouched |
| 2 | Detect equal-size edits | same-size edits uploaded, batch recovery fixed, cache format unchanged, 4 xfails left |
| 3 | Honest run results | partial failure → exit 5 + `last-run.json`, consumer never acks unfinished work, 2 xfails left |
| 4 | Deletion and exclusion safety | excluded remote copies kept, mass-delete guard, mount re-check, 1 xfail left |
| 5 | Headless defaults and file locations | no headless extension renaming, settings in `~/.config`, 0 xfails |
| 6 | Arch packaging, safe units, diagnostics, public release | PKGBUILD + escaped units + doctor + public README, suite green |

## Not planned yet (needs a planning session first)

From spec §6–§10. Much larger, and better in a separate repository:

- SDK/event experiment: a TypeScript or C# client on Proton's SDK, persisted event cursor that survives restart.
- Two-way prototype: one mapping, SQLite state, explicit conflict handling (spec §7 table).
- Desktop status UI and file-manager integration.
- Ask Proton maintainers about the Linux daemon's public boundary first (spec §10).
