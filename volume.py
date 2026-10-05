"""A local folder that is the Proton account, plus its Dolphin place.

The engine still reaches Drive only through the official CLI. This module
writes the mapping, the sidebar entry, and the not-yet-synced row. It does
not upload or download.
"""

import os
from urllib.parse import quote

import syncdb

MY_FILES = "/my-files"
PLACE_ID = "proton-drive-sync-volume"
PLACE_TITLE = "Proton Drive"


def default_local_dir():
    return os.path.expanduser("~/Proton Drive")


def directory_has_entries(path):
    """True when ``path`` exists and contains anything."""
    if not os.path.isdir(path):
        return False
    with os.scandir(path) as entries:
        return any(True for _entry in entries)


def ensure_empty_directory(path):
    """Create ``path`` only when it is missing or already empty.

    A file at that path, or a directory that already has children, is refused
    so an existing tree is not treated as the account.
    """
    if os.path.exists(path) and not os.path.isdir(path):
        raise ValueError("not a directory")
    if directory_has_entries(path):
        raise ValueError("not empty")
    os.makedirs(path, exist_ok=True)


def mapping_for(local_dir):
    """Two-way volume mapping. Deletion stays off."""
    return {
        "type": "folder",
        "source": os.path.abspath(local_dir),
        "dest_parent": MY_FILES,
        "direction": "twoway",
        "volume": True,
        "allow_delete": False,
        "shared_delete_confirmed": False,
    }


def _tracked(mapping):
    """A volume, or the one mapping chosen as the Proton Drive place."""
    if not isinstance(mapping, dict) or mapping.get("direction") != "twoway":
        return False
    return mapping.get("volume") is True or mapping.get("live") is True


def _volume_mapping(mappings, local_path):
    path = os.path.normpath(local_path)
    for mapping in mappings or []:
        if not _tracked(mapping):
            continue
        root = os.path.normpath(mapping.get("source") or "")
        if not root:
            continue
        if path == root or path.startswith(root + os.sep):
            return mapping, root
    return None, None


def _remote_for(mapping, root, local_path):
    rel = os.path.relpath(os.path.normpath(local_path), root)
    dest = (mapping.get("dest_parent") or MY_FILES).rstrip("/")
    if mapping.get("volume") is not True:
        dest = dest + "/" + os.path.basename(root.rstrip("/"))
    if rel in (".", ""):
        return dest
    return dest + "/" + rel.replace(os.sep, "/")


def mark_live(mappings, source):
    """The Proton Drive place opens this one folder. Other rows lose ``live``.

    The chosen folder becomes two-way. It is not turned into a copy of the
    whole account.
    """
    wanted = os.path.normpath(source)
    chosen = None
    for row in mappings or []:
        if not isinstance(row, dict):
            continue
        src = os.path.normpath(row.get("source") or "")
        if row.get("type", "folder") == "folder" and src == wanted:
            row["live"] = True
            if row.get("direction") != "twoway":
                row["direction"] = "twoway"
            chosen = row
        else:
            row.pop("live", None)
    return chosen


def note_local_change(config_path, mappings, local_path):
    """Mark one changed file inside a volume as not yet synced.

    A conflict or an error row is left as it is. A directory path is ignored.
    """
    if not isinstance(local_path, str) or not local_path:
        return False
    if os.path.isdir(local_path):
        return False
    found, root = _volume_mapping(mappings, local_path)
    if found is None:
        return False
    remote = _remote_for(found, root, local_path)
    database = syncdb.database_path(config_path)
    with syncdb.SyncDB(database) as db:
        row = db.get(os.path.normpath(local_path))
        if row and row.get("state") in ("conflict", "error"):
            return False
        if row:
            stored = dict(row)
            stored["state"] = "unsynced"
            stored["remote_path"] = remote
            db.upsert(stored)
            return True
        db.upsert({
            "local_path": os.path.normpath(local_path),
            "remote_path": remote,
            "remote_node_id": None,
            "sha1": None,
            "claimed_size": None,
            "claimed_mtime": None,
            "local_inode": None,
            "local_mtime": None,
            "state": "unsynced",
        })
    return True


def _file_uri(local_dir):
    path = os.path.abspath(local_dir).replace("\\", "/")
    if not path.startswith("/"):
        path = "/" + path
    return "file://" + quote(path, safe="/")


def _bookmark(local_dir):
    href = _file_uri(local_dir)
    return (
        " <bookmark href=\"{href}\">\n"
        "  <title>{title}</title>\n"
        "  <info>\n"
        "   <metadata owner=\"http://www.kde.org\">\n"
        "    <ID>{ident}</ID>\n"
        "    <IsHidden>false</IsHidden>\n"
        "    <icon name=\"drive-harddisk\"/>\n"
        "   </metadata>\n"
        "  </info>\n"
        " </bookmark>\n"
    ).format(href=href, title=PLACE_TITLE, ident=PLACE_ID)


def places_path():
    return os.path.expanduser("~/.local/share/user-places.xbel")


def ensure_dolphin_place(local_dir, path=None):
    """Insert the Proton Drive place. Other bookmarks in the file stay."""
    target = path or places_path()
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    bookmark = _bookmark(local_dir)
    if not os.path.exists(target):
        text = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<xbel version=\"1.0\">\n"
            + bookmark
            + "</xbel>\n"
        )
        _replace(target, text)
        return True
    with open(target, "r", encoding="utf-8") as handle:
        text = handle.read()
    if PLACE_ID in text:
        href = _file_uri(local_dir)
        start = text.find(PLACE_ID)
        open_at = text.rfind("<bookmark ", 0, start)
        if open_at < 0:
            return True
        href_at = text.find("href=\"", open_at)
        end_quote = text.find("\"", href_at + 6) if href_at >= 0 else -1
        if href_at < 0 or href_at > start or end_quote < 0:
            return True
        text = text[:href_at + 6] + href + text[end_quote:]
        _replace(target, text)
        return True
    close = text.rfind("</xbel>")
    if close < 0:
        return False
    text = text[:close] + bookmark + text[close:]
    _replace(target, text)
    return True


def _replace(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, path)


def start_watcher(mappings_path):
    """Install and start the local watcher and the consumer."""
    import realtime_manager
    result = realtime_manager.install_or_update_units(mappings_path, enable=True)
    ok = bool(result[0]) if result else False
    message = result[1] if result and len(result) > 1 else ""
    return ok, message
