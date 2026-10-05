"""Document de mappings, filtres de sortie et calendrier — sans écran."""

import json
import os

from ui import calendar, document, run
from mapping_keys import carry_unknown_keys


def test_load_list_and_object(tmp_path):
    listed = tmp_path / "list.json"
    listed.write_text(json.dumps([
        {"type": "folder", "source": "/data", "dest_parent": "/my-files/a",
         "future_key": 1},
    ]), encoding="utf-8")
    doc = document.Document()
    doc.load(str(listed))
    assert doc.mappings[0]["future_key"] == 1
    assert doc.global_exclusions == {"names": [], "patterns": []}
    doc.save()
    assert json.loads(listed.read_text(encoding="utf-8"))[0]["future_key"] == 1
    assert not os.path.exists(str(listed) + ".tmp")

    obj = tmp_path / "obj.json"
    obj.write_text(json.dumps({
        "exclusions": {"names": [".tmp"], "patterns": ["*.bak"]},
        "mappings": [{"type": "file", "source": "/f", "dest_parent": "/my-files"}],
        "ignored_top": True,
    }), encoding="utf-8")
    doc.load(str(obj))
    assert doc.global_exclusions["names"] == [".tmp"]
    saved = doc.payload()
    assert saved["exclusions"]["patterns"] == ["*.bak"]
    assert "ignored_top" not in saved


def test_edit_keeps_unknown_keys_and_drops_deletion_when_off():
    old = {
        "type": "folder", "source": "/s", "dest_parent": "/my-files/d",
        "allow_delete": True, "delete_mode": "trash", "source_kind": "local",
        "excluded_remote": "prune", "future_key": {"a": 1},
    }
    new = document.build_mapping(
        old, "folder", "/s", "/my-files/d", "replace", False, "trash", "")
    assert new["future_key"] == {"a": 1}
    assert new["excluded_remote"] == "prune"
    for key in ("allow_delete", "delete_mode", "source_kind"):
        assert key not in new
    assert carry_unknown_keys(None, {"x": 1}) == {"x": 1}


def test_twoway_direction_is_opt_in_and_unknown_keys_stay():
    old = {
        "type": "folder", "source": "/s", "dest_parent": "/my-files/d",
        "direction": "twoway", "poll_minutes": 5, "future_key": 1,
        "shared_delete_confirmed": True,
    }
    kept = document.build_mapping(
        old, "folder", "/s", "/my-files/d", "replace", False, "trash", "",
        direction="twoway")
    assert kept["direction"] == "twoway"
    assert kept["poll_minutes"] == 5
    assert kept["future_key"] == 1
    assert "shared_delete_confirmed" not in kept
    upload = document.build_mapping(
        old, "folder", "/s", "/my-files/d", "replace", False, "trash", "",
        direction="upload")
    assert "direction" not in upload
    assert upload["poll_minutes"] == 5
    confirmed = document.build_mapping(
        old, "folder", "/s", "/shared-with-me/box", "replace", True, "trash",
        "local", direction="twoway", shared_delete_confirmed=True)
    assert confirmed["shared_delete_confirmed"] is True
    assert document.backup_blurb([upload]) == "Unofficial one-way backup"
    assert document.backup_blurb([kept]) == "Two-way is on for those mappings only"
    carried = {"type": "folder", "source": "/s", "dest_parent": "/my-files"}
    carry_unknown_keys(old, carried)
    assert carried["direction"] == "twoway"


def test_destination_and_source_rules():
    assert document.destination_ok("/my-files")
    assert document.destination_ok("/my-files/photos")
    assert document.destination_ok("/shared-with-me/team")
    assert not document.destination_ok("/my-filesX")
    assert not document.destination_ok("/photos")
    assert document.edit_error("", "/my-files", False, "") 
    assert document.edit_error("relative", "/my-files", False, "")
    assert document.edit_error("/abs", "/devices", False, "")
    assert document.edit_error("/abs", "/my-files", True, "")
    assert document.edit_error("/abs", "/my-files", True, "local") is None
    assert document.confirm_kind("/shared-with-me/a", True, "trash") == "shared"
    assert document.confirm_kind("/my-files", True, "permanent") == "permanent"
    assert document.confirm_kind("/my-files", False, "trash") is None
    assert document.mapping_remote_path("/my-files", "/data/photos") == "/my-files/photos"


def test_move_refuses_other_account(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    src = tmp_path / "a.json"
    dest = tmp_path / "b.json"
    src.write_text("[]", encoding="utf-8")
    dest.write_text("[]", encoding="utf-8")
    document.atomic_write_json(str(cache / "a.cache"), {"__meta__": {"account": "one"}})
    document.atomic_write_json(str(cache / "b.cache"), {"__meta__": {"account": "two"}})
    mapping = {"type": "folder", "source": "/data", "dest_parent": "/my-files"}
    plan = document.plan_move(
        str(src), str(dest), mapping, {"names": [], "patterns": []}, str(cache))
    assert plan["ok"] is False
    assert plan["reason"] == "other_account"


def test_move_copies_cache_subtree(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    src = tmp_path / "a.json"
    dest = tmp_path / "b.json"
    src.write_text(json.dumps([
        {"type": "folder", "source": "/data", "dest_parent": "/my-files"},
    ]), encoding="utf-8")
    document.atomic_write_json(str(cache / "a.cache"), {
        "__meta__": {"account": "one"},
        "/data": {"subtree_complete": True},
        "/data/child": {"subtree_complete": True},
        "/other": {"subtree_complete": True},
    })
    mapping = {"type": "folder", "source": "/data", "dest_parent": "/my-files"}
    plan = document.plan_move(
        str(src), str(dest), mapping, {"names": [], "patterns": []}, str(cache))
    assert plan["ok"] is True
    document.apply_move(
        str(src), str(dest), mapping, plan["src_account"],
        plan["copy_excl"], plan["src_excl"], str(cache))
    moved = json.loads((cache / "b.cache").read_text(encoding="utf-8"))
    left = json.loads((cache / "a.cache").read_text(encoding="utf-8"))
    assert moved["/data"]["subtree_complete"] is True
    assert "/data" not in left
    assert left["/other"]["subtree_complete"] is True
    body = json.loads(dest.read_text(encoding="utf-8"))
    assert body["mappings"][0]["source"] == "/data"


def test_ready_and_clear_primed(tmp_path):
    path = tmp_path / "m.json"
    cache = tmp_path / "m.cache"
    mapping = {"type": "folder", "source": "/data", "dest_parent": "/my-files"}
    document.atomic_write_json(str(cache), {"/data": {"subtree_complete": True, "sig": {}}})
    assert document.ready_state(mapping, document.read_cache(str(cache)), {}) == "ready"
    document.clear_primed(str(cache), "/data")
    assert document.ready_state(mapping, document.read_cache(str(cache)), {}) == "pending"
    assert document.ready_state({"type": "file", "source": "/f"}, {}, {}) == "na"
    assert not os.path.exists(str(path))


def test_engine_args_progress_and_exit_code():
    args = run.sync_args("/m.json", dry_run=True, delete=True, only_sources=["/a"])
    assert args == ["/m.json", "--dry-run", "--delete", "--only-source", "/a"]
    prime = run.prime_args("/m.json", ["/a"])
    assert "--delete" in prime and "--accept-account-change" in prime
    assert prime.count("--only-source") == 1
    reset = run.reset_args("/m.json", ["/a"], wipe=True)
    assert "--reset-source" in reset and "--wipe-remote" in reset
    assert "--delete" not in reset
    assert run.parse_progress("@@PROGRESS state=start files=2 bytes=1048576")
    assert run.parse_progress("@@PROGRESS state=done") == ""
    assert run.parse_progress("hello") is None
    assert run.is_error_line("❌ boom")
    assert not run.is_error_line("📂 /home/Rapport_erreur")
    assert run.visible_text("detail line\n", verbose=False, errors_only=False) is None
    assert run.sync_status(5).startswith("Sync finished with failures")
    assert "code 0" in run.sync_status(0)
    assert "code 5" in run.finished_banner("prime", 5, True, "/log")


def test_calendar_roundtrip():
    assert calendar.build_on_calendar("hourly", 3) == "*-*-* *:00:00"
    assert calendar.build_on_calendar("daily", 3) == "*-*-* 03:00:00"
    assert calendar.build_on_calendar("weekly", 3, "Sun") == "Sun *-*-* 03:00:00"
    assert calendar.parse_on_calendar("Mon *-*-* 15:00:00") == ("weekly", 15, "Mon")
    assert calendar.parse_on_calendar("not a calendar") is None
