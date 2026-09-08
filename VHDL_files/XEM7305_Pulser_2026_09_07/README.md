# XEM7305 Pulse Sequencer — Phase 1 + Phase 2

Port of the pulse sequencer from XEM6010 (`VHDL_files/Pulser_w_2015_07_28/photon/photon.vhd`)
to the XEM7305. See the full port plan discussion for all phases; this
folder currently implements **Phases 1 and 2**.

**Status:**
- Phase 1 (host interface migration): **complete and verified on real
  XEM7305 hardware** (see Bring-up test plan below — every step
  confirmed via `test/smoke_test.py`).
- Phase 2 (clocking): scaffolded, **not yet built/tested on hardware**.

## Scope of these phases

**Phase 1** rewires the full legacy endpoint map onto the
new-generation okHost interface (`okUH`/`okHU`/`okUHU`/`okAA`/`okRSVD`,
`okHE`/`okEH`/`okEHx` buses) so host communication can be verified on
real hardware before porting the RAM/FIFO/PMT sequencer logic.

**Phase 2** replaces the legacy design's `clk_pll_100_in_200_out` MMCM
with a Vivado Clocking Wizard IP (`src/ip/clk_wiz_0`), producing the
same three clocks — 200 MHz (PMT oversampling), 100 MHz (main sequencer
state machine), 20 MHz (DDS FIFO / line-trigger) — but from the
XEM7305's 200 MHz differential `sys_clk` instead of the XEM6010's
100 MHz single-ended Cypress clock. MMCM lock status and a
free-running counter per clock are exposed at new bring-up-only WireOut
endpoints (0x23-0x26, no legacy equivalent) so `test/smoke_test.py` can
verify actual frequency from Python instead of trusting the
configuration blindly.

**Not yet implemented** (later phases): block RAM + FIFO IP for the
sequence memory and photon counters (Phase 3),
`pmt_input`/`logic_out`/`logic_in`/`dds_logic_*` I/O and their pin
mapping (Phase 4 — blocked on a breakout board/pinout for the XEM7305,
see the port-plan discussion), and the actual sequencer/counting state
machines (Phase 5). [src/photon.vhd](src/photon.vhd) stubs all of that:
WireIn/TriggerIn values are only partially shown on LEDs, BTPipeIn
writes are accepted and discarded, and BTPipeOut reads return a fixed
per-address test pattern.

## Endpoint map

0x00-0x22, 0x40, 0x80-0xA2 are unchanged from the legacy design and
preserved exactly so `Python_files/servers/pulser/api.py` needs no
address changes once this is wired up for real. 0x23-0x26 are new,
Phase-2-only bring-up additions with no legacy equivalent.

| Address | Type | Role |
|---|---|---|
| 0x00-0x06 | WireIn | mode/config, PMT period, manual overrides, DDS channel select, loop count, line-trigger delay |
| 0x40 | TriggerIn | reset counters/RAM/FIFOs, advance/reset DDS |
| 0x21, 0x22 | WireOut | status flags, photon-FIFO count |
| 0x23 | WireOut | *(Phase 2 bring-up only)* MMCM `locked` (bit 0) |
| 0x24-0x26 | WireOut | *(Phase 2 bring-up only)* free-running counters on clk_200/clk_100/clk_20 |
| 0x80 | BTPipeIn | pulse sequence program |
| 0x81 | BTPipeIn | DDS program |
| 0xA0 | BTPipeOut | time-resolved photon counts |
| 0xA1 | BTPipeOut | normal PMT counts |
| 0xA2 | BTPipeOut | readout counts |

## Important interface change to carry into later phases

Wire/pipe data on this FrontPanel generation is **32 bits wide**
(`ep_dataout`/`ep_datain` in `src/okLibrary.vhd` are all
`std_logic_vector(31 downto 0)`), vs. the legacy XEM6010 design's
16-bit wires/pipes. Phase 3's FIFOs need to widen to match — a
throughput improvement, but a real change to the RTL and possibly to
how `Python_files/servers/pulser/sequence.py` packs bytes for the pipe
transfers.

## Files

- `src/photon.vhd` — top-level (Phase 1 host interface + Phase 2 clocking)
- `src/okLibrary.vhd`, `okCoreHarness.v`, `okWireIn.v`, `okWireOut.v`,
  `okTriggerIn.v`, `okBTPipeIn.v`, `okBTPipeOut.v` — Opal Kelly IP,
  copied verbatim from `../XEM7305_references/Locally_compiled_photon_2026`
  (already proven on this hardware). Do not hand-edit these. Note:
  Opal Kelly also ships `okLibrary.v`, a Verilog reimplementation of
  the same `okHost`/`okWireOR` defined in `okLibrary.vhd` — meant for
  Verilog-only projects, not to be added alongside the VHDL version.
  Deliberately **not** included here since `photon.vhd` is VHDL and
  resolves those via `okLibrary.vhd`'s `FRONTPANEL` package; adding
  both gives Vivado two conflicting definitions of the same module.
- `src/ip/clk_wiz_0/` — Vivado Clocking Wizard IP (Phase 2), generated
  by `create_project.tcl`. Not checked in — regenerated fresh each time
  the Tcl script runs, like any other Vivado-managed IP.
- `constraints/xem7305.xdc` — host interface, clock, and LED pins only
  (copied from `../XEM7305_references/Counter/XEM7305-VHDL`). Pulser
  I/O pins are not yet defined — see Phase 4.
- `create_project.tcl` — recreates the Vivado project from these
  sources (`vivado -mode batch -source create_project.tcl`), including
  generating the Phase 2 `clk_wiz_0` IP. Targets `xc7s50csga324-1`,
  matching `Locally_compiled_ramtester` and the `Device:` comment
  embedded in the copied encrypted OK netlists.
  `Locally_compiled_photon_2026` was instead built for `csga324-2` —
  confirm your board's actual speed grade before building for hardware.

## Known-good FrontPanel SDK version

`test/smoke_test.py` failed to `ConfigureFPGA()` from Python (error -7,
`FileError`) on Windows with a newer FrontPanel SDK/driver install, even
though the identical `.bit` loaded fine through the FrontPanel GUI
itself. Root cause was a path typo in how the script was invoked, but
what actually made it visible/fixable was downgrading to **FrontPanel
SDK 5.3.7** — that's the version confirmed working end-to-end (GUI
bitstream load + scripted `ConfigureFPGA` + WireIn/WireOut round trip)
on this Windows PC. If `ConfigureFPGA` starts failing again on a
different machine, matching this SDK version is the first thing to try.

## Bring-up test plan — Phase 1

All steps below confirmed via `test/smoke_test.py` on real XEM7305
hardware (FrontPanel SDK 5.3.7).

1. ✅ Build and program the bitstream.
2. ✅ Using OK's FrontPanel software (or a quick Python `ok.FrontPanel()`
   script), write to WireIn 0x00 bits 0-2 and confirm LEDs 0-2 respond.
3. ✅ Confirm LED 3 blinks on its own (proves the `sys_clkp`/`sys_clkn`
   oscillator + `IBUFGDS` path independently of USB traffic).
4. ✅ Read WireOut 0x21/0x22 and confirm they echo WireIn 0x00 / TriggerIn
   0x40 state.
5. ✅ Read BTPipeOut 0xA0/0xA1/0xA2 and confirm each returns its distinct
   test pattern (`0xA0A0A0A0`, `0xA1A1A1A1`, `0xA2A2A2A2`) — confirms
   address decoding is correct for all three read pipes.
6. ✅ Write to BTPipeIn 0x80/0x81 and confirm the transfer completes
   without hardware hang (content is discarded at this phase).

## Bring-up test plan — Phase 2 (not yet run on hardware)

Covered by `test_clocking()` in `test/smoke_test.py`, but the design
has not been synthesized/tested since these changes were added — needs
a rebuild in Vivado (`vivado -mode batch -source create_project.tcl`,
which now also generates the `clk_wiz_0` IP) before any of this can be
confirmed.

1. ⬜ Read WireOut 0x23 bit 0 and confirm the MMCM reports `locked`.
2. ⬜ Read WireOut 0x24/0x25/0x26 twice, ~1s apart, and confirm the
   counter deltas correspond to ~200 MHz / ~100 MHz / ~20 MHz
   (`test_clocking()` does this with a 5% tolerance).
3. ⬜ Re-confirm all Phase 1 checks still pass (the `okWireOR` fan-in
   width and `okEHx` slot count changed to make room for the new
   WireOut endpoints — a regression here would mean a slot-indexing
   mistake).

Before building: `src/photon.vhd` declares a `clk_wiz_0` component with
ports (`clk_in1`, `clk_out1`, `clk_out2`, `clk_out3`, `locked`) matching
Vivado's standard Clocking Wizard wrapper naming, but this hasn't been
checked against the actual generated `src/ip/clk_wiz_0/clk_wiz_0.vhd`
on real Vivado — if synthesis reports a missing/mismatched component,
compare port names there first.
