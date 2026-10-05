"""La fenêtre Qt se construit sans écran (plateforme offscreen)."""

import os

import pytest

# Icônes de la barre précédente, remises sur les boutons Mappings.


def test_window_builds(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton, QScrollArea

    from ui import theme
    from ui.shell import MainWindow

    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    window = MainWindow()
    window.show()
    assert window.stack.count() == 2
    assert window.mappings.run_btn.objectName() == "Primary"
    assert window.mappings.stop_btn.objectName() == "Danger"
    mappings = window.stack.widget(0)
    labels = [w.text() for w in mappings.findChildren(QPushButton)]
    labels += [w.text() for w in mappings.findChildren(QCheckBox)]
    assert any(text.startswith("📂") for text in labels)
    assert any(text.startswith("▶") for text in labels)
    assert window.mappings.excl_summary.text().startswith("🌐")
    nav = [
        button.text() for button in window._qt.findChildren(QPushButton)
        if button.objectName() == "Nav"
    ]
    assert [text[0] for text in nav] == ["📂", "⚙"]
    assert isinstance(window.settings.scroll, QScrollArea)
    assert window.stack.widget(1).findChild(QScrollArea) is window.settings.scroll
    assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"
    window.close()


def test_window_reloads_the_last_mappings_file(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    import json
    import config
    from PySide6.QtWidgets import QApplication
    from ui.shell import MainWindow

    folder = tmp_path / "Docs"
    folder.mkdir()
    cfg = tmp_path / "mappings.json"
    cfg.write_text(json.dumps([{
        "type": "folder",
        "source": str(folder),
        "dest_parent": "/my-files/Docs",
    }]), encoding="utf-8")
    assert config.set_last_mappings_path(str(cfg))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert os.path.normpath(window.doc.path) == os.path.normpath(str(cfg))
    from ui.live_sync import short_commit
    commit = short_commit(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if commit:
        assert commit in window._qt.windowTitle()
    window.close()
    app.processEvents()
