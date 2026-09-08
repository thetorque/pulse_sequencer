"""
Phase 1/2/3/5a bring-up smoke test for the XEM7305 pulser scaffold
(../src/photon.vhd). Exercises every endpoint address in the legacy map,
plus the Phase 2 clocking, Phase 3 RAM/FIFO, and Phase 5a sequencer
bring-up-only endpoints, and checks the fixed/echoed/measured values the
scaffold is expected to return.

Phase 3 note: BTPipeOut 0xA0/0xA1/0xA2 used to return a fixed test
pattern (Phase 1 stub); they now reach real FIFOs instead, but nothing
writes to those FIFOs yet (that's Phase 5's PMT-counting logic), so
this script now expects them to read back empty rather than checking
for a fixed pattern. BTPipeIn 0x80 now reaches a real pulse_fifo ->
pulser_ram write path, which this script exercises directly.

Phase 5a note: test_sequencer_basic() writes a minimal 3-word pulse
program (dummy, non-zero, all-zero terminator -- see the comment in
the function itself for why a 2-word all-zero program can never
terminate) and confirms the new sequencer FSM runs it to completion
(pulser_sequence_done asserts). The one non-zero word repeats the same
byte pattern in both 32-bit halves, so this test still doesn't need to
care about pulse_fifo's write order either way -- though that order is
now confirmed, see PULSE_WORD_ORDER_CONFIRMED below and
../test/led_walk_demo.py, which determines it empirically and uses it
to run a real (non-symmetric) pulse program.

test_manual_override() exercises the per-channel force/invert override
mux (ep02wire/ep03wire, channels 0-11) against two known master_logic
values (0 and all-ones) and asserts logic_out against a
Python-computed expected value for each -- see loop_test_demo.py and
led_walk_demo.py for the two other Phase 5a control paths (repeat
mode/loop count, and a real non-symmetric pulse program) exercised in
separate standalone scripts rather than here.

This is standalone and does NOT reuse Python_files/servers/pulser/ok.py —
that module is compiled against the old XEM6010-era FrontPanel SDK and
won't work with the XEM7305. Point PYTHONPATH (or copy the module next
to this script) at the `ok` module bundled with your installed FrontPanel
SDK instead (FrontPanelUSB install dir, API/python subfolder).

DOWNGRADED to the FP5-style flat API (ok.FrontPanel() directly exposing
GetDeviceCount/OpenBySerial/SetWireInValue/etc.), matching exactly how
Python_files/servers/pulser/api.py already talks to the board. This is
a deliberate debugging step: the FrontPanel GUI application confirmed
the bitstream/RTL itself responds correctly to WireIn 0x00, but the
first version of this script (written against the FP6 API --
ok.FrontPanelDevices() / GetFPGADataPortClassic(), see
https://docs.opalkelly.com/fpsdk/fp6-migration-guide/python/) ran with
no exceptions yet saw no effect. Since the FP6 wrapper and the FP5
wrapper likely resolve/bind the underlying okFrontPanel DLL
differently, reverting to the FP5 call surface tests whether the
problem is specific to how the FP6 Python binding loads the driver on
this Windows machine, rather than the design or Python itself.

Usage:
    python smoke_test.py path/to/photon.bit

Requires Python 3 and the Opal Kelly `ok` FrontPanel Python module.
"""
import os
import struct
import sys
import time

import ok


PIPE_BLOCK_SIZE = 16  # bytes; matches the block size used elsewhere in this project's api.py

# Phase 2 clocking bring-up: expected frequency (Hz) of each free-running
# counter exposed at WireOut 0x24-0x26 (see src/photon.vhd).
CLOCK_CHECKS = {0x24: 200e6, 0x25: 100e6, 0x26: 20e6}
CLOCK_MEASURE_SECONDS = 1.0
CLOCK_TOLERANCE = 0.05  # 5%; generous margin for wall-clock jitter over a 1s window

# Phase 3 RAM/FIFO bring-up: WireOut address reporting each FIFO's
# read-side occupancy (rd_data_count), see src/photon.vhd.
FIFO_STATUS = {"pulse_fifo": 0x27, "fifo_photon": 0x28,
               "normal_pmt_fifo": 0x29, "readout_count_fifo": 0x2A}
DRAIN_POLL_ATTEMPTS = 20
DRAIN_POLL_INTERVAL = 0.01  # seconds; pulse_fifo drains in low microseconds at 100 MHz, this is generous

# Phase 5a sequencer bring-up: logic_out readback and sequence-done/loop-count
# status, see src/photon.vhd WireOut 0x2B/0x2C.
LOGIC_OUT_WIRE = 0x2B
SEQ_STATUS_WIRE = 0x2C
SEQ_DONE_BIT = 1 << 16  # ep2Cwire bit 16, see photon.vhd
SEQ_POLL_ATTEMPTS = 50
SEQ_POLL_INTERVAL = 0.01

# CONFIRMED on real hardware via led_walk_demo.py's diagnostic step:
# pulse_fifo (32-bit write -> 64-bit read) concatenates the SECOND 32-bit
# pipe write into the RAM word's low bits (logic_out) and the FIRST into
# the high bits (timestamp) -- the opposite of Xilinx FIFO Generator's
# commonly-cited default (first write -> low bits), so this was worth
# actually checking rather than assuming. test_sequencer_basic() below
# still doesn't depend on this (its one non-zero word repeats the same
# value in both halves), but any future test constructing a real,
# non-symmetric pulse_fifo word should follow this order -- see
# led_walk_demo.py's pack_word() for a working example.
PULSE_WORD_ORDER_CONFIRMED = "high_word_first"  # first pipe write -> high 32 bits (timestamp)


def connect(bit_path):
    xem = ok.FrontPanel()
    if xem.GetDeviceCount() < 1:
        sys.exit("No Opal Kelly devices found.")
    serial = xem.GetDeviceListSerial(0)
    xem.OpenBySerial(serial)
    print(f"Connected to device ID '{xem.GetDeviceID()}' (serial {serial})")

    exists = os.path.exists(bit_path)
    size = os.path.getsize(bit_path) if exists else "n/a"
    print(f"Bitstream path: {bit_path!r} (repr, to reveal any hidden/odd characters)")
    print(f"  os.path.exists: {exists}, size: {size} bytes")

    result = xem.ConfigureFPGA(bit_path)
    if result:
        sys.exit(f"Failed to configure FPGA with {bit_path} "
                  f"(ConfigureFPGA returned {result} -- see "
                  f"https://docs.opalkelly.com/fpsdk/frontpanel-api/error-codes/ for what it means)")
    print(f"Configured FPGA with {bit_path}")
    return xem


def test_wire_in_leds(xem):
    print("\n--- WireIn 0x00 -> LEDs 0-2 ---")
    for bits in (0b001, 0b010, 0b100, 0b111, 0b000):
        xem.SetWireInValue(0x00, bits, 0x07)
        xem.UpdateWireIns()
        input(f"  Wrote WireIn 0x00 = {bits:#05b} -- check LEDs 0-2, press Enter to continue")


def test_wire_out_echo(xem):
    print("\n--- WireOut 0x21/0x22 echo check ---")
    xem.SetWireInValue(0x00, 0x5, 0x7)  # arbitrary known pattern on ep00wire
    xem.UpdateWireIns()
    xem.ActivateTriggerIn(0x40, 0)      # pulse a bit in ep40wire so it's nonzero-ish transiently

    xem.UpdateWireOuts()
    ep21 = xem.GetWireOutValue(0x21)
    ep22 = xem.GetWireOutValue(0x22)
    print(f"  WireOut 0x21 (should reflect WireIn 0x00) = {ep21:#010x}")
    print(f"  WireOut 0x22 (mirrors TriggerIn 0x40, a single-cycle pulse -- "
          f"expect this to read back as 0x00000000, that's normal, not a failure) = {ep22:#010x}")
    assert ep21 & 0x7 == 0x5, f"expected low 3 bits 0x5, got {ep21:#x}"
    print("  OK: WireOut 0x21 matches WireIn 0x00")


def test_pulse_fifo_drain(xem):
    print("\n--- BTPipeIn 0x80 -> pulse_fifo -> pulser_ram (Phase 3) ---")
    xem.UpdateWireOuts()
    occupancy = xem.GetWireOutValue(FIFO_STATUS["pulse_fifo"])
    print(f"  WireOut {FIFO_STATUS['pulse_fifo']:#04x} (pulse_fifo occupancy) before write = {occupancy}")
    assert occupancy == 0, (
        f"expected pulse_fifo empty before this test, got occupancy {occupancy} "
        f"-- a previous run may have left it stuck")

    pattern = bytearray(range(PIPE_BLOCK_SIZE))  # 16 distinct bytes, easy to eyeball on a scope/ILA later
    n = xem.WriteToBlockPipeIn(0x80, PIPE_BLOCK_SIZE, pattern)
    status = "OK" if n == PIPE_BLOCK_SIZE else "UNEXPECTED RETURN"
    print(f"  Wrote {n} bytes to pipe 0x80  [{status}]")
    assert n == PIPE_BLOCK_SIZE, f"WriteToBlockPipeIn returned {n}, expected {PIPE_BLOCK_SIZE}"

    for attempt in range(1, DRAIN_POLL_ATTEMPTS + 1):
        xem.UpdateWireOuts()
        occupancy = xem.GetWireOutValue(FIFO_STATUS["pulse_fifo"])
        if occupancy == 0:
            print(f"  WireOut {FIFO_STATUS['pulse_fifo']:#04x} back to 0 after {attempt} poll(s) "
                  f"-- pulse_fifo drained into pulser_ram  [OK]")
            break
        time.sleep(DRAIN_POLL_INTERVAL)
    else:
        raise AssertionError(
            f"pulse_fifo never drained: WireOut {FIFO_STATUS['pulse_fifo']:#04x} still reports "
            f"{occupancy} after {DRAIN_POLL_ATTEMPTS} polls -- the RAM-writer drain process may be stuck")


def test_sequencer_basic(xem):
    print("\n--- Phase 5a sequencer: run a minimal 3-word program to completion ---")

    # Make sure pulser_start_bit (WireIn 0x00 bit 2) is low before touching
    # the RAM below -- test_wire_out_echo leaves it set to 1, and if it's
    # still high here the sequencer would start fetching from pulser_ram
    # immediately on reset, racing against the pipe write that hasn't
    # happened yet.
    xem.SetWireInValue(0x00, 0, 1 << 2)
    xem.UpdateWireIns()

    # Full reset: sequencer state (bit 0) and the RAM write pointer (bit 1).
    xem.ActivateTriggerIn(0x40, 0)
    xem.ActivateTriggerIn(0x40, 1)
    xem.UpdateWireOuts()
    logic_out = xem.GetWireOutValue(LOGIC_OUT_WIRE)
    status = xem.GetWireOutValue(SEQ_STATUS_WIRE)
    print(f"  After reset: logic_out (0x2B) = {logic_out:#010x}, "
          f"seq status (0x2C) = {status:#010x} (expect both 0)")
    assert logic_out == 0, f"expected logic_out 0 after reset, got {logic_out:#x}"
    assert status == 0, f"expected seq status 0 after reset (done=0, seq_count=0), got {status:#x}"

    # Three 64-bit RAM words. time_count starts at 0 and only ever
    # increases, so a time_stamp=0 word can only ever be recognized as
    # "end of sequence" the moment it's freshly read -- which requires
    # at least one earlier, non-zero-timestamp transition to have
    # already happened (see the explanation this replaced: an all-zero
    # 2-word program can never terminate, because the very first
    # transition check needs time_count=0, but time_count has already
    # become 1 by the time that check first runs). So:
    #   word 0: dummy (never applied per the sequencer's own convention)
    #   word 1: non-zero, so the first transition can actually fire
    #   word 2: all-zero -- the real end-of-sequence sentinel
    # word 1 writes the SAME small value (100) to both of its 32-bit
    # halves, so this test doesn't need to care about pulse_fifo's write
    # order (now confirmed, see PULSE_WORD_ORDER_CONFIRMED above) --
    # whichever half becomes the timestamp reads back 100 -- small
    # enough to finish in ~4 us
    # (100 ticks * 40 ns), not the ~674 ms an earlier, badly-chosen
    # "order-robust" value (0x01010101) would have caused. This does
    # assume standard little-endian packing *within* each 32-bit write
    # (first byte sent = LSB) -- a much more standard, lower-risk
    # assumption than the inter-word ordering this sidesteps. A
    # trailing all-zero word 3 pads the total to 32 bytes (2 blocks of
    # PIPE_BLOCK_SIZE); it's never read since the sequence already ends
    # at word 2.
    nonzero_half = struct.pack('<I', 100)
    program = bytearray(8) + nonzero_half * 2 + bytearray(16)
    n = xem.WriteToBlockPipeIn(0x80, PIPE_BLOCK_SIZE, program)
    assert n == len(program), f"WriteToBlockPipeIn returned {n}, expected {len(program)}"
    print(f"  Wrote {n} bytes (4 RAM words: dummy, non-zero, zero terminator, zero padding) to pipe 0x80  [OK]")

    for attempt in range(1, DRAIN_POLL_ATTEMPTS + 1):
        xem.UpdateWireOuts()
        occupancy = xem.GetWireOutValue(FIFO_STATUS["pulse_fifo"])
        if occupancy == 0:
            break
        time.sleep(DRAIN_POLL_INTERVAL)
    else:
        raise AssertionError("pulse_fifo never drained before starting the sequencer test")

    # Start the sequencer (WireIn 0x00 bit 2, ep00wire(2) = pulser_start_bit).
    xem.SetWireInValue(0x00, 1 << 2, 1 << 2)
    xem.UpdateWireIns()
    print("  Started sequencer (WireIn 0x00 bit 2)")

    for attempt in range(1, SEQ_POLL_ATTEMPTS + 1):
        xem.UpdateWireOuts()
        status = xem.GetWireOutValue(SEQ_STATUS_WIRE)
        if status & SEQ_DONE_BIT:
            print(f"  WireOut 0x2C reports sequence done after {attempt} poll(s)  [OK]")
            break
        time.sleep(SEQ_POLL_INTERVAL)
    else:
        raise AssertionError(
            f"sequencer never signaled done: WireOut {SEQ_STATUS_WIRE:#04x} still reports "
            f"{status:#x} after {SEQ_POLL_ATTEMPTS} polls -- the FSM may be stuck")

    logic_out = xem.GetWireOutValue(LOGIC_OUT_WIRE)
    print(f"  logic_out (0x2B) after done = {logic_out:#010x} (expect 0, the sentinel word's logic bits)")
    assert logic_out == 0, f"expected logic_out 0 once done, got {logic_out:#x}"

    # Housekeeping: clear the start bit so later tests don't find the
    # sequencer still marked "running".
    xem.SetWireInValue(0x00, 0, 1 << 2)
    xem.UpdateWireIns()


def test_manual_override(xem):
    print("\n--- Manual override mux (ep02wire/ep03wire, channels 0-11) ---")

    # Cycle all 4 override modes across channels 0-11 (4 repeats of the
    # 4-mode pattern): (ep02,ep03) = (0,0)=follow master_logic,
    # (0,1)=invert, (1,0)=force 0, (1,1)=force 1. This gives
    # ep02wire(11:0)=0xCCC, ep03wire(11:0)=0xAAA (verified: each nibble
    # is 1100/1010, i.e. mode n%4 in order for every group of 4 bits).
    xem.SetWireInValue(0x02, 0xCCC, 0xFFF)
    xem.SetWireInValue(0x03, 0xAAA, 0xFFF)
    xem.UpdateWireIns()

    # Phase A: master_logic held at 0 via reset, sequencer not started.
    # follow/force-0 modes read 0; invert/force-1 modes read 1 (since
    # NOT 0 = 1) -- computed expected value: 0x00000AAA (channels 0-11
    # only; nothing else drives logic_out's other bits when
    # master_logic is 0).
    xem.SetWireInValue(0x00, 0, 1 << 2)
    xem.UpdateWireIns()
    xem.ActivateTriggerIn(0x40, 0)
    xem.ActivateTriggerIn(0x40, 1)
    xem.UpdateWireOuts()
    logic_out = xem.GetWireOutValue(LOGIC_OUT_WIRE)
    expected = 0x00000AAA
    print(f"  master_logic=0: logic_out (0x2B) = {logic_out:#010x} (expect {expected:#010x})")
    assert logic_out == expected, f"expected {expected:#x} with master_logic=0, got {logic_out:#x}"

    # Phase B: drive master_logic to all-ones via a 2-word program. Word
    # 0 is applied immediately and unconditionally (the initial-fill
    # path, not the "peek at next word" transition logic), and since
    # word 1's own timestamp is 0, time_count can never "reach" it (see
    # test_sequencer_basic's comment for why) -- so the sequencer just
    # stays parked showing word 0's value indefinitely. That's exactly
    # what this test wants: a long-lived, stable non-zero master_logic
    # to read at leisure, not a bug here. Uses the confirmed pulse_fifo
    # word order (PULSE_WORD_ORDER_CONFIRMED): first write -> high 32
    # bits (timestamp, ignored for word 0 either way), second write ->
    # low 32 bits (logic).
    program = struct.pack('<II', 0, 0xFFFFFFFF) + bytearray(8)
    n = xem.WriteToBlockPipeIn(0x80, PIPE_BLOCK_SIZE, program)
    assert n == len(program), f"WriteToBlockPipeIn returned {n}, expected {len(program)}"
    for attempt in range(1, DRAIN_POLL_ATTEMPTS + 1):
        xem.UpdateWireOuts()
        if xem.GetWireOutValue(FIFO_STATUS["pulse_fifo"]) == 0:
            break
        time.sleep(DRAIN_POLL_INTERVAL)
    else:
        raise AssertionError("pulse_fifo never drained before the override-mux test's second phase")

    xem.SetWireInValue(0x00, 1 << 2, 1 << 2)
    xem.UpdateWireIns()
    time.sleep(0.01)  # word 0 applies within microseconds; this is generous
    xem.UpdateWireOuts()
    logic_out = xem.GetWireOutValue(LOGIC_OUT_WIRE)
    # channels 0-11: follow/force-1 modes read 1, invert/force-0 modes
    # read 0 (0x999); bits 12/13 = master_logic(18)/(19) = 1 (DDS
    # step/reset, no override); bits 14/15 fixed 0; bits 16-31 =
    # master_logic(31:16) = 0xFFFF (straight passthrough, no override).
    expected = 0xFFFF3999
    print(f"  master_logic=0xFFFFFFFF: logic_out (0x2B) = {logic_out:#010x} (expect {expected:#010x})")
    assert logic_out == expected, f"expected {expected:#x} with master_logic=0xFFFFFFFF, got {logic_out:#x}"

    # Housekeeping: stop and reset the sequencer, and put ep02wire/
    # ep03wire back to "normal" (no override) so later tests see
    # logic_out follow master_logic unmodified.
    xem.SetWireInValue(0x00, 0, 1 << 2)
    xem.UpdateWireIns()
    xem.ActivateTriggerIn(0x40, 0)
    xem.ActivateTriggerIn(0x40, 1)
    xem.SetWireInValue(0x02, 0, 0xFFF)
    xem.SetWireInValue(0x03, 0, 0xFFF)
    xem.UpdateWireIns()


def test_pipe_out_empty(xem):
    print("\n--- BTPipeOut 0xA0-0xA2 (Phase 3: real FIFOs, no producer yet) ---")
    pipe_addrs = {0xA0: "fifo_photon", 0xA1: "normal_pmt_fifo", 0xA2: "readout_count_fifo"}
    for pipe_addr, fifo_name in pipe_addrs.items():
        buf = bytearray(PIPE_BLOCK_SIZE)
        n = xem.ReadFromBlockPipeOut(pipe_addr, PIPE_BLOCK_SIZE, buf)
        status = "OK" if n == PIPE_BLOCK_SIZE else "UNEXPECTED RETURN"
        print(f"  Pipe {pipe_addr:#04x} ({fifo_name}): read {n} bytes  [{status}]")
        assert n == PIPE_BLOCK_SIZE, f"ReadFromBlockPipeOut on {pipe_addr:#04x} returned {n}"

        status_addr = FIFO_STATUS[fifo_name]
        xem.UpdateWireOuts()
        occupancy = xem.GetWireOutValue(status_addr)
        status = "OK" if occupancy == 0 else "UNEXPECTED"
        print(f"  WireOut {status_addr:#04x} ({fifo_name} occupancy) = {occupancy} "
              f"(expected 0 -- Phase 5 hasn't wired a producer yet)  [{status}]")
        assert occupancy == 0, (
            f"WireOut {status_addr:#04x} reports {occupancy} words queued in {fifo_name}, "
            f"expected 0 since no Phase 5 producer exists yet")


def test_clocking(xem):
    print("\n--- Phase 2 clocking (WireOut 0x23-0x26) ---")
    xem.UpdateWireOuts()
    locked = xem.GetWireOutValue(0x23) & 0x1
    print(f"  MMCM locked (0x23 bit 0) = {locked}")
    assert locked == 1, "clk_wiz_0 is not reporting locked"

    start = {addr: xem.GetWireOutValue(addr) for addr in CLOCK_CHECKS}
    time.sleep(CLOCK_MEASURE_SECONDS)
    xem.UpdateWireOuts()
    end = {addr: xem.GetWireOutValue(addr) for addr in CLOCK_CHECKS}

    for addr, expected_hz in CLOCK_CHECKS.items():
        delta = (end[addr] - start[addr]) & 0xFFFFFFFF  # counters are 32-bit, wrap safely over 1s
        measured_hz = delta / CLOCK_MEASURE_SECONDS
        error = abs(measured_hz - expected_hz) / expected_hz
        status = "OK" if error <= CLOCK_TOLERANCE else "MISMATCH"
        print(f"  WireOut {addr:#04x}: expected ~{expected_hz/1e6:.1f} MHz, "
              f"measured ~{measured_hz/1e6:.2f} MHz (error {error:.1%})  [{status}]")
        assert error <= CLOCK_TOLERANCE, (
            f"clock at WireOut {addr:#04x} measured {measured_hz/1e6:.2f} MHz, "
            f"expected ~{expected_hz/1e6:.1f} MHz")


def test_pipe_in_stub(xem):
    print("\n--- BTPipeIn 0x81 (DDS program, still a discard-everything stub) ---")
    dummy = bytearray(PIPE_BLOCK_SIZE)
    n = xem.WriteToBlockPipeIn(0x81, PIPE_BLOCK_SIZE, dummy)
    status = "OK" if n == PIPE_BLOCK_SIZE else "UNEXPECTED RETURN"
    print(f"  Pipe 0x81: wrote {n} bytes  [{status}]")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} path/to/photon.bit")

    xem = connect(sys.argv[1])
    test_wire_in_leds(xem)
    test_wire_out_echo(xem)
    test_clocking(xem)
    test_pulse_fifo_drain(xem)
    test_sequencer_basic(xem)
    test_manual_override(xem)
    test_pipe_out_empty(xem)
    test_pipe_in_stub(xem)
    print("\nAll checks completed.")
