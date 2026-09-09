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

Word order -- overall sequence confirmed by construction, but the
32-bit split direction is empirically determined, not assumed:
each 64-bit word is written as two 32-bit pipe writes (first -> high
32 bits, second -> low 32 bits, the same PULSE_WORD_ORDER_CONFIRMED =
"high_word_first" convention already established in smoke_test.py for
pulse_fifo's 32-bit write side), and the write-assembler/read-prefetch
pipeline preserves the overall word sequence end to end (word N
written is word N read back, in order -- traced through the VHDL, not
just assumed). BUT ddr3_read_fifo is a natively asymmetric FIFO
(64-bit write / 32-bit read, see photon.vhd's ddr3_read_fifo component
comment for why -- an earlier hand-rolled splitter broke okBTPipeOut's
timing assumptions on real hardware), so which 32-bit half of each
64-bit word comes out of BTPipeOut 0xA3 *first* is Vivado's own
FIFO Generator convention, not something controlled in the VHDL. This
script determines it empirically first (determine_read_order(), same
approach as led_walk_demo.py's determine_word_order() for pulse_fifo)
rather than guessing.

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
DDR3_READ_IDLE_BIT = 1 << 16
DDR3_READ_COUNT_MASK = 0xFFFF  # bits below rd_pf_idle (bit 16); actual count is 6 bits wide
READ_POLL_ATTEMPTS = 200
READ_POLL_INTERVAL = 0.01
READ_IDLE_POLL_ATTEMPTS = 200
READ_IDLE_POLL_INTERVAL = 0.01


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


def wait_read_ready(xem, min_count):
    for _ in range(READ_POLL_ATTEMPTS):
        xem.UpdateWireOuts()
        count = xem.GetWireOutValue(DDR3_READ_STATUS_WIRE) & DDR3_READ_COUNT_MASK
        if count >= min_count:
            return count
        time.sleep(READ_POLL_INTERVAL)
    raise RuntimeError(
        f"ddr3_read_fifo never reached {min_count} words (WireOut 0x2F)")


def wait_read_idle(xem):
    """Must be checked before switching ep00wire(4) back to write mode
    -- see rd_pf_idle's declaration comment in photon.vhd for why."""
    for _ in range(READ_IDLE_POLL_ATTEMPTS):
        xem.UpdateWireOuts()
        status = xem.GetWireOutValue(DDR3_READ_STATUS_WIRE)
        if status & DDR3_READ_IDLE_BIT:
            return
        time.sleep(READ_IDLE_POLL_INTERVAL)
    raise RuntimeError("ddr3 read path never reported idle (WireOut 0x2F bit 16)")


def reset_ddr3(xem):
    xem.SetWireInValue(0x00, 0, DDR3_READ_ENABLE_BIT)
    xem.UpdateWireIns()
    xem.ActivateTriggerIn(0x40, 1)  # RAM_PTR_RESET_BIT
    xem.ActivateTriggerIn(0x40, 5)  # DDR3_PTR_RESET_BIT


def write_words(xem, words):
    """Writes `words` (must be even count) through BTPipeIn 0x80 and
    waits for both pulse_fifo and the ddr3 write path to drain."""
    if len(words) % 2 != 0:
        raise ValueError("word count must be even -- see module docstring")
    program = bytearray()
    for w in words:
        program += pack_word(w)
    if len(program) % PIPE_BLOCK_SIZE:
        program += bytearray(PIPE_BLOCK_SIZE - len(program) % PIPE_BLOCK_SIZE)
    n = xem.WriteToBlockPipeIn(0x80, PIPE_BLOCK_SIZE, program)
    assert n == len(program), f"WriteToBlockPipeIn returned {n}, expected {len(program)}"
    drain_pulse_fifo(xem)
    wait_write_idle(xem)


def drain_read_fifo(xem):
    """Reads (and discards) whatever's left in ddr3_read_fifo, in whole
    blocks. Only safe to call once read mode is off (ep00wire(4)=0) --
    otherwise read-prefetch keeps eagerly refilling it from
    ever-increasing addresses and this would never terminate."""
    buf = bytearray(PIPE_BLOCK_SIZE)
    while True:
        xem.UpdateWireOuts()
        count = xem.GetWireOutValue(DDR3_READ_STATUS_WIRE) & DDR3_READ_COUNT_MASK
        if count < PIPE_BLOCK_SIZE // 4:  # fewer than one block's worth of halves left
            return
        n = xem.ReadFromBlockPipeOut(0xA3, PIPE_BLOCK_SIZE, buf)
        assert n == PIPE_BLOCK_SIZE, f"ReadFromBlockPipeOut returned {n}, expected {PIPE_BLOCK_SIZE}"


def read_halves(xem, n_words):
    """Switches to read mode, waits for n_words to be ready, reads them
    back as a flat list of 32-bit halves (2 per word), switches back to
    write mode, then drains any leftover prefetched words so the next
    read phase starts from a clean ddr3_read_fifo -- see
    drain_read_fifo() docstring for why this ordering matters."""
    xem.SetWireInValue(0x00, DDR3_READ_ENABLE_BIT, DDR3_READ_ENABLE_BIT)
    xem.UpdateWireIns()

    wait_read_ready(xem, n_words * 2)  # WireOut 0x2F counts 32-bit halves

    total_bytes = n_words * 8  # 2x 32-bit halves per word, 4 bytes each
    if total_bytes % PIPE_BLOCK_SIZE:
        total_bytes += PIPE_BLOCK_SIZE - total_bytes % PIPE_BLOCK_SIZE
    buf = bytearray(total_bytes)
    n = xem.ReadFromBlockPipeOut(0xA3, PIPE_BLOCK_SIZE, buf)
    assert n == total_bytes, f"ReadFromBlockPipeOut returned {n}, expected {total_bytes}"

    result = list(struct.unpack(f'<{total_bytes // 4}I', bytes(buf)))[:n_words * 2]

    wait_read_idle(xem)
    xem.SetWireInValue(0x00, 0, DDR3_READ_ENABLE_BIT)
    xem.UpdateWireIns()
    drain_read_fifo(xem)

    return result


def determine_read_order(xem):
    """DIAGNOSTIC version: writes two words with clearly distinct,
    recognizable halves (no zeros, so a wrong value is easy to
    recognize by which word/half it actually came from) and prints
    all 4 halves read back, rather than just checking the first two --
    see the temporary diagnostic note in the module docstring."""
    print("\n--- Determining ddr3_read_fifo 32-bit split order (diagnostic) ---")
    reset_ddr3(xem)

    word0 = 0xAAAAAAAA_55555555  # high=0xAAAAAAAA, low=0x55555555
    word1 = 0x11112222_33334444  # high=0x11112222, low=0x33334444
    write_words(xem, [word0, word1])

    halves = read_halves(xem, 2)
    print(f"  Wrote word0 high={0xAAAAAAAA:#010x} low={0x55555555:#010x}")
    print(f"  Wrote word1 high={0x11112222:#010x} low={0x33334444:#010x}")
    print("  Readback halves: " + ", ".join(f"{h:#010x}" for h in halves))
    sys.exit("Diagnostic run -- inspect the halves above, not a real failure.")


def main():
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} path/to/photon.bit")
    if N_WORDS % 2 != 0:
        sys.exit("N_WORDS must be even -- see module docstring")

    xem = connect(sys.argv[1])

    low_first = determine_read_order(xem)

    print("\n--- Phase 6b DDR3 write/read adapter round-trip test ---")
    reset_ddr3(xem)

    # Distinct, easy-to-recognize 64-bit test patterns.
    test_words = [0xA5A5_0000_0000_0000 | i for i in range(N_WORDS)]
    print(f"  Writing {N_WORDS} test words: " + ", ".join(f"{w:#018x}" for w in test_words))
    write_words(xem, test_words)
    print("  pulse_fifo drained and ddr3 write path idle  [OK]")

    halves = read_halves(xem, N_WORDS)
    readback_words = []
    for i in range(0, len(halves), 2):
        a, b = halves[i], halves[i + 1]
        low, high = (a, b) if low_first else (b, a)
        readback_words.append((high << 32) | low)

    print("  Readback: " + ", ".join(f"{w:#018x}" for w in readback_words))
    status = "OK" if readback_words == test_words else "MISMATCH"
    print(f"  Round trip: [{status}]")
    assert readback_words == test_words, (
        f"readback {readback_words!r} does not match written {test_words!r}")

    print("\nAll checks completed.")


if __name__ == "__main__":
    main()
