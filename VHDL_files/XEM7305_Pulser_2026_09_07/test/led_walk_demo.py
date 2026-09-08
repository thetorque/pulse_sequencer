"""
led_walk_demo.py -- turns on led_ext[0..5] one at a time, 0.5 s apart,
by programming a real pulse sequence through BTPipeIn 0x80 -> pulse_fifo
-> pulser_ram (Phase 3) and running it on the Phase 5a sequencer FSM.

This also resolves, empirically, an open question noted in README.md
and test/smoke_test.py (PULSE_WORD_ORDER_ASSUMED): which of pulse_fifo's
two 32-bit pipe writes lands in pulser_ram's low 32 bits (logic_out) vs.
high 32 bits (timestamp) when the 64-bit RAM word is assembled. Rather
than guess, this script writes one word with two distinct values, one
per half, applies it (a RAM word's *first* word is always applied
immediately on start -- no ambiguity there, see src/photon.vhd's
initial-fill states 0-4), and reads logic_out (WireOut 0x2B) back to
see which value ended up in the logic-bits half. That confirmed order
is then used to build the real LED-walk program.

Timing-model note: src/photon.vhd advances time_count once every 4
clk_100 cycles (40 ns/tick @ 100 MHz) -- see the Phase 5a header
comment there for why. 0.5 s = 12,500,000 ticks.

Sequencer quirk this program works around: the FSM peeks at the
*next* word's timestamp before applying the *current* word's logic
bits -- if that next word is the zero-timestamp end-of-sequence
sentinel, the current word's content is skipped entirely (jumps
straight to all-off instead). So the LED5 word is followed by a
harmless repeat of itself before the real terminator, otherwise LED5
would never actually be displayed. See README.md's Phase 5a bring-up
section for the full explanation (same issue test_sequencer_basic()
in smoke_test.py had to work around).

Usage:
    python led_walk_demo.py path/to/photon.bit

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
INTERVAL_S = 0.5
INTERVAL_TICKS = int(INTERVAL_S * 1e9 / NS_PER_TICK)  # 12,500,000

LOGIC_OUT_WIRE = 0x2B
SEQ_STATUS_WIRE = 0x2C
SEQ_DONE_BIT = 1 << 16
PULSE_FIFO_WIRE = 0x27
DRAIN_POLL_ATTEMPTS = 50
DRAIN_POLL_INTERVAL = 0.01


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
    xem.SetWireInValue(0x00, 0, 1 << 2)  # make sure pulser_start_bit is low first
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


def pack_word(logic_bits, timestamp, low_first):
    """One 64-bit pulser_ram word as two 32-bit pipe writes, in
    whichever order actually lands where (see determine_word_order)."""
    low = struct.pack('<I', logic_bits & 0xFFFFFFFF)
    high = struct.pack('<I', timestamp & 0x3FFFFFFF)  # 30-bit field, top 2 bits unused
    return (low + high) if low_first else (high + low)


def determine_word_order(xem):
    print("\n--- Determining pulse_fifo write order ---")
    reset_sequencer(xem)

    FIRST_WRITE = 0x0000000A
    SECOND_WRITE = 0x00000005
    # word 0: candidate (logic, timestamp) pair, applied immediately no
    # matter which order pulse_fifo uses -- that's what makes this a
    # clean diagnostic. word 1: terminator, so the sequencer can't run
    # off into whatever garbage is left in pulser_ram beyond this.
    program = bytearray(struct.pack('<II', FIRST_WRITE, SECOND_WRITE)) + bytearray(8)
    write_and_drain(xem, program)

    xem.SetWireInValue(0x00, 1 << 2, 1 << 2)
    xem.UpdateWireIns()
    time.sleep(0.01)  # word 0 applies within microseconds; this is generous
    xem.UpdateWireOuts()
    logic_out = xem.GetWireOutValue(LOGIC_OUT_WIRE)
    xem.SetWireInValue(0x00, 0, 1 << 2)
    xem.UpdateWireIns()

    print(f"  Wrote first_write={FIRST_WRITE:#x}, second_write={SECOND_WRITE:#x} as one word's two halves")
    print(f"  logic_out (0x2B) after word 0 applied = {logic_out:#010x}")
    if logic_out == FIRST_WRITE:
        print("  -> the FIRST pipe write lands in the LOW 32 bits (logic_out) -- 'low_word_first'")
        return True
    elif logic_out == SECOND_WRITE:
        print("  -> the SECOND pipe write lands in the LOW 32 bits (logic_out) -- 'high_word_first'")
        return False
    else:
        sys.exit(f"Unexpected logic_out {logic_out:#x} -- neither {FIRST_WRITE:#x} nor "
                  f"{SECOND_WRITE:#x}. Something else is wrong; not safe to guess and proceed.")


def main():
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} path/to/photon.bit")

    xem = connect(sys.argv[1])
    low_first = determine_word_order(xem)

    print("\n--- Programming LED walk: led_ext[0..5], 0.5 s apart ---")
    reset_sequencer(xem)

    # (logic_bits, timestamp) pairs. word 0 (LED0) is applied immediately
    # on start; each later word is applied when time_count reaches its
    # timestamp. The LED5 word is followed by a harmless repeat of
    # itself so it actually gets displayed (see module docstring) before
    # the real all-zero terminator.
    words = [(1 << i, INTERVAL_TICKS * i) for i in range(6)]
    words.append((1 << 5, INTERVAL_TICKS * 6))  # LED5 repeat
    words.append((0, 0))                        # terminator

    program = bytearray()
    for logic_bits, timestamp in words:
        program += pack_word(logic_bits, timestamp, low_first)
    total = write_and_drain(xem, program)
    print(f"  Wrote {len(words)} words ({total} bytes incl. any padding) to pipe 0x80")

    xem.SetWireInValue(0x00, 1 << 2, 1 << 2)
    xem.UpdateWireIns()
    print(f"  Started -- watch led_ext[0]..led_ext[5], ~{INTERVAL_S}s apart, ~{INTERVAL_S * 6}s total")

    deadline = time.time() + INTERVAL_S * 6 + 1.0  # generous margin past the expected finish
    done = False
    while time.time() < deadline:
        xem.UpdateWireOuts()
        if xem.GetWireOutValue(SEQ_STATUS_WIRE) & SEQ_DONE_BIT:
            done = True
            break
        time.sleep(0.05)

    if done:
        print("  Sequence done -- all LEDs should be off now.")
    else:
        print("  WARNING: sequence did not report done within the expected time.")

    xem.SetWireInValue(0x00, 0, 1 << 2)
    xem.UpdateWireIns()


if __name__ == "__main__":
    main()
