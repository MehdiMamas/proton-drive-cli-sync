"""Arrival-folder conflicts between upload mappings.

A mapping lands in dest_parent/basename(source) on Proton: its arrival
folder. Two mappings that share an arrival folder, or whose arrival folders
are nested, must never trash each other's files when deletions are
propagated. The engine keeps uploading them and holds back the deletions of
both mappings of each pair.
"""


def _trash_calls(fake_drive):
    return [c for c in fake_drive.calls() if c[:2] == ["filesystem", "trash"]]


def _mapping(source, dest, **extra):
    mapping = {"type": "folder", "source": str(source), "dest_parent": dest,
               "allow_delete": True, "source_kind": "local"}
    mapping.update(extra)
    return mapping


def test_same_arrival_folder_never_trashes_the_other(
        fake_drive, local_tree, write_mappings, engine):
    root = local_tree({"here/Photos/a.jpg": (b"AAAA", 1_000_000_000),
                       "nas/Photos/b.jpg": (b"BBBB", 1_000_000_000)})
    cfg = write_mappings([
        _mapping(root / "here" / "Photos", "/my-files/Backups"),
        _mapping(root / "nas" / "Photos", "/my-files/Backups"),
    ])
    assert engine(cfg).returncode == 0
    result = engine(cfg, "--delete")
    out = result.stdout + result.stderr
    assert _trash_calls(fake_drive) == [], out
    assert sorted(fake_drive.listing("/my-files/Backups/Photos")) == ["a.jpg", "b.jpg"]


def test_nested_arrival_folder_is_not_trashed_by_the_outer_mapping(
        fake_drive, local_tree, write_mappings, engine):
    root = local_tree({"here/Documents/a.txt": (b"AAAA", 1_000_000_000),
                       "nas/Invoices/b.txt": (b"BBBB", 1_000_000_000)})
    cfg = write_mappings([
        _mapping(root / "here" / "Documents", "/my-files/Backups"),
        _mapping(root / "nas" / "Invoices", "/my-files/Backups/Documents"),
    ])
    assert engine(cfg).returncode == 0
    result = engine(cfg, "--delete")
    out = result.stdout + result.stderr
    # Today the outer mapping trashes Invoices and the other one sends it
    # back at once: the final state looks fine, the trash calls do not.
    assert _trash_calls(fake_drive) == [], out


def _two_photos(local_tree):
    root = local_tree({"here/Photos/a.jpg": (b"AAAA", 1_000_000_000),
                       "nas/Photos/b.jpg": (b"BBBB", 1_000_000_000)})
    return root, [_mapping(root / "here" / "Photos", "/my-files/Backups"),
                  _mapping(root / "nas" / "Photos", "/my-files/Backups")]


def test_hold_is_logged_and_files_are_still_sent(
        fake_drive, local_tree, write_mappings, engine):
    root, maps = _two_photos(local_tree)
    result = engine(write_mappings(maps), "--delete")
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert out.count("[arrival-conflict]") == 2, out
    assert out.count("puts its content in the same Proton folder") == 2, out
    assert sorted(fake_drive.listing("/my-files/Backups/Photos")) == ["a.jpg", "b.jpg"]


def test_real_time_subpath_holds_deletions(
        fake_drive, local_tree, write_mappings, engine):
    root, maps = _two_photos(local_tree)
    cfg = write_mappings(maps)
    assert engine(cfg, "--delete").returncode == 0
    here = str(root / "here" / "Photos")
    result = engine(cfg, "--delete", "--ignore-cache", "--subpath", here,
                    "--mapping-source", here)
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert _trash_calls(fake_drive) == [], out
    assert "[arrival-conflict]" in out


def test_inner_mapping_never_trashes_the_outer_mapping_files(
        fake_drive, local_tree, write_mappings, engine):
    # The outer source has a subfolder named like the inner arrival folder:
    # both mappings upload into /my-files/Backups/Documents/Invoices. Holding
    # only the outer mapping let the inner one trash outer.txt for good.
    root = local_tree({"here/Documents/Invoices/outer.txt": (b"OUT", 1_000_000_000),
                       "nas/Invoices/inner.txt": (b"IN", 1_000_000_000)})
    cfg = write_mappings([
        _mapping(root / "here" / "Documents", "/my-files/Backups"),
        _mapping(root / "nas" / "Invoices", "/my-files/Backups/Documents"),
    ])
    assert engine(cfg).returncode == 0
    result = engine(cfg, "--delete")
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert _trash_calls(fake_drive) == [], out
    assert sorted(fake_drive.listing("/my-files/Backups/Documents/Invoices")) == [
        "inner.txt", "outer.txt"]
    assert out.count("[arrival-conflict]") == 2, out
    assert out.count("are nested, one inside the other") == 2, out


def test_no_conflict_deletes_as_before(
        fake_drive, local_tree, write_mappings, engine):
    root = local_tree({"here/Photos/a.jpg": (b"AAAA", 1_000_000_000),
                       "nas/Photos/b.jpg": (b"BBBB", 1_000_000_000)})
    cfg = write_mappings([
        _mapping(root / "here" / "Photos", "/my-files/Backups"),
        _mapping(root / "nas" / "Photos", "/my-files/Backups/NAS"),
    ])
    assert engine(cfg).returncode == 0
    (root / "here" / "Photos" / "a.jpg").unlink()
    result = engine(cfg, "--delete")
    out = result.stdout + result.stderr
    assert "[arrival-conflict]" not in out, out
    assert fake_drive.trashed("/my-files/Backups/Photos/a.jpg"), out


def test_reset_wipe_refused_for_a_shared_arrival_folder(
        fake_drive, local_tree, write_mappings, engine):
    root, maps = _two_photos(local_tree)
    cfg = write_mappings(maps)
    assert engine(cfg).returncode == 0
    here = str(root / "here" / "Photos")
    result = engine(cfg, "--reset-source", here, "--wipe-remote")
    out = result.stdout + result.stderr
    assert "Remote wipe REFUSED" in out, out
    assert _trash_calls(fake_drive) == [], out
    assert sorted(fake_drive.listing("/my-files/Backups/Photos")) == ["a.jpg", "b.jpg"]


def test_mappings_file_is_not_modified(
        fake_drive, local_tree, write_mappings, engine):
    root, maps = _two_photos(local_tree)
    cfg = write_mappings(maps)
    before = cfg.read_text(encoding="utf-8")
    assert engine(cfg, "--delete").returncode == 0
    assert cfg.read_text(encoding="utf-8") == before
