"""Watch the chosen folder and ask for a sync after a short quiet period.

The window owns this. A systemd unit is not required for a new file to sync.
"""

import os
import threading
import time

QUIET_SECONDS = 2.0


def due(last_event, now, quiet=QUIET_SECONDS):
    """True once ``quiet`` seconds have passed since the latest event."""
    if last_event is None:
        return False
    return (now - last_event) >= quiet


class LiveSync:
    def __init__(self):
        self._stop = threading.Event()
        self._thread = None
        self._source = None
        self._on_change = None
        self._dirty_at = None

    def follow(self, source, on_change):
        self.stop()
        self._stop = threading.Event()
        self._dirty_at = None
        self._source = source
        self._on_change = on_change
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)

    def _note(self):
        self._dirty_at = time.monotonic()

    def _run(self):
        stop = self._stop
        source = self._source
        try:
            import pyinotify
        except ImportError:
            self._poll(stop, source)
            return
        manager = pyinotify.WatchManager()
        mask = (
            pyinotify.IN_CLOSE_WRITE | pyinotify.IN_CREATE | pyinotify.IN_DELETE
            | pyinotify.IN_MOVED_TO | pyinotify.IN_MOVED_FROM
        )

        class _Handler(pyinotify.ProcessEvent):
            def process_default(self_inner, event):
                name = os.path.basename(getattr(event, "pathname", "") or "")
                if name.startswith("."):
                    return
                self._note()

        try:
            manager.add_watch(source, mask, rec=True, auto_add=True)
        except Exception:
            self._poll(stop, source)
            return
        notifier = pyinotify.Notifier(manager, _Handler())
        try:
            while not stop.is_set():
                if notifier.check_events(timeout=400):
                    notifier.read_events()
                    notifier.process_events()
                self._pump_once()
        finally:
            notifier.stop()

    def _pump_once(self):
        dirty = self._dirty_at
        if not due(dirty, time.monotonic()):
            return
        self._dirty_at = None
        callback = self._on_change
        if callback is not None:
            callback()

    def _poll(self, stop, source):
        previous = _signature(source)
        while not stop.is_set():
            stop.wait(QUIET_SECONDS)
            current = _signature(source)
            if current != previous:
                previous = current
                callback = self._on_change
                if callback is not None:
                    callback()


def _signature(root):
    count = 0
    newest = 0
    if not root or not os.path.isdir(root):
        return (0, 0)
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            if name.startswith("."):
                continue
            count += 1
            try:
                newest = max(newest, os.path.getmtime(os.path.join(dirpath, name)))
            except OSError:
                pass
    return (count, newest)
