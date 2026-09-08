# XEM7305 Pulse Sequencer — Phase 1 + Phase 2 + Phase 3

Port of the pulse sequencer from XEM6010 (`VHDL_files/Pulser_w_2015_07_28/photon/photon.vhd`)
to the XEM7305. See the full port plan discussion for all phases; this
folder currently implements **Phases 1, 2, and 3**.

**Status:**
- Phase 1 (host interface migration): **complete and verified on real
  XEM7305 hardware** (see Bring-up test plan below — every step
  confirmed via `test/smoke_test.py`).
- Phase 2 (clocking): **complete and verified on real XEM7305
  hardware** — MMCM locked, and clk_200/clk_100/clk_20 measured at
  200.16/100.08/20.02 MHz (0.1% of nominal) via `test/smoke_test.py`.
- Phase 3 (pulse-sequence RAM/FIFO path): **complete and verified on
  real XEM7305 hardware** — `pulse_fifo` drains a written pulse
  program into `pulser_ram`, and all three BTPipeOut read FIFOs
  (`fifo_photon`, `normal_pmt_fifo`, `readout_count_fifo`) respond
  correctly with empty occupancy (no Phase 5 producer yet) via
  `test/smoke_test.py`.

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

**Phase 3** ports the pulse-sequence RAM and photon-counting FIFOs to
native Vivado IP: `pulse_fifo` (32-bit write side, 64-bit read side —
width conversion, since `pulser_ram`'s word format stays 64 bits wide
for Phase 5 sequencer compatibility) drains into `pulser_ram` (Simple
Dual-Port Block RAM, 64-bit, 1024 deep), and the three read-side FIFOs
(`fifo_photon`, `normal_pmt_fifo`, `readout_count_fifo`) are native
32-bit Independent-Clocks Block RAM FIFOs feeding BTPipeOut 0xA0-0xA2.
Occupancy (`rd_data_count`) for all four FIFOs is exposed at new
bring-up-only WireOut endpoints (0x27-0x2A). Phase 3 only wires the
RAM *write* path and the read FIFOs' *read* side — nothing yet drives
`pulser_ram`'s read port or the read FIFOs' write ports (that's
Phase 5). `dds_fifo` is deliberately **excluded** from this phase: its
read clock is supplied by the DDS board itself, so it belongs with the
rest of the DDS I/O in Phase 4/5, not with the sequence-memory path.
All 5 IP cores were generated manually in the Vivado GUI (not via
`create_project.tcl`) with settings cross-checked against the legacy
`.xco` configs in `VHDL_files/Pulser_w_2015_07_28/photon/ipcore_dir/`.

**Not yet implemented** (later phases):
`pmt_input`/`logic_out`/`logic_in`/`dds_logic_*` I/O and their pin
mapping, plus `dds_fifo` (Phase 4 — blocked on a breakout
board/pinout for the XEM7305, see the port-plan discussion), and the
actual sequencer/counting state machines that drive `pulser_ram`'s
read port and produce data into the read FIFOs (Phase 5).
[src/photon.vhd](src/photon.vhd) stubs the rest: WireIn/TriggerIn
values are only partially shown on LEDs, the DDS program pipe (0x81)
is accepted and discarded, and the RAM-writer drain process used to
bring up Phase 3 is a bring-up-only stand-in for the real sequencer.

## Endpoint map

0x00-0x22, 0x40, 0x80-0xA2 are unchanged *addresses* from the legacy
design and preserved exactly so `Python_files/servers/pulser/api.py`
needs no address changes once this is wired up for real — though as
of Phase 3, 0x80 and 0xA0-0xA2 now reach real FIFOs/RAM instead of
stub logic (see Phase 3 scope above). 0x23-0x2A are new, Phase 2/3
bring-up additions with no legacy equivalent.

| Address | Type | Role |
|---|---|---|
| 0x00-0x06 | WireIn | mode/config, PMT period, manual overrides, DDS channel select, loop count, line-trigger delay |
| 0x40 | TriggerIn | reset counters/RAM/FIFOs, advance/reset DDS |
| 0x21, 0x22 | WireOut | status flags, photon-FIFO count |
| 0x23 | WireOut | *(Phase 2 bring-up only)* MMCM `locked` (bit 0) |
| 0x24-0x26 | WireOut | *(Phase 2 bring-up only)* free-running counters on clk_200/clk_100/clk_20 |
| 0x27-0x2A | WireOut | *(Phase 3 bring-up only)* `rd_data_count` occupancy for `pulse_fifo`/`fifo_photon`/`normal_pmt_fifo`/`readout_count_fifo` |
| 0x80 | BTPipeIn | pulse sequence program → `pulse_fifo` → `pulser_ram` |
| 0x81 | BTPipeIn | DDS program (still a discard-everything stub) |
| 0xA0 | BTPipeOut | time-resolved photon counts, from `fifo_photon` |
| 0xA1 | BTPipeOut | normal PMT counts, from `normal_pmt_fifo` |
| 0xA2 | BTPipeOut | readout counts, from `readout_count_fifo` |

## Important interface change to carry into later phases

Wire/pipe data on this FrontPanel generation is **32 bits wide**
(`ep_dataout`/`ep_datain` in `src/okLibrary.vhd` are all
`std_logic_vector(31 downto 0)`), vs. the legacy XEM6010 design's
16-bit wires/pipes. Phase 3 adopted this natively: all FIFOs read/write
32 bits on the host side (rather than preserving the legacy 16-bit
width), except `pulse_fifo`, which still converts 32→64 on its read
side since `pulser_ram`'s word format stays 64 bits wide for Phase 5
sequencer compatibility. This is a throughput improvement, but a real
change from the legacy RTL, and likely means
`Python_files/servers/pulser/sequence.py` will need to change how it
packs bytes for the pipe transfers once Phase 5 wires up real data.

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
- `pulse_fifo`, `pulser_ram`, `fifo_photon`, `normal_pmt_fifo`,
  `readout_count_fifo` — Phase 3 FIFO Generator / Block Memory
  Generator IP, generated manually in the Vivado IP catalog (not by
  `create_project.tcl`) so settings could be reviewed interactively
  against the legacy `.xco` configs before committing to them. Not
  checked in, same as `clk_wiz_0` — regenerate from the settings
  documented in the Phase 3 scope section above if the project is
  rebuilt from scratch.
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

## Bring-up test plan — Phase 2

All steps below confirmed via `test/smoke_test.py` on real XEM7305
hardware.

1. ✅ Read WireOut 0x23 bit 0 and confirm the MMCM reports `locked`.
2. ✅ Read WireOut 0x24/0x25/0x26 twice, ~1s apart, and confirm the
   counter deltas correspond to ~200 MHz / ~100 MHz / ~20 MHz —
   measured 200.16/100.08/20.02 MHz (0.1% error).
3. ✅ Re-confirm all Phase 1 checks still pass (the `okWireOR` fan-in
   width and `okEHx` slot count changed to make room for the new
   WireOut endpoints — no regression observed).

`src/photon.vhd`'s `clk_wiz_0` component declaration (`clk_in1`,
`clk_out1`, `clk_out2`, `clk_out3`, `locked`) matched the actual
generated wrapper as-is — no `reset` port, no adjustments needed.

## Bring-up test plan — Phase 3

All steps below confirmed via `test/smoke_test.py` on real XEM7305
hardware.

1. ✅ Confirm `pulse_fifo` reports empty (WireOut 0x27 = 0) before any
   write.
2. ✅ Write a 16-byte pattern to BTPipeIn 0x80 and confirm the transfer
   completes.
3. ✅ Poll WireOut 0x27 and confirm it returns to 0 — proves the
   bring-up-only RAM-writer drain process pulled the word out of
   `pulse_fifo` and wrote it into `pulser_ram` (drained in 1 poll).
4. ✅ Read BTPipeOut 0xA0/0xA1/0xA2 (`fifo_photon`/`normal_pmt_fifo`/
   `readout_count_fifo`) and confirm each transfer completes.
5. ✅ Confirm WireOut 0x28/0x29/0x2A all read back 0 — expected, since
   no Phase 5 producer writes to these FIFOs yet.
6. ✅ Re-confirm all Phase 1/2 checks still pass (no regression from
   the added IP or the `okWireOR`/`okEHx` width changes needed for the
   new WireOut endpoints).

All 5 generated `.vhd` wrappers (`pulse_fifo`, `pulser_ram`,
`fifo_photon`, `normal_pmt_fifo`, `readout_count_fifo`) were checked
against `src/photon.vhd`'s component declarations before this test
ran. Notable GUI settings that needed correcting from Vivado's
defaults to match the legacy `.xco` behavior:

- Block Memory Generator (`pulser_ram`): "Always Enabled" instead of
  "Use ENA/ENB Pin" (the default would have exposed required `ena`/
  `enb` inputs not present in the component declaration); Port B
  output register unchecked (legacy has 1-cycle read latency, not the
  default 2-cycle).
- `pulse_fifo`: Read Mode set to First-Word-Fall-Through (the drain
  FSM assumes FWFT); Read Data Count enabled on the Data Counts tab
  (unset by default, which would have omitted the `rd_data_count`
  port).
- `fifo_photon`: Full Flags Reset Value set to 0 (the one FIFO in the
  whole design that differs from the others' value of 1, per the
  legacy `.xco`); Read Data Count enabled, same reason as above.
- `normal_pmt_fifo`, `readout_count_fifo`: matched the legacy `.xco`
  and the Vivado defaults with no corrections needed.

**Known CDC concern, not yet fixed:** the RAM-writer drain process
(bring-up-only, `src/photon.vhd`) reads `ep40wire(1)` as a reset in
the `clk_100` domain, but that TriggerIn is generated with
`ep_clk => sys_clk` (200 MHz) — a single-cycle pulse that could in
principle be missed by the `clk_100` domain. Not exercised by the
current test (nothing triggers this reset bit), but worth revisiting
before Phase 5 relies on that reset path.
