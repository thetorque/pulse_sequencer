# data_vault -- py3 Data Vault LabRAD server (adopted upstream)

The Data Vault stores numeric experiment data: datasets of independent /
dependent variables with parameters and comments, on disk as **HDF5**, served
over LabRAD. Experiment scripts write their data here; the grapher reads it back.

This is **not a hand-port** -- it's the upstream, maintained
[`labrad/servers`](https://github.com/labrad/servers) Data Vault package
(v3.0.1) vendored here and given a small Python-3 cleanup, rather than porting
the lab's older ASCII-only `dvascii.py`. We get the structured, backend-
abstracted (HDF5 + CSV), grapher-compatible implementation. GPL headers are kept
intact.

```
client / experiment script  ──LabRAD──►  Data Vault  ──►  HDF5 files on disk
```

## Layout

| path | role |
|---|---|
| `data_vault.py` | launcher: reads the storage dir from the registry (prompts on first run), starts the server |
| `datavault/server.py` | the `Data Vault` LabRAD server (settings) |
| `datavault/backend.py` | storage backends (HDF5 primary, CSV) |
| `datavault/__init__.py` | `SessionStore` -- sessions/datasets on disk |
| `datavault/util.py`, `errors.py` | helpers, error types |
| `test_client.py` | smoke test: create a dataset, add rows, read back |

## Python-3 changes made

Purely mechanical (the upstream was already `from __future__`-straddled):
`print` statements → `print()`, `except X, e:` → `except X as e:`,
`raw_input` → `input`, and `xrange(sys.maxint)` → `itertools.count()` (two
unbounded attribute-scan loops). No logic changed.

## One-time setup

Needs `h5py` (the HDF5 storage format) in addition to the usual pylabrad stack:

```bash
pip install h5py
```

## Running

Start the scalabrad manager first (see `../pulser_labrad/README.md`), then, with
the LabRAD env set:

```bash
python data_vault/data_vault.py
```

**First run** it can't find a storage directory in the registry and prompts:

```
Could not load repository location from registry.
Please enter data storage directory or hit enter to use
the default directory (~/.labrad/vault):
>>>
```

Hit enter to accept `~/.labrad/vault` (or type a path). It saves the location to
the registry under `Servers > Data Vault > Repository`, so subsequent starts are
non-interactive. Then it registers as **Data Vault** (visible in the Manager
Monitor).

Smoke test in another shell:

```bash
python data_vault/test_client.py
```

Expected: it creates a dataset, writes 5 rows, reads them back, and prints
`PASS`. The data lands as an HDF5 file under the storage directory.

## Notes

- Data Vault is just the **storage** server -- it has no GUI. Viewing data
  graphically is the grapher's job (`pygrapherlive`, a later port, or our own).
- The client-side server name maps to `cxn.data_vault` (pylabrad lowercases
  "Data Vault" and turns the space into an underscore).
- Key settings: `cd` / `dir` (navigate), `new` (create a dataset), `open`,
  `add` (append rows), `get` (read rows), `variables`, `add parameter` /
  `get parameters`, `add comment` / `get comments`, tags.
