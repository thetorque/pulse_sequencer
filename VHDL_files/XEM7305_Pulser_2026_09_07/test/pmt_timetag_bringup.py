#!/usr/bin/env python3
"""
pmt_timetag_bringup.py -- Phase 5 (PMT) m4b hardware bring-up for the
time-resolved photon timetagger (pmt_sim -> pmt_timetagger -> fifo_photon -> 0xA0).

Drives the on-FPGA synthetic PMT source at a known rate, records photon
timestamps for a detection window, and verifies the timestamps are spaced by
the expected interval. The source runs on clk_100 (period P cycles); the
timetagger runs on clk_200 (5 ns/tick), so consecutive timestamps differ by
exactly 2*P ticks (2 clk_200 per clk_100). Self-checking, no detector, no pin.

    python pmt_timetag_bringup.py path/to/photon.bit [period_cycles]

Endpoints (see photon.vhd Phase 5 m4b):
  WireIn  0x08 : bit1 = use synthetic source, bit2 = timetagger record enable
  WireIn  0x09 : synthetic-source period (clk_100 cycles per pulse)
  WireOut 0x28 : fifo_photon fill level (readable 32-bit-word count, bits 14:0)
  BTPipeOut 0xA0 : the photon timestamps (32-bit words, 5 ns ticks)
  TriggerIn 0x40 : bit0 = counter/datapath reset, bit3 = fifo_photon reset

As with 0xA1, 0xA0's ep_ready is tied high, so read ONLY whole 16-byte blocks
the fill wire reports, after stopping recording.
"""
import struct
import sys
import time

import ok
from ddr3_roundtrip_demo import connect

PMT_CTRL_WIRE   = 0x08
PMT_PERIOD_WIRE = 0x09
PHOTON_FILL_WIRE = 0x28         # fifo_photon rd_data_count (bits 14:0)
PHOTON_PIPE     = 0xA0
RESET_TRIG      = 0x40
RESET_COUNTER_BIT = 0
RESET_PHOTON_FIFO_BIT = 3       # fifo_photon reset (ep40wire(3))

SIM_EN_BIT    = 1 << 1
RECORD_EN_BIT = 1 << 2

PIPE_BLOCK_SIZE = 16            # BTPipeOut reads whole 16-byte (4-word) blocks

PERIOD = int(sys.argv[2]) if len(sys.argv) > 2 else 200   # clk_100 cycles/pulse
EXPECT_DIFF = 2 * PERIOD        # clk_200 ticks between consecutive timestamps
NTAGS = 12


def set_wire(xem, addr, value):
    xem.SetWireInValue(addr, value, 0xFFFFFFFF)
    xem.UpdateWireIns()


def read_wire(xem, addr):
    xem.UpdateWireOuts()
    return xem.GetWireOutValue(addr)


def fill_level(xem):
    return read_wire(xem, PHOTON_FILL_WIRE) & 0x7FFF     # 15-bit rd_data_count


def main():
    if len(sys.argv) < 2:
        sys.exit(f"usage: python {sys.argv[0]} path/to/photon.bit [period_cycles]")
    xem = connect(sys.argv[1])

    print(f"\n--- PMT timetagger bring-up: period={PERIOD} clk_100 cycles "
          f"-> expect {EXPECT_DIFF}-tick (5 ns) spacing ---")

    # clean start: stop, reset the photon FIFO and the counter/source/time base
    set_wire(xem, PMT_CTRL_WIRE, 0)
    xem.ActivateTriggerIn(RESET_TRIG, RESET_PHOTON_FIFO_BIT)
    xem.ActivateTriggerIn(RESET_TRIG, RESET_COUNTER_BIT)

    set_wire(xem, PMT_PERIOD_WIRE, PERIOD)

    # open the detection window: synthetic source + recording on
    set_wire(xem, PMT_CTRL_WIRE, SIM_EN_BIT | RECORD_EN_BIT)

    t0 = time.time()
    while fill_level(xem) < NTAGS:
        if time.time() - t0 > 5.0:
            sys.exit(f"  TIMEOUT: only {fill_level(xem)} timestamps after 5 s "
                     f"(timetagger not recording -- check ep08(2)/fifo_photon wiring)")
        time.sleep(0.005)

    # close the window so the fill is stable while we read
    set_wire(xem, PMT_CTRL_WIRE, 0)
    fill = fill_level(xem)
    n_words = (fill // 4) * 4
    print(f"  recorded {fill} timestamps; reading back {n_words}")

    buf = bytearray(n_words * 4)
    got = xem.ReadFromBlockPipeOut(PHOTON_PIPE, PIPE_BLOCK_SIZE, buf)
    if got != len(buf):
        sys.exit(f"  ReadFromBlockPipeOut returned {got}, expected {len(buf)}")
    tags = list(struct.unpack(f"<{n_words}I", bytes(buf)))

    print("  timestamps (5 ns ticks):", tags)
    diffs = [b - a for a, b in zip(tags, tags[1:])]
    print("  spacings:", diffs)
    errors = sum(1 for d in diffs if d != EXPECT_DIFF)
    if errors == 0 and len(diffs) >= 1:
        print(f"  RESULT: PASS -- every spacing == {EXPECT_DIFF} ticks "
              f"({EXPECT_DIFF * 5} ns)")
        return 0
    print(f"  RESULT: FAIL -- {errors} spacing(s) off expected {EXPECT_DIFF}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
