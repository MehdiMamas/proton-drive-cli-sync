"""Tests for the sync database (syncdb): folders table and schema migration."""

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

