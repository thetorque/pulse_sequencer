# Phase 6c simulation — DDR3 line streamer (milestone 1)

Sim-first development of the block that lets the pulse-sequencer FSM read its
program from DDR3 instead of `pulser_ram`. This directory is **simulation
only** — nothing here is in the synthesized bitstream yet.

## What it is

`ddr3_line_streamer` streams 64-bit pulse-sequence lines out of DDR3 (via the
MIG native app interface) into a 128-write / 64-read independent-clocks
prefetch FIFO that the sequencer pops from. It reuses the proven Phase 6b
read-prefetch handshake and adds what the sequencer needs:

- **Autonomous refill** — keep the FIFO topped up from a sequential address
  walk starting at `BASE_ADDR` (no host command budget).
- **Keep-warm heartbeat** — while the FIFO is full the read engine would go
  idle; during long pulse dwells that lets the DDR3 controller go *cold* and
  the first read afterwards can mis-address (the Phase 6b cold-start corner).
  So while idle it issues a throwaway read to a **different bank** every
  `HEARTBEAT_CYCLES` and discards it, keeping the controller warm. This is the
  dynamic, data-independent version of the `--sacrifice-beat0` workaround.
- **Loop-back** — a `restart` pulse flushes the FIFO, rewinds to `BASE_ADDR`,
  and **drains any in-flight read** first (otherwise its in-order, pre-restart
  response would be pushed as line 0 of the rewound stream — a real bug found
  and fixed in sim).
- **Lost-command retry** — the Phase 6b bounded state-2 timeout, carried over.

## Files

| File | Role |
|---|---|
| `ddr3_line_streamer.vhd` | the streamer (synthesizable; the real design instantiates the Xilinx FIFO IP for `line_fifo_128x64`) |
| `line_fifo_128x64.vhd` | **sim model** of the 128/64 independent-clocks Standard FIFO |
| `mig_read_model.vhd` | **sim model** of the MIG app read interface + address-derived data |
| `tb_line_streamer.vhd` | testbench + scoreboard |
| `run_sim.sh` | GHDL run script |

## Running

```
./run_sim.sh
```
Expected tail: `ALL TESTS PASSED (retries=… heartbeats=…)`. See `run_sim.sh`
for the macOS GHDL dyld workaround and the xsim alternative.

The testbench (two clocks — ui_clk 81.25 MHz, seq_clk 100 MHz) checks: lines
arrive strictly in order (each line encodes its own index), no starvation at a
representative dwell, the heartbeat fires during a full-FIFO idle **without**
disturbing the stream, loop-back rewinds to line 0, and injected lost commands
are recovered with data still in order.

## What sim can and cannot prove

Simulation proves the streamer **logic** — prefetch, ordering, no-starvation,
loop-back, drain, retry. It **cannot** reproduce the cold-start row
mis-address (a silicon-timing effect), so the heartbeat's *effectiveness* is a
hardware property, to be confirmed on real hardware exactly as
`--sacrifice-beat0` was.

## Integration notes (for wiring into `photon.vhd`)

1. Replace `line_fifo_128x64` with a generated Xilinx `fifo_generator` IP
   (128-write / 64-read, independent clocks, Standard FIFO); add it to
   `create_project.tcl`. **Match the 64-bit half ordering** (low-first here) to
   the write-assembler's line packing on hardware, as the Phase 6b byte order
   was matched.
2. `restart` and `primed` cross the ui_clk↔seq_clk boundary — add pulse/level
   synchronizers at integration (the sim drives them in-domain).
3. The sequencer FSM (`photon.vhd` ~line 1040) already reads lines sequentially
   with a 2-line look-ahead; point its line source at this FIFO and drive
   `restart` from its infinite-loop path.
4. **Starvation ceiling** (measured by `tb_streamer_throughput`, model MIG
   read latency 24 ui_clk): sustained **~6 lines/µs ≈ 166 ns/line**. So dwells
   ≥ ~166 ns/line never starve; faster bursts down to 40 ns/line are buffered
   (~512 lines ≈ 27 µs) before starvation; and a sequence that fits in the
   FIFO (≤512 lines) can be pre-loaded whole for zero DDR reads during
   execution (no starvation at any dwell). Realistic pulse dwells (µs–ms) sit
   far above the floor, so the one-at-a-time engine suffices; pipelined
   (multi-outstanding) reads are a ~10× option reserved for sustained sub-µs
   streaming of sequences too large to pre-load. The real floor is set by the
   actual MIG latency — the M2 hardware self-test measures it.
