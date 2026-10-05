"""Jetons visuels. Inspirés de l'identité Proton, sans logo ni marque officielle."""

COLORS = {
    "purple": "#6D4AFF",
    "purple_hover": "#5B3CE0",
    "text": "#1C1B24",
    "muted": "#5C5A66",
    "canvas": "#F5F4FA",
    "card": "#FFFFFF",
    "border": "#E4E1EE",
    "danger": "#D2294B",
    "warning": "#E8A200",
    "success": "#1A9E57",
}

STYLESHEET = """
QMainWindow, QWidget#AppRoot, QWidget#Sidebar, QWidget#PageHost {
    background: %(canvas)s;
    color: %(text)s;
}
QFrame#Card {
    background: %(card)s;
    border: 1px solid %(border)s;
    border-radius: 8px;
}
QFrame#TopBar {
    background: %(card)s;
    border: none;
    border-bottom: 1px solid %(border)s;
}
QLabel {
    color: %(text)s;
    background: transparent;
}
QLabel#Muted, QLabel#Footer {
    color: %(muted)s;
}
QLabel#Title {
    font-size: 18px;
}
QLabel#AccountOk {
    color: %(success)s;
}
QLabel#AccountBad {
    color: %(danger)s;
}
QLabel#AccountWait {
    color: %(muted)s;
}
QPushButton {
    border-radius: 8px;
    padding: 8px 14px;
    background: %(card)s;
    color: %(text)s;
    border: 1px solid %(border)s;
}
QPushButton:hover {
    background: %(canvas)s;
}
QPushButton#Primary {
    background: %(purple)s;
    color: white;
    border: none;
    padding: 8px 18px;
}
QPushButton#Primary:hover {
    background: %(purple_hover)s;
}
QPushButton#Primary:disabled {
    background: #C4B8F5;
    color: white;
}
QPushButton#Danger {
    background: %(card)s;
    color: %(danger)s;
    border: 1px solid %(danger)s;
}
QPushButton#Danger:hover {
    background: #FDECEF;
}
QPushButton#Nav {
    text-align: left;
    border: none;
    border-radius: 8px;
    padding: 10px 14px;
    background: transparent;
}
QPushButton#Nav:checked {
    background: %(card)s;
    color: %(purple)s;
}
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {
    background: %(card)s;
    color: %(text)s;
    border: 1px solid %(border)s;
    border-radius: 8px;
    padding: 6px 8px;
}
QTableWidget {
    background: %(card)s;
    color: %(text)s;
    border: none;
    gridline-color: %(border)s;
    selection-background-color: #EDE7FF;
    selection-color: %(text)s;
}
QHeaderView::section {
    background: %(canvas)s;
    color: %(muted)s;
    border: none;
    border-bottom: 1px solid %(border)s;
    padding: 6px;
}
QCheckBox, QRadioButton {
    background: transparent;
    color: %(text)s;
}
QScrollArea {
    border: none;
    background: transparent;
}
""" % COLORS


def apply(app):
    """Fusion + feuille de style. Inter si elle est installée, sinon DejaVu Sans."""
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    if not isinstance(app, QApplication):
        return
    app.setStyle("Fusion")
    families = set(QFontDatabase.families())
    if "Inter" in families:
        app.setFont(QFont("Inter", 10))
    elif "DejaVu Sans" in families:
        app.setFont(QFont("DejaVu Sans", 10))
    app.setStyleSheet(STYLESHEET)
