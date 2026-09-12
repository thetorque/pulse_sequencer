"""
seq_viewer.py -- a pulse-sequence timing-diagram viewer (read-only).

Compile a pulser3.Sequence and *see* it: each TTL channel is a lane whose
waveform steps high when the channel is on, across a shared time axis. No
hardware and no LabRAD needed -- pulser3 imports fine without the `ok` module,
so you can preview a sequence on any machine before running it.

Sources:
  * Demo -- a small built-in sequence, for an instant look.
  * Open... -- a .py file that defines build_sequence() returning a
    pulser3.Sequence (or a module-level `sequence`).

The drawing lives in seq_plot.SequencePlot (shared with seq_editor.py).

Needs PyQt5 + pyqtgraph:  pip install PyQt5 pyqtgraph
Run:  python seq_viewer.py
"""
import importlib.util
import os
import sys

from PyQt5 import QtWidgets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seq_plot import SequencePlot, pg    # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulser3 import Sequence, hwconfig   # noqa: E402


def demo_sequence():
    seq = Sequence(channel_map=hwconfig.CHANNELS)
    seq.add_pulse('sMOT_AO', 0.0, 0.3)
    seq.add_pulse('sMOT_PROBE', 0.1, 0.5)
    seq.add_pulse('BIG_MOT_SH', 0.3, 0.5)
    seq.add_pulse('405_ECDL', 0.4, 0.2)
    seq.add_pulse('DiffCountTrigger', 0.0, 0.02)
    seq.add_pulse('DiffCountTrigger', 0.5, 0.02)
    seq.extend_length(1.0)
    return seq


class SeqViewer(QtWidgets.QWidget):
    def __init__(self, parent=None, cxn=None):     # cxn accepted (dashboard) but unused
        super().__init__(parent)
        self.setObjectName('Root')
        self.setWindowTitle('Sequence Viewer')
        self.resize(760, 460)
        self._seq = None
        self._build_ui()
        if pg is not None:
            self._set_sequence(demo_sequence(), 'demo')

    def _build_ui(self):
        v = QtWidgets.QVBoxLayout(self)
        if pg is None:
            v.addWidget(QtWidgets.QLabel("pyqtgraph is not installed.\n\n    pip install pyqtgraph"))
            return
        bar = QtWidgets.QHBoxLayout()
        demo = QtWidgets.QPushButton("Demo")
        demo.clicked.connect(lambda: self._set_sequence(demo_sequence(), 'demo'))
        openb = QtWidgets.QPushButton("Open…")
        openb.clicked.connect(self._open)
        self.all_check = QtWidgets.QCheckBox("Show all channels")
        self.all_check.toggled.connect(self._replot)
        self.info = QtWidgets.QLabel("")
        self.info.setStyleSheet("color:#6b7280;")
        bar.addWidget(demo)
        bar.addWidget(openb)
        bar.addWidget(self.all_check)
        bar.addWidget(self.info, 1)
        v.addLayout(bar)
        self.plot = SequencePlot()
        v.addWidget(self.plot, 1)

    def _open(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open a sequence .py (defines build_sequence())", filter="Python (*.py)")
        if not path:
            return
        try:
            folder = os.path.dirname(path)
            if folder not in sys.path:
                sys.path.insert(0, folder)
            spec = importlib.util.spec_from_file_location('user_seq', path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, 'build_sequence'):
                seq = mod.build_sequence()
            elif hasattr(mod, 'sequence'):
                seq = mod.sequence
            else:
                raise Exception("define build_sequence() -> Sequence, or a `sequence` variable")
            self._set_sequence(seq, os.path.basename(path))
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Could not load sequence", str(e))

    def _set_sequence(self, seq, label):
        self._seq = seq
        self._label = label
        self._replot()

    def _replot(self):
        if pg is None or self._seq is None:
            return
        try:
            n, T = self.plot.set_sequence(self._seq, self.all_check.isChecked())
            self.info.setText("%s  —  %d channels, length %.4g s" % (self._label, n, T))
        except Exception as e:
            self.info.setText("cannot compile: %s" % e)


DASHBOARD_PANEL = {'title': 'Sequence Viewer', 'widget': SeqViewer}


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
    w = SeqViewer()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
