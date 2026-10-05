"""Volume folder, Dolphin place, and the status process the window owns."""

import os
import sqlite3

import syncdb
import volume
from ui.status_service import StatusService, close_action


def test_empty_directory_is_refused_when_it_has_files(tmp_path):
    folder = tmp_path / "Proton Drive"
    folder.mkdir()
    (folder / "already.txt").write_text("x", encoding="utf-8")
    try:
        volume.ensure_empty_directory(str(folder))
    except ValueError as exc:
        assert str(exc) == "not empty"
    else:
        raise AssertionError("a folder with files was accepted")
    empty = tmp_path / "Empty"
    volume.ensure_empty_directory(str(empty))
    assert empty.is_dir()
    assert list(empty.iterdir()) == []


def test_dolphin_place_is_added_without_removing_other_bookmarks(tmp_path):
    places = tmp_path / "user-places.xbel"
    places.write_text(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<xbel version=\"1.0\">\n"
        " <bookmark href=\"file:///home/keep\">\n"
        "  <title>Keep</title>\n"
        " </bookmark>\n"
        "</xbel>\n",
        encoding="utf-8")
    local = tmp_path / "Proton Drive"
    local.mkdir()
    assert volume.ensure_dolphin_place(str(local), str(places))
    text = places.read_text(encoding="utf-8")
    assert "file:///home/keep" in text
    assert volume.PLACE_ID in text
    assert "Proton%20Drive" in text
    assert volume.ensure_dolphin_place(str(local), str(places))
    again = places.read_text(encoding="utf-8")
    assert again.count(volume.PLACE_ID) == 1
    assert "file:///home/keep" in again


def test_local_change_is_unsynced_then_pending_then_synced(tmp_path, monkeypatch):
    import twoway
    root = tmp_path / "Proton Drive"
    root.mkdir()
    local = root / "a.txt"
    local.write_bytes(b"AAAA")
    os.utime(local, (1_000_000_000, 1_000_000_000))
    cfg = tmp_path / "mappings.json"
    cfg.write_text("[]", encoding="utf-8")
    mapping = volume.mapping_for(str(root))
    assert volume.note_local_change(str(cfg), [mapping], str(local))
    with syncdb.SyncDB(syncdb.database_path(str(cfg))) as db:
        assert db.get(os.path.normpath(str(local)))["state"] == "unsynced"

    seen = []

    def upload_batch(paths, folder, **kwargs):
        with syncdb.SyncDB(syncdb.database_path(str(cfg))) as db:
            seen.append(db.get(os.path.normpath(str(local)))["state"])
        return True

    monkeypatch.setattr(twoway._ps, "upload_batch", upload_batch)
    ctx = twoway._Ctx(
        mapping, syncdb.SyncDB(syncdb.database_path(str(cfg))),
        None, None, False, False, {}, str(root), str(cfg))
    assert twoway._upload(str(local), "/my-files", None, ctx)
    assert seen == ["pending-up"]
    with syncdb.SyncDB(syncdb.database_path(str(cfg))) as db:
        assert db.get(os.path.normpath(str(local)))["state"] == "synced"
    ctx.db.close()


def test_schema_v1_accepts_unsynced_after_open(tmp_path):
    path = tmp_path / "old.sync.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta (key, value) VALUES ('schema_version', '1');
        CREATE TABLE files (
            local_path TEXT PRIMARY KEY,
            remote_path TEXT NOT NULL,
            remote_node_id TEXT,
            sha1 TEXT,
            claimed_size INTEGER,
            claimed_mtime REAL,
            local_inode INTEGER,
            local_mtime REAL,
            state TEXT NOT NULL CHECK (
                state IN ('synced', 'pending-up', 'pending-down', 'conflict', 'error')
            )
        );
        """
    )
    conn.execute(
        "INSERT INTO files (local_path, remote_path, state) VALUES (?, ?, ?)",
        ("/data/a.txt", "/my-files/a.txt", "synced"),
    )
    conn.commit()
    conn.close()
    with syncdb.SyncDB(str(path)) as db:
        db.upsert({
            "local_path": "/data/b.txt",
            "remote_path": "/my-files/b.txt",
            "state": "unsynced",
        })
        assert db.get("/data/a.txt")["state"] == "synced"
        assert db.get("/data/b.txt")["state"] == "unsynced"


def test_choose_mapping_points_proton_drive_at_that_folder(tmp_path, monkeypatch):
    import local_watcher
    docs = tmp_path / "Docs"
    other = tmp_path / "Other"
    docs.mkdir()
    other.mkdir()
    (docs / "a.txt").write_bytes(b"AAAA")
    rows = [
        {"type": "folder", "source": str(docs), "dest_parent": "/my-files/Backups"},
        {"type": "folder", "source": str(other), "dest_parent": "/my-files/Other"},
    ]
    chosen = volume.mark_live(rows, str(docs))
    assert chosen["live"] is True
    assert chosen["direction"] == "twoway"
    assert "volume" not in chosen
    assert "live" not in rows[1]
    cfg = tmp_path / "mappings.json"
    cfg.write_text("[]", encoding="utf-8")
    assert volume.note_local_change(str(cfg), rows, str(docs / "a.txt"))
    with syncdb.SyncDB(syncdb.database_path(str(cfg))) as db:
        row = db.get(os.path.normpath(str(docs / "a.txt")))
    assert row["state"] == "unsynced"
    assert row["remote_path"] == "/my-files/Backups/Docs/a.txt"
    monkeypatch.setattr(local_watcher, "source_kind_of", lambda _path: "local")
    watched = local_watcher.select_targets(rows)
    assert [item["watch_dir"] for item in watched] == [os.path.normpath(str(docs))]
    places = tmp_path / "user-places.xbel"
    volume.ensure_dolphin_place(str(docs), str(places))
    text = places.read_text(encoding="utf-8")
    assert volume.PLACE_TITLE in text
    assert text.count("<bookmark ") == 1


def test_close_action_hides_until_quit():
    assert close_action(False, False, True) == "hide"
    assert close_action(False, True, False) == "stay"
    assert close_action(True, True, False) == "quit"


class _Proc:
    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def kill(self):
        self.returncode = 0


def test_status_service_starts_one_child_and_stops_it(tmp_path):
    mappings = tmp_path / "mappings.json"
    mappings.write_text("[]", encoding="utf-8")
    started = []

    def popen(argv, **kwargs):
        started.append(argv)
        return _Proc()

    service = StatusService(probe=lambda: False, popen=popen)
    assert service.ensure(str(mappings)) is True
    assert service.ensure(str(mappings)) is True
    assert len(started) == 1
    assert started[0][1].endswith("cloudproviders.py")
    assert started[0][2:] == ["--mappings", str(mappings)]
    service.stop()
    assert service.running() is False
    busy = StatusService(probe=lambda: True, popen=popen)
    assert busy.ensure(str(mappings)) is False
    assert len(started) == 1
