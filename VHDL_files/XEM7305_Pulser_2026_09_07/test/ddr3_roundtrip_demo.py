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
(WireOut 0x2E bit 5) before switching to read mode, and the read path
idle (WireOut 0x2F bit 16) before switching back -- see photon.vhd's
Phase 6b file header comment for the full explanation.

Even word count requirement: the write-assembler only completes a
burst after popping a *pair* of words (two 64-bit words -> one 128-bit
MIG write), so this script always writes an even count.

ddr3_read_fifo readback ordering: ddr3_read_fifo is a natively
asymmetric FIFO (64-bit write / 32-bit read, FWFT). Per AMD/Xilinx
PG057 ("Non-symmetric Aspect Ratio and First-Word Fall-Through"), a
FWFT FIFO has 2 extra read words available versus a standard FIFO --
for this 2:1 width ratio, that's exactly one extra 64-bit write's
worth of look-ahead built into the core itself, confirmed empirically:
every "high" 32-bit read structurally showed the *next* pushed entry's
high half rather than the current one, with the very first entry's own
high half permanently unavailable otherwise. photon.vhd's read-prefetch
absorbs this with a one-time throwaway priming push immediately after
reset, before any real data (see rd_pf_primed's declaration comment
there). That shifts the whole readback stream: the priming push itself
reconstructs as a (garbage) whole word -- its own low half plus the
NEXT push's high half, which structurally leaks into its slot -- so
the first two 32-bit halves ever read back after a reset must be
discarded as a pair, not just the first half. After that, each real
word's HIGH half comes first and its LOW half second -- the opposite
of a naive "low first" assumption, and only correct for the first read
session following a reset (ep40wire(5)), since the shift is a one-time
offset in the lifetime push sequence, not something re-established per
read call.

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
        f"ddr3_read_fifo never reached {min_count} halves (WireOut 0x2F)")


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


def read_words(xem, n_words):
    """Switches to read mode, waits for the priming push plus n_words
    real words to be ready, reads them back as a list of n_words 64-bit
    integers (see module docstring for the priming-push/shift
    reconstruction), switches back to write mode, then drains any
    leftover prefetched words. Only valid as the FIRST read call since
    the last reset_ddr3() -- see module docstring."""
    xem.SetWireInValue(0x00, DDR3_READ_ENABLE_BIT, DDR3_READ_ENABLE_BIT)
    xem.UpdateWireIns()

    # +3 halves: halves[0] is a leftover/unused half before the stream
    # settles, and halves[1]/halves[2] reconstruct as a (garbage) *whole*
    # word -- the priming push's own low half plus the next push's high
    # half that structurally leaks into its slot. That whole pair must be
    # discarded, not just one half. See module docstring.
    needed_halves = n_words * 2 + 3
    wait_read_ready(xem, needed_halves)

    total_bytes = needed_halves * 4
    if total_bytes % PIPE_BLOCK_SIZE:
        total_bytes += PIPE_BLOCK_SIZE - total_bytes % PIPE_BLOCK_SIZE
    buf = bytearray(total_bytes)
    n = xem.ReadFromBlockPipeOut(0xA3, PIPE_BLOCK_SIZE, buf)
    assert n == total_bytes, f"ReadFromBlockPipeOut returned {n}, expected {total_bytes}"

    halves = list(struct.unpack(f'<{total_bytes // 4}I', bytes(buf)))

    # halves[0] is unused, halves[1]/halves[2] reconstruct the priming
    # push itself (discarded). Real word k's high half is at
    # halves[3 + 2k], low half at halves[4 + 2k].
    words = []
    for k in range(n_words):
        high = halves[3 + 2 * k]
        low = halves[4 + 2 * k]
        words.append((high << 32) | low)

    wait_read_idle(xem)
    xem.SetWireInValue(0x00, 0, DDR3_READ_ENABLE_BIT)
    xem.UpdateWireIns()
    drain_read_fifo(xem)

    return words


def main():
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} path/to/photon.bit")
    if N_WORDS % 2 != 0:
        sys.exit("N_WORDS must be even -- see module docstring")

    xem = connect(sys.argv[1])

    print("\n--- Phase 6b DDR3 write/read adapter round-trip test ---")
    reset_ddr3(xem)

    # Distinct, easy-to-recognize 64-bit test patterns.
    test_words = [0xA5A5_0000_0000_0000 | i for i in range(N_WORDS)]
    print(f"  Writing {N_WORDS} test words: " + ", ".join(f"{w:#018x}" for w in test_words))
    write_words(xem, test_words)
    print("  pulse_fifo drained and ddr3 write path idle  [OK]")

    readback_words = read_words(xem, N_WORDS)

    print("  Readback: " + ", ".join(f"{w:#018x}" for w in readback_words))
    status = "OK" if readback_words == test_words else "MISMATCH"
    print(f"  Round trip: [{status}]")
    assert readback_words == test_words, (
        f"readback {readback_words!r} does not match written {test_words!r}")

    print("\nAll checks completed.")


if __name__ == "__main__":
    main()
