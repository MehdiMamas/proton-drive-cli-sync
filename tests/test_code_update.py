"""Restart after a code update (code_update.py).

A long-running program must restart only when the code changed, once the
copy is over (the new fingerprint stays still for a while), and never onto
code that does not compile. Each restart is written down once, read once.
"""
import json
import os
import subprocess
import sys
import textwrap
import time

import code_update


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _app(tmp_path):
    app = tmp_path / "app"
    (app / "locale" / "fr" / "LC_MESSAGES").mkdir(parents=True)
    (app / "a.py").write_text("x = 1\n")
    (app / "b.py").write_text("y = 2\n")
    (app / "locale" / "fr" / "LC_MESSAGES" / "p.mo").write_bytes(b"mo")
    return app


def _touch(path, text):
    path.write_text(text)
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


def test_no_change_never_ready(tmp_path):
    app = _app(tmp_path)
    clock = Clock()
    w = code_update.CodeWatch("t", app_dir=str(app), stable_seconds=60, clock=clock)
    for _ in range(5):
        clock.t += 100
        assert w.ready() is False


def test_ready_only_after_the_new_code_stays_still(tmp_path):
    app = _app(tmp_path)
    clock = Clock()
    w = code_update.CodeWatch("t", app_dir=str(app), stable_seconds=60, clock=clock)
    _touch(app / "a.py", "x = 10\n")
    assert w.ready() is False            # change just seen
    clock.t += 30
    _touch(app / "b.py", "y = 20\n")      # copy still going on
    assert w.ready() is False
    clock.t += 59
    assert w.ready() is False            # still < 60 s since the last change
    clock.t += 2
    assert w.ready() is True


def test_old_file_dates_do_not_count_as_stable(tmp_path):
    """unzip restores archive dates: a file can look an hour old while the
    copy is still in progress. Only an unchanged fingerprint counts."""
    app = _app(tmp_path)
    clock = Clock()
    w = code_update.CodeWatch("t", app_dir=str(app), stable_seconds=60, clock=clock)
    (app / "a.py").write_text("x = 10\n")
    os.utime(app / "a.py", (time.time() - 3600, time.time() - 3600))
    assert w.ready() is False


def test_a_new_translation_counts(tmp_path):
    app = _app(tmp_path)
    clock = Clock()
    w = code_update.CodeWatch("t", app_dir=str(app), stable_seconds=60, clock=clock)
    (app / "locale" / "fr" / "LC_MESSAGES" / "p.mo").write_bytes(b"new mo")
    assert w.ready() is False
    clock.t += 61
    assert w.ready() is True


def test_code_that_does_not_compile_is_refused(tmp_path):
    app = _app(tmp_path)
    clock = Clock()
    w = code_update.CodeWatch("t", app_dir=str(app), stable_seconds=60, clock=clock)
    _touch(app / "a.py", "def broken(:\n")
    w.ready()
    clock.t += 61
    assert w.ready() is False            # keeps the old code running
    _touch(app / "a.py", "x = 3\n")       # fixed by the next copy
    w.ready()
    clock.t += 61
    assert w.ready() is True


def test_restarts_are_shown_once(tmp_path, monkeypatch):
    monkeypatch.setattr(code_update, "RESTARTS_FILE", str(tmp_path / "r.jsonl"))
    assert code_update.take_restarts() == []
    code_update.record_restart("watcher", when=20.0)
    code_update.record_restart("consumer", when=10.0)
    items = code_update.take_restarts()
    assert [i["name"] for i in items] == ["consumer", "watcher"]
    assert code_update.take_restarts() == []


def test_a_program_restarts_itself_with_the_new_code(tmp_path):
    """End to end: a real process, the file changes, it replaces itself with
    the same pid, runs the new code and leaves one line in the restarts file."""
    app = _app(tmp_path)
    here = os.path.dirname(os.path.abspath(code_update.__file__))
    out = tmp_path / "out.txt"
    restarts = tmp_path / "restarts.jsonl"
    (app / "prog.py").write_text(textwrap.dedent(f"""
        import os, sys, time
        sys.path.insert(0, {here!r})
        import code_update
        code_update.RESTARTS_FILE = {str(restarts)!r}
        import a
        with open({str(out)!r}, "a") as fh:
            fh.write(f"{{os.getpid()}} {{a.x}}\\n")
        if a.x == 2:
            sys.exit(0)
        w = code_update.CodeWatch("watcher", app_dir={str(app)!r}, stable_seconds=1)
        deadline = time.time() + 20
        while time.time() < deadline:
            if w.ready():
                w.restart()
            time.sleep(0.2)
        sys.exit(3)
    """))
    proc = subprocess.Popen([sys.executable, str(app / "prog.py")], cwd=str(app))
    for _ in range(50):
        if out.exists():
            break
        time.sleep(0.1)
    _touch(app / "a.py", "x = 2\n")
    assert proc.wait(timeout=30) == 0
    lines = out.read_text().split()
    assert lines[1] == "1" and lines[3] == "2"
    assert lines[0] == lines[2]                      # same pid: replaced in place
    recorded = [json.loads(line) for line in restarts.read_text().splitlines()]
    assert [r["name"] for r in recorded] == ["watcher"]
