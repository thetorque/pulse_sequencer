# parameter_vault -- py3 ParameterVault LabRAD server

Python-3 port of the legacy `servers/parameter_vault` for the modern
**scalabrad** manager. ParameterVault is the experiment's central parameter
store: it holds every parameter in memory, keyed by `(collection,
parameter_name)`, backed by the LabRAD **Registry** (under
`Servers > Parameter Vault`). Experiment scripts, trackers, and GUIs all read
and write their settings through it.

Same LabRAD name, setting IDs/names, and *parameter change* signal as the
legacy server, so existing clients work unchanged. Ported off py2 and hardened
so a fresh (empty) registry doesn't crash startup.

## Parameter types

Each parameter is stored as `(type, value)`; a *checked* read (`Get Parameter`
with `checked=True`, the default) reduces it to its effective value:

| type | stored value | checked read |
|---|---|---|
| `parameter` | `(min, max, current)` | `current` (bounds-checked) |
| `duration_bandwidth` | `(min, max, current)` | `current` (bounds-checked) |
| `scan` | `((min,max), (start,stop,N))` | `(start, stop, N)` |
| `selection_simple` | `(choice, [choices])` | `choice` |
| `line_selection` | `(choice, [(label,val),…])` | `choice` |
| `string` / `bool` / `sideband_selection` / `spectrum_sensitivity` | value | value as-is |

## Settings

| ID | method | purpose |
|---|---|---|
| 0 | `set_parameter` | set a value (`full_info=True` replaces the whole typed record) |
| 1 | `get_parameter` | get a value (`checked=True` reduces to the effective value) |
| 2 | `get_parameter_names` | names in a collection |
| 3 | `save_parameters_to_registry` | persist memory → registry |
| 4 | `get_collections` | all collection names |
| 5 | `refresh_parameters` | save, then reload from registry |
| 6 | `reload_parameters` | discard memory, reload from registry |

Plus the `signal: parameter change` (ID 612512, `(ss)` = collection, name) fired
to other clients when a parameter is set.

## Running

Start the scalabrad manager first (see `../pulser_labrad/README.md` for the
manager + `pylabrad` setup — same manager serves every server). Then:

```bash
python parameter_vault/parameter_vault.py
```

It connects, ensures the `Servers > Parameter Vault` registry tree exists, loads
whatever parameters are there, and registers as **ParameterVault**. Smoke test
in another shell:

```bash
python parameter_vault/test_client.py
```

Expected: it seeds two parameters, reloads, reads/writes them, checks that an
out-of-bounds write is rejected, and prints `PASS`.

## Notes

- The parameter tree lives in the registry, so it persists across restarts and
  is shared with any other client that reads `Servers > Parameter Vault`.
- No hardware — this server is pure infrastructure. It's a dependency of the
  experiment scripts, ScriptScanner, and the trackers (all still to port).
