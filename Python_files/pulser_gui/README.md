# pulser_gui -- PyQt5 clients for the Pulser LabRAD server

Python-3 / **PyQt5** port of the legacy `clients/` GUIs (which were py2 /
PyQt4). These talk to the `Pulser` LabRAD server (`../pulser_labrad/`) over the
modern scalabrad manager -- the same stack the headless clients use, just with
a Qt front end.

```
Qt GUI (PyQt5)  ──LabRAD (blocking client)──►  Pulser server  ──►  pulser3  ──►  XEM7305
```

`switch_control.py` uses pylabrad's **blocking** client and a plain Qt event
loop -- not the Twisted/`qt5reactor` integration the legacy client used.
`qt5reactor` conflicts with modern PyQt5 on Windows (it floods
`QCoreApplication::exec: The event loop is already running` and the window comes
up empty). A switch panel is a single-operator tool that doesn't need the async
machinery: button clicks call the server directly, and a light `QTimer` poll of
`Get State` keeps the buttons in sync when another client -- or a running
sequence's Auto channels -- changes something (the same effect the legacy
*switch toggled* signal gave, without the reactor).

## Files

| file | role |
|---|---|
| `switch_control.py` | ON / OFF / Auto buttons for the switchable TTL channels (blocking client) |
| `pmt_control.py` | control panel for NormalPMTFlow: mode (Normal/Differential), collection window, record on/off, live count |
| `script_scanner_gui.py` | operator view for ScriptScanner: launch (run/repeat/scan/schedule) + live queue / running (progress + pause/stop) / scheduled |
| `theme.py` | shared modern look (Fusion + light QSS); the GUIs call `theme.apply(app)` |
| `connection.py` | shared **async** LabRAD connection -- kept for a future Twisted/async client (not used by the blocking GUIs) |

Both GUIs use the modern theme in `theme.py` (card panels, rounded accent
buttons, blue "selected"/green "recording" states, themed inputs) -- edit that
one file to restyle.

## Setup

Python deps (in addition to the server's `pylabrad`):

```bash
pip install PyQt5
```

Set the same LabRAD env the server and test clients use:

```bash
export LABRADHOST=localhost
export LABRADPASSWORD=<PW>
export LABRAD_TLS=off
```

## Running

Start the manager and the `Pulser` server first (see
`../pulser_labrad/README.md`), then:

```bash
python switch_control.py     # TTL switch panel
python pmt_control.py        # PMT mode / window / record panel (talks to NormalPMTFlow)
python script_scanner_gui.py # launch + monitor experiments (talks to ScriptScanner)
```

`script_scanner_gui.py` needs the **ScriptScanner** server running (see
`../script_scanner/README.md`); scans/repeats also need the Data Vault. The left
panel launches the selected experiment **once**, **repeated** N times (optionally
saving), on a **schedule** (every N seconds, with a priority), or as a
**parameter scan** (type a collection / parameter / units and a min–max–steps
range — e.g. the bundled *PMT Point* scans `Spectrum` / `frequency` / `kHz` into
a lineshape). The right panel polls the server ~2.5×/s and shows the **running**
scripts (status + progress bar, with Pause/Resume and Stop), the **queue**, and
**scheduled** scans, each with a Cancel button. The parameter-editing tree from
the old GUI is left out for now — a dedicated ParameterVault editor can come
later.

`pmt_control.py` needs the NormalPMTFlow server running (which needs Pulser +
Data Vault); it prompts for the LabRAD password if the env credentials don't
work. It shows the counting mode, collection window, a record toggle, the
current dataset, and a live count. The live count is read **non-blockingly**
from the Data Vault (the latest row of the current dataset) -- it deliberately
avoids the blocking Get Next Counts, which can hang in differential mode. For a
full trace, open the dataset in the Live Grapher.

Each channel in `switch_control.py` shows **ON** / **OFF** / **Auto**:

- **ON / OFF** -- force that TTL output high/low via the manual override,
  independent of any running sequence (server `Switch Manual`).
- **Auto** -- return the channel to sequence control (server `Switch Auto`).

Buttons reflect the live state; a twice-a-second poll re-reads `Get State`, so
changes made by another client (or by a running sequence on Auto channels) show
up within ~0.5 s.

### Which channels appear

Only channels wired for hardware override (**number < 12**) are shown -- the
2026 `logic_out` mux (`photon.vhd`) overrides channels 0..11; channels 12/13
are DDS bits, 14/15 are unused, and 16..31 pass the sequence straight through.
Channel names/numbers come from the server's `Get Channels`; edit
`pulser3/hwconfig.py` to rename or renumber them.

## Notes / expected rough edges

- If the GUI can't reach the manager/server it shows the error in the window
  instead of a button grid -- check the LabRAD env and that both are running.
- `DDS_CONTROL` and the `qtui/` designer forms are not ported yet (DDS is
  hardware-blocked).
