"""Sync mode (upload only / two-way) in the mapping editor's pure helpers.

A two-way mapping lives under "twoway_mappings" in the file; "mappings" stays
upload-only. These tests need no display: they cover the load/save round trip
and the switch between modes without importing Tk.
"""

import json

import mapping_keys as mk
import proton_sync


def _m(source, **extra):
    m = {"type": "folder", "source": source, "dest_parent": "/my-files/B"}
    m.update(extra)
    return m


def _roundtrip(data):
    mappings, gex, extras = mk.split_loaded(data)
    return mk.build_output(mappings, gex, extras)


def test_load_marks_twoway_mappings():
    data = {"mappings": [_m("/a")], "twoway_mappings": [_m("/b", allow_delete=True)]}
    mappings, _gex, _extras = mk.split_loaded(data)
    assert [mk.sync_mode(m) for m in mappings] == [mk.MODE_UPLOAD, mk.MODE_TWOWAY]
    assert mappings[1]["allow_delete"] is True
    assert mk.MODE_KEY not in data["twoway_mappings"][0]   # input untouched


def test_roundtrip_keeps_both_lists_and_order():
    data = {
        "mappings": [_m("/a"), _m("/c", exclusions={"names": ["x"], "patterns": []})],
        "twoway_mappings": [_m("/b"), _m("/d", allow_delete=True,
                                         delete_mode="trash", source_kind="local")],
    }
    out = _roundtrip(data)
    assert out["mappings"] == data["mappings"]
    assert out["twoway_mappings"] == data["twoway_mappings"]


def test_marker_never_written():
    mappings, gex, extras = mk.split_loaded({"twoway_mappings": [_m("/b")]})
    text = json.dumps(mk.build_output(mappings, gex, extras))
    assert mk.MODE_KEY not in text


def test_unknown_top_level_and_mapping_keys_preserved():
    data = {"mappings": [_m("/a", future="1")],
            "twoway_mappings": [_m("/b", future="2")],
            "something_new": {"k": 1}}
    out = _roundtrip(data)
    assert out["something_new"] == {"k": 1}
    assert out["mappings"][0]["future"] == "1"
    assert out["twoway_mappings"][0]["future"] == "2"


def test_switch_upload_to_twoway_and_back():
    mappings, gex, extras = mk.split_loaded([_m("/a"), _m("/b")])
    mk.set_sync_mode(mappings[0], mk.MODE_TWOWAY)
    out = mk.build_output(mappings, gex, extras)
    assert [m["source"] for m in out["mappings"]] == ["/b"]
    assert [m["source"] for m in out["twoway_mappings"]] == ["/a"]

    # reload, switch back: it leaves twoway_mappings and returns to a plain list
    mappings, gex, extras = mk.split_loaded(out)
    mk.set_sync_mode(mappings[0] if mk.sync_mode(mappings[0]) == mk.MODE_TWOWAY
                     else mappings[1], mk.MODE_UPLOAD)
    back = mk.build_output(mappings, gex, extras)
    assert back == [_m("/b"), _m("/a")]


def test_old_list_format_without_twoway_stays_a_list():
    data = [_m("/a"), _m("/b")]
    assert _roundtrip(data) == data


def test_dialog_result_does_not_inherit_old_marker():
    old = _m("/a")
    mk.set_sync_mode(old, mk.MODE_TWOWAY)
    new = {"type": "folder", "source": "/a", "dest_parent": "/my-files/B"}
    mk.carry_unknown_keys(old, new)
    assert mk.sync_mode(new) == mk.MODE_UPLOAD


def test_engine_reads_what_the_editor_writes(tmp_path):
    mappings, gex, extras = mk.split_loaded([_m("/a"), _m("/b")])
    mk.set_sync_mode(mappings[1], mk.MODE_TWOWAY)
    path = tmp_path / "mappings.json"
    path.write_text(json.dumps(mk.build_output(mappings, gex, extras)))
    assert [m["source"] for m in proton_sync.load_twoway_mappings(str(path))] == ["/b"]
    upload, _gex = proton_sync.load_config(str(path))
    assert [m["source"] for m in upload] == ["/a"]
