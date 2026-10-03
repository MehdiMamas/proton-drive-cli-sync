"""Where settings.json lives.

config.py and i18n.py both call settings_path(). This module imports neither
of them, so those imports cannot cycle. Nothing here raises: a missing home,
a read-only config directory, or a failed copy falls back to a path.
"""

import os
import shutil
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))

_MIGRATED_NOTICE = "Settings copied to {p}. The previous file was left in place."
_UNWRITABLE_NOTICE = "Could not write settings to {p}; reading {legacy} instead."
_unwritable_said = False


def xdg_config_home():
    raw = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if raw:
        return raw
    return os.path.join(os.path.expanduser("~"), ".config")


def xdg_settings_path():
    return os.path.join(xdg_config_home(), "proton-drive-sync", "settings.json")


def legacy_settings_path():
    return os.path.join(APP_DIR, "settings.json")


def _say(template, **kwargs):
    text = template
    module = sys.modules.get("i18n")
    translate = getattr(module, "_", None) if module is not None else None
    if callable(translate):
        try:
            text = translate(template)
        except Exception:
            text = template
    try:
        print(text.format(**kwargs), file=sys.stderr)
    except Exception:
        pass


def _migrate_legacy(legacy, dest):
    """Copy legacy settings onto dest. Leave legacy in place. Mode 0600."""
    tmp = dest + ".tmp"
    try:
        os.makedirs(os.path.dirname(dest), mode=0o700, exist_ok=True)
        shutil.copyfile(legacy, tmp)
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
        os.chmod(dest, 0o600)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
    _say(_MIGRATED_NOTICE, p=dest)
    return True


def settings_path():
    """Path of settings.json for this process.

    1. PROTON_SYNC_SETTINGS, when set and non-empty.
    2. The XDG path, when that file already exists.
    3. A one-time copy of APP_DIR/settings.json into the XDG path, when the
       legacy file exists and the copy succeeds. The legacy file stays.
    4. The legacy file, when the XDG directory cannot be written.
    5. The XDG path (created on the first write).
    """
    global _unwritable_said
    try:
        override = os.environ.get("PROTON_SYNC_SETTINGS", "").strip()
        if override:
            return override
        dest = xdg_settings_path()
        try:
            dest_exists = os.path.isfile(dest)
        except OSError:
            dest_exists = False
        if dest_exists:
            return dest
        legacy = legacy_settings_path()
        try:
            legacy_exists = os.path.isfile(legacy)
        except OSError:
            legacy_exists = False
        if legacy_exists:
            if _migrate_legacy(legacy, dest):
                return dest
            if not _unwritable_said:
                _unwritable_said = True
                _say(_UNWRITABLE_NOTICE, p=dest, legacy=legacy)
            return legacy
        return dest
    except Exception:
        try:
            return legacy_settings_path()
        except Exception:
            return "settings.json"
