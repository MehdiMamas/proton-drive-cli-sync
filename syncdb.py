"""SQLite sync database, one file per mappings file.

The path comes from ``config.DATA_DIR`` (or an explicit directory). This
module does not call the Proton CLI and does not decide uploads or downloads.
"""

import os
import sqlite3


STATES = (
    "synced",
    "pending-up",
    "pending-down",
    "conflict",
    "error",
    "unsynced",
)

_COLUMNS = (
    "local_path",
    "remote_path",
    "remote_node_id",
    "sha1",
    "claimed_size",
    "claimed_mtime",
    "local_inode",
    "local_mtime",
    "state",
)

_FOLDER_COLUMNS = (
    "local_path",
    "remote_path",
    "remote_node_id",
    "local_seen",
    "remote_seen",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    local_path TEXT PRIMARY KEY,
    remote_path TEXT NOT NULL,
    remote_node_id TEXT,
    sha1 TEXT,
    claimed_size INTEGER,
    claimed_mtime REAL,
    local_inode INTEGER,
    local_mtime REAL,
    state TEXT NOT NULL CHECK (
        state IN ('synced', 'pending-up', 'pending-down', 'conflict', 'error', 'unsynced')
    )
);
CREATE INDEX IF NOT EXISTS files_by_remote ON files (remote_path);
CREATE INDEX IF NOT EXISTS files_by_state ON files (state);
CREATE TABLE IF NOT EXISTS folders (
    local_path TEXT PRIMARY KEY,
    remote_path TEXT NOT NULL,
    remote_node_id TEXT,
    local_seen INTEGER NOT NULL DEFAULT 0,
    remote_seen INTEGER NOT NULL DEFAULT 0
);
"""

_FILES_V2 = """
CREATE TABLE files_v2 (
    local_path TEXT PRIMARY KEY,
    remote_path TEXT NOT NULL,
    remote_node_id TEXT,
    sha1 TEXT,
    claimed_size INTEGER,
    claimed_mtime REAL,
    local_inode INTEGER,
    local_mtime REAL,
    state TEXT NOT NULL CHECK (
        state IN ('synced', 'pending-up', 'pending-down', 'conflict', 'error', 'unsynced')
    )
);
"""


def database_path(mappings_file, data_dir=None):
    """Path of the SQLite file for ``mappings_file``.

    ``data_dir`` defaults to ``config.DATA_DIR``. The file name follows the
    cache: ``mappings-user1.json`` becomes ``mappings-user1.sync.sqlite``.
    """
    if data_dir is None:
        import config as appconfig
        data_dir = appconfig.DATA_DIR
    base = os.path.basename(os.fspath(mappings_file))
    if base.lower().endswith(".json"):
        base = base[:-5]
    if not base or base in (".", ".."):
        raise ValueError("mappings file name is empty")
    return os.path.join(os.fspath(data_dir), base + ".sync.sqlite")


def _optional_text(value):
    if isinstance(value, str) and value:
        return value
    return None


def _optional_int(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


class SyncDB:
    """Rows for files this mappings file has already reconciled."""

    def __init__(self, path):
        parent = os.path.dirname(os.fspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.path = os.fspath(path)
        self._conn = sqlite3.connect(self.path, timeout=5)
        try:
            self._ensure()
        except Exception:
            self._conn.close()
            raise

    def _ensure(self):
        self._conn.executescript(_SCHEMA)
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', '3')"
            )
            self._conn.commit()
            return
        if row[0] == "1":
            self._migrate_unsynced()
            row = ("2",)
        if row[0] == "2":
            # Version 3 adds the folders table, already created by _SCHEMA.
            self._conn.execute(
                "UPDATE meta SET value = '3' WHERE key = 'schema_version'"
            )
            self._conn.commit()
            return
        if row[0] != "3":
            raise ValueError("unsupported sync database version")

    def _migrate_unsynced(self):
        """Rebuild the file table so ``unsynced`` passes the state check."""
        self._conn.executescript(
            _FILES_V2 + """
            INSERT INTO files_v2
                SELECT local_path, remote_path, remote_node_id, sha1,
                       claimed_size, claimed_mtime, local_inode, local_mtime, state
                FROM files;
            DROP TABLE files;
            ALTER TABLE files_v2 RENAME TO files;
            CREATE INDEX IF NOT EXISTS files_by_remote ON files (remote_path);
            CREATE INDEX IF NOT EXISTS files_by_state ON files (state);
            UPDATE meta SET value = '2' WHERE key = 'schema_version';
            """
        )
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def get(self, local_path):
        row = self._conn.execute(
            "SELECT {cols} FROM files WHERE local_path = ?".format(
                cols=", ".join(_COLUMNS)
            ),
            (local_path,),
        ).fetchone()
        if row is None:
            return None
        return dict(zip(_COLUMNS, row))

    def rows(self):
        found = self._conn.execute(
            "SELECT {cols} FROM files".format(cols=", ".join(_COLUMNS))
        ).fetchall()
        return [dict(zip(_COLUMNS, row)) for row in found]

    def upsert(self, row):
        if not isinstance(row, dict):
            raise TypeError("row must be a dict")
        local_path = row.get("local_path")
        remote_path = row.get("remote_path")
        state = row.get("state")
        if not isinstance(local_path, str) or not local_path:
            raise ValueError("local_path is required")
        if not isinstance(remote_path, str) or not remote_path:
            raise ValueError("remote_path is required")
        if state not in STATES:
            raise ValueError("unknown state")
        values = (
            local_path,
            remote_path,
            _optional_text(row.get("remote_node_id")),
            _optional_text(row.get("sha1")),
            _optional_int(row.get("claimed_size")),
            _optional_float(row.get("claimed_mtime")),
            _optional_int(row.get("local_inode")),
            _optional_float(row.get("local_mtime")),
            state,
        )
        assignments = ", ".join(
            "{c} = excluded.{c}".format(c=column)
            for column in _COLUMNS
            if column != "local_path"
        )
        self._conn.execute(
            "INSERT INTO files ({cols}) VALUES ({marks}) "
            "ON CONFLICT(local_path) DO UPDATE SET {assignments}".format(
                cols=", ".join(_COLUMNS),
                marks=", ".join("?" for _ in _COLUMNS),
                assignments=assignments,
            ),
            values,
        )
        self._conn.commit()

    def get_folder(self, local_path):
        row = self._conn.execute(
            "SELECT local_path, remote_path, remote_node_id, local_seen, "
            "remote_seen FROM folders WHERE local_path = ?",
            (local_path,),
        ).fetchone()
        if row is None:
            return None
        return dict(zip(_FOLDER_COLUMNS, row))

    def folders(self):
        found = self._conn.execute(
            "SELECT local_path, remote_path, remote_node_id, local_seen, "
            "remote_seen FROM folders"
        ).fetchall()
        return [dict(zip(_FOLDER_COLUMNS, row)) for row in found]

    def upsert_folder(self, row):
        if not isinstance(row, dict):
            raise TypeError("row must be a dict")
        local_path = row.get("local_path")
        remote_path = row.get("remote_path")
        if not isinstance(local_path, str) or not local_path:
            raise ValueError("local_path is required")
        if not isinstance(remote_path, str) or not remote_path:
            raise ValueError("remote_path is required")
        self._conn.execute(
            "INSERT INTO folders (local_path, remote_path, remote_node_id, "
            "local_seen, remote_seen) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(local_path) DO UPDATE SET "
            "remote_path = excluded.remote_path, "
            "remote_node_id = excluded.remote_node_id, "
            "local_seen = excluded.local_seen, "
            "remote_seen = excluded.remote_seen",
            (
                local_path,
                remote_path,
                _optional_text(row.get("remote_node_id")),
                1 if row.get("local_seen") else 0,
                1 if row.get("remote_seen") else 0,
            ),
        )
        self._conn.commit()

    def delete(self, local_path):
        self._conn.execute(
            "DELETE FROM files WHERE local_path = ?",
            (local_path,),
        )
        self._conn.commit()

    def delete_folder_tree(self, local_path):
        """Forget a folder and everything the baseline holds below it."""
        prefix = local_path.rstrip(os.sep) + os.sep
        self._conn.execute(
            "DELETE FROM files WHERE substr(local_path, 1, ?) = ?",
            (len(prefix), prefix))
        self._conn.execute(
            "DELETE FROM folders WHERE local_path = ? "
            "OR substr(local_path, 1, ?) = ?",
            (local_path, len(prefix), prefix))
        self._conn.commit()

    def get_meta(self, key):
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else row[0]

    def set_meta(self, key, value):
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)))
        self._conn.commit()

    def move_tree(self, old_local, new_local, old_remote, new_remote):
        """Rewrite the paths of a moved folder and of every row below it.

        The folder row itself and the file rows keep their node ids; only
        local_path and remote_path change."""
        old_local = old_local.rstrip(os.sep)
        new_local = new_local.rstrip(os.sep)
        old_remote = old_remote.rstrip("/")
        new_remote = new_remote.rstrip("/")
        for table in ("folders", "files"):
            found = self._conn.execute(
                "SELECT local_path, remote_path FROM {t}".format(t=table)
            ).fetchall()
            for local_path, remote_path in found:
                if local_path == old_local or local_path.startswith(
                        old_local + os.sep):
                    local_new = new_local + local_path[len(old_local):]
                else:
                    continue
                if remote_path == old_remote or remote_path.startswith(
                        old_remote + "/"):
                    remote_new = new_remote + remote_path[len(old_remote):]
                else:
                    remote_new = remote_path
                self._conn.execute(
                    "UPDATE {t} SET local_path = ?, remote_path = ? "
                    "WHERE local_path = ?".format(t=table),
                    (local_new, remote_new, local_path))
        self._conn.commit()

    def move_file_row(self, old_local, new_local, new_remote, inode=None):
        """Re-key a file row to its new place, keeping its sha1 and node id."""
        row = self.get(old_local)
        if row is None:
            return
        self._conn.execute("DELETE FROM files WHERE local_path = ?",
                           (old_local,))
        row["local_path"] = new_local
        row["remote_path"] = new_remote
        if inode is not None:
            row["local_inode"] = inode
        self._conn.commit()
        self.upsert(row)
