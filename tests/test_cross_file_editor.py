"""Editor side of the conflicts between the two mappings files in service."""

import json
import types

import pytest

import mapping_keys as mk


def _m(source, dest, **extra):
    m = {"type": "folder", "source": source, "dest_parent": dest}
    m.update(extra)
    return m


def _write(path, mappings, exclusions=None):
    doc = {"mappings": mappings}
    if exclusions is not None:
        doc["exclusions"] = exclusions
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


def test_cross_conflicts_skip_the_same_mapping_only():
    mine = [_m("/h/Photos", "/my-files/S"), _m("/h/Docs", "/my-files/S")]
    theirs = [_m("/h/Photos/", "/my-files/S/"), _m("/n/Docs", "/my-files/S"),
              _m("/n/Inv", "/my-files/S/Docs")]
    found = mk.cross_conflicts(mine, {}, theirs, {})
    assert [(i, j, k) for i, j, k, _a, _b in found] == [(1, 1, "same"), (1, 2, "contains")]
    # Same source and destination, other exclusions: a conflict.
    found = mk.cross_conflicts(mine, {"names": ["tmp"]}, theirs, {})
    assert (0, 0, "same") in [(i, j, k) for i, j, k, _a, _b in found]


def test_other_running_files():
    assert mk.other_running_files("/x/a.json", ["/x/a.json", None, "/x/b.json",
                                                "/x/b.json"]) == ["/x/b.json"]
    assert mk.other_running_files(None, ["/x/a.json", None]) == ["/x/a.json"]


def test_read_mappings_document(tmp_path):
    p = _write(tmp_path / "m.json", [_m("/a/X", "/my-files")], {"names": ["n"]})
    maps, g = mk.read_mappings_document(p)
    assert maps[0]["source"] == "/a/X" and g == {"names": ["n"], "patterns": []}
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    assert mk.read_mappings_document(str(tmp_path / "bad.json")) is None
    assert mk.read_mappings_document(str(tmp_path / "none.json")) is None


def test_install_confirmation_only_when_files_conflict(tmp_path, monkeypatch):
    ed = pytest.importorskip("proton_mapping_editor")
    asked = []
    monkeypatch.setattr(ed, "dlg_confirm", lambda *a, **k: asked.append(a[1]) or False)
    a = _write(tmp_path / "a.json", [_m("/h/Photos", "/my-files/S")])
    b = _write(tmp_path / "b.json", [_m("/n/Photos", "/my-files/S")])
    c = _write(tmp_path / "c.json", [_m("/n/Other", "/my-files/S")])
    assert ed.confirm_cross_file_install(None, a, [c]) is True
    assert asked == []
    assert ed.confirm_cross_file_install(None, a, [a]) is True
    assert ed.confirm_cross_file_install(None, a, [b]) is False
    assert len(asked) == 1 and "b.json" in asked[0] and "/n/Photos" in asked[0]


def test_load_warns_about_the_other_file(tmp_path, monkeypatch):
    ed = pytest.importorskip("proton_mapping_editor")
    shown = []
    monkeypatch.setattr(ed, "dlg_warning", lambda *a, **k: shown.append(a[1]))
    a = _write(tmp_path / "a.json", [_m("/h/Photos", "/my-files/S")])
    b = _write(tmp_path / "b.json", [_m("/n/Photos", "/my-files/S")])
    monkeypatch.setattr(ed, "running_mappings_files", lambda: [a, b])
    stub = types.SimpleNamespace(config_path=a, mappings=json.load(open(a))["mappings"],
                                 global_exclusions={"names": [], "patterns": []})
    ed.MappingEditor._warn_cross_file_conflicts(stub)
    assert len(shown) == 1 and "b.json" in shown[0]
    monkeypatch.setattr(ed, "running_mappings_files", lambda: [a, a])
    shown.clear()
    ed.MappingEditor._warn_cross_file_conflicts(stub)
    assert shown == []


def test_a_file_in_preparation_is_not_warned(tmp_path, monkeypatch):
    ed = pytest.importorskip("proton_mapping_editor")
    shown = []
    monkeypatch.setattr(ed, "dlg_warning", lambda *a, **k: shown.append(a[1]))
    a = _write(tmp_path / "a.json", [_m("/h/Photos", "/my-files/S")])
    b = _write(tmp_path / "b.json", [_m("/n/Photos", "/my-files/S")])
    # Both services run on b; a is being prepared and is not in service.
    monkeypatch.setattr(ed, "running_mappings_files", lambda: [b, b])
    stub = types.SimpleNamespace(config_path=a, mappings=json.load(open(a))["mappings"],
                                 global_exclusions={"names": [], "patterns": []})
    ed.MappingEditor._warn_cross_file_conflicts(stub)
    assert shown == []
    assert ed.file_in_service(a, [b, b]) is False
    assert ed.file_in_service(b, [None, b]) is True
