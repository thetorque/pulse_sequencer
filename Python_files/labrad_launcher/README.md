# labrad_launcher -- one-window control center for the LabRAD stack

Start the whole system from a single GUI instead of a PowerShell window per
server. The launcher starts the **scalabrad manager**, scans a folder for
**servers**, and starts/stops each one with a button -- all as child processes
whose output is captured in tabs here.

It's **launcher-managed**: the GUI itself spawns and supervises every process
(via Qt's `QProcess`), so there's no LabRAD-node registry config to set up, and
it can start the manager too (which the node can't). Closing the launcher stops
everything it started (after a confirm).

```
Before:  manager | Pulser | ParameterVault | DataVault | ...   (5+ windows)
After:   labrad_launcher                                        (1 window)
```

## Run

```bash
pip install PyQt5
python labrad_launcher/labrad_launcher.py
```

## Use

1. **Manager** -- set the path to your scalabrad `labrad.bat` (Browse…), check
   the registry / password / TLS fields, and click **Start Manager**. It spawns
   the JVM manager; its log appears in the *Manager* tab. (`JAVA_HOME` must be
   set in your environment, as for running `labrad.bat` by hand.)
2. **Servers** -- Browse to a folder (e.g. `Python_files`) and the launcher
   lists every server it finds (any file with a `### NODE INFO` block). Click
   **Start** on a row, or **Start All**. Each server's output gets its own tab.
3. **Environment** -- the key/value table is applied to every server it launches.
   Pre-seeded with `LABRADHOST` / `LABRADPASSWORD` / `LABRAD_TLS` and
   `PULSER_BIT_PATH` (fill that in for the Pulser server). **Save config** to
   remember everything for next time.

Typical flow: **Start Manager** → **Start All** → whole stack up, all logs in
one window, every server a click to stop or restart.

## Notes & knobs

- **Config** is saved to `~/.labrad/launcher_config.json` (manager settings,
  scan folder, environment). Not in the repo.
- **Server discovery** skips this repo's legacy Python-2 trees (`servers/`,
  `clients/`, `old_legacy_code/`) so they don't show up as un-launchable py2
  servers. Edit `EXCLUDE_DIRS` in the script for a different layout.
- **Servers run with the launcher's own Python** (`sys.executable`), so launch
  the launcher with the interpreter that has `pylabrad` / `h5py` installed.
- **Stopping** uses a process-tree kill on Windows (`taskkill /T`), because the
  manager is `cmd -> java` and a plain kill would orphan the JVM.
- **Lifecycle**: servers are children of the launcher, so keep it open to keep
  the stack up; quitting stops everything (with a confirm). A "leave running on
  exit" option can be added later.

## Ideas for later (we'll iterate)

- Per-server environment overrides (not just a shared set).
- Autostart list (bring named servers up when the launcher opens).
- Start ordering / dependency hints.
- Fold in the Manager Monitor's live connected-servers view.
- Optional "detach" so processes survive closing the launcher.
