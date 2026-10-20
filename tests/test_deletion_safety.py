"""Deletion safety: excluded_remote and the mass-deletion guard.

excluded_remote: absent means prune; keep is opt-in for this mapping only.
A remote name is kept only when the mapping says "keep", the name matches
that mapping's own exclusions, and it does not match a global exclusion.

Mass-deletion guard: off by default, so a large deletion still trashes. A
refusal (guard on, both thresholds crossed) leaves the bytes in place and is
counted in deletions_refused, so the pass ends with code 5.
"""

import json

from mapping_keys import carry_unknown_keys

REMOTE = "/my-files/Backups/Docs"


def _mapping(source, **extra):
    mapping = {
        "type": "folder",
        "source": str(source),
        "dest_parent": "/my-files/Backups",
        "allow_delete": True,
        "source_kind": "local",
    }
    mapping.update(extra)
    return mapping


def _exclude(name):
    return {"names": [name], "patterns": []}


def _upload_secret(local_tree, write_mappings, engine, **extra):
    src = local_tree({"Docs/secret.txt": (b"hide", 1_000_000_000)})
    assert engine(write_mappings([_mapping(src / "Docs", **extra)])).returncode == 0
    return src


def test_absent_excluded_remote_prunes(
        fake_drive, local_tree, write_mappings, engine):
    src = _upload_secret(local_tree, write_mappings, engine)
    cfg = write_mappings([_mapping(
        src / "Docs", exclusions=_exclude("secret.txt"))])
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert fake_drive.trashed(REMOTE + "/secret.txt")


def test_excluded_remote_prune_restores_old_behavior(
        fake_drive, local_tree, write_mappings, engine):
    src = _upload_secret(local_tree, write_mappings, engine)
    cfg = write_mappings([_mapping(
        src / "Docs", excluded_remote="prune", exclusions=_exclude("secret.txt"))])
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert fake_drive.trashed(REMOTE + "/secret.txt")


def test_keep_preserves_mapping_only_exclusion(
        fake_drive, local_tree, write_mappings, engine):
    src = _upload_secret(local_tree, write_mappings, engine)
    cfg = write_mappings(
        [_mapping(src / "Docs", excluded_remote="keep",
                  exclusions=_exclude("secret.txt"))],
        exclusions=_exclude("other.txt"))
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not fake_drive.trashed(REMOTE + "/secret.txt")


def test_unchecking_keep_prunes_on_next_full_pass(
        fake_drive, local_tree, write_mappings, engine):
    src = _upload_secret(local_tree, write_mappings, engine)
    keep = write_mappings([_mapping(src / "Docs", excluded_remote="keep",
                                    exclusions=_exclude("secret.txt"))])
    assert engine(keep, "--delete").returncode == 0
    assert not fake_drive.trashed(REMOTE + "/secret.txt")
    prune = write_mappings([_mapping(src / "Docs", exclusions=_exclude("secret.txt"))])
    result = engine(prune, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert fake_drive.trashed(REMOTE + "/secret.txt")


def test_global_only_exclusion_trashed_even_when_keep(
        fake_drive, local_tree, write_mappings, engine):
    src = _upload_secret(local_tree, write_mappings, engine)
    cfg = write_mappings(
        [_mapping(src / "Docs", excluded_remote="keep")],
        exclusions=_exclude("secret.txt"))
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert fake_drive.trashed(REMOTE + "/secret.txt")


def test_name_in_mapping_and_global_exclusions_is_trashed(
        fake_drive, local_tree, write_mappings, engine):
    src = _upload_secret(local_tree, write_mappings, engine)
    cfg = write_mappings(
        [_mapping(src / "Docs", excluded_remote="keep",
                  exclusions=_exclude("secret.txt"))],
        exclusions=_exclude("secret.txt"))
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert fake_drive.trashed(REMOTE + "/secret.txt")


def test_remote_only_item_still_trashed_in_mirror_mode(
        fake_drive, local_tree, write_mappings, engine):
    src = local_tree({"Docs/keep.txt": (b"keep", 1_000_000_000)})
    fake_drive.seed_file(REMOTE + "/gone.txt", b"old")
    cfg = write_mappings([_mapping(src / "Docs", exclusions=_exclude("secret.txt"))])
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert fake_drive.trashed(REMOTE + "/gone.txt")
    assert not fake_drive.trashed(REMOTE + "/keep.txt")


def test_unknown_excluded_remote_value_prunes(
        fake_drive, local_tree, write_mappings, engine):
    src = _upload_secret(local_tree, write_mappings, engine)
    cfg = write_mappings([_mapping(
        src / "Docs", excluded_remote="bogus", exclusions=_exclude("secret.txt"))])
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "bogus" in result.stdout
    assert fake_drive.trashed(REMOTE + "/secret.txt")


def test_subpath_respects_excluded_remote(fake_drive, local_tree, write_mappings, engine):
    src = _upload_secret(local_tree, write_mappings, engine)
    docs = str(src / "Docs")
    kept = write_mappings([_mapping(
        src / "Docs", excluded_remote="keep", exclusions=_exclude("secret.txt"))])
    kept_run = engine(kept, "--delete", "--ignore-cache", "--subpath", docs,
                      "--mapping-source", docs)
    assert kept_run.returncode == 0, kept_run.stdout + kept_run.stderr
    assert not fake_drive.trashed(REMOTE + "/secret.txt")
    pruned = write_mappings([_mapping(
        src / "Docs", exclusions=_exclude("secret.txt"))])
    pruned_run = engine(pruned, "--delete", "--ignore-cache", "--subpath", docs,
                        "--mapping-source", docs)
    assert pruned_run.returncode == 0, pruned_run.stdout + pruned_run.stderr
    assert fake_drive.trashed(REMOTE + "/secret.txt")


def test_listing_failure_never_deletes(fake_drive, local_tree, write_mappings, engine):
    src = local_tree({"Docs/a.txt": (b"a", 1_000_000_000)})
    fake_drive.seed_file(REMOTE + "/orphan.txt", b"old")
    fake_drive.add_fault(cmd="list", match=REMOTE)
    result = engine(write_mappings([_mapping(src / "Docs")]), "--delete")
    # The failed listing is counted (folders_listing_failed): code 5.
    assert result.returncode == 5, result.stdout + result.stderr
    assert not fake_drive.trashed(REMOTE + "/orphan.txt")


def test_delete_opts_keep_the_mount_recheck(tmp_path):
    """excluded_remote rides in the same options as the mount re-check."""
    import proton_sync
    opts = proton_sync.build_delete_opts(
        _mapping(tmp_path, excluded_remote="keep", exclusions=_exclude("secret.txt")),
        str(tmp_path))
    assert callable(opts["delete_guard"])
    assert opts["mount_lost"] is False
    assert opts["excluded_remote"] == "keep"
    assert opts["mapping_exclusions"].is_excluded("secret.txt")
    assert not opts["global_exclusions"].is_excluded("secret.txt")


def test_mappings_roundtrip_preserves_unknown_keys():
    old = {
        "type": "folder", "source": "/s", "dest_parent": "/d",
        "allow_delete": True, "delete_mode": "trash", "source_kind": "local",
        "excluded_remote": "keep", "future_key": {"a": 1},
    }
    # The dialog rebuilt the mapping with allow_delete switched off.
    new = {"type": "folder", "source": "/s", "dest_parent": "/d"}
    saved = json.loads(json.dumps(carry_unknown_keys(old, dict(new))))
    assert "excluded_remote" not in saved
    assert saved["future_key"] == {"a": 1}
    for key in ("allow_delete", "delete_mode", "source_kind"):
        assert key not in saved
    assert carry_unknown_keys(None, {"x": 1}) == {"x": 1}
    # A key the dialog already wrote is left alone.
    assert carry_unknown_keys({"future_key": 1}, {"future_key": 2}) == {"future_key": 2}


def test_unchecked_box_drops_excluded_remote_after_carry():
    """The dialog copies unknown keys, then sets or pops excluded_remote."""
    old = {"excluded_remote": "keep", "future_key": 1}
    new = {"type": "folder", "source": "/s", "dest_parent": "/d"}
    carry_unknown_keys(old, new)
    checked = False
    if checked:
        new["excluded_remote"] = "keep"
    else:
        new.pop("excluded_remote", None)
    assert "excluded_remote" not in new
    assert new["future_key"] == 1

    again = {"type": "folder"}
    carry_unknown_keys({"excluded_remote": "prune", "future_key": 1}, again)
    again["excluded_remote"] = "keep"
    assert again["excluded_remote"] == "keep"
    assert again["future_key"] == 1


def _run_result(result):
    line = [x for x in result.stdout.splitlines() if x.startswith("[run-result] ")][-1]
    return json.loads(line[len("[run-result] "):])


def _many(count):
    return {"Docs/f%02d.txt" % i: (b"data%d" % i, 1_000_000_000) for i in range(count)}


def _emptied(local_tree, write_mappings, engine, count, remove, **extra):
    src = local_tree(_many(count))
    cfg = write_mappings([_mapping(src / "Docs", **extra)])
    assert engine(cfg).returncode == 0
    for i in range(remove):
        (src / "Docs" / ("f%02d.txt" % i)).unlink()
    return cfg


def _trashed_count(fake_drive, count):
    return sum(1 for i in range(count) if fake_drive.trashed(REMOTE + "/f%02d.txt" % i))


def _editor_lines():
    import json
    import pathlib
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "proton_mapping_editor.py").read_text(encoding="utf-8")
    start = source.index("# --- editor output filter (no Tk) ---")
    end = source.index("# --- end editor output filter ---")
    namespace = {"json": json}
    exec(source[start:end], namespace)
    return namespace["visible_editor_lines"]


def test_guard_off_by_default_still_trashes(fake_drive, local_tree, write_mappings, engine):
    cfg = _emptied(local_tree, write_mappings, engine, 30, 30)
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[delete-guard]" not in result.stdout
    assert _trashed_count(fake_drive, 30) == 30


def test_guard_on_refuses_twenty_and_half(fake_drive, local_tree, write_mappings, engine):
    engine.update_settings(mass_delete_guard=True)
    cfg = _emptied(local_tree, write_mappings, engine, 30, 30)
    result = engine(cfg, "--delete")
    assert result.returncode == 5, result.stdout + result.stderr
    assert "[delete-guard]" in result.stdout
    assert "refusing to trash 30 of 30" in result.stdout
    # The line names the way out in the window, not a command-line flag.
    assert "“Allow this run”" in result.stdout
    refusal = [line + "\n" for line in result.stdout.splitlines()
               if "refusing to trash" in line]
    show = _editor_lines()
    assert show(refusal) == refusal
    assert show(refusal, errors_only=True) == refusal
    assert _run_result(result)["deletions_refused"] == 1
    assert _trashed_count(fake_drive, 30) == 0
    # Not marked reconciled: the next pass looks again and refuses again.
    again = engine(cfg, "--delete")
    assert again.returncode == 5, again.stdout + again.stderr
    assert "refusing to trash 30 of 30" in again.stdout
    assert _trashed_count(fake_drive, 30) == 0


def test_guard_on_below_threshold_trashes(fake_drive, local_tree, write_mappings, engine):
    engine.update_settings(mass_delete_guard=True)
    cfg = _emptied(local_tree, write_mappings, engine, 30, 3)
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[delete-guard]" not in result.stdout
    assert _trashed_count(fake_drive, 30) == 3


def test_allow_mass_delete_overrides_enabled_guard(
        fake_drive, local_tree, write_mappings, engine):
    engine.update_settings(mass_delete_guard=True)
    cfg = _emptied(local_tree, write_mappings, engine, 30, 30)
    result = engine(cfg, "--delete", "--allow-mass-delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[delete-guard]" not in result.stdout
    assert _trashed_count(fake_drive, 30) == 30


def test_per_mapping_threshold_keys_are_ignored(
        fake_drive, local_tree, write_mappings, engine):
    """Thresholds are global only: keys left in an old mapping change nothing."""
    engine.update_settings(mass_delete_guard=True)
    cfg = _emptied(
        local_tree, write_mappings, engine, 30, 3,
        max_delete_min=2, max_delete_ratio=0.05)
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[delete-guard]" not in result.stdout
    assert _trashed_count(fake_drive, 30) == 3


def _photos(local_tree, write_mappings, engine, count=200):
    files = {"Docs/a.txt": (b"a", 1_000_000_000)}
    files.update({"Docs/Photos/p%03d.jpg" % i: (b"p%d" % i, 1_000_000_000)
                  for i in range(count)})
    src = local_tree(files)
    cfg = write_mappings([_mapping(src / "Docs")])
    assert engine(cfg).returncode == 0
    for i in range(count):
        (src / "Docs" / "Photos" / ("p%03d.jpg" % i)).unlink()
    (src / "Docs" / "Photos").rmdir()
    return cfg


def _photos_trashed(fake_drive, count=200):
    return (fake_drive.trashed(REMOTE + "/Photos")
            or any(fake_drive.trashed(REMOTE + "/Photos/p%03d.jpg" % i)
                   for i in range(count)))


def test_deleted_folder_counts_with_its_contents(
        fake_drive, local_tree, write_mappings, engine):
    """Docs/Photos (200 files) deleted locally weighs 201 of 202, not 1 of 2."""
    engine.update_settings(mass_delete_guard=True)
    cfg = _photos(local_tree, write_mappings, engine)
    result = engine(cfg, "--delete")
    assert result.returncode == 5, result.stdout + result.stderr
    assert "[delete-guard]" in result.stdout
    assert "refusing to trash 201 of 202" in result.stdout
    assert "@@DELETE-GUARD\t201\t202\t" + REMOTE + "\n" in result.stdout
    assert not _photos_trashed(fake_drive)
    assert not fake_drive.trashed(REMOTE + "/a.txt")


def test_deleted_folder_trashed_when_guard_off(
        fake_drive, local_tree, write_mappings, engine):
    cfg = _photos(local_tree, write_mappings, engine)
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert fake_drive.trashed(REMOTE + "/Photos")


def test_unmeasured_orphan_folder_is_refused(
        fake_drive, local_tree, write_mappings, engine):
    engine.update_settings(mass_delete_guard=True, max_delete_min=0)
    cfg = _photos(local_tree, write_mappings, engine, count=3)
    fake_drive.add_fault(cmd="list", match=REMOTE + "/Photos")
    result = engine(cfg, "--delete")
    assert result.returncode == 5, result.stdout + result.stderr
    assert "could not be measured" in result.stdout
    assert not _photos_trashed(fake_drive, 3)


def test_allow_mass_delete_in_lifts_only_the_named_folder(
        fake_drive, local_tree, write_mappings, engine):
    engine.update_settings(mass_delete_guard=True)
    files = {}
    for sub in ("A", "B"):
        files.update({"Docs/%s/f%02d.txt" % (sub, i): (b"%s%d" % (sub.encode(), i),
                                                       1_000_000_000)
                      for i in range(30)})
    src = local_tree(files)
    cfg = write_mappings([_mapping(src / "Docs")])
    assert engine(cfg).returncode == 0
    for sub in ("A", "B"):
        for i in range(30):
            (src / "Docs" / sub / ("f%02d.txt" % i)).unlink()

    refused = engine(cfg, "--delete")
    assert refused.returncode == 5, refused.stdout + refused.stderr
    folders = sorted(line.split("\t")[3] for line in refused.stdout.splitlines()
                     if line.startswith("@@DELETE-GUARD\t"))
    assert folders == [REMOTE + "/A", REMOTE + "/B"]

    result = engine(cfg, "--delete", "--allow-mass-delete-in", REMOTE + "/A/")
    assert result.returncode == 5, result.stdout + result.stderr
    assert all(fake_drive.trashed(REMOTE + "/A/f%02d.txt" % i) for i in range(30))
    assert not any(fake_drive.trashed(REMOTE + "/B/f%02d.txt" % i) for i in range(30))
    assert "@@DELETE-GUARD\t30\t30\t" + REMOTE + "/B\n" in result.stdout
    assert "@@DELETE-GUARD\t30\t30\t" + REMOTE + "/A\n" not in result.stdout


def test_bad_config_values_fall_back(fake_drive, local_tree, write_mappings, engine):
    import config
    assert config.DEFAULTS["mass_delete_guard"] is False
    assert config.mass_delete_guard() is False
    assert config.max_delete_min() == 20
    assert config.max_delete_ratio() == 0.5
    config._put("mass_delete_guard", "no")
    config._put("max_delete_min", "lots")
    config._put("max_delete_ratio", 2)
    assert config.mass_delete_guard() is False
    assert config.max_delete_min() == 20
    assert config.max_delete_ratio() == 0.5
    config._put("max_delete_min", -3)
    config._put("max_delete_ratio", -0.2)
    assert config.max_delete_min() == 20
    assert config.max_delete_ratio() == 0.5

    # The engine process reads its own settings file. Garbage there still
    # refuses the 20-and-half case, using the defaults.
    engine.update_settings(
        mass_delete_guard=True, max_delete_min="nope", max_delete_ratio=9)
    cfg = _emptied(local_tree, write_mappings, engine, 30, 21)
    result = engine(cfg, "--delete")
    assert result.returncode == 5, result.stdout + result.stderr
    assert "refusing to trash 21 of 30" in result.stdout
    assert _trashed_count(fake_drive, 30) == 0


def _editor_function(name):
    import ast
    import pathlib
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "proton_mapping_editor.py").read_text(encoding="utf-8")
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = {}
    exec(ast.get_source_segment(source, node), namespace)
    return namespace[name]


def test_editor_reruns_only_the_refused_folder(
        fake_drive, local_tree, write_mappings, engine):
    """The editor reads the engine's @@DELETE-GUARD line and reruns with
    --allow-mass-delete-in for that folder."""
    engine.update_settings(mass_delete_guard=True)
    cfg = _emptied(local_tree, write_mappings, engine, 30, 21)
    result = engine(cfg, "--delete")
    assert result.returncode == 5, result.stdout + result.stderr
    parse = _editor_function("_parse_delete_guard_line")
    lines = [x for x in result.stdout.splitlines(keepends=True)
             if x.startswith("@@DELETE-GUARD")]
    assert [parse(x) for x in lines] == [(REMOTE, 21, 30)]
    assert parse("@@DELETE-GUARD\t3\t\t/X\n") == ("/X", 3, None)
    assert parse("@@DELETE-GUARD\tmany\t1\t/X\n") is None
    assert parse("@@DELETE-GUARD\t3\t1\n") is None

    rerun = engine(cfg, "--delete", "--allow-mass-delete-in", REMOTE)
    assert rerun.returncode == 0, rerun.stdout + rerun.stderr
    assert "[delete-guard]" not in rerun.stdout
    assert _trashed_count(fake_drive, 30) == 21


def test_threshold_setters_accept_a_comma_and_refuse_bad_values():
    import config
    assert config.parse_ratio("0,5") == 0.5
    assert config.parse_ratio(" 0.25 ") == 0.25
    assert config.parse_ratio("1") == 1.0
    for bad in ("abc", "", "1,5", "-0.1", 2, True, None):
        assert config.parse_ratio(bad) is None, bad
    assert config.parse_min(" 30 ") == 30
    for bad in ("2.5", "-1", "lots", "", True, None):
        assert config.parse_min(bad) is None, bad

    assert config.set_max_delete_ratio("0,3") is True
    assert config.max_delete_ratio() == 0.3
    assert config.set_max_delete_min("12") is True
    assert config.max_delete_min() == 12
    # A refused value writes nothing: the previous one stays.
    assert config.set_max_delete_ratio("half") is False
    assert config.set_max_delete_min("-4") is False
    assert config.max_delete_ratio() == 0.3
    assert config.max_delete_min() == 12


def test_configuration_takes_the_share_as_a_whole_percentage():
    """The window shows and takes a whole percentage; settings.json keeps the
    fraction the engine reads, so existing files need no conversion."""
    import config
    assert config.parse_percent(" 50 ") == 50
    assert config.parse_percent("0") == 0
    assert config.parse_percent("100") == 100
    for bad in ("0,5", "0.5", "50%", "101", "-1", "", "half", True, None):
        assert config.parse_percent(bad) is None, bad

    assert config.max_delete_percent() == 50            # default 0.5
    assert config.set_max_delete_percent("30") is True
    assert config.max_delete_ratio() == 0.3             # stored as a fraction
    assert config.max_delete_percent() == 30
    assert config.set_max_delete_percent("0,3") is False  # refused, nothing written
    assert config.max_delete_ratio() == 0.3


def test_kept_excluded_names_do_not_count_toward_the_guard(
        fake_drive, local_tree, write_mappings, engine):
    """Names kept by excluded_remote are not orphans, so they do not arm it."""
    engine.update_settings(mass_delete_guard=True)
    cfg = _emptied(local_tree, write_mappings, engine, 30, 30)
    kept = write_mappings([_mapping(
        cfg_source(cfg), excluded_remote="keep",
        exclusions={"names": [], "patterns": ["f*.txt"]})])
    result = engine(kept, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[delete-guard]" not in result.stdout
    assert _trashed_count(fake_drive, 30) == 0


def cfg_source(cfg):
    with open(cfg, encoding="utf-8") as f:
        return json.load(f)["mappings"][0]["source"]


def test_twoway_global_exclusion_trashes_without_downloading(
        fake_drive, local_tree, write_mappings, engine):
    src = local_tree({"Docs/keep.txt": (b"keep", 1_000_000_000)})
    fake_drive.seed_file(REMOTE + "/secret.txt", b"hide")
    cfg = write_mappings(
        [], twoway_mappings=[_mapping(src / "Docs")],
        exclusions=_exclude("secret.txt"))
    result = engine.reconcile(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert fake_drive.trashed(REMOTE + "/secret.txt")
    assert not (src / "Docs" / "secret.txt").exists()
