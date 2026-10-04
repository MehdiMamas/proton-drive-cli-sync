"""excluded_remote, mass-deletion guard, mount re-check, GUI key preservation."""

import json
import os

import proton_sync
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


def _many(count):
    return {"Docs/f%02d.txt" % i: (b"data%d" % i, 1_000_000_000) for i in range(count)}


def _exclude(name):
    return {"names": [name], "patterns": []}


def _upload_secret(local_tree, write_mappings, engine, **extra):
    src = local_tree({"Docs/secret.txt": (b"hide", 1_000_000_000)})
    assert engine(write_mappings([_mapping(src / "Docs", **extra)])).returncode == 0
    return src


def test_excluded_remote_prune_restores_old_behavior(
        fake_drive, local_tree, write_mappings, engine):
    src = _upload_secret(local_tree, write_mappings, engine)
    cfg = write_mappings([_mapping(
        src / "Docs", excluded_remote="prune", exclusions=_exclude("secret.txt"))])
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


def test_unknown_excluded_remote_value_defaults_to_keep(
        fake_drive, local_tree, write_mappings, engine):
    src = _upload_secret(local_tree, write_mappings, engine)
    cfg = write_mappings([_mapping(
        src / "Docs", excluded_remote="bogus", exclusions=_exclude("secret.txt"))])
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "bogus" in result.stdout
    assert not fake_drive.trashed(REMOTE + "/secret.txt")


def test_subpath_respects_excluded_remote(fake_drive, local_tree, write_mappings, engine):
    src = _upload_secret(local_tree, write_mappings, engine)
    docs = str(src / "Docs")
    cfg = write_mappings([_mapping(src / "Docs", exclusions=_exclude("secret.txt"))])
    kept = engine(cfg, "--delete", "--ignore-cache", "--subpath", docs, "--mapping-source", docs)
    assert kept.returncode == 0, kept.stdout + kept.stderr
    assert not fake_drive.trashed(REMOTE + "/secret.txt")
    prune = write_mappings([_mapping(
        src / "Docs", excluded_remote="prune", exclusions=_exclude("secret.txt"))])
    pruned = engine(prune, "--delete", "--ignore-cache", "--subpath", docs, "--mapping-source", docs)
    assert pruned.returncode == 0, pruned.stdout + pruned.stderr
    assert fake_drive.trashed(REMOTE + "/secret.txt")


def _emptied_tree(local_tree, write_mappings, engine, count, remove, **extra):
    src = local_tree(_many(count))
    cfg = write_mappings([_mapping(src / "Docs", **extra)])
    assert engine(cfg).returncode == 0
    for i in range(remove):
        (src / "Docs" / ("f%02d.txt" % i)).unlink()
    return cfg


def _trashed_count(fake_drive, count):
    return sum(1 for i in range(count) if fake_drive.trashed(REMOTE + "/f%02d.txt" % i))


def test_mass_delete_guard_refuses_and_exits_5(fake_drive, local_tree, write_mappings, engine):
    cfg = _emptied_tree(local_tree, write_mappings, engine, 30, 30)
    result = engine(cfg, "--delete")
    assert result.returncode == 5, result.stdout + result.stderr
    assert "[delete-guard]" in result.stdout
    assert _trashed_count(fake_drive, 30) == 0
    assert '"deletions_refused": 1' in result.stdout
    # The folder was not marked delete_synced: the next pass looks again and refuses again.
    again = engine(cfg, "--delete")
    assert again.returncode == 5, again.stdout + again.stderr
    assert _trashed_count(fake_drive, 30) == 0


def test_mass_delete_guard_below_threshold_allows(
        fake_drive, local_tree, write_mappings, engine):
    cfg = _emptied_tree(local_tree, write_mappings, engine, 30, 3)
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[delete-guard]" not in result.stdout
    assert _trashed_count(fake_drive, 30) == 3


def test_allow_mass_delete_flag_overrides_guard(
        fake_drive, local_tree, write_mappings, engine):
    cfg = _emptied_tree(local_tree, write_mappings, engine, 30, 30)
    result = engine(cfg, "--delete", "--allow-mass-delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[delete-guard]" not in result.stdout
    assert _trashed_count(fake_drive, 30) == 30


def test_per_mapping_threshold_override(fake_drive, local_tree, write_mappings, engine):
    cfg = _emptied_tree(
        local_tree, write_mappings, engine, 30, 3, max_delete_min=2, max_delete_ratio=0.05)
    result = engine(cfg, "--delete")
    assert result.returncode == 5, result.stdout + result.stderr
    assert "[delete-guard]" in result.stdout
    assert _trashed_count(fake_drive, 30) == 0


def test_listing_failure_never_deletes(fake_drive, local_tree, write_mappings, engine):
    src = local_tree({"Docs/a.txt": (b"a", 1_000_000_000)})
    fake_drive.seed_file(REMOTE + "/orphan.txt", b"old")
    fake_drive.add_fault(cmd="list", match=REMOTE)
    result = engine(write_mappings([_mapping(src / "Docs")]), "--delete")
    assert result.returncode == 5, result.stdout + result.stderr
    assert not fake_drive.trashed(REMOTE + "/orphan.txt")


def test_mount_lost_mid_pass_stops_deletions(fake_drive, local_tree):
    folders = ("a", "b", "c")
    spec = {}
    for name in folders:
        spec["Docs/%s/old.txt" % name] = (b"old", 1_000_000_000)
    src = local_tree(spec)
    root = str(src / "Docs")
    proton_sync._RUN.reset()
    assert proton_sync.sync_folder(root, "/my-files/Backups", rename_ext=False)
    for name in folders:
        (src / "Docs" / name / "old.txt").unlink()
        local_tree.write("Docs/%s/new.txt" % name, b"new", 1_000_000_100)

    calls = []

    def guard():
        calls.append(1)
        return (True, "") if len(calls) == 1 else (False, "mount gone")

    opts = {"delete_guard": guard, "mount_lost": False,
            "max_delete_min": 20, "max_delete_ratio": 0.5}
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


def test_mappings_roundtrip_preserves_unknown_keys():
    old = {
        "type": "folder", "source": "/s", "dest_parent": "/d",
        "allow_delete": True, "delete_mode": "trash", "source_kind": "local",
        "excluded_remote": "prune", "max_delete_min": 5, "max_delete_ratio": 0.2,
        "future_key": {"a": 1},
    }
    # The dialog rebuilt the mapping with allow_delete switched off.
    new = {"type": "folder", "source": "/s", "dest_parent": "/d"}
    saved = json.loads(json.dumps(carry_unknown_keys(old, new)))
    assert saved["excluded_remote"] == "prune"
    assert saved["max_delete_min"] == 5
    assert saved["max_delete_ratio"] == 0.2
    assert saved["future_key"] == {"a": 1}
    for key in ("allow_delete", "delete_mode", "source_kind"):
        assert key not in saved
    assert carry_unknown_keys(None, {"x": 1}) == {"x": 1}
    assert carry_unknown_keys({"excluded_remote": "prune"}, {"excluded_remote": "keep"}) == {
        "excluded_remote": "keep"}


def test_config_thresholds_fall_back_on_bad_values():
    import config
    assert config.DEFAULTS["max_delete_min"] == 20
    assert config.DEFAULTS["max_delete_ratio"] == 0.5
    assert isinstance(config.max_delete_min(), int)
    assert 0.0 <= config.max_delete_ratio() <= 1.0
