"""
switch_control.py -- PyQt5 Switch Control GUI for the Pulser's TTL channels.

Python-3 / PyQt5 port of the legacy clients/SWITCH_CONTROL.py (py2 / PyQt4).
Each switchable channel gets an ON / OFF / Auto button group: ON/OFF force the
TTL output via the manual override, Auto returns it to sequence control. The
buttons stay in sync across clients via the server's 'switch toggled' signal.

Only channels wired for hardware override (number < 12) are shown -- the 2026
logic_out mux (photon.vhd) overrides channels 0..11; higher channels are a
straight passthrough, so forcing them would be a no-op.

Run the manager and the Pulser server first (see pulser_labrad/README.md), then:

    python switch_control.py

Needs PyQt5 and qt5reactor:  pip install PyQt5 qt5reactor
"""
from PyQt5 import QtWidgets
from twisted.internet.defer import inlineCallbacks, returnValue

from connection import connection

SIGNALID = 378902
SWITCHABLE_BELOW = 12   # hardware override is wired for channel numbers 0..11


class switchWidget(QtWidgets.QFrame):
    def __init__(self, reactor, cxn=None, parent=None):
        super(switchWidget, self).__init__(parent)
        self.initialized = False
        self.reactor = reactor
        self.cxn = cxn
        self.connect()

    @inlineCallbacks
    def connect(self):
        if self.cxn is None:
            self.cxn = connection()
            yield self.cxn.connect()
        from labrad.types import Error
        self.Error = Error
        self.context = yield self.cxn.context()
        try:
            displayed_channels = yield self.get_displayed_channels()
            yield self.initializeGUI(displayed_channels)
            yield self.setupListeners()
        except Exception as e:
            print(e)
            print('SWITCH CONTROL: Pulser not available')
            self.setDisabled(True)
        yield self.cxn.add_on_connect('Pulser', self.reinitialize)
        yield self.cxn.add_on_disconnect('Pulser', self.disable)

    @inlineCallbacks
    def get_displayed_channels(self):
        """Switchable channel names (number < 12), optionally narrowed by the
        registry 'display_channels' list if one is set."""
        server = yield self.cxn.get_server('Pulser')
        all_channels = yield server.get_channels(context=self.context)
        switchable = [name for name, number in all_channels
                      if number < SWITCHABLE_BELOW]
        wanted = yield self.registry_load_displayed(switchable)
        if wanted is None:
            returnValue(switchable)
        returnValue([name for name in wanted if name in switchable])

    @inlineCallbacks
    def registry_load_displayed(self, all_names):
        """Registry-configured subset to show, or None to show all switchable.
        A missing Registry server (or key) just falls back to all."""
        try:
            reg = yield self.cxn.get_server('Registry')
        except Exception:
            returnValue(None)
        yield reg.cd(['Clients', 'Switch Control'], True, context=self.context)
        try:
            displayed = yield reg.get('display_channels', context=self.context)
        except self.Error as e:
            if e.code == 21:                       # key error -> seed and use all
                yield reg.set('display_channels', all_names, context=self.context)
                displayed = None
            else:
                raise
        returnValue(displayed)

    @inlineCallbacks
    def reinitialize(self):
        self.setDisabled(False)
        server = yield self.cxn.get_server('Pulser')
        if self.initialized:
            yield server.signal__switch_toggled(SIGNALID, context=self.context)
            for name in self.d.keys():
                yield self.setStateNoSignals(name, server)
        else:
            displayed_channels = yield self.get_displayed_channels()
            yield self.initializeGUI(displayed_channels)
            yield self.setupListeners()

    @inlineCallbacks
    def initializeGUI(self, channels):
        server = yield self.cxn.get_server('Pulser')
        self.d = {}
        layout = QtWidgets.QGridLayout()
        self.setFrameStyle(QtWidgets.QFrame.Panel | QtWidgets.QFrame.Sunken)
        self.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding,
                           QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(QtWidgets.QLabel('Switches'), 0, 0)
        for order, name in enumerate(channels):
            groupBox = QtWidgets.QGroupBox(name)
            groupBoxLayout = QtWidgets.QVBoxLayout()
            buttonOn = QtWidgets.QPushButton('ON')
            buttonOn.setAutoExclusive(True)
            buttonOn.setCheckable(True)
            buttonOff = QtWidgets.QPushButton('OFF')
            buttonOff.setCheckable(True)
            buttonOff.setAutoExclusive(True)
            buttonAuto = QtWidgets.QPushButton('Auto')
            buttonAuto.setCheckable(True)
            buttonAuto.setAutoExclusive(True)
            groupBoxLayout.addWidget(buttonOn)
            groupBoxLayout.addWidget(buttonOff)
            groupBoxLayout.addWidget(buttonAuto)
            groupBox.setLayout(groupBoxLayout)
            self.d[name] = {'ON': buttonOn, 'OFF': buttonOff, 'AUTO': buttonAuto}
            yield self.setStateNoSignals(name, server)
            buttonOn.clicked.connect(self.buttonConnectionManualOn(name, server))
            buttonOff.clicked.connect(self.buttonConnectionManualOff(name, server))
            buttonAuto.clicked.connect(self.buttonConnectionAuto(name, server))
            layout.addWidget(groupBox, 0, 1 + order)
        self.setLayout(layout)
        self.initialized = True

    @inlineCallbacks
    def setStateNoSignals(self, name, server):
        ismanual, manstate, _maninv, _autoinv = yield server.get_state(
            name, context=self.context)
        if not ismanual:
            button = self.d[name]['AUTO']
        elif manstate:
            button = self.d[name]['ON']
        else:
            button = self.d[name]['OFF']
        button.blockSignals(True)
        button.setChecked(True)
        button.blockSignals(False)

    def buttonConnectionManualOn(self, name, server):
        @inlineCallbacks
        def func(state):
            yield server.switch_manual(name, True, context=self.context)
        return func

    def buttonConnectionManualOff(self, name, server):
        @inlineCallbacks
        def func(state):
            yield server.switch_manual(name, False, context=self.context)
        return func

    def buttonConnectionAuto(self, name, server):
        @inlineCallbacks
        def func(state):
            yield server.switch_auto(name, context=self.context)
        return func

    @inlineCallbacks
    def setupListeners(self):
        server = yield self.cxn.get_server('Pulser')
        yield server.signal__switch_toggled(SIGNALID, context=self.context)
        yield server.addListener(listener=self.followSignal, source=None,
                                 ID=SIGNALID, context=self.context)

    def followSignal(self, x, data):
        switchName, state = data
        if switchName not in self.d.keys():
            return None
        if state == 'Auto':
            button = self.d[switchName]['AUTO']
        elif state == 'ManualOn':
            button = self.d[switchName]['ON']
        elif state == 'ManualOff':
            button = self.d[switchName]['OFF']
        else:
            return None
        button.blockSignals(True)
        button.setChecked(True)
        button.blockSignals(False)

    def closeEvent(self, x):
        self.reactor.stop()

    @inlineCallbacks
    def disable(self):
        self.setDisabled(True)
        yield None


if __name__ == "__main__":
    a = QtWidgets.QApplication([])
    import qt5reactor
    qt5reactor.install()
    from twisted.internet import reactor
    widget = switchWidget(reactor)
    widget.setWindowTitle('Pulser Switch Control')
    widget.show()
    reactor.run()
