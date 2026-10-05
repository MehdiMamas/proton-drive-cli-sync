"""La fenêtre Qt se construit sans écran (plateforme offscreen)."""

import os

import pytest


def test_window_builds(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from ui import theme
    from ui.shell import MainWindow

    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    window = MainWindow()
    window.show()
    assert window.stack.count() == 4
    assert window.mappings.run_btn.objectName() == "Primary"
    assert window.mappings.stop_btn.objectName() == "Danger"
    assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"
    window.close()
