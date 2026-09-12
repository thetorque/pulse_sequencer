"""
script_scanner_gui.py -- PyQt5 operator view for the ScriptScanner server.

Launch experiments (single / repeat / scan / schedule) and watch the live queue,
running scripts (progress bar + pause/resume/stop), and scheduled scans. py3/
PyQt5 rebuild of the legacy clients/script_scanner_gui (PyQt4 + qt4reactor + a
big tree_view parameter editor) in our blocking-client + QTimer-poll style -- no
reactor, layout built in code.

This is the ORCHESTRATION half of the old GUI. The parameter-editing half (the
tree_view editor bound to the ParameterVault) is intentionally left out; a scan
here just takes a typed (collection, parameter, units) -- e.g. the bundled
'PMT Point' scans Spectrum / frequency / kHz. A dedicated ParameterVault editor
can come later.

Needs PyQt5 (LabRAD env from LABRADHOST/LABRADPASSWORD/LABRAD_TLS; prompts for a
password if the env credentials don't work):

    pip install PyQt5
    python script_scanner_gui.py
"""
import os
import sys
import traceback

from PyQt5 import QtCore, QtWidgets

import labrad
from labrad.units import WithUnit

POLL_MS = 400
PRIORITIES = ['Normal', 'First in Queue', 'Pause All Others']


class ScriptScannerGui(QtWidgets.QWidget):
    def __init__(self, parent=None, cxn=None):
        super().__init__(parent)
        self.setObjectName('Root')
        self.setWindowTitle('Script Scanner')
        self.resize(760, 520)
        self.server = None
        self._run_rows = {}               # ident -> dict of row widgets
        self._owns_cxn = cxn is None      # only disconnect a connection we opened
        self.cxn = cxn or self._connect() or self._login_loop()
        self._build_ui()
        if self.cxn is not None:
            try:
                self.server = self.cxn.scriptscanner
            except Exception as e:
                self._fatal("ScriptScanner not available:\n%s" % e)
                return
            self._populate_experiments()
            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self._poll)
            self.timer.start(POLL_MS)

    # ---- connection (env, then prompt) ------------------------------------
    def _connect(self, host=None, password=None):
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

    # ---- error helper -----------------------------------------------------
    @staticmethod
    def _short_err(e):
        s = str(e).strip()
        return s.splitlines()[-1] if s else e.__class__.__name__

    def _warn(self, title, e):
        QtWidgets.QMessageBox.warning(self, title, self._short_err(e))

    def _fatal(self, msg):
        lay = self.layout() or QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(msg)
        label.setWordWrap(True)
        lay.addWidget(label)

    # ---- UI ---------------------------------------------------------------
    def _build_ui(self):
        outer = QtWidgets.QHBoxLayout(self)
        if self.cxn is None:
            msg = "Cannot reach LabRAD"
            if hasattr(self, '_err'):
                msg += ":\n%s" % self._err
            outer.addWidget(QtWidgets.QLabel(msg))
            return

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(self._build_launch_panel())
        splitter.addWidget(self._build_status_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter)

    def _build_launch_panel(self):
        box = QtWidgets.QGroupBox("Launch")
        v = QtWidgets.QVBoxLayout(box)

        v.addWidget(QtWidgets.QLabel("Experiment"))
        self.experiment_combo = QtWidgets.QComboBox()
        v.addWidget(self.experiment_combo)

        # --- run once ---
        self.run_btn = QtWidgets.QPushButton("Run once")
        self.run_btn.setObjectName('primary')
        self.run_btn.clicked.connect(self._on_run)
        v.addWidget(self.run_btn)

        # --- repeat ---
        rep = QtWidgets.QHBoxLayout()
        rep.addWidget(QtWidgets.QLabel("Repeat"))
        self.repeat_spin = QtWidgets.QSpinBox()
        self.repeat_spin.setRange(1, 1000000)
        self.repeat_spin.setValue(5)
        rep.addWidget(self.repeat_spin)
        rep.addWidget(QtWidgets.QLabel("×"))
        self.save_check = QtWidgets.QCheckBox("save")
        self.save_check.setChecked(True)
        rep.addWidget(self.save_check)
        self.repeat_btn = QtWidgets.QPushButton("Go")
        self.repeat_btn.clicked.connect(self._on_repeat)
        rep.addWidget(self.repeat_btn)
        v.addLayout(rep)

        # --- schedule ---
        sch = QtWidgets.QHBoxLayout()
        sch.addWidget(QtWidgets.QLabel("Every"))
        self.schedule_spin = QtWidgets.QDoubleSpinBox()
        self.schedule_spin.setRange(0.1, 1e6)
        self.schedule_spin.setDecimals(2)
        self.schedule_spin.setValue(10.0)
        self.schedule_spin.setSuffix(" s")
        sch.addWidget(self.schedule_spin)
        self.start_now_check = QtWidgets.QCheckBox("now")
        self.start_now_check.setChecked(True)
        sch.addWidget(self.start_now_check)
        self.schedule_btn = QtWidgets.QPushButton("Schedule")
        self.schedule_btn.clicked.connect(self._on_schedule)
        sch.addWidget(self.schedule_btn)
        v.addLayout(sch)

        self.priority_combo = QtWidgets.QComboBox()
        self.priority_combo.addItems(PRIORITIES)
        pri = QtWidgets.QHBoxLayout()
        pri.addWidget(QtWidgets.QLabel("Priority"))
        pri.addWidget(self.priority_combo, 1)
        v.addLayout(pri)

        # --- scan ---
        v.addWidget(self._hline())
        scan_box = QtWidgets.QGroupBox("Scan a parameter")
        form = QtWidgets.QFormLayout(scan_box)
        self.measure_combo = QtWidgets.QComboBox()          # filled with (same) + experiments
        form.addRow("Measure with", self.measure_combo)
        self.collection_edit = QtWidgets.QLineEdit("Spectrum")
        form.addRow("Collection", self.collection_edit)
        self.param_edit = QtWidgets.QLineEdit("frequency")
        form.addRow("Parameter", self.param_edit)
        mm = QtWidgets.QHBoxLayout()
        self.min_spin = QtWidgets.QDoubleSpinBox()
        self.min_spin.setRange(-1e9, 1e9)
        self.min_spin.setValue(-3.0)
        self.max_spin = QtWidgets.QDoubleSpinBox()
        self.max_spin.setRange(-1e9, 1e9)
        self.max_spin.setValue(3.0)
        mm.addWidget(self.min_spin)
        mm.addWidget(QtWidgets.QLabel("to"))
        mm.addWidget(self.max_spin)
        form.addRow("Range", mm)
        se = QtWidgets.QHBoxLayout()
        self.steps_spin = QtWidgets.QSpinBox()
        self.steps_spin.setRange(2, 1000000)
        self.steps_spin.setValue(21)
        self.units_edit = QtWidgets.QLineEdit("kHz")
        se.addWidget(self.steps_spin)
        se.addWidget(QtWidgets.QLabel("steps in"))
        se.addWidget(self.units_edit)
        form.addRow("Steps", se)
        self.scan_btn = QtWidgets.QPushButton("Scan")
        self.scan_btn.setObjectName('primary')
        self.scan_btn.clicked.connect(self._on_scan)
        form.addRow(self.scan_btn)
        v.addWidget(scan_box)

        v.addStretch(1)
        return box

    def _build_status_panel(self):
        box = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)

        run_box = QtWidgets.QGroupBox("Running")
        rl = QtWidgets.QVBoxLayout(run_box)
        self.running_table = QtWidgets.QTableWidget(0, 5)
        self.running_table.setHorizontalHeaderLabels(["ID", "Experiment", "Status", "Progress", ""])
        self._stretch_table(self.running_table, stretch_col=1)
        rl.addWidget(self.running_table)
        v.addWidget(run_box, 2)

        q_box = QtWidgets.QGroupBox("Queue")
        ql = QtWidgets.QVBoxLayout(q_box)
        self.queue_table = QtWidgets.QTableWidget(0, 3)
        self.queue_table.setHorizontalHeaderLabels(["ID", "Experiment", ""])
        self._stretch_table(self.queue_table, stretch_col=1)
        ql.addWidget(self.queue_table)
        v.addWidget(q_box, 1)

        s_box = QtWidgets.QGroupBox("Scheduled")
        sl = QtWidgets.QVBoxLayout(s_box)
        self.scheduled_table = QtWidgets.QTableWidget(0, 4)
        self.scheduled_table.setHorizontalHeaderLabels(["ID", "Experiment", "Every (s)", ""])
        self._stretch_table(self.scheduled_table, stretch_col=1)
        sl.addWidget(self.scheduled_table)
        v.addWidget(s_box, 1)

        return box

    @staticmethod
    def _stretch_table(table, stretch_col):
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        hh = table.horizontalHeader()
        for c in range(table.columnCount()):
            mode = QtWidgets.QHeaderView.Stretch if c == stretch_col else QtWidgets.QHeaderView.ResizeToContents
            hh.setSectionResizeMode(c, mode)

    @staticmethod
    def _hline():
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        return line

    # ---- population -------------------------------------------------------
    def _populate_experiments(self):
        try:
            scripts = list(self.server.get_available_scripts())
        except Exception as e:
            self._fatal("Could not list scripts:\n%s" % e)
            return
        self.experiment_combo.clear()
        self.experiment_combo.addItems(scripts)
        self.measure_combo.clear()
        self.measure_combo.addItem("(same as experiment)")
        self.measure_combo.addItems(scripts)

    def _selected_experiment(self):
        return self.experiment_combo.currentText().strip()

    # ---- launch actions ---------------------------------------------------
    def _on_run(self):
        name = self._selected_experiment()
        if not name:
            return
        try:
            self.server.new_experiment(name)
        except Exception as e:
            self._warn("Run failed", e)

    def _on_repeat(self):
        name = self._selected_experiment()
        if not name:
            return
        try:
            self.server.new_script_repeat(name, int(self.repeat_spin.value()),
                                          bool(self.save_check.isChecked()))
        except Exception as e:
            self._warn("Repeat failed", e)

    def _on_schedule(self):
        name = self._selected_experiment()
        if not name:
            return
        try:
            self.server.new_script_schedule(name, WithUnit(float(self.schedule_spin.value()), 's'),
                                            self.priority_combo.currentText(),
                                            bool(self.start_now_check.isChecked()))
        except Exception as e:
            self._warn("Schedule failed", e)

    def _on_scan(self):
        name = self._selected_experiment()
        if not name:
            return
        measure = self.measure_combo.currentText()
        if measure.startswith("(same"):
            measure = name
        collection = self.collection_edit.text().strip()
        parameter = self.param_edit.text().strip()
        units = self.units_edit.text().strip()
        if not (collection and parameter and units):
            self._warn("Scan failed", ValueError("collection, parameter and units are required"))
            return
        try:
            self.server.new_script_scan(name, measure, collection, parameter,
                                        float(self.min_spin.value()), float(self.max_spin.value()),
                                        int(self.steps_spin.value()), units)
        except Exception as e:
            self._warn("Scan failed", e)

    # ---- table actions ----------------------------------------------------
    def _cancel_queued(self, ident):
        try:
            self.server.remove_queued_script(ident)
        except Exception as e:
            self._warn("Cancel failed", e)

    def _cancel_scheduled(self, ident):
        try:
            self.server.cancel_scheduled_script(ident)
        except Exception as e:
            self._warn("Cancel failed", e)

    def _stop_running(self, ident):
        try:
            self.server.stop_script(ident)
        except Exception as e:
            self._warn("Stop failed", e)

    def _pause_running(self, ident, should_pause):
        try:
            self.server.pause_script(ident, should_pause)
        except Exception as e:
            self._warn("Pause failed", e)

    # ---- polling ----------------------------------------------------------
    def _poll(self):
        if self.server is None:
            return
        try:
            running = self.server.get_running()
            queue = self.server.get_queue()
            scheduled = self.server.get_scheduled()
        except Exception:
            return  # manager/server briefly unavailable; try again next tick
        self._update_running(running)
        self._update_queue(queue)
        self._update_scheduled(scheduled)

    def _update_running(self, running):
        current = {}
        for ident, name in running:
            ident = int(ident)
            current[ident] = name
            try:
                status, pct = self.server.get_progress(ident)
            except Exception:
                status, pct = '?', 0.0
            if ident not in self._run_rows:
                self._add_running_row(ident, name)
            self._set_running_row(ident, status, float(pct))
        # remove rows that are no longer running
        for ident in list(self._run_rows.keys()):
            if ident not in current:
                self._remove_running_row(ident)

    def _add_running_row(self, ident, name):
        table = self.running_table
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(ident)))
        table.setItem(row, 1, QtWidgets.QTableWidgetItem(name))
        status_item = QtWidgets.QTableWidgetItem("")
        table.setItem(row, 2, status_item)
        bar = QtWidgets.QProgressBar()
        bar.setRange(0, 100)
        table.setCellWidget(row, 3, bar)
        btns = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(btns)
        h.setContentsMargins(2, 1, 2, 1)
        h.setSpacing(4)
        pause_btn = QtWidgets.QPushButton("Pause")
        stop_btn = QtWidgets.QPushButton("Stop")
        pause_btn.clicked.connect(lambda _, i=ident: self._on_pause_clicked(i))
        stop_btn.clicked.connect(lambda _, i=ident: self._stop_running(i))
        h.addWidget(pause_btn)
        h.addWidget(stop_btn)
        table.setCellWidget(row, 4, btns)
        self._run_rows[ident] = {'status': status_item, 'bar': bar,
                                 'pause_btn': pause_btn, 'stop_btn': stop_btn,
                                 'paused': False}

    def _set_running_row(self, ident, status, pct):
        r = self._run_rows.get(ident)
        if r is None:
            return
        r['status'].setText(status)
        r['bar'].setValue(int(round(pct)))
        paused = status in ('Paused', 'Pausing')
        r['paused'] = paused
        r['pause_btn'].setText("Resume" if paused else "Pause")

    def _on_pause_clicked(self, ident):
        r = self._run_rows.get(ident)
        if r is None:
            return
        # ask to pause if currently running, resume if currently paused
        self._pause_running(ident, not r['paused'])

    def _remove_running_row(self, ident):
        del self._run_rows[ident]
        self._rebuild_running_table_from_rows()

    def _rebuild_running_table_from_rows(self):
        # simplest correct approach: find the row whose ID cell is gone and drop it.
        table = self.running_table
        ids_present = set(self._run_rows.keys())
        for row in range(table.rowCount() - 1, -1, -1):
            item = table.item(row, 0)
            if item is None or int(item.text()) not in ids_present:
                table.removeRow(row)

    def _update_queue(self, queue):
        rows = [(int(ident), name) for ident, name, order in queue]
        self._fill_simple_table(self.queue_table, rows, self._cancel_queued)

    def _update_scheduled(self, scheduled):
        rows = []
        for ident, name, dur in scheduled:
            try:
                secs = float(dur['s'])
            except Exception:
                secs = float(dur)
            rows.append((int(ident), name, "%.2f" % secs))
        self._fill_scheduled_table(self.scheduled_table, rows)

    def _fill_simple_table(self, table, rows, cancel_cb):
        table.setRowCount(0)
        for ident, name in rows:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(ident)))
            table.setItem(row, 1, QtWidgets.QTableWidgetItem(name))
            btn = QtWidgets.QPushButton("Cancel")
            btn.clicked.connect(lambda _, i=ident: cancel_cb(i))
            table.setCellWidget(row, 2, btn)

    def _fill_scheduled_table(self, table, rows):
        table.setRowCount(0)
        for ident, name, secs in rows:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(ident)))
            table.setItem(row, 1, QtWidgets.QTableWidgetItem(name))
            table.setItem(row, 2, QtWidgets.QTableWidgetItem(secs))
            btn = QtWidgets.QPushButton("Cancel")
            btn.clicked.connect(lambda _, i=ident: self._cancel_scheduled(i))
            table.setCellWidget(row, 3, btn)

    def closeEvent(self, ev):
        try:
            if self.cxn is not None and self._owns_cxn:
                self.cxn.disconnect()
        except Exception:
            pass
        ev.accept()


# dashboard.py discovers panels by this manifest
DASHBOARD_PANEL = {'title': 'Script Scanner', 'widget': ScriptScannerGui}


def main():
    app = QtWidgets.QApplication(sys.argv)
    try:
        import theme
        theme.apply(app)
    except Exception:
        traceback.print_exc()
    w = ScriptScannerGui()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
