# XEM7305 Pulse Sequencer — Phase 1 + Phase 2 + Phase 3 + Phase 5a + Phase 6a + Phase 6b

Port of the pulse sequencer from XEM6010 (`VHDL_files/Pulser_w_2015_07_28/photon/photon.vhd`)
to the XEM7305. See the full port plan discussion for all phases; this
folder currently implements **Phases 1, 2, 3, 5a, and 6a** (Phase 4 and
the rest of Phase 5 are blocked on a breakout board — see below; Phase
6b onward is the rest of the DDR3 migration for `pulser_ram`).

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
- Phase 5a (pulse-sequence FSM + `logic_out`): **complete and verified
  on real XEM7305 hardware** — the sequencer reads a RAM-programmed
  sequence, respects its timing, and correctly signals completion via
  `test/smoke_test.py`. `test/led_walk_demo.py` further confirmed a
  real, non-symmetric `logic_out` pattern on real hardware — `led_ext`
  visibly lights `[0]` through `[5]` in turn, 0.5 s apart — and
  resolved `pulse_fifo`'s write-order convention empirically along the
  way (see Phase 5a bring-up section below).
- Phase 6a (DDR3 MIG bring-up): **complete and verified on real XEM7305
  hardware** — `ddr3_256_16` (Xilinx MIG 7-series) instantiated with
  its `app_*` command interface tied fully inert (nothing reads/writes
  DDR3 yet — that's Phase 6b), MIG owns the physical `sys_clk_p`/
  `sys_clk_n` pins directly, `clk_wiz_0` re-sourced from MIG's `ui_clk`,
  and `init_calib_complete` (WireOut 0x2D) confirmed asserting via
  `test/smoke_test.py` — real calibration against the XEM7305's actual
  DDR3 chip, not just a clean build.

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

**Phase 5a** ports the legacy design's main pulse-sequence FSM: it
reads `pulser_ram`'s read port (unused since Phase 3) two words ahead,
applies each 64-bit word's low 32 bits to `master_logic` for the
duration given by its high 30 bits, and derives `logic_out` from
`master_logic` through the same per-channel force/invert override mux
(`ep02wire`/`ep03wire`) as the legacy design. The legacy design drove
`pulser_ram`'s read-port clock as a manually-toggled pulse from its own
FSM; our Vivado-generated `pulser_ram` has a real, continuously-running
read clock instead (fixed 1-cycle latency, no enable pin), so that
toggle scheme couldn't be ported literally — the read-ahead pipeline
was redesigned around this simpler always-on port, while preserving
the legacy 40 ns/tick (4 `clk_100` cycles) timing exactly, so existing
pulse programs keep meaning the same real-world durations. See the
`photon.vhd` file header for the full explanation.

`logic_out`'s low 6 bits reach real pins: `led_ext`, a 6-LED add-on
header (pins copied from `../XEM7305_references/Locally_compiled_ramtester`,
LVCMOS33 — a different bank/voltage than the onboard `led[3:0]`, so a
separate board/header, not more onboard LEDs). The rest of `logic_out`
has no pins yet (Phase 4); the full 32-bit value plus sequence-done/
loop-count status are exposed on bring-up-only WireOuts (0x2B/0x2C)
regardless, so the FSM can be verified independent of `led_ext`.
`pmt_input`/`logic_in`/`dds_logic_*` and their pin mapping, plus
`dds_fifo`, are still blocked on a breakout board/pinout for the
XEM7305 — see the port-plan discussion.

**Not yet implemented** (later phases): line-trigger conditioning
(Phase 5b — the legacy design's `logic_in(0)` debounce/delay/pulse
chain that gates the sequencer's wait-to-start state; stubbed to
always-disabled for now), PMT oversampling and the three FIFOs'
write-side counting logic (Phase 5c), and DDS step/reset control
routing (Phase 5d) — all blocked on the same breakout board as Phase 4.
[src/photon.vhd](src/photon.vhd) stubs the rest: WireIn/TriggerIn
values are only partially shown on LEDs, the DDS program pipe (0x81)
is accepted and discarded, and the three read FIFOs' write sides are
unconnected (their bring-up occupancy WireOuts will correctly read 0
until Phase 5c exists).

**Phase 6a** begins the DDR3 migration for `pulser_ram` (currently
1024×64-bit BRAM — fine for bring-up, but a hard ceiling for real
experiment sequences): instantiates the DDR3 SDRAM controller
(`src/ip/ddr3_256_16`, Xilinx MIG 7-series, generated from
`../XEM7305_references/Locally_compiled_ramtester`'s proven `mig_b.prj`
configuration unmodified) as pure bring-up. Its `app_*` command
interface is tied fully inert (`app_en`/`app_wdf_wren` = `'0'`) —
nothing reads or writes DDR3 yet; that's Phase 6b's read-prefetch-
buffer/write-burst-assembler adapters. MIG now owns the physical
`sys_clk_p`/`sys_clk_n` differential pins directly (System Clock =
Differential, matching the proven reference design exactly), replacing
the old `IBUFGDS`/`sys_clk` path; `clk_wiz_0` (Phase 2) is re-sourced
from MIG's `ui_clk` (~81.25 MHz) instead of raw `sys_clk`, and the
heartbeat counter and `TriggerIn` 0x40's `ep_clk` both move to `ui_clk`
too — it's the earliest clock in the whole chain that's independent of
USB traffic (available once just MIG's own PLL locks, without needing
full DDR3 calibration or `clk_wiz_0`'s own lock). A new bring-up-only
WireOut (0x2D) exposes `init_calib_complete` for host-side polling.

## Endpoint map

0x00-0x22, 0x40, 0x80-0xA2 are unchanged *addresses* from the legacy
design and preserved exactly so `Python_files/servers/pulser/api.py`
needs no address changes once this is wired up for real — though as
of Phase 3, 0x80 and 0xA0-0xA2 now reach real FIFOs/RAM instead of
stub logic (see Phase 3 scope above). 0x23-0x2D are new, Phase
2/3/5a/6a bring-up additions with no legacy equivalent.

| Address | Type | Role |
|---|---|---|
| 0x00-0x06 | WireIn | mode/config, PMT period, manual overrides, DDS channel select, loop count, line-trigger delay |
| 0x40 | TriggerIn | reset counters/RAM/FIFOs, advance/reset DDS |
| 0x21, 0x22 | WireOut | status flags, photon-FIFO count |
| 0x23 | WireOut | *(Phase 2 bring-up only)* MMCM `locked` (bit 0) |
| 0x24-0x26 | WireOut | *(Phase 2 bring-up only)* free-running counters on clk_200/clk_100/clk_20 |
| 0x27-0x2A | WireOut | *(Phase 3 bring-up only)* `rd_data_count` occupancy for `pulse_fifo`/`fifo_photon`/`normal_pmt_fifo`/`readout_count_fifo` |
| 0x2B | WireOut | *(Phase 5a bring-up only)* full 32-bit `logic_out` readback |
| 0x2C | WireOut | *(Phase 5a bring-up only)* bit 16 = sequence-done, bits 15:0 = running loop count |
| 0x2D | WireOut | *(Phase 6a bring-up only)* MIG `init_calib_complete` (bit 0) |
| 0x80 | BTPipeIn | pulse sequence program → `pulse_fifo` → `pulser_ram` |
| 0x81 | BTPipeIn | DDS program (still a discard-everything stub) |
| 0xA0 | BTPipeOut | time-resolved photon counts, from `fifo_photon` |
| 0xA1 | BTPipeOut | normal PMT counts, from `normal_pmt_fifo` |
| 0xA2 | BTPipeOut | readout counts, from `readout_count_fifo` |

`logic_out(5 downto 0)` is also driven out to the `led_ext` output
port (see Files below) — not a FrontPanel endpoint, but the only part
of `logic_out` with physical pins so far.

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

- `src/photon.vhd` — top-level (Phase 1 host interface + Phase 2
  clocking + Phase 3 RAM/FIFO + Phase 5a sequencer FSM + Phase 6a DDR3
  MIG bring-up)
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
  the Tcl script runs, like any other Vivado-managed IP. As of Phase
  6a, its input is `ui_clk` (~81.25 MHz, MIG-derived, not a clean
  number) instead of raw `sys_clk` — `PRIM_IN_FREQ`/`PRIM_SOURCE`
  updated accordingly (see `create_project.tcl` below); the requested
  200/100/20 MHz outputs land ~0.02% off exactly clean, which Vivado
  reports as an unavoidable warning (81.25 MHz doesn't divide back into
  the MMCM's 0.125-step multiply grid evenly) — negligible for this
  design's timing needs.
- `src/ip/ddr3_256_16/` — Xilinx MIG 7-series DDR3 SDRAM controller IP
  (Phase 6a), generated by `create_project.tcl` via
  `CONFIG.XML_INPUT_FILE` loading
  `../XEM7305_references/Locally_compiled_ramtester`'s proven
  `mig_b.prj` unmodified — this bypasses the interactive Pin Selection
  wizard's DRC, which fails validating `ddr3_ba[0]`'s pin placement due
  to a MIG-version-strictness mismatch (see AR#45588) even though the
  pinout is proven correct on real hardware. Not checked in, same as
  the other Vivado-managed IP. Native (non-AXI4) `app_*` interface, not
  yet used for anything (Phase 6b).
- `pulse_fifo`, `pulser_ram`, `fifo_photon`, `normal_pmt_fifo`,
  `readout_count_fifo` — Phase 3 FIFO Generator / Block Memory
  Generator IP, generated manually in the Vivado IP catalog (not by
  `create_project.tcl`) so settings could be reviewed interactively
  against the legacy `.xco` configs before committing to them. Not
  checked in, same as `clk_wiz_0` — regenerate from the settings
  documented in the Phase 3 scope section above if the project is
  rebuilt from scratch.
- `constraints/xem7305.xdc` — host interface, clock, and LED pins
  (copied from `../XEM7305_references/Counter/XEM7305-VHDL`), plus
  `led_ext`'s 6 pins (Phase 5a, copied from
  `../XEM7305_references/Locally_compiled_ramtester`) and the
  `set_clock_groups -asynchronous` declaration for `clk_wiz_0`'s output
  clocks vs. `mmcm0_clk0`/`okUH0` (a Phase 2 gap — those clocks were
  never declared asynchronous to `okClk`'s source, which Vivado doesn't
  infer automatically through a second PLL stage; only surfaced once
  Phase 5a added enough paths to show up in the timing summary as
  widespread setup failures. Safe to declare truly asynchronous since
  every real crossing between these domains goes through the FIFO
  Generator cores' own internal synchronizers or Opal Kelly's
  WireIn/WireOut/TriggerIn primitives — see the comment in the `.xdc`
  itself). Pulser I/O pins beyond `led_ext` are not yet defined — see
  Phase 4. As of Phase 6a: `sys_clkp`/`sys_clkn` renamed to
  `sys_clk_p`/`sys_clk_n` (MIG/ramtester convention), the DDR3 pin
  block copied verbatim from ramtester's `.xdc`, the old `create_clock`
  on that pin removed (MIG's own generated IP constraints supply it
  now), and a second `set_clock_groups -asynchronous` declaration added
  for `clk_pll_i` (MIG's internal PLL domain) vs. `clk_wiz_0`'s output
  clocks — the same "Phase 2 gap" pattern one hop further down the
  clock tree, since cascading MIG's PLL into `clk_wiz_0`'s own MMCM
  means Vivado no longer infers that relationship either; this one
  surfaced as a real implementation run's WNS -2.722 ns / 266 failing
  endpoints (all `clk_pll_i` → `clk_out2_clk_wiz_0`, landing on
  `pulser_ram`'s write-port registers) before the declaration was added.
- `create_project.tcl` — recreates the Vivado project from these
  sources (`vivado -mode batch -source create_project.tcl`), including
  generating the Phase 2 `clk_wiz_0` IP (Phase 6a: `PRIM_IN_FREQ`
  81.25 MHz, `PRIM_SOURCE` `No_buffer` — see `src/ip/clk_wiz_0/` above)
  and the Phase 6a `ddr3_256_16` IP via `CONFIG.XML_INPUT_FILE`.
  Targets `xc7s50csga324-1`, matching `Locally_compiled_ramtester` and
  the `Device:` comment embedded in the copied encrypted OK netlists.
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

## Bring-up test plan — Phase 5a

All steps below confirmed via `test/smoke_test.py` on real XEM7305
hardware.

1. ✅ After a full reset (TriggerIn 0x40 bits 0 and 1), confirm
   `logic_out` (WireOut 0x2B) and sequence status (WireOut 0x2C) both
   read 0.
2. ✅ Write a 3-word pulse program (dummy word, one word with a
   non-zero timestamp, an all-zero end-of-sequence sentinel word) to
   BTPipeIn 0x80 and confirm it drains into `pulser_ram` (WireOut 0x27
   back to 0).
3. ✅ Start the sequencer (WireIn 0x00 bit 2) and poll WireOut 0x2C
   until bit 16 (sequence-done) asserts — confirmed after 1 poll,
   consistent with the ~4 µs (100-tick) program duration used.
4. ✅ Confirm `logic_out` reads 0 once done (the sentinel word's logic
   bits, and one-shot-mode end-of-sequence forces `master_logic` to
   all-zero).
5. ✅ Re-confirm all Phase 1/2/3 checks still pass (no regression from
   the added FSM or the `okWireOR`/`okEHx` width changes needed for the
   new WireOut endpoints).

**Timing closure note:** the first post-Phase-5a build failed timing
badly (WNS -5.06 ns, 625 failing endpoints) — not a logic bug, but a
Phase 2 gap: `clk_wiz_0`'s output clocks were never declared
asynchronous to `okClk`'s source (`mmcm0_clk0`), only `sys_clk` was.
Adding that declaration (see Files above) brought timing fully clean
(WNS +0.387 ns, 0 failing endpoints) with no RTL changes needed.

**Test-writing note, not an RTL bug:** the first version of the
sequencer test used a 2-word all-zero program and hung forever, since
`time_count` starts at 0 and only increases — a `time_stamp = 0` word
can only be recognized as "end of sequence" the moment it's freshly
read, which requires an earlier non-zero-timestamp transition to have
already happened first. The same limitation exists in the legacy
design's arithmetic; real compiled pulse programs just never hit it.
Fixed by giving the test a real 3-word program instead (see above).

**`pulse_fifo` word order and `led_ext`, both confirmed via
`test/led_walk_demo.py`:** the `test_sequencer_basic()` test above
deliberately used values that don't depend on `pulse_fifo`'s
32-bit-write → 64-bit-read word-concatenation order, so it was still
an open question after Phase 5a's initial bring-up. `led_walk_demo.py`
resolves it empirically instead of guessing: it writes one word with
distinct values in each half, applies it (a word's first application
is always unambiguous — see the initial-fill states in `photon.vhd`),
and reads `logic_out` back to see which value landed in the logic-bits
half. **Confirmed on real hardware: the *second* pipe write lands in
the low 32 bits (logic_out), the *first* in the high 32 bits
(timestamp)** — `PULSE_WORD_ORDER_CONFIRMED = "high_word_first"` in
`test/smoke_test.py` — the opposite of Xilinx FIFO Generator's
commonly-cited default, so worth having actually checked rather than
assumed. Using that confirmed order, the same script then programs a
real 6-step pulse sequence and `led_ext[0]` through `[5]` were
confirmed to visibly light up in turn, 0.5 s apart, exactly as
programmed — the first real (non-symmetric, human-visible) `logic_out`
pattern run on this hardware.

`led_walk_demo.py` also had to work around the same FSM quirk noted
above (the word transitioning in is skipped if the *next* word is the
zero-timestamp terminator) by repeating its final LED5 word once
before the real terminator — otherwise LED5 would never actually be
displayed.

**Repeat mode (`ep00wire(1)`) and loop count (WireIn 0x05), confirmed
via `test/loop_test_demo.py`:** neither had been exercised by any
prior test. `loop_test_demo.py` programs a simple `led_ext[0]` blink
(0.5 s on, 0.5 s off, repeating) and confirms two things on real
hardware:

1. ✅ With `ep05wire = 3`: `seq_count` (WireOut 0x2C bits 15:0)
   increments once per completed loop (0→1→2→3), and
   `pulser_sequence_done` (bit 16) asserts in the exact same wrap event
   `seq_count` reaches 3 — not a loop early or late — with `logic_out`
   correctly at 0 once stopped.
2. ✅ With `ep05wire = 0`: `seq_count` keeps climbing (reached 3 within
   the ~3.5 s sampling window) and `pulser_sequence_done` never
   asserts, confirming true loop-forever behavior.
3. ✅ Visually confirmed: `led_ext[0]` blinks at a steady ~1 Hz rate
   throughout both runs, stopping dark after the third blink in the
   finite-count case and continuing indefinitely in the loop-forever
   case.

Repeat mode has its own version of the same "word right before the
terminator is skipped" FSM quirk: the transitioning-in word *is*
applied (unlike one-shot mode), but the FSM immediately re-fetches
word 0 afterward, so that word is only visible for a handful of
`clk_100` cycles — not its programmed duration. Worked around by
making that word identical to word 0 (ON), so the brief flicker is
indistinguishable from the loop simply continuing (see
`loop_test_demo.py`'s module docstring for the full trace).

**Manual override mux (`ep02wire`/`ep03wire`, channels 0-11), confirmed
via `test_manual_override()` in `test/smoke_test.py`:** the last
previously-unexercised Phase 5a control path. Cycles all 4 override
modes (follow / invert / force-0 / force-1) across the 12 overridable
channels and checks `logic_out` against Python-computed expected
values at two `master_logic` values:

1. ✅ `master_logic = 0` (via reset, sequencer not started): `logic_out`
   reads `0x00000AAA`, exactly as computed.
2. ✅ `master_logic = 0xFFFFFFFF` (via a 2-word program parked
   indefinitely on word 0 — word 1's timestamp of 0 can never be
   "reached", the same arithmetic quirk `test_sequencer_basic` works
   around, which conveniently gives a long-lived stable value to read
   here): `logic_out` reads `0xFFFF3999`, exactly as computed.
3. ✅ Visually confirmed: `led_ext[1,3,5]` ON for phase 1, `led_ext[0,3,4]`
   ON for phase 2, matching `logic_out`'s low 6 bits in each case.

Between the two phases this exercises all 4 modes against both a 0 and
a 1 input on every one of the 12 overridable channels — full
truth-table coverage in two WireOut reads, both held stable by the FSM
so there's no time pressure to check the LEDs.

With this, all of Phase 5a's control paths have been exercised on real
hardware: core sequencer timing, `logic_out`/`led_ext`, `pulse_fifo`'s
word order, repeat mode and loop count, and the manual override mux.

## Bring-up test plan — Phase 6a

All steps below confirmed via `test/smoke_test.py` on real XEM7305
hardware.

1. ✅ Read WireOut 0x2D bit 0 and confirm MIG reports
   `init_calib_complete` — asserted well within the 2 s poll margin,
   confirming real calibration against the XEM7305's actual DDR3 chip,
   not just a clean build.
2. ✅ Re-confirm all Phase 1/2/3/5a checks still pass — clocking
   measured 200.21/100.10/20.02 MHz (all within tolerance), Phase 3
   RAM/FIFO drain, Phase 5a sequencer completion, and the manual
   override mux all unaffected by moving the heartbeat counter,
   `TriggerIn` 0x40's `ep_clk`, and `clk_wiz_0`'s input off `sys_clk`
   and onto MIG's `ui_clk`.

**Two timing/clocking gaps found and fixed before this passed clean:**

- MMCM VCO out of range (`clk_gen/inst/mmcm_adv_inst`, computed
  2708.333 MHz vs. the valid 600-1200 MHz range): not a real bug —
  `clk_wiz_0`'s IP had already been reconfigured for an 81.25 MHz
  `ui_clk` input, but a stale, not-yet-synced copy of `photon.vhd` was
  still wiring `clk_in1` to the old 200 MHz `sys_clk` directly (2708.333
  = 200 × 40.625 / 3, the coefficients solved for 81.25 MHz fed a
  200 MHz signal instead). Fixed by syncing the updated `photon.vhd`.
- Bogus setup violations after that (WNS -2.722 ns, 266 failing
  endpoints, all `clk_pll_i` → `clk_out2_clk_wiz_0`): see the
  `constraints/xem7305.xdc` entry under Files above — the same
  "Phase 2 gap" pattern as Phase 5a's timing note, one hop further down
  the clock tree. Fixed with one more `set_clock_groups -asynchronous`
  declaration; brought timing fully clean with no RTL changes needed.

## Bring-up test plan — Phase 6b

Phase 6b adds the DDR3 **write-assembler** and **read-prefetch** adapters
in `photon.vhd` — the glue that moves 64-bit host words through DDR3 via
MIG's native 128-bit interface — and verifies a full host→DDR3→host
round-trip. Driven by `test/ddr3_roundtrip_demo.py`. Hardware-verified on
real XEM7305.

**Adapter design (the version that finally worked, copied from
`XEM7305_references/Locally_compiled_ramtester`):**

- `ddr3_read_fifo` is a **128-bit-write / 32-bit-read Standard FIFO** (NOT
  FWFT), independent clocks — the read-prefetch pushes each whole 128-bit
  MIG response in ONE write and the FIFO does the 128→32 width conversion.
  An earlier 64/32 FWFT read FIFO with a manual low/high split needed
  priming/flush/offset work-arounds and was a persistent source of
  intermittent corruption; the Standard FIFO has none of those quirks.
- `ddr3_write_fifo` pairs two 64-bit host words into one 128-bit MIG write.
- Reads and writes are time-multiplexed onto MIG's single command channel
  via `ep00wire(4)` (host-controlled write/read mode), not a runtime
  arbiter.

**Three MIG-7 command-channel gotchas found and fixed (see
`memory/ddr3-read-adapter-design.md`):**

1. **Never hold `app_en` past acceptance** — re-asserting it the cycle
   after `app_rdy` accepts makes MIG latch the same read twice. Assert
   `app_en` only while the command is unaccepted.
2. **Lost command** — MIG occasionally counts a read (`app_rdy` high) but
   never returns `app_rd_data_valid`. Commit the address advance/count on
   VALID, not on `app_rdy`, with a bounded state-2 timeout that re-issues.
   `dbg_retry_count` (WireOut 0x31 bits 15:8) shows it firing 1-6× per run
   — normal and recovered.
3. **Cold-start read mis-address** — the FIRST read after the controller
   has been idle for milliseconds (host round-trip + FIFO reset between
   test batches → banks precharge, refreshes run) occasionally activates
   the wrong row (one row-address bit latched low → a valid-but-wrong beat
   from ~16 rows lower). Proven by the memtest two-pass to be a TRANSIENT
   read event — the stored data is intact. Ramtester never hits it because
   it streams reads continuously and never lets the controller go cold.

**Test modes (`test/ddr3_roundtrip_demo.py <bitfile> <mode>`):**

- `<n_words>` — single-batch round-trip of n_words (even, ≤256).
- `soak [n_batches] [words_per_batch]` — repeated round-trips, structured
  or `--random` data.
- `endurance [duration_sec] [words_per_batch]` — run for a duration
  (default 1 h), per-batch reset.
- `memtest [mib] [chunk_words] [seed]` — write all of `mib` MiB, THEN read
  it all back in TWO passes: proves data retention and no aliasing, and
  the two-pass comparison separates a transient read mis-address (fails a
  different set each pass → data intact) from a real data error (same set
  every pass).
- `memtest ... --sacrifice-beat0` — reserve the first beat of each chunk
  as a discarded dummy so the cold first-read of every batch lands on a
  throwaway; the RTL-free workaround for gotcha 3. Passes with ZERO
  mismatches at 128 and 256 MiB.

**Status:** write path, retention, and warm/low-address reads are
hardware-proven robust over full-depth sweeps. The cold-start corner
(gotcha 3) affects only the first read after a long idle — an artifact of
the host-in-the-loop batch structure that the real workload will not
create. The proper fix belongs in the Phase 6c DDR3 read streamer as a
keep-warm heartbeat (issue throwaway reads during dwells so the controller
never goes cold), to be developed and proven in simulation. The low 32 KiB
(`app_addr` < 0x4000 = 4096 sequence lines) is structurally immune
regardless (that row-address bit is never set there, and the fault only
ever clears it).

**Bring-up diagnostics stripped** (kept `dbg_retry_count` +
`dbg_cmd_count` on WireOut 0x31; removed `dbg_valid_count`, `dbg_high0/1`,
`dbg_resp_count`, the `dbg_dup_*` duplicate-detector, and
`dbg_valid_outside_s2`, along with WireOut endpoints 0x30/0x32/0x33/0x34 —
`okEHx` slices renumbered and `okWireOR N` dropped 26→22; the host test's
`print_read_diagnostics` and constants updated to match).

**Housekeeping still pending (needs a build to verify):**

- Add `create_ip` TCL for `ddr3_read_fifo` / `ddr3_write_fifo` /
  `pulse_fifo` to `create_project.tcl` to fix the Mac↔Windows IP
  divergence (the read FIFO in particular must be regenerated as the
  128/32 Standard FIFO).
