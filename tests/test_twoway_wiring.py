"""main() runs the sync_mappings entries: validation, overlap rules, trigger."""

import json

import pytest

import mapping_keys


def _m(source, dest, **extra):
    m = {"type": "folder", "source": str(source), "dest_parent": dest}
    m.update(extra)
    return m


def _tw(source, dest, **extra):
    return _m(source, dest, direction="twoway", **extra)


def _calls_with(calls, verb):
    return [c for c in calls if len(c) >= 2 and c[0] == "filesystem" and c[1] == verb]


def _write(tmp_path, upload, sync):
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"mappings": upload, "sync_mappings": sync}),
                    encoding="utf-8")
    return path


# --- the pure check -------------------------------------------------------

@pytest.mark.parametrize("a,b,reason", [
    ("/x/Docs", "/x/Docs", "local-same"),
    ("/x/Docs", "/x/Docs/", "local-same"),
    ("/x", "/x/Docs", "local-parent"),
    ("/x/Docs/sub", "/x/Docs", "local-child"),
])
def test_local_overlap_reasons(a, b, reason):
    hit = mapping_keys.sync_mapping_conflicts([_tw(a, "/d1")], [_m(b, "/d2")])
    assert hit[0][0] == reason
    both = mapping_keys.sync_mapping_conflicts([_tw(a, "/d1"), _tw(b, "/d2")])
    assert set(both) == {0, 1}


def test_no_overlap_on_segment_boundary_or_between_upload_mappings():
    assert mapping_keys.sync_mapping_conflicts(
        [_tw("/x/Doc", "/d1")], [_m("/x/Documents", "/d2")]) == {}
    # upload mappings may overlap each other: only two-way ones are checked
    assert mapping_keys.sync_mapping_conflicts([], [_m("/x", "/d"), _m("/x/y", "/e")]) == {}


def test_arrival_conflict_reuses_the_arrival_rule():
    hit = mapping_keys.sync_mapping_conflicts(
        [_tw("/a/Docs", "/Proton")], [_m("/b/Docs", "/Proton")])
    assert hit[0][0] == "arrival-same"
    hit = mapping_keys.sync_mapping_conflicts(
        [_tw("/a/Docs", "/Proton")], [_m("/b/sub", "/Proton/Docs")])
    assert hit[0][0] == "arrival-contains"


# --- through main() -------------------------------------------------------

def test_unknown_direction_is_skipped_with_one_line_and_never_uploaded(
        fake_drive, local_tree, engine, tmp_path):
    src = local_tree({"Dl/a.txt": (b"AAAA", 1_000_000_000)})
    cfg = _write(tmp_path, [], [_m(src / "Dl", "/my-files/Dl", direction="download")])
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [l for l in result.stdout.splitlines() if "unknown direction" in l]
    assert len(lines) == 1 and "'download'" in lines[0]
    assert fake_drive.uploads() == []
    assert _calls_with(fake_drive.calls(), "upload") == []


def test_unknown_type_is_skipped_with_one_line(fake_drive, local_tree, engine, tmp_path):
    src = local_tree({"T/a.txt": (b"AAAA", 1_000_000_000)})
    cfg = _write(tmp_path, [], [_tw(src / "T", "/my-files/T", type="album")])
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len([l for l in result.stdout.splitlines() if "unknown type" in l]) == 1
    assert fake_drive.uploads() == []


@pytest.mark.parametrize("other_rel", ["Two", "Two/sub", ""], ids=["same", "child", "parent"])
@pytest.mark.parametrize("other_is_twoway", [False, True], ids=["upload", "twoway"])
def test_local_overlap_blocks_the_twoway_mapping(
        fake_drive, local_tree, engine, tmp_path, other_rel, other_is_twoway):
    src = local_tree({"Two/sub/a.txt": (b"AAAA", 1_000_000_000)})
    mine = _tw(src / "Two", "/my-files/Mine")
    other_path = (src / other_rel) if other_rel else src
    if other_is_twoway:
        cfg = _write(tmp_path, [], [mine, _tw(other_path, "/my-files/Other")])
    else:
        cfg = _write(tmp_path, [_m(other_path, "/my-files/Other")], [mine])
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Two-way mapping not run" in result.stdout
    assert fake_drive.content("/my-files/Mine/Two/sub/a.txt") is None


def test_arrival_conflict_blocks_the_twoway_mapping(
        fake_drive, local_tree, engine, tmp_path):
    src = local_tree({"a/Docs/x.txt": (b"XXXX", 1_000_000_000),
                      "b/Docs/y.txt": (b"YYYY", 1_000_000_000)})
    cfg = _write(tmp_path, [_m(src / "b" / "Docs", "/my-files/Shared")],
                 [_tw(src / "a" / "Docs", "/my-files/Shared")])
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    blocked = [l for l in result.stdout.splitlines() if "Two-way mapping not run" in l]
    assert len(blocked) == 1 and "same Proton folder" in blocked[0]
    assert fake_drive.content("/my-files/Shared/Docs/x.txt") is None
    assert fake_drive.content("/my-files/Shared/Docs/y.txt") == b"YYYY"  # upload unchanged


def test_trigger_none_lists_the_whole_remote_and_runs(
        fake_drive, local_tree, engine, tmp_path):
    src = local_tree({"Two/a.txt": (b"AAAA", 1_000_000_000)})
    fake_drive.seed_file("/my-files/TW/Two/web.txt", b"WEB")
    cfg = _write(tmp_path, [], [_tw(src / "Two", "/my-files/TW")])
    result = engine(cfg)  # default trigger: none
    assert result.returncode == 0, result.stdout + result.stderr
    lists = [c for c in _calls_with(fake_drive.calls(), "list")]
    assert any("/my-files/TW/Two" in c for c in lists)
    assert fake_drive.content("/my-files/TW/Two/a.txt") == b"AAAA"
    assert (src / "Two" / "web.txt").read_bytes() == b"WEB"


def test_unknown_trigger_name_falls_back_to_full_listing(
        fake_drive, local_tree, engine, tmp_path):
    src = local_tree({"Two/a.txt": (b"AAAA", 1_000_000_000)})
    engine.update_settings(twoway_trigger="events")
    cfg = _write(tmp_path, [], [_tw(src / "Two", "/my-files/TW")])
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "unknown" in result.stdout
    assert fake_drive.content("/my-files/TW/Two/a.txt") == b"AAAA"


def test_valid_mapping_runs_next_to_an_upload_mapping(
        fake_drive, local_tree, engine, tmp_path):
    src = local_tree({"Two/a.txt": (b"AAAA", 1_000_000_000),
                      "One/b.txt": (b"BBBB", 1_000_000_000)})
    cfg = _write(tmp_path, [_m(src / "One", "/my-files/OneWay")],
                 [_tw(src / "Two", "/my-files/TwoWay")])
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert fake_drive.content("/my-files/OneWay/One/b.txt") == b"BBBB"
    assert fake_drive.content("/my-files/TwoWay/Two/a.txt") == b"AAAA"
