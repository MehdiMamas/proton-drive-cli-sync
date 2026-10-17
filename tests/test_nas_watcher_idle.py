"""The NAS watcher stays alive without a NAS target and picks up the first NAS
mapping pushed later; it never exits on its own."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

import nas_watcher
import realtime_manager as rm

REPO = Path(__file__).resolve().parents[1]


def test_idle_counts_and_messages(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    assert nas_watcher.idle_counts(str(cfg)) == (0, 0)
    msg = nas_watcher.idle_message(0, 0, 30)
    assert "no mapping has been pushed" in msg and "30s" in msg

    (cfg / "mappings-user1.json").write_text(json.dumps([
        {"type": "folder", "source": "/home/user1/a", "source_kind": "local"},
        {"type": "folder", "source": "/home/user1/b", "source_kind": "local"},
    ]), encoding="utf-8")
    assert nas_watcher.idle_counts(str(cfg)) == (1, 2)
    msg = nas_watcher.idle_message(1, 2, 30)
    assert "2 mapping(s) found" in msg and "none of them on the NAS" in msg


def _wait_for(predicate, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.2)
    return False


@pytest.mark.skipif(shutil.which("true") is None, reason="needs a POSIX system")
def test_watcher_waits_then_watches_a_pushed_mapping(tmp_path):
    pytest.importorskip("pyinotify")
    base = tmp_path / "proton-sync"
    base.mkdir()
    for name in rm._NAS_SCRIPT_FILES:
        shutil.copy(REPO / name, base / name)
    (base / "config").mkdir()
    (base / "queue").mkdir()
    data = tmp_path / "data"
    data.mkdir()

    env = os.environ.copy()
    env["PROTON_SYNC_SETTINGS"] = str(base / "settings.json")
    env["PYTHONUNBUFFERED"] = "1"
    code = ("import sys; sys.path.insert(0, %r)\n"
            "import nas_watcher\n"
            "nas_watcher.run_watcher(config_dir=%r, queue_dir=%r, "
            "rescan_interval=1)\n") % (str(base), str(base / "config"),
                                       str(base / "queue"))
    log_path = tmp_path / "watcher.log"
    with open(log_path, "w") as log:
        proc = subprocess.Popen([sys.executable, "-c", code], cwd=str(base),
                                env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        assert _wait_for(lambda: "No NAS target yet" in log_path.read_text(), 15)
        time.sleep(1.5)
        assert proc.poll() is None, log_path.read_text()   # still alive

        (base / "config" / "mappings-user1.json").write_text(json.dumps([
            {"type": "folder", "source": str(data), "source_kind": "nfs"},
        ]), encoding="utf-8")
        assert _wait_for(lambda: "target added (live)" in log_path.read_text(), 15), \
            log_path.read_text()

        (data / "new.txt").write_text("x", encoding="utf-8")
        qdir = base / "queue" / "user1"
        # The catch-up and the event target the same folder: one marker file.
        assert _wait_for(lambda: "ADD [user1]" in log_path.read_text(), 15), \
            log_path.read_text()
        assert qdir.is_dir() and os.listdir(qdir)
        assert proc.poll() is None
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_selftest_on_a_parent_keeps_mapping_watches(tmp_path):
    """A correspondence test on a folder above a watched mapping must not
    remove the mapping's watches when it ends (same kernel watch ids)."""
    pytest.importorskip("pyinotify")
    share = tmp_path / "share"
    base = share / "proton-sync"
    base.mkdir(parents=True)
    for name in rm._NAS_SCRIPT_FILES:
        shutil.copy(REPO / name, base / name)
    (base / "config").mkdir()
    (base / "queue").mkdir()
    data = tmp_path / "data"
    deep = data / "deep"
    deep.mkdir(parents=True)
    (base / "config" / "mappings-user1.json").write_text(json.dumps([
        {"type": "folder", "source": str(data), "source_kind": "nfs"},
    ]), encoding="utf-8")

    env = os.environ.copy()
    env["PROTON_SYNC_SETTINGS"] = str(base / "settings.json")
    env["PYTHONUNBUFFERED"] = "1"
    code = ("import sys; sys.path.insert(0, %r)\n"
            "import nas_watcher\n"
            "nas_watcher.run_watcher(config_dir=%r, queue_dir=%r, "
            "rescan_interval=1)\n") % (str(base), str(base / "config"),
                                       str(base / "queue"))
    log_path = tmp_path / "watcher.log"
    with open(log_path, "w") as log:
        proc = subprocess.Popen([sys.executable, "-c", code], cwd=str(base),
                                env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        assert _wait_for(lambda: "Self-test listener active" in log_path.read_text(), 15)
        color, msg = rm.run_selftest(str(tmp_path), str(tmp_path), timeout=15,
                                     poll=0.1, nas_mount=str(share))
        assert color == "green", (msg, log_path.read_text())
        time.sleep(1.5)
        (deep / "after-test.txt").write_text("x", encoding="utf-8")
        assert _wait_for(lambda: "after-test.txt" in log_path.read_text(), 10), \
            log_path.read_text()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
