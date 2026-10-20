"""Two-way support in the Tk editor: mode, conflict warning, trigger setting.

The pure helpers need no display; the editor tests use the same headless stub
as test_mapping_file_keys.py and are skipped without tkinter.
"""

import json
import types

import pytest

import mapping_keys as mk


def _m(source, dest="/my-files/B", **extra):
    m = {"type": "folder", "source": source, "dest_parent": dest}
    m.update(extra)
    return m


def _tw(source, dest="/my-files/B", **extra):
    return _m(source, dest, direction="twoway", **extra)


def test_load_marks_sync_mappings_and_keeps_order():
    data = {"mappings": [_m("/a")], "sync_mappings": [_tw("/b", allow_delete=True)]}
    mappings, _gex, extras = mk.split_loaded(data)
    assert [mk.sync_mode(m) for m in mappings] == [mk.MODE_UPLOAD, mk.MODE_TWOWAY]
    assert extras == {}
    assert mk.MODE_KEY not in data["sync_mappings"][0]   # input untouched


def test_roundtrip_is_lossless_and_marker_never_written():
    data = {"exclusions": {"names": ["x"], "patterns": []},
            "mappings": [_m("/a", future="1")],
            "sync_mappings": [_tw("/b", future="2", delete_mode="trash")],
            "something_new": {"k": 1}}
    mappings, gex, extras = mk.split_loaded(data)
    out = mk.build_output(mappings, gex, extras)
    assert out == data
    assert mk.MODE_KEY not in json.dumps(out)


def test_moving_between_modes_keeps_fields_and_unknown_keys():
    mappings, gex, extras = mk.split_loaded(
        [_m("/a", allow_delete=True, future={"k": 1}, exclusions={"names": ["n"], "patterns": []})])
    mk.set_sync_mode(mappings[0], mk.MODE_TWOWAY)
    out = mk.build_output(mappings, gex, extras)
    assert out["mappings"] == []
    moved = out["sync_mappings"][0]
    assert moved == _tw("/a", allow_delete=True, future={"k": 1},
                        exclusions={"names": ["n"], "patterns": []})

    mappings, gex, extras = mk.split_loaded(out)
    mk.set_sync_mode(mappings[0], mk.MODE_UPLOAD)
    back = mk.build_output(mappings, gex, extras)
    assert back["mappings"] == [_m("/a", allow_delete=True, future={"k": 1},
                                   exclusions={"names": ["n"], "patterns": []})]
    assert "sync_mappings" not in back


def test_an_unknown_direction_value_is_kept():
    mappings, gex, extras = mk.split_loaded({"sync_mappings": [_m("/a", direction="later")]})
    out = mk.build_output(mappings, gex, extras)
    assert out["sync_mappings"][0]["direction"] == "later"


def test_a_non_list_sync_mappings_is_left_alone():
    mappings, gex, extras = mk.split_loaded({"mappings": [_m("/a")], "sync_mappings": "?"})
    assert mk.build_output(mappings, gex, extras)["sync_mappings"] == "?"


def test_plain_list_stays_a_list():
    data = [_m("/a"), _m("/b")]
    mappings, gex, extras = mk.split_loaded(data)
    assert mk.build_output(mappings, gex, extras) == data


def test_dialog_result_does_not_inherit_old_marker():
    old = mk.set_sync_mode(_m("/a"), mk.MODE_TWOWAY)
    new = {"type": "folder", "source": "/a", "dest_parent": "/my-files/B"}
    mk.carry_unknown_keys(old, new)
    assert mk.sync_mode(new) == mk.MODE_UPLOAD


def test_twoway_conflicts_use_flat_list_indices():
    mappings, _g, _e = mk.split_loaded({
        "mappings": [_m("/h/Docs", "/my-files/X")],
        "sync_mappings": [_tw("/h/Docs/sub", "/my-files/Y"), _tw("/h/Free", "/my-files/Z")]})
    found = mk.twoway_conflicts(mappings)
    assert [(i, reason) for i, reason, _o, _d in found] == [(1, "local-child")]
    assert found[0][2]["source"] == "/h/Docs"


def test_set_twoway_trigger(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "_write_raw", lambda k, v: store.update({k: v}) or True)
    store = {}
    config.set_twoway_trigger(" None ")
    assert store == {"twoway_trigger": "none"}


def test_trigger_choices_come_from_the_engine():
    import proton_sync
    assert "none" in proton_sync.TWOWAY_TRIGGERS


# -- the editor itself (needs tkinter, no display) -----------------------------

def _editor_stub():
    ed = pytest.importorskip("proton_mapping_editor")
    stub = types.SimpleNamespace(
        mappings=[], global_exclusions={"names": [], "patterns": []},
        _extra_top={}, config_path=None,
        status=types.SimpleNamespace(set=lambda *_a: None),
        _set_dirty=lambda *_a: None, _refresh_tree=lambda: None,
        _update_excl_summary=lambda: None, _auto_push_mappings=lambda *_a: None,
        _warn_revisions_unsupported=lambda: None,
        _warn_permanent_delete_unsupported=lambda: None,
    )
    stub._warn_arrival_conflicts = lambda: ed.MappingEditor._warn_arrival_conflicts(stub)
    stub._twoway_conflict_lines = lambda: ed.MappingEditor._twoway_conflict_lines(stub)
    stub._warn_twoway_conflicts = lambda: ed.MappingEditor._warn_twoway_conflicts(stub)
    return ed, stub


def test_editor_load_warns_naming_the_conflicting_mapping(tmp_path, monkeypatch):
    ed, stub = _editor_stub()
    shown = []
    monkeypatch.setattr(ed, "dlg_warning", lambda *a, **k: shown.append(a[1]))
    path = tmp_path / "mappings.json"
    path.write_text(json.dumps({
        "mappings": [_m("/h/Docs", "/my-files/X")],
        "sync_mappings": [_tw("/h/Docs/sub", "/my-files/Y")]}), encoding="utf-8")
    ed.MappingEditor._load(stub, str(path))
    assert len(shown) == 1
    assert "/h/Docs/sub" in shown[0] and "/h/Docs" in shown[0]
    assert "inside the local folder" in shown[0]
    # Not dropped: still listed, still two-way.
    assert [mk.sync_mode(m) for m in stub.mappings] == [mk.MODE_UPLOAD, mk.MODE_TWOWAY]


def test_editor_load_names_an_arrival_folder_conflict(tmp_path, monkeypatch):
    ed, stub = _editor_stub()
    shown = []
    monkeypatch.setattr(ed, "dlg_warning", lambda *a, **k: shown.append(a[1]))
    path = tmp_path / "mappings.json"
    path.write_text(json.dumps({
        "mappings": [_m("/h/Share", "/my-files")],
        "sync_mappings": [_tw("/n/Share", "/my-files")]}), encoding="utf-8")
    ed.MappingEditor._load(stub, str(path))
    assert len(shown) == 1   # one message: the two-way one, not also the upload one
    assert "/n/Share" in shown[0] and "/my-files/Share" in shown[0]


def test_editor_load_is_silent_without_conflict(tmp_path, monkeypatch):
    ed, stub = _editor_stub()
    shown = []
    monkeypatch.setattr(ed, "dlg_warning", lambda *a, **k: shown.append(a[1]))
    path = tmp_path / "mappings.json"
    path.write_text(json.dumps({"mappings": [_m("/h/A", "/my-files/X")],
                                "sync_mappings": [_tw("/h/B", "/my-files/Y")]}),
                    encoding="utf-8")
    ed.MappingEditor._load(stub, str(path))
    assert shown == []


def test_editor_save_warns_before_writing_and_keeps_the_mapping(tmp_path, monkeypatch):
    ed, stub = _editor_stub()
    order = []
    monkeypatch.setattr(ed, "dlg_warning", lambda *a, **k: order.append("warn"))
    path = tmp_path / "mappings.json"
    stub.mappings = [_m("/h/Docs", "/my-files/X"),
                     mk.set_sync_mode(_m("/h/Docs", "/my-files/Y"), mk.MODE_TWOWAY)]
    real_replace = ed.os.replace
    monkeypatch.setattr(ed.os, "replace", lambda a, b: (order.append("write"), real_replace(a, b)))
    ed.MappingEditor._save(stub, str(path))
    assert order == ["warn", "write"]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert [m["source"] for m in saved["sync_mappings"]] == ["/h/Docs"]


def test_editor_save_moves_a_mapping_between_lists(tmp_path):
    ed, stub = _editor_stub()
    path = tmp_path / "mappings.json"
    path.write_text(json.dumps([_m("/h/A", future="x"), _m("/h/B")]), encoding="utf-8")
    ed.MappingEditor._load(stub, str(path))
    mk.set_sync_mode(stub.mappings[0], mk.MODE_TWOWAY)
    ed.MappingEditor._save(stub, str(path))
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["sync_mappings"] == [_tw("/h/A", future="x")]
    assert saved["mappings"] == [_m("/h/B")]
