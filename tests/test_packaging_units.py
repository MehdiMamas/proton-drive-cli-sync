"""Phase 6: escaped systemd units, doctor, launchers and the Arch PKGBUILD."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import realtime_manager
import schedule_manager
import unitexec

REPO = Path(__file__).resolve().parents[1]
ARCH = REPO / "packaging" / "arch"
PACKAGED = "/usr/lib/proton-drive-cli-sync"


def _exec_line(text):
    return next(l for l in text.splitlines() if l.startswith("ExecStart="))


@pytest.mark.parametrize("arg,expected", [
    ("/plain/path.json", "/plain/path.json"),
    ("/with space/m.json", '"/with space/m.json"'),
    ('/with"quote/m.json', '"/with\\"quote/m.json"'),
    ("/100%/m.json", "/100%%/m.json"),
    ("/back\\slash/m.json", '"/back\\\\slash/m.json"'),
    ("/cost$/m.json", "/cost$$/m.json"),
    ("", '""'),
    ('a b"c%d', '"a b\\"c%%d"'),
])
def test_systemd_quote_spaces_quotes_percent_backslash(arg, expected):
    assert unitexec.systemd_quote(arg) == expected
    # What systemd reads back is the original text (specifiers unescaped).
    assert unitexec.split_exec(expected) == [arg]


def _use_unit_dir(monkeypatch, tmp_path):
    unit_dir = tmp_path / "user"
    unit_dir.mkdir()
    monkeypatch.setattr(schedule_manager, "SYSTEMD_USER_DIR", str(unit_dir))
    monkeypatch.setattr(schedule_manager, "SERVICE_PATH",
                        str(unit_dir / schedule_manager.SERVICE_NAME))
    return unit_dir


@pytest.mark.parametrize("name", [
    "my maps/mappings.json",
    'quo"te/mappings.json',
    "100%/mappings.json",
    "back\\slash/mappings.json",
])
@pytest.mark.parametrize("delete", [False, True])
def test_service_unit_with_space_in_mappings_path_roundtrips(
        tmp_path, monkeypatch, name, delete):
    _use_unit_dir(monkeypatch, tmp_path)
    path = str(tmp_path) + "/" + name
    text = schedule_manager.build_service_text(path, delete=delete)
    Path(schedule_manager.SERVICE_PATH).write_text(text, encoding="utf-8")
    assert schedule_manager.read_service_mappings_path() == path
    assert schedule_manager.read_service_delete() is delete


def test_legacy_unquoted_unit_still_parsed(tmp_path, monkeypatch):
    _use_unit_dir(monkeypatch, tmp_path)
    Path(schedule_manager.SERVICE_PATH).write_text(
        "[Service]\n"
        "Environment=PROTON_DRIVE_CLI=/opt/app/proton-drive\n"
        "ExecStart=/usr/bin/python3 /opt/app/proton_sync.py /data/mappings.json --delete\n",
        encoding="utf-8")
    assert schedule_manager.read_service_mappings_path() == "/data/mappings.json"
    assert schedule_manager.read_service_delete() is True
    Path(schedule_manager.SERVICE_PATH).write_text(
        "[Service]\nExecStart=/usr/bin/python3 /opt/app/proton_sync.py /data/m.json\n",
        encoding="utf-8")
    assert schedule_manager.read_service_mappings_path() == "/data/m.json"
    assert schedule_manager.read_service_delete() is False


def test_legacy_consumer_unit_still_parsed(tmp_path, monkeypatch):
    consume = tmp_path / "proton-consume.service"
    consume.write_text(
        "[Service]\nExecStart=/usr/bin/python3 /opt/app/realtime_consumer.py /data/m.json\n",
        encoding="utf-8")
    monkeypatch.setattr(realtime_manager, "CONSUME_PATH", str(consume))
    assert realtime_manager.read_units_mappings_path() == "/data/m.json"


def test_packaged_install_uses_usr_bin_launcher(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule_manager, "APP_DIR", PACKAGED)
    monkeypatch.setattr(schedule_manager, "DEFAULT_ENGINE", PACKAGED + "/proton_sync.py")
    monkeypatch.setattr(schedule_manager, "DEFAULT_CLI", PACKAGED + "/proton-drive")
    path = str(tmp_path / "my maps" / "mappings.json")
    text = schedule_manager.build_service_text(path, delete=True)
    line = _exec_line(text)
    assert line.startswith("ExecStart=/usr/bin/proton-drive-sync ")
    assert "python3" not in line and PACKAGED not in line
    assert "PROTON_DRIVE_CLI=" not in text  # nothing to point at under /usr/lib
    assert "RestartPreventExitStatus=5" in text
    Path(schedule_manager.SERVICE_PATH).parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(schedule_manager, "SERVICE_PATH",
                        str(tmp_path / "proton-sync.service"))
    Path(schedule_manager.SERVICE_PATH).write_text(text, encoding="utf-8")
    assert schedule_manager.read_service_mappings_path() == path
    assert schedule_manager.read_service_delete() is True


def test_unpackaged_install_keeps_python_path(monkeypatch, tmp_path):
    text = schedule_manager.build_service_text(str(tmp_path / "m.json"))
    line = _exec_line(text)
    assert line.startswith("ExecStart=/usr/bin/python3 ")
    assert "Environment=PROTON_DRIVE_CLI=" in text


def test_consumer_unit_generation_escaped(tmp_path, monkeypatch):
    app = str(tmp_path / "my app")
    monkeypatch.setattr(realtime_manager, "H_ENGINE_DIR", app)
    path = str(tmp_path / "my maps" / "100%.json")
    for build, script in ((realtime_manager.build_consume_service_text,
                           "realtime_consumer.py"),
                          (realtime_manager.build_watch_service_text,
                           "local_watcher.py")):
        text = build(path)
        args = unitexec.split_exec(_exec_line(text)[len("ExecStart="):])
        assert args == ["/usr/bin/python3", app + "/" + script, path]
        assert '"%s"' % (app + "/" + script) in text
        assert "100%%.json" in text
        env = next(l for l in text.splitlines() if l.startswith("Environment="))
        assert env.startswith('Environment="PROTON_DRIVE_CLI=') or \
            env.startswith("Environment=PROTON_DRIVE_CLI=")
    consume = tmp_path / "proton-consume.service"
    consume.write_text(realtime_manager.build_consume_service_text(path),
                       encoding="utf-8")
    monkeypatch.setattr(realtime_manager, "CONSUME_PATH", str(consume))
    assert realtime_manager.read_units_mappings_path() == path


# ---------- doctor ----------

def _doctor(args, home, env_extra=None, path_env=None):
    env = {k: v for k, v in os.environ.items()
           if k not in ("PROTON_DRIVE_CLI", "DBUS_SESSION_BUS_ADDRESS")}
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(Path(home) / ".config")
    if path_env is not None:
        env["PATH"] = path_env
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(REPO / "doctor.py")] + args,
                          cwd=str(REPO), env=env, capture_output=True,
                          text=True, timeout=120)


def test_doctor_redact_removes_emails_and_paths(tmp_path):
    home = tmp_path / "home" / "alice"
    (home / ".proton-drive-sync").mkdir(parents=True)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "language": "en",
        "account_name": "alice@example.org",
        "proton_cli_path": "/opt/secret-tools/proton-drive",
    }), encoding="utf-8")
    mappings = tmp_path / "mappings.json"
    mappings.write_text(json.dumps({"mappings": [{
        "type": "folder",
        "source": "/mnt/secret-nas/private photos",
        "dest_parent": "/my-files/Backups of bob@example.net",
        "allow_delete": False,
        "delete_mode": "trash",
    }]}), encoding="utf-8")
    (home / ".proton-drive-sync" / "last-run.json").write_text(json.dumps({
        "last_full": {"exit": 0, "source": "/mnt/secret-nas/private photos",
                      "user": "carol@example.com"}}), encoding="utf-8")
    plain = _doctor(["--mappings", str(mappings)], home,
                    {"PROTON_SYNC_SETTINGS": str(settings)})
    assert plain.returncode == 0, plain.stderr
    assert "secret-nas" in plain.stdout  # the unredacted report shows it
    redacted = _doctor(["--redact", "--mappings", str(mappings)], home,
                       {"PROTON_SYNC_SETTINGS": str(settings)})
    assert redacted.returncode == 0, redacted.stderr
    out = redacted.stdout
    for secret in ("alice@example.org", "bob@example.net", "carol@example.com",
                   "secret-nas", "private photos", "secret-tools",
                   str(tmp_path), "/home/alice"):
        assert secret not in out, secret
    assert "mapping 1: type=folder" in out
    assert "allow_delete=False" in out


def test_doctor_survives_missing_systemctl_and_cli(tmp_path):
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    settings = tmp_path / "settings.json"
    settings.write_text('{"language": "en"}', encoding="utf-8")
    result = _doctor([], home, {"PROTON_SYNC_SETTINGS": str(settings)},
                     path_env=str(empty))
    assert result.returncode == 0, result.stderr
    assert "systemctl: not available" in result.stdout
    assert "proton-drive --version: not available" in result.stdout
    assert "Secret Service" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr


# ---------- packaging ----------

def test_pkgbuild_syntax():
    pkgbuild = ARCH / "PKGBUILD"
    assert pkgbuild.is_file()
    result = subprocess.run(["bash", "-n", str(pkgbuild)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    text = pkgbuild.read_text(encoding="utf-8")
    body = text[text.index("package() {"):]
    # Destinations (${pkgdir}/usr/...) are not repository files.
    body = re.sub(r"\$\{pkgdir\}\S*", "", body)
    body = re.sub(r"\$\{_lib\}\S*", "", body)
    names = set(re.findall(
        r"[A-Za-z0-9_./-]+\.(?:py|png|md|json|desktop|install)\b", body))
    names |= set(re.findall(r"packaging/arch/launchers/[\w-]+", body))
    names |= {"LICENSE", "VERSION"} & set(re.findall(r"\b(LICENSE|VERSION)\b", body))
    assert names, "package() references no files?"
    missing = [n for n in sorted(names)
               if "${" not in n and not (REPO / n).exists()]
    assert not missing, missing
    install = re.search(r"^install=(\S+)", text, re.MULTILINE).group(1)
    assert (ARCH / install).is_file()
    for glob_pattern in re.findall(r"in (locale/[^;\s]+)", body):
        assert list(REPO.glob(glob_pattern)), glob_pattern
    assert "depends=('python' 'tk' 'python-pyinotify')" in text
    assert "check()" in text and "pytest" in text


@pytest.mark.parametrize("launcher,script", [
    ("proton-drive-sync", "proton_sync.py"),
    ("proton-drive-sync-gui", "proton_mapping_editor.py"),
    ("proton-drive-sync-doctor", "doctor.py"),
])
def test_launchers_exec_correct_scripts(launcher, script):
    text = (ARCH / "launchers" / launcher).read_text(encoding="utf-8")
    lines = [l for l in text.splitlines() if l.strip()]
    assert lines[0] == "#!/bin/sh"
    assert lines[1] == 'exec python3 %s/%s "$@"' % (PACKAGED, script)
    assert (REPO / script).is_file()
    assert unitexec.PACKAGED_DIR == PACKAGED
    assert unitexec.PACKAGED_LAUNCHERS.get("proton_sync.py") == "/usr/bin/proton-drive-sync"
