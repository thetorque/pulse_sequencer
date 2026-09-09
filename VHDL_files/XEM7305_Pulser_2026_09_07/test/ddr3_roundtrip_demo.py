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

Per-batch read command budget (WireIn 0x07): read-prefetch used to
gate purely on ddr3_read_rd_data_count, with no idea how many words
the host actually wanted -- during a batch's slow USB round trip it
would keep eagerly issuing MIG read commands the whole time, racing
rd_pf_addr ahead of wr_asm_addr by an unpredictable amount. Harmless
for a single self-contained batch, but fatal across multiple batches
sharing one reset epoch: a later batch's readback would fetch stale
memory instead of what it just wrote. read_words() now writes this
batch's read-command count (n_words/2) to WireIn 0x07 before entering
read mode; see rd_pf_issued/rd_pf_target's declaration comment in
photon.vhd.

Per-batch trailing flush: removing that overshoot also exposed a
second, related effect -- ddr3_read_rd_data_count plateaus at
2*(total_pushes-1) halves, not 2*total_pushes, meaning the MOST
RECENTLY pushed word never becomes visible until something else is
pushed after it (confirmed on hardware; same FWFT-lookahead mechanism
as the priming push's PG057 finding, just biting the tail of a batch
instead of the head -- the old eager overshoot always supplied that
"something else" for free). photon.vhd's read-prefetch now pushes one
more throwaway dummy after each batch's real commands finish
(rd_pf_flushed) to flush the batch's own last word into visibility.

Multi-batch continuation: as long as reset_ddr3() isn't called between
batches, wr_asm_addr/rd_pf_addr keep advancing, and every batch's
reconstruction uses the *same* offset -- each batch's trailing flush
doubles as the next batch's leading dummy, so there's always exactly
one dummy pair immediately before a batch's real data, whether that's
the once-ever priming push (batch 0) or the previous batch's own
trailing flush (every batch after). run_soak_test() strings many
batches together this way to walk further into DDR3's address space
than a single batch's FIFO depth allows, verifying each batch
immediately (in the spirit of the Locally_compiled_ramtester reference
design).

Usage:
    python ddr3_roundtrip_demo.py path/to/photon.bit [n_words] [--random[=SEED]]
    python ddr3_roundtrip_demo.py path/to/photon.bit soak [n_batches] [words_per_batch] [--random[=SEED]]

--random switches from the structured, easy-to-recognize test pattern
(constant high bits, small incrementing low bits) to full 64-bit
random words -- see make_test_words()'s docstring for why that
matters. The seed used is always printed so a failing run can be
reproduced with --random=SEED.

n_words/words_per_batch must be even. Practical ceilings:
ddr3_write_fifo's actual depth (~33 64-bit entries) bounds how many
words can be buffered before draining to MIG, and ddr3_read_fifo's
occupancy gate (<48 halves, see photon.vhd's rd_pf_state comment)
bounds how many words' worth of halves can accumulate in one batch
before read-prefetch stalls -- pushing past either ceiling is expected
to fail with a clear timeout, not silent corruption.

Requires Python 3 and the Opal Kelly `ok` FrontPanel Python module
(see smoke_test.py's docstring for how to point PYTHONPATH at it).
"""
import random
import struct
import sys
import time

import ok


PIPE_BLOCK_SIZE = 16  # bytes; matches the block size used elsewhere in this project

N_WORDS = 8  # must be even -- see module docstring

DDR3_READ_ENABLE_BIT = 1 << 4  # ep00wire(4)
DDR3_PTR_RESET_BIT = 1 << 5    # ep40wire(5)
RAM_PTR_RESET_BIT = 1 << 1     # ep40wire(1), reset alongside for a clean run

READ_BUDGET_WIRE = 0x07  # ep07wire: this batch's read-command count

PULSE_FIFO_WIRE = 0x27
DRAIN_POLL_ATTEMPTS = 50
DRAIN_POLL_INTERVAL = 0.01

DDR3_WRITE_STATUS_WIRE = 0x2E
DDR3_WRITE_IDLE_BIT = 1 << 5
WRITE_IDLE_POLL_ATTEMPTS = 100
WRITE_IDLE_POLL_INTERVAL = 0.01

DDR3_READ_STATUS_WIRE = 0x2F
DDR3_READ_IDLE_BIT = 1 << 16
DDR3_READ_COUNT_MASK = 0x3F  # ddr3_read_rd_data_count is bits 5:0 only -- must NOT
                             # overlap ddr3_read_empty (bit 14) / rd_pf_flushed (bit 15),
                             # which a wider 0xFFFF mask wrongly folded in (flushed is set
                             # after every batch, so the count read as >= 0x8000 and
                             # drain_read_fifo's "count < 4" stop check never fired ->
                             # infinite blocking block-reads -> hang)
DDR3_READ_PRIMED_BIT = 1 << 17     # DIAGNOSTIC (temporary): rd_pf_primed
DDR3_READ_ISSUED_SHIFT = 18        # DIAGNOSTIC (temporary): rd_pf_issued, bits 25:18
DDR3_READ_ISSUED_MASK = 0xFF
DDR3_READ_FLUSHED_BIT = 1 << 15    # rd_pf_flushed -- see photon.vhd's ep2Fwire comment
DDR3_READ_EMPTY_BIT = 1 << 14      # ddr3_read_empty -- see photon.vhd's ep2Fwire comment
BATCH_DONE_POLL_ATTEMPTS = 200
BATCH_DONE_POLL_INTERVAL = 0.01
NOT_EMPTY_POLL_ATTEMPTS = 200
NOT_EMPTY_POLL_INTERVAL = 0.01

DUP_STATUS_WIRE = 0x34  # DIAGNOSTIC (temporary): see photon.vhd's dbg_dup_count comment
VALID_COUNT_WIRE = 0x30  # DIAGNOSTIC (temporary): dbg_valid_count, rising edges of app_rd_data_valid
CMD_COUNT_WIRE = 0x31    # DIAGNOSTIC (temporary): dbg_cmd_count, MIG read commands issued
READ_POLL_ATTEMPTS = 200
READ_POLL_INTERVAL = 0.01
READ_IDLE_POLL_ATTEMPTS = 200
READ_IDLE_POLL_INTERVAL = 0.01

DDR3_CALIB_STATUS_WIRE = 0x2D  # ep2Dwire bit 0: MIG init_calib_complete
DDR3_CALIB_COMPLETE_BIT = 1
CALIB_POLL_ATTEMPTS = 500
CALIB_POLL_INTERVAL = 0.01


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
    wait_calib_complete(xem)
    return xem


def wait_calib_complete(xem):
    """Waits for MIG's init_calib_complete (WireOut 0x2D bit 0) before
    letting any test proceed. ConfigureFPGA() triggers MIG's DDR3
    calibration sequence; issuing app_* commands before it finishes is
    undefined behavior. This was never checked before -- a real gap,
    not just a diagnostic -- found while chasing intermittent
    data-path corruption that turned out to be timing-correlated
    (same seed, same host-side overhead before the first command,
    similarly likely to race calibration) rather than data-dependent."""
    for _ in range(CALIB_POLL_ATTEMPTS):
        xem.UpdateWireOuts()
        if xem.GetWireOutValue(DDR3_CALIB_STATUS_WIRE) & DDR3_CALIB_COMPLETE_BIT:
            print("  DDR3 calibration complete (WireOut 0x2D bit 0)  [OK]")
            return
        time.sleep(CALIB_POLL_INTERVAL)
    raise RuntimeError("DDR3 calibration (init_calib_complete, WireOut 0x2D bit 0) never completed")


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


def wait_batch_done(xem, target_commands):
    """Waits for read-prefetch to finish this batch's work: the priming
    push done (rd_pf_primed), all target_commands real commands issued
    (rd_pf_issued), the trailing flush done (rd_pf_flushed), and
    parked in state 0 with nothing left to do (rd_pf_idle). All four
    are pure ui_clk-domain state -- no clock-domain crossing -- unlike
    ddr3_read_rd_data_count, which was caught on hardware staying
    frozen at a stale value across a full 2-second poll window while
    dbg_cmd_count/dbg_valid_count clearly kept moving (its CDC
    synchronization into okClk can genuinely lock up). Once these four
    conditions hold, the batch's halves are available by construction
    (1 priming push + target_commands*2 real words + 1 trailing flush)
    -- no need to also poll the count to confirm it."""
    for _ in range(BATCH_DONE_POLL_ATTEMPTS):
        xem.UpdateWireOuts()
        status = xem.GetWireOutValue(DDR3_READ_STATUS_WIRE)
        primed = bool(status & DDR3_READ_PRIMED_BIT)
        issued = (status >> DDR3_READ_ISSUED_SHIFT) & DDR3_READ_ISSUED_MASK
        flushed = bool(status & DDR3_READ_FLUSHED_BIT)
        idle = bool(status & DDR3_READ_IDLE_BIT)
        if primed and flushed and idle and issued >= target_commands:
            return
        time.sleep(BATCH_DONE_POLL_INTERVAL)
    print_dup_diagnostics(xem)
    raise RuntimeError(
        f"read-prefetch never finished this batch (WireOut 0x2F) -- "
        f"primed={primed}, issued={issued}/{target_commands}, flushed={flushed}, idle={idle}")


def wait_read_not_empty(xem):
    """Sanity gate before ReadFromBlockPipeOut, on top of
    wait_batch_done(): confirming the *write side* finished pushing
    (rd_pf_primed/issued/flushed/idle) says nothing about whether that
    data has actually crossed into the read clock domain yet --
    calling ReadFromBlockPipeOut before it has crossed hangs (no
    software timeout on that call, confirmed on hardware). Unlike
    ddr3_read_rd_data_count, ddr3_read_empty is a single bit -- no
    "different bits resolve at different times" glitch risk -- so it's
    safe to gate on, the same way this design already trusts
    ddr3_write_empty elsewhere."""
    for _ in range(NOT_EMPTY_POLL_ATTEMPTS):
        xem.UpdateWireOuts()
        if not (xem.GetWireOutValue(DDR3_READ_STATUS_WIRE) & DDR3_READ_EMPTY_BIT):
            return
        time.sleep(NOT_EMPTY_POLL_INTERVAL)
    print_dup_diagnostics(xem)
    raise RuntimeError("ddr3_read_fifo still reports empty after read-prefetch finished (WireOut 0x2F bit 14)")


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
    ever-increasing addresses and this would never terminate. Returns
    (pre_count, pre_empty, blocks_drained) for the per-batch drift
    diagnostic (see read_words)."""
    xem.UpdateWireOuts()
    status = xem.GetWireOutValue(DDR3_READ_STATUS_WIRE)
    pre_count = status & DDR3_READ_COUNT_MASK
    pre_empty = bool(status & DDR3_READ_EMPTY_BIT)
    blocks_drained = 0
    buf = bytearray(PIPE_BLOCK_SIZE)
    while True:
        xem.UpdateWireOuts()
        count = xem.GetWireOutValue(DDR3_READ_STATUS_WIRE) & DDR3_READ_COUNT_MASK
        if count < PIPE_BLOCK_SIZE // 4:  # fewer than one block's worth of halves left
            return pre_count, pre_empty, blocks_drained
        n = xem.ReadFromBlockPipeOut(0xA3, PIPE_BLOCK_SIZE, buf)
        assert n == PIPE_BLOCK_SIZE, f"ReadFromBlockPipeOut returned {n}, expected {PIPE_BLOCK_SIZE}"
        blocks_drained += 1


def read_words(xem, n_words):
    """Switches to read mode, waits for this batch's real words (plus
    the leading dummy that precedes them -- the once-ever priming push
    for the very first batch, or the previous batch's own trailing
    flush for any later one -- and this batch's own trailing flush),
    reads them back as a list of n_words 64-bit integers, switches
    back to write mode, then drains any leftover prefetched words.

    Every batch uses the same reconstruction offset: read-prefetch's
    per-batch trailing flush (rd_pf_flushed in photon.vhd) guarantees
    something is always pushed immediately before, and immediately
    after, this batch's own real words, so the leading garbage pair is
    always exactly 2 halves regardless of which batch this is. See the
    module docstring's "Multi-batch continuation" section."""
    target_commands = n_words // 2
    xem.SetWireInValue(READ_BUDGET_WIRE, target_commands, 0xFFFFFFFF)
    xem.SetWireInValue(0x00, DDR3_READ_ENABLE_BIT, DDR3_READ_ENABLE_BIT)
    xem.UpdateWireIns()

    # +3 halves: halves[0] is a leftover/unused half before the
    # stream settles, and halves[1]/halves[2] reconstruct as a
    # (garbage) *whole* word -- the leading dummy's own low half plus
    # the next push's high half that structurally leaks into its
    # slot. That whole pair must be discarded, not just one half. See
    # module docstring.
    needed_halves = n_words * 2 + 3
    offset = 3
    # Gate on read-prefetch's own (non-CDC) completion state, not on
    # ddr3_read_rd_data_count -- see wait_batch_done()'s docstring.
    wait_batch_done(xem, target_commands)
    # Then confirm the data has actually crossed into the read clock
    # domain before calling ReadFromBlockPipeOut -- see
    # wait_read_not_empty()'s docstring.
    wait_read_not_empty(xem)

    total_bytes = needed_halves * 4
    if total_bytes % PIPE_BLOCK_SIZE:
        total_bytes += PIPE_BLOCK_SIZE - total_bytes % PIPE_BLOCK_SIZE
    buf = bytearray(total_bytes)
    n = xem.ReadFromBlockPipeOut(0xA3, PIPE_BLOCK_SIZE, buf)
    assert n == total_bytes, f"ReadFromBlockPipeOut returned {n}, expected {total_bytes}"

    halves = list(struct.unpack(f'<{total_bytes // 4}I', bytes(buf)))

    # Real word k's high half is at halves[offset + 2k], low half at
    # halves[offset + 1 + 2k].
    words = []
    for k in range(n_words):
        high = halves[offset + 2 * k]
        low = halves[offset + 1 + 2 * k]
        words.append((high << 32) | low)

    wait_read_idle(xem)
    xem.SetWireInValue(0x00, 0, DDR3_READ_ENABLE_BIT)
    xem.UpdateWireIns()
    pre_count, pre_empty, blocks_drained = drain_read_fifo(xem)
    # DIAGNOSTIC (temporary): per-batch drift. If drain removes a
    # variable number of blocks across batches, that's the read-window
    # misalignment source -- see the batch-N mismatch analysis.
    print(f"    [drain diag] pre-drain count={pre_count} empty={pre_empty} blocks_drained={blocks_drained}")

    return words


def print_dup_diagnostics(xem):
    """Reads WireOut 0x34 (see photon.vhd's dbg_dup_count declaration
    comment) and prints whether any MIG read command's response has
    ever bit-duplicated the *previous* command's response since the
    last reset_ddr3() -- and if so, whether that pair's addresses also
    matched (an address-advance bug) or differed (a data-path race)."""
    xem.UpdateWireOuts()
    status = xem.GetWireOutValue(DUP_STATUS_WIRE)
    dup_count = (status >> 1) & 0x7FFF
    addr_match = bool(status & 1)
    dup_at_cmd = (status >> 16) & 0xFFFF
    if dup_count == 0:
        print("  dup-response diagnostic: none detected (dbg_dup_count=0)")
    else:
        print(
            f"  dup-response diagnostic: dbg_dup_count={dup_count}, "
            f"most recent at dbg_cmd_count={dup_at_cmd}, "
            f"addr_match={addr_match} "
            f"({'same address -- address-advance bug' if addr_match else 'DIFFERENT address -- data-path race'})"
        )

    xem.UpdateWireOuts()
    valid_count = xem.GetWireOutValue(VALID_COUNT_WIRE) & 0xFF
    cmd_count = xem.GetWireOutValue(CMD_COUNT_WIRE) & 0xFF
    print(
        f"  app_rd_data_valid diagnostic: dbg_valid_count={valid_count}, "
        f"dbg_cmd_count={cmd_count} "
        f"({'MATCH -- one valid pulse per command' if valid_count == cmd_count else 'MISMATCH -- valid fired a different number of times than commands issued'})"
    )


def make_test_words(n, tag, rng=None):
    """n distinct 64-bit test words. With rng=None, a structured,
    easy-to-recognize pattern (tag in the high 16 bits, an index in
    the low bits) -- good for eyeballing a mismatch, but its mostly-
    zero low bits and constant high bits won't catch bit-position-
    specific faults (a stuck bit, bit-line crosstalk). With an rng
    (random.Random), full 64-bit random words instead -- pass a seeded
    rng for a reproducible run."""
    if rng is not None:
        return [rng.getrandbits(64) for _ in range(n)]
    return [0xA5A5_0000_0000_0000 | (tag << 16) | i for i in range(n)]


def run_soak_test(xem, n_batches, words_per_batch, rng=None):
    """Writes and immediately verifies n_batches batches of
    words_per_batch words each, without resetting pointers in between
    -- see module docstring's "Multi-batch continuation" section.
    Walks n_batches*words_per_batch*8 bytes deeper into DDR3's address
    space than a single batch's FIFO depth would otherwise allow.
    Stops at the first mismatch. rng: see make_test_words()."""
    print(f"\n--- DDR3 soak test: {n_batches} batches of {words_per_batch} words ---")
    reset_ddr3(xem)
    for batch in range(n_batches):
        test_words = make_test_words(words_per_batch, batch, rng)
        write_words(xem, test_words)
        readback_words = read_words(xem, words_per_batch)
        if readback_words != test_words:
            print(f"  batch {batch}: [MISMATCH]")
            print(f"    wrote:     " + ", ".join(f"{w:#018x}" for w in test_words))
            print(f"    read back: " + ", ".join(f"{w:#018x}" for w in readback_words))
            print_dup_diagnostics(xem)
            raise AssertionError(f"soak test failed at batch {batch}")
        print(f"  batch {batch}: [OK]")
    print(f"\nAll {n_batches} batches verified.")
    print_dup_diagnostics(xem)


def parse_random_flag(argv):
    """Extracts a trailing --random or --random=SEED flag from argv
    (any position), returning (remaining_argv, rng_or_None). Prints
    the seed used so a failing run can be reproduced exactly."""
    remaining = []
    seed = None
    use_random = False
    for arg in argv:
        if arg == "--random":
            use_random = True
        elif arg.startswith("--random="):
            use_random = True
            seed = int(arg.split("=", 1)[1])
        else:
            remaining.append(arg)
    if not use_random:
        return remaining, None
    if seed is None:
        seed = random.SystemRandom().randrange(2**32)
    print(f"  random data enabled, seed={seed} (pass --random={seed} to reproduce)")
    return remaining, random.Random(seed)


def main():
    argv, rng = parse_random_flag(sys.argv[1:])
    argv = [sys.argv[0]] + argv

    if len(argv) >= 3 and argv[2] == "soak":
        if len(argv) not in (3, 4, 5):
            sys.exit(f"Usage: {argv[0]} path/to/photon.bit soak [n_batches] [words_per_batch] [--random[=SEED]]")
        n_batches = int(argv[3]) if len(argv) >= 4 else 20
        words_per_batch = int(argv[4]) if len(argv) == 5 else 16
        if words_per_batch % 2 != 0:
            sys.exit("words_per_batch must be even -- see module docstring")
        xem = connect(argv[1])
        run_soak_test(xem, n_batches, words_per_batch, rng)
        return

    if len(argv) not in (2, 3):
        sys.exit(f"Usage: {argv[0]} path/to/photon.bit [n_words] [--random[=SEED]]")
    n_words = int(argv[2]) if len(argv) == 3 else N_WORDS
    if n_words % 2 != 0:
        sys.exit("n_words must be even -- see module docstring")

    xem = connect(argv[1])

    print("\n--- Phase 6b DDR3 write/read adapter round-trip test ---")
    reset_ddr3(xem)

    test_words = make_test_words(n_words, 0, rng)
    print(f"  Writing {n_words} test words: " + ", ".join(f"{w:#018x}" for w in test_words))
    write_words(xem, test_words)
    print("  pulse_fifo drained and ddr3 write path idle  [OK]")

    readback_words = read_words(xem, n_words)

    print("  Readback: " + ", ".join(f"{w:#018x}" for w in readback_words))
    status = "OK" if readback_words == test_words else "MISMATCH"
    print(f"  Round trip: [{status}]")
    assert readback_words == test_words, (
        f"readback {readback_words!r} does not match written {test_words!r}")

    print("\nAll checks completed.")


if __name__ == "__main__":
    main()
