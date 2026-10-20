"""Renames and moves in two-way sync: applied as renames and moves on the
other side, never as a transfer plus a deletion."""

import os

import pytest

import remote_state
import syncdb

REMOTE = "/my-files/B"


@pytest.fixture
def engine(engine):
    class _Reconciling:
        def __call__(self, cfg, *args):
            return engine.reconcile(cfg, *args)
    return _Reconciling()


def _mapping(source):
    return {"type": "folder", "source": str(source), "dest_parent": REMOTE,
            "direction": "twoway", "allow_delete": True, "source_kind": "local"}


def _verb(calls, verb):
    return [c for c in calls if len(c) >= 2 and c[0] == "filesystem" and c[1] == verb]


def _norm(path):
    return remote_state.normalize(path)


def _rename_nodes(fake_drive, old, new):
    """What Proton does on a rename or move: same node ids, new path."""
    old, new = _norm(old), _norm(new)

    def mutate(state):
        remote_state.ensure_folders(state, new)
        nodes = state["nodes"]
        for path in sorted(nodes):
            if path == old or path.startswith(old + "/"):
                nodes[new + path[len(old):]] = nodes.pop(path)
    fake_drive._update(mutate)


def _synced(engine, local_tree, write_mappings, files):
    src = local_tree(files)
    cfg = write_mappings([_mapping(src / "Docs")])
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    return src, cfg


def _nodes(fake_drive):
    holder = {}

    def look(state):
        holder["nodes"] = {p: n for p, n in state["nodes"].items()
                           if not n.get("trashed")}
    fake_drive._update(look)
    return holder["nodes"]


def test_file_renamed_on_proton_is_renamed_here_without_download(
        fake_drive, local_tree, write_mappings, engine):
    src, cfg = _synced(engine, local_tree, write_mappings, {"Docs/a.txt": b"AAAA"})
    _rename_nodes(fake_drive, REMOTE + "/Docs/a.txt", REMOTE + "/Docs/b.txt")
    before = len(_verb(fake_drive.calls(), "download"))
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(os.listdir(src / "Docs")) == ["b.txt"]
    assert (src / "Docs" / "b.txt").read_bytes() == b"AAAA"
    assert len(_verb(fake_drive.calls(), "download")) == before


def test_folder_renamed_on_proton_renames_the_local_folder(
        fake_drive, local_tree, write_mappings, engine, isolated_home):
    src, cfg = _synced(engine, local_tree, write_mappings,
                       {"Docs/one/a.txt": b"AAAA", "Docs/one/deep/b.txt": b"BBBB"})
    _rename_nodes(fake_drive, REMOTE + "/Docs/one", REMOTE + "/Docs/uno")
    before = len(_verb(fake_drive.calls(), "download"))
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (src / "Docs" / "uno" / "a.txt").read_bytes() == b"AAAA"
    assert (src / "Docs" / "uno" / "deep" / "b.txt").read_bytes() == b"BBBB"
    assert not (src / "Docs" / "one").exists()
    assert len(_verb(fake_drive.calls(), "download")) == before
    db_path = syncdb.database_path(
        os.path.basename(str(cfg)), data_dir=str(isolated_home / ".proton-drive-sync"))
    with syncdb.SyncDB(db_path) as database:
        assert database.get(str(src / "Docs" / "uno" / "deep" / "b.txt"))
        assert database.get(str(src / "Docs" / "one" / "a.txt")) is None
        assert database.get_folder(str(src / "Docs" / "uno" / "deep"))


def test_file_moved_between_folders_moves_the_local_file(
        fake_drive, local_tree, write_mappings, engine):
    src, cfg = _synced(engine, local_tree, write_mappings,
                       {"Docs/one/a.txt": b"AAAA", "Docs/two/c.txt": b"CC"})
    _rename_nodes(fake_drive, REMOTE + "/Docs/one/a.txt", REMOTE + "/Docs/two/a.txt")
    before = len(_verb(fake_drive.calls(), "download"))
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (src / "Docs" / "two" / "a.txt").read_bytes() == b"AAAA"
    assert not (src / "Docs" / "one" / "a.txt").exists()
    assert len(_verb(fake_drive.calls(), "download")) == before


def test_file_moved_out_of_the_tree_goes_through_the_deletion_gates(
        fake_drive, local_tree, write_mappings, engine):
    src, cfg = _synced(engine, local_tree, write_mappings,
                       {"Docs/a.txt": b"AAAA", "Docs/keep.txt": b"KEEP"})
    _rename_nodes(fake_drive, REMOTE + "/Docs/a.txt", "/my-files/Elsewhere/a.txt")
    # Without --delete nothing is removed locally.
    assert engine(cfg).returncode == 0
    assert (src / "Docs" / "a.txt").exists()
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[held] " in result.stdout, result.stdout
    assert not (src / "Docs" / "a.txt").exists()
    assert (src / "Docs" / "keep.txt").exists()


def test_local_rename_is_a_remote_rename(fake_drive, local_tree, write_mappings, engine):
    src, cfg = _synced(engine, local_tree, write_mappings, {"Docs/a.txt": b"AAAA"})
    uploads = len(fake_drive.uploads())
    os.rename(src / "Docs" / "a.txt", src / "Docs" / "b.txt")
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = fake_drive.calls()
    assert [c[2:] for c in _verb(calls, "rename")] == [[REMOTE + "/Docs/a.txt", "b.txt"]]
    assert _verb(calls, "move") == [] and _verb(calls, "trash") == []
    assert len(fake_drive.uploads()) == uploads
    assert fake_drive.content(REMOTE + "/Docs/b.txt") == b"AAAA"
    assert fake_drive.content(REMOTE + "/Docs/a.txt") is None
    # Settled: another pass does nothing more.
    assert engine(cfg, "--delete").returncode == 0
    assert len(_verb(fake_drive.calls(), "rename")) == 1


def test_local_move_is_a_remote_move(fake_drive, local_tree, write_mappings, engine):
    src, cfg = _synced(engine, local_tree, write_mappings,
                       {"Docs/one/a.txt": b"AAAA", "Docs/two/c.txt": b"CC"})
    uploads = len(fake_drive.uploads())
    os.rename(src / "Docs" / "one" / "a.txt", src / "Docs" / "two" / "a.txt")
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = fake_drive.calls()
    assert [c[2:] for c in _verb(calls, "move")] == [
        [REMOTE + "/Docs/one/a.txt", REMOTE + "/Docs/two"]]
    assert _verb(calls, "rename") == [] and _verb(calls, "trash") == []
    assert len(fake_drive.uploads()) == uploads
    assert fake_drive.content(REMOTE + "/Docs/two/a.txt") == b"AAAA"


def test_local_move_and_rename_is_move_then_rename_without_upload(
        fake_drive, local_tree, write_mappings, engine):
    src, cfg = _synced(engine, local_tree, write_mappings,
                       {"Docs/one/a.txt": b"AAAA", "Docs/two/c.txt": b"CC"})
    uploads = len(fake_drive.uploads())
    start = len(fake_drive.calls())
    os.rename(src / "Docs" / "one" / "a.txt", src / "Docs" / "two" / "z.txt")
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = fake_drive.calls()[start:]
    verbs = [c[1] for c in calls if c[0] == "filesystem"
             and c[1] in ("move", "rename", "upload", "trash")]
    assert verbs == ["move", "rename"]
    assert [c[2:] for c in _verb(calls, "rename")] == [[REMOTE + "/Docs/two/a.txt", "z.txt"]]
    assert len(fake_drive.uploads()) == uploads
    assert fake_drive.content(REMOTE + "/Docs/two/z.txt") == b"AAAA"


def test_local_folder_rename_is_one_remote_rename(
        fake_drive, local_tree, write_mappings, engine, isolated_home):
    src, cfg = _synced(engine, local_tree, write_mappings,
                       {"Docs/one/a.txt": b"AAAA", "Docs/one/deep/b.txt": b"BBBB"})
    uploads = len(fake_drive.uploads())
    os.rename(src / "Docs" / "one", src / "Docs" / "uno")
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = fake_drive.calls()
    assert [c[2:] for c in _verb(calls, "rename")] == [[REMOTE + "/Docs/one", "uno"]]
    assert _verb(calls, "trash") == []
    assert len(fake_drive.uploads()) == uploads
    assert fake_drive.content(REMOTE + "/Docs/uno/deep/b.txt") == b"BBBB"
    assert not [p for p in _nodes(fake_drive) if p.startswith(_norm(REMOTE + "/Docs/one"))]


def test_rename_with_changed_content_is_not_a_rename(
        fake_drive, local_tree, write_mappings, engine):
    """A file renamed and edited here is a new file: the checksum differs."""
    src, cfg = _synced(engine, local_tree, write_mappings, {"Docs/a.txt": b"AAAA"})
    os.rename(src / "Docs" / "a.txt", src / "Docs" / "b.txt")
    (src / "Docs" / "b.txt").write_bytes(b"CHANGED")
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _verb(fake_drive.calls(), "rename") == []
    assert fake_drive.content(REMOTE + "/Docs/b.txt") == b"CHANGED"
