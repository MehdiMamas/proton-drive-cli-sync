"""Dialogues d'édition : mapping, exclusions, dossier Proton, connexion.

Aucune règle de sauvegarde ici. La validation est dans ui.document.
"""

import threading

try:
    from i18n import _
except ImportError:
    def _(s):
        return s

from ui import document, widgets


def _qt_exclusions():
    from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit
    return QDialog, QHBoxLayout, QLabel, QPlainTextEdit


def _qt():
    from PySide6.QtWidgets import (
        QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
        QPushButton, QRadioButton,
    )
    return (QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
            QPushButton, QRadioButton, QCheckBox)


class MappingDialog:
    """Saisie d'un mapping. ``result`` est le dict des champs, ou None."""

    def __init__(self, parent, kind, mapping=None, revisions_ok=None, shared_ok=None):
        (QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
         QPushButton, QRadioButton, QCheckBox) = _qt()
        self._QFileDialog = QFileDialog
        self.result = None
        is_edit = mapping is not None
        m_type = mapping["type"] if is_edit else kind
        self._type = m_type
        dlg, body, content, buttons = widgets.dialog(
            parent,
            _("Edit mapping") if is_edit else (
                _("Add a folder") if m_type == "folder" else _("Add a file")),
            scroll=True)
        self._dlg = dlg
        dlg.resize(680, 680)

        place, place_l = widgets.section(body, _("Source (local)"))
        src_row = QHBoxLayout()
        self.source = QLineEdit(mapping["source"] if is_edit else "")
        src_row.addWidget(self.source)
        browse = QPushButton(_("Browse…"))
        browse.clicked.connect(self._browse_source)
        src_row.addWidget(browse)
        place_l.addLayout(src_row)

        place_l.addWidget(QLabel(_("Destination (parent folder on Proton Drive)")))
        dest_row = QHBoxLayout()
        self.dest = QLineEdit(mapping["dest_parent"] if is_edit else "/my-files")
        dest_row.addWidget(self.dest)
        proton = QPushButton(_("Browse Proton…"))
        proton.clicked.connect(self._browse_proton)
        dest_row.addWidget(proton)
        place_l.addLayout(dest_row)
        content.addWidget(place)

        direction, direction_l = widgets.section(body, _("Direction"))
        twoway_init = (not is_edit) or mapping.get("direction") == "twoway"
        self.upload = QRadioButton(_(
            "Upload only — local files are backed up. Remote changes are not downloaded"))
        self.twoway = QRadioButton(_("Two-way — for this mapping only"))
        self.upload.setChecked(not twoway_init)
        self.twoway.setChecked(twoway_init)
        direction_l.addWidget(self.upload)
        direction_l.addWidget(self.twoway)
        self.keep_both = QLabel(_(
            "If both sides change, both copies are kept and nothing is deleted. "
            "Remote changes are checked about every 5 minutes, not every second."))
        self.keep_both.setWordWrap(True)
        self.keep_both.setObjectName("Muted")
        direction_l.addWidget(self.keep_both)
        content.addWidget(direction)
        self.twoway.toggled.connect(self._direction_note)
        self._direction_note()

        modified, modified_l = widgets.section(body, _("Modified files"))
        conf = (mapping.get("conflict_mode") or "replace") if is_edit else "replace"
        self.replace = QRadioButton(_(
            "Replace — the previous version goes to the Proton trash"))
        self.revision = QRadioButton(_(
            "Keep a revision — the previous version stays attached to the file"))
        self.replace.setChecked(conf != "revision")
        self.revision.setChecked(conf == "revision")
        modified_l.addWidget(self.replace)
        modified_l.addWidget(self.revision)
        self.conf_note = QLabel("")
        self.conf_note.setObjectName("Muted")
        self.conf_note.setWordWrap(True)
        modified_l.addWidget(self.conf_note)
        if revisions_ok is False:
            self.revision.setEnabled(False)
            if conf == "revision":
                self.conf_note.setText(_(
                    "This mapping asks for revisions, but the installed Proton CLI "
                    "is too old to create them: it will run in replace mode until "
                    "the CLI is updated. The setting is kept."))
            else:
                self.conf_note.setText(_(
                    "Revisions need a newer Proton CLI than the one installed."))
        elif revisions_ok is None and conf == "revision":
            self.conf_note.setText(_(
                "This mapping asks for revisions, but the Proton CLI version "
                "could not be determined, so they cannot be used: it will run "
                "in replace mode. The setting is kept."))
        content.addWidget(modified)

        deletion, deletion_l = widgets.section(body, _("Deletion propagation"))
        allow_init = bool(mapping.get("allow_delete")) if is_edit else False
        mode_init = (mapping.get("delete_mode") or "trash") if is_edit else "trash"
        kind_init = (mapping.get("source_kind") or "") if is_edit else ""
        self.allow = QCheckBox(_(
            "Allow this mapping to delete on Proton what was deleted locally"))
        self.allow.setChecked(allow_init)
        deletion_l.addWidget(self.allow)
        self.shared_note = QLabel("")
        self.shared_note.setWordWrap(True)
        self.shared_note.setObjectName("Muted")
        deletion_l.addWidget(self.shared_note)
        self.trash = QRadioButton(_("Proton trash (recoverable)"))
        self.trash.setChecked(mode_init != "permanent")
        deletion_l.addWidget(self.trash)
        self.perm_note = QLabel("")
        self.perm_note.setWordWrap(True)
        if mode_init == "permanent":
            self.perm_note.setText(_(
                "This mapping is set to permanent deletion, which the "
                "Proton CLI no longer allows reliably: it deletes to the "
                "trash instead. Pick trash mode to make that explicit."))
        deletion_l.addWidget(self.perm_note)
        self.nfs = QRadioButton(_("NFS (network/NAS)"))
        self.local = QRadioButton(_("Local (internal disk)"))
        self.nfs.setChecked(kind_init == "nfs")
        self.local.setChecked(kind_init == "local")
        deletion_l.addWidget(self.nfs)
        deletion_l.addWidget(self.local)
        content.addWidget(deletion)
        self._shared_ok = shared_ok
        self.allow.toggled.connect(self._toggle)
        self.dest.textChanged.connect(self._shared_lock)
        self._shared_lock()

        widgets.action(buttons, _("Cancel"), dlg.reject)
        widgets.action(buttons, _("OK"), self._ok, primary=True)
        self._accepted = dlg.exec() == QDialog.Accepted

    def _browse_source(self):
        if self._type == "folder":
            path = self._QFileDialog.getExistingDirectory(
                self._dlg, _("Choose a source folder"))
        else:
            path, _filt = self._QFileDialog.getOpenFileName(
                self._dlg, _("Choose a source file"))
        if path:
            self.source.setText(path)

    def _browse_proton(self):
        chosen = RemoteFolderPicker.pick(self._dlg, self.dest.text().strip() or "/my-files")
        if chosen:
            self.dest.setText(chosen)

    def _direction_note(self):
        self.keep_both.setVisible(self.twoway.isChecked())

    def _toggle(self):
        on = self.allow.isChecked()
        for widget in (self.trash, self.nfs, self.local):
            widget.setEnabled(on)

    def _shared_lock(self):
        dest = self.dest.text().strip().rstrip("/")
        shared = dest.startswith("/shared-with-me")
        if shared and self._shared_ok is False:
            self.allow.setChecked(False)
            self.allow.setEnabled(False)
            self.shared_note.setText(_(
                "Deletions can't be propagated to a “Shared with me” "
                "destination with this Proton CLI version: this mapping is "
                "upload-only."))
        elif shared:
            self.allow.setEnabled(True)
            src = self.source.text().strip()
            target = document.mapping_remote_path(dest, src) if document.source_is_absolute(src) else ""
            if target:
                self.shared_note.setText(_(
                    "This folder belongs to someone else.\n\n{p}\n\n"
                    "If you enable deletion, anything inside that subfolder "
                    "that is missing locally is deleted and sent to the "
                    "OWNER'S trash. The rest of their shared folder is not "
                    "touched.").format(p=target))
            else:
                self.shared_note.setText(_(
                    "This folder belongs to someone else.\n\n"
                    "Once you pick a source, deletion will only affect the "
                    "subfolder named after it, inside this shared folder.\n\n"
                    "Anything missing locally is deleted from there and sent "
                    "to the OWNER'S trash. The rest of their shared folder is "
                    "not touched."))
        else:
            self.allow.setEnabled(True)
            self.shared_note.setText("")
        self._toggle()

    def _ok(self):
        source = self.source.text()
        dest = self.dest.text()
        allow = self.allow.isChecked()
        kind = "nfs" if self.nfs.isChecked() else ("local" if self.local.isChecked() else "")
        message = document.edit_error(source, dest, allow, kind)
        if message:
            widgets.warn(self._dlg, message, _("Invalid destination") if "destination" in message.lower() or "/my-files" in message else _("Missing source"))
            return
        mode = "permanent" if (not self.trash.isChecked() and self.perm_note.text()) else "trash"
        # Le choix définitif n'est plus proposé. On ne le réécrit que s'il
        # était déjà là ET que l'utilisateur n'a pas coché la corbeille.
        if self.trash.isChecked():
            mode = "trash"
        needed = document.confirm_kind(dest, allow, mode)
        if needed == "permanent":
            if not widgets.confirm(
                    self._dlg,
                    _("You chose PERMANENT deletion (no trash).\n\n"
                      "Files deleted locally will be erased from Proton with "
                      "no possibility of recovery.\n\nConfirm this choice?"),
                    _("Permanent deletion"), _("Confirm"), _("Cancel")):
                return
        if needed == "shared":
            remote = document.mapping_remote_path(dest, source) or dest.strip()
            shared_text = _(
                    "This destination is a folder shared with you — it "
                    "belongs to someone else.\n\n"
                    "With deletion enabled, every file inside\n{p}\n"
                    "and its subfolders that is missing from your local "
                    "source will be deleted and sent to the OWNER'S trash — "
                    "including files other people put there. Only that "
                    "subfolder is affected: neither the rest of the shared "
                    "folder nor the rest of the Drive.\n\n"
                    "Only enable deletion on a folder you are the sole "
                    "contributor to, as one-way delivery to its owner. Any "
                    "other use is potentially destructive.\n\n"
                    "Enable deletion on this shared folder?").format(p=remote)
            if self.twoway.isChecked():
                shared_text += _("\n\nTwo-way is on for this mapping. "
                                 "The same confirmation is required before a "
                                 "file that disappeared locally can be trashed.")
            if not widgets.confirm(
                    self._dlg, shared_text,
                    _("Deletion on a shared folder"), _("Enable"), _("Cancel")):
                return
        self.result = {
            "type": self._type,
            "source": source,
            "dest": dest,
            "direction": "twoway" if self.twoway.isChecked() else "upload",
            "shared_delete_confirmed": needed == "shared",
            "conflict_mode": "revision" if self.revision.isChecked() else "replace",
            "allow_delete": allow,
            "delete_mode": mode,
            "source_kind": kind,
        }
        self._dlg.accept()

    @property
    def accepted(self):
        return self._accepted and self.result is not None


class ExclusionsDialog:
    def __init__(self, parent, title, current, context):
        QDialog, QHBoxLayout, QLabel, QPlainTextEdit = _qt_exclusions()
        self.result = None
        dlg, body, content, buttons = widgets.dialog(parent, title)
        dlg.resize(640, 480)
        intro = QLabel(context)
        intro.setWordWrap(True)
        content.addWidget(intro)
        help_lbl = QLabel(_(
            "• Exact names: one per line (e.g. .caltrash, trash, .Trash-1000). "
            "Case-insensitive. Excludes any folder OR file with that name.\n"
            "• Patterns: one per line, shell style (e.g. *.tmp, .Trash-*, ~*). "
            "The * matches any sequence of characters."))
        help_lbl.setWordWrap(True)
        help_lbl.setObjectName("Muted")
        content.addWidget(help_lbl)
        row = QHBoxLayout()
        names = QPlainTextEdit("\n".join((current or {}).get("names", []) or []))
        pats = QPlainTextEdit("\n".join((current or {}).get("patterns", []) or []))
        names_card, names_l = widgets.section(body, _("Exact names (one per line)"))
        pats_card, pats_l = widgets.section(body, _("Patterns (one per line)"))
        names_l.addWidget(names)
        pats_l.addWidget(pats)
        row.addWidget(names_card)
        row.addWidget(pats_card)
        content.addLayout(row)
        widgets.action(buttons, _("Cancel"), dlg.reject)
        widgets.action(buttons, _("OK"), dlg.accept, primary=True)
        if dlg.exec() == QDialog.Accepted:
            self.result = {
                "names": document.parse_lines(names.toPlainText()),
                "patterns": document.parse_lines(pats.toPlainText()),
            }


class RemoteFolderPicker:
    """Arbre paresseux des dossiers Proton. Réutilise get_remote_listing."""

    @staticmethod
    def pick(parent, start):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QDialog, QLabel, QTreeWidget, QTreeWidgetItem
        dlg, _body, content, buttons = widgets.dialog(parent, _("Browse Proton…"))
        dlg.resize(520, 420)
        chosen = {"path": None}
        status = QLabel(_("Double-click to open a folder; select the "
                          "destination, then “Choose this folder”."))
        status.setWordWrap(True)
        content.addWidget(status)
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        content.addWidget(tree, 1)

        def add_placeholder(item):
            child = QTreeWidgetItem([_("Loading…")])
            child.setData(0, Qt.UserRole, "placeholder")
            item.addChild(child)

        def add_node(parent_item, path):
            item = QTreeWidgetItem([path])
            item.setData(0, Qt.UserRole, path)
            add_placeholder(item)
            if parent_item is None:
                tree.addTopLevelItem(item)
            else:
                parent_item.addChild(item)
            return item

        def fill(item):
            path = item.data(0, Qt.UserRole)
            kids = item.takeChildren()
            del kids
            try:
                import proton_sync
                listing = proton_sync.get_remote_listing(path)
            except Exception as exc:
                status.setText(str(exc))
                return
            if not getattr(listing, "ok", False):
                status.setText(getattr(listing, "error", "") or _("(no subfolder)"))
                return
            folders = []
            for name, meta in listing.items():
                kind = (meta or {}).get("type")
                if kind in (None, "folder"):
                    folders.append(name)
            if not folders:
                status.setText(_("(no subfolder)"))
                return
            for name in sorted(folders):
                child_path = path.rstrip("/") + "/" + name
                add_node(item, child_path)

        for base in ("/my-files", "/shared-with-me"):
            add_node(None, base)
        tree.itemExpanded.connect(lambda item: (
            fill(item) if item.childCount() == 1
            and item.child(0).data(0, Qt.UserRole) == "placeholder" else None))

        def accept():
            item = tree.currentItem()
            path = item.data(0, Qt.UserRole) if item else None
            if not path or path == "placeholder":
                return
            chosen["path"] = path
            dlg.accept()

        widgets.action(buttons, _("Cancel"), dlg.reject)
        widgets.action(buttons, _("Choose this folder"), accept, primary=True)
        tree.itemDoubleClicked.connect(lambda *_a: accept())
        if dlg.exec() != QDialog.Accepted:
            return None
        return chosen["path"]


class LoginDialog:
    """Lance ``proton-drive auth login``. Le mot de passe reste dans le navigateur."""

    def __init__(self, parent):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import (
            QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
        )
        import queue
        import subprocess
        self._queue = queue.Queue()
        dlg, body, content, buttons = widgets.dialog(parent, _("Sign in to Proton"))
        dlg.resize(640, 420)
        intro = QLabel(_(
            "A browser window will open for you to sign in to Proton "
            "(password and 2FA stay in the browser — never handled here).\n"
            "Keep this window open until it confirms success."))
        intro.setWordWrap(True)
        content.addWidget(intro)
        url_row = QHBoxLayout()
        self._url = QLineEdit()
        self._url.setReadOnly(True)
        copy = QPushButton(_("Copy URL"))
        copy.setEnabled(False)
        url_row.addWidget(self._url)
        url_row.addWidget(copy)
        content.addLayout(url_row)
        progress, progress_l = widgets.section(body, _("Sign-in progress"))
        out = QPlainTextEdit()
        out.setReadOnly(True)
        out.setMinimumHeight(120)
        progress_l.addWidget(out)
        status = QLabel(_("Starting sign-in…"))
        status.setWordWrap(True)
        progress_l.addWidget(status)
        content.addWidget(progress)
        found = {"url": None}
        proc = {"p": None}

        def append(text):
            out.insertPlainText(text)
            if "http" in text and found["url"] is None:
                for tok in text.split():
                    if tok.startswith("http"):
                        found["url"] = tok
                        self._url.setText(tok)
                        copy.setEnabled(True)
                        break

        def pump():
            try:
                while True:
                    kind, payload = self._queue.get_nowait()
                    if kind == "line":
                        append(payload)
                    elif kind == "status":
                        status.setText(payload)
            except queue.Empty:
                pass

        timer = QTimer(dlg)
        timer.timeout.connect(pump)
        timer.start(80)

        def reader():
            try:
                import realtime_manager
                proc["p"] = subprocess.Popen(
                    realtime_manager.auth_login_command(),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1)
            except Exception as exc:
                self._queue.put(("line", str(exc) + "\n"))
                self._queue.put(("status", _("❌ proton-drive not found — check its path.")))
                return
            for line in proc["p"].stdout:
                self._queue.put(("line", line))
            code = proc["p"].wait()
            if code == 0:
                self._queue.put(("status", _("Signed in.")))
            else:
                self._queue.put(("status", _("Sign-in failed.")))

        def copy_url():
            if found["url"]:
                from PySide6.QtWidgets import QApplication
                QApplication.clipboard().setText(found["url"])

        def close_dlg():
            timer.stop()
            running = proc["p"]
            if running is not None and running.poll() is None:
                try:
                    running.terminate()
                except OSError:
                    pass
            dlg.reject()

        copy.clicked.connect(copy_url)
        widgets.action(buttons, _("Close"), close_dlg)
        threading.Thread(target=reader, daemon=True).start()
        dlg.exec()
