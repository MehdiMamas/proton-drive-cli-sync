"""Page Temps réel. Les actions appellent realtime_manager, rien d'autre."""

import subprocess
import threading

try:
    from i18n import _
except ImportError:
    def _(s):
        return s

from ui import widgets


def _pair(result):
    if not result:
        return False, ""
    return bool(result[0]), result[1] if len(result) > 1 else ""


class RealtimePage:
    def __init__(self, host, window):
        from PySide6.QtWidgets import (
            QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSpinBox,
            QVBoxLayout,
        )
        self.window = window
        self._tail = None
        root = QVBoxLayout(host)
        root.setContentsMargins(16, 16, 16, 16)
        card, layout = widgets.card(host)
        self.title = QLabel(_("Real-time"))
        self.title.setObjectName("Title")
        layout.addWidget(self.title)
        self.state = QLabel(_("Reading…"))
        self.state.setWordWrap(True)
        layout.addWidget(self.state)

        buttons = QHBoxLayout()
        specs = (
            (_("Install / Update"), self.on_install, "Primary"),
            (_("Start"), self.on_start, None),
            (_("Stop"), self.on_stop, "Danger"),
            (_("Restart"), self.on_restart, None),
            (_("Disable"), self.on_disable, None),
        )
        for label, slot, name in specs:
            button = QPushButton(label)
            if name:
                button.setObjectName(name)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        delays = QHBoxLayout()
        self.debounce = QSpinBox()
        self.debounce.setRange(1, 3600)
        self.cycle = QSpinBox()
        self.cycle.setRange(1, 3600)
        apply_delays = QPushButton(_("Apply delays"))
        apply_delays.clicked.connect(self.on_delays)
        delays.addWidget(QLabel(_("Debounce (s)")))
        delays.addWidget(self.debounce)
        delays.addWidget(QLabel(_("Cycle (s)")))
        delays.addWidget(self.cycle)
        delays.addWidget(apply_delays)
        delays.addStretch(1)
        layout.addLayout(delays)

        nas = QHBoxLayout()
        push = QPushButton(_("Push mappings"))
        scripts = QPushButton(_("Push scripts"))
        clean = QPushButton(_("Clear queues"))
        push.clicked.connect(self.on_push)
        scripts.clicked.connect(self.on_scripts)
        clean.clicked.connect(self.on_clean)
        for button in (push, scripts, clean):
            nas.addWidget(button)
        nas.addStretch(1)
        layout.addLayout(nas)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        layout.addWidget(self.log)
        root.addWidget(card)
        self._delays_seen = False
        from PySide6.QtCore import QObject, Signal

        class _Bus(QObject):
            line = Signal(str)

        self._bus = _Bus()
        self._bus.line.connect(self.log.appendPlainText)

    def on_show(self):
        self.refresh()
        self._start_tail()

    def _path(self):
        return self.window.doc.path

    def refresh(self):
        path = self._path()
        if not path:
            self.state.setText(_("Open or save a mappings file first."))
            return
        try:
            import realtime_manager
            st = realtime_manager.status(path)
        except Exception as exc:
            self.state.setText(str(exc))
            return
        if not self._delays_seen:
            self.debounce.setValue(int(st.get("debounce_seconds") or 30))
            self.cycle.setValue(int(st.get("cycle_seconds") or 30))
            self._delays_seen = True
        drift = st.get("drift") or {}
        queues = st.get("queues") or {}
        nas = st.get("nas") or {}
        watched = st.get("units_mappings_path") or path
        self.title.setText(_("Real-time — watching {f}").format(
            f=__import__("os").path.basename(watched)))
        lines = [
            _("Daemons: watch {w}, consumer {c}").format(
                w=_("active") if st.get("watch_active") else _("stopped"),
                c=_("active") if st.get("consume_active") else _("stopped")),
            _("NAS copy: {s}").format(s=drift.get("state") or "—"),
            _("Queues — local: {n}    NAS ({u}): {p}").format(
                n=queues.get("local", 0),
                u=queues.get("user", ""),
                p=(queues.get("nas", 0) if queues.get("nas_reachable")
                   else _("NAS unreachable"))),
            _("NAS watcher markers: {n}").format(n=nas.get("marker_count", 0)),
        ]
        if st.get("nas_scripts_stale"):
            lines.append(_("NAS scripts out of date: push them."))
        self.state.setText("\n".join(lines))

    def _need(self):
        if self._path():
            return True
        widgets.info(self.window, _("Open or save a mappings file first."), _("No file"))
        return False

    def _report(self, result):
        ok, msg = _pair(result)
        (widgets.info if ok else widgets.error)(self.window, msg, _("Real-time"))
        self.refresh()

    def on_install(self):
        if not self._need():
            return
        try:
            import realtime_manager
            result = realtime_manager.install_or_update_units(self._path(), enable=True)
        except Exception as exc:
            widgets.error(self.window, str(exc), _("Real-time"))
            return
        self._report(result)

    def on_start(self):
        self._simple("start_daemons")

    def on_stop(self):
        self._simple("stop_daemons")

    def on_restart(self):
        self._simple("restart_daemons")

    def on_disable(self):
        self._simple("disable_daemons")

    def _simple(self, name):
        try:
            import realtime_manager
            result = getattr(realtime_manager, name)()
        except Exception as exc:
            widgets.error(self.window, str(exc), _("Real-time"))
            return
        self._report(result)

    def on_delays(self):
        try:
            import realtime_manager
            ok, msg = realtime_manager.write_config(
                self.debounce.value(), self.cycle.value())
        except Exception as exc:
            widgets.error(self.window, str(exc), _("Real-time"))
            return
        (widgets.info if ok else widgets.error)(self.window, msg, _("Real-time"))

    def on_push(self):
        if not self._need():
            return
        try:
            import realtime_manager
            ok, msg = realtime_manager.push_mappings_to_nas(self._path())
        except Exception as exc:
            widgets.error(self.window, str(exc), _("Real-time"))
            return
        (widgets.info if ok else widgets.error)(self.window, msg, _("Real-time"))
        self.refresh()

    def on_scripts(self):
        try:
            import realtime_manager
            ok, msg, _cmd = realtime_manager.push_scripts_to_nas()
        except Exception as exc:
            widgets.error(self.window, str(exc), _("Real-time"))
            return
        (widgets.info if ok else widgets.error)(self.window, str(msg), _("Real-time"))
        self.refresh()

    def on_clean(self):
        if not self._need():
            return
        path = self._path()
        try:
            import realtime_manager
            queues = realtime_manager.count_queues(path)
        except Exception as exc:
            widgets.error(self.window, str(exc), _("Queues"))
            return
        nas_part = (f"{queues['nas']}" if queues.get("nas_reachable")
                    else _("NAS unreachable"))
        if not widgets.confirm(
                self.window,
                _("Clear the pending markers?\n\n"
                  "Local: {n}    NAS ({u}): {p}\n\n"
                  "Changes not yet processed will be forgotten (the nightly "
                  "sync remains the safety net).").format(
                      n=queues.get("local", 0), u=queues.get("user", ""), p=nas_part),
                _("Clear the queues?"), _("Clear"), _("Cancel")):
            return
        try:
            ok, msg = realtime_manager.clean_queues(path)
        except Exception as exc:
            widgets.error(self.window, str(exc), _("Queues"))
            return
        (widgets.info if ok else widgets.error)(self.window, msg, _("Queues"))
        self.refresh()

    def _start_tail(self):
        if self._tail is not None and self._tail.poll() is None:
            return
        try:
            import realtime_manager
            cmd = realtime_manager.journal_follow_command()
        except Exception:
            return
        try:
            self._tail = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1)
        except OSError:
            return

        def reader():
            proc = self._tail
            if proc is None or proc.stdout is None:
                return
            for line in proc.stdout:
                self._bus.line.emit(line.rstrip("\n"))

        threading.Thread(target=reader, daemon=True).start()

    def stop_tail(self):
        proc = self._tail
        self._tail = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
