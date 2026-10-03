"""JSON remote-drive state shared by the fake proton-drive CLI and the tests.

`claimedModificationTime` is the local file's `st_mtime` in POSIX seconds,
captured when the fake stores the upload. That mirrors a plausible CLI
behaviour and is enough for the phase 1 harness. Phase 2 has to check what
the real `proton-drive` binary actually puts in that field (local mtime,
server time, or nothing) and update the fake to match.
"""

import base64
import hashlib
import json
import os

# Encrypted size is larger than the original. The engine prefers claimedSize
# and only falls back to totalStorageSize, so the overhead must not leak into
# a comparison that uses the claimed field.
STORAGE_OVERHEAD = 64


def default_state():
    return {
        "account": "tester@example.com",
        "version_text": (
            "Proton Drive CLI cli-drive@0.8.0+fake\n"
            "Proton Drive SDK js@0.19.1+fake\n"
        ),
        "nodes": {
            "/my-files": {"type": "folder"},
        },
        "faults": [],
        "calls": [],
        "uploads": [],
        "upload_cwds": [],
    }


def normalize(path):
    if path is None:
        return "/"
    raw = str(path).strip()
    if raw in ("", "/"):
        return "/"
    parts = [p for p in raw.split("/") if p and p != "."]
    return "/" + "/".join(parts)


def unescape_glob(name):
    """Undo the engine's `[x]` glob escapes. `a[[]b.txt` becomes `a[b.txt`."""
    out = []
    i = 0
    while i < len(name):
        if name[i] == "[" and i + 2 < len(name) and name[i + 2] == "]":
            out.append(name[i + 1])
            i += 3
        else:
            out.append(name[i])
            i += 1
    return "".join(out)


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = default_state()
    if not isinstance(data, dict):
        data = default_state()
    data.setdefault("account", "tester@example.com")
    data.setdefault("version_text", default_state()["version_text"])
    data.setdefault("nodes", {"/my-files": {"type": "folder"}})
    data.setdefault("faults", [])
    data.setdefault("calls", [])
    data.setdefault("uploads", [])
    data.setdefault("upload_cwds", [])
    return data


def save(path, state):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle)
    os.replace(tmp, path)


def ensure_folders(state, remote_path):
    parts = [p for p in normalize(remote_path).strip("/").split("/") if p]
    current = ""
    for part in parts[:-1]:
        current = current + "/" + part
        state["nodes"].setdefault(current, {"type": "folder"})


def direct_children(state, path):
    """Non-trashed direct children as (name, node) pairs."""
    path = normalize(path)
    found = []
    for node_path, node in state["nodes"].items():
        if node.get("trashed"):
            continue
        if path == "/":
            rest = node_path.strip("/")
            if rest and "/" not in rest:
                found.append((rest, node))
            continue
        prefix = path + "/"
        if node_path.startswith(prefix):
            rest = node_path[len(prefix):]
            if rest and "/" not in rest:
                found.append((rest, node))
    found.sort(key=lambda item: item[0])
    return found


def list_item(name, node, account):
    """One `filesystem list -j` element, in the shape `_unwrap` expects."""
    item = {
        "name": name,
        "type": {"ok": True, "value": node.get("type", "file")},
        "keyAuthor": {"ok": True, "value": account},
    }
    if node.get("type") != "file":
        return item
    raw = base64.b64decode(node.get("content_b64") or "")
    size = len(raw)
    # remove_size_meta drops both claimedSize and the totalStorageSize
    # fallback, so the engine sees an unknown size and chooses to re-send.
    if not node.get("remove_size_meta"):
        item["totalStorageSize"] = size + STORAGE_OVERHEAD
    revision = {"claimedModificationTime": node.get("mtime")}
    if not node.get("remove_size_meta"):
        revision["claimedSize"] = size
    if not node.get("remove_digest"):
        revision["claimedDigests"] = {"sha1": hashlib.sha1(raw).hexdigest()}
    item["activeRevision"] = {"ok": True, "value": revision}
    return item


def _fault_matches(fault, cmd, text):
    if fault.get("cmd") != cmd:
        return False
    match = fault.get("match")
    if not match:
        return True
    if str(text).startswith("/"):
        return match == text
    return match == text or match in text


def consume_faults(state, cmd, text):
    """Return faults that fire for this command, and decrement `times`.

    A missing `times` fires on every match. `times: 1` fires once.
    """
    fired = []
    kept = []
    for fault in state.get("faults", []):
        if not _fault_matches(fault, cmd, text):
            kept.append(fault)
            continue
        times = fault.get("times")
        if times is not None and times <= 0:
            kept.append(fault)
            continue
        fired.append(fault)
        if times is None:
            kept.append(fault)
        else:
            updated = dict(fault)
            updated["times"] = times - 1
            if updated["times"] > 0:
                kept.append(updated)
    state["faults"] = kept
    return fired


def store_file(state, remote_path, data, mtime):
    """Replace semantics: an existing file keeps its revision counter and bumps it."""
    remote_path = normalize(remote_path)
    ensure_folders(state, remote_path)
    previous = state["nodes"].get(remote_path)
    revisions = 1
    if isinstance(previous, dict) and previous.get("type") == "file":
        revisions = int(previous.get("revisions") or 1) + 1
    state["nodes"][remote_path] = {
        "type": "file",
        "content_b64": base64.b64encode(data).decode("ascii"),
        "mtime": int(mtime),
        "revisions": revisions,
        "trashed": False,
    }
    state.setdefault("uploads", []).append(remote_path)
    return remote_path


def trash_tree(state, remote_path):
    remote_path = normalize(remote_path)
    node = state["nodes"].get(remote_path)
    if not isinstance(node, dict):
        return False
    node["trashed"] = True
    prefix = remote_path + "/"
    for path, child in state["nodes"].items():
        if path.startswith(prefix):
            child["trashed"] = True
    return True


def file_bytes(state, remote_path):
    node = state["nodes"].get(normalize(remote_path))
    if not isinstance(node, dict) or node.get("type") != "file" or node.get("trashed"):
        return None
    return base64.b64decode(node.get("content_b64") or "")
