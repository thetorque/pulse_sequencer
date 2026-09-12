"""
seq_editor.py -- interactive pulse-sequence editor (v2).

Build a TTL sequence in a table (channel / start / duration), watch the timing
diagram update live as you type, then Export it as a build_sequence() .py or
Program + Run it on the hardware. The diagram is the shared seq_plot.SequencePlot
used by the read-only viewer.

Editing + Export need no hardware (pulser3 imports without `ok`). Program + Run
needs the manager + Pulser server (it prompts for the LabRAD password, or uses a
shared connection when embedded in the dashboard).

Needs PyQt5 + pyqtgraph:  pip install PyQt5 pyqtgraph
Run:  python seq_editor.py
"""
import os
import sys
import time

from PyQt5 import QtWidgets, QtCore

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seq_plot import SequencePlot, pg    # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulser3 import Sequence, hwconfig   # noqa: E402

try:
    import labrad
    from labrad.units import s as _S
except Exception:
    labrad = None
    _S = None

CHANNELS = [name for name, _n in sorted(hwconfig.CHANNELS.items(), key=lambda kv: kv[1])]


class SeqEditor(QtWidgets.QWidget):
    def __init__(self, parent=None, cxn=None):
        super().__init__(parent)
        self.setObjectName('Root')
        self.setWindowTitle('Sequence Editor')
        self.resize(900, 520)
        self.cxn = cxn
        self._owns_cxn = False
        self._seq = None
        self._p = None                 # pulser server ref while running
        self._run_start = None
        self._total = None             # loop count (None = infinite)
        self._run_timer = None
        self._updating = False         # guard while linking duration <-> stop
        self._build_ui()
        if pg is not None:
            self._add_row('sMOT_PROBE', 0.1, 0.5)
            self._add_row('BIG_MOT_SH', 0.3, 0.5)
            self.length_spin.setValue(1.0)
            self._rebuild()

    # ---- UI ----------------------------------------------------------------
    def _build_ui(self):
        root = QtWidgets.QHBoxLayout(self)
        if pg is None:
            root.addWidget(QtWidgets.QLabel("pyqtgraph is not installed.\n\n    pip install pyqtgraph"))
            return

        left = QtWidgets.QVBoxLayout()
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Channel", "Start (s)", "Duration (s)", "Stop (s)", "Del"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(0, 148)
        self.table.setColumnWidth(1, 88)
        self.table.setColumnWidth(2, 92)
        self.table.setColumnWidth(3, 92)
        self.table.setColumnWidth(4, 40)
        self.table.setMinimumWidth(480)
        left.addWidget(self.table, 1)

        row = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton("+ Pulse")
        add.clicked.connect(lambda: (self._add_row(), self._rebuild()))
        row.addWidget(add)
        row.addWidget(QtWidgets.QLabel("Length:"))
        self.length_spin = self._spin(1.0)
        self.length_spin.valueChanged.connect(self._rebuild)
        row.addWidget(self.length_spin)
        row.addStretch(1)
        left.addLayout(row)

        runrow = QtWidgets.QHBoxLayout()
        runrow.addWidget(QtWidgets.QLabel("Loops:"))
        self.loops_spin = QtWidgets.QSpinBox()
        self.loops_spin.setRange(1, 65535)
        self.loops_spin.setValue(1)
        runrow.addWidget(self.loops_spin)
        self.inf_check = QtWidgets.QCheckBox("∞")
        self.inf_check.setToolTip("Run forever until Stop")
        self.inf_check.toggled.connect(lambda on: self.loops_spin.setEnabled(not on))
        runrow.addWidget(self.inf_check)
        runrow.addStretch(1)
        left.addLayout(runrow)

        actions = QtWidgets.QHBoxLayout()
        exp = QtWidgets.QPushButton("Export .py")
        exp.clicked.connect(self._export)
        self.run_btn = QtWidgets.QPushButton("Program + Run")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self._run)
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        actions.addWidget(exp)
        actions.addWidget(self.run_btn)
        actions.addWidget(self.stop_btn)
        actions.addStretch(1)
        left.addLayout(actions)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setVisible(False)
        left.addWidget(self.progress)
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        left.addWidget(self.status)

        rightw = QtWidgets.QWidget()
        rv = QtWidgets.QVBoxLayout(rightw)
        rv.setContentsMargins(0, 0, 0, 0)
        self.plot = SequencePlot()
        rv.addWidget(self.plot)

        leftw = QtWidgets.QWidget()
        leftw.setLayout(left)
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        split.addWidget(leftw)
        split.addWidget(rightw)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        root.addWidget(split)

    def _spin(self, val):
        sp = QtWidgets.QDoubleSpinBox()
        sp.setDecimals(6)
        sp.setRange(0.0, 85.0)
        sp.setSingleStep(0.001)
        sp.setValue(val)
        return sp

    def _add_row(self, channel=None, start=0.0, duration=0.001):
        r = self.table.rowCount()
        self.table.insertRow(r)
        combo = QtWidgets.QComboBox()
        combo.addItems(CHANNELS)
        if channel in CHANNELS:
            combo.setCurrentIndex(CHANNELS.index(channel))
        combo.currentIndexChanged.connect(self._rebuild)
        start_sp = self._spin(start)
        dur_sp = self._spin(duration)
        stop_sp = self._spin(start + duration)      # stop = start + duration
        # start/duration edits recompute stop; a stop edit recomputes duration.
        # _updating guards against the setValue() feedback loop.
        start_sp.valueChanged.connect(lambda: self._link(start_sp, dur_sp, stop_sp, 'start'))
        dur_sp.valueChanged.connect(lambda: self._link(start_sp, dur_sp, stop_sp, 'dur'))
        stop_sp.valueChanged.connect(lambda: self._link(start_sp, dur_sp, stop_sp, 'stop'))
        rm = QtWidgets.QPushButton("×")
        rm.setFixedWidth(28)
        rm.clicked.connect(self._remove_clicked)
        self.table.setCellWidget(r, 0, combo)
        self.table.setCellWidget(r, 1, start_sp)
        self.table.setCellWidget(r, 2, dur_sp)
        self.table.setCellWidget(r, 3, stop_sp)
        self.table.setCellWidget(r, 4, rm)

    def _link(self, start_sp, dur_sp, stop_sp, which):
        """Keep stop = start + duration. Editing start/duration moves stop;
        editing stop sets duration (= stop - start)."""
        if self._updating:
            return
        self._updating = True
        if which == 'stop':
            dur_sp.setValue(max(0.0, stop_sp.value() - start_sp.value()))
        else:
            stop_sp.setValue(start_sp.value() + dur_sp.value())
        self._updating = False
        self._rebuild()

    def _remove_clicked(self):
        btn = self.sender()
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 4) is btn:
                self.table.removeRow(r)
                break
        self._rebuild()

    # ---- build + draw ------------------------------------------------------
    def _pulses(self):
        out = []
        for r in range(self.table.rowCount()):
            out.append((self.table.cellWidget(r, 0).currentText(),
                        self.table.cellWidget(r, 1).value(),
                        self.table.cellWidget(r, 2).value()))
        return out

    def _make_sequence(self):
        seq = Sequence(channel_map=hwconfig.CHANNELS)
        for name, start, dur in self._pulses():
            seq.add_pulse(name, start, dur)
        L = self.length_spin.value()
        if L > 0:
            seq.extend_length(L)
        return seq

    def _rebuild(self):
        if pg is None:
            return
        try:
            seq = self._make_sequence()
            seq.to_lines()          # validate: rejects overlaps / out-of-range / empty
            n, T = self.plot.set_sequence(seq)
            self._seq = seq
            self.status.setStyleSheet("color:#16a34a;")
            self.status.setText("ok — %d channels, length %.4g s" % (n, T))
        except Exception as e:
            self._seq = None
            self.status.setStyleSheet("color:#dc2626;")
            self.status.setText(str(e))

    # ---- export ------------------------------------------------------------
    def _export(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export sequence as .py", "sequence.py", "Python (*.py)")
        if not path:
            return
        lines = ["from pulser3 import Sequence, hwconfig", "", "",
                 "def build_sequence():",
                 "    seq = Sequence(channel_map=hwconfig.CHANNELS)"]
        for name, start, dur in self._pulses():
            lines.append("    seq.add_pulse(%r, %g, %g)" % (name, start, dur))
        L = self.length_spin.value()
        if L > 0:
            lines.append("    seq.extend_length(%g)" % L)
        lines += ["    return seq", ""]
        try:
            with open(path, 'w') as f:
                f.write("\n".join(lines))
            self.status.setStyleSheet("color:#16a34a;")
            self.status.setText("exported %s" % os.path.basename(path))
        except OSError as e:
            QtWidgets.QMessageBox.warning(self, "Export failed", str(e))

    # ---- program + run -----------------------------------------------------
    def _pulser(self):
        if self.cxn is None:
            if labrad is None:
                raise Exception("pylabrad is not installed")
            host = os.environ.get('LABRADHOST', 'localhost') or 'localhost'
            pw = os.environ.get('LABRADPASSWORD', '') or ''
            try:
                self.cxn = labrad.connect(host=host, username='', password=pw,
                                          tls_mode=('on' if os.environ.get('LABRAD_TLS', 'off')
                                                    in ('on', 'true', '1') else 'off'))
                self._owns_cxn = True
            except Exception:
                pw, ok = QtWidgets.QInputDialog.getText(
                    self, "LabRAD password", "Password for %s:" % host,
                    QtWidgets.QLineEdit.Password)
                if not ok:
                    raise Exception("cancelled")
                self.cxn = labrad.connect(host=host, username='', password=pw, tls_mode='off')
                self._owns_cxn = True
        return self.cxn.pulser

    def _run(self):
        if self._seq is None:
            QtWidgets.QMessageBox.warning(self, "Cannot run", "Fix the sequence first (see status).")
            return
        try:
            p = self._pulser()
            p.new_sequence()
            for name, start, dur in self._pulses():
                p.add_ttl_pulse(name, start * _S, dur * _S)
            L = self.length_spin.value()
            if L > 0:
                p.extend_sequence_length(L * _S)
            p.program_sequence()
            if self.inf_check.isChecked():
                p.start_infinite(); self._total = None
            else:
                loops = self.loops_spin.value()
                if loops == 1:
                    p.start_single()
                else:
                    p.start_number(loops)
                self._total = loops
            self._p = p
            self._run_start = time.time()
            self._begin_run_ui()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Program + Run failed", str(e))
            self._end_run_ui()

    def _begin_run_ui(self):
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        if self._total is None:
            self.progress.setRange(0, 0)          # busy/indeterminate
        else:
            self.progress.setRange(0, self._total)
            self.progress.setValue(0)
        self.progress.setVisible(True)
        if self._run_timer is None:
            self._run_timer = QtCore.QTimer(self)
            self._run_timer.timeout.connect(self._poll_run)
        self._run_timer.start(200)
        self._poll_run()

    def _poll_run(self):
        if self._p is None:
            return
        elapsed = time.time() - self._run_start
        try:
            completed = int(self._p.repeatitions_completed())
        except Exception as e:
            self.status.setStyleSheet("color:#dc2626;")
            self.status.setText("poll error: %s" % e)
            return
        try:
            done = bool(self._p.is_sequence_done())
        except Exception:
            done = self._total is not None and completed >= self._total   # old server
        self.status.setStyleSheet("color:#16a34a;")
        if self._total is None:
            self.status.setText("running ∞ — %d loops · %.1f s" % (completed, elapsed))
            return
        self.progress.setValue(self._total if done else min(completed, self._total))
        if done:
            self._run_timer.stop()
            self.status.setText("done — %d loop(s) in %.2f s" % (self._total, elapsed))
            self._end_run_ui()
        else:
            self.status.setText("running — loop %d/%d · %.1f s"
                                % (min(completed, self._total), self._total, elapsed))

    def _stop(self):
        try:
            if self._p is not None:
                self._p.stop_sequence()
        except Exception:
            pass
        if self._run_timer is not None:
            self._run_timer.stop()
        elapsed = (time.time() - self._run_start) if self._run_start else 0.0
        self.status.setStyleSheet("color:#6b7280;")
        self.status.setText("stopped after %.1f s" % elapsed)
        self._end_run_ui()

    def _end_run_ui(self):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress.setVisible(False)
        self.progress.setRange(0, 1)              # reset out of busy mode

    def closeEvent(self, ev):
        if self._run_timer is not None:
            self._run_timer.stop()
        try:
            if self.cxn is not None and self._owns_cxn:
                self.cxn.disconnect()
        except Exception:
            pass
        ev.accept()


DASHBOARD_PANEL = {'title': 'Sequence Editor', 'widget': SeqEditor}


def main():
    app = QtWidgets.QApplication(sys.argv)
    gui = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pulser_gui')
    if gui not in sys.path:
        sys.path.insert(0, gui)
    try:
        import theme
        theme.apply(app)
    except Exception:
        app.setStyle('Fusion')
    w = SeqEditor()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
