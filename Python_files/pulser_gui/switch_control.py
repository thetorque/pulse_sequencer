"""
switch_control.py -- PyQt5 Switch Control GUI for the Pulser's TTL channels.

Python-3 / PyQt5 port of the legacy clients/SWITCH_CONTROL.py (py2 / PyQt4).
Each switchable channel gets an ON / OFF / Auto button group: ON/OFF force the
TTL output via the manual override, Auto returns it to sequence control.

This uses pylabrad's *blocking* client and a plain Qt event loop -- NOT the
Twisted/qt5reactor integration the legacy client used. qt5reactor conflicts
with modern PyQt5 on Windows (floods "QCoreApplication::exec: The event loop is
already running"), and a switch panel is a single-operator tool that doesn't
need the async machinery: button clicks call the server directly, and a light
QTimer poll of Get State keeps the buttons in sync when another client (or a
running sequence's Auto channels) changes something -- the same effect the
legacy 'switch toggled' signal gave, without the reactor.

Only channels wired for hardware override (number < 12) are shown -- the 2026
logic_out mux (photon.vhd) overrides channels 0..11; higher channels are a
straight passthrough, so forcing them would be a no-op.

Run the manager and the Pulser server first (see pulser_labrad/README.md), then:

    python switch_control.py

Needs PyQt5 (LabRAD env from LABRADHOST/LABRADPASSWORD/LABRAD_TLS):

    pip install PyQt5
"""
import sys

from PyQt5 import QtWidgets, QtCore

import labrad

SWITCHABLE_BELOW = 12    # hardware override is wired for channel numbers 0..11
POLL_MS = 500            # how often to re-read switch state for cross-client sync


class SwitchWidget(QtWidgets.QFrame):
    def __init__(self, parent=None):
        super(SwitchWidget, self).__init__(parent)
        self.d = {}                       # name -> {'ON','OFF','AUTO': QPushButton}
        self.setFrameStyle(QtWidgets.QFrame.Panel | QtWidgets.QFrame.Sunken)
        try:
            self.cxn = labrad.connect()   # env: LABRADHOST/LABRADPASSWORD/LABRAD_TLS
            self.pulser = self.cxn.pulser
        except Exception as e:
            self._show_error("Cannot reach LabRAD / Pulser:\n%s" % e)
            return
        try:
            channels = self._switchable_channels()
        except Exception as e:
            self._show_error("Pulser not available:\n%s" % e)
            return
        if not channels:
            self._show_error("No switchable channels (numbers 0..%d) in the "
                             "channel map." % (SWITCHABLE_BELOW - 1))
            return
        self._build_ui(channels)
        # poll for external changes (other clients, Auto channels in a sequence)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh_states)
        self.timer.start(POLL_MS)

    # ---- LabRAD helpers ----------------------------------------------------
    def _switchable_channels(self):
        """Channel names whose hardware number is overridable (< 12), in order."""
        chans = self.pulser.get_channels()          # [(name, number), ...]
        switchable = [(name, int(number)) for name, number in chans
                      if int(number) < SWITCHABLE_BELOW]
        switchable.sort(key=lambda nn: (nn[1], nn[0]))
        return [name for name, _ in switchable]

    def _get_state(self, name):
        """(ismanual, manualstate) for a channel."""
        ismanual, manstate, _maninv, _autoinv = self.pulser.get_state(name)
        return bool(ismanual), bool(manstate)

    # ---- UI ----------------------------------------------------------------
    def _show_error(self, msg):
        layout = QtWidgets.QVBoxLayout()
        label = QtWidgets.QLabel(msg)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.setLayout(layout)

    def _build_ui(self, channels):
        layout = QtWidgets.QGridLayout()
        self.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding,
                           QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(QtWidgets.QLabel('Switches'), 0, 0)
        for order, name in enumerate(channels):
            groupBox = QtWidgets.QGroupBox(name)
            groupBoxLayout = QtWidgets.QVBoxLayout()
            buttonOn = QtWidgets.QPushButton('ON')
            buttonOff = QtWidgets.QPushButton('OFF')
            buttonAuto = QtWidgets.QPushButton('Auto')
            for b in (buttonOn, buttonOff, buttonAuto):
                b.setCheckable(True)
                b.setAutoExclusive(True)
                groupBoxLayout.addWidget(b)
            groupBox.setLayout(groupBoxLayout)
            self.d[name] = {'ON': buttonOn, 'OFF': buttonOff, 'AUTO': buttonAuto}
            buttonOn.clicked.connect(self._make_manual(name, True))
            buttonOff.clicked.connect(self._make_manual(name, False))
            buttonAuto.clicked.connect(self._make_auto(name))
            layout.addWidget(groupBox, 0, 1 + order)
        self.setLayout(layout)
        self.refresh_states()

    def _set_checked_silently(self, button):
        button.blockSignals(True)
        button.setChecked(True)
        button.blockSignals(False)

    def refresh_states(self):
        """Re-read every channel's state and reflect it on the buttons."""
        for name, buttons in self.d.items():
            try:
                ismanual, manstate = self._get_state(name)
            except Exception:
                return                       # server hiccup; try again next tick
            if not ismanual:
                self._set_checked_silently(buttons['AUTO'])
            elif manstate:
                self._set_checked_silently(buttons['ON'])
            else:
                self._set_checked_silently(buttons['OFF'])

    # ---- button actions (blocking LabRAD calls) ----------------------------
    def _make_manual(self, name, level):
        def func(_checked):
            try:
                self.pulser.switch_manual(name, level)
            except Exception as e:
                print("switch_manual(%s, %s) failed: %s" % (name, level, e))
        return func

    def _make_auto(self, name):
        def func(_checked):
            try:
                self.pulser.switch_auto(name)
            except Exception as e:
                print("switch_auto(%s) failed: %s" % (name, e))
        return func


def main():
    app = QtWidgets.QApplication(sys.argv)
    widget = SwitchWidget()
    widget.setWindowTitle('Pulser Switch Control')
    widget.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
