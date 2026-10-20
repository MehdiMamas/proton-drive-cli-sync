"""Two-way reconcile for one entry of the ``twoway_mappings`` key.

Entries of ``mappings`` stay one-way and never reach this module. Downloads go through the engine's ``run_cli``. A failed
download does not replace the local file and does not rewrite its sync row.
A failed remote listing does not update the sync database for that folder.
"""

import json
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass

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
        _detect_remote_moves(ctx)
        complete = _sync_dir(source, mapping.get("dest_parent") or "", ctx)
        if not ctx.dry_run:
            _backfill_ids(ctx)
        return complete


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
        # Reconcile one folder only: known sub-folders are left to their own
        # events (the events trigger sets this).
        self.shallow = False
        # Listings the move detection already read: {remote folder: listing}.
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
    _detect_local_renames(entries, local_dir, ctx)
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
            if (ctx.shallow and listing.get(entry.name) is not None
                    and ctx.db.get_folder(entry.path)):
                continue
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
    if ctx.cache is not None and not ctx.dry_run and complete and not ctx.shallow:
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
        # A reconcile that did not list the parent keeps the id it knew.
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


# ---------------------------------------------------------------------------
# Remote moves and renames, local renames (#17 sections 1 and 3)
# ---------------------------------------------------------------------------

def _remote_root(ctx):
    return _remote_folder(ctx.source_root, ctx.mapping.get("dest_parent") or "", ctx)


def _local_for(remote_path, ctx):
    """Local path of a remote path under the mapped tree."""
    rel = remote_path[len(_remote_root(ctx)):].strip("/")
    if not rel:
        return ctx.source_root
    return os.path.join(ctx.source_root, *rel.split("/"))


def _walk_remote(ctx):
    """Every node of the mapped remote tree: ({id: (path, type)}, {path: (id, type)}).

    Returns None when a listing failed, so callers do nothing on a partial view."""
    by_id, by_path = {}, {}
    todo = [_remote_root(ctx)]
    while todo:
        folder = todo.pop()
        listing = _ps.get_remote_listing(folder, verbose=ctx.verbose)
        ctx.prelisted[folder] = listing
        if not listing.ok:
            return None
        for name, info in listing.items():
            if ctx.exclusions and ctx.exclusions.is_excluded(name):
                continue
            path = folder.rstrip("/") + "/" + name
            rtype = info.get("type") if isinstance(info, dict) else None
            node_id = info.get("node_id") if isinstance(info, dict) else None
            if node_id:
                by_id[node_id] = (path, rtype)
            by_path[path] = (node_id, rtype)
            if rtype == "folder":
                todo.append(path)
    return by_id, by_path


def _detect_remote_moves(ctx):
    """Apply remote renames and moves found by node id (full pass)."""
    prefix = ctx.source_root.rstrip(os.sep) + os.sep
    mine = [r for r in list(ctx.db.folders()) + list(ctx.db.rows())
            if r.get("remote_node_id") and r["local_path"].startswith(prefix)]
    if not mine:
        return
    walked = _walk_remote(ctx)
    if walked is None:
        return
    by_id = walked[0]
    if _apply_moves(ctx, lambda node_id: by_id.get(node_id)):
        ctx.prelisted.clear()  # paths changed, list again


def _apply_moves(ctx, where):
    """Move local folders, then files, whose baseline node is somewhere else.

    ``where(node_id)`` gives the node's current (remote path, type) or None."""
    skipped = set()
    moved = False
    while True:
        pending = []
        for row in ctx.db.folders():
            if row["local_path"] == ctx.source_root or row["local_path"] in skipped:
                continue
            found = where(row.get("remote_node_id")) if row.get("remote_node_id") else None
            if found and found[1] == "folder" and found[0] != row["remote_path"]:
                pending.append((row, found[0]))
        if not pending:
            break
        pending.sort(key=lambda item: item[0]["remote_path"].count("/"))
        row, new_remote = pending[0]
        if _move_local(row, new_remote, True, ctx):
            moved = True
        else:
            skipped.add(row["local_path"])
        if ctx.dry_run:
            skipped.update(r["local_path"] for r, _n in pending)
    for row in ctx.db.rows():
        node_id = row.get("remote_node_id")
        if not node_id or row.get("state") != "synced":
            continue
        found = where(node_id)
        if found and found[1] == "file" and found[0] != row["remote_path"]:
            if _move_local(row, found[0], False, ctx):
                moved = True
    return moved


def _move_local(row, new_remote, is_folder, ctx):
    old_local = row["local_path"]
    new_local = _local_for(new_remote, ctx)
    if not os.path.lexists(old_local):
        return False
    if os.path.lexists(new_local):
        print("[move-skipped] " + _(
            "{o} moved on Proton but {n} already exists here, left for the "
            "normal reconcile.").format(o=old_local, n=new_local))
        return False
    print("[moved] " + _("{o} -> {n} (moved on Proton)").format(
        o=old_local, n=new_local))
    if ctx.dry_run:
        return True
    try:
        os.makedirs(os.path.dirname(new_local), exist_ok=True)
        os.rename(old_local, new_local)
    except OSError as exc:
        print("[move-skipped] " + _("Could not move {o}: {e}").format(
            o=old_local, e=exc))
        return False
    if is_folder:
        ctx.db.move_tree(old_local, new_local, row["remote_path"], new_remote)
    else:
        try:
            inode = os.stat(new_local).st_ino
        except OSError:
            inode = None
        ctx.db.move_file_row(old_local, new_local, new_remote, inode)
    return True


def _backfill_ids(ctx):
    """Fill in the node ids the uploads could not know, so renames are found."""
    folders = ctx.db.folders()
    files = ctx.db.rows()
    missing = [r for r in folders + files if not r.get("remote_node_id")]
    if not missing:
        return
    walked = _walk_remote(ctx)
    ctx.prelisted.clear()
    if walked is None:
        return
    by_path = walked[1]
    for row in files:
        if row.get("remote_node_id"):
            continue
        found = by_path.get(row["remote_path"])
        if found and found[0] and found[1] == "file":
            stored = dict(row)
            stored["remote_node_id"] = found[0]
            ctx.db.upsert(stored)
    for row in folders:
        if row.get("remote_node_id"):
            continue
        if row["local_path"] == ctx.source_root:
            data, _err = _ps.cli_json(["filesystem", "info", row["remote_path"]])
            node_id = _ps._unwrap(data.get("uid")) if isinstance(data, dict) else None
        else:
            found = by_path.get(row["remote_path"])
            node_id = found[0] if found and found[1] == "folder" else None
        if node_id:
            stored = dict(row)
            stored["remote_node_id"] = node_id
            ctx.db.upsert_folder(stored)


def _detect_local_renames(entries, local_dir, ctx):
    """Log files renamed here: same inode and sha1 as a vanished baseline row.

    The CLI has no move command, so the new name goes up as a normal upload
    and the old remote copy leaves through the gated removal in _remote_only."""
    fresh = []
    for entry in entries:
        if (entry.is_file() and not entry.is_symlink()
                and ctx.db.get(entry.path) is None
                and not _is_conflict_copy(entry.name)):
            fresh.append(entry)
    if not fresh:
        return
    vanished = [r for r in ctx.db.rows()
                if os.path.dirname(r["local_path"]) == local_dir
                and r.get("state") == "synced" and r.get("local_inode")
                and not os.path.lexists(r["local_path"])]
    for entry in fresh:
        try:
            inode = entry.stat().st_ino
        except OSError:
            continue
        for row in vanished:
            if row.get("local_inode") != inode:
                continue
            try:
                same = _ps._local_sha1(entry.path) == row.get("sha1")
            except OSError:
                same = False
            if same:
                print("[renamed] " + _(
                    "{o} was renamed to {n} here, sending the new name; the "
                    "old copy on Proton goes through the deletion checks."
                ).format(o=os.path.basename(row["local_path"]), n=entry.name))
                break


# ---------------------------------------------------------------------------
# Events trigger
# ---------------------------------------------------------------------------

@dataclass
class ChangeEvent:
    event: str                 # created | modified | moved | removed
    node_id: str
    parent_id: str = None
    old_parent_id: str = None
    name: str = None
    type: str = "file"         # file | folder
    sha1: str = None


class ProbeError(Exception):
    pass


_EVENT_KINDS = ("created", "modified", "moved", "removed")


def parse_probe_output(text):
    """The one adapter from the probe's output to the event model.

    One JSON object per line. ``{"cursor": "..."}`` carries the cursor for
    the next run; any other line with an ``event`` and a ``node_id`` is a
    change. Malformed lines are skipped. Returns (events, cursor)."""
    events, cursor = [], None
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        if "cursor" in obj and "event" not in obj:
            if obj["cursor"] is not None:
                cursor = str(obj["cursor"])
            continue
        kind = obj.get("event")
        node_id = obj.get("node_id")
        if kind not in _EVENT_KINDS or not node_id:
            continue
        events.append(ChangeEvent(
            event=kind, node_id=str(node_id),
            parent_id=obj.get("parent_id"),
            old_parent_id=obj.get("old_parent_id"),
            name=obj.get("name"),
            type=obj.get("type") or "file",
            sha1=obj.get("sha1")))
    return events, cursor


def run_probe(cmd, cursor=None):
    """Run the configured probe; returns (events, cursor). Raises ProbeError."""
    try:
        argv = shlex.split(cmd)
    except ValueError as exc:
        raise ProbeError(str(exc))
    if not argv:
        raise ProbeError("empty probe command")
    if cursor:
        argv += ["--cursor", cursor]
    try:
        result = subprocess.run(argv, capture_output=True, text=True,
                                timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProbeError(str(exc))
    if result.returncode != 0:
        raise ProbeError("exit {c}: {e}".format(
            c=result.returncode, e=(result.stderr or "").strip()[:200]))
    return parse_probe_output(result.stdout)


def _cursor_key(mapping):
    return "twoway_cursor:" + (mapping.get("source") or "")


def _folder_by_id(ctx, node_id):
    if not node_id:
        return None
    for row in ctx.db.folders():
        if row.get("remote_node_id") == node_id:
            return row
    return None


def sync_events(mapping, config_path, cache, exclusions, dry_run=False,
                verbose=False, allow_mass_delete=False, global_ex=None,
                delete=False):
    """The "events" trigger: reconcile only what the probe reports changed."""
    cmd = _ps.appconfig.twoway_probe_cmd() if getattr(_ps, "_HAS_CONFIG", False) else ""
    kwargs = dict(dry_run=dry_run, verbose=verbose,
                  allow_mass_delete=allow_mass_delete, global_ex=global_ex,
                  delete=delete)
    if not cmd or mapping.get("type") == "file":
        return sync_mapping(mapping, config_path, cache, exclusions, **kwargs)
    key = _cursor_key(mapping)
    source = mapping.get("source") or ""
    meta = syncdb.SyncDB(syncdb.database_path(config_path))
    with meta:
        cursor = meta.get_meta(key)
        baseline = any(r["local_path"] == source for r in meta.folders())
    first = (not baseline or not cursor or bool(mapping.get("rescan")))
    try:
        events, new_cursor = run_probe(cmd, None if first else cursor)
    except ProbeError as exc:
        print("[probe-failed] " + _(
            "Event probe failed ({e}); two-way mapping skipped.").format(e=exc))
        return False

    if first:
        # Full listing: first run or explicit rescan. The cursor was taken
        # before it, so events during the listing are replayed next time.
        complete = sync_mapping(mapping, config_path, cache, exclusions, **kwargs)
        if complete and new_cursor and not dry_run:
            with syncdb.SyncDB(syncdb.database_path(config_path)) as db:
                db.set_meta(key, new_cursor)
        return complete

    ctx = _context(mapping, config_path, cache, exclusions, dry_run, verbose,
                   allow_mass_delete, source_root=source,
                   global_ex=global_ex, delete=delete)
    ctx.shallow = True
    with ctx.db:
        complete = _apply_events(events, ctx)
        if complete and new_cursor and not dry_run:
            ctx.db.set_meta(key, new_cursor)
    return complete


def _apply_events(events, ctx):
    affected = []
    for ev in events:
        if ev.event == "moved" and ev.name:
            _apply_moved_event(ev, ctx)
        for pid in (ev.parent_id, ev.old_parent_id):
            if pid and pid not in affected:
                affected.append(pid)
        if ev.type == "folder" and ev.event in ("modified", "created"):
            if ev.node_id not in affected:
                affected.append(ev.node_id)
    paths = []
    for pid in affected:
        row = _folder_by_id(ctx, pid)
        if row is not None:
            paths.append(row["local_path"])
    # Local edits in folders the probe did not report: the disk walk is cheap,
    # only the remote listings are not, and those stay limited to this set.
    paths.extend(sorted(_local_changed_folders(ctx)))
    complete = True
    done = set()
    for path in paths:
        row = _nearest_known_folder(path, ctx)
        if row is None or row["local_path"] in done:
            continue
        done.add(row["local_path"])
        parent = posixpath.dirname(row["remote_path"]) or "/"
        if not _sync_dir(row["local_path"], parent, ctx):
            complete = False
    return complete


def _nearest_known_folder(path, ctx):
    """Closest existing folder at or above `path` the baseline knows."""
    root = ctx.source_root
    while path:
        if os.path.isdir(path):
            row = ctx.db.get_folder(path)
            if row is not None:
                return row
        if path == root or len(path) <= len(root):
            return None
        path = os.path.dirname(path)
    return None


def _file_row_unchanged(path, row):
    """Size, mtime and inode against the baseline row; no hashing."""
    if row.get("state") != "synced":
        return False
    try:
        st = os.stat(path)
    except OSError:
        return False
    size, mtime = row.get("claimed_size"), row.get("local_mtime")
    if size is None or mtime is None:
        return False
    if st.st_size != size or float(st.st_mtime) != float(mtime):
        return False
    inode = row.get("local_inode")
    return not inode or st.st_ino == inode


def _local_changed_folders(ctx):
    """Folders under the mapping with a local change since the baseline.

    A new, edited, deleted or renamed file or folder puts its folder in the
    set, and for a rename both the old and the new parent."""
    root = ctx.source_root
    changed = set()
    seen_files, seen_dirs = set(), {root}
    excluded = ctx.exclusions.is_excluded if ctx.exclusions else (lambda n: False)
    for parent, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not excluded(d)]
        for name in dirs:
            path = os.path.join(parent, name)
            seen_dirs.add(path)
            if os.path.islink(path):
                continue
            if ctx.db.get_folder(path) is None:
                changed.add(parent)
                changed.add(path)
        for name in files:
            if excluded(name) or _is_conflict_copy(name):
                continue
            path = os.path.join(parent, name)
            seen_files.add(path)
            row = ctx.db.get(path)
            if row is None or not _file_row_unchanged(path, row):
                changed.add(parent)
    for row in ctx.db.rows():
        path = row["local_path"]
        if (path.startswith(root + os.sep) and path not in seen_files
                and not excluded(os.path.basename(path))):
            changed.add(os.path.dirname(path))
    for row in ctx.db.folders():
        path = row["local_path"]
        if (path.startswith(root + os.sep) and path not in seen_dirs
                and not excluded(os.path.basename(path))):
            changed.add(os.path.dirname(path))
    return changed


def _apply_moved_event(ev, ctx):
    parent = _folder_by_id(ctx, ev.parent_id)
    if parent is None:
        return  # moved out of the mapped tree: the old folder's reconcile removes it
    new_remote = parent["remote_path"].rstrip("/") + "/" + ev.name
    where = lambda node_id: (new_remote, ev.type) if node_id == ev.node_id else None
    _apply_moves(ctx, where)
