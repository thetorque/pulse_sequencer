"""
manager_monitor.py -- a small PyQt5 "what's connected" panel for the LabRAD
(scalabrad) manager.

scalabrad is headless, so this is our lightweight stand-in for the old Delphi
manager GUI: a live table of the servers currently registered with the manager,
plus a running log of connect / disconnect events. Our own tool, easy to extend
(per-server settings drill-down, registry browser, etc. can be added later).

Same approach as the other GUIs here (pulser_gui): pylabrad's *blocking* client
and a plain Qt event loop -- no Twisted/qt5reactor. It polls the manager on a
timer (the manager's `servers()` call is exactly what pylabrad uses internally
to list servers), which is simpler and more robust than subscribing to the
Server Connect/Disconnect signals, and plenty responsive for a status panel.

Run the scalabrad manager first (see pulser_labrad/README.md), then:

    python manager_monitor.py

Needs PyQt5 (LabRAD env from LABRADHOST/LABRADPASSWORD/LABRAD_TLS):

    pip install PyQt5
"""
import os
import sys
import time

from PyQt5 import QtWidgets, QtCore, QtGui

import labrad

POLL_MS = 2000    # how often to re-poll the manager for the server list


class ManagerMonitor(QtWidgets.QWidget):
    def __init__(self):
        super(ManagerMonitor, self).__init__()
        self.setWindowTitle('LabRAD Manager Monitor')
        self.resize(560, 520)
        self._prev = {}                       # id -> name from the last poll
        self._host = os.environ.get('LABRADHOST', 'localhost')

        try:
            self.cxn = labrad.connect()       # env: LABRADHOST/LABRADPASSWORD/LABRAD_TLS
        except Exception as e:
            self._build_error("Cannot reach the LabRAD manager:\n%s" % e)
            return

        self._build_ui()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(POLL_MS)
        self.refresh()

    # ---- UI -----------------------------------------------------------------
    def _build_error(self, msg):
        layout = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(msg)
        label.setWordWrap(True)
        layout.addWidget(label)

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # header: status + controls
        top = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("connecting...")
        self.status.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        top.addWidget(self.status, 1)
        self.auto = QtWidgets.QCheckBox("Auto")
        self.auto.setChecked(True)
        self.auto.toggled.connect(self._toggle_auto)
        top.addWidget(self.auto)
        refresh = QtWidgets.QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        top.addWidget(refresh)
        layout.addLayout(top)

        # split: server table over the event log
        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)

        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["ID", "Server"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemDoubleClicked.connect(self._copy_name)
        splitter.addWidget(self.table)

        logbox = QtWidgets.QWidget()
        logl = QtWidgets.QVBoxLayout(logbox)
        logl.setContentsMargins(0, 0, 0, 0)
        logl.addWidget(QtWidgets.QLabel("Events"))
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        logl.addWidget(self.log)
        splitter.addWidget(logbox)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

    def _toggle_auto(self, on):
        if on:
            self.timer.start(POLL_MS)
        else:
            self.timer.stop()

    def _copy_name(self, item):
        name = self.table.item(item.row(), 1).text()
        QtWidgets.QApplication.clipboard().setText(name)
        self._set_status(self.status.text().split('  |  copied')[0] +
                         "  |  copied '%s'" % name)

    # ---- polling ------------------------------------------------------------
    def _log(self, msg):
        self.log.appendPlainText("%s  %s" % (time.strftime("%H:%M:%S"), msg))

    def _set_status(self, text):
        self.status.setText(text)

    def refresh(self):
        try:
            servers = self.cxn.manager.servers()      # [(id, name), ...]
        except Exception as e:
            self._set_status("manager error: %s" % e)
            return

        current = {int(sid): str(name) for sid, name in servers}

        # log connects / disconnects vs the previous poll
        for sid, name in sorted(current.items()):
            if sid not in self._prev:
                self._log("+ connected:    %s (id %d)" % (name, sid))
        for sid, name in sorted(self._prev.items()):
            if sid not in current:
                self._log("- disconnected: %s (id %d)" % (name, sid))

        self._populate(current)
        self._prev = current
        self._set_status("Manager @ %s  |  %d servers  |  updated %s"
                         % (self._host, len(current), time.strftime("%H:%M:%S")))

    def _populate(self, current):
        # preserve the selected server across the rebuild
        selected = None
        row = self.table.currentRow()
        if row >= 0 and self.table.item(row, 1):
            selected = self.table.item(row, 1).text()

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for sid, name in sorted(current.items(), key=lambda kv: kv[1].lower()):
            r = self.table.rowCount()
            self.table.insertRow(r)
            id_item = QtWidgets.QTableWidgetItem()
            id_item.setData(QtCore.Qt.DisplayRole, sid)     # numeric sort
            self.table.setItem(r, 0, id_item)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(name))
            if selected is not None and name == selected:
                self.table.selectRow(r)
        self.table.setSortingEnabled(True)


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = ManagerMonitor()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
