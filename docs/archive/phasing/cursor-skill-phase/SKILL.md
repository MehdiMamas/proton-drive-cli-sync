---
name: phase
description: >-
  Execute one Proton Drive Sync phase from PROGRESS.md through its gate, open a pull
  request, fix Claude's review until it says Ready to merge, merge it, then start the next phase in a new headless session.
  Invoke as /phase alone to run the next phase from PROGRESS.md, or as /phase followed by a single phase number, for example /phase 3.
  Add resume (/phase resume or /phase <number> resume) to pick up an open phase pull request.
disable-model-invocation: true
---

# Execute one Proton Drive Sync phase

Invoked as `/phase`, `/phase <number>`, `/phase resume` or `/phase <number> resume`. Without a number, run the next phase (see **Argument**). One phase per branch and one pull request. Run the review loop below until Claude's review says **Ready to merge**, merge, then hand off to a new session (see **Hand off**). Never start the next phase in this chat. Do the work in this checkout. Never create a git worktree or a sibling folder.

With `resume`, the pull request for this phase already exists: check out its branch, skip to **Review loop**, and start at step 1 for the current head commit.

## Argument

1. Read the phase number from the user message. Accept `3` or `03`. Reject anything that is not a whole number with a matching plan file, and tell the user to run `/phase 3`. Zero-pad it to two digits (`NN`) for file and branch names.
   - **No number, no `resume`:** read `PROGRESS.md` on `origin/main` (`git fetch origin && git show origin/main:PROGRESS.md`) and take the lowest-numbered phase in the table that is not `completed`. If it already has an open pull request (`gh pr list --state open --head <branch>`), switch to `resume` for it. If every phase is completed, say so and stop. Tell the user which phase you picked before you edit anything.
   - **`resume` with no number:** list open pull requests whose head branch matches `phase-NN-*` (`gh pr list --state open --json number,headRefName`). Exactly one: resume that phase. None or more than one: stop, list them, and ask which number.
2. Read `PROGRESS.md`. The number must be the active phase. If it is not, stop and say which phase is active. With `resume`, the phase may already be marked `completed` on the branch; check `PROGRESS.md` on `origin/main` instead.
3. Open the one plan `.cursor/plans/phase-<NN>-*.plan.md`. The branch name is that filename without `.plan.md` (`phase-03-contracts`).

## Before editing

1. Read that plan in full, including Out of scope.
2. Read the master-plan sections the plan cites (§N).
3. Confirm the previous phase's gate cell contains a command, an exit result, or a CI URL. If it is only a sentence, stop and tell the user.
4. Read every rule in `.cursor/rules/` whose description or globs match the work: `10-engine-safety.mdc` (engine, consumer, scheduler, config), `50-testing.mdc`, `55-python-style-i18n.mdc`, `60-build-release.mdc`. For any test work, also read `.cursor/skills/fake-cli-testing/SKILL.md`.

## Environment (Windows dev machine)

- Cursor's terminal is PowerShell. Run `git`, `gh` and `python` there.
- All Python execution and tests run in **WSL**: `wsl -- bash scripts/test.sh [pytest args]`. Windows Python results never count as gate evidence (`fcntl`, `/proc` and systemd do not exist there).
- The review script needs Git Bash, because plain `bash` in PowerShell may start WSL, where `claude` and `gh` are not installed:
  `& "C:\Program Files\Git\bin\bash.exe" .cursor/skills/phase/review.sh <n>`.

## While editing

- Do the todos in the active plan. Nothing from a later phase: no stubs, empty services, or placeholder files.
- New behavior goes in new files. Touch upstream files as little as possible and list each one in `UPSTREAM.md`.
- If the plan disagrees with the code, update that phase's plan and note it under **Notes / decisions** in `PROGRESS.md`.
- Later-phase work that the current gate does not need goes under **Deferred** in `PROGRESS.md`, with the phase name.

## Search before you call a string change done

When the phase changes an identity string, folder, protocol, mutex, endpoint, or URL, follow `07-complete-search.mdc`.

1. Search the old string with no hit cap. Page until a page is empty.
2. Search siblings: leading dot, `-dev`, and the other product's name (`app-dev` and `.app-dev` are different directories).
3. Open every writer and every reader of that path.
4. Keep npm package names and upstream test fixtures. Change runtime paths.
5. Write the leftover hits, and why they stay, into `PROGRESS.md`.

## Gate

Follow `08-gate-proof.mdc`.

1. Run the gate command from the phase plan.
2. Put the command and the result in the phase row of `PROGRESS.md`, with the date.
3. Mark that phase `completed`. Set **Active phase** to the following phase and **Next** to the one after it, both still `not started`.
4. If a check did not run, say so in the gate cell and name the phase that owns it.

## Pull request

Branch from current `main` using the plan filename (`phase-03-contracts`).

Commit only this phase, after the gate evidence is in `PROGRESS.md`. Message style is the phase handoff: a conventional subject that names the phase.

Push and open the pull request with `gh pr create`. Use `.github/pull_request_template.md` and add the review block below. Do not open it as a draft; drafts are not reviewed. Do not request a reviewer by guessing a username. Tell the user the URL, then go to **Review loop**.

```markdown
## What changed
<phase number and one paragraph>

## How to test
<the gate command and its result>

## Review for Claude
- [ ] Only this phase's plan todos are implemented. No later-phase files or stubs.
- [ ] Gate evidence is command output, and it names the OS that actually ran.
- [ ] Every changed identity, path, protocol, or endpoint was searched with no hit cap. Readers and writers match. Sibling folders (`-dev`, leading dot) were checked.
- [ ] Upstream edits (if any) are listed in `UPSTREAM.md` and stay small.
- [ ] The project's architecture rules in `.cursor/rules/` hold for every changed file.
- [ ] Deferred items in `PROGRESS.md` name a later phase.
```

## Review loop

The review runs on this machine with the Claude Code CLI, not in GitHub Actions. `.cursor/skills/phase/review.sh` reviews the pushed head commit against the instructions in `review-prompt.md` on `origin/main`, posts one summary comment that starts with `## Phase <X> review (round <r>) — <verdict>` and ends with `<!-- reviewed-sha: <sha> round: <r> -->`, and posts a new comment each round. Pushing does not start a review; you start it.

### 1. Review the head commit

1. Push, and make sure the working tree is clean and `git rev-parse HEAD` equals `gh pr view <n> --json headRefOid`. The script refuses to run otherwise.
2. Run `& "C:\Program Files\Git\bin\bash.exe" .cursor/skills/phase/review.sh <n>` (from PowerShell; see **Environment**). It takes a while (often 10–40 minutes). If your terminal tool would time out, run it in the background with output redirected to a log file, and check the log every 2 minutes until it prints `VERDICT:` or exits.
3. The last lines print `Report: <path>` and `VERDICT: <verdict>`. Read the whole report at that path.

If the script exits non-zero, stop and tell the user, without merging, with its error output. Exit code 3 means the PR has used its review budget (see below): that is a stop, not an error to work around.

### 2. Act on the verdict

- **Changes needed:** go to **Fixing review feedback**, then back to step 1.
- **Ready to merge:** go to **Merge**.
- **Needs user** or **Blocked:** stop. Tell the user the verdict, the open items and the PR URL. Do not merge and do not hand off.

**Review budget for this project: 2 rounds per PR** (`PHASE_REVIEW_MAX_ROUNDS` in `review.sh`; the user chose it to keep costs down). Round 1 is the full review. Round 2 is the final one and only checks the fixes. So:

- After round 1 **Changes needed**: one fix round (all of **For Cursor** in one push), then round 2.
- After round 2 **Ready to merge**: merge.
- After round 2 anything else that lists items under **For Cursor**: fix them all in one push, post a short PR comment mapping each item to its commit, then **stop without merging** and tell the user. There is no round 3; the user decides.
- Never try to get around the budget (deleting review comments, re-running with a changed env var). Only the user may do that.

### 3. Merge

Merge only when all of these are true. If one is not, stop and tell the user why.

1. The verdict on the comment for the current `$HEAD` is exactly **Ready to merge**.
2. CI on the head commit passed: `gh pr checks <n> --watch --interval 60`. CI runs only on demand, so if the PR has no checks, skip this. If a check fails because of this phase's changes, stop and tell the user (with a 2-round budget there is no spare round for it). If it fails for an unrelated reason (runner outage, flaky upstream job), stop and tell the user.
3. `gh pr view <n> --json mergeable,mergeStateStatus` says `MERGEABLE`. If `main` moved and there is a conflict, stop and tell the user.
4. Nothing was pushed after the reviewed commit: `git rev-parse HEAD` still equals the reviewed sha, and so does `gh pr view <n> --json headRefOid`.

Then:

1. `gh pr merge <n> --merge --delete-branch --match-head-commit <reviewed sha>`.
2. `git switch main && git pull --ff-only`. Never create a worktree to reach `main`. If the switch fails because this folder has uncommitted work, commit that work first, then switch in this folder.
3. Go to **Hand off**.

## Hand off

Only after a merge. Never after **Needs user**, **Blocked**, a failed review script, or a stopped fix loop.

1. Run `bash .cursor/skills/phase/next-phase.sh`. It reads `PROGRESS.md` on `origin/main`. If a phase is not `completed`, it starts a new headless Cursor CLI session (`agent -p`) in the background that runs `/phase`, so the next phase starts with a clean context and no window or prompt. That session writes its output to `.git/phase-runs/<time>-next.log` in the main repository, and hands off again after its own merge. It starts nothing when every phase is completed, when `PHASE_AUTOCHAIN=0`, after `PHASE_CHAIN_MAX` chained sessions (default 30), or when the `agent` CLI is missing or not logged in. `PHASE_AGENT_MODEL` picks the model.
2. Tell the user: the PR URL, the merge commit, the review's **Follow-ups (not blocking)** list as-is, and the script's `NEXT:` line.
3. Stop. Do not start the next phase in this session; the new session gives it a clean context.

## Fixing review feedback

Each round is a full local review run, so make every round count.

1. Read the whole review summary before you change anything. Fix every item in **For Cursor** in the same round, minor ones included.
2. Fix the class, not just the line. If the review flags stale state in one method, check every method that touches that state. If it flags one file's header, check every new file.
3. Treat your fix as new code. For each field, map or set you add or change, check that begin, send, interrupt, dispose and error paths all keep it correct. Add a test for each behavior you change.
4. Run the gate command, plus the project's lint and pre-commit checks (`wsl -- python3 -m py_compile <changed .py files>` and `wsl -- bash -n <changed .sh files>`) on the changed files, and update the gate cell in `PROGRESS.md`.
5. Push once, with all fixes in that push. Do not push partial fixes one at a time.
6. Go back to **Review loop** step 1. Once a review says **Ready to merge**, do not push again, not even to update `PROGRESS.md`: a push after that verdict needs a new review. **Follow-ups** are for the user, not for you.
7. Do not push commits that only refresh a CI run URL or other bookkeeping. Each pushed commit needs a new review.
