"""Boîtes et boutons partagés. Les textes viennent de _()."""

try:
    from i18n import _
except ImportError:
    def _(s):
        return s


def qt_parent(parent):
    """QWidget réel. La fenêtre est une enveloppe : son widget est ``_qt``."""
    inner = getattr(parent, "_qt", None)
    return inner if inner is not None else parent


def _box(parent, title, text, buttons):
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(qt_parent(parent))
    box.setWindowTitle(title or "")
    box.setText(text or "")
    box.setStandardButtons(buttons)
    return box


def info(parent, text, title):
    from PySide6.QtWidgets import QMessageBox
    box = _box(parent, title, text, QMessageBox.Ok)
    box.exec()


def warn(parent, text, title):
    from PySide6.QtWidgets import QMessageBox
    box = _box(parent, title, text, QMessageBox.Ok)
    box.setIcon(QMessageBox.Warning)
    box.exec()


def error(parent, text, title):
    from PySide6.QtWidgets import QMessageBox
    box = _box(parent, title, text, QMessageBox.Ok)
    box.setIcon(QMessageBox.Critical)
    box.exec()


def confirm(parent, text, title, ok_text, cancel_text):
    """True si l'utilisateur confirme."""
    from PySide6.QtWidgets import QMessageBox
    box = _box(parent, title, text, QMessageBox.Ok | QMessageBox.Cancel)
    box.button(QMessageBox.Ok).setText(ok_text)
    box.button(QMessageBox.Cancel).setText(cancel_text)
    return box.exec() == QMessageBox.Ok


def confirm_check(parent, text, title, ok_text, cancel_text, check_text):
    """(accepté, case cochée)."""
    from PySide6.QtWidgets import QMessageBox
    box = _box(parent, title, text, QMessageBox.Ok | QMessageBox.Cancel)
    box.setIcon(QMessageBox.Warning)
    box.button(QMessageBox.Ok).setText(ok_text)
    box.button(QMessageBox.Cancel).setText(cancel_text)
    box.setCheckBox(None)
    from PySide6.QtWidgets import QCheckBox
    box.setCheckBox(QCheckBox(check_text))
    accepted = box.exec() == QMessageBox.Ok
    return accepted, bool(box.checkBox().isChecked()) if box.checkBox() else False


def card(parent):
    from PySide6.QtWidgets import QFrame, QVBoxLayout
    frame = QFrame(parent)
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(8)
    return frame, layout


def hline_buttons(*buttons):
    from PySide6.QtWidgets import QHBoxLayout, QWidget
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for button in buttons:
        layout.addWidget(button)
    layout.addStretch(1)
    return row
