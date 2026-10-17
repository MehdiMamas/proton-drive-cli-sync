"""NFS mount reading, derived correspondences and the NAS service file built
for the account set in the settings."""

import json
import os
import threading
import time

import pytest

import config
import realtime_manager as rm

MOUNTS = [
    ("/dev/sda1", "/", "ext4"),
    ("nas-test:/home/nas", "/mnt/nas-test/home_nas", "nfs4"),
    ("nas-test:/media/nas1", "/mnt/nas-test/nas1", "nfs"),
    ("nas-prod:/media/nas1", "/media/nas1", "nfs"),
    ("[fd00::3]:/srv/data", "/mnt/v6", "nfs4"),
    ("//server/share", "/mnt/smb", "cifs"),
]


def test_split_nfs_source():
    assert rm.split_nfs_source("srv:/home/nas") == ("srv", "/home/nas")
    assert rm.split_nfs_source("srv:/") == ("srv", "/")
    assert rm.split_nfs_source("[fd00::3]:/srv/data/") == ("fd00::3", "/srv/data")
    assert rm.split_nfs_source("//server/share") is None
    assert rm.split_nfs_source("srv:relative") is None
    assert rm.split_nfs_source("") is None


def test_nfs_mounts_keeps_only_nfs():
    points = [m["point"] for m in rm.nfs_mounts(MOUNTS)]
    assert points == ["/media/nas1", "/mnt/nas-test/home_nas",
                      "/mnt/nas-test/nas1", "/mnt/v6"]


def test_nas_side_path():
    assert rm.nas_side_path("/mnt/nas-test/home_nas/proton-sync", MOUNTS) == \
        "/home/nas/proton-sync"
    assert rm.nas_side_path("/mnt/nas-test/home_nas", MOUNTS) == "/home/nas"
    assert rm.nas_side_path("/mnt/nas-test/nas1/a b/c", MOUNTS) == "/media/nas1/a b/c"
    # A prefix that is not a path component does not match.
    assert rm.nas_side_path("/mnt/nas-test/nas10/x", MOUNTS) is None
    assert rm.nas_side_path("/home/user/local", MOUNTS) is None


def test_suggested_pairs_skip_shared_and_identity():
    pairs = rm.suggested_pairs("/mnt/nas-test/home_nas", MOUNTS)
    assert {"local": "/mnt/nas-test/nas1", "nas": "/media/nas1"} in pairs
    assert all(p["local"] != "/mnt/nas-test/home_nas" for p in pairs)
    assert all(p["local"] != "/media/nas1" for p in pairs)   # same both sides


def test_suggested_pairs_keep_the_shared_folder_server_only():
    mounts = MOUNTS + [("nas-prod:/media/nas1/Download",
                        "/home/user/Downloads", "nfs")]
    pairs = rm.suggested_pairs("/mnt/nas-test/home_nas", mounts)
    assert pairs == [{"local": "/mnt/nas-test/nas1", "nas": "/media/nas1"}]


def test_suggested_service_account():
    assert rm.suggested_service_account("/home/nas/proton-sync") == "nas"
    assert rm.suggested_service_account("/srv/proton/proton-sync") == ""
    assert rm.suggested_service_account("/home") == ""


def test_service_text_for_account_and_dir():
    text = rm.build_nas_service_text("nasuser", "/srv/proton sync")
    assert "User=nasuser\n" in text
    assert "WorkingDirectory=/srv/proton sync\n" in text
    assert 'ExecStart=/usr/bin/python3 "/srv/proton sync/nas_watcher.py"\n' in text
    assert "Group=" not in text
    assert "WantedBy=multi-user.target" in text
    cmd = rm.nas_service_install_command("/home/nas/proton-sync")
    assert cmd.startswith("sudo cp /home/nas/proton-sync/proton-nas-watch.service "
                          "/etc/systemd/system/ && sudo systemctl daemon-reload")
    assert "enable proton-nas-watch.service" in cmd
    assert cmd.endswith("restart proton-nas-watch.service")


def test_odd_paths_are_quoted_and_escaped():
    text = rm.build_nas_service_text("nas", "/srv/50%/sync")
    assert "WorkingDirectory=/srv/50%%/sync\n" in text
    assert "ExecStart=/usr/bin/python3 /srv/50%%/sync/nas_watcher.py\n" in text
    cmd = rm.nas_service_install_command("/srv/it's here")
    assert cmd.startswith("sudo cp '/srv/it'\"'\"'s here/proton-nas-watch.service' ")


@pytest.mark.parametrize("name", ["nas", "nas_user", "user-1", "a.b"])
def test_valid_account_names(name):
    assert config.valid_account_name(name)


@pytest.mark.parametrize("name", ["", "1abc", "nas\nUser=root", "two words",
                                  "x" * 40, None, "nas\n", "_svc"])
def test_invalid_account_names(name):
    assert not config.valid_account_name(name)


@pytest.fixture
def shared(tmp_path, monkeypatch):
    """A shared folder 'mounted' from nas-test:/home/nas at <tmp>/home_nas."""
    mount = tmp_path / "home_nas"
    mount.mkdir()
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"language": "en", "nas_enabled": True,
                                    "nas_mount_path": str(mount)}),
                        encoding="utf-8")
    monkeypatch.setenv("PROTON_SYNC_SETTINGS", str(settings))
    fake = [("nas-test:/home/nas", str(mount), "nfs4")]
    monkeypatch.setattr(rm.mount_check, "_read_mounts", lambda: fake)
    monkeypatch.setattr(rm, "nas_reachable", lambda: True)
    rm.refresh_nas_paths()
    yield mount
    monkeypatch.undo()
    rm.refresh_nas_paths()


def test_no_account_builds_no_service_file(shared):
    ok, _msg, cmd = rm.push_scripts_to_nas()
    assert ok
    assert not (shared / "proton-sync" / rm.NAS_SERVICE_NAME).exists()
    assert cmd == "sudo systemctl restart proton-nas-watch.service"


def test_account_builds_and_pushes_service_file(shared):
    assert config.set_nas_service_account("nas")
    ok, msg, cmd = rm.push_scripts_to_nas()
    assert ok, msg
    svc = shared / "proton-sync" / rm.NAS_SERVICE_NAME
    text = svc.read_text(encoding="utf-8")
    assert "User=nas\n" in text
    assert "WorkingDirectory=/home/nas/proton-sync\n" in text
    assert cmd == rm.nas_service_install_command("/home/nas/proton-sync")
    assert rm.nas_scripts_stale() is False

    # Same account again: nothing changes, the plain restart is offered.
    ok, _msg, cmd = rm.push_scripts_to_nas()
    assert ok and cmd is None

    # Another account: the file is rewritten and flagged as stale beforehand.
    assert config.set_nas_service_account("watcher")
    assert rm.nas_scripts_stale() is True
    ok, _msg, cmd = rm.push_scripts_to_nas()
    assert "User=watcher\n" in svc.read_text(encoding="utf-8")
    assert cmd.startswith("sudo cp ")


def test_invalid_account_is_refused_and_not_written(shared):
    assert not config.set_nas_service_account("nas\nUser=root")
    assert config.nas_service_account() == ""


def test_refresh_follows_a_new_mount(shared, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    config.set_nas_mount_path(str(other))
    assert rm.NAS_BASE == os.path.join(str(shared), "proton-sync")
    rm.refresh_nas_paths()
    assert rm.NAS_BASE == os.path.join(str(other), "proton-sync")
    assert rm.NAS_CONFIG_DIR == os.path.join(str(other), "proton-sync", "config")


def test_selftest_uses_the_mount_it_is_given(shared, tmp_path):
    """The request lands under the mount passed in, not the saved one."""
    shown = tmp_path / "shown"
    shown.mkdir()
    seen = []

    def spy():
        sdir = shown / "proton-sync" / "selftest"
        for _ in range(100):
            if sdir.is_dir() and any(n.startswith("request-")
                                     for n in os.listdir(sdir)):
                seen.append(True)
                return
            time.sleep(0.02)

    t = threading.Thread(target=spy)
    t.start()
    color, _msg = rm.run_selftest(str(tmp_path), "/x", timeout=1.0, poll=0.05,
                                  nas_mount=str(shown))
    t.join()
    assert seen == [True]
    assert color == "yellow"            # nobody answered
    assert not (shared / "proton-sync" / "selftest").exists()
