"""
dashboard.py -- a dockable panel host for the LabRAD client GUIs.

The client-side companion to the launcher: where the launcher manages server
*processes*, the dashboard hosts the client *GUIs* in one window. It scans a
folder for GUI modules, lets you add any of them as a dockable panel, and you
drag/float/tab/resize them however you like -- the layout is saved and restored.

How it finds panels: any GUI module that declares a module-level manifest

    DASHBOARD_PANEL = {'title': 'Switch Control', 'widget': SwitchWidget}

shows up in the Panels menu. The panel's widget class is instantiated as
`widget(cxn=shared_cxn)` -- the dashboard connects to LabRAD *once* (with the
password prompt) and shares that connection with every panel, so there's one
login and one connection for the whole window.

Needs PyQt5 (+ whatever the panels need, e.g. pyqtgraph for the grapher):

    pip install PyQt5 pyqtgraph
    python dashboard.py
"""
import base64
import importlib.util
import json
import os
import sys

from PyQt5 import QtCore, QtWidgets

try:
    import labrad
except Exception:
    labrad = None

CONFIG_PATH = os.path.expanduser('~/.labrad/dashboard_config.json')
EXCLUDE_DIRS = {'old_legacy_code', 'servers', 'clients', '__pycache__',
                '.git', 'test', 'tests', 'sim', 'ip'}


def find_panels(root):
    """Scan `root` for modules declaring DASHBOARD_PANEL; import and collect
    them. Returns {key: {'title', 'widget'}}. Adds each module's folder to
    sys.path so its own imports resolve."""
    panels = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fn in files:
            if not fn.endswith('.py'):
                continue
            path = os.path.join(dirpath, fn)
            if os.path.abspath(path) == os.path.abspath(__file__):
                continue                          # don't import ourselves
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    text = f.read()
            except OSError:
                continue
            if 'DASHBOARD_PANEL' not in text:
                continue
            folder = os.path.dirname(path)
            if folder not in sys.path:
                sys.path.insert(0, folder)
            key = os.path.splitext(fn)[0]
            try:
                spec = importlib.util.spec_from_file_location(key, path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                panel = getattr(mod, 'DASHBOARD_PANEL', None)
                if panel and panel.get('widget'):
                    panels[key] = {'title': panel.get('title', key),
                                   'widget': panel['widget']}
            except Exception as e:
                print("dashboard: skip %s (%s)" % (path, e))
    return panels


class PanelDock(QtWidgets.QDockWidget):
    """A dock that fully deletes its panel (stopping its timers) when closed."""
    def __init__(self, title, key, on_closed, parent):
        super().__init__(title, parent)
        self.key = key
        self._on_closed = on_closed
        self.setObjectName('dock_' + key)     # required for saveState/restoreState
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)

    def closeEvent(self, ev):
        self._on_closed(self.key)
        super().closeEvent(ev)


class Dashboard(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('LabRAD Dashboard')
        self.resize(1100, 720)
        self.setDockNestingEnabled(True)
        self.open_docks = {}

        self.scan_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._apply_theme()

        self.cxn = self._connect() or self._login_loop()
        self.panels = find_panels(self.scan_root) if self.cxn is not None else {}

        self.hint = QtWidgets.QLabel(
            "Add panels from the  Panels  menu.", alignment=QtCore.Qt.AlignCenter)
        self.hint.setStyleSheet("color:#98a2b3; font-size:12pt;")
        self.setCentralWidget(self.hint)

        self._build_menu()
        if self.cxn is None:
            self.hint.setText("Cannot reach LabRAD.\n%s" % getattr(self, '_err', ''))
            return
        self._restore_layout()
        self._update_central()

    # ---- theme -------------------------------------------------------------
    def _apply_theme(self):
        app = QtWidgets.QApplication.instance()
        gui = os.path.join(self.scan_root, 'pulser_gui')
        if gui not in sys.path:
            sys.path.insert(0, gui)
        try:
            import theme                       # shared look from pulser_gui/theme.py
            theme.apply(app)
        except Exception:
            app.setStyle('Fusion')

    # ---- connection (shared; env then prompt) ------------------------------
    def _connect(self, host=None, password=None):
        if labrad is None:
            self._err = "pylabrad is not installed."
            return None
        host = host or os.environ.get('LABRADHOST', 'localhost') or 'localhost'
        if password is None:
            password = os.environ.get('LABRADPASSWORD', '') or ''
        tls = 'on' if os.environ.get('LABRAD_TLS', 'off') in ('on', 'true', '1') else 'off'
        try:
            return labrad.connect(host=host, username='', password=password, tls_mode=tls)
        except Exception as e:
            self._err = str(e)
            return None

    def _login_loop(self):
        if labrad is None:
            return None
        host = os.environ.get('LABRADHOST', 'localhost') or 'localhost'
        pw = os.environ.get('LABRADPASSWORD', '') or ''
        while True:
            creds = self._prompt_login(host, pw)
            if creds is None:
                return None
            host, pw = creds
            cxn = self._connect(host=host, password=pw)
            if cxn is not None:
                return cxn
            QtWidgets.QMessageBox.warning(self, "Connection failed",
                                          "Could not connect:\n%s" % getattr(self, '_err', ''))

    def _prompt_login(self, host, pw):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Connect to LabRAD")
        form = QtWidgets.QFormLayout(dlg)
        host_edit = QtWidgets.QLineEdit(host)
        pw_edit = QtWidgets.QLineEdit(pw)
        pw_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        form.addRow("Manager host:", host_edit)
        form.addRow("Password:", pw_edit)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        pw_edit.setFocus()
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            return (host_edit.text().strip() or 'localhost'), pw_edit.text()
        return None

    # ---- menu --------------------------------------------------------------
    def _build_menu(self):
        self.menuBar().clear()
        m = self.menuBar().addMenu("Panels")
        for key in sorted(self.panels, key=lambda k: self.panels[k]['title'].lower()):
            act = m.addAction(self.panels[key]['title'])
            act.triggered.connect(lambda _=False, k=key: self.add_panel(k))
        m.addSeparator()
        m.addAction("Rescan panels", self._rescan)
        m.addAction("Close all panels", self._close_all)

    def _rescan(self):
        self.panels = find_panels(self.scan_root)
        self._build_menu()

    # ---- panels ------------------------------------------------------------
    def add_panel(self, key):
        if key in self.open_docks:
            self.open_docks[key].raise_()
            return
        spec = self.panels.get(key)
        if not spec:
            return
        try:
            widget = spec['widget'](cxn=self.cxn)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Panel failed",
                                          "%s:\n%s" % (spec['title'], e))
            return
        dock = PanelDock(spec['title'], key, self._on_dock_closed, self)
        dock.setWidget(widget)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        self.open_docks[key] = dock
        self._update_central()

    def _on_dock_closed(self, key):
        self.open_docks.pop(key, None)
        # defer: the dock is mid-close, update after it's gone
        QtCore.QTimer.singleShot(0, self._update_central)

    def _close_all(self):
        for dock in list(self.open_docks.values()):
            dock.close()

    def _update_central(self):
        self.hint.setVisible(not self.open_docks)

    # ---- layout persistence ------------------------------------------------
    def _restore_layout(self):
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            return
        for key in cfg.get('open', []):
            if key in self.panels:
                self.add_panel(key)
        geo = cfg.get('geometry')
        st = cfg.get('state')
        if geo:
            self.restoreGeometry(QtCore.QByteArray.fromBase64(geo.encode()))
        if st:
            self.restoreState(QtCore.QByteArray.fromBase64(st.encode()))

    def closeEvent(self, ev):
        cfg = {
            'open': list(self.open_docks.keys()),
            'geometry': bytes(self.saveGeometry().toBase64()).decode(),
            'state': bytes(self.saveState().toBase64()).decode(),
        }
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, 'w') as f:
                json.dump(cfg, f, indent=2)
        except OSError:
            pass
        try:
            if self.cxn is not None:
                self.cxn.disconnect()
        except Exception:
            pass
        ev.accept()


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = Dashboard()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
