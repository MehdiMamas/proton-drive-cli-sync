"""The NAS reads its settings beside its scripts; Install / Update writes the
interface language there."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import realtime_manager as rm

REPO = Path(__file__).resolve().parents[1]


def _nas_copy(dest):
    dest.mkdir(parents=True)
    for name in rm._NAS_SCRIPT_FILES:
        if (REPO / name).exists():
            shutil.copy(REPO / name, dest / name)
    shutil.copytree(REPO / "locale", dest / "locale")
    return dest


def _python(code, cwd, home):
    env = os.environ.copy()
    for var in ("PROTON_SYNC_SETTINGS", "XDG_CONFIG_HOME", "LC_ALL",
                "LC_MESSAGES"):
        env.pop(var, None)
    env["HOME"] = str(home)
    env["LANG"] = "C"
    return subprocess.run([sys.executable, "-c", code], cwd=str(cwd), env=env,
                          capture_output=True, text=True)


def test_nas_watcher_reads_the_settings_beside_it(tmp_path):
    nas = _nas_copy(tmp_path / "proton-sync")
    (nas / "settings.json").write_text('{"language": "fr"}\n', encoding="utf-8")
    home = tmp_path / "nas-home"
    home.mkdir()
    code = (
        "import runpy, sys\n"
        "sys.argv = ['nas_watcher.py', '--help']\n"
        "try:\n"
        "    runpy.run_path('nas_watcher.py', run_name='__main__')\n"
        "except SystemExit:\n"
        "    pass\n"
        "import i18n, paths\n"
        "print(paths.settings_path())\n"
        "print(i18n.resolve_language())\n"
    )
    result = _python(code, nas, home)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert lines[-2:] == [str(nas / "settings.json"), "fr"]
    assert not (home / ".config").exists()


def test_importing_nas_watcher_keeps_the_desktop_path(tmp_path):
    copy = _nas_copy(tmp_path / "scripts")
    home = tmp_path / "desk-home"
    home.mkdir()
    result = _python("import nas_watcher, paths\nprint(paths.settings_path())\n",
                     copy, home)
    assert result.returncode == 0, result.stderr
    expect = home / ".config" / "proton-drive-cli-sync" / "settings.json"
    assert result.stdout.strip().splitlines()[-1] == str(expect)


@pytest.fixture
def nas(tmp_path, monkeypatch):
    base = tmp_path / "proton-sync"
    monkeypatch.setattr(rm, "NAS_BASE", str(base))
    monkeypatch.setattr(rm, "NAS_SETTINGS_PATH", str(base / "settings.json"))
    monkeypatch.setattr(rm, "nas_reachable", lambda: True)
    monkeypatch.setattr(rm.appconfig, "nas_enabled", lambda: True)
    return base


def _desktop_language(tmp_path, monkeypatch, value):
    path = tmp_path / "desktop-settings.json"
    path.write_text(json.dumps({"language": value}), encoding="utf-8")
    monkeypatch.setenv("PROTON_SYNC_SETTINGS", str(path))


def _nas_settings(nas):
    return json.loads((nas / "settings.json").read_text(encoding="utf-8"))


def test_install_writes_the_interface_language_to_the_nas(
        nas, tmp_path, monkeypatch):
    _desktop_language(tmp_path, monkeypatch, "de")
    assert rm.nas_scripts_stale() is True
    ok, msg, _cmd = rm.push_scripts_to_nas()
    assert ok, msg
    assert _nas_settings(nas) == {"language": "de"}
    assert "settings.json (language de)" in msg
    assert (nas / "nas_watcher.py").exists()
    assert rm.nas_scripts_stale() is False

    _desktop_language(tmp_path, monkeypatch, "it")
    assert rm.nas_scripts_stale() is True
    data = _nas_settings(nas)
    data["kept"] = 1
    (nas / "settings.json").write_text(json.dumps(data), encoding="utf-8")
    ok, msg, _cmd = rm.push_scripts_to_nas()
    assert ok, msg
    assert _nas_settings(nas) == {"language": "it", "kept": 1}
    assert rm.nas_scripts_stale() is False


def test_auto_language_writes_the_resolved_one(nas, tmp_path, monkeypatch):
    _desktop_language(tmp_path, monkeypatch, "auto")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.setenv("LANG", "pt_BR.UTF-8")
    ok, msg, _cmd = rm.push_scripts_to_nas()
    assert ok, msg
    assert _nas_settings(nas) == {"language": "pt"}
    # A service without the session's LANG does not flag a language already set.
    monkeypatch.setenv("LANG", "C")
    assert rm.nas_scripts_stale() is False
    os.remove(nas / "settings.json")
    assert rm.nas_scripts_stale() is True


def test_local_only_mode_writes_nothing_to_the_nas(nas, tmp_path, monkeypatch):
    monkeypatch.setattr(rm.appconfig, "nas_enabled", lambda: False)
    _desktop_language(tmp_path, monkeypatch, "fr")
    assert rm.push_scripts_to_nas() == (True, None, None)
    assert not nas.exists()
