"""
workbench.py -- Script Scanner + Sequence Editor + Sequence Viewer in one window.

These three tools are used together (write/preview a sequence, then run it as an
experiment), so this bundles them as tabs of a single GUI sharing ONE LabRAD
connection (one login for the whole window) -- the same connection-sharing the
dashboard does, but as a focused, fixed three-tab layout instead of docks.

  - Script Scanner  -- launch / monitor experiments (needs the manager + server)
  - Parameters      -- edit ParameterVault values (needs the manager + server)
  - Sequence Editor -- build a sequence, preview it live, Program + Run
  - Sequence Viewer -- open and view a sequence .py

The Editor and Viewer work with no hardware, so if the manager isn't up (or you
cancel the login) the window still opens for those two; the Script Scanner tab
then shows a short note instead.

The standalone GUIs (script_scanner_gui.py / seq_viewer / seq_editor) and their
dashboard panels are unchanged -- this is just an additional launcher.

    pip install PyQt5 pyqtgraph
    python pulser_gui/workbench.py
"""
import importlib.util
import os
import sys

from PyQt5 import QtCore, QtWidgets

import labrad

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)                 # Python_files
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _load(mod_name, relpath):
    """Load a module by file path (avoids name clashes with same-named dirs)."""
    path = os.path.join(_ROOT, relpath)
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ScriptScannerGui = _load('wb_script_scanner_gui', 'pulser_gui/script_scanner_gui.py').ScriptScannerGui
ParameterEditor = _load('wb_parameter_editor', 'pulser_gui/parameter_editor.py').ParameterEditor
SeqEditor = _load('wb_seq_editor', 'seq_viewer/seq_editor.py').SeqEditor
SeqViewer = _load('wb_seq_viewer', 'seq_viewer/seq_viewer.py').SeqViewer


class Workbench(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName('Root')
        self.setWindowTitle('Experiment Workbench')
        self.resize(1040, 660)
        # one shared connection for the whole window (env, then a single prompt);
        # None if the manager isn't reachable / the user cancels -> offline tabs
        self.cxn = self._connect() or self._login_loop()

        tabs = QtWidgets.QTabWidget()
        if self.cxn is not None:
            tabs.addTab(ScriptScannerGui(cxn=self.cxn), "Script Scanner")
            tabs.addTab(ParameterEditor(cxn=self.cxn), "Parameters")
        else:
            note = QtWidgets.QLabel(
                "Not connected to LabRAD.\n\nStart the manager and the ScriptScanner "
                "server, then reopen the Workbench to use this tab.\n\n"
                "(The Sequence Editor and Viewer work without a connection.)")
            note.setAlignment(QtCore.Qt.AlignCenter)
            note.setWordWrap(True)
            tabs.addTab(note, "Script Scanner")
        tabs.addTab(SeqEditor(cxn=self.cxn), "Sequence Editor")
        tabs.addTab(SeqViewer(cxn=self.cxn), "Sequence Viewer")

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(tabs)

    # ---- connection (shared; env then prompt) -----------------------------
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
                return None                 # cancel -> open offline
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

    def closeEvent(self, ev):
        try:
            if self.cxn is not None:
                self.cxn.disconnect()
        except Exception:
            pass
        ev.accept()


def main():
    app = QtWidgets.QApplication(sys.argv)
    try:
        import theme
        theme.apply(app)
    except Exception:
        pass
    w = Workbench()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
