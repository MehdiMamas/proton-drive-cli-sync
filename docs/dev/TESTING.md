# Testing

The engine is tested without a Proton account. A fake `proton-drive` executable
stands in for the real CLI. Tests run on Linux, in WSL on the Windows dev
machine. Windows Python is not a result: the engine needs `fcntl`.

## Run

From PowerShell, in the repository root:

```powershell
wsl -- bash scripts/test.sh
wsl -- bash scripts/test.sh -k baseline -vv
```

`scripts/test.sh` refuses to run unless `uname -s` is Linux. The first run
creates `.venv-wsl/` (gitignored) and installs `requirements-dev.txt`. Later
runs reinstall only when that file is newer than the stamp. Extra arguments
are passed to pytest.

The default pytest options skip tests marked `slow` and turn off the cache
provider. `xfail_strict` is on: a known-bug test that starts passing fails
the run, so the phase that fixes it has to remove the marker.

## Fake CLI

`tests/fakes/fake_proton_drive.py` is the executable (`#!/usr/bin/env python3`).
`PROTON_DRIVE_CLI` points the engine at it. `FAKE_PROTON_STATE` is the JSON
file that holds the remote drive. The engine fixture sets both and fails
immediately if `PROTON_DRIVE_CLI` is unset, instead of searching for a real
binary.

The state file records the account, the `--version` text, nodes, faults,
every argv the fake saw, and the remote paths that were stored. Helpers in
`tests/fakes/remote_state.py` load and save that file. Tests reach it through
the `fake_drive` fixture: `seed_file`, `seed_folder`, `content`, `listing`,
`calls`, `uploads`, `add_fault`, `trashed`.

Supported commands are the ones the engine sends: `--version`,
`filesystem list` (with and without `-j`), `filesystem info`,
`filesystem create-folder`, `filesystem upload`, and `filesystem trash`.
Anything else exits 2 with `fake: unsupported command` on stderr.

`filesystem list /` without `-j` is the auth probe. A fault `{"cmd": "auth"}`
makes that probe exit 1. `filesystem list <path> -j` returns a JSON array of
direct children that are not trashed. Fields the engine unwraps (`type`,
`keyAuthor`, `activeRevision`) use `{"ok": true, "value": ...}`. File items
carry `claimedSize`, `claimedModificationTime` and `claimedDigests.sha1`.
`claimedModificationTime` is the local file's mtime in POSIX seconds at the
moment of upload. Phase 2 checks whether the real CLI does the same and
updates the fake if it does not.

Uploads read names relative to the process cwd, which is how the engine
calls the CLI. Glob escapes are undone first (`a[[]b.txt` is the file
`a[b.txt]`). An upload of an existing file replaces the bytes and bumps
`revisions`. A per-file fault fails that name only: `- <name>: <error>` on
stdout, `N item(s) failed to upload` on stderr, exit 1, and the other names
in the batch are stored. `filesystem trash` marks the node and its
descendants trashed, and listings hide them.

`add_fault(cmd=..., match=..., mode=..., times=..., stderr=...)` injects a
failure. `times` defaults to every call; `times=1` fires once. `mode` is
`fail` (per-file or whole command), `partial` (same reporting; other files
in a per-file fault still succeed), `perm` (stderr contains `permission`),
`stderr_text`, or `hang`. On a node, `remove_size_meta` omits `claimedSize`
and the `totalStorageSize` fallback, and `remove_digest` omits
`claimedDigests`, so a test can force the missing-metadata paths.

## Writing an engine test

Use the fixtures in `tests/conftest.py`. `_isolate` runs for every test: it
points `HOME` and `XDG_*` at a temporary directory and, if `config` or
`proton_sync` were imported in this process, retargets their path constants.
The session ends by checking that the real `~/.proton-drive-sync` was not
created and that `settings.json` did not appear in the repository root.

`local_tree({"Docs/a.txt": (b"AAAA", 1_000_000_000)})` builds files and sets
their mtime. A number below `10**15` is seconds; a larger number is
nanoseconds. `local_tree.write` updates one file the same way.

`write_mappings([...])` writes a mappings JSON in the new-format object
(`mappings` plus optional global `exclusions`).

`engine(mappings_path, *args)` runs `proton_sync.py` as a subprocess with a
temporary settings file `{"language": "en"}`, the fake CLI, and the isolated
home. It returns `(returncode, stdout, stderr)` on a `CompletedProcess`.
Assert on remote bytes and exit codes. Stable tags such as `[upload-failed]`
and `[auth-failed]` are part of the API and may be asserted. Do not assert
on translated sentences.

Import `proton_sync` in-process only for a pure helper. The equal-size
comparator test does not import the module: it execs the three functions the
way Appendix A of the briefing does, so importing the engine cannot create
directories as a side effect of that test.

## Known bugs (strict xfail)

`tests/test_known_bugs.py` pins bugs that later phases fix. Each test is
`@pytest.mark.xfail(strict=True, reason="phase-NN: ...")`. The test states
the behavior we want. On today's code it fails, and strict mode records that
as an expected failure. A phase that fixes the bug removes the marker in the
same change. Leaving the marker on a test that now passes fails the suite.

| Test | Removed by |
|---|---|
| `test_equal_size_edit_is_uploaded` | phase 2 |
| `test_equal_size_edit_detected_by_comparator` | phase 2 |
| `test_batch_recovery_not_fooled_by_old_equal_size_remote` | phase 2 |
| `test_upload_failure_exits_nonzero` | phase 3 |
| `test_subpath_upload_failure_exits_nonzero` | phase 3 |
| `test_exclusion_added_later_keeps_remote_copy` | phase 4 |
| `test_headless_run_does_not_rename_extensions_on_modern_cli` | phase 5 |
