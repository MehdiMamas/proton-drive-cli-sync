"""Page Mappings : tableau, édition, journal et passes du moteur."""

import datetime
import os
import shlex
import threading

try:
    from i18n import _
except ImportError:
    def _(s):
        return s

from ui import document, run, widgets
from ui.pages.mapping_dialogs import ExclusionsDialog, MappingDialog


def _selected_rows(table):
    return sorted({item.row() for item in table.selectedItems()})


def _consumer_active():
    try:
        import realtime_manager
        _rc, out, _err = realtime_manager._run(
            ["systemctl", "--user", "is-active", realtime_manager.CONSUME_NAME])
    except Exception:
        return False
    return (out or "").strip() == "active"


class MappingsPage:
    """La page vit dans ``host``. Le document est celui de la fenêtre."""

    def __init__(self, host, window):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QCheckBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
            QTableWidget, QVBoxLayout,
        )
        self.window = window
        self.doc = window.doc
        self._control = run.PassControl()
        self._worker = None
        self._log_path = None
        self._Qt = Qt
        self._QTableWidget = QTableWidget
        root = QVBoxLayout(host)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        bar, bar_l = widgets.card(host)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.setContentsMargins(0, 0, 0, 0)
        self.open_btn = QPushButton(_("📂 Open…"))
        self.save_btn = QPushButton(_("💾 Save"))
        self.save_as_btn = QPushButton(_("💾 Save as…"))
        self.excl_btn = QPushButton(_("🌐 Global exclusions…"))
        for button, slot in (
            (self.open_btn, self.on_open),
            (self.save_btn, self.on_save),
            (self.save_as_btn, self.on_save_as),
            (self.excl_btn, self.on_global_exclusions),
        ):
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        bar_l.addLayout(row)
        self.excl_summary = QLabel("")
        self.excl_summary.setObjectName("Muted")
        bar_l.addWidget(self.excl_summary)
        root.addWidget(bar)

        table_card, table_l = widgets.card(host)
        def add_actions(labels):
            actions = QHBoxLayout()
            actions.setSpacing(8)
            actions.setContentsMargins(0, 0, 0, 0)
            for label, slot, name in labels:
                button = QPushButton(label)
                if name:
                    button.setObjectName(name)
                button.clicked.connect(slot)
                actions.addWidget(button)
            actions.addStretch(1)
            table_l.addLayout(actions)

        add_actions((
            (_("➕ Folder…"), lambda: self.on_add("folder"), None),
            (_("➕ File…"), lambda: self.on_add("file"), None),
            (_("Choose mapping…"), self.on_choose_mapping, None),
        ))
        add_actions((
            (_("✏ Edit"), self.on_edit, None),
            (_("🚫 Mapping exclusions"), self.on_mapping_exclusions, None),
            (_("🗑 Delete"), self.on_remove, "Danger"),
            (_("↪ Move to file…"), self.on_move, None),
        ))
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            _("Ready"), _("Type"), _("Deletion propagation"), _("Modified files"),
            _("Source (local)"),
            _("Destination (parent folder on Proton Drive)"),
            _("Mapping exclusions"),
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemDoubleClicked.connect(lambda *_a: self.on_edit())
        table_l.addWidget(self.table)
        root.addWidget(table_card, 1)

        out_card, out_l = widgets.card(host)
        out_l.addWidget(QLabel(_("Sync output")))
        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.verbose = QCheckBox(_("Verbose"))
        self.errors_only = QCheckBox(_("❗ Errors only"))
        clear = QPushButton(_("🧹 Clear output"))
        self.verbose.toggled.connect(self._refilter)
        self.errors_only.toggled.connect(self._refilter)
        clear.clicked.connect(self.output_clear)
        filters.addWidget(self.verbose)
        filters.addWidget(self.errors_only)
        filters.addWidget(clear)
        filters.addStretch(1)
        out_l.addLayout(filters)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(8000)
        out_l.addWidget(self.output)
        self.progress = QLabel("")
        self.progress.setObjectName("Muted")
        out_l.addWidget(self.progress)
        root.addWidget(out_card, 1)

        run_card, run_l = widgets.card(host)
        run_l.addWidget(QLabel(_("Manual sync")))
        opts = QHBoxLayout()
        opts.setSpacing(8)
        self.dry = QCheckBox(_("Test (dry-run)"))
        self.delete = QCheckBox(_("Propagate deletions"))
        self.sha1 = QCheckBox(_("SHA1 check"))
        opts.addWidget(self.dry)
        opts.addWidget(self.delete)
        opts.addWidget(self.sha1)
        opts.addStretch(1)
        run_l.addLayout(opts)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.prime_btn = QPushButton(_("🌱 Prime cache"))
        self.reset_btn = QPushButton(_("♻ Reset mapping"))
        self.copy_btn = QPushButton(_("📋 Copy command"))
        self.stop_btn = QPushButton(_("⏹ Stop"))
        self.stop_btn.setObjectName("Danger")
        self.stop_btn.setEnabled(False)
        self.run_btn = QPushButton(_("▶ Run sync"))
        self.run_btn.setObjectName("Primary")
        self.prime_btn.clicked.connect(self.on_prime)
        self.reset_btn.clicked.connect(self.on_reset)
        self.copy_btn.clicked.connect(self.on_copy)
        self.stop_btn.clicked.connect(self.on_stop)
        self.run_btn.clicked.connect(self.on_run)
        for button in (self.prime_btn, self.reset_btn, self.copy_btn):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.stop_btn)
        buttons.addWidget(self.run_btn)
        run_l.addLayout(buttons)
        root.addWidget(run_card)
        self._refresh()

    def on_show(self):
        self._refresh()

    def output_clear(self):
        self.output.clear()

    def _flags(self):
        self._control.verbose = self.verbose.isChecked()
        self._control.errors_only = self.errors_only.isChecked()

    def _append(self, text):
        self.output.insertPlainText(text)
        bar = self.output.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _refilter(self, *_a):
        self._flags()
        self.output.clear()
        path = self._log_path
        if not path or not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("@@PROGRESS"):
                        continue
                    shown = run.visible_text(
                        line, self._control.verbose, self._control.errors_only)
                    if shown:
                        self._append(shown)
        except OSError:
            pass

    def _busy(self, running):
        for button in (self.run_btn, self.prime_btn, self.reset_btn):
            button.setEnabled(not running)
        self.stop_btn.setEnabled(running)

    def _start(self, target):
        from PySide6.QtCore import QObject, QThread, Signal

        class _Bridge(QObject):
            text = Signal(str)
            status = Signal(str)
            progress = Signal(str)
            auth = Signal(bool)
            done = Signal()

        class _Job(QThread):
            def run(self_inner):
                try:
                    target()
                finally:
                    bridge.done.emit()

        bridge = _Bridge()
        bridge.text.connect(self._append)
        bridge.status.connect(self.window.set_status)
        bridge.progress.connect(self.progress.setText)
        bridge.auth.connect(self.window.set_auth)
        bridge.done.connect(lambda: self._busy(False))
        bridge.done.connect(self._refresh)
        bridge.done.connect(self._warn_unreadable)
        self._bridge = bridge
        self._flags()
        self._control.stop = False
        self._control.on_text = bridge.text.emit
        self._control.on_status = bridge.status.emit
        self._control.on_progress = bridge.progress.emit
        self._control.on_auth = bridge.auth.emit
        self._busy(True)
        self._worker = _Job()
        self._worker.start()

    def _warn_unreadable(self):
        paths = list(getattr(self._control, "unreadable", []) or [])
        if not paths:
            return
        shown = paths[:8]
        liste = "\n".join("  • " + p for p in shown)
        widgets.warn(
            self.window,
            _("{n} folder(s) could not be read.\n\n{list}\n\n"
              "What this means: the contents of these folders are NOT being "
              "backed up, and real-time is disabled for them. Everything else "
              "synced normally.\n\n"
              "This is almost always a permissions change at the source. Once "
              "the folders are readable again, prime the cache to clear it.")
            .format(n=len(paths), list=liste),
            _("Folders that could not be read"))

    def _selected_sources(self):
        rows = _selected_rows(self.table)
        if not rows:
            return None
        sources = []
        for row in rows:
            if 0 <= row < len(self.doc.mappings):
                src = self.doc.mappings[row].get("source")
                if src:
                    sources.append(src)
        return sources or None

    def _one_index(self):
        rows = _selected_rows(self.table)
        if not rows:
            widgets.info(self.window, _("First select a row in the list."), _("No selection"))
            return None
        if len(rows) > 1:
            widgets.info(
                self.window,
                _("Several mappings are selected. This action applies to "
                  "a single mapping — select just one row."),
                _("Single selection required"))
            return None
        return rows[0]

    def _refresh(self):
        from PySide6.QtWidgets import QTableWidgetItem
        cache = self.doc.cache_data()
        glob = self.doc.global_exclusions
        self.table.setRowCount(len(self.doc.mappings))
        try:
            import proton_sync
            revisions = bool(proton_sync.cli_supports_revisions())
        except Exception:
            revisions = False
        marks = {"ready": "●", "pending": "○", "na": "—"}
        for row, mapping in enumerate(self.doc.mappings):
            state = document.ready_state(mapping, cache, glob)
            if mapping.get("direction") == "twoway":
                kind = _("Two-way")
            else:
                kind = _("Folder") if mapping.get("type") == "folder" else _("File")
            if mapping.get("allow_delete"):
                deletion = "!" if mapping.get("delete_mode") == "permanent" else "🗑"
            else:
                deletion = ""
            if mapping.get("conflict_mode") == "revision":
                rev = "↺" if revisions else "!"
            else:
                rev = ""
            excl = mapping.get("exclusions") or {}
            n_names = len(excl.get("names", []) or [])
            n_pat = len(excl.get("patterns", []) or [])
            excl_txt = (_("{n} name(s), {m} pattern(s)").format(n=n_names, m=n_pat)
                        if n_names or n_pat else "—")
            values = [
                marks[state], kind, deletion, rev,
                mapping.get("source", ""), mapping.get("dest_parent", ""), excl_txt,
            ]
            for col, value in enumerate(values):
                item = self.table.item(row, col)
                if item is None:
                    item = QTableWidgetItem()
                    self.table.setItem(row, col, item)
                item.setText(value)
                item.setFlags(item.flags() & ~self._Qt.ItemIsEditable)
        names = ", ".join(self.doc.global_exclusions.get("names", []) or [])
        pats = ", ".join(self.doc.global_exclusions.get("patterns", []) or [])
        parts = []
        if names:
            parts.append(_("names: ") + names)
        if pats:
            parts.append(_("patterns: ") + pats)
        summary = " | ".join(parts) if parts else _("(none)")
        self.excl_summary.setText(_("🌐 Global exclusions — ") + summary)
        self.window.refresh_file_chip()
        self.window.refresh_direction_line()

    def _running(self):
        return self._worker is not None and self._worker.isRunning()

    def _need_file(self):
        if self.doc.path:
            return True
        widgets.info(self.window, _("Open or save a mappings file first."), _("No file"))
        return False

    def _need_engine(self):
        if os.path.exists(run.ENGINE):
            return True
        widgets.error(
            self.window, _("The engine was not found at:\n{p}").format(p=run.ENGINE),
            _("Engine not found"))
        return False

    def _offer_save(self, question):
        if not self.doc.dirty:
            return True
        if widgets.confirm(self.window, question, _("Save first?"), _("Save"), _("No")):
            return bool(self.on_save())
        return True

    def on_open(self):
        from PySide6.QtWidgets import QFileDialog
        path, _filt = QFileDialog.getOpenFileName(
            widgets.qt_parent(self.window), _("Open a mappings file"), "", "JSON (*.json)")
        if not path:
            return
        try:
            self.doc.load(path)
        except Exception as exc:
            widgets.error(self.window, str(exc), _("Load error"))
            return
        self._refresh()
        self.window.set_status(_("Loaded: {p} ({n} entries)").format(
            p=path, n=len(self.doc.mappings)))

    def on_save(self):
        if not self.doc.path:
            return self.on_save_as()
        try:
            path = self.doc.save()
        except Exception as exc:
            widgets.error(self.window, str(exc), _("Save error"))
            return False
        self._after_save(path)
        return True

    def on_save_as(self):
        from PySide6.QtWidgets import QFileDialog
        path, _filt = QFileDialog.getSaveFileName(
            widgets.qt_parent(self.window), _("Save the mappings file"), "mappings.json", "JSON (*.json)")
        if not path:
            return False
        try:
            self.doc.save(path)
        except Exception as exc:
            widgets.error(self.window, str(exc), _("Save error"))
            return False
        self._after_save(path)
        return True

    def _after_save(self, path):
        self.window.set_status(_("Saved: {p}").format(p=path))
        self.window.refresh_file_chip()
        base = os.path.basename(path)
        if not (base.startswith("mappings-") and base.endswith(".json")):
            return

        def work():
            try:
                import realtime_manager
                ok, msg = realtime_manager.push_mappings_to_nas(path)
            except Exception as exc:
                ok, msg = False, _("NAS push failed: {e}").format(e=exc)
            text = (_("Saved and pushed to the NAS: {base}").format(base=base) if ok
                    else _("Saved: {base}  —  {msg}").format(base=base, msg=msg))
            self.window.set_status(text)

        threading.Thread(target=work, daemon=True).start()

    def on_global_exclusions(self):
        dlg = ExclusionsDialog(
            self.window, _("Global exclusions"), self.doc.global_exclusions,
            _("These exclusions apply to ALL mappings. "
              "A folder or file whose name matches will be ignored during the sync."))
        if dlg.result is None:
            return
        self.doc.global_exclusions = dlg.result
        self.doc.dirty = True
        self._refresh()

    def _nas_confirm(self, mapping):
        if mapping.get("source_kind") != "nfs":
            return True
        try:
            import config as appconfig
            pair = appconfig.pair_covering(mapping["source"])
        except Exception:
            return True
        if not pair:
            return True
        try:
            verdict = appconfig.selftest_verdict(pair["local"], pair["nas"])
        except Exception:
            verdict = None
        if verdict == "green":
            return True
        if verdict == "red":
            detail = _("its last test FAILED (paths do not match)")
        elif verdict == "yellow":
            detail = _("its last test reported a problem")
        else:
            detail = _("it has not been tested yet")
        return widgets.confirm(
            self.window,
            _("This folder is on the NAS and depends on the path "
              "correspondence {l} ↔ {n}, but {d}.\n\n"
              "If the correspondence is wrong, real-time sync may not "
              "work for this folder. You can check it in "
              "Configuration (coloured dots next to each "
              "correspondence).\n\nAdd this mapping anyway?").format(
                  l=pair["local"], n=pair["nas"], d=detail),
            _("Correspondence not validated"), _("Add anyway"), _("Cancel"))

    def _dialog_for(self, kind, mapping=None):
        flags = self.window.cli_flags
        dlg = MappingDialog(
            self.window, kind, mapping,
            revisions_ok=flags.get("revisions"),
            shared_ok=flags.get("shared"))
        if not dlg.accepted:
            return None
        fields = dlg.result
        built = document.build_mapping(
            mapping, fields["type"], fields["source"], fields["dest"],
            fields["conflict_mode"], fields["allow_delete"],
            fields["delete_mode"], fields["source_kind"],
            direction=fields.get("direction") or "upload",
            shared_delete_confirmed=bool(fields.get("shared_delete_confirmed")))
        if not self._nas_confirm(built):
            return None
        return built

    def on_add(self, kind):
        built = self._dialog_for(kind)
        if built is None:
            return
        self.doc.mappings.append(built)
        self.doc.dirty = True
        self._refresh()
        label = _("Added (folder): {s}") if kind == "folder" else _("Added (file): {s}")
        self.window.set_status(label.format(s=built["source"]))

    def on_choose_mapping(self):
        import volume as volume_mod
        from PySide6.QtWidgets import QInputDialog
        folders = [
            row for row in self.doc.mappings
            if row.get("type", "folder") == "folder" and row.get("source")
        ]
        if not folders:
            widgets.info(
                self.window,
                _("Add a folder mapping first. Proton Drive opens that folder."),
                _("Choose mapping"))
            return
        if not self._need_file():
            return
        if not self._offer_save(_(
                "The mappings file has unsaved changes. Save them before choosing?")):
            return
        labels = [
            "{s}  →  {d}".format(s=row.get("source"), d=row.get("dest_parent") or "")
            for row in folders
        ]
        label, accepted = QInputDialog.getItem(
            widgets.qt_parent(self.window),
            _("Choose mapping"),
            _("Proton Drive in Dolphin opens this folder, so you can see how "
              "syncing is going. The rest of the account is not downloaded."),
            labels, 0, False)
        if not accepted:
            return
        mapping = folders[labels.index(label)]
        if volume_mod.mark_live(self.doc.mappings, mapping["source"]) is None:
            return
        self.doc.dirty = True
        try:
            self.doc.save(self.doc.path)
        except Exception as exc:
            widgets.error(self.window, str(exc), _("Save error"))
            return
        self._arm_live(mapping["source"], announce_cli=True)

    def resume_live(self):
        """Reopen the chosen folder's watcher. A pass starts after the session check."""
        live = self._live_mapping() if self.doc.path else None
        if live is not None:
            self._prepare_live(live["source"])
        self._auth_then(live["source"] if live is not None else "", announce_cli=False)

    def _live_mapping(self):
        for row in self.doc.mappings:
            if (row.get("live") is True and row.get("type", "folder") == "folder"
                    and row.get("source")):
                return row
        return None

    def _arm_live(self, source, announce_cli):
        self._prepare_live(source)
        self._auth_then(source, announce_cli=announce_cli)

    def _prepare_live(self, source):
        import volume as volume_mod
        volume_mod.ensure_dolphin_place(source)
        try:
            import realtime_manager
            realtime_manager.write_config(2, 2)
        except Exception:
            pass
        started, message = volume_mod.start_watcher(self.doc.path)
        if not started or not _consumer_active():
            watchers = getattr(self.window, "watchers", None)
            if watchers is not None:
                watchers.ensure(self.doc.path)
                started = True
        self._refresh()
        tray = getattr(self.window, "_tray", None)
        if tray is not None:
            tray.refresh()
        if not started:
            self.window.set_status(message or _("The real-time watcher was not started."))
        self._queue_pass(source, False)

    def _queue_pass(self, source, announce_cli):
        if not source:
            return
        self._queued_source = source
        self._queued_announce = announce_cli
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._run_queued_pass)

    def _run_queued_pass(self):
        source = getattr(self, "_queued_source", "") or ""
        announce = bool(getattr(self, "_queued_announce", False))
        self._queued_source = ""
        if source:
            self._launch_mapping_pass(source, announce_cli=announce)

    def _auth_then(self, source, announce_cli):
        self._pending_source = source
        self._announce_cli = announce_cli

        def work():
            try:
                import realtime_manager
                ok, detail = realtime_manager.auth_status()
                if not ok:
                    import time
                    time.sleep(2.5)
                    ok, detail = realtime_manager.auth_status()
            except Exception as exc:
                ok, detail = False, str(exc)
            email = ""
            if ok:
                try:
                    import proton_sync
                    email = proton_sync.get_account_email() or ""
                except Exception:
                    email = ""
            self.window.report_auth(ok, email if ok else detail)

        import threading
        threading.Thread(target=work, daemon=True).start()

    def _launch_mapping_pass(self, source, announce_cli):
        import config as appconfig
        if not appconfig.cli_is_usable():
            lines = appconfig.cli_unusable_explanation()
            if announce_cli:
                widgets.error(self.window, "\n".join(lines), _("Proton CLI"))
            else:
                self.window.set_status(lines[0] if lines else _("Proton CLI binary unusable."))
            return
        if not self._need_engine() or self._running():
            return
        log_path = self._log_file()
        args = run.sync_args(
            self.doc.path, dry_run=False, verify_hash=False, verbose=False,
            delete=False, only_sources=[source])
        cmd = run.engine_cmd(args)
        self._append(_("=== Launch: {c} ===").format(
            c=" ".join(shlex.quote(part) for part in cmd)) + "\n")
        self.window.set_status(_("Sync in progress…"))
        self._start(lambda: run.run_sync(cmd, log_path, run.engine_env(), self._control))

    def on_edit(self):
        index = self._one_index()
        if index is None:
            return
        old = self.doc.mappings[index]
        was_ready = document.ready_state(
            old, self.doc.cache_data(), self.doc.global_exclusions) == "ready"
        old_mirror = bool(old.get("allow_delete"))
        built = self._dialog_for(old.get("type"), old)
        if built is None:
            return
        try:
            index = next(i for i, row in enumerate(self.doc.mappings) if row is old)
        except StopIteration:
            return
        new_mirror = bool(built.get("allow_delete"))
        if was_ready and new_mirror and not old_mirror:
            if self.doc.path and run.lock_is_busy(self.doc.path, run.engine_env()):
                widgets.warn(self.window, _("A sync is already running."), _("Sync in progress"))
                return
            if not widgets.confirm(
                    self.window,
                    _("This mapping was primed as ADDITIVE and you are switching it "
                      "to MIRROR (deletion enabled).\n\n"
                      "Its priming can no longer be used as-is: a mirror mapping "
                      "must reconcile the destination before real-time can handle "
                      "its deletions. Saving will therefore RESET this mapping's "
                      "primed state — it becomes unavailable for real-time until you "
                      "prime it again (in mirror mode).\n\n"
                      "Tip: it is best to decide a mapping's vocation before it holds "
                      "a lot of data, so this re-priming stays quick.\n\n"
                      "Save and reset the primed state?"),
                    _("Change to mirror mode"), _("Save and reset"), _("Cancel")):
                return
            self.doc.mappings[index] = built
            if self.doc.path:
                document.clear_primed(
                    document.cache_path_for(self.doc.path), built["source"])
            self.doc.dirty = True
            self._refresh()
            self.window.set_status(_(
                "Mapping switched to mirror — prime it again to "
                "enable real-time deletions: {s}").format(s=built["source"]))
            return
        if was_ready and old_mirror and not new_mirror:
            widgets.info(
                self.window,
                _("This mapping switches from MIRROR to ADDITIVE: it will no "
                  "longer delete anything on Proton. No re-priming is required — "
                  "its primed state stays valid.\n\n"
                  "Note: if you switch it back to mirror later, the next mirror "
                  "priming will take longer to reconcile the destination again."),
                _("Change to additive mode"))
        self.doc.mappings[index] = built
        self.doc.dirty = True
        self._refresh()
        self.window.set_status(_("Mapping updated: {s}").format(s=built["source"]))

    def on_mapping_exclusions(self):
        index = self._one_index()
        if index is None:
            return
        mapping = self.doc.mappings[index]
        dlg = ExclusionsDialog(
            self.window, _("Mapping exclusions"), mapping.get("exclusions") or {},
            mapping.get("source", ""))
        if dlg.result is None:
            return
        if dlg.result["names"] or dlg.result["patterns"]:
            mapping["exclusions"] = dlg.result
        else:
            mapping.pop("exclusions", None)
        self.doc.dirty = True
        self._refresh()

    def on_remove(self):
        index = self._one_index()
        if index is None:
            return
        removed = self.doc.mappings.pop(index)
        self.doc.dirty = True
        self._refresh()
        self.window.set_status(_("Removed: {s}").format(s=removed.get("source", "")))

    def on_move(self):
        from PySide6.QtWidgets import QFileDialog
        index = self._one_index()
        if index is None or not self._need_file():
            return
        if run.lock_is_busy(self.doc.path, run.engine_env()):
            widgets.warn(self.window, _("A sync is already running."), _("Sync in progress"))
            return
        if self.doc.dirty and not widgets.confirm(
                self.window,
                _("This file has unsaved changes. Moving a "
                  "mapping saves the whole file (to keep both files consistent). "
                  "Continue and save?"),
                _("Move mapping"), _("Continue"), _("Cancel")):
            return
        mapping = self.doc.mappings[index]
        dest, _filt = QFileDialog.getSaveFileName(
            widgets.qt_parent(self.window), _("Move to which mappings file?"), "", "JSON (*.json)",
            options=QFileDialog.Option.DontConfirmOverwrite)
        if not dest:
            return
        plan = document.plan_move(
            self.doc.path, dest, mapping, self.doc.global_exclusions)
        if not plan["ok"]:
            self._refuse_move(plan)
            return
        if plan.get("notice") == "copy":
            widgets.info(
                self.window,
                _("The source file's global exclusions will be "
                  "copied to the destination — this is required so the mapping "
                  "keeps its primed state and syncs the same way."),
                _("Global exclusions copied"))
        if plan.get("notice") == "impact" and not widgets.confirm(
                self.window,
                _("The destination file uses different "
                  "global exclusions, and applying this file's would make {n} "
                  "already-primed mapping(s) there no longer ready:\n  • {names}\n\n"
                  "They would fall back to ⏳ and need re-priming. Other mappings "
                  "are unaffected.\n\nApply this file's global exclusions to the "
                  "destination?\n(Cancel to check and harmonize them yourself "
                  "first.)").format(
                      n=len(plan["impacted"]),
                      names="\n  • ".join(
                          os.path.basename(s.rstrip("/")) for s in plan["impacted"])),
                _("Global exclusions differ"), _("Apply and move"), _("Cancel")):
            self.window.set_status(_("Move cancelled."))
            return
        if not widgets.confirm(
                self.window,
                _("Move this mapping to “{f}”?\n\n  • {s}\n\nIts cache "
                  "(priming) is moved too, so it stays ready — no re-priming needed as long "
                  "as the Proton destination is unchanged.\n\nAfterwards, reinstall/restart "
                  "the background services of BOTH files (⚡ Real-time…, ⏰ Schedule…) so "
                  "they follow the change.").format(
                      f=os.path.basename(dest), s=mapping.get("source", "")),
                _("Move mapping"), _("Move"), _("Cancel")):
            return
        try:
            document.apply_move(
                self.doc.path, dest, mapping, plan.get("src_account"),
                plan.get("copy_excl"), plan.get("src_excl"))
        except Exception as exc:
            widgets.error(self.window, _("Move failed: {e}").format(e=exc), _("Move mapping"))
            return
        self.doc.mappings.pop(index)
        self.doc.save(self.doc.path)
        self._refresh()
        self.window.set_status(_("Mapping moved to {f}: {s}").format(
            f=os.path.basename(dest), s=mapping.get("source", "")))

    def _refuse_move(self, plan):
        reason = plan["reason"]
        if reason == "same_file":
            widgets.info(self.window, _("Source and destination are the same file."),
                         _("Move mapping"))
            return
        if reason == "other_account":
            widgets.error(
                self.window,
                _("The destination file is linked to another Proton "
                  "account:\n  destination: {b}\n  source: {a}\n\nTransfer refused "
                  "— the cache must not mix two accounts.").format(
                      a=plan.get("src_account"), b=plan.get("dest_account")),
                _("Different Proton account"))
            return
        widgets.error(
            self.window,
            _("The destination file already has mappings but no cache "
              "yet, so its Proton account cannot be verified.\n\nPrime the "
              "destination file at least once first, then move the mapping — this "
              "avoids mixing two accounts by mistake."),
            _("Destination identity unknown"))

    def _log_file(self):
        os.makedirs(run.log_dir(), exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        path = os.path.join(run.log_dir(), f"sync-{stamp}.log")
        self._log_path = path
        return path

    def _in_scope(self, only_sources):
        if not only_sources:
            return list(self.doc.mappings)
        wanted = {document.source_key(s) for s in only_sources}
        return [m for m in self.doc.mappings
                if document.source_key(m.get("source", "")) in wanted]

    def on_copy(self):
        if not self._need_file():
            return
        from PySide6.QtWidgets import QApplication
        args = run.sync_args(
            self.doc.path, dry_run=self.dry.isChecked(),
            verify_hash=self.sha1.isChecked(), verbose=self.verbose.isChecked(),
            delete=self.delete.isChecked(), only_sources=self._selected_sources())
        cmd = run.shell_command(args, os.path.join(run.log_dir(), "sync-copy.log"))
        QApplication.clipboard().setText(cmd)
        self.window.set_status(_("Command copied to the clipboard."))
        self._append(_("[Command copied]") + "\n" + cmd + "\n\n")

    def on_run(self):
        if not self._need_file() or not self._need_engine():
            return
        only = self._selected_sources()
        if not self._offer_save(_(
                "The mappings file has unsaved changes. Save them before running?")):
            return
        if self._running():
            widgets.info(self.window, _("A sync is already running."), _("Already running"))
            return
        scope = run.scope_line(only, len(self.doc.mappings))
        if self.delete.isChecked() and not self.dry.isChecked():
            _kind, text = run.deletion_confirm_text(self._in_scope(only), scope)
            if not widgets.confirm(
                    self.window, text, _("Confirm deletion propagation"),
                    _("Run"), _("Cancel")):
                self.window.set_status(_("Launch cancelled."))
                return
        log_path = self._log_file()
        args = run.sync_args(
            self.doc.path, dry_run=self.dry.isChecked(),
            verify_hash=self.sha1.isChecked(), verbose=self.verbose.isChecked(),
            delete=self.delete.isChecked(), only_sources=only)
        cmd = run.engine_cmd(args)
        env = run.engine_env()
        self._append("▶ " + scope + "\n")
        self._append(_("=== Launch: {c} ===").format(
            c=" ".join(shlex.quote(part) for part in cmd)) + "\n")
        self._append(_("=== Log: {p} ===").format(p=log_path) + "\n\n")
        self.window.set_status(_("Sync in progress…"))
        self._start(lambda: run.run_sync(cmd, log_path, env, self._control))

    def on_stop(self):
        run.request_stop(self._control)

    def on_prime(self):
        if not self._need_file() or not self._need_engine():
            return
        if not self._offer_save(_(
                "The mappings file has unsaved changes. Save them before priming?")):
            return
        if self._running():
            widgets.info(self.window, _("A sync is already running."), _("Already running"))
            return
        selected = self._selected_sources()
        sources = selected or [m["source"] for m in self.doc.mappings if m.get("source")]
        if not sources:
            widgets.info(self.window, _("No mapping to prime."), _("Nothing to do"))
            return
        scope = (_("{n} selected mapping(s)").format(n=len(sources)) if selected
                 else _("all {n} mapping(s)").format(n=len(sources)))
        names = "\n  • ".join(os.path.basename(s) for s in sources)
        if not widgets.confirm(
                self.window,
                _("This is a REAL pass, not a test — the Test (dry-run) option "
                  "does not apply to priming.") + "\n\n" +
                _("Prime {scope}:\n  • {names}\n\n"
                  "Each mapping is primed with the options set in its own "
                  "configuration (the trash field): additive mappings upload without "
                  "ever deleting; mirror mappings (trash / permanent) reconcile the "
                  "destination. Once done, the mappings become available for real-time "
                  "processing.\n\n"
                  "The real-time consumer and the scheduled timer are paused during "
                  "priming and restored afterwards. This can take a while on large "
                  "folders (it is interruptible and resumes where it left off).\n\n"
                  "Start priming?").format(scope=scope, names=names),
                _("Prime cache"), _("Start priming"), _("Cancel")):
            self.window.set_status(_("Priming cancelled."))
            return
        self._launch_orchestrated("prime", run.prime_args(self.doc.path, sources))

    def on_reset(self):
        if not self._need_file() or not self._need_engine():
            return
        if not self._offer_save(_(
                "The mappings file has unsaved changes. Save them before resetting?")):
            return
        if self._running():
            widgets.info(self.window, _("A sync is already running."), _("Already running"))
            return
        rows = _selected_rows(self.table)
        if not rows:
            widgets.info(self.window, _("Select the mapping(s) to reset in the list first."),
                         _("No selection"))
            return
        chosen = [self.doc.mappings[row] for row in rows if 0 <= row < len(self.doc.mappings)]
        sources = [m["source"] for m in chosen if m.get("source")]
        if not sources:
            widgets.info(self.window, _("No mapping to reset."), _("Nothing to do"))
            return
        names = "\n  • ".join(os.path.basename(s.rstrip("/")) for s in sources)
        ok, wipe = widgets.confirm_check(
            self.window,
            _("Reset {n} selected mapping(s):\n  • {names}\n\n"
              "This PURGES their local cache (they fall back to ⏳ “pending”) and "
              "rebuilds them with a targeted pass — like priming. Each mapping is "
              "rebuilt according to ITS OWN configuration (the trash field): "
              "additive mappings come back ready for real-time without deleting "
              "anything; mirror mappings come back fully armed for their deletions "
              "(trash or permanent, as configured).\n\n"
              "Optionally, tick below to also empty each mapping's REMOTE folder "
              "(sent to Proton TRASH, recoverable until emptied) before rebuilding — under "
              "the mount guard. You will purge the trash yourself once you have "
              "checked the re-upload succeeded.\n\n"
              "Real-time consumer and the scheduled timer are paused during the "
              "reset and restored afterwards. It is interruptible: to resume, just "
              "press Reset again (idempotent).\n\n"
              "Start reset?").format(n=len(sources), names=names),
            _("Reset mapping"), _("Start reset"), _("Cancel"),
            _("Also empty the remote folder (→ Proton trash)"))
        if not ok:
            self.window.set_status(_("Reset cancelled."))
            return
        if wipe:
            shared = [m for m in chosen
                      if str(m.get("dest_parent", "")).rstrip("/").startswith("/shared-with-me")]
            if shared:
                listed = "\n  • ".join(
                    document.mapping_remote_path(m.get("dest_parent", ""), m.get("source", ""))
                    or m.get("dest_parent", "") for m in shared)
                if not widgets.confirm(
                        self.window,
                        _("You asked to empty the remote folder, and {n} of the "
                          "selected mapping(s) write inside a folder shared with "
                          "you:\n  • {names}\n\n"
                          "Those subfolders sit in folders belonging to someone "
                          "else. Emptying them sends their content — including files "
                          "other people put there — to the OWNER'S trash. The rest of "
                          "their shared folders is not touched.\n\n"
                          "Empty these subfolders anyway?").format(
                              n=len(shared), names=listed),
                        _("Emptying inside a shared folder"), _("Empty anyway"), _("Cancel")):
                    self.window.set_status(_("Reset cancelled."))
                    return
        self._launch_orchestrated("reset", run.reset_args(self.doc.path, sources, wipe=wipe))

    def _launch_orchestrated(self, kind, args):
        log_path = self._log_file()
        cmd = run.engine_cmd(args)
        env = run.engine_env()
        config_path = self.doc.path
        self._start(lambda: run.run_orchestrated(
            cmd, config_path, log_path, env, self._control, kind))
