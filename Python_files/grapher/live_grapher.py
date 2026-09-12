"""
live_grapher.py -- a lightweight live plotter for the LabRAD Data Vault.

Browse the vault, pick a dataset, and watch it plot in real time -- the counts
NormalPMTFlow is writing show up as a scrolling trace. Our own small tool
(pyqtgraph + blocking pylabrad client + a poll timer), rather than the 3600-line
py2/PyQt4 pygrapherlive.

How it stays live: it opens the dataset in its own LabRAD context, so each
`get()` returns only the rows added since the last one (a fresh context starts
at row 0) -- no re-reading the whole set, no reactor.

Needs PyQt5 + pyqtgraph:  pip install PyQt5 pyqtgraph

Run:  python live_grapher.py    (LabRAD env from LABRADHOST/LABRADPASSWORD/LABRAD_TLS)
"""
import os
import sys

from PyQt5 import QtCore, QtWidgets

try:
    import pyqtgraph as pg
except ImportError:
    pg = None

try:
    import labrad
except Exception:
    labrad = None

POLL_MS = 250
PENS = ['#2563eb', '#dc2626', '#16a34a', '#d97706', '#7c3aed', '#0891b2']

STYLESHEET = """
QWidget#Grapher { background-color: #f4f5f7; }
QWidget { font-family: 'Segoe UI','SF Pro Text','Helvetica Neue',Arial,sans-serif;
          font-size: 10pt; color: #1f2328; }
QPushButton { background:#fff; border:1px solid #d0d5dd; border-radius:8px; padding:6px 12px; }
QPushButton:hover { background:#f2f4f7; }
QListWidget { background:#fff; border:1px solid #e4e7ec; border-radius:8px; outline:none; }
QListWidget::item:selected { background:#e8f0fe; color:#1f2328; }
QCheckBox { spacing:6px; }
"""


class Grapher(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName('Grapher')
        self.setWindowTitle('LabRAD Data Vault — Live Grapher')
        self.resize(960, 600)
        self.path = ['']            # current vault directory (absolute)
        self.plot_ctx = None        # dedicated context for the open dataset
        self.dataset = None
        self.n_indep = 1
        self.curves = []
        self.x = []
        self.ys = []

        self.cxn = self._connect()                 # try environment credentials
        if self.cxn is None and labrad is not None and pg is not None:
            self.cxn = self._login_loop()          # else prompt for host/password
        self._build_ui()
        if self.cxn is not None:
            self._refresh_dir()
            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self._poll)
            self.timer.start(POLL_MS)

    # ---- connection --------------------------------------------------------
    def _connect(self, host=None, password=None):
        if labrad is None:
            return None
        host = host or os.environ.get('LABRADHOST', 'localhost') or 'localhost'
        if password is None:
            password = os.environ.get('LABRADPASSWORD', '') or ''
        tls = 'on' if os.environ.get('LABRAD_TLS', 'off') in ('on', 'true', '1') else 'off'
        try:
            cxn = labrad.connect(host=host, username='', password=password, tls_mode=tls)
            self.dv = cxn.data_vault
            return cxn
        except Exception as e:
            self._err = str(e)
            return None

    def _login_loop(self):
        """Prompt for host/password and retry until it connects or the user
        cancels. Used when the environment credentials don't work."""
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
            QtWidgets.QMessageBox.warning(
                self, "Connection failed",
                "Could not connect to the manager:\n%s\n\n"
                "Check the host and password, then try again."
                % getattr(self, '_err', ''))

    def _prompt_login(self, host, pw):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Connect to LabRAD")
        form = QtWidgets.QFormLayout(dlg)
        host_edit = QtWidgets.QLineEdit(host)
        pw_edit = QtWidgets.QLineEdit(pw)
        pw_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        form.addRow("Manager host:", host_edit)
        form.addRow("Password:", pw_edit)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        pw_edit.setFocus()
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            return (host_edit.text().strip() or 'localhost'), pw_edit.text()
        return None

    # ---- UI ----------------------------------------------------------------
    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        if pg is None:
            outer.addWidget(QtWidgets.QLabel(
                "pyqtgraph is not installed.\n\n    pip install pyqtgraph"))
            return
        if self.cxn is None:
            msg = "Cannot reach LabRAD / Data Vault"
            if labrad is None:
                msg = "pylabrad is not installed."
            elif hasattr(self, '_err'):
                msg += ":\n%s" % self._err
            outer.addWidget(QtWidgets.QLabel(msg))
            return

        top = QtWidgets.QHBoxLayout()
        self.up_btn = QtWidgets.QPushButton("↑ Up")
        self.up_btn.clicked.connect(self._go_up)
        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._refresh_dir)
        self.latest_btn = QtWidgets.QPushButton("Open latest")
        self.latest_btn.clicked.connect(self._open_latest)
        self.live_check = QtWidgets.QCheckBox("Live")
        self.live_check.setChecked(True)
        self.path_lbl = QtWidgets.QLabel("/")
        top.addWidget(self.up_btn)
        top.addWidget(self.refresh_btn)
        top.addWidget(self.latest_btn)
        top.addWidget(self.live_check)
        top.addWidget(self.path_lbl, 1)
        outer.addLayout(top)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.listw = QtWidgets.QListWidget()
        self.listw.itemDoubleClicked.connect(self._on_item)
        splitter.addWidget(self.listw)

        pg.setConfigOptions(antialias=True, background='w', foreground='#1f2328')
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.legend = self.plot.addLegend()
        splitter.addWidget(self.plot)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        outer.addWidget(splitter, 1)

        self.status = QtWidgets.QLabel("select a dataset")
        outer.addWidget(self.status)

    # ---- navigation --------------------------------------------------------
    def _refresh_dir(self):
        try:
            self.dv.cd(self.path)
            dirs, datasets = self.dv.dir()
        except Exception as e:
            self.status.setText("dir error: %s" % e)
            return
        self.path_lbl.setText('/' + '/'.join(p for p in self.path if p))
        self.listw.clear()
        for d in sorted(dirs, key=str.lower):
            it = QtWidgets.QListWidgetItem("📁  " + d)
            it.setData(QtCore.Qt.UserRole, ('dir', d))
            self.listw.addItem(it)
        for ds in datasets:
            it = QtWidgets.QListWidgetItem("📈  " + ds)
            it.setData(QtCore.Qt.UserRole, ('dataset', ds))
            self.listw.addItem(it)

    def _go_up(self):
        if len(self.path) > 1:
            self.path = self.path[:-1]
            self._refresh_dir()

    def _on_item(self, item):
        kind, name = item.data(QtCore.Qt.UserRole)
        if kind == 'dir':
            self.path = self.path + [name]
            self._refresh_dir()
        else:
            self._open_dataset(name)

    def _open_latest(self):
        try:
            self.dv.cd(self.path)
            _dirs, datasets = self.dv.dir()
        except Exception as e:
            self.status.setText("dir error: %s" % e)
            return
        if datasets:
            self._open_dataset(sorted(datasets)[-1])

    # ---- plotting ----------------------------------------------------------
    def _open_dataset(self, name):
        try:
            ctx = self.cxn.context()
            self.dv.cd(self.path, context=ctx)
            self.dv.open(name, context=ctx)
            indeps, deps = self.dv.variables(context=ctx)
        except Exception as e:
            self.status.setText("open error: %s" % e)
            return
        self.plot_ctx = ctx
        self.dataset = name
        self.n_indep = max(1, len(indeps))
        # axis labels from the first independent / plot generic Y
        xlab = indeps[0][0] if indeps else 't'
        xunit = indeps[0][1] if indeps and len(indeps[0]) > 1 else ''
        self.plot.setLabel('bottom', xlab, units=xunit or None)
        # rebuild curves (removeItem clears their legend entries too)
        for c in self.curves:
            self.plot.removeItem(c)
        self.curves = []
        self.x = []
        self.ys = [[] for _ in deps]
        for j, dep in enumerate(deps):
            label = dep[1] if len(dep) > 1 and dep[1] else dep[0]
            pen = pg.mkPen(PENS[j % len(PENS)], width=2)
            self.curves.append(self.plot.plot([], [], pen=pen, name=label))
        self.status.setText("%s — 0 points" % name)

    def _poll(self):
        if self.plot_ctx is None or not self.live_check.isChecked():
            return
        try:
            new = self.dv.get(context=self.plot_ctx)
        except Exception as e:
            self.status.setText("read error: %s" % e)
            return
        if new is None or len(new) == 0:
            return
        for r in new:
            self.x.append(float(r[0]))
            for j in range(len(self.curves)):
                self.ys[j].append(float(r[self.n_indep + j]))
        for j, c in enumerate(self.curves):
            c.setData(self.x, self.ys[j])
        self.status.setText("%s — %d points" % (self.dataset, len(self.x)))

    def closeEvent(self, ev):
        try:
            if self.cxn is not None:
                self.cxn.disconnect()
        except Exception:
            pass
        ev.accept()


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(STYLESHEET)
    w = Grapher()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
