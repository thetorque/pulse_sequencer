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

Phase 5a note: test_sequencer_basic() writes a minimal 2-word pulse
program (both words all-zero) and confirms the new sequencer FSM runs
it to completion (pulser_sequence_done asserts). Both words are
deliberately all-zero bytes so the test doesn't depend on knowing
pulse_fifo's actual 32-bit-write -> 64-bit-read word-concatenation
order (first write in the low 32 bits vs. the high 32 bits) -- that
convention is assumed (not yet verified against real hardware)
elsewhere but doesn't matter when every byte is zero either way.
Testing an actual non-trivial logic_out pattern requires nailing down
that word order first; see the comment on PULSE_WORD_ORDER_ASSUMED
below.

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

# NOT YET VERIFIED against real hardware: assumed pulse_fifo (32-bit write ->
# 64-bit read) concatenates the first 32-bit pipe write into the RAM word's
# low bits and the second into the high bits, matching Xilinx FIFO
# Generator's documented behavior for asymmetric write-narrower-than-read
# widths. test_sequencer_basic() below only writes all-zero words, so it
# doesn't depend on this being right -- but a future test that checks an
# actual non-zero logic_out pattern will, and should swap the two halves
# below if the observed pattern comes out looking time/logic-swapped.
PULSE_WORD_ORDER_ASSUMED = "low_word_first"


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
    print("\n--- Phase 5a sequencer: run a minimal 2-word program to completion ---")

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

    # Two all-zero 64-bit RAM words (word 0 is never applied per the
    # sequencer's own convention; word 1's time_stamp=0 is the
    # end-of-sequence sentinel) -- all-zero bytes sidestep the unverified
    # PULSE_WORD_ORDER_ASSUMED question entirely, see module docstring.
    program = bytearray(16)
    n = xem.WriteToBlockPipeIn(0x80, PIPE_BLOCK_SIZE, program)
    assert n == PIPE_BLOCK_SIZE, f"WriteToBlockPipeIn returned {n}, expected {PIPE_BLOCK_SIZE}"
    print(f"  Wrote {n} bytes (2 all-zero RAM words) to pipe 0x80  [OK]")

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
    test_pipe_out_empty(xem)
    test_pipe_in_stub(xem)
    print("\nAll checks completed.")
