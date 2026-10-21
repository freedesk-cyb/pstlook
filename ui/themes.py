from __future__ import annotations

from string import Template

from PySide6.QtGui import QColor, QPalette

THEMES: dict[str, dict[str, object]] = {
    "claro": {
        "label": "Claro profesional",
        "colors": {
            "bg": "#f5f7fb",
            "surface": "#ffffff",
            "surface_alt": "#f1f3f4",
            "topbar": "#ffffff",
            "text": "#1f2937",
            "muted": "#6b7280",
            "border": "#e1e5ea",
            "accent": "#1a73e8",
            "accent_hover": "#1765cc",
            "accent_pressed": "#1355aa",
            "accent_text": "#ffffff",
            "selection": "#dbe8fd",
            "selection_text": "#174ea6",
            "hover": "#eaf1fb",
            "header": "#f8f9fb",
            "splitter": "#dfe3e8",
            "scroll": "#c4c9d1",
            "scroll_hover": "#a9b0ba",
            "disabled": "#9aa0a6",
            "progress_bg": "#e8eaed",
        },
    },
    "oscuro": {
        "label": "Oscuro grafito",
        "colors": {
            "bg": "#101419",
            "surface": "#181e25",
            "surface_alt": "#222a33",
            "topbar": "#151b21",
            "text": "#e8ecf2",
            "muted": "#98a4b3",
            "border": "#2b3440",
            "accent": "#4f8cff",
            "accent_hover": "#6aa0ff",
            "accent_pressed": "#3b76e0",
            "accent_text": "#ffffff",
            "selection": "#263f65",
            "selection_text": "#eef5ff",
            "hover": "#212a34",
            "header": "#1e252d",
            "splitter": "#2c3541",
            "scroll": "#3a4553",
            "scroll_hover": "#4d5a6a",
            "disabled": "#66717f",
            "progress_bg": "#2a323c",
        },
    },
    "azul": {
        "label": "Azul corporativo",
        "colors": {
            "bg": "#eef4fb",
            "surface": "#ffffff",
            "surface_alt": "#edf3f9",
            "topbar": "#ffffff",
            "text": "#16283b",
            "muted": "#5c7086",
            "border": "#d6e2ef",
            "accent": "#0f5c99",
            "accent_hover": "#0d4d81",
            "accent_pressed": "#0a3d67",
            "accent_text": "#ffffff",
            "selection": "#d4e8f8",
            "selection_text": "#0b3d66",
            "hover": "#e7f2fb",
            "header": "#f4f9fd",
            "splitter": "#cfdeeb",
            "scroll": "#b9cadb",
            "scroll_hover": "#9fb5c9",
            "disabled": "#92a5b7",
            "progress_bg": "#dfeaf4",
        },
    },
    "verde": {
        "label": "Verde ejecutivo",
        "colors": {
            "bg": "#f0f7f4",
            "surface": "#ffffff",
            "surface_alt": "#ecf4f0",
            "topbar": "#ffffff",
            "text": "#1c2f29",
            "muted": "#62796f",
            "border": "#d5e5de",
            "accent": "#157f63",
            "accent_hover": "#116b53",
            "accent_pressed": "#0d5642",
            "accent_text": "#ffffff",
            "selection": "#d5efe6",
            "selection_text": "#0c4e3c",
            "hover": "#e7f5ef",
            "header": "#f3faf7",
            "splitter": "#cedfd8",
            "scroll": "#b7ccc3",
            "scroll_hover": "#9cb5aa",
            "disabled": "#90a79e",
            "progress_bg": "#dfece6",
        },
    },
    "vino": {
        "label": "Vino ejecutivo",
        "colors": {
            "bg": "#faf3f5",
            "surface": "#ffffff",
            "surface_alt": "#f8eef1",
            "topbar": "#ffffff",
            "text": "#342126",
            "muted": "#7a646b",
            "border": "#ead7dc",
            "accent": "#9b2c46",
            "accent_hover": "#84243a",
            "accent_pressed": "#6d1c2f",
            "accent_text": "#ffffff",
            "selection": "#f2dbe1",
            "selection_text": "#671b2e",
            "hover": "#f8e9ed",
            "header": "#fcf6f8",
            "splitter": "#e5d3d8",
            "scroll": "#d3bcc2",
            "scroll_hover": "#bea3aa",
            "disabled": "#ac969c",
            "progress_bg": "#f1e2e6",
        },
    },
}

_PLANTILLA_QSS = """
QMainWindow, QWidget#centralWidget {
    background: $bg;
}
QWidget#topBar {
    background: $topbar;
    border-bottom: 1px solid $border;
}
QLabel#appTitle {
    color: $text;
    font-size: 16px;
    font-weight: 700;
}
QLabel#panelTitle {
    color: $text;
    font-size: 14px;
    font-weight: 600;
}
QLabel#mutedLabel, QLabel#progressLabel {
    color: $muted;
    font-size: 12px;
}
QLabel#subjectLabel {
    color: $text;
    font-size: 18px;
    font-weight: 650;
    padding-bottom: 3px;
}
QLabel#emailMeta {
    color: $muted;
    font-size: 12px;
}
QPushButton {
    background: $surface_alt;
    color: $text;
    border: 1px solid $border;
    border-radius: 6px;
    padding: 5px 10px;
}
QPushButton:hover {
    background: $hover;
}
QPushButton:pressed {
    background: $selection;
}
QPushButton:disabled {
    color: $disabled;
}
QPushButton#openButton {
    background: $accent;
    color: $accent_text;
    border: none;
    border-radius: 16px;
    padding: 8px 18px;
    font-weight: 600;
}
QPushButton#openButton:hover {
    background: $accent_hover;
}
QPushButton#openButton:pressed {
    background: $accent_pressed;
}
QPushButton#openButton:disabled {
    background: $disabled;
    color: $surface;
}
QPushButton#pdfButton {
    background: $surface;
    color: $accent;
    border: 1px solid $border;
    border-radius: 14px;
    padding: 6px 13px;
    font-weight: 600;
}
QPushButton#pdfButton:hover {
    background: $hover;
    border-color: $accent;
}
QPushButton#pdfButton:pressed {
    background: $selection;
}
QPushButton#pdfButton:disabled {
    color: $disabled;
    border-color: $border;
}
QLineEdit#searchEdit {
    background: $surface_alt;
    border: 1px solid transparent;
    border-radius: 18px;
    padding: 8px 15px;
    color: $text;
    selection-background-color: $selection;
    selection-color: $selection_text;
}
QLineEdit#searchEdit:focus {
    background: $surface;
    border: 1px solid $accent;
}
QComboBox#themeCombo {
    background: $surface_alt;
    color: $text;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 6px 10px;
    min-width: 150px;
}
QComboBox#themeCombo:hover {
    background: $hover;
    border-color: $accent;
}
QComboBox#themeCombo QAbstractItemView {
    background: $surface;
    color: $text;
    border: 1px solid $border;
    selection-background-color: $selection;
    selection-color: $selection_text;
    outline: 0;
    padding: 4px;
}
QMenu {
    background: $surface;
    color: $text;
    border: 1px solid $border;
    padding: 5px;
}
QMenu::item {
    border-radius: 5px;
    padding: 6px 18px;
}
QMenu::item:selected {
    background: $selection;
    color: $selection_text;
}
QTreeView {
    background: transparent;
    border: none;
    outline: none;
    padding: 2px;
    color: $text;
}
QTreeView::item {
    border-radius: 6px;
    padding: 6px 5px;
}
QTreeView::item:hover {
    background: $hover;
}
QTreeView::item:selected {
    background: $selection;
    color: $selection_text;
}
QTableWidget {
    background: $surface;
    border: 1px solid $border;
    border-radius: 8px;
    outline: none;
    color: $text;
    selection-background-color: $selection;
    selection-color: $selection_text;
}
QTableWidget::item {
    padding: 5px 8px;
    border-bottom: 1px solid $border;
}
QTableWidget::item:selected {
    background: $selection;
    color: $selection_text;
}
QHeaderView::section {
    background: $header;
    color: $muted;
    border: none;
    border-bottom: 1px solid $border;
    padding: 7px 8px;
    font-size: 12px;
    font-weight: 600;
}
QTableCornerButton::section {
    background: $header;
    border: none;
}
QFrame#emailHeader {
    background: $surface;
    border-bottom: 1px solid $border;
}
QGroupBox#attachmentsGroup {
    background: $surface;
    border: none;
    border-top: 1px solid $border;
    margin-top: 8px;
    padding-top: 8px;
    font-weight: 600;
    color: $text;
}
QSplitter::handle {
    background: $splitter;
}
QSplitter::handle:horizontal {
    width: 1px;
}
QSplitter::handle:vertical {
    height: 1px;
}
QProgressBar {
    background: $progress_bg;
    border: none;
    border-radius: 4px;
    height: 16px;
    text-align: center;
    color: $text;
    font-size: 10px;
}
QProgressBar::chunk {
    background: $accent;
    border-radius: 4px;
}
QStatusBar {
    background: $bg;
    color: $muted;
}
QToolTip {
    background: $surface;
    color: $text;
    border: 1px solid $border;
    padding: 4px;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: $scroll;
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: $scroll_hover;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: $scroll;
    min-width: 24px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover {
    background: $scroll_hover;
}
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0;
    height: 0;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}
"""


def theme_key(clave: str | None) -> str:
    return clave if clave in THEMES else "claro"


def theme_label(clave: str) -> str:
    return str(THEMES[theme_key(clave)]["label"])


def theme_colors(clave: str) -> dict[str, str]:
    return dict(THEMES[theme_key(clave)]["colors"])


def build_stylesheet(clave: str) -> str:
    return Template(_PLANTILLA_QSS).substitute(**theme_colors(clave))


def build_palette(clave: str) -> QPalette:
    c = theme_colors(clave)
    paleta = QPalette()
    roles = {
        QPalette.ColorRole.Window: c["bg"],
        QPalette.ColorRole.WindowText: c["text"],
        QPalette.ColorRole.Base: c["surface"],
        QPalette.ColorRole.AlternateBase: c["surface_alt"],
        QPalette.ColorRole.Text: c["text"],
        QPalette.ColorRole.Button: c["surface_alt"],
        QPalette.ColorRole.ButtonText: c["text"],
        QPalette.ColorRole.Highlight: c["accent"],
        QPalette.ColorRole.HighlightedText: c["accent_text"],
        QPalette.ColorRole.ToolTipBase: c["surface"],
        QPalette.ColorRole.ToolTipText: c["text"],
        QPalette.ColorRole.PlaceholderText: c["muted"],
        QPalette.ColorRole.Light: c["surface"],
        QPalette.ColorRole.Midlight: c["surface_alt"],
        QPalette.ColorRole.Mid: c["border"],
        QPalette.ColorRole.Dark: c["splitter"],
        QPalette.ColorRole.Shadow: c["disabled"],
    }
    for rol, color in roles.items():
        paleta.setColor(rol, QColor(color))

    for rol in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.PlaceholderText,
    ):
        paleta.setColor(
            QPalette.ColorGroup.Disabled, rol, QColor(c["disabled"])
        )
    return paleta
