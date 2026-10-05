"""Two-way reconcile for one mapping that opted in with ``direction: twoway``.

A mapping with no direction, or any other value, stays one-way and never
reaches this module. Downloads go through the engine's ``run_cli``. A failed
download does not replace the local file and does not rewrite its sync row.
A failed remote listing does not update the sync database for that folder.
"""

import os
import shutil
import sys
import tempfile

import syncdb


def _load_engine():
    """The running engine.

    ``python proton_sync.py`` executes that file as ``__main__``. Importing
    ``proton_sync`` again would be a second module, with its own counters, so
    a failure recorded here would not change the pass exit code.
    """
    main = sys.modules.get("__main__")
    if main is not None and hasattr(main, "run_cli") and hasattr(main, "get_remote_listing"):
        return main
    import proton_sync
    return proton_sync


_ps = _load_engine()

try:
    from i18n import _
except ImportError:
    def _(s):
        return s


_DOC_TYPES = ("document", "spreadsheet", "proton-doc")
_CONFLICT_MARK = " (proton conflict)"
WEB_DOCUMENT_LINE = (
    "Proton web document. Open it on the web. This copy is not uploaded."
)


def is_twoway(mapping):
    return isinstance(mapping, dict) and mapping.get("direction") == "twoway"


def is_volume(mapping):
    """The local folder is My files itself, not a folder created under it."""
    return is_twoway(mapping) and mapping.get("volume") is True


def sync_mapping(mapping, config_path, cache, exclusions, dry_run=False,
                 verbose=False, allow_mass_delete=False, global_ex=None):
    """Reconcile one twoway mapping. Returns True when the tree completed."""
    source = mapping.get("source") or ""
    if mapping.get("type") == "file":
        ctx = _context(mapping, config_path, cache, exclusions, dry_run,
                       verbose, allow_mass_delete, source_root=os.path.dirname(source),
                       global_ex=global_ex)
        with ctx.db:
            return _sync_file(source, mapping.get("dest_parent") or "", ctx)
    ctx = _context(mapping, config_path, cache, exclusions, dry_run,
                   verbose, allow_mass_delete, source_root=source,
                   global_ex=global_ex)
    with ctx.db:
        return _sync_dir(source, mapping.get("dest_parent") or "", ctx)


def sync_tree(mapping, local_dir, remote_parent, config_path, cache, exclusions,
              dry_run=False, verbose=False, allow_mass_delete=False, global_ex=None):
    """Reconcile one folder of a twoway mapping (a full pass or a subpath)."""
    ctx = _context(mapping, config_path, cache, exclusions, dry_run,
                   verbose, allow_mass_delete,
                   source_root=mapping.get("source") or local_dir,
                   global_ex=global_ex)
    with ctx.db:
        return _sync_dir(local_dir, remote_parent, ctx)


class _Ctx:
    def __init__(self, mapping, db, cache, exclusions, dry_run, verbose,
                 opts, source_root, config_path):
        self.mapping = mapping
        self.db = db
        self.cache = cache
        self.exclusions = exclusions
        self.dry_run = dry_run
        self.verbose = verbose
        self.opts = opts
        self.source_root = source_root
        self.config_path = config_path


def _context(mapping, config_path, cache, exclusions, dry_run, verbose,
             allow_mass_delete, source_root, global_ex=None):
    opts = _ps.build_delete_opts(
        mapping, source_root, allow_mass_delete, verbose, global_ex=global_ex)
    db = syncdb.SyncDB(syncdb.database_path(config_path))
    return _Ctx(mapping, db, cache, exclusions, dry_run, verbose, opts,
                source_root, config_path)


def _sync_file(local_file, remote_parent, ctx):
    if not ctx.dry_run and not _ps.ensure_remote_path(remote_parent):
        return False
    listing = _ps.get_remote_listing(remote_parent, verbose=ctx.verbose)
    if not listing.ok:
        print("[list-skipped] " + _(
            "Could not list {p} — file skipped this pass "
            "(nothing sent, nothing deleted).").format(p=remote_parent))
        _ps._RUN.add("folders_listing_failed")
        return False
    name = os.path.basename(local_file)
    return _reconcile_file(local_file, remote_parent, listing.get(name), ctx)


def _remote_folder(local_dir, remote_parent, ctx):
    """Remote directory this local directory lists.

    A volume root lists ``dest_parent`` (``/my-files``). Every other folder,
    including children of a volume, still appends its own name.
    """
    parent = (remote_parent or "").rstrip("/")
    root = os.path.normpath(ctx.source_root or "")
    if is_volume(ctx.mapping) and os.path.normpath(local_dir) == root:
        return parent
    name = os.path.basename(os.path.normpath(local_dir))
    return parent + "/" + name if parent else "/" + name


def _sync_dir(local_dir, remote_parent, ctx):
    """List this folder even when the one-way fingerprint is unchanged."""
    remote_folder = _remote_folder(local_dir, remote_parent, ctx)
    print("📂 " + local_dir)
    if not ctx.dry_run and not _ps.ensure_remote_path(remote_folder):
        return False
    listing = _ps.get_remote_listing(remote_folder, verbose=ctx.verbose)
    if not listing.ok:
        print("[list-skipped] " + _(
            "Could not list {p} — folder skipped this pass "
            "(nothing sent, nothing deleted).").format(p=remote_folder))
        _ps._RUN.add("folders_listing_failed")
        return False

    try:
        entries = list(os.scandir(local_dir))
    except OSError as exc:
        _ps._note_unreadable(local_dir, exc)
        return False

    local_names = set()
    dir_failed = False
    all_children = True
    for entry in entries:
        if ctx.exclusions and ctx.exclusions.is_excluded(entry.name):
            continue
        local_names.add(entry.name)
        if _is_conflict_copy(entry.name):
            continue
        if entry.is_dir(follow_symlinks=False):
            if not _sync_dir(entry.path, remote_folder, ctx):
                all_children = False
        elif entry.is_file():
            if not _reconcile_file(
                    entry.path, remote_folder, listing.get(entry.name), ctx):
                dir_failed = True

    if not _remote_only(local_dir, remote_folder, listing, local_names, ctx):
        dir_failed = True

    complete = all_children and not dir_failed
    if ctx.cache is not None and not ctx.dry_run and complete:
        excl_fp = ctx.exclusions.fingerprint() if ctx.exclusions else None
        signature = _ps._local_signature(local_dir, remote_folder, excl_fp)
        if signature is not None:
            ctx.cache.update(local_dir, signature, subtree_complete=True)
            ctx.cache.maybe_save()
    return complete


def _remote_only(local_dir, remote_folder, listing, local_names, ctx):
    gone = []
    restores = []
    ok = True
    for name, info in listing.items():
        if name in local_names:
            continue
        if ctx.exclusions and ctx.exclusions.is_excluded(name):
            if _ps._keep_excluded_remote(name, ctx.exclusions, ctx.opts):
                continue
            remote_path = remote_folder.rstrip("/") + "/" + name
            if _can_trash(ctx, remote_path):
                if not _ps.remote_trash(
                        remote_path, permanent=False, dry_run=ctx.dry_run):
                    ok = False
            continue
        local_path = os.path.join(local_dir, name)
        remote_path = remote_folder.rstrip("/") + "/" + name
        rtype = info.get("type") if isinstance(info, dict) else None
        if rtype == "folder":
            if not ctx.dry_run:
                os.makedirs(local_path, exist_ok=True)
            if not _sync_dir(local_path, remote_folder, ctx):
                ok = False
            continue
        if rtype in _DOC_TYPES:
            _mark_document(local_path, remote_path, info, ctx)
            continue
        row = ctx.db.get(local_path)
        if row and row.get("state") == "synced":
            gone.append((local_path, remote_path, info, row))
        elif row and row.get("state") == "pending-down":
            restores.append((local_path, remote_path, info))
        elif row and row.get("state") == "conflict":
            continue
        else:
            restores.append((local_path, remote_path, info))

    if _refusing_mass_delete(gone, listing, ctx):
        print("[delete-guard] " + _(
            "refusing to trash {n} of {t} remote item(s) in {p}").format(
                n=len(gone), t=len(listing), p=remote_folder))
        _ps._RUN.add("deletions_refused")
        for local_path, remote_path, info, row in gone:
            _set_state(row, "pending-down", ctx)
        return False

    for local_path, remote_path, info, row in gone:
        if _can_trash(ctx, remote_path):
            if _ps.remote_trash(
                    remote_path, permanent=False, dry_run=ctx.dry_run):
                if not ctx.dry_run:
                    ctx.db.delete(local_path)
            else:
                ok = False
        else:
            _set_state(row, "pending-down", ctx)
            if ctx.opts.get("mount_lost"):
                ok = False

    for local_path, remote_path, info in restores:
        if not _download_over(local_path, remote_path, info, ctx):
            ok = False
    return ok


def _reconcile_file(local_path, remote_folder, remote_info, ctx):
    name = os.path.basename(local_path)
    remote_path = remote_folder.rstrip("/") + "/" + name
    if isinstance(remote_info, dict) and remote_info.get("type") in _DOC_TYPES:
        _mark_document(local_path, remote_path, remote_info, ctx)
        return True
    row = ctx.db.get(local_path)
    if row and row.get("state") == "conflict":
        print("[conflict] " + _("both sides changed, kept both: {p}").format(p=local_path))
        return True

    if not isinstance(remote_info, dict) or remote_info.get("type") not in (None, "file"):
        if row and row.get("state") == "synced":
            return _hold(local_path, ctx)
        return _upload(local_path, remote_folder, remote_info, ctx)

    action, reason = _ps.download_decision(local_path, remote_info, row)
    if reason == "local-only":
        return _upload(local_path, remote_folder, remote_info, ctx)
    if action == "download":
        return _download_over(local_path, remote_path, remote_info, ctx)
    if action == "conflict":
        return _write_conflict(local_path, remote_path, remote_info, row, ctx)
    if not ctx.dry_run:
        _save_synced(local_path, remote_path, remote_info, ctx)
    return True


def _remember(local_path, remote_path, state, ctx):
    """Record a state without claiming the upload already finished."""
    if ctx.dry_run:
        return
    row = ctx.db.get(local_path)
    if row:
        stored = dict(row)
        stored["state"] = state
        if remote_path:
            stored["remote_path"] = remote_path
        ctx.db.upsert(stored)
        return
    ctx.db.upsert({
        "local_path": local_path,
        "remote_path": remote_path,
        "remote_node_id": None,
        "sha1": None,
        "claimed_size": None,
        "claimed_mtime": None,
        "local_inode": None,
        "local_mtime": None,
        "state": state,
    })


def _upload(local_path, remote_folder, remote_info, ctx):
    if _is_web_marker(local_path):
        return True
    remote_path = remote_folder.rstrip("/") + "/" + os.path.basename(local_path)
    _remember(local_path, remote_path, "pending-up", ctx)
    ok = _ps.upload_batch(
        [local_path], remote_folder, dry_run=ctx.dry_run, verbose=ctx.verbose,
        conflict_mode=ctx.mapping.get("conflict_mode", "replace"))
    if not ok:
        _remember(local_path, remote_path, "error", ctx)
        return False
    if not ctx.dry_run:
        _save_synced(local_path, remote_path, remote_info, ctx)
    return True


def _download_over(local_path, remote_path, remote_info, ctx):
    if ctx.dry_run:
        print("[download] " + _("[DRY-RUN] would download: {p}").format(p=local_path))
        return True
    parent = os.path.dirname(local_path) or "."
    temporary = tempfile.mkdtemp(prefix=".proton-sync-download-", dir=parent)
    try:
        fetched, skipped = _fetch(remote_path, temporary)
        if skipped:
            _mark_document(local_path, remote_path, remote_info, ctx)
            return True
        if fetched is None:
            print("[download-failed] " + _(
                "download failed, local file kept: {p}").format(p=local_path))
            _ps._RUN.add("files_failed")
            return False
        os.replace(fetched, local_path)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    print("[download] " + _("downloaded {p}").format(p=local_path))
    _save_synced(local_path, remote_path, remote_info, ctx)
    return True


def _fetch(remote_path, directory):
    """Return (local path or None, skipped_document)."""
    result = _ps.run_cli(
        ["filesystem", "download", "-f", "replace", remote_path, directory])
    text = (result.stdout or "") + "\n" + (result.stderr or "")
    if "skipped:" in text:
        return None, True
    name = os.path.basename(remote_path.rstrip("/"))
    path = os.path.join(directory, name)
    if result.returncode != 0 or not os.path.isfile(path):
        return None, False
    return path, False


def _write_conflict(local_path, remote_path, remote_info, row, ctx):
    print("[conflict] " + _("both sides changed, kept both: {p}").format(p=local_path))
    if ctx.dry_run:
        return True
    conflict_path = _conflict_path(local_path)
    if not os.path.exists(conflict_path):
        parent = os.path.dirname(local_path) or "."
        temporary = tempfile.mkdtemp(prefix=".proton-sync-download-", dir=parent)
        try:
            fetched, skipped = _fetch(remote_path, temporary)
            if skipped:
                _mark_document(local_path, remote_path, remote_info, ctx)
                return True
            if fetched is None:
                print("[download-failed] " + _(
                    "download failed, local file kept: {p}").format(p=local_path))
                _ps._RUN.add("files_failed")
                return False
            os.replace(fetched, conflict_path)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
    _mark_conflict(local_path, remote_path, remote_info, row, ctx)
    return True


def _hold(local_path, ctx):
    """Move the local file into the state directory. Do not delete the bytes."""
    if ctx.dry_run:
        print("[held] " + _("[DRY-RUN] would move aside: {p}").format(p=local_path))
        return True
    dest = _holding_destination(ctx, local_path)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        dest = dest + ".kept"
    try:
        os.rename(local_path, dest)
    except OSError:
        try:
            shutil.copy2(local_path, dest)
        except OSError as exc:
            print("[download-failed] " + _(
                "could not move aside {p}: {e}").format(p=local_path, e=exc))
            _ps._RUN.add("files_failed")
            return False
        print("[held] " + local_path + " -> " + dest)
        _ps._RUN.add("files_failed")
        return False
    ctx.db.delete(local_path)
    print("[held] " + local_path + " -> " + dest)
    return True


def _can_trash(ctx, remote_path):
    if not ctx.mapping.get("allow_delete"):
        return False
    if (str(remote_path).startswith("/shared-with-me")
            and ctx.mapping.get("shared_delete_confirmed") is not True):
        return False
    if ctx.opts.get("mount_lost"):
        return False
    guard = ctx.opts.get("delete_guard")
    if guard is None:
        return False
    ok, reason = guard()
    if ok:
        return True
    ctx.opts["mount_lost"] = True
    print("[delete-guard] " + _(
        "mount check failed, remote file kept: {r}").format(r=reason))
    _ps._RUN.add("deletions_refused")
    return False


def _refusing_mass_delete(gone, listing, ctx):
    if not gone or ctx.opts.get("allow_mass_delete"):
        return False
    if not ctx.opts.get("mass_delete_guard", True):
        return False
    n_remote = len(listing)
    if not n_remote:
        return False
    max_min = ctx.opts.get("max_delete_min", 20)
    max_ratio = ctx.opts.get("max_delete_ratio", 0.5)
    return len(gone) >= max_min and len(gone) / n_remote > max_ratio


def _save_synced(local_path, remote_path, remote_info, ctx):
    try:
        st = os.stat(local_path)
        sha = _ps._local_sha1(local_path)
    except OSError:
        return
    # Local SHA-1, not the listing from before the upload. The remote copy
    # just received these bytes; storing the old claimed SHA-1 would look
    # like both sides changed on the next pass.
    claimed_size = st.st_size
    claimed_mtime = float(st.st_mtime)
    node_id = None
    if isinstance(remote_info, dict):
        node_id = remote_info.get("node_id")
    ctx.db.upsert({
        "local_path": local_path,
        "remote_path": remote_path,
        "remote_node_id": node_id,
        "sha1": sha,
        "claimed_size": claimed_size,
        "claimed_mtime": claimed_mtime,
        "local_inode": st.st_ino,
        "local_mtime": st.st_mtime,
        "state": "synced",
    })


def _mark_conflict(local_path, remote_path, remote_info, row, ctx):
    if row:
        stored = dict(row)
        stored["state"] = "conflict"
        stored["remote_path"] = remote_path
    else:
        try:
            st = os.stat(local_path)
            sha = _ps._local_sha1(local_path)
        except OSError:
            return
        stored = {
            "local_path": local_path,
            "remote_path": remote_path,
            "remote_node_id": None,
            "sha1": sha,
            "claimed_size": st.st_size,
            "claimed_mtime": float(st.st_mtime),
            "local_inode": st.st_ino,
            "local_mtime": st.st_mtime,
            "state": "conflict",
        }
    if isinstance(remote_info, dict) and remote_info.get("node_id"):
        stored["remote_node_id"] = remote_info.get("node_id")
    ctx.db.upsert(stored)


def _is_web_marker(local_path):
    """True when this file is the stand-in for a Proton document."""
    try:
        if os.path.getsize(local_path) > 4096:
            return False
        with open(local_path, "r", encoding="utf-8", errors="replace") as handle:
            line = handle.readline(200)
    except OSError:
        return False
    return line.startswith("Proton web document")


def _write_web_marker(local_path):
    """Write the stand-in, or leave a real file that already uses this name."""
    if os.path.isdir(local_path):
        return False
    if os.path.isfile(local_path):
        return _is_web_marker(local_path)
    parent = os.path.dirname(local_path) or "."
    os.makedirs(parent, exist_ok=True)
    temporary = os.path.join(parent, ".proton-sync-marker-tmp")
    text = (
        WEB_DOCUMENT_LINE + "\n"
        "The Proton CLI has no file body for a document or a spreadsheet.\n"
    )
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, local_path)
    except OSError:
        try:
            os.remove(temporary)
        except OSError:
            pass
        return False
    return True


def _mark_document(local_path, remote_path, remote_info, ctx):
    print("[download-skipped] " + _(
        "Proton document or spreadsheet left unchanged: {p}").format(p=remote_path))
    if ctx.dry_run:
        return
    if os.path.isfile(local_path) and not _is_web_marker(local_path):
        return
    if not _write_web_marker(local_path):
        claimed_size = None
        sha = None
        claimed_mtime = None
        node_id = None
        if isinstance(remote_info, dict):
            claimed_size = remote_info.get("claimed_size")
            sha = remote_info.get("sha1")
            claimed_mtime = _ps._remote_mtime_seconds(remote_info.get("mtime"))
            node_id = remote_info.get("node_id")
        ctx.db.upsert({
            "local_path": local_path,
            "remote_path": remote_path,
            "remote_node_id": node_id,
            "sha1": sha,
            "claimed_size": claimed_size,
            "claimed_mtime": claimed_mtime,
            "local_inode": None,
            "local_mtime": None,
            "state": "error",
        })
        return
    _save_synced(local_path, remote_path, remote_info, ctx)


def _set_state(row, state, ctx):
    if ctx.dry_run or not row:
        return
    stored = dict(row)
    stored["state"] = state
    ctx.db.upsert(stored)


def _holding_destination(ctx, local_path):
    import config as appconfig
    stem = os.path.splitext(os.path.basename(os.fspath(ctx.config_path)))[0]
    try:
        rel = os.path.relpath(local_path, ctx.source_root)
    except ValueError:
        rel = os.path.basename(local_path)
    if rel.startswith(".."):
        rel = os.path.basename(local_path)
    return os.path.join(appconfig.DATA_DIR, "holding", stem, rel)


def _conflict_path(local_path):
    directory = os.path.dirname(local_path)
    stem, ext = os.path.splitext(os.path.basename(local_path))
    return os.path.join(directory, stem + _CONFLICT_MARK + ext)


def _is_conflict_copy(name):
    stem, _ext = os.path.splitext(name)
    return stem.endswith(_CONFLICT_MARK)
