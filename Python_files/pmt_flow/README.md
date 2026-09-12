# pmt_flow -- py3 NormalPMTFlow LabRAD server

The higher-level PMT server. It sits **on top of the Pulser** and continuously
records photon counts into the **Data Vault** at a fixed collection period, and
serves live counts to clients. py3 port of the legacy
`servers/PMT_flow/NormalPMTFlow.py`, delegating to the ported Pulser (PMT
counting) and the adopted Data Vault -- same LabRAD name, setting IDs, and
signals so existing clients keep working.

```
client ──► NormalPMTFlow ──► Pulser (PMT counting) ──► XEM7305
                    └────────► Data Vault (logs each window)
```

## Dependencies (must be running)

The manager, plus **Pulser**, **Data Vault**, and this server. NormalPMTFlow
reconnects automatically if the Pulser or Data Vault comes/goes (it listens for
the manager's Server Connect/Disconnect messages).

## Modes

- **Normal** -- works end-to-end today with the Pulser's on-FPGA **synthetic
  source** (no detector needed). Each collection window's count rate is streamed
  into the Data Vault as `[t, count, 0, 0]`.
- **Differential** -- runs on the FPGA differential counter, gated by
  `DiffCountTrigger` (channel 16, now in `pulser3.hwconfig`). The 866 repump
  channels `866DP` / `Internal866` are added to the sequence **only if present**
  in the channel map -- so it works on a synthetic-source bench (trigger only),
  and drives the real repump once you add those channels for your hardware. A
  meaningful ON/OFF differential needs the real 866 laser.

## Settings (unchanged from legacy)

| ID | method | purpose |
|---|---|---|
| 0 | `set_save_folder` | Data Vault directory for the counts |
| 1 | `start_new_dataset` | open a fresh dataset |
| 2 | `set_mode` | 'Normal' / 'Differential' |
| 3 | `get_current_mode` | active mode |
| 4 | `record_data` | start the recording loop |
| 5 | `stop_recording` | stop it |
| 6 | `is_running` | recording? |
| 7 | `current_data_set` | open dataset name |
| 8 | `set_time_length` | collection period (seconds) |
| 9 | `get_next_counts` | next N counts of 'ON'/'OFF'/'DIFF' (optionally averaged) |
| 10 | `get_time_length` | current period |
| 11 | `get_time_length_range` | allowed (min, max) |

Signals: `signal: new count` (331483, `v`) per window; `signal: new setting`
(331484, `(ss)`) on state/mode/dataset changes.

## Running

Start the manager + Pulser + Data Vault first (easiest via the Launcher), then:

```bash
python pmt_flow/normal_pmt_flow.py
```

Smoke test in another shell (drives Normal mode against the synthetic source):

```bash
python pmt_flow/test_client.py
```

Expected: it sets Normal mode, records for ~1.5 s, reads back an averaged ON
count rate near **100 KC/s** (100 kHz source over a 50 ms window), confirms a
dataset was created, and prints `PASS`.

## py3 changes

Mechanical: `print` statements → `print()`, `listeners.remove` → `discard`, and
the legacy Pulser's `complete_infinite_iteration` (absent from the 2026 Pulser
server) mapped to `stop_sequence` in `_stopPulserDiff`. Collection time is now
passed to the Pulser as a plain float (seconds), matching the 2026
`Set Collection Time` signature.
