"""One twoway mapping round-trips both directions and a conflict.

A one-way mapping in the same file never downloads.
"""

import os

import remote_state
import syncdb


def _mapping(source, dest, **extra):
    mapping = {
        "type": "folder",
        "source": str(source),
        "dest_parent": dest,
    }
    mapping.update(extra)
    return mapping


def _downloads(calls):
    return [
        call for call in calls
        if len(call) >= 2 and call[0] == "filesystem" and call[1] == "download"
    ]


def _json_lists(calls):
    found = []
    for call in calls:
        if len(call) >= 3 and call[0] == "filesystem" and call[1] == "list" and "-j" in call:
            found.append(call[2])
    return found


def _set_remote(fake_drive, path, data, mtime):
    def mutate(state):
        remote_state.store_file(state, path, data, mtime)
        normalized = remote_state.normalize(path)
        if state["uploads"] and state["uploads"][-1] == normalized:
            state["uploads"].pop()
    fake_drive._update(mutate)


def _db(isolated_home, cfg):
    return syncdb.database_path(
        os.path.basename(str(cfg)),
        data_dir=str(isolated_home / ".proton-drive-sync"))


def test_volume_downloads_into_the_local_root(
        fake_drive, local_tree, write_mappings, engine):
    src = local_tree({})
    fake_drive.seed_file("/my-files/hello.txt", b"HELLO", 1_000_000_000)
    cfg = write_mappings([
        _mapping(src, "/my-files", direction="twoway", volume=True,
                 allow_delete=False),
    ])
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (src / "hello.txt").read_bytes() == b"HELLO"
    assert not (src / src.name).exists()
    listed = _json_lists(fake_drive.calls())
    assert "/my-files" in listed
    assert "/my-files/" + src.name not in listed


def test_volume_subpath_does_not_append_the_local_folder_name():
    import proton_sync
    volume = {
        "source": "/data/Proton Drive",
        "dest_parent": "/my-files",
        "direction": "twoway",
        "volume": True,
    }
    parent, err = proton_sync._remote_parent_for_subpath(
        volume, "/data/Proton Drive/Docs")
    assert err is None
    assert parent == "/my-files"
    root, err = proton_sync._remote_parent_for_subpath(
        volume, "/data/Proton Drive")
    assert err is None
    assert root == "/my-files"
    normal = {
        "source": "/data/Docs",
        "dest_parent": "/my-files/Backups",
        "direction": "twoway",
    }
    parent, err = proton_sync._remote_parent_for_subpath(normal, "/data/Docs/Sub")
    assert err is None
    assert parent == "/my-files/Backups/Docs"


def test_failed_upload_is_recorded_as_error(
        fake_drive, local_tree, write_mappings, engine, isolated_home):
    src = local_tree({"Docs/a.txt": (b"AAAA", 1_000_000_000)})
    cfg = write_mappings([
        _mapping(src / "Docs", "/my-files/Backups", direction="twoway"),
    ])
    fake_drive.add_fault(cmd="upload", match="a.txt", mode="fail", times=5)
    result = engine(cfg)
    assert result.returncode == 5, result.stdout + result.stderr
    with syncdb.SyncDB(_db(isolated_home, cfg)) as database:
        row = database.get(str(src / "Docs" / "a.txt"))
    assert row["state"] == "error"


def test_twoway_round_trip_and_one_way_does_not_download(
        fake_drive, local_tree, write_mappings, engine):
    src = local_tree({
        "Two/a.txt": (b"AAAA", 1_000_000_000),
        "One/b.txt": (b"BBBB", 1_000_000_000),
    })
    cfg = write_mappings([
        _mapping(src / "Two", "/my-files/TwoWay", direction="twoway"),
        _mapping(src / "One", "/my-files/OneWay"),
    ])
    remote = "/my-files/TwoWay/Two/a.txt"
    one_remote = "/my-files/OneWay/One/b.txt"

    first = engine(cfg)
    assert first.returncode == 0, first.stdout + first.stderr
    assert fake_drive.content(remote) == b"AAAA"
    assert fake_drive.content(one_remote) == b"BBBB"
    assert _downloads(fake_drive.calls()) == []

    before = len(fake_drive.calls())
    again = engine(cfg)
    assert again.returncode == 0, again.stdout + again.stderr
    second = fake_drive.calls()[before:]
    assert "/my-files/TwoWay/Two" in _json_lists(second)
    assert _downloads(second) == []

    local_tree.write("Two/a.txt", b"BBBB", 1_000_000_100)
    uploaded = engine(cfg)
    assert uploaded.returncode == 0, uploaded.stdout + uploaded.stderr
    assert fake_drive.content(remote) == b"BBBB"
    assert (src / "Two" / "a.txt").read_bytes() == b"BBBB"

    _set_remote(fake_drive, remote, b"CCCC", 1_000_000_200)
    downloaded = engine(cfg)
    assert downloaded.returncode == 0, downloaded.stdout + downloaded.stderr
    assert "[download] " in downloaded.stdout
    assert (src / "Two" / "a.txt").read_bytes() == b"CCCC"
    assert fake_drive.content(remote) == b"CCCC"

    local_tree.write("Two/a.txt", b"DDDD", 1_000_000_300)
    _set_remote(fake_drive, remote, b"EEEE", 1_000_000_400)
    conflict = engine(cfg)
    assert conflict.returncode == 0, conflict.stdout + conflict.stderr
    assert "[conflict] " in conflict.stdout
    assert (src / "Two" / "a.txt").read_bytes() == b"DDDD"
    assert fake_drive.content(remote) == b"EEEE"
    assert (src / "Two" / "a (proton conflict).txt").read_bytes() == b"EEEE"

    one_way_downloads = [
        call for call in _downloads(fake_drive.calls())
        if any("/my-files/OneWay" in part for part in call)
    ]
    assert one_way_downloads == []


def test_local_deletion_restores_on_the_next_pass_unless_deletion_is_on(
        fake_drive, local_tree, write_mappings, engine):
    src = local_tree({"Docs/a.txt": (b"AAAA", 1_000_000_000)})
    remote = "/my-files/Backups/Docs/a.txt"
    keep = write_mappings([
        _mapping(src / "Docs", "/my-files/Backups", direction="twoway"),
    ])
    assert engine(keep).returncode == 0
    (src / "Docs" / "a.txt").unlink()
    kept = engine(keep)
    assert kept.returncode == 0, kept.stdout + kept.stderr
    assert fake_drive.content(remote) == b"AAAA"
    assert not (src / "Docs" / "a.txt").exists()
    restored = engine(keep)
    assert restored.returncode == 0, restored.stdout + restored.stderr
    assert (src / "Docs" / "a.txt").read_bytes() == b"AAAA"

    src2 = local_tree({"Gone/a.txt": (b"AAAA", 1_000_000_000)})
    remote2 = "/my-files/TrashMe/Gone/a.txt"
    deleting = write_mappings([
        _mapping(src2 / "Gone", "/my-files/TrashMe", direction="twoway",
                 allow_delete=True, source_kind="local"),
    ])
    assert engine(deleting).returncode == 0
    (src2 / "Gone" / "a.txt").unlink()
    trashed = engine(deleting)
    assert trashed.returncode == 0, trashed.stdout + trashed.stderr
    assert fake_drive.trashed(remote2)
    assert not (src2 / "Gone" / "a.txt").exists()


def test_shared_folder_is_not_trashed_without_confirmation(
        fake_drive, local_tree, write_mappings, engine):
    fake_drive.seed_folder("/shared-with-me/Box")
    src = local_tree({"Docs/a.txt": (b"AAAA", 1_000_000_000)})
    remote = "/shared-with-me/Box/Docs/a.txt"
    cfg = write_mappings([
        _mapping(src / "Docs", "/shared-with-me/Box", direction="twoway",
                 allow_delete=True, source_kind="local"),
    ])
    assert engine(cfg).returncode == 0
    (src / "Docs" / "a.txt").unlink()
    kept = engine(cfg)
    assert kept.returncode == 0, kept.stdout + kept.stderr
    assert not fake_drive.trashed(remote)
    assert fake_drive.content(remote) == b"AAAA"


def test_confirmed_shared_folder_may_trash(
        fake_drive, local_tree, write_mappings, engine):
    fake_drive.seed_folder("/shared-with-me/Box")
    src = local_tree({"Docs/a.txt": (b"AAAA", 1_000_000_000)})
    remote = "/shared-with-me/Box/Docs/a.txt"
    cfg = write_mappings([
        _mapping(src / "Docs", "/shared-with-me/Box", direction="twoway",
                 allow_delete=True, source_kind="local",
                 shared_delete_confirmed=True),
    ])
    assert engine(cfg).returncode == 0
    (src / "Docs" / "a.txt").unlink()
    trashed = engine(cfg)
    assert trashed.returncode == 0, trashed.stdout + trashed.stderr
    assert fake_drive.trashed(remote)


def test_missing_remote_moves_the_local_file_aside(
        fake_drive, local_tree, write_mappings, engine):
    src = local_tree({"Docs/a.txt": (b"AAAA", 1_000_000_000)})
    remote = "/my-files/Backups/Docs/a.txt"
    cfg = write_mappings([
        _mapping(src / "Docs", "/my-files/Backups", direction="twoway"),
    ])
    assert engine(cfg).returncode == 0
    def mutate(state):
        state["nodes"].pop(remote_state.normalize(remote), None)
    fake_drive._update(mutate)
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[held] " in result.stdout
    assert not (src / "Docs" / "a.txt").exists()
    dest = result.stdout.split("[held] ", 1)[1].split(" -> ", 1)[1].splitlines()[0].strip()
    assert os.path.isfile(dest)
    assert open(dest, "rb").read() == b"AAAA"


def test_failed_listing_does_not_update_the_sync_row(
        fake_drive, local_tree, write_mappings, engine, isolated_home):
    src = local_tree({"Docs/a.txt": (b"AAAA", 1_000_000_000)})
    cfg = write_mappings([
        _mapping(src / "Docs", "/my-files/Backups", direction="twoway"),
    ])
    assert engine(cfg).returncode == 0
    with syncdb.SyncDB(_db(isolated_home, cfg)) as database:
        before = database.get(str(src / "Docs" / "a.txt"))
    assert before["state"] == "synced"
    assert before["sha1"]
    local_tree.write("Docs/a.txt", b"BBBB", 1_000_000_100)
    fake_drive.add_fault(
        cmd="list", match="/my-files/Backups/Docs", mode="fail", times=1)
    failed = engine(cfg)
    assert failed.returncode == 5, failed.stdout + failed.stderr
    assert "[list-skipped] " in failed.stdout
    assert (src / "Docs" / "a.txt").read_bytes() == b"BBBB"
    assert fake_drive.content("/my-files/Backups/Docs/a.txt") == b"AAAA"
    with syncdb.SyncDB(_db(isolated_home, cfg)) as database:
        after = database.get(str(src / "Docs" / "a.txt"))
    assert after["sha1"] == before["sha1"]
    assert after["state"] == "synced"


def test_proton_document_is_logged_and_not_deleted(
        fake_drive, local_tree, write_mappings, engine, isolated_home):
    src = local_tree({"Docs/a.txt": (b"AAAA", 1_000_000_000)})
    cfg = write_mappings([
        _mapping(src / "Docs", "/my-files/Backups", direction="twoway"),
    ])
    def mutate(state):
        path = "/my-files/Backups/Docs/notes.doc"
        remote_state.ensure_folders(state, path)
        state["nodes"][path] = {"type": "document"}
    fake_drive._update(mutate)
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[download-skipped] " in result.stdout
    assert not (src / "Docs" / "notes.doc").exists()
    assert fake_drive.content("/my-files/Backups/Docs/a.txt") == b"AAAA"
    with syncdb.SyncDB(_db(isolated_home, cfg)) as database:
        row = database.get(str(src / "Docs" / "notes.doc"))
    assert row["state"] == "error"
