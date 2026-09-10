"""
ddr3_backend.py -- canonical low-level DDR3 pipe primitives for the 2026
XEM7305 bitstream (connect, calibration wait, program write, verify readback).

This is the SINGLE SOURCE OF TRUTH for the intricate host<->DDR3 machinery: the
three MIG-7 read gotchas (app_en double-issue, lost-command retry, cold-start
row mis-address) and the calibration-race fix, all debugged and cleared on
silicon in Phase 6b/6c. It was lifted verbatim from the Phase 6b bring-up test
`VHDL_files/.../test/ddr3_roundtrip_demo.py` (M1.5) so that:

  * pulser3 is self-contained -- the driver no longer reaches into the FPGA
    test tree (the old _ddr3.py path-injection bridge), so the package can be
    deployed standalone on the experiment-control PC; and
  * there is exactly one copy -- ddr3_roundtrip_demo.py now imports these names
    from here instead of defining them, so the two can never drift.

`import ok` is at module top (this half genuinely needs the FrontPanel binding),
so importing this module requires the `ok` module -- pulser3.driver imports it
lazily (via _ddr3.py) to keep wiremap/sequence importable off the bench.

Test-only code (memtest / soak / endurance / patterns / CLI) intentionally
stayed in ddr3_roundtrip_demo.py -- only the reusable primitives moved here.
"""
import struct
import sys
import time

import ok


PIPE_BLOCK_SIZE = 16  # bytes; matches the block size used elsewhere in this project

DDR3_READ_ENABLE_BIT = 1 << 4  # ep00wire(4)
DDR3_PTR_RESET_BIT = 1 << 5    # ep40wire(5)
RAM_PTR_RESET_BIT = 1 << 1     # ep40wire(1), reset alongside for a clean run
DDR3_READ_FIFO_RESET_BIT = 1 << 6  # ep00wire(6): per-batch read-FIFO reset
READ_FIFO_RESET_HOLD = 0.0002  # seconds around the read-FIFO reset pulse; the
                               # UpdateWireIns USB round-trips already hold rst for
                               # ~1 ms (>> the FIFO's few-cycle minimum), so this
                               # is just a small margin, kept short for throughput

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

CMD_COUNT_WIRE = 0x31    # DIAGNOSTIC: dbg_cmd_count (bits 7:0) + dbg_retry_count (bits 15:8)
DUP_WIRE = 0x34          # DIAGNOSTIC (restored): dbg_dup_addr_match (bit 0),
                         # dbg_dup_count(14:0) (bits 15:1), dbg_dup_at_cmd (bits 31:16).
                         # Counts MIG read responses whose 128-bit data equals the
                         # immediately-preceding response -- a duplicate/extra beat.
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
    print_read_diagnostics(xem)
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
    status = xem.GetWireOutValue(DDR3_READ_STATUS_WIRE)
    issued = (status >> DDR3_READ_ISSUED_SHIFT) & DDR3_READ_ISSUED_MASK
    state = (status >> DDR3_READ_STATE_SHIFT) & DDR3_READ_STATE_MASK
    idle = bool(status & DDR3_READ_IDLE_BIT)
    print_read_diagnostics(xem)
    raise RuntimeError(
        f"ddr3_read_fifo still reports empty after read-prefetch finished (WireOut 0x2F bit 14) "
        f"-- issued={issued}, rd_pf_state={state}, idle={idle} "
        f"(issued=0 => budget latched 0; issued>0 => data not visible on read side)")


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


def _enter_read_mode(xem, target_commands):
    """Sets the read-command budget (ep07) then raises read mode (ep00
    bit 4), which latches the budget on its rising edge -- and verifies
    read-prefetch actually started. That latch samples a CDC-crossing
    multi-bit ep07, so it occasionally captures a stale 0 (issued stays
    0, read-prefetch idle in state 0). If that happens, drop read mode
    and re-latch. Self-healing so a rare mis-latch doesn't fail a run."""
    for attempt in range(6):
        xem.SetWireInValue(READ_BUDGET_WIRE, target_commands, 0xFFFFFFFF)
        xem.UpdateWireIns()  # commit budget first, let it settle
        xem.SetWireInValue(0x00, DDR3_READ_ENABLE_BIT, DDR3_READ_ENABLE_BIT)
        xem.UpdateWireIns()  # rising edge latches the (now-settled) budget
        # confirm read-prefetch started within ~150 ms
        for _ in range(15):
            xem.UpdateWireOuts()
            status = xem.GetWireOutValue(DDR3_READ_STATUS_WIRE)
            issued = (status >> DDR3_READ_ISSUED_SHIFT) & DDR3_READ_ISSUED_MASK
            idle = bool(status & DDR3_READ_IDLE_BIT)
            state = (status >> DDR3_READ_STATE_SHIFT) & DDR3_READ_STATE_MASK
            if issued > 0 or state != 0 or (issued >= target_commands and idle):
                return  # started (or already finished) -- budget latched fine
            time.sleep(0.01)
        # budget latched 0: read-prefetch never moved. Drop read mode and retry.
        xem.SetWireInValue(0x00, 0, DDR3_READ_ENABLE_BIT)
        xem.UpdateWireIns()
    # Fell through -- leave read mode on so wait_batch_done raises with detail.


def read_words(xem, n_words, reset_fifo=True):
    """Optionally resets the read FIFO so this batch starts empty,
    switches to read mode, waits for read-prefetch to issue n_words/2
    read commands (one 128-bit MIG response each), reads them back, and
    switches to write mode.

    reset_fifo (default True) pulses ddr3_read_fifo_rst before the
    batch, clearing the read FIFO and read-prefetch state. All callers
    currently keep it on: skipping it (an attempted throughput
    optimization) was found to wedge the second batch -- something in
    the read FIFO's state after a full drain still needs the reset --
    so the flag stays as a hook but defaults to the proven behavior.

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
    _enter_read_mode(xem, target_commands)

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


def print_read_diagnostics(xem):
    """Reads WireOut 0x31 and reports the lost-command retry count
    (dbg_retry_count, bits 15:8 -- nonzero means the MIG app_rdy
    edge-timing issue was hit and recovered) and the completed-command
    liveness counter (dbg_cmd_count, bits 7:0, 8-bit so it wraps). The
    0x30/0x34 bring-up diagnostics (valid-edge count and the duplicate-
    response detector) were removed from photon.vhd once the read path
    was proven; only these two counters remain."""
    xem.UpdateWireOuts()
    cmd31 = xem.GetWireOutValue(CMD_COUNT_WIRE)
    cmd_count = cmd31 & 0xFF
    retry_count = (cmd31 >> 8) & 0xFF   # dbg_retry_count, bits 15:8
    print(f"  read-command diagnostic: dbg_cmd_count={cmd_count} (8-bit, wraps)")
    print(f"  lost-command retry diagnostic: dbg_retry_count={retry_count} "
          f"({'no lost commands' if retry_count == 0 else 'MIG app_rdy edge-timing issue hit and recovered'})")
