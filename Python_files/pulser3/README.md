# pulser3 -- headless Python-3 host driver (XEM7305, 2026 bitstream)

A plain-Python-3 replacement for the FPGA-facing half of the legacy LabRAD
control stack (`../servers/pulser`). **No LabRAD, Twisted, or Qt.** It targets
the 2026 bitstream's endpoint map (DDR3 program store, Phase 6c), reusing the
hardware-proven DDR3 pipe primitives.

## Why this exists

The legacy `servers/pulser/api.py` speaks the **XEM6010** contract (on-chip
`pulser_ram`, old wire map, 30-bit time). The 2026 board uses a **different**
contract. A blind 2-to-3 of the old driver would import cleanly and drive the
wrong registers. `pulser3` ports the logic onto the correct map instead --
which the test scripts under `VHDL_files/.../test/` already validated.

## Layout

| file | role |
|---|---|
| `wiremap.py` | 2026 endpoint constants (single source of truth for the host<->FPGA contract). Pure, hardware-free. |
| `_ddr3.py` | Bridge to the proven DDR3 pipe primitives in `ddr3_roundtrip_demo.py` (lazy `ok` import). |
| `driver.py` | `Driver`: connect, load DDR3 program, start/stop/loop, reset, status. |
| `run_demo.py` | M1 end-to-end proof: 12-state waveform via the driver (`python -m pulser3.run_demo <bit>`). |

## Status

- **M1 (done):** low-level driver -- connect, program load + verify, run
  (single / infinite / N loops), status (seq_done, seq_count, line_count,
  overflow). Verify on hardware with `run_demo.py`.
- **M2 (next):** sequence compiler -- port `servers/pulser/sequence.py`
  (`addPulse`, `extendSequenceLength`, `parseTTL`) to py3, emitting the line
  list `Driver.load_program` consumes. Desktop-unit-testable (no `ok`).
- **M3:** `hwconfig.py` (channel name->number, 40 ns res, 31-bit time) +
  an ergonomic `run_sequence.py` CLI (named channels in seconds -> hardware).

## Deferred (M4) -- DDS + PMT

The 2026 design will include DDS and PMT/photon-counting, but that **hardware
isn't ready yet**, so it is intentionally not ported. When it lands, port
`servers/pulser/dds.py` and the readout pipes (`getNormalCounts`,
`getResolvedCounts`, `getReadoutCounts`, BTPipeOut 0xa0-0xa2) against the then-
current wire map. Tracked so it isn't forgotten.

## Requirements

Python 3 + the Opal Kelly `ok` FrontPanel module (only needed to touch
hardware -- `wiremap`/`sequence` import without it for off-bench unit tests).
