"""Tema único de Fruquis: oscuro, minimalista, bordes redondeados y un solo acento. Se aplica a toda la aplicación."""
BG, PANEL, RAISED, LINE, TEXT, DIM, ACCENT, DANGER = "#16161c", "#1c1c24", "#262632", "#2d2d3a", "#ececf1", "#8d8da0", "#8a6ae0", "#f07178"

CSS = f"""
* {{ font-family:'Inter','Segoe UI','Noto Sans',sans-serif; font-size:13px; }}
QWidget {{ color:{TEXT}; }}
QDialog, QMessageBox, QInputDialog, QFileDialog, QWidget#win {{ background:{BG}; }}
QWidget#body {{ background:{BG}; }}
QScrollArea {{ background:{BG}; border:none; }}
QFrame#float {{ background:{BG}; border:1px solid #3a3a4c; border-radius:18px; }}
QFrame#floatbar {{ background:transparent; border:none; }}
QFrame#side {{ background:{PANEL}; border-right:1px solid {LINE}; }}
QFrame#card {{ background:{PANEL}; border:1px solid {LINE}; border-radius:16px; }}
QLabel {{ background:transparent; }}
QLabel#brand {{ font-size:15px; font-weight:700; letter-spacing:1px; }}
QFrame#topbar {{ background:{PANEL}; border-bottom:1px solid {LINE}; }}
QLabel#h2 {{ font-size:15px; font-weight:600; padding-left:4px; }}
QPushButton#tab {{ background:transparent; border:none; color:{DIM}; padding:7px 12px; border-radius:10px; }}
QPushButton#tab:hover {{ background:{RAISED}; color:{TEXT}; }}
QPushButton#tab:checked {{ background:#2e2a46; color:white; }}
QLabel#toast {{ background:#2e2a46; color:white; border:1px solid {ACCENT}; border-radius:14px; padding:10px 18px; font-weight:600; }}
QLabel#h1 {{ font-size:20px; font-weight:600; }}
QLabel#dim, QLabel#hint {{ color:{DIM}; font-size:12px; }}
QLabel#section {{ color:{DIM}; font-size:11px; font-weight:600; letter-spacing:1px; }}

QPushButton {{ background:{RAISED}; border:1px solid {LINE}; border-radius:10px; padding:8px 14px; }}
QPushButton:hover {{ border-color:{ACCENT}; }}
QPushButton:pressed {{ background:#30304a; }}
QPushButton:disabled {{ color:#6a6a7c; background:{PANEL}; border-color:{LINE}; }}
QPushButton#primary {{ background:{ACCENT}; border:none; color:white; font-weight:600; }}
QPushButton#primary:hover {{ background:#9b80ee; }}
QPushButton#primary:disabled {{ background:#34343f; color:#7a7a8c; }}
QPushButton#ghost {{ background:transparent; border:none; color:{DIM}; }}
QPushButton#ghost:hover {{ background:{RAISED}; color:{TEXT}; }}
QPushButton#danger {{ background:transparent; border:none; color:{DANGER}; }}
QPushButton#danger:hover {{ background:#3a2430; }}
QPushButton#pill {{ border-radius:16px; padding:8px 12px; }}

QListWidget {{ background:transparent; border:none; outline:none; }}
QListWidget::item {{ padding:9px 12px; margin:2px 8px; border-radius:10px; }}
QListWidget::indicator {{ width:16px; height:16px; border-radius:5px; border:1px solid #55556a; background:transparent; }}
QListWidget::indicator:checked {{ background:{ACCENT}; border-color:{ACCENT}; }}
QListWidget::item:hover {{ background:{RAISED}; }}
QListWidget::item:selected {{ background:#2e2a46; color:white; }}

QLineEdit, QPlainTextEdit, QSpinBox, QComboBox, QTextBrowser {{ background:{PANEL}; border:1px solid {LINE}; border-radius:10px; padding:6px 10px;
  selection-background-color:{ACCENT}; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color:{ACCENT}; }}
QComboBox::drop-down {{ border:none; width:22px; }}
QComboBox QAbstractItemView {{ background:{PANEL}; border:1px solid {LINE}; selection-background-color:{ACCENT}; outline:none; }}
QSpinBox::up-button, QSpinBox::down-button {{ width:0; border:none; }}
QProgressBar {{ background:{RAISED}; border:none; border-radius:4px; max-height:8px; min-height:8px; }}
QProgressBar::chunk {{ background:{ACCENT}; border-radius:4px; }}

QCheckBox {{ spacing:8px; }}
QCheckBox::indicator {{ width:16px; height:16px; border-radius:5px; border:1px solid #55556a; background:transparent; }}
QCheckBox::indicator:checked {{ background:{ACCENT}; border-color:{ACCENT}; }}
QSlider::groove:horizontal {{ height:6px; background:{RAISED}; border-radius:3px; }}
QSlider::sub-page:horizontal {{ background:{ACCENT}; border-radius:3px; }}
QSlider::handle:horizontal {{ width:16px; height:16px; margin:-5px 0; border-radius:8px; background:white; }}
QMenu {{ background:{PANEL}; border:1px solid {LINE}; border-radius:12px; padding:6px; }}
QMenu::item {{ padding:7px 18px; border-radius:8px; }}
QMenu::item:selected {{ background:{ACCENT}; color:white; }}
QMenu::separator {{ height:1px; background:{LINE}; margin:5px 8px; }}
QToolTip {{ background:{PANEL}; color:{TEXT}; border:1px solid {LINE}; padding:5px 8px; border-radius:8px; }}
QScrollBar:vertical {{ background:transparent; width:8px; margin:0; }}
QScrollBar::handle:vertical {{ background:#3a3a48; border-radius:4px; min-height:30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
QScrollBar:horizontal {{ height:0; }}
"""


def apply(app):
    app.setStyle("Fusion")
    app.setStyleSheet(CSS)
