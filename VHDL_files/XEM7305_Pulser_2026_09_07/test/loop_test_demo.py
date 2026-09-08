"""
loop_test_demo.py -- exercises the Phase 5a sequencer's repeat-mode
control bits, never touched by smoke_test.py or led_walk_demo.py:
ep00wire(1) (pulser_infinite_loop, "repeat this program" enable) and
WireIn 0x05 (ep05wire, loop-count target -- 0 means loop forever,
non-zero means auto-stop after that many completed loops).

Programs a simple blink on led_ext[0]: ON for 0.5s, OFF for 0.5s,
repeat. Runs it two ways:
  1. finite loop count (ep05wire = LOOP_COUNT) -- confirms seq_count
     (WireOut 0x2C bits 15:0) increments once per loop and
     pulser_sequence_done (bit 16) asserts exactly when it reaches
     LOOP_COUNT, not before or after.
  2. loop count = 0 (loop forever) -- confirms seq_count keeps
     increasing and done never asserts, then stops it manually.

FSM quirk this works around (same one led_walk_demo.py's final LED5
step deals with, see that file and README.md's Phase 5a section): the
word transitioning in is only safely displayed for its full duration
if the *next* word isn't the zero-timestamp terminator. In repeat
mode specifically, a word sitting right before the terminator DOES
get momentarily applied, but the FSM immediately re-fetches word 0
afterward, so that word is visible for only a handful of clk_100
cycles -- not its full programmed duration. Worked around here by
making that word identical to word 0 (ON), so the brief flicker is
indistinguishable from the loop simply continuing.

Word order: pulse_fifo's 32-bit-write -> 64-bit-read concatenation was
confirmed empirically by led_walk_demo.py (PULSE_WORD_ORDER_CONFIRMED
in smoke_test.py): the *second* pipe write lands in the low 32 bits
(logic_out), the *first* in the high 32 bits (timestamp). Hardcoded
here rather than re-diagnosed, since this script isn't investigating
that question -- if the IP is ever regenerated, rerun
led_walk_demo.py's diagnostic step to reconfirm.

Usage:
    python loop_test_demo.py path/to/photon.bit

Requires Python 3 and the Opal Kelly `ok` FrontPanel Python module
(see smoke_test.py's docstring for how to point PYTHONPATH at it).
"""
import struct
import sys
import time

import ok


PIPE_BLOCK_SIZE = 16
CLK_100_HZ = 100e6
TICKS_PER_TIME_COUNT = 4  # see src/photon.vhd Phase 5a header comment
NS_PER_TICK = (1e9 / CLK_100_HZ) * TICKS_PER_TIME_COUNT  # 40 ns
HALF_PERIOD_S = 0.5
HALF_PERIOD_TICKS = int(HALF_PERIOD_S * 1e9 / NS_PER_TICK)  # 12,500,000

LOOP_COUNT = 3  # for the finite-loop-count test

LOGIC_OUT_WIRE = 0x2B
SEQ_STATUS_WIRE = 0x2C
SEQ_DONE_BIT = 1 << 16
SEQ_COUNT_MASK = 0xFFFF
PULSE_FIFO_WIRE = 0x27
DRAIN_POLL_ATTEMPTS = 50
DRAIN_POLL_INTERVAL = 0.01

PULSER_INFINITE_LOOP_BIT = 1 << 1  # ep00wire(1)
PULSER_START_BIT = 1 << 2          # ep00wire(2)


def connect(bit_path):
    xem = ok.FrontPanel()
    if xem.GetDeviceCount() < 1:
        sys.exit("No Opal Kelly devices found.")
    serial = xem.GetDeviceListSerial(0)
    xem.OpenBySerial(serial)
    print(f"Connected to device ID '{xem.GetDeviceID()}' (serial {serial})")
    result = xem.ConfigureFPGA(bit_path)
    if result:
        sys.exit(f"Failed to configure FPGA with {bit_path} (ConfigureFPGA returned {result})")
    print(f"Configured FPGA with {bit_path}")
    return xem


def reset_sequencer(xem):
    xem.SetWireInValue(0x00, 0, PULSER_START_BIT)  # make sure pulser_start_bit is low first
    xem.UpdateWireIns()
    xem.ActivateTriggerIn(0x40, 0)  # pulser_counter_reset
    xem.ActivateTriggerIn(0x40, 1)  # pulser_ram write-pointer reset


def drain_pulse_fifo(xem):
    for _ in range(DRAIN_POLL_ATTEMPTS):
        xem.UpdateWireOuts()
        if xem.GetWireOutValue(PULSE_FIFO_WIRE) == 0:
            return
        time.sleep(DRAIN_POLL_INTERVAL)
    raise RuntimeError("pulse_fifo never drained")


def write_and_drain(xem, program):
    if len(program) % PIPE_BLOCK_SIZE:
        program = program + bytearray(PIPE_BLOCK_SIZE - len(program) % PIPE_BLOCK_SIZE)
    n = xem.WriteToBlockPipeIn(0x80, PIPE_BLOCK_SIZE, program)
    assert n == len(program), f"WriteToBlockPipeIn returned {n}, expected {len(program)}"
    drain_pulse_fifo(xem)
    return len(program)


def pack_word(logic_bits, timestamp):
    """One 64-bit pulser_ram word as two 32-bit pipe writes, using the
    confirmed order: second write -> low 32 bits (logic), first write
    -> high 32 bits (timestamp)."""
    low = struct.pack('<I', logic_bits & 0xFFFFFFFF)
    high = struct.pack('<I', timestamp & 0x3FFFFFFF)  # 30-bit field, top 2 bits unused
    return high + low


def program_blink(xem, loop_count):
    reset_sequencer(xem)

    # word 0: LED0 ON, applied immediately, held for HALF_PERIOD_TICKS
    # word 1: LED0 OFF, applied normally (word 2 isn't the terminator),
    #         held for HALF_PERIOD_TICKS
    # word 2: LED0 ON again -- same content as word 0, so the brief
    #         flicker-then-rewrap this word gets in repeat mode (see
    #         module docstring) is indistinguishable from just looping
    # word 3: terminator (timestamp = 0)
    words = [
        (0x01, 0),
        (0x00, HALF_PERIOD_TICKS),
        (0x01, HALF_PERIOD_TICKS * 2),
        (0x00, 0),
    ]
    program = bytearray()
    for logic_bits, timestamp in words:
        program += pack_word(logic_bits, timestamp)
    write_and_drain(xem, program)

    xem.SetWireInValue(0x05, loop_count, 0xFFFF)
    xem.UpdateWireIns()
    xem.SetWireInValue(0x00, PULSER_INFINITE_LOOP_BIT, PULSER_INFINITE_LOOP_BIT)
    xem.UpdateWireIns()


def stop_sequencer(xem):
    xem.SetWireInValue(0x00, 0, PULSER_START_BIT)
    xem.UpdateWireIns()


def test_finite_loop_count(xem):
    print(f"\n--- Finite loop count: ep05wire = {LOOP_COUNT} ---")
    program_blink(xem, LOOP_COUNT)

    xem.SetWireInValue(0x00, PULSER_START_BIT, PULSER_START_BIT)
    xem.UpdateWireIns()
    print("  Started -- watch led_ext[0] blink; expecting it to stop after "
          f"{LOOP_COUNT} loops (~{LOOP_COUNT * HALF_PERIOD_S * 2:.1f}s)")

    last_seq_count = -1
    deadline = time.time() + LOOP_COUNT * HALF_PERIOD_S * 2 + 2.0  # generous margin
    done = False
    while time.time() < deadline:
        xem.UpdateWireOuts()
        status = xem.GetWireOutValue(SEQ_STATUS_WIRE)
        seq_count = status & SEQ_COUNT_MASK
        if seq_count != last_seq_count:
            print(f"  seq_count = {seq_count}")
            last_seq_count = seq_count
        if status & SEQ_DONE_BIT:
            done = True
            break
        time.sleep(0.02)

    stop_sequencer(xem)
    assert done, "sequencer never signaled done -- loop-count auto-stop may not be working"
    assert last_seq_count == LOOP_COUNT, (
        f"expected seq_count == {LOOP_COUNT} when done, got {last_seq_count}")
    xem.UpdateWireOuts()
    logic_out = xem.GetWireOutValue(LOGIC_OUT_WIRE)
    print(f"  Done after {last_seq_count} loops, as expected  [OK]")
    print(f"  logic_out (0x2B) after done = {logic_out:#010x} (expect 0)")
    assert logic_out == 0, f"expected logic_out 0 once done, got {logic_out:#x}"


def test_infinite_loop(xem):
    print("\n--- Infinite loop: ep05wire = 0 ---")
    program_blink(xem, 0)

    xem.SetWireInValue(0x00, PULSER_START_BIT, PULSER_START_BIT)
    xem.UpdateWireIns()
    watch_s = HALF_PERIOD_S * 2 * 3.5  # sample across ~3.5 loops
    print(f"  Started -- watch led_ext[0] keep blinking; sampling seq_count for {watch_s:.1f}s")

    last_seq_count = -1
    deadline = time.time() + watch_s
    while time.time() < deadline:
        xem.UpdateWireOuts()
        status = xem.GetWireOutValue(SEQ_STATUS_WIRE)
        seq_count = status & SEQ_COUNT_MASK
        if seq_count != last_seq_count:
            print(f"  seq_count = {seq_count}")
            last_seq_count = seq_count
        assert not (status & SEQ_DONE_BIT), (
            "sequencer signaled done, but ep05wire=0 should loop forever")
        time.sleep(0.02)

    stop_sequencer(xem)
    reset_sequencer(xem)  # leave the sequencer stopped and reset for whatever runs next
    print(f"  Reached seq_count = {last_seq_count} without stopping, as expected  [OK]")
    assert last_seq_count >= 2, (
        f"expected at least 2 completed loops in {watch_s:.1f}s, only saw {last_seq_count}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} path/to/photon.bit")

    xem = connect(sys.argv[1])
    test_finite_loop_count(xem)
    test_infinite_loop(xem)
    print("\nAll checks completed.")
