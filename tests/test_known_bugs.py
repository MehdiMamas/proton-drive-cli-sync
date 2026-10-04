"""Known bugs. Each test is a strict xfail until the change that fixes it removes the marker."""

import ast
import hashlib
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _mapping(source, **extra):
    mapping = {
        "type": "folder",
        "source": str(source),
        "dest_parent": "/my-files/Backups",
    }
    mapping.update(extra)
    return mapping


def _load_comparator():
    """Appendix A: load only the comparison helpers, not the module's startup."""
    tree = ast.parse((REPO / "proton_sync.py").read_text(encoding="utf-8"))
    names = {"_local_signature", "_local_sha1", "needs_upload"}
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    scope = {"os": os, "_": lambda text: text}
    exec(compile(ast.Module(body=functions, type_ignores=[]),
                 "isolated_comparison", "exec"), scope)
    return scope


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="equal-size edit is not uploaded",
)
def test_equal_size_edit_is_uploaded(fake_drive, local_tree, write_mappings, engine):
    src = local_tree({"Docs/a.txt": (b"AAAA", 1_000_000_000)})
    cfg = write_mappings([_mapping(src / "Docs")])
    assert engine(cfg).returncode == 0
    local_tree.write("Docs/a.txt", b"BBBB", 1_000_000_100)
    assert engine(cfg).returncode == 0
    assert fake_drive.content("/my-files/Backups/Docs/a.txt") == b"BBBB"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="default comparator ignores equal-size content edits",
)
def test_equal_size_edit_detected_by_comparator(tmp_path):
    scope = _load_comparator()
    folder = tmp_path / "folder"
    folder.mkdir()
    path = folder / "example.txt"
    path.write_bytes(b"AAAA")
    os.utime(path, (1_000_000_000, 1_000_000_000))
    before = scope["_local_signature"](str(folder), "/my-files/Test")
    remote = {"size": 4, "sha1": hashlib.sha1(b"AAAA").hexdigest()}
    path.write_bytes(b"BBBB")
    os.utime(path, (1_000_000_100, 1_000_000_100))
    after = scope["_local_signature"](str(folder), "/my-files/Test")
    check = scope["needs_upload"]
    assert before != after
    assert check(str(path), remote) is True


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="batch recovery treats old equal-size remote content as success",
)
def test_batch_recovery_not_fooled_by_old_equal_size_remote(
        fake_drive, local_tree, write_mappings, engine):
    fake_drive.seed_file("/my-files/Backups/Docs/a.txt", b"AAAA", mtime=1_000_000_000)
    src = local_tree({"Docs/a.txt": (b"BBBB", 1_000_000_100)})
    fake_drive.add_fault(cmd="upload", match="a.txt", times=5, stderr="nope")
    cfg = write_mappings([_mapping(src / "Docs")])
    # --verify-hash selects the equal-size edit, so the upload fault fires.
    # Recovery then re-lists and treats the old same-size remote file as done.
    result = engine(cfg, "--verify-hash")
    assert any(
        len(call) >= 2
        and call[0] == "filesystem"
        and call[1] == "upload"
        and "a.txt" in call
        for call in fake_drive.calls()
    ), fake_drive.calls()
    content = fake_drive.content("/my-files/Backups/Docs/a.txt")
    reported = "[upload-failed]" in result.stdout
    assert content == b"BBBB" or reported, result.stdout + result.stderr


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="a failed upload still exits 0",
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
    reason="a failed subpath upload still exits 0",
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
    reason="a later exclusion plus --delete trashes the remote copy",
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
    reason="headless run renames extensions when the setting is absent",
)
def test_headless_run_does_not_rename_extensions_on_modern_cli(
        fake_drive, local_tree, write_mappings, engine):
    src = local_tree({"Docs/IMG.JPG": (b"img", 1_000_000_000)})
    cfg = write_mappings([_mapping(src / "Docs")])
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (src / "Docs" / "IMG.JPG").is_file()
    assert not (src / "Docs" / "IMG.jpg").exists()
