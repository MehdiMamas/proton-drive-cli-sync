"""Watcher and consumer owned by the window when systemd did not start them."""

import os
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FolderWatchers:
    def __init__(self):
        self._procs = []
        self._path = None

    def running(self):
        return any(proc.poll() is None for proc in self._procs)

    def ensure(self, mappings_path):
        if not mappings_path or not os.path.isfile(mappings_path):
            return False
        if self.running() and self._path == mappings_path:
            return True
        self.stop()
        try:
            import config as appconfig
            cli = appconfig.resolve_proton_cli()
        except Exception:
            cli = ""
        env = dict(os.environ)
        if cli:
            env["PROTON_DRIVE_CLI"] = cli
        for name in ("local_watcher.py", "realtime_consumer.py"):
            script = os.path.join(APP_DIR, name)
            self._procs.append(subprocess.Popen(
                [sys.executable, script, mappings_path],
                cwd=APP_DIR,
                env=env,
                start_new_session=True,
            ))
        self._path = mappings_path
        return True

    def stop(self):
        procs = list(self._procs)
        self._procs = []
        self._path = None
        for proc in procs:
            if proc.poll() is not None:
                continue
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
