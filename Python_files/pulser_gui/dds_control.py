"""
dds_control.py -- PyQt5 DDS Control GUI for the Pulser's DDS channels.

Python-3 / PyQt5 port of the legacy clients/DDS_CONTROL.py (py2 / PyQt4,
QCustomFreqPower). One card per DDS channel (pulser3 hwconfig.DDS_CHANNELS):

    Frequency (MHz)  | Step (1 Hz .. 10 MHz) | Power (dBm) | RF ON/OFF | Identify

These are the channel's MANUAL state -- what it outputs between runs (row 0 of
every DDS table). Values are sent when you press Enter / leave the field / use
the arrows (no keyboard tracking), and the server applies them at once.

Like switch_control.py this uses pylabrad's BLOCKING client and a plain Qt event
loop (no qt5reactor -- see that file). A light QTimer poll keeps the panel in
sync with other clients and with the server's DDS lock: while a programmed DDS
sequence holds the lock, the controls are greyed out and a banner says why
(Stop Sequence releases it). A field you are editing is never overwritten by
the poll. The legacy moving-lattice panel is gone (no ramps on the 2026 DDS).

Run the manager and the Pulser server first (pulser_labrad/README.md), then:

    python dds_control.py

Needs PyQt5 (LabRAD env from LABRADHOST/LABRADPASSWORD/LABRAD_TLS).
"""
import sys

from PyQt5 import QtCore, QtWidgets

try:
    import labrad
    from labrad.units import WithUnit
except Exception:                 # lets the widget be built with a stand-in server
    labrad = None
    WithUnit = None

POLL_MS = 1000
STEPS = [("1 Hz", 1e-6), ("10 Hz", 1e-5), ("100 Hz", 1e-4), ("1 kHz", 1e-3),
         ("10 kHz", 1e-2), ("100 kHz", 0.1), ("1 MHz", 1.0), ("10 MHz", 10.0)]
DEFAULT_STEP = "1 MHz"


def _num(v, unit):
    """A LabRAD Value (or a plain number) -> float in `unit`."""
    try:
        return float(v[unit])
    except Exception:
        return float(v)


def _unit(x, unit):
    return WithUnit(x, unit) if WithUnit is not None else x


def _short_error(e):
    """The useful line of a LabRAD error (drop tracebacks and payload noise)."""
    msg = getattr(e, 'msg', None) or str(e)
    lines = [ln.strip() for ln in str(msg).splitlines()
             if ln.strip() and not ln.strip().startswith('[payload')]
    return lines[-1] if lines else str(e)


class DDSChannelCard(QtWidgets.QGroupBox):
    """Frequency / step / power / RF for one channel."""

    def __init__(self, panel, name, freq_range, amp_range):
        super().__init__(name)
        self.panel, self.name = panel, name
        grid = QtWidgets.QGridLayout(self)
        grid.setHorizontalSpacing(10)
        for col, text in enumerate(("Frequency (MHz)", "Step", "Power (dBm)", "", "")):
            lab = QtWidgets.QLabel(text)
            lab.setObjectName('hint')
            grid.addWidget(lab, 0, col)

        self.freq = QtWidgets.QDoubleSpinBox()
        self.freq.setDecimals(6)                       # 1 Hz
        self.freq.setRange(*freq_range)
        self.freq.setKeyboardTracking(False)
        self.freq.setMinimumWidth(170)
        self.freq.setObjectName('big')
        self.freq.setAccelerated(True)

        self.step = QtWidgets.QComboBox()
        for label, mhz in STEPS:
            self.step.addItem(label, mhz)
        self.step.setCurrentText(DEFAULT_STEP)
        self.step.currentIndexChanged.connect(self._step_changed)
        self._step_changed()

        self.power = QtWidgets.QDoubleSpinBox()
        self.power.setDecimals(2)
        self.power.setSingleStep(0.1)
        self.power.setRange(*amp_range)
        self.power.setKeyboardTracking(False)
        self.power.setMinimumWidth(100)

        self.rf = QtWidgets.QPushButton("OFF")
        self.rf.setObjectName('rf')
        self.rf.setCheckable(True)
        self.rf.setMinimumWidth(64)
        self.rf.setToolTip("RF switch: ON = output enabled")

        grid.addWidget(self.freq, 1, 0)
        grid.addWidget(self.step, 1, 1)
        grid.addWidget(self.power, 1, 2)
        grid.addWidget(self.rf, 1, 3)
        self.ident = QtWidgets.QPushButton("Identify")
        self.ident.setToolTip("Blink this board's D6 LED (amber) for 10 s")
        self.ident.clicked.connect(self._identify)
        grid.addWidget(self.ident, 1, 4)

        self.freq.valueChanged.connect(self._freq_changed)
        self.power.valueChanged.connect(self._power_changed)
        self.rf.toggled.connect(self._rf_toggled)

    # ---- user actions -> server (blocking) ---------------------------------
    def _step_changed(self, *_):
        self.freq.setSingleStep(self.step.currentData())

    def _freq_changed(self, mhz):
        self.panel.call(self, lambda p: p.frequency(self.name, _unit(mhz, 'MHz')))

    def _power_changed(self, dbm):
        self.panel.call(self, lambda p: p.amplitude(self.name, _unit(dbm, 'dBm')))

    def _identify(self, *_):
        self.panel.call(self, lambda p: p.identify_dds(self.name, 10))

    def _rf_toggled(self, on):
        self.rf.setText("ON" if on else "OFF")
        self.panel.call(self, lambda p: p.output(self.name, bool(on)))

    # ---- server -> widgets (no signals back) --------------------------------
    def show_state(self, mhz, dbm, on, force=False):
        for w, v in ((self.freq, mhz), (self.power, dbm)):
            if force or not w.hasFocus():              # never clobber an edit in progress
                if abs(w.value() - v) > 1e-9:
                    w.blockSignals(True)
                    w.setValue(v)
                    w.blockSignals(False)
        if self.rf.isChecked() != on:
            self.rf.blockSignals(True)
            self.rf.setChecked(on)
            self.rf.blockSignals(False)
        self.rf.setText("ON" if on else "OFF")

    def set_locked(self, locked):
        for w in (self.freq, self.power, self.rf):
            w.setEnabled(not locked)


class DDSWidget(QtWidgets.QFrame):
    """All DDS channels of the Pulser, as one panel."""

    def __init__(self, parent=None, cxn=None, server=None):
        super().__init__(parent)
        self.setObjectName('Root')
        self.cards = {}
        self.locked = None
        self._owns_cxn = cxn is None and server is None
        try:
            if server is not None:
                self.pulser = server                    # tests / embedding
            else:
                self.cxn = cxn or labrad.connect()
                self.pulser = self.cxn.pulser
            names = list(self.pulser.get_dds_channels())
        except Exception as e:
            self._show_error("Cannot reach the Pulser's DDS settings:\n%s" % _short_error(e))
            return
        if not names:
            self._show_error("The Pulser has no DDS channels (pulser3/hwconfig.py DDS_CHANNELS).")
            return
        self._build_ui(names)
        self.refresh(force=True)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(POLL_MS)

    # ---- UI -----------------------------------------------------------------
    def _show_error(self, msg):
        lay = QtWidgets.QVBoxLayout(self)
        lab = QtWidgets.QLabel(msg)
        lab.setWordWrap(True)
        lay.addWidget(lab)

    def _build_ui(self, names):
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        self.banner = QtWidgets.QLabel(
            "DDS locked: a programmed sequence uses the DDS. Stop the sequence to "
            "change the manual settings.")
        self.banner.setObjectName('lockbanner')
        self.banner.setWordWrap(True)
        self.banner.hide()
        lay.addWidget(self.banner)
        for name in names:
            fr = tuple(float(x) for x in self.pulser.get_dds_frequency_range(name))
            ar = tuple(float(x) for x in self.pulser.get_dds_amplitude_range(name))
            card = DDSChannelCard(self, name, fr, ar)
            self.cards[name] = card
            lay.addWidget(card)
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName('error')
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        lay.addStretch(1)
        self.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding,
                           QtWidgets.QSizePolicy.Minimum)

    # ---- server access --------------------------------------------------------
    def call(self, card, fn):
        """Run one setter; on failure show why and put the card back to the
        server's values."""
        try:
            fn(self.pulser)
            self.status.setText("")
        except Exception as e:
            self.status.setText("%s: %s" % (card.name, _short_error(e)))
        self._read_card(card, force=True)

    def _read_card(self, card, force=False):
        p = self.pulser
        try:
            mhz = _num(p.frequency(card.name), 'MHz')
            dbm = _num(p.amplitude(card.name), 'dBm')
            on = bool(p.output(card.name))
        except Exception:
            return False
        card.show_state(mhz, dbm, on, force=force)
        return True

    def refresh(self, force=False):
        """Poll: lock state + every channel's manual state."""
        try:
            locked = bool(self.pulser.get_dds_lock())
        except Exception:
            locked = False                           # older server: no lock query
        if locked != self.locked:
            self.locked = locked
            self.banner.setVisible(locked)
            for card in self.cards.values():
                card.set_locked(locked)
        for card in self.cards.values():
            if not self._read_card(card, force=force):
                return                               # server hiccup; next tick

    def closeEvent(self, ev):
        if getattr(self, 'timer', None):
            self.timer.stop()
        if self._owns_cxn and getattr(self, 'cxn', None) is not None:
            try:
                self.cxn.disconnect()
            except Exception:
                pass
        ev.accept()


# dashboard.py discovers panels by this manifest
DASHBOARD_PANEL = {'title': 'DDS Control', 'widget': DDSWidget}


def main():
    app = QtWidgets.QApplication(sys.argv)
    try:
        import theme
        theme.apply(app)
    except Exception:
        pass
    w = DDSWidget()
    w.setWindowTitle('Pulser DDS Control')
    w.resize(620, 10)
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
