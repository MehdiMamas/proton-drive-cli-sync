"""Engine core of two-way sync (#17 PR-1): key, trigger setting, folders table.

The PR-3 test is a strict xfail: it describes the wanted behaviour and
fails today, so it flips loudly when the feature lands.
"""

import os
import shutil
import sqlite3

import pytest

import proton_sync
import remote_state
import syncdb


def _mapping(source, dest, **extra):
    mapping = {"type": "folder", "source": str(source), "dest_parent": dest}
    mapping.update(extra)
    return mapping


def _downloads(calls):
    return [c for c in calls
            if len(c) >= 2 and c[0] == "filesystem" and c[1] == "download"]


def _db(isolated_home, cfg):
    return syncdb.database_path(
        os.path.basename(str(cfg)),
        data_dir=str(isolated_home / ".proton-drive-sync"))


def test_load_twoway_mappings_reads_only_its_own_key(tmp_path):
    cfg = tmp_path / "m.json"
    cfg.write_text('{"mappings": [{"source": "a"}], '
                   '"twoway_mappings": [{"source": "b"}]}')
    assert proton_sync.load_twoway_mappings(str(cfg)) == [{"source": "b"}]
    cfg.write_text('{"mappings": [{"source": "a"}]}')
    assert proton_sync.load_twoway_mappings(str(cfg)) == []
    cfg.write_text('{"twoway_mappings": "nope"}')
    assert proton_sync.load_twoway_mappings(str(cfg)) == []


def test_trigger_none_skips_twoway_mappings_and_uploads_the_rest(
        fake_drive, local_tree, write_mappings, engine):
    src = local_tree({
        "Two/a.txt": (b"AAAA", 1_000_000_000),
        "One/b.txt": (b"BBBB", 1_000_000_000),
    })
    cfg = write_mappings([_mapping(src / "One", "/my-files/OneWay")],
                         twoway_mappings=[_mapping(src / "Two", "/my-files/TwoWay")])
    fake_drive.seed_file("/my-files/TwoWay/Two/web.txt", b"WEB")
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Two-way mapping skipped" in result.stdout
    assert "'none'" in result.stdout
    assert fake_drive.content("/my-files/OneWay/One/b.txt") == b"BBBB"
    assert fake_drive.content("/my-files/TwoWay/Two/a.txt") is None
    assert _downloads(fake_drive.calls()) == []
    assert not (src / "Two" / "web.txt").exists()


def test_reconcile_remembers_the_synced_folders(
        fake_drive, local_tree, write_mappings, engine, isolated_home):
    src = local_tree({"Docs/sub/a.txt": (b"AAAA", 1_000_000_000)})
    cfg = write_mappings([], twoway_mappings=[_mapping(src / "Docs", "/my-files/B")])
    result = engine.reconcile(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    with syncdb.SyncDB(_db(isolated_home, cfg)) as database:
        row = database.get_folder(str(src / "Docs" / "sub"))
        assert row is not None
        assert row["remote_path"] == "/my-files/B/Docs/sub"
        assert row["local_seen"] == 1 and row["remote_seen"] == 1
        assert str(src / "Docs") in {f["local_path"] for f in database.folders()}


def test_folder_rows_upsert_and_validate(tmp_path):
    with syncdb.SyncDB(tmp_path / "s.db") as database:
        database.upsert_folder({"local_path": "/l", "remote_path": "/r",
                                "local_seen": True})
        database.upsert_folder({"local_path": "/l", "remote_path": "/r2",
                                "remote_node_id": "n1", "remote_seen": True})
        row = database.get_folder("/l")
        assert row == {"local_path": "/l", "remote_path": "/r2",
                       "remote_node_id": "n1", "local_seen": 0, "remote_seen": 1}
        assert database.get_folder("/none") is None
        with pytest.raises(ValueError):
            database.upsert_folder({"local_path": "/l"})


@pytest.mark.parametrize("version", ["1", "2"])
def test_old_databases_migrate_to_folders(tmp_path, version):
    path = tmp_path / "old.db"
    with syncdb.SyncDB(path) as database:
        database.upsert({"local_path": "/f", "remote_path": "/r/f", "state": "synced"})
    conn = sqlite3.connect(str(path))
    conn.execute("DROP TABLE folders")
    conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (version,))
    conn.commit()
    conn.close()
    with syncdb.SyncDB(path) as database:
        assert database.get("/f")["state"] == "synced"
        database.upsert_folder({"local_path": "/d", "remote_path": "/r/d"})
        assert database.get_folder("/d")
    conn = sqlite3.connect(str(path))
    assert conn.execute("SELECT value FROM meta WHERE key='schema_version'"
                        ).fetchone()[0] == "3"
    conn.close()


def test_folder_deleted_on_proton_is_moved_aside_not_recreated(
        fake_drive, local_tree, write_mappings, engine):
    src = local_tree({"Docs/sub/a.txt": (b"AAAA", 1_000_000_000)})
    cfg = write_mappings([], twoway_mappings=[_mapping(src / "Docs", "/my-files/B", source_kind="local")])
    assert engine.reconcile(cfg).returncode == 0
    base = remote_state.normalize("/my-files/B/Docs/sub")

    def mutate(state):
        for path in [p for p in state["nodes"] if p == base or p.startswith(base + "/")]:
            state["nodes"].pop(path)
    fake_drive._update(mutate)
    result = engine.reconcile(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (src / "Docs" / "sub").exists()
    assert fake_drive.content("/my-files/B/Docs/sub/a.txt") is None
    assert "sub" not in fake_drive.listing("/my-files/B/Docs")


def _synced(engine, local_tree, write_mappings, files, **extra):
    src = local_tree(files)
    cfg = write_mappings([], twoway_mappings=[
        _mapping(src / "Docs", "/my-files/B", source_kind="local", **extra)])
    assert engine.reconcile(cfg).returncode == 0
    return src, cfg


def _drop_remote(fake_drive, remote_path):
    base = remote_state.normalize(remote_path)

    def mutate(state):
        for path in [p for p in state["nodes"] if p == base or p.startswith(base + "/")]:
            state["nodes"].pop(path)
    fake_drive._update(mutate)


def test_folder_deleted_locally_is_trashed_on_proton(
        fake_drive, local_tree, write_mappings, engine, isolated_home):
    src, cfg = _synced(engine, local_tree, write_mappings,
                       {"Docs/sub/a.txt": (b"AAAA", 1_000_000_000),
                        "Docs/keep.txt": (b"KKKK", 1_000_000_000)},
                       allow_delete=True)
    shutil.rmtree(src / "Docs" / "sub")
    result = engine.reconcile(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (src / "Docs" / "sub").exists()
    assert fake_drive.content("/my-files/B/Docs/sub/a.txt") is None
    assert "sub" not in fake_drive.listing("/my-files/B/Docs")
    assert fake_drive.content("/my-files/B/Docs/keep.txt") == b"KKKK"
    with syncdb.SyncDB(_db(isolated_home, cfg)) as database:
        assert database.get_folder(str(src / "Docs" / "sub")) is None
        assert database.get(str(src / "Docs" / "sub" / "a.txt")) is None


def test_folder_deletions_are_held_without_delete(
        fake_drive, local_tree, write_mappings, engine, isolated_home):
    src, cfg = _synced(engine, local_tree, write_mappings,
                       {"Docs/gone_here/a.txt": (b"AAAA", 1_000_000_000),
                        "Docs/gone_there/b.txt": (b"BBBB", 1_000_000_000)},
                       allow_delete=True)
    shutil.rmtree(src / "Docs" / "gone_here")
    _drop_remote(fake_drive, "/my-files/B/Docs/gone_there")
    result = engine.reconcile(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "deletions are off" in result.stdout
    # Nothing is recreated on either side and nothing is removed.
    assert not (src / "Docs" / "gone_here").exists()
    assert fake_drive.content("/my-files/B/Docs/gone_here/a.txt") == b"AAAA"
    assert (src / "Docs" / "gone_there" / "b.txt").read_bytes() == b"BBBB"
    assert fake_drive.content("/my-files/B/Docs/gone_there/b.txt") is None
    with syncdb.SyncDB(_db(isolated_home, cfg)) as database:
        assert database.get_folder(str(src / "Docs" / "gone_here"))
        assert database.get_folder(str(src / "Docs" / "gone_there"))


def test_edit_inside_a_folder_deleted_on_proton_wins(
        fake_drive, local_tree, write_mappings, engine):
    src, cfg = _synced(engine, local_tree, write_mappings,
                       {"Docs/sub/a.txt": (b"AAAA", 1_000_000_000),
                        "Docs/sub/b.txt": (b"BBBB", 1_000_000_000)})
    (src / "Docs" / "sub" / "a.txt").write_bytes(b"EDITED!")
    _drop_remote(fake_drive, "/my-files/B/Docs/sub")
    result = engine.reconcile(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (src / "Docs" / "sub" / "a.txt").read_bytes() == b"EDITED!"
    assert fake_drive.content("/my-files/B/Docs/sub/a.txt") == b"EDITED!"


def test_edit_inside_a_folder_deleted_locally_wins(
        fake_drive, local_tree, write_mappings, engine):
    src, cfg = _synced(engine, local_tree, write_mappings,
                       {"Docs/sub/a.txt": (b"AAAA", 1_000_000_000)},
                       allow_delete=True)
    shutil.rmtree(src / "Docs" / "sub")
    fake_drive.seed_file("/my-files/B/Docs/sub/a.txt", b"NEWER-ON-PROTON",
                         mtime=2_000_000_000)
    result = engine.reconcile(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (src / "Docs" / "sub" / "a.txt").read_bytes() == b"NEWER-ON-PROTON"
    assert fake_drive.content("/my-files/B/Docs/sub/a.txt") == b"NEWER-ON-PROTON"


def test_mass_delete_guard_holds_folder_deletions(
        fake_drive, local_tree, write_mappings, engine):
    engine.update_settings(mass_delete_guard=True, max_delete_min=1)
    src, cfg = _synced(engine, local_tree, write_mappings,
                       {"Docs/one/a.txt": (b"AAAA", 1_000_000_000),
                        "Docs/two/b.txt": (b"BBBB", 1_000_000_000)},
                       allow_delete=True)
    shutil.rmtree(src / "Docs" / "one")
    shutil.rmtree(src / "Docs" / "two")
    result = engine.reconcile(cfg, "--delete")
    assert "[delete-guard]" in result.stdout, result.stdout + result.stderr
    assert fake_drive.content("/my-files/B/Docs/one/a.txt") == b"AAAA"
    assert fake_drive.content("/my-files/B/Docs/two/b.txt") == b"BBBB"
    assert not (src / "Docs" / "one").exists()


@pytest.mark.xfail(strict=True, reason="#17 PR-2/PR-3")
def test_file_renamed_on_proton_renames_the_local_file(
        fake_drive, local_tree, write_mappings, engine):
    src = local_tree({"Docs/a.txt": (b"AAAA", 1_000_000_000)})
    cfg = write_mappings([], twoway_mappings=[_mapping(src / "Docs", "/my-files/B")])
    assert engine.reconcile(cfg).returncode == 0
    old = remote_state.normalize("/my-files/B/Docs/a.txt")
    new = remote_state.normalize("/my-files/B/Docs/b.txt")

    def mutate(state):
        state["nodes"][new] = state["nodes"].pop(old)
    fake_drive._update(mutate)
    before = len(_downloads(fake_drive.calls()))
    result = engine.reconcile(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (src / "Docs" / "b.txt").read_bytes() == b"AAAA"
    assert not (src / "Docs" / "a.txt").exists()
    assert len(_downloads(fake_drive.calls())) == before
