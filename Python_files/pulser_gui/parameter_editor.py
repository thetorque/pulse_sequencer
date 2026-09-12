"""
parameter_editor.py -- PyQt5 editor for the ParameterVault.

Browse collections and parameters and edit their values, then Apply (write back to
the vault) and optionally Save to registry (persist across restarts). This is the
GUI the experiment layer needed: instead of a Set-Parameter one-liner, tweak
LedBlink.on_time (or any parameter) and re-run.

Handles the common typed values -- parameter / duration_bandwidth (numeric with a
range + units), string, bool, selection (simple / line), and scan (start / stop /
steps). Other, rarer types are shown read-only.

Blocking pylabrad client + a manual Refresh (no poll, so it never overwrites an
edit in progress). Needs PyQt5; LabRAD env from LABRADHOST/LABRADPASSWORD/
LABRAD_TLS, prompting if those don't work.

    pip install PyQt5
    python parameter_editor.py
"""
import os
import sys

from PyQt5 import QtCore, QtWidgets

import labrad
from labrad.units import WithUnit


def _is_value(x):
    return hasattr(x, 'units')


def _mag(x):
    """Magnitude of a labrad Value or a plain number."""
    try:
        return float(x)
    except (TypeError, ValueError):
        try:
            return float(x[x.units])
        except Exception:
            return 0.0


def _unit(x):
    return getattr(x, 'units', None) if _is_value(x) else None


def _mk(mag, unit):
    return WithUnit(float(mag), unit) if unit else float(mag)


class ParameterEditor(QtWidgets.QWidget):
    def __init__(self, parent=None, cxn=None):
        super().__init__(parent)
        self.setObjectName('Root')
        self.setWindowTitle('Parameter Editor')
        self.resize(640, 480)
        self.pv = None
        self._rows = {}                   # name -> {'get': callable or None}
        self._current = None              # current collection
        self._owns_cxn = cxn is None
        self.cxn = cxn or self._connect() or self._login_loop()
        self._build_ui()
        if self.cxn is not None:
            try:
                self.pv = self.cxn.parametervault
            except Exception as e:
                self._fatal("ParameterVault not available:\n%s" % e)
                return
            self._load_collections()

    # ---- connection -------------------------------------------------------
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

    # ---- helpers ----------------------------------------------------------
    def _fatal(self, msg):
        lay = self.layout() or QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(msg)
        label.setWordWrap(True)
        lay.addWidget(label)

    def _warn(self, title, e):
        s = str(e).strip()
        QtWidgets.QMessageBox.warning(self, title, s.splitlines()[-1] if s else e.__class__.__name__)

    # ---- UI ---------------------------------------------------------------
    def _build_ui(self):
        outer = QtWidgets.QHBoxLayout(self)
        if self.cxn is None:
            msg = "Cannot reach LabRAD"
            if hasattr(self, '_err'):
                msg += ":\n%s" % self._err
            outer.addWidget(QtWidgets.QLabel(msg))
            return

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

        left = QtWidgets.QWidget()
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QtWidgets.QLabel("Collections"))
        self.collection_list = QtWidgets.QListWidget()
        self.collection_list.currentTextChanged.connect(self._load_collection)
        lv.addWidget(self.collection_list)
        refresh = QtWidgets.QPushButton("Refresh")
        refresh.clicked.connect(self._refresh)
        lv.addWidget(refresh)
        add_btn = QtWidgets.QPushButton("Add parameter…")
        add_btn.clicked.connect(self._add_parameter)
        lv.addWidget(add_btn)
        splitter.addWidget(left)

        right = QtWidgets.QWidget()
        rv = QtWidgets.QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.form_host = QtWidgets.QWidget()
        self.form = QtWidgets.QFormLayout(self.form_host)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.form_host)
        rv.addWidget(scroll, 1)
        btns = QtWidgets.QHBoxLayout()
        self.apply_btn = QtWidgets.QPushButton("Apply")
        self.apply_btn.setObjectName('primary')
        self.apply_btn.clicked.connect(self._apply)
        self.save_btn = QtWidgets.QPushButton("Save to registry")
        self.save_btn.clicked.connect(self._save)
        btns.addWidget(self.apply_btn)
        btns.addWidget(self.save_btn)
        btns.addStretch(1)
        rv.addLayout(btns)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter)

    # ---- load -------------------------------------------------------------
    def _load_collections(self):
        try:
            collections = sorted(self.pv.get_collections())
        except Exception as e:
            self._fatal("Could not list collections:\n%s" % e)
            return
        self.collection_list.clear()
        self.collection_list.addItems(collections)
        if collections:
            self.collection_list.setCurrentRow(0)

    def _refresh(self):
        self._load_collections()

    def _clear_form(self):
        while self.form.rowCount():
            self.form.removeRow(0)
        self._rows = {}

    def _load_collection(self, collection):
        self._current = collection
        self._clear_form()
        if not collection:
            return
        try:
            names = sorted(self.pv.get_parameter_names(collection))
        except Exception as e:
            self._warn("Load failed", e)
            return
        for name in names:
            try:
                record = self.pv.get_parameter(collection, name, False)   # full typed record
                widget, getter = self._make_editor(record)
            except Exception as e:
                widget = QtWidgets.QLabel("(error: %s)" % e)
                getter = None
            # editor + a small delete button per row
            row = QtWidgets.QWidget()
            h = QtWidgets.QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            h.addWidget(widget, 1)
            del_btn = QtWidgets.QToolButton()
            del_btn.setText("✕")
            del_btn.setToolTip("Delete %s" % name)
            del_btn.clicked.connect(lambda _=False, n=name: self._delete_parameter(n))
            h.addWidget(del_btn)
            self.form.addRow(name, row)
            self._rows[name] = {'get': getter}

    # ---- per-type editors -------------------------------------------------
    def _make_editor(self, record):
        """Return (widget, getter). getter() -> the full record to write back,
        or None for read-only types."""
        kind = record[0]
        item = record[1]

        if kind in ('parameter', 'duration_bandwidth'):
            lo, hi, cur = item[0], item[1], item[2]
            unit = _unit(cur) or _unit(lo)
            spin = QtWidgets.QDoubleSpinBox()
            spin.setDecimals(6)
            spin.setRange(_mag(lo), _mag(hi))
            spin.setValue(_mag(cur))
            if unit:
                spin.setSuffix(" " + unit)
            spin.setToolTip("range %.4g .. %.4g%s" % (_mag(lo), _mag(hi), (" " + unit) if unit else ""))
            return spin, (lambda: (kind, [lo, hi, _mk(spin.value(), unit)]))

        if kind == 'string':
            edit = QtWidgets.QLineEdit(str(item))
            return edit, (lambda: ('string', str(edit.text())))

        if kind == 'bool':
            box = QtWidgets.QCheckBox()
            box.setChecked(bool(item))
            return box, (lambda: ('bool', bool(box.isChecked())))

        if kind == 'selection_simple':
            selected, options = item[0], list(item[1])
            combo = QtWidgets.QComboBox()
            combo.addItems([str(o) for o in options])
            if str(selected) in [str(o) for o in options]:
                combo.setCurrentText(str(selected))
            return combo, (lambda: ('selection_simple', (str(combo.currentText()), options)))

        if kind == 'line_selection':
            selected, mapping = item[0], list(item[1])
            labels = [str(pair[0]) for pair in mapping]
            combo = QtWidgets.QComboBox()
            combo.addItems(labels)
            if str(selected) in labels:
                combo.setCurrentText(str(selected))
            return combo, (lambda: ('line_selection', (str(combo.currentText()), mapping)))

        if kind == 'scan':
            (lo, hi), (start, stop, steps) = item[0], item[1]
            unit = _unit(start) or _unit(lo)
            start_sp = QtWidgets.QDoubleSpinBox(); start_sp.setDecimals(6)
            stop_sp = QtWidgets.QDoubleSpinBox(); stop_sp.setDecimals(6)
            for sp, val in ((start_sp, start), (stop_sp, stop)):
                sp.setRange(_mag(lo), _mag(hi))
                sp.setValue(_mag(val))
                if unit:
                    sp.setSuffix(" " + unit)
            steps_sp = QtWidgets.QSpinBox(); steps_sp.setRange(1, 1000000); steps_sp.setValue(int(_mag(steps)))
            row = QtWidgets.QWidget()
            h = QtWidgets.QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(start_sp); h.addWidget(QtWidgets.QLabel("to")); h.addWidget(stop_sp)
            h.addWidget(QtWidgets.QLabel("in")); h.addWidget(steps_sp); h.addWidget(QtWidgets.QLabel("steps"))
            return row, (lambda: ('scan', ((lo, hi),
                                           (_mk(start_sp.value(), unit), _mk(stop_sp.value(), unit),
                                            int(steps_sp.value())))))

        # unknown / complex type -> read-only
        label = QtWidgets.QLabel("%s: %s" % (kind, item))
        label.setWordWrap(True)
        label.setStyleSheet("color:#667085;")
        return label, None

    # ---- write ------------------------------------------------------------
    def _apply(self):
        if not self._current:
            return
        errors = []
        for name, info in self._rows.items():
            getter = info['get']
            if getter is None:
                continue
            try:
                value = getter()
                self.pv.set_parameter(self._current, name, value, True)   # full record
            except Exception as e:
                errors.append("%s: %s" % (name, str(e).splitlines()[-1]))
        if errors:
            QtWidgets.QMessageBox.warning(self, "Some parameters not saved", "\n".join(errors))
        else:
            self.apply_btn.setText("Applied ✓")
            QtCore.QTimer.singleShot(1200, lambda: self.apply_btn.setText("Apply"))

    # ---- add a new parameter ---------------------------------------------
    def _add_parameter(self):
        result = self._prompt_add_parameter()
        if result is None:
            return
        collection, name, record = result
        # new parameters can't be created via Set Parameter; write the typed
        # record into the registry and reload the vault
        try:
            existing = list(self.pv.get_collections())
            if collection in existing and name in list(self.pv.get_parameter_names(collection)):
                if QtWidgets.QMessageBox.question(
                        self, "Overwrite?",
                        "%s / %s already exists. Overwrite it?" % (collection, name)
                ) != QtWidgets.QMessageBox.Yes:
                    return
            # reload (below) reverts in-memory values to the registry, so persist
            # current values first -- otherwise Applied-but-unsaved edits are lost
            self.pv.save_parameters_to_registry()
            reg = self.cxn.registry
            reg.cd(['', 'Servers', 'Parameter Vault', collection], True)
            reg.set(name, record)
            self.pv.reload_parameters()
        except Exception as e:
            self._warn("Add failed", e)
            return
        # show it: (re)load collections, select this one
        self._load_collections()
        items = self.collection_list.findItems(collection, QtCore.Qt.MatchExactly)
        if items:
            self.collection_list.setCurrentItem(items[0])

    def _prompt_add_parameter(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Add parameter")
        form = QtWidgets.QFormLayout(dlg)

        coll_combo = QtWidgets.QComboBox()
        coll_combo.setEditable(True)
        try:
            coll_combo.addItems(sorted(self.pv.get_collections()))
        except Exception:
            pass
        if self._current:
            coll_combo.setCurrentText(self._current)
        form.addRow("Collection", coll_combo)

        name_edit = QtWidgets.QLineEdit()
        form.addRow("Name", name_edit)

        type_combo = QtWidgets.QComboBox()
        type_combo.addItems(['parameter', 'string', 'bool', 'selection_simple'])
        form.addRow("Type", type_combo)

        # type-specific fields in a stack
        stack = QtWidgets.QStackedWidget()

        # parameter: min / max / current / unit
        pw = QtWidgets.QWidget(); pf = QtWidgets.QFormLayout(pw)
        min_sp = QtWidgets.QDoubleSpinBox(); min_sp.setDecimals(6); min_sp.setRange(-1e12, 1e12); min_sp.setValue(0.0)
        max_sp = QtWidgets.QDoubleSpinBox(); max_sp.setDecimals(6); max_sp.setRange(-1e12, 1e12); max_sp.setValue(1.0)
        cur_sp = QtWidgets.QDoubleSpinBox(); cur_sp.setDecimals(6); cur_sp.setRange(-1e12, 1e12); cur_sp.setValue(0.5)
        unit_edit = QtWidgets.QLineEdit(); unit_edit.setPlaceholderText("e.g. s, MHz -- blank = no unit")
        pf.addRow("Min", min_sp); pf.addRow("Max", max_sp); pf.addRow("Current", cur_sp); pf.addRow("Unit", unit_edit)
        stack.addWidget(pw)

        # string
        sw = QtWidgets.QWidget(); sf = QtWidgets.QFormLayout(sw)
        str_edit = QtWidgets.QLineEdit()
        sf.addRow("Value", str_edit)
        stack.addWidget(sw)

        # bool
        bw = QtWidgets.QWidget(); bf = QtWidgets.QFormLayout(bw)
        bool_box = QtWidgets.QCheckBox("true")
        bf.addRow("Value", bool_box)
        stack.addWidget(bw)

        # selection_simple
        selw = QtWidgets.QWidget(); self_f = QtWidgets.QFormLayout(selw)
        opts_edit = QtWidgets.QLineEdit(); opts_edit.setPlaceholderText("comma-separated, e.g. a, b, c")
        self_f.addRow("Options", opts_edit)
        stack.addWidget(selw)

        type_combo.currentIndexChanged.connect(stack.setCurrentIndex)
        form.addRow(stack)

        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)

        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return None

        collection = coll_combo.currentText().strip()
        name = name_edit.text().strip()
        if not collection or not name:
            self._warn("Add failed", ValueError("collection and name are required"))
            return None

        kind = type_combo.currentText()
        if kind == 'parameter':
            unit = unit_edit.text().strip()
            lo, hi, cur = min_sp.value(), max_sp.value(), cur_sp.value()
            if not (lo <= cur <= hi):
                self._warn("Add failed", ValueError("need min <= current <= max"))
                return None
            record = ('parameter', [_mk(lo, unit), _mk(hi, unit), _mk(cur, unit)])
        elif kind == 'string':
            record = ('string', str(str_edit.text()))
        elif kind == 'bool':
            record = ('bool', bool(bool_box.isChecked()))
        else:  # selection_simple
            options = [o.strip() for o in opts_edit.text().split(',') if o.strip()]
            if not options:
                self._warn("Add failed", ValueError("give at least one option"))
                return None
            record = ('selection_simple', (options[0], options))
        return collection, name, record

    # ---- delete a parameter ----------------------------------------------
    def _delete_parameter(self, name):
        if not self._current:
            return
        if QtWidgets.QMessageBox.question(
                self, "Delete parameter",
                "Delete %s / %s?\nThis removes it from the registry." % (self._current, name)
        ) != QtWidgets.QMessageBox.Yes:
            return
        collection = self._current
        removed_collection = False
        try:
            # reload (below) reverts in-memory to the registry, so persist current
            # values first -- keeps Applied-but-unsaved edits on other parameters
            self.pv.save_parameters_to_registry()
            reg = self.cxn.registry
            reg.cd(['', 'Servers', 'Parameter Vault', collection])
            reg.del_(name)
            subdirs, keys = reg.dir()
            if not keys and not subdirs:
                # collection is now empty -- remove the empty directory too
                reg.cd(['', 'Servers', 'Parameter Vault'])
                reg.rmdir(collection)
                removed_collection = True
            self.pv.reload_parameters()
        except Exception as e:
            self._warn("Delete failed", e)
            return
        if removed_collection:
            self._load_collections()
        else:
            self._load_collection(collection)

    def _save(self):
        try:
            self.pv.save_parameters_to_registry()
            self.save_btn.setText("Saved ✓")
            QtCore.QTimer.singleShot(1200, lambda: self.save_btn.setText("Save to registry"))
        except Exception as e:
            self._warn("Save failed", e)

    def closeEvent(self, ev):
        try:
            if self.cxn is not None and self._owns_cxn:
                self.cxn.disconnect()
        except Exception:
            pass
        ev.accept()


# dashboard.py discovers panels by this manifest
DASHBOARD_PANEL = {'title': 'Parameter Editor', 'widget': ParameterEditor}


def main():
    app = QtWidgets.QApplication(sys.argv)
    try:
        import theme
        theme.apply(app)
    except Exception:
        pass
    w = ParameterEditor()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
