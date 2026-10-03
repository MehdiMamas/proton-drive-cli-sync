# /phase-status

Report where the project stands. Read-only: do not change anything.

1. Read `PROGRESS.md` (active phase, Next, the phase table, Deferred) and `.cursor/plans/00-roadmap.plan.md`.
2. For each phase, find its PR: `gh pr list --state all --search "head:phase-<NN>-" --json number,state,title,url,mergedAt`.
3. For an open PR, find the latest review: `gh pr view <n> --json comments` → comments starting with `## Phase`, highest
   `round:` in the `<!-- reviewed-sha: … round: r -->` marker. Report its verdict, round (budget is 2), and whether the
   reviewed sha equals the PR head (`gh pr view <n> --json headRefOid`).
4. Output a table: Phase | Title | PR | State (not started / in progress / in review / waiting for user / merged) | Next action.
   Flag any mismatch between `PROGRESS.md` and GitHub.
