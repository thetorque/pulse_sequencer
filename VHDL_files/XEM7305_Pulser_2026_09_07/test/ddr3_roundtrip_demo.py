"""
ddr3_roundtrip_demo.py -- Phase 6b standalone bring-up test for the new
DDR3 write-assembler / read-prefetch adapters (../src/photon.vhd),
independent of pulser_ram and the Phase 5a sequencer FSM (that's
Phase 6c). Writes a small set of distinct 64-bit test patterns through
the *existing* BTPipeIn 0x80 -> pulse_fifo path (the same one Phase 5a's
tests already exercise -- the bring-up-only RAM-writer drain process
now feeds ddr3_write_fifo in lockstep with pulser_ram, see photon.vhd's
file header comment), then reads them back from DDR3 via the new
BTPipeOut 0xA3 and confirms an exact round trip.

Mode switching: MIG's app_addr/app_cmd/app_en command channel is shared
between the write-assembler and read-prefetch, so they're time-
multiplexed via ep00wire(4) (0=write mode, 1=read mode) rather than a
runtime arbiter. This script MUST confirm the write path is fully idle
(WireOut 0x2E bit 5) before switching to read mode -- switching early
would abandon an in-flight write command mid-transaction. See
photon.vhd's Phase 6b file header comment for the full explanation.

Even word count requirement: the write-assembler only completes a
burst after popping a *pair* of words (two 64-bit words -> one 128-bit
MIG write), so this script always writes an even count -- an odd count
would leave the write-assembler stuck waiting for a word that never
comes, and WireOut 0x2E bit 5 would never reassert.

Word order (both directions confirmed by construction here, not
empirically discovered): each 64-bit word is written as two 32-bit
pipe writes (first -> high 32 bits, second -> low 32 bits, the same
PULSE_WORD_ORDER_CONFIRMED = "high_word_first" convention already
established in smoke_test.py for pulse_fifo's 32-bit write side) and
the write-assembler pairs the first *popped* pulse_fifo word into the
burst's low 64 bits, the second into the high 64 bits. On readback, the
read-prefetch pushes the low 64 bits first, high 64 bits second, and
BTPipeOut 0xA3 splits each 64-bit word into low-32-bits-first,
high-32-bits-second (see photon.vhd's ddr3_read_datain/ddr3_read_pipe_half
comment) -- all explicit choices made in the VHDL, not FIFO-Generator
defaults, so there's no order ambiguity left to determine here.

Usage:
    python ddr3_roundtrip_demo.py path/to/photon.bit

Requires Python 3 and the Opal Kelly `ok` FrontPanel Python module
(see smoke_test.py's docstring for how to point PYTHONPATH at it).
"""
import struct
import sys
import time

import ok


PIPE_BLOCK_SIZE = 16  # bytes; matches the block size used elsewhere in this project

N_WORDS = 8  # must be even -- see module docstring

DDR3_READ_ENABLE_BIT = 1 << 4  # ep00wire(4)
DDR3_PTR_RESET_BIT = 1 << 5    # ep40wire(5)
RAM_PTR_RESET_BIT = 1 << 1     # ep40wire(1), reset alongside for a clean run

PULSE_FIFO_WIRE = 0x27
DRAIN_POLL_ATTEMPTS = 50
DRAIN_POLL_INTERVAL = 0.01

DDR3_WRITE_STATUS_WIRE = 0x2E
DDR3_WRITE_IDLE_BIT = 1 << 5
WRITE_IDLE_POLL_ATTEMPTS = 100
WRITE_IDLE_POLL_INTERVAL = 0.01

DDR3_READ_STATUS_WIRE = 0x2F
READ_COUNT_MASK = 0x1F  # 5 bits, 32-deep ddr3_read_fifo
READ_POLL_ATTEMPTS = 200
READ_POLL_INTERVAL = 0.01


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


def pack_word(value):
    """One 64-bit test word as two 32-bit pipe writes, using the
    confirmed pulse_fifo order: first write -> high 32 bits, second ->
    low 32 bits (PULSE_WORD_ORDER_CONFIRMED in smoke_test.py)."""
    high = struct.pack('<I', (value >> 32) & 0xFFFFFFFF)
    low = struct.pack('<I', value & 0xFFFFFFFF)
    return high + low


def drain_pulse_fifo(xem):
    for _ in range(DRAIN_POLL_ATTEMPTS):
        xem.UpdateWireOuts()
        if xem.GetWireOutValue(PULSE_FIFO_WIRE) == 0:
            return
        time.sleep(DRAIN_POLL_INTERVAL)
    raise RuntimeError("pulse_fifo never drained")


def wait_write_idle(xem):
    for _ in range(WRITE_IDLE_POLL_ATTEMPTS):
        xem.UpdateWireOuts()
        status = xem.GetWireOutValue(DDR3_WRITE_STATUS_WIRE)
        if status & DDR3_WRITE_IDLE_BIT:
            return
        time.sleep(WRITE_IDLE_POLL_INTERVAL)
    raise RuntimeError(
        "ddr3 write path never reported idle (WireOut 0x2E bit 5) -- "
        "check N_WORDS is even")


def wait_read_count(xem, expected):
    for _ in range(READ_POLL_ATTEMPTS):
        xem.UpdateWireOuts()
        count = xem.GetWireOutValue(DDR3_READ_STATUS_WIRE) & READ_COUNT_MASK
        if count >= expected:
            return count
        time.sleep(READ_POLL_INTERVAL)
    raise RuntimeError(
        f"ddr3_read_fifo never reached {expected} words (WireOut 0x2F)")


def main():
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} path/to/photon.bit")
    if N_WORDS % 2 != 0:
        sys.exit("N_WORDS must be even -- see module docstring")

    xem = connect(sys.argv[1])

    print("\n--- Phase 6b DDR3 write/read adapter round-trip test ---")

    # Reset: write mode, both address counters, ram write pointer too.
    xem.SetWireInValue(0x00, 0, DDR3_READ_ENABLE_BIT)
    xem.UpdateWireIns()
    xem.ActivateTriggerIn(0x40, 1)  # RAM_PTR_RESET_BIT
    xem.ActivateTriggerIn(0x40, 5)  # DDR3_PTR_RESET_BIT

    # Distinct, easy-to-recognize 64-bit test patterns.
    test_words = [0xA5A5_0000_0000_0000 | i for i in range(N_WORDS)]
    print(f"  Writing {N_WORDS} test words: " + ", ".join(f"{w:#018x}" for w in test_words))

    program = bytearray()
    for w in test_words:
        program += pack_word(w)
    if len(program) % PIPE_BLOCK_SIZE:
        program += bytearray(PIPE_BLOCK_SIZE - len(program) % PIPE_BLOCK_SIZE)
    n = xem.WriteToBlockPipeIn(0x80, PIPE_BLOCK_SIZE, program)
    assert n == len(program), f"WriteToBlockPipeIn returned {n}, expected {len(program)}"

    drain_pulse_fifo(xem)
    print("  pulse_fifo drained (WireOut 0x27 back to 0)  [OK]")

    wait_write_idle(xem)
    print("  ddr3 write path idle (WireOut 0x2E bit 5)  [OK]")

    # Switch to read mode.
    xem.SetWireInValue(0x00, DDR3_READ_ENABLE_BIT, DDR3_READ_ENABLE_BIT)
    xem.UpdateWireIns()

    wait_read_count(xem, N_WORDS)
    print(f"  ddr3_read_fifo reached {N_WORDS} words (WireOut 0x2F)  [OK]")

    total_bytes = N_WORDS * 8  # 2x 32-bit halves per word, 4 bytes each
    if total_bytes % PIPE_BLOCK_SIZE:
        total_bytes += PIPE_BLOCK_SIZE - total_bytes % PIPE_BLOCK_SIZE
    buf = bytearray(total_bytes)
    n = xem.ReadFromBlockPipeOut(0xA3, PIPE_BLOCK_SIZE, buf)
    assert n == total_bytes, f"ReadFromBlockPipeOut returned {n}, expected {total_bytes}"

    halves = struct.unpack(f'<{total_bytes // 4}I', bytes(buf))
    readback_words = []
    for i in range(0, len(halves), 2):
        low, high = halves[i], halves[i + 1]
        readback_words.append((high << 32) | low)
    readback_words = readback_words[:N_WORDS]

    print("  Readback: " + ", ".join(f"{w:#018x}" for w in readback_words))
    status = "OK" if readback_words == test_words else "MISMATCH"
    print(f"  Round trip: [{status}]")
    assert readback_words == test_words, (
        f"readback {readback_words!r} does not match written {test_words!r}")

    # Cleanup: back to write mode.
    xem.SetWireInValue(0x00, 0, DDR3_READ_ENABLE_BIT)
    xem.UpdateWireIns()

    print("\nAll checks completed.")


if __name__ == "__main__":
    main()
