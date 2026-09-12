"""
theme.py -- shared modern look for the pulser_gui PyQt5 clients.

Fusion base style + a light custom stylesheet (card panels, rounded accent
buttons, colour-coded checked state, themed inputs), matching the launcher.
Give the top-level widget objectName 'Root' so its background is themed, then
call apply(app) in main().
"""

STYLESHEET = """
QWidget#Root { background-color: #f4f5f7; }
QFrame#Root  { background-color: #f4f5f7; }
QDialog      { background-color: #f4f5f7; }
QWidget { font-family: 'Segoe UI','SF Pro Text','Helvetica Neue',Arial,sans-serif;
          font-size: 10pt; color: #1f2328; }
QLabel { background: transparent; }

QGroupBox {
    background: #ffffff; border: 1px solid #e4e7ec; border-radius: 10px;
    margin-top: 16px; padding: 14px 12px 12px 12px; font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 12px; padding: 0 4px; color: #475467;
}

QPushButton {
    background: #ffffff; border: 1px solid #d0d5dd; border-radius: 8px;
    padding: 6px 14px;
}
QPushButton:hover { background: #f2f4f7; }
QPushButton:pressed { background: #e4e7ec; }
QPushButton:disabled { color: #98a2b3; background: #f2f4f7; }
QPushButton:checked { background: #2563eb; color: #ffffff; border: none; }
QPushButton#primary { background: #2563eb; color: #ffffff; border: none; font-weight: 600; }
QPushButton#primary:hover { background: #1d4ed8; }
/* record toggle: green while recording */
QPushButton#record:checked { background: #16a34a; }

QComboBox, QAbstractSpinBox, QLineEdit {
    background: #ffffff; border: 1px solid #d0d5dd; border-radius: 8px;
    padding: 5px 8px; min-height: 20px;
}
QComboBox:focus, QAbstractSpinBox:focus, QLineEdit:focus { border: 1px solid #2563eb; }
QComboBox::drop-down { border: none; width: 18px; subcontrol-origin: padding; subcontrol-position: center right; }
/* draw the dropdown caret (a CSS triangle) -- without this, styling drop-down hides Qt's native arrow */
QComboBox::down-arrow {
    width: 0; height: 0; margin-right: 7px;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid #667085;
}
QComboBox::down-arrow:hover { border-top-color: #2563eb; }
QComboBox QAbstractItemView {
    background: #ffffff; border: 1px solid #e4e7ec;
    selection-background-color: #e8f0fe; selection-color: #1f2328; outline: none;
}

QCheckBox { spacing: 6px; }

QTableWidget {
    background: #ffffff; border: 0.5px solid #e4e7ec; border-radius: 8px;
    gridline-color: #f0f1f4; outline: none;
}
QTableWidget::item { padding: 4px 6px; }
QTableWidget::item:selected { background: #e8f0fe; color: #1f2328; }
QHeaderView::section {
    background: #f8fafc; border: none; border-bottom: 1px solid #e4e7ec;
    padding: 6px 8px; font-weight: 600; color: #667085;
}
QSplitter::handle { background: transparent; }

PlotWidget { border: 0.5px solid #e4e7ec; border-radius: 8px; }

QLCDNumber {
    background: #0f172a; color: #22d3ee;
    border: 1px solid #e4e7ec; border-radius: 8px;
}
"""


def apply(app):
    """Apply the Fusion base style + the shared stylesheet to a QApplication."""
    app.setStyle('Fusion')
    app.setStyleSheet(STYLESHEET)
