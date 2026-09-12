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
| `connection.py` | shared **async** LabRAD connection -- kept for a future Twisted/async client (not used by `switch_control.py`) |

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
python switch_control.py
```

Each channel shows **ON** / **OFF** / **Auto**:

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
