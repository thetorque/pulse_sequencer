#!/usr/bin/env python3
"""
pmt_bringup.py -- Phase 5 (PMT) m2 hardware bring-up for the normal-mode
photon-counting datapath (pmt_sim -> pmt_counter -> normal_pmt_fifo -> 0xA1).

Drives the on-FPGA synthetic PMT source at a known rate and verifies the
per-window counts the counter pushes into normal_pmt_fifo. Because the source
is deterministic (one pulse every `period` clk_100 cycles) and the gate is
`gate_len` cycles, every steady-state window must report EXACTLY
gate_len // period counts -- a self-checking test with no real detector and no
input pin wired (the datapath's whole point).

    python pmt_bringup.py path/to/photon.bit

Endpoints (see photon.vhd Phase 5 m2):
  WireIn  0x08 : bit0 = counter enable, bit1 = use synthetic source
  WireIn  0x09 : synthetic-source period  (clk_100 cycles per pulse)
  WireIn  0x0A : collection gate length   (clk_100 cycles per window)
  WireOut 0x29 : normal_pmt_fifo fill level (readable 32-bit-word count)
  BTPipeOut 0xA1 : the per-window counts (32-bit words)
  TriggerIn 0x40 : bit0 = counter/datapath reset, bit2 = normal_pmt_fifo reset

NOTE: ep_ready on 0xA1 is tied high in this bitstream (no empty-gating), so we
read ONLY whole 16-byte blocks that the fill wire says are present, after
stopping the counter -- never more than is actually in the FIFO.
"""
import struct
import sys
import time

import ok
from ddr3_roundtrip_demo import connect   # ConfigureFPGA + MIG calib wait

PMT_CTRL_WIRE   = 0x08
PMT_PERIOD_WIRE = 0x09
PMT_GATE_WIRE   = 0x0A
FILL_WIRE       = 0x29          # normal_pmt_fifo rd_data_count (bits 9:0)
PMT_PIPE        = 0xA1
RESET_TRIG      = 0x40
RESET_COUNTER_BIT = 0           # pulser_counter_reset (clears counter + source)
RESET_FIFO_BIT    = 2           # normal_pmt_fifo reset

COUNT_EN_BIT = 1 << 0
SIM_EN_BIT   = 1 << 1

PIPE_BLOCK_SIZE = 16            # bytes; BTPipeOut reads whole 16-byte (4-word) blocks

# Test stimulus: 100 cycles/pulse and a 100000-cycle gate -> exactly 1000
# counts/window. At clk_100 = 100 MHz that is a 1 MHz source and a 1 ms gate.
PERIOD  = 100
GATE    = 100_000
EXPECT  = GATE // PERIOD        # = 1000 counts per steady window
WINDOWS = 12                    # collect this many, then read them back
SKIP    = 1                     # first window low by 1 (reset/sync startup)


def set_wire(xem, addr, value):
    xem.SetWireInValue(addr, value, 0xFFFFFFFF)
    xem.UpdateWireIns()


def read_wire(xem, addr):
    xem.UpdateWireOuts()
    return xem.GetWireOutValue(addr)


def pulse_trig(xem, bit):
    xem.ActivateTriggerIn(RESET_TRIG, bit)


def fill_level(xem):
    return read_wire(xem, FILL_WIRE) & 0x3FF   # 10-bit rd_data_count


def main():
    if len(sys.argv) != 2:
        sys.exit(f"usage: python {sys.argv[0]} path/to/photon.bit")
    xem = connect(sys.argv[1])

    print(f"\n--- PMT normal-count bring-up: period={PERIOD}, gate={GATE} "
          f"-> expect {EXPECT} counts/window ---")

    # clean start: stop, reset the FIFO and the counter/source
    set_wire(xem, PMT_CTRL_WIRE, 0)
    pulse_trig(xem, RESET_FIFO_BIT)
    pulse_trig(xem, RESET_COUNTER_BIT)

    # program the source period and collection gate
    set_wire(xem, PMT_PERIOD_WIRE, PERIOD)
    set_wire(xem, PMT_GATE_WIRE, GATE)

    # run: synthetic source + counter on
    set_wire(xem, PMT_CTRL_WIRE, SIM_EN_BIT | COUNT_EN_BIT)

    # wait for WINDOWS windows to land in the FIFO
    t0 = time.time()
    while fill_level(xem) < WINDOWS:
        if time.time() - t0 > 5.0:
            sys.exit(f"  TIMEOUT: only {fill_level(xem)} windows after 5 s "
                     f"(counter not pushing -- check ep08/ep09/ep0A wiring)")
        time.sleep(0.005)

    # stop counting so the fill level is stable while we read
    set_wire(xem, PMT_CTRL_WIRE, 0)
    fill = fill_level(xem)
    n_words = (fill // 4) * 4          # whole 16-byte blocks only
    print(f"  collected {fill} windows; reading back {n_words}")

    buf = bytearray(n_words * 4)
    got = xem.ReadFromBlockPipeOut(PMT_PIPE, PIPE_BLOCK_SIZE, buf)
    if got != len(buf):
        sys.exit(f"  ReadFromBlockPipeOut returned {got}, expected {len(buf)}")
    counts = list(struct.unpack(f"<{n_words}I", bytes(buf)))

    print("  window counts:", counts)
    errors = 0
    for i, c in enumerate(counts):
        if i < SKIP:
            continue
        if c != EXPECT:
            errors += 1
            print(f"    window {i}: {c} (expected {EXPECT})")
    if errors == 0:
        print(f"  RESULT: PASS -- every steady window == {EXPECT} counts")
        return 0
    print(f"  RESULT: FAIL -- {errors} window(s) off expected {EXPECT}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
