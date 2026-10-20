"""Tests for the sync database (syncdb): files and folders tables."""

import sqlite3

import pytest

import syncdb


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


def test_file_rows_round_trip_and_delete(tmp_path):
    with syncdb.SyncDB(tmp_path / "s.db") as database:
        database.upsert({"local_path": "/f", "remote_path": "/r/f",
                         "remote_node_id": "n1", "claimed_size": 4,
                         "state": "synced"})
        row = database.get("/f")
        assert row["remote_node_id"] == "n1"
        assert row["claimed_size"] == 4
        assert row["state"] == "synced"
        assert [r["local_path"] for r in database.rows()] == ["/f"]
        database.delete("/f")
        assert database.get("/f") is None


def test_unknown_state_is_refused(tmp_path):
    with syncdb.SyncDB(tmp_path / "s.db") as database:
        with pytest.raises((ValueError, sqlite3.IntegrityError)):
            database.upsert({"local_path": "/f", "remote_path": "/r/f",
                             "state": "bogus"})


def test_rows_survive_reopening(tmp_path):
    path = tmp_path / "s.db"
    with syncdb.SyncDB(path) as database:
        database.upsert({"local_path": "/f", "remote_path": "/r/f", "state": "synced"})
        database.upsert_folder({"local_path": "/d", "remote_path": "/r/d"})
    with syncdb.SyncDB(path) as database:
        assert database.get("/f")["remote_path"] == "/r/f"
        assert database.get_folder("/d")["remote_path"] == "/r/d"


def test_unknown_schema_version_is_refused(tmp_path):
    path = tmp_path / "s.db"
    syncdb.SyncDB(path).close()
    conn = sqlite3.connect(str(path))
    conn.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    with pytest.raises(ValueError):
        syncdb.SyncDB(path)


def test_database_path_follows_the_mappings_file(tmp_path):
    assert syncdb.database_path("/x/mappings-user1.json", tmp_path) == str(
        tmp_path / "mappings-user1.sync.sqlite"
    )
    with pytest.raises(ValueError):
        syncdb.database_path("/x/.json", tmp_path)


def test_delete_folder_tree_forgets_the_folder_and_its_files(tmp_path):
    with syncdb.SyncDB(str(tmp_path / "s.db")) as database:
        for path in ("/x/Docs", "/x/Docs/sub", "/x/Docs2"):
            database.upsert_folder({"local_path": path, "remote_path": "/r" + path,
                                    "local_seen": 1, "remote_seen": 1})
        database.upsert({"local_path": "/x/Docs/sub/a.txt", "remote_path": "/r/a",
                         "remote_node_id": None, "sha1": None, "claimed_size": 1,
                         "claimed_mtime": 1.0, "local_inode": 1, "local_mtime": 1.0,
                         "state": "synced"})
        database.delete_folder_tree("/x/Docs")
        assert database.get_folder("/x/Docs") is None
        assert database.get_folder("/x/Docs/sub") is None
        assert database.get("/x/Docs/sub/a.txt") is None
        assert database.get_folder("/x/Docs2") is not None
