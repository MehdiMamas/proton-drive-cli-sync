# One-time setup (human)

## 1. Tools on the Windows machine

- `gh` authenticated (`gh auth status`) and set to the fork: `gh repo set-default <you>/proton-drive-cli-sync`.
- Claude Code CLI logged in (`claude --version`, run `claude` once interactively if needed). The phase review runs
  locally through `.cursor/skills/phase/review.sh` with Git Bash, so it uses your Claude plan and no Actions minutes.
- Git Bash at `C:\Program Files\Git\bin\bash.exe` (comes with Git for Windows).
- In this clone: `git config core.autocrlf false` (files run in WSL need LF; `.gitattributes` enforces it too).

## 2. WSL (tests run there)

```powershell
wsl --install -d Ubuntu       # admin PowerShell, then reboot and create the Linux user
wsl -- sudo apt-get update
wsl -- sudo apt-get install -y python3 python3-venv python3-pip gettext
```

Cursor runs `wsl -- bash scripts/test.sh`, which builds `.venv-wsl/` on first use. `claude` and `gh` do not need to be in WSL.

## 3. Cursor

- Open the `proton-drive-cli-sync` folder (not the parent) so `.cursor/` is picked up.
- Agent mode. Allow `git`, `gh`, `python`, `wsl` and the Git Bash review command, or the phase will stall on approvals.
- The review takes 10–40 minutes. The skill runs it in the background and polls the log.

## 4. Run a phase

```
/phase 1           # then /phase 2 ... after each merge, when you decide
/phase 1 resume    # pick up an open phase PR
/phase-status      # where are we?
```

Each phase ends merged, or stopped with a report. Review budget is 2 rounds per PR. To allow another round on a PR yourself,
run `PHASE_REVIEW_MAX_ROUNDS=3 bash .cursor/skills/phase/review.sh <pr>` in Git Bash.

## Cost controls in place

- No Claude job on GitHub Actions. Reviews run locally, only when the `/phase` loop starts them.
- At most 2 review rounds per PR, enforced by `review.sh`.
- `tests.yml` is manual only (`gh workflow run tests.yml`).
