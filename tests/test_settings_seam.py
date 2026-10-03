"""PROTON_SYNC_SETTINGS is evaluated at import and defaults to the historical path."""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _python(code, home, extra_env=None):
    env = os.environ.copy()
    env.pop("PROTON_SYNC_SETTINGS", None)
    env["HOME"] = str(home)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
    )


def test_settings_path_defaults_when_env_unset(tmp_path):
    home = tmp_path / "seam-home"
    home.mkdir()
    code = (
        "import os, config, i18n\n"
        "expect = os.path.join(config.APP_DIR, 'settings.json')\n"
        "assert config._SETTINGS_PATH == expect, config._SETTINGS_PATH\n"
        "assert i18n.SETTINGS_PATH == os.path.join(i18n.APP_DIR, 'settings.json')\n"
        "print('ok')\n"
    )
    result = _python(code, home)
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_settings_path_defaults_when_env_empty(tmp_path):
    home = tmp_path / "seam-home-empty"
    home.mkdir()
    code = (
        "import os, config, i18n\n"
        "expect = os.path.join(config.APP_DIR, 'settings.json')\n"
        "assert config._SETTINGS_PATH == expect, config._SETTINGS_PATH\n"
        "assert i18n.SETTINGS_PATH == os.path.join(i18n.APP_DIR, 'settings.json')\n"
        "print('ok')\n"
    )
    result = _python(code, home, {"PROTON_SYNC_SETTINGS": ""})
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_settings_path_follows_env_when_set(tmp_path):
    home = tmp_path / "seam-home"
    home.mkdir()
    chosen = tmp_path / "custom-settings.json"
    code = (
        "import os, config, i18n\n"
        "chosen = os.environ['PROTON_SYNC_SETTINGS']\n"
        "assert config._SETTINGS_PATH == chosen\n"
        "assert i18n.SETTINGS_PATH == chosen\n"
        "print('ok')\n"
    )
    result = _python(code, home, {"PROTON_SYNC_SETTINGS": str(chosen)})
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
