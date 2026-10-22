"""Tests for opening the sync database from several places at once."""

import sqlite3
import threading

import syncdb


def _pragma(database, name):
    return database._conn.execute("PRAGMA " + name).fetchone()[0]


def test_database_opens_in_wal_mode_with_busy_timeout(tmp_path):
    with syncdb.SyncDB(tmp_path / "s.db") as database:
        assert _pragma(database, "journal_mode") == "wal"
        assert _pragma(database, "busy_timeout") == syncdb.BUSY_TIMEOUT_MS


def test_two_open_handles_see_each_others_rows(tmp_path):
    path = tmp_path / "s.db"
    with syncdb.SyncDB(path) as first, syncdb.SyncDB(path) as second:
        first.upsert({"local_path": "/f", "remote_path": "/r/f",
                      "state": "synced"})
        assert second.get("/f")["remote_path"] == "/r/f"
        second.upsert_folder({"local_path": "/d", "remote_path": "/r/d"})
        assert first.get_folder("/d")["remote_path"] == "/r/d"


def test_reader_is_not_blocked_by_an_open_write_transaction(tmp_path):
    path = tmp_path / "s.db"
    with syncdb.SyncDB(path) as database:
        database.upsert({"local_path": "/f", "remote_path": "/r/f",
                         "state": "synced"})
        other = sqlite3.connect(str(path), timeout=0.1)
        try:
            other.execute("BEGIN IMMEDIATE")
            other.execute("UPDATE meta SET value = value WHERE key = 'x'")
            assert database.get("/f")["remote_path"] == "/r/f"
        finally:
            other.rollback()
            other.close()


def test_writer_waits_for_another_writer_instead_of_failing(tmp_path):
    path = tmp_path / "s.db"
    syncdb.SyncDB(path).close()
    blocker = sqlite3.connect(str(path), timeout=5)
    blocker.execute("BEGIN IMMEDIATE")
    errors = []

    def write():
        try:
            with syncdb.SyncDB(path) as database:
                database.upsert({"local_path": "/w", "remote_path": "/r/w",
                                 "state": "synced"})
        except Exception as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    thread = threading.Thread(target=write)
    thread.start()
    thread.join(0.5)
    assert thread.is_alive()  # waiting on the lock, not failed
    blocker.rollback()
    blocker.close()
    thread.join(10)
    assert not thread.is_alive()
    assert errors == []
    with syncdb.SyncDB(path) as database:
        assert database.get("/w")["remote_path"] == "/r/w"


def test_many_threads_write_the_same_database(tmp_path):
    path = tmp_path / "s.db"
    syncdb.SyncDB(path).close()
    errors = []

    def work(n):
        try:
            for i in range(10):
                with syncdb.SyncDB(path) as database:
                    database.upsert({"local_path": "/t%d/%d" % (n, i),
                                     "remote_path": "/r", "state": "synced"})
        except Exception as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == []
    with syncdb.SyncDB(path) as database:
        assert len(list(database.rows())) == 60
