"""Known bugs. Each test is a strict xfail until the phase named in its reason fixes it.

Phase 2 moved the equal-size tests to tests/test_equal_size.py and removed their markers.
"""

import pytest


def _mapping(source, **extra):
    mapping = {
        "type": "folder",
        "source": str(source),
        "dest_parent": "/my-files/Backups",
    }
    mapping.update(extra)
    return mapping


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="phase-03: a failed upload still exits 0",
)
def test_upload_failure_exits_nonzero(fake_drive, local_tree, write_mappings, engine):
    src = local_tree({"Docs/a.txt": (b"hello", 1_000_000_000)})
    fake_drive.add_fault(cmd="upload", match="a.txt", times=5, stderr="nope")
    cfg = write_mappings([_mapping(src / "Docs")])
    result = engine(cfg)
    assert result.returncode == 5


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="phase-03: a failed subpath upload still exits 0",
)
def test_subpath_upload_failure_exits_nonzero(fake_drive, local_tree, write_mappings, engine):
    src = local_tree({"Docs/a.txt": (b"hello", 1_000_000_000)})
    cfg = write_mappings([_mapping(src / "Docs")])
    warmed = engine(cfg)
    assert warmed.returncode == 0, warmed.stdout + warmed.stderr
    local_tree.write("Docs/a.txt", b"hello!", 1_000_000_100)
    fake_drive.add_fault(cmd="upload", match="a.txt", times=5, stderr="nope")
    result = engine(cfg, "--subpath", str(src / "Docs"), "--mapping-source", str(src / "Docs"))
    assert result.returncode == 5


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="phase-04: a later exclusion plus --delete trashes the remote copy",
)
def test_exclusion_added_later_keeps_remote_copy(fake_drive, local_tree, write_mappings, engine):
    src = local_tree({"Docs/secret.txt": (b"hide", 1_000_000_000)})
    cfg = write_mappings([_mapping(src / "Docs", allow_delete=True, source_kind="local")])
    assert engine(cfg).returncode == 0
    excluded = write_mappings([_mapping(
        src / "Docs",
        allow_delete=True,
        source_kind="local",
        exclusions={"names": ["secret.txt"], "patterns": []},
    )])
    result = engine(excluded, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not fake_drive.trashed("/my-files/Backups/Docs/secret.txt")
    assert fake_drive.content("/my-files/Backups/Docs/secret.txt") == b"hide"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="phase-05: headless run renames extensions when the setting is absent",
)
def test_headless_run_does_not_rename_extensions_on_modern_cli(
        fake_drive, local_tree, write_mappings, engine):
    src = local_tree({"Docs/IMG.JPG": (b"img", 1_000_000_000)})
    cfg = write_mappings([_mapping(src / "Docs")])
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (src / "Docs" / "IMG.JPG").is_file()
    assert not (src / "Docs" / "IMG.jpg").exists()
