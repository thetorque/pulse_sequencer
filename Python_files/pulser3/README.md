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
| `ddr3_backend.py` | Canonical low-level DDR3 pipe primitives (connect, calib wait, write/read). Single source of truth (M1.5). |
| `_ddr3.py` | Thin lazy seam over `ddr3_backend` that keeps the `ok` import deferred for off-bench use. |
| `driver.py` | `Driver`: connect, load DDR3 program, start/stop/loop, reset, status. |
| `sequence.py` | `Sequence`: build TTL pulses in seconds (int or named channels) -> compile to the 64-bit line list. |
| `hwconfig.py` | Experiment config: channel name->number map + timing; `new_sequence()` factory. |
| `run_demo.py` | M1 end-to-end proof: 12-state waveform via the driver (`python -m pulser3.run_demo <bit>`). |
| `run_sequence.py` | M3 named-channel runner: hwconfig -> Sequence -> Driver (`python -m pulser3.run_sequence <bit>`). |
| `test_sequence.py` | `Sequence` unit tests, no hardware (`python -m pulser3.test_sequence`). |

## Status

- **M1 (done):** low-level driver -- connect, program load + verify, run
  (single / infinite / N loops), status (seq_done, seq_count, line_count,
  overflow). Verify on hardware with `run_demo.py`.
- **M2 (done):** sequence compiler -- `sequence.py` ports
  `addPulse`/`extendSequenceLength`/`parseTTL` to py3 (no numpy/LabRAD),
  emitting the 64-bit line list `Driver.load_program` consumes. 6/6 unit tests
  pass off the bench. Preserves the legacy absolute-tick timing model; refuses
  empty sequences (which would hang the FSM). Not yet exercised on hardware
  through the driver -- that lands with M3's runner.
- **M3 (done, hardware-verified):** `hwconfig.py` (channel name->number map +
  timing, ported from the legacy TTL channelDict) + `run_sequence.py`, an
  ergonomic named-channel CLI (`hwconfig -> Sequence -> Driver`). `run_sequence`
  drives the walking-staircase LED pattern on silicon -- the full compiler ->
  driver path is proven end to end.
- **M1.5 (done):** made `pulser3` self-contained -- lifted the DDR3 pipe
  primitives out of the FPGA test tree into `ddr3_backend.py` (byte-faithful
  move, diff-verified), and flipped `ddr3_roundtrip_demo.py` to import them from
  here (it self-bootstraps `pulser3` onto `sys.path`, so `ddr3_sequencer_bringup`
  and `run_all_6c` keep working unchanged). The package no longer reaches into
  `VHDL_files/`. Re-verify `run_all_6c` on the bench once (behavior is identical
  by construction, but it touches the green 6c path).

## Deferred (M4) -- DDS + PMT

The 2026 design will include DDS and PMT/photon-counting, but that **hardware
isn't ready yet**, so it is intentionally not ported. When it lands, port
`servers/pulser/dds.py` and the readout pipes (`getNormalCounts`,
`getResolvedCounts`, `getReadoutCounts`, BTPipeOut 0xa0-0xa2) against the then-
current wire map. Tracked so it isn't forgotten.

## Requirements

Python 3 + the Opal Kelly `ok` FrontPanel module (only needed to touch
hardware -- `wiremap`/`sequence` import without it for off-bench unit tests).
