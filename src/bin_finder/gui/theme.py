APP_STYLE = r"""
QWidget {
    background: #07111d;
    color: #e7eef7;
    font-family: "Segoe UI";
    font-size: 12px;
}
QMainWindow { background: #050d17; }
QFrame#panel {
    background: #0b1623;
    border: 1px solid #18334b;
    border-radius: 10px;
}
QFrame#header { background: #07111d; border-bottom: 1px solid #173047; }
QLabel#appTitle { font-size: 26px; font-weight: 800; color: #f0b4ff; }
QLabel#subtitle { color: #94a9bd; font-size: 12px; }
QLabel#panelTitle { font-size: 15px; font-weight: 700; }
QLabel#muted { color: #8296aa; }
QPushButton, QToolButton {
    background: #102235;
    border: 1px solid #24425f;
    border-radius: 6px;
    padding: 7px 10px;
    color: #edf6ff;
}
QPushButton:hover, QToolButton:hover { background: #17314a; border-color: #3474a6; }
QPushButton#primary { background: #0878ff; border-color: #2e91ff; font-weight: 700; }
QPushButton#success { background: #12cf85; color: #03150e; border-color: #29e7a0; font-weight: 800; }
QToolButton:checked { background: #0f5db5; border: 1px solid #36a0ff; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #0a1725;
    border: 1px solid #203b55;
    border-radius: 6px;
    padding: 6px;
    selection-background-color: #0f6dc8;
}
QComboBox::drop-down { border: none; }
QTabWidget::pane { border: 1px solid #1b364f; border-radius: 7px; background: #091522; }
QTabBar::tab {
    background: #102133; color: #a9bdd0; padding: 8px 12px; border: 1px solid #203b55;
}
QTabBar::tab:selected { background: #0d5ba7; color: white; }
QScrollArea { border: none; background: transparent; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { background: #0c1927; border: 1px solid #18334b; border-radius: 7px; margin: 3px; padding: 8px; }
QListWidget::item:selected { background: #0d385f; border-color: #1d92ff; }
QProgressBar { background: #0a1725; border: 1px solid #203b55; border-radius: 5px; text-align: center; }
QProgressBar::chunk { background: #18c998; border-radius: 4px; }
"""

PANEL_ACCENTS = {
    1: "#ff233d",      # Project & script
    2: "#248bff",      # Script scene list
    3: "#20d964",      # Search sources/options
    4: "#ff8a18",      # Search results
    5: "#c522ff",      # Review / analysis / choose
    6: "#b833ff",      # Selected footage
    7: "#20d964",      # Export
}


# F001.1 GUI polish: horizontal workspace navigation and larger single-language scene text.
APP_STYLE += r"""
QFrame#topNavigation {
    background: transparent;
    border: none;
}
QPushButton#topNavButton {
    background: #0b1a29;
    border: 1px solid #24425f;
    border-radius: 7px;
    padding: 9px 14px;
    font-size: 14px;
    font-weight: 700;
}
QPushButton#topNavButton:hover {
    background: #132a40;
    border-color: #3b83bb;
}
QPushButton#topNavButton:checked {
    background: #123e68;
    border: 1px solid #2f97ef;
    color: #ffffff;
}
QPlainTextEdit#sceneText {
    font-size: 14px;
    line-height: 1.35;
    padding: 9px;
}
QTabWidget#analysisTabs::pane {
    border: 1px solid #274862;
    border-radius: 7px;
}
"""

# F001.2 compact provider row + denser result/export workspace.
APP_STYLE += r"""
QCheckBox#providerCheck {
    background: #0c1b2a;
    border: 1px solid #24425f;
    border-radius: 6px;
    padding: 6px 9px;
    spacing: 7px;
}
QCheckBox#providerCheck:hover {
    background: #132a40;
    border-color: #3b83bb;
}
QTabBar::tab {
    min-width: 68px;
}
"""
