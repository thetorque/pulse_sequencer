# XEM7305 Pulse Sequencer — Phase 1: Host Interface Migration

Port of the pulse sequencer from XEM6010 (`VHDL_files/Pulser_w_2015_07_28/photon/photon.vhd`)
to the XEM7305. See the full port plan discussion for all phases; this
folder currently implements **Phase 1 only**.

**Status: Phase 1 complete and verified on real XEM7305 hardware** (see
Bring-up test plan below — every step confirmed via `test/smoke_test.py`).
Phase 2 (clocking) is next.

## Scope of this phase

Rewire the full legacy endpoint map onto the new-generation okHost
interface (`okUH`/`okHU`/`okUHU`/`okAA`/`okRSVD`, `okHE`/`okEH`/`okEHx`
buses) so host communication can be verified on real hardware before
porting the RAM/FIFO/PMT sequencer logic.

**Not yet implemented** (later phases): PLL/clock tree (Phase 2), block
RAM + FIFO IP for the sequence memory and photon counters (Phase 3),
`pmt_input`/`logic_out`/`logic_in`/`dds_logic_*` I/O and their pin
mapping (Phase 4 — blocked on a breakout board/pinout for the XEM7305,
see the port-plan discussion), and the actual sequencer/counting state
machines (Phase 5). [src/photon.vhd](src/photon.vhd) stubs all of that:
WireIn/TriggerIn values are only partially shown on LEDs, BTPipeIn
writes are accepted and discarded, and BTPipeOut reads return a fixed
per-address test pattern.

## Endpoint map (unchanged from the legacy design)

Preserved exactly so `Python_files/servers/pulser/api.py` needs no
address changes once this is wired up for real:

| Address | Type | Role |
|---|---|---|
| 0x00-0x06 | WireIn | mode/config, PMT period, manual overrides, DDS channel select, loop count, line-trigger delay |
| 0x40 | TriggerIn | reset counters/RAM/FIFOs, advance/reset DDS |
| 0x21, 0x22 | WireOut | status flags, photon-FIFO count |
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

- `src/photon.vhd` — new top-level (this phase's actual work)
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
- `constraints/xem7305.xdc` — host interface, clock, and LED pins only
  (copied from `../XEM7305_references/Counter/XEM7305-VHDL`). Pulser
  I/O pins are not yet defined — see Phase 4.
- `create_project.tcl` — recreates the Vivado project from these
  sources (`vivado -mode batch -source create_project.tcl`). Targets
  `xc7s50csga324-1`, matching `Locally_compiled_ramtester` and the
  `Device:` comment embedded in the copied encrypted OK netlists.
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

## Bring-up test plan for this phase

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
