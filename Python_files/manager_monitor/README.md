# manager_monitor -- a "what's connected" panel for the scalabrad manager

scalabrad runs headless (console logs only), so unlike the old Delphi manager
there's no at-a-glance view of which servers are up. `manager_monitor.py` is our
lightweight PyQt5 stand-in: a live table of the servers currently registered
with the manager, plus a running log of connect / disconnect events.

It's deliberately small and ours to grow -- per-server settings drill-down, a
registry browser, or a Data Vault grapher can be added later, on our own terms
(the official `scalabrad-web` GUI is 2016 source-only with a dead download
channel, so building our own was the pragmatic call).

```
manager_monitor (PyQt5)  ──LabRAD (blocking client)──►  scalabrad manager
```

## How it works

Same style as the other GUIs here (`pulser_gui`): pylabrad's **blocking**
client and a plain Qt event loop -- no Twisted/`qt5reactor`. It polls the
manager every 2 s via `manager.servers()` (the same call pylabrad uses
internally to enumerate servers) and diffs successive polls to log connects and
disconnects. Polling is simpler and more robust than subscribing to the
`Server Connect` / `Server Disconnect` signals, and 2 s is plenty for a status
panel.

## Running

Start the scalabrad manager first (see `../pulser_labrad/README.md`). Then, with
the LabRAD env set:

```bash
pip install PyQt5
export LABRADHOST=localhost
export LABRADPASSWORD=<PW>
export LABRAD_TLS=off
python manager_monitor.py
```

- **Table** -- every connected server (ID + name), sortable by either column.
  Double-click a row to copy the server name to the clipboard (handy for pasting
  into a client).
- **Auto** -- toggle the 2 s auto-refresh; **Refresh** polls once now.
- **Events** -- timestamped connect/disconnect log, so you can see a server come
  and go (e.g. restarting the Pulser server).
- **Status bar** -- manager host, server count, last-updated time. If the
  manager becomes unreachable it shows the error instead of crashing.

## Ideas for later

- Double-click (or a detail pane) to list a selected server's **settings**
  (IDs / names / signatures) -- needs confirming the pylabrad introspection call
  on the bench first.
- A registry browser/editor (replacing `RegistryEditor.exe`).
- Filter box to narrow a long server list.
