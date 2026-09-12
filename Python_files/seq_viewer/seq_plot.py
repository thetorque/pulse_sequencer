"""
seq_plot.py -- shared timing-diagram widget for the sequence viewer/editor.

SequencePlot.set_sequence(seq) draws a pulser3.Sequence as stacked digital
lanes (one per TTL channel) on a shared time axis. Used by both seq_viewer.py
(read-only) and seq_editor.py (live while editing).
"""
import os
import sys

try:
    import pyqtgraph as pg
except ImportError:
    pg = None

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pulser3 import hwconfig          # noqa: E402

PENS = ['#2563eb', '#0891b2', '#7c3aed', '#d97706', '#16a34a', '#dc2626', '#db2777']

if pg is not None:
    pg.setConfigOptions(antialias=True, background='w', foreground='#1f2328')

    class SequencePlot(pg.PlotWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._names = {num: name for name, num in
                           sorted(hwconfig.CHANNELS.items(), key=lambda kv: kv[0])}
            self.setLabel('bottom', 'time', units='s')
            self.showGrid(x=True, y=False, alpha=0.2)
            self.setMouseEnabled(x=True, y=False)   # zoom/pan the time axis only
            self.hideButtons()

        def set_sequence(self, seq, show_all=False):
            """Draw the sequence. Returns (n_channels_shown, length_s). May raise
            SequenceError if the sequence doesn't compile (overlap, out of range)."""
            self.clear()
            rows = seq.human_readable()             # [(t_s, channel_int, bits), ...]
            n_ch = seq.channel_total
            used = [i for i in range(n_ch) if any(r[2][i] == '1' for r in rows)]
            shown = list(range(n_ch)) if show_all else (used or [0])
            T = rows[-1][0] if rows else 0.0
            left = []
            for lane, ch in enumerate(shown):
                base = -lane
                hi = base + 0.72
                xs, ys = [], []
                prev = int(rows[0][2][ch])
                xs.append(rows[0][0]); ys.append(hi if prev else base)
                for r in rows[1:]:
                    v = int(r[2][ch])
                    xs.append(r[0]); ys.append(hi if prev else base)
                    xs.append(r[0]); ys.append(hi if v else base)
                    prev = v
                self.plot(xs, ys, pen=pg.mkPen(PENS[ch % len(PENS)], width=2))
                left.append((base + 0.36, self._names.get(ch, 'ch%d' % ch)))
            self.getAxis('left').setTicks([left, []])
            self.setYRange(-(len(shown) - 1) - 0.4, 0.9, padding=0)
            self.setXRange(0, T if T > 0 else 1.0, padding=0.02)
            return len(shown), T
else:
    SequencePlot = None
