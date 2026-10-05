"""v1.17.0 upload rule, observed through the engine and the fake drive."""

import proton_sync


def _mapping(source, **extra):
    mapping = {
        "type": "folder",
        "source": str(source),
        "dest_parent": "/my-files/Backups",
    }
    mapping.update(extra)
    return mapping


def test_equal_size_edit_is_uploaded(fake_drive, local_tree, write_mappings, engine):
    src = local_tree({"Docs/a.txt": (b"AAAA", 1_000_000_000)})
    cfg = write_mappings([_mapping(src / "Docs")])
    assert engine(cfg).returncode == 0
    local_tree.write("Docs/a.txt", b"BBBB", 1_000_000_100)
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert fake_drive.content("/my-files/Backups/Docs/a.txt") == b"BBBB"
    assert fake_drive.revisions("/my-files/Backups/Docs/a.txt") == 2


def test_identical_rewrite_is_not_uploaded(fake_drive, local_tree, write_mappings, engine):
    src = local_tree({"Docs/a.txt": (b"AAAA", 1_000_000_000)})
    cfg = write_mappings([_mapping(src / "Docs")])
    assert engine(cfg).returncode == 0
    local_tree.write("Docs/a.txt", b"AAAA", 1_000_000_100)
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert fake_drive.content("/my-files/Backups/Docs/a.txt") == b"AAAA"
    assert fake_drive.revisions("/my-files/Backups/Docs/a.txt") == 1


def test_unchanged_file_is_not_read_when_a_neighbour_changes(
        fake_drive, local_tree, monkeypatch):
    src = local_tree({
        "Docs/keep.txt": (b"AAAA", 1_000_000_000),
        "Docs/move.txt": (b"CCCC", 1_000_000_000),
    })
    cache = proton_sync.Cache(str(src / "cache.json"))
    folder = str(src / "Docs")
    assert proton_sync.sync_folder(
        folder, "/my-files/Backups", cache=cache, rename_ext=False)
    local_tree.write("Docs/move.txt", b"DDDD", 1_000_000_100)
    hashed = []
    real = proton_sync._local_sha1

    def counted(path, *args, **kwargs):
        hashed.append(path)
        return real(path, *args, **kwargs)

    monkeypatch.setattr(proton_sync, "_local_sha1", counted)
    assert proton_sync.sync_folder(
        folder, "/my-files/Backups", cache=cache, rename_ext=False)
    assert not any(path.endswith("keep.txt") for path in hashed), hashed
    assert any(path.endswith("move.txt") for path in hashed), hashed


def test_batch_recovery_does_not_accept_an_older_equal_size_copy(
        fake_drive, local_tree, write_mappings, engine):
    fake_drive.seed_file("/my-files/Backups/Docs/a.txt", b"AAAA", mtime=1_000_000_000)
    src = local_tree({"Docs/a.txt": (b"BBBB", 1_000_000_100)})
    fake_drive.add_fault(cmd="upload", match="a.txt", times=5, stderr="nope")
    cfg = write_mappings([_mapping(src / "Docs")])
    result = engine(cfg)
    assert "[upload-failed]" in result.stdout, result.stdout + result.stderr
    assert fake_drive.content("/my-files/Backups/Docs/a.txt") == b"AAAA"


def test_file_edited_while_excluded_is_uploaded_when_the_exclusion_is_removed(
        fake_drive, local_tree, write_mappings, engine):
    src = local_tree({
        "Docs/secret.txt": (b"AAAA", 1_000_000_000),
        "Docs/keep.txt": (b"keep", 1_000_000_000),
    })
    excluded = write_mappings([_mapping(
        src / "Docs",
        exclusions={"names": ["secret.txt"], "patterns": []},
    )])
    first = engine(excluded)
    assert first.returncode == 0, first.stdout + first.stderr
    assert fake_drive.content("/my-files/Backups/Docs/secret.txt") is None
    local_tree.write("Docs/secret.txt", b"BBBB", 1_000_000_100)
    second = engine(excluded)
    assert second.returncode == 0, second.stdout + second.stderr
    assert fake_drive.content("/my-files/Backups/Docs/secret.txt") is None
    plain = write_mappings([_mapping(src / "Docs")])
    third = engine(plain)
    assert third.returncode == 0, third.stdout + third.stderr
    assert fake_drive.content("/my-files/Backups/Docs/secret.txt") == b"BBBB"
