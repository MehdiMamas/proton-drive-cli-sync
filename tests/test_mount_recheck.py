"""Mount re-check during a deletion pass.

A refused deletion is logged with the [delete-guard] tag and counted in
deletions_refused, which makes the pass end with code 5. The remote copies
stay put and the uploads continue.
"""

import proton_sync

REMOTE = "/my-files/Backups/Docs"


def test_mount_lost_mid_pass_stops_deletions(fake_drive, local_tree):
    folders = ("a", "b", "c")
    spec = {}
    for name in folders:
        spec["Docs/%s/old.txt" % name] = (b"old", 1_000_000_000)
    src = local_tree(spec)
    root = str(src / "Docs")
    # sync_folder remembers remote folders on the module. This test calls it
    # in-process; clear that set so a later in-process test does not skip
    # creating the same paths in a different fake Drive.
    proton_sync._REMOTE_KNOWN.clear()
    try:
        assert proton_sync.sync_folder(root, "/my-files/Backups", rename_ext=False)
        for name in folders:
            (src / "Docs" / name / "old.txt").unlink()
            local_tree.write("Docs/%s/new.txt" % name, b"new", 1_000_000_100)

        calls = []

        def guard():
            calls.append(1)
            return (True, "") if len(calls) == 1 else (False, "mount gone")

        opts = {"delete_guard": guard, "mount_lost": False}
        proton_sync._RUN.reset()
        complete = proton_sync.sync_folder(
            root, "/my-files/Backups", delete=True, rename_ext=False, delete_opts=opts)
        assert complete is False
        trashed = [n for n in folders if fake_drive.trashed(REMOTE + "/%s/old.txt" % n)]
        assert len(trashed) == 1
        assert opts["mount_lost"] is True
        assert proton_sync._RUN.deletions_refused == 1
        assert proton_sync._RUN.has_failures()
        for name in folders:   # uploads continue after the latch
            assert fake_drive.content(REMOTE + "/%s/new.txt" % name) == b"new"
    finally:
        proton_sync._REMOTE_KNOWN.clear()
        proton_sync._RUN.reset()


def _refuse(source_path, source_kind, verbose=False):
    return False, "mount gone"


def test_refusal_at_start_of_mapping_counts(fake_drive, local_tree, monkeypatch, capsys):
    src = local_tree({"Docs/a.txt": (b"a", 1_000_000_000)})
    monkeypatch.setattr(proton_sync, "_delete_guard_ok", _refuse)
    mapping = {"allow_delete": True, "source_kind": "local"}
    proton_sync._REMOTE_KNOWN.clear()
    proton_sync._RUN.reset()
    try:
        proton_sync.sync_folder_guarded(
            mapping, str(src / "Docs"), "/my-files/Backups", delete=True, rename_ext=False)
        assert "Deletions disabled for this mapping" in capsys.readouterr().out
        assert proton_sync._RUN.deletions_refused == 1
        assert proton_sync._RUN.has_failures()
    finally:
        proton_sync._REMOTE_KNOWN.clear()
        proton_sync._RUN.reset()


def test_refusal_at_start_of_subpath_counts(fake_drive, local_tree, monkeypatch, capsys):
    src = local_tree({"Docs/sub/a.txt": (b"a", 1_000_000_000)})
    monkeypatch.setattr(proton_sync, "_delete_guard_ok", _refuse)
    mapping = {"type": "folder", "source": str(src / "Docs"),
               "dest_parent": "/my-files/Backups",
               "allow_delete": True, "source_kind": "local"}
    proton_sync._REMOTE_KNOWN.clear()
    proton_sync._RUN.reset()
    try:
        proton_sync.sync_subpath(
            mapping, str(src / "Docs" / "sub"), delete=True, rename_ext=False)
        assert "Deletions disabled for this subpath" in capsys.readouterr().out
        assert proton_sync._RUN.deletions_refused == 1
        assert proton_sync._RUN.has_failures()
    finally:
        proton_sync._REMOTE_KNOWN.clear()
        proton_sync._RUN.reset()


def _editor_filters():
    import pathlib
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "proton_mapping_editor.py").read_text(encoding="utf-8")
    start = source.index("# --- editor output filter (no Tk) ---")
    end = source.index("# --- end editor output filter ---")
    namespace = {"json": __import__("json")}
    exec(source[start:end], namespace)
    return namespace["visible_editor_lines"]


def test_mid_pass_refusal_line_is_visible_in_the_editor():
    import gettext
    import pathlib
    show = _editor_filters()
    msgid = ("  ⚠  [delete-guard] Deletions disabled for the rest of this mapping, "
             "the mount check failed during the pass: {r}")
    locale_dir = pathlib.Path(__file__).resolve().parents[1] / "locale"
    for lang in ("en", "fr", "de", "es", "it", "pt"):
        tr = gettext.translation("proton-sync", str(locale_dir), languages=[lang],
                                 fallback=True)
        line = tr.gettext(msgid).format(r="mount gone") + "\n"
        if lang != "en":
            assert line.startswith("  ⚠  [delete-guard] ") and tr.gettext(msgid) != msgid, lang
        assert show([line]) == [line], lang
        assert show([line], errors_only=True) == [line], lang
