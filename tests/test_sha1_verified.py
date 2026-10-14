"""The SHA1 check on record, per mapping (✅✅ in the “Ready” column).

The engine notes a mapping as checked when a full pass ends it without
failure and its content was compared at equal size: a “SHA1 check” pass,
an “Ignore cache” pass, or the first pass of a mapping the cache did not
know. Checks made before this record existed are taken, once, from the
logs the window writes.
"""
import json

import proton_sync


def _mapping(source):
    return {"type": "folder", "source": str(source), "dest_parent": "/my-files/Backups"}


def _cache(isolated_home):
    path = isolated_home / ".proton-drive-sync" / "cache" / "mappings.cache"
    return json.loads(path.read_text(encoding="utf-8"))


def _verified(isolated_home):
    return _cache(isolated_home).get("__meta__", {}).get("sha1_verified", {})


def test_first_pass_of_a_new_mapping_is_a_check(
        fake_drive, local_tree, write_mappings, engine, isolated_home):
    src = local_tree({"Docs/a.txt": (b"hello", 1_000_000_000)})
    cfg = write_mappings([_mapping(src / "Docs")])
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert str(src / "Docs") in _verified(isolated_home)


def test_an_ordinary_pass_on_a_known_mapping_adds_nothing(
        fake_drive, local_tree, write_mappings, engine, isolated_home):
    src = local_tree({"Docs/a.txt": (b"hello", 1_000_000_000)})
    cfg = write_mappings([_mapping(src / "Docs")])
    assert engine(cfg).returncode == 0
    # Same cache, but as an older engine would have left it: no record.
    data = _cache(isolated_home)
    data["__meta__"].pop("sha1_verified")
    path = isolated_home / ".proton-drive-sync" / "cache" / "mappings.cache"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _verified(isolated_home) == {}
    # A “SHA1 check” pass then notes it, and says so in its header.
    result = engine(cfg, "--verify-hash")
    assert result.returncode == 0, result.stdout + result.stderr
    assert str(src / "Docs") in _verified(isolated_home)
    assert "SHA1 check: every folder is examined again" in result.stdout
    assert "Resuming on an existing cache" not in result.stdout
    assert "  — SHA1 check of all content" in result.stdout


def test_a_mapping_with_a_failure_is_not_noted(
        fake_drive, local_tree, write_mappings, engine, isolated_home):
    src = local_tree({"Docs/a.txt": (b"hello", 1_000_000_000)})
    fake_drive.add_fault(cmd="upload", match="a.txt", times=10, stderr="network down")
    result = engine(write_mappings([_mapping(src / "Docs")]))
    assert result.returncode != 0
    assert _verified(isolated_home) == {}


def test_dry_run_notes_nothing(fake_drive, local_tree, write_mappings, engine, isolated_home):
    src = local_tree({"Docs/a.txt": (b"hello", 1_000_000_000)})
    result = engine(write_mappings([_mapping(src / "Docs")]), "--dry-run", "--verify-hash")
    assert result.returncode == 0, result.stdout + result.stderr
    path = isolated_home / ".proton-drive-sync" / "cache" / "mappings.cache"
    assert not path.exists() or _verified(isolated_home) == {}


def test_reset_removes_then_restores_the_record(tmp_path):
    cache = proton_sync.Cache(str(tmp_path / "c.cache"))
    cache.data["/src/Docs"] = {"sig": {}, "delete_synced": True}
    cache.mark_sha1_verified("/src/Docs", 100.0)
    cache.mark_sha1_verified("/src/Other", 200.0)
    cache.purge_subtree("/src/Docs")
    assert cache.sha1_verified() == {"/src/Other": 200.0}
    assert not cache.has_entries_under("/src/Docs")


# ── Checks taken from the logs, once ─────────────────────────────────────

LOG_OK = """== Synchro Proton Drive — 2 entrée(s) — réel [verify-hash] ==
   Cache : /home/myuser/.proton-drive-sync/cache/mappings.cache (12 dossier(s) connu(s))
   ↺ Reprise sur un cache existant — le travail déjà enregistré ne sera pas refait (les dossiers inchangés sont sautés).

▶ Mapping 1/2 : /src/Docs  =>  /my-files
📂 /src/Docs
    (taille identique, contenu vérifié par SHA1 — identique : Erreurs-2024.txt)

▶ Mapping 2/2 : /src/Photos  =>  /my-files
📂 /src/Photos

Terminé.
"""


def _import(tmp_path, logs, mappings=("/src/Docs", "/src/Photos")):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    for name, text in logs.items():
        (log_dir / name).write_text(text, encoding="utf-8")
    cache = proton_sync.Cache(str(tmp_path / "mappings.cache"))
    n = proton_sync.import_sha1_from_logs(
        cache, "mappings.cache",
        [{"type": "folder", "source": s} for s in mappings], str(log_dir))
    return n, cache


def test_a_finished_check_in_the_logs_is_taken(tmp_path):
    n, cache = _import(tmp_path, {"sync-20261003-1442.log": LOG_OK})
    assert n == 2
    assert set(cache.sha1_verified()) == {"/src/Docs", "/src/Photos"}
    assert cache.sha1_logs_read()


def test_logs_that_do_not_prove_a_check_are_ignored(tmp_path):
    logs = {
        # before the corrected engine ran
        "sync-20261002-0900.log": LOG_OK,
        # an ordinary pass
        "sync-20261005-0900.log": LOG_OK.replace(" [verify-hash]", ""),
        # another mappings file
        "sync-20261005-1000.log": LOG_OK.replace("mappings.cache", "mappings-other.cache"),
        # a failure
        "sync-20261005-1100.log": LOG_OK.replace("📂 /src/Photos", "  ❌ upload failed: x"),
        # interrupted: no final line
        "sync-20261005-1200.log": LOG_OK.replace("Terminé.\n", ""),
        # dry run
        "sync-20261005-1300.log": LOG_OK.replace("réel", "DRY-RUN (rien ne sera transféré)"),
        # newer engine, ended with failures
        "sync-20261005-1400.log": LOG_OK + "Résumé : …\n[run-result] {\"exit\": 5}\n",
    }
    n, cache = _import(tmp_path, logs)
    assert n == 0
    assert cache.sha1_verified() == {}
    assert cache.sha1_logs_read()


def test_only_mappings_still_present_are_noted(tmp_path):
    n, cache = _import(tmp_path, {"sync-20261003-1442.log": LOG_OK},
                       mappings=("/src/Docs",))
    assert n == 1
    assert set(cache.sha1_verified()) == {"/src/Docs"}


def test_the_logs_are_read_once(fake_drive, local_tree, write_mappings, engine, isolated_home):
    src = local_tree({"Docs/a.txt": (b"hello", 1_000_000_000)})
    cfg = write_mappings([_mapping(src / "Docs")])
    assert engine(cfg).returncode == 0
    assert _cache(isolated_home)["__meta__"].get("sha1_logs_read") == 2


def test_an_account_change_does_not_reread_the_old_logs(
        fake_drive, local_tree, write_mappings, engine, isolated_home):
    """The logs speak of the previous account's Drive: after the cache is
    discarded for a new account, they must not be read for it."""
    src = local_tree({"Docs/a.txt": (b"hello", 1_000_000_000)})
    cfg = write_mappings([_mapping(src / "Docs")])
    path = isolated_home / ".proton-drive-sync" / "cache" / "mappings.cache"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"__meta__": {
        "account": "other@example.com",
        "sha1_verified": {"/old/mapping": 1.0}}}), encoding="utf-8")
    result = engine(cfg, "--accept-account-change")
    assert result.returncode == 0, result.stdout + result.stderr
    meta = _cache(isolated_home)["__meta__"]
    assert meta.get("sha1_logs_read") == 2
    assert "/old/mapping" not in meta.get("sha1_verified", {})


def test_a_restricted_pass_reads_the_logs_for_every_mapping(
        fake_drive, local_tree, write_mappings, engine, isolated_home, tmp_path):
    """Found in production: with one row selected (--only-source), only that
    mapping was taken from the logs. The logs cover the whole file."""
    import pathlib, shutil
    src = local_tree({"Docs/a.txt": (b"a", 1_000_000_000),
                      "Photos/b.txt": (b"b", 1_000_000_000)})
    cfg = write_mappings([_mapping(src / "Docs"), _mapping(src / "Photos")])
    # A cache as v1.18.0 left it: both mappings known, no record, logs
    # flagged as read by the faulty version (True).
    assert engine(cfg).returncode == 0
    path = isolated_home / ".proton-drive-sync" / "cache" / "mappings.cache"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["__meta__"]["sha1_verified"] = {}
    data["__meta__"]["sha1_logs_read"] = True
    path.write_text(json.dumps(data), encoding="utf-8")
    logs = pathlib.Path(proton_sync.__file__).resolve().parent / "logs"
    created = not logs.exists()
    logs.mkdir(exist_ok=True)
    log = logs / "sync-20261003-1442.log"
    assert not log.exists()
    log.write_text(LOG_OK.replace("/src/Docs", str(src / "Docs"))
                   .replace("/src/Photos", str(src / "Photos")), encoding="utf-8")
    try:
        result = engine(cfg, "--only-source", str(src / "Docs"))
    finally:
        log.unlink()
        if created:
            shutil.rmtree(logs)
    assert result.returncode == 0, result.stdout + result.stderr
    assert set(_verified(isolated_home)) == {str(src / "Docs"), str(src / "Photos")}
    assert "2 mapping(s) already checked by SHA1" in result.stdout
