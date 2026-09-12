"""
pmt_control.py -- PyQt5 control panel for NormalPMTFlow.

Switch the counting mode (Normal / Differential), change the collection window,
start/stop recording into the Data Vault, and watch the live count. py3/PyQt5
rebuild of the legacy clients/PMT_CONTROL.py (which used a .ui file + qt4reactor)
in our blocking-client + poll style -- no reactor, layout built in code.

The live count is polled only when recording with a short window (a blocking
Get Next Counts on a long window would freeze the UI); the Live Grapher is the
place to watch long traces.

Needs PyQt5 (LabRAD env from LABRADHOST/LABRADPASSWORD/LABRAD_TLS; prompts for a
password if the env credentials don't work):

    pip install PyQt5
    python pmt_control.py
"""
import os
import sys

from PyQt5 import QtCore, QtWidgets

import labrad
from labrad.units import s

POLL_MS = 500
COUNT_POLL_MAX_WINDOW = 1.0    # only poll a live count for windows <= this (s)


class PMTControl(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName('PMTControl')
        self.setWindowTitle('PMT Control')
        self.resize(360, 260)
        self.server = None
        self._syncing = False
        self.cxn = self._connect() or self._login_loop()
        self._build_ui()
        if self.cxn is not None:
            try:
                self.server = self.cxn.normalpmtflow
            except Exception as e:
                self._fatal("NormalPMTFlow not available:\n%s" % e)
                return
            self._init_from_server()
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

    # ---- UI ---------------------------------------------------------------
    def _fatal(self, msg):
        lay = self.layout() or QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(msg)
        label.setWordWrap(True)
        lay.addWidget(label)

    def _build_ui(self):
        form = QtWidgets.QFormLayout(self)
        if self.cxn is None:
            msg = "Cannot reach LabRAD"
            if hasattr(self, '_err'):
                msg += ":\n%s" % self._err
            form.addRow(QtWidgets.QLabel(msg))
            return

        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(['Normal', 'Differential'])
        self.mode_combo.currentIndexChanged.connect(self._on_mode)
        form.addRow("Mode:", self.mode_combo)

        self.window_spin = QtWidgets.QDoubleSpinBox()
        self.window_spin.setDecimals(3)
        self.window_spin.setSuffix(" s")
        self.window_spin.setRange(0.001, 60.0)
        self.window_spin.valueChanged.connect(self._on_window)
        form.addRow("Collection window:", self.window_spin)

        self.record_btn = QtWidgets.QPushButton("Record: OFF")
        self.record_btn.setCheckable(True)
        self.record_btn.toggled.connect(self._on_record)
        form.addRow(self.record_btn)

        self.newset_btn = QtWidgets.QPushButton("New Dataset")
        self.newset_btn.clicked.connect(self._on_newset)
        form.addRow(self.newset_btn)

        self.dataset_lbl = QtWidgets.QLabel("—")
        self.dataset_lbl.setWordWrap(True)
        form.addRow("Dataset:", self.dataset_lbl)

        self.count_lcd = QtWidgets.QLCDNumber()
        self.count_lcd.setDigitCount(8)
        self.count_lcd.display(0)
        form.addRow("Count (KC/s):", self.count_lcd)

    # ---- server sync ------------------------------------------------------
    def _init_from_server(self):
        try:
            lo, hi = self.server.get_time_length_range()
            self.window_spin.blockSignals(True)
            self.window_spin.setRange(float(lo), float(hi))
            self.window_spin.blockSignals(False)
        except Exception:
            pass
        self._sync(initial=True)

    def _sync(self, initial=False):
        """Pull current mode/window/state/dataset from the server (no feedback)."""
        self._syncing = True
        try:
            mode = self.server.getcurrentmode()
            i = self.mode_combo.findText(mode)
            if i >= 0:
                self.mode_combo.setCurrentIndex(i)
            if initial:
                self.window_spin.setValue(float(self.server.get_time_length()))
            running = bool(self.server.isrunning())
            self.record_btn.setChecked(running)
            self.record_btn.setText("Record: ON" if running else "Record: OFF")
            self.dataset_lbl.setText(self.server.currentdataset() or "—")
        except Exception:
            pass
        finally:
            self._syncing = False

    def _poll(self):
        if self.server is None:
            return
        self._sync()
        # live count: only for short windows (a long-window blocking read hangs UI)
        if self.record_btn.isChecked() and self.window_spin.value() <= COUNT_POLL_MAX_WINDOW:
            try:
                val = self.server.get_next_counts('ON', 1, True)
                self.count_lcd.display(float(val))
            except Exception:
                pass

    # ---- handlers ---------------------------------------------------------
    def _on_mode(self, _idx):
        if self._syncing:
            return
        try:
            self.server.set_mode(self.mode_combo.currentText())
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Set mode failed", str(e))

    def _on_window(self, value):
        if self._syncing:
            return
        try:
            self.server.set_time_length(value * s)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Set window failed", str(e))

    def _on_record(self, state):
        if self._syncing:
            return
        try:
            if state:
                self.server.record_data()
                self.dataset_lbl.setText(self.server.currentdataset() or "—")
            else:
                self.server.stoprecording()
                self.count_lcd.display(0)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Record toggle failed", str(e))
        self.record_btn.setText("Record: ON" if self.record_btn.isChecked() else "Record: OFF")

    def _on_newset(self):
        try:
            name = self.server.start_new_dataset()
            self.dataset_lbl.setText(name or "—")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "New dataset failed", str(e))

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
    w = PMTControl()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
