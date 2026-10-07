# One-time setup (human)

## 1. Tools on the Windows machine

- `gh` authenticated (`gh auth status`) and set to the fork: `gh repo set-default <you>/proton-drive-cli-sync`.
- Claude Code CLI logged in (`claude --version`, run `claude` once interactively if needed).
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
- Agent mode. Allow `git`, `gh`, `python` and `wsl`.

## 4. Phases

Phase plans (`.cursor/plans/`) and `PROGRESS.md` are run only from the Phase Autopilot dashboard. The old `/phase` skill is archived in `docs/archive/phasing/`.

## Cost controls in place

- No Claude job on GitHub Actions.
- `tests.yml` is manual only (`gh workflow run tests.yml`).
