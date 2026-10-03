# Proton Drive Sync build progress

Read this file **before** any work. It is the single source of truth for which phase is active. Rules: `.cursor/rules/05-phase-discipline.mdc`. Roadmap: `.cursor/plans/00-roadmap.plan.md`.

**Active phase:** 1 – Test harness with a fake Proton CLI (not started) → `.cursor/plans/phase-01-test-harness.plan.md`
**Next:** 2 – Detect equal-size edits (not started)

| Phase | Plan | Status | Gate evidence | Date |
|---|---|---|---|---|
| 1 | `phase-01-test-harness.plan.md` | not started | | |
| 2 | `phase-02-equal-size-edits.plan.md` | not started | | |
| 3 | `phase-03-run-results.plan.md` | not started | | |
| 4 | `phase-04-deletion-safety.plan.md` | not started | | |
| 5 | `phase-05-headless-defaults-and-paths.plan.md` | not started | | |
| 6 | `phase-06-arch-packaging-release.plan.md` | not started | | |

## Handoff (2026-10-03)

**Where we are**
- Fork of `lafontaj/proton-drive-cli-sync` at `5a852e2`. The phasing setup is merged into `main` (PR #1, `f9f186e`).
- No CI on pull requests. `.github/workflows/tests.yml` is manual (`workflow_dispatch`) only. Reviews run locally via `.cursor/skills/phase/review.sh`.
- WSL is installed but waits for a Windows restart. Phase 1 finishes the WSL setup itself as its first task (see "WSL setup after the restart" in the phase 1 plan).

**Who does what**
- Cursor: code changes, using `/phase <N>` or `/phase <N> resume`.
- Claude Code: orchestration. Checks PR and review state, decides the next step, and updates this file and the plans.
- User: approves pushes, posts anything public, and decides when the next phase starts.

**Prompt to give Cursor**
```
/phase 1

Build the test harness from .cursor/plans/phase-01-test-harness.plan.md: fake proton-drive CLI, hermetic pytest fixtures, scripts/test.sh for WSL, baseline tests and the 7 strict-xfail known-bug tests. Do not change proton_sync.py. Run `wsl -- bash scripts/test.sh`, record the summary line and the WSL distro in this file, open the PR, run the local review loop, and stop after the merge.
```

## Deferred
- [Not planned] SDK/event experiment, two-way prototype, desktop status UI (see roadmap "Not planned yet"). Noticed while planning, 2026-10-03.
- [Human, after phase 6] Publish to the AUR, tag `v2.0.0`, run `makepkg`/`namcap` on Arch. Noticed while planning, 2026-10-03.
- [Human, any time] Run the read-only inventory from spec §5 on Nizar's machine (after phase 6: `proton-drive-sync-doctor --redact`) to learn whether deletion, rename-ext or equal-size edits affect his setup. Noticed while planning, 2026-10-03.

## Notes / decisions
- 2026-10-03: Forked at upstream `5a852e218d353209a3b39cabdb4b810d0f254177`, the commit the spec reviewed. Upstream remote is `upstream`.
- 2026-10-03: Review budget for this project is **2 rounds per PR** (round 1 full, round 2 verify). Set by the user for cost reasons; enforced by `PHASE_REVIEW_MAX_ROUNDS` in `.cursor/skills/phase/review.sh`. After round 2, Cursor fixes what is listed, pushes once, and stops without merging if the verdict was not Ready to merge.
- 2026-10-03: Tests run in WSL (`wsl -- bash scripts/test.sh`) because the engine needs `fcntl`, `/proc` and systemd. Windows Python results do not count as gate evidence.
- 2026-10-03: The spec is the engineering briefing, renamed `PROTON_DRIVE_SYNC_MASTER_PLAN.md` with headings turned into `# N.`. The surname of the user it was written for was removed from the public copy.
- 2026-10-03: Upstream files edited by this fork are listed in `UPSTREAM.md` so fixes can be offered back to upstream later.
