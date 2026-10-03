---
name: fake-cli-testing
description: Build and use the fake `proton-drive` CLI and pytest fixtures to test the engine without a Proton account. Use when writing or changing tests under tests/, or when phase 1 asks you to create the harness.
---

# Fake proton-drive CLI and test harness

The engine calls the CLI as a subprocess (`run_cli`, `run_cli_watched`), resolved by `config.resolve_proton_cli()`
with `PROTON_DRIVE_CLI` taking priority. So the most faithful test double is a **real executable** that
reads and writes a JSON "remote drive" state file. Tests then drive the real engine code end to end.

## Files (created in phase 1)

```
tests/
  conftest.py                 # isolation (autouse) + fixtures below
  fakes/
    fake_proton_drive.py      # the executable (chmod +x, shebang #!/usr/bin/env python3)
    remote_state.py           # helpers shared by the fake and the tests (load/save/seed/inspect)
  test_*.py
scripts/test.sh               # WSL runner
requirements-dev.txt          # pytest (pinned major), nothing else unless needed
pytest.ini                    # testpaths=tests, addopts=-q -m "not slow", markers: slow
```

## Fake CLI contract (must match what the engine parses, see `proton_sync.py`)

State file path from env `FAKE_PROTON_STATE`. Shape:

```json
{
  "account": "tester@example.com",
  "version_text": "Proton Drive CLI cli-drive@0.8.0+fake\nProton Drive SDK js@0.19.1+fake",
  "nodes": {
    "/my-files": {"type": "folder"},
    "/my-files/Backups/a.txt": {"type": "file", "content_b64": "...", "mtime": 1000000000, "revisions": 1, "trashed": false}
  },
  "faults": [ {"cmd": "upload", "match": "a.txt", "mode": "fail|partial|hang|perm|stderr_text", "times": 1, "stderr": "..."} ],
  "calls": [ ["filesystem","upload","-f","replace","-d","merge","a.txt","/my-files/Backups"] ]
}
```

Every invocation appends its argv to `calls` (tests assert on it) and records `cwd` for uploads.

| argv | Behavior |
| --- | --- |
| `--version` | print `version_text`, exit 0 |
| `filesystem list <path> -j` | JSON array of direct children that are not trashed. Each item: `{"name", "type": {"ok": true, "value": "file"/"folder"}, "totalStorageSize": size+overhead, "keyAuthor": {"ok":true,"value":account}, "activeRevision": {"ok": true, "value": {"claimedSize": n, "claimedModificationTime": mtime, "claimedDigests": {"sha1": hex}}}}` (folders: no `activeRevision`). Missing path → exit 1, stderr "not found". `/` lists the virtual roots (`my-files`, …). |
| `filesystem list /` (no -j) | auth probe: exit 0, or exit 1 if `faults` has `{"cmd":"auth"}` |
| `filesystem info <path> -j` | exit 0 + JSON if exists, else exit 1 |
| `filesystem create-folder <parent> <name>` | create; if exists → exit 1 stderr "already exists" |
| `filesystem upload -f <replace\|create-new-revision> -d merge [--skip-thumbnails] <names…> <remote_parent>` | names are relative to the process **cwd** (the engine passes names + `cwd=`); un-escape glob escapes `[x]`→`x`. Read each local file, store content/mtime/sha1 under the remote parent; replace bumps `revisions`. A per-file fault makes that file fail: print `- <name>: <error>` on stdout, `N item(s) failed to upload` on stderr, exit 1, other files still succeed (models the real partial batch). |
| `filesystem trash <path>` | mark node and descendants `trashed: true` |
| anything else | exit 2, stderr "fake: unsupported command" (so unexpected calls are loud) |

Fault option `remove_size_meta: true` / `remove_digest: true` on a node omits `claimedSize` / `claimedDigests` in listings (to test missing-metadata paths).
`claimedModificationTime` must mirror what the real CLI does. Phase 2 investigates this and the fake must
then be updated to match the finding (document it in `remote_state.py`).

## Fixtures (`tests/conftest.py`)

- `_isolate` (autouse): `monkeypatch.setenv("HOME", tmp/home)`, `XDG_CONFIG_HOME`, `XDG_STATE_HOME`, `XDG_CACHE_HOME`
  under tmp; point `config._SETTINGS_PATH` to a tmp settings file; delete `PROTON_SYNC_DEBUG`; reload or patch the
  module-level path constants in `config` and `proton_sync` (`LOCK_FILE`, `CACHE_DIR`, `FAILURES_LOG`, `RENAMED_LOG`,
  `HEALTH_FILE`, `CLI_VERSION_CACHE`) so nothing touches the real home. Assert at teardown that the real
  `~/.proton-drive-sync` was not created by the test session (cheap safety net).
- `fake_drive`: creates the state file, sets `FAKE_PROTON_STATE` and `PROTON_DRIVE_CLI` (path to the fake, made executable),
  returns a helper object with `seed_file(remote_path, bytes, mtime)`, `seed_folder`, `content(remote_path)`,
  `listing(remote_path)`, `calls()`, `uploads()` (list of uploaded remote paths), `add_fault(...)`, `trashed(path)`.
- `local_tree`: helper to build a local source tree in `tmp_path` with explicit `os.utime(..., ns=…)`.
- `engine`: runs the engine as a **subprocess** (`[sys.executable, "proton_sync.py", mappings.json, *args]`, cwd = repo
  root, env with the isolation vars) and returns `(returncode, stdout, stderr)`. Use it for end-to-end and exit-code tests.
  Import `proton_sync` in-process only for unit tests of pure helpers; reset module globals (`_UNREADABLE`,
  `_cli_version_cache`) between tests.
- `write_mappings(list_of_dicts)` → path to a temp mappings JSON (same format as `mappings.example.json`).

## Writing a good engine test

```python
def test_equal_size_edit_is_uploaded(fake_drive, local_tree, write_mappings, engine):
    src = local_tree({"Docs/a.txt": (b"AAAA", 1_000_000_000)})
    cfg = write_mappings([{"type": "folder", "source": str(src / "Docs"), "dest_parent": "/my-files/Backups"}])
    assert engine(cfg).returncode == 0                       # first pass uploads
    local_tree.write("Docs/a.txt", b"BBBB", 1_000_000_100)   # same size, newer mtime
    assert engine(cfg).returncode == 0
    assert fake_drive.content("/my-files/Backups/Docs/a.txt") == b"BBBB"
```

Assert on **remote state and exit codes**, not on log wording (except stable tags, which are API).
Real-time consumer tests: use `realtime_consumer`'s existing `runner=` injection to feed exit codes and output.
