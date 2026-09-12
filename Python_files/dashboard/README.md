# dashboard -- dockable panel host for the LabRAD client GUIs

The client-side companion to the launcher. Where the **launcher** manages server
*processes*, the **dashboard** hosts the client *GUIs* in one window: add any of
them as a dockable panel and arrange them however you like -- drag to an edge,
tab them together, float one off, resize -- and the layout is saved and restored.

```
dashboard (QMainWindow + docks)
  ├─ Switch Control   (panel)
  ├─ PMT Control      (panel)     ── all sharing ONE LabRAD connection
  └─ Live Grapher     (panel)
```

## How it finds panels

Any GUI module that declares a module-level manifest shows up in the **Panels**
menu automatically:

```python
DASHBOARD_PANEL = {'title': 'Switch Control', 'widget': SwitchWidget}
```

The dashboard scans `Python_files` (skipping the legacy trees), imports the
modules that declare it, and lists them. A new GUI joins the dashboard just by
adding that one line + accepting an optional `cxn=None` in its widget `__init__`.

## One connection, one login

The dashboard connects to LabRAD **once** (using the env credentials, or a
password prompt if those don't work) and passes that connection to every panel
as `widget(cxn=shared_cxn)`. So you get a single login and a single connection
for the whole window instead of one per GUI. All panels run on the Qt main
thread, so they share the one blocking connection safely.

## Run

```bash
pip install PyQt5 pyqtgraph
python dashboard/dashboard.py
```

Start the manager + the servers first (via the launcher). Then **Panels ▸** pick
one to add it; drag it where you want; add more. Close a panel with its dock's ✕
(that stops its polling). Your arrangement and open panels are saved to
`~/.labrad/dashboard_config.json` and restored next time.

- **Panels menu** -- one entry per discovered GUI, plus **Rescan panels** and
  **Close all panels**.
- Layout uses Qt's native `saveState`/`restoreState` (docks matched by name).

## Notes / ideas for later

- Panels get the shared connection; a standalone `python switch_control.py`
  still self-connects (and prompts) as before -- the `cxn` argument is optional.
- Could merge the launcher and dashboard into one "mission control" with tabs.
- Per-panel connection status, a toolbar of quick-add buttons, saved layouts.
