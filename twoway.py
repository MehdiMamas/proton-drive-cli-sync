"""Two-way reconcile for one entry of the ``sync_mappings`` key (direction "twoway").

Entries of ``mappings`` stay one-way and never reach this module. Downloads go through the engine's ``run_cli``. A failed
download does not replace the local file and does not rewrite its sync row.
A failed remote listing does not update the sync database for that folder.
"""

__version__ = "1.2.0"

import os
import re
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
_CONFLICT_STEM = re.compile(r" \(proton conflict(?: \d+)?\)$")
WEB_DOCUMENT_LINE = (
    "Proton web document. Open it on the web. This copy is not uploaded."
)


def sync_mapping(mapping, config_path, cache, exclusions, dry_run=False,
                 verbose=False, allow_mass_delete=False, global_ex=None,
                 delete=False):
    """Reconcile one twoway mapping. Returns True when the tree completed.

    ``delete`` is the pass's ``--delete`` switch. Without it nothing is
    removed on either side, whatever the mapping says.
    """
    source = mapping.get("source") or ""
    if mapping.get("type") == "file":
        ctx = _context(mapping, config_path, cache, exclusions, dry_run,
                       verbose, allow_mass_delete, source_root=os.path.dirname(source),
                       global_ex=global_ex, delete=delete)
        with ctx.db:
            return _sync_file(source, mapping.get("dest_parent") or "", ctx)
    ctx = _context(mapping, config_path, cache, exclusions, dry_run,
                   verbose, allow_mass_delete, source_root=source,
                   global_ex=global_ex, delete=delete)
    with ctx.db:
        dest_parent = mapping.get("dest_parent") or ""
        _detect_local_moves(ctx, dest_parent)
        _detect_remote_moves(ctx, dest_parent)
        complete = _sync_dir(source, dest_parent, ctx)
        if not ctx.dry_run:
            _backfill_ids(ctx, dest_parent)
        return complete


_CONFLICT_TEXT = {
    "local-same": "same local folder as {o}",
    "local-parent": "its local folder contains the one of {o}",
    "local-child": "its local folder is inside the one of {o}",
    "arrival-same": "same Proton folder as {o}: {d}",
    "arrival-inside": "its Proton folder is inside the one of {o}: {d}",
    "arrival-contains": "its Proton folder contains the one of {o}: {d}",
}


def plan(sync_mappings, upload_mappings):
    """Split the ``sync_mappings`` entries into (runnable, skipped).

    skipped is a list of (mapping, log line). Nothing here runs an entry: an
    unknown direction or type, or an overlap with another mapping, only
    produces a line. Checked on every load of the file."""
    import mapping_keys
    skipped, ok = [], []
    for m in sync_mappings:
        if not isinstance(m, dict):
            skipped.append((m, _("Two-way entry skipped: not a mapping object")))
        elif m.get("direction") not in mapping_keys.SYNC_DIRECTIONS:
            skipped.append((m, _("Sync mapping skipped: unknown direction {d!r}: {s}")
                            .format(d=m.get("direction"), s=m.get("source", ""))))
        elif m.get("type") not in mapping_keys.SYNC_TYPES:
            skipped.append((m, _("Sync mapping skipped: unknown type {t!r}: {s}")
                            .format(t=m.get("type"), s=m.get("source", ""))))
        elif not m.get("source") or not m.get("dest_parent"):
            skipped.append((m, _("Sync mapping skipped: source or destination missing: {s}")
                            .format(s=m.get("source", ""))))
        else:
            ok.append(m)
    conflicts = mapping_keys.sync_mapping_conflicts(ok, upload_mappings)
    runnable = []
    for i, m in enumerate(ok):
        hit = conflicts.get(i)
        if hit:
            reason, other, detail = hit
            why = _(_CONFLICT_TEXT[reason]).format(o=other.get("source", "?"), d=detail)
            skipped.append((m, _("Two-way mapping not run: {s} ({w})")
                            .format(s=m["source"], w=why)))
        else:
            runnable.append(m)
    return runnable, skipped


def run_pass(sync_mappings, upload_mappings, config_path, cache, global_ex,
             only_source=None, trigger_name="none", runner=None, dry_run=False,
             verbose=False, allow_mass_delete=False, delete=False):
    """Run the two-way pass of one engine run. Returns a list of
    (source, complete, unreadable) for the health report.

    ``runner`` is a trigger's own function; None means no events probe, so
    the whole Proton side is listed (``sync_mapping``). ``upload_mappings`` is
    the full ``mappings`` list, for the overlap check."""
    if runner is None and trigger_name != "none":
        print(_("Two-way trigger {t!r} unknown: listing the whole Proton side")
              .format(t=trigger_name))
    runnable, skipped = plan(sync_mappings, upload_mappings)
    for _skipped, line in skipped:
        print("  \u23ed " + line)
    if only_source:
        wanted = {os.path.normpath(s) for s in only_source}
        runnable = [m for m in runnable
                    if os.path.normpath(m["source"]) in wanted]
    out = []
    for m in runnable:
        print(_("\n\u25b6 Two-way mapping: {s}  =>  {d}").format(
            s=m["source"], d=m["dest_parent"]))
        _ps._RUN.mappings_total += 1
        if not os.path.exists(m["source"]):
            print(_("  \u274c Source not found, skipped: {s}").format(s=m["source"]))
            _ps._RUN.add("sources_missing")
            continue
        complete = (runner or sync_mapping)(
            m, config_path, cache, _ps.mapping_exclusions(m, global_ex),
            dry_run=dry_run, verbose=verbose, allow_mass_delete=allow_mass_delete,
            global_ex=global_ex, delete=delete)
        if complete:
            _ps._RUN.add("mappings_complete")
        out.append((m["source"], bool(complete), _ps._take_unreadable()))
        cache.save()
    return out


def sync_tree(mapping, local_dir, remote_parent, config_path, cache, exclusions,
              dry_run=False, verbose=False, allow_mass_delete=False, global_ex=None,
              delete=False):
    """Reconcile one folder of a twoway mapping (a full pass or a subpath)."""
    ctx = _context(mapping, config_path, cache, exclusions, dry_run,
                   verbose, allow_mass_delete,
                   source_root=mapping.get("source") or local_dir,
                   global_ex=global_ex, delete=delete)
    with ctx.db:
        return _sync_dir(local_dir, remote_parent, ctx)


class _Ctx:
    def __init__(self, mapping, db, cache, exclusions, dry_run, verbose,
                 opts, source_root, config_path, delete=False):
        self.mapping = mapping
        self.db = db
        self.cache = cache
        self.exclusions = exclusions
        self.dry_run = dry_run
        self.verbose = verbose
        self.opts = opts
        self.source_root = source_root
        self.config_path = config_path
        self.delete = bool(delete)
        # Remote listings read by the move detection, reused by _sync_dir.
        self.prelisted = {}


def _context(mapping, config_path, cache, exclusions, dry_run, verbose,
             allow_mass_delete, source_root, global_ex=None, delete=False):
    opts = _ps.build_delete_opts(
        mapping, source_root, global_ex=global_ex,
        allow_mass_delete=allow_mass_delete, verbose=verbose)
    db = syncdb.SyncDB(syncdb.database_path(config_path))
    return _Ctx(mapping, db, cache, exclusions, dry_run, verbose, opts,
                source_root, config_path, delete=delete)


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
    """Remote directory this local directory lists."""
    parent = (remote_parent or "").rstrip("/")
    name = os.path.basename(os.path.normpath(local_dir))
    return parent + "/" + name if parent else "/" + name


def _sync_dir(local_dir, remote_parent, ctx, remote_info=None):
    """List this folder even when the one-way fingerprint is unchanged."""
    remote_folder = _remote_folder(local_dir, remote_parent, ctx)
    print("📂 " + local_dir)
    if not ctx.dry_run and not _ps.ensure_remote_path(remote_folder):
        return False
    listing = ctx.prelisted.pop(remote_folder, None)
    if listing is None:
        listing = _ps.get_remote_listing(remote_folder, verbose=ctx.verbose)
    if not listing.ok:
        print("[list-skipped] " + _(
            "Could not list {p} — folder skipped this pass "
            "(nothing sent, nothing deleted).").format(p=remote_folder))
        _ps._RUN.add("folders_listing_failed")
        return False
    _remember_folder(local_dir, remote_folder, remote_info, ctx)

    try:
        entries = list(os.scandir(local_dir))
    except OSError as exc:
        _ps._note_unreadable(local_dir, exc)
        return False

    local_names = set()
    dir_failed = False
    all_children = True
    gone_dirs = _folders_gone_on_proton(entries, listing, ctx)
    if gone_dirs and not _handle_folders_gone_on_proton(
            gone_dirs, listing, remote_folder, ctx):
        dir_failed = True
    for entry in entries:
        if ctx.exclusions and ctx.exclusions.is_excluded(entry.name):
            continue
        local_names.add(entry.name)
        if _is_conflict_copy(entry.name):
            continue
        if entry.path in gone_dirs:
            continue
        if entry.is_dir(follow_symlinks=False):
            if not _sync_dir(entry.path, remote_folder, ctx,
                             listing.get(entry.name)):
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


def _folders_gone_on_proton(entries, listing, ctx):
    """Local folders the baseline saw on Proton that Proton no longer lists.

    A folder with files edited or added here since the baseline is not in
    the result: the newer edit wins, so it is synced as a normal folder and
    recreated on Proton. Returns {local path: remote path}.
    """
    gone = {}
    for entry in entries:
        if not entry.is_dir(follow_symlinks=False):
            continue
        if ctx.exclusions and ctx.exclusions.is_excluded(entry.name):
            continue
        if listing.get(entry.name) is not None:
            continue
        base = ctx.db.get_folder(entry.path)
        if not base or not base.get("remote_seen"):
            continue
        if _local_tree_changed(entry.path, ctx):
            print("[restore] " + _(
                "folder removed on Proton but changed here since, sending it "
                "again: {p}").format(p=entry.path))
            continue
        gone[entry.path] = base.get("remote_path") or ""
    return gone


def _local_tree_changed(local_dir, ctx):
    """True when anything under this folder is new or edited since the baseline."""
    for parent, dirs, files in os.walk(local_dir):
        dirs[:] = [d for d in dirs
                   if not (ctx.exclusions and ctx.exclusions.is_excluded(d))]
        for name in dirs:
            if not ctx.db.get_folder(os.path.join(parent, name)):
                return True
        for name in files:
            if ctx.exclusions and ctx.exclusions.is_excluded(name):
                continue
            path = os.path.join(parent, name)
            row = ctx.db.get(path)
            if (not row or row.get("state") != "synced"
                    or _ps._local_differs_from_row(path, row) is not False):
                return True
    return False


def _handle_folders_gone_on_proton(gone_dirs, listing, remote_folder, ctx):
    """Move aside local folders that were removed on Proton. True when clean.

    Same gates as a file removed on Proton: only on a pass with ``--delete``,
    after the mount check and the mass-delete guard. Nothing is deleted, the
    folder goes to the holding folder, and nothing recreates it on Proton.
    """
    if not ctx.delete:
        for path in gone_dirs:
            print("[kept] " + _(
                "folder removed on Proton; local folder kept because "
                "deletions are off for this pass: {p}").format(p=path))
        return True
    if not _mount_ok(ctx, _("local folder kept")):
        return False
    if _refusing_mass_delete(list(gone_dirs), list(listing) + list(gone_dirs), ctx):
        print("[delete-guard] " + _(
            "refusing to move aside {n} of {t} folder(s) in {p}").format(
                n=len(gone_dirs), t=len(listing) + len(gone_dirs), p=remote_folder))
        _ps._RUN.add("deletions_refused")
        return False
    ok = True
    for path in gone_dirs:
        if _hold(path, ctx):
            if not ctx.dry_run:
                ctx.db.delete_folder_tree(path)
        else:
            ok = False
    return ok


def _remote_tree_changed(remote_path, local_path, ctx):
    """True when Proton holds anything new or edited below this folder.

    A listing that fails counts as changed: nothing is trashed on a guess.
    """
    listing = _ps.get_remote_listing(remote_path, verbose=ctx.verbose)
    if not listing.ok:
        return True
    for name, info in listing.items():
        if ctx.exclusions and ctx.exclusions.is_excluded(name):
            continue
        child_local = os.path.join(local_path, name)
        child_remote = remote_path.rstrip("/") + "/" + name
        rtype = info.get("type") if isinstance(info, dict) else None
        if rtype == "folder":
            if (not ctx.db.get_folder(child_local)
                    or _remote_tree_changed(child_remote, child_local, ctx)):
                return True
        elif rtype in _DOC_TYPES:
            continue
        else:
            row = ctx.db.get(child_local)
            if (not row or row.get("state") != "synced"
                    or _remote_changed_since(info, row) is not False):
                return True
    return False


def _remember_folder(local_dir, remote_folder, remote_info, ctx):
    """Baseline row for a folder seen on both sides."""
    if ctx.dry_run:
        return
    node_id = remote_info.get("node_id") if isinstance(remote_info, dict) else None
    if not node_id:
        known = ctx.db.get_folder(local_dir)
        node_id = known.get("remote_node_id") if known else None
    ctx.db.upsert_folder({
        "local_path": local_dir,
        "remote_path": remote_folder,
        "remote_node_id": node_id,
        "local_seen": 1,
        "remote_seen": 1,
    })


def _remote_only(local_dir, remote_folder, listing, local_names, ctx):
    gone = []
    folders_gone = []
    restores = []
    ok = True
    for name, info in listing.items():
        if name in local_names:
            continue
        if ctx.exclusions and ctx.exclusions.is_excluded(name):
            if _ps._keep_excluded_remote(name, ctx.opts):
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
            base = ctx.db.get_folder(local_path)
            if base and base.get("local_seen"):
                if _remote_tree_changed(remote_path, local_path, ctx):
                    print("[restore] " + _(
                        "folder removed here but changed on Proton since, "
                        "downloading it again: {p}").format(p=local_path))
                else:
                    folders_gone.append((local_path, remote_path))
                    continue
            if not ctx.dry_run:
                os.makedirs(local_path, exist_ok=True)
            if not _sync_dir(local_path, remote_folder, ctx, info):
                ok = False
            continue
        if rtype in _DOC_TYPES:
            _mark_document(local_path, remote_path, info, ctx)
            continue
        row = ctx.db.get(local_path)
        if row and row.get("state") == "synced":
            if _remote_changed_since(info, row) is False:
                gone.append((local_path, remote_path, info, row))
            else:
                # Removed here, but the Proton copy changed after the last
                # sync, or the listing cannot tell. The newer copy comes back.
                print("[restore] " + _(
                    "deleted here but changed on Proton since, downloading "
                    "it again: {p}").format(p=local_path))
                restores.append((local_path, remote_path, info))
        elif row and row.get("state") == "conflict":
            # The original was removed during a conflict. The Proton version
            # comes back under the original name; any conflict copy stays.
            restores.append((local_path, remote_path, info))
        else:
            restores.append((local_path, remote_path, info))

    if _refusing_mass_delete(gone + folders_gone, listing, ctx):
        print("[delete-guard] " + _(
            "refusing to trash {n} of {t} remote item(s) in {p}").format(
                n=len(gone), t=len(listing), p=remote_folder))
        _ps._RUN.add("deletions_refused")
        for local_path, remote_path, info, row in gone:
            _set_state(row, "pending-down", ctx)
        return False

    for local_path, remote_path in folders_gone:
        if _can_trash(ctx, remote_path):
            if _ps.remote_trash(
                    remote_path, permanent=False, dry_run=ctx.dry_run):
                if not ctx.dry_run:
                    ctx.db.delete_folder_tree(local_path)
            else:
                ok = False
        else:
            print("[kept] " + _(
                "folder removed here; Proton folder kept because deletions "
                "are off for this pass: {p}").format(p=remote_path))
            if ctx.opts.get("mount_lost"):
                ok = False

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
        return _resolve_conflict(local_path, remote_folder, remote_info, row, ctx)

    if not isinstance(remote_info, dict) or remote_info.get("type") not in (None, "file"):
        if row and row.get("state") == "synced":
            return _remote_gone(local_path, remote_folder, remote_info, row, ctx)
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
        fetched, skipped, reason = _fetch(remote_path, temporary)
        if skipped:
            _mark_document(local_path, remote_path, remote_info, ctx)
            return True
        if fetched is None:
            _download_failed(local_path, reason)
            return False
        os.replace(fetched, local_path)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    print("[download] " + _("downloaded {p}").format(p=local_path))
    _save_synced(local_path, remote_path, remote_info, ctx)
    return True


def _fetch(remote_path, directory):
    """Return (local path or None, skipped_document, reason).

    ``directory`` is a fresh, empty folder. The CLI normally writes the file
    under its remote name; if it picked another name, the one file it wrote
    is used. ``reason`` is the CLI's own message when nothing usable came
    back.
    """
    result = _ps.run_cli(
        ["filesystem", "download", "-f", "replace", remote_path, directory])
    text = (result.stdout or "") + "\n" + (result.stderr or "")
    if "skipped:" in text:
        return None, True, ""
    if result.returncode != 0:
        return None, False, _cli_reason(result)
    name = os.path.basename(remote_path.rstrip("/"))
    path = os.path.join(directory, name)
    if os.path.isfile(path):
        return path, False, ""
    written = []
    for parent, _dirs, files in os.walk(directory):
        written.extend(os.path.join(parent, f) for f in files)
    if len(written) == 1:
        return written[0], False, ""
    return None, False, _cli_reason(result) or _(
        "the Proton CLI finished but wrote {n} files instead of one").format(
            n=len(written))


def _cli_reason(result):
    """Last line the CLI printed on stderr, else stdout, kept short."""
    for stream in (result.stderr, result.stdout):
        lines = [line.strip() for line in (stream or "").splitlines() if line.strip()]
        if lines:
            reason = lines[-1]
            return reason if len(reason) <= 300 else reason[:297] + "..."
    return ""


def _download_failed(local_path, reason):
    if os.path.lexists(local_path):
        text = _("download failed, local file kept: {p}").format(p=local_path)
    else:
        text = _("could not download {p}").format(p=local_path)
    if reason:
        text += " — " + _("Proton CLI said: {r}").format(r=reason)
    print("[download-failed] " + text)
    _ps._RUN.add("files_failed")


def _write_conflict(local_path, remote_path, remote_info, row, ctx):
    """Keep both: the Proton version is saved next to the local file.

    Each copy gets a fresh name, so an older conflict copy is never
    overwritten.
    """
    if ctx.dry_run:
        print("[conflict] " + _(
            "[DRY-RUN] both sides changed, would keep both: {p}").format(p=local_path))
        return True
    parent = os.path.dirname(local_path) or "."
    temporary = tempfile.mkdtemp(prefix=".proton-sync-download-", dir=parent)
    try:
        fetched, skipped, reason = _fetch(remote_path, temporary)
        if skipped:
            _mark_document(local_path, remote_path, remote_info, ctx)
            return True
        if fetched is None:
            _download_failed(local_path, reason)
            return False
        conflict_path = _conflict_path(local_path)
        os.replace(fetched, conflict_path)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    print("[conflict] " + _(
        "both sides changed. Your file is kept; the Proton version is saved "
        "as {c}").format(c=conflict_path))
    _conflict_help(local_path)
    _mark_conflict(local_path, remote_path, remote_info, row, ctx)
    return True


def _conflict_help(local_path):
    print("[conflict] " + _(
        "To finish: keep the version you want under the name {n} and delete "
        "the \"(proton conflict)\" copy. The next pass sends your choice to "
        "Proton.").format(n=os.path.basename(local_path)))


def _resolve_conflict(local_path, remote_folder, remote_info, row, ctx):
    """Finish a conflict once the person has picked a version.

    The row holds the Proton version from when the conflict was found.
    Nothing on Proton is replaced while a conflict copy is still here.
    """
    remote_path = remote_folder.rstrip("/") + "/" + os.path.basename(local_path)
    if not isinstance(remote_info, dict) or remote_info.get("type") not in (None, "file"):
        # The Proton copy is gone. The local file is the only one left.
        print("[conflict-resolved] " + _(
            "no Proton copy any more, sending yours: {p}").format(p=local_path))
        return _upload(local_path, remote_folder, remote_info, ctx)
    remote_sha = _ps._optional_sha1(remote_info.get("sha1"))
    if remote_sha:
        try:
            same = _ps._local_sha1(local_path) == remote_sha
        except OSError:
            same = False
        if same:
            print("[conflict-resolved] " + _(
                "both versions are the same now: {p}").format(p=local_path))
            if not ctx.dry_run:
                _save_synced(local_path, remote_path, remote_info, ctx)
            return True
    if _conflict_copies(local_path):
        print("[conflict] " + _(
            "waiting for you to choose a version: {p}").format(p=local_path))
        _conflict_help(local_path)
        return True
    if _remote_changed_since(remote_info, row) is False:
        print("[conflict-resolved] " + _(
            "conflict copy removed, sending your version: {p}").format(p=local_path))
        return _upload(local_path, remote_folder, remote_info, ctx)
    # Proton changed again after the conflict. Keep that version too.
    return _write_conflict(local_path, remote_path, remote_info, row, ctx)


def _remote_gone(local_path, remote_folder, remote_info, row, ctx):
    """The Proton copy was removed after the last sync.

    An edit made here since then wins and is sent again. An unchanged file
    is moved to the holding folder, never deleted, and only on a pass that
    allows deletions.
    """
    if _ps._local_differs_from_row(local_path, row) is not False:
        print("[restore] " + _(
            "removed on Proton but changed here since, sending it again: "
            "{p}").format(p=local_path))
        return _upload(local_path, remote_folder, remote_info, ctx)
    if not ctx.delete:
        print("[kept] " + _(
            "removed on Proton; local file kept because deletions are off "
            "for this pass: {p}").format(p=local_path))
        return True
    return _hold(local_path, ctx)


def _remote_changed_since(remote_info, row):
    """True, False, or None when the listing cannot tell."""
    if not isinstance(remote_info, dict) or not isinstance(row, dict):
        return None
    return _ps._remote_differs_from_row(
        _ps._claimed_size_of(remote_info),
        _ps._optional_sha1(remote_info.get("sha1")),
        _ps._remote_mtime_seconds(remote_info.get("mtime")),
        row)


def _hold(local_path, ctx):
    """Move the local file into the state directory. Do not delete the bytes."""
    if ctx.dry_run:
        print("[held] " + _("[DRY-RUN] would move aside: {p}").format(p=local_path))
        return True
    dest = _holding_destination(ctx, local_path)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    # A file held earlier under the same name is never replaced.
    base, n = dest, 1
    while os.path.lexists(dest):
        dest = base + (".kept" if n == 1 else ".kept%d" % n)
        n += 1
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
    # Two switches, as for one-way mappings: the pass's --delete and the
    # mapping's allow_delete.
    if not ctx.delete or not ctx.mapping.get("allow_delete"):
        return False
    if (str(remote_path).startswith("/shared-with-me")
            and ctx.mapping.get("shared_delete_confirmed") is not True):
        return False
    return _mount_ok(ctx, _("remote file kept"))


def _mount_ok(ctx, kept):
    """The mount check shared by every deletion. A refusal holds for the pass."""
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
        "mount check failed, {k}: {r}").format(k=kept, r=reason))
    _ps._RUN.add("deletions_refused")
    return False


def _refusing_mass_delete(gone, listing, ctx):
    if not gone or ctx.opts.get("allow_mass_delete"):
        return False
    if not ctx.opts.get("mass_delete_guard"):
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
    if not node_id:
        known = ctx.db.get(local_path)
        node_id = known.get("remote_node_id") if known else None
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
    """The row remembers the Proton version that was saved as the copy.

    A later pass compares the listing with it. Unchanged means the person's
    choice can be sent. Changed means Proton moved on and gets a new copy.
    """
    info = remote_info if isinstance(remote_info, dict) else {}
    try:
        st = os.stat(local_path)
        inode, mtime = st.st_ino, st.st_mtime
    except OSError:
        inode, mtime = None, None
    ctx.db.upsert({
        "local_path": local_path,
        "remote_path": remote_path,
        "remote_node_id": info.get("node_id") or (row or {}).get("remote_node_id"),
        "sha1": _ps._optional_sha1(info.get("sha1")),
        "claimed_size": _ps._claimed_size_of(info),
        "claimed_mtime": _ps._remote_mtime_seconds(info.get("mtime")),
        "local_inode": inode,
        "local_mtime": mtime,
        "state": "conflict",
    })


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
    """A conflict-copy name that is not in use yet."""
    directory = os.path.dirname(local_path)
    stem, ext = os.path.splitext(os.path.basename(local_path))
    candidate = os.path.join(directory, stem + _CONFLICT_MARK + ext)
    number = 2
    while os.path.lexists(candidate):
        candidate = os.path.join(
            directory, "{s} (proton conflict {n}){e}".format(s=stem, n=number, e=ext))
        number += 1
    return candidate


def _is_conflict_copy(name):
    stem, _ext = os.path.splitext(name)
    return bool(_CONFLICT_STEM.search(stem))


def _conflict_copies(local_path):
    """Conflict copies of this file that are still in its folder."""
    directory = os.path.dirname(local_path) or "."
    stem, ext = os.path.splitext(os.path.basename(local_path))
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    found = []
    for name in names:
        other_stem, other_ext = os.path.splitext(name)
        if other_ext != ext or not _is_conflict_copy(name):
            continue
        if _CONFLICT_STEM.sub("", other_stem) == stem:
            found.append(os.path.join(directory, name))
    return sorted(found)


# --- renames and moves -------------------------------------------------------
#
# A rename or move is applied as a rename or move on the other side, never as
# a transfer plus a deletion. No events cursor is kept: each pass compares the
# baseline rows (node id, inode, checksum) with what both sides show now.

def _remote_root(ctx, dest_parent):
    return _remote_folder(ctx.source_root, dest_parent, ctx)


def _under(path, root):
    root = root.rstrip(os.sep)
    return path == root or path.startswith(root + os.sep)


def _local_for(ctx, dest_parent, remote_path):
    """Local path of a remote path inside the mapping, or None when outside."""
    root = _remote_root(ctx, dest_parent).rstrip("/")
    if remote_path == root:
        return ctx.source_root
    if not remote_path.startswith(root + "/"):
        return None
    rest = remote_path[len(root) + 1:]
    return os.path.join(ctx.source_root, *rest.split("/"))


def _remote_for(ctx, dest_parent, local_path):
    rel = os.path.relpath(local_path, ctx.source_root)
    root = _remote_root(ctx, dest_parent).rstrip("/")
    if rel == ".":
        return root
    return root + "/" + "/".join(rel.split(os.sep))


def _mapping_rows(ctx):
    files = [r for r in ctx.db.rows()
             if _under(r["local_path"], ctx.source_root) and r["state"] == "synced"]
    folders = [r for r in ctx.db.folders()
               if _under(r["local_path"], ctx.source_root)
               and r["local_path"].rstrip(os.sep) != ctx.source_root.rstrip(os.sep)]
    return files, folders


def _walk_remote(ctx, dest_parent):
    """({node_id: (path, type, info)}, ok) for the whole remote tree; the listings
    read on the way are kept in ctx.prelisted for _sync_dir."""
    found = {}
    pending = [_remote_root(ctx, dest_parent)]
    listings = {}
    while pending:
        folder = pending.pop()
        listing = _ps.get_remote_listing(folder, verbose=ctx.verbose)
        listings[folder] = listing  # a failed one too: _sync_dir reports it
        if not listing.ok:
            ctx.prelisted.update(listings)
            return None
        for name, info in listing.items():
            path = folder.rstrip("/") + "/" + name
            kind = info.get("type")
            if info.get("node_id"):
                found[info["node_id"]] = (path, kind, info)
            if kind == "folder":
                pending.append(path)
    ctx.prelisted.update(listings)
    return found


def _detect_remote_moves(ctx, dest_parent):
    """A node id now at another remote path: rename or move the local copy."""
    files, folders = _mapping_rows(ctx)
    if not any(r.get("remote_node_id") for r in files + folders):
        return
    nodes = _walk_remote(ctx, dest_parent)
    if nodes is None:
        return
    for row in sorted(folders, key=lambda r: r["local_path"].count(os.sep)):
        row = ctx.db.get_folder(row["local_path"]) or row
        seen = nodes.get(row.get("remote_node_id"))
        if not seen or seen[1] != "folder" or seen[0] == row["remote_path"]:
            continue
        _move_local(row, seen[0], True, ctx, dest_parent)
    files, _folders = _mapping_rows(ctx)
    for row in files:
        seen = nodes.get(row.get("remote_node_id"))
        if not seen or seen[1] != "file" or seen[0] == row["remote_path"]:
            continue
        if _remote_changed_since(seen[2], row) is not False:
            continue  # content differs: the normal reconcile decides
        _move_local(row, seen[0], False, ctx, dest_parent)


def _move_local(row, new_remote, is_dir, ctx, dest_parent):
    new_local = _local_for(ctx, dest_parent, new_remote)
    old_local = row["local_path"]
    if new_local is None or not os.path.lexists(old_local):
        return False  # moved out of the tree, or gone here: deletion gates apply
    if os.path.lexists(new_local):
        return False
    print("↪ " + _("moved on Proton, moving here too: {a} -> {b}").format(
        a=old_local, b=new_local))
    if ctx.dry_run:
        return True
    try:
        os.makedirs(os.path.dirname(new_local), exist_ok=True)
        os.rename(old_local, new_local)
    except OSError as exc:
        print("❌ " + _("local move failed: {e}").format(e=exc))
        return False
    if is_dir:
        ctx.db.move_tree(old_local, new_local, row["remote_path"], new_remote)
    else:
        try:
            inode = os.stat(new_local).st_ino
        except OSError:
            inode = None
        ctx.db.move_file_row(old_local, new_local, new_remote, inode=inode)
    return True


def _backfill_ids(ctx, dest_parent):
    """Fill in node ids the baseline lacks (an upload does not return one)."""
    files, folders = _mapping_rows(ctx)
    missing = [r for r in files + folders if not r.get("remote_node_id")]
    if not missing:
        return
    nodes = _walk_remote(ctx, dest_parent)
    ctx.prelisted.clear()
    if nodes is None:
        return
    by_path = {path: (nid, kind) for nid, (path, kind, _i) in nodes.items()}
    for row in files:
        seen = by_path.get(row["remote_path"])
        if not row.get("remote_node_id") and seen and seen[1] == "file":
            ctx.db.upsert(dict(row, remote_node_id=seen[0]))
    for row in folders:
        seen = by_path.get(row["remote_path"])
        if not row.get("remote_node_id") and seen and seen[1] == "folder":
            ctx.db.upsert_folder(dict(row, remote_node_id=seen[0]))


def _unrecorded_files(ctx):
    """{inode: path} of local files with no baseline row."""
    known = {r["local_path"] for r in ctx.db.rows()}
    found = {}
    for base, dirs, names in os.walk(ctx.source_root):
        dirs[:] = [d for d in dirs
                   if not (ctx.exclusions and ctx.exclusions.is_excluded(d))]
        for name in names:
            if (ctx.exclusions and ctx.exclusions.is_excluded(name)) \
                    or _is_conflict_copy(name):
                continue
            path = os.path.join(base, name)
            if path in known or os.path.islink(path):
                continue
            try:
                found[os.stat(path).st_ino] = path
            except OSError:
                continue
    return found


def _remote_relocate(old_remote, new_remote, ctx, dest_parent):
    """Move, then rename: never an upload. Returns True when the item is at
    new_remote."""
    old_parent, old_name = old_remote.rsplit("/", 1)
    new_parent, new_name = new_remote.rsplit("/", 1)
    current = old_remote
    if old_parent != new_parent:
        if not ctx.dry_run and not _ps.ensure_remote_path(new_parent):
            return False
        if not _ps.remote_move(current, new_parent or "/", dry_run=ctx.dry_run):
            return False
        current = (new_parent.rstrip("/") + "/" + old_name)
    if old_name != new_name:
        if not _ps.remote_rename(current, new_name, dry_run=ctx.dry_run):
            return False
    return True


def _detect_local_moves(ctx, dest_parent):
    """A synced file or folder that vanished here while the same inode and
    checksum appear under a new name: rename or move it on Proton."""
    files, _folders = _mapping_rows(ctx)
    vanished = [r for r in files if not os.path.lexists(r["local_path"])]
    if not vanished:
        return
    fresh = _unrecorded_files(ctx)
    if not fresh:
        return
    matched = {}
    for row in vanished:
        path = fresh.get(row.get("local_inode"))
        if path is None or not row.get("sha1"):
            continue
        try:
            if _ps._local_sha1(path) != row["sha1"]:
                continue
        except OSError:
            continue
        matched[row["local_path"]] = path
    # A folder renamed or moved: every synced file below it reappears at the
    # same relative place under one new folder.
    folder_rows = sorted(
        (r for r in ctx.db.folders()
         if _under(r["local_path"], ctx.source_root)
         and r["local_path"].rstrip(os.sep) != ctx.source_root.rstrip(os.sep)
         and not os.path.lexists(r["local_path"])),
        key=lambda r: r["local_path"].count(os.sep))
    for frow in folder_rows:
        old = frow["local_path"]
        if ctx.db.get_folder(old) is None:
            continue  # already moved with a parent
        below = [r for r in files if _under(r["local_path"], old)]
        if not below or any(r["local_path"] not in matched for r in below):
            continue
        first = below[0]["local_path"]
        rel = os.path.relpath(first, old)
        target = matched[first]
        if not target.endswith(os.sep + rel):
            continue
        new = target[:-(len(rel) + 1)]
        if os.path.lexists(old) or not os.path.isdir(new) \
                or ctx.db.get_folder(new) is not None:
            continue
        if any(matched[r["local_path"]] != os.path.join(
                new, os.path.relpath(r["local_path"], old)) for r in below):
            continue
        new_remote = _remote_for(ctx, dest_parent, new)
        print("↪ " + _("renamed or moved here, applying on Proton: {a} -> {b}")
              .format(a=old, b=new))
        if not _remote_relocate(frow["remote_path"], new_remote, ctx, dest_parent):
            continue
        if not ctx.dry_run:
            ctx.db.move_tree(old, new, frow["remote_path"], new_remote)
        for r in below:
            matched.pop(r["local_path"], None)
    files = [r for r in files if r["local_path"] in matched]
    for row in files:
        new = matched[row["local_path"]]
        if ctx.db.get(row["local_path"]) is None:
            continue
        new_remote = _remote_for(ctx, dest_parent, new)
        print("↪ " + _("renamed or moved here, applying on Proton: {a} -> {b}")
              .format(a=row["local_path"], b=new))
        if not _remote_relocate(row["remote_path"], new_remote, ctx, dest_parent):
            continue
        if not ctx.dry_run:
            ctx.db.move_file_row(row["local_path"], new, new_remote,
                                 inode=os.stat(new).st_ino)
