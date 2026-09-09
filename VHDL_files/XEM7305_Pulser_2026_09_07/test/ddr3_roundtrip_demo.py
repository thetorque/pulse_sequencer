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

Read path (ramtester-style single-push): ddr3_read_fifo is a 128-bit
write / 32-bit read FWFT FIFO (matching Locally_compiled_ramtester's
fifo_w128_256_r32_1024). photon.vhd's read-prefetch pushes each read
command's WHOLE 128-bit MIG response in one write; the FIFO does the
128->32 conversion. So n_words/2 read commands produce exactly n_words
words -- no priming push, no trailing flush, no offset. Confirmed on
hardware: the FIFO serializes each 128-bit entry BIG-endian (MSB 32
bits first), and the write-assembler packs the pair's first word in
the low 64 bits and the second in the high 64, so the four halves of
entry e come out as [w1_hi, w1_lo, w0_hi, w0_lo]: w0 (= word 2e) =
(halves[4e+2] << 32) | halves[4e+3], w1 (= word 2e+1) =
(halves[4e+0] << 32) | halves[4e+1]. This replaced an earlier 64/32
FIFO whose asymmetric-FWFT look-ahead needed priming/flush/offset
work-arounds that were a persistent source of intermittent corruption.

Per-batch read command budget (WireIn 0x07): read-prefetch gates
issuance on this batch's command count (n_words/2), so rd_pf_addr
stays in lockstep with wr_asm_addr and never races ahead into
not-yet-written memory. read_words() writes it before entering read
mode; see rd_pf_issued/rd_pf_target's comment in photon.vhd.

Per-batch read-FIFO reset: read_words() pulses ddr3_read_fifo_rst
(ep00wire(6), see reset_read_fifo) before each batch, clearing the
read FIFO so every batch starts empty, with no inter-batch carryover.
The reset leaves rd_pf_addr/wr_asm_addr untouched, so the DDR3 address
walk still advances across batches. run_soak_test() strings many
batches together this way to walk further into DDR3's address space
than a single batch's FIFO depth allows, verifying each batch
immediately (in the spirit of the Locally_compiled_ramtester
reference design).

Usage:
    python ddr3_roundtrip_demo.py path/to/photon.bit [n_words] [--random[=SEED]]
    python ddr3_roundtrip_demo.py path/to/photon.bit soak [n_batches] [words_per_batch] [--random[=SEED]]
    python ddr3_roundtrip_demo.py path/to/photon.bit endurance [duration_sec] [words_per_batch] [--random[=SEED]]

endurance runs continuously for duration_sec (default 3600 = 1 hr),
sweeping the whole 512 MiB device by letting the DDR3 address advance
and wrap. It verifies every batch, prints progress every 15 s, counts
mismatches (re-syncing after each so an overnight run keeps going), and
prints PASS/FAIL at the end. Ctrl+C stops early with a summary. Use
--random for fresh random data each batch. words_per_batch defaults to
256 (must be even, <= 500 -- the read FIFO holds 256 128-bit entries).

--random switches from the structured, easy-to-recognize test pattern
(constant high bits, small incrementing low bits) to full 64-bit
random words -- see make_test_words()'s docstring for why that
matters. The seed used is always printed so a failing run can be
reproduced with --random=SEED.

n_words/words_per_batch must be even. Practical ceilings:
ddr3_write_fifo's actual depth (~33 64-bit entries) bounds how many
words can be buffered before draining to MIG, and ddr3_read_fifo's
write-side depth (256 128-bit entries) bounds how many read commands
can accumulate in one batch before read-prefetch stalls on full --
pushing past either ceiling is expected
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

# XEM7305 DDR3 is 512 MiB: 4 Gib x16 = 8 banks x 32768 rows x 1024 cols
# x 16 bits (from ddr3_256_16_mig.v: BANK_WIDTH=3, ROW_WIDTH=15,
# COL_WIDTH=10, MEM_DEVICE_WIDTH=16). Used only to report % coverage.
DDR3_TOTAL_BYTES = 512 * 1024 * 1024

DDR3_READ_ENABLE_BIT = 1 << 4  # ep00wire(4)
DDR3_PTR_RESET_BIT = 1 << 5    # ep40wire(5)
RAM_PTR_RESET_BIT = 1 << 1     # ep40wire(1), reset alongside for a clean run
DDR3_READ_FIFO_RESET_BIT = 1 << 6  # ep00wire(6): per-batch read-FIFO reset
READ_FIFO_RESET_HOLD = 0.002   # seconds to hold the read-FIFO reset asserted / recover

READ_BUDGET_WIRE = 0x07  # ep07wire: this batch's read-command count

PULSE_FIFO_WIRE = 0x27
DRAIN_POLL_ATTEMPTS = 50
DRAIN_POLL_INTERVAL = 0.01

DDR3_WRITE_STATUS_WIRE = 0x2E
DDR3_WRITE_IDLE_BIT = 1 << 5
WRITE_IDLE_POLL_ATTEMPTS = 100
WRITE_IDLE_POLL_INTERVAL = 0.01

DDR3_READ_STATUS_WIRE = 0x2F       # ep2Fwire, see photon.vhd's layout comment
DDR3_READ_IDLE_BIT = 1 << 16       # rd_pf_idle
DDR3_READ_ISSUED_SHIFT = 18        # rd_pf_issued, bits 25:18
DDR3_READ_ISSUED_MASK = 0xFF
DDR3_READ_EMPTY_BIT = 1 << 13      # ddr3_read_empty
DDR3_VALID_OUTSIDE_S2_BIT = 1 << 14  # DIAGNOSTIC: dbg_valid_outside_s2
DDR3_READ_STATE_SHIFT = 10         # DIAGNOSTIC: rd_pf_state, bits 12:10
DDR3_READ_STATE_MASK = 0x7
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
    """Waits for read-prefetch to finish this batch's work: all
    target_commands read commands issued (rd_pf_issued) and parked in
    state 0 with nothing left to do (rd_pf_idle). Both are pure
    ui_clk-domain state -- no clock-domain crossing. Once they hold,
    the batch's target_commands 128-bit responses have all been pushed
    into ddr3_read_fifo (one whole-response push each -- ramtester
    style, no priming/flush)."""
    for _ in range(BATCH_DONE_POLL_ATTEMPTS):
        xem.UpdateWireOuts()
        status = xem.GetWireOutValue(DDR3_READ_STATUS_WIRE)
        issued = (status >> DDR3_READ_ISSUED_SHIFT) & DDR3_READ_ISSUED_MASK
        idle = bool(status & DDR3_READ_IDLE_BIT)
        if idle and issued >= target_commands:
            return
        time.sleep(BATCH_DONE_POLL_INTERVAL)
    state = (status >> DDR3_READ_STATE_SHIFT) & DDR3_READ_STATE_MASK
    valid_outside_s2 = bool(status & DDR3_VALID_OUTSIDE_S2_BIT)
    print_dup_diagnostics(xem)
    raise RuntimeError(
        f"read-prefetch never finished this batch (WireOut 0x2F) -- "
        f"issued={issued}/{target_commands}, idle={idle}, "
        f"rd_pf_state={state}, valid_outside_capture_state={valid_outside_s2} "
        f"(state 2 = waiting for a valid that never came; valid_outside=True => a valid "
        f"was missed, False => MIG returned no valid for a counted command [lost command])")


def wait_read_not_empty(xem):
    """Sanity gate before ReadFromBlockPipeOut, on top of
    wait_batch_done(): confirming the *write side* finished pushing
    (rd_pf_issued/idle) says nothing about whether that
    data has actually crossed into the read clock domain yet --
    calling ReadFromBlockPipeOut before it has crossed hangs (no
    software timeout on that call, confirmed on hardware). Unlike
    ddr3_read_rd_data_count, ddr3_read_empty is a single bit -- no
    "different bits resolve at different times" glitch risk -- so it's
    safe to gate on, the same way ramtester and this design's
    ddr3_write_empty do."""
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


def reset_read_fifo(xem):
    """Pulses ddr3_read_fifo_rst (ep00wire(6)): clears the read FIFO and
    read-prefetch state (rd_pf_state/issued) WITHOUT
    touching the addresses, so each batch reads from a clean read-side
    state -- the identical starting condition batch 0 always read
    correctly from -- instead of relying on a fragile inter-batch FIFO
    carryover that raced across the ui_clk->okClk crossing. Must be
    called with read mode off (ep00wire(4)=0) and read-prefetch idle.
    The FIFO IP's rst is asynchronous; the hold/recover margins here are
    orders of magnitude longer than its few-cycle minimum."""
    xem.SetWireInValue(0x00, DDR3_READ_FIFO_RESET_BIT, DDR3_READ_FIFO_RESET_BIT)
    xem.UpdateWireIns()
    time.sleep(READ_FIFO_RESET_HOLD)
    xem.SetWireInValue(0x00, 0, DDR3_READ_FIFO_RESET_BIT)
    xem.UpdateWireIns()
    time.sleep(READ_FIFO_RESET_HOLD)


def read_words(xem, n_words, reset_fifo=True):
    """Optionally resets the read FIFO so this batch starts empty,
    switches to read mode, waits for read-prefetch to issue n_words/2
    read commands (one 128-bit MIG response each), reads them back, and
    switches to write mode.

    reset_fifo (default True) pulses ddr3_read_fifo_rst before the
    batch. It's belt-and-suspenders: each batch is already balanced
    (pushes and reads exactly n_words/2 entries, leaving the FIFO
    empty), so it's safe to skip -- the endurance test does, to avoid
    the reset's ~4 ms hold and sweep the device far faster.

    Ramtester-style single-push: each read command's whole 128-bit
    response is pushed into the 128-write/32-read ddr3_read_fifo in one
    write, so there is no priming push, no trailing flush, and no
    offset -- n_words/2 commands produce exactly n_words words, with no
    lookahead penalty to account for. Each 128-bit entry serializes to
    the read side as four little-endian 32-bit halves: [w0_lo, w0_hi,
    w1_lo, w1_hi] (the write-assembler packs the first word in the low
    64 bits, second in the high 64 -- see photon.vhd). Must be called
    with read mode off on entry (write_words leaves it there)."""
    # Clean read-side state for this batch -- must happen before read
    # mode is enabled and while read-prefetch is idle.
    if reset_fifo:
        reset_read_fifo(xem)

    target_commands = n_words // 2
    xem.SetWireInValue(READ_BUDGET_WIRE, target_commands, 0xFFFFFFFF)
    xem.SetWireInValue(0x00, DDR3_READ_ENABLE_BIT, DDR3_READ_ENABLE_BIT)
    xem.UpdateWireIns()

    # Gate on read-prefetch's own (non-CDC) completion state.
    wait_batch_done(xem, target_commands)
    # Then confirm the data has actually crossed into the read clock
    # domain before calling ReadFromBlockPipeOut (that call has no
    # software timeout) -- see wait_read_not_empty()'s docstring.
    wait_read_not_empty(xem)

    # n_words 64-bit words = n_words*8 bytes = (n_words/2) 16-byte
    # blocks -- always block-aligned for an even n_words, no padding.
    total_bytes = n_words * 8
    assert total_bytes % PIPE_BLOCK_SIZE == 0, "n_words must be even"
    buf = bytearray(total_bytes)
    n = xem.ReadFromBlockPipeOut(0xA3, PIPE_BLOCK_SIZE, buf)
    assert n == total_bytes, f"ReadFromBlockPipeOut returned {n}, expected {total_bytes}"

    halves = list(struct.unpack(f'<{total_bytes // 4}I', bytes(buf)))

    # Each 4 consecutive halves are one 128-bit MIG entry = two 64-bit
    # words. Confirmed on hardware: the FIFO serializes each 128-bit
    # word BIG-endian (MSB 32 bits first), and the write-assembler
    # packs the first word in the low 64 bits, the second in the high
    # 64 -- so the four halves come out as [w1_hi, w1_lo, w0_hi, w0_lo]
    # (w0 = first word of the pair, w1 = second).
    words = []
    for e in range(n_words // 2):
        b = 4 * e
        words.append((halves[b + 2] << 32) | halves[b + 3])  # w0 (low 64 of entry)
        words.append((halves[b + 0] << 32) | halves[b + 1])  # w1 (high 64 of entry)

    wait_read_idle(xem)
    xem.SetWireInValue(0x00, 0, DDR3_READ_ENABLE_BIT)
    xem.UpdateWireIns()

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
    cmd31 = xem.GetWireOutValue(CMD_COUNT_WIRE)
    cmd_count = cmd31 & 0xFF
    retry_count = (cmd31 >> 8) & 0xFF   # dbg_retry_count, bits 15:8
    print(
        f"  app_rd_data_valid diagnostic: dbg_valid_count={valid_count}, "
        f"dbg_cmd_count={cmd_count} "
        f"({'MATCH -- one valid pulse per command' if valid_count == cmd_count else 'MISMATCH -- valid fired a different number of times than commands issued'})"
    )
    print(f"  lost-command retry diagnostic: dbg_retry_count={retry_count} "
          f"({'no lost commands' if retry_count == 0 else 'MIG app_rdy edge-timing issue hit and recovered'})")


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


def _endurance_progress(xem, start, batch, total_words, mismatches, tag):
    """One progress/summary line for the endurance test."""
    elapsed = max(time.time() - start, 1e-6)
    data_bytes = total_words * 8
    mb_s = data_bytes / 1e6 / elapsed
    sweeps = data_bytes / DDR3_TOTAL_BYTES
    xem.UpdateWireOuts()
    retry8 = (xem.GetWireOutValue(CMD_COUNT_WIRE) >> 8) & 0xFF  # 8-bit, wraps -- liveness only
    print(f"  [{tag}] {elapsed:7.0f}s  batches={batch}  data={data_bytes/1e9:.2f} GB  "
          f"{mb_s:.2f} MB/s  ~{sweeps:.2f}x 512MiB sweeps  mismatches={mismatches}  "
          f"retry8={retry8}")


def run_endurance_test(xem, duration_sec, words_per_batch, rng=None):
    """Continuously writes+verifies batches for duration_sec, letting the
    DDR3 address sweep forward (and wrap) to exercise the whole 512 MiB
    device. Verifies every batch; counts mismatches but keeps going
    (re-syncing addresses after each) so one glitch doesn't end an
    overnight run. Ctrl+C stops early and still prints the summary.
    Skips the per-batch FIFO reset for speed -- see read_words()."""
    print(f"\n--- DDR3 endurance test: {duration_sec}s, {words_per_batch} words/batch ---")
    print(f"    each batch sweeps {words_per_batch*8} bytes; "
          f"a full 512 MiB sweep is {DDR3_TOTAL_BYTES // (words_per_batch*8)} batches")
    reset_ddr3(xem)
    reset_read_fifo(xem)  # once, up front -- not per batch
    start = time.time()
    batch = 0
    total_words = 0
    mismatches = 0
    report_interval = 15.0
    next_report = start + report_interval
    try:
        while time.time() - start < duration_sec:
            test_words = make_test_words(words_per_batch, batch & 0xFFFF, rng)
            offset = (total_words * 8) % DDR3_TOTAL_BYTES  # ~byte addr this batch hits
            write_words(xem, test_words)
            readback = read_words(xem, words_per_batch, reset_fifo=False)
            if readback != test_words:
                mismatches += 1
                bad = next(i for i in range(words_per_batch) if readback[i] != test_words[i])
                print(f"  [MISMATCH #{mismatches}] batch {batch}, ~offset 0x{offset:x}, "
                      f"first bad word #{bad}: wrote {test_words[bad]:#018x} "
                      f"read {readback[bad]:#018x}")
                print_dup_diagnostics(xem)
                reset_ddr3(xem)        # re-sync so one glitch doesn't cascade
                reset_read_fifo(xem)
                total_words = 0        # address restarts at 0
                batch += 1
                continue
            total_words += words_per_batch
            batch += 1
            if time.time() >= next_report:
                _endurance_progress(xem, start, batch, total_words, mismatches, "progress")
                next_report = time.time() + report_interval
    except KeyboardInterrupt:
        print("\n  (interrupted)")
    print("\n--- Endurance summary ---")
    _endurance_progress(xem, start, batch, total_words, mismatches, "final")
    if mismatches == 0:
        print(f"  RESULT: PASS -- {batch} batches, no mismatches")
    else:
        print(f"  RESULT: FAIL -- {mismatches} mismatch(es) over {batch} batches")
        raise AssertionError(f"endurance test saw {mismatches} mismatch(es)")


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

    if len(argv) >= 3 and argv[2] == "endurance":
        if len(argv) not in (3, 4, 5):
            sys.exit(f"Usage: {argv[0]} path/to/photon.bit endurance [duration_sec] [words_per_batch] [--random[=SEED]]")
        duration_sec = int(argv[3]) if len(argv) >= 4 else 3600
        words_per_batch = int(argv[4]) if len(argv) == 5 else 256
        if words_per_batch % 2 != 0:
            sys.exit("words_per_batch must be even -- see module docstring")
        if words_per_batch > 500:
            sys.exit("words_per_batch must be <= 500 (read FIFO holds 256 128-bit entries)")
        xem = connect(argv[1])
        run_endurance_test(xem, duration_sec, words_per_batch, rng)
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
