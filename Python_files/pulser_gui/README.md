# pulser_gui -- PyQt5 clients for the Pulser LabRAD server

Python-3 / **PyQt5** port of the legacy `clients/` GUIs (which were py2 /
PyQt4). These talk to the `Pulser` LabRAD server (`../pulser_labrad/`) over the
modern scalabrad manager -- the same stack the headless clients use, just with
a Qt front end.

```
Qt GUI (PyQt5 + qt5reactor)  ──LabRAD──►  Pulser server  ──►  pulser3  ──►  XEM7305
```

## Files

| file | role |
|---|---|
| `connection.py` | shared async LabRAD connection (server connect/disconnect callbacks) |
| `switch_control.py` | ON / OFF / Auto buttons for the switchable TTL channels |

## Setup

Python deps (in addition to the server's `pylabrad twisted`):

```bash
pip install PyQt5 qt5reactor
```

`qt5reactor` marries Twisted's reactor to the Qt event loop (the PyQt5
equivalent of the legacy `qt4reactor`). Set the same LabRAD env the server and
test clients use:

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

Buttons reflect the live state and stay in sync across multiple clients via the
server's *switch toggled* signal.

### Which channels appear

Only channels wired for hardware override (**number < 12**) are shown -- the
2026 `logic_out` mux (`photon.vhd`) overrides channels 0..11; channels 12/13
are DDS bits, 14/15 are unused, and 16..31 pass the sequence straight through.
Channel names/numbers come from the server's `Get Channels`; edit
`pulser3/hwconfig.py` to rename or renumber them.

If a `Registry` server is running, an optional
`Clients > Switch Control > display_channels` list narrows which switchable
channels are shown; with no Registry (or no key) all switchable channels
appear.

## Notes / expected rough edges

- Written against pylabrad's **py3** async API mirroring the legacy client
  patterns (`connectAsync`, `@inlineCallbacks`, `signal__switch_toggled`). If a
  detail differs, the first run surfaces it -- same write-here / verify-on-the-
  bench rhythm as the rest of the port.
- `DDS_CONTROL` and the `qtui/` designer forms are not ported yet (DDS is
  hardware-blocked).
