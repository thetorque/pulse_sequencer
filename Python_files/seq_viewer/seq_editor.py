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
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Channel", "Start (s)", "Duration (s)", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 32)
        self.table.setMinimumWidth(400)
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

        actions = QtWidgets.QHBoxLayout()
        exp = QtWidgets.QPushButton("Export .py")
        exp.clicked.connect(self._export)
        run = QtWidgets.QPushButton("Program + Run")
        run.setObjectName("primary")
        run.clicked.connect(self._run)
        actions.addWidget(exp)
        actions.addWidget(run)
        actions.addStretch(1)
        left.addLayout(actions)

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
        start_sp.valueChanged.connect(self._rebuild)
        dur_sp = self._spin(duration)
        dur_sp.valueChanged.connect(self._rebuild)
        rm = QtWidgets.QPushButton("×")
        rm.setFixedWidth(28)
        rm.clicked.connect(self._remove_clicked)
        self.table.setCellWidget(r, 0, combo)
        self.table.setCellWidget(r, 1, start_sp)
        self.table.setCellWidget(r, 2, dur_sp)
        self.table.setCellWidget(r, 3, rm)

    def _remove_clicked(self):
        btn = self.sender()
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 3) is btn:
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
            p.start_single()
            self.status.setStyleSheet("color:#16a34a;")
            self.status.setText("programmed + started single run")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Program + Run failed", str(e))

    def closeEvent(self, ev):
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
