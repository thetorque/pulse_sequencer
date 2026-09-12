# grapher -- live Data Vault plotter (pyqtgraph)

Browse the LabRAD Data Vault, pick a dataset, and watch it plot in real time.
The counts NormalPMTFlow writes appear as a scrolling trace, so you can *see* a
measurement as it runs instead of reading HDF5 after the fact.

This is our own small tool -- **pyqtgraph + blocking pylabrad client + a poll
timer** -- rather than a port of the legacy 3600-line py2/PyQt4 `pygrapherlive`.
Same reasoning as the launcher: far less code, no Twisted/qt4reactor, and ours
to extend.

```
live_grapher (PyQt5 + pyqtgraph)  ──LabRAD──►  Data Vault  ──►  HDF5
```

## How it stays live

It opens the chosen dataset in its **own LabRAD context**. A fresh context's
read cursor starts at row 0, so the first `get()` returns the whole history and
each later `get()` returns only the rows added since -- efficient live append,
no re-reading, no reactor. Navigation (`cd`/`dir`) uses a separate context, so
it never disturbs the plot cursor.

## Run

```bash
pip install PyQt5 pyqtgraph
python grapher/live_grapher.py
```

(with the usual `LABRADHOST` / `LABRADPASSWORD` / `LABRAD_TLS` env). Start the
manager + Data Vault first (easiest via the Launcher).

## Use

- The left list shows the current vault directory: 📁 subdirectories,
  📈 datasets. Double-click a folder to enter it, **↑ Up** to go back,
  **Refresh** to re-read.
- Double-click a dataset (or **Open latest** for the newest in the folder) to
  plot it. Every dependent column becomes a curve, labelled from the dataset's
  variables; the X axis is the first independent.
- **Live** keeps it updating (~4 Hz). Uncheck to freeze.

For a live demo: start NormalPMTFlow recording (its `record_data`), then open
its dataset here and watch the ~100 KC/s trace grow.

## Ideas for later (we'll iterate)

- Curve fitting and cursors (what pygrapherlive had).
- Multiple datasets / overlays.
- Auto-follow the newest dataset as NormalPMTFlow opens new ones.
- Export a plot image.
- Fold into the Launcher as a tab.
