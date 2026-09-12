"""
labrad_launcher.py -- a PyQt5 control center for the LabRAD stack.

One window to bring the whole system up: start the scalabrad manager, point at a
folder of servers, and start/stop each one with a button -- all as child
processes whose output is captured in tabs here, so you don't open a PowerShell
per server.

This is "launcher-managed": the GUI itself spawns and supervises every process
(via QProcess), rather than driving the LabRAD node. Simple, no registry config,
and it also starts the manager (which the node cannot). Closing the launcher
stops everything it started (with a confirm).

Needs PyQt5:  pip install PyQt5

Run:  python labrad_launcher.py
"""
import json
import os
import re
import subprocess
import sys

from PyQt5 import QtCore, QtGui, QtWidgets

CONFIG_PATH = os.path.expanduser('~/.labrad/launcher_config.json')
NODE_INFO_RE = re.compile(r'###\s*BEGIN NODE INFO(.*?)###\s*END NODE INFO', re.S)
NAME_RE = re.compile(r'^\s*name\s*=\s*(.+?)\s*$', re.M)
# Directories skipped while scanning. 'servers' and 'clients' are this repo's
# legacy Python-2 trees (also archived in 'old_legacy_code'); scanning them would
# surface py2 servers that can't launch under py3. Edit this set for your layout.
EXCLUDE_DIRS = {'old_legacy_code', 'servers', 'clients', '__pycache__',
                '.git', 'test', 'tests', 'sim'}

DEFAULT_CONFIG = {
    'manager_bat': '',
    'registry': 'file:///C:/labrad-registry?format=binary',
    'password': 'test',
    'tls': False,
    'scan_folder': '',
    'env': {
        'LABRADHOST': 'localhost',
        'LABRADPASSWORD': 'test',
        'LABRAD_TLS': 'off',
        'PULSER_BIT_PATH': '',
    },
}

MANAGER_KEY = '__manager__'

RUNNING_COLOR = '#16a34a'
STOPPED_COLOR = '#9198a1'

# A clean, modern light theme layered over the Fusion base style. Cards for the
# group boxes, rounded/accented buttons, a dark console for the log tabs.
STYLESHEET = """
QWidget#Launcher { background-color: #f4f5f7; }
QWidget { font-family: 'Segoe UI','SF Pro Text','Helvetica Neue',Arial,sans-serif;
          font-size: 10pt; color: #1f2328; }

QGroupBox {
    background: #ffffff;
    border: 1px solid #e4e7ec;
    border-radius: 10px;
    margin-top: 16px;
    padding: 14px 12px 12px 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px; padding: 0 4px;
    color: #475467;
}

QLabel { background: transparent; }

QPushButton {
    background: #ffffff;
    border: 1px solid #d0d5dd;
    border-radius: 8px;
    padding: 6px 14px;
}
QPushButton:hover { background: #f2f4f7; }
QPushButton:pressed { background: #e4e7ec; }
QPushButton:disabled { color: #98a2b3; background: #f2f4f7; }
QPushButton#primary {
    background: #2563eb; color: #ffffff; border: none; font-weight: 600;
}
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#primary:pressed { background: #1e40af; }

QLineEdit {
    background: #ffffff; border: 1px solid #d0d5dd; border-radius: 8px;
    padding: 6px 9px; selection-background-color: #2563eb; selection-color: #fff;
}
QLineEdit:focus { border: 1px solid #2563eb; }
QLineEdit::placeholder { color: #98a2b3; }

QCheckBox { spacing: 6px; }

QTableWidget {
    background: #ffffff; border: 1px solid #e4e7ec; border-radius: 8px;
    gridline-color: #f0f1f4; outline: none;
}
QHeaderView::section {
    background: #f8fafc; border: none; border-bottom: 1px solid #e4e7ec;
    padding: 7px 8px; font-weight: 600; color: #667085;
}
QTableWidget::item { padding: 5px 6px; }
QTableWidget::item:selected { background: #e8f0fe; color: #1f2328; }

QSplitter::handle { background: transparent; }

QTabWidget::pane { border: 1px solid #e4e7ec; border-radius: 8px; top: -1px; background: #1e1e1e; }
QTabBar::tab {
    background: transparent; padding: 7px 16px; margin-right: 2px; color: #667085;
    border: 1px solid transparent;
    border-top-left-radius: 8px; border-top-right-radius: 8px;
}
QTabBar::tab:selected {
    background: #ffffff; color: #1f2328;
    border: 1px solid #e4e7ec; border-bottom-color: #ffffff;
}
QTabBar::tab:hover:!selected { color: #1f2328; }

QPlainTextEdit {
    background: #1e1e1e; color: #d4d4d4;
    border: none; border-radius: 8px; padding: 6px;
    font-family: 'Consolas','Menlo','DejaVu Sans Mono',monospace; font-size: 9.5pt;
}
"""


def find_servers(folder):
    """Scan `folder` recursively for LabRAD server files (those carrying a
    NODE INFO block). Returns a sorted list of (name, filepath)."""
    found = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fn in files:
            if not fn.endswith('.py'):
                continue
            path = os.path.join(root, fn)
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    head = f.read(4096)
            except OSError:
                continue
            m = NODE_INFO_RE.search(head)
            if not m:
                continue
            nm = NAME_RE.search(m.group(1))
            name = nm.group(1).strip() if nm else os.path.splitext(fn)[0]
            found.append((name, path))
    return sorted(found, key=lambda t: t[0].lower())


class Launcher(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName('Launcher')
        self.setWindowTitle('LabRAD Launcher')
        self.resize(900, 640)
        self.cfg = self._load_config()
        self.procs = {}       # key -> QProcess  (key = server name or MANAGER_KEY)
        self.logs = {}        # key -> QPlainTextEdit
        self.rows = {}        # server name -> row index in the table
        self._build_ui()
        if self.cfg['scan_folder'] and os.path.isdir(self.cfg['scan_folder']):
            self._rescan()

    # ---- config -----------------------------------------------------------
    def _load_config(self):
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))   # deep copy
        try:
            with open(CONFIG_PATH) as f:
                saved = json.load(f)
            cfg.update({k: saved[k] for k in saved if k != 'env'})
            cfg['env'].update(saved.get('env', {}))
        except (OSError, ValueError):
            pass
        return cfg

    def _save_config(self):
        self._pull_config_from_ui()
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, 'w') as f:
                json.dump(self.cfg, f, indent=2)
        except OSError as e:
            self._log(MANAGER_KEY, "[launcher] could not save config: %s\n" % e)

    def _pull_config_from_ui(self):
        self.cfg['manager_bat'] = self.bat_edit.text()
        self.cfg['registry'] = self.reg_edit.text()
        self.cfg['password'] = self.pw_edit.text()
        self.cfg['tls'] = self.tls_check.isChecked()
        self.cfg['scan_folder'] = self.folder_edit.text()
        env = {}
        for r in range(self.env_table.rowCount()):
            k = self.env_table.item(r, 0)
            v = self.env_table.item(r, 1)
            if k and k.text().strip():
                env[k.text().strip()] = v.text() if v else ''
        self.cfg['env'] = env

    # ---- UI ---------------------------------------------------------------
    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)

        top = QtWidgets.QWidget()
        top_l = QtWidgets.QVBoxLayout(top)
        top_l.setContentsMargins(0, 0, 0, 0)
        top_l.addWidget(self._manager_group())
        body = QtWidgets.QHBoxLayout()
        body.addWidget(self._servers_group(), 2)
        body.addWidget(self._env_group(), 1)
        top_l.addLayout(body)
        splitter.addWidget(top)

        self.log_tabs = QtWidgets.QTabWidget()
        self.log_tabs.setMinimumHeight(160)
        splitter.addWidget(self.log_tabs)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter)

    def _manager_group(self):
        g = QtWidgets.QGroupBox("LabRAD manager (scalabrad)")
        form = QtWidgets.QGridLayout(g)
        self.bat_edit = QtWidgets.QLineEdit(self.cfg['manager_bat'])
        self.bat_edit.setPlaceholderText(r"path to scalabrad-*\bin\labrad.bat")
        browse = QtWidgets.QPushButton("Browse…")
        browse.clicked.connect(self._browse_bat)
        self.reg_edit = QtWidgets.QLineEdit(self.cfg['registry'])
        self.pw_edit = QtWidgets.QLineEdit(self.cfg['password'])
        self.tls_check = QtWidgets.QCheckBox("Require TLS")
        self.tls_check.setChecked(self.cfg['tls'])
        self.mgr_status = QtWidgets.QLabel("○ stopped")
        self.mgr_status.setStyleSheet("color: %s; font-weight: 600;" % STOPPED_COLOR)
        self.mgr_btn = QtWidgets.QPushButton("Start Manager")
        self.mgr_btn.setObjectName("primary")
        self.mgr_btn.clicked.connect(self._toggle_manager)

        form.addWidget(QtWidgets.QLabel("Launcher:"), 0, 0)
        form.addWidget(self.bat_edit, 0, 1)
        form.addWidget(browse, 0, 2)
        form.addWidget(QtWidgets.QLabel("Registry:"), 1, 0)
        form.addWidget(self.reg_edit, 1, 1, 1, 2)
        form.addWidget(QtWidgets.QLabel("Password:"), 2, 0)
        form.addWidget(self.pw_edit, 2, 1)
        form.addWidget(self.tls_check, 2, 2)
        form.addWidget(self.mgr_btn, 3, 0)
        form.addWidget(self.mgr_status, 3, 1, 1, 2)
        return g

    def _servers_group(self):
        g = QtWidgets.QGroupBox("Servers")
        v = QtWidgets.QVBoxLayout(g)
        row = QtWidgets.QHBoxLayout()
        self.folder_edit = QtWidgets.QLineEdit(self.cfg['scan_folder'])
        self.folder_edit.setPlaceholderText("folder to scan for servers")
        fbrowse = QtWidgets.QPushButton("Browse…")
        fbrowse.clicked.connect(self._browse_folder)
        rescan = QtWidgets.QPushButton("Rescan")
        rescan.clicked.connect(self._rescan)
        row.addWidget(self.folder_edit)
        row.addWidget(fbrowse)
        row.addWidget(rescan)
        v.addLayout(row)

        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Server", "Status", "Action"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.Stretch)
        v.addWidget(self.table)

        allrow = QtWidgets.QHBoxLayout()
        start_all = QtWidgets.QPushButton("Start All")
        start_all.setObjectName("primary")
        start_all.clicked.connect(self._start_all)
        stop_all = QtWidgets.QPushButton("Stop All")
        stop_all.clicked.connect(self._stop_all)
        allrow.addWidget(start_all)
        allrow.addWidget(stop_all)
        allrow.addStretch(1)
        v.addLayout(allrow)
        return g

    def _env_group(self):
        g = QtWidgets.QGroupBox("Environment (applied to servers)")
        v = QtWidgets.QVBoxLayout(g)
        self.env_table = QtWidgets.QTableWidget(0, 2)
        self.env_table.setHorizontalHeaderLabels(["Variable", "Value"])
        self.env_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch)
        for k, val in self.cfg['env'].items():
            self._add_env_row(k, val)
        v.addWidget(self.env_table)
        addrow = QtWidgets.QHBoxLayout()
        addbtn = QtWidgets.QPushButton("+ row")
        addbtn.clicked.connect(lambda: self._add_env_row("", ""))
        savebtn = QtWidgets.QPushButton("Save config")
        savebtn.clicked.connect(self._save_config)
        addrow.addWidget(addbtn)
        addrow.addWidget(savebtn)
        addrow.addStretch(1)
        v.addLayout(addrow)
        return g

    def _add_env_row(self, k, val):
        r = self.env_table.rowCount()
        self.env_table.insertRow(r)
        self.env_table.setItem(r, 0, QtWidgets.QTableWidgetItem(k))
        self.env_table.setItem(r, 1, QtWidgets.QTableWidgetItem(val))

    # ---- browse / scan ----------------------------------------------------
    def _browse_bat(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select the scalabrad launcher (labrad.bat)")
        if path:
            self.bat_edit.setText(path)

    def _browse_folder(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select a folder to scan for servers")
        if path:
            self.folder_edit.setText(path)
            self._rescan()

    def _rescan(self):
        folder = self.folder_edit.text()
        if not os.path.isdir(folder):
            return
        servers = find_servers(folder)
        self.table.setRowCount(0)
        self.rows = {}
        for name, path in servers:
            r = self.table.rowCount()
            self.table.insertRow(r)
            item = QtWidgets.QTableWidgetItem(name)
            item.setData(QtCore.Qt.UserRole, path)
            item.setToolTip(path)
            self.table.setItem(r, 0, item)
            running = name in self.procs and self._is_running(name)
            st = QtWidgets.QTableWidgetItem("● running" if running else "○ stopped")
            st.setForeground(QtGui.QColor(RUNNING_COLOR if running else STOPPED_COLOR))
            self.table.setItem(r, 1, st)
            btn = QtWidgets.QPushButton("Stop" if running else "Start")
            btn.clicked.connect(lambda _=False, n=name: self._toggle_server(n))
            self.table.setCellWidget(r, 2, btn)
            self.rows[name] = r

    # ---- process helpers --------------------------------------------------
    def _full_env(self):
        env = QtCore.QProcessEnvironment.systemEnvironment()
        self._pull_config_from_ui()
        for k, v in self.cfg['env'].items():
            env.insert(k, v)
        return env

    def _is_running(self, key):
        p = self.procs.get(key)
        return p is not None and p.state() != QtCore.QProcess.NotRunning

    def _log_widget(self, key, title):
        if key not in self.logs:
            w = QtWidgets.QPlainTextEdit()
            w.setReadOnly(True)
            w.setMaximumBlockCount(5000)
            self.logs[key] = w
            self.log_tabs.addTab(w, title)
        return self.logs[key]

    def _log(self, key, text):
        w = self._log_widget(key, "Manager" if key == MANAGER_KEY else key)
        w.moveCursor(w.textCursor().End)
        w.insertPlainText(text)
        w.moveCursor(w.textCursor().End)

    def _start_process(self, key, program, args, workdir, title):
        if self._is_running(key):
            return
        proc = QtCore.QProcess(self)
        proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        proc.setProcessEnvironment(self._full_env())
        if workdir:
            proc.setWorkingDirectory(workdir)
        proc.readyReadStandardOutput.connect(
            lambda k=key: self._drain(k))
        proc.stateChanged.connect(lambda st, k=key: self._on_state(k))
        self.procs[key] = proc
        self._log_widget(key, title)
        self.log_tabs.setCurrentWidget(self.logs[key])
        self._log(key, "[launcher] starting: %s %s\n" % (program, ' '.join(args)))
        proc.start(program, args)

    def _drain(self, key):
        p = self.procs.get(key)
        if not p:
            return
        data = bytes(p.readAllStandardOutput()).decode('utf-8', 'replace')
        if data:
            self._log(key, data)

    def _stop_process(self, key):
        p = self.procs.get(key)
        if not p or p.state() == QtCore.QProcess.NotRunning:
            return
        pid = int(p.processId())
        self._log(key, "[launcher] stopping (pid %d)\n" % pid)
        if os.name == 'nt' and pid:
            # kill the whole tree (cmd -> java, etc.) -- QProcess.kill only gets
            # the direct child, which would orphan grandchildren on Windows.
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True)
        else:
            p.terminate()
            if not p.waitForFinished(3000):
                p.kill()

    def _on_state(self, key):
        running = self._is_running(key)
        text = "● running" if running else "○ stopped"
        color = RUNNING_COLOR if running else STOPPED_COLOR
        if key == MANAGER_KEY:
            self.mgr_status.setText(text)
            self.mgr_status.setStyleSheet("color: %s; font-weight: 600;" % color)
            self.mgr_btn.setText("Stop Manager" if running else "Start Manager")
        elif key in self.rows:
            r = self.rows[key]
            item = self.table.item(r, 1)
            if item:
                item.setText(text)
                item.setForeground(QtGui.QColor(color))
            btn = self.table.cellWidget(r, 2)
            if btn:
                btn.setText("Stop" if running else "Start")

    # ---- manager ----------------------------------------------------------
    def _toggle_manager(self):
        if self._is_running(MANAGER_KEY):
            self._stop_process(MANAGER_KEY)
            return
        bat = self.bat_edit.text()
        if not bat or not os.path.isfile(bat):
            self._log(MANAGER_KEY, "[launcher] set a valid labrad.bat path first\n")
            self.log_tabs.setCurrentWidget(self._log_widget(MANAGER_KEY, "Manager"))
            return
        margs = ["--registry", self.reg_edit.text(),
                 "--password", self.pw_edit.text(),
                 "--tls-required", "true" if self.tls_check.isChecked() else "false"]
        workdir = os.path.dirname(bat)
        if os.name == 'nt':
            self._start_process(MANAGER_KEY, "cmd.exe", ["/c", bat] + margs,
                                workdir, "Manager")
        else:
            self._start_process(MANAGER_KEY, bat, margs, workdir, "Manager")

    # ---- servers ----------------------------------------------------------
    def _toggle_server(self, name):
        if self._is_running(name):
            self._stop_process(name)
            return
        r = self.rows.get(name)
        if r is None:
            return
        path = self.table.item(r, 0).data(QtCore.Qt.UserRole)
        self._start_process(name, sys.executable, [path],
                            os.path.dirname(path), name)

    def _start_all(self):
        for name in list(self.rows):
            if not self._is_running(name):
                self._toggle_server(name)

    def _stop_all(self):
        for name in list(self.rows):
            self._stop_process(name)

    # ---- shutdown ---------------------------------------------------------
    def closeEvent(self, ev):
        running = [k for k in self.procs if self._is_running(k)]
        if running:
            resp = QtWidgets.QMessageBox.question(
                self, "Stop everything?",
                "%d process(es) are still running. Stop them and quit?" % len(running),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if resp != QtWidgets.QMessageBox.Yes:
                ev.ignore()
                return
        for k in list(self.procs):
            self._stop_process(k)
        self._save_config()
        ev.accept()


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle('Fusion')                 # modern cross-platform base style
    app.setStyleSheet(STYLESHEET)
    w = Launcher()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
