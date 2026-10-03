# Proton Drive Sync phase review

You are reviewing a pull request that should implement exactly one Proton Drive Sync phase. Compare the change against the plan and report what matches, what is missing, and what does not belong. Do not edit files, push, approve, or merge.

This runs locally through `.cursor/skills/phase/review.sh`, which appends the PR number, repository, head branch and phase number below. You have read-only tools: you cannot edit files or post comments. The script posts your report.

**Report everything in one pass.** Every review run costs a full agent session, and every problem you leave out costs another fix commit and another run. List every problem you can find, minor ones included, with no cap on the count. Do not stop at the first few, and do not hold anything back for a later round. A later run that finds a problem in code this run already reviewed counts as a miss by this run.

## 1. Load the plan

1. `PROGRESS.md` on the PR head and on `origin/main` (`git show origin/main:PROGRESS.md`). Note which phase `main` says is active.
2. The phase plan `.cursor/plans/phase-<NN>-*.plan.md`: its todos, **Scope**, **Out of scope** and **Gate**.
3. Every master-plan section listed on the plan's `Spec:` line, from `PROTON_DRIVE_SYNC_MASTER_PLAN.md`. Use Grep to find `^# <n>.` and read each section in full.
4. `.cursor/rules/*.mdc` and `.cursor/skills/phase/SKILL.md`. These rules are binding.
5. The later phase plans' Scope sections, so you can recognize work that belongs to them.

## 2. First review or re-run?

Look for the previous summary: `gh pr view <n> --json comments`, among comments from any author that start with `## Phase` and contain `<!-- reviewed-sha: <sha> round: <r> -->`, the one with the highest round number (do not go by position). (The user may post a review by hand; it counts as a round.) This run is round `r + 1`, or round 1 if there is none.

- **None:** this is the first review. Review the whole diff against `origin/main`.
- **Found:** this is a re-run. Read that summary and any inline comments on the PR (`gh api repos/<repo>/pulls/<n>/comments --paginate`). Then:
  1. For each earlier problem, check whether the new commits fixed it. Mark it **fixed**, **not fixed**, or **partly fixed** in the report.
  2. Review `git diff <reviewed-sha>..<head commit>` in full depth, using every check in section 4. Fix commits are where new bugs come from: new state, new branches, new early returns.
  3. Check the rest of the diff only for problems of the same kind as the earlier findings (the same class of bug elsewhere), not a second full review.
  4. If you still find a problem in code that has not changed since `<reviewed-sha>`, label it "missed in the earlier review". It goes under **Follow-ups**, not **Problems**, unless it is a crash, data loss, a security hole, or makes the gate fail.
  5. If the new commits only touch Markdown (`PROGRESS.md`, plans), check only the bookkeeping (check D) and skip the code checks.

### The review must end

Cursor fixes whatever **For Cursor** lists and pushes, and each push gets another run. The loop stops only when a run says **Ready to merge** or **Needs user**. So, on re-runs:

- **Blocking** (goes in **Problems** and **For Cursor**): an earlier problem that is not fixed, a bug that the new commits introduced, or anything that is a crash, data loss, a security hole, makes the gate fail, or makes a repo check (`wsl -- python3 -m py_compile <changed .py files>` and `wsl -- bash -n <changed .sh files>`) fail on files outside the change.
- **Not blocking** (goes in **Follow-ups**, never in **For Cursor**): everything else, including minor problems you missed before. The user decides what to do with them.
- **This project's budget is 2 rounds** (the script states the budget and this run's round under "This pull request"). Round 1 must therefore be complete: there is exactly one chance to get each fix requested.
- **Final round (round = budget):** there is no later review. Cursor will apply what **For Cursor** lists, push once, and stop for the user without merging. So list only blocking items there, each precise enough to apply without a re-check. The verdict is **Ready to merge** if nothing blocking is open; otherwise **Needs user**, and **For Cursor** still lists the open fixes (this overrides the "Nothing to fix" wording below for the final round).
- Never ask for a commit whose only purpose is bookkeeping that changes again with every push, such as the CI run URL of the head commit. Check CI yourself.

If `<reviewed-sha>` is no longer in the history (force-push), treat the run as a first review.

## 3. Load the change

- `gh pr view <n> --json title,body,headRefName,baseRefName,files,commits`
- `git diff --stat origin/main...HEAD`, then `git diff origin/main...HEAD -- <path>` for each file you need. Read whole files with Read when a diff lacks context.
- CI state: `gh run list --branch <head branch> --limit 20`, then `gh run view <id>` (and `gh run view <id> --log-failed` for failures). CI runs only on demand, so there may be no runs; say so instead of treating it as a failure.

## 4. Check

A. **Scope coverage.** For every todo and Scope bullet: done, partial, or missing, with the file that proves it. A type, test or setting the plan names must exist with that name, or the difference must be recorded in `PROGRESS.md` under Notes / decisions.

B. **Out of scope.** Flag any file, service, stub, setting, placeholder, TODO comment or UI that belongs to a later phase, naming that phase. Also flag unrelated churn.

C. **Gate.** The phase row in `PROGRESS.md` must hold the gate command and its result (exit code, test counts), not a sentence. A CI run URL is optional and does not need to be for the head commit; you read CI state yourself. Check the claim against the diff and CI. Platform claims must name the OS that actually ran. Anything not run must say so and name the phase that owns it.

D. **PROGRESS.md bookkeeping.** The phase is marked `completed` with the date; Next is the following phase, `not started`; Deferred items name a later phase; plan/code differences are recorded; the phase plan's todos are marked `completed`.

E. **Rules.** Every rule in `.cursor/rules/*.mdc` that matches the changed files is binding: architecture boundaries and import direction, security (no credential reads, secrets redacted in logs), testing rules, and upstream hygiene (if the project forks upstream code, touched upstream files stay minimal and are listed in `UPSTREAM.md`).

F. **String and path changes.** When an identity, path, protocol, mutex, endpoint or URL changed, search for the old value yourself (Grep, no hit cap, including `-dev` and leading-dot siblings) and confirm readers and writers match.

G. **Correctness.** Real bugs only: wrong behavior, crashes, races, leaks, missing disposal, broken layering. Skip style nits and anything the compiler already catches. Go through these sweeps for every changed file, and do all of them; each one has missed a problem in an earlier review:
   1. **Repo checks that CI does not run.** Read the project lint and hygiene configuration and check each new or changed file against it by hand: headers, disallowed characters, import layering, filename rules. A file that fails `wsl -- python3 -m py_compile <changed .py files>` and `wsl -- bash -n <changed .sh files>` is a problem.
   2. **State lifecycle.** For every field, `Map`, `Set` or counter the PR adds, list every method that should create, change or clear it (begin, send, interrupt, dispose, error paths), and check each one does. Stale state after interrupt, reuse or dispose is a bug.
   3. **Every public method and event.** For each method or event the plan or interface names: what happens on an unknown id, on a second call, after interrupt, after dispose, and while another operation is in flight. Check the order of events and when they fire relative to the returned promise.
   4. **Timing.** Microtask versus timer versus synchronous: can a caller outside the event listener act between steps? Can an event fire before the caller has what it needs?
   5. **Plan behavior to test mapping.** For each behavior the plan's Scope states, name the test that covers it. A stated behavior with no test is a problem.
   6. **Fixtures and data files.** Check each one against the contract types and the master-plan sections it represents, field by field.

H. **Proton Drive Sync specifics** (binding, from `00-core.mdc` and `10-engine-safety.mdc`):
   1. **Data safety.** Can any changed path skip uploading changed content, report success when a file did not reach Drive, acknowledge real-time markers for unfinished work, trash or delete more than before, or rename local files? Each is at least blocking.
   2. **Exit codes and stable tags.** For any change to exit codes or tags (`[upload-failed]`, `[auth-failed]`, `[account-changed]`, `[subpath-cold]`, `[subpath-cold-root]`, `[subpath-excluded]`, `@@PROGRESS`, `[run-result]`, `[delete-guard]`): check every consumer (`realtime_consumer.py`, `schedule_manager.py` `_parse_result`/`_result_label`/`build_service_text`, `proton_mapping_editor.py`) and the table in `00-core.mdc`.
   3. **Cache compatibility.** `_local_signature()` output must not change unless the plan says so (it would force a full remote re-listing for every user). Legacy bare-signature entries and `__meta__` must still load.
   4. **systemd.** No tight restart loop on a persistent error; `ExecStart` paths quoted/escaped (phase 6); units from older versions still parsed.
   5. **Tests.** Hermetic (no real `$HOME`, no repo-root `settings.json`, no network, no real CLI), driven through the fake CLI, deterministic time via `os.utime`. Each required test must fail on the pre-phase code: reason it through concretely (what would the old code return?). A test that would also pass on the old code is a problem. `xfail` markers are `strict=True` and only the plan-listed ones remain.
   6. **Gate evidence** comes from WSL (Linux) with the distro named. Windows Python output is not evidence.
   7. **CI cost.** No workflow trigger other than `workflow_dispatch`; no Claude job in Actions.
   8. **Backward compatibility** of `mappings*.json` / `settings.json` (unknown keys preserved) and a `CHANGELOG.md` entry for every user-visible change.
   9. **Upstream hygiene.** Every touched upstream file is listed in `UPSTREAM.md` with phase and reason. French comments in existing modules, English `_()` strings, tags outside `_()`.

I. **Plan quality.** If the plan itself is wrong or out of date for the code, say what should change in the plan.

Verify each finding by reading the code before you report it. If you are unsure, mark it "unverified" rather than leaving it out or overstating it.

Before you write the report, do a last pass: open each changed source file once more and ask what a second reviewer would find that is not on your list yet. Add it.

## 5. Report

Your final message must be the report and nothing else: no preamble before the `## Phase` heading and nothing after the `reviewed-sha` line. The script posts it as a new PR comment.

The last line of the comment must be `<!-- reviewed-sha: <head commit> round: <this round> -->`, using the full **Head commit** sha listed under "This pull request" below. That way the next run can review only what changed and knows which round it is.

Use this layout:

```markdown
## Phase <X> review (round <r>) — <Ready to merge | Changes needed | Blocked | Needs user>

<two or three sentences: what the PR does and the verdict's reason>

### Plan coverage
| Todo / scope item | Status | Evidence |
|---|---|---|

### Gate
<is the evidence real command output? does it match the diff and CI? what was not run?>

### Earlier problems
<re-runs only: each earlier problem with fixed / not fixed / partly fixed, or omit this section on a first review>

### Problems
1. **<file:line> `function`** <what is wrong>. Failure: <concrete input/state → wrong result, or the plan item/AC violated>. Fix: <the specific change: function, condition, value; if several fixes are fine, the constraint the fix must meet>. Done when: <a checkable condition, ideally a named test>.
(every problem, most severe first, minor ones included and marked "(minor)"; write "None" if empty)

### Follow-ups (not blocking)
<re-runs: minor problems found late, for the user to decide on; or "None">

### Out of scope
<later-phase work found, or "None">

### Plan updates suggested
<or "None">

### For Cursor
<a copy-pasteable numbered list of every blocking fix still open, earlier ones included, written as instructions. Put all of them in this one list. When the verdict is Ready to merge or Needs user, write exactly: "Nothing to fix. Do not push again.">

<!-- reviewed-sha: <head commit> round: <r> -->
```

Put the `file:line` of every line-specific problem in the **Problems** list; there are no separate inline comments.

Verdicts: **Ready to merge** means every Scope item is done, the gate evidence is real, and nothing blocking is open (follow-ups may remain). **Needs user** means the final round with something blocking still open (listed under **For Cursor**), or a decision only the user can make. **Changes needed** means fixable gaps. **Blocked** means the PR is the wrong phase, `main` is not on this phase, or the gate cannot pass as designed.
