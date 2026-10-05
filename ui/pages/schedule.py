"""Page Planification. Les unités viennent de schedule_manager, pas d'un second générateur."""

try:
    from i18n import _
except ImportError:
    def _(s):
        return s

from ui import calendar, widgets

_DAYS = (
    ("Mon", _("Monday")), ("Tue", _("Tuesday")), ("Wed", _("Wednesday")),
    ("Thu", _("Thursday")), ("Fri", _("Friday")), ("Sat", _("Saturday")),
    ("Sun", _("Sunday")),
)


class SchedulePage:
    def __init__(self, host, window):
        from PySide6.QtWidgets import (
            QCheckBox, QComboBox, QHBoxLayout, QLabel, QPlainTextEdit,
            QPushButton, QVBoxLayout,
        )
        self.window = window
        root = QVBoxLayout(host)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        status, status_l = widgets.section(host, _("Current state"))
        self.state = QLabel(_("Reading…"))
        self.state.setWordWrap(True)
        status_l.addWidget(self.state)
        root.addWidget(status)

        actions, layout = widgets.section(host, _("Actions"))
        row = QHBoxLayout()
        self.freq = QComboBox()
        self.freq.addItem(_("Daily"), "daily")
        self.freq.addItem(_("Weekly"), "weekly")
        self.freq.addItem(_("Hourly"), "hourly")
        self.day = QComboBox()
        for token, label in _DAYS:
            self.day.addItem(label, token)
        self.hour = QComboBox()
        for h in range(24):
            self.hour.addItem(f"{h:02d}:00", h)
        self.freq.currentIndexChanged.connect(self._freq_changed)
        row.addWidget(QLabel(_("Frequency: ")))
        row.addWidget(self.freq)
        row.addWidget(QLabel(_("   Day: ")))
        row.addWidget(self.day)
        row.addWidget(QLabel(_("   Time: ")))
        row.addWidget(self.hour)
        row.addStretch(1)
        layout.addLayout(row)
        self.delete = QCheckBox(_(
            "Option B — propagate deletions on the scheduled pass"))
        layout.addWidget(self.delete)

        buttons = QHBoxLayout()
        apply = QPushButton(_("Apply"))
        apply.setObjectName("Primary")
        enable = QPushButton(_("Enable"))
        disable = QPushButton(_("Disable"))
        run_now = QPushButton(_("Run now"))
        journal = QPushButton(_("Journal"))
        apply.clicked.connect(self.on_apply)
        enable.clicked.connect(lambda: self._call("enable_timer"))
        disable.clicked.connect(lambda: self._call("disable_timer"))
        run_now.clicked.connect(lambda: self._call("run_now"))
        journal.clicked.connect(self.on_journal)
        for button in (apply, enable, disable, run_now, journal):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        root.addWidget(actions)

        log_card, log_l = widgets.section(host, _("Log"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(160)
        log_l.addWidget(self.log)
        root.addWidget(log_card, 1)
        self._freq_changed()
        from PySide6.QtCore import QObject, Signal

        class _Bus(QObject):
            text = Signal(str)

        self._bus = _Bus()
        self._bus.text.connect(self.log.setPlainText)

    def on_show(self):
        self.refresh()

    def _freq_changed(self):
        hourly = self.freq.currentData() == "hourly"
        weekly = self.freq.currentData() == "weekly"
        self.hour.setEnabled(not hourly)
        self.day.setEnabled(weekly)

    def _path(self):
        return self.window.doc.path

    def refresh(self):
        try:
            import schedule_manager
            st = schedule_manager.status()
        except Exception as exc:
            self.state.setText(str(exc))
            return
        lines = [
            _("Service: {s}").format(s=_("installed") if st.get("service_exists") else _("absent")),
            _("Timer: {s}").format(
                s=_("active") if st.get("timer_active") else _("inactive")),
        ]
        if st.get("mappings_path"):
            lines.append(st["mappings_path"])
        if st.get("calendar"):
            lines.append(st["calendar"])
        if st.get("next_run"):
            lines.append(str(st["next_run"]))
        self.state.setText("\n".join(lines))
        parsed = calendar.parse_on_calendar(st.get("calendar") or "")
        if parsed:
            freq, hour, dow = parsed
            idx = self.freq.findData(freq)
            if idx >= 0:
                self.freq.setCurrentIndex(idx)
            hidx = self.hour.findData(hour)
            if hidx >= 0:
                self.hour.setCurrentIndex(hidx)
            didx = self.day.findData(dow)
            if didx >= 0:
                self.day.setCurrentIndex(didx)
        self.delete.setChecked(bool(st.get("delete")))

    def on_apply(self):
        path = self._path()
        if not path:
            widgets.info(self.window, _("Open or save a mappings file first."), _("No file"))
            return
        delete = self.delete.isChecked()
        if delete and not widgets.confirm(
                self.window,
                _("You are enabling Option B: the scheduled sync will "
                  "AUTOMATICALLY propagate local deletions to Proton (according "
                  "to each mapping's settings), without intervention.\n\n"
                  "Safety nets: a several-hour window before execution, and the "
                  "Proton trash (mappings in trash mode), which keeps items "
                  "until you empty it — so purge it to reclaim space.\n\n"
                  "Make sure you have tested --delete manually first. "
                  "Continue?"),
                _("Enable automatic deletions?"), _("Enable Option B"), _("Cancel")):
            return
        try:
            import os
            import schedule_manager
            installed = schedule_manager.read_service_mappings_path()
            if installed and os.path.realpath(installed) != os.path.realpath(path):
                if not widgets.confirm(
                        self.window,
                        _("The scheduled service currently uses:\n  {old}\n"
                          "You are installing:\n  {new}\n\n"
                          "This will switch the schedule to the file you are editing. "
                          "Continue?").format(
                              old=os.path.basename(installed),
                              new=os.path.basename(path)),
                        _("Active mappings file change"),
                        _("Confirm the change"),
                        _("Cancel (keep the current file)")):
                    return
            cal = calendar.build_on_calendar(
                self.freq.currentData(), self.hour.currentData(), self.day.currentData())
            ok, msg = schedule_manager.install_or_update(
                path, on_calendar=cal, delete=delete, enable=True)
        except Exception as exc:
            widgets.error(self.window, str(exc), _("Schedule"))
            return
        (widgets.info if ok else widgets.error)(self.window, msg, _("Schedule"))
        self.refresh()

    def _call(self, name):
        try:
            import schedule_manager
            ok, msg = getattr(schedule_manager, name)()
        except Exception as exc:
            widgets.error(self.window, str(exc), _("Schedule"))
            return
        (widgets.info if ok else widgets.error)(self.window, msg, _("Schedule"))
        self.refresh()

    def on_journal(self):
        self.log.setPlainText(_("Reading the journal…"))

        def work():
            try:
                import schedule_manager
                _ok, text = schedule_manager.journal_last_run()
            except Exception as exc:
                text = str(exc)
            self._bus.text.emit(text)

        import threading
        threading.Thread(target=work, daemon=True).start()
