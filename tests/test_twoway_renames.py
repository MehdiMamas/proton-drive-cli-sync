"""Renames and moves in two-way sync, and the events trigger (#17 PR-2/PR-3)."""

import json
import os
import stat
import sys

import pytest

import remote_state
import syncdb
import twoway

REMOTE = "/my-files/B"


def _mapping(source, **extra):
    mapping = {"type": "folder", "source": str(source), "dest_parent": REMOTE}
    mapping.update(extra)
    return mapping


def _downloads(calls):
    return [c for c in calls
            if len(c) >= 2 and c[0] == "filesystem" and c[1] == "download"]


def _lists(calls):
    return [c[2] for c in calls
            if len(c) >= 3 and c[0] == "filesystem" and c[1] == "list"]


def _db(isolated_home, cfg):
    return syncdb.database_path(
        os.path.basename(str(cfg)),
        data_dir=str(isolated_home / ".proton-drive-sync"))


def _norm(path):
    return remote_state.normalize(path)


def _rename_nodes(fake_drive, old, new):
    """Move a node and everything below it, keeping node ids."""
    old, new = _norm(old), _norm(new)

    def mutate(state):
        nodes = state["nodes"]
        for path in sorted(nodes):
            if path == old or path.startswith(old + "/"):
                nodes[new + path[len(old):]] = nodes.pop(path)
    fake_drive._update(mutate)


def _synced(engine, local_tree, write_mappings, files, **extra):
    src = local_tree(files)
    cfg = write_mappings([], twoway_mappings=[_mapping(src / "Docs", **extra)])
    assert engine.reconcile(cfg).returncode == 0
    return src, cfg


def test_folder_renamed_on_proton_renames_the_local_folder(
        fake_drive, local_tree, write_mappings, engine, isolated_home):
    src, cfg = _synced(engine, local_tree, write_mappings,
                       {"Docs/one/a.txt": b"AAAA", "Docs/one/deep/b.txt": b"BBBB"})
    _rename_nodes(fake_drive, REMOTE + "/Docs/one", REMOTE + "/Docs/uno")
    before = len(_downloads(fake_drive.calls()))
    result = engine.reconcile(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (src / "Docs" / "uno" / "a.txt").read_bytes() == b"AAAA"
    assert (src / "Docs" / "uno" / "deep" / "b.txt").read_bytes() == b"BBBB"
    assert not (src / "Docs" / "one").exists()
    assert len(_downloads(fake_drive.calls())) == before
    with syncdb.SyncDB(_db(isolated_home, cfg)) as database:
        assert database.get(str(src / "Docs" / "uno" / "deep" / "b.txt"))
        assert database.get(str(src / "Docs" / "one" / "a.txt")) is None
        assert database.get_folder(str(src / "Docs" / "uno" / "deep"))


def test_file_moved_between_folders_moves_the_local_file(
        fake_drive, local_tree, write_mappings, engine):
    src, cfg = _synced(engine, local_tree, write_mappings,
                       {"Docs/x/a.txt": b"AAAA", "Docs/y/keep.txt": b"KEEP"})
    _rename_nodes(fake_drive, REMOTE + "/Docs/x/a.txt", REMOTE + "/Docs/y/a.txt")
    before = len(_downloads(fake_drive.calls()))
    result = engine.reconcile(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (src / "Docs" / "y" / "a.txt").read_bytes() == b"AAAA"
    assert not (src / "Docs" / "x" / "a.txt").exists()
    assert len(_downloads(fake_drive.calls())) == before


def test_file_moved_out_of_the_tree_goes_through_the_deletion_gates(
        fake_drive, local_tree, write_mappings, engine):
    src, cfg = _synced(engine, local_tree, write_mappings,
                       {"Docs/a.txt": b"AAAA", "Docs/keep.txt": b"KEEP"})
    _rename_nodes(fake_drive, REMOTE + "/Docs/a.txt", "/my-files/Elsewhere/a.txt")
    # Without --delete nothing is removed locally.
    assert engine.reconcile(cfg).returncode == 0
    assert (src / "Docs" / "a.txt").exists()
    result = engine.reconcile(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[held] " in result.stdout, result.stdout
    assert not (src / "Docs" / "a.txt").exists()
    assert (src / "Docs" / "keep.txt").exists()


def test_local_rename_is_sent_under_the_new_name(
        fake_drive, local_tree, write_mappings, engine):
    src, cfg = _synced(engine, local_tree, write_mappings,
                       {"Docs/a.txt": b"AAAA", "Docs/keep.txt": b"KEEP"},
                       allow_delete=True, delete_mode="trash",
                       source_kind="local")
    os.rename(src / "Docs" / "a.txt", src / "Docs" / "b.txt")
    result = engine.reconcile(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[renamed] " in result.stdout, result.stdout
    assert fake_drive.content(REMOTE + "/Docs/b.txt") == b"AAAA"
    assert fake_drive.trashed(REMOTE + "/Docs/a.txt")


def test_probe_output_is_parsed_into_events_and_a_cursor():
    text = "\n".join([
        json.dumps({"event": "moved", "node_id": "n1", "parent_id": "p2",
                    "old_parent_id": "p1", "name": "b.txt", "type": "file",
                    "sha1": "abc"}),
        "not json",
        json.dumps({"event": "bogus", "node_id": "n2"}),
        json.dumps({"event": "created", "node_id": "n3", "type": "folder"}),
        json.dumps({"cursor": "c42"}),
    ])
    events, cursor = twoway.parse_probe_output(text)
    assert cursor == "c42"
    assert [e.event for e in events] == ["moved", "created"]
    assert events[0] == twoway.ChangeEvent(
        event="moved", node_id="n1", parent_id="p2", old_parent_id="p1",
        name="b.txt", type="file", sha1="abc")
    assert events[1].type == "folder"


def _probe(tmp_path, lines, code=0):
    """A probe script that prints `lines` (JSON objects) and records its argv."""
    script = tmp_path / "probe.py"
    out = tmp_path / "probe_out.jsonl"
    log = tmp_path / "probe_args.log"
    script.write_text(
        "import sys\n"
        "open({log!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
        "sys.stdout.write(open({out!r}).read())\n"
        "sys.exit({code})\n".format(log=str(log), out=str(out), code=code),
        encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    def write(new_lines):
        out.write_text("".join(json.dumps(x) + "\n" for x in new_lines),
                       encoding="utf-8")
    write(lines)
    write.cmd = "{py} {script}".format(py=sys.executable, script=script)
    write.args = lambda: log.read_text().splitlines() if log.exists() else []
    return write


def _events_run(engine, cfg, probe, *args):
    engine.update_settings(twoway_trigger="events", twoway_probe_cmd=probe.cmd)
    return engine(cfg, *args)


def _folder_ids(isolated_home, cfg):
    with syncdb.SyncDB(_db(isolated_home, cfg)) as database:
        return {r["local_path"]: r["remote_node_id"] for r in database.folders()}


def test_events_trigger_first_run_lists_everything_and_stores_the_cursor(
        fake_drive, local_tree, write_mappings, engine, isolated_home, tmp_path):
    src = local_tree({"Docs/a.txt": b"AAAA"})
    cfg = write_mappings([], twoway_mappings=[_mapping(src / "Docs")])
    probe = _probe(tmp_path, [{"cursor": "c1"}])
    result = _events_run(engine, cfg, probe)
    assert result.returncode == 0, result.stdout + result.stderr
    assert fake_drive.content(REMOTE + "/Docs/a.txt") == b"AAAA"
    with syncdb.SyncDB(_db(isolated_home, cfg)) as database:
        assert database.get_meta("twoway_cursor:" + str(src / "Docs")) == "c1"
    # Second run hands the stored cursor back to the probe.
    probe([{"cursor": "c2"}])
    assert _events_run(engine, cfg, probe).returncode == 0
    assert probe.args()[-1] == "--cursor c1"
    with syncdb.SyncDB(_db(isolated_home, cfg)) as database:
        assert database.get_meta("twoway_cursor:" + str(src / "Docs")) == "c2"


def test_events_trigger_applies_a_reported_remote_rename(
        fake_drive, local_tree, write_mappings, engine, isolated_home, tmp_path):
    src = local_tree({"Docs/a.txt": b"AAAA"})
    cfg = write_mappings([], twoway_mappings=[_mapping(src / "Docs")])
    probe = _probe(tmp_path, [{"cursor": "c1"}])
    assert _events_run(engine, cfg, probe).returncode == 0
    root_id = _folder_ids(isolated_home, cfg)[str(src / "Docs")]
    with syncdb.SyncDB(_db(isolated_home, cfg)) as database:
        file_id = database.get(str(src / "Docs" / "a.txt"))["remote_node_id"]
    assert root_id and file_id
    _rename_nodes(fake_drive, REMOTE + "/Docs/a.txt", REMOTE + "/Docs/b.txt")
    probe([{"event": "moved", "node_id": file_id, "parent_id": root_id,
            "old_parent_id": root_id, "name": "b.txt", "type": "file"},
           {"cursor": "c2"}])
    before = len(_downloads(fake_drive.calls()))
    result = _events_run(engine, cfg, probe, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (src / "Docs" / "b.txt").read_bytes() == b"AAAA"
    assert not (src / "Docs" / "a.txt").exists()
    assert len(_downloads(fake_drive.calls())) == before


def test_events_trigger_reconciles_only_the_reported_folders(
        fake_drive, local_tree, write_mappings, engine, isolated_home, tmp_path):
    src = local_tree({"Docs/one/a.txt": b"AAAA", "Docs/two/b.txt": b"BBBB"})
    cfg = write_mappings([], twoway_mappings=[_mapping(src / "Docs")])
    probe = _probe(tmp_path, [{"cursor": "c1"}])
    assert _events_run(engine, cfg, probe).returncode == 0
    ids = _folder_ids(isolated_home, cfg)
    one = ids[str(src / "Docs" / "one")]
    assert one
    fake_drive.seed_file(REMOTE + "/Docs/one/new.txt", b"NEW")
    fake_drive.seed_file(REMOTE + "/Docs/two/other.txt", b"OTHER")
    probe([{"event": "created", "node_id": "n-new", "parent_id": one,
            "name": "new.txt", "type": "file"}, {"cursor": "c2"}])
    mark = len(fake_drive.calls())
    result = _events_run(engine, cfg, probe)
    assert result.returncode == 0, result.stdout + result.stderr
    listed = _lists(fake_drive.calls()[mark:])
    inside = [p for p in listed if p.startswith(_norm(REMOTE + "/Docs"))]
    assert inside == [_norm(REMOTE + "/Docs/one")], listed
    assert (src / "Docs" / "one" / "new.txt").read_bytes() == b"NEW"
    assert not (src / "Docs" / "two" / "other.txt").exists()


def test_events_trigger_skips_the_mapping_when_the_probe_fails(
        fake_drive, local_tree, write_mappings, engine, isolated_home, tmp_path):
    src = local_tree({"Docs/a.txt": b"AAAA"})
    cfg = write_mappings([], twoway_mappings=[_mapping(src / "Docs")])
    probe = _probe(tmp_path, [], code=3)
    result = _events_run(engine, cfg, probe)
    assert "[probe-failed]" in result.stdout, result.stdout + result.stderr
    assert fake_drive.uploads() == []
    assert (src / "Docs" / "a.txt").read_bytes() == b"AAAA"
    with syncdb.SyncDB(_db(isolated_home, cfg)) as database:
        assert database.get_meta("twoway_cursor:" + str(src / "Docs")) is None


def test_events_trigger_without_a_probe_command_is_skipped(
        fake_drive, local_tree, write_mappings, engine):
    src = local_tree({"Docs/a.txt": b"AAAA"})
    cfg = write_mappings([], twoway_mappings=[_mapping(src / "Docs")])
    engine.update_settings(twoway_trigger="events", twoway_probe_cmd="")
    result = engine(cfg)
    assert "skipped" in result.stdout.lower(), result.stdout
    assert fake_drive.uploads() == []
