#!/usr/bin/env python3
"""proton-drive-sync-doctor: read-only report for bug reports.

Prints the install, CLI, systemd, settings, mapping and session facts needed to
diagnose an unattended run. It never writes, never uploads and never starts a
unit. Every external command has a timeout. A failure becomes a line in the
report, and the exit code is always 0.

Use --redact before pasting the report anywhere public: home paths become `~`,
other absolute paths become <path#n>, and e-mail addresses become <account>.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CMD_TIMEOUT = 10

try:
    import config as appconfig
except Exception:  # config absent or broken: the report still runs
    appconfig = None

SYNC_SERVICE = "proton-sync.service"
SYNC_TIMER = "proton-sync.timer"
REALTIME_UNITS = ("proton-watch.service", "proton-consume.service")
NA = "not available"


# ---------- helpers ----------

def run_cmd(args, timeout=CMD_TIMEOUT):
    """(ok, text). Never raises."""
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout)
    except FileNotFoundError:
        return False, "%s: %s (command not found)" % (args[0], NA)
    except subprocess.TimeoutExpired:
        return False, "%s: timed out after %ss" % (args[0], timeout)
    except Exception as exc:  # report, never fatal
        return False, "%s: %s: %s" % (args[0], type(exc).__name__, exc)
    text = (r.stdout or "") + (("\n" + r.stderr) if r.stderr.strip() else "")
    return r.returncode == 0, text.strip()


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError) as exc:
        return None, "unreadable (%s)" % type(exc).__name__


def compact(data, limit=1500):
    try:
        text = json.dumps(data, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        text = repr(data)
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


def version_tuple(text):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else None


# ---------- redaction ----------

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_ABS_PATH = re.compile(r"(?<![\w./~<>#:=@-])/(?:[^\s\"'<>|;,()\[\]{}]+)")
_HOME_PATH = re.compile(r"(?<![\w.<>#-])~(/[^\s\"'<>|;,()\[\]{}]+)")
# Fixed system and application locations: not personal, useful in a report.
_KEEP_ABS = ("/usr/", "/proc/", "/sys/", "/bin/", "/etc/systemd/",
             "/run/user/", "/lib/")
_KEEP_HOME = ("/.proton-drive-sync", "/.config/proton-drive-sync",
              "/.config/systemd/user")


class Redactor:
    """Replaces personal strings. Known values (seen in settings and mappings)
    are replaced literally first, so a path with spaces cannot leak a tail."""

    def __init__(self):
        self.known = []
        self.numbers = {}

    def number(self, path):
        if path not in self.numbers:
            self.numbers[path] = len(self.numbers) + 1
        return "<path#%d>" % self.numbers[path]

    def learn(self, value):
        if isinstance(value, str) and len(value) > 1 and "/" in value:
            self.known.append(value.rstrip("/"))

    def learn_tree(self, data):
        if isinstance(data, dict):
            for v in data.values():
                self.learn_tree(v)
        elif isinstance(data, list):
            for v in data:
                self.learn_tree(v)
        elif isinstance(data, str) and data.startswith("/"):
            self.learn(data)

    def apply(self, text):
        home = os.path.expanduser("~").rstrip("/")
        for value in sorted(set(self.known), key=len, reverse=True):
            if value and value != home:
                text = text.replace(value, self.number(value))
        text = _EMAIL.sub("<account>", text)
        if home and home != "/":
            text = text.replace(home, "~")
        text = _HOME_PATH.sub(self._home_sub, text)
        return _ABS_PATH.sub(self._abs_sub, text)

    def _home_sub(self, m):
        rest = m.group(1)
        if rest.startswith(_KEEP_HOME):
            return m.group(0)
        return "~/" + self.number(rest.lstrip("/"))

    def _abs_sub(self, m):
        path = m.group(0)
        if path.startswith(_KEEP_ABS):
            return path
        return self.number(path)


# ---------- report sections ----------

class Report:
    def __init__(self):
        self.lines = []

    def section(self, title):
        self.lines.append("")
        self.lines.append("== %s ==" % title)

    def add(self, text=""):
        for line in str(text).splitlines() or [""]:
            self.lines.append(line)

    def kv(self, key, value):
        self.add("%s: %s" % (key, value))

    def text(self):
        return "\n".join(self.lines) + "\n"


def engine_version():
    version = None
    for name in ("VERSION",):
        try:
            with open(os.path.join(APP_DIR, name), "r", encoding="utf-8") as f:
                version = f.read().strip()
        except OSError:
            pass
    commit = None
    if os.path.isdir(os.path.join(APP_DIR, ".git")):
        ok, out = run_cmd(["git", "-C", APP_DIR, "rev-parse", "--short", "HEAD"])
        if ok:
            commit = out
    return version, commit


def section_install(rep):
    rep.section("Install")
    version, commit = engine_version()
    rep.kv("fork version", version or "unknown (no VERSION file)")
    rep.kv("git commit", commit or "not a git checkout")
    rep.kv("program directory", APP_DIR)
    rep.kv("python", sys.version.split()[0])
    rep.kv("HOME", os.path.expanduser("~"))
    rep.kv("XDG_CONFIG_HOME", os.environ.get("XDG_CONFIG_HOME") or "(unset)")


def section_cli(rep):
    rep.section("Proton CLI")
    chain = [
        ("PROTON_DRIVE_CLI", os.environ.get("PROTON_DRIVE_CLI") or "(unset)"),
        ("settings proton_cli_path",
         (appconfig.proton_cli_path() if appconfig else None) or "(unset)"),
        ("next to the scripts",
         os.path.join(APP_DIR, "proton-drive")
         if os.access(os.path.join(APP_DIR, "proton-drive"), os.X_OK)
         else "(not found)"),
        ("on PATH", shutil.which("proton-drive") or "(not found)"),
    ]
    for label, value in chain:
        rep.kv("resolve: " + label, value)
    cli = None
    try:
        cli = appconfig.resolve_proton_cli() if appconfig else None
    except Exception as exc:
        rep.kv("resolved", "error (%s)" % type(exc).__name__)
    if cli is None:
        cli = shutil.which("proton-drive")
    rep.kv("resolved", cli or NA)
    version = None
    if cli and os.path.exists(cli):
        ok, out = run_cmd([cli, "--version"])
        rep.kv("proton-drive --version", out.splitlines()[0] if out else NA)
        version = version_tuple(out) if ok else None
    else:
        rep.kv("proton-drive --version", NA + " (CLI not found)")
    return version


def section_systemd(rep):
    rep.section("systemd (user)")
    if shutil.which("systemctl") is None:
        rep.add("systemctl: " + NA)
    else:
        for unit in (SYNC_SERVICE, SYNC_TIMER) + REALTIME_UNITS:
            rep.add("-- %s" % unit)
            ok, out = run_cmd(["systemctl", "--user", "cat", unit])
            rep.add(out if out else NA)
            ok, out = run_cmd(["systemctl", "--user", "show", unit, "-p",
                               "Result", "-p", "ExecMainStatus",
                               "-p", "ActiveState"])
            rep.add(out if out else NA)
        ok, out = run_cmd(["systemctl", "--user", "list-timers", SYNC_TIMER,
                           "--no-pager"])
        rep.add("-- list-timers")
        rep.add(out if out else NA)
    rep.add("-- linger")
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    if shutil.which("loginctl") is None or not user:
        rep.add("linger: " + NA)
    else:
        ok, out = run_cmd(["loginctl", "show-user", user, "-p", "Linger"])
        rep.add(out if out else NA)
    rep.add("-- journal (last 50 lines of %s)" % SYNC_SERVICE)
    if shutil.which("journalctl") is None:
        rep.add("journalctl: " + NA)
    else:
        ok, out = run_cmd(["journalctl", "--user", "-u", SYNC_SERVICE,
                           "-n", "50", "--no-pager"])
        rep.add(out if out else NA)


def section_state(rep, redactor):
    rep.section("Last run and health")
    data_dir = getattr(appconfig, "DATA_DIR", None) or os.path.expanduser(
        "~/.proton-drive-sync")
    for label, attr, name in (("last-run.json", "LAST_RUN_FILE", "last-run.json"),
                              ("health.json", "HEALTH_FILE", "health.json")):
        path = getattr(appconfig, attr, None) or os.path.join(data_dir, name)
        data, err = read_json(path)
        redactor.learn_tree(data)
        rep.kv(label, compact(data) if err is None else err)


def mappings_file(explicit):
    if explicit:
        return explicit
    try:
        import schedule_manager
        return schedule_manager.read_service_mappings_path()
    except Exception:
        return None


def section_settings(rep, redactor, cli_version, mappings_arg):
    rep.section("Settings")
    if appconfig is None:
        rep.add("config module: " + NA)
    else:
        settings, err = read_json(getattr(appconfig, "_SETTINGS_PATH", ""))
        rep.kv("settings file", getattr(appconfig, "_SETTINGS_PATH", NA))
        if err is not None:
            rep.kv("settings", err)
        else:
            redactor.learn_tree(settings)
            if isinstance(settings, dict):
                for key in sorted(settings):
                    if "account" in key or "email" in key:
                        settings = dict(settings, **{key: "<hidden>"})
            rep.kv("settings (as stored)", compact(settings))
        try:
            modern = bool(cli_version and cli_version >= (0, 5, 0))
            effective = appconfig.effective_rename_ext(lambda: modern)
            rep.kv("rename-ext effective", "%s (CLI >= 0.5.0: %s)"
                   % ("on" if effective else "off",
                      "yes" if modern else "no or unknown"))
        except Exception as exc:
            rep.kv("rename-ext effective", "error (%s)" % type(exc).__name__)
        for label, fn in (("max_delete_min", "max_delete_min"),
                          ("max_delete_ratio", "max_delete_ratio"),
                          ("cli_stall_minutes", "cli_stall_minutes")):
            try:
                rep.kv(label, getattr(appconfig, fn)())
            except Exception as exc:
                rep.kv(label, "error (%s)" % type(exc).__name__)

    rep.section("Mappings")
    path = mappings_file(mappings_arg)
    rep.kv("mappings file", path or "unknown (no unit and no --mappings)")
    if not path:
        return
    data, err = read_json(path)
    if err is not None:
        rep.kv("mappings", err)
        return
    redactor.learn_tree(data)
    if isinstance(data, dict):
        mappings = data.get("mappings") or []
        global_ex = data.get("exclusions") or {}
    else:
        mappings, global_ex = data, {}
    rep.kv("global exclusions", _ex_counts(global_ex))
    if not isinstance(mappings, list):
        rep.kv("mappings", "unexpected shape")
        return
    for i, m in enumerate(mappings, 1):
        if not isinstance(m, dict):
            rep.add("mapping %d: unexpected shape" % i)
            continue
        rep.add("mapping %d: type=%s source=%s dest_parent=%s" % (
            i, m.get("type"), m.get("source"), m.get("dest_parent")))
        rep.add("  allow_delete=%s delete_mode=%s excluded_remote=%s "
                "source_kind=%s conflict_mode=%s exclusions=%s" % (
                    m.get("allow_delete"), m.get("delete_mode"),
                    m.get("excluded_remote"), m.get("source_kind"),
                    m.get("conflict_mode"), _ex_counts(m.get("exclusions"))))


def _ex_counts(ex):
    if not isinstance(ex, dict):
        return "names=0 patterns=0"
    names = ex.get("names") or []
    patterns = ex.get("patterns") or []
    return "names=%d patterns=%d" % (len(names), len(patterns))


def section_session(rep):
    rep.section("Session (unattended auth)")
    bus = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    rep.kv("DBUS_SESSION_BUS_ADDRESS", "set" if bus else "not set")
    rep.kv("PROTON_DRIVE_CREDENTIALS_STORE",
           os.environ.get("PROTON_DRIVE_CREDENTIALS_STORE") or "(unset)")
    if shutil.which("busctl") is None:
        rep.kv("Secret Service (org.freedesktop.secrets)", NA + " (busctl missing)")
    else:
        ok, out = run_cmd(["busctl", "--user", "status",
                           "org.freedesktop.secrets"])
        rep.kv("Secret Service (org.freedesktop.secrets)",
               "reachable" if ok else "not reachable")


def build_report(mappings_arg=None, redact=False):
    rep = Report()
    redactor = Redactor()
    rep.add("proton-drive-sync doctor (read-only)")
    rep.add("Redaction: %s" % ("on" if redact else
                               "OFF - run with --redact before pasting this publicly"))
    steps = [section_install]
    for fn in steps:
        _guard(rep, fn, rep)
    cli_version = _guard(rep, section_cli, rep)
    _guard(rep, section_systemd, rep)
    _guard(rep, section_state, rep, redactor)
    _guard(rep, section_settings, rep, redactor, cli_version, mappings_arg)
    _guard(rep, section_session, rep)
    text = rep.text()
    return redactor.apply(text) if redact else text


def _guard(rep, fn, *args):
    """A broken section is a line in the report, not a crash."""
    try:
        return fn(*args)
    except Exception as exc:
        rep.add("%s failed: %s: %s" % (fn.__name__, type(exc).__name__, exc))
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="proton-drive-sync-doctor",
        description="Read-only diagnostic report. Exit code is always 0.")
    parser.add_argument("--redact", action="store_true",
                        help="hide e-mails and personal paths (use before pasting)")
    parser.add_argument("--mappings", help="mappings file (default: the one in the unit)")
    args = parser.parse_args(argv)
    try:
        sys.stdout.write(build_report(args.mappings, args.redact))
    except Exception as exc:  # last resort: still a report, still exit 0
        sys.stdout.write("doctor failed: %s: %s\n" % (type(exc).__name__, exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
